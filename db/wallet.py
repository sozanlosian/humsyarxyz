# -*- coding: utf-8 -*-
"""
💰 HUMSYAR — WALLET SUBSYSTEM (🌊 W6)

کیف پول داخلی = یک زیرسیستم مالی واقعی، نه یک عدد روی User:

    Wallet Ledger (wallet_transactions)  ←  منبع حقیقت مالی
              ↓
    Cached Balance (wallets.balance)     ←  بهینه‌سازی عملکرد

قوانین حسابداری (همه با شواهد معماری موجود هماهنگ‌اند):
- مبالغ integer و به «تومان» — همان واحد sub_payments (بدون float).
- هر تغییر موجودی یک تراکنش مستقل و **تغییرناپذیر** است؛ اصلاح فقط با
  compensating transaction (type='reversal')، هرگز overwrite.
- Idempotency با unique index روی (reference_type, reference_id):
  دابل‌کلیک/ری‌تری = یک اثر اقتصادی.
- الگوی insert-first: اول تراکنش `pending` با کلید یکتا درج می‌شود، بعد
  موجودی اتمیک اعمال می‌شود، بعد تراکنش `ok` می‌شود. کرش بین مراحل =
  تراکنش pendingِ قابل‌شناسایی در مغایرت‌گیری، نه اثر اقتصادی دوباره.
- Debit اتمیک و شرطی: `balance >= amount` داخل خودِ update — دو خرید
  هم‌زمان روی موجودی یکسان، فقط یکی برنده می‌شود.
- Ledger هرگز حذف نمی‌شود (data retention مالی).

استاندارد پول: تومان (int) — یکسان در Bot / Mini App / Web Admin / API.
"""
import os
import logging
from pymongo.errors import DuplicateKeyError
from bson import ObjectId
from time_utils import utc_now_iso

logger = logging.getLogger('database')

# واحد پول سراسری — از معماری موجود استخراج شده (plan.price تومان int است)
WALLET_CURRENCY = 'تومان'
# 🌊 W2 — thresholds (Toman)
WALLET_DAILY_LIMIT = int(os.getenv("WALLET_DAILY_LIMIT", "5000000") or 5000000)
WALLET_LARGE_THRESHOLD = int(os.getenv("WALLET_LARGE_THRESHOLD", "2000000") or 2000000)
try:
    WALLET_OWNER_ID = int(os.getenv("ADMIN_ID", "0") or 0)
except:
    WALLET_OWNER_ID = 0

# انواع تراکنش — فقط آنچه واقعاً لازم است
TX_REFUND_CREDIT = 'refund_credit'
TX_SUB_PURCHASE = 'subscription_purchase'
TX_ADMIN_CREDIT = 'admin_credit'
TX_ADMIN_DEBIT = 'admin_debit'
TX_REVERSAL = 'reversal'
# 🌊 W6.2 — شارژ کیف پول با رسید بانکی (تأیید ادمین → اعتبار)
TX_TOPUP = 'topup_credit'
TX_REFERRAL_CREDIT = 'referral_credit'  # 🌱 W13 — جایزه دعوت

_TX_LABELS = {
    TX_REFUND_CREDIT: 'بازگشت وجه',
    TX_SUB_PURCHASE: 'خرید اشتراک با کیف پول',
    TX_ADMIN_CREDIT: 'افزایش موجودی توسط ادمین',
    TX_ADMIN_DEBIT: 'کسر موجودی توسط ادمین',
    TX_REVERSAL: 'اصلاح مالی (جبران تراکنش قبلی)',
    TX_TOPUP: 'شارژ کیف پول',
    TX_REFERRAL_CREDIT: 'جایزه دعوت دوستان',
}

def _wallet_need_owner_approval(amount: int, tx_type: str, actor_id: int) -> bool:
    if tx_type not in (TX_ADMIN_CREDIT, TX_ADMIN_DEBIT):
        return False
    if amount <= WALLET_LARGE_THRESHOLD:
        return False
    if WALLET_OWNER_ID and int(actor_id) == WALLET_OWNER_ID:
        return False
    return True

# عمر آستانه‌ی تراکنش pending برای پرچم‌خوردن در مغایرت‌گیری (ثانیه)
_STUCK_PENDING_SECONDS = 600


class WalletError(ValueError):
    """خطای مالی کیف پول با کد ماشین‌خوان + پیام فارسی برای کاربر."""

    def __init__(self, code: str, message: str = ''):
        self.code = code
        super().__init__(message or code)


