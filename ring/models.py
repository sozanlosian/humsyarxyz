"""💍 Ring Street — مدل داده، اعتبارسنجی و ماشین حالت (§۲، §۳، §۱۱، §۲۶)

هیچ‌جا «احراز هویت سن» نمی‌کنیم؛ خوداظهاری است و در متن هم صریح
نوشته می‌شود (§۲). سن دقیق فقط در DB می‌ماند و در UI حلقه‌ی سنی نشان
داده می‌شود — مگر در حالت reveal دوطرفه (§۲۷).
"""
from __future__ import annotations

import re

# ── حلقه‌های سنی (کلید، برچسب، min، max) ──────────────────────
AGE_RANGES = [
    ("18-20", "۱۸–۲۰", 18, 20),
    ("21-23", "۲۱–۲۳", 21, 23),
    ("24-26", "۲۴–۲۶", 24, 26),
    ("27-30", "۲۷–۳۰", 27, 30),
    ("31-35", "۳۱–۳۵", 31, 35),
    ("36+",  "۳۶+",    36, 99),
]
AGE_INDEX = {k: (lo, hi) for k, _, lo, hi in AGE_RANGES}
AGE_LABELS = {k: lbl for k, lbl, _, _ in AGE_RANGES}

GENDERS = {"male": "👨 پسر", "female": "👩 دختر",
           "undisclosed": "🤐 ترجیح می‌دم بگم نه"}
MODES = {"serious": "💍 آشنایی جدی", "fun": "🎭 رینگ فان"}
INTENTS = {"marriage": "💍 ازدواج", "serious": "❤️ رابطه جدی", "first": "🤝 آشنایی اولیه"}
TOPICS = {
    "university": "🎓 دانشگاه", "game": "🎮 بازی", "movie": "🎬 فیلم",
    "music": "🎵 موسیقی", "fun": "😂 فان", "free": "🧠 بحث آزاد", "random": "🎲 رندوم",
}
PROFILE_FIELDS = {
    "bio":        ("درباره من", 300),
    "interests":  ("علایق", 160),
    "city":       ("شهر", 60),
    "university": ("دانشگاه", 80),
    "major":      ("رشته", 80),
}
REPORT_REASONS = {                      # کلید → (برچسب، severity §۲۳)
    "harassment":  ("🚨 آزار و مزاحمت", 2),
    "insult":      ("🤬 توهین و فحاشی", 1),
    "sexual":      ("🔞 محتوای نامناسب", 3),
    "money":       ("💰 درخواست پول / کلاهبرداری", 4),
    "offapp":      ("📞 اصرار به ارتباط خارج از ربات", 3),
    "spam":        ("🎯 تبلیغات / اسپم", 1),
    "doxxing":     ("🕵️ تلاش برای افشای هویت", 4),
    "other":       ("⚠️ سایر", 1),
}
# گزارش‌های قدیمی با کلیدهای قبلی در DB ممکن است بمانند ⇒ هنگام خواندن
# نگاشت می‌شوند (نه migration مخرب).
REASON_ALIAS = {"sexual_content": "sexual", "scam": "money", "suspicious": "other"}


def reason_key(raw: str | None) -> str:
    k = str(raw or "other").strip()
    k = REASON_ALIAS.get(k, k)
    return k if k in REPORT_REASONS else "other"


def reason_sev(raw: str | None) -> int:
    return int(REASONS_SEVERITY.get(reason_key(raw), 1))


REASONS_SEVERITY = {k: v[1] for k, v in REPORT_REASONS.items()}
REASONS_LABELS = {k: v[0] for k, v in REPORT_REASONS.items()}

# ── نسخه‌ی قوانین (§۲۷) ────────────────────────────────────────
# با تغییر این عدد، همهٔ کاربران باید نسخهٔ جدید را دوباره بپذیرند
# (در پروفایل `rules_version` ذخیره می‌شود).
RULES_VERSION = 2      # §۴۰ (V4): متن قوانین بازنویسی شد ⇒ همه یک‌بار دوباره می‌پذیرند

