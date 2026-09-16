# -*- coding: utf-8 -*-
"""🛡 AUDIT-FIX — قرارداد بکاپ/بازیابی: هرچه صادر می‌شود باید بازیابی شود.

Pure-fake (بدون Mongo): مجموعه‌های جعلی با همان API حداقلی motor،
seed حداقلی، سپس چرخه‌ی کامل:
  build_full_backup_data → _encode (gzip) → _decode → _restore_section
و اثبات‌ها:
  ۱) همه‌ی ۲۱ سکشن (شامل wallets/ring/growth/ops جدید) صادر و بازیابی می‌شوند؛
  ۲) sha256 روی همان شکلی که در فایل می‌نشیند حساب می‌شود (hash-what-you-ship)؛
  ۳) datetimeهای BSON با تگ صریح round-trip می‌شوند (TTL/کوئری تاریخ نمی‌شکند)؛
  ۴) بکاپ‌های legacy (expires_at رشته‌ای) هم revive می‌شوند؛
  ۵) restore دوباره‌اجرا idempotent است (merge/upsert، بدون تکثیر)؛
  ۶) سطح ظرفیت/ناسازگاری شمارش، بکاپ را fail-closed می‌کند.
"""
import asyncio
import copy
import gzip
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# ایمپورت database در ساخت کلاینت lazy است؛ URI ساختگی فقط برای لحظه‌ی
# import لازم است و بلافاصله پاک می‌شود تا skipUnless(MONGODB_URI) فایل‌های
# دیگر (content_admin/video/...) دست‌نخورده بماند — این سوئیت pure-fake است.
_MONGO_WAS_SET = "MONGODB_URI" in os.environ
_ADMIN_WAS_SET = "ADMIN_ID" in os.environ
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")
os.environ.setdefault("ADMIN_ID", "1")

from bson import ObjectId  # noqa: E402

import backup  # noqa: E402

if not _MONGO_WAS_SET:
    os.environ.pop("MONGODB_URI", None)
if not _ADMIN_WAS_SET:
    os.environ.pop("ADMIN_ID", None)
del _MONGO_WAS_SET, _ADMIN_WAS_SET
from backup import (  # noqa: E402
    BackupIntegrityError,
    _decode_backup_bytes,
    _encode_backup_bytes,
    _restore_section,
    _revive_datetypes,
    _sections_digest,
    _snapshot_collection,
    build_backup_caption,
    build_full_backup_data,
    build_section_backup_data,
)

ALL_SECTIONS = {
    'users', 'basic_science', 'references', 'qbank', 'schedules', 'faq',
    'tickets', 'access_control', 'subscription_system', 'grades', 'settings',
    'logs', 'stats', 'communications', 'ai', 'prestige', 'webadmin_state',
    'wallets', 'ring', 'growth', 'ops',
}
NEW_SECTIONS = {'wallets', 'ring', 'growth', 'ops'}


# ── fakes ──────────────────────────────────────────────
class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def sort(self, *a, **k):
        return self

    async def to_list(self, n):
        return copy.deepcopy(self._rows[:n])


class FakeCollection:
    """حداقل API موتور که بکاپ/بازیابی استفاده می‌کند."""

    def __init__(self, docs=None):
        self.docs = copy.deepcopy(list(docs or []))

    async def count_documents(self, *a, **k):
        return len(self.docs)

    def find(self, *a, **k):
        return _FakeCursor(self.docs)

    async def find_one(self, flt=None):
        flt = flt or {}
        for d in self.docs:
            if all(d.get(k) == v for k, v in flt.items()):
                return copy.deepcopy(d)
        return None

    async def replace_one(self, flt, doc, upsert=False, **kw):
        for i, d in enumerate(self.docs):
            if all(d.get(k) == v for k, v in flt.items()):
                self.docs[i] = copy.deepcopy(doc)
                return
        if upsert:
            self.docs.append(copy.deepcopy(doc))

    async def insert_one(self, doc, **kw):
        self.docs.append(copy.deepcopy(doc))

    async def insert_many(self, docs, **kw):
        self.docs.extend(copy.deepcopy(list(docs)))

    async def update_one(self, flt, update, upsert=False, **kw):
        for d in self.docs:
            if all(d.get(k) == v for k, v in flt.items()):
                for k, v in (update.get('$set') or {}).items():
                    d[k] = copy.deepcopy(v)
                return
        if upsert:
            nd = dict(flt)
            nd.update(copy.deepcopy(update.get('$set') or {}))
            self.docs.append(nd)


