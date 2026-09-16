# -*- coding: utf-8 -*-
"""🛡 HOTFIX — پایداری startup بات.

کرش دیپلوی: TimedOut گذرا به api.telegram.org حین initialize پروسه را
می‌کشت و supervisor پس از چند تکرار FATAL می‌شد → بات برای همه‌ی پیام‌ها
خاموش. fix: حلقه‌ی retry با backoff فقط برای خطاهای شبکه‌ای؛ InvalidToken
(پیکربندی) باید همچنان صریح کرش کند.

علاوه بر تست‌های ساختاری، خودِ `_run_polling_with_retry` با اپ ساختگی
به‌صورت تابعی اجرا می‌شود — همان کدی که در پروداکشن call می‌شود.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# bot.py در سطح ماژول بدون توکن sys.exit(1) می‌کند — برای import در تست
# یک توکن ساختگی کافی است (هیچ اتصال شبکه‌ای در import برقرار نمی‌شود).
os.environ.setdefault("TELEGRAM_TOKEN", "123:FAKE_TEST_TOKEN_FOR_IMPORT")

try:
    import bot  # noqa: E402
    _BOT_IMPORT_ERROR = None
except Exception as _exc:  # حالت CI بدون MONGODB_URI — تست تابعی skip می‌شود
    bot = None
    _BOT_IMPORT_ERROR = _exc

from telegram.error import InvalidToken, NetworkError, TimedOut  # noqa: E402


class _StubApp:
    """اپ ساختگی: run_polling طبق سناریو خطا می‌دهد یا تمیز برمی‌گردد."""

    def __init__(self, scenario):
        self._scenario = list(scenario)

    def run_polling(self, **kwargs):
        action = self._scenario.pop(0) if self._scenario else None
        if isinstance(action, Exception):
            raise action
        return None  # خروج تمیز


class _StubNetworkError(NetworkError):
    """خطای شبکه‌ای عمومی (NetworkError در PTB انتزاعی است)."""


class BotStartupResilienceStaticTests(unittest.TestCase):

    def setUp(self):
        self.src = (ROOT / "bot.py").read_text(encoding="utf-8")
        idx = self.src.index("def _run_polling_with_retry(")
        # 🛡 W3 — پنجره‌ی ثابت ۲۶۰۰ نویسه با هر کامنت می‌شکست؛ کل تابع
        # (تا ابتدای تابع بعدی) مبنای assertionهاست.
        end = self.src.index("\ndef ", idx + 10)
        self.body = self.src[idx:end]

    def test_retry_loop_retries_network_errors(self):
        self.assertIn("while True:", self.body,
                      "تا برقراری اتصال باید زنده بماند")
        self.assertIn("from telegram.error import TimedOut, NetworkError, RetryAfter", self.body)
        self.assertIn("except (TimedOut, NetworkError, RetryAfter)", self.body)
        self.assertIn("time.sleep(delay)", self.body, "backoff لازم است")
        # بازسازی اپ در هر تلاش — PTB پس از initialize شکست‌خورده قابل
        # اعتماد برای initialize دوباره نیست
        self.assertIn("app = build_app()", self.body)

    def test_invalid_token_not_retried(self):
        import re
        # تاپل‌های retry نباید InvalidToken داشته باشند (در هر دو شاخه)
        tuples = re.findall(r"except \((TimedOut[^)]*)\)", self.body)
        self.assertTrue(tuples, "تاپل retry پیدا نشد")
        for tup in tuples:
            self.assertNotIn("InvalidToken", tup,
                             "خطای پیکربندی نباید در دامنه‌ی retry باشد")
        # و گارد صریح «عدم retry + raise» برایش موجود باشد
        self.assertIn("if 'InvalidToken' in type(e).__name__", self.body)
        guard = self.body.split("if 'InvalidToken' in type(e).__name__")[1][:200]
        self.assertIn("raise", guard)

    def test_time_imported(self):
        self.assertIn("\nimport time\n", self.src)

    def test_main_uses_helper(self):
        idx = self.src.index("def main():")
        self.assertIn("_run_polling_with_retry(_build_application_with_post_init)",
                      self.src[idx:idx + 300])


@unittest.skipIf(bot is None,
                 f"import bot ناموفق (حالت CI بدون mongo): {_BOT_IMPORT_ERROR}")
class BotStartupResilienceFunctionalTests(unittest.TestCase):
    """اجرای واقعی حلقه‌ی retry با اپ ساختگی و sleep پچ‌شده."""

    def test_timed_out_twice_then_success(self):
        builds = []

        def factory():
            app = _StubApp([TimedOut("httpx.ConnectTimeout")])
            builds.append(app)
            return app

        last = _StubApp([])  # تلاش سوم: موفق
        calls = {"n": 0}

        def counting_factory():
            calls["n"] += 1
            return last if calls["n"] == 3 else factory()

        with patch("bot.time.sleep") as sleep_mock:
            bot._run_polling_with_retry(counting_factory)  # نباید raise کند

        self.assertEqual(calls["n"], 3, "دو خطای گذرا + یک موفقیت = ۳ تلاش")
        self.assertEqual([c.args[0] for c in sleep_mock.call_args_list], [2, 4],
                         "backoff نمایی: ۲ سپس ۴ ثانیه")

    def test_network_error_also_retried(self):
        state = {"n": 0}

        def factory():
            state["n"] += 1
            return _StubApp([_StubNetworkError("Connection reset")] if state["n"] == 1 else [])

        with patch("bot.time.sleep"):
            bot._run_polling_with_retry(factory)
        self.assertEqual(state["n"], 2)

    def test_invalid_token_crashes_loud(self):
        state = {"n": 0}

        def factory():
            state["n"] += 1
            return _StubApp([InvalidToken("401: Unauthorized")])

        with patch("bot.time.sleep") as sleep_mock:
            with self.assertRaises(InvalidToken):
                bot._run_polling_with_retry(factory)
        self.assertEqual(state["n"], 1, "خطای پیکربندی retry نمی‌شود")
        sleep_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
