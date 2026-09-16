# -*- coding: utf-8 -*-
"""🌊 W4 — سخت‌سازی و سلامت دیتابیس: SEC-01/04/05/06/07، DB-02/04، PERF-01.

۱) گارد ایستا: سیم‌کشی همه‌ی آیتم‌ها + نبود رفتار ناامن قدیمی.
۲) runtime با Mongo محلی: ایندکس‌ها، helperهای بچ، retention.

داده با پیشوند w4؛ در پایان پاک می‌شود. loop مشترک (tests/_rtloop).
"""
import os
import socket
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

W4_A = 891101
W4_B = 891102


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


class W4StaticTests(unittest.TestCase):
    """گاردهای ایستای W4."""

    def test_sec01_docs_gated(self):
        src = read("api", "main.py")
        self.assertIn("API_DOCS_ENABLED", src)
        self.assertIn('docs_url="/docs" if _DOCS_ON else None', src)
        self.assertIn('openapi_url="/openapi.json" if _DOCS_ON else None', src)
        # پیش‌فرض امن: خاموش مگر صریح
        self.assertIn('os.getenv("API_DOCS_ENABLED", "0")', src)

    def test_sec04_gateway_perm_migrated(self):
        src = read("api", "routers", "payment_gateway.py")
        self.assertEqual(
            src.count('require_perm("subscription.manage")'), 3)
        self.assertNotIn("get_admin_user", src)

    def test_sec05_callback_encoded(self):
        src = read("api", "routers", "subscription.py")
        idx = src.index('router.get("/zarinpal/callback")')
        block = src[idx:idx + 900]
        self.assertIn("quote(", block)
        self.assertIn("safe=''", block)

    def test_sec06_no_merchant_leak(self):
        src = read("api", "routers", "payment_gateway.py")
        self.assertNotIn("mid[:10]", src)
        # در بدنه‌ی PUT هیچ برش خامی از مرچنت نیست (ماسک فقط داخل _mask)
        put = src[src.index("async def put_zarinpal_cfg"):
                  src.index("@router.post")]
        self.assertNotIn("mid[:", put)
        # نشت قدیمی (کل body در audit) حذف شده؛ فقط مقدار ماسک‌شده
        self.assertNotIn("after=body.model_dump", put)
        self.assertIn("_mask(body.merchant_id)", put)
        # audit فقط masked/cleared می‌بیند، نه خود مرچنت
        self.assertIn('if k != "merchant_id"', src)
        self.assertIn("(cleared)", src)

    def test_sec07_guards_present(self):
        admin = read("api", "routers", "web_admin.py")
        # helper تحمل‌خطا + گاردهای is_valid سر راه ورودی کاربر
        self.assertIn("def _oid(v):", admin)
        self.assertGreaterEqual(admin.count("ObjectId.is_valid"), 8)
        self.assertIn("شناسه کمپین نامعتبر است", admin)
        # DLQ/bulk-delete ورودی خراب را skip می‌کنند، نه ۵۰۰
        self.assertIn("شناسه‌های نامعتبر", admin)
        fin = read("db", "finance.py")
        idx = fin.index("async def sub_plan_get")
        block = fin[idx:idx + 200]
        self.assertIn("except Exception:", block)
        self.assertIn("return None", block)

    def test_db02_retention_scheduled(self):
        src = read("bot.py")
        self.assertIn("async def audit_retention_job", src)
        self.assertIn("name='audit_retention'", src)
        self.assertIn("audit_retention_cleanup", src)
        self.assertIn("audit_log_alert_count", src)

    def test_db04_indexes_added(self):
        src = read("db", "core.py")
        for needle in ("self.ai_conversations,\n                            "
                       "[('user_id', 1), ('updated_at', -1)]",
                       "self.notif_runs,\n                            "
                       "[('job_name', 1), ('started_at', -1)]",
                       "self.user_roles,\n                            "
                       "[('roles', 1)]"):
            self.assertIn(needle, src, f"ایندکس {needle[:30]}… نیست")

    def test_perf01_bulk_reads_batched(self):
        src = read("api", "routers", "web_admin.py")
        self.assertIn("get_users_by_ids(ids)", src)
        self.assertIn("get_users_roles_keys(ids)", src)
        self.assertIn("target = _users.get(uid)", src)
        # دیگر get_user تکی داخل حلقه‌های bulk نیست
        bulk = src[src.index("async def users_bulk_preview"):
                   src.index("WA2.7")]
        self.assertNotIn("await db.get_user(uid)", bulk)
        self.assertNotIn("await db.get_user_roles(uid)", bulk)
        core = read("db", "core.py")
        self.assertIn("async def get_users_by_ids", core)
        rbac = read("db", "rbac.py")
        self.assertIn("async def get_users_roles_keys", rbac)


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
class W4RuntimeTests(unittest.TestCase):
    """ایندکس‌ها، helperهای بچ و retention روی داده‌ی واقعی."""

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
        await cls._clean()
        for uid in (W4_A, W4_B):
            await db.users.update_one(
                {"user_id": uid},
                {"$set": {"user_id": uid, "name": f"W4 {uid}",
                          "role": "student", "approved": True,
                          "suspended": False}},
                upsert=True)
        await db.user_roles.update_one(
            {"_id": W4_A}, {"$set": {"roles": ["w4_r1", "w4_r2"]}},
            upsert=True)
        await db.ensure_indexes()

    @classmethod
    async def _clean(cls):
        db = cls.db
        await db.users.delete_many({"user_id": {"$in": [W4_A, W4_B]}})
        await db.user_roles.delete_many({"_id": {"$in": [W4_A, W4_B]}})
        await db.audit_logs.delete_many({"action": "w4_retention_probe"})

    def test_db04_index_names_exist(self):
        async def go():
            db = self.db
            ai = await db.ai_conversations.index_information()
            self.assertIn("user_id_1_updated_at_-1", ai)
            nr = await db.notif_runs.index_information()
            self.assertIn("job_name_1_started_at_-1", nr)
            ur = await db.user_roles.index_information()
            self.assertIn("roles_1", ur)
        self._run(go())

    def test_perf01_batch_parity(self):
        async def go():
            db = self.db
            users = await db.get_users_by_ids([W4_A, W4_B, 999999999])
            self.assertEqual(set(users), {W4_A, W4_B})
            self.assertEqual(users[W4_A]["name"], f"W4 {W4_A}")
            single = await db.get_user(W4_A, use_cache=False)
            self.assertEqual(users[W4_A]["name"], single["name"])
            keys = await db.get_users_roles_keys([W4_A, W4_B])
            self.assertEqual(sorted(keys[W4_A]), ["w4_r1", "w4_r2"])
            self.assertEqual(keys[W4_B], [])
            single_keys = (await db.get_user_roles(W4_A)).get("keys")
            self.assertEqual(sorted(single_keys), ["w4_r1", "w4_r2"])
        self._run(go())

    def test_db02_retention_deletes_only_old(self):
        async def go():
            import audit as audit_mod
            db = self.db
            now = datetime.now(timezone.utc)
            old_ts = (now - timedelta(days=400)).isoformat()
            new_ts = (now - timedelta(days=10)).isoformat()
            await db.audit_logs.insert_one(
                {"action": "w4_retention_probe", "timestamp": old_ts,
                 "severity": "INFO"})
            await db.audit_logs.insert_one(
                {"action": "w4_retention_probe", "timestamp": new_ts,
                 "severity": "INFO"})
            deleted = await audit_mod.apply_retention(365)
            self.assertGreaterEqual(deleted, 1)
            left = await db.audit_logs.find(
                {"action": "w4_retention_probe"}).to_list(10)
            self.assertEqual(len(left), 1)
            self.assertEqual(left[0]["timestamp"], new_ts)
        self._run(go())


if __name__ == "__main__":
    unittest.main()
