"""
🎫 تیکت پشتیبانی — نسخه پیشرفته
  ✅ پیش‌نمایش تیکت قبل از ارسال
  ✅ گفتگوی دوطرفه — دانشجو میتونه ادامه بده
  ✅ مدیریت پیشرفته برای ادمین: فیلتر، جستجو، ورودی
  ✅ اطلاعات کامل کاربری در پیام ادمین (ورودی، گروه)
  ✅ تیکت باز = کانال گفتگو، نه یک پیام
"""
import os
import re
import logging


def _h(value, dash: str = '') -> str:
    """escape با تحمل داده‌ی ناهمگون — 🛡 AUDIT-T1.

    فیلدهای پروفایل لگسی ممکن است int (شماره دانشجویی) یا None باشند؛
    `html.escape(123)` می‌ترکد، پس اول رشته/خط‌تیره می‌شود بعد escape.
    """
    from utils import esc as _central          # 🛡 AUDIT-A6 — یک پیاده‌سازی مرکزی
    return _central(value, dash)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import ContextTypes
from database import db
from utils import fmt_jalali, fmt_jalali_dt, send_audit_log, webapp_kb

def _tk_kb(rows, link: str):
    """🧠 موج N2 — کیبورد تیکت + ردیف web_app‌‌ی همان رشته‌ی تیکت
    (Deep Link) تا کاربر با یک لمس روی همان رشته/آخرین پاسخ باز شود."""
    _k = webapp_kb(link)
    if _k: rows = _k.inline_keyboard + rows
    return InlineKeyboardMarkup(rows)


logger   = logging.getLogger(__name__)
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))

TICKET_WAITING       = 60
TICKET_REPLY_WAITING = 61

SUBJECTS = [
    "🔬 مشکل در بخش علوم پایه",
    "📚 مشکل در بخش رفرنس‌ها",
    "🧪 مشکل در بانک سوال",
    "📅 مشکل در برنامه/امتحانات",
    "👤 مشکل حساب کاربری",
    "⚙️ مشکل فنی",
    "💡 پیشنهاد بهبود",
    "❓ سوال دیگر",
]


# ══════════════════════════════════════════════════
#  Callback اصلی
# ══════════════════════════════════════════════════

USER_TICKET_ACTIONS = {
    'main', 'new', 'subject', 'prio', 'preview_confirm', 'preview_cancel',
    'list', 'view', 'reply_user',
}

# 🌊 W8/UX-04 — اولویت تیکت (مشترک با API/وب)
TICKET_PRIORITY_FA = {
    'low': '🟢 کم‌اهمیت', 'normal': '⚪ عادی',
    'high': '🟠 مهم', 'urgent': '🔴 فوری',
}

# 🌊 W9 — وضعیت تیکت (هم‌گام با TICKET_STATUSES دیتابیس)
TICKET_STATUS_FA = {
    'open': '🟡 باز', 'in_progress': '🔵 در حال بررسی',
    'waiting_user': '🟣 منتظر کاربر', 'resolved': '✅ حل‌شده',
    'closed': '🟢 بسته',
}
TICKET_STATUS_ICON = {
    'open': '🟡', 'in_progress': '🔵', 'waiting_user': '🟣',
    'resolved': '✅', 'closed': '🟢',
}


async def _tperm(uid: int, perm: str) -> bool:
    """🌊 W10 — گیت RBAC تیکت در ربات.

    ADMIN_ID همیشه True (داخل has_permission) ⇒ بوت‌استرپ حفظ می‌شود؛
    خطای DB ⇒ رفتار قدیمی (فقط ADMIN_ID) تا قفل‌نشدن/بازنشدن ناامن.
    """
    try:
        return bool(await db.has_permission(uid, perm))
    except Exception:
        return uid == ADMIN_ID


async def _is_ticket_staff(uid: int) -> bool:
    return (await _tperm(uid, 'tickets.manage')
            or await _tperm(uid, 'tickets.reply'))


