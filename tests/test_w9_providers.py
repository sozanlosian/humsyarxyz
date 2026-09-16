# -*- coding: utf-8 -*-
"""🌊 W9 — کاتالوگ مرکزی مدل‌ها + providerهای چندگانه.

۱) سازگاری کاتالوگ (هر provider مدل و پیش‌فرض دارد؛ payload سالم است)
۲) فراخوان عمومی OpenAI-compatible با httpx.MockTransport
   (مسیر groq، خطاها، گارد vision، تفاوت ۴۰۲ openrouter/بقیه)
۳) runtime: پیش‌فرض مدل هر provider + endpoint کاتالوگ + گارد تصویر
۴) سیم‌کشی ایستا هر سه UI (بات/پنل وب/مینی‌اپ)

الگوی runtime مثل بقیه‌ی موج‌ها: loop مشترک _rtloop.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

_HAS_MONGO_URI = bool(os.environ.get("MONGODB_URI"))


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


# ══════════════════════════════════════════════════════════════
#  ۱) سازگاری کاتالوگ
# ══════════════════════════════════════════════════════════════
@unittest.skipUnless(_HAS_MONGO_URI,
                     "import ai_solver به MONGODB_URI نیاز دارد (CI)")
class CatalogConsistencyTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("TELEGRAM_TOKEN", "123:test")
        import ai_solver
        cls.asv = ai_solver

    def test_every_provider_has_models_and_default(self):
        for pid in self.asv.PROVIDERS:
            self.assertTrue(
                self.asv.MODEL_CATALOG.get(pid),
                f"provider {pid} مدل کاتالوگ ندارد")
            self.assertIn(pid, self.asv.DEFAULT_MODELS,
                          f"provider {pid} مدل پیش‌فرض ندارد")
            default = self.asv.DEFAULT_MODELS[pid]
            ids = [m[0] for m in self.asv.MODEL_CATALOG[pid]]
            self.assertIn(default, ids,
                          f"پیش‌فرض {pid} باید در کاتالوگش باشد")

    def test_urls_defined_except_gemini(self):
        for pid, meta in self.asv.PROVIDERS.items():
            if pid == "gemini":
                self.assertIsNone(meta["url"])
            else:
                self.assertTrue(meta["url"].startswith("https://"),
                                f"{pid} url نامعتبر")

    def test_payload_shape(self):
        payload = self.asv.ai_catalog_payload()
        self.assertEqual(len(payload["providers"]),
                         len(self.asv.PROVIDERS))
        for prov in payload["providers"]:
            for key in ("id", "label", "vision", "images",
                        "default_model", "models"):
                self.assertIn(key, prov)
            for model in prov["models"]:
                self.assertTrue(model["id"])
                self.assertTrue(model["label"])
                self.assertIsInstance(model["free"], bool)
        self.assertTrue(payload["image_models"])
        self.assertIn(payload["default_image_model"],
                      [m["id"] for m in payload["image_models"]])

    def test_all_compat_providers_registered(self):
        import ai_solver
        for pid in ("gemini", "openrouter", "groq", "cerebras",
                    "mistral", "deepseek"):
            self.assertIn(pid, ai_solver.STREAM_PROVIDERS,
                          f"{pid} در STREAM_PROVIDERS ثبت نشده")


# ══════════════════════════════════════════════════════════════
#  ۲) فراخوان عمومی OpenAI-compatible (بدون Mongo)
# ══════════════════════════════════════════════════════════════
@unittest.skipUnless(_HAS_MONGO_URI,
                     "import ai_solver به MONGODB_URI نیاز دارد (CI)")
class OpenAiCompatCallerTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("TELEGRAM_TOKEN", "123:test")
        import ai_solver
        cls.asv = ai_solver

    def _call(self, handler, **kwargs):
        import _rtloop
        import httpx
        _rtloop.adopt()
        kwargs.setdefault("api_key", "k")
        kwargs.setdefault("model", "m")
        kwargs.setdefault("system_prompt", "sp")
        kwargs.setdefault("text", "سلام")
        real = httpx.AsyncClient

        def factory(*a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            kw.pop("timeout", None)
            return real(*a, **kw)

        with mock.patch("httpx.AsyncClient", factory):
            return _rtloop.run(self.asv._call_openai_compat(**kwargs))

    def test_groq_url_and_success(self):
        seen = {}

        def handler(request):
            import httpx
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("Authorization")
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "جواب"},
                             "finish_reason": "stop"}],
                "usage": {"total_tokens": 42}})

        answer, tokens = self._call(handler, provider="groq")
        self.assertEqual(answer, "جواب")
        self.assertEqual(tokens, 42)
        self.assertIn("api.groq.com/openai/v1/chat/completions",
                      seen["url"])
        self.assertEqual(seen["auth"], "Bearer k")

    def test_429_maps_quota_error(self):
        def handler(request):
            import httpx
            return httpx.Response(429, json={})

        with self.assertRaises(self.asv.AIQuotaError):
            self._call(handler, provider="cerebras")

    def test_no_vision_provider_rejects_image(self):
        def handler(request):
            raise AssertionError("نباید اصلاً درخواست بفرستد")

        with self.assertRaises(self.asv.AIConfigError) as ctx:
            self._call(handler, provider="groq",
                       image_bytes=b"jpg", image_mime="image/jpeg")
        self.assertIn("تصویر", str(ctx.exception))

    def test_openrouter_402_specific_message(self):
        def handler(request):
            import httpx
            return httpx.Response(402, json={})

        with self.assertRaises(self.asv.AIConfigError) as ctx:
            self._call(handler, provider="openrouter")
        self.assertIn("credits", str(ctx.exception))

    def test_other_provider_402_generic_message(self):
        def handler(request):
            import httpx
            return httpx.Response(402, json={})

        with self.assertRaises(self.asv.AIConfigError) as ctx:
            self._call(handler, provider="mistral")
        self.assertNotIn("credits", str(ctx.exception))


# ══════════════════════════════════════════════════════════════
#  ۳) runtime — config/endpoint/گارد تصویر
# ══════════════════════════════════════════════════════════════
@unittest.skipUnless(_mongo_available(), "MongoDB در دسترس نیست (CI)")
class ProviderRuntimeTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import _rtloop
        _rtloop.adopt()
        cls.runcoro = staticmethod(_rtloop.run)
        os.environ.setdefault("TELEGRAM_TOKEN", "123:test")
        os.environ["ADMIN_ID"] = "880901"
        os.environ.setdefault("MONGODB_URI",
                              "mongodb://127.0.0.1:27017")
        from database import db
        cls.db = db
        import ai_solver
        cls.asv = ai_solver
        from api.routers import ai_management
        cls.mgmt = ai_management
        from api.routers import ai as ai_router
        cls.ai = ai_router
        from fastapi import HTTPException
        cls.HTTPException = HTTPException

    def tearDown(self):
        # بازگردانی provider پیش‌فرض
        self.runcoro(self.db.set_setting("ai_provider", "gemini"))

    def test_default_model_per_provider(self):
        self.runcoro(self.db.set_setting("ai_provider", "groq"))
        self.runcoro(self.db.set_setting("ai_model", ""))
        cfg = self.runcoro(self.asv.get_ai_config())
        self.assertEqual(cfg["model"], "llama-3.3-70b-versatile")

    def test_models_catalog_endpoint(self):
        res = self.runcoro(self.mgmt.models_catalog(admin={"id": 1}))
        ids = [p["id"] for p in res["providers"]]
        for expected in ("gemini", "openrouter", "groq",
                         "cerebras", "mistral", "deepseek"):
            self.assertIn(expected, ids)

    def test_image_blocked_on_non_gemini_provider(self):
        self.runcoro(self.db.set_setting("ai_provider", "groq"))
        self.runcoro(self.db.set_setting("ai_enabled", "1"))
        self.runcoro(self.db.set_setting("ai_api_key", "k"))
        body = self.ai.ImageGenBody(prompt="یک گربه", aspect_ratio="1:1")
        with self.assertRaises(self.HTTPException) as ctx:
            self.runcoro(self.ai.generate_image_ep(
                body, user={"id": 880902}))
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("Gemini", ctx.exception.detail)


# ══════════════════════════════════════════════════════════════
#  ۴) سیم‌کشی ایستا — هر سه UI
# ══════════════════════════════════════════════════════════════
class ProviderUiStaticTests(unittest.TestCase):

    def test_bot_admin_uses_central_catalog(self):
        src = _read("ai_admin.py")
        self.assertIn("MODEL_CATALOG", src)
        self.assertIn("PROVIDER_KEY_HINTS", src)
        self.assertIn("'groq'", src)

    def test_webadmin_selects_from_catalog(self):
        src = _read("webadmin", "src", "pages", "AiAdmin.jsx")
        self.assertIn("aiModels", src)
        self.assertIn("__custom", src)
        self.assertIn("default_model", src)
        api = _read("webadmin", "src", "api.js")
        self.assertIn("/api/web-admin/ai/models", api)

    def test_miniapp_admin_selects_from_catalog(self):
        src = _read("miniapp", "src", "pages", "Admin", "AiAdmin.jsx")
        self.assertIn("/api/ai-admin/models", src)
        self.assertIn("__custom", src)
        self.assertIn("image_models", src)
        self.assertIn("default_model", src)

    def test_backend_validation_extended(self):
        for path in (("api", "routers", "ai_management.py"),
                     ("api", "routers", "web_admin.py")):
            src = _read(*path)
            self.assertIn("groq|cerebras|mistral|deepseek", src)

    def test_models_endpoints_exist(self):
        self.assertIn('"/models"',
                      _read("api", "routers", "ai_management.py"))
        self.assertIn('"/ai/models"',
                      _read("api", "routers", "web_admin.py"))


if __name__ == "__main__":
    unittest.main()