class FakeRingCols:
    SUBS = ['profiles', 'queue', 'sessions', 'blocks', 'reports', 'bans',
            'ratings', 'evidence', 'audit', 'limits', 'daily', 'counters']

    def __init__(self):
        for n in self.SUBS:
            setattr(self, n, FakeCollection())


class FakeDB:
    def __init__(self):
        self._cols = {}
        self.ring_cols = FakeRingCols()

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        if name not in self._cols:
            self._cols[name] = FakeCollection()
        return self._cols[name]


DT = datetime(2026, 9, 10, 3, 5, tzinfo=timezone.utc)


def make_source_db() -> FakeDB:
    db = FakeDB()
    db.users.docs = [
        {'_id': ObjectId(), 'user_id': 1, 'name': 'تست',
         'last_seen': DT},  # datetime بومی → باید تگ شود و برگردد
    ]
    db.exam_sessions.docs = [
        {'_id': ObjectId(), 'session_id': 'abc123', 'user_id': 1,
         'started_at': '2026-09-10T03:00:00+00:00',  # رشته می‌ماند
         'expires_at': DT},  # بومی → revive
    ]
    db.wallets.docs = [{'_id': ObjectId(), 'user_id': 1, 'balance': 50000}]
    db.wallet_transactions.docs = [
        {'_id': ObjectId(), 'user_id': 1, 'amount': 50000, 'kind': 'deposit'}]
    db.referrals.docs = [{'_id': ObjectId(), 'referrer_id': 1, 'invitee_id': 2}]
    db.ring_cols.profiles.docs = [{'_id': ObjectId(), 'user_id': 1, 'rep': 10}]
    db.schedules.docs = [{'_id': ObjectId(), 'type': 'exam',
                          'lesson': 'تشریح', 'date': '2026-09-26', 'time': '08:00'}]
    db.audit_outbox.docs = [{'_id': ObjectId(), 'kind': 'audit', 'sent': False}]
    db.settings.docs = [{'_id': 'global', 'auto_backup_hour': 3,
                         'ai_api_key': 'SECRET-MUST-NOT-LEAK'}]
    db.grades.docs = [{'_id': ObjectId(), 'user_id': 1, 'score': 18.5}]
    return db


async def _restore_all(sections: dict, target_db) -> dict:
    """همان حلقه‌ی dispatch که backup_confirm_restore انجام می‌دهد."""
    old, backup.db = backup.db, target_db
    try:
        out = {}
        for sec_name, sec_data in sections.items():
            out[sec_name] = await _restore_section(sec_name, sec_data)
        return out
    finally:
        backup.db = old


