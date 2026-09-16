# -*- coding: utf-8 -*-
"""🌊 موج ۲۱ — Action Center: موتور موجود به محصول تبدیل شد.

دو لایه‌ی تست، مثل بقیه‌ی repo:

۱) گاردهای ایستا — بدون Mongo/تلگرام، در همان job سبک CI اجرا می‌شوند:
   • صفحه‌ی `/actions` در PAGES و ناوبری ثبت شده
   • صفحه‌ی جدید کلاس CSS مرده نمی‌سازد (الگوی `.attention-critical` موج‌های قبل)
   • هر `go:` متادیتای /attention به یک صفحه‌ی ثبت‌شده ختم می‌شود

۲) تست runtime — اولین تست این repo که واقعاً handler را اجرا می‌کند
   (ASGI + Mongo واقعی). در CI بدون Mongo خودبه‌خود Skip می‌شود؛
   در محیط توسعه با `MONGODB_URI` اجرا می‌شود.

نکته‌ی فنی runtime: کلاینت Motor به اولین event loop گره می‌خورد، پس کل
کلاس روی **یک** loop مشترک اجرا می‌شود (نه asyncio.run جدا برای هر تست).
داده‌ی تست پیشوند `w21` دارد و در پایان پاک می‌شود.
"""
import asyncio
import hashlib
import hmac
import json
import os
import re
import socket
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]

TEST_UID = 888001
TEST_TOKEN = "123456:W21-TEST-TOKEN"


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────
#  گاردهای ایستا
# ─────────────────────────────────────────────────────────────

class ActionCenterStaticTests(unittest.TestCase):

    def test_actions_page_registered_and_imported(self):
        app = read("webadmin", "src", "app.jsx")
        self.assertIn("'/actions': Actions", app,
                      "صفحه‌ی مرکز اقدام در PAGES ثبت نشده")
        self.assertIn("const Actions = lazy", app,
                      "lazy import صفحه‌ی Actions حذف شده")
        self.assertIn("path: '/actions'", app,
                      "آیتم ناوبری مرکز اقدام حذف شده")

    def test_actions_page_has_no_dead_css_classes(self):
        """§W21-1 — در موج‌های قبلی کلاس‌هایی مثل `.attention-critical`
        استفاده می‌شد ولی در styles.css نبود (بی‌اثرِ بی‌صدا). این گارد همان
        الگو را برای صفحه‌ی جدید می‌گیرد: بخش ایستای هر className باید در
        styles.css وجود داشته باشد."""
        page = read("webadmin", "src", "pages", "Actions.jsx")
        css = read("webadmin", "src", "styles.css")
        offenders = []
        # ۱) className="..." ساده   ۲) className={`...${...}`} → بخش ایستا
        literals = re.findall(r'className="([^"]+)"', page)
        templates = re.findall(r'className=\{`([^`$]+)', page)
        for chunk in literals + templates:
            for cls in chunk.split():
                if cls and f".{cls}" not in css:
                    offenders.append(cls)
        self.assertEqual([], offenders,
                         f"کلاس CSS مرده در Actions.jsx: {offenders}")

    def test_attention_go_targets_are_registered_pages(self):
        """هر `go:` در متادیتای /attention باید به صفحه‌ای برسد که در PAGES
        ثبت شده (deep-link بی‌مقصد = کارت مرده)."""
        src = read("api", "routers", "web_admin.py")
        meta = re.search(r'meta = \{(.*?)\n    \}', src, re.S)
        self.assertIsNotNone(meta, "ساختار meta در /attention پیدا نشد")
        goes = re.findall(r'"/([a-z-]+)[?"]', meta.group(1))
        app = read("webadmin", "src", "app.jsx")
        routes = set(re.findall(r"'(/[a-z-]+)':", app))
        unknown = [g for g in goes if f"/{g}" not in routes]
        self.assertEqual([], unknown, f"مقصد go ثبت‌نشده در PAGES: {unknown}")


# ─────────────────────────────────────────────────────────────
#  تست runtime (Skip در CI بدون Mongo)
# ─────────────────────────────────────────────────────────────

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
    # امضا باید دقیقاً با توکن سرور (env) باشد — وگرنه 401.
    token = os.environ.setdefault("TELEGRAM_TOKEN", TEST_TOKEN)
    user = {"id": uid, "first_name": "Wave21", "username": "w21_test"}
    pairs = {"user": json.dumps(user, separators=(",", ":")),
             "auth_date": str(int(time.time()))}
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode({**pairs, "hash": digest})


