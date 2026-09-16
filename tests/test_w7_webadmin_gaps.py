"""🌊 W7 — رفع شکاف‌های پنل ادمین وب:
۱) مرکز تنظیمات: کلیدهای عملیاتی که سیستم مصرف می‌کرد ولی UI نداشت
   (کارت دریافت، کرانه‌های شارژ، سقف هدیه، محدودیت‌های ضدسوءاستفاده…)
۲) خروجی CSV ledger کیف پول (ردپای مالی)
۳) فیلتر نوع رسید (اشتراک/شارژ/هدیه)

تست‌ها توابع واقعی اندپوینت/کاتالوگ را صدا می‌زنند (نه بازپیاده‌سازی).
الگوی runtime دقیقاً مثل test_wallet_contracts: loop مشترک (_rtloop).
"""
import os
import unittest

_HAS_MONGO_URI = bool(os.environ.get("MONGODB_URI"))

ADMIN_UID = 880701
STUDENT_W7 = 880702


def _read(*parts):
    root = os.path.join(os.path.dirname(__file__), "..")
    with open(os.path.join(root, *parts), encoding="utf-8") as f:
        return f.read()


def _mongo_available() -> bool:
    if not _HAS_MONGO_URI:
        return False
    import socket
    from urllib.parse import urlparse
    u = urlparse(os.environ["MONGODB_URI"])
    try:
        socket.create_connection((u.hostname or "127.0.0.1",
                                  u.port or 27017), 1).close()
        return True
    except OSError:
        return False


