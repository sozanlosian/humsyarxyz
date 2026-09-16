# -*- coding: utf-8 -*-
"""🌱 W13 — ریفرال (دعوت دوستان + جایزه).

- attribution در هر دو مسیر ثبت‌نام (ربات/مینی‌اپ)؛ جایزه فقط با کلید روشن.
- جایزه‌ها: روز اشتراک / شارژ کیف / کد تخفیف اختصاصی / XP پرستیژ.
- زمان پرداخت: on_register | on_first_buy | split (نصف‌نصف).
- همه‌ی خطاها داخلی مهار می‌شوند: ریفرال هرگز ثبت‌نام/پرداخت را نمی‌شکند.
"""
import logging
import os

import growth_rules as gr
from database import db

logger = logging.getLogger(__name__)

CB = 'ref:'


# ── کانفیگ ──────────────────────────────────────────────
async def ref_config() -> dict:
    try:
        stored = await db.get_setting('ref_cfg', None)
    except Exception:
        stored = None
    return gr.merge_ref_config(stored if isinstance(stored, dict) else None)


async def is_enabled() -> bool:
    return bool((await ref_config())['enabled'])


async def invite_link_for(uid: int) -> tuple:
    """(کد، لینک) دعوت کاربر. مستقل از کلید (نمایش، جای دیگر گیت می‌شود)."""
    code = await db.ref_ensure_code(int(uid))
    bot_username = (os.environ.get('BOT_USERNAME') or '').strip().lstrip('@')
    return code, (gr.ref_link(bot_username, code) if bot_username and code else '')


# ── attribution (موقع ثبت‌نام) ──────────────────────────
async def attribute(invitee_id: int, raw_code, source: str = 'bot'):
    """ثبت دعوت + اعطای احتمالی لگ register. همیشه exception-safe."""
    try:
        code = gr.parse_ref_start_arg(raw_code)
        if not code:
            return None
        inviter = await db.ref_get_user_by_code(code)
        if not inviter:
            return None
        doc = await db.ref_record(int(inviter['user_id']), int(invitee_id),
                                  source)
        if not doc:
            return None
        cfg = await ref_config()
        if cfg['enabled'] and cfg['timing'] in ('on_register', 'split'):
            res = await db.ref_grant(doc, 'register')
            if res.get('granted'):
                await notify_inviter(int(inviter['user_id']), res['granted'],
                                     'register')
        return doc
    except Exception as e:
        logger.warning('referral.attribute failed: %s', e)
        return None


# ── اولین خرید (هوک از finalize_approved_payment) ───────
async def on_first_payment(payer_id: int):
    """تریگر لگ buy برای دعوت‌شده‌ای که اولین خرید واقعی را کرد."""
    try:
        doc = await db.ref_mark_first_buy(int(payer_id))
        if not doc:
            return None
        cfg = await ref_config()
        if cfg['enabled'] and cfg['timing'] in ('on_first_buy', 'split'):
            res = await db.ref_grant(doc, 'buy')
            if res.get('granted'):
                await notify_inviter(int(doc['inviter_id']), res['granted'],
                                     'buy')
            return res
        return {'granted': {}, 'skipped': ['timing_or_disabled']}
    except Exception as e:
        logger.warning('referral.on_first_payment failed: %s', e)
        return None


# ── اعلان جایزه ─────────────────────────────────────────
async def notify_inviter(inviter_id: int, granted: dict, trigger: str) -> None:
    try:
        desc = gr.describe_granted(granted)
        if not desc:
            return
        when = 'ثبت‌نام دوستت' if trigger == 'register' else \
            'اولین خرید دوستت'
        await db.inbox_add(
            int(inviter_id), 'referral_reward',
            '🎁 جایزه دعوت رسید!',
            f'به‌خاطر {when} این جوایز به حسابت اضافه شد:\n{desc}',
            link='/me/profile')
    except Exception as e:
        logger.warning('referral.notify failed: %s', e)


# ── هندلر ربات (namespace: ref:) ────────────────────────
async def referral_callback(update, context) -> None:
    """نمایش لینک/آمار دعوت. با کلید خاموش → پیام به‌زودی."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    query = update.callback_query
    uid = update.effective_user.id
    data = (query.data or '')[len(CB):]
    try:
        if not await is_enabled():
            await query.answer('بخش دعوت دوستان به‌زودی فعال می‌شود 🌱',
                               show_alert=True)
            return
        code, link = await invite_link_for(uid)
        stats = await db.ref_inviter_stats(uid)
        earned = stats.get('earned') or {}
        by_status = stats.get('by_status') or {}
        text = (
            '🎁 <b>دعوت دوستان</b>\n'
            '━━━━━━━━━━━━━━━━\n'
            f'🔗 لینک دعوت تو:\n<code>{link or "—"}</code>\n\n'
            f'👥 دعوت‌شده‌ها: <b>{stats.get("total", 0)}</b> '
            f'(✅ {by_status.get("counted", 0)}'
            f' · ⏳ {stats.get("awaiting_buy", 0)} در انتظار خرید)\n'
            f'🏆 مجموع جوایزت: {int(earned.get("sub_days", 0))} روز اشتراک، '
            f'{int(earned.get("wallet", 0)):,} تومان، '
            f'{int(earned.get("xp", 0))} XP\n\n'
            '<i>دوستت با لینکت ثبت‌نام کنه، هر دو جایزه می‌گیرید 🎉</i>'
        )
        buttons = []
        if link:
            from urllib.parse import quote
            share = ('https://t.me/share/url?url=' + quote(link, safe='') +
                     '&text=' + quote('با این لینک تو هامزیار ثبت‌نام کن 🎓',
                                      safe=''))
            buttons.append([InlineKeyboardButton('📤 اشتراک‌گذاری لینک',
                                                 url=share)])
        buttons.append([InlineKeyboardButton('🔄 بروزرسانی',
                                             callback_data='ref:menu')])
        await query.edit_message_text(text, parse_mode='HTML',
                                      reply_markup=InlineKeyboardMarkup(
                                          buttons))
    except Exception as e:
        logger.warning('referral_callback failed: %s', e)
        try:
            await query.answer('خطا — دوباره تلاش کن.', show_alert=True)
        except Exception:
            pass
