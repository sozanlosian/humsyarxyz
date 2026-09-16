"""
🚀 Start — ثبت‌نام و ورود کاربر
"""
import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import db
from utils import main_keyboard, admin_keyboard, content_admin_keyboard, get_keyboard_for_user

logger = logging.getLogger(__name__)

ADMIN_ID  = int(os.getenv('ADMIN_ID', '0'))
REGISTER        = 0
STEP_NAME       = 10
STEP_GROUP      = 12
STEP_INTAKE     = 13
STEP_STUDENT_ID = 14   # FIX: مرحله جدید — فقط وقتی require_student_id فعال است


# ══════════════════════════════════════════════════
#  /start
# ══════════════════════════════════════════════════

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid        = update.effective_user.id
    first_name = update.effective_user.first_name or ''
    user       = await db.get_user(uid)

    # ── کاربر جدید ──
    if not user:
        # FIX جدید: بلاک کامل — کاربرانی که با آیدی عددی‌شان بلاک شده‌اند
        # (نه فقط حذف) حتی اجازه‌ی دیدن دکمه‌ی «شروع ثبت‌نام» را ندارند.
        if await db.is_blacklisted(uid):
            context.user_data.clear()
            await update.message.reply_text(
                "🚫 <b>دسترسی مسدود است</b>\n\n"
                "حساب شما توسط مدیریت ربات مسدود شده و امکان ثبت‌نام مجدد وجود ندارد.\n"
                "در صورت اعتراض، از طریق راه‌های ارتباطی خارج از ربات با مدیریت در تماس باشید.",
                parse_mode='HTML'
            )
            return ConversationHandler.END

        context.user_data.clear()
        # 🌱 W13 — لینک دعوت (?start=ref_XXXX)؛ تا پایان ثبت‌نام نگه داشته می‌شود
        try:
            _sargs = getattr(context, 'args', None) or []
            if _sargs:
                import growth_rules as _gr
                _rcode = _gr.parse_ref_start_arg(_sargs[0])
                if _rcode:
                    context.user_data['pending_ref'] = _rcode
        except Exception:
            pass
        await update.message.reply_text(
            f"🩺 <b>به ربات آموزشی پزشکی خوش آمدید!</b>\n\n"
            f"سلام <b>{first_name}</b> عزیز 👋\n\n"
            "این ربات به شما کمک می‌کند:\n"
            "📚 منابع و جزوات درسی\n"
            "🧪 بانک سوال و تمرین هوشمند\n"
            "📅 برنامه کلاس‌ها و امتحانات\n"
            "🎫 پشتیبانی و پاسخ سریع\n\n"
            "━━━━━━━━━━━━━━━━\n"
            "برای شروع، ابتدا ثبت‌نام کنید.\n"
            "فقط <b>۲ مرحله</b> ساده! 🚀",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ شروع ثبت‌نام", callback_data='register:start')
            ]])
        )
        return REGISTER

    # ── در انتظار تأیید ──
    if not user.get('approved') and uid != ADMIN_ID:
        await update.message.reply_text(
            "⏳ <b>در انتظار تأیید</b>\n\n"
            f"سلام <b>{user.get('name', '')}</b> عزیز،\n"
            "ثبت‌نام شما انجام شده و منتظر تأیید ادمین است.\n\n"
            "به زودی دسترسی شما فعال می‌شود. 🙏",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    # FIX: کاربر تأییدشده، اما شماره دانشجویی ندارد و الان اجباری شده
    require_sid = await db.get_setting('require_student_id', False)
    if require_sid and not user.get('student_id') and uid != ADMIN_ID:
        context.user_data['reg_name']   = user.get('name', '')
        context.user_data['reg_group']  = user.get('group', '1')
        context.user_data['reg_intake'] = user.get('intake', '')
        context.user_data['completing_profile'] = True
        await update.message.reply_text(
            "🎓 <b>تکمیل ثبت‌نام لازم است</b>\n\n"
            "ادمین وارد کردن شماره دانشجویی را برای همه دانشجویان الزامی کرده است.\n\n"
            "لطفاً شماره دانشجویی خود را وارد کنید تا بتوانید از ربات استفاده کنید:",
            parse_mode='HTML'
        )
        return STEP_STUDENT_ID

    # ── کاربر تأییدشده ──
    kb = await get_keyboard_for_user(user, uid)   # FIX: حالا async است
    await update.message.reply_text(
        f"🩺 <b>خوش برگشتید {user.get('name', '')} عزیز!</b>",
        parse_mode='HTML',
        reply_markup=kb
    )
    await _show_dashboard(update, context)
    return ConversationHandler.END


# ══════════════════════════════════════════════════
#  ثبت‌نام — Callbacks
# ══════════════════════════════════════════════════

async def register_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == 'register:start':
        uid = update.effective_user.id
        # FIX جدید: لایه‌ی دوم دفاعی — اگر کاربر بعد از دیدن دکمه‌ی
        # «شروع ثبت‌نام» و قبل از لمسش بلاک شده باشد.
        if await db.is_blacklisted(uid):
            context.user_data.clear()
            await query.edit_message_text(
                "🚫 حساب شما توسط مدیریت ربات مسدود شده و امکان ثبت‌نام ندارید."
            )
            return ConversationHandler.END
        context.user_data['reg_step'] = 'name'
        await query.edit_message_text(
            "📝 <b>مرحله ۱ از ۲ — نام و نام خانوادگی</b>\n\n"
            "👤 لطفاً نام کامل خود را بنویسید:\n\n"
            "<i>مثال: علی احمدی</i>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ انصراف", callback_data='register:cancel')
            ]])
        )
        return STEP_NAME

    elif data == 'register:cancel':
        await query.edit_message_text(
            "❌ ثبت‌نام لغو شد.\n\nبرای شروع مجدد /start بزنید."
        )
        return ConversationHandler.END

    elif data == 'register:group1':
        return await _save_group(update, context, '1')

    elif data == 'register:group2':
        return await _save_group(update, context, '2')

    return REGISTER