@unittest.skipUnless(_mongo_available(), "MongoDB در دسترس نیست (CI)")
class W7RuntimeTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("TELEGRAM_TOKEN", "123:test")
        os.environ["ADMIN_ID"] = str(ADMIN_UID)  # مدیر ارشد = همه‌ی مجوزها
        os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
        from database import db
        cls.db = db
        from api.routers import web_admin
        cls.wa = web_admin
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
        await cls.db.users.update_one(
            {"user_id": ADMIN_UID},
            {"$set": {"user_id": ADMIN_UID, "name": "W7 Admin",
                      "role": "admin", "approved": True,
                      "suspended": False}}, upsert=True)
        await cls.db.users.update_one(
            {"user_id": STUDENT_W7},
            {"$set": {"user_id": STUDENT_W7, "name": "تست W7",
                      "role": "student", "approved": True,
                      "suspended": False}}, upsert=True)

    @classmethod
    async def _clean(cls):
        await cls.db.wallets.delete_many({"user_id": STUDENT_W7})
        await cls.db.wallet_transactions.delete_many(
            {"user_id": STUDENT_W7})
        await cls.db.sub_payments.delete_many({"user_id": STUDENT_W7})
        await cls.db.users.delete_many(
            {"user_id": {"$in": [ADMIN_UID, STUDENT_W7]}})
        # کلید تست‌شده به پیش‌فرض کد برگردد
        await cls.db.set_setting("topup_min", None)

    # ── ۱) مرکز تنظیمات ─────────────────────────────────────────
    def test_catalog_covers_orphan_keys(self):
        keys = {r[0] for _, rows in self.wa._SETTINGS_CATALOG
                for r in rows}
        for k in ("subscription_card_number", "subscription_card_owner",
                  "topup_min", "topup_max", "gift_enabled", "gift_rate_max",
                  "gift_rate_window_h", "report_rate_max",
                  "report_rate_window_min", "url_import_max_mb",
                  "qbank_ai_daily_limit", "qbank_ai_topic_daily_limit",
                  "qbank_weak_min_attempts", "qbank_weak_accuracy_pct",
                  "resource_notif_interval_hours", "poll_channel_id"):
            self.assertIn(k, keys, f"{k} در کاتالوگ تنظیمات نیست")

    def test_patch_number_validation(self):
        from fastapi import HTTPException
        async def run():
            body = self.wa.SettingPatch(value="abc")
            with self.assertRaises(HTTPException) as ctx:
                await self.wa.settings_center_patch(
                    "topup_min", body, user={"id": ADMIN_UID})
            self.assertEqual(ctx.exception.status_code, 422)
            with self.assertRaises(HTTPException):
                await self.wa.settings_center_patch(
                    "topup_min", self.wa.SettingPatch(value="-5"),
                    user={"id": ADMIN_UID})
            await self.wa.settings_center_patch(
                "topup_min", self.wa.SettingPatch(value="15000"),
                user={"id": ADMIN_UID})
            val = await self.db.get_setting("topup_min", None)
            self.assertEqual(int(val), 15000)
        self._run(run())

    def test_center_lists_new_categories(self):
        async def run():
            res = await self.wa.settings_center(user={"id": ADMIN_UID})
            cats = {c["key"] for c in res["categories"]}
            for c in ("finance", "gift", "limits"):
                self.assertIn(c, cats)
        self._run(run())

    # ── ۲) خروجی CSV ledger ──────────────────────────────────────
    def test_wallet_csv_export_contains_ledger(self):
        async def run():
            await self.db.wallets.delete_many({"user_id": STUDENT_W7})
            await self.db.wallet_transactions.delete_many(
                {"user_id": STUDENT_W7})
            await self.db.wallet_credit(STUDENT_W7, 70000, "topup_credit",
                                        "w7test", "csv-1", ADMIN_UID,
                                        "شارژ تست W7")
            resp = await self.wa.wa_export_wallet_csv(
                user_id=STUDENT_W7, status="", user={"id": ADMIN_UID})
            text = resp.body.decode("utf-8")
            self.assertIn("شارژ تست W7", text)
            self.assertIn("w7test:csv-1", text)
            self.assertIn("70000", text)
        self._run(run())

    # ── ۳) فیلتر نوع رسید ────────────────────────────────────────
    def test_payments_kind_filter(self):
        async def run():
            await self.db.sub_payments.delete_many(
                {"user_id": STUDENT_W7})
            pid_top = await self.db.sub_payment_create(
                user_id=STUDENT_W7, plan_id="wallet_topup",
                plan_name="شارژ کیف پول", price=50000,
                final_price=50000, screenshot_file_id="f")
            pid_norm = await self.db.sub_payment_create(
                user_id=STUDENT_W7, plan_id="someplan",
                plan_name="پلن عادی", price=10000, final_price=10000,
                screenshot_file_id="f")
            res_top = await self.wa.wa_subscription_payments(
                status=None, skip=0, limit=100, search=None,
                kind="topup", user={"id": ADMIN_UID, "_db": {}})
            ids_top = [p["id"] for p in res_top["payments"]]
            self.assertIn(pid_top, ids_top)
            self.assertNotIn(pid_norm, ids_top)
            res_norm = await self.wa.wa_subscription_payments(
                status=None, skip=0, limit=100, search=None,
                kind="normal", user={"id": ADMIN_UID, "_db": {}})
            ids_norm = [p["id"] for p in res_norm["payments"]]
            self.assertIn(pid_norm, ids_norm)
            self.assertNotIn(pid_top, ids_norm)
        self._run(run())


class WebadminGapsStaticTests(unittest.TestCase):

    def test_settings_ui_number_type(self):
        s = _read("webadmin", "src", "pages", "Settings.jsx")
        self.assertIn("it.type === 'number'", s)

    def test_wallet_csv_wired(self):
        api_js = _read("webadmin", "src", "api.js")
        self.assertIn("exportWalletCsv:", api_js)
        self.assertIn("/api/web-admin/exports/wallet.csv", api_js)
        wa = _read("api", "routers", "web_admin.py")
        self.assertIn('@router.get("/exports/wallet.csv")', wa)
        sub_jsx = _read("webadmin", "src", "pages", "Subscriptions.jsx")
        self.assertIn("exportWalletCsv(", sub_jsx)

    def test_kind_filter_wired(self):
        wa = _read("api", "routers", "web_admin.py")
        self.assertIn("kind: Optional[str] = Query(None", wa)
        sm = _read("api", "routers", "subscription_management.py")
        self.assertIn('kind == "topup"', sm)
        self.assertIn("wallet_topup", sm)
        sub_jsx = _read("webadmin", "src", "pages", "Subscriptions.jsx")
        self.assertIn("setKind(", sub_jsx)
        self.assertIn("'topup', '💰 شارژ'", sub_jsx)


if __name__ == "__main__":
    unittest.main()
