"""
💳 پنل مدیریت اشتراک — پرمیشن subscription.manage (🌊 W10؛ قبلاً فقط ADMIN_ID)
  ✅ کلید اجباری‌سازی سراسری (پیش‌فرض خاموش)
  ✅ چند پلن هم‌زمان — قیمت/روز هرکدام مستقل
  ✅ شماره کارت
  ✅ صف رسیدهای در انتظار
  ✅ مدیریت دستی اشتراک هر کاربر (فعال/تمدید/لغو با دلیل)
  ✅ کدهای تخفیف درصدی
  ✅ اعطای رایگان دسته‌جمعی بر اساس نقش
  ✅ آمار
"""
import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db
from utils import send_audit_log, safe_send, spawn_bg   # 🛡 AUDIT-M1
from time_utils import format_datetime_fa, now_utc, utc_now_iso

logger = logging.getLogger(__name__)
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))


def _fmt_price(p: int) -> str:
    return f"{p:,}".replace(',', '٬') + " تومان"


def _fa(n) -> str:
    try:
        return str(int(n)).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))
    except Exception:
        return str(n)


def _back(cb='suba:main'):
    return [InlineKeyboardButton("🔙 بازگشت", callback_data=cb)]


# ══════════════════════════════════════════════════
#  منوی اصلی
# ══════════════════════════════════════════════════

async def _show_main(query):
    enforced = await db.get_setting('subscription_enforced', False)
    protect  = await db.get_setting('protect_content_enabled', True)
    stats = await db.sub_stats()
    status_txt  = "🟢 اجباری (فعال روی همه)" if enforced else "🔴 غیرفعال (فعلاً همه دسترسی دارن)"
    protect_txt = "🟢 روشن (فوروارد/ذخیره غیرفعاله)" if protect else "🔴 خاموش (فوروارد/ذخیره آزاده)"
    text = (
        f"💳 <b>مدیریت اشتراک</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"وضعیت اجباری اشتراک: {status_txt}\n"
        f"🔒 محافظت کپی‌رایت فایل‌ها: {protect_txt}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"✅ فعال: <b>{stats['active']}</b>  |  ⏳ در انتظار: <b>{stats['pending']}</b>\n"
        f"⌛ منقضی: {stats['expired']}  |  🚫 لغوشده: {stats['revoked']}\n\n"
        f"💰 درآمد این ماه: <b>{_fmt_price(stats['revenue_month'])}</b>\n"
        f"💰 درآمد کل: {_fmt_price(stats['revenue'])}\n"
        f"📈 نرخ تأیید: {stats['conv_rate']}٪  ({stats['approved_total']} تأیید / {stats['rejected_total']} رد)\n"
        f"🏆 پرفروش‌ترین پلن: {stats['top_plan']}"
    )
    toggle_label  = "🔴 خاموش‌کردن اجباری اشتراک" if enforced else "🟢 اجباری‌کردن اشتراک برای همه"
    protect_label = "🔴 خاموش‌کردن محافظت فایل‌ها" if protect else "🟢 روشن‌کردن محافظت فایل‌ها"
    # 🌊 W6 — gateway status badge
    _gw_merchant = (await db.get_setting('zarinpal_merchant_id', '') or '').strip()
    _gw_enabled = await db.get_setting('zarinpal_enabled', True)
    _gw_sandbox = await db.get_setting('zarinpal_sandbox', None)
    if _gw_sandbox is None:
        _gw_sandbox = not bool(_gw_merchant)
    _gw_badge = "🟢 فعال" if (_gw_enabled and _gw_merchant) else ("🟡 آزمایشی" if not _gw_merchant else "🔴 غیرفعال")
    _gw_mode = "سندباکس" if _gw_sandbox else "اصلی"
    keyboard = [
        [InlineKeyboardButton(toggle_label, callback_data='suba:toggle_enforce')],
        [InlineKeyboardButton(protect_label, callback_data='suba:toggle_protect')],
        [InlineKeyboardButton(f"💳 درگاه زرین‌پال [{_gw_badge} • {_gw_mode}]", callback_data='suba:gateway')],
        [InlineKeyboardButton("📋 پلن‌ها", callback_data='suba:plans'),
         InlineKeyboardButton("💳 شماره کارت", callback_data='suba:card')],
        [InlineKeyboardButton(f"📥 صف در انتظار ({stats['pending']})", callback_data='suba:pending'),
         InlineKeyboardButton("📜 تاریخچه‌ی کامل", callback_data='suba:history:all:0')],
        [InlineKeyboardButton(f"📋 لیست مشترکین فعال ({stats['active']})", callback_data='suba:subscribers:0')],
        [InlineKeyboardButton("👤 مدیریت اشتراک کاربر", callback_data='suba:user_search')],
        [InlineKeyboardButton("🎟 کدهای تخفیف", callback_data='suba:discounts')],
        [InlineKeyboardButton("🎁 اعطای رایگان دسته‌جمعی", callback_data='suba:grant')],
        _back('admin:cat_settings'),
    ]
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


# ══════════════════════════════════════════════════
#  تاریخچه‌ی کامل رسیدها (همه‌ی وضعیت‌ها + فیلتر + صفحه‌بندی)
# ══════════════════════════════════════════════════

_HISTORY_FILTERS = {
    'all': ('همه', None), 'pending': ('در انتظار', 'pending'),
    'approved': ('تأییدشده', 'approved'), 'rejected': ('ردشده', 'rejected'),
}
_HISTORY_PAGE_SIZE = 8


