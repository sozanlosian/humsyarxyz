"""
👨‍⚕️ پنل ادمین — نسخه کامل و حرفه‌ای
  ✅ broadcast پیشرفته: preview + تأیید + ارسال به گروه خاص + ارسال زماندار
  ✅ فیکس باگ duplicate key در restore بکاپ
  ✅ فیکس سرچ کاربران
  ✅ pagination و filter کاربران
"""
import os
import asyncio
BROADCAST_SEM = asyncio.Semaphore(1)  # 🌊 W3 — یک broadcast در لحظه، جلوگیری از گرسنگی jobهای دیگر
import logging
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    Message
)
from telegram.ext import ContextTypes, ConversationHandler
from telegram.error import RetryAfter, Forbidden, BadRequest, TimedOut, NetworkError
from database import db
from broadcast_service import (
    create_campaign as create_broadcast_campaign,
    resolve_recipients as resolve_broadcast_recipients,
    send_payload as send_broadcast_payload,
    finish_direct as finish_broadcast_direct,
)
from utils import (
    main_keyboard, content_admin_keyboard, safe_send,
    esc as _esc,                                  # 🛡 AUDIT-A6 — escape مرکزی پروژه
    send_audit_log, get_keyboard_for_user, fmt_jalali_dt, now_tehran, now_tehran_str,
)
from time_utils import fa_digits, format_time_fa, now_utc, parse_machine_datetime

logger   = logging.getLogger(__name__)
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
BROADCAST = 5   # نگه داشته شده برای سازگاری با bot.py


async def _admin_menu(query_or_msg, edit: bool = True, uid: int = None):
    """
    FIX جدید: منو بر اساس نقش فیلتر می‌شود —
    ADMIN_ID همه‌چیز می‌بیند، نقش‌های فرعی فقط بخش مجاز خودشان.
    """
    s     = await db.global_stats()
    role  = None
    if uid is not None and uid != ADMIN_ID:
        role_doc = await db.get_admin_role(uid)
        role = role_doc.get('role') if role_doc else None
        # 🛡 RBAC-W3 (افزایشی): بدون نقش میراثی ولی با مجوز RBAC —
        # دیدِ منو از Permission حدس زده می‌شود (§۸ Permission-Driven)
        if role is None:
            if await db.has_perm(uid, 'content.manage'):
                role = 'content_admin'
            elif await db.has_perm(uid, 'content.scoped'):
                role = 'content_scoped'
            elif await db.has_perm(uid, 'tickets.reply'):
                role = 'support'
            elif (await db.has_perm(uid, 'schedules.manage')
                  and await db.has_perm(uid, 'users.view')):
                role = 'bot_admin'
            elif await db.has_perm(uid, 'grades.scoped'):
                role = 'grade_rep'

    # نقش پشتیبان: منوی بسیار محدود
    if role == 'support':
        keyboard = [
            [InlineKeyboardButton("🎫 مدیریت تیکت‌ها", callback_data='ticket:admin_list')],
        ]
        text = "🎫 <b>پنل پشتیبان</b>\n━━━━━━━━━━━━━━━━\nشما فقط به مدیریت تیکت‌ها دسترسی دارید."
        markup = InlineKeyboardMarkup(keyboard)
        try:
            if edit and hasattr(query_or_msg, 'edit_message_text'):
                await query_or_msg.edit_message_text(text, parse_mode='HTML', reply_markup=markup)
            else:
                msg = query_or_msg if hasattr(query_or_msg, 'reply_text') else query_or_msg.message
                await msg.reply_text(text, parse_mode='HTML', reply_markup=markup)
        except Exception as e:
            logger.debug(f"_admin_menu(support): {e}")
        return

    # نقش مسئول اطلاعیه: فقط broadcast
    if role == 'broadcaster':
        keyboard = [
            [InlineKeyboardButton("📢 ارسال همگانی", callback_data='admin:broadcast')],
        ]
        text = "📢 <b>پنل مسئول اطلاعیه</b>\n━━━━━━━━━━━━━━━━"
        markup = InlineKeyboardMarkup(keyboard)
        try:
            if edit and hasattr(query_or_msg, 'edit_message_text'):
                await query_or_msg.edit_message_text(text, parse_mode='HTML', reply_markup=markup)
            else:
                msg = query_or_msg if hasattr(query_or_msg, 'reply_text') else query_or_msg.message
                await msg.reply_text(text, parse_mode='HTML', reply_markup=markup)
        except Exception as e:
            logger.debug(f"_admin_menu(broadcaster): {e}")
        return

    # مدیر محتوای کلی هم نباید منوی تنظیمات/حذف کاربرِ مالک را ببیند؛
    # فقط مسیرهای محتوایی و بازبینی سؤال در اختیار اوست.
    if role == 'content_admin':
        keyboard = [
            [InlineKeyboardButton("🎓 رفتن به پنل محتوا", callback_data='ca:main')],
            [InlineKeyboardButton("🧪 بازبینی سؤال‌ها", callback_data='questions:ca_q_list')],
            [InlineKeyboardButton("⚠️ گزارشات سوال/جزوه", callback_data='report:manage:all')],
        ]
        text = "🎓 <b>پنل مدیر محتوا</b>\n━━━━━━━━━━━━━━━━\nدسترسی فقط به محتوای آموزشی و بازبینی سؤال‌ها."
        markup = InlineKeyboardMarkup(keyboard)
        try:
            if edit and hasattr(query_or_msg, 'edit_message_text'):
                await query_or_msg.edit_message_text(text, parse_mode='HTML', reply_markup=markup)
            else:
                msg = query_or_msg if hasattr(query_or_msg, 'reply_text') else query_or_msg.message
                await msg.reply_text(text, parse_mode='HTML', reply_markup=markup)
        except Exception as e:
            logger.debug(f"_admin_menu(content_admin): {e}")
        return

    # FIX امنیتی: content_scoped باید به پنل محتوا هدایت شود،
    # نه منوی کامل ادمین ارشد را ببیند.
    if role == 'content_scoped':
        keyboard = [
            [InlineKeyboardButton("🎓 رفتن به پنل محتوا", callback_data='ca:main')],
        ]
        text = (
            "📅 <b>پنل ادمین محتوای ورودی خاص</b>\n━━━━━━━━━━━━━━━━\n\n"
            "شما فقط به محتوای ورودی خاص خودتان دسترسی دارید.\n"
            "از دکمه زیر وارد پنل محتوا شوید:"
        )
        markup = InlineKeyboardMarkup(keyboard)
        try:
            if edit and hasattr(query_or_msg, 'edit_message_text'):
                await query_or_msg.edit_message_text(text, parse_mode='HTML', reply_markup=markup)
            else:
                msg = query_or_msg if hasattr(query_or_msg, 'reply_text') else query_or_msg.message
                await msg.reply_text(text, parse_mode='HTML', reply_markup=markup)
        except Exception as e:
            logger.debug(f"_admin_menu(content_scoped): {e}")
        return

    # FIX جدید: نقش خرخون — فقط دسترسی به بررسی گزارش سوال/جزوه
    if role == 'reviewer':
        keyboard = [
            [InlineKeyboardButton("⚠️ گزارشات سوال/جزوه", callback_data='report:manage:all')],
        ]
        text = "🤓 <b>پنل خرخون</b>\n━━━━━━━━━━━━━━━━\nشما به بررسی گزارشات سوال و جزوه دسترسی دارید."
        markup = InlineKeyboardMarkup(keyboard)
        try:
            if edit and hasattr(query_or_msg, 'edit_message_text'):
                await query_or_msg.edit_message_text(text, parse_mode='HTML', reply_markup=markup)
            else:
                msg = query_or_msg if hasattr(query_or_msg, 'reply_text') else query_or_msg.message
                await msg.reply_text(text, parse_mode='HTML', reply_markup=markup)
        except Exception as e:
            logger.debug(f"_admin_menu(reviewer): {e}")
        return

    # FIX جدید: نماینده‌ی ورودی — فقط دسترسی به ثبت نمره (محدود به ورودی خودش)
    if role == 'grade_rep':
        scope = role_doc.get('scope_intake', '')
        keyboard = [
            [InlineKeyboardButton("📊 ثبت نمره‌ی جدید", callback_data='grades:new')],
            [InlineKeyboardButton("📋 نمرات ثبت‌شده", callback_data='grades:list:0')],
        ]
        text = (
            f"📊 <b>پنل نمرات — نماینده‌ی ورودی {scope}</b>\n━━━━━━━━━━━━━━━━\n"
            "شما فقط می‌توانید برای دانشجویان همین ورودی نمره ثبت کنید."
        )
        markup = InlineKeyboardMarkup(keyboard)
        try:
            if edit and hasattr(query_or_msg, 'edit_message_text'):
                await query_or_msg.edit_message_text(text, parse_mode='HTML', reply_markup=markup)
            else:
                msg = query_or_msg if hasattr(query_or_msg, 'reply_text') else query_or_msg.message
                await msg.reply_text(text, parse_mode='HTML', reply_markup=markup)
        except Exception as e:
            logger.debug(f"_admin_menu(grade_rep): {e}")
        return

    # FIX RBAC: این منو فقط برای bot_admin است. بلوک قبلی بدون شرط بود و
    # باعث می‌شد ADMIN_ID هم به‌جای منوی کامل، منوی نماینده را ببیند.
    if role == 'bot_admin':
        keyboard = [
            [InlineKeyboardButton("👥 مدیریت کاربران",  callback_data='admin:users:0')],
            [
                InlineKeyboardButton("📅 برنامه جدید",  callback_data='schedule:add_type'),
                InlineKeyboardButton("✏️ ویرایش برنامه", callback_data='schedule:manage_types'),
            ],
            [InlineKeyboardButton("🗑 حذف برنامه",   callback_data='schedule:del_list')],
            [InlineKeyboardButton("📢 ارسال همگانی",    callback_data='admin:broadcast')],
        ]
        text = "👮 <b>پنل ادمین ربات (نماینده)</b>\n━━━━━━━━━━━━━━━━\nدسترسی محدود — بدون تنظیمات حیاتی."
        markup = InlineKeyboardMarkup(keyboard)
        try:
            if edit and hasattr(query_or_msg, 'edit_message_text'):
                await query_or_msg.edit_message_text(text, parse_mode='HTML', reply_markup=markup)
            else:
                msg = query_or_msg if hasattr(query_or_msg, 'reply_text') else query_or_msg.message
                await msg.reply_text(text, parse_mode='HTML', reply_markup=markup)
        except Exception as e:
            logger.debug(f"_admin_menu(bot_admin): {e}")
        return

    # فقط ادمین ارشد به این نقطه می‌رسد — منوی کامل
    # FIX جدید: منوی شلوغ قبلی (بیش از ۲۰ دکمه تخت) به ۵ دسته‌ی
    # موضوعی دسته‌بندی شد تا پیمایش پنل ادمین ساده‌تر و تمیزتر شود.
    # همه‌ی callback_dataهای قدیمی دست‌نخورده باقی مانده‌اند — فقط
    # لایه‌ی ناوبری جدید روی همان اکشن‌های قبلی اضافه شده.
    keyboard = [
        [InlineKeyboardButton(
            f"📊 آمار سیستم  ({s['users']} کاربر | {s.get('open_tickets', 0)} تیکت باز)",
            callback_data='admin:stats'
        )],
        [InlineKeyboardButton("⚠️ نیازمند اقدام (بستن هشدار)", callback_data='admin:attention')],
        [InlineKeyboardButton("🧠 مرکز هوش ربات (هشدار و پیش‌بینی)", callback_data='admin:insights')],
        [
            InlineKeyboardButton("👥 کاربران و دسترسی‌ها", callback_data='admin:cat_users'),
            InlineKeyboardButton("📚 محتوای آموزشی",        callback_data='admin:cat_content'),
        ],
        [
            InlineKeyboardButton("📅 برنامه کلاسی",         callback_data='admin:cat_schedule'),
            InlineKeyboardButton("📢 ارتباط با کاربران",     callback_data='admin:cat_comm'),
        ],
        [InlineKeyboardButton("⚙️ تنظیمات و سیستم", callback_data='admin:cat_settings')],
    ]
    text   = "👨‍⚕️ <b>پنل مدیریت</b>\n━━━━━━━━━━━━━━━━"
    markup = InlineKeyboardMarkup(keyboard)
    try:
        if edit and hasattr(query_or_msg, 'edit_message_text'):
            await query_or_msg.edit_message_text(text, parse_mode='HTML', reply_markup=markup)
        else:
            msg = query_or_msg if hasattr(query_or_msg, 'reply_text') else query_or_msg.message
            await msg.reply_text(text, parse_mode='HTML', reply_markup=markup)
    except Exception as e:
        logger.debug(f"_admin_menu: {e}")