# ── «چه چیزی از پروفایلم دیده شود» (§۳۵ — opt-in/opt-out) ─────
# پیش‌فرض = همان رفتار فعلی (هرچه کاربر نوشته نمایش داده می‌شود)، ولی
# کاربر می‌تواند تک‌تک خاموشش کند؛ هیچ فیلدی که کاربر ننوشته نمایش
# داده نمی‌شود و هیچ شناسهٔ تلگرامی در این فهرست نیست.
PROFILE_VIEW = {
    "show_age":        "🎂 سن/حلقهٔ سنی",
    "show_gender":     "👤 جنسیت",
    "show_field":      "📚 رشتهٔ تحصیل",
    "show_university": "🎓 دانشگاه",
    "show_city":       "🏙 شهر",
    "show_bio":        "📝 دربارهٔ من و علایق",
}
VIEW_DEFAULT = {k: True for k in PROFILE_VIEW}


def view_on(profile: dict | None, key: str) -> bool:
    """آیا این بخش از پروفایل برای طرف مقابل قابل نمایش است؟"""
    p = profile or {}
    if key not in PROFILE_VIEW:
        return False
    v = p.get(key)
    return VIEW_DEFAULT[key] if v is None else bool(v)


RATINGS = {"great": 5, "good": 4, "mid": 3, "bad": 2, "worst": 1}
RATING_LABELS = {"great": "😍 عالی", "good": "🙂 خوب", "mid": "😐 معمولی",
                 "bad": "😕 بد", "worst": "🚨 مشکل داشت"}
ICEBREAKERS = [
    "🎓 رشته‌ات چیه؟", "🎵 آخرین آهنگی که گوش دادی؟", "🎬 فیلم محبوبت؟",
    "☕ قهوه یا چای؟", "😂 عجیب‌ترین اتفاق دانشگاه؟", "💭 یک سوال تصادفی",
]

# ── ماشین حالت (§۱۱) ──────────────────────────────────────────
(IDLE, AGE_GATE, GENDER_PICK, MODE_PICK, TERMS, PROFILE,
 CHATTING, REPORT_WHY, BLOCK_CONFIRM, PAUSED, BANNED) = (
    "IDLE", "AGE_GATE", "GENDER_PICK", "MODE_PICK", "TERMS", "PROFILE",
    "CHATTING", "REPORT_WHY", "BLOCK_CONFIRM", "PAUSED", "BANNED")

TRANSITIONS: dict[str, set[str]] = {
    IDLE: {AGE_GATE, PROFILE, PAUSED},
    AGE_GATE: {GENDER_PICK, IDLE, BANNED},
    GENDER_PICK: {MODE_PICK, IDLE, BANNED},
    MODE_PICK: {TERMS, PROFILE, IDLE, BANNED},
    TERMS: {PROFILE, IDLE, BANNED},
    PROFILE: {IDLE, MODE_PICK, BANNED},
    CHATTING: {IDLE, PAUSED, BANNED, REPORT_WHY, BLOCK_CONFIRM},
    REPORT_WHY: {CHATTING, IDLE, BLOCK_CONFIRM},
    BLOCK_CONFIRM: {IDLE, CHATTING},
    PAUSED: {IDLE, PROFILE},
    BANNED: {IDLE},
}


# ══════════════════════════════════════════════════════════════
#  §۵ (V4) — ماشین حالتِ واحدِ کاربر
#
#  حالت‌های جریانِ تعامل (IDLE/AGE_GATE/… بالا) دست‌نخورده می‌مانند؛ این‌جا
#  نمایِ *چرخهٔ مچ* از همان سه منبعِ موجود (پروفایل · ردیف صف · session فعال)
#  ساخته می‌شود — هیچ فیلد/کالکشن جدیدی لازم نیست، پس migration هم لازم نیست
#  (§۴۸). همه‌ی مصرف‌کننده‌ها (صفحهٔ رینگ، /ring status، فیلترِ رله، پنل ادمین،
#  endpoint عیب‌یابی) همین یک تابع را صدا می‌زنند تا منبع حقیقت یکی بماند (§۱۲).
# ══════════════════════════════════════════════════════════════

(US_IDLE, US_PROFILE, US_READY, US_WAITING, US_MATCHED, US_PAUSED,
 US_ENDED, US_RESTRICTED, US_EXPIRED) = (
    "IDLE", "PROFILE_REQUIRED", "READY", "WAITING", "MATCHED", "PAUSED",
    "ENDED", "RESTRICTED", "EXPIRED")

