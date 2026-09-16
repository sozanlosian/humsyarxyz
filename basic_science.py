"""
🔬 علوم پایه — دانشجو
  ✅ فیکس دکمه‌های بازگشت — هر لایه به لایه قبل
  ✅ context.user_data برای نگهداری مسیر
  ✅ نمایش سریع با asyncio
"""
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db
from utils import TERMS, CONTENT_ICONS
BRAND_NAME = os.getenv("BRAND_NAME", "HumsyarX")

logger = logging.getLogger(__name__)


async def basic_science_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    data   = query.data
    parts  = data.split(':')
    action = parts[1] if len(parts) > 1 else 'main'

    # FIX جدید: دفاع لایه‌دوم — حتی اگه از دکمه‌ی قدیمیِ توی چت وارد بشه
    if action != 'main_admin':
        from subscription import feature_allowed
        if not await feature_allowed(update.effective_user.id, "resources"):
            await query.answer("🔒 اول باید اشتراک فعال کنی — از «📚 منابع» شروع کن.", show_alert=True)
            return
    await query.answer()

    if action == 'main':
        context.user_data['bs_from_admin'] = False
        await _show_terms(query, back_cb='resources:menu')

    elif action == 'main_admin':
        context.user_data['bs_from_admin'] = True
        await _show_terms(query, back_cb='admin:main')

    elif action == 'term':
        idx  = int(parts[2])
        term = TERMS[idx]
        context.user_data.update({'bs_term': term, 'bs_term_idx': idx})
        fa   = context.user_data.get('bs_from_admin', False)
        back = 'bs:main_admin' if fa else 'bs:main'
        await _show_lessons(query, term, idx, back_cb=back)

    elif action == 'lesson':
        lesson_id = parts[2]
        # 🌊 C1 — ضد ID-manipulation: درسِ ورودی دیگر برای دانشجو باز نمی‌شود
        uid = update.effective_user.id
        if not await db.is_content_admin(uid):
            u = await db.get_user(uid)
            if await db.lesson_intake(lesson_id) not in \
                    db.student_intake_filter((u or {}).get('intake', '')):
                await query.answer("⛔ این بخش برای ورودی شما نیست.",
                                   show_alert=True); return
        context.user_data['bs_lesson_id'] = lesson_id
        idx       = context.user_data.get('bs_term_idx', 0)
        await _show_sessions(query, lesson_id, back_cb=f'bs:term:{idx}')

    elif action == 'session':
        session_id = parts[2]
        # 🌊 C1 — ضد ID-manipulation روی جلسه
        uid = update.effective_user.id
        if not await db.is_content_admin(uid):
            u = await db.get_user(uid)
            if await db.session_intake(session_id) not in \
                    db.student_intake_filter((u or {}).get('intake', '')):
                await query.answer("⛔ این بخش برای ورودی شما نیست.",
                                   show_alert=True); return
            # 🍴 C2 — جلسه‌ی پایه‌ای که fork دارد → هدایت بی‌صدا به نسخه‌ی
            # اختصاصی ورودی خود دانشجو (base همان‌هایی‌ست که جایگزین شده)
            _fk = await db.session_superseded_by_fork(
                session_id, (u or {}).get('intake', ''))
            if _fk:
                session_id = str(_fk['_id'])
        context.user_data['bs_session_id'] = session_id
        lesson_id  = context.user_data.get('bs_lesson_id', '')
        await _show_content(query, session_id, back_cb=f'bs:lesson:{lesson_id}')

    # دانلود محتوا — با پیشوند bs_dl:
    elif data.startswith('bs_dl:'):
        content_id = parts[1]
        await _download_content(query, content_id, update.effective_user.id)


# ══════════════════════════════════════════════════
#  نمایش‌دهنده‌ها
# ══════════════════════════════════════════════════

