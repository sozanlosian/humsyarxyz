"""
💳 سیستم اشتراک — بخش دانشجو + بررسی رسید توسط ادمین
  ✅ چند پلن هم‌زمان (روز/قیمت مستقل)
  ✅ کد تخفیف درصدی
  ✅ فقط عکس اسکرین‌شات — بدون فایل/متن
  ✅ بررسی فقط توسط ADMIN_ID
  ✅ غیرفعال به‌صورت پیش‌فرض — کلید اجباری‌سازی در پنل ادمین
"""
import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db
from utils import ADMIN_ID as _ADMIN_ID_FALLBACK, safe_send, send_audit_log

logger = logging.getLogger(__name__)
ADMIN_ID = int(os.getenv('ADMIN_ID', '0')) or _ADMIN_ID_FALLBACK


def _fmt_price(p: int) -> str:
    return f"{p:,}".replace(',', '٬') + " تومان"


# ══════════════════════════════════════════════════
#  گیت دسترسی — نقطه‌ی واحدی که بخش منابع/بانک‌سوال صداش می‌زنن
# ══════════════════════════════════════════════════

async def has_access(uid: int) -> bool:
    """آیا این کاربر اجازه‌ی دسترسی به منابع/بانک‌سوال را دارد؟ — W8: تفویض به هسته"""
    try:
        from core.access import has_access as _core_has
        return (await _core_has(int(uid))).allowed
    except Exception:
        # fallback بدون هسته
        enforced = await db.get_setting('subscription_enforced', False)
        if not enforced:
            return True
        if int(uid) == ADMIN_ID:
            return True
        return await db.sub_is_active(int(uid))


async def feature_allowed(uid: int, feature: str) -> bool:
    """🌊 W7 — چک بولین فیچر برای ربات (thin روی core؛ هرگز raise نمی‌کند)."""
    try:
        from core.access import check_feature
        return (await check_feature(int(uid), feature)).allowed
    except Exception:
        return False


async def check_and_show_paywall(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                 uid: int, feature: str = "question_bank") -> bool:
    """
    اگر دسترسی داشت True برمی‌گرداند (ادامه‌ی مسیر عادی).
    اگر نداشت، خودش صفحه‌ی قفل را نشان می‌دهد و False برمی‌گرداند —
    فراخوان فقط کافیست چک کند و در صورت False چیز دیگری نفرستد.
    """
    if await feature_allowed(uid, feature):
        return True
    await show_paywall(update.message, uid, feature=feature)
    return False


# ══════════════════════════════════════════════════
#  صفحه‌ی قفل / انتخاب پلن
# ══════════════════════════════════════════════════

async def show_paywall(target, uid: int, edit: bool = False, feature: str = ""):
    plans = await db.sub_plan_list(only_active=True)
    # 🌊 W7 — سرخط فیچرمحور (پس‌رو سازگار: بدون فیچر همان متن قبلی)
    try:
        from core.features import FEATURE_CATALOG
        _flabel = (FEATURE_CATALOG.get(feature) or {}).get("label", "")
    except Exception:
        _flabel = ""
    discount = None
    if hasattr(target, 'get'):  # نباید پیش بیاد، فقط ایمنی
        pass

    if _flabel:
        header = (
            f"🔒 <b>«{_flabel}» مخصوص دانشجوهای مشترک است</b>\n\n"
            f"برای دسترسی به {_flabel}، یکی از پلن‌های زیر رو انتخاب کن:\n"
            "━━━━━━━━━━━━━━━━\n"
        )
    else:
        header = (
            "🔒 <b>این بخش مخصوص دانشجوهای مشترک است</b>\n\n"
            "برای دسترسی به منابع درسی و بانک سوال، یکی از پلن‌های زیر رو انتخاب کن:\n"
            "━━━━━━━━━━━━━━━━\n"
        )
    if not plans:
        text = header + "⚠️ فعلاً هیچ پلنی تعریف نشده. با ادمین در تماس باش."
        kb = InlineKeyboardMarkup([])
    else:
        keyboard = []
        for p in plans:
            price_txt = _fmt_price(p['price'])
            keyboard.append([InlineKeyboardButton(
                f"💳 {p['name']} — {p['days']} روزه — {price_txt}",
                callback_data=f"sub:plan:{p['_id']}"
            )])
        keyboard.append([InlineKeyboardButton("🎟 کد تخفیف دارم", callback_data='sub:discount')])
        # 🌊 W6/MISS-03 — دکمه‌ی trial فقط برای واجدین
        try:
            _trial = await db.trial_status(uid)
        except Exception:
            _trial = {"eligible": False}
        if _trial.get("eligible"):
            keyboard.append([InlineKeyboardButton(
                f"🎁 شروع {_trial.get('days', 7)} روز آزمایشی رایگان",
                callback_data='sub:trial')])
        # 🌊 GIFT — ورودی هدیه (feature flag از settings، بدون کد سخت)
        if str(await db.get_setting('gift_enabled', '1')) == '1':
            keyboard.append([InlineKeyboardButton(
                "🎁 خرید اشتراک هدیه برای یک دوست", callback_data='sub:gift')])
        text = header + "هر پلن رو بزن تا جزئیات پرداخت رو ببینی 👇"
        kb = InlineKeyboardMarkup(keyboard)

    if edit:
        await target.edit_text(text, parse_mode='HTML', reply_markup=kb)
    else:
        await target.reply_text(text, parse_mode='HTML', reply_markup=kb)


async def _show_plan_detail(query, context, plan_id: str, uid: int):
    plan = await db.sub_plan_get(plan_id)
    if not plan or not plan.get('active'):
        await query.answer("❌ این پلن دیگه در دسترس نیست.", show_alert=True)
        return

    price = plan['price']
    discount_code = context.user_data.get('sub_discount_code')
    final_price = price
    if discount_code:
        # 🎟 موج D1 — اعتبارسنجی با plan_id + user_id (plan-targeting + per-user limit)
        v = await db.discount_validate(discount_code, plan_id=str(plan['_id']), user_id=uid)
        if not v['ok']:
            context.user_data.pop('sub_discount_code', None)
            discount_code = None
        else:
            final_price = round(price * (100 - v['percent']) / 100)

    context.user_data['sub_plan_id']    = str(plan['_id'])
    context.user_data['sub_final_price'] = final_price
    context.user_data.pop('sub_mode', None)  # هنوز منتظر عکس نیستیم — اول باید قوانین تأیید بشه

    await _show_rules(query, plan_id)


# ══════════════════════════════════════════════════
#  ✅ قوانین و تعهدنامه — مرحله‌ی اجباری قبل از دیدن شماره کارت
# ══════════════════════════════════════════════════

RULES_TEXT = (
    "📜 <b>قبل از پرداخت، این قوانین رو حتماً بخون</b>\n"
    "━━━━━━━━━━━━━━━━\n\n"
    "1. فایل‌های منابع و بانک سوال فقط برای استفاده‌ی <b>شخصی خودت</b>ه.\n"
    "فوروارد کردن، اشتراک‌گذاری یا ارسال به هر شخص دیگه (حتی همکلاسی) "
    "به هر شکلی (تلگرام، گروه، فضای مجازی) <b>ممنوعه</b>.\n\n"
    "2. اگه به هر دلیلی بخشی از محتوا رو جای دیگه استفاده کردی، "
    "<b>ذکر منبع (هامزیار)</b> الزامیه.\n\n"
    "3. 🚫 <b>هرگونه نقض این قوانین (فوروارد/کپی/انتشار بدون منبع) "
    "= بن دائم و خودکار از ربات + لغو فوری اشتراک، بدون بازگشت وجه.</b>\n"
    "هیچ عذر یا استثنایی («فقط برای یه نفر فرستادم»، «نمی‌دونستم» و امثالش) "
    "پذیرفته نیست.\n\n"
    "4. قبل از ارسال رسید، مطمئن شو مبلغ درست و کامل واریز شده — "
    "رسید با مبلغ اشتباه رد می‌شه.\n\n"
    "5. لغو اشتراک به‌خاطر نقض قوانین، غیرقابل اعتراضه.\n\n"
    "━━━━━━━━━━━━━━━━\n"
    "با زدن دکمه‌ی زیر، یعنی این قوانین رو خوندی و قبول داری ✅"
)


