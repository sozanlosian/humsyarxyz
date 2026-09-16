"""💍 Ring Street — چرخه‌ی عمر صف/جلسه (§۷..§۱۰، §۱۷..§۲۱، §۴۵)

نکته‌ی طراحی که باید حفظ شود: هر transition باید **از Mongo قابل
تکرار** باشد. handler تلگرام ممکن است دو بار بیاید (دابل‌تپ، retry،
updater duplicate)؛ جایی که لازم است با `claim_token` و
`find_one_and_update` جلوی دوباره‌کاری گرفته می‌شود، و جایی که لازم
نیست `$setOnInsert` نگهش داشته (§۶۲).
"""
from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import timedelta

from ring import models as M
from ring import matcher, settings as S
from time_utils import now_utc, utc_now_iso

logger = logging.getLogger(__name__)

MAX_CONTENTION_RETRIES = 6   # تلاش مجدد وقتی صف خالی نیست ولی همه claimed‌اند
MAX_ATTEMPTS = 16         # سقف تلاش برای یافتن کاندید در هر match — هر تلاش یک
                          # find_one_and_update ایندکس‌شده است؛ زیر طوفانِ همزمانی
                          # این عدد جفت‌شدن‌های از‌دست‌رفته را جبران می‌کند (§۴۰).
MAX_PARTNERS_KEEP = 60    # سقف آرایه‌ی recent_partners در پروفایل


class Result(dict):
    """نتیجه‌ی یک عملیات — `kind` تعیین‌کننده‌ی پیام به کاربر است."""

    @classmethod
    def of(cls, kind: str, **kw) -> "Result":
        r = cls(kind=kind)
        r.update(kw)
        return r


def new_token() -> str:
    return secrets.token_hex(8)


# ══════════════════════════════════════════════════════════════
#  پروفایل / onboarding
# ══════════════════════════════════════════════════════════════

async def ensure_profile(uid: int, **seed) -> dict:
    """پروفایل را (اگر نیست) می‌سازد. شمارش «پروفایل جدید» هم همین‌جا."""
    from database import db
    existed = await db.ring_profile(uid) is not None
    doc = await db.ring_profile_ensure(uid, **seed)
    if not existed:
        await db.ring_bump(profiles=1)
    return doc


async def set_age(uid: int, age) -> Result:
    from database import db
    cfg = await S.get_cfg()
    if not M.age_ok(age, int(cfg.get("min_age", 18))):
        return Result.of("too_young")
    a = int(age)
    await db.ring_profile_update(uid, {
        "age": a, "age_range": M.range_of(a),
        "age_confirmed_at": utc_now_iso(), "age_self_declared": True,
    })
    await db.ring_profile_ensure(uid, age=a, age_range=M.range_of(a))
    return Result.of("ok")


async def set_gender(uid: int, gender: str) -> Result:
    from database import db
    g = M.norm_choice(gender, M.GENDERS)
    if not g:
        return Result.of("bad_input")
    await db.ring_profile_update(uid, {"gender": g})
    return Result.of("ok", gender=g)


async def set_mode(uid: int, mode: str) -> Result:
    from database import db
    m = M.norm_choice(mode, M.MODES)
    if not m:
        return Result.of("bad_input")
    if not await S.mode_enabled(m):
        return Result.of("mode_off", mode=m)
    # §۱۷ (V5) — اگر کاربر وسط جست‌وجو یا گفت‌وگو باشد، عوض‌کردن حالت صف/session
    # را با هم ناسازگار می‌کند (ردیفش در حالت قبلی می‌ماند). این گارد *اینجا*
    # است، نه فقط در UI؛ هر مسیر دیگری (ادیتور پنل، ربات) هم همان را می‌گیرد.
    q = await db.ring_queue_get(uid)
    if q and q.get("status") in ("waiting", "claiming"):
        return Result.of("locked", why="searching", mode=m)
    if await db.ring_session_active_for(uid):
        return Result.of("locked", why="in_chat", mode=m)
    await db.ring_profile_update(uid, {"mode": m})
    await db.ring_bump(**{f"profiles_{m}": 1})   # شمارش per-mode (مقدار باید int باشد)
    return Result.of("ok", mode=m)


def rules_want(cfg: dict | None = None) -> int:
    """نسخه‌ای از قوانین که کاربر باید پذیرفته باشد (§۲۷/§۴۰).

    `max` یعنی نسخهٔ موجود در **کد** کفِ الزامی است: ریلاسی که متن قوانین را
    عوض می‌کند (RULES_VERSION بالا می‌رود) همه را یک‌بار دوباره می‌پرسد، حتی
    اگر ادمین در پنل عددِ کمتری تنظیم کرده باشد. ادمین فقط می‌تواند بیشتر کند.
    """
    return max(int((cfg or {}).get("rules_version") or 0), M.RULES_VERSION)


async def accept_terms(uid: int, *, version: int | None = None) -> Result:
    """پذیرش قوانین (§۲۷): نسخه و زمانش هم ذخیره می‌شود تا با تغییر نسخهٔ
    قوانین، کاربر دوباره بپرسیم (بدون این، پذیرش همیشگی می‌ماند)."""
    from database import db
    cfg = await S.get_cfg()
    stamp = utc_now_iso()
    await db.ring_profile_update(uid, {
        "consent_terms_at": stamp, "rules_accepted_at": stamp,
        "rules_version": int(version or rules_want(cfg))})
    await db.ring_bump(consents=1)
    return Result.of("ok", version=int(version or rules_want(cfg)))


async def set_view(uid: int, key: str, on: bool) -> Result:
    """«چه چیزهایی از پروفایلم دیده شود» (§۳۵) — فقط کلیدهای مجاز."""
    from database import db
    if key not in M.PROFILE_VIEW:
        return Result.of("bad_input")
    await db.ring_profile_update(uid, {key: bool(on)})
    return Result.of("ok", key=key, on=bool(on))


async def rules_pending(uid: int) -> bool:
    """آیا کاربر باید دوباره قوانین را بپذیرد؟ (§۲۷)"""
    from database import db
    cfg = await S.get_cfg()
    p = await db.ring_profile(uid) or {}
    want = rules_want(cfg)
    return int(p.get("rules_version") or 0) < want


async def stop_timer(uid: int) -> None:
    """§۱۲ — خاموش‌کردن تایمر بدون تغییر حالت (هر جای مشکوک از همین‌جا)."""
    await forget_search_msg(uid)


async def pause_search(uid: int) -> Result:
    """«⏸ توقف جست‌وجو» (§۱۴/§۲۳/§۷۰): خروج از صف، بدون/session و بدون
    دست‌زدن به پروفایل — اگر وسط گفت‌وگو باشد، چیزی را نمی‌بندد.

    §۲۳ — «توقف» یک حالتِ *ماندگار* است (نه فقط نبودنِ ردیف در صف): فلگ روی
    پروفایل می‌نشیند تا بعد از ری‌استارتِ پروسه هم `state_of` همان PAUSED را
    بدهد و کاربر ناخودآگاه دوباره در صف نیفتد.
    """
    from database import db
    q = await db.ring_queue_get(uid)
    if q and q.get("status") == "in_chat":
        return Result.of("in_chat")
    await db.ring_queue_leave(uid)
    await db.ring_profile_update(uid, {"search_paused": True})
    await forget_search_msg(uid)          # §۱۲ — پیامِ انتظار هم باید بمیرد
    return Result.of("paused")


async def resume_search(uid: int) -> Result:
    """«▶️ ادامه جست‌وجو» — فلگ توقف را پاک می‌کند و کاربر دوباره آماده است."""
    from database import db
    await db.ring_profile_update(uid, {"search_paused": False})
    return await join_queue(uid)


async def state_of(uid: int) -> str:
    """§۵/§۱۲ — حالتِ واحدِ کاربر از همان سه منبعِ موجود (+ فلگِ EXPIRED در V5).

    تنها جایی که «من کجا هستم؟» تعیین می‌شود: صفحهٔ رینگ، فیلترِ رله،
    /ring status و پنل ادمین همه همین را می‌خوانند.
    """
    from database import db
    p = await db.ring_profile(uid) or {}
    q = await db.ring_queue_get(uid)
    sess = await db.ring_session_active_for(uid)
    ended = False
    if not sess and not q and (p.get("recent_partners") or []):
        cfg = await S.get_cfg()
        ended = bool(await recent_pairs(
            p, int(cfg.get("rematch_after_s") or cfg.get("skip_cooldown_s") or 0)))
    return M.user_state(p, q, sess, banned=bool(await db.ring_ban_active(uid)),
                        ended_recently=ended,
                        expired_recently=bool(p.get("search_expired_at")))


async def pair_diagnose(uid: int, cid: int) -> dict:
    """§۳۷/§۳۸ — «چرا این دو نفر به هم مچ نشدند؟» با همان الگوریتمِ واقعی.

    از پنل ادمین صدا زده می‌شود و *هیچ* مسیر جدیدی برای تصمیم نمی‌سازد:
    دقیقاً `_verdict` (همان که حلقهٔ مچ اجرا می‌کند) اجرا می‌شود.
    """
    from database import db
    cfg = await S.get_cfg()
    me_p = await db.ring_profile(uid) or {}
    cand_q = await db.ring_queue_get(cid)
    cand_p = await db.ring_profile(cid) or {}
    mode = (cand_q or {}).get("mode") or cand_p.get("mode") or me_p.get("mode") or "fun"
    v = await _verdict(uid, cid, {**(cand_q or {}), **cand_p, "user_id": cid},
                       mode, cfg, [], [], me={**me_p, "user_id": uid})
    q = await db.ring_queue_get(uid)
    return {
        "ok": bool(v["ok"]), "reason": v.get("reason") or "",
        "checks": v.get("checks") or {}, "hints": v.get("hints") or {},
        "mode": mode,
        "a": {"state": await state_of(uid),
              "in_queue": bool(q and q.get("status") in ("waiting", "claiming", "claimed")),
              "queue_status": (q or {}).get("status"),
              "state_label": M.US_LABELS.get(await state_of(uid), "—")},
        "b": {"state": await state_of(cid),
              "in_queue": bool(cand_q and cand_q.get("status") in
                               ("waiting", "claiming", "claimed")),
              "queue_status": (cand_q or {}).get("status"),
              "state_label": M.US_LABELS.get(await state_of(cid), "—")},
    }


async def ready(uid: int) -> tuple[bool, str]:
    """آیا کاربر می‌تواند وارد صف شود؟ (سن + جنسیت + حالت + قوانین + بن)"""
    from database import db
    cfg = await S.get_cfg()
    p = await db.ring_profile(uid)
    if not p:
        return False, "no_profile"
    if p.get("status") == "banned":
        if not await db.ring_ban_active(uid):
            await db.ring_profile_status(uid, "active")   # بن تمام شده
        else:
            return False, "banned"
    if p.get("status") == "paused":
        return False, "paused"
    if not M.age_ok(p.get("age"), int(cfg.get("min_age", 18))):
        return False, "too_young"
    if not p.get("gender"):
        return False, "no_gender"
    if not p.get("mode"):
        return False, "no_mode"
    if not await S.mode_enabled(p.get("mode")):
        return False, "mode_off"
    if not p.get("consent_terms_at"):
        return False, "no_terms"
    # §۲۷ — با بالا رفتن نسخهٔ قوانین، پذیرش قبلی دیگر کافی نیست
    want = rules_want(cfg)
    if int(p.get("rules_version") or 0) < want:
        return False, "rules_outdated"
    # §۴۵ — حالت زرد: پروفایل و چت‌ها سالم، ولی match تازه ساخته نمی‌شود
    if await S.maintenance():
        return False, "maintenance"
    return True, ""


