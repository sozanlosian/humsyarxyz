"""User subscription, discounts and payment receipt endpoints."""

import os

from datetime import datetime
from html import escape

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)

from pydantic import (
    BaseModel,
    Field,
)

from api.auth import (
    get_current_user,
)
try:
    from api.rate_limit import rate_limit_user
    from fastapi import Request
    _HAS_RL = True
except Exception:
    _HAS_RL = False
    rate_limit_user = None  # type: ignore

from api.telegram_send import (
    upload_and_get_file_id,
)

from bson import ObjectId
from database import db
from request_context import current_request_id

async def _sub_audit(actor: dict, action: str, *, before=None, after=None, target_id="", target_label="", severity="INFO", details: str = ""):
    try:
        uid = actor["id"] if isinstance(actor, dict) else actor
        name = (actor.get("_db") or {}).get("name") if isinstance(actor, dict) else str(uid)
        if isinstance(actor, dict):
            try:
                role = await db.get_actor_role_label(uid)
            except Exception:
                role = "student"
        else:
            role = "student"
        await db.log_action(uid, name or str(uid), role, action, "Subscription", category="subscription", severity=severity, target_id=str(target_id), target_type="sub_payment" if target_id else "subscription", target_label=target_label, before=before, after=after, details=details, tags=["مالی", "اشتراک"] )
    except Exception:
        pass
from time_utils import utc_now_iso


router = APIRouter()

MAX_RECEIPT_SIZE = (
    10 * 1024 * 1024
)


def normalize_plan(
    item: dict,
) -> dict:
    return {
        "id": str(
            item.get("_id", "")
        ),

        "name": str(
            item.get("name", "")
        ),

        "days": max(
            0,
            int(
                item.get(
                    "days",
                    0,
                )
                or 0
            ),
        ),

        "price": max(
            0,
            int(
                item.get(
                    "price",
                    0,
                )
                or 0
            ),
        ),

        # 🌊 W6/MISS-04 — ۰ = ارث از سقف سراسری
        "ai_daily_limit": max(
            0,
            int(
                item.get(
                    "ai_daily_limit",
                    0,
                )
                or 0
            ),
        ),

        # 🌊 W7
        "entitlements": dict(
            item.get(
                "entitlements",
                {},
            )
            or {}
        ),

        # 🌊 W8/MISS-03 — ظرفیت خانواده (۱ = شخصی)
        "max_members": max(
            1,
            int(
                item.get(
                    "max_members",
                    1,
                )
                or 1
            ),
        ),
    }


def normalize_payment(
    item: dict,
) -> dict:
    status = item.get(
        "status",
        "pending",
    )

    labels = {
        "pending":
            "در انتظار بررسی",

        "approved":
            "تأییدشده",

        "rejected":
            "ردشده",

        "zarinpal_pending":
            "در انتظار پرداخت",

        "cancelled":
            "لغوشده",

        "refunded":
            "بازگشت وجه",
    }

    price = max(
        0,
        int(
            item.get(
                "price",
                0,
            )
            or 0
        ),
    )

    final_price = max(
        0,
        int(
            item.get(
                "final_price",
                price,
            )
            or 0
        ),
    )

    return {
        "id": str(
            item.get("_id", "")
        ),

        "plan_name":
            item.get(
                "plan_name",
                "",
            ),

        "price":
            price,

        "final_price":
            final_price,

        "discount_code":
            item.get(
                "discount_code",
                "",
            ),

        "status":
            status,

        "status_label":
            labels.get(
                status,
                status,
            ),

        "submitted_at":
            str(
                item.get(
                    "submitted_at",
                    "",
                )
            )[:16],

        "reviewed_at":
            str(
                item.get(
                    "reviewed_at",
                    "",
                )
            )[:16],

        "review_note":
            item.get(
                "review_note",
                "",
            ),

        "method":
            item.get(
                "method",
                "",
            ),

        "authority": (
            item.get(
                "zarinpal_authority",
                "",
            )
            if status == "zarinpal_pending"
            else ""
        ),
    }


@router.get("/status")
async def get_status(
    user=Depends(
        get_current_user
    ),
):
    user_id = user["id"]

    subscription = (
        await db.sub_get(
            user_id
        )
    )

    active = (
        await db.sub_is_active(
            user_id
        )
    )

    days_left = (
        await db.sub_days_left(
            user_id
        )
        if active
        else 0
    )

    plans = (
        await db.sub_plan_list(
            only_active=True
        )
    )

    history = (
        await db.sub_payment_history(
            user_id
        )
    )

    card_number = (
        await db.get_setting(
            "subscription_card_number",
            "—",
        )
    )

    card_owner = (
        await db.get_setting(
            "subscription_card_owner",
            "—",
        )
    )

    # گیت از ماژول ربات — تک‌منبعِ قانون؛ فرانت فقط می‌خواند
    from subscription import (
        has_access,
    )

    resource_access = (
        await has_access(user_id)
    )

    enforced = bool(
        await db.get_setting(
            "subscription_enforced",
            False,
        )
    )

    has_pending = any(
        item.get("status")
        == "pending"

        for item in history
    )

    return {
        "active":
            active,

        "days_left":
            days_left,

        "plan_name": (
            subscription.get(
                "plan_name",
                "",
            )
            if subscription
            else ""
        ),

        "expires": (
            str(
                subscription.get(
                    "end_date",
                    "",
                )
            )[:10]
            if subscription
            else ""
        ),

        "has_pending_payment":
            has_pending,

        "resource_access":
            resource_access,

        "enforced":
            enforced,

        "plans": [
            normalize_plan(item)
            for item in plans
        ],

        # 🌊 W6/MISS-03 — فرانت فقط می‌خواند؛ تصمیم با claim است
        "trial": await db.trial_status(user_id),

        # 🌊 W7 — نقشه‌ی سبک فیچرها برای هماهنگی UI (مرجع نهایی: API)
        "features": await _features_map(),

        "payments": [
            normalize_payment(item)
            for item in history
        ],

        "payment": {
            "card_number":
                card_number,

            "card_owner":
                card_owner,
        },
    }


class DiscountRequest(
    BaseModel
):
    plan_id: str = Field(
        min_length=24,
        max_length=24,
    )

    code: str = Field(
        min_length=1,
        max_length=40,
    )


