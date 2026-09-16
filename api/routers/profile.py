"""User profile endpoints for the Telegram Mini App."""
import asyncio
from typing import Any, List, Mapping

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import ADMIN_ID, get_current_user
from api.user_metrics import non_negative_int, normalize_stats, normalize_weekly
from database import db
from request_context import current_request_id

async def _profile_audit(actor: dict, action: str, *, before=None, after=None, details: str = "", target_label: str = ""):
    try:
        db_user = actor.get("_db") if isinstance(actor.get("_db"), dict) else {}
        name = (db_user.get("name") or actor.get("name") or str(actor.get("id") or ""))
        from database import db as _db
        # actor role: try resolve
        try:
            role_label = await _db.get_actor_role_label(actor["id"])
        except Exception:
            role_label = "student"
        await _db.log_action(
            actor["id"], name, role_label,
            action, "Profile", category="user", severity="INFO",
            target_id=str(actor["id"]), target_type="user", target_label=target_label or name,
            before=before, after=after, details=details,
        )
    except Exception:
        pass

router = APIRouter()
_VALID_ROLES = {"student", "content_admin", "support", "admin"}


def _text(value: Any, default: str = "") -> str:
    return str(value).strip() if value is not None else default


def _role_for(uid: int, db_user: Mapping[str, Any]) -> str:
    if uid == ADMIN_ID:
        return "admin"
    role = _text(db_user.get("role"), "student")
    return role if role in _VALID_ROLES else "student"


@router.get("")
async def get_profile(user=Depends(get_current_user)):
    uid = user["id"]
    db_user = user["_db"] if isinstance(user.get("_db"), Mapping) else {}
    raw_stats, weekly, raw_tickets, roles_info, user_perms, nick_status = \
        await asyncio.gather(
            db.user_stats(uid),
            db.weekly_activity(uid),
            db.ticket_get_user(uid),
            db.get_user_roles(uid),
            db.get_user_perms(uid),
            db.nickname_status(uid, db_user),
        )

    stats = normalize_stats(raw_stats)
    stats["weekly_chart"] = normalize_weekly(weekly)
    tickets = raw_tickets if isinstance(raw_tickets, list) else []

    return {
        "user": {
            "name": _text(db_user.get("name")),
            "intake": _text(db_user.get("intake")),
            "group": _text(db_user.get("group")),
            "student_id": _text(db_user.get("student_id")),
            "role": _role_for(uid, db_user),
            "telegram_id": uid,
            # 🛡 RBAC-W1 (افزایشی): کلیدهای نقش + union مجوزها —
            # منبع گیت‌های مینی‌اپ در موج W3؛ فیلدهای قبلی دست‌نخورده
            "roles": roles_info["keys"],
            "roles_detail": [
                {
                    "key":   r["_id"],
                    "label": r.get("label", r["_id"]),
                    "icon":  r.get("icon", "🛡"),
                    "color": r.get("color", "#70A7FF"),
                }
                for r in roles_info["roles"]
            ],
            "perms": sorted(user_perms),
            # 🏷 Identity v1 (افزایشی — «user» قبلی دست‌نخورده):
            # هویت اجتماعی + چراغ‌های قابل‌تغییر برای FE
            "nickname": nick_status["nickname"],
            "display_name": nick_status["display_name"],
            "can_change_nickname": nick_status["can_change_nickname"],
            "next_change_at": nick_status["next_change_at"],
            "show_real_name": nick_status["show_real_name"],
            "nickname_cooldown_days": nick_status["cooldown_days"],
        },
        "stats": stats,
        "tickets": {
            "open": sum(
                1
                for ticket in tickets
                if isinstance(ticket, Mapping) and ticket.get("status") == "open"
            ),
            "closed": sum(
                1
                for ticket in tickets
                if isinstance(ticket, Mapping) and ticket.get("status") == "closed"
            ),
        },
    }


class NameUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.patch("/name")
async def update_name(body: NameUpdate, user=Depends(get_current_user)):
    name = " ".join(body.name.split())
    if len(name) < 3 or len(name) > 50 or "<" in name or ">" in name:
        raise HTTPException(status_code=422, detail="نام نامعتبر")
    await db.update_user(user["id"], {"name": name})
    await _profile_audit(user, "ویرایش نام نمایشی", before={"name": (user.get("_db") or {}).get("name")}, after={"name": name})
    return {"ok": True, "name": name}


# 🏷 Identity v1 — پیام‌های خطای لقب از db.NICK_ERROR_FA می‌آیند
# (تک‌منبع مشترک API/Bot — §یک منبع واحد)


class NicknameUpdate(BaseModel):
    nickname: str = Field(default="", max_length=80)


