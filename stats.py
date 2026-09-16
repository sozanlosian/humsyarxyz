"""
📊 آمار کاربر — با نمودار فعالیت هفتگی
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db
from utils import progress_bar, get_level

logger = logging.getLogger(__name__)


async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    uid    = update.effective_user.id
    action = query.data.split(':')[1] if ':' in query.data else 'main'

    if action == 'main':
        await _main_stats(query, uid)
    elif action == 'weekly':
        await _weekly(query, uid)
    elif action == 'weak':
        await _weak(query, uid)
    elif action == 'refresh':
        await _main_stats(query, uid)


async def _main_stats(query, uid: int):
    stats  = await db.user_stats(uid)
    user   = await db.get_user(uid)
    total  = stats['total_answers']
    correct = stats['correct_answers']
    wrong  = total - correct
    pct    = stats['percentage']
    bar    = progress_bar(pct)
    level  = get_level(pct)

    # 👑 Prestige در آمار — رنک + نوار پیشرفت ASCII + رکوردها + وضعیت چالش
    ps_line = ''
    try:
        _ps = await db.prestige_state(uid, lite=True)
        if _ps:
            ps_line = f"👑 رنک: <b>{_ps['icon']} {_ps['title']} {_ps['stars']}</b>\n"
            nxt = _ps.get('next') or {}
            ch = _ps.get('challenge') or {}
            if ch.get('mode') == 'ready':
                ps_line += (f"⚔️ چالش ارتقا آماده است: {ch.get('icon','')} "
                            f"{ch.get('title','')} — از مرکز آزمون!\n")
            elif ch.get('mode') == 'cooldown':
                ps_line += "⏳ چالش ارتقا در کول‌داون است — کمی دیگر برگرد.\n"
            elif ch.get('mode') == 'locked':
                ps_line += "🔒 چالش Apex هنوز قفل است (پیش‌شرط‌های اجتماعی).\n"
            elif nxt.get('span'):
                from utils import progress_bar as _pbar
                have = int(nxt.get('have') or 0)
                span = max(1, int(nxt.get('span') or 1))
                ps_line += (f"<code>[{_pbar(min(100, round(have / span * 100)), 12)}]"
                            f"</code> {have}/{span}\n")
            rec = _ps.get('records') or {}
            rec_bits = [f"🔥 بهترین استریک <b>{_ps['streak']['best']}</b>"]
            if rec.get('best_exam_pct'):
                rec_bits.append(f"🎯 بهترین آزمون <b>{rec['best_exam_pct']}٪</b>")
            if rec.get('top1_weeks_best'):
                rec_bits.append(f"👑 صدر هفته ×<b>{rec['top1_weeks_best']}</b>")
            if rec.get('apex_wins'):
                rec_bits.append(f"🌌 برد Apex ×<b>{rec['apex_wins']}</b>")
            ps_line += "🏆 رکوردها: " + " · ".join(rec_bits) + "\n"
    except Exception:
        ps_line = ''

    text = (
        f"📊 <b>آمار من</b>\n"
        f"👤 {user.get('name', '')} | گروه {user.get('group', '')}\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"🏅 سطح: <b>{level}</b>\n"
        f"{ps_line}\n"
        f"📊 آمادگی: <code>[{bar}]</code> <b>{pct}%</b>\n"
        f"✅ صحیح: <b>{correct}</b>  ❌ اشتباه: <b>{wrong}</b>\n"
        f"📥 دانلود: <b>{stats['downloads']}</b>\n"
        f"🔥 فعالیت هفتگی: <b>{stats['week_activity']}</b>\n"
        f"⚡ نقاط ضعف: <b>{len(stats['weak_topics'])}</b> مبحث"
    )
    keyboard = [
        [
            InlineKeyboardButton("📅 فعالیت هفتگی", callback_data='stats:weekly'),
            InlineKeyboardButton("⚡ نقاط ضعف",      callback_data='stats:weak'),
        ],
        [InlineKeyboardButton("🔄 بروزرسانی",        callback_data='stats:refresh')],
        [InlineKeyboardButton("🔙 داشبورد",           callback_data='dashboard:refresh')],
    ]
    await query.edit_message_text(
        text, parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _weekly(query, uid: int):
    """
    FIX باگ مهم: progress_bar(pct, length, fill, empty) انتظار
    pct در بازه ۰-۱۰۰ دارد، اما اینجا count خام (نه درصد) پاس
    داده می‌شد و عدد ۱۰ به‌جای آرگومان length در جای fill (که
    باید رشته باشد) می‌نشست — همین باعث خطای int+str می‌شد.
    حالا درصد واقعی نسبت به max_val محاسبه و پاس داده می‌شود؛
    و مقادیر غیرعددی هم با int() ایمن می‌شوند (طبق پیشنهاد سند).
    """
    data    = await db.weekly_activity(uid)
    # FIX: تبدیل ایمن به int برای جلوگیری از خطای نوع داده
    safe_data = []
    for date_str, count in data:
        try:
            safe_data.append((date_str, int(count)))
        except (TypeError, ValueError):
            safe_data.append((date_str, 0))
    data = safe_data

    max_val = max((d[1] for d in data), default=1) or 1
    lines   = ["📅 <b>فعالیت ۷ روز گذشته</b>\n"]
    total   = 0
    for date_str, count in data:
        pct    = (count / max_val) * 100 if max_val else 0
        bar    = progress_bar(pct, 10)
        marker = "◀" if count == max_val and count > 0 else ""
        lines.append(f"<code>{date_str}</code>: {bar} <b>{count}</b> {marker}")
        total += count
    lines.append(f"\n📊 مجموع: <b>{total}</b> عمل")

    await query.edit_message_text(
        '\n'.join(lines),
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 بازگشت", callback_data='stats:main')
        ]])
    )


async def _weak(query, uid: int):
    user = await db.get_user(uid)
    weak = user.get('weak_topics', []) if user else []

    if not weak:
        text = "🎉 <b>هیچ نقطه ضعفی ندارید!</b>\nبیشتر تمرین کنید."
    else:
        lines = ["⚡ <b>نقاط ضعف شما:</b>\n"]
        for i, t in enumerate(weak, 1):
            lines.append(f"{i}. ❌ {t}")
        lines.append("\n💡 روی این مباحث بیشتر تمرین کنید.")
        text = '\n'.join(lines)

    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ تمرین نقاط ضعف", callback_data='questions:weak')],
            [InlineKeyboardButton("🔙 بازگشت",           callback_data='stats:main')],
        ])
    )
