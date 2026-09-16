"""🛡 رینگ استریت — API ادمین (§۳۲، §۶۶..§۷۴)

فقط `/api/ring/*`؛ هیچ route موجودی دست‌نخورده. همه‌ی اکشن‌ها دو جا لاگ
می‌شوند: `ring_admin_audit` (تاریخچه‌ی خودِ فیچر) و `audit_logs` عمومی
پنل (`db.log_action`) تا ردپای پنل یکدست بماند.

نکته‌ی حریم: این API هرگز پیام/محتوای گفت‌وگو را نمی‌دهد، مگر شواهدِ
یک گزارش که فقط با TTL کوتاه و پس از گزارش ثبت‌شده وجود دارد (§۳۵).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.auth import require_perm
from api.serialize import doc, docs, payload
from database import db
from ring import moderation, service
from ring import settings as S
from ring import state as ring_state
from time_utils import utc_now_iso

logger = __import__("logging").getLogger(__name__)

router = APIRouter()
_guard = Depends(require_perm("ring.manage"))


# ══════════════════════════════════════════════════════════════
#  Bodies
# ══════════════════════════════════════════════════════════════

class FlagBody(BaseModel):
    enabled: bool
    disable_mode: str = Field(default="soft", pattern="^(soft|hard)$")


class SettingsBody(BaseModel):
    updates: dict = Field(default_factory=dict)


class BanBody(BaseModel):
    user_id: int
    kind: str = Field(default="temporary", pattern="^(warning|temporary|permanent)$")
    hours: int | None = None
    reason: str = ""
    scope: str = Field(default="ring", pattern="^(ring|global)$")


class ReviewBody(BaseModel):
    action: str
    note: str = ""


class ForceMatchBody(BaseModel):
    user_a: int
    user_b: int


class EndBody(BaseModel):
    reason: str = "admin"


class StateBody(BaseModel):
    """§۴۵ — سه حالت از یک منبع حقیقت (Mongo)، بدون flag سخت‌کدشده."""
    state: str = Field(pattern="^(active|maintenance|disabled)$")
    disable_mode: str = Field(default="soft", pattern="^(soft|hard)$")


class RulesBody(BaseModel):
    text: str = ""
    bump_version: bool = True


def _wait_s(iso) -> int | None:
    """مدت انتظار از `queued_at` (برای مانیتور صف) — بدون query اضافه."""
    try:
        from time_utils import now_utc
        t = now_utc().fromisoformat(str(iso))
        if t.tzinfo is None:
            t = t.replace(tzinfo=now_utc().tzinfo)
        return max(0, int((now_utc() - t).total_seconds()))
    except Exception:
        return None


def _admin(user: dict) -> int:
    try:
        return int(user.get("id") or 0)
    except Exception:
        return 0


async def _audit(user: dict, action: str, target: str, note: str = "",
                 details: dict | None = None) -> None:
    """double-write: تاریخچه‌ی رینگ + audit_logs عمومی پنل (§۷۳)."""
    if not await db.ring_audit(_admin(user), action, target, note, details or {}):
        raise HTTPException(status_code=503, detail="ثبت حسابرسی رینگ انجام نشد؛ دوباره تلاش کنید")
    try:
        actor = user.get("_db") or {}
        # unify: ring → system/integration with correct actor_role from DB
        try:
            _role_ring = await db.get_actor_role_label(actor.get("user_id", _admin(user)) or 0)
        except Exception:
            _role_ring = actor.get("name", "مدیر رینگ") or "ring"
        await db.log_action(
            actor.get("user_id", _admin(user)) or 0,
            actor.get("name", "مدیر رینگ"), _role_ring,
            action, "System", category="system", target_type="ring", target_id=str(target),
            target_label=str(note)[:120], details=str(details or "")[:400],
            tags=["#پنل_وب", "#رینگ"])
    except Exception as e:
        logger.exception("ring admin audit write failed (%s)", action)
        raise HTTPException(status_code=503, detail="ثبت حسابرسی رینگ انجام نشد؛ دوباره تلاش کنید") from e


# ══════════════════════════════════════════════════════════════
#  داشبورد / صف / گفت‌وگوها
# ══════════════════════════════════════════════════════════════

@router.get("/metrics")
async def metrics(days: int = Query(7, ge=1, le=90), user=_guard):
    """§۴۹ — شمارنده‌های چرخهٔ مچ (attempts/candidates/created/notify/orphans).

    فقط `$inc`های روزانه را از `ring_stats_daily` می‌خواند و یتیم‌های *الان* را
    از `ring_overview`؛ هیچ کوئریِ تازه‌ای روی sessions/queue نمی‌زند.
    """
    from ring import analytics as A
    await A.flush_metrics()                 # تا عددی که می‌بینید的最新ِ RAM هم باشد
    return payload(await A.cycle_metrics(days=days))


@router.get("/sessions/{session_id}/health")
async def session_health(session_id: str, user=_guard):
    """§۴۶ — سلامتِ مرحله‌به‌مرحلهٔ یک match (state/queue/timer/notify/relay)."""
    return payload(await service.session_health(session_id))


@router.post("/sessions/{session_id}/repair")
async def session_repair(session_id: str, user=_guard):
    """§۴۷ — ترمیمِ محافظه‌کارانه + گزارشِ «چه چیزی درست شد».

    ایمن است: هیچ session را نمی‌بندد، پیامِ کاربری را پاک نمی‌کند و کارت
    تکراری نمی‌فرستد (per-user sent flag). اگر همه‌چیز درست باشد no-op است.
    """
    from database import db
    out = await service.repair_session(session_id)
    await db.ring_audit(int(user.get("id") or 0), "RING_SESSION_REPAIR",
                        session_id, str(out.get("repaired") or {})[:400], {})
    return payload(out)


@router.get("/overview")
async def overview(user=_guard):
    cfg = await S.get_cfg()
    return {
        "flag": await S.get_flag(),
        "disable_mode": await S.disable_mode(),
        "maintenance": await S.maintenance(),
        "state": await S.ui_state(),
        "state_label": _STATE_LABELS.get(await S.ui_state(), "—"),
        "rules_version": service.rules_want(await S.get_cfg()),
        "live": payload(await db.ring_overview()),
        "queue": payload(await db.ring_queue_stats()),
        "settings": cfg,
        "labels": S.labels(),
        "ram": {"in_chat": ring_state.count()},
        "server_time": utc_now_iso(),
    }


# ══════════════════════════════════════════════════════════════
#  وضعیت فیچر (§۴۵) و قوانین (§۲۶/§۲۷)
# ══════════════════════════════════════════════════════════════

_STATE_LABELS = {"active": "🟢 فعال", "maintenance": "🟡 نگهداری",
                 "disabled": "🔴 غیرفعال"}


@router.get("/state")
async def state_get(user=_guard):
    st = await S.ui_state()
    return {"state": st, "state_label": _STATE_LABELS.get(st, "—"),
            "enabled": await S.get_flag(), "maintenance": await S.maintenance(),
            "disable_mode": await S.disable_mode()}


@router.post("/state")
async def state_post(body: StateBody, user=_guard):
    """تک‌نقطهٔ تغییر وضعیت: active / maintenance / disabled.

    maintenance یعنی «چت‌های جاری تمام شوند، جفت تازه ساخته نشود» — پس نه
    sessionی بسته می‌شود و نه پیامی به کاربران می‌پرد؛ فقط join_queue و
    try_match دروازه دارند. تغییر وضعیت هیچ callback قدیمی را نمی‌شکند
    (§۳/§۶۶) چون کلیدها در `ring/handlers.py` همچنان ثبت‌اند.
    """
    want, mode = body.state, body.disable_mode
    await S.set_enabled(_admin(user), want != "disabled", mode)
    await S.set_maintenance(_admin(user), want == "maintenance")
    S.invalidate()
    if want == "disabled" and mode == "hard":
        from ring import jobs as ring_jobs
        await ring_jobs._hard_disable(db)
    await _audit(user, "RING_STATE", want, mode)
    return {"ok": True, "state": want, "state_label": _STATE_LABELS.get(want, "—"),
            "enabled": want != "disabled", "maintenance": want == "maintenance",
            "disable_mode": mode}


@router.get("/rules")
async def rules_get(user=_guard):
    """متن قوانین (پیش‌فرض/جایگزین ادمین) + چند نفر نسخهٔ فعلی را پذیرفته‌اند."""
    from ring import models as ring_models
    from ring import texts as ring_texts
    cfg = await S.get_cfg(force=True)
    # نسخهٔ *الزامی* (کفِ کد + عددِ پنل) — وگرنه پنل عددی را نشان می‌دهد که
    # عملاً از کاربر خواسته نشده (§۴۰/§۲۷)
    ver = service.rules_want(cfg)
    accepted = await db.ring_cols.profiles.count_documents(
        {"rules_version": {"$gte": ver}})
    total = await db.ring_cols.profiles.count_documents({"status": "active"})
    return {
        "version": ver,
        "text": (cfg.get("rules_text_override") or "").strip()
                or ring_texts.RULES_BODY,
        "default_text": ring_texts.RULES_BODY,
        "overridden": bool((cfg.get("rules_text_override") or "").strip()),
        "min_age": int(cfg.get("min_age", 18)),
        "accepted": accepted, "active_profiles": total,
        "pending": max(0, total - accepted),
    }


@router.post("/rules")
async def rules_post(body: RulesBody, user=_guard):
    """ذخیرهٔ متن (و در صورت درخواست، بالا بردن نسخه ⇒ همه دوباره می‌پذیرند)."""
    from ring import models as ring_models
    cfg = await S.get_cfg(force=True)
    cur_ver = service.rules_want(cfg)
    text = (body.text or "").strip()
    if len(text) > 3500:
        raise HTTPException(status_code=422, detail="متن قوانین بیش از ۳۵۰۰ کاراکتر است")
    updates = {"rules_text_override": text, "rules_version": cur_ver + 1
               if body.bump_version else cur_ver}
    merged = await S.set_cfg(_admin(user), updates)
    S.invalidate()
    await _audit(user, "RING_RULES", f"v{updates['rules_version']}",
                 f"{len(text)} کاراکتر", {"bump": bool(body.bump_version)})
    return {"ok": True, "version": updates["rules_version"],
            "overridden": bool(text), "settings": merged}


@router.get("/queue")
async def queue(mode: str | None = Query(default=None, pattern="^(serious|fun)$"),
                limit: int = Query(default=100, ge=1, le=500),
                user=_guard):
    rows = await db.ring_queue_list(mode=mode, limit=limit)
    out = []
    for r in rows:
        out.append({"uid": r.get("user_id"), "mode": r.get("mode"),
                    "status": r.get("status"), "anon": r.get("anon_id"),
                    "gender": r.get("gender"), "age_range": r.get("age_range"),
                    "queued_at": r.get("queued_at"),
                    "wait_s": _wait_s(r.get("queued_at"))})
    return {"queue": out, "stats": payload(await db.ring_queue_stats())}


@router.get("/sessions")
async def sessions(status: str | None = Query(default="active",
                                             pattern="^(active|ended)$"),
                   mode: str | None = Query(default=None, pattern="^(serious|fun)$"),
                   page: int = Query(default=1, ge=1, le=2000),
                   size: int = Query(default=25, ge=1, le=200),
                   user=_guard):
    rows, total = await db.ring_session_list(status=status, mode=mode,
                                             page=page, per=size)
    # 🛡 AUDIT-§۷۵ — سندِ خام = `_id` از نوع ObjectId ⇒ ۵۰۰ در سریال‌ساز
    return {"sessions": docs(rows), "total": total, "page": page, "size": size}


@router.get("/sessions/{sid}")
async def session_detail(sid: str, user=_guard):
    sess = await db.ring_session(sid)
    if not sess:
        raise HTTPException(404, "session پیدا نشد")
    sess.pop("slots", None)                      # uidها در users هستند
    ev = await db.ring_evidence_for(sid, limit=50)
    return {"session": doc(sess), "evidence_count": len(ev),
            "reports": [r.get("report_id") for r in
                        await db.ring_cols.reports.find({"session_id": sid})
                        .to_list(20)]}


@router.post("/sessions/{sid}/end")
async def session_end(sid: str, body: EndBody, user=_guard):
    r = await service.admin_force_end(_admin(user), sid, body.reason)
    if r["kind"] != "ok":
        raise HTTPException(404 if r["kind"] == "not_found" else 400,
                            "جلسه پیدا نشد یا بسته شده است")
    await _audit(user, "RING_FORCE_END", sid, body.reason)
    return {"ok": True}


# ══════════════════════════════════════════════════════════════
#  گزارش‌ها (Moderation)
# ══════════════════════════════════════════════════════════════

@router.get("/reports")
async def reports(status: str | None = None, page: int = Query(default=1, ge=1),
                  size: int = Query(default=25, ge=1, le=100),
                  user=_guard):
    rows, total = await db.ring_report_list(status=status, page=page, per=size)
    # 🛡 AUDIT-§۷۵ — ریشه‌ی ۵۰۰ پروداکشن: jsonable_encoder روی `_id` با
    # `TypeError: 'ObjectId' object is not iterable` می‌ترکید. با فهرستِ خالی
    # پاسخ ۲۰۰ بود؛ با اولین گزارشِ واقعی — و بعد از انجامِ effectها — ۵۰۰.
    return {"reports": docs(rows), "total": total, "page": page, "size": size}


@router.get("/reports/{rid}")
async def report_detail(rid: int, user=_guard):
    rep = await db.ring_report_get(rid)
    if not rep:
        raise HTTPException(404, "گزارش پیدا نشد")
    ev = await db.ring_evidence_for(rep.get("session_id") or "", limit=60)
    target = await db.ring_profile(int(rep.get("reported_uid") or 0))
    return {"report": doc(rep), "evidence": docs(ev),
            "target": {"score": (target or {}).get("report_score"),
                       "warnings": (target or {}).get("warnings"),
                       "status": (target or {}).get("status"),
                       "history": docs(await db.ring_reports_against(
                           int(rep["reported_uid"]), 30)) if target else []}}


@router.post("/reports/{rid}/review")
async def report_review(rid: int, body: ReviewBody, user=_guard):
    r = await moderation.admin_review(_admin(user), rid, body.action, body.note)
    if not r.get("ok"):
        raise HTTPException(404, "گزارش پیدا نشد")
    await _audit(user, f"RING_REPORT_{body.action}", str(rid), body.note,
                 {"target": r.get("target")})
    return payload(r)


# ══════════════════════════════════════════════════════════════
#  پروفایل / بلاک / بن
# ══════════════════════════════════════════════════════════════

@router.get("/profiles")
async def profiles(q: str | None = None, status: str | None = None,
                   mode: str | None = None, page: int = Query(default=1, ge=1),
                   size: int = Query(default=25, ge=1, le=100),
                   user=_guard):
    rows, total = await db.ring_admin_profiles(q=q, status=status, mode=mode,
                                               page=page, per=size)
    return {"profiles": docs(rows), "total": total, "page": page, "size": size}


@router.get("/profiles/{uid}")
async def profile_detail(uid: int, user=_guard):
    p = await db.ring_profile(uid)
    if not p:
        raise HTTPException(404, "پروفایلی برای این آیدی ثبت نشده")
    sess, _ = await db.ring_session_list(uid=uid, status=None, page=1, per=10)
    blocks = await db.ring_blocks_list(uid)
    return {
        "profile": doc({k: p.get(k) for k in
                    ("_id", "anon_id", "mode", "gender", "age_range", "status",
                     "report_score", "warnings", "sessions_count", "bio",
                     "interests", "city", "university", "major", "topics", "state",
                     "created_at", "updated_at", "consent_terms_at")}),
        "sessions": docs(sess),
        "blocks_given": len(blocks),
        "reports_against": docs(await db.ring_reports_against(uid, 30)),
        "rating": await db.ring_rating_stats(uid),
        "ban": doc(await db.ring_ban_active(uid)),
    }


@router.post("/profiles/{uid}/pause")
async def profile_pause(uid: int, user=_guard):
    await service.set_paused(uid, True)
    await _audit(user, "RING_PAUSE", str(uid))
    return {"ok": True}


@router.post("/profiles/{uid}/resume")
async def profile_resume(uid: int, user=_guard):
    await service.set_paused(uid, False)
    await _audit(user, "RING_RESUME", str(uid))
    return {"ok": True}


@router.post("/profiles/{uid}/queue/remove")
async def queue_remove(uid: int, user=_guard):
    await service.admin_remove_from_queue(_admin(user), uid)
    return {"ok": True}


@router.get("/blocks")
async def blocks(uid: int | None = Query(default=None),
                 limit: int = Query(default=100, ge=1, le=500), user=_guard):
    """مسدودسازی‌ها (§۴۶) — با `uid` فهرست یک کاربر، بدون آن فهرست سراسری."""
    if uid is not None:
        rows = await db.ring_blocks_list(uid)
    else:
        rows = await db.ring_blocks_recent(limit=limit)
    out = []
    for r in rows:
        a_uid = int(r.get("user_id") or 0)
        b_uid = int(r.get("blocked_user_id") or 0)
        pa = await db.ring_profile(a_uid) or {}
        pb = await db.ring_profile(b_uid) or {}
        out.append({"user_id": a_uid, "blocked_user_id": b_uid,
                    "user_anon": pa.get("anon_id"), "blocked_anon": pb.get("anon_id"),
                    "source": r.get("source") or ("report" if r.get("from_report") else "user"),
                    "created_at": r.get("created_at") or r.get("at")})
    total = await db.ring_cols.blocks.count_documents({})
    return {"blocks": out, "total": total}


@router.get("/bans")
async def bans(limit: int = Query(default=50, ge=1, le=200), user=_guard):
    return {"bans": docs(await db.ring_ban_list(limit=limit))}


@router.post("/bans")
async def ban(body: BanBody, user=_guard):
    r = await moderation.admin_ban(_admin(user), body.user_id, body.kind,
                                   body.hours, body.reason, body.scope)
    await _audit(user, "RING_BAN", str(body.user_id), body.reason, r)
    return payload(r)


@router.delete("/bans/{uid}")
async def unban(uid: int, user=_guard):
    r = await moderation.admin_lift(_admin(user), uid, "panel")
    await _audit(user, "RING_UNBAN", str(uid))
    return payload(r)


@router.post("/force-match")
async def force_match(body: ForceMatchBody, user=_guard):
    r = await service.admin_force_match(_admin(user), body.user_a, body.user_b)
    await _audit(user, "RING_FORCE_MATCH", f"{body.user_a},{body.user_b}", "", r)
    if r["kind"] not in ("ok",):
        raise HTTPException(400, f"ممکن نشد: {r.get('kind')}"
                            + (f" (uid={r['uid']})" if r.get("uid") else ""))
    return payload({"ok": True, "session": r.get("session")})


# ══════════════════════════════════════════════════════════════
#  تنظیمات / آمار / حسابرسی
# ══════════════════════════════════════════════════════════════

@router.get("/debug-match")
async def debug_match(a: int = Query(..., ge=1), b: int = Query(..., ge=1),
                      user=_guard):
    """§۳۷/§۳۸ — «چرا این دو نفر به هم مچ نشدند؟» با *همان* الگوریتمِ زنده.

    هیچ تصمیمِ دیگری ساخته نمی‌شود: `service.pair_diagnose` دقیقاً `_verdict`
    را اجرا می‌کند، پس چیزی که پنل نشان می‌دهد با لاگ
    `RING_MATCH_ATTEMPT … reason=` یکی است. داده‌ی خصوصی (بیو/علاقه‌مندی)
    برگردانده نمی‌شود — فقط بولتینِ چک‌ها و دلیل.
    """
    if a == b:
        raise HTTPException(422, "دو uid متفاوت لازم است")
    out = await service.pair_diagnose(int(a), int(b))
    await _audit(user, "RING_DEBUG_MATCH", f"{a},{b}", out.get("reason") or "ok")
    return payload(out)


@router.get("/settings")
async def settings_get(user=_guard):
    return {"settings": await S.get_cfg(force=True), "labels": S.labels(),
            "defaults": S.defaults(),
            "flag": await S.get_flag(), "disable_mode": await S.disable_mode()}


@router.post("/flag")
async def flag(body: FlagBody, user=_guard):
    await S.set_enabled(_admin(user), body.enabled, body.disable_mode)
    if not body.enabled and body.disable_mode == "hard":
        from ring import jobs as ring_jobs
        await ring_jobs._hard_disable(db)
    await _audit(user, "RING_FLAG", "on" if body.enabled else "off",
                 body.disable_mode)
    return {"ok": True, "enabled": body.enabled, "disable_mode": body.disable_mode}


@router.post("/settings")
async def settings_post(body: SettingsBody, user=_guard):
    merged = await S.set_cfg(_admin(user), body.updates or {})
    await _audit(user, "RING_SETTINGS", "cfg", "", {"changed": list(body.updates or {})})
    return payload({"ok": True, "settings": merged})


@router.get("/analytics")
async def analytics(days: int = Query(default=7, ge=1, le=180), user=_guard):
    from ring import analytics as A
    return payload(await A.summary(days))


@router.get("/audit")
async def audit(limit: int = Query(default=60, ge=1, le=400), user=_guard):
    return {"audit": docs(await db.ring_audit_list(limit=limit))}


@router.post("/maintenance/reconcile")
async def reconcile(user=_guard):
    """ترمیم دستی ناسازگارها (session/queue یتیم) — idempotent."""
    r = await db.ring_reconcile()
    await _audit(user, "RING_RECONCILE", "", "", r)
    return {"ok": True, **r}


@router.post("/maintenance/purge-evidence")
async def purge_evidence(user=_guard):
    n = await db.ring_evidence_purge()
    await _audit(user, "RING_PURGE_EVIDENCE", "", f"n={n}")
    return {"ok": True, "purged": n}


@router.post("/maintenance/disable-all")
async def disable_all(body: FlagBody, user=_guard):
    """خاموشی اضطراری + بستن همه (§۷۴) — برای «یک‌دکمه‌ی خاموش»."""
    await S.set_enabled(_admin(user), False, "hard")
    from ring import jobs as ring_jobs
    await ring_jobs._hard_disable(db)
    await _audit(user, "RING_DISABLE_ALL", "global", body.disable_mode)
    return {"ok": True}
