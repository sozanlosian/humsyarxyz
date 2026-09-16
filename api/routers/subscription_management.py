"""Subscription administration endpoints."""

import hashlib
import json
import logging
import re

from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
from time_utils import format_datetime_fa, now_utc, utc_now_iso

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)
from fastapi.responses import Response

from pydantic import (
    BaseModel,
    Field,
)

from api.auth import (
    require_perm,
)

from api.telegram_send import (
    _send,
    API_BASE,
    BOT_TOKEN,
)

from api.routers.admin_panel import (
    _audit,
)

from database import db


router = APIRouter()


class PlanBody(BaseModel):
    name: str = Field(
        min_length=2,
        max_length=100,
    )

    days: int = Field(
        ge=1,
        le=3650,
    )

    price: int = Field(
        ge=0,
        le=2_000_000_000,
    )

    # 🌊 W6/MISS-04 — سهمیه روزانه هوشیار؛ ۰ = ارث از سقف سراسری
    ai_daily_limit: int = Field(
        default=0,
        ge=0,
        le=100000,
    )

    # 🌊 W7 — {feature: bool}؛ فقط کلیدهای true/false ذخیره می‌شوند
    entitlements: dict = Field(default_factory=dict)

    # 🌊 W8/MISS-03 — ظرفیت خانواده (۱ = شخصی)
    max_members: int = Field(default=1, ge=1, le=50)


class SubscriptionSettingsBody(BaseModel):
    subscription_enforced: bool | None = None
    protect_content_enabled: bool | None = None


class BulkGrantBody(BaseModel):
    mode: str = Field(pattern="^(list|role)$")
    identifiers: list[str] = Field(default_factory=list, max_length=500)
    role: str | None = None
    days: int = Field(ge=1, le=3650)
    plan_name: str = Field(default="اشتراک رایگان", min_length=2, max_length=100)
    extend: bool = True


class DecisionBody(BaseModel):
    approved: bool

    note: str = Field(
        default="",
        max_length=500,
    )


class GrantBody(BaseModel):
    user_id: int = Field(
        gt=0
    )

    days: int = Field(
        ge=1,
        le=3650,
    )

    plan_name: str = Field(
        default="اشتراک دستی",
        max_length=100,
    )

    extend: bool = True


class RevokeBody(BaseModel):
    reason: str = Field(
        min_length=2,
        max_length=500,
    )


# ══════════════════════════════════════════════
# 🔎 جست‌وجوی یکپارچه — همان قرارداد سراسری
# db.build_user_search_query (نام، @یوزرنیم،
# شماره دانشجویی، آیدی عددی) که ربات و پنل
# کاربران هم از آن استفاده می‌کنند.
# ══════════════════════════════════════════════

async def _matched_user_ids(
    raw: str,
) -> list:
    """آیدی عددی کاربرانِ منطبق با عبارت جست‌وجو."""

    user_query = (
        db.build_user_search_query(
            raw
        )
    )

    if not user_query:
        return []

    matched = (
        await db.users.find(
            user_query,
            {'user_id': 1},
        ).to_list(500)
    )

    return [
        user['user_id']

        for user in matched

        if user.get('user_id')
        is not None
    ]


def _numeric_id_or_none(
    raw: str,
):
    """عبارت کاملاً عددی → int در غیر این صورت
    None — برای تطبیق مستقیم روی خودِ کالکشن
    (رسید/اشتراکِ کاربرِ حذف‌شده هم باید با
    آیدی عددی پیدا شود)."""

    if raw.lstrip('+-').isdigit():
        try:
            return int(raw)

        except (
            ValueError,
            OverflowError,
        ):
            return None

    return None


async def _payment_search_filter(
    search,
):
    """فیلتر $or رسیدها: کاربران منطبق + نام
    پلن + کد تخفیف + آیدی عددی مستقیم."""

    raw = (search or '').strip()

    if not raw:
        return None

    pattern = {
        '$regex':
            re.escape(raw),
        '$options': 'i',
    }

    or_parts = [
        {'plan_name': pattern},
        {'discount_code': pattern},
    ]

    ids = await _matched_user_ids(raw)

    if ids:
        or_parts.append(
            {'user_id': {'$in': ids}}
        )

    numeric = _numeric_id_or_none(raw)

    if numeric is not None:
        or_parts.append(
            {'user_id': numeric}
        )

    return {'$or': or_parts}


async def _subscriber_search_filter(
    search,
):
    """فیلتر $or مشترکین: کاربران منطبق (کلید
    اشتراک = user_id در فیلد _id) + نام پلن +
    آیدی عددی مستقیم."""

    raw = (search or '').strip()

    if not raw:
        return None

    pattern = {
        '$regex':
            re.escape(raw),
        '$options': 'i',
    }

    or_parts = [
        {'plan_name': pattern},
    ]

    ids = await _matched_user_ids(raw)

    if ids:
        or_parts.append(
            {'_id': {'$in': ids}}
        )

    numeric = _numeric_id_or_none(raw)

    if numeric is not None:
        or_parts.append(
            {'_id': numeric}
        )

    return {'$or': or_parts}


class DiscountBody(BaseModel):
    code: str = Field(
        min_length=2,
        max_length=40,
    )

    percent: int = Field(
        ge=1,
        le=100,
    )

    max_uses: int = Field(
        default=0,
        ge=0,
    )

    expires_at: str | None = None

    # 🎟 موج D1 — plan-targeting + per-user limit
    target_plan_ids: list[str] | None = None
    per_user_limit: int = Field(
        default=0,
        ge=0,
    )


class DiscountBroadcastBody(BaseModel):
    """بدنه‌ی درخواست انتشار کمپین کد تخفیف."""
    target: str = Field(
        default='all',
        pattern='^(all|subscribers|no_sub)$',
    )

    title: str | None = None
    description: str | None = None


class CardBody(BaseModel):
    card_number: str = Field(
        min_length=4,
        max_length=40,
    )

    card_owner: str = Field(
        min_length=2,
        max_length=100,
    )


