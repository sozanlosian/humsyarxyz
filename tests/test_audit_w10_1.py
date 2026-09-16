# -*- coding: utf-8 -*-
"""🌊 W10.1 — یکپارچگی تیکت + رگرسیون ۴۲۲ تب‌ها.

ایستا؛ بدون Mongo و شبکه. مهم‌ترین تست: کلیدهای تب وب‌ادمین
باید زیرمجموعه‌ی الگوی بک‌اند باشند (گارد skew فرانت/بک).
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


class SkewGuardTest(unittest.TestCase):
    def test_webadmin_tabs_subset_of_backend_pattern(self):
        jsx = read("webadmin", "src", "pages", "Tickets.jsx")
        m = re.search(r"\{\[\[(.*?)\]\]\.map\(\(\[k, v\]\)",
                      jsx.replace("\n", " "))
        self.assertIsNotNone(m, "tabs array پیدا نشد")
        keys = set(re.findall(r"\['([^']*)',\s*'[^']*'\]", m.group(1)))
        keys.discard("")
        wa = read("api", "routers", "web_admin.py")
        pats = re.findall(r'pattern="\^\(([^)]+)\)\$"', wa)
        ticket_pats = [p for p in pats if "open" in p and "closed" in p]
        self.assertTrue(ticket_pats, "الگوی status تیکت پیدا نشد")
        allowed = set(ticket_pats[0].split("|"))
        # saved-viewهای قدیمی answered هم باید پاس شوند
        self.assertIn("answered", allowed)
        self.assertTrue(keys <= allowed,
                        f"تب‌های بدون پشتیبانی بک‌اند: {keys - allowed}")

    def test_bot_filters_are_internal_values(self):
        src = read("ticket.py")
        vals = set(re.findall(r"ticket:admin_filter:status:(\w+)", src))
        self.assertTrue(vals <= {"open", "closed", "all"}, vals)


class UnityStaticTest(unittest.TestCase):
    def test_row_badge_knows_new_statuses(self):
        jsx = read("webadmin", "src", "pages", "Tickets.jsx")
        self.assertIn("waiting_user: 'منتظر کاربر'", jsx)
        self.assertIn("in_progress: 'در حال بررسی'", jsx)

    def test_analytics_open_is_non_closed_sum(self):
        jsx = read("webadmin", "src", "pages", "Tickets.jsx")
        self.assertIn("analytics.status?.in_progress", jsx)
        self.assertIn("analytics.status?.waiting_user", jsx)
        self.assertIn("analytics.status?.resolved", jsx)

    def test_bot_user_counts_non_closed(self):
        src = read("ticket.py")
        self.assertNotIn("t['status'] == 'open'", src)
        self.assertIn("ticket_norm_status(t.get('status')) != 'closed'",
                      src)

    def test_bot_user_detail_shows_priority(self):
        src = read("ticket.py")
        self.assertGreaterEqual(src.count("TICKET_PRIORITY_FA.get"), 2)

    def test_admin_list_normalizes_status(self):
        ap = read("api", "routers", "admin_panel.py")
        self.assertGreaterEqual(
            ap.count('"status": db.ticket_norm_status(t.get("status"))'),
            2)

    def test_miniapp_shows_sla_expectation(self):
        mini = read("miniapp", "src", "pages", "Me", "Tickets.jsx")
        self.assertIn("هدف پاسخ‌گویی", mini)
        self.assertIn("ticket.sla?.sla_hours", mini)


if __name__ == "__main__":
    unittest.main()
