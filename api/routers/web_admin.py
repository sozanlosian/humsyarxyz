# -*- coding: utf-8 -*-
"""
🖥️ موج WA + WA2 — Web Admin Control Center API

احراز هویت مستقل دسکتاپ: OTP تلگرامی → سشن HttpOnly (۱۲ ساعته).
هیچ منطق کسب‌وکاری تکرار نمی‌شود: همان user/RBAC/audit/db موجود.
- مالک (ADMIN_ID) یا دارای هر مجوز RBAC یا ادمین محتوا ⇒ اجازه‌ی ورود وب.
- دسترسی به هر endpoint همچنان permission-based است (require_perm/owner).

🌊 WA2 (افزایشی — هیچ endpoint/رفتار قبلی حذف یا تغییر نکرده):
  WA2.1 Content Command Center : /content/tree + duplicate + bulk sessions/items
  WA2.2 Exams Admin            : /exams CRUD (schedules type=exam) + /exams/stats
  WA2.3 Settings Center        : /settings/center (GET/PATCH + meta)
  WA2.4 Bulk + Saved Filters   : tickets/questions bulk + /saved-filters
  WA2.5 Global Quick Search    : /search
  WA2.6 Analytics              : /wa-analytics (stats.view)
  WA2.7 Attention + Activity   : /attention + /activity
  WA2.8 User 360               : /users/{uid}/360
  WA2.9 Hardening              : محدودسازی bulk کاربران به مجوز + audit همه‌ی اکشن‌ها
"""
import asyncio
import csv
import hashlib
import io
import json
import logging
import re
import secrets
import time
from datetime import datetime, timedelta, date, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional

from api.auth import (
    ADMIN_ID, _hash_token, get_current_user, get_content_admin_user,
    expiry_is_past, get_content_global_user, new_session_token, resolve_content_intake,
    resolve_web_session, utc_now, WA_SESSION_COOKIE, WA_SESSION_TTL_H,
)
from api.rate_limit import rate_limit_user  # 🛡 W10/RATE-01
from database import db
from api.routers import admin_panel as owner_api
from api.routers import subscription_management as subscription_api
from api.routers import ai_management as ai_admin_api
from api.routers import content_admin as content_api
from api.routers import academic_admin as academic_api
from api.routers import rbac as rbac_api
from api.routers import resources as resources_api
import backup as backup_service
import broadcast_service
from ai_solver import save_persona, delete_persona, generate_broadcast_ai
from request_context import current_request_id
from question_bank import QuestionImportService, QuestionBankService, QuestionDomainError
from question_bank.contracts import approved_query, canonical_difficulty, canonical_status, clean_text, status_query
from time_utils import (
    TimeContractError, canonical_utc, day_bounds_utc, diagnostics as time_diagnostics,
    format_datetime_fa, now_utc, parse_clock_time, parse_gregorian_date,
    parse_machine_datetime, remaining_days, today_tehran, utc_now_iso,
)

logger = logging.getLogger("api.web_admin")

router = APIRouter()
question_bank = QuestionBankService(db)
question_imports = QuestionImportService(db)

OTP_TTL_MIN = 5
OTP_MAX_ATTEMPTS = 5
OTP_RL_COUNT = 5          # حداکثر درخواست کد
OTP_RL_WINDOW = 600       # در ۱۰ دقیقه

# rate-limit ساده‌ی درون‌حافظه‌ای per-identifier (گره Railway تک‌نمونه‌ای)
# 🛡 AUDIT-A4 — محدود و خودتصفیه‌شونده: مقدار هر کلید فقط «شمارنده + شروع
# پنجره» است (لیست بی‌نهایت زمان نه)، و کل دیکشنری بالای سقفِ کلید
# جارو می‌شود؛ در حمله‌ی کلید-متفاوت دیگر RAM پروسه بی‌نهایت رشد نمی‌کند.
_otp_rl: dict = {}
_OTP_RL_MAX_KEYS = 4096


def _otp_rl_allow(key: str) -> bool:
    """True اگر درخواست مجاز است؛ False یعنی پنجره پر شده (429)."""
    now = time.time()
    ent = _otp_rl.get(key)
    if not ent or (now - float(ent.get("first") or 0.0)) >= OTP_RL_WINDOW:
        _otp_rl[key] = {"first": now, "n": 1}
        allowed = True
    else:
        ent["n"] = int(ent.get("n") or 0) + 1
        allowed = ent["n"] <= OTP_RL_COUNT
    if len(_otp_rl) > _OTP_RL_MAX_KEYS:
        for k in [k for k, v in _otp_rl.items() if (now - float(v.get("first") or 0.0)) >= OTP_RL_WINDOW]:
            _otp_rl.pop(k, None)
        if len(_otp_rl) > _OTP_RL_MAX_KEYS:      # هنوز شلوغ → قدیمی‌ترین‌ها
            for k in sorted(_otp_rl, key=lambda k: float(_otp_rl[k].get("first") or 0.0))[
                    : len(_otp_rl) - _OTP_RL_MAX_KEYS]:
                _otp_rl.pop(k, None)
    return allowed

TERMS = ['ترم ۱', 'ترم ۲', 'ترم ۳', 'ترم ۴', 'ترم ۵']
CONTENT_TYPES = ['video', 'ppt', 'pdf', 'note', 'test', 'voice']


def _now() -> str:
    """Canonical machine timestamp; display conversion belongs to clients."""
    return utc_now_iso()


def _export_instant(value, human: bool = False):
    if value in (None, ""):
        return ""
    try:
        return format_datetime_fa(value, fallback=str(value)) if human else canonical_utc(value)
    except ValueError:
        return str(value)


def _oid(v):
    try:
        return ObjectId(str(v))
    except Exception:
        return None


async def _has_admin_access(uid: int) -> bool:
    """مالک یا دارای هر مجوز RBAC یا ادمین محتوا."""
    if uid == ADMIN_ID:
        return True
    try:
        if await db.is_content_admin(uid):
            return True
    except Exception:
        pass
    try:
        if await db.get_user_perms(uid):
            return True
    except Exception:
        pass
    return False


async def _resolve_user(identifier: str):
    """آیدی عددی یا یوزرنیم تلگرام → سند کاربر (بدون نشت وجود/عدم وجود)."""
    ident = (identifier or "").strip()[:64]
    if not ident:
        return None
    if ident.lstrip("-").isdigit():
        return await db.get_user(int(ident))
    uname = ident.lstrip("@").lower()
    # 🛡 AUDIT-R2 — ورودی باید «رشته» باشد نه الگو: قبلاً `. * + \d (…)` در
    # یوزرنیم معنای regexp می‌گرفت → تطبیق عرضیِ حساب‌های دیگر و هزینه‌ی
    # ReDoS روی ورودی بلند. escape + سقف طول، تطبیق را بایت‌به‌بایت می‌کند.
    return await db.users.find_one(
        {"username": {"$regex": f"^{re.escape(uname)}$", "$options": "i"}}
    )


async def _guard_any_admin(user=Depends(get_current_user)) -> dict:
    """گیت مشترک endpointهای وب‌ادمین: احراز هویت + حداقل یک سطح ادمین."""
    if not await _has_admin_access(user["id"]):
        raise HTTPException(status_code=403, detail="forbidden")
    return user


def _perm(permission: str):
    """🛡 WA2 — گیت مجوز برای اکشن‌های مدیریتی وب (تصمیم فقط با Permission).

    بای‌پس مالک/ادمین میراثی داخل db.has_permission اعمال می‌شود؛ در غیر
    این صورت 403 دقیقاً مثل بقیه‌ی سطح ادمین."""
    async def _guard(user=Depends(get_current_user)) -> dict:
        try:
            if await db.has_permission(user["id"], permission):
                return user
        except Exception:
            pass
        raise HTTPException(status_code=403, detail="forbidden")
    _guard.__name__ = f"wa_perm_{permission.replace('.', '_')}"
    return _guard


def _perm_any(*permissions: str):
    """عبور با داشتن حداقل یکی از مجوزها؛ owner bypass داخل DB باقی می‌ماند."""
    async def _guard(user=Depends(get_current_user)) -> dict:
        for permission in permissions:
            try:
                if await db.has_permission(user["id"], permission):
                    return user
            except Exception:
                continue
        raise HTTPException(status_code=403, detail="forbidden")
    _guard.__name__ = "wa_perm_any_" + "_or_".join(
        p.replace('.', '_') for p in permissions)
    return _guard


async def _audit(actor_uid: int, action: str, *, severity: str = "INFO",
                 target_id: str = "", target_type: str = "",
                 target_label: str = "", tags=None,
                 before: dict = None, after: dict = None, details: str = ""):
    """Mandatory WebAdmin audit persistence.

    Audit failures are no longer swallowed. Callers that need compensation can
    now roll a domain mutation back; all other callers fail visibly with the
    request ID rather than silently completing an unaudited sensitive action.
    """
    u = await db.get_user(actor_uid)
    return await db.log_action(
        actor_uid, (u or {}).get("name", str(actor_uid)),
        await db.get_actor_role_label(actor_uid),
        action, "WebAdmin", category="admin", severity=severity,
        target_id=str(target_id), target_type=target_type,
        target_label=target_label, tags=tags or [],
        before=before, after=after, details=details,
    )


async def _audit_strict(actor_uid: int, action: str, *, severity: str = "HIGH",
                        target_id: str = "", target_type: str = "",
                        target_label: str = "", tags=None,
                        before: dict = None, after: dict = None):
    """Audit variant for mutations that must fail closed and compensate."""
    actor = await db.get_user(actor_uid)
    return await db.log_action(
        actor_uid, (actor or {}).get("name", str(actor_uid)),
        await db.get_actor_role_label(actor_uid), action, "WebAdmin",
        category="admin", severity=severity, target_id=str(target_id),
        target_type=target_type, target_label=target_label,
        tags=tags or [], before=before, after=after,
    )


class RequestCode(BaseModel):
    identifier: str


class VerifyCode(BaseModel):
    identifier: str
    code: str


# 🛡 §۸۷ — نقشه‌ی اکشن→مجوزِ عملیات گروهی، تک‌منبع.
# پیش‌نمایش و اجرای واقعی *باید* از یک دیکشنری بخوانند؛ اگر هرکدام
# نسخه‌ی خودش را داشته باشد، روزی واگرا می‌شوند و پیش‌نمایش دروغ می‌گوید.
_BULK_ACTION_PERM = {
    "approve": "users.manage", "set_intake": "users.manage",
    "set_group": "users.manage", "add_role": "users.manage",
    "remove_role": "users.manage", "suspend": "users.suspend",
    "unsuspend": "users.suspend", "message": "users.message",
    "block": "users.delete",
    # 🛡 AUDIT-§۷۹ — اشتراک گروهی با همان مجوزِ «مرکز کنترل اشتراک»
    # (subscription.manage)، نه users.manage: پول در این مسیر جابه‌جا
    # می‌شود و گیت باید با گیتِ خودِ آن بخش یکی باشد.
    "grant_subscription": "subscription.manage",
    "renew_subscription": "subscription.manage",
}


class BulkBody(BaseModel):
    action: str            # approve | suspend | unsuspend | set_intake | grant_subscription | renew_subscription
    ids: list[int]
    value: Optional[str] = None     # WA2.4 — مقدار جانبی (مثل intake)
    # 🛡 AUDIT-§۷۹ — اشتراک گروهی: همان فیلدهای GrantBodyِ بخش مالی.
    # هیچ فیلدِ «موازی» ساخته نمی‌شود؛ اعطا از همان endpoint تک‌موردی انجام
    # می‌شود تا تاریخِ پایان، نوتیف، audit و ادعایِ یکتا یکی بماند.
    days: Optional[int] = Field(default=None, ge=1, le=3650)
    plan_name: Optional[str] = Field(default=None, max_length=100)
    extend: Optional[bool] = None


@router.post("/auth/request-code")
async def request_code(body: RequestCode, request: Request):
    """ارسال کد ورود ۶ رقمی از طریق ربات تلگرام (بدون نشت وجود حساب)."""
    ident = (body.identifier or "").strip()[:64]
    # ── rate limit ── (WA2.9: شناسه + IP هر دو در کلید لحاظ می‌شوند)
    ip = ""
    try:
        ip = (request.client.host if getattr(request, "client", None) else "") or ""
    except Exception:
        ip = ""
    rl_key = f"{ident}|{ip}"
    if not _otp_rl_allow(rl_key):
        raise HTTPException(status_code=429,
                            detail="تعداد درخواست زیاد است؛ چند دقیقه دیگر تلاش کنید.")

    user = await _resolve_user(ident)
    if user and user.get("approved") and not user.get("suspended"):
        uid = int(user.get("user_id"))
        if await _has_admin_access(uid):
            code = f"{secrets.randbelow(900000) + 100000}"
            salt = secrets.token_hex(16)
            exp = utc_now() + timedelta(minutes=OTP_TTL_MIN)
            await db.web_admin_otps.delete_many({"uid": uid})
            await db.web_admin_otps.insert_one({
                "uid": uid, "code_salt": salt,
                "code_hash": hashlib.sha256(f"{salt}:{code}".encode()).hexdigest(),
                "expires_at": exp, "attempts": 0, "created_at": utc_now(),
            })
            # ارسال از صف outbox موجود ربات (همان الگوی admin_panel._notify)
            await db.client["medicalbot"]["bot_notifications"].insert_one({
                "type": "web_admin_otp", "chat_id": uid,
                "text": (f"🔐 <b>کد ورود به پنل مدیریت هامزیار</b>\n\n"
                         f"کد: <code>{code}</code>\n"
                         f"⏳ اعتبار: {OTP_TTL_MIN} دقیقه\n\n"
                         f"اگر شما درخواست نداده‌اید، این پیام را نادیده بگیرید."),
                "sent": False, "created_at": _now(),
            })
            await _audit(uid, "درخواست کد ورود پنل وب", tags=["ورود_وب", "otp"])
    # پاسخ یکسان always (ضد account-enumeration)
    return {"ok": True,
            "message": "اگر این حساب ادمین باشد، کد ورود در تلگرام برایتان ارسال شد."}


@router.post("/auth/verify")
async def verify_code(body: VerifyCode, request: Request, response: Response):
    user = await _resolve_user(body.identifier)
    if not user:
        # 🛡 AUDIT-R7 (§۱۸) — این شاخه قبلاً متن خطای متفاوتی داشت و هیچ
        # مقایسه‌ای انجام نمی‌داد ⇒ هم بدنه و هم زمان پاسخ، «بود/نبودِ حساب»
        # را لو می‌داد. حالا دقیقاً مثل «کد غلط» رفتار می‌کند: مقایسه‌ی صوری
        # روی یک هش جعلی + همان status/detail. (وضعیت «کد منقضی‌شده» عمداً
        # حفظ شده: آن شاخه برای هر حسابِ دارای کد مصرف‌شده یکسان است و
        # اطلاعات تازه‌ای درباره‌ی وجود حساب نمی‌دهد.)
        _fake = hashlib.sha256(f"{'0' * 32}:{(body.code or '').strip()}".encode()).hexdigest()
        secrets.compare_digest(_fake, "0" * 64)
        raise HTTPException(status_code=401, detail="کد نامعتبر است.")
    uid = int(user.get("user_id"))
    otp = await db.web_admin_otps.find_one({"uid": uid})
    if not otp or expiry_is_past(otp.get("expires_at")):
        # 🛡 AUDIT-R7 — این شاخه هم دقیقاً مثل «حساب ناموجود» پاسخ می‌دهد؛
        # وگرنه تفاوتِ بدنه، بودنِ یک حسابِ ادمین را لو می‌دهد.
        raise HTTPException(status_code=401, detail="کد نامعتبر است.")
    if (otp.get("attempts") or 0) >= OTP_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="تلاش‌های ناموفق زیاد بود؛ دوباره درخواست کد بدهید.")
    raw_code = (body.code or "").strip()
    salt = otp.get("code_salt")
    candidate = hashlib.sha256(f"{salt}:{raw_code}".encode()).hexdigest() if salt \
        else hashlib.sha256(raw_code.encode()).hexdigest()
    ok = secrets.compare_digest(candidate, str(otp.get("code_hash") or ""))
    if not ok:
        await db.web_admin_otps.update_one({"uid": uid}, {"$inc": {"attempts": 1}})
        raise HTTPException(status_code=401, detail="کد نامعتبر است.")
    if not await _has_admin_access(uid):
        raise HTTPException(status_code=403, detail="forbidden")

    await db.web_admin_otps.delete_many({"uid": uid})
    token = new_session_token()
    peer_ip = ((getattr(request, "client", None) and request.client.host) or "")[:64]
    user_agent = (request.headers.get("user-agent") or "")[:240]
    now_utc = utc_now()
    await db.web_admin_sessions.insert_one({
        "_id": _hash_token(token), "uid": uid,
        "created_at": now_utc,
        "expires_at": now_utc + timedelta(hours=WA_SESSION_TTL_H),
        "revoked": False, "peer_ip": peer_ip, "user_agent": user_agent,
    })
    response.set_cookie(
        WA_SESSION_COOKIE, token,
        max_age=WA_SESSION_TTL_H * 3600,
        httponly=True, secure=True, samesite="lax", path="/",
    )
    try:
        await _audit(uid, "ورود موفق به پنل وب", tags=["ورود_وب"])
    except Exception:
        await db.web_admin_sessions.update_one(
            {"_id": _hash_token(token)},
            {"$set": {"revoked": True, "revoked_at": utc_now(),
                      "revoke_reason": "login_audit_failed"}},
        )
        response.delete_cookie(WA_SESSION_COOKIE, path="/")
        raise HTTPException(503, "ثبت حسابرسی ورود ممکن نشد؛ نشست ایجاد نشد")
    return {"ok": True, "id": uid, "name": user.get("name", "")}


@router.get("/me")
async def me(user=Depends(_guard_any_admin)):
    uid = user["id"]
    perms = sorted(await db.get_user_perms(uid))
    return {
        "id": uid,
        "name": (user.get("_db") or {}).get("name", ""),
        "nickname": (user.get("_db") or {}).get("nickname"),
        "username": (user.get("_db") or {}).get("username", ""),
        "is_owner": uid == ADMIN_ID,
        "is_content_admin": await db.is_content_admin(uid),
        "role_label": await db.get_actor_role_label(uid),
        "perms": perms,
    }


@router.post("/auth/logout")
async def logout(request: Request, response: Response, user=Depends(_guard_any_admin)):
    sess = await resolve_web_session(request.cookies.get(WA_SESSION_COOKIE, ""))
    if sess:
        await db.web_admin_sessions.update_one(
            {"_id": sess["_id"]}, {"$set": {"revoked": True, "revoked_at": utc_now()}})
    response.delete_cookie(WA_SESSION_COOKIE, path="/")
    await _audit(user["id"], "خروج از پنل وب", tags=["خروج_وب"])
    return {"ok": True}


def _session_time(value) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value or "")


@router.get("/system/security/sessions")
async def wa_security_sessions(
    request: Request, page: int = Query(1, ge=1), limit: int = Query(30, ge=1, le=100),
    user=Depends(_perm("system.manage")),
):
    """Bounded inventory of live WebAdmin sessions for security operations."""
    now = utc_now()
    legacy_now = utc_now().replace(tzinfo=None).isoformat()
    active_query = {"revoked": False, "$or": [
        {"expires_at": {"$type": "date", "$gt": now}},
        {"expires_at": {"$type": "string", "$gt": legacy_now}},
    ]}
    total, docs = await asyncio.gather(
        db.web_admin_sessions.count_documents(active_query),
        db.web_admin_sessions.find(active_query).sort("created_at", -1)
        .skip((page - 1) * limit).limit(limit).to_list(limit),
    )
    uids = sorted({int(doc.get("uid")) for doc in docs if doc.get("uid") is not None})
    users = await db.users.find(
        {"user_id": {"$in": uids}}, {"user_id": 1, "name": 1, "nickname": 1, "username": 1}
    ).to_list(len(uids)) if uids else []
    by_uid = {int(item.get("user_id")): item for item in users if item.get("user_id") is not None}
    current_id = _hash_token(request.cookies.get(WA_SESSION_COOKIE, "")) \
        if request.cookies.get(WA_SESSION_COOKIE) else ""
    rows = []
    for doc in docs:
        uid = int(doc.get("uid"))
        person = by_uid.get(uid, {})
        rows.append({
            "id": str(doc.get("_id")), "uid": uid,
            "name": person.get("nickname") or person.get("name") or str(uid),
            "username": person.get("username") or "",
            "created_at": _session_time(doc.get("created_at")),
            "expires_at": _session_time(doc.get("expires_at")),
            "peer_ip": str(doc.get("peer_ip") or ""),
            "user_agent": str(doc.get("user_agent") or "")[:240],
            "current": str(doc.get("_id")) == current_id,
        })
    return {"sessions": rows, "total": int(total), "page": page, "limit": limit,
            "pages": max(1, (int(total) + limit - 1) // limit), "checked_at": _now()}


class SessionRevokeIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


@router.post("/system/security/sessions/{session_id}/revoke")
async def wa_security_session_revoke(
    session_id: str, body: SessionRevokeIn, request: Request,
    user=Depends(_perm("system.manage")),
):
    if not re.fullmatch(r"[0-9a-f]{64}", session_id or ""):
        raise HTTPException(422, "شناسه نشست معتبر نیست")
    current_id = _hash_token(request.cookies.get(WA_SESSION_COOKIE, "")) \
        if request.cookies.get(WA_SESSION_COOKIE) else ""
    if session_id == current_id:
        raise HTTPException(409, "برای پایان نشست جاری از خروج از حساب استفاده کنید")
    session = await db.web_admin_sessions.find_one({"_id": session_id, "revoked": False})
    if not session or expiry_is_past(session.get("expires_at")):
        raise HTTPException(404, "نشست فعال پیدا نشد")
    target_uid = int(session.get("uid"))
    if target_uid == ADMIN_ID and user["id"] != ADMIN_ID:
        raise HTTPException(403, "نشست مالک فقط توسط خود مالک قابل لغو است")
    changed = await db.web_admin_sessions.update_one(
        {"_id": session_id, "revoked": False},
        {"$set": {"revoked": True, "revoked_at": utc_now(),
                  "revoked_by": user["id"], "revoke_reason": body.reason.strip()}},
    )
    if not getattr(changed, "modified_count", 0):
        raise HTTPException(409, "نشست هم‌زمان تغییر کرده است")
    try:
        await _audit_strict(
            user["id"], "لغو نشست فعال پنل وب", severity="HIGH",
            target_id=session_id[:16], target_type="web_admin_session",
            target_label=str(target_uid), tags=["امنیت", "لغو_نشست"],
            before={"uid": target_uid, "revoked": False,
                    "expires_at": _session_time(session.get("expires_at"))},
            after={"uid": target_uid, "revoked": True, "reason": body.reason.strip()},
        )
    except Exception:
        await db.web_admin_sessions.update_one(
            {"_id": session_id, "revoked_by": user["id"]},
            {"$set": {"revoked": False},
             "$unset": {"revoked_at": "", "revoked_by": "", "revoke_reason": ""}},
        )
        raise HTTPException(503, "ثبت حسابرسی ممکن نشد؛ لغو نشست بازگردانده شد")
    return {"ok": True, "session_id": session_id, "uid": target_uid}


@router.get("/overview")
async def overview(user=Depends(_guard_any_admin)):
    """KPIهای role-aware؛ هیچ شمارش خارج از effective permissions query نمی‌شود."""
    uid = user["id"]
    perms = await db.get_user_perms(uid)
    allow = lambda *keys: uid == ADMIN_ID or any(k in perms for k in keys)
    jobs = {}
    if allow("users.view", "users.manage", "stats.view"):
        jobs["total_users"] = db.users.count_documents({})
    if allow("users.manage"):
        jobs["pending_users"] = db.users.count_documents({"approved": False, "suspended": {"$ne": True}})
    if allow("subscription.manage"):
        jobs["pending_payments"] = db.sub_payment_count_all("pending")
        jobs["sub_stats"] = db.sub_stats()
    if allow("questions.review", "questions.review_scoped"):
        q_pending = status_query("pending")
        if not await db.has_permission(uid, "questions.review"):
            scoped_intake = await db.get_scoped_intake(uid)
            q_pending = {"$and": [q_pending, {"intake": scoped_intake or "__missing_scope__"}]}
        jobs["pending_questions"] = db.questions.count_documents(q_pending)
    if allow("tickets.reply", "tickets.manage"):
        jobs["open_tickets"] = db.tickets.count_documents({"status": "open"})
    if allow("reports.review"):
        jobs["open_reports"] = db.content_reports.count_documents({"status": {"$in": ["new", "pending", "reviewing"]}})
    keys = list(jobs)
    values = await asyncio.gather(*(jobs[k] for k in keys), return_exceptions=True)
    data = {k: (None if isinstance(v, Exception) else v) for k, v in zip(keys, values)}
    sub_stats = data.pop("sub_stats", None) or {}
    if allow("subscription.manage"):
        data["active_subs"] = sub_stats.get("active", 0)
        data["expiring_soon"] = sub_stats.get("expiring", 0)
    return data


_SMART_USER_RAW_FIELDS = {
    "name": "name", "nickname": "nickname", "username": "username",
    "student_id": "student_id", "intake": "intake", "group": "group",
    "total_answers": "total_answers", "correct_answers": "correct_answers",
    "streak": "streak_current", "ai_usage": "ai_total_usage",
    "registered_at": "registered_at", "last_active": "last_active",
}
_SMART_OPS = {"eq": "$eq", "ne": "$ne", "gt": "$gt", "gte": "$gte", "lt": "$lt", "lte": "$lte"}


async def _compile_user_smart_query(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        tree = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise HTTPException(422, "ساختار فیلتر هوشمند معتبر نیست")
    state = {"nodes": 0, "leaves": 0}
    now = now_utc()

    async def compile_node(node, depth=0):
        if depth > 3 or not isinstance(node, dict):
            raise HTTPException(422, "عمق فیلتر هوشمند بیشتر از حد مجاز است")
        state["nodes"] += 1
        if state["nodes"] > 40:
            raise HTTPException(422, "ساختار فیلتر هوشمند بیش از حد پیچیده است")
        if "conditions" in node:
            logic = str(node.get("logic") or "and").lower()
            if logic not in ("and", "or"):
                raise HTTPException(422, "منطق گروه باید AND یا OR باشد")
            conditions = node.get("conditions") or []
            if not conditions:
                raise HTTPException(422, "گروه شرط خالی است")
            compiled = [await compile_node(child, depth + 1) for child in conditions]
            return {"$and" if logic == "and" else "$or": compiled}
        state["leaves"] += 1
        if state["leaves"] > 30:
            raise HTTPException(422, "حداکثر ۳۰ شرط در فیلتر هوشمند مجاز است")
        field, op, value = node.get("field"), node.get("op", "eq"), node.get("value")
        if field in _SMART_USER_RAW_FIELDS:
            db_field = _SMART_USER_RAW_FIELDS[field]
            if op == "contains":
                text = str(value or "").strip()
                if not text: raise HTTPException(422, "مقدار جست‌وجوی شرط خالی است")
                return {db_field: {"$regex": re.escape(text), "$options": "i"}}
            if op == "in":
                values = value if isinstance(value, list) else [part.strip() for part in str(value or "").split(",") if part.strip()]
                return {db_field: {"$in": values[:100]}}
            mongo_op = _SMART_OPS.get(op)
            if not mongo_op: raise HTTPException(422, "عملگر فیلتر هوشمند پشتیبانی نمی‌شود")
            if field in ("total_answers", "correct_answers", "streak", "ai_usage"):
                try: value = float(value)
                except (TypeError, ValueError): raise HTTPException(422, "مقدار عددی شرط نامعتبر است")
            if field == "group": value = db.normalize_group(value)
            return {db_field: value} if op == "eq" else {db_field: {mongo_op: value}}
        if field == "status":
            mapping = {
                "active": {"approved": True, "suspended": {"$ne": True}},
                "pending": {"approved": False, "suspended": {"$ne": True}},
                "suspended": {"suspended": True},
            }
            if op not in ("eq", "ne") or value not in mapping:
                raise HTTPException(422, "شرط وضعیت نامعتبر است")
            if op == "eq": return mapping[value]
            return {"$nor": [mapping[value]]}
        if field == "accuracy":
            try: threshold = float(value)
            except (TypeError, ValueError): raise HTTPException(422, "آستانه دقت نامعتبر است")
            if op not in _SMART_OPS: raise HTTPException(422, "عملگر دقت نامعتبر است")
            accuracy_expr = {"$cond": [
                {"$gt": [{"$ifNull": ["$total_answers", 0]}, 0]},
                {"$multiply": [{"$divide": [{"$ifNull": ["$correct_answers", 0]},
                                               {"$ifNull": ["$total_answers", 1]}]}, 100]}, 0]}
            return {"$expr": {_SMART_OPS[op]: [accuracy_expr, threshold]}}
        if field == "inactive_days":
            try: days = max(0, min(3650, int(value)))
            except (TypeError, ValueError): raise HTTPException(422, "تعداد روز عدم فعالیت نامعتبر است")
            cutoff = (now - timedelta(days=days)).isoformat()
            clause = {"$or": [{"last_active": {"$lt": cutoff}}, {"last_active": {"$exists": False}}, {"last_active": ""}]}
            return clause if op in ("gte", "gt", "eq") else {"$nor": [clause]}
        if field == "subscription_days_left":
            try: days = max(0, min(3650, int(value)))
            except (TypeError, ValueError): raise HTTPException(422, "روز باقی‌مانده اشتراک نامعتبر است")
            end_filter = {"$gte": now.isoformat()}
            cutoff = (now + timedelta(days=days)).isoformat()
            if op in ("lte", "lt", "eq"): end_filter["$lte"] = cutoff
            elif op in ("gt", "gte"): end_filter["$gt"] = cutoff
            else: raise HTTPException(422, "عملگر اشتراک نامعتبر است")
            ids = await db.subscriptions.distinct("_id", {"status": "active", "end_date": end_filter})
            return {"user_id": {"$in": ids}}
        if field == "open_tickets":
            ids = await db.tickets.distinct("user_id", {"status": "open"})
            truthy = str(value).lower() in ("1", "true", "yes") or value is True
            return {"user_id": {"$in" if truthy else "$nin": ids}}
        if field == "role":
            ids = await db.user_ids_by_role(str(value or "").strip(), limit=100000)
            return {"user_id": {"$in": ids}}
        if field == "exam_count":
            try: threshold = max(0, int(value))
            except (TypeError, ValueError): raise HTTPException(422, "تعداد آزمون نامعتبر است")
            mongo_op = _SMART_OPS.get(op)
            if not mongo_op: raise HTTPException(422, "عملگر تعداد آزمون نامعتبر است")
            grouped = await db.exam_sessions.aggregate([
                {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
                {"$match": {"count": {mongo_op: threshold}}}, {"$project": {"_id": 1}},
            ]).to_list(100000)
            return {"user_id": {"$in": [row.get("_id") for row in grouped if row.get("_id") is not None]}}
        raise HTTPException(422, "فیلد فیلتر هوشمند پشتیبانی نمی‌شود")

    return await compile_node(tree)


@router.get("/users")
async def users_table(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    q: str | None = Query(None),
    intake: str | None = Query(None),
    group: str | None = Query(None),
    status: str | None = Query(None),   # pending | suspended | active
    role: str | None = Query(None, max_length=80),
    activity: str | None = Query(None, pattern="^(never|inactive_14|inactive_30)$"),
    accuracy_max: float | None = Query(None, ge=0, le=100),
    sub_expiring_days: int | None = Query(None, ge=1, le=365),
    has_open_ticket: bool | None = Query(None),
    smart: str | None = Query(None, max_length=8000),
    sort_by: str = Query("registered_at", pattern="^(registered_at|last_active|name|total_answers|correct_answers|streak_current|ai_total_usage)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    user=Depends(_perm_any("users.view", "users.manage")),
):
    """جدول حرفه‌ای کاربران با pagination/filter/sort کاملاً سرورساید.

    enrichmentهای نقش، اشتراک، تیکت و تعداد آزمون برای همان صفحه به‌شکل
    batch خوانده می‌شوند؛ هیچ query به‌ازای هر ردیف و هیچ full dataset fetch
    در پاسخ وجود ندارد.
    """
    filt = db.build_user_search_query(q) if q else {}
    smart = smart if isinstance(smart, str) else None
    smart_filter = await _compile_user_smart_query(smart)
    if smart_filter:
        filt = {"$and": [filt, smart_filter]} if filt else {"$and": [smart_filter]}
    if intake:
        filt["intake"] = intake
    if group:
        filt["group"] = db.normalize_group(group)
    if status == "pending":
        filt["approved"] = False
    elif status == "suspended":
        filt["suspended"] = True
    elif status == "active":
        filt["approved"] = True
        filt["suspended"] = {"$ne": True}
    if role:
        role_ids = await db.user_ids_by_role(role, limit=100000)
        # users.role فقط mirror سازگاری است؛ user_ids_by_role هر سه منبع را
        # deduplicate می‌کند و منطق RBAC موازی نمی‌سازد.
        filt["user_id"] = {"$in": role_ids}
    now = now_utc()
    if activity == "never":
        filt["$and"] = filt.get("$and", []) + [{"$or": [
            {"last_active": {"$exists": False}}, {"last_active": None},
            {"last_active": ""},
        ]}]
    elif activity in ("inactive_14", "inactive_30"):
        days = 14 if activity == "inactive_14" else 30
        cutoff = (now - timedelta(days=days)).isoformat()
        filt["$and"] = filt.get("$and", []) + [{"$or": [
            {"last_active": {"$lt": cutoff}}, {"last_active": {"$exists": False}},
        ]}]
    if accuracy_max is not None:
        filt["$expr"] = {"$lte": [
            {"$cond": [
                {"$gt": [{"$ifNull": ["$total_answers", 0]}, 0]},
                {"$multiply": [
                    {"$divide": [
                        {"$ifNull": ["$correct_answers", 0]},
                        {"$ifNull": ["$total_answers", 1]},
                    ]}, 100,
                ]},
                0,
            ]},
            accuracy_max,
        ]}
    if sub_expiring_days is not None:
        sub_ids = await db.subscriptions.distinct("_id", {
            "status": "active", "end_date": {
                "$gte": now.isoformat(),
                "$lte": (now + timedelta(days=sub_expiring_days)).isoformat(),
            },
        })
        existing_ids = (filt.get("user_id") or {}).get("$in")
        filt["user_id"] = {"$in": ([i for i in sub_ids if i in set(existing_ids)]
                                      if existing_ids is not None else sub_ids)}
    if has_open_ticket is not None:
        ticket_ids = await db.tickets.distinct("user_id", {"status": "open"})
        existing_ids = (filt.get("user_id") or {}).get("$in")
        if has_open_ticket:
            filt["user_id"] = {"$in": ([i for i in ticket_ids if i in set(existing_ids)]
                                          if existing_ids is not None else ticket_ids)}
        elif existing_ids is not None:
            ticket_set = set(ticket_ids)
            filt["user_id"] = {"$in": [i for i in existing_ids if i not in ticket_set]}
        else:
            filt["user_id"] = {"$nin": ticket_ids}

    total = await db.users.count_documents(filt)
    projection = {
        "user_id": 1, "name": 1, "nickname": 1, "username": 1, "student_id": 1,
        "group": 1, "intake": 1, "role": 1, "approved": 1, "suspended": 1,
        "registered_at": 1, "last_active": 1, "total_answers": 1,
        "correct_answers": 1, "prestige_rank": 1, "prestige_div": 1,
        "streak_current": 1, "ai_total_usage": 1,
    }
    docs = await (db.users.find(filt, projection)
                  .sort(sort_by, 1 if sort_dir == "asc" else -1)
                  .skip((page - 1) * per_page).limit(per_page).to_list(per_page))
    ids = [u.get("user_id") for u in docs if u.get("user_id") is not None]
    if ids:
        role_docs, sub_docs, open_docs, exam_counts = await asyncio.gather(
            db.user_roles.find({"_id": {"$in": ids}}, {"roles": 1, "scope_intake": 1}).to_list(per_page),
            db.subscriptions.find({"_id": {"$in": ids}}, {
                "status": 1, "plan_name": 1, "end_date": 1,
            }).to_list(per_page),
            db.tickets.find({"user_id": {"$in": ids}, "status": "open"}, {"user_id": 1}).to_list(500),
            db.exam_sessions.aggregate([
                {"$match": {"user_id": {"$in": ids}}},
                {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
            ]).to_list(per_page),
        )
    else:
        role_docs, sub_docs, open_docs, exam_counts = [], [], [], []
    role_map = {r.get("_id"): r for r in role_docs}
    sub_map = {s.get("_id"): s for s in sub_docs}
    open_set = {t.get("user_id") for t in open_docs}
    exam_map = {e.get("_id"): int(e.get("count") or 0) for e in exam_counts}

    rows = []
    for u in docs:
        uid = u.get("user_id")
        total_answers = int(u.get("total_answers") or 0)
        correct = int(u.get("correct_answers") or 0)
        sub = sub_map.get(uid) or {}
        days_left = None
        if sub.get("status") == "active" and sub.get("end_date"):
            try:
                days_left = remaining_days(sub["end_date"], now=now)
            except (TypeError, ValueError):
                days_left = None
        roles = list((role_map.get(uid) or {}).get("roles") or [])
        if not roles and u.get("role") not in (None, "", "student"):
            roles = [u.get("role")]
        rows.append({
            "id": uid, "name": u.get("name", ""), "nickname": u.get("nickname"),
            "username": u.get("username", ""), "display_name": db.display_name_of(u),
            "student_id": u.get("student_id", ""), "group": u.get("group", ""),
            "intake": u.get("intake", ""), "role": u.get("role", "student"),
            "roles": roles, "role_scope": (role_map.get(uid) or {}).get("scope_intake"),
            "approved": u.get("approved", False), "suspended": u.get("suspended", False),
            "registered_at": u.get("registered_at") or None,
            "last_active": u.get("last_active") or None,
            "total_answers": total_answers, "correct_answers": correct,
            "accuracy": round(correct * 100 / total_answers, 1) if total_answers else 0,
            "rank": u.get("prestige_rank", ""), "div": u.get("prestige_div", ""),
            "streak": int(u.get("streak_current") or 0),
            "ai_usage": int(u.get("ai_total_usage") or 0),
            "exam_count": exam_map.get(uid, 0), "has_open_ticket": uid in open_set,
            "subscription": {
                "status": sub.get("status", ""), "plan": sub.get("plan_name", ""),
                "end_date": sub.get("end_date") or None, "days_left": days_left,
            } if sub else None,
        })
    return {
        "total": total, "page": page, "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "users": rows,
    }


@router.get("/exports/users.csv")
async def export_users_csv(
    q: str | None = Query(None), intake: str | None = Query(None),
    group: str | None = Query(None), status: str | None = Query(None),
    role: str | None = Query(None), activity: str | None = Query(None),
    accuracy_max: float | None = Query(None, ge=0, le=100),
    sub_expiring_days: int | None = Query(None, ge=1, le=365),
    has_open_ticket: bool | None = Query(None), smart: str | None = Query(None, max_length=8000),
    sort_by: str = Query("registered_at"), sort_dir: str = Query("desc"),
    human: bool = False,
    user=Depends(_perm_any("users.view", "users.manage")),
):
    """CSV streaming برای dataset بزرگ؛ مرورگر هرگز همه کاربران را در RAM نمی‌گیرد."""
    await rate_limit_user(user["id"], "export_users_csv", 10, 60)  # 🛡 W10
    smart = smart if isinstance(smart, str) else None
    allowed_sort = {"registered_at", "last_active", "name", "total_answers", "correct_answers", "streak_current", "ai_total_usage"}
    if sort_by not in allowed_sort or sort_dir not in ("asc", "desc"):
        raise HTTPException(422, "مرتب‌سازی نامعتبر است")
    if activity not in (None, "", "never", "inactive_14", "inactive_30"):
        raise HTTPException(422, "فیلتر فعالیت نامعتبر است")
    await _audit(user["id"], "خروجی CSV کاربران", severity="HIGH",
                 target_type="export", target_label="users.csv",
                 after={"filtered": bool(any([q, intake, group, status, role, activity,
                                                accuracy_max is not None, sub_expiring_days,
                                                has_open_ticket is not None, smart]))},
                 tags=["خروجی", "کاربران", "پنل_وب"])
    columns = ["telegram_id", "name", "nickname", "username", "student_id", "intake", "group",
               "status", "roles", "subscription", "subscription_end", "accuracy", "total_answers",
               "exam_count", "ai_usage", "streak", "rank", "last_active", "registered_at"]

    def safe(value):
        text = "" if value is None else str(value)
        return "'" + text if text[:1] in ("=", "+", "-", "@") else text

    async def stream():
        buf = io.StringIO(); writer = csv.writer(buf)
        writer.writerow(columns)
        yield "\ufeff" + buf.getvalue(); buf.seek(0); buf.truncate(0)
        page = 1
        while True:
            result = await users_table(
                page=page, per_page=100, q=q, intake=intake, group=group, status=status,
                role=role, activity=activity, accuracy_max=accuracy_max,
                sub_expiring_days=sub_expiring_days, has_open_ticket=has_open_ticket, smart=smart,
                sort_by=sort_by, sort_dir=sort_dir, user=user,
            )
            rows = result.get("users") or []
            for row in rows:
                sub = row.get("subscription") or {}
                writer.writerow([safe(v) for v in [
                    row.get("id"), row.get("name"), row.get("nickname"), row.get("username"),
                    row.get("student_id"), row.get("intake"), row.get("group"),
                    "suspended" if row.get("suspended") else "active" if row.get("approved") else "pending",
                    "|".join(row.get("roles") or []), sub.get("status"), _export_instant(sub.get("end_date"), human),
                    row.get("accuracy"), row.get("total_answers"), row.get("exam_count"),
                    row.get("ai_usage"), row.get("streak"),
                    " / ".join(x for x in [row.get("rank"), row.get("div")] if x),
                    _export_instant(row.get("last_active"), human),
                    _export_instant(row.get("registered_at"), human),
                ]])
                yield buf.getvalue(); buf.seek(0); buf.truncate(0)
            if page >= int(result.get("pages") or 1) or not rows:
                break
            page += 1

    return StreamingResponse(stream(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=humsyar-users.csv"})


@router.post("/users/bulk/preview")
async def users_bulk_preview(body: BulkBody, user=Depends(_guard_any_admin)):
    """🔍 §۸۷ — پیش‌نمایش عملیات گروهی (dry-run کاملاً بدون نوشتن).

    برای Broadcast از قبل پیش‌نمایش وجود داشت، ولی تغییرِ انبوهِ کاربران —
    که برگشت‌ناپذیرتر است — بدون آن اجرا می‌شد. اینجا *همان* گیت مجوز و
    *همان* قواعدِ skip بازاجرا می‌شود، فقط هیچ نوشتنی رخ نمی‌دهد.

    خروجی سه سطل است: `will_apply` / `will_skip` / `not_found` تا ادمین
    پیش از زدنِ دکمه بداند دقیقاً روی چند نفر اثر می‌گذارد.
    """
    await rate_limit_user(user["id"], "bulk_preview", 10, 60)  # 🛡 W10
    action_perm = _BULK_ACTION_PERM
    need = action_perm.get(body.action)
    if not need:
        raise HTTPException(400, "اکشن نامعتبر است.")
    if not await db.has_permission(user["id"], need):
        raise HTTPException(403, "forbidden")

    ids = list(dict.fromkeys(
        int(i) for i in (body.ids or [])
        if isinstance(i, (int, str)) and str(i).isdigit()
    ))[:100]
    if not ids:
        raise HTTPException(400, "لیست کاربران خالی است.")
    value = (body.value or "").strip()
    if body.action in ("set_intake", "set_group", "add_role", "remove_role",
                       "message", "block") and not value:
        raise HTTPException(422, "مقدار عملیات گروهی الزامی است")
    if body.action in ("add_role", "remove_role") and not await db.get_role(value):
        raise HTTPException(422, "نقش ناشناخته است")

    will_apply, will_skip, not_found = [], [], []
    # 🗄 W4/PERF-01 — دو کوئری بچ به‌جای N+1 (رفتار skipها عیناً حفظ می‌شود)
    _users = await db.get_users_by_ids(ids)
    _need_roles = body.action in ("add_role", "remove_role")
    _roles = await db.get_users_roles_keys(ids) if _need_roles else {}
    for uid in ids:
        if uid == ADMIN_ID and body.action in ("suspend", "remove_role", "block"):
            will_skip.append({"id": uid, "reason": "owner_protected"}); continue
        target = _users.get(uid)
        if not target:
            not_found.append({"id": uid, "reason": "user_not_found"}); continue
        label = target.get("name") or str(uid)
        reason = None
        if body.action == "approve" and target.get("approved") and not target.get("suspended"):
            reason = "already_approved"
        elif body.action == "suspend" and target.get("suspended"):
            reason = "already_suspended"
        elif body.action == "unsuspend" and not target.get("suspended"):
            reason = "not_suspended"
        elif body.action == "set_intake" and (target.get("intake") or "") == value:
            reason = "already_set"
        elif body.action == "add_role" and value in (_roles.get(uid) or []):
            reason = "already_has_role"
        elif body.action == "remove_role" and value not in (_roles.get(uid) or []):
            reason = "role_not_assigned"
        if reason:
            will_skip.append({"id": uid, "name": label, "reason": reason})
        else:
            will_apply.append({"id": uid, "name": label})

    # 🛡 §۸۵ — عملیات گروهیِ نقش هم می‌تواند سیستم را قفل کند.
    lockout = []
    if body.action == "remove_role":
        for row in will_apply:
            risk = await db.assignment_lockout_risk(row["id"], [], [value])
            if risk["blocked"]:
                lockout.append({"id": row["id"], "perms": risk["perms"]})

    return {"ok": True, "action": body.action, "value": value,
            "total": len(ids), "will_apply": will_apply,
            "will_skip": will_skip, "not_found": not_found,
            "lockout_risk": lockout,
            "counts": {"apply": len(will_apply), "skip": len(will_skip),
                       "missing": len(not_found)}}


@router.post("/users/bulk")
async def users_bulk(body: BulkBody, user=Depends(_guard_any_admin)):
    """اکشن گروهی کاربران با گزارش success/failed/skipped و سقف ۱۰۰.

    تغییر نقش از همان تابع RBAC و پیام از همان outbox موجود استفاده می‌کند؛
    این endpoint orchestration وب است، نه business logic موازی.
    """
    need = _BULK_ACTION_PERM.get(body.action)
    if not need:
        raise HTTPException(400, "اکشن نامعتبر است.")
    actor = user["id"]
    if not await db.has_permission(actor, need):
        raise HTTPException(403, "forbidden")
    ids = list(dict.fromkeys(
        int(i) for i in (body.ids or [])
        if isinstance(i, (int, str)) and str(i).isdigit()
    ))[:100]
    if not ids:
        raise HTTPException(400, "لیست کاربران خالی است.")
    succeeded, skipped, failed = [], [], []
    granted: list[dict] = []
    value = (body.value or "").strip()
    # 🗄 W4/PERF-01 — دو کوئری بچ به‌جای N+1 (نوشتن‌ها تکی می‌ماند تا
    # گزارش success/failed/skipped دقیق بماند)
    _users = await db.get_users_by_ids(ids)
    _need_roles = body.action in ("add_role", "remove_role")
    _roles = await db.get_users_roles_keys(ids) if _need_roles else {}
    # 🛡 AUDIT-§۷۹ — اشتراک گروهی: فقط orchestration؛ نوشتنِ واقعی با همان
    # endpoint تک‌موردیِ مالی است (op_claim + sub_activate + نوتیف + audit).
    sub_extend = None
    sub_days = sub_plan = None
    if body.action in ("grant_subscription", "renew_subscription"):
        sub_extend = (body.extend if body.extend is not None
                      else body.action == "renew_subscription")
        try:
            sub_days = int(body.days if body.days else (value or 0))
        except (TypeError, ValueError):
            raise HTTPException(422, "تعداد روز باید عدد صحیح باشد.")
        if not (1 <= int(sub_days) <= 3650):
            raise HTTPException(422, "تعداد روز نامعتبر است (۱ تا ۳۶۵۰ روز).")
        sub_plan = (body.plan_name or "").strip()[:100] or "اشتراک دستی"
    if body.action in ("set_intake", "set_group", "add_role", "remove_role", "message", "block") and not value:
        raise HTTPException(422, "مقدار عملیات گروهی الزامی است")
    if body.action in ("add_role", "remove_role") and not await db.get_role(value):
        raise HTTPException(422, "نقش ناشناخته است")

    for uid in ids:
        if uid == ADMIN_ID and body.action in ("suspend", "remove_role", "block"):
            skipped.append({"id": uid, "reason": "owner_protected"})
            continue
        target = _users.get(uid)
        if not target:
            skipped.append({"id": uid, "reason": "user_not_found"})
            continue
        try:
            if body.action == "approve":
                if target.get("approved") and not target.get("suspended"):
                    skipped.append({"id": uid, "reason": "already_approved"}); continue
                await db.update_user(uid, {"approved": True, "suspended": False})
                await db.inbox_add(uid, 'account', "✅ حسابت تأیید شد!",
                    "اکنون به تمام بخش‌های هامزیار دسترسی داری — خوش اومدی! 🎓", link='/')
            elif body.action == "suspend":
                if target.get("suspended"):
                    skipped.append({"id": uid, "reason": "already_suspended"}); continue
                await db.update_user(uid, {"suspended": True, "approved": False})
            elif body.action == "unsuspend":
                if not target.get("suspended"):
                    skipped.append({"id": uid, "reason": "not_suspended"}); continue
                await db.update_user(uid, {"suspended": False, "approved": True})
            elif body.action == "set_intake":
                if (target.get("intake") or "") == value:
                    skipped.append({"id": uid, "reason": "unchanged"}); continue
                await db.update_user(uid, {"intake": value})
            elif body.action == "set_group":
                normalized = db.normalize_group(value)
                if (target.get("group") or "") == normalized:
                    skipped.append({"id": uid, "reason": "unchanged"}); continue
                await db.update_user(uid, {"group": normalized})
            elif body.action in ("add_role", "remove_role"):
                has_role = value in (_roles.get(uid) or [])
                if (body.action == "add_role" and has_role) or (body.action == "remove_role" and not has_role):
                    skipped.append({"id": uid, "reason": "unchanged"}); continue
                payload = rbac_api.AssignBody(
                    add=[value] if body.action == "add_role" else [],
                    remove=[value] if body.action == "remove_role" else [],
                )
                await rbac_api.assign_roles(uid=uid, body=payload, user=user)
            elif body.action == "message":
                await wa_user_message(uid=uid, body=DmIn(text=value), user=user)
            elif body.action == "block":
                await wa_user_action(uid=uid, body=UserActionIn(action="block", reason=value), user=user)
            elif body.action in ("grant_subscription", "renew_subscription"):
                r = await subscription_api.grant_subscription(
                    body=subscription_api.GrantBody(
                        user_id=uid, days=int(sub_days), plan_name=sub_plan, extend=bool(sub_extend)),
                    admin=user)
                granted.append({"id": uid, "end_date": (r or {}).get("end_date")})
            succeeded.append(uid)
        except HTTPException as exc:
            failed.append({"id": uid, "error": str(exc.detail or "operation_failed")[:160]})
        except Exception:
            failed.append({"id": uid, "error": "operation_failed"})

    labels = {
        "approve": "تأیید گروهی", "suspend": "تعلیق گروهی",
        "unsuspend": "رفع تعلیق گروهی", "set_intake": "تغییر ورودی گروهی",
        "set_group": "تغییر گروه گروهی", "add_role": "افزودن نقش گروهی",
        "remove_role": "حذف نقش گروهی", "message": "پیام گروهی انتخابی",
        "block": "مسدودسازی گروهی",
        "grant_subscription": "اعطای گروهی اشتراک", "renew_subscription": "تمدید گروهی اشتراک",
    }
    await _audit(
        actor, f"{labels[body.action]} کاربران ({len(succeeded)} موفق)",
        severity="CRITICAL" if body.action == "block" else "HIGH" if body.action in ("suspend", "remove_role", "grant_subscription", "renew_subscription") else "INFO",
        target_type="user_batch", target_label=f"{len(ids)} کاربر",
        after={"action": body.action, "requested": len(ids),
               "succeeded": len(succeeded), "failed": len(failed), "skipped": len(skipped),
               **({"days": int(sub_days), "plan": sub_plan, "extend": bool(sub_extend)}
                  if body.action in ("grant_subscription", "renew_subscription") else {})},
        tags=["bulk_users", "اشتراک", "پنل_وب"] if body.action in
        ("grant_subscription", "renew_subscription") else ["bulk_users", "پنل_وب"],
    )
    out = {"ok": not failed, "done": len(succeeded), "succeeded": succeeded,
           "failed": failed, "skipped": skipped,
           "action": body.action, "value": value or None}
    if body.action in ("grant_subscription", "renew_subscription"):
        out["granted"] = granted
        out["days"] = int(sub_days)
        out["plan_name"] = sub_plan
        out["extend"] = bool(sub_extend)
    return out


# ══════════════════════════════════════════════════════════════════
# 🌊 WA2.7 — «نیازمند اقدام» + فید فعالیت واقعی
# ══════════════════════════════════════════════════════════════════

@router.get("/attention")
async def attention(user=Depends(_guard_any_admin)):
    """صف‌های اقدام permission-aware؛ شمارش خارج از دسترسی حتی برگردانده نمی‌شود."""
    perms = await db.get_user_perms(user["id"])
    allow = lambda *keys: user["id"] == ADMIN_ID or any(k in perms for k in keys)
    jobs, time_jobs = {}, {}
    async def latest_at(collection, query, *fields):
        docs = await collection.find(query).sort(fields[0], -1).limit(1).to_list(1)
        row = docs[0] if docs else {}
        return next((row.get(field) for field in fields if row.get(field)), None)
    if allow("users.view", "users.manage"):
        query = {"approved": False, "suspended": {"$ne": True}}
        jobs["users"] = db.users.count_documents(query)
        time_jobs["users"] = latest_at(db.users, query, "registered_at")
    if allow("subscription.manage"):
        query = {"status": "pending"}
        jobs["payments"] = db.sub_payment_count_all("pending")
        time_jobs["payments"] = latest_at(db.sub_payments, query, "submitted_at", "created_at")
    if allow("questions.review", "questions.review_scoped"):
        query = {"approved": False}
        jobs["questions"] = db.questions.count_documents(query)
        time_jobs["questions"] = latest_at(db.questions, query, "created_at")
    if allow("tickets.reply", "tickets.manage"):
        query = {"status": "open"}
        jobs["tickets"] = db.tickets.count_documents(query)
        time_jobs["tickets"] = latest_at(db.tickets, query, "created_at")
    if allow("reports.review"):
        query = {"status": {"$in": ["new", "pending", "reviewing"]}}
        jobs["reports"] = db.content_reports.count_documents(query)
        time_jobs["reports"] = latest_at(db.content_reports, query, "created_at")
    if allow("notifications.manage", "system.manage"):
        async def failed_jobs_metric(kind):
            # 🌊 W5 — «اجرای دارای خطا» باید actionable بماند: خطای تاریخِ
            # خیلی قدیمی نباید کارت را برای همیشه قرمز نگه دارد (شمارش
            # قبلی ۲۰ اجرای اخیر را بی‌بازه می‌شمرد). پنجره‌ی ۲۴ ساعته +
            # کارت‌های outbox/DLQ برای backlog واقعی.
            runs = await db.get_recent_notif_runs(limit=20)
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            failed = []
            for run in runs:
                if int(run.get("failed") or 0) <= 0:
                    continue
                at_raw = run.get("started_at") or run.get("created_at")
                try:
                    fresh = parse_machine_datetime(at_raw) >= cutoff
                except (TypeError, ValueError):
                    fresh = True
                if fresh:
                    failed.append(run)
            return len(failed) if kind == "count" else ((failed[0].get("started_at") or failed[0].get("created_at")) if failed else None)
        jobs["failed_jobs"] = failed_jobs_metric("count")
        time_jobs["failed_jobs"] = failed_jobs_metric("time")

        # 🌊 WA21 — سه صفِ پیام ربات که تا اینجا هیچ‌کس آن‌ها را نمی‌دید.
        # مصرف‌کننده‌ی outbox در bot.py است؛ اگر ربات پایین باشد یا تلگرام
        # reject کند، پیام‌ها در `bot_notifications` می‌مانند و تنها نشانه‌شان
        # همین شمارش‌هاست. منبع داده موجود است ⇒ کالکشن جدید ساخته نمی‌شود.
        backlog_q = {"sent": False,
                     "$or": [{"send_at": {"$exists": False}}, {"send_at": None}]}
        jobs["outbox_backlog"] = db.bot_notifs.count_documents(backlog_q)
        time_jobs["outbox_backlog"] = latest_at(db.bot_notifs, backlog_q, "created_at")

        scheduled_q = {"sent": False, "send_at": {"$exists": True, "$ne": None}}
        jobs["outbox_scheduled"] = db.bot_notifs.count_documents(scheduled_q)
        time_jobs["outbox_scheduled"] = latest_at(db.bot_notifs, scheduled_q, "send_at")

        # DLQ: اسنادی که پس از سقف تلاش `status="dead"` شده‌اند. `sent=True`
        # دارند، پس از شمارش backlog بیرون می‌افتند و بی‌صدا گم می‌شوند.
        dead_q = {"status": "dead"}
        jobs["dlq"] = db.bot_notifs.count_documents(dead_q)
        time_jobs["dlq"] = latest_at(db.bot_notifs, dead_q, "sent_at", "created_at")

    if allow("questions.import"):
        # 🌊 WA21 — درون‌ریزی نیمه‌تمام: jobهایی که preview آماده شده ولی
        # ادمین confirm/cancel نکرده است. بدون این کارت، job تا ابد معلق می‌ماند.
        import_q = {"status": {"$in": ["preview_ready", "validated", "importing"]}}
        jobs["imports"] = db.question_import_jobs.count_documents(import_q)
        time_jobs["imports"] = latest_at(db.question_import_jobs, import_q,
                                         "created_at", "validated_at")
    keys = list(jobs)
    values, time_values = await asyncio.gather(
        asyncio.gather(*(jobs[k] for k in keys), return_exceptions=True),
        asyncio.gather(*(time_jobs[k] for k in keys), return_exceptions=True))
    counts = {k: (0 if isinstance(v, Exception) else int(v or 0)) for k, v in zip(keys, values)}
    timestamps = {k: (None if isinstance(v, Exception) else v) for k, v in zip(keys, time_values)}
    meta = {
        "payments": ("🧾", "رسید پرداخت در انتظار بررسی", "/subscriptions?tab=payments", "warning"),
        "tickets": ("🎫", "تیکت بدون پاسخ", "/tickets?status=open", "warning"),
        "questions": ("🧪", "سؤال در انتظار بازبینی", "/questions?status=pending", "warning"),
        "users": ("🧑‍🎓", "کاربر در انتظار تأیید", "/users?status=pending", "warning"),
        "reports": ("🚩", "گزارش محتوا/سؤال در انتظار", "/content?tab=reports", "warning"),
        "failed_jobs": ("⚙️", "اجرای اعلان دارای خطا", "/system", "critical"),
        # 🌊 WA21 — مقصد هر کارت جایی است که واقعاً همان صف را نشان می‌دهد؛
        # `?focus=` در System.jsx و `?tab=` در Operations.jsx مصرف می‌شود.
        "outbox_backlog": ("📤", "پیام در صف خروجی ربات", "/system?focus=outbox", "warning"),
        "outbox_scheduled": ("⏰", "پیام زمان‌بندی‌شده‌ی ارسال‌نشده", "/system?focus=outbox", "info"),
        "dlq": ("💀", "پیام مرده — هرگز تحویل نشده", "/system?focus=dlq", "critical"),
        "imports": ("📥", "درون‌ریزی منتظر تأیید", "/questions?tab=import", "warning"),
    }
    checked_at = _now()
    items = [{"key": k, "icon": meta[k][0], "label": meta[k][1],
              "count": counts.get(k, 0), "go": meta[k][2], "severity": meta[k][3],
              "timestamp": timestamps.get(k), "urgent": counts.get(k, 0) > 0}
             for k in meta if k in counts]

    # 🌊 WA21 — کارت کیفیت داده. عمداً خارج از gather بالا: این ۱۲ بررسی
    # $lookup دارند و نباید هر بار که داشبورد باز می‌شود موازی با بقیه صف‌ها
    # اجرا شوند. نتیجه یک dict خلاصه است، نه یک عدد، تا UI بتواند تفکیک
    # critical/warning را نشان دهد. خطای هر بررسی بقیه را نمی‌کُشد.
    if allow("system.manage"):
        quality = await _quality_summary()
        items.append({
            "key": "data_quality", "icon": "🧬",
            "label": "ناهنجاری کیفیت داده",
            "count": quality["count"], "go": "/operations?tab=quality",
            "severity": "critical" if quality["critical"] else (
                "warning" if quality["count"] else "info"),
            "timestamp": checked_at, "urgent": quality["count"] > 0,
            "detail": quality,
        })
    # 💰 W6 — مغایرت مالی کیف پول (§۶۴): ledger حساب را لو نمی‌دهد؛
    # موارد بحرانی یعنی پول ناهم‌خوان است. دیپ‌لینک به مغایرت‌گیری که همان
    # موارد human-readable + اقدام امن دارند. خارج از gather بالا:
    # aggregate دارد و نباید با صف‌های سبک موازی شود.
    if allow("subscription.manage"):
        witems = await db.wallet_reconcile_items()
        wcrit = [i for i in witems if i.get("severity") == "critical"]
        wats = [i.get("at") for i in wcrit if i.get("at")]
        items.append({
            "key": "wallet_issues", "icon": "👛",
            "label": "مغایرت مالی کیف پول",
            "count": len(wcrit), "go": "/subscriptions?tab=reconcile",
            "severity": "critical" if wcrit else "info",
            "timestamp": max(wats) if wats else checked_at,
            "urgent": bool(wcrit),
        })
    backup = None
    if allow("backup.manage", "settings.manage", "system.manage"):
        last_run = await db.get_setting("auto_backup_last_run", None)
        enabled = bool(await db.get_setting("auto_backup_enabled", False))
        backup = {"last_run": last_run, "enabled": enabled}
        stale = not enabled or not last_run
        if enabled and last_run:
            try: stale = parse_machine_datetime(last_run) < now_utc() - timedelta(hours=48)
            except (TypeError, ValueError): stale = True
        if stale:
            items.append({"key": "backup_issue", "icon": "💾",
                          "label": "پشتیبان‌گیری نیازمند بررسی است", "count": 1,
                          "go": "/system", "severity": "critical",
                          "timestamp": last_run or checked_at, "urgent": True})
    # 🌊 W7 — dismissed items: هشدار نادرست / اسپم را ادمین با دلیل می‌بندد
    try:
        dcol = db.client["medicalbot"]["attention_dismissals"]
        ddocs = await dcol.find({}).to_list(100)
        now = now_utc()
        dmap = {}
        for d in ddocs:
            until = d.get("dismissed_until")
            if until:
                try:
                    if parse_machine_datetime(until) < now:
                        continue
                except Exception:
                    pass
            kk = d.get("key") or ""
            if kk:
                dmap[kk] = d
        for it in items:
            dd = dmap.get(it["key"])
            if dd:
                it["dismissed"] = True
                it["dismiss_reason"] = dd.get("reason", "")
                it["dismissed_at"] = dd.get("dismissed_at")
                it["dismissed_until"] = dd.get("dismissed_until")
                it["dismissed_by"] = dd.get("dismissed_by")
                it["urgent"] = False
                # خاکستری‌کردن: severity فقط برای رنگ؛ dismissed باید info باشد
                if it.get("severity") in ("critical", "warning"):
                    it["_orig_severity"] = it["severity"]
                    it["severity"] = "info"
            else:
                it["dismissed"] = False
    except Exception as e:
        logger.warning(f"attention dismiss enrich failed: {e}")
        for it in items:
            it.setdefault("dismissed", False)
    return {"items": items, "backup": backup, "checked_at": checked_at}



# ══════════════════════════════════════════════════════════════════
# 🌊 W7 — «نیازمند اقدام» قابل‌بستن + مدیریت اسپم کیف پول
# هر کارت می‌تواند با دلیل و بازه (۲۴/۷۲/۱۶۸h یا دائم) بسته شود؛
# تا پایان بازه urgent=False و grey-out می‌شود و در bot اسپم نمی‌کند.
# ══════════════════════════════════════════════════════════════════

class AttentionDismissBody(BaseModel):
    key: str = Field(..., min_length=1, max_length=64)
    reason: str = Field(..., min_length=3, max_length=300)
    dismiss_hours: int = Field(24, ge=0, le=720, description="0=دائم")

class AttentionRestoreBody(BaseModel):
    key: str = Field(..., min_length=1, max_length=64)

@router.get("/attention/dismissals")
async def attention_dismissals(user=Depends(_guard_any_admin)):
    dcol = db.client["medicalbot"]["attention_dismissals"]
    docs = await dcol.find({}).to_list(100)
    return {"items": [{"key": d.get("key"), "reason": d.get("reason"), "dismissed_at": d.get("dismissed_at"), "dismissed_until": d.get("dismissed_until"), "dismissed_by": d.get("dismissed_by")} for d in docs]}

@router.post("/attention/dismiss")
async def attention_dismiss(body: AttentionDismissBody, user=Depends(_guard_any_admin)):
    key = body.key.strip()
    reason = body.reason.strip()
    # اعتبارسنجی کلید: باید جزو کلیدهای attention باشد (جلوگیری از کلید فیک)
    allowed_keys = {"users","payments","questions","tickets","reports","failed_jobs","outbox_backlog","outbox_scheduled","dlq","imports","data_quality","wallet_issues","backup_issue"}
    if key not in allowed_keys:
        raise HTTPException(422, "کلید نیازمند اقدام نامعتبر است")
    until = None
    if body.dismiss_hours and body.dismiss_hours > 0:
        until = (now_utc() + timedelta(hours=body.dismiss_hours)).isoformat()
    dcol = db.client["medicalbot"]["attention_dismissals"]
    await dcol.update_one({"key": key}, {"$set": {"key": key, "reason": reason, "dismissed_at": _now(), "dismissed_until": until, "dismissed_by": user["id"], "dismissed_by_name": (user.get("_db") or {}).get("name","")}}, upsert=True)
    await _audit(user["id"], f"بستن هشدار نیازمند اقدام: {key}", severity="WARNING", target_type="attention", target_id=key, target_label=reason[:80], after={"key": key, "reason": reason, "until": until}, tags=["نیازمند_اقدام","بستن_هشدار","پنل_وب"])
    return {"ok": True, "key": key, "dismissed_until": until}

@router.post("/attention/restore")
async def attention_restore(body: AttentionRestoreBody, user=Depends(_guard_any_admin)):
    key = body.key.strip()
    dcol = db.client["medicalbot"]["attention_dismissals"]
    res = await dcol.delete_one({"key": key})
    if not res.deleted_count:
        raise HTTPException(404, "این هشدار بسته نشده است")
    await _audit(user["id"], f"بازکردن هشدار نیازمند اقدام: {key}", severity="INFO", target_type="attention", target_id=key, tags=["نیازمند_اقدام","بازکردن_هشدار","پنل_وب"])
    return {"ok": True, "key": key}

class WalletAlertSettingsBody(BaseModel):
    enabled: Optional[bool] = None
    cooldown_hours: Optional[int] = Field(None, ge=1, le=168)
    muted_until: Optional[str] = None

@router.get("/system/wallet-alerts")
async def wallet_alert_settings_get(user=Depends(_guard_any_admin)):
    enabled = await db.get_setting("wallet_alert_enabled", None)
    if enabled is None:
        enabled = True
    cooldown = await db.get_setting("wallet_alert_cooldown_hours", None)
    if cooldown is None:
        cooldown = 6
    muted = await db.get_setting("wallet_alert_muted_until", None)
    # همچنین وضعیت dismiss فعلی wallet_issues برای نمایش یکپارچه
    ddoc = await db.client["medicalbot"]["attention_dismissals"].find_one({"key": "wallet_issues"})
    return {"enabled": bool(enabled), "cooldown_hours": int(cooldown), "muted_until": muted, "dismiss": {"active": bool(ddoc and (not ddoc.get("dismissed_until") or ddoc.get("dismissed_until") > _now())), "reason": (ddoc or {}).get("reason"), "until": (ddoc or {}).get("dismissed_until")}}

@router.patch("/system/wallet-alerts")
async def wallet_alert_settings_patch(body: WalletAlertSettingsBody, user=Depends(_perm("system.manage"))):
    before = {}
    if body.enabled is not None:
        before["enabled"] = await db.get_setting("wallet_alert_enabled", True)
        await db.set_setting("wallet_alert_enabled", bool(body.enabled))
    if body.cooldown_hours is not None:
        before["cooldown_hours"] = await db.get_setting("wallet_alert_cooldown_hours", 6)
        await db.set_setting("wallet_alert_cooldown_hours", int(body.cooldown_hours))
    if body.muted_until is not None:
        before["muted_until"] = await db.get_setting("wallet_alert_muted_until", None)
        val = body.muted_until.strip() or None
        # اعتبارسنجی ISO اگر داده شد
        if val:
            try:
                parse_machine_datetime(val)
            except Exception:
                raise HTTPException(422, "زمان mute معتبر نیست")
        await db.set_setting("wallet_alert_muted_until", val)
    await _audit(user["id"], "تنظیم هشدار مغایرت کیف پول", severity="WARNING", target_type="wallet_alert", after=body.model_dump(exclude_none=True), before=before, tags=["کیف_پول","هشدار","پنل_وب"])
    return await wallet_alert_settings_get(user=user)


@router.get("/activity")
async def activity(limit: int = Query(40, ge=1, le=100),
                   user=Depends(_guard_any_admin)):
    """🕓 جریان فعالیت واقعی از audit_logs — با متادیتای کامل برای View Context."""
    logs = await db.get_recent_logs(limit=limit)
    out = []
    for l in logs:
        actor = l.get("actor") or {}
        out.append({
            "id": str(l.get("_id", "")),
            "at": l.get("timestamp") or None,
            "actor_id": actor.get("id"),
            "actor_name": actor.get("name", ""),
            "actor_role": actor.get("role", ""),
            "action": l.get("action", ""),
            "module": l.get("module", ""),
            "severity": l.get("severity", "INFO"),
            "target_type": l.get("target_type", ""),
            "target_id": l.get("target_id", ""),
            "target_label": l.get("target_label", ""),
            "tags": l.get("tags") or [],
        })
    return {"items": out}


@router.get("/dashboard-bundle")
async def dashboard_bundle(user=Depends(_guard_any_admin)):
    """یک round-trip برای صفحه اصلی؛ بخش‌های اختیاری permission-aware هستند."""
    uid = user["id"]
    perms = await db.get_user_perms(uid)
    base, attn = await asyncio.gather(overview(user=user), attention(user=user))
    insights = None
    feed = []
    owner_stats = None
    if uid == ADMIN_ID or "stats.view" in perms:
        try:
            insights = await db.admin_insights()
        except Exception:
            insights = None
    if uid == ADMIN_ID or "audit.view" in perms:
        try:
            feed = (await activity(limit=30, user=user)).get("items", [])
        except Exception:
            feed = []
    if uid == ADMIN_ID:
        try:
            owner_stats = await owner_api.stats(admin=user)
        except Exception:
            owner_stats = None
    return {"overview": base, "attention": attn, "activity": feed,
            "insights": insights, "stats": owner_stats}


# ══════════════════════════════════════════════════════════════════
# 👑 W24/W28 — Operations Hub: My Work, Alerts, Data Quality
# ══════════════════════════════════════════════════════════════════

async def _oldest_time(collection, query: dict, *fields):
    docs = await collection.find(query).sort(fields[0], 1).limit(1).to_list(1)
    row = docs[0] if docs else {}
    return next((row.get(field) for field in fields if row.get(field)), None)


@router.get("/operations/my-work")
async def wa_my_work(user=Depends(_guard_any_admin)):
    """صف کار واقعی مدیر جاری؛ هیچ task یا SLA ساختگی تولید نمی‌شود."""
    uid = user["id"]
    perms = await db.get_user_perms(uid)
    allow = lambda *keys: uid == ADMIN_ID or any(key in perms for key in keys)
    jobs, times, meta = {}, {}, {}
    if allow("tickets.reply", "tickets.manage"):
        query = {"assignee_id": uid, "status": {"$ne": "closed"}}
        jobs["assigned_tickets"] = db.tickets.count_documents(query)
        times["assigned_tickets"] = _oldest_time(db.tickets, query, "created_at")
        meta["assigned_tickets"] = ("🎫", "تیکت‌های تخصیص‌یافته به من", "/tickets?assignee=" + str(uid), "high")
    if allow("questions.review", "questions.review_scoped"):
        scope = await _question_scope_context(user)
        query = {"approved": False}
        if scope.get("kind") == "scoped": query["intake"] = scope.get("intake") or ""
        jobs["question_reviews"] = db.questions.count_documents(query)
        times["question_reviews"] = _oldest_time(db.questions, query, "created_at")
        meta["question_reviews"] = ("🧪", "سؤال‌های منتظر بازبینی", "/questions?status=pending", "normal")
    if allow("reports.review"):
        query = {"status": {"$in": ["new", "pending", "reviewing"]}}
        jobs["content_reports"] = db.content_reports.count_documents(query)
        times["content_reports"] = _oldest_time(db.content_reports, query, "created_at")
        meta["content_reports"] = ("🚩", "گزارش‌های محتوا", "/content?tab=reports", "normal")
    if allow("subscription.manage"):
        query = {"status": "pending"}
        jobs["payment_reviews"] = db.sub_payments.count_documents(query)
        times["payment_reviews"] = _oldest_time(db.sub_payments, query, "submitted_at", "created_at")
        meta["payment_reviews"] = ("🧾", "رسیدهای منتظر بررسی", "/subscriptions?tab=payments", "high")
    if allow("users.manage"):
        query = {"approved": False, "suspended": {"$ne": True}}
        jobs["user_approvals"] = db.users.count_documents(query)
        times["user_approvals"] = _oldest_time(db.users, query, "registered_at")
        meta["user_approvals"] = ("👤", "ثبت‌نام‌های منتظر تأیید", "/users?status=pending", "normal")
    keys = list(jobs)
    counts, oldest = await asyncio.gather(
        asyncio.gather(*(jobs[key] for key in keys), return_exceptions=True),
        asyncio.gather(*(times[key] for key in keys), return_exceptions=True),
    ) if keys else ([], [])
    tasks = []
    for key, count_value, time_value in zip(keys, counts, oldest):
        count = 0 if isinstance(count_value, Exception) else int(count_value or 0)
        at = None if isinstance(time_value, Exception) else time_value
        icon, label, go, urgency = meta[key]
        tasks.append({"key": key, "icon": icon, "label": label, "count": count,
                      "oldest_at": at, "go": go, "urgency": urgency,
                      "empty": count == 0})
    tasks.sort(key=lambda item: ({"high": 0, "normal": 1}.get(item["urgency"], 2),
                                 0 if item["count"] else 1, item.get("oldest_at") or ""))
    return {"tasks": tasks, "checked_at": _now()}


@router.get("/operations/alerts")
async def wa_alert_center(user=Depends(_guard_any_admin)):
    data = await attention(user=user)
    alerts = [item for item in data.get("items", []) if int(item.get("count") or 0) > 0]
    alerts.sort(key=lambda item: (0 if item.get("severity") == "critical" else 1,
                                  item.get("timestamp") or ""))
    return {"alerts": alerts, "checked_at": data.get("checked_at")}


_QUALITY_META = {
    "users_missing_intake": ("warning", "کاربر تأییدشده بدون ورودی", "تکمیل ورودی فقط پس از بررسی پرونده"),
    "users_invalid_intake": ("critical", "کاربر با ورودی نامعتبر", "تطبیق ورودی کاربر با رجیستری ورودی‌ها"),
    "duplicate_student_ids": ("critical", "شماره دانشجویی تکراری", "بررسی هویت پیش از هر اصلاح"),
    "invalid_role_refs": ("critical", "ارجاع به نقش نامعتبر", "بازبینی تخصیص نقش و حذف reference نامعتبر"),
    "orphan_sessions": ("critical", "جلسه بدون درس والد", "اتصال به درس معتبر یا حذف با تأیید"),
    "orphan_files": ("critical", "فایل بدون جلسه والد", "اتصال به جلسه معتبر یا حذف با تأیید"),
    "orphan_ref_books": ("critical", "کتاب رفرنس بدون موضوع والد", "اتصال به موضوع معتبر یا حذف با تأیید"),
    "orphan_ref_files": ("critical", "فایل رفرنس بدون کتاب والد", "اتصال به کتاب معتبر یا حذف با تأیید"),
    "orphan_subscriptions": ("critical", "اشتراک بدون کاربر", "بررسی زنجیره پرداخت و هویت پیش از اصلاح"),
    "orphan_payments": ("critical", "پرداخت بدون کاربر", "بررسی رسید و هویت پیش از اصلاح"),
    "malformed_questions": ("warning", "رکورد سؤال ناقص", "اصلاح فیلدهای الزامی پیش از استفاده"),
    "files_missing_metadata": ("info", "فایل آموزشی با متادیتای ناقص", "تکمیل نام/نوع/توضیح"),
}


def _quality_simple_query(kind: str):
    return {
        "users_missing_intake": (db.users, {"approved": True, "$or": [
            {"intake": {"$exists": False}}, {"intake": None}, {"intake": ""}]}),
        "malformed_questions": (db.questions, {"$or": [
            {"question": {"$exists": False}}, {"question": ""},
            {"lesson": {"$exists": False}}, {"lesson": ""},
            {"options": {"$exists": False}}, {"options.1": {"$exists": False}},
            {"correct_answer": {"$exists": False}}]}),
        "files_missing_metadata": (db.bs_content, {"$or": [
            {"type": {"$exists": False}}, {"type": ""},
            {"description": {"$exists": False}}, {"description": ""}]}),
    }.get(kind)


async def _quality_invalid_roles(skip=0, limit=30, count_only=False):
    valid = [role.get("_id") for role in await db.list_roles() if role.get("_id")]
    pipeline = [
        {"$unwind": "$roles"}, {"$match": {"roles": {"$nin": valid}}},
        {"$group": {"_id": "$_id", "invalid": {"$addToSet": "$roles"}}},
    ]
    if count_only:
        pipeline.append({"$count": "count"})
        return await db.user_roles.aggregate(pipeline).to_list(1)
    pipeline.extend([{"$sort": {"_id": 1}}, {"$skip": skip}, {"$limit": limit}])
    return await db.user_roles.aggregate(pipeline).to_list(limit)


async def _quality_orphans(child, parent, parent_field: str, skip=0, limit=30, count_only=False):
    pipeline = [
        {"$addFields": {"_parent_oid": {"$convert": {
            "input": f"${parent_field}", "to": "objectId", "onError": None, "onNull": None}}}},
        {"$lookup": {"from": parent.name, "localField": "_parent_oid", "foreignField": "_id", "as": "_parent"}},
        {"$match": {"_parent.0": {"$exists": False}}},
    ]
    if count_only:
        pipeline.append({"$count": "count"})
        return await child.aggregate(pipeline).to_list(1)
    pipeline.extend([{"$project": {"_parent": 0, "_parent_oid": 0}}, {"$sort": {"_id": 1}},
                     {"$skip": skip}, {"$limit": limit}])
    return await child.aggregate(pipeline).to_list(limit)


async def _quality_value_orphans(child, parent, local_field: str, foreign_field: str,
                                 skip=0, limit=30, count_only=False):
    pipeline = [
        {"$match": {local_field: {"$exists": True, "$nin": [None, ""]}}},
        {"$lookup": {"from": parent.name, "localField": local_field,
                     "foreignField": foreign_field, "as": "_parent"}},
        {"$match": {"_parent.0": {"$exists": False}}},
    ]
    if count_only:
        pipeline.append({"$count": "count"})
        return await child.aggregate(pipeline).to_list(1)
    pipeline.extend([{"$project": {"_parent": 0}}, {"$sort": {"_id": 1}},
                     {"$skip": skip}, {"$limit": limit}])
    return await child.aggregate(pipeline).to_list(limit)


async def _quality_duplicate_student_ids(skip=0, limit=30, count_only=False):
    pipeline = [
        {"$match": {"student_id": {"$exists": True, "$nin": [None, ""]}}},
        {"$group": {"_id": "$student_id", "count": {"$sum": 1},
                    "user_ids": {"$addToSet": "$user_id"},
                    "names": {"$addToSet": "$name"}}},
        {"$match": {"count": {"$gt": 1}}},
    ]
    if count_only:
        pipeline.append({"$count": "count"})
        return await db.users.aggregate(pipeline).to_list(1)
    pipeline.extend([{"$sort": {"count": -1, "_id": 1}}, {"$skip": skip}, {"$limit": limit}])
    return await db.users.aggregate(pipeline).to_list(limit)


async def _quality_count(kind: str):
    simple = _quality_simple_query(kind)
    if simple:
        collection, query = simple
        return await collection.count_documents(query)
    if kind == "invalid_role_refs":
        rows = await _quality_invalid_roles(count_only=True)
    elif kind == "duplicate_student_ids":
        rows = await _quality_duplicate_student_ids(count_only=True)
    elif kind == "users_invalid_intake":
        rows = await _quality_value_orphans(db.users, db.intakes, "intake", "code", count_only=True)
    elif kind == "orphan_sessions":
        rows = await _quality_orphans(db.bs_sessions, db.bs_lessons, "lesson_id", count_only=True)
    elif kind == "orphan_files":
        rows = await _quality_orphans(db.bs_content, db.bs_sessions, "session_id", count_only=True)
    elif kind == "orphan_ref_books":
        rows = await _quality_orphans(db.ref_books, db.ref_subjects, "subject_id", count_only=True)
    elif kind == "orphan_ref_files":
        rows = await _quality_orphans(db.ref_files, db.ref_books, "book_id", count_only=True)
    elif kind == "orphan_subscriptions":
        rows = await _quality_value_orphans(db.subscriptions, db.users, "user_id", "user_id", count_only=True)
    elif kind == "orphan_payments":
        rows = await _quality_value_orphans(db.sub_payments, db.users, "user_id", "user_id", count_only=True)
    else:
        return 0
    return int(rows[0].get("count") or 0) if rows else 0


async def _quality_summary() -> dict:
    """🌊 WA21 — خلاصه‌ی سبکِ همه‌ی بررسی‌های کیفیت داده برای کارت Action Center.

    همان `_quality_count` موجود است (منطق جدیدی نوشته نشده)؛ فقط به‌جای
    برگرداندن فهرست کامل، جمع و تفکیک severity را می‌دهد. خطای یک بررسی
    بقیه را نمی‌کُشد و در `checked`/`total` قابل تشخیص است.
    """
    kinds = list(_QUALITY_META)
    values = await asyncio.gather(*(_quality_count(k) for k in kinds),
                                  return_exceptions=True)
    total = critical = warning = info = 0
    top = []
    for kind, value in zip(kinds, values):
        if isinstance(value, Exception):
            continue
        n = int(value or 0)
        if not n:
            continue
        total += n
        sev = _QUALITY_META[kind][0]
        if sev == "critical":
            critical += n
        elif sev == "warning":
            warning += n
        else:
            info += n
        top.append({"kind": kind, "severity": sev,
                    "label": _QUALITY_META[kind][1], "count": n})
    top.sort(key=lambda x: (x["severity"] != "critical", -x["count"]))
    return {"count": total, "critical": critical, "warning": warning, "info": info,
            "checked": len(kinds), "top": top[:4]}


# 🌊 WA21 — گونه‌هایی که اصلاحشان «امن» است: رکوردی که والدِ معتبر ندارد
# هیچ‌وقت نمی‌تواند نمایش داده شود، پس حذفش داده‌ی قابل‌دسترس را از بین نمی‌برد.
# گونه‌های هویتی/مالی (duplicate_student_ids، orphan_subscriptions،
# orphan_payments، users_invalid_intake) عمداً اینجا نیستند: اصلاحشان تصمیم
# انسانی می‌خواهد و auto-fix روی هویت/پرداخت ممنوع است.
_QUALITY_SAFE_FIXES = {
    "orphan_files":     "حذف فایل آموزشی بدون جلسه‌ی والد",
    "orphan_ref_files": "حذف فایل رفرنس بدون کتاب والد",
    "orphan_ref_books": "حذف کتاب رفرنس بدون موضوع والد",
    "orphan_sessions":  "حذف جلسه‌ی بدون درس والد",
    "invalid_role_refs": "حذف ارجاع به نقش‌های ناموجود (نقش‌های معتبر حفظ می‌شوند)",
}


def _quality_safe_fix_criteria(kind: str):
    """معیار حذف برای گونه‌های امن — دقیقاً همان معیار شمارش، نه یک کپی سلیقه‌ای."""
    if kind == "orphan_files":
        coll, field, parent = db.bs_content, "session_id", db.bs_sessions
    elif kind == "orphan_ref_files":
        coll, field, parent = db.ref_files, "book_id", db.ref_books
    elif kind == "orphan_ref_books":
        coll, field, parent = db.ref_books, "subject_id", db.ref_subjects
    elif kind == "orphan_sessions":
        coll, field, parent = db.bs_sessions, "lesson_id", db.bs_lessons
    else:
        return None, None
    return coll, [
        {"$addFields": {"_parent_oid": {"$convert": {
            "input": f"${field}", "to": "objectId", "onError": None, "onNull": None}}}},
        {"$lookup": {"from": parent.name, "localField": "_parent_oid",
                     "foreignField": "_id", "as": "_parent"}},
        {"$match": {"_parent.0": {"$exists": False}}},
        {"$project": {"_id": 1}},
    ]


class WaQualityFix(BaseModel):
    kind: str
    confirm: bool = False


@router.post("/operations/data-quality/{kind}/fix")
async def wa_data_quality_fix(kind: str, body: WaQualityFix,
                              user=Depends(_perm("system.manage"))):
    """🌊 WA21 — اصلاح یک ناهنجاری کیفیت داده، با تأیید صریح + Audit.

    چرا فقط این گونه‌ها: حذف رکورد یتیم هیچ داده‌ی قابل‌دسترس را از بین نمی‌برد
    (والدش وجود ندارد، پس هرگز نمایش داده نمی‌شد). هر گونه‌ی هویتی/مالی عمداً
    بیرون از این فهرست است و 400 می‌گیرد.
    """
    if kind not in _QUALITY_SAFE_FIXES:
        raise HTTPException(
            400, "این گونه اصلاح خودکار ندارد؛ باید دستی بررسی شود.")
    if not body.confirm:
        raise HTTPException(400, "برای اجرای اصلاح، تأیید صریح لازم است.")

    before = await _quality_count(kind)
    if kind == "invalid_role_refs":
        # نقش‌های معتبر حفظ می‌شوند؛ فقط کلیدهایی که در roles وجود ندارند
        # از آرایه‌ی roles بیرون کشیده می‌شوند. هیچ سندی کامل حذف نمی‌شود.
        valid = [r.get("_id") for r in await db.list_roles() if r.get("_id")]
        result = await db.user_roles.update_many(
            {}, {"$pull": {"roles": {"$nin": valid}}})
        removed = int(result.modified_count or 0)
    else:
        coll, pipeline = _quality_safe_fix_criteria(kind)
        ids = [row["_id"] for row in await coll.aggregate(pipeline).to_list(100000)]
        removed = 0
        if ids:
            removed = int((await coll.delete_many({"_id": {"$in": ids}})).deleted_count or 0)
    after = await _quality_count(kind)

    log_id = await _audit(
        user["id"], f"اصلاح خودکار کیفیت داده: {kind}", severity="WARNING",
        target_id=kind, target_type="data_quality",
        target_label=_QUALITY_META[kind][1],
        before={"count": before}, after={"count": after, "removed": removed},
        details=_QUALITY_SAFE_FIXES[kind], tags=["کیفیت_داده", "پنل_وب"])
    return {"ok": True, "kind": kind, "removed": removed,
            "before": before, "after": after, "audit_id": log_id}


@router.get("/operations/data-quality")
async def wa_data_quality(user=Depends(_perm("system.manage"))):
    kinds = list(_QUALITY_META)
    values = await asyncio.gather(*(_quality_count(kind) for kind in kinds), return_exceptions=True)
    items = []
    for kind, value in zip(kinds, values):
        severity, label, suggestion = _QUALITY_META[kind]
        items.append({"kind": kind, "severity": severity, "label": label,
                      "suggestion": suggestion,
                      "count": None if isinstance(value, Exception) else int(value or 0),
                      "available": not isinstance(value, Exception)})
    # 🌊 WA21 — دیگر کاملاً فقط‌خواندنی نیست: گونه‌های `_QUALITY_SAFE_FIXES`
    # اکشن Fix دارند. بقیه همچنان inspect-only هستند و UI باید همین را بگوید.
    return {"items": items, "checked_at": _now(),
            "read_only": False, "fixable": sorted(_QUALITY_SAFE_FIXES)}


@router.get("/operations/data-quality/{kind}")
async def wa_data_quality_items(
    kind: str, skip: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100),
    user=Depends(_perm("system.manage")),
):
    if kind not in _QUALITY_META:
        raise HTTPException(404, "نوع بررسی کیفیت داده پیدا نشد")
    total = await _quality_count(kind)
    simple = _quality_simple_query(kind)
    if simple:
        collection, query = simple
        docs = await collection.find(query).sort("_id", 1).skip(skip).limit(limit).to_list(limit)
    elif kind == "invalid_role_refs":
        docs = await _quality_invalid_roles(skip, limit)
    elif kind == "duplicate_student_ids":
        docs = await _quality_duplicate_student_ids(skip, limit)
    elif kind == "users_invalid_intake":
        docs = await _quality_value_orphans(db.users, db.intakes, "intake", "code", skip, limit)
    elif kind == "orphan_sessions":
        docs = await _quality_orphans(db.bs_sessions, db.bs_lessons, "lesson_id", skip, limit)
    elif kind == "orphan_files":
        docs = await _quality_orphans(db.bs_content, db.bs_sessions, "session_id", skip, limit)
    elif kind == "orphan_ref_books":
        docs = await _quality_orphans(db.ref_books, db.ref_subjects, "subject_id", skip, limit)
    elif kind == "orphan_ref_files":
        docs = await _quality_orphans(db.ref_files, db.ref_books, "book_id", skip, limit)
    elif kind == "orphan_subscriptions":
        docs = await _quality_value_orphans(db.subscriptions, db.users, "user_id", "user_id", skip, limit)
    else:
        docs = await _quality_value_orphans(db.sub_payments, db.users, "user_id", "user_id", skip, limit)
    severity, label, suggestion = _QUALITY_META[kind]
    items = await _quality_enrich_items(kind, docs, severity, label, suggestion)
    return {"items": items, "total": total, "skip": skip, "limit": limit,
            "read_only": False, "repair": _QUALITY_REPAIR.get(kind, {})}


# ══════════════════════════════════════════════════════════════════
# 🌊 W5 — مرکز اقدام قابل‌فهم و قابل‌اصلاح
# آیتم‌ها باید human-readable باشند (عنوان انسانی + context واقعی +
# فهرست کمبودها) و هر گونه که semantics اصلاحش روشن است، اکشن مستقیم
# دارد. ID فنی فقط در `technical`. گونه‌های هویتی/مالی عمداً دستی می‌مانند.
# ══════════════════════════════════════════════════════════════════

_QUALITY_REPAIR = {
    "files_missing_metadata": {"edit": True, "delete": False, "attach": None},
    "orphan_files":     {"edit": False, "delete": True, "attach": "sessions"},
    "orphan_sessions":  {"edit": False, "delete": True, "attach": "lessons"},
    "orphan_ref_books": {"edit": False, "delete": True, "attach": "subjects"},
    "orphan_ref_files": {"edit": False, "delete": True, "attach": "books"},
}

# kind → (کالکشن فرزند، فیلد ارجاع، کالکشن والد) برای «اتصال به والد معتبر»
_QUALITY_ATTACH = {
    "orphan_files":     ("bs_content",  "session_id", "bs_sessions"),
    "orphan_sessions":  ("bs_sessions", "lesson_id",  "bs_lessons"),
    "orphan_ref_books": ("ref_books",   "subject_id", "ref_subjects"),
    "orphan_ref_files": ("ref_files",   "book_id",    "ref_books"),
}


async def _quality_enrich_items(kind, docs, severity, label, suggestion):
    """🌊 W5 — بزرگ‌نمایی انسانی آیتم‌های کیفیت داده.

    به‌جای headline کردن ObjectId، عنوان انسانی + context واقعی
    (درس/جلسه/نام‌ها) + فهرست فیلدهای ناقص برگردانده می‌شود."""
    sessions, lessons = {}, {}
    if kind == "files_missing_metadata":
        sids = [ObjectId(s) for s in {str(d.get("session_id") or "") for d in docs}
                if s and ObjectId.is_valid(s)]
        if sids:
            sdocs = await db.bs_sessions.find({"_id": {"$in": sids}}).to_list(500)
            sessions = {str(s["_id"]): s for s in sdocs}
            lids = [ObjectId(x) for x in {str(s.get("lesson_id") or "") for s in sdocs}
                    if x and ObjectId.is_valid(x)]
            if lids:
                ldocs = await db.bs_lessons.find({"_id": {"$in": lids}}).to_list(500)
                lessons = {str(l["_id"]): l for l in ldocs}
    out = []
    for doc in docs:
        item = {"id": str(doc.get("_id", "")),
                "reason": label, "severity": severity, "suggestion": suggestion,
                "metadata": {key: doc.get(key) for key in
                             ("user_id", "user_ids", "names", "count", "intake", "lesson_id", "session_id",
                              "subject_id", "book_id", "student_id", "roles", "invalid", "type", "source")
                             if doc.get(key) is not None}}
        title = (doc.get("name") or doc.get("question") or doc.get("topic") or
                 doc.get("description") or "")
        context, missing = "", []
        if kind == "files_missing_metadata":
            sess = sessions.get(str(doc.get("session_id") or "")) or {}
            les = lessons.get(str(sess.get("lesson_id") or "")) or {}
            ctype = (doc.get("type") or "").strip()
            title = title or f"فایل آموزشی{' (' + ctype + ')' if ctype else ''}"
            parts = []
            if les.get("name"):
                parts.append(f"درس: {les['name']}")
            if sess.get("name") or sess.get("topic"):
                parts.append(f"جلسه: {sess.get('name') or sess.get('topic')}")
            context = " · ".join(parts) or "متصل به جلسه‌ی معتبر نیست"
            missing = [f for f in ("type", "description")
                       if not (doc.get(f) or "").strip()]
            if not (doc.get("name") or doc.get("description") or "").strip():
                missing.append("name")
        elif kind in _QUALITY_ATTACH:
            field = _QUALITY_ATTACH[kind][1]
            context = f"ارجاع شکسته: {field}={doc.get(field) or '—'}"
            title = title or label
        elif kind == "duplicate_student_ids":
            title = f"شماره دانشجویی {doc.get('_id')} مشترک بین {doc.get('count')} کاربر"
            context = " · ".join((doc.get("names") or [])[:4])
        elif kind in ("users_missing_intake", "users_invalid_intake"):
            title = doc.get("name") or f"کاربر #{doc.get('user_id')}"
            context = (f"شماره دانشجویی: {doc.get('student_id') or '—'} · "
                       f"ورودی: {doc.get('intake') or '—'}")
        elif kind == "malformed_questions":
            title = (doc.get("question") or "سؤال بدون متن")[:80]
            context = f"درس: {doc.get('lesson') or '—'} · موضوع: {doc.get('topic') or '—'}"
        elif kind in ("orphan_subscriptions", "orphan_payments"):
            title = f"{label} #{doc.get('user_id')}"
            context = "بررسی زنجیره پرداخت و هویت پیش از هر اصلاح"
        else:
            title = title or label
        item.update({"title": title, "context": context, "missing": missing,
                     "technical": str(doc.get("_id", "")),
                     "repair": _QUALITY_REPAIR.get(kind, {})})
        out.append(item)
    return out


class WaQualityRepairBody(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None


@router.post("/operations/data-quality/files_missing_metadata/{item_id}/repair")
async def wa_data_quality_repair(item_id: str, body: WaQualityRepairBody,
                                 user=Depends(_perm("system.manage"))):
    """🌊 W5 — اصلاح مستقیم متادیتای ناقص: فقط فیلدهای داده‌شده set می‌شوند،
    سپس همان rule دوباره اجرا می‌شود؛ `resolved` فقط وقتی true است که رکورد
    واقعاً از شمارش خارج شده باشد. بدون حدس، بدون overwrite خودکار."""
    from api.routers.content_admin import CONTENT_TYPES
    if not ObjectId.is_valid(item_id):
        raise HTTPException(404, "رکورد پیدا نشد")
    doc = await db.bs_content.find_one({"_id": ObjectId(item_id)})
    if not doc:
        raise HTTPException(404, "فایل آموزشی پیدا نشد")
    updates = {}
    if body.name is not None:
        name = body.name.strip()
        if len(name) < 3:
            raise HTTPException(422, "نام باید حداقل ۳ نویسه باشد")
        updates["name"] = name[:200]
    if body.type is not None:
        ctype = body.type.strip().lower()
        if ctype not in CONTENT_TYPES:
            raise HTTPException(422, "نوع معتبر نیست؛ مجاز: " + "، ".join(CONTENT_TYPES))
        updates["type"] = ctype
    if body.description is not None:
        desc = body.description.strip()
        if len(desc) < 3:
            raise HTTPException(422, "توضیح باید حداقل ۳ نویسه باشد")
        updates["description"] = desc[:2000]
    if not updates:
        raise HTTPException(400, "هیچ فیلدی برای اصلاح داده نشد")
    await db.bs_content.update_one({"_id": doc["_id"]}, {"$set": updates})
    after = await db.bs_content.find_one({"_id": doc["_id"]})
    resolved = bool((after.get("type") or "").strip()) and \
        bool((after.get("description") or "").strip())
    log_id = await _audit(
        user["id"], "اصلاح کیفیت داده: تکمیل متادیتای فایل آموزشی",
        severity="INFO", target_type="content", target_id=item_id,
        target_label=(after.get("name") or after.get("description") or item_id)[:80],
        before={k: doc.get(k) for k in updates},
        after={**updates, "resolved": resolved},
        tags=["کیفیت_داده", "پنل_وب"])
    return {"ok": True, "resolved": resolved, "audit_id": log_id}


class WaQualityAttachBody(BaseModel):
    parent_id: str


@router.post("/operations/data-quality/{kind}/{item_id}/attach")
async def wa_data_quality_attach(kind: str, item_id: str, body: WaQualityAttachBody,
                                 user=Depends(_perm("system.manage"))):
    """🌊 W5 — اتصال رکورد یتیم به والد معتبرِ انتخاب‌شده توسط ادمین.
    والد باید واقعاً وجود داشته باشد؛ پس از اتصال، rule دوباره چک می‌شود."""
    if kind not in _QUALITY_ATTACH:
        raise HTTPException(400, "این گونه اقدام «اتصال به والد» ندارد")
    child_name, field, parent_name = _QUALITY_ATTACH[kind]
    if not ObjectId.is_valid(item_id) or not ObjectId.is_valid(body.parent_id):
        raise HTTPException(404, "رکورد پیدا نشد")
    target = await getattr(db, parent_name).find_one({"_id": ObjectId(body.parent_id)})
    if not target:
        raise HTTPException(404, "والد معتبر پیدا نشد")
    res = await getattr(db, child_name).update_one(
        {"_id": ObjectId(item_id)}, {"$set": {field: str(target["_id"])}})
    if not res.matched_count:
        raise HTTPException(404, "رکورد پیدا نشد")
    log_id = await _audit(
        user["id"], f"اصلاح کیفیت داده: اتصال {kind} به والد معتبر",
        severity="WARNING", target_type=child_name, target_id=item_id,
        target_label=target.get("name") or str(target["_id"]),
        before={field: None}, after={field: str(target["_id"]), "resolved": True},
        tags=["کیفیت_داده", "پنل_وب"])
    return {"ok": True, "resolved": True, "audit_id": log_id}


class WaQualityRemoveBody(BaseModel):
    confirm: bool = False


@router.post("/operations/data-quality/{kind}/{item_id}/remove")
async def wa_data_quality_remove(kind: str, item_id: str, body: WaQualityRemoveBody,
                                 user=Depends(_perm("system.manage"))):
    """🌊 W5 — حذف تکی رکورد یتیم با تأیید صریح. پیش از حذف دوباره چک می‌شود
    که رکورد هنوز یتیم است (اگر والدش سر راه سبز شده، 409)."""
    if kind not in _QUALITY_ATTACH:
        raise HTTPException(400, "این گونه حذف تکی ندارد")
    if not body.confirm:
        raise HTTPException(400, "برای حذف، تأیید صریح لازم است")
    child_name, field, parent_name = _QUALITY_ATTACH[kind]
    if not ObjectId.is_valid(item_id):
        raise HTTPException(404, "رکورد پیدا نشد")
    doc = await getattr(db, child_name).find_one({"_id": ObjectId(item_id)})
    if not doc:
        raise HTTPException(404, "رکورد پیدا نشد")
    ref = str(doc.get(field) or "")
    if ref and ObjectId.is_valid(ref) and \
            await getattr(db, parent_name).find_one({"_id": ObjectId(ref)}):
        raise HTTPException(409, "این رکورد دیگر یتیم نیست؛ حذف لازم نیست")
    await getattr(db, child_name).delete_one({"_id": doc["_id"]})
    log_id = await _audit(
        user["id"], f"اصلاح کیفیت داده: حذف تکی {kind}",
        severity="WARNING", target_type=child_name, target_id=item_id,
        target_label=doc.get("name") or doc.get("description") or item_id,
        before={"present": True}, after={"present": False},
        tags=["کیفیت_داده", "پنل_وب"])
    return {"ok": True, "removed": 1, "audit_id": log_id}


@router.get("/operations/quality-parents/{parent_kind}")
async def wa_data_quality_parents(parent_kind: str,
                                  q: str = Query("", max_length=60),
                                  user=Depends(_perm("system.manage"))):
    """🌊 W5 — انتخاب والد معتبر برای attach (کرانه‌دار و جست‌وجوپذیر)."""
    coll = {"sessions": db.bs_sessions, "lessons": db.bs_lessons,
            "books": db.ref_books, "subjects": db.ref_subjects}.get(parent_kind)
    if coll is None:
        raise HTTPException(404, "نوع والد معتبر نیست")
    flt = {"name": {"$regex": re.escape(q.strip()), "$options": "i"}} if q.strip() else {}
    docs = await coll.find(flt).sort("name", 1).limit(20).to_list(20)
    return {"items": [{"id": str(d["_id"]), "label": d.get("name") or str(d["_id"])}
                      for d in docs]}


# ══════════════════════════════════════════════════════════════════
# 🌊 WA2.5 — جست‌وجوی سراسری سریع (Command Palette)
# ══════════════════════════════════════════════════════════════════

@router.get("/search")
async def global_quick_search(q: str = Query(..., min_length=2, max_length=80),
                              user=Depends(_guard_any_admin)):
    """جست‌وجوی سراسری permission-aware در موجودیت‌های واقعی سامانه."""
    query = " ".join(q.split())[:80]
    rx = {"$regex": re.escape(query), "$options": "i"}
    uid = user["id"]
    perms = await db.get_user_perms(uid)
    allow = lambda *keys: uid == ADMIN_ID or any(k in perms for k in keys)
    res = {"users": [], "tickets": [], "questions": [], "content": [],
           "exams": [], "grades": [], "roles": [], "broadcasts": [],
           "payments": [], "subscriptions": [], "notifications": [],
           "audit": [], "wallets": []}

    if allow("users.view", "users.manage"):
        try:
            us = await db.users.find(db.build_user_search_query(query)).sort("registered_at", -1).limit(6).to_list(6)
            res["users"] = [{"id": u.get("user_id"), "name": u.get("name", ""),
                "student_id": u.get("student_id", ""), "intake": u.get("intake", ""),
                "username": u.get("username", "")} for u in us]
        except Exception:
            pass
    if allow("tickets.reply", "tickets.manage"):
        try:
            ts = await db.tickets.find({"$or": [{"subject": rx}, {"user_name": rx}]}).sort("created_at", -1).limit(5).to_list(5)
            res["tickets"] = [{"id": t.get("ticket_id"), "subject": t.get("subject", ""),
                "status": t.get("status", ""), "user_name": t.get("user_name", "")} for t in ts]
        except Exception:
            pass
    if allow("questions.review", "questions.review_scoped"):
        try:
            scope = await _question_scope_context(user)
            qf = {"question": rx}
            if scope.get("kind") == "scoped": qf["intake"] = scope.get("intake") or ""
            qs = await db.questions.find(qf).sort("created_at", -1).limit(5).to_list(5)
            res["questions"] = [{"id": str(x.get("_id", "")), "text": (x.get("question", "") or "")[:90],
                "lesson": x.get("lesson", ""), "topic": x.get("topic", ""),
                "approved": bool(x.get("approved"))} for x in qs]
        except Exception:
            pass
    if allow("content.manage", "content.scoped"):
        try:
            scope = await db.get_content_scope(uid)
            intake = scope.get("intake") if scope and scope.get("kind") == "scoped" else None
            rs = await db.search_resources(query, intake=intake)
            res["content"] = [{"title": r.get("title") or r.get("description") or "",
                "type": r.get("type", ""), "path": r.get("path", "")} for r in (rs or [])[:5]]
        except Exception:
            pass
    if allow("schedules.manage"):
        try:
            docs = await db.schedules.find({"type": "exam", "$or": [
                {"lesson": rx}, {"teacher": rx}, {"location": rx}]}).sort("date", -1).limit(5).to_list(5)
            res["exams"] = [{"id": str(x.get("_id", "")), "lesson": x.get("lesson", ""),
                "date": x.get("date", ""), "group": db.normalize_group(x.get("group")) or "هر دو"} for x in docs]
        except Exception:
            pass
    if allow("grades.manage", "grades.scoped"):
        try:
            gf = {"$or": [{"lesson": rx}, {"exam_title": rx}]}
            if query.isdigit(): gf["$or"].append({"student_id": int(query)})
            if await db.has_permission(uid, "grades.scoped") and not await db.has_permission(uid, "grades.manage"):
                scope = await db.get_scoped_intake(uid)
                scoped_ids = await db.users.distinct("user_id", {"intake": scope}) if scope else []
                gf["student_id"] = {"$in": scoped_ids}
            docs = await db.grades.find(gf).sort("exam_date", -1).limit(5).to_list(5)
            res["grades"] = [{"id": str(row.get("_id", "")), "student_id": row.get("student_id"),
                              "lesson": row.get("lesson", ""), "exam_title": row.get("exam_title", ""),
                              "score": row.get("score"), "exam_date": row.get("exam_date", "")} for row in docs]
        except Exception:
            pass
    if allow("roles.manage"):
        try:
            docs = await db.roles.find({"$or": [{"label": rx}, {"_id": rx}]}).sort("priority", 1).limit(5).to_list(5)
            res["roles"] = [{"id": row.get("_id"), "label": row.get("label", ""),
                             "active": row.get("active", True), "permissions": len(row.get("perms") or [])} for row in docs]
        except Exception:
            pass
    if allow("broadcast.send"):
        try:
            docs = await db.broadcast_campaigns.find({"$or": [
                {"payload.text": rx}, {"payload.caption": rx}, {"created_by_name": rx},
            ]}).sort("created_at", -1).limit(5).to_list(5)
            res["broadcasts"] = [{"id": str(row.get("_id", "")),
                "text": ((row.get("payload") or {}).get("text") or (row.get("payload") or {}).get("caption") or f"[{row.get('message_type','text')}]")[:90],
                "status": row.get("status", ""), "source": row.get("source", ""),
                "created_at": row.get("created_at", ""), "correlation_id": row.get("correlation_id")}
                for row in docs]
        except Exception:
            pass
    if allow("subscription.manage"):
        try:
            pays = await db.sub_payments.find({"$or": [{"plan_name": rx}, {"discount_code": rx}]}).sort("submitted_at", -1).limit(5).to_list(5)
            res["payments"] = [{"id": str(x.get("_id", "")), "user_id": x.get("user_id"),
                "plan": x.get("plan_name", ""), "status": x.get("status", ""),
                "amount": x.get("final_price", x.get("price", 0))} for x in pays]
            subs = await db.subscriptions.find({"plan_name": rx}).sort("end_date", -1).limit(5).to_list(5)
            res["subscriptions"] = [{"user_id": x.get("_id"), "plan": x.get("plan_name", ""),
                "status": x.get("status", ""), "end_date": x.get("end_date", "")} for x in subs]
            # 💰 W6 — کیف پول (§۱۰۷): آیدی عددی مستقیم، وگرنه از راه نام کاربر
            if query.isdigit():
                wq = {"user_id": int(query)}
            else:
                wuids = [int(u["user_id"]) for u in await db.users.find(
                    {"name": rx}, {"user_id": 1}).limit(20)]
                wq = {"user_id": {"$in": wuids}} if wuids else {"user_id": -1}
            ws = await db.wallets.find(wq).sort("balance", -1).limit(5).to_list(5)
            if ws:
                wnames = {}
                for u in await db.users.find(
                        {"user_id": {"$in": [w["user_id"] for w in ws]}}).to_list(50):
                    wnames[int(u["user_id"])] = u.get("name") or ""
                res["wallets"] = [{"user_id": w["user_id"],
                                   "name": wnames.get(int(w["user_id"]), ""),
                                   "balance": int(w.get("balance", 0))}
                                  for w in ws]
        except Exception:
            pass
    if allow("notifications.manage", "broadcast.send"):
        try:
            notes = await db.bot_notifs.find({"text": rx}).sort("created_at", -1).limit(5).to_list(5)
            res["notifications"] = [{"id": str(x.get("_id", "")), "type": x.get("type", ""),
                "text": (x.get("text", "") or "")[:90], "sent": bool(x.get("sent"))} for x in notes]
        except Exception:
            pass
    if allow("audit.view"):
        try:
            al = await db.audit_logs.find({"$or": [{"action": rx}, {"actor.name": rx},
                {"target.label": rx}]}).sort("timestamp", -1).limit(5).to_list(5)
            res["audit"] = [{"id": str(a.get("_id", "")), "action": a.get("action", ""),
                "actor": (a.get("actor") or {}).get("name", ""),
                "at": a.get("timestamp") or None} for a in al]
        except Exception:
            pass
    return {"q": query, **res}


# ══════════════════════════════════════════════════════════════════
# 🌊 WA2.4 — فیلترهای ذخیره‌شده + اکشن گروهی تیکت/سؤال
# ══════════════════════════════════════════════════════════════════

SAVED_VIEW_SCOPE_PERMS = {
    "users": ("users.view", "users.manage"),
    "questions": ("questions.review", "questions.review_scoped"),
    "content": ("content.manage", "content.scoped"),
    "audit": ("audit.view",), "payments": ("subscription.manage",),
    "subscriptions": ("subscription.manage",),
    "tickets": ("tickets.reply", "tickets.manage"),
    "reports": ("reports.review",), "grades": ("grades.manage", "grades.scoped"),
    "broadcast_segment": ("broadcast.send",), "broadcast_draft": ("broadcast.send",),
    "exams": ("schedules.manage",),
    "analytics": ("stats.view",),
}


async def _saved_view_scope_allowed(user: dict, scope: str) -> bool:
    if scope not in SAVED_VIEW_SCOPE_PERMS:
        return False
    if user["id"] == ADMIN_ID:
        return True
    for permission in SAVED_VIEW_SCOPE_PERMS[scope]:
        if await db.has_permission(user["id"], permission):
            return True
    return False


class SavedFilterIn(BaseModel):
    name: str
    scope: str
    filters: dict = {}
    columns: list[str] = []
    sort: dict = {}
    density: str = ""
    shared: bool = False


class SavedFilterPatch(BaseModel):
    name: Optional[str] = None
    filters: Optional[dict] = None
    columns: Optional[list[str]] = None
    sort: Optional[dict] = None
    density: Optional[str] = None
    shared: Optional[bool] = None


@router.get("/saved-filters")
async def saved_filters_list(scope: str | None = Query(None),
                             user=Depends(_guard_any_admin)):
    """Saved Views شخصی + اشتراکی، فقط در scope مجاز همان مدیر."""
    if scope and not await _saved_view_scope_allowed(user, scope):
        raise HTTPException(403, "forbidden")
    query = {"$or": [{"owner": user["id"]}, {"shared": True}]}
    if scope:
        query["scope"] = scope
    else:
        allowed_scopes = [key for key in SAVED_VIEW_SCOPE_PERMS
                          if await _saved_view_scope_allowed(user, key)]
        query["scope"] = {"$in": allowed_scopes}
    docs = await db.wa_saved_filters.find(query).sort("updated_at", -1).limit(80).to_list(80)
    owner_ids = list({d.get("owner") for d in docs if d.get("owner") is not None})
    owners = await db.users.find({"user_id": {"$in": owner_ids}}, {"user_id": 1, "name": 1}).to_list(len(owner_ids) or 1)
    owner_map = {u.get("user_id"): u.get("name", "") for u in owners}
    return {"filters": [{
        "id": str(d.get("_id", "")), "name": d.get("name", ""),
        "scope": d.get("scope", ""), "filters": d.get("filters") or {},
        "columns": d.get("columns") or [], "sort": d.get("sort") or {},
        "density": d.get("density") or "", "shared": bool(d.get("shared")), "owner": d.get("owner"),
        "owner_name": owner_map.get(d.get("owner"), ""),
        "editable": d.get("owner") == user["id"],
        "created_at": d.get("created_at") or None,
        "updated_at": d.get("updated_at") or d.get("created_at") or None,
        "updated_by": d.get("updated_by") or d.get("owner"),
        "last_opened_at": d.get("last_opened_at") or None,
        "last_opened_by": d.get("last_opened_by"),
    } for d in docs if d.get("owner") == user["id"] or d.get("shared")]}


@router.post("/saved-filters")
async def saved_filters_add(body: SavedFilterIn, user=Depends(_guard_any_admin)):
    name = (body.name or "").strip()[:60]
    if not name:
        raise HTTPException(422, "نام نما الزامی است")
    if not await _saved_view_scope_allowed(user, body.scope):
        raise HTTPException(403, "forbidden")
    uid = user["id"]
    if await db.wa_saved_filters.count_documents({"owner": uid}) >= 50:
        raise HTTPException(422, "حداکثر ۵۰ نمای ذخیره‌شده می‌توانید داشته باشید")
    now = _now()
    doc = {"owner": uid, "name": name, "scope": body.scope,
           "filters": body.filters or {}, "columns": list(dict.fromkeys(body.columns or []))[:80],
           "sort": body.sort or {}, "density": body.density if body.density in ("compact", "comfortable", "") else "",
           "shared": bool(body.shared), "updated_by": uid,
           "created_at": now, "updated_at": now}
    r = await db.wa_saved_filters.insert_one(doc)
    await _audit(user["id"], "ذخیره نمای ذخیره‌شده", severity="INFO", target_type="saved_filter", target_id=str(getattr(r, "inserted_id", "") or ""), target_label=name, after={"scope": body.scope}, tags=["saved_filter", "پنل_وب"])
    return {"ok": True, "id": str(getattr(r, "inserted_id", "") or "")}


@router.put("/saved-filters/{fid}")
async def saved_filters_update(fid: str, body: SavedFilterPatch,
                               user=Depends(_guard_any_admin)):
    oid = _oid(fid)
    query = {"owner": user["id"], "_id": oid if oid else fid}
    old = await db.wa_saved_filters.find_one(query)
    if not old:
        raise HTTPException(404, "نمای ذخیره‌شده پیدا نشد")
    if not await _saved_view_scope_allowed(user, old.get("scope", "")):
        raise HTTPException(403, "forbidden")
    changes = {}
    if body.name is not None:
        name = body.name.strip()[:60]
        if not name: raise HTTPException(422, "نام نما الزامی است")
        changes["name"] = name
    if body.filters is not None: changes["filters"] = body.filters
    if body.columns is not None: changes["columns"] = list(dict.fromkeys(body.columns))[:80]
    if body.sort is not None: changes["sort"] = body.sort
    if body.density is not None:
        if body.density not in ("compact", "comfortable", ""):
            raise HTTPException(422, "چگالی نما نامعتبر است")
        changes["density"] = body.density
    if body.shared is not None: changes["shared"] = bool(body.shared)
    if not changes: raise HTTPException(422, "تغییری ارسال نشده است")
    changes["updated_at"] = _now(); changes["updated_by"] = user["id"]
    await db.wa_saved_filters.update_one(query, {"$set": changes})
    await _audit(user["id"], "ویرایش نمای ذخیره‌شده", severity="INFO", target_type="saved_filter", target_id=fid, target_label=old.get("name",""), before={"scope": old.get("scope")}, after={"changed": list(changes)}, tags=["saved_filter", "پنل_وب"])
    return {"ok": True, "changed": list(changes)}


@router.post("/saved-filters/{fid}/touch")
async def saved_filter_touch(fid: str, user=Depends(_guard_any_admin)):
    oid = _oid(fid)
    query = {"_id": oid if oid else fid,
             "$or": [{"owner": user["id"]}, {"shared": True}]}
    doc = await db.wa_saved_filters.find_one(query)
    if not doc or not await _saved_view_scope_allowed(user, doc.get("scope", "")):
        raise HTTPException(404, "نمای ذخیره‌شده پیدا نشد")
    await db.wa_saved_filters.update_one({"_id": doc["_id"]}, {"$set": {
        "last_opened_at": _now(), "last_opened_by": user["id"]}})
    return {"ok": True}


@router.delete("/saved-filters/{fid}")
async def saved_filters_del(fid: str, user=Depends(_guard_any_admin)):
    """فقط صاحب فیلتر می‌تواند آن را حذف کند."""
    oid = _oid(fid)
    q = {"owner": user["id"]}
    if oid:
        q["_id"] = oid
    else:
        q["_id"] = fid
    r = await db.wa_saved_filters.delete_many(q)
    if getattr(r, "deleted_count", 0):
        try:
            await _audit(user["id"], "حذف نمای ذخیره‌شده", severity="INFO", target_type="saved_filter", target_id=fid, tags=["saved_filter", "پنل_وب"])
        except Exception:
            pass
    if not getattr(r, "deleted_count", 0):
        raise HTTPException(404, "فیلتر یافت نشد")
    return {"ok": True}


async def _require_object_permission(user: dict, target_type: str):
    perm_map = {
        "user": ("users.view", "users.manage"), "question": ("questions.review", "questions.review_scoped"),
        "ticket": ("tickets.reply", "tickets.manage"), "payment": ("subscription.manage",),
        "subscription": ("subscription.manage",), "role": ("roles.manage",),
        "notification": ("notifications.manage",), "broadcast": ("broadcast.send",),
        "setting": ("settings.manage",), "exam": ("schedules.manage",), "grade": ("grades.manage", "grades.scoped"),
    }
    required = perm_map.get(target_type)
    if not required: raise HTTPException(422, "نوع object پشتیبانی نمی‌شود")
    if user["id"] == ADMIN_ID: return
    if not any([await db.has_permission(user["id"], permission) for permission in required]):
        raise HTTPException(403, "forbidden")


@router.get("/objects/{target_type}/{target_id}")
async def wa_object_summary(target_type: str, target_id: str, user=Depends(_guard_any_admin)):
    """Universal object summary: identity/status/metadata/relations از persisted data."""
    await _require_object_permission(user, target_type)
    relations, actions = [], []
    if target_type == "user":
        if not target_id.isdigit(): raise HTTPException(422, "شناسه کاربر نامعتبر است")
        doc = await db.get_user(int(target_id))
        if not doc: raise HTTPException(404, "کاربر پیدا نشد")
        identity = {"id": doc.get("user_id"), "label": db.display_name_of(doc), "type": "user"}
        status = "suspended" if doc.get("suspended") else "active" if doc.get("approved") else "pending"
        metadata = {key: doc.get(key) for key in ("username", "student_id", "intake", "group", "registered_at", "last_active")}
        ticket_count, question_count = await asyncio.gather(
            db.tickets.count_documents({"user_id": int(target_id)}),
            db.questions.count_documents({"creator_id": int(target_id)}))
        relations = [{"type": "ticket", "label": "تیکت‌ها", "count": ticket_count, "go": f"/tickets?q={target_id}"},
                     {"type": "question", "label": "سؤال‌های طراحی‌شده", "count": question_count, "go": f"/questions?author={target_id}"}]
        actions = ["edit", "message"]
    elif target_type == "question":
        doc = await db.get_question_by_id(target_id)
        if not doc: raise HTTPException(404, "سؤال پیدا نشد")
        scope = await _question_scope_context(user)
        if scope.get("kind") == "scoped" and (doc.get("intake") or "") != (scope.get("intake") or ""):
            raise HTTPException(403, "intake_out_of_scope")
        identity = {"id": target_id, "label": (doc.get("question") or "")[:120], "type": "question"}
        status = "approved" if doc.get("approved") else "pending"
        metadata = {key: doc.get(key) for key in ("lesson", "topic", "difficulty", "source", "intake", "attempt_count", "correct_count", "report_count")}
        if doc.get("creator_id"):
            relations.append({"type": "user", "label": doc.get("creator_name") or "طراح", "id": doc.get("creator_id"), "go": f"/users?q={doc.get('creator_id')}"})
        actions = [] if doc.get("approved") else ["edit", "approve", "reject"]
    elif target_type == "ticket":
        if not target_id.isdigit(): raise HTTPException(422, "شناسه تیکت نامعتبر است")
        doc = await db.ticket_get(int(target_id))
        if not doc: raise HTTPException(404, "تیکت پیدا نشد")
        identity = {"id": int(target_id), "label": doc.get("subject") or f"تیکت {target_id}", "type": "ticket"}
        status = doc.get("status", "open")
        metadata = {key: doc.get(key) for key in ("priority", "assignee_name", "created_at", "last_reply_at", "tags")}
        if doc.get("user_id"):
            relations.append({"type": "user", "label": doc.get("user_name") or "کاربر", "id": doc.get("user_id"), "go": f"/users?q={doc.get('user_id')}"})
        actions = ["reply", "close"] if status != "closed" else ["reopen"]
    elif target_type == "role":
        doc = await db.get_role(target_id)
        if not doc: raise HTTPException(404, "نقش پیدا نشد")
        identity = {"id": target_id, "label": doc.get("label") or target_id, "type": "role"}
        status = "active" if doc.get("active", True) else "disabled"
        metadata = {"description": doc.get("description") or doc.get("desc"), "permissions": doc.get("perms") or [], "system": bool(doc.get("system"))}
        relations = [{"type": "user", "label": "اعضای نقش", "count": len(await db.user_ids_by_role(target_id, limit=100000)), "go": f"/users?role={target_id}"}]
        actions = [] if doc.get("system") else ["edit", "clone", "toggle", "delete"]
    elif target_type == "broadcast":
        oid = _oid(target_id)
        doc = await db.broadcast_campaigns.find_one({"_id": oid if oid else target_id})
        if not doc: raise HTTPException(404, "کمپین پیدا نشد")
        payload = doc.get("payload") or {}
        identity = {"id": target_id,
                    "label": (payload.get("text") or payload.get("caption") or f"[{doc.get('message_type','text')}]")[:120],
                    "type": "broadcast"}
        status = doc.get("status", "")
        metadata = {key: doc.get(key) for key in ("source", "message_type", "audience", "send_at", "created_at", "started_at", "finished_at", "total", "success", "failed", "skipped", "correlation_id")}
        relations = [{"type": "user", "label": "سازنده", "id": doc.get("created_by"),
                      "go": f"/users?q={doc.get('created_by')}"}] if doc.get("created_by") else []
        actions = ["cancel"] if status in ("queued", "scheduled") else ["retry_failed"] if doc.get("failed") else []
    elif target_type in ("payment", "subscription"):
        uid = int(target_id) if target_id.isdigit() else None
        if target_type == "payment":
            oid = _oid(target_id); doc = await db.sub_payments.find_one({"_id": oid if oid else target_id})
            uid = (doc or {}).get("user_id")
        else:
            doc = await db.sub_get(uid) if uid is not None else None
        if not doc: raise HTTPException(404, "رکورد اشتراک پیدا نشد")
        identity = {"id": target_id, "label": doc.get("plan_name") or f"اشتراک {target_id}", "type": target_type}
        status = doc.get("status", "")
        metadata = {key: doc.get(key) for key in ("amount", "final_price", "submitted_at", "start_date", "end_date", "discount_code")}
        if uid is not None: relations.append({"type": "user", "label": "دارنده", "id": uid, "go": f"/users?q={uid}"})
        actions = ["approve", "reject"] if target_type == "payment" and status == "pending" else []
    else:
        raise HTTPException(422, "خلاصه این نوع object هنوز پشتیبانی نمی‌شود")
    return {"identity": identity, "status": status, "metadata": metadata,
            "relations": relations, "available_actions": actions}


@router.get("/audit/correlation/{correlation_id}")
async def wa_correlation_chain(correlation_id: str, user=Depends(_perm("audit.view"))):
    correlation_id = correlation_id.strip()[:120]
    if not correlation_id: raise HTTPException(422, "Correlation ID الزامی است")
    audits, campaigns, outbox = await asyncio.gather(
        db.audit_logs.find({"correlation_id": correlation_id}).sort("timestamp", 1).limit(100).to_list(100),
        db.broadcast_campaigns.find({"correlation_id": correlation_id}).sort("created_at", 1).limit(20).to_list(20),
        db.bot_notifs.find({"correlation_id": correlation_id}).sort("created_at", 1).limit(100).to_list(100),
    )
    events = [{"id": f"audit:{row.get('_id')}", "stage": "audit", "title": row.get("action") or "Audit",
               "status": row.get("severity", "INFO"), "at": row.get("timestamp"),
               "metadata": {"module": row.get("module"), "target": row.get("target") or {}}} for row in audits]
    events.extend({"id": f"campaign:{row.get('_id')}", "stage": "campaign",
                   "title": ((row.get("payload") or {}).get("text") or (row.get("payload") or {}).get("caption") or "Broadcast Campaign")[:100],
                   "status": row.get("status", ""), "at": row.get("created_at"),
                   "metadata": {"source": row.get("source"), "total": row.get("total"),
                                "success": row.get("success"), "failed": row.get("failed")}}
                  for row in campaigns)
    events.extend({"id": f"outbox:{row.get('_id')}", "stage": "outbox",
                   "title": row.get("type") or "Outbox",
                   "status": "failed" if row.get("failed") else "sent" if row.get("sent") else "scheduled" if row.get("send_at") else "queued",
                   "at": row.get("sent_at") or row.get("created_at"),
                   "metadata": {"chat_id": row.get("chat_id"), "send_at": row.get("send_at")}}
                  for row in outbox)
    events.sort(key=lambda event: event.get("at") or "")
    return {"correlation_id": correlation_id, "events": events,
            "counts": {"audit": len(audits), "campaign": len(campaigns), "outbox": len(outbox)},
            "complete": bool(events)}


@router.get("/history/{target_type}/{target_id}")
async def object_history(
    target_type: str, target_id: str,
    limit: int = Query(30, ge=1, le=100),
    user=Depends(_guard_any_admin),
):
    """Timeline/diff عمومی objectها بر پایه audit مشترک، با RBAC هر domain."""
    await _require_object_permission(user, target_type)
    if target_type == "question":
        item = await db.get_question_by_id(target_id)
        if not item:
            raise HTTPException(404, "سؤال پیدا نشد")
        scope = await _question_scope_context(user)
        if scope.get("kind") == "scoped" and (item.get("intake") or "") != (scope.get("intake") or ""):
            raise HTTPException(403, "intake_out_of_scope")
    elif target_type == "user" and (not target_id.isdigit() or not await db.get_user(int(target_id))):
        raise HTTPException(404, "کاربر پیدا نشد")
    elif target_type == "ticket" and (not target_id.isdigit() or not await db.ticket_get(int(target_id))):
        raise HTTPException(404, "تیکت پیدا نشد")
    docs = await db.audit_logs.find({"$or": [
        {"target.type": target_type, "target.id": target_id},
        {"target_type": target_type, "target_id": target_id},
    ]}).sort("timestamp", -1).limit(limit).to_list(limit)
    return {"items": [{
        "id": str(d.get("_id", "")), "title": d.get("action", ""),
        "actor": (d.get("actor") or {}).get("name", ""),
        "actor_role": (d.get("actor") or {}).get("role", ""),
        "at": d.get("timestamp") or None,
        "description": d.get("details", ""), "severity": d.get("severity", "INFO"),
        "changes": d.get("changes") or [], "correlation_id": d.get("correlation_id"),
    } for d in docs], "target_type": target_type, "target_id": target_id}


class TicketsBulk(BaseModel):
    action: str           # close | reopen
    ids: list[int]


@router.post("/tickets/bulk")
async def tickets_bulk(body: TicketsBulk, user=Depends(_perm("tickets.manage"))):
    """⚡ اکشن گروهی تیکت (سقف ۱۰۰) — با همان متدهای موجود db."""
    await rate_limit_user(user["id"], "tickets_bulk", 10, 60)  # 🛡 W10
    ids = [int(i) for i in (body.ids or []) if isinstance(i, (int, str)) and str(i).isdigit()][:100]
    if not ids:
        raise HTTPException(400, "لیست تیکت‌ها خالی است")
    if body.action not in ("close", "reopen"):
        raise HTTPException(422, "اکشن گروهی نامعتبر است")
    succeeded, skipped, failed = [], [], []
    for tid in ids:
        try:
            t = await db.ticket_get(tid)
            if not t:
                skipped.append({"id": tid, "reason": "ticket_not_found"}); continue
            if body.action == "close":
                if t.get("status") == "closed":
                    skipped.append({"id": tid, "reason": "already_closed"}); continue
                await db.ticket_close(tid)
            else:
                # 🌊 W9 — بازگشایی از بسته یا حل‌شده
                if db.ticket_norm_status(t.get("status")) not in ("closed", "resolved"):
                    skipped.append({"id": tid, "reason": "already_open"}); continue
                await db.ticket_reopen(tid)
            succeeded.append(tid)
        except Exception:
            failed.append({"id": tid, "error": "operation_failed"})
    fa = {"close": "بستن گروهی", "reopen": "بازگشایی گروهی"}
    await _audit(user["id"], f"{fa[body.action]} تیکت ({len(succeeded)} مورد)",
                 severity="INFO", target_type="ticket_batch", target_label=f"{len(ids)} تیکت",
                 after={"action": body.action, "succeeded": len(succeeded),
                        "skipped": len(skipped), "failed": len(failed)},
                 tags=["bulk_tickets", "پنل_وب"])
    return {"ok": not failed, "done": len(succeeded), "succeeded": succeeded,
            "skipped": skipped, "failed": failed}


async def _question_scope_context(user: dict) -> dict:
    """Scope مستقل مجوز بازبینی سؤال؛ به content.manage وابسته نیست."""
    if await db.has_permission(user["id"], "questions.review"):
        return {"kind": "global", "intake": None}
    if await db.has_permission(user["id"], "questions.review_scoped"):
        scope = await db.get_scoped_intake(user["id"])
        if not scope:
            info = await db.get_user_roles(user["id"])
            scope = info.get("scope_intake")
        if scope:
            return {"kind": "scoped", "intake": scope}
    raise HTTPException(403, "question_scope_missing")


async def _question_admin(user: dict) -> dict:
    ctx = dict(user)
    ctx["_scope"] = await _question_scope_context(user)
    return ctx


@router.get("/questions")
async def wa_questions_list(
    status: str = Query("pending", pattern="^(pending|approved|rejected|needs_changes|all)$"),
    intake: Optional[str] = Query(None, max_length=80),
    q: Optional[str] = Query(None, max_length=120),
    lesson: Optional[str] = Query(None, max_length=100),
    topic: Optional[str] = Query(None, max_length=100),
    difficulty: Optional[str] = Query(None, pattern="^(easy|medium|hard)$"),
    source: Optional[str] = Query(None, max_length=40),
    author: Optional[str] = Query(None, max_length=100),
    date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
    skip: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100),
    sort_by: str = Query("created_at", pattern="^(created_at|attempt_count|correct_count|difficulty)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    user=Depends(_perm_any("questions.review", "questions.review_scoped")),
):
    """Question workspace سرورساید برای 10k+ سؤال، بدون تغییر endpoint قدیمی pending."""
    author = author if isinstance(author, str) else None
    date_from = date_from if isinstance(date_from, str) else None
    date_to = date_to if isinstance(date_to, str) else None
    scope = await _question_scope_context(user)
    if scope.get("kind") == "scoped":
        iv = scope.get("intake") or ""
        if intake not in (None, "", iv):
            raise HTTPException(403, "intake_out_of_scope")
    else:
        iv = intake if intake is not None else None
    filt = {"intake": iv} if iv is not None else {}
    if status != "all":
        lifecycle = status_query(status)
        if "$or" in lifecycle:
            filt["$and"] = [lifecycle]
        else:
            filt.update(lifecycle)
    if lesson:
        filt["lesson"] = lesson
    if topic:
        filt["topic"] = topic
    if difficulty:
        key = canonical_difficulty(difficulty)
        labels = {"easy": "آسان 🟢", "medium": "متوسط 🟡", "hard": "سخت 🔴"}
        filt["difficulty"] = {"$in": [key, labels[key]]}
    if source:
        filt["source"] = source
    if author and author.strip():
        author_value = author.strip()
        if author_value.isdigit():
            filt["creator_id"] = int(author_value)
        else:
            filt["creator_name"] = {"$regex": re.escape(author_value), "$options": "i"}
    if date_from or date_to:
        created = {}
        try:
            if date_from:
                created["$gte"] = day_bounds_utc(parse_gregorian_date(date_from))[0].isoformat()
            if date_to:
                created["$lt"] = day_bounds_utc(parse_gregorian_date(date_to))[1].isoformat()
        except ValueError:
            raise HTTPException(422, "بازه تاریخ سؤال معتبر نیست")
        filt["created_at"] = created
    if q and q.strip():
        term = q.strip()
        rx = {"$regex": re.escape(term), "$options": "i"}
        options = [{"question": rx}, {"lesson": rx}, {"topic": rx}, {"creator_name": rx}]
        oid = _oid(term)
        if oid: options.append({"_id": oid})
        filt["$or"] = options
    total = await db.questions.count_documents(filt)
    docs = await (db.questions.find(filt)
                  .sort(sort_by, 1 if sort_dir == "asc" else -1)
                  .skip(skip).limit(limit).to_list(limit))
    # §W10 — تأیید هم مثلِ بقیه باید مجوز بخواهد. پیش‌تر `can_approve`
    # هیچ مجوزی نمی‌سنجید و به‌جایش «سازنده نبودن» را شرط کرده بود.
    can_review = (await db.has_permission(user["id"], "questions.review")
                  or await db.has_permission(user["id"], "questions.review_scoped"))
    can_reject = await db.has_permission(user["id"], "questions.reject")
    can_edit = await db.has_permission(user["id"], "questions.edit")
    # 🛡 §۸۴ — پرچمِ حذف، هم‌شکل با can_reject/can_edit تا UI خودش
    # تصمیم نگیرد. سؤالِ تأییدشده قفل است، پس پرچم روی آن خاموش می‌ماند.
    can_delete = await db.has_permission(user["id"], "questions.delete")
    rows = []
    for d in docs:
        attempts = int(d.get("attempt_count") or 0)
        correct = int(d.get("correct_count") or 0)
        rows.append({
            "id": str(d.get("_id", "")), "lesson_id": str(d.get("lesson_id") or ""),
            "topic_id": str(d.get("topic_id") or ""), "lesson": d.get("lesson", ""),
            "topic": d.get("topic", ""), "difficulty": canonical_difficulty(d.get("difficulty"), strict=False),
            "question": d.get("question", ""), "options": d.get("options", []),
            "correct": d.get("correct_answer", 0), "explanation": d.get("explanation", ""),
            "creator_id": d.get("creator_id"), "creator_name": d.get("creator_name", ""),
            "created_at": d.get("created_at") or None, "updated_at": d.get("updated_at") or None,
            "intake": d.get("intake", ""), "source": d.get("source", "system"),
            "creator_type": d.get("creator_type", "student"),
            "status": canonical_status(d), "approved": canonical_status(d) == "approved",
            "review_reason": d.get("review_reason", ""), "reviewed_by": d.get("reviewed_by"),
            "reviewed_at": d.get("reviewed_at"), "version": int(d.get("version") or 1),
            "attempts": attempts,
            "accuracy": round(correct * 100 / attempts, 1) if attempts else 0,
            "reports": int(d.get("report_count") or 0),
            # §W10 — پرچم‌ها با قانونِ واقعیِ سرور هم‌راستا شدند:
            #  • تأیید: مجوزِ بررسی لازم است (نه «سازنده نبودن»). قانونِ
            #    ضدِ خودتأییدی برداشته شد چون روی نصبِ تک‌ادمینه سؤال را
            #    برای همیشه قفل می‌کرد.
            #  • ویرایش/رد: دیگر به `pending` محدود نیستند — موجِ ۷ این
            #    را در ربات باز کرد و پنل عقب مانده بود. سؤالِ تأییدشده
            #    باید قابلِ اصلاح باشد وگرنه گزارشِ دانشجو بن‌بست می‌خورد.
            "can_approve": canonical_status(d) == "pending" and can_review,
            "can_reject": canonical_status(d) != "rejected" and can_reject,
            "can_edit": can_edit,
            "can_delete": canonical_status(d) != "approved" and can_delete,
        })
    return {"questions": rows, "total": total, "skip": skip, "limit": limit,
            "pages": (total + limit - 1) // limit, "status": status, "intake": iv}


class WebAdminQuestionCreate(BaseModel):
    lesson_id: Optional[str] = None
    topic_id: Optional[str] = None
    lesson: str = Field(min_length=1, max_length=100)
    topic: str = Field(min_length=1, max_length=100)
    difficulty: str = Field(pattern="^(easy|medium|hard)$")
    question: str = Field(min_length=10, max_length=2000)
    options: list[str] = Field(min_length=4, max_length=4)
    correct_answer: int = Field(ge=0, le=3)
    explanation: str = Field(default="", max_length=4000)
    intake: Optional[str] = Field(default=None, max_length=80)


@router.post("/questions")
async def wa_question_create(
    body: WebAdminQuestionCreate,
    user=Depends(_perm_any("questions.review", "questions.review_scoped")),
):
    actor = await _question_admin(user)
    try:
        # §W10 — یکپارچگی با ربات (موجِ ۶): ادمینِ دارای `questions.review`
        # از پنل هم مستقیم ثبت می‌کند. اعتماد در لایهٔ دامنه دوباره با
        # RBAC سنجیده می‌شود، پس این پرچم به‌تنهایی چیزی را دور نمی‌زند.
        direct = await db.has_permission(user["id"], "questions.review")
        result = await question_bank.create_question(
            actor=actor, payload=body.model_dump(), source="web_admin",
            creator_type="admin", auto_approve=direct, intake=body.intake)
    except QuestionDomainError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message,
                                              "details": exc.details})
    document = result["question"]
    final_status = canonical_status(document)
    await _audit(user["id"],
                 "ثبت مستقیم سؤال" if final_status == "approved"
                 else "ساخت سؤال و ارسال به بازبینی مستقل", severity="INFO",
                 target_type="question", target_id=str(document["_id"]),
                 target_label=document.get("question", "")[:100],
                 after={"status": final_status, "intake": document.get("intake", "")},
                 tags=["بانک_سؤال", "ساخت",
                       "ثبت_مستقیم" if final_status == "approved" else "بازبینی_مستقل"])
    return {"ok": True, "question_id": str(document["_id"]), "status": final_status}


@router.get("/exports/questions.csv")
async def export_questions_csv(
    status: str = Query("pending", pattern="^(pending|approved|rejected|needs_changes|all)$"),
    intake: Optional[str] = Query(None), q: Optional[str] = Query(None),
    lesson: Optional[str] = Query(None), topic: Optional[str] = Query(None),
    difficulty: Optional[str] = Query(None), source: Optional[str] = Query(None),
    author: Optional[str] = Query(None), date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    sort_by: str = Query("created_at", pattern="^(created_at|attempt_count|correct_count|difficulty)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"), human: bool = False,
    user=Depends(_perm_any("questions.review", "questions.review_scoped")),
):
    """خروجی سؤال با همان scope/filter/sort جدول؛ داده در مرورگر تجمیع نمی‌شود."""
    await _audit(user["id"], "خروجی CSV سؤال‌ها", severity="HIGH",
                 target_type="export", target_label="questions.csv",
                 tags=["خروجی", "سؤال", "پنل_وب"])
    columns = ["id", "question", "lesson", "topic", "difficulty", "status", "intake",
               "creator_id", "creator_name", "source", "attempts", "accuracy", "created_at"]
    def safe(value):
        text = "" if value is None else str(value)
        return "'" + text if text[:1] in ("=", "+", "-", "@") else text
    async def stream():
        buf = io.StringIO(); writer = csv.writer(buf); writer.writerow(columns)
        yield "\ufeff" + buf.getvalue(); buf.seek(0); buf.truncate(0)
        skip = 0
        while True:
            result = await wa_questions_list(
                status=status, intake=intake, q=q, lesson=lesson, topic=topic,
                difficulty=difficulty, source=source, author=author,
                date_from=date_from, date_to=date_to, skip=skip, limit=100, sort_by=sort_by, sort_dir=sort_dir, user=user)
            rows = result.get("questions") or []
            for row in rows:
                writer.writerow([safe(v) for v in [row.get("id"), row.get("question"),
                    row.get("lesson"), row.get("topic"), row.get("difficulty"),
                    "approved" if row.get("approved") else "pending", row.get("intake"),
                    row.get("creator_id"), row.get("creator_name"), row.get("source"),
                    row.get("attempts"), row.get("accuracy"), _export_instant(row.get("created_at"), human)]])
                yield buf.getvalue(); buf.seek(0); buf.truncate(0)
            skip += len(rows)
            if not rows or skip >= int(result.get("total") or 0): break
    return StreamingResponse(stream(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=humsyar-questions.csv"})


@router.get("/questions/taxonomy")
async def wa_question_taxonomy(
    intake: Optional[str] = Query(None, max_length=80),
    user=Depends(_perm_any("questions.review", "questions.review_scoped")),
):
    scope = await _question_scope_context(user)
    if scope["kind"] == "scoped":
        if intake not in (None, "", scope["intake"]):
            raise HTTPException(403, "intake_out_of_scope")
        visible = [scope["intake"], ""]
    else:
        visible = [intake, ""] if intake else None
    return {"lessons": await question_bank.taxonomy_tree(
        visible_intakes=visible, only_with_questions=False),
        "intake": scope.get("intake") if scope["kind"] == "scoped" else intake}


@router.get("/questions/intakes")
async def wa_question_intakes(
    user=Depends(_perm_any("questions.review", "questions.review_scoped")),
):
    return await content_api.content_intakes(admin=await _question_admin(user))


@router.get("/questions/pending")
async def wa_questions_pending(
    intake: Optional[str] = Query(None),
    user=Depends(_perm_any("questions.review", "questions.review_scoped")),
):
    return await content_api.pending_questions(
        intake=intake, skip=0, limit=100, admin=await _question_admin(user))


@router.post("/questions/{qid}/approve")
async def wa_question_approve(
    qid: str, body: content_api.QuestionReviewInput = None,
    user=Depends(_perm_any("questions.review", "questions.review_scoped")),
):
    return await content_api.approve_question(qid=qid, body=body, admin=await _question_admin(user))


@router.post("/questions/{qid}/reject")
async def wa_question_reject(
    qid: str, body: content_api.QuestionReviewInput,
    user=Depends(_perm_any("questions.reject", "questions.review")),
):
    return await content_api.reject_question(qid=qid, body=body, admin=await _question_admin(user))


@router.post("/questions/{qid}/needs-changes")
async def wa_question_needs_changes(
    qid: str, body: content_api.QuestionReviewInput,
    user=Depends(_perm_any("questions.reject", "questions.review")),
):
    return await content_api.needs_changes_question(qid=qid, body=body,
                                                     admin=await _question_admin(user))


# ── §W9 — گزارش‌های سؤال در پنلِ وب ──────────────────────────────
#
# هر دو مسیر صرفاً به `content_admin` delegate می‌کنند تا قانونِ scope،
# حریمِ گزارش‌دهنده و آستانه‌ها یک‌جا بمانند (بدونِ سیستمِ دوم).
@router.get("/questions/reported")
async def wa_reported_questions(
    intake: Optional[str] = Query(None),
    min_reports: int = Query(1, ge=1, le=1000),
    skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
    user=Depends(_perm_any("questions.review", "questions.review_scoped")),
):
    """فهرستِ سؤالاتِ گزارش‌دار — نشانگرِ «⚠️ n گزارش» در پنل."""
    return await content_api.reported_questions(
        admin=user, intake=intake, min_reports=min_reports,
        skip=skip, limit=limit)


@router.get("/questions/{qid}/reports")
async def wa_question_reports(
    qid: str, limit: int = Query(50, ge=1, le=200),
    user=Depends(_perm_any("questions.review", "questions.review_scoped")),
):
    """نمای تجمیعیِ گزارش‌های یک سؤال."""
    return await content_api.question_reports(qid=qid, admin=user, limit=limit)


# ══════════════════════════════════════════════════════════════════
# 🌊 WA22 — Question Health + Question 360
#
# «سلامت سؤال» ویژگیِ اختراعی نیست؛ ترکیب سیگنال‌هایی است که همین حالا
# در داده وجود دارد و فقط نمایشِ مدیریتی نداشتند:
#   • شمارنده‌های attempt_count/correct_count روی خود سند سؤال
#     (در هر پاسخِ آزمون db/content.py افزایش می‌دهد)
#   • گزارش‌های باز در content_reports (status new/reviewing)
#   • نبود توضیح پاسخ برای سؤالی که در آزمون استفاده شده
# Question 360 هم همان الگوی User 360 (§WA2.8) است: پرونده‌ی کامل یک
# سؤال بدون ترک صفحه؛ هر بخش جدا ضدخطا (Empty و Unavailable دو حالت‌اند).
# ══════════════════════════════════════════════════════════════════

_HEALTH_MIN_ATTEMPTS = 5     # کمتر از این تعداد تلاش، نرخ غلط معنادار نیست
_HEALTH_WRONG_RATE = 0.60    # آستانه‌ی «نرخ غلط بحرانی»
_HEALTH_BORDER_RATE = 0.40   # آستانه‌ی مرزی


def _qid_filter(qid: str) -> dict:
    """‏_id سؤال در این repo دو شکل دارد: ObjectId (production) و str
    (dev/تست). هر دو شکل جست‌وجو می‌شود — فرض روی یکی ممنوع."""
    variants = [{"_id": qid}]
    if ObjectId.is_valid(qid):
        variants.append({"_id": ObjectId(qid)})
    return variants[0] if len(variants) == 1 else {"$or": variants}


def _question_health(q, open_reports: int) -> dict:
    """امتیاز بیماری ۰..۱۰۰ (بیشتر = بدتر) + ریز اجزا برای نمایش و تست."""
    attempts = int(q.get("attempt_count") or 0)
    correct = int(q.get("correct_count") or 0)
    wrong_rate = round((attempts - correct) / attempts, 3) if attempts > 0 else 0.0
    signals, points = [], 0
    if open_reports > 0:
        points += 45
        signals.append({"key": "open_reports", "points": 45,
                        "label": f"{open_reports} گزارش باز"})
    if attempts >= _HEALTH_MIN_ATTEMPTS:
        if wrong_rate >= _HEALTH_WRONG_RATE:
            points += 45
            signals.append({"key": "wrong_rate", "points": 45,
                            "label": f"نرخ پاسخ غلط {int(round(wrong_rate * 100))}٪"})
        elif wrong_rate >= _HEALTH_BORDER_RATE:
            points += 20
            signals.append({"key": "wrong_rate", "points": 20,
                            "label": f"نرخ پاسخ غلط مرزی {int(round(wrong_rate * 100))}٪"})
    if attempts > 0 and not clean_text(q.get("explanation")):
        points += 10
        signals.append({"key": "no_explanation", "points": 10,
                        "label": "بدون توضیح پاسخ"})
    return {
        "score": min(100, points),
        "needs_review": bool(open_reports > 0 or (
            attempts >= _HEALTH_MIN_ATTEMPTS and wrong_rate >= _HEALTH_WRONG_RATE)),
        "components": {
            "open_reports": open_reports, "attempts": attempts,
            "correct": correct, "wrong_rate": wrong_rate,
            "has_explanation": bool(clean_text(q.get("explanation"))),
        },
        "signals": signals,
    }


@router.get("/questions/health")
async def wa_questions_health(
    limit: int = Query(50, ge=1, le=200),
    include_healthy: bool = Query(False),
    user=Depends(_perm_any("questions.review", "questions.review_scoped")),
):
    """🌊 WA22 — صف سلامت سؤال‌ها: بدترین‌ها اول.

    مجموعه‌ی نامزد کرانه‌دار است (اسکن کل کالکشن ممنوع): سؤال‌های دارای
    گزارش باز + ۵۰۰ پرسوالِ پرتلاش. Scope همان قوانین لیست سؤال است
    (questions.review_scoped فقط ورودی خودش را می‌بیند)."""
    scope = await _question_scope_context(user)
    base = {"intake": scope.get("intake") or ""} if scope.get("kind") == "scoped" else {}
    rep_docs = await db.content_reports.aggregate([
        {"$match": {"target_type": "question",
                    "status": {"$in": ["new", "reviewing"]}}},
        {"$group": {"_id": "$target_id", "n": {"$sum": 1}}},
    ]).to_list(length=5000)
    rep = {str(r["_id"]): int(r["n"]) for r in rep_docs if r.get("_id")}
    cand = []
    for t in rep:
        cand.append(t)
        if ObjectId.is_valid(t):
            cand.append(ObjectId(t))
    by_id = {}
    if cand:
        async for q in db.questions.find({**base, "_id": {"$in": cand}}):
            by_id[str(q["_id"])] = q
    async for q in db.questions.find(
            base, sort=[("attempt_count", -1)], limit=500):
        by_id.setdefault(str(q["_id"]), q)
    rows = []
    for q in by_id.values():
        health = _question_health(q, rep.get(str(q["_id"]), 0))
        if not include_healthy and health["score"] <= 0:
            continue
        rows.append({
            "id": str(q["_id"]),
            "question": clean_text(q.get("question"), 120),
            "lesson": q.get("lesson", ""), "topic": q.get("topic", ""),
            "difficulty": q.get("difficulty", ""),
            "status": canonical_status(q), "intake": q.get("intake", ""),
            "attempt_count": int(q.get("attempt_count") or 0),
            "correct_count": int(q.get("correct_count") or 0),
            "wrong_rate": health["components"]["wrong_rate"],
            "score": health["score"], "needs_review": health["needs_review"],
            "signals": health["signals"],
        })
    rows.sort(key=lambda r: (-r["score"], -r["attempt_count"]))
    return {"items": rows[:limit],
            "summary": {"considered": len(rows),
                        "needs_review": sum(1 for r in rows if r["needs_review"]),
                        "min_attempts": _HEALTH_MIN_ATTEMPTS,
                        "wrong_rate_threshold": _HEALTH_WRONG_RATE,
                        "checked_at": _now()}}


@router.get("/questions/{qid}/360")
async def wa_question_360(
        qid: str,
        user=Depends(_perm_any("questions.review", "questions.review_scoped"))):
    """🌊 WA22 — نمای ۳۶۰ درجه‌ی سؤال: پرونده + سلامت + گزارش‌ها + آزمون واقعی.

    همان قرارداد User 360: هر بخش جدا ضدخطا؛ خطای بخش در section_errors
    می‌نشیند و بقیه‌ی پاسخ سالم می‌ماند."""
    q = await db.questions.find_one(_qid_filter(qid))
    if not q:
        raise HTTPException(404, "سؤال پیدا نشد")
    qid_s = str(q["_id"])
    out = {"question": {
        "id": qid_s, "question": q.get("question", ""),
        "options": q.get("options") or [],
        "correct_answer": q.get("correct_answer"),
        "explanation": q.get("explanation") or "",
        "lesson": q.get("lesson", ""), "topic": q.get("topic", ""),
        "difficulty": q.get("difficulty", ""),
        "status": canonical_status(q), "intake": q.get("intake", ""),
        "source": q.get("source", ""), "creator_id": q.get("creator_id"),
        "creator_name": q.get("creator_name", ""),
        "created_at": q.get("created_at") or None,
        "attempt_count": int(q.get("attempt_count") or 0),
        "correct_count": int(q.get("correct_count") or 0),
        "twins": 0,
    }, "health": None, "reports": None, "exams": None, "section_errors": {}}
    try:
        if q.get("content_hash"):
            out["question"]["twins"] = await db.questions.count_documents(
                {"content_hash": q["content_hash"], "_id": {"$ne": q["_id"]}})
    except Exception:
        out["section_errors"]["twins"] = "unavailable"
    try:
        open_reports = await db.content_reports.count_documents(
            {"target_type": "question", "target_id": qid_s,
             "status": {"$in": ["new", "reviewing"]}})
        out["health"] = _question_health(q, open_reports)
    except Exception:
        out["section_errors"]["health"] = "unavailable"
    try:
        total = await db.content_reports.count_documents(
            {"target_type": "question", "target_id": qid_s})
        open_n = await db.content_reports.count_documents(
            {"target_type": "question", "target_id": qid_s,
             "status": {"$in": ["new", "reviewing"]}})
        recent = await db.content_reports.find(
            {"target_type": "question", "target_id": qid_s}
        ).sort("created_at", -1).limit(20).to_list(length=20)
        out["reports"] = {
            "total": total, "open": open_n,
            "recent": [{
                "report_id": r.get("report_id"), "reason": r.get("reason", ""),
                "note": r.get("note", ""), "status": r.get("status", ""),
                "user_name": r.get("user_name", ""),
                "reporter_id": r.get("user_id"),
                "created_at": r.get("created_at") or None,
            } for r in recent],
        }
    except Exception:
        out["section_errors"]["reports"] = "unavailable"
    try:
        agg = await db.exam_sessions.aggregate([
            {"$match": {"answers.question_id": qid_s}},
            {"$unwind": "$answers"},
            {"$match": {"answers.question_id": qid_s}},
            {"$group": {"_id": None, "attempts": {"$sum": 1},
                        "correct": {"$sum": {
                            "$cond": ["$answers.is_correct", 1, 0]}}}},
        ]).to_list(length=1)
        sessions = await db.exam_sessions.find(
            {"answers.question_id": qid_s}
        ).sort("started_at", -1).limit(10).to_list(length=10)
        recent_answers = []
        for s in sessions:
            for a in (s.get("answers") or []):
                if str(a.get("question_id")) == qid_s:
                    recent_answers.append({
                        "session_id": s.get("session_id") or str(s["_id"]),
                        "user_id": s.get("user_id"),
                        "is_correct": bool(a.get("is_correct")),
                        "selected": a.get("selected"),
                        "at": a.get("answered_at") or s.get("started_at") or None,
                    })
        out["exams"] = {
            "attempts": int(agg[0]["attempts"]) if agg else 0,
            "correct": int(agg[0]["correct"]) if agg else 0,
            "recent": recent_answers[:10],
        }
    except Exception:
        out["section_errors"]["exams"] = "unavailable"
    return out


@router.delete("/questions/{qid}")
async def wa_question_delete(
    qid: str, reason: str = Query(default="", max_length=1000),
    user=Depends(_perm_any("questions.delete")),
):
    """🛡 §۸۴ — حذف سخت سؤال. گیتِ لبه `questions.delete` است و همان مجوز
    دوباره داخل `question_bank` هم بررسی می‌شود (دفاع در عمق)."""
    return await content_api.delete_question(
        qid=qid, reason=reason, admin=await _question_admin(user))


@router.patch("/questions/{qid}")
async def wa_question_patch(
    qid: str, body: content_api.QuestionPatch,
    user=Depends(_perm_any("questions.edit", "questions.review", "questions.review_scoped")),
):
    return await content_api.patch_question(
        qid=qid, body=body, admin=await _question_admin(user))


@router.post("/questions/bulk-import")
async def wa_questions_import(
    body: content_api.QuestionImportBody,
    intake: Optional[str] = Query(None),
    user=Depends(_perm_any("questions.review", "questions.review_scoped")),
):
    return await content_api.bulk_import_questions(
        body=body, intake=intake, admin=await _question_admin(user))


class QuestionsBulk(BaseModel):
    action: str           # approve | reject | needs_changes | metadata
    ids: list[str]
    patch: Optional[dict] = None
    reason: str = ""


@router.post("/questions/bulk")
async def questions_bulk(
    body: QuestionsBulk,
    user=Depends(_perm_any("questions.review", "questions.review_scoped")),
):
    """تغییر گروهی با همان lifecycle نرم، permission و scope مسیر تکی."""
    ids = [str(i) for i in (body.ids or [])][:100]
    if not ids:
        raise HTTPException(400, "لیست سؤال‌ها خالی است")
    if body.action not in ("approve", "reject", "needs_changes", "metadata"):
        raise HTTPException(400, "اکشن نامعتبر است")
    if body.action in ("reject", "needs_changes") and not await db.has_permission(user["id"], "questions.reject"):
        raise HTTPException(403, "questions.reject required")
    if body.action == "metadata" and not await db.has_permission(user["id"], "questions.edit"):
        raise HTTPException(403, "questions.edit required")
    if body.action in ("reject", "needs_changes") and len(body.reason.strip()) < 3:
        raise HTTPException(422, "دلیل بررسی الزامی است")
    patch_body = None
    if body.action == "metadata":
        allowed = {key: value for key, value in (body.patch or {}).items()
                   if key in ("lesson", "topic", "difficulty") and value not in (None, "")}
        if not allowed: raise HTTPException(422, "حداقل یک metadata معتبر لازم است")
        try: patch_body = content_api.QuestionPatch(**allowed)
        except Exception: raise HTTPException(422, "metadata سؤال معتبر نیست")
    succeeded, skipped, failed = [], [], []
    scope = await _question_scope_context(user)
    question_admin = dict(user); question_admin["_scope"] = scope
    for qid in ids:
        try:
            q = await db.get_question_by_id(qid)
            if not q:
                skipped.append({"id": qid, "reason": "question_not_found"}); continue
            if canonical_status(q) == "approved":
                skipped.append({"id": qid, "reason": "already_approved"}); continue
            # scope مستقل permission سؤال؛ نقش سفارشی مجبور به content.manage نیست.
            if (scope.get("kind") == "scoped"
                    and (q.get("intake") or "") != (scope.get("intake") or "")):
                skipped.append({"id": qid, "reason": "intake_out_of_scope"}); continue
            if body.action == "approve":
                await question_bank.transition(question_id=qid, reviewer=user,
                                               target="approved", reason=body.reason)
            elif body.action == "metadata":
                await content_api.patch_question(qid=qid, body=patch_body, admin=question_admin)
            else:
                await question_bank.transition(question_id=qid, reviewer=user,
                                               target=body.action, reason=body.reason)
            succeeded.append(qid)
        except QuestionDomainError as exc:
            skipped.append({"id": qid, "reason": exc.code})
        except Exception:
            failed.append({"id": qid, "error": "operation_failed"})
    fa = {"approve": "تأیید گروهی", "reject": "رد گروهی",
          "needs_changes": "درخواست اصلاح گروهی", "metadata": "ویرایش گروهی metadata"}
    await _audit(user["id"], f"{fa[body.action]} سؤال‌ها ({len(succeeded)} مورد)",
                 severity="INFO", target_type="question_batch", target_label=f"{len(ids)} سؤال",
                 after={"action": body.action, "requested": len(ids), "reason": body.reason,
                        "patch_fields": list((body.patch or {}).keys()) if body.action == "metadata" else [],
                        "succeeded": len(succeeded), "skipped": len(skipped), "failed": len(failed)},
                 tags=["bulk_questions", "پنل_وب"])
    return {"ok": not failed, "done": len(succeeded), "succeeded": succeeded,
            "skipped": skipped, "failed": failed}


class QuestionsExportPdfInput(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=100)
    mode: str = Field(default="practice", pattern="^(practice|exam)$")


@router.post("/questions/export/pdf")
async def questions_export_pdf(
    body: QuestionsExportPdfInput,
    user=Depends(_perm_any("questions.review", "questions.review_scoped", "questions.edit")),
):
    """📄 خروجی PDF از سؤال‌های منتخب — پرمیوم Hamsyar (practice/exam).

    حد ۱۰۰ سؤال، با موتور مشترک qbank.generate_exam_pdf تا طراحی و فونت
    دقیقاً یکدست با ربات/مینی‌اپ باشد. دسترسی: questions.review یا scoped.
    """
    ids = [str(x).strip() for x in (body.ids or []) if str(x).strip()][:100]
    if not ids:
        raise HTTPException(400, "لیست سؤال‌ها خالی است")
    if body.mode not in ("practice", "exam"):
        raise HTTPException(400, "mode نامعتبر است")
    from bson import ObjectId
    # scope-aware fetch (scoped admin فقط intake خودش را ببیند)
    scope = await _question_scope_context(user)
    oids = [ObjectId(x) for x in ids if ObjectId.is_valid(x)]
    if len(oids) != len(ids):
        raise HTTPException(422, "شناسه‌ی برخی سؤال‌ها معتبر نیست")
    docs = await db.questions.find({"_id": {"$in": oids}}).to_list(len(oids))
    by_id = {str(d["_id"]): d for d in docs}
    # preserve order of input, skip missing/out-of-scope
    ordered = []
    for qid in ids:
        doc = by_id.get(qid)
        if not doc:
            continue
        if scope.get("kind") == "scoped" and (doc.get("intake") or "") != (scope.get("intake") or ""):
            continue
        ordered.append(doc)
    if not ordered:
        raise HTTPException(404, "هیچ سؤال در دسترس/هم‌راستا با intake شما پیدا نشد")
    # meta
    from qbank.query import ExamMeta
    from qbank import generate_exam_pdf
    # lesson/topic از اکثریت
    from collections import Counter
    lesson = Counter([d.get("lesson","") for d in ordered]).most_common(1)[0][0] or "بانک سوال — منتخب"
    topic = Counter([d.get("topic","") for d in ordered if d.get("topic")]).most_common(1)
    topic_val = topic[0][0] if topic else ""
    meta = ExamMeta(
        lesson=lesson,
        topic=topic_val,
        difficulty=None,
        student_name=user.get("name") or user.get("username") or "",
        exam_code=f"SEL-{len(ordered):02d}-" + "".join(ids[0][-4:]) if ids else "SEL",
        chapter=None,
    )
    try:
        pdf_bytes = generate_exam_pdf(ordered, meta, mode=body.mode)
    except Exception as exc:
        raise HTTPException(500, f"ساخت PDF ناموفق بود: {exc}")
    filename = f"humsyar-questions-" + ("practice" if body.mode=="practice" else "exam") + f"-{len(ordered)}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Question-Count": str(len(ordered)),
            "X-PDF-Mode": body.mode,
        },
    )


# ── Question Bank JSON ingestion (owner-only, preview-first) ──────
@router.get("/questions/import/prompt")
async def question_import_prompt(user=Depends(_perm("questions.import"))):
    return question_imports.prompt()


@router.post("/questions/import/upload")
async def question_import_upload(file: UploadFile = File(...), user=Depends(_perm("questions.import"))):
    raw = await file.read(10 * 1024 * 1024 + 1)
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "حجم فایل JSON بیشتر از ۱۰MB است")
    if not raw:
        raise HTTPException(422, "فایل خالی است")
    try:
        preview = await question_imports.create_preview(
            admin=user, raw=raw, file_name=file.filename or "questions.json")
    except QuestionDomainError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message})
    await _audit(user["id"], "بارگذاری JSON بانک سؤال برای پیش‌نمایش", severity="HIGH",
                 target_type="question_import", target_id=preview["job_id"],
                 target_label=file.filename or "questions.json",
                 after={"schema_version": preview["schema_version"], **preview["counts"]},
                 tags=["بانک_سؤال", "درون‌ریزی", "پیش‌نمایش"])
    return preview


@router.get("/questions/import/{job_id}")
async def question_import_preview(job_id: str, user=Depends(_perm("questions.import"))):
    try:
        preview = await question_imports.preview(job_id)
    except QuestionDomainError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message})
    job = await db.question_import_jobs.find_one({"_id": job_id, "admin_id": user["id"]})
    if not job: raise HTTPException(404, "job پیدا نشد")
    return preview


@router.get("/questions/import/{job_id}/items")
async def question_import_items(job_id: str, classification: Optional[str] = Query(None),
                                skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                                user=Depends(_perm("questions.import"))):
    if not await db.question_import_jobs.find_one({"_id": job_id, "admin_id": user["id"]}, {"_id": 1}):
        raise HTTPException(404, "job پیدا نشد")
    return await question_imports.list_items(job_id, classification=classification, skip=skip, limit=limit)


class ImportMapInput(BaseModel):
    lesson_id: str
    topic_id: str


@router.patch("/questions/import/{job_id}/items/{item_id}/mapping")
async def question_import_mapping(job_id: str, item_id: str, body: ImportMapInput,
                                  user=Depends(_perm("questions.import"))):
    if not await db.question_import_jobs.find_one({"_id": job_id, "admin_id": user["id"]}, {"_id": 1}):
        raise HTTPException(404, "job پیدا نشد")
    try:
        result = await question_imports.map_item(job_id=job_id, item_id=item_id,
                                                 lesson_id=body.lesson_id, topic_id=body.topic_id)
    except QuestionDomainError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message})
    await _audit(user["id"], "نگاشت taxonomy ردیف import سؤال", severity="HIGH",
                 target_type="question_import_item", target_id=item_id,
                 after={"job_id": job_id, "lesson_id": body.lesson_id, "topic_id": body.topic_id,
                        "classification": result.get("classification")},
                 tags=["بانک_سؤال", "درون‌ریزی", "نگاشت"])
    return result


class ImportDecisionInput(BaseModel):
    decision: str = Field(pattern="^(import|skip)$")


@router.patch("/questions/import/{job_id}/items/{item_id}/decision")
async def question_import_decision(job_id: str, item_id: str, body: ImportDecisionInput,
                                   user=Depends(_perm("questions.import"))):
    if not await db.question_import_jobs.find_one({"_id": job_id, "admin_id": user["id"]}, {"_id": 1}):
        raise HTTPException(404, "job پیدا نشد")
    try:
        result = await question_imports.set_decision(job_id=job_id, item_id=item_id,
                                                      decision=body.decision)
    except QuestionDomainError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message})
    await _audit(user["id"], "تصمیم ردیف import سؤال", severity="HIGH",
                 target_type="question_import_item", target_id=item_id,
                 after={"job_id": job_id, "decision": body.decision},
                 tags=["بانک_سؤال", "درون‌ریزی", "تصمیم"])
    return result


@router.post("/questions/import/{job_id}/confirm")
async def question_import_confirm(job_id: str, user=Depends(_perm("questions.import"))):
    try:
        result = await question_imports.confirm(job_id=job_id, admin=user)
    except QuestionDomainError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message})
    await _audit(user["id"], "تأیید نهایی درون‌ریزی بانک سؤال", severity="CRITICAL",
                 target_type="question_import", target_id=job_id, target_label=job_id,
                 after={"imported": result.get("imported", 0), "skipped": result.get("skipped", 0),
                        "failed": result.get("failed", 0), "idempotent": result.get("idempotent", False)},
                 tags=["بانک_سؤال", "درون‌ریزی", "تأیید_نهایی"])
    return result


@router.post("/questions/import/{job_id}/cancel")
async def question_import_cancel(job_id: str, user=Depends(_perm("questions.import"))):
    try: result = await question_imports.cancel(job_id=job_id, admin_id=user["id"])
    except QuestionDomainError as exc: raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message})
    await _audit(user["id"], "لغو درون‌ریزی بانک سؤال", severity="INFO",
                 target_type="question_import", target_id=job_id, target_label=job_id)
    return result


# ══════════════════════════════════════════════════════════════════
# 🌊 WA2.3 — مرکز کنترل تنظیمات (+ Last-Modified-By/At)
# ══════════════════════════════════════════════════════════════════

# (key, label, توضیح, نوع, perm, severity-لاگ)
_SETTINGS_CATALOG = [
    ("general", [
        ("maintenance_mode", "حالت تعمیر و نگهداشت",
         "وقتی روشن است، ربات برای کاربران عادی پیام تعمیرات نشان می‌دهد",
         "bool", "settings.manage", "CRITICAL"),
        ("maintenance_text", "متن حالت تعمیر",
         "متن نمایشی به کاربران هنگام حالت تعمیر (حداکثر ۴۰۰ کاراکتر)",
         "text", "settings.manage", "HIGH"),
        ("require_student_id", "الزام شماره دانشجویی",
         "ثبت‌نام بدون شماره دانشجویی ممکن نمی‌شود",
         "bool", "settings.manage", "HIGH"),
    ]),
    ("logs", [
        ("log_group_admin", "گروه لاگ مدیریت",
         "آیدی عددی گروه تلگرام لاگ‌های مدیریتی (عدد منفی؛ خالی=حذف)",
         "group", "settings.manage", "HIGH"),
        ("log_group_content", "گروه لاگ محتوا",
         "آیدی عددی گروه تلگرام لاگ‌های محتوایی (عدد منفی؛ خالی=حذف)",
         "group", "settings.manage", "HIGH"),
    ]),
    ("donation", [
        ("donation_enabled", "بخش حمایت مالی",
         "نمایش دکمه‌ی حمایت مالی در ربات/مینی‌اپ",
         "bool", "settings.manage", "HIGH"),
        ("donation_link", "لینک حمایت مالی",
         "آدرس صفحه‌ی حمایت (با http/https؛ خالی=حذف)",
         "link", "settings.manage", "HIGH"),
    ]),
    # 🌊 W6/MISS-03 — trial اشتراک
    ("subscription", [
        ("trial_enabled", "دوره‌ی آزمایشی",
         "نمایش و امکان دریافت trial برای کاربران بدون اشتراک",
         "bool", "subscription.manage", "HIGH"),
        ("trial_days", "مدت trial (روز)",
         "طول دوره‌ی آزمایشی؛ بین ۱ تا ۳۰ (پیش‌فرض ۷)",
         "number", "subscription.manage", "HIGH"),
    ]),
    # 🌊 W8/UX-04 — SLA تیکت (ساعت مهلت اولین پاسخ به‌تفکیک اولویت)
    ("support", [
        ("ticket_sla_urgent", "مهلت پاسخ فوری (ساعت)",
         "تیکت‌های فوری؛ ۰ = بدون SLA (پیش‌فرض ۸)",
         "number", "tickets.manage", "HIGH"),
        ("ticket_sla_high", "مهلت پاسخ مهم (ساعت)",
         "تیکت‌های مهم؛ ۰ = بدون SLA (پیش‌فرض ۲۴)",
         "number", "tickets.manage", "HIGH"),
        ("ticket_sla_normal", "مهلت پاسخ عادی (ساعت)",
         "تیکت‌های عادی؛ ۰ = بدون SLA (پیش‌فرض ۴۸)",
         "number", "tickets.manage", "HIGH"),
        ("ticket_sla_low", "مهلت پاسخ کم‌اهمیت (ساعت)",
         "تیکت‌های کم‌اهمیت؛ ۰ = بدون SLA (پیش‌فرض ۷۲)",
         "number", "tickets.manage", "HIGH"),
        ("ticket_stale_hours", "آستانه‌ی یادآوری تیکت مانده (ساعت)",
         "تیکت باز بدون پاسخ پس از این ساعت به مسئول یادآوری می‌شود (پیش‌فرض ۲۴)",
         "number", "tickets.manage", "HIGH"),
    ]),
    ("backup", [
        ("auto_backup_enabled", "بکاپ خودکار روزانه",
         "هر روز در ساعت مشخص‌شده نسخه‌ی پشتیبان ساخته می‌شود",
         "bool", "backup.manage", "HIGH"),
        ("auto_backup_hour", "ساعت بکاپ خودکار",
         "ساعت اجرا به‌وقت تهران (۰ تا ۲۳)",
         "hour", "backup.manage", "HIGH"),
        ("auto_backup_last_run", "آخرین اجرای بکاپ",
         "فقط نمایشی — توسط جاب بکاپ به‌روزرسانی می‌شود",
         "readonly", "backup.manage", "INFO"),
    ]),
]


@router.get("/settings/center")
async def settings_center(
    user=Depends(_perm_any("settings.manage", "notifications.manage", "backup.manage")),
):
    """⚙️ نمای دسته‌بندی‌شده‌ی تنظیمات + متا (آخرین تغییردهنده/زمان)."""
    meta_docs = await db.settings_meta.find({}).to_list(200)
    meta = {str(m.get("_id")): m for m in meta_docs}
    notif_defaults = await db.get_notif_defaults()

    cats = []
    for cat_key, rows in _SETTINGS_CATALOG:
        items = []
        for key, label, desc, typ, perm, sev in rows:
            if not await db.has_permission(user["id"], perm):
                continue
            val = await db.get_setting(key, None)
            m = meta.get(key) or {}
            items.append({
                "key": key, "label": label, "desc": desc, "type": typ,
                "value": val,
                "updated_by": m.get("by_name", ""), "updated_at": m.get("at") or None,
            })
        if items:
            cats.append({"key": cat_key, "items": items})

    # 🔔 پیش‌فرض اعلان‌ها — همان کلیدهای get_notif_defaults (بدون توقف ربات)
    notif_items = []
    notif_labels = {}
    try:
        for row in db.NOTIF_CATALOG:
            notif_labels[row[0]] = row[1]
    except Exception:
        pass
    if await db.has_permission(user["id"], "notifications.manage"):
        existing_users = await db.users.count_documents({})
        for k in sorted(notif_defaults.keys()):
            m = meta.get(f"notif_default:{k}") or {}
            notif_items.append({
                "key": f"notif_default:{k}", "label": notif_labels.get(k, k),
                "desc": "پیش‌فرض این دسته اعلان؛ هنگام ذخیره محدوده‌ی اعمال را انتخاب کنید",
                "type": "bool", "value": bool(notif_defaults.get(k)),
                "existing_users": existing_users,
                "updated_by": m.get("by_name", ""), "updated_at": m.get("at") or None,
            })
        cats.append({"key": "notif", "items": notif_items})
    if await db.has_permission(user["id"], "settings.manage"):
        diag = time_diagnostics()
        cats.append({"key": "time", "items": [
            {"key": "system_timezone", "label": "Timezone رسمی", "desc": "منبع واحد business time", "type": "info", "value": diag["timezone"]},
            {"key": "system_calendar", "label": "تقویم و locale", "desc": "نمایش تمام رابط‌های فارسی", "type": "info", "value": f'{diag["calendar"]} · {diag["locale"]}'},
            {"key": "system_utc_now", "label": "زمان UTC ماشین", "desc": "timestamp canonical برای diagnostics", "type": "technical_time", "value": diag["server_utc"]},
            {"key": "system_tehran_now", "label": "زمان فعلی تهران", "desc": "نمایش جلالی مطابق IANA", "type": "readonly", "value": diag["server_utc"]},
            {"key": "system_week_start", "label": "شروع هفته", "desc": "مبنای تقویم، گزارش و تحلیل هفتگی", "type": "info", "value": diag["week_start"]},
        ]})
    return {"categories": cats}


class SettingPatch(BaseModel):
    value: object = None
    # فقط برای notif_default؛ False یعنی فقط default کاربران جدید.
    apply_to_existing: bool = False


class IdentityPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_length: int = Field(ge=1, le=40)
    max_length: int = Field(ge=2, le=80)
    cooldown_days: int = Field(ge=0, le=365)
    allow_emoji: bool
    allow_spaces: bool
    blacklist: list[str] = Field(default_factory=list, max_length=100)
    reserved_words: list[str] = Field(default_factory=list, max_length=100)


@router.patch("/settings/center/{key}")
async def settings_center_patch(key: str, body: SettingPatch,
                                user=Depends(_guard_any_admin)):
    """✏️ تغییر یک تنظیم — همان کنوانسیون مقداردهی پنل وب موجود + متا + audit.
    مقادیر با همان کلیدهای bot_settings نوشته می‌شوند ⇒ ربات/مینی‌اپ بی‌وقفه
    همان رفتار قبلی را می‌خوانند."""
    uid = user["id"]
    is_notif = key.startswith("notif_default:")
    need = "notifications.manage" if is_notif else None
    if not is_notif:
        row = next((r for _, rows in _SETTINGS_CATALOG for r in rows if r[0] == key), None)
        if not row:
            raise HTTPException(404, "تنظیم ناشناخته")
        if row[3] == "readonly":
            raise HTTPException(422, "این تنظیم فقط‌خواندنی است")
        need = row[4]
    if not await db.has_permission(uid, need):
        raise HTTPException(403, "forbidden")

    val = body.value
    affected_users = 0
    if is_notif:
        ntype = key.split(":", 1)[1]
        try:
            known = {r[0] for r in db.NOTIF_CATALOG}
            if ntype not in known:
                raise HTTPException(404, "دسته‌ی اعلان ناشناخته")
        except HTTPException:
            raise
        except Exception:
            pass
        try:
            result = await db.update_notif_default(
                ntype, bool(val), apply_existing=bool(body.apply_to_existing))
        except ValueError:
            raise HTTPException(404, "دسته‌ی اعلان ناشناخته")
        old = result["before"]
        label = ntype
        sev = "WARNING" if result["apply_existing"] else "INFO"
        before, after = old, result["after"]
        affected_users = result["affected_users"]
    else:
        _, label, _desc, typ, _perm_key, sev = row
        old = await db.get_setting(key, None)
        if typ == "bool":
            val = bool(val)
        elif typ == "text":
            val = str(val or "").strip()
            if len(val) > 400:
                raise HTTPException(422, "متن نباید بیشتر از ۴۰۰ کاراکتر باشد")
        elif typ == "group":
            if val in (None, ""):
                val = None
            else:
                try:
                    val = int(val)
                except (TypeError, ValueError):
                    raise HTTPException(422, "آیدی گروه باید عدد باشد")
                if val >= 0:
                    raise HTTPException(422, "آیدی گروه باید عدد منفی باشد (مثل -1001234567890)")
        elif typ == "link":
            val = (str(val or "").strip()) or None
            if val and not (val.startswith("http://") or val.startswith("https://")):
                raise HTTPException(422, "لینک باید با http:// یا https:// شروع شود")
            if val and len(val) > 300:
                raise HTTPException(422, "لینک نباید بیشتر از ۳۰۰ کاراکتر باشد")
        elif typ == "hour":
            try:
                val = int(val)
            except (TypeError, ValueError):
                raise HTTPException(422, "ساعت باید عدد باشد")
            if not 0 <= val <= 23:
                raise HTTPException(422, "ساعت بکاپ باید بین ۰ تا ۲۳ باشد")
        elif typ == "number":
            # 🌊 W6/MISS-03 — فرانت از قبل number را رندر می‌کرد ولی بک‌اند
            # اعتبارسنجی نداشت (مقدار خام ذخیره می‌شد)
            try:
                val = int(val)
            except (TypeError, ValueError):
                raise HTTPException(422, "مقدار باید عدد صحیح باشد")
        await db.set_setting(key, val)
        before, after = old, val

    audit_after = {label: after}
    if is_notif:
        audit_after.update({"اعمال روی کاربران فعلی": bool(body.apply_to_existing),
                            "کاربران تغییرکرده": affected_users})
    try:
        await _audit(uid, f"تغییر تنظیم «{label}»", severity=sev,
                     before={label: before}, after=audit_after,
                     tags=["تنظیمات", "پنل_وب", f"setting:{key}"])
    except Exception:
        if is_notif:
            await db.update_notif_default(ntype, before,
                                          apply_existing=bool(body.apply_to_existing))
        else:
            await db.set_setting(key, before)
        raise HTTPException(503, "ثبت حسابرسی ناموفق بود؛ تنظیم قبلی بازگردانده شد")
    # متادیتا فقط بعد از audit موفق ثبت می‌شود.
    udb = user.get("_db") or {}
    await db.settings_meta.update_one(
        {"_id": key},
        {"$set": {"by": uid, "by_name": udb.get("name", str(uid)), "at": _now()}},
        upsert=True)
    return {"ok": True, "key": key, "before": before, "after": after,
            "apply_to_existing": bool(is_notif and body.apply_to_existing),
            "affected_users": affected_users}


@router.get("/settings/identity-policy")
async def identity_policy_get(user=Depends(_perm("settings.manage"))):
    cfg = await db.get_identity_config()
    return {"policy": cfg}


@router.put("/settings/identity-policy")
async def identity_policy_update(body: IdentityPolicyUpdate,
                                 user=Depends(_perm("settings.manage"))):
    if body.min_length > body.max_length:
        raise HTTPException(422, "حداقل طول نمی‌تواند بیشتر از حداکثر باشد")

    def clean_words(values):
        out, seen = [], set()
        for raw in values:
            word = " ".join(str(raw or "").split()).strip()
            canon = word.casefold()
            if not word or canon in seen:
                continue
            if len(word) > 60:
                raise HTTPException(422, "هر واژه حداکثر ۶۰ کاراکتر باشد")
            seen.add(canon); out.append(word)
        return out

    clean = body.model_dump()
    clean["blacklist"] = clean_words(body.blacklist)
    clean["reserved_words"] = clean_words(body.reserved_words)
    before = await db.get_identity_config()
    after = await db.update_identity_config(clean, actor=user["id"])
    try:
        await _audit(user["id"], "به‌روزرسانی سیاست نام‌نما", severity="HIGH",
                     target_type="identity_policy", target_label="nickname",
                     before=before, after=after,
                     tags=["هویت", "نام‌نما", "تنظیمات", "پنل_وب"])
    except Exception:
        await db.update_identity_config(before, actor=user["id"])
        raise HTTPException(503, "ثبت حسابرسی ناموفق بود؛ سیاست قبلی بازگردانده شد")
    return {"ok": True, "policy": after}


# ══════════════════════════════════════════════════════════════════
# 🌊 WA2.2 — مدیریت آزمون‌ها (schedules type=exam + آمار exam_sessions)
# ══════════════════════════════════════════════════════════════════

def _exam_status(doc: dict) -> str:
    """scheduled | active | finished — مشتق از date/time (میلادی ISO همان سیستم)."""
    try:
        d = parse_gregorian_date(doc.get("date"))
    except Exception:
        return "scheduled"
    today = today_tehran()
    if d > today:
        return "scheduled"
    if d == today:
        return "active"
    return "finished"


_STATUS_FA = {"scheduled": "زمان‌بندی‌شده", "active": "در حال برگزاری", "finished": "برگزارشده"}


def _exam_row(doc: dict) -> dict:
    st = _exam_status(doc)
    return {
        "id": str(doc.get("_id", "")),
        "lesson": doc.get("lesson", ""), "teacher": doc.get("teacher", ""),
        "date": doc.get("date", ""), "time": doc.get("time", ""),
        "location": doc.get("location", ""), "notes": doc.get("notes", ""),
        "group": db.normalize_group(doc.get("group", "هر دو")) or "هر دو",
        "status": st, "status_fa": _STATUS_FA[st],
        "reminded": doc.get("notified_days") or [],
    }


@router.get("/exams")
async def exams_list(status: str | None = Query(None),
                     user=Depends(_perm("schedules.manage"))):
    """📝 لیست آزمون‌ها (type='exam' در schedules) + وضعیت مشتق‌شده."""
    docs = await db.schedules.find({"type": "exam"}).sort("date", -1).to_list(200)
    rows = [_exam_row(d) for d in docs]
    if status in _STATUS_FA:
        rows = [r for r in rows if r["status"] == status]
    counts = {k: 0 for k in _STATUS_FA}
    for r in [_exam_row(d) for d in docs]:
        counts[r["status"]] += 1
    return {"exams": rows, "counts": counts}


class ExamIn(BaseModel):
    lesson: str
    date: str
    time: str = ""
    teacher: str = ""
    location: str = ""
    notes: str = ""
    group: str = "هر دو"


def _valid_exam_fields(body) -> tuple:
    lesson = (body.lesson or "").strip()
    if not (1 <= len(lesson) <= 80):
        raise HTTPException(422, "عنوان درس/آزمون الزامی است (حداکثر ۸۰ کاراکتر)")
    d = (body.date or "").strip()
    try:
        parse_gregorian_date(d)
    except (TimeContractError, TypeError, ValueError):
        raise HTTPException(422, "تاریخ باید به فرمت YYYY-MM-DD باشد")
    t = (body.time or "").strip()
    if t:
        try:
            parse_clock_time(t)
        except (TimeContractError, TypeError, ValueError):
            raise HTTPException(422, "ساعت باید به فرمت HH:MM باشد")
    grp = db.normalize_group(body.group or "هر دو") or "هر دو"
    if grp not in ("هر دو", "1", "2"):
        grp = "هر دو"
    return lesson, d, t, grp


@router.post("/exams")
async def exams_create(body: ExamIn, user=Depends(_perm("schedules.manage"))):
    """➕ ایجاد آزمون — دقیقاً با همان db.add_schedule(type='exam') مسیر ربات."""
    lesson, d, t, grp = _valid_exam_fields(body)
    teacher = (body.teacher or "").strip()[:80]
    location = (body.location or "").strip()[:80]
    notes = (body.notes or "").strip()[:300]
    sid = await db.add_schedule("exam", lesson, teacher, d, t, location,
                                notes=notes, group=grp)
    item = await db.get_schedule_by_id(str(sid)) or {
        "_id": sid, "type": "exam", "lesson": lesson, "teacher": teacher,
        "date": d, "time": t, "location": location, "notes": notes, "group": grp,
    }
    notice = await db.schedule_notify_event(item, "created")
    await _audit(user["id"], "ایجاد آزمون جدید", severity="INFO",
                 target_id=str(sid), target_type="exam", target_label=lesson,
                 after={"تاریخ": d, "گروه": grp,
                        "اطلاع‌رسانی": notice.get("notified", 0)},
                 tags=["امتحان", "پنل_وب"])
    # 🌊 W8/UX-05 — هشدار تداخل (غیرمسدودکننده)
    conflicts = await db.schedule_find_conflicts(
        grp, d, t, '', exclude_id=str(sid))
    return {"ok": True, "id": str(sid),
            "notified": notice.get("notified", 0),
            "warnings": {"schedule_conflicts": conflicts}}


@router.patch("/exams/{sid}")
async def exams_update(sid: str, body: ExamIn,
                       user=Depends(_perm("schedules.manage"))):
    lesson, d, t, grp = _valid_exam_fields(body)
    old = await db.get_schedule_by_id(sid)
    if not old or old.get("type") != "exam":
        raise HTTPException(404, "آزمون یافت نشد")
    teacher = (body.teacher or "").strip()[:80]
    location = (body.location or "").strip()[:80]
    notes = (body.notes or "").strip()[:300]
    ok = await db.update_schedule_full(sid, lesson, teacher, d, t, location,
                                       notes, grp)
    if not ok:
        raise HTTPException(500, "به‌روزرسانی ناموفق بود")
    item = await db.get_schedule_by_id(sid) or {
        **old, "lesson": lesson, "teacher": teacher, "date": d, "time": t,
        "location": location, "notes": notes, "group": grp,
    }
    notice = await db.schedule_notify_event(item, "updated")
    await _audit(user["id"], "ویرایش آزمون", severity="WARNING",
                 target_id=sid, target_type="exam", target_label=lesson,
                 before={"عنوان": old.get("lesson"), "تاریخ": old.get("date"),
                         "گروه": old.get("group")},
                 after={"عنوان": lesson, "تاریخ": d, "گروه": grp,
                        "اطلاع‌رسانی": notice.get("notified", 0)},
                 tags=["امتحان", "پنل_وب"])
    return {"ok": True, "notified": notice.get("notified", 0)}


@router.delete("/exams/{sid}")
async def exams_delete(sid: str, user=Depends(_perm("schedules.manage"))):
    old = await db.get_schedule_by_id(sid)
    if not old or old.get("type") != "exam":
        raise HTTPException(404, "آزمون یافت نشد")
    _res = await db.delete_schedule(sid)
    if _res is None:              # 🛡 AUDIT-R6 — خطای دیتابیس، نه حذف موفق
        raise HTTPException(status_code=500, detail="حذف انجام نشد — دوباره تلاش کنید")
    notice = await db.schedule_notify_event(old, "cancelled")
    await _audit(user["id"], "حذف آزمون", severity="HIGH",
                 target_id=sid, target_type="exam",
                 target_label=old.get("lesson", ""),
                 before={"تاریخ": old.get("date"), "گروه": old.get("group")},
                 after={"حذف": True, "اطلاع‌رسانی": notice.get("notified", 0)},
                 tags=["امتحان", "لغو", "پنل_وب"])
    return {"ok": True, "notified": notice.get("notified", 0)}


@router.get("/exams/stats")
async def exams_stats(user=Depends(_perm("schedules.manage"))):
    """📊 آمار آزمون‌های تمرینی (exam_sessions) — خواندنی و دفاعی."""
    out = {"total_runs": 0, "finished": 0, "avg_pct": None,
           "runs_7d": 0, "questions_total": 0}
    try:
        out["total_runs"] = await db.exam_sessions.count_documents({})
        out["finished"] = await db.exam_sessions.count_documents({"status": "finished"})
        week_ago = (now_utc() - timedelta(days=7)).isoformat()
        out["runs_7d"] = await db.exam_sessions.count_documents(
            {"started_at": {"$gte": week_ago}})
        # میانگین درصد — نمونه‌ی ۵۰۰تایی اخیر (بدون aggregate سنگین)
        rows = await db.exam_sessions.find({"status": "finished"}).sort("started_at", -1).limit(500).to_list(500)
        pcts = []
        for r in rows:
            tot = r.get("total") or r.get("count") or 0
            cor = r.get("correct") or 0
            if tot:
                try:
                    pcts.append(round(cor * 100.0 / tot, 1))
                except Exception:
                    pass
        if pcts:
            out["avg_pct"] = round(sum(pcts) / len(pcts), 1)
    except Exception:
        pass
    try:
        out["questions_total"] = await db.questions.count_documents(approved_query())
    except Exception:
        pass
    return out


# ══════════════════════════════════════════════════════════════════
# 🌊 WA2.1 — Content Command Center (درخت ترم→درس→جلسه+نشان fork)
# ══════════════════════════════════════════════════════════════════

@router.get("/content/tree")
async def content_tree(intake: Optional[str] = Query(None),
                       admin=Depends(get_content_admin_user)):
    """🌳 درخت مؤثر محتوا برای یک ورودی — ۳ کوئری ثابت (بدون N+1):
    پایه‌ی سراسری + overrideهای همان ورودی، با نشان 🌐/⭐/🏷 روی هر جلسه."""
    iv = resolve_content_intake(admin, intake)  # '' یا کد ورودی (scope-enforced)
    actor_scope = admin.get("_scope") or {"kind": "global", "intake": None}
    scoped_view = actor_scope.get("kind") == "scoped"
    scope_intakes = ["", iv] if iv else [""]

    # 🌊 WA3-fix — داکیومنت‌های پیش از موج C1 ممکن است فیلد intake نداشته
    # باشند؛ با $or آن‌ها را هم می‌آوریم (معادل '' سراسری تلقی می‌شوند).
    lessons = await db.bs_lessons.find({
        "term": {"$in": TERMS},
        "$or": [{"intake": {"$in": scope_intakes}}, {"intake": {"$exists": False}},
                {"intake": None}],
    }).to_list(400)
    lesson_ids = [str(l.get("_id")) for l in lessons]
    # داده‌های legacy ممکن است foreign key را به‌صورت ObjectId نگه داشته
    # باشند، در حالی که مسیرهای جدید string ذخیره می‌کنند. هر دو شکل باید
    # در یک query خوانده شوند؛ خروجی API همیشه string است.
    lesson_refs = list(lesson_ids)
    lesson_refs.extend(oid for oid in (_oid(v) for v in lesson_ids) if oid is not None)
    sessions = await db.bs_sessions.find(
        {"lesson_id": {"$in": lesson_refs}}).to_list(2000) if lesson_refs else []
    if iv:
        # 🌊 C3-fix — فیلتر سطل باید دقیق باشد: عبارت قبلی («یا هر non-fork»)
        # جلسه‌های «exclusive» ورودی‌های دیگر را هم وارد درخت می‌کرد. تا پیش از
        # موج C3 چنین سندی وجود نداشت (هر non-fork یا سراسری است یا ارث‌بر از
        # درس خودش)؛ حالا که نماینده می‌تواند جلسه‌ی فقط-ورودی بسازد، این
        # نشت واقعی می‌شد ⇒ فقط سراسری + ورودی خودِ actor.
        sessions = [s for s in sessions if str(s.get("intake") or "") in ("", iv)]
    else:
        sessions = [s for s in sessions if str(s.get("intake") or "") == ""
                    and not s.get("fork_of")]
    sess_ids = [str(s.get("_id")) for s in sessions]
    session_refs = list(sess_ids)
    session_refs.extend(oid for oid in (_oid(v) for v in sess_ids) if oid is not None)
    counts = {}
    if session_refs:
        for c in await db.bs_content.find(
                {"session_id": {"$in": session_refs}}).to_list(5000):
            cid = str(c.get("session_id") or "")
            slot = counts.setdefault(cid, {"n": 0, "types": {}})
            slot["n"] += 1
            t = str(c.get("type") or "?")
            slot["types"][t] = slot["types"].get(t, 0) + 1

    intake_labels = {}
    try:
        for i in await db.get_all_intakes():
            if i.get("active", True):
                code = str(i.get("code") or "")
                if code:
                    intake_labels[code] = str(i.get("label") or code)
    except Exception:
        pass
    if scoped_view:
        intake_labels = {iv: intake_labels.get(iv, iv)} if iv else {}

    def legacy_int(value) -> int:
        """order/number قدیمی گاهی string یا None است؛ قرارداد وب همیشه int."""
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    tree = []
    for term in TERMS:
        # order/number در اسناد قدیمی می‌تواند None یا string باشد؛ مرتب‌سازی
        # مستقیم int و str در Python 3 باعث TypeError و پاسخ 500 می‌شود.
        t_lessons = sorted([l for l in lessons if str(l.get("term") or "") == term],
                           key=lambda x: (legacy_int(x.get("order")), str(x.get("_id"))))
        trow = {"term": term, "lessons": []}
        for l in t_lessons:
            lid = str(l.get("_id"))
            # 🛡 §۸۳ — با `order` مرتب می‌شود، همان کلیدی که
            # `/content/sessions/{id}/reorder` می‌نویسد. با `number` نتیجه‌ی
            # جابه‌جایی هرگز در درخت دیده نمی‌شد. `number` معیار دوم است تا
            # جلسه‌های قدیمیِ بدون order (همه order=0) ترتیب خودشان را
            # نگه دارند.
            l_sessions = sorted(
                [s for s in sessions if str(s.get("lesson_id") or "") == lid],
                key=lambda x: (legacy_int(x.get("order")),
                               legacy_int(x.get("number")), str(x.get("_id"))),
            )
            srows = []
            for s in l_sessions:
                sid = str(s.get("_id"))
                s_intake = str(s.get("intake") or "")
                s_intake_effective = s_intake if s_intake else str(l.get("intake") or "")
                # fork_of در بعضی داده‌های قدیمی ObjectId است. عبور مستقیم آن
                # به FastAPI هنگام json encoding با 500 شکست می‌خورد.
                fork_of = str(s.get("fork_of") or "")
                srows.append({
                    "id": sid, "number": legacy_int(s.get("number")),
                    "topic": str(s.get("topic") or ""),
                    "teacher": str(s.get("teacher") or ""),
                    "intake": s_intake_effective,
                    "intake_label": intake_labels.get(s_intake_effective, ""),
                    "kind": ("fork" if fork_of else
                             ("exclusive" if s_intake_effective else "global")),
                    "fork_of": fork_of,
                    # 🛡 C3.1 — اگر scope کاربر تنظیم نشده (iv='') هیچ سطلی
                    # برای او نوشتنی نیست، حتی سراسری
                    "readonly": bool(scoped_view and (not iv or s_intake_effective != iv)),
                    "content_count": counts.get(sid, {}).get("n", 0),
                    "types": counts.get(sid, {}).get("types", {}),
                })
            lesson_intake = str(l.get("intake") or "")
            trow["lessons"].append({
                "id": lid, "name": str(l.get("name") or ""),
                "teacher": str(l.get("teacher") or ""),
                "intake": lesson_intake,
                "readonly": bool(scoped_view and (not iv or lesson_intake != iv)),
                # 🌊 C3 — والد قفل است ولی «جلسه‌ی فقط-ورودی-خودم» ساختنی است
                "can_create_sessions": bool(scoped_view and iv and not lesson_intake),
                "sessions": srows, "session_count": len(srows),
                "content_count": sum(r["content_count"] for r in srows),
            })
        tree.append(trow)
    result = {"intake": str(iv or ""), "scope_kind": str(actor_scope.get("kind") or "global"),
              "tree": tree,
              "intakes": [{"code": c, "label": l} for c, l in intake_labels.items()]}
    # دفاع نهایی در برابر هر BSON legacy که از projection بالا عبور کرده باشد.
    return jsonable_encoder(result, custom_encoder={ObjectId: str})


async def _student_preview_context(user_id: int, admin: dict):
    target = await db.get_user(user_id)
    if not target or not target.get("approved") or target.get("suspended"):
        raise HTTPException(404, "دانشجوی فعال پیدا نشد")
    if await _has_admin_access(user_id):
        raise HTTPException(422, "برای پیش‌نمایش باید حساب دانشجو انتخاب شود")
    intake = target.get("intake") or ""
    scope = admin.get("_scope") or await db.get_content_scope(admin["id"])
    if scope and scope.get("kind") == "scoped" and intake != (scope.get("intake") or ""):
        raise HTTPException(403, "intake_out_of_scope")
    return {"id": user_id, "_db": target}, target


@router.get("/content/student-preview/students")
async def wa_student_preview_students(q: str = Query(..., min_length=2, max_length=100),
                                      admin=Depends(get_content_admin_user)):
    query = db.build_user_search_query(q.strip())
    query["approved"] = True; query["suspended"] = {"$ne": True}
    scope = admin.get("_scope") or await db.get_content_scope(admin["id"])
    if scope and scope.get("kind") == "scoped": query["intake"] = scope.get("intake") or ""
    docs = await db.users.find(query, {"user_id": 1, "name": 1, "nickname": 1,
        "student_id": 1, "username": 1, "intake": 1, "group": 1, "role": 1}).sort("name", 1).limit(20).to_list(20)
    return {"students": [{"id": row.get("user_id"), "name": db.display_name_of(row),
                           "student_id": row.get("student_id", ""), "username": row.get("username", ""),
                           "intake": row.get("intake", ""), "group": row.get("group", "")}
                          for row in docs if row.get("role", "student") == "student"]}


@router.get("/content/student-preview")
async def wa_student_preview(user_id: int = Query(...), admin=Depends(get_content_admin_user)):
    context, target = await _student_preview_context(user_id, admin)
    terms = await resources_api.terms(user=context)
    return {"student": {"id": user_id, "name": db.display_name_of(target),
                         "intake": target.get("intake", ""), "group": target.get("group", "")},
            "terms": terms.get("terms") or [], "resolver": "mini_app_resources"}


@router.get("/content/student-preview/lessons")
async def wa_student_preview_lessons(user_id: int, term: str = Query(..., max_length=100),
                                     admin=Depends(get_content_admin_user)):
    context, _ = await _student_preview_context(user_id, admin)
    return await resources_api.lessons(term=term, user=context)


@router.get("/content/student-preview/sessions")
async def wa_student_preview_sessions(user_id: int, lesson_id: str = Query(..., max_length=80),
                                      admin=Depends(get_content_admin_user)):
    context, _ = await _student_preview_context(user_id, admin)
    return await resources_api.sessions(lesson_id=lesson_id, user=context)


@router.get("/content/student-preview/files")
async def wa_student_preview_files(user_id: int, session_id: str = Query(..., max_length=80),
                                   admin=Depends(get_content_admin_user)):
    context, _ = await _student_preview_context(user_id, admin)
    return await resources_api.files(session_id=session_id, user=context)


@router.get("/content/impact/{target_type}/{target_id}")
async def wa_content_impact(
    target_type: str, target_id: str, admin=Depends(get_content_admin_user),
):
    if target_type == "lesson":
        item = await db.bs_get_lesson(target_id)
        intake = (item or {}).get("intake") or ""
        session_ids = [str(row.get("_id")) for row in await db.bs_sessions.find({"lesson_id": target_id}, {"_id": 1}).to_list(10000)]
        sessions = len(session_ids)
        files = await db.bs_content.count_documents({"session_id": {"$in": session_ids}}) if session_ids else 0
    elif target_type == "session":
        item = await db.bs_get_session(target_id)
        intake = await db.session_intake(target_id) if item else ""
        sessions = 1 if item else 0
        files = await db.bs_content.count_documents({"session_id": target_id}) if item else 0
    elif target_type == "content_item":
        item = await db.bs_get_content_item(target_id)
        intake = await db.content_intake(target_id) if item else ""
        sessions, files = 0, 1 if item else 0
    else:
        raise HTTPException(422, "نوع محتوا برای تحلیل اثر پشتیبانی نمی‌شود")
    if not item:
        raise HTTPException(404, "محتوا پیدا نشد")
    if not await db.can_access_intake(admin["id"], intake):
        raise HTTPException(403, "intake_out_of_scope")
    user_query = {"approved": True, "suspended": {"$ne": True}}
    if intake: user_query["intake"] = intake
    affected_users = await db.users.count_documents(user_query)
    return {"target_type": target_type, "target_id": target_id, "intake": intake,
            "affected_users": affected_users, "affected_sessions": sessions,
            "affected_files": files, "visibility": "potential",
            "explanation": "تعداد کاربران فعالی که این scope بالقوه برایشان قابل مشاهده است؛ سیاست اشتراک ممکن است دسترسی نهایی را محدود کند."}


@router.get("/content/history")
async def content_history(
    target_id: str = Query(..., min_length=1, max_length=80),
    target_type: str = Query(..., pattern="^(lesson|session|content_item|reference_subject|reference_book|reference_file)$"),
    limit: int = Query(20, ge=1, le=50),
    admin=Depends(get_content_admin_user),
):
    if target_type == "lesson":
        item = await db.bs_get_lesson(target_id); item_intake = (item or {}).get("intake") or ""
    elif target_type == "session":
        item = await db.bs_get_session(target_id); item_intake = await db.session_intake(target_id)
    elif target_type == "content_item":
        item = await db.bs_get_content_item(target_id); item_intake = await db.content_intake(target_id)
    elif target_type == "reference_subject":
        item = await db.ref_get_subject(target_id); item_intake = (item or {}).get("intake") or ""
    elif target_type == "reference_book":
        item = await db.ref_get_book(target_id); item_intake = await db.ref_book_intake(target_id)
    elif target_type == "reference_file":
        item = await db.ref_get_file(target_id); item_intake = await db.ref_file_intake(target_id)
    else:
        raise HTTPException(422, "نوع محتوا پشتیبانی نمی‌شود")
    if not item:
        raise HTTPException(404, "محتوا پیدا نشد")
    scope = admin.get("_scope") or await db.get_content_scope(admin["id"])
    if scope and scope.get("kind") == "scoped" and item_intake not in ("", scope.get("intake") or ""):
        raise HTTPException(403, "intake_out_of_scope")
    docs = await db.audit_logs.find({"$or": [
        {"target.id": target_id}, {"target_id": target_id},
    ]}).sort("timestamp", -1).limit(limit).to_list(limit)
    return {"items": [{
        "id": str(d.get("_id", "")), "title": d.get("action", ""),
        "actor": (d.get("actor") or {}).get("name", ""),
        "at": d.get("timestamp") or None,
        "description": d.get("details", ""), "severity": d.get("severity", "INFO"),
    } for d in docs]}


@router.post("/content/sessions/{sid}/duplicate")
async def content_session_duplicate(sid: str,
                                    admin=Depends(get_content_global_user)):
    """📄➜📄 کلون جلسه — شماره‌ی بعدی همان درس؛ کپی فایل‌ها با notif_sent=True
    (کلون «محتوای جدید» نیست ⇒ دوباره اعلان منابع نمی‌شورد)."""
    base = await db.bs_get_session(sid)
    if not base:
        raise HTTPException(404, "جلسه یافت نشد")
    lid = base.get("lesson_id", "")
    eff_intake = await db.session_intake(sid)
    sibs = await db.bs_sessions.find({"lesson_id": lid}).to_list(500)
    next_num = max([0] + [s.get("number", 0) or 0 for s in sibs]) + 1
    doc = {"lesson_id": lid, "number": next_num,
           "topic": (base.get("topic", "") or "")[:120],
           "teacher": base.get("teacher", ""),
           "intake": eff_intake, "duplicated_from": sid,
           "created_at": _now()}
    r = await db.bs_sessions.insert_one(doc)
    new_sid = str(getattr(r, "inserted_id", "") or "")
    copied = 0
    for c in (await db.bs_get_content(sid)):
        await db.bs_content.insert_one({
            "session_id": new_sid, "type": c.get("type", "pdf"),
            "file_id": c.get("file_id", ""), "description": c.get("description", ""),
            "extra_info": c.get("extra_info", ""), "order": c.get("order", 0),
            "uploaded_at": _now(), "downloads": 0, "notif_sent": True,
        })
        copied += 1
    await _audit(admin["id"], "کلون جلسه (همراه فایل‌ها)", severity="INFO",
                 target_id=new_sid, target_type="session",
                 target_label=base.get("topic", ""), tags=["کلون_جلسه", "پنل_وب"])
    return {"ok": True, "id": new_sid, "number": next_num, "copied": copied}


class SessionsBulk(BaseModel):
    action: str                 # duplicate | delete | move
    ids: list[str]
    target_lesson: Optional[str] = None


@router.post("/content/sessions/bulk")
async def content_sessions_bulk(body: SessionsBulk,
                                admin=Depends(get_content_global_user)):
    """⚡ اکشن گروهی جلسات (سقف ۵۰) — فقط ادمین ارشد محتوا (ساختار سراسری)."""
    ids = [str(i) for i in (body.ids or [])][:50]
    if not ids:
        raise HTTPException(400, "لیست جلسات خالی است")
    done = 0
    if body.action == "delete":
        for sid in ids:
            # پاک‌سازی forkهای وابسته هم (جلوگیری از یتیم‌شدن)
            for f in await db.bs_sessions.find({"fork_of": sid}).to_list(50):
                await db.bs_delete_session(str(f.get("_id")))
            await db.bs_delete_session(sid)
            done += 1
    elif body.action == "duplicate":
        for sid in ids:
            try:
                r = await content_session_duplicate(sid, admin)
                if r.get("ok"):
                    done += 1
            except Exception:
                continue   # جلسه‌ی نامعتبر/خراب متوقف‌کننده‌ی بقیه نیست
    elif body.action == "move":
        tl = (body.target_lesson or "").strip()
        target = await db.bs_get_lesson(tl)
        if not target:
            raise HTTPException(404, "درس مقصد یافت نشد")
        siblings = await db.bs_sessions.find({"lesson_id": tl}).to_list(500)
        next_num = max([0] + [s.get("number", 0) or 0 for s in siblings])
        for sid in ids:
            s = await db.bs_get_session(sid)
            if not s or s.get("lesson_id") == tl:
                continue
            if s.get("fork_of"):
                continue  # fork را جابه‌جا نمی‌کنیم (به base گره خورده)
            next_num += 1
            await db.bs_update_session(sid, {"lesson_id": tl, "number": next_num,
                                             "intake": target.get("intake") or ""})
            done += 1
    else:
        raise HTTPException(400, "اکشن نامعتبر است")
    fa = {"delete": "حذف گروهی", "duplicate": "کلون گروهی", "move": "انتقال گروهی"}
    await _audit(admin["id"], f"{fa[body.action]} جلسات ({done} مورد)",
                 severity="HIGH" if body.action == "delete" else "INFO",
                 target_label=f"{done} جلسه", tags=["bulk_content", "پنل_وب"])
    return {"ok": True, "done": done}


class ItemsBulk(BaseModel):
    action: str                 # delete | move
    ids: list[str]
    target_session: Optional[str] = None


@router.post("/content/items/bulk")
async def content_items_bulk(body: ItemsBulk,
                             admin=Depends(get_content_global_user)):
    """⚡ اکشن گروهی آیتم‌های محتوا (سقف ۱۰۰): حذف | انتقال به جلسه‌ی دیگر."""
    ids = [str(i) for i in (body.ids or [])][:100]
    if not ids:
        raise HTTPException(400, "لیست آیتم‌ها خالی است")
    done = 0
    if body.action == "delete":
        for cid in ids:
            if await db.bs_get_content_item(cid):
                _res = await db.bs_delete_content(cid)
                if _res is None:              # 🛡 AUDIT-R6 — خطای دیتابیس، نه حذف موفق
                    raise HTTPException(status_code=500, detail="حذف انجام نشد — دوباره تلاش کنید")
                done += 1
    elif body.action == "move":
        ts = (body.target_session or "").strip()
        if not await db.bs_get_session(ts):
            raise HTTPException(404, "جلسه‌ی مقصد یافت نشد")
        order = await db.bs_content.count_documents({"session_id": ts})
        for cid in ids:
            c = await db.bs_get_content_item(cid)
            if not c or c.get("session_id") == ts:
                continue
            order += 1
            await db.bs_content.update_one({"_id": _oid(cid)},
                                           {"$set": {"session_id": ts, "order": order}})
            done += 1
    else:
        raise HTTPException(400, "اکشن نامعتبر است")
    await _audit(admin["id"],
                 f"{'حذف' if body.action == 'delete' else 'انتقال'} گروهی فایل‌ها ({done} مورد)",
                 severity="HIGH" if body.action == "delete" else "INFO",
                 target_label=f"{done} فایل", tags=["bulk_content", "پنل_وب"])
    return {"ok": True, "done": done}


# ══════════════════════════════════════════════════════════════════
# 🌊 WA2.6 — تحلیل پیشرفته‌ی وب‌ادمین (بدون هیچ داده‌ی ساختگی)
# ══════════════════════════════════════════════════════════════════

@router.get("/wa-analytics")
async def wa_analytics(user=Depends(_perm("stats.view")),
                       days: int = Query(14, ge=1, le=90)):
    """Management analytics from persisted aggregates, with per-domain status.

    Snapshot domains keep their historical contract. Only ``bundle`` and
    ``new_resources_in_range`` are controlled by ``days``; the response states
    this explicitly so the UI never implies a time filter that was not applied.
    """
    generated_at = utc_now_iso()
    out = {
        "days": days, "generated_at": generated_at, "domain_status": {},
        "range_applies_to": ["bundle", "new_resources_in_range"],
        "scope": {"kind": "global", "label": "کل سامانه"},
    }
    domain_specs = [
        ("users", getattr(db, "stats_dashboard_users", None)),
        ("content", getattr(db, "stats_dashboard_content", None)),
        ("questions", getattr(db, "stats_dashboard_questions", None)),
        ("tickets", getattr(db, "stats_dashboard_tickets", None)),
        ("notif", getattr(db, "stats_dashboard_notif", None)),
        ("pulse", getattr(db, "activity_pulse", None)),
        ("sub", getattr(db, "sub_stats", None)),
    ]

    async def _call(fn):
        if fn is None:
            return RuntimeError("metric_source_unavailable")
        try:
            return await fn()
        except Exception as exc:
            return exc

    results = await asyncio.gather(*[_call(fn) for _, fn in domain_specs])
    for (name, _), value in zip(domain_specs, results):
        if isinstance(value, Exception):
            out[name] = {}
            out["domain_status"][name] = {"ok": False, "error": "temporarily_unavailable"}
        else:
            out[name] = value
            out["domain_status"][name] = {"ok": True}

    # Reuse domain aggregates instead of repeating the exact same Mongo counts.
    users_snapshot = out.get("users") or {}
    content_snapshot = out.get("content") or {}
    out["active_today"] = users_snapshot.get("active_today")
    out["new_resources_7d"] = content_snapshot.get("new_this_week")
    out["domain_status"]["active_today"] = dict(out["domain_status"].get("users", {"ok": False, "error": "temporarily_unavailable"}))
    out["domain_status"]["new_resources_7d"] = dict(out["domain_status"].get("content", {"ok": False, "error": "temporarily_unavailable"}))
    if days == 7 and out["new_resources_7d"] is not None:
        out["new_resources_in_range"] = out["new_resources_7d"]
        out["domain_status"]["new_resources_in_range"] = dict(out["domain_status"]["new_resources_7d"])
    else:
        try:
            out["new_resources_in_range"] = await db.new_resources_count(days)
            out["domain_status"]["new_resources_in_range"] = {"ok": True}
        except Exception:
            out["new_resources_in_range"] = None
            out["domain_status"]["new_resources_in_range"] = {"ok": False, "error": "temporarily_unavailable"}

    try:
        deep = bool(await db.has_permission(user["id"], "stats.deep"))
    except Exception:
        deep = False
    out["deep"] = deep
    if deep:
        try:
            out["bundle"] = await db.stats_analytics_bundle(days)
            out["domain_status"]["bundle"] = {"ok": True}
        except Exception:
            out["domain_status"]["bundle"] = {"ok": False, "error": "temporarily_unavailable"}
    else:
        out["domain_status"]["bundle"] = {"ok": False, "error": "permission_required"}

    return jsonable_encoder(out, custom_encoder={ObjectId: str})


# 🌊 موج Parity-Final — مرکز هوش ربات در وب: منطق rule-based واحدِ
# db.admin_insights() (همان صفحه‌ی admin:insights ربات) بدون هیچ کپی‌خوانی.
@router.get("/wa-insights")
async def wa_insights(user=Depends(_perm("stats.view"))):
    try:
        return await db.admin_insights()
    except Exception:
        # جزئیات exception فقط در لاگ سرور می‌ماند؛ API متن داخلی/credential را لو نمی‌دهد.
        raise HTTPException(503, "insights_temporarily_unavailable")


# ══════════════════════════════════════════════════════════════════
# 🌊 WA2.7 — مدیریت اعلان‌ها: اجراها + تلاش مجدد (مشابه admin_panel ولی با مجوز)
# ══════════════════════════════════════════════════════════════════

@router.get("/notif/runs")
async def notif_runs(job_name: str | None = Query(None),
                     limit: int = Query(15, ge=1, le=50),
                     user=Depends(_perm("notifications.manage"))):
    runs = await db.get_recent_notif_runs(job_name=job_name, limit=limit)
    return {"runs": [{
        "id": str(r.get("_id", "")), "job_name": r.get("job_name", ""),
        "status": r.get("status", ""), "sent": r.get("sent", 0),
        "failed": r.get("failed", 0), "total": r.get("total", 0),
        "started_at": r.get("started_at") or None,
        "finished_at": r.get("finished_at") or None,
    } for r in runs]}


@router.get("/notif/runs/{run_id}")
async def notif_run_detail(run_id: str, user=Depends(_perm("notifications.manage"))):
    oid = _oid(run_id)
    if not oid: raise HTTPException(422, "شناسه اجرای اعلان نامعتبر است")
    run = await db.notif_runs.find_one({"_id": oid})
    if not run: raise HTTPException(404, "اجرای اعلان پیدا نشد")
    failed = run.get("failed_targets_detailed") or [{"user_id": uid} for uid in (run.get("failed_user_ids") or [])]
    return {"run": {"id": run_id, "job_name": run.get("job_name", ""),
        "status": run.get("status", ""), "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"), "sent": int(run.get("sent") or 0),
        "failed": int(run.get("failed") or 0), "skipped": int(run.get("skipped") or 0),
        "total": int(run.get("total") or 0), "error": (run.get("error") or "")[:500],
        "message_preview": (run.get("message_text") or "")[:500],
        "correlation_id": run.get("correlation_id"),
        "failed_targets": [{"user_id": item.get("user_id"), "error": item.get("error") or "send_failed"}
                           for item in failed[:100]],
        "failed_targets_truncated": len(failed) > 100}}


@router.post("/notif/runs/{run_id}/retry")
async def notif_retry(run_id: str, user=Depends(_perm("notifications.manage"))):
    """🔁 صف دوباره‌ی گیرندگان ناموفق — همان الگوی admin_panel ولی permission-based."""
    targets = await db.get_failed_notif_details(run_id)
    if not targets:
        raise HTTPException(404, "موردی برای تلاش مجدد پیدا نشد")
    notif = db.client["medicalbot"]["bot_notifications"]
    n = 0
    for t in targets:
        if not t.get("message"):
            continue
        await notif.insert_one({"type": "notif_retry", "chat_id": t["user_id"],
                                "text": t["message"], "sent": False,
                                "created_at": _now(), "correlation_id": current_request_id.get()})
        n += 1
    await _audit(user["id"], f"تلاش مجدد ارسال اعلان ({n} گیرنده)",
                 severity="INFO", target_label=run_id, tags=["retry_notif", "پنل_وب"])
    return {"ok": True, "requeued": n}


# ══════════════════════════════════════════════════════════════════
# 🌊 WA3 — پریتی کامل «مدیریت کاربران» (آینه‌ی دقیق رفتار پنل وب قبلی ولی
# permission-based؛ هیچ endpoint موجود تغییر نمی‌کند)
# ══════════════════════════════════════════════════════════════════

class DmIn(BaseModel):
    text: str


@router.post("/users/{uid}/message")
async def wa_user_message(uid: int, body: DmIn, user=Depends(_perm("users.message"))):
    """✉️ پیام مستقیم ادمین به کاربر — همان کانال outbox ربات."""
    text = (body.text or "").strip()
    if not (1 <= len(text) <= 1500):
        raise HTTPException(422, "متن پیام باید بین ۱ تا ۱۵۰۰ کاراکتر باشد")
    target = await db.get_user(uid)
    if not target:
        raise HTTPException(404, "کاربر یافت نشد")
    await db.client["medicalbot"]["bot_notifications"].insert_one({
        "type": f"admin_dm", "chat_id": uid,
        "text": f"📩 <b>پیام از پشتیبانی هامزیار</b>\n\n{text}",
        "sent": False, "created_at": _now()})
    await _audit(user["id"], "ارسال پیام مستقیم به کاربر", severity="INFO",
                 target_id=uid, target_type="user",
                 target_label=target.get("name", ""), tags=["dm_کاربر", "پنل_وب"])
    return {"ok": True}


class UserActionIn(BaseModel):
    action: str          # approve|reject|suspend|unsuspend|delete|block|unblock
    reason: str = ""


@router.post("/users/{uid}/action")
async def wa_user_action(uid: int, body: UserActionIn, user=Depends(_guard_any_admin)):
    """⚙️ اکشن‌های تکی کاربر — معناشناسی دقیقاً برابر پنل قبلی/ربات + آینه‌ی
    Inbox مینی‌اپ (سه کلاینت سینک می‌مانند)."""
    _PERM = {"approve": "users.manage", "reject": "users.manage",
             "suspend": "users.suspend", "unsuspend": "users.suspend",
             "delete": "users.delete", "block": "users.delete", "unblock": "users.delete"}
    need = _PERM.get(body.action)
    if not need:
        raise HTTPException(400, "اکشن نامعتبر است")
    actor = user["id"]
    if not await db.has_permission(actor, need):
        raise HTTPException(403, "forbidden")
    if uid == ADMIN_ID and body.action in ("suspend", "delete", "block", "reject"):
        raise HTTPException(403, "روی مالک سامانه قابل اعمال نیست")
    target = await db.get_user(uid)
    notif = db.client["medicalbot"]["bot_notifications"]

    if body.action == "unblock":
        ok = await db.unblock_user(uid)
        if not ok:
            raise HTTPException(404, "این کاربر در بلک‌لیست نیست")
        await _audit(actor, "رفع مسدودیت کاربر", severity="HIGH",
                     target_id=uid, target_type="user", tags=["آنبلاک_کاربر", "پنل_وب"])
        return {"ok": True}
    if not target:
        raise HTTPException(404, "کاربر یافت نشد")
    label = target.get("name", "")

    if body.action == "approve":
        await db.update_user(uid, {"approved": True})
        await notif.insert_one({"type": "user_approved", "chat_id": uid,
            "text": "✅ <b>حساب شما تأیید شد!</b>\n\nاکنون می‌توانید از هامزیار استفاده کنید.\n/start بزنید.",
            "sent": False, "created_at": _now()})
        await db.inbox_add(uid, 'account', "✅ حسابت تأیید شد!",
            "اکنون به تمام بخش‌های هامزیار دسترسی داری — خوش اومدی! 🎓", link='/')
        await _audit(actor, "تأیید حساب کاربر", target_id=uid, target_type="user",
                     target_label=label, tags=["تأیید_کاربر", "پنل_وب"])
    elif body.action == "reject":
        await db.users.delete_one({"user_id": uid})
        await _audit(actor, "رد درخواست عضویت", severity="WARNING", target_id=uid,
                     target_type="user", target_label=label, tags=["رد_کاربر", "پنل_وب"])
    elif body.action == "suspend":
        await db.update_user(uid, {"suspended": True, "approved": False})
        await notif.insert_one({"type": "user_suspended", "chat_id": uid,
            "text": "⚠️ دسترسی شما موقتاً تعلیق شد.", "sent": False, "created_at": _now()})
        await _audit(actor, "تعلیق حساب کاربر", severity="HIGH", target_id=uid,
                     target_type="user", target_label=label, tags=["تعلیق_کاربر", "پنل_وب"])
    elif body.action == "unsuspend":
        await db.update_user(uid, {"suspended": False, "approved": True})
        await _audit(actor, "رفع تعلیق حساب کاربر", target_id=uid, target_type="user",
                     target_label=label, tags=["رفع_تعلیق", "پنل_وب"])
    elif body.action == "delete":
        await notif.insert_one({"type": "user_deleted", "chat_id": uid,
            "text": "❌ حساب شما حذف شد.", "sent": False, "created_at": _now()})
        await db.delete_user(uid)
        await _audit(actor, "حذف حساب کاربر", severity="CRITICAL", target_id=uid,
                     target_type="user", target_label=label, tags=["حذف_کاربر", "پنل_وب"])
    elif body.action == "block":
        await db.block_user(uid, reason=body.reason or "",
                            blocked_by=actor, blocked_by_name=(user.get("_db") or {}).get("name", ""))
        try:
            await db.blacklist.update_one({"_id": uid}, {"$set": {"name": label}})
        except Exception:
            pass
        await notif.insert_one({"type": "user_blocked", "chat_id": uid,
            "text": "🚫 حساب شما مسدود شد و امکان ثبت‌نام مجدد ندارید.",
            "sent": False, "created_at": _now()})
        await _audit(actor, "مسدودسازی کاربر (بلک‌لیست)", severity="CRITICAL",
                     target_id=uid, target_type="user", target_label=label,
                     tags=["بلاک_کاربر", "پنل_وب"])
    return {"ok": True}


class WaUserPatch(BaseModel):
    name: Optional[str] = None
    nickname: Optional[str] = None
    group: Optional[str] = None
    intake: Optional[str] = None
    student_id: Optional[str] = None


@router.patch("/users/{uid}")
async def wa_user_patch(uid: int, body: WaUserPatch, user=Depends(_perm("users.manage"))):
    """✏️ ویرایش فیلدهای پروفایل — همان whitelist پنل قبلی + لقب از مسیر
    IdentityService (اعتبارسنجی/audit خودکار داخل db)."""
    old_doc = await db.get_user(uid)
    if not old_doc:
        raise HTTPException(404, "کاربر یافت نشد")
    updates = {}
    if body.name is not None:
        updates["name"] = body.name.strip()[:80]
    if body.group is not None:
        updates["group"] = db.normalize_group(body.group)
    if body.intake is not None:
        updates["intake"] = body.intake
    if body.student_id is not None:
        updates["student_id"] = body.student_id.strip()[:40]
    nick_note = ""
    if body.nickname is not None:
        ok, err, _info = await db.set_nickname(
            uid, body.nickname, changed_by=f"admin:{user['id']}", reason="پنل وب‌ادمین")
        if not ok:
            raise HTTPException(422, f"لقب نامعتبر: {err}")
        nick_note = " + لقب"
    # 🌊 موج Audit-Diff — اسنپ‌شات «قبل» پیش از update (مقادیر scalar تغییرناپذیرند)
    _LBL = {"name": "نام", "group": "گروه", "intake": "ورودی", "student_id": "شماره دانشجویی"}
    _before = {_LBL.get(k, k): old_doc.get(k) for k in updates}
    _after = {_LBL.get(k, k): updates[k] for k in updates}
    if updates:
        await db.update_user(uid, updates)
    if updates or body.nickname is not None:
        await _audit(user["id"], "ویرایش اطلاعات کاربر" + nick_note, severity="WARNING",
                     target_id=uid, target_type="user",
                     target_label=" / ".join(f"{k}: {v}" for k, v in updates.items())[:300],
                     before=_before or None, after=_after or None,
                     tags=["ویرایش_کاربر", "پنل_وب"])
    return {"ok": True, "changed": list(updates.keys()) + (["nickname"] if body.nickname is not None else [])}


@router.get("/blacklist")
async def wa_blacklist(user=Depends(_perm("users.view"))):
    """🚫 بلک‌لیست — همان شکل پنل قبلی."""
    items = await db.get_blacklist()
    return {"blacklist": [{
        "id": b.get("_id"), "name": b.get("name", ""),
        "blocked_by_name": b.get("blocked_by_name", ""),
        "blocked_at": b.get("blocked_at") or None} for b in items]}


# ══════════════════════════════════════════════════════════════════
# 🌊 WA3 — مرتب‌سازی محتوا (reorder) — همان متدهای db که ربات استفاده می‌کند
# ══════════════════════════════════════════════════════════════════

class ReorderIn(BaseModel):
    direction: str       # up | down


@router.post("/content/lessons/{lid}/reorder")
async def content_lesson_reorder(lid: str, body: ReorderIn,
                                 admin=Depends(get_content_admin_user)):
    lesson = await db.bs_get_lesson(lid)
    if not lesson:
        raise HTTPException(404, "درس یافت نشد")
    if not await db.can_access_intake(admin["id"], lesson.get("intake") or ""):
        raise HTTPException(403, "intake_out_of_scope")
    q = {"term": lesson.get("term", ""), "intake": lesson.get("intake") or ""}
    fn = db.reorder_up if body.direction == "up" else db.reorder_down
    ok = await fn("bs_lessons", lid, q)
    if ok:
        await _audit(admin["id"], "تغییر ترتیب درس علوم پایه", severity="INFO",
                     target_id=lid, target_type="lesson", target_label=lesson.get("name", ""),
                     after={"جهت": body.direction}, tags=["محتوا", "ترتیب", "پنل_وب"])
    return {"ok": bool(ok)}


@router.post("/content/sessions/{sid}/reorder")
async def content_session_reorder(sid: str, body: ReorderIn,
                                  admin=Depends(get_content_admin_user)):
    ses = await db.bs_get_session(sid)
    if not ses:
        raise HTTPException(404, "جلسه یافت نشد")
    if not await db.can_access_intake(admin["id"], await db.session_intake(sid)):
        raise HTTPException(403, "intake_out_of_scope")
    q = {"lesson_id": ses.get("lesson_id", "")}
    if ses.get("fork_of") or (ses.get("intake") or ""):
        q["intake"] = ses.get("intake") or ""
    else:
        # baseها هرگز با fork ورودی دیگر swap نمی‌شوند.
        q["fork_of"] = {"$in": [None, ""]}
        q["$or"] = [{"intake": ""}, {"intake": None},
                    {"intake": {"$exists": False}}]
    fn = db.reorder_up if body.direction == "up" else db.reorder_down
    ok = await fn("bs_sessions", sid, q)
    # §W11 — بازچینشِ جلسه ترتیبِ محتوایی را که دانشجو می‌بیند عوض می‌کند،
    # پس یک mutationِ مدیریتیِ ماندگار است و باید مثلِ بقیه ثبت شود.
    # ممیزیِ موجِ ۱۱ نشان داد این تنها شکافِ واقعیِ audit در کلِ پنل بود.
    if ok:
        await _audit(admin["id"], "بازچینش ترتیب جلسه", severity="INFO",
                     target_id=str(sid), target_type="bs_session",
                     target_label=str(ses.get("title") or ses.get("topic") or "")[:100],
                     after={"direction": body.direction,
                            "lesson_id": ses.get("lesson_id", "")},
                     tags=["محتوا", "بازچینش"])
    return {"ok": bool(ok)}


@router.post("/content/items/{cid}/reorder")
async def content_item_reorder(cid: str, body: ReorderIn,
                               admin=Depends(get_content_admin_user)):
    item = await db.bs_get_content_item(cid)
    if not item:
        raise HTTPException(404, "فایل یافت نشد")
    if not await db.can_access_intake(admin["id"], await db.content_intake(cid)):
        raise HTTPException(403, "intake_out_of_scope")
    sid = item.get("session_id", "")
    fn = db.reorder_content_up if body.direction == "up" else db.reorder_content_down
    ok = await fn(cid, sid)
    # §W11 — همان دلیلِ بازچینشِ جلسه: ترتیبِ فایل‌ها برای دانشجو تغییر می‌کند.
    if ok:
        await _audit(admin["id"], "بازچینش ترتیب فایل محتوا", severity="INFO",
                     target_id=str(cid), target_type="bs_content",
                     target_label=str(item.get("description") or "")[:100],
                     after={"direction": body.direction, "session_id": sid},
                     tags=["محتوا", "بازچینش"])
    return {"ok": bool(ok)}


# ══════════════════════════════════════════════════════════════════
# 🌊 WA2.8 — User 360 (کانتکست کامل بدون ترک صفحه)
# ══════════════════════════════════════════════════════════════════

@router.get("/users/{uid}/360")
async def user_360(uid: int, user=Depends(_perm("users.view"))):
    """👤 نمای ۳۶۰ درجه‌ی کاربر — پرونده + اشتراک + نقش‌ها + شمارش‌ها +
    آخرین تیکت‌ها + آخرین رویدادهای audit مرتبط، همه در یک پاسخ."""
    target = await db.get_user(uid)
    if not target:
        raise HTTPException(404, "کاربر یافت نشد")
    out = {
        "user": {
            "id": target.get("user_id"), "name": target.get("name", ""),
            "nickname": target.get("nickname"), "username": target.get("username", ""),
            "display_name": db.display_name_of(target),
            "student_id": target.get("student_id", ""),
            "intake": target.get("intake", ""), "group": target.get("group", ""),
            "role": target.get("role", "student"),
            "approved": target.get("approved", False),
            "suspended": target.get("suspended", False),
            "registered_at": target.get("registered_at") or None,
            "last_active": target.get("last_active") or None,
            "total_answers": target.get("total_answers", 0),
            "correct_answers": target.get("correct_answers", 0),
            "accuracy": round(
                int(target.get("correct_answers") or 0) * 100 /
                int(target.get("total_answers") or 1), 1
            ) if int(target.get("total_answers") or 0) else 0,
            "prestige_rank": target.get("prestige_rank", ""),
            "prestige_div": target.get("prestige_div", ""),
            "streak_current": target.get("streak_current", 0) or 0,
        },
        "subscription": None, "wallet": None, "admin_role": None, "roles": [], "perms": [],
        "counts": {"tickets": 0, "grades": 0, "answers": 0, "questions": 0,
                   "exams": 0, "notifications": 0},
        "recent_tickets": [], "recent_audit": [], "recent_questions": [],
        "recent_exams": [], "recent_notifications": [], "prestige_history": [],
        # Empty و Unavailable دو حالت جدا هستند؛ UI برای هر بخش Retry نشان می‌دهد.
        "section_errors": {},
    }
    try:
        sub = await db.sub_get(uid)
        if sub:
            out["subscription"] = {
                "status": sub.get("status", ""), "plan": sub.get("plan_name", ""),
                "end_date": sub.get("end_date") or None,
                "days_left": await db.sub_days_left(uid),
            }
    except Exception:
        out["section_errors"]["subscription"] = "unavailable"
    try:
        # 💰 W6 — کیف پول در نمای ۳۶۰: موجودی + آخرین تراکنش (server-derived)
        w = await db.wallet_summary(uid)
        out["wallet"] = {
            "balance": w["balance"], "currency": w["currency"],
            "credits_total": w["credits_total"],
            "debits_total": w["debits_total"], "last_tx": w["last_tx"],
        }
    except Exception:
        out["section_errors"]["wallet"] = "unavailable"
    try:
        ar = await db.get_admin_role(uid)
        if ar:
            out["admin_role"] = {"role": ar.get("role"), "scope": ar.get("scope_intake")}
        role_info = await db.get_user_roles(uid)
        out["roles"] = [{
            "key": r.get("_id"), "label": r.get("label", r.get("_id", "")),
            "active": r.get("active", True), "scope": role_info.get("scope_intake"),
        } for r in role_info.get("roles", [])]
    except Exception:
        out["section_errors"]["roles"] = "unavailable"
    try:
        out["perms"] = sorted(await db.get_user_perms(uid))
    except Exception:
        out["section_errors"]["permissions"] = "unavailable"
    try:
        out["counts"]["tickets"] = await db.tickets.count_documents({"user_id": uid})
        out["recent_tickets"] = [{
            "id": t.get("ticket_id"), "subject": t.get("subject", ""),
            "status": t.get("status", ""),
            "at": t.get("created_at") or None,
        } for t in await db.tickets.find({"user_id": uid}).sort("created_at", -1).limit(5).to_list(5)]
    except Exception:
        out["section_errors"]["tickets"] = "unavailable"
    try:
        out["counts"]["grades"] = await db.grades.count_documents({"student_id": uid})
        out["counts"]["answers"] = await db.answers.count_documents({"user_id": uid})
        out["counts"]["questions"] = await db.questions.count_documents({"creator_id": uid})
        out["counts"]["exams"] = await db.exam_sessions.count_documents({"user_id": uid})
    except Exception:
        out["section_errors"]["academic_counts"] = "unavailable"
    try:
        logs = await db.audit_logs.find({"$or": [
            {"actor.id": uid}, {"target.id": str(uid)}, {"target.id": uid},
            {"target_id": str(uid)}, {"target_id": uid},
        ]}).sort("timestamp", -1).limit(20).to_list(20)
        out["recent_audit"] = [{
            "id": str(l.get("_id", "")), "action": l.get("action", ""),
            "module": l.get("module", ""),
            "at": l.get("timestamp") or None,
            "severity": l.get("severity", "INFO"),
            "relation": "actor" if (l.get("actor") or {}).get("id") == uid else "target",
            "changes": l.get("changes") or [],
            "correlation_id": l.get("correlation_id"),
        } for l in logs]
    except Exception:
        out["section_errors"]["audit"] = "unavailable"

    # 🌊 W-Admin — بخش‌های جدید User 360 (افزودنی؛ هر بخش جدا ضدخطا)
    try:  # 📊 تحصیلی — آخرین نمرات
        gdocs = await db.grades.find({"student_id": uid}).sort("exam_date", -1).limit(6).to_list(6)
        out["academic"] = {"grades_recent": [{
            "lesson": g.get("lesson", ""), "exam_title": g.get("exam_title", ""),
            "exam_date": g.get("exam_date", ""), "score": g.get("score", 0),
            # 🛡 AUDIT-§۸۲ — ترم هم در کارنامه‌ی ۳۶۰ دیده می‌شود
            "term": g.get("term", ""),
        } for g in gdocs]}
    except Exception:
        out.setdefault("academic", {"grades_recent": []})
        out["section_errors"]["academic"] = "unavailable"
    try:  # 🤖 هوشیار — از روی سند کاربر (بدون کوئری اضافه)
        today = today_tehran().isoformat()
        out["ai"] = {
            "total_usage": target.get("ai_total_usage", 0) or 0,
            "today": (target.get("ai_usage_count", 0) or 0)
                     if target.get("ai_usage_date") == today else 0,
            "total_tokens": target.get("ai_total_tokens", 0) or 0,
            "banned": bool(target.get("ai_banned")),
        }
    except Exception:
        out.setdefault("ai", {})
        out["section_errors"]["ai"] = "unavailable"
    try:  # 🏆 افتخار — رنک/XP/استریک از سند کاربر
        dx = target.get("daily_xp") or {}
        out["prestige"] = {
            "rank": target.get("prestige_rank", ""), "div": target.get("prestige_div", ""),
            "prestige_xp": target.get("prestige_xp", 0) or 0,
            "effective_xp": target.get("effective_xp", 0) or 0,
            "weekly_xp": target.get("weekly_xp", 0) or 0,
            "monthly_xp": target.get("monthly_xp", 0) or 0,
            "streak_current": target.get("streak_current", 0) or 0,
            "streak_best": target.get("streak_best", 0) or 0,
            "daily_xp_amount": dx.get("amount", 0) or 0,
        }
    except Exception:
        out.setdefault("prestige", {})
        out["section_errors"]["prestige"] = "unavailable"
    try:  # 🔔 اعلان‌ها — شمارش و آخرین آیتم‌ها
        un = await db.user_notifs.count_documents({"user_id": uid, "read": {"$ne": True}})
        tot = await db.user_notifs.count_documents({"user_id": uid})
        ndocs = await db.user_notifs.find({"user_id": uid}).sort("created_at", -1).limit(8).to_list(8)
        out["notifs"] = {"unread": un, "total": tot}
        out["counts"]["notifications"] = tot
        out["recent_notifications"] = [{
            "id": str(n.get("_id", "")), "type": n.get("type", ""),
            "title": n.get("title", ""), "body": n.get("body", ""),
            "read": bool(n.get("read")),
            "at": n.get("created_at") or None,
        } for n in ndocs]
    except Exception:
        out.setdefault("notifs", {})
        out["section_errors"]["notifications"] = "unavailable"
    try:
        qdocs = await db.questions.find({"creator_id": uid}).sort("created_at", -1).limit(8).to_list(8)
        out["recent_questions"] = [{
            "id": str(q.get("_id", "")), "question": (q.get("question") or "")[:180],
            "lesson": q.get("lesson", ""), "topic": q.get("topic", ""),
            "difficulty": q.get("difficulty", ""), "approved": bool(q.get("approved")),
            "attempts": int(q.get("attempt_count") or 0),
            "accuracy": round(int(q.get("correct_count") or 0) * 100 /
                              int(q.get("attempt_count") or 1), 1)
                        if int(q.get("attempt_count") or 0) else 0,
            "at": q.get("created_at") or None,
        } for q in qdocs]
    except Exception:
        out["section_errors"]["questions"] = "unavailable"
    try:
        edocs = await db.exam_sessions.find({"user_id": uid}).sort("started_at", -1).limit(8).to_list(8)
        out["recent_exams"] = [{
            "id": str(e.get("session_id") or e.get("_id", "")),
            "lesson": e.get("lesson", ""), "topic": e.get("topic", ""),
            "status": e.get("status", "active"),
            "answered": int(e.get("answered") or 0), "correct": int(e.get("correct") or 0),
            "total": len(e.get("question_ids") or []),
            "percentage": round(int(e.get("correct") or 0) * 100 /
                                int(e.get("answered") or 1)) if int(e.get("answered") or 0) else 0,
            "started_at": e.get("started_at") or None,
        } for e in edocs]
    except Exception:
        out["section_errors"]["exams"] = "unavailable"
    try:
        # منبع واحد domain: schema واقعی prestige_history با uid/type/detail/at.
        pdocs = await db.prestige_history_list(uid, limit=10)
        out["prestige_history"] = [{
            "id": f"{i}:{p.get('type', '')}:{p.get('at', '')}", "kind": p.get("type", ""),
            "title": p.get("title", "") or p.get("type", ""),
            "xp": int((p.get("detail") or {}).get("xp") or (p.get("detail") or {}).get("amount") or 0),
            "at": p.get("at") or None,
        } for i, p in enumerate(pdocs)]
    except Exception:
        out["section_errors"]["prestige_history"] = "unavailable"
    # Timeline واحد از eventهای واقعی و قابل‌ردیابی؛ هیچ event مصنوعی ساخته نمی‌شود.
    activity = []
    if target.get("registered_at"):
        activity.append({"id": "registration", "kind": "registration", "icon": "👤",
                         "title": "ثبت‌نام در هامزیار", "at": target.get("registered_at") or None,
                         "go": f"/users?q={uid}"})
    try:
        adocs = await db.answers.find({"user_id": uid}).sort("answered_at", -1).limit(12).to_list(12)
        activity.extend({"id": f"answer:{a.get('_id')}", "kind": "answer", "icon": "🧪",
                         "title": "پاسخ صحیح به سؤال" if a.get("is_correct") else "پاسخ به سؤال",
                         "description": f"شناسه سؤال: {a.get('question_id', '')}",
                         "at": a.get("answered_at") or None, "go": f"/questions?q={a.get('question_id', '')}"}
                        for a in adocs)
    except Exception:
        out["section_errors"]["answers"] = "unavailable"
    activity.extend({"id": f"exam:{e['id']}", "kind": "exam", "icon": "📝",
                     "title": f"آزمون {e.get('lesson') or 'سفارشی'}", "description": f"نتیجه {e.get('percentage', 0)}٪",
                     "at": e.get("started_at", ""), "go": "/exams?tab=grades"} for e in out.get("recent_exams", []))
    activity.extend({"id": f"ticket:{t['id']}", "kind": "ticket", "icon": "🎫",
                     "title": t.get("subject") or "تیکت پشتیبانی", "description": t.get("status", ""),
                     "at": t.get("at", ""), "go": f"/tickets?q={t['id']}"} for t in out.get("recent_tickets", []))
    activity.extend({"id": f"prestige:{p['id']}", "kind": "prestige", "icon": "🏆",
                     "title": p.get("title") or p.get("kind") or "رویداد Prestige",
                     "description": f"{p.get('xp', 0):+d} XP", "at": p.get("at", ""), "go": f"/users?q={uid}"}
                    for p in out.get("prestige_history", []))
    activity.extend({"id": f"audit:{a.get('id', i)}", "kind": "audit", "icon": "🧭",
                     "title": a.get("action") or "رویداد حسابرسی", "description": a.get("module", ""),
                     "at": a.get("at", ""), "go": f"/audit?target={uid}"}
                    for i, a in enumerate(out.get("recent_audit", [])))
    out["activity"] = sorted(activity, key=lambda event: event.get("at") or "", reverse=True)[:40]
    return out


@router.get("/users/{uid}/relations/{section}")
async def user_relation_list(
    uid: int, section: str,
    skip: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100),
    user=Depends(_perm("users.view")),
):
    if not await db.get_user(uid):
        raise HTTPException(404, "کاربر یافت نشد")
    specs = {
        "tickets": (db.tickets, {"user_id": uid}, "created_at"),
        "grades": (db.grades, {"student_id": uid}, "exam_date"),
        "answers": (db.answers, {"user_id": uid}, "answered_at"),
        "questions": (db.questions, {"creator_id": uid}, "created_at"),
        "exams": (db.exam_sessions, {"user_id": uid}, "started_at"),
        "notifications": (db.user_notifs, {"user_id": uid}, "created_at"),
        "prestige": (db.prestige_history, {"uid": uid}, "at"),
    }
    if section == "audit":
        col = db.audit_logs
        filt = {"$or": [{"actor.id": uid}, {"target.id": str(uid)},
                         {"target.id": uid}, {"target_id": str(uid)}, {"target_id": uid}]}
        sort_key = "timestamp"
    elif section in specs:
        col, filt, sort_key = specs[section]
    else:
        raise HTTPException(404, "بخش تاریخچه ناشناخته است")
    total, docs = await asyncio.gather(
        col.count_documents(filt),
        col.find(filt).sort(sort_key, -1).skip(skip).limit(limit).to_list(limit),
    )

    def row(doc):
        base = {"id": str(doc.get("_id", ""))}
        if section == "tickets": base.update({"title": doc.get("subject", ""), "status": doc.get("status", ""), "at": doc.get("created_at", "")})
        elif section == "grades": base.update({"title": doc.get("lesson", ""), "detail": doc.get("exam_title", ""), "value": doc.get("score"), "at": doc.get("exam_date", "")})
        elif section == "answers": base.update({"title": str(doc.get("question_id", "")), "status": "correct" if doc.get("is_correct") else "wrong", "at": doc.get("answered_at", "")})
        elif section == "questions": base.update({"title": (doc.get("question") or "")[:220], "detail": f"{doc.get('lesson','')} · {doc.get('topic','')}", "status": canonical_status(doc), "at": doc.get("created_at", "")})
        elif section == "exams": base.update({"title": doc.get("lesson") or "آزمون سفارشی", "detail": doc.get("topic", ""), "status": doc.get("status", ""), "value": doc.get("correct", 0), "at": doc.get("started_at", "")})
        elif section == "notifications": base.update({"title": doc.get("title", ""), "detail": doc.get("body", ""), "status": "read" if doc.get("read") else "unread", "at": doc.get("created_at", "")})
        elif section == "prestige": base.update({"title": doc.get("title") or doc.get("type", ""), "detail": doc.get("detail") or {}, "at": doc.get("at", "")})
        else: base.update({"title": doc.get("action", ""), "detail": doc.get("module", ""), "status": doc.get("severity", "INFO"), "at": doc.get("timestamp", "")})
        return jsonable_encoder(base, custom_encoder={ObjectId: str})
    return {"section": section, "items": [row(doc) for doc in docs],
            "total": total, "skip": skip, "limit": limit}


# ══════════════════════════════════════════════════════════════════
# 🛡 موج RBAC-Execution — مسیرهای permission-based برای Web Admin
# routeهای owner قدیمی دست‌نخورده‌اند؛ این wrapperها همان business logic
# موجود را با guard دانه‌ای فراخوانی می‌کنند.
# ══════════════════════════════════════════════════════════════════

# ── RBAC helpers ──────────────────────────────────────────────────

@router.get("/rbac/intakes")
async def wa_rbac_intakes(user=Depends(_perm("users.manage"))):
    items = await db.get_all_intakes()
    return {"intakes": [
        {"code": i.get("code", ""), "label": i.get("label", i.get("code", "")),
         "active": i.get("active", True)}
        for i in items
    ]}


@router.get("/rbac/roles-picker")
async def wa_rbac_roles_picker(user=Depends(_perm("users.manage"))):
    """فهرست کمینه و فقط‌خواندنی نقش‌ها برای filter/bulk کاربر."""
    roles = await db.list_roles()
    return {"roles": [{
        "key": r.get("_id"), "label": r.get("label", r.get("_id", "")),
        "active": r.get("active", True),
    } for r in roles if r.get("active", True)]}


# ── Tickets ───────────────────────────────────────────────────────

@router.get("/tickets")
async def wa_tickets_list(
    status: Optional[str] = Query(None, pattern="^(open|in_progress|waiting_user|resolved|answered|closed)$"),
    q: Optional[str] = Query(None, max_length=120),
    intake: Optional[str] = Query(None, max_length=80),
    priority: Optional[str] = Query(None, pattern="^(low|normal|high|urgent)$"),
    assignee_id: Optional[int] = Query(None), unanswered: Optional[bool] = Query(None),
    date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
    sort_by: str = Query("created_at", pattern="^(created_at|last_reply_at)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1), limit: int = Query(30, ge=1, le=100),
    user=Depends(_perm_any("tickets.reply", "tickets.manage")),
):
    """Support queue با search/filter/pagination سرورساید؛ legacy owner route حفظ شده."""
    q = q if isinstance(q, str) else None
    intake = intake if isinstance(intake, str) else None
    priority = priority if isinstance(priority, str) else None
    assignee_id = assignee_id if isinstance(assignee_id, int) else None
    unanswered = unanswered if isinstance(unanswered, bool) else None
    date_from = date_from if isinstance(date_from, str) else None
    date_to = date_to if isinstance(date_to, str) else None
    sort_by = sort_by if isinstance(sort_by, str) else "created_at"
    sort_dir = sort_dir if isinstance(sort_dir, str) else "desc"
    page = page if isinstance(page, int) else 1
    limit = limit if isinstance(limit, int) else 30
    return await owner_api.all_tickets(
        status=status, q=q, intake=intake, priority=priority,
        assignee_id=assignee_id, unanswered=unanswered,
        date_from=date_from, date_to=date_to, sort_by=sort_by, sort_dir=sort_dir,
        page=page, limit=limit, admin=user,
    )


@router.get("/exports/tickets.csv")
async def export_tickets_csv(
    status: Optional[str] = Query(None, pattern="^(open|in_progress|waiting_user|resolved|answered|closed)$"),
    q: Optional[str] = Query(None), intake: Optional[str] = Query(None),
    priority: Optional[str] = Query(None, pattern="^(low|normal|high|urgent)$"),
    assignee_id: Optional[int] = Query(None), unanswered: Optional[bool] = Query(None),
    date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
    sort_by: str = Query("created_at", pattern="^(created_at|last_reply_at)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"), human: bool = False,
    user=Depends(_perm_any("tickets.reply", "tickets.manage")),
):
    await rate_limit_user(user["id"], "export_tickets_csv", 10, 60)  # 🛡 W10
    await _audit(user["id"], "خروجی CSV تیکت‌ها", severity="HIGH",
                 target_type="export", target_label="tickets.csv",
                 tags=["خروجی", "تیکت", "پنل_وب"])
    columns = ["id", "subject", "user_id", "user_name", "status", "priority",
               "assignee_id", "assignee_name", "reply_count", "created_at", "last_reply_at", "tags"]
    def safe(value):
        text = "" if value is None else str(value)
        return "'" + text if text[:1] in ("=", "+", "-", "@") else text
    async def stream():
        buf = io.StringIO(); writer = csv.writer(buf); writer.writerow(columns)
        yield "\ufeff" + buf.getvalue(); buf.seek(0); buf.truncate(0)
        page = 1
        while True:
            result = await owner_api.all_tickets(
                admin=user, status=status, q=q, intake=intake, priority=priority,
                assignee_id=assignee_id, unanswered=unanswered, date_from=date_from,
                date_to=date_to, sort_by=sort_by, sort_dir=sort_dir, page=page, limit=100)
            rows = result.get("tickets") or []
            for row in rows:
                writer.writerow([safe(v) for v in [row.get("id"), row.get("subject"), row.get("user_id"),
                    row.get("user_name"), row.get("status"), row.get("priority"), row.get("assignee_id"),
                    row.get("assignee_name"), row.get("reply_count"),
                    _export_instant(row.get("created_at"), human),
                    _export_instant(row.get("last_reply_at"), human), "|".join(row.get("tags") or [])]])
                yield buf.getvalue(); buf.seek(0); buf.truncate(0)
            if not rows or page >= int(result.get("pages") or 1): break
            page += 1
    return StreamingResponse(stream(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=humsyar-tickets.csv"})


@router.get("/tickets/assignees")
async def wa_ticket_assignees(user=Depends(_perm_any("tickets.reply", "tickets.manage"))):
    roles = await db.list_roles()
    role_keys = [r.get("_id") for r in roles
                 if r.get("active", True) and set(r.get("perms") or []) & {"tickets.reply", "tickets.manage"}]
    ids = {ADMIN_ID}
    for key in role_keys:
        ids.update(await db.user_ids_by_role(key, limit=100000))
    docs = await db.users.find({"user_id": {"$in": list(ids)}}, {
        "user_id": 1, "name": 1, "username": 1,
    }).sort("name", 1).to_list(100000)
    intakes = await db.get_all_intakes()
    return {"assignees": [{"id": u.get("user_id"), "name": u.get("name", ""),
                             "username": u.get("username", "")} for u in docs],
            "intakes": [{"code": i.get("code", ""), "label": i.get("label", i.get("code", ""))}
                        for i in intakes]}


@router.get("/tickets/{tid}")
async def wa_ticket_detail(
    tid: int,
    user=Depends(_perm_any("tickets.reply", "tickets.manage")),
):
    result = await owner_api.ticket_detail(tid=tid, admin=user)
    raw = await db.ticket_get(tid)
    ticket = result.get("ticket") or {}
    ticket.update({
        "priority": (raw or {}).get("priority", "normal"),
        "tags": (raw or {}).get("tags") or [],
        "assignee_id": (raw or {}).get("assignee_id"),
        "assignee_name": (raw or {}).get("assignee_name", ""),
        "internal_notes": [{
            "id": str(n.get("id") or i), "text": n.get("text", ""),
            "actor_id": n.get("actor_id"), "actor_name": n.get("actor_name", ""),
            "at": n.get("at") or None,
        } for i, n in enumerate((raw or {}).get("internal_notes") or [])],
    })
    return result


class TicketMetaPatch(BaseModel):
    priority: Optional[str] = None
    tags: Optional[list[str]] = None
    assignee_id: Optional[int] = None
    status: Optional[str] = None  # 🌊 W9 — تغییر وضعیت گاردشده


@router.patch("/tickets/{tid}/meta")
async def wa_ticket_meta(
    tid: int, body: TicketMetaPatch,
    user=Depends(_perm("tickets.manage")),
):
    ticket = await db.ticket_get(tid)
    if not ticket:
        raise HTTPException(404, "تیکت پیدا نشد")
    updates = {}
    if body.priority is not None:
        if body.priority not in ("low", "normal", "high", "urgent"):
            raise HTTPException(422, "اولویت نامعتبر است")
        updates["priority"] = body.priority
        # 🌊 W8/UX-04 — ارتقا/تنزل اولویت، مهلت SLA را بازمحاسبه می‌کند
        updates["sla_hours"] = await db.ticket_sla_hours(body.priority)
    if body.tags is not None:
        updates["tags"] = list(dict.fromkeys(
            str(tag).strip()[:30] for tag in body.tags if str(tag).strip()
        ))[:12]
    if "assignee_id" in body.model_fields_set:
        if body.assignee_id is None:
            updates.update({"assignee_id": None, "assignee_name": ""})
        else:
            assignee = await db.get_user(body.assignee_id)
            if not assignee or not await db.has_permission(body.assignee_id, "tickets.reply"):
                raise HTTPException(422, "مسئول انتخابی مجوز پاسخ‌گویی ندارد")
            updates.update({"assignee_id": body.assignee_id,
                            "assignee_name": assignee.get("name", str(body.assignee_id))})
    if not updates:
        raise HTTPException(422, "تغییری ارسال نشده است")
    # 🌊 W9 — وضعیت از مسیر گارد می‌گذرد (transition نامعتبر ⇒ 409)
    if body.status is not None:
        res = await db.ticket_set_status(tid, body.status)
        if not res.get("ok"):
            raise HTTPException(
                409 if res.get("error") in ("invalid_transition", "race")
                else 404, "تغییر وضعیت مجاز نیست")
        updates["status"] = res["to"]
    before = {key: ticket.get(key) for key in updates
              if key != "status"}
    if "status" in updates:
        before["status"] = res.get("frm")
    if updates:
        await db.tickets.update_one({"ticket_id": tid}, {"$set": updates})
    await _audit(user["id"], "ویرایش صف/متادیتای تیکت", severity="WARNING",
                 target_id=tid, target_type="ticket", target_label=ticket.get("subject", ""),
                 before=before, after=updates, tags=["تیکت", "متادیتا", "پنل_وب"])
    return {"ok": True, "changed": list(updates)}


class TicketNoteIn(BaseModel):
    text: str


@router.post("/tickets/{tid}/notes")
async def wa_ticket_note(
    tid: int, body: TicketNoteIn,
    user=Depends(_perm("tickets.manage")),
):
    ticket = await db.ticket_get(tid)
    if not ticket:
        raise HTTPException(404, "تیکت پیدا نشد")
    text = (body.text or "").strip()
    if not (1 <= len(text) <= 1500):
        raise HTTPException(422, "یادداشت باید بین ۱ تا ۱۵۰۰ کاراکتر باشد")
    actor = user.get("_db") or await db.get_user(user["id"]) or {}
    note = {"id": secrets.token_hex(8), "text": text, "actor_id": user["id"],
            "actor_name": actor.get("name", str(user["id"])), "at": _now()}
    await db._push_capped("tickets", {"ticket_id": tid}, "internal_notes",
                          note, db.NOTE_INLINE_CAP, archive_kind="notes")
    await _audit(user["id"], "افزودن یادداشت داخلی تیکت", severity="INFO",
                 target_id=tid, target_type="ticket", target_label=ticket.get("subject", ""),
                 after={"note_id": note["id"]}, tags=["تیکت", "یادداشت_داخلی", "پنل_وب"])
    return {"ok": True, "note": note}


@router.get("/tickets/analytics/summary")
async def wa_tickets_analytics(user=Depends(_perm("tickets.manage"))):
    docs = await db.tickets.find({}, {
        "status": 1, "priority": 1, "assignee_id": 1, "assignee_name": 1,
        "created_at": 1, "closed_at": 1, "replies": 1,
    }).sort("created_at", -1).limit(5000).to_list(5000)
    status_counts, priority_counts, workload = {}, {}, {}
    response_minutes, resolution_minutes = [], []
    for t in docs:
        status = t.get("status", "open"); status_counts[status] = status_counts.get(status, 0) + 1
        priority = t.get("priority", "normal"); priority_counts[priority] = priority_counts.get(priority, 0) + 1
        if t.get("assignee_id"):
            key = str(t.get("assignee_id")); workload.setdefault(key, {"name": t.get("assignee_name", key), "count": 0})["count"] += 1
        try:
            created = parse_machine_datetime(t.get("created_at", ""))
            admin_reply = next((r for r in (t.get("replies") or []) if not (r.get("text") or "").startswith("[دانشجو]")), None)
            if admin_reply and admin_reply.get("at"):
                response_minutes.append(max(0, (parse_machine_datetime(admin_reply["at"]) - created).total_seconds() / 60))
            if t.get("closed_at"):
                resolution_minutes.append(max(0, (parse_machine_datetime(t["closed_at"]) - created).total_seconds() / 60))
        except (TypeError, ValueError):
            pass
    avg = lambda rows: round(sum(rows) / len(rows), 1) if rows else None
    return {"total": len(docs), "sample_limited": len(docs) == 5000,
            "status": status_counts, "priority": priority_counts,
            "avg_first_response_minutes": avg(response_minutes),
            "avg_resolution_minutes": avg(resolution_minutes),
            "workload": sorted(workload.values(), key=lambda x: x["count"], reverse=True)[:10]}


@router.post("/tickets/{tid}/reply")
async def wa_ticket_reply(
    tid: int,
    body: owner_api.AdminReply,
    user=Depends(_perm("tickets.reply")),
):
    return await owner_api.admin_reply(tid=tid, body=body, admin=user)


@router.post("/tickets/{tid}/close")
async def wa_ticket_close(tid: int, user=Depends(_perm("tickets.manage"))):
    return await owner_api.close_ticket(tid=tid, admin=user)


@router.get("/tickets/canned")
async def wa_canned_list(user=Depends(_perm("tickets.manage"))):
    """🌊 W8/UX-04 — پاسخ‌های آماده."""
    return await owner_api.canned_list_ep(admin=user)


@router.post("/tickets/canned")
async def wa_canned_add(body: owner_api.CannedBody,
                        user=Depends(_perm("tickets.manage"))):
    return await owner_api.canned_add_ep(body=body, admin=user)


@router.put("/tickets/canned/{cid}")
async def wa_canned_update(cid: str, body: owner_api.CannedBody,
                           user=Depends(_perm("tickets.manage"))):
    return await owner_api.canned_update_ep(cid=cid, body=body, admin=user)


@router.delete("/tickets/canned/{cid}")
async def wa_canned_delete(cid: str, user=Depends(_perm("tickets.manage"))):
    return await owner_api.canned_delete_ep(cid=cid, admin=user)


@router.post("/tickets/{tid}/reopen")
async def wa_ticket_reopen(tid: int, user=Depends(_perm("tickets.manage"))):
    return await owner_api.reopen_ticket(tid=tid, admin=user)


# ── Broadcast / Poll / notification settings ──────────────────────

@router.get("/intakes-picker")
async def wa_intakes_picker(user=Depends(_perm("broadcast.send"))):
    items = await db.get_all_intakes()
    return {"intakes": [
        {"code": i.get("code", ""), "label": i.get("label", i.get("code", "")),
         "active": i.get("active", True)}
        for i in items
    ]}


@router.post("/broadcast/preview")
async def wa_broadcast_preview(
    body: owner_api.BroadcastPreview,
    user=Depends(_perm("broadcast.send")),
):
    return await owner_api.broadcast_preview(body=body, admin=user)


@router.post("/broadcast")
async def wa_broadcast_send(
    body: owner_api.BroadcastSend,
    user=Depends(_perm("broadcast.send")),
):
    return await owner_api.broadcast(body=body, admin=user)


@router.post("/broadcast/media")
async def wa_broadcast_media_upload(
    media_type: str = Form(...), file: UploadFile = File(...),
    user=Depends(_perm("broadcast.send")),
):
    if media_type not in {"photo", "video", "document", "voice", "audio"}:
        raise HTTPException(422, "نوع رسانه پشتیبانی نمی‌شود")
    raw = await file.read(50 * 1024 * 1024 + 1)
    if len(raw) > 50 * 1024 * 1024:
        raise HTTPException(413, "حجم فایل بیشتر از ۵۰MB است")
    limits = {"photo": 10, "voice": 25, "audio": 45, "video": 45, "document": 45}
    if not raw or len(raw) > limits[media_type] * 1024 * 1024:
        raise HTTPException(413, f"حجم فایل برای {media_type} نامعتبر یا بیش از حد مجاز است")
    try:
        file_id = await broadcast_service.upload_media(
            user["id"], media_type, file.filename or "broadcast-file", raw,
            file.content_type or "application/octet-stream")
    except Exception:
        raise HTTPException(502, "آپلود رسانه به تلگرام ناموفق بود")
    return {"ok": True, "media_type": media_type, "file_id": file_id,
            "filename": file.filename or ""}


@router.post("/broadcast/test")
async def wa_broadcast_test(
    body: owner_api.BroadcastSend,
    user=Depends(_perm("broadcast.send")),
):
    try:
        result = await broadcast_service.send_payload_http(user["id"], body.payload())
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception:
        raise HTTPException(502, "ارسال آزمایشی به تلگرام ناموفق بود")
    await _audit(user["id"], "ارسال آزمایشی کمپین", severity="INFO",
                 target_id=user["id"], target_type="broadcast_test",
                 tags=["ارسال_همگانی", "test_send", "پنل_وب"])
    return {**result, "request_id": current_request_id.get()}


@router.get("/broadcast/campaigns/{campaign_id}")
async def wa_broadcast_campaign_detail(campaign_id: str,
                                       user=Depends(_perm("broadcast.send"))):
    doc = await broadcast_service.refresh_campaign(campaign_id)
    if not doc:
        raise HTTPException(404, "کمپین پیدا نشد")
    failed = await db.bot_notifs.find(
        {"campaign_id": campaign_id, "failed": True},
        {"chat_id": 1, "error": 1, "sent_at": 1}).limit(100).to_list(100)
    return {"campaign": broadcast_service.campaign_row(doc),
            "pending": int(doc.get("pending") or 0),
            "failures": [{"user_id": row.get("chat_id"),
                            "error": row.get("error") or "send_failed",
                            "at": row.get("sent_at", "")} for row in failed],
            "failures_truncated": int(doc.get("failed") or 0) > len(failed)}


@router.post("/broadcast/campaigns/{campaign_id}/retry-failed")
async def wa_broadcast_campaign_retry(campaign_id: str,
                                      user=Depends(_perm("broadcast.send"))):
    try: oid = ObjectId(campaign_id)
    except Exception: raise HTTPException(422, "شناسه کمپین نامعتبر است")
    campaign = await db.broadcast_campaigns.find_one({"_id": oid})
    if not campaign:
        raise HTTPException(404, "کمپین پیدا نشد")
    failed = await db.bot_notifs.count_documents({"campaign_id": campaign_id, "failed": True})
    if not failed:
        raise HTTPException(404, "گیرنده ناموفقی برای تلاش مجدد نیست")
    await db.bot_notifs.update_many({"campaign_id": campaign_id, "failed": True},
        {"$set": {"sent": False, "failed": False}, "$unset": {"error": "", "sent_at": ""}})
    await db.broadcast_campaigns.update_one({"_id": oid},
        {"$inc": {"failed": -failed}, "$set": {"status": "queued", "finished_at": None, "updated_at": _now()}})
    await _audit(user["id"], "تلاش مجدد گیرندگان ناموفق کمپین", severity="WARNING",
                 target_id=campaign_id, target_type="broadcast_campaign",
                 after={"requeued": failed}, tags=["ارسال_همگانی", "retry_failed", "پنل_وب"])
    return {"ok": True, "requeued": failed}


@router.get("/broadcast/options")
async def wa_broadcast_options(user=Depends(_perm("broadcast.send"))):
    """گزینه‌های segment واقعی؛ فقط metadata نقش و وضعیت‌های persisted."""
    roles = await db.list_roles()
    return {"roles": [{"key": r.get("_id"), "label": r.get("label") or r.get("_id")}
                      for r in roles if r.get("_id") and r.get("active", True)],
            "subscription_statuses": [
                {"key": "active", "label": "اشتراک فعال"},
                {"key": "inactive", "label": "بدون اشتراک فعال"},
                {"key": "expiring_7", "label": "پایان اشتراک تا ۷ روز"},
            ]}


@router.get("/broadcast/history")
async def wa_broadcast_history(user=Depends(_perm("broadcast.send"))):
    return await owner_api.broadcast_history(admin=user, limit=20)


@router.get("/broadcast/scheduled")
async def wa_broadcast_scheduled(user=Depends(_perm("broadcast.send"))):
    return await owner_api.broadcast_scheduled(admin=user, limit=10)


@router.post("/broadcast/cancel")
async def wa_broadcast_cancel(
    body: owner_api.BroadcastCancel,
    user=Depends(_perm("broadcast.send")),
):
    return await owner_api.broadcast_cancel(body=body, admin=user)


@router.get("/poll/status")
async def wa_poll_status(user=Depends(_perm("notifications.manage"))):
    return await owner_api.poll_status(admin=user)


@router.post("/poll/channel")
async def wa_poll_channel(
    body: owner_api.PollChannelSet,
    user=Depends(_perm("notifications.manage")),
):
    old = await db.get_setting("poll_channel_id", None)
    result = await owner_api.poll_channel_set(body=body, admin=user)
    await _audit(user["id"], "تغییر کانال نظرسنجی", severity="WARNING",
                 before={"کانال": old}, after={"کانال": body.channel_id.strip()},
                 tags=["نظرسنجی", "پنل_وب"])
    return result


@router.post("/poll")
async def wa_poll_create(
    body: owner_api.PollCreate,
    user=Depends(_perm("notifications.manage")),
):
    return await owner_api.poll_create(body=body, admin=user)


@router.get("/notifications/settings")
async def wa_notif_settings(user=Depends(_perm("notifications.manage"))):
    return await owner_api.notif_settings(admin=user)


@router.post("/notifications/settings")
async def wa_notif_settings_update(
    body: owner_api.NotifSettingsUpdate,
    user=Depends(_perm("notifications.manage")),
):
    return await owner_api.notif_settings_update(body=body, admin=user)


# ── Subscription Control Center (delegated via subscription.manage) ──

@router.get("/subscription/overview")
async def wa_subscription_overview(user=Depends(_perm("subscription.manage"))):
    return await subscription_api.overview(admin=user)


@router.get("/subscription/payments")
async def wa_subscription_payments(
    status: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    search: Optional[str] = Query(None),
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.payments(
        status=status, kind=kind, skip=skip, limit=limit, search=search, admin=user)


@router.post("/subscription/payments/{payment_id}/decision")
async def wa_subscription_decision(
    payment_id: str,
    body: subscription_api.DecisionBody,
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.decide_payment(
        payment_id=payment_id, body=body, admin=user)


@router.get("/subscription/payments/{payment_id}/receipt")
async def wa_subscription_receipt(
    payment_id: str,
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.payment_receipt(payment_id=payment_id, admin=user)


@router.get("/subscription/discounts")
async def wa_subscription_discounts(user=Depends(_perm("subscription.manage"))):
    return await subscription_api.discounts(admin=user)


@router.patch("/subscription/settings")
async def wa_subscription_settings(
    body: subscription_api.SubscriptionSettingsBody,
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.update_subscription_settings(body=body, admin=user)


@router.post("/subscription/plans")
async def wa_subscription_plan_add(
    body: subscription_api.PlanBody,
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.add_plan(body=body, admin=user)


@router.put("/subscription/plans/{plan_id}")
async def wa_subscription_plan_update(
    plan_id: str,
    body: subscription_api.PlanBody,
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.update_plan(plan_id=plan_id, body=body, admin=user)


@router.post("/subscription/plans/{plan_id}/toggle")
async def wa_subscription_plan_toggle(
    plan_id: str,
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.toggle_plan(plan_id=plan_id, admin=user)


@router.delete("/subscription/plans/{plan_id}")
async def wa_subscription_plan_delete(
    plan_id: str,
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.delete_plan(plan_id=plan_id, admin=user)


@router.post("/subscription/payments/{payment_id}/send-receipt")
async def wa_subscription_send_receipt(
    payment_id: str,
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.send_receipt(payment_id=payment_id, admin=user)


# ══════════════════════════════════════════════════════════════════
# 🌊 WA23 / W5 — Finance Completeness: بازگشت وجه + مغایرت‌گیری
#
# فقط روی primitiveهای موجود: گذار اتمیکِ الگوی AUDIT-A1 (db/finance.py)،
# sub_revoke، audit_logs و bot_notifications. نه کالکیشن جدید، نه RBAC
# موازی — همان گیت `subscription.manage`.
# تصمیم محصول (مستند، نه پنهان): بازگشت وجه، دوره‌ی اشتراکِ تمدیدشده را
# جراحی نمی‌کند (extend=True روزها را ادغام کرده)؛ پس revoke اختیاریِ
# صریح است و حالت «refunded ولی اشتراک فعال» در مغایرت‌گیری پرچم می‌ماند
# تا اپراتور تصمیم بگیرد — نه حذف خودکارِ روزهای کاربر.
# ══════════════════════════════════════════════════════════════════

_RECON_META = {
    "approved_no_active_sub": ("high", "تأییدشده بدون اشتراک فعال"),
    "active_sub_no_approved_payment": ("high", "اشتراک فعال بدون پرداخت تأییدشده"),
    "refunded_but_active_sub": ("critical", "بازگشت وجه شده ولی اشتراک هنوز فعال"),
    "pending_stale": ("warning", "رسید قدیمی در انتظار بررسی"),
    "approved_topup_not_credited": ("high", "شارژ تأییدشده بدون اعتبار کیف پول"),
    "approved_discount_overrun": ("high", "تخفیف خارج از ظرفیت در پرداخت تأییدشده"),
}


class WaRefundBody(BaseModel):
    confirm: bool = False
    reason: str = ""
    revoke_subscription: bool = False


@router.post("/subscription/payments/{payment_id}/refund")
async def wa_subscription_refund(payment_id: str, body: WaRefundBody,
                                 user=Depends(_perm("subscription.manage"))):
    """🌊 W5 — بازگشت وجه رسید تأییدشده: تأیید صریح + دلیل + گذار اتمیک +
    Audit بحرانی + اطلاع به دانشجو. revoke اشتراک اختیاری و صریح است."""
    if not body.confirm:
        raise HTTPException(400, "بازگشت وجه بدون تأیید صریح ممکن نیست")
    reason = (body.reason or "").strip()
    if len(reason) < 3:
        raise HTTPException(400, "دلیل بازگشت وجه باید حداقل ۳ نویسه باشد")
    payment = await db.sub_payment_get(payment_id)
    if not payment:
        raise HTTPException(404, "رسید پیدا نشد")
    if payment.get("status") != "approved":
        raise HTTPException(409, "فقط رسید تأییدشده قابل بازگشت وجه است")
    uid = int(payment.get("user_id") or 0)
    if not await db.sub_payment_refund(payment_id, admin_id=int(user["id"]),
                                       reason=reason):
        raise HTTPException(409, "این رسید هم‌زمان بازگشت وجه شده است")
    # 🌊 W3/MISS-02 — اگر پول واقعی در درگاه گرفته شده (ref_id دارد)،
    # reversal خودکار ممکن نیست (فقط برای verifyنشده‌ها)؛ بازوی درگاهی
    # «دستی» علامت می‌خورد تا اپراتور در پنل زرین‌پال هم اقدام کند.
    gateway_reversal = None
    if (payment.get("method") == "zarinpal" or payment.get("zarinpal_authority")) \
            and payment.get("zarinpal_ref_id"):
        gateway_reversal = "manual_required"
        await db.sub_payment_mark_gateway_reversal(str(payment["_id"]))
    revoked = False
    if body.revoke_subscription:
        revoked = await db.sub_revoke(uid, f"بازگشت وجه: {reason}",
                                      int(user["id"]))
    # 💰 W6 — بازگشت وجه = اعتبار کیف پول داخلی (نه فقط status).
    # مبلغ از خودِ رسید (سرور-ساید)؛ idempotency با کلید یکتای
    # (sub_payment_refund, payment_id) — حتی اگر این خط دوبار اجرا شود.
    # اگر اعتبار ناموفق باشد، مغایرت‌گیری «refund_without_wallet_credit»
    # را بحرانی پرچم می‌کند (هرگز خطای مالی پنهان نمی‌شود).
    amount = int(payment.get("final_price") or payment.get("amount") or 0)
    credit_tx = None
    balance_after = None
    if amount > 0:
        try:
            tx = await db.wallet_credit(
                uid, amount, "refund_credit", "sub_payment_refund",
                str(payment["_id"]), int(user["id"]),
                f"بازگشت وجه — {payment.get('plan_name') or 'اشتراک'}")
            credit_tx = str(tx.get("_id"))
            balance_after = tx.get("balance_after")
        except Exception as e:
            logger.warning(f"refund wallet credit failed {payment_id}: {e}")
    log_id = await _audit(
        int(user["id"]), "بازگشت وجه رسید پرداخت", severity="CRITICAL",
        target_type="sub_payment", target_id=str(payment["_id"]),
        target_label=f"رسید کاربر {uid}",
        before={"status": "approved",
                "amount": payment.get("final_price", payment.get("amount"))},
        after={"status": "refunded", "reason": reason,
               "revoked_subscription": revoked,
               "wallet_credited": bool(credit_tx),
               "wallet_tx_id": credit_tx,
               "gateway_reversal": gateway_reversal},
        tags=["مالی", "بازگشت_وجه"])
    if amount > 0 and credit_tx:
        text = (f"💸 مبلغ {amount:,} تومان به کیف پول شما بازگشت. "
                f"می‌توانید با آن اشتراک بخرید.")
    else:
        text = f"💸 بازگشت وجه رسید شما ثبت شد: {reason}"
    await db.client["medicalbot"]["bot_notifications"].insert_one({
        "type": "event:refund", "chat_id": uid, "sent": False,
        "text": text, "created_at": _now()})
    return {"ok": True, "payment_id": str(payment["_id"]),
            "gateway_reversal": gateway_reversal,
            "revoked_subscription": bool(revoked),
            "wallet_credited": bool(credit_tx),
            "wallet_tx_id": credit_tx,
            "wallet_balance_after": balance_after,
            "audit_id": log_id}


@router.get("/subscription/reconcile")
async def wa_subscription_reconcile(
        user=Depends(_perm("subscription.manage"))):
    """🌊 W5 — مغایرت‌گیری مالی فقط‌خواندنی: ناهم‌خوانی‌های بین
    sub_payments و subscriptions که هر کدام یعنی «پول/دسترسی بی‌حساب».

    همه‌ی خواندن‌ها کرانه‌دار است (to_list محدود) — بدون اسکن بی‌پایان."""
    items = []
    active_subs = {s["_id"] for s in await db.subscriptions.find(
        {"status": "active"}).to_list(length=10000)}
    users_with_approved = {
        int(r["_id"]) for r in await db.sub_payments.aggregate([
            {"$match": {"status": "approved",
                        "plan_id": {"$ne": "wallet_topup"}}},
            {"$group": {"_id": "$user_id"}},
        ]).to_list(length=10000)}
    # ۱) تأییدشده ولی کاربر اشتراک فعال ندارد
    # 🛡 W1 — رسید شارژ ذاتاً اشتراک نمی‌سازد (آشکارساز ۱-ب)؛
    # رسید هدیه هم اشتراکِ «گیرنده» را می‌سازد نه payer.
    # 🌊 W5 — پنجره‌ی زمانی: اشتراکی که خیلی وقت پیش به‌صورت طبیعی
    # منقضی شده «ناهم‌خوانی» نیست؛ فقط پنجره‌ی اخیر پرچم می‌خورد تا
    # لیست با نویز انقضاهای قدیمی دفن نشود.
    try:
        _w5win = max(7, int(await db.get_setting("recon_window_days", 90) or 90))
    except Exception:
        _w5win = 90
    _cutoff = (datetime.now(timezone.utc) - timedelta(days=_w5win)).isoformat()
    _skipped_stale = 0
    async for p in db.sub_payments.find(
            {"status": "approved"}).sort("reviewed_at", -1).limit(200):
        if str(p.get("plan_id") or "") == "wallet_topup":
            continue
        _at = str(p.get("reviewed_at") or p.get("submitted_at") or "")
        if _at < _cutoff:
            _skipped_stale += 1
            continue
        uid = int(p.get("user_id") or 0)
        gift_to = int((p.get("gift") or {}).get("to") or 0)
        if (gift_to or uid) not in active_subs:
            items.append({"type": "approved_no_active_sub", "user_id": uid,
                          "payment": p,
                          "at": p.get("reviewed_at") or p.get("submitted_at")})
    # ۱-ب) 🛡 W1 — رسید شارژِ تأییدشده که اعتبارش به کیف ننشسته
    # (کرش بین تأیید و finalize) — اقدام: اجرای idempotent دوباره‌ی finalize.
    async for p in db.sub_payments.find(
            {"status": "approved", "plan_id": "wallet_topup",
             "topup_credited_at": None}).sort("reviewed_at", -1).limit(200):
        items.append({"type": "approved_topup_not_credited",
                      "user_id": int(p.get("user_id") or 0),
                      "payment": p,
                      "at": p.get("reviewed_at") or p.get("submitted_at")})
    # ۱-ج) 🌊 W3 — پرداخت تأییدشده‌ای که کد تخفیفش بعد از پرداخت موفق
    # ظرفیت نداشت (overrun) — پول گرفته و approve شده؛ بازبینی مدیریتی.
    async for p in db.sub_payments.find(
            {"status": "approved", "discount_overrun": True}).sort("reviewed_at", -1).limit(200):
        items.append({"type": "approved_discount_overrun",
                      "user_id": int(p.get("user_id") or 0),
                      "payment": p,
                      "at": p.get("reviewed_at") or p.get("submitted_at")})
    # ۲) اشتراک فعال (منبع پرداخت) بدون هیچ پرداخت تأییدشده
    async for s in db.subscriptions.find(
            {"status": "active", "source": "payment"}).limit(200):
        uid = int(s["_id"])
        if uid not in users_with_approved:
            items.append({"type": "active_sub_no_approved_payment",
                          "user_id": uid, "payment": None,
                          "at": s.get("end_date")})
    # ۳) بازگشت وجه شده ولی اشتراک هنوز فعال
    async for p in db.sub_payments.find(
            {"status": "refunded"}).sort("refunded_at", -1).limit(200):
        uid = int(p.get("user_id") or 0)
        if uid in active_subs:
            items.append({"type": "refunded_but_active_sub", "user_id": uid,
                          "payment": p,
                          "at": p.get("refunded_at")})
    # ۴) رسیدهای مانده‌ی قدیمی (>۷۲ ساعت)
    stale = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
    async for p in db.sub_payments.find(
            {"status": "pending",
             "submitted_at": {"$lt": stale}}).limit(200):
        items.append({"type": "pending_stale",
                      "user_id": int(p.get("user_id") or 0),
                      "payment": p,
                      "at": p.get("submitted_at")})
    # 🌊 W5 — مغایرت باید برای ادمین انسانی باشد: نام کاربر، مبلغ، پلن،
    # جمله‌ی توضیح و اقدامِ ممکن. ID فقط در technical.
    uids = list({i["user_id"] for i in items})
    users = {}
    if uids:
        for u in await db.users.find({"user_id": {"$in": uids}}).to_list(1000):
            users[int(u["user_id"])] = u
    summary = {t: sum(1 for i in items if i["type"] == t)
               for t in _RECON_META}
    out_items = []
    for i in items:
        sev, label = _RECON_META[i["type"]]
        p = i.get("payment") or {}
        u = users.get(i["user_id"]) or {}
        who = u.get("name") or f"کاربر #{i['user_id']}"
        amount = p.get("final_price", p.get("amount"))
        t = i["type"]
        if t == "approved_no_active_sub":
            text = (f"رسید {who} به مبلغ {int(amount or 0):,} تومان تأیید شده "
                    f"ولی هیچ اشتراک فعالی برایش وجود ندارد.")
            actions = [{"key": "activate", "label": "فعال‌سازی امن اشتراک"},
                       {"key": "go", "label": "بررسی رسید",
                        "go": f"/subscriptions?tab=payments&q={i['user_id']}"}]
        elif t == "approved_topup_not_credited":
            text = (f"رسید شارژ {who} به مبلغ {int(amount or 0):,} تومان تأیید شده "
                    f"ولی اعتبارش به کیف پول ننشسته است.")
            actions = [{"key": "finalize_topup", "label": "اعمال اعتبار شارژ"},
                       {"key": "go", "label": "بررسی کیف پول",
                        "go": f"/subscriptions?tab=wallets&q={i['user_id']}"}]
        elif t == "approved_discount_overrun":
            text = (f"پرداخت {who} به مبلغ {int(amount or 0):,} تومان با کد تخفیف "
                    f"«{p.get('discount_code') or '—'}» تأیید شده ولی ظرفیت کد تمام شده بود — "
                    f"تخفیف خارج از ظرفیت داده شد؛ بازبینی شود.")
            actions = [{"key": "go", "label": "بررسی رسید",
                        "go": f"/subscriptions?tab=payments&q={i['user_id']}"}]
        elif t == "active_sub_no_approved_payment":
            text = (f"{who} اشتراک فعال دارد (منبع: پرداخت) ولی هیچ رسید "
                    f"تأییدشده‌ای برایش ثبت نشده — دسترسی بی‌حساب.")
            actions = [{"key": "go", "label": "بررسی مشترک",
                        "go": f"/subscriptions?tab=subscribers&q={i['user_id']}"}]
        elif t == "refunded_but_active_sub":
            text = (f"وجه رسید {who} بازگشت داده شده ولی اشتراک هنوز فعال "
                    f"است — تصمیم: revoke یا نگهداری آگاهانه.")
            actions = [{"key": "go", "label": "مدیریت/revoke اشتراک",
                        "go": f"/subscriptions?tab=subscribers&q={i['user_id']}"}]
        else:
            text = f"رسید {who} بیش از ۷۲ ساعت در انتظار بررسی مانده است."
            actions = [{"key": "go", "label": "بررسی رسید",
                        "go": f"/subscriptions?tab=payments&status=pending&q={i['user_id']}"}]
        out_items.append({
            "type": t, "severity": sev, "label": label,
            "user_id": i["user_id"], "user_name": u.get("name") or "",
            "student_id": u.get("student_id") or "",
            "payment_id": str(p["_id"]) if p.get("_id") else None,
            "amount": amount, "plan_name": p.get("plan_name") or "",
            "at": i["at"], "summary": text, "actions": actions,
            "technical": str(p.get("_id") or ""),
        })
    # 💰 W6 — مغایرت‌های کیف پول: جمله‌ی انسانی، نه OID جارگون
    witems = await db.wallet_reconcile_items()
    if witems:
        wnames = {}
        for u in await db.users.find(
                {"user_id": {"$in": [i["user_id"] for i in witems]}}).to_list(200):
            wnames[int(u["user_id"])] = u.get("name") or ""
        for i in witems:
            who = wnames.get(i["user_id"]) or f"کاربر {i['user_id']}"
            go_wallet = {"key": "go", "label": "بررسی کیف پول",
                         "go": f"/subscriptions?tab=wallets&q={i['user_id']}"}
            t = i["type"]
            if t == "wallet_balance_mismatch":
                label, sev = "مغایرت حسابداری کیف پول", "critical"
                text = (f"موجودی ثبت‌شده‌ی کیف پول {who} "
                        f"({i['balance']:,} تومان) با جمع ledger "
                        f"({i['ledger']:,} تومان) نمی‌خواند — اختلاف "
                        f"{abs(i['amount']):,} تومان.")
                actions = [{"key": "resync",
                            "label": "هم‌ترازسازی با ledger (امن)"},
                           go_wallet]
            elif t == "refund_without_wallet_credit":
                label, sev = "بازگشت وجه بدون اعتبار کیف پول", "critical"
                text = (f"بازگشت وجه {i['amount']:,} تومان برای {who} ثبت "
                        f"شده ولی اعتبار کیف پول ایجاد نشده است.")
                actions = [{"key": "recredit", "label": "اعتبار مجدد کیف پول",
                            "payment_id": i["payment_id"]}, go_wallet]
            elif t == "wallet_debit_without_payment":
                label, sev = "کسر کیف پول بدون پرداخت تأییدشده", "critical"
                text = (f"کسر {i['amount']:,} تومان از کیف پول {who} بدون "
                        f"رسید تأییدشده‌ی متناظر انجام شده است.")
                actions = [go_wallet]
            else:
                label, sev = "تراکنش کیف پول در انتظار", "warning"
                text = (f"تراکنش {i['amount']:,} تومانی کیف پول {who} در "
                        f"حالت معلق مانده است (احتمالاً کرش بین مراحل).")
                actions = [{"key": "resolve_tx",
                            "label": "تعیین تکلیف تراکنش",
                            "tx_id": i.get("tx_id")},
                           go_wallet]
            out_items.append({
                "type": t, "severity": sev, "label": label,
                "user_id": i["user_id"], "user_name": who,
                "student_id": "", "payment_id": i.get("payment_id"),
                "amount": i.get("amount") or 0, "plan_name": "",
                "at": i.get("at"), "summary": text, "actions": actions,
                "technical": i.get("tx_id") or i.get("payment_id") or "",
            })
    # 🌊 W5 — داشبورد مغایرت (§۳۷): چند مورد امروز با اقدام واقعی رفع شده؟
    today = datetime.now(timezone.utc).date().isoformat()
    resolved_today = await db.audit_logs.count_documents({
        "action": {"$regex": "رفع مغایرت مالی"},
        "timestamp": {"$gte": today}})
    return {"items": out_items,
            "summary": {**summary, "total": len(out_items),
                        "resolved_today": resolved_today,
                        "window_days": _w5win,
                        "skipped_stale": _skipped_stale,
                        "checked_at": _now()}}


class WaReconActivateBody(BaseModel):
    confirm: bool = False


@router.post("/subscription/reconcile/{payment_id}/activate")
async def wa_reconcile_activate(payment_id: str, body: WaReconActivateBody,
                                user=Depends(_perm("subscription.manage"))):
    """🌊 W5 — اقدام مغایرت «تأیید بدون اشتراک فعال»: فعال‌سازی امن با همان
    primitive رسمی finalize_approved_payment (plan days از پلن واقعی).
    اتمیک و تأیید صریح؛ اگر اشتراک هم‌زمان فعال شده باشد 409."""
    if not body.confirm:
        raise HTTPException(400, "برای فعال‌سازی، تأیید صریح لازم است")
    payment = await db.sub_payment_get(payment_id)
    if not payment:
        raise HTTPException(404, "رسید پیدا نشد")
    if payment.get("status") != "approved":
        raise HTTPException(409, "فقط رسید تأییدشده قابل فعال‌سازی است")
    uid = int(payment.get("user_id") or 0)
    sub = await db.sub_get(uid)
    if sub and sub.get("status") == "active":
        raise HTTPException(409, "کاربر هم‌اکنون اشتراک فعال دارد؛ مغایرتی نیست")
    try:
        result = await db.finalize_approved_payment(payment, int(user["id"]))
    except ValueError:
        raise HTTPException(422, "مدت پلن این رسید نامعتبر است؛ بررسی دستی لازم است")
    log_id = await _audit(
        int(user["id"]), "رفع مغایرت مالی: فعال‌سازی امن اشتراک",
        severity="CRITICAL", target_type="sub_payment",
        target_id=str(payment["_id"]), target_label=f"رسید کاربر {uid}",
        before={"subscription": (sub or {}).get("status")},
        after={"status": "active", "end_date": result.get("end_date")},
        tags=["مالی", "مغایرت‌گیری"])
    await db.client["medicalbot"]["bot_notifications"].insert_one({
        "type": "event:subscription_active", "chat_id": uid, "sent": False,
        "text": "✅ اشتراک شما فعال شد؛ پایان دوره در پروفایل قابل مشاهده است.",
        "created_at": _now()})
    return {"ok": True, "end_date": result.get("end_date"), "audit_id": log_id}


class WaReconFinalizeTopupBody(BaseModel):
    confirm: bool = False


@router.post("/subscription/reconcile/{payment_id}/finalize-topup")
async def wa_reconcile_finalize_topup(payment_id: str, body: WaReconFinalizeTopupBody,
                                      user=Depends(_perm("subscription.manage"))):
    """🌊 W1 — اقدام مغایرت «شارژ تأییدشده بدون اعتبار»: اجرای idempotent
    دوباره‌ی finalize_approved_payment برای رسید شارژ (همان primitive تأیید).
    اگر اعتبار قبلاً نشسته باشد، اثر دوم ساخته نمی‌شود (already)."""
    if not body.confirm:
        raise HTTPException(400, "برای اعمال اعتبار، تأیید صریح لازم است")
    payment = await db.sub_payment_get(payment_id)
    if not payment:
        raise HTTPException(404, "رسید پیدا نشد")
    if str(payment.get("plan_id") or "") != "wallet_topup":
        raise HTTPException(409, "فقط رسید شارژ کیف پول قابل finalize است")
    if payment.get("status") != "approved":
        raise HTTPException(409, "فقط رسید تأییدشده قابل finalize است")
    uid = int(payment.get("user_id") or 0)
    try:
        result = await db.finalize_approved_payment(payment, int(user["id"]))
    except ValueError:
        raise HTTPException(422, "مبلغ این رسید شارژ نامعتبر است؛ بررسی دستی لازم است")
    log_id = await _audit(
        int(user["id"]), "رفع مغایرت مالی: اعمال اعتبار شارژ",
        severity="CRITICAL", target_type="sub_payment",
        target_id=str(payment["_id"]), target_label=f"رسید شارژ کاربر {uid}",
        before={"topup_credited": False},
        after={"topup_credited": True, "already": bool(result.get("already")),
               "amount": result.get("amount"),
               "balance_after": result.get("balance_after")},
        tags=["مالی", "مغایرت‌گیری"])
    if not result.get("already"):
        await db.client["medicalbot"]["bot_notifications"].insert_one({
            "type": "event:wallet_credit", "chat_id": uid, "sent": False,
            "text": f"💰 مبلغ {int(result.get('amount') or 0):,} تومان به کیف پول شما اضافه شد.",
            "created_at": _now()})
    already = bool(result.get("already"))
    return {"ok": True, "already": already, "already_credited": already,
            "amount": result.get("amount"),
            "balance_after": result.get("balance_after"),
            "tx_id": result.get("tx_id"), "audit_id": log_id}


@router.get("/subscription/finance")
async def wa_subscription_finance(user=Depends(_perm("subscription.manage"))):
    """🌊 W5 — مرکز مالی: aggregate واقعی از sub_payments (نه شمارش فرانت).
    درآمد = فقط رسیدهای تأییدشده؛ بازگشت وجه جدا؛ روند ۱۴ روزه کرانه‌دار."""
    totals = {}
    async for row in db.sub_payments.aggregate([
            {"$group": {"_id": "$status", "count": {"$sum": 1},
                        "total": {"$sum": {"$ifNull": ["$final_price", 0]}}}}]):
        totals[row["_id"] or "unknown"] = {"count": int(row["count"]),
                                           "total": int(row["total"])}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    daily = []
    async for row in db.sub_payments.aggregate([
            {"$match": {"status": "approved",
                        "reviewed_at": {"$gte": cutoff}}},
            {"$group": {"_id": {"$substrCP": ["$reviewed_at", 0, 10]},
                        "total": {"$sum": {"$ifNull": ["$final_price", 0]}}}},
            {"$sort": {"_id": 1}}]):
        daily.append({"day": row["_id"], "total": int(row["total"])})
    refunds = []
    uids = set()
    rdocs = await db.sub_payments.find({"status": "refunded"}).sort(
        "refunded_at", -1).limit(20).to_list(20)
    for p in rdocs:
        uids.add(int(p.get("user_id") or 0))
    names = {}
    if uids:
        for u in await db.users.find({"user_id": {"$in": list(uids)}}).to_list(500):
            names[int(u["user_id"])] = u.get("name") or ""
    for p in rdocs:
        uid = int(p.get("user_id") or 0)
        refunds.append({"payment_id": str(p["_id"]), "user_id": uid,
                        "user_name": names.get(uid, ""),
                        "amount": p.get("final_price", p.get("amount")),
                        "reason": (p.get("refund") or {}).get("reason") or p.get("refund_reason") or "",
                        "at": p.get("refunded_at"),
                        "by": (p.get("refund") or {}).get("by") or p.get("refunded_by")})
    appr = totals.get("approved", {"count": 0, "total": 0})
    rej = totals.get("rejected", {"count": 0, "total": 0})
    ref = totals.get("refunded", {"count": 0, "total": 0})
    decided = appr["count"] + rej["count"]
    week = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()[:10]
    revenue_week = sum(d["total"] for d in daily if d["day"] >= week)
    return {"totals": totals,
            "revenue_total": appr["total"],
            "revenue_week": revenue_week,
            "revenue_refunded": ref["total"],
            "refunded_count": ref["count"],
            "pending_count": totals.get("pending", {"count": 0, "total": 0})["count"],
            "success_rate": round(100.0 * appr["count"] / decided, 1) if decided else None,
            "refund_rate": round(100.0 * ref["count"] / (appr["count"] + ref["count"]), 1)
            if (appr["count"] + ref["count"]) else None,
            "wallet": await db.wallet_stats_global(),
            "daily": daily, "refunds": refunds, "checked_at": _now()}


@router.get("/subscription/payments/{payment_id}/trace")
async def wa_payment_trace(payment_id: str,
                           user=Depends(_perm("subscription.manage"))):
    """🌊 W5 — ردیابی کامل یک رسید (§۱۱): کاربر ← پرداخت ← اشتراک ←
    بازگشت وجه ← خط زمانی حسابرسی. فقط خواندنی و کرانه‌دار."""
    payment = await db.sub_payment_get(payment_id)
    if not payment:
        raise HTTPException(404, "رسید پیدا نشد")
    uid = int(payment.get("user_id") or 0)
    u = await db.users.find_one({"user_id": uid})
    sub = await db.sub_get(uid)
    logs = await db.audit_logs.find({"target.id": str(payment["_id"])}).sort(
        "timestamp", -1).limit(8).to_list(8)
    # 💰 W6 — زنجیره‌ی مالی رسید در کیف پول (refund credit / wallet debit /
    # reversal) تا کل chain در یک نما trace شود
    wtxs = await db.wallet_transactions.find(
        {"reference_id": str(payment["_id"]),
         "reference_type": {"$in": ["sub_payment_refund",
                                    "sub_payment_wallet",
                                    "sub_payment_wallet_reversal"]}}
    ).sort("created_at", -1).to_list(10)
    return {
        "payment": {"id": str(payment["_id"]), "status": payment.get("status"),
                    "plan_name": payment.get("plan_name"),
                    "price": payment.get("price"),
                    "final_price": payment.get("final_price"),
                    "discount_code": payment.get("discount_code"),
                    "submitted_at": payment.get("submitted_at"),
                    "reviewed_at": payment.get("reviewed_at"),
                    "review_note": payment.get("review_note")},
        "user": {"user_id": uid, "name": (u or {}).get("name") or "",
                 "student_id": (u or {}).get("student_id") or "",
                 "username": (u or {}).get("username") or ""} if u else None,
        "subscription": {"status": sub.get("status"), "plan_name": sub.get("plan_name"),
                         "start_date": sub.get("start_date"),
                         "end_date": sub.get("end_date"),
                         "source": sub.get("source")} if sub else None,
        "refund": {"reason": payment.get("refund_reason") or
                   (payment.get("refund") or {}).get("reason"),
                   "at": payment.get("refunded_at"),
                   "by": (payment.get("refund") or {}).get("by")}
        if payment.get("status") == "refunded" else None,
        "gift": payment.get("gift"),
        "wallet_txs": [{"id": str(t["_id"]), "type": t.get("type"),
                        "direction": t.get("direction"),
                        "amount": int(t.get("amount") or 0),
                        "label": t.get("label"), "status": t.get("status"),
                        "balance_after": t.get("balance_after"),
                        "at": t.get("created_at")} for t in wtxs],
        "audit": [{"id": str(l["_id"]), "at": l.get("timestamp"),
                   "actor_name": (l.get("actor") or {}).get("name", ""),
                   "action": l.get("action", ""), "severity": l.get("severity")}
                  for l in logs],
    }


@router.get("/exports/payments.csv")
async def wa_export_payments_csv(status: str = Query("", max_length=20),
                                 user=Depends(_perm("subscription.manage"))):
    """🌊 W5 — خروجی CSV کرانه‌دار رسیدها (حداکثر ۲۰۰ سطر) با header انسانی."""
    flt = {"status": status} if status else {}
    rows = await db.sub_payments.find(flt).sort("submitted_at", -1).limit(2000).to_list(2000)
    uids = {int(p.get("user_id") or 0) for p in rows}
    names = {}
    if uids:
        for u in await db.users.find({"user_id": {"$in": list(uids)}}).to_list(2000):
            names[int(u["user_id"])] = u.get("name") or ""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["شناسه", "کاربر", "شماره تلگرام", "پلن", "مبلغ پایه", "مبلغ نهایی",
                "کد تخفیف", "وضعیت", "ثبت", "بررسی", "بازگشت وجه"])
    for p in rows:
        uid = int(p.get("user_id") or 0)
        w.writerow([str(p["_id"]), names.get(uid, ""), uid, p.get("plan_name") or "",
                    p.get("price") or "", p.get("final_price") or "",
                    p.get("discount_code") or "", p.get("status") or "",
                    p.get("submitted_at") or "", p.get("reviewed_at") or "",
                    p.get("refunded_at") or ""])
    log_id = await _audit(int(user["id"]), "خروجی CSV رسیدها",
                          severity="INFO", target_type="export",
                          target_id=f"payments:{status or 'all'}",
                          after={"rows": len(rows)}, tags=["مالی", "خروجی"])
    return Response(
        "\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=humsyar-payments.csv",
                 "X-Audit-Id": str(log_id)})


@router.get("/exports/wallet.csv")
async def wa_export_wallet_csv(user_id: int = Query(0),
                               user=Depends(_perm("subscription.manage"))):
    """🌊 W1 — خروجی CSV کرانه‌دار دفترکل کیف پول (حداکثر ۲۰۰۰ سطر آخر).
    user_id اختیاری: فقط تراکنش‌های همان کاربر."""
    flt = {"user_id": int(user_id)} if int(user_id or 0) else {}
    rows = await db.wallet_transactions.find(flt).sort("_id", -1).limit(2000).to_list(2000)
    uids = {int(t.get("user_id") or 0) for t in rows}
    names = {}
    if uids:
        for u in await db.users.find({"user_id": {"$in": list(uids)}}).to_list(2000):
            names[int(u["user_id"])] = u.get("name") or ""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["شناسه", "کاربر", "شماره تلگرام", "نوع", "جهت", "مبلغ (تومان)",
                "موجودی پس‌از", "نوع مرجع", "شناسه مرجع", "ثبت‌کننده", "تاریخ"])
    for t in rows:
        uid = int(t.get("user_id") or 0)
        w.writerow([str(t.get("_id")), names.get(uid, ""), uid,
                    t.get("label") or t.get("type") or "",
                    t.get("direction") or "",
                    t.get("amount") if t.get("amount") is not None else "",
                    t.get("balance_after") if t.get("balance_after") is not None else "",
                    t.get("reference_type") or "", t.get("reference_id") or "",
                    t.get("actor_id") if t.get("actor_id") is not None else t.get("actor") or "",
                    t.get("at") or t.get("created_at") or ""])
    log_id = await _audit(int(user["id"]), "خروجی CSV دفترکل کیف پول",
                          severity="INFO", target_type="export",
                          target_id=f"wallet:{user_id or 'all'}",
                          after={"rows": len(rows)}, tags=["مالی", "خروجی"])
    return Response(
        "\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=humsyar-wallet.csv",
                 "X-Audit-Id": str(log_id)})


# ── 💰 W6 — مدیریت کیف پول‌ها ──────────────────────────────────
class WaWalletAdjustBody(BaseModel):
    amount: int = Field(..., description="مبلغ به تومان؛ مثبت=افزایش، منفی=کسر")
    reason: str = Field(..., min_length=3, max_length=200)
    confirm: bool = False


class WaRecreditBody(BaseModel):
    payment_id: str
    confirm: bool = False


class WaWalletResyncBody(BaseModel):
    confirm: bool = False


class WaTxResolveBody(BaseModel):
    action: str = Field(..., description="complete یا cancel")
    confirm: bool = False


@router.get("/wallets")
async def wa_wallets(skip: int = Query(0, ge=0),
                     limit: int = Query(30, ge=1, le=100),
                     q: str = Query("", max_length=80),
                     user=Depends(_perm("subscription.manage"))):
    """💰 W6 — لیست کیف پول‌ها با نام/موجودی (جست‌وجو: uid/نام/شماره دانشجویی)."""
    flt = {}
    if q.strip():
        qq = q.strip()
        ors = []
        if qq.isdigit():
            ors.append({"user_id": int(qq)})
        ors += [{"name": {"$regex": re.escape(qq), "$options": "i"}},
                {"student_id": {"$regex": re.escape(qq), "$options": "i"}}]
        uids = [int(u["user_id"]) for u in await db.users.find(
            {"$or": ors}, {"user_id": 1}).limit(500)]
        flt = {"user_id": {"$in": uids}} if uids else {"user_id": -1}
    total = await db.wallets.count_documents(flt)
    docs = await db.wallets.find(flt).sort("balance", -1).skip(skip).limit(limit).to_list(limit)
    users = {}
    if docs:
        for u in await db.users.find(
                {"user_id": {"$in": [d["user_id"] for d in docs]}}).to_list(500):
            users[int(u["user_id"])] = u
    return {"total": total, "items": [{
        "user_id": d["user_id"],
        "user_name": (users.get(d["user_id"]) or {}).get("name") or "",
        "student_id": (users.get(d["user_id"]) or {}).get("student_id") or "",
        "balance": int(d.get("balance", 0)),
        "currency": d.get("currency") or "تومان",
        "updated_at": d.get("updated_at"),
    } for d in docs]}


@router.get("/wallets/{uid}")
async def wa_wallet_detail(uid: int,
                           skip: int = Query(0, ge=0),
                           limit: int = Query(20, ge=1, le=50),
                           user=Depends(_perm("subscription.manage"))):
    """💰 W6 — جزئیات کیف پول: موجودی + آمار + تاریخچه صفحه‌بندی‌شده.
    تراکنش‌ها human-readable (label فارسی) و IDها فقط فنی."""
    u = await db.users.find_one({"user_id": uid})
    summary = await db.wallet_summary(uid)
    txs = await db.wallet_tx_list(uid, skip=skip, limit=limit)
    # 🌊 W6.1 — تراکنش‌های معلق (کرش) در صفحه‌ی اول دیده می‌شوند تا ادمین
    # بتواند همان‌جا تعیین تکلیف کند؛ در ledger کاربر شمارش نمی‌شوند.
    pend = []
    if skip == 0:
        pend = await db.wallet_transactions.find(
            {"user_id": uid, "status": "pending"}
        ).sort([("created_at", -1), ("_id", -1)]).to_list(10)
    txs = list(pend) + list(txs)
    return {"summary": {**summary,
                        "user_name": (u or {}).get("name") or "",
                        "student_id": (u or {}).get("student_id") or ""},
            "transactions": [{
                "id": str(t["_id"]), "type": t.get("type"),
                "direction": t.get("direction"), "amount": int(t.get("amount") or 0),
                "label": t.get("label"), "status": t.get("status"),
                "balance_before": t.get("balance_before"),
                "balance_after": t.get("balance_after"),
                "reference_type": t.get("reference_type"),
                "reference_id": t.get("reference_id"),
                "actor_id": t.get("actor_id"), "at": t.get("created_at"),
            } for t in txs],
            "tx_total": await db.wallet_tx_count(uid)}


@router.post("/wallets/{uid}/adjust")
async def wa_wallet_adjust(uid: int, body: WaWalletAdjustBody,
                           user=Depends(_perm("subscription.manage"))):
    """💰 W6 — تنظیم دستی موجودی: فقط با دلیل + تأیید صریح + audit بحرانی.
    هیچ تنظیم بی‌صدایی وجود ندارد؛ کسر با موجودی ناکافی ۴۰۰ می‌گیرد."""
    if not body.confirm:
        raise HTTPException(400, "تنظیم دستی بدون تأیید صریح ممکن نیست")
    amount = int(body.amount)
    if amount == 0 or abs(amount) > 50_000_000:
        raise HTTPException(400, "مبلغ نامعتبر است")
    u = await db.users.find_one({"user_id": uid})
    if not u:
        raise HTTPException(404, "کاربر پیدا نشد")
    token = secrets.token_hex(8)
    try:
        if amount > 0:
            tx = await db.wallet_credit(
                uid, amount, "admin_credit", "admin_adjustment", token,
                int(user["id"]), f"افزایش دستی — {body.reason}")
        else:
            tx = await db.wallet_debit(
                uid, -amount, "admin_debit", "admin_adjustment", token,
                int(user["id"]), f"کسر دستی — {body.reason}")
    except Exception as e:
        code = getattr(e, "code", "")
        if code == "insufficient_balance":
            raise HTTPException(400, "موجودی کیف پول برای این کسر کافی نیست")
        # 🛡 W3/SEC-02 — سقف روزانه به‌جای ۵۰۰ خام، پاسخ معنادار می‌دهد
        if code == "daily_limit_exceeded":
            raise HTTPException(429, str(e) or "سقف روزانه کیف پول")
        if code == "daily_limit_unavailable":
            raise HTTPException(
                503, "سامانه سقف روزانه موقتاً در دسترس نیست؛ "
                     "لطفاً دقایقی دیگر تلاش کنید")
        raise
    log_id = await _audit(
        int(user["id"]), "تنظیم دستی کیف پول", severity="CRITICAL",
        target_type="wallet", target_id=str(uid),
        target_label=(u.get("name") or f"کاربر {uid}"),
        before={"balance": int(tx.get("balance_before") or 0)},
        after={"balance": tx.get("balance_after"), "amount": amount,
               "reason": body.reason, "tx_id": str(tx["_id"])},
        tags=["مالی", "کیف_پول", "تنظیم_دستی"])
    await db.client["medicalbot"]["bot_notifications"].insert_one({
        "type": "event:wallet", "chat_id": uid, "sent": False,
        "text": (f"{'➕' if amount > 0 else '➖'} {'افزایش' if amount > 0 else 'کسر'} "
                 f"{abs(amount):,} تومان در کیف پول شما — {body.reason}"),
        "created_at": _now()})
    return {"ok": True, "tx_id": str(tx["_id"]),
            "balance_after": tx.get("balance_after"), "audit_id": log_id}


@router.post("/wallets/{uid}/resync")
async def wa_wallet_resync(uid: int, body: WaWalletResyncBody,
                           user=Depends(_perm("subscription.manage"))):
    """💰 W6 — هم‌ترازسازی موجودی کش با ledger (§۹۰ repair امن):
    ledger منبع حقیقت است؛ موجودی کش فقط بهینه‌سازی. اگر جمع ledger منفی
    شود یعنی خودِ ledger ناهنجار است — آن حالت هرگز خودکار «اصلاح»
    نمی‌شود و برای بررسی انسانی پرچم می‌ماند."""
    if not body.confirm:
        raise HTTPException(400, "هم‌ترازسازی بدون تأیید صریح ممکن نیست")
    w = await db.wallets.find_one({"user_id": uid})
    if not w:
        raise HTTPException(404, "کیف پول پیدا نشد")
    # 🌊 W6.1 — تا تراکنش معلقی تعیین‌تکلیف نشده، هم‌ترازسازی ممنوع:
    # وگرنه جمع ledgerِ ok بدون اثرِ در راه محاسبه و موجودی خراب می‌شود.
    if await db.wallet_pending_count(uid):
        raise HTTPException(
            409, "این کیف پول تراکنش معلق دارد؛ ابتدا آن را تعیین تکلیف "
                 "کنید (کامل یا لغو)، سپس هم‌ترازسازی ممکن است")
    ledger = 0
    async for row in db.wallet_transactions.aggregate([
            {"$match": {"user_id": uid, "status": "ok"}},
            {"$group": {"_id": None, "s": {"$sum": {"$cond": [
                {"$eq": ["$direction", "credit"]},
                "$amount", {"$multiply": ["$amount", -1]}]}}}}]):
        ledger = int(row["s"])
    if ledger < 0:
        raise HTTPException(
            409, "جمع ledger منفی است — تراکنش‌ها ناهنجارند؛ "
                 "اصلاح خودکار انجام نشد و مورد نیازمند بررسی دستی است")
    before = int(w.get("balance", 0))
    await db.wallets.update_one(
        {"user_id": uid},
        {"$set": {"balance": ledger, "updated_at": _now()}})
    log_id = await _audit(
        int(user["id"]), "هم‌ترازسازی موجودی کیف پول با ledger",
        severity="CRITICAL", target_type="wallet", target_id=str(uid),
        target_label=f"کیف پول کاربر {uid}",
        before={"balance": before}, after={"balance": ledger},
        tags=["مالی", "کیف_پول", "مغایرت"])
    return {"ok": True, "balance": ledger, "audit_id": log_id}


@router.post("/wallet-tx/{tx_id}/resolve")
async def wa_wallet_tx_resolve(tx_id: str, body: WaTxResolveBody,
                               user=Depends(_perm("subscription.manage"))):
    """🌊 W6.1 — تعیین تکلیف تراکنش معلق (کرش بین مراحل ledger):
    تشخیص اینکه اثر مالی اعمال شده یا نه در لایه‌ی db و evidence-based
    است؛ اینجا فقط گیت مجوز + تأیید صریح + audit بحرانی اضافه می‌شود."""
    if not body.confirm:
        raise HTTPException(400, "تعیین تکلیف بدون تأیید صریح ممکن نیست")
    try:
        res = await db.wallet_resolve_pending(tx_id, int(user["id"]),
                                              body.action)
    except Exception as e:
        code = getattr(e, "code", "")
        if code == "tx_not_found":
            raise HTTPException(404, str(e))
        if code == "tx_not_pending":
            raise HTTPException(409, str(e))
        if code == "bad_action":
            raise HTTPException(400, str(e))
        if code == "insufficient_balance":
            raise HTTPException(400, "اعمال کسر ممکن نیست — موجودی کافی نیست")
        if code == "cancel_would_overdraw":
            raise HTTPException(409, str(e))
        raise
    log_id = await _audit(
        int(user["id"]), "تعیین تکلیف تراکنش معلق کیف پول",
        severity="CRITICAL", target_type="wallet_tx", target_id=tx_id,
        target_label=f"تراکنش کیف پول",
        before={"status": "pending"},
        after={**res},
        tags=["مالی", "کیف_پول", "کرش_ریکاوری"])
    return {**res, "audit_id": log_id}


@router.post("/subscription/reconcile/wallet-recredit")
async def wa_wallet_recredit(body: WaRecreditBody,
                             user=Depends(_perm("subscription.manage"))):
    """💰 W6 — اقدام امن روی مغایرت «بازگشت وجه بدون اعتبار کیف پول»:
    اعتبار مجدد **idempotent** (کلید = همان sub_payment_refund/payment_id)؛
    دوبار اجرا = یک اثر اقتصادی. این یک repair مالی است: audit بحرانی."""
    if not body.confirm:
        raise HTTPException(400, "این اقدام مالی بدون تأیید صریح ممکن نیست")
    payment = await db.sub_payment_get(body.payment_id)
    if not payment or payment.get("status") != "refunded":
        raise HTTPException(409, "فقط رسید بازگشت‌وجه‌شده قابل اعتبار مجدد است")
    uid = int(payment.get("user_id") or 0)
    amount = int(payment.get("final_price") or payment.get("amount") or 0)
    if amount <= 0:
        raise HTTPException(409, "مبلغ معتبری برای اعتبار یافت نشد")
    tx = await db.wallet_credit(
        uid, amount, "refund_credit", "sub_payment_refund",
        str(payment["_id"]), int(user["id"]),
        f"بازگشت وجه (اعتبار مجدد مغایرت) — {payment.get('plan_name') or 'اشتراک'}")
    log_id = await _audit(
        int(user["id"]), "رفع مغایرت مالی — اعتبار مجدد کیف پول",
        severity="CRITICAL", target_type="sub_payment",
        target_id=body.payment_id, target_label=f"رسید کاربر {uid}",
        before={"wallet_credited": False},
        after={"wallet_credited": True, "amount": amount,
               "tx_id": str(tx["_id"]),
               "already_credited": tx.get("balance_after") is None},
        tags=["مالی", "مغایرت", "کیف_پول"])
    return {"ok": True, "tx_id": str(tx["_id"]),
            "balance_after": tx.get("balance_after"), "audit_id": log_id}


@router.get("/subscription/subscribers")
async def wa_subscription_subscribers(
    status: str = Query("active"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None),
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.subscribers(
        status=status, skip=skip, limit=limit, search=search, admin=user)


@router.get("/subscription/subscribers/{user_id}")
async def wa_subscription_subscriber_detail(
    user_id: int,
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.subscriber_detail(user_id=user_id, admin=user)


@router.get("/subscription/users/search")
async def wa_subscription_user_search(
    q: str = Query("", max_length=80),
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.search_users_for_grant(q=q, admin=user)


@router.post("/subscription/subscribers/grant")
async def wa_subscription_grant(
    body: subscription_api.GrantBody,
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.grant_subscription(body=body, admin=user)


@router.post("/subscription/subscribers/grant-bulk")
async def wa_subscription_grant_bulk(
    body: subscription_api.BulkGrantBody,
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.grant_subscription_bulk(body=body, admin=user)


@router.post("/subscription/subscribers/{user_id}/revoke")
async def wa_subscription_revoke(
    user_id: int,
    body: subscription_api.RevokeBody,
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.revoke_subscription(
        user_id=user_id, body=body, admin=user)


@router.post("/subscription/discounts")
async def wa_subscription_discount_add(
    body: subscription_api.DiscountBody,
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.add_discount(body=body, admin=user)


@router.post("/subscription/discounts/{code}/toggle")
async def wa_subscription_discount_toggle(
    code: str,
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.toggle_discount(code=code, admin=user)


@router.delete("/subscription/discounts/{code}")
async def wa_subscription_discount_delete(
    code: str,
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.delete_discount(code=code, admin=user)


@router.post("/subscription/discounts/{code}/preview")
async def wa_subscription_discount_preview(
    code: str,
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.preview_discount_campaign(code=code, admin=user)


@router.post("/subscription/discounts/{code}/broadcast")
async def wa_subscription_discount_broadcast(
    code: str,
    body: subscription_api.DiscountBroadcastBody,
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.start_discount_broadcast(code=code, body=body, admin=user)


@router.get("/subscription/discounts/{code}/broadcast/{bid}")
async def wa_subscription_discount_broadcast_status(
    code: str, bid: str,
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.discount_broadcast_status(code=code, bid=bid, admin=user)


@router.post("/subscription/discounts/{code}/broadcast/{bid}/cancel")
async def wa_subscription_discount_broadcast_cancel(
    code: str, bid: str,
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.cancel_discount_broadcast(code=code, bid=bid, admin=user)


@router.get("/subscription/discounts/{code}/broadcasts")
async def wa_subscription_discount_broadcasts(
    code: str,
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.discount_broadcasts_list(code=code, admin=user)


@router.get("/subscription/discounts/{code}/stats")
async def wa_subscription_discount_stats(
    code: str,
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.discount_stats(code=code, admin=user)


@router.put("/subscription/card")
async def wa_subscription_card(
    body: subscription_api.CardBody,
    user=Depends(_perm("subscription.manage")),
):
    return await subscription_api.update_card(body=body, admin=user)


# ── AI Admin ───────────────────────────────────────────────────────

class WaAiConfigUpdate(BaseModel):
    """پیکربندی غیرsecret؛ extra=forbid مانع عبور دستی api_key می‌شود."""
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    provider: str = Field(
        pattern="^(gemini|openrouter|groq|cerebras|mistral|deepseek)$")
    model: str = Field(min_length=2, max_length=150)
    daily_limit: int = Field(ge=0, le=1000)
    thinking: str = Field(pattern="^(auto|high)$")
    system_prompt: str = Field(min_length=20, max_length=20000)
    disabled_message: str = Field(default="", max_length=1000)


class WaAiKeyRotate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: str = Field(min_length=8, max_length=500)


class WaAiPersonaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)
    prompt: Optional[str] = Field(default=None, min_length=20, max_length=20000)


class WaAiDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notes: str = Field(min_length=3, max_length=2000)


@router.get("/ai/models")
async def wa_ai_models(user=Depends(_perm("ai.manage"))):
    """🌊 W9 — کاتالوگ مرکزی مدل‌ها برای selectهای پنل وب."""
    return await ai_admin_api.models_catalog(admin=user)


@router.get("/ai/config")
async def wa_ai_config(user=Depends(_perm("ai.manage"))):
    return await ai_admin_api.config(admin=user)


@router.put("/ai/config")
async def wa_ai_config_update(
    body: WaAiConfigUpdate,
    user=Depends(_perm("ai.manage")),
):
    before = await ai_admin_api.config(admin=user)
    safe_body = ai_admin_api.ConfigUpdate(**body.model_dump(), api_key=None)
    result = await ai_admin_api.update_config(body=safe_body, admin=user)
    after = await ai_admin_api.config(admin=user)
    try:
        await _audit(user["id"], "به‌روزرسانی تنظیمات هوشیار", severity="HIGH",
                     before={k: before.get(k) for k in ("enabled", "provider", "model", "daily_limit", "thinking", "system_prompt", "disabled_message")},
                     after={k: after.get(k) for k in ("enabled", "provider", "model", "daily_limit", "thinking", "system_prompt", "disabled_message")},
                     tags=["هوشیار", "پیکربندی", "پنل_وب"])
    except Exception:
        rollback = ai_admin_api.ConfigUpdate(
            enabled=before["enabled"], provider=before["provider"], model=before["model"],
            daily_limit=before["daily_limit"], thinking=before["thinking"],
            system_prompt=before["system_prompt"],
            disabled_message=before.get("disabled_message") or "", api_key=None)
        await ai_admin_api.update_config(body=rollback, admin=user)
        raise HTTPException(503, "ثبت حسابرسی ناموفق بود؛ پیکربندی قبلی بازگردانده شد")
    return result


@router.post("/ai/api-key/rotate")
async def wa_ai_api_key_rotate(body: WaAiKeyRotate,
                               user=Depends(_perm("ai.manage"))):
    """چرخش secret فقط مالک؛ مقدار هرگز response/audit نمی‌شود. Vault-aware: کلید برای provider فعلی در vault ذخیره می‌شود."""
    secret = body.api_key.strip()
    if len(secret) < 8:
        raise HTTPException(422, "کلید API معتبر نیست")
    cfg = await ai_admin_api.get_ai_config()
    provider = cfg.get("provider") or "gemini"
    old_secret = cfg.get("api_key") or ""
    before_configured = bool(old_secret)
    # ذخیره در vault برای provider فعلی + legacy برای سازگاری
    await ai_admin_api.set_api_key_for_provider(provider, secret)
    await ai_admin_api.set_ai_setting("api_key", secret)
    try:
        await _audit(user["id"], "AI API key rotated", severity="CRITICAL",
                     target_type="ai_secret", target_label=f"Houshyar API key ({provider})",
                     before={"configured": before_configured, "provider": provider},
                     after={"configured": True, "provider": provider},
                     tags=["هوشیار", "secret_rotation", "owner_only", "پنل_وب"])
    except Exception:
        await ai_admin_api.set_api_key_for_provider(provider, old_secret)
        await ai_admin_api.set_ai_setting("api_key", old_secret)
        raise HTTPException(503, "ثبت حسابرسی ناموفق بود؛ کلید قبلی بازگردانده شد")
    return {"ok": True, "has_api_key": True, "provider": provider}


@router.post("/ai/test")
async def wa_ai_test(user=Depends(_perm("ai.manage"))):
    started = time.perf_counter()
    result = await ai_admin_api.test_connection(admin=user)
    result["response_time_ms"] = round((time.perf_counter() - started) * 1000, 1)
    result["request_id"] = current_request_id.get()
    await _audit(user["id"], "آزمایش اتصال هوشیار", severity="INFO",
                 target_type="ai_provider", target_label="connection test",
                 after={"ok": bool(result.get("ok")), "tokens": int(result.get("tokens") or 0)},
                 tags=["هوشیار", "connection_test", "owner_only", "پنل_وب"])
    return result


@router.get("/ai/users/{user_id}/profile")
async def wa_ai_user_profile(user_id: int, user=Depends(_perm("ai.manage"))):
    target = await db.get_user(user_id)
    if not target:
        raise HTTPException(404, "کاربر پیدا نشد")
    notes = await db.ai_get_profile_notes(user_id)
    return {"user": {"id": user_id, "name": target.get("name", "")},
            "notes": [str(note)[:500] for note in notes[:50]],
            "note_count": len(notes),
            "legacy_memory_present": bool(target.get("ai_mem")),
            "scope": "profile_notes_and_legacy_memory_only"}


@router.delete("/ai/users/{user_id}/profile")
async def wa_ai_user_profile_clear(user_id: int, user=Depends(_perm("ai.manage"))):
    target = await db.get_user(user_id)
    if not target:
        raise HTTPException(404, "کاربر پیدا نشد")
    before = {"profile_notes": len(target.get("ai_profile_notes") or []),
              "legacy_memory_present": bool(target.get("ai_mem"))}
    result = await ai_admin_api.clear_profile(user_id=user_id, admin=user)
    try:
        await _audit(user["id"], "پاک‌سازی پروفایل ماندگار هوشیار", severity="HIGH",
                     target_id=user_id, target_type="user", target_label=target.get("name", ""),
                     before=before,
                     after={"profile_notes": 0, "legacy_memory_present": False},
                     tags=["هوشیار", "privacy", "owner_only", "پنل_وب"])
    except Exception:
        restore = {k: target[k] for k in ("ai_profile_notes", "ai_mem", "ai_mem_at") if k in target}
        if restore:
            await db.users.update_one({"user_id": user_id}, {"$set": restore})
        raise HTTPException(503, "ثبت حسابرسی ناموفق بود؛ داده پاک‌شده بازگردانده شد")
    return {**result, "cleared": "profile_notes_and_legacy_memory_only"}


@router.get("/ai/personas")
async def wa_ai_personas(user=Depends(_perm("ai.manage"))):
    cfg = await ai_admin_api.get_ai_config()
    meta_raw = await db.get_setting("ai_personas_meta", {})
    meta = meta_raw if isinstance(meta_raw, dict) else {}
    current = cfg.get("system_prompt") or ""
    return {"personas": [{"name": str(name), "prompt": str(prompt),
                           "active": str(prompt) == current,
                           "created_by": (meta.get(name) or {}).get("created_by"),
                           "created_at": (meta.get(name) or {}).get("created_at", "")}
                          for name, prompt in (cfg.get("personas") or {}).items()]}


@router.post("/ai/personas")
async def wa_ai_persona_create(body: WaAiPersonaCreate, user=Depends(_perm("ai.manage"))):
    cfg = await ai_admin_api.get_ai_config()
    name = body.name.strip()
    prompt = (body.prompt or cfg.get("system_prompt") or "").strip()
    if len(prompt) < 20:
        raise HTTPException(422, "متن persona حداقل ۲۰ کاراکتر باشد")
    old_prompt = (cfg.get("personas") or {}).get(name)
    existed = old_prompt is not None
    meta_raw = await db.get_setting("ai_personas_meta", {})
    old_meta = dict(meta_raw) if isinstance(meta_raw, dict) else {}
    await save_persona(name, prompt)
    meta = dict(old_meta)
    meta[name] = {"created_by": user["id"], "created_at": _now()}
    await db.set_setting("ai_personas_meta", meta)
    try:
        await _audit(user["id"], "ذخیره persona هوشیار", severity="WARNING",
                     target_type="ai_persona", target_label=name,
                     before={"exists": existed}, after={"exists": True},
                     tags=["هوشیار", "persona", "owner_only", "پنل_وب"])
    except Exception:
        if existed: await save_persona(name, old_prompt)
        else: await delete_persona(name)
        await db.set_setting("ai_personas_meta", old_meta)
        raise HTTPException(503, "ثبت حسابرسی ناموفق بود؛ تغییر Persona بازگردانده شد")
    return {"ok": True, "name": name}


@router.post("/ai/personas/{name}/activate")
async def wa_ai_persona_activate(name: str, user=Depends(_perm("ai.manage"))):
    cfg = await ai_admin_api.get_ai_config()
    prompt = (cfg.get("personas") or {}).get(name)
    if not prompt:
        raise HTTPException(404, "Persona پیدا نشد")
    old = cfg.get("system_prompt") or ""
    await ai_admin_api.set_ai_setting("system_prompt", prompt)
    try:
        await _audit(user["id"], "فعال‌سازی persona هوشیار", severity="HIGH",
                     target_type="ai_persona", target_label=name,
                     before={"system_prompt": old}, after={"system_prompt": prompt},
                     tags=["هوشیار", "persona", "owner_only", "پنل_وب"])
    except Exception:
        await ai_admin_api.set_ai_setting("system_prompt", old)
        raise HTTPException(503, "ثبت حسابرسی ناموفق بود؛ Persona قبلی فعال ماند")
    return {"ok": True, "name": name}


@router.delete("/ai/personas/{name}")
async def wa_ai_persona_delete(name: str, user=Depends(_perm("ai.manage"))):
    cfg = await ai_admin_api.get_ai_config()
    old_prompt = (cfg.get("personas") or {}).get(name)
    if old_prompt is None:
        raise HTTPException(404, "Persona پیدا نشد")
    meta_raw = await db.get_setting("ai_personas_meta", {})
    old_meta = dict(meta_raw) if isinstance(meta_raw, dict) else {}
    await delete_persona(name)
    if name in old_meta:
        meta = dict(old_meta); meta.pop(name, None)
        await db.set_setting("ai_personas_meta", meta)
    try:
        await _audit(user["id"], "حذف persona هوشیار", severity="HIGH",
                     target_type="ai_persona", target_label=name,
                     before={"exists": True}, after={"deleted": True},
                     tags=["هوشیار", "persona", "owner_only", "پنل_وب"])
    except Exception:
        await save_persona(name, old_prompt)
        await db.set_setting("ai_personas_meta", old_meta)
        raise HTTPException(503, "ثبت حسابرسی ناموفق بود؛ Persona بازگردانده شد")
    return {"ok": True}


@router.post("/ai/broadcast-draft")
async def wa_ai_broadcast_draft(body: WaAiDraft,
                                user=Depends(_perm("broadcast.send"))):
    try:
        draft = await generate_broadcast_ai(body.notes.strip())
    except Exception:
        raise HTTPException(503, "هوشیار نتوانست پیش‌نویس بسازد؛ نوشتن دستی همچنان در دسترس است")
    return {"draft": draft, "request_id": current_request_id.get()}


@router.get("/ai/stats")
async def wa_ai_stats(user=Depends(_perm("ai.manage"))):
    return await ai_admin_api.stats(admin=user)


def _ai_report_query(q: str | None = None, user_id: int | None = None,
                     date_from: str | None = None, date_to: str | None = None) -> dict:
    filt = {}
    if q:
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        filt["$or"] = [{"name": rx}, {"question": rx}, {"answer": rx}]
    if user_id is not None:
        filt["user_id"] = user_id
    created = {}
    if date_from:
        try: created["$gte"] = day_bounds_utc(parse_gregorian_date(date_from))[0]
        except ValueError: raise HTTPException(422, "تاریخ شروع نامعتبر است")
    if date_to:
        try: created["$lt"] = day_bounds_utc(parse_gregorian_date(date_to))[1]
        except ValueError: raise HTTPException(422, "تاریخ پایان نامعتبر است")
    if created: filt["created_at"] = created
    return filt


def _ai_report_row(item: dict) -> dict:
    at = item.get("created_at")
    return {"id": str(item.get("_id", "")), "user_id": item.get("user_id"),
            "name": str(item.get("name") or ""),
            "question": str(item.get("question") or ""),
            "answer": str(item.get("answer") or ""),
            "created_at": at.isoformat() if isinstance(at, datetime) else (at or None)}


@router.get("/ai/reports")
async def wa_ai_reports(
    q: Optional[str] = Query(None, max_length=100), user_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    skip: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100),
    user=Depends(_perm("ai.manage")),
):
    filt = _ai_report_query(q, user_id, date_from, date_to)
    total, docs = await asyncio.gather(
        db.ai_reports.count_documents(filt),
        db.ai_reports.find(filt).sort("created_at", -1 if sort_dir == "desc" else 1)
          .skip(skip).limit(limit).to_list(limit),
    )
    return {"reports": [_ai_report_row(item) for item in docs], "total": total,
            "skip": skip, "limit": limit}


@router.get("/exports/ai-reports.csv")
async def wa_ai_reports_export(
    q: Optional[str] = Query(None, max_length=100), user_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"), human: bool = False,
    user=Depends(_perm("ai.manage")),
):
    filt = _ai_report_query(q, user_id, date_from, date_to)
    async def stream():
        yield "\ufeffid,user_id,name,question,answer,created_at\r\n".encode("utf-8")
        cursor = db.ai_reports.find(filt).sort("created_at", -1 if sort_dir == "desc" else 1)
        async for item in cursor:
            row = _ai_report_row(item); buf = io.StringIO(); writer = csv.writer(buf)
            writer.writerow([row["id"], row["user_id"], row["name"], row["question"], row["answer"], _export_instant(row["created_at"], human)])
            yield buf.getvalue().encode("utf-8")
    return StreamingResponse(stream(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=humsyar-ai-reports.csv"})


@router.get("/ai/banned")
async def wa_ai_banned(
    q: Optional[str] = Query(None, max_length=100),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    skip: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100),
    user=Depends(_perm("ai.manage")),
):
    filt = {"ai_banned": True}
    if q:
        search = db.build_user_search_query(q.strip())
        filt = {"$and": [filt, search]}
    total, docs = await asyncio.gather(
        db.users.count_documents(filt),
        db.users.find(filt, {"user_id": 1, "name": 1, "nickname": 1,
                             "username": 1, "ai_total_usage": 1})
          .sort("name", 1 if sort_dir == "asc" else -1).skip(skip).limit(limit).to_list(limit),
    )
    return {"users": [{"id": item.get("user_id"),
                        "name": db.display_name_of(item),
                        "username": item.get("username", ""),
                        "usage_total": int(item.get("ai_total_usage") or 0)} for item in docs],
            "total": total, "skip": skip, "limit": limit}


@router.get("/ai/users")
async def wa_ai_users(
    q: str = Query(..., min_length=2, max_length=100),
    user=Depends(_perm("ai.manage")),
):
    return await ai_admin_api.users(q=q, admin=user)


@router.post("/ai/users/ban")
async def wa_ai_ban(
    body: ai_admin_api.UserAction,
    user=Depends(_perm("ai.manage")),
):
    target = await db.get_user(body.user_id)
    result = await ai_admin_api.toggle_ban(body=body, admin=user)
    try:
        await _audit(user["id"], "تغییر دسترسی کاربر به هوشیار", severity="HIGH",
                     target_id=body.user_id, target_type="user",
                     target_label=(target or {}).get("name", str(body.user_id)),
                     before={"مسدود": bool((target or {}).get("ai_banned"))},
                     after={"مسدود": bool(result.get("banned"))},
                     tags=["هوشیار", "دسترسی", "پنل_وب"])
    except Exception:
        await db.ai_set_banned(body.user_id, bool((target or {}).get("ai_banned")))
        raise HTTPException(503, "ثبت حسابرسی ناموفق بود؛ دسترسی قبلی بازگردانده شد")
    return result


@router.post("/ai/users/reset-quota")
async def wa_ai_reset_quota(
    body: ai_admin_api.UserAction,
    user=Depends(_perm("ai.manage")),
):
    target = await db.get_user(body.user_id)
    result = await ai_admin_api.reset_quota(body=body, admin=user)
    try:
        await _audit(user["id"], "صفرکردن سهمیه روزانه هوشیار", severity="WARNING",
                     target_id=body.user_id, target_type="user",
                     target_label=(target or {}).get("name", str(body.user_id)),
                     before={"usage": int((target or {}).get("ai_usage_count") or 0),
                             "tokens": int((target or {}).get("ai_tokens_today") or 0)},
                     after={"usage": 0, "tokens": 0},
                     tags=["هوشیار", "سهمیه", "پنل_وب"])
    except Exception:
        await db.users.update_one({"user_id": body.user_id}, {"$set": {
            "ai_usage_count": int((target or {}).get("ai_usage_count") or 0),
            "ai_tokens_today": int((target or {}).get("ai_tokens_today") or 0)}})
        raise HTTPException(503, "ثبت حسابرسی ناموفق بود؛ سهمیه قبلی بازگردانده شد")
    return result


# ── Audit ──────────────────────────────────────────────────────────

@router.get("/audit-logs")
async def wa_audit_logs(
    category: Optional[str] = Query(None),
    min_severity: Optional[str] = Query(None),
    q: Optional[str] = Query(None), actor: Optional[str] = Query(None),
    actor_role: Optional[str] = Query(None), module: Optional[str] = Query(None),
    action: Optional[str] = Query(None), target_type: Optional[str] = Query(None),
    target: Optional[str] = Query(None), date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None), correlation_id: Optional[str] = Query(None),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    skip: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100),
    user=Depends(_perm("audit.view")),
):
    return await owner_api.audit_logs_admin(
        admin=user, category=category, min_severity=min_severity, q=q,
        actor=actor, actor_role=actor_role, module=module, action=action,
        target_type=target_type, target=target, date_from=date_from,
        date_to=date_to, correlation_id=correlation_id, sort_dir=sort_dir,
        skip=skip, limit=limit)


class UndoBody(BaseModel):
    reason: str = Field(default="", max_length=500)


@router.post("/audit-logs/{log_id}/undo")
async def wa_audit_undo(log_id: str, body: UndoBody,
                        user=Depends(_perm("audit.undo"))):
    """↩️ §۸۸ — بازگردانی یک تغییرِ ثبت‌شده.

    گیت مجوزِ *جداگانه* (`audit.undo`) دارد، نه `audit.view`: دیدنِ
    تاریخچه و تغییردادنِ گذشته دو سطح اختیارند.
    """
    result = await db.undo_audit_log(log_id, user["id"])
    if not result.get("ok"):
        raise HTTPException(result.get("status", 409), result.get("error", "بازگردانی ممکن نشد"))
    await _audit(user, "بازگردانی تغییر", "Audit", severity="HIGH",
                 target_id=log_id, target_type="audit_log",
                 target_label=str(result.get("target_id")),
                 before={"undone": False},
                 after={"undone": True, "restored": result.get("restored"),
                        "reason": body.reason.strip()},
                 tags=["حسابرسی", "بازگردانی"])
    return {"ok": True, "restored": result.get("restored")}


@router.get("/exports/audit.csv")
async def export_audit_csv(
    category: Optional[str] = Query(None), min_severity: Optional[str] = Query(None),
    q: Optional[str] = Query(None), actor: Optional[str] = Query(None),
    actor_role: Optional[str] = Query(None), module: Optional[str] = Query(None),
    action: Optional[str] = Query(None), target_type: Optional[str] = Query(None),
    target: Optional[str] = Query(None), date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None), correlation_id: Optional[str] = Query(None),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"), human: bool = False,
    user=Depends(_perm("audit.view")),
):
    """CSV سرورساید و filter-aware برای 100k+ audit؛ بدون blobسازی dataset در React."""
    query = owner_api.build_audit_query(
        category=category, min_severity=min_severity, q=q, actor=actor,
        actor_role=actor_role, module=module, action=action,
        target_type=target_type, target=target, date_from=date_from,
        date_to=date_to, correlation_id=correlation_id)
    await _audit(user["id"], "خروجی CSV حسابرسی", severity="HIGH",
                 target_type="export", target_label="audit.csv",
                 after={"filters": {k: v for k, v in {
                     "category": category, "min_severity": min_severity, "q": q,
                     "actor": actor, "module": module, "target": target,
                     "date_from": date_from, "date_to": date_to,
                     "correlation_id": correlation_id}.items() if v}},
                 tags=["خروجی", "حسابرسی", "پنل_وب"])
    columns = ["timestamp", "severity", "category", "module", "action",
               "actor_id", "actor_name", "actor_role", "target_type", "target_id",
               "target_label", "correlation_id", "details"]

    def safe(value):
        text = "" if value is None else str(value)
        return "'" + text if text[:1] in ("=", "+", "-", "@") else text

    async def stream():
        buf = io.StringIO(); writer = csv.writer(buf)
        writer.writerow(columns)
        yield "\ufeff" + buf.getvalue(); buf.seek(0); buf.truncate(0)
        offset = 0
        while True:
            docs = await db.audit_logs.find(query).sort("timestamp", 1 if sort_dir == "asc" else -1).skip(offset).limit(500).to_list(500)
            if not docs: break
            for row in docs:
                actor_doc, target_doc = row.get("actor") or {}, row.get("target") or {}
                writer.writerow([safe(v) for v in [
                    _export_instant(row.get("timestamp"), human), row.get("severity"), row.get("category"), row.get("module"),
                    row.get("action"), actor_doc.get("id"), actor_doc.get("name"), actor_doc.get("role"),
                    target_doc.get("type") or row.get("target_type"),
                    target_doc.get("id") or row.get("target_id"),
                    target_doc.get("label") or row.get("target_label"),
                    row.get("correlation_id"), row.get("details")]])
                yield buf.getvalue(); buf.seek(0); buf.truncate(0)
            if len(docs) < 500: break
            offset += len(docs)

    return StreamingResponse(stream(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=humsyar-audit.csv"})


# ── System / Backup / Prestige ─────────────────────────────────────

@router.get("/system/status")
async def wa_system_status(
    user=Depends(_perm_any(
        "system.manage", "backup.manage", "prestige.manage",
        "settings.manage", "notifications.manage")),
):
    out = await owner_api.bot_status(admin=user)
    perms = await db.get_user_perms(user["id"])
    allow = lambda *keys: user["id"] == ADMIN_ID or any(k in perms for k in keys)
    if allow("notifications.manage", "system.manage"):
        try:
            recent = await db.get_recent_notif_runs(limit=10)
            out["notifications"] = {
                "pending_queue": await db.bot_notifs.count_documents({"sent": False}),
                "recent_failed_runs": sum(1 for r in recent if int(r.get("failed") or 0) > 0),
                "last_run": (recent[0].get("started_at") if recent else None),
            }
        except Exception:
            out["notifications"] = None
    if allow("backup.manage", "system.manage"):
        out["backup"] = {
            "enabled": bool(await db.get_setting("auto_backup_enabled", False)),
            "last_run": await db.get_setting("auto_backup_last_run", None),
            "hour": int(await db.get_setting("auto_backup_hour", 3) or 3),
        }
    return out


@router.get("/system/time-standard")
async def wa_system_time_standard(
    user=Depends(_perm_any("system.manage", "settings.manage")),
):
    return {
        **time_diagnostics(),
        "storage_contract": "UTC / timezone-aware ISO-8601 or BSON Date",
        "display_contract": "Asia/Tehran / Persian / fa-IR",
        "date_only_contract": "Gregorian YYYY-MM-DD machine date interpreted as Tehran civil day",
    }


@router.get("/system/observability")
async def wa_system_observability(hours: int = Query(24, ge=1, le=720),
                                  user=Depends(_perm("system.manage"))):
    since = now_utc() - timedelta(hours=hours)
    match = {"at": {"$gte": since}}
    total, errors = await asyncio.gather(
        db.wa_api_metrics.count_documents(match),
        db.wa_api_metrics.count_documents({**match, "status": {"$gte": 400}}),
    )
    rows = await db.wa_api_metrics.aggregate([
        {"$match": match},
        {"$group": {"_id": "$route", "requests": {"$sum": 1},
                    "errors": {"$sum": {"$cond": [{"$gte": ["$status", 400]}, 1, 0]}},
                    "avg_ms": {"$avg": "$duration_ms"}, "max_ms": {"$max": "$duration_ms"}}},
        {"$sort": {"requests": -1}}, {"$limit": 50},
    ]).to_list(50)
    recent = await db.wa_api_metrics.find({"at": {"$gte": since}, "status": {"$gte": 400}}, {
        "route": 1, "method": 1, "status": 1, "duration_ms": 1, "request_id": 1, "at": 1,
    }).sort("at", -1).limit(30).to_list(30)
    total, errors = int(total or 0), int(errors or 0)
    # 🌊 W5/REL-03 — شمارنده‌های همه‌ی /api/* (افزایشی؛ قرارداد قبلی سر جایش)
    try:
        from api.api_counters import snapshot as _api_snapshot
        _api = _api_snapshot()
    except Exception:
        _api = {"routes": [], "recent_5xx": [], "total": 0, "ephemeral": True}
    return {"hours": hours, "total": total, "errors": errors,
            "api": _api,
            "error_rate": round(errors * 100 / total, 2) if total else None,
            "routes": [{"route": row.get("_id"), "requests": row.get("requests", 0),
                        "errors": row.get("errors", 0), "avg_ms": round(float(row.get("avg_ms") or 0), 2),
                        "max_ms": round(float(row.get("max_ms") or 0), 2)} for row in rows],
            "recent_errors": [{**{key: item.get(key) for key in
                                ("route", "method", "status", "duration_ms", "request_id")},
                               "at": item.get("at").isoformat() if hasattr(item.get("at"), "isoformat") else str(item.get("at") or "")}
                              for item in recent],
            "retention_days": 30, "persisted": True}


class FeaturePolicyBody(BaseModel):
    enabled: bool | None = None
    access: str | None = None
    trial_allowed: bool | None = None
    quota_kind: str | None = None
    quota_limit: int | None = None
    fail_open: bool | None = None
    note: str | None = Field(default=None, max_length=300)
    pending_access: str | None = None
    effective_from: str | None = Field(default=None, max_length=40)


@router.get("/features")
async def wa_features_list(user=Depends(_perm("subscription.manage"))):
    """🌊 W7 — کاتالوگ + پالیسی همه‌ی فیچرها برای پنل دسترسی."""
    from core.features import FEATURE_CATALOG, default_policy
    docs = await db.feature_policies.find(
        {"_id": {"$in": list(FEATURE_CATALOG)}}).to_list(50)
    by_id = {d.get("_id"): d for d in docs}
    items = []
    for key, spec in FEATURE_CATALOG.items():
        d = by_id.get(key) or {}
        pol = default_policy(key)
        for k in ("enabled", "access", "trial_allowed", "quota", "fail_open",
                  "note", "pending_access", "effective_from"):
            if k in d:
                pol[k] = d[k]
        prev = d.get("prev") or {}
        items.append({
            "key": key, "label": spec.get("label", key),
            "category": spec.get("category", ""),
            "desc": spec.get("desc", ""),
            "enforced": bool(spec.get("enforced")),
            "stored": bool(d), "policy": pol,
            "updated_by": d.get("updated_by_name", "") or "",
            "updated_at": d.get("updated_at"),
            "has_prev": bool(prev),
            "prev_at": prev.get("_at"), "prev_by": prev.get("_by_name", ""),
        })
    return {"items": items}


@router.put("/features/{key}")
async def wa_feature_update(key: str, body: FeaturePolicyBody,
                            user=Depends(_perm("subscription.manage"))):
    """🌊 W7 — تغییر پالیسی یک فیچر (audit اجباری + جبران در شکست audit)."""
    from core.features import FEATURE_CATALOG, ACCESS_MODES, QUOTA_KINDS
    if key not in FEATURE_CATALOG:
        raise HTTPException(404, "فیچر ناشناخته")
    patch = {}
    if body.enabled is not None:
        patch["enabled"] = bool(body.enabled)
    if body.access is not None:
        if body.access not in ACCESS_MODES:
            raise HTTPException(422, "حالت دسترسی نامعتبر")
        patch["access"] = body.access
    if body.trial_allowed is not None:
        patch["trial_allowed"] = bool(body.trial_allowed)
    if body.quota_kind is not None or body.quota_limit is not None:
        cur = await db.get_feature_policy(key) or {}
        q = dict(cur.get("quota") or {"kind": "none", "limit": 0})
        if body.quota_kind is not None:
            if body.quota_kind not in QUOTA_KINDS:
                raise HTTPException(422, "نوع سهمیه نامعتبر")
            q["kind"] = body.quota_kind
        if body.quota_limit is not None:
            if body.quota_limit < 0 or body.quota_limit > 1000000:
                raise HTTPException(422, "سقف سهمیه نامعتبر")
            q["limit"] = int(body.quota_limit)
        patch["quota"] = q
    if body.fail_open is not None:
        patch["fail_open"] = bool(body.fail_open)
    if body.note is not None:
        patch["note"] = (body.note or "")[:300]
    if body.pending_access is not None:
        if body.pending_access not in ("", *ACCESS_MODES):
            raise HTTPException(422, "حالت زمان‌بندی نامعتبر")
        patch["pending_access"] = body.pending_access or None
    if body.effective_from is not None:
        eff = (body.effective_from or "").strip() or None
        if eff:
            try:
                from datetime import datetime
                datetime.fromisoformat(eff)
            except ValueError:
                raise HTTPException(422, "زمان شروع نامعتبر (ISO)")
        patch["effective_from"] = eff
    if not patch:
        raise HTTPException(422, "تغییری ارسال نشده")
    res = await db.set_feature_policy(
        key, patch, user["id"], (user.get("_db") or {}).get("name", ""))
    from core.access import invalidate_policy_cache
    invalidate_policy_cache(key)
    try:
        await _audit(user["id"], f"تغییر دسترسی فیچر «{key}»",
                     severity="HIGH", target_id=key, target_type="feature",
                     target_label=(FEATURE_CATALOG[key].get("label") or key),
                     before=res["before"], after=res["after"],
                     tags=["فیچر", "دسترسی", "پنل_وب", f"feature:{key}"])
    except Exception:
        # جبران: مثل settings_center — برگرداندن پالیسیِ قبلی
        try:
            await db.set_feature_policy(key, res["before"], user["id"], "")
            invalidate_policy_cache(key)
        except Exception:
            pass
        raise HTTPException(500, "ثبت audit ناموفق بود؛ تغییر برگردانده شد")
    try:
        await db.log_feature_event(key, "feature_policy_changed",
                                   user["id"], {"after": res["after"]})
    except Exception:
        pass
    return {"ok": True, "after": res["after"]}


@router.post("/features/{key}/rollback")
async def wa_feature_rollback(key: str,
                              user=Depends(_perm("subscription.manage"))):
    """🌊 W7 — بازگردانی به پالیسی قبلی (دو بار = redo)."""
    from core.features import FEATURE_CATALOG
    if key not in FEATURE_CATALOG:
        raise HTTPException(404, "فیچر ناشناخته")
    res = await db.rollback_feature_policy(
        key, user["id"], (user.get("_db") or {}).get("name", ""))
    if not res:
        raise HTTPException(409, "پالیسی قبلی وجود ندارد")
    from core.access import invalidate_policy_cache
    invalidate_policy_cache(key)
    try:
        await _audit(user["id"], f"بازگردانی دسترسی فیچر «{key}»",
                     severity="HIGH", target_id=key, target_type="feature",
                     before=res["before"], after=res["after"],
                     tags=["فیچر", "دسترسی", "بازگردانی", f"feature:{key}"])
    except Exception:
        try:
            await db.set_feature_policy(key, res["before"], user["id"], "")
            invalidate_policy_cache(key)
        except Exception:
            pass
        raise HTTPException(500, "ثبت audit ناموفق بود؛ تغییر برگردانده شد")
    return {"ok": True, "after": res["after"]}


@router.get("/system/client-errors")
async def wa_system_client_errors(hours: int = Query(24, ge=1, le=720),
                                  limit: int = Query(50, ge=1, le=200),
                                  user=Depends(_perm("system.manage"))):
    """🌊 W5/REL-03 — خطاهای گزارش‌شده‌ی فرانت (مینی‌اپ/وب‌ادمین)."""
    since = now_utc() - timedelta(hours=hours)
    rows = await db.client_errors.find(
        {"at": {"$gte": since}}).sort("at", -1).to_list(limit)
    groups = await db.client_errors.aggregate([
        {"$match": {"at": {"$gte": since}}},
        {"$group": {"_id": {"app": "$app", "message": "$message"},
                    "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 20},
    ]).to_list(20)
    items = []
    for r in rows:
        at = r.get("at")
        items.append({
            "app": r.get("app") or "", "path": r.get("path") or "",
            "message": (r.get("message") or "")[:200],
            "user_id": r.get("user_id"),
            "at": at.isoformat() if hasattr(at, "isoformat") else str(at or ""),
        })
    return {"hours": hours, "items": items,
            "groups": [{"app": (g.get("_id") or {}).get("app") or "",
                        "message": ((g.get("_id") or {}).get("message") or "")[:200],
                        "count": int(g.get("n") or 0)} for g in groups]}


@router.get("/system/jobs")
async def wa_system_jobs(
    user=Depends(_perm_any("system.manage", "notifications.manage", "backup.manage")),
):
    """Job center فقط از queue/run/settings واقعی؛ هیچ scheduler ساختگی ندارد."""
    perms = await db.get_user_perms(user["id"])
    allow = lambda *keys: user["id"] == ADMIN_ID or any(k in perms for k in keys)
    jobs = []
    if allow("notifications.manage", "system.manage"):
        runs = await db.get_recent_notif_runs(limit=20)
        grouped = {}
        for run in runs:
            name = run.get("job_name") or "notification"
            grouped.setdefault(name, run)
        for name, run in grouped.items():
            jobs.append({
                "key": f"notif:{name}", "label": name, "kind": "notification",
                "status": run.get("status", "unknown"),
                "sent": int(run.get("sent") or 0), "failed": int(run.get("failed") or 0),
                "total": int(run.get("total") or 0),
                "last_run": run.get("started_at") or None,
            })
        queue = await db.bot_notifs.count_documents({"sent": False})
        scheduled = await db.bot_notifs.count_documents({
            "sent": False, "send_at": {"$exists": True, "$ne": None},
        })
        jobs.append({"key": "outbox", "label": "صف خروجی ربات", "kind": "queue",
                     "status": "pending" if queue else "idle", "pending": queue,
                     "scheduled": scheduled})
    if allow("backup.manage", "system.manage"):
        enabled = bool(await db.get_setting("auto_backup_enabled", False))
        jobs.append({"key": "backup", "label": "پشتیبان خودکار", "kind": "backup",
                     "status": "enabled" if enabled else "disabled",
                     "hour": int(await db.get_setting("auto_backup_hour", 3) or 3),
                     "last_run": await db.get_setting("auto_backup_last_run", None)})
    dead = await db.bot_notifs.count_documents({"status": "dead"})
    if dead:
        jobs.append({"key": "dlq", "label": "پیام‌های مرده (DLQ)", "kind": "dlq",
                     "status": "failed", "dead": dead})
    return {"jobs": jobs, "checked_at": _now()}


# ══════════════════════════════════════════════════════════════════
# 💀 DLQ — صف پیام‌های مرده
#
# چرا لازم است: مصرف‌کننده‌ی outbox در bot.py پس از ۴ تلاش ناموفق سند را
# `status="dead"` و `sent=True` می‌کند. آن `sent=True` باعث می‌شود پیام از
# شمارش `pending_queue` بیرون بیفتد، در حالی که هرگز به کاربر نرسیده است.
# نتیجه: گم‌شدن خاموش پیام — هیچ صفحه‌ای در پنل آن را نشان نمی‌داد.
# این اندپوینت‌ها همان اسناد را قابل‌مشاهده و قابل‌بازپخش می‌کنند.
# هیچ کالکشن یا سیستم حسابرسی جدیدی ساخته نمی‌شود.
# ══════════════════════════════════════════════════════════════════

_DLQ_MAX_REQUEUE = 500


@router.get("/system/dlq")
async def wa_dlq_list(
    page: int = Query(1, ge=1), per_page: int = Query(25, ge=1, le=100),
    user=Depends(_perm_any("system.manage", "notifications.manage")),
):
    """پیام‌هایی که پس از سقف تلاش مرده‌اند و هرگز تحویل نشده‌اند."""
    filt = {"status": "dead"}
    total = await db.bot_notifs.count_documents(filt)
    docs = await db.bot_notifs.find(
        filt, {"chat_id": 1, "text": 1, "type": 1, "attempts": 1, "error": 1,
               "sent_at": 1, "created_at": 1, "campaign_id": 1},
    ).sort("sent_at", -1).skip((page - 1) * per_page).limit(per_page).to_list(per_page)
    return {
        "items": [{
            "id": str(row.get("_id")),
            "user_id": row.get("chat_id"),
            # متن بریده می‌شود: DLQ برای تشخیص است، نه بازخوانی کامل پیام کاربر.
            "text": (row.get("text") or "")[:160],
            "type": row.get("type") or "",
            "attempts": int(row.get("attempts") or 0),
            "error": (row.get("error") or "")[:200],
            "campaign_id": row.get("campaign_id"),
            "died_at": row.get("sent_at") or None,
            "created_at": row.get("created_at") or None,
        } for row in docs],
        "total": total, "page": page, "per_page": per_page,
        "pages": max(1, -(-total // per_page)),
        "checked_at": _now(),
    }


class WaDlqRequeue(BaseModel):
    ids: Optional[list[str]] = None
    all_dead: bool = False


@router.post("/system/dlq/requeue")
async def wa_dlq_requeue(body: WaDlqRequeue,
                         user=Depends(_perm("system.manage"))):
    """بازگرداندن پیام‌های مرده به صف ارسال.

    شمارنده‌ی attempts صفر می‌شود وگرنه سند بلافاصله دوباره می‌میرد.
    سقف دارد تا یک درخواست، کل صف را روی تلگرام آوار نکند.
    """
    if body.all_dead:
        filt = {"status": "dead"}
        ids = [row["_id"] for row in await db.bot_notifs.find(
            filt, {"_id": 1}).limit(_DLQ_MAX_REQUEUE).to_list(_DLQ_MAX_REQUEUE)]
    else:
        raw = list(dict.fromkeys(body.ids or []))[:_DLQ_MAX_REQUEUE]
        ids = []
        for item in raw:
            try:
                ids.append(ObjectId(item))
            except Exception:
                continue
        if raw and not ids:
            raise HTTPException(422, "شناسه‌ی نامعتبر است")
    if not ids:
        raise HTTPException(400, "موردی برای بازپخش انتخاب نشده است")
    result = await db.bot_notifs.update_many(
        {"_id": {"$in": ids}, "status": "dead"},
        {"$set": {"sent": False, "failed": False, "attempts": 0, "status": "queued"},
         "$unset": {"error": "", "sent_at": "", "send_at": ""}})
    # details پاس داده می‌شود چون log_action مقدار `after` را فقط وقتی نگه
    # می‌دارد که `before` هم بیاید؛ بدون این، شمارشِ بازپخش در لاگ گم می‌شد.
    await _audit(user["id"], "بازپخش پیام‌های مرده صف", severity="WARNING",
                 target_type="dlq", target_label="bot_outbox",
                 details=f"{result.modified_count} پیام از {len(ids)} مورد به صف بازگشت",
                 before={"requeued": 0}, after={"requeued": result.modified_count},
                 tags=["صف", "dlq", "پنل_وب"])
    return {"requeued": result.modified_count, "requested": len(ids)}


@router.post("/system/dlq/discard")
async def wa_dlq_discard(body: WaDlqRequeue,
                         user=Depends(_perm("system.manage"))):
    """کنارگذاشتن نهایی پیام‌های مرده.

    سند حذف نمی‌شود — فقط `status="discarded"` می‌گیرد تا ردِ حسابرسی و
    امکان بررسی بعدی باقی بماند.
    """
    if body.all_dead:
        ids = [row["_id"] for row in await db.bot_notifs.find(
            {"status": "dead"}, {"_id": 1}).limit(_DLQ_MAX_REQUEUE).to_list(_DLQ_MAX_REQUEUE)]
    else:
        ids = []
        for item in list(dict.fromkeys(body.ids or []))[:_DLQ_MAX_REQUEUE]:
            try:
                ids.append(ObjectId(item))
            except Exception:
                continue
    if not ids:
        raise HTTPException(400, "موردی برای کنارگذاشتن انتخاب نشده است")
    result = await db.bot_notifs.update_many(
        {"_id": {"$in": ids}, "status": "dead"},
        {"$set": {"status": "discarded", "discarded_at": _now(),
                  "discarded_by": user["id"]}})
    await _audit(user["id"], "کنارگذاشتن پیام‌های مرده صف", severity="HIGH",
                 target_type="dlq", target_label="bot_outbox",
                 details=f"{result.modified_count} پیام از {len(ids)} مورد کنار گذاشته شد",
                 before={"discarded": 0}, after={"discarded": result.modified_count},
                 tags=["صف", "dlq", "پنل_وب"])
    return {"discarded": result.modified_count, "requested": len(ids)}


@router.get("/system/backup-settings")
async def wa_backup_settings(user=Depends(_perm("backup.manage"))):
    return {
        "auto_backup_enabled": bool(await db.get_setting("auto_backup_enabled", False)),
        "auto_backup_hour": int(await db.get_setting("auto_backup_hour", 3) or 0),
        "auto_backup_last_run": await db.get_setting("auto_backup_last_run", None),
    }


class WaBackupSettingsPatch(BaseModel):
    auto_backup_enabled: Optional[bool] = None
    auto_backup_hour: Optional[int] = None


@router.patch("/system/backup-settings")
async def wa_backup_settings_patch(
    body: WaBackupSettingsPatch,
    user=Depends(_perm("backup.manage")),
):
    owner_body = owner_api.BotSettingsPatch(
        auto_backup_enabled=body.auto_backup_enabled,
        auto_backup_hour=body.auto_backup_hour,
    )
    return await owner_api.bot_settings_patch(body=owner_body, admin=user)


async def _read_restore_upload(file: UploadFile):
    if not (file.filename or "").lower().endswith(".json"):
        raise HTTPException(422, "فقط فایل JSON پشتیبان پذیرفته می‌شود")
    raw = await file.read(50 * 1024 * 1024 + 1)
    if len(raw) > 50 * 1024 * 1024:
        raise HTTPException(413, "حجم فایل پشتیبان بیشتر از ۵۰MB است")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(422, "فایل JSON معتبر نیست")
    if not isinstance(data, dict) or not data.get("backup_version"):
        raise HTTPException(422, "ساختار فایل پشتیبان شناخته‌شده نیست")
    integrity = data.get("integrity")
    if isinstance(integrity, dict) and integrity.get("complete") is not True:
        raise HTTPException(422, "پشتیبان ناقص است و برای بازیابی پذیرفته نمی‌شود")
    section = data.get("section", "full")
    sections = data.get("sections") or {section: data}
    if not isinstance(sections, dict) or not sections:
        raise HTTPException(422, "فایل هیچ بخش قابل بازیابی ندارد")
    known = {"users", "basic_science", "content", "references", "refs", "qbank",
             "schedules", "faq", "tickets", "access_control", "access",
             "subscription_system", "subscription", "grades", "settings", "logs", "stats",
             "communications", "ai", "prestige", "webadmin_state"}
    unknown = [key for key in sections if key not in known]
    if unknown:
        raise HTTPException(422, f"بخش ناشناخته در پشتیبان: {', '.join(unknown[:5])}")
    digest = hashlib.sha256(raw).hexdigest()
    return data, sections, digest, len(raw)


def _backup_section_count(value):
    if not isinstance(value, dict):
        return 0
    if isinstance(value.get("count"), int):
        return value["count"]
    return sum(_backup_section_count(v) for v in value.values() if isinstance(v, dict))


@router.post("/system/restore/validate")
async def wa_restore_validate(
    file: UploadFile = File(...), user=Depends(_guard_any_admin),
):
    if user["id"] != ADMIN_ID:
        raise HTTPException(403, "owner_only")
    data, sections, digest, size = await _read_restore_upload(file)
    integrity = data.get("integrity") if isinstance(data.get("integrity"), dict) else None
    warnings = []
    if integrity is None:
        warnings.append("این فایل legacy است و manifest یکپارچگی ندارد؛ شمارش کامل‌بودن قابل اثبات نیست.")
    warnings.append("بازیابی از نوع merge/upsert است؛ رکوردهای فعلیِ غایب از فایل حذف نمی‌شوند.")
    return {"valid": True, "digest": digest, "size": size,
            "backup_version": data.get("backup_version"),
            "created_at": data.get("created_at") or None,
            "restore_semantics": data.get("restore_semantics") or "merge_upsert",
            "integrity": integrity,
            "warnings": warnings,
            "sections": [{"key": key, "records": _backup_section_count(value)}
                         for key, value in sections.items()]}


@router.post("/system/restore/confirm")
async def wa_restore_confirm(
    file: UploadFile = File(...), digest: str = Form(...),
    confirmation: str = Form(...), user=Depends(_guard_any_admin),
):
    if user["id"] != ADMIN_ID:
        raise HTTPException(403, "owner_only")
    if confirmation.strip() != "RESTORE HUMSYAR":
        raise HTTPException(422, "عبارت تأیید بازیابی صحیح نیست")
    _data, sections, actual_digest, _size = await _read_restore_upload(file)
    if not secrets.compare_digest(actual_digest, digest.strip().lower()):
        raise HTTPException(409, "فایل با نسخه‌ی اعتبارسنجی‌شده یکسان نیست")
    # Fail closed before touching data: at least the restore intent is durable,
    # even if a later section fails and requires operator recovery.
    await _audit_strict(
        user["id"], "آغاز بازیابی فایل پشتیبان از Web Admin", severity="CRITICAL",
        target_id=actual_digest[:16], target_type="backup",
        target_label=", ".join(sections.keys()),
        after={"phase": "started", "sections": len(sections),
               "semantics": _data.get("restore_semantics") or "merge_upsert"},
        tags=["بازیابی_بکاپ", "پنل_وب", "restore_started"],
    )
    restored = {}
    for key, value in sections.items():
        restored[key] = await backup_service._restore_section(key, value)
    await _audit(user["id"], "بازیابی فایل پشتیبان از Web Admin", severity="CRITICAL",
                 target_id=actual_digest[:16], target_type="backup",
                 target_label=", ".join(sections.keys()),
                 after={"sections": len(restored), "records": sum(restored.values())},
                 tags=["بازیابی_بکاپ", "پنل_وب"])
    return {"ok": True, "restored": restored, "total": sum(restored.values())}


@router.post("/system/backup")
async def wa_backup_request(
    body: owner_api.BackupRequestBody,
    user=Depends(_perm("backup.manage")),
):
    return await owner_api.request_backup(body=body, admin=user)


@router.post("/system/export/excel")
async def wa_export_excel(user=Depends(_perm("backup.manage"))):
    await db.bot_notifs.insert_one({
        "type": "excel_export_request", "chat_id": user["id"],
        "text": "__EXCEL_EXPORT__", "sent": False, "created_at": _now(),
    })
    await _audit(user["id"], "درخواست خروجی اکسل کامل", severity="HIGH",
                 tags=["اکسل", "خروجی", "پنل_وب"])
    return {"ok": True, "message": "📊 فایل اکسل از طریق ربات برای شما ارسال می‌شود."}


@router.post("/system/prestige/backfill")
async def wa_prestige_backfill(user=Depends(_perm("prestige.manage"))):
    return await owner_api.prestige_backfill(admin=user)


@router.get("/system/prestige-config")
async def wa_prestige_config(user=Depends(_perm("prestige.manage"))):
    return await owner_api.prestige_config_get(admin=user)


@router.put("/system/prestige-config")
async def wa_prestige_config_update(
    body: owner_api.PrestigeConfigPut,
    user=Depends(_perm("prestige.manage")),
):
    return await owner_api.prestige_config_put(body=body, admin=user)


@router.post("/system/notifications/force-send")
async def wa_force_resources(user=Depends(_perm("notifications.manage"))):
    return await owner_api.notifications_force_send(admin=user)


@router.post("/system/log-groups/test")
async def wa_log_groups_test(
    user=Depends(_perm_any("settings.manage", "system.manage")),
):
    return await owner_api.log_groups_test(admin=user)


# ── Content reports: تاریخچه و workflow برای reports.review ───────

@router.get("/content/reports")
async def wa_content_reports(
    status: Optional[str] = Query(None), skip: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    user=Depends(_perm("reports.review")),
):
    return await content_api.reports_list_ep(
        status=status, skip=skip, limit=limit, admin=user)


@router.get("/content/reports/stats")
async def wa_content_report_stats(user=Depends(_perm("reports.review"))):
    return await content_api.reports_stats_ep(admin=user)


@router.post("/content/reports/{rid}/status")
async def wa_content_report_status(
    rid: int, body: content_api.ReportStatusUpdate,
    user=Depends(_perm("reports.review")),
):
    return await content_api.report_status_ep(rid=rid, body=body, admin=user)


# ── Schedule: کلاس/امتحان/جبرانی برای schedules.manage ────────────

@router.get("/schedule")
async def wa_schedule_list(
    stype: Optional[str] = Query(None),
    user=Depends(_perm("schedules.manage")),
):
    return await content_api.schedule_list(admin=user, stype=stype)


@router.post("/schedule")
async def wa_schedule_create(
    body: content_api.ScheduleCreate,
    user=Depends(_perm("schedules.manage")),
):
    return await content_api.add_schedule(body=body, admin=user)


@router.patch("/schedule/{sid}")
async def wa_schedule_update(
    sid: str,
    body: content_api.ScheduleUpdate,
    user=Depends(_perm("schedules.manage")),
):
    return await content_api.edit_schedule(sid=sid, body=body, admin=user)


@router.delete("/schedule/{sid}")
async def wa_schedule_delete(
    sid: str,
    user=Depends(_perm("schedules.manage")),
):
    return await content_api.del_schedule(sid=sid, admin=user)


@router.post("/schedule/{sid}/flex-change")
async def wa_schedule_flex_change(
    sid: str,
    body: content_api.FlexChange,
    user=Depends(_perm("schedules.manage")),
):
    return await content_api.flex_change(sid=sid, body=body, admin=user)


# ── 📅 الگوی هفتگی (شنبه-جمعه) + اسکن هوشیار — پروکسی وب‌ادمین ───
@router.get("/schedule/templates")
async def wa_schedule_templates_list(
    group: Optional[str] = Query(None),
    user=Depends(_perm("schedules.manage")),
):
    return await academic_api.schedule_templates_list(group=group, admin=user)

@router.post("/schedule/templates/bulk")
async def wa_schedule_templates_bulk(
    body: academic_api.TemplateBulk,
    user=Depends(_perm("schedules.manage")),
):
    return await academic_api.schedule_templates_bulk(body=body, admin=user)

@router.delete("/schedule/templates")
async def wa_schedule_templates_delete(
    group: Optional[str] = Query(None),
    user=Depends(_perm("schedules.manage")),
):
    return await academic_api.schedule_templates_clear(group=group, admin=user)


@router.delete("/schedule/templates/clear")
async def wa_schedule_templates_clear_alias(
    group: Optional[str] = Query(None),
    user=Depends(_perm("schedules.manage")),
):
    """Alias قدیمی برای سازگاری با کش فرانت — همان پاک‌سازی الگو."""
    return await academic_api.schedule_templates_clear(group=group, admin=user)


@router.delete("/schedule")
async def wa_schedule_bulk_delete(
    group: Optional[str] = Query(None),
    stype: Optional[str] = Query(None),
    user=Depends(_perm("schedules.manage")),
):
    """پاک‌سازی گروهی برنامه‌های تولیدشده (schedules) — برای «پاکسازی این گروه» یکپارچه.

    بدون پارامتر ⇒ همه‌ی برنامه‌ها پاک می‌شود (با تأیید فرانت).
    group با normalize + aliasهای legacy، stype اختیاری (class/exam/makeup).
    هیچ‌وقت 404 نمی‌دهد؛ حتی اگر چیزی برای حذف نبود deleted=0 برمی‌گردد.
    """
    q: dict = {}
    if group is not None and str(group).strip() != "":
        norm = db.normalize_group(group)
        # برای 1 و 2 تمام aliasها را پاک کن تا legacy نماند
        if norm in ("1", "2"):
            q["group"] = {"$in": db.group_aliases(norm)}
        else:
            q["group"] = norm
    if stype:
        if stype not in ("class", "exam", "makeup"):
            raise HTTPException(400, "stype نامعتبر است")
        q["type"] = stype
    r = await db.schedules.delete_many(q)
    n = int(getattr(r, "deleted_count", 0) or 0)
    try:
        await _audit(user["id"], f"پاک‌سازی گروهی برنامه‌ها ({n} مورد)", "Schedules", severity="WARNING",
                     target_type="schedule", target_label=str(group or "همه"),
                     after={"deleted": n, "group": group, "stype": stype},
                     tags=["برنامه", "پاکسازی_گروهی", "پنل_وب"])
    except Exception:
        pass
    return {"ok": True, "deleted": n}


class BulkScheduleDeleteIn(BaseModel):
    ids: Optional[List[str]] = None
    group: Optional[str] = None
    stype: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    delete_all: bool = False


@router.post("/schedule/bulk-delete")
async def wa_schedule_bulk_delete_post(
    body: BulkScheduleDeleteIn,
    user=Depends(_perm("schedules.manage")),
):
    """حذف گروهی پیشرفته — انتخاب چندتایی / بازه‌ی تاریخی / همه.

    - اگر ids داده شود: همان‌ها حذف می‌شوند (حتی اگر ادغام‌شده باشند).
    - وگرنه فیلتر group/stype/date_from/date_to اعمال می‌شود.
    - اگر هیچ‌کدام نبود و delete_all=false → 400 (جلوگیری از حذف تصادفی).
    - هیچ‌وقت 404 نمی‌دهد؛ deleted=0 هم ok است.
    """
    from bson import ObjectId
    q: dict = {}

    # حالت 1: حذف بر اساس ids صریح
    if body.ids:
        oids = []
        for sid in body.ids:
            try:
                oids.append(ObjectId(str(sid).strip()))
            except Exception:
                continue
        if not oids:
            raise HTTPException(400, "شناسه‌های نامعتبر")
        q["_id"] = {"$in": oids}
    else:
        # حالت 2: فیلتر
        has_filter = any([body.group not in (None, ""), body.stype not in (None, ""), body.date_from, body.date_to, body.delete_all])
        if not has_filter:
            raise HTTPException(400, "برای حذف گروهی باید ids یا فیلتر یا delete_all ارسال شود")

        if body.group is not None and str(body.group).strip() != "":
            norm = db.normalize_group(body.group)
            if norm in ("1", "2"):
                q["group"] = {"$in": db.group_aliases(norm)}
            else:
                q["group"] = norm
        if body.stype:
            if body.stype not in ("class", "exam", "makeup"):
                raise HTTPException(400, "stype نامعتبر است")
            q["type"] = body.stype
        # بازه‌ی تاریخی — هماهنگ با time.js جلالی→میلادی و ارقام فارسی
        if body.date_from or body.date_to:
            date_q = {}
            def _to_gregorian(s: str) -> str:
                from time_utils import en_digits as _en
                s = _en(str(s)).strip()
                if not s:
                    return ""
                s_norm = s.replace("/", "-").replace("٫", "-").replace("،", "-")
                # جلالی با ارقام فارسی یا لاتین: 14xx-xx-xx
                try:
                    if s_norm[:2] == "14" or (len(s_norm) >= 4 and s_norm[:4].startswith("14")):
                        from time_utils import parse_jalali_date
                        d = parse_jalali_date(s)
                        return d.isoformat()
                except Exception:
                    pass
                try:
                    from time_utils import parse_gregorian_date
                    d = parse_gregorian_date(s_norm[:10])
                    return d.isoformat()
                except Exception:
                    return s_norm[:10]
            if body.date_from:
                g = _to_gregorian(body.date_from)
                if g:
                    date_q["$gte"] = g
            if body.date_to:
                g = _to_gregorian(body.date_to)
                if g:
                    date_q["$lte"] = g
            if date_q:
                # اعتبارسنجی ترتیب بازه (هماهنگ با فرانت PersianDatePicker)
                if "$gte" in date_q and "$lte" in date_q and date_q["$gte"] > date_q["$lte"]:
                    raise HTTPException(400, "بازه‌ی تاریخ نامعتبر است: تاریخ شروع باید قبل از پایان باشد")
                q["date"] = date_q
        # اگر delete_all بدون فیلتر دیگر، q خالی می‌ماند → حذف همه
        if not q and body.delete_all:
            q = {}

    if not q and not body.ids and not body.delete_all:
        raise HTTPException(400, "فیلتر حذف خالی است")

    r = await db.schedules.delete_many(q)
    n = int(getattr(r, "deleted_count", 0) or 0)
    try:
        await _audit(user["id"], f"حذف گروهی پیشرفته ({n} مورد)", "Schedules", severity="WARNING",
                     target_type="schedule", target_label=str(body.group or body.stype or ("ids:"+str(len(body.ids or [])) if body.ids else "همه")),
                     after={"deleted": n, "filters": body.model_dump()},
                     tags=["برنامه", "حذف_گروهی", "پنل_وب"])
    except Exception:
        pass
    return {"ok": True, "deleted": n}

@router.post("/schedule/templates/generate")
async def wa_schedule_templates_generate(
    body: academic_api.TemplateGenerate,
    user=Depends(_perm("schedules.manage")),
):
    return await academic_api.schedule_templates_generate(body=body, admin=user)

@router.post("/schedule/templates/scan")
async def wa_schedule_templates_scan(
    file: UploadFile = File(...),
    group: Optional[str] = Query(None),
    user=Depends(_perm("schedules.manage")),
):
    return await academic_api.schedule_templates_scan(file=file, group=group, admin=user)

@router.post("/schedule/templates/scan/confirm")
async def wa_schedule_templates_scan_confirm(
    body: academic_api.TemplateBulk,
    user=Depends(_perm("schedules.manage")),
):
    return await academic_api.schedule_templates_scan_confirm(body=body, admin=user)

@router.post("/schedule/exams/scan")
async def wa_schedule_exams_scan(
    file: UploadFile = File(...),
    user=Depends(_perm("schedules.manage")),
):
    return await academic_api.schedule_exams_scan(file=file, admin=user)

@router.post("/schedule/exams/scan/confirm")
async def wa_schedule_exams_scan_confirm(
    body: academic_api.ExamBulkConfirm,
    user=Depends(_perm("schedules.manage")),
):
    return await academic_api.schedule_exams_scan_confirm(body=body, admin=user)


# ── Grades: global/scoped permissions ──────────────────────────────

async def _grade_intake_scope(user: dict) -> Optional[str]:
    if await db.has_permission(user["id"], "grades.manage"):
        return None
    if await db.has_permission(user["id"], "grades.scoped"):
        scope = await db.get_scoped_intake(user["id"])
        if scope:
            return scope
        info = await db.get_user_roles(user["id"])
        if info.get("scope_intake"):
            return info["scope_intake"]
    raise HTTPException(403, "grade_scope_missing")


@router.get("/grades/recent")
async def wa_grades_recent(
    skip: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100),
    q: Optional[str] = Query(None, max_length=100),
    lesson: Optional[str] = Query(None, max_length=100),
    group: Optional[str] = Query(None, max_length=20), intake: Optional[str] = Query(None, max_length=80),
    date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
    # 🛡 AUDIT-§۸۲ — پروکسیِ پنل باید پارامترِ تازه را *فروارد* کند؛ وگرنه
    # فیلتر ترم در API کار می‌کند ولی از پنل بی‌اثر است (قرارداد §۳۴:
    # هر پارامترِ تازه‌ای در هر لایه‌ی میانی باید عبور داده شود).
    term: Optional[str] = Query(None, max_length=40),
    user=Depends(_perm_any("grades.manage", "grades.scoped")),
):
    requested_intake = intake if isinstance(intake, str) else None
    date_from = date_from if isinstance(date_from, str) else None
    date_to = date_to if isinstance(date_to, str) else None
    scoped_intake = await _grade_intake_scope(user)
    if scoped_intake is not None and requested_intake not in (None, "", scoped_intake):
        raise HTTPException(403, "intake_out_of_scope")
    effective_intake = scoped_intake if scoped_intake is not None else requested_intake
    return await academic_api.grades_recent(
        skip=skip, limit=limit, intake=effective_intake, group=group,
        q=q, lesson=lesson, date_from=date_from, date_to=date_to,
        term=term.strip()[:40] if isinstance(term, str) and term.strip() else None,
        admin=user)


@router.get("/grades/term-options")
async def wa_grades_term_options(
    user=Depends(_perm_any("grades.manage", "grades.scoped")),
):
    """🛡 §۸۲-ب — پروکسیِ گزینه‌های ترم برای فرمِ ثبتِ پنل وب.

    قرارداد §۳۴: هر مسیرِ تازه باید در لایه‌ی میانی هم عبور داده شود، وگرنه
    منوی ترم در پنل ۴۰۴ می‌گیرد و خالی می‌ماند.
    """
    return await academic_api.grades_term_options(admin=user)


@router.get("/grades/lesson-term")
async def wa_grades_lesson_term(
    lesson: str = Query(..., min_length=1, max_length=120),
    user=Depends(_perm_any("grades.manage", "grades.scoped")),
):
    """🛡 §۸۲-ج — پروکسی حدس ترم از روی درس برای پرکردن خودکار منوی ترم."""
    return await academic_api.grades_lesson_term(lesson=lesson, admin=user)


@router.get("/grades/intakes")
async def wa_grades_intakes(user=Depends(_perm_any("grades.manage", "grades.scoped"))):
    scoped = await _grade_intake_scope(user)
    items = await db.get_all_intakes()
    return {"scope_intake": scoped, "intakes": [{"code": item.get("code", ""),
             "label": item.get("label", item.get("code", ""))} for item in items
             if item.get("active", True) and (scoped is None or item.get("code") == scoped)]}


@router.get("/grades/find-student")
async def wa_grades_find_student(
    q: str = Query(..., min_length=2, max_length=100),
    user=Depends(_perm_any("grades.manage", "grades.scoped")),
):
    intake = await _grade_intake_scope(user)
    users = await db.search_users(q.strip())
    return {"students": [
        {"id": s.get("user_id"), "name": s.get("name", ""),
         "student_id": s.get("student_id", ""), "group": s.get("group", ""),
         "intake": s.get("intake", "")}
        for s in users
        if s.get("approved") and (intake is None or s.get("intake") == intake)
    ]}


@router.post("/grades/bulk")
async def wa_grades_bulk(
    body: academic_api.GradeBulkCreate,
    user=Depends(_perm_any("grades.manage", "grades.scoped")),
):
    intake = await _grade_intake_scope(user)
    if intake is not None:
        ids = [e.user_id for e in body.entries]
        matched = await db.users.find(
            {"user_id": {"$in": ids}, "approved": True, "intake": intake},
            {"user_id": 1}).to_list(len(ids))
        if {u.get("user_id") for u in matched} != set(ids):
            raise HTTPException(403, "grade_intake_out_of_scope")
    return await academic_api.grades_bulk_create(body=body, admin=user)


async def _grade_for_actor(grade_id: str, user: dict) -> dict:
    grade = await db.grade_get(grade_id)
    if not grade:
        raise HTTPException(404, "نمره پیدا نشد")
    intake = await _grade_intake_scope(user)
    if intake is not None:
        student = await db.get_user(grade.get("student_id"))
        if not student or student.get("intake") != intake:
            raise HTTPException(403, "grade_intake_out_of_scope")
    return grade


@router.patch("/grades/{grade_id}")
async def wa_grade_update(
    grade_id: str, body: academic_api.GradeUpdate,
    user=Depends(_perm_any("grades.manage", "grades.scoped")),
):
    await _grade_for_actor(grade_id, user)
    return await academic_api.grade_update(
        grade_id=grade_id, body=body, admin=user)


@router.delete("/grades/{grade_id}")
async def wa_grade_delete(
    grade_id: str,
    user=Depends(_perm_any("grades.manage", "grades.scoped")),
):
    await _grade_for_actor(grade_id, user)
    return await academic_api.grade_delete(grade_id=grade_id, admin=user)


# ═══════════════════════════════════════════════════════════
# 🌱 W13 / 💳 W14 — مدیریت رشد (ریفرال + پیگیری پرداخت)
# ═══════════════════════════════════════════════════════════

class GrowthConfigBody(BaseModel):
    ref: dict = {}
    dun: dict = {}


class GrowthReviewBody(BaseModel):
    approve: bool


@router.get("/growth/config")
async def wa_growth_config(user=Depends(_perm("subscription.manage"))):
    """خواندن کانفیگ رشد (ریفرال + dunning) با پیش‌فرض‌های امن."""
    import growth_rules as _gr
    ref_stored = await db.get_setting("ref_cfg", None)
    dun_stored = await db.get_setting("dun_cfg", None)
    return {
        "ref": _gr.merge_ref_config(
            ref_stored if isinstance(ref_stored, dict) else None),
        "dun": _gr.merge_dun_config(
            dun_stored if isinstance(dun_stored, dict) else None),
    }


@router.put("/growth/config")
async def wa_growth_config_update(body: GrowthConfigBody,
                                  user=Depends(_perm("subscription.manage"))):
    """به‌روزرسانی کانفیگ رشد (partial؛ اعتبارسنجی + audit اجباری)."""
    import growth_rules as _gr
    before_ref = await db.get_setting("ref_cfg", None) or {}
    before_dun = await db.get_setting("dun_cfg", None) or {}
    patch_ref = body.ref if isinstance(body.ref, dict) else {}
    patch_dun = body.dun if isinstance(body.dun, dict) else {}
    if not patch_ref and not patch_dun:
        raise HTTPException(422, "تغییری ارسال نشده")
    merged_ref = dict(before_ref)
    merged_ref.update(patch_ref)
    if "rewards" in patch_ref and isinstance(patch_ref["rewards"], dict):
        rw = dict((before_ref.get("rewards") or {}))
        for k, v in patch_ref["rewards"].items():
            if k in _gr.REWARD_TYPES and isinstance(v, dict):
                one = dict(rw.get(k) or {})
                one.update(v)
                rw[k] = one
        merged_ref["rewards"] = rw
    after_ref = _gr.merge_ref_config(merged_ref)
    after_dun = _gr.merge_dun_config({**before_dun, **patch_dun})
    await db.set_setting("ref_cfg", after_ref)
    await db.set_setting("dun_cfg", after_dun)
    try:
        await _audit(user["id"], "تغییر کانفیگ رشد (ریفرال/dunning)",
                     severity="HIGH", target_type="growth",
                     before={"ref": before_ref, "dun": before_dun},
                     after={"ref": after_ref, "dun": after_dun},
                     tags=["رشد", "ریفرال", "dunning", "پنل_وب"])
    except Exception:
        try:
            await db.set_setting("ref_cfg", before_ref)
            await db.set_setting("dun_cfg", before_dun)
        except Exception:
            pass
        raise HTTPException(500, "ثبت audit ناموفق بود؛ تغییر برگردانده شد")
    return {"ok": True, "ref": after_ref, "dun": after_dun}


@router.get("/growth/referrals")
async def wa_growth_referrals(status: str = Query(default=""),
                              inviter: int = Query(default=0),
                              skip: int = Query(default=0, ge=0),
                              limit: int = Query(default=20, ge=1, le=100),
                              user=Depends(
                                  _perm("subscription.manage"))):
    """فهرست دعوت‌ها (فیلتر وضعیت/دعوت‌کننده + صفحه‌بندی)."""
    if status and status not in ("counted", "flagged", "capped",
                                 "rejected"):
        raise HTTPException(422, "وضعیت نامعتبر")
    docs = await db.ref_list(inviter_id=inviter, status=status,
                             skip=skip, limit=limit)
    total = await db.ref_count(inviter_id=inviter, status=status)
    uids = {d.get("inviter_id") for d in docs} | \
        {d.get("invitee_id") for d in docs}
    names = {}
    try:
        users = await db.get_users_by_ids([u for u in uids if u])
        names = {u: (d or {}).get("name", "") for u, d in users.items()}
    except Exception:
        pass
    items = [{
        "id": str(d.get("_id")),
        "inviter_id": d.get("inviter_id"),
        "inviter_name": names.get(d.get("inviter_id"), ""),
        "invitee_id": d.get("invitee_id"),
        "invitee_name": names.get(d.get("invitee_id"), ""),
        "source": d.get("source", ""),
        "status": d.get("status", ""),
        "flag_reason": d.get("flag_reason", ""),
        "created_at": d.get("created_at", ""),
        "reward_register": bool(d.get("reward_register")),
        "reward_buy": bool(d.get("reward_buy")),
        "first_buy_at": d.get("invitee_first_buy_at"),
        "granted": d.get("granted") or {},
    } for d in docs]
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.post("/growth/referrals/{rid}/review")
async def wa_growth_review(rid: str, body: GrowthReviewBody,
                           user=Depends(_perm("subscription.manage"))):
    """تأیید/رد دستی دعوت مشکوک (تأیید → اعطای جوایز سررسیده)."""
    doc = await db.ref_set_status(rid, "counted" if body.approve
                                  else "rejected", user["id"])
    if not doc:
        raise HTTPException(404, "دعوت پیدا نشد یا قابل‌بازبینی نیست")
    granted_all = {}
    if body.approve and doc.get("status") == "counted":
        try:
            r1 = await db.ref_grant(doc, "register")
            granted_all["register"] = r1.get("granted", {})
            if doc.get("invitee_first_buy_at"):
                r2 = await db.ref_grant(doc, "buy")
                granted_all["buy"] = r2.get("granted", {})
            if granted_all.get("register") or granted_all.get("buy"):
                from referral import notify_inviter as _notify
                await _notify(int(doc["inviter_id"]),
                              {**granted_all.get("register", {}),
                               **granted_all.get("buy", {})},
                              "register")
        except Exception:
            pass
    try:
        await _audit(user["id"],
                     f"بازبینی دعوت: {'تأیید' if body.approve else 'رد'}",
                     severity="HIGH", target_id=str(doc.get("_id")),
                     target_type="referral",
                     target_label=f"{doc.get('inviter_id')}→"
                                  f"{doc.get('invitee_id')}",
                     tags=["رشد", "ریفرال", "بازبینی", "پنل_وب"])
    except Exception:
        pass
    return {"ok": True, "status": doc.get("status"),
            "granted": granted_all}


@router.get("/growth/stats")
async def wa_growth_stats(user=Depends(_perm("subscription.manage"))):
    """آمار یک‌نگاه رشد: ریفرال + پیگیری پرداخت."""
    return {
        "referral": await db.ref_global_stats(),
        "dunning": await db.dun_stats(),
    }