# §۶ (V5) — «در حال جست‌وجو» و «کسی پیدا نشد» دو حالت جدا هستند. ردیفِ صف
# یعنی SEARCHING؛ EXPIRED فقط وقتی ساخته می‌شود که سقف انتظار تمام شده باشد.
US_SEARCHING = US_WAITING
# §۴۱ (V6) — اسپکِ کاربر وضعیتِ «داخل گفت‌وگو» را CHATTING صدا می‌زند و
# وضعیتِ انتظار را SEARCHING. V۵ فقط `US_SEARCHING` را alias کرد و کدِ
# خوانا/قابل‌grep نبود (برای لاگ‌های RING_STATE_TRANSITION…to=chatting هم همین
# نام مصرف می‌شود). هیچ مقدارِ تازه‌ای اضافه نشده: همان `US_MATCHED`.
US_CHATTING = US_MATCHED

US_LABELS = {
    US_IDLE: "⚪ آزاد",
    US_PROFILE: "📝 پروفایل ناقص",
    US_READY: "🟢 آمادهٔ جست‌وجو",
    US_WAITING: "🔎 در حال جست‌وجو…",
    US_MATCHED: "💬 در گفت‌وگو",
    US_PAUSED: "⏸ جست‌وجو متوقف",
    US_ENDED: "🔚 گفت‌وگوی اخیر تمام شده",
    US_EXPIRED: "⌛ زمان جست‌وجو تمام شد",
    US_RESTRICTED: "⛔ محدود",
}

# ماشینِ چرخهٔ مچ — برای مستندسازی/اعتبارسنجی؛ گذارِ واقعی را دیتابیس
# (ردیف صف + session) تعیین می‌کند تا زیر هم‌زمانی نشکند (§۶).
USER_STATE_FLOW = {
    US_IDLE: {US_PROFILE, US_READY, US_RESTRICTED},
    US_PROFILE: {US_READY, US_IDLE, US_RESTRICTED},
    US_READY: {US_WAITING, US_PAUSED, US_MATCHED, US_RESTRICTED, US_IDLE},
    # SEARCHING می‌تواند به MATCHED برسد یا با لغو/توقف/اتمام وقت بیرون بیاید
    US_WAITING: {US_MATCHED, US_PAUSED, US_READY, US_IDLE, US_RESTRICTED,
                 US_EXPIRED},
    US_EXPIRED: {US_WAITING, US_READY, US_PAUSED, US_IDLE, US_RESTRICTED},
    US_MATCHED: {US_ENDED, US_RESTRICTED},
    US_ENDED: {US_WAITING, US_READY, US_PAUSED, US_IDLE, US_RESTRICTED},
    US_PAUSED: {US_READY, US_WAITING, US_IDLE, US_RESTRICTED},
    US_RESTRICTED: {US_IDLE},
}

# statusِ ردیف صف ⇒ حالت (ماشینِ §۱۱ V3: waiting → claiming → claimed → in_chat)
_QUEUE_STATE = {
    "waiting": US_WAITING, "claiming": US_WAITING, "claimed": US_WAITING,
    "in_chat": US_MATCHED,
}


def user_state(profile: dict | None, queue_row: dict | None, session: dict | None,
               *, banned: bool = False, ended_recently: bool = False,
               expired_recently: bool = False) -> str:
    """حالتِ واحدِ کاربر — اولویت: محدودیت › گفت‌وگو › صف › پروفایل.

    ⚠️ اگر session فعال باشد هرگز WAITING گزارش نمی‌کنیم، حتی اگر ردیف صف
    به‌خاطر race هنوز `waiting` باشد (§۹/§۵۹: «مچ‌شده در صف نمی‌ماند»).
    """
    if profile is None and not banned:
        return US_IDLE                       # هنوز هیچ پروفایلی نساخته (§۴۲)
    p = profile or {}
    if banned or p.get("status") in ("banned", "restricted", "paused"):
        return US_RESTRICTED
    if session and session.get("status") == "active":
        return US_MATCHED
    st = (queue_row or {}).get("status")
    if st in _QUEUE_STATE:
        return _QUEUE_STATE[st]
    if p.get("search_paused"):
        return US_PAUSED
    if not p.get("age") or not p.get("gender") or not p.get("mode"):
        return US_PROFILE
    if expired_recently:
        return US_EXPIRED                  # §۳۶ — «وقت تمام شد»، نه «آماده»
    if ended_recently:
        return US_ENDED
    return US_READY


