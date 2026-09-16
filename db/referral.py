# -*- coding: utf-8 -*-
"""🌱 W13/W14 — میکسین رشد: ریفرال (دعوت) + پیگیری پرداخت نیمه‌تمام.

- ریفرال: کد یکتا per-user + جدول referrals + اعطای جایزه‌ی idempotent.
- پیگیری: claim اتمیک گام‌های dunning روی sub_payments (بدون دابل‌سند).
- همه‌ی رفتارها از settings (`ref_cfg` / `dun_cfg`) خوانده می‌شوند؛
  پیش‌فرض همه‌چیز خاموش است (زیرساخت policy-ready، مطابق اصل W7).
"""
import logging
import time as _time

import growth_rules as gr
from time_utils import utc_now_iso

logger = logging.getLogger('database')

try:
    from pymongo.errors import DuplicateKeyError
except Exception:  # pragma: no cover
    DuplicateKeyError = Exception


class DBReferral:
    # ── کد دعوت ────────────────────────────────────────
    async def ref_ensure_code(self, uid: int) -> str:
        """کد دعوت یکتای کاربر (ساخت تنبل، مقاوم به race)."""
        u = await self.users.find_one({'user_id': int(uid)}, {'ref_code': 1})
        if u and u.get('ref_code'):
            return u['ref_code']
        for _ in range(8):
            code = gr.make_ref_code()
            try:
                res = await self.users.update_one(
                    {'user_id': int(uid),
                     '$or': [{'ref_code': {'$exists': False}},
                             {'ref_code': None}, {'ref_code': ''}]},
                    {'$set': {'ref_code': code}})
                if res.modified_count:
                    return code
                u = await self.users.find_one({'user_id': int(uid)},
                                              {'ref_code': 1})
                if u and u.get('ref_code'):
                    return u['ref_code']
            except DuplicateKeyError:
                continue  # کد تکراری — یکی دیگر بساز
        # آخرین تلاش: خواندن (race برنده شده؟)
        u = await self.users.find_one({'user_id': int(uid)}, {'ref_code': 1})
        return (u or {}).get('ref_code') or ''

    async def ref_get_user_by_code(self, code: str):
        code = gr.normalize_ref_code(code)
        if not code:
            return None
        return await self.users.find_one({'ref_code': code})

    # ── ثبت دعوت (attribution) ─────────────────────────
    async def ref_get_by_invitee(self, invitee_id: int):
        return await self.referrals.find_one({'invitee_id': int(invitee_id)})

    async def ref_record(self, inviter_id: int, invitee_id: int,
                         source: str = 'bot') -> dict | None:
        """ثبت رابطه‌ی دعوت. idempotent: هر invitee فقط یک inviter (اولی می‌برد).

        برمی‌گرداند: سند referrals، یا None اگر نامعتبر (خوددعوتی/ناشناس).
        توجه: ثبت attribution همیشه انجام می‌شود (حتی با کلید خاموش)؛
        اعطای جایزه جداگانه و گیت‌شده است.
        """
        inviter_id, invitee_id = int(inviter_id), int(invitee_id)
        if inviter_id == invitee_id:
            return None
        ex = await self.ref_get_by_invitee(invitee_id)
        if ex:
            return ex
        inviter = await self.users.find_one({'user_id': inviter_id},
                                            {'user_id': 1})
        if not inviter:
            return None
        now_iso = utc_now_iso()
        now_ts = _time.time()
        cfg = gr.merge_ref_config(await self.get_setting('ref_cfg', None))
        # ضدتقلب: انفجار (N دعوت در M دقیقه) → flagged (جایزه نگه داشته می‌شود)
        status, flag_reason = 'counted', ''
        try:
            recent = await self.referrals.find(
                {'inviter_id': inviter_id}).sort('created_at', -1).to_list(
                    max(2, int(cfg['burst_n']) + 1))
            times = [gr.parse_iso_ts(d.get('created_at')) for d in recent]
            if gr.burst_flagged(times + [now_ts], now_ts,
                                int(cfg['burst_n']),
                                int(cfg['burst_minutes']) * 60):
                status, flag_reason = 'flagged', 'burst'
        except Exception as e:
            logger.warning('ref burst check failed: %s', e)
        # ضدتقلب: سقف روزانه/ماهانه → capped (ثبت می‌شود، جایزه نه)
        if status == 'counted':
            try:
                day_start = now_ts - 86400
                mon_start = now_ts - 30 * 86400
                docs = await self.referrals.find(
                    {'inviter_id': inviter_id}).sort(
                        'created_at', -1).to_list(
                            max(2, int(cfg['cap_monthly']) + 2))
                ts = [t for t in
                      (gr.parse_iso_ts(d.get('created_at')) for d in docs) if t]
                if sum(1 for t in ts if t >= day_start) >= max(1, int(cfg['cap_daily'])):
                    status, flag_reason = 'capped', 'daily_cap'
                elif sum(1 for t in ts if t >= mon_start) >= max(1, int(cfg['cap_monthly'])):
                    status, flag_reason = 'capped', 'monthly_cap'
            except Exception as e:
                logger.warning('ref cap check failed: %s', e)
        doc = {
            'inviter_id': inviter_id, 'invitee_id': invitee_id,
            'source': source if source in ('bot', 'miniapp') else 'bot',
            'status': status, 'flag_reason': flag_reason,
            'created_at': now_iso,
            'reward_register': False, 'reward_buy': False,
            'invitee_first_buy_at': None,
            'granted': {},
        }
        try:
            r = await self.referrals.insert_one(doc)
            doc['_id'] = r.inserted_id
        except DuplicateKeyError:
            # race دو ثبت هم‌زمان برای یک invitee — اولی برد
            return await self.ref_get_by_invitee(invitee_id)
        try:
            # first-wins روی سند کاربر هم (برای کوئری سریع)
            await self.users.update_one(
                {'user_id': invitee_id,
                 '$or': [{'referred_by': {'$exists': False}},
                         {'referred_by': None}, {'referred_by': 0}]},
                {'$set': {'referred_by': inviter_id}})
        except Exception:
            pass
        return doc

    # ── بازبینی دستی ───────────────────────────────────
    async def ref_set_status(self, ref_id: str, status: str,
                             admin_id: int = 0) -> dict | None:
        """تغییر وضعیت توسط ادمین (approve/reject). سند به‌روز را برمی‌گرداند."""
        from bson import ObjectId
        if status not in ('counted', 'rejected'):
            return None
        try:
            oid = ObjectId(ref_id)
        except Exception:
            return None
        doc = await self.referrals.find_one({'_id': oid})
        if not doc or doc.get('status') not in ('flagged', 'capped', 'counted'):
            return doc
        await self.referrals.update_one(
            {'_id': oid},
            {'$set': {'status': status,
                      'reviewed_by': int(admin_id or 0),
                      'reviewed_at': utc_now_iso()}})
        doc['status'] = status
        return doc

    # ── اعطای جایزه (idempotent per trigger) ────────────
    async def ref_grant(self, ref_doc: dict, trigger: str) -> dict:
        """اعطای جایزه‌های فعال برای یک تریگر ('register' | 'buy').

        - فقط وقتی کلید اصلی روشن است و وضعیت counted است.
        - هر تریگر حداکثر یک‌بار (claim اتمیک روی فلگ).
        - شکست یک جایزه بقیه را متوقف نمی‌کند؛ خلاصه برمی‌گردد (هرگز raise).
        """
        out = {'granted': {}, 'skipped': [], 'errors': {}}
        try:
            if trigger not in ('register', 'buy'):
                return out
            if not isinstance(ref_doc, dict) or not ref_doc.get('_id'):
                return out
            if ref_doc.get('status') != 'counted':
                out['skipped'].append('not_counted')
                return out
            cfg = gr.merge_ref_config(await self.get_setting('ref_cfg', None))
            if not cfg['enabled']:
                out['skipped'].append('disabled')
                return out
            timing = cfg['timing']
            if timing == 'on_register' and trigger != 'register':
                out['skipped'].append('timing')
                return out
            if timing == 'on_first_buy' and trigger != 'buy':
                out['skipped'].append('timing')
                return out
            # claim اتمیک: فقط یک گرانت موفق per trigger
            flag = f'reward_{trigger}'
            res = await self.referrals.update_one(
                {'_id': ref_doc['_id'], flag: {'$ne': True}},
                {'$set': {flag: True}})
            if res.modified_count != 1:
                out['skipped'].append('already')
                return out
            inviter = int(ref_doc['inviter_id'])
            rw = cfg['rewards']
            is_split = (timing == 'split')
            # سهم این تریگر از هر جایزه‌ی عددی
            todo = {}
            for key in ('sub_days', 'wallet'):
                spec = rw.get(key) or {}
                if not spec.get('on') or int(spec.get('amount') or 0) <= 0:
                    continue
                amt = int(spec['amount'])
                if is_split:
                    first, second = gr.split_amounts(amt)
                    amt = first if trigger == 'register' else second
                if amt > 0:
                    todo[key] = amt
            # غیرعددی‌ها: در split موقع register (پاداش خوش‌آمد)،
            # در بقیه‌ی حالت‌ها موقع همان تریگر فعال
            if (not is_split) or trigger == 'register':
                for key in ('discount', 'xp'):
                    spec = rw.get(key) or {}
                    if spec.get('on') and int(spec.get('amount') or 0) > 0:
                        todo[key] = int(spec['amount'])
            granted = {}
            if 'sub_days' in todo:
                try:
                    end = await self.sub_activate(
                        inviter, todo['sub_days'], '🎁 جایزه دعوت',
                        source='referral', extend=True)
                    granted['sub_days'] = {'days': todo['sub_days'],
                                           'end_date': end}
                except Exception as e:
                    out['errors']['sub_days'] = str(e)[:160]
            if 'wallet' in todo:
                try:
                    from db.wallet import TX_REFERRAL_CREDIT
                    tx = await self.wallet_credit(
                        inviter, todo['wallet'], TX_REFERRAL_CREDIT,
                        'referral', f"{ref_doc['_id']}:{trigger}",
                        0, '🎁 جایزه دعوت دوستان')
                    granted['wallet'] = {
                        'amount': todo['wallet'],
                        'balance_after': tx.get('balance_after')}
                except Exception as e:
                    out['errors']['wallet'] = str(e)[:160]
            if 'discount' in todo:
                try:
                    import secrets as _secrets
                    code = (f"REF{inviter}-"
                            f"{''.join(_secrets.choice('ABCDEFGHJKMNPQRSTUVWXYZ23456789') for _ in range(4))}")
                    ok = await self.discount_add(
                        code, todo['discount'], max_uses=1,
                        per_user_limit=1, created_by=0)
                    if ok:
                        granted['discount'] = {'code': code,
                                               'percent': todo['discount']}
                    else:
                        out['errors']['discount'] = 'code_collision'
                except Exception as e:
                    out['errors']['discount'] = str(e)[:160]
            if 'xp' in todo:
                try:
                    await self.prestige_event(
                        inviter, 'referral', {'xp': todo['xp']})
                    granted['xp'] = {'xp': todo['xp']}
                except Exception as e:
                    out['errors']['xp'] = str(e)[:160]
            out['granted'] = granted
            try:
                await self.referrals.update_one(
                    {'_id': ref_doc['_id']},
                    {'$set': {f'granted.{trigger}': granted}})
            except Exception:
                pass
            return out
        except Exception as e:  # هرگز مسیر پول/ثبت‌نام را نشکن
            logger.exception('ref_grant failed: %s', e)
            out['errors']['fatal'] = str(e)[:160]
            return out

    # ── اولین خرید invitee ─────────────────────────────
    async def ref_mark_first_buy(self, invitee_id: int):
        """ثبت اولین خرید دعوت‌شده (idempotent) + برگرداندن سند دعوت."""
        doc = await self.ref_get_by_invitee(int(invitee_id))
        if not doc or doc.get('invitee_first_buy_at'):
            return doc
        await self.referrals.update_one(
            {'_id': doc['_id'], 'invitee_first_buy_at': None},
            {'$set': {'invitee_first_buy_at': utc_now_iso()}})
        doc['invitee_first_buy_at'] = utc_now_iso()
        return doc

    # ── فهرست و آمار ───────────────────────────────────
    async def ref_list(self, inviter_id: int = 0, status: str = '',
                       skip: int = 0, limit: int = 20) -> list:
        q = {}
        if inviter_id:
            q['inviter_id'] = int(inviter_id)
        if status:
            q['status'] = status
        cur = self.referrals.find(q).sort('created_at', -1).skip(
            max(0, int(skip))).limit(max(1, min(100, int(limit))))
        return await cur.to_list(length=100)

    async def ref_count(self, inviter_id: int = 0, status: str = '') -> int:
        q = {}
        if inviter_id:
            q['inviter_id'] = int(inviter_id)
        if status:
            q['status'] = status
        return await self.referrals.count_documents(q)

    async def ref_inviter_stats(self, inviter_id: int) -> dict:
        docs = await self.referrals.find(
            {'inviter_id': int(inviter_id)}).to_list(length=5000)
        by_status = {}
        earned = {'sub_days': 0, 'wallet': 0, 'discount': 0, 'xp': 0}
        for d in docs:
            by_status[d.get('status', '?')] = by_status.get(
                d.get('status', '?'), 0) + 1
            for leg in (d.get('granted') or {}).values():
                if not isinstance(leg, dict):
                    continue
                if 'sub_days' in leg:
                    earned['sub_days'] += int(
                        (leg['sub_days'] or {}).get('days', 0))
                if 'wallet' in leg:
                    earned['wallet'] += int(
                        (leg['wallet'] or {}).get('amount', 0))
                if 'discount' in leg:
                    earned['discount'] += 1
                if 'xp' in leg:
                    earned['xp'] += int((leg['xp'] or {}).get('xp', 0))
        return {'total': len(docs), 'by_status': by_status,
                'earned': earned,
                'awaiting_buy': sum(
                    1 for d in docs
                    if d.get('status') == 'counted'
                    and d.get('reward_register')
                    and not d.get('reward_buy'))}

    async def ref_global_stats(self) -> dict:
        total = await self.referrals.count_documents({})
        counted = await self.referrals.count_documents({'status': 'counted'})
        flagged = await self.referrals.count_documents({'status': 'flagged'})
        capped = await self.referrals.count_documents({'status': 'capped'})
        rejected = await self.referrals.count_documents({'status': 'rejected'})
        bought = await self.referrals.count_documents(
            {'invitee_first_buy_at': {'$ne': None}})
        return {'total': total, 'counted': counted, 'flagged': flagged,
                'capped': capped, 'rejected': rejected,
                'first_buys': bought}

    # ── پیگیری پرداخت (dunning) ────────────────────────
    async def dun_recent_pending(self, limit: int = 500) -> list:
        """رسیدهای زرین‌پالِ درانتظار (انتخاب نهایی در dunning.py، خالص)."""
        cur = self.sub_payments.find(
            {'status': 'zarinpal_pending'}).sort(
                'submitted_at', 1).limit(max(1, min(2000, int(limit))))
        return await cur.to_list(length=2000)

    async def dun_mark_sent(self, pid, step_idx: int) -> bool:
        """claim اتمیک ارسال گام: فقط اگر هنوز pending است و گام ارسال نشده.

        هم race تیک‌های هم‌زمان را می‌بندد، هم پرداختِ این‌چنددقیقه
        کامل‌شده را خودکار از صف می‌اندازد (بدون نیاز به re-fetch)."""
        from bson import ObjectId
        try:
            oid = pid if isinstance(pid, ObjectId) else ObjectId(str(pid))
        except Exception:
            return False
        try:
            res = await self.sub_payments.update_one(
                {'_id': oid, 'status': 'zarinpal_pending',
                 'dunning_sent': {'$ne': int(step_idx)}},
                {'$addToSet': {'dunning_sent': int(step_idx)},
                 '$set': {f'dunning_sent_at.{int(step_idx)}': utc_now_iso()}})
            return res.modified_count == 1
        except Exception:
            return False

    async def dun_log_click(self, pid) -> None:
        from bson import ObjectId
        try:
            oid = pid if isinstance(pid, ObjectId) else ObjectId(str(pid))
        except Exception:
            return
        try:
            await self.sub_payments.update_one(
                {'_id': oid},
                {'$inc': {'dunning_clicks': 1},
                 '$set': {'dunning_last_click': utc_now_iso()}})
        except Exception:
            pass

    async def dun_stats(self) -> dict:
        sent = await self.sub_payments.count_documents(
            {'dunning_sent': {'$exists': True, '$ne': []}})
        clicks_agg = await self.sub_payments.aggregate([
            {'$match': {'dunning_clicks': {'$gt': 0}}},
            {'$group': {'_id': None, 'clicks': {'$sum': '$dunning_clicks'},
                        'n': {'$sum': 1}}},
        ]).to_list(length=2)
        clicks = (clicks_agg[0]['clicks'] if clicks_agg else 0) or 0
        clicked_n = (clicks_agg[0]['n'] if clicks_agg else 0) or 0
        # تقریبیِ مستند: approvedهایی که قبلاً یادآوری گرفته‌اند
        paid_after = await self.sub_payments.count_documents(
            {'status': 'approved', 'dunning_sent': {'$exists': True,
                                                   '$ne': []}})
        pending_now = await self.sub_payments.count_documents(
            {'status': 'zarinpal_pending'})
        return {'reminded': sent, 'clicks': clicks,
                'clicked_payments': clicked_n,
                'paid_after_reminder': paid_after,
                'pending_now': pending_now}
