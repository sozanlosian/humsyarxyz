# -*- coding: utf-8 -*-
"""
🎟 موتور کمپین تخفیف HUMSYAR — موج D1

نقطه‌ی واحدی که قالب پیام انتشار کد تخفیف را برای Bot و Mini App و
Notification می‌سازد. همه‌چیز Dynamic از روی سند discount + sub_plans
محاسبه می‌شود؛ هیچ نام/قیمت/مدت/درصدی Hardcode نیست.

قواعد:
- HUMSYAR یک پلتفرم آموزشی دانشجویی است — هیچ اصطلاح VPNای (سرویس، حجم،
  گیگ، اکانت، سرور، اتصال...) در متن‌ها استفاده نمی‌شود.
- فرمول قیمت: همان موتور فعلی — round(price * (100 - percent) / 100)
- Placeholderها با {{name}} در قالب جایگذاری می‌شوند.
"""
from datetime import datetime


# ══════════════════════════════════════════════════
#  قالب پیش‌فرض — آموزشی، فارسی، RTL
# ══════════════════════════════════════════════════
DEFAULT_TEMPLATE = """🎟 <b>{{title}}</b>

{{description}}

🎟 کد تخفیف:
<code>{{code}}</code>

💰 میزان تخفیف: <b>{{percent}}٪</b>

📦 قابل استفاده برای: {{plans}}{{plans_lines}}

🔢 ظرفیت استفاده: {{usage_limit}}{{remaining_line}}

⏰ اعتبار: {{expires_at}}

‼️ مهلت استفاده از تخفیف تا پایان اعتبار کد است."""


DEFAULT_TITLE = 'تخفیف ویژه هامزیار فعال شد!'
DEFAULT_DESCRIPTION = 'برای مدت محدودی می‌تونی اشتراک هامزیار رو با تخفیف ویژه تهیه کنی.'


# ── کمک‌متن‌ها ──

def fmt_price(p) -> str:
    """۱۰۰٬۰۰۰ تومان — دقیقاً مثل _fmt_price در subscription.py"""
    try:
        return f"{int(p):,}".replace(',', '٬') + " تومان"
    except Exception:
        return str(p)


def _fa_int(n) -> str:
    """عدد به رقم‌های فارسی برای نمایش کاربر."""
    try:
        return str(int(n)).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))
    except Exception:
        return str(n)


def _fa_date(iso: str) -> str:
    """تاریخ ISO → نمایش کوتاه فارسی (جلالی) — سازگار با utils.fmt_jalali."""
    if not iso:
        return 'بدون انقضا'
    try:
        from utils import fmt_jalali_dt
        return fmt_jalali_dt(iso, with_time=False)
    except Exception:
        return str(iso)[:10]


def discounted_price(price: int, percent: int) -> int:
    """⚙️ Single Source of Truth برای محاسبه — همان فرمول فعلی."""
    try:
        return round(int(price) * (100 - int(percent)) / 100)
    except Exception:
        return int(price or 0)


# ══════════════════════════════════════════════════
#  Context Builder — همه‌ی Placeholderها
# ══════════════════════════════════════════════════

