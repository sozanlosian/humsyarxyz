"""
👤 پروفایل کاربر
  ✅ FIX: ویرایش نام بدون ConversationHandler — با mode در unified_text_handler
  ✅ ویرایش شماره دانشجویی
  ✅ ویرایش گروه و ورودی
"""
import os
import logging
from utils import esc as escape   # 🛡 AUDIT-A6 —escape مرکزی
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import ContextTypes, ConversationHandler
from database import db
from utils import send_audit_log
from utils import progress_bar, get_rank, fmt_jalali_dt

logger   = logging.getLogger(__name__)
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
PROFILE_EDIT_WAITING = 70  # نگه داشته برای سازگاری با bot.py


def _profile_text(user: dict, stats: dict, open_tickets: int, sub_line: str = '') -> str:
    role_map = {
        'student':       '🧑‍🎓 دانشجو',
        'content_admin': '🎓 ادمین محتوا',
        'admin':         '👑 ادمین',
    }
    role_icon = role_map.get(user.get('role', 'student'), '🧑‍🎓 دانشجو')
    rank      = get_rank(stats.get('correct_answers', 0))
    pct       = stats.get('percentage', 0)
    bar       = progress_bar(pct)
    reg_date  = fmt_jalali_dt(user.get('registered_at', ''), with_time=False) or 'نامشخص'
    uname     = f"@{user['username']}" if user.get('username') else '—'
    sid       = user.get('student_id', '') or '—'
    intake    = user.get('intake', '') or 'ثبت نشده'

    # 🏷 Identity v1 — لقب + حریم نمایش نام واقعی (سینک با مینی‌اپ)
    nick      = (user.get('nickname') or '').strip()
    show_real = user.get('show_real_name') is not False
    nick_line = escape(nick) if nick else '«ثبت نشده»'
    priv_line = ('نام واقعی هم دیده می‌شود 👁'
                 if show_real else 'فقط لقب دیده می‌شود 🔒')

    return (
        "👤 <b>پروفایل من</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"📛 <b>نام:</b>  {user.get('name', '')}\n"
        f"🏷 <b>لقب:</b>  {nick_line}\n"
        f"👁 <b>نمایش عمومی:</b>  {priv_line}\n"
        f"🎓 <b>شماره دانشجویی:</b>  {sid}\n"
        f"📅 <b>ورودی:</b>  {intake}\n"
        f"👥 <b>گروه:</b>  گروه {user.get('group', '')}\n"
        f"📱 <b>یوزرنیم:</b>  {uname}\n"
        f"🎭 <b>نقش:</b>  {role_icon}\n"
        f"📅 <b>ثبت‌نام:</b>  {reg_date}\n"
        + (f"{sub_line}" if sub_line else "") +
        "\n"
        "━━━━━━━━━━━━━━━━\n"
        "📊 <b>آمار تحصیلی</b>\n\n"
        f"🧪 سوال پاسخ داده: <b>{stats.get('total_answers', 0)}</b>\n"
        f"✅ پاسخ صحیح: <b>{stats.get('correct_answers', 0)}</b>\n"
        f"📈 درصد موفقیت: <b>{pct}%</b>\n"
        f"<code>[{bar}]</code>\n\n"
        f"📥 دانلودها: <b>{stats.get('downloads', 0)}</b>\n"
        f"🔥 فعالیت هفتگی: <b>{stats.get('week_activity', 0)}</b>\n"
        f"🎫 تیکت باز: <b>{open_tickets}</b>\n\n"
        "━━━━━━━━━━━━━━━━\n"
        f"🏅 <b>رتبه:</b>  {rank}\n"
    )


