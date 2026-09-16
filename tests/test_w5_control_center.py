# -*- coding: utf-8 -*-
"""🌊 W5 — مرکز اقدام قابل‌فهم/قابل‌اصلاح + مغایرت انسانی + مرکز مالی.

قرارداد: آیتم‌های کیفیت داده human-readable اند (عنوان + context + missing +
repair)، اصلاح مستقیم rule را دوباره اجرا می‌کند و شمارش از بک‌اند تازه می‌شود؛
مغایرت‌گیری نام/مبلغ/اقدام می‌دهد و «فعال‌سازی امن» با primitive رسمی؛
مرکز مالی aggregate واقعی است. بدون Mongo → Skip (CI)."""
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

TEST_UID = 889501
STUDENT_UID = 889502
TEST_TOKEN = "123456:W21-TEST-TOKEN"

LESSON_OID = OID(f"{301:024x}")
SESSION_OID = OID(f"{302:024x}")
CONTENT_BAD1 = OID(f"{303:024x}")   # متادیتای ناقص → repair
CONTENT_BAD2 = OID(f"{304:024x}")   # ناقص دوم برای شمارش
CONTENT_OK = OID(f"{305:024x}")     # کامل → نباید در لیست باشد
CONTENT_ORPHAN = OID(f"{306:024x}") # session یتیم → attach/remove
ORPHAN_SESS = OID(f"{307:024x}")
PLAN_OID = OID(f"{308:024x}")
PAY_RECON = OID(f"{309:024x}")
U_RECON = 889601


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


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
    user = {"id": uid, "first_name": "W5C", "username": "w5c_test"}
    pairs = {"user": json.dumps(user, separators=(",", ":")),
             "auth_date": str(int(time.time()))}
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode({**pairs, "hash": digest})


class ControlCenterStaticTests(unittest.TestCase):
    """گارد ساختاری: مسیرها، گیت مجوز، سیم‌کشی UI."""

    def setUp(self):
        self.wa = read("api", "routers", "web_admin.py")

    def test_repair_routes_with_perm_gate(self):
        for route in ("/operations/data-quality/files_missing_metadata/{item_id}/repair",
                      "/operations/data-quality/{kind}/{item_id}/attach",
                      "/operations/data-quality/{kind}/{item_id}/remove",
                      "/operations/quality-parents/{parent_kind}",
                      "/subscription/reconcile/{payment_id}/activate",
                      "/subscription/finance"):
            self.assertIn(f'"{route}"', self.wa, route)
        # گیت مجوز روی اقدامها
        idx = self.wa.index("wa_data_quality_repair")
        self.assertIn('_perm("system.manage")', self.wa[idx - 300:idx + 300])
        idx = self.wa.index("wa_reconcile_activate")
        self.assertIn('_perm("subscription.manage")', self.wa[idx - 300:idx + 300])

    def test_no_raw_id_as_headline(self):
        # enrichment عنوان انسانی می‌سازد و ID فقط در technical
        self.assertIn("async def _quality_enrich_items", self.wa)
        self.assertIn('"technical": str(doc.get("_id", ""))', self.wa)

    def test_ui_wired(self):
        api_js = read("webadmin", "src", "api.js")
        for fn in ("dataQualityRepair", "dataQualityAttach", "dataQualityRemove",
                   "dataQualityParents", "subReconcileActivate", "subFinance",
                   "subPaymentTrace", "exportPaymentsCsv"):
            self.assertIn(fn + ":", api_js, fn)
        dash = read("webadmin", "src", "pages", "Dashboard.jsx")
        self.assertIn("attn-group", dash, "گروه‌بندی نیازمند اقدام")
        styles = read("webadmin", "src", "styles.css")
        self.assertIn("trace-timeline", styles, "خط زمانی ردیابی")
        ops = read("webadmin", "src", "pages", "Operations.jsx")
        for token in ("EditMetaForm", "AttachPicker", "تکمیل/ویرایش اطلاعات", "جزئیات فنی"):
            self.assertIn(token, ops, token)
        subs = read("webadmin", "src", "pages", "Subscriptions.jsx")
        for token in ("FinancialPanel", "subReconcileActivate", "مغایرت یعنی چه؟",
                      "فعال‌سازی امن اشتراک"):
            self.assertIn(token, subs, token)

    def test_reconcile_human_summary_backend(self):
        self.assertIn("رسید {who} به مبلغ", self.wa)
        self.assertIn('"summary": text', self.wa)


