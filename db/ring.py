"""💍 Ring Street — لایه‌ی داده (mixin)

قاعده‌ی این فایل: هر عمل اتمیک باید با *خودِ Mongo* تضمین شود، نه با
RAM و نه با «اول بخوان بعد بنویس». سه تضمین ساختاری:

  ۱) صف = یک سند به‌ازای هر کاربر (`_id = user_id`) ⇒ عضویت دوبل در صف
     از نظر فیزیکِ دیتابیس ناممکن است (join_queue idempotent).
  ۲) «حداکثر یک گفت‌وگوی فعال به‌ازای هر کاربر» با **unique index روی
     فیلد آرایه‌ای `slots`** + `partialFilterExpression={status:'active'}`
     تضمین می‌شود: ایندکس روی آرایه، هر عضو را به‌تنهایی کلید می‌کند؛
     پس درج دومین سندِ active با همان uid خطای E11000 می‌دهد — و
     چون `slots=[uid, uid]` هم تکلیرو تکراری است، match با خودِ شخص
     هم در سطح دیتابیس بسته می‌شود.
  ۳) برداشتن کاندید از صف با `find_one_and_update` اتمیک است ⇒ دو
     matcher همزمان یک کاندید را نمی‌گیرند (بدون transaction).

هیچ‌جا پیام کاربران به‌صورت پیش‌فرض ذخیره نمی‌شود؛ `ring_message_evidence`
فقط snapshot گزارش‌شده (یا حالتِ log_all) است و با TTL خودش می‌سوزد.
"""
from __future__ import annotations

import logging
import random
import re
from datetime import timedelta

from pymongo import ReturnDocument

from time_utils import now_utc, utc_now_iso

logger = logging.getLogger(__name__)

ANON_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # بدون I/O/0/1 — خوانا در کپی
ANON_LEN = 4
QUEUE_WAITING = "waiting"
QUEUE_CLAIMING = "claiming"        # در حال match شدن (توسط خود کاربر)
QUEUE_CLAIMED = "claimed"          # توسط یک matcher دیگر رزرو شده
QUEUE_INCHAT = "in_chat"
ACTIVE = "active"
ENDED = "ended"

MAX_PARTNERS_CAP = 60      # سقف آرایه‌ی recent_partners (§۱۷)
CAND_HEAD = 12
QUEUE_COUNT_CAP = 200      # سقف شمارش صف (§۵۳) — بالای آن «حداقل ۲۰۰ نفر»             # چند سند از سر صف برای انتخاب تصادفی بررسی شود (§۱۰)

_ID_RE = re.compile(r"^[A-Za-z0-9_.]{4,16}$")


def new_anon_id() -> str:
    return "".join(random.choice(ANON_ALPHABET) for _ in range(ANON_LEN))


def _ago(iso: str | None, seconds: float) -> bool:
    """آیا timestamp ایزوِ داده‌شده قدیمی‌تر از `seconds` است؟ (بدون فرض timezone)"""
    if not iso:
        return True
    try:
        t = now_utc().fromisoformat(str(iso))
    except Exception:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=now_utc().tzinfo)
    return (now_utc() - t).total_seconds() > seconds


class _RingCols:
    """دسته‌ی کلکشن‌های Ring.

    نام دیتابیس از خودِ دایورِ `bot_settings` خوانده می‌شود تا اگر روزی
    `medicalbot` عوض شد، این ماژول hard-code نمانده باشد (تطبیق با
    `DBCore.__init__`)."""

    def __init__(self, core) -> None:
        try:
            d = core.settings.database
        except Exception:
            d = core.client["medicalbot"]
        self.profiles  = d["ring_profiles"]
        self.queue     = d["ring_queue"]
        self.sessions  = d["ring_sessions"]
        self.blocks    = d["ring_blocks"]
        self.reports   = d["ring_reports"]
        self.bans      = d["ring_bans"]
        self.ratings   = d["ring_ratings"]
        self.evidence  = d["ring_message_evidence"]
        self.audit     = d["ring_admin_audit"]
        self.limits    = d["ring_limits"]
        self.daily     = d["ring_stats_daily"]
        self.counters  = d["ring_counters"]