async def ticket_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    uid    = update.effective_user.id
    parts  = query.data.split(':')
    action = parts[1] if len(parts) > 1 else 'main'

    # FIX جدید (باگ اسپم تیکت): کاربر حذف‌شده/بلاک‌شده ممکن است هنوز
    # دکمه‌ی شیشه‌ای قدیمی «تیکت جدید» یا «مشاهده‌ی تیکت» را در چت
    # قبلی‌اش داشته باشد. بدون این چک می‌توانست با لمس همان دکمه،
    # بدون هیچ رکوردی در دیتابیس، تیکت خالی/اسپم بسازد.
    if action in USER_TICKET_ACTIONS and not await _is_ticket_staff(uid):
        u = await db.get_user(uid)
        if not u or not u.get('approved'):
            await query.answer(
                "⚠️ حساب شما یافت نشد یا هنوز تأیید نشده. لطفاً با /start ثبت‌نام کنید.",
                show_alert=True
            )
            return

    await query.answer()

    if action == 'main':
        await _ticket_main(query, uid)

    elif action == 'new':
        keyboard = [
            [InlineKeyboardButton(s, callback_data=f'ticket:subject:{i}')]
            for i, s in enumerate(SUBJECTS)
        ]
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='ticket:main')])
        await query.edit_message_text(
            "🎫 <b>تیکت جدید</b>\n\nموضوع مشکل را انتخاب کنید:",
            parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif action == 'subject':
        subject = SUBJECTS[int(parts[2])]
        context.user_data['ticket_subject'] = subject
        # 🌊 W8/UX-04 — انتخاب اولویت قبل از نوشتن متن
        await query.edit_message_text(
            f"🎫 <b>{subject}</b>\n\n"
            "🥇 اولویت تیکت را انتخاب کنید:",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(TICKET_PRIORITY_FA['urgent'],
                                      callback_data=f"ticket:prio:{parts[2]}:urgent"),
                 InlineKeyboardButton(TICKET_PRIORITY_FA['high'],
                                      callback_data=f"ticket:prio:{parts[2]}:high")],
                [InlineKeyboardButton(TICKET_PRIORITY_FA['normal'],
                                      callback_data=f"ticket:prio:{parts[2]}:normal"),
                 InlineKeyboardButton(TICKET_PRIORITY_FA['low'],
                                      callback_data=f"ticket:prio:{parts[2]}:low")],
                [InlineKeyboardButton("❌ لغو", callback_data='ticket:main')],
            ])
        )

    elif action == 'prio':
        subject = SUBJECTS[int(parts[2])]
        prio = parts[3] if len(parts) > 3 else 'normal'
        if prio not in TICKET_PRIORITY_FA:
            prio = 'normal'
        context.user_data['ticket_subject'] = subject
        context.user_data['ticket_priority'] = prio
        context.user_data['ticket_mode']    = 'waiting_message'
        await query.edit_message_text(
            f"🎫 <b>{subject}</b> ({TICKET_PRIORITY_FA[prio]})\n\n"
            "✍️ توضیح کامل مشکل خود را بنویسید:\n"
            "<i>هرچه دقیق‌تر بنویسید، سریع‌تر پاسخ می‌گیرید.</i>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ لغو", callback_data='ticket:main')
            ]])
        )
        return TICKET_WAITING

    elif action == 'preview_confirm':
        # تأیید پیش‌نمایش — ارسال واقعی
        await _do_create_ticket(update, context, confirmed=True)

    elif action == 'preview_cancel':
        # ویرایش — برگشت به نوشتن
        context.user_data['ticket_mode'] = 'waiting_message'
        subject = context.user_data.get('ticket_subject', '')
        await query.edit_message_text(
            f"🎫 <b>{subject}</b>\n\n"
            "✍️ پیام جدید خود را بنویسید:",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ لغو کامل", callback_data='ticket:main')
            ]])
        )
        return TICKET_WAITING

    elif action == 'list':
        await _ticket_list(query, uid)

    elif action == 'view':
        tid    = int(parts[2])
        ticket = await db.ticket_get(tid)
        if not ticket or ticket['user_id'] != uid:
            await query.answer("❌ تیکت پیدا نشد!", show_alert=True)
            return
        await _show_ticket_detail(query, ticket, is_admin=False)

    # ── ادامه مکالمه توسط دانشجو ──
    elif action == 'reply_user':
        tid    = int(parts[2])
        ticket = await db.ticket_get(tid)
        if not ticket or ticket['user_id'] != uid:
            await query.answer("❌ دسترسی ندارید!", show_alert=True)
            return
        if ticket.get('status') == 'closed':
            await query.answer("❌ این تیکت بسته شده. تیکت جدید باز کنید.", show_alert=True)
            return
        context.user_data['user_replying_ticket'] = tid
        context.user_data['ticket_mode']          = 'user_reply'
        await query.edit_message_text(
            f"💬 <b>ادامه تیکت #{tid}</b>\n\n"
            "پیام جدید خود را بنویسید:",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ لغو", callback_data=f'ticket:view:{tid}')
            ]])
        )
        return TICKET_WAITING

    # ══════════════════════════════════════════════
    # بخش ادمین — مدیریت پیشرفته
    # ══════════════════════════════════════════════

    elif action == 'manage' and await _tperm(uid, 'tickets.manage'):
        await _admin_manage(query, context)

    elif action == 'admin_filter' and await _tperm(uid, 'tickets.manage'):
        ftype = parts[2] if len(parts) > 2 else 'status'
        fval  = parts[3] if len(parts) > 3 else 'all'
        context.user_data[f'tkt_f_{ftype}'] = fval
        await _admin_manage(query, context)

    elif action == 'admin_search' and await _tperm(uid, 'tickets.manage'):
        context.user_data['ticket_mode']   = 'admin_search'
        context.user_data['mode']          = 'ticket_search'
        await query.edit_message_text(
            "🔍 <b>جستجوی تیکت</b>\n\n"
            "شماره تیکت یا نام کاربر را وارد کنید:",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ لغو", callback_data='ticket:manage')
            ]])
        )

    elif action == 'admin_view' and await _tperm(uid, 'tickets.manage'):
        tid    = int(parts[2])
        ticket = await db.ticket_get(tid)
        if not ticket:
            await query.answer("❌ پیدا نشد!", show_alert=True)
            return
        await _show_ticket_detail(query, ticket, is_admin=True)

    elif action == 'admin_prio' and await _tperm(uid, 'tickets.manage'):
        tid, prio = int(parts[2]), parts[3] if len(parts) > 3 else 'normal'
        ticket = await db.ticket_get(tid)
        if prio in TICKET_PRIORITY_FA and ticket:
            _frm = ticket.get('priority', 'normal')
            _sla = await db.ticket_sla_hours(prio)
            await db.tickets.update_one(
                {'ticket_id': tid},
                {'$set': {'priority': prio, 'sla_hours': _sla}})
            try:
                _au = await db.get_user(uid) or {}
                await send_audit_log(
                    context.bot, 'admin', _au.get('name', 'ادمین'), uid,
                    "تغییر اولویت تیکت (ربات)", module='Tickets',
                    severity='INFO',
                    actor_role=await db.get_actor_role_label(uid),
                    target_id=str(tid), target_type='ticket',
                    target_label=(ticket.get('subject') or '')[:60],
                    before={'priority': _frm},
                    after={'priority': prio, 'sla_hours': _sla},
                    tags=['اولویت_تیکت', 'ربات'])
            except Exception:
                pass
        ticket = await db.ticket_get(tid)
        await _show_ticket_detail(query, ticket, is_admin=True)

    elif action == 'admin_status' and await _tperm(uid, 'tickets.manage'):
        # 🌊 W9 — تغییر وضعیت گاردشده از ربات
        tid, to = int(parts[2]), parts[3] if len(parts) > 3 else ''
        res = await db.ticket_set_status(tid, to)
        if not res.get('ok'):
            await query.answer("⛔ این گذار وضعیت مجاز نیست",
                               show_alert=True)
        else:
            try:
                _au = await db.get_user(uid) or {}
                await send_audit_log(
                    context.bot, 'admin', _au.get('name', 'ادمین'), uid,
                    "تغییر وضعیت تیکت (ربات)", module='Tickets',
                    severity='INFO',
                    actor_role=await db.get_actor_role_label(uid),
                    target_id=str(tid), target_type='ticket',
                    target_label=f"تیکت #{tid}",
                    before={'status': res.get('frm')},
                    after={'status': res.get('to')},
                    tags=['وضعیت_تیکت', 'ربات'])
            except Exception:
                pass
        ticket = await db.ticket_get(tid)
        await _show_ticket_detail(query, ticket, is_admin=True)

    elif action == 'admin_canned' and await _tperm(uid, 'tickets.reply'):
        tid, cid = int(parts[2]), parts[3] if len(parts) > 3 else ''
        _canned = None
        for _c in await db.canned_list(only_active=True):
            if str(_c.get('_id')) == cid:
                _canned = _c
                break
        if not _canned:
            await query.answer("❌ پاسخ آماده پیدا نشد", show_alert=True)
            return
        await _send_ticket_reply(context.bot, tid, _canned['text'],
                                 actor_id=uid)
        context.user_data['ticket_mode'] = ''
        await query.edit_message_text(
            f"✅ پاسخ آماده «{_canned['title']}» به تیکت #{tid} ارسال شد!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"📋 تیکت #{tid}",
                                      callback_data=f'ticket:admin_view:{tid}')],
                [InlineKeyboardButton("🔙 مدیریت تیکت‌ها",
                                      callback_data='ticket:manage')],
            ]))

    elif action == 'admin_reply' and await _tperm(uid, 'tickets.reply'):
        tid = int(parts[2])
        context.user_data['replying_ticket'] = tid
        context.user_data['ticket_mode']     = 'admin_reply'
        ticket  = await db.ticket_get(tid)
        rc      = len(ticket.get('replies', [])) if ticket else 0
        # 🌊 W8/UX-04 — پاسخ‌های آماده (ارسال فوری با یک لمس)
        _kb = []
        for _c in (await db.canned_list(only_active=True))[:6]:
            _kb.append([InlineKeyboardButton(
                f"⚡ {_c.get('title', '')[:30]}",
                callback_data=f"ticket:admin_canned:{tid}:{_c.get('_id')}")])
        _kb.append([InlineKeyboardButton("🤖 پیش‌نویسِ هوشیار", callback_data=f'ticket:ai_draft:{tid}')])
        _kb.append([InlineKeyboardButton("❌ لغو", callback_data=f'ticket:admin_view:{tid}')])
        await query.edit_message_text(
            f"✏️ <b>پاسخ به تیکت #{tid}</b>\n"
            f"پاسخ‌های قبلی: {rc}\n\n"
            "پاسخ جدید خود را بنویسید یا یک پاسخ آماده بفرستید:",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(_kb)
        )
        return TICKET_REPLY_WAITING

    # ── ⚠️ قابلیتِ جدید: پیش‌نویسِ پاسخِ تیکت با هوشیار ──
    elif action == 'ai_draft' and await _tperm(uid, 'tickets.reply'):
        tid = int(parts[2])
        await _ticket_ai_draft(query, context, tid)

    elif action == 'ai_send' and await _tperm(uid, 'tickets.reply'):
        tid   = int(parts[2])
        draft = context.user_data.get('ai_ticket_draft', '')
        if not draft:
            await query.answer("⚠️ پیش‌نویسی برای ارسال نیست.", show_alert=True)
            return
        await _send_ticket_reply(context.bot, tid, draft, actor_id=uid)
        context.user_data.pop('ai_ticket_draft', None)
        context.user_data.pop('replying_ticket', None)
        context.user_data['ticket_mode'] = ''
        await query.edit_message_text(
            f"✅ پاسخِ پیشنهادیِ هوشیار به تیکت #{tid} ارسال شد!",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(f"📋 تیکت #{tid}", callback_data=f'ticket:admin_view:{tid}'),
                    InlineKeyboardButton("🔒 بستن",          callback_data=f'ticket:admin_close:{tid}'),
                ],
                [InlineKeyboardButton("🔙 مدیریت تیکت‌ها", callback_data='ticket:manage')],
            ])
        )

    elif action == 'admin_close' and await _tperm(uid, 'tickets.manage'):
        tid = int(parts[2])
        await query.edit_message_text(
            f"🔒 <b>بستن تیکت #{tid}</b>\n\n"
            "آیا مطمئنید که مشکل حل شده؟",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ بله، ببند", callback_data=f'ticket:admin_close_confirm:{tid}')],
                [InlineKeyboardButton("❌ برگشت",     callback_data=f'ticket:admin_view:{tid}')],
            ])
        )

    elif action == 'admin_close_confirm' and await _tperm(uid, 'tickets.manage'):
        tid    = int(parts[2])
        ticket = await db.ticket_get(tid)
        await db.ticket_close(tid)
        # FIX طبق سند: بستن تیکت = HIGH (تصمیم نهایی پشتیبانی)،
        # و target_label موضوع/کاربر تیکت را نشان می‌دهد، نه فقط شماره
        admin_user = await db.get_user(uid)
        actor_name = admin_user.get('name', 'ادمین') if admin_user else 'ادمین'
        actor_role = await db.get_actor_role_label(uid)
        ticket_label = f"{ticket.get('subject','')} — {ticket.get('user_name','')}" if ticket else f"تیکت #{tid}"
        await send_audit_log(
            context.bot, 'admin', actor_name, uid,
            "بستن تیکت", module='Tickets', severity='HIGH',
            actor_role=actor_role,
            target_id=str(tid), target_type='ticket', target_label=ticket_label,
            tags=['بستن_تیکت']
        )
        if ticket:
            # 🔔 موج ۴.۹۰ — اینباکس مینی‌اپ (Deep Link به همان تیکت)
            await db.inbox_add(ticket['user_id'], 'ticket_closed',
                f"✅ تیکت #{tid} بسته شد",
                f"📋 {ticket.get('subject','')}",
                link=f'/me/tickets?t={tid}')
            try:
                await context.bot.send_message(
                    ticket['user_id'],
                    f"✅ <b>تیکت #{tid} بسته شد</b>\n\n"
                    f"📋 {ticket.get('subject','')}\n\n"
                    "مشکل شما حل‌شده تلقی شد.\n"
                    "اگر سوال جدیدی دارید، تیکت جدید ثبت کنید.",
                    parse_mode='HTML',
                    reply_markup=_tk_kb([[
                        InlineKeyboardButton("🎫 تیکت جدید", callback_data='ticket:new')
                    ]], f'/me/tickets?t={tid}&hl=last')
                )
            except Exception:
                pass
        await query.edit_message_text(
            f"✅ تیکت #{tid} بسته شد.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 مدیریت تیکت‌ها", callback_data='ticket:manage')
            ]])
        )

    elif action == 'admin_reopen' and await _tperm(uid, 'tickets.manage'):
        # FIX جدید طبق سند: بازگشایی تیکت — قابلیت کاملاً جدید
        tid    = int(parts[2])
        ticket = await db.ticket_get(tid)
        await db.ticket_reopen(tid)
        admin_user = await db.get_user(uid)
        actor_name = admin_user.get('name', 'ادمین') if admin_user else 'ادمین'
        actor_role = await db.get_actor_role_label(uid)
        ticket_label = f"{ticket.get('subject','')} — {ticket.get('user_name','')}" if ticket else f"تیکت #{tid}"
        await send_audit_log(
            context.bot, 'admin', actor_name, uid,
            "بازگشایی تیکت", module='Tickets', severity='WARNING',
            actor_role=actor_role,
            target_id=str(tid), target_type='ticket', target_label=ticket_label,
            before={'وضعیت': 'بسته شده'}, after={'وضعیت': 'در حال بررسی'},
            tags=['بازگشایی_تیکت']
        )
        if ticket:
            # 🔔 موج ۴.۹۰ — اینباکس مینی‌اپ
            await db.inbox_add(ticket['user_id'], 'ticket_reopened',
                f"🔓 تیکت #{tid} مجدداً باز شد",
                f"📋 {ticket.get('subject','')}",
                link=f'/me/tickets?t={tid}')
            try:
                await context.bot.send_message(
                    ticket['user_id'],
                    f"🔓 <b>تیکت #{tid} مجدداً باز شد</b>\n\n"
                    f"📋 {ticket.get('subject','')}\n\n"
                    "می‌توانید ادامه گفتگو را ارسال کنید.",
                    parse_mode='HTML'
                )
            except Exception:
                pass
        await query.edit_message_text(
            f"🔓 تیکت #{tid} بازگشایی شد.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 مدیریت تیکت‌ها", callback_data='ticket:manage')
            ]])
        )

    # سازگاری با callback های قدیمی
    elif action == 'admin_list' and await _tperm(uid, 'tickets.manage'):
        await _admin_manage(query, context)

    elif action == 'admin_all' and await _tperm(uid, 'tickets.manage'):
        context.user_data['tkt_f_status'] = 'all'
        await _admin_manage(query, context)


