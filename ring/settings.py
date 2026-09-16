"""💍 Ring Street — تنظیمات و feature flag (§۲۹، §۳۸، §۵۶)

منبع حقیقت همیشه Mongo است (`bot_settings/_id=global` با پیشوند `ring.`).
اینجا دو چیز اضافه می‌کند:

  • `get_cfg()`  — نسخه‌ی async با کش TTL‌دار (برای هندلرها/اپی)
  • `flag_sync()` — نسخه‌ی **سمک** فقط برای `utils.main_keyboard()`؛
    کیبورد در جاهای زیادی به‌صورت sync ساخته می‌شود و نباید برای هر
    کیبورد یک query بزند. مقدارش توسط post_init، هر job دوره‌ای و هر
    تغییر از پنل تازه می‌شود ⇒ تا `CACHE_TTL` ثانیه تأخیر در پروسه‌ی
    دیگر (api ↔ bot) طبیعی است و در گزارش ذکر شده.

هیچ کلیدی در اینجا hard-code نمی‌شود که admin نتواند عوضش کند؛ همه از
`SPEC` می‌آیند و `clamp()` مقدار پنل را به بازه‌ی امن می‌برد.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

# ⚠️ نام کلیدها عمداً «نقطه‌چین» نیست: `db.set_setting("ring.x", v)` در Mongo
# معنای path به فرعی دارد و مستند را به‌شکل `{"ring": {"x": …}}` درمی‌آورد؛
# `get_setting("ring.x")` بعد آن را پیدا نمی‌کند (تست گرفتم). پس همه‌ی
# کلیدهای این فیچر با پیشوند `ring_` در `bot_settings/_id=global` می‌نشینند.
PREFIX = "ring_"
FLAG_KEY = "ring_enabled"
CFG_KEY = "ring_cfg"
# 🟡 حالت سوم (§۴۵ Maintenance): فیچر «روشن» است ولی match تازه ساخته نمی‌شود
# و چت‌های جاری می‌توانند تمام شوند. حرفه‌ای‌تر از disable کامل.
MAINT_KEY = "ring_maintenance"
CACHE_TTL = 10          # ثانیه — کش read-side
FLAG_REFRESH_MAX = 60   # حداکثر فاصله‌ی تازه‌سازی flag در حالت عادی

# name: (برچسب فارسی، default، min، max، نوع)
SPEC: dict[str, tuple[str, object, float | None, float | None, str]] = {
    "serious_enabled":      ("حالت آشنایی جدی", True, None, None, "bool"),
    "fun_enabled":          ("حالت رینگ فان", True, None, None, "bool"),
    "min_age":              ("حداقل سن", 18, 18, 30, "int"),
    "max_age":              ("حداکثر سن", 60, 25, 99, "int"),
    "queue_timeout_s":      ("سقف انتظار در صف (ثانیه)", 600, 30, 3600, "int"),
    "session_idle_s":       ("بی‌فعالیت جلسه (ثانیه)", 1800, 60, 86400, "int"),
    "session_grace_s":      ("مهلت پیش از بستن جلسه (ثانیه)", 300, 0, 3600, "int"),
    "max_msg_per_min":      ("سقف پیام در دقیقه", 20, 1, 200, "int"),
    "max_search_per_min":   ("سقف «نفر بعدی» در دقیقه", 6, 1, 60, "int"),
    "max_report_per_day":   ("سقف گزارش در روز", 10, 1, 100, "int"),
    "max_profile_per_hour": ("سقف ویرایش پروفایل در ساعت", 12, 1, 100, "int"),
    "max_media_per_min":    ("سقف فایل/مدیا در دقیقه", 6, 0, 60, "int"),
    "skip_cooldown_s":      ("کول‌داون پس از نفر بعدی (ثانیه)", 86400, 0, 604800, "int"),
    "rematch_after_s":      ("چقدر صبر کنیم تا پارتنرِ اخیر دوباره قابل انتخاب شود (ثانیه)", 90, 30, 3600, "int"),
    "debug_match_log":      ("لاگ جزئیات رد شدن کاندید (بدون محتوای خصوصی)", False, None, None, "bool"),
    "report_cooldown_s":    ("کول‌داون پس از گزارش (ثانیه)", 3600, 0, 604800, "int"),
    "auto_mod_enabled":     ("میدان خودکار moderation", True, None, None, "bool"),
    "report_review_score":  ("آستانه‌ی بررسی گزارش", 3, 1, 50, "int"),
    "report_restrict_score": ("آستانه‌ی محدودیت موقت", 5, 2, 80, "int"),
    "report_ban_score":     ("آستانه‌ی بن خودکار", 10, 3, 200, "int"),
    "auto_ban_hours":       ("مدت بن خودکار (ساعت)", 24, 1, 8760, "int"),
    "allow_rating":         ("امتیازدهی پس از گفت‌وگو", True, None, None, "bool"),
    "allow_reveal":         ("معرفی دوطرفه (serious)", True, None, None, "bool"),
    "allow_topics":         ("موضوع گفت‌وگو در حالت فان", True, None, None, "bool"),
    "allow_icebreakers":    ("جرقه‌ی گفت‌وگو", True, None, None, "bool"),
    "media_text":           ("اجازه‌ی متن", True, None, None, "bool"),
    "media_sticker":        ("اجازه‌ی استیکر", True, None, None, "bool"),
    "media_photo":          ("اجازه‌ی عکس", True, None, None, "bool"),
    "media_voice":          ("اجازه‌ی ویس", False, None, None, "bool"),
    "media_video":          ("اجازه‌ی ویدیو", False, None, None, "bool"),
    "media_document":       ("اجازه‌ی فایل", False, None, None, "bool"),
    # §۱۸ — مخاطب/موقعیت سیاستِ *مجزا* دارند: هر دو هویت لو می‌دهند
    # (شمارهٔ تماس در contact، مختصات خانه/دانشگاه در location) ⇒ پیش‌فرض خاموش.
    "media_contact":        ("اجازه‌ی فرستادن مخاطب (شمارهٔ تماس)", False, None, None, "bool"),
    "media_location":       ("اجازه‌ی فرستادن موقعیت مکانی", False, None, None, "bool"),
    "evidence_mode":        ("ثبت محتوای پیام", "report_only", None, None,
                             "choice:report_only,all,off"),
    "evidence_ttl_days":    ("ماندگاری شواهد (روز)", 7, 7, 30, "int"),   # §۳۵: ۷ تا ۳۰ روز
    "warn_personal_data":   ("هشدار ارسال اطلاعات شخصی", True, None, None, "bool"),
    "safety_note_every":    ("نمایش یادآوری ایمنی هر چند جلسه", 3, 1, 100, "int"),
    "rules_version":        ("نسخهٔ قوانین (با تغییرش همه باید دوباره بپذیرند)", 2, 1, 99, "int"),
    "rules_text_override":  ("متن جایگزین قوانین (خالی = متن پیش‌فرض ۱۲بندی)", "",
                             None, 3500, "text"),
    "max_partners_history": ("تعداد پارتنرهای اخیر برای کول‌داون", 40, 1, 500, "int"),
}

MEDIA_KINDS = {                        # کلید تنظیمات ← نوع پیام تلگرام
    "text": "text", "sticker": "sticker", "photo": "photo",
    "voice": "voice", "video": "video", "document": "document",
}

_cfg_cache: dict = {"data": None, "at": 0.0, "flag": None, "flag_at": 0.0, "maint": None}


def defaults() -> dict:
    return {k: v[1] for k, v in SPEC.items()}


def labels() -> dict:
    return {k: v[0] for k, v in SPEC.items()}


def clamp(name: str, value):
    """اعتبارسنجی مقدارِ ادمین — بجز عدد، نوع هم تحمیل می‌شود تا
    `True`/`"0"` در Mongo باعث رفتار عجیب نشود."""
    _, _, lo, hi, kind = SPEC[name]
    if kind == "bool":
        if isinstance(value, str):
            value = value.strip().lower() not in ("0", "false", "no", "off", "")
        return bool(value)
    if kind == "text":
        txt = "" if value is None else str(value)
        return txt.strip()[: (int(hi) if hi else 3500)]
    if kind.startswith("choice:"):
        opts = kind.split(":", 1)[1].split(",")
        v = str(value).strip()
        return v if v in opts else opts[0]
    try:
        v = int(float(value))
    except (TypeError, ValueError):
        return defaults()[name]
    if lo is not None:
        v = max(int(lo), v)
    if hi is not None:
        v = min(int(hi), v)
    return v


def _coerce(raw: dict) -> dict:
    out = defaults()
    for k, v in (raw or {}).items():
        if k in SPEC:
            try:
                out[k] = clamp(k, v)
            except Exception as e:
                logger.debug("[RING] cfg key %r ignored: %s", k, e)
    return out


async def get_flag() -> bool:
    """آیا کل فیچر روشن است؟ (§۵۶ — تنها منبع حقیقت)"""
    from database import db
    try:
        val = await db.get_setting(FLAG_KEY, False)
    except Exception as e:
        logger.warning("ring flag read failed → disabled: %s", e)
        return False
    _cfg_cache["flag"] = bool(val)
    _cfg_cache["flag_at"] = time.monotonic()
    try:
        _cfg_cache["maint"] = bool(await db.get_setting(MAINT_KEY, False))
    except Exception as e:
        logger.debug("[RING] maintenance read failed (fallback): %s", e)
    return bool(val)


async def get_cfg(force: bool = False) -> dict:
    from database import db
    now = time.monotonic()
    if not force and _cfg_cache["data"] is not None and now - _cfg_cache["at"] < CACHE_TTL:
        return _cfg_cache["data"]
    raw: dict = {}
    try:
        raw = (await db.get_setting(CFG_KEY, {})) or {}
    except Exception as e:
        logger.warning("ring cfg read failed → defaults: %s", e)
    cfg = _coerce(raw if isinstance(raw, dict) else {})
    _cfg_cache["data"] = cfg
    _cfg_cache["at"] = now
    # flag را هم همین‌جا تازه می‌کنیم تا flag_sync همیشه مقدار معقولی داشته باشد
    try:
        _cfg_cache["flag"] = bool(await db.get_setting(FLAG_KEY, False))
        _cfg_cache["flag_at"] = now
    except Exception as e:
        logger.debug("[RING] settings cache invalidate failed: %s", e)
    return cfg


async def mode_enabled(mode: str) -> bool:
    cfg = await get_cfg()
    if not await get_flag():
        return False
    return bool(cfg.get("serious_enabled" if mode == "serious" else "fun_enabled", True))


async def disable_mode() -> str:
    """soft (جلسات موجود تمام می‌شوند) یا hard (§۲۹/§۷۴)"""
    from database import db
    try:
        return (await db.get_setting("ring_disable_mode", "soft")) or "soft"
    except Exception:
        return "soft"


async def set_enabled(admin_id: int, enabled: bool, disable_mode_: str = "soft") -> None:
    from database import db
    await db.set_setting(FLAG_KEY, bool(enabled))
    await db.set_setting("ring_disable_mode", "hard" if disable_mode_ == "hard" else "soft")
    await db.ring_audit(admin_id, "ENABLE_RING" if enabled else "DISABLE_RING",
                        "global", f"disable_mode={disable_mode_}", {"enabled": bool(enabled)})
    invalidate()


async def set_cfg(admin_id: int, updates: dict) -> dict:
    """مقادیر را اعتبارسنجی/ذخیره و کش را باطل می‌کند. §۷۴: هیچ کلید
    ناشناخته‌ای نوشته نمی‌شود (جلوی آلوده‌شدن settings با payload دلخواه)."""
    from database import db
    cur = (await db.get_setting(CFG_KEY, {})) or {}
    merged = _coerce(cur)
    changed = {}
    for k, v in (updates or {}).items():
        if k in SPEC:
            merged[k] = clamp(k, v)
            changed[k] = merged[k]
    await db.set_setting(CFG_KEY, merged)
    await db.ring_audit(admin_id, "UPDATE_SETTINGS", "config", "", changed)
    invalidate()
    return merged


async def maintenance() -> bool:
    """حالت زرد (§۴۵): صف و match جدید بسته، چت‌های جاری باز."""
    from database import db
    try:
        return bool(await db.get_setting(MAINT_KEY, False))
    except Exception as e:
        logger.warning("ring maintenance read failed → عادی: %s", e)
        return False


def maintenance_sync() -> bool:
    return bool(_cfg_cache.get("maint"))


async def set_maintenance(admin_id: int, on: bool) -> None:
    from database import db
    await db.set_setting(MAINT_KEY, bool(on))
    await db.ring_audit(admin_id, "RING_MAINTENANCE_ON" if on else "RING_MAINTENANCE_OFF",
                        "global", "", {"maintenance": bool(on)})
    _cfg_cache["maint"] = bool(on)


async def ui_state() -> str:
    """🟢 active / 🟡 maintenance / 🔴 disabled — تنها منبع وضعیت برای پنل و منو."""
    if not await get_flag():
        return "disabled"
    return "maintenance" if await maintenance() else "active"


def flag_sync() -> bool:
    """سمک — برای کیبورد. اگر هیچ‌وقت read نشده، «خاموش» (امن‌ترین حالت:
    دکمه‌ای که فیچرش خاموش است نمایش داده نمی‌شود)."""
    f = _cfg_cache.get("flag")
    return bool(f) if f is not None else False


def flag_stale() -> bool:
    """آیا flag باید دوباره از DB خوانده شود؟ (برای job دوره‌ای)"""
    return time.monotonic() - float(_cfg_cache.get("flag_at") or 0) > min(CACHE_TTL, FLAG_REFRESH_MAX)


def invalidate() -> None:
    _cfg_cache["data"] = None
    _cfg_cache["at"] = 0.0
    _cfg_cache["maint"] = None


def set_flag_sync(value: bool) -> None:
    _cfg_cache["flag"] = bool(value)
    _cfg_cache["flag_at"] = time.monotonic()