async def _profile_keyboard(user: dict = None) -> InlineKeyboardMarkup:
    # 🏷 Identity v1 — برچسب سوییچ حریم از سند کاربر (سینک با مینی‌اپ)
    show_real = (user or {}).get('show_real_name') is not False
    priv_btn  = InlineKeyboardButton(
        "🔒 پنهان‌سازی نام واقعی" if show_real else "👁 نمایش نام واقعی",
        callback_data='profile:toggle_privacy')
    rows = [
        [
            InlineKeyboardButton("✏️ ویرایش نام",          callback_data='profile:edit_name'),
            InlineKeyboardButton("🎓 ویرایش شماره دانشجویی", callback_data='profile:edit_sid'),
        ],
        [
            InlineKeyboardButton("🏷 تغییر لقب", callback_data='profile:edit_nick'),
            priv_btn,
        ],
        [
            InlineKeyboardButton("👥 تغییر گروه",  callback_data='profile:edit_group'),
            InlineKeyboardButton("📅 تغییر ورودی", callback_data='profile:edit_intake'),
        ],
        # FIX جدید: دسترسی به جزئیات کامل اشتراک از پروفایل
        # 🌊 W6.2 — کیف پول (موجودی + شارژ + خرید) مستقیم از پروفایل
        [
            InlineKeyboardButton("💰 کیف پول", callback_data='sub:wallet'),
            InlineKeyboardButton("🧾 جزئیات اشتراک", callback_data='sub:my_status'),
        ],
        # 👑 Prestige — دسترسی سریع به نشان‌ها و سفر رقابتی
        [
            InlineKeyboardButton("🏅 نشان‌های من", callback_data='profile:badges'),
            InlineKeyboardButton("📜 سفر من",      callback_data='profile:journey'),
        ],
        [InlineKeyboardButton("🔄 بروزرسانی",     callback_data='profile:refresh')],
        [InlineKeyboardButton("🔙 داشبورد",        callback_data='dashboard:refresh')],
    ]
    # 🌱 W13 — دعوت دوستان (فقط وقتی کلید ریفرال روشن است)
    try:
        from referral import is_enabled as _ref_on
        if await _ref_on():
            rows.insert(-2, [InlineKeyboardButton('🎁 دعوت دوستان',
                                                  callback_data='ref:menu')])
    except Exception:
        pass
    return InlineKeyboardMarkup(rows)


async def _get_profile_data(uid: int) -> tuple:
    user    = await db.get_user(uid)
    stats   = await db.user_stats(uid)
    tickets = await db.ticket_get_user(uid)
    open_t  = sum(1 for t in tickets if t.get('status') == 'open')
    return user, stats, open_t


# ══════════════════════════════════════════════════
#  Callback
# ══════════════════════════════════════════════════

