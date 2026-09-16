# -*- coding: utf-8 -*-
"""🌊 W7 (ممیزی) — فیچرگیتینگ مرکزی: FREE/SUB/TRIAL/DISABLED/ADMIN/QUOTA/policy/rollback/bypass.

runtime منطقی روی فیکِ ذخیره‌سازی (بدون Mongo) + متدهای واقعی db.core روی
کالکشن فیک + مایگریشن v4 واقعی. قراردادها از check_feature خوانده می‌شوند.
"""
import asyncio
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")

import core.access as acc
from core.errors import Code
from core.features import FEATURE_CATALOG, default_policy
from db.core import DBCore

ADMIN = 999
USER = 111


class FakeDB:
    """فیک سطح سرویس برای check_feature."""

    def __init__(self):
        self.policies = {}
        self.subs = {}
        self.active = set()
        self.plans = {}
        self.usage = {}
        self.events = []
        self.fail_policy = False
        self.fail_usage = False
        self.fail_sub = False
        self.get_policy_calls = 0

    async def get_feature_policy(self, feature):
        self.get_policy_calls += 1
        if self.fail_policy:
            raise ConnectionError("db down")
        doc = self.policies.get(feature)
        return dict(doc) if doc else None

    async def log_feature_event(self, feature, event, uid, extra=None):
        self.events.append((feature, event, uid, extra or {}))

    async def sub_get(self, uid):
        if self.fail_sub:
            raise ConnectionError("db down")
        return dict(self.subs.get(int(uid)) or {}) or None

    async def sub_is_active(self, uid):
        return int(uid) in self.active

    async def plan_for_sub(self, sub):
        return self.plans.get((sub or {}).get("plan_id"))

    async def feature_usage_get(self, uid, feature, kind):
        if self.fail_usage:
            raise ConnectionError("db down")
        return self.usage.get((int(uid), feature, kind), 0)


