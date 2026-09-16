"""🐛 FIX آپلود ویدیو — تست‌های Flow آپلود محتوای مینی‌اپ.

ریشه‌ی باگ واقعی (با Evidence):
R1) تایم‌اوت سراسری axios مینی‌اپ ۱۵ ثانیه است؛ آپلود ویدیو دو هاپ دارد
    (مرورگر→سرور→تلگرام) و همیشه از آن بیشتر می‌شد → خطای بی‌response →
    پیام عمومی «عملیات انجام نشد».
R2) بدون سقف/نوع در کلاینت — فایل ۲۰۰ مگابایتی کامل آپلود می‌شد تا ۴۱۳
    بگیرد (و قبلش در ۱۵ ثانیه timeout می‌خورد).
R3) بک‌اند علت شکست تلگرام را می‌بلعید (return None بدون لاگ) و timeout
    ثابت ۶۰ برای ویدیوی بزرگ کم بود.

این تست‌ها لایه‌ی بک‌اند را مستقیماً اجرا می‌کنند (بدون شبکه): سقف حجم،
دسته‌بندی خطای storage، مسیر موفق، و لاگ مرحله‌ای.
"""
import os
import unittest
from unittest import mock

from fastapi import HTTPException

# قرارداد سوئیت: در CI (بدون MONGODB_URI) تست‌های وابسته به importِ
# database سکیت می‌شوند — هرگز env ست نمی‌شود.
_HAS_MONGO_URI = bool(os.environ.get("MONGODB_URI"))


