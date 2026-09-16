# -*- coding: utf-8 -*-
"""🌊 W10 (ممیزی) — ریت‌لیمیت جراحی + RBAC ربات + پین deps.

نیمه‌خالص + ایستا؛ بدون Mongo و شبکه.
"""
import asyncio
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_had_uri = "MONGODB_URI" in os.environ
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")

from api import rate_limit as rl

if not _had_uri:
    del os.environ["MONGODB_URI"]


def read(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


class LimiterCoreTest(unittest.TestCase):
    def test_allow_then_block_with_retry_after(self):
        async def go():
            rl._store.clear()
            for _ in range(3):
                ok, _ = await rl._check("t:key1", 3, 60)
                self.assertTrue(ok)
            ok, retry = await rl._check("t:key1", 3, 60)
            self.assertFalse(ok)
            self.assertGreaterEqual(retry, 1)
        asyncio.run(go())

    def test_window_reset(self):
        async def go():
            rl._store.clear()
            rl._store["t:key2"] = (0.0, 99, 60)  # پنجره‌ی منقضی
            ok, _ = await rl._check("t:key2", 3, 60)
            self.assertTrue(ok)
        asyncio.run(go())

    def test_rate_limit_user_raises_429(self):
        from fastapi import HTTPException
        async def go():
            rl._store.clear()
            with self.assertRaises(HTTPException) as cm:
                for _ in range(4):
                    await rl.rate_limit_user(777, "w10probe", 3, 60)
            self.assertEqual(cm.exception.status_code, 429)
            self.assertIn("Retry-After", cm.exception.headers)
        asyncio.run(go())


class NewLimitsStaticTest(unittest.TestCase):
    def test_user_endpoints(self):
        self.assertIn('"search_q", 30, 60',
                      read("api", "routers", "global_search.py"))
        self.assertIn('"leaderboard", 60, 60',
                      read("api", "routers", "dashboard.py"))

    def test_admin_heavy_endpoints(self):
        ap = read("api", "routers", "admin_panel.py")
        self.assertIn('"broadcast_send", 5, 60', ap)
        self.assertIn('"export_excel", 10, 60', ap)
        wa = read("api", "routers", "web_admin.py")
        for scope in ("export_users_csv", "export_tickets_csv",
                      "bulk_preview", "tickets_bulk"):
            self.assertIn(f'"{scope}", 10, 60', wa)

    def test_csv_status_pattern_covers_w9(self):
        wa = read("api", "routers", "web_admin.py")
        self.assertIn("in_progress|waiting_user|resolved", wa)


class BotRbacStaticTest(unittest.TestCase):
    def test_ticket_gates_migrated(self):
        src = read("ticket.py")
        self.assertIn("async def _tperm", src)
        self.assertIn("async def _is_ticket_staff", src)
        # فقط fallback داخل _tperm مانده
        self.assertEqual(src.count("uid == ADMIN_ID"), 1)
        self.assertIn("_tperm(uid, 'tickets.manage')", src)
        self.assertIn("_tperm(uid, 'tickets.reply')", src)
        self.assertIn("actor_id=uid", src)

    def test_router_and_sub_migrated(self):
        mr = read("message_router.py")
        self.assertIn("'search_user': 'users.view'", mr)
        self.assertIn("has_permission(uid, 'schedules.manage')", mr)
        self.assertIn("has_permission(uid, _need)", mr)
        sa = read("subscription_admin.py")
        self.assertIn("has_permission(uid, 'subscription.manage')", sa)


class PinsStaticTest(unittest.TestCase):
    def test_all_pinned(self):
        req = read("requirements.txt")
        for pin in ("httpx==0.28.1", "imageio-ffmpeg==0.6.0",
                    "cryptography==50.0.1"):
            self.assertIn(pin, req)


if __name__ == "__main__":
    unittest.main()