# ══════════════════════════════════════════════════
#  هندلر پیام
# ══════════════════════════════════════════════════

async def ticket_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    user = await db.get_user(uid)
    mode = context.user_data.get('ticket_mode', '')
    text = update.message.text.strip()

    # ── دانشجو: پیام اولیه تیکت — نمایش پیش‌نمایش ──
    if mode == 'waiting_message':
        subject = context.user_data.get('ticket_subject', 'سوال')
        context.user_data['ticket_draft'] = text
        context.user_data['ticket_mode']  = 'awaiting_confirm'

        await update.message.reply_text(
            # 🛡 AUDIT-T1 — موضوع/متن، ورودیِ خودِ کاربر است: بدون escape،
            # رشته‌ای مثل <a href="…"> در پیش‌نمایش/نوتیف ادمین تگ زنده می‌شد
            # (فیشینگ داخل چت ادمین) یا تگِ ناقص باعث خطای پارس و رد شدن
            # کل پیام می‌گشت.
            f"👁 <b>پیش‌نمایش تیکت</b>\n\n"
            f"📋 موضوع: <b>{_h(subject)}</b>\n"
            f"🥇 اولویت: {TICKET_PRIORITY_FA.get(context.user_data.get('ticket_priority', 'normal'), '⚪ عادی')}\n"
            f"━━━━━━━━━━━━━━━━\n\n"
            f"💬 {_h(text)}\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            "آیا این تیکت را ارسال می‌کنید؟",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ بله، ارسال کن", callback_data='ticket:preview_confirm'),
                    InlineKeyboardButton("✏️ ویرایش",        callback_data='ticket:preview_cancel'),
                ],
                [InlineKeyboardButton("❌ لغو کامل", callback_data='ticket:main')],
            ])
        )
        return TICKET_WAITING

    # ── دانشجو: تأیید شده — ارسال واقعی ──
    elif mode == 'awaiting_confirm':
        # این حالت از callback handle میشه، نه از پیام
        pass

    # ── دانشجو: ادامه مکالمه در تیکت باز ──
    elif mode == 'user_reply':
        tid = context.user_data.get('user_replying_ticket')
        if not tid:
            return
        ticket = await db.ticket_get(tid)
        if not ticket or ticket.get('status') == 'closed':
            await update.message.reply_text("❌ این تیکت بسته شده.")
            context.user_data.pop('ticket_mode', None)
            return

        # اضافه کردن پیام به replies با تگ [دانشجو]
        reply_text = f"[دانشجو] {text}"
        await db.ticket_add_reply(tid, reply_text)
        # AUDIT — student reply via bot
        try:
            _u = await db.get_user(uid)
            _name = (_u or {}).get('name', str(uid))
            _role = await db.get_actor_role_label(uid)
            await send_audit_log(context.bot, 'user', _name, uid, "پاسخ دانشجو به تیکت (ربات)", module='Tickets', severity='INFO', actor_role=_role, target_id=str(tid), target_type='ticket', target_label=f"تیکت #{tid}", after={"reply_len": len(text)}, tags=['پاسخ_تیکت', 'ربات'])
        except Exception:
            pass
        context.user_data.pop('ticket_mode', None)
        context.user_data.pop('user_replying_ticket', None)

        name = user.get('name', '') if user else ''
        # اطلاع به ادمین
        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"💬 <b>پیام جدید در تیکت #{tid}</b>\n"
                f"👤 {_h(name)}\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"{_h(text)}",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(f"✏️ پاسخ تیکت #{tid}", callback_data=f'ticket:admin_view:{tid}')
                ]])
            )
        except Exception:
            pass

        await update.message.reply_text(
            f"✅ پیام شما به تیکت #{tid} اضافه شد.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f"📋 مشاهده تیکت #{tid}", callback_data=f'ticket:view:{tid}')
            ]])
        )

    # ── جستجوی تیکت توسط ادمین ──
    elif mode == 'admin_search' and await _tperm(uid, 'tickets.manage'):
        context.user_data.pop('ticket_mode', None)
        context.user_data.pop('mode', None)
        await _search_tickets(update, text)

    # ── پاسخ ادمین به تیکت ──
    elif mode == 'admin_reply' and await _tperm(uid, 'tickets.reply'):
        tid = context.user_data.pop('replying_ticket', None)
        if not tid:
            return
        context.user_data['ticket_mode'] = ''
        await _send_ticket_reply(context.bot, tid, text, actor_id=uid)

        await update.message.reply_text(
            f"✅ پاسخ به تیکت #{tid} ارسال شد!",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(f"📋 تیکت #{tid}", callback_data=f'ticket:admin_view:{tid}'),
                    InlineKeyboardButton("🔒 بستن",          callback_data=f'ticket:admin_close:{tid}'),
                ],
                [InlineKeyboardButton("🔙 مدیریت تیکت‌ها", callback_data='ticket:manage')],
            ])
        )