# ── tests ──────────────────────────────────────────────
class BackupCoverageTests(unittest.TestCase):
    def test_full_backup_has_all_sections(self):
        src = make_source_db()
        old, backup.db = backup.db, src
        try:
            data = asyncio.run(build_full_backup_data())
        finally:
            backup.db = old
        self.assertEqual(data['backup_version'], '3.1')
        self.assertEqual(set(data['sections'].keys()), ALL_SECTIONS)
        for sec in NEW_SECTIONS:
            sub = data['sections'][sec]
            total = sum(v.get('count', 0) for v in sub.values()
                        if isinstance(v, dict))
            self.assertGreaterEqual(total, 1, f'section {sec} exported empty')
        integ = data['integrity']
        self.assertTrue(integ['complete'])
        self.assertIn('sha256_sections', integ)
        self.assertIn('wallets', integ['datasets'])
        self.assertIn('ring_profiles', integ['datasets'])
        self.assertIn('referrals', integ['datasets'])
        # نسخه‌ی قدیمیِ prestige دیگر exam_sessions را دوباره صادر نمی‌کند
        self.assertNotIn('exam_sessions', data['sections']['prestige'])
        self.assertIn('exams', data['sections']['qbank'])
        self.assertIn('files_meta', data['sections']['qbank'])

    def test_secrets_never_enter_artifacts(self):
        src = make_source_db()
        old, backup.db = backup.db, src
        try:
            data = asyncio.run(build_full_backup_data())
        finally:
            backup.db = old
        blob = json.dumps(data, ensure_ascii=False, default=str)
        self.assertNotIn('SECRET-MUST-NOT-LEAK', blob)
        self.assertEqual(
            data['sections']['settings']['data'].get('auto_backup_hour'), 3)

    def test_exclusion_lists_documented(self):
        src = make_source_db()
        old, backup.db = backup.db, src
        try:
            data = asyncio.run(build_full_backup_data())
        finally:
            backup.db = old
        integ = data['integrity']
        self.assertIn('web_admin_sessions', integ['excluded_security_data'])
        self.assertIn('bot_notifications', integ['excluded_ephemeral_data'])
        self.assertTrue(integ['exclusion_reason'])


class BackupEncodingTests(unittest.TestCase):
    def test_gzip_roundtrip_and_shrink(self):
        src = make_source_db()
        old, backup.db = backup.db, src
        try:
            data = asyncio.run(build_full_backup_data())
        finally:
            backup.db = old
        blob = _encode_backup_bytes(data)
        self.assertEqual(blob[:2], gzip.compress(b'x')[:2])  # magic
        plain = json.dumps(data, ensure_ascii=False, default=str).encode('utf-8')
        self.assertLess(len(blob), len(plain))
        back = _decode_backup_bytes(blob)
        self.assertEqual(back['backup_version'], '3.1')
        self.assertEqual(set(back['sections'].keys()), ALL_SECTIONS)

    def test_legacy_plain_json_decodes(self):
        legacy = {'backup_version': '1.0', 'sections': {'users': {'data': []}}}
        raw = json.dumps(legacy).encode('utf-8')
        self.assertEqual(_decode_backup_bytes(raw)['backup_version'], '1.0')

    def test_sha_matches_what_ships(self):
        """هشِ ذخیره‌شده دقیقاً روی بایت‌های فایل (پس از decode) برقرار است."""
        src = make_source_db()
        old, backup.db = backup.db, src
        try:
            data = asyncio.run(build_full_backup_data())
        finally:
            backup.db = old
        shipped = _decode_backup_bytes(_encode_backup_bytes(data))
        self.assertEqual(
            _sections_digest(shipped['sections']),
            shipped['integrity']['sha256_sections'])

    def test_sha_tamper_detected(self):
        src = make_source_db()
        old, backup.db = backup.db, src
        try:
            data = asyncio.run(build_full_backup_data())
        finally:
            backup.db = old
        expect = data['integrity']['sha256_sections']
        data['sections']['users']['data'].append({'_id': 'x', 'evil': True})
        self.assertNotEqual(_sections_digest(data['sections']), expect)

    def test_snapshot_count_guard_fail_closed(self):
        class _Drifty(FakeCollection):
            def __init__(self):
                super().__init__([{'_id': 'a'}])
                self._calls = 0

            async def count_documents(self, *a, **k):
                self._calls += 1
                return [0, 1, 1, 0][min(self._calls - 1, 3)]

        manifest = {}
        with self.assertRaises(BackupIntegrityError):
            asyncio.run(_snapshot_collection(_Drifty(), 100, 'drifty', manifest))
        self.assertFalse(manifest['drifty']['complete'])