async def _show_history(query, filt: str, page: int):
    label, status = _HISTORY_FILTERS.get(filt, ('همه', None))
    total = await db.sub_payment_count_all(status)
    items = await db.sub_payment_list_all(status, skip=page * _HISTORY_PAGE_SIZE, limit=_HISTORY_PAGE_SIZE)
    icons = {'pending': '⏳', 'approved': '✅', 'rejected': '❌'}

    lines = [f"📜 <b>تاریخچه‌ی رسیدها</b> — {label} ({total})\n━━━━━━━━━━━━━━━━"]
    if not items:
        lines.append("چیزی پیدا نشد.")
    for p in items:
        user = await db.get_user(p['user_id'])
        name = user.get('name', str(p['user_id'])) if user else str(p['user_id'])
        icon = icons.get(p['status'], '•')
        lines.append(f"{icon} {name} — {p['plan_name']} — {_fmt_price(p['final_price'])}")

    # فیلترها
    filter_row = [
        InlineKeyboardButton(('🔘 ' if k == filt else '') + v[0], callback_data=f'suba:history:{k}:0')
        for k, v in _HISTORY_FILTERS.items()
    ]
    keyboard = [filter_row]

    # صفحه‌بندی
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("◀️ قبلی", callback_data=f'suba:history:{filt}:{page-1}'))
    if (page + 1) * _HISTORY_PAGE_SIZE < total:
        nav_row.append(InlineKeyboardButton("بعدی ▶️", callback_data=f'suba:history:{filt}:{page+1}'))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append(_back())
    await query.edit_message_text("\n".join(lines), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


# ══════════════════════════════════════════════════
#  پلن‌ها
# ══════════════════════════════════════════════════

async def _show_plans(query):
    plans = await db.sub_plan_list()
    lines = ["📋 <b>پلن‌های اشتراک</b>\n━━━━━━━━━━━━━━━━"]
    keyboard = []
    if not plans:
        lines.append("هنوز پلنی تعریف نشده.")
    for p in plans:
        mark = "✅" if p.get('active') else "⛔️"
        sold = await db.sub_payments.count_documents({'plan_id': str(p['_id']), 'status': 'approved'})
        _aiq = int(p.get('ai_daily_limit') or 0)
        lines.append(f"{mark} {p['name']} — {p['days']} روز — {_fmt_price(p['price'])} — 🛒 {sold} فروش" + (f" — 🤖 {_aiq}/روز" if _aiq > 0 else ""))
        keyboard.append([
            InlineKeyboardButton("✏️ ویرایش", callback_data=f"suba:plan_edit:{p['_id']}"),
            InlineKeyboardButton(f"{'⛔️ غیرفعال' if p.get('active') else '✅ فعال'}",
                                  callback_data=f"suba:plan_toggle:{p['_id']}"),
            InlineKeyboardButton("🗑 حذف", callback_data=f"suba:plan_del:{p['_id']}"),
        ])
    keyboard.append([InlineKeyboardButton("➕ پلن جدید", callback_data='suba:plan_add')])
    keyboard.append(_back())
    await query.edit_message_text("\n".join(lines), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _prompt_plan_edit(query, context, plan_id: str):
    plan = await db.sub_plan_get(plan_id)
    if not plan:
        await query.answer("❌ پلن پیدا نشد.", show_alert=True)
        return
    context.user_data['mode'] = 'suba_plan_edit'
    context.user_data['suba_plan_edit_id'] = plan_id
    await query.edit_message_text(
        f"✏️ <b>ویرایش «{plan['name']}»</b>\n\n"
        f"مقدار فعلی: {plan['days']} روز — {_fmt_price(plan['price'])}\n\n"
        "فرم جدید رو بفرست:\n<code>نام | روز | قیمت</code>\n\n"
        f"مثال:\n<code>{plan['name']} | {plan['days']} | {plan['price']}</code>",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup([_back('suba:plans')])
    )


async def handle_plan_edit_text(update, context):
    plan_id = context.user_data.pop('suba_plan_edit_id', None)
    context.user_data.pop('mode', None)
    text = update.message.text.strip()
    if not plan_id:
        return
    try:
        name, days_s, price_s = [p.strip() for p in text.split('|')]
        days, price = int(days_s), int(price_s)
        await db.sub_plan_update(plan_id, {'name': name, 'days': days, 'price': price})
        await update.message.reply_text(f"✅ پلن به‌روزرسانی شد: «{name}» ({days} روز، {_fmt_price(price)})")
    except Exception:
        await update.message.reply_text(
            "❌ فرمت اشتباه بود.\nمثال درست: <code>یک ماهه | 30 | 100000</code>", parse_mode='HTML'
        )


async def _prompt_plan_add(query, context):
    context.user_data['mode'] = 'suba_plan_add'
    await query.edit_message_text(
        "➕ <b>پلن جدید</b>\n\nبه این فرم بفرست:\n<code>نام | تعداد روز | قیمت (تومان)</code>\n\n"
        "مثال:\n<code>یک ماهه | 30 | 100000</code>",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup([_back('suba:plans')])
    )


async def handle_plan_add_text(update, context):
    text = update.message.text.strip()
    context.user_data.pop('mode', None)
    try:
        name, days_s, price_s = [p.strip() for p in text.split('|')]
        days, price = int(days_s), int(price_s)
        await db.sub_plan_add(name, days, price)
        await update.message.reply_text(f"✅ پلن «{name}» ({days} روز، {_fmt_price(price)}) اضافه شد.")
    except Exception:
        await update.message.reply_text(
            "❌ فرمت اشتباه بود.\nدوباره از «📋 پلن‌ها → ➕ پلن جدید» امتحان کن.\n"
            "مثال درست: <code>یک ماهه | 30 | 100000</code>", parse_mode='HTML'
        )


# ══════════════════════════════════════════════════
#  شماره کارت
# ══════════════════════════════════════════════════

async def _show_card(query):
    num   = await db.get_setting('subscription_card_number', '—')
    owner = await db.get_setting('subscription_card_owner', '—')
    text = (
        f"💳 <b>اطلاعات کارت</b>\n━━━━━━━━━━━━━━━━\n"
        f"شماره: <code>{num}</code>\nصاحب حساب: {owner}"
    )
    keyboard = [
        [InlineKeyboardButton("✏️ ویرایش", callback_data='suba:card_edit')],
        _back(),
    ]
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _prompt_card_edit(query, context):
    context.user_data['mode'] = 'suba_card'
    await query.edit_message_text(
        "✏️ به این فرم بفرست:\n<code>شماره کارت | نام صاحب حساب</code>\n\n"
        "مثال:\n<code>6037-xxxx-xxxx-xxxx | امیرحسین ...</code>",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup([_back('suba:card')])
    )


async def handle_card_text(update, context):
    text = update.message.text.strip()
    context.user_data.pop('mode', None)
    try:
        num, owner = [p.strip() for p in text.split('|', 1)]
        _old_num = await db.get_setting('subscription_card_number', '')
        _old_owner = await db.get_setting('subscription_card_owner', '')
        await db.set_setting('subscription_card_number', num)
        await db.set_setting('subscription_card_owner', owner)
        try:
            _au = await db.get_user(update.effective_user.id) or {}
            _an = _au.get('name', 'مدیر ارشد')
            _ar = await db.get_actor_role_label(update.effective_user.id)
            # شماره کارت حساس است — فقط 4 رقم آخر در جزئیات
            _masked = (num[:4] + '****' + num[-4:]) if len(num) >= 8 else '****'
            await send_audit_log(context.bot, 'admin', _an, update.effective_user.id,
                "ویرایش اطلاعات کارت اشتراک", module='Subscription', severity='HIGH', actor_role=_ar,
                before={'card_number': _old_num[:4]+'****' if _old_num else '—', 'owner': _old_owner},
                after={'card_number': _masked, 'owner': owner},
                tags=['اشتراک_کارت'])
        except Exception as _e:
            import logging; logging.getLogger(__name__).warning(f"card audit failed: {_e}")
        await update.message.reply_text("✅ اطلاعات کارت به‌روزرسانی شد.")
    except Exception:
        await update.message.reply_text("❌ فرمت اشتباه بود. مثال: <code>شماره | نام</code>", parse_mode='HTML')


# ══════════════════════════════════════════════════
#  صف در انتظار
# ══════════════════════════════════════════════════

async def _show_pending(query):
    pending = await db.sub_payment_list_pending()
    if not pending:
        text = "📥 <b>صف در انتظار</b>\n\n✅ چیزی در صف نیست."
        keyboard = [_back()]
    else:
        lines = ["📥 <b>صف در انتظار</b>\n━━━━━━━━━━━━━━━━"]
        keyboard = []
        for p in pending[:15]:
            user = await db.get_user(p['user_id'])
            name = user.get('name', str(p['user_id'])) if user else str(p['user_id'])
            lines.append(f"• {name} — {p['plan_name']} — {_fmt_price(p['final_price'])}")
            keyboard.append([
                InlineKeyboardButton(f"👁 {name[:20]}", callback_data=f"suba:view_pay:{p['_id']}")
            ])
        keyboard.append(_back())
        text = "\n".join(lines)
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _resend_payment_for_review(query, context, pid):
    """اگه پیام اصلی رسید گم/اسکرول شده، دوباره با دکمه تأیید/رد برای ادمین می‌فرسته"""
    p = await db.sub_payment_get(pid)
    if not p:
        await query.answer("❌ پیدا نشد.", show_alert=True)
        return
    user = await db.get_user(p['user_id'])
    name = user.get('name', str(p['user_id'])) if user else str(p['user_id'])
    reject_count = await db.sub_payment_reject_count(p['user_id'])
    warn_line = f"\n⚠️ این کاربر قبلاً {reject_count} بار رد شده" if reject_count > 0 else ""
    caption = (
        f"💳 <b>رسید پرداخت</b>\n\n👤 {name}\n🆔 <code>{p['user_id']}</code>\n"
        f"📦 {p['plan_name']} | 💰 {_fmt_price(p['final_price'])}{warn_line}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تأیید", callback_data=f"sub:appr:{pid}"),
        InlineKeyboardButton("❌ رد", callback_data=f"sub:rej:{pid}"),
    ]])
    await query.message.reply_photo(p['screenshot_file_id'], caption=caption, parse_mode='HTML', reply_markup=kb)


# ══════════════════════════════════════════════════
#  📋 لیست کامل مشترکین فعال (قابل مرور، نه فقط جستجو)
# ══════════════════════════════════════════════════

_SUBSCRIBERS_PAGE_SIZE = 10


