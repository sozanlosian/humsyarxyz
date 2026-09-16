# -*- coding: utf-8 -*-
"""🌊 W6 (ممیزی) — اعتماد و پول‌سازی: RBAC-legacy، سهمیه AI پلنی، trial، PERF-02/03.

۱) گارد ایستا (همیشه اجرا): سیم‌کشی همه‌ی آیتم‌ها + نبود legacy.
۲) runtime منطقی (نیازمند deps سبک؛ بدون Mongo): منطق واقعی trial_claim،
   رقابت دابل‌کلیک، ماتریس ai_limit، timeout سرچ، کش PDF — روی فیکِ ذخیره‌سازی.
۳) runtime با Mongo محلی (DB-gated): trial و resolver واقعی.

داده با پیشوند w6؛ در پایان پاک می‌شود. loop مشترک (tests/_rtloop).
"""
import asyncio
import os
import socket
import sys
import unittest
from pathlib import Path
from types import MethodType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# ایمپورت database در ساخت کلاینت lazy است؛ URI ساختگی برای import کافی است
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017")

try:
    from db.core import DBCore  # noqa: F401
    from db.finance import DBFinance  # noqa: F401
    import api.routers.global_search as gs  # noqa: F401
    import question_bank.exam as exam_mod  # noqa: F401
    import qbank  # noqa: F401
    _DEPS_OK = True
    _DEPS_ERR = ""
except Exception as e:  # pragma: no cover — محیط بدون deps
    _DEPS_OK = False
    _DEPS_ERR = str(e)

W6_UID = 891601


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


