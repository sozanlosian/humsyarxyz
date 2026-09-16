# -*- coding: utf-8 -*-
"""🌊 GIFT — قرارداد هدیه‌ی اشتراک (خرید برای دانشجوی دیگر).

۱) گارد ایستا: مدل داده روی همان sub_payments (بدون کالکیشن جدید)،
   idempotency، finalize مشترک هر دو مسیر تصمیم، ایندکس‌ها، wiring
   بات/وب‌ادمین/مینی‌اپ.
۲) runtime: چرخه‌ی تأیید هدیه (فعال‌سازی گیرنده + اعلان)، idempotency
   ساخت، لغو pending، retry اعلان، اعتبارسنجی‌های /buy (خود-هدیه،
   گیرنده نامعتبر، feature flag، rate limit) و حریم جست‌وجوی گیرنده.

داده با پیشوند gift و _idهای پایدار؛ در پایان پاک می‌شود. بدون Mongo
→ Skip. loop مشترک (tests/_rtloop) چون Motor به اولین loop گره می‌خورد.
"""
import hashlib
import hmac
import json
import os
import socket
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode

from bson import ObjectId as OID

ROOT = Path(__file__).resolve().parents[1]

ADMIN_UID = 888001
PAYER_UID = 888201
RECIP_UID = 888202
OTHER_UID = 888203
TEST_TOKEN = "123456:W21-TEST-TOKEN"

PLAN_OID = OID(f"{301:024x}")
P_IDEM = OID(f"{311:024x}")     # idempotency ساخت
P_LIFE = OID(f"{312:024x}")     # چرخه‌ی تأیید
P_CANCEL = OID(f"{313:024x}")   # لغو pending
P_RETRY = OID(f"{314:024x}")    # retry اعلان (approved)
P_NONGIFT = OID(f"{315:024x}")  # رسید عادی → cancel باید 422
P_RATE1 = OID(f"{316:024x}")    # هدیه‌ی approved برای تست rate limit
P_SELF = OID(f"{317:024x}")     # خود-هدیه (نباید ساخته شود)


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


class GiftStaticTests(unittest.TestCase):

    def test_model_on_sub_payments_no_new_collection(self):
        """D4 — هدیه روی همان sub_payments: gift{to,message,activated_at}
        + idem_key. هیچ کالکشن جدیدی در core.py ثبت نشده."""
        fin = read("db", "finance.py")
        self.assertIn("gift_to: int = 0", fin)
        self.assertIn("idem_key", fin)
        self.assertIn("async def finalize_approved_payment", fin)
        core = read("db", "core.py")
        self.assertNotIn("self.gifts", core,
                         "کالکشن جداگانه برای هدیه مجاز نیست (D4)")

    def test_idempotency_guard(self):
        fin = read("db", "finance.py")
        idx = fin.index("async def sub_payment_create")
        block = fin[idx:idx + 900]
        self.assertIn("find_one", block,
                      "idem_key باید قبل از insert بررسی شود")
        self.assertIn("idem_key", block)

    def test_finalize_double_activation_guard(self):
        fin = read("db", "finance.py")
        idx = fin.index("async def finalize_approved_payment")
        block = fin[idx:idx + 1600]
        self.assertIn("activated_at", block,
                      "لایه‌ی دوم یک‌باربودن: گارد activated_at")

    def test_both_decide_paths_share_finalize(self):
        web = read("api", "routers", "subscription_management.py")
        bot = read("subscription.py")
        self.assertIn("finalize_approved_payment", web,
                      "decide وب باید از finalize مشترک استفاده کند")
        self.assertIn("finalize_approved_payment", bot,
                      "تأیید ادمین در بات باید از finalize مشترک استفاده کند")

    def test_indexes_registered(self):
        core = read("db", "core.py")
        self.assertIn("('gift.to', 1)", core)
        idx = core.index("self._index(self.sub_payments, 'idem_key'")
        self.assertIn("unique=True", core[idx:idx + 200])
        self.assertIn("sparse=True", core[idx:idx + 200])

    def test_buy_validations_server_side(self):
        src = read("api", "routers", "subscription.py")
        self.assertIn("gift_to: int = Form(0)", src)
        self.assertIn('gift_enabled', src, "feature flag")
        self.assertIn("gift_to == user_id", src, "خود-هدیه")
        self.assertIn("gift_rate_max", src, "rate limit از settings")
        self.assertIn("/gift/recipients", src)
        self.assertIn('"/gifts"', src)

    def test_bot_wiring(self):
        sub = read("subscription.py")
        self.assertIn("sub:gift", sub)
        self.assertIn("gift_recipient_handler", sub)
        self.assertIn("gift_message_handler", sub)
        self.assertIn("sub_gift_to", sub)
        router = read("message_router.py")
        self.assertIn("gift_recipient", router)

    def test_ui_wired(self):
        apijs = read("webadmin", "src", "api.js")
        for fn in ("subGifts", "subGiftCancel", "subGiftRetryNotify"):
            self.assertIn(fn, apijs)
        page = read("webadmin", "src", "pages", "Subscriptions.jsx")
        self.assertIn("هدایا", page)
        self.assertIn("GiftsPanel", page)
        mini = read("miniapp", "src", "pages", "Me", "Subscription.jsx")
        self.assertIn("gift_to", mini)
        self.assertIn("اشتراک هدیه", mini)
        self.assertIn("/api/subscription/gifts", mini)