@router.post("/discount")
async def validate_discount(
    body: DiscountRequest,

    user=Depends(
        get_current_user
    ),
):
    if _HAS_RL:
        await rate_limit_user(user["id"], "sub_discount", 20, 60)
    plan = (
        await db.sub_plan_get(
            body.plan_id
        )
    )

    if (
        not plan
        or not plan.get("active")
    ):
        raise HTTPException(
            status_code=404,
            detail="پلن پیدا نشد",
        )

    code = (
        body.code
        .strip()
        .upper()
    )

    # 🎟 موج D1 — اعتبارسنجی با plan_id + user_id (plan-targeting + per-user limit)
    result = (
        await db.discount_validate(
            code,
            plan_id=str(
                plan.get("_id")
            ),
            user_id=user["id"],
        )
    )

    if not result.get("ok"):
        raise HTTPException(
            status_code=422,

            detail=result.get(
                "reason",
                "کد تخفیف معتبر نیست",
            ),
        )

    price = max(
        0,
        int(
            plan.get(
                "price",
                0,
            )
            or 0
        ),
    )

    percent = max(
        0,
        min(
            100,
            int(
                result.get(
                    "percent",
                    0,
                )
                or 0
            ),
        ),
    )

    final_price = round(
        price
        * (
            100 - percent
        )
        / 100
    )

    return {
        "ok":
            True,

        "code":
            code,

        "percent":
            percent,

        "price":
            price,

        "final_price":
            final_price,
    }


async def _features_map() -> dict:
    """🌊 W7 — {feature: {label, enabled, access}} برای فرانت (best-effort)."""
    try:
        from core.features import FEATURE_CATALOG
        docs = await db.feature_policies.find(
            {"_id": {"$in": list(FEATURE_CATALOG)}}).to_list(50)
        by_id = {d.get("_id"): d for d in docs}
        out = {}
        for key, spec in FEATURE_CATALOG.items():
            d = by_id.get(key) or {}
            out[key] = {"label": spec.get("label", key),
                        "enabled": bool(d.get("enabled", True)),
                        "access": d.get("access", "free")}
        return out
    except Exception:
        return {}


class FeatureEventBody(BaseModel):
    feature: str = Field(max_length=40)
    event: str = Field(max_length=40)  # paywall_viewed|subscription_cta_clicked|feature_opened
    extra: dict = Field(default_factory=dict)


@router.post("/feature-events")
async def feature_event_ep(
    body: FeatureEventBody,
    user=Depends(
        get_current_user
    ),
):
    """🌊 W7 — ایونت فرانت (paywall/CTA)؛ کرانه‌دار و best-effort."""
    if _HAS_RL:
        await rate_limit_user(user["id"], "feature_event", 30, 60)
    from core.features import FEATURE_CATALOG
    if body.feature not in FEATURE_CATALOG:
        raise HTTPException(status_code=404, detail="فیچر ناشناخته")
    if body.event not in ("paywall_viewed", "subscription_cta_clicked",
                          "feature_opened"):
        raise HTTPException(status_code=422, detail="ایونت نامعتبر")
    extra = {str(k)[:40]: str(v)[:200]
             for k, v in (body.extra or {}).items()} if isinstance(
                 body.extra, dict) else {}
    await db.log_feature_event(body.feature, body.event, user["id"], extra)
    return {"ok": True}


_TRIAL_FA = {
    "trial_disabled": "دوره‌ی آزمایشی فعلاً فعال نیست.",
    "already_subscribed": "اشتراک فعال داری؛ نیازی به trial نیست.",
    "already_used": "قبلاً از دوره‌ی آزمایشی استفاده کرده‌ای.",
    "no_plan": "فعلاً پلنی برای trial تعریف نشده است.",
    "unknown_user": "کاربر شناخته نشد.",
    "error": "خطای موقت؛ دوباره تلاش کن.",
}


@router.get("/trial/status")
async def trial_status_ep(
    user=Depends(
        get_current_user
    ),
):
    """🌊 W6/MISS-03 — وضعیت trial کاربر جاری."""
    return await db.trial_status(user["id"])


@router.post("/trial")
async def trial_claim_ep(
    user=Depends(
        get_current_user
    ),
):
    """🌊 W6/MISS-03 — دریافت trial (یک‌بار، ضد دابل‌کلیک)."""
    if _HAS_RL:
        await rate_limit_user(user["id"], "trial_claim", 3, 3600)
    try:
        res = await db.trial_claim(user["id"])
    except ValueError as e:
        raise HTTPException(
            status_code=409,
            detail=_TRIAL_FA.get(str(e), _TRIAL_FA["error"]),
        )
    return {"ok": True, **res}


class _FamilyRedeemBody(BaseModel):
    code: str = Field(min_length=8, max_length=12)


@router.get("/family")
async def family_overview_ep(
    user=Depends(
        get_current_user
    ),
):
    """🌊 W8/MISS-03 — نمای خانواده: مالک (اعضا+ظرفیت) یا عضو (مالک+پایان)."""
    uid = int(user["id"])
    sub = await db.sub_get(uid) or {}
    if (sub.get("source") == "family") and sub.get("family_owner_id"):
        owner_id = int(sub["family_owner_id"])
        owner = await db.get_user(owner_id) or {}
        return {
            "role": "member",
            "owner_id": owner_id,
            "owner_name": owner.get("name", ""),
            "end_date": sub.get("end_date"),
            "plan_name": sub.get("plan_name", ""),
        }
    seats = await db.family_plan_seats(uid)
    members = []
    if seats["total"] > 1:
        for m in await db.family_members(uid):
            u = await db.get_user(int(m["_id"])) or {}
            members.append({
                "user_id": int(m["_id"]),
                "name": u.get("name", ""),
                "status": m.get("status", ""),
                "end_date": m.get("end_date"),
            })
    return {
        "role": "owner",
        "seats_total": seats["total"],
        "seats_used": seats["used"],
        "seats_left": seats["left"],
        "plan_id": seats["plan_id"],
        "members": members,
    }


@router.post("/family/code")
async def family_code_ep(
    user=Depends(
        get_current_user
    ),
):
    """🌊 W8/MISS-03 — ساخت کد دعوت یک‌بارمصرف توسط مالک."""
    if _HAS_RL:
        await rate_limit_user(user["id"], "family_code", 10, 3600)
    res = await db.family_code_create(int(user["id"]))
    if not res.get("ok"):
        raise HTTPException(status_code=409, detail=res.get("error"))
    return res


