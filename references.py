"""
رفرنس‌ها — دانشجو — فیکس کامل دکمه‌های بازگشت
✅ بازگشت صحیح در همه مسیرها
✅ پشتیبانی چند جلد
✅ ذخیره مسیر ناوبری در context
"""
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db

logger = logging.getLogger(__name__)
BRAND_NAME = os.getenv("BRAND_NAME", "HumsyarX")


async def references_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    data   = query.data
    parts  = data.split(':')
    action = parts[1] if len(parts) > 1 else 'main'

    # FIX جدید: دفاع لایه‌دوم اشتراک
    from subscription import feature_allowed
    if not await feature_allowed(update.effective_user.id, "references"):
        await query.answer("🔒 اول باید اشتراک فعال کنی — از «📚 منابع» شروع کن.", show_alert=True)
        return
    await query.answer()

    came_from_admin = context.user_data.get('ref_from_admin', False)

    if action == 'main':
        context.user_data['ref_from_admin']   = False
        context.user_data.pop('ref_subject_id', None)
        context.user_data.pop('ref_book_id', None)
        await _show_subjects(query, back_cb='resources:menu')

    elif action == 'main_admin':
        context.user_data['ref_from_admin']   = True
        context.user_data.pop('ref_subject_id', None)
        context.user_data.pop('ref_book_id', None)
        await _show_subjects(query, back_cb='admin:main')

    elif action == 'subject':
        subject_id = parts[2]
        # 🌊 C1 — ضد ID-manipulation: موضوع ورودی دیگر برای دانشجو باز نمی‌شود
        uid = update.effective_user.id
        if not await db.is_content_admin(uid):
            u = await db.get_user(uid)
            if await db.ref_subject_intake(subject_id) not in \
                    db.student_intake_filter((u or {}).get('intake', '')):
                await query.answer("⛔ این بخش برای ورودی شما نیست.",
                                   show_alert=True); return
        context.user_data['ref_subject_id'] = subject_id
        # بازگشت صحیح: به لیست درس‌ها
        back = 'ref:main_admin' if came_from_admin else 'ref:main'
        await _show_books(query, context, subject_id, back_cb=back)

    elif action == 'book':
        book_id    = parts[2]
        # 🍴 C2 — ضد ID-manipulation روی کتاب + هدایت base جایگزین‌شده به fork
        uid = update.effective_user.id
        if not await db.is_content_admin(uid):
            u = await db.get_user(uid)
            _uint = (u or {}).get('intake', '')
            if await db.ref_book_intake(book_id) not in \
                    db.student_intake_filter(_uint):
                await query.answer("⛔ این بخش برای ورودی شما نیست.",
                                   show_alert=True); return
            _fk = await db.book_superseded_by_fork(book_id, _uint)
            if _fk:
                book_id = str(_fk['_id'])
        subject_id = context.user_data.get('ref_subject_id', '')
        context.user_data['ref_book_id'] = book_id
        # بازگشت صحیح: به لیست کتاب‌های همان درس
        back_cb = f'ref:subject:{subject_id}' if subject_id else ('ref:main_admin' if came_from_admin else 'ref:main')
        await _show_lang_choice(query, context, book_id, back_cb=back_cb)

    elif action == 'volumes':
        # نمایش جلدهای یک زبان خاص
        book_id    = parts[2]
        lang       = parts[3]
        subject_id = context.user_data.get('ref_subject_id', '')
        context.user_data['ref_book_id'] = book_id
        # بازگشت صحیح: به صفحه انتخاب زبان همان کتاب
        back_cb = f'ref:book:{book_id}'
        await _show_volumes(query, context, book_id, lang, back_cb=back_cb)

    elif action == 'dl':
        file_id_db = parts[2]
        await _download_ref(query, file_id_db, update.effective_user.id)


# ══════════════════════════════════════════════════════════
#  نمایش لیست درس‌ها
# ══════════════════════════════════════════════════════════

async def _show_subjects(query, back_cb='resources:menu'):
    # 🌊 C1 — دانشجو فقط موضوعات ورودی خودش + سراسری؛ پیش‌نمایش ادمین بدون فیلتر
    uid = query.from_user.id
    intake = None if await db.is_content_admin(uid) else \
        db.student_intake_filter(((await db.get_user(uid)) or {}).get('intake', ''))
    subjects = await db.ref_get_subjects(intake=intake)
    if not subjects:
        await query.edit_message_text(
            "📚 <b>رفرنس‌ها</b>\n\n❌ هنوز درسی تعریف نشده.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 بازگشت", callback_data=back_cb)
            ]]))
        return
    keyboard = []
    for s in subjects:
        sid = str(s['_id'])
        keyboard.append([InlineKeyboardButton(f"📖 {s['name']}",
                                              callback_data=f'ref:subject:{sid}')])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=back_cb)])
    await query.edit_message_text(
        "📚 <b>رفرنس‌های درسی</b>\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "درس مورد نظر را انتخاب کنید:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard))


