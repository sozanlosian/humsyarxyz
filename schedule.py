"""
📅 برنامه کلاس‌ها و امتحانات
  ✅ تاریخ شمسی ورودی و نمایش
  ✅ فیکس باگ کاما فارسی (٫ → ,)
  ✅ فیلتر گروه
  ✅ اضافه/حذف توسط ادمین
"""
import os
import io
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import ContextTypes
from database import db
from bson import ObjectId
from utils import (fmt_jalali, days_until, exam_countdown, ADMIN_ID,
                    jalali_weekday_index, JALALI_WEEK_SAT_FIRST, send_audit_log)
from time_utils import (
    TimeContractError, format_time_fa, now_tehran, parse_clock_time,
    parse_gregorian_date,
    start_of_week_tehran,
)

logger = logging.getLogger(__name__)

TYPE_NAMES  = {'class': '📖 کلاس', 'exam': '📝 امتحان', 'makeup': '🔄 جبرانی'}
GROUP_ICONS = {'1': '1️⃣', '2': '2️⃣', 'هر دو': '👥', '': '👥'}


def _fa_time(value) -> str:
    return format_time_fa(value, fallback=str(value or '—'))

def _fa_interval(start, end=None) -> str:
    if start and end:
        try:
            # normalize via en_digits if needed
            from time_utils import en_digits as _en
            s = _en(str(start)).strip()
            e = _en(str(end)).strip()
            # fix 01-05 -> 13-17 for display (PM)
            def _fix(v):
                try:
                    hh, mm = v.split(':')
                    h = int(hh)
                    if 1 <= h <= 5:
                        return f"{h+12:02d}:{mm}"
                    return v
                except: return v
            s = _fix(s); e = _fix(e)
            return f"{_fa_time(s)} تا {_fa_time(e)}"
        except: 
            return f"{_fa_time(start)} تا {_fa_time(end)}"
    return _fa_time(start)

def _doc_time_display(doc: dict) -> str:
    if not doc: return _fa_time('')
    return _fa_interval(doc.get('time'), doc.get('end_time') or doc.get('time_end'))

def _parse_interval(raw: str):
    """Parse '08:00-10:00' / '08:00 تا 10:00' / '8-10' / '08:00' -> (start, end|None) or (None,None)"""
    if not raw: return None, None
    from time_utils import en_digits as _en
    import re
    tmp = _en(str(raw)).replace('—','-').replace('–','-').replace('تا','-')
    times = re.findall(r'(\d{1,2}:\d{2})', tmp)
    if len(times) >= 2:
        s = f"{int(times[0].split(':')[0]):02d}:{times[0].split(':')[1]}"
        e = f"{int(times[1].split(':')[0]):02d}:{times[1].split(':')[1]}"
        return s, e
    if len(times) == 1:
        hh, mm = times[0].split(':')
        s = f"{int(hh):02d}:{mm}"
        # check if dash with hour only second part like "08:00-10"
        if '-' in tmp:
            # try to find second hour without minutes
            after = tmp.split('-',1)[1]
            m2 = re.search(r'(\d{1,2})', after)
            if m2:
                # if times only one colon, the dash part might be "10" -> assume ":00"
                if ':' not in after:
                    e = f"{int(m2.group(1)):02d}:00"
                    return s, e
        return s, None
    # handle "8-10" without colon
    if '-' in tmp:
        parts = tmp.split('-')
        if len(parts)==2:
            m1 = re.search(r'(\d{1,2})', parts[0])
            m2 = re.search(r'(\d{1,2})', parts[1])
            if m1 and m2:
                s = f"{int(m1.group(1)):02d}:00"
                e = f"{int(m2.group(1)):02d}:00"
                return s, e
    return None, None



async def _can_manage_schedule(uid: int) -> bool:
    """گیت مشترک mutationهای schedule در Bot و Web Admin."""
    if uid == ADMIN_ID:
        return True
    try:
        return await db.has_permission(uid, 'schedules.manage')
    except Exception:
        logger.exception("schedule permission check failed for %s", uid)
        return False


async def _notify_schedule_deleted(context, item: dict):
    """
    FIX جدید: تکمیل چرخه‌ی نوتیف برنامه — تا امروز فقط «اضافه‌شدن» و
    «ویرایش» به دانشجوها اطلاع داده می‌شد، ولی «حذف‌شدن» (مثلاً لغو یک
    امتحان یا کلاس جبرانی) هیچ نوتیفی نداشت؛ فقط در لاگ ادمین ثبت
    می‌شد. این تابع دقیقاً از همان الگوی notif_users/broadcast_message
    که در _finalize_schedule_add جواب می‌دهد استفاده می‌کند تا رفتار و
    ظاهر پیام با بقیه‌ی نوتیف‌های برنامه یکدست بماند.
    """
    from utils import broadcast_message
    stype   = item.get('type', 'class')
    ntype   = {'exam': 'exam', 'makeup': 'makeup'}.get(stype, 'schedule')
    users   = await db.notif_users(ntype, group=item.get('group'))
    if not users:
        return
    type_fa = TYPE_NAMES.get(stype, stype)
    g_label = f" | گروه {item.get('group')}" if item.get('group') not in ('هر دو', '', None) else ''
    jalali_display = fmt_jalali(item.get('date', ''))
    notif_msg = (
        f"❌ <b>{type_fa} لغو شد</b>\n\n"
        f"📚 {item.get('lesson','')}\n"
        f"👨‍🏫 {item.get('teacher','')}\n"
        f"📅 {jalali_display}  ⏰ {_doc_time_display(item)}\n"
        f"📍 {item.get('location','')}{g_label}"
    )
    await broadcast_message(context.bot, users, notif_msg)


def _days_label(days: int) -> str:
    if days < 0:  return f"({abs(days)} روز پیش)"
    if days == 0: return "⚠️ امروز!"
    if days == 1: return "⏰ فردا!"
    if days <= 3: return f"🔴 {days} روز دیگر"
    if days <= 7: return f"🟠 {days} روز دیگر"
    return f"🟢 {days} روز دیگر"


def _normalize_text(text: str) -> str:
    """
    FIX: نرمال‌سازی متن ورودی
    - کاما فارسی ٫ → کاما انگلیسی ,
    - ویرگول فارسی ، → کاما انگلیسی ,
    - فاصله‌های اضافه حذف
    """
    text = text.replace('٫', ',').replace('،', ',')
    # حذف فاصله‌های اضافه اطراف کاما
    import re
    text = re.sub(r'\s*,\s*', ', ', text)
    return text.strip()


def _jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple:
    """Compatibility wrapper; calendar conversion lives in time_utils."""
    from time_utils import jalali_to_gregorian
    converted = jalali_to_gregorian(jy, jm, jd)
    return converted.year, converted.month, converted.day


def _parse_jalali_date(date_str: str) -> str:
    """Parse Persian input to a Gregorian date-only machine value."""
    from time_utils import en_digits, parse_gregorian_date, parse_jalali_date
    raw = ''.join(c for c in en_digits(date_str or '') if c.isprintable()).strip()
    normalized = raw.replace('/', '-').replace('\\', '-')
    try:
        year = int(normalized.split('-', 1)[0])
        if 1200 <= year <= 1600:
            return parse_jalali_date(normalized).isoformat()
        return parse_gregorian_date(normalized).isoformat()
    except (ValueError, TypeError):
        return raw


def _is_valid_time(time_str: str) -> bool:
    """بررسی مرکزی فرمت ساعت HH:MM."""
    try:
        parse_clock_time(time_str)
        return True
    except TimeContractError:
        return False


def _is_date_string(s: str) -> bool:
    """تشخیص اینکه آیا رشته تاریخ است یا نه"""
    s = s.strip().replace('/', '-')
    parts_d = s.split('-')
    if len(parts_d) != 3:
        return False
    try:
        y = int(parts_d[0])
        return y > 1000  # شمسی یا میلادی
    except Exception:
        return False


# ══════════════════════════════════════════════════
#  Callback اصلی
# ══════════════════════════════════════════════════