@router.post("/family/redeem")
async def family_redeem_ep(
    body: _FamilyRedeemBody,
    user=Depends(
        get_current_user
    ),
):
    """🌊 W8/MISS-03 — ثبت کد دعوت و لینک‌شدن به خانواده."""
    if _HAS_RL:
        await rate_limit_user(user["id"], "family_redeem", 10, 3600)
    res = await db.family_redeem(body.code, int(user["id"]))
    if not res.get("ok"):
        raise HTTPException(status_code=409, detail=res.get("error"))
    return res


@router.delete("/family/members/{member_id}")
async def family_remove_ep(
    member_id: int,
    user=Depends(
        get_current_user
    ),
):
    """🌊 W8/MISS-03 — حذف عضو توسط مالک."""
    res = await db.family_remove(int(user["id"]), int(member_id),
                                 int(user["id"]))
    if not res.get("ok"):
        raise HTTPException(status_code=409, detail=res.get("error"))
    return res


@router.post("/buy")
async def buy(
    plan_id: str = Form(...),

    discount_code: str = Form(
        ""
    ),

    receipt: UploadFile | None = File(
        default=None
    ),

    gift_to: int = Form(0),
    gift_message: str = Form(""),
    idem: str = Form(""),

    user=Depends(
        get_current_user
    ),
):
    if _HAS_RL:
        await rate_limit_user(user["id"], "sub_buy", 12, 60)
    user_id = user["id"]

    database_user = user["_db"]

    plan = (
        await db.sub_plan_get(
            plan_id
        )
    )

    if (
        not plan
        or not plan.get("active")
    ):
        raise HTTPException(
            status_code=404,
            detail="پلن پیدا نشد",
        )

    has_pending = (
        await db
        .sub_payment_has_pending(
            user_id
        )
    )

    if has_pending:
        raise HTTPException(
            status_code=409,

            detail=(
                "یک رسید قبلی در "
                "انتظار بررسی دارید"
            ),
        )


    # 🌊 GIFT — هدیه روی همان زیرساخت خرید عادی (نه مسیر موازی).
    # قیمت همیشه سرور-ساید است؛ گیرنده در سرور اعتبارسنجی می‌شود؛
    # پیام هدیه در لایه‌ی db sanitize و محدود به ۳۰۰ نویسه می‌شود.
    gift_to = int(gift_to or 0)
    gift_message = (gift_message or "").strip()
    if gift_to:
        if str(await db.get_setting("gift_enabled", "1")) != "1":
            raise HTTPException(
                status_code=403,
                detail="خرید اشتراک هدیه فعلاً غیرفعال است",
            )
        if gift_to == user_id:
            raise HTTPException(
                status_code=422,
                detail=(
                    "هدیه دادن به خودتان همان خرید عادی است — "
                    "از «خرید اشتراک» استفاده کنید"
                ),
            )
        recipient = await db.get_user(gift_to)
        if not recipient or recipient.get("suspended"):
            raise HTTPException(
                status_code=422,
                detail="دانشجوی موردنظر پیدا نشد یا امکان دریافت هدیه را ندارد",
            )
        # ضد-سوءاستفاده: سقف هدیه در بازه‌ی لغزان — مقدار از settings
        # (تصمیم D10: عدد سخت کد نمی‌شود؛ اول اندازه‌گیری، بعد تنظیم)
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        try:
            _lim = int(await db.get_setting("gift_rate_max", "5"))
            _win = int(await db.get_setting("gift_rate_window_h", "24"))
        except Exception:
            _lim, _win = 5, 24
        _since = (_dt.now(_tz.utc) - _td(hours=_win)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        _cnt = await db.sub_payments.count_documents(
            {
                "user_id": user_id,
                "gift.to": {"$exists": True},
                "submitted_at": {"$gte": _since},
            }
        )
        if _cnt >= _lim:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"سقف {_lim} هدیه در {_win} ساعت اخیر پر شده است؛ "
                    "کمی بعد تلاش کنید"
                ),
            )


    price = max(
        0,
        int(
            plan.get(
                "price",
                0,
            )
            or 0
        ),
    )

    final_price = price
    # مقدار اولیه — برای پلن رایگانِ بدون کد، percent تعریف‌نشده باقی نماند
    percent = None

    code = (
        discount_code
        .strip()
        .upper()
        or None
    )


    if code:
        validation = (
            await db
            .discount_validate(
                code,
                plan_id=str(
                    plan.get("_id")
                ),
                user_id=user_id,
            )
        )

        if not validation.get(
            "ok"
        ):
            raise HTTPException(
                status_code=422,

                detail=validation.get(
                    "reason",
                    "کد تخفیف معتبر نیست",
                ),
            )

        percent = max(
            0,
            min(
                100,
                int(
                    validation.get(
                        "percent",
                        0,
                    )
                    or 0
                ),
            ),
        )

        final_price = round(
            price
            * (
                100 - percent
            )
            / 100
        )


    # تخفیف صددرصدی:
    # بدون رسید و تأیید ادمین
    # 🌊 GIFT — کد تخفیف ۱۰۰٪ با هدیه ترکیب نمی‌شود (تصمیم ثبت‌شده:
    # هدیه خرید واقعی است؛ کد رایگان مسیر شخصی است)
    if gift_to and final_price <= 0:
        raise HTTPException(
            status_code=422,
            detail="کد تخفیف ۱۰۰٪ با هدیه قابل ترکیب نیست",
        )

    if final_price <= 0 and code:
        # 🎟 موج D1 — مصرف اتمیک «قبل» از فعال‌سازی: اگر ظرفیت در همین
        # کسری‌از‌لحظه پر شده باشد، فعال‌سازی انجام نمی‌شود (نشتی صفر)
        consumed_free = await db.discount_consume(code, user_id=user_id)
        if not consumed_free:
            raise HTTPException(
                status_code=422,
                detail="ظرفیت این کد تخفیف همین حالا تکمیل شد.",
            )
    if final_price <= 0:
        try:
            end_date = (
                await db.sub_activate(
                    user_id,

                    int(
                        plan.get(
                            "days",
                            0,
                        )
                        or 0
                    ),

                    plan.get(
                        "name",
                        "اشتراک",
                    ),

                    source=
                        "discount",

                    # 🌊 W6/MISS-04 — اتصال اشتراک به پلن (سهمیه پلنی)
                    plan_id=
                        plan_id,

                    granted_by=
                        0,

                    extend=
                        True,
                )
            )

            payment_id = (
                await db
                .sub_payment_create(
                    user_id=
                        user_id,

                    plan_id=
                        plan_id,

                    plan_name=
                        plan.get(
                            "name",
                            "",
                        ),

                    price=
                        price,

                    final_price=
                        0,

                    screenshot_file_id=
                        "",

                    discount_code=
                        code,

                    discount_percent=
                        percent,
                )
            )
            await _sub_audit(user, "ثبت رسید پرداخت (API) — رایگان", target_id=str(payment_id), target_label=plan.get("name",""), after={"final_price": 0, "discount_code": code}, severity="INFO")

            await db.sub_payment_decide(
                payment_id,

                approved=True,

                admin_id=0,

                note=
                    "تخفیف ۱۰۰٪",
            )
        except Exception:
            # 🎟 جبران: فعال‌سازی/ثبت تراکنش نیمه‌کاره ماند — مصرف کد که
            # قبل از فعال‌سازی رزرو شده بود، آزاد می‌شود (نشتی صفر)
            if code:
                await db.discount_release(code, user_id=user_id)
            raise

        return {
            "ok":
                True,

            "activated":
                True,

            "payment_id":
                payment_id,

            "expires":
                str(end_date),

            "message":
                "اشتراک رایگان فعال شد.",
        }


    # برای پرداخت معمولی
    # تصویر رسید الزامی است
    if receipt is None:
        raise HTTPException(
            status_code=422,

            detail=(
                "تصویر رسید پرداخت "
                "الزامی است"
            ),
        )


    content_type = (
        receipt.content_type
        or ""
    )

    if not content_type.startswith(
        "image/"
    ):
        raise HTTPException(
            status_code=422,

            detail=(
                "رسید باید فایل "
                "تصویری باشد"
            ),
        )


    raw = await receipt.read(MAX_RECEIPT_SIZE + 1)
    if len(raw) > MAX_RECEIPT_SIZE:
        raise HTTPException(status_code=413, detail="حجم رسید بیشتر از ۱۰ مگابایت است")

    if not raw:
        raise HTTPException(
            status_code=422,

            detail=(
                "فایل رسید خالی است"
            ),
        )



    file_id = (
        await upload_and_get_file_id(
            user_id,

            receipt.filename
            or "receipt.jpg",

            raw,

            content_type
            or "image/jpeg",
        )
    )


    if not file_id:
        raise HTTPException(
            status_code=502,

            detail=(
                "آپلود رسید در "
                "تلگرام ناموفق بود"
            ),
        )


    if code:
        # 🎟 موج D1 — مصرف اتمیک «قبل» از ثبت رسید: ظرفیت دوره‌ی انتظار
        # بررسی هم رزرو می‌شود. در رد ادمین → discount_release. اگر ثبت
        # رسید خطا بخورد، مصرف با release جبران می‌شود.
        consumed_paid = await db.discount_consume(code, user_id=user_id)
        if not consumed_paid:
            raise HTTPException(
                status_code=422,
                detail="ظرفیت این کد تخفیف همین حالا تکمیل شد — رسیدی ثبت نشد.",
            )
    try:
        payment_id = (
            await db.sub_payment_create(
                user_id=
                    user_id,

                plan_id=
                    plan_id,

                plan_name=
                    plan.get(
                        "name",
                        "",
                    ),

                price=
                    price,

                final_price=
                    final_price,

                screenshot_file_id=
                    file_id,

                discount_code=
                    code,

                discount_percent=
                    percent if code else None,

                gift_to=
                    gift_to,

                gift_message=
                    gift_message,

                idem_key=
                    idem,
            )
        )
        await _sub_audit(user, "ثبت رسید پرداخت (API)", target_id=str(payment_id), target_label=plan.get("name",""), after={"final_price": final_price, "discount_code": code, "gift_to": gift_to}, severity="INFO")
    except Exception:
        if code:
            await db.discount_release(code, user_id=user_id)
        raise


    try:
        notification_collection = (
            db.client[
                "medicalbot"
            ][
                "bot_notifications"
            ]
        )

        admin_id = int(
            os.getenv(
                "ADMIN_ID",
                "0",
            )
        )

        safe_payment_id = escape(
            payment_id
        )

        safe_name = escape(
            str(
                database_user.get(
                    "name",
                    "",
                )
            )
        )

        safe_plan = escape(
            str(
                plan.get(
                    "name",
                    "",
                )
            )
        )

        await (
            notification_collection
            .insert_one({
                "type":
                    "payment_request",

                "chat_id":
                    admin_id,

                "text": (
                    f"💳 <b>رسید جدید "
                    f"#{safe_payment_id}</b>"

                    f"\n👤 {safe_name}"

                    f"\n📦 {safe_plan}"

                    f"\n💰 "
                    f"{final_price:,} "
                    f"تومان"
                ),

                "sent":
                    False,

                "created_at":
                    utc_now_iso(),
            })
        )

    except Exception:
        # ثبت رسید نباید به‌خاطر
        # خطای اعلان ادمین شکست بخورد
        pass


    return {
        "ok":
            True,

        "activated":
            False,

        "payment_id":
            payment_id,

        "price":
            price,

        "final_price":
            final_price,

        "plan_name":
            plan.get(
                "name",
                "",
            ),

        "message": (
            "رسید ثبت شد و در "
            "انتظار بررسی مدیریت است."
        ),
    }



