"""
🩺 داشبورد — با فراخوانی موازی دیتابیس برای سرعت
  ✅ نمایش ورودی + گروه
  ✅ جدول برترین‌ها
"""
import os
import asyncio
import logging
from utils import esc as escape   # 🛡 AUDIT-A6 —escape مرکزی
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db
from time_utils import parse_gregorian_date
from utils import progress_bar, get_rank, exam_countdown, now_tehran

logger   = logging.getLogger(__name__)
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))


async def build_dashboard_text(uid: int) -> tuple:
    # The user's group is needed before loading exams so students never see
    # another group's schedule. Other independent queries still run in parallel.
    user = await db.get_user(uid)
    if not user:
        return "❌ کاربر پیدا نشد.", None

    stats, exams, new_res, donation_enabled, donation_link = await asyncio.gather(
        db.user_stats(uid),
        db.upcoming_exams(7, group=str(user.get('group', '') or '')),
        db.new_resources_count(7),
        db.get_setting('donation_enabled', False),
        db.get_setting('donation_link', None),
    )

    open_tickets = 0
    try:
        tickets = await db.ticket_get_user(uid)
        open_tickets = sum(1 for t in tickets if t.get('status') == 'open')
    except Exception:
        pass

    exam_lines = []
    today = now_tehran().date()
    for e in (exams or [])[:2]:
        try:
            exam_date = parse_gregorian_date(e.get('date'))
            days = max(0, (exam_date - today).days)
            exam_lines.append(
                f"  📝 {e.get('lesson', '')} — {exam_countdown(days)}"
            )
        except (TypeError, ValueError):
            exam_lines.append(f"  📝 {e.get('lesson', '')}")
    exam_text = '\n'.join(exam_lines) if exam_lines else "  ✅ امتحانی نزدیک نیست"

    weak     = stats['weak_topics'][:3]
    weak_str = '، '.join(weak) if weak else 'ندارید 🎉'
    pct      = stats['percentage']
    bar      = progress_bar(pct)
    rank     = get_rank(stats['correct_answers'])
    act      = stats['week_activity']
    act_stars = '🔥' * min(act // 3, 5) if act > 0 else '💤'

    notif_s       = user.get('notification_settings', {})
    # 🧩 N3-fix — NOTIF_ITEMS قدیمی از notifications.py حذف شده
    # بود و این import کرش می‌داد. منبع واحد = کاتالوگ db؛ شمارش
    # با کلیدهای Canonical (PREF_ALIAS داخل notif_pref_on کلید
    # قدیمیِ ذخیره‌شده‌ی کاربر را خودکار ترجمه می‌کند).
    notif_total   = len(db.NOTIF_CATALOG)
    defaults      = await db.get_notif_defaults()
    active_notifs = sum(1 for k, _label, _desc, _d in db.NOTIF_CATALOG
                        if db.notif_pref_on(notif_s, k, defaults))
    group_icon    = "1️⃣" if str(user.get('group', '')) == '1' else "2️⃣"
    role          = user.get('role', 'student')
    role_badge    = (
        " | 👑 ادمین" if uid == ADMIN_ID
        else " | 🎓 ادمین محتوا" if role == 'content_admin'
        else ""
    )

    intake      = user.get('intake', '') or '—'
    sid_line    = f"🎓 {user.get('student_id', '')}\n" if user.get('student_id') else ""

    # 👑 موج P2 — خط Prestige با رتبه‌ی عددی/Top٪ + وضعیت چالش
    prestige_line = ''
    try:
        _ps = await db.prestige_state(uid)
        if _ps:
            rank_bit = ''
            if _ps.get('rank_number') and _ps.get('total_active'):
                rank_bit = (f"  ·  🏆 #{_ps['rank_number']}"
                            f" (Top {_ps.get('top_pct')}٪)")
            ch = _ps.get('challenge') or {}
            ch_bit = ''
            if ch.get('mode') == 'ready':
                ch_bit = (f"\n⚔️ چالش ارتقا آماده است: {ch.get('icon','')} "
                          f"{ch.get('title','')} — مرکز آزمون!")
            elif ch.get('mode') == 'cooldown':
                ch_bit = "\n⏳ چالش ارتقا در کول‌داون است."
            prestige_line = (
                f"{_ps['icon']} <b>{_ps['title']} {_ps['stars']}</b>"
                f"  ·  🔥 {_ps['streak']['current']} روز{rank_bit}"
                f"  ·  {_ps['next']['label']}{ch_bit}\n\n"
            )
    except Exception:
        prestige_line = ''

    text = (
        f"🩺 <b>داشبورد — {user['name']}</b>{role_badge}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 ورودی: <b>{intake}</b>  |  👥 گروه {group_icon}\n"
        f"{sid_line}\n"
        f"{prestige_line}"
        f"📊 <b>آمادگی تستی</b>\n"
        f"  {bar} <b>{pct}%</b>  {rank}\n\n"
        f"📈 <b>آمار من</b>\n"
        f"  🧪 سوال: <b>{stats['total_answers']}</b>  "
        f"✅ صحیح: <b>{stats['correct_answers']}</b>  "
        f"📥 دانلود: <b>{stats['downloads']}</b>\n"
        f"  {act_stars} فعالیت این هفته: <b>{act}</b> بار\n\n"
        f"⏳ <b>امتحانات پیش رو</b>\n{exam_text}\n\n"
        f"⚡ <b>نقاط ضعف:</b> {weak_str}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📚 منابع جدید این هفته: <b>{new_res}</b>  "
        f"🔔 اعلان‌های فعال: <b>{active_notifs}/{notif_total}</b>"
    )
    if open_tickets:
        text += f"\n🎫 تیکت‌های باز: <b>{open_tickets}</b>"

    keyboard = [
        [
            InlineKeyboardButton("🔄 بروزرسانی",    callback_data='dashboard:refresh'),
            InlineKeyboardButton("📊 آمار کامل",     callback_data='stats:main'),
        ],
        [
            InlineKeyboardButton("🧪 تمرین هوشمند", callback_data='questions:weak'),
            InlineKeyboardButton("🏆 جدول برترین",  callback_data='dashboard:leaderboard'),
        ],
        [
            InlineKeyboardButton("🔔 اعلان‌ها",     callback_data='notif:main'),
            InlineKeyboardButton("🎫 پشتیبانی",     callback_data='ticket:main'),
        ],
    ]
    if donation_enabled and donation_link:
        keyboard.append([
            InlineKeyboardButton("💙 حمایت مالی", url=donation_link),
        ])
    if uid == ADMIN_ID:
        keyboard.append([
            InlineKeyboardButton("👨‍⚕️ پنل ادمین",  callback_data='admin:main'),
            InlineKeyboardButton("📡 وضعیت ربات",   callback_data='admin:bot_status'),
        ])

    return text, InlineKeyboardMarkup(keyboard)


async def _build_leaderboard_text(uid: int) -> tuple:
    """
    FIX طبق سند: طراحی قبلی شلوغ بود (گروه + ورودی + جزئیات زیاد
    در هر سطر). حالا مینیمال — فقط نام، کسر صحیح/کل، درصد.
    """
    leaders = await db.get_leaderboard(10)
    lines   = ["🏆 <b>جدول برترین‌ها</b>\n━━━━━━━━━━━━━━━━\n"]
    medals  = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']
    for i, u in enumerate(leaders):
        # 🏷 Identity v1 — نام نمایشی (لقب؟لقب:نام واقعی)، سینک با مینی‌اپ
        name    = escape(db.display_name_of(u) or 'کاربر')
        correct = int(u.get('correct_answers', 0) or 0)
        total   = int(u.get('total_answers', 0) or 0)
        pct     = round(correct / total * 100) if total > 0 else 0
        marker  = " 👈" if u.get('user_id') == uid else ""
        lines.append(f"{medals[i]} <b>{name}</b>{marker}")
        lines.append(f"     {correct}/{total} صحیح  •  {pct}%\n")
    text = '\n'.join(lines)
    kb   = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 بازگشت", callback_data='dashboard:refresh')
    ]])
    return text, kb


async def dashboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    uid    = update.effective_user.id
    action = query.data.split(':')[1] if ':' in query.data else 'refresh'

    if action == 'leaderboard':
        text, kb = await _build_leaderboard_text(uid)
    else:
        text, kb = await build_dashboard_text(uid)

    try:
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=kb)
    except Exception:
        await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=kb)