@router.get("/overview")
async def overview(
    admin=Depends(require_perm("subscription.manage")),
):
    stats = (
        await db.sub_stats()
    )

    plans = (
        await db.sub_plan_list()
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
    roles = await db.list_roles()

    # Fix-Foundation: KPIهای تکمیلی از داده‌ی واقعی؛ ساختار nested قدیمی
    # حفظ می‌شود و فقط کلیدهای افزوده به stats اضافه می‌شوند.
    stats = dict(stats or {})
    now_iso = utc_now_iso()
    soon_iso = (now_utc() + timedelta(days=7)).isoformat()
    stats["expiring"] = await db.subscriptions.count_documents({
        "status": "active", "end_date": {"$gte": now_iso, "$lte": soon_iso},
    })
    stats["discounts"] = await db.discount_codes.count_documents({})

    return {
        "stats":
            stats,

        "plans": [
            {
                "id":
                    str(
                        plan["_id"]
                    ),

                "name":
                    plan.get(
                        "name",
                        "",
                    ),

                "days":
                    plan.get(
                        "days",
                        0,
                    ),

                "price":
                    plan.get(
                        "price",
                        0,
                    ),

                "active":
                    plan.get(
                        "active",
                        True,
                    ),

                # 🌊 W6/MISS-04
                "ai_daily_limit":
                    plan.get(
                        "ai_daily_limit",
                        0,
                    ) or 0,

                # 🌊 W7
                "entitlements":
                    plan.get(
                        "entitlements",
                        {},
                    ) or {},

                # 🌊 W8/MISS-03
                "max_members":
                    plan.get(
                        "max_members",
                        1,
                    ) or 1,
            }

            for plan in plans
        ],

        "card": {
            "card_number":
                card_number,

            "card_owner":
                card_owner,
        },

        "settings": {
            "subscription_enforced": bool(await db.get_setting("subscription_enforced", False)),
            "protect_content_enabled": bool(await db.get_setting("protect_content_enabled", True)),
        },
        "roles": [{
            "key": r.get("_id"), "label": r.get("label", r.get("_id", "")),
            "icon": r.get("icon", "🛡"), "active": r.get("active", True),
        } for r in roles],
    }


@router.patch("/settings")
async def update_subscription_settings(
    body: SubscriptionSettingsBody,
    admin=Depends(require_perm("subscription.manage")),
):
    changed = []
    before, after = {}, {}
    for key in ("subscription_enforced", "protect_content_enabled"):
        value = getattr(body, key)
        if value is None:
            continue
        old = bool(await db.get_setting(key, key == "protect_content_enabled"))
        if old != bool(value):
            await db.set_setting(key, bool(value))
            before[key] = old
            after[key] = bool(value)
            changed.append(key)
            # 🌊 W7 — سوییچ legacy حالا ماکرو است: روی هر ۳ پالیسی محتوا می‌نویسد
            # (تک‌منبع حقیقت = feature_policies؛ کلید قدیمی فقط برای rollback نگه داشته می‌شود)
            if key == "subscription_enforced":
                from core.access import invalidate_policy_cache
                _mode = "subscription" if value else "free"
                for _f in ("question_bank", "resources", "references"):
                    await db.set_feature_policy(
                        _f, {"access": _mode}, admin["id"],
                        (admin.get("_db") or {}).get("name", ""))
                    invalidate_policy_cache(_f)
                after["feature_policies"] = f"qb+resources+references → {_mode}"
                await db.log_feature_event(
                    "question_bank", "feature_policy_changed", admin["id"],
                    {"via": "legacy_enforced_macro", "access": _mode})
    if changed:
        await _audit(
            admin, "به‌روزرسانی سیاست اشتراک", "Subscription", severity="HIGH",
            before=before, after=after, tags=["اشتراک", "تنظیمات", "پنل_وب"],
        )
    return {"ok": True, "changed": changed}


@router.put("/plans/{plan_id}")
async def update_plan(
    plan_id: str,
    body: PlanBody,
    admin=Depends(require_perm("subscription.manage")),
):
    old = await db.sub_plan_get(plan_id)
    if not old:
        raise HTTPException(status_code=404, detail="پلن پیدا نشد")
    # 🌊 W7 — سفیدسازی entitlements با کاتالوگ (کلید ناشناخته دور ریخته می‌شود)
    from core.features import FEATURE_CATALOG as _FCAT
    _ent = {k: bool(v) for k, v in (body.entitlements or {}).items()
            if k in _FCAT}
    patch = {"name": body.name.strip(), "days": body.days, "price": body.price,
             "ai_daily_limit": body.ai_daily_limit, "entitlements": _ent,
             "max_members": body.max_members}
    ok = await db.sub_plan_update(plan_id, patch)
    if not ok:
        raise HTTPException(status_code=500, detail="ویرایش پلن انجام نشد")
    await _audit(
        admin, "ویرایش پلن اشتراک", "Subscription", severity="HIGH",
        target_id=plan_id, target_type="plan", target_label=patch["name"],
        before={k: old.get(k) for k in patch}, after=patch,
        tags=["اشتراک", "پلن", "پنل_وب"],
    )
    return {"ok": True}


@router.post("/plans")
async def add_plan(
    body: PlanBody,

    admin=Depends(require_perm("subscription.manage")),
):
    from core.features import FEATURE_CATALOG as _FCAT2
    _ent2 = {k: bool(v) for k, v in (body.entitlements or {}).items()
             if k in _FCAT2}
    plan_id = (
        await db.sub_plan_add(
            body.name.strip(),
            body.days,
            body.price,
            body.ai_daily_limit,
            _ent2,
            body.max_members,
        )
    )

    await _audit(
        admin, "ایجاد پلن اشتراک", "Subscription", severity="HIGH",
        target_id=str(plan_id), target_type="plan", target_label=body.name.strip(),
        after={"name": body.name.strip(), "days": body.days, "price": body.price,
               "ai_daily_limit": body.ai_daily_limit, "entitlements": _ent2,
               "max_members": body.max_members},
        tags=["اشتراک", "پلن", "پنل_وب"],
    )
    return {
        "ok":
            True,

        "id":
            plan_id,
    }


@router.post(
    "/plans/{plan_id}/toggle"
)
async def toggle_plan(
    plan_id: str,

    admin=Depends(require_perm("subscription.manage")),
):
    old = await db.sub_plan_get(plan_id)
    changed = (
        await db.sub_plan_toggle(
            plan_id
        )
    )

    if not changed:
        raise HTTPException(
            status_code=404,
            detail="پلن پیدا نشد",
        )

    new_state = not bool((old or {}).get("active", True))
    await _audit(
        admin, "تغییر وضعیت پلن اشتراک", "Subscription", severity="HIGH",
        target_id=plan_id, target_type="plan",
        target_label=(old or {}).get("name", plan_id),
        before={"active": bool((old or {}).get("active", True))},
        after={"active": new_state}, tags=["اشتراک", "پلن", "پنل_وب"],
    )
    return {
        "ok": True,
        "active": new_state,
    }


@router.delete(
    "/plans/{plan_id}"
)
async def delete_plan(
    plan_id: str,

    admin=Depends(require_perm("subscription.manage")),
):
    plan = (
        await db.sub_plan_get(
            plan_id
        )
    )

    if not plan:
        raise HTTPException(
            status_code=404,
            detail="پلن پیدا نشد",
        )

    if not await db.sub_plan_delete(
        plan_id
    ):
        raise HTTPException(
            status_code=500,
            detail="حذف پلن ناموفق بود؛ دوباره تلاش کنید.",
        )
    await _audit(
        admin, "حذف پلن اشتراک", "Subscription", severity="HIGH",
        target_id=plan_id, target_type="plan", target_label=plan.get("name", plan_id),
        before={"name": plan.get("name"), "days": plan.get("days"), "price": plan.get("price")},
        tags=["اشتراک", "پلن", "پنل_وب"],
    )

    return {
        "ok": True,
    }


class _FamilyAddBody(BaseModel):
    owner_id: int = Field(gt=0)
    user_id: int = Field(gt=0)


@router.get("/family")
async def family_overview_admin(
    owner_id: int,
    admin=Depends(require_perm("subscription.manage")),
):
    """🌊 W8/MISS-03 — اعضای خانواده‌ی یک مالک (ادمین)."""
    seats = await db.family_plan_seats(int(owner_id))
    members = []
    for m in await db.family_members(int(owner_id)):
        u = await db.get_user(int(m["_id"])) or {}
        members.append({
            "user_id": int(m["_id"]), "name": u.get("name", ""),
            "status": m.get("status", ""), "end_date": m.get("end_date"),
        })
    return {**seats, "members": members}


@router.post("/family/members")
async def family_add_admin(
    body: _FamilyAddBody,
    admin=Depends(require_perm("subscription.manage")),
):
    """🌊 W8/MISS-03 — افزودن مستقیم عضو توسط ادمین (بدون کد)."""
    owner_id, user_id = int(body.owner_id), int(body.user_id)
    if owner_id == user_id:
        raise HTTPException(status_code=422, detail="مالک و عضو یکی است")
    if not await db.sub_is_active(owner_id):
        raise HTTPException(status_code=409, detail="اشتراک مالک فعال نیست")
    if await db.sub_is_active(user_id):
        raise HTTPException(status_code=409, detail="این کاربر اشتراک فعال دارد")
    seats = await db.family_plan_seats(owner_id)
    if seats["total"] <= 1:
        raise HTTPException(status_code=409, detail="پلن مالک خانوادگی نیست")
    if seats["left"] <= 0:
        raise HTTPException(status_code=409, detail="ظرفیت خانواده پر شده")
    owner_sub = await db.sub_get(owner_id)
    now = utc_now_iso()
    await db.subscriptions.update_one(
        {"_id": user_id},
        {"$set": {"status": "active",
                  "plan_name": str(owner_sub.get("plan_name") or "خانواده"),
                  "plan_id": str(owner_sub.get("plan_id") or ""),
                  "start_date": now, "end_date": owner_sub.get("end_date"),
                  "source": "family", "granted_by": admin["id"],
                  "family_owner_id": owner_id, "family_code": "admin",
                  "last_plan_days": int(owner_sub.get("last_plan_days") or 0),
                  "reminder_3d_sent": False, "reminder_1d_sent": False,
                  "updated_at": now}},
        upsert=True)
    await _audit(
        admin, "افزودن عضو خانواده", "Subscription", severity="HIGH",
        target_id=str(user_id), target_type="user",
        after={"owner_id": owner_id},
        tags=["اشتراک", "خانواده", "پنل_وب"],
    )
    return {"ok": True}


@router.delete("/family/members/{user_id}")
async def family_remove_admin(
    user_id: int,
    owner_id: int,
    admin=Depends(require_perm("subscription.manage")),
):
    """🌊 W8/MISS-03 — حذف عضو توسط ادمین."""
    res = await db.family_remove(int(owner_id), int(user_id), admin["id"])
    if not res.get("ok"):
        raise HTTPException(status_code=409, detail=res.get("error"))
    await _audit(
        admin, "حذف عضو خانواده", "Subscription", severity="HIGH",
        target_id=str(user_id), target_type="user",
        tags=["اشتراک", "خانواده", "پنل_وب"],
    )
    return {"ok": True}


@router.get("/payments")
async def payments(
    status: str | None = Query(
        default=None
    ),

    skip: int = Query(
        default=0,
        ge=0,
    ),

    limit: int = Query(
        default=30,
        ge=1,
        le=100,
    ),

    search: str | None = Query(
        default=None
    ),

    kind: str | None = Query(
        default=None,
        description="topup | gift | normal — 🌊 W7 تفکیک نوع رسید",
    ),

    admin=Depends(require_perm("subscription.manage")),
):
    extra = (
        await _payment_search_filter(
            search
        )
    )
    # 🌊 W7 — فیلتر نوع رسید: شارژ کیف پول / هدیه / خرید عادی.
    # معیار همان داده است (plan_id ثابت شارژ، فیلد gift) — ستون جدید نساختیم.
    extra = extra or {}  # search=None → None برمی‌گردد، نه {}
    if kind == "topup":
        extra = {**extra, "plan_id": "wallet_topup"}
    elif kind == "gift":
        extra = {**extra, "gift.to": {"$exists": True}}
    elif kind == "normal":
        extra = {**extra,
                 "plan_id": {"$ne": "wallet_topup"},
                 "gift": {"$exists": False}}

    items = (
        await db
        .sub_payment_list_all(
            status=status,
            skip=skip,
            limit=limit,
            extra=extra,
        )
    )

    total = (
        await db
        .sub_payment_count_all(
            status=status,
            extra=extra,
        )
    )

    user_ids = list({
        item.get("user_id")

        for item in items

        if item.get("user_id")
    })

    if user_ids:
        users = (
            await db.users.find(
                {
                    "user_id": {
                        "$in":
                            user_ids,
                    }
                },

                {
                    "user_id": 1,
                    "name": 1,
                    "student_id": 1,
                    "username": 1,
                },
            )
            .to_list(
                len(user_ids)
            )
        )

    else:
        users = []

    users_map = {
        user["user_id"]:
            user

        for user in users
    }

    result = []

    for item in items:
        user_id = item.get(
            "user_id"
        )

        database_user = (
            users_map.get(
                user_id,
                {},
            )
        )

        result.append({
            "id":
                str(
                    item["_id"]
                ),

            "user_id":
                user_id,

            "user_name": (
                database_user.get(
                    "name"
                )
                or f"#{user_id}"
            ),

            "student_id":
                database_user.get(
                    "student_id",
                    "",
                ),

            "username": (
                database_user.get(
                    "username"
                )
                or ""
            ),

            "plan_id":
                item.get(
                    "plan_id",
                    "",
                ),

            "plan_name":
                item.get(
                    "plan_name",
                    "",
                ),

            "price":
                item.get(
                    "price",
                    0,
                ),

            "final_price":
                item.get(
                    "final_price",
                    item.get(
                        "price",
                        0,
                    ),
                ),

            # aliasهای افزودنی برای کلاینت‌های قدیمی/جدید؛ منبع هر سه
            # دقیقاً snapshot مالی final_price است.
            "final_amount":
                item.get("final_price", item.get("price", 0)),

            "amount":
                item.get("final_price", item.get("price", 0)),

            "discount_code":
                item.get(
                    "discount_code",
                    "",
                ),

            "discount_percent":
                item.get("discount_percent"),

            "has_receipt":
                bool(item.get("screenshot_file_id")),

            "status":
                item.get(
                    "status",
                    "pending",
                ),

            "submitted_at":
                str(
                    item.get(
                        "submitted_at",
                        "",
                    )
                )[:16],

            "review_note":
                item.get(
                    "review_note",
                    "",
                ),
        })

    return {
        "total":
            total,

        "payments":
            result,
    }


@router.get("/payments/{payment_id}/receipt")
async def payment_receipt(
    payment_id: str,
    admin=Depends(require_perm("subscription.manage")),
):
    """پروکسی امن تصویر رسید از Telegram؛ token هرگز به مرورگر نمی‌رود."""
    payment = await db.sub_payment_get(payment_id)
    file_id = (payment or {}).get("screenshot_file_id")
    if not file_id:
        raise HTTPException(status_code=404, detail="تصویر رسید موجود نیست")
    if not BOT_TOKEN:
        raise HTTPException(status_code=503, detail="TELEGRAM_TOKEN تنظیم نشده است")

    try:
        import httpx
        import mimetypes

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            meta_response = await client.get(
                f"{API_BASE}/getFile", params={"file_id": file_id})
            meta = meta_response.json() if meta_response.content else {}
            if meta_response.status_code != 200 or not meta.get("ok"):
                raise HTTPException(
                    status_code=502,
                    detail=str(meta.get("description") or "دریافت مسیر رسید ناموفق بود")[:200],
                )
            file_path = (meta.get("result") or {}).get("file_path")
            if not file_path:
                raise HTTPException(status_code=502, detail="مسیر فایل رسید خالی است")
            raw_response = await client.get(
                f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}")
            if raw_response.status_code != 200:
                raise HTTPException(status_code=502, detail="دریافت تصویر رسید ناموفق بود")
            if len(raw_response.content) > 20 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="حجم تصویر رسید بیش از حد مجاز است")
            media_type = (raw_response.headers.get("content-type")
                          or mimetypes.guess_type(file_path)[0]
                          or "application/octet-stream")
            return Response(
                content=raw_response.content,
                media_type=media_type,
                headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("receipt proxy failed: %s", exc)
        raise HTTPException(status_code=502, detail="دریافت تصویر رسید ناموفق بود")


@router.post(
    "/payments/{payment_id}/decision"
)
async def decide_payment(
    payment_id: str,

    body: DecisionBody,

    admin=Depends(require_perm("subscription.manage")),
):
    payment = (
        await db.sub_payment_get(
            payment_id
        )
    )

    if not payment:
        raise HTTPException(
            status_code=404,
            detail="رسید پیدا نشد",
        )

    if (
        payment.get("status")
        != "pending"
    ):
        raise HTTPException(
            status_code=409,

            detail=(
                "این رسید قبلاً "
                "بررسی شده"
            ),
        )


    if body.approved:
        plan = (
            await db.sub_plan_get(
                str(
                    payment.get(
                        "plan_id",
                        "",
                    )
                )
            )
        )

        days = int(
            plan.get(
                "days",
                0,
            )
            if plan
            else 0
        )

        if days <= 0:
            raise HTTPException(
                status_code=422,

                detail=(
                    "مدت پلن "
                    "نامعتبر است"
                ),
            )

    # 🛡 AUDIT-A1 — «تصمیم» باید ادعا شود، نه فقط نوشته: گذار اتمیک
    # pending→approved/rejected درون خودِ update است. اگر رسید را همان
    # لحظه ادمین دیگری (یا ربات) بسته باشد، ۴۰۹ می‌دهیم و هیچ اثر مالی
    # رخ نمی‌دهد — پیش از این check-then-act بود و دابل‌کلیک = دو دوره
    # اشتراک برای یک رسید.
    if not await db.sub_payment_decide(
        payment_id,

        approved=
            body.approved,

        admin_id=
            admin["id"],

        note=
            body.note.strip(),
    ):
        raise HTTPException(
            status_code=409,

            detail=(
                "این رسید هم‌زمان بررسی شد"
            ),
        )

    if body.approved:
        # 🌊 GIFT — فعال‌سازی از تنها نقطه‌ی مشترک (بات/وب یک‌جا):
        # رسید عادی → payer، رسید هدیه → recipient. اتمیک و یک‌بار.
        await db.finalize_approved_payment(
            payment,
            admin["id"],
        )


    if not body.approved and payment.get("discount_code"):
        # 🎟 موج D1 — کد در ثبت رسید مصرف شده؛ در رد، ظرفیت برمی‌گردد
        await db.discount_release(
            payment["discount_code"], user_id=payment["user_id"]
        )


    notification_collection = (
        db.client[
            "medicalbot"
        ][
            "bot_notifications"
        ]
    )


    if body.approved:
        notification_text = (
            "✅ رسید شما تأیید و "
            "اشتراک فعال شد."
        )

    else:
        notification_text = (
            "❌ رسید شما رد شد."
        )

        if body.note.strip():
            notification_text += (
                f"\n{body.note.strip()}"
            )

    # ROOT-FIX 🌊 GIFT — insert قبلاً داخل شاخه‌ی else بود و در تأیید
    # هیچ اعلانی برای payer ثبت نمی‌شد؛ notification_text هر دو شاخه
    # نشان می‌دهد insert باید برای هر دو تصمیم انجام شود.
    await notification_collection.insert_one({
        "type":
            "payment_decision",

        "chat_id":
            payment["user_id"],

        "text":
            notification_text,

        "sent":
            False,

        "created_at":
            utc_now_iso(),
    })

    # 🌊 GIFT — گیرنده هم از طریق همان outbox باخبر می‌شود
    # (نوتیفیکیشن هرگز rollback نمی‌کند؛ worker با retry می‌فرستد).
    _gift = payment.get("gift") or {}
    if body.approved and _gift.get("to"):
        _sender = await db.get_user(payment["user_id"])
        _sname = (
            (_sender or {}).get("name")
            or f"کاربر {payment['user_id']}"
        )
        await notification_collection.insert_one({
            "type": "gift_activated",
            "chat_id": int(_gift["to"]),
            "text": (
                "🎁 هدیه‌ای برایتان فعال شد!\n"
                f"{_sname} اشتراک «{payment.get('plan_name', '')}» "
                "را به شما هدیه داد. از امروز فعال است."
            ),
            "sent": False,
            "created_at": utc_now_iso(),
        })

    decision = "approved" if body.approved else "rejected"
    await _audit(
        admin, "بررسی رسید اشتراک", "Subscription", severity="HIGH",
        target_id=payment_id, target_type="payment",
        target_label=str(payment.get("user_id", "")),
        before={"status": payment.get("status", "pending")},
        after={"status": decision, "note": body.note.strip()},
        tags=["اشتراک", "رسید", "تصمیم_مالی", "پنل_وب"],
    )

    return {
        "ok": True,
    }


@router.post(
    "/payments/{payment_id}/send-receipt"
)
async def send_receipt(
    payment_id: str,

    admin=Depends(require_perm("subscription.manage")),
):
    payment = (
        await db.sub_payment_get(
            payment_id
        )
    )

    if (
        not payment
        or not payment.get(
            "screenshot_file_id"
        )
    ):
        raise HTTPException(
            status_code=404,

            detail=(
                "تصویر رسید موجود نیست"
            ),
        )


    sent = await _send(
        "sendDocument",

        {
            "chat_id":
                admin["id"],

            "document":
                payment[
                    "screenshot_file_id"
                ],

            "caption":
                f"رسید #{payment_id}",
        },
    )


    if not sent:
        raise HTTPException(
            status_code=502,

            detail=(
                "ارسال رسید ناموفق بود"
            ),
        )

    await _audit(
        admin, "ارسال تصویر رسید به مدیر", "Subscription", severity="WARNING",
        target_id=payment_id, target_type="payment",
        target_label=str(payment.get("user_id", "")),
        after={"recipient_admin_id": admin["id"]},
        tags=["اشتراک", "رسید", "حریم_خصوصی", "پنل_وب"],
    )

    return {
        "ok": True,
    }


@router.get("/subscribers")
async def subscribers(
    status: str = Query(
        default="active"
    ),

    skip: int = Query(
        default=0,
        ge=0,
    ),

    limit: int = Query(
        default=50,
        ge=1,
        le=100,
    ),

    search: str | None = Query(
        default=None
    ),

    admin=Depends(require_perm("subscription.manage")),
):
    extra = (
        await _subscriber_search_filter(
            search
        )
    )

    items = (
        await db.sub_list_by_status(
            status,
            skip,
            limit,
            extra=extra,
        )
    )

    total = (
        await db
        .sub_count_by_status(
            status,
            extra=extra,
        )
    )

    user_ids = [
        item.get("_id")
        for item in items
    ]

    if user_ids:
        users = (
            await db.users.find(
                {
                    "user_id": {
                        "$in":
                            user_ids,
                    }
                },

                {
                    "user_id": 1,
                    "name": 1,
                    "student_id": 1,
                    "username": 1,
                },
            )
            .to_list(
                len(user_ids)
            )
        )

    else:
        users = []

    users_map = {
        user["user_id"]:
            user

        for user in users
    }

    result = []

    for item in items:
        user_id = item.get(
            "_id"
        )

        database_user = (
            users_map.get(
                user_id,
                {},
            )
        )

        result.append({
            "user_id":
                user_id,

            "name": (
                database_user.get(
                    "name"
                )
                or f"#{user_id}"
            ),

            "student_id":
                database_user.get(
                    "student_id",
                    "",
                ),

            "username": (
                database_user.get(
                    "username"
                )
                or ""
            ),

            "plan_name":
                item.get(
                    "plan_name",
                    "",
                ),

            "status":
                item.get(
                    "status",
                    "",
                ),

            "end_date": item.get("end_date") or None,
        })

    return {
        "total":
            total,

        "subscribers":
            result,
    }


@router.get("/subscribers/{user_id}")
async def subscriber_detail(
    user_id: int,
    admin=Depends(require_perm("subscription.manage")),
):
    user = await db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="کاربر پیدا نشد")
    sub = await db.sub_get(user_id)
    history = await db.sub_payment_history(user_id)
    return {
        "user": {
            "id": user_id, "name": user.get("name", ""),
            "student_id": user.get("student_id", ""),
            "username": user.get("username", ""),
            "intake": user.get("intake", ""), "group": user.get("group", ""),
        },
        "subscription": ({
            "status": sub.get("status", ""), "plan_name": sub.get("plan_name", ""),
            "start_date": sub.get("start_date") or None,
            "end_date": sub.get("end_date") or None,
            "days_left": await db.sub_days_left(user_id),
            "source": sub.get("source", ""), "revoke_reason": sub.get("revoke_reason", ""),
        } if sub else None),
        "payments": [{
            "id": str(p.get("_id", "")), "plan_name": p.get("plan_name", ""),
            "price": p.get("price", 0),
            "final_price": p.get("final_price", p.get("price", 0)),
            "discount_code": p.get("discount_code", ""),
            "status": p.get("status", ""),
            "submitted_at": p.get("submitted_at") or None,
            "reviewed_at": p.get("reviewed_at") or None,
            "review_note": p.get("review_note", ""),
        } for p in history],
    }


