"""💍 Ring Street — تحلیل (§۳۶): funnel، کیفیت تطبیق، moderation

فقط aggregateهای محدود با index و `allowDiskUse=False` — هیچ‌وقت روی کل
کاربران ربات اسکن نمی‌کنیم (§۵۳). آمار روزانه از `ring_stats_daily`
(شمارنده‌های atomic) می‌آید که تقریباً رایگان است؛ aggregateهای سنگین
فقط از پنل/درخواست خاص اجرا می‌شوند.
"""
from __future__ import annotations

from time_utils import utc_now_iso   # §۴۹ (V6) — cycle_metrics به همین نیاز دارد

import logging
from datetime import timedelta

from time_utils import now_utc

logger = logging.getLogger(__name__)


def _since(days: int):
    return (now_utc() - timedelta(days=max(1, min(int(days or 7), 180)))).replace(
        microsecond=0).isoformat(timespec="seconds")


# نام شمارنده‌ها در `ring_stats_daily.c.*` — حتماً با bumpهای ماژول‌ها یکی باشد
COUNTERS = {
    "profiles": "profiles", "consents": "consents", "joins": "queue_join",
    "matches": "match", "ends": "session_end", "messages": "messages",
    "reports": "report", "blocks": "blocks", "rated": "rating",
    "wait_s": "wait_s", "session_s": "session_seconds", "bans": "bans",
    "rematch": "rematch", "max_wait_s": "max_wait_s",
}


async def funnel(days: int = 7) -> dict:
    """profile → consent → queue join → match → ≥1 message → end."""
    from database import db
    rows = await db.ring_daily(days)
    acc = {k: 0 for k in COUNTERS}
    for r in rows:
        c = r.get("c") or {}
        for out_key, db_key in COUNTERS.items():
            acc[out_key] += int(c.get(db_key) or 0)
    n = max(1, acc["joins"])
    return {
        "days": days,
        **acc,
        "match_rate": round(acc["matches"] / n, 3),
        "avg_wait_s": round(acc["wait_s"] / n, 1),
        "avg_session_s": round(acc["session_s"] / max(1, acc["ends"]), 1),
        "msgs_per_match": round(acc["messages"] / max(1, acc["matches"]), 1),
        "report_per_match": round(acc["reports"] / max(1, acc["matches"]), 3),
    }


async def mode_split(days: int = 7) -> dict:
    """تقسیم fun/serious از روی sessionها (نه شمارنده‌ها) — aggregate محدود."""
    from database import db
    cut = _since(days)
    out = {}
    pipeline = [
        {"$match": {"created_at": {"$gte": cut}}},
        {"$group": {"_id": "$mode",
                    "n": {"$sum": 1},
                    "msgs": {"$sum": "$messages_count"},
                    "dur_ms": {"$sum": {
                        "$cond": [
                            {"$and": [{"$ne": ["$ended_at", None]},
                                     {"$gt": ["$messages_count", 0]}]},
                            {"$subtract": [
                                {"$dateFromString": {"dateString": "$ended_at"}},
                                {"$dateFromString": {"dateString": "$created_at"}}]},
                            0]}}}},
        {"$limit": 10},
    ]
    try:
        async for d in db.ring_cols.sessions.aggregate(pipeline, allowDiskUse=False):
            n = max(1, int(d.get("n") or 0))
            out[d["_id"] or "unknown"] = {
                "sessions": int(d.get("n") or 0),
                "messages": int(d.get("msgs") or 0),
                "avg_duration_s": round((d.get("dur_ms") or 0) / 1000 / n, 1),
            }
    except Exception as e:
        logger.debug("ring mode_split failed: %s", e)
    return out


