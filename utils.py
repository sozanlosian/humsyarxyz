"""
🛠️ Utilities — ثابت‌ها، کیبوردها، و توابع کمکی مشترک
"""
import os
import html
import logging
from datetime import datetime
from typing import Optional, List
from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ConversationHandler

logger = logging.getLogger(__name__)

ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))

# ══════════════════════════════════════════════════
#  ثابت‌های مشترک
# ══════════════════════════════════════════════════
TERMS = ['ترم ۱', 'ترم ۲', 'ترم ۳', 'ترم ۴', 'ترم ۵']

CONTENT_TYPES = [
    ('video', '🎥 ویدیو کلاس'),
    ('ppt',   '📊 پاورپوینت'),
    ('pdf',   '📄 جزوه PDF'),
    ('note',  '📝 نکات'),
    ('test',  '🧪 تست'),
    ('voice', '🎙 ویس استاد'),
]

CONTENT_ICONS = {k: v for k, v in CONTENT_TYPES}

NOTIF_LABELS = {
    'new_resources':  '📚 منابع جدید',
    'schedule':       '📅 تغییر برنامه',
    'exam':           '📝 یادآوری امتحان',
    'daily_question': '🧪 سوال روزانه',
}

DIFF_LABELS = {
    'easy':   'آسان 🟢',
    'medium': 'متوسط 🟡',
    'hard':   'سخت 🔴',
}

# ══════════════════════════════════════════════════
#  کیبوردهای ReplyKeyboard
# ══════════════════════════════════════════════════

def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([
        [KeyboardButton("🩺 داشبورد"),     KeyboardButton("📚 منابع")],
        [KeyboardButton("🧪 بانک سوال"),   KeyboardButton("❓ سوالات متداول")],
        [KeyboardButton("🤖 هوشیار"),      KeyboardButton("📅 برنامه")],
        [KeyboardButton("👤 پروفایل"),     KeyboardButton("💎 اشتراک ویژه")],
        [KeyboardButton("💙 حمایت مالی"),  KeyboardButton("🔔 اعلان‌ها")],
        [KeyboardButton("🎫 پشتیبانی")],
    ], resize_keyboard=True)


def content_admin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([
        [KeyboardButton("🩺 داشبورد"),     KeyboardButton("📚 منابع")],
        [KeyboardButton("🧪 بانک سوال"),   KeyboardButton("❓ سوالات متداول")],
        [KeyboardButton("🤖 هوشیار"),      KeyboardButton("📅 برنامه")],
        [KeyboardButton("👤 پروفایل"),     KeyboardButton("💎 اشتراک ویژه")],
        [KeyboardButton("💙 حمایت مالی"),  KeyboardButton("🔔 اعلان‌ها")],
        [KeyboardButton("🎫 پشتیبانی")],
        [KeyboardButton("🎓 پنل محتوا")],
    ], resize_keyboard=True)


def admin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([
        [KeyboardButton("🩺 داشبورد"),     KeyboardButton("📚 منابع")],
        [KeyboardButton("🧪 بانک سوال"),   KeyboardButton("❓ سوالات متداول")],
        [KeyboardButton("🤖 هوشیار"),      KeyboardButton("📅 برنامه")],
        [KeyboardButton("👤 پروفایل"),     KeyboardButton("💎 اشتراک ویژه")],
        [KeyboardButton("💙 حمایت مالی"),  KeyboardButton("🔔 اعلان‌ها")],
        [KeyboardButton("🎫 پشتیبانی")],
        [KeyboardButton("👨‍⚕️ پنل ادمین"), KeyboardButton("🎓 پنل محتوا")],
    ], resize_keyboard=True)


def sub_admin_keyboard() -> ReplyKeyboardMarkup:
    """
    FIX جدید: کیبورد برای کاربرانی که نقش فرعی ادمین دارند
    (support/broadcaster) — دکمه‌های دانشجویی عادی + پنل ادمین محدود.
    """
    return ReplyKeyboardMarkup([
        [KeyboardButton("🩺 داشبورد"),     KeyboardButton("📚 منابع")],
        [KeyboardButton("🧪 بانک سوال"),   KeyboardButton("❓ سوالات متداول")],
        [KeyboardButton("🤖 هوشیار"),      KeyboardButton("📅 برنامه")],
        [KeyboardButton("👤 پروفایل"),     KeyboardButton("💎 اشتراک ویژه")],
        [KeyboardButton("💙 حمایت مالی"),  KeyboardButton("🔔 اعلان‌ها")],
        [KeyboardButton("🎫 پشتیبانی")],
        [KeyboardButton("👨‍⚕️ پنل ادمین")],
    ], resize_keyboard=True)


async def get_keyboard_for_user(user: dict, uid: int) -> ReplyKeyboardMarkup:
    """
    کیبورد مناسب بر اساس نقش کاربر — FIX جدید: حالا async است تا
    بتواند نقش‌های فرعی ادمین (admin_roles) را هم چک کند.

    🔧 FIX (باگ واقعی گزارش‌شده): دکمهٔ «💍 رینگ استریت» باید به **همهٔ**
    نسخه‌های منوی اصلی اضافه شود. قبلاً فقط شاخهٔ آخر (کاربر عادی) آن را
    داشت، پس ادمین/مالک که فیچر را روشن می‌کرد در /start دکمه را نمی‌دید.
    """
    return await ring_aware_keyboard(await _role_keyboard(user, uid))