class W6StaticTests(unittest.TestCase):
    """گاردهای ایستای W6."""

    def test_rbac_no_legacy_left(self):
        for f in ("admin_panel", "ai_management", "subscription_management",
                  "web_admin"):
            src = read("api", "routers", f + ".py")
            self.assertNotIn("get_admin_user", src, f)

    def test_rbac_uniform_routers(self):
        ai = read("api", "routers", "ai_management.py")
        self.assertEqual(ai.count('require_perm("ai.manage")'), 14)
        # نوشتن سکرت با actor تفویض‌شده باید audit داشته باشد (بدون ماده‌ی کلید)
        self.assertIn("ثبت کلید API هوشیار", ai)
        self.assertIn("حذف کلید API هوشیار", ai)
        sm = read("api", "routers", "subscription_management.py")
        # 🌊 W8/B1: ‏۳۰ قبلی + ۳ فمیلی (plan detail/members/remove)
        self.assertEqual(sm.count('require_perm("subscription.manage")'), 33)

    def test_rbac_web_admin_groups(self):
        wa = read("api", "routers", "web_admin.py")
        self.assertEqual(wa.count('_perm("questions.import")'), 8)
        # ۱۰ مورد از قبل بود (کاتالوگ وب‌ادمین) + ۸ مهاجرتی این موج
        self.assertEqual(wa.count('_perm("ai.manage")'), 18)

    def test_rbac_admin_panel_map(self):
        ap = read("api", "routers", "admin_panel.py")
        # 🌊 W8/B3: ‏۵۵ قبلی + ۴ پاسخ آماده (canned CRUD)
        self.assertEqual(ap.count("require_perm("), 59)
        # نمونه‌برداری نگاشت (مسیر → مجوز): هر مسیر باید همان مجوز همسایه‌اش را داشته باشد
        for route, perm in (
            ('"/stats"', '"stats.view"'),
            ('"/analytics"', '"stats.deep"'),
            ('"/content-admins/{uid}"', '"roles.manage"'),
            ('"/users/{uid}/message"', '"users.message"'),
            ('"/users/{uid}/block"', '"users.delete"'),
            ('"/tickets/{tid}/reply"', '"tickets.reply"'),
            ('"/tickets/canned"', '"tickets.manage"'),  # 🌊 W8/B3
            ('"/broadcast"', '"broadcast.send"'),
            ('"/export/excel"', '"users.manage"'),
            ('"/backup"', '"backup.manage"'),
            ('"/audit-logs"', '"audit.view"'),
        ):
            i = ap.index(route)
            j = ap.index("@router.", i)
            chunk = ap[i:j]
            self.assertIn(f"require_perm({perm})", chunk, route)

    def test_miss04_plan_quota_wired(self):
        fin = read("db", "finance.py")
        self.assertIn("ai_daily_limit", fin)
        self.assertIn("plan_id: str = ''", fin)
        core = read("db", "core.py")
        self.assertIn("async def ai_limit_for_user", core)
        sol = read("ai_solver.py")
        self.assertIn("ai_limit_for_user(uid, cfg['daily_limit'])", sol)
        ai = read("api", "routers", "ai.py")
        self.assertIn("ai_limit_for_user", ai)
        sm = read("api", "routers", "subscription_management.py")
        self.assertIn("ai_daily_limit: int = Field(", sm)
        sub = read("api", "routers", "subscription.py")
        self.assertIn('"ai_daily_limit"', sub)
        bot = read("subscription.py")
        self.assertIn("plan_id=str(plan.get('_id', '') or '')", bot)

    def test_miss04_frontend_wired(self):
        web = read("webadmin", "src", "pages", "Subscriptions.jsx")
        self.assertIn("ai_daily_limit", web)
        self.assertIn("سهمیه هوشیار/روز", web)
        mini = read("miniapp", "src", "pages", "Me", "Subscription.jsx")
        self.assertIn("plan.ai_daily_limit", mini)
        adm = read("subscription_admin.py")
        self.assertIn("ai_daily_limit", adm)

    def test_miss03_trial_wired(self):
        fin = read("db", "finance.py")
        self.assertIn("async def trial_status", fin)
        self.assertIn("async def trial_claim", fin)
        self.assertIn("trial_used", fin)
        sub = read("api", "routers", "subscription.py")
        self.assertIn('"/trial/status"', sub)
        self.assertIn('router.post("/trial")', sub)
        self.assertIn('"trial": await db.trial_status(user_id)', sub)
        wa = read("api", "routers", "web_admin.py")
        self.assertIn('"trial_enabled"', wa)
        self.assertIn('"trial_days"', wa)
        self.assertIn('typ == "number"', wa)
        bot = read("subscription.py")
        self.assertIn("sub:trial", bot)
        self.assertIn("trial_claim(uid)", bot)
        mini = read("miniapp", "src", "pages", "Me", "Subscription.jsx")
        self.assertIn("/api/subscription/trial", mini)
        self.assertIn("claimTrial", mini)

    def test_perf02_search_timeout_wired(self):
        src = read("api", "routers", "global_search.py")
        self.assertIn("asyncio.wait_for(asyncio.gather(", src)
        self.assertIn("except asyncio.TimeoutError:", src)
        self.assertIn("status_code=503", src)
        self.assertEqual(src.count(".max_time_ms(_SEARCH_MAX_TIME_MS)"), 3)

    def test_perf03_pdf_offloaded(self):
        src = read("question_bank", "exam.py")
        self.assertIn("asyncio.to_thread", src)
        self.assertIn("_PDF_CACHE", src)
        self.assertIn("_PDF_CACHE_MAX", src)

    def test_autorenew_doc_exists(self):
        doc = read("docs", "auto-renew-decision.md")
        self.assertIn("recurring", doc)
        self.assertIn("trial_claim", doc)


# ─────────────────────────────────────────────
# فیک‌های ذخیره‌سازی (منطق واقعی، ذخیره‌سازی جعلی)
# ─────────────────────────────────────────────

class _FakeUsers:
    def __init__(self):
        self.docs = {}

    async def find_one(self, filt, proj=None):
        return self.docs.get(filt.get("user_id"))

    async def update_one(self, filt, update):
        uid = filt.get("user_id")
        doc = self.docs.get(uid)
        if doc is None:
            return SimpleNamespace(matched_count=0, modified_count=0)
        cond = filt.get("trial_used")
        if isinstance(cond, dict) and "$ne" in cond:
            if doc.get("trial_used") == cond["$ne"]:
                return SimpleNamespace(matched_count=0, modified_count=0)
        doc.update(update.get("$set", {}))
        return SimpleNamespace(matched_count=1, modified_count=1)