async def profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    uid    = update.effective_user.id
    parts  = query.data.split(':')
    action = parts[1] if len(parts) > 1 else 'main'

    if action in ('main', 'refresh'):
        user, stats, open_t = await _get_profile_data(uid)
        if not user:
            await query.edit_message_text("❌ کاربر پیدا نشد.")
            return
        from subscription import sub_status_line
        sub_line = await sub_status_line(uid)
        await query.edit_message_text(
            _profile_text(user, stats, open_t, sub_line),
            parse_mode='HTML',
            reply_markup=await _profile_keyboard(user)
        )

    # ── 👑 Prestige: ۶ نشان اخیر (Spec v3 — منوی پروفایل) ──
    elif action == 'badges':
        user = await db.get_user(uid) or {}
        ach = user.get('achievements') or {}
        recent = sorted(
            ((k, str((v or {}).get('at', ''))) for k, v in ach.items()),
            key=lambda kv: kv[1], reverse=True)[:6]
        lines = []
        for k, _at in recent:
            try:
                m = db._badge_meta(k, user)
            except Exception:
                m = None
            if not m:
                continue
            t = f"{m['icon']} <b>{m['title']}</b>"
            if m.get('tiers_count'):
                t += f" — پله {m.get('tier', 0)}/{m['tiers_count']}"
            lines.append(t)
        text = (
            "🏅 <b>نشان‌های من</b>\n"
            "━━━━━━━━━━━━━━━━\n\n"
            + ("\n".join(lines)
               if lines else "هنوز نشانی نداری — اولین پاسخ‌ت را بده! 🌱")
            + f"\n\nمجموع نشان‌ها: <b>{len(ach)}</b>"
            + "\nکلکسیون کامل در مینی‌اپ: بخش «نشان‌های من»"
        )
        await query.edit_message_text(
            text, parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 پروفایل", callback_data='profile:main')]]))

    # ── 👑 Prestige: ۵ رویداد اخیر سفر رقابتی ──
    elif action == 'journey':
        try:
            rows = await db.prestige_history_list(uid, 5)
        except Exception:
            rows = []
        lines = []
        for r in rows or []:
            bit = f"▫️ {r.get('title', '')}"
            if r.get('at_jalali'):
                bit += f"\n   <i>{r['at_jalali']}</i>"
            lines.append(bit)
        text = (
            "📜 <b>سفر من</b>\n"
            "━━━━━━━━━━━━━━━━\n\n"
            + ("\n\n".join(lines)
               if lines else "هنوز رویدادی ثبت نشده — شروع کن! ⚡")
            + "\n\nتایم‌لاین کامل در مینی‌اپ: بخش «نشان‌های من»"
        )
        await query.edit_message_text(
            text, parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 پروفایل", callback_data='profile:main')]]))

    # ── FIX: ویرایش نام با mode — نه ConversationHandler ──
    elif action == 'edit_name':
        context.user_data['profile_edit'] = 'name'
        context.user_data['mode']         = 'profile_edit'
        await query.edit_message_text(
            "✏️ <b>ویرایش نام</b>\n\n"
            "نام و نام خانوادگی جدید خود را بنویسید:\n"
            "<i>مثال: علی احمدی</i>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ لغو", callback_data='profile:cancel_edit')
            ]])
        )

    elif action == 'edit_sid':
        context.user_data['profile_edit'] = 'student_id'
        context.user_data['mode']         = 'profile_edit'
        await query.edit_message_text(
            "🎓 <b>ویرایش شماره دانشجویی</b>\n\n"
            "شماره دانشجویی خود را وارد کنید:",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ لغو", callback_data='profile:cancel_edit')
            ]])
        )

    # ── 🏷 Identity v1: ویرایشگر لقب (سینک با مینی‌اپ — همان db.set_nickname) ──
    elif action == 'edit_nick':
        user = await db.get_user(uid) or {}
        nick = (user.get('nickname') or '').strip()
        st   = await db.nickname_status(uid, user)
        cfg  = await db.get_identity_config()
        buttons = []
        if nick:
            buttons.append([InlineKeyboardButton(
                "🗑 حذف لقب", callback_data='profile:clear_nick')])
        if not st['can_change_nickname']:
            # Cooldown فعال — فقط حذف آزاد است (مثل مینی‌اپ)
            next_fa = fmt_jalali_dt(
                st['next_change_at'] or '', with_time=False) or '—'
            buttons.append([InlineKeyboardButton(
                "🔙 بازگشت", callback_data='profile:main')])
            await query.edit_message_text(
                "🏷 <b>لقب</b>\n"
                "━━━━━━━━━━━━━━━━\n\n"
                f"لقب فعلی: <b>{escape(nick) or '—'}</b>\n\n"
                f"⏳ تغییر بعدی لقب از <b>{next_fa}</b> ممکن می‌شود.\n"
                "<i>حذف لقب همیشه آزاد است.</i>",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(buttons))
            return
        context.user_data['profile_edit'] = 'nickname'
        context.user_data['mode']         = 'profile_edit'
        mn  = int(cfg.get('min_length', 3))
        mx  = int(cfg.get('max_length', 24))
        cd  = int(cfg.get('cooldown_days', 30))
        buttons.append([InlineKeyboardButton(
            "❌ لغو", callback_data='profile:cancel_edit')])
        await query.edit_message_text(
            "🏷 <b>تغییر لقب</b>\n"
            "━━━━━━━━━━━━━━━━\n\n"
            f"لقب فعلی: <b>{escape(nick) if nick else '—'}</b>\n\n"
            "لقب جدید را بنویسید:\n"
            f"▫️ {mn} تا {mx} نویسه — فارسی/انگلیسی/عدد\n"
            "▫️ لینک، شماره تماس و آیدی تلگرام ممنوع\n"
            f"▫️ پس از تغییر، تا {cd} روز قفل می‌شود!\n\n"
            "<i>نام واقعی در نمره، حضور و گزارش‌ها همیشه"
            " ثابت می‌ماند.</i>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(buttons))

    elif action == 'clear_nick':
        ok, err, info = await db.set_nickname(
            uid, '', changed_by='user', reason='ربات تلگرام')
        if ok:
            try:
                _u = await db.get_user(uid)
                _role = await db.get_actor_role_label(uid)
                await send_audit_log(context.bot, 'user', (_u or {}).get('name', str(uid)), uid, "پاکسازی لقب (ربات)", module='Profile', severity='INFO', actor_role=_role, target_id=str(uid), target_type='user', target_label=(_u or {}).get('name',''), after={"nickname": ""}, tags=['لقب', 'ربات'])
            except Exception:
                pass
        await query.answer(
            "✅ لقب پاک شد؛ نام واقعی نمایش داده می‌شود."
            if ok else f"⚠️ {db.nick_error_text(err, info)}",
            show_alert=True)
        user, stats, open_t = await _get_profile_data(uid)
        await query.edit_message_text(
            _profile_text(user, stats, open_t),
            parse_mode='HTML',
            reply_markup=await _profile_keyboard(user))

    # ── 🏷 Identity v1: سوییچ نمایش اسم واقعی (همان فیلد مینی‌اپ) ──
    elif action == 'toggle_privacy':
        user     = await db.get_user(uid) or {}
        was_on   = user.get('show_real_name') is not False
        await db.set_show_real_name(uid, not was_on)
        try:
            _u2 = await db.get_user(uid)
            _role2 = await db.get_actor_role_label(uid)
            await send_audit_log(context.bot, 'user', (_u2 or {}).get('name', str(uid)), uid, "تغییر حریم خصوصی نام (ربات)", module='Profile', severity='INFO', actor_role=_role2, target_id=str(uid), target_type='user', target_label=(_u2 or {}).get('name',''), before={"show_real_name": was_on}, after={"show_real_name": not was_on}, tags=['حریم', 'ربات'])
        except Exception:
            pass
        await query.answer(
            "🔒 در فضای عمومی فقط لقب نمایش داده می‌شود."
            if was_on else
            "👁 نام واقعی هم نمایش داده می‌شود.",
            show_alert=True)
        user, stats, open_t = await _get_profile_data(uid)
        await query.edit_message_text(
            _profile_text(user, stats, open_t),
            parse_mode='HTML',
            reply_markup=await _profile_keyboard(user))

    elif action == 'cancel_edit':
        context.user_data.pop('profile_edit', None)
        context.user_data.pop('mode', None)
        user, stats, open_t = await _get_profile_data(uid)
        await query.edit_message_text(
            _profile_text(user, stats, open_t),
            parse_mode='HTML',
            reply_markup=await _profile_keyboard(user)
        )

    elif action == 'edit_group':
        user = await db.get_user(uid)
        current_group = user.get('group', '') if user else ''
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{'✅ ' if current_group == '1' else ''}1️⃣ گروه ۱",
                    callback_data='profile:set_group:1'
                ),
                InlineKeyboardButton(
                    f"{'✅ ' if current_group == '2' else ''}2️⃣ گروه ۲",
                    callback_data='profile:set_group:2'
                ),
            ],
            [InlineKeyboardButton("🔙 بازگشت", callback_data='profile:main')],
        ]
        await query.edit_message_text(
            f"👥 <b>تغییر گروه درسی</b>\n\n"
            f"گروه فعلی: <b>گروه {current_group or 'تعیین نشده'}</b>\n\n"
            "گروه جدید خود را انتخاب کنید:",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif action == 'set_group' and len(parts) > 2:
        new_group = parts[2]
        _before_g = (await db.get_user(uid) or {}).get('group', '')
        await db.update_user(uid, {'group': new_group})
        try:
            _u3 = await db.get_user(uid)
            _role3 = await db.get_actor_role_label(uid)
            await send_audit_log(context.bot, 'user', (_u3 or {}).get('name', str(uid)), uid, "ویرایش گروه (ربات)", module='Profile', severity='INFO', actor_role=_role3, target_id=str(uid), target_type='user', target_label=(_u3 or {}).get('name',''), before={"group": _before_g}, after={"group": new_group}, tags=['گروه', 'ربات'])
        except Exception:
            pass
        await query.answer(f"✅ گروه به {new_group} تغییر یافت!", show_alert=True)
        user, stats, open_t = await _get_profile_data(uid)
        await query.edit_message_text(
            _profile_text(user, stats, open_t),
            parse_mode='HTML',
            reply_markup=await _profile_keyboard(user)
        )

    elif action == 'edit_intake':
        intakes = await db.get_active_intakes()
        user    = await db.get_user(uid)
        current = user.get('intake', '') if user else ''
        if not intakes:
            await query.answer("❌ هیچ ورودی‌ای تعریف نشده!", show_alert=True)
            return
        keyboard = []
        for i in intakes:
            active = current == i['code']
            keyboard.append([InlineKeyboardButton(
                f"{'✅ ' if active else ''}{i['label']}",
                callback_data=f'profile:set_intake:{i["code"]}'
            )])
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='profile:main')])
        await query.edit_message_text(
            f"📅 <b>تغییر ورودی تحصیلی</b>\n\n"
            f"ورودی فعلی: <b>{current or 'ثبت نشده'}</b>\n\n"
            "ورودی جدید خود را انتخاب کنید:",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif action == 'set_intake' and len(parts) > 2:
        new_intake = parts[2]
        intakes    = await db.get_all_intakes()
        label      = next((i['label'] for i in intakes if i['code'] == new_intake), new_intake)
        _before_i = (await db.get_user(uid) or {}).get('intake', '')
        await db.update_user(uid, {'intake': new_intake})
        try:
            _u4 = await db.get_user(uid)
            _role4 = await db.get_actor_role_label(uid)
            await send_audit_log(context.bot, 'user', (_u4 or {}).get('name', str(uid)), uid, "ویرایش ورودی (ربات)", module='Profile', severity='INFO', actor_role=_role4, target_id=str(uid), target_type='user', target_label=(_u4 or {}).get('name',''), before={"intake": _before_i}, after={"intake": new_intake}, tags=['ورودی', 'ربات'])
        except Exception:
            pass
        await query.answer(f"✅ ورودی به {label} تغییر یافت!", show_alert=True)
        user, stats, open_t = await _get_profile_data(uid)
        await query.edit_message_text(
            _profile_text(user, stats, open_t),
            parse_mode='HTML',
            reply_markup=await _profile_keyboard(user)
        )


# ══════════════════════════════════════════════════
#  FIX: هندلر متن پروفایل — بدون ConversationHandler
#  فراخوانی از unified_text_handler در bot.py
# ══════════════════════════════════════════════════

async def profile_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    FIX: این تابع از unified_text_handler فراخوانی میشه
    وقتی mode == 'profile_edit' باشه
    """
    uid   = update.effective_user.id
    field = context.user_data.get('profile_edit', '')
    text  = update.message.text.strip()

    if not field:
        return

    if field == 'name':
        if len(text) < 3:
            await update.message.reply_text("⚠️ نام باید حداقل ۳ حرف باشد. مجدد وارد کنید:")
            return
        if len(text) > 50:
            await update.message.reply_text("⚠️ نام نباید بیشتر از ۵۰ حرف باشد:")
            return
        _before_n = (await db.get_user(uid) or {}).get('name', '')
        await db.update_user(uid, {'name': text})
        try:
            _role5 = await db.get_actor_role_label(uid)
            await send_audit_log(context.bot, 'user', text, uid, "ویرایش نام (ربات)", module='Profile', severity='INFO', actor_role=_role5, target_id=str(uid), target_type='user', target_label=text, before={"name": _before_n}, after={"name": text}, tags=['نام', 'ربات'])
        except Exception:
            pass
        context.user_data.pop('profile_edit', None)
        context.user_data.pop('mode', None)
        await update.message.reply_text(
            f"✅ نام به <b>{text}</b> تغییر یافت!",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("👤 مشاهده پروفایل", callback_data='profile:main')
            ]])
        )

    elif field == 'student_id':
        if len(text) < 5:
            await update.message.reply_text("⚠️ شماره دانشجویی نامعتبر است. مجدد وارد کنید:")
            return
        _before_sid = (await db.get_user(uid) or {}).get('student_id', '')
        await db.update_user(uid, {'student_id': text})
        try:
            _u6 = await db.get_user(uid)
            _role6 = await db.get_actor_role_label(uid)
            await send_audit_log(context.bot, 'user', (_u6 or {}).get('name', str(uid)), uid, "ویرایش شماره دانشجویی (ربات)", module='Profile', severity='INFO', actor_role=_role6, target_id=str(uid), target_type='user', target_label=(_u6 or {}).get('name',''), before={"student_id": _before_sid}, after={"student_id": text}, tags=['شماره_دانشجویی', 'ربات'])
        except Exception:
            pass
        context.user_data.pop('profile_edit', None)
        context.user_data.pop('mode', None)
        await update.message.reply_text(
            f"✅ شماره دانشجویی <code>{text}</code> ثبت شد!",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("👤 مشاهده پروفایل", callback_data='profile:main')
            ]])
        )

    # 🏷 Identity v1 — ورود متن لقب (Validation همان db — سینک با مینی‌اپ)
    elif field == 'nickname':
        ok, err, info = await db.set_nickname(
            uid, text, changed_by='user', reason='ربات تلگرام')
        if ok:
            try:
                _u7 = await db.get_user(uid)
                _role7 = await db.get_actor_role_label(uid)
                await send_audit_log(context.bot, 'user', (_u7 or {}).get('name', str(uid)), uid, "ثبت لقب (ربات)", module='Profile', severity='INFO', actor_role=_role7, target_id=str(uid), target_type='user', target_label=(_u7 or {}).get('name',''), after={"nickname": info.get('nickname')}, tags=['لقب', 'ربات'])
            except Exception:
                pass
        if not ok:
            await update.message.reply_text(
                f"⚠️ {db.nick_error_text(err, info)}\n\n"
                "دوباره بنویسید یا «❌ لغو» را بزنید:")
            return
        context.user_data.pop('profile_edit', None)
        context.user_data.pop('mode', None)
        if info.get('nickname'):
            msg = (
                f"✅ لقب ثبت شد: <b>{escape(info['nickname'])}</b>\n\n"
                "از این پس در رتبه‌بندی، فید و نشان‌ها همین نام دیده می‌شود.\n"
                "<i>نام واقعی در نمره و گزارش‌ها ثابت می‌ماند.</i>"
            )
        else:
            msg = "✅ لقب پاک شد؛ نام واقعی نمایش داده می‌شود."
        await update.message.reply_text(
            msg,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("👤 مشاهده پروفایل", callback_data='profile:main')
            ]])
        )
    else:
        context.user_data.pop('profile_edit', None)
        context.user_data.pop('mode', None)


async def show_profile_msg(update: Update):
    uid             = update.effective_user.id
    user, stats, open_t = await _get_profile_data(uid)
    if not user:
        await update.message.reply_text("❌ کاربر پیدا نشد.")
        return
    from subscription import sub_status_line
    sub_line = await sub_status_line(uid)
    await update.message.reply_text(
        _profile_text(user, stats, open_t, sub_line),
        parse_mode='HTML',
        reply_markup=await _profile_keyboard(user)
    )
