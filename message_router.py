"""
🗺️ Message Router — مسیریابی پیام‌های متنی (دکمه‌های ReplyKeyboard)
"""
import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import db

logger   = logging.getLogger(__name__)
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
SEARCH   = 3


# ══════════════════════════════════════════════════
#  مسیریاب اصلی
# ══════════════════════════════════════════════════

async def route_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text.strip()

    # ══════════════════════════════════════════════════
    # 🛡 بررسی کاربر — همیشه اول از همه اجرا می‌شود
    # ══════════════════════════════════════════════════
    # FIX باگ مهم: قبلاً این چک بعد از همه‌ی شاخه‌های حالت‌محور
    # (ticket_mode، ca_mode، creating_question، awaiting_search) بود.
    # یعنی اگر کاربری وسط یک گفتگو (مثلاً نوشتن تیکت) حذف/بلاک می‌شد،
    # context.user_data['ticket_mode'] هنوز روی حافظه‌ی مکالمه باقی
    # می‌ماند و پیام بعدی‌اش مستقیم به ticket_message_handler می‌رفت —
    # بدون اینکه اصلاً کاربر در دیتابیس وجود داشته باشد. نتیجه: تیکت
    # با نام/شماره‌دانشجویی خالی ثبت می‌شد و کاربر حذف‌شده همچنان
    # می‌توانست بی‌نهایت تیکت (اسپم) بفرستد. با انتقال این چک به همین‌جا
    # —قبل از هر شاخه‌ی دیگر— هیچ حالت آویزونی دیگر قابل‌دور زدن نیست.
    user = await db.get_user(uid)
    if not user:
        context.user_data.clear()   # پاک‌سازی هر state آویزون (ticket_mode و مشابه)
        await update.message.reply_text(
            "لطفاً ابتدا /start را بزنید تا ثبت‌نام کنید."
        )
        return
    if not user.get('approved') and uid != ADMIN_ID:
        await update.message.reply_text("⏳ دسترسی شما هنوز تأیید نشده است.")
        return

    # ── حالت‌های خاص ادمین ──
    # profile_edit برای همه کاربران
    if context.user_data.get('mode') == 'profile_edit':
        from profile import profile_text_handler
        return await profile_text_handler(update, context)

    # 🌊 W10 — روت حالت‌های متنی ادمین با RBAC (به‌جای ADMIN_ID خالص)
    mode = context.user_data.get('mode', '')
    _MODE_PERM = {
        'search_user': 'users.view', 'edit_user': 'users.manage',
        'add_lesson': 'content.manage', 'add_topic': 'content.manage',
        'add_intake': 'settings.manage',
    }
    if mode in _MODE_PERM:
        try:
            _ok = await db.has_permission(uid, _MODE_PERM[mode])
        except Exception:
            _ok = (uid == ADMIN_ID)
        if _ok:
            from admin import handle_admin_text
            await handle_admin_text(update, context)
        else:
            await update.message.reply_text("❌ دسترسی ندارید.")
        return
    # 🌊 W10 — broadcast و اشتراک هم با پرمیشن (نه ADMIN_ID خالص)
    if mode == 'broadcast' or mode == 'sub_reject_reason' or mode.startswith('suba_'):
        _need = ('broadcast.send' if mode == 'broadcast'
                 else 'subscription.manage')
        try:
            _ok = await db.has_permission(uid, _need)
        except Exception:
            _ok = (uid == ADMIN_ID)
        if not _ok:
            await update.message.reply_text("❌ دسترسی ندارید.")
            return
        if mode == 'broadcast':
            from admin import admin_broadcast_handler
            return await admin_broadcast_handler(update, context)
        # FIX جدید: سیستم اشتراک — رد رسید با دلیل
        if mode == 'sub_reject_reason':
            from subscription import admin_reject_reason_handler
            return await admin_reject_reason_handler(update, context)
        # FIX جدید: سیستم اشتراک — همه‌ی حالت‌های متنی پنل مدیریت اشتراک
        if mode.startswith('suba_'):
            from subscription_admin import subscription_admin_text_handler
            return await subscription_admin_text_handler(update, context)

    # FIX جدید: سیستم نمرات — ثبت نمره، هم برای ADMIN_ID هم برای نقش
    # «نماینده‌ی ورودی» (grade_rep)؛ به همین دلیل بیرون از بلاک بالا
    # است که فقط مخصوص ADMIN_ID بود.
    mode = context.user_data.get('mode', '')
    # 🌊 GIFT — حالت‌های خرید هدیه (برای همه‌ی کاربران، نه فقط ادمین)
    if mode in ('gift_recipient', 'gift_message'):
        from subscription import (gift_message_handler,
                                  gift_recipient_handler)
        return await (
            gift_recipient_handler if mode == 'gift_recipient'
            else gift_message_handler
        )(update, context)
    if mode == 'grades_exam_title':
        from grades import handle_exam_title_text
        return await handle_exam_title_text(update, context)
    if mode == 'grades_bulk_list':
        from grades import handle_bulk_list_text
        return await handle_bulk_list_text(update, context)

    # ── ویرایش تک‌فیلدی برنامه (بخش اول) ──
    if context.user_data.get('mode') == 'edit_schedule_field' and (  # 🌊 W10
            await db.has_permission(uid, 'schedules.manage')):
        from schedule import handle_edit_schedule_field_text
        return await handle_edit_schedule_field_text(update, context)

    # ── حالت ساخت سؤال؛ اشتراک در هر پیام دوباره server-side بررسی می‌شود ──
    if context.user_data.get('mode') == 'creating_question':
        from subscription import feature_allowed
        if not await feature_allowed(uid, "question_bank"):
            context.user_data.pop('mode', None); context.user_data.pop('create_step', None)
            await update.message.reply_text("🔒 اشتراک فعال نیست؛ پیش‌نویس ارسال نشد.")
            return
        from questions import handle_create_question_steps
        return await handle_create_question_steps(update, context)

    # ── دلیل بررسی سؤال توسط reviewer/admin ──
    if context.user_data.get('mode') == 'question_review_reason':
        from questions import handle_question_review_reason_text
        return await handle_question_review_reason_text(update, context)

    # ── حالت ادمین محتوا ──
    ca_text_modes = {
        'add_lesson', 'add_session', 'waiting_description',
        'waiting_ref_description', 'add_faq', 'add_ref_subject',
        'add_ref_book', 'edit_lesson', 'edit_session',
        'edit_ref_subject', 'edit_ref_book',
    }
    if context.user_data.get('ca_mode') in ca_text_modes:
        if await db.is_content_admin(uid):
            from content_admin import ca_text_handler
            return await ca_text_handler(update, context)

    # ── تیکت ──
    if context.user_data.get('ticket_mode') in (
        'waiting_message', 'admin_reply', 'user_reply',
        'admin_search', 'awaiting_confirm'
    ):
        from ticket import ticket_message_handler
        return await ticket_message_handler(update, context)

    # ticket_search — جستجوی تیکت توسط ادمین
    if context.user_data.get('mode') == 'ticket_search':
        from ticket import ticket_message_handler
        return await ticket_message_handler(update, context)

    # ── جستجو ──
    if context.user_data.get('awaiting_search'):
        from search import search_handler
        return await search_handler(update, context)

    # FIX جدید: کد تخفیف اشتراک
    if context.user_data.get('sub_mode') == 'awaiting_discount':
        from subscription import discount_text_handler
        return await discount_text_handler(update, context)

    # 🌊 W6.2 — مبلغ دلخواه شارژ کیف پول
    if context.user_data.get('sub_mode') == 'awaiting_topup_amount':
        from subscription import topup_amount_text_handler
        return await topup_amount_text_handler(update, context)

    # 🌊 W8/MISS-03 — کد دعوت خانواده
    if context.user_data.get('sub_mode') == 'awaiting_family_code':
        from subscription import family_code_text_handler
        return await family_code_text_handler(update, context)

    # ── مسیریابی دکمه‌های منو ──
    await _route_menu_button(update, context, text, uid, user)


