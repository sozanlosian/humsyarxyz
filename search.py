import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import db
from time_utils import (
    TimeContractError, format_date_fa, parse_clock_time,
    parse_gregorian_date, parse_jalali_date,
)

logger = logging.getLogger(__name__)
SEARCH = 3


async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    mode = context.user_data.pop('search_mode', 'resources')
    context.user_data.pop('awaiting_search', None)

    if mode == 'resources':
        # 🛡 موج QA-Q1 — دو اصلاح امنیتی/انسجامی:
        # ۱) جستجو scope-aware شد (قبلاً بدون intake → عنوان محتوای ورودی
        #    دیگر هم برای دانشجو نمایش داده می‌شد — نشت cross-intake)
        # ۲) callback نتایج به مسیر مدرن bs_dl متصل شد (مسیر قدیمی
        #    download_resource به db.get_resourceِ ناموجود می‌رفت)
        uid = update.effective_user.id
        if await db.is_content_admin(uid):
            _vintake = None  # مدیر محتوا/مالک: پیش‌نمایش بدون فیلتر
        else:
            _u = await db.get_user(uid) or {}
            _vintake = db.student_intake_filter(_u.get('intake', ''))
        results = await db.search_resources(text, intake=_vintake)
        if not results:
            await update.message.reply_text(f"🔍 نتیجه‌ای برای «{text}» پیدا نشد.")
            return ConversationHandler.END
        keyboard = []
        for r in results[:10]:
            rid = str(r['_id'])
            _l = (r.get('_lesson') or {}).get('name', '')
            _t = (r.get('_session') or {}).get('topic', '')
            label = f"📄 {_l} → {_t} | {r.get('type','')}"
            keyboard.append([InlineKeyboardButton(label, callback_data=f'bs_dl:{rid}')])
        await update.message.reply_text(
            f"🔍 <b>{len(results)} نتیجه برای «{text}»</b>",
            parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif mode == 'add_schedule':
        await _add_schedule(update, context, text)

    return ConversationHandler.END



async def _add_schedule(update, context, text):
    import os
    ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
    stype = context.user_data.pop('schedule_type', 'class')
    try:
        parts = [p.strip() for p in text.split(',')]
        if len(parts) < 5:
            raise ValueError("حداقل ۵ فیلد لازم است")
        lesson, teacher, entered_date, time, location = parts[:5]
        notes = parts[5] if len(parts) > 5 else ''
        parsed_date = (parse_jalali_date(entered_date) if '/' in entered_date
                       else parse_gregorian_date(entered_date))
        date = parsed_date.isoformat()
        parse_clock_time(time)
        date_display = format_date_fa(date, long=True, date_only=True)
        await db.add_schedule(stype, lesson, teacher, date, time, location, notes)

        users = await db.notif_users('schedule' if stype != 'exam' else 'exam')
        count = 0
        for u in users:
            if u['user_id'] != ADMIN_ID:
                try:
                    type_fa = {'class': 'کلاس', 'exam': 'امتحان', 'makeup': 'جبرانی'}.get(stype, '')
                    await context.bot.send_message(u['user_id'],
                        f"📅 <b>{type_fa} جدید:</b> {lesson}\n👨‍🏫 {teacher} | {date_display} {time}",
                        parse_mode='HTML')
                    count += 1
                except Exception: pass   # 🛡 §۲۰ — همین الگوی resources.py (bare except ⇒ بلعیدن لغو)

        await update.message.reply_text(
            f"✅ برنامه اضافه شد!\n📌 {lesson} | {date_display} {time}\n🔔 {count} نفر مطلع شدند."
        )
    except (TimeContractError, ValueError) as e:
        await update.message.reply_text(
            f"❌ خطا: {e}\nمثال: آناتومی, دکتر محمدی, 1405/05/24, 09:00, کلاس A2"
        )
    context.user_data.pop('mode', None)