def _gateway_callback_default() -> str:
    """🌊 W2 — کال‌بک پیش‌فرض درگاه (تک‌منبع برای request و topup)."""
    base = (os.getenv("ZARINPAL_CALLBACK_URL") or os.getenv("WEBAPP_URL") or "").strip().rstrip("/")
    if base:
        return f"{base}/payment/verify"
    return "https://humsyar.ir/payment/verify"


def _clamp_callback_url(provided: str, default: str) -> str:
    """🌊 W2 — کال‌بک دلخواه کلاینت فقط اگر https و هم‌مبدأ با مبدأ پیکربندی‌شده باشد؛
    در غیر این صورت نادیده گرفته و پیش‌فرض امن برگردانده می‌شود (جلوگیری از open-redirect)."""
    p = (provided or "").strip()
    if not p:
        return default
    try:
        from urllib.parse import urlparse
        pu, du = urlparse(p), urlparse(default)
        if (pu.scheme == "https" and du.netloc
                and (pu.netloc or "").lower() == (du.netloc or "").lower()):
            return p
    except Exception:
        pass
    return default


# ══════════════════════════════════════════════════════════════════
# 💳 W2 — زرین‌پال (درگاه خودکار + Sandbox mock)
# ══════════════════════════════════════════════════════════════════
@router.get("/gateway-status")
async def gateway_status(user=Depends(get_current_user)):
    """🌊 W2 — وضعیت عمومی درگاه برای کلاینت‌ها (فقط boolean؛ بدون secret)."""
    if _HAS_RL:
        await rate_limit_user(user["id"], "gw_status", 60, 60)
    from payments.zarinpal import gateway_public_status
    return await gateway_public_status()