class _FakeSubs:
    def __init__(self):
        self.docs = {}

    async def find_one(self, filt):
        return self.docs.get(filt.get("_id"))

    async def update_one(self, filt, update, upsert=False):
        uid = filt.get("_id")
        doc = self.docs.setdefault(uid, {"_id": uid})
        doc.update(update.get("$set", {}))
        return SimpleNamespace(matched_count=1, modified_count=1)


class _FakeFinanceSelf(SimpleNamespace):
    """self جعلی برای متدهای واقعی DBFinance/DBCore."""

    async def get_setting(self, key, default=None):
        return self.settings.get(key, default)

    async def sub_plan_list(self, only_active=False):
        return [p for p in self.plans
                if not only_active or p.get("active")]

    async def sub_plan_get(self, plan_id):
        return next((p for p in self.plans
                     if str(p.get("_id")) == str(plan_id)), None)


def _make_fake(days_setting=7, enabled=1, plans=(), users=(), subs=()):
    fake = _FakeFinanceSelf(
        settings={"trial_enabled": enabled, "trial_days": days_setting},
        plans=[dict(p) for p in plans],
        users=_FakeUsers(), subscriptions=_FakeSubs(),
    )
    if _DEPS_OK:
        # متدهای واقعی روی ذخیره‌سازی جعلی (فراخوانی‌های داخلی self.* هم واقعی‌اند)
        for _name in ("trial_status", "trial_claim", "sub_get",
                      "sub_is_active", "sub_activate"):
            setattr(fake, _name,
                    MethodType(getattr(DBFinance, _name), fake))
        # 🌊 W7 — ai_limit_for_user حالا از plan_for_sub (واقعی DBCore) استفاده می‌کند
        setattr(fake, "plan_for_sub",
                MethodType(DBCore.plan_for_sub, fake))
    return fake


def _seed_users(fake, uids):
    for u in uids:
        fake.users.docs[u] = {"user_id": u}


