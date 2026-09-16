# -*- coding: utf-8 -*-
"""
🔐 هسته — دسترسی و اشتراک (واحد در Bot / API / MiniApp) — W8

تنها پیاده‌سازی قانون has_access کل محصول این‌جاست.
subscription.py و api/auth.py فقط thin-wrapper هستند و به همین ماژول تفویض می‌کنند.
ترتیب دقیق عین ربات سابق: enforce خاموش → allowed، ADMIN_ID → allowed، وگرنه sub_is_active.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import logging
import os
import time as _time
from database import db
from .errors import Code, DEFAULT_MESSAGE
from .features import FEATURE_CATALOG, default_policy

logger = logging.getLogger(__name__)

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
except Exception:
    ADMIN_ID = 0

@dataclass
class AccessResult:
    allowed: bool
    code: Optional[str] = None
    message: str = ""
    is_owner: bool = False

async def has_access(uid: int) -> AccessResult:
    """قرارداد واحد has_access با code ماشین‌خوان.

    🌊 W7 — معنای legacy (اشتراک‌اجباری سراسری) حالا از پالیسی
    question_bank خوانده می‌شود؛ migration نسخه ۴ مقدار سوییچ قدیمی را
    به پالیسی‌ها منتقل کرده است. صداکننده‌های واقعی فیچر صریح پاس می‌دهند.
    """
    res = await check_feature(int(uid), "question_bank")
    return AccessResult(allowed=res.allowed, code=res.code,
                        message=res.message, is_owner=res.is_owner)

# سازگار با کد قدیم که bool انتظار داشت
async def has_access_bool(uid: int) -> bool:
    return (await has_access(uid)).allowed

async def require_access(uid: int):
    res = await require_feature_access(int(uid), "question_bank")
    return res


# ══════════════════════════════════════════════════
#  🌊 W7 — Feature Gating مرکزی (FREE NOW, PAY LATER)
# ══════════════════════════════════════════════════

@dataclass
class FeatureAccess:
    allowed: bool
    reason: str = ""            # entitled|subscription_required|...
    code: Optional[str] = None  # Code.* ماشین‌خوان برای MiniApp
    message: str = ""           # فارسی نمایشی (قابل تغییر بدون شکستن کلاینت)
    feature: str = ""
    quota_remaining: Optional[int] = None  # None = نامحدود/نامربوط
    trial: bool = False
    is_owner: bool = False
    http_status: int = 402      # 402 دسترسی، 429 سهمیه، 503 خطای موقت


# AI سهمیه‌ی تخصصی خودش را دارد (W6)؛ check_feature فقط flag/access را می‌سنجد
# و peek سهمیه را None برمی‌گرداند — خطای سهمیه از همان مسیر قبلی (429) می‌آید.
_AI_SPECIAL = ("ai_chat", "ai_image", "ai_practice")

_POLICY_TTL_S = 60
_POLICY_CACHE: dict = {}  # feature → (policy, monotonic_ts)


def invalidate_policy_cache(feature: str | None = None) -> None:
    """ابطال کش پالیسی — نویسنده‌ها (ادمین) بعد از ذخیره صدا می‌زنند."""
    if feature:
        _POLICY_CACHE.pop(feature, None)
    else:
        _POLICY_CACHE.clear()


def _effective_access(policy: dict) -> str:
    """پالیسی زمان‌بندی‌شده: اگر effective_from رسیده، pending اعمال می‌شود."""
    try:
        pend, eff = policy.get("pending_access"), policy.get("effective_from")
        if pend and eff:
            dt = datetime.fromisoformat(str(eff))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) >= dt:
                return str(pend)
    except Exception:
        pass
    return str(policy.get("access") or "free")


async def _load_policy(feature: str):
    """خوانش پالیسی با کش؛ شکست ⇒ کش کهنه، وگرنه None (fail-safe در caller)."""
    now = _time.monotonic()
    hit = _POLICY_CACHE.get(feature)
    if hit and hit[1] > now:
        return dict(hit[0])
    try:
        doc = await db.get_feature_policy(feature)
    except Exception as e:
        logger.warning("feature policy load failed for %s: %s", feature, e)
        if hit:
            return dict(hit[0])  # کش کهنه بهتر از تصمیم کور است
        return None
    if not doc:
        # فیچر تازه‌ی کاتالوگ که هنوز ذخیره نشده: پیش‌فرض درون‌حافظه‌ای
        # (بدون write در مسیر خوانش؛ با اولین ذخیره‌ی ادمین ماندگار می‌شود)
        return default_policy(feature)
    policy = dict(doc)
    _POLICY_CACHE[feature] = (dict(doc), now + _POLICY_TTL_S)
    return policy


async def _quota_peek(uid: int, feature: str, policy: dict) -> Optional[int]:
    """باقی‌مانده‌ی سهمیه‌ی ژنریک؛ None = نامحدود/تخصصی/خطا (fail-open در peek)."""
    try:
        q = policy.get("quota") or {}
        kind, limit = q.get("kind") or "none", int(q.get("limit") or 0)
    except (TypeError, ValueError):
        return None
    if kind not in ("daily", "monthly") or limit <= 0:
        return None
    if feature in _AI_SPECIAL:
        return None
    try:
        used = await db.feature_usage_get(uid, feature, kind)
    except Exception as e:
        logger.warning("quota peek failed %s/%s: %s", uid, feature, e)
        return None
    return max(0, limit - int(used or 0))


async def _log_event_best_effort(feature: str, event: str, uid: int,
                                 extra: dict | None = None) -> None:
    try:
        await db.log_feature_event(feature, event, uid, extra or {})
    except Exception:
        pass


async def check_feature(uid: int, feature: str) -> FeatureAccess:
    """🌊 W7 — تصمیم مرکزی دسترسی. ترتیب لایه‌ها:
    flag (kill switch) ← access mode ← user/trial/plan ← quota (peek)."""
    uid, feature = int(uid), str(feature)
    if feature not in FEATURE_CATALOG:
        logger.error("check_feature: unknown feature %s", feature)
        return FeatureAccess(allowed=False, reason="unknown_feature",
                             code=Code.FORBIDDEN, message=DEFAULT_MESSAGE[Code.FORBIDDEN],
                             feature=feature, http_status=403)
    owner = bool(ADMIN_ID) and uid == ADMIN_ID

    policy = await _load_policy(feature)
    if policy is None:
        # DB در دسترس نیست و کش هم نداریم: fail-safe
        return FeatureAccess(allowed=False, reason="policy_unavailable",
                             code=Code.POLICY_UNAVAILABLE,
                             message=DEFAULT_MESSAGE[Code.POLICY_UNAVAILABLE],
                             feature=feature, http_status=503)
    if not policy.get("enabled", True) or _effective_access(policy) == "disabled":
        await _log_event_best_effort(feature, "feature_denied", uid,
                                     {"reason": "feature_disabled"})
        return FeatureAccess(allowed=False, reason="feature_disabled",
                             code=Code.FEATURE_DISABLED,
                             message=DEFAULT_MESSAGE[Code.FEATURE_DISABLED],
                             feature=feature, http_status=402)
    access = _effective_access(policy)
    if access == "admin_only" and not owner:
        await _log_event_best_effort(feature, "feature_denied", uid,
                                     {"reason": "admin_only"})
        return FeatureAccess(allowed=False, reason="admin_only",
                             code=Code.ADMIN_ONLY,
                             message=DEFAULT_MESSAGE[Code.ADMIN_ONLY],
                             feature=feature, http_status=402)
    if owner or access == "free":
        # مالک: بای‌پس entitlement و سهمیه (ولی نه kill switch — بالا اعمال شد)
        return FeatureAccess(allowed=True, reason="entitled", feature=feature,
                             is_owner=owner,
                             quota_remaining=None if owner else
                             await _quota_peek(uid, feature, policy))

    # ── access == subscription ──
    try:
        sub = await db.sub_get(uid)
    except Exception as e:
        logger.warning("check_feature sub read failed %s: %s", uid, e)
        return FeatureAccess(allowed=False, reason="policy_unavailable",
                             code=Code.POLICY_UNAVAILABLE,
                             message=DEFAULT_MESSAGE[Code.POLICY_UNAVAILABLE],
                             feature=feature, http_status=503)
    active = False
    try:
        active = await db.sub_is_active(uid)
    except Exception:
        active = False
    if not active:
        status = str((sub or {}).get("status") or "").lower()
        if status == "pending":
            code = Code.SUB_PENDING
        elif status in ("expired", "cancelled", "revoked"):
            code = Code.SUB_EXPIRED
        else:
            code = Code.SUB_REQUIRED
        await _log_event_best_effort(feature, "feature_denied", uid,
                                     {"reason": code})
        numa = "subscription_required" if code == Code.SUB_REQUIRED else code.lower()
        return FeatureAccess(allowed=False, reason=numa, code=code,
                             message=DEFAULT_MESSAGE[code],
                             feature=feature, http_status=402)
    trial = str((sub or {}).get("source") or "") == "trial"
    if trial and not policy.get("trial_allowed", True):
        await _log_event_best_effort(feature, "feature_denied", uid,
                                     {"reason": "trial_excluded"})
        return FeatureAccess(allowed=False, reason="trial_excluded",
                             code=Code.SUB_REQUIRED,
                             message="🔒 دوره‌ی آزمایشی شامل این قابلیت نیست.",
                             feature=feature, trial=True, http_status=402)
    # entitlement پلن (پلن‌های legacy بدون نقشه = دسترسی کامل)
    try:
        plan = await db.plan_for_sub(sub or {})
    except Exception:
        plan = None
    if plan:
        ent = plan.get("entitlements") or {}
        if isinstance(ent, dict) and ent and ent.get(feature) is False:
            await _log_event_best_effort(feature, "feature_denied", uid,
                                         {"reason": "plan_excluded"})
            return FeatureAccess(allowed=False, reason="plan_excluded",
                                 code=Code.PLAN_EXCLUDES_FEATURE,
                                 message=DEFAULT_MESSAGE[Code.PLAN_EXCLUDES_FEATURE],
                                 feature=feature, trial=trial, http_status=402)
    remaining = await _quota_peek(uid, feature, policy)
    if remaining == 0:
        await _log_event_best_effort(feature, "quota_exhausted", uid, {})
        return FeatureAccess(allowed=False, reason="quota_exhausted",
                             code=Code.QUOTA_EXHAUSTED,
                             message=DEFAULT_MESSAGE[Code.QUOTA_EXHAUSTED],
                             feature=feature, trial=trial, http_status=429)
    if trial:
        await _log_event_best_effort(feature, "trial_feature_used", uid, {})
    return FeatureAccess(allowed=True, reason="entitled", feature=feature,
                         quota_remaining=remaining, trial=trial)


async def require_feature_access(uid: int, feature: str) -> FeatureAccess:
    """نسخه‌ی raiseکننده برای API: 402 دسترسی / 429 سهمیه / 503 موقت."""
    res = await check_feature(int(uid), feature)
    if not res.allowed:
        from fastapi import HTTPException
        raise HTTPException(status_code=res.http_status, detail={
            "code": res.code, "message": res.message, "feature": feature})
    return res
