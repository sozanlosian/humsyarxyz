"""احراز هویت امن Telegram Mini App با HMAC-SHA256."""
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException, Request

from database import db
from time_utils import TimeContractError, now_utc as _contract_now_utc, parse_machine_datetime


BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except (TypeError, ValueError):
    ADMIN_ID = 0

# 🛡 AUDIT-R1 — پنجره‌ی اعتبار امضا؛ به‌صورت env قابل تنظیم است تا در
# محیط‌هایی که ساعت سرور کشیده است یا flowهای کُند، بدون دیپلوی تازه
# بسته/باز شود. replay کامل در مدل Telegram WebApp حذف‌شدنی نیست (امضای
# stateless)، پس این عدد خودش «پنجره‌ی replay» است و پیش‌فرض یک ساعت نگه
# داشته شده تا سشن‌های وب‌ادمین نشکنند (sane ceiling = 24h).
try:
    INIT_DATA_MAX_AGE = max(30, min(int(os.getenv("INIT_DATA_MAX_AGE_SEC", "3600") or 3600), 86400))
except (TypeError, ValueError):
    INIT_DATA_MAX_AGE = 3600


# ── W1 Nonce (Replay) — best-effort, fails open if DB unavailable ──
# Stores hash(init_data) with TTL = INIT_DATA_MAX_AGE to reject replay.
# Nonce check is AFTER HMAC verification (never store unverified data).
_INIT_NONCE_TTL = INIT_DATA_MAX_AGE
try:
    _NONCE_ENABLED = os.getenv("INIT_NONCE_ENABLED", "0").strip().lower() not in ("0","false","no","off")
except: _NONCE_ENABLED = False
# If enabled, every init_data hash is stored once (TTL=INIT_DATA_MAX_AGE) and replay → 401.
# Disabled by default to allow Telegram's own re-sends (same initData on page reload).
# Enable with INIT_NONCE_ENABLED=1 when you need strict replay protection.

async def _check_init_nonce_once(init_data: str) -> None:
    """Strict once-only nonce using insert+DuplicateKeyError. Raises 401 on replay if DB available."""
    if not _NONCE_ENABLED or not init_data:
        return
    h = hashlib.sha256(init_data.encode("utf-8")).hexdigest()
    try:
        await db.init_nonces.insert_one({"_id": h, "at": utc_now(), "hash": h})
    except Exception as e:
        try:
            from pymongo.errors import DuplicateKeyError as DKE
            if isinstance(e, DKE):
                raise HTTPException(status_code=401, detail="init_data_reused")
        except HTTPException:
            raise
        except Exception:
            pass
        try:
            import logging as _lg
            _lg.getLogger("api.auth").debug(f"nonce check fail-open: {e}")
        except: pass

def _auth_error(detail: str = "invalid_init_data") -> HTTPException:
    return HTTPException(status_code=401, detail=detail)


def verify_telegram_init_data(init_data: str) -> dict:
    """Validate Telegram WebApp initData and return its user object.

    Telegram signs the decoded query-string values.  ``parse_qsl`` is used
    instead of manually splitting the string so encoded characters and plus
    signs are handled correctly.  No user-provided id is trusted before the
    signature has been verified.
    """
    if not BOT_TOKEN:
        raise HTTPException(status_code=500, detail="BOT_TOKEN not set")
    if not isinstance(init_data, str) or not init_data.strip():
        raise _auth_error("missing_init_data")

    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
        parsed = dict(pairs)
    except (TypeError, ValueError):
        raise _auth_error()

    received_hash = parsed.pop("hash", "")
    if not received_hash or len(received_hash) != 64:
        raise _auth_error()

    try:
        auth_date = int(parsed.get("auth_date", "0"))
    except (TypeError, ValueError):
        raise _auth_error()

    now = int(time.time())
    if auth_date <= 0 or auth_date > now + 60 or now - auth_date > INIT_DATA_MAX_AGE:
        raise _auth_error("init_data_expired")

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(parsed.items())
    )
    secret_key = hmac.new(
        b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256
    ).digest()
    computed_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise _auth_error()

    try:
        user = json.loads(parsed.get("user", "{}"))
    except (TypeError, json.JSONDecodeError):
        raise _auth_error("invalid_user_data")
    if not isinstance(user, dict) or not user.get("id"):
        raise _auth_error("invalid_user_data")
    return user