async def update_profile(uid: int, fields: dict) -> Result:
    from database import db
    cfg = await S.get_cfg()
    rl = await db.ring_limit_hit("profile", uid, int(cfg["max_profile_per_hour"]), 3600)
    if not rl["ok"]:
        return Result.of("rate_limited", retry_after=rl["retry_after"], scope="profile")
    allowed = set(M.PROFILE_FIELDS) | {
        "age", "gender", "mode", "intent", "topics",
        "pref_gender", "pref_age_ranges", "serious_intent", "seek_mode"}
    sets: dict = {}
    for k, v in (fields or {}).items():
        if k not in allowed:
            continue
        if k in M.PROFILE_FIELDS:
            sets[k] = M.clean_text(v, M.PROFILE_FIELDS[k][1])
        elif k == "age":
            if not M.age_ok(v, int(cfg.get("min_age", 18))):
                return Result.of("too_young")
            sets["age"] = int(v)
            sets["age_range"] = M.range_of(int(v))
        elif k == "gender":
            g = M.norm_choice(v, M.GENDERS)
            if not g:
                return Result.of("bad_input")
            sets["gender"] = g
        elif k == "mode":
            m = M.norm_choice(v, M.MODES)
            if not m:
                return Result.of("bad_input")
            sets["mode"] = m
        elif k == "intent":
            sets["intent"] = M.norm_choice(v, M.INTENTS, None)
        elif k == "topics":
            sets["topics"] = [t for t in (v or []) if t in M.TOPICS][:6]
        elif k in ("pref_gender",):
            sets[k] = M.norm_choice(v, list(M.GENDERS) + ["any"], "any")
        elif k in ("pref_age_ranges",):
            keys = [x.strip() for x in str(v or "").split(",")]
            valid = [k for k in keys if k in M.AGE_INDEX]
            sets[k] = ",".join(valid) if valid else "any"
        else:
            sets[k] = M.clean_text(v, 120)
    if sets:
        await db.ring_profile_update(uid, sets)
        # سند صف هم باید همان ترجیحات را ببیند (برای فیلتر efi­cient)
        await sync_queue_doc(uid)
    return Result.of("ok", fields=list(sets))


async def sync_queue_doc(uid: int) -> None:
    """پروفایل ← سند صف (ترجیحات برای query کاندید لازم‌اند)."""
    from database import db
    p = await db.ring_profile(uid)
    q = await db.ring_queue_get(uid)
    if not p or not q:
        return
    await db.ring_cols.queue.update_one({"_id": uid}, {"$set": {
        "gender": p.get("gender"), "age": p.get("age"),
        "age_range": p.get("age_range"), "mode": p.get("mode"),
        "pref_gender": p.get("pref_gender"), "pref_age_ranges": p.get("pref_age_ranges"),
        "topics": p.get("topics") or [],
    }})


# ══════════════════════════════════════════════════════════════
#  صف
# ══════════════════════════════════════════════════════════════

async def join_queue(uid: int, mode: str | None = None) -> Result:
    from database import db
    if not await S.get_flag():
        return Result.of("disabled")
    # §۲۳ — «توقف» با ورود دوباره به صف لغو می‌شود (وگرنه PAUSED چسبناک می‌ماند)
    if (await db.ring_profile(uid) or {}).get("search_paused"):
        await db.ring_profile_update(uid, {"search_paused": False})
    # §۳۶ (V5) — «زمان جست‌وجو تمام شد» با جست‌وجوی تازه پاک می‌شود؛ اگر پاک
    # نشود، صفحهٔ رینگ تا ابد همان پیامِ قدیمی را نشان می‌دهد.
    if (await db.ring_profile(uid) or {}).get("search_expired_at"):
        await db.ring_profile_update(uid, {"search_expired_at": None})
    ok, why = await ready(uid)
    if not ok:
        return Result.of(why)
    p = await db.ring_profile(uid)
    mode = mode or p.get("mode")
    if not await S.mode_enabled(mode):
        return Result.of("mode_off", mode=mode)
    if await S.maintenance():                       # §۴۵ — match تازه ممنوع
        return Result.of("maintenance")
    cfg = await S.get_cfg()
    rl = await db.ring_limit_hit("search", uid, int(cfg["max_search_per_min"]), 60)
    if not rl["ok"]:
        return Result.of("rate_limited", retry_after=rl["retry_after"], scope="search")
    doc = {
        "mode": mode, "gender": p.get("gender"), "age": p.get("age"),
        "age_range": p.get("age_range"), "pref_gender": p.get("pref_gender"),
        "pref_age_ranges": p.get("pref_age_ranges"), "topics": p.get("topics") or [],
        "anon_id": p.get("anon_id"),
    }
    st = await db.ring_queue_join(uid, doc)
    if st == "already_in_chat":
        return Result.of("in_chat", session_id=(await db.ring_queue_get(uid) or {}).get("session_id"))
    if st == "claimed":
        # رزروِ matcherِ دیگر دست‌نخورده می‌ماند؛ kind=waiting ⇒ search()
        # وارد try_match می‌شود و همان‌جا یا session را adopt می‌کند یا busy.
        return Result.of("waiting", mode=mode, reserving=True, queued=0, waited_s=0)
    await db.ring_audit("user", "QUEUE_JOIN", str(uid), mode, {})
    await db.ring_bump(queue_join=1)
    # §۴۱ (V5) — برچسب‌های diagnostic؛ هرگز به‌جای متنِ چت و همیشه یک‌خطی.
    logger.info("RING_SEARCH_START uid=%s mode=%s status=%s", uid, mode, st)
    mine = await db.ring_queue_get(uid)
    return Result.of("waiting", mode=mode,
                     queued=await db.ring_queue_waiting_count(mode, [uid]),
                     waited_s=int(_waited_s(mine)))


async def cancel_search(uid: int) -> Result:
    """«از صف برو بیرون» بدون دست‌زدن به گفت‌وگو (§۴۴/§۶۴).

    برای /start و /cancel: اگر کاربر جریان رینگ را ول کرد، نباید در صف
    بماند و «در غیابش» match شود. اگر وسط گفت‌وگو باشد، چت دست‌نخورده است
    (ردیف صف‌اش `in_chat` است و اصلاً پاک نمی‌شود تا end_session درست کار کند).
    """
    from database import db
    q = await db.ring_queue_get(uid)
    if not q:
        sess = await db.ring_session_active_for(uid)
        if sess:
            return Result.of("in_chat", session_id=sess.get("session_id"))
        return Result.of("ok", queued=False)
    if q.get("status") == "in_chat":
        return Result.of("in_chat", session_id=q.get("session_id"))
    if q.get("status") == "claimed":
        # §۳۹ (V6) — matcher همین لحظه او را برداشته؛ ردیف را پاک نکن که
        # sessionِ دیگری بی‌صاحب می‌شود. برنده match است؛ cancelِ بعدی no-op.
        logger.info("RING_SEARCH_CANCEL_DEFERRED uid=%s reason=claimed", uid)
        return Result.of("busy", why="claimed")
    if not await db.ring_queue_leave_if(uid, ("waiting", "claiming")):
        sess = await db.ring_session_active_for(uid)
        if sess:
            return Result.of("matched", session_id=sess.get("session_id"))
        return Result.of("busy", why="row-changed")
    await forget_search_msg(uid)          # §۱۲ — تایمرِ یتیم ممنوع
    logger.info("RING_SEARCH_CANCEL uid=%s mode=%s", uid, q.get("mode"))
    return Result.of("ok", queued=True)


async def leave_queue(uid: int) -> Result:
    from database import db
    await db.ring_queue_leave(uid)
    return Result.of("ok")


async def search(uid: int) -> Result:
    """«🔎 پیدا کردن نفر» / «🔄 نفر بعدی» — join + match در یک فراخوانی."""
    r = await join_queue(uid)
    if r["kind"] != "waiting":
        return r
    return await try_match(uid)


async def _adopt_existing(uid: int, token: str) -> Result | None:
    """اگر matcherِ دیگری همین لحظه ما را برداشته، همان session را adopt کن.

    بدون این، دو جست‌وجوی هم‌زمان به هر دو طرف «کسی پیدا نشد» می‌گفت در حالی
    که یک session واقعی بین‌شان ساخته شده بود (§۹/§۱۰ race). کارت گفت‌وگو را
    سمتِ برنده ارسال شده، پس اینجا `silent` است تا کارت دوتایی نشود.
    """
    from database import db
    # تا ۴ ثانیه (با بیرون‌آمدن زودهنگام) صبر می‌کنیم: طرفِ برنده همین حالا
    # دارد session را می‌سازد؛ زیر بارِ ۲۰ جست‌وجوی هم‌زمان این کار می‌تواند
    # بیشتر از یک دورِ event loop طول بکشد و بی‌صبر بودن یعنی «کسی پیدا نشد»
    # برای کاربری که در واقعmatch شده است.
    for _ in range(20):
        sess = await db.ring_session_active_for(uid)
        if sess:
            peer = await db.ring_session_peer(sess, uid)
            logger.info("RING_MATCH_ADOPTED uid=%s sid=%s", uid, sess["session_id"])
            return Result.of("matched", session=sess, peer=peer, silent=True)
        mine = await db.ring_queue_get(uid)
        stt = (mine or {}).get("status")
        if not mine or stt in ("waiting", "claiming"):
            return None                      # رزور آزاد شد ⇒ منتظر نمی‌مانیم
        # claimed (در حال ساخته‌شدنِ session) و in_chat (session همین حالا
        # نوشته می‌شود) هر دو «صبر کن»‌اند؛ قبلاً in_chat را «آزاد» می‌شمرد
        # و کاربرِ واقعاً-match‌شده «empty» می‌گرفت.
        await asyncio.sleep(0.2)
    logger.info("RING_MATCH_ADOPT_TIMEOUT uid=%s", uid)
    return None


def _reject_log(uid: int, cid: int, reason: str, cfg: dict,
                verdict: dict | None = None) -> None:
    """لاگِ ساختارمندِ تلاشِ مچ (§۳۷/§۳۸).

    یک خطِ کلید=مقدار که با grep پیدا می‌شود و هیچ محتوای خصوصی ندارد؛ uidها
    فقط در حالت دیباگ کامل نوشته می‌شوند تا لاگ production قابل‌انتشار بماند.
    """
    v = (verdict or {}).get("checks", {}) or {}
    tags = " ".join(f"{k}=0" for k, ok in v.items() if not ok) or "-"
    line = (f"RING_MATCH_ATTEMPT reason={reason or 'ok'} result="
            f"{'MATCH' if (verdict or {}).get('ok', True) else 'REJECT'} "
            f"failed=[{tags}]")
    if cfg.get("debug_match_log"):
        logger.info("%s user_id=%s candidate_id=%s", line, uid, cid)
    else:
        logger.info("%s user_id=…%s candidate_id=…%s", line, str(uid)[-4:], str(cid)[-4:])


