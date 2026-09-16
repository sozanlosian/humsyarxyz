# -*- coding: utf-8 -*-
"""🌱 W13/W14 — قوانین خالص رشد (ریفرال + پیگیری پرداخت).

عمداً بدون هیچ ایمپورتی از database/bot: همه‌ی توابع pure و sync هستند
تا در CIِ بدون Mongo هم تست شوند. منطق stateful در referral.py و dunning.py.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

# ── کد دعوت ──────────────────────────────────────────────
REF_CODE_LEN = 8
# بدون نویسه‌های اشتباه‌شونده (0/O/1/I/L)
REF_CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
REF_START_PREFIX = 'ref_'


def normalize_ref_code(s) -> str:
    return (str(s or '').strip().upper())


def parse_ref_start_arg(text) -> str | None:
    """پارس `?start=ref_XXXX` (حساس به حروف نیست). نامعتبر → None."""
    t = normalize_ref_code(text)
    if not t.startswith(REF_START_PREFIX.upper()):
        return None
    code = t[len(REF_START_PREFIX):]
    if len(code) != REF_CODE_LEN:
        return None
    if any(c not in REF_CODE_ALPHABET for c in code):
        return None
    return code


def make_ref_code() -> str:
    return ''.join(secrets.choice(REF_CODE_ALPHABET) for _ in range(REF_CODE_LEN))


def ref_link(bot_username: str, code: str) -> str:
    return f'https://t.me/{(bot_username or "").strip().lstrip("@")}?start={REF_START_PREFIX}{code}'


# ── انواع جایزه ──────────────────────────────────────────
REWARD_TYPES = {
    'sub_days': {'label': 'روز اشتراک', 'unit': 'days', 'default': 7, 'max': 365},
    'wallet': {'label': 'شارژ کیف پول', 'unit': 'toman', 'default': 50000, 'max': 10_000_000},
    'discount': {'label': 'کد تخفیف اختصاصی', 'unit': 'percent', 'default': 20, 'max': 100},
    'xp': {'label': 'امتیاز پرستیژ', 'unit': 'xp', 'default': 100, 'max': 100_000},
}
# کدام جایزه‌ها عددی و نصف‌شدنی‌اند (حالت split)؟
REWARD_SPLITTABLE = {'sub_days', 'wallet'}
TIMINGS = ('on_register', 'on_first_buy', 'split')


def split_amounts(amount: int) -> tuple:
    """نصف‌کردن جایزه در حالت split: نصف اول (رو به بالا) + باقیمانده."""
    a = max(0, int(amount or 0))
    first = (a + 1) // 2
    return first, a - first


# ── کانفیگ ریفرال (کلیدهای settings با پیشوند ref_) ──────
DEFAULT_REF_CONFIG = {
    'enabled': False,
    'timing': 'split',
    'rewards': {
        key: {'on': False, 'amount': spec['default']}
        for key, spec in REWARD_TYPES.items()
    },
    'cap_daily': 5,
    'cap_monthly': 30,
    'burst_n': 5,
    'burst_minutes': 30,
}


def merge_ref_config(stored: dict | None) -> dict:
    """ادغام امن کانفیگ ذخیره‌شده با پیش‌فرض‌ها (اعتبارسنجی + clamp)."""
    stored = dict(stored or {})
    cfg = {
        'enabled': bool(stored.get('enabled', False)),
        'timing': stored.get('timing', 'split'),
        'cap_daily': stored.get('cap_daily', 5),
        'cap_monthly': stored.get('cap_monthly', 30),
        'burst_n': stored.get('burst_n', 5),
        'burst_minutes': stored.get('burst_minutes', 30),
    }
    if cfg['timing'] not in TIMINGS:
        cfg['timing'] = 'split'
    for key in ('cap_daily', 'cap_monthly', 'burst_n', 'burst_minutes'):
        try:
            cfg[key] = max(0, int(cfg[key]))
        except (TypeError, ValueError):
            cfg[key] = DEFAULT_REF_CONFIG[key]
    cfg['rewards'] = {}
    stored_rw = stored.get('rewards') or {}
    for key, spec in REWARD_TYPES.items():
        one = stored_rw.get(key) or {}
        try:
            amount = int(one.get('amount', spec['default']))
        except (TypeError, ValueError):
            amount = spec['default']
        amount = max(0, min(spec['max'], amount))
        if key == 'discount' and amount > 0:
            amount = max(1, amount)
        cfg['rewards'][key] = {'on': bool(one.get('on', False)), 'amount': amount}
    return cfg


# ── کانفیگ پیگیری پرداخت (کلیدهای dun_) ──────────────────
DEFAULT_DUN_CONFIG = {
    'enabled': False,
    'step1_s': 3600,
    'step2_s': 86400,
    'quiet_start': 0,   # ساعت تهران (شروع بازه‌ی سکوت)
    'quiet_end': 7,     # ساعت تهران (پایان بازه‌ی سکوت)
}


def merge_dun_config(stored: dict | None) -> dict:
    stored = dict(stored or {})
    cfg = {'enabled': bool(stored.get('enabled', False))}
    for key in ('step1_s', 'step2_s'):
        try:
            cfg[key] = max(60, int(stored.get(key, DEFAULT_DUN_CONFIG[key])))
        except (TypeError, ValueError):
            cfg[key] = DEFAULT_DUN_CONFIG[key]
    for key in ('quiet_start', 'quiet_end'):
        try:
            cfg[key] = max(0, min(23, int(stored.get(key, DEFAULT_DUN_CONFIG[key]))))
        except (TypeError, ValueError):
            cfg[key] = DEFAULT_DUN_CONFIG[key]
    return cfg


def dun_steps(cfg: dict) -> list:
    """گام‌های زمانی به ثانیه، مرتب و یکتا."""
    return sorted({int(cfg.get('step1_s', 3600)), int(cfg.get('step2_s', 86400))})


# ── زمان ──────────────────────────────────────────────────
def parse_iso_ts(s) -> float | None:
    """ISO → timestamp؛ خراب/خالی → None (هرگز exception)."""
    if not s or not isinstance(s, str):
        return None
    try:
        txt = s.strip()
        if txt.endswith('Z'):
            txt = txt[:-1] + '+00:00'
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, OverflowError):
        return None


def tehran_hour(ts: float) -> int:
    """ساعت تهران برای timestamp (بدون وابستگی به tzdata سیستم)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromtimestamp(ts, tz=ZoneInfo('Asia/Tehran')).hour
    except Exception:
        # تهران از ۲۰۲۲ DST ندارد: ‎+3:30‎ ثابت (دقیق تا سطح دقیقه)
        base = datetime.fromtimestamp(ts, tz=timezone.utc)
        return ((base.hour * 60 + base.minute + 210) // 60) % 24


def in_quiet_hours(hour: int, start_h: int, end_h: int) -> bool:
    """آیا ساعت در بازه‌ی سکوت است؟ (بازه‌ی overnight-aware؛ برابر = بدون سکوت)."""
    start_h, end_h = int(start_h) % 24, int(end_h) % 24
    if start_h == end_h:
        return False
    if start_h < end_h:
        return start_h <= int(hour) < end_h
    return int(hour) >= start_h or int(hour) < end_h


# ── ضدتقلب: تشخیص انفجار دعوت ────────────────────────────
def burst_flagged(event_ts_list: list, now_ts: float, n: int, window_s: int) -> bool:
    """اگر n رویداد آخر همگی داخل پنجره باشند → مشکوک."""
    if n <= 1:
        return False
    recent = sorted((t for t in event_ts_list if t), reverse=True)[:n]
    if len(recent) < n:
        return False
    return (now_ts - recent[-1]) <= max(1, int(window_s))


# ── متن‌های نمایشی (خالص — تست‌پذیر) ───────────────────
def describe_granted(granted: dict) -> str:
    """خلاصه‌ی فارسی جوایز اعطاشده‌ی ریفرال."""
    parts = []
    if not isinstance(granted, dict):
        return ''
    sub = granted.get('sub_days') or {}
    if sub.get('days'):
        parts.append(f"🎁 {sub['days']} روز اشتراک")
    wal = granted.get('wallet') or {}
    if wal.get('amount'):
        parts.append(f"👛 {int(wal['amount']):,} تومان شارژ کیف پول")
    dis = granted.get('discount') or {}
    if dis.get('code'):
        parts.append(f"🎟 کد تخفیف {dis.get('percent') or ''}٪: "
                     f"<code>{dis['code']}</code>")
    xp = granted.get('xp') or {}
    if xp.get('xp'):
        parts.append(f"⚡ {xp['xp']} امتیاز پرستیژ")
    return '\n'.join(parts)


def _fmt_price(v) -> str:
    try:
        return f'{int(v):,} تومان'
    except (TypeError, ValueError):
        return '—'


def dunning_message(doc: dict, step_idx: int) -> str:
    """متن یادآوری پیگیری پرداخت."""
    plan = (doc or {}).get('plan_name') or 'اشتراک'
    amount = _fmt_price((doc or {}).get('final_price')
                        or (doc or {}).get('price') or 0)
    if step_idx <= 0:
        return (
            '💳 <b>پرداختت نیمه‌تمام مونده!</b>\n\n'
            f'📦 {plan} — {amount}\n'
            'به درگاه رفتی ولی پرداخت کامل نشد. اگه منصرف نشدی، '
            'از همین‌جا ادامه بده 👇'
        )
    return (
        '⏰ <b>آخرین یادآوری پرداخت</b>\n\n'
        f'📦 {plan} — {amount}\n'
        'این پرداخت هنوز بازه و ممکنه منقضی بشه. '
        'برای فعال‌شدن اشتراکت ادامه بده 👇'
    )


# ── انتخاب پرداخت‌های مستحق یادآوری (خالص) ───────────────
def dunning_due(payments: list, now_ts: float, steps_s: list) -> list:
    """از میان رسیدها، (رسید، شماره‌ی گام)‌های سررسیده را برمی‌گرداند.

    شرط: status دقیقاً zarinpal_pending + مبلغ مثبت + سن کافی برای گام +
    آن گام قبلاً ارسال نشده باشد. هر رسید حداکثر یک گام (کوچک‌ترینِ سررسیده).
    """
    out = []
    for p in payments or []:
        if not isinstance(p, dict):
            continue
        if p.get('status') != 'zarinpal_pending':
            continue
        try:
            if int(p.get('final_price') or p.get('price') or 0) <= 0:
                continue
        except (TypeError, ValueError):
            continue
        born = parse_iso_ts(p.get('submitted_at'))
        if born is None:
            continue
        age = now_ts - born
        sent = p.get('dunning_sent') or []
        for idx, step_s in enumerate(steps_s or []):
            if age >= step_s and idx not in sent:
                out.append((p, idx))
                break
    return out