async def _send_ticket_reply(bot, tid: int, text: str,
                             actor_id: int = 0) -> None:
    """
    منطقِ مشترکِ «ثبت و ارسالِ پاسخِ ادمین به یک تیکت» — چه پاسخ دستی
    تایپ شده باشه، چه از پیش‌نویسِ هوشیار تاییدشده. اینجا فقط یه بارِ
    واحد نوشته شده تا هر دو مسیر رفتارِ کاملاً یکسانی داشته باشن.
    """
    ticket = await db.ticket_get(tid)
    await db.ticket_add_reply(tid, text)
    # AUDIT — admin reply via bot (if called by admin)
    try:
        # 🌊 W10 — actor واقعی (RBAC)؛ پیش‌فرض ADMIN_ID برای سازگاری
        _actor = int(actor_id or ADMIN_ID)
        _admin_u = await db.get_user(_actor)
        _admin_name = (_admin_u or {}).get('name', 'ادمین')
        _admin_role = await db.get_actor_role_label(_actor)
        await send_audit_log(None, 'admin', _admin_name, _actor, "پاسخ پشتیبانی به تیکت (ربات)", module='Tickets', severity='INFO', actor_role=_admin_role, target_id=str(tid), target_type='ticket', target_label=(ticket or {}).get('subject','')[:60], after={"reply_len": len(text)}, tags=['پاسخ_تیکت', 'ربات'])
    except Exception:
        pass

    if ticket:
        try:
            # 🔔 موج ۴.۹۰ — اینباکس مینی‌اپ (خلاصه‌ی پاسخ بدون HTML)
            import re as _re
            await db.inbox_add(ticket['user_id'], 'ticket_reply',
                f"📨 پاسخ به تیکت #{tid}",
                f"📋 {ticket.get('subject','')}\n💬 {_re.sub('<[^>]+>', '', text)[:180]}",
                link=f'/me/tickets?t={tid}')
            await bot.send_message(
                ticket['user_id'],
                f"📨 <b>پاسخ به تیکت #{tid}</b>\n"
                f"📋 {_h(ticket.get('subject',''))}\n"
                f"━━━━━━━━━━━━━━━━\n\n"
                f"💬 {_h(text)}\n\n"
                "<i>برای ادامه گفتگو می‌توانید پاسخ دهید.</i>",
                parse_mode='HTML',
                reply_markup=_tk_kb([[
                    InlineKeyboardButton("💬 ادامه گفتگو", callback_data=f'ticket:reply_user:{tid}'),
                    InlineKeyboardButton("📋 مشاهده تیکت", callback_data=f'ticket:view:{tid}'),
                ]], f'/me/tickets?t={tid}&hl=last')
            )
        except Exception:
            pass


