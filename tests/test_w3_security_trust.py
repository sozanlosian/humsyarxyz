# -*- coding: utf-8 -*-
"""🌊 W3 — امنیت و اعتماد: SEC-02/03، BUG-06/07، MISS-02، overrun تخفیف، unwrap کیف پول.

۱) گارد ایستا: سیم‌کشی همه‌ی آیتم‌ها + نبود رفتار قدیمی (fail-open / 409 تخفیف).
۲) بدون DB: reverse در mock + رفتار 429 ریت‌لیمیتر.
۳) runtime با Mongo محلی: fail-closed سقف روزانه، op_claim + takeover،
   helperهای پرچم overrun/reversal، کوئری آشکارساز مغایرت.

داده با پیشوند w3؛ در پایان پاک می‌شود. loop مشترک (tests/_rtloop).
"""
import asyncio
import os
import socket
import time
import unittest
from pathlib import Path

from bson import ObjectId as OID

ROOT = Path(__file__).resolve().parents[1]

W3_UID = 890101
P_W3_OVERRUN = OID(f"{401:024x}")
P_W3_REVERSAL = OID(f"{402:024x}")


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


class W3StaticTests(unittest.TestCase):
    """گاردهای ایستای W3."""

    def test_sec02_fail_closed(self):
        src = read("db", "wallet.py")
        self.assertIn("daily_limit_unavailable", src)
        self.assertIn("logger.critical", src)
        # هیچ except خالی در مسیر سقف روزانه نمانده
        idx = 0
        for _ in range(2):
            idx = src.index("_wallet_daily_toman_sum", idx) + 10
        block = src[src.rindex("if tx_type in (TX_ADMIN_CREDIT", 0, idx):
                    idx + 700]
        self.assertNotIn("except Exception:\n                pass", block)
        admin = read("api", "routers", "web_admin.py")
        self.assertIn('"daily_limit_exceeded"', admin)
        self.assertIn('"daily_limit_unavailable"', admin)

    def test_sec03_dedicated_caps(self):
        cases = [
            (("api", "routers", "registration.py"), '"register", 5, 600'),
            (("api", "routers", "tickets.py"), '"ticket_create", 10, 60'),
            (("api", "routers", "tickets.py"), '"ticket_reply", 30, 60'),
            (("api", "routers", "reports.py"), '"report_create", 10, 60'),
            (("api", "routers", "questions.py"), '"q_answer", 100, 60'),
            (("api", "routers", "questions.py"), '"ai_generate", 10, 60'),
            (("api", "routers", "url_import.py"), '"urlimport_job", 30, 60'),
            (("api", "routers", "references.py"), '"ref_download", 60, 60'),
        ]
        for parts, needle in cases:
            src = read(*parts)
            self.assertIn("rate_limit_user", src, f"{parts[-1]} ایمپورت ندارد")
            self.assertIn(needle, src, f"{parts[-1]} سقف {needle} را ندارد")
        main = read("api", "main.py")
        self.assertIn("_rl_check_global", main)

    def test_bug07_claims_present(self):
        src = read("api", "routers", "subscription_management.py")
        self.assertIn('"sub_grant"', src)
        self.assertIn('"sub_grant_bulk"', src)
        self.assertIn("async def op_claim", read("db", "finance.py"))
        fin = read("db", "finance.py")
        idx = fin.index("async def op_claim")
        self.assertIn("modified_count", fin[idx:idx + 1500])
        # وب‌ادمین همان مسیر ادعادار را صدا می‌زند، نه منطق جدا
        admin = read("api", "routers", "web_admin.py")
        self.assertIn("subscription_api.grant_subscription(body=body, admin=user)", admin)
        self.assertIn("subscription_api.grant_subscription_bulk(body=body, admin=user)", admin)

    def test_bug06_webhook_warning(self):
        src = read("bot.py")
        self.assertIn("NOT supported on", src)
        self.assertIn("docs/runbook.md", src)

    def test_miss02_reverse_wired(self):
        pay = read("payments", "zarinpal.py")
        self.assertIn("async def zarinpal_reverse", pay)
        self.assertIn("reverse.json", pay)
        bot = read("bot.py")
        self.assertIn("zarinpal_reverse", bot)
        self.assertIn("zarinpal_reversed", bot)
        admin = read("api", "routers", "web_admin.py")
        self.assertIn("sub_payment_mark_gateway_reversal", admin)
        self.assertIn('"gateway_reversal": gateway_reversal', admin)
        modal = read("webadmin", "src", "pages", "Subscriptions.jsx")
        self.assertIn("gateway_reversal", modal)
        self.assertIn("manual_required", modal)

    def test_overrun_approve_not_fail(self):
        src = read("api", "routers", "subscription.py")
        self.assertIn("discount_overrun", src)
        self.assertIn("sub_payment_mark_discount_overrun", src)
        # رفتار قدیمی (fail بعد از پول قطعی) حذف شده
        self.assertNotIn("ظرفیت کد تخفیف پر شده", src)
        bot = read("subscription.py")
        self.assertIn("sub_payment_mark_discount_overrun", bot)
        admin = read("api", "routers", "web_admin.py")
        self.assertIn('"approved_discount_overrun"', admin)

    def test_wallet_unwrap_fixed(self):
        sub = read("miniapp", "src", "pages", "Me", "Subscription.jsx")
        self.assertIn(
            "api.get('/api/subscription/wallet').then((r) => r.data)", sub)
        self.assertIn("r?.data?.items", sub)
        prof = read("miniapp", "src", "pages", "Me", "Profile.jsx")
        self.assertIn(
            "api.get('/api/subscription/wallet').then((r) => r.data)", prof)