async def _search_pass(uid: int, token: str, me_q: dict, me_p: dict, mode: str,
                       cfg: dict, *, blocked: list[int], exclude: set[int],
                       verify_recent: list[int], announce: bool) -> Result:
    """یک دور جست‌وجو: کاندید از query (اتمیک claim) → سازگاری دوطرفه → session.

    `exclude` فیلترِ *کوئری* است و `verify_recent` همان فهرست برای چکِ
    نرم‌افزاری؛ تفکیکشان برای tier دوم (بازگشت به پارتنر اخیر) لازم است.
    """
    from database import db
    tried: list[int] = []
    contention = 0
    for _ in range(MAX_ATTEMPTS):
        cand = await db.ring_queue_find_candidate(
            mode,
            gender=(me_q.get("pref_gender")
                    if me_q.get("pref_gender") not in (None, "any") else None),
            age_range=_first_range(me_q.get("pref_age_ranges")),
            exclude=sorted(exclude | set(tried)), token=token)
        if not cand:
            # دو حالت: صف واقعاً خالی است، یا همه‌ی کاندیدها همین لحظه
            # توسط جست‌وجوگر دیگری claimed شده‌اند ⇒ تلاش کوتاه با backoff.
            others = await db.ring_queue_waiting_count(
                mode, sorted(exclude | set(tried)))
            if others and contention < MAX_CONTENTION_RETRIES:
                contention += 1
                await asyncio.sleep(0.12 * contention)
                continue
            return Result.of("empty", waited_s=int(_waited_s(me_q)), queued=others)
        cid = int(cand["user_id"])
        tried.append(cid)
        from ring import analytics as _A
        _A.note_metric("candidate_found")       # §۴۹ (V6)
        logger.debug("RING_CANDIDATE_FOUND uid=%s cand=…%s", uid, str(cid)[-4:])
        v = await _verdict(uid, cid, cand, mode, cfg, blocked, verify_recent,
                           me={**me_q, **me_p, "user_id": uid})
        reason = "" if v["ok"] else (v["reason"] or "incompat")
        if reason:
            _reject_log(uid, cid, reason, cfg, v)
            from ring import analytics as _A
            _A.note_reject(reason.split(":")[-1])          # §۳۹
            _A.note_metric("candidate_rejected")           # §۴۹ (V6)
            await db.ring_queue_release(cid)
            continue
        sess = await _open_session(uid, cid, me_p, mode, cfg)
        if sess:
            _A.note_metric("match_created")                 # §۴۹ (V6)
        if not sess:
            # یا slot او پر شده، یا matcherِ دیگری همین pair را ساخته ⇒
            # اگر session واقعیِ ما وجود دارد، همان را بگیر (نه «کسی نیست»)
            won = await db.ring_session_active_for(uid)
            if won:
                peer = await db.ring_session_peer(won, uid)
                if peer != cid:
                    # cid را نگرفته‌ایم ⇒ رزروی روی او را پس بده، وگرنه
                    # بی‌صدا یتیم می‌ماند تا repair (۱۵۰ ثانیه) آزادش کند
                    await db.ring_queue_release(cid)
                logger.info("RING_MATCH_STOLEN_TO_ADOPT uid=%s sid=%s peer=%s",
                            uid, won["session_id"], peer)
                return Result.of("matched", session=won,
                                 peer=peer if peer is not None else cid,
                                 silent=True)
            _reject_log(uid, cid, "race", cfg)
            await db.ring_queue_release(cid)
            continue
        await db.ring_report_recent(uid, cid, int(cfg["max_partners_history"]))
        await db.ring_bump(match=1, wait_s=int(_waited_s(me_q)))
        # §۳۹ — بیشترین انتظار روزانه با $max (رایگان، بدون read-modify-write)
        await db.ring_bump_max("max_wait_s", int(_waited_s(me_q)))
        logger.info("RING_MATCH_CREATED uid=%s peer=%s sid=%s wait_s=%s",
                    uid, cid, sess["session_id"], int(_waited_s(me_q)))
        if announce:
            # مسیر job (نه کاربر): کارت match را خودمان برای هر دو طرف
            # می‌فرستیم، چون هندلری که منتظر پاسخ است وجود ندارد (§۴۰).
            from ring import handlers as H
            await H.announce_match(uid, cid, sess, cfg)
        return Result.of("matched", session=sess, peer=cid)
    return Result.of("empty", tried=len(tried))


def _warn_no_bot_tick() -> None:
    """§۴۵/§۵۸ — «بات نیست» را بگو، ولی لاگ را سیل نکن (هر ۵ دقیقه یک‌بار)."""
    global _NOBOT_LOG_AT
    now = now_utc().timestamp()
    if now - float(_NOBOT_LOG_AT or 0.0) < 300.0:
        return
    _NOBOT_LOG_AT = now
    logger.warning("RING_SEARCH_TICK_NOBOT — بات در دسترس نیست؛ تایمر ویرایش "
                   "نمی‌کند (notify.bind در post_init را بررسی کن)")


async def _finalize_dead(uid: int, q: dict | None) -> bool:
    """§۸ (V6) — حبابِ «در حال جست‌وجو»ی یک کاربرِ دیگر-منتظر را نهایی می‌کند.

    وضعیت از DB خوانده می‌شود (نه از RAM): اگر session فعال باشد پیام
    «مچ شدی + کنترل‌های چت» و وگر نه «جست‌وجو تمام شد» می‌نشیند. اگر هیچ
    پیامِ قابل‌ویرایشی نباشد False برمی‌گرداند تا فراخوان شناسه را پاک کند.
    """
    from database import db
    from ring import keyboards as K, texts
    p = await db.ring_profile(uid) or {}
    sm = p.get("search_msg") or {}
    if not (sm.get("m") and sm.get("c")):
        return False
    sess = await db.ring_session_active_for(uid)
    cfg = await S.get_cfg()
    if sess:
        try:
            kb = K.kb_chat(sess.get("mode") or p.get("mode") or "fun", cfg)
        except Exception as e:
            logger.warning("RING_KB_FAIL uid=%s err=%s", uid, str(e)[:120])
            kb = None
        r = await finalize_search_ui(uid, "🎉 مچ شدی! کارت گفت‌وگو همین پایین "
                                          "آمده ✅ — دکمه‌های زیر گفت‌وگو را ببین.",
                                     kind="plain", cfg=cfg)
        if r == "edited" and kb is not None:
            await db.ring_cols.profiles.update_one({"_id": int(uid)},
                                                    {"$set": {"ring_last_ui": "chat"}})
        return r in ("edited", "pending")
    mode = (q or {}).get("mode") or p.get("mode") or "fun"
    try:
        text = texts.search_expired(mode, cfg, waited_s=int(_waited_s(q or {})), p=p)
    except Exception:
        text = "⌛ جست‌وجو به پایان رسید."
    r = await finalize_search_ui(uid, text, kind="expired", cfg=cfg, sm=sm)
    return r in ("edited", "pending")


async def _heal_after_race(uid: int, chat_id: int, message_id: int) -> None:
    """§۲۱ — editِ ما برندهٔ مسابقه نبود؛ متنِ نهایی را برگردان."""
    from database import db
    from ring import notify
    sess = await db.ring_session_active_for(uid)
    text = ("🎉 مچ شدی! کارت گفت‌وگو همین پایین آمده ✅" if sess
            else "⌛ جست‌وجو به پایان رسید.")
    bot = notify._bot()
    if bot is None:
        return
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
        logger.info("RING_SEARCH_UI_HEALED uid=%s reason=race to=%s",
                    uid, "matched" if sess else "expired")
    except Exception as e:
        logger.warning("RING_SEARCH_UI_HEAL_FAIL uid=%s err=%s", uid, str(e)[:140])



# ══════════════════════════════════════════════════════════
#  §۳/§۲۴ (V6) — چرخهٔ کاملِ «match» در **یک** تابع
#
#  تا V۵ این پنج کار در چهار نقطه پخش بودند (service._open_session،
#  handlers._announce_match، handlers._retire_wait، jobs.housekeeping) و هر
#  مسیرِ تازه‌ای می‌توانست یکی را جا بیندازد. روی سرورِ زنده همان شد:
#  session ساخته شد و رله کار کرد، ولی «توقف تایمر / نهایی‌کردن UI / اطلاعیه»
#  همه بی‌صدا `return` کردند (notify._bot() هیچ‌وقت بات نداشت).
# ══════════════════════════════════════════════════════════

NOTIFY_BACKOFF_S = (5, 15, 60)      # §۳۲ — سه تلاش، نه حلقهٔ بی‌نهایت
NOTIFY_MAX_TRIES = len(NOTIFY_BACKOFF_S)
UI_PEND_MAX_TRIES = 5               # §۱۴ — پیامی که هرگز نمی‌آید، با لاگ رها می‌شود
_NOBOT_LOG_AT = 0.0


def _ago_s(iso) -> float:
    """چند ثانیه از آن لحظه گذشته؟ (خطا ⇒ عددِ بزرگ، یعنی «همین حالا تلاش کن»)."""
    if not iso:
        return 1e9
    try:
        return max(0.0, (now_utc() - now_utc().fromisoformat(str(iso))).total_seconds())
    except Exception:
        return 1e9


def _HTML():
    from telegram.constants import ParseMode
    return ParseMode.HTML


async def _final_kb(kind, cfg: dict | None, p: dict):
    """دکمه‌های پیامِ نهایی — تا بعد از edit صفحه بن‌بست نشود (§۹/§۱۰)."""
    from ring import keyboards as K
    if kind == "expired":
        return K.kb_expired((p or {}).get("mode") or "fun", cfg or {})
    return None


_KB_DEFAULT = object()


async def finalize_search_ui(uid: int, text: str, *, kind: str = "plain",
                             cfg: dict | None = None,
                             sm: dict | None = None, markup=_KB_DEFAULT) -> str:
    """حبابِ «🔎 در حال جست‌وجو…» را با `text` جایگزین می‌کند (§۸/§۲۴ V6).

    بازگشت: `edited` | `pending` | `none`

    تفاوتِ مهم با V۵: اگر بات هنوز bind نشده باشد یا تلگرام edit را رد کند،
    شناسه **پاک نمی‌شود**؛ متن در `search_msg.pend` می‌ماند و
    `repair_search_ui` (از تیک / housekeeping / post_init) بعداً همان را
    می‌نشاند. این راهِ برگشتِ «۰۰:۰۰ تا ابد» است (§۵۵: UI هرگز نباید گم شود).
    """
    from database import db
    from ring import notify
    p = await db.ring_profile(uid) or {}
    have = p.get("search_msg") or {}
    # `sm` snapshotِ فراخوان است: اگر شناسه را *قبل از* این تابع پاک کرده باشیم
    # (مسیرِ انقضا آن را در کپی نگه می‌دارد تا تایمر نمیرد)، همان را مصرف می‌کنیم.
    sm = have if (have.get("m") and have.get("c")) else (sm or {})
    if not (sm.get("m") and sm.get("c")):
        return "none"
    bot = notify._bot()
    if bot is not None:
        kb = (await _final_kb(kind, cfg, p)) if markup is _KB_DEFAULT else markup
        try:
            await bot.edit_message_text(chat_id=int(sm["c"]), message_id=int(sm["m"]),
                                        text=text, parse_mode=_HTML(), reply_markup=kb)
            await db.ring_search_msg_clear(uid)
            from ring import analytics as _A
            _A.note_metric("search_ui_finalized")
            logger.info("RING_SEARCH_UI_FINALIZED uid=%s result=edited kind=%s",
                        uid, kind)
            return "edited"
        except Exception as e:
            logger.warning("RING_SEARCH_UI_FINALIZED uid=%s result=retry err=%s",
                           uid, str(e)[:140])
    if await db.ring_search_msg_pend(uid, text, kind,
                                     chat_id=sm.get("c"), message_id=sm.get("m")):
        logger.info("RING_SEARCH_UI_FINALIZED uid=%s result=pending kind=%s",
                    uid, kind)
    else:
        logger.warning("RING_SEARCH_UI_FINALIZED uid=%s result=lost kind=%s "
                       "(پروفایلی برای ثبتِ pend نبود)", uid, kind)
    return "pending"


