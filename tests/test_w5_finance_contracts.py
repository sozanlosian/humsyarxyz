# -*- coding: utf-8 -*-
"""🌊 W5 (WA23) — Finance Completeness: بازگشت وجه + مغایرت‌گیری.

۱) گارد ایستا: روت‌ها با گیت `subscription.manage`، helper اتمیک در
   db/finance.py، wiring کلاینت.
۲) runtime: چرخه‌ی refund (confirm/دلیل/اتمیکی/audit)، revoke اختیاری،
   و پرچم‌های مغایرت‌گیری روی داده‌ی واقعی. بدون Mongo → Skip.

داده با پیشوند w5 و _idهای پایدار؛ در پایان پاک می‌شود. loop مشترک
(tests/_rtloop) چون Motor به اولین loop گره می‌خورد.
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

TEST_UID = 888001
STUDENT_UID = 888002
TEST_TOKEN = "123456:W21-TEST-TOKEN"

P_REFUND = OID(f"{201:024x}")     # approved، بدون اشتراک → چرخه‌ی refund
P_PENDING = OID(f"{202:024x}")    # pending → refund باید 409
P_REVOKE = OID(f"{203:024x}")     # approved + اشتراک فعال → refund+revoke
P_RECON_A = OID(f"{204:024x}")    # approved بدون اشتراک → پرچم (a)
P_RECON_OLD = OID(f"{205:024x}")  # pending قدیمی → پرچم (d)
P_HEALTHY = OID(f"{206:024x}")    # approved + اشتراک فعال → بدون پرچم
U_REFUND, U_REVOKE, U_RECON_A, U_RECON_B, U_RECON_OLD, U_HEALTHY = (
    888101, 888103, 888110, 888111, 888112, 888113)


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


class FinanceStaticTests(unittest.TestCase):

    def test_routes_with_perm_gate(self):
        src = read("api", "routers", "web_admin.py")
        for route in ('@router.post("/subscription/payments/{payment_id}/refund")',
                      '@router.get("/subscription/reconcile")'):
            self.assertIn(route, src, f"روت {route} ثبت نشده")
            idx = src.index(route)
            self.assertIn('_perm("subscription.manage")', src[idx:idx + 300],
                          f"روت {route} گیت subscription.manage ندارد")

    def test_refund_helper_is_atomic(self):
        fin = read("db", "finance.py")
        self.assertIn("async def sub_payment_refund", fin)
        idx = fin.index("async def sub_payment_refund")
        block = fin[idx:idx + 900]
        self.assertIn("'status': 'approved'", block,
                      "گذار refund باید اتمیک باشد (شرط داخل update)")
        self.assertIn("modified_count == 1", block)

    def test_ui_wired(self):
        apijs = read("webadmin", "src", "api.js")
        self.assertIn("subRefund", apijs)
        self.assertIn("subReconcile", apijs)
        page = read("webadmin", "src", "pages", "Subscriptions.jsx")
        self.assertIn("مغایرت‌گیری", page)
        self.assertIn("بازگشت وجه", page)


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
    user = {"id": uid, "first_name": "W5", "username": "w5_test"}
    pairs = {"user": json.dumps(user, separators=(",", ":")),
             "auth_date": str(int(time.time()))}
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode({**pairs, "hash": digest})


@unittest.skipUnless(_mongo_available(), "MONGODB_URI محلی در دسترس نیست (CI)")
class FinanceRuntimeTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("TELEGRAM_TOKEN", TEST_TOKEN)
        os.environ["ADMIN_ID"] = str(TEST_UID)
        os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")

        import httpx
        cls.httpx = httpx
        import api.main as main_mod
        cls.app = main_mod.app
        from database import db
        cls.db = db
        cls.admin_h = {"X-Init-Data": _signed_init_data(TEST_UID)}
        cls.student_h = {"X-Init-Data": _signed_init_data(STUDENT_UID)}

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
        await db.users.update_one({"user_id": TEST_UID}, {"$set": {
            "user_id": TEST_UID, "name": "W5 Tester", "role": "admin",
            "approved": True, "suspended": False}}, upsert=True)
        await db.users.update_one({"user_id": STUDENT_UID}, {"$set": {
            "user_id": STUDENT_UID, "name": "W5 Student", "role": "student",
            "approved": True, "suspended": False}}, upsert=True)
        await cls._clean()
        base = {"plan_name": "ماهانه", "final_price": 120000,
                "user_name": "تست مالی",
                "submitted_at": "2026-01-01T00:00:00+00:00"}
        for oid, uid, status in ((P_REFUND, U_REFUND, "approved"),
                                 (P_PENDING, U_REFUND, "pending"),
                                 (P_REVOKE, U_REVOKE, "approved"),
                                 (P_RECON_A, U_RECON_A, "approved"),
                                 (P_RECON_OLD, U_RECON_OLD, "pending"),
                                 (P_HEALTHY, U_HEALTHY, "approved")):
            doc = {**base, "_id": oid, "user_id": uid, "status": status}
            if status == "approved":
                doc["reviewed_by"] = TEST_UID
                doc["reviewed_at"] = "2026-01-02T00:00:00+00:00"
            if oid == P_RECON_OLD:
                doc["submitted_at"] = "2025-12-01T00:00:00+00:00"
            await db.sub_payments.update_one({"_id": oid},
                                             {"$set": doc}, upsert=True)
        # اشتراک فعال برای U_REVOKE و U_HEALTHY؛ فعالِ بی‌پرداخت برای U_RECON_B
        for uid in (U_REVOKE, U_HEALTHY, U_RECON_B):
            await db.subscriptions.update_one({"_id": uid}, {"$set": {
                "status": "active", "plan_name": "ماهانه",
                "source": "payment", "end_date": "2027-01-01T00:00:00+00:00",
                "start_date": "2026-01-01T00:00:00+00:00"}}, upsert=True)

    @classmethod
    async def _clean(cls):
        await cls.db.sub_payments.delete_many(
            {"_id": {"$in": [P_REFUND, P_PENDING, P_REVOKE, P_RECON_A,
                             P_RECON_OLD, P_HEALTHY]}})
        await cls.db.subscriptions.delete_many(
            {"_id": {"$in": [U_REVOKE, U_HEALTHY, U_RECON_B]}})
        await cls.db.bot_notifs.delete_many({"type": "event:refund"})

    def _client_ctx(self):
        return self.httpx.AsyncClient(
            transport=self.httpx.ASGITransport(app=self.app), base_url="http://t")

    def test_refund_lifecycle(self):
        async def run():
            async with self._client_ctx() as c:
                r1 = await c.post(
                    f"/api/web-admin/subscription/payments/{P_REFUND}/refund",
                    headers=self.admin_h, json={"confirm": False,
                                                "reason": "تست"})
                r2 = await c.post(
                    f"/api/web-admin/subscription/payments/{P_REFUND}/refund",
                    headers=self.admin_h, json={"confirm": True, "reason": "ab"})
                r3 = await c.post(
                    f"/api/web-admin/subscription/payments/{P_REFUND}/refund",
                    headers=self.admin_h,
                    json={"confirm": True, "reason": "اشتباه اداری"})
                r4 = await c.post(
                    f"/api/web-admin/subscription/payments/{P_REFUND}/refund",
                    headers=self.admin_h,
                    json={"confirm": True, "reason": "دوباره"})
                doc = await self.db.sub_payments.find_one({"_id": P_REFUND})
                audits = await self.db.audit_logs.count_documents(
                    {"tags": "بازگشت_وجه", "target.id": str(P_REFUND)})
            return r1, r2, r3, r4, doc, audits
        r1, r2, r3, r4, doc, audits = self._run(run())
        self.assertEqual(r1.status_code, 400, "بدون confirm باید 400")
        self.assertEqual(r2.status_code, 400, "دلیل کوتاه باید 400")
        self.assertEqual(r3.status_code, 200, r3.text)
        self.assertTrue(r3.json()["ok"])
        self.assertFalse(r3.json()["revoked_subscription"])
        self.assertEqual(r4.status_code, 409, "refund دوم باید 409 اتمیک")
        self.assertEqual(doc["status"], "refunded")
        self.assertEqual(doc["refund_reason"], "اشتباه اداری")
        self.assertGreaterEqual(audits, 1, "بازگشت وجه باید audit بحرانی داشته باشد")

    def test_refund_pending_rejected(self):
        async def run():
            async with self._client_ctx() as c:
                return await c.post(
                    f"/api/web-admin/subscription/payments/{P_PENDING}/refund",
                    headers=self.admin_h,
                    json={"confirm": True, "reason": "تست"})
        r = self._run(run())
        self.assertEqual(r.status_code, 409, "رسید pending قابل refund نیست")

    def test_refund_with_revoke(self):
        async def run():
            async with self._client_ctx() as c:
                r = await c.post(
                    f"/api/web-admin/subscription/payments/{P_REVOKE}/refund",
                    headers=self.admin_h,
                    json={"confirm": True, "reason": "برگشت با revoke",
                          "revoke_subscription": True})
                sub = await self.db.subscriptions.find_one({"_id": U_REVOKE})
            return r, sub
        r, sub = self._run(run())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["revoked_subscription"])
        self.assertEqual(sub["status"], "revoked")
        self.assertIn("بازگشت وجه", sub.get("revoke_reason", ""))

    def test_reconcile_flags(self):
        async def run():
            async with self._client_ctx() as c:
                return await c.get("/api/web-admin/subscription/reconcile",
                                   headers=self.admin_h)
        r = self._run(run())
        self.assertEqual(r.status_code, 200)
        items = r.json()["items"]
        types_by_user = {(i["type"], i["user_id"]) for i in items}
        self.assertIn(("approved_no_active_sub", U_RECON_A), types_by_user)
        self.assertIn(("active_sub_no_approved_payment", U_RECON_B), types_by_user)
        self.assertIn(("pending_stale", U_RECON_OLD), types_by_user)
        self.assertNotIn(("approved_no_active_sub", U_HEALTHY), types_by_user,
                         "کاربر سالم نباید پرچم بخورد")
        s = r.json()["summary"]
        self.assertGreaterEqual(s["total"], 3)

    def test_forbidden_for_student(self):
        async def run():
            async with self._client_ctx() as c:
                r1 = await c.get("/api/web-admin/subscription/reconcile",
                                 headers=self.student_h)
                r2 = await c.post(
                    f"/api/web-admin/subscription/payments/{P_REFUND}/refund",
                    headers=self.student_h,
                    json={"confirm": True, "reason": "تست"})
            return r1, r2
        r1, r2 = self._run(run())
        self.assertEqual(r1.status_code, 403)
        self.assertEqual(r2.status_code, 403)


if __name__ == "__main__":
    unittest.main()