async def _show_rules(query, plan_id: str):
    keyboard = [
        [InlineKeyboardButton("✅ خوندم و قبول دارم، برو مرحله‌ی بعد", callback_data=f'sub:agree:{plan_id}')],
        [InlineKeyboardButton("🔙 بازگشت به پلن‌ها", callback_data='sub:back')],
    ]
    await query.edit_message_text(RULES_TEXT, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _gateway_status() -> dict:
    """🌊 W2 — وضعیت درگاه برای دکمه‌ی پرداخت آنلاین ربات (فقط boolean؛ بدون secret)."""
    try:
        from payments.zarinpal import gateway_public_status
        return await gateway_public_status()
    except Exception:
        return {"online_pay_enabled": False, "mock": False}


def _bot_gateway_callback() -> str:
    """🌊 W2 — کال‌بک درگاه برای پرداخت‌های ربات (مسیر API که به مینی‌اپ ریدایرکت می‌کند)."""
    base = (os.getenv("ZARINPAL_CALLBACK_URL") or os.getenv("WEBAPP_URL") or "").strip().rstrip("/")
    if base.startswith("http"):
        return f"{base}/api/subscription/zarinpal/callback"
    return ""


async def _zarinpal_start(query, context, uid: int, kind: str, ref: str):
    """🌊 W2 — شروع پرداخت آنلاین (plan یا topup)؛ آینه‌ی منطق API."""
    from payments.zarinpal import zarinpal_request as _zp_req
    gw = await _gateway_status()
    if not gw.get("online_pay_enabled"):
        await query.answer("پرداخت آنلاین فعلاً فعال نیست.", show_alert=True)
        return
    if await db.sub_payment_has_pending(uid):
        await query.answer("یه پرداخت در انتظار داری؛ اول اون مشخص بشه.", show_alert=True)
        return
    gift_to = 0
    gift_message = ""
    code = None
    percent = None
    if kind == "plan":
        plan = await db.sub_plan_get(ref)
        if not plan or not plan.get("active"):
            await query.answer("❌ این پلن دیگه در دسترس نیست.", show_alert=True)
            return
        gift_to = int(context.user_data.get("sub_gift_to") or 0)
        gift_message = str(context.user_data.get("sub_gift_message") or "")[:300]
        if gift_to:
            if str(await db.get_setting("gift_enabled", "1")) != "1":
                await query.answer("خرید هدیه فعلاً غیرفعال است.", show_alert=True)
                return
            if gift_to == uid:
                await query.answer("هدیه به خودت مجاز نیست.", show_alert=True)
                return
            rec = await db.get_user(gift_to)
            if not rec or rec.get("suspended"):
                context.user_data.pop("sub_gift_to", None)
                await query.answer("گیرنده‌ی هدیه پیدا نشد.", show_alert=True)
                return
        code = (context.user_data.get("sub_discount_code") or "").strip().upper() or None
        price = max(0, int(plan.get("price") or 0))
        if code:
            v = await db.discount_validate(code, plan_id=str(plan["_id"]), user_id=uid)
            if not v.get("ok"):
                await query.answer(v.get("reason") or "کد تخفیف معتبر نیست.", show_alert=True)
                return
            percent = int(v.get("percent") or 0)
            price = round(price * (100 - percent) / 100)
        if price <= 0:
            await query.answer("این خرید رایگان است؛ از مسیر خرید رایگان اقدام کن.", show_alert=True)
            return
        if gift_to and price <= 0:
            await query.answer("کد ۱۰۰٪ با هدیه ترکیب نمی‌شود.", show_alert=True)
            return
        plan_id, plan_name = str(plan["_id"]), plan.get("name", "")
        desc = f"اشتراک {plan_name} هامشیار"
        idem = f"zpb:{uid}:{plan_id[:8]}:{price}"
        back_cb, back_label = "sub:back", "🔙 بازگشت به پلن‌ها"
    else:
        tmin, tmax = await _topup_bounds()
        try:
            price = int(ref)
        except (TypeError, ValueError):
            price = 0
        if not tmin <= price <= tmax:
            await query.answer(f"مبلغ شارژ باید بین {tmin:,} و {tmax:,} تومان باشد.", show_alert=True)
            return
        plan_id, plan_name = "wallet_topup", "شارژ کیف پول"
        desc = f"شارژ کیف پول هامشیار — کاربر {uid}"
        idem = f"zpb:{uid}:topup:{price}"
        back_cb, back_label = "sub:wallet", "🔙 بازگشت به کیف پول"
    try:
        zp = await _zp_req(price, desc, _bot_gateway_callback())
    except Exception as e:
        await query.answer(f"درگاه پاسخ نداد؛ دوباره تلاش کن. ({e})", show_alert=True)
        return
    authority = zp["authority"]
    try:
        pid = await db.sub_payment_create_zarinpal(
            uid, plan_id, plan_name, price, price, authority,
            discount_code=code, discount_percent=percent, idem_key=idem)
        if gift_to:
            from bson import ObjectId
            await db.sub_payments.update_one(
                {"_id": ObjectId(pid)},
                {"$set": {"gift": {"to": gift_to, "message": gift_message, "activated_at": None}}})
        try:
            _rz = await db.get_actor_role_label(uid)
        except Exception:
            _rz = "student"
        try:
            await send_audit_log(None, "user", (await db.get_user(uid) or {}).get("name", str(uid)), uid,
                                 "درخواست پرداخت آنلاین (ربات)", module="Subscription", severity="INFO",
                                 actor_role=_rz, target_id=str(pid), target_type="sub_payment",
                                 target_label=plan_name[:60], after={"final_price": price}, tags=["مالی", "ربات"])
        except Exception:
            pass
    except Exception as e:
        if code:
            try:
                await db.discount_release(code, user_id=uid)
            except Exception:
                pass
        await query.answer(f"ثبت پرداخت ناموفق بود؛ دوباره تلاش کن. ({e})", show_alert=True)
        return
    context.user_data.pop("sub_mode", None)
    context.user_data["sub_zp_authority"] = authority
    mock_note = "\n\n<i>حالت نمایشی درگاه فعال است (پرداخت واقعی انجام نمی‌شود).</i>" if zp.get("mock") else ""
    gift_line = f"🎁 هدیه برای: <b>{(await db.get_user(gift_to) or {}).get('name', '—')}</b>\n" if gift_to else ""
    text = (
        f"⚡ <b>پرداخت آنلاین — {plan_name}</b>\n\n"
        f"{gift_line}"
        f"💰 مبلغ: <b>{_fmt_price(price)}</b>\n\n"
        f"۱️⃣ دکمه‌ی «پرداخت در زرین‌پال» رو بزن و پرداخت رو کامل کن.\n"
        f"۲️⃣ برگرد همینجا و «پرداخت کردم، بررسی کن» رو بزن.\n\n"
        f"<i>این لینک ۱ ساعت اعتبار دارد.</i>{mock_note}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 پرداخت در زرین‌پال", url=zp["url"])],
        [InlineKeyboardButton("✅ پرداخت کردم، بررسی کن", callback_data=f"sub:zchk:{authority}")],
        [InlineKeyboardButton(back_label, callback_data=back_cb)],
    ])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


async def _zarinpal_check(query, context, uid: int, authority: str):
    """🌊 W2 — بررسی نتیجه‌ی پرداخت آنلاین؛ آینه‌ی منطق API (verify)."""
    from payments.zarinpal import zarinpal_verify as _zp_v
    authority = (authority or "").strip()
    doc = await db.sub_payment_find_by_authority(authority)
    if not doc:
        await query.answer("پرداخت پیدا نشد.", show_alert=True)
        return
    if int(doc.get("user_id") or 0) != uid:
        await query.answer("این پرداخت متعلق به شما نیست.", show_alert=True)
        return
    status = doc.get("status")
    if status == "approved":
        await query.answer("این پرداخت قبلاً تأیید و فعال شده است ✅", show_alert=True)
        await _show_my_status(query, uid)
        return
    if status != "zarinpal_pending":
        await query.answer("این پرداخت منقضی یا بسته شده؛ یک پرداخت جدید بساز.", show_alert=True)
        return
    amount = int(doc.get("final_price") or doc.get("price") or 0)
    try:
        zp = await _zp_v(authority, amount)
    except Exception as e:
        await query.answer(f"خطا در استعلام درگاه؛ دوباره تلاش کن. ({e})", show_alert=True)
        return
    if not zp.get("ok"):
        await query.answer("پرداخت هنوز تأیید نشده (لغو شده یا ناقص است).", show_alert=True)
        return
    code = (doc.get("discount_code") or "").strip().upper() or None
    # 🌊 W3 — آینه‌ی API: پول گرفته شده پس approve + پرچم overrun.
    discount_overrun = False
    if code:
        consumed = await db.discount_consume(code, user_id=uid)
        if not consumed:
            discount_overrun = True
    ref_id = str(zp.get("ref_id") or "")
    res = await db.sub_payment_verify_zarinpal(authority, ref_id, amount)
    if not res.get("ok"):
        if code:
            try:
                await db.discount_release(code, user_id=uid)
            except Exception:
                pass
        if res.get("already"):
            await _show_my_status(query, uid)
            return
        await query.answer(res.get("reason") or "تأیید هم‌زمان — دوباره تلاش کن.", show_alert=True)
        return
    if discount_overrun:
        try:
            await db.sub_payment_mark_discount_overrun(authority)
            try:
                _rz2 = await db.get_actor_role_label(uid)
            except Exception:
                _rz2 = "student"
            await send_audit_log(None, "user", (await db.get_user(uid) or {}).get("name", str(uid)), uid,
                                 "تأیید پرداخت آنلاین با تخفیف خارج از ظرفیت (ربات)", module="Subscription",
                                 severity="HIGH", actor_role=_rz2, target_id=str(doc["_id"]),
                                 target_type="sub_payment", target_label=(doc.get("plan_name") or "")[:60],
                                 after={"discount_overrun": True}, tags=["مالی", "ربات", "مغایرت"])
        except Exception:
            pass
    context.user_data.pop("sub_zp_authority", None)
    context.user_data.pop("sub_gift_to", None)
    context.user_data.pop("sub_gift_message", None)
    context.user_data.pop("sub_discount_code", None)
    context.user_data.pop("sub_final_price", None)
    from utils import fmt_jalali_dt as _fmt_jalali_dt
    act = res.get("activation") or {}
    is_topup = str(doc.get("plan_id") or "") == "wallet_topup"
    if is_topup:
        balance = int((await db.wallet_get_for_user_id(uid) or {}).get("balance", 0))
        text = (
            f"💰 <b>کیف پولت شارژ شد!</b>\n\n"
            f"➕ مبلغ: {_fmt_price(amount)}\n"
            f"👛 موجودی فعلی: <b>{_fmt_price(balance)}</b>\n"
            f"🧾 شماره پیگیری: <code>{ref_id}</code>"
        )
        back = "sub:wallet"
    else:
        gift = doc.get("gift") or {}
        if gift.get("to"):
            rec = await db.get_user(int(gift["to"])) or {}
            text = (
                f"🎁 <b>هدیه‌ات فعال شد!</b>\n\n"
                f"اشتراک «{doc.get('plan_name', '')}» برای "
                f"<b>{rec.get('name', 'گیرنده')}</b> فعال شد ✅\n"
                f"🧾 شماره پیگیری: <code>{ref_id}</code>"
            )
        else:
            text = (
                f"🎉 <b>اشتراکت فعال شد!</b>\n\n"
                f"📦 {doc.get('plan_name', '')}\n"
                f"📅 تا: {_fmt_jalali_dt(act.get('end_date', ''), with_time=False)}\n"
                f"🧾 شماره پیگیری: <code>{ref_id}</code>"
            )
        back = "sub:my_status"
    try:
        await db.inbox_add(uid, "sub_payment", "✅ پرداخت آنلاین تأیید شد",
                           f"{doc.get('plan_name', '')} — {_fmt_price(amount)}",
                           link="/me/subscription")
    except Exception:
        pass
    await query.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data=back)]]))