@unittest.skipUnless(_mongo_available(), "MONGODB_URI محلی در دسترس نیست (CI)")
class ControlCenterRuntimeTests(unittest.TestCase):

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
            "user_id": TEST_UID, "name": "W5C Admin", "role": "admin",
            "approved": True, "suspended": False}}, upsert=True)
        await db.users.update_one({"user_id": STUDENT_UID}, {"$set": {
            "user_id": STUDENT_UID, "name": "W5C Student", "role": "student",
            "approved": True, "suspended": False}}, upsert=True)
        await db.users.update_one({"user_id": U_RECON}, {"$set": {
            "user_id": U_RECON, "name": "رضا کریمی", "student_id": "98001",
            "role": "student", "approved": True, "suspended": False}}, upsert=True)
        await cls._clean()
        await db.bs_lessons.update_one({"_id": LESSON_OID}, {"$set": {
            "name": "فیزیولوژی", "term": 1}}, upsert=True)
        await db.bs_sessions.update_one({"_id": SESSION_OID}, {"$set": {
            "name": "قلب و عروق", "lesson_id": str(LESSON_OID)}}, upsert=True)
        base = {"session_id": str(SESSION_OID), "order": 0}
        await db.bs_content.update_one({"_id": CONTENT_BAD1}, {"$set": {
            **base, "type": "", "description": ""}}, upsert=True)
        await db.bs_content.update_one({"_id": CONTENT_BAD2}, {"$set": {
            **base, "type": "pdf", "description": ""}}, upsert=True)
        await db.bs_content.update_one({"_id": CONTENT_OK}, {"$set": {
            **base, "type": "pdf", "description": "جزوه کامل قلب"}}, upsert=True)
        await db.bs_content.update_one({"_id": CONTENT_ORPHAN}, {"$set": {
            "session_id": str(ORPHAN_SESS), "type": "pdf",
            "description": "فایل یتیم"}}, upsert=True)
        await db.sub_plans.update_one({"_id": PLAN_OID}, {"$set": {
            "name": "ماهانه", "days": 30, "price": 120000}}, upsert=True)
        await db.sub_payments.update_one({"_id": PAY_RECON}, {"$set": {
            "user_id": U_RECON, "plan_id": str(PLAN_OID), "plan_name": "ماهانه",
            "price": 120000, "final_price": 120000, "status": "approved",
            "reviewed_at": "2026-01-02T00:00:00+00:00",
            "submitted_at": "2026-01-01T00:00:00+00:00"}}, upsert=True)

    @classmethod
    async def _clean(cls):
        db = cls.db
        await db.bs_content.delete_many({"_id": {"$in": [
            CONTENT_BAD1, CONTENT_BAD2, CONTENT_OK, CONTENT_ORPHAN]}})
        await db.bs_sessions.delete_many({"_id": {"$in": [SESSION_OID]}})
        await db.bs_lessons.delete_many({"_id": {"$in": [LESSON_OID]}})
        await db.sub_payments.delete_many({"_id": {"$in": [PAY_RECON]}})
        await db.subscriptions.delete_many({"_id": {"$in": [U_RECON]}})
        await db.sub_plans.delete_many({"_id": {"$in": [PLAN_OID]}})

    def _client_ctx(self):
        return self.httpx.AsyncClient(
            transport=self.httpx.ASGITransport(app=self.app), base_url="http://t")

    def test_quality_items_humanized(self):
        async def run():
            async with self._client_ctx() as c:
                r = await c.get("/api/web-admin/operations/data-quality/files_missing_metadata",
                                headers=self.admin_h)
                assert r.status_code == 200, r.text
                data = r.json()
                ids = [i["id"] for i in data["items"]]
                assert str(CONTENT_BAD1) in ids and str(CONTENT_OK) not in ids
                row = next(i for i in data["items"] if i["id"] == str(CONTENT_BAD1))
                # human-readable: عنوان نه ID؛ context واقعی؛ missing دقیق
                assert row["title"] != row["technical"]
                assert "فیزیولوژی" in row["context"] and "قلب و عروق" in row["context"]
                assert "type" in row["missing"] and "description" in row["missing"]
                assert row["repair"]["edit"] is True
                assert data["repair"]["edit"] is True
        self._run(run())

    def test_repair_resolves_and_counts_drop(self):
        async def run():
            async with self._client_ctx() as c:
                before = await c.get("/api/web-admin/operations/data-quality",
                                     headers=self.admin_h)
                n_before = next(i["count"] for i in before.json()["items"]
                                if i["kind"] == "files_missing_metadata")
                r = await c.post(
                    f"/api/web-admin/operations/data-quality/files_missing_metadata/{CONTENT_BAD1}/repair",
                    headers=self.admin_h,
                    json={"name": "فایل فیزیولوژی", "type": "pdf",
                          "description": "جزوه جلسه قلب"})
                assert r.status_code == 200, r.text
                assert r.json()["resolved"] is True
                after = await c.get("/api/web-admin/operations/data-quality/files_missing_metadata",
                                    headers=self.admin_h)
                ids = [i["id"] for i in after.json()["items"]]
                assert str(CONTENT_BAD1) not in ids
                n_after = next(i["count"] for i in (await c.get(
                    "/api/web-admin/operations/data-quality",
                    headers=self.admin_h)).json()["items"]
                    if i["kind"] == "files_missing_metadata")
                assert n_after == n_before - 1
                # audit ثبت شده (مدل audit_logs: target تودرتو است)
                log = await self.db.audit_logs.find_one(
                    {"target.id": str(CONTENT_BAD1), "target.type": "content"})
                assert log and "متادیتا" in (log.get("action") or "")
        self._run(run())

    def test_repair_validation(self):
        async def run():
            async with self._client_ctx() as c:
                url = f"/api/web-admin/operations/data-quality/files_missing_metadata/{CONTENT_BAD2}/repair"
                r = await c.post(url, headers=self.admin_h, json={"type": "exe"})
                assert r.status_code == 422
                r = await c.post(url, headers=self.admin_h, json={"description": "ab"})
                assert r.status_code == 422
                r = await c.post(url, headers=self.admin_h, json={})
                assert r.status_code == 400
        self._run(run())

    def test_orphan_attach_then_remove(self):
        async def run():
            async with self._client_ctx() as c:
                # والد معتبر جست‌وجو می‌شود
                r = await c.get("/api/web-admin/operations/quality-parents/sessions?q=قلب",
                                headers=self.admin_h)
                assert r.status_code == 200
                hits = r.json()["items"]
                assert any(p["id"] == str(SESSION_OID) for p in hits)
                # attach → resolved
                r = await c.post(
                    f"/api/web-admin/operations/data-quality/orphan_files/{CONTENT_ORPHAN}/attach",
                    headers=self.admin_h, json={"parent_id": str(SESSION_OID)})
                assert r.status_code == 200 and r.json()["resolved"] is True
                # حذف تکی بدون confirm ممنوع
                r = await c.post(
                    f"/api/web-admin/operations/data-quality/orphan_files/{CONTENT_OK}/remove",
                    headers=self.admin_h, json={"confirm": False})
                assert r.status_code == 400
                # CONTENT_OK دیگر یتیم نیست → حذفش 409
                r = await c.post(
                    f"/api/web-admin/operations/data-quality/orphan_files/{CONTENT_OK}/remove",
                    headers=self.admin_h, json={"confirm": True})
                assert r.status_code == 409
        self._run(run())

    def test_reconcile_human_and_activate(self):
        async def run():
            async with self._client_ctx() as c:
                r = await c.get("/api/web-admin/subscription/reconcile",
                                headers=self.admin_h)
                assert r.status_code == 200, r.text
                items = r.json()["items"]
                hit = next((i for i in items if i["payment_id"] == str(PAY_RECON)), None)
                assert hit, "مورد مغایرت تأیید-بدون-اشتراک پیدا نشد"
                assert hit["user_name"] == "رضا کریمی"
                assert hit["amount"] == 120000
                # جمله‌ی انسانی: نام کاربر + مبلغ قالب‌بندی‌شده در خلاصه
                assert "رضا کریمی" in hit["summary"]
                assert "120,000" in hit["summary"]
                assert any(a["key"] == "activate" for a in hit["actions"])
                # فعال‌سازی امن
                r = await c.post(
                    f"/api/web-admin/subscription/reconcile/{PAY_RECON}/activate",
                    headers=self.admin_h, json={"confirm": True})
                assert r.status_code == 200, r.text
                sub = await self.db.subscriptions.find_one({"_id": U_RECON})
                assert sub and sub["status"] == "active"
                # تکرار هم‌زمان/دوباره → 409
                r = await c.post(
                    f"/api/web-admin/subscription/reconcile/{PAY_RECON}/activate",
                    headers=self.admin_h, json={"confirm": True})
                assert r.status_code == 409
                # مورد از مغایرت خارج شد
                r = await c.get("/api/web-admin/subscription/reconcile",
                                headers=self.admin_h)
                assert not any(i["payment_id"] == str(PAY_RECON)
                               for i in r.json()["items"])
        self._run(run())

    def test_finance_aggregates(self):
        async def run():
            async with self._client_ctx() as c:
                r = await c.get("/api/web-admin/subscription/finance",
                                headers=self.admin_h)
                assert r.status_code == 200, r.text
                data = r.json()
                assert data["totals"]["approved"]["count"] >= 1
                assert data["revenue_total"] >= 120000
                assert data["success_rate"] is None or 0 <= data["success_rate"] <= 100
        self._run(run())

    def test_forbidden_for_student(self):
        async def run():
            async with self._client_ctx() as c:
                for method, path in (
                        ("get", "/api/web-admin/operations/data-quality"),
                        ("get", "/api/web-admin/subscription/finance"),
                        ("get", "/api/web-admin/subscription/reconcile")):
                    r = await getattr(c, method)(path, headers=self.student_h)
                    assert r.status_code == 403, (path, r.status_code)
        self._run(run())

    def test_payment_trace_and_export(self):
        """§۱۱/۱۳/۸۶ — ردیابی کامل رسید + خروجی CSV کرانه‌دار."""
        async def run():
            async with self._client_ctx() as c:
                r = await c.get(
                    f"/api/web-admin/subscription/payments/{PAY_RECON}/trace",
                    headers=self.admin_h)
                assert r.status_code == 200, r.text
                t = r.json()
                assert t["payment"]["status"] == "approved"
                assert t["user"]["name"] == "رضا کریمی"
                assert "subscription" in t and "refund" in t and "audit" in t
                # §۷۶ پیوند اشتراک به منبع پرداخت
                assert t["payment"]["final_price"] == 120000
                r = await c.get("/api/web-admin/exports/payments.csv",
                                headers=self.admin_h)
                assert r.status_code == 200
                assert "text/csv" in r.headers["content-type"]
                head = r.text.splitlines()[0]
                assert "کاربر" in head and "وضعیت" in head
                assert str(PAY_RECON) in r.text
        self._run(run())

    def test_finance_extras_and_recon_dashboard(self):
        """§۳۷/۸۷ — داشبورد مغایرت (resolved_today) و analytics مالی."""
        async def run():
            async with self._client_ctx() as c:
                r = await c.get("/api/web-admin/subscription/finance",
                                headers=self.admin_h)
                d = r.json()
                assert "revenue_week" in d and "refund_rate" in d
                r = await c.get("/api/web-admin/subscription/reconcile",
                                headers=self.admin_h)
                assert "resolved_today" in r.json()["summary"]
        self._run(run())


if __name__ == "__main__":
    unittest.main(verbosity=2)