@unittest.skipUnless(_mongo_available(), "MONGODB_URI محلی در دسترس نیست (CI)")
class ActionCenterRuntimeTests(unittest.TestCase):
    """اجرای واقعی endpointها روی FastAPI + Mongo — بدون سرور خارجی."""

    loop = None

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
        cls.headers = {"X-Init-Data": _signed_init_data(TEST_UID)}

        # یک loop مشترک بین همه‌ی کلاس‌های runtime (tests/_rtloop):
        # Motor به اولین loop گره می‌خورد؛ loop دوم یعنی RuntimeError.
        from _rtloop import adopt
        adopt()
        cls._run(cls._prepare())

    @classmethod
    def tearDownClass(cls):
        # loop مشترک را نبند — کلاس‌های runtime بعدی همان را لازم دارند.
        cls._run(cls._clean())

    @classmethod
    def _run(cls, coro):
        from _rtloop import run
        return run(coro)

    @classmethod
    async def _prepare(cls):
        db = cls.db
        await db.users.update_one(
            {"user_id": TEST_UID},
            {"$set": {"user_id": TEST_UID, "name": "Wave21 Tester",
                      "role": "admin", "approved": True, "suspended": False}},
            upsert=True)
        await cls._clean()

    @classmethod
    async def _clean(cls):
        await cls.db.bs_content.delete_many({"_id": {"$regex": "^w21"}})
        await cls.db.bs_sessions.delete_many({"_id": {"$regex": "^w21"}})

    def _client_ctx(self):
        return self.httpx.AsyncClient(
            transport=self.httpx.ASGITransport(app=self.app), base_url="http://t")

    def test_attention_contains_new_queue_cards(self):
        async def run():
            async with self._client_ctx() as c:
                return await c.get("/api/web-admin/attention", headers=self.headers)
        r = self._run(run())
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        keys = {i["key"] for i in payload["items"]}
        for expected in ("outbox_backlog", "outbox_scheduled", "dlq", "data_quality"):
            self.assertIn(expected, keys, f"کارت {expected} در /attention نیست")
        q = [i for i in payload["items"] if i["key"] == "data_quality"][0]
        self.assertIn("detail", q, "کارت کیفیت داده باید خلاصه‌ی severity بدهد")
        self.assertEqual({"count", "critical", "warning", "info", "checked", "top"},
                         set(q["detail"].keys()))

    def test_data_quality_fix_requires_confirm_and_whitelist(self):
        async def run():
            async with self._client_ctx() as c:
                r1 = await c.post(
                    "/api/web-admin/operations/data-quality/orphan_files/fix",
                    headers=self.headers, json={"kind": "orphan_files"})
                r2 = await c.post(
                    "/api/web-admin/operations/data-quality/duplicate_student_ids/fix",
                    headers=self.headers,
                    json={"kind": "duplicate_student_ids", "confirm": True})
            return r1, r2
        r1, r2 = self._run(run())
        self.assertEqual(r1.status_code, 400, "بدون confirm باید 400 باشد")
        self.assertEqual(r2.status_code, 400,
                         "گونه‌ی هویتی عمداً قابل auto-fix نیست")

    def test_fix_deletes_only_true_orphans_and_audits(self):
        from bson import ObjectId
        parent_oid, missing_oid = ObjectId(), ObjectId()

        async def run():
            db = self.db
            # در production اپ همیشه session_id = str(ObjectId) ذخیره می‌کند؛
            # تست هم باید همان شکل داده را بسازد، نه رشته‌ی دلخواه.
            await db.bs_sessions.update_one({"_id": parent_oid}, {"$set": {
                "title": "والد تست"}}, upsert=True)
            await db.bs_content.update_one({"_id": "w21good"}, {"$set": {
                "session_id": str(parent_oid), "title": "سالم", "type": "pdf"}}, upsert=True)
            await db.bs_content.update_one({"_id": "w21orphan"}, {"$set": {
                "session_id": str(missing_oid), "title": "یتیم", "type": "pdf"}}, upsert=True)
            async with self._client_ctx() as c:
                r1 = await c.post(
                    "/api/web-admin/operations/data-quality/orphan_files/fix",
                    headers=self.headers, json={"kind": "orphan_files", "confirm": True})
                r2 = await c.post(
                    "/api/web-admin/operations/data-quality/orphan_files/fix",
                    headers=self.headers, json={"kind": "orphan_files", "confirm": True})
            await db.bs_sessions.delete_one({"_id": parent_oid})
            return (r1.json(), r2.json(),
                    await db.bs_content.find_one({"_id": "w21good"}),
                    await db.bs_content.find_one({"_id": "w21orphan"}),
                    await db.audit_logs.count_documents(
                        {"tags": "کیفیت_داده", "target.id": "orphan_files"}))
        first, second, good, orphan, audits = self._run(run())
        self.assertTrue(first["ok"])
        self.assertGreaterEqual(first["removed"], 1)
        self.assertEqual(second["removed"], 0, "اجرای دوم باید idempotent باشد")
        self.assertIsNone(orphan, "رکورد یتیم باید حذف شده باشد")
        self.assertIsNotNone(good, "رکورد سالمِ دارای والد هرگز نباید حذف شود")
        self.assertGreaterEqual(audits, 1, "اصلاح باید در حسابرسی ثبت شود")

    def test_attention_forbidden_without_any_admin_access(self):
        """کاربر بدون هیچ نقش/مجوزی نباید صف‌ها را ببیند.

        ⚠️ عمداً با uid دوم: TEST_UID همان ADMIN_ID است و بای‌پس مالک دارد،
        پس با او هرگز 403 نمی‌گیریم."""
        student_uid = TEST_UID + 1
        headers = {"X-Init-Data": _signed_init_data(student_uid)}

        async def run():
            db = self.db
            await db.users.update_one(
                {"user_id": student_uid},
                {"$set": {"user_id": student_uid, "name": "W21 Student",
                          "role": "student", "approved": True,
                          "suspended": False}},
                upsert=True)
            await db.user_roles.delete_one({"_id": student_uid})
            await db.admin_roles.delete_one({"_id": student_uid})
            async with self._client_ctx() as c:
                return await c.get("/api/web-admin/attention", headers=headers)
        r = self._run(run())
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
