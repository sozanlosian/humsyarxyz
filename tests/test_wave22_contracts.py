# -*- coding: utf-8 -*-
"""🌊 موج ۲۲ — Question Health + Question 360.

دو لایه، مثل بقیه‌ی repo:

۱) گاردهای ایستا (CI سبک): روت‌ها با گیت مجوز ثبت شده‌اند، کلاینت وصل است،
   و صفحه‌ی سؤال‌ها wiring دارد.
۲) تست runtime (ASGI + Mongo واقعی): محاسبه‌ی امتیاز سلامت از سیگنال‌های
   واقعی، ترتیب بدترین‌اول، بخش‌های ۳۶۰، و RBAC. بدون Mongo خودبه‌خود Skip.

داده‌ی تست پیشوند `w22` دارد و در پایان پاک می‌شود. یک loop مشترک برای کل
کلاس (Motor به اولین loop گره می‌خورد).
"""
import asyncio
import hashlib
import hmac
import json
import os
import socket
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]

TEST_UID = 888001
STUDENT_UID = 888002
TEST_TOKEN = "123456:W21-TEST-TOKEN"


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


# ─────────────────────────────────────────────
#  گاردهای ایستا
# ─────────────────────────────────────────────

class QuestionHealthStaticTests(unittest.TestCase):

    def test_routes_registered_with_perm_gate(self):
        src = read("api", "routers", "web_admin.py")
        for route in ('@router.get("/questions/health")',
                      '@router.get("/questions/{qid}/360")'):
            self.assertIn(route, src, f"روت {route} ثبت نشده")
        for route in ('@router.get("/questions/health")',
                      '@router.get("/questions/{qid}/360")'):
            idx = src.index(route)
            self.assertIn(
                '_perm_any("questions.review", "questions.review_scoped")',
                src[idx:idx + 500],
                f"روت {route} گیت مجوز questions.review ندارد")

    def test_health_reuses_existing_signals_not_new_collections(self):
        """سلامت باید روی داده‌ی موجود باشد نه کالکیشن اختراعی."""
        src = read("api", "routers", "web_admin.py")
        idx = src.index('_HEALTH_MIN_ATTEMPTS')
        block = src[idx:idx + 9000]
        self.assertIn("attempt_count", block)
        self.assertIn("content_reports", block)
        self.assertIn("exam_sessions", block)
        self.assertNotIn("create_collection", block)

    def test_ui_wired(self):
        apijs = read("webadmin", "src", "api.js")
        self.assertIn("questionHealth", apijs)
        self.assertIn("question360", apijs)
        page = read("webadmin", "src", "pages", "Questions.jsx")
        self.assertIn("سلامت سؤال‌ها", page, "دکمه‌ی صفحه‌ی سلامت نیست")
        self.assertIn("نمای ۳۶۰ سؤال", page, "درایور ۳۶۰ نیست")

    def test_questions_page_has_no_dead_css_classes(self):
        """همان گارد موج ۲۱: بخش ایستای هر className باید در styles.css باشد."""
        import re
        page = read("webadmin", "src", "pages", "Questions.jsx")
        css = read("webadmin", "src", "styles.css")
        offenders = []
        chunks = re.findall(r'className="([^"]+)"', page)
        chunks += re.findall(r'className=\{`([^`$]+)', page)
        for chunk in chunks:
            for cls in chunk.split():
                if cls and f".{cls}" not in css:
                    offenders.append(cls)
        self.assertEqual([], offenders, f"کلاس CSS مرده: {offenders}")


# ─────────────────────────────────────────────
#  runtime
# ─────────────────────────────────────────────

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
    user = {"id": uid, "first_name": "Wave22", "username": "w22_test"}
    pairs = {"user": json.dumps(user, separators=(",", ":")),
             "auth_date": str(int(time.time()))}
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode({**pairs, "hash": digest})


