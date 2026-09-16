"""💍 Ring Street — گزارش، بلاک، بن و حسابرسی (§۱۹..§۲۵، §۳۶، §۳۷، §۵۸)

اصل: **گزارش ≠ بن**. گزارش فقط وارد صف moderation می‌شود و امتیاز
severity روی پروفایل می‌نشیند؛ اقدام خودکار فقط وقتی رخ می‌دهد که
آستانه‌ها رد شوند و همیشه با قابلیت بازگشت ادمین (§۲۳).

بلاک دوطرفه ذخیره می‌شود تا matcher با یک lookup ساده بتواند رد کند.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from ring import models as M
from ring import notify
from ring import settings as S
from ring import state
from time_utils import now_utc, utc_now_iso

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
#  بلاک
# ══════════════════════════════════════════════════════════════

async def block(uid: int, session_id: str, reason: str = "") -> dict:
    """بلاکِ پارتنرِ فعلی. اگر session باز باشد بسته می‌شود (§۱۹)."""
    from database import db
    sess = await db.ring_session(session_id) if session_id else None
    peer = await db.ring_session_peer(sess, uid) if sess else None
    if peer is None:
        return {"ok": False, "why": "no_session"}
    await db.ring_block(uid, peer, reason)
    from ring import service
    if sess and sess.get("status") == "active":
        await service.end_session(uid, session_id, "blocked",
                                  requeue_uids=())        # بلاک‌شده دوباره در صف من نمی‌آید
    await db.ring_audit("user", "BLOCK_CREATED", f"{uid}->{peer}", reason[:120], {})
    await db.ring_bump(blocks=1)
    logger.info("RING_BLOCK_CREATED uid=%s blocked=%s", uid, peer)
    await notify.send_text(peer, "🚫 طرف مقابل شما را بلاک کرد و گفت‌وگو بسته شد.")
    return {"ok": True, "peer": peer}


async def block_explicit(uid: int, anon_id: str) -> dict:
    """بلاک از «🛡 امنیت» با ناشناس‌آی‌دی (بدون چت فعال)."""
    from database import db
    p = await db.ring_profile_by_anon(anon_id.strip() if anon_id else "")
    if not p:
        return {"ok": False, "why": "not_found"}
    if int(p["_id"]) == int(uid):
        return {"ok": False, "why": "self"}
    await db.ring_block(uid, int(p["_id"]), "manual")
    return {"ok": True, "anon": p.get("anon_id")}


async def unblock(uid: int, other: int) -> dict:
    from database import db
    await db.ring_unblock(uid, other)
    return {"ok": True}


# ══════════════════════════════════════════════════════════════
#  گزارش
# ══════════════════════════════════════════════════════════════

async def report(uid: int, session_id: str | None, reason_key: str,
                 details: str = "", block_too: bool = False,
                 target_anon: str | None = None) -> dict:
    """ثبت گزارش + snapshot شواهد + امتیاز severity + (اختیاری) auto-moderation."""
    from database import db
    from ring import relay, service
    cfg = await S.get_cfg()
    rl = await db.ring_limit_hit("report", uid, int(cfg["max_report_per_day"]), 86400)
    if not rl["ok"]:
        return {"ok": False, "why": "rate_limited", "retry_after": rl["retry_after"]}
    # §۲۲ — دلیل با نگاشت کلیدهای قدیمی (sexual_content/scam/suspicious)
    # نرمال می‌شود تا گزارش‌های وزن‌دارِ انباشته از دست نروند.
    reason = M.norm_choice(M.reason_key(reason_key), M.REPORT_REASONS, "other")
    severity = int(M.REPORT_REASONS[reason][1])
    sess = await db.ring_session(session_id) if session_id else None
    peer = await db.ring_session_peer(sess, uid) if sess else None
    if peer is None and target_anon:
        # گزارش بعد از تمام‌شدن چت: با همان ناشناس‌آی‌دی (§۲۰)
        p = await db.ring_profile_by_anon(str(target_anon).strip().lstrip("#"))
        peer = int(p["_id"]) if p else None
    if peer is None:
        return {"ok": False, "why": "no_target"}
    rep = {
        "session_id": session_id or None, "reporter_uid": int(uid),
        "reported_uid": int(peer), "mode": (sess or {}).get("mode"),
        "reason": reason, "details": M.clean_text(details, 600),
        "severity": severity,
        "reporter_anon": (await db.ring_profile(uid) or {}).get("anon_id"),
        "reported_anon": (await db.ring_profile(peer) or {}).get("anon_id"),
    }
    rid = await db.ring_report_create(rep)
    ev = 0
    if session_id:
        ev = await relay.persist_buffer_as_evidence(session_id, rid)
    # گزارش = پایان گفت‌وگو (با دلیلِ «گزارش‌شده» تا ادمب بفهمد)
    if sess and sess.get("status") == "active":
        await service.end_session(uid, session_id, "reported", requeue_uids=())
    if block_too:
        await db.ring_block(uid, peer, f"report:{rid}")
    score = await db.ring_profile_score(peer, severity, warnings=1)
    acted = await _auto_moderate(peer, score, cfg)
    await db.ring_audit("user", "REPORT_CREATED", f"{uid}->{peer}", reason,
                        {"report_id": rid, "evidence": ev, "score": score})
    await db.ring_bump(report=1)
    logger.info("RING_REPORT_CREATED id=%s sev=%s score=%s", rid, severity, score)
    return {"ok": True, "report_id": rid, "score": score,
            "evidence": ev, "auto": acted, "blocked": bool(block_too)}


async def _auto_moderate(uid: int, score: int, cfg: dict) -> str:
    """محدودیت/بن خودکار فقط بر اساس آستانه — و همیشه قابل بازگشت (§۲۳)."""
    from database import db
    if not cfg.get("auto_mod_enabled"):
        return "off"
    if score >= int(cfg["report_ban_score"]):
        hours = int(cfg["auto_ban_hours"])
        until = (now_utc() + timedelta(hours=hours)).isoformat(timespec="seconds")
        await db.ring_ban_create(uid, "temporary", until,
                                 f"auto:score>={cfg['report_ban_score']}", 0)
        await db.ring_bump(bans=1)
        logger.info("RING_USER_BANNED uid=%s auto=%ss", uid, hours)
        return "banned"
    if score >= int(cfg["report_restrict_score"]):
        await db.ring_profile_status(uid, "paused")
        await db.ring_queue_leave(uid)
        return "restricted"
    if score >= int(cfg["report_review_score"]):
        return "review"
    return "none"


# ══════════════════════════════════════════════════════════════
#  بن (از پنل)
# ══════════════════════════════════════════════════════════════

BAN_PRESETS = {"1h": 1, "6h": 6, "24h": 24, "3d": 72, "7d": 168, "30d": 720}


async def admin_ban(admin_id: int, uid: int, kind: str, hours: int | None,
                    reason: str, scope: str = "ring") -> dict:
    from database import db
    kind = M.norm_choice(kind, ["warning", "temporary", "permanent"], "temporary")
    until = None
    if kind == "temporary":
        h = int(hours or BAN_PRESETS["24h"])
        until = (now_utc() + timedelta(hours=max(1, min(h, 24 * 365)))).isoformat(timespec="seconds")
    if kind == "warning":
        await db.ring_profile_score(uid, 0, warnings=1)
        await db.ring_audit(admin_id, "WARN_USER", str(uid), reason[:200], {"scope": scope})
        await notify.send_text(uid, "⚠️ درباره‌ی رفتارت در رینگ استریت هشداری ثبت شد.")
        return {"ok": True, "kind": "warning"}
    await db.ring_ban_create(uid, kind, until, reason, admin_id, scope)
    if kind == "permanent" and scope == "global":
        # بن سراسریِ ربات (حذف اکان + blacklist) عمداً اینجا صدا زده نمی‌شود:
        # `db.block_user` رکورد کاربر را از `users` پاک می‌کند و خارج از
        # دامنه‌ی رینگ است. پرچم ذخیره می‌شود و ادمین از پنلِ موجود اقدام می‌کند (§۹۳).
        await db.ring_cols.bans.update_one(
            {"user_id": int(uid), "scope": "global", "admin_id": int(admin_id)},
            {"$set": {"global_flagged": True}}, upsert=True)
    sess = await db.ring_session_active_for(uid)
    if sess:
        from ring import service
        await service.end_session(None, sess["session_id"], "banned", requeue_uids=())
    await db.ring_audit(admin_id, "BAN_USER", str(uid), reason[:200],
                        {"kind": kind, "until": until, "scope": scope})
    logger.info("RING_USER_BANNED uid=%s kind=%s by=%s", uid, kind, admin_id)
    await notify.send_text(uid, "🚫 دسترسی شما به رینگ استریت "
                                + ("برای همیشه " if kind == "permanent" else "موقتاً ")
                                + "محدود شد." + (f"\nدلیل: {reason[:120]}" if reason else ""))
    return {"ok": True, "kind": kind, "until": until}


async def admin_lift(admin_id: int, uid: int, reason: str = "") -> dict:
    from database import db
    await db.ring_ban_lift(uid, reason[:200])
    await db.ring_cols.profiles.update_one({"_id": int(uid)}, {"$set": {"report_score": 0}})
    await db.ring_audit(admin_id, "UNBAN_USER", str(uid), reason[:200], {})
    await notify.send_text(uid, "✅ محدودیت رینگ استریت شما برداشته شد.")
    return {"ok": True}


# ══════════════════════════════════════════════════════════════
#  بررسی گزارش (Moderation)
# ══════════════════════════════════════════════════════════════

ACTIONS = {"resolve": "resolved", "dismiss": "dismissed", "review": "reviewing",
           "warn": "action_taken", "temp_ban": "action_taken",
           "perm_ban": "action_taken", "restore": "pending"}


async def admin_review(admin_id: int, report_id: int, action: str,
                       note: str = "") -> dict:
    from database import db
    act = M.norm_choice(action, list(ACTIONS), "review")
    rep = await db.ring_report_get(report_id)
    if not rep:
        return {"ok": False, "why": "not_found"}
    target = int(rep.get("reported_uid") or 0)
    await db.ring_report_set_status(report_id, ACTIONS[act], admin_id, note)
    if act == "warn":
        await db.ring_profile_score(target, 0, warnings=1)
    elif act == "temp_ban":
        await admin_ban(admin_id, target, "temporary", 24, note or f"report:{report_id}")
    elif act == "perm_ban":
        await admin_ban(admin_id, target, "permanent", None, note or f"report:{report_id}")
    elif act in ("resolve", "dismiss", "restore"):
        await db.ring_profile_score(target, -1 if act == "dismiss" else 0)
    await db.ring_audit(admin_id, f"REVIEW_REPORT:{act}", str(report_id),
                        note[:200], {"target": target})
    return {"ok": True, "action": act, "status": ACTIONS[act]}


async def user_report_history(uid: int) -> dict:
    from database import db
    rows = await db.ring_cols.reports.find({"reporter_uid": int(uid)}) \
                    .sort("created_at", -1).to_list(30)
    return {"made": [{"id": r.get("report_id"), "reason": r.get("reason"),
                      "status": r.get("status"), "at": r.get("created_at")} for r in rows]}


async def rating(uid: int, session_id: str, score_key: str) -> dict:
    """امتیاز پس از جلسه — بی‌نام و یک‌بار (§۲۴)."""
    from database import db
    if not (await S.get_cfg()).get("allow_rating"):
        return {"ok": False, "why": "off"}
    sess = await db.ring_session(session_id)
    if not sess:
        return {"ok": False, "why": "no_session"}
    peer = await db.ring_session_peer(sess, uid)
    if peer is None:
        return {"ok": False, "why": "no_peer"}
    sc = M.RATINGS.get(score_key)
    if sc is None:
        return {"ok": False, "why": "bad_score"}
    added = await db.ring_rating_add(session_id, uid, peer, sc)
    if added:
        await db.ring_bump(rating=1)
    return {"ok": True, "duplicate": not added}
