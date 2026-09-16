# -*- coding: utf-8 -*-
"""💳 W14 — پیگیری پرداخت نیمه‌تمام درگاه (dunning).

- دو گام پیش‌فرض: ۱ ساعت و ۲۴ ساعت بعد از ساخت رسید زرین‌پال.
- ارسال فقط با کلید روشن + خارج از ساعات سکوت + claim اتمیک (بدون دابل‌سند).
- پرداختِ کامل/منقضی‌شده خودکار از صف می‌افتد (چک status در claim).
"""
import logging
import time as _time

import growth_rules as gr
from database import db

logger = logging.getLogger(__name__)

CB = 'dun:'
TICK_NAME = 'dunning_tick'


async def dun_config() -> dict:
    try:
        stored = await db.get_setting('dun_cfg', None)
    except Exception:
        stored = None
    return gr.merge_dun_config(stored if isinstance(stored, dict) else None)


def build_message(doc: dict, step_idx: int) -> str:
    """متن یادآوری (خالص؛ پیاده‌سازی در growth_rules برای تست‌پذیری)."""
    return gr.dunning_message(doc, step_idx)


async def dunning_job(context) -> dict:
    """تیک زمان‌بندی‌شده (هر ۱۰ دقیقه). خلاصه برمی‌گرداند؛ هرگز raise."""
    out = {'ok': True, 'sent': 0, 'skipped': '', 'errors': 0}
    try:
        cfg = await dun_config()
        if not cfg['enabled']:
            out['skipped'] = 'disabled'
            return out
        now = _time.time()
        if gr.in_quiet_hours(gr.tehran_hour(now),
                             cfg['quiet_start'], cfg['quiet_end']):
            out['skipped'] = 'quiet_hours'
            return out
        steps = gr.dun_steps(cfg)
        pendings = await db.dun_recent_pending()
        due = gr.dunning_due(pendings, now, steps)
        if not due:
            return out
        from utils import safe_send
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        for doc, idx in due:
            pid = str(doc.get('_id'))
            # claim اتمیک (شامل چک still-pending داخل کوئری)
            if not await db.dun_mark_sent(pid, idx):
                continue
            uid = int(doc.get('user_id') or 0)
            if not uid:
                continue
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton('💳 ادامه‌ی پرداخت',
                                      callback_data=f'dun:resume:{pid}')],
                [InlineKeyboardButton('🧾 وضعیت اشتراک من',
                                      callback_data='sub:my_status')],
            ])
            try:
                ok = await safe_send(context.bot, uid,
                                     build_message(doc, idx),
                                     parse_mode='HTML', reply_markup=kb)
            except Exception as e:
                logger.warning('dunning send failed pid=%s: %s', pid, e)
                ok = False
            if ok:
                out['sent'] += 1
            else:
                out['errors'] += 1
        if out['sent'] or out['errors']:
            logger.info('dunning tick: sent=%d errors=%d',
                        out['sent'], out['errors'])
        return out
    except Exception as e:
        logger.warning('dunning_job failed: %s', e)
        out['ok'] = False
        out['skipped'] = 'error'
        return out


async def dunning_click(update, context) -> None:
    """کلیک «ادامه‌ی پرداخت» → ثبت کلیک + واگذاری به فلو verify موجود."""
    query = update.callback_query
    uid = update.effective_user.id
    pid = (query.data or '')[len('dun:resume:'):]
    try:
        from bson import ObjectId
        doc = await db.sub_payments.find_one({'_id': ObjectId(pid)})
    except Exception:
        doc = None
    if not doc:
        try:
            await query.answer('پرداخت پیدا نشد.', show_alert=True)
        except Exception:
            pass
        return
    if int(doc.get('user_id') or 0) != uid:
        try:
            await query.answer('این پرداخت متعلق به شما نیست.', show_alert=True)
        except Exception:
            pass
        return
    try:
        await db.dun_log_click(pid)
    except Exception:
        pass
    # استفاده‌ی مجدد از منطق verify (approved/expired را خودش مدیریت می‌کند)
    try:
        from subscription import _zarinpal_check
        await _zarinpal_check(query, context, uid,
                              doc.get('zarinpal_authority') or '')
    except Exception as e:
        logger.warning('dunning_click delegate failed: %s', e)
        try:
            await query.answer('خطا — دوباره تلاش کن.', show_alert=True)
        except Exception:
            pass