async def schedule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    uid    = update.effective_user.id
    can_manage = await _can_manage_schedule(uid)
    parts  = query.data.split(':')
    action = parts[1] if len(parts) > 1 else 'main'

    user       = await db.get_user(uid)
    user_group = user.get('group', '') if user else ''

    if action == 'main':
        await _schedule_main(query, user_group)

    elif action == 'group_view':
        group_filter = parts[2] if len(parts) > 2 and parts[2] else user_group
        await _show_group_schedule(query, group_filter)

    elif action == 'export_pdf':
        await _export_schedule_pdf(query, context, user, user_group)

    elif action == 'export_pdf_type':
        stype        = parts[2] if len(parts) > 2 else 'all'
        group_filter = parts[3] if len(parts) > 3 and parts[3] else None
        await _export_schedule_pdf(query, context, user, group_filter or user_group,
                                    stype=None if stype == 'all' else stype)

    # ══════════════════════════════════════════════
    # FIX جدید: فلوی پیش‌نمایش قبل از ثبت برنامه
    # ══════════════════════════════════════════════
    elif action == 'flex' and can_manage:
        flex_type = parts[2] if len(parts) > 2 else 'fixed'
        p = context.user_data.get('pending_schedule', {})
        if not p:
            await query.edit_message_text("❌ اطلاعاتی برای پیش‌نمایش پیدا نشد.")
            return
        p['flex_type'] = flex_type
        context.user_data['pending_schedule'] = p
        await _show_schedule_preview(query, context, edit=True)

    elif action == 'confirm_add' and can_manage:
        await _finalize_schedule_add(query, context)

    elif action == 'edit_pending' and can_manage:
        p = context.user_data.get('pending_schedule', {})
        stype = p.get('stype', 'class')
        edit_sid = p.get('edit_sid')
        context.user_data.pop('pending_schedule', None)
        context.user_data['schedule_type'] = stype
        context.user_data['mode'] = 'add_schedule'
        if edit_sid:
            context.user_data['schedule_edit_sid'] = edit_sid
        type_fa = TYPE_NAMES.get(stype, stype)
        cancel_cb = f'schedule:item:{edit_sid}' if edit_sid else 'admin:main'
        await query.edit_message_text(
            f"✏️ <b>ویرایش {type_fa}</b>\n\n"
            "اطلاعات را دوباره با فرمت زیر بفرستید:\n"
            "<code>درس, استاد, 1404/MM/DD, HH:MM, مکان, گروه, توضیح</code>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ لغو", callback_data=cancel_cb)
            ]])
        )

    elif action == 'cancel_pending' and can_manage:
        p = context.user_data.get('pending_schedule', {})
        edit_sid = p.get('edit_sid')
        context.user_data.pop('pending_schedule', None)
        context.user_data.pop('mode', None)
        context.user_data.pop('schedule_edit_sid', None)
        back_cb = f'schedule:item:{edit_sid}' if edit_sid else 'admin:main'
        back_label = "🔙 بازگشت به برنامه" if edit_sid else "🔙 پنل ادمین"
        await query.edit_message_text(
            "❌ لغو شد. هیچ تغییری ثبت نشد." if edit_sid else "❌ لغو شد. هیچ موردی ثبت نشد.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(back_label, callback_data=back_cb)
            ]])
        )

    elif action == 'type':
        stype        = parts[2] if len(parts) > 2 else 'class'
        group_filter = parts[3] if len(parts) > 3 else user_group
        # FIX سازگاری به‌عقب: اگه کسی هنوز callback قدیمی type:class داشت
        # (مثلاً از پیام‌های قدیمی)، به همان صفحه یکپارچه هدایت شود
        if stype == 'class':
            await _show_group_schedule(query, group_filter)
            return
        items        = await db.get_schedules(stype=stype, group=group_filter or None)
        title        = TYPE_NAMES.get(stype, stype)
        if group_filter:
            title += f" — گروه {group_filter}"
        await _show_schedule_list(query, items, title, stype=stype, group_filter=group_filter)

    elif action == 'upcoming':
        items    = await db.upcoming_exams(14)
        filtered = [
            i for i in items
            if i.get('group', 'هر دو') in ('هر دو', user_group, '')
        ]
        await _show_schedule_list(query, filtered, "⏳ امتحانات ۱۴ روز آینده")

    elif action == 'group_sel':
        stype = parts[2] if len(parts) > 2 else 'class'
        keyboard = [
            [InlineKeyboardButton("1️⃣ گروه ۱",     callback_data=f'schedule:type:{stype}:1')],
            [InlineKeyboardButton("2️⃣ گروه ۲",     callback_data=f'schedule:type:{stype}:2')],
            [InlineKeyboardButton("👥 هر دو گروه", callback_data=f'schedule:type:{stype}:')],
            [InlineKeyboardButton("🔙 بازگشت",     callback_data='schedule:main')],
        ]
        await query.edit_message_text(
            "👥 کدام گروه را نمایش دهم?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif action == 'add_type' and can_manage:
        keyboard = [
            [InlineKeyboardButton("📖 کلاس",   callback_data='schedule:add_start:class')],
            [InlineKeyboardButton("📝 امتحان", callback_data='schedule:add_start:exam')],
            [InlineKeyboardButton("🔄 جبرانی", callback_data='schedule:add_start:makeup')],
            [InlineKeyboardButton("🔙 بازگشت", callback_data='admin:cat_schedule')],
        ]
        await query.edit_message_text(
            "📅 <b>افزودن برنامه</b>\n\nنوع را انتخاب کنید:",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif action == 'add_start' and can_manage:
        stype = parts[2] if len(parts) > 2 else 'class'
        context.user_data['schedule_type'] = stype
        context.user_data['mode']          = 'add_schedule'
        type_fa = TYPE_NAMES.get(stype, stype)
        await query.edit_message_text(
            f"📅 <b>افزودن {type_fa}</b>\n\n"
            "فرمت ورودی:\n"
            "<code>درس, استاد, تاریخ شمسی, ساعت, مکان, گروه, توضیح</code>\n\n"
            "📌 مثال:\n"
            "<code>آناتومی, دکتر محمدی, 1404/01/15, 09:00, کلاس A2, هر دو</code>\n\n"
            "⚠️ نکات:\n"
            "• تاریخ باید شمسی باشد: <code>1404/01/15</code>\n"
            "• ساعت: <code>09:00</code> یا <code>14:30</code>\n"
            "• گروه: <code>۱</code> یا <code>۲</code> یا <code>هر دو</code> (اختیاری)\n"
            "• از کاما انگلیسی <code>,</code> استفاده کنید",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ لغو", callback_data='admin:cat_schedule')
            ]])
        )

    elif action == 'del_list' and can_manage:
        await _show_delete_list(query)

    elif action == 'del' and can_manage:
        sid = parts[2]
        # FIX جدید: گرفتن اطلاعات قبل از حذف برای ثبت در لاگ
        deleted_item = await db.schedules.find_one({'_id': ObjectId(sid)})
        await db.delete_schedule(sid)
        await query.answer("🗑 برنامه حذف شد!", show_alert=True)
        if deleted_item:
            admin_user = await db.get_user(uid)
            actor_name = admin_user.get('name', 'ادمین') if admin_user else 'ادمین'
            actor_role = await db.get_actor_role_label(uid)
            type_fa = TYPE_NAMES.get(deleted_item.get('type',''), '')
            await send_audit_log(
                context.bot, 'admin', actor_name, uid,
                f"حذف {type_fa}", module='Schedules', severity='HIGH',
                actor_role=actor_role,
                target_id=sid, target_type='schedule',
                target_label=f"{deleted_item.get('lesson','')} — {fmt_jalali(deleted_item.get('date',''))}",
                tags=['حذف_برنامه']
            )
            # FIX جدید: اطلاع‌رسانی حذف به دانشجوهای همون گروه
            await _notify_schedule_deleted(context, deleted_item)
        await _show_delete_list(query)

    # ══════════════════════════════════════════════
    # FIX جدید: اعلام تغییر زمان برای کلاس منعطف
    # ══════════════════════════════════════════════
    elif action == 'flex_list' and can_manage:
        await _show_flex_list(query)

    # ══════════════════════════════════════════════
    # بخش اول: قابلیت ویرایش برنامه‌ها
    # ══════════════════════════════════════════════
    elif action == 'manage_types' and can_manage:
        await _show_manage_types(query)

    elif action == 'manage_list' and can_manage:
        stype = parts[2] if len(parts) > 2 else 'class'
        await _show_manage_list(query, stype)

    elif action == 'item' and can_manage:
        sid = parts[2]
        await _show_item_detail(query, sid)

    elif action == 'edit_menu' and can_manage:
        sid = parts[2]
        await _show_edit_menu(query, sid)

    elif action == 'edit_field' and can_manage:
        sid   = parts[2]
        field = parts[3] if len(parts) > 3 else ''
        await _start_field_edit(query, context, sid, field)

    elif action == 'edit_full' and can_manage:
        sid = parts[2]
        item = await db.get_schedule_by_id(sid)
        if not item:
            await query.edit_message_text("❌ این برنامه پیدا نشد.")
            return
        context.user_data['schedule_type']    = item.get('type', 'class')
        context.user_data['schedule_edit_sid'] = sid
        context.user_data['mode']             = 'add_schedule'
        type_fa = TYPE_NAMES.get(item.get('type', 'class'), '')
        await query.edit_message_text(
            f"✏️ <b>ویرایش کامل {type_fa}</b>\n\n"
            "اطلاعات جدید را با فرمت زیر بفرستید (کل اطلاعات جایگزین می‌شود):\n"
            "<code>درس, استاد, 1404/MM/DD, HH:MM, مکان, گروه, توضیح</code>\n\n"
            "📌 مثال:\n"
            "<code>آناتومی, دکتر محمدی, 1404/01/15, 09:00, کلاس A2, هر دو</code>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ لغو", callback_data=f'schedule:item:{sid}')
            ]])
        )

    elif action == 'del_item' and can_manage:
        sid = parts[2]
        item = await db.schedules.find_one({'_id': ObjectId(sid)})
        stype = item.get('type', 'class') if item else 'class'
        await db.delete_schedule(sid)
        await query.answer("🗑 برنامه حذف شد!", show_alert=True)
        if item:
            admin_user = await db.get_user(uid)
            actor_name = admin_user.get('name', 'ادمین') if admin_user else 'ادمین'
            actor_role = await db.get_actor_role_label(uid)
            type_fa = TYPE_NAMES.get(item.get('type', ''), '')
            await send_audit_log(
                context.bot, 'admin', actor_name, uid,
                f"حذف {type_fa}", module='Schedules', severity='HIGH',
                actor_role=actor_role,
                target_id=sid, target_type='schedule',
                target_label=f"{item.get('lesson','')} — {fmt_jalali(item.get('date',''))}",
                tags=['حذف_برنامه']
            )
            # FIX جدید: اطلاع‌رسانی حذف به دانشجوهای همون گروه
            await _notify_schedule_deleted(context, item)
        await _show_manage_list(query, stype)

    elif action == 'flex_change' and can_manage:
        sid = parts[2]
        context.user_data['flex_change_sid'] = sid
        context.user_data['mode'] = 'flex_time_change'
        await query.edit_message_text(
            "🔄 <b>اعلام تغییر زمان کلاس</b>\n\n"
            "زمان جدید را با فرمت زیر بفرستید:\n"
            "<code>1404/MM/DD, HH:MM, توضیح کوتاه (اختیاری)</code>\n\n"
            "📌 مثال:\n"
            "<code>1404/02/10, 14:00, به دلیل تعطیلی استاد</code>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ لغو", callback_data='schedule:flex_list')
            ]])
        )

    # ══════════════════════════════════════════════
    # 📸 اسکن با هوشیار + الگوی هفتگی
    # ══════════════════════════════════════════════
    elif action == 'scan_menu' and can_manage:
        await _show_scan_menu(query)

    elif action == 'scan_weekly' and can_manage:
        context.user_data['mode'] = 'schedule_scan_weekly'
        await query.edit_message_text(
            "📸 <b>اسکن برنامه هفتگی با هوشیار</b>\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "عکس جدول برنامه کلاسی (شنبه تا جمعه) را بفرستید.\n"
            "هوشیار آن را به الگوی هفتگی تبدیل می‌کند — بعد پیش‌نمایش را تایید می‌کنید.\n\n"
            "💡 نکته: جدول باید خوانا باشد (۸-۱۰، ۱۰-۱۲ ... یا ساعت دقیق). "
            "برای کلاس‌های عملی/آز، نوع «منعطف» پیشنهاد می‌شود ولی قابل ویرایش است.\n\n"
            "برای لغو /cancel بزنید.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data='schedule:scan_menu')]]))

    elif action == 'scan_exam' and can_manage:
        context.user_data['mode'] = 'schedule_scan_exam'
        await query.edit_message_text(
            "📝 <b>اسکن برنامه امتحانات با هوشیار</b>\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "عکس جدول امتحانات (تاریخ + ساعت + درس) را بفرستید.\n"
            "هوشیار آن را استخراج می‌کند — پیش‌نمایش را تایید کنید تا ثبت شود.\n\n"
            "برای لغو /cancel بزنید.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data='schedule:scan_menu')]]))

    elif action == 'scan_confirm' and can_manage:
        await _confirm_scan(query, context, kind='weekly')

    elif action == 'scan_exam_confirm' and can_manage:
        await _confirm_scan(query, context, kind='exam')

    elif action == 'scan_cancel' and can_manage:
        context.user_data.pop('scan_preview', None)
        context.user_data.pop('mode', None)
        await query.edit_message_text("❌ اسکن لغو شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='schedule:scan_menu')]]))

    elif action == 'template_menu' and can_manage:
        await _show_template_menu(query)

    elif action == 'template_generate' and can_manage:
        await _handle_template_generate(query, context)

    elif action == 'template_clear' and can_manage:
        await _handle_template_clear(query)


# ══════════════════════════════════════════════════
#  UI
# ══════════════════════════════════════════════════

async def _schedule_main(query, user_group: str):
    """
    FIX طبق سند: «لیست کلاس‌ها» و «جدول هفتگی» قبلاً دو صفحه جدا
    برای یک داده بودند — گیج‌کننده و تکراری. حالا فقط یک دکمه
    «📊 برنامه کلاسی» وجود دارد که به _show_group_schedule می‌رود؛
    آن تابع همه‌چیز (جدول هفته + امتحانات مرتبط) را یکجا نشان می‌دهد.
    """
    g = user_group or ''
    g_label = f" — گروه {g}" if g else ""
    keyboard = [
        [InlineKeyboardButton(f"📊 برنامه کلاسی{g_label}", callback_data=f'schedule:group_view:{g}')],
        [InlineKeyboardButton("📝 امتحانات",      callback_data=f'schedule:type:exam:{g}')],
        [
            InlineKeyboardButton("🔄 جبرانی",        callback_data=f'schedule:type:makeup:{g}'),
            InlineKeyboardButton("⏳ امتحانات نزدیک", callback_data='schedule:upcoming'),
        ],
        [InlineKeyboardButton("👥 تغییر گروه نمایش", callback_data='schedule:group_sel:class')],
        [
            InlineKeyboardButton("📊 نمرات من", callback_data='grades:mine'),
            InlineKeyboardButton("📄 خروجی PDF (همه)", callback_data='schedule:export_pdf'),
        ],
        [InlineKeyboardButton("🔙 بازگشت",           callback_data='dashboard:refresh')],
    ]
    await query.edit_message_text(
        f"📅 <b>برنامه و امتحانات</b>\n"
        f"{'👤 گروه شما: ' + g if g else ''}",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _export_schedule_pdf(query, context, user: dict, user_group: str, stype: str = None):
    """
    FIX جدید: خروجی PDF شیک — با پارامتر stype قابل محدودسازی به یک
    نوع مشخص (کلاس/امتحان/جبرانی)، تا هر بخش فقط PDF مخصوص خودش را
    بسازد و همه‌چیز با هم قاطی نشود. stype=None یعنی «همه‌چیز با هم»
    (فقط از دکمه‌ی عمومی توی منوی اصلی برنامه در دسترس است).
    """
    items = await db.get_schedules(stype=stype, upcoming=True, group=user_group or None)
    if not items:
        await query.answer("📭 فعلاً چیزی توی این بخش نیست که خروجی بگیریم.", show_alert=True)
        return

    await query.answer("⏳ در حال ساخت PDF...")
    try:
        from schedule_pdf import generate_schedule_pdf
        student_name = user.get('name', '') if user else ''
        pdf_bytes = await asyncio.to_thread(
            generate_schedule_pdf, items, user_group or 'همه', student_name, stype
        )
    except Exception as e:
        logger.exception("schedule PDF export failed")
        await query.message.reply_text(f"❌ خطا در ساخت PDF: {e}")
        return

    type_slug = stype or 'hame'
    type_label = TYPE_NAMES.get(stype, '📋 همه‌ی برنامه‌ها') if stype else '📋 همه‌ی برنامه‌ها'
    # 🔢 منطق شمارش: برای کلاسِ هفتگی، ۲۰۰ ردیفِ تاریخ‌دار نداریم، ۲۷ کلاسِ یک هفته است
    display_count = len(items)
    try:
        if stype == 'class' or (stype is None and items and all((it.get('type') or 'class') == 'class' for it in items)):
            from schedule_pdf import _should_use_weekly_grid, _collect_weekly_slots
            if _should_use_weekly_grid(items, stype):
                sm, wkinfo = _collect_weekly_slots(items) or (None, (None, None))
                if sm and wkinfo and wkinfo[0]:
                    display_count = sum(len(v) for day in sm.values() for v in day.values())
    except Exception:
        display_count = len(items)
    file_obj = io.BytesIO(pdf_bytes)
    fname = f"barname_{type_slug}_{user_group or 'hamzyar'}_{now_tehran().strftime('%Y%m%d')}.pdf"
    file_obj.name = fname
    await query.message.reply_document(
        document=file_obj,
        caption=f"{type_label}\n👥 گروه {user_group or 'همه'}\n🔢 {display_count} مورد",
        parse_mode='HTML',
        filename=fname,
    )


async def _show_group_schedule(query, user_group: str):
    """
    FIX طبق سند: منبع واحد برنامه گروه — جدول هفته (شنبه تا جمعه)
    + برجسته‌سازی روز جاری + کلاس‌های منعطف مشخص + امتحانات مرتبط
    همان گروه، همه در یک صفحه. دیگر صفحه‌ی جدا «جدول هفتگی» وجود ندارد.
    """
    from datetime import timedelta
    today = now_tehran().date()
    week_start = start_of_week_tehran(today).date()
    week_end = week_start + timedelta(days=6)
    today_idx = (today.weekday() - 5) % 7

    start_str = week_start.isoformat()
    end_str = week_end.isoformat()

    all_classes = await db.get_schedules(stype='class', upcoming=False, group=user_group or None)
    week_classes = [c for c in all_classes if start_str <= c.get('date', '') <= end_str]

    by_day = {i: [] for i in range(7)}
    for c in week_classes:
        idx = jalali_weekday_index(c.get('date', ''))
        by_day[idx].append(c)

    g_label = f" — گروه {user_group}" if user_group else ""
    lines = [
        f"📊 <b>برنامه کلاسی{g_label}</b>",
        f"🗓 {fmt_jalali(start_str).split('(')[0].strip()} تا {fmt_jalali(end_str).split('(')[0].strip()}",
        "━━━━━━━━━━━━━━━━",
    ]
    has_any = False
    for i, day_name in enumerate(JALALI_WEEK_SAT_FIRST):
        items = sorted(by_day[i], key=lambda x: x.get('time', ''))
        # FIX: برجسته‌سازی روز جاری
        is_today = (i == today_idx)
        day_header = f"👉 <b>{day_name} (امروز)</b>" if is_today else f"📅 <b>{day_name}</b>"
        lines.append(f"\n{day_header}")
        if not items:
            lines.append("   <i>کلاسی ندارید</i>")
            continue
        has_any = True
        for c in items:
            flex = c.get('flex_type', 'fixed')
            if flex == 'flexible':
                time_part = f"🔄 زمان متغیر — آخرین اعلام: {_doc_time_display(c)}"
                if c.get('flex_note'):
                    time_part += f" ({c['flex_note']})"
            else:
                time_part = f"⏰ {_doc_time_display(c)}"
            lines.append(
                f"   • <b>{c.get('lesson','')}</b>\n"
                f"     {time_part}\n"
                f"     👨‍🏫 {c.get('teacher','')}  |  📍 {c.get('location','')}"
            )
    if not has_any:
        lines.append("\n<i>هیچ کلاسی برای این هفته ثبت نشده است.</i>")

    # FIX طبق سند: امتحانات مرتبط همین گروه هم در همان صفحه
    exams = await db.upcoming_exams(14)
    group_exams = [e for e in exams if e.get('group', 'هر دو') in ('هر دو', user_group, '')]
    if group_exams:
        lines.append("\n━━━━━━━━━━━━━━━━")
        lines.append("📝 <b>امتحانات نزدیک</b>")
        for e in group_exams[:5]:
            jalali = fmt_jalali(e.get('date', ''))
            lines.append(f"   • {e.get('lesson','')} — {jalali} {_doc_time_display(e)}")

    text = '\n'.join(lines)
    if len(text) > 4000:
        text = text[:3900] + "\n\n<i>... برای جزئیات کامل با ادمین هماهنگ کنید</i>"

    keyboard = []
    all_upcoming_classes = await db.get_schedules(stype='class', upcoming=True, group=user_group or None)
    if all_upcoming_classes:
        keyboard.append([InlineKeyboardButton(
            "📄 خروجی PDF همین بخش (کلاسی)",
            callback_data=f"schedule:export_pdf_type:class:{user_group or ''}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='schedule:main')])

    await query.edit_message_text(
        text, parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _show_schedule_list(query, items: list, title: str, stype: str = None, group_filter: str = None):
    # FIX جدید: دکمه‌ی خروجی PDF مخصوص همین بخش (نه قاطی همه‌ی انواع) —
    # فقط وقتی نشون داده می‌شه که واقعاً چیزی برای اکسپورت باشه
    export_cb = f"schedule:export_pdf_type:{stype or 'all'}:{group_filter or ''}"
    keyboard = []
    if items:
        keyboard.append([InlineKeyboardButton("📄 خروجی PDF همین بخش", callback_data=export_cb)])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='schedule:main')])
    kb_back = InlineKeyboardMarkup(keyboard)

    if not items:
        await query.edit_message_text(
            f"{title}\n\n❌ موردی ثبت نشده است.",
            reply_markup=kb_back
        )
        return

    lines = [f"<b>{title}</b>\n━━━━━━━━━━━━━━━━\n"]
    for s in items:
        icon     = TYPE_NAMES.get(s.get('type', ''), '📌').split()[0]
        g_icon   = GROUP_ICONS.get(str(s.get('group', '')), '👥')
        date_str = s.get('date', '')
        days     = days_until(date_str)
        jalali   = fmt_jalali(date_str)
        d_label  = _days_label(days)
        weekly   = " 🔁" if s.get('is_weekly') else ''
        lines.append(
            f"{icon} <b>{s.get('lesson', '')}</b>  {g_icon}{weekly}\n"
            f"   📅 {jalali}  |  {d_label}\n"
            f"   ⏰ {_doc_time_display(s)}  |  👨‍🏫 {s.get('teacher', '')}\n"
            f"   📍 {s.get('location', '')}\n"
            + (f"   📝 {s['notes']}\n" if s.get('notes') else '')
        )

    text = '\n'.join(lines)
    if len(text) > 4000:
        text = text[:3900] + "\n\n<i>... موارد بیشتر موجود است</i>"
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=kb_back)


# ══════════════════════════════════════════════════
#  بخش اول: مدیریت (مشاهده/ویرایش/حذف) برنامه‌ها
# ══════════════════════════════════════════════════

FIELD_LABELS = {
    'date':     '📅 تاریخ',
    'time':     '⏰ ساعت',
    'location': '📍 مکان',
    'teacher':  '👨\u200d🏫 استاد',
    'lesson':   '📚 درس',
    'notes':    '📝 توضیحات',
    'group':    '👥 گروه',
}


async def _show_manage_types(query):
    """FIX جدید: انتخاب نوع برنامه برای ویرایش/مدیریت"""
    keyboard = [
        [InlineKeyboardButton("📖 کلاس",   callback_data='schedule:manage_list:class')],
        [InlineKeyboardButton("📝 امتحان", callback_data='schedule:manage_list:exam')],
        [InlineKeyboardButton("🔄 جبرانی", callback_data='schedule:manage_list:makeup')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='admin:cat_schedule')],
    ]
    await query.edit_message_text(
        "✏️ <b>ویرایش برنامه‌ها</b>\n\nنوع برنامه‌ای که می‌خواهید ببینید/ویرایش کنید را انتخاب کنید:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _show_manage_list(query, stype: str):
    """
    FIX جدید (بخش اول): نمایش لیست برنامه‌های ثبت‌شده از یک نوع خاص،
    برای انتخاب و مشاهده/ویرایش/حذف.
    """
    items = await db.get_schedules(stype=stype, upcoming=False)
    type_fa = TYPE_NAMES.get(stype, stype)
    keyboard = []
    for s in items[:30]:
        sid = str(s['_id'])
        jd  = fmt_jalali(s.get('date', ''))
        label = f"{s.get('lesson','')} | {jd} {_doc_time_display(s)}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f'schedule:item:{sid}')])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='schedule:manage_types')])
    text = f"✏️ <b>{type_fa}</b>\n\nیک مورد را برای مشاهده/ویرایش/حذف انتخاب کنید:"
    if not items:
        text = f"✏️ <b>{type_fa}</b>\n\n❌ هیچ برنامه‌ای از این نوع ثبت نشده است."
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_item_detail(query, sid: str):
    """FIX جدید: نمایش «مشاهده» کامل یک برنامه + دکمه‌های ویرایش/حذف/بازگشت"""
    item = await db.get_schedule_by_id(sid)
    if not item:
        await query.edit_message_text("❌ این برنامه پیدا نشد.")
        return
    stype   = item.get('type', 'class')
    type_fa = TYPE_NAMES.get(stype, stype)
    jalali_display = fmt_jalali(item.get('date', ''))
    flex = item.get('flex_type', 'fixed')
    flex_label = "🔄 منعطف" if flex == 'flexible' else "📌 ثابت"
    g_label = item.get('group') or 'هر دو'
    text = (
        f"👁 <b>{type_fa}</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"📚 <b>درس:</b> {item.get('lesson','')}\n"
        f"👨‍🏫 <b>استاد:</b> {item.get('teacher','')}\n"
        f"📅 <b>تاریخ:</b> {jalali_display}\n"
        f"⏰ <b>ساعت:</b> {_doc_time_display(item)}\n"
        f"📍 <b>مکان:</b> {item.get('location','')}\n"
        f"👥 <b>گروه:</b> {g_label}\n"
        f"🔁 <b>نوع زمان‌بندی:</b> {flex_label}\n"
        + (f"📝 <b>توضیحات:</b> {item.get('notes')}\n" if item.get('notes') else '')
    )
    keyboard = [
        [InlineKeyboardButton("✏️ ویرایش", callback_data=f'schedule:edit_menu:{sid}')],
        [InlineKeyboardButton("🗑 حذف",     callback_data=f'schedule:del_item:{sid}')],
        [InlineKeyboardButton("🔙 بازگشت",  callback_data=f'schedule:manage_list:{stype}')],
    ]
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_edit_menu(query, sid: str):
    """FIX جدید: انتخاب اینکه کدام فیلد ویرایش شود، یا ویرایش کامل"""
    item = await db.get_schedule_by_id(sid)
    if not item:
        await query.edit_message_text("❌ این برنامه پیدا نشد.")
        return
    keyboard = [
        [
            InlineKeyboardButton("📅 ویرایش تاریخ", callback_data=f'schedule:edit_field:{sid}:date'),
            InlineKeyboardButton("⏰ ویرایش ساعت",  callback_data=f'schedule:edit_field:{sid}:time'),
        ],
        [
            InlineKeyboardButton("📍 ویرایش مکان",  callback_data=f'schedule:edit_field:{sid}:location'),
            InlineKeyboardButton("👨‍🏫 ویرایش استاد", callback_data=f'schedule:edit_field:{sid}:teacher'),
        ],
        [
            InlineKeyboardButton("📚 ویرایش درس",   callback_data=f'schedule:edit_field:{sid}:lesson'),
            InlineKeyboardButton("👥 ویرایش گروه",  callback_data=f'schedule:edit_field:{sid}:group'),
        ],
        [InlineKeyboardButton("📝 ویرایش توضیحات", callback_data=f'schedule:edit_field:{sid}:notes')],
        [InlineKeyboardButton("✏️ ویرایش کامل همه اطلاعات", callback_data=f'schedule:edit_full:{sid}')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f'schedule:item:{sid}')],
    ]
    await query.edit_message_text(
        f"✏️ <b>ویرایش {item.get('lesson','')}</b>\n\nکدام بخش را می‌خواهید ویرایش کنید؟",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _start_field_edit(query, context, sid: str, field: str):
    """FIX جدید: شروع ویرایش تک‌فیلدی — نمایش مقدار فعلی و درخواست مقدار جدید"""
    item = await db.get_schedule_by_id(sid)
    if not item or field not in FIELD_LABELS:
        await query.edit_message_text("❌ این برنامه پیدا نشد.")
        return
    context.user_data['edit_schedule_sid']   = sid
    context.user_data['edit_schedule_field'] = field
    context.user_data['mode']                = 'edit_schedule_field'

    current = item.get(field, '')
    current_display = fmt_jalali(current) if field == 'date' else (current or '—')
    label = FIELD_LABELS[field]

    hint = ''
    if field == 'date':
        hint = "\n\nفرمت: <code>1404/MM/DD</code> (تاریخ شمسی)"
    elif field == 'time':
        hint = "\n\nفرمت: <code>HH:MM</code> — مثال: <code>14:30</code>"
    elif field == 'group':
        hint = "\n\nمقدار: <code>1</code> یا <code>2</code> یا <code>هر دو</code>"

    await query.edit_message_text(
        f"✏️ <b>{label}</b>\n\n"
        f"مقدار فعلی: <b>{current_display}</b>\n\n"
        f"مقدار جدید را ارسال کنید:{hint}",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ لغو", callback_data=f'schedule:item:{sid}')
        ]])
    )


async def handle_edit_schedule_field_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    FIX جدید (بخش اول): پردازش مقدار جدید یک فیلد و به‌روزرسانی مستقیم
    همان رکورد در دیتابیس (UPDATE، نه INSERT) + اطلاع‌رسانی به دانشجوها.
    """
    from utils import broadcast_message
    sid   = context.user_data.pop('edit_schedule_sid', None)
    field = context.user_data.pop('edit_schedule_field', None)
    context.user_data.pop('mode', None)
    raw   = update.message.text.strip()

    if not sid or not field:
        await update.message.reply_text("❌ خطا — دوباره تلاش کنید.")
        return

    item = await db.get_schedule_by_id(sid)
    if not item:
        await update.message.reply_text("❌ این برنامه پیدا نشد (ممکن است حذف شده باشد).")
        return

    value = raw
    if field == 'date':
        parsed = _parse_jalali_date(_normalize_text(raw))
        try:
            parse_gregorian_date(parsed)
        except (TimeContractError, ValueError):
            await update.message.reply_text(
                "❌ تاریخ نامعتبر است. فرمت صحیح: <code>1404/MM/DD</code>",
                parse_mode='HTML'
            )
            return
        value = parsed
    elif field == 'time':
        raw_time = raw.strip()
        if not _is_valid_time(raw_time):
            await update.message.reply_text("❌ فرمت ساعت اشتباه است. مثال: <code>14:30</code>", parse_mode='HTML')
            return
        value = raw_time
    elif field == 'group':
        group_map = {
            '1': '1', '۱': '1', 'گروه ۱': '1', 'گروه 1': '1',
            '2': '2', '۲': '2', 'گروه ۲': '2', 'گروه 2': '2',
            'هر دو': 'هر دو', 'هردو': 'هر دو', 'all': 'هر دو',
        }
        value = group_map.get(raw.strip(), raw.strip() or 'هر دو')

    before_value = fmt_jalali(item.get('date', '')) if field == 'date' else item.get(field, '')
    ok = await db.update_schedule_field(sid, field, value)
    if not ok:
        await update.message.reply_text("❌ خطا در ذخیره تغییر.")
        return

    type_fa = TYPE_NAMES.get(item.get('type', ''), '')
    label   = FIELD_LABELS.get(field, field)
    after_value = fmt_jalali(value) if field == 'date' else value

    admin_uid  = update.effective_user.id
    admin_user = await db.get_user(admin_uid)
    actor_name = admin_user.get('name', 'ادمین') if admin_user else 'ادمین'
    actor_role = await db.get_actor_role_label(admin_uid)
    await send_audit_log(
        context.bot, 'admin', actor_name, admin_uid,
        f"ویرایش {type_fa} — {label}", module='Schedules', severity='WARNING',
        actor_role=actor_role,
        target_id=sid, target_type='schedule', target_label=item.get('lesson', ''),
        before={label: before_value}, after={label: after_value},
        tags=['ویرایش_برنامه']
    )

    # FIX (بخش اول): اطلاع‌رسانی به دانشجوها که برنامه بروزرسانی شده —
    # بدون هیچ کش قدیمی؛ همه Queryهای نمایش برنامه مستقیماً از دیتابیس
    # می‌خوانند، پس نسخه جدید بلافاصله برای همه قابل مشاهده است.
    ntype = {'exam': 'exam', 'makeup': 'makeup'}.get(item.get('type'), 'schedule')
    users = await db.notif_users(ntype, group=item.get('group'))
    if field in ('date', 'time'):
        notif_text = "زمان کلاس تغییر کرده است." if item.get('type') == 'class' else f"⏰ زمان {type_fa} تغییر کرده است."
    else:
        notif_text = f"برنامه {type_fa} شما بروزرسانی شد."
    # interval-aware display for time edit
    if field == 'time':
        s_disp, e_disp = _parse_interval(value)
        # if interval parsed, show range
        if s_disp and e_disp:
            time_disp = _fa_interval(s_disp, e_disp)
        elif s_disp:
            time_disp = _fa_time(s_disp)
        else:
            time_disp = _fa_time(value)
    else:
        time_disp = _doc_time_display(item)
    notif_msg = (
        f"🔔 <b>{notif_text}</b>\n\n"
        f"📚 {item.get('lesson','')}\n"
        f"📅 {fmt_jalali(value) if field=='date' else fmt_jalali(item.get('date',''))}"
        f"  ⏰ {time_disp}\n"
        f"📍 {value if field=='location' else item.get('location','')}"
    )
    sent, _ = await broadcast_message(context.bot, users, notif_msg)

    await update.message.reply_text(
        f"✅ <b>{label} با موفقیت ویرایش شد!</b>\n\n"
        f"📚 {item.get('lesson','')}\n"
        f"مقدار جدید: <b>{after_value}</b>\n\n"
        f"🔔 <b>{sent} نفر</b> مطلع شدند.",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("👁 مشاهده برنامه", callback_data=f'schedule:item:{sid}'),
            InlineKeyboardButton("🔙 پنل ادمین",      callback_data='admin:cat_schedule'),
        ]])
    )


async def _show_delete_list(query):
    items    = await db.get_schedules(upcoming=False)
    keyboard = []
    for s in items[:20]:
        sid  = str(s['_id'])
        jd   = fmt_jalali(s.get('date', ''))
        tp   = TYPE_NAMES.get(s.get('type', ''), '').split()[0]
        label = f"🗑 {tp} | {s.get('lesson','')} | {jd}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f'schedule:del:{sid}')])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='admin:cat_schedule')])
    await query.edit_message_text(
        "🗑 <b>حذف برنامه</b>\n\nانتخاب کنید:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _show_flex_list(query):
    """
    FIX جدید: لیست کلاس‌های منعطف برای اعلام تغییر زمان.
    """
    all_items = await db.get_schedules(upcoming=True)
    flex_items = [s for s in all_items if s.get('flex_type') == 'flexible']
    if not flex_items:
        await query.edit_message_text(
            "🔄 <b>کلاس‌های منعطف</b>\n\n"
            "❌ هیچ کلاس منعطفی ثبت نشده.\n"
            "<i>برای ثبت کلاس منعطف، هنگام افزودن برنامه، نوع زمان‌بندی را «منعطف» انتخاب کنید.</i>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 بازگشت", callback_data='admin:cat_schedule')
            ]])
        )
        return
    keyboard = []
    for s in flex_items[:20]:
        sid = str(s['_id'])
        jd  = fmt_jalali(s.get('date', ''))
        label = f"🔄 {s.get('lesson','')} | {jd} {_doc_time_display(s)}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f'schedule:flex_change:{sid}')])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='admin:cat_schedule')])
    await query.edit_message_text(
        "🔄 <b>اعلام تغییر زمان — انتخاب کلاس</b>\n\n"
        "کلاسی که زمانش تغییر کرده را انتخاب کنید:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_flex_time_change_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    FIX جدید: پردازش متن زمان جدید برای کلاس منعطف + نوتیف فوری
    به همه‌ی دانشجویانی که نوتیف 'schedule' را روشن دارند.
    """
    from utils import broadcast_message
    sid = context.user_data.pop('flex_change_sid', None)
    context.user_data.pop('mode', None)
    raw = _normalize_text(update.message.text.strip())

    if not sid:
        await update.message.reply_text("❌ خطا — دوباره تلاش کنید.")
        return

    parts = [p.strip() for p in raw.split(',')]
    if len(parts) < 2:
        await update.message.reply_text(
            "❌ فرمت اشتباه!\nمثال: <code>1404/02/10, 14:00, توضیح</code>",
            parse_mode='HTML'
        )
        return

    new_date_raw = parts[0]
    new_time_raw = parts[1].strip()
    note         = parts[2] if len(parts) > 2 else ''
    s_parsed, e_parsed = _parse_interval(new_time_raw)
    if not s_parsed:
        await update.message.reply_text("❌ فرمت ساعت اشتباه است. مثال: 14:00 یا 08:00 تا 10:00")
        return
    new_time = s_parsed
    new_end = e_parsed or ''
    if new_end:
        try:
            from time_utils import parse_clock_time as _pct
            _pct(new_time); _pct(new_end)
            if int(new_end.split(':')[0])*60+int(new_end.split(':')[1]) <= int(new_time.split(':')[0])*60+int(new_time.split(':')[1]):
                await update.message.reply_text("❌ پایان باید بعد از شروع باشد.")
                return
        except Exception:
            await update.message.reply_text("❌ ساعت نامعتبر.")
            return
    else:
        # synthesize common end if missing
        synth = {"08:00":"10:00","10:00":"12:00","13:00":"15:00","15:00":"17:00","17:00":"19:00"}
        if new_time in synth:
            new_end = synth[new_time]

    new_date = _parse_jalali_date(new_date_raw)
    try:
        parse_gregorian_date(new_date)
    except (TimeContractError, ValueError):
        await update.message.reply_text("❌ تاریخ نامعتبر است.")
        return

    schedule_doc = await db.schedules.find_one({'_id': ObjectId(sid)})
    if not schedule_doc:
        await update.message.reply_text("❌ این کلاس پیدا نشد.")
        return

    ok = await db.update_schedule_time(sid, new_date, new_time, note, end_time=new_end)
    if not ok:
        await update.message.reply_text("❌ خطا در ذخیره تغییر.")
        return

    jalali_display = fmt_jalali(new_date)
    lesson  = schedule_doc.get('lesson', '')
    teacher = schedule_doc.get('teacher', '')
    location = schedule_doc.get('location', '')
    group    = schedule_doc.get('group', 'هر دو')

    notif_msg = (
        f"🔄 <b>تغییر زمان کلاس</b>\n\n"
        f"📚 {lesson}\n"
        f"👨‍🏫 {teacher}\n\n"
        f"📅 <b>زمان جدید:</b> {jalali_display}  ⏰ {_fa_interval(new_time, new_end)}\n"
        f"📍 {location}"
        + (f"\n\n📝 {note}" if note else '')
    )
    users = await db.notif_users('schedule', group=group)
    sent, _ = await broadcast_message(context.bot, users, notif_msg)

    admin_uid  = update.effective_user.id
    admin_user = await db.get_user(admin_uid)
    actor_name = admin_user.get('name', 'ادمین') if admin_user else 'ادمین'
    actor_role = await db.get_actor_role_label(admin_uid)
    old_jalali = fmt_jalali(schedule_doc.get('date', ''))
    await send_audit_log(
        context.bot, 'admin', actor_name, admin_uid,
        "تغییر زمان کلاس", module='Schedules', severity='WARNING',
        actor_role=actor_role,
        target_id=sid, target_type='schedule', target_label=lesson,
        before={'زمان': f"{old_jalali} {_doc_time_display(schedule_doc)}"},
        after={'زمان': f"{jalali_display} {_fa_interval(new_time, new_end)}"},
        tags=['تغییر_زمان_کلاس']
    )

    await update.message.reply_text(
        f"✅ <b>تغییر زمان ثبت و اعلام شد!</b>\n\n"
        f"📚 {lesson}\n📅 {jalali_display}  ⏰ {_fa_interval(new_time, new_end)}\n\n"
        f"🔔 <b>{sent} نفر</b> مطلع شدند.",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 پنل ادمین", callback_data='admin:cat_schedule')
        ]])
    )