async def _show_payment_details(query, context, plan_id: str):
    plan = await db.sub_plan_get(plan_id)
    if not plan or not plan.get('active'):
        await query.answer("❌ این پلن دیگه در دسترس نیست.", show_alert=True)
        return

    price = plan['price']
    discount_code = context.user_data.get('sub_discount_code')
    final_price = context.user_data.get('sub_final_price', price)

    # 🌊 GIFT — کد تخفیف ۱۰۰٪ با هدیه ترکیب نمی‌شود (همان قانون API)
    gift_to = context.user_data.get('sub_gift_to')
    if gift_to and final_price <= 0:
        context.user_data.pop('sub_gift_to', None)
        context.user_data.pop('sub_gift_message', None)
        await query.answer(
            "کد تخفیف ۱۰۰٪ با هدیه ترکیب نمی‌شه — برای خودت عادی بخر 😉",
            show_alert=True)
        return

    # FIX جدید: کد تخفیف ۱۰۰٪ = رایگان کامل — نیازی به رسید/اسکرین‌شات
    # نیست، همون لحظه فعال می‌شه (منطقاً چیزی برای پرداخت نمانده که
    # عکسش گرفته شود).
    if final_price <= 0:
        await _activate_free_via_discount(query, context, plan, discount_code)
        return

    discount_line = ''
    if discount_code:
        discount_line = f"🎟 کد <code>{discount_code}</code> اعمال شد\n"

    card_num   = await db.get_setting('subscription_card_number', '—')
    card_owner = await db.get_setting('subscription_card_owner', '—')

    price_line = (f"<s>{_fmt_price(price)}</s> ➜ <b>{_fmt_price(final_price)}</b>"
                  if discount_code else f"<b>{_fmt_price(price)}</b>")

    # 🌊 GIFT — خط گیرنده؛ گیرنده از لحظه‌ی انتخاب «قفل» شده و
    # در لحظه‌ی ثبت رسید هم دوباره سرور-ساید اعتبارسنجی می‌شود.
    gift_line = ''
    if gift_to:
        _rec = await db.get_user(gift_to)
        if _rec:
            gift_line = f"🎁 هدیه برای: <b>{_rec.get('name', '—')}</b>\n"
        else:
            gift_to = None
            context.user_data.pop('sub_gift_to', None)
            context.user_data.pop('sub_gift_message', None)

    text = (
        f"💳 <b>{plan['name']}</b> — {plan['days']} روزه\n\n"
        f"{gift_line}"
        f"{discount_line}"
        f"💰 مبلغ: {price_line}\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📇 شماره کارت:\n<code>{card_num}</code>\n"
        f"👤 به نام: {card_owner}\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"بعد از واریز، <b>فقط عکس رسید/اسکرین‌شات</b> رو همینجا بفرست.\n"
        f"بعد از تأیید ادمین، اشتراکت فوراً فعال می‌شه ✅\n\n"
        f"<i>یادت باشه: قوانین ذکرشده در مرحله‌ی قبل رو قبول کردی 📜</i>"
    )
    keyboard = []
    # 🌊 W2 — پرداخت آنلاین (هدیه هم پشتیبانی می‌شود؛ اعتبارسنجی سمت سرور)
    if (await _gateway_status()).get("online_pay_enabled"):
        keyboard.append([InlineKeyboardButton(
            "⚡ پرداخت آنلاین (زرین‌پال)",
            callback_data=f"sub:zpay:{plan_id}")])
    # 💰 W6 — کیف پول روش پرداخت جدید است (هدیه فقط با رسید بانکی)
    if not gift_to:
        _w = await db.wallet_get_for_user_id(query.from_user.id)
        _wb = int((_w or {}).get('balance', 0))
        keyboard.append([InlineKeyboardButton(
            f"💰 خرید با کیف پول (موجودی: {_fmt_price(_wb)})",
            callback_data=f"sub:wpay:{plan_id}")])
    keyboard.append(
        [InlineKeyboardButton("🔙 بازگشت به پلن‌ها", callback_data='sub:back')])
    context.user_data['sub_mode'] = 'awaiting_screenshot'
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _activate_free_via_discount(query, context, plan: dict, discount_code: str):
    """FIX جدید: مسیر کد تخفیف ۱۰۰٪ — بدون رسید، بدون بررسی ادمین، فعال‌سازی آنی

    🎟 موج D1 — ترتیب امن: validate مجدد → مصرف اتمیک → فعال‌سازی.
    اگر در کسری از ثانیه‌ی بین انتخاب پلن و این لحظه ظرفیت پر شده باشد،
    مصرف شکست می‌خورد و فعال‌سازی انجام نمی‌شود (نشتی ظرفیت = صفر)."""
    uid = query.from_user.id
    for k in ('sub_mode', 'sub_plan_id', 'sub_final_price', 'sub_discount_code'):
        context.user_data.pop(k, None)

    _percent = None
    if discount_code:
        # اعتبارسنجی دوباره‌ی سمت سرور (deep-link/prefill هم هرگز اعتماد نیست)
        v = await db.discount_validate(discount_code, plan_id=str(plan['_id']), user_id=uid)
        if not v.get('ok'):
            await query.edit_message_text(
                f"⏰ {v.get('reason', 'این کد تخفیف دیگر معتبر نیست.')}",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💳 بازگشت به پلن‌ها", callback_data='sub:back')]]))
            return
        # مصرف اتمیک با user_id — ظرفیت سراسری ($expr) و سقف هر کاربر race-safe
        consumed = await db.discount_consume(discount_code, user_id=uid)
        if not consumed:
            await query.edit_message_text(
                "⏰ متأسفانه ظرفیت این کد همین حالا تکمیل شد.\n"
                "بدون کد هم می‌تونی ادامه بدی 👇",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💳 مشاهده‌ی پلن‌ها", callback_data='sub:back')]]))
            return
        _percent = consumed.get('percent')

    await db.sub_activate(uid, plan['days'], plan['name'], source='payment',
                           granted_by=0, extend=True,
                           plan_id=str(plan.get('_id', '') or ''))  # 🌊 W6/MISS-04
    if discount_code:
        # ثبت به‌عنوان یک تراکنش approved با مبلغ صفر — برای آمار و تاریخچه
        pid = await db.sub_payment_create(
            user_id=uid, plan_id=str(plan['_id']), plan_name=plan['name'],
            price=plan['price'], final_price=0, screenshot_file_id='',
            discount_code=discount_code, discount_percent=_percent,
        )
        try:
            _r1 = await db.get_actor_role_label(uid)
        except Exception: _r1="student"
        try: await __import__('utils').send_audit_log(None,'user',(await db.get_user(uid) or {}).get('name',str(uid)),uid,"ثبت رسید رایگان (ربات)",module='Subscription',severity='INFO',actor_role=_r1,target_id=str(pid),target_type='sub_payment',target_label=plan['name'][:60],after={"final_price":0},tags=['مالی','ربات'])
        except Exception: pass
        await db.sub_payment_decide(pid, approved=True, admin_id=0, note='کد تخفیف ۱۰۰٪ — خودکار')

    days_left = await db.sub_days_left(uid)
    text = (
        f"🎉 <b>اشتراکت با کد تخفیف رایگان فعال شد!</b>\n\n"
        f"📦 پلن: {plan['name']}\n"
        f"⏳ {days_left} روز اعتبار داری\n\n"
        f"از بخش «👤 پروفایل» هر وقت خواستی می‌تونی باقیمونده رو چک کنی."
    )
    # 🔔 موج ۴.۹۰ — اینباکس مینی‌اپ (فعال‌سازی با کد تخفیف)
    await db.inbox_add(uid, 'sub_activated',
        "🎉 اشتراکت با کد تخفیف فعال شد!",
        f"📦 پلن: {plan['name']} — {days_left} روز اعتبار داری.",
        link='/me/subscription')
    await query.edit_message_text(text, parse_mode='HTML')


# ══════════════════════════════════════════════════
#  کد تخفیف
# ══════════════════════════════════════════════════

async def _prompt_discount(query, context):
    context.user_data['sub_mode'] = 'awaiting_discount'
    await query.edit_message_text(
        "🎟 <b>کد تخفیف</b>\n\nکد رو تایپ کن و بفرست:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", callback_data='sub:back')]])
    )


async def discount_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    v = await db.discount_validate(code, user_id=update.effective_user.id)
    if not v['ok']:
        await update.message.reply_text(f"❌ {v['reason']}\n\nدوباره امتحان کن یا /cancel بزن.")
        return
    context.user_data['sub_discount_code'] = code
    context.user_data.pop('sub_mode', None)
    await update.message.reply_text(
        f"✅ کد <code>{code}</code> با {v['percent']}٪ تخفیف ثبت شد.\n"
        f"حالا یکی از پلن‌ها رو انتخاب کن:", parse_mode='HTML'
    )
    await show_paywall(update.message, update.effective_user.id)


async def _discount_deep_link(query, context, code: str, uid: int):
    """
    🎟 موج D1 — CTA پیام کمپین (sub:dcode:CODE):
    کد را از قبل در user_data قرار می‌دهد (Prefill) و کاربر مستقیم وارد
    paywall می‌شود. validate نهایی هنگام انتخاب پلن و پرداخت Server-side
    انجام می‌شود — این فقط ورود سریع است.
    """
    code = (code or '').strip().upper()
    v = await db.discount_validate(code, user_id=uid)
    if not v['ok']:
        await query.edit_message_text(
            f"⏰ <b>{v['reason']}</b>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💳 دیدن پلن‌های اشتراک", callback_data='sub:back')
            ]]))
        return
    context.user_data['sub_discount_code'] = code
    context.user_data.pop('sub_mode', None)
    await show_paywall(query.message, uid, edit=True)