@unittest.skipUnless(_DEPS_OK, f"deps سبک نصب نیست: {_DEPS_ERR}")
class W6LogicTests(unittest.TestCase):
    """منطق واقعی روی ذخیره‌سازی جعلی (بدون Mongo)."""

    def test_trial_claim_happy_path(self):
        async def go():
            plans = [
                {"_id": "p1", "name": "ماهانه", "days": 30, "price": 100,
                 "active": True, "ai_daily_limit": 50},
                {"_id": "p2", "name": "سالانه", "days": 365, "price": 900,
                 "active": True, "ai_daily_limit": 200},
            ]
            fake = _make_fake(plans=plans)
            _seed_users(fake, [11])
            st = await DBFinance.trial_status(fake, 11)
            self.assertTrue(st["eligible"])
            self.assertEqual(st["days"], 7)
            res = await DBFinance.trial_claim(fake, 11)
            self.assertEqual(res["days"], 7)
            self.assertEqual(res["plan_name"], "ماهانه")
            sub = await DBFinance.sub_get(fake, 11)
            self.assertEqual(sub["status"], "active")
            self.assertEqual(sub["source"], "trial")
            # معادل ارزان‌ترین پلن ⇒ سهمیه پلنی هم اعمال می‌شود
            self.assertEqual(sub["plan_id"], "p1")
            self.assertTrue(await DBFinance.sub_is_active(fake, 11))
            lim = await DBCore.ai_limit_for_user(fake, 11, 10)
            self.assertEqual(lim, 50)
        asyncio.run(go())

    def test_trial_double_claim_race_single_winner(self):
        async def go():
            plans = [{"_id": "p1", "name": "ماهانه", "days": 30,
                      "price": 100, "active": True}]
            fake = _make_fake(plans=plans)
            _seed_users(fake, [22])

            async def attempt():
                try:
                    await DBFinance.trial_claim(fake, 22)
                    return "won"
                except ValueError as e:
                    return str(e)

            results = await asyncio.gather(*[attempt() for _ in range(10)])
            self.assertEqual(results.count("won"), 1)
            # بازنده‌ها یا به توکن می‌خورند یا به چکِ «اشتراک فعال» — هر دو دفاع‌اند
            losers = [r for r in results if r != "won"]
            self.assertEqual(len(losers), 9)
            for r in losers:
                self.assertIn(r, ("already_used", "already_subscribed"))
            # فقط یک اشتراک trial ساخته شده
            sub = await DBFinance.sub_get(fake, 22)
            self.assertEqual(sub["source"], "trial")
        asyncio.run(go())

    def test_trial_status_matrix(self):
        async def go():
            plans = [{"_id": "p1", "name": "م", "days": 30, "price": 5,
                      "active": True}]
            # غیرفعال
            f = _make_fake(enabled=0, plans=plans)
            _seed_users(f, [1])
            st = await DBFinance.trial_status(f, 1)
            self.assertEqual((st["eligible"], st["reason"]),
                             (False, "trial_disabled"))
            # اشتراک فعال
            f = _make_fake(plans=plans)
            _seed_users(f, [2])
            f.subscriptions.docs[2] = {
                "_id": 2, "status": "active",
                "end_date": "2999-01-01T00:00:00+00:00"}
            st = await DBFinance.trial_status(f, 2)
            self.assertEqual(st["reason"], "already_subscribed")
            # قبلاً استفاده شده
            f = _make_fake(plans=plans)
            _seed_users(f, [3])
            f.users.docs[3]["trial_used"] = True
            st = await DBFinance.trial_status(f, 3)
            self.assertEqual(st["reason"], "already_used")
            # بدون پلن
            f = _make_fake(plans=[])
            _seed_users(f, [4])
            st = await DBFinance.trial_status(f, 4)
            self.assertEqual(st["reason"], "no_plan")
            # کاربر ناشناخته
            f = _make_fake(plans=plans)
            st = await DBFinance.trial_status(f, 999)
            self.assertEqual(st["reason"], "unknown_user")
            # clamp روزها
            f = _make_fake(days_setting=99, plans=plans)
            _seed_users(f, [5])
            st = await DBFinance.trial_status(f, 5)
            self.assertEqual(st["days"], 30)
        asyncio.run(go())

    def test_ai_limit_matrix(self):
        async def go():
            plans = [
                {"_id": "a", "name": "A", "active": True,
                 "ai_daily_limit": 60},
                {"_id": "b", "name": "B", "active": True,
                 "ai_daily_limit": 0},  # ارث از سراسری
            ]
            f = _make_fake(plans=plans)
            # plan_id مستقیم
            f.subscriptions.docs[1] = {"_id": 1, "status": "active",
                                       "plan_id": "a",
                                       "end_date": "2999-01-01T00:00:00+00:00"}
            self.assertEqual(await DBCore.ai_limit_for_user(f, 1, 10), 60)
            # پلن بدون سهمیه ⇒ سراسری
            f.subscriptions.docs[2] = {"_id": 2, "status": "active",
                                       "plan_id": "b",
                                       "end_date": "2999-01-01T00:00:00+00:00"}
            self.assertEqual(await DBCore.ai_limit_for_user(f, 2, 10), 10)
            # اشتراک قدیمی بدون plan_id ⇒ تطبیق نام
            f.subscriptions.docs[3] = {"_id": 3, "status": "active",
                                       "plan_name": "A",
                                       "end_date": "2999-01-01T00:00:00+00:00"}
            self.assertEqual(await DBCore.ai_limit_for_user(f, 3, 10), 60)
            # فعال‌سازی دستی (نام ساختگی) ⇒ سراسری
            f.subscriptions.docs[4] = {"_id": 4, "status": "active",
                                       "plan_name": "فعال‌سازی دستی",
                                       "end_date": "2999-01-01T00:00:00+00:00"}
            self.assertEqual(await DBCore.ai_limit_for_user(f, 4, 10), 10)
            # بدون اشتراک ⇒ سراسری
            self.assertEqual(await DBCore.ai_limit_for_user(f, 5, 10), 10)
        asyncio.run(go())

    def test_search_timeout_returns_503(self):
        async def go():
            from fastapi import HTTPException

            class _HangCursor:
                def sort(self, *a, **k): return self
                def limit(self, *a, **k): return self
                def max_time_ms(self, *a, **k): return self
                async def to_list(self, n):
                    await asyncio.sleep(30)

            class _HangFinder:
                def find(self, *a, **k): return _HangCursor()

            class _HangDB(_HangFinder):
                def __init__(self):
                    _hf = _HangFinder()
                    self.questions = self.faq = self.schedules = _hf
                    self.ref_subjects = self.ref_books = _hf
                async def search_resources(self, *a, **k):
                    await asyncio.sleep(30)
                async def is_content_admin(self, uid): return True

            prev_db, prev_t = gs.db, gs._SEARCH_TIMEOUT_S
            gs.db, gs._SEARCH_TIMEOUT_S = _HangDB(), 0.2
            try:
                with self.assertRaises(HTTPException) as cm:
                    await gs.search(q="هوش", user={"id": 1, "_db": {}})
                self.assertEqual(cm.exception.status_code, 503)
            finally:
                gs.db, gs._SEARCH_TIMEOUT_S = prev_db, prev_t
        asyncio.run(go())

    def test_search_caps_results(self):
        async def go():
            class _Cursor:
                def __init__(self, docs): self.docs = docs
                def sort(self, *a, **k): return self
                def limit(self, *a, **k): return self
                def max_time_ms(self, *a, **k): return self
                async def to_list(self, n): return list(self.docs)

            class _DB:
                def __init__(self): self.calls = 0
                async def search_resources(self, *a, **k):
                    return [{"_id": f"r{i}", "name": f"R{i}"}
                            for i in range(25)]
                async def is_content_admin(self, uid): return True
            db = _DB()
            db.questions = SimpleNamespace(
                find=lambda *a, **k: _Cursor(
                    [{"_id": f"q{i}"} for i in range(25)]))
            db.faq = SimpleNamespace(
                find=lambda *a, **k: _Cursor(
                    [{"_id": f"f{i}"} for i in range(25)]))
            db.schedules = SimpleNamespace(
                find=lambda *a, **k: _Cursor(
                    [{"_id": f"s{i}"} for i in range(25)]))
            db.ref_subjects = SimpleNamespace(
                find=lambda *a, **k: _Cursor(
                    [{"_id": f"b{i}"} for i in range(25)]))
            db.ref_books = SimpleNamespace(
                find=lambda *a, **k: _Cursor([]))
            prev = gs.db
            gs.db = db
            try:
                out = await gs.search(q="هوش", user={"id": 1, "_db": {}})
            finally:
                gs.db = prev
            self.assertEqual(out["query"], "هوش")
            self.assertLessEqual(len(out["results"]), 50)
            # هر نوع حداکثر ۱۰ (۶ نوع × ۲۵ ورودی ⇒ ≤۵۰ خروجی)
            self.assertEqual(len(out["results"]), 50)
        asyncio.run(go())

    def test_pdf_cache_avoids_rebuild(self):
        async def go():
            from bson import ObjectId
            calls = []

            def _fake_build(questions, meta, mode="practice"):
                calls.append(mode)
                return b"%PDF-fake-" + mode.encode()

            oid = str(ObjectId())
            session = {"_id": "s1", "session_id": "sid1", "user_id": 1,
                       "status": "finished", "output_mode": "",
                       "question_ids": [oid], "lesson": "L", "topic": "T",
                       "difficulty": None, "exam_code": "E1"}
            qdoc = {"_id": ObjectId(oid), "updated_at": "t0"}

            class _Chain:
                async def to_list(self, n):
                    return [qdoc]

            class _FakePDFDB:
                questions = SimpleNamespace(find=lambda *a, **k: _Chain())
                question_pdf_generations = SimpleNamespace(
                    insert_one=lambda *a, **k: _aw())
                def display_name_of(self, u): return "T"

            async def _aw(*a, **k): return None

            class _FakeSessions:
                async def find_one(self, *a, **k): return dict(session)
                async def update_one(self, *a, **k): return None

            class _FakeQbank:
                async def verify_access(self, *a, **k): return None

            svc = exam_mod.ExamService.__new__(exam_mod.ExamService)
            svc.db, svc.qbank, svc.sessions = (_FakePDFDB(), _FakeQbank(),
                                               _FakeSessions())
            prev_build, prev_cache = qbank.generate_exam_pdf, dict(
                exam_mod._PDF_CACHE)
            qbank.generate_exam_pdf = _fake_build
            exam_mod._PDF_CACHE.clear()
            try:
                c1, m1 = await svc.generate_pdf(session_id="sid1",
                                                user={"id": 1},
                                                mode="practice")
                c2, m2 = await svc.generate_pdf(session_id="sid1",
                                                user={"id": 1},
                                                mode="practice")
                self.assertEqual(c1, c2)
                self.assertEqual(m1["generation_id"], m2["generation_id"])
                self.assertEqual(len(calls), 1)  # دومی از کش
                await svc.generate_pdf(session_id="sid1", user={"id": 1},
                                       mode="exam")
                self.assertEqual(len(calls), 2)  # mode متفاوت ⇒ rebuild
            finally:
                qbank.generate_exam_pdf = prev_build
                exam_mod._PDF_CACHE.clear()
                exam_mod._PDF_CACHE.update(prev_cache)
        asyncio.run(go())