async def show_schedule_main(message: Message, uid: int, user: dict):
    """
    FIX باگ مهم: این تابع یک کپی موازی و قدیمی از _schedule_main بود
    که هنوز دکمه‌های «کلاس‌ها» و «جدول هفتگی» را جدا نشان می‌داد —
    دقیقاً همان منشاء تناقضی که کاربر گزارش داد. حالا دقیقاً همان
    منوی یکپارچه‌ی _schedule_main را می‌سازد (یک دکمه «برنامه کلاسی»).
    """
    user_group = user.get('group', '') if user else ''
    g = user_group or ''
    g_label = f" — گروه {g}" if g else ""
    keyboard = [
        [InlineKeyboardButton(f"📊 برنامه کلاسی{g_label}", callback_data=f'schedule:group_view:{g}')],
        [InlineKeyboardButton("📝 امتحانات",      callback_data=f'schedule:type:exam:{g}')],
        [
            InlineKeyboardButton("🔄 جبرانی",        callback_data=f'schedule:type:makeup:{g}'),
            InlineKeyboardButton("⏳ امتحانات نزدیک", callback_data='schedule:upcoming'),
        ],
        [InlineKeyboardButton("👥 تغییر گروه نمایش", callback_data='schedule:group_sel:class')],
        [
            InlineKeyboardButton("📊 نمرات من", callback_data='grades:mine'),
            InlineKeyboardButton("📄 خروجی PDF (همه)", callback_data='schedule:export_pdf'),
        ],
    ]
    await message.reply_text(
        f"📅 <b>برنامه و امتحانات</b>\n"
        f"{'👤 گروه شما: ' + g if g else ''}",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ══════════════════════════════════════════════════
#  پارسر افزودن برنامه — FIX کامل
# ══════════════════════════════════════════════════

async def _ask_flex_type(message, context):
    """
    FIX جدید — مرحله ۱ پیش‌نمایش: انتخاب نوع زمان‌بندی (ثابت/منعطف)
    قبل از نمایش پیش‌نمایش نهایی.
    """
    keyboard = [
        [InlineKeyboardButton("📌 ثابت (زمان قطعی و همیشگی)", callback_data='schedule:flex:fixed')],
        [InlineKeyboardButton("🔄 منعطف (ممکن است زمان تغییر کند)", callback_data='schedule:flex:flexible')],
        [InlineKeyboardButton("❌ لغو", callback_data='admin:cat_schedule')],
    ]
    await message.reply_text(
        "📌 <b>نوع زمان‌بندی این مورد چیست؟</b>\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📌 <b>ثابت:</b> همیشه طبق همین زمان برگزار می‌شود\n"
        "🔄 <b>منعطف:</b> ممکن است زمان جا‌به‌جا شود — در جدول هفتگی "
        "با برچسب «زمان متغیر» نشان داده می‌شود",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _show_schedule_preview(message_or_query, context, edit: bool = False):
    """
    FIX جدید — مرحله ۲ پیش‌نمایش: نمایش کامل اطلاعات قبل از ثبت نهایی،
    با دکمه‌های ✅ تأیید و انتشار / ✏️ بازگشت و ویرایش / ❌ لغو.
    """
    p = context.user_data.get('pending_schedule', {})
    if not p:
        return
    type_fa = TYPE_NAMES.get(p['stype'], p['stype'])
    jalali_display = fmt_jalali(p['date'])
    flex = p.get('flex_type', 'fixed')
    flex_label = "🔄 منعطف (ممکن است تغییر کند)" if flex == 'flexible' else "📌 ثابت"
    g_label = p['group'] if p['group'] not in ('', None) else 'هر دو'
    is_edit = bool(p.get('edit_sid'))
    header  = "👁 <b>پیش‌نمایش ویرایش — لطفاً بررسی کنید</b>" if is_edit else "👁 <b>پیش‌نمایش — لطفاً بررسی کنید</b>"
    footer  = "بروزرسانی همان برنامه (بدون ساخت رکورد جدید)" if is_edit else "در انتظار تأیید نهایی شما"

    text = (
        f"{header}\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"🏷 <b>نوع:</b> {type_fa}\n"
        f"📚 <b>درس:</b> {p['lesson']}\n"
        f"👨‍🏫 <b>استاد:</b> {p['teacher']}\n"
        f"📅 <b>تاریخ:</b> {jalali_display}\n"
        f"⏰ <b>ساعت:</b> {_fa_interval(p['time'], p.get('end_time') or p.get('time_end'))}\n"
        f"📍 <b>مکان:</b> {p['location']}\n"
        f"👥 <b>گروه هدف:</b> {g_label}\n"
        f"🔁 <b>نوع زمان‌بندی:</b> {flex_label}\n"
        + (f"📝 <b>توضیحات:</b> {p['notes']}\n" if p.get('notes') else '')
        + "\n━━━━━━━━━━━━━━━━\n"
        f"📤 <b>وضعیت انتشار:</b> {footer}"
    )
    keyboard = [
        [InlineKeyboardButton("✅ تأیید و انتشار", callback_data='schedule:confirm_add')],
        [InlineKeyboardButton("✏️ بازگشت و ویرایش", callback_data='schedule:edit_pending')],
        [InlineKeyboardButton("❌ لغو", callback_data='schedule:cancel_pending')],
    ]
    markup = InlineKeyboardMarkup(keyboard)
    if edit and hasattr(message_or_query, 'edit_message_text'):
        await message_or_query.edit_message_text(text, parse_mode='HTML', reply_markup=markup)
    else:
        msg = message_or_query if hasattr(message_or_query, 'reply_text') else message_or_query.message
        await msg.reply_text(text, parse_mode='HTML', reply_markup=markup)


async def _finalize_schedule_add(update_or_query, context):
    """
    FIX جدید: تأیید نهایی — همان منطق ذخیره و اطلاع‌رسانی قبلی،
    اما حالا بعد از تأیید کاربر در پیش‌نمایش اجرا می‌شود.
    """
    from utils import broadcast_message
    p = context.user_data.pop('pending_schedule', {})
    if not p:
        return

    edit_sid = p.get('edit_sid')
    is_edit  = bool(edit_sid)

    if is_edit:
        # FIX جدید (بخش اول): از UPDATE استفاده می‌شود، نه INSERT —
        # همان رکورد بروزرسانی می‌شود و ID برنامه ثابت می‌ماند.
        ok = await db.update_schedule_full(
            edit_sid, p['lesson'], p['teacher'], p['date'], p['time'],
            p['location'], p.get('notes', ''), p['group'],
            flex_type=p.get('flex_type', 'fixed'),
            flex_note=p.get('time', '') if p.get('flex_type') == 'flexible' else '',
            end_time=p.get('end_time','') or p.get('time_end',''),
        )
        sid = edit_sid
        if not ok:
            for k in ('awaiting_search', 'search_mode', 'mode', 'schedule_type', 'schedule_edit_sid'):
                context.user_data.pop(k, None)
            fail_text = "❌ خطا در بروزرسانی — این برنامه پیدا نشد."
            if hasattr(update_or_query, 'edit_message_text'):
                await update_or_query.edit_message_text(fail_text)
            else:
                await update_or_query.message.reply_text(fail_text)
            return
    else:
        sid = await db.add_schedule(
            p['stype'], p['lesson'], p['teacher'], p['date'], p['time'],
            p['location'], p.get('notes', ''), p['group'],
            flex_type=p.get('flex_type', 'fixed'),
            flex_note=p.get('time', '') if p.get('flex_type') == 'flexible' else '',
            end_time=p.get('end_time','') or p.get('time_end',''),
        )

    # FIX جدید: نوتیف جبرانی جدا از برنامه کلاسی عادی است
    ntype = {'exam': 'exam', 'makeup': 'makeup'}.get(p['stype'], 'schedule')
    users   = await db.notif_users(ntype, group=p.get('group'))
    type_fa = TYPE_NAMES.get(p['stype'], p['stype'])
    g_label = f" | گروه {p['group']}" if p['group'] not in ('هر دو', '') else ''
    jalali_display = fmt_jalali(p['date'])
    flex_tag = " 🔄 (منعطف)" if p.get('flex_type') == 'flexible' else ''
    if is_edit:
        title_line = f"🔔 <b>{type_fa} شما بروزرسانی شد</b>{flex_tag}"
    else:
        title_line = f"📅 <b>{type_fa} جدید</b>{flex_tag}"
    notif_msg = (
        f"{title_line}\n\n"
        f"📚 {p['lesson']}\n"
        f"👨‍🏫 {p['teacher']}\n"
        f"📅 {jalali_display}  ⏰ {_fa_interval(p['time'], p.get('end_time'))}\n"
        f"📍 {p['location']}{g_label}"
    )
    sent, _ = await broadcast_message(context.bot, users, notif_msg)

    bot_obj = context.bot
    admin_uid = update_or_query.from_user.id if hasattr(update_or_query, 'from_user') else update_or_query.effective_user.id
    admin_user = await db.get_user(admin_uid)
    actor_name = admin_user.get('name', 'ادمین') if admin_user else 'ادمین'
    actor_role = await db.get_actor_role_label(admin_uid)
    await send_audit_log(
        bot_obj, 'admin', actor_name, admin_uid,
        f"ویرایش کامل {type_fa}" if is_edit else f"ایجاد {type_fa} جدید",
        module='Schedules', severity='WARNING' if is_edit else 'INFO',
        actor_role=actor_role,
        target_id=str(sid),
        target_type='schedule', target_label=p['lesson'],
        details=f"{jalali_display} {_fa_time(p['time'])}",
        tags=['ویرایش_برنامه'] if is_edit else ['ایجاد_برنامه']
    )

    for k in ('awaiting_search', 'search_mode', 'mode', 'schedule_type', 'schedule_edit_sid'):
        context.user_data.pop(k, None)

    header = f"✅ <b>{type_fa} با موفقیت ویرایش شد!</b>" if is_edit else f"✅ <b>{type_fa} با موفقیت اضافه شد!</b>"
    text = (
        f"{header}\n\n"
        f"📚 {p['lesson']}\n"
        f"👨‍🏫 {p['teacher']}\n"
        f"📅 {jalali_display}  ⏰ {_fa_time(p['time'])}\n"
        f"📍 {p['location']}{g_label}\n\n"
        f"🔔 <b>{sent} نفر</b> مطلع شدند."
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("👁 مشاهده برنامه", callback_data=f'schedule:item:{sid}')
        if is_edit else
        InlineKeyboardButton("📅 مشاهده برنامه", callback_data=f'schedule:type:{p["stype"]}:'),
        InlineKeyboardButton("🔙 پنل ادمین",      callback_data='admin:cat_schedule'),
    ]])
    if hasattr(update_or_query, 'edit_message_text'):
        await update_or_query.edit_message_text(text, parse_mode='HTML', reply_markup=keyboard)
    else:
        await update_or_query.message.reply_text(text, parse_mode='HTML', reply_markup=keyboard)