# ══════════════════════════════════════════════════
#  دریافت اسکرین‌شات از دانشجو
# ══════════════════════════════════════════════════

# ══════════════════════════════════════════════════
#  🌊 GIFT — انتخاب گیرنده و پیام هدیه (حالت‌های متنی)
# ══════════════════════════════════════════════════

async def gift_recipient_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """جست‌وجوی حریم‌محور گیرنده: فقط نام و یوزرنیم نمایش داده می‌شود
    (قرارداد مشترک db.search_users — همان چیزی که ربات/وب استفاده
    می‌کنند). هیچ فیلد شخصی‌تری به payer نشان داده نمی‌شود."""
    text = (update.message.text or '').strip()
    if not text:
        return
    results = await db.search_users(text, limit=5)
    results = [r for r in results if r.get('user_id')]
    if not results:
        await update.message.reply_text(
            "🔍 کسی با این مشخصات پیدا نشد.\n"
            "اسم، @یوزرنیم یا آیدی عددی رو دوباره بفرست (لغو: /cancel)"
        )
        return
    if len(results) == 1:
        r = results[0]
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ بله، همینه",
                                 callback_data=f"sub:grsel:{r['user_id']}"),
            InlineKeyboardButton("🔙 نه، دوباره", callback_data='sub:gift'),
        ]])
        await update.message.reply_text(
            f"منظورت «{r.get('name') or '—'}» "
            f"(@{r.get('username') or 'بدون یوزرنیم'}) هست؟",
            reply_markup=kb)
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{r.get('name') or '—'} (@{r.get('username') or '—'}) — {r['user_id']}",
            callback_data=f"sub:grsel:{r['user_id']}")]
        for r in results
    ])
    await update.message.reply_text(
        "چند نفر پیدا شدن — گیرنده‌ی هدیه کدومشونه؟",
        reply_markup=kb)


async def gift_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (update.message.text or '').strip()[:300]
    context.user_data['sub_gift_message'] = msg
    context.user_data.pop('mode', None)
    await update.message.reply_text(
        "✅ پیامت ذخیره شد.\nحالا پلن هدیه رو انتخاب کن 👇")
    await show_paywall(update.message, update.effective_user.id)


async def screenshot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    # FIX جدید: جلوگیری از اسپم — تا رسید قبلی بررسی نشده، رسید جدید قبول نمی‌شه
    if await db.sub_payment_has_pending(uid):
        await update.message.reply_text(
            "⏳ یه رسید قبلی ازت در انتظار بررسیه.\n"
            "لطفاً صبر کن تا همون بررسی بشه، بعد اگه لازم بود رسید جدید بفرست."
        )
        for k in ('sub_mode', 'sub_plan_id', 'sub_final_price', 'sub_discount_code'):
            context.user_data.pop(k, None)
        return

    plan_id = context.user_data.get('sub_plan_id')
    plan = await db.sub_plan_get(plan_id) if plan_id else None
    if not plan:
        await update.message.reply_text("❌ اول باید یه پلن انتخاب کنی. /cancel بزن و دوباره امتحان کن.")
        return

    final_price = context.user_data.get('sub_final_price', plan['price'])
    discount_code = context.user_data.get('sub_discount_code')
    photo = update.message.photo[-1]

    # 🎟 موج D1 — مصرف کد در لحظه‌ی ثبت رسید (نه در تأیید ادمین) تا ظرفیت
    # کد دوره‌ی انتظار را هم پوشش دهد. اگر در این لحظه ظرفیت پر/کد نامعتبر
    # شده باشد، رسید باطل می‌شود تا کاربر با مبلغ اشتباه پرداخت نکند؛ در
    # رد رسید می‌آید (discount_release).
    discount_percent = None
    if discount_code:
        v = await db.discount_validate(discount_code, plan_id=str(plan['_id']), user_id=uid)
        consumed = v.get('ok') and await db.discount_consume(discount_code, user_id=uid)
        if not consumed:
            for k in ('sub_mode', 'sub_plan_id', 'sub_final_price', 'sub_discount_code'):
                context.user_data.pop(k, None)
            await update.message.reply_text(
                "⚠️ کد تخفیفت همین حالا نامعتبر یا تکمیل ظرفیت شد — رسیدت ثبت نشد.\n"
                "لطفاً قیمت را دوباره چک کن و در صورت تمایل رسید تازه بفرست.",
            )
            return
        discount_percent = consumed.get('percent')

    # 🌊 GIFT — گیرنده در لحظه‌ی ثبت رسید دوباره سرور-ساید چک می‌شود
    # (lock بعد از intent، اما اعتماد به کلاینت صفر). idem_key از
    # file_id عکس: آپدیت تکراری تلگرام = رسید دوم ساخته نمی‌شود.
    gift_to = context.user_data.get('sub_gift_to') or 0
    gift_message = context.user_data.get('sub_gift_message', '')
    if gift_to:
        rec = await db.get_user(gift_to)
        if not rec or gift_to == uid:
            for k in ('sub_mode', 'sub_plan_id', 'sub_final_price',
                      'sub_discount_code', 'sub_gift_to', 'sub_gift_message'):
                context.user_data.pop(k, None)
            await update.message.reply_text(
                "⚠️ گیرنده‌ی هدیه معتبر نیست — رسید ثبت نشد. "
                "از اول /start بزن."
            )
            return

    pid = await db.sub_payment_create(
        user_id=uid, plan_id=str(plan['_id']), plan_name=plan['name'],
        price=plan['price'], final_price=final_price,
        screenshot_file_id=photo.file_id, discount_code=discount_code,
        discount_percent=discount_percent,
        gift_to=gift_to, gift_message=gift_message,
        idem_key=f"bot:{uid}:{photo.file_id}",
    )
    try:
        _r2 = await db.get_actor_role_label(uid)
    except Exception: _r2="student"
    try: await __import__('utils').send_audit_log(None,'user',(await db.get_user(uid) or {}).get('name',str(uid)),uid,"ثبت رسید پرداخت (ربات)",module='Subscription',severity='INFO',actor_role=_r2,target_id=str(pid),target_type='sub_payment',target_label=plan['name'][:60],after={"final_price": final_price},tags=['مالی','ربات'])
    except Exception: pass

    for k in ('sub_mode', 'sub_plan_id', 'sub_final_price', 'sub_discount_code',
              'sub_gift_to', 'sub_gift_message'):
        context.user_data.pop(k, None)

    user = await db.get_user(uid)
    uname = f"@{user.get('username')}" if user and user.get('username') else '—'
    name  = user.get('name', update.effective_user.full_name) if user else update.effective_user.full_name
    reject_count = await db.sub_payment_reject_count(uid)
    warn_line = f"\n⚠️ این کاربر قبلاً {reject_count} بار رد شده\n" if reject_count > 0 else ""

    caption = (
        f"💳 <b>رسید پرداخت اشتراک جدید</b>\n\n"
        f"👤 {name} | {uname}\n"
        f"🆔 <code>{uid}</code>\n"
        f"📦 پلن: {plan['name']} ({plan['days']} روز)\n"
        f"💰 مبلغ: {_fmt_price(final_price)}"
        + (f" (کد {discount_code})" if discount_code else "") + "\n"
        + (f"🎁 هدیه برای: {rec.get('name', '—')} (<code>{gift_to}</code>)\n"
           if gift_to else "")
        + warn_line
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تأیید", callback_data=f"sub:appr:{pid}"),
        InlineKeyboardButton("❌ رد", callback_data=f"sub:rej:{pid}"),
    ]])
    try:
        sent = await context.bot.send_photo(
            ADMIN_ID, photo.file_id, caption=caption, parse_mode='HTML', reply_markup=kb
        )
        await db.sub_payment_set_admin_msg(pid, sent.message_id)
    except Exception as e:
        logger.error(f"sub_payment admin notify failed: {e}")

    await update.message.reply_text(
        "⏳ رسیدت برای ادمین ارسال شد.\nبه‌محض بررسی، نتیجه رو بهت اطلاع می‌دیم."
    )


# ══════════════════════════════════════════════════
#  🌊 W6.2 — شارژ کیف پول (همان معماری رسید بانکی خرید؛ بدون مسیر موازی)
# ══════════════════════════════════════════════════

TOPUP_AMOUNTS = (50_000, 100_000, 200_000, 500_000)


async def _topup_bounds() -> tuple:
    """کرانه‌های مبلغ — همان settings که اندپوینت API هم می‌خواند."""
    try:
        return (int(await db.get_setting('topup_min', '10000')),
                int(await db.get_setting('topup_max', '20000000')))
    except Exception:
        return 10_000, 20_000_000


async def _prompt_topup_amounts(query, context):
    context.user_data.pop('sub_mode', None)
    context.user_data.pop('sub_topup_amount', None)
    kb = [[InlineKeyboardButton(f"{_fmt_price(a)} تومان",
                                callback_data=f"sub:topamt:{a}")]
          for a in TOPUP_AMOUNTS]
    kb.append([InlineKeyboardButton("✏️ مبلغ دلخواه",
                                    callback_data="sub:topcustom")])
    kb.append([InlineKeyboardButton("🔙 بازگشت به کیف پول",
                                    callback_data="sub:wallet")])
    await query.edit_message_text(
        "💰 <b>شارژ کیف پول</b>\n\n"
        "مبلغ شارژ رو انتخاب کن؛ بعدش اطلاعات کارت و نحوه‌ی ارسال رسید "
        "نشونت داده می‌شه 👇",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(kb))


