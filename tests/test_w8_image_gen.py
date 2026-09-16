# -*- coding: utf-8 -*-
"""🌊 W8 — تولید تصویر با Gemini (بات + مینی‌اپ + API).

۱) تست‌های provider: نگاشت خطا/retry/parse با httpx.MockTransport
   (توابع واقعی ai_solver.generate_image و _parse_image_response صدا
   زده می‌شوند، نه بازپیاده‌سازی).
۲) تست‌های اندپوینت /api/ai/generate-image: گاردها (ban/غیرفعال/سهمیه/
   قفل ۴۰۹/اعتبارسنجی) و سیاست «مصرف سهمیه فقط بعد از موفقیت».
۳) تست‌های سیم‌کشی ایستا: بات، مینی‌اپ، ادمین — و نبودِ کلید API در
   سورسِ مینی‌اپ.

الگوی runtime دقیقاً مثل test_w7_webadmin_gaps: loop مشترک _rtloop.
"""
import base64
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))  # برای import _rtloop خارجِ discover

_HAS_MONGO_URI = bool(os.environ.get("MONGODB_URI"))

ADMIN_UID = 880801
STUDENT_W8 = 880802
STUDENT_W8_B = 880803

FAKE_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()


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


def _mock_transport(handler):
    import httpx
    return httpx.MockTransport(handler)


# ══════════════════════════════════════════════════════════════
#  ۱) provider — بدون Mongo (httpx.MockTransport + هوک _image_http_client)
# ══════════════════════════════════════════════════════════════
@unittest.skipUnless(_HAS_MONGO_URI,
                     "import ai_solver به MONGODB_URI نیاز دارد (CI)")