async def moderation_stats(days: int = 30) -> dict:
    """چند گزارش تا بن، چند تای رد شده (برای تنظیم آستانه‌ها)."""
    from database import db
    cut = _since(days)
    out = {"by_reason": {}, "by_status": {}, "dup_share": 0.0, "total": 0}
    pipeline = [{"$match": {"created_at": {"$gte": cut}}},
                {"$group": {"_id": "$reason", "n": {"$sum": 1},
                            "dup": {"$sum": {"$cond": [{"$gt": [{"$size": {"$ifNull": ["$duplicate_of", []]}}, 0]}, 1, 0]}},
                            "sev": {"$sum": "$severity"}}}]
    total = dup = 0
    try:
        async for d in db.ring_cols.reports.aggregate(pipeline, allowDiskUse=False):
            out["by_reason"][d["_id"] or "other"] = {"n": d["n"], "severity_sum": d.get("sev", 0)}
            total += d["n"]
            dup += int(d.get("dup") or 0)
        async for d in db.ring_cols.reports.aggregate(
                [{"$match": {"created_at": {"$gte": cut}}},
                 {"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
            out["by_status"][d["_id"] or "pending"] = d["n"]
        bans = await db.ring_cols.bans.count_documents({"created_at": {"$gte": cut}})
        out["bans"] = bans
        out["total"] = total
        out["dup_share"] = round(dup / total, 3) if total else 0.0
        out["reports_per_ban"] = round(total / bans, 1) if bans else None
    except Exception as e:
        logger.debug("ring moderation_stats failed: %s", e)
    return out


async def top_topics(days: int = 30, limit: int = 8) -> list[dict]:
    from database import db
    cut = _since(days)
    try:
        rows = []
        async for d in db.ring_cols.profiles.aggregate(
                [{"$match": {"consent_terms_at": {"$gte": cut}}},
                 {"$unwind": "$topics"},
                 {"$group": {"_id": "$topics", "n": {"$sum": 1}}},
                 {"$sort": {"n": -1}}, {"$limit": max(1, min(limit, 30))}],
                allowDiskUse=False):
            rows.append({"topic": d["_id"], "users": d["n"]})
        return rows
    except Exception as e:
        logger.debug("ring top_topics failed: %s", e)
        return []


# §۳۹ (V4) — «چرا مچ نشد؟» باید اندازه‌گیری شود، نه فقط در لاگ دیده شود.
# شمارش در RAM نگه داشته می‌شود (هر رد = یک $inc اضافه در مسیر داغ نزنیم) و
# در همان job دوره‌ای که صف را جارو می‌کند روی دیسک می‌نشیند.
_rejects: dict[str, int] = {}


# §۴۹ (V6) — شمارنده‌های *چرخهٔ* مچ، نه فقط دلایل رد. همان الگوی `note_reject`:
# در RAM جمع می‌شوند و یک‌بار در هر دورِ housekeeping روی دیسک می‌نشینند، پس
# hot path (کلیکِ «جست‌وجو») با هر attempt دو $inc به DB نمی‌زند.
_metrics: dict[str, int] = {}


def note_metric(key: str, n: int = 1) -> None:
    """شمارندهٔ چرخه (match_attempts, candidate_found, notify_fail, …)."""
    if not key:
        return
    _metrics[key] = _metrics.get(key, 0) + int(n or 0)


async def flush_metrics() -> int:
    """`_metrics` را در `ring_stats_daily.c.*` می‌نویسد (§۴۹)."""
    if not _metrics:
        return 0
    snap = dict(_metrics)
    _metrics.clear()
    from database import db
    try:
        await db.ring_bump(**snap)
    except Exception as e:
        logger.warning("ring metric flush failed: %s", e)
        return 0
    return sum(snap.values())


CYCLE_KEYS = ("match_attempts", "candidate_found", "candidate_rejected",
              "match_created", "notify_ok", "notify_fail", "search_ui_finalized",
              "state_transition", "queue_removed", "timer_cancelled",
              "orphan_matches", "queue_orphans", "timer_orphans", "stuck_searches")


async def cycle_metrics(days: int = 7) -> dict:
    """جمعِ روزانهٔ شمارنده‌های چرخه + یتیم‌های *همین لحظه* (§۴۹/§۴۶).

    یتیم‌ها از `ring_overview` خوانده می‌شوند (وضعیتِ زنده)، نه از آمارِ روزانه:
    ادمین باید ببیند «الان» چیزی خراب است یا نه.
    """
    from database import db
    out = {k: 0 for k in CYCLE_KEYS}
    try:
        for r in await db.ring_daily(days):
            for k, v in (r.get("c") or {}).items():
                if k in out:
                    out[k] += int(v or 0)
    except Exception as e:
        logger.warning("ring cycle metrics read failed: %s", e)
    out["window_days"] = int(days)
    out["generated_at"] = utc_now_iso()
    try:
        ov = await db.ring_overview()
        for k in ("orphan_matches", "queue_orphans", "timer_orphans",
                  "pending_notify", "pending_ui", "notify_health", "errors"):
            if k in ov:
                out[k] = ov[k]
        out["stuck_searches"] = int(out.get("pending_notify") or 0) + \
            int(out.get("pending_ui") or 0)
    except Exception as e:
        out["live_error"] = str(e)[:160]
    return out


def note_reject(reason: str) -> None:
    """از حلقهٔ مچ صدا زده می‌شود؛ async نیست و نباید منتظر DB بماند."""
    if not reason:
        return
    _rejects[reason] = _rejects.get(reason, 0) + 1


async def flush_rejects() -> int:
    """شمارنده‌های RAM را در `ring_stats_daily.c.reject_*` می‌نویسد.

    §۴۹ (V6) — همین‌جا `flush_metrics()` هم صدا زده می‌شود: همان jobِ ۳۰ ثانیه‌ای
    هر دو دسته را می‌شوید و لازم نیست شغلِ تازه‌ای به bot.py اضافه شود.
    """
    await flush_metrics()
    if not _rejects:
        return 0
    snap = dict(_rejects)
    _rejects.clear()
    from database import db
    try:
        await db.ring_bump(**{f"reject_{k}": v for k, v in snap.items()})
    except Exception as e:
        logger.debug("ring reject counters flush failed: %s", e)
    return sum(snap.values())


async def reject_reasons(days: int = 7) -> dict:
    """تفکیک دلایل رد — برای کارت «چرا مچ نمی‌شوند؟» در پنل (§۳۹)."""
    from database import db
    out: dict[str, int] = {}
    try:
        for r in await db.ring_daily(days):
            for k, v in (r.get("c") or {}).items():
                if k.startswith("reject_"):
                    out[k[len("reject_"):]] = out.get(k[len("reject_"):], 0) + int(v or 0)
    except Exception as e:
        logger.debug("ring reject counters read failed: %s", e)
    for k, v in _rejects.items():                       # آنچه هنوز تخلیه نشده
        out[k] = out.get(k, 0) + int(v)
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


async def summary(days: int = 7) -> dict:
    """پاسخ `/api/ring/analytics` و کارت «📊» پنل."""
    from database import db
    ov = {}
    try:
        ov = await db.ring_overview()
    except Exception as e:
        logger.debug("ring overview failed: %s", e)
    fun = await funnel(days)
    fun["max_wait_s"] = int(await _max_wait(days))
    return {"funnel": fun, "modes": await mode_split(days),
            "moderation": await moderation_stats(days), "topics": await top_topics(days),
            "reject_reasons": await reject_reasons(days),
            "paused": await _paused_count(),
            "live": ov}


async def _max_wait(days: int = 7) -> int:
    """بیشترین انتظار ثبت‌شده (§۳۹) — از شمارندهٔ `$max` روزانه."""
    from database import db
    best = 0
    try:
        for r in await db.ring_daily(days):
            best = max(best, int((r.get("c") or {}).get("max_wait_s") or 0))
    except Exception as e:
        logger.debug("max_wait read failed: %s", e)     # §۱۵ (V6) — بی‌صدا نه
    return best


async def _paused_count() -> int:
    """چند نفر «⏸ توقف جست‌وجو» زده‌اند (§۲۳/§۳۹)."""
    from database import db
    try:
        return await db.ring_cols.profiles.count_documents(
            {"search_paused": True, "status": "active"}, limit=5000)
    except Exception:
        return 0