async def _prompt_topup_receipt(target, context, uid: int, amount: int,
                                is_query: bool):
    """نمایش اطلاعات واریز + ورود به حالت انتظار عکس رسید."""
    tmin, tmax = await _topup_bounds()
    if not tmin <= amount <= tmax:
        msg = (f"⚠️ مبلغ شارژ باید بین {_fmt_price(tmin)} و "
               f"{_fmt_price(tmax)} باشه.")
        if is_query:
            await target.answer(msg, show_alert=True)
        else:
            await target.reply_text(msg)
        return
    if await db.sub_payment_has_pending(uid):
        msg = ("⏳ یه رسید قبلی ازت در انتظار بررسیه؛ اول اون بررسی بشه، "
               "بعد می‌تونی رسید شارژ بفرستی.")
        if is_query:
            await target.answer(msg, show_alert=True)
        else:
            await target.reply_text(msg)
        return
    card_num = await db.get_setting('subscription_card_number', '—')
    card_owner = await db.get_setting('subscription_card_owner', '—')
    context.user_data['sub_mode'] = 'awaiting_topup_screenshot'
    context.user_data['sub_topup_amount'] = amount
    text = (
        f"💰 <b>شارژ کیف پول — {_fmt_price(amount)}</b>\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📇 شماره کارت:\n<code>{card_num}</code>\n"
        f"👤 به نام: {card_owner}\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"مبلغ <b>{_fmt_price(amount)}</b> رو واریز کن و <b>فقط عکس "
        f"رسید/اسکرین‌شات</b> رو همینجا بفرست.\n"
        f"بعد از تأیید ادمین، مبلغ فوراً به کیف پولت اضافه می‌شه ✅"
    )
    _kb_rows = []
    # 🌊 W2 — شارژ آنی با درگاه
    if (await _gateway_status()).get("online_pay_enabled"):
        _kb_rows.append([InlineKeyboardButton(
            "⚡ پرداخت آنلاین (زرین‌پال)",
            callback_data=f"sub:ztop:{amount}")])
    _kb_rows.append([InlineKeyboardButton("🔙 انصراف", callback_data="sub:wallet")])
    kb = InlineKeyboardMarkup(_kb_rows)
    if is_query:
        await target.edit_message_text(text, parse_mode='HTML',
                                       reply_markup=kb)
    else:
        await target.reply_text(text, parse_mode='HTML', reply_markup=kb)


async def topup_amount_text_handler(update: Update,
                                    context: ContextTypes.DEFAULT_TYPE):
    """مبلغ دلخواه — ارقام فارسی/عربی نرمال می‌شوند؛ کرانه سرور-ساید."""
    raw = (update.message.text or '').strip()
    table = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
    cleaned = raw.translate(table).replace(',', '').replace(' ', '')
    try:
        amount = int(cleaned)
    except ValueError:
        await update.message.reply_text(
            "❌ مبلغ رو فقط با عدد بفرست (مثلاً ۱۵۰۰۰۰) یا /cancel بزن.")
        return
    await _prompt_topup_receipt(update.message, context,
                                update.effective_user.id, amount,
                                is_query=False)


async def topup_screenshot_handler(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    """عکس رسید شارژ — دقیقاً همان الگوی screenshot_handler خرید:
    رسید یک sub_payment با plan_id='wallet_topup' است؛ تأیید ادمین در
    finalize_approved_payment اعتبار کیف پول می‌سازد."""
    uid = update.effective_user.id
    amount = int(context.user_data.get('sub_topup_amount') or 0)
    if amount <= 0:
        context.user_data.pop('sub_mode', None)
        await update.message.reply_text(
            "❌ اول مبلغ شارژ رو انتخاب کن. /cancel بزن و از «کیف پول» "
            "دوباره امتحان کن.")
        return
    if await db.sub_payment_has_pending(uid):
        for k in ('sub_mode', 'sub_topup_amount'):
            context.user_data.pop(k, None)
        await update.message.reply_text(
            "⏳ یه رسید قبلی ازت در انتظار بررسیه.\n"
            "لطفاً صبر کن تا همون بررسی بشه.")
        return
    photo = update.message.photo[-1]
    pid = await db.sub_payment_create(
        user_id=uid, plan_id='wallet_topup', plan_name='شارژ کیف پول',
        price=amount, final_price=amount, screenshot_file_id=photo.file_id,
        idem_key=f"bot:topup:{uid}:{photo.file_id}",
    )
    try:
        _r3 = await db.get_actor_role_label(uid)
    except Exception: _r3="student"
    try: await __import__('utils').send_audit_log(None,'user',(await db.get_user(uid) or {}).get('name',str(uid)),uid,"ثبت رسید شارژ کیف پول (ربات)",module='Subscription',severity='INFO',actor_role=_r3,target_id=str(pid),target_type='sub_payment',target_label="شارژ کیف پول",after={"amount": amount},tags=['مالی','ربات'])
    except Exception: pass
    for k in ('sub_mode', 'sub_topup_amount'):
        context.user_data.pop(k, None)

    user = await db.get_user(uid)
    uname = f"@{user.get('username')}" if user and user.get('username') else '—'
    name = (user.get('name', update.effective_user.full_name)
            if user else update.effective_user.full_name)
    reject_count = await db.sub_payment_reject_count(uid)
    warn_line = (f"\n⚠️ این کاربر قبلاً {reject_count} بار رد شده\n"
                 if reject_count > 0 else "")
    caption = (
        f"💰 <b>رسید شارژ کیف پول جدید</b>\n\n"
        f"👤 {name} | {uname}\n"
        f"🆔 <code>{uid}</code>\n"
        f"💰 مبلغ: {_fmt_price(amount)}\n"
        f"📌 تأیید = اعتبار به کیف پول کاربر (نه اشتراک)"
        + warn_line
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تأیید", callback_data=f"sub:appr:{pid}"),
        InlineKeyboardButton("❌ رد", callback_data=f"sub:rej:{pid}"),
    ]])
    try:
        sent = await context.bot.send_photo(
            ADMIN_ID, photo.file_id, caption=caption,
            parse_mode='HTML', reply_markup=kb)
        await db.sub_payment_set_admin_msg(pid, sent.message_id)
    except Exception as e:
        logger.error(f"topup admin notify failed: {e}")

    await update.message.reply_text(
        "⏳ رسید شارژت برای ادمین ارسال شد.\n"
        "به‌محض تأیید، مبلغ به کیف پولت اضافه می‌شه."
    )


# ══════════════════════════════════════════════════
#  callback اصلی — دکمه‌های sub:
# ══════════════════════════════════════════════════

async def subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = update.effective_user.id
    parts = query.data.split(':')
    action = parts[1] if len(parts) > 1 else ''

    if action == 'plan':
        await _show_plan_detail(query, context, parts[2], uid)

    elif action == 'agree':
        await _show_payment_details(query, context, parts[2])

    elif action == 'wpay':
        # 💰 W6 — صفحه‌ی تأیید قبل از کسر: موجودی + قیمت + موجودی پس از خرید
        await _wallet_confirm(query, context, parts[2] if len(parts) > 2 else '', uid)

    elif action == 'wbuy':
        await _wallet_buy(query, context, parts[2] if len(parts) > 2 else '', uid)

    # 🌊 W2 — پرداخت آنلاین زرین‌پال
    elif action == 'zpay':
        await _zarinpal_start(query, context, uid, 'plan', parts[2] if len(parts) > 2 else '')
    elif action == 'zchk':
        await _zarinpal_check(query, context, uid, parts[2] if len(parts) > 2 else '')
    elif action == 'ztop':
        await _zarinpal_start(query, context, uid, 'topup', parts[2] if len(parts) > 2 else '')

    elif action == 'wallet':
        _skip = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        await _show_wallet(query, uid, _skip)
    # 🌊 W6.2 — شارژ کیف پول
    elif action == 'topup':
        await _prompt_topup_amounts(query, context)
    elif action == 'topamt':
        _amt = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        await _prompt_topup_receipt(query, context, uid, _amt, is_query=True)
    elif action == 'topcustom':
        context.user_data['sub_mode'] = 'awaiting_topup_amount'
        context.user_data.pop('sub_topup_amount', None)
        await query.edit_message_text(
            "✏️ <b>مبلغ دلخواه</b>\n\nمبلغ شارژ (تومان) رو تایپ کن و بفرست:",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                "🔙 انصراف", callback_data="sub:wallet")]]))

    elif action == 'discount':
        await _prompt_discount(query, context)

    elif action == 'dcode':
        # 🎟 موج D1 — CTA کمپین: ورود مستقیم با کد پیش‌پُر‌شده
        await _discount_deep_link(query, context, parts[2] if len(parts) > 2 else '', uid)

    elif action == 'gift':
        # 🌊 GIFT — ورودی هدیه: اول گیرنده، بعد پیام، بعد پلن‌ها
        if str(await db.get_setting('gift_enabled', '1')) != '1':
            await query.answer("خرید هدیه فعلاً غیرفعال است", show_alert=True)
            return
        context.user_data.pop('sub_gift_to', None)
        context.user_data.pop('sub_gift_message', None)
        context.user_data['mode'] = 'gift_recipient'
        await query.edit_message_text(
            "🎁 <b>خرید اشتراک هدیه</b>\n\n"
            "اسم، @یوزرنیم یا آیدی عددی دانشجو رو بفرست تا پیداش کنم.\n\n"
            "<i>فقط نام و یوزرنیم افراد نمایش داده می‌شه — "
            "اطلاعات شخصی‌تر بهت نشون داده نمی‌شه.</i>\n\n"
            "برای لغو /cancel بزن.",
            parse_mode='HTML')

    elif action == 'grsel':
        # 🌊 GIFT — قفل‌کردن گیرنده بعد از تأیید صریح (lock پس از intent)
        try:
            rid = int(parts[2])
        except (IndexError, ValueError):
            await query.answer("خطا؛ دوباره امتحان کن.", show_alert=True)
            return
        if rid == uid:
            await query.answer(
                "هدیه به خودت یعنی خرید عادی 😉 از لیست پلن‌ها بخر.",
                show_alert=True)
            return
        rec = await db.get_user(rid)
        if not rec:
            await query.answer("این دانشجو پیدا نشد.", show_alert=True)
            return
        context.user_data['sub_gift_to'] = rid
        context.user_data['mode'] = 'gift_message'
        await query.edit_message_text(
            f"🎁 گیرنده: <b>{rec.get('name') or '—'}</b>\n\n"
            "می‌خوای پیامی همراه هدیه بفرستی؟ (حداکثر ۳۰۰ نویسه)\n"
            "پیامت رو بنویس، یا دکمه‌ی زیر رو بزن:",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                "بی‌خیال پیام ✋", callback_data='sub:gskip')]]))

    elif action == 'gskip':
        context.user_data.pop('sub_gift_message', None)
        context.user_data.pop('mode', None)
        await show_paywall(query.message, uid, edit=True)

    elif action == 'trial':
        # 🌊 W6/MISS-03 — دریافت trial از ربات (همان primitive مینی‌اپ)
        try:
            res = await db.trial_claim(uid)
        except ValueError as e:
            _msg = {
                'trial_disabled': '❌ دوره‌ی آزمایشی فعلاً فعال نیست.',
                'already_subscribed': 'ℹ️ اشتراک فعال داری؛ نیازی به trial نیست.',
                'already_used': '❌ قبلاً از دوره‌ی آزمایشی استفاده کرده‌ای.',
                'no_plan': '❌ فعلاً پلنی برای trial تعریف نشده.',
            }.get(str(e), '❌ خطای موقت؛ دوباره تلاش کن.')
            await query.answer(_msg, show_alert=True)
            return
        except Exception:
            await query.answer('❌ خطای موقت؛ دوباره تلاش کن.', show_alert=True)
            return
        await query.answer(f"🎉 {res['days']} روز اشتراک آزمایشی فعال شد!",
                           show_alert=True)
        await _show_my_status(query, uid)
        return

    elif action == 'back':
        context.user_data.pop('sub_mode', None)
        context.user_data.pop('sub_gift_to', None)
        context.user_data.pop('sub_gift_message', None)
        await show_paywall(query.message, uid, edit=True)

    elif action == 'my_status':
        await _show_my_status(query, uid)

    elif action == 'my_history':
        await _show_my_history(query, uid)

    # 🌊 W8/MISS-03 — خانواده
    elif action == 'family':
        await _show_family(query, context, uid)
    elif action == 'famcode':
        await _family_new_code(query, context, uid)
    elif action == 'famredeem':
        context.user_data['sub_mode'] = 'awaiting_family_code'
        await query.edit_message_text(
            "🎟 <b>ثبت کد دعوت خانواده</b>\n\nکد ۸ حرفی‌ای که مالک خانواده فرستاده رو تایپ کن و بفرست:",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                "🔙 انصراف", callback_data="sub:my_status")]]))
    elif action == 'famrm':
        await _family_remove_member(query, context, uid,
                                    parts[2] if len(parts) > 2 else '')

    elif action == 'appr' and uid == ADMIN_ID:
        await _admin_approve(query, context, parts[2])

    elif action == 'rej' and uid == ADMIN_ID:
        context.user_data['sub_reject_pid'] = parts[2]
        context.user_data['mode'] = 'sub_reject_reason'
        await query.message.reply_text(
            "✍️ دلیل رد رو بنویس (برای دانشجو ارسال می‌شه):"
        )