class W3MockTests(unittest.TestCase):
    """بدون DB: reverse در mock + رفتار 429."""

    @classmethod
    def setUpClass(cls):
        import payments.zarinpal as zp
        cls.zp = zp
        zp._CFG_CACHE["at"] = time.time()
        zp._CFG_CACHE["data"] = {
            "merchant_id": "", "sandbox": True,
            "callback_base": "", "enabled": True,
        }

    @classmethod
    def tearDownClass(cls):
        cls.zp._clear_cfg_cache()

    def test_mock_reverse_roundtrip(self):
        async def go():
            req = await self.zp.zarinpal_request(
                50000, "تست W3", "https://x.test/payment/verify")
            rev = await self.zp.zarinpal_reverse(req["authority"])
            self.assertTrue(rev.get("ok"))
            self.assertEqual(rev.get("code"), 100)
            self.assertTrue(rev.get("mock"))
        asyncio.run(go())

    def test_rate_limiter_returns_429_with_retry_after(self):
        import api.rate_limit as rl
        prev, rl._ENABLED = rl._ENABLED, True
        scope = f"w3test-{time.time_ns()}"
        try:
            async def go():
                from fastapi import HTTPException
                await rl.rate_limit_user(890199, scope, 2, 60)
                await rl.rate_limit_user(890199, scope, 2, 60)
                with self.assertRaises(HTTPException) as ctx:
                    await rl.rate_limit_user(890199, scope, 2, 60)
                self.assertEqual(ctx.exception.status_code, 429)
                self.assertIn("Retry-After", ctx.exception.headers or {})
            asyncio.run(go())
        finally:
            rl._ENABLED = prev
            rl._store.pop(f"u:890199:{scope}", None)


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