# ══════════════════════════════════════════════════════════
#  نمایش کتاب‌های یک درس
# ══════════════════════════════════════════════════════════

async def _show_books(query, context, subject_id, back_cb='ref:main'):
    subject = await db.ref_get_subject(subject_id)
    if not subject:
        await query.answer("❌ درس پیدا نشد!", show_alert=True); return
    # 🍴 موج C2 — نمای مؤثر دانشجو: fork جایگزین base؛ پیش‌نمایش مدیر = همه
    uid = query.from_user.id
    _intake = None if await db.is_content_admin(uid) else \
        db.student_intake_filter(((await db.get_user(uid)) or {}).get('intake', ''))
    books = await db.ref_get_books_effective(subject_id, intake=_intake)
    if not books:
        await query.edit_message_text(
            f"📖 <b>{subject['name']}</b>\n\n❌ رفرنسی برای این درس تعریف نشده.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 بازگشت", callback_data=back_cb)
            ]]))
        return
    keyboard = []
    for b in books:
        bid = str(b['_id'])
        files     = await db.ref_get_files(bid)
        fa_count  = sum(1 for f in files if f.get('lang') == 'fa')
        en_count  = sum(1 for f in files if f.get('lang') == 'en')
        badges    = []
        if fa_count: badges.append(f"🇮🇷×{fa_count}" if fa_count > 1 else "🇮🇷")
        if en_count: badges.append(f"🌐×{en_count}" if en_count > 1 else "🌐")
        badge_str = "  " + "  ".join(badges) if badges else ""
        keyboard.append([InlineKeyboardButton(
            f"📘 {b['name']}{badge_str}", callback_data=f'ref:book:{bid}')])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=back_cb)])
    await query.edit_message_text(
        f"📖 <b>{subject['name']}</b>\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"رفرنس مورد نظر را انتخاب کنید:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard))


# ══════════════════════════════════════════════════════════
#  انتخاب زبان / نسخه
# ══════════════════════════════════════════════════════════

async def _show_lang_choice(query, context, book_id, back_cb='ref:main'):
    """انتخاب زبان — اگه یه جلد داشت مستقیم دانلود، اگه چند جلد داشت صفحه جلدها"""
    book = await db.ref_get_book(book_id)
    if not book:
        await query.answer("❌ کتاب پیدا نشد!", show_alert=True); return

    files = await db.ref_get_files(book_id)
    if not files:
        await query.edit_message_text(
            f"📘 <b>{book['name']}</b>\n\n❌ فایلی برای این رفرنس بارگذاری نشده.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 بازگشت", callback_data=back_cb)
            ]]))
        return

    fa_files = sorted([f for f in files if f.get('lang') == 'fa'],
                      key=lambda x: x.get('volume', 1))
    en_files = sorted([f for f in files if f.get('lang') == 'en'],
                      key=lambda x: x.get('volume', 1))

    keyboard = []

    for lang, lang_files, lang_icon, lang_label in [
        ('fa', fa_files, '🇮🇷', 'ترجمه فارسی'),
        ('en', en_files, '🌐', 'نسخه لاتین (اصلی)'),
    ]:
        if not lang_files:
            continue

        if len(lang_files) == 1:
            f   = lang_files[0]
            fid = str(f['_id'])
            dl  = f.get('downloads', 0)
            disp = (f.get('display_file_name') or f.get('display_name') or '').strip()
            desc = f.get('description', '')
            if disp:
                btn_label = f"{lang_icon} {lang_label} — {disp[:30]} | ⬇️ {dl}"
            elif desc:
                btn_label = f"{lang_icon} {lang_label} — {desc[:20]} | ⬇️ {dl}"
            else:
                btn_label = f"{lang_icon} {lang_label} | ⬇️ {dl}"
            keyboard.append([InlineKeyboardButton(btn_label,
                                                  callback_data=f'ref:dl:{fid}')])
        else:
            total_dl = sum(f.get('downloads', 0) for f in lang_files)
            keyboard.append([InlineKeyboardButton(
                f"{lang_icon} {lang_label} | {len(lang_files)} جلد | ⬇️ {total_dl}",
                callback_data=f'ref:volumes:{book_id}:{lang}'
            )])

    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=back_cb)])

    await query.edit_message_text(
        f"📘 <b>{book['name']}</b>\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"نسخه مورد نظر را انتخاب کنید:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard))


