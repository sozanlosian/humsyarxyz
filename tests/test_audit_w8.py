# -*- coding: utf-8 -*-
"""🌊 W8 (ممیزی) — قراردادهای خالص: SLA تیکت، دقیقه‌ی برنامه، پیش‌نمایش، iCal.

بدون Mongo و بدون شبکه؛ فقط منطق خالص توابع واقعی.
"""
import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# قرارداد سوئیت: تست‌های databaseمحور بدون MONGODB_URI سکیت می‌شوند.
# این فایل الفبایی اول است؛ env را فقط برای ایمپورت‌های خودش ست می‌کند
# و بلافاصله برمی‌گرداند تا رفتار skip دیگران عوض نشود.
_had_uri = "MONGODB_URI" in os.environ
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
os.environ.setdefault("TELEGRAM_TOKEN", "test-token-for-audit-w8")

from db.core import DBCore
from db.content import DBContent
from api.telegram_send import (
    is_previewable,
    preview_token,
    verify_preview_token,
)
from api.routers.schedule import build_ical

if not _had_uri:
    del os.environ["MONGODB_URI"]


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


class SlaInfoTest(unittest.TestCase):
    def test_no_sla_when_zero(self):
        t = {"sla_hours": 0, "created_at": _iso(datetime.now(timezone.utc)),
             "status": "open"}
        info = DBCore.ticket_sla_info(t)
        self.assertEqual(info["sla_hours"], 0)
        self.assertIsNone(info["due_at"])
        self.assertFalse(info["breached"])
        self.assertFalse(info["responded"])

    def test_legacy_ticket_treated_as_no_sla(self):
        info = DBCore.ticket_sla_info({"status": "open"})
        self.assertEqual(info["sla_hours"], 0)
        self.assertFalse(info["breached"])

    def test_breached_when_past_due(self):
        old = datetime.now(timezone.utc) - timedelta(hours=50)
        t = {"sla_hours": 48, "created_at": _iso(old), "status": "open"}
        info = DBCore.ticket_sla_info(t)
        self.assertTrue(info["breached"])
        self.assertIsNotNone(info["due_at"])
        self.assertFalse(info["responded"])

    def test_not_breached_before_due(self):
        now = datetime.now(timezone.utc)
        t = {"sla_hours": 48, "created_at": _iso(now), "status": "open"}
        info = DBCore.ticket_sla_info(t)
        self.assertFalse(info["breached"])
        self.assertIsNotNone(info["due_at"])

    def test_responded_never_breaches(self):
        old = datetime.now(timezone.utc) - timedelta(hours=200)
        t = {"sla_hours": 8, "created_at": _iso(old), "status": "open",
             "first_response_at": _iso(old + timedelta(hours=1))}
        info = DBCore.ticket_sla_info(t)
        self.assertTrue(info["responded"])
        self.assertFalse(info["breached"])
        self.assertIsNone(info["due_at"])

    def test_closed_never_breaches(self):
        old = datetime.now(timezone.utc) - timedelta(hours=200)
        t = {"sla_hours": 8, "created_at": _iso(old), "status": "closed"}
        info = DBCore.ticket_sla_info(t)
        self.assertFalse(info["breached"])
        self.assertIsNone(info["due_at"])

    def test_sla_defaults_present(self):
        self.assertEqual(DBCore.TICKET_SLA_DEFAULTS["urgent"], 8)
        self.assertEqual(DBCore.TICKET_SLA_DEFAULTS["low"], 72)


class SchedMinutesTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(DBContent._sched_minutes("08:30"), 510)
        self.assertEqual(DBContent._sched_minutes("00:00"), 0)
        self.assertEqual(DBContent._sched_minutes("23:59"), 1439)

    def test_invalid_returns_none(self):
        for bad in ("", None, "abc", "25:00", "10:60", "10", "10:20:30"):
            self.assertIsNone(DBContent._sched_minutes(bad), bad)


class PreviewableTest(unittest.TestCase):
    def test_media_and_pdf(self):
        self.assertTrue(is_previewable("video/mp4"))
        self.assertTrue(is_previewable("audio/mpeg"))
        self.assertTrue(is_previewable("image/jpeg"))
        self.assertTrue(is_previewable("application/pdf"))

    def test_archives_not_previewable(self):
        self.assertFalse(is_previewable("application/zip"))
        self.assertFalse(is_previewable("application/x-rar-compressed"))

    def test_legacy_extension_fallback(self):
        self.assertTrue(
            is_previewable("application/octet-stream", "mp4"))
        self.assertTrue(
            is_previewable("", "pdf"))
        self.assertFalse(
            is_previewable("application/octet-stream", "exe"))


class PreviewTokenTest(unittest.TestCase):
    def test_roundtrip(self):
        exp = int(time.time()) + 600
        tok = preview_token(123, "res", "abc", exp)
        self.assertTrue(verify_preview_token(tok, 123, "res", "abc", exp))

    def test_tamper_rejected(self):
        exp = int(time.time()) + 600
        tok = preview_token(123, "res", "abc", exp)
        bad = ("0" if tok[0] != "0" else "1") + tok[1:]
        self.assertFalse(verify_preview_token(bad, 123, "res", "abc", exp))

    def test_expired_rejected(self):
        exp = int(time.time()) - 1
        tok = preview_token(123, "res", "abc", exp)
        self.assertFalse(verify_preview_token(tok, 123, "res", "abc", exp))

    def test_scope_file_uid_bound(self):
        exp = int(time.time()) + 600
        tok = preview_token(123, "res", "abc", exp)
        self.assertFalse(verify_preview_token(tok, 123, "ref", "abc", exp))
        self.assertFalse(verify_preview_token(tok, 123, "res", "xyz", exp))
        self.assertFalse(verify_preview_token(tok, 999, "res", "abc", exp))

    def test_empty_token_rejected(self):
        exp = int(time.time()) + 600
        self.assertFalse(verify_preview_token("", 123, "res", "abc", exp))


class BuildIcalTest(unittest.TestCase):
    def test_envelope_and_event(self):
        items = [{
            "_id": "evt1",
            "kind": "class",
            "lesson": "ریاضی",
            "date": "2026-09-15",
            "time": "08:00",
        }]
        out = build_ical(items)
        self.assertIn("BEGIN:VCALENDAR", out)
        self.assertIn("END:VCALENDAR", out)
        self.assertIn("BEGIN:VEVENT", out)
        self.assertIn("UID:evt1@humsyar", out)
        self.assertIn("DTSTART:", out)
        self.assertIn("DTEND:", out)
        self.assertIn("ریاضی", out)

    def test_dateless_skipped(self):
        out = build_ical([{"_id": "x", "kind": "exam",
                           "lesson": "فیزیک"}])
        self.assertNotIn("BEGIN:VEVENT", out)
        self.assertIn("BEGIN:VCALENDAR", out)

    def test_escaping(self):
        items = [{
            "_id": "e2",
            "kind": "exam",
            "lesson": "شیمی; آلی, پیشرفته\nنهایی",
            "date": "2026-09-15",
            "time": "10:00",
        }]
        out = build_ical(items)
        self.assertIn("شیمی\\; آلی\\, پیشرفته\\nنهایی", out)

    def test_empty_list_valid_envelope(self):
        out = build_ical([])
        self.assertIn("BEGIN:VCALENDAR", out)
        self.assertIn("END:VCALENDAR", out)
        self.assertNotIn("BEGIN:VEVENT", out)


if __name__ == "__main__":
    unittest.main()