@unittest.skipUnless(_mongo_available(), "MONGODB_URI محلی در دسترس نیست (CI)")
class W3RuntimeTests(unittest.TestCase):
    """fail-closed، op_claim، پرچم‌ها و آشکارساز روی داده‌ی واقعی."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
        from database import db
        cls.db = db
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
        await db.users.update_one(
            {"user_id": W3_UID},
            {"$set": {"user_id": W3_UID, "name": "W3 Tester",
                      "role": "student", "approved": True,
                      "suspended": False}},
            upsert=True)
        await cls._clean()

    @classmethod
    async def _clean(cls):
        db = cls.db
        await db.sub_payments.delete_many(
            {"_id": {"$in": [P_W3_OVERRUN, P_W3_REVERSAL]}})
        await db.admin_op_locks.delete_many(
            {"_id": {"$regex": "^w3test:"}})
        await db.wallet_transactions.delete_many(
            {"ref_id": {"$regex": "^w3-"}})
        await db.wallets.delete_many({"user_id": W3_UID})

    def test_sec02_cap_error_blocks_admin_credit(self):
        async def go():
            from db.wallet import WalletError
            db = self.db
            real = db._wallet_daily_toman_sum

            async def boom(_uid):
                raise RuntimeError("w3 sim DB error")
            db._wallet_daily_toman_sum = boom
            try:
                with self.assertRaises(WalletError) as ctx:
                    await db.wallet_credit(
                        W3_UID, 1000, "admin_credit",
                        "w3test", "w3-failclosed", 1, "w3")
                self.assertEqual(ctx.exception.code,
                                 "daily_limit_unavailable")
                # هیچ تراکنشی نباید نوشته شده باشد
                n = await db.wallet_transactions.count_documents(
                    {"ref_id": "w3-failclosed"})
                self.assertEqual(n, 0)
            finally:
                db._wallet_daily_toman_sum = real
        self._run(go())

    def test_bug07_claim_and_takeover(self):
        async def go():
            db = self.db
            key = f"w3test:{time.time_ns()}"
            self.assertTrue(await db.op_claim("w3test", key, ttl_seconds=120))
            self.assertFalse(await db.op_claim("w3test", key, ttl_seconds=120))
            # قفل منقضی قابل تصاحب است (بدون انتظار TTL واقعی)
            past = time.time() - 3600
            import datetime
            await db.admin_op_locks.update_one(
                {"_id": f"w3test:{key}"},
                {"$set": {"expires_at": datetime.datetime.fromtimestamp(
                    past, tz=datetime.timezone.utc)}})
            self.assertTrue(await db.op_claim("w3test", key, ttl_seconds=120))
        self._run(go())

    def test_overrun_and_reversal_markers(self):
        async def go():
            db = self.db
            await db.sub_payments.insert_one({
                "_id": P_W3_OVERRUN, "user_id": W3_UID,
                "plan_id": "w3-plan", "plan_name": "w3",
                "price": 100000, "final_price": 90000,
                "method": "zarinpal", "status": "approved",
                "zarinpal_authority": "TEST-W3-OVERRUN",
                "zarinpal_ref_id": "W3R1", "discount_code": "W3X",
                "reviewed_at": "2026-09-10T00:00:00+00:00",
                "submitted_at": "2026-09-10T00:00:00+00:00",
            })
            self.assertTrue(await db.sub_payment_mark_discount_overrun(
                "TEST-W3-OVERRUN"))
            # همان کوئری آشکارساز مغایرت‌گیری باید پیدایش کند
            found = await db.sub_payments.find_one(
                {"status": "approved", "discount_overrun": True,
                 "_id": P_W3_OVERRUN})
            self.assertIsNotNone(found)
            await db.sub_payments.insert_one({
                "_id": P_W3_REVERSAL, "user_id": W3_UID,
                "plan_id": "w3-plan", "plan_name": "w3",
                "price": 50000, "final_price": 50000,
                "method": "zarinpal", "status": "refunded",
                "zarinpal_authority": "TEST-W3-REV",
                "zarinpal_ref_id": "W3R2",
                "submitted_at": "2026-09-10T00:00:00+00:00",
            })
            self.assertTrue(await db.sub_payment_mark_gateway_reversal(
                str(P_W3_REVERSAL)))
            doc = await db.sub_payments.find_one({"_id": P_W3_REVERSAL})
            self.assertEqual(doc.get("gateway_reversal"), "manual_required")
        self._run(go())


if __name__ == "__main__":
    unittest.main()