async def _show_cat_users(query, uid: int = None):
    """👥 دسته: کاربران و دسترسی‌ها"""
    keyboard = [
        [
            InlineKeyboardButton("👥 مدیریت کاربران",  callback_data='admin:users:0'),
            InlineKeyboardButton("⏳ تأیید کاربران",   callback_data='admin:pending'),
        ],
        [InlineKeyboardButton("🔍 جستجوی کاربر",       callback_data='admin:search_user')],
        [InlineKeyboardButton("📅 مدیریت ورودی‌ها",    callback_data='admin:intakes')],
        [InlineKeyboardButton("🎓 ادمین‌های محتوا",     callback_data='admin:content_admins')],
        [InlineKeyboardButton("🚫 لیست مسدودها (بلک‌لیست)", callback_data='admin:blacklist_view')],
    ]
    if uid is None or uid == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("🛡 سطوح دسترسی ادمین", callback_data='admin:roles')])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:main')])
    await query.edit_message_text(
        "👥 <b>کاربران و دسترسی‌ها</b>\n━━━━━━━━━━━━━━━━",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_cat_content(query):
    """📚 دسته: محتوای آموزشی"""
    keyboard = [
        [
            InlineKeyboardButton("📘 علوم پایه",   callback_data='ca:terms_admin'),
            InlineKeyboardButton("📚 رفرنس‌ها",     callback_data='ca:refs_admin'),
        ],
        [InlineKeyboardButton("❓ مدیریت FAQ",      callback_data='ca:faq_admin')],
        [
            InlineKeyboardButton("🧪 بازبینی سؤال‌ها", callback_data='questions:ca_q_list'),
            InlineKeyboardButton("✅ تأیید سوالات", callback_data='admin:pending_q'),
        ],
        [InlineKeyboardButton("⚠️ گزارشات سوال/جزوه", callback_data='report:manage:all')],
        [InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:main')],
    ]
    await query.edit_message_text(
        "📚 <b>محتوای آموزشی</b>\n━━━━━━━━━━━━━━━━",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_cat_schedule(query):
    """📅 دسته: برنامه کلاسی"""
    keyboard = [
        [
            InlineKeyboardButton("📅 برنامه جدید", callback_data='schedule:add_type'),
            InlineKeyboardButton("🗑 حذف برنامه",  callback_data='schedule:del_list'),
        ],
        [InlineKeyboardButton("📸 اسکن با هوشیار (عکس جدول → الگو)", callback_data='schedule:scan_menu')],
        [InlineKeyboardButton("✏️ ویرایش برنامه‌ها", callback_data='schedule:manage_types')],
        [InlineKeyboardButton("🔄 اعلام تغییر زمان (کلاس منعطف)", callback_data='schedule:flex_list')],
        [InlineKeyboardButton("🔁 الگوی هفتگی → تولید برنامه", callback_data='schedule:template_menu')],
        [InlineKeyboardButton("📊 مدیریت نمرات", callback_data='grades:new')],
        [InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:main')],
    ]
    await query.edit_message_text(
        "📅 <b>برنامه کلاسی</b>\n━━━━━━━━━━━━━━━━",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_cat_comm(query, uid: int = None):
    """📢 دسته: ارتباط با کاربران"""
    keyboard = [
        [InlineKeyboardButton("📢 ارسال همگانی",  callback_data='admin:broadcast')],
        [InlineKeyboardButton("📊 نظرسنجی کانال", callback_data='admin:poll_main')],
        [InlineKeyboardButton("🎫 مدیریت تیکت‌ها", callback_data='ticket:admin_list')],
    ]
    if uid is None or uid == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("📢 مدیریت اعلان‌ها", callback_data='admin:notif_manage')])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:main')])
    await query.edit_message_text(
        "📢 <b>ارتباط با کاربران</b>\n━━━━━━━━━━━━━━━━",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_cat_settings(query, uid: int = None):
    """⚙️ دسته: تنظیمات و سیستم"""
    keyboard = [
        [InlineKeyboardButton("📡 وضعیت ربات",   callback_data='admin:bot_status')],
        [InlineKeyboardButton("💾 پشتیبان‌گیری", callback_data='backup:menu')],
        # 👑 موج P0 — اجرای دستی محاسبه‌ی اولیه‌ی Prestige (یک‌باره، idempotent)
        [InlineKeyboardButton("🏅 محاسبه‌ی اولیه‌ی Prestige", callback_data='admin:prestige_backfill')],
    ]
    if uid is None or uid == ADMIN_ID:
        keyboard.append([
            InlineKeyboardButton("⚙️ تنظیمات ربات", callback_data='admin:settings'),
            InlineKeyboardButton("💙 حمایت مالی",   callback_data='admin:donation_manage'),
        ])
        keyboard.append([
            InlineKeyboardButton("📋 لاگ فعالیت", callback_data='admin:audit_log'),
            InlineKeyboardButton("📥 خروجی اکسل", callback_data='admin:export_excel'),
        ])
        # FIX جدید: سیستم اشتراک — فقط ادمین ارشد
        keyboard.append([InlineKeyboardButton("💳 مدیریت اشتراک", callback_data='suba:main')])
        # 🤖 هوشیار — دستیار هوش مصنوعی
        keyboard.append([InlineKeyboardButton("🤖 مدیریت هوشیار", callback_data='ai:main')])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:main')])
    await query.edit_message_text(
        "⚙️ <b>تنظیمات و سیستم</b>\n━━━━━━━━━━━━━━━━",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))



# 🌊 W7 — نیازمند اقدام در ربات: بستن/بازکردن هشدار با دلیل + مدیریت اسپم کیف پول
async def _show_attention(query, uid: int):
    from time_utils import utc_now_iso, now_utc, parse_machine_datetime
    from datetime import timedelta
    try:
        is_owner = uid == ADMIN_ID
        perms = await db.get_user_perms(uid) if not is_owner else set()
        items = []
        try:
            if is_owner or any(k in perms for k in ('subscription.manage',)):
                witems = await db.wallet_reconcile_items()
                wcrit = [x for x in witems if x.get('severity')=='critical']
                items.append({'key':'wallet_issues','icon':'👛','label':'مغایرت مالی کیف پول','count':len(wcrit),'severity':'critical' if wcrit else 'info','urgent':bool(wcrit)})
        except Exception: pass
        try:
            c = await db.users.count_documents({'approved': False, 'suspended': {'$ne': True}})
            if c: items.append({'key':'users','icon':'🧑‍🎓','label':'کاربر در انتظار تأیید','count':c,'severity':'warning','urgent':True})
        except: pass
        try:
            c = await db.sub_payment_count_all('pending')
            if c: items.append({'key':'payments','icon':'🧾','label':'رسید پرداخت در انتظار','count':c,'severity':'warning','urgent':True})
        except: pass
        try:
            c = await db.tickets.count_documents({'status':'open'})
            if c: items.append({'key':'tickets','icon':'🎫','label':'تیکت بدون پاسخ','count':c,'severity':'warning','urgent':True})
        except: pass
        try:
            from api.routers.web_admin import _quality_summary
            qs = await _quality_summary()
            if qs['count']: items.append({'key':'data_quality','icon':'🧬','label':'ناهنجاری کیفیت داده','count':qs['count'],'severity':'critical' if qs['critical'] else 'warning','urgent':True})
        except: pass
        try:
            runs = await db.get_recent_notif_runs(limit=20)
            from datetime import datetime, timezone, timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            failed = []
            for r in runs:
                if int(r.get('failed') or 0)<=0: continue
                try:
                    from time_utils import parse_machine_datetime as _pm
                    if _pm(r.get('started_at') or r.get('created_at')) >= cutoff:
                        failed.append(r)
                except: failed.append(r)
            if failed: items.append({'key':'failed_jobs','icon':'⚙️','label':'اجرای اعلان دارای خطا','count':len(failed),'severity':'critical','urgent':True})
        except: pass
        try:
            dcol = db.client["medicalbot"]["attention_dismissals"]
            ddocs = await dcol.find({}).to_list(100)
            from time_utils import now_utc as _nu, parse_machine_datetime as _pm2
            now = _nu()
            dmap = {}
            for d in ddocs:
                u = d.get('dismissed_until')
                if u:
                    try:
                        if _pm2(u) < now: continue
                    except: pass
                dmap[d.get('key')] = d
        except Exception:
            dmap = {}
        active = [x for x in items if x['key'] not in dmap]
        dismissed = [x for x in items if x['key'] in dmap]
        for k, d in list(dmap.items()):
            if k not in [x['key'] for x in items]:
                dismissed.append({'key':k,'icon':'🔕','label':k,'count':0,'severity':'info','urgent':False,'dismissed':True,'reason':d.get('reason')})
        try:
            wallet_enabled = await db.get_setting('wallet_alert_enabled', True)
            if wallet_enabled is None: wallet_enabled = True
            wallet_cooldown = await db.get_setting('wallet_alert_cooldown_hours', 6)
            if wallet_cooldown is None: wallet_cooldown = 6
            wallet_muted = await db.get_setting('wallet_alert_muted_until', None)
        except: wallet_enabled, wallet_cooldown, wallet_muted = True, 6, None
        text_lines = ["⚠️ <b>نیازمند اقدام</b>", "━━━━━━━━━━━━━━━━", ""]
        if not active and not dismissed:
            text_lines.append("✅ هیچ مورد فعالی نیست — همه صف‌ها خالی‌اند 🎉")
        if active:
            text_lines.append(f"<b>فعال ({len(active)}):</b>")
            for it in active:
                text_lines.append(f"{it['icon']} {it['label']}: <b>{it['count']}</b> — {it['key']}")
            text_lines.append("")
        if dismissed:
            text_lines.append(f"<b>بسته‌شده ({len(dismissed)}):</b>")
            for it in dismissed:
                d = dmap.get(it['key'], {})
                until = d.get('dismissed_until') or 'دائم'
                text_lines.append(f"🔕 {it['key']}: {d.get('reason','—')} (تا {until})")
            text_lines.append("")
        text_lines.append(f"👛 هشدار کیف پول: {'فعال' if wallet_enabled else 'غیرفعال'} | ضداسپم {fa_digits(wallet_cooldown)}ساعت" + (f" | بی‌صدا تا {fmt_jalali_dt(wallet_muted)}" if wallet_muted else ""))
        text = "\n".join(text_lines)
        kb = []
        for it in active:
            kb.append([InlineKeyboardButton(f"🔕 بستن «{it['label']}» ۲۴ساعته", callback_data=f"admin:att_dis:{it['key']}:24"), InlineKeyboardButton(f"۷۲ساعت", callback_data=f"admin:att_dis:{it['key']}:72")])
            kb[-1].append(InlineKeyboardButton("دائم", callback_data=f"admin:att_dis:{it['key']}:0"))
        for it in dismissed:
            kb.append([InlineKeyboardButton(f"↩️ بازکردن «{it['key']}»", callback_data=f"admin:att_res:{it['key']}")])
        kb.append([InlineKeyboardButton("👛 هشدار کیف پول: " + ("غیرفعال کن" if wallet_enabled else "فعال کن"), callback_data="admin:att_wallet_toggle")])
        if wallet_muted:
            kb.append([InlineKeyboardButton("🔔 لغو بی‌صدا", callback_data="admin:att_wallet_unmute")])
        else:
            kb.append([InlineKeyboardButton("🔕 بی‌صدا ۲۴ساعت", callback_data="admin:att_wallet_mute24")])
        kb.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:main')])
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        import traceback
        traceback.print_exc()
        await query.edit_message_text(f"خطا در نمایش نیازمند اقدام: {e}", parse_mode='HTML')

async def _attention_dismiss_bot(query, uid, key, hours, context):
    from time_utils import now_utc, utc_now_iso
    from datetime import timedelta
    allowed_keys = {"users","payments","questions","tickets","reports","failed_jobs","outbox_backlog","outbox_scheduled","dlq","imports","data_quality","wallet_issues","backup_issue"}
    if key not in allowed_keys:
        await query.answer("کلید نامعتبر", show_alert=True); return
    until = None
    if hours and hours>0:
        until = (now_utc() + timedelta(hours=hours)).isoformat()
    reason = "بسته شد از ربات تلگرام (بررسی ادمین)"
    dcol = db.client["medicalbot"]["attention_dismissals"]
    await dcol.update_one({"key": key}, {"$set": {"key": key, "reason": reason, "dismissed_at": utc_now_iso(), "dismissed_until": until, "dismissed_by": uid}}, upsert=True)
    try:
        u = await db.get_user(uid)
        await db.log_action(uid, (u or {}).get("name", str(uid)), await db.get_actor_role_label(uid), f"بستن هشدار نیازمند اقدام: {key}", "BotAdmin", category="admin", severity="WARNING", target_id=key, target_type="attention", target_label=reason[:80])
    except: pass
    await query.answer(f"🔕 {key} بسته شد ({'دائم' if not until else f'{fa_digits(hours)} ساعت'})", show_alert=True)
    await _show_attention(query, uid)

async def _attention_restore_bot(query, uid, key, context):
    dcol = db.client["medicalbot"]["attention_dismissals"]
    res = await dcol.delete_one({"key": key})
    if not res.deleted_count:
        await query.answer("این هشدار بسته نشده", show_alert=True); return
    try:
        u = await db.get_user(uid)
        await db.log_action(uid, (u or {}).get("name", str(uid)), await db.get_actor_role_label(uid), f"بازکردن هشدار نیازمند اقدام: {key}", "BotAdmin", category="admin", severity="INFO", target_id=key, target_type="attention")
    except: pass
    await query.answer(f"↩️ {key} باز شد", show_alert=True)
    await _show_attention(query, uid)



async def show_admin_main(message, uid: int = None):
    await _admin_menu(message, edit=False, uid=uid)


# FIX جدید: عملیاتی که فقط ادمین ارشد (ADMIN_ID) حق انجامش را دارد —
# حتی پشتیبان/مسئول اطلاعیه/مدیر محتوای محدود هم نمی‌توانند.
ROOT_ONLY_ACTIONS = {
    'roles', 'role_add', 'role_remove', 'role_set',
    'role_add_pick', 'role_type', 'role_intake',
    'settings', 'toggle_require_sid',
    'toggle_maintenance', 'set_maintenance_text',
    'set_log_group_admin', 'set_log_group_content',
    'export_excel', 'audit_log',
    'confirm_delete_user', 'delete_user',
    'confirm_block_user', 'block_user', 'unblock_user', 'blacklist_view',  # FIX جدید: بلاک کامل
    'content_admins', 'ca_set', 'ca_remove',
    'notif_manage', 'notif_set_interval', 'notif_history', 'notif_retry',
    'notif_defaults', 'notif_default_toggle', 'notif_force_send',
    'channel_lock', 'channel_lock_add', 'channel_lock_remove',  # FIX جدید
    'set_poll_channel',  # کانال نظرسنجی / اطلاع‌رسانی
    'poll_main', 'poll_create', 'poll_add_option', 'poll_done_options',
    'poll_type', 'poll_confirm', 'poll_cancel',
    'donation_manage', 'donation_toggle', 'set_donation_link',
    'remove_donation_link',  # حمایت مالی
    'cat_users', 'cat_content', 'cat_schedule', 'cat_comm', 'cat_settings',  # منوهای دسته‌بندی‌شده
}


# ── 🧹 موج Q2/W7 — هندلرهای استخراج‌شده از admin_callback ──
# (گام اول: گروه notif_*. رفتار/روتینگ عیناً حفظ شده؛ فقط
# بدنه‌ی شاخه‌ها به توابع سطح ماژول منتقل شده‌اند)

async def _h_notif_set_interval(query, context, parts, uid):
    hours = int(parts[2])
    _old_h = await db.get_setting('resource_notif_interval_hours', 24)
    await db.set_setting('resource_notif_interval_hours', hours)
    try:
        _au = await db.get_user(uid) or {}
        _an = _au.get('name','مدیر ارشد')
        _ar = await db.get_actor_role_label(uid)
        await send_audit_log(context.bot,'admin',_an,uid,"تغییر فاصله اعلان منابع",module='Settings',severity='WARNING',actor_role=_ar,before={'hours': _old_h},after={'hours': hours},tags=['اعلان'])
    except Exception as _e: import logging; logging.getLogger(__name__).warning(f"notif interval audit failed: {_e}")
    await query.answer(f"✅ فاصله اعلان منابع جدید: هر {fa_digits(hours)} ساعت", show_alert=True)
    await _show_notif_manage(query)

async def _h_notif_history(query, context, parts, uid):
    job_name = parts[2] if len(parts) > 2 else None
    await _show_notif_history(query, job_name)

async def _h_notif_retry(query, context, parts, uid):
    run_id = parts[2]
    await _retry_failed_notif(query, context, run_id)

async def _h_notif_default_toggle(query, context, parts, uid):
    ntype = parts[2]
    defaults = await db.get_notif_defaults()
    new_val  = not defaults.get(ntype, True)
    # تک‌منبع semantics با WebAdmin: default + اعمال روی کاربران فعلی.
    result = await db.update_notif_default(ntype, new_val, apply_existing=True)
    affected = result['affected_users']
    admin_user = await db.get_user(uid)
    actor_name = admin_user.get('name', 'مدیر ارشد') if admin_user else 'مدیر ارشد'
    actor_role = await db.get_actor_role_label(uid)
    await send_audit_log(
        context.bot, 'admin', actor_name, uid,
        "تغییر تنظیمات اعلان‌ها", module='Settings', severity='WARNING',
        actor_role=actor_role,
        details=f"پیش‌فرض {ntype}: {'روشن' if new_val else 'خاموش'} | اعمال روی {affected} کاربر",
        tags=['تنظیمات_اعلان']
    )
    await query.answer(f"✅ بروزرسانی شد و روی {affected} کاربر اعمال شد", show_alert=True)
    await _show_notif_defaults(query)

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid   = update.effective_user.id
    parts  = query.data.split(':')
    action = parts[1] if len(parts) > 1 else 'main'

    # FIX جدید: سطوح دسترسی چندگانه
    if uid != ADMIN_ID:
        role_doc = await db.get_admin_role(uid)
        # New multi-role assignments may exist before a legacy projection is
        # materialised. Resolve them from the shared permission source.
        if not role_doc:
            shared_perms = await db.get_user_perms(uid)
            if not shared_perms:
                await query.answer("❌ دسترسی ندارید!", show_alert=True)
                return
            role_doc = {"role": "rbac"}
        if action in ROOT_ONLY_ACTIONS:
            await query.answer("❌ این بخش فقط در اختیار مدیر ارشد است.", show_alert=True)
            return
        role  = role_doc.get('role', '')
        # تک‌منبع جدید RBAC؛ admin_roles/role فقط برای compatibility در
        # شاخه‌های UI استفاده می‌شود، نه برای تصمیم permission.
        perms = await db.get_user_perms(uid)
        # FIX امنیتی: محدودیت دقیق هر نقش فرعی به منوی خودش —
        # غیر از 'main' (که خودش منوی فیلترشده نشان می‌دهد)، فقط
        # عمل متناسب با مجوز همان نقش اجازه دارد.
        if action == 'broadcast' and not ('broadcast.send' in perms or 'broadcast' in perms):
            await query.answer("❌ شما دسترسی ارسال همگانی ندارید.", show_alert=True)
            return
        if action != 'main':
            if role == 'support':
                await query.answer(
                    "ℹ️ شما دسترسی پشتیبان دارید — از منوی «🎫 مدیریت تیکت‌ها» استفاده کنید.",
                    show_alert=True
                )
                return
            if role == 'content_scoped' and action != 'broadcast':
                await query.answer(
                    "ℹ️ شما ادمین محتوای ورودی خاص هستید — از منوی «🎓 پنل محتوا» استفاده کنید.",
                    show_alert=True
                )
                return
            if role == 'broadcaster' and not (action == 'broadcast' or action.startswith('bc_')):
                await query.answer(
                    "ℹ️ شما فقط دسترسی ارسال همگانی دارید.",
                    show_alert=True
                )
                return
            # FIX جدید: نقش خرخون فقط به مدیریت گزارشات دسترسی دارد
            # (که در namespace 'report:' است، نه 'admin:') — پس هر
            # اکشن admin: دیگری برایش رد می‌شود.
            if role == 'reviewer':
                await query.answer(
                    "ℹ️ شما دسترسی خرخون دارید — از منوی «⚠️ گزارشات سوال/جزوه» استفاده کنید.",
                    show_alert=True
                )
                return
            # FIX جدید: ادمین ربات فقط به کاربران، برنامه‌ها، broadcast دسترسی دارد
            if role == 'bot_admin' and not (
                action in (
                    'users', 'users_filter', 'uf_group', 'uf_intake', 'uf_clear',
                    'user_detail', 'search_user', 'approve', 'reject', 'edit_group',
                    'set_group', 'edit_intake', 'set_intake_user', 'pending', 'broadcast',
                ) or action.startswith('bc_')
            ):
                await query.answer(
                    "ℹ️ شما دسترسی محدود دارید — کاربران، برنامه‌ها و ارسال همگانی.",
                    show_alert=True
                )
                return
            # FIX جدید: نماینده‌ی ورودی فقط به پنل نمرات دسترسی دارد
            # (namespace جدا 'grades:')، هیچ اکشن admin: برایش مجاز نیست
            if role == 'grade_rep':
                await query.answer(
                    "ℹ️ شما دسترسی نماینده دارید — از منوی «📊 پنل نمرات» استفاده کنید.",
                    show_alert=True
                )
                return
            if role == 'rbac':
                user_actions = {
                    'users', 'users_filter', 'uf_group', 'uf_intake', 'uf_clear',
                    'user_detail', 'search_user', 'approve', 'reject', 'edit_group',
                    'set_group', 'edit_intake', 'set_intake_user', 'pending',
                }
                if action in user_actions and not (
                    'users.view' in perms or 'users.manage' in perms):
                    await query.answer("❌ مجوز مشاهده کاربران را ندارید.", show_alert=True)
                    return
                if (action.startswith('bc_') or action == 'broadcast') and not (
                        'broadcast.send' in perms or 'broadcast' in perms):
                    await query.answer("❌ مجوز ارسال همگانی را ندارید.", show_alert=True)
                    return
                if action.startswith('stats') or action in ('insights', 'activity'):
                    if 'stats.view' not in perms:
                        await query.answer("❌ مجوز مشاهده آمار را ندارید.", show_alert=True)
                        return
                if action not in user_actions and not action.startswith('bc_') \
                        and action not in ('broadcast', 'stats', 'stats_users', 'stats_content',
                                           'stats_questions', 'stats_tickets', 'stats_notif',
                                           'insights', 'activity'):
                    await query.answer("❌ این عملیات برای نقش شما فعال نیست.", show_alert=True)
                    return

    await query.answer()

    if action == 'main':
        await _admin_menu(query, uid=uid)
    elif action == 'stats':
        await _show_stats(query)

    elif action == 'stats_users':
        await _show_stats_users(query)

    elif action == 'stats_content':
        await _show_stats_content(query)

    elif action == 'stats_questions':
        await _show_stats_questions(query)

    elif action == 'stats_tickets':
        await _show_stats_tickets(query)

    elif action == 'stats_notif':
        await _show_stats_notif(query)

    elif action == 'insights':
        await _show_admin_insights(query)

    elif action == 'attention':
        await _show_attention(query, uid)
    elif action == 'att_dis':
        # admin:att_dis:<key>:<hours>
        try:
            _k = parts[2] if len(parts)>2 else ""
            _h = int(parts[3]) if len(parts)>3 else 24
            await _attention_dismiss_bot(query, uid, _k, _h, context)
        except Exception as e:
            await query.answer(f"خطا: {e}", show_alert=True)
    elif action == 'att_res':
        try:
            _k = parts[2] if len(parts)>2 else ""
            await _attention_restore_bot(query, uid, _k, context)
        except Exception as e:
            await query.answer(f"خطا: {e}", show_alert=True)
    elif action == 'att_wallet_toggle':
        cur = await db.get_setting('wallet_alert_enabled', True)
        if cur is None: cur = True
        await db.set_setting('wallet_alert_enabled', not cur)
        await query.answer(f"هشدار کیف پول {'غیرفعال' if cur else 'فعال'} شد", show_alert=True)
        await _show_attention(query, uid)
    elif action == 'att_wallet_mute24':
        from time_utils import now_utc
        from datetime import timedelta
        until = (now_utc() + timedelta(hours=24)).isoformat()
        await db.set_setting('wallet_alert_muted_until', until)
        await query.answer("۲۴ ساعت بی‌صدا شد 🔕", show_alert=True)
        await _show_attention(query, uid)
    elif action == 'att_wallet_unmute':
        await db.set_setting('wallet_alert_muted_until', None)
        await query.answer("بی‌صدا لغو شد 🔔", show_alert=True)
        await _show_attention(query, uid)

    # ══════════════════════════════════════════════
    # 🗂 منوهای دسته‌بندی‌شده پنل ادمین (لایه ناوبری جدید)
    # ══════════════════════════════════════════════
    elif action == 'cat_users':
        await _show_cat_users(query, uid=uid)
    elif action == 'cat_content':
        await _show_cat_content(query)
    elif action == 'cat_schedule':
        await _show_cat_schedule(query)
    elif action == 'cat_comm':
        await _show_cat_comm(query, uid=uid)
    elif action == 'cat_settings':
        await _show_cat_settings(query, uid=uid)

    elif action == 'bot_status':
        await _show_bot_status(query, context)

    # ══════════════════════════════════════════════
    # ⚙️ تنظیمات ربات
    # ══════════════════════════════════════════════
    elif action == 'settings':
        await _show_settings(query)

    elif action == 'toggle_require_sid':
        current = await db.get_setting('require_student_id', False)
        new_val = not current
        await db.set_setting('require_student_id', new_val)
        await query.answer("✅ شماره دانشجویی اکنون اجباری است" if new_val else "✅ شماره دانشجویی اکنون اختیاری است", show_alert=True)
        admin_user = await db.get_user(uid)
        actor_name = admin_user.get('name', 'مدیر ارشد') if admin_user else 'مدیر ارشد'
        actor_role = await db.get_actor_role_label(uid)
        await send_audit_log(
            context.bot, 'admin', actor_name, uid,
            "تغییر تنظیمات ثبت‌نام", module='Settings', severity='HIGH',
            actor_role=actor_role,
            before={'شماره دانشجویی': 'اختیاری' if new_val else 'اجباری'},
            after={'شماره دانشجویی': 'اجباری' if new_val else 'اختیاری'},
            tags=['تنظیمات_ثبت_نام']
        )
        await _show_settings(query)

    elif action == 'prestige_backfill':
        # 👑 موج P0 — اجرای دستی Backfill (فقط مدیر ارشد؛ idempotent)
        if uid != ADMIN_ID:
            await query.answer('⛔ فقط مدیر ارشد', show_alert=True); return
        await query.answer('🏅 در حال محاسبه‌ی Prestige…')
        await query.edit_message_text(
            "🏅 <b>محاسبه‌ی اولیه‌ی Prestige</b>\n━━━━━━━━━━━━━━━━\n\n"
            "⏳ در حال پیمایش کاربران و replay تاریخچه…\n"
            "این کار idempotent است و زمان‌بر نیست (batch).",
            parse_mode='HTML')
        rep = await db.prestige_backfill()
        if rep.get('fatal'):
            await query.edit_message_text(
                f"❌ خطای DB در Backfill:\n<code>{_esc(str(rep['fatal'])[:300])}</code>",
                parse_mode='HTML'); return
        lines = [
            "🏅 <b>نتیجه‌ی Backfill Prestige</b>\n━━━━━━━━━━━━━━━━\n",
            f"👥 پیمایش: <b>{rep['scanned']}</b> کاربر",
            f"✅ مهاجرت: <b>{rep['migrated']}</b>",
            f"🏛 بنیان‌گذار: <b>{rep['founders']}</b>",
            f"🏆 نشان‌های جهانی اعطاشده: <b>{len(rep['firsts'])}</b>",
            f"⚠️ خطا: <b>{rep['errors']}</b>",
        ]
        for f in rep['firsts'][:10]:
            lines.append(f"  • {f['key']} ← <code>{f['uid']}</code>")
        await query.edit_message_text('\n'.join(lines), parse_mode='HTML')
        try:
            admin_user = await db.get_user(uid)
            actor_name = admin_user.get('name', 'مدیر ارشد') if admin_user else 'مدیر ارشد'
            actor_role = await db.get_actor_role_label(uid)
            await send_audit_log(
                context.bot, 'admin', actor_name, uid,
                "اجرای Backfill Prestige",
                module='Settings', severity='CRITICAL',
                actor_role=actor_role,
                details=(f"مهاجرت={rep['migrated']} • بنیان‌گذار={rep['founders']} • "
                         f"نشان جهانی={len(rep['firsts'])} • خطا={rep['errors']}"),
                tags=['prestige', 'backfill'])
        except Exception:
            pass
        return

    elif action == 'toggle_maintenance':
        current = await db.get_setting('maintenance_mode', False)
        new_val = not current
        await db.set_setting('maintenance_mode', new_val)
        await query.answer("🔧 حالت تعمیر فعال شد" if new_val else "✅ حالت تعمیر غیرفعال شد", show_alert=True)
        admin_user = await db.get_user(uid)
        actor_name = admin_user.get('name', 'مدیر ارشد') if admin_user else 'مدیر ارشد'
        actor_role = await db.get_actor_role_label(uid)
        await send_audit_log(
            context.bot, 'admin', actor_name, uid,
            "فعال‌شدن حالت تعمیر" if new_val else "غیرفعال‌شدن حالت تعمیر",
            module='Settings', severity='CRITICAL',
            actor_role=actor_role,
            before={'وضعیت': 'غیرفعال' if new_val else 'فعال'},
            after={'وضعیت': 'فعال' if new_val else 'غیرفعال'},
            tags=['حالت_تعمیر']
        )
        await _show_settings(query)

    elif action == 'set_maintenance_text':
        context.user_data['mode'] = 'set_maintenance_text'
        await query.edit_message_text(
            "🔧 <b>متن حالت تعمیر</b>\n\nمتن جدیدی که کاربران در حالت تعمیر می‌بینند را ارسال کنید:\n"
            "<i>برای بازگشت به متن پیش‌فرض، کلمه «پیشفرض» را بفرستید.</i>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data='admin:settings')]])
        )

    elif action == 'set_log_group_admin':
        context.user_data['mode'] = 'set_log_group_admin'
        await query.edit_message_text(
            "🛡 <b>تنظیم گروه لاگ پنل ادمین</b>\n\n"
            "ربات را به گروه مورد نظر اضافه کنید، سپس یک پیام در آن گروه بفرستید و "
            "آن را به اینجا فوروارد کنید — یا مستقیماً آیدی عددی گروه (با علامت منفی) را ارسال کنید.\n\n"
            "<i>برای حذف تنظیم فعلی، کلمه «حذف» را بفرستید.</i>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data='admin:settings')]])
        )

    elif action == 'set_log_group_content':
        context.user_data['mode'] = 'set_log_group_content'
        await query.edit_message_text(
            "🎓 <b>تنظیم گروه لاگ پنل محتوا</b>\n\n"
            "ربات را به گروه ادمین محتوا اضافه کنید، سپس یک پیام در آن گروه بفرستید و "
            "آن را به اینجا فوروارد کنید — یا مستقیماً آیدی عددی گروه (با علامت منفی) را ارسال کنید.\n\n"
            "<i>برای حذف تنظیم فعلی، کلمه «حذف» را بفرستید.</i>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data='admin:settings')]])
        )

    elif action == 'test_log_groups':
        await _test_log_groups(query, context)

    elif action == 'set_poll_channel':
        context.user_data['mode'] = 'set_poll_channel'
        current = await db.get_setting('poll_channel_id', None)
        current_txt = f"\n\n📌 تنظیم فعلی: <code>{_esc(current)}</code>" if current else ""
        await query.edit_message_text(
            f"📊 <b>تنظیم کانال نظرسنجی / اطلاع‌رسانی</b>{current_txt}\n\n"
            "آیدی عددی کانال (با <code>-100</code>) را ارسال کنید.\n\n"
            "💡 روش پیدا کردن آیدی کانال:\n"
            "یک پیام از کانال را به @RawDataBot فوروارد کنید و مقدار <code>chat.id</code> را کپی کنید.\n\n"
            "<i>⚠️ ربات باید admin کانال باشد.</i>\n"
            "<i>برای حذف تنظیم فعلی، کلمه «حذف» را بفرستید.</i>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data='admin:settings')]])
        )

    # ══════════════════════════════════════════════
    # 💙 حمایت مالی
    # ══════════════════════════════════════════════
    elif action == 'donation_manage':
        await _show_donation_manage(query)

    elif action == 'donation_toggle':
        current = await db.get_setting('donation_enabled', False)
        new_val = not current
        await db.set_setting('donation_enabled', new_val)
        await query.answer("✅ بخش حمایت مالی فعال شد" if new_val else "✅ بخش حمایت مالی غیرفعال شد", show_alert=True)
        admin_user = await db.get_user(uid)
        actor_name = admin_user.get('name', 'مدیر ارشد') if admin_user else 'مدیر ارشد'
        actor_role = await db.get_actor_role_label(uid)
        await send_audit_log(
            context.bot, 'admin', actor_name, uid,
            "فعال‌شدن بخش حمایت مالی" if new_val else "غیرفعال‌شدن بخش حمایت مالی",
            module='Settings', severity='HIGH',
            actor_role=actor_role,
            before={'وضعیت': 'غیرفعال' if new_val else 'فعال'},
            after={'وضعیت': 'فعال' if new_val else 'غیرفعال'},
            tags=['حمایت_مالی']
        )
        await _show_donation_manage(query)

    elif action == 'set_donation_link':
        context.user_data['mode'] = 'set_donation_link'
        current = await db.get_setting('donation_link', None)
        current_txt = f"\n\n📌 لینک فعلی:\n<code>{_esc(current)}</code>" if current else ""
        await query.edit_message_text(
            f"💙 <b>تنظیم لینک حمایت مالی</b>{current_txt}\n\n"
            "لینک صفحه حمایت مالی را ارسال کنید (مثلاً لینک صفحه پروژه در reymit.org).\n\n"
            "<i>برای حذف لینک فعلی، کلمه «حذف» را بفرستید.</i>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data='admin:donation_manage')]])
        )

    elif action == 'remove_donation_link':
        await db.set_setting('donation_link', None)
        await query.answer("✅ لینک حمایت مالی حذف شد", show_alert=True)
        # FIX لاگ: حذف لینک مثل تاگل باید ثبت شود (پارتی با وب‌پنل)
        admin_user = await db.get_user(uid)
        actor_name = admin_user.get('name', 'مدیر ارشد') if admin_user else 'مدیر ارشد'
        actor_role = await db.get_actor_role_label(uid)
        await send_audit_log(
            context.bot, 'admin', actor_name, uid,
            "حذف لینک حمایت مالی", module='Settings', severity='HIGH',
            actor_role=actor_role,
            before={'لینک': 'تنظیم شده'}, after={'لینک': 'حذف شد'},
            tags=['حمایت_مالی']
        )
        await _show_donation_manage(query)

    elif action == 'export_excel':
        await _export_excel(query, context)

    elif action == 'channel_lock':
        await _show_channel_lock(query)

    elif action == 'channel_lock_add':
        context.user_data['mode'] = 'add_required_channel'
        await query.edit_message_text(
            "🔒 <b>افزودن کانال اجباری</b>\n\n"
            "آیدی عددی کانال (با علامت منفی، مثل <code>-1001234567890</code>) "
            "و سپس نام کانال را با کاما جدا کنید:\n\n"
            "📌 مثال:\n<code>-1001234567890, کانال اطلاع‌رسانی هامزیار</code>\n\n"
            "<i>⚠️ ربات باید ادمین آن کانال باشد تا بتواند عضویت را چک کند.</i>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ لغو", callback_data='admin:channel_lock')
            ]])
        )

    elif action == 'channel_lock_remove':
        ch_id = parts[2]
        await db.remove_required_channel(ch_id)
        admin_user = await db.get_user(uid)
        actor_name = admin_user.get('name', 'مدیر ارشد') if admin_user else 'مدیر ارشد'
        actor_role = await db.get_actor_role_label(uid)
        await send_audit_log(
            context.bot, 'admin', actor_name, uid,
            "حذف کانال اجباری", module='Settings', severity='HIGH',
            actor_role=actor_role, target_id=ch_id, target_type='channel',
            tags=['کانال_اجباری']
        )
        await query.answer("✅ کانال حذف شد!", show_alert=True)
        await _show_channel_lock(query)

    elif action == 'audit_log':
        sev = parts[2] if len(parts) > 2 and parts[2] != 'all' else None
        await _show_audit_log(query, 'admin', sev)

    # ══════════════════════════════════════════════
    # 📢 مدیریت اعلان‌ها — FIX جدید
    # ══════════════════════════════════════════════
    elif action == 'notif_manage':
        await _show_notif_manage(query)

    elif action == 'notif_set_interval':
        await _h_notif_set_interval(query, context, parts, uid)

    elif action == 'notif_force_send':
        await _handle_notif_force_send(query)

    elif action == 'notif_history':
        await _h_notif_history(query, context, parts, uid)

    elif action == 'notif_retry':
        await _h_notif_retry(query, context, parts, uid)

    elif action == 'notif_defaults':
        await _show_notif_defaults(query)

    elif action == 'notif_default_toggle':
        await _h_notif_default_toggle(query, context, parts, uid)

    # ══════════════════════════════════════════════
    # 🛡 سطوح دسترسی چندگانه ادمین (admin_roles)
    # ══════════════════════════════════════════════
    elif action == 'roles':
        # FIX باگ: پاک‌سازی state نیمه‌کاره افزودن نقش — وگرنه بعد از
        # لغو، mode='add_admin_role' باقی می‌ماند و پیام بعدی کاربر
        # در هر بخش دیگری از ربات به اشتباه به‌عنوان آیدی پارس می‌شود.
        for k in ('mode', 'new_role_type', 'new_role_intake'):
            context.user_data.pop(k, None)
        await _show_roles(query)

    elif action == 'role_add_pick':
        # انتخاب نوع نقش قبل از گرفتن آیدی
        await _show_role_type_picker(query)

    elif action == 'role_type':
        role_type = parts[2]
        context.user_data['new_role_type'] = role_type
        if role_type in ('content_scoped', 'grade_rep'):
            await _show_role_intake_picker(query, role_type)
        else:
            context.user_data['mode'] = 'add_admin_role'
            await query.edit_message_text(
                f"🛡 <b>افزودن {db.ROLE_LABELS.get(role_type, role_type)}</b>\n\n"
                "آیدی عددی تلگرام کاربر را ارسال کنید:\n"
                "<i>(می‌توانید با فوروارد پیام کاربر به @userinfobot آیدی را پیدا کنید)</i>",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ لغو", callback_data='admin:roles')
                ]])
            )

    elif action == 'role_intake':
        intake_code = parts[2] if len(parts) > 2 else ''
        if not intake_code:
            # 🛡 C3.1 — کد خالی (= «سراسری») برای نقش ورودی‌محور مجاز نیست
            await query.answer("❌ ورودی نامعتبر است.", show_alert=True)
            return
        context.user_data['new_role_intake'] = intake_code
        context.user_data['mode'] = 'add_admin_role'
        role_type_label = db.ROLE_LABELS.get(context.user_data.get('new_role_type', ''), 'نقش محدود')
        await query.edit_message_text(
            f"🛡 <b>افزودن {role_type_label}</b>\n\n"
            "آیدی عددی تلگرام کاربر را ارسال کنید:",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ لغو", callback_data='admin:roles')
            ]])
        )

    elif action == 'role_remove':
        target_uid = int(parts[2])
        await db.remove_admin_role(target_uid)
        admin_user = await db.get_user(uid)
        actor_name = admin_user.get('name', 'مدیر ارشد') if admin_user else 'مدیر ارشد'
        actor_role = await db.get_actor_role_label(uid)
        target_user_doc = await db.get_user(target_uid)
        target_label = target_user_doc.get('name', '') if target_user_doc else ''
        await send_audit_log(
            context.bot, 'admin', actor_name, uid,
            "حذف رول از ادمین", module='Roles', severity='CRITICAL',
            actor_role=actor_role,
            target_id=str(target_uid), target_type='user', target_label=target_label,
            tags=['نقش_ها']
        )
        await query.answer("✅ نقش حذف شد!", show_alert=True)
        await _show_roles(query)

    elif action == 'users':
        page = int(parts[2]) if len(parts) > 2 else 0
        await _show_users_list(query, context, page, group=context.user_data.get('filter_group'), intake=context.user_data.get('filter_intake'))
    elif action == 'users_filter':
        await _show_users_filter(query, context)
    elif action == 'uf_group':
        g = parts[2] if len(parts) > 2 and parts[2] != 'all' else None
        context.user_data['filter_group'] = g
        await _show_users_list(query, context, 0, group=g, intake=context.user_data.get('filter_intake'))
    elif action == 'uf_intake':
        icode = parts[2] if len(parts) > 2 and parts[2] != 'all' else None
        context.user_data['filter_intake'] = icode
        await _show_users_list(query, context, 0, group=context.user_data.get('filter_group'), intake=icode)
    elif action == 'uf_clear':
        context.user_data.pop('filter_group', None)
        context.user_data.pop('filter_intake', None)
        await _show_users_list(query, context, 0)
    elif action == 'user_detail':
        await _show_user_detail(query, context, int(parts[2]))

    # ✉️ موج ۴.۸۰ — شروع جریان «پیام مستقیم» از کارت کاربر
    elif action == 'dm_user':
        target = int(parts[2])
        target_user = await db.get_user(target)
        if not target_user:
            await query.answer("کاربر پیدا نشد!", show_alert=True)
            return
        context.user_data['mode']           = 'admin_dm'
        context.user_data['dm_target']      = target
        context.user_data['dm_target_name'] = target_user.get('name', '')
        await query.edit_message_text(
            "✉️ <b>پیام مستقیم به کاربر</b>\n━━━━━━━━━━━━━━━━\n\n"
            f"گیرنده: <b>{target_user.get('name','')}</b>"
            + (f" (@{target_user.get('username')})" if target_user.get('username') else "") + "\n\n"
            "متن پیام را بنویسید. پیام با سربرگ «مدیریت هامزیار» "
            "از طرف ربات برای کاربر ارسال می‌شود — فقط متن ساده بنویسید.\n\n"
            "<i>حداکثر ۳۵۰۰ کاراکتر — برای لغو، دکمه‌ی زیر را بزنید.</i>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ لغو", callback_data=f'admin:user_detail:{target}')
            ]])
        )
    elif action in ('edit_name', 'edit_group', 'edit_sid'):
        target_uid = int(parts[2])
        field_map  = {'edit_name': ('name','نام'), 'edit_group': ('group','گروه'), 'edit_sid': ('student_id','شماره دانشجویی')}
        field, label = field_map[action]
        if action == 'edit_group':
            # ویرایش گروه با دکمه — نه متن
            user_t = await db.get_user(target_uid)
            cur_g  = user_t.get('group', '') if user_t else ''
            await query.edit_message_text(
                f"👥 <b>تغییر گروه کاربر</b>\n\nگروه فعلی: <b>{cur_g or 'تعیین نشده'}</b>\n\nگروه جدید را انتخاب کنید:",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(f"{'✅ ' if cur_g=='1' else ''}1️⃣ گروه ۱", callback_data=f'admin:set_group:{target_uid}:1'),
                        InlineKeyboardButton(f"{'✅ ' if cur_g=='2' else ''}2️⃣ گروه ۲", callback_data=f'admin:set_group:{target_uid}:2'),
                    ],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data=f'admin:user_detail:{target_uid}')],
                ])
            )
        else:
            context.user_data['edit_user'] = {'uid': target_uid, 'field': field, 'label': label}
            context.user_data['mode'] = 'edit_user'
            await query.edit_message_text(
                f"✏️ <b>ویرایش {label}</b>\n\nمقدار جدید را وارد کنید:", parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data=f'admin:user_detail:{target_uid}')]]))

    elif action == 'set_group':
        target_uid = int(parts[2])
        new_group  = parts[3] if len(parts) > 3 else '1'
        await db.update_user(target_uid, {'group': new_group})
        await query.answer(f"✅ گروه به {new_group} تغییر یافت!", show_alert=True)
        await _show_user_detail(query, context, target_uid)

    elif action == 'edit_intake':
        target_uid = int(parts[2])
        user_t     = await db.get_user(target_uid)
        cur_intake = user_t.get('intake', '') if user_t else ''
        intakes    = await db.get_all_intakes()
        keyboard   = []
        for i in intakes:
            active = cur_intake == i['code']
            keyboard.append([InlineKeyboardButton(
                f"{'✅ ' if active else ''}{i['label']}",
                callback_data=f'admin:set_intake_user:{target_uid}:{i["code"]}'
            )])
        keyboard.append([InlineKeyboardButton("❌ بدون ورودی", callback_data=f'admin:set_intake_user:{target_uid}:none')])
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f'admin:user_detail:{target_uid}')])
        await query.edit_message_text(
            f"📅 <b>تغییر ورودی کاربر</b>\n\nورودی فعلی: <b>{cur_intake or '—'}</b>\n\nورودی جدید را انتخاب کنید:",
            parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif action == 'set_intake_user':
        target_uid = int(parts[2])
        new_intake = '' if parts[3] == 'none' else parts[3]
        await db.update_user(target_uid, {'intake': new_intake})
        await query.answer(f"✅ ورودی به‌روز شد!", show_alert=True)
        await _show_user_detail(query, context, target_uid)
    elif action == 'suspend':
        target_uid = int(parts[2])
        target_user = await db.get_user(target_uid)
        target_name = target_user.get('name', '') if target_user else ''
        await db.update_user(target_uid, {'approved': False})
        await safe_send(context.bot, target_uid, "⚠️ دسترسی شما موقتاً تعلیق شد.")
        await query.answer("🚫 تعلیق شد!", show_alert=True)
        admin_user = await db.get_user(uid)
        actor_name = admin_user.get('name', 'مدیر') if admin_user else 'مدیر'
        actor_role = await db.get_actor_role_label(uid)
        await send_audit_log(
            context.bot, 'admin', actor_name, uid,
            "مسدودسازی کاربر", module='Users', severity='HIGH',
            actor_role=actor_role,
            target_id=str(target_uid), target_type='user', target_label=target_name,
            tags=['مسدودسازی']
        )
        await _show_users_list(query, context, 0)
    elif action == 'approve':
        target_uid = int(parts[2])
        prev_user = await db.get_user(target_uid)
        # FIX جدید: تشخیص ثبت‌نام تازه (هنوز approved نبوده) از رفع تعلیق
        was_already_registered = bool(prev_user and prev_user.get('registered_at'))
        is_unban = was_already_registered and prev_user.get('approved') is False
        await db.update_user(target_uid, {'approved': True})
        user = await db.get_user(target_uid)
        target_kb = await get_keyboard_for_user(user, target_uid)
        # 🔔 موج ۴.۹۰ — اینباکس مینی‌اپ (تأیید حساب → داشبورد)
        await db.inbox_add(target_uid, 'account',
            "✅ حسابت تأیید شد!",
            "اکنون به تمام بخش‌های هامزیار دسترسی داری — خوش اومدی! 🎓",
            link='/')
        await safe_send(context.bot, target_uid, "✅ <b>دسترسی شما تأیید شد!</b>", parse_mode='HTML', reply_markup=target_kb)
        await query.answer("✅ تأیید شد!", show_alert=True)
        if is_unban:
            admin_user = await db.get_user(uid)
            actor_name = admin_user.get('name', 'مدیر') if admin_user else 'مدیر'
            actor_role = await db.get_actor_role_label(uid)
            await send_audit_log(
                context.bot, 'admin', actor_name, uid,
                "رفع مسدودسازی کاربر", module='Users', severity='WARNING',
                actor_role=actor_role,
                target_id=str(target_uid), target_type='user',
                target_label=prev_user.get('name', '') if prev_user else '',
                tags=['رفع_مسدودسازی']
            )
        await _show_pending(query)
    elif action == 'reject':
        target_uid = int(parts[2])
        await db.delete_user(target_uid)
        await safe_send(context.bot, target_uid, "❌ درخواست شما رد شد.")
        await query.answer("❌ رد شد.", show_alert=True)
        await _show_pending(query)
    elif action == 'confirm_delete_user':
        target_uid = int(parts[2])
        user = await db.get_user(target_uid)
        name = user.get('name','') if user else ''
        await query.edit_message_text(
            f"⚠️ <b>حذف کاربر</b>\n\nمطمئنی می‌خواهی <b>{name}</b> را حذف کنی؟", parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⚠️ بله، حذف", callback_data=f'admin:delete_user:{target_uid}'),
                InlineKeyboardButton("❌ لغو", callback_data=f'admin:user_detail:{target_uid}'),
            ]]))
    elif action == 'delete_user':
        target_uid = int(parts[2])
        user = await db.get_user(target_uid)
        name = user.get('name','') if user else ''
        await db.delete_user(target_uid)
        await safe_send(context.bot, target_uid, "❌ حساب شما حذف شد.")
        await query.answer(f"🗑 {name} حذف شد!", show_alert=True)
        # FIX جدید: لاگ عمل حساس — گروه ادمین
        admin_user = await db.get_user(uid)
        actor_name = admin_user.get('name', 'مدیر ارشد') if admin_user else 'مدیر ارشد'
        actor_role = await db.get_actor_role_label(uid)
        await send_audit_log(
            context.bot, 'admin', actor_name, uid,
            "حذف کاربر", module='Users', severity='HIGH',
            actor_role=actor_role,
            target_id=str(target_uid), target_type='user', target_label=name,
            tags=['حذف_کاربر']
        )
        await _show_users_list(query, context, 0)
    elif action == 'confirm_block_user':
        target_uid = int(parts[2])
        user = await db.get_user(target_uid)
        name = user.get('name', '') if user else ''
        await query.edit_message_text(
            f"🚫 <b>بلاک کامل کاربر</b>\n\n"
            f"مطمئنی می‌خواهی <b>{name}</b> (<code>{target_uid}</code>) را بلاک کنی؟\n\n"
            "⚠️ برخلاف «حذف کامل»، این کاربر هم از دیتابیس حذف می‌شود و هم "
            "دیگر با همین آیدی عددی <b>نمی‌تواند دوباره ثبت‌نام کند</b> — "
            "مگر این‌که بعداً از بلک‌لیست خارجش کنی.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🚫 بله، بلاک کن", callback_data=f'admin:block_user:{target_uid}'),
                InlineKeyboardButton("❌ لغو", callback_data=f'admin:user_detail:{target_uid}'),
            ]]))
    elif action == 'block_user':
        target_uid = int(parts[2])
        user = await db.get_user(target_uid)
        name = user.get('name', '') if user else ''
        admin_user = await db.get_user(uid)
        actor_name = admin_user.get('name', 'مدیر ارشد') if admin_user else 'مدیر ارشد'
        await db.block_user(target_uid, blocked_by=uid, blocked_by_name=actor_name)
        await safe_send(context.bot, target_uid, "🚫 حساب شما مسدود شد و امکان ثبت‌نام مجدد ندارید.")
        await query.answer(f"🚫 {name} بلاک شد!", show_alert=True)
        actor_role = await db.get_actor_role_label(uid)
        await send_audit_log(
            context.bot, 'admin', actor_name, uid,
            "بلاک کامل کاربر", module='Users', severity='HIGH',
            actor_role=actor_role,
            target_id=str(target_uid), target_type='user', target_label=name,
            tags=['بلاک_کامل']
        )
        await _show_users_list(query, context, 0)
    elif action == 'blacklist_view':
        await _show_blacklist(query)
    elif action == 'unblock_user':
        target_uid = int(parts[2])
        ok = await db.unblock_user(target_uid)
        if ok:
            admin_user = await db.get_user(uid)
            actor_name = admin_user.get('name', 'مدیر ارشد') if admin_user else 'مدیر ارشد'
            actor_role = await db.get_actor_role_label(uid)
            await send_audit_log(
                context.bot, 'admin', actor_name, uid,
                "رفع بلاک کاربر", module='Users', severity='WARNING',
                actor_role=actor_role,
                target_id=str(target_uid), target_type='user',
                tags=['رفع_بلاک']
            )
            await query.answer("✅ از بلک‌لیست خارج شد.", show_alert=True)
        else:
            await query.answer("این آیدی در بلک‌لیست نبود.", show_alert=True)
        await _show_blacklist(query)
    elif action == 'pending':
        await _show_pending(query)
    elif action == 'search_user':
        context.user_data['mode'] = 'search_user'
        context.user_data.pop('awaiting_search', None)
        await query.edit_message_text(
            "🔍 <b>جستجوی کاربر</b>\n\nنام، شماره دانشجویی یا یوزرنیم را وارد کنید:", parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data='admin:cat_users')]]))
    elif action == 'intakes':
        await _show_intakes(query)
    elif action == 'intake_add':
        context.user_data['mode'] = 'add_intake'
        await query.edit_message_text(
            "📅 <b>افزودن ورودی جدید</b>\n\nفرمت: <code>کد, برچسب</code>\nمثال: <code>bahman_1404, بهمن ۱۴۰۴</code>", parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data='admin:intakes')]]))
    elif action == 'intake_toggle':
        code_it = parts[2]
        old_intake = next((i for i in (await db.get_all_intakes()) if i.get('code')==code_it), {})
        new_state = await db.toggle_intake(code_it)
        try:
            _au = await db.get_user(uid) or {}
            _an = _au.get('name', 'مدیر ارشد')
            _ar = await db.get_actor_role_label(uid)
            await send_audit_log(context.bot, 'admin', _an, uid,
                "تغییر وضعیت ورودی" if new_state else "تغییر وضعیت ورودی",
                module='Users', severity='WARNING', actor_role=_ar,
                target_id=code_it, target_type='intake', target_label=old_intake.get('label', code_it),
                before={'active': not new_state}, after={'active': new_state},
                tags=['ورودی'])
        except Exception as _e:
            import logging; logging.getLogger(__name__).warning(f"intake_toggle audit failed: {_e}")
        await query.answer(f"{'✅ فعال' if new_state else '❌ غیرفعال'} شد", show_alert=True)
        await _show_intakes(query)
    elif action == 'intake_del':
        _del_code = parts[2]
        _del_old = next((i for i in (await db.get_all_intakes()) if i.get('code')==_del_code), {})
        await db.delete_intake(_del_code)
        try:
            _au = await db.get_user(uid) or {}
            _an = _au.get('name', 'مدیر ارشد')
            _ar = await db.get_actor_role_label(uid)
            await send_audit_log(context.bot, 'admin', _an, uid,
                "حذف ورودی", module='Users', severity='HIGH', actor_role=_ar,
                target_id=_del_code, target_type='intake', target_label=_del_old.get('label', _del_code),
                tags=['ورودی','حذف_ورودی'])
        except Exception as _e:
            import logging; logging.getLogger(__name__).warning(f"intake_del audit failed: {_e}")
        await query.answer("🗑 ورودی حذف شد!", show_alert=True)
        await _show_intakes(query)
    elif action == 'intake_view':
        code = parts[2]
        stats = await db.intake_stats(code)
        intakes = await db.get_all_intakes()
        intake = next((i for i in intakes if i['code'] == code), {})
        label = intake.get('label', code)
        groups = stats.get('groups', {})
        g_text = '\n'.join(f"  گروه {g}: {c} نفر" for g, c in groups.items()) or "  داده‌ای نیست"
        await query.edit_message_text(
            f"📅 <b>ورودی: {label}</b>\n🔑 کد: <code>{code}</code>\n━━━━━━━━━━━━━━━━\n👥 مجموع دانشجو: <b>{stats['total']}</b>\n\n<b>تفکیک گروه:</b>\n{g_text}",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به ورودی‌ها", callback_data='admin:intakes')]]))
    elif action == 'content_admins':
        admins = await db.get_content_admins()
        keyboard = []
        for a in admins:
            keyboard.append([
                InlineKeyboardButton(f"🎓 {a.get('name','')}", callback_data=f'admin:user_detail:{a["user_id"]}'),
                InlineKeyboardButton("🗑 لغو", callback_data=f'admin:ca_remove:{a["user_id"]}'),
            ])
        keyboard.append([InlineKeyboardButton("➕ دادن دسترسی", callback_data='admin:ca_grant')])
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='admin:cat_users')])
        await query.edit_message_text(f"🎓 <b>ادمین‌های محتوا</b> — {len(admins)} نفر", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    elif action == 'ca_grant':
        users = await db.all_users(approved_only=True)
        students = [u for u in users if u.get('role','student') == 'student'][:20]
        keyboard = [[InlineKeyboardButton(f"👤 {u.get('name','')} | گروه {u.get('group','')}", callback_data=f'admin:ca_set:{u["user_id"]}')] for u in students]
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='admin:content_admins')])
        await query.edit_message_text("➕ کاربر مورد نظر را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif action == 'ca_set':
        target_uid = int(parts[2])
        _t_before = await db.get_user(target_uid) or {}
        await db.update_user(target_uid, {'role': 'content_admin'})
        try:
            _au = await db.get_user(uid) or {}
            _an = _au.get('name', 'مدیر ارشد')
            _ar = await db.get_actor_role_label(uid)
            await send_audit_log(context.bot, 'admin', _an, uid,
                "اعطای دسترسی ادمین محتوا", module='Roles', severity='HIGH', actor_role=_ar,
                target_id=str(target_uid), target_type='user', target_label=_t_before.get('name',''),
                before={'role': _t_before.get('role','')}, after={'role': 'content_admin'},
                tags=['اعطای_نقش'])
        except Exception as _e:
            import logging; logging.getLogger(__name__).warning(f"ca_set audit failed: {_e}")
        await safe_send(context.bot, target_uid, "🎓 <b>دسترسی ادمین محتوا به شما داده شد!</b>", parse_mode='HTML', reply_markup=content_admin_keyboard())
        await query.answer("✅ دسترسی داده شد!", show_alert=True)
        await _show_cat_users(query, uid=uid)
    elif action == 'ca_remove':
        target_uid = int(parts[2])
        _t_before2 = await db.get_user(target_uid) or {}
        await db.update_user(target_uid, {'role': 'student'})
        try:
            _au = await db.get_user(uid) or {}
            _an = _au.get('name', 'مدیر ارشد')
            _ar = await db.get_actor_role_label(uid)
            await send_audit_log(context.bot, 'admin', _an, uid,
                "لغو دسترسی ادمین محتوا", module='Roles', severity='HIGH', actor_role=_ar,
                target_id=str(target_uid), target_type='user', target_label=_t_before2.get('name',''),
                before={'role': _t_before2.get('role','')}, after={'role': 'student'},
                tags=['لغو_نقش'])
        except Exception as _e:
            import logging; logging.getLogger(__name__).warning(f"ca_remove audit failed: {_e}")
        await safe_send(context.bot, target_uid, "⚠️ دسترسی ادمین محتوای شما لغو شد.", reply_markup=main_keyboard())
        await query.answer("↩️ دسترسی لغو شد!", show_alert=True)
        await _show_cat_users(query, uid=uid)
    elif action in ('qbank_manage', 'qbank_upload', 'qbank_lesson', 'qbank_topic', 'qbank_list', 'qbank_del'):
        context.user_data.pop('mode', None)
        await query.edit_message_text(
            "ℹ️ بانک فایل قدیمی بازنشسته شده است. سؤال‌ها اکنون به‌صورت ساختاریافته "
            "در دامنه مشترک ساخته، بررسی و برای آزمون/PDF استفاده می‌شوند.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🧪 بازبینی سؤال‌ها", callback_data='questions:ca_q_list')],
                [InlineKeyboardButton("🔙 پنل محتوا", callback_data='admin:cat_content')],
            ]))
    elif action == 'pending_q':
        # یک صف بررسی و یک permission/lifecycle contract برای همه پنل‌ها.
        from questions import _ca_question_list
        await _ca_question_list(query, uid, context)
    elif action == 'approve_q':
        # سازگاری callbackهای قدیمی؛ mutation همچنان از domain مشترک می‌گذرد.
        from questions import _h_ca_q_approve
        await _h_ca_q_approve(query, context, uid, parts[2])
    elif action == 'reject_q':
        # رد بدون دلیل ممنوع است؛ handler مشترک دلیل متنی می‌گیرد.
        from questions import _h_ca_q_del
        await _h_ca_q_del(query, context, uid, parts[2], target='rejected')

    # ══════════════════════════════════════════════
    # 📢 BROADCAST — سیستم جدید حرفه‌ای
    # ══════════════════════════════════════════════
    elif action == 'broadcast':
        await _broadcast_main(query, context)

    # ══════════════════════════════════════════════
    # 📊 نظرسنجی کانال
    # ══════════════════════════════════════════════
    elif action == 'poll_main':
        await _poll_main(query, context)

    elif action == 'poll_create':
        context.user_data['poll_data'] = {'options': []}
        context.user_data['mode'] = 'poll_question'
        await query.edit_message_text(
            "📊 <b>ساخت نظرسنجی جدید</b>\n━━━━━━━━━━━━━━━━\n\n"
            "📝 سوال نظرسنجی را بنویسید:\n\n"
            "<i>مثال: بهترین منبع برای یادگیری آناتومی کدام است؟</i>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data='admin:poll_cancel')]])
        )

    elif action == 'poll_add_option':
        context.user_data['mode'] = 'poll_option'
        opts = context.user_data.get('poll_data', {}).get('options', [])
        opts_txt = '\n'.join(f"  {i+1}. {o}" for i, o in enumerate(opts)) if opts else "  (هنوز گزینه‌ای نیست)"
        await query.edit_message_text(
            f"📊 <b>افزودن گزینه</b>\n━━━━━━━━━━━━━━━━\n\n"
            f"گزینه‌های فعلی:\n{opts_txt}\n\n"
            f"✏️ گزینه جدید را بنویسید ({len(opts)}/10):",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data='admin:poll_preview')]])
        )

    elif action == 'poll_done_options':
        await _poll_preview(query, context)

    elif action == 'poll_preview':
        await _poll_preview(query, context)

    elif action == 'poll_type':
        ptype = parts[2] if len(parts) > 2 else 'regular'
        context.user_data.setdefault('poll_data', {})['type'] = ptype
        await _poll_confirm(query, context)

    elif action == 'poll_confirm':
        await _poll_send(query, context)

    elif action == 'poll_cancel':
        context.user_data.pop('poll_data', None)
        context.user_data['mode'] = ''
        await query.answer("✅ لغو شد.")
        await _poll_main(query, context)
    elif action == 'bc_target':
        target = parts[2] if len(parts) > 2 else 'all'
        context.user_data['bc_target'] = target
        await _broadcast_ask_message(query, context, target)

    elif action == 'bc_intake':
        # زیرمنوی ورودی: همه / گروه ۱ / گروه ۲
        code     = parts[2] if len(parts) > 2 else ''
        intakes  = await db.get_all_intakes()
        intake   = next((i for i in intakes if i['code'] == code), {})
        label    = intake.get('label', code)
        all_u    = await db.all_users(approved_only=True)
        all_i    = [u for u in all_u if u.get('intake') == code]
        g1_count = sum(1 for u in all_i if str(u.get('group','')) == '1')
        g2_count = sum(1 for u in all_i if str(u.get('group','')) == '2')
        keyboard = [
            [InlineKeyboardButton(
                f"👥 همه دانشجویان ورودی ({len(all_i)} نفر)",
                callback_data=f'admin:bc_target:intake_{code}'
            )],
            [
                InlineKeyboardButton(
                    f"1️⃣ گروه ۱  ({g1_count} نفر)",
                    callback_data=f'admin:bc_target:intake_{code}_g1'
                ),
                InlineKeyboardButton(
                    f"2️⃣ گروه ۲  ({g2_count} نفر)",
                    callback_data=f'admin:bc_target:intake_{code}_g2'
                ),
            ],
            [InlineKeyboardButton("🔙 بازگشت", callback_data='admin:broadcast')],
        ]
        await query.edit_message_text(
            f"📢 <b>ارسال همگانی — ورودی {label}</b>\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📌 گروه مورد نظر را انتخاب کنید:",
            parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif action == 'bc_cancel':
        _broadcast_clear(context)
        await query.answer("✅ لغو شد.")
        await _broadcast_main(query, context)
    elif action == 'bc_confirm':
        await _broadcast_do_send(query, context)
    elif action == 'bc_schedule':
        await _broadcast_schedule_menu(query, context)
    elif action == 'bc_sched_set':
        mins = int(parts[2]) if len(parts) > 2 else 0
        context.user_data['bc_delay_min'] = mins
        await _broadcast_show_preview(query, context, scheduled=True)
    elif action == 'bc_sched_confirm':
        await _broadcast_do_send(query, context, scheduled=True)
    elif action == 'bc_edit':
        await _broadcast_ask_message(query, context, context.user_data.get('bc_target','all'), edit=True)

    elif action == 'bc_preview_back':
        # FIX باگ: بازگشت واقعی به پیش‌نمایش بدون ارسال پیام
        context.user_data.pop('bc_delay_min', None)
        await _broadcast_show_preview(query, context)

    elif action == 'bc_test':
        # ویژگی جدید: ارسال آزمایشی فقط به خود ادمین قبل از ارسال واقعی
        await _broadcast_send_test(query, context)

    # ── ⚠️ قابلیتِ جدید: دستیارِ نوشتنِ اطلاعیه با هوشیار ──
    elif action == 'bc_ai_start':
        context.user_data['mode'] = 'bc_ai_notes'
        await query.edit_message_text(
            "🤖 <b>نوشتنِ اطلاعیه با هوشیار</b>\n\n"
            "چندتا نکته/بولت‌پوینت درباره‌ی موضوعِ اطلاعیه بنویس "
            "(مثلاً: «هوشیار امروز آپدیت شد، سریع‌تر جواب می‌ده، همه می‌تونن استفاده کنن»)، "
            "هوشیار طبقِ استانداردِ رسمیِ هامزیار متنِ کامل رو می‌سازه:",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✏️ خودم می‌نویسم", callback_data='admin:bc_edit'),
                InlineKeyboardButton("❌ لغو", callback_data='admin:bc_cancel'),
            ]]))

    elif action == 'bc_ai_regen':
        await _broadcast_ai_generate(query, context)

    elif action == 'bc_ai_use':
        draft = context.user_data.get('bc_ai_draft', '')
        if not draft:
            await query.answer("⚠️ چیزی برای استفاده نیست.", show_alert=True)
            return
        context.user_data['bc_msg_data'] = {'type': 'text', 'text': draft}
        context.user_data['mode'] = ''
        context.user_data.pop('bc_ai_draft', None)
        await _broadcast_show_preview(query, context)