class ZarinpalRequestBody(BaseModel):
    plan_id: str = Field(..., min_length=6)
    discount_code: str = Field(default="", max_length=40)
    gift_to: int = Field(default=0)
    gift_message: str = Field(default="", max_length=300)
    callback_url: str = Field(default="", max_length=500)
    idem: str = Field(default="", max_length=64)

@router.post("/zarinpal/request")
async def zarinpal_request_ep(body: ZarinpalRequestBody, user=Depends(get_current_user)):
    if _HAS_RL:
        await rate_limit_user(user["id"], "zarinpal_req", 10, 60)
    from payments.zarinpal import zarinpal_request as _zp_req
    user_id = user["id"]
    plan = await db.sub_plan_get(body.plan_id)
    if not plan or not plan.get("active"):
        raise HTTPException(status_code=404, detail="پلن پیدا نشد")
    # pending guard — like buy
    if await db.sub_payment_has_pending(user_id):
        raise HTTPException(status_code=409, detail="یک رسید قبلی در انتظار بررسی دارید — با درگاه جدید ناسازگار است")
    gift_to = int(body.gift_to or 0)
    if gift_to:
        if str(await db.get_setting("gift_enabled", "1")) != "1":
            raise HTTPException(status_code=403, detail="هدیه غیرفعال است")
        if gift_to == user_id:
            raise HTTPException(status_code=422, detail="هدیه به خود مجاز نیست")
        rec = await db.get_user(gift_to)
        if not rec or rec.get("suspended"):
            raise HTTPException(status_code=422, detail="گیرنده پیدا نشد")
    price = max(0, int(plan.get("price") or 0))
    code = (body.discount_code or "").strip().upper() or None
    percent = None
    if code:
        v = await db.discount_validate(code, plan_id=str(plan["_id"]), user_id=user_id)
        if not v.get("ok"):
            raise HTTPException(status_code=422, detail=v.get("reason") or "کد تخفیف معتبر نیست")
        percent = int(v.get("percent") or 0)
        price = round(price * (100 - percent) / 100)
    if price <= 0:
        raise HTTPException(status_code=422, detail="این پلن با این کد رایگان است — از مسیر «خرید رایگان» استفاده کنید")
    if gift_to and price <= 0:
        raise HTTPException(status_code=422, detail="کد ۱۰۰٪ با هدیه قابل ترکیب نیست")
    idem = (body.idem or "").strip()[:64] or f"zp-{user_id}-{body.plan_id[:8]}-{price}"
    # idempotency guard
    if idem:
        ex = await db.sub_payments.find_one({"idem_key": idem})
        if ex and ex.get("zarinpal_authority"):
            return {"ok": True, "authority": ex["zarinpal_authority"], "url": f"https://sandbox.zarinpal.com/pg/StartPay/{ex['zarinpal_authority']}" if ex["zarinpal_authority"].startswith("TEST-") else f"https://www.zarinpal.com/pg/StartPay/{ex['zarinpal_authority']}", "payment_id": str(ex["_id"]), "replay": True, "final_price": int(ex.get("final_price") or price)}
    # discount not consumed yet — will be consumed atomically at verify (after payment) to avoid stuck reservation
    # gateway request
    cb = _clamp_callback_url(body.callback_url, _gateway_callback_default())
    desc = f"اشتراک {plan.get('name','')} هامشیار"
    try:
        zp = await _zp_req(price, desc, cb)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"درگاه زرین‌پال پاسخ نداد: {e}")
    authority = zp["authority"]
    try:
        pid = await db.sub_payment_create_zarinpal(user_id, str(plan["_id"]), plan.get("name",""), int(plan.get("price") or price), price, authority, discount_code=code, discount_percent=percent, idem_key=idem)
        if gift_to:
            await db.sub_payments.update_one({"_id": ObjectId(pid)}, {"$set": {"gift": {"to": int(gift_to), "message": (body.gift_message or "")[:300], "activated_at": None}}})
        await _sub_audit(user, "درخواست پرداخت زرین‌پال", target_id=pid, target_label=plan.get("name",""), after={"authority": authority, "final_price": price, "discount_code": code}, severity="INFO")
    except Exception as e:
        if code:
            await db.discount_release(code, user_id=user_id)
        raise HTTPException(status_code=500, detail=f"ثبت پرداخت ناموفق: {e}")
    return {"ok": True, "authority": authority, "url": zp["url"], "payment_id": pid, "final_price": price, "mock": zp.get("mock", False)}

class ZarinpalTopupBody(BaseModel):
    amount: int = Field(..., ge=1, le=100_000_000)
    callback_url: str = Field(default="", max_length=500)
    idem: str = Field(default="", max_length=64)