class RestoreRoundtripTests(unittest.TestCase):
    def _shipped_sections(self):
        src = make_source_db()
        old, backup.db = backup.db, src
        try:
            data = asyncio.run(build_full_backup_data())
        finally:
            backup.db = old
        shipped = _decode_backup_bytes(_encode_backup_bytes(data))
        return shipped['sections']

    def test_restore_into_empty_db(self):
        sections = self._shipped_sections()
        target = FakeDB()
        restored = asyncio.run(_restore_all(sections, target))
        for sec in ALL_SECTIONS:
            self.assertIn(sec, restored, f'section {sec} not restored')
        # کاربران + datetime بومی
        self.assertEqual(len(target.users.docs), 1)
        u = target.users.docs[0]
        self.assertIsInstance(u['_id'], ObjectId)
        self.assertIsInstance(u['last_seen'], datetime)
        self.assertEqual(u['last_seen'], DT)
        # سشن آزمون: رشته‌ها رشته، expires_at بومی
        ex = target.exam_sessions.docs[0]
        self.assertIsInstance(ex['expires_at'], datetime)
        self.assertEqual(ex['expires_at'], DT)
        self.assertIsInstance(ex['started_at'], str)
        # سکشن‌های جدید
        self.assertEqual(len(target.wallets.docs), 1)
        self.assertEqual(len(target.wallet_transactions.docs), 1)
        self.assertEqual(len(target.referrals.docs), 1)
        self.assertEqual(len(target.ring_cols.profiles.docs), 1)
        # تنظیمات merge می‌شود و secret ندارد
        g = asyncio.run(target.settings.find_one({'_id': 'global'}))
        self.assertEqual(g['auto_backup_hour'], 3)
        self.assertNotIn('ai_api_key', g)

    def test_restore_idempotent_merge(self):
        sections = self._shipped_sections()
        target = FakeDB()
        asyncio.run(_restore_all(sections, target))
        before = {k: len(c.docs) for k, c in target._cols.items()}
        asyncio.run(_restore_all(sections, target))
        after = {k: len(c.docs) for k, c in target._cols.items()}
        self.assertEqual(before, after)
        self.assertEqual(len(target.ring_cols.profiles.docs), 1)

    def test_legacy_string_expires_at_revived(self):
        """بکاپ قدیمی (قبل از تگ): expires_at رشته‌ای → datetime بومی."""
        target = FakeDB()
        old, backup.db = backup.db, target
        try:
            n = asyncio.run(_restore_section(
                'qbank',
                {'exams': {'count': 1, 'data': [
                    {'_id': str(ObjectId()), 'session_id': 'legacy1',
                     'expires_at': '2026-09-10T03:05:00+00:00'}]}}))
        finally:
            backup.db = old
        self.assertEqual(n, 1)
        self.assertIsInstance(target.exam_sessions.docs[0]['expires_at'], datetime)

    def test_legacy_prestige_exam_sessions_still_restore(self):
        target = FakeDB()
        old, backup.db = backup.db, target
        try:
            asyncio.run(_restore_section(
                'prestige',
                {'history': {'count': 0, 'data': []},
                 'feed_reactions': {'count': 0, 'data': []},
                 'exam_sessions': {'count': 1, 'data': [
                     {'_id': str(ObjectId()), 'session_id': 'old1',
                      'expires_at': '2026-09-10T03:05:00+00:00'}]}}))
        finally:
            backup.db = old
        self.assertEqual(len(target.exam_sessions.docs), 1)
        self.assertIsInstance(target.exam_sessions.docs[0]['expires_at'], datetime)

    def test_new_section_files_roundtrip(self):
        for sec in sorted(NEW_SECTIONS):
            src = make_source_db()
            old, backup.db = backup.db, src
            try:
                data = asyncio.run(build_section_backup_data(sec))
            finally:
                backup.db = old
            target = FakeDB()
            old2, backup.db = backup.db, target
            try:
                # همان شکل dispatch فایلِ بخشی در confirm_restore
                n = asyncio.run(_restore_section(sec, data))
            finally:
                backup.db = old2
            expect = sum(v.get('count', 0) for v in data.values()
                         if isinstance(v, dict))
            self.assertEqual(n, expect, f'section file {sec}')

    def test_revive_ignores_plain_dicts(self):
        doc = {'a': {'b': 1}, 'c': [{'$__hxdt': 'not-a-date'}]}
        self.assertEqual(_revive_datetypes(doc), doc)