# ══════════════════════════════════════════════════
# 📢 توابع Broadcast
# ══════════════════════════════════════════════════

async def _broadcast_main(query, context):
    """
    ساختار صحیح:
    - همه کاربران
    - هر ورودی → زیرمنو: همه / گروه ۱ / گروه ۲
    """
    intakes   = await db.get_all_intakes()
    all_users = await db.all_users(approved_only=True)
    all_count = len(all_users)

    keyboard = [
        [InlineKeyboardButton(f"👥 همه کاربران ({all_count} نفر)", callback_data='admin:bc_target:all')],
    ]
    # هر ورودی یه دکمه جداگانه داره که زیرمنو باز میکنه
    for i in intakes:
        code   = i['code']
        label  = i['label']
        # شمارش کاربران این ورودی
        intake_users = [u for u in all_users if u.get('intake') == code]
        cnt    = len(intake_users)
        keyboard.append([InlineKeyboardButton(
            f"📅 {label} ({cnt} نفر)",
            callback_data=f'admin:bc_intake:{code}'
        )])

    keyboard.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:cat_comm')])
    await query.edit_message_text(
        "📢 <b>ارسال همگانی</b>\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📌 <b>مرحله ۱:</b> مخاطبین پیام را انتخاب کنید:",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _broadcast_ask_message(query, context, target: str, edit: bool = False):
    context.user_data['bc_target'] = target
    context.user_data['mode']      = 'broadcast'
    context.user_data.pop('bc_msg_data', None)
    target_label = _get_target_label(target)
    hint = "ویرایش" if edit else "ارسال"
    await query.edit_message_text(
        f"📢 <b>ارسال همگانی — {hint} پیام</b>\n\n"
        f"📌 مخاطب: <b>{target_label}</b>\n\n━━━━━━━━━━━━━━━━\n"
        "✍️ <b>مرحله ۲:</b> پیام خود را بنویسید:\n\n"
        "• متن (HTML پشتیبانی می‌شود)\n• عکس + کپشن\n• ویدیو + کپشن\n• فایل + کپشن\n\n"
        "<i>💡 قبل از ارسال، پیش‌نمایش نشان داده می‌شود.</i>\n\n"
        "یا بذار هوشیار برات بنویسه:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🤖 با هوشیار بنویس", callback_data='admin:bc_ai_start')],
            [InlineKeyboardButton("❌ لغو", callback_data='admin:bc_cancel')],
        ]))