@router.post("/zarinpal/topup")
async def zarinpal_topup_ep(body: ZarinpalTopupBody, user=Depends(get_current_user)):
    """🌊 W2 — شارژ کیف پول با درگاه آنلاین (مبلغ‌محور؛ بدون پلن)."""
    if _HAS_RL:
        await rate_limit_user(user["id"], "zarinpal_topup", 10, 60)
    from payments.zarinpal import zarinpal_request as _zp_req, gateway_public_status
    user_id = user["id"]
    gw = await gateway_public_status()
    if not gw.get("online_pay_enabled"):
        raise HTTPException(status_code=503, detail="پرداخت آنلاین در حال حاضر فعال نیست")
    try:
        topup_min = int(await db.get_setting("topup_min", str(TOPUP_DEFAULT_MIN)))
        topup_max = int(await db.get_setting("topup_max", str(TOPUP_DEFAULT_MAX)))
    except Exception:
        topup_min, topup_max = TOPUP_DEFAULT_MIN, TOPUP_DEFAULT_MAX
    amount = int(body.amount or 0)
    if not topup_min <= amount <= topup_max:
        raise HTTPException(status_code=422,
                            detail=f"مبلغ شارژ باید بین {topup_min:,} و {topup_max:,} تومان باشد")
    if await db.sub_payment_has_pending(user_id):
        raise HTTPException(status_code=409, detail="یک پرداخت در انتظار قبلی دارید")
    idem = (body.idem or "").strip()[:64] or f"zpt-{user_id}-{amount}"
    ex = await db.sub_payments.find_one({"idem_key": idem})
    if ex is not None and int(ex.get("user_id") or 0) == user_id and ex.get("zarinpal_authority"):
        auth = ex["zarinpal_authority"]
        host = "sandbox.zarinpal.com" if auth.startswith("TEST-") else "www.zarinpal.com"
        return {"ok": True, "authority": auth, "url": f"https://{host}/pg/StartPay/{auth}",
                "payment_id": str(ex["_id"]), "replay": True,
                "final_price": int(ex.get("final_price") or amount)}
    cb = _clamp_callback_url(body.callback_url, _gateway_callback_default())
    try:
        zp = await _zp_req(amount, f"شارژ کیف پول هامشیار — کاربر {user_id}", cb)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"درگاه زرین‌پال پاسخ نداد: {e}")
    try:
        pid = await db.sub_payment_create_zarinpal(
            user_id, "wallet_topup", "شارژ کیف پول", amount, amount,
            zp["authority"], idem_key=idem)
        await _sub_audit(user, "درخواست شارژ کیف پول با درگاه", target_id=str(pid),
                         target_label="شارژ کیف پول",
                         after={"authority": zp["authority"], "amount": amount}, severity="INFO")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ثبت پرداخت ناموفق: {e}")
    return {"ok": True, "authority": zp["authority"], "url": zp["url"],
            "payment_id": str(pid), "final_price": amount, "mock": zp.get("mock", False)}


class ZarinpalVerifyBody(BaseModel):
    authority: str = Field(..., min_length=6, max_length=64)
    # Status from Zarinpal redirect (OK/NOK) — optional

@router.post("/zarinpal/verify")
async def zarinpal_verify_ep(body: ZarinpalVerifyBody, user=Depends(get_current_user)):
    if _HAS_RL:
        await rate_limit_user(user["id"], "zarinpal_verify", 20, 60)
    from payments.zarinpal import zarinpal_verify as _zp_v
    authority = (body.authority or "").strip()
    doc = await db.sub_payment_find_by_authority(authority)
    if not doc:
        raise HTTPException(status_code=404, detail="پرداخت پیدا نشد")
    if int(doc.get("user_id") or 0) != user["id"]:
        raise HTTPException(status_code=403, detail="این پرداخت متعلق به شما نیست")
    if doc.get("status") == "approved":
        sub = await db.sub_get(user["id"])
        return {"ok": True, "already": True, "end_date": (sub or {}).get("end_date"), "ref_id": doc.get("zarinpal_ref_id")}
    if doc.get("status") != "zarinpal_pending":
        raise HTTPException(status_code=409, detail=f"وضعیت پرداخت {doc.get('status')} قابل تایید نیست")
    amount = int(doc.get("final_price") or doc.get("price") or 0)
    code = (doc.get("discount_code") or "").strip().upper() or None
    zp = await _zp_v(authority, amount)
    if not zp.get("ok"):
        raise HTTPException(status_code=402, detail="پرداخت تایید نشد (لغو شده یا نامعتبر)")
    ref_id = str(zp.get("ref_id") or "")
    # consume discount atomically after payment success (if present)
    # 🌊 W3 — پول در درگاه قطعی گرفته شده؛ fail کردن در این نقطه یعنی
    # «پولِ گرفته‌شده‌ی بی‌حساب». پس approve می‌کنیم + پرچم overrun برای
    # بازبینی مغایرت‌گیری (تخفیف خارج از ظرفیت به کاربر داده شد).
    discount_overrun = False
    if code:
        consumed = await db.discount_consume(code, user_id=user["id"])
        if not consumed:
            discount_overrun = True
    res = await db.sub_payment_verify_zarinpal(authority, ref_id, amount)
    if not res.get("ok"):
        if code:
            await db.discount_release(code, user_id=user["id"])
        if res.get("already"):
            sub = await db.sub_get(user["id"])
            return {"ok": True, "already": True, "end_date": (sub or {}).get("end_date"), "ref_id": ref_id}
        raise HTTPException(status_code=409, detail=res.get("reason") or "تایید هم‌زمان — دوباره تلاش کنید")
    if discount_overrun:
        await db.sub_payment_mark_discount_overrun(authority)
    await _sub_audit(user, "تایید پرداخت زرین‌پال", target_id=str(doc["_id"]), target_label=doc.get("plan_name",""), after={"ref_id": ref_id, "authority": authority, "discount_overrun": discount_overrun}, severity=("HIGH" if discount_overrun else "INFO"))
    act = res.get("activation") or {}
    return {"ok": True, "ref_id": ref_id, "end_date": act.get("end_date"), "days": act.get("days"), "mock": zp.get("mock", False), "discount_overrun": discount_overrun}

@router.get("/zarinpal/callback")
async def zarinpal_callback(Authority: str = Query(""), Status: str = Query("")):
    """Callback for Zarinpal redirect (when callback_url points to API). Verifies and redirects to miniapp."""
    from fastapi.responses import RedirectResponse
    from urllib.parse import quote
    base = (os.getenv("WEBAPP_URL") or "https://humsyar.ir").strip().rstrip("/")
    # 🛡 W4/SEC-05 — بازتاب پارامترهای درگاه با encode (ضد query-injection)
    target = (f"{base}/payment/verify?Authority={quote(Authority or '', safe='')}"
              f"&Status={quote(Status or '', safe='')}")
    if Status != "OK":
        # user cancelled — optionally mark payment cancelled? keep pending for retry
        return RedirectResponse(url=target + "&verified=0", status_code=302)
    # verify will be done by frontend via POST /zarinpal/verify with auth; here just redirect
    return RedirectResponse(url=target, status_code=302)

