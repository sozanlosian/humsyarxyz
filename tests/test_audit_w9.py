# -*- coding: utf-8 -*-
"""🌊 W9 (ممیزی) — ورک‌فلو وضعیت تیکت، دسته‌ی canned، گاردها.

خالص + ایستا؛ بدون Mongo و شبکه.
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# قرارداد سوئیت: env فقط برای ایمپورت‌های خودمان، بعد برگردان
_had_uri = "MONGODB_URI" in os.environ
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")

from db.core import DBCore

if not _had_uri:
    del os.environ["MONGODB_URI"]


def read(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


class NormStatusTest(unittest.TestCase):
    def test_known_kept(self):
        for s in ("open", "in_progress", "waiting_user",
                  "resolved", "closed"):
            self.assertEqual(DBCore.ticket_norm_status(s), s)

    def test_legacy_answered(self):
        self.assertEqual(DBCore.ticket_norm_status("answered"),
                         "waiting_user")

    def test_garbage_collapses_to_open(self):
        for bad in ("", None, "zzz", 123):
            self.assertEqual(DBCore.ticket_norm_status(bad), "open")


class TransitionTest(unittest.TestCase):
    def test_same_is_noop(self):
        for s in DBCore.TICKET_STATUSES:
            self.assertTrue(DBCore.ticket_transition_allowed(s, s))

    def test_open_fan_out(self):
        self.assertTrue(DBCore.ticket_transition_allowed(
            "open", "in_progress"))
        self.assertTrue(DBCore.ticket_transition_allowed(
            "open", "resolved"))
        self.assertTrue(DBCore.ticket_transition_allowed(
            "open", "closed"))
        self.assertFalse(DBCore.ticket_transition_allowed(
            "open", "waiting_user"))

    def test_waiting_user(self):
        self.assertTrue(DBCore.ticket_transition_allowed(
            "waiting_user", "in_progress"))
        self.assertFalse(DBCore.ticket_transition_allowed(
            "waiting_user", "open"))

    def test_closed_only_reopens(self):
        self.assertTrue(DBCore.ticket_transition_allowed(
            "closed", "in_progress"))
        self.assertFalse(DBCore.ticket_transition_allowed(
            "closed", "open"))
        self.assertFalse(DBCore.ticket_transition_allowed(
            "closed", "resolved"))

    def test_resolved(self):
        self.assertTrue(DBCore.ticket_transition_allowed(
            "resolved", "closed"))
        self.assertTrue(DBCore.ticket_transition_allowed(
            "resolved", "in_progress"))
        self.assertFalse(DBCore.ticket_transition_allowed(
            "resolved", "waiting_user"))

    def test_legacy_source_normalized(self):
        self.assertTrue(DBCore.ticket_transition_allowed(
            "answered", "in_progress"))


class CannedCategoryTest(unittest.TestCase):
    def test_trim_and_cap(self):
        self.assertEqual(DBCore.canned_clean_category("  مالی  "), "مالی")
        self.assertEqual(DBCore.canned_clean_category(None), "")
        self.assertEqual(len(DBCore.canned_clean_category("x" * 100)), 40)


class RaceGuardStaticTest(unittest.TestCase):
    def test_conditional_update_with_retry(self):
        src = read("db", "core.py")
        i = src.index("async def ticket_set_status")
        chunk = src[i:i + 2500]
        self.assertIn("for _ in range(2)", chunk)
        self.assertIn("'status': t.get('status')", chunk)
        self.assertIn("'error': 'race'", chunk)


class AuditWiringStaticTest(unittest.TestCase):
    def test_bot_prio_audited(self):
        src = read("ticket.py")
        i = src.index("action == 'admin_prio'")
        chunk = src[i:i + 2500]
        self.assertIn("send_audit_log", chunk)
        self.assertIn("تغییر اولویت تیکت (ربات)", chunk)

    def test_bot_status_action_exists(self):
        src = read("ticket.py")
        self.assertIn("action == 'admin_status'", src)
        self.assertIn("ticket_set_status", src)

    def test_bot_fa_covers_all_statuses(self):
        src = read("ticket.py")
        i = src.index("TICKET_STATUS_FA = {")
        chunk = src[i:i + 600]
        for s in DBCore.TICKET_STATUSES:
            self.assertIn(f"'{s}'", chunk)

    def test_meta_patch_guarded(self):
        src = read("api", "routers", "web_admin.py")
        self.assertIn("ticket_set_status(tid, body.status)", src)

    def test_close_reopen_audit_status(self):
        src = read("api", "routers", "admin_panel.py")
        self.assertIn('before={"status": res.get("frm")}', src)

    def test_open_queue_is_non_closed(self):
        src = read("db", "core.py")
        i = src.index("async def ticket_get_all")
        chunk = src[i:i + 500]
        self.assertIn('"$ne": "closed"', chunk.replace("'", '"'))


if __name__ == "__main__":
    unittest.main()