class DBWallet:
    """Mixin کیف پول — همان الگوی DBFinance (بدون سیستم مالی موازی)."""

    # 🌊 W2 — helper داخل کلاس
    async def _wallet_daily_toman_sum(self, user_id: int) -> int:
        """جمع امروز (ok) برای کاربر — تومان."""
        from time_utils import start_of_day_tehran
        try:
            day_start = start_of_day_tehran().isoformat()
        except Exception:
            import datetime
            day_start = datetime.datetime.now(datetime.timezone.utc).isoformat()
        total = 0
        async for row in self.wallet_transactions.aggregate([
            {'$match': {'user_id': int(user_id), 'status': 'ok', 'created_at': {'$gte': day_start}}},
            {'$group': {'_id': None, 's': {'$sum': '$amount'}}}]):
            total = int(row['s'])
        return total

    # ── پروویژن ────────────────────────────────────────────────
    async def wallet_get_or_create(self, user_id: int) -> dict:
        """کیف پول یکتا per کاربر، idempotent و امن زیر هم‌زمانی:
        unique index روی user_id + گرفتن DuplicateKeyError و خواندن مجدد."""
        user_id = int(user_id)
        w = await self.wallets.find_one({'user_id': user_id})
        if w:
            return w
        try:
            await self.wallets.insert_one({
                'user_id': user_id, 'balance': 0,
                'currency': WALLET_CURRENCY,
                'created_at': utc_now_iso(), 'updated_at': utc_now_iso()})
        except DuplicateKeyError:
            pass  # request هم‌زمان ساخت — همان یک wallet معتبر است
        w = await self.wallets.find_one({'user_id': user_id})
        if not w:
            raise WalletError('wallet_provision_failed',
                              'ساخت کیف پول ممکن نشد')
        return w

    # ── هسته‌ی ledger ──────────────────────────────────────────
    async def _wallet_tx_insert_pending(self, user_id, amount, tx_type,
                                        ref_type, ref_id, actor_id, label):
        """درج تراکنش pending با کلید یکتا (ref_type, ref_id).
        خروجی: (tx_dict, is_new). is_new=False یعنی قبلاً ثبت شده (ری‌تری)."""
        doc = {
            'user_id': int(user_id), 'type': tx_type,
            'direction': 'credit' if tx_type in (
                TX_REFUND_CREDIT, TX_ADMIN_CREDIT, TX_REVERSAL,
                TX_TOPUP) else 'debit',
            'amount': int(amount), 'currency': WALLET_CURRENCY,
            'reference_type': ref_type, 'reference_id': str(ref_id),
            'balance_before': None, 'balance_after': None,
            'label': (label or _TX_LABELS.get(tx_type, tx_type))[:120],
            'actor_id': int(actor_id or 0),
            'status': 'pending', 'created_at': utc_now_iso(),
        }
        try:
            r = await self.wallet_transactions.insert_one(doc)
            doc['_id'] = r.inserted_id
            return doc, True
        except DuplicateKeyError:
            existing = await self.wallet_transactions.find_one(
                {'reference_type': ref_type, 'reference_id': str(ref_id)})
            if not existing:
                raise WalletError('tx_key_conflict',
                                  'کلید تراکنش مالی تکراری است')
            return existing, False

    async def _wallet_apply(self, wallet, tx, delta: int) -> dict:
        """اعمال اتمیک delta روی موجودی + ثبت before/after روی تراکنش.
        برای debit از شرط `balance >= amount` در خودِ query استفاده می‌شود؛
        اگر شرط نگرفت، تراکنش `failed` می‌شود و WalletError برمی‌گردانیم
        (موجودی دست‌نخورده می‌ماند)."""
        if delta < 0:
            updated = await self.wallets.find_one_and_update(
                {'_id': wallet['_id'], 'balance': {'$gte': -delta}},
                {'$inc': {'balance': delta},
                 '$set': {'updated_at': utc_now_iso()}})
            if updated is None:
                await self.wallet_transactions.update_one(
                    {'_id': tx['_id'], 'status': 'pending'},
                    {'$set': {'status': 'failed',
                              'fail_reason': 'insufficient_balance'}})
                w = await self.wallets.find_one({'_id': wallet['_id']})
                raise WalletError(
                    'insufficient_balance',
                    'موجودی کیف پول کافی نیست'
                    f' (موجودی: {int((w or {}).get("balance", 0)):,} تومان)')
            balance_before = int(updated['balance'])
        else:
            updated = await self.wallets.find_one_and_update(
                {'_id': wallet['_id']},
                {'$inc': {'balance': delta},
                 '$set': {'updated_at': utc_now_iso()}})
            balance_before = int((updated or {}).get('balance', 0))
        balance_after = balance_before + delta
        # گارد status: فقط تراکنش pending کامل می‌شود — اگر هم‌زمان مسیر
        # دیگری آن را تعیین‌تکلیف کرده باشد، اثر دوم نوشته نمی‌شود.
        res = await self.wallet_transactions.update_one(
            {'_id': tx['_id'], 'status': 'pending'},
            {'$set': {'status': 'ok', 'balance_before': balance_before,
                      'balance_after': balance_after}})
        if res.modified_count != 1:
            logger.warning(f'wallet tx {tx["_id"]} was resolved concurrently')
        tx.update({'status': 'ok', 'balance_before': balance_before,
                   'balance_after': balance_after})
        return tx

    async def wallet_credit(self, user_id: int, amount: int, tx_type: str,
                            ref_type: str, ref_id, actor_id: int,
                            label: str = '') -> dict:
        """اعتبار کیف پول — idempotent بر اساس (ref_type, ref_id)."""
        amount = int(amount)
        if amount <= 0:
            raise WalletError('invalid_amount', 'مبلغ باید مثبت باشد')
        if _wallet_need_owner_approval(amount, tx_type, int(actor_id or 0)):
            raise WalletError('needs_owner_approval', 'مبلغ بالا — نیاز به تایید مالک (ADMIN_ID)')
        if tx_type in (TX_ADMIN_CREDIT, TX_ADMIN_DEBIT):
            try:
                daily = await self._wallet_daily_toman_sum(int(user_id))
                if daily + amount > WALLET_DAILY_LIMIT:
                    raise WalletError('daily_limit_exceeded', f'سقف روزانه کیف پول ({WALLET_DAILY_LIMIT:,} تومان) — فردا دوباره')
            except WalletError:
                raise
            except Exception as e:
                # 🛡 W3/SEC-02 — fail-closed: اگر جمع روزانه قابل
                # محاسبه نباشد (خطای DB)، سقف نادیده گرفته نمی‌شود؛
                # تراکنش متوقف می‌شود تا دور زدن سقف مالی در شرایط
                # خطا ممکن نباشد.
                logger.critical(
                    'wallet daily-cap unavailable; blocking %s of %s '
                    'for user %s: %s',
                    tx_type, amount, user_id, e)
                raise WalletError(
                    'daily_limit_unavailable',
                    'سامانه سقف روزانه موقتاً در دسترس نیست؛ '
                    'لطفاً دقایقی دیگر تلاش کنید')
        tx, is_new = await self._wallet_tx_insert_pending(
            user_id, amount, tx_type, ref_type, ref_id, actor_id, label)
        if not is_new:
            return tx  # ری‌تری/دابل‌کلیک → همان اثر قبلی، بدون اعتبار دوم
        wallet = await self.wallet_get_or_create(user_id)
        return await self._wallet_apply(wallet, tx, amount)

    async def wallet_debit(self, user_id: int, amount: int, tx_type: str,
                           ref_type: str, ref_id, actor_id: int,
                           label: str = '') -> dict:
        """کسر از کیف پول — اتمیک، شرطی (بدون موجودی منفی) و idempotent."""
        amount = int(amount)
        if amount <= 0:
            raise WalletError('invalid_amount', 'مبلغ باید مثبت باشد')
        if _wallet_need_owner_approval(amount, tx_type, int(actor_id or 0)):
            raise WalletError('needs_owner_approval', 'مبلغ بالا — نیاز به تایید مالک (ADMIN_ID)')
        if tx_type in (TX_ADMIN_CREDIT, TX_ADMIN_DEBIT):
            try:
                daily = await self._wallet_daily_toman_sum(int(user_id))
                if daily + amount > WALLET_DAILY_LIMIT:
                    raise WalletError('daily_limit_exceeded', f'سقف روزانه کیف پول ({WALLET_DAILY_LIMIT:,} تومان) — فردا دوباره')
            except WalletError:
                raise
            except Exception as e:
                # 🛡 W3/SEC-02 — fail-closed: اگر جمع روزانه قابل
                # محاسبه نباشد (خطای DB)، سقف نادیده گرفته نمی‌شود؛
                # تراکنش متوقف می‌شود تا دور زدن سقف مالی در شرایط
                # خطا ممکن نباشد.
                logger.critical(
                    'wallet daily-cap unavailable; blocking %s of %s '
                    'for user %s: %s',
                    tx_type, amount, user_id, e)
                raise WalletError(
                    'daily_limit_unavailable',
                    'سامانه سقف روزانه موقتاً در دسترس نیست؛ '
                    'لطفاً دقایقی دیگر تلاش کنید')
        tx, is_new = await self._wallet_tx_insert_pending(
            user_id, amount, tx_type, ref_type, ref_id, actor_id, label)
        if not is_new:
            return tx
        wallet = await self.wallet_get_or_create(user_id)
        return await self._wallet_apply(wallet, tx, -amount)

    # ── خواندن ─────────────────────────────────────────────────
    async def wallet_tx_list(self, user_id: int, skip: int = 0,
                             limit: int = 20) -> list:
        limit = max(1, min(int(limit), 50))
        # ترتیب پایدار: created_at ثانیه‌ای است؛ _id گره‌ی tie-breaker است
        return await self.wallet_transactions.find(
            {'user_id': int(user_id), 'status': 'ok'}
        ).sort([('created_at', -1), ('_id', -1)]).skip(
            max(0, int(skip))).limit(limit).to_list(limit)

    async def wallet_tx_count(self, user_id: int) -> int:
        return await self.wallet_transactions.count_documents(
            {'user_id': int(user_id), 'status': 'ok'})

    async def wallet_tx_list_cursor(self, user_id: int, after_id: str = None, limit: int = 20) -> list:
        """Cursor pagination برای کیف پول — بعد از after_id (exclusive)."""
        q = {'user_id': int(user_id), 'status': 'ok'}
        if after_id:
            try:
                from bson import ObjectId
                q['_id'] = {'$lt': ObjectId(str(after_id))}
            except Exception:
                pass
        limit = max(1, min(int(limit), 50))
        return await self.wallet_transactions.find(q).sort('_id', -1).limit(limit).to_list(limit)

    async def wallet_pending_count(self, user_id: int) -> int:
        return await self.wallet_transactions.count_documents(
            {'user_id': int(user_id), 'status': 'pending'})

    async def _wallet_ok_ledger_sum(self, user_id: int) -> int:
        """جمع جبری ledger (فقط ok) — مبنای هر قضاوت حسابداری."""
        total = 0
        async for row in self.wallet_transactions.aggregate([
                {'$match': {'user_id': int(user_id), 'status': 'ok'}},
                {'$group': {'_id': None, 's': {'$sum': {'$cond': [
                    {'$eq': ['$direction', 'credit']},
                    '$amount', {'$multiply': ['$amount', -1]}]}}}}]):
            total = int(row['s'])
        return total

    # ── تعیین تکلیف تراکنش معلق (کرش بین مراحل) ───────────────
    async def wallet_resolve_pending(self, tx_id: str, admin_id: int,
                                     action: str) -> dict:
        """🌊 W6.1 — repair عمیق کرش: تراکنش pending یعنی الگوی
        insert-first بین «درج» و «اعمال/نشان‌گذاری» قطع شده است.

        تشخیص **evidence-based** است، نه حدس: اختلافِ (موجودی کش − جمع
        ledgerِ ok) اگر دقیقاً برابر اثر این تراکنش باشد، یعنی اثر مالی
        قبلاً اعمال شده و فقط نشان‌گذاری جا مانده؛ وگرنه اثر هرگز اعمال
        نشده. بر این اساس:

        action='complete' → اگر اثر اعمال نشده: اتمیک اعمال می‌شود
            (debit با شرط موجودی؛ ناکافی = خطا و tx همچنان معلق)؛
            اگر اعمال شده: فقط ok نشان‌گذاری می‌شود (بدون اثر دوم).
        action='cancel'   → txfailed می‌شود؛ اگر اثر اعمال شده باشد با
            compensating transaction جبران می‌شود (ledger هرگز بازنویسی
            نمی‌شود). جبرانِ creditِ اعمال‌شده یک debit است و اگر موجودی
            خرج شده باشد، صریحاً خطا می‌دهد (پنهان‌کاری صفر)."""
        try:
            tx = await self.wallet_transactions.find_one(
                {'_id': ObjectId(str(tx_id))})
        except Exception:
            tx = None
        if not tx:
            raise WalletError('tx_not_found', 'تراکنش پیدا نشد')
        if tx.get('status') != 'pending':
            raise WalletError('tx_not_pending',
                              'تراکنش معلق نیست (قبلاً تعیین تکلیف شده)')
        if action not in ('complete', 'cancel'):
            raise WalletError('bad_action', 'اقدام معتبر نیست')
        uid = int(tx['user_id'])
        amount = int(tx['amount'])
        delta = amount if tx['direction'] == 'credit' else -amount
        wallet = await self.wallet_get_or_create(uid)
        ledger = await self._wallet_ok_ledger_sum(uid)
        applied = (int(wallet.get('balance', 0)) - ledger) == delta

        if action == 'complete':
            if applied:
                res = await self.wallet_transactions.update_one(
                    {'_id': tx['_id'], 'status': 'pending'},
                    {'$set': {'status': 'ok',
                              'recovery': 'completed_after_crash',
                              'resolved_by': int(admin_id)}})
                if res.modified_count != 1:
                    raise WalletError('tx_not_pending',
                                      'تراکنش هم‌زمان تعیین تکلیف شد')
                return {'tx_id': str(tx['_id']), 'resolution': 'marked_applied',
                        'applied_before': True,
                        'balance_after': int(wallet.get('balance', 0))}
            # اثر اعمال نشده — همین‌جا اتمیک اعمال می‌شود
            tx = await self._wallet_apply(wallet, tx, delta)
            return {'tx_id': str(tx['_id']), 'resolution': 'applied_now',
                    'applied_before': False,
                    'balance_after': tx.get('balance_after')}

        # cancel — اگر اثر اعمال شده، طبق دکترین compensating transaction:
        # اول جبران (idempotent با کلید یکتا)، بعد خودِ تراکنش ok ثبت می‌شود
        # (واقعاً اتفاق افتاده) با نشان recovery — ledger هرگز بازنویسی
        # نمی‌شود و invariant «balance == جمع ledger» برقرار می‌ماند.
        # اگر اثر اعمال نشده: tx مستقیماً failed می‌شود (اثری در کار نبوده).
        if applied:
            if tx['direction'] == 'credit':
                # جبرانِ اعتبارِ اعمال‌شده = کسر همان مبلغ
                try:
                    await self.wallet_debit(
                        uid, amount, TX_ADMIN_DEBIT, 'pending_cancel',
                        str(tx['_id']), admin_id,
                        'جبران تراکنش معلق لغوشده (اعتبار)')
                except WalletError as e:
                    if e.code == 'insufficient_balance':
                        raise WalletError(
                            'cancel_would_overdraw',
                            'لغو ممکن نیست: موجودی خرج شده و جبران کسری '
                            'می‌آورد — نیازمند بررسی دستی (مغایرت‌گیری)')
                    raise
            else:
                await self.wallet_credit(
                    uid, amount, TX_REVERSAL, 'pending_cancel',
                    str(tx['_id']), admin_id,
                    'جبران تراکنش معلق لغوشده (کسر)')
            res = await self.wallet_transactions.update_one(
                {'_id': tx['_id'], 'status': 'pending'},
                {'$set': {'status': 'ok',
                          'recovery': 'cancelled_after_apply',
                          'resolved_by': int(admin_id)}})
        else:
            res = await self.wallet_transactions.update_one(
                {'_id': tx['_id'], 'status': 'pending'},
                {'$set': {'status': 'failed',
                          'fail_reason': 'cancelled_by_admin',
                          'resolved_by': int(admin_id)}})
        if res.modified_count != 1:
            raise WalletError('tx_not_pending',
                              'تراکنش هم‌زمان تعیین تکلیف شد')
        return {'tx_id': str(tx['_id']), 'resolution': 'cancelled',
                'applied_before': applied,
                'balance_after': int((await self.wallet_get_for_user_id(
                    uid) or {}).get('balance', 0))}

    async def wallet_summary(self, user_id: int) -> dict:
        """خلاصه‌ی کیف پول یک کاربر — همه از بک‌اند (client هیچ‌وقت
        موجودی را تعیین نمی‌کند)."""
        w = await self.wallet_get_or_create(user_id)
        agg = {'credit': 0, 'debit': 0}
        async for row in self.wallet_transactions.aggregate([
                {'$match': {'user_id': int(user_id), 'status': 'ok'}},
                {'$group': {'_id': '$direction',
                            'total': {'$sum': '$amount'}}}]):
            agg[row['_id']] = int(row['total'])
        last = await self.wallet_transactions.find_one(
            {'user_id': int(user_id), 'status': 'ok'},
            sort=[('created_at', -1), ('_id', -1)])
        return {'user_id': int(user_id),
                'balance': int(w.get('balance', 0)),
                'currency': WALLET_CURRENCY,
                'credits_total': agg['credit'], 'debits_total': agg['debit'],
                'last_tx': ({'id': str(last['_id']),
                             'label': last.get('label'),
                             'amount': last.get('amount'),
                             'direction': last.get('direction'),
                             'at': last.get('created_at')} if last else None),
                'created_at': w.get('created_at')}

    async def wallet_stats_global(self) -> dict:
        """آمار سراسری برای مرکز مالی ادمین (aggregate، نه اسکن)."""
        totals = {'wallets': 0, 'balance': 0}
        async for row in self.wallets.aggregate([
                {'$group': {'_id': None, 'n': {'$sum': 1},
                            'b': {'$sum': '$balance'}}}]):
            totals = {'wallets': int(row['n']), 'balance': int(row['b'])}
        by_type = {}
        async for row in self.wallet_transactions.aggregate([
                {'$match': {'status': 'ok'}},
                {'$group': {'_id': {'t': '$type', 'd': '$direction'},
                            'n': {'$sum': 1},
                            'total': {'$sum': '$amount'}}}]):
            key = row['_id']['t'] or 'unknown'
            cur = by_type.setdefault(key, {'count': 0, 'total': 0})
            cur['count'] += int(row['n'])
            cur['total'] += int(row['total'])
        return {**totals, 'by_type': by_type}

    async def wallet_get_for_user_id(self, user_id: int):
        return await self.wallets.find_one({'user_id': int(user_id)})

    # ── مغایرت‌گیری کیف پول ────────────────────────────────────
    async def wallet_reconcile_items(self, limit: int = 50) -> list:
        """مغایرت‌های بحرانی کیف پول — human-readable در لایه‌ی ادمین:
        ۱) balance کش‌شده ≠ جمع ledger (اختلاف حسابداری)
        ۲) بازگشت وجه انجام‌شده بدون اعتبار کیف پول
        ۳) کسر کیف پول بدون رسید تأییدشده
        ۴) تراکنش pending گیرکرده (کرش بین مراحل)"""
        items = []
        # ۱) ledger sum vs cached balance
        ledger_sums = {}
        async for row in self.wallet_transactions.aggregate([
                {'$match': {'status': 'ok'}},
                {'$group': {'_id': '$user_id',
                            's': {'$sum': {'$cond': [
                                {'$eq': ['$direction', 'credit']},
                                '$amount', {'$multiply': ['$amount', -1]}]}}}}]):
            ledger_sums[int(row['_id'])] = int(row['s'])
        async for w in self.wallets.find({}).limit(2000):
            uid = int(w['user_id'])
            bal = int(w.get('balance', 0))
            ledger = ledger_sums.get(uid, 0)
            if bal != ledger:
                items.append({'type': 'wallet_balance_mismatch',
                              'severity': 'critical', 'user_id': uid,
                              'amount': bal - ledger, 'balance': bal,
                              'ledger': ledger, 'at': w.get('updated_at')})
        # ۲) refunded payment without wallet credit
        credited_refs = {
            t['reference_id'] async for t in self.wallet_transactions.find(
                {'reference_type': 'sub_payment_refund',
                 'status': 'ok'}, {'reference_id': 1})}
        async for p in self.sub_payments.find(
                {'status': 'refunded'}).sort('refunded_at', -1).limit(200):
            if str(p['_id']) not in credited_refs:
                items.append({'type': 'refund_without_wallet_credit',
                              'severity': 'critical',
                              'user_id': int(p.get('user_id') or 0),
                              'payment_id': str(p['_id']),
                              'amount': int(p.get('final_price')
                                            or p.get('amount') or 0),
                              'at': p.get('refunded_at')})
        # ۳) wallet debit without approved payment
        async for t in self.wallet_transactions.find(
                {'reference_type': 'sub_payment_wallet',
                 'status': 'ok'}).sort('created_at', -1).limit(200):
            pid = t['reference_id']
            try:
                p = await self.sub_payments.find_one({'_id': ObjectId(pid)})
            except Exception:
                p = None
            if not p or p.get('status') not in ('approved', 'refunded'):
                items.append({'type': 'wallet_debit_without_payment',
                              'severity': 'critical',
                              'user_id': int(t.get('user_id') or 0),
                              'payment_id': pid, 'amount': int(t['amount']),
                              'at': t.get('created_at')})
        # ۵) 🌊 W6.2 — رسید شارژ تأییدشده بدون اعتبار کیف پول (کرش بین
        # تأیید و اعتبار). ملاک قضاوت همان ledger است، نه فقط فیلد
        # topup_credited_at — اگر tx اعتبار وجود داشته باشد مغایرتی نیست.
        topup_refs = {
            t['reference_id'] async for t in self.wallet_transactions.find(
                {'reference_type': 'sub_payment_topup',
                 'status': 'ok'}, {'reference_id': 1})}
        async for p in self.sub_payments.find(
                {'plan_id': 'wallet_topup', 'status': 'approved'}
        ).sort('reviewed_at', -1).limit(200):
            if str(p['_id']) not in topup_refs:
                items.append({'type': 'topup_without_wallet_credit',
                              'severity': 'critical',
                              'user_id': int(p.get('user_id') or 0),
                              'payment_id': str(p['_id']),
                              'amount': int(p.get('final_price')
                                            or p.get('amount') or 0),
                              'at': p.get('reviewed_at')})
        # ۴) stuck pending tx (crash recovery)
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(seconds=_STUCK_PENDING_SECONDS)).isoformat()
        async for t in self.wallet_transactions.find(
                {'status': 'pending',
                 'created_at': {'$lt': cutoff}}).limit(50):
            items.append({'type': 'wallet_tx_stuck_pending',
                          'severity': 'warning',
                          'user_id': int(t.get('user_id') or 0),
                          'tx_id': str(t['_id']), 'amount': int(t['amount']),
                          'at': t.get('created_at')})
        return items[:limit]

    # ── خرید اشتراک با کیف پول (لایه‌ی db — سرویس واحد) ────────
    async def sub_payment_create_wallet(self, user_id: int, plan_id: str,
                                        plan_name: str, price: int,
                                        idem_key: str = '',
                                        final_price: int = None,
                                        discount_code: str = None,
                                        discount_percent: int = None) -> str:
        """رسید خرید کیف‌پولی روی همان sub_payments — مسیر موازی نیست.
        status='wallet_processing' تا debit اتمیک تأیید شود؛ در صف رسیدهای
        دستی (pending) ظاهر نمی‌شود. snapshot تخفیف همان الگوی موج D1 است."""
        if idem_key:
            existing = await self.sub_payments.find_one(
                {'idem_key': idem_key}, {'_id': 1})
            if existing:
                return str(existing['_id'])
        doc = {
            'user_id': int(user_id), 'plan_id': plan_id,
            'plan_name': plan_name, 'price': int(price),
            'final_price': int(final_price if final_price is not None
                               else price),
            'discount_code': discount_code,
            'discount_percent': discount_percent,
            'screenshot_file_id': None,
            'method': 'wallet', 'status': 'wallet_processing',
            'submitted_at': utc_now_iso(), 'admin_msg_id': None,
        }
        if idem_key:
            doc['idem_key'] = idem_key
        try:
            r = await self.sub_payments.insert_one(doc)
            return str(r.inserted_id)
        except DuplicateKeyError:  # race روی idem_key یکتا
            existing = await self.sub_payments.find_one(
                {'idem_key': idem_key}, {'_id': 1})
            if existing:
                return str(existing['_id'])
            raise

    async def wallet_purchase_finalize(self, pid: str) -> bool:
        """CAS اتمیک wallet_processing→approved — فقط یک بار موفق می‌شود."""
        try:
            res = await self.sub_payments.update_one(
                {'_id': ObjectId(pid), 'status': 'wallet_processing'},
                {'$set': {'status': 'approved', 'reviewed_by': 0,
                          'reviewed_at': utc_now_iso(),
                          'review_note': 'پرداخت از کیف پول داخلی'}})
            return res.modified_count == 1
        except Exception as e:
            logger.warning(f'wallet_purchase_finalize failed {pid}: {e}')
            return False

    # ── سرویس واحد خرید با کیف پول (API و Bot مشترک) ───────────
    async def wallet_purchase(self, user_id: int, plan_id: str,
                              idem_key: str = '',
                              discount_code: str = None) -> dict:
        """🌊 W6 — تنها منطق خرید با کیف پول؛ Bot و MiniApp/Web API هر دو
        همین را صدا می‌زنند (منطق موازی ممنوع).

        order (sub_payments, method=wallet) → debit اتمیک شرطی →
        CAS اتمیک → همان سرویس فعال‌سازیِ تأیید رسید (finalize_approved_payment).

        🎟 کد تخفیف: validate قبل از debit؛ مصرف اتمیک بعد از debit موفق
        (همان primitive موج D1)؛ اگر مصرف شکست بخورد، debit با reversal
        جبران می‌شود — کد تخفیف هرگز «نیمه‌مصرف» نمی‌ماند.

        خطاها WalletError با کد ماشین‌خوان هستند:
        plan_not_found / plan_price_invalid / discount_invalid /
        discount_full / discount_exhausted / insufficient_balance /
        order_conflict / plan_days_invalid (با جبران reversal)."""
        user_id = int(user_id)
        plan = await self.sub_plan_get(plan_id)
        if not plan or not plan.get('active'):
            raise WalletError('plan_not_found', 'پلن پیدا نشد')
        price = int(plan.get('price') or 0)
        if price <= 0:
            raise WalletError('plan_price_invalid', 'قیمت پلن نامعتبر است')
        # 🎟 تخفیف — فقط اعتبارسنجی؛ قیمت نهایی همان فرمول مسیر رسید است
        code = (discount_code or '').strip().upper()
        percent = None
        if code:
            v = await self.discount_validate(
                code, plan_id=str(plan['_id']), user_id=user_id)
            if not v.get('ok'):
                raise WalletError('discount_invalid',
                                  v.get('reason') or 'کد تخفیف معتبر نیست')
            percent = int(v.get('percent') or 0)
        final = round(price * (100 - percent) / 100) if percent else price
        if final <= 0:
            raise WalletError('discount_full',
                              'کد تخفیف ۱۰۰٪ نیازی به کیف پول ندارد — '
                              'از مسیر فعال‌سازی رایگان استفاده کنید')
        idem = (idem_key or '').strip()[:64]
        pid = await self.sub_payment_create_wallet(
            user_id, str(plan['_id']), plan.get('name', 'اشتراک'), price,
            idem, final_price=final, discount_code=code or None,
            discount_percent=percent)
        # ری‌تری با idem یکسان و سفارشِ کامل‌شده → همان نتیجه، بدون اثر دوم
        existing = await self.sub_payment_get(pid)
        if existing and existing.get('status') == 'approved' \
                and existing.get('method') == 'wallet':
            sub = await self.sub_get(user_id)
            return {'payment_id': pid, 'plan_name': plan.get('name'),
                    'amount': int(existing.get('final_price') or final),
                    'replay': True,
                    'end_date': (sub or {}).get('end_date')}
        try:
            await self.wallet_debit(
                user_id, final, TX_SUB_PURCHASE, 'sub_payment_wallet',
                pid, user_id, f"خرید اشتراک {plan.get('name', '')} با کیف پول")
        except WalletError as e:
            if e.code == 'insufficient_balance':
                await self.sub_payments.update_one(
                    {'_id': ObjectId(pid), 'status': 'wallet_processing'},
                    {'$set': {'status': 'rejected',
                              'review_note': 'موجودی کیف پول کافی نبود'}})
            raise
        # 🎟 مصرف اتمیک کد بعد از debit؛ شکست = جبران کامل debit
        if code:
            consumed = await self.discount_consume(code, user_id=user_id)
            if not consumed:
                await self.wallet_credit(
                    user_id, final, TX_REVERSAL,
                    'sub_payment_wallet_discount_fail', pid, 0,
                    'بازگشت مبلغ به دلیل اتمام ظرفیت کد تخفیف')
                await self.sub_payments.update_one(
                    {'_id': ObjectId(pid)},
                    {'$set': {'status': 'rejected',
                              'review_note': 'مصرف کد تخفیف ناموفق — '
                                             'مبلغ به کیف پول برگشت'}})
                raise WalletError('discount_exhausted',
                                  'ظرفیت کد تخفیف پر شده — '
                                  'موجودی شما دست‌نخورده است')
        if not await self.wallet_purchase_finalize(pid):
            existing = await self.sub_payment_get(pid)
            if not existing or existing.get('status') != 'approved':
                raise WalletError('order_conflict',
                                  'سفارش در حال پردازش است یا بسته شده')
        payment = await self.sub_payment_get(pid)
        try:
            act = await self.finalize_approved_payment(payment, admin_id=user_id)
        except ValueError:
            # جبران مالی صریح: مبلغ با compensating transaction برمی‌گردد
            await self.wallet_credit(
                user_id, final, TX_REVERSAL, 'sub_payment_wallet_reversal',
                pid, 0, 'بازگشت مبلغ به دلیل خطای فعال‌سازی')
            await self.sub_payments.update_one(
                {'_id': ObjectId(pid)},
                {'$set': {'status': 'rejected',
                          'review_note': 'خطای فعال‌سازی — مبلغ به کیف پول برگشت'}})
            raise WalletError('plan_days_invalid',
                              'پلن معتبر نیست؛ مبلغ به کیف پول شما برگشت')
        return {'payment_id': pid, 'plan_name': plan.get('name'),
                'amount': final, 'end_date': act.get('end_date'),
                'days': act.get('days'), 'replay': False}