async def repair_search_ui(limit: int = 20) -> int:
    """§۱۴ — `pend`های معوقه را اعمال می‌کند (ترمیم حبابِ یخ‌زده)."""
    from database import db
    from ring import notify
    n = 0
    cfg = await S.get_cfg()
    for uid in await db.ring_search_msg_pend_ids(limit):
        p = await db.ring_profile(uid) or {}
        sm = p.get("search_msg") or {}
        pend = str(sm.get("pend") or "").strip()
        if not pend or not sm.get("m") or not sm.get("c"):
            await db.ring_search_msg_clear(uid)
            continue
        bot = notify._bot()
        if bot is None:
            return n                          # هنوز باتی نیست؛ دورِ بعد
        if int(sm.get("pt") or 0) >= UI_PEND_MAX_TRIES:
            await db.ring_search_msg_clear(uid)
            logger.warning("RING_SEARCH_UI_FINALIZED uid=%s result=dropped tries=%s "
                           "(پیامِ روی صفحه پاک شده؟)", uid, sm.get("pt"))
            continue
        await db.ring_cols.profiles.update_one({"_id": int(uid)},
                                               {"$inc": {"search_msg.pt": 1}})
        try:
            await bot.edit_message_text(chat_id=int(sm["c"]), message_id=int(sm["m"]),
                                        text=pend, parse_mode=_HTML(),
                                        reply_markup=await _final_kb(sm.get("pend_k"),
                                                                     cfg, p))
            await db.ring_search_msg_clear(uid)
            from ring import analytics as _A
            _A.note_metric("search_ui_finalized")
            n += 1
            logger.info("RING_SEARCH_UI_FINALIZED uid=%s result=edited-later", uid)
        except Exception as e:
            logger.warning("RING_SEARCH_UI_RETRY_FAIL uid=%s err=%s", uid, str(e)[:140])
    return n


async def notify_match_started(session_id: str, *, cfg: dict | None = None,
                               reason: str = "match") -> dict:
    """§۱۱/§۲ — کارت مچ برای هر دو طرف، **با ثبتِ نتیجه در DB** (idempotent).

    تنها جایی است که کارت مچ ارسال می‌شود و از سه راه صدا زده می‌شود:
      • بی‌درنگ بعد از match (`finalize_match`)          ⇒ §۱۸
      • housekeeping برای ترمیم (`retry_pending_notify`) ⇒ §۱۹/§۳۱
      • `post_init` بعد از ری‌استارت                      ⇒ §۳۶
    `sessions.notify[uid].s` نشانهٔ «رسید» است؛ پس نه پیامی گم می‌شود و نه دو
    تا می‌رود، حتی اگر پروسه میانِ کار بمیرد (§۱۲/§۳۴: source of truth = DB).
    """
    from database import db
    from ring import notify, texts
    out = {"sent": [], "failed": [], "skipped": [], "session_id": session_id}
    from ring import notify as _N
    if _N._bot() is None:
        # §۳۲ (V6) — بدون بات، «تلاش» حساب نمی‌شود (وگرنه ۹۰ ثانیه بی‌باتی،
        # بودجهٔ ۳ تلاشِ backoff را صفر می‌کرد و اطلاعیه برای همیشه می‌مرد).
        out["skipped"].append("no-bot")
        logger.warning("RING_MATCH_NOTIFY_DEFERRED sid=%s reason=no-bot", session_id)
        return out
    sess = await db.ring_session(session_id)
    if not sess:
        out["skipped"].append("no-session")
        return out
    if cfg is None:
        cfg = await S.get_cfg()
    slots = _sess_uids(sess)
    nstate = sess.get("notify") or {}
    seqs = sess.get("notify_seq") or {}
    if sess.get("status") != "active" and reason == "retry":
        # §۳۱/§۳۶ (V6) — جبرانی برای گفت‌وگویی که تمام شده فرستاده نمی‌شود
        # (کارت مچ برای چتِ بسته، فقط گیج‌کننده است). UI/حباب در مسیرِ
        # `repair_search_ui` همچنان ترمیم می‌شود.
        out["skipped"].append("closed")
        return out
    for a in slots:
        st = nstate.get(str(a)) or {}
        if st.get("s"):
            out["skipped"].append(a)                       # قبلاً رسیده (§۱۲)
            continue
        if int(st.get("t") or 0) >= NOTIFY_MAX_TRIES and reason == "retry":
            out["skipped"].append(a)
            continue
        peers = [u for u in slots if u != int(a)]
        b = peers[0] if peers else None
        pb = await db.ring_profile(b) if b is not None else None
        card = texts.match_card(sess, pb or {}, cfg,
                                session_no=int(seqs.get(str(a)) or 1))
        from ring import keyboards as K
        try:
            kb = K.kb_chat(sess.get("mode") or "fun", cfg)
        except Exception as e:
            logger.warning("RING_KB_FAIL sid=%s err=%s", session_id, str(e)[:120])
            kb = None
        ok = await notify.send_text(a, card, parse_mode=_HTML(), reply_markup=kb)
        await db.ring_session_note_sent(session_id, a, sent=bool(ok),
                                        err=None if ok else "send-failed")
        from ring import analytics as _A
        _A.note_metric("notify_ok" if ok else "notify_fail")   # §۴۹ (V6)
        (out["sent"] if ok else out["failed"]).append(a)
        logger.info("RING_MATCH_NOTIFY uid=%s sid=%s result=%s reason=%s",
                    a, session_id, "sent" if ok else "failed", reason)
    if out["sent"] or out["failed"]:
        logger.info("RING_CHAT_READY sid=%s slots=%s notified=%s failed=%s",
                    session_id, slots, out["sent"], out["failed"])
    return out


async def finalize_match(session_id: str, *, cfg: dict | None = None,
                         ui_text: str | None = None) -> dict:
    """§۲۴ — ترتیبِ اجباری: DB → state → queue → timer → UI → notify.

    idempotent است، پس `jobs._sweep`، مسیرِ کاربر و روترِ ادمین همه همین یکی را
    صدا می‌زنند (§۴: «notification نباید منطقِ پراکنده داشته باشد»).
    """
    from database import db
    sess = await db.ring_session(session_id)
    if not sess:
        return {"ok": False, "why": "no-session"}
    if cfg is None:
        cfg = await S.get_cfg()
    slots = _sess_uids(sess)
    for u in slots:
        q = await db.ring_queue_get(u)
        if q and q.get("status") in ("waiting", "claiming"):
            await db.ring_queue_into_chat(u, session_id)
            logger.info("RING_QUEUE_REMOVED uid=%s sid=%s result=repaired",
                        u, session_id)
        logger.info("RING_TIMER_CANCELLED uid=%s sid=%s", u, session_id)
    txt = ui_text or "🎉 مچ شدی! کارت گفت‌وگو همین پایین آمده ✅"
    ui = {u: await finalize_search_ui(u, txt) for u in slots}
    res = await notify_match_started(session_id, cfg=cfg)
    res.update({"ok": True, "ui": ui, "slots": slots})
    return res


def _sess_uids(sess: dict) -> list[int]:
    """اسلات‌های یک جلسه، با fallback به `user_a`/`user_b`.

    لازم است چون `ring_session_end` عمداً `slots` را null می‌کند (تا unique
    indexِ «یک جلسهٔ فعال به‌ازای هر کاربر» آزاد شود) — و ادمین دقیقاً همان
    جلسه‌های تمام‌شده/گزارش‌شده را برای بازرسی باز می‌کند (§۴۶ V6). همان
    fallbackی که `db.ring_session_peer` دارد، این‌جا هم لازم بود.
    """
    out: list[int] = []
    for u in (sess.get("slots") or []):
        try:
            out.append(int(u))
        except Exception:
            continue
    if out:
        return out
    for k in ("user_a", "user_b"):
        try:
            if sess.get(k):
                out.append(int(sess[k]))
        except Exception:
            continue
    return out


async def session_health(session_id: str) -> dict:
    """§۴۶ — «این match کدام مرحله‌اش کامل نشد؟» (برای پنل و برای دیباگِ زنده).

    خروجی برای هر مرحله `dict[uid] = bool` است تا ادمین ببیند مشکل یک‌طرفه
    است یا دوطرفه (در V5 دقیقاً همین را نمی‌شد فهمید؛ فقط «چیزی کار نمی‌کند»
    دیده می‌شد). هیچ query سنگینی ندارد: پنج readِ کلیددار.
    """
    from database import db
    from ring import notify as _N
    out: dict = {"session_id": session_id, "found": False,
                 "steps": {"state": {}, "queue": {}, "timer": {},
                           "notify": {}, "relay": {}},
                 "needs_repair": False, "notify_health": _N.health()}
    sess = await db.ring_session(session_id)
    if not sess:
        out["error"] = "no-session"
        return out
    out["found"] = True
    out["status"] = sess.get("status")
    out["mode"] = sess.get("mode")
    out["created_at"] = sess.get("created_at")
    slots = _sess_uids(sess)
    out["slots"] = slots
    out["ended"] = sess.get("status") != "active"
    nstate = sess.get("notify") or {}
    al = sess.get("aliases") or {}
    for u in slots:
        p = await db.ring_profile(u) or {}
        out["steps"]["state"][u] = p.get("current_session") == session_id
        q = await db.ring_queue_get(u)
        # «درست» یعنی: ردیفی که او را دوباره match کند وجود ندارد
        out["steps"]["queue"][u] = not (q and q.get("status") in
                                       ("waiting", "claiming", "claimed"))
        out["steps"]["timer"][u] = not (p.get("search_msg") or {})
        out["steps"]["notify"][u] = bool((nstate.get(str(u)) or {}).get("s"))
        out["steps"]["relay"][u] = bool(al.get(str(u)))
    out["steps"]["notify_tries"] = {u: int((nstate.get(str(u)) or {}).get("t") or 0)
                                     for u in slots}
    out["needs_repair"] = any(any(not v for v in d.values())
                              for k, d in out["steps"].items()
                              if k != "notify_tries" and isinstance(d, dict))
    return out