def _mongo_available() -> bool:
    uri = os.getenv("MONGODB_URI", "")
    if not (uri.startswith("mongodb://127.0.0.1") or uri.startswith("mongodb://localhost")):
        return False
    host, _, port = uri[len("mongodb://"):].partition(":")
    try:
        with socket.create_connection((host, int(port or 27017)), timeout=1):
            return True
    except OSError:
        return False


def _signed_init_data(uid: int) -> str:
    token = os.environ.setdefault("TELEGRAM_TOKEN", TEST_TOKEN)
    user = {"id": uid, "first_name": "Gift", "username": "gift_test"}
    pairs = {"user": json.dumps(user, separators=(",", ":")),
             "auth_date": str(int(time.time()))}
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode({**pairs, "hash": digest})


@unittest.skipUnless(_mongo_available(), "MONGODB_URI محلی در دسترس نیست (CI)")
class GiftRuntimeTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("TELEGRAM_TOKEN", TEST_TOKEN)
        os.environ["ADMIN_ID"] = str(ADMIN_UID)
        os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")

        import httpx
        cls.httpx = httpx
        import api.main as main_mod
        cls.app = main_mod.app
        from database import db
        cls.db = db

        cls.admin_h = {"X-Init-Data": _signed_init_data(ADMIN_UID)}
        cls.payer_h = {"X-Init-Data": _signed_init_data(PAYER_UID)}

        from _rtloop import adopt
        adopt()
        cls._run(cls._prepare())

    @classmethod
    def tearDownClass(cls):
        cls._run(cls._clean())

    @classmethod
    def _run(cls, coro):
        from _rtloop import run
        return run(coro)

    @classmethod
    async def _prepare(cls):
        db = cls.db
        for uid, name, role in ((ADMIN_UID, "Gift Admin", "admin"),
                                (PAYER_UID, "پرداخت‌کننده", "student"),
                                (RECIP_UID, "گیرنده هدیه", "student"),
                                (OTHER_UID, "دیگری", "student")):
            await db.users.update_one({"user_id": uid}, {"$set": {
                "user_id": uid, "name": name, "role": role,
                "approved": True, "suspended": False}}, upsert=True)
        await cls._clean()
        await db.sub_plans.update_one({"_id": PLAN_OID}, {"$set": {
            "name": "پلن هدیه", "price": 150000, "days": 30,
            "active": True}}, upsert=True)
        now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
        base = {"plan_id": str(PLAN_OID), "plan_name": "پلن هدیه",
                "price": 150000, "final_price": 150000,
                "screenshot_file_id": "", "discount_code": None,
                "submitted_at": now}
        docs = [
            {**base, "_id": P_LIFE, "user_id": PAYER_UID, "status": "pending",
             "gift": {"to": RECIP_UID, "message": "موفق باشی", "activated_at": None}},
            {**base, "_id": P_CANCEL, "user_id": OTHER_UID, "status": "pending",
             "gift": {"to": RECIP_UID, "message": "", "activated_at": None}},
            {**base, "_id": P_RETRY, "user_id": PAYER_UID, "status": "approved",
             "gift": {"to": OTHER_UID, "message": "", "activated_at": now}},
            {**base, "_id": P_NONGIFT, "user_id": OTHER_UID, "status": "pending"},
            {**base, "_id": P_RATE1, "user_id": PAYER_UID, "status": "approved",
             "gift": {"to": OTHER_UID, "message": "", "activated_at": now}},
        ]
        for doc in docs:
            await db.sub_payments.update_one({"_id": doc["_id"]},
                                             {"$set": doc}, upsert=True)
        # تنظیمات: هدیه فعال، rate سخت‌گیرانه برای تست ۴۲۹
        await db.set_setting("gift_enabled", "1")
        await db.set_setting("gift_rate_max", "1")
        await db.set_setting("gift_rate_window_h", "24")

    @classmethod
    async def _clean(cls):
        db = cls.db
        await db.sub_payments.delete_many({"_id": {"$in": [
            P_IDEM, P_LIFE, P_CANCEL, P_RETRY, P_NONGIFT, P_RATE1, P_SELF]}})
        await db.sub_plans.delete_one({"_id": PLAN_OID})
        await db.subscriptions.delete_many(
            {"_id": {"$in": [RECIP_UID, OTHER_UID, PAYER_UID]}})
        await db.bot_notifs.delete_many(
            {"type": {"$in": ["gift_activated", "gift_cancelled",
                              "payment_decision"]}})
        await db.settings.update_one(
            {"_id": "global"},
            {"$unset": {"gift_enabled": "", "gift_rate_max": "",
                        "gift_rate_window_h": ""}})

    def _client_ctx(self):
        return self.httpx.AsyncClient(
            transport=self.httpx.ASGITransport(app=self.app), base_url="http://t")

    # ── idempotency ساخت ─────────────────────────────────────
    def test_create_idempotent(self):
        async def run():
            key = "gift-test-idem-1"
            p1 = await self.db.sub_payment_create(
                user_id=PAYER_UID, plan_id=str(PLAN_OID), plan_name="پلن هدیه",
                price=150000, final_price=150000, screenshot_file_id="",
                gift_to=RECIP_UID, gift_message="hi", idem_key=key)
            p2 = await self.db.sub_payment_create(
                user_id=PAYER_UID, plan_id=str(PLAN_OID), plan_name="پلن هدیه",
                price=150000, final_price=150000, screenshot_file_id="",
                gift_to=RECIP_UID, gift_message="hi", idem_key=key)
            count = await self.db.sub_payments.count_documents(
                {"idem_key": key})
            await self.db.sub_payments.delete_one({"_id": OID(p1)})
            return p1, p2, count
        p1, p2, count = self._run(run())
        self.assertEqual(p1, p2, "کلید تکراری باید همان سند را برگرداند")
        self.assertEqual(count, 1, "یک کلید = یک رسید")

    # ── چرخه‌ی تأیید هدیه ────────────────────────────────────
    def test_approve_activates_recipient_once(self):
        async def run():
            async with self._client_ctx() as c:
                r = await c.post(
                    f"/api/subscription-admin/payments/{P_LIFE}/decision",
                    headers=self.admin_h, json={"approved": True, "note": ""})
                pay = await self.db.sub_payments.find_one({"_id": P_LIFE})
                sub = await self.db.subscriptions.find_one({"_id": RECIP_UID})
                payer_sub = await self.db.subscriptions.find_one(
                    {"_id": PAYER_UID})
                notif = await self.db.bot_notifs.find_one(
                    {"type": "gift_activated", "chat_id": RECIP_UID})
                # تصمیم دوباره روی همان رسید → 409
                r2 = await c.post(
                    f"/api/subscription-admin/payments/{P_LIFE}/decision",
                    headers=self.admin_h, json={"approved": True, "note": ""})
                return r, pay, sub, payer_sub, notif, r2
        r, pay, sub, payer_sub, notif, r2 = self._run(run())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(pay["status"], "approved")
        self.assertIsNotNone(pay["gift"]["activated_at"],
                             "gift.activated_at باید ست شود")
        self.assertIsNotNone(sub, "اشتراک گیرنده باید ساخته شود")
        self.assertEqual(sub["status"], "active")
        self.assertEqual(sub["source"], "gift")
        self.assertIsNone(payer_sub,
                          "payer نباید اشتراک بگیرد — هدیه برای گیرنده است")
        self.assertIsNotNone(notif, "اعلان گیرنده باید در outbox باشد")
        self.assertEqual(r2.status_code, 409, "تصمیم دوباره باید 409 شود")

    def test_finalize_second_call_no_extra_days(self):
        """لایه‌ی دوم یک‌باربودن: finalize روی هدیه‌ی فعال‌شده روز اضافه
        نمی‌کند (حتی اگر کسی اشتباهاً دوباره صدایش کند)."""
        async def run():
            from database import db
            pay = await db.sub_payments.find_one({"_id": P_LIFE})
            before = await db.subscriptions.find_one({"_id": RECIP_UID})
            res = await db.finalize_approved_payment(pay, ADMIN_UID)
            after = await db.subscriptions.find_one({"_id": RECIP_UID})
            return res, before, after
        res, before, after = self._run(run())
        self.assertTrue(res.get("already"), "باید already برگرداند")
        self.assertEqual(before["end_date"], after["end_date"],
                         "هیچ روزی نباید اضافه شود")

    # ── لغو pending ──────────────────────────────────────────
    def test_cancel_pending_gift(self):
        async def run():
            async with self._client_ctx() as c:
                r1 = await c.post(
                    f"/api/subscription-admin/gifts/{P_CANCEL}/cancel",
                    headers=self.admin_h)
                r2 = await c.post(
                    f"/api/subscription-admin/gifts/{P_CANCEL}/cancel",
                    headers=self.admin_h)
                r3 = await c.post(
                    f"/api/subscription-admin/gifts/{P_NONGIFT}/cancel",
                    headers=self.admin_h)
                pay = await self.db.sub_payments.find_one({"_id": P_CANCEL})
                return r1, r2, r3, pay
        r1, r2, r3, pay = self._run(run())
        self.assertEqual(r1.status_code, 200, r1.text)
        self.assertEqual(pay["status"], "cancelled")
        self.assertEqual(r2.status_code, 409, "لغو دوباره باید 409 شود")
        self.assertEqual(r3.status_code, 422, "رسید عادی، هدیه نیست")

    # ── retry اعلان ──────────────────────────────────────────
    def test_retry_notify(self):
        async def run():
            async with self._client_ctx() as c:
                r1 = await c.post(
                    f"/api/subscription-admin/gifts/{P_RETRY}/retry-notify",
                    headers=self.admin_h)
                r2 = await c.post(
                    f"/api/subscription-admin/gifts/{P_NONGIFT}/retry-notify",
                    headers=self.admin_h)
                n = await self.db.bot_notifs.count_documents(
                    {"type": "gift_activated", "chat_id": OTHER_UID})
                return r1, r2, n
        r1, r2, n = self._run(run())
        self.assertEqual(r1.status_code, 200, r1.text)
        self.assertEqual(r2.status_code, 422)
        self.assertGreaterEqual(n, 1, "اعلان دوباره باید در outbox باشد")

    # ── اعتبارسنجی‌های /buy (سمت دانشجو) ─────────────────────
    def _buy(self, c, **kw):
        data = {"plan_id": str(PLAN_OID), "discount_code": ""}
        data.update({k: str(v) for k, v in kw.items()})
        return c.post("/api/subscription/buy", headers=self.payer_h,
                      data=data)

    def test_buy_self_gift_rejected(self):
        async def run():
            async with self._client_ctx() as c:
                r = await self._buy(c, gift_to=PAYER_UID)
                return r
        r = self._run(run())
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("خودتان", r.json()["detail"])

    def test_buy_unknown_recipient_rejected(self):
        async def run():
            async with self._client_ctx() as c:
                r = await self._buy(c, gift_to=999999999)
                return r
        r = self._run(run())
        self.assertEqual(r.status_code, 422, r.text)

    def test_buy_rate_limit_and_flag(self):
        async def run():
            async with self._client_ctx() as c:
                # PAYER_UID یک هدیه‌ی approved در بازه دارد؛ max=1 → 429
                r_limit = await self._buy(c, gift_to=RECIP_UID)
                await self.db.set_setting("gift_enabled", "0")
                r_flag = await self._buy(c, gift_to=RECIP_UID)
                await self.db.set_setting("gift_enabled", "1")
                await self.db.set_setting("gift_rate_max", "50")
                r_ok = await self._buy(c, gift_to=RECIP_UID)
                return r_limit, r_flag, r_ok
        r_limit, r_flag, r_ok = self._run(run())
        self.assertEqual(r_limit.status_code, 429, r_limit.text)
        self.assertEqual(r_flag.status_code, 403, r_flag.text)
        # بدون رسید → باید به خطای ۴۲۲ رسید برسد یعنی از گیت‌ها گذشته
        self.assertEqual(r_ok.status_code, 422, r_ok.text)

    # ── حریم جست‌وجوی گیرنده ─────────────────────────────────
    def test_recipients_privacy(self):
        async def run():
            async with self._client_ctx() as c:
                r = await c.get("/api/subscription/gift/recipients",
                                headers=self.payer_h,
                                params={"q": "گیرنده"})
                return r
        r = self._run(run())
        self.assertEqual(r.status_code, 200, r.text)
        items = r.json()["items"]
        self.assertTrue(items, "گیرنده باید پیدا شود")
        for it in items:
            self.assertLessEqual(set(it.keys()), {"user_id", "name", "username"},
                                 "هیچ فیلد شخصی اضافه‌ای مجاز نیست")
        self.assertNotIn(PAYER_UID, [it["user_id"] for it in items],
                         "خودِ payer نباید در نتایج باشد")

    # ── تاریخچه‌ی هدیه (دو طرف) ──────────────────────────────
    def test_gift_history_both_sides(self):
        async def run():
            async with self._client_ctx() as c:
                r_payer = await c.get("/api/subscription/gifts",
                                      headers=self.payer_h)
                recip_h = {"X-Init-Data": _signed_init_data(RECIP_UID)}
                r_recip = await c.get("/api/subscription/gifts",
                                      headers=recip_h)
                return r_payer.json(), r_recip.json()
        payer, recip = self._run(run())
        payer_tos = [g["to"] for g in payer["as_payer"]]
        self.assertIn(RECIP_UID, payer_tos)
        self.assertIn(OTHER_UID, payer_tos)
        rec_froms = [g["from"] for g in recip["as_recipient"]]
        self.assertIn(PAYER_UID, rec_froms)
        for g in recip["as_recipient"]:
            self.assertIn("message", g)

    # ── لیست ادمین ───────────────────────────────────────────
    def test_admin_gifts_list(self):
        async def run():
            async with self._client_ctx() as c:
                r = await c.get("/api/subscription-admin/gifts",
                                headers=self.admin_h,
                                params={"status": "all", "page": 1,
                                        "per_page": 50})
                rf = await c.get("/api/subscription-admin/gifts",
                                 headers=self.admin_h,
                                 params={"status": "pending", "page": 1,
                                         "per_page": 50})
                return r.json(), rf.json()
        allg, pend = self._run(run())
        ids = [it["id"] for it in allg["items"]]
        self.assertIn(str(P_LIFE), ids)
        self.assertIn(str(P_CANCEL), ids)
        self.assertNotIn(str(P_NONGIFT), ids, "رسید عادی در لیست هدیه نیست")
        self.assertTrue(all(it["status"] == "pending" for it in pend["items"]))
        self.assertLessEqual(len(allg["items"]), 50)


if __name__ == "__main__":
    unittest.main(verbosity=2)