# ═══════════════ 🌊 GIFT — تاریخچه‌ی هدیه‌ها (سمت دانشجو) ═══════════════
@router.get("/gifts")
async def gift_history(user=Depends(get_current_user)):
    """هدیه‌هایی که داده‌ام (as_payer) و دریافت کرده‌ام (as_recipient).

    وضعیت‌ها همان ۵ وضعیت قرارداد رسید است — هیچ وضعیت جدیدی اختراع
    نشده (ماتریس وضعیت §۲۲). پیام هدیه فقط به payer/recipient خودش
    نشان داده می‌شود."""
    uid = user["id"]
    payer_docs = (
        await db.sub_payments.find(
            {"user_id": uid, "gift.to": {"$exists": True}}
        )
        .sort("submitted_at", -1)
        .limit(50)
        .to_list(50)
    )
    rec_docs = (
        await db.sub_payments.find(
            {"gift.to": uid}
        )
        .sort("submitted_at", -1)
        .limit(50)
        .to_list(50)
    )

    def _shape(d: dict, as_payer: bool) -> dict:
        gift = d.get("gift") or {}
        return {
            "id": str(d.get("_id", "")),
            "plan_name": d.get("plan_name", ""),
            "final_price": d.get("final_price", 0),
            "status": d.get("status", "pending"),
            "submitted_at": d.get("submitted_at", ""),
            "to": gift.get("to", 0) if as_payer else uid,
            "from": d.get("user_id", 0) if not as_payer else uid,
            "message": gift.get("message", ""),
            "activated_at": gift.get("activated_at"),
        }

    return {
        "ok": True,
        "as_payer": [_shape(d, True) for d in payer_docs],
        "as_recipient": [_shape(d, False) for d in rec_docs],
    }


# ═══════════════ 🌊 GIFT — جست‌وجوی حریم‌محور گیرنده ═══════════════
@router.get("/gift/recipients")
async def gift_recipients(
    q: str = Query("", max_length=100),
    user=Depends(get_current_user),
):
    """جست‌وجوی گیرنده‌ی هدیه — قرارداد مشترک db.search_users.

    حریم خصوصی: فقط user_id، name و username برمی‌گردد؛ هیچ فیلد
    شخصی دیگری (شماره، وضعیت اشتراک، ...) به payer داده نمی‌شود.
    خودِ payer از نتایج حذف می‌شود (خود-هدیه مجاز نیست)."""
    q = (q or "").strip()
    if len(q) < 2:
        return {"ok": True, "items": []}
    rows = await db.search_users(q, limit=10)
    items = [
        {
            "user_id": r.get("user_id"),
            "name": r.get("name", "—"),
            "username": r.get("username") or "",
        }
        for r in rows
        if r.get("user_id") and int(r["user_id"]) != user["id"]
    ]
    return {"ok": True, "items": items[:10]}


# ══════════════════════════════════════════════════════════════════
# 💰 W6 — کیف پول داخلی (API canonical — Bot/MiniApp/Web مشترک)
# موجودی همیشه از بک‌اند می‌آید؛ client هیچ‌وقت مبلغ/موجودی تعیین نمی‌کند.
# ══════════════════════════════════════════════════════════════════

class BuyWalletBody(BaseModel):
    plan_id: str
    idem: str = ""
    discount_code: str = ""


def _tx_view(t: dict) -> dict:
    """نمای human-readable تراکنش — IDها فقط جزئیات فنی‌اند."""
    return {
        "id": str(t["_id"]), "type": t.get("type"),
        "direction": t.get("direction"), "amount": int(t.get("amount") or 0),
        "label": t.get("label"), "at": t.get("created_at"),
        "balance_after": t.get("balance_after"),
        "reference_type": t.get("reference_type"),
    }


@router.get("/wallet")
async def wallet_status(user=Depends(get_current_user)):
    """موجودی + آمار + تراکنش‌های اخیر — همه server-derived."""
    s = await db.wallet_summary(user["id"])
    txs = await db.wallet_tx_list(user["id"], limit=10)
    return {**s, "transactions": [_tx_view(t) for t in txs]}


@router.get("/wallet/transactions")
async def wallet_transactions(skip: int = 0, limit: int = 20,
                              after: str | None = Query(None, max_length=32),
                              user=Depends(get_current_user)):
    limit = max(1, min(int(limit), 50))
    if after:
        # 🌊 W2 — cursor pagination (indexed, no skip)
        txs = await db.wallet_tx_list_cursor(user["id"], after_id=after, limit=limit)
        next_cursor = str(txs[-1]["_id"]) if len(txs) == limit else None
        return {"items": [_tx_view(t) for t in txs], "next_cursor": next_cursor, "has_more": next_cursor is not None}
    skip = max(0, int(skip))
    txs = await db.wallet_tx_list(user["id"], skip=skip, limit=limit)
    return {"items": [_tx_view(t) for t in txs],
            "total": await db.wallet_tx_count(user["id"])}


async def _wallet_purchase_result(payment: dict, user_id: int,
                                  act: dict = None, replay: bool = False):
    w = await db.wallet_get_for_user_id(user_id)
    out = {"ok": True, "payment_id": str(payment["_id"]),
           "plan_name": payment.get("plan_name"),
           "amount": int(payment.get("final_price") or 0),
           "balance": int((w or {}).get("balance", 0)), "replay": replay}
    if act:
        out["end_date"] = act.get("end_date")
        out["days"] = act.get("days")
    else:
        sub = await db.sub_get(user_id)
        out["end_date"] = (sub or {}).get("end_date")
    return out