async def repair_session(session_id: str) -> dict:
    """§۴۷ — ترمیمِ *محافظه‌کارانه* یک session.

    فقط همان کاری را می‌کند که باید شده باشد و نشده: state را ست می‌کند،
    ردیفِ جاماندهٔ صف را `in_chat` می‌کند، حبابِ یخ‌زده را نهایی می‌کند و
    کارتِ نرسیده را می‌فرستد (idempotent). هیچ session را نمی‌بندد، هیچ
    پیامِ کاربری را پاک نمی‌کند و چیزی را «از نو» match نمی‌کند.
    """
    from database import db
    sess = await db.ring_session(session_id)
    if not sess:
        return {"ok": False, "why": "no-session"}
    before = await session_health(session_id)
    did: dict = {"state": {}, "queue": {}, "timer": {}, "notify": None}
    for u, ok in (before["steps"]["state"] or {}).items():
        if ok:
            continue
        await db.ring_cols.profiles.update_one({"_id": int(u)},
                                               {"$set": {"current_session": session_id}})
        did["state"][int(u)] = True
        logger.warning("RING_REPAIR sid=%s step=state uid=%s", session_id, u)
    for u, ok in (before["steps"]["queue"] or {}).items():
        if ok:
            continue
        await db.ring_queue_into_chat(int(u), session_id)
        did["queue"][int(u)] = True
        logger.warning("RING_REPAIR sid=%s step=queue uid=%s", session_id, u)
    txt = "🎉 مچ شدی! کارت گفت‌وگو همین پایین آمده ✅"
    for u, ok in (before["steps"]["timer"] or {}).items():
        if ok:
            continue
        did["timer"][int(u)] = await finalize_search_ui(int(u), txt)
        logger.warning("RING_REPAIR sid=%s step=timer uid=%s result=%s",
                       session_id, u, did["timer"][int(u)])
    if any(not v for v in (before["steps"]["notify"] or {}).values()):
        did["notify"] = await notify_match_started(session_id)
    out = {"ok": True, "session_id": session_id, "repaired": did,
           "after": await session_health(session_id)}
    out["after"]["needs_repair"] = bool(out["after"]["needs_repair"])
    return out


async def boot_repair() -> dict:
    """§۳۶ — بلافاصله بعد از بالا آمدن: کارهای ناتمامِ چرخهٔ match را ببند.

    سه چیز، همه idempotent:
      ۱) `notify` — کارت‌هایی که نرسیده‌اند (از DB خوانده می‌شوند، نه RAM)
      ۲) `pend`  — پیام‌های جست‌وجویی که نهایی نشدند (حبابِ یخ‌زده)
      ۳) یتیم‌ها  — session/queue/timerِ ناسازگار (§۴۸)
    اگر رینگ خاموش باشد یا DB در دسترس نباشد، `{}` برمی‌گرداند و بوت را نمی‌شکند.
    """
    out: dict = {}
    try:
        from database import db  # noqa: F401  (نشان می‌دهد DB لازم است)
    except Exception as e:
        logger.warning("RING_BOOT_REPAIR skipped (db unavailable): %s", e)
        return {}
    for key, coro in (("notify", retry_pending_notify(limit=20)),
                      ("ui", repair_search_ui(limit=20)),
                      ("orphans", repair_orphans(limit=50))):
        try:
            r = await coro
            out[key] = r if isinstance(r, (int,)) else r
        except Exception as e:
            out[f"{key}_error"] = str(e)[:140]
            logger.warning("RING_BOOT_REPAIR %s failed err=%s", key, str(e)[:140])
    logger.info("RING_BOOT_REPAIR %s", out)
    return out


async def retry_pending_notify(limit: int = 20) -> dict:
    """§۳۱/§۳۲ — اطلاعیهٔ نرسیده را با backoff دوباره می‌فرستد (فقط fallback)."""
    from database import db
    cfg = await S.get_cfg()
    tried = 0
    for row in await db.ring_sessions_pending_notify(limit=limit):
        nstate = row.get("notify") or {}
        due = False
        for u in row.get("missing") or []:
            st = nstate.get(str(u)) or {}
            tries = int(st.get("t") or 0)
            if tries >= NOTIFY_MAX_TRIES:
                continue
            gap = NOTIFY_BACKOFF_S[min(tries, len(NOTIFY_BACKOFF_S) - 1)]
            if _ago_s(st.get("at")) >= gap:
                due = True
                break
        if not due:
            continue
        await notify_match_started(row["session_id"], cfg=cfg, reason="retry")
        tried += 1
    return {"retried": tried}


async def repair_orphans(*, limit: int = 50) -> dict:
    """§۴۸ — ناسازگاری‌ها را *محافظه‌کارانه* درست می‌کند (+شمارشِ متریک).

      • session فعال دارد ولی `current_session` ندارد → ست می‌شود
      • ردیف `waiting` دارد ولی session فعال دارد → از صف بیرون (یتیمِ صف)
      • `search_msg` دارد ولی ردیفِ زنده ندارد → تایمر خاموش (یتیمِ تایمر)

    هیچ session‌ای را نمی‌بندد و هیچ پیامِ کاربری را پاک نمی‌کند؛ فقط فلگ‌ها را
    هم‌راستا می‌کند و در `ring_admin_audit` می‌نویسد تا قابل بازرسی بماند.
    """
    from database import db
    rep = {"orphan_matches": 0, "queue_orphans": 0, "timer_orphans": 0}
    try:
        for sid, u in await db.ring_sessions_missing_current(limit=limit):
            await db.ring_cols.profiles.update_one(
                {"_id": int(u)}, {"$set": {"current_session": sid}})
            rep["orphan_matches"] += 1
            logger.warning("RING_ORPHAN_REPAIR type=match sid=%s uid=%s", sid, u)
    except Exception as e:
        logger.warning("RING_ORPHAN_REPAIR type=match skipped err=%s", str(e)[:140])
    try:
        for u in await db.ring_queue_orphans(limit=limit):
            if not await db.ring_session_active_for(u):
                continue
            await db.ring_queue_leave(u)
            rep["queue_orphans"] += 1
            logger.warning("RING_ORPHAN_REPAIR type=queue uid=%s", u)
    except Exception as e:
        logger.warning("RING_ORPHAN_REPAIR type=queue skipped err=%s", str(e)[:140])
    try:
        for u in await db.ring_search_msg_orphans(limit):
            q = await db.ring_queue_get(u)
            if q and q.get("status") in ("waiting", "claiming", "claimed"):
                continue
            # §۸ (V6) — «پاک‌کردنِ شناسه» کافی نیست: اگر آن پیام هنوز روی صفحه
            # باشد، کاربر تا ابد «🔎 در حال جست‌وجو…» می‌بیند. اول نهایی‌اش می‌کنیم
            # (متنِ واقعی از DB)، و فقط اگر ویرایش ممکن نبود شناسه را رها می‌کنیم.
            if await _finalize_dead(u, q):
                rep["healed"] = int(rep.get("healed") or 0) + 1
            else:
                await db.ring_search_msg_clear(u)
            rep["timer_orphans"] += 1
            logger.warning("RING_ORPHAN_REPAIR type=timer uid=%s", u)
    except Exception as e:
        logger.warning("RING_ORPHAN_REPAIR type=timer skipped err=%s", str(e)[:140])
    if any(rep.values()):
        from ring import analytics as _A
        for k, v in rep.items():
            _A.note_metric(k, int(v or 0))
    return rep



async def remember_search_msg(uid: int, chat_id: int, message_id: int,
                              *, waited_s: int = 0) -> None:
    """§۴ (V5) — «این همان پیامی است که تایمر رویش edit می‌شود».

    روی DB نوشته می‌شود تا ری‌استارتِ پروسه تایمر را نکُشد (§۳۵).
    """
    from database import db
    try:
        await db.ring_search_msg_set(uid, chat_id, message_id, waited_s)
    except Exception as e:
        logger.debug("[RING] search_msg set failed uid=%s: %s", uid, e)


async def forget_search_msg(uid: int, *, expired: bool = False) -> None:
    """تایمر را خاموش می‌کند (لغو/توقف/مچ/پایان وقت — همه از همین‌جا)."""
    from database import db
    try:
        await db.ring_search_msg_clear(
            uid, expired_at=utc_now_iso() if expired else None)
    except Exception as e:
        logger.debug("[RING] search_msg clear failed uid=%s: %s", uid, e)


async def _render_search_final(uid: int, cfg: dict, text: str,
                               sm: dict | None = None) -> str:
    """پیامِ پایانِ جست‌وجو — از همان `finalize_search_ui` (§۱۰/§۱۴ V6).

    V۵ برای این کار دو مسیرِ جدا داشت (edit اگر شد، وگر نه sendِ تازه) که در
    حالتِ «بات نبود» پیامِ دوم می‌ساخت و بعد هم شناسه را پاک می‌کرد ⇒ حبابِ
    یخ‌زده. حالا اگر edit ممکن نبود، متن در `pend` می‌ماند و دورِ بعد اعمال
    می‌شود؛ پیامِ تازه فقط وقتی می‌رود که هیچ شناسه‌ای در کار نباشد
    (کاربر پیامِ انتظار را پاک کرده) — و آن هم با لاگ اگر نرسید.
    """
    from database import db
    from ring import notify
    if sm is None:
        sm = (await db.ring_profile(uid) or {}).get("search_msg") or {}
    r = await finalize_search_ui(uid, text, kind="expired", cfg=cfg, sm=sm)
    if r == "none" and not (sm.get("m") and sm.get("c")):
        from ring import keyboards as K
        p = await db.ring_profile(uid) or {}
        kb = K.kb_expired(p.get("mode") or "fun", cfg or {})
        if not await notify.send_text(uid, text, parse_mode=_HTML(), reply_markup=kb):
            logger.warning("RING_SEARCH_EXPIRE_UNDELIVERED uid=%s "
                           "(نه پیامِ انتظار بود، نه ارسالِ تازه نشست)", uid)
    return r


async def expire_search(uid: int) -> bool:
    """§۳۶ — «سقفِ انتظار همین حالا رد شده» (از هر مسیری که کاربر بپرسد).

    `search_tick` این را برای صف صدا می‌زند؛ هندلر هم وقتی کاربر *همین لحظه*
    دکمه را می‌زند و ردیفش قدیمی‌تر از timeout است، همان راه را می‌رود، تا
    دو نسخهٔ متفاوت از «کسی پیدا نشد» در محصول نداشته باشیم.
    """
    from database import db
    q = await db.ring_queue_get(uid)
    if not q or q.get("status") not in ("waiting", "claiming"):
        return False
    cfg = await S.get_cfg()
    timeout = max(30, int(cfg.get("queue_timeout_s") or 600))
    if int(_waited_s(q)) < timeout:
        return False
    # §۵۳ (V6) — «انجام شد» فقط وقتی واقعاً انجام شده باشد: اگر `_expire_search`
    # به‌دلیلِ matchedشدن یا تغییرِ ردیف abort کرد، ما هم False می‌گوییم (قبلاً
    # همیشه True برمی‌گرداند و فراخوان — jobs/handlers — موفقیتِ ساختگی می‌دید).
    return await _expire_search(uid, q, await db.ring_profile(uid) or {}, cfg, timeout)