class ImageProviderUnitTests(unittest.TestCase):
    """خطاهای نگاشت‌شده و رفتار retry لایه‌ی provider."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("TELEGRAM_TOKEN", "123:test")
        import ai_solver
        cls.asv = ai_solver
        cls.patch = mock.patch.object(
            ai_solver, "IMG_RETRY_BASE_DELAY", 0.001)
        cls.patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()

    def _run_with(self, handler):
        import _rtloop
        _rtloop.adopt()
        import httpx

        def factory(timeout):
            return httpx.AsyncClient(
                transport=_mock_transport(handler), timeout=timeout)

        with mock.patch.object(self.asv, "_image_http_client", factory):
            return _rtloop.run(self.asv.generate_image(
                "key", "gemini-2.5-flash-image", "یک گربه", "16:9"))

    def test_success_parses_inline_image(self):
        seen = {}

        def handler(request):
            import json, httpx
            seen["body"] = json.loads(request.content)
            seen["key"] = request.headers.get("x-goog-api-key")
            return httpx.Response(200, json={
                "candidates": [{"content": {"parts": [{
                    "inlineData": {"mimeType": "image/png",
                                   "data": FAKE_PNG}}]}}]})

        res = self._run_with(handler)
        self.assertEqual(res["mime"], "image/png")
        self.assertEqual(res["data_b64"], FAKE_PNG)
        self.assertEqual(seen["key"], "key")
        gc = seen["body"]["generationConfig"]
        self.assertEqual(gc["responseModalities"], ["IMAGE"])
        self.assertEqual(gc["imageConfig"]["aspectRatio"], "16:9")

    def test_unknown_aspect_falls_back_1x1(self):
        seen = {}

        def handler(request):
            import json, httpx
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={
                "candidates": [{"content": {"parts": [{
                    "inlineData": {"mimeType": "image/png",
                                   "data": FAKE_PNG}}]}}]})

        import _rtloop
        _rtloop.adopt()
        import httpx

        def factory(timeout):
            return httpx.AsyncClient(
                transport=_mock_transport(handler), timeout=timeout)

        with mock.patch.object(self.asv, "_image_http_client", factory):
            _rtloop.run(self.asv.generate_image(
                "key", "m", "prompt ok", "99:99"))
        self.assertEqual(
            seen["body"]["generationConfig"]["imageConfig"]["aspectRatio"],
            "1:1")

    def test_401_maps_auth_error_without_retry(self):
        calls = []

        def handler(request):
            import httpx
            calls.append(1)
            return httpx.Response(401, json={"error": "bad key"})

        with self.assertRaises(self.asv.AiImageError) as ctx:
            self._run_with(handler)
        self.assertEqual(ctx.exception.code, "GEMINI_AUTH_ERROR")
        self.assertEqual(len(calls), 1, "401 نباید retry شود")
        self.assertNotIn("bad key", ctx.exception.user_message)

    def test_400_maps_invalid_request_without_retry(self):
        calls = []

        def handler(request):
            import httpx
            calls.append(1)
            return httpx.Response(400, json={"error": "details"})

        with self.assertRaises(self.asv.AiImageError) as ctx:
            self._run_with(handler)
        self.assertEqual(ctx.exception.code, "GEMINI_INVALID_REQUEST")
        self.assertEqual(len(calls), 1)

    def test_429_retries_then_succeeds(self):
        calls = []

        def handler(request):
            import httpx
            calls.append(1)
            if len(calls) < 3:
                return httpx.Response(429, json={})
            return httpx.Response(200, json={
                "candidates": [{"content": {"parts": [{
                    "inlineData": {"mimeType": "image/png",
                                   "data": FAKE_PNG}}]}}]})

        res = self._run_with(handler)
        self.assertEqual(res["data_b64"], FAKE_PNG)
        self.assertEqual(len(calls), 3)

    def test_429_retry_after_header_respected(self):
        import httpx
        calls = []
        slept = []

        async def fake_sleep(seconds):
            slept.append(seconds)

        def handler(request):
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(
                    429, json={}, headers={"Retry-After": "7"})
            return httpx.Response(200, json={
                "candidates": [{"content": {"parts": [{
                    "inlineData": {"mimeType": "image/png",
                                   "data": FAKE_PNG}}]}}]})

        import _rtloop
        _rtloop.adopt()

        def factory(timeout):
            return httpx.AsyncClient(
                transport=_mock_transport(handler), timeout=timeout)

        with mock.patch.object(self.asv, "_image_http_client", factory), \
             mock.patch.object(self.asv, "_img_sleep", fake_sleep):
            res = _rtloop.run(self.asv.generate_image(
                "key", "m", "prompt ok", "1:1"))
        self.assertEqual(res["data_b64"], FAKE_PNG)
        self.assertEqual(slept, [7.0], "باید دقیقاً Retry-After رعایت شود")

    def test_429_retry_after_over_cap_fails_fast(self):
        import httpx
        calls = []

        async def fake_sleep(seconds):
            raise AssertionError("نباید اصلاً بخوابد")

        def handler(request):
            calls.append(1)
            return httpx.Response(
                429, json={}, headers={"Retry-After": "999"})

        import _rtloop
        _rtloop.adopt()

        def factory(timeout):
            return httpx.AsyncClient(
                transport=_mock_transport(handler), timeout=timeout)

        with mock.patch.object(self.asv, "_image_http_client", factory), \
             mock.patch.object(self.asv, "_img_sleep", fake_sleep):
            with self.assertRaises(self.asv.AiImageError) as ctx:
                _rtloop.run(self.asv.generate_image(
                    "key", "m", "prompt ok", "1:1"))
        self.assertEqual(ctx.exception.code, "GEMINI_RATE_LIMIT")
        self.assertEqual(len(calls), 1, "بدون معطلی باید شکست بخورد")

    def test_429_logs_response_body_for_diagnosis(self):
        import httpx

        def handler(request):
            return httpx.Response(
                429,
                json={"error": {
                    "message": "QUOTA_ZERO_FOR_IMAGE_MODEL_ON_PROJECT"}})

        import logging
        with self.assertLogs("ai_solver", level="WARNING") as logs:
            with self.assertRaises(self.asv.AiImageError):
                self._run_with(handler)
        joined = "\n".join(logs.output)
        self.assertIn("QUOTA_ZERO_FOR_IMAGE_MODEL_ON_PROJECT", joined,
                      "علت دقیق Google باید در لاگ باشد")

    def test_503_always_maps_unavailable(self):
        def handler(request):
            import httpx
            return httpx.Response(503, json={})

        with self.assertRaises(self.asv.AiImageError) as ctx:
            self._run_with(handler)
        self.assertEqual(ctx.exception.code, "GEMINI_UNAVAILABLE")

    def test_timeout_maps_timeout(self):
        def handler(request):
            import httpx
            raise httpx.ReadTimeout("slow")

        with self.assertRaises(self.asv.AiImageError) as ctx:
            self._run_with(handler)
        self.assertEqual(ctx.exception.code, "GEMINI_TIMEOUT")

    # ---- parse ----
    def test_parse_prompt_feedback_block(self):
        with self.assertRaises(self.asv.AiImageError) as ctx:
            self.asv._parse_image_response(
                {"promptFeedback": {"blockReason": "SAFETY"}})
        self.assertEqual(ctx.exception.code, "GEMINI_SAFETY_BLOCK")

    def test_parse_finish_reason_safety(self):
        with self.assertRaises(self.asv.AiImageError) as ctx:
            self.asv._parse_image_response({"candidates": [{
                "finishReason": "PROHIBITED_CONTENT",
                "content": {"parts": [{"text": "nope"}]}}]})
        self.assertEqual(ctx.exception.code, "GEMINI_SAFETY_BLOCK")

    def test_parse_no_image_part(self):
        with self.assertRaises(self.asv.AiImageError) as ctx:
            self.asv._parse_image_response({"candidates": [{
                "content": {"parts": [{"text": "متن بدون عکس"}]}}]})
        self.assertEqual(ctx.exception.code, "IMAGE_PARSE_FAILED")

    def test_parse_empty_candidates(self):
        with self.assertRaises(self.asv.AiImageError) as ctx:
            self.asv._parse_image_response({"candidates": []})
        self.assertEqual(ctx.exception.code, "IMAGE_PARSE_FAILED")

    def test_parse_non_image_inline_skipped(self):
        with self.assertRaises(self.asv.AiImageError) as ctx:
            self.asv._parse_image_response({"candidates": [{
                "content": {"parts": [{
                    "inlineData": {"mimeType": "application/pdf",
                                   "data": "eA=="}}]}}]})
        self.assertEqual(ctx.exception.code, "IMAGE_PARSE_FAILED")


# ══════════════════════════════════════════════════════════════
#  ۲) اندپوینت /api/ai/generate-image — با Mongo واقعی
# ══════════════════════════════════════════════════════════════
@unittest.skipUnless(_mongo_available(), "MongoDB در دسترس نیست (CI)")
class ImageEndpointRuntimeTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import _rtloop
        _rtloop.adopt()
        cls.runcoro = staticmethod(_rtloop.run)
        os.environ.setdefault("TELEGRAM_TOKEN", "123:test")
        os.environ["ADMIN_ID"] = str(ADMIN_UID)
        os.environ.setdefault("MONGODB_URI",
                              "mongodb://127.0.0.1:27017")
        from database import db
        cls.db = db
        from api.routers import ai as ai_router
        cls.ai = ai_router
        import ai_solver
        cls.asv = ai_solver
        from fastapi import HTTPException
        cls.HTTPException = HTTPException
        for uid in (STUDENT_W8, STUDENT_W8_B):
            try:
                cls.run(db.create_user(uid, "دانشجوی W8",
                                       f"w8-{uid}", "گروه تست"))
            except Exception:
                pass  # از اجرای قبلی وجود دارد

    def setUp(self):
        # ایزوله‌سازی هر تست: سهمیه‌ها/قفل‌ها از صفر
        self.runcoro(self.db.users.update_one(
            {"user_id": STUDENT_W8},
            {"$set": {"ai_image_count": 0,
                      "ai_image_date": "1970-01-01",
                      "ai_usage_count": 0,
                      "ai_usage_date": "1970-01-01",
                      "ai_banned": False}}))
        self.runcoro(self.db.admin_op_locks.delete_many(
            {"kind": "ai_inflight"}))
        # تنظیمات پایه: فعال + کلید + سهمیه تصویر ۲
        self.runcoro(self.db.set_setting("ai_enabled", "1"))
        self.runcoro(self.db.set_setting("ai_api_key", "fake-key"))
        self.runcoro(self.db.set_setting("ai_image_enabled", "1"))
        self.runcoro(self.db.set_setting("ai_image_daily_limit", "2"))

    def _call(self, uid, prompt="یک کتابخانه زیبا", ratio="1:1"):
        body = self.ai.ImageGenBody(prompt=prompt, aspect_ratio=ratio)
        return self.ai.generate_image_ep(body, user={"id": uid})

    def _with_fake_provider(self, result=None, exc=None):
        async def fake(api_key, model, prompt, aspect_ratio="1:1"):
            self.assertEqual(api_key, "fake-key")
            if exc:
                raise exc
            return result or {"mime": "image/png",
                              "data_b64": FAKE_PNG}
        return mock.patch.object(self.ai, "generate_image", fake)

    def test_success_returns_image_and_consumes_after(self):
        with self._with_fake_provider():
            res = self.runcoro(self._call(STUDENT_W8))
        self.assertTrue(res["ok"])
        self.assertEqual(res["image"], FAKE_PNG)
        self.assertEqual(res["usage"]["used_today"], 1)
        self.assertEqual(res["usage"]["daily_limit"], 2)
        self.assertEqual(res["usage"]["remaining"], 1)

    def test_empty_prompt_422(self):
        with self.assertRaises(self.HTTPException) as ctx:
            self.runcoro(self._call(STUDENT_W8, prompt="  "))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_too_long_prompt_422(self):
        with self.assertRaises(self.HTTPException) as ctx:
            self.runcoro(self._call(STUDENT_W8, prompt="ک" * 1001))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_bad_ratio_422(self):
        with self.assertRaises(self.HTTPException) as ctx:
            self.runcoro(self._call(STUDENT_W8, ratio="7:3"))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_disabled_image_503(self):
        self.runcoro(self.db.set_setting("ai_image_enabled", "0"))
        with self.assertRaises(self.HTTPException) as ctx:
            self.runcoro(self._call(STUDENT_W8))
        self.assertEqual(ctx.exception.status_code, 503)

    def test_no_api_key_503(self):
        self.runcoro(self.db.set_setting("ai_api_key", ""))
        with self.assertRaises(self.HTTPException) as ctx:
            self.runcoro(self._call(STUDENT_W8))
        self.assertEqual(ctx.exception.status_code, 503)

    def test_banned_user_403(self):
        self.runcoro(self.db.ai_set_banned(STUDENT_W8_B, True))
        try:
            with self.assertRaises(self.HTTPException) as ctx:
                self.runcoro(self._call(STUDENT_W8_B))
            self.assertEqual(ctx.exception.status_code, 403)
        finally:
            self.runcoro(self.db.ai_set_banned(STUDENT_W8_B, False))

    def test_quota_exhausted_429(self):
        today = self.asv_today()
        self.runcoro(self.db.ai_image_inc(STUDENT_W8, today))
        self.runcoro(self.db.ai_image_inc(STUDENT_W8, today))
        with self.assertRaises(self.HTTPException) as ctx:
            self.runcoro(self._call(STUDENT_W8))
        self.assertEqual(ctx.exception.status_code, 429)

    def asv_today(self):
        from time_utils import today_tehran
        return today_tehran().isoformat()

    def test_admin_bypasses_quota(self):
        with self._with_fake_provider():
            res = self.runcoro(self._call(ADMIN_UID))
        self.assertTrue(res["usage"]["unlimited"])

    def test_provider_failure_does_not_consume(self):
        exc = self.asv.AiImageError("GEMINI_SAFETY_BLOCK", "نه!")
        today = self.asv_today()
        before = self.runcoro(self.db.ai_image_used_today(STUDENT_W8, today))
        with self._with_fake_provider(exc=exc):
            with self.assertRaises(self.HTTPException) as ctx:
                self.runcoro(self._call(STUDENT_W8))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail, "نه!")
        after = self.runcoro(self.db.ai_image_used_today(STUDENT_W8, today))
        self.assertEqual(before, after,
                         "شکست provider نباید سهمیه بسوزاند")

    def test_inflight_lock_prevents_double_request(self):
        claimed = self.runcoro(self.asv.ai_claim_inflight(STUDENT_W8))
        self.assertTrue(claimed)
        try:
            with self.assertRaises(self.HTTPException) as ctx:
                self.runcoro(self._call(STUDENT_W8))
            self.assertEqual(ctx.exception.status_code, 409)
        finally:
            self.runcoro(self.asv.ai_release_inflight(STUDENT_W8))

    def test_lock_released_after_success(self):
        with self._with_fake_provider():
            self.runcoro(self._call(STUDENT_W8))
        self.assertFalse(self.runcoro(self.asv.ai_is_inflight(STUDENT_W8)))

    def test_lock_released_after_provider_error(self):
        exc = self.asv.AiImageError("GEMINI_TIMEOUT", "دیر شد")
        with self._with_fake_provider(exc=exc):
            with self.assertRaises(self.HTTPException):
                self.runcoro(self._call(STUDENT_W8))
        self.assertFalse(self.runcoro(self.asv.ai_is_inflight(STUDENT_W8)))

    def test_image_quota_bucket_independent_from_chat(self):
        today = self.asv_today()
        # مصرف چت نباید سهمیه‌ی تصویر را پر کند
        for _ in range(3):
            self.runcoro(self.db.ai_consume_quota(STUDENT_W8, 5, today))
        used = self.runcoro(self.db.ai_image_used_today(STUDENT_W8, today))
        self.assertEqual(used, 0)

    def test_config_reads_image_settings(self):
        self.runcoro(self.db.set_setting("ai_image_model", "test-model-x"))
        self.runcoro(self.db.set_setting("ai_image_daily_limit", "7"))
        cfg = self.runcoro(self.asv.get_ai_config())
        self.assertEqual(cfg["image_model"], "test-model-x")
        self.assertEqual(cfg["image_daily_limit"], 7)
        self.assertTrue(cfg["image_enabled"])


# ══════════════════════════════════════════════════════════════
#  ۳) سیم‌کشی ایستا
# ══════════════════════════════════════════════════════════════
class ImageWiringStaticTests(unittest.TestCase):

    def test_bot_wires_image_mode(self):
        bot = _read("bot.py")
        self.assertIn("handle_ai_image_prompt", bot)
        self.assertIn("ai_image_prompt", bot)
        # در روترِ متن، شاخه‌ی تصویر باید قبل از handle_ai_text باشد
        self.assertLess(bot.index("mode') == 'ai_image_prompt'"),
                        bot.index("return await handle_ai_text"))

    def test_bot_callback_and_keyboard(self):
        asv = _read("ai_solver.py")
        self.assertIn("aiu:imgstart", asv)
        self.assertIn("ساخت تصویر", asv)
        self.assertIn("handle_ai_image_prompt", asv)

    def test_endpoint_wired(self):
        router = _read("api", "routers", "ai.py")
        self.assertIn("/generate-image", router)
        self.assertIn("ai_image_used_today", router)
        self.assertIn("ai_image_inc", router)
        # provider مستقیم صدا زده نمی‌شود؛ از ai_solver ایمپورت می‌شود
        self.assertIn("    generate_image,\n", router)

    def test_miniapp_page_and_route(self):
        page = _read("miniapp", "src", "pages", "Ai", "AiImage.jsx")
        self.assertIn("/api/ai/generate-image", page)
        self.assertIn("aspect_ratio", page)
        self.assertIn("timeout: 150_000", page)
        app = _read("miniapp", "src", "App.jsx")
        self.assertIn('/ai/image', app)
        self.assertIn("AiImageScreen", app)

    def test_miniapp_has_no_provider_key(self):
        page = _read("miniapp", "src", "pages", "Ai", "AiImage.jsx")
        for needle in ("x-goog-api-key", "AIza", "api_key"):
            self.assertNotIn(needle, page)

    def test_admin_config_exposes_image_settings(self):
        mgmt = _read("api", "routers", "ai_management.py")
        for key in ("image_enabled", "image_model", "image_daily_limit"):
            self.assertIn(key, mgmt)
        admin_ui = _read("miniapp", "src", "pages", "Admin",
                         "AiAdmin.jsx")
        for key in ("image_enabled", "image_model",
                    "image_daily_limit"):
            self.assertIn(key, admin_ui)

    def test_no_env_var_for_image_settings(self):
        # مدل/سهمیه/کلید تصویر همه از settingsِ دیتابیس می‌آیند؛
        # هیچ os.getenv مربوط به تصویر نباید اضافه شده باشد
        asv = _read("ai_solver.py")
        self.assertNotIn("getenv('AI_IMAGE", asv)
        self.assertNotIn('getenv("AI_IMAGE', asv)
        router = _read("api", "routers", "ai.py")
        self.assertNotIn("getenv('AI_IMAGE", router)
        self.assertNotIn('getenv("AI_IMAGE', router)


if __name__ == "__main__":
    unittest.main()