@router.post("/buy-wallet")
async def buy_wallet(body: BuyWalletBody, user=Depends(get_current_user)):
    if _HAS_RL:
        await rate_limit_user(user["id"], "sub_wallet", 12, 60)
    """خرید اشتراک از کیف پول — روی همان سیستم خرید موجود؛ کیف پول فقط
    روش پرداخت جدید است. منطق واحد در db.wallet_purchase (Bot هم همان را
    صدا می‌زند). خطاها با پیام فارسی و کد ماشین‌خوان برمی‌گردند."""
    user_id = user["id"]
    try:
        res = await db.wallet_purchase(user_id, body.plan_id, body.idem,
                                       discount_code=body.discount_code)
        await _sub_audit(user, "خرید اشتراک از کیف پول (API)", target_id=str(res.get("payment_id" ) or ""), target_label=body.plan_id[:24], after={"discount_code": body.discount_code, "amount": int(res.get("amount") or 0)}, severity="INFO")
    except Exception as e:
        code = getattr(e, "code", "")
        if code == "plan_not_found":
            raise HTTPException(status_code=404, detail=str(e))
        if code == "insufficient_balance":
            w = await db.wallet_get_for_user_id(user_id)
            plan = await db.sub_plan_get(body.plan_id)
            price = int((plan or {}).get("price") or 0)
            dc = (body.discount_code or "").strip()
            if dc and plan:
                v = await db.discount_validate(
                    dc, plan_id=str(plan["_id"]), user_id=user_id)
                if v.get("ok"):
                    price = round(price * (100 - int(v.get("percent") or 0))
                                  / 100)
            balance = int((w or {}).get("balance", 0))
            raise HTTPException(
                status_code=400,
                detail=(f"موجودی کیف پول کافی نیست. موجودی: {balance:,} تومان · "
                        f"قیمت: {price:,} تومان · "
                        f"کسری: {max(0, price - balance):,} تومان"))
        if code in ("discount_invalid", "discount_exhausted",
                    "discount_full"):
            raise HTTPException(status_code=400, detail=str(e))
        if code in ("plan_days_invalid", "plan_price_invalid"):
            raise HTTPException(status_code=422, detail=str(e))
        if code == "order_conflict":
            raise HTTPException(status_code=409, detail=str(e))
        raise
    if not res.get("replay"):
        await db.client["medicalbot"]["bot_notifications"].insert_one({
            "type": "event:wallet_purchase", "chat_id": user_id, "sent": False,
            "text": (f"✅ اشتراک شما با استفاده از کیف پول فعال شد "
                     f"({int(res.get('amount') or 0):,} تومان)."),
            "created_at": utc_now_iso()})
    w = await db.wallet_get_for_user_id(user_id)
    return {"ok": True, **res,
            "balance": int((w or {}).get("balance", 0))}


# 🌊 W6.2 — شارژ کیف پول از سمت دانشجو: همان معماری رسید بانکی خرید
# (رسید → بررسی ادمین → اعتبار). سیستم مالی موازی ساخته نمی‌شود؛
# رسید شارژ یک sub_payment با plan_id ثابت 'wallet_topup' است و
# finalize_approved_payment شاخه‌ی اعتبار آن را دارد.
TOPUP_DEFAULT_MIN = 10_000
TOPUP_DEFAULT_MAX = 20_000_000


@router.post("/topup")
async def topup(
    amount: int = Form(...),
    receipt: UploadFile | None = File(default=None),
    idem: str = Form(""),
    user=Depends(get_current_user),
):
    if _HAS_RL:
        await rate_limit_user(user["id"], "topup", 12, 60)
    user_id = user["id"]
    database_user = user["_db"]
    try:
        topup_min = int(await db.get_setting(
            "topup_min", str(TOPUP_DEFAULT_MIN)))
        topup_max = int(await db.get_setting(
            "topup_max", str(TOPUP_DEFAULT_MAX)))
    except Exception:
        topup_min, topup_max = TOPUP_DEFAULT_MIN, TOPUP_DEFAULT_MAX
    if not topup_min <= int(amount or 0) <= topup_max:
        raise HTTPException(
            status_code=422,
            detail=(f"مبلغ شارژ باید بین {topup_min:,} و "
                    f"{topup_max:,} تومان باشد"))
    # همان قاعده‌ی خرید: هر کاربر در هر لحظه یک رسید در انتظار دارد
    if await db.sub_payment_has_pending(user_id):
        raise HTTPException(
            status_code=409,
            detail="یک رسید قبلی در انتظار بررسی دارید")
    if receipt is None:
        raise HTTPException(
            status_code=422, detail="تصویر رسید پرداخت الزامی است")
    content_type = receipt.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=422, detail="رسید باید فایل تصویری باشد")
    raw = await receipt.read(MAX_RECEIPT_SIZE + 1)
    if len(raw) > MAX_RECEIPT_SIZE:
        raise HTTPException(status_code=413, detail="حجم رسید بیشتر از ۱۰ مگابایت است")
    if not raw:
        raise HTTPException(status_code=422, detail="فایل رسید خالی است")

    file_id = await upload_and_get_file_id(
        user_id, receipt.filename or "receipt.jpg", raw,
        content_type or "image/jpeg")
    if not file_id:
        raise HTTPException(
            status_code=502, detail="آپلود رسید در تلگرام ناموفق بود")
    payment_id = await db.sub_payment_create(
        user_id=user_id, plan_id="wallet_topup", plan_name="شارژ کیف پول",
        price=int(amount), final_price=int(amount),
        screenshot_file_id=file_id,
        idem_key=idem or f"topup:{user_id}:{file_id}")
    await _sub_audit(user, "ثبت رسید شارژ کیف پول (API)", target_id=str(payment_id), target_label="شارژ کیف پول", after={"amount": int(amount)}, severity="INFO")
    try:
        admin_id = int(os.getenv("ADMIN_ID", "0"))
        safe_payment_id = escape(payment_id)
        safe_name = escape(str(database_user.get("name", user_id)))
        await db.client["medicalbot"]["bot_notifications"].insert_one({
            "type": "payment_request", "chat_id": admin_id,
            "text": (f"💰 <b>رسید شارژ کیف پول #{safe_payment_id}</b>"
                     f"\n👤 {safe_name}"
                     f"\n💰 {int(amount):,} تومان"),
            "sent": False, "created_at": utc_now_iso()})
    except Exception:
        pass  # ثبت رسید نباید به‌خاطر خطای اعلان ادمین شکست بخورد
    return {"ok": True, "payment_id": payment_id, "amount": int(amount),
            "message": "رسید شارژ ثبت شد و در انتظار بررسی مدیریت است؛ "
                       "پس از تأیید، مبلغ به کیف پول شما اضافه می‌شود."}