async def _ticket_ai_draft(query, context, tid: int):
    """
    ⚠️ قابلیتِ جدید: پیش‌نویسِ پاسخِ تیکت با هوشیار. اگه AI کار نکنه
    (سهمیه/قطعی/کلید)، ادمین همیشه می‌تونه با دکمه‌ی «لغو» برگرده به
    همون صفحه‌ی «پاسخِ دستی» که قبلاً بود — این قابلیت هیچ‌وقت مسیرِ
    اصلیِ پاسخ‌دادن به تیکت رو قفل نمی‌کنه.
    """
    from ai_solver import generate_ticket_reply_ai, AIError

    ticket = await db.ticket_get(tid)
    if not ticket:
        await query.answer("❌ تیکت پیدا نشد.", show_alert=True)
        return

    try:
        draft = await generate_ticket_reply_ai(
            subject=ticket.get('subject', ''),
            ticket_text=ticket.get('message', ''),
            previous_replies=ticket.get('replies', []),
        )
    except AIError as e:
        await query.edit_message_text(
            f"⚠️ هوشیار الان نتونست پیش‌نویس بسازه:\n<i>{e}</i>\n\n"
            "می‌تونی خودت دستی پاسخ بدی.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 دوباره امتحان کن", callback_data=f'ticket:ai_draft:{tid}')],
                [InlineKeyboardButton("✏️ پاسخِ دستی", callback_data=f'ticket:admin_reply:{tid}')],
            ]))
        return
    except Exception:
        logger.exception("طراحی پیش‌نویسِ پاسخِ تیکت با AI ناموفق بود")
        await query.edit_message_text(
            "⚠️ یه خطای غیرمنتظره پیش اومد. می‌تونی خودت دستی پاسخ بدی.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✏️ پاسخِ دستی", callback_data=f'ticket:admin_reply:{tid}')
            ]]))
        return

    context.user_data['ai_ticket_draft'] = draft
    await query.edit_message_text(
        f"🤖 <b>پیش‌نویسِ پیشنهادیِ هوشیار — تیکت #{tid}</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"{draft}",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ ارسالِ همین پاسخ", callback_data=f'ticket:ai_send:{tid}')],
            [InlineKeyboardButton("🔄 دوباره بساز", callback_data=f'ticket:ai_draft:{tid}')],
            [InlineKeyboardButton("✏️ خودم می‌نویسم", callback_data=f'ticket:admin_reply:{tid}')],
        ]))


