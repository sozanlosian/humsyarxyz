"""📝 Registration — ثبت‌نام دانشجو از داخل Mini App.

این روتر دقیقاً با فلوی ثبت‌نام بات (start.py) سینک است:
  * همان قوانین اعتبارسنجی (نام ۳ تا ۵۰ حرف، شماره دانشجویی ۵ تا ۳۰)
  * همان تنظیمات زنده (require_student_id، ورودی‌های فعال)
  * همان db.create_user — پس schema کاربران دو کانال کاملاً یکسان است
  * همان چک‌های امنیتی (بلک‌لیست، تأیید ادمین ارشد)
  * ثبت رویداد در audit_logs با تگ «ثبت_نام» مثل بات
"""
import logging
import os
from datetime import datetime
from time_utils import utc_now_iso
from api.rate_limit import rate_limit_user  # 🛡 W3/SEC-03
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from api.auth import verify_telegram_init_data
from database import db

logger = logging.getLogger(__name__)
router = APIRouter()

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))


# ══════════════════════════════════════════════
#  احراز هویت سبک — برای کاربران هنوز‌ثبت‌نشده
# ══════════════════════════════════════════════

def _verified_tg_user(x_init_data: str) -> dict:
    """فقط امضای تلگرام را چک می‌کند (بدون نیاز به رکورد تأییدشده در DB).

    get_current_user برای کاربر not_registered خطای 403 می‌دهد؛ اما
    ثبت‌نام دقیقاً برای همان کاربران است پس به این نسخه سبک‌تر نیاز داریم.
    """
    tg_user = verify_telegram_init_data(x_init_data)
    try:
        uid = int(tg_user["id"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(401, "invalid_user_data")
    return {**tg_user, "id": uid}


def _notify_admin(text: str):
    """اطلاع به ادمین ارشد از طریق صف داخلی bot_notifications —
    همان مکانیزمی که admin_panel.py استفاده می‌کند و بات آن را می‌فرستد."""
    notif = db.client["medicalbot"]["bot_notifications"]
    return notif.insert_one({
        "type": "admin_notice",
        "chat_id": ADMIN_ID,
        "text": text,
        "sent": False,
        "created_at": utc_now_iso(),
    })


async def _public_state(uid: int):
    """وضعیت ثبت‌نام کاربر + تنظیماتی که فرم مینی‌اپ لازم دارد."""
    user = await db.get_user(uid)
    blacklisted = await db.is_blacklisted(uid)

    if blacklisted:
        state = "blacklisted"
    elif not user:
        state = "not_registered"
    elif user.get("suspended"):
        state = "suspended"
    elif user.get("approved"):
        state = "approved"
    else:
        state = "pending"

    require_sid = bool(await db.get_setting("require_student_id", False))
    intakes = await db.get_active_intakes()

    return {
        "state": state,
        "require_student_id": require_sid,
        "intakes": [
            {"code": i.get("code", ""), "label": i.get("label", "")}
            for i in intakes
        ],
        "groups": ["1", "2"],
        "user": {
            "name": user.get("name", ""),
            "group": user.get("group", ""),
            "intake": user.get("intake", ""),
        } if user else None,
    }


# ══════════════════════════════════════════════
#  وضعیت فعلی (درایو فرم + پولینگ صفحه انتظار)
# ══════════════════════════════════════════════

@router.get("/status")
async def registration_status(x_init_data: str = Header(default="", alias="X-Init-Data")):
    tg_user = _verified_tg_user(x_init_data)
    data = await _public_state(tg_user["id"])
    data["tg_first_name"] = (
        tg_user.get("first_name")
        or tg_user.get("username")
        or ""
    )
    return data


# ══════════════════════════════════════════════
#  ثبت‌نام
# ══════════════════════════════════════════════

class RegisterBody(BaseModel):
    name: str
    group: str
    intake: Optional[str] = ""
    student_id: Optional[str] = ""
    ref: Optional[str] = ""  # 🌱 W13 — کد دعوت (اختیاری)


@router.post("/register")
async def register_via_miniapp(
    body: RegisterBody,
    x_init_data: str = Header(default="", alias="X-Init-Data"),
):
    tg_user = _verified_tg_user(x_init_data)
    uid = tg_user["id"]
    # 🛡 W3/SEC-03 — ضد اسپم ثبت‌نام (init-data امضاشده است؛ کلید = کاربر)
    await rate_limit_user(uid, "register", 5, 600)
    username = tg_user.get("username")

    # ── لایه دفاعی بلک‌لیست (مثل بات) ──
    if await db.is_blacklisted(uid):
        raise HTTPException(403, "blacklisted")

    # ── قبلاً ثبت‌نام کرده ──
    existing = await db.get_user(uid)
    if existing:
        raise HTTPException(
            409,
            "already_registered" if existing.get("approved") else "already_pending",
        )

    # ── نام (قانون بات: ۳ تا ۵۰) ──
    name = (body.name or "").strip()
    if len(name) < 3:
        raise HTTPException(422, "نام باید حداقل ۳ حرف باشد")
    if len(name) > 50:
        raise HTTPException(422, "نام نباید بیشتر از ۵۰ حرف باشد")

    # ── گروه (مثل بات: فقط ۱ یا ۲) ──
    group = (body.group or "").strip()
    if group not in ("1", "2"):
        raise HTTPException(422, "گروه درسی نامعتبر است")

    # ── ورودی — فقط از میان ورودی‌های فعال ──
    intake = (body.intake or "").strip()
    active_codes = {
        i.get("code", "") for i in await db.get_active_intakes()
    }
    if intake and intake not in active_codes:
        raise HTTPException(422, "ورودی تحصیلی نامعتبر است")
    if not active_codes:
        intake = ""   # مثل بات: بدون ورودی فعال، این مرحله حذف می‌شود

    # ── شماره دانشجویی — الزام از تنظیمات زنده خوانده می‌شود ──
    require_sid = bool(await db.get_setting("require_student_id", False))
    student_id = (body.student_id or "").strip()
    if require_sid and not student_id:
        raise HTTPException(422, "شماره دانشجویی الزامی است")
    if student_id and not (5 <= len(student_id) <= 30):
        raise HTTPException(422, "شماره دانشجویی باید بین ۵ تا ۳۰ کاراکتر باشد")

    # ── ساخت کاربر — تابع مشترک با بات، schema یکسان ──
    # دابل‌کلیک/درخواست همزمان → ایندکس یکتای user_id خطا می‌دهد؛
    # آن را به 409 تمیز تبدیل می‌کنیم (نه ۵۰۰).
    try:
        await db.create_user(uid, name, student_id, group, username, intake=intake)
    except Exception as e:
        if "duplicate key" in str(e).lower():
            raise HTTPException(409, "already_registered")
        raise

    # 🌱 W13 — attribution دعوت (exception-safe؛ ثبت‌نام را نمی‌شکند)
    try:
        if (body.ref or "").strip():
            from referral import attribute as _ref_attribute
            await _ref_attribute(uid, body.ref, 'miniapp')
    except Exception:
        pass

    if uid == ADMIN_ID:
        await db.update_user(uid, {"approved": True})
        return {"ok": True, "state": "approved"}

    # ── اطلاع به ادمین ارشد ──
    try:
        intake_label = next(
            (i.get("label") for i in await db.get_active_intakes()
             if i.get("code") == intake),
            intake or "نامشخص",
        )
        _notify_admin(
            "🔔 <b>درخواست ثبت‌نام جدید</b> (از مینی‌اپ)\n\n"
            f"👤 نام: <b>{name}</b>\n"
            f"👥 گروه: <b>{group}</b>\n"
            f"📅 ورودی: <b>{intake_label}</b>\n"
            f"📱 یوزرنیم: @{username or 'ندارد'}\n"
            f"🆔 آیدی: <code>{uid}</code>\n\n"
            "برای تأیید: پنل مدیریت ← مدیریت کاربران"
        )
    except Exception as e:
        logger.warning(f"Cannot notify admin about mini-app registration: {e}")

    # ── ثبت در لاگ فعالیت (هم‌خانواده با لاگ بات) ──
    try:
        await db.log_action(
            uid, name, "دانشجو",
            "ثبت‌نام کاربر جدید", "Users", "admin", "INFO",
            str(uid), "user", name,
            None, None,
            f"گروه: {group} | ورودی: {intake or 'نامشخص'} | منبع: مینی‌اپ",
            ["ثبت_نام", "مینی_اپ"],
        )
    except Exception as e:
        logger.warning(f"audit log for registration failed: {e}")

    # ── FIX سینک: ثبت‌نام از ربات با send_audit_log به گروه لاگ هم
    # می‌رسد؛ ثبت‌نام از مینی‌اپ هم باید همان‌طور به گروه برسد تا گروه
    # تصویر کامل هر دو کانال را داشته باشد (با همان قالب مشترک) ──
    try:
        from utils import build_audit_log_text
        chat_id = await db.get_setting("log_group_admin", None)
        if chat_id:
            text = build_audit_log_text(
                "admin", name, uid, "ثبت‌نام کاربر جدید",
                module="Users", severity="INFO", actor_role="دانشجو",
                target_id=str(uid), target_type="user", target_label=name,
                details=f"گروه: {group} | ورودی: {intake or 'نامشخص'} | منبع: مینی‌اپ",
                tags=["ثبت_نام", "مینی_اپ"],
            )
            notif = db.client["medicalbot"]["bot_notifications"]
            await notif.insert_one({
                "type": "audit_log_web",
                "chat_id": int(chat_id),
                "text": text,
                "sent": False,
                "created_at": utc_now_iso(),
            })
    except Exception as e:
        logger.warning(f"registration log-group sync failed: {e}")

    return {"ok": True, "state": "pending"}