async def _notify_subscription_change(user_id: int, title: str, body: str, dm: str, ntype: str):
    try:
        await db.notify_user(
            user_id, ntype, title=title, body=body,
            link="/me/subscription", dm=dm,
        )
    except Exception as exc:
        logger.warning("subscription notification failed for %s: %s", user_id, exc)


@router.get(
    "/users/search"
)
async def search_users_for_grant(
    q: str = Query(
        default="",
        max_length=80,
    ),

    admin=Depends(require_perm("subscription.manage")),
):
    """🔎 جست‌وجوی فشرده‌ی دانشجو برای
    «اعطای دستی» — همان موتور مشترک
    db.search_users (آیدی عددی دقیق،
    @یوزرنیم با/بدون @، نام و شماره
    دانشجویی) با خروجی سبک برای
    دراپ‌داون انتخاب."""

    raw = (q or "").strip()

    if len(raw) < 2:
        return {"users": []}

    results = (
        await db.search_users(
            raw,
            limit=8,
        )
    )

    return {
        "users": [
            {
                "id":
                    user.get(
                        "user_id"
                    ),

                "name":
                    user.get(
                        "name",
                        "",
                    ),

                "student_id":
                    user.get(
                        "student_id",
                        "",
                    ),

                "username":
                    user.get(
                        "username"
                    )
                    or "",
            }

            for user in results

            if user.get("user_id")
            is not None
        ]
    }


