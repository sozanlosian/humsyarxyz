# -*- coding: utf-8 -*-
"""
🔍 HUMSYAR Audit & Observability — Production-Grade Refactor
=============================================================
* نسخه نهایی: بازطراحی کامل Logging / Audit / Activity Tracking
* مطابق با Mission Spec §5-§68  —  Zero Blind Spot, Reliability, Observability

این ماژول «قلب» سیستم جدید است:
  • Audit Event Schema استاندارد (event_id, correlation_id, actor/target, before/after, severity...)
  • Sanitizer مرکزی (Redaction)
  • Correlation / Request ID
  • HTML Safety
  • Telegram Delivery Outbox + Retry + Recovery + Health
  • Category / Severity / Action Naming استاندارد
  • Application Log vs Audit Log جداسازی
  • Backward Compatibility با send_audit_log / db.log_action موجود

همه‌ی ماژول‌ها باید به‌جای فراخوانی پراکنده‌ی logger یا db مستقیماً از
این قرارداد استفاده کنند — اما لایه‌ی سازگاری Legacy حفظ شده تا هیچ
Feature فعلی نشکند.
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# ─────────── Time ───────────
try:
    from time_utils import now_utc, utc_now_iso, TEHRAN, format_datetime_fa
except Exception:  # pragma: no cover
    from zoneinfo import ZoneInfo
    TEHRAN = ZoneInfo("Asia/Tehran")
    def now_utc():
        return datetime.now(timezone.utc)
    def utc_now_iso():
        return now_utc().isoformat()
    def format_datetime_fa(v, long=False, seconds=False, fallback="—"):
        try:
            return v.astimezone(TEHRAN).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return str(v)

try:
    from request_context import current_request_id
except Exception:
    from contextvars import ContextVar
    current_request_id = ContextVar("humsyar_request_id", default=None)

logger = logging.getLogger("audit")
app_logger = logging.getLogger("app")  # Application Log separation

# ══════════════════════════════════════════════════
#  1) Severity — استاندارد ۶سطحه (§17)
# ══════════════════════════════════════════════════
SEVERITY_LEVELS = ("DEBUG", "INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")
SEVERITY_ORDER = {s: i for i, s in enumerate(SEVERITY_LEVELS)}
SEVERITY_META = {
    "DEBUG":    {"icon": "⚪", "label": "DEBUG"},
    "INFO":     {"icon": "🟢", "label": "INFO"},
    "LOW":      {"icon": "🔵", "label": "LOW"},
    "MEDIUM":   {"icon": "🟡", "label": "MEDIUM"},
    "HIGH":     {"icon": "🟠", "label": "HIGH"},
    "CRITICAL": {"icon": "🔴", "label": "CRITICAL"},
}
# سازگاری با legacy WARNING → MEDIUM
_LEGACY_SEV_MAP = {"WARNING": "MEDIUM", "WARN": "MEDIUM", "ERROR": "HIGH"}

def normalize_severity(s: str) -> str:
    if not s:
        return "INFO"
    u = str(s).strip().upper()
    if u in _LEGACY_SEV_MAP:
        u = _LEGACY_SEV_MAP[u]
    return u if u in SEVERITY_LEVELS else "INFO"

# ══════════════════════════════════════════════════
#  2) Category — استاندارد (§18)
# ══════════════════════════════════════════════════
CATEGORIES = (
    "admin", "content", "user", "subscription", "payment",
    "ai", "notification", "ticket", "qbank", "reference",
    "system", "security", "database", "integration", "job",
    "grades", "schedule", "backup",
)
def normalize_category(c: str) -> str:
    c = (c or "system").strip().lower()
    return c if c in CATEGORIES else "system"

# ── Unified category → group/icon/title (single source of truth §18-§20) ──
# مدیریتی → log_group_admin / 🛡  |  محتوایی → log_group_content / 🎓
_ADMIN_CATS = {"admin","security","system","ai","job","database","integration","subscription","payment","backup","notification"}
_CONTENT_CATS = {"content","qbank","reference","grades","schedule","ticket"}
# user → مدیریتی (چون مدیریت کاربران است)، اما قابل تنظیم
def get_category_meta(category: str) -> tuple[str, str, str]:
    """return (group_key, icon, title) — unified for message + delivery."""
    c = normalize_category(category)
    if c in _ADMIN_CATS or c == "user":  # user management logs are admin-visible
        return ("log_group_admin", "🛡", "گزارش فعالیت مدیریتی")
    if c in _CONTENT_CATS:
        return ("log_group_content", "🎓", "گزارش فعالیت محتوا")
    # fallback — system-like → admin
    if c in ("admin","security","system"):
        return ("log_group_admin", "🛡", "گزارش فعالیت مدیریتی")
    return ("log_group_admin", "🛡", "گزارش فعالیت")

# ══════════════════════════════════════════════════
#  3) Action Naming — dot-notation (§19)
#     action = "content.created"   (پایدار برای query)
#     display_action = "ایجاد محتوا" (فارسی برای UI)
# ══════════════════════════════════════════════════
ACTION_LABEL_FA = {
    # content
    "content.created": "ایجاد محتوا",
    "content.updated": "ویرایش محتوا",
    "content.deleted": "حذف محتوا",
    "content.reordered": "تغییر ترتیب محتوا",
    "content.moved": "انتقال محتوا",
    "content.uploaded": "آپلود محتوا",
    "content.replaced": "جایگزینی محتوا",
    "content.forked": "ساخت نسخه اختصاصی",
    "content.unforked": "بازگردانی نسخه اختصاصی",
    # lesson/session
    "lesson.created": "ایجاد درس",
    "lesson.updated": "ویرایش درس",
    "lesson.deleted": "حذف درس",
    "lesson.reordered": "تغییر ترتیب درس",
    "session.created": "ایجاد جلسه",
    "session.updated": "ویرایش جلسه",
    "session.deleted": "حذف جلسه",
    # reference
    "reference.created": "ایجاد رفرنس",
    "reference.updated": "ویرایش رفرنس",
    "reference.deleted": "حذف رفرنس",
    "reference.reordered": "تغییر ترتیب رفرنس",
    # qbank
    "qbank.question_created": "ایجاد سوال",
    "qbank.question_updated": "ویرایش سوال",
    "qbank.question_deleted": "حذف سوال",
    "qbank.question_published": "انتشار سوال",
    "qbank.import_started": "شروع درون‌ریزی",
    "qbank.import_completed": "اتمام درون‌ریزی",
    # admin / rbac
    "admin.role_changed": "تغییر نقش ادمین",
    "admin.permission_changed": "تغییر دسترسی",
    "admin.scope_changed": "تغییر حوزه دسترسی",
    "admin.created": "افزودن ادمین",
    "admin.removed": "حذف ادمین",
    "admin.login": "ورود ادمین",
    "admin.unauthorized": "تلاش دسترسی غیرمجاز",
    # ai
    "ai.request_started": "شروع درخواست هوش مصنوعی",
    "ai.request_completed": "اتمام درخواست هوش مصنوعی",
    "ai.request_failed": "خطای درخواست هوش مصنوعی",
    "ai.model_changed": "تغییر مدل AI",
    "ai.provider_changed": "تغییر ارائه‌دهنده AI",
    "ai.api_key_changed": "تغییر کلید API",
    "ai.system_prompt_changed": "تغییر پرامپت سیستم",
    "ai.persona_changed": "تغییر پرسونا",
    "ai.enabled": "فعال‌سازی AI",
    "ai.disabled": "غیرفعال‌سازی AI",
    "ai.limit_changed": "تغییر محدودیت AI",
    "ai.image_generated": "تولید تصویر AI",
    "ai.image_failed": "خطای تولید تصویر",
    # subscription
    "subscription.created": "ایجاد اشتراک",
    "subscription.renewed": "تمدید اشتراک",
    "subscription.extended": "تمدید دستی اشتراک",
    "subscription.expired": "انقضای اشتراک",
    "subscription.cancelled": "لغو اشتراک",
    "subscription.revoked": "ابطال اشتراک",
    "subscription.granted": "اعطای اشتراک",
    # payment
    "payment.created": "ایجاد پرداخت",
    "payment.callback_received": "دریافت Callback پرداخت",
    "payment.verified": "تأیید پرداخت",
    "payment.rejected": "رد پرداخت",
    "payment.failed": "خطای پرداخت",
    "payment.duplicate": "پرداخت تکراری",
    "payment.refund": "بازگشت وجه",
    # notification
    "notification.queued": "صف اعلان",
    "notification.sent": "ارسال اعلان",
    "notification.failed": "خطای اعلان",
    "notification.retry": "تلاش مجدد اعلان",
    "notification.permanent_failure": "شکست قطعی اعلان",
    "broadcast.campaign_created": "ایجاد کمپین",
    "broadcast.campaign_started": "شروع کمپین",
    "broadcast.campaign_completed": "اتمام کمپین",
    # ticket / reports
    "ticket.created": "ایجاد تیکت",
    "ticket.replied": "پاسخ تیکت",
    "ticket.closed": "بستن تیکت",
    "ticket.reopened": "بازگشایی تیکت",
    "report.created": "ایجاد گزارش",
    "report.resolved": "حل گزارش",
    # system / job
    "system.startup": "راه‌اندازی سیستم",
    "system.shutdown": "خاموشی سیستم",
    "system.job_started": "شروع Job",
    "system.job_completed": "اتمام Job",
    "system.job_failed": "خطای Job",
    "system.db_failure": "خطای دیتابیس",
    "system.maintenance_enabled": "فعال‌سازی حالت تعمیر",
    # security
    "security.unauthorized": "دسترسی غیرمجاز",
    "security.forbidden": "عملیات ممنوع",
    "security.rate_limited": "محدودیت نرخ",
    "security.invalid_auth": "احراز هویت نامعتبر",
}

def action_display(action: str) -> str:
    return ACTION_LABEL_FA.get(action, action)

# ══════════════════════════════════════════════════
#  4) Actor Type (§6)
# ══════════════════════════════════════════════════
ACTOR_TYPES = ("USER", "ADMIN", "SUPER_ADMIN", "CONTENT_ADMIN", "SYSTEM", "SCHEDULED_JOB", "WEBHOOK", "BOT")
def normalize_actor_type(t: str) -> str:
    u = (t or "USER").strip().upper()
    return u if u in ACTOR_TYPES else "USER"

# ══════════════════════════════════════════════════
#  5) Sanitizer مرکزی — §9 (§22 HTML Safety هم اینجا)
# ══════════════════════════════════════════════════
# کلیدهای حساس — هر فیلدی که نامش شامل یکی از این‌ها باشد redact می‌شود
SENSITIVE_KEYS = (
    "api_key", "apikey", "api-key", "secret", "password", "passwd",
    "token", "jwt", "cookie", "session", "authorization", "auth",
    "bot_token", "db_uri", "mongodb_uri", "credential", "private_key",
    "client_secret", "access_token", "refresh_token",
)
# الگوهای مقداری
_SENSITIVE_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9]{10,}|sk-proj-[A-Za-z0-9_-]{10,}|"
    r"gh[pousr]_[A-Za-z0-9_]{10,}|"
    r"Bearer\s+[A-Za-z0-9\-\._~\+\/]+=*)",
    re.IGNORECASE,
)
REDACTED = "[REDACTED]"

def _is_sensitive_key(k: str) -> bool:
    lk = str(k).lower()
    return any(s in lk for s in SENSITIVE_KEYS)

def sanitize_value(v: Any) -> Any:
    """Redact حساسیت + truncate بسیار طولانی‌ها."""
    if v is None:
        return None
    if isinstance(v, dict):
        return {kk: (REDACTED if _is_sensitive_key(kk) else sanitize_value(vv)) for kk, vv in v.items()}
    if isinstance(v, list):
        return [sanitize_value(x) for x in v[:50]]
    s = str(v)
    if _is_sensitive_key(s):
        return REDACTED
    # اگر مقدار شبیه secret است
    if _SENSITIVE_VALUE_RE.search(s):
        return REDACTED
    # redact طول‌های مشکوک توکن‌مانند (>60 کاراکتر بدون فاصله)
    if len(s) > 60 and " " not in s and re.match(r"^[A-Za-z0-9_\-\.]+$", s):
        # احتمال توکن — نیمه را بپوشان
        return s[:4] + "…[REDACTED]…" + s[-4:] if len(s) > 20 else REDACTED
    if len(s) > 2000:
        return s[:2000] + "…(truncated)"
    return v

def sanitize_audit_data(data: Any) -> Any:
    """Sanitizer عمومی — برای before/after/metadata/details."""
    if data is None:
        return None
    if isinstance(data, dict):
        return sanitize_value(data)
    if isinstance(data, str):
        #details ممکن است شامل کلید حساس باشد
        if any(k in data.lower() for k in ("api_key", "token", "password", "secret")):
            # اگر کل details شامل secret است، redact خطی
            return _SENSITIVE_VALUE_RE.sub(REDACTED, data)
        return sanitize_value(data)
    return sanitize_value(data)

def html_escape(v: Any) -> str:
    """§22 — HTML Safety مرکزی، از Duplicate Escape جلوگیری با unescape اول."""
    s = str(v) if v is not None else ""
    # اگر قبلاً escape شده بود، decode کن تا دوبار escape نشود
    s = html.unescape(s)
    return html.escape(s, quote=True)

# ══════════════════════════════════════════════════
#  6) Correlation / Request / Event ID (§10-§11)
# ══════════════════════════════════════════════════
def new_event_id() -> str:
    return uuid.uuid4().hex  # 32 hex — idempotency key

def new_correlation_id() -> str:
    """
    HY-YYYYMMDD-XXXXXX — قابل جستجو، قابل مرتب‌سازی زمانی.
    هر User Action یک correlation_id می‌گیرد؛ تمام مراحل همان عملیات
    (Click → API → Permission → DB → Notification → Audit) یکسان است.
    """
    today = datetime.now(TEHRAN).strftime("%Y%m%d")
    rand = uuid.uuid4().hex[:6].upper()
    return f"HY-{today}-{rand}"

def new_request_id() -> str:
    return uuid.uuid4().hex[:16]

def get_request_id() -> Optional[str]:
    try:
        return current_request_id.get()
    except Exception:
        return None

def get_correlation_id(explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit
    try:
        cid = current_request_id.get()
        if cid:
            return cid
    except Exception:
        pass
    return new_correlation_id()

# ══════════════════════════════════════════════════
#  7) Telegram Delivery Classification (§15)
# ══════════════════════════════════════════════════
RETRYABLE_ERRORS = (
    "timeout", "timed out", "network", "connection", "retryafter",
    "too many requests", "5xx", "502", "503", "504", "temporarily unavailable",
    "telegram temporary", "flood", "retry_after",
)
NON_RETRYABLE_ERRORS = (
    "chat not found", "bot was kicked", "bot was blocked", "bot removed",
    "unauthorized", "forbidden", "chat_id is empty", "invalid message",
    "message is not modified", "bad request", "can't parse entities",
    "message text is empty", "message to delete not found", "peer_id_invalid",
)

def classify_telegram_error(err: str) -> str:
    """return: 'retryable' | 'non_retryable' | 'unknown'"""
    e = (err or "").lower()
    for pat in NON_RETRYABLE_ERRORS:
        if pat in e:
            return "non_retryable"
    for pat in RETRYABLE_ERRORS:
        if pat in e:
            return "retryable"
    if "retryafter" in e or "retry_after" in e or "429" in e:
        return "retryable"
    # پیش‌فرض: خطای ناشناخته را retryable فرض می‌کنیم ولی با backoff محدود
    return "retryable"

# Retry policy
MAX_RETRIES = 5
BASE_BACKOFF_SEC = 5
MAX_BACKOFF_SEC = 300

def next_retry_delay(attempt: int, retry_after: Optional[int] = None) -> int:
    if retry_after and retry_after > 0:
        return min(retry_after + 2, MAX_BACKOFF_SEC)
    # exponential backoff + jitter
    delay = BASE_BACKOFF_SEC * (2 ** min(attempt, 4))
    # jitter 0.8..1.2
    import random
    delay = int(delay * (0.8 + random.random() * 0.4))
    return min(delay, MAX_BACKOFF_SEC)

# ══════════════════════════════════════════════════
#  8) Audit Event Schema — §5
# ══════════════════════════════════════════════════
def build_audit_event(
    *,
    event_id: Optional[str] = None,
    actor_id: Any = 0,
    actor_name: str = "نامشخص",
    actor_role: str = "نامشخص",
    actor_type: str = "USER",
    module: str = "System",
    category: str = "system",
    action: str = "system.unknown",
    severity: str = "INFO",
    target_type: str = "",
    target_id: str = "",
    target_label: str = "",
    before: Optional[dict] = None,
    after: Optional[dict] = None,
    result: str = "SUCCESS",
    status: str = "SUCCESS",
    source: str = "bot",  # bot | miniapp | webadmin | api | job | system
    channel: str = "telegram",
    request_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    metadata: Optional[dict] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    tags: Optional[list] = None,
    details: str = "",
    target_context: Optional[dict] = None,  # intake/course/lesson/session parent
) -> dict:
    """ساخت رویداد استاندارد — تابع خالص بدون I/O."""
    now = now_utc()
    ts_iso = now.isoformat()
    # Tehran display — یکپارچه با time_utils (شمسی، Asia/Tehran)
    try:
        ts_tehran = now.astimezone(TEHRAN).isoformat()
    except Exception:
        ts_tehran = ts_iso
    try:
        ts_tehran_str = format_datetime_fa(now, long=True)
    except Exception:
        try:
            ts_tehran_str = now.astimezone(TEHRAN).strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception:
            ts_tehran_str = ts_iso

    # Normalize
    severity_n = normalize_severity(severity)
    category_n = normalize_category(category)

    # Sanitization — هرگز secrets ذخیره نشود
    before_s = sanitize_audit_data(before) if before else None
    after_s = sanitize_audit_data(after) if after else None
    metadata_s = sanitize_audit_data(metadata) if metadata else {}
    details_s = sanitize_audit_data(details) if details else ""
    target_label_s = sanitize_audit_data(target_label) if target_label else ""
    error_msg_s = sanitize_audit_data(error_message) if error_message else None

    # before/after برای جستجوی سریع به‌صورت changes نیز
    changes = []
    if before_s or after_s:
        b = before_s or {}
        a = after_s or {}
        if isinstance(b, dict) and isinstance(a, dict):
            for k in list(a.keys()) + [kk for kk in b.keys() if kk not in a]:
                changes.append({"field": k, "before": b.get(k, "—"), "after": a.get(k, "—")})

    doc = {
        "event_id": event_id or new_event_id(),
        "timestamp": ts_iso,
        "timestamp_tehran": ts_tehran,
        "timestamp_tehran_str": ts_tehran_str,
        "actor": {
            "id": int(actor_id) if str(actor_id).lstrip("-").isdigit() else actor_id,
            "name": html_escape(actor_name) if False else str(actor_name)[:200],  # ذخیره خام + sanitize قبلی، escape فقط در نمایش
            "role": str(actor_role)[:100],
            "type": normalize_actor_type(actor_type),
        },
        "module": str(module)[:100],
        "category": category_n,
        "action": str(action)[:200],
        "display_action": action_display(str(action)),
        "severity": severity_n,
        "target": {
            "type": str(target_type)[:100] if target_type else "",
            "id": str(target_id)[:200] if target_id else "",
            "label": str(target_label_s)[:500] if target_label_s else "",
            "context": sanitize_audit_data(target_context) if target_context else {},
        },
        "before": before_s,
        "after": after_s,
        "changes": changes,
        "result": str(result)[:50] if result else "SUCCESS",
        "status": str(status)[:50] if status else "SUCCESS",
        "source": str(source)[:50],
        "channel": str(channel)[:50],
        "request_id": request_id or get_request_id() or new_request_id(),
        "correlation_id": correlation_id or get_correlation_id(),
        "ip": str(ip)[:100] if ip else None,
        "user_agent": str(user_agent)[:500] if user_agent else None,
        "metadata": metadata_s,
        "details": str(details_s)[:4000] if details_s else "",
        "error_code": str(error_code)[:100] if error_code else None,
        "error_message": str(error_msg_s)[:2000] if error_msg_s else None,
        "tags": [str(t)[:100] for t in (tags or [])][:20],
        "created_at": ts_iso,
        # Delivery tracking (§41)
        "telegram_delivery_status": "PENDING",
        "telegram_message_id": None,
        "telegram_chat_id": None,
        "telegram_sent_at": None,
        "telegram_error": None,
        "audit_version": 2,
    }
    return doc

# ══════════════════════════════════════════════════
#  9) Telegram Message Builder — §20 §21 §22
#     حرفه‌ای، ثابت، HTML-Safe، تگ‌دار، خلاصه
# ══════════════════════════════════════════════════
def build_telegram_audit_text(event: dict) -> str:
    """
    پیام گروه لاگ — خلاصه ولی کامل:
      چه کسی / چه نقشی / چه کاری / روی چه چیزی / چه زمانی / اهمیت / شناسه‌ها
    before/after کامل در DB می‌ماند؛ در تلگرام فقط خلاصه.
    """
    sev = SEVERITY_META.get(event.get("severity", "INFO"), SEVERITY_META["INFO"])
    cat = event.get("category", "system")
    _gkey, cat_icon, cat_title = get_category_meta(cat)

    actor = event.get("actor") or {}
    target = event.get("target") or {}
    mod = event.get("module", "")
    # ترجمه ماژول
    try:
        from database import db as _db
        mod_fa = _db.MODULE_LABELS_FA.get(mod, mod)
    except Exception:
        mod_fa = mod

    # زمان تهران — یکپارچه شمسی (time_utils)
    raw_ts = event.get("timestamp_tehran") or event.get("timestamp") or event.get("timestamp_tehran_str") or ""
    try:
        ts = format_datetime_fa(raw_ts, long=True) if raw_ts else (event.get("timestamp_tehran_str") or "")
        # اگر format_datetime_fa مقدار fallback برگرداند و raw_ts همان strftime قدیمی بود، به همان اکتفا کن
        if ts == "—" and event.get("timestamp_tehran_str"):
            ts = event.get("timestamp_tehran_str")
    except Exception:
        ts = event.get("timestamp_tehran_str") or event.get("timestamp", "")

    lines = [
        f"{cat_icon} <b>{html_escape(cat_title)}</b>",
        "",
        "━━━━━━━━━━━━━━━━",
        f"🕒 <b>زمان</b>",
        html_escape(ts),
        "",
        "👤 <b>انجام‌دهنده</b>",
        f"• نام: {html_escape(actor.get('name', 'نامشخص'))}",
        f"• نقش: {html_escape(actor.get('role', 'نامشخص'))}",
        f"• شناسه: <code>{html_escape(actor.get('id',''))}</code>",
        "",
        "⚡ <b>عملیات</b>",
        html_escape(event.get("display_action") or event.get("action", "")),
    ]

    if target.get("label") or target.get("id"):
        lines += ["", "🎯 <b>هدف</b>"]
        if target.get("label"):
            lines.append(f"• عنوان: {html_escape(target['label'])}")
        if target.get("id"):
            lines.append(f"• شناسه: <code>{html_escape(target['id'])}</code>")
        # context parent اگر باشد
        ctx = target.get("context") or {}
        if isinstance(ctx, dict) and ctx:
            for k in ("intake", "course", "subject", "lesson", "session", "category"):
                if ctx.get(k):
                    lines.append(f"• {html_escape(k)}: {html_escape(ctx[k])}")

    if mod_fa:
        lines += ["", "📂 <b>بخش</b>", html_escape(mod_fa)]

    details = event.get("details") or ""
    if details:
        # HTML safety قبلاً sanitize شده؛ دوباره escape برای نمایش
        lines += ["", "📝 <b>جزئیات</b>", html_escape(details[:800])]

    # before/after خلاصه (حداکثر 3 فیلد)
    changes = event.get("changes") or []
    if changes:
        lines += ["", "🔄 <b>تغییرات</b>"]
        for ch in changes[:3]:
            lines.append(f"• {html_escape(ch.get('field',''))}: {html_escape(ch.get('before','—'))} ← {html_escape(ch.get('after','—'))}")
        if len(changes) > 3:
            lines.append(f"<i>… و {len(changes)-3} فیلد دیگر در دیتابیس</i>")

    # نتیجه عملیات vs تحویل لاگ (§12 — تفکیک)
    result = event.get("result", "SUCCESS")
    status = event.get("status", "SUCCESS")
    if result != "SUCCESS" or status != "SUCCESS":
        lines += ["", f"📌 <b>نتیجه عملیات</b>: {html_escape(result)} / {html_escape(status)}"]
        if event.get("error_message"):
            lines.append(f"⚠️ {html_escape(event['error_message'][:300])}")

    lines += ["", f"🏷 <b>سطح اهمیت</b>", f"{sev['icon']} {sev['label']}"]

    # تگ‌ها
    auto_tags = []
    if mod_fa:
        auto_tags.append(mod_fa.replace(" ", "_"))
    if actor.get("role"):
        clean_role = str(actor["role"]).split("(")[0].strip().replace(" ", "_")
        if clean_role:
            auto_tags.append(clean_role)
    all_tags = list(dict.fromkeys(auto_tags + (event.get("tags") or [])))
    if all_tags:
        lines += ["", " ".join(f"#{html_escape(t)}" for t in all_tags if t)]

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3960] + "\n… <i>(ادامه در لاگ دیتابیس)</i>"
    return text

# Compatibility wrapper برای utils.build_audit_log_text قدیمی
def build_audit_log_text(category: str, actor_name: str, actor_id: int,
                          action: str, module: str = '', details: str = '',
                          severity: str = 'INFO', actor_role: str = '',
                          target_id: str = '', target_type: str = '',
                          target_label: str = '', before: dict = None,
                          after: dict = None, tags: list = None) -> str:
    """Wrapper سازگار با امضای قدیمی — برای utils."""
    ev = build_audit_event(
        actor_id=actor_id, actor_name=actor_name, actor_role=actor_role,
        module=module or category, category=category, action=action,
        severity=severity, target_id=target_id, target_type=target_type,
        target_label=target_label, before=before, after=after,
        details=details, tags=tags,
    )
    return build_telegram_audit_text(ev)

# ══════════════════════════════════════════════════
#  10) Persistence + Delivery — Outbox (§14) + Retry (§15) + Health (§52)
# ══════════════════════════════════════════════════
# Delivery status values
DELIVERY_PENDING = "PENDING"
DELIVERY_DELIVERED = "DELIVERED"
DELIVERY_FAILED = "FAILED"
DELIVERY_PERMANENT_FAILED = "PERMANENT_FAILED"
DELIVERY_RETRY = "RETRY"

# In-memory health counters (§52, §16, §42)
_delivery_health = {
    "last_success": None,
    "last_failure": None,
    "last_error": None,
    "consecutive_failures": 0,
    "pending": 0,
    "failed": 0,
    "is_healthy": True,
    "down_since": None,
    "recovered_at": None,
}

def get_delivery_health() -> dict:
    return dict(_delivery_health)

async def persist_audit_event(event: dict) -> str:
    """
    ذخیره‌ی Durable در audit_logs — هیچ‌وقت به خاطر خطای تلگرام Rollback نشود (§35).
    returns: inserted_id / event_id
    """
    try:
        from database import db
        doc = dict(event)
        # Mongo _id جداگانه؛ event_id ایندکس یکتا
        r = await db.audit_logs.insert_one(doc)
        # Alert بحرانی
        sev = doc.get("severity")
        if sev in ("CRITICAL",):
            try:
                await db.dispatch_critical_alert({**doc, "_id": r.inserted_id})
            except Exception:
                logger.debug("critical alert dispatch failed", exc_info=True)
        return str(r.inserted_id)
    except Exception as e:
        logger.exception("persist_audit_event failed event_id=%s", event.get("event_id"))
        raise

async def enqueue_telegram_delivery(event: dict, chat_id: int | str) -> None:
    """
    صف Outbox برای تحویل تلگرام — قابل Retry (§14).
    از کالکشن audit_outbox استفاده می‌کنیم؛ اگر نبود از bot_notifications reuse می‌کنیم (§14 می‌گوید reuse اگر وجود دارد).
    """
    try:
        from database import db
        # سعی کن audit_outbox را به‌کار ببر؛ اگر کالکشن نیست، fallback به bot_notifications
        has_outbox = hasattr(db, "audit_outbox") and db.audit_outbox is not None
        payload_text = build_telegram_audit_text(event)
        if has_outbox:
            await db.audit_outbox.insert_one({
                "event_id": event["event_id"],
                "audit_log_id": event.get("_id"),
                "category": event.get("category"),
                "chat_id": int(chat_id),
                "text": payload_text,
                "status": DELIVERY_PENDING,
                "attempts": 0,
                "next_retry_at": utc_now_iso(),
                "last_error": None,
                "created_at": utc_now_iso(),
                "correlation_id": event.get("correlation_id"),
            })
        else:
            # Fallback: bot_notifications (existing queue) — §14 Reuse
            await db.bot_notifs.insert_one({
                "type": "audit_log",
                "chat_id": int(chat_id),
                "text": payload_text,
                "sent": False,
                "created_at": utc_now_iso(),
                "correlation_id": event.get("correlation_id"),
                "event_id": event["event_id"],
                "attempts": 0,
            })
    except Exception as e:
        logger.warning("enqueue_telegram_delivery failed event_id=%s: %s", event.get("event_id"), e)

async def deliver_to_telegram(bot, chat_id: int, text: str, event_id: str = "") -> dict:
    """
    ارسال واقعی به تلگرام با دسته‌بندی Retryable (§15) و ثبت delivery tracking (§41).
    return: {"ok": bool, "message_id": int|None, "error": str|None, "retryable": bool}
    """
    try:
        msg = await bot.send_message(int(chat_id), text, parse_mode="HTML")
        mid = getattr(msg, "message_id", None)
        # health recovery
        _delivery_health["last_success"] = utc_now_iso()
        _delivery_health["consecutive_failures"] = 0
        if _delivery_health["down_since"]:
            _delivery_health["recovered_at"] = utc_now_iso()
            _delivery_health["down_since"] = None
            _delivery_health["is_healthy"] = True
            logger.info("audit delivery RECOVERED chat_id=%s event_id=%s", chat_id, event_id)
        return {"ok": True, "message_id": mid, "error": None, "retryable": False}
    except Exception as e:
        err = str(e)[:500]
        # استخراج RetryAfter اگر باشد
        retry_after = None
        try:
            # PTB RetryAfter exception دارای retry_after
            if hasattr(e, "retry_after"):
                retry_after = int(getattr(e, "retry_after"))
            else:
                m = re.search(r"retry.?after.*?(\d+)", err, re.I)
                if m:
                    retry_after = int(m.group(1))
        except Exception:
            pass
        kind = classify_telegram_error(err)
        retryable = (kind == "retryable")
        # health failure
        _delivery_health["last_failure"] = utc_now_iso()
        _delivery_health["last_error"] = err
        _delivery_health["consecutive_failures"] += 1
        if _delivery_health["consecutive_failures"] >= 3 and not _delivery_health["down_since"]:
            _delivery_health["down_since"] = utc_now_iso()
            _delivery_health["is_healthy"] = False
            logger.warning("audit delivery DOWN chat_id=%s err=%s", chat_id, err)
        logger.warning("deliver_to_telegram failed chat=%s kind=%s retry_after=%s err=%s", chat_id, kind, retry_after, err)
        return {"ok": False, "message_id": None, "error": err, "retryable": retryable, "retry_after": retry_after}

async def process_audit_outbox_once(bot, limit: int = 20) -> dict:
    """
    Worker تک‌مرحله‌ای برای Outbox — توسط job یا دستی صدا زده می‌شود.
    Idempotent (§43): event_id یکتاست؛ ارسال دوباره‌ی timeout امن است اگر پیام واقعاً رفته باشد، چون
                       متن یکسان است و duplicate delivery کنترل می‌شود.
    Race (§44): find_one_and_update برای claim اتمیک.
    """
    try:
        from database import db
        if not hasattr(db, "audit_outbox"):
            # fallback: bot_notifications path — توسط mini_app_outbox_job موجود پردازش می‌شود
            return {"processed": 0, "note": "no audit_outbox, using bot_notifications"}
        now_iso = utc_now_iso()
        # پیدا کن pending یا retry که زمانش رسیده
        query = {
            "status": {"$in": [DELIVERY_PENDING, DELIVERY_RETRY, DELIVERY_FAILED]},
            "next_retry_at": {"$lte": now_iso},
            "attempts": {"$lt": MAX_RETRIES},
        }
        docs = await db.audit_outbox.find(query).sort("created_at", 1).limit(limit).to_list(limit)
        stats = {"processed": 0, "delivered": 0, "failed": 0, "retry": 0}
        for doc in docs:
            # atomic claim — جلوگیری از Race دو Worker (§44)
            claimed = await db.audit_outbox.find_one_and_update(
                {"_id": doc["_id"], "status": doc["status"], "attempts": doc["attempts"]},
                {"$set": {"status": "CLAIMED", "claimed_at": utc_now_iso()}},
            )
            # اگر claim شکست (race)، رد شو
            if not claimed:
                continue
            # نگاشت به event برای delivery tracking در audit_logs (§41)
            event_id = doc.get("event_id")
            chat_id = doc.get("chat_id")
            text = doc.get("text")
            attempts = int(doc.get("attempts") or 0)
            res = await deliver_to_telegram(bot, chat_id, text, event_id)
            stats["processed"] += 1
            if res["ok"]:
                await db.audit_outbox.update_one({"_id": doc["_id"]}, {"$set": {
                    "status": DELIVERY_DELIVERED,
                    "telegram_message_id": res.get("message_id"),
                    "telegram_sent_at": utc_now_iso(),
                    "last_error": None,
                }})
                # update audit_logs delivery tracking
                try:
                    await db.audit_logs.update_one({"event_id": event_id}, {"$set": {
                        "telegram_delivery_status": DELIVERY_DELIVERED,
                        "telegram_message_id": res.get("message_id"),
                        "telegram_chat_id": chat_id,
                        "telegram_sent_at": utc_now_iso(),
                        "telegram_error": None,
                    }})
                except Exception:
                    pass
                stats["delivered"] += 1
            else:
                kind = classify_telegram_error(res.get("error") or "")
                if kind == "non_retryable" or attempts + 1 >= MAX_RETRIES:
                    await db.audit_outbox.update_one({"_id": doc["_id"]}, {"$set": {
                        "status": DELIVERY_PERMANENT_FAILED,
                        "attempts": attempts + 1,
                        "last_error": res.get("error"),
                        "next_retry_at": utc_now_iso(),
                    }})
                    try:
                        await db.audit_logs.update_one({"event_id": event_id}, {"$set": {
                            "telegram_delivery_status": DELIVERY_PERMANENT_FAILED,
                            "telegram_chat_id": chat_id,
                            "telegram_error": res.get("error"),
                        }})
                    except Exception:
                        pass
                    stats["failed"] += 1
                else:
                    delay = next_retry_delay(attempts, res.get("retry_after"))
                    next_at = (now_utc() + timedelta(seconds=delay)).isoformat()
                    await db.audit_outbox.update_one({"_id": doc["_id"]}, {"$set": {
                        "status": DELIVERY_RETRY if attempts + 1 < MAX_RETRIES else DELIVERY_FAILED,
                        "attempts": attempts + 1,
                        "last_error": res.get("error"),
                        "next_retry_at": next_at,
                    }})
                    try:
                        await db.audit_logs.update_one({"event_id": event_id}, {"$set": {
                            "telegram_delivery_status": DELIVERY_FAILED,
                            "telegram_chat_id": chat_id,
                            "telegram_error": res.get("error"),
                        }})
                    except Exception:
                        pass
                    stats["retry"] += 1
        return stats
    except Exception as e:
        logger.exception("process_audit_outbox_once failed: %s", e)
        return {"processed": 0, "error": str(e)}

async def audit_outbox_worker(bot, interval_sec: int = 30):
    """Background loop — برای Railway job یا bot job_queue."""
    while True:
        try:
            await process_audit_outbox_once(bot)
        except Exception:
            logger.exception("audit_outbox_worker loop error")
        await asyncio.sleep(interval_sec)

# ══════════════════════════════════════════════════
#  11) Core API — audit_event / audit_success / audit_failure (§47)
#     همه‌ی Moduleها باید از این Contract مشترک استفاده کنند.
# ══════════════════════════════════════════════════
async def audit_event(
    bot=None,
    *,
    actor_id: Any,
    actor_name: str,
    actor_role: str = "نامشخص",
    actor_type: str = "USER",
    module: str = "System",
    category: str = "system",
    action: str = "system.unknown",
    severity: str = "INFO",
    target_id: str = "",
    target_type: str = "",
    target_label: str = "",
    before: Optional[dict] = None,
    after: Optional[dict] = None,
    result: str = "SUCCESS",
    status: str = "SUCCESS",
    source: str = "bot",
    channel: str = "telegram",
    request_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    metadata: Optional[dict] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    tags: Optional[list] = None,
    details: str = "",
    target_context: Optional[dict] = None,
    telegram_chat_id: Optional[int | str] = None,  # اگر بخواهی مستقیم بفرستی
) -> dict:
    """
    ثبت Audit استاندارد (§47):
      1) Sanitization
      2) Persistence (must succeed for sensitive ops — caller 503 if fails)
      3) Delivery (secondary — fail-open, enqueue outbox)

    return: {"event_id": str, "audit_id": str, "correlation_id": str, "delivery": str}
    """
    # correlation/request از context اگر نداده
    corr = correlation_id or get_correlation_id()
    req = request_id or get_request_id() or new_request_id()
    event = build_audit_event(
        actor_id=actor_id, actor_name=actor_name, actor_role=actor_role, actor_type=actor_type,
        module=module, category=category, action=action, severity=severity,
        target_type=target_type, target_id=target_id, target_label=target_label,
        before=before, after=after, result=result, status=status,
        source=source, channel=channel, request_id=req, correlation_id=corr,
        ip=ip, user_agent=user_agent, metadata=metadata,
        error_code=error_code, error_message=error_message,
        tags=tags, details=details, target_context=target_context,
    )
    # 1) Persist — invariant (§35, §48)
    audit_id = await persist_audit_event(event)
    event["_id"] = audit_id
    event["event_id"] = event["event_id"]  # keep

    # 2) Delivery — secondary (§13, §35)
    # اگر bot داده و chat_id داریم، enqueue یا direct
    delivery = "PENDING"
    try:
        if bot is not None:
            # تعیین chat_id گروه لاگ بر اساس دسته
            if telegram_chat_id is None:
                try:
                    from database import db as _db
                    group_key, _, _ = get_category_meta(category)
                    chat_id = await _db.get_setting(group_key, None)
                    # اگر گروه مربوطه نبود، admin را fallback کن
                    if not chat_id and group_key != "log_group_admin":
                        chat_id = await _db.get_setting("log_group_admin", None)
                    telegram_chat_id = chat_id
                except Exception:
                    telegram_chat_id = None
            if telegram_chat_id:
                # Outbox enqueue — delivery جدا از business (§13)
                await enqueue_telegram_delivery(event, telegram_chat_id)
                # تلاش فوری (best-effort) — اگر fail شد، outbox دوباره retry می‌کند
                try:
                    text = build_telegram_audit_text(event)
                    res = await deliver_to_telegram(bot, int(telegram_chat_id), text, event["event_id"])
                    if res["ok"]:
                        delivery = DELIVERY_DELIVERED
                        # mark delivered immediately to avoid duplicate later
                        try:
                            from database import db as _db2
                            if hasattr(_db2, "audit_outbox"):
                                await _db2.audit_outbox.update_many(
                                    {"event_id": event["event_id"], "status": {"$in": [DELIVERY_PENDING, "CLAIMED"]}},
                                    {"$set": {"status": DELIVERY_DELIVERED, "telegram_message_id": res.get("message_id"), "telegram_sent_at": utc_now_iso()}}
                                )
                            await _db2.audit_logs.update_one({"event_id": event["event_id"]}, {"$set": {
                                "telegram_delivery_status": DELIVERY_DELIVERED,
                                "telegram_message_id": res.get("message_id"),
                                "telegram_chat_id": int(telegram_chat_id),
                                "telegram_sent_at": utc_now_iso(),
                            }})
                        except Exception:
                            pass
                    else:
                        delivery = DELIVERY_FAILED
                except Exception as de:
                    logger.debug("immediate delivery failed (outbox will retry) event_id=%s: %s", event["event_id"], de)
                    delivery = DELIVERY_FAILED
            else:
                delivery = "NO_GROUP"  # فقط DB (§16 — گروه تنظیم نشده = فقط DB)
        else:
            # بدون bot — فقط DB (مثلاً از API بدون bot instance — via bot_notifications queue)
            # enqueue via DB-only path — worker بعدی می‌فرستد
            if telegram_chat_id:
                await enqueue_telegram_delivery(event, telegram_chat_id)
    except Exception as e:
        logger.warning("audit delivery enqueue failed event_id=%s: %s", event.get("event_id"), e)
        delivery = "ENQUEUE_FAILED"

    return {"event_id": event["event_id"], "audit_id": audit_id, "correlation_id": corr, "delivery": delivery}

# Convenience
async def audit_success(bot=None, **kwargs) -> dict:
    kwargs.setdefault("result", "SUCCESS")
    kwargs.setdefault("status", "SUCCESS")
    kwargs.setdefault("severity", kwargs.get("severity") or "INFO")
    return await audit_event(bot, **kwargs)

async def audit_failure(bot=None, **kwargs) -> dict:
    kwargs.setdefault("result", "FAILED")
    kwargs.setdefault("status", "FAILED")
    if "severity" not in kwargs or kwargs["severity"] == "INFO":
        kwargs["severity"] = "HIGH"
    return await audit_event(bot, **kwargs)

# ══════════════════════════════════════════════════
#  12) Application Log Helpers — جداسازی §4
# ══════════════════════════════════════════════════
def app_log_debug(msg: str, *args, **kwargs):
    app_logger.debug(msg, *args, **kwargs)

def app_log_info(msg: str, *args, **kwargs):
    app_logger.info(msg, *args, **kwargs)

def app_log_warning(msg: str, *args, **kwargs):
    app_logger.warning(msg, *args, **kwargs)

def app_log_error(msg: str, *args, **kwargs):
    app_logger.error(msg, *args, **kwargs)

def app_log_exception(msg: str, *args, **kwargs):
    app_logger.exception(msg, *args, **kwargs)

# ══════════════════════════════════════════════════
#  13) Legacy Compatibility — send_audit_log version 2
# ══════════════════════════════════════════════════
async def legacy_send_audit_log(bot, category: str, actor_name: str, actor_id: int,
                                 action: str, module: str = '', details: str = '',
                                 severity: str = 'INFO', actor_role: str = '',
                                 target_id: str = '', target_type: str = '',
                                 target_label: str = '', before: dict = None,
                                 after: dict = None, tags: list = None,
                                 correlation_id: str = None) -> str:
    """سازگاری کامل با utils.send_audit_log قدیمی — حالا از مسیر جدید می‌گذرد."""
    # نگاشت legacy WARNING
    sev = normalize_severity(severity)
    cat = normalize_category(category)
    # action legacy ممکن است فارسی باشد — اگر شامل نقطه نباشد، به content.legacy نگاشت می‌کنیم
    act = action.strip() if action else "system.unknown"
    # اگر action فارسی/بدون dot است، به‌صورت رویداد آزاد ثبت می‌کنیم اما tags حفظ می‌شود
    if "." not in act:
        # تبدیل عنوان فارسی به action code انگلیسی برای query
        # نگاشت حداقلی؛ بقیه as-is با پیشوند legacy.
        act_code = f"legacy.{cat}.{hashlib.md5(act.encode()).hexdigest()[:8]}"
        # display_action همان act فارسی می‌ماند
        details_combined = f"{act}\n{details}" if details else act
    else:
        act_code = act
        details_combined = details

    res = await audit_event(
        bot,
        actor_id=actor_id, actor_name=actor_name, actor_role=actor_role,
        module=module or cat, category=cat, action=act_code,
        severity=sev, target_id=target_id, target_type=target_type,
        target_label=target_label, before=before, after=after,
        details=details_combined, tags=tags, correlation_id=correlation_id,
    )
    return res["audit_id"]

# ══════════════════════════════════════════════════
#  14) Observability / Health §52 + Retention §39
# ══════════════════════════════════════════════════
async def get_audit_health() -> dict:
    try:
        from database import db
        pending = await db.audit_outbox.count_documents({"status": {"$in": [DELIVERY_PENDING, DELIVERY_RETRY]}}) if hasattr(db, "audit_outbox") else 0
        failed = await db.audit_outbox.count_documents({"status": DELIVERY_FAILED}) if hasattr(db, "audit_outbox") else 0
        perm_failed = await db.audit_outbox.count_documents({"status": DELIVERY_PERMANENT_FAILED}) if hasattr(db, "audit_outbox") else 0
        last_success = _delivery_health.get("last_success")
        return {
            "audit_persistence": "HEALTHY",
            "telegram_delivery": "HEALTHY" if _delivery_health.get("is_healthy") else "DEGRADED",
            "outbox": "HEALTHY",
            "pending": pending,
            "failed": failed,
            "permanent_failed": perm_failed,
            "last_success": last_success,
            "last_failure": _delivery_health.get("last_failure"),
            "down_since": _delivery_health.get("down_since"),
            "consecutive_failures": _delivery_health.get("consecutive_failures"),
        }
    except Exception as e:
        return {"error": str(e)}

# Retention helper — قابل پیکربندی (§39)
DEFAULT_RETENTION_DAYS = 365  # پیش‌فرض یک سال؛ قابل override با setting
async def apply_retention(days: int | None = None) -> int:
    """حذف لاگ‌های قدیمی‌تر از retention — فقط اگر تنظیمات اجازه دهد."""
    try:
        from database import db
        if days is None:
            days = int(await db.get_setting("audit_retention_days", DEFAULT_RETENTION_DAYS))
        if days <= 0:
            return 0  # نگهداری نامحدود (طبق policy)
        cutoff = (now_utc() - timedelta(days=days)).isoformat()
        r = await db.audit_logs.delete_many({"timestamp": {"$lt": cutoff}})
        return int(getattr(r, "deleted_count", 0) or 0)
    except Exception as e:
        logger.warning("retention cleanup failed: %s", e)
        return 0

__all__ = [
    "SEVERITY_LEVELS", "CATEGORIES", "ACTION_LABEL_FA", "ACTOR_TYPES",
    "REDACTED", "sanitize_audit_data", "sanitize_value", "html_escape",
    "new_event_id", "new_correlation_id", "new_request_id", "get_request_id", "get_correlation_id",
    "normalize_severity", "normalize_category", "normalize_actor_type",
    "build_audit_event", "build_telegram_audit_text", "build_audit_log_text",
    "persist_audit_event", "enqueue_telegram_delivery", "deliver_to_telegram",
    "process_audit_outbox_once", "audit_outbox_worker",
    "audit_event", "audit_success", "audit_failure",
    "legacy_send_audit_log",
    "get_audit_health", "apply_retention",
    "get_delivery_health",
    "DELIVERY_PENDING", "DELIVERY_DELIVERED", "DELIVERY_FAILED", "DELIVERY_PERMANENT_FAILED",
    "classify_telegram_error", "next_retry_delay",
]