# ══════════════════════════════════════════════════════════
#  نمایش جلدها
# ══════════════════════════════════════════════════════════

async def _show_volumes(query, context, book_id, lang, back_cb='ref:main'):
    """نمایش همه جلدهای یک زبان برای انتخاب"""
    book = await db.ref_get_book(book_id)
    if not book:
        await query.answer("❌ کتاب پیدا نشد!", show_alert=True); return

    files = await db.ref_get_files(book_id)
    lang_files = sorted([f for f in files if f.get('lang') == lang],
                        key=lambda x: x.get('volume', 1))

    if not lang_files:
        await query.answer("❌ فایلی پیدا نشد!", show_alert=True); return

    lang_icon  = '🇮🇷' if lang == 'fa' else '🌐'
    lang_label = 'ترجمه فارسی' if lang == 'fa' else 'نسخه لاتین (اصلی)'

    keyboard = []
    for f in lang_files:
        fid  = str(f['_id'])
        vol  = f.get('volume', 1)
        dl   = f.get('downloads', 0)
        disp = (f.get('display_file_name') or f.get('display_name') or '').strip()
        desc = f.get('description', '')
        # 📄 priority: display name
        if disp:
            btn_label = f"{lang_icon} جلد {vol} — {disp[:35]} | ⬇️ {dl}"
        elif desc:
            btn_label = f"{lang_icon} جلد {vol} — {desc[:20]} | ⬇️ {dl}"
        else:
            btn_label = f"{lang_icon} جلد {vol} | ⬇️ {dl}"

        keyboard.append([InlineKeyboardButton(btn_label,
                                              callback_data=f'ref:dl:{fid}')])

    # بازگشت به صفحه انتخاب زبان
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=back_cb)])

    await query.edit_message_text(
        f"📘 <b>{book['name']}</b>\n"
        f"{lang_icon} <b>{lang_label}</b>\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"جلد مورد نظر را انتخاب کنید:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard))


# ══════════════════════════════════════════════════════════
#  دانلود
# ══════════════════════════════════════════════════════════

async def _download_ref(query, file_id_db, uid):
    item = await db.ref_get_file(file_id_db)
    if not item:
        await query.answer("❌ فایل پیدا نشد!", show_alert=True); return
    # 🌊 C1 — ضد دانلود متقاطع: فایل ورودی دیگر برای دانشجو سرو نمی‌شود
    if not await db.is_content_admin(uid):
        u = await db.get_user(uid)
        _uint = (u or {}).get('intake', '')
        if await db.ref_file_intake(file_id_db) not in \
                db.student_intake_filter(_uint):
            await query.answer("⛔ این فایل برای ورودی شما نیست.",
                               show_alert=True)
            return
        # 🍴 C2 — جایگزینی: دانلود معادلِ fork (اگر کتاب، fork دارد)
        _fork_b = await db.book_superseded_by_fork(item.get('book_id', ''), _uint)
        if _fork_b:
            _fk_file = await db.ref_files.find_one({
                'book_id': str(_fork_b['_id']), 'fork_of': file_id_db})
            if _fk_file:
                item, file_id_db = _fk_file, str(_fk_file['_id'])
    await db.ref_inc_download(file_id_db, uid)

    lang  = item.get('lang', 'fa')
    vol   = item.get('volume', 1)
    desc  = item.get('description', '')
    dl    = item.get('downloads', 0)

    lang_icon  = '🇮🇷' if lang == 'fa' else '🌐'
    lang_label = 'ترجمه فارسی' if lang == 'fa' else 'نسخه لاتین (اصلی)'

    caption_parts = [f"📘 {lang_icon} {lang_label} — جلد {vol}"]
    disp = (item.get('display_file_name') or item.get('display_name') or "").strip()
    if disp:
        caption_parts.append(f"📄 {disp}")
    if desc:
        caption_parts.append(f"📝 {desc}")
    caption_parts.append(f"📥 {dl} دانلود")
    if item.get('branding_enabled') and BRAND_NAME:
        caption_parts.append(f"🏷 {BRAND_NAME}")
    caption = "\n".join(caption_parts)

    # دکمه بازگشت به کتاب
    book_id = str(item.get('book_id', ''))
    back_kb = None
    if book_id:
        back_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 بازگشت به کتاب", callback_data=f'ref:book:{book_id}')
        ]])

    try:
        protect = await db.get_setting('protect_content_enabled', True)
        await query.message.reply_document(
            item['file_id'],
            caption=caption,
            parse_mode='HTML',
            reply_markup=back_kb,
            protect_content=protect)
    except Exception as e:
        logger.error(f"ref download error: {e}")
        await query.answer("❌ خطا در ارسال فایل!", show_alert=True)