class FakeColl:
    """کالکشن فیک با رفتار نزدیک Mongo برای متدهای واقعی db.core."""

    def __init__(self):
        self.store = {}
        self.race_once = set()  # _idهایی که یک‌بار DuplicateKey می‌دهند

    async def find_one(self, filt):
        doc = self.store.get(filt.get("_id"))
        return dict(doc) if doc else None

    async def insert_one(self, doc):
        self.store[doc["_id"]] = dict(doc)

    async def update_one(self, filt, upd, upsert=False):
        _id = filt.get("_id")
        doc = self.store.get(_id) or ({"_id": _id} if upsert else None)
        if doc is None:
            return
        for k, v in (upd.get("$set") or {}).items():
            doc[k] = v
        self.store[_id] = doc

    async def find_one_and_update(self, filt, upd, upsert=False,
                                  return_document=None):
        from pymongo.errors import DuplicateKeyError
        _id = filt.get("_id")
        if _id in self.race_once:  # شبیه‌سازی race ساخت سند
            self.race_once.discard(_id)
            raise DuplicateKeyError("simulated race")
        lt = (filt.get("count") or {}).get("$lt")
        doc = self.store.get(_id)
        if doc is None:
            if lt is not None and not (0 < lt):
                raise DuplicateKeyError("limit reached")
            doc = {"_id": _id, "count": 0}
        elif lt is not None and not (doc.get("count", 0) < lt):
            raise DuplicateKeyError("limit reached")
        doc["count"] = doc.get("count", 0) + (upd.get("$inc") or {}).get("count", 0)
        for k, v in (upd.get("$set") or {}).items():
            doc[k] = v
        self.store[_id] = doc
        return dict(doc)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class W7AccessTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDB()
        self._db, acc.db = acc.db, self.fake
        self._admin, acc.ADMIN_ID = acc.ADMIN_ID, ADMIN
        acc.invalidate_policy_cache()

    def tearDown(self):
        acc.db = self._db
        acc.ADMIN_ID = self._admin
        acc.invalidate_policy_cache()

    def pol(self, feature, **kw):
        p = default_policy(feature)
        p.update(kw)
        self.fake.policies[feature] = p
        return p

    # ── پایه: FREE / ناشناخته ──
    def test_free_default_allows_stranger(self):
        r = run(acc.check_feature(USER, "question_bank"))
        self.assertTrue(r.allowed)
        self.assertEqual(r.reason, "entitled")

    def test_unknown_feature_403(self):
        r = run(acc.check_feature(USER, "nope"))
        self.assertFalse(r.allowed)
        self.assertEqual(r.code, Code.FORBIDDEN)
        self.assertEqual(r.http_status, 403)

    # ── kill switch (مالک را هم می‌بندد) ──
    def test_kill_switch_blocks_owner(self):
        self.pol("question_bank", enabled=False)
        r = run(acc.check_feature(ADMIN, "question_bank"))
        self.assertFalse(r.allowed)
        self.assertEqual(r.code, Code.FEATURE_DISABLED)
        self.assertTrue(r.http_status, 402)

    def test_disabled_mode_blocks_owner(self):
        self.pol("resources", access="disabled")
        r = run(acc.check_feature(ADMIN, "resources"))
        self.assertFalse(r.allowed)
        self.assertEqual(r.code, Code.FEATURE_DISABLED)

    # ── admin_only ──
    def test_admin_only(self):
        self.pol("wallet", access="admin_only")
        r = run(acc.check_feature(USER, "wallet"))
        self.assertFalse(r.allowed)
        self.assertEqual(r.code, Code.ADMIN_ONLY)
        r = run(acc.check_feature(ADMIN, "wallet"))
        self.assertTrue(r.allowed)
        self.assertTrue(r.is_owner)

    # ── بای‌پس مالک (ولی نه kill switch) ──
    def test_owner_bypass_subscription_and_quota(self):
        self.pol("mock_exam", access="subscription",
                 quota={"kind": "daily", "limit": 1})
        self.fake.usage[(ADMIN, "mock_exam", "daily")] = 99
        r = run(acc.check_feature(ADMIN, "mock_exam"))
        self.assertTrue(r.allowed)
        self.assertIsNone(r.quota_remaining)

    # ── اشتراک ──
    def test_subscription_required_variants(self):
        self.pol("question_bank", access="subscription")
        r = run(acc.check_feature(USER, "question_bank"))
        self.assertEqual(r.code, Code.SUB_REQUIRED)
        self.assertEqual(r.reason, "subscription_required")  # سازگاری legacy
        self.fake.subs[USER] = {"status": "pending"}
        r = run(acc.check_feature(USER, "question_bank"))
        self.assertEqual(r.code, Code.SUB_PENDING)
        self.fake.subs[USER] = {"status": "expired"}
        r = run(acc.check_feature(USER, "question_bank"))
        self.assertEqual(r.code, Code.SUB_EXPIRED)

    def test_subscriber_allowed(self):
        self.pol("question_bank", access="subscription")
        self.fake.subs[USER] = {"status": "active", "plan_id": "p1"}
        self.fake.active.add(USER)
        r = run(acc.check_feature(USER, "question_bank"))
        self.assertTrue(r.allowed)
        self.assertFalse(r.trial)

    # ── trial ──
    def test_trial_excluded(self):
        self.pol("mock_exam", access="subscription", trial_allowed=False)
        self.fake.subs[USER] = {"status": "active", "source": "trial"}
        self.fake.active.add(USER)
        r = run(acc.check_feature(USER, "mock_exam"))
        self.assertFalse(r.allowed)
        self.assertEqual(r.reason, "trial_excluded")
        self.assertTrue(r.trial)

    def test_trial_allowed_logs_event(self):
        self.pol("question_bank", access="subscription", trial_allowed=True)
        self.fake.subs[USER] = {"status": "active", "source": "trial"}
        self.fake.active.add(USER)
        r = run(acc.check_feature(USER, "question_bank"))
        self.assertTrue(r.allowed)
        self.assertTrue(r.trial)
        self.assertIn(("question_bank", "trial_feature_used", USER),
                      [(f, e, u) for f, e, u, _ in self.fake.events])

    # ── entitlement پلن ──
    def test_plan_excludes_feature(self):
        self.pol("mock_exam", access="subscription")
        self.fake.subs[USER] = {"status": "active", "plan_id": "basic"}
        self.fake.active.add(USER)
        self.fake.plans["basic"] = {"entitlements": {"mock_exam": False}}
        r = run(acc.check_feature(USER, "mock_exam"))
        self.assertFalse(r.allowed)
        self.assertEqual(r.code, Code.PLAN_EXCLUDES_FEATURE)

    def test_legacy_plan_full_access(self):
        self.pol("mock_exam", access="subscription")
        self.fake.subs[USER] = {"status": "active", "plan_id": "old"}
        self.fake.active.add(USER)
        self.fake.plans["old"] = {"name": "قدیمی"}  # بدون entitlements
        r = run(acc.check_feature(USER, "mock_exam"))
        self.assertTrue(r.allowed)

    # ── سهمیه ──
    def test_quota_exhausted_429(self):
        self.pol("pdf_generation", access="subscription",
                 quota={"kind": "monthly", "limit": 2})
        self.fake.subs[USER] = {"status": "active"}
        self.fake.active.add(USER)
        self.fake.usage[(USER, "pdf_generation", "monthly")] = 2
        r = run(acc.check_feature(USER, "pdf_generation"))
        self.assertFalse(r.allowed)
        self.assertEqual(r.code, Code.QUOTA_EXHAUSTED)
        self.assertEqual(r.http_status, 429)

    def test_quota_remaining_reported(self):
        self.pol("pdf_generation", access="subscription",
                 quota={"kind": "monthly", "limit": 5})
        self.fake.subs[USER] = {"status": "active"}
        self.fake.active.add(USER)
        self.fake.usage[(USER, "pdf_generation", "monthly")] = 2
        r = run(acc.check_feature(USER, "pdf_generation"))
        self.assertTrue(r.allowed)
        self.assertEqual(r.quota_remaining, 3)

    def test_ai_special_skips_generic_peek(self):
        self.pol("ai_chat", quota={"kind": "daily", "limit": 3})
        self.fake.usage[(USER, "ai_chat", "daily")] = 99
        r = run(acc.check_feature(USER, "ai_chat"))
        self.assertTrue(r.allowed)
        self.assertIsNone(r.quota_remaining)

    # ── زمان‌بندی ──
    def test_scheduled_policy(self):
        from datetime import datetime, timedelta, timezone
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        self.pol("resources", access="free", pending_access="subscription",
                 effective_from=past)
        r = run(acc.check_feature(USER, "resources"))
        self.assertFalse(r.allowed)  # گذشته ⇒ subscription اعمال شده
        self.pol("references", access="free", pending_access="subscription",
                 effective_from=future)
        r = run(acc.check_feature(USER, "references"))
        self.assertTrue(r.allowed)  # آینده ⇒ هنوز free

    # ── کش + ابطال ──
    def test_policy_cache_and_invalidation(self):
        self.pol("tickets", access="subscription")
        run(acc.check_feature(USER, "tickets"))
        run(acc.check_feature(USER, "tickets"))
        self.assertEqual(self.fake.get_policy_calls, 1)
        acc.invalidate_policy_cache("tickets")
        run(acc.check_feature(USER, "tickets"))
        self.assertEqual(self.fake.get_policy_calls, 2)

    # ── fail-safe ──
    def test_policy_unavailable_503_without_cache(self):
        self.fake.fail_policy = True
        r = run(acc.check_feature(USER, "question_bank"))
        self.assertFalse(r.allowed)
        self.assertEqual(r.code, Code.POLICY_UNAVAILABLE)
        self.assertEqual(r.http_status, 503)

    def test_stale_cache_used_when_db_down(self):
        import time as _t
        self.pol("tickets", access="free")
        run(acc.check_feature(USER, "tickets"))
        self.assertEqual(self.fake.get_policy_calls, 1)
        # منقضی‌کردن کش + قطع DB ⇒ همان کش کهنه
        feat = "tickets"
        pol, _ = acc._POLICY_CACHE[feat]
        acc._POLICY_CACHE[feat] = (pol, _t.monotonic() - 1)
        self.fake.fail_policy = True
        r = run(acc.check_feature(USER, "tickets"))
        self.assertTrue(r.allowed)

    def test_sub_read_failure_503(self):
        self.pol("question_bank", access="subscription")
        self.fake.fail_sub = True
        r = run(acc.check_feature(USER, "question_bank"))
        self.assertFalse(r.allowed)
        self.assertEqual(r.code, Code.POLICY_UNAVAILABLE)

    # ── نسخه raiseکننده + wrapper قدیمی ──
    def test_require_feature_access_raises_402(self):
        from fastapi import HTTPException
        self.pol("question_bank", access="subscription")
        with self.assertRaises(HTTPException) as cm:
            run(acc.require_feature_access(USER, "question_bank"))
        self.assertEqual(cm.exception.status_code, 402)
        self.assertEqual(cm.exception.detail["code"], Code.SUB_REQUIRED)
        self.assertEqual(cm.exception.detail["feature"], "question_bank")

    def test_has_access_legacy_wrapper(self):
        self.pol("question_bank", access="free")
        r = run(acc.has_access(USER))
        self.assertTrue(r.allowed)