def build_campaign_context(discount: dict, plans: list) -> dict:
    """
    discount: سند discount_codes
    plans:    لیست پلن‌های هدف (از sub_plans فیلترشده — فقط فعال‌ها)
    خروجی: dict آماده برای render_template
    """
    percent = int(discount.get('percent', 0) or 0)
    max_uses = int(discount.get('max_uses', 0) or 0)
    used = int(discount.get('used_count', 0) or 0)
    remaining = max(0, max_uses - used) if max_uses > 0 else None
    code = discount.get('code', '')

    # ── پلن‌ها (Dynamic) ──
    plan_names = [p.get('name', 'اشتراک') for p in plans]
    if plans:
        plans_txt = '، '.join(plan_names)
    else:
        plans_txt = 'همه پلن‌های فعال'

    # خطوط قیمت هر پلن (هر پلن: اصلی خط‌خورده → نهایی)
    lines = []
    prices_raw, prices_disc = [], []
    for p in plans:
        price = int(p.get('price', 0) or 0)
        disc = discounted_price(price, percent)
        prices_raw.append(price)
        prices_disc.append(disc)
        if price == disc:
            lines.append(f"\n• {p.get('name','اشتراک')} ← {fmt_price(price)}")
        else:
            lines.append(
                f"\n• {p.get('name','اشتراک')} ← "
                f"<s>{fmt_price(price)}</s> ➜ <b>{fmt_price(disc)}</b>"
            )
    plans_lines = ''.join(lines)

    # ── ظرفیت ──
    if max_uses > 0:
        usage_limit = f"{_fa_int(max_uses)} نفر"
    else:
        usage_limit = 'نامحدود'
    remaining_line = ''
    if remaining is not None and remaining <= max(3, int(max_uses * 0.2)):
        remaining_line = f"\n⚡ فقط {_fa_int(remaining)} استفاده باقی مانده!"

    return {
        'code': code,
        'percent': discount.get('percent', 0),
        'percent_fa': _fa_int(percent),
        'used_count': used,
        'used_count_fa': _fa_int(used),
        'max_uses': max_uses,
        'max_uses_fa': _fa_int(max_uses) if max_uses > 0 else '∞',
        'remaining_uses': remaining if remaining is not None else '',
        'remaining_uses_fa': _fa_int(remaining) if remaining is not None else '',
        'expires_at': _fa_date(discount.get('expires_at')),
        'plans': plans_txt,
        'plan_names': plans_txt,
        'plans_lines': plans_lines,
        'usage_limit': usage_limit,
        'remaining_line': remaining_line,
        'min_price': fmt_price(min(prices_raw)) if prices_raw else '',
        'max_price': fmt_price(max(prices_raw)) if prices_raw else '',
        'min_discounted': fmt_price(min(prices_disc)) if prices_disc else '',
        'max_discounted': fmt_price(max(prices_disc)) if prices_disc else '',
        'discounted_prices': plans_lines,
        'created_at': _fa_date(discount.get('created_at')),
        'title': discount.get('announcement_title') or DEFAULT_TITLE,
        'description': discount.get('announcement_text') or DEFAULT_DESCRIPTION,
    }


def render_template(template: str, ctx: dict) -> str:
    """جایگذاری {{placeholder}} — ساده و در برابر کلید ناموجود امن."""
    out = template or DEFAULT_TEMPLATE
    for k, v in ctx.items():
        out = out.replace('{{' + k + '}}', str(v))
    return out


# ══════════════════════════════════════════════════
#  سرویس سطح بالا — ساخت پیام کمپین از DB
# ══════════════════════════════════════════════════

async def resolve_target_plans(db, discount: dict) -> list:
    """پلن‌های هدف کد — همیشه از sub_plans سالم (فعال) خوانده می‌شود."""
    targets = discount.get('target_plan_ids') or []
    active_plans = await db.sub_plan_list(only_active=True)
    if not targets:
        return active_plans
    return [p for p in active_plans if str(p['_id']) in [str(t) for t in targets]]


async def build_campaign_message(db, discount: dict, template: str = None,
                                  overrides: dict = None) -> tuple:
    """
    خروجی: (title, html_text)
    overrides (اختیاری): {'title':..., 'description':...} برای شخصی‌سازی
    متن پیش از ارسال — اطلاعات حساس (درصد/ظرفیت/قیمت) همچنان DB است.
    """
    plans = await resolve_target_plans(db, discount)
    ctx = build_campaign_context(discount, plans)
    if overrides:
        if overrides.get('title'):
            ctx['title'] = overrides['title']
        if overrides.get('description'):
            ctx['description'] = overrides['description']
    text = render_template(template or discount.get('announcement_template'), ctx)
    return ctx['title'], text


def campaign_cta_link(discount: dict) -> str:
    """🔗 Deep Link مینی‌اپ: صفحه‌ی اشتراک با کد پیش‌پُر‌شده."""
    code = discount.get('code', '')
    return f"/me/subscription?discount={code}" if code else '/me/subscription'


def build_soldout_message(discount: dict) -> str:
    """
    ⛔ موج D2 — متن جایگزین کمپین پس از اتمام ظرفیت.
    پیام‌های ارسالی‌ی کمپین با این متن (و بدون دکمه‌ی CTA) ادیت می‌شوند.
    """
    code = discount.get('code', '')
    pct = _fa_int(discount.get('percent', 0))
    return (
        f"⛔ <b>ظرفیت کد تخفیف {code} تکمیل شد!</b>\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"این کد ({pct}٪ تخفیف) به سقف استفاده رسید و دیگر فعال نیست. 🙏\n\n"
        f"💡 نوتیفیکیشن «🎁 تخفیف‌ها» را روشن نگه دار تا "
        f"کمپین بعدی را از دست ندهی."
    )