def can_move(frm: str | None, to: str) -> bool:
    """ترنزیشن مجاز است؟ حالت ناشناخته ⇒ فقط به IDLE برگردیم (fail-safe)."""
    if not frm or frm == to:
        return True
    return to in TRANSITIONS.get(frm, {IDLE})


def age_ok(age, min_age: int = 18) -> bool:
    try:
        a = int(age)
    except (TypeError, ValueError):
        return False
    return min_age <= a <= 99


def range_of(age: int) -> str:
    for key, _, lo, hi in AGE_RANGES:
        if lo <= int(age) <= hi:
            return key
    return AGE_RANGES[0][0]


def ranges_overlap(a: str | None, b: str | None) -> bool:
    """تداخل دو حلقه (هیچکدام = محدودیتی نیست)."""
    if not a or not b or a == "any" or b == "any":
        return True
    alo, ahi = AGE_INDEX.get(a, (0, 0))
    blo, bhi = AGE_INDEX.get(b, (0, 0))
    return not (ahi < blo or bhi < alo)


def bucket_of(age) -> str | None:
    """بازهٔ سنیِ استاندارد از روی **عددِ** سن (§۸/§۳۶).

    اگر فیلدِ `age_range` ذخیره‌شده با `age` می‌خواند، فرقی نمی‌کند؛ اما اگر
    جایی stale بماند (ویرایش سن، ری‌استارت، دادهٔ دستی ادمین) سنجش باید از
    عدد واقعی انجام شود، وگرنه کاربر «ظاهراً سازگار» رد می‌شود — همان کلاسی
    که در گزارشِ «دو نفر در صف و هیچ مچ» دیده شد.
    """
    try:
        a = int(age)
    except (TypeError, ValueError):
        return None
    for key, _lbl, lo, hi in AGE_RANGES:
        if lo <= a <= hi:
            return key
    return None


def pref_allows(age, age_range, pref_key: str | None) -> bool:
    """آیا `age` داخل بازه‌های انتخابیِ `pref_key` می‌افتد؟ (دوطرفه، §۸/§۳۶)"""
    return age_range_matches(bucket_of(age) or age_range, pref_key)


def age_range_matches(cand_range: str | None, pref_key: str | None) -> bool:
    """preference طرف مقابل: `pref_key` یکی از کلیدهای AGE_RANGES یا
    ترکیبی ('18-20,21-23') یا None است."""
    if not pref_key or pref_key == "any":
        return True
    keys = [k.strip() for k in str(pref_key).split(",") if k.strip()]
    if not keys:
        return True
    return any(ranges_overlap(cand_range, k) for k in keys)


def gender_matches(cand_gender: str | None, pref: str | None) -> bool:
    if not pref or pref in ("any", "", None):
        return True
    return cand_gender == pref


def norm_choice(v, allowed: dict | list | tuple, default=None):
    if isinstance(allowed, dict):
        allowed = list(allowed.keys())
    else:
        allowed = list(allowed)
    if v in allowed:
        return v
    low = str(v or "").strip().lower()
    for a in allowed:
        if str(a).lower() == low:
            return a
    return default


_TEXT_CLEAN = re.compile(r"[\u200b-\u200f\u202a-\u202e<>]")


def clean_text(v, limit: int = 300) -> str:
    """حذف کاراکترهای بی‌نام/RTL-override و تگ — جلوگیری از جعل ظاهری
    و از کارافتادن HTML تلگرام."""
    s = _TEXT_CLEAN.sub("", str(v or ""))
    s = " ".join(s.split())
    return s[:limit]


def has_leak(text: str) -> str | None:
    """§۲۸ — تشخیص ساده‌ی اطلاعات هویتی. هشدار می‌دهد، جلو نمی‌گیرد
    (هیچ فیلتری ۱۰۰٪ نیست و نباید توهم امنیت ایجاد کنیم)."""
    t = str(text or "")
    if re.search(r"(?<!\d)0?9\d{9}(?!\d)", t):
        return "شماره تلفن"
    if re.search(r"@[A-Za-z][A-Za-z0-9_]{4,31}", t):
        return "آیدی تلگرام"
    if re.search(r"\b\d{10,11}\b", t):
        return "شمارهٔ عددی"
    if re.search(r"https?://\S+", t, re.I) or re.search(r"(tg://|t\.me/)", t, re.I):
        return "لینک"
    if re.search(r"\b\d{10}\b|\b\d{3}-?\d{2}-?\d{2}-?\d{6}\b", t):
        return "کد ملی"
    return None