async def _admin_approve(query, context, pid: str):
    payment = await db.sub_payment_get(pid)
    if not payment or payment.get('status') != 'pending':
        await query.answer("این رسید قبلاً بررسی شده.", show_alert=True)
        return
    is_topup = str(payment.get('plan_id') or '') == 'wallet_topup'
    if not is_topup:
        plan = await db.sub_plan_get(payment['plan_id'])
        if not plan or int(plan.get('days', 0) or 0) <= 0:
            await query.answer("مدت این پلن نامعتبر است؛ اول پلن را اصلاح کن.",
                               show_alert=True)
            return

    # 🛡 AUDIT-A1 — اول «ادعا»ی تصمیم (گذار اتمیک pending→approved). اگر
    # هم‌زمان کسی همان رسید را بسته باشد نباید حتی یک روز اضافه شود؛
    # پیش از این، چکِ status و نوشتن دو فرمان جدا بودند و دو تأیید
    # پشت‌سرهم = دو دوره اشتراک برای یک رسید.
    if not await db.sub_payment_decide(pid, approved=True, admin_id=ADMIN_ID):
        await query.answer("این رسید هم‌زمان بررسی و بسته شد.", show_alert=True)
        return

    # 🌊 GIFT — فعال‌سازی از تنها نقطه‌ی مشترک (بات/وب یک‌جا):
    # رسید عادی → payer، رسید هدیه → recipient. اتمیک و یک‌بار.
    # 🌊 W6.2 — رسید شارژ → همان primitive، اعتبار کیف پول می‌سازد.
    res = await db.finalize_approved_payment(payment, ADMIN_ID)
    if is_topup:
        balance = int((await db.wallet_get_for_user_id(
            payment['user_id']) or {}).get('balance', 0))
        await db.inbox_add(payment['user_id'], 'wallet_topup',
            "💰 کیف پولت شارژ شد!",
            (f"رسید شارژ {_fmt_price(int(payment.get('final_price') or 0))} "
             f"تأیید شد؛ موجودی فعلی: {_fmt_price(balance)} تومان."),
            link='/me/subscription')
        await safe_send(
            context.bot, payment['user_id'],
            (f"💰 <b>کیف پولت شارژ شد!</b>\n\n"
             f"➕ مبلغ: {_fmt_price(int(payment.get('final_price') or 0))}\n"
             f"👛 موجودی فعلی: <b>{_fmt_price(balance)}</b>\n\n"
             f"حالا می‌تونی با کیف پول اشتراک بخری 💳"),
            parse_mode='HTML')
        try:
            await query.edit_message_caption(
                caption=query.message.caption + "\n\n✅ <b>تأیید شد</b>",
                parse_mode='HTML')
        except Exception:
            pass
        return
    target = res['target_uid']
    gift = payment.get('gift') or {}
    # 🎟 موج D1 — کد تخفیف در لحظه‌ی ثبت رسید مصرف شده؛ اینجا دیگر مصرف
    # مجدد نداریم (رفع باگ مصرف دوگانه). در رد رسید → discount_release.

    days_left = await db.sub_days_left(target)
    # 🔔 موج ۴.۹۰ — اینباکس مینی‌اپ (تأیید رسید → فعال‌سازی)
    await db.inbox_add(payment['user_id'], 'sub_activated',
        "✅ اشتراکت فعال شد!" if not gift else "✅ هدیه‌ات فعال شد!",
        (f"رسیدت تأیید شد؛ 📦 {payment['plan_name']} — {days_left} روز اعتبار داری."
         if not gift else
         f"هدیه‌ات برای کاربر {target} فعال شد؛ 📦 {payment['plan_name']}."),
        link='/me/subscription')
    await safe_send(
        context.bot, payment['user_id'],
        (f"✅ <b>اشتراکت فعال شد!</b>\n\n"
         f"📦 پلن: {payment['plan_name']}\n"
         f"⏳ {days_left} روز اعتبار داری\n\n"
         f"از بخش «👤 پروفایل» هر وقت خواستی می‌تونی باقیمونده رو چک کنی."
         if not gift else
         f"✅ <b>هدیه‌ات به مقصد رسید!</b>\n\n"
         f"📦 پلن: {payment['plan_name']}\n"
         f"🎁 اشتراک برای کاربر {target} فعال شد.\n\n"
         f"ممنون از مهربونیت 💚"),
        parse_mode='HTML'
    )
    if gift:
        # 🌊 گیرنده هم خبردار می‌شود — نوتیفیکیشن هرگز تراکنش را
        # برنمی‌گرداند؛ safe_send بی‌صدا شکست می‌خورد و قابل retry است.
        sender = await db.get_user(payment['user_id'])
        sname = (sender or {}).get('name') or f"کاربر {payment['user_id']}"
        await db.inbox_add(target, 'gift_activated',
            "🎁 هدیه‌ای برایت فعال شد!",
            f"{sname} اشتراک «{payment['plan_name']}» را به تو هدیه داد.",
            link='/me/subscription')
        await safe_send(
            context.bot, target,
            f"🎁 <b>هدیه‌ای برایت فعال شد!</b>\n\n"
            f"{sname} اشتراک «{payment['plan_name']}» رو بهت هدیه داد.\n"
            f"⏳ {days_left} روز اعتبار داری 💚",
            parse_mode='HTML'
        )
    try:
        await query.edit_message_caption(
            caption=query.message.caption + "\n\n✅ <b>تأیید شد</b>",
            parse_mode='HTML'
        )
    except Exception:
        pass

    # FIX جدید: تأیید پرداخت قبلاً هیچ لاگی نداشت — چون مستقیم با پول
    # سروکار داره باید مثل بقیه‌ی عملیات مالی ثبت بشه
    await send_audit_log(
        context.bot, 'admin', 'ادمین ارشد', ADMIN_ID,
        f"تأیید رسید پرداخت — {payment['plan_name']} ({_fmt_price(payment.get('final_price', 0))})",
        module='Subscription', severity='INFO',
        target_id=str(payment['user_id']), target_type='user',
        target_label=f"کاربر {payment['user_id']}", tags=['تایید_پرداخت']
    )