async def _expire_search(uid: int, q: dict, p: dict, cfg: dict,
                         timeout_s: int) -> bool:
    """§۲/§۱۲/§۳۶ (V5) — پایانِ سقف انتظار.

    تنها جایی که «کسی پیدا نشد» گفته می‌شود؛ تا پیش از آن پیام فقط
    «در حال جست‌وجو» است. اگر کاربر پیام را پاک کرده باشد، `notify` جانشین
    می‌شود (§۱۰) و صفِ او هم تمیز می‌شود.
    """
    from database import db
    from ring import texts
    # §۳۸ (V6) — اگر matcher همین لحظه session ساخته، انقضا بازمی‌گردد؛
    # ترکیبِ «A=EXPIRED و B=MATCHED» غیرممکن می‌شود.
    if await db.ring_session_active_for(uid):
        await db.ring_search_msg_clear(uid)
        logger.info("RING_SEARCH_EXPIRE_ABORTED uid=%s reason=matched", uid)
        return False
    waited = int(_waited_s(q))
    sm = dict(p.get("search_msg") or {})          # §۱۰ — اول کپی، بعد پاک‌کردن
    if not await db.ring_queue_leave_if(uid, ("waiting", "claiming")):
        logger.info("RING_SEARCH_EXPIRE_ABORTED uid=%s reason=row-changed", uid)
        return False
    await db.ring_search_msg_clear(uid, expired_at=utc_now_iso())
    text = texts.search_expired(q.get("mode") or p.get("mode") or "fun", cfg,
                                waited_s=waited, p=p)
    await _render_search_final(uid, cfg, text, sm)     # §۱۰ — با snapshot
    logger.info("RING_SEARCH_EXPIRED uid=%s waited_s=%s timeout_s=%s",
                uid, waited, timeout_s)
    return True


async def search_tick(*, limit: int = 200, edit_every_s: int = 10) -> dict:
    """§۴/§۵/§۱۲ (V5) — «تیک» تایمرِ انتظار؛ هر ~۱۰ ثانیه از scheduler صدا زده می‌شود.

    چرا شغل جدا و نه هندلر: کاربر باید *بدون کلیک* ببیند زمان دارد می‌گذرد و
    باید خودبه‌خود مچ یا منقضی شود. قوانین ایمنی:
      • فقط برای ردیفِ زندهٔ صف (waiting/claiming)؛ هر چیز دیگر ⇒ شناسهٔ پیام
        پاک می‌شود، پس یتیم‌ماندنِ تایمر غیرممکن است (§۱۲).
      • اگر session فعال باشد هرگز edit نمی‌کند (پیامِ چت به هم نمی‌ریزد).
      • برای هر کاربر حداکثر یک edit در هر پنجرهٔ زمانی (§۵) — نه یک پیام تازه.
      • هیچ match تازه‌ای اینجا نمی‌کند؛ جاروی صف (`_sweep`) این کار را می‌کند،
        پس hot pathِ رله و matcher ارزان می‌ماند (§۴۹).
      • مدتِ انتظار از `queued_at` خوانده می‌شود، نه شمارندهٔ RAM ⇒ بعد از
        ری‌استارت عدد از همان‌جا ادامه می‌یابد (§۳۴/§۶۴).
    """
    from database import db
    from ring import keyboards as K, notify, texts
    from telegram.constants import ParseMode
    from telegram.error import BadRequest
    stats = {"edited": 0, "expired": 0, "dropped": 0, "skipped": 0, "ui": 0}
    # §۱۴ — حباب‌های یخ‌زده (pend) اول از همه ترمیم می‌شوند؛ این راهِ برگشتِ
    # «۰۰:۰۰ برای همیشه» است، چون ممکن است در لحظهٔ match بات bind نشده باشد.
    try:
        stats["ui"] = await repair_search_ui(limit=max(1, min(20, int(limit))))
    except Exception as e:
        logger.warning("RING_SEARCH_UI_REPAIR_FAIL err=%s", str(e)[:140])
    bot = notify._bot()
    if bot is None:
        # §۵۸ — دیگر «خطای بی‌صدا» نیست: warningِ نرخ‌محدود در سطح INFO.
        _warn_no_bot_tick()
        return stats
    cfg = await S.get_cfg()
    timeout = max(30, int(cfg.get("queue_timeout_s") or 600))
    every = max(5, int(edit_every_s))
    uids = await db.ring_queue_searching_ids(limit)
    # هزینه (§۴۹): یک query دسته‌جمعی برای «کی داخل session است» + به‌ازای هر
    # کاربرِ منتظر دو query (ردیف صف و پروفایل). بررسی بن *این‌جا انجام نمی‌شود*:
    # کاربر بن‌شده مچ نمی‌شود (matcher چک می‌کند) و ردیفش را housekeeping
    # پاک می‌کند؛ هزینهٔ یک query اضافه به‌ازای هر کاربر در هر ۱۰ ثانیه
    # فقط برای «ویرایش پیامِ خودش» توجیه ندارد.
    in_sess = await db.ring_sessions_uids(uids)
    seen: set[int] = set()
    for uid in uids:
        seen.add(int(uid))
        try:
            q = await db.ring_queue_get(uid)
            if not q or q.get("status") not in ("waiting", "claiming"):
                # §۱۲/§۸ (V6) — در V۵ فقط شناسه پاک می‌شد؛ نتیجه: هر کاربری که
                # match شده بود ولی `finalize_match` به‌دلیل باگِ بات به پیامش
                # نرسیده بود، «🔎 در حال جست‌وجو…» یخ‌زده روی صفحه نگه می‌داشت.
                # حالا همین‌جا همان پیام با متنِ وضعیتِ *واقعی* نهایی می‌شود.
                if await _finalize_dead(uid, q):
                    stats["healed"] = stats.get("healed", 0) + 1
                else:
                    await db.ring_search_msg_clear(uid)
                stats["dropped"] += 1
                continue
            if int(uid) in in_sess:                      # داخل چت — دست نزن
                if await _finalize_dead(uid, q):
                    stats["healed"] = stats.get("healed", 0) + 1
                else:
                    await db.ring_search_msg_clear(uid)
                stats["dropped"] += 1
                continue
            waited = int(_waited_s(q))
            p = await db.ring_profile(uid) or {}
            if waited >= timeout:
                # §۳۸ — اگر انقضا به‌دلیل match برگشت، عددِ expired دروغ نمی‌گوید
                if await _expire_search(uid, q, p, cfg, timeout):
                    stats["expired"] += 1
                else:
                    stats["skipped"] += 1
                continue
            sm = p.get("search_msg") or {}
            if not sm.get("m") or not sm.get("c"):
                continue
            if waited - int(sm.get("s") or 0) < every:   # هنوز وقتِ edit نرسیده
                continue
            mode = p.get("mode") or q.get("mode") or "fun"
            n = await db.ring_queue_waiting_count(mode)
            text = texts.searching(mode, p, waited_s=waited,
                                   queue_n=max(0, int(n or 1) - 1),
                                   timeout_s=timeout)
            # §۲۱/§۲ (V6) — اول «مجوزِ ویرایش» را با CAS بگیر. اگر در فاصلهٔ
            # خواندن تا اینجا match/انقضا/لغو رخ داده باشد `rev` عوض شده و ما
            # edit **نمی‌زنیم**؛ وگرنه کارتِ مچ زیرِ «در حال جست‌وجو…» گم می‌شود.
            rev = int(sm.get("rev") or 1)
            if not await db.ring_search_msg_bump(uid, waited, expect_rev=rev):
                stats["skipped"] = stats.get("skipped", 0) + 1
                continue
            try:
                await bot.edit_message_text(chat_id=int(sm["c"]), message_id=int(sm["m"]),
                                            text=text, parse_mode=ParseMode.HTML,
                                            reply_markup=K.kb_searching())
                stats["edited"] += 1
                after = (await db.ring_profile(uid) or {}).get("search_msg") or {}
                if int(after.get("rev") or 0) != rev + 1:
                    await _heal_after_race(uid, int(sm["c"]), int(sm["m"]))
            except BadRequest as e:
                # پیام پاک یا غیرقابل‌ویرایش شده ⇒ تایمر باید با آن بمیرد (§۱۲)
                logger.debug("[RING] search tick edit rejected uid=%s: %s", uid, e)
                await db.ring_search_msg_clear(uid)
                stats["dropped"] += 1
        except Exception as e:
            logger.warning("[RING] search tick failed for uid=%s: %s", uid, e)
    # §۱۲ — یتیم‌ها: پروفایلی که هنوز `search_msg` دارد ولی ردیفِ «زنده» ندارد
    # (inside a chat, admin pulled it out, restore from backup, half-finished path)
    # (ادمین بیرونش کرد، restore از بکاپ، مسیرِ نصفه‌کاره). تایمر باید با
    # همان پیام بمیرد، وگرنه یک «۰۰:۰۰» بی‌صاحب روی صفحه می‌ماند.
    try:
        for uid in await db.ring_search_msg_orphans(limit):
            if int(uid) in seen:
                continue
            q2 = await db.ring_queue_get(uid)
            if q2 and q2.get("status") in ("waiting", "claiming", "claimed"):
                continue        # هنوز صاحبِ ردیفِ زنده است (یا مسابقه با join_queue)
            # §۸ (V6) — «پاک‌کردنِ شناسه» تنها کافی نبود: روی سرورِ زنده همین
            # مسیر باعث شد حبابِ «۰۰:۰۰» برای همیشه بماند (آدرسِ پیام رفت،
            # متنِ نهایی هیچ‌وقت ننشست). اول نهایی می‌کنیم، وگرنه پاک می‌کنیم.
            if await _finalize_dead(uid, q2):
                stats["healed"] = stats.get("healed", 0) + 1
            else:
                await db.ring_search_msg_clear(uid)
            stats["dropped"] += 1
    except Exception as e:
        logger.debug("[RING] orphan sweep skipped: %s", e)
    return stats