def _grant_key(admin, uids, days, extend, plan_name: str = '') -> str:
    """🛡 AUDIT-A1b — اثرانگشت پایدارِ یک اعطا برای «ادعای یکتا».

    همان ادمین + همان مجموعه‌ی کاربران + همان مقدار = همان کلید؛ پس
    دابل‌کلیک، رتریِ مرورگر یا «ارسال دوباره‌ی فرم بازمانده» اثر
    دوم تولید نمی‌کند.
    """
    payload = json.dumps(
        {
            "a": int(admin["id"]),
            "u": sorted(int(u) for u in uids),
            "d": int(days),
            "e": bool(extend),
            "p": str(plan_name or "").strip(),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


@router.post(
    "/subscribers/grant"
)
async def grant_subscription(
    body: GrantBody,

    admin=Depends(require_perm("subscription.manage")),
):
    user = (
        await db.get_user(
            body.user_id
        )
    )

    if not user:
        raise HTTPException(
            status_code=404,
            detail="کاربر پیدا نشد",
        )

    # 🛡 AUDIT-A1b — ادعای یکتا پیش از افزودن روز. کلید عمداً آزاد نمی‌شود:
    # حالت واقعی «اعطا انجام شد و پاسخ در شبکه گم شد → کاربر دوباره می‌زند»
    # دقیقاً همان چیزی است که باید خنثی شود؛ قفل با TTL (۲ دقیقه) پاک می‌شود.
    if not await db.op_claim(
        "sub_grant",

        _grant_key(
            admin,
            [body.user_id],
            body.days,
            body.extend,
            body.plan_name,
        ),
    ):
        raise HTTPException(
            status_code=409,

            detail=(
                "این اعطا همین حالا ثبت شده است "
                "(کلیک تکراری؟) — از تاریخچه "
                "مطمئن شوید."
            ),
        )

    end_date = (
        await db.sub_activate(
            body.user_id,

            body.days,

            body.plan_name
            .strip(),

            source=
                "manual",

            granted_by=
                admin["id"],

            extend=
                body.extend,
        )
    )


    end_text = format_datetime_fa(end_date, long=True)
    await _notify_subscription_change(
        body.user_id,
        "💎 اشتراک هامزیار فعال شد",
        f"پلن {body.plan_name.strip()} تا {end_text} فعال است.",
        (f"💎 <b>اشتراک هامزیار برای شما فعال شد</b>\n\n"
         f"📦 پلن: {body.plan_name.strip()}\n📅 پایان: {end_text}"),
        "sub_activated",
    )
    await _audit(
        admin, "فعال‌سازی دستی اشتراک", "Subscription", severity="HIGH",
        target_id=str(body.user_id), target_type="user", target_label=user.get("name", ""),
        after={"days": body.days, "plan": body.plan_name.strip(),
               "extend": body.extend, "end_date": end_text},
        tags=["اشتراک", "اعطای_دستی", "پنل_وب"],
    )
    return {
        "ok":
            True,

        "end_date":
            end_text,
    }


@router.post("/subscribers/grant-bulk")
async def grant_subscription_bulk(
    body: BulkGrantBody,
    admin=Depends(require_perm("subscription.manage")),
):
    target_ids: list[int] = []
    unresolved: list[str] = []

    if body.mode == "role":
        role = (body.role or "").strip()
        if not role:
            raise HTTPException(status_code=422, detail="نقش هدف الزامی است")
        target_ids.extend(await db.user_ids_by_role(role, limit=1000))
    else:
        for raw in body.identifiers[:500]:
            ident = str(raw or "").strip()
            if not ident:
                continue
            if ident.lstrip("+-").isdigit():
                uid = int(ident)
                if await db.get_user(uid):
                    target_ids.append(uid)
                else:
                    unresolved.append(ident)
                continue
            matches = await db.search_users(ident, limit=20)
            low = ident.lstrip("@").lower()
            exact = [u for u in matches if
                     str(u.get("username") or "").lower() == low or
                     str(u.get("student_id") or "") == ident or
                     str(u.get("name") or "").strip().lower() == ident.lower()]
            chosen = exact[0] if len(exact) == 1 else (matches[0] if len(matches) == 1 else None)
            if chosen and chosen.get("user_id") is not None:
                target_ids.append(int(chosen["user_id"]))
            else:
                unresolved.append(ident)

    target_ids = list(dict.fromkeys(target_ids))[:1000]
    if not target_ids:
        raise HTTPException(status_code=422, detail="هیچ کاربر معتبری برای اعطا پیدا نشد")

    # 🛡 AUDIT-A1b — اعطای گروهی «یک‌بارمصرف»: تکرار درخواست = ۱۰۰۰ کاربر
    # با دو برابر اعتبار، پس کلید مجموعه هدف + مقدار هم ادعا می‌شود.
    if not await db.op_claim(
        "sub_grant_bulk",
        _grant_key(admin, target_ids, body.days, body.extend, body.plan_name),
        ttl_seconds=600,
    ):
        raise HTTPException(
            status_code=409,
            detail="این اعطای گروهی همین حالا ثبت شده است (کلیک تکراری؟) — لطفاً یک‌بار صبر کنید.",
        )

    granted, failed = 0, []
    for uid in target_ids:
        try:
            end_date = await db.sub_activate(
                uid, body.days, body.plan_name.strip(), source="free_grant",
                granted_by=admin["id"], extend=body.extend)
            end_text = format_datetime_fa(end_date, long=True)
            await _notify_subscription_change(
                uid, "🎁 اشتراک رایگان هامزیار",
                f"{body.days} روز اشتراک تا {end_text} برای شما فعال شد.",
                (f"🎁 <b>اشتراک رایگان هامزیار برای شما فعال شد</b>\n\n"
                 f"⏳ مدت: {body.days} روز\n📅 پایان: {end_text}"),
                "sub_activated",
            )
            granted += 1
        except Exception as exc:
            logger.warning("bulk subscription grant failed for %s: %s", uid, exc)
            failed.append(uid)

    await _audit(
        admin, "اعطای دسته‌جمعی اشتراک رایگان", "Subscription", severity="HIGH",
        target_type="subscription_batch", target_label=f"{granted} کاربر",
        after={"mode": body.mode, "role": body.role, "days": body.days,
               "granted": granted, "failed": len(failed), "unresolved": len(unresolved)},
        tags=["اشتراک", "اعطای_دسته_جمعی", "پنل_وب"],
    )
    return {"ok": True, "granted": granted, "failed_ids": failed,
            "unresolved": unresolved, "total_resolved": len(target_ids)}


@router.post(
    "/subscribers/{user_id}/revoke"
)
async def revoke_subscription(
    user_id: int,

    body: RevokeBody,

    admin=Depends(require_perm("subscription.manage")),
):
    user = await db.get_user(user_id)
    revoked = (
        await db.sub_revoke(
            user_id,

            body.reason
            .strip(),

            admin["id"],
        )
    )

    if not revoked:
        raise HTTPException(
            status_code=404,

            detail=(
                "اشتراک پیدا نشد"
            ),
        )

    await _notify_subscription_change(
        user_id,
        "⛔ اشتراک هامزیار لغو شد",
        body.reason.strip(),
        f"⛔ <b>اشتراک هامزیار لغو شد</b>\n\n📝 دلیل: {body.reason.strip()}",
        "sub_expired",
    )
    await _audit(
        admin, "لغو اشتراک کاربر", "Subscription", severity="HIGH",
        target_id=str(user_id), target_type="user",
        target_label=(user or {}).get("name", str(user_id)),
        after={"status": "revoked", "reason": body.reason.strip()},
        tags=["اشتراک", "لغو", "پنل_وب"],
    )
    return {
        "ok": True,
    }


@router.get("/discounts")
async def discounts(
    admin=Depends(require_perm("subscription.manage")),
):
    items = (
        await db.discount_list()
    )

    return {
        "discounts": [
            {
                "code":
                    item.get(
                        "code",
                        "",
                    ),

                "percent":
                    item.get(
                        "percent",
                        0,
                    ),

                "max_uses":
                    item.get(
                        "max_uses",
                        0,
                    ),

                "used_count":
                    item.get(
                        "used_count",
                        0,
                    ),

                "expires_at": item.get("expires_at") or None,

                "active":
                    item.get(
                        "active",
                        True,
                    ),

                "target_plan_ids":
                    item.get(
                        "target_plan_ids",
                        [],
                    )
                    or [],

                "per_user_limit":
                    item.get(
                        "per_user_limit",
                        0,
                    )
                    or 0,
            }

            for item in items
        ],
    }


@router.post("/discounts")
async def add_discount(
    body: DiscountBody,

    admin=Depends(require_perm("subscription.manage")),
):
    try:
        created = await db.discount_add(
            body.code, body.percent, body.max_uses, body.expires_at,
            admin["id"], body.target_plan_ids, body.per_user_limit,
        )
    except ValueError as exc:
        if str(exc) == "invalid_discount_expiry":
            raise HTTPException(status_code=422, detail="تاریخ انقضای تخفیف معتبر نیست")
        raise

    if not created:
        raise HTTPException(
            status_code=409,
            detail="کد تکراری است",
        )

    await _audit(
        admin, "ایجاد کد تخفیف", "Subscription", severity="HIGH",
        target_id=body.code.upper(), target_type="discount", target_label=body.code.upper(),
        after={"percent": body.percent, "max_uses": body.max_uses,
               "expires_at": body.expires_at, "target_plan_ids": body.target_plan_ids or [],
               "per_user_limit": body.per_user_limit},
        tags=["اشتراک", "تخفیف", "پنل_وب"],
    )
    return {
        "ok": True,
    }


@router.post(
    "/discounts/{code}/toggle"
)
async def toggle_discount(
    code: str,

    admin=Depends(require_perm("subscription.manage")),
):
    old = await db.discount_get(code)
    changed = (
        await db.discount_toggle(
            code
        )
    )

    if not changed:
        raise HTTPException(
            status_code=404,

            detail=(
                "کد پیدا نشد"
            ),
        )

    new_state = not bool((old or {}).get("active", True))
    await _audit(
        admin, "تغییر وضعیت کد تخفیف", "Subscription", severity="HIGH",
        target_id=code.upper(), target_type="discount", target_label=code.upper(),
        before={"active": bool((old or {}).get("active", True))},
        after={"active": new_state}, tags=["اشتراک", "تخفیف", "پنل_وب"],
    )
    return {
        "ok": True,
        "active": new_state,
    }


@router.delete(
    "/discounts/{code}"
)
async def delete_discount(
    code: str,

    admin=Depends(require_perm("subscription.manage")),
):
    old = await db.discount_get(code)
    deleted = (
        await db.discount_delete(
            code
        )
    )

    if not deleted:
        raise HTTPException(
            status_code=404,

            detail=(
                "کد پیدا نشد"
            ),
        )

    await _audit(
        admin, "حذف کد تخفیف", "Subscription", severity="HIGH",
        target_id=code.upper(), target_type="discount", target_label=code.upper(),
        before={"percent": (old or {}).get("percent"),
                "used_count": (old or {}).get("used_count"),
                "max_uses": (old or {}).get("max_uses")},
        tags=["اشتراک", "تخفیف", "پنل_وب"],
    )
    return {
        "ok": True,
    }



# ══════════════════════════════════════════════════
#  🎟 موج D1 — کمپین تخفیف: Preview / Broadcast / Status / Stats
#  Bot و Mini App هر دو از همین API استفاده می‌کنند — Source of Truth
#  موتور تولید پیام: discount_campaign.py (Dynamic، بدون Hardcode)
# ══════════════════════════════════════════════════

async def _campaign_msg(discount: dict, title=None, description=None):
    from discount_campaign import build_campaign_message
    overrides = {}
    if title:
        overrides['title'] = title
    if description:
        overrides['description'] = description
    _, text = await build_campaign_message(db, discount, overrides=overrides or None)
    return text


@router.post("/discounts/{code}/preview")
async def preview_discount_campaign(
    code: str,

    admin=Depends(require_perm("subscription.manage")),
):
    discount = await db.discount_get(code)
    if not discount:
        raise HTTPException(status_code=404, detail="کد پیدا نشد")
    text = await _campaign_msg(discount)
    from discount_campaign import resolve_target_plans, campaign_cta_link
    plans = await resolve_target_plans(db, discount)
    return {
        "ok": True,
        "text": text,
        "plans": [{"id": str(p["_id"]), "name": p.get("name",""),
                   "days": p.get("days", 0), "price": p.get("price", 0)} for p in plans],
        "cta_link": campaign_cta_link(discount),
    }


@router.post("/discounts/{code}/broadcast")
async def start_discount_broadcast(
    code: str,

    body: DiscountBroadcastBody,

    admin=Depends(require_perm("subscription.manage")),
):
    from api.telegram_send import _send as _tg_send
    import asyncio as _asyncio

    discount = await db.discount_get(code)
    if not discount:
        raise HTTPException(status_code=404, detail="کد پیدا نشد")
    if not discount.get("active"):
        raise HTTPException(status_code=422, detail="این کد غیرفعال است — اول فعالش کن.")

    # ضد دابل‌کلیک: اگر broadcast همین کد در حال ارسال است
    active_bc = await db.discount_bcast_active_for(code)
    if active_bc:
        raise HTTPException(status_code=409, detail="انتشار قبلی همین کد هنوز در حال اجراست.")

    text = await _campaign_msg(discount, body.title, body.description)
    users = await db.discount_segment_users(body.target)
    # 🎚 ادغام نوتیفیکیشن: کاربرانی که دسته‌ی «🎁 تخفیف‌ها» را خاموش
    # کرده‌اند از ارسال DM کنار گذاشته می‌شوند
    try:
        _defaults = await db.get_notif_defaults()
        users = [u for u in users if db.notif_pref_on(
            u.get("notification_settings", {}), "discounts", _defaults)]
    except Exception as e:
        # 🧹 W5 — فیلتر ترجیحات در صورت خطا fail-open مانده (رفتار قبلی
        # حفظ شده) ولی دیگر silent نیست: در لاگ ثبت می‌شود
        logger.warning(f"discount notif-pref filter failed (fail-open): {e}")
    if not users:
        raise HTTPException(status_code=422,
            detail="هیچ مخاطبی در این بخش نیست (پس از اعمال ترجیحات اعلان کاربران).")

    from discount_campaign import campaign_cta_link
    from utils import webapp_url
    cta_url = webapp_url(campaign_cta_link(discount))
    kb_rows = []
    if cta_url:
        kb_rows.append([{
            "text": "🎟 دریافت اشتراک با تخفیف",
            "web_app": {"url": cta_url},
        }])
    kb_rows.append([
        {"text": "💳 تهیه اشتراک با تخفیف (در بات)",
         "callback_data": f"sub:dcode:{code}"}
    ])

    bid = await db.discount_bcast_create(code, body.target, admin["id"], source='web')
    await db.discount_bcast_update(bid, {"total": len(users)})

    await _audit(
        admin, "broadcast_started", "Discounts", severity="INFO",
        target_id=bid, target_type="broadcast", target_label=code,
        after={"code": code, "target": body.target, "total": len(users)},
        tags=["broadcast", "discount"],
    )

    async def _run():
        import os
        BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
        import httpx
        sent = failed = blocked = 0
        cancelled = False
        msg_refs = []  # ⛔ موج D2 — مرجع پیام‌های موفق برای ادیت «اتمام موجودی»
        base = f"https://api.telegram.org/bot{BOT_TOKEN}"
        reply_markup = {"inline_keyboard": kb_rows} if kb_rows else None
        async with httpx.AsyncClient(timeout=30) as cli:
            for i, u in enumerate(users):
                # ⛔ توقف: هر ۲۰ نفر وضعیت را از دیتابیس می‌خوانیم
                if i > 0 and i % 20 == 0:
                    cur = await db.discount_bcast_get(bid)
                    if cur and cur.get("status") == "cancelled":
                        cancelled = True
                        break
                uid = u["user_id"]
                payload = {
                    "chat_id": uid, "text": text, "parse_mode": "HTML",
                }
                if reply_markup:
                    payload["reply_markup"] = reply_markup
                outcome = "fail"  # ok | fail | blocked — شمارش دقیق هر کاربر
                for _attempt in range(3):
                    try:
                        r = await cli.post(f"{base}/sendMessage", json=payload)
                        if r.status_code == 200 and r.json().get("ok"):
                            outcome = "ok"
                            _mid = r.json().get("result", {}).get("message_id")
                            if _mid:
                                msg_refs.append({"c": uid, "m": _mid})
                            break
                        if r.status_code == 429:
                            # RetryAfter — صبر دقیق به اندازه‌ی اعلام تلگرام
                            ra = r.json().get("parameters", {}).get("retry_after", 2)
                            await _asyncio.sleep(ra + 0.5)
                            continue
                        if r.status_code == 403:
                            outcome = "blocked"
                            await db.mark_user_blocked(uid)
                            break
                        await _asyncio.sleep(1.2)
                        continue
                    except Exception:
                        await _asyncio.sleep(1.2)
                        continue
                if outcome == "ok":
                    sent += 1
                elif outcome == "blocked":
                    blocked += 1
                else:
                    failed += 1
                # گام‌بندی نرخ — الگوی _do_broadcast_send
                await _asyncio.sleep(0.05)
                if (i + 1) % 25 == 0 or (i + 1) == len(users):
                    if msg_refs:
                        try:
                            await db.discount_bcast_add_msgs(bid, msg_refs)
                        except Exception as e:
                            # 🧹 W5 — از دست رفتن مرجع پیام‌ها silent نماند
                            logger.warning(f"bcast add_msgs failed ({bid}): {e}")
                        msg_refs = []
                    await db.discount_bcast_update(bid, {
                        "sent": sent, "failed": failed, "blocked": blocked})
        # خالی‌کردن مراجع باقی‌مانده (در صورت توقف زودهنگام)
        if msg_refs:
            try:
                await db.discount_bcast_add_msgs(bid, msg_refs)
            except Exception as e:
                logger.warning(f"bcast add_msgs final flush failed ({bid}): {e}")
        await db.discount_bcast_update(bid, {
            "status": "cancelled" if cancelled else "completed",
            "sent": sent, "failed": failed,
            "blocked": blocked, "finished_at": utc_now_iso(),
        })
        if not cancelled:
            await _audit(
                admin, "broadcast_completed", "Discounts", severity="INFO",
                target_id=bid, target_type="broadcast", target_label=code,
                after={"sent": sent, "failed": failed, "blocked": blocked},
                tags=["broadcast", "discount"],
            )

    # 🛡 AUDIT-M1 — مرجع نگه‌داشتن + ثبت خطا (قبلاً شکست broadcast فقط یک
    # «Task exception was never retrieved» در stdout بود)
    from utils import spawn_bg
    spawn_bg(_run(), 'discount_broadcast_web')
    return {"ok": True, "broadcast_id": bid, "total": len(users)}


@router.get("/discounts/{code}/broadcast/{bid}")
async def discount_broadcast_status(
    code: str, bid: str,

    admin=Depends(require_perm("subscription.manage")),
):
    bc = await db.discount_bcast_get(bid)
    if not bc or bc.get("code") != code:
        raise HTTPException(status_code=404, detail="broadcast پیدا نشد")
    return {
        "ok": True,
        "broadcast_id": bid,
        "status": bc.get("status"),
        "total": bc.get("total", 0),
        "sent": bc.get("sent", 0),
        "failed": bc.get("failed", 0),
        "blocked": bc.get("blocked", 0),
        "created_at": bc.get("created_at"),
        "finished_at": bc.get("finished_at"),
    }


@router.post("/discounts/{code}/broadcast/{bid}/cancel")
async def cancel_discount_broadcast(
    code: str, bid: str,

    admin=Depends(require_perm("subscription.manage")),
):
    bc = await db.discount_bcast_get(bid)
    if not bc or bc.get("code") != code:
        raise HTTPException(status_code=404, detail="broadcast پیدا نشد")
    if bc.get("status") != "sending":
        raise HTTPException(status_code=422, detail="این انتشار دیگر فعال نیست.")
    await db.discount_bcast_update(bid, {"status": "cancelled"})
    await _audit(
        admin, "broadcast_cancelled", "Discounts", severity="INFO",
        target_id=bid, target_type="broadcast", target_label=code,
    )
    return {"ok": True}


@router.get("/discounts/{code}/broadcasts")
async def discount_broadcasts_list(
    code: str,

    admin=Depends(require_perm("subscription.manage")),
):
    items = await db.discount_bcast_list(code, 10)
    return {
        "broadcasts": [
            {
                "broadcast_id": b.get("broadcast_id"),
                "status": b.get("status"),
                "target": b.get("target"),
                "total": b.get("total", 0),
                "sent": b.get("sent", 0),
                "failed": b.get("failed", 0),
                "blocked": b.get("blocked", 0),
                "created_at": b.get("created_at"),
                "finished_at": b.get("finished_at"),
            } for b in items
        ]
    }


@router.get("/discounts/{code}/stats")
async def discount_stats(
    code: str,

    admin=Depends(require_perm("subscription.manage")),
):
    discount = await db.discount_get(code)
    if not discount:
        raise HTTPException(status_code=404, detail="کد پیدا نشد")
    pay = await db.discount_payment_stats(code)
    mu = discount.get("max_uses", 0)
    used = discount.get("used_count", 0)
    remaining = max(0, mu - used) if mu > 0 else None
    targets = discount.get("target_plan_ids") or []
    plans_names = []
    if targets:
        plans = await db.sub_plan_list(only_active=False)
        plans_names = [p["name"] for p in plans if str(p["_id"]) in [str(t) for t in targets]]
    return {
        "ok": True,
        "code": code,
        "percent": discount.get("percent", 0),
        "used_count": used,
        "max_uses": mu,
        "remaining_uses": remaining,
        "target_plans": plans_names or None,
        "per_user_limit": discount.get("per_user_limit", 0),
        "expires_at": discount.get("expires_at") or None,
        "active": discount.get("active", True),
        "payments": pay,
    }


@router.put("/card")
async def update_card(
    body: CardBody,

    admin=Depends(require_perm("subscription.manage")),
):
    old_number = await db.get_setting("subscription_card_number", "")
    old_owner = await db.get_setting("subscription_card_owner", "")
    await db.set_setting(
        "subscription_card_number",

        body.card_number
        .strip(),
    )

    await db.set_setting(
        "subscription_card_owner",

        body.card_owner
        .strip(),
    )

    await _audit(
        admin, "ویرایش اطلاعات کارت اشتراک", "Subscription", severity="HIGH",
        target_type="settings", target_label="کارت پرداخت",
        before={"card_number": old_number, "card_owner": old_owner},
        after={"card_number": body.card_number.strip(), "card_owner": body.card_owner.strip()},
        tags=["اشتراک", "کارت", "پنل_وب"],
    )
    return {
        "ok": True,
    }


# ═══════════════ 🌊 GIFT — مدیریت هدیه‌ها ═══════════════
@router.get("/gifts")
async def list_gifts(
    status: str = Query("all"),
    payer: int = Query(0),
    recipient: int = Query(0),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    admin=Depends(require_perm("subscription.manage")),
):
    """لیست هدیه‌ها با صفحه‌بندی اجباری (قرارداد W4).

    فیلترها: status ∈ all/pending/approved/rejected/refunded/cancelled،
    payer، recipient. نام‌ها از users همان لحظه join می‌شوند."""
    q = {"gift.to": {"$exists": True}}
    if status != "all":
        q["status"] = status
    if payer:
        q["user_id"] = int(payer)
    if recipient:
        q["gift.to"] = int(recipient)
    total = await db.sub_payments.count_documents(q)
    docs = (
        await db.sub_payments.find(q)
        .sort("submitted_at", -1)
        .skip((page - 1) * per_page)
        .limit(per_page)
        .to_list(per_page)
    )
    items = []
    for d in docs:
        p = await db.get_user(d.get("user_id", 0))
        r = await db.get_user((d.get("gift") or {}).get("to", 0))
        items.append({
            "id": str(d.get("_id", "")),
            "payer_id": d.get("user_id", 0),
            "payer_name": (p or {}).get("name", "—"),
            "recipient_id": (d.get("gift") or {}).get("to", 0),
            "recipient_name": (r or {}).get("name", "—"),
            "plan_name": d.get("plan_name", ""),
            "final_price": d.get("final_price", 0),
            "status": d.get("status", "pending"),
            "submitted_at": d.get("submitted_at", ""),
            "message": (d.get("gift") or {}).get("message", ""),
            "activated_at": (d.get("gift") or {}).get("activated_at"),
        })
    return {"ok": True, "items": items, "total": total,
            "page": page, "per_page": per_page}


@router.post("/gifts/{payment_id}/cancel")
async def cancel_gift(payment_id: str, admin=Depends(require_perm("subscription.manage"))):
    """لغو هدیه‌ی pending (CAS). فعال‌سازی دستی کور وجود ندارد —
    تنها مسیر فعال‌سازی، تأیید رسید است (تصمیم §۵۸)."""
    payment = await db.sub_payment_get(payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="هدیه پیدا نشد")
    if not (payment.get("gift") or {}).get("to"):
        raise HTTPException(status_code=422, detail="این رسید هدیه نیست")
    if not await db.sub_payment_cancel(payment_id, admin["id"]):
        raise HTTPException(
            status_code=409, detail="فقط هدیه‌ی در انتظار را می‌توان لغو کرد")
    notification_collection = db.client["medicalbot"]["bot_notifications"]
    await notification_collection.insert_one({
        "type": "gift_cancelled",
        "chat_id": payment["user_id"],
        "text": "ℹ️ درخواست هدیه‌ی اشتراک شما توسط مدیریت لغو شد.",
        "sent": False,
        "created_at": utc_now_iso(),
    })
    await _audit(
        admin, "لغو هدیه اشتراک", "Subscription", severity="HIGH",
        target_id=payment_id, target_type="payment",
        before={"status": payment.get("status")}, after={"status": "cancelled"},
        tags=["اشتراک", "هدیه", "پنل_وب"],
    )
    return {"ok": True, "status": "cancelled"}


@router.post("/gifts/{payment_id}/retry-notify")
async def retry_gift_notify(payment_id: str, admin=Depends(require_perm("subscription.manage"))):
    """ارسال دوباره‌ی اعلان گیرنده از طریق همان outbox —
    نوتیفیکیشن هرگز تراکنش را rollback نکرده و همیشه قابل retry است."""
    payment = await db.sub_payment_get(payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="هدیه پیدا نشد")
    gift = payment.get("gift") or {}
    if not gift.get("to"):
        raise HTTPException(status_code=422, detail="این رسید هدیه نیست")
    if payment.get("status") != "approved":
        raise HTTPException(
            status_code=409, detail="فقط هدیه‌ی فعال‌شده اعلان دارد")
    sender = await db.get_user(payment["user_id"])
    sname = (sender or {}).get("name") or f"کاربر {payment['user_id']}"
    notification_collection = db.client["medicalbot"]["bot_notifications"]
    await notification_collection.insert_one({
        "type": "gift_activated",
        "chat_id": int(gift["to"]),
        "text": (
            "🎁 هدیه‌ای برایتان فعال شد!\n"
            f"{sname} اشتراک «{payment.get('plan_name', '')}» "
            "را به شما هدیه داد. از امروز فعال است."
        ),
        "sent": False,
        "created_at": utc_now_iso(),
    })
    await _audit(
        admin, "ارسال دوباره اعلان هدیه", "Subscription", severity="MEDIUM",
        target_id=payment_id, target_type="payment",
        tags=["اشتراک", "هدیه", "پنل_وب"],
    )
    return {"ok": True, "queued": True}