@router.patch("/nickname")
async def update_nickname(
    body: NicknameUpdate,
    user=Depends(get_current_user),
):
    """🏷 تنظیم/تغییر/پاک‌کردن لقب — خالی ⇒ پاک‌کردن (§۳).
    Validation کاملاً سمت سرور در db.validate_nickname است."""
    ok, err, info = await db.set_nickname(
        user["id"], body.nickname, changed_by="user",
    )
    if not ok:
        raise HTTPException(
            status_code=422,
            detail=db.nick_error_text(err, info),
        )
    await _profile_audit(user, "ویرایش لقب", after={"nickname": info.get("nickname"), "display_name": info.get("display_name")})
    return {
        "ok": True,
        "nickname": info.get("nickname"),
        "display_name": info.get("display_name"),
    }


class PrivacyUpdate(BaseModel):
    show_real_name: bool


@router.patch("/privacy")
async def update_privacy(
    body: PrivacyUpdate,
    user=Depends(get_current_user),
):
    """🏷 §Privacy — سوییچ نمایش نام واقعی در سطوح اجتماعی."""
    await db.set_show_real_name(user["id"], body.show_real_name)
    await _profile_audit(user, "تغییر حریم خصوصی نام", before={"show_real_name": not bool(body.show_real_name)}, after={"show_real_name": bool(body.show_real_name)})
    return {"ok": True, "show_real_name": body.show_real_name}


class GroupUpdate(BaseModel):
    group: str = Field(pattern=r"^[12]$")


@router.patch("/group")
async def update_group(body: GroupUpdate, user=Depends(get_current_user)):
    await db.update_user(user["id"], {"group": body.group})
    await _profile_audit(user, "ویرایش گروه", before={"group": (user.get("_db") or {}).get("group")}, after={"group": body.group})
    return {"ok": True, "group": body.group}


class IntakeUpdate(BaseModel):
    intake: str = Field(min_length=1, max_length=50)


@router.patch("/intake")
async def update_intake(body: IntakeUpdate, user=Depends(get_current_user)):
    intake = body.intake.strip()
    active = await db.get_active_intakes()
    active_codes = {
        _text(item.get("code"))
        for item in (active if isinstance(active, list) else [])
        if isinstance(item, Mapping) and _text(item.get("code"))
    }
    if not intake or intake not in active_codes:
        raise HTTPException(status_code=422, detail="ورودی نامعتبر")
    await db.update_user(user["id"], {"intake": intake})
    await _profile_audit(user, "ویرایش ورودی", before={"intake": (user.get("_db") or {}).get("intake")}, after={"intake": intake})
    return {"ok": True, "intake": intake}


class StudentIdUpdate(BaseModel):
    student_id: str = Field(min_length=3, max_length=20)


@router.patch("/student-id")
async def update_student_id(
    body: StudentIdUpdate, user=Depends(get_current_user)
):
    student_id = body.student_id.strip()
    if not student_id.isdigit():
        raise HTTPException(status_code=422, detail="شماره دانشجویی باید عدد باشد")
    await db.update_user(user["id"], {"student_id": student_id})
    await _profile_audit(user, "ویرایش شماره دانشجویی", before={"student_id": (user.get("_db") or {}).get("student_id")}, after={"student_id": student_id})
    return {"ok": True, "student_id": student_id}


@router.get("/rank")
async def get_rank(user=Depends(get_current_user)):
    uid = user["id"]
    db_user = user["_db"] if isinstance(user.get("_db"), Mapping) else {}
    if non_negative_int(db_user.get("total_answers")) == 0:
        return {"rank": None, "total_users": 0, "percentile": 0}

    my_correct = non_negative_int(db_user.get("correct_answers"))
    query = {"approved": True, "total_answers": {"$gt": 0}}
    better, total = await asyncio.gather(
        db.users.count_documents({**query, "correct_answers": {"$gt": my_correct}}),
        db.users.count_documents(query),
    )
    total = non_negative_int(total)
    better = min(non_negative_int(better), total)
    return {
        "rank": better + 1 if total else None,
        "total_users": total,
        "percentile": round((1 - better / total) * 100) if total else 0,
    }


@router.get("/prestige")
async def get_prestige(user=Depends(get_current_user)):
    """👑 وضعیت کامل Prestige (موج P0) — افزایشی؛ منبع یکتا db.prestige_state."""
    state = await db.prestige_state(user["id"])
    return {"prestige": state}


@router.get("/prestige/badges")
async def get_prestige_badges(user=Depends(get_current_user)):
    """👑 P1 — کلکسیون کامل نشان‌ها (۵ تکاملی + تکی‌ها + جهانی‌ها)"""
    data = await db.prestige_badges(user["id"])
    if data is None:
        raise HTTPException(status_code=404, detail="کاربر پیدا نشد")
    return {"badges": data}