class FakeUpload:
    """شبیه‌ساز UploadFile — read تکه‌ای مثل starlette."""

    def __init__(self, data: bytes, filename="clip.mp4",
                 content_type="video/mp4"):
        self._data = data
        self._pos = 0
        self.filename = filename
        self.content_type = content_type

    async def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            chunk, self._pos = self._data[self._pos:], len(self._data)
            return chunk
        chunk = self._data[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk


def _router():
    from api.routers import content_admin
    return content_admin


def _admin():
    return {"id": 111, "_db": {"name": "ادمین محتوا"}}


@unittest.skipUnless(_HAS_MONGO_URI, "MONGODB_URI لازم است (import database)")
class ReadCappedTests(unittest.IsolatedAsyncioTestCase):
    """واحدِ خالص: خواندن stream با سقف."""

    async def test_under_cap_ok(self):
        mod = _router()
        raw = await mod._read_capped(FakeUpload(b"x" * 1024), 45 * 1024)
        self.assertEqual(len(raw), 1024)

    async def test_over_cap_raises_413(self):
        mod = _router()
        big = FakeUpload(b"x" * (1024 * 1024 + 10))
        with self.assertRaises(HTTPException) as ctx:
            await mod._read_capped(big, 1024 * 1024)
        self.assertEqual(ctx.exception.status_code, 413)

    async def test_exactly_cap_ok(self):
        mod = _router()
        raw = await mod._read_capped(FakeUpload(b"x" * 1024), 1024)
        self.assertEqual(len(raw), 1024)


@unittest.skipUnless(_HAS_MONGO_URI, "MONGODB_URI لازم است (import database)")
class SessionContentUploadTests(unittest.IsolatedAsyncioTestCase):
    """اندپوینت واقعی با dependencyهای stub — مسیرهای موفق/شکست."""

    def setUp(self):
        self.mod = _router()

    async def _call(self, data: bytes, storage_result="tgfid",
                    storage_raises=False, ctype="video"):
        calls = {"bs_add_content": 0}

        async def fake_upload(*a, **k):
            if storage_raises:
                raise RuntimeError("read timeout")
            return storage_result

        async def fake_bs_add_content(*a, **k):
            calls["bs_add_content"] += 1
            return "content-1"

        async def fake_audit(*a, **k):
            return None

        with mock.patch.object(self.mod, "_deny_intake",
                               mock.AsyncMock(return_value=None)), \
             mock.patch.object(self.mod, "upload_and_get_file_id",
                               side_effect=fake_upload), \
             mock.patch.object(self.mod.db, "session_intake",
                               mock.AsyncMock(return_value="")), \
             mock.patch.object(self.mod.db, "bs_add_content",
                               side_effect=fake_bs_add_content), \
             mock.patch.object(self.mod, "_audit", side_effect=fake_audit):
            return await self.mod.bs_add_content_ep(
                "sid-1", ctype=ctype, description="ویدیو جلسه",
                extra_info="", file=FakeUpload(data), admin=_admin()), calls

    async def test_video_success_path(self):
        res, calls = await self._call(b"v" * 2048)
        self.assertTrue(res["ok"])
        self.assertEqual(calls["bs_add_content"], 1)

    async def test_oversized_video_rejected_before_storage(self):
        # ۴۶ مگابایت — باید ۴۱۳ بگیرد و هرگز به تلگرام نرسد
        hit_storage = {"n": 0}

        async def fake_upload(*a, **k):
            hit_storage["n"] += 1
            return "tgfid"

        async def fake_audit(*a, **k):
            return None

        with mock.patch.object(self.mod, "_deny_intake",
                               mock.AsyncMock(return_value=None)), \
             mock.patch.object(self.mod, "upload_and_get_file_id",
                               side_effect=fake_upload), \
             mock.patch.object(self.mod.db, "session_intake",
                               mock.AsyncMock(return_value="")), \
             mock.patch.object(self.mod, "_audit", side_effect=fake_audit):
            with self.assertRaises(HTTPException) as ctx:
                await self.mod.bs_add_content_ep(
                    "sid-1", ctype="video", description="", extra_info="",
                    file=FakeUpload(b"v" * (46 * 1024 * 1024)),
                    admin=_admin())
        self.assertEqual(ctx.exception.status_code, 413)
        self.assertEqual(hit_storage["n"], 0,
                         "فایل بیش‌ازحد نباید به storage برسد")

    async def test_storage_none_is_502(self):
        with self.assertRaises(HTTPException) as ctx:
            await self._call(b"v" * 10, storage_result=None)
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("لاگ سرور", str(ctx.exception.detail))

    async def test_storage_exception_is_502_not_500(self):
        # قبل از FIX: استثنا رها می‌شد → ۵۰۰ بی‌توضیح
        with self.assertRaises(HTTPException) as ctx:
            await self._call(b"v" * 10, storage_raises=True)
        self.assertEqual(ctx.exception.status_code, 502)

    async def test_invalid_ctype_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            await self._call(b"v" * 10, ctype="exe")
        self.assertEqual(ctx.exception.status_code, 422)


class UploadFixStaticTests(unittest.TestCase):
    """سیم‌کشی fix در هر دو لایه — بدون حدس، از روی منبع."""

    @staticmethod
    def _read(*parts):
        import os
        root = os.path.join(os.path.dirname(__file__), "..")
        with open(os.path.join(root, *parts), encoding="utf-8") as f:
            return f.read()

    def test_telegram_send_structured_timeout_and_logging(self):
        src = self._read("api", "telegram_send.py")
        self.assertIn("httpx.Timeout(connect=", src)
        self.assertIn("UPLOAD_FAILED stage=storage", src)
        # token/URL هرگز لاگ نمی‌شود — فقط نوع خطا و status
        self.assertNotIn("logger.info(API_BASE", src)

    def test_router_stage_logging_and_capped_read(self):
        src = self._read("api", "routers", "content_admin.py")
        for token in ("UPLOAD_REQUEST_RECEIVED", "UPLOAD_SUCCESS",
                      "_read_capped", "MAX_UPLOAD_BYTES"):
            self.assertIn(token, src)

    def test_miniapp_upload_timeout_and_guards(self):
        lib = self._read("miniapp", "src", "lib", "api.js")
        self.assertIn("timeout: 15000", lib)  # سراسری دست‌نخورده
        cl = self._read("miniapp", "src", "pages", "Admin",
                        "ContentLibrary.jsx")
        self.assertEqual(cl.count("timeout: 600000"), 2,
                         "هر دو مسیر آپلود باید مهلت طولانی بگیرند")
        self.assertIn("video/*", cl)          # accept متناسب با نوع
        self.assertIn("45 * 1024 * 1024", cl)  # سقف سمت کلاینت

    def test_errortext_categories(self):
        fmt = self._read("miniapp", "src", "lib", "format.js")
        for token in ("ECONNABORTED", "ERR_NETWORK", "413"):
            self.assertIn(token, fmt)


if __name__ == "__main__":
    unittest.main()