def _mongo_available() -> bool:
    uri = os.getenv("MONGODB_URI", "")
    if not (uri.startswith("mongodb://127.0.0.1") or
            uri.startswith("mongodb://localhost")):
        return False
    host, _, port = uri[len("mongodb://"):].partition(":")
    try:
        with socket.create_connection((host, int(port or 27017)), timeout=1):
            return True
    except OSError:
        return False


@unittest.skipUnless(_mongo_available(), "MONGODB_URI محلی در دسترس نیست (CI)")
class W6DbGatedTests(unittest.TestCase):
    """trial و resolver واقعی روی Mongo محلی."""

    @classmethod
    def setUpClass(cls):
        from database import db
        cls.db = db
        from _rtloop import adopt
        adopt()
        cls._run(cls._prepare())

    @classmethod
    def tearDownClass(cls):
        cls._run(cls._clean())

    @classmethod
    def _run(cls, coro):
        from _rtloop import run
        return run(coro)

    @classmethod
    async def _prepare(cls):
        db = cls.db
        await cls._clean()
        await db.users.update_one(
            {"user_id": W6_UID}, {"$set": {"user_id": W6_UID, "name": "W6"}},
            upsert=True)
        await db.sub_plans.insert_one({
            "_id": "w6plan", "name": "W6 پلن", "days": 30, "price": 50,
            "active": True, "ai_daily_limit": 77})

    @classmethod
    async def _clean(cls):
        db = cls.db
        await db.users.delete_many({"user_id": W6_UID})
        await db.subscriptions.delete_many({"_id": W6_UID})
        await db.sub_plans.delete_many({"_id": "w6plan"})

    def test_trial_claim_real(self):
        async def go():
            db = self.db
            res = await db.trial_claim(W6_UID)
            self.assertEqual(res["plan_name"], "W6 پلن")
            sub = await db.sub_get(W6_UID)
            self.assertEqual(sub["source"], "trial")
            self.assertEqual(sub["plan_id"], "w6plan")
            self.assertTrue(await db.sub_is_active(W6_UID))
            with self.assertRaises(ValueError):
                await db.trial_claim(W6_UID)
        self._run(go())

    def test_ai_limit_real(self):
        async def go():
            db = self.db
            await db.trial_claim(W6_UID)
            self.assertEqual(await db.ai_limit_for_user(W6_UID, 10), 77)
        self._run(go())