async def try_match(uid: int, *, announce: bool = False) -> Result:
    """مراحل معماری: claim خود · کاندید · سازگاری دوطرفه · claim اتمیک ·
    ساخت session · خروج هر دو از صف · اطلاع‌رسانی به هر دو.

    سه چیزی که این نسخه درست کرد (ریشهٔ باگ «دو نفر در صف، هیچ match»):
      1. «claiming» بودنِ طرف مقابل دیگر دلیل رد شدن نیست — دو کلیک هم‌زمان
         یکدیگر را می‌بینند (قبلاً هر دو `empty` می‌گرفتند).
      2. اگر matcherِ دیگری ما را بردارد، `empty` نمی‌گوییم؛ همان session را
         adopt می‌کنیم (`silent` ⇒ بدون کارت تکراری).
      3. اگر تنها سازگارهایِ صف «پارتنرهای اخیر» باشند، بعد از
         `rematch_after_s` صبر tier دوم اجرا می‌شود تا صف‌های کوچک گرسنه
         نمانند — ولی پارتنرِ گفت‌وگوی *همین لحظه* هرگز برنمی‌گردد.
    """
    from database import db
    from ring import analytics as _A
    _A.note_metric("match_attempts")            # §۴۹ (V6)
    token = new_token()
    me_q = await db.ring_queue_claim_self(uid, token)
    if not me_q:
        cur = await db.ring_queue_get(uid)
        if cur and cur.get("status") == "in_chat":
            return Result.of("in_chat", session_id=cur.get("session_id"))
        taken = await _adopt_existing(uid, token)
        if taken is not None:
            return taken
        cur2 = await db.ring_queue_get(uid)
        if cur2 and cur2.get("status") == "waiting":
            # رزروی که دیگری روی ما گرفته بود پس داده شد ⇒ ما دوباره آزادیم؛
            # صادقانه «هنوز کسی پیدا نشده» را می‌گوییم، نه «داری انتخاب می‌شی».
            md = cur2.get("mode") or "fun"
            return Result.of("waiting", mode=md,
                             queued=await db.ring_queue_waiting_count(md, [uid]),
                             waited_s=int(_waited_s(cur2)))
        return Result.of("busy")
    try:
        cfg = await S.get_cfg()
        if not await S.get_flag():
            await db.ring_queue_release_self(uid, token)
            return Result.of("disabled")
        if await S.maintenance():                   # §۴۵
            await db.ring_queue_release_self(uid, token)
            return Result.of("maintenance")
        me_p = await db.ring_profile(uid)
        if not me_p:
            await db.ring_queue_release_self(uid, token)
            return Result.of("no_profile")
        blocked = await db.ring_block_ids(uid)
        pairs = await recent_pairs(me_p, int(cfg["skip_cooldown_s"]))
        recent = [u for u, _ in pairs]
        mode = me_q.get("mode") or me_p.get("mode")
        r = await _search_pass(uid, token, me_q, me_p, mode, cfg,
                               blocked=blocked, exclude={uid, *blocked, *recent},
                               verify_recent=recent, announce=announce)
        if r.get("kind") != "empty":
            return r
        # ── tier 2: صف فقط از پارتنرهای اخیر پر است ⇒ بعد از صبر، آزادتر ──
        guard = max(60, int(cfg.get("rematch_after_s") or 90))
        waited = int(_waited_s(me_q))
        relaxed = False
        if recent and waited >= guard:
            very = {u for u, at in pairs if at >= now_utc() - timedelta(seconds=guard)}
            r2 = await _search_pass(uid, token, me_q, me_p, mode, cfg,
                                    blocked=blocked, exclude={uid, *blocked, *very},
                                    verify_recent=sorted(very), announce=announce)
            if r2.get("kind") != "empty":
                r2["relaxed"] = True
                await db.ring_bump(rematch=1)     # §۳۹ — چند مچ از پارتنرِ اخیر؟
                return r2
            relaxed = True
            r = r2
        # هیچ‌چیز نشد ⇒ خودمان را آزاد کن (فقط اگر کسی ما را نبرده باشد)
        released = await db.ring_queue_release_self(uid, token)
        # ★ قفل نهایی (invariant): اگر کاربر عملاً در session فعال است، هیچ
        # مسیری نباید «empty/busy» برگرداند — هر ترتیبی از claimها که پیش
        # آمده باشد، اینجا به همان match تبدیل می‌شود.
        if await db.ring_session_active_for(uid):
            taken = await _adopt_existing(uid, token)
            if taken is not None:
                return taken
        if not released:
            # رزروی که دیگری روی ما گرفته بود بی‌صدا رها شده (matcher آن دور
            # را با adopt/waiting تمام کرد). ما در `claimed` گیر می‌کردیم تا
            # repairِ ۱۵۰ ثانیه‌ای — پس خودمان برمی‌گردیم توی صف؛ اگر آن
            # matcher زنده باشد، into_chatِ خودش ما را دوباره می‌گیرد و
            # unique index جلوی session دوتایی را می‌گیرد.
            await db.ring_queue_release(uid)
            logger.info("[RING] self-heal uid=%s رزروی بی‌صاحب آزاد شد", uid)
        # ── settle: طرفِ مقابل چند میلی‌ثانیه *بعد از ما* join می‌کند ──
        # بدون این، جست‌وجوگرِ زودتر-تمام‌شده «کسی نیست» می‌گوید و بیست
        # میلی‌ثانیه بعد همان کاربر او را match می‌کند (پیام متناقض). دو چیز
        # را دنبال می‌کند: (۱) sessionِ من ساخته شد؟ ⇒ همان را adopt کن؛
        # (۲) کسی در صف ظاهر شد؟ ⇒ یک دورِ دیگر تلاش کن. سقف: ~۱.۲ ثانیه،
        # فقط در مسیرِ شکست؛ جاروی ۳۰ ثانیه‌ایِ job همچنان تورِ نهایی است.
        if r.get("kind") == "empty" and not r.get("relaxed"):
            for _ in range(5):
                await asyncio.sleep(0.25)
                won = await db.ring_session_active_for(uid)
                if won:
                    peer = await db.ring_session_peer(won, uid)
                    logger.info("RING_MATCH_SETTLED uid=%s sid=%s", uid, won["session_id"])
                    return Result.of("matched", session=won,
                                     peer=peer if peer is not None else -1,
                                     silent=True)
                me_now = await db.ring_queue_get(uid)
                if not me_now or me_now.get("status") != "waiting":
                    break                      # یا در چتیم (بالا چک شد) یا بیرون صفیم
                if not await db.ring_queue_waiting_count(mode, [uid]):
                    continue
                await db.ring_queue_claim_self(uid, token)
                r3 = await _search_pass(uid, token, me_q, me_p, mode, cfg,
                                        blocked=blocked,
                                        exclude={uid, *blocked, *recent},
                                        verify_recent=recent, announce=announce)
                await db.ring_queue_release_self(uid, token)
                if r3.get("kind") != "empty":
                    return r3
                r = r3
        if r.get("kind") == "empty" and not relaxed:
            # چرا خالی؟ «کسی در صف نیست» با «همه را اخیراً دیدی» فرق دارد
            fresh = await db.ring_queue_waiting_count(mode, sorted({uid, *blocked}))
            if recent and fresh:
                r["why"] = "recent_only"
        return r
    except Exception as e:
        logger.exception("ring.try_match failed")
        try:
            await db.ring_queue_release_self(uid, token)
        except Exception as e2:
            # §۴۵/§۱۵ (V6) — اگر آزادکردنِ claim هم شکست، رزروی روی کاربر
            # می‌ماند تا `repair_claims` (۱۵۰ ثانیه) پس بدهد؛ این باید در لاگ
            # باشد، وگرنه «چرا این کاربر دیگر مچ نمی‌شود» بی‌جواب می‌ماند.
            logger.warning("RING_RELEASE_AFTER_ERROR_FAILED uid=%s err=%s",
                           uid, str(e2)[:140])
        return Result.of("error", error=str(e)[:120])


def _waited_s(queue_doc: dict | None) -> float:
    """چقدر این کاربر در صف بود (برای avg_wait در آمار §۳۶)."""
    try:
        t = now_utc().fromisoformat(str((queue_doc or {}).get("queued_at")))
        if t.tzinfo is None:
            t = t.replace(tzinfo=now_utc().tzinfo)
        return max(0.0, (now_utc() - t).total_seconds())
    except Exception:
        return 0.0


def _first_range(pref) -> str | None:
    """برای اینکه فیلتر سن در خودِ query اعمال شود، اگر کاربر دقیقاً یک
    حلقه انتخاب کرده همان را می‌فرستیم؛ چندحلقه‌ای در `hard_ok` چک می‌شود."""
    if not pref or pref == "any":
        return None
    parts = [p.strip() for p in str(pref).split(",") if p.strip() in M.AGE_INDEX]
    return parts[0] if len(parts) == 1 else None


async def _verdict(uid: int, cid: int, cand: dict, mode: str, cfg: dict,
                   blocked: list[int], recent: list[int],
                   me: dict | None = None) -> dict:
    """دکمه‌ی واقعیِ «چرا نشد» — همه‌ی چک‌های بعد از رزرو، در یک dict (§۳۶).

    هم مسیرِ داغِ مچ و هم endpoint عیب‌یابی پنل همین را صدا می‌زنند، پس هیچ‌وقت
    «تصمیم» و «توضیحِ تصمیم» از هم جدا نمی‌شوند. `me` همان سندِ من است که در
    حلقه‌ی داغ از قبل خوانده شده (برای پرهیز از دو query اضافه به‌ازای هر کاندید).
    """
    from database import db
    me_doc = me if me is not None else {
        **(await db.ring_queue_get(uid) or {}),
        **(await db.ring_profile(uid) or {}), "user_id": uid}
    cp = await db.ring_profile(cid)
    cand_q = await db.ring_queue_get(cid)
    cand_sess = await db.ring_session_active_for(cid)
    block_hit = bool(await db.ring_blocked_between(uid, cid)) or cid in blocked
    # کول‌داونِ rematch دوطرفه است: اگر او من را دیروز دیده، pair تکراری نشدنی‌ست
    # `recent` خالی = caller چکِ کول‌داون را خاموش کرده (tier دوم دقیقاً برای
    # همان ساخته شده که پارتنرِ اخیر دوباره کاندید باشد) ⇒ چک دوطرفه هم خاموش.
    peers_of_cand: set[int] = set()
    if recent:
        cool = int(cfg.get("skip_cooldown_s") or 0)
        peers_of_cand = {u for u, _at in await recent_pairs(cp or {}, cool)}
    v = matcher.verdict(
        {**me_doc, "user_id": uid},
        {**cand, **{k: (cp or {}).get(k) for k in
                    ("bio", "interests", "city", "university", "major", "topics")},
         "user_id": cid},
        mode=mode, cfg=cfg,
        blocked=block_hit, recent=cid in recent or uid in peers_of_cand,
        my_session=bool(await db.ring_session_active_for(uid)),
        cand_session=bool(cand_sess),
        cand_available=bool(cp) and (cp or {}).get("status") not in ("banned", "paused")
                         and not await db.ring_ban_active(cid),
        # ⚠️ کاندید همین لحظه قفلِ ماست ⇒ ردیفش claimed است؛ تنها حالتی
        # که واقعاً مانع است in_chat بودنِ اوست (وگرنه هر مچی رد می‌شد!)
        queue_ok=bool(cand_q) and cand_q.get("status") != "in_chat",
        mode_enabled=await S.mode_enabled(mode))
    return v