async def _role_keyboard(user: dict, uid: int) -> ReplyKeyboardMarkup:
    """انتخاب کیبورد بر اساس نقش (بدون در نظر گرفتن فیچر رینگ)."""
    if uid == ADMIN_ID:
        return admin_keyboard()
    role = user.get('role', 'student') if user else 'student'
    if role == 'content_admin':
        return content_admin_keyboard()
    # FIX جدید: چک نقش فرعی (support/broadcaster/content_scoped)
    from database import db
    role_doc = await db.get_admin_role(uid)
    if role_doc:
        sub_role = role_doc.get('role', '')
        if sub_role == 'content_scoped':
            return content_admin_keyboard()
        return sub_admin_keyboard()
    # 🛡 RBAC-W3 (افزایشی — مسیرهای بالا دست‌نخورده‌اند): نقش
    # دیتابی‌سی با مجوز content.*/tickets.reply هم کیبورد متناسب می‌گیرد
    if await db.has_perm(uid, 'content.manage') or \
            await db.has_perm(uid, 'content.scoped'):
        return content_admin_keyboard()
    if await db.has_perm(uid, 'tickets.reply'):
        return sub_admin_keyboard()
    return main_keyboard()


async def ring_aware_keyboard(kb: ReplyKeyboardMarkup) -> ReplyKeyboardMarkup:
    """💍 رینگ استریت — اگر فیچر از پنل روشن باشد، دکمه‌ی «💍 رینگ استریت»
    به کیبورد اصلی اضافه می‌شود (§۴۱ «منوی پویا»).

    • کیبورد موجود mutate نمی‌شود (کالکشن‌های استاتیک این ماژول بین همهٔ
      کاربران به‌اشتراک‌اند؛ پس شیء جدید می‌سازیم).
    • flag از کش سمک خوانده می‌شود؛ اگر کش سرد بود یک refresh کوتاه از DB
      می‌گیریم و خطا یعنی «دکمه نباشد» (fail-safe).
    """
    try:
        from ring import settings as _rs
        # یک query ارزان روی bot_settings/_id=global (فقط در /start) ⇒
        # روشن/خاموش‌کردن از پنل در همان لحظه در منو اثر می‌کند، نه تا
        # ۳۰ ثانیه بعد (job). اگر DB خطا داد: دکمه نباشد (fail-safe).
        await _rs.get_flag()
        if not _rs.flag_sync():
            return kb
        # ⚠️ کیبورد reply آتریبیوت `keyboard` دارد (نه `inline_keyboard`)؛
        # اشتباه در اینجا با except بلعیده می‌شد و دکمه هیچ‌وقت اضافه نمی‌شد.
        rows = [[KeyboardButton("💍 رینگ استریت")]] + [list(r) for r in (kb.keyboard or [])]
        return ReplyKeyboardMarkup(rows, resize_keyboard=True,
                                   one_time_keyboard=getattr(kb, "one_time_keyboard", False),
                                   input_field_placeholder=getattr(kb, "input_field_placeholder", None),
                                   is_persistent=getattr(kb, "is_persistent", None))
    except Exception:
        logger.exception("ring_aware_keyboard failed — منوی بدون دکمهٔ رینگ")
        return kb


# ══════════════════════════════════════════════════
#  دکمه‌های InlineKeyboard کمکی
# ══════════════════════════════════════════════════

def back_btn(label: str = "🔙 بازگشت", cb: str = 'dashboard:refresh') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=cb)]])


def confirm_keyboard(yes_cb: str, no_cb: str,
                     yes_label: str = "✅ بله",
                     no_label: str = "❌ خیر") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(yes_label, callback_data=yes_cb),
        InlineKeyboardButton(no_label, callback_data=no_cb),
    ]])