@unittest.skipUnless(_mongo_available(), "MONGODB_URI محلی در دسترس نیست (CI)")
class QuestionHealthRuntimeTests(unittest.TestCase):
    """اجرای واقعی endpointهای WA22 روی FastAPI + Mongo."""

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
        cls.admin_h = {"X-Init-Data": _signed_init_data(TEST_UID)}
        cls.student_h = {"X-Init-Data": _signed_init_data(STUDENT_UID)}

        # loop مشترک runtime — ببین tests/_rtloop
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
            {"user_id": TEST_UID},
            {"$set": {"user_id": TEST_UID, "name": "Wave22 Tester",
                      "role": "admin", "approved": True, "suspended": False}},
            upsert=True)
        await db.users.update_one(
            {"user_id": STUDENT_UID},
            {"$set": {"user_id": STUDENT_UID, "name": "Wave22 Student",
                      "role": "student", "approved": True, "suspended": False}},
            upsert=True)
        await cls._clean()
        base = {"options": ["الف", "ب", "ج", "د"], "correct_answer": 0,
                "difficulty": "medium", "lesson": "L22", "topic": "T22",
                "approved": True, "status": "approved", "intake": "",
                "source": "manual", "creator_id": 7,
                "created_at": "2026-01-01T00:00:00+00:00"}
        # w22a: نرخ غلط ۸۰٪ + بدون توضیح ⇒ ۴۵+۴۵+۱۰=۵۵ (بدون گزارش)
        await db.questions.update_one({"_id": "w22a"}, {"$set": {
            **base, "question": "سؤال ناسالم موج ۲۲ الف",
            "attempt_count": 10, "correct_count": 2, "explanation": "",
            "content_hash": "w22hash-a"}}, upsert=True)
        # w22b: سالم ولی یک گزارش باز ⇒ ۴۵
        await db.questions.update_one({"_id": "w22b"}, {"$set": {
            **base, "question": "سؤال گزارش‌دار موج ۲۲ ب",
            "attempt_count": 10, "correct_count": 9, "explanation": "چون ب",
            "content_hash": "w22hash-b"}}, upsert=True)
        # w22c: بدون سیگنال ⇒ باید از لیست پیش‌فرض غایب باشد
        await db.questions.update_one({"_id": "w22c"}, {"$set": {
            **base, "question": "سؤال سالم موج ۲۲ ج",
            "attempt_count": 0, "correct_count": 0, "explanation": "x",
            "content_hash": "w22hash-c"}}, upsert=True)
        await db.content_reports.update_one({"_id": "w22r1"}, {"$set": {
            "target_type": "question", "target_id": "w22b",
            "reason": "wrong_answer", "note": "تست", "status": "new",
            "user_id": 900001, "user_name": "گزارش‌دهنده تست",
            "created_at": "2026-01-02T00:00:00+00:00"}}, upsert=True)
        await db.exam_sessions.update_one({"_id": "w22ex"}, {"$set": {
            "session_id": "w22ex", "user_id": 900001, "status": "finished",
            "started_at": "2026-01-02T01:00:00+00:00",
            "answers": [
                {"question_id": "w22a", "selected": 0, "correct_answer": 0,
                 "is_correct": True,
                 "answered_at": "2026-01-02T01:01:00+00:00"},
                {"question_id": "w22a", "selected": 1, "correct_answer": 0,
                 "is_correct": False,
                 "answered_at": "2026-01-02T01:02:00+00:00"},
            ]}}, upsert=True)

    @classmethod
    async def _clean(cls):
        await cls.db.questions.delete_many({"_id": {"$regex": "^w22"}})
        await cls.db.content_reports.delete_many({"_id": {"$regex": "^w22"}})
        await cls.db.exam_sessions.delete_many({"_id": {"$regex": "^w22"}})

    def _client_ctx(self):
        return self.httpx.AsyncClient(
            transport=self.httpx.ASGITransport(app=self.app), base_url="http://t")

    def test_health_scores_and_order(self):
        async def run():
            async with self._client_ctx() as c:
                r = await c.get("/api/web-admin/questions/health",
                                headers=self.admin_h)
                return r
        r = self._run(run())
        self.assertEqual(r.status_code, 200)
        items = {i["id"]: i for i in r.json()["items"]}
        self.assertIn("w22a", items)
        self.assertIn("w22b", items)
        self.assertNotIn("w22c", items, "سؤال بدون سیگنال نباید در لیست پیش‌فرض باشد")
        a, b = items["w22a"], items["w22b"]
        self.assertEqual(a["score"], 55)          # 45 نرخ غلط + 10 بدون توضیح
        self.assertTrue(a["needs_review"])
        self.assertEqual(b["score"], 45)          # گزارش باز
        self.assertTrue(b["needs_review"])
        order = [i["id"] for i in r.json()["items"]]
        self.assertLess(order.index("w22a"), order.index("w22b"),
                        "بدترین‌ها باید اول باشند")
        self.assertEqual(r.json()["summary"]["needs_review"],
                         sum(1 for i in r.json()["items"] if i["needs_review"]))

    def test_health_include_healthy_shows_zero_score(self):
        async def run():
            async with self._client_ctx() as c:
                return await c.get(
                    "/api/web-admin/questions/health?include_healthy=true",
                    headers=self.admin_h)
        r = self._run(run())
        ids = {i["id"] for i in r.json()["items"]}
        self.assertIn("w22c", ids)

    def test_360_sections_real_data(self):
        async def run():
            async with self._client_ctx() as c:
                ra = await c.get("/api/web-admin/questions/w22a/360",
                                 headers=self.admin_h)
                rb = await c.get("/api/web-admin/questions/w22b/360",
                                 headers=self.admin_h)
                rn = await c.get("/api/web-admin/questions/w22nope/360",
                                 headers=self.admin_h)
            return ra, rb, rn
        ra, rb, rn = self._run(run())
        self.assertEqual(ra.status_code, 200)
        self.assertEqual(rn.status_code, 404)
        a = ra.json()
        self.assertEqual(a["question"]["attempt_count"], 10)
        self.assertEqual(a["health"]["score"], 55)
        self.assertTrue(a["health"]["needs_review"])
        self.assertEqual(a["exams"]["attempts"], 2,
                         "بخش آزمون باید پاسخ‌های واقعی exam_sessions را بشمارد")
        self.assertEqual(a["exams"]["correct"], 1)
        self.assertEqual(a["reports"]["total"], 0)
        b = rb.json()
        self.assertEqual(b["reports"]["open"], 1)
        self.assertEqual(b["reports"]["recent"][0]["reason"], "wrong_answer")

    def test_forbidden_for_plain_student(self):
        async def run():
            async with self._client_ctx() as c:
                r1 = await c.get("/api/web-admin/questions/health",
                                 headers=self.student_h)
                r2 = await c.get("/api/web-admin/questions/w22a/360",
                                 headers=self.student_h)
            return r1, r2
        r1, r2 = self._run(run())
        self.assertEqual(r1.status_code, 403)
        self.assertEqual(r2.status_code, 403)


if __name__ == "__main__":
    unittest.main()
