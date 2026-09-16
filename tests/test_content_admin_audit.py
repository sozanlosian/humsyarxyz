"""🐛 رگرسیون: helper آدیت پنل محتوا باید before/after را بپذیرد.

باگ واقعی: `_audit` در content_admin.py پارامتر before/after نداشت ولی
دو فراخوان (ویرایش درس/جلسه) آن را پاس می‌دادند → TypeError هنگام
binding (بیرون از try داخلی) → اقدام موفق ادمین با «خطای ربات» تمام
می‌شد. این تست دقیقاً همان binding را بررسی می‌کند.
"""
import inspect
import os
import unittest

_HAS_MONGO_URI = bool(os.environ.get("MONGODB_URI"))


@unittest.skipUnless(_HAS_MONGO_URI, "MONGODB_URI لازم است (import database)")
class AuditHelperSignatureTests(unittest.TestCase):

    def test_audit_accepts_before_after(self):
        import content_admin
        sig = inspect.signature(content_admin._audit)
        for kw in ("before", "after"):
            self.assertIn(kw, sig.parameters,
                          f"_audit پارامتر {kw} ندارد — TypeError برمی‌گردد")
        # helper باید همان before/after را به send_audit_log پاس بدهد
        import inspect as _i
        src = _i.getsource(content_admin._audit)
        self.assertIn("before=before", src)
        self.assertIn("after=after", src)

    def test_edit_flows_call_shape_matches(self):
        """فراخوان‌های before=/after= در edit_lesson/edit_session با
        امضای helper سازگارند (بدون اجرای async — فقط inspect)."""
        import content_admin
        import inspect as _i
        src = _i.getsource(content_admin)
        # هر دو جریان ویرایش، before و after را پاس می‌دهند
        self.assertEqual(src.count("before={field:"), 2)
        sig = inspect.signature(content_admin._audit)
        self.assertIn("before", sig.parameters)
        self.assertIn("after", sig.parameters)


if __name__ == "__main__":
    unittest.main()