async def handle_add_schedule_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    پارس متن افزودن برنامه توسط ادمین
    FIX: نرمال‌سازی کاما فارسی + تشخیص هوشمند فیلدها
    """
    from utils import broadcast_message
    stype = context.user_data.pop('schedule_type', 'class')
    raw   = update.message.text.strip()

    # FIX: نرمال‌سازی کاما فارسی و ویرگول
    raw = _normalize_text(raw)

    try:
        parts = [p.strip() for p in raw.split(',')]

        if len(parts) < 5:
            raise ValueError(
                f"تعداد فیلدها کافی نیست ({len(parts)} فیلد دریافت شد، حداقل ۵ نیاز است)"
            )

        # FIX: تشخیص هوشمند — اگه فیلد سوم تاریخ نبود، بگرد دنبال تاریخ
        lesson  = parts[0]
        teacher = parts[1]

        # پیدا کردن تاریخ در بین فیلدها
        date_idx = None
        for i in range(2, min(4, len(parts))):
            if _is_date_string(parts[i]):
                date_idx = i
                break

        if date_idx is None:
            raise ValueError(
                "تاریخ شمسی پیدا نشد!\n"
                "مثال: <code>1404/03/18</code>\n"
                "توجه: از کاما انگلیسی <code>,</code> استفاده کنید، نه فارسی <code>٫</code>"
            )

        raw_date = parts[date_idx]
        date     = _parse_jalali_date(raw_date)

        # اعتبارسنجی تاریخ میلادی تولیدشده
        try:
            parse_gregorian_date(date)
        except (TimeContractError, ValueError):
            raise ValueError(f"تاریخ نامعتبر: {raw_date}")

        # بقیه فیلدها
        remaining = parts[date_idx + 1:]
        if len(remaining) < 2:
            raise ValueError("ساعت و مکان الزامی هستند")

        # FIX interval: پیدا کردن ساعت — پشتیبانی از بازه 08:00-10:00 یا 08:00 تا 10:00
        time_str = None
        end_str = None
        time_idx = None
        for i, r in enumerate(remaining):
            s,e = _parse_interval(r)
            if s:
                time_str = s
                end_str = e
                time_idx = i
                break

        if not time_str:
            raise ValueError(
                f"ساعت معتبر پیدا نشد! فرمت صحیح: <code>09:00</code> یا <code>08:00 تا 10:00</code>"
            )
        # synthesize end if missing with common intervals
        if not end_str:
            synth = {"08:00":"10:00","10:00":"12:00","13:00":"15:00","15:00":"17:00","17:00":"19:00"}
            end_str = synth.get(time_str, "")

        after_time = remaining[time_idx + 1:]
        location   = after_time[0].strip() if after_time else 'اعلام نشده'
        group      = after_time[1].strip() if len(after_time) > 1 else 'هر دو'
        notes      = after_time[2].strip() if len(after_time) > 2 else ''

        # نرمال‌سازی گروه
        group_map = {
            '1': '1', '۱': '1', 'گروه ۱': '1', 'گروه 1': '1',
            '2': '2', '۲': '2', 'گروه ۲': '2', 'گروه 2': '2',
            'هر دو': 'هر دو', 'هردو': 'هر دو', 'all': 'هر دو', '': 'هر دو',
        }
        group = group_map.get(group, 'هر دو')

        # FIX جدید: به‌جای ذخیره مستقیم، اطلاعات پارس‌شده را نگه می‌داریم
        # و یک پیش‌نمایش + انتخاب نوع زمان‌بندی نشان می‌دهیم.
        pending = {
            'stype': stype, 'lesson': lesson, 'teacher': teacher,
            'date': date, 'time': time_str, 'end_time': end_str or '', 'location': location,
            'group': group, 'notes': notes,
        }
        # FIX جدید (بخش اول — ویرایش کامل): اگر این متن برای ویرایش یک
        # برنامه‌ی موجود است (نه افزودن جدید)، sid آن را نگه می‌داریم
        # تا در پایان به‌جای INSERT از UPDATE استفاده شود.
        edit_sid = context.user_data.pop('schedule_edit_sid', None)
        if edit_sid:
            pending['edit_sid'] = edit_sid
        context.user_data['pending_schedule'] = pending
        context.user_data.pop('mode', None)
        await _ask_flex_type(update.message, context)

    except ValueError as e:
        edit_sid = context.user_data.get('schedule_edit_sid')
        for k in ('awaiting_search', 'search_mode', 'mode', 'schedule_type'):
            context.user_data.pop(k, None)
        retry_cb = f'schedule:edit_full:{edit_sid}' if edit_sid else f'schedule:add_start:{stype}'
        cancel_cb = f'schedule:item:{edit_sid}' if edit_sid else 'admin:main'
        await update.message.reply_text(
            f"❌ <b>خطا:</b> {e}\n\n"
            "━━━━━━━━━━━━━━━━\n"
            "📋 <b>فرمت صحیح:</b>\n"
            "<code>درس, استاد, 1404/MM/DD, HH:MM, مکان, گروه, توضیح</code>\n\n"
            "📌 <b>مثال:</b>\n"
            "<code>آناتومی, دکتر محمدی, 1404/01/15, 09:00, کلاس A2, هر دو</code>\n\n"
            "⚠️ <b>مهم:</b> از کاما انگلیسی <code>,</code> استفاده کنید",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 تلاش مجدد", callback_data=retry_cb),
                InlineKeyboardButton("❌ لغو",         callback_data=cancel_cb),
            ]])
        )


# ══════════════════════════════════════════════════
#  📸 اسکن با هوشیار — منطق Bot
# ══════════════════════════════════════════════════

async def _show_scan_menu(query):
    txt = (
        "📸 <b>اسکن با هوشیار</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "عکس جدول را بفرستید تا هوشیار آن را به‌صورت ساختاریافته استخراج کند.\n"
        "بعد پیش‌نمایش را تایید می‌کنید — هیچ چیزی بدون تایید ذخیره نمی‌شود.\n\n"
        "• <b>برنامه هفتگی</b> → به الگوی شنبه-جمعه تبدیل می‌شود (تکرار خودکار هفته بعد)\n"
        "• <b>امتحانات</b> → مستقیم به لیست امتحانات می‌رود"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 اسکن برنامه هفتگی (شنبه-جمعه)", callback_data='schedule:scan_weekly')],
        [InlineKeyboardButton("📝 اسکن لیست امتحانات", callback_data='schedule:scan_exam')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='admin:cat_schedule')],
    ])
    await query.edit_message_text(txt, parse_mode='HTML', reply_markup=kb)

async def _show_template_menu(query):
    templates = await db.get_schedule_templates()
    total = len(templates or [])
    g1 = sum(1 for t in (templates or []) if t.get('group') == '1')
    g2 = sum(1 for t in (templates or []) if t.get('group') == '2')
    both = total - g1 - g2
    txt = (
        "🔁 <b>الگوی هفتگی (شنبه-جمعه)</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"📦 الگوهای ذخیره‌شده: <b>{total}</b> (گ۱: {g1} | گ۲: {g2} | هر دو: {both})\n\n"
        "الگو هر هفته تکرار می‌شود؛ کافی است بازه را انتخاب کنید و «تولید» بزنید.\n"
        "استثنا (لغو/جبرانی) را از بخش ویرایش/حذف تک‌جلسه انجام دهید — الگو دست‌نخورده می‌ماند."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ تولید برای ۴ هفته آینده", callback_data='schedule:template_generate')],
        [InlineKeyboardButton("🗑 پاک‌سازی الگوها", callback_data='schedule:template_clear')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='admin:cat_schedule')],
    ])
    await query.edit_message_text(txt, parse_mode='HTML', reply_markup=kb)

async def _handle_template_generate(query, context):
    from datetime import timedelta
    from time_utils import parse_gregorian_date as _pgd
    import jdatetime
    today = now_tehran().date()
    # start = this Saturday
    start = start_of_week_tehran(today).date().isoformat().replace('-', '/')
    # convert to jalali for generate API
    # we pass jalali to db layer which handles both
    try:
        jd = jdatetime.date.fromgregorian(date=today)
        # use jalali formatting YYYY/MM/DD
        jalali_today = f"{jd.year}/{jd.month:02d}/{jd.day:02d}"
        start_j = jalali_today  # approx; db will handle correctly via parse_jalali
        # end = 4 weeks later
        end_date = today + timedelta(days=28)
        jd2 = jdatetime.date.fromgregorian(date=end_date)
        end_j = f"{jd2.year}/{jd2.month:02d}/{jd2.day:02d}"
    except Exception:
        end_date = today + timedelta(days=28)
        start_j = today.isoformat().replace('-', '/')
        end_j = end_date.isoformat().replace('-', '/')
    await query.edit_message_text("⏳ در حال تولید برنامه ۴ هفته از روی الگو...")
    res = await db.generate_schedules_from_templates(start_j, end_j)
    if not res.get('ok'):
        await query.edit_message_text(f"❌ خطا: {res.get('error')}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='schedule:template_menu')]]))
        return
    created = res.get('created', 0)
    skipped = res.get('skipped', 0)
    await query.edit_message_text(
        f"✅ تولید انجام شد\n\n"
        f"🆕 ایجاد: <b>{created}</b>\n"
        f"⏭ تکراری (رد): <b>{skipped}</b>\n"
        f"📅 بازه: {start_j} تا {end_j}",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='schedule:template_menu')]])
    )
    try:
        admin_user = await db.get_user(query.from_user.id)
        await send_audit_log(context.bot, 'admin', admin_user.get('name','ادمین') if admin_user else 'ادمین', query.from_user.id,
                             "تولید برنامه از الگو (Bot)", module='Schedules', severity='INFO',
                             after={'created': created, 'skipped': skipped}, tags=['الگوی_هفتگی','تولید','ربات'])
    except Exception:
        pass

async def _handle_template_clear(query):
    n = await db.clear_schedule_templates()
    await query.edit_message_text(f"🗑 الگوها پاک شدند ({n} ردیف).", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='schedule:template_menu')]]))

WEEKDAY_FA = ["شنبه","یکشنبه","دوشنبه","سه‌شنبه","چهارشنبه","پنج‌شنبه","جمعه"]

async def handle_schedule_scan_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get('mode', '')
    kind = 'weekly' if mode == 'schedule_scan_weekly' else 'exam' if mode == 'schedule_scan_exam' else None
    if kind not in ('weekly','exam'):
        return
    msg = update.message
    # get largest photo or document image
    file_obj = None
    try:
        if msg.photo:
            file_obj = await msg.photo[-1].get_file()
        elif msg.document and (msg.document.mime_type or '').startswith('image/'):
            file_obj = await msg.document.get_file()
    except Exception as e:
        await msg.reply_text(f"❌ دریافت عکس ناموفق: {e}")
        return
    if not file_obj:
        await msg.reply_text("❌ عکسی دریافت نشد.")
        return
    # download
    try:
        bio = io.BytesIO()
        await file_obj.download_to_memory(bio)
        image_bytes = bio.getvalue()
    except Exception as e:
        await msg.reply_text(f"❌ دانلود عکس ناموفق: {e}")
        return
    if len(image_bytes) < 500:
        await msg.reply_text("❌ عکس خراب یا خیلی کوچک است.")
        return
    if len(image_bytes) > 12*1024*1024:
        await msg.reply_text("❌ حجم عکس خیلی زیاد است (حداکثر ۱۲MB).")
        return
    # guess mime
    mime = "image/jpeg"
    try:
        if image_bytes[:2] == b'\xff\xd8':
            mime = "image/jpeg"
        elif image_bytes[:8].startswith(b'\x89PNG'):
            mime = "image/png"
        elif image_bytes[:4] == b'RIFF' and b'WEBP' in image_bytes[:12]:
            mime = "image/webp"
    except Exception:
        pass
    await msg.reply_text("⏳ هوشیار در حال خواندن جدول است... لطفاً صبر کنید.")
    try:
        from ai_solver import scan_weekly_schedule_image, scan_exam_schedule_image
        if kind == 'weekly':
            parsed = await scan_weekly_schedule_image(image_bytes, mime)
            slots = parsed.get('slots') or []
            if not slots:
                await msg.reply_text("❌ چیزی در عکس تشخیص داده نشد. لطفاً عکسی خوانا و واضح بفرستید.")
                return
            context.user_data['scan_preview'] = {'kind': 'weekly', 'slots': slots}
            context.user_data.pop('mode', None)
            # preview text
            # group by weekday
            by_w = {i: [] for i in range(7)}
            for s in slots:
                try:
                    w = int(s.get('weekday', -1))
                    if 0 <= w <= 6:
                        by_w[w].append(s)
                except Exception:
                    continue
            lines = ["👁 <b>پیش‌نمایش اسکن — برنامه هفتگی</b>", "━━━━━━━━━━━━━━━━", f"🔢 تعداد ردیف: <b>{len(slots)}</b>", ""]
            for w in range(7):
                lst = sorted(by_w[w], key=lambda x: x.get('time',''))
                if not lst:
                    continue
                lines.append(f"📅 <b>{WEEKDAY_FA[w]}</b>")
                for s in lst:
                    fl = "🔄" if s.get('flex_type') == 'flexible' else "📌"
                    gl = s.get('group','هر دو')
                    lines.append(f"  {fl} {_fa_interval(s.get('time',''), s.get('end_time') or s.get('time_end',''))} — <b>{s.get('lesson','')}</b> ({gl}) {s.get('teacher','') or ''} {s.get('location','') or ''}".strip())
                lines.append("")
            lines.append("برای تایید و ذخیره به‌عنوان الگوی هفتگی، دکمه تایید را بزنید.")
            lines.append("بعد از ذخیره، از بخش «🔁 الگوی هفتگی → تولید» برنامه ۴ هفته را بسازید.")
            txt = "\n".join(lines)[:3800]
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"✅ تایید و ذخیره ({len(slots)} ردیف)", callback_data='schedule:scan_confirm')],
                [InlineKeyboardButton("❌ لغو", callback_data='schedule:scan_cancel')],
            ])
            await msg.reply_text(txt, parse_mode='HTML', reply_markup=kb)
        else:
            parsed = await scan_exam_schedule_image(image_bytes, mime)
            exams = parsed.get('exams') or []
            if not exams:
                await msg.reply_text("❌ امتحانی تشخیص داده نشد.")
                return
            context.user_data['scan_preview'] = {'kind': 'exam', 'exams': exams}
            context.user_data.pop('mode', None)
            lines = ["👁 <b>پیش‌نمایش اسکن — امتحانات</b>", "━━━━━━━━━━━━━━━━", f"🔢 تعداد: <b>{len(exams)}</b>", ""]
            for e in exams[:30]:
                lines.append(f"• <b>{e.get('lesson','')}</b> — {e.get('date','')} {_fa_time(e.get('time',''))} 📍{e.get('location','') or '—'} ({e.get('group','هر دو')})")
            if len(exams) > 30:
                lines.append(f"... و {len(exams)-30} مورد دیگر")
            txt = "\n".join(lines)[:3800]
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"✅ تایید و ثبت ({len(exams)} امتحان)", callback_data='schedule:scan_exam_confirm')],
                [InlineKeyboardButton("❌ لغو", callback_data='schedule:scan_cancel')],
            ])
            await msg.reply_text(txt, parse_mode='HTML', reply_markup=kb)
    except Exception as e:
        from ai_solver import AIConfigError, AIError
        if isinstance(e, AIConfigError):
            await msg.reply_text(f"⚠️ هوشیار پیکربندی نشده: {e}\n\nاز پنل وب → تنظیمات Vault → AI API Keys یک مدل vision (gemini/openrouter) ست کنید.")
        elif isinstance(e, AIError):
            await msg.reply_text(f"❌ اسکن ناموفق: {e}")
        else:
            logger.exception("schedule scan failed")
            await msg.reply_text(f"❌ خطای اسکن: {str(e)[:300]}")
        # keep mode so admin can retry
        return

async def _confirm_scan(query, context, kind: str):
    preview = context.user_data.get('scan_preview')
    if not preview or preview.get('kind') != kind:
        await query.edit_message_text("❌ پیش‌نمایشی پیدا نشد. دوباره عکس بفرستید.")
        return
    if kind == 'weekly':
        slots = preview.get('slots') or []
        # validate times
        for s in slots:
            if not _is_valid_time(s.get('time','')):
                await query.edit_message_text("❌ زمان نامعتبر در پیش‌نمایش — دوباره اسکن کنید.")
                return
        res = await db.bulk_upsert_schedule_templates(slots)
        context.user_data.pop('scan_preview', None)
        await query.edit_message_text(
            f"✅ الگوی هفتگی ذخیره شد\n\n"
            f"➕ افزوده: <b>{res.get('added',0)}</b> | ✏️ به‌روز: <b>{res.get('updated',0)}</b> | مجموع: <b>{res.get('total',0)}</b>\n"
            f"حالا از «🔁 الگوی هفتگی → تولید» برنامه را برای هفته‌های آینده بسازید.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔁 تولید برنامه ۴ هفته", callback_data='schedule:template_generate'), InlineKeyboardButton("🔙 پنل", callback_data='admin:cat_schedule')]])
        )
        try:
            admin_user = await db.get_user(query.from_user.id)
            await send_audit_log(context.bot, 'admin', admin_user.get('name','ادمین') if admin_user else 'ادمین', query.from_user.id,
                                 "اسکن و ذخیره الگوی هفتگی (Bot هوشیار)", module='Schedules', severity='INFO',
                                 after=res, tags=['الگوی_هفتگی','اسکن_هوشیار','ربات'])
        except Exception:
            pass
    else:
        exams = preview.get('exams') or []
        from time_utils import parse_gregorian_date, parse_jalali_date, TimeContractError, en_digits
        created = 0; skipped = 0
        for raw in exams:
            try:
                lesson = str(raw.get('lesson') or '').strip()
                if not lesson: 
                    skipped += 1; continue
                raw_date = str(raw.get('date') or '').strip()
                if not raw_date:
                    skipped += 1; continue
                norm = en_digits(raw_date).replace('/', '-')
                try:
                    y = int(norm.split('-',1)[0])
                    if 1200 <= y <= 1600:
                        gdate = parse_jalali_date(raw_date).isoformat()
                    else:
                        gdate = parse_gregorian_date(norm).isoformat()
                except Exception:
                    skipped += 1; continue
                time_v = str(raw.get('time') or '08:00').strip()
                try:
                    parse_clock_time(time_v)
                except Exception:
                    time_v = '08:00'
                group = db.normalize_group(raw.get('group') or 'هر دو') or 'هر دو'
                loc = str(raw.get('location') or '').strip()[:80]
                exists = await db.schedules.find_one({"date": gdate, "type": "exam", "lesson": lesson, "time": time_v})
                if exists:
                    skipped +=1; continue
                await db.add_schedule("exam", lesson, "", gdate, time_v, loc, "", group)
                created +=1
            except Exception:
                skipped+=1; continue
        context.user_data.pop('scan_preview', None)
        await query.edit_message_text(
            f"✅ امتحانات ثبت شد\n\n🆕 ایجاد: <b>{created}</b> | ⏭ تکراری: <b>{skipped}</b>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 پنل", callback_data='admin:cat_schedule')]])
        )
        try:
            admin_user = await db.get_user(query.from_user.id)
            await send_audit_log(context.bot, 'admin', admin_user.get('name','ادمین') if admin_user else 'ادمین', query.from_user.id,
                                 "اسکن و ثبت امتحانات (Bot هوشیار)", module='Schedules', severity='INFO',
                                 after={'created':created,'skipped':skipped}, tags=['امتحان','اسکن_هوشیار','ربات'])
        except Exception:
            pass