# ──────────────────────────────────────────────────────────
#  🖥️ موج WA — Web Admin Session (HttpOnly cookie)
#  مسیر initData عیناً حفظ شده و همیشه در اولویت است؛ اگر هدر
#  نبود و کوکی wa_session معتبر بود، همان dict کاربر ساخته می‌شود.
# ──────────────────────────────────────────────────────────
WA_SESSION_COOKIE = "wa_session"
WA_SESSION_TTL_H = 12


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def utc_now() -> datetime:
    """Compatibility alias for the global HUMSYAR time contract."""
    return _contract_now_utc()


def expiry_is_past(value, now: datetime | None = None) -> bool:
    """Read both legacy ISO-string expiries and new BSON datetime values.

    New documents use BSON datetimes so Mongo TTL indexes can physically remove
    expired OTP/session records. Legacy string records remain readable during
    rollout and are rejected in Python once expired.
    """
    now = now or utc_now()
    try:
        parsed = parse_machine_datetime(value)
    except (TimeContractError, TypeError, ValueError):
        return True
    return parsed <= parse_machine_datetime(now)


async def resolve_web_session(token: str) -> dict | None:
    """توکن خام کوکی را به سند سشن معتبر نگاشت می‌کند (expiry/revoke چک‌شده)."""
    if not token:
        return None
    doc = await db.web_admin_sessions.find_one({
        "_id": _hash_token(token),
        "revoked": False,
    })
    if not doc or expiry_is_past(doc.get("expires_at")):
        return None
    return doc


async def get_current_user(
    request: Request,
    x_init_data: str = Header(default="", alias="X-Init-Data"),
) -> dict:
    if not x_init_data:
        # 🖥️ WA — fallback سشن وب‌ادمین (فقط وقتی هدر غایب است)
        sess = await resolve_web_session(request.cookies.get(WA_SESSION_COOKIE, ""))
        if sess:
            uid = int(sess["uid"])
            try: request.state.user_id = uid
            except: pass
            db_user = await db.get_user(uid)
            if not db_user:
                raise HTTPException(status_code=403, detail="not_registered")
            if not db_user.get("approved"):
                raise HTTPException(status_code=403, detail="pending_approval")
            if db_user.get("suspended"):
                raise HTTPException(status_code=403, detail="suspended")
            return {"id": uid, "first_name": db_user.get("name", ""),
                    "_db": db_user, "_wa_session": sess}
        raise _auth_error("missing_init_data")
    tg_user = verify_telegram_init_data(x_init_data)
    # W1 — after HMAC verified, enforce once-only nonce (if enabled)
    try:
        await _check_init_nonce_once(x_init_data)
    except HTTPException:
        raise
    except Exception:
        pass
    try:
        uid = int(tg_user["id"])
    except (KeyError, TypeError, ValueError):
        raise _auth_error("invalid_user_data")
    try: request.state.user_id = uid
    except: pass

    db_user = await db.get_user(uid)
    if not db_user:
        raise HTTPException(status_code=403, detail="not_registered")
    if not db_user.get("approved"):
        raise HTTPException(status_code=403, detail="pending_approval")
    if db_user.get("suspended"):
        raise HTTPException(status_code=403, detail="suspended")
    return {**tg_user, "id": uid, "_db": db_user}


async def get_admin_user(user=Depends(get_current_user)) -> dict:
    if user["id"] != ADMIN_ID:
        raise HTTPException(status_code=403, detail="admin_only")
    return user


def require_perm(permission: str):
    """🛡 گیت مجوز RBAC — موج W8: thin-wrapper روی core.rbac.

    هر روتر جدید باید به‌جای چسبیدن به role/ADMIN_ID، از این کارخانه
    استفاده کند: Depends(require_perm('roles.manage'))
    تفویض به core/rbac — قرارداد واحد در هر ۳ لایه."""
    async def _guard(user=Depends(get_current_user)) -> dict:
        # W8 core path — واحد با Bot
        try:
            from core.rbac import has_permission
            if await has_permission(user["id"], permission):
                return user
        except Exception:
            if await db.has_perm(user["id"], permission):
                return user
        raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "forbidden"})

    _guard.__name__ = f"require_perm_{permission.replace('.', '_')}"
    return _guard