def paginate(items: list, page: int, per_page: int = 8,
             cb_prefix: str = 'page') -> tuple:
    """برگرداندن صفحه جاری و دکمه‌های ناوبری"""
    total_pages = max(1, (len(items) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    chunk = items[start:start + per_page]

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ قبلی", callback_data=f'{cb_prefix}:{page - 1}'))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("بعدی ▶️", callback_data=f'{cb_prefix}:{page + 1}'))

    return chunk, nav, page, total_pages


# ══════════════════════════════════════════════════
#  توابع فرمت‌بندی
# ══════════════════════════════════════════════════

def progress_bar(pct: float, length: int = 10,
                 fill: str = '█', empty: str = '░') -> str:
    filled = int(min(pct, 100) / 100 * length)
    return fill * filled + empty * (length - filled)


def get_rank(correct_answers: int) -> str:
    if correct_answers >= 200: return "🏆 نخبه"
    if correct_answers >= 100: return "🥇 حرفه‌ای"
    if correct_answers >= 50:  return "🥈 پیشرفته"
    if correct_answers >= 20:  return "🥉 در حال رشد"
    return "🌱 تازه‌کار"


def get_level(pct: float) -> str:
    if pct >= 90: return "🏆 خبره"
    if pct >= 75: return "⭐ پیشرفته"
    if pct >= 60: return "📈 متوسط"
    if pct >= 40: return "📚 مبتدی"
    return "🌱 تازه‌کار"


def exam_countdown(days: int) -> str:
    if days < 0:  return f"({abs(days)} روز پیش)"
    if days == 0: return "🔴 امروز!"
    if days == 1: return "🔴 فردا!"
    if days <= 3: return f"🟠 {days} روز دیگر"
    if days <= 7: return f"🟡 {days} روز دیگر"
    return f"🟢 {days} روز دیگر"


# ══════════════════════════════════════════════════
#  قرارداد مرکزی زمان و تاریخ هامزیار
# ══════════════════════════════════════════════════
# این نام‌ها برای compatibility ماژول‌های قدیمی حفظ شده‌اند؛ تمام منطق
# timezone/calendar در time_utils.py است و این فایل conversion مستقلی ندارد.
from time_utils import (
    TEHRAN, UTC, day_bounds_utc, format_date_fa, format_datetime_fa,
    jalali_to_gregorian, now_tehran as _contract_now_tehran,
    now_utc, parse_gregorian_date, today_tehran, utc_now_iso,
)


def jalali_weekday_index(date_str: str) -> int:
    """Persian calendar UX index: Saturday=0 ... Friday=6."""
    try:
        local_date = parse_gregorian_date(str(date_str)[:10])
        return (local_date.weekday() - 5) % 7
    except (TypeError, ValueError):
        return 0


JALALI_WEEK_SAT_FIRST = ['شنبه', 'یکشنبه', 'دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنج‌شنبه', 'جمعه']


def fmt_jalali(date_str: str) -> str:
    """Display a Gregorian date-only value in Persian/Jalali (no timezone shift)."""
    raw = str(date_str or '').strip()
    if not raw:
        return ''
    return format_date_fa(raw[:10], long=True, weekday=True, date_only=True, fallback=raw)


def now_tehran() -> datetime:
    return _contract_now_tehran()


def today_start_utc_str() -> str:
    start, _next = day_bounds_utc()
    return start.isoformat(timespec='seconds')


def now_tehran_str(with_time: bool = True) -> str:
    current = now_utc()
    return (format_datetime_fa(current, long=True)
            if with_time else format_date_fa(current, long=True))


def fmt_jalali_dt(iso_str, with_time: bool = True) -> str:
    """Display a canonical/legacy UTC machine timestamp as Tehran/Jalali."""
    if iso_str in (None, ''):
        return ''
    return (format_datetime_fa(iso_str, long=True, fallback=str(iso_str))
            if with_time else format_date_fa(iso_str, long=True, fallback=str(iso_str)[:10]))


def days_until(date_str: str) -> int:
    """Days between a Gregorian date-only business day and today in Tehran."""
    try:
        target = parse_gregorian_date(str(date_str)[:10])
        return (target - today_tehran()).days
    except (TypeError, ValueError):
        return 0


# ══════════════════════════════════════════════════
#  هندلر لغو
# ══════════════════════════════════════════════════

async def cancel_handler(update, context):
    """لغو هر عملیات در جریان با /cancel"""
    keys_to_clear = [
        'ca_mode', 'ca_pending_file', 'ca_content_type',
        'ca_edit_target', 'ca_edit_field', 'ca_ref_lang', 'ca_ref_volume',
        'ticket_mode', 'mode', 'creating_question',
        'profile_edit', 'awaiting_search', 'search_mode',
        'edit_user', 'backup_mode',
        'scan_preview', 'pending_schedule', 'schedule_type', 'schedule_edit_sid',
        'edit_schedule_sid', 'edit_schedule_field', 'flex_change_sid',
        # FIX جدید: سیستم اشتراک
        'sub_mode', 'sub_plan_id', 'sub_final_price', 'sub_discount_code',
        'sub_topup_amount',
        'sub_reject_pid', 'suba_target_uid', 'suba_grant_role',
        'suba_plan_edit_id', 'suba_grant_list',
        'grade_intake_scope', 'grade_lesson', 'grade_exam_title',
        'grades_lesson_options', 'grade_matched',
    ]
    for key in keys_to_clear:
        context.user_data.pop(key, None)

    await update.message.reply_text(
        "✅ عملیات لغو شد.\n\nاز دکمه‌های منو استفاده کنید.",
        # فقط ردیف رینگ به همان کیبورد قبلی اضافه می‌شود (منطق نقش‌ها
        # در /cancel عوض نشود) — وگرنه /cancel منوی ادمین را عوض می‌کرد.
        reply_markup=await ring_aware_keyboard(main_keyboard())
    )
    return ConversationHandler.END


# ══════════════════════════════════════════════════
#  🛡 AUDIT-A6 — escape مرکزی HTML برای تلگرام
# ══════════════════════════════════════════════════

def esc(value, dash: str = '', quote: bool = True) -> str:
    """تنها پیاده‌سازی مورد استنادِ escape در پروژه (ربات).

    چرا مرکزی: هر مسیر ربات که ورودیِ کاربر/ادمین را داخل `parse_mode='HTML'`
    می‌گذارد با یکی از دو خطر روبه‌روست — (۱) تزریق markup به مخاطب بعدی
    (لینک جعلی در پیام ادمین) و (۲) `Bad Request: can't parse entities` که
    پیام/پیش‌نمایش را کامل از کار می‌اندازد (مثلاً سوال نظرسنجی «نمره < ۱۰؟»).
    این تابع هر دو را می‌بندد و بر خلاف `html.escape` خالص، داده‌ی ناهمگون
    (None/int/خالی) را هم می‌بلعد و نمی‌ترکد.
    """
    if value is None or value == '':
        return dash
    return html.escape(str(value), quote=quote)


# ══════════════════════════════════════════════════
#  🛡 AUDIT-M1 — مالکیت تسک‌های «آتش‌وبفراموش»
# ══════════════════════════════════════════════════

_BG_TASKS: set = set()


def spawn_bg(coro, name: str = 'bg'):
    """`asyncio.create_task` با صاحب.

    دو مشکل الگوی خام حل می‌شود:
      ۱) اگر هیچ مرجعی به Task نماند، GC می‌تواند تسک را وسط کار بکشد
         (سند رسمی asyncio) — کارهای طولانی مثل broadcast ناپدید می‌شدند.
      ۲) خطای مدیریت‌نشده‌ی تسک فقط در `Task exception was never retrieved`
         ظاهر می‌شد و در production گم می‌شد؛ اینجا warning می‌شود.
    مرجع در ست نگه داشته و در پایان کار آزاد می‌شود ⇒ رشد بی‌نهایت ندارد (§۵۸).
    """
    import asyncio
    task = asyncio.create_task(coro, name=name)
    _BG_TASKS.add(task)

    def _done(t) -> None:
        _BG_TASKS.discard(t)
        if t.cancelled():
            logger.info(f"background task {name} cancelled")
            return
        exc = t.exception()
        if exc is not None:
            logger.warning(f"background task {name} failed: {type(exc).__name__}: {exc}")

    task.add_done_callback(_done)
    return task


# ══════════════════════════════════════════════════
#  ارسال امن پیام (بدون کرش روی Forbidden)
# ══════════════════════════════════════════════════

def safe_send_status(exc) -> str:
    """طبقه‌بندی خطای ارسال — 🛡 AUDIT-A3 (برای صف‌ها).

    بازگشت:
      ``'permanent'`` — بلاک/حذف‌شدن کاربر، چت/پیام ناموجود، محتوای نامعتبر.
                تلاش مجدد هیچ‌وقت جواب نمی‌دهد ⇒ صف باید سند را ببندد.
      ``'backoff'``  — پنالتی تلگرام (RetryAfter); باید به‌مدت
                ``exc.retry_after`` عقب بیفتد، نه اینکه دوباره کوبیده شود.
      ``'retry'``    — شبکه/timeout؛ تلاش مجدد با تاخیر منطقی.

    چرا: مرتب‌سازیِ retry در §۲۹ برای تک‌تک فرستنده‌ها لازم است؛ قبلاً هر
    خطا یک «شکست» بود و صف‌های ماندگار (outbox/کمپین) یا تا ابد retry
    می‌شدند یا پیام را برای همیشه دور می‌ریختند.
    """
    from telegram.error import RetryAfter, Forbidden, BadRequest, TimedOut, NetworkError
    if isinstance(exc, RetryAfter):
        return 'backoff'
    # Forbidden فرزندِ BadRequest است؛ باید قبل از آن بررسی شود
    if isinstance(exc, (Forbidden, BadRequest)):
        return 'permanent'
    if isinstance(exc, (TimedOut, NetworkError)):
        return 'retry'
    return 'retry'


def _split_smart(text: str, limit: int = 4096) -> list:
    """🌊 W5 — برش هوشمند پیام طولانی: جدول/كد را وسط نمی‌برد.
    - ترجيح: برش روی \n\n، سپس \n، سپس فاصله، هرگز وسط code-block یا |…|
    - هر chunk ≤ limit و با header اگر چندتایی شد
    """
    if len(text) <= limit:
        return [text]
    # تشخیص بلوک کد
    chunks = []
    remaining = text
    while len(remaining) > limit:
        # ناحیه امن برای برش
        window = remaining[:limit]
        # اگر داخل بلوک کد هستیم، تا انتهای بلوک صبر کن
        # شمارش ``` در window زوج نیست => داخل کد هستیم
        if window.count("```") % 2 == 1:
            # پیدا کردن بسته شدن
            end = remaining.find("```", limit)
            if end != -1 and end - len(remaining[:limit]) < 800:
                # کمی فراتر برو تا بلوک کامل شود (تا 800 اضافه مجاز)
                cut = end + 3
                if cut > limit and cut < limit + 800:
                    chunks.append(remaining[:cut])
                    remaining = remaining[cut:].lstrip("\n")
                    continue
        # ترجیح برش روی \n\n
        cut = window.rfind("\n\n")
        if cut < limit * 0.5:
            cut = window.rfind("\n")
        if cut < limit * 0.4:
            cut = window.rfind(" ")
        if cut < limit * 0.3:
            cut = limit
        else:
            # برای \n\n شاملش
            if remaining[cut:cut+2] == "\n\n":
                cut += 2
            elif remaining[cut] in ("\n", " "):
                cut += 1
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    # اگر چند chunks، هدر شماره اضافه کن (اختیاری)
    if len(chunks) > 1:
        headered = []
        for i, ch in enumerate(chunks, 1):
            hdr = f"[{i}/{len(chunks)}]\n" if len(chunks) > 1 else ""
            # اگر header + ch > limit، ch را کوتاه کن (نادر)
            if len(hdr) + len(ch) > limit:
                ch = ch[:limit - len(hdr) - 10] + "…"
            headered.append(hdr + ch)
        return headered
    return chunks

async def safe_send_ex(bot, uid: int, text: str, **kwargs):
    """همان safe_send با جزئیات تشخیصی — ``(ok, error_text, exception)``.

    صف‌های ماندگار برای تصمیم «بستن/عقب‌انداختن/تلاش مجدد» به خودِ خطا
    نیاز دارند، نه فقط bool. safe_send روی همین تابع نشسته تا رفتار
    همه‌ی صدازننده‌ها عوض نشود.
    🌊 W5 — اگر text > 4096، برش هوشمند و ارسال چندپیامه (همه یا هیچ نه، best-effort)
    """
    import asyncio
    from telegram.error import RetryAfter, TimedOut, NetworkError, BadRequest
    # 🌊 W5 smart chunk
    parts = _split_smart(text, 4096)
    if len(parts) > 1:
        # ارسال چندپیام با تاخیر کوتاه بین هر chunk تا flood نشود
        for idx, part in enumerate(parts):
            ok, err, exc = await safe_send_ex(bot, uid, part, **kwargs)
            if not ok:
                return False, err, exc
            if idx < len(parts) - 1:
                await asyncio.sleep(0.35)
        return True, "", None
    last_err = None
    for attempt in range(3):
        try:
            await bot.send_message(uid, text, **kwargs)
            return True, "", None
        except Exception as e:
            # 🛡 AUDIT-S1b — در PTB خودِ `BadRequest` فرزندِ `NetworkError` است.
            # الگوی قبلی («هر NetworkError ⇒ retry») باعث می‌شد هر خطای
            # **دائمی** (bot kicked / chat not found / متن Too long / خطای
            # پارس) سه بار با ۱.۵ ثانیه خواب تکرار شود و فالبکِ HTML هرگز
            # اجرا نشود؛ پس رده‌بندی روی نوعِ مشخص انجام می‌شود.
            if isinstance(e, RetryAfter):
                last_err = e
                await asyncio.sleep(min(e.retry_after, 30) + 0.5)
                continue
            if isinstance(e, (TimedOut, NetworkError)) and not isinstance(e, BadRequest):
                last_err = e
                await asyncio.sleep(1.5)
                continue
            # 🛡 AUDIT-S1 — «can't parse entities» تقصیر شبکه نیست: متنِ
            # کاربر escape نشده تگ ناقص می‌سازد و پیام کامل دور ریخته
            # می‌شد. یک بار بدون parse_mode بفرست تا محتوا نرسد به صفِ مرده.
            if kwargs.get('parse_mode') and 'parse' in str(e).lower():
                kw = {k: v for k, v in kwargs.items() if k != 'parse_mode'}
                try:
                    await bot.send_message(uid, text, **kw)
                    logger.info(f"safe_send: parse خطای HTML داشت؛ متن ساده ارسال شد (uid={uid})")
                    return True, "", None
                except Exception as e2:
                    logger.debug(f"safe_send fallback failed for {uid}: {e2}")
                    return False, str(e2), e2
            logger.debug(f"safe_send failed for {uid}: {e}")
            return False, str(e), e
    return False, str(last_err or "send retries exhausted"), last_err


async def safe_send(bot, uid: int, text: str, **kwargs) -> bool:
    """
    ارسال پیام با مدیریت خطا — برای broadcast.

    🐛 باگ واقعی که اینجا بود: این تابع هیچ فرقی بین «کاربر ربات را
    بلاک کرده» (خطای دائمی) و «تلگرام موقتاً محدودمان کرده / خطای
    شبکه‌ی گذرا» (RetryAfter / TimedOut — قابل‌حل با کمی صبر) قائل
    نمی‌شد؛ هر دو را یکسان «ناموفق» می‌شمرد و برای همیشه از دستش
    می‌داد. چون این تابع پایه‌ی broadcast_message است و آن هم پایه‌ی
    اطلاع‌رسانی برنامه/امتحان/منابع جدید در کل ربات، همین یک باگ روی
    همه‌ی کانال‌های اعلان اثر می‌گذاشت. حالا RetryAfter و خطاهای موقت
    شبکه باعث یک صبر کوتاه و تلاش مجدد می‌شوند، نه از دست رفتن پیام.
    """
    ok, _err, _exc = await safe_send_ex(bot, uid, text, **kwargs)
    return ok


async def broadcast_message(bot, users: List[dict], text: str,
                            parse_mode: str = 'HTML') -> tuple:
    """ارسال همگانی — برمی‌گردونه (sent, failed)"""
    import asyncio
    sent, failed = 0, 0
    # ارسال دسته‌ای با تاخیر کم برای جلوگیری از flood
    for i, u in enumerate(users):
        ok = await safe_send(bot, u['user_id'], text, parse_mode=parse_mode)
        if ok:
            sent += 1
        else:
            failed += 1
        if i % 30 == 29:
            await asyncio.sleep(1)  # تنفس بین دسته‌ها
    return sent, failed


# ══════════════════════════════════════════════════
#  لاگ فعالیت حساس — ارسال به گروه‌های مشخص‌شده
# ══════════════════════════════════════════════════

# FIX بازطراحی کامل طبق استاندارد جدید Audit Log:
# هر پیام باید در کمتر از ۵ ثانیه نشان دهد چه کسی/چه نقشی/چه کاری/
# روی چه چیزی/چه تغییری/چه سطح اهمیتی — بدون نیاز به مراجعه به دیتابیس.

SEVERITY_META = {
    'DEBUG':    {'icon': '⚪', 'label': 'DEBUG'},
    'INFO':     {'icon': '🟢', 'label': 'INFO'},
    'LOW':      {'icon': '🔵', 'label': 'LOW'},
    'MEDIUM':   {'icon': '🟡', 'label': 'MEDIUM'},
    'HIGH':     {'icon': '🟠', 'label': 'HIGH'},
    'CRITICAL': {'icon': '🔴', 'label': 'CRITICAL'},
    # Legacy compat
    'WARNING':  {'icon': '🟡', 'label': 'MEDIUM'},
}


def new_correlation_id() -> str:
    """
    🆕 Audit Refactor — HY-YYYYMMDD-XXXXXX (§10)
    قابل جستجو، قابل مرتب‌سازی زمانی، prefix HY برای فیلتر سریع.
    تمام مراحل یک User Action یک correlation_id مشترک دارند.
    Fallback: همچنان uuid کوتاه اگر timezone در دسترس نباشد.
    """
    try:
        from time_utils import now_tehran
        today = now_tehran().strftime("%Y%m%d")
    except Exception:
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
    import uuid
    rand = uuid.uuid4().hex[:6].upper()
    return f"HY-{today}-{rand}"


def new_event_id() -> str:
    """§5 — Event ID یکتای 32hex برای Idempotency (§43)."""
    import uuid
    return uuid.uuid4().hex


def sanitize_audit_data(data):
    """Sanitizer مرکزی — §9: Redact قبل از Persistence."""
    try:
        from audit import sanitize_audit_data as _san
        return _san(data)
    except Exception:
        return data


def get_correlation_id(explicit=None) -> str:
    try:
        from audit import get_correlation_id as _g
        return _g(explicit)
    except Exception:
        return explicit or new_correlation_id()


def _fa_module(module: str) -> str:
    """ترجمه نام ماژول انگلیسی (پایدار در کد) به فارسی (فقط برای نمایش)"""
    from database import db
    return db.MODULE_LABELS_FA.get(module, module)


def build_audit_log_text(category: str, actor_name: str, actor_id: int,
                          action: str, module: str = '', details: str = '',
                          severity: str = 'INFO', actor_role: str = '',
                          target_id: str = '', target_type: str = '',
                          target_label: str = '', before: dict = None,
                          after: dict = None, tags: list = None) -> str:
    """
    🧱 متن نهایی پیام لاگ — حالا Delegate به audit.py مرکزی (§20-§22).
    همان قالب حرفه‌ای، HTML-Safe، تگ‌دار، با before/after خلاصه.
    سازگاری Legacy حفظ شده — تمام فراخوان‌های قدیمی بدون تغییر کار می‌کنند.
    """
    try:
        from audit import build_audit_log_text as _central
        return _central(category, actor_name, actor_id, action, module, details,
                        severity, actor_role, target_id, target_type,
                        target_label, before, after, tags)
    except Exception:
        # Fallback قدیمی اگر audit.py لود نشد — نباید رخ دهد ولی safe است
        pass
    def esc(v) -> str:
        return html.escape(str(v))
    try:
        from audit import normalize_severity
        sev_n = normalize_severity(severity)
    except Exception:
        sev_n = (severity or "INFO").upper()
    sev_meta  = SEVERITY_META.get(sev_n, SEVERITY_META['INFO'])
    cat_icon  = '🛡' if category == 'admin' else '🎓'
    cat_title = 'گزارش فعالیت مدیریتی' if category == 'admin' else 'گزارش فعالیت محتوا'
    now_str   = now_tehran_str()
    module_fa = _fa_module(module) if module else ''
    lines = [
        f"{cat_icon} <b>{cat_title}</b>",
        "", f"🕒 <b>زمان</b>", esc(now_str), "",
        f"👤 <b>انجام‌دهنده</b>",
        f"• نام: {esc(actor_name)}",
        f"• نقش: {esc(actor_role or 'نامشخص')}",
        f"• شناسه: <code>{esc(actor_id)}</code>",
        "", f"⚡ <b>عملیات</b>", esc(action),
    ]
    if target_label or target_id:
        lines += ["", f"🎯 <b>هدف</b>"]
        if target_label: lines.append(f"• عنوان: {esc(target_label)}")
        if target_id: lines.append(f"• شناسه: <code>{esc(target_id)}</code>")
    if module_fa: lines += ["", f"📂 <b>بخش</b>", esc(module_fa)]
    if details: lines += ["", f"📝 <b>جزئیات</b>", esc(details[:800])]
    if before and after:
        change_lines = []
        for key in after:
            old_val = before.get(key, '—')
            new_val = after.get(key, '—')
            change_lines.append(f"• {esc(key)}: {esc(old_val)} ← {esc(new_val)}")
        if change_lines: lines += ["", f"🔄 <b>تغییرات</b>"] + change_lines[:3]
    lines += ["", f"🏷 <b>سطح اهمیت</b>", f"{sev_meta['icon']} {sev_meta['label']}"]
    auto_tags = []
    if module_fa: auto_tags.append(module_fa.replace(' ', '_'))
    if actor_role:
        clean_role = actor_role.split('(')[0].strip().replace(' ', '_')
        if clean_role: auto_tags.append(clean_role)
    all_tags = list(dict.fromkeys(auto_tags + (tags or [])))
    if all_tags: lines += ["", ' '.join(f"#{esc(t)}" for t in all_tags if t)]
    text = '\n'.join(lines)
    if len(text) > 4000: text = text[:3960] + "\n… <i>(ادامه در لاگ دیتابیس)</i>"
    return text


async def send_audit_log(bot, category: str, actor_name: str, actor_id: int,
                          action: str, module: str = '', details: str = '',
                          severity: str = 'INFO', actor_role: str = '',
                          target_id: str = '', target_type: str = '',
                          target_label: str = '', before: dict = None,
                          after: dict = None, tags: list = None,
                          correlation_id: str = None,
                          # 🚀 New optional enriched fields (§5) — backward compat
                          event_id: str = None, actor_type: str = None,
                          source: str = None, channel: str = None,
                          request_id: str = None, ip: str = None,
                          user_agent: str = None, metadata: dict = None,
                          result: str = None, status: str = None,
                          error_code: str = None, error_message: str = None,
                          target_context: dict = None) -> str:
    """
    ثبت در دیتابیس + ارسال همان متن به گروه لاگ تلگرام — نسخه‌ی بازطراحی‌شده §13§35
    ✅ Audit Persistence و Audit Delivery دو مرحله مستقل هستند (§13).
       DB Audit موفق → Business SUCCESS حتی اگر Telegram Fail شود.
       Delivery Failure هرگز Silent نیست (§16): ثبت در delivery_status + retry + alert.
    ✅ Outbox قابل Retry (§14) + Retry Policy طبقه‌بندی‌شده (§15)
    ✅ Business Status vs Logging Status جدا (§12, §35)
    ✅ Sanitization + HTML Safety مرکزی (§9, §22)
    ✅ Correlation / Event ID (§10-§11) + Actor/Target کامل (§6-§8)
    Legacy سازگاری کامل: تمام فراخوان‌های قدیمی بدون تغییر کار می‌کنند.
    """
    # Delegate به audit.py مرکزی — Single Source of Truth §47
    try:
        from audit import audit_event as _audit_event
        # تعیین source/channel اگر نداده
        src = source or ("bot" if bot else "system")
        ch = channel or "telegram"
        # Correlation از context اگر نداده
        corr = correlation_id or get_correlation_id()
        # actor_type اگر نداده — حدس از role
        atype = actor_type
        if not atype:
            if actor_role and "مدیر ارشد" in actor_role: atype = "SUPER_ADMIN"
            elif actor_role and "محتوا" in actor_role: atype = "CONTENT_ADMIN"
            elif actor_role and "ادمین" in actor_role: atype = "ADMIN"
            else: atype = "USER"
        res = await _audit_event(
            bot,
            actor_id=actor_id, actor_name=actor_name, actor_role=actor_role, actor_type=atype,
            module=module or category, category=category, action=action,
            severity=severity, target_id=target_id, target_type=target_type,
            target_label=target_label, before=before, after=after,
            result=result or "SUCCESS", status=status or "SUCCESS",
            source=src, channel=ch, request_id=request_id, correlation_id=corr,
            ip=ip, user_agent=user_agent, metadata=metadata,
            error_code=error_code, error_message=error_message,
            tags=tags, details=details, target_context=target_context,
            telegram_chat_id=None,  # audit_event خودش group را resolve می‌کند
        )
        # Recovery detection (§42) — اگر delivery بعد از downtime موفق شد، recovery event
        # توسط audit.py در _delivery_health ردیابی می‌شود؛ اینجا نیاز به کار اضافی نیست
        # ولی برای سازگاری با فلگ قدیمی log_group_alerted_*, همگام می‌کنیم:
        try:
            from database import db as _db
            from audit import get_delivery_health
            health = get_delivery_health()
            alert_key = f'log_group_alerted_{category}'
            if health.get("is_healthy") and await _db.get_setting(alert_key, False):
                await _db.set_setting(alert_key, False)
                # Recovery notification به گروه (اختیاری — فقط یکبار)
                if health.get("recovered_at"):
                    try:
                        fallback_chat = await _db.get_setting('log_group_admin' if category=='admin' else 'log_group_content', None)
                        if fallback_chat and bot:
                            await bot.send_message(int(fallback_chat),
                                f"🟢 <b>بازیابی سیستم لاگ</b>\n\nارسال لاگ به گروه دوباره برقرار شد.\n⏱ بازیابی: {health['recovered_at']}",
                                parse_mode='HTML')
                    except Exception:
                        pass
            # اگر delivery FAILED بود و فلگ هنوز False است، هشدار یک‌باره (سازگاری با قدیم)
            if res.get("delivery") in ("FAILED", "ENQUEUE_FAILED"):
                if not await _db.get_setting(alert_key, False):
                    await _db.set_setting(alert_key, True)
                    try:
                        group_fa = 'لاگ مدیریت' if category == 'admin' else 'لاگ محتوا'
                        chat_id = await _db.get_setting('log_group_admin' if category=='admin' else 'log_group_content', None)
                        await bot.send_message(
                            ADMIN_ID,
                            f"🚨 <b>ارسال لاگ به گروه {group_fa} ناموفق بود</b>\n\n"
                            f"🔑 گروه فعلی: <code>{chat_id}</code>\n"
                            f"⚠️ خطا: <code>Delivery={res.get('delivery')}</code>\n\n"
                            "💡 ربات از گروه حذف/اخراج شده یا گروه به سوپرگروه تبدیل شده. لطفاً دوباره تنظیمش کن.\n"
                            "لاگ‌ها در دیتابیس محفوظ‌اند و صف Retry فعال است.",
                            parse_mode='HTML')
                    except Exception:
                        pass
        except Exception:
            pass
        return res.get("audit_id") or res.get("event_id")
    except Exception as e:
        # اگر audit.py هر دلیلی fail شد (نباید)، fallback به مسیر قدیمی با log قابل مشاهده (§34)
        logger.exception("audit_event delegation failed, falling back to legacy: %s", e)
        try:
            from database import db as _db2
            log_id = await _db2.log_action(
                actor_id, actor_name, actor_role, action, module, category,
                severity, target_id, target_type, target_label,
                before, after, details, tags, correlation_id,
                event_id=event_id, actor_type=actor_type, source=source, channel=channel,
                request_id=request_id, ip=ip, user_agent=user_agent, metadata=metadata,
                result=result, status=status, error_code=error_code, error_message=error_message,
                target_context=target_context,
            )
        except Exception as e2:
            logger.exception("legacy log_action also failed: %s", e2)
            raise
        # تلاش ارسال best-effort (بدون شکستن business)
        try:
            group_key = 'log_group_admin' if category == 'admin' else 'log_group_content'
            chat_id = await _db2.get_setting(group_key, None)
            if chat_id and bot:
                text = build_audit_log_text(
                    category, actor_name, actor_id, action,
                    module=module, details=details, severity=severity,
                    actor_role=actor_role, target_id=target_id, target_type=target_type,
                    target_label=target_label, before=before, after=after, tags=tags,
                )
                try:
                    await bot.send_message(int(chat_id), text, parse_mode='HTML')
                except Exception as ee:
                    logger.warning(f"send_audit_log fallback delivery failed for chat {chat_id}: {ee}")
        except Exception:
            pass
        return log_id


# ══════════════════════════════════════════════════
#  بررسی حالت تعمیر و نگهداری (Maintenance mode)
# ══════════════════════════════════════════════════

async def is_maintenance_on() -> bool:
    """آیا ربات در حالت تعمیر و نگهداری است؟"""
    from database import db
    return bool(await db.get_setting('maintenance_mode', False))


async def maintenance_message() -> str:
    from database import db
    custom = await db.get_setting('maintenance_text', '')
    if custom:
        return custom
    return (
        "🔧 <b>ربات موقتاً در حال بروزرسانی است</b>\n\n"
        "لطفاً چند دقیقه دیگر دوباره تلاش کنید.\n"
        "از صبر شما سپاسگزاریم 🙏"
    )

# ══════════════════════════════════════════════════
#  🧠 موج N2 — دیپ‌لینک WebApp در DMها (مرکز اعلان ربات)
#  هر رویداد که Link دارد، روی پیام دکمه‌ی web_app
#  (مینی‌اپ به‌جای بازکردن ناوبری) می‌گیرد. سازنده از
#  WEBAPP_URL (همان متغیری که API سرو می‌کند) می‌خواند.
# ══════════════════════════════════════════════════

import os as _os

def webapp_url(link: str = '') -> str:
    """🔗 url مطلق مینی‌اپ برای Deep Link (خود link از / شروع می‌شود).
    اگر WEBAPP_URL تنظیم نشده (محیط لوکال)، None → بدون دکمه.

    🚂 مهاجرت Railway — مقدار درست:
        WEBAPP_URL=https://<domain>/app
    (مینی‌اپ روی پیشوند /app/ سرو می‌شود، نه ریشه‌ی دامنه.)
    این تابع همان source of truth همه‌ی دکمه‌های web_app است، پس یک
    بار تنظیم کردن متغیر، همه‌ی لینک‌ها را جابه‌جا می‌کند.

    دو نکته‌ی رفتاری که اینجا تضمین شده‌اند:
      • هرگز اسلش دوبل ساخته نمی‌شود: /app + /schedule → /app/schedule
        (نه /app//schedule) — با rstrip روی پایه و '/' اجباری روی link
      • query string و fragment داخل link سالم می‌مانند
        ('/me/subscription?tab=pay#x' دست‌نخورده می‌چسبد)
    """
    base = (_os.getenv('WEBAPP_URL') or '').strip()
    if not base or base == '*':
        return None
    if link and not link.startswith('/'):
        link = '/' + link
    if '://' not in base:  # دفاع در برابر host خام — برای link خالی هم لازم است
        base = 'https://' + base
    return (base.rstrip('/') + link) if link else base.rstrip('/')


def webapp_kb(link: str, label: str = '📱 باز کردن در هامزیار'):
    """🧩 InlineKeyboardMarkup تک‌کلیده‌ی web_app — اگر base نداشت None"""
    url = webapp_url(link)
    if not url:
        return None
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(label, web_app=WebAppInfo(url=url))
    ]])


# ─── Audit health helpers (proxy to audit.py مرکزی) ───
def get_audit_delivery_health() -> dict:
    try:
        from audit import get_delivery_health as _h
        return _h()
    except Exception:
        return {"is_healthy": True, "consecutive_failures": 0}

async def get_audit_db_health(days: int = 7) -> dict:
    try:
        from database import db as _db
        return await _db.get_audit_health_metrics()
    except Exception:
        return {}