async def admin_reject_reason_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid = context.user_data.pop('sub_reject_pid', None)
    context.user_data.pop('mode', None)
    note = update.message.text.strip()
    if not pid:
        return
    payment = await db.sub_payment_get(pid)
    if not payment or payment.get('status') != 'pending':
        await update.message.reply_text("این رسید قبلاً بررسی شده.")
        return
    # 🛡 AUDIT-A1 — ادعای اتمیک؛ بازنده هیچ اثر جانبی ندارد، وگرنه یک کد
    # تخفیف دو بار آزاد می‌شود (ظرفیت جعلی).
    if not await db.sub_payment_decide(pid, approved=False, admin_id=update.effective_user.id, note=note):
        await update.message.reply_text("این رسید هم‌زمان بررسی و بسته شد.")
        return
    # 🎟 موج D1 — کد تخفیف در ثبت رسید مصرف شد؛ در رد، ظرفیت به کاربر
    # برمی‌گردد تا بتواند با رسید درست دوباره از همان کد استفاده کند
    if payment.get('discount_code'):
        await db.discount_release(payment['discount_code'], user_id=payment['user_id'])
    # 🧠 N1.2 — سینک‌فیکس: reject رسید فقط DM بود؛ آینه‌ی Inbox هم می‌نشیند
    # (DM از همان safe_send بعدی می‌رود — اینجا فقط آرشیو+Deep Link)
    await db.notify_user(payment['user_id'], 'payment_rejected',
        title='❌ رسیدت تأیید نشد',
        body=f'📝 دلیل: {note}\nرسید درست را از بخش اشتراک دوباره بفرست.',
        link='/me/subscription', dm=None)
    await safe_send(
        context.bot, payment['user_id'],
        f"❌ <b>رسیدت تأیید نشد</b>\n\n📝 دلیل: {note}\n\n"
        f"می‌تونی دوباره از بخش «📚 منابع» یا «🧪 بانک سوال» اقدام کنی و رسید جدید بفرستی.",
        parse_mode='HTML'
    )
    await update.message.reply_text("❌ رد شد و به دانشجو اطلاع داده شد.")

    # FIX جدید: رد پرداخت هم قبلاً لاگ نمی‌شد
    await send_audit_log(
        context.bot, 'admin', 'ادمین ارشد', update.effective_user.id,
        f"رد رسید پرداخت — {payment['plan_name']} — دلیل: {note}",
        module='Subscription', severity='INFO',
        target_id=str(payment['user_id']), target_type='user',
        target_label=f"کاربر {payment['user_id']}", tags=['رد_پرداخت']
    )


# ══════════════════════════════════════════════════
#  🧾 وضعیت کامل اشتراک من (صفحه‌ی اختصاصی، جزئیات کامل)
# ══════════════════════════════════════════════════

_SOURCE_LABELS = {
    'payment':      '💳 خریداری‌شده',
    'admin_manual': '🛠 فعال‌سازی دستی ادمین',
    'free_grant':   '🎁 اشتراک رایگان هدیه‌ای',
    'trial':        '🆓 دوره‌ی آزمایشی',
    'family':       '👨‍👩‍👧 خانواده',
}


async def _build_my_status(uid: int):
    from utils import fmt_jalali_dt, progress_bar
    s = await db.sub_get(uid)
    keyboard = []

    if not s or s.get('status') not in ('active', 'expired', 'revoked'):
        text = "💎 <b>اشتراک ویژه من</b>\n\n⚠️ فعلاً هیچ اشتراکی نداری."
        keyboard.append([InlineKeyboardButton("💳 خرید اشتراک", callback_data='sub:back')])

    elif s.get('status') == 'active' and await db.sub_is_active(uid):
        days_left  = await db.sub_days_left(uid)
        total_days = max(1, s.get('last_plan_days', days_left) or 1)
        pct        = min(100, round(days_left / total_days * 100))
        bar        = progress_bar(pct)
        source     = _SOURCE_LABELS.get(s.get('source', ''), '—')

        # FIX جدید: تاریخ تأیید (اگه از مسیر پرداخت با رسید فعال شده) هم نشون داده بشه
        approved_line = ''
        history = await db.sub_payment_history(uid)
        approved = next((p for p in history if p['status'] == 'approved'), None)
        if approved and approved.get('reviewed_at'):
            approved_line = f"✅ تاریخ تأیید: {fmt_jalali_dt(approved['reviewed_at'])}\n"

        text = (
            "💎 <b>اشتراک ویژه من</b>\n"
            "━━━━━━━━━━━━━━━━\n"
            f"📦 پلن: <b>{s.get('plan_name','—')}</b>\n"
            f"🎫 منبع: {source}\n"
            f"📅 تاریخ خرید: {fmt_jalali_dt(s.get('start_date',''), with_time=False)}\n"
            f"{approved_line}"
            f"📅 تاریخ انقضا: <b>{fmt_jalali_dt(s.get('end_date',''), with_time=False)}</b>\n\n"
            f"⏳ <b>{days_left} روز</b> باقی‌مانده\n"
            f"<code>[{bar}]</code> {pct}٪"
        )
        keyboard.append([InlineKeyboardButton("🔄 تمدید زودتر", callback_data='sub:back')])

    elif s.get('status') == 'revoked':
        text = (
            "💎 <b>اشتراک ویژه من</b>\n\n"
            "🚫 اشتراکت لغو شده.\n"
            f"📝 دلیل: {s.get('revoke_reason','—')}\n\n"
            "اگه فکر می‌کنی اشتباهیه، از «🎫 پشتیبانی» با ادمین در تماس باش."
        )
    else:  # expired
        text = (
            "💎 <b>اشتراک ویژه من</b>\n\n"
            "⌛ آخرین اشتراکت تموم شده.\n"
            f"📦 پلن قبلی: {s.get('plan_name','—')}\n"
            f"📅 تا: {fmt_jalali_dt(s.get('end_date',''), with_time=False)}"
        )
        keyboard.append([InlineKeyboardButton("🔄 تمدید کن", callback_data='sub:back')])

    # 🌊 W8/MISS-03 — ورودی خانواده: مالک/عضو → مدیریت؛ بی‌اشتراک → ثبت کد
    try:
        _s = await db.sub_get(uid)
        if _s and _s.get('source') == 'family' and _s.get('family_owner_id'):
            keyboard.append([InlineKeyboardButton(
                "👨‍👩‍👧 خانواده‌ی من", callback_data='sub:family')])
        elif _s and _s.get('status') == 'active' and await db.sub_is_active(uid):
            _seats = await db.family_plan_seats(uid)
            if _seats['total'] > 1:
                keyboard.append([InlineKeyboardButton(
                    f"👨‍👩‍👧 خانواده ({_seats['used']}/{_seats['total']-1} عضو)",
                    callback_data='sub:family')])
        else:
            keyboard.append([InlineKeyboardButton(
                "🎟 ثبت کد دعوت خانواده", callback_data='sub:famredeem')])
    except Exception:
        pass
    # 💰 W6 — کیف پول در صفحه‌ی وضعیت اشتراک (موجودی همیشه از بک‌اند)
    w = await db.wallet_get_for_user_id(uid)
    wb = int((w or {}).get('balance', 0))
    text += f"\n\n👛 <b>کیف پول:</b> {_fmt_price(wb)}"
    keyboard.append([InlineKeyboardButton("💰 کیف پول من", callback_data='sub:wallet')])
    keyboard.append([InlineKeyboardButton("🧾 تاریخچه‌ی پرداخت‌ها", callback_data='sub:my_history')])
    return text, keyboard


async def _show_my_status(query, uid: int):
    text, keyboard = await _build_my_status(uid)
    try:
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await query.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def show_my_status_msg(update):
    """FIX جدید: نسخه‌ی پیامی (نه callback) — برای دکمه‌ی «💎 اشتراک ویژه» توی منوی اصلی"""
    uid = update.effective_user.id
    text, keyboard = await _build_my_status(uid)
    await update.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_my_history(query, uid: int):
    from utils import fmt_jalali_dt
    history = await db.sub_payment_history(uid)
    status_icons = {'pending': '⏳', 'approved': '✅', 'rejected': '❌',
                    'zarinpal_pending': '💳', 'cancelled': '🚫', 'refunded': '↩️'}
    status_labels = {'zarinpal_pending': 'در انتظار پرداخت', 'cancelled': 'لغوشده',
                     'refunded': 'بازگشت وجه'}
    if not history:
        text = "🧾 <b>تاریخچه‌ی پرداخت‌ها</b>\n\nهنوز رسیدی ثبت نکردی."
    else:
        lines = ["🧾 <b>تاریخچه‌ی پرداخت‌ها</b>\n━━━━━━━━━━━━━━━━"]
        for p in history[:15]:
            icon = status_icons.get(p['status'], '•')
            date = fmt_jalali_dt(p.get('submitted_at', ''))
            _sl = status_labels.get(p['status'])
            lines.append(f"{icon} {p['plan_name']} — {_fmt_price(p['final_price'])} — {date}"
                         + (f" ({_sl})" if _sl else ""))
            if p['status'] == 'rejected' and p.get('review_note'):
                lines.append(f"   ↳ دلیل رد: {p['review_note']}")
        text = "\n".join(lines)
    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data='sub:my_status')]]
    try:
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await query.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


# ══════════════════════════════════════════════════
#  🌊 W8/MISS-03 — خانواده/گروهی (بات)
# ══════════════════════════════════════════════════

async def _show_family(query, context, uid: int):
    from utils import fmt_jalali_dt
    s = await db.sub_get(uid) or {}
    kb = []
    # نمای عضو
    if s.get('source') == 'family' and s.get('family_owner_id'):
        owner = await db.get_user(int(s['family_owner_id'])) or {}
        text = (
            "👨‍👩‍👧 <b>خانواده‌ی من</b>\n"
            "━━━━━━━━━━━━━━━━\n"
            f"👑 مالک: <b>{owner.get('name', '—')}</b>\n"
            f"📦 پلن: {s.get('plan_name', '—')}\n"
            f"📅 پایان: <b>{fmt_jalali_dt(s.get('end_date', ''), with_time=False)}</b>\n\n"
            "اشتراکت به مالک وصله؛ با پایان/لغو اشتراک مالک، دسترسی تو هم قطع می‌شه."
        )
        kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data='sub:my_status')])
    else:
        seats = await db.family_plan_seats(uid)
        if seats['total'] <= 1:
            text = ("👨‍👩‍👧 <b>خانواده</b>\n\nپلن فعلیت خانوادگی نیست؛ "
                    "با ارتقا به پلن خانواده می‌تونی اعضا اضافه کنی.")
            kb.append([InlineKeyboardButton("💳 مشاهده‌ی پلن‌ها", callback_data='sub:back')])
        else:
            members = await db.family_members(uid)
            lines = [f"👨‍👩‍👧 <b>خانواده‌ی من</b> — {seats['used']} از {seats['total']-1} صندلی پر",
                     "━━━━━━━━━━━━━━━━"]
            for m in members:
                if m.get('status') != 'active':
                    continue
                u = await db.get_user(int(m['_id'])) or {}
                lines.append(f"👤 {u.get('name', m['_id'])} — تا "
                             f"{fmt_jalali_dt(m.get('end_date', ''), with_time=False)}")
                kb.append([InlineKeyboardButton(
                    f"➖ حذف {u.get('name', m['_id'])}",
                    callback_data=f"sub:famrm:{m['_id']}")])
            if seats['left'] > 0:
                kb.append([InlineKeyboardButton("➕ ساخت کد دعوت جدید",
                                                callback_data='sub:famcode')])
            else:
                lines.append("\n⚠️ ظرفیت پر شده؛ برای عضو جدید یکی رو حذف کن.")
            text = "\n".join(lines)
        kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data='sub:my_status')])
    try:
        await query.edit_message_text(text, parse_mode='HTML',
                                      reply_markup=InlineKeyboardMarkup(kb))
    except Exception:
        await query.message.reply_text(text, parse_mode='HTML',
                                       reply_markup=InlineKeyboardMarkup(kb))