async def _do_create_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE, confirmed: bool = False):
    """ارسال واقعی تیکت بعد از تأیید پیش‌نمایش"""
    query   = update.callback_query
    uid     = update.effective_user.id
    user    = await db.get_user(uid)

    # FIX جدید: لایه‌ی دوم دفاعی — حتی اگر مسیر دیگری (context.user_data
    # آویزون) به این تابع برسد، بدون رکورد معتبر کاربر هیچ تیکتی ساخته
    # نمی‌شود.
    if not user or not user.get('approved'):
        context.user_data.clear()
        await query.answer("⚠️ حساب شما یافت نشد. لطفاً با /start ثبت‌نام کنید.", show_alert=True)
        return

    subject = context.user_data.get('ticket_subject', 'سوال')
    text    = context.user_data.get('ticket_draft', '')

    if not text:
        await query.answer("❌ پیامی برای ارسال وجود ندارد!", show_alert=True)
        return

    name    = user.get('name', '')      if user else ''
    sid     = user.get('student_id','') if user else ''
    group   = user.get('group', '')     if user else ''
    intake  = user.get('intake', '')    if user else ''
    uname   = f"@{user.get('username','')}" if user and user.get('username') else 'ندارد'

    tid = await db.ticket_create(uid, name, subject, text,
        priority=context.user_data.get('ticket_priority', 'normal'))
    # AUDIT — ticket create via bot
    try:
        _role2 = await db.get_actor_role_label(uid)
        await send_audit_log(context.bot, 'user', name or str(uid), uid, "ثبت تیکت (ربات)", module='Tickets', severity='INFO', actor_role=_role2, target_id=str(tid), target_type='ticket', target_label=subject[:60], after={"subject": subject[:60]}, tags=['ثبت_تیکت', 'ربات'])
    except Exception:
        pass
    context.user_data.pop('ticket_mode', None)
    context.user_data.pop('ticket_draft', None)
    context.user_data.pop('ticket_subject', None)
    context.user_data.pop('ticket_priority', None)

    # 🔔 موج ۴.۹۰ — ثبت تیکت در مرکز اعلان مینی‌اپ (پارتی با مسیر وب)
    await db.inbox_add(uid, 'ticket_created',
        f"🎫 تیکت #{tid} ثبت شد",
        f"📋 {subject}\nبه‌محض پاسخ پشتیبانی، همین‌جا خبرت می‌کنیم.",
        link=f'/me/tickets?t={tid}')

    # اطلاع کامل به ادمین با ورودی
    try:
        await context.bot.send_message(
            ADMIN_ID,
            f"🔔 <b>تیکت جدید #{tid}</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"👤 <b>نام:</b> {_h(name)}\n"
            f"🎓 <b>شماره دانشجویی:</b> {_h(sid) or '—'}\n"
            f"📅 <b>ورودی:</b> {_h(intake) or '—'}\n"
            f"👥 <b>گروه:</b> {_h(group) or '—'}\n"
            f"📱 <b>یوزرنیم:</b> {_h(uname)}\n"
            f"🆔 <b>آیدی:</b> <code>{uid}</code>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📋 <b>موضوع:</b> {_h(subject)}\n\n"
            f"💬 <b>متن تیکت:</b>\n{_h(text)}",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f"✏️ پاسخ به تیکت #{tid}", callback_data=f'ticket:admin_view:{tid}')
            ]])
        )
    except Exception:
        pass

    await query.edit_message_text(
        f"✅ <b>تیکت #{tid} با موفقیت ثبت شد!</b>\n\n"
        "📬 به زودی پاسخ داده خواهد شد.\n"
        "تا زمانی که تیکت باز است، می‌توانید پیام جدید اضافه کنید. 🙏",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"📋 مشاهده تیکت #{tid}", callback_data=f'ticket:view:{tid}')],
            [InlineKeyboardButton("🔙 بازگشت به پشتیبانی",  callback_data='ticket:main')],
        ])
    )


# ══════════════════════════════════════════════════
#  مدیریت تیکت‌ها — ادمین پیشرفته
# ══════════════════════════════════════════════════