async def _show_subscribers_list(query, page: int):
    from utils import fmt_jalali_dt
    total = await db.sub_count_by_status('active')
    items = await db.sub_list_by_status('active', skip=page * _SUBSCRIBERS_PAGE_SIZE, limit=_SUBSCRIBERS_PAGE_SIZE)

    lines = [f"📋 <b>مشترکین فعال</b> ({total} نفر)\n━━━━━━━━━━━━━━━━"]
    keyboard = []
    if not items:
        lines.append("فعلاً هیچ مشترک فعالی نیست.")
    for s in items:
        uid = s['_id']
        user = await db.get_user(uid)
        name = user.get('name', str(uid)) if user else str(uid)
        days_left = await db.sub_days_left(uid)
        soon = "🔴" if days_left <= 3 else "✅"
        lines.append(f"{soon} {name} — {s.get('plan_name','-')} — {days_left} روز مانده (تا {fmt_jalali_dt(s.get('end_date',''), with_time=False)})")
        keyboard.append([InlineKeyboardButton(f"👤 {name[:25]}", callback_data=f"suba:user:{uid}")])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("◀️ قبلی", callback_data=f'suba:subscribers:{page-1}'))
    if (page + 1) * _SUBSCRIBERS_PAGE_SIZE < total:
        nav_row.append(InlineKeyboardButton("بعدی ▶️", callback_data=f'suba:subscribers:{page+1}'))
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton("🔍 جستجو در مشترکین", callback_data='suba:user_search')])
    keyboard.append(_back())
    await query.edit_message_text("\n".join(lines), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


# ══════════════════════════════════════════════════
#  مدیریت دستی اشتراک کاربر
# ══════════════════════════════════════════════════

async def _prompt_user_search(query, context):
    context.user_data['mode'] = 'suba_user_search'
    await query.edit_message_text(
        "🔍 آیدی عددی، یوزرنیم یا نام دانشجو رو بفرست:",
        reply_markup=InlineKeyboardMarkup([_back()])
    )


async def handle_user_search_text(update, context):
    context.user_data.pop('mode', None)
    text = update.message.text.strip()
    results = await db.search_users(text)
    if not results:
        await update.message.reply_text("❌ کاربری پیدا نشد.")
        return
    keyboard = []
    for u in results[:10]:
        keyboard.append([InlineKeyboardButton(
            f"👤 {u.get('name','?')} (@{u.get('username','-')})",
            callback_data=f"suba:user:{u['user_id']}"
        )])
    keyboard.append(_back())
    await update.message.reply_text(
        f"🔍 {len(results)} نتیجه:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _show_user_detail(query, target_uid: int):
    user = await db.get_user(target_uid)
    name = user.get('name', str(target_uid)) if user else str(target_uid)
    s = await db.sub_get(target_uid)
    if s and s.get('status') == 'active' and await db.sub_is_active(target_uid):
        from utils import progress_bar
        days = await db.sub_days_left(target_uid)
        total = max(1, s.get('last_plan_days', days) or 1)
        pct = min(100, round(days / total * 100))
        status_txt = f"✅ فعال — {days} روز مانده ({s.get('plan_name','-')})\n<code>[{progress_bar(pct)}]</code> {pct}٪"
    elif s and s.get('status') == 'revoked':
        status_txt = f"🚫 لغوشده — دلیل: {s.get('revoke_reason','-')}"
    elif s and s.get('status') == 'expired':
        status_txt = "⌛ منقضی‌شده"
    else:
        status_txt = "⚠️ بدون اشتراک"

    reject_count = await db.sub_payment_reject_count(target_uid)
    reject_line = f"\n⚠️ {reject_count} بار رد شده" if reject_count > 0 else ""

    text = f"👤 <b>{name}</b>\n🆔 <code>{target_uid}</code>\n\n💳 وضعیت: {status_txt}{reject_line}"
    keyboard = [
        [
            InlineKeyboardButton("+7", callback_data=f"suba:manual_quick:{target_uid}:7"),
            InlineKeyboardButton("+30", callback_data=f"suba:manual_quick:{target_uid}:30"),
            InlineKeyboardButton("+90", callback_data=f"suba:manual_quick:{target_uid}:90"),
        ],
        [InlineKeyboardButton("✍️ تعداد دلخواه", callback_data=f"suba:manual_activate:{target_uid}")],
        [InlineKeyboardButton("🧾 تاریخچه‌ی این کاربر", callback_data=f"suba:user_history:{target_uid}")],
    ]
    if s and s.get('status') == 'active':
        keyboard.append([InlineKeyboardButton("🚫 لغو اشتراک (با دلیل)", callback_data=f"suba:revoke:{target_uid}")])
    keyboard.append(_back())
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _quick_activate(query, context, target_uid: int, days: int):
    # 🛡 AUDIT-A1b — «ادعای یکتا» روی (ادمین، کاربر، مقدار). پنل بعد از اعطا
    # همان دکمه‌ها را نگه می‌دارد، پس دابل‌تپ یا فشار یک دکمه‌ی کهنه (پیام
    # قدیمیِ چند ساعت پیش) قبلاً یک بار دیگر +N روز اضافه می‌کرد. برای
    # اعطای عمدیِ مجدد، مسیر «✍️ تعداد دلخواه» باز است (مصرف یک‌بارمصرف).
    if not await db.op_claim('sub_quick_grant', f"{query.from_user.id}:{target_uid}:{days}",
                             ttl_seconds=3600):
        await query.answer(
            "این اعطا (%s روز) همین حالا برای این کاربر ثبت شده بود.\n"
            "اگر عمدی است از «✍️ تعداد دلخواه» استفاده کنید." % days,
            show_alert=True,
        )
        return
    await db.sub_activate(target_uid, days, plan_name=f'فعال‌سازی دستی (+{days} روز)',
                           source='admin_manual', granted_by=query.from_user.id, extend=True)
    days_left = await db.sub_days_left(target_uid)
    # 🔔 موج ۴.۹۰ — اینباکس مینی‌اپ (فعال‌سازی اشتراک)
    await db.inbox_add(target_uid, 'sub_activated',
        "💎 اشتراکت فعال شد!",
        f"اشتراکت توسط ادمین فعال شد؛ {days_left} روز اعتبار داری.",
        link='/me/subscription')
    await safe_send(
        context.bot, target_uid,
        f"✅ <b>اشتراکت توسط ادمین فعال شد!</b>\n\n⏳ {days_left} روز اعتبار داری.\n"
        f"از بخش «👤 پروفایل» می‌تونی چک کنی.", parse_mode='HTML'
    )
    await query.answer(f"✅ {days} روز فعال شد.", show_alert=True)
    await send_audit_log(
        context.bot, 'admin', 'ادمین ارشد', query.from_user.id,
        f"فعال‌سازی دستی سریع (+{days} روز)", module='Subscription', severity='INFO',
        target_id=str(target_uid), target_type='user', tags=['اشتراک_دستی']
    )
    await _show_user_detail(query, target_uid)


async def _show_user_payment_history(query, target_uid: int):
    from utils import fmt_jalali_dt
    history = await db.sub_payment_history(target_uid)
    icons = {'pending': '⏳', 'approved': '✅', 'rejected': '❌'}
    lines = [f"🧾 <b>تاریخچه‌ی پرداخت کاربر {target_uid}</b>\n━━━━━━━━━━━━━━━━"]
    if not history:
        lines.append("هیچ رسیدی ثبت نکرده.")
    for p in history[:15]:
        icon = icons.get(p['status'], '•')
        date = fmt_jalali_dt(p.get('submitted_at', ''))
        lines.append(f"{icon} {p['plan_name']} — {_fmt_price(p['final_price'])} — {date}")
    await query.edit_message_text(
        "\n".join(lines), parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([_back(f'suba:user:{target_uid}')])
    )


async def _prompt_manual_days(query, context, target_uid):
    context.user_data['mode'] = 'suba_manual_days'
    context.user_data['suba_target_uid'] = target_uid
    await query.edit_message_text(
        "➕ تعداد روز اشتراک رو بفرست (فقط عدد، مثلاً 30):",
        reply_markup=InlineKeyboardMarkup([_back(f'suba:user:{target_uid}')])
    )


async def handle_manual_days_text(update, context):
    target_uid = context.user_data.pop('suba_target_uid', None)
    context.user_data.pop('mode', None)
    text = update.message.text.strip()
    if not target_uid or not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("❌ فقط یه عدد مثبت بفرست.")
        return
    days = int(text)
    await db.sub_activate(target_uid, days, plan_name='فعال‌سازی دستی',
                           source='admin_manual', granted_by=update.effective_user.id, extend=True)
    days_left = await db.sub_days_left(target_uid)
    # 🔔 موج ۴.۹۰ — اینباکس مینی‌اپ (فعال‌سازی اشتراک)
    await db.inbox_add(target_uid, 'sub_activated',
        "💎 اشتراکت فعال شد!",
        f"اشتراکت توسط ادمین فعال شد؛ {days_left} روز اعتبار داری.",
        link='/me/subscription')
    await safe_send(
        context.bot, target_uid,
        f"✅ <b>اشتراکت توسط ادمین فعال شد!</b>\n\n⏳ {days_left} روز اعتبار داری.\n"
        f"از بخش «👤 پروفایل» می‌تونی چک کنی.", parse_mode='HTML'
    )
    await update.message.reply_text(f"✅ {days} روز برای کاربر {target_uid} فعال شد.")
    await send_audit_log(
        context.bot, 'admin', 'ادمین ارشد', update.effective_user.id,
        "فعال‌سازی دستی اشتراک", module='Subscription', severity='INFO',
        target_id=str(target_uid), target_type='user', tags=['اشتراک_دستی']
    )


async def _prompt_revoke_reason(query, context, target_uid):
    context.user_data['mode'] = 'suba_revoke_reason'
    context.user_data['suba_target_uid'] = target_uid
    await query.edit_message_text(
        "🚫 دلیل لغو اشتراک رو بنویس (برای دانشجو ارسال می‌شه):",
        reply_markup=InlineKeyboardMarkup([_back(f'suba:user:{target_uid}')])
    )


async def handle_revoke_reason_text(update, context):
    target_uid = context.user_data.pop('suba_target_uid', None)
    context.user_data.pop('mode', None)
    reason = update.message.text.strip()
    if not target_uid:
        return
    ok = await db.sub_revoke(target_uid, reason, update.effective_user.id)
    if ok:
        await safe_send(
            context.bot, target_uid,
            f"🚫 <b>اشتراکت لغو شد</b>\n\n📝 دلیل: {reason}", parse_mode='HTML'
        )
        await update.message.reply_text("✅ لغو شد و به کاربر اطلاع داده شد.")
        await send_audit_log(
            context.bot, 'admin', 'ادمین ارشد', update.effective_user.id,
            "لغو اشتراک", module='Subscription', severity='HIGH',
            target_id=str(target_uid), target_type='user',
            target_label=reason, tags=['لغو_اشتراک']
        )
    else:
        await update.message.reply_text("❌ این کاربر اصلاً اشتراکی نداشت.")


# ══════════════════════════════════════════════════
#  کدهای تخفیف
# ══════════════════════════════════════════════════

async def _show_discounts(query):
    from utils import fmt_jalali_dt
    codes = await db.discount_list()
    lines = ["🎟 <b>کدهای تخفیف</b>\n━━━━━━━━━━━━━━━━"]
    keyboard = []
    if not codes:
        lines.append("هنوز کدی ساخته نشده.")
    for c in codes[:20]:
        mark = "✅" if c.get('active') else "⛔️"
        used = f"{c.get('used_count',0)}/{c['max_uses'] if c.get('max_uses') else '∞'}"
        exp  = f" — تا {fmt_jalali_dt(c['expires_at'], with_time=False)}" if c.get('expires_at') else ""
        plan_note = ""
        if c.get('target_plan_ids'):
            plan_note = f" — 📦 {_fa(len(c['target_plan_ids']))} پلن"
        lines.append(f"{mark} <code>{c['code']}</code> — {c['percent']}٪ — استفاده: {used}{exp}{plan_note}")
        keyboard.append([
            InlineKeyboardButton(f"{'⛔️' if c.get('active') else '✅'} {c['code']}",
                                  callback_data=f"suba:disc_toggle:{c['code']}"),
            InlineKeyboardButton("📣", callback_data=f"suba:disc_bcast:{c['code']}"),
            InlineKeyboardButton("👁", callback_data=f"suba:disc_prev:{c['code']}"),
        ])
        keyboard.append([
            InlineKeyboardButton("📊 آمار", callback_data=f"suba:disc_stats:{c['code']}"),
            InlineKeyboardButton("🗑 حذف", callback_data=f"suba:disc_del:{c['code']}"),
        ])
    keyboard.append([InlineKeyboardButton("➕ کد جدید", callback_data='suba:disc_add')])
    keyboard.append(_back())
    await query.edit_message_text("\n".join(lines), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _prompt_discount_add(query, context):
    context.user_data['mode'] = 'suba_discount_add'
    await query.edit_message_text(
        "➕ <b>کد تخفیف جدید</b>\n\nفرم:\n"
        "<code>کد | درصد | سقف‌استفاده(0=نامحدود) | روز‌اعتبار(0=همیشگی)</code>\n\n"
        "مثال:\n<code>NOWRUZ20 | 20 | 0 | 30</code>\n(یعنی ۲۰٪ تخفیف، بی‌سقف استفاده، تا ۳۰ روز دیگه معتبر)\n\n"
        "برای کد ۱۰۰٪ رایگان، درصد رو 100 بذار.",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup([_back('suba:discounts')])
    )


async def handle_discount_add_text(update, context):
    from datetime import datetime, timedelta
    text = update.message.text.strip()
    context.user_data.pop('mode', None)
    try:
        parts = [p.strip() for p in text.split('|')]
        code, percent = parts[0], int(parts[1])
        max_uses = int(parts[2]) if len(parts) > 2 else 0
        exp_days = int(parts[3]) if len(parts) > 3 else 0
        expires_at = (now_utc() + timedelta(days=exp_days)).isoformat() if exp_days > 0 else None
        ok = await db.discount_add(code, percent, max_uses, expires_at, update.effective_user.id)
        if ok:
            await update.message.reply_text(f"✅ کد <code>{code.upper()}</code> ساخته شد.", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ این کد از قبل وجود داره.")
    except Exception:
        await update.message.reply_text(
            "❌ فرمت اشتباه بود.\nمثال: <code>NOWRUZ20 | 20 | 0 | 30</code>", parse_mode='HTML'
        )


# ══════════════════════════════════════════════════
#  🎟 موج D1 — کمپین انتشار کد تخفیف (Preview / Broadcast / Stats)
# ══════════════════════════════════════════════════

async def _campaign_text(discount: dict):
    """متن HTML کمپین — از موتور مشترک discount_campaign (Dynamic)."""
    from discount_campaign import build_campaign_message
    _, text = await build_campaign_message(db, discount)
    return text


def _campaign_cta_kb(discount: dict):
    """کیبورد زیر پیام کمپین: Deep Link مینی‌اپ + دیپ‌لینک بات (fallback)."""
    from utils import webapp_kb
    from discount_campaign import campaign_cta_link
    code = discount['code']
    kb = webapp_kb(campaign_cta_link(discount), label='🎟 دریافت اشتراک با تخفیف')
    rows = list(kb.inline_keyboard) if kb else []
    rows.append([InlineKeyboardButton(
        "💳 تهیه اشتراک با تخفیف (در بات)",
        callback_data=f"sub:dcode:{code}")])
    return InlineKeyboardMarkup(rows)


async def _show_discount_preview(query, code: str):
    discount = await db.discount_get(code)
    if not discount:
        await query.answer("❌ کد پیدا نشد.", show_alert=True)
        return
    text = await _campaign_text(discount)
    await query.message.reply_text(
        "👁 <b>پیش‌نمایش پیام کمپین</b>\n────────────\n" + text,
        parse_mode='HTML',
        reply_markup=_campaign_cta_kb(discount))
    try:
        await send_audit_log(query.from_user, f"👁 پیش‌نمایش کمپین کد {code}", 'subscriptions')
    except Exception:
        pass


async def _prompt_discount_broadcast(query, context, code: str):
    discount = await db.discount_get(code)
    if not discount:
        await query.answer("❌ کد پیدا نشد.", show_alert=True)
        return
    if not discount.get('active'):
        await query.answer("⚠️ این کد غیرفعال است — اول فعالش کن.", show_alert=True)
        return
    # ضد دابل‌کلیک: اگر broadcast همین کد در حال ارسال است
    active_bc = await db.discount_bcast_active_for(code)
    if active_bc:
        await query.answer("⏳ انتشار قبلی همین کد هنوز در حال اجراست.", show_alert=True)
        return
    counts = []
    for seg, label in (('all', 'همه کاربران'), ('subscribers', 'دارای اشتراک فعال'),
                        ('no_sub', 'بدون اشتراک فعال')):
        users = await db.discount_segment_users(seg)
        counts.append((seg, label, len(users)))
    context.user_data['bcast_draft_code'] = code
    lines = "\n".join(f"• {l}: <b>{_fa(c)}</b> نفر" for _, l, c in counts)
    text = (
        f"📣 <b>انتشار کد {discount['code']}</b>\n━━━━━━━━━━━━━━━━\n"
        f"💰 {discount['percent']}٪ تخفیف\n\n"
        f"مخاطب را انتخاب کن:\n{lines}\n\n"
        f"پیامِ آماده‌ی کمپین (پلن‌ها و قیمت‌ها Dynamic از سیستم) برای همه ارسال می‌شود "
        f"و دکمه‌ی CTA مستقیم به صفحه‌ی اشتراک دارد."
    )
    kb = [[InlineKeyboardButton(f"📨 {l} ({_fa(c)})", callback_data=f"suba:disc_bcast_go:{code}:{s}")]
          for s, l, c in counts]
    kb.append(_back('suba:discounts'))
    await query.edit_message_text(text, parse_mode='HTML',
                                  reply_markup=InlineKeyboardMarkup(kb))


async def _execute_discount_broadcast(query, context, code: str, segment: str):
    import asyncio
    from telegram.error import RetryAfter, Forbidden, BadRequest, TimedOut, NetworkError
    discount = await db.discount_get(code)
    if not discount or not discount.get('active'):
        await query.answer("❌ کد معتبر/فعال نیست.", show_alert=True)
        return
    active_bc = await db.discount_bcast_active_for(code)  # ضد دابل‌کلیک (لایه اجرا)
    if active_bc:
        await query.answer("⏳ انتشار قبلی همین کد هنوز در حال اجراست.", show_alert=True)
        return

    text = await _campaign_text(discount)
    kb = _campaign_cta_kb(discount)
    users = await db.discount_segment_users(segment)
    # 🎚 ادغام نوتیفیکیشن: کاربرانی که دسته‌ی «🎁 تخفیف‌ها» را خاموش
    # کرده‌اند از ارسال DM کنار گذاشته می‌شوند (اینباکس همچنان آرشیو می‌شود)
    try:
        _defaults = await db.get_notif_defaults()
        seg_total = len(users)
        users = [u for u in users if db.notif_pref_on(
            u.get('notification_settings', {}), 'discounts', _defaults)]
    except Exception:
        seg_total = len(users)
    seg_label = {'all': 'همه کاربران', 'subscribers': 'دارای اشتراک فعال',
                 'no_sub': 'بدون اشتراک فعال'}.get(segment, segment)

    bid = await db.discount_bcast_create(code, segment, query.from_user.id, source='bot')
    await db.discount_bcast_update(bid, {'total': len(users)})
    _pref_note = (f" (🔕 {_fa(seg_total - len(users))} نفر اعلان تخفیف را "
                  f"خاموش کرده‌اند)") if seg_total != len(users) else ""
    await query.edit_message_text(
        f"📣 <b>در حال انتشار {discount['code']}…</b>\n\n"
        f"👥 مخاطب: {seg_label} — {_fa(len(users))} نفر{_pref_note}\n"
        f"🆔 <code>{bid}</code>\n\nپیشرفت همین‌جا بروزرسانی می‌شود…",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⛔ توقف انتشار", callback_data=f'suba:disc_bcast_stop:{bid}')
        ]])
    )
    try:
        await send_audit_log(query.from_user,
            f"📣 شروع انتشار کد {code} → {seg_label} ({bid})", 'subscriptions')
    except Exception:
        pass

    async def _run():
        sent, failed, blocked = 0, 0, 0
        cancelled = False
        last_note = 0
        msg_refs = []  # ⛔ موج D2 — مرجع پیام‌های موفق برای ادیت «اتمام موجودی»
        for i, u in enumerate(users):
            # ⛔ پشتیبانی از توقف: هر ۲۰ نفر وضعیت را از دیتابیس می‌خوانیم
            if i > 0 and i % 20 == 0:
                cur = await db.discount_bcast_get(bid)
                if cur and cur.get('status') == 'cancelled':
                    cancelled = True
                    break
            uid = u['user_id']
            outcome = 'fail'  # ok | fail | blocked — شمارش دقیق هر کاربر
            for _attempt in range(3):
                try:
                    _m = await context.bot.send_message(
                        uid, text, parse_mode='HTML', reply_markup=kb)
                    outcome = 'ok'
                    msg_refs.append({'c': uid, 'm': _m.message_id})
                    break
                except RetryAfter as e:
                    await asyncio.sleep(e.retry_after + 0.5)
                    continue
                except Forbidden:
                    outcome = 'blocked'
                    await db.mark_user_blocked(uid)
                    break
                except (TimedOut, NetworkError):
                    await asyncio.sleep(1.5)
                    continue
                except BadRequest:
                    break
                except Exception:
                    break
            if outcome == 'ok':
                sent += 1
            elif outcome == 'blocked':
                blocked += 1
            else:
                failed += 1
            # گام‌بندی نرخ — الگوی _do_broadcast_send (جلوگیری از طوفان 429)
            await asyncio.sleep(0.05)
            # پیشرفت هر ۲۵ کاربر (+ خالی‌کردن مراجع پیام در DB)
            if (i + 1) % 25 == 0 or (i + 1) == len(users):
                if msg_refs:
                    try:
                        await db.discount_bcast_add_msgs(bid, msg_refs)
                    except Exception:
                        pass
                    msg_refs = []
                if (i + 1) - last_note >= 25 or (i + 1) == len(users):
                    last_note = i + 1
                    await db.discount_bcast_update(bid, {
                        'sent': sent, 'failed': failed, 'blocked': blocked})
                    try:
                        await query.edit_message_text(
                            f"📣 <b>در حال انتشار {discount['code']}…</b>\n\n"
                            f"👥 {_fa(len(users))} نفر — پیشرفت: "
                            f"{_fa(i+1)}/{_fa(len(users))}\n"
                            f"✅ {_fa(sent)} | ❌ {_fa(failed)} | 🚫 {_fa(blocked)}",
                            parse_mode='HTML')
                    except Exception:
                        pass
        # خالی‌کردن مراجع باقی‌مانده (در صورت توقف زودهنگام)
        if msg_refs:
            try:
                await db.discount_bcast_add_msgs(bid, msg_refs)
            except Exception:
                pass
            msg_refs = []
        await db.discount_bcast_update(bid, {
            'status': 'cancelled' if cancelled else 'completed',
            'sent': sent, 'failed': failed,
            'blocked': blocked, 'finished_at': utc_now_iso(),
        })
        # اینباکس مینی‌اپ (اختیاری): برای کاربرانی که موفق گرفتند
        try:
            link = __import__('discount_campaign', fromlist=['campaign_cta_link']) \
                .campaign_cta_link(discount)
            await db.inbox_add_many([
                {'user_id': u['user_id'], 'type': 'discount',
                 'title': f"🎟 تخفیف {discount['percent']}٪ — کد {discount['code']}",
                 'body': text.replace('<b>', '').replace('</b>', '').replace('<code>', '').replace('</code>', '').replace('<s>', '').replace('</s>', '')[:240],
                 'link': link}
                for u in users[:500]
            ])
        except Exception:
            pass
        rate = (sent / len(users) * 100) if users else 0
        title = f"⛔ <b>انتشار {discount['code']} متوقف شد</b>" if cancelled \
            else f"✅ <b>گزارش انتشار {discount['code']}</b>"
        summary = (
            f"{title}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"👥 هدف: {_fa(len(users))} ({seg_label}){_pref_note}\n"
            f"✅ موفق: {_fa(sent)}\n"
            f"❌ ناموفق: {_fa(failed)}\n"
            f"🚫 بلاک‌کننده: {_fa(blocked)}\n"
            f"📨 نرخ موفقیت: {_fa(round(rate, 2))}٪\n"
            f"🆔 <code>{bid}</code>"
        )
        try:
            await query.edit_message_text(summary, parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([_back('suba:discounts')]))
        except Exception:
            await safe_send(context.bot, query.from_user.id, summary)
        try:
            if cancelled:
                await send_audit_log(query.from_user,
                    f"⛔ انتشار {code} لغو شد — تا لحظه‌ی توقف ✅{sent} ❌{failed} 🚫{blocked} ({bid})",
                    'subscriptions')
            else:
                await send_audit_log(query.from_user,
                    f"📣 انتشار {code} تمام شد — ✅{sent} ❌{failed} 🚫{blocked} ({bid})",
                    'subscriptions')
        except Exception:
            pass

    # 🛡 AUDIT-M1 — broadcast ربات: تسک طولانی بی‌مرجع ممکن است وسط کار
    # جمع‌آوری شود و خطایش هرگز جایی ثبت نشود.
    spawn_bg(_run(), 'discount_broadcast_bot')


async def _show_discount_stats(query, code: str):
    discount = await db.discount_get(code)
    if not discount:
        await query.answer("❌ کد پیدا نشد.", show_alert=True)
        return
    pay = await db.discount_payment_stats(code)
    bcasts = await db.discount_bcast_list(code, 3)
    mu = discount.get('max_uses', 0)
    used = discount.get('used_count', 0)
    remaining = max(0, mu - used) if mu > 0 else '∞'
    targets = discount.get('target_plan_ids') or []
    if targets:
        plans = await db.sub_plan_list(only_active=False)
        names = [p['name'] for p in plans if str(p['_id']) in [str(t) for t in targets]]
        plans_txt = '، '.join(names) or f"{_fa(len(targets))} پلن"
    else:
        plans_txt = 'همه پلن‌های فعال'
    bc_lines = ''
    for b in bcasts:
        st = {'sending': '⏳', 'completed': '✅', 'failed': '❌', 'cancelled': '🚫'}.get(b.get('status'), '❔')
        bc_lines += (f"\n{st} <code>{b.get('broadcast_id','')}</code> — "
                     f"{_fa(b.get('sent',0))}/{_fa(b.get('total',0))}")
    text = (
        f"📊 <b>آمار {discount['code']}</b>\n━━━━━━━━━━━━━━━━\n"
        f"💰 تخفیف: {discount['percent']}٪\n"
        f"🎟 مصرف: {_fa(used)}/{_fa(mu) if mu else '∞'} — باقی: {_fa(remaining) if remaining != '∞' else '∞'}\n"
        f"📦 پلن‌های هدف: {plans_txt}\n"
        f"👥 سقف هر کاربر: {_fa(discount.get('per_user_limit') or 0) or 'نامحدود'}\n"
        f"⏰ انقضا: {format_datetime_fa(discount.get('expires_at'), long=True) if discount.get('expires_at') else 'بدون انقضا'}\n"
        f"────────────────────\n"
        f"💳 پرداخت‌های تأییدشده با این کد: {_fa(pay['usage_approved'])}\n"
        f"💰 مبلغ تخفیف‌داده‌شده: {_fmt_price(pay['discount_given'])}\n"
        f"📥 درآمد (با تخفیف): {_fmt_price(pay['revenue'])}"
        f"{bc_lines}"
    )
    await query.edit_message_text(text, parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([_back('suba:discounts')]))


# ══════════════════════════════════════════════════
#  اعطای رایگان دسته‌جمعی
# ══════════════════════════════════════════════════

async def _show_grant_menu(query):
    keyboard = [
        [InlineKeyboardButton("🎓 ادمین ارشد محتوا (از پروفایل کاربران)", callback_data='suba:grant_role:content_admin')],
    ]
    for role, label in db.ROLE_LABELS.items():
        if role == 'content_admin':
            continue  # از قبل بالا اضافه شد (منبع داده‌ش فرق داره: users.role نه admin_roles)
        keyboard.append([InlineKeyboardButton(label, callback_data=f'suba:grant_role:{role}')])
    keyboard.append([InlineKeyboardButton("📋 لیست آیدی دلخواه (چندتایی)", callback_data='suba:grant_list')])
    keyboard.append([InlineKeyboardButton("👤 دستی با آیدی/یوزرنیم (تک‌نفره)", callback_data='suba:user_search')])
    keyboard.append(_back())
    await query.edit_message_text(
        "🎁 <b>اعطای اشتراک رایگان دسته‌جمعی</b>\n\n"
        "یه نقش انتخاب کن، یا برای گروه دلخواه (مثلاً نماینده‌های چند دانشگاه)\n"
        "از «📋 لیست آیدی دلخواه» استفاده کن:",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _prompt_grant_list(query, context):
    context.user_data['mode'] = 'suba_grant_list_ids'
    await query.edit_message_text(
        "📋 <b>لیست دانشجویان</b>\n\n"
        "هر نفر رو توی یه خط جدا بفرست — هرکدوم از این سه حالت می‌تونه باشه:\n"
        "• آیدی عددی تلگرام\n"
        "• یوزرنیم (با یا بدون @)\n"
        "• اسم دقیق ثبت‌شده توی ربات\n\n"
        "مثال:\n<code>123456789\n@ali_r\nسارا محمدی</code>",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup([_back('suba:grant')])
    )


async def handle_grant_list_ids_text(update, context):
    """
    FIX مهم: قبلاً فقط آیدی عددی قبول می‌کرد و هر چیز دیگه (یوزرنیم،
    اسم) رو بی‌صدا نادیده می‌گرفت — حتی با split روی فاصله که اسم‌های
    چندکلمه‌ای رو هم خراب می‌کرد. حالا هر خط می‌تواند آیدی عددی،
    یوزرنیم (با/بدون @)، یا اسم ثبت‌شده در ربات باشد؛ هر خط جدا پردازش
    و به کاربر واقعی متصل می‌شود.
    """
    context.user_data.pop('mode', None)
    raw = update.message.text.strip()
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        await update.message.reply_text("❌ چیزی وارد نشد.")
        return

    resolved, not_found, ambiguous = [], [], []
    for line in lines:
        if line.lstrip('+-').isdigit():
            resolved.append((int(line), line))
            continue
        matches = await db.search_users(line)
        if len(matches) == 1:
            resolved.append((matches[0]['user_id'], matches[0].get('name', line)))
        elif len(matches) == 0:
            not_found.append(line)
        else:
            ambiguous.append(line)

    if not resolved:
        await update.message.reply_text(
            "❌ هیچ‌کدوم پیدا نشدن. هر خط می‌تونه آیدی عددی، یوزرنیم (با یا بدون @)، "
            "یا اسم دقیق ثبت‌شده توی ربات باشه."
        )
        return

    ids = [uid for uid, _ in resolved]
    context.user_data['suba_grant_list'] = ids
    context.user_data['mode'] = 'suba_grant_list_days'

    lines_out = [f"✅ {len(resolved)} نفر پیدا شد:"]
    lines_out += [f"   • {name}" for _, name in resolved[:15]]
    if len(resolved) > 15:
        lines_out.append(f"   … و {len(resolved)-15} نفر دیگر")
    if ambiguous:
        lines_out.append(f"\n⚠️ {len(ambiguous)} مورد چند نتیجه داشت (نادیده گرفته شد): " + "، ".join(ambiguous[:5]))
    if not_found:
        lines_out.append(f"\n❌ {len(not_found)} مورد پیدا نشد: " + "، ".join(not_found[:5]))
    lines_out.append("\nحالا چند روز اشتراک رایگان بدیم؟ (فقط عدد)")
    await update.message.reply_text("\n".join(lines_out))


async def handle_grant_list_days_text(update, context):
    ids = context.user_data.pop('suba_grant_list', [])
    context.user_data.pop('mode', None)
    text = update.message.text.strip()
    if not ids or not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("❌ فقط یه عدد مثبت بفرست.")
        return
    days = int(text)
    count = 0
    for uid in ids:
        user = await db.get_user(uid)
        if not user:
            continue
        await db.sub_activate(uid, days, plan_name='🎁 اشتراک رایگان',
                               source='free_grant', granted_by=update.effective_user.id, extend=True)
        days_left = await db.sub_days_left(uid)
        await safe_send(
            context.bot, uid,
            f"🎁 <b>یه اشتراک رایگان بهت هدیه داده شد!</b>\n\n"
            f"⏳ {days_left} روز اعتبار داری.\nاز بخش «👤 پروفایل» می‌تونی چک کنی.",
            parse_mode='HTML'
        )
        count += 1
    skipped = len(ids) - count
    msg = f"✅ اشتراک رایگان {days} روزه به {count} نفر فعال شد."
    if skipped:
        msg += f"\n⚠️ {skipped} آیدی در دیتابیس پیدا نشد (احتمالاً هنوز /start نزده)."
    await update.message.reply_text(msg)
    await send_audit_log(
        context.bot, 'admin', 'ادمین ارشد', update.effective_user.id,
        "اعطای رایگان دسته‌جمعی (لیست دستی)", module='Subscription', severity='INFO',
        target_label=f"{count} نفر — {days} روز", tags=['اشتراک_رایگان']
    )


async def _prompt_grant_days(query, context, role: str):
    context.user_data['mode'] = 'suba_grant_days'
    context.user_data['suba_grant_role'] = role
    label = 'ادمین ارشد محتوا' if role == 'content_admin' else db.ROLE_LABELS.get(role, role)
    await query.edit_message_text(
        f"🎁 اعطا به «{label}»\n\nچند روز اشتراک رایگان بدیم؟ (فقط عدد)",
        reply_markup=InlineKeyboardMarkup([_back('suba:grant')])
    )


async def handle_grant_days_text(update, context):
    role = context.user_data.pop('suba_grant_role', None)
    context.user_data.pop('mode', None)
    text = update.message.text.strip()
    if not role or not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("❌ فقط یه عدد مثبت بفرست.")
        return
    days = int(text)

    if role == 'content_admin':
        target_uids = [u['user_id'] async for u in db.users.find({'role': 'content_admin'})]
    else:
        role_docs = await db.get_all_admin_roles()
        target_uids = [r['_id'] for r in role_docs if r.get('role') == role]

    if not target_uids:
        await update.message.reply_text("⚠️ هیچ کاربری با این نقش پیدا نشد.")
        return

    count = 0
    for uid in target_uids:
        await db.sub_activate(uid, days, plan_name='🎁 اشتراک رایگان',
                               source='free_grant', granted_by=update.effective_user.id, extend=True)
        days_left = await db.sub_days_left(uid)
        await safe_send(
            context.bot, uid,
            f"🎁 <b>یه اشتراک رایگان بهت هدیه داده شد!</b>\n\n"
            f"⏳ {days_left} روز اعتبار داری.\nاز بخش «👤 پروفایل» می‌تونی چک کنی.",
            parse_mode='HTML'
        )
        count += 1

    await update.message.reply_text(f"✅ اشتراک رایگان {days} روزه به {count} نفر فعال شد.")
    await send_audit_log(
        context.bot, 'admin', 'ادمین ارشد', update.effective_user.id,
        "اعطای رایگان دسته‌جمعی", module='Subscription', severity='INFO',
        target_label=f"{role} × {count} نفر — {days} روز", tags=['اشتراک_رایگان']
    )


# ══════════════════════════════════════════════════
#  callback اصلی
# ══════════════════════════════════════════════════

# ══════════════════════════════════════════
#  💳 درگاه زرین‌پال — مدیریت از ربات (W6)
# ══════════════════════════════════════════
async def _show_gateway(query):
    mid = (await db.get_setting('zarinpal_merchant_id', '') or '').strip()
    masked = (mid[:4] + "****" + mid[-4:]) if len(mid) >= 8 else ("****" if mid else "— (تنظیم نشده)")
    sb = await db.get_setting('zarinpal_sandbox', None)
    if sb is None: sb = not bool(mid)
    cb = (await db.get_setting('zarinpal_callback_url', '') or '').strip() or "— (پیش‌فرض از WEBAPP_URL)"
    enabled = await db.get_setting('zarinpal_enabled', True)
    if enabled is None: enabled = True
    status = "🟢 فعال" if (enabled and mid) else ("🟡 آزمایشی (mock) — بدون merchant" if not mid else "🔴 غیرفعال")
    mode = "سندباکس (sandbox.zarinpal.com)" if sb else "اصلی (api.zarinpal.com)"
    # docs link as url button
    kb = [
        [InlineKeyboardButton(f"وضعیت: {status}", callback_data='suba:gateway')],
        [InlineKeyboardButton(f"حالت: {mode}", callback_data='suba:gateway_toggle_sandbox')],
        [InlineKeyboardButton(f"درگاه: {'فعال' if enabled else 'غیرفعال'}", callback_data='suba:gateway_toggle_enabled')],
        [InlineKeyboardButton("✏️ Merchant ID (کلید زرین‌پال)", callback_data='suba:gateway_edit_merchant')],
        [InlineKeyboardButton("🔗 Callback URL", callback_data='suba:gateway_edit_callback')],
        [InlineKeyboardButton("🧪 تست اتصال", callback_data='suba:gateway_test')],
        [InlineKeyboardButton("📖 مستندات زرین‌پال", url="https://www.zarinpal.com/docs/howToUse/")],
        _back(),
    ]
    text = (
        f"💳 <b>درگاه پرداخت زرین‌پال</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🔑 Merchant: <code>{masked}</code>\n"
        f"🧪 حالت: {mode}\n"
        f"🔗 Callback: <code>{cb}</code>\n"
        f"⚙️ وضعیت کلی: {status}\n\n"
        f"💡 برای اتصال واقعی، Merchant ID ۳۶کاراکتری (UUID) را از پنل زرین‌پال بگیر و اینجا بگذار.\n"
        f"سندباکس = تست بدون پول واقعی (https://sandbox.zarinpal.com).\n"
        f"Callback باید https باشد و در پنل زرین‌پال هم ثبت شده باشد."
    )
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(kb))

async def _prompt_gateway_merchant(query, context):
    context.user_data['mode'] = 'suba_gateway_merchant'
    await query.edit_message_text("🔑 Merchant ID زرین‌پال را بفرست (۳۶ کاراکتری UUID) — برای پاک کردن و برگشت به mock، بنویس <code>clear</code> یا <code>mock</code>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup([_back('suba:gateway')]))

async def _prompt_gateway_callback(query, context):
    context.user_data['mode'] = 'suba_gateway_callback'
    await query.edit_message_text("🔗 آدرس Callback را بفرست (باید https:// باشد) — برای پیش‌فرض خالی بذار: بنویس <code>clear</code>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup([_back('suba:gateway')]))

async def handle_gateway_merchant_text(update, context):
    text = update.message.text.strip()
    context.user_data.pop('mode', None)
    if text.lower() in ("clear","mock","test","empty"):
        await db.set_setting('zarinpal_merchant_id', '')
        try:
            from payments.zarinpal import _clear_cfg_cache; _clear_cfg_cache()
        except: pass
        await update.message.reply_text("✅ Merchant پاک شد — حالت آزمایشی (mock) فعال است.")
        return
    if len(text) < 10:
        await update.message.reply_text("❌ Merchant خیلی کوتاه است. دوباره بفرست.")
        return
    await db.set_setting('zarinpal_merchant_id', text.strip())
    try:
        from payments.zarinpal import _clear_cfg_cache; _clear_cfg_cache()
    except: pass
    masked = text[:4] + "****" + text[-4:] if len(text)>=8 else "****"
    await update.message.reply_text(f"✅ ذخیره شد: <code>{masked}</code>", parse_mode='HTML')
    try:
        _au = await db.get_user(update.effective_user.id) or {}
        _an = _au.get('name','مدیر ارشد')
        _ar = await db.get_actor_role_label(update.effective_user.id)
        await send_audit_log(context.bot, 'admin', _an, update.effective_user.id, "ویرایش Merchant زرین‌پال", module='Payment', severity='HIGH', actor_role=_ar, after={'merchant_masked': masked}, tags=['درگاه_پرداخت'])
    except: pass

async def handle_gateway_callback_text(update, context):
    text = update.message.text.strip()
    context.user_data.pop('mode', None)
    if text.lower() in ("clear","empty","default"):
        await db.set_setting('zarinpal_callback_url', '')
        try:
            from payments.zarinpal import _clear_cfg_cache; _clear_cfg_cache()
        except: pass
        await update.message.reply_text("✅ Callback به پیش‌فرض (WEBAPP_URL) برگشت.")
        return
    cb = text.strip().rstrip("/")
    if not cb.startswith("https://") and not cb.startswith("http://"):
        await update.message.reply_text("❌ باید با https:// شروع شود.")
        return
    await db.set_setting('zarinpal_callback_url', cb)
    try:
        from payments.zarinpal import _clear_cfg_cache; _clear_cfg_cache()
    except: pass
    await update.message.reply_text(f"✅ Callback ذخیره شد:\n<code>{cb}</code>", parse_mode='HTML')

async def subscription_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid   = update.effective_user.id
    # 🌊 W10 — پنل اشتراک با پرمیشن (ADMIN_ID همیشه پاس می‌شود)
    try:
        _ok = await db.has_permission(uid, 'subscription.manage')
    except Exception:
        _ok = (uid == ADMIN_ID)
    if not _ok:
        await query.answer("❌ مجوز مدیریت اشتراک ندارید.", show_alert=True)
        return
    await query.answer()
    parts  = query.data.split(':')
    action = parts[1] if len(parts) > 1 else 'main'

    if action == 'main':
        await _show_main(query)
    elif action == 'gateway':
        await _show_gateway(query)
    elif action == 'gateway_toggle_sandbox':
        cur = await db.get_setting('zarinpal_sandbox', None)
        if cur is None:
            cur_mid = (await db.get_setting('zarinpal_merchant_id','') or '').strip()
            cur = not bool(cur_mid)
        await db.set_setting('zarinpal_sandbox', not cur)
        try:
            from payments.zarinpal import _clear_cfg_cache; _clear_cfg_cache()
        except: pass
        await _show_gateway(query)
    elif action == 'gateway_toggle_enabled':
        cur = await db.get_setting('zarinpal_enabled', True)
        if cur is None: cur = True
        await db.set_setting('zarinpal_enabled', not cur)
        try:
            from payments.zarinpal import _clear_cfg_cache; _clear_cfg_cache()
        except: pass
        await _show_gateway(query)
    elif action == 'gateway_edit_merchant':
        await _prompt_gateway_merchant(query, context)
    elif action == 'gateway_edit_callback':
        await _prompt_gateway_callback(query, context)
    elif action == 'gateway_test':
        mid = (await db.get_setting('zarinpal_merchant_id','') or '').strip()
        sb = await db.get_setting('zarinpal_sandbox', None)
        if sb is None: sb = not bool(mid)
        is_mock = not bool(mid)
        msg = f"🧪 تست: {'mock (بدون merchant)' if is_mock else ('sandbox' if sb else 'اصلی')} — merchant={'****' if mid else '—'}"
        await query.answer(msg, show_alert=True)

    elif action == 'toggle_enforce':
        cur = await db.get_setting('subscription_enforced', False)
        await db.set_setting('subscription_enforced', not cur)
        # 🌊 W7 — ماکرو روی پالیسی‌ها (تک‌منبع حقیقت)
        try:
            from core.access import invalidate_policy_cache
            _mode = "subscription" if not cur else "free"
            for _f in ("question_bank", "resources", "references"):
                await db.set_feature_policy(_f, {"access": _mode}, uid, "")
                invalidate_policy_cache(_f)
        except Exception:
            pass
        await send_audit_log(
            context.bot, 'admin', 'ادمین ارشد', uid,
            f"{'فعال‌سازی' if not cur else 'خاموش‌کردن'} اجباری اشتراک",
            module='Subscription', severity='HIGH', tags=['اشتراک_اجباری']
        )
        await _show_main(query)

    elif action == 'toggle_protect':
        cur = await db.get_setting('protect_content_enabled', True)
        await db.set_setting('protect_content_enabled', not cur)
        await send_audit_log(
            context.bot, 'admin', 'ادمین ارشد', uid,
            f"{'روشن‌کردن' if not cur else 'خاموش‌کردن'} محافظت کپی‌رایت فایل‌ها",
            module='Subscription', severity='INFO', tags=['محافظت_فایل']
        )
        await _show_main(query)

    elif action == 'plans':
        await _show_plans(query)
    elif action == 'plan_add':
        await _prompt_plan_add(query, context)
    elif action == 'plan_edit':
        await _prompt_plan_edit(query, context, parts[2])
    elif action == 'plan_toggle':
        _pt_old = await db.sub_plan_get(parts[2]) or {}
        await db.sub_plan_toggle(parts[2])
        try:
            _au = await db.get_user(uid) or {}
            _an = _au.get('name', 'مدیر ارشد')
            _ar = await db.get_actor_role_label(uid)
            _pt_new = await db.sub_plan_get(parts[2]) or {}
            await send_audit_log(context.bot, 'admin', _an, uid,
                f"{'فعال‌سازی' if _pt_new.get('active') else 'غیرفعال‌سازی'} پلن {_pt_new.get('name','')}", module='Subscription', severity='WARNING', actor_role=_ar,
                target_id=parts[2], target_type='plan', target_label=_pt_new.get('name',''),
                before={'active': _pt_old.get('active')}, after={'active': _pt_new.get('active')},
                tags=['پلن'])
        except Exception as _e:
            import logging; logging.getLogger(__name__).warning(f"plan_toggle audit failed: {_e}")
        await _show_plans(query)
    elif action == 'plan_del':
        _pd_old = await db.sub_plan_get(parts[2]) or {}
        if not await db.sub_plan_delete(parts[2]):
            await query.answer("❌ حذف پلن ناموفق بود؛ دوباره تلاش کن.",
                               show_alert=True)
            return
        try:
            _au = await db.get_user(uid) or {}
            _an = _au.get('name', 'مدیر ارشد')
            _ar = await db.get_actor_role_label(uid)
            await send_audit_log(context.bot, 'admin', _an, uid,
                f"حذف پلن {_pd_old.get('name','')}", module='Subscription', severity='HIGH', actor_role=_ar,
                target_id=parts[2], target_type='plan', target_label=_pd_old.get('name',''),
                tags=['پلن','حذف_پلن'])
        except Exception as _e:
            import logging; logging.getLogger(__name__).warning(f"plan_del audit failed: {_e}")
        await _show_plans(query)

    elif action == 'card':
        await _show_card(query)
    elif action == 'card_edit':
        await _prompt_card_edit(query, context)

    elif action == 'pending':
        await _show_pending(query)
    elif action == 'view_pay':
        await _resend_payment_for_review(query, context, parts[2])
    elif action == 'history':
        await _show_history(query, parts[2], int(parts[3]))
    elif action == 'subscribers':
        await _show_subscribers_list(query, int(parts[2]))

    elif action == 'user_search':
        await _prompt_user_search(query, context)
    elif action == 'user':
        await _show_user_detail(query, int(parts[2]))
    elif action == 'user_history':
        await _show_user_payment_history(query, int(parts[2]))
    elif action == 'manual_activate':
        await _prompt_manual_days(query, context, int(parts[2]))
    elif action == 'manual_quick':
        await _quick_activate(query, context, int(parts[2]), int(parts[3]))
    elif action == 'revoke':
        await _prompt_revoke_reason(query, context, int(parts[2]))

    elif action == 'discounts':
        await _show_discounts(query)
    elif action == 'disc_add':
        await _prompt_discount_add(query, context)
    elif action == 'disc_toggle':
        _dc_old = await db.discount_get(parts[2]) or {}
        await db.discount_toggle(parts[2])
        try:
            _au = await db.get_user(uid) or {}
            _an = _au.get('name', 'مدیر ارشد')
            _ar = await db.get_actor_role_label(uid)
            _dc_new = await db.discount_get(parts[2]) or {}
            await send_audit_log(context.bot, 'admin', _an, uid,
                f"{'فعال‌سازی' if _dc_new.get('active') else 'غیرفعال‌سازی'} کد تخفیف {_dc_new.get('code','')}", module='Subscription', severity='HIGH', actor_role=_ar,
                target_id=parts[2], target_type='discount', target_label=_dc_new.get('code',''),
                before={'active': _dc_old.get('active')}, after={'active': _dc_new.get('active')},
                tags=['تخفیف'])
        except Exception as _e:
            import logging; logging.getLogger(__name__).warning(f"disc_toggle audit failed: {_e}")
        await _show_discounts(query)
    elif action == 'disc_del':
        _dd_old = await db.discount_get(parts[2]) or {}
        await db.discount_delete(parts[2])
        try:
            _au = await db.get_user(uid) or {}
            _an = _au.get('name', 'مدیر ارشد')
            _ar = await db.get_actor_role_label(uid)
            await send_audit_log(context.bot, 'admin', _an, uid,
                f"حذف کد تخفیف {_dd_old.get('code','')}", module='Subscription', severity='HIGH', actor_role=_ar,
                target_id=parts[2], target_type='discount', target_label=_dd_old.get('code',''),
                tags=['تخفیف','حذف_تخفیف'])
        except Exception as _e:
            import logging; logging.getLogger(__name__).warning(f"disc_del audit failed: {_e}")
        await _show_discounts(query)
    # 🎟 موج D1 — کمپین: پیش‌نمایش/انتشار/آمار
    elif action == 'disc_prev':
        await _show_discount_preview(query, parts[2])
    elif action == 'disc_bcast':
        await _prompt_discount_broadcast(query, context, parts[2])
    elif action == 'disc_bcast_go':
        await _execute_discount_broadcast(query, context, parts[2], parts[3])
    elif action == 'disc_bcast_stop':
        # ⛔ توقف انتشار در حال اجرا — حلقه‌ی ارسال هر ۲۰ نفر وضعیت را می‌خواند
        bc = await db.discount_bcast_get(parts[2])
        if bc and bc.get('status') == 'sending':
            await db.discount_bcast_update(parts[2], {'status': 'cancelled'})
            await query.answer("⛔ درخواست توقف ثبت شد؛ ارسال در اولین گام متوقف می‌شود.",
                               show_alert=True)
        else:
            await query.answer("این انتشار دیگر در حال اجرا نیست.", show_alert=True)
    elif action == 'disc_stats':
        await _show_discount_stats(query, parts[2])

    elif action == 'grant':
        await _show_grant_menu(query)
    elif action == 'grant_role':
        await _prompt_grant_days(query, context, parts[2])
    elif action == 'grant_list':
        await _prompt_grant_list(query, context)


# ══════════════════════════════════════════════════
#  دیسپچر متن — همه‌ی حالت‌های suba_* از اینجا رد می‌شوند
# ══════════════════════════════════════════════════

TEXT_MODE_HANDLERS = {
    'suba_plan_add':        handle_plan_add_text,
    'suba_plan_edit':       handle_plan_edit_text,
    'suba_card':             handle_card_text,
    'suba_user_search':      handle_user_search_text,
    'suba_manual_days':      handle_manual_days_text,
    'suba_revoke_reason':    handle_revoke_reason_text,
    'suba_discount_add':     handle_discount_add_text,
    'suba_grant_days':       handle_grant_days_text,
    'suba_grant_list_ids':   handle_grant_list_ids_text,
    'suba_grant_list_days':  handle_grant_list_days_text,
    'suba_gateway_merchant': handle_gateway_merchant_text,
    'suba_gateway_callback': handle_gateway_callback_text,
}


async def subscription_admin_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get('mode', '')
    handler = TEXT_MODE_HANDLERS.get(mode)
    if handler:
        await handler(update, context)