async def _broadcast_ai_generate(query_or_msg, context, is_message: bool = False):
    """
    ⚠️ قابلیتِ جدید: تولیدِ متنِ اطلاعیه با هوشیار. اگه هوش مصنوعی به هر
    دلیلی (سهمیه، قطعی، کلید نامعتبر) کار نکنه، این تابع هرگز کرش نمی‌کنه
    و ادمین رو به مسیرِ دستیِ همیشگیِ نوشتنِ اطلاعیه (که مستقل از AI
    هست) هدایت می‌کنه.
    """
    from ai_solver import generate_broadcast_ai, AIError

    notes = context.user_data.get('bc_ai_notes', '')

    async def _edit(text, reply_markup):
        if is_message:
            await query_or_msg.reply_text(text, parse_mode='HTML', reply_markup=reply_markup)
        else:
            await query_or_msg.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)

    try:
        draft = await generate_broadcast_ai(notes)
    except AIError as e:
        await _edit(
            f"⚠️ هوشیار الان نتونست اطلاعیه بنویسه:\n<i>{e}</i>\n\n"
            "می‌تونی خودت دستی بنویسی — کاملاً مستقل از این مشکل کار می‌کنه.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 دوباره امتحان کن", callback_data='admin:bc_ai_regen')],
                [InlineKeyboardButton("✏️ خودم می‌نویسم", callback_data='admin:bc_edit')],
            ]))
        return
    except Exception:
        logger.exception("تولید اطلاعیه با AI ناموفق بود")
        await _edit(
            "⚠️ یه خطای غیرمنتظره پیش اومد. می‌تونی خودت دستی بنویسی.",
            InlineKeyboardMarkup([[InlineKeyboardButton("✏️ خودم می‌نویسم", callback_data='admin:bc_edit')]]))
        return

    context.user_data['bc_ai_draft'] = draft
    preview = f"👁 <b>پیش‌نمایشِ اطلاعیه</b>\n━━━━━━━━━━━━━━━━\n\n{draft}"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ استفاده از این متن", callback_data='admin:bc_ai_use')],
        [InlineKeyboardButton("🔄 دوباره بساز", callback_data='admin:bc_ai_regen')],
        [InlineKeyboardButton("✏️ خودم می‌نویسم", callback_data='admin:bc_edit')],
    ])
    await _edit(preview, keyboard)