async def _route_menu_button(update, context, text: str, uid: int, user: dict):
    """مسیریابی دکمه‌های کیبورد اصلی"""

    if text == "🩺 داشبورد":
        from dashboard import build_dashboard_text
        t, kb = await build_dashboard_text(uid)
        await update.message.reply_text(t, parse_mode='HTML', reply_markup=kb)

    elif text == "📚 منابع":
        from subscription import check_and_show_paywall
        if not await check_and_show_paywall(update, context, uid,
                                            feature="resources"):
            return
        keyboard = [
            [InlineKeyboardButton("🔬 علوم پایه", callback_data='bs:main')],
            [InlineKeyboardButton("📖 رفرنس‌ها",  callback_data='ref:main')],
        ]
        await update.message.reply_text(
            "📚 <b>منابع درسی</b>\n\n"
            "━━━━━━━━━━━━━━━━\n"
            "🔬 <b>علوم پایه:</b> محتوای جلسات (ویدیو، جزوه، پاورپوینت و...)\n"
            "📖 <b>رفرنس‌ها:</b> کتاب‌های مرجع درسی (PDF فارسی/لاتین)",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif text == "🧪 بانک سوال":
        from subscription import check_and_show_paywall
        if not await check_and_show_paywall(update, context, uid,
                                            feature="question_bank"):
            return
        from questions import _main_menu_msg
        await _main_menu_msg(update.message)

    elif text == "🤖 هوشیار":
        from ai_solver import show_ai_intro
        await show_ai_intro(update, context)

    elif text == "❓ سوالات متداول":
        from faq import show_faq_main
        await show_faq_main(update.message)

    elif text == "📅 برنامه":
        from schedule import show_schedule_main
        await show_schedule_main(update.message, uid, user)

    elif text == "👤 پروفایل":
        from profile import show_profile_msg
        await show_profile_msg(update)

    elif text == "💎 اشتراک ویژه":
        from subscription import show_my_status_msg
        await show_my_status_msg(update)

    elif text == "💙 حمایت مالی":
        donation_enabled = await db.get_setting('donation_enabled', False)
        donation_link    = await db.get_setting('donation_link', None)
        if donation_enabled and donation_link:
            await update.message.reply_text(
                "💙 <b>حمایت مالی از هامزیار</b>\n\n"
                "اگه دلت می‌خواد به ادامه‌دار بودن و پیشرفت این ربات کمک کنی، "
                "می‌تونی از لینک زیر حمایت کنی. هر مقداری، بزرگ باشه یا کوچیک، "
                "قدردانی می‌شه 🙏",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💙 حمایت مالی", url=donation_link)]])
            )
        else:
            await update.message.reply_text("💙 این بخش فعلاً فعال نیست.")

    elif text == "🔔 اعلان‌ها":
        from notifications import show_notif_settings
        await show_notif_settings(update.message, uid)

    elif text == "🎫 پشتیبانی":
        from ticket import show_ticket_main
        await show_ticket_main(update.message, uid)

    elif text == "🎓 پنل محتوا":
        if await db.is_content_admin(uid):
            from content_admin import show_ca_main
            # 🌊 C1 — context پاس داده می‌شود تا اسکوپ ورودی (انتخاب‌شده
            # یا قفل‌شده) از user_data خوانده/نوشته شود
            await show_ca_main(update.message, uid, context)
        else:
            await update.message.reply_text("❌ دسترسی ندارید.")

    elif text == "👨‍⚕️ پنل ادمین":
        # FIX جدید: ادمین ارشد یا هر کاربر با نقش فرعی (support/broadcaster/...)
        if uid == ADMIN_ID:
            from admin import show_admin_main
            await show_admin_main(update.message, uid)
        else:
            # 🛡 FIX پاریتیِ RBAC: این گیت فقط `admin_roles` میراثی را
            # می‌دید، در حالی که `admin_callback` (همان پنل، یک لایه
            # جلوتر) از مدت‌ها پیش نقش‌های دیتابیس‌محور را هم می‌پذیرد.
            # نتیجه: نقشی که در پنل وب ساخته می‌شد و هنوز projection
            # میراثی نداشت، اصلاً نمی‌توانست پنل ربات را باز کند — هرچند
            # مجوزهایش کاملاً معتبر بود. حالا هر دو منبع پذیرفته می‌شوند
            # (همان ترتیبِ admin_callback) تا Bot/Mini App/Web Admin یک
            # تصمیم واحد بگیرند. منوی داخل _admin_menu از قبل بر اساس
            # همین مجوزها فیلتر می‌شود، پس دسترسی اضافه‌ای باز نمی‌شود.
            role_doc = await db.get_admin_role(uid)
            if not role_doc:
                role_doc = bool(await db.get_user_perms(uid))
            if role_doc:
                from admin import show_admin_main
                await show_admin_main(update.message, uid)
            else:
                await update.message.reply_text("❌ دسترسی ندارید.")

    elif text == "🔍 جستجو":
        context.user_data['awaiting_search'] = True
        context.user_data['search_mode']     = 'resources'
        await update.message.reply_text(
            "🔍 <b>جستجو</b>\n\nکلمه‌ای که دنبالش هستید را بنویسید:",
            parse_mode='HTML'
        )

    else:
        # پیام نامشناخته — راهنمای سریع
        await update.message.reply_text(
            "از دکمه‌های منو استفاده کنید یا /start بزنید.",
        )