async def _show_terms(query, back_cb: str = 'resources:menu'):
    keyboard = []
    for i in range(0, len(TERMS), 2):
        row = [InlineKeyboardButton(f"📘 {TERMS[i]}", callback_data=f'bs:term:{i}')]
        if i + 1 < len(TERMS):
            row.append(InlineKeyboardButton(f"📘 {TERMS[i+1]}", callback_data=f'bs:term:{i+1}'))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=back_cb)])
    await query.edit_message_text(
        "🔬 <b>علوم پایه پزشکی</b>\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "ترم تحصیلی خود را انتخاب کنید:\n\n"
        "<i>⚠️ واحدهای هر ترم بر اساس چارت پیشنهادی است.</i>",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _student_view_intake(query) -> list | None:
    """🌊 C1 — scope دید دانشجو: ورودی خودش + سراسری.
    مدیران محتوا (پیش‌نمایش ادمین) None می‌گیرند = بدون فیلتر (رفتار قدیمی)."""
    uid = query.from_user.id
    if await db.is_content_admin(uid):
        return None
    u = await db.get_user(uid)
    return db.student_intake_filter((u or {}).get('intake', ''))


async def _show_lessons(query, term: str, term_idx: int, back_cb: str):
    lessons  = await db.bs_get_lessons(
        term, intake=await _student_view_intake(query))
    keyboard = []
    for l in lessons:
        lid         = str(l['_id'])
        teacher_txt = f" | {l.get('teacher', '')}" if l.get('teacher') else ''
        keyboard.append([InlineKeyboardButton(
            f"📖 {l['name']}{teacher_txt}", callback_data=f'bs:lesson:{lid}'
        )])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=back_cb)])

    if not lessons:
        await query.edit_message_text(
            f"📘 <b>{term}</b>\n\n❌ هنوز درسی تعریف نشده.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    await query.edit_message_text(
        f"📘 <b>{term}</b>\n━━━━━━━━━━━━━━━━\nدرس مورد نظر را انتخاب کنید:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _show_sessions(query, lesson_id: str, back_cb: str):
    lesson   = await db.bs_get_lesson(lesson_id)
    if not lesson:
        await query.answer("❌ درس پیدا نشد!", show_alert=True)
        return
    # 🍴 موج C2 — نمای مؤثر دانشجو: fork جایگزین base می‌شود؛
    # پیش‌نمایش مدیر محتوا = None (همه، رفتار قدیمی)
    sessions = await db.bs_get_sessions_effective(
        lesson_id, intake=await _student_view_intake(query))
    keyboard = []
    for s in sessions:
        sid = str(s['_id'])
        # forkهای خود ورودی با وبج ⭐ نمایش داده می‌شوند
        marker = "⭐ " if s.get('fork_of') else ""
        keyboard.append([InlineKeyboardButton(
            f"{marker}📌 جلسه {s['number']} — {s.get('topic', '')[:30]}",
            callback_data=f'bs:session:{sid}'
        )])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=back_cb)])

    if not sessions:
        await query.edit_message_text(
            f"📖 <b>{lesson['name']}</b>\n\n❌ هنوز جلسه‌ای ثبت نشده.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    await query.edit_message_text(
        f"📖 <b>{lesson['name']}</b>\n"
        f"👨‍🏫 {lesson.get('teacher', '') or '—'}\n"
        f"━━━━━━━━━━━━━━━━\nجلسه مورد نظر را انتخاب کنید:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _show_content(query, session_id: str, back_cb: str):
    session  = await db.bs_get_session(session_id)
    if not session:
        await query.answer("❌ جلسه پیدا نشد!", show_alert=True)
        return
    contents = await db.bs_get_content(session_id)
    keyboard = []

    if contents:
        by_type: dict = {}
        for c in contents:
            by_type.setdefault(c.get('type', 'pdf'), []).append(c)

        for ctype, items in by_type.items():
            icon_label = CONTENT_ICONS.get(ctype, '📎 فایل')
            for item in items:
                cid   = str(item['_id'])
                # 📄 priority: display name > description > type
                disp = (item.get('display_file_name') or item.get('display_name') or '').strip()
                if disp:
                    # truncate label for button (Telegram 64 chars limit)
                    label = f"{icon_label} — {disp[:40]}"
                    # if also has description different from display, append short desc
                    desc = item.get('description','').strip()
                    if desc and desc[:20] not in disp:
                        label = f"{label[:50]}"
                else:
                    desc  = item.get('description', '')[:20]
                    label = icon_label + (f" — {desc}" if desc else '')
                keyboard.append([InlineKeyboardButton(
                    label, callback_data=f'bs_dl:{cid}'
                )])
        content_list = '\n'.join(
            f"  {CONTENT_ICONS.get(t, '📎')} {len(v)} فایل"
            for t, v in by_type.items()
        )
    else:
        content_list = "❌ محتوایی بارگذاری نشده"

    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=back_cb)])
    await query.edit_message_text(
        f"📌 <b>جلسه {session['number']}</b>\n"
        f"📚 {session.get('topic', '')}\n"
        f"👨‍🏫 {session.get('teacher', '') or '—'}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{content_list}\n\n"
        "برای دانلود کلیک کنید:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _download_content(query, content_id: str, uid: int):
    item = await db.bs_get_content_item(content_id)
    if not item:
        await query.answer("❌ فایل پیدا نشد!", show_alert=True)
        return
    # 🌊 C1 — ضد دانلود متقاطع: فایل ورودی دیگر برای دانشجو سرو نمی‌شود
    if not await db.is_content_admin(uid):
        u = await db.get_user(uid)
        _uint = (u or {}).get('intake', '')
        if await db.content_intake(content_id) not in \
                db.student_intake_filter(_uint):
            await query.answer("⛔ این فایل برای ورودی شما نیست.",
                               show_alert=True)
            return
        # 🍴 C2 — دانلود از نسخه‌ی جایگزین‌شده → هدایت به معادلِ fork
        _sess_fk = await db.session_superseded_by_fork(
            item.get('session_id', ''), _uint)
        if _sess_fk:
            _fk_content = await db.bs_content.find_one({
                'session_id': str(_sess_fk['_id']), 'fork_of': content_id})
            if _fk_content:
                item, content_id = _fk_content, str(_fk_content['_id'])
    await db.bs_inc_download(content_id, uid)

    ctype  = item.get('type', 'pdf')
    parts  = [CONTENT_ICONS.get(ctype, '📎')]
    # 📄 display name (new) — show sanitized final name
    disp = (item.get('display_file_name') or item.get('display_name') or "").strip()
    if disp:
        parts.append(f"📄 {disp}")
    if item.get('description'):
        parts.append(f"📝 {item['description']}")
    if item.get('extra_info'):
        parts.append(item['extra_info'])
    parts.append(f"📥 {item.get('downloads', 0)} دانلود")
    # branding tag separate from filename
    if item.get('branding_enabled') and BRAND_NAME:
        parts.append(f"🏷 {BRAND_NAME}")
    caption = '\n'.join(parts)

    # FIX طبق سند: متن دکمه باید عمومی باشد چون فایل می‌تواند
    # PDF/ویدیو/ویس/پاورپوینت باشد — نه فقط «جزوه»
    report_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚠️ گزارش ایراد", callback_data=f'report:resource:{content_id}')
    ]])
    # FIX جدید: محافظت کپی‌رایت — این پرچم دکمه‌ی فوروارد/ذخیره را
    # در اپ رسمی تلگرام برای گیرنده غیرفعال می‌کند (کامل ضدگلوله
    # نیست: اسکرین‌شات را نمی‌گیرد، ولی فوروارد ساده را می‌گیرد)
    # قابل روشن/خاموش از پنل ادمین → 💳 مدیریت اشتراک
    protect = await db.get_setting('protect_content_enabled', True)
    try:
        if ctype == 'video':
            await query.message.reply_video(
                item['file_id'], caption=caption, parse_mode='HTML',
                reply_markup=report_kb, protect_content=protect
            )
        elif ctype == 'voice':
            await query.message.reply_voice(
                item['file_id'], caption=caption, parse_mode='HTML',
                reply_markup=report_kb, protect_content=protect
            )
        else:
            await query.message.reply_document(
                item['file_id'], caption=caption, parse_mode='HTML',
                reply_markup=report_kb, protect_content=protect
            )
    except Exception:
        try:
            await query.message.reply_document(
                item['file_id'], caption=caption, parse_mode='HTML',
                reply_markup=report_kb, protect_content=protect
            )
        except Exception:
            await query.answer("❌ خطا در ارسال فایل!", show_alert=True)