async def _broadcast_show_preview(query_or_msg, context, scheduled: bool = False):
    msg_data     = context.user_data.get('bc_msg_data', {})
    target       = context.user_data.get('bc_target', 'all')
    target_label = _get_target_label(target)
    delay_min    = context.user_data.get('bc_delay_min', 0)
    msg_type     = msg_data.get('type', 'text')
    type_icons   = {'text':'📝 متن','photo':'🖼 عکس','video':'🎥 ویدیو','document':'📎 فایل','voice':'🎙 ویس','audio':'🎵 صدا'}
    type_label   = type_icons.get(msg_type, '📝')
    users_list   = await _get_target_users(target)
    user_count   = len(users_list)

    if msg_type == 'text':
        text_val = msg_data.get('text','')
        content_preview = (text_val[:200] + '...') if len(text_val) > 200 else text_val
        preview_block = f"<blockquote>{content_preview}</blockquote>"
    else:
        cap = msg_data.get('caption','')
        cap_preview = (cap[:100] + '...') if cap and len(cap) > 100 else cap
        preview_block = f"[{type_label}]"
        if cap_preview:
            preview_block += f"\n<blockquote>{cap_preview}</blockquote>"

    schedule_line = ""
    if delay_min and delay_min > 0:
        h = delay_min // 60
        m = delay_min % 60
        t_str = f"{fa_digits(h)} ساعت {fa_digits(m)} دقیقه" if h else f"{fa_digits(m)} دقیقه"
        send_time = format_time_fa(now_utc() + timedelta(minutes=delay_min))
        schedule_line = f"\n⏰ ارسال در: <b>{t_str} دیگر</b> (حدوداً ساعت {send_time})"

    info_text = (
        f"📢 <b>پیش‌نمایش و تأیید</b>\n\n"
        f"📌 مخاطب: <b>{target_label}</b>\n"
        f"👥 دریافت‌کنندگان: <b>{user_count} نفر</b>\n"
        f"📄 نوع پیام: <b>{type_label}</b>"
        f"{schedule_line}\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👁 <b>پیش‌نمایش:</b>\n\n"
        f"{preview_block}\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"آیا این پیام را ارسال می‌کنید؟"
    )

    confirm_cb = 'admin:bc_sched_confirm' if (scheduled and delay_min > 0) else 'admin:bc_confirm'
    keyboard = [
        [
            InlineKeyboardButton("✅ بله، ارسال کن", callback_data=confirm_cb),
            InlineKeyboardButton("✏️ ویرایش پیام",   callback_data='admin:bc_edit'),
        ],
        [InlineKeyboardButton("🧪 ارسال آزمایشی به خودم", callback_data='admin:bc_test')],
        [InlineKeyboardButton("⏰ ارسال زماندار",    callback_data='admin:bc_schedule')],
        [InlineKeyboardButton("❌ لغو",               callback_data='admin:bc_cancel')],
    ]

    try:
        if hasattr(query_or_msg, 'edit_message_text'):
            await query_or_msg.edit_message_text(info_text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query_or_msg.reply_text(info_text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.debug(f"preview error: {e}")
        try:
            msg = query_or_msg.message if hasattr(query_or_msg, 'message') else query_or_msg
            await msg.reply_text(info_text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            pass


async def _broadcast_schedule_menu(query, context):
    options = [
        ("⏰ ۱۵ دقیقه دیگر", 15), ("⏰ ۳۰ دقیقه دیگر", 30),
        ("⏰ ۱ ساعت دیگر",   60), ("⏰ ۲ ساعت دیگر",   120),
        ("⏰ ۶ ساعت دیگر",  360), ("⏰ ۱۲ ساعت دیگر",  720),
        ("⏰ ۲۴ ساعت دیگر",1440),
    ]
    keyboard = [[InlineKeyboardButton(label, callback_data=f'admin:bc_sched_set:{mins}')] for label, mins in options]
    # FIX باگ: این دکمه قبلاً به 'admin:bc_confirm' وصل بود که همان اکشن
    # «ارسال قطعی» است — یعنی با زدن «بازگشت به پیش‌نمایش» پیام واقعاً و
    # فوراً ارسال می‌شد! حالا به 'admin:bc_preview_back' وصل است که فقط
    # دوباره صفحه پیش‌نمایش را نشان می‌دهد، بدون ارسال.
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به پیش‌نمایش", callback_data='admin:bc_preview_back')])
    keyboard.append([InlineKeyboardButton("❌ لغو", callback_data='admin:bc_cancel')])
    await query.edit_message_text("⏰ <b>ارسال زماندار</b>\n\nچه زمانی پیام ارسال شود?",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _broadcast_send_test(query, context):
    """
    ویژگی جدید: ارسال آزمایشی پیام همگانی — دقیقاً همان محتوای آماده‌شده
    (متن/عکس/ویدیو/فایل/ویس/صدا با همان کپشن و parse_mode) فقط برای
    خود ادمین ارسال می‌شود. state پیش‌نمایش دست‌نخورده می‌ماند تا ادمین
    بعد از دیدن نتیجه واقعی هنوز بتواند «ویرایش پیام»، «ارسال قطعی» یا
    «لغو» را انتخاب کند — نه اینکه ارسال آزمایشی خودش را جای ارسال
    واقعی جا بزند.
    """
    msg_data = context.user_data.get('bc_msg_data', {})
    if not msg_data:
        await query.answer("❌ پیامی برای ارسال آزمایشی وجود ندارد!", show_alert=True)
        return
    tester_uid = query.from_user.id
    sent, _, _ = await _do_broadcast_send_guarded(context.bot, [{'user_id': tester_uid}], msg_data)
    if sent:
        await query.answer("✅ پیام آزمایشی برای شما ارسال شد — پایین چت خودتان را چک کنید.", show_alert=True)
    else:
        await query.answer("❌ ارسال آزمایشی ناموفق بود.", show_alert=True)


async def _broadcast_do_send(query, context, scheduled: bool = False):
    msg_data  = context.user_data.get('bc_msg_data', {})
    target    = context.user_data.get('bc_target', 'all')
    delay_min = context.user_data.get('bc_delay_min', 0) if scheduled else 0

    if not msg_data:
        await query.answer("❌ پیامی برای ارسال وجود ندارد!", show_alert=True)
        return

    # FIX (حرفه‌ای‌سازی): جلوگیری از دابل‌تپ روی «ارسال کن» — اگر یک
    # ارسال از قبل در حال انجام است، دوباره شروع نشود (وگرنه پیام دوبار
    # برای همه فرستاده می‌شود).
    if context.user_data.get('bc_sending'):
        await query.answer("⏳ ارسال قبلی هنوز در حال انجام است، صبر کنید...", show_alert=True)
        return

    if delay_min > 0:
        h = delay_min // 60
        m = delay_min % 60
        t_str = f"{fa_digits(h)} ساعت {fa_digits(m)} دقیقه" if h else f"{fa_digits(m)} دقیقه"
        due = now_utc() + timedelta(minutes=delay_min)
        send_time = format_time_fa(due)
        campaign = await create_broadcast_campaign(
            payload=msg_data, target=target, created_by=query.from_user.id,
            created_by_name=query.from_user.full_name or "مدیر", source="bot",
            send_at=due.isoformat(), enqueue=True)
        _broadcast_clear(context)
        await query.edit_message_text(
            f"✅ <b>پیام زماندار ثبت شد!</b>\n\n"
            f"🆔 کمپین: <code>{campaign['campaign_id']}</code>\n"
            f"👥 گیرنده: <b>{campaign['recipient_count']}</b>\n"
            f"⏰ ارسال خواهد شد در: <b>{t_str} دیگر</b>\n"
            f"🕐 حدوداً ساعت: <b>{send_time}</b>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:cat_comm')]]))
        return

    context.user_data['bc_sending'] = True
    try:
        status_msg = await query.edit_message_text(
            "⏳ <b>در حال ارسال پیام...</b>\n\nدر حال آماده‌سازی فهرست مخاطبان...",
            parse_mode='HTML')
    except Exception:
        status_msg = query.message

    users_list = await _get_target_users(target)
    total = len(users_list)

    if total == 0:
        context.user_data['bc_sending'] = False
        _broadcast_clear(context)
        await status_msg.edit_text(
            "⚠️ <b>هیچ مخاطبی برای این هدف پیدا نشد.</b>\n\nپیامی ارسال نشد.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:cat_comm')]]))
        return

    campaign = await create_broadcast_campaign(
        payload=msg_data, target=target, created_by=query.from_user.id,
        created_by_name=query.from_user.full_name or "مدیر", source="bot",
        enqueue=False)

    async def _progress(done, total_n, sent_n, failed_n, blocked_n):
        pct = int(done * 100 / total_n) if total_n else 100
        try:
            await status_msg.edit_text(
                f"⏳ <b>در حال ارسال پیام...</b>\n\n"
                f"📊 پیشرفت: <b>{done}/{total_n}</b> ({pct}%)\n"
                f"✅ موفق: {sent_n}  |  🚫 بلاک: {blocked_n}  |  ❌ سایر خطاها: {failed_n - blocked_n}",
                parse_mode='HTML')
        except Exception:
            pass  # ادیت خیلی سریع پشت سر هم ممکنه با محدودیت تلگرام مواجه بشه — بی‌خطر نادیده گرفته می‌شود

    try:
        # FIX (حرفه‌ای‌سازی): همه‌ی مراحل ارسال داخل try/finally هستند
        # تا در صورت بروز هر خطای پیش‌بینی‌نشده‌ای، پرچم bc_sending
        # همیشه آزاد شود و ادمین برای همیشه پشت یک ارسالِ «گیر کرده»
        # قفل نماند.
        await _broadcast_inbox_mirror(users_list, msg_data)
        sent, failed_total, blocked = await _do_broadcast_send_guarded(
            context.bot, users_list, msg_data, progress_cb=_progress)
    finally:
        context.user_data['bc_sending'] = False

    other_failed = failed_total - blocked
    await finish_broadcast_direct(campaign["campaign_id"], sent, failed_total)
    _broadcast_clear(context)
    # FIX طبق سند: ارسال همگانی سراسری = CRITICAL (نه WARNING)،
    # چون اگر اشتباه به همه فرستاده شود باید فوری و برجسته معلوم باشد.
    actor_id   = query.from_user.id
    actor_user = await db.get_user(actor_id)
    actor_name = actor_user.get('name', 'مدیر') if actor_user else 'مدیر'
    actor_role = await db.get_actor_role_label(actor_id)
    await send_audit_log(
        context.bot, 'admin', actor_name, actor_id,
        "ارسال همگانی", module='Notifications', severity='CRITICAL',
        actor_role=actor_role,
        target_type='broadcast', target_label=f"هدف: {target}",
        details=f"موفق: {sent} | بلاک: {blocked} | سایر خطاها: {other_failed} | مجموع: {total}",
        tags=['ارسال_همگانی']
    )
    await status_msg.edit_text(
        f"📢 <b>ارسال همگانی تمام شد</b>\n\n━━━━━━━━━━━━━━━━\n"
        f"✅ موفق: <b>{sent} نفر</b>\n"
        f"🚫 مسدود کرده‌اند (بلاک ربات): <b>{blocked} نفر</b>\n"
        f"❌ سایر خطاها: <b>{other_failed} نفر</b>\n"
        f"📊 مجموع مخاطبان: <b>{total} نفر</b>",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:cat_comm')]]))


async def _scheduled_broadcast_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    msg_data = data.get('msg_data', {})
    target   = data.get('target', 'all')
    admin_id = data.get('admin_id', ADMIN_ID)
    users_list = await _get_target_users(target)
    await _broadcast_inbox_mirror(users_list, msg_data)
    sent, failed_total, blocked = await _do_broadcast_send_guarded(context.bot, users_list, msg_data)
    other_failed = failed_total - blocked
    # پاک‌سازی رکورد ماندگارشده — دیگر لازم نیست چون همین الان ارسال شد
    try:
        job_name = context.job.name
        await db.delete_setting(f'scheduled_broadcast_{job_name}')
    except Exception:
        pass
    try:
        await context.bot.send_message(admin_id,
            f"📢 <b>ارسال زماندار انجام شد</b>\n\n"
            f"✅ موفق: <b>{sent} نفر</b>\n"
            f"🚫 بلاک: <b>{blocked} نفر</b>\n"
            f"❌ سایر خطاها: <b>{other_failed} نفر</b>",
            parse_mode='HTML')
    except Exception:
        pass


async def _broadcast_inbox_mirror(users_list: list, msg_data: dict) -> None:
    """
    🔔 موج ۴.۹۰ — انعکاس اطلاعیه‌ی همگانی در مرکز اعلان مینی‌اپ.
    مثل همه‌ی نویسنده‌های اینباکس: سابقه‌ی رویداد برای همه‌ی مخاطبان ثبت
    می‌شود، نه فقط کسانی که پیام تلگرامشان رسید — کاربری که ربات را بلاک
    کرده باز هم می‌تواند اطلاعیه را در مینی‌اپ ببیند (همگام‌سازی واقعی).
    فقط در دو نقطه‌ی ارسالِ واقعی صدا زده می‌شود؛ ارسالِ «تست» پنل،
    اینباکس کاربر را شلوغ نمی‌کند.
    """
    import re as _re
    raw = (msg_data.get('text') or msg_data.get('caption') or '').strip()
    body = _re.sub(r'<[^>]+>', '', raw).strip() or 'پیام همگانی مدیریت'
    await db.inbox_add_many([
        {'user_id': u['user_id'], 'type': 'announcement',
         'title': '📢 اطلاعیه‌ی مدیریت', 'body': body, 'link': None}
        for u in users_list if u.get('user_id')
    ])


async def _do_broadcast_send_guarded(bot, users_list: list, msg_data: dict, progress_cb=None) -> tuple:
    """
    FIX کامل (حرفه‌ای‌سازی ارسال همگانی):
    - RetryAfter (محدودیت نرخ تلگرام) → صبر دقیق به‌اندازه‌ی زمان اعلام‌شده
      و تلاش مجدد برای همان کاربر، به‌جای شمردنش به‌عنوان ناموفق.
    - TimedOut / NetworkError (خطای موقت شبکه) → یک تلاش مجدد کوتاه.
    - Forbidden (کاربر ربات را بلاک/غیرفعال کرده) → به‌طور جداگانه شمرده
      و در دیتابیس علامت‌گذاری می‌شود (blocked_bot) تا آمار واقعی و
      قابل‌اعتماد باشد، نه فقط یک عدد «ناموفق» مبهم.
    - سایر خطاها (BadRequest و غیره) → ناموفق، ولی ارسال به بقیه‌ی
      کاربران متوقف نمی‌شود.
    - progress_cb (اختیاری): هر ۲۵ نفر یک‌بار صدا زده می‌شود تا پیام
      «در حال ارسال...» زنده بروزرسانی شود.
    """
    sent, failed, blocked = 0, 0, 0
    msg_type = msg_data.get('type', 'text')
    caption  = msg_data.get('caption', '')
    file_id  = msg_data.get('file_id', '')
    text_val = msg_data.get('text', '')
    total    = len(users_list)

    for i, u in enumerate(users_list):
        uid = u['user_id']
        ok  = False
        for attempt in range(3):
            try:
                # renderer واحد با Web outbox و test-send؛ payload دوم نداریم.
                await send_broadcast_payload(bot, uid, msg_data)
                ok = True
                break
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + 0.5)
                continue  # همین کاربر را دوباره امتحان کن، ناموفق حساب نشود
            except Forbidden:
                blocked += 1
                await db.mark_user_blocked(uid)
                break
            except (TimedOut, NetworkError):
                await asyncio.sleep(1.5)
                continue
            except BadRequest:
                logger.warning(f"broadcast BadRequest for uid={uid}")
                break
            except Exception:
                logger.exception(f"broadcast unexpected error for uid={uid}")
                break
        if ok:
            sent += 1
        else:
            failed += 1

        if progress_cb and ((i + 1) % 25 == 0 or (i + 1) == total):
            try:
                await progress_cb(i + 1, total, sent, failed, blocked)
            except Exception:
                pass

        # کنترل نرخ ارسال — برای جلوگیری از محدودیت تلگرام
        if i % 30 == 29:
            await asyncio.sleep(1)
        else:
            await asyncio.sleep(0.05)

    return sent, failed + blocked, blocked


# 🌊 W3 — wrapper with semaphore to avoid starvation


async def _get_target_users(target: str) -> list:
    """
    فرمت‌های پشتیبانی‌شده:
      all              → همه کاربران
      g1 / g2          → گروه ۱ یا ۲ از همه ورودی‌ها
      intake_CODE      → همه کاربران یک ورودی
      intake_CODE_g1   → گروه ۱ از ورودی CODE
      intake_CODE_g2   → گروه ۲ از ورودی CODE
    """
    return await resolve_broadcast_recipients(target, actor_id=ADMIN_ID)


def _get_target_label(target: str) -> str:
    labels = {'all': 'همه کاربران', 'g1': 'گروه ۱ (همه ورودی‌ها)', 'g2': 'گروه ۲ (همه ورودی‌ها)'}
    if target in labels:
        return labels[target]
    if target.startswith('intake_'):
        rest = target[7:]
        if rest.endswith('_g1'):
            return f"ورودی {rest[:-3]} — گروه ۱"
        elif rest.endswith('_g2'):
            return f"ورودی {rest[:-3]} — گروه ۲"
        return f"ورودی {rest}"
    return target


def _broadcast_clear(context):
    for key in ['bc_target', 'bc_msg_data', 'bc_delay_min', 'mode']:
        context.user_data.pop(key, None)


async def admin_broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت پیام و نمایش preview — فراخوانی از unified handlers در bot.py"""
    uid = update.effective_user.id
    # FIX باگ: قبلاً فقط ADMIN_ID اجازه داشت، پس نقش‌های فرعی که
    # مجوز broadcast دارند (مثلاً 'broadcaster' یا 'bot_admin') هیچ‌وقت
    # نمی‌تونستن واقعاً پیام همگانی بفرستن — متنشون گرفته نمی‌شد.
    if uid != ADMIN_ID:
        perms = await db.get_user_perms(uid)
        # 🛡 RBAC-W3 — تصمیم نهایی فقط از permissionهای مشترک می‌آید.
        if 'broadcast.send' not in perms and 'broadcast' not in perms:
            return
    if context.user_data.get('mode') != 'broadcast':
        return

    msg = update.message
    if msg.text:
        context.user_data['bc_msg_data'] = {'type': 'text', 'text': msg.text}
    elif msg.photo:
        context.user_data['bc_msg_data'] = {'type': 'photo', 'file_id': msg.photo[-1].file_id, 'caption': msg.caption or ''}
    elif msg.video:
        context.user_data['bc_msg_data'] = {'type': 'video', 'file_id': msg.video.file_id, 'caption': msg.caption or ''}
    elif msg.document:
        context.user_data['bc_msg_data'] = {'type': 'document', 'file_id': msg.document.file_id, 'caption': msg.caption or ''}
    elif msg.voice:
        context.user_data['bc_msg_data'] = {'type': 'voice', 'file_id': msg.voice.file_id, 'caption': ''}
    elif msg.audio:
        context.user_data['bc_msg_data'] = {'type': 'audio', 'file_id': msg.audio.file_id, 'caption': msg.caption or ''}
    else:
        await msg.reply_text("❌ این نوع پیام پشتیبانی نمی‌شود.\nلطفاً متن، عکس، ویدیو یا فایل ارسال کنید.")
        return

    context.user_data['mode'] = ''  # reset mode
    await _broadcast_show_preview(msg, context)


# ══════════════════════════════════════════════════
# نمایش‌دهنده‌ها
# ══════════════════════════════════════════════════

async def _show_bot_status(query, context):
    """
    FIX جدید: مانیتورینگ واقعی سلامت سیستم با psutil — مصرف RAM/CPU
    پروسه و کانتینر، uptime واقعی، تعداد کاربران آنلاین تقریبی.
    روی Railway این اعداد مربوط به همان کانتینر ربات است (نه کل
    سرور فیزیکی) — دقیقاً همان چیزی که برای پایش خود ربات لازم است.
    """
    import time
    from datetime import datetime

    db_status = "disconnected"
    db_ping   = "—"
    try:
        t0 = time.monotonic()
        await db.client.admin.command("ping")
        db_ping   = f"{int((time.monotonic()-t0)*1000)} ms"
        db_status = "✅ متصل"
    except Exception as e:
        db_status = f"❌ خطا: {str(e)[:30]}"

    jobs_info = []
    try:
        if context.application.job_queue:
            for job in context.application.job_queue.jobs():
                nxt = job.next_t
                nxt_str = format_time_fa(nxt) if nxt else "—"
                jobs_info.append(f"  ⏰ {job.name}  |  بعدی: {nxt_str}")
    except Exception:
        pass
    jobs_text = "\n".join(jobs_info) if jobs_info else "  —"

    # FIX جدید: متریک‌های واقعی سیستم با psutil
    sys_lines = []
    try:
        import psutil, os
        proc = psutil.Process(os.getpid())

        # حافظه پروسه ربات (مهم‌ترین عدد — واقعاً ربات چقدر مصرف می‌کند)
        mem_mb = proc.memory_info().rss / 1024 / 1024

        # حافظه کل کانتینر
        vm = psutil.virtual_memory()
        vm_used_mb  = vm.used / 1024 / 1024
        vm_total_mb = vm.total / 1024 / 1024

        # CPU (۰.۳ ثانیه نمونه‌گیری — سریع و کافی برای یک عدد لحظه‌ای)
        # FIX: این یک فراخوانی blocking است؛ در ترد جداگانه اجرا می‌شود
        # تا event loop اصلی ربات در این ۰.۳ ثانیه قفل نشود.
        cpu_pct = await asyncio.to_thread(psutil.cpu_percent, 0.3)

        # uptime واقعی پروسه ربات (نه زمان سرور)
        uptime_sec = time.time() - proc.create_time()
        h, rem = divmod(int(uptime_sec), 3600)
        m, s_  = divmod(rem, 60)
        uptime_str = f"{h} ساعت {m} دقیقه" if h else f"{m} دقیقه {s_} ثانیه"

        # رنگ‌بندی هشدار بر اساس فشار منابع
        ram_icon = "🟢" if vm.percent < 70 else "🟡" if vm.percent < 90 else "🔴"
        cpu_icon = "🟢" if cpu_pct < 70 else "🟡" if cpu_pct < 90 else "🔴"

        sys_lines = [
            "",
            "━━━━━━━━━━━━━━━━",
            "🖥 <b>سلامت سیستم</b>",
            "",
            f"{ram_icon} <b>RAM کانتینر:</b> {vm_used_mb:.0f} / {vm_total_mb:.0f} MB  ({vm.percent}%)",
            f"   └ مصرف خود ربات: {mem_mb:.1f} MB",
            f"{cpu_icon} <b>CPU:</b> {cpu_pct}%",
            f"⏱ <b>مدت کارکرد ربات:</b> {uptime_str}",
        ]
    except ImportError:
        sys_lines = [
            "",
            "━━━━━━━━━━━━━━━━",
            "🖥 <b>سلامت سیستم:</b> ⚠️ psutil نصب نیست",
        ]
    except Exception as e:
        sys_lines = [
            "",
            "━━━━━━━━━━━━━━━━",
            f"🖥 <b>سلامت سیستم:</b> ⚠️ خطا در خوانش ({str(e)[:40]})",
        ]

    # FIX جدید: کاربران آنلاین تقریبی (فعالیت در ۳۰ دقیقه و امروز)
    try:
        online_30m = await db.count_active_users(30)
        active_today = await db.count_active_users_today()
        online_line = f"🟢 آنلاین (۳۰ دقیقه اخیر): <b>{online_30m}</b>  |  فعال امروز: <b>{active_today}</b>"
    except Exception:
        online_line = "🟢 آنلاین: داده در دسترس نیست"

    s = await db.global_stats()
    now_str = now_tehran_str()
    lines_t = [
        "📡 <b>وضعیت ربات</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        f"🗄 <b>دیتابیس:</b> {db_status}",
        f"🏓 <b>پینگ DB:</b> {db_ping}",
        "",
        "⏰ <b>Job های فعال:</b>",
        jobs_text,
    ] + sys_lines + [
        "",
        "━━━━━━━━━━━━━━━━",
        "📊 <b>آمار کلی</b>",
        "",
        online_line,
        f"👥 کاربران تأیید: <b>{s['users']}</b>",
        f"⏳ منتظر تأیید: <b>{s['pending']}</b>",
        f"🧪 سوال تأییدشده: <b>{s['questions']}</b>",
        f"📁 محتوای علوم پایه: <b>{s.get('bs_content', 0)}</b>",
        f"📖 رفرنس ها: <b>{s.get('ref_files', 0)}</b>",
        f"🎫 تیکت باز: <b>{s.get('open_tickets', 0)}</b>",
        "",
        "━━━━━━━━━━━━━━━━",
        f"🕐 زمان سرور: <code>{now_str}</code>",
    ]
    text = "\n".join(lines_t)
    await query.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 بروزرسانی", callback_data="admin:bot_status")],
            [InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin:cat_settings")],
        ])
    )


def _mini_bar(value: int, max_value: int, width: int = 10) -> str:
    """نمودار میله‌ای متنی ساده برای نمایش روند در تلگرام (بدون نیاز به تصویر)"""
    if max_value <= 0:
        return "░" * width
    filled = round((value / max_value) * width)
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


async def _show_admin_insights(query):
    """
    🧠 مرکز هوش ربات — جمع‌بندی هوشمندِ rule-based روی داده‌های واقعی:
    هشدارهای قابل‌اقدام (تأخیر در تأیید/تیکت، سوالات پرخطا، ادمین
    غیرفعال، محتوای جاافتاده) + روند و پیش‌بینی ساده‌ی رشد هفته‌ی بعد.
    """
    d = await db.admin_insights()

    wc = d['week_counts']  # [این‌هفته, ۱هفته‌پیش, ۲هفته‌پیش, ۳هفته‌پیش]
    wmax = max(wc or [1]) or 1
    trend_lines = "\n".join(
        f"  {label}  {_mini_bar(c, wmax, 10)}  <b>{c}</b>"
        for label, c in zip(['این هفته  ', '۱ هفته پیش', '۲ هفته پیش', '۳ هفته پیش'], wc)
    )

    if d['alerts']:
        alert_lines = "\n\n".join(
            f"{a['icon']} <b>{a['title']}</b>" + (f"\n   └ {a['detail']}" if a['detail'] else '')
            for a in d['alerts']
        )
    else:
        alert_lines = "✅ در حال حاضر هیچ هشدار فعالی وجود ندارد — همه‌چیز مرتب است."

    medals = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣']
    if d.get('top_admins'):
        top_admin_lines = "\n".join(
            f"  {medals[i]} {a['name']} ({a['role']}) — {a['count']} کنش"
            for i, a in enumerate(d['top_admins'])
        )
    else:
        top_admin_lines = "  — این هفته هیچ فعالیتی از ادمین‌های فرعی ثبت نشده"

    text = (
        "🧠 <b>مرکز هوش ربات</b>\n━━━━━━━━━━━━━━━━\n"
        "تحلیل خودکار وضعیت ربات بر اساس داده‌های واقعی؛ بدون نیاز به گشتن دستی بین صفحات.\n\n"
        "🚨 <b>هشدارهای قابل‌اقدام</b>\n"
        f"{alert_lines}\n\n"
        "👑 <b>پرکارترین ادمین‌های فرعی (۷ روز اخیر)</b>\n"
        f"{top_admin_lines}\n\n"
        "📈 <b>روند ثبت‌نام ۴ هفته اخیر</b>\n"
        f"{trend_lines}\n\n"
        f"🔮 <b>پیش‌بینی هفته‌ی آینده: حدود <u>{d['forecast_next_week']}</u> ثبت‌نام جدید</b>\n"
        f"  (بر مبنای میانگین {d['prior_avg']} در هفته‌های قبل + روند اخیر)"
    )

    buttons = []
    for a in d['alerts']:
        buttons.append([InlineKeyboardButton(f"{a['icon']} رسیدگی: {a['title'][:28]}", callback_data=a['action'])])
    buttons.append([InlineKeyboardButton("🔄 بروزرسانی", callback_data='admin:insights')])
    buttons.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:main')])

    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(buttons))


async def _show_stats(query):
    """
    صفحه‌ی خلاصه‌ی آمار — یک نگاه کلی سریع به کل ربات + دکمه‌های ورود
    به هر بخش برای جزئیات کامل. اعداد این صفحه تقریبی و برای مرور
    سریع‌اند؛ عدد دقیق و کامل هر بخش در زیرصفحه‌ی مخصوص خودش است.
    """
    s, pulse = await asyncio.gather(db.global_stats(), db.activity_pulse())

    peak_txt = "—"
    if pulse.get('peak_hour') is not None:
        h = int(pulse['peak_hour'])
        peak_txt = f"ساعت {fa_digits(f'{h:02d}:00–{(h+1)%24:02d}:00')} ({fa_digits(pulse['peak_hour_count'])} کنش)"

    text = (
        "📊 <b>آمار سیستم — نمای کلی</b>\n━━━━━━━━━━━━━━━━\n\n"
        f"👥 کاربران تأیید: <b>{s['users']}</b>  |  ⏳ منتظر تأیید: <b>{s['pending']}</b>\n"
        f"🆕 جدید این هفته: <b>{s.get('new_users_week', 0)}</b>  |  "
        f"🟢 آنلاین اکنون: <b>{s.get('online_30m', 0)}</b>\n\n"
        f"🔬 محتوای علوم پایه: <b>{s.get('bs_content', 0)}</b> فایل در <b>{s.get('bs_lessons', 0)}</b> درس\n"
        f"📚 رفرنس‌ها: <b>{s.get('ref_books', 0)}</b> کتاب در <b>{s.get('ref_subjects', 0)}</b> درس\n"
        f"🧪 بانک سوال: <b>{s['questions']}</b> سوال تأییدشده\n"
        f"⬇️ مجموع دانلود کل ربات: <b>{s.get('total_downloads', 0)}</b>\n"
        f"🎫 تیکت‌های باز: <b>{s.get('open_tickets', 0)}</b>\n\n"
        "⚡ <b>نبض فعالیت (۷ روز اخیر)</b>\n"
        f"  🔥 مجموع کنش‌های ثبت‌شده: <b>{pulse.get('total_actions_week', 0)}</b>\n"
        f"  ⏰ پرترافیک‌ترین ساعت: <b>{peak_txt}</b>\n\n"
        "برای آمار کامل و جزئی هر بخش، از دکمه‌های زیر استفاده کنید 👇"
    )
    await query.edit_message_text(text, parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🧠 مرکز هوش ربات (هشدار و پیش‌بینی)", callback_data='admin:insights')],
            [
                InlineKeyboardButton("👥 آمار کاربران", callback_data='admin:stats_users'),
                InlineKeyboardButton("📚 آمار محتوا",   callback_data='admin:stats_content'),
            ],
            [
                InlineKeyboardButton("🧪 آمار بانک سوال", callback_data='admin:stats_questions'),
                InlineKeyboardButton("🎫 آمار تیکت‌ها",   callback_data='admin:stats_tickets'),
            ],
            [InlineKeyboardButton("🔔 سلامت اعلان‌های خودکار", callback_data='admin:stats_notif')],
            [InlineKeyboardButton("🖥 وضعیت سرور/ربات", callback_data='admin:bot_status')],
            [InlineKeyboardButton("🔄 بروزرسانی", callback_data='admin:stats')],
            [InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:main')],
        ]))


async def _show_stats_users(query):
    """آمار جزئی کاربران: رشد، فعالیت، تفکیک گروه/ورودی، نقش‌های فرعی"""
    d = await db.stats_dashboard_users()

    growth_max = max([c for _, c in d['growth_7d']] or [1])
    growth_lines = "\n".join(
        f"  {date}  {_mini_bar(cnt, growth_max, 8)}  <b>{cnt}</b>"
        for date, cnt in d['growth_7d']
    )

    intake_lines = "\n".join(
        f"  • {label}: <b>{cnt}</b>" for label, cnt in d['by_intake'][:8]
    ) or "  —"

    role_label = {
        'support': '🎫 پشتیبان', 'content_admin': '🎓 ادمین ارشد محتوا',
        'content_scoped': '📅 ادمین محتوای ورودی خاص', 'broadcaster': '📢 مسئول اطلاعیه',
        'reviewer': '🤓 خرخون', 'bot_admin': '👮 ادمین ربات',
    }
    role_lines = "\n".join(
        f"  • {role_label.get(r, r)}: <b>{c}</b>" for r, c in d['sub_admin_roles'].items()
    ) or "  —"

    medals = ['🥇', '🥈', '🥉']
    top_lines = "\n".join(
        f"  {medals[i]} {u.get('name', 'کاربر')} — "
        f"{int(u.get('correct_answers', 0) or 0)}/{int(u.get('total_answers', 0) or 0)}"
        for i, u in enumerate(d.get('top_users', []))
    ) or "  — هنوز فعالیتی ثبت نشده"

    engagement_rate = round(d['active_week'] / d['total_approved'] * 100, 1) if d['total_approved'] else 0

    text = (
        "👥 <b>آمار جزئی کاربران</b>\n━━━━━━━━━━━━━━━━\n\n"
        f"✅ تأییدشده: <b>{d['total_approved']}</b>   ⏳ منتظر تأیید: <b>{d['total_pending']}</b>\n"
        f"🆕 امروز: <b>{d['new_today']}</b>  |  ۷ روز اخیر: <b>{d['new_week']}</b>  |  ۳۰ روز اخیر: <b>{d['new_month']}</b>\n\n"
        f"📈 <b>روند ثبت‌نام ۷ روز اخیر:</b>\n{growth_lines}\n\n"
        f"🟢 فعال امروز: <b>{d['active_today']}</b>   🟢 فعال این هفته: <b>{d['active_week']}</b>\n"
        f"💡 <b>نرخ مشارکت هفتگی: {engagement_rate}٪</b> از کل کاربران\n"
        f"😴 غیرفعال ۱۴+ روز: <b>{d['inactive_14d']}</b>   😴 غیرفعال ۳۰+ روز: <b>{d['inactive_30d']}</b>\n"
        f"🚫 بلاک‌کرده ربات را: <b>{d['blocked_bot']}</b>\n\n"
        f"🏷 <b>گروه:</b> گروه ۱: <b>{d['group1']}</b>  |  گروه ۲: <b>{d['group2']}</b>  |  بدون گروه: <b>{d['group_unset']}</b>\n\n"
        f"📅 <b>تفکیک بر اساس ورودی:</b>\n{intake_lines}\n\n"
        f"🏆 <b>برترین کاربران:</b>\n{top_lines}\n\n"
        f"👮 <b>نقش‌های فرعی ادمین:</b>\n{role_lines}\n"
        f"🎓 ادمین ارشد محتوا: <b>{d['content_admins']}</b>"
    )
    await query.edit_message_text(text, parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 بروزرسانی", callback_data='admin:stats_users')],
            [InlineKeyboardButton("🔙 بازگشت به آمار", callback_data='admin:stats')],
        ]))


async def _show_stats_content(query):
    """آمار جزئی محتوا: علوم پایه به‌تفکیک نوع، رفرنس به‌تفکیک زبان، دانلودها"""
    d = await db.stats_dashboard_content()

    bs_type_lines = "\n".join(
        f"  • {label}: <b>{cnt}</b>" for label, cnt in d['bs_types'].items()
    ) or "  —"
    ref_lang_lines = "\n".join(
        f"  • {label}: <b>{cnt}</b>" for label, cnt in d['ref_langs'].items()
    ) or "  —"
    top_qbank_lines = "\n".join(
        f"  • {lesson}: <b>{cnt}</b> سؤال" for lesson, cnt in d['top_qbank_lessons']
    ) or "  —"

    total_downloads = d['bs_downloads'] + d['ref_downloads']

    text = (
        "📚 <b>آمار جزئی محتوا</b>\n━━━━━━━━━━━━━━━━\n\n"
        f"🆕 منابع جدید این هفته: <b>{d.get('new_this_week', 0)}</b>\n\n"
        f"🔬 <b>علوم پایه</b> — {d['bs_lessons']} درس، {d['bs_sessions']} جلسه، "
        f"{d['bs_total_content']} فایل\n{bs_type_lines}\n\n"
        f"📚 <b>رفرنس‌ها</b> — {d['ref_subjects']} درس، {d['ref_books']} کتاب، "
        f"{d['ref_total_files']} فایل\n{ref_lang_lines}\n\n"
        f"❓ سوالات متداول (FAQ): <b>{d['faq_count']}</b>\n\n"
        f"🧪 <b>بانک سؤال ساختاریافته</b> — <b>{d['qbank_questions']}</b> سؤال تأییدشده\n"
        f"پرسؤال‌ترین درس‌ها:\n{top_qbank_lines}\n"
        f"🧠 کل تلاش‌های ثبت‌شده: <b>{d['qbank_attempts']}</b>\n\n"
        f"⬇️ <b>مجموع دانلود منابع: {total_downloads}</b>\n"
        f"  • علوم پایه: {d['bs_downloads']}  |  رفرنس: {d['ref_downloads']}"
    )
    await query.edit_message_text(text, parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 بروزرسانی", callback_data='admin:stats_content')],
            [InlineKeyboardButton("🔙 بازگشت به آمار", callback_data='admin:stats')],
        ]))


async def _show_stats_questions(query):
    """آمار جزئی بانک سوال: دقت پاسخ‌دهی، پرسوال‌ترین درس‌ها، سخت‌ترین سوالات"""
    d = await db.stats_dashboard_questions()

    diff_max = max(d['by_difficulty'].values() or [1])
    diff_lines = "\n".join(
        f"  {label}  {_mini_bar(cnt, diff_max, 8)}  <b>{cnt}</b>"
        for label, cnt in d['by_difficulty'].items()
    ) or "  —"
    lesson_max = max([c for _, c in d['top_lessons']] or [1])
    top_lesson_lines = "\n".join(
        f"  {_mini_bar(cnt, lesson_max, 8)}  <b>{cnt}</b>  {lesson}"
        for lesson, cnt in d['top_lessons']
    ) or "  —"

    if d['hardest_questions']:
        hardest_lines = "\n".join(
            f"  {i+1}. {h['question']}...\n"
            f"      ({h['lesson']} / {h['topic']}) — نرخ خطا: <b>{h['wrong_rate']}٪</b> "
            f"از {h['attempts']} تلاش"
            for i, h in enumerate(d['hardest_questions'])
        )
    else:
        hardest_lines = "  داده کافی نیست (حداقل ۵ تلاش برای هر سوال لازم است)"

    text = (
        "🧪 <b>آمار جزئی بانک سوال</b>\n━━━━━━━━━━━━━━━━\n\n"
        f"✅ تأییدشده: <b>{d['approved']}</b>   ⏳ در انتظار بررسی: <b>{d['pending']}</b>\n"
        f"  └ 🤖 تولید ربات: <b>{d.get('by_bot', 0)}</b>  |  ✍️ کاربران: <b>{d.get('by_users', 0)}</b>\n\n"
        f"📊 <b>تفکیک سطح دشواری:</b>\n{diff_lines}\n\n"
        f"📖 <b>پرسوال‌ترین درس‌ها:</b>\n{top_lesson_lines}\n\n"
        f"🎯 <b>دقت کلی پاسخ‌دهی کاربران: {d['accuracy']}٪</b>\n"
        f"  (از مجموع <b>{d['total_attempts']}</b> پاسخ، <b>{d['total_correct']}</b> صحیح بوده)\n\n"
        f"😵 <b>سخت‌ترین سوالات (بیشترین نرخ خطا):</b>\n{hardest_lines}"
    )
    await query.edit_message_text(text, parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 بروزرسانی", callback_data='admin:stats_questions')],
            [InlineKeyboardButton("🔙 بازگشت به آمار", callback_data='admin:stats')],
        ]))


async def _show_stats_tickets(query):
    """آمار جزئی پشتیبانی"""
    d = await db.stats_dashboard_tickets()
    close_rate = round(d['closed'] / d['total'] * 100, 1) if d['total'] else 0
    if d.get('avg_resolution_h') is not None:
        h = d['avg_resolution_h']
        res_txt = f"<b>{h}</b> ساعت" if h < 48 else f"<b>{round(h/24, 1)}</b> روز"
        res_line = f"⏱ میانگین زمان رسیدگی (۳۰ روز اخیر): {res_txt}  (بر مبنای {d['resolved_sample']} تیکت)"
    else:
        res_line = "⏱ میانگین زمان رسیدگی: داده کافی نیست"
    text = (
        "🎫 <b>آمار جزئی تیکت‌های پشتیبانی</b>\n━━━━━━━━━━━━━━━━\n\n"
        f"📂 باز: <b>{d['open']}</b>   ✅ بسته‌شده: <b>{d['closed']}</b>   "
        f"جمع کل: <b>{d['total']}</b>\n"
        f"📈 نرخ رسیدگی کلی: <b>{close_rate}٪</b>\n"
        f"{res_line}\n\n"
        f"🆕 تیکت جدید این هفته: <b>{d['new_week']}</b>\n"
        f"🆕 تیکت جدید این ماه: <b>{d['new_month']}</b>\n"
        f"✅ بسته‌شده در ۷ روز اخیر: <b>{d['closed_week']}</b>"
    )
    await query.edit_message_text(text, parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 بروزرسانی", callback_data='admin:stats_tickets')],
            [InlineKeyboardButton("🔙 بازگشت به آمار", callback_data='admin:stats')],
        ]))


async def _show_stats_notif(query):
    """سلامت اعلان‌های خودکار — بر اساس ۱۰ اجرای اخیر هر job"""
    d = await db.stats_dashboard_notif()
    job_labels = {
        'exam_reminder':  '🔔 یادآوری امتحان',
        'daily_question': '📝 سوال روزانه',
        'new_resources':  '📦 اعلان منابع جدید',
    }
    status_icon = {'ok': '✅', 'error': '❌', 'success': '✅'}
    blocks = []
    for job, info in d.items():
        label = job_labels.get(job, job)
        if not info:
            blocks.append(f"<b>{label}</b>\n  — هنوز اجرا نشده")
            continue
        rate = round(
            info['total_sent'] / (info['total_sent'] + info['total_failed']) * 100, 1
        ) if (info['total_sent'] + info['total_failed']) else 0
        icon = status_icon.get(info['last_status'], 'ℹ️')
        blocks.append(
            f"<b>{label}</b>\n"
            f"  {icon} آخرین اجرا: {info['last_at'] or '—'}  "
            f"(موفق: {info['last_sent']}، ناموفق: {info['last_failed']})\n"
            f"  📊 نرخ موفقیت {info['runs_checked']} اجرای اخیر: <b>{rate}٪</b>"
        )
    text = "🔔 <b>سلامت اعلان‌های خودکار</b>\n━━━━━━━━━━━━━━━━\n\n" + "\n\n".join(blocks)
    await query.edit_message_text(text, parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📜 تاریخچه کامل اعلان‌ها", callback_data='admin:notif_history')],
            [InlineKeyboardButton("🔄 بروزرسانی", callback_data='admin:stats_notif')],
            [InlineKeyboardButton("🔙 بازگشت به آمار", callback_data='admin:stats')],
        ]))


async def _show_users_list(query, context, page: int = 0, group: str = None, intake: str = None):
    # FIX UX: صفحه فعلی لیست کاربران را نگه می‌داریم تا دکمه «بازگشت به
    # لیست» در صفحه جزئیات کاربر، دقیقاً به همین صفحه و فیلتر برگردد
    # — نه همیشه به صفحه اول.
    context.user_data['users_page'] = page
    all_users = await db.all_users(approved_only=False)
    if group:
        all_users = [u for u in all_users if u.get('group') == group]
    if intake:
        all_users = [u for u in all_users if u.get('intake') == intake]
    per_page = 8
    total    = len(all_users)
    approved = sum(1 for u in all_users if u.get('approved'))
    start    = page * per_page
    chunk    = all_users[start:start + per_page]
    filter_parts = []
    if group:  filter_parts.append(f"گروه {group}")
    if intake: filter_parts.append(f"ورودی {intake}")
    filter_label = f" | 🔽 {' + '.join(filter_parts)}" if filter_parts else ""
    text = f"👥 <b>کاربران{filter_label}</b>\n✅ تأیید: {approved} | ⏳ منتظر: {total-approved} | مجموع: {total}\n\n"
    keyboard = []
    for u in chunk:
        icon  = "✅" if u.get('approved') else "⏳"
        role  = "🎓" if u.get('role') == 'content_admin' else ""
        itak  = f" | {u.get('intake','')}" if u.get('intake') else ""
        keyboard.append([InlineKeyboardButton(
            f"{icon}{role} {u.get('name','')[:10]} | گروه {u.get('group','')}{itak}",
            callback_data=f'admin:user_detail:{u["user_id"]}')])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ قبلی", callback_data=f'admin:users:{page-1}'))
    if start + per_page < total:
        nav.append(InlineKeyboardButton("بعدی ▶️", callback_data=f'admin:users:{page+1}'))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔽 فیلتر", callback_data='admin:users_filter'), InlineKeyboardButton("🔍 جستجو", callback_data='admin:search_user')])
    if group or intake:
        keyboard.append([InlineKeyboardButton("❌ حذف فیلتر", callback_data='admin:uf_clear')])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:cat_users')])
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_users_filter(query, context):
    intakes  = await db.get_all_intakes()
    f_group  = context.user_data.get('filter_group')
    f_intake = context.user_data.get('filter_intake')
    keyboard = [
        [InlineKeyboardButton("━━ فیلتر گروه ━━", callback_data='admin:users_filter')],
        [
            InlineKeyboardButton(f"{'✅' if not f_group else '⬜'} همه", callback_data='admin:uf_group:all'),
            InlineKeyboardButton(f"{'✅' if f_group=='1' else '⬜'} گروه ۱", callback_data='admin:uf_group:1'),
            InlineKeyboardButton(f"{'✅' if f_group=='2' else '⬜'} گروه ۲", callback_data='admin:uf_group:2'),
        ],
        [InlineKeyboardButton("━━ فیلتر ورودی ━━", callback_data='admin:users_filter')],
        [InlineKeyboardButton("همه ورودی‌ها", callback_data='admin:uf_intake:all')],
    ]
    for i in intakes:
        active = f_intake == i['code']
        keyboard.append([InlineKeyboardButton(f"{'✅' if active else '⬜'} {i['label']}", callback_data=f'admin:uf_intake:{i["code"]}')])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f'admin:users:{context.user_data.get("users_page", 0)}')])
    active_filters = []
    if f_group:  active_filters.append(f"گروه {f_group}")
    if f_intake: active_filters.append(f_intake)
    current = f"فعال: {' + '.join(active_filters)}" if active_filters else "بدون فیلتر"
    await query.edit_message_text(f"🔽 <b>فیلتر کاربران</b>\n{current}", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_user_detail(query, context, target_uid: int):
    user = await db.get_user(target_uid)
    if not user:
        await query.answer("کاربر پیدا نشد!", show_alert=True)
        return
    stats   = await db.user_stats(target_uid)
    status  = "✅ تأیید شده" if user.get('approved') else "⏳ در انتظار"
    role_m  = {'student': '🧑‍🎓 دانشجو', 'content_admin': '🎓 ادمین ارشد محتوا'}
    role_t  = role_m.get(user.get('role','student'), user.get('role',''))
    uname   = f"@{user['username']}" if user.get('username') else 'ندارد'
    tickets = await db.ticket_get_user(target_uid)
    open_t  = sum(1 for t in tickets if t['status'] == 'open')

    # FIX جدید: وضعیت اشتراک هم اینجا نشون داده بشه، نه فقط توی پنل اشتراک جدا
    sub = await db.sub_get(target_uid)
    if sub and sub.get('status') == 'active' and await db.sub_is_active(target_uid):
        sub_days = await db.sub_days_left(target_uid)
        sub_line = f"💳 اشتراک: ✅ فعال — {sub_days} روز مانده ({sub.get('plan_name','-')})"
    elif sub and sub.get('status') == 'revoked':
        sub_line = f"💳 اشتراک: 🚫 لغوشده ({sub.get('revoke_reason','-')})"
    elif sub and sub.get('status') == 'expired':
        sub_line = "💳 اشتراک: ⌛ منقضی‌شده"
    else:
        sub_line = "💳 اشتراک: ⚠️ نداره"

    text = (
        f"👤 <b>پروفایل کاربر</b>\n━━━━━━━━━━━━━━━━\n\n"
        f"📛 نام: <b>{user.get('name','')}</b>\n"
        f"🏷 لقب: <b>{user.get('nickname') or '—'}</b>\n"  # 🏷 Identity v1
        f"🎓 شماره: <code>{user.get('student_id','') or '—'}</code>\n"
        f"👥 گروه: <b>{user.get('group','')}</b>\n"
        f"📱 یوزرنیم: {uname}\n"
        f"🆔 آیدی: <code>{target_uid}</code>\n"
        f"🔘 وضعیت: {status}  |  نقش: {role_t}\n"
        f"📅 ورودی: <b>{user.get('intake','') or 'ثبت نشده'}</b>\n"
        f"📅 ثبت‌نام: {fmt_jalali_dt(user.get('registered_at',''), with_time=False)}\n"
        f"{sub_line}\n\n"
        f"📊 <b>آمار:</b>\n"
        f"  📥 دانلود: {stats['downloads']}  🧪 سوال: {stats['total_answers']}  ✅ صحیح: {stats['correct_answers']}\n"
        f"  📈 درصد: {stats['percentage']}%  🔥 هفتگی: {stats['week_activity']}\n"
        f"  🎫 تیکت باز: {open_t}"
    )
    keyboard = [
        [
            InlineKeyboardButton("✏️ ویرایش نام",  callback_data=f'admin:edit_name:{target_uid}'),
            InlineKeyboardButton("✏️ ویرایش گروه", callback_data=f'admin:edit_group:{target_uid}'),
        ],
        [InlineKeyboardButton("📅 ویرایش ورودی", callback_data=f'admin:edit_intake:{target_uid}')],
        [InlineKeyboardButton("💳 مدیریت اشتراک این کاربر", callback_data=f'suba:user:{target_uid}')],
    ]
    # ✉️ موج ۴.۸۰ — پیام مستقیم به کاربر از کارت مدیریت.
    # فقط مدیر ارشد: مرحله‌ی تایپ پیام مثل همه‌ی modeهای متنیِ
    # پنل به ADMIN_ID محدود است (bot.py unified_text_handler).
    if query.from_user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("✉️ ارسال پیام به این کاربر", callback_data=f'admin:dm_user:{target_uid}')])
    if user.get('role','student') == 'student':
        keyboard.append([InlineKeyboardButton("🎓 دادن دسترسی محتوا", callback_data=f'admin:ca_set:{target_uid}')])
    elif user.get('role') == 'content_admin':
        keyboard.append([InlineKeyboardButton("↩️ لغو دسترسی محتوا", callback_data=f'admin:ca_remove:{target_uid}')])
    if user.get('approved'):
        keyboard.append([InlineKeyboardButton("🚫 تعلیق", callback_data=f'admin:suspend:{target_uid}')])
    else:
        keyboard.append([InlineKeyboardButton("✅ تأیید", callback_data=f'admin:approve:{target_uid}'), InlineKeyboardButton("❌ رد", callback_data=f'admin:reject:{target_uid}')])
    keyboard.append([InlineKeyboardButton("🗑 حذف کامل", callback_data=f'admin:confirm_delete_user:{target_uid}')])
    keyboard.append([InlineKeyboardButton("🚫 بلاک کامل (حذف + جلوگیری از ثبت‌نام مجدد)", callback_data=f'admin:confirm_block_user:{target_uid}')])
    back_page = context.user_data.get('users_page', 0)
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به لیست", callback_data=f'admin:users:{back_page}')])
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_pending(query):
    pending = await db.pending_users()
    if not pending:
        await query.edit_message_text("✅ هیچ کاربر در انتظاری وجود ندارد.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:cat_users')]]))
        return
    keyboard = []
    for u in pending:
        uid = u['user_id']
        keyboard.append([InlineKeyboardButton(f"👤 {u.get('name','')} | {u.get('student_id','') or 'بدون شماره'} | گروه {u.get('group','')}", callback_data=f'admin:user_detail:{uid}')])
        keyboard.append([InlineKeyboardButton("✅ تأیید", callback_data=f'admin:approve:{uid}'), InlineKeyboardButton("❌ رد", callback_data=f'admin:reject:{uid}')])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:cat_users')])
    await query.edit_message_text(f"⏳ <b>کاربران در انتظار</b> — {len(pending)} نفر", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_blacklist(query):
    """🚫 لیست کاربران بلاک‌شده — با دکمه‌ی رفع بلاک برای هرکدام"""
    entries = await db.get_blacklist()
    if not entries:
        await query.edit_message_text(
            "🚫 <b>بلک‌لیست</b>\n━━━━━━━━━━━━━━━━\n\nهیچ کاربری بلاک نشده است.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='admin:cat_users')]]))
        return
    keyboard = []
    lines = []
    for e in entries[:30]:
        target_uid = e['_id']
        reason = e.get('reason', '') or 'بدون دلیل ثبت‌شده'
        by     = e.get('blocked_by_name', '')
        when   = fmt_jalali_dt(e.get('blocked_at', '') or '', with_time=False)
        # 🔧 FIX: `reason` خوانده می‌شد ولی هیچ‌وقت نمایش داده نمی‌شد
        # (pyflakes هم آن را متغیرِ بی‌مصرف گزارش می‌کرد). دلیلِ مسدودی
        # مهم‌ترین اطلاعِ این صفحه است: بدون آن، ادمینِ دوم نمی‌داند
        # رفعِ بلاک درست است یا نه. پنل وب این فیلد را نشان می‌دهد؛
        # حالا ربات هم همان را نشان می‌دهد (پاریتی).
        lines.append(
            f"🆔 <code>{target_uid}</code> — {_esc(when)}"
            + (f" — توسط {_esc(by)}" if by else '')
            + f"\n     └ 📝 {_esc(reason[:120])}"
        )
        keyboard.append([
            InlineKeyboardButton(f"↩️ رفع بلاک {target_uid}", callback_data=f'admin:unblock_user:{target_uid}')
        ])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='admin:cat_users')])
    text = (
        f"🚫 <b>بلک‌لیست</b> — {len(entries)} نفر\n━━━━━━━━━━━━━━━━\n\n"
        + "\n".join(lines) +
        "\n\n<i>این کاربران با همین آیدی عددی نمی‌توانند دوباره ثبت‌نام کنند.</i>"
    )
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))



async def _show_notif_manage(query):
    """
    FIX جدید: مدیریت اعلان‌ها از پنل ادمین — تنظیم فاصله زمانی
    اعلان منابع جدید + دسترسی به تاریخچه ارسال هر job + دکمه‌ی
    ارسال فوری (بدون نیاز به صبر تا پایان بازه) + تشخیص خطای اخیر.
    """
    from utils import fmt_jalali
    interval = await db.get_setting('resource_notif_interval_hours', 24)
    pending  = await db.get_unnotified_resources()
    last_sent_str = await db.get_setting('resource_notif_last_sent', None)
    last_error    = await db.get_setting('resource_notif_last_error', None)

    if last_sent_str:
        last_sent_dt = parse_machine_datetime(last_sent_str)
        elapsed_h = round((now_utc() - last_sent_dt).total_seconds() / 3600, 1)
        remaining_h = round(interval - elapsed_h, 1)
        timing_line = (
            f"🕐 آخرین ارسال: {fmt_jalali_dt(last_sent_str)} ({elapsed_h} ساعت پیش)\n"
            + (f"⏭ ارسال بعدی: حدود {remaining_h} ساعت دیگه\n" if remaining_h > 0
               else "⏭ الان وقتشه، منتظر اجرای بعدی job (حداکثر تا ۱ ساعت دیگه) یا بزن «ارسال فوری»\n")
        )
    else:
        timing_line = "🕐 هنوز هیچ ارسالی ثبت نشده.\n"

    error_line = f"\n🔴 <b>آخرین خطا:</b> {last_error}\n" if last_error else ""

    text = (
        "📢 <b>مدیریت اعلان‌ها</b>\n━━━━━━━━━━━━━━━━\n\n"
        f"📚 <b>فاصله اعلان منابع جدید:</b> هر {interval} ساعت\n"
        f"⏳ منابع در انتظار اعلام: <b>{len(pending)}</b> مورد\n"
        f"{timing_line}"
        f"{error_line}\n"
        "━━━━━━━━━━━━━━━━\n"
        "برای مشاهده تاریخچه ارسال هر دسته از اعلان‌ها، یکی را انتخاب کنید:"
    )
    keyboard = [
        [
            InlineKeyboardButton("24 ساعت" + (" ✅" if interval == 24 else ""), callback_data='admin:notif_set_interval:24'),
            InlineKeyboardButton("48 ساعت" + (" ✅" if interval == 48 else ""), callback_data='admin:notif_set_interval:48'),
            InlineKeyboardButton("72 ساعت" + (" ✅" if interval == 72 else ""), callback_data='admin:notif_set_interval:72'),
        ],
        [InlineKeyboardButton(f"🚀 ارسال فوری الان ({len(pending)} مورد در صف)", callback_data='admin:notif_force_send')],
        [InlineKeyboardButton("⚙️ وضعیت پیش‌فرض اعلان‌ها (همه کاربران)", callback_data='admin:notif_defaults')],
        [InlineKeyboardButton("📚 تاریخچه: منابع جدید",   callback_data='admin:notif_history:new_resources')],
        [InlineKeyboardButton("📝 تاریخچه: یادآوری امتحان", callback_data='admin:notif_history:exam_reminder')],
        [InlineKeyboardButton("🧪 تاریخچه: سوال روزانه",   callback_data='admin:notif_history:daily_question')],
        [InlineKeyboardButton("📋 همه اجراهای اخیر",        callback_data='admin:notif_history')],
        [InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:cat_comm')],
    ]
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _handle_notif_force_send(query):
    """FIX جدید: ارسال فوری منابع جدید — بدون نیاز به صبر تا پایان بازه‌ی ۲۴/۴۸/۷۲ ساعته"""
    from bot import _run_new_resources_notif
    # توجه: admin_callback از قبل یک‌بار query.answer() را صدا زده،
    # پس اینجا دوباره answer() نمی‌زنیم (تلگرام اجازه‌ی answer دوم را نمی‌دهد)
    result = await _run_new_resources_notif(query.get_bot(), force=True)
    if result.get('sent'):
        msg = (f"✅ ارسال فوری انجام شد.\n{result['items']} مورد به {result['users_sent']} نفر "
               f"ارسال شد (ناموفق: {result['users_failed']}).")
    elif result.get('reason') == 'no_items':
        msg = "ℹ️ چیزی در صف نیست که ارسال بشه."
    elif result.get('reason') == 'already_running':
        msg = "⚠️ یک دور ارسال قبلاً همین حالا در جریان است؛ صبر کن یا بعداً دوباره بزن."
    elif result.get('reason') == 'error':
        msg = f"❌ خطا در ارسال: {result.get('error','نامشخص')[:200]}"
    else:
        msg = "⚠️ ارسال نشد."
    await query.message.reply_text(msg)
    await _show_notif_manage(query)


async def _show_notif_defaults(query):
    """
    FIX (بخش سوم): تعیین وضعیت پیش‌فرض (روشن/خاموش) هر دسته اعلان.
    برخلاف قبل، این مقدار همین لحظه روی همه کاربران — قدیمی، جدید،
    فعال و غیرفعال — اعمال می‌شود (نه فقط کاربران تازه ثبت‌نام‌شده).
    """
    # 🧩 N3-fix — NOTIF_ITEMS قدیمی حذف شده بود؛ منبع واحد =
    # کاتالوگ db. کلیدها Canonical‌اند و handler توگل با همان
    # canonical می‌نویسد — زنجیره‌ی set/get سرتاسر یکدست.
    defaults = await db.get_notif_defaults()
    text = (
        "⚙️ <b>وضعیت پیش‌فرض اعلان‌ها</b>\n━━━━━━━━━━━━━━━━\n\n"
        "تغییر هر مورد، همین الان روی <b>همه کاربران</b> "
        "(قدیمی و جدید) اعمال می‌شود."
    )
    keyboard = []
    for key, label, _desc, _d in db.NOTIF_CATALOG:
        is_on = defaults.get(key, True)
        icon  = "🔔" if is_on else "🔕"
        keyboard.append([InlineKeyboardButton(
            f"{icon} {label} — {'روشن' if is_on else 'خاموش'}",
            callback_data=f'admin:notif_default_toggle:{key}'
        )])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='admin:notif_manage')])
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_notif_history(query, job_name: str = None):
    """
    FIX جدید: نمایش تاریخچه اجراهای notif_runs — وضعیت موفق/ناموفق
    هر اجرا، با دکمه retry برای اجراهایی که شکست داشته‌اند.
    """
    runs = await db.get_recent_notif_runs(job_name, limit=10)
    job_label = {
        'new_resources': '📚 منابع جدید', 'exam_reminder': '📝 یادآوری امتحان',
        'daily_question': '🧪 سوال روزانه',
    }.get(job_name, '📋 همه اعلان‌ها')

    if not runs:
        text = f"{job_label}\n\nهنوز هیچ اجرایی ثبت نشده."
        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data='admin:notif_manage')]]
    else:
        lines = [f"{job_label}\n━━━━━━━━━━━━━━━━"]
        keyboard = []
        for r in runs:
            started = fmt_jalali_dt(r.get('started_at'))
            status  = r.get('status', 'running')
            icon    = {'completed': '✅', 'error': '❌', 'skipped': '⏭', 'running': '⏳'}.get(status, '❔')
            sent    = r.get('sent', 0)
            failed  = r.get('failed', 0)
            lines.append(
                f"\n{icon} <code>{_esc(started)}</code>\n"
                f"   ✅ موفق: {sent}  |  ❌ ناموفق: {failed}"
            )
            if failed > 0:
                rid = str(r['_id'])
                keyboard.append([InlineKeyboardButton(
                    f"🔄 تلاش مجدد — {started}", callback_data=f'admin:notif_retry:{rid}'
                )])
        text = '\n'.join(lines)
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='admin:notif_manage')])

    await query.edit_message_text(text[:4000], parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _retry_failed_notif(query, context, run_id: str):
    """
    FIX جدید: ارسال مجدد برای کاربرانی که در یک اجرای قبلی fail شدند
    — این‌بار با محتوای واقعی همان پیام (نه یک متن کلی جایگزین)،
    چون اکنون notif_runs متن دقیق هر پیام را هم ذخیره می‌کند.
    """
    details = await db.get_failed_notif_details(run_id)
    if not details:
        # سازگاری با اجراهای قدیمی‌تر که هنوز متن پیام ذخیره نشده بود
        failed_ids = await db.get_failed_notif_targets(run_id)
        if not failed_ids:
            await query.answer("✅ موردی برای تلاش مجدد نیست.", show_alert=True)
            return
        details = [{
            'user_id': uid_target,
            'message': (
                "🔔 <b>یادآوری</b>\n\nاین پیام به دلیل خطای موقت دوباره ارسال شد. "
                "برای جزئیات به بخش‌های مربوطه ربات مراجعه کنید."
            ),
        } for uid_target in failed_ids]

    sent, failed = 0, 0
    for rec in details:
        ok = await safe_send(context.bot, rec['user_id'], rec['message'], parse_mode='HTML')
        if ok:
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(0.05)
    await query.answer(f"✅ {sent} ارسال موفق، {failed} هنوز ناموفق", show_alert=True)


async def _show_channel_lock(query):
    """
    FIX جدید: مدیریت قفل اجباری عضویت کانال — لیست کانال‌های فعلی
    + دکمه افزودن/حذف. اگر هیچ کانالی نباشد، قفل عملاً غیرفعال است.
    """
    channels = await db.get_required_channels()
    text = (
        "🔒 <b>قفل اجباری عضویت کانال</b>\n━━━━━━━━━━━━━━━━\n\n"
        + (
            f"📌 {len(channels)} کانال فعال — کاربران عادی باید عضو همه آن‌ها باشند:\n\n"
            if channels else
            "⬜ هیچ کانالی تنظیم نشده — قفل غیرفعال است.\n\n"
        )
    )
    keyboard = []
    for ch in channels:
        keyboard.append([InlineKeyboardButton(
            f"🗑 {ch['title']}", callback_data=f'admin:channel_lock_remove:{ch["id"]}'
        )])
    keyboard.append([InlineKeyboardButton("➕ افزودن کانال جدید", callback_data='admin:channel_lock_add')])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data='admin:settings')])
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_settings(query):
    """
    FIX جدید: صفحه تنظیمات کلی ربات — شامل اجباری‌بودن شماره
    دانشجویی، حالت تعمیر و نگهداری، گروه‌های لاگ، و کانال نظرسنجی.
    """
    require_sid = await db.get_setting('require_student_id', False)
    maint       = await db.get_setting('maintenance_mode', False)
    log_admin   = await db.get_setting('log_group_admin', None)
    log_content = await db.get_setting('log_group_content', None)
    poll_channel = await db.get_setting('poll_channel_id', None)
    missing     = await db.users_missing_student_id()

    sid_status   = "✅ فعال (اجباری)" if require_sid else "⬜ غیرفعال (اختیاری)"
    sid_toggle    = "🔴 غیرفعال کردن" if require_sid else "🟢 فعال کردن"
    maint_status = "🔧 فعال (ربات در دسترس کاربران عادی نیست)" if maint else "✅ غیرفعال (ربات عادی کار می‌کند)"
    maint_toggle  = "🟢 خاموش کردن حالت تعمیر" if maint else "🔴 روشن کردن حالت تعمیر"
    admin_grp_txt = f"<code>{log_admin}</code>" if log_admin else "تنظیم نشده"
    content_grp_txt = f"<code>{_esc(log_content)}</code>" if log_content else "تنظیم نشده"
    poll_channel_txt = f"<code>{_esc(poll_channel)}</code>" if poll_channel else "⚠️ تنظیم نشده"

    text = (
        "⚙️ <b>تنظیمات ربات</b>\n━━━━━━━━━━━━━━━━\n\n"
        f"🎓 <b>الزامی بودن شماره دانشجویی:</b> {sid_status}\n"
        f"👥 کاربران بدون شماره دانشجویی: <b>{len(missing)}</b> نفر\n\n"
        f"🔧 <b>حالت تعمیر و نگهداری:</b> {maint_status}\n\n"
        f"🛡 گروه لاگ پنل ادمین: {admin_grp_txt}\n"
        f"🎓 گروه لاگ پنل محتوا: {content_grp_txt}\n\n"
        f"📊 کانال نظرسنجی / اطلاع‌رسانی: {poll_channel_txt}\n"
    )
    channels = await db.get_required_channels()
    channel_label = f"🔒 قفل کانال: {len(channels)} کانال فعال" if channels else "🔓 قفل کانال: غیرفعال"

    keyboard = [
        [InlineKeyboardButton(sid_toggle, callback_data='admin:toggle_require_sid')],
        [InlineKeyboardButton(maint_toggle, callback_data='admin:toggle_maintenance')],
        [InlineKeyboardButton("✏️ متن حالت تعمیر", callback_data='admin:set_maintenance_text')],
        [InlineKeyboardButton("🛡 تنظیم گروه لاگ ادمین", callback_data='admin:set_log_group_admin')],
        [InlineKeyboardButton("🎓 تنظیم گروه لاگ محتوا", callback_data='admin:set_log_group_content')],
        [InlineKeyboardButton("🧪 تست ارسال به گروه‌های لاگ", callback_data='admin:test_log_groups')],
        [InlineKeyboardButton("📊 تنظیم کانال نظرسنجی", callback_data='admin:set_poll_channel')],
        [InlineKeyboardButton(channel_label, callback_data='admin:channel_lock')],
        [InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:cat_settings')],
    ]
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _test_log_groups(query, context):
    """
    🧪 FIX جدید: فرستادن یک پیام تست واقعی به هر دو گروه لاگ و گزارش
    نتیجه‌ی دقیق (✅/❌ + متن خطا) در همین‌جا — تا سلامت اتصال گروه‌ها
    بدون حدس‌زدن قابل بررسی باشد. اگر ارسال شکست بخورد، send_audit_log
    هم از این پس به پیوی مدیر ارشد یک‌بار هشدار می‌دهد.
    """
    results = []
    for key, label in (('log_group_admin', '🛡 گروه لاگ مدیریت'),
                       ('log_group_content', '🎓 گروه لاگ محتوا')):
        chat_id = await db.get_setting(key, None)
        if not chat_id:
            results.append(f"{label}: ⬜ تنظیم نشده")
            continue
        try:
            await context.bot.send_message(
                int(chat_id),
                f"🧪 <b>پیام تست</b>\n\nاگر این پیام را می‌بینی، اتصال "
                f"{label} سالم است. ✅\n"
                f"🕒 {now_tehran_str()}",
                parse_mode='HTML'
            )
            results.append(f"{label}: ✅ پیام تست ارسال شد (<code>{chat_id}</code>)")
        except Exception as e:
            results.append(
                f"{label}: ❌ خطا در ارسال\n<code>{_esc(str(e)[:150])}</code>\n"
                f"💡 ربات را دوباره به گروه اضافه/ادمین کن یا آیدی را دوباره تنظیم کن."
            )
    results.append(
        "\n<i>از این پس اگر ارسال یک لاگ واقعی هم شکست بخورد، یک‌بار به "
        "پیوی مدیر ارشد هشدار داده می‌شود (تا با اصلاح گروه).</i>"
    )
    await query.edit_message_text(
        "🧪 <b>نتیجه‌ی تست گروه‌های لاگ</b>\n━━━━━━━━━━━━━━━━\n\n" + "\n\n".join(results),
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⚙️ بازگشت به تنظیمات", callback_data='admin:settings')
        ]])
    )


async def _show_donation_manage(query):
    """
    💙 پنل مدیریت بخش حمایت مالی — فعال/غیرفعال کردن دکمه در
    داشبورد کاربران و تنظیم/حذف لینک صفحه حمایت (مثل reymit).
    """
    enabled = await db.get_setting('donation_enabled', False)
    link    = await db.get_setting('donation_link', None)

    status_txt = "✅ فعال (در داشبورد نمایش داده می‌شود)" if enabled else "⬜ غیرفعال (در داشبورد مخفی است)"
    toggle_txt = "🔴 غیرفعال کردن" if enabled else "🟢 فعال کردن"
    link_txt   = f"<code>{link}</code>" if link else "⚠️ تنظیم نشده"

    text = (
        "💙 <b>مدیریت حمایت مالی</b>\n━━━━━━━━━━━━━━━━\n\n"
        f"📊 وضعیت نمایش: {status_txt}\n\n"
        f"🔗 لینک فعلی: {link_txt}\n\n"
        "<i>کاربران با زدن دکمه «💙 حمایت مالی» در داشبورد مستقیماً به این لینک هدایت می‌شوند.</i>"
    )
    if enabled and not link:
        text += "\n\n⚠️ توجه: بخش فعال است اما لینکی تنظیم نشده — دکمه در داشبورد نمایش داده نمی‌شود تا لینک ثبت کنید."

    keyboard = [
        [InlineKeyboardButton(toggle_txt, callback_data='admin:donation_toggle')],
        [InlineKeyboardButton("✏️ تنظیم / تغییر لینک", callback_data='admin:set_donation_link')],
    ]
    if link:
        keyboard.append([InlineKeyboardButton("🗑 حذف لینک", callback_data='admin:remove_donation_link')])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:cat_settings')])

    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_audit_log(query, category: str, min_severity: str = None, module: str = None):
    """
    FIX بازطراحی کامل طبق سند جدید Audit Log — نمایش هر لاگ با ساختار
    actor{name,role}/target{label}/changes/تگ‌ها، هماهنگ با مدل داده
    جدید database.py. در کمتر از ۵ ثانیه باید همه‌چیز معلوم باشد.
    """
    logs = await db.get_recent_logs(category, min_severity, module, limit=20)
    sev_icon = {'INFO': '🟢', 'WARNING': '🟡', 'HIGH': '🟠', 'CRITICAL': '🔴'}

    if not logs:
        text = "📋 <b>لاگ فعالیت</b>\n\nهیچ موردی با این فیلتر یافت نشد."
    else:
        lines = ["📋 <b>لاگ فعالیت</b>\n━━━━━━━━━━━━━━━━"]
        for log in logs:
            ts = fmt_jalali_dt(log.get('timestamp'))
            icon = sev_icon.get(log.get('severity', 'INFO'), '🟢')
            module_en = log.get('module', '')
            module_fa = db.MODULE_LABELS_FA.get(module_en, module_en)
            module_tag = f" [{module_fa}]" if module_fa else ""

            actor = log.get('actor', {})
            actor_name = actor.get('name', '') if isinstance(actor, dict) else log.get('actor_name', '')
            actor_role = actor.get('role', '') if isinstance(actor, dict) else log.get('actor_role', '')

            target = log.get('target', {})
            target_label = target.get('label', '') if isinstance(target, dict) else ''

            lines.append(f"\n{icon} <code>{ts}</code>{module_tag}")
            lines.append(f"👤 {actor_name} ({actor_role}) — <b>{log.get('action','')}</b>")
            if target_label:
                lines.append(f"🎯 {target_label}")

            changes = log.get('changes', [])
            if changes:
                for ch in changes:
                    lines.append(f"   {ch.get('field','')}: {ch.get('before','—')} ← {ch.get('after','—')}")
            elif log.get('details'):
                lines.append(f"   📝 {log['details']}")
        text = '\n'.join(lines)

    filter_label = {
        None: "همه سطوح", 'WARNING': "🟡 WARNING به بالا",
        'HIGH': "🟠 HIGH به بالا", 'CRITICAL': "🔴 فقط CRITICAL",
    }.get(min_severity, "همه سطوح")
    text = f"🔽 فیلتر: {filter_label}\n\n" + text

    keyboard = [
        [
            InlineKeyboardButton("همه" + (" ✅" if not min_severity else ""), callback_data='admin:audit_log:all'),
            InlineKeyboardButton("🟡 WARNING+" + (" ✅" if min_severity == 'WARNING' else ""), callback_data='admin:audit_log:WARNING'),
        ],
        [
            InlineKeyboardButton("🟠 HIGH+" + (" ✅" if min_severity == 'HIGH' else ""), callback_data='admin:audit_log:HIGH'),
            InlineKeyboardButton("🔴 CRITICAL" + (" ✅" if min_severity == 'CRITICAL' else ""), callback_data='admin:audit_log:CRITICAL'),
        ],
        [InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:cat_settings')],
    ]
    await query.edit_message_text(
        text[:4000], parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _export_excel(query, context):
    """
    خروجی کامل دیتابیس از پنل ربات — حالا روی ماژول مشترک
    excel_report سوار است تا سمت web (صف bot_notifications)
    هم دقیقاً همان خروجی را تحویل بگیرد.
    """
    uid = query.from_user.id
    await query.edit_message_text("⏳ <b>در حال ساخت فایل اکسل...</b>", parse_mode='HTML')
    try:
        from excel_report import build_database_excel
        buf, fname, caption, counts = await build_database_excel()
        await query.message.reply_document(
            document=buf, filename=fname, caption=caption, parse_mode='HTML'
        )
        # خروجی گرفتن دیتابیس شامل اطلاعات حساس کاربران است —
        # باید ثبت شود که کِی و توسط کدام مدیر دانلود شد.
        admin_user_doc = await db.get_user(uid)
        actor_name = admin_user_doc.get('name', 'مدیر ارشد') if admin_user_doc else 'مدیر ارشد'
        actor_role = await db.get_actor_role_label(uid)
        await send_audit_log(
            context.bot, 'admin', actor_name, uid,
            "خروجی اکسل دیتابیس", module='Backup', severity='HIGH',
            actor_role=actor_role,
            details=f"{counts['users']} کاربر | {counts['tickets']} تیکت | {counts['questions']} سوال",
            tags=['خروجی_اکسل']
        )
    except Exception as e:
        logger.error(f"excel export error: {e}")
        await query.message.reply_text("❌ خطا در ساخت فایل اکسل — جزئیات در لاگ سرور.")

async def _show_intakes(query):
    intakes = await db.get_all_intakes()
    keyboard = []
    for i in intakes:
        code  = i['code']
        label = i['label']
        icon  = "✅" if i.get('active', True) else "❌"
        keyboard.append([
            InlineKeyboardButton(f"{icon} {label}", callback_data=f'admin:intake_view:{code}'),
            InlineKeyboardButton("🔄", callback_data=f'admin:intake_toggle:{code}'),
            InlineKeyboardButton("🗑", callback_data=f'admin:intake_del:{code}'),
        ])
    keyboard.append([InlineKeyboardButton("➕ افزودن ورودی جدید", callback_data='admin:intake_add')])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:cat_users')])
    await query.edit_message_text(
        "📅 <b>مدیریت ورودی‌های دانشجویی</b>\n\n━━━━━━━━━━━━━━━━\n✅=فعال | ❌=غیرفعال | 🔄=تغییر | 🗑=حذف",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


# ══════════════════════════════════════════════════
# 🛡 سطوح دسترسی چندگانه ادمین — UI
# ══════════════════════════════════════════════════

async def _show_roles(query):
    """لیست نقش‌های فرعی فعلی + دکمه افزودن"""
    roles = await db.get_all_admin_roles()
    keyboard = []
    if not roles:
        text = (
            "🛡 <b>سطوح دسترسی ادمین</b>\n\n"
            "━━━━━━━━━━━━━━━━\n"
            "هنوز هیچ نقش فرعی تعریف نشده.\n\n"
            "💡 شما (مدیر ارشد) همیشه دسترسی کامل دارید.\n"
            "می‌توانید برای دیگران نقش محدودتر بسازید:\n"
            "• 🎫 پشتیبان — فقط پاسخ به تیکت\n"
            "• 🎓 ادمین ارشد محتوا / 📅 ادمین محتوای ورودی خاص\n"
            "• 📢 مسئول اطلاعیه — فقط ارسال همگانی"
        )
    else:
        text = "🛡 <b>سطوح دسترسی ادمین</b>\n\n━━━━━━━━━━━━━━━━\n"
        for r in roles:
            target_uid = r['_id']
            u = await db.get_user(target_uid)
            name = u.get('name', '') if u else f"آیدی {target_uid}"
            role_label = db.ROLE_LABELS.get(r.get('role', ''), r.get('role', ''))
            scope = r.get('scope_intake')
            scope_txt = f" ({scope})" if scope else ""
            text += f"\n👤 <b>{name}</b>\n   {role_label}{scope_txt}\n"
            keyboard.append([InlineKeyboardButton(
                f"🗑 حذف نقش {name}", callback_data=f'admin:role_remove:{target_uid}'
            )])
    keyboard.append([InlineKeyboardButton("➕ افزودن نقش جدید", callback_data='admin:role_add_pick')])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:cat_users')])
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_role_type_picker(query):
    """انتخاب نوع نقش قبل از گرفتن آیدی کاربر"""
    keyboard = [
        [InlineKeyboardButton("🎫 پشتیبان (فقط تیکت)", callback_data='admin:role_type:support')],
        [InlineKeyboardButton("🎓 ادمین ارشد محتوا",   callback_data='admin:role_type:content_admin')],
        [InlineKeyboardButton("📅 ادمین محتوای ورودی خاص", callback_data='admin:role_type:content_scoped')],
        [InlineKeyboardButton("📢 مسئول اطلاعیه",        callback_data='admin:role_type:broadcaster')],
        [InlineKeyboardButton("📊 نماینده ورودی (ثبت نمره)", callback_data='admin:role_type:grade_rep')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='admin:roles')],
    ]
    await query.edit_message_text(
        "🛡 <b>افزودن نقش جدید</b>\n\nنوع نقش را انتخاب کنید:",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _show_role_intake_picker(query, role_type: str = 'content_scoped'):
    """برای content_scoped/grade_rep — انتخاب ورودی که این نقش فقط به آن دسترسی دارد"""
    intakes = await db.get_all_intakes()
    if not intakes:
        await query.answer("❌ هنوز هیچ ورودی‌ای تعریف نشده! اول از «مدیریت ورودی‌ها» اضافه کنید.", show_alert=True)
        return
    keyboard = [[InlineKeyboardButton(i['label'], callback_data=f'admin:role_intake:{i["code"]}')] for i in intakes]
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='admin:role_add_pick')])
    label = db.ROLE_LABELS.get(role_type, 'نقش محدود به ورودی')
    await query.edit_message_text(
        f"📅 <b>{label}</b>\n\nاین نقش فقط به کدام ورودی دسترسی داشته باشد؟",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ══════════════════════════════════════════════════
# هندلرهای متن
# ══════════════════════════════════════════════════

# ══════════════════════════════════════════════════
# 📊 توابع نظرسنجی کانال
# ══════════════════════════════════════════════════

async def _poll_main(query, context):
    """صفحه اصلی نظرسنجی — نمایش وضعیت کانال + دکمه ساخت"""
    channel_id = await db.get_setting('poll_channel_id', None)
    if channel_id:
        channel_txt = f"✅ کانال تنظیم شده: <code>{_esc(channel_id)}</code>"
        keyboard = [
            [InlineKeyboardButton("📊 ساخت نظرسنجی جدید", callback_data='admin:poll_create')],
            [InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:cat_comm')],
        ]
    else:
        channel_txt = (
            "⚠️ <b>کانال نظرسنجی تنظیم نشده!</b>\n\n"
            "برای استفاده از این قابلیت:\n"
            "۱. یک کانال تلگرام بساز\n"
            "۲. ربات را admin کانال کن\n"
            "۳. از تنظیمات ربات، کانال را تنظیم کن"
        )
        keyboard = [
            [InlineKeyboardButton("⚙️ رفتن به تنظیمات ربات", callback_data='admin:settings')],
            [InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:cat_comm')],
        ]
    await query.edit_message_text(
        f"📊 <b>نظرسنجی کانال</b>\n━━━━━━━━━━━━━━━━\n\n{channel_txt}",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _poll_preview(query, context):
    """پیش‌نمایش نظرسنجی و انتخاب نوع"""
    poll_data = context.user_data.get('poll_data', {})
    question = poll_data.get('question', '')
    options  = poll_data.get('options', [])

    if not question:
        await query.answer("❌ ابتدا سوال را وارد کنید", show_alert=True)
        return

    opts_txt = '\n'.join(f"  {i+1}. {_esc(o)}" for i, o in enumerate(options)) if options else "  (هنوز گزینه‌ای نیست)"
    can_send = len(options) >= 2

    keyboard = []
    if can_send:
        keyboard.append([
            InlineKeyboardButton("🔓 عمومی (نتایج مرئی)", callback_data='admin:poll_type:regular'),
            InlineKeyboardButton("🔒 ناشناس", callback_data='admin:poll_type:quiz'),
        ])
    keyboard.append([InlineKeyboardButton("➕ افزودن گزینه", callback_data='admin:poll_add_option')])
    keyboard.append([InlineKeyboardButton("❌ لغو", callback_data='admin:poll_cancel')])

    await query.edit_message_text(
        f"📊 <b>پیش‌نمایش نظرسنجی</b>\n━━━━━━━━━━━━━━━━\n\n"
        # 🛡 AUDIT-A6 — سوال/گزینه‌ها متنِ تایپ‌شده‌اند؛ «نمره < ۱۰؟» قبلاً
        # پیش‌نمایش را می‌شکست (BadRequest در edit_message_text ⇒ پنل قفل).
        f"❓ <b>سوال:</b> {_esc(question)}\n\n"
        f"📋 <b>گزینه‌ها:</b>\n{opts_txt}\n\n"
        f"{'✅ آماده ارسال — نوع نظرسنجی را انتخاب کنید:' if can_send else '⚠️ حداقل ۲ گزینه لازم است.'}",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _poll_confirm(query, context):
    """تأیید نهایی قبل از ارسال"""
    poll_data = context.user_data.get('poll_data', {})
    question  = poll_data.get('question', '')
    options   = poll_data.get('options', [])
    ptype     = poll_data.get('type', 'regular')
    channel_id = await db.get_setting('poll_channel_id', None)

    type_label = "🔓 عمومی (رأی‌ها قابل مشاهده)" if ptype == 'regular' else "🔒 ناشناس"
    opts_txt   = '\n'.join(f"  {i+1}. {_esc(o)}" for i, o in enumerate(options))
    ch_txt     = f"<code>{channel_id}</code>" if channel_id else "⚠️ تنظیم نشده"

    await query.edit_message_text(
        f"📊 <b>تأیید ارسال نظرسنجی</b>\n━━━━━━━━━━━━━━━━\n\n"
        f"❓ <b>سوال:</b> {_esc(question)}\n\n"
        f"📋 <b>گزینه‌ها:</b>\n{opts_txt}\n\n"
        f"🔑 <b>نوع:</b> {type_label}\n"
        f"📡 <b>کانال:</b> {ch_txt}\n\n"
        f"آیا مطمئنی؟",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ بله، ارسال کن", callback_data='admin:poll_confirm'),
                InlineKeyboardButton("❌ لغو", callback_data='admin:poll_cancel'),
            ]
        ])
    )


async def _poll_send(query, context):
    """ارسال نهایی poll به کانال"""
    poll_data  = context.user_data.pop('poll_data', {})
    question   = poll_data.get('question', '')
    options    = poll_data.get('options', [])
    ptype      = poll_data.get('type', 'regular')
    channel_id = await db.get_setting('poll_channel_id', None)

    if not channel_id:
        await query.answer("❌ کانال نظرسنجی تنظیم نشده!", show_alert=True)
        await _poll_main(query, context)
        return

    is_anonymous = (ptype == 'quiz')
    try:
        await context.bot.send_poll(
            chat_id=channel_id,
            question=question,
            options=options,
            is_anonymous=is_anonymous,
            allows_multiple_answers=False,
        )
        await query.edit_message_text(
            f"✅ <b>نظرسنجی با موفقیت ارسال شد!</b>\n\n"
            f"❓ {_esc(question)}\n"
            f"📡 کانال: <code>{_esc(channel_id)}</code>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 نظرسنجی جدید", callback_data='admin:poll_create')],
                [InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:cat_comm')],
            ])
        )
    except Exception as e:
        await query.edit_message_text(
            # 🛡 متن خطای تلگرام ممکن است `<` داشته باشد؛ بدون escape خودِ
            # پیامِ خطا هم نمی‌رسید (همان کلاسی که در error_handler دیدیم).
            f"❌ <b>خطا در ارسال نظرسنجی</b>\n\n"
            f"<code>{_esc(str(e)[:300])}</code>\n\n"
            f"مطمئن شو ربات admin کانال است.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data='admin:poll_main')]
            ])
        )


async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    mode = context.user_data.get('mode', '')
    text = update.message.text.strip()

    # ── نظرسنجی: دریافت سوال
    if mode == 'poll_question':
        if len(text) > 300:
            await update.message.reply_text("❌ سوال نباید بیشتر از ۳۰۰ کاراکتر باشد.")
            return True
        context.user_data.setdefault('poll_data', {})['question'] = text
        context.user_data['mode'] = 'poll_option'
        opts = context.user_data['poll_data'].get('options', [])
        await update.message.reply_text(
            f"✅ سوال ثبت شد.\n\n"
            f"❓ <b>{_esc(text)}</b>\n\n"
            f"➕ حالا گزینه اول را بنویس (حداقل ۲ گزینه لازم است، حداکثر ۱۰):",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data='admin:poll_cancel')]])
        )
        return True

    # ── نظرسنجی: دریافت گزینه‌ها
    if mode == 'poll_option':
        poll_data = context.user_data.setdefault('poll_data', {})
        options   = poll_data.setdefault('options', [])
        if len(text) > 100:
            await update.message.reply_text("❌ هر گزینه نباید بیشتر از ۱۰۰ کاراکتر باشد.")
            return True
        if text in options:
            await update.message.reply_text("❌ این گزینه قبلاً اضافه شده.")
            return True
        options.append(text)
        opts_txt = '\n'.join(f"  {i+1}. {_esc(o)}" for i, o in enumerate(options))
        remaining = 10 - len(options)
        keyboard = []
        if len(options) >= 2:
            keyboard.append([InlineKeyboardButton("✅ اتمام و پیش‌نمایش", callback_data='admin:poll_done_options')])
        if remaining > 0:
            keyboard.append([InlineKeyboardButton("➕ گزینه بعدی", callback_data='admin:poll_add_option')])
        keyboard.append([InlineKeyboardButton("❌ لغو", callback_data='admin:poll_cancel')])
        await update.message.reply_text(
            f"✅ گزینه «{_esc(text)}» اضافه شد.\n\n"
            f"📋 گزینه‌های فعلی:\n{opts_txt}\n\n"
            f"{'یک گزینه دیگر بنویس یا اتمام را بزن:' if remaining > 0 else '⚠️ به حداکثر ۱۰ گزینه رسیدی.'}",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return True

    # FIX جدید: متن دلخواه حالت تعمیر و نگهداری
    if mode == 'add_required_channel':
        context.user_data['mode'] = ''
        parts_txt = [p.strip() for p in text.split(',', 1)]
        if len(parts_txt) < 2 or not parts_txt[0].lstrip('-').isdigit():
            await update.message.reply_text(
                "❌ فرمت اشتباه!\nمثال: <code>-1001234567890, نام کانال</code>",
                parse_mode='HTML'
            )
            return True
        ch_id, ch_title = parts_txt[0], parts_txt[1]
        ok = await db.add_required_channel(ch_id, ch_title)
        if ok:
            admin_uid = update.effective_user.id
            admin_user = await db.get_user(admin_uid)
            actor_name = admin_user.get('name', 'مدیر ارشد') if admin_user else 'مدیر ارشد'
            actor_role = await db.get_actor_role_label(admin_uid)
            await send_audit_log(
                context.bot, 'admin', actor_name, admin_uid,
                "افزودن کانال اجباری", module='Settings', severity='HIGH',
                actor_role=actor_role,
                target_id=ch_id, target_type='channel', target_label=ch_title,
                tags=['کانال_اجباری']
            )
            await update.message.reply_text(
                f"✅ کانال <b>{ch_title}</b> اضافه شد.\n\n"
                "⚠️ مطمئن شوید ربات در این کانال ادمین است.",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔒 بازگشت به مدیریت کانال", callback_data='admin:channel_lock')
                ]])
            )
        else:
            await update.message.reply_text("⚠️ این کانال قبلاً اضافه شده.")
        return True

    if mode == 'set_maintenance_text':
        context.user_data['mode'] = ''
        _old_mt = await db.get_setting('maintenance_text', '')
        if text in ('پیشفرض', 'پیش‌فرض', '-'):
            await db.set_setting('maintenance_text', '')
            msg = "✅ متن حالت تعمیر به پیش‌فرض بازگشت."
            _new_mt = ''
        else:
            await db.set_setting('maintenance_text', text)
            msg = "✅ متن حالت تعمیر ذخیره شد."
            _new_mt = text
        try:
            _au = await db.get_user(update.effective_user.id) or {}
            _an = _au.get('name', 'مدیر ارشد')
            _ar = await db.get_actor_role_label(update.effective_user.id)
            await send_audit_log(context.bot, 'admin', _an, update.effective_user.id,
                "تغییر متن حالت تعمیر", module='Settings', severity='HIGH', actor_role=_ar,
                before={'maintenance_text': _old_mt or '(پیش‌فرض)'}, after={'maintenance_text': _new_mt or '(پیش‌فرض)'},
                tags=['حالت_تعمیر'])
        except Exception as _e:
            import logging; logging.getLogger(__name__).warning(f"maintenance_text audit failed: {_e}")
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⚙️ بازگشت به تنظیمات", callback_data='admin:settings')
        ]]))
        return True

    # FIX جدید: تنظیم گروه لاگ — هم آیدی عددی، هم پیام فوروارد‌شده
    if mode in ('set_log_group_admin', 'set_log_group_content'):
        key = 'log_group_admin' if mode == 'set_log_group_admin' else 'log_group_content'
        context.user_data['mode'] = ''
        if text in ('حذف', '-'):
            _old_lg = await db.get_setting(key, None)
            await db.set_setting(key, None)
            try:
                _au = await db.get_user(update.effective_user.id) or {}
                _an = _au.get('name', 'مدیر ارشد')
                _ar = await db.get_actor_role_label(update.effective_user.id)
                await send_audit_log(context.bot, 'admin', _an, update.effective_user.id,
                    f"حذف گروه لاگ {key}", module='Settings', severity='HIGH', actor_role=_ar,
                    before={'group': str(_old_lg) if _old_lg else 'تنظیم نشده'}, after={'group': 'حذف شد'},
                    target_id=key, target_type='settings',
                    tags=['گروه_لاگ'])
            except Exception as _e:
                import logging; logging.getLogger(__name__).warning(f"del log group audit failed: {_e}")
            await update.message.reply_text(
                "✅ تنظیم گروه حذف شد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ بازگشت به تنظیمات", callback_data='admin:settings')]])
            )
            return True
        chat_id = None
        # حالت ۱: پیام فوروارد‌شده از طرف خودِ گروه (پیام anonymous گروه)
        fwd = update.message.forward_origin
        if fwd is not None and hasattr(fwd, 'sender_chat') and fwd.sender_chat is not None:
            chat_id = fwd.sender_chat.id
        # حالت ۲ (قابل‌اعتمادترین روش): آیدی عددی منفی مستقیم گروه
        # — با فوروارد یک پیام به @RawDataBot یا @userinfobot پیدا می‌شود
        elif text.lstrip('-').isdigit():
            chat_id = int(text)
            # FIX: آیدی گروه/سوپرگروه/کانال همیشه منفی است؛ آیدی مثبت
            # مال یک کاربر است و ذخیره‌اش فقط باعث می‌شد همه‌ی لاگ‌ها
            # بعداً بی‌صدا در ارسال شکست بخورند
            if chat_id >= 0:
                await update.message.reply_text(
                    "⚠️ آیدی گروه باید <b>عدد منفی</b> باشد (مثل "
                    "<code>-1001234567890</code>) — عدد مثبت آیدی یک کاربر است، نه گروه.\n\n"
                    "💡 یک پیام از گروه را به @RawDataBot فوروارد کنید و مقدار "
                    "<code>chat.id</code> را اینجا بفرستید.",
                    parse_mode='HTML'
                )
                return True
        if not chat_id:
            await update.message.reply_text(
                "⚠️ آیدی عددی گروه (با علامت منفی، مثلاً <code>-1001234567890</code>) را بفرستید.\n\n"
                "💡 برای پیدا کردن آیدی گروه: یک پیام از آن گروه را به @RawDataBot فوروارد کنید "
                "و مقدار <code>chat.id</code> را از پاسخ آن کپی کنید.",
                parse_mode='HTML'
            )
            return True
        _old_lg2 = await db.get_setting(key, None)
        await db.set_setting(key, chat_id)
        try:
            _au = await db.get_user(update.effective_user.id) or {}
            _an = _au.get('name', 'مدیر ارشد')
            _ar = await db.get_actor_role_label(update.effective_user.id)
            await send_audit_log(context.bot, 'admin', _an, update.effective_user.id,
                f"تنظیم گروه لاگ {key}", module='Settings', severity='HIGH', actor_role=_ar,
                before={'group': str(_old_lg2) if _old_lg2 else 'تنظیم نشده'}, after={'group': str(chat_id)},
                target_id=key, target_type='settings',
                tags=['گروه_لاگ'])
        except Exception as _e:
            import logging; logging.getLogger(__name__).warning(f"set log group audit failed: {_e}")
        try:
            await context.bot.send_message(chat_id, "✅ این گروه به‌عنوان گروه لاگ ربات تنظیم شد.")
        except Exception:
            await update.message.reply_text(
                "⚠️ گروه ذخیره شد، اما ربات نتوانست پیام تستی بفرستد — مطمئن شوید ربات عضو آن گروه است."
            )
        await update.message.reply_text(
            f"✅ آیدی گروه <code>{chat_id}</code> ذخیره شد.", parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ بازگشت به تنظیمات", callback_data='admin:settings')]])
        )
        return True

    # تنظیم کانال نظرسنجی / اطلاع‌رسانی
    if mode == 'set_poll_channel':
        context.user_data['mode'] = ''
        if text in ('حذف', '-'):
            _old_pc = await db.get_setting('poll_channel_id', None)
            await db.set_setting('poll_channel_id', None)
            try:
                _au2 = await db.get_user(update.effective_user.id) or {}
                _an2 = _au2.get('name','مدیر ارشد')
                _ar2 = await db.get_actor_role_label(update.effective_user.id)
                await send_audit_log(context.bot,'admin',_an2,update.effective_user.id,"حذف کانال نظرسنجی",module='Settings',severity='WARNING',actor_role=_ar2,before={'poll_channel_id': str(_old_pc) if _old_pc else 'تنظیم نشده'},after={'poll_channel_id': 'حذف شد'},tags=['کانال','نظرسنجی'])
            except Exception as _e: import logging; logging.getLogger(__name__).warning(f"poll_channel delete audit failed: {_e}")
            await update.message.reply_text(
                "✅ کانال نظرسنجی حذف شد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ بازگشت به تنظیمات", callback_data='admin:settings')]])
            )
            return True
        # پشتیبانی از فوروارد پیام کانال
        channel_id = None
        fwd = update.message.forward_origin
        if fwd is not None and hasattr(fwd, 'sender_chat') and fwd.sender_chat is not None:
            channel_id = fwd.sender_chat.id
        elif text.lstrip('-').isdigit():
            channel_id = int(text)
        if not channel_id:
            await update.message.reply_text(
                "⚠️ آیدی کانال (با <code>-100</code>، مثلاً <code>-1001234567890</code>) را بفرستید.\n\n"
                "💡 یک پیام از کانال را به @RawDataBot فوروارد کنید تا آیدی را پیدا کنید.",
                parse_mode='HTML'
            )
            return True
        _old_pc2 = await db.get_setting('poll_channel_id', None)
        await db.set_setting('poll_channel_id', channel_id)
        try:
            _au3 = await db.get_user(update.effective_user.id) or {}
            _an3 = _au3.get('name','مدیر ارشد')
            _ar3 = await db.get_actor_role_label(update.effective_user.id)
            await send_audit_log(context.bot,'admin',_an3,update.effective_user.id,"تنظیم کانال نظرسنجی",module='Settings',severity='WARNING',actor_role=_ar3,before={'poll_channel_id': str(_old_pc2) if _old_pc2 else 'تنظیم نشده'},after={'poll_channel_id': str(channel_id)},tags=['کانال','نظرسنجی'])
        except Exception as _e: import logging; logging.getLogger(__name__).warning(f"poll_channel set audit failed: {_e}")
        try:
            await context.bot.send_message(channel_id, "✅ این کانال به‌عنوان کانال نظرسنجی / اطلاع‌رسانی ربات تنظیم شد.")
        except Exception:
            await update.message.reply_text(
                "⚠️ کانال ذخیره شد، اما ربات نتوانست پیام تستی بفرستد — مطمئن شوید ربات admin کانال است."
            )
        await update.message.reply_text(
            f"✅ کانال نظرسنجی با آیدی <code>{_esc(channel_id)}</code> ذخیره شد.", parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ بازگشت به تنظیمات", callback_data='admin:settings')]])
        )
        return True

    # تنظیم لینک حمایت مالی
    if mode == 'set_donation_link':
        context.user_data['mode'] = ''
        admin_uid = update.effective_user.id
        if text in ('حذف', '-'):
            old_link = await db.get_setting('donation_link', None)
            await db.set_setting('donation_link', None)
            # FIX لاگ: حذف لینک از طریق پیام متنی هم ثبت شود (پارتی با وب‌پنل)
            admin_user = await db.get_user(admin_uid)
            actor_name = admin_user.get('name', 'مدیر ارشد') if admin_user else 'مدیر ارشد'
            actor_role = await db.get_actor_role_label(admin_uid)
            await send_audit_log(
                context.bot, 'admin', actor_name, admin_uid,
                "حذف لینک حمایت مالی", module='Settings', severity='HIGH',
                actor_role=actor_role,
                before={'لینک': old_link or 'تنظیم نشده'}, after={'لینک': 'حذف شد'},
                tags=['حمایت_مالی']
            )
            await update.message.reply_text(
                "✅ لینک حمایت مالی حذف شد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💙 بازگشت به مدیریت حمایت مالی", callback_data='admin:donation_manage')]])
            )
            return True
        if not (text.startswith('http://') or text.startswith('https://')):
            context.user_data['mode'] = 'set_donation_link'
            await update.message.reply_text(
                "⚠️ لینک باید با <code>http://</code> یا <code>https://</code> شروع شود. دوباره ارسال کنید.",
                parse_mode='HTML'
            )
            return True
        old_link = await db.get_setting('donation_link', None)
        await db.set_setting('donation_link', text)
        # FIX لاگ: تنظیم/تغییر لینک هم مثل تاگل باید ثبت شود (پارتی با وب‌پنل)
        admin_user = await db.get_user(admin_uid)
        actor_name = admin_user.get('name', 'مدیر ارشد') if admin_user else 'مدیر ارشد'
        actor_role = await db.get_actor_role_label(admin_uid)
        await send_audit_log(
            context.bot, 'admin', actor_name, admin_uid,
            "تنظیم لینک حمایت مالی", module='Settings', severity='HIGH',
            actor_role=actor_role,
            before={'لینک': old_link or 'تنظیم نشده'}, after={'لینک': text},
            tags=['حمایت_مالی']
        )
        await update.message.reply_text(
            f"✅ لینک حمایت مالی ذخیره شد:\n<code>{_esc(text)}</code>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💙 بازگشت به مدیریت حمایت مالی", callback_data='admin:donation_manage')]])
        )
        return True

    # FIX جدید: گام نهایی افزودن نقش فرعی ادمین — گرفتن آیدی عددی
    if mode == 'add_admin_role':
        if not text.isdigit():
            await update.message.reply_text(
                "⚠️ آیدی باید فقط عدد باشد. دوباره وارد کنید یا /cancel بزنید."
            )
            return True
        target_uid   = int(text)
        role_type    = context.user_data.pop('new_role_type', '')
        scope_intake = context.user_data.pop('new_role_intake', None)
        context.user_data['mode'] = ''
        # 🛡 C3.1 — نقش‌های ورودی‌محور بدون ورودی معنا ندارند؛ وگرنه حسابی
        # «scoped بدون scope» ساخته می‌شد (و پیش از این موج، چنان حسابی روی
        # هسته‌ی 🌐 سراسری write داشت). source: §۱۴.۱ گزارش
        if role_type in ('content_scoped', 'grade_rep') and not (scope_intake or '').strip():
            await update.message.reply_text(
                "❌ این نقش حتماً باید به یک ورودی محدود شود.\n"
                "اول از «مدیریت ورودی‌ها» ورودی بسازید، سپس دوباره اقدام کنید.")
            return True
        admin_uid = update.effective_user.id
        ok = await db.add_admin_role(target_uid, role_type, admin_uid, scope_intake)
        if not ok:
            await update.message.reply_text("❌ نوع نقش نامعتبر است.")
            return True
        role_label = db.ROLE_LABELS.get(role_type, role_type)
        scope_txt  = f" — محدود به ورودی {scope_intake}" if scope_intake else ""
        admin_user = await db.get_user(admin_uid)
        actor_name = admin_user.get('name', 'مدیر ارشد') if admin_user else 'مدیر ارشد'
        actor_role = await db.get_actor_role_label(admin_uid)
        target_user_for_log = await db.get_user(target_uid)
        await send_audit_log(
            context.bot, 'admin', actor_name, admin_uid,
            "انتساب رول به کاربر", module='Roles', severity='CRITICAL',
            actor_role=actor_role,
            target_id=str(target_uid), target_type='user',
            target_label=target_user_for_log.get('name', '') if target_user_for_log else '',
            details=f"نقش: {role_label}{scope_txt}",
            tags=['انتساب_نقش']
        )
        try:
            await context.bot.send_message(
                target_uid,
                f"🛡 <b>دسترسی جدید به شما داده شد!</b>\n\nنقش: {role_label}{scope_txt}\n\n"
                "از دکمه «👨‍⚕️ پنل ادمین» در منوی اصلی استفاده کنید.",
                parse_mode='HTML'
            )
        except Exception:
            pass
        await update.message.reply_text(
            f"✅ نقش <b>{role_label}</b>{scope_txt} برای آیدی <code>{target_uid}</code> ثبت شد.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🛡 بازگشت به سطوح دسترسی", callback_data='admin:roles')
            ]])
        )
        return True

    if mode == 'search_user':
        users = await db.search_users(text)
        context.user_data['mode'] = ''
        if not users:
            await update.message.reply_text(f"❌ کاربری با «{text}» پیدا نشد.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔍 جستجوی مجدد", callback_data='admin:search_user'),
                    InlineKeyboardButton("🔙 پنل ادمین", callback_data='admin:cat_users'),
                ]]))
            return True
        keyboard = [[InlineKeyboardButton(
            f"{'✅' if u.get('approved') else '⏳'} {u.get('name','')} | {u.get('student_id','') or u.get('username','N/A')}",
            callback_data=f'admin:user_detail:{u["user_id"]}')] for u in users]
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='admin:cat_users')])
        await update.message.reply_text(f"🔍 <b>{len(users)} نتیجه برای «{text}»:</b>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        return True

    elif mode == 'edit_user':
        info  = context.user_data.get('edit_user', {})
        uid   = info.get('uid')
        field = info.get('field')
        label = info.get('label', '')
        if uid and field:
            _eu_before = await db.get_user(uid) or {}
            _eu_old = _eu_before.get(field, '')
            await db.update_user(uid, {field: text})
            try:
                _au = await db.get_user(update.effective_user.id) or {}
                _an = _au.get('name', 'مدیر ارشد')
                _ar = await db.get_actor_role_label(update.effective_user.id)
                await send_audit_log(context.bot, 'admin', _an, update.effective_user.id,
                    f"ویرایش کاربر {field}", module='Users', severity='WARNING', actor_role=_ar,
                    target_id=str(uid), target_type='user', target_label=_eu_before.get('name',''),
                    before={field: _eu_old}, after={field: text},
                    tags=['ویرایش_کاربر'])
            except Exception as _e:
                import logging; logging.getLogger(__name__).warning(f"edit_user audit failed: {_e}")
            context.user_data['mode'] = ''
            await update.message.reply_text(f"✅ {label} ویرایش شد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👤 مشاهده کاربر", callback_data=f'admin:user_detail:{uid}')]]))
            return True

    elif mode == 'add_intake':
        try:
            pts = [p.strip() for p in text.split(',', 1)]
            if len(pts) < 2:
                raise ValueError("فرمت اشتباه")
            code, label = pts[0], pts[1]
            ok = await db.add_intake(code, label)
            if ok:
                try:
                    _au = await db.get_user(update.effective_user.id) or {}
                    _an = _au.get('name', 'مدیر ارشد')
                    _ar = await db.get_actor_role_label(update.effective_user.id)
                    await send_audit_log(context.bot, 'admin', _an, update.effective_user.id,
                        "افزودن ورودی جدید", module='Users', severity='INFO', actor_role=_ar,
                        target_id=code, target_type='intake', target_label=label,
                        tags=['ورودی'])
                except Exception as _e:
                    import logging; logging.getLogger(__name__).warning(f"add_intake audit failed: {_e}")
            context.user_data.pop('mode', None)
            if ok:
                await update.message.reply_text(f"✅ ورودی <b>{label}</b> اضافه شد!", parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📅 مدیریت ورودی‌ها", callback_data='admin:intakes')]]))
            else:
                await update.message.reply_text(f"⚠️ ورودی با کد <code>{code}</code> قبلاً وجود دارد.", parse_mode='HTML')
            return True
        except ValueError:
            await update.message.reply_text("❌ فرمت اشتباه!\nمثال: <code>bahman_1404, بهمن ۱۴۰۴</code>", parse_mode='HTML')
            return True

    # ── ✉️ موج ۴.۸۰: دریافت متن «پیام مستقیم به کاربر»
    # نام و آیدی گیرنده قبل از پاک‌کردن state نگه داشته می‌شوند تا
    # حتی با خطای ورودی هم کارت کاربر قابلِ بازگشت باشد.
    if mode == 'admin_dm':
        target      = context.user_data.get('dm_target', 0)
        target_name = context.user_data.get('dm_target_name', '')
        admin_name  = update.effective_user.full_name or 'ادمین'

        if not target:
            context.user_data['mode'] = ''
            await update.message.reply_text(
                "❌ گیرنده مشخص نیست — دوباره از کارت کاربر شروع کنید."
            )
            return True

        def _restore_dm():
            context.user_data['mode']           = 'admin_dm'
            context.user_data['dm_target']      = target
            context.user_data['dm_target_name'] = target_name

        if len(text) < 2:
            _restore_dm()
            await update.message.reply_text(
                "⚠️ پیام خیلی کوتاه است (حداقل ۲ کاراکتر). دوباره بنویسید:"
            )
            return True
        if len(text) > 3500:
            _restore_dm()
            await update.message.reply_text(
                "⚠️ پیام خیلی بلند است (حداکثر ۳۵۰۰ کاراکتر). کوتاه‌تر بنویسید:"
            )
            return True

        context.user_data.pop('mode', None)
        context.user_data.pop('dm_target', None)
        context.user_data.pop('dm_target_name', None)

        # بدنه‌ی پیام ادمین escape می‌شود: نه HTML تزریقی کار می‌کند،
        # نه کاراکترهایی مثل «<» ارسال را می‌شکنند.  🛡 AUDIT-A6
        body = (
            "📩 <b>پیام از مدیریت هامزیار</b>\n"
            "━━━━━━━━━━━━━━━━\n\n"
            f"{_esc(text)}"
        )
        back_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("👤 بازگشت به کارت کاربر",
                                 callback_data=f'admin:user_detail:{target}')
        ]])
        # 🔔 موج ۴.۹۰ — اینباکس مینی‌اپ (پیام مستقیم مدیریت)
        await db.inbox_add(target, 'admin_dm',
            "📩 پیام از مدیریت هامزیار",
            text[:400], link=None)
        try:
            await context.bot.send_message(target, body, parse_mode='HTML')
        except Exception as e:
            logger.warning(f"DM to user {target} failed: {e}")
            await update.message.reply_text(
                f"⚠️ <b>پیام به {target_name or 'کاربر'} در تلگرام نرسید.</b>\n"
                "احتمالاً کاربر ربات را بلاک کرده یا هنوز /start نزده است.\n"
                "<i>با این حال، پیام در «مرکز اعلان مینی‌اپ» کاربر ثبت شد و آنجا می‌تواند بخواندش.</i>",
                parse_mode='HTML',
                reply_markup=back_kb
            )
            return True

        from utils import send_audit_log
        await send_audit_log(
            context.bot, 'admin', admin_name, update.effective_user.id,
            "ارسال پیام مستقیم به کاربر", module='Users', severity='INFO',
            actor_role='ادمین ارشد', target_type='user',
            target_label=target_name, details=text[:100],
            tags=['پیام_مستقیم']
        )
        await update.message.reply_text(
            f"✅ <b>پیام برای {target_name or 'کاربر'} ارسال شد.</b>\n\n"
            f"📩 <i>{_esc(text[:180])}</i>",
            parse_mode='HTML',
            reply_markup=back_kb
        )
        return True

    return False