@router.get("/prestige/history")
async def get_prestige_history(
    limit: int = 30,
    user=Depends(get_current_user),
):
    """👑 P1 — «سفر من»: تایم‌لاین رویدادهای پرستیژ با تاریخ جلالی"""
    limit = max(1, min(int(limit), 100))
    items = await db.prestige_history_list(user["id"], limit)
    return {"items": items}


class ShowcaseInput(BaseModel):
    keys: List[str] = []


@router.put("/prestige/showcase")
async def put_prestige_showcase(
    body: ShowcaseInput,
    user=Depends(get_current_user),
):
    """👑 P1 — پین حداکثر ۳ نشان بازشده (اعتبارسنجی سروری)"""
    keys = [str(k)[:60] for k in (body.keys or [])][:10]
    res = await db.prestige_showcase_set(user["id"], keys)
    await _profile_audit(user, "ویرایش ویترین افتخار", after={"keys": keys[:3]})
    return res


class PrivacyInput(BaseModel):
    public: bool


@router.patch("/prestige/privacy")
async def patch_prestige_privacy(
    body: PrivacyInput,
    user=Depends(get_current_user),
):
    """👑 P2 — کلید پوشش عمومی (پیش‌فرض روشن؛ نام در لیدربرد/فید ماسک می‌شود)"""
    await db.users.update_one(
        {"user_id": user["id"]},
        {"$set": {"privacy_public": bool(body.public)}},
    )
    await _profile_audit(user, "تغییر حریم عمومی پرستیژ", after={"privacy_public": bool(body.public)})
    return {"ok": True, "privacy_public": bool(body.public)}


@router.get("/prestige/public/{target_uid}")
async def get_prestige_public(
    target_uid: int,
    user=Depends(get_current_user),
):
    """👑 P2 — Hero Card عمومی: رنک/Top٪/شوکیس/رکوردها — بدون آمار حساس"""
    try:
        tid = int(target_uid)
    except Exception:
        raise HTTPException(status_code=422, detail="شناسه‌ی نامعتبر")
    data = await db.prestige_public(tid)
    if not data.get("ok"):
        raise HTTPException(status_code=404, detail="کاربر پیدا نشد")
    return data


@router.get("/intakes")
async def get_intakes(user=Depends(get_current_user)):
    items = await db.get_active_intakes()
    result = []
    seen = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, Mapping):
            continue
        code = _text(item.get("code"))
        if not code or code in seen:
            continue
        seen.add(code)
        result.append(
            {"code": code, "label": _text(item.get("label"), code) or code}
        )
    return {"intakes": result}


@router.get("/badges")
async def get_badges(user=Depends(get_current_user)):
    stats = normalize_stats(await db.user_stats(user["id"]))
    total = stats["total_answers"]
    percentage = stats["percentage"]
    downloads = stats["downloads"]

    earned = set()
    if total >= 1:
        earned.add("first")
    if total >= 50:
        earned.add("fifty")
    if total >= 200:
        earned.add("two_hundred")
    if percentage >= 70:
        earned.add("seventy")
    if percentage >= 90:
        earned.add("ninety")
    if downloads >= 10:
        earned.add("downloader")

    return {
        "badges": [
            {"id": "first", "title": "اولین قدم", "icon": "🌱", "earned": "first" in earned},
            {"id": "fifty", "title": "۵۰ سوال", "icon": "🧪", "earned": "fifty" in earned},
            {"id": "two_hundred", "title": "۲۰۰ سوال", "icon": "🏆", "earned": "two_hundred" in earned},
            {"id": "seventy", "title": "۷۰٪ موفق", "icon": "⭐", "earned": "seventy" in earned},
            {"id": "ninety", "title": "۹۰٪ موفق", "icon": "🥇", "earned": "ninety" in earned},
            {"id": "downloader", "title": "خواننده", "icon": "📚", "earned": "downloader" in earned},
        ]
    }

# ══════════════════════════════════════════════
# 💙 حمایت مالی — خواندن زنده همان تنظیماتی که
# ربات برای دکمه «💙 حمایت مالی» استفاده می‌کند
# ══════════════════════════════════════════════

@router.get("/donation")
async def donation_config(user=Depends(get_current_user)):
    """تنظیمات حمایت مالی برای مینی‌اپ.

    دقیقاً همان کلیدهایی که message_router.py ربات مصرف می‌کند
    (donation_enabled + donation_link) — پس فعال‌سازی/تغییر لینک
    از سمت بات بلافاصله در مینی‌اپ هم اعمال می‌شود (سینک کامل).
    """
    enabled = bool(await db.get_setting("donation_enabled", False))
    link = (await db.get_setting("donation_link", None)) or ""
    return {"enabled": enabled and bool(link), "link": link}