async def _family_new_code(query, context, uid: int):
    res = await db.family_code_create(uid)
    if not res.get('ok'):
        await query.answer(f"❌ {res.get('error')}", show_alert=True)
        return
    code = res['code']
    kb = [[InlineKeyboardButton("🔙 خانواده‌ی من", callback_data='sub:family')]]
    try:
        await query.edit_message_text(
            "🎟 <b>کد دعوت ساخته شد</b>\n\n"
            f"<code>{code[:4]}-{code[4:]}</code>\n\n"
            "این کد رو برای عضو جدید بفرست؛ یک‌بارمصرفه و با ثبت، "
            f"اشتراکش تا پایان اشتراک تو فعال می‌شه. (صندلی خالی: {res.get('seats_left', 0)})",
            parse_mode='HTML', reply_markup=InlineKeyboardMarkup(kb))
    except Exception:
        pass


async def _family_remove_member(query, context, uid: int, member: str):
    try:
        mid = int(member)
    except (TypeError, ValueError):
        await query.answer("❌ شناسه نامعتبر", show_alert=True)
        return
    res = await db.family_remove(uid, mid, uid)
    await query.answer(("✅ عضو حذف شد" if res.get('ok')
                        else f"❌ {res.get('error')}"), show_alert=True)
    await _show_family(query, context, uid)


async def family_code_text_handler(update, context):
    """🎟 ثبت کد دعوت خانواده (sub_mode=awaiting_family_code)."""
    context.user_data.pop('sub_mode', None)
    code = (update.message.text or '').strip()
    res = await db.family_redeem(code, update.effective_user.id)
    if res.get('ok'):
        from utils import fmt_jalali_dt
        await update.message.reply_text(
            "🎉 <b>به خانواده پیوستی!</b>\n\n"
            f"📦 پلن: {res.get('plan_name', '')}\n"
            f"📅 پایان: <b>{fmt_jalali_dt(res.get('end_date', ''), with_time=False)}</b>",
            parse_mode='HTML')
    else:
        await update.message.reply_text(f"❌ {res.get('error')}")


# ══════════════════════════════════════════════════
#  خط وضعیت برای پروفایل (نمای فشرده)
# ══════════════════════════════════════════════════

async def sub_status_line(uid: int) -> str:
    enforced = await db.get_setting('subscription_enforced', False)
    s = await db.sub_get(uid)
    if not enforced and (not s or s.get('status') != 'active'):
        return ""  # وقتی اجباری نیست و اشتراکی هم نداره، اصلاً خط اشتراک نشون نده
    if s and s.get('status') == 'active' and await db.sub_is_active(uid):
        days = await db.sub_days_left(uid)
        return f"💳 اشتراک: ✅ فعال — {days} روز باقی‌مانده\n"
    if s and s.get('status') == 'revoked':
        return "💳 اشتراک: ❌ لغوشده\n"
    return "💳 اشتراک: ⚠️ نداری — از «📚 منابع» می‌تونی فعالش کنی\n"


# ══════════════════════════════════════════════════════════════
#  💰 W6 — کیف پول داخلی (بات): تأیید → خرید → نمایش
#  منطق خرید فقط در سرویس واحد db.wallet_purchase است (API هم همان).
# ══════════════════════════════════════════════════════════════

async def _wallet_confirm(query, context, plan_id: str, uid: int):
    plan = await db.sub_plan_get(plan_id)
    if not plan or not plan.get('active'):
        await query.answer("❌ این پلن دیگه در دسترس نیست.", show_alert=True)
        return
    price = int(plan.get('price') or 0)
    # 🎟 W6 — کد تخفیف انتخاب‌شده در همین flow روی خرید کیف‌پولی هم اعمال
    # می‌شود؛ همان اعتبارسنجی سرور-ساید، بدون مصرف در این مرحله.
    discount_code = context.user_data.get('sub_discount_code')
    percent = 0
    if discount_code:
        v = await db.discount_validate(discount_code, plan_id=str(plan['_id']), user_id=uid)
        if v.get('ok'):
            percent = int(v.get('percent') or 0)
        else:
            discount_code = None
    final_price = round(price * (100 - percent) / 100) if percent else price
    if final_price <= 0:
        await query.answer(
            "کد تخفیف ۱۰۰٪ نیازی به کیف پول ندارد — از مسیر فعال‌سازی رایگان استفاده کن.",
            show_alert=True)
        return
    w = await db.wallet_get_for_user_id(uid)
    balance = int((w or {}).get('balance', 0))
    if balance < final_price:
        await query.answer(
            f"موجودی کافی نیست — {_fmt_price(balance)} از {_fmt_price(final_price)}",
            show_alert=True)
        return
    discount_line = (f"🎟 کد <code>{discount_code}</code> اعمال شد\n"
                     if discount_code else "")
    text = (
        f"💰 <b>خرید اشتراک با کیف پول</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📦 پلن: <b>{plan.get('name', '—')}</b> — {plan.get('days', '—')} روزه\n"
        f"{discount_line}"
        f"💵 مبلغ: <b>{_fmt_price(final_price)}</b>\n"
        f"👛 موجودی فعلی: {_fmt_price(balance)}\n"
        f"👛 موجودی پس از خرید: <b>{_fmt_price(balance - final_price)}</b>\n\n"
        f"با تأیید، مبلغ از کیف پول کسر و اشتراکت فعال می‌شه ✅"
    )
    keyboard = [
        [InlineKeyboardButton("✅ تأیید خرید", callback_data=f"sub:wbuy:{plan_id}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='sub:back')],
    ]
    try:
        await query.edit_message_text(
            text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await query.message.reply_text(
            text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _wallet_buy(query, context, plan_id: str, uid: int):
    """اجرا روی سرویس واحد db.wallet_purchase — همان منطق API.
    خطای مالی هرگز پنهان نمی‌شود؛ در شکست، موجودی دست‌نخورده می‌ماند."""
    from db.wallet import WalletError
    try:
        res = await db.wallet_purchase(
            uid, plan_id,
            discount_code=context.user_data.get('sub_discount_code'))
    except WalletError as e:
        await query.answer(str(e), show_alert=True)
        return
    except Exception:
        logger.exception(f"wallet buy failed uid={uid} plan={plan_id}")
        await query.answer(
            "خطا در خرید — موجودی شما دست‌نخورده است. دوباره امتحان کن.",
            show_alert=True)
        return
    w = await db.wallet_get_for_user_id(uid)
    balance = int((w or {}).get('balance', 0))
    text = (
        "🎉 <b>خرید موفق!</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"✅ اشتراک <b>{res.get('plan_name', '')}</b> با کیف پول فعال شد.\n"
        f"💵 کسرشده: {_fmt_price(int(res.get('amount') or 0))}\n"
        f"👛 موجودی کیف پول: <b>{_fmt_price(balance)}</b>"
    )
    keyboard = [[InlineKeyboardButton(
        "💎 وضعیت اشتراک من", callback_data='sub:my_status')]]
    try:
        await query.edit_message_text(
            text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await query.message.reply_text(
            text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_wallet(query, uid: int, skip: int = 0):
    """💰 موجودی + تراکنش‌ها — human-readable و صفحه‌بندی‌شده (کرانه‌دار)."""
    from utils import fmt_jalali_dt
    page = max(0, min(int(skip or 0), 200))
    s = await db.wallet_summary(uid)
    txs = await db.wallet_tx_list(uid, skip=page, limit=8)
    lines = ["💰 <b>کیف پول من</b>", "━━━━━━━━━━━━━━━━",
             f"👛 موجودی: <b>{_fmt_price(int(s.get('balance') or 0))}</b>"]
    if txs:
        lines.append("\n<b>تراکنش‌ها:</b>")
        for t in txs:
            sign = '➕' if t.get('direction') == 'credit' else '➖'
            lines.append(
                f"{sign} {_fmt_price(int(t.get('amount') or 0))} — "
                f"{t.get('label') or ''} ({fmt_jalali_dt(t.get('created_at', ''))})")
    else:
        lines.append("\nتراکنشی در این صفحه نیست.")
    keyboard = []
    # 🌊 W6.2 — شارژ کیف پول از سمت دانشجو (رسید بانکی → تأیید ادمین)
    keyboard.append([InlineKeyboardButton(
        "💰 شارژ کیف پول", callback_data="sub:topup")])
    if len(txs) == 8:
        keyboard.append([InlineKeyboardButton(
            "🕓 تراکنش‌های قدیمی‌تر", callback_data=f"sub:wallet:{page + 8}")])
    keyboard.append(
        [InlineKeyboardButton("💳 خرید اشتراک", callback_data='sub:back')])
    keyboard.append([InlineKeyboardButton(
        "🔙 بازگشت",
        callback_data=f"sub:wallet:{max(0, page - 8)}" if page
        else 'sub:my_status')])
    try:
        await query.edit_message_text(
            '\n'.join(lines), parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await query.message.reply_text(
            '\n'.join(lines), parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard))