class DBRing:
    """همه‌ی عملیات داده‌ی Ring. از DBCore جدا تا ماژول قابل خاموش‌کردن بماند."""

    _ring_cols = None

    @property
    def ring_cols(self) -> _RingCols:
        if self._ring_cols is None:
            self._ring_cols = _RingCols(self)
        return self._ring_cols

    # ══════════════════════════════════════════════════════════
    #  bootstrap — ایندکس‌ها + بذرِ مجوز/تنظیمات
    #  توسط DBCore.ensure_indexes() صدا زده می‌شود (خطا آن را نمی‌شکند)
    # ══════════════════════════════════════════════════════════

    async def ring_bootstrap(self) -> None:
        await self.ring_indexes()
        # مجوز جدید، هم‌سبک «stats.deep»: $setOnInsert ⇒ هیچ ویرایش دستی پاک نمی‌شود
        try:
            await self.perm_catalog.update_one(
                {"_id": "ring.manage"},
                {"$setOnInsert": {"_id": "ring.manage",
                                  "label": "مدیریت رینگ استریت",
                                  "category": "ring"}},
                upsert=True,
            )
            for role in ("bot_admin", "reviewer", "admin"):   # admin ممکن است نباشد
                await self.roles.update_one(
                    {"_id": role}, {"$addToSet": {"perms": "ring.manage"}})
        except Exception as e:                       # نقش‌ها هنوز ساخته نشده‌اند
            logger.debug("ring perm seed skipped: %s", e)

    async def ring_indexes(self) -> None:
        c = self.ring_cols
        await c.profiles.create_index("anon_id", unique=True, background=True,
                                name="uq_ring_anon_id",
                                partialFilterExpression={"anon_id": {"$type": "string"}})
        await c.profiles.create_index("status", background=True)
        await c.profiles.create_index([("mode", 1), ("status", 1)], background=True)
        await c.profiles.create_index([("state", 1), ("pending_field", 1)], background=True)
        # §۱۲ (V5) — جاروی «یتیم‌ها» روی پروفایل‌هایی که `search_msg` دارند؛
        # sparse ⇒ اسنادِ بی‌search_msg وارد ایندکس نمی‌شوند (هزینه = تعدادِ
        # منتظرها، نه اندازهٔ کل مجموعه). idempotent و بدون مهاجرت داده.
        await c.profiles.create_index("search_msg.m", sparse=True, background=True,
                                      name="ring_search_msg")
        await c.queue.create_index([("status", 1), ("mode", 1), ("queued_at", 1)], background=True)
        # کوئری کاندید حالا `status: {$in: [waiting, claiming]}` است؛ explain روی
        # ۴۰۰۰ سند نشان داد که planner همان ایندکس status-first را با SORT_MERGE
        # برای دو کرانهٔ $in استفاده می‌کند و docsExamined = limit ⇒ ایندکس
        # اضافه لازم نیست (کمتر ایندکس = write کمتر و رول‌بک ساده‌تر).
        await c.queue.create_index([("status", 1), ("last_seen", 1)], background=True)
        await c.sessions.create_index("session_id", unique=True, background=True)
        # ★ تضمین اصلی: یک کاربر حداکثر یک session فعال
        await c.sessions.create_index(
            "slots", unique=True, background=True, name="uq_ring_one_active_per_user",
            partialFilterExpression={"status": ACTIVE})
        await c.sessions.create_index([("status", 1), ("last_activity_at", -1)], background=True)
        await c.sessions.create_index([("slots", 1), ("ended_at", -1)], background=True)
        await c.sessions.create_index([("mode", 1), ("created_at", -1)], background=True)
        await c.blocks.create_index([("user_id", 1), ("blocked_user_id", 1)], background=True)
        await c.blocks.create_index("blocked_user_id", background=True)
        await c.reports.create_index([("status", 1), ("created_at", -1)], background=True)
        await c.reports.create_index([("reported_uid", 1), ("created_at", -1)], background=True)
        await c.reports.create_index("session_id", background=True)
        await c.bans.create_index([("user_id", 1), ("until", 1)], background=True)
        await c.bans.create_index([("active", 1), ("until", 1)], background=True)
        await c.ratings.create_index([("rated_uid", 1), ("created_at", -1)], background=True)
        await c.evidence.create_index([("session_id", 1), ("seq", 1)], background=True)
        await c.evidence.create_index("expires_at", expireAfterSeconds=0, background=True)
        await c.audit.create_index([("created_at", -1)], background=True)
        await c.audit.create_index([("admin_id", 1), ("created_at", -1)], background=True)
        await c.limits.create_index("expires_at", expireAfterSeconds=0, background=True)
        await c.daily.create_index("date", unique=True, background=True)
        # کالکشن شمارنده‌ها lazily ساخته می‌شود؛ یک سند bootstrap تا در
        # listCollections و مانیتورینگ پنل، هر ۱۲ کالکشن دیده شوند.
        try:
            await c.counters.insert_one({"_id": "bootstrap", "created_at": utc_now_iso()})
        except Exception:
            pass   # از قبل وجود دارد

    # ══════════════════════════════════════════════════════════
    #  profiles
    # ══════════════════════════════════════════════════════════

    async def ring_profile(self, uid: int) -> dict | None:
        return await self.ring_cols.profiles.find_one({"_id": int(uid)})

    async def ring_profile_by_anon(self, anon_id: str) -> dict | None:
        return await self.ring_cols.profiles.find_one({"anon_id": anon_id})

    async def ring_profile_touch(self, uid: int) -> None:
        await self.ring_cols.profiles.update_one(
            {"_id": int(uid)},
            {"$set": {"last_seen_at": utc_now_iso()}},
        )

    async def ring_profile_ensure(self, uid: int, **seed) -> dict:
        """ساخت پروفایل با anon_id یکتا (تلاش مجدد روی تصادف).

        `$setOnInsert` ⇒ فراخوانی دوباره هیچ فیلدی را بازنویسی نمی‌کند
        (idempotent — §۶۲).
        """
        col = self.ring_cols.profiles
        uid = int(uid)
        for _ in range(8):
            anon = new_anon_id()
            try:
                await col.update_one(
                    {"_id": uid},
                    {"$setOnInsert": {
                        "anon_id": f"#{anon}",
                        "created_at": utc_now_iso(),
                        "last_seen_at": utc_now_iso(),
                        "status": "active",
                        "report_score": 0,
                        "warnings": 0,
                        "consent_terms_at": None,
                        "age_confirmed_at": None,
                        "banned_until": None,
                        # «چه چیزهایی دیده شود» (§۳۵) — opt-out، نه opt-in، تا
                        # رفتار کاربران فعلی عوض نشود؛ صریح در doc ذخیره می‌شود.
                        "show_age": True, "show_gender": True, "show_field": True,
                        "show_university": True, "show_city": True, "show_bio": True,
                        "rules_version": 0, "rules_accepted_at": None,
                        **{k: v for k, v in seed.items() if v is not None},
                    }},
                    upsert=True,
                )
                doc = await col.find_one({"_id": uid})
                if doc:
                    return doc
            except Exception as e:                    # E11000 روی anon_id
                if "E11000" not in str(e):
                    raise
        raise RuntimeError("ring anon_id generation failed")

    async def ring_profile_update(self, uid: int, fields: dict,
                                  unset: list | None = None) -> None:
        """`upsert=True` + بذرِanon_id: هیچ نوشتی در onboarding بی‌صدا
        گم نمی‌شود حتی اگر کاربر هنوز `ensure` نشده باشد."""
        sets = dict(fields or {})
        sets["updated_at"] = utc_now_iso()
        seed = {"anon_id": new_anon_id(), "status": "active",
                "report_score": 0, "warnings": 0, "created_at": utc_now_iso(),
                "last_seen_at": utc_now_iso(), "consent_terms_at": None,
                "age_confirmed_at": None, "banned_until": None}
        # Mongo هرگونه هم‌پوشانی مسیر بین $set و $setOnInsert را رد می‌کند
        seed = {k: v for k, v in seed.items() if k not in sets}
        upd = {"$set": sets, "$setOnInsert": seed}
        if unset:
            upd["$unset"] = {k: "" for k in unset}
        for _ in range(3):
            try:
                await self.ring_cols.profiles.update_one({"_id": int(uid)}, upd, upsert=True)
                return
            except Exception as e:
                if "E11000" not in str(e):
                    raise
                upd["$setOnInsert"]["anon_id"] = new_anon_id()   # تصادف نادر

    async def ring_profile_status(self, uid: int, status: str) -> None:
        await self.ring_cols.profiles.update_one(
            {"_id": int(uid)},
            {"$set": {"status": status, "updated_at": utc_now_iso()}},
        )

    async def ring_report_recent(self, uid: int, peer: int, cap: int = 40) -> None:
        """ثبت پارتنر اخیر (برای cooldown «همان نفر دوباره نه» — §۱۷).

        `$position:0` + `$slice` ⇒ آرایه هیچ‌وقت بی‌نهایت رشد نمی‌کند و
        تازه‌ترین‌ها اول می‌مانند. فقط شناسه نگه داشته می‌شود، نه بیشتر.
        """
        cap = max(4, min(int(cap or 40), MAX_PARTNERS_CAP))
        for a, b in ((int(uid), int(peer)), (int(peer), int(uid))):
            await self.ring_cols.profiles.update_one(
                {"_id": a},
                {"$push": {"recent_partners": {
                    "$each": [{"uid": int(b), "at": utc_now_iso()}],
                    "$position": 0, "$slice": cap}}},
            )

    async def ring_profile_score(self, uid: int, delta: int, *,
                                 warnings: int = 0) -> int:
        """report score با severity weighting (±). خروجی = امتیاز جدید."""
        await self.ring_cols.profiles.update_one(
            {"_id": int(uid)},
            {"$inc": {"report_score": int(delta), "warnings": int(warnings)},
             "$set": {"updated_at": utc_now_iso()},
             "$setOnInsert": {"anon_id": new_anon_id(), "status": "active"}},
            upsert=True,
        )
        doc = await self.ring_cols.profiles.find_one({"_id": int(uid)}, {"report_score": 1})
        return int((doc or {}).get("report_score", 0))

    async def ring_profile_delete(self, uid: int) -> dict:
        """حذف پروفایل با «anonymize باقی‌مانده‌ها» — گزارش‌ها می‌مانند ولی
        هویت قابل‌بازگشت نباشد (§۷۶)."""
        uid = int(uid)
        removed = {"profile": 0, "queue": 0, "ratings": 0, "anonymized_reports": 0}
        r = await self.ring_cols.profiles.delete_one({"_id": uid})
        removed["profile"] = r.deleted_count
        r = await self.ring_cols.queue.delete_one({"_id": uid})
        removed["queue"] = r.deleted_count
        r = await self.ring_cols.ratings.delete_many({"rater_uid": uid})
        removed["ratings"] = r.deleted_count
        await self.ring_cols.reports.update_many(
            {"reporter_uid": uid}, {"$set": {"reporter_uid": 0, "reporter_anon": "#deleted"}})
        await self.ring_cols.blocks.delete_many(
            {"$or": [{"user_id": uid}, {"blocked_user_id": uid}]})
        for s in await self.ring_cols.sessions.find(
                {"status": ACTIVE, "slots": uid}).to_list(5):
            await self.ring_session_end(s["session_id"], "profile_deleted", None)
        removed["anonymized_reports"] = 1
        await self.ring_audit("system", "DELETE_PROFILE", str(uid), "درخواست کاربر", {})
        return removed

    # ══════════════════════════════════════════════════════════
    #  queue — یک سند به‌ازای کاربر (`_id = uid`)
    # ══════════════════════════════════════════════════════════

    async def ring_queue_join(self, uid: int, doc: dict) -> str:
        """ok | already_in_chat | waiting

        idempotent: ورود دوباره فقط `queued_at` را نو نمی‌کند مگر وقتی
        کاربر واقعاً بیرون صف بوده — وگرنه fairness (اول صبر=اولویت)
        با هر بار «next» ریست می‌شد و starvation الکی.
        """
        uid = int(uid)
        cur = await self.ring_cols.queue.find_one({"_id": uid})
        if cur and cur.get("status") == QUEUE_INCHAT:
            return "already_in_chat"
        if cur and cur.get("status") == QUEUE_CLAIMED:
            # یک matcherِ دیگر همین حالا ما را رزرو کرده (در فاصلهٔ «claim تا
            # ساخت session»). clickِ خودِ کاربر نباید آن رزرو را پاک کند —
            # وگرنه برنده session می‌سازد و ما بیرون می‌آییم و «empty» می‌خوانیم.
            return "claimed"
        payload = dict(doc)
        payload["user_id"] = uid
        payload["status"] = QUEUE_WAITING
        payload["last_seen"] = utc_now_iso()
        if not cur or cur.get("status") != QUEUE_WAITING:
            payload["queued_at"] = utc_now_iso()
        payload.setdefault("claim_token", None)
        try:
            # فیلترِ not-in / not-claimed اتمیک است: اگر بین read و write کاربر
            # وارد چت شد یا توسط matcherِ دیگری claimed شد، این update چیزی را
            # خراب نمی‌کند و upsert هم به دلیل تکرار _id می‌ترکد ⇒ همان
            # «already_in_chat»/«claimed» برمی‌گردانیم (§۴۰).
            await self.ring_cols.queue.update_one(
                {"_id": uid, "status": {"$nin": [QUEUE_INCHAT, QUEUE_CLAIMED]}},
                {"$set": payload}, upsert=True)
        except Exception as e:
            if "E11000" in str(e):
                return "already_in_chat"
            raise
        return "waiting"

    async def ring_queue_leave(self, uid: int) -> None:
        await self.ring_cols.queue.delete_one({"_id": int(uid)})

    async def ring_queue_leave_if(self, uid: int, statuses: tuple) -> bool:
        """ترکِ مشروط (§۳۸/§۳۹ V6): فقط اگر هنوز در همان وضعیت‌هاست پاک کن.

        اگر matcher همین لحظه کاربر را `claimed`/`in_chat` کرده باشد، این
        حذف nothing می‌شود و `False` برمی‌گرداند ⇒ فراخوان‌کننده (expire/cancel)
        نباید ادعای «از صف بیرون رفتی» بکند؛ نتیجه‌اش این است که هیچ‌وقت
        `A=EXPIRED` و `B=MATCHED` نداریم.
        """
        r = await self.ring_cols.queue.delete_one(
            {"_id": int(uid), "status": {"$in": list(statuses)}})
        return bool(getattr(r, "deleted_count", 0))

    async def ring_queue_get(self, uid: int) -> dict | None:
        return await self.ring_cols.queue.find_one({"_id": int(uid)})

    async def ring_queue_claim_self(self, uid: int, token: str) -> dict | None:
        """waiting → claiming. اگر None برگشت، کاربر یا در صف نیست یا
        هم‌زمان یک «next» دیگر در حال پردازش است (§۶۳)."""
        return await self.ring_cols.queue.find_one_and_update(
            {"_id": int(uid), "status": QUEUE_WAITING},
            {"$set": {"status": QUEUE_CLAIMING, "claim_token": token,
                      "claim_at": utc_now_iso()}},
            return_document=ReturnDocument.BEFORE,
        )

    # صف‌هایی که «برای match شدن در دسترس»‌اند. CLAIMING یعنی «این کاربر
    # همین حالا دارد می‌گردد» ⇒ بهترین کاندید ممکن، نه رقیب!
    # CLAIMING را از این فهرست برداشتن دقیقاً همان باگی بود که دو کاربرِ
    # هم‌زمان را برای همیشه از هم رد می‌کرد (هر دو empty می‌گرفتند).
    MATCHABLE = (QUEUE_WAITING, QUEUE_CLAIMING)

    async def ring_queue_find_candidate(self, mode: str, *, gender: str | None,
                                        age_range: str | None,
                                        exclude: list[int], token: str,
                                        statuses: tuple | None = None) -> dict | None:
        """اتمیک‌ترین حالت: یک کاندیدِ منطبق را پیدا **و** قفل می‌کند.

        sort بر اساس queued_at ⇒ کسی که بیشتر منتظر است اول انتخاب می‌شود
        (§۱۰ fairness). `claimed_by_me` برای rollback لازم است.
        """
        open_states = list(statuses or self.MATCHABLE)
        q: dict = {
            "mode": mode,
            "status": {"$in": open_states},
            "user_id": {"$nin": list(exclude) or [-1]},
        }
        if gender:
            q["gender"] = gender
        if age_range:
            q["age_range"] = age_range
        col = self.ring_cols.queue
        # سرِ صف = کسانی که بیشتر صبر کرده‌اند (§۱۰ fairness) — حداکثر CAND_HEAD
        # سند، با sort روی همین ایندکس ⇒ کوئری همیشه bound است.
        head = await col.find(q).sort([("queued_at", 1)]).limit(CAND_HEAD).to_list(CAND_HEAD)
        if not head:
            return None
        # tie-break تصادفی (§۱۰): اگر همه در یک ثانیه صف شده باشند، بدون
        # shuffled همهٔ جست‌وجوگران روی یک سند می‌کوبیدند و match‌ها دور
        # می‌رفتند (تست طوفان ۲۰تایی این را ثابت کرد).
        # tie-break فقط «درونِ» برابرهای queued_at — وگرنه fairness (§۱۰
        # «هرکس بیشتر صبر کرده اول») از بین می‌رود. DB سرتاسر را مرتب
        # داده، پس فقط گروه‌های متوالیِ هم‌مقدار را shuffle می‌کنیم.
        ordered: list[dict] = []
        i = 0
        while i < len(head):
            j = i
            while j < len(head) and head[j].get("queued_at") == head[i].get("queued_at"):
                j += 1
            grp = head[i:j]
            if len(grp) > 1:
                random.shuffle(grp)
            ordered.extend(grp)
            i = j
        for cand in ordered:
            # claim اتمیک: اگر همین لحظه کسی دیگری برداشت، None ⇒ بعدی
            claimed = await col.find_one_and_update(
                {"_id": cand["_id"], "status": {"$in": open_states}},
                {"$set": {"status": QUEUE_CLAIMED, "claimed_by_token": token,
                          "claimed_at": utc_now_iso()}},
                return_document=ReturnDocument.BEFORE,
            )
            if claimed:
                return claimed
        return None

    async def ring_queue_release(self, uid: int) -> None:
        """claimed/claiming → waiting (بدون تغییر queued_at ⇒ fairness حفظ می‌شود)"""
        await self.ring_cols.queue.update_one(
            {"_id": int(uid), "status": {"$in": [QUEUE_CLAIMED, QUEUE_CLAIMING]}},
            {"$set": {"status": QUEUE_WAITING, "claimed_by_token": None,
                      "claim_token": None}},
        )

    async def ring_queue_release_self(self, uid: int, token: str) -> bool:
        """آزادکردنِ claimِ **خودِ** کاربر، بدون دست‌زدن به رزروِ دیگری.

        اگر در همین فاصله یک matcher دیگر ما را claimed کرده، release نباید
        آن رزرو را باطل کند (وگرنه یک session بی‌صدا گم می‌شود).
        """
        r = await self.ring_cols.queue.update_one(
            {"_id": int(uid),
             "$or": [{"status": QUEUE_CLAIMING},
                     {"status": QUEUE_CLAIMED, "claimed_by_token": token}]},
            {"$set": {"status": QUEUE_WAITING, "claimed_by_token": None,
                      "claim_token": None}},
        )
        return bool(r.modified_count)

    async def ring_queue_taken_by_other(self, uid: int, token: str) -> dict | None:
        """سند صفِ کاربر، اگر همین حالا توسط matcherِ دیگری claimed شده."""
        d = await self.ring_cols.queue.find_one({"_id": int(uid)})
        if not d:
            return None
        if d.get("status") == QUEUE_CLAIMED and d.get("claimed_by_token") not in (None, token):
            return d
        if d.get("status") == QUEUE_INCHAT:
            return d
        return None

    async def ring_queue_into_chat(self, uid: int, session_id: str) -> None:
        await self.ring_cols.queue.update_one(
            {"_id": int(uid)},
            {"$set": {"status": QUEUE_INCHAT, "session_id": session_id,
                      "in_chat_since": utc_now_iso()}},
        )

    async def ring_queue_requeue(self, uid: int, mode: str | None = None) -> bool:
        """خروج از چت → دوباره در دسترس برای match شدن (فقط اگر درخواست داده باشد)."""
        sets: dict = {"status": QUEUE_WAITING, "queued_at": utc_now_iso(),
                      "session_id": None}
        if mode:
            sets["mode"] = mode
        r = await self.ring_cols.queue.update_one(
            {"_id": int(uid), "status": QUEUE_INCHAT}, {"$set": sets},
        )
        return r.modified_count > 0

    async def ring_queue_waiting_count(self, mode: str | None = None,
                                       exclude: list[int] | None = None,
                                       statuses: tuple | None = None,
                                       cap: int = QUEUE_COUNT_CAP) -> int:
        """چند نفر (جز من) «قابل match»‌اند — برای اینکه بفهمیم صف واقعاً
        خالی است یا فقط لحظه‌اً claimed شده (§۴۰).

        ⚠️ باید CLAIMING را هم بشمارد، وگرنه دو جست‌وجوی هم‌زمان «هیچ‌کس
        نیست» می‌بینند و بی‌Retry رها می‌کنند (همان باگ گزارش‌شده).

        `cap`: این شمارش در مسیرِ هر جست‌وجوی بی‌نتیجه صدا زده می‌شود، پس
        حداکثر `cap` تا بررسی می‌شود (§۵۳ هزینهٔ محدود). مقدار برگشتی همیشه
        «کرانهٔ پایینِ» واقعی است؛ مصرف‌کننده بالای cap می‌نویسد «حداقل».
        """
        q: dict = {"status": {"$in": list(statuses or self.MATCHABLE)}}
        if mode:
            q["mode"] = mode
        if exclude:
            q["user_id"] = {"$nin": [int(x) for x in exclude]}
        lim = int(cap) if cap else 0        # 0 = بدون سقف (پیامو PyMongo)
        return await self.ring_cols.queue.count_documents(q, limit=lim) if lim \
            else await self.ring_cols.queue.count_documents(q)

    async def ring_queue_stats(self) -> dict:
        out = {"waiting": 0, "claimed": 0, "in_chat": 0, "by_mode": {}, "by_gender": {}}
        async for d in self.ring_cols.queue.aggregate([
            {"$group": {"_id": {"status": "$status", "mode": "$mode"}, "n": {"$sum": 1}}}
        ]):
            st, md = (d["_id"].get("status"), d["_id"].get("mode"))
            out["by_mode"][f"{md}:{st}"] = d["n"]
            if st in ("waiting", QUEUE_CLAIMED, QUEUE_INCHAT):
                out[{"waiting": "waiting", QUEUE_CLAIMED: "claimed",
                     QUEUE_INCHAT: "in_chat"}[st]] += d["n"]
        # تفکیک جنسیتیِ منتظرها (§۴۶ — «صف چند نفر است و چه ترکیبی؟»)
        async for d in self.ring_cols.queue.aggregate([
            {"$match": {"status": "waiting"}},
            {"$group": {"_id": "$gender", "n": {"$sum": 1}}},
        ]):
            out["by_gender"][str(d.get("_id") or "unknown")] = int(d["n"])
        return out

    async def ring_queue_list(self, mode: str | None = None, limit: int = 200) -> list[dict]:
        q = {} if not mode else {"mode": mode}
        return await self.ring_cols.queue.find(q).sort("queued_at", 1).to_list(limit)

    # ══════════════════════════════════════════════════════════
    #  §۳..§۱۲ (V5) — پیامِ «در حال جست‌وجو» و تایمر زنده‌اش
    #
    #  شناسهٔ پیام روی *سند پروفایل* نگه داشته می‌شود (نه RAM)، تا بعد از
    #  ری‌استارتِ پروسه هم تایمر ادامه پیدا کند (§۳۵/§۴). مهاجرت لازم ندارد:
    #  نبودِ `search_msg` فقط یعنی «پیامی برای ویرایش نیست».
    # ══════════════════════════════════════════════════════════

    async def ring_search_msg_set(self, uid: int, chat_id: int, message_id: int,
                                  shown_s: int = 0) -> None:
        """§۴/§۵۴ (V6) — یک «نسل» شمارنده هم دارد: `rev`.

        هر بازنویسی/پاک‌کردن `rev` را بالا می‌برد، پس ویرایشِ در راهِ tick که
        با `expect_rev` صدا زده شده، اگر در فاصله‌ی خواندن تا نوشتن match یا
        لغو رخ داده باشد، **باخت می‌کند** (CAS) ⇒ پیامِ چت/کارت مچ روی صفحه
        با «🔎 در حال جست‌وجو…» بازنویسی نمی‌شود (§۲۱/§۲۲/§۲۳).
        """
        await self.ring_cols.profiles.update_one(
            {"_id": int(uid)},
            {"$set": {"search_msg": {"c": int(chat_id), "m": int(message_id),
                                     "s": int(shown_s or 0), "rev": 1,
                                     "at": utc_now_iso()}}})

    async def ring_search_msg_bump(self, uid: int, shown_s: int,
                                   expect_rev: int | None = None) -> bool:
        """CAS: فقط اگر هنوز همان «نسلِ» جست‌وجو جاری است، ساطیه را جابه‌جا کن.

        `expect_rev=None` ⇒ رفتار قدیمی (بدون CAS). وقتی `False` برگردد یعنی
        در فاصلهٔ خواندن→ویرایش، جست‌وجو عوض/تمام شده ⇒ فراخوان‌کننده **نباید**
        edit بزند (§۲۱).
        """
        filt: dict = {"_id": int(uid), "search_msg": {"$exists": True}}
        if expect_rev is not None:
            filt["search_msg.rev"] = int(expect_rev)
        r = await self.ring_cols.profiles.update_one(
            filt, {"$set": {"search_msg.s": int(shown_s or 0)},
                   "$inc": {"search_msg.rev": 1}})
        return bool(getattr(r, "modified_count", 0))

    async def ring_search_msg_pend(self, uid: int, text: str,
                                   kind: str = "plain", *,
                                   chat_id=None, message_id=None) -> bool:
        """§۸/§۱۰/§۱۴ (V6) — پیامی که *باید* جای حبابِ انتظار بنشیند ولی نشست.

        این‌جا شناسه پاک **نمی‌شود**: `search_tick` (و گامِ ترمیمِ housekeeping)
        همین `pend` را روی همان پیام می‌نویسد. با این کار «پیام یخ‌زدهٔ 00:00»
        دیگر وضعیتِ ماندگار نیست؛ نهایتاً یک دور دیرتر درست می‌شود.

        `chat_id`/`message_id` برای حالتی است که شناسه را *همان لحظه* unset
        کرده‌ایم (انقضا و مچ‌شدن اول تایمر را می‌بندند) ولی edit هنوز ننشسته:
        آن‌ها را برمی‌گردانیم تا `repair_search_ui` بداند کدام پیام را عوض کند —
        وگرنه هیچ‌کس آدرسِ حباب را ندارد و برای همیشه می‌ماند (§۵۵).
        """
        set_: dict = {"search_msg.pend": str(text or "")[:700],
                      "search_msg.pend_k": str(kind or "plain")[:12]}
        if chat_id and message_id:
            set_["search_msg.c"] = int(chat_id)
            set_["search_msg.m"] = int(message_id)
        r = await self.ring_cols.profiles.update_one(
            {"_id": int(uid)},
            {"$set": set_, "$inc": {"search_msg.rev": 1}})
        return bool(r.matched_count)

    async def ring_search_msg_pend_ids(self, limit: int = 50) -> list[int]:
        """uidهایی که پیامِ قطعی‌شان در صفِ اعمال مانده (`search_msg.pend`).

        از همان ایندکس sparse `search_msg.m` استفاده می‌کند ⇒ پیمایش فقط روی
        کسانِ دارای پیامِ انتظار، نه کل پروفایل‌ها. شرط `m > 0` هم لازم است:
        بدون آدرسِ پیام، `pend` فقط زباله است و باید پاک شود (نه بده‌بده).
        """
        cur = self.ring_cols.profiles.find(
            {"search_msg.pend": {"$exists": True, "$nin": [None, ""]},
             "search_msg.m": {"$gt": 0}},
            {"_id": 1}).to_list(int(limit))
        return [int(d["_id"]) for d in await cur]

    async def ring_search_msg_clear(self, uid: int, *, expired_at=None) -> None:
        """تایمر را خاموش می‌کند؛ `expired_at` فقط برای حالت EXPIRED نوشته می‌شود."""
        # `$inc` روی `rev` قبل از `$unset`: هر editِ در راهی که با expect_rev
        # قفل شده، بعد از این پاک‌کردن **باید** شکست بخورد (§۲۱).
        await self.ring_cols.profiles.update_one({"_id": int(uid)},
                                                 {"$inc": {"search_msg.rev": 1}})
        upd: dict = {"$unset": {"search_msg": ""}}
        if expired_at:
            upd["$set"] = {"search_expired_at": expired_at}
        await self.ring_cols.profiles.update_one({"_id": int(uid)}, upd)

    async def ring_sessions_uids(self, uids: list[int]) -> set[int]:
        """zیر ۱۰+ uid ⇒ یک query (به‌جای N تا) برای «کی الان داخل session است».

        برای tickِ تایمر (§۱۲ V5) استفاده می‌شود: ویرایش پیامِ انتظار برای کسی
        که داخل گفت‌وگو ممنوع است، ولی نمی‌خواهیم به‌ازای هر کاربر دو query بزنیم.
        """
        want = {int(u) for u in uids}
        if not want:
            return set()
        out: set[int] = set()
        cur = self.ring_cols.sessions.find(
            {"status": "active", "slots": {"$in": sorted(want)}},
            {"slots": 1}).to_list(len(want) + 10)
        for d in await cur:
            for s in (d.get("slots") or []):
                try:
                    if int(s) in want:
                        out.add(int(s))
                except Exception:
                    continue
        return out

    async def ring_search_msg_orphans(self, limit: int = 200) -> list[int]:
        """uidهایی که `search_msg` دارند ولی دیگر در صف نیستند (§۱۲ V5).

        ایندکسِ sparse روی `search_msg.m` ⇒ هزینه فقط به تعدادِ منتظرها،
        نه به بزرگیِ کل مجموعهٔ پروفایل‌ها.
        """
        cur = self.ring_cols.profiles.find({"search_msg": {"$exists": True}},
                                           {"_id": 1}).to_list(int(limit))
        return [int(d["_id"]) for d in await cur]

    async def ring_sessions_missing_current(self, limit: int = 50) -> list[tuple]:
        """§۴۸ (V6) — (session_id, uid)هایی که sessionِ فعال دارند ولی
        `profiles.current_session`شان ست نشده (crash بین ساخت session و attach).

        بدون این، کاربر «در جست‌وجو» می‌ماند در حالی که رله فعال است — دقیقاً
        همان چیزی که کاربر گزارش داد. فقط ۱۰۰×limit سندِ فعالِ تازه خوانده می‌شود.
        """
        out: list[tuple] = []
        cap = int(limit) * 4
        cur = self.ring_cols.sessions.find({"status": ACTIVE},
                                           {"session_id": 1, "slots": 1}).sort(
            "created_at", -1).to_list(cap)
        for s in await cur or []:
            sid = s.get("session_id")
            if not sid:
                continue
            for u in (s.get("slots") or []):
                try:
                    uid = int(u)
                except Exception:
                    continue
                p = await self.ring_cols.profiles.find_one({"_id": uid},
                                                            {"current_session": 1})
                if (p or {}).get("current_session") != sid:
                    out.append((sid, uid))
                    if len(out) >= int(limit):
                        return out
        return out

    async def ring_queue_orphans(self, limit: int = 50) -> list[int]:
        """§۴۸ — ردیف‌های `waiting` که صاحبشان الان sessionِ فعال دارد.

        این‌ها «یتیمِ صف»اند: match شده‌اند ولی ردیفشان پاک/به‌روزرسانی نشده ⇒
        matcherِ بعدی آن‌ها را دوباره برمی‌دارد و ممکن است sessionِ دوم بسازد.
        """
        out: list[int] = []
        rows = await self.ring_cols.queue.find(
            {"status": QUEUE_WAITING}, {"user_id": 1}).to_list(int(limit) * 4)
        for d in rows or []:
            try:
                uid = int(d.get("user_id") or 0)
            except Exception:
                continue
            if not uid:
                continue
            if await self.ring_session_active_for(uid):
                out.append(uid)
                if len(out) >= int(limit):
                    return out
        return out

    async def ring_queue_searching_ids(self, limit: int = 200) -> list[int]:
        """ردیف‌های «هنوز منتظر» با `queued_at` قدیمی‌تر اول (§۴ fairness).

        از همان ایندکس `status_1_mode_1_queued_at_1` استفاده می‌کند؛ limit سخت
        است تا هزینهٔ tick مستقل از بزرگی صف بماند (§۴۹).
        """
        cur = self.ring_cols.queue.find(
            {"status": {"$in": [QUEUE_WAITING, QUEUE_CLAIMING]}}
        ).sort("queued_at", 1).to_list(int(limit))
        rows = await cur
        out: list[int] = []
        for d in rows or []:
            try:
                out.append(int(d["user_id"]))
            except Exception:
                continue
        return out

    async def ring_queue_stale(self, timeout_s: int) -> list[int]:
        ids = []
        async for d in self.ring_cols.queue.find({"status": QUEUE_WAITING}).limit(2000):
            if _ago(d.get("last_seen"), timeout_s):
                ids.append(int(d["user_id"]))
        return ids

    async def ring_queue_repair_claims(self, stale_s: int = 120) -> int:
        """claim‌های یتیم (matcher کرش کرد / تلگرام وسط کار مُرد) را آزاد می‌کند.

        §۴۰/§۴۵ — این job باید idempotent باشد: فقط سندی که واقعاً
        timeout خورده برگردانده می‌شود.
        """
        n = 0
        async for d in self.ring_cols.queue.find({
                "status": {"$in": [QUEUE_CLAIMED, QUEUE_CLAIMING]}}).limit(500):
            when = d.get("claimed_at") if d["status"] == QUEUE_CLAIMED else d.get("claim_at")
            if _ago(when, stale_s):
                await self.ring_queue_release(d["user_id"])
                n += 1
        return n

    async def ring_queue_drop_user(self, uid: int) -> None:
        await self.ring_cols.queue.delete_one({"_id": int(uid)})

    # ══════════════════════════════════════════════════════════
    #  sessions
    # ══════════════════════════════════════════════════════════

    async def ring_session_create(self, sess: dict) -> str | None:
        """درج session فعال. اگر یکی از دو نفر همین حالا چت فعال دارد،
        unique index روی `slots` می‌ترکد ⇒ None برمی‌گردانیم (race با
        یک matcher دیگر باخته شد؛ صداکننده rollback می‌کند)."""
        sid = sess["session_id"]
        slots = [int(u) for u in (sess.get("slots") or [])]
        if len(slots) != 2 or len(set(slots)) != 2:
            # self-match یا سند ناقص — ایندکس یکتا فقط بین اسناد مقایسه
            # می‌کند، پس این گارد اینجا لازم است (§۶۵).
            return None
        sess["slots"] = slots
        try:
            await self.ring_cols.sessions.insert_one(sess)
            return sid
        except Exception as e:
            if "E11000" in str(e):
                return None
            raise

    async def ring_session(self, session_id: str) -> dict | None:
        return await self.ring_cols.sessions.find_one({"session_id": session_id})

    async def ring_session_active_for(self, uid: int) -> dict | None:
        return await self.ring_cols.sessions.find_one(
            {"status": ACTIVE, "slots": int(uid)})

    async def ring_session_peer(self, sess: dict | None, uid: int) -> int | None:
        """`sess` می‌تواند None باشد (جلسه‌ای که همین حالا بسته شده) —
        فراخواننده‌های moderation این حالت را دارند.

        برای جلسات ended، `slots` عمداً null شده (تا unique index آزاد شود)
        ⇒ مرجع دوم `user_a`/`user_b` است؛ بدون آن «امتیازدهی پس از گفت‌وگو»
        (§۲۴) هیچ‌وقت peer نداشت و بی‌صدا می‌مرد.
        """
        uid = int(uid)
        d = sess or {}
        slots = d.get("slots") or [x for x in (d.get("user_a"), d.get("user_b"))
                                   if x is not None]
        for s in slots:
            if int(s) != uid:
                return int(s)
        return None

    async def ring_session_touch(self, session_id: str, *, media: bool = False,
                                 inc_messages: int = 1) -> None:
        upd = {"$inc": {"messages_count": inc_messages},
               "$set": {"last_activity_at": utc_now_iso()}}
        if media:
            upd["$inc"]["media_count"] = 1
        await self.ring_cols.sessions.update_one({"session_id": session_id}, upd)

    async def ring_session_end(self, session_id: str, reason: str,
                               ended_by: int | None) -> dict | None:
        """اتمام — و *در همان update* آزادکردن slot.

        مستند «قبل» از به‌روزرسانی برمی‌گردد (slots/status قدیمی) چون
        فراخواننده برای اطلاع‌رسانی به طرف مقابل به uidها نیاز دارد؛
        برای وضعیت نهایی `ring_session()` را بخوانید.

        `slots: None` عمداً آرایه را از ایندکس partial بیرون می‌اندازد
        تا کاربر دوباره بتواند عضو یک active session شود.
        """
        doc = await self.ring_cols.sessions.find_one_and_update(
            {"session_id": session_id, "status": ACTIVE},
            {"$set": {
                "status": ENDED, "ended_at": utc_now_iso(),
                "termination_reason": reason,
                "ended_by": int(ended_by) if ended_by is not None else None,
                "slots": None,
            }},
            return_document=ReturnDocument.BEFORE,
        )
        return doc

    async def ring_last_ended_session(self, uid: int) -> dict | None:
        """آخرین session تمام‌شده‌ی کاربر (برای امتیازدهی §۲۴) — یک‌بار مصرف:
        با `rating_done` علامت می‌خورد تا دو بار پرسیده نشود."""
        # `slots` بعد از end حذف می‌شود ⇒ جست‌وجو باید روی user_a/user_b
        # هم باشد، وگرنه هیچ‌وقت چیزی پیدا نمی‌شود (§۲۴).
        return await self.ring_cols.sessions.find_one_and_update(
            {"$or": [{"slots": int(uid)}, {"user_a": int(uid)}, {"user_b": int(uid)}],
             "status": ENDED, "rating_done": {"$ne": True}},
            {"$set": {"rating_done": True}},
            sort=[("ended_at", -1)],
            return_document=ReturnDocument.BEFORE,
        )

    # ══════════════════════════════════════════════════════════
    #  §۱۰..§۱۳/§۳۰/§۳۶ (V6) — «آیا هر دو طرف واقعاً خبردار شدند؟»
    #
    #  notification یک *اثر جانبی* است؛ منبع حقیقت session است. پس نتیجهٔ هر
    #  ارسال روی خودِ سند نگه داشته می‌شود:
    #      sessions.notify = {"<uid>": {"s": sent_at, "t": tries,
    #                                   "at": last_try_at, "e": error}}
    #  نبودِ `s` = «هنفرستاده». این تنها چیزی است که بعد از ری‌استارت یا
    #  خرابیِ تلگرام لازم است تا نه پیامی گم شود، نه دوتا برود.
    # ══════════════════════════════════════════════════════════

    async def ring_session_notify_state(self, session_id: str) -> dict:
        sess = await self.ring_cols.sessions.find_one(
            {"session_id": session_id}, {"notify": 1, "slots": 1, "status": 1})
        return ((sess or {}).get("notify") or {})

    async def ring_session_note_sent(self, session_id: str, uid: int, *,
                                     sent: bool | None = None,
                                     err: str | None = None,
                                     tried: bool = True) -> None:
        """ثبت نتیجهٔ ارسال برای یک کاربر (idempotent: `s` فقط یک‌بار نوشته می‌شود)."""
        setd: dict = {}
        if sent is True:
            setd["notify.%s.s" % uid] = utc_now_iso()
            setd["notify.%s.e" % uid] = None
        elif sent is False:
            setd["notify.%s.e" % uid] = (str(err) if err else "failed")[:200]
        if tried:
            setd["notify.%s.at" % uid] = utc_now_iso()
        upd: dict = {}
        if setd:
            upd["$set"] = setd
        if tried:
            upd["$inc"] = {"notify.%s.t" % uid: 1}
        if not upd:
            return
        await self.ring_cols.sessions.update_one({"session_id": session_id}, upd)

    async def ring_sessions_pending_notify(self, limit: int = 20,
                                           window_s: int = 1800) -> list[dict]:
        """sessionهای فعال که اطلاعیهٔ مچِ یک یا هر دو طرف نرسیده است.

        پنجرهٔ زمانی (§۳۲): فقط نیم ساعتِ آخر — بعد از آن کاربر خودش
          `/ring` را می‌زند و مسیرِ adopt همان کارت را می‌گیرد؛ ما برای یک
          چتِ پنج‌روزهٔ تمام‌شده پیام نمی‌فرستیم.
        """
        cutoff = (now_utc() - timedelta(seconds=int(window_s))).isoformat()
        out: list[dict] = []
        cur = self.ring_cols.sessions.find(
            {"status": ACTIVE, "created_at": {"$gte": cutoff}}
        ).sort("created_at", -1).to_list(int(limit) * 4)
        for d in await cur:
            notify = d.get("notify") or {}
            slots = [int(x) for x in (d.get("slots") or [])]
            missing = [u for u in slots if not (notify.get(str(u)) or {}).get("s")]
            if missing:
                out.append({"session_id": d.get("session_id"), "slots": slots,
                            "notify": notify, "mode": d.get("mode"),
                            "created_at": d.get("created_at"), "missing": missing})
            if len(out) >= int(limit):
                break
        return out

    async def ring_session_note(self, session_id: str, fields: dict) -> None:
        await self.ring_cols.sessions.update_one(
            {"session_id": session_id}, {"$set": fields})

    async def ring_session_idle(self, idle_s: int, limit: int = 500) -> list[dict]:
        cutoff = (now_utc() - timedelta(seconds=idle_s)).isoformat(timespec="seconds")
        return await self.ring_cols.sessions.find(
            {"status": ACTIVE, "last_activity_at": {"$lt": cutoff}}
        ).to_list(limit)

    async def ring_session_list(self, *, status: str | None = ACTIVE, mode: str | None = None,
                                uid: int | None = None, page: int = 1,
                                per: int = 25) -> tuple[list[dict], int]:
        q: dict = {}
        if status:
            q["status"] = status
        if mode:
            q["mode"] = mode
        if uid is not None:
            q["slots"] = int(uid)
        col = self.ring_cols.sessions
        total = await col.count_documents(q)
        rows = await col.find(q).sort("created_at", -1).skip((page - 1) * per).to_list(per)
        return rows, total

    async def ring_reconcile(self) -> dict:
        """تعمیمِ ناسازگاری‌ها (§۴۵): هر کاربری که active session ندارد ولی
        در صف با status=in_chat قفل شده، آزاد می‌شود؛ و برعکس."""
        freed = dup = 0
        async for d in self.ring_cols.queue.find({"status": QUEUE_INCHAT}).limit(2000):
            s = await self.ring_session_active_for(d["user_id"])
            if not s or (s.get("session_id") != d.get("session_id")):
                # release فقط claimed را آزاد می‌کند؛ اینجا کاربر هیچ چت
                # فعالی ندارد پس سند صف باید کلاً برود (§۴۵).
                await self.ring_queue_leave(d["user_id"])
                freed += 1
        # دو active session با یک کاربر (فقط اگر ایندکس از هر دو side رد شده باشد)
        seen: dict[int, str] = {}
        async for s in self.ring_cols.sessions.find({"status": ACTIVE}).limit(2000):
            for u in s.get("slots") or []:
                u = int(u)
                if u in seen:
                    await self.ring_session_end(s["session_id"], "reconcile_duplicate", None)
                    dup += 1
                    break
                seen[u] = s["session_id"]
        return {"freed": freed, "duplicate_sessions_closed": dup}

    # ══════════════════════════════════════════════════════════
    #  blocks
    # ══════════════════════════════════════════════════════════

    async def ring_block(self, blocker: int, blocked: int, reason: str = "") -> None:
        # رابطه دوطرفه «ممنوعه» است ⇒ هر دو جهت ثبت می‌شود تا
        # find_one_and_update بتواند با یک $O(1) lookup فیلتر کند.
        now = utc_now_iso()
        for a, b in ((int(blocker), int(blocked)), (int(blocked), int(blocker))):
            await self.ring_cols.blocks.update_one(
                {"_id": f"{a}:{b}"},
                {"$setOnInsert": {"user_id": a, "blocked_user_id": b,
                                  "reason": reason[:200], "created_at": now}},
                upsert=True)
        await self.ring_cols.profiles.update_one(
            {"_id": int(blocked)}, {"$inc": {"block_count": 1}})

    async def ring_block_ids(self, uid: int) -> list[int]:
        """هر دو جهت بلاک (§۱۹): کسانی که من بلاک کردم + کسانی که مرا بلاک
        کرده‌اند — اگر فقط یک سمت را برگردانیم، طرفِ بلاک‌کننده می‌تواند
        دوباره با من matched شود و وعده‌ی «دیگر هیچ‌وقت» نقض می‌شود."""
        ids: set[int] = set()
        me = int(uid)
        async for d in self.ring_cols.blocks.find(
                {"$or": [{"user_id": me}, {"blocked_user_id": me}]},
                {"user_id": 1, "blocked_user_id": 1}).limit(3000):
            if int(d.get("user_id", -1)) == me:
                other = d.get("blocked_user_id")
            else:
                other = d.get("user_id")
            if other is not None:
                ids.add(int(other))
        ids.discard(me)
        return sorted(ids)

    async def ring_blocked_between(self, a: int, b: int) -> bool:
        d = await self.ring_cols.blocks.find_one(
            {"_id": {"$in": [f"{int(a)}:{int(b)}", f"{int(b)}:{int(a)}"]}})
        return bool(d)

    async def ring_unblock(self, uid: int, other: int) -> None:
        for a, b in ((int(uid), int(other)), (int(other), int(uid))):
            await self.ring_cols.blocks.delete_many(
                {"$or": [{"_id": f"{a}:{b}"},
                        {"user_id": a, "blocked_user_id": b}]})

    async def ring_blocks_recent(self, limit: int = 100) -> list[dict]:
        """تازه‌ترین مسدودسازی‌ها (برای پنل؛ بدون هیچ محتوای گفت‌وگو)."""
        return await self.ring_cols.blocks.find({}).sort("created_at", -1).to_list(int(limit))

    async def ring_blocks_list(self, uid: int) -> list[dict]:
        return await self.ring_cols.blocks.find({"user_id": int(uid)}).to_list(200)

    # ══════════════════════════════════════════════════════════
    #  reports
    # ══════════════════════════════════════════════════════════

    # §۲۲ — severity برای وزن‌دهی به گزارش‌ها. دیکشنری در `ring.models`
    # منبعِ یکتا است؛ اینجا فقط aliasهای کلیدهای قدیمی نگه داشته می‌شود تا
    # گزارش‌های ذخیره‌شده قبل از این تغییر هم درست وزن بگیرند.
    SEVERITY = {"harassment": 2, "insult": 1, "sexual": 3, "money": 4,
                "offapp": 3, "spam": 1, "doxxing": 4, "other": 1,
                "sexual_content": 3, "scam": 4, "suspicious": 2}

    async def ring_report_create(self, rep: dict) -> int:
        seq_doc = await self.ring_cols.counters.find_one_and_update(
            {"_id": "ring_reports"}, {"$inc": {"seq": 1}}, upsert=True)
        rid = int((seq_doc or {}).get("seq", 0)) + 1
        rep["report_id"] = rid
        rep["status"] = "pending"
        rep["created_at"] = utc_now_iso()
        rep.setdefault("severity", self.SEVERITY.get(rep.get("reason", "other"), 1))
        await self.ring_cols.reports.insert_one(rep)
        return rid

    async def ring_report_get(self, rid: int) -> dict | None:
        return await self.ring_cols.reports.find_one({"report_id": int(rid)})

    async def ring_report_list(self, status: str | None = None, page: int = 1,
                               per: int = 25) -> tuple[list[dict], int]:
        q = {} if not status else {"status": status}
        col = self.ring_cols.reports
        total = await col.count_documents(q)
        rows = await col.find(q).sort("created_at", -1).skip((page - 1) * per).to_list(per)
        return rows, total

    async def ring_report_set_status(self, rid: int, status: str, admin_id: int,
                                     note: str = "") -> None:
        await self.ring_cols.reports.update_one(
            {"report_id": int(rid)},
            {"$set": {"status": status, "handled_by": int(admin_id),
                      "handled_at": utc_now_iso(), "admin_note": note[:500]}},
        )

    async def ring_reports_against(self, uid: int, within_days: int = 30) -> list[dict]:
        since = (now_utc() - timedelta(days=within_days)).isoformat(timespec="seconds")
        return await self.ring_cols.reports.find(
            {"reported_uid": int(uid), "created_at": {"$gte": since}}).to_list(100)

    async def ring_report_duplicate(self, uid: int, rid: int, dup_ids: list[int]) -> None:
        await self.ring_cols.reports.update_many(
            {"report_id": {"$in": [int(r) for r in dup_ids]}},
            {"$set": {"status": "merged", "duplicate_of": int(rid)}})

    # ══════════════════════════════════════════════════════════
    #  bans (مستقل از بن سراسری ربات — §۳۷)
    # ══════════════════════════════════════════════════════════

    async def ring_ban_create(self, uid: int, kind: str, until_iso: str | None,
                              reason: str, admin_id: int, scope: str = "ring") -> None:
        await self.ring_cols.bans.insert_one({
            "user_id": int(uid), "kind": kind, "scope": scope,
            "until": until_iso, "reason": (reason or "")[:300],
            "admin_id": int(admin_id), "created_at": utc_now_iso(), "active": True,
        })
        await self.ring_cols.profiles.update_one(
            {"_id": int(uid)},
            {"$set": {"status": "banned", "banned_until": until_iso}})
        await self.ring_queue_drop_user(uid)

    async def ring_ban_active(self, uid: int) -> dict | None:
        """بنِ فعال (temp با expiry لحاظ می‌شود؛ permanent تا lift)."""
        now = utc_now_iso()
        d = await self.ring_cols.bans.find_one({
            "user_id": int(uid), "active": True,
            "$or": [{"until": None}, {"until": {"$gt": now}}]},
            sort=[("created_at", -1)])
        if not d:
            # انقضا: flag را تمیز کن تا profile هم آزاد شود
            exp = await self.ring_cols.bans.find_one(
                {"user_id": int(uid), "active": True,
                 "kind": "temporary", "until": {"$lte": now}})
            if exp:
                await self.ring_ban_lift(uid, "expired")
        return d

    async def ring_ban_lift(self, uid: int, note: str = "") -> None:
        await self.ring_cols.bans.update_many(
            {"user_id": int(uid), "active": True},
            {"$set": {"active": False, "lifted_at": utc_now_iso(), "lift_note": note[:200]}})
        await self.ring_cols.profiles.update_one(
            {"_id": int(uid)},
            {"$set": {"status": "active", "banned_until": None}})

    async def ring_ban_list(self, limit: int = 100) -> list[dict]:
        return await self.ring_cols.bans.find({}).sort("created_at", -1).to_list(limit)

    # ══════════════════════════════════════════════════════════
    #  ratings (§۲۴ — anonymous، فقط امتیاز)
    # ══════════════════════════════════════════════════════════

    async def ring_rating_add(self, session_id: str, rater: int, rated: int,
                              score: int) -> bool:
        """یک rating به‌ازای هر (session, rater) — `$setOnInsert` ⇒ دوباره‌زنی
        دکمه هیچ اثری ندارد (§۶۲)."""
        r = await self.ring_cols.ratings.update_one(
            {"_id": f"{session_id}:{int(rater)}"},
            {"$setOnInsert": {"session_id": session_id, "rater_uid": int(rater),
                              "rated_uid": int(rated), "score": int(score),
                              "created_at": utc_now_iso()}},
            upsert=True)
        return r.upserted_id is not None

    async def ring_rating_stats(self, uid: int) -> dict:
        out = {"n": 0, "avg": None}
        async for d in self.ring_cols.ratings.aggregate([
                {"$match": {"rated_uid": int(uid)}},
                {"$group": {"_id": None, "n": {"$sum": 1}, "avg": {"$avg": "$score"}}}]):
            out = {"n": d["n"], "avg": round(d["avg"], 2) if d.get("avg") is not None else None}
        return out

    # ══════════════════════════════════════════════════════════
    #  evidence (snapshot محدود + TTL)
    # ══════════════════════════════════════════════════════════

    async def ring_evidence_put(self, doc: dict) -> None:
        doc.setdefault("created_at", utc_now_iso())
        await self.ring_cols.evidence.update_one(
            {"_id": doc["_id"]}, {"$setOnInsert": doc}, upsert=True)

    async def ring_evidence_for(self, session_id: str, limit: int = 60) -> list[dict]:
        return await self.ring_cols.evidence.find({"session_id": session_id}).sort("seq", 1).to_list(limit)

    async def ring_evidence_purge(self) -> int:
        """پاک‌سازی دستی (TTL monitor هم خودش انجام می‌دهد — این برای admin)"""
        r = await self.ring_cols.evidence.delete_many({"expires_at": {"$lte": now_utc()}})
        return r.deleted_count

    # ══════════════════════════════════════════════════════════
    #  rate limit — bucket‌های شمارشی با TTL (§۲۲)
    # ══════════════════════════════════════════════════════════

    async def ring_limit_hit(self, scope: str, uid: int, limit: int,
                             window_s: int) -> dict:
        """atomic counter در بازهٔ زمانی. برمی‌گرداند {ok, n, retry_after}."""
        uid = int(uid)
        if limit <= 0:
            return {"ok": True, "n": 0, "retry_after": 0}
        ts = now_utc()
        bucket = int(ts.timestamp() // window_s)
        _id = f"{scope}:{uid}:{bucket}"
        expires = ts.replace(microsecond=0) + timedelta(
            seconds=(bucket + 1) * window_s - int(ts.timestamp()) + 5)
        doc = await self.ring_cols.limits.find_one_and_update(
            {"_id": _id},
            {"$inc": {"n": 1}, "$set": {"expires_at": expires, "scope": scope,
                                        "user_id": uid, "window": window_s}},
            upsert=True, return_document=ReturnDocument.AFTER)
        n = int((doc or {}).get("n", 1))
        if n > limit:
            # retry_after = زمان تا ابتدای باکت بعدی (نه TTL که ۵ ثانیه
            # حاشیه دارد) ⇒ هیچ‌وقت بیشتر از خود window نمی‌شود.
            retry = (bucket + 1) * window_s - int(ts.timestamp())
            return {"ok": False, "n": n, "retry_after": max(1, int(retry))}
        return {"ok": True, "n": n, "retry_after": 0}

    # ══════════════════════════════════════════════════════════
    #  audit + daily stats
    # ══════════════════════════════════════════════════════════

    async def ring_audit(self, admin_id: int | str, action: str, target: str,
                         reason: str, meta: dict | None) -> bool:
        try:
            await self.ring_cols.audit.insert_one({
                "admin_id": str(admin_id), "action": action, "target": str(target),
                "reason": (reason or "")[:300], "meta": meta or {},
                "created_at": utc_now_iso()})
            return True
        except Exception as e:
            logger.exception("ring_audit failed: %s", e)
            return False

    async def ring_audit_list(self, limit: int = 100) -> list[dict]:
        return await self.ring_cols.audit.find({}).sort("created_at", -1).to_list(limit)

    async def ring_bump(self, **counters: int) -> None:
        """شمارنده‌ی روزانه برای نمودارها (users/day, sessions/day, reports/day)."""
        day = now_utc().date().isoformat()
        inc = {f"c.{k}": int(v) for k, v in counters.items() if v}
        if not inc:
            return
        await self.ring_cols.daily.update_one(
            {"date": day}, {"$inc": inc, "$set": {"updated_at": utc_now_iso()}},
            upsert=True)

    async def ring_bump_max(self, key: str, value: int) -> None:
        """بیشترین مقدارِ دیده‌شده در روز (§۳۹ — max wait). `$max` idempotent است."""
        day = now_utc().date().isoformat()
        await self.ring_cols.daily.update_one(
            {"date": day},
            {"$max": {f"c.{key}": int(value)}, "$set": {"updated_at": utc_now_iso()}},
            upsert=True)

    async def ring_daily(self, days: int = 14) -> list[dict]:
        since = (now_utc() - timedelta(days=days)).date().isoformat()
        return await self.ring_cols.daily.find({"date": {"$gte": since}}).sort("date", 1).to_list(days + 2)

    # ══════════════════════════════════════════════════════════
    #  admin helpers
    # ══════════════════════════════════════════════════════════

    async def ring_admin_profiles(self, *, status: str | None = None, q: str | None = None,
                                  mode: str | None = None, page: int = 1,
                                  per: int = 25) -> tuple[list[dict], int]:
        """جست‌وجوی ادمین (§۷۰): فقط با آیدی عددی تلگرام یا ناشناس‌آی‌دی.

        عمداً جست‌وجوی «نام/بیو» وجود ندارد — تبدیل پنل به دایرکتوری
        هویت، کل وعده‌ی ناشناس‌بودن را باطل می‌کند (§۳۱)."""
        query: dict = {}
        if status:
            query["status"] = status
        if mode:
            query["mode"] = mode
        if q:
            s = str(q).strip()
            if s.lstrip("#").isdigit():
                # _id پروفایل همان user_id است (فیلد جدا نداریم)
                query["_id"] = int(s.lstrip("#"))
            elif s:
                query["anon_id"] = {"$regex": re.escape(s.lstrip("#").upper()),
                                    "$options": "i"}
        col = self.ring_cols.profiles
        total = await col.count_documents(query)
        rows = await col.find(query).sort("created_at", -1).skip((page - 1) * per).to_list(per)
        return rows, total

    async def ring_overview(self) -> dict:
        """داشبورد پنل. §۵۸ (V6) — هر شمارش در shell خودش.

        روی سرورِ زنده پنل با بنر «بازیابی داده‌های رینگ ناموفق بود» مواجه شد؛
        اگر حتی *یک* count_documents بدود (مثلاً در میانه‌ی restart)، پاسخ کل
        درخواست ۵۰۰ می‌شد و کاربر هیچی نمی‌دید. حالا هر بخش جدا می‌شکند،
        خطایش در `errors` می‌آید و بقیهٔ پنل رندر می‌شود.
        """
        c = self.ring_cols
        now = utc_now_iso()
        today = now_utc().date().isoformat()
        out: dict = {"errors": {}, "last_updated": now}

        async def k(key, coro):
            try:
                out[key] = await coro
            except Exception as e:
                out["errors"][key] = str(e)[:160]

        await k("profiles", c.profiles.count_documents({}))
        await k("active_profiles", c.profiles.count_documents({"status": "active"}))
        await k("paused", c.profiles.count_documents({"status": "paused"}))
        await k("banned", c.profiles.count_documents({"status": "banned"}))
        await k("waiting", c.queue.count_documents({"status": QUEUE_WAITING}))
        await k("in_chat", c.sessions.count_documents({"status": ACTIVE}))
        await k("sessions_today", c.sessions.count_documents({"created_at": {"$gte": today}}))
        await k("sessions_total", c.sessions.count_documents({}))
        await k("reports_pending", c.reports.count_documents({"status": "pending"}))
        await k("reports_today", c.reports.count_documents({"created_at": {"$gte": today}}))
        await k("blocks", c.blocks.count_documents({}))
        await k("bans_active", c.bans.count_documents({"active": True}))
        # ── V6: سلامتِ لایهٔ ارسال + کارهای معوقه (§۳۰/§۴۶) ──
        try:
            from ring import notify as _N
            out["notify_health"] = _N.health()
        except Exception as e:
            out["errors"]["notify_health"] = str(e)[:160]
        try:
            out["pending_notify"] = len(await self.ring_sessions_pending_notify(limit=200))
        except Exception as e:
            out["errors"]["pending_notify"] = str(e)[:160]
        try:
            out["pending_ui"] = len(await self.ring_search_msg_pend_ids(limit=200))
        except Exception as e:
            out["errors"]["pending_ui"] = str(e)[:160]
        try:
            # §۴۸ (V6) — نشانهٔ واقعِ «یتیمِ تایمر»: پیامِ انتظار روی پروفایلی
            # که داخل گفت‌وگو است (current_session دارد). کسی که *در صف است*
            # و حباب دارد، یتیم نیست؛ با predicateِ قبلی هر منتظرِ سالمی هم
            # شمرده می‌شد و پنل آمارِ خطای جعلی نشان می‌داد.
            out["timer_orphans"] = await c.profiles.count_documents(
                {"search_msg": {"$exists": True},
                 "current_session": {"$nin": [None, ""]}})
        except Exception as e:
            out["errors"]["timer_orphans"] = str(e)[:160]
        if not out["errors"]:
            out.pop("errors")
        return out