async def step_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 3:
        await update.message.reply_text("⚠️ نام باید حداقل ۳ حرف باشد. مجدد وارد کنید:")
        return STEP_NAME
    if len(name) > 50:
        await update.message.reply_text("⚠️ نام نباید بیشتر از ۵۰ حرف باشد:")
        return STEP_NAME

    context.user_data['reg_name'] = name

    await update.message.reply_text(
        f"✅ <b>نام ثبت شد:</b> {name}\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📝 <b>مرحله ۲ از ۲ — انتخاب گروه درسی</b>\n\n"
        "👥 گروه خود را انتخاب کنید:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("1️⃣ گروه ۱", callback_data='register:group1'),
                InlineKeyboardButton("2️⃣ گروه ۲", callback_data='register:group2'),
            ],
            [InlineKeyboardButton("❌ انصراف", callback_data='register:cancel')],
        ])
    )
    return STEP_GROUP


async def _save_group(update, context, group: str):
    query    = update.callback_query
    uid      = update.effective_user.id
    username = update.effective_user.username
    name     = context.user_data.get('reg_name', '')

    if not name:
        await query.edit_message_text("❌ خطا. لطفاً /start بزنید.")
        return ConversationHandler.END

    context.user_data['reg_group'] = group

    intakes = await db.get_active_intakes()
    if not intakes:
        return await _after_intake_step(update, context, uid, name, group, '', username, query=query)

    keyboard = [[InlineKeyboardButton(i['label'], callback_data=f'register:intake:{i["code"]}')]
                for i in intakes]
    keyboard.append([InlineKeyboardButton("❌ انصراف", callback_data='register:cancel')])
    await query.edit_message_text(
        f"✅ <b>گروه {group} انتخاب شد</b>\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📝 <b>مرحله ۳ — ورودی تحصیلی</b>\n\n"
        "📅 ورودی خود را انتخاب کنید:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return STEP_INTAKE


async def _after_intake_step(update, context, uid, name, group, intake, username, query=None):
    """
    نقطه‌ی مشترک بعد از انتخاب ورودی — تصمیم می‌گیرد آیا مرحله‌ی
    شماره دانشجویی لازم است (require_student_id) یا مستقیم ثبت‌نام تکمیل شود.
    """
    context.user_data['reg_intake'] = intake
    require_sid = await db.get_setting('require_student_id', False)

    if require_sid:
        text = (
            "✅ <b>اطلاعات قبلی ثبت شد</b>\n\n"
            "━━━━━━━━━━━━━━━━\n"
            "📝 <b>مرحله نهایی — شماره دانشجویی</b>\n\n"
            "🎓 لطفاً شماره دانشجویی خود را وارد کنید:\n"
            "<i>این فیلد برای تکمیل ثبت‌نام الزامی است.</i>"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ انصراف", callback_data='register:cancel')]])
        if query:
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=kb)
        else:
            await update.message.reply_text(text, parse_mode='HTML', reply_markup=kb)
        return STEP_STUDENT_ID

    # FIX جدید: لایه‌ی دوم دفاعی در برابر بلاک — حتی اگر کاربری بین
    # نمایش دکمه‌ی «شروع ثبت‌نام» و رسیدن به همین نقطه بلاک شده باشد.
    if await db.is_blacklisted(uid):
        context.user_data.clear()
        msg = "🚫 حساب شما توسط مدیریت مسدود شده و امکان ثبت‌نام ندارید."
        if query:
            await query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return ConversationHandler.END

    await db.create_user(uid, name, '', group, username, intake=intake)
    # 🌱 W13 — attribution دعوت (exception-safe؛ ثبت‌نام را نمی‌شکند)
    try:
        _pr = context.user_data.pop('pending_ref', None)
        if _pr:
            from referral import attribute as _ref_attribute
            await _ref_attribute(uid, _pr, 'bot')
    except Exception:
        pass
    return await _finish_registration(update, context, uid, name, group, intake, username)


async def step_student_id_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    گرفتن شماره دانشجویی — هم در فلوی ثبت‌نام تازه، هم برای کاربران
    قدیمی که باید پروفایلشان را تکمیل کنند (completing_profile).
    """
    sid = update.message.text.strip()
    if len(sid) < 5:
        await update.message.reply_text("⚠️ شماره دانشجویی باید حداقل ۵ کاراکتر باشد. دوباره وارد کنید:")
        return STEP_STUDENT_ID
    if len(sid) > 30:
        await update.message.reply_text("⚠️ شماره دانشجویی نامعتبر است. دوباره وارد کنید:")
        return STEP_STUDENT_ID

    uid      = update.effective_user.id
    username = update.effective_user.username
    name     = context.user_data.get('reg_name', '')
    group    = context.user_data.get('reg_group', '1')
    intake   = context.user_data.get('reg_intake', '')

    if context.user_data.get('completing_profile'):
        await db.update_user(uid, {'student_id': sid})
        context.user_data.pop('completing_profile', None)
        for k in ('reg_name', 'reg_group', 'reg_intake'):
            context.user_data.pop(k, None)
        user = await db.get_user(uid)
        kb   = await get_keyboard_for_user(user, uid)
        await update.message.reply_text(
            f"✅ <b>شماره دانشجویی ثبت شد!</b>\n\nخوش برگشتید <b>{name}</b> عزیز 🎉",
            parse_mode='HTML', reply_markup=kb
        )
        await _show_dashboard(update, context)
        return ConversationHandler.END

    # FIX جدید: لایه‌ی دوم دفاعی در برابر بلاک (نگاه کنید به _after_intake_step)
    if await db.is_blacklisted(uid):
        context.user_data.clear()
        await update.message.reply_text("🚫 حساب شما توسط مدیریت مسدود شده و امکان ثبت‌نام ندارید.")
        return ConversationHandler.END

    await db.create_user(uid, name, sid, group, username, intake=intake)
    # 🌱 W13 — attribution دعوت (exception-safe؛ ثبت‌نام را نمی‌شکند)
    try:
        _pr = context.user_data.pop('pending_ref', None)
        if _pr:
            from referral import attribute as _ref_attribute
            await _ref_attribute(uid, _pr, 'bot')
    except Exception:
        pass
    return await _finish_registration(update, context, uid, name, group, intake, username)


# ══════════════════════════════════════════════════
#  هندلر انتخاب ورودی در ثبت‌نام
# ══════════════════════════════════════════════════

async def register_intake_callback(update, context):
    """وقتی کاربر ورودی رو انتخاب کرد"""
    query    = update.callback_query
    await query.answer()
    uid      = update.effective_user.id
    username = update.effective_user.username
    intake   = query.data.split(':')[2]
    name     = context.user_data.get('reg_name', '')
    group    = context.user_data.get('reg_group', '1')

    return await _after_intake_step(update, context, uid, name, group, intake, username, query=query)


async def _finish_registration(update, context, uid, name, group, intake, username):
    """پایان ثبت‌نام — اطلاع به ادمین + پیام کاربر"""
    query = update.callback_query
    intake_label = intake or 'نامشخص'

    if uid == ADMIN_ID:
        await db.update_user(uid, {'approved': True})
        await query.edit_message_text(
            f"🎉 <b>ثبت‌نام کامل شد!</b>\n\n"
            f"👤 نام: <b>{name}</b>  |  👥 گروه: <b>{group}</b>\n"
            f"📅 ورودی: <b>{intake_label}</b>\n"
            f"🔑 نقش: <b>ادمین</b>  |  ✅ دسترسی فعال",
            parse_mode='HTML'
        )
        await context.bot.send_message(uid, "به پنل ادمین خوش آمدید! 👨‍⚕️",
            reply_markup=admin_keyboard())
        await _send_dashboard_by_id(context, uid)
    else:
        # طبق درخواست صریح: درخواست ثبت‌نام جدید همیشه به پیوی شخصی
        # ادمین ارشد می‌رود (نه فقط گروه) — چون اقدام فوری لازم دارد.
        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"🔔 <b>درخواست ثبت‌نام جدید</b>\n\n"
                f"👤 نام: <b>{name}</b>\n"
                f"👥 گروه: <b>{group}</b>\n"
                f"📅 ورودی: <b>{intake_label}</b>\n"
                f"📱 یوزرنیم: @{username or 'ندارد'}\n"
                f"🆔 آیدی: <code>{uid}</code>",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ تأیید", callback_data=f'admin:approve:{uid}'),
                    InlineKeyboardButton("❌ رد",    callback_data=f'admin:reject:{uid}'),
                ]])
            )
        except Exception as e:
            logger.warning(f"Cannot notify admin: {e}")

        # FIX جدید: ثبت در Audit Log گروه ادمین هم (severity پایین —
        # رویداد روزمره است، اما باید در تاریخچه باشد)
        from utils import send_audit_log
        await send_audit_log(
            context.bot, 'admin', name, uid,
            "ثبت‌نام کاربر جدید", module='Users', severity='INFO',
            actor_role='دانشجو', target_type='user', target_label=name,
            details=f"گروه: {group} | ورودی: {intake_label}",
            tags=['ثبت_نام']
        )

        await query.edit_message_text(
            f"🎉 <b>ثبت‌نام با موفقیت انجام شد!</b>\n\n"
            f"👤 نام: <b>{name}</b>\n"
            f"👥 گروه: <b>{group}</b>  |  📅 ورودی: <b>{intake_label}</b>\n\n"
            "━━━━━━━━━━━━━━━━\n"
            "⏳ <b>در انتظار تأیید ادمین...</b>\n\n"
            "پس از تأیید، پیام دریافت خواهید کرد. 🙏",
            parse_mode='HTML'
        )

    for k in ('reg_name', 'reg_step', 'reg_group', 'pending_ref'):
        context.user_data.pop(k, None)
    return ConversationHandler.END


# ══════════════════════════════════════════════════
#  توابع کمکی داشبورد
# ══════════════════════════════════════════════════

async def _show_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from dashboard import build_dashboard_text
    uid = update.effective_user.id
    try:
        text, kb = await build_dashboard_text(uid)
        await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=kb)
    except Exception as e:
        logger.error(f"Dashboard error: {e}")


async def _send_dashboard_by_id(context: ContextTypes.DEFAULT_TYPE, uid: int):
    from dashboard import build_dashboard_text
    try:
        text, kb = await build_dashboard_text(uid)
        await context.bot.send_message(uid, text, parse_mode='HTML', reply_markup=kb)
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