async def get_content_admin_user(user=Depends(get_current_user)) -> dict:
    """🌊 موج C1 — گیت پنل محتوا: هر دارنده‌ی scope معتبر عبور می‌کند:
    مالک/ادمین/ادمین ارشد محتوا (global) و ادمین محتوای ورودی خاص (scoped).
    scope محاسبه‌شده روی user['_scope'] سوار می‌شود تا endpointها با
    enforce_content_intake تصمیم نهایی را بگیرند — گیت فقط «ورود به
    پنل» است، سطح دسترسیِ هر عملیات در خود endpoint enforce می‌شود."""
    scope = await db.get_content_scope(user["id"])
    if not scope:
        raise HTTPException(status_code=403, detail="content_admin_only")
    user["_scope"] = scope
    return user


async def get_content_global_user(user=Depends(get_current_user)) -> dict:
    """فقط ادمین ارشد محتوا/مالک/ادمین — معادل دقیق رفتار قبلیِ
    get_content_admin_user برای بخش‌هایی که scope ندارند
    (schedule/grades/reports) — ادمین ورودی خاص همچنان ۴۰۳."""
    scope = await db.get_content_scope(user["id"])
    if not scope or scope.get("kind") != "global":
        raise HTTPException(status_code=403, detail="content_admin_only")
    user["_scope"] = scope
    return user


def resolve_content_intake(user: dict, requested=None) -> str:
    """تصمیم نهایی intake برای یک endpoint محتوا (§۱۰ spec):
      • global → intake درخواستی (پیش‌فرض '' = سراسری)
      • scoped → اگر intake درخواستی با scope مغایرت داشت ۴۰۳؛
        در غیر این صورت همیشه scope (نه چیزی که کلاینت فرستاده)
    """
    scope = user.get("_scope") or {"kind": "scoped", "intake": ""}
    if scope.get("kind") == "global":
        return (requested or "") if requested is not None else ""
    own = scope.get("intake") or ""
    if requested not in (None, "", own):
        raise HTTPException(status_code=403, detail="intake_out_of_scope")
    return own


def require_feature(feature: str):
    """🌊 W7 — کارخانه‌ی گیت فیچر: تنها نقطه‌ی اعمال سمت API.

    402 دسترسی / 429 سهمیه / 503 موقت — همیشه با {code, message, feature}.
    """
    async def _gate(user=Depends(get_current_user)) -> dict:
        from core.access import require_feature_access
        await require_feature_access(user["id"], feature)
        return user
    _gate.__name__ = f"require_feature_{feature}"
    return _gate


async def get_question_access_user(user=Depends(get_current_user)) -> dict:
    """Single server-side subscription gate for every student Question Bank API — W8 core."""
    try:
        from core.access import require_feature_access
        await require_feature_access(user["id"], "question_bank")
    except HTTPException:
        raise
    except Exception:
        from subscription import has_access
        if not await has_access(user["id"]):
            raise HTTPException(status_code=402, detail={"code": "SUB_REQUIRED", "message": "subscription_required"})
    return user


async def get_resource_access_user(user=Depends(get_current_user)) -> dict:
    """گیت اشتراک برای «منابع علوم پایه» و «رفرنس‌ها» — W8 core.

    دقیقاً همان قانونِ واحد ربات از هسته (core.access) اجرا می‌شود.
    کد خطا ساختاریافته: {code: SUB_REQUIRED, message} تا MiniApp با کد
    تصمیم بگیرد نه با تطبیق رشته فارسی.
    """
    try:
        from core.access import require_feature_access
        await require_feature_access(user["id"], "resources")
    except HTTPException:
        raise
    except Exception:
        from subscription import has_access
        if not await has_access(user["id"]):
            raise HTTPException(status_code=402, detail={"code": "SUB_REQUIRED", "message": "subscription_required"})
    return user


async def get_references_access_user(user=Depends(get_current_user)) -> dict:
    """🌊 W7 — گیت اشتراک رفرنس‌ها (جدا از منابع؛ سوییچ مستقل)."""
    try:
        from core.access import require_feature_access
        await require_feature_access(user["id"], "references")
    except HTTPException:
        raise
    except Exception:
        from subscription import has_access
        if not await has_access(user["id"]):
            raise HTTPException(status_code=402, detail={"code": "SUB_REQUIRED", "message": "subscription_required"})
    return user