class BackupCaptionTests(unittest.TestCase):
    def test_auto_caption_jalali_no_gregorian(self):
        import re
        cap = build_backup_caption(
            {'summary': {'users': 10, 'lessons': 5, 'questions': 7,
                         'tickets': 1, 'subscriptions': 3, 'wallets': 4}},
            2_621_440, True)
        self.assertIn('بکاپ خودکار روزانه', cap)
        self.assertIn('🔐', cap)
        self.assertIn('2.5 MB', cap)
        self.assertIn('، ساعت', cap)  # قالب بلند جلالی
        self.assertIsNone(re.search(r'20\d\d-\d\d', cap))

    def test_section_caption_fallback(self):
        cap = build_backup_caption(
            {'description': 'کیف پول‌ها و تراکنش‌ها',
             'wallets': {'count': 2}, 'transactions': {'count': 5}},
            1024, False, title='X')
        self.assertIn('رکوردها: 7', cap)
        self.assertIn('🔓', cap)


class JalaliScheduleNotifyTests(unittest.TestCase):
    def test_updated_exam_notification_is_jalali(self):
        from types import SimpleNamespace

        from db.content import DBContent

        inserted, inbox = [], []

        async def _insert_many(docs):
            inserted.extend(docs)

        async def _inbox_add_many(docs):
            inbox.extend(docs)

        async def _notif_users(pref, group=None):
            return [{'user_id': 1}]

        stub = SimpleNamespace(
            normalize_group=lambda g: g or 'هر دو',
            notif_users=_notif_users,
            bot_notifs=SimpleNamespace(insert_many=_insert_many),
            inbox_add_many=_inbox_add_many,
        )
        item = {'type': 'exam', 'lesson': 'مقدمات علوم تشریح',
                'teacher': 'دکتر زمانی', 'date': '2026-09-26',
                'time': '08:00', 'location': 'حکیم', 'group': 'هر دو'}
        res = asyncio.run(DBContent.schedule_notify_event(stub, item, 'updated'))
        self.assertEqual(res['notified'], 1)
        text = inserted[0]['text']
        body = inbox[0]['body']
        self.assertIn('🔔', text)
        self.assertIn('امتحان به‌روزرسانی شد', text)
        self.assertEqual(inbox[0]['title'], '🔔 امتحان به‌روزرسانی شد')
        for payload in (text, body):
            self.assertNotIn('2026-09-26', payload)
            self.assertIn('۰۸:۰۰', payload)
            self.assertIn('۴ مهر ۱۴۰۵', payload)


class BackupWiringStaticTests(unittest.TestCase):
    def test_new_sections_wired_in_source(self):
        src = ROOT.joinpath('backup.py').read_text(encoding='utf-8')
        for token in ["'wallets'", "'ring'", "'growth'", "'ops'",
                      'db.ring_cols', 'db_counters', '_sections_digest',
                      '_encode_backup_bytes', '_decode_backup_bytes',
                      'build_backup_caption']:
            self.assertIn(token, src)
        bot = ROOT.joinpath('bot.py').read_text(encoding='utf-8')
        self.assertIn('build_backup_caption', bot)
        self.assertIn('.json.gz', bot)
        content = ROOT.joinpath('db', 'content.py').read_text(encoding='utf-8')
        self.assertIn('format_date_fa(date', content)


if __name__ == '__main__':
    unittest.main()