async def _admin_manage(query, context):
    """پنل مدیریت تیکت‌ها با فیلتر پیشرفته"""
    f_status = context.user_data.get('tkt_f_status', 'open')
    f_intake = context.user_data.get('tkt_f_intake', 'all')

    # دریافت تیکت‌ها
    if f_status == 'all':
        tickets = await db.ticket_get_all()
    else:
        tickets = await db.ticket_get_all(f_status)

    # فیلتر ورودی
    if f_intake != 'all':
        user_ids_in_intake = set()
        intake_users = await db.get_users_by_intake(f_intake)
        user_ids_in_intake = {u['user_id'] for u in intake_users}
        tickets = [t for t in tickets if t.get('user_id') in user_ids_in_intake]

    total  = len(tickets)
    open_c = sum(1 for t in tickets
                 if db.ticket_norm_status(t.get('status')) != 'closed')
    closed_c = total - open_c

    # دکمه‌های فیلتر وضعیت
    s_btns = [
        InlineKeyboardButton(
            f"{'✅' if f_status=='open' else '⬜'} 🟡 باز ({open_c})",
            callback_data='ticket:admin_filter:status:open'
        ),
        InlineKeyboardButton(
            f"{'✅' if f_status=='closed' else '⬜'} 🟢 بسته ({closed_c})",
            callback_data='ticket:admin_filter:status:closed'
        ),
        InlineKeyboardButton(
            f"{'✅' if f_status=='all' else '⬜'} 📂 همه ({total})",
            callback_data='ticket:admin_filter:status:all'
        ),
    ]

    # دکمه‌های فیلتر ورودی
    intakes = await db.get_all_intakes()
    i_btns  = [InlineKeyboardButton(
        f"{'✅' if f_intake=='all' else '⬜'} همه ورودی‌ها",
        callback_data='ticket:admin_filter:intake:all'
    )]
    for i in intakes:
        i_btns.append(InlineKeyboardButton(
            f"{'✅' if f_intake==i['code'] else '⬜'} {i['label']}",
            callback_data=f'ticket:admin_filter:intake:{i["code"]}'
        ))

    keyboard = [s_btns]
    # اگه ورودی‌ها زیاد بود، دو تا در هر ردیف
    for idx in range(0, len(i_btns), 2):
        keyboard.append(i_btns[idx:idx+2])

    # لیست تیکت‌ها
    _PICON = {'low': '🟢', 'normal': '⚪', 'high': '🟠', 'urgent': '🔴'}
    for t in tickets[:12]:
        icon = TICKET_STATUS_ICON.get(
            db.ticket_norm_status(t.get('status')), '🟡')
        rc   = len(t.get('replies', []))
        _pi = _PICON.get(t.get('priority', 'normal'), '⚪')
        _br = '🔴' if db.ticket_sla_info(t).get('breached') else ''
        keyboard.append([InlineKeyboardButton(
            f"{icon}{_br} #{t['ticket_id']} {_pi} | {t.get('user_name','')[:8]} | {t.get('subject','')[:14]} | {rc}💬",
            callback_data=f"ticket:admin_view:{t['ticket_id']}"
        )])

    keyboard.append([InlineKeyboardButton("🔍 جستجوی تیکت", callback_data='ticket:admin_search')])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data='admin:cat_comm')])

    await query.edit_message_text(
        f"🎫 <b>مدیریت تیکت‌ها</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🟡 باز: <b>{open_c}</b>  |  🟢 بسته: <b>{closed_c}</b>  |  📂 کل: <b>{total}</b>",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _search_tickets(update: Update, query_text: str):
    """جستجوی تیکت با شماره یا نام کاربر"""
    results = []

    # جستجو با شماره تیکت
    if query_text.isdigit():
        t = await db.ticket_get(int(query_text))
        if t:
            results = [t]
    else:
        # 🛡 AUDIT-P-9 — جست‌وجو در خودِ DB (ایندکس user_name) با سقف ۱۵؛
        # قبلاً روی ticket_get_all (۱۰۰ تیکت آخر) فیلتر می‌شد و هر تیکت
        # قدیمی‌تر عملاً «پیدا نشد» می‌گرفت.
        results = await db.ticket_search_name(query_text, limit=15)

    if not results:
        await update.message.reply_text(
            f"❌ نتیجه‌ای برای «{query_text}» پیدا نشد.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 مدیریت تیکت‌ها", callback_data='ticket:manage')
            ]])
        )
        return

    keyboard = []
    for t in results[:10]:
        icon = TICKET_STATUS_ICON.get(
            db.ticket_norm_status(t.get('status')), '🟡')
        keyboard.append([InlineKeyboardButton(
            f"{icon} #{t['ticket_id']} | {t.get('user_name','')} | {t.get('subject','')[:20]}",
            callback_data=f"ticket:admin_view:{t['ticket_id']}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='ticket:manage')])

    await update.message.reply_text(
        f"🔍 <b>{len(results)} نتیجه برای «{query_text}»:</b>",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ══════════════════════════════════════════════════
#  نمایش‌دهنده‌ها
# ══════════════════════════════════════════════════

async def _show_ticket_detail(query, ticket: dict, is_admin: bool):
    tid         = ticket['ticket_id']
    status      = db.ticket_norm_status(ticket.get('status'))
    status_icon = TICKET_STATUS_FA.get(status, '🟡 باز')
    replies     = ticket.get('replies', [])

    if is_admin:
        # اطلاعات کامل کاربری برای ادمین
        uid_t = ticket.get('user_id', '')
        user  = await db.get_user(uid_t) if uid_t else None
        intake = user.get('intake', '') if user else ''
        group  = user.get('group', '')  if user else ''
        sid    = user.get('student_id', '') if user else ''

        # 🌊 W8/UX-04 — اولویت/SLA/مسئول
        _prio = TICKET_PRIORITY_FA.get(ticket.get('priority', 'normal'), '⚪ عادی')
        _sla = db.ticket_sla_info(ticket)
        _sla_line = ''
        if _sla['sla_hours'] > 0:
            if _sla['responded']:
                _sla_line = f"⏱ SLA: ✅ پاسخ داده شده\n"
            elif _sla['breached']:
                _sla_line = "⏱ SLA: 🔴 <b>مهلت گذشته!</b>\n"
            else:
                _sla_line = f"⏱ SLA: تا {fmt_jalali_dt(_sla['due_at'])}\n"
        _assign = ticket.get('assignee_name') or '—'
        # 🌊 W9 — پرچم مسئول غیرفعال (بدون سلب خودکار)
        if ticket.get('assignee_id'):
            try:
                if not await db.ticket_assignee_ok(
                        ticket.get('assignee_id')):
                    _assign = f"{_assign} ⚠️(غیرفعال)"
            except Exception:
                pass
        text = (
            f"🎫 <b>تیکت #{tid}</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"👤 نام: <b>{ticket.get('user_name','')}</b>\n"
            f"🆔 آیدی: <code>{uid_t}</code>\n"
            f"🎓 شماره: {sid or '—'}\n"
            f"📅 ورودی: {intake or '—'}\n"
            f"👥 گروه: {group or '—'}\n"
            f"📋 موضوع: {_h(ticket.get('subject',''))}\n"
            f"🔘 وضعیت: {status_icon}\n"
            f"🥇 اولویت: {_prio}\n"
            f"{_sla_line}"
            f"👔 مسئول: {_h(_assign)}\n"
            f"📅 تاریخ ثبت: {fmt_jalali_dt(ticket['created_at'])}\n"
            f"━━━━━━━━━━━━━━━━\n\n"
            f"💬 <b>پیام اولیه:</b>\n{_h(ticket['message'])}\n"
        )
    else:
        text = (
            f"🎫 <b>تیکت #{tid}</b>\n"
            f"📋 {_h(ticket.get('subject',''))}\n"
            f"🔘 {status_icon}\n"
            f"🥇 {TICKET_PRIORITY_FA.get(ticket.get('priority', 'normal'), '⚪ عادی')}\n"
            f"📅 {fmt_jalali_dt(ticket['created_at'], with_time=False)}\n"
            f"━━━━━━━━━━━━━━━━\n\n"
            f"💬 <b>پیام شما:</b>\n{_h(ticket['message'])}\n"
        )

    # نمایش همه پاسخ‌ها
    if replies:
        text += f"\n━━━━━━━━━━━━━━━━\n💬 <b>ادامه گفتگو ({len(replies)}):</b>\n"
        for i, r in enumerate(replies, 1):
            at_str  = fmt_jalali_dt(r.get('at', ''), with_time=False) if r.get('at') else ''
            msg_txt = r.get('text', '')
            # تشخیص فرستنده
            if msg_txt.startswith('[دانشجو]'):
                sender = "🧑‍🎓"
                msg_txt = msg_txt[8:].strip()
            else:
                sender = "🎓 پشتیبانی"
            text += f"\n{sender}  <i>{at_str}</i>\n{_h(msg_txt)}\n"

    keyboard = []
    if is_admin:
        if status != 'closed':
            keyboard.append([InlineKeyboardButton("✏️ پاسخ جدید", callback_data=f'ticket:admin_reply:{tid}')])
            # 🌊 W8/UX-04 — تغییر سریع اولویت
            _cur = ticket.get('priority', 'normal')
            keyboard.append([
                InlineKeyboardButton(f"{'✅' if _cur == p else ''}{lbl}",
                                     callback_data=f'ticket:admin_prio:{tid}:{p}')
                for p, lbl in (('low', '🟢'), ('normal', '⚪'),
                               ('high', '🟠'), ('urgent', '🔴'))])
            # 🌊 W9 — تغییر سریع وضعیت (فقط گذارهای مجاز)
            _nxt = [s for s in db.TICKET_TRANSITIONS.get(status, ())
                    if s != 'closed']
            if _nxt:
                keyboard.append([
                    InlineKeyboardButton(
                        TICKET_STATUS_FA.get(s, s),
                        callback_data=f'ticket:admin_status:{tid}:{s}')
                    for s in _nxt])
            keyboard.append([InlineKeyboardButton("🔒 بستن تیکت",  callback_data=f'ticket:admin_close:{tid}')])
        else:
            # FIX جدید طبق سند: بازگشایی تیکت بسته‌شده
            keyboard.append([InlineKeyboardButton("🔓 بازگشایی تیکت", callback_data=f'ticket:admin_reopen:{tid}')])
        keyboard.append([InlineKeyboardButton("🔙 مدیریت تیکت‌ها", callback_data='ticket:manage')])
    else:
        if status != 'closed':
            keyboard.append([InlineKeyboardButton("💬 ادامه گفتگو", callback_data=f'ticket:reply_user:{tid}')])
        keyboard.append([InlineKeyboardButton("🔙 تیکت‌های من", callback_data='ticket:list')])

    try:
        await query.edit_message_text(
            text[:4090], parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        # 🛡 AUDIT-T1 — دو حالت قبلاً فقط «pass» می‌شد: (۱) محتوای یکسان
        # («message is not modified») که واقعاً بی‌ضرر است؛ (۲) خطای پارس
        # HTML وقتی برش ۴۰۹۰ کاراکتر یک تگ را نصف کرده یا متن کاربر
        # کاراکتر رزرو دارد. برای (۲) همان متن را بدون مارک‌آپ نشان می‌دهیم
        # تا تیکت باز شود، و ردپاش هم در لاگ می‌ماند (§۲۰).
        _msg = str(e)
        if 'not modified' in _msg.lower():
            return
        logger.warning(f"ticket view render failed (#{tid}): {_msg[:200]}")
        try:
            await query.edit_message_text(
                re.sub(r'<[^>]+>', '', text)[:4090],
                reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e2:
            logger.warning(f"ticket view fallback failed (#{tid}): {str(e2)[:200]}")


async def _ticket_main(query, uid: int):
    tickets    = await db.ticket_get_user(uid)
    open_count = sum(1 for t in tickets
                     if db.ticket_norm_status(t.get('status')) != 'closed')
    done_count = len(tickets) - open_count
    keyboard   = [
        [InlineKeyboardButton("🎫 ارسال تیکت جدید",            callback_data='ticket:new')],
        [InlineKeyboardButton(f"📋 تیکت‌های من ({len(tickets)})", callback_data='ticket:list')],
    ]
    if await _tperm(uid, 'tickets.manage'):
        open_t = await db.ticket_get_all('open')
        all_t  = await db.ticket_get_all()
        keyboard.append([InlineKeyboardButton(
            f"🎫 مدیریت تیکت‌ها ({len(open_t)} باز / {len(all_t)} کل)",
            callback_data='ticket:manage'
        )])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='dashboard:refresh')])
    await query.edit_message_text(
        f"🎫 <b>پشتیبانی</b>\n\n"
        f"🟡 باز: {open_count}  |  🟢 بسته‌شده: {done_count}\n\n"
        "برای ارسال مشکل یا سوال، تیکت جدید بزنید:",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _ticket_list(query, uid: int):
    tickets = await db.ticket_get_user(uid)
    if not tickets:
        await query.edit_message_text(
            "📋 هیچ تیکتی ندارید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎫 تیکت جدید", callback_data='ticket:new')],
                [InlineKeyboardButton("🔙 بازگشت",    callback_data='ticket:main')],
            ])
        )
        return
    keyboard = []
    for t in tickets[:12]:
        icon = TICKET_STATUS_ICON.get(
            db.ticket_norm_status(t.get('status')), '🟡')
        rc   = len(t.get('replies', []))
        status_str = TICKET_STATUS_FA.get(
            db.ticket_norm_status(t.get('status')), 'باز').split(' ', 1)[-1]
        keyboard.append([InlineKeyboardButton(
            f"{icon} #{t['ticket_id']} | {t.get('subject','')[:20]} | {status_str} | {rc} پیام",
            callback_data=f"ticket:view:{t['ticket_id']}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='ticket:main')])
    await query.edit_message_text(
        "📋 <b>تیکت‌های من</b>",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_ticket_main(message: Message, uid: int):
    tickets    = await db.ticket_get_user(uid)
    open_count = sum(1 for t in tickets
                     if db.ticket_norm_status(t.get('status')) != 'closed')
    done_count = len(tickets) - open_count
    keyboard   = [
        [InlineKeyboardButton("🎫 ارسال تیکت جدید",              callback_data='ticket:new')],
        [InlineKeyboardButton(f"📋 تیکت‌های من ({len(tickets)})", callback_data='ticket:list')],
    ]
    if await _tperm(uid, 'tickets.manage'):
        open_t = await db.ticket_get_all('open')
        all_t  = await db.ticket_get_all()
        keyboard.append([InlineKeyboardButton(
            f"🎫 مدیریت تیکت‌ها ({len(open_t)} باز / {len(all_t)} کل)",
            callback_data='ticket:manage'
        )])
    await message.reply_text(
        f"🎫 <b>پشتیبانی</b>\n\n"
        f"🟡 باز: {open_count}  |  🟢 بسته‌شده: {done_count}\n\n"
        "برای ارسال مشکل یا سوال، تیکت جدید بزنید:",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard)
    )