class W7PolicyStoreTest(unittest.TestCase):
    """متدهای واقعی db.core روی کالکشن فیک: set/rollback/consume."""

    def setUp(self):
        self.db = DBCore.__new__(DBCore)
        self.db.feature_policies = FakeColl()
        self.db.feature_usage = FakeColl()

    def test_set_rollback_redo(self):
        run(self.db.set_feature_policy("question_bank", {"access": "free"}, 1, "a"))
        run(self.db.set_feature_policy("question_bank", {"access": "subscription"}, 1, "a"))
        cur = run(self.db.feature_policies.find_one({"_id": "question_bank"}))
        self.assertEqual(cur["access"], "subscription")
        self.assertEqual(cur["prev"]["access"], "free")
        r1 = run(self.db.rollback_feature_policy("question_bank", 1, "a"))
        self.assertEqual(r1["after"]["access"], "free")  # rollback
        r2 = run(self.db.rollback_feature_policy("question_bank", 1, "a"))
        self.assertEqual(r2["after"]["access"], "subscription")  # redo

    def test_rollback_without_prev_none(self):
        self.assertIsNone(run(self.db.rollback_feature_policy("wallet", 1, "a")))

    def test_consume_atomic_limit(self):
        ok, used = run(self.db.feature_consume(USER, "pdf_generation", "daily", 2))
        self.assertTrue(ok)
        self.assertEqual(used, 1)
        ok, used = run(self.db.feature_consume(USER, "pdf_generation", "daily", 2))
        self.assertTrue(ok)
        self.assertEqual(used, 2)
        ok, used = run(self.db.feature_consume(USER, "pdf_generation", "daily", 2))
        self.assertFalse(ok)  # سقف پر است، نه واحد مجانی
        self.assertEqual(used, 2)

    def test_consume_race_retries_once(self):
        key = f"{USER}:mock_exam:{self.db._usage_period('daily')}"
        self.db.feature_usage.race_once.add(key)
        ok, used = run(self.db.feature_consume(USER, "mock_exam", "daily", 5))
        self.assertTrue(ok)
        self.assertEqual(used, 1)  # تلاش مجدد موفق؛ دقیقاً یک واحد

    def test_consume_noop_without_quota(self):
        ok, used = run(self.db.feature_consume(USER, "tickets", "none", 0))
        self.assertTrue(ok)
        self.assertEqual(used, 0)


class W7MigrationTest(unittest.TestCase):
    def test_v4_seed_and_enforced_and_idempotent(self):
        from db import migrations
        db = FakeColl()
        fake = FakeColl()  # setting جدا
        settings = {"subscription_enforced": True}

        class MDB:
            feature_policies = db

            async def get_setting(self, k, d=None):
                return settings.get(k, d)

        m = MDB()
        n = run(migrations._migrate_v4_feature_policies(m))
        self.assertEqual(n, len(FEATURE_CATALOG))
        qb = run(db.find_one({"_id": "question_bank"}))
        self.assertEqual(qb["access"], "subscription")
        ai = run(db.find_one({"_id": "ai_chat"}))
        self.assertEqual(ai["access"], "free")
        n2 = run(migrations._migrate_v4_feature_policies(m))
        self.assertEqual(n2, 0)  # idempotent
        self.assertEqual(len(db.store), len(FEATURE_CATALOG))


if __name__ == "__main__":
    unittest.main()