async def _open_session(uid: int, cid: int, me_p: dict, mode: str, cfg: dict) -> dict | None:
    """ساخت جلسه + عبورِ هر دو کاربر به in_chat. None ⇒ race باخخته."""
    from database import db
    from ring import state
    cp = await db.ring_profile(cid)
    sid = f"RS{now_utc().strftime('%y%m%d')}{secrets.token_hex(4).upper()}"
    alias = f"ناشناس #{(cp or {}).get('anon_id', '#0000').lstrip('#')}"
    my_alias = f"ناشناس #{(me_p or {}).get('anon_id', '#0000').lstrip('#')}"
    sess = {
        "session_id": sid, "mode": mode, "status": "active",
        "slots": [int(uid), int(cid)],
        "user_a": int(uid), "user_b": int(cid),
        "alias_a": my_alias, "alias_b": alias,
        "created_at": utc_now_iso(), "last_activity_at": utc_now_iso(),
        "messages_count": 0, "media_count": 0,
        "safety_shown": False, "reveal": {"a": None, "b": None},
        "evidence_seq": 0,
    }
    got = await db.ring_session_create(sess)
    if not got:
        return None
    for u, al in ((uid, my_alias), (cid, alias)):
        # §۵/§۰ (V6) — state و شمارشِ جلسه همین‌جا نوشته می‌شوند، *پیش از* هر
        # تماسِ تلگرامی. اگر لایهٔ ارسال بچکد (بات bind نشده، کاربر بلاک کرده،
        # ۴۲۹)، DB همچنان می‌گوید «این دو در یک چت‌اند» و job ترمیم می‌کند:
        # شکستِ notification ≠ شکستِ match.
        await db.ring_queue_into_chat(u, sid)
        await db.ring_cols.profiles.update_one(
            {"_id": u}, {"$inc": {"sessions_count": 1},
                         "$set": {"current_session": sid}})
        # §۷ (V6) — تایمر اینجا *پاک نمی‌شود*: شناسهٔ پیامِ انتظار لازم است تا
        # `finalize_match` همان پیام را به «🎉 مچ شدی» تبدیل کند. ردیفِ صف
        # `in_chat` شده، پس `search_tick` دیگر سراغش نمی‌آید؛ پاک‌کردن در
        # `finalize_search_ui` انجام می‌شود (و اگر نشد، گامِ ترمیم/pend).
        logger.info("RING_TIMER_STOP_REQUESTED uid=%s sid=%s", u, sid)
        logger.info("RING_STATE_TRANSITION uid=%s from=searching to=chatting sid=%s",
                    u, sid)
        logger.info("RING_QUEUE_REMOVED uid=%s sid=%s", u, sid)
        logger.info("RING_TIMER_CANCELLED uid=%s sid=%s", u, sid)
    seqs: dict = {}
    for u in (uid, cid):
        d = await db.ring_cols.profiles.find_one({"_id": int(u)}, {"sessions_count": 1})
        seqs[str(u)] = int((d or {}).get("sessions_count") or 1)
    await db.ring_cols.sessions.update_one(
        {"session_id": sid},
        {"$set": {"aliases": {str(uid): my_alias, str(cid): alias},
                  "notify_seq": seqs}})
    state.attach(uid, cid, sid, mode, my_alias, alias)
    from ring import analytics as _A
    _A.note_metric("state_transition", 2)            # §۴۹ (V6) — در RAM، نه DB
    _A.note_metric("queue_removed", 2)
    _A.note_metric("timer_cancelled", 2)
    await db.ring_bump(session=1)
    logger.info("RING_SESSION_STARTED sid=%s mode=%s slots=%s", sid, mode, [uid, cid])
    return await db.ring_session(sid) or sess


# ══════════════════════════════════════════════════════════════
#  پایان گفت‌وگو
# ══════════════════════════════════════════════════════════════

async def end_session(uid: int | None, session_id: str, reason: str, *,
                      notify_peer: str | None = None, requeue_uids: tuple = ()) -> dict | None:
    """خاتمه‌ی جلسه + آزادسازی هر دو طرف. idempotent: اگر جلسه بسته شده
    باشد، None برمی‌گردد و پیامی ارسال نمی‌شود (§۶۲)."""
    from database import db
    from ring import state
    sess = await db.ring_session_end(session_id, reason, uid)
    if not sess:
        return None
    uids = [int(u) for u in (sess.get("slots") or [])]
    for u in uids:
        state.detach(u)
        await db.ring_cols.profiles.update_one({"_id": u}, {"$set": {"current_session": None}})
        await db.ring_queue_leave(u)
    for u in requeue_uids:
        if int(u) in uids:
            await db.ring_queue_requeue(int(u))
    peer = None
    if uid is not None:
        peer = next((u for u in uids if u != int(uid)), None)
    if peer and notify_peer:
        from ring import notify
        await notify.send_text(peer, notify_peer)
    dur = 0
    try:
        dur = int((now_utc() - now_utc().fromisoformat(sess["created_at"])).total_seconds())
    except Exception as e:
        logger.debug("[RING] مدتِ جلسه خوانده نشد sid=%s: %s",
                     sess.get("session_id"), e)   # §۱۵ — بی‌صدا نبودن
    await db.ring_bump(session_end=1, session_seconds=dur)
    logger.info("RING_SESSION_ENDED sid=%s reason=%s", session_id, reason)
    return {"session": sess, "uids": uids, "peer": peer}


async def stop(uid: int, session_id: str) -> Result:
    from ring import texts
    r = await end_session(uid, session_id, "user_stop")
    if not r:
        return Result.of("already_ended")
    if r.get("peer"):
        from ring import notify
        await notify.send_text(r["peer"], texts.peer_ended())
    return Result.of("ok", peer=r.get("peer"))


async def next_partner(uid: int, session_id: str) -> Result:
    from ring import texts
    from database import db
    sess = await db.ring_session(session_id)
    peer = None
    if sess:
        peer = await db.ring_session_peer(sess, uid)
    r = await end_session(uid, session_id, "user_next", requeue_uids=(uid,))
    if r and peer:
        from ring import notify
        await notify.send_text(peer, texts.peer_next())
    out = await search(uid)
    return Result.of("ok", next=out)


async def recent_pairs(profile: dict, cooldown_s: int) -> list[tuple[int, object]]:
    """`(uid, لحظه‌ی پایان دیدار)` برای پارتنرهای داخل cooldown."""
    out: list[tuple[int, object]] = []
    if not cooldown_s:
        return out
    cutoff = now_utc() - timedelta(seconds=cooldown_s)
    for row in (profile or {}).get("recent_partners") or []:
        try:
            at = now_utc().fromisoformat(str(row.get("at")))
            if at.tzinfo is None:
                at = at.replace(tzinfo=now_utc().tzinfo)
            if at >= cutoff:
                out.append((int(row["uid"]), at))
        except Exception:
            continue
    return out


async def recent_partners(profile: dict, cooldown_s: int) -> list[int]:
    """فقط uidهایی کهCooldown روی آن‌ها منقضی نشده (§۱۷ مرحله ۹)."""
    if not cooldown_s:
        return []
    out = []
    cutoff = now_utc() - timedelta(seconds=cooldown_s)
    for row in (profile or {}).get("recent_partners") or []:
        try:
            at = now_utc().fromisoformat(str(row.get("at")))
            if at.tzinfo is None:
                at = at.replace(tzinfo=now_utc().tzinfo)
            if at >= cutoff:
                out.append(int(row["uid"]))
        except Exception:
            continue
    return out


# ══════════════════════════════════════════════════════════════
#  کنترل‌های کاربر / ادمین
# ══════════════════════════════════════════════════════════════

async def set_paused(uid: int, paused: bool) -> Result:
    from database import db
    await db.ring_profile_status(uid, "paused" if paused else "active")
    if paused:
        await db.ring_queue_leave(uid)
        sess = await db.ring_session_active_for(uid)
        if sess:
            await end_session(None, sess["session_id"], "paused_by_user")
    return Result.of("ok")


async def delete_all(uid: int) -> Result:
    from database import db
    from ring import state
    sess = await db.ring_session_active_for(uid)
    if sess:
        await end_session(None, sess["session_id"], "profile_deleted")
    state.detach(uid)
    await db.ring_profile_delete(uid)
    return Result.of("ok")


async def admin_force_match(admin_id: int, a: int, b: int) -> Result:
    """match دستی — همان چک‌های ایمنی، فقط بدون نیاز به صف (§۶۷)."""
    from database import db
    from ring import state
    cfg = await S.get_cfg()
    if await db.ring_blocked_between(a, b):
        return Result.of("blocked")
    for u in (a, b):
        if await db.ring_ban_active(u):
            return Result.of("banned", uid=u)
        if await db.ring_session_active_for(u):
            return Result.of("in_chat", uid=u)
        p = await db.ring_profile(u)
        if not p or not M.age_ok(p.get("age"), int(cfg.get("min_age", 18))):
            return Result.of("no_profile", uid=u)
    pa, pb = await db.ring_profile(a), await db.ring_profile(b)
    mode = pa.get("mode") or "fun"
    sess = await _open_session(a, b, pa, mode, cfg)
    if not sess:
        return Result.of("race")
    await db.ring_audit(admin_id, "FORCE_MATCH", f"{a},{b}", mode, {"session": sess["session_id"]})
    from ring import texts
    from ring import notify
    await notify.send_text(a, texts.match_card(sess, pb, cfg))
    await notify.send_text(b, texts.match_card(sess, pa, cfg))
    return Result.of("ok", session=sess["session_id"])


async def admin_force_end(admin_id: int, session_id: str, reason: str) -> Result:
    from database import db
    from ring import texts
    from ring import notify
    sess = await db.ring_session(session_id)
    if not sess:
        return Result.of("not_found")
    r = await end_session(None, session_id, f"admin:{reason[:40]}")
    for u in (sess.get("slots") or []):
        await notify.send_text(int(u), texts.admin_ended())
    await db.ring_audit(admin_id, "FORCE_END_SESSION", session_id, reason, {})
    return Result.of("ok")


async def admin_remove_from_queue(admin_id: int, uid: int) -> Result:
    from database import db
    await db.ring_queue_leave(uid)
    await db.ring_audit(admin_id, "REMOVE_FROM_QUEUE", str(uid), "", {})
    return Result.of("ok")


# ══════════════════════════════════════════════════════════════
#  reveal دوطرفه (§۲۷) — nice-to-have، ولی در DB و با consent نگه داشته می‌شود
# ══════════════════════════════════════════════════════════════

async def reveal_request(uid: int) -> Result:
    from database import db
    from ring import texts
    cfg = await S.get_cfg()
    if not cfg.get("allow_reveal"):
        return Result.of("off")
    sess = await db.ring_session_active_for(uid)
    if not sess:
        return Result.of("no_session")
    if (sess.get("mode") or "fun") != "serious":
        return Result.of("serious_only")
    peer = await db.ring_session_peer(sess, uid)
    rev = dict(sess.get("reveal") or {})
    rev[str(uid)] = "requested"
    await db.ring_session_note(sess["session_id"], {"reveal": rev})
    from ring import notify
    await notify.send_text(peer, texts.reveal_ask())
    return Result.of("ok", peer=peer)


async def reveal_answer(uid: int, accept: bool) -> Result:
    from database import db
    sess = await db.ring_session_active_for(uid)
    if not sess:
        return Result.of("no_session")
    peer = await db.ring_session_peer(sess, uid)
    rev = dict(sess.get("reveal") or {})
    rev[str(uid)] = "yes" if accept else "no"
    await db.ring_session_note(sess["session_id"], {"reveal": rev})
    if rev.get(str(peer)) == "yes" and rev.get(str(uid)) == "yes":
        pa, pb = await db.ring_profile(peer), await db.ring_profile(uid)
        from ring import texts
        from ring import notify
        await notify.send_text(uid, texts.reveal_shared(pa))
        await notify.send_text(peer, texts.reveal_shared(pb))
        await db.ring_bump(reveal=1)
        return Result.of("both_yes", peer=peer)
    from ring import notify
    if not accept:
        await notify.send_text(peer, "🙏 درخواست معرفی رد شد. ناشناس می‌مانید.")
    else:
        await notify.send_text(peer, "✅ طرف مقابل هم موافقت کرد.")
    return Result.of("ok", peer=peer)
