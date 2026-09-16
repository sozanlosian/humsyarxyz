"""👑 Admin Panel"""
import asyncio
import logging
import os
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from api.auth import require_perm
from api.rate_limit import rate_limit_user  # 🛡 W10/RATE-01
from database import db
from question_bank.contracts import approved_query, status_query
from request_context import current_request_id
import broadcast_service
from time_utils import day_bounds_utc, fa_digits, now_utc, parse_gregorian_date, utc_now_iso

router = APIRouter()
ADMIN_ID = int(os.getenv("ADMIN_ID","0"))
logger = logging.getLogger(__name__)


async def _notify(chat_id: int, text: str, ntype: str = "admin_notice"):
    # 🌊 W-Admin-fix: قبلاً coroutine اینسرت هرگز await نمی‌شد ⇒ همه‌ی اعلان‌های
    # این روتر (تأیید کاربر، پاسخ تیکت، سیگنال‌ها) سکوت-coroutine می‌شدند.
    notif = db.client["medicalbot"]["bot_notifications"]
    return await notif.insert_one({"type":ntype,"chat_id":chat_id,"text":text,
        "sent":False,"created_at":utc_now_iso(),
        "correlation_id": current_request_id.get()})


async def _audit(admin, action: str, module: str, *, severity: str = "INFO",
                 target_id: str = "", target_type: str = "",
                 target_label: str = "", details: str = "",
                 before: dict = None, after: dict = None,
                 tags: list = None):
    """ثبت رویداد در audit_logs برای اقدامات انجام‌شده از پنل وب +
    ارسال همان رویداد به گروه لاگ تلگرام از طریق صف bot_notifications.

    مقادیر به‌صورت موضعی (positional) به db.log_action داده می‌شوند تا
    دقیقاً با امضای موجود در database.py سازگار بمانند.

    FIX سینک: قبلاً لاگ‌های وب فقط در دیتابیس می‌ماندند و گروه لاگ
    تلگرام هرگز اقدامات پنل وب را نمی‌دید (فقط لاگ‌های ربات را).
    حالا متن با همان build_audit_log_text مشترکِ ربات ساخته می‌شود و به
    گروه log_group_admin صف می‌شود — قالب پیام در گروه برای هر دو کانال
    کاملاً یکدست است و لاگ‌های وب با تگ #پنل_وب مشخص می‌شوند.
    ثبت پایدار لاگ بخشی از invariant عملیات حساس است؛ شکست آن با 503
    اعلام می‌شود (صف تلگرام اما وابستگی ثانویه و fail-open است).
    """
    try:
        actor = admin.get("_db") or {}
        uid  = actor.get("user_id", admin.get("id", 0))
        name = actor.get("name", "مدیر ارشد")
        # نقش واقعی با همان منطق ربات (مدیر ارشد/نقش‌های فرعی/...) تا
        # در گروه و دیتابیس دقیقاً مثل لاگ‌های ربات دیده شود
        try:
            role = await db.get_actor_role_label(uid)
        except Exception:
            role = actor.get("role", "admin")
        # 🆕 Audit Refactor — Correlation/Request propagation (§10-§11)
        corr = current_request_id.get() or None
        # request_id را اگر در context موجود بود بفرست (همان correlation برای وب)
        await db.log_action(
            uid, name, role,
            action, module, "admin", severity,
            str(target_id), target_type, target_label,
            before, after, details, tags, correlation_id=corr,
            source="api", channel="web",
            request_id=corr, metadata={"endpoint": module},
        )
        # سینک با گروه لاگ تلگرام — همان متنی که send_audit_log می‌سازد
        try:
            from utils import build_audit_log_text
            chat_id = await db.get_setting("log_group_admin", None)
            if chat_id:
                sync_tags = list(dict.fromkeys((tags or []) + ["پنل_وب"]))
                text = build_audit_log_text(
                    "admin", name, uid, action,
                    module=module, severity=severity, actor_role=role,
                    target_id=str(target_id), target_type=target_type,
                    target_label=target_label, before=before, after=after,
                    details=details, tags=sync_tags,
                )
                await _notify(int(chat_id), text, "audit_log_web")
        except Exception:
            # Telegram log delivery is secondary: the durable DB audit above
            # is the invariant and should not depend on Bot API availability.
            logger.warning("web audit notification enqueue failed for %s", action)
    except Exception as exc:
        # Mutations must not report success when their durable audit trail is
        # unavailable. Callers receive a retryable 503 (sensitive move
        # endpoints already rollback around this helper).
        logger.exception("durable web audit write failed for %s", action)
        raise HTTPException(status_code=503, detail="ثبت حسابرسی انجام نشد؛ دوباره تلاش کنید") from exc


def _rp_mini(u: dict) -> dict:
    """👑 P3 — مینی-چیپ پرستیژ از فیلدهای ذخیره‌شده (بدون کوئری اضافه)."""
    ranks = {r[0]: r for r in db.PRESTIGE_RANKS}
    r = ranks.get(u.get("prestige_rank") or "rookie", ranks["rookie"])
    try:
        dv = int(u.get("prestige_div", 3) or 3)
    except Exception:
        dv = 3
    return {"icon": r[2], "title": r[1], "color": r[4],
            "div": dv, "roman": db.ROMAN.get(dv, "III"),
            "stars": db.DIV_STARS.get(dv, "⭐")}


@router.get("/stats")
async def stats(admin=Depends(require_perm("stats.view"))):
    """نمای فشرده‌ی واقعی داشبورد مالک.

    کلیدهای flat برای Web Admin فعلی نگه داشته می‌شوند و آبجکت‌های nested
    نیز برای مصرف‌کننده‌های قدیمی باقی می‌مانند. هیچ مقدار placeholder یا
    عدد ساختگی در پاسخ وجود ندارد.
    """
    from utils import today_start_utc_str

    today_start = today_start_utc_str()
    week_ago = (now_utc() - timedelta(days=7)).isoformat()
    (users_total, users_pending, questions_approved, questions_pending,
     tickets_open, reports_open, subscriptions, active_today, active_week,
     new_today, total_answers) = await asyncio.gather(
        db.users.count_documents({"approved": True}),
        db.users.count_documents({"approved": False}),
        db.questions.count_documents(approved_query()),
        db.questions.count_documents(status_query("pending")),
        db.tickets.count_documents({"status": "open"}),
        db.content_reports.count_documents({"status": "new"}),
        db.sub_stats(),
        db.count_active_users_today(),
        db.users.count_documents({"last_active": {"$gte": week_ago}}),
        db.users.count_documents({"registered_at": {"$gte": today_start}}),
        db.answers.count_documents({}),
    )
    return {
        "active_today": active_today,
        "active_week": active_week,
        "new_today": new_today,
        "total_answers": total_answers,
        "users": {"total": users_total, "pending": users_pending},
        "questions": {"approved": questions_approved, "pending": questions_pending},
        "tickets": {"open": tickets_open},
        "reports": {"open": reports_open},
        "subscriptions": subscriptions or {},
    }

@router.get("/bot-status")
async def bot_status(admin=Depends(require_perm("stats.view"))):
    """سلامت واقعی DB/API و حضور process ربات در همان container.

    این endpoint heartbeat تلگرام را جعل نمی‌کند: ``bot_ok`` فقط می‌گوید
    process مربوط به ``bot.py`` زنده دیده شده است. جزئیات خطا نیز جداگانه
    برگردانده می‌شود تا UI حالت نامشخص را با «سالم» اشتباه نگیرد.
    """
    import time

    db_ping = None
    db_error = ""
    db_ok = False
    try:
        t0 = time.monotonic()
        await db.client.admin.command("ping")
        db_ping = int((time.monotonic() - t0) * 1000)
        db_ok = True
    except Exception as e:
        db_error = str(e)[:160]

    bot_ok = False
    bot_pid = None
    bot_error = ""
    sys_info = {}
    try:
        import psutil
        import os as _os

        current_pid = _os.getpid()
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                args = p.info.get("cmdline") or []
                proc_name = (p.info.get("name") or "").lower()
                executable = _os.path.basename(args[0]).lower() if args else ""
                has_bot_arg = any(_os.path.basename(str(arg)) == "bot.py" for arg in args[1:])
                is_python = "python" in proc_name or executable.startswith("python")
                if p.info.get("pid") != current_pid and is_python and has_bot_arg:
                    bot_ok = True
                    bot_pid = p.info.get("pid")
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        proc = psutil.Process(current_pid)
        mem = proc.memory_info().rss / 1024 / 1024
        vm = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=None)
        up = time.time() - proc.create_time()
        d, r = divmod(int(up), 86400)
        h, r = divmod(r, 3600)
        m, s = divmod(r, 60)
        if d:
            uptime_fa = f"{fa_digits(d)} روز و {fa_digits(h)} ساعت"
        elif h:
            uptime_fa = f"{fa_digits(h)} ساعت و {fa_digits(m)} دقیقه"
        elif m:
            uptime_fa = f"{fa_digits(m)} دقیقه و {fa_digits(s)} ثانیه"
        else:
            uptime_fa = f"{fa_digits(s)} ثانیه"
        sys_info = {
            "api_ram_mb": round(mem, 1),
            "total_ram_mb": round(vm.total / 1024 / 1024),
            "used_ram_pct": vm.percent,
            "cpu_pct": cpu,
            "uptime": uptime_fa,
        }
    except Exception as e:
        bot_error = str(e)[:160]

    return {
        "api_ok": True,
        "bot_ok": bot_ok,
        "bot_pid": bot_pid,
        "bot_error": bot_error,
        "db_ok": db_ok,
        "db_ping_ms": db_ping,
        "db_error": db_error,
        "checked_at": utc_now_iso(),
        "sys": sys_info,
    }

# ══════════════════════════════════════════════
# 👥 کاربران
# ══════════════════════════════════════════════

@router.get("/users")
async def list_users(admin=Depends(require_perm("users.view")), search: Optional[str]=Query(None),
                      group: Optional[str]=Query(None), intake: Optional[str]=Query(None)):
    # 🔎 قرارداد مشترک جست‌وجو (db.build_user_search_query) — حالا آیدی
    # عددی تلگرام هم دقیق پیدا می‌شود؛ قبلاً فقط name/student_id/username
    # بود و با ربات ناسازگار بود.
    q = db.build_user_search_query(search) if search else {}
    if group: q["group"]=group
    if intake: q["intake"]=intake
    # 🚀 موج ۴.۶۰ — projection: قبلاً سند کامل هر کاربر (شامل
    # notification_settings تو‌در‌تو، weak_topics، آمار و…) روی
    # سیم می‌رفت؛ فقط فیلدهای مصرفی پاسخ fetch می‌شود.
    _projection = {
        "user_id": 1, "name": 1, "student_id": 1,
        "group": 1, "intake": 1, "role": 1,
        "approved": 1, "suspended": 1,
        "registered_at": 1, "total_answers": 1,
        # 👑 P3 — مینی-چیپ پرستیژ برای NameChip در UserManagement
        "prestige_rank": 1, "prestige_div": 1,
    }
    users = await db.users.find(q, _projection).sort("registered_at",-1).to_list(500)
    return {"users":[{"id":u.get("user_id"),"name":u.get("name",""),
        # 🏷 Identity v1 — ادمین همیشه هر دو هویت را می‌بیند (§۳)
        "nickname": u.get("nickname"),
        "display_name": db.display_name_of(u),
        "student_id":u.get("student_id",""),
        "group":u.get("group",""),"intake":u.get("intake",""),"role":u.get("role","student"),
        "approved":u.get("approved",False),"suspended":u.get("suspended",False),
        "registered_at":u.get("registered_at") or None,"total_answers":u.get("total_answers",0),
        "prestige": _rp_mini(u)} for u in users]}

@router.get("/users/pending")
async def pending_users(admin=Depends(require_perm("users.view"))):
    users = await db.pending_users()
    return {"users":[{"id":u.get("user_id"),"name":u.get("name",""),"student_id":u.get("student_id",""),
        "group":u.get("group",""),"intake":u.get("intake",""),"registered_at":u.get("registered_at") or None} for u in users]}

@router.get("/users/{uid}")
async def user_detail(uid: int, admin=Depends(require_perm("users.view"))):
    u = await db.get_user(uid)
    if not u: raise HTTPException(404, "کاربر پیدا نشد")
    return {"user":{"id":u.get("user_id"),"name":u.get("name",""),
        "nickname": u.get("nickname"),
        "display_name": db.display_name_of(u),
        "student_id":u.get("student_id",""),
        "group":u.get("group",""),"intake":u.get("intake",""),"role":u.get("role","student"),
        "approved":u.get("approved",False),"suspended":u.get("suspended",False),
        "registered_at":u.get("registered_at") or None,"total_answers":u.get("total_answers",0),
        "correct_answers":u.get("correct_answers",0),"downloads":u.get("downloads",0)}}

@router.post("/users/{uid}/approve")
async def approve(uid: int, admin=Depends(require_perm("users.manage"))):
    user = await db.get_user(uid)
    if not user: raise HTTPException(404)
    await db.update_user(uid,{"approved":True})
    await _notify(uid, "✅ <b>حساب شما تأیید شد!</b>\n\nاکنون می‌توانید از هامزیار استفاده کنید.\n/start بزنید.", "user_approved")
    # 🔔 موج ۴.۹۰ — اینباکس مینی‌اپ (تأیید حساب)
    await db.inbox_add(uid, 'account', "✅ حسابت تأیید شد!",
        "اکنون به تمام بخش‌های هامزیار دسترسی داری — خوش اومدی! 🎓", link='/')
    await _audit(admin, "تأیید حساب کاربر", "Users", severity="INFO",
        target_id=uid, target_type="user", target_label=user.get("name",""),
        tags=["تأیید_کاربر","پنل_وب"])
    return {"ok":True}

@router.post("/users/{uid}/reject")
async def reject(uid: int, admin=Depends(require_perm("users.manage"))):
    user = await db.get_user(uid)
    await db.users.delete_one({"user_id":uid})
    await _audit(admin, "رد درخواست عضویت", "Users", severity="WARNING",
        target_id=uid, target_type="user",
        target_label=(user or {}).get("name",""),
        tags=["رد_کاربر","پنل_وب"])
    return {"ok":True}

@router.post("/users/{uid}/suspend")
async def suspend(uid: int, admin=Depends(require_perm("users.manage"))):
    if uid == ADMIN_ID: raise HTTPException(403,"نمی‌توانید ادمین را تعلیق کنید")
    user = await db.get_user(uid)
    if not user: raise HTTPException(404)
    suspended = not user.get("suspended",False)
    await db.update_user(uid,{"suspended":suspended, "approved": not suspended})
    if suspended:
        await _notify(uid, "⚠️ دسترسی شما موقتاً تعلیق شد.", "user_suspended")
    await _audit(admin,
        "تعلیق حساب کاربر" if suspended else "رفع تعلیق حساب کاربر",
        "Users", severity="HIGH" if suspended else "INFO",
        target_id=uid, target_type="user", target_label=user.get("name",""),
        before={"suspended":not suspended}, after={"suspended":suspended},
        tags=["تعلیق_کاربر","پنل_وب"])
    return {"ok":True,"suspended":suspended}


class DmBody(BaseModel):
    """متن پیام مستقیم ادمین به کاربر"""
    text: str


@router.post("/users/{uid}/message")
async def dm_user_ep(uid: int, body: DmBody, admin=Depends(require_perm("users.message"))):
    # ✉️ موج ۴.۸۰ — پیام مستقیم از کارت کاربر مینی‌اپ.
    # ارسال واقعی از طریق صف bot_notifications (همان کانالی که خودِ ربات
    # برای اطلاع‌رسانی‌ها استفاده می‌کند) انجام می‌شود؛ جاب outbox هر ۲۰
    # ثانیه تخلیه می‌کند — پاسخ صادقانه «در صف قرار گرفت» است.
    user = await db.get_user(uid)
    if not user: raise HTTPException(404, "کاربر پیدا نشد")
    text = body.text.strip()
    if len(text) < 2:    raise HTTPException(400, "متن پیام خیلی کوتاه است")
    if len(text) > 3500: raise HTTPException(400, "متن پیام خیلی بلند است (حداکثر ۳۵۰۰ کاراکتر)")
    # بدنه escape می‌شود: نه تزریق HTML، نه شکستن ارسال با «<»
    from html import escape as _esc
    out = (
        "📩 <b>پیام از مدیریت هامزیار</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"{_esc(text)}"
    )
    # _notify سنکرون صدا زده می‌شود و insert را برمی‌گرداند؛ اگر خروجی
    # coroutine باشد (motor) باید await شود تا درج واقعاً اجرا شود —
    # در حالت درایور همگام هم بی‌اثر است. بدون این، پیام گاهی فقط
    # «برنامه‌ریزی» می‌شد و هرگز به outbox نمی‌نشست.
    _res = await _notify(uid, out, "admin_dm")
    if asyncio.iscoroutine(_res):
        await _res
    # 🔔 موج ۴.۹۰ — پیام مستقیم در مرکز اعلان مینی‌اپ هم می‌نشیند؛
    # حتی اگر ربات بلاک باشد، کاربر آنجا می‌خواندش
    await db.inbox_add(uid, 'admin_dm', "📩 پیام از مدیریت هامزیار",
        text[:400], link=None)
    await _audit(admin, "ارسال پیام مستقیم به کاربر", "Users", severity="INFO",
        target_id=uid, target_type="user", target_label=user.get("name",""),
        details=text[:100], tags=["پیام_مستقیم","پنل_وب"])
    return {"ok": True, "queued": True}

@router.post("/users/{uid}/delete")
async def delete_user_ep(uid: int, admin=Depends(require_perm("users.delete"))):
    if uid == ADMIN_ID: raise HTTPException(403,"نمی‌توانید ادمین ارشد را حذف کنید")
    user = await db.get_user(uid)
    if not user: raise HTTPException(404)
    await _notify(uid, "❌ حساب شما حذف شد.", "user_deleted")
    await db.delete_user(uid)
    await _audit(admin, "حذف حساب کاربر", "Users", severity="CRITICAL",
        target_id=uid, target_type="user", target_label=user.get("name",""),
        tags=["حذف_کاربر","پنل_وب"])
    return {"ok":True}

@router.post("/users/{uid}/block")
async def block_user_ep(uid: int, admin=Depends(require_perm("users.delete"))):
    if uid == ADMIN_ID: raise HTTPException(403,"نمی‌توانید ادمین ارشد را بلاک کنید")
    user = await db.get_user(uid)
    if not user: raise HTTPException(404)
    actor_name = admin["_db"].get("name","مدیر ارشد")
    await db.block_user(uid, blocked_by=admin["id"], blocked_by_name=actor_name)
    await db.blacklist.update_one({"_id":uid},{"$set":{"name":user.get("name","")}})
    await _notify(uid, "🚫 حساب شما مسدود شد و امکان ثبت‌نام مجدد ندارید.", "user_blocked")
    await _audit(admin, "مسدودسازی کاربر (بلک‌لیست)", "Users", severity="CRITICAL",
        target_id=uid, target_type="user", target_label=user.get("name",""),
        tags=["بلاک_کاربر","پنل_وب"])
    return {"ok":True}

@router.post("/users/{uid}/unblock")
async def unblock_user_ep(uid: int, admin=Depends(require_perm("users.delete"))):
    ok = await db.unblock_user(uid)
    if not ok: raise HTTPException(404,"این آیدی در بلک‌لیست نبود")
    await _audit(admin, "رفع مسدودیت کاربر", "Users", severity="HIGH",
        target_id=uid, target_type="user", tags=["آنبلاک_کاربر","پنل_وب"])
    return {"ok":True}

@router.get("/blacklist")
async def blacklist(admin=Depends(require_perm("users.view"))):
    items = await db.get_blacklist()
    return {"blacklist":[{"id":b.get("_id"),"name":b.get("name",""),
        "blocked_by_name":b.get("blocked_by_name",""),"blocked_at":b.get("blocked_at") or None} for b in items]}

# ══════════════════════════════════════════════
# 🎓 ادمین‌های محتوا
# ══════════════════════════════════════════════

@router.get("/content-admins")
async def content_admins_list(admin=Depends(require_perm("roles.manage"))):
    admins = await db.get_content_admins()
    return {"admins":[{"id":a.get("user_id"),"name":a.get("name","")} for a in admins]}

@router.post("/content-admins/{uid}")
async def grant_content_admin(uid: int, admin=Depends(require_perm("roles.manage"))):
    user = await db.get_user(uid)
    if not user: raise HTTPException(404)
    await db.update_user(uid,{"role":"content_admin"})
    await _notify(uid, "🎓 <b>دسترسی ادمین محتوا به شما داده شد!</b>", "content_admin_granted")
    await _audit(admin, "اعطای دسترسی ادمین ارشد محتوا", "Roles", severity="HIGH",
        target_id=uid, target_type="user", target_label=user.get("name",""),
        tags=["اعطای_نقش","پنل_وب"])
    return {"ok":True}

@router.delete("/content-admins/{uid}")
async def revoke_content_admin(uid: int, admin=Depends(require_perm("roles.manage"))):
    await db.update_user(uid,{"role":"student"})
    await _notify(uid, "⚠️ دسترسی ادمین محتوای شما لغو شد.", "content_admin_revoked")
    await _audit(admin, "لغو دسترسی ادمین ارشد محتوا", "Roles", severity="HIGH",
        target_id=uid, target_type="user",
        tags=["لغو_نقش","پنل_وب"])
    return {"ok":True}

@router.get("/students")
async def students_list(admin=Depends(require_perm("users.view")), q: Optional[str]=Query(None)):
    users = await db.all_users(approved_only=True)
    students = [u for u in users if u.get("role","student")=="student"]
    if q:
        ql=q.lower()
        students=[u for u in students if ql in u.get("name","").lower() or ql in u.get("student_id","").lower()]
    return {"students":[{"id":u.get("user_id"),"name":u.get("name",""),"group":u.get("group","")} for u in students[:50]]}

# ══════════════════════════════════════════════
# ✏️ ویرایش کاربر
# ══════════════════════════════════════════════

class UserPatch(BaseModel):
    name: Optional[str]=None; group: Optional[str]=None
    intake: Optional[str]=None; student_id: Optional[str]=None
    role: Optional[str]=None
    nickname: Optional[str]=None   # 🏷 Identity v1

@router.patch("/users/{uid}")
async def edit_user(uid: int, body: UserPatch, admin=Depends(require_perm("users.manage"))):
    updates={}
    if body.name       is not None: updates["name"]=body.name.strip()
    if body.group      is not None: updates["group"]=db.normalize_group(body.group)
    if body.intake     is not None: updates["intake"]=body.intake
    if body.student_id is not None: updates["student_id"]=body.student_id.strip()
    if body.role       is not None:
        if body.role not in ("student","content_admin","support"): raise HTTPException(422,"نقش نامعتبر")
        updates["role"]=body.role
    # 🏷 Identity v1 — لقب از مسیر IdentityService (اعتبارسنجی
    # کامل + bypass Cooldown برای ادمین + Audit خودکار در db)
    if body.nickname is not None:
        actor_id = admin["id"] if isinstance(admin, dict) else 0
        ok, err, _info = await db.set_nickname(
            uid, body.nickname,
            changed_by=f"admin:{actor_id}",
            reason="پنل مدیریت",
        )
        if not ok:
            raise HTTPException(422, f"لقب نامعتبر: {err}")
    if updates:
        await db.update_user(uid,updates)
        await _audit(admin, "ویرایش اطلاعات کاربر", "Users", severity="WARNING",
            target_id=uid, target_type="user",
            details=" / ".join(f"{k}: {v}" for k, v in updates.items())[:400],
            tags=["ویرایش_کاربر","پنل_وب"])
    return {"ok":True}

# ══════════════════════════════════════════════
# 📅 ورودی‌ها (Intakes)
# ══════════════════════════════════════════════

@router.get("/intakes")
async def intakes_list(admin=Depends(require_perm("settings.manage"))):
    items = await db.get_all_intakes()
    result=[]
    for i in items:
        st = await db.intake_stats(i.get("code",""))
        result.append({"code":i.get("code",""),"label":i.get("label",""),
            "active":i.get("active",True),"total":st.get("total",0),"groups":st.get("groups",{})})
    return {"intakes":result}

class IntakeCreate(BaseModel):
    code: str; label: str

@router.post("/intakes")
async def add_intake_ep(body: IntakeCreate, admin=Depends(require_perm("settings.manage"))):
    code=body.code.strip(); label=body.label.strip()
    if not code or not label: raise HTTPException(422,"کد و برچسب الزامی است")
    await db.add_intake(code, label)
    await _audit(admin, "افزودن ورودی جدید", "Users", severity="INFO",
        target_id=code, target_type="intake", target_label=label,
        tags=["ورودی","پنل_وب"])
    return {"ok":True}

@router.post("/intakes/{code}/toggle")
async def toggle_intake_ep(code: str, admin=Depends(require_perm("settings.manage"))):
    new_state = await db.toggle_intake(code)
    await _audit(admin,
        "فعال‌سازی پذیرش ورودی" if new_state else "توقف پذیرش ورودی",
        "Users", severity="WARNING",
        target_id=code, target_type="intake",
        tags=["ورودی","پنل_وب"])
    return {"ok":True,"active":new_state}

@router.delete("/intakes/{code}")
async def delete_intake_ep(code: str, admin=Depends(require_perm("settings.manage"))):
    await db.delete_intake(code)
    await _audit(admin, "حذف ورودی", "Users", severity="HIGH",
        target_id=code, target_type="intake", tags=["ورودی","پنل_وب"])
    return {"ok":True}

# ══════════════════════════════════════════════
# 🎫 تیکت‌ها
# ══════════════════════════════════════════════

@router.get("/tickets")
async def all_tickets(
    admin=Depends(require_perm("tickets.manage")), status: Optional[str] = Query(None),
    q: Optional[str] = Query(None), intake: Optional[str] = Query(None),
    priority: Optional[str] = Query(None), assignee_id: Optional[int] = Query(None),
    unanswered: Optional[bool] = Query(None), date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    sort_by: str = Query("created_at"), sort_dir: str = Query("desc"),
    page: int = Query(1, ge=1), limit: int = Query(30, ge=1, le=100),
    after: Optional[str] = Query(None, max_length=32, description="cursor _id for keyset pagination"),
):
    """تک‌منبع query صف پشتیبانی برای owner route و Web wrapper."""
    # سازگاری direct-call تست‌ها/مصرف‌های قدیمی
    q = q if isinstance(q, str) else None
    intake = intake if isinstance(intake, str) else None
    priority = priority if isinstance(priority, str) else None
    assignee_id = assignee_id if isinstance(assignee_id, int) else None
    unanswered = unanswered if isinstance(unanswered, bool) else None
    date_from = date_from if isinstance(date_from, str) else None
    date_to = date_to if isinstance(date_to, str) else None
    sort_by = sort_by if isinstance(sort_by, str) and sort_by in ("created_at", "last_reply_at") else "created_at"
    sort_dir = sort_dir if isinstance(sort_dir, str) and sort_dir in ("asc", "desc") else "desc"
    page = page if isinstance(page, int) else 1
    limit = limit if isinstance(limit, int) else 30
    filt = {}
    # 🌊 W9 — «باز» = غیربسته؛ وضعیت‌های جدید فیلتر exact دارند
    if status == "closed":
        filt["status"] = "closed"
    elif status == "answered":
        filt.update({"status": {"$ne": "closed"}, "replies.0": {"$exists": True}})
    elif status == "open":
        filt["status"] = {"$ne": "closed"}
    elif status in ("in_progress", "waiting_user", "resolved"):
        filt["status"] = status
    if q and q.strip():
        import re
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        filt["$or"] = [{"subject": rx}, {"user_name": rx}, {"message": rx}]
        if q.strip().isdigit():
            filt["$or"].append({"ticket_id": int(q.strip())})
    if intake:
        ids = await db.users.distinct("user_id", {"intake": intake})
        filt["user_id"] = {"$in": ids}
    if priority == "normal":
        # legacy ticketها قبل از افزودن priority فاقد فیلدند و معنای domain آن‌ها «عادی» است.
        filt.setdefault("$and", []).append({"$or": [
            {"priority": "normal"}, {"priority": {"$exists": False}}, {"priority": None}]})
    elif priority:
        filt["priority"] = priority
    if assignee_id is not None:
        filt["assignee_id"] = assignee_id
    if unanswered is True:
        filt["replies.0"] = {"$exists": False}
        filt["status"] = {"$ne": "closed"}
    if date_from or date_to:
        created = {}
        try:
            if date_from:
                created["$gte"] = day_bounds_utc(parse_gregorian_date(date_from))[0].isoformat()
            if date_to:
                created["$lt"] = day_bounds_utc(parse_gregorian_date(date_to))[1].isoformat()
        except ValueError:
            raise HTTPException(422, "بازه تاریخ تیکت معتبر نیست")
        filt["created_at"] = created
    # 🌊 W4 — cursor pagination (keyset) — if after provided, use _id > after
    if after:
        try:
            from bson import ObjectId as _OID
            if _OID.is_valid(after):
                filt["_id"] = {"$gt": _OID(after)}
                # when cursor used, ignore page offset
                tickets = await (db.tickets.find(filt).sort("_id", 1).limit(limit + 1).to_list(limit + 1))
                has_more = len(tickets) > limit
                if has_more:
                    tickets = tickets[:limit]
                next_cursor = str(tickets[-1]["_id"]) if tickets and has_more else None
                return {"tickets": [{
                    "id": t.get("ticket_id"), "user_id": t.get("user_id"),
                    "user_name": t.get("user_name", ""), "subject": t.get("subject", ""),
                    "status": db.ticket_norm_status(t.get("status")), "reply_count": len(t.get("replies", [])),
                    "created_at": t.get("created_at") or None,
                    "last_reply_at": t.get("last_reply_at") or None,
                    "priority": t.get("priority", "normal"), "tags": t.get("tags") or [],
                    "assignee_id": t.get("assignee_id"), "assignee_name": t.get("assignee_name", ""),
                    "sla": db.ticket_sla_info(t),
                } for t in tickets], "total": None, "page": None, "limit": limit, "next_cursor": next_cursor, "has_more": has_more}
        except Exception:
            pass
    total = await db.tickets.count_documents(filt)
    tickets = await (db.tickets.find(filt).sort(sort_by, 1 if sort_dir == "asc" else -1)
                     .skip((page - 1) * limit).limit(limit).to_list(limit))
    return {"tickets": [{
        "id": t.get("ticket_id"), "user_id": t.get("user_id"),
        "user_name": t.get("user_name", ""), "subject": t.get("subject", ""),
        "status": db.ticket_norm_status(t.get("status")), "reply_count": len(t.get("replies", [])),
        "created_at": t.get("created_at") or None,
        "last_reply_at": t.get("last_reply_at") or None,
        "priority": t.get("priority", "normal"), "tags": t.get("tags") or [],
        "assignee_id": t.get("assignee_id"), "assignee_name": t.get("assignee_name", ""),
        "sla": db.ticket_sla_info(t),
    } for t in tickets], "total": total, "page": page, "limit": limit,
        "pages": (total + limit - 1) // limit, "next_cursor": None, "has_more": False}

@router.get("/tickets/{tid}")
async def ticket_detail(tid: int, admin=Depends(require_perm("tickets.manage"))):
    t = await db.ticket_get(tid)
    if not t: raise HTTPException(404)
    uid=t.get("user_id"); u=await db.get_user(uid) if uid else None
    replies=[{"text":r.get("text","").removeprefix("[دانشجو]").strip(),
        "sender":"user" if r.get("text","").startswith("[دانشجو]") else "support","at": r.get("at") or None} for r in t.get("replies",[])]
    return {"ticket":{"id":t.get("ticket_id"),"subject":t.get("subject",""),"message":t.get("message",""),
        "status":t.get("status","open"),"created_at": t.get("created_at") or None,"replies":replies,
        "priority":t.get("priority","normal"),"assignee_id":t.get("assignee_id"),
        "assignee_name":t.get("assignee_name",""),"sla":db.ticket_sla_info(t),
        "assignee_active": await db.ticket_assignee_ok(t.get("assignee_id")) if t.get("assignee_id") else None,
        "user":{"id":uid,"name":t.get("user_name",""),"student_id":u.get("student_id","") if u else "","group":u.get("group","") if u else "","intake":u.get("intake","") if u else ""}}}

class AdminReply(BaseModel):
    message: str

@router.post("/tickets/{tid}/reply")
async def admin_reply(tid: int, body: AdminReply, admin=Depends(require_perm("tickets.reply"))):
    t=await db.ticket_get(tid)
    if not t: raise HTTPException(404)
    if t.get("status")=="closed": raise HTTPException(400)
    msg=body.message.strip()
    if not msg: raise HTTPException(422)
    await db.ticket_add_reply(tid, msg)
    await _notify(t["user_id"], f"💬 <b>پاسخ پشتیبانی #{tid}</b>\n{msg}", "ticket_admin_reply")
    await _audit(admin, "پاسخ به تیکت پشتیبانی", "Tickets", severity="INFO",
        target_id=tid, target_type="ticket", target_label=t.get("subject",""),
        tags=["تیکت","پنل_وب"])
    return {"ok":True}

@router.post("/tickets/{tid}/close")
async def close_ticket(tid: int, admin=Depends(require_perm("tickets.manage"))):
    t = await db.ticket_get(tid)
    if not t:
        raise HTTPException(404, "تیکت پیدا نشد")
    res = await db.ticket_close(tid)
    await _audit(admin, "بستن تیکت", "Tickets", severity="INFO",
        target_id=tid, target_type="ticket",
        before={"status": res.get("frm")}, after={"status": res.get("to")},
        tags=["تیکت","پنل_وب"])
    return {"ok":True}

@router.post("/tickets/{tid}/reopen")
async def reopen_ticket(tid: int, admin=Depends(require_perm("tickets.manage"))):
    t = await db.ticket_get(tid)
    if not t:
        raise HTTPException(404, "تیکت پیدا نشد")
    res = await db.ticket_reopen(tid)
    await _audit(admin, "بازگشایی تیکت", "Tickets", severity="INFO",
        target_id=tid, target_type="ticket",
        before={"status": res.get("frm")}, after={"status": res.get("to")},
        tags=["تیکت","پنل_وب"])
    return {"ok":True}


class CannedBody(BaseModel):
    title: str
    text: str
    active: bool = True
    category: str = ""  # 🌊 W9 — دسته‌بندی پاسخ آماده


@router.get("/tickets/canned")
async def canned_list_ep(category: str = "",
                         admin=Depends(require_perm("tickets.manage"))):
    """🌊 W8/UX-04 — پاسخ‌های آماده. 🌊 W9 — فیلتر دسته."""
    items = await db.canned_list(category=category)
    return {"items": [{**c, "id": str(c.pop("_id", ""))} for c in items]}


@router.post("/tickets/canned")
async def canned_add_ep(body: CannedBody, admin=Depends(require_perm("tickets.manage"))):
    if not body.title.strip() or not body.text.strip():
        raise HTTPException(422, "عنوان و متن لازم است")
    cid = await db.canned_add(body.title, body.text, admin["id"],
                                category=body.category)
    await _audit(admin, "افزودن پاسخ آماده", "Tickets", severity="INFO",
        target_id=cid, target_type="canned", target_label=body.title[:60],
        tags=["تیکت","پنل_وب"])
    return {"ok": True, "id": cid}


@router.put("/tickets/canned/{cid}")
async def canned_update_ep(cid: str, body: CannedBody, admin=Depends(require_perm("tickets.manage"))):
    ok = await db.canned_update(cid, {"title": body.title, "text": body.text,
                                      "active": body.active,
                                      "category": body.category})
    if not ok:
        raise HTTPException(404, "پاسخ آماده پیدا نشد")
    await _audit(admin, "ویرایش پاسخ آماده", "Tickets", severity="INFO",
        target_id=cid, target_type="canned", target_label=body.title[:60],
        tags=["تیکت","پنل_وب"])
    return {"ok": True}


@router.delete("/tickets/canned/{cid}")
async def canned_delete_ep(cid: str, admin=Depends(require_perm("tickets.manage"))):
    if not await db.canned_delete(cid):
        raise HTTPException(404, "پاسخ آماده پیدا نشد")
    await _audit(admin, "حذف پاسخ آماده", "Tickets", severity="WARNING",
        target_id=cid, target_type="canned", tags=["تیکت","پنل_وب"])
    return {"ok": True}

# ══════════════════════════════════════════════
# 📢 Broadcast پیشرفته — preview / تأیید / زمان‌دار / هدفمند
# ══════════════════════════════════════════════

class BroadcastTarget(BaseModel):
    scope: str = "all"  # all|intake|group|intake_group|role|subscription|saved_segment
    intake: Optional[str] = None
    group: Optional[str] = None
    role: Optional[str] = None
    subscription_status: Optional[str] = None
    saved_segment_id: Optional[str] = None


async def _resolve_broadcast_users(target: BroadcastTarget, actor_id: int = ADMIN_ID):
    """Compatibility wrapper روی resolver واحد domain."""
    try:
        return await broadcast_service.resolve_recipients(target.model_dump(), actor_id, db)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

class BroadcastPreview(BaseModel):
    target: BroadcastTarget

@router.post("/broadcast/preview")
async def broadcast_preview(body: BroadcastPreview, admin=Depends(require_perm("broadcast.send"))):
    users = await _resolve_broadcast_users(body.target, admin["id"])
    return {"recipient_count": len(users), "audience": body.target.model_dump()}


class BroadcastSend(BaseModel):
    text: str = ""                       # legacy text client
    message_type: str = "text"
    file_id: str = ""
    caption: str = ""
    target: BroadcastTarget
    send_at: Optional[str] = None

    def payload(self) -> dict:
        return ({"type": "text", "text": self.text}
                if self.message_type == "text" else
                {"type": self.message_type, "file_id": self.file_id, "caption": self.caption})


@router.post("/broadcast")
async def broadcast(body: BroadcastSend, admin=Depends(require_perm("broadcast.send"))):
    await rate_limit_user(admin["id"], "broadcast_send", 5, 60)  # 🛡 W10
    try:
        result = await broadcast_service.create_campaign(
            payload=body.payload(), target=body.target.model_dump(),
            created_by=admin["id"], created_by_name=(admin.get("_db") or {}).get("name", ""),
            source="web", send_at=body.send_at, correlation_id=current_request_id.get(), enqueue=True)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    try:
        await _audit(admin, "ایجاد کمپین همگانی" + (" زمان‌دار" if body.send_at else ""),
            "Notifications", severity="HIGH", target_id=result["campaign_id"],
            target_type="broadcast_campaign", target_label=f"{result['recipient_count']} گیرنده",
            details=(body.text or body.caption)[:300],
            tags=["ارسال_همگانی", "campaign", "پنل_وب"])
    except Exception:
        try: await broadcast_service.cancel(result["campaign_id"])
        except Exception: pass
        raise HTTPException(503, "ثبت حسابرسی ناموفق بود؛ کمپین لغو شد")
    return {"ok": True, "queued": result["recipient_count"],
            "scheduled": bool(body.send_at), **result}

@router.get("/broadcast/history")
async def broadcast_history(admin=Depends(require_perm("broadcast.send")), limit: int=Query(20, ge=1, le=100)):
    docs = await db.broadcast_campaigns.find({}).sort("created_at", -1).limit(limit).to_list(limit)
    return {"history": [broadcast_service.campaign_row(doc) for doc in docs]}

# ── 🌊 موج Notif-Scheduled — مدیریت ارسال‌های همگانی زمان‌دارِ در انتظار ──
# پاریت با ربات: تا لحظه‌ی send_at پیام‌ها sent=False می‌مانند؛ لغو = حذف همان
# دسته (کلید یکتای دسته = text + created_at). همه‌ی مسیرها سطح مالک می‌مانند.

@router.get("/broadcast/scheduled")
async def broadcast_scheduled(admin=Depends(require_perm("broadcast.send")), limit: int=Query(10, ge=1, le=50)):
    docs = await db.broadcast_campaigns.find(
        {"status": "scheduled", "send_at": {"$gt": utc_now_iso()}}
    ).sort("send_at", 1).limit(limit).to_list(limit)
    return {"scheduled": [broadcast_service.campaign_row(doc) for doc in docs]}


class BroadcastCancel(BaseModel):
    campaign_id: str = ""
    # legacy fields فقط برای compatibility ورودی قدیمی؛ control plane جدید ID است.
    text: str = ""
    created_at: str = ""


@router.post("/broadcast/cancel")
async def broadcast_cancel(body: BroadcastCancel, admin=Depends(require_perm("broadcast.send"))):
    if not body.campaign_id:
        raise HTTPException(422, "شناسه کمپین الزامی است")
    try:
        cancelled = await broadcast_service.cancel(body.campaign_id)
    except ValueError:
        raise HTTPException(409, "کمپین پیدا نشد یا دیگر قابل لغو نیست")
    n = cancelled["cancelled"]
    try:
        await _audit(admin, "لغو کمپین همگانی", "Notifications", severity="HIGH",
            target_id=body.campaign_id, target_type="broadcast_campaign",
            target_label=f"{n} گیرنده", tags=["ارسال_همگانی", "لغو", "پنل_وب"])
    except Exception:
        await broadcast_service.rollback_cancel(body.campaign_id,
                                                cancelled["previous_status"])
        raise HTTPException(503, "ثبت حسابرسی ناموفق بود؛ لغو کمپین بازگردانده شد")
    return {"ok": True, "cancelled": n, "campaign_id": body.campaign_id}

# ══════════════════════════════════════════════
# 📊 نظرسنجی کانال
# ══════════════════════════════════════════════

@router.get("/poll/status")
async def poll_status(admin=Depends(require_perm("settings.manage"))):
    channel_id = await db.get_setting("poll_channel_id", None)
    return {"channel_id": channel_id, "configured": bool(channel_id)}

class PollChannelSet(BaseModel):
    channel_id: str

@router.post("/poll/channel")
async def poll_channel_set(body: PollChannelSet, admin=Depends(require_perm("settings.manage"))):
    old = await db.get_setting("poll_channel_id", None)
    await db.set_setting("poll_channel_id", body.channel_id.strip())
    await _audit(admin, "تغییر کانال نظرسنجی", "Notifications", severity="WARNING", target_type="setting", target_label="poll_channel_id", before={"poll_channel_id": old}, after={"poll_channel_id": body.channel_id.strip()}, tags=["نظرسنجی", "تنظیمات"])
    return {"ok":True}

class PollCreate(BaseModel):
    question: str; options: List[str]; anonymous: bool = False

@router.post("/poll")
async def poll_create(body: PollCreate, admin=Depends(require_perm("settings.manage"))):
    if len(body.options) < 2: raise HTTPException(422, "حداقل ۲ گزینه لازم است")
    channel_id = await db.get_setting("poll_channel_id", None)
    if not channel_id: raise HTTPException(400, "کانال نظرسنجی تنظیم نشده — اول از بخش تنظیمات کانال رو وارد کن")
    from api.telegram_send import BOT_TOKEN, API_BASE
    import httpx
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(f"{API_BASE}/sendPoll", json={
            "chat_id": channel_id, "question": body.question, "options": body.options,
            "is_anonymous": body.anonymous, "allows_multiple_answers": False,
        })
    data = resp.json()
    if not data.get("ok"):
        raise HTTPException(502, f"ارسال ناموفق — مطمئن شو ربات ادمین کانال هست ({data.get('description','')})")
    await _audit(admin, "ایجاد نظرسنجی در کانال", "Notifications", severity="INFO",
        target_type="poll", target_label=body.question[:100],
        tags=["نظرسنجی","پنل_وب"])
    return {"ok":True}

# ══════════════════════════════════════════════
# 🔒 قفل اجباری عضویت کانال — 🌊 موج ChannelLock
# (معادل admin:channel_lock ربات؛ متدهای db موجود بودند
# ولی API وب نداشتند — فقط افزودنی، سطح مالک)
# ══════════════════════════════════════════════

@router.get("/channel-lock")
async def channel_lock_list(admin=Depends(require_perm("settings.manage"))):
    channels = await db.get_required_channels()
    return {"channels": [
        {"id": c.get("id", ""), "title": c.get("title", ""),
         "invite_link": c.get("invite_link", "")} for c in channels]}

class ChannelLockAdd(BaseModel):
    id: str
    title: str
    invite_link: str = ""

@router.post("/channel-lock")
async def channel_lock_add(body: ChannelLockAdd, admin=Depends(require_perm("settings.manage"))):
    cid = body.id.strip(); title = body.title.strip()
    if not cid or not title:
        raise HTTPException(422, "آیدی و نام کانال الزامی است")
    ok = await db.add_required_channel(cid, title, body.invite_link.strip())
    if not ok:
        raise HTTPException(409, "این کانال قبلاً اضافه شده است")
    await _audit(admin, "افزودن کانال اجباری", "Settings", severity="WARNING",
        target_id=cid, target_type="channel", target_label=title,
        tags=["قفل_کانال", "پنل_وب"])
    return {"ok": True}

@router.delete("/channel-lock/{channel_id}")
async def channel_lock_remove(channel_id: str, admin=Depends(require_perm("settings.manage"))):
    current = await db.get_required_channels()
    if not any(c.get("id") == channel_id for c in current):
        raise HTTPException(404, "کانال در لیست نیست")
    await db.remove_required_channel(channel_id)
    await _audit(admin, "حذف کانال اجباری", "Settings", severity="WARNING",
        target_id=channel_id, target_type="channel",
        tags=["قفل_کانال", "پنل_وب"])
    return {"ok": True}

# ══════════════════════════════════════════════
# 🔔 مدیریت اعلان‌ها — فاصله زمانی / تاریخچه / retry
# ══════════════════════════════════════════════

@router.get("/notifications/settings")
async def notif_settings(admin=Depends(require_perm("notifications.manage"))):
    interval = await db.get_setting("resource_notif_interval_hours", 24)
    last_sent = await db.get_setting("resource_notif_last_sent", None)
    last_error = await db.get_setting("resource_notif_last_error", None)
    return {"interval_hours": interval, "last_sent": last_sent, "last_error": last_error}

class NotifSettingsUpdate(BaseModel):
    interval_hours: int

@router.post("/notifications/settings")
async def notif_settings_update(body: NotifSettingsUpdate, admin=Depends(require_perm("notifications.manage"))):
    if body.interval_hours not in (24, 48, 72): raise HTTPException(422, "مقدار مجاز: ۲۴، ۴۸ یا ۷۲")
    old = await db.get_setting("resource_notif_interval_hours", 24)
    await db.set_setting("resource_notif_interval_hours", body.interval_hours)
    await _audit(admin, "تغییر فاصله اعلان منابع", "Settings", severity="WARNING",
        target_type="settings",
        before={"فاصله(ساعت)": old}, after={"فاصله(ساعت)": body.interval_hours},
        tags=["تنظیمات_اعلان","پنل_وب"])
    return {"ok":True}

@router.get("/notifications/history")
async def notif_history(admin=Depends(require_perm("notifications.manage")), job_name: Optional[str]=Query(None), limit: int=Query(15)):
    runs = await db.get_recent_notif_runs(job_name=job_name, limit=limit)
    return {"runs":[{"id":str(r["_id"]),"job_name":r.get("job_name",""),"status":r.get("status",""),
        "sent":r.get("sent",0),"failed":r.get("failed",0),"total":r.get("total",0),
        "started_at":r.get("started_at",""),"finished_at":r.get("finished_at")} for r in runs]}

@router.post("/notifications/history/{run_id}/retry")
async def notif_retry(run_id: str, admin=Depends(require_perm("notifications.manage"))):
    targets = await db.get_failed_notif_details(run_id)
    if not targets: raise HTTPException(404, "موردی برای تلاش مجدد پیدا نشد")
    notif = db.client["medicalbot"]["bot_notifications"]
    docs = [{"type":"notif_retry","chat_id":t["user_id"],"text":t["message"],"sent":False,
        "created_at":utc_now_iso()} for t in targets if t.get("message")]
    if docs: await notif.insert_many(docs)
    return {"ok":True, "requeued": len(docs)}

@router.post("/export/excel")
async def export_excel(admin=Depends(require_perm("users.manage"))):
    await rate_limit_user(admin["id"], "export_excel", 10, 60)  # 🛡 W10
    await _notify(ADMIN_ID, "__EXCEL_EXPORT__", "excel_export_request")
    return {"ok":True,"message":"📊 فایل اکسل از طریق ربات ارسال می‌شود."}


# ── بخش‌های بکاپ — دقیقاً همان‌هایی که منوی backup.py در ربات دارد ──
BACKUP_SECTION_LABELS_FA = {
    "all":          "کامل — همه بخش‌ها",
    "users":        "کاربران",
    "content":      "علوم پایه",
    "refs":         "رفرنس‌ها",
    "qbank":        "بانک سوال",
    "subscription": "اشتراک و پرداخت",
    "grades":       "نمرات",
    "access":       "دسترسی‌ها و تنظیمات",
}

class BackupRequestBody(BaseModel):
    section: str = "all"

@router.post("/backup")
async def request_backup(body: BackupRequestBody, admin=Depends(require_perm("backup.manage"))):
    """درخواست فایل پشتیبان JSON از پنل وب — با همان الگوی خروجی اکسل:
    سیگنال __BACKUP_REQUEST__ در صف bot_notifications می‌نشیند و
    mini_app_outbox_job در ربات فایل را می‌سازد و به چت ادمین می‌فرستد
    (همان build_full_backup_data / build_section_backup_data مشترک ربات)."""
    if body.section not in BACKUP_SECTION_LABELS_FA:
        raise HTTPException(422, "بخش بکاپ نامعتبر است")
    signal = ("__BACKUP_REQUEST__" if body.section == "all"
              else f"__BACKUP_REQUEST__:{body.section}")
    await _notify(admin.get("id", ADMIN_ID), signal, f"backup_request_{body.section}")
    await _audit(admin, "درخواست فایل پشتیبان از پنل وب", "Backup", severity="HIGH",
        details=f"بخش: {BACKUP_SECTION_LABELS_FA[body.section]}",
        tags=["بکاپ", "پنل_وب"])
    return {"ok": True,
            "message": "💾 فایل پشتیبان از طریق ربات ارسال می‌شود (بسته به حجم دیتابیس ممکن است چند ثانیه طول بکشد)."}

# ══════════════════════════════════════════════
# ⚙️ تنظیمات ربات — همان کلیدهایی که پنل ربات
# استفاده می‌کند تا هر دو کانال سینک بمانند
# ══════════════════════════════════════════════

@router.get("/settings")
async def bot_settings_get(admin=Depends(require_perm("settings.manage"))):
    """خواندن تنظیمات مشترک ربات/مینی‌اپ."""
    return {
        "maintenance_mode": bool(await db.get_setting("maintenance_mode", False)),
        "maintenance_text": (await db.get_setting("maintenance_text", "")) or "",
        "require_student_id": bool(await db.get_setting("require_student_id", False)),
        # گروه‌های لاگ تلگرام — همان کلیدهای پنل ربات تا وضعیتش از وب هم
        # قابل مشاهده/تغییر باشد (None یعنی تنظیم نشده)
        "log_group_admin": await db.get_setting("log_group_admin", None),
        "log_group_content": await db.get_setting("log_group_content", None),
        # 💙 حمایت مالی — همان کلیدهای پنل ربات (admin:donation_manage)
        "donation_enabled": bool(await db.get_setting("donation_enabled", False)),
        "donation_link": await db.get_setting("donation_link", None),
        # 💾 بکاپ خودکار — همان کلیدهای backup.py (backup:auto_settings)
        "auto_backup_enabled": bool(await db.get_setting("auto_backup_enabled", False)),
        "auto_backup_hour": int(await db.get_setting("auto_backup_hour", 3) or 0),
        "auto_backup_last_run": await db.get_setting("auto_backup_last_run", None),
    }

class BotSettingsPatch(BaseModel):
    maintenance_mode: Optional[bool] = None
    maintenance_text: Optional[str] = None
    require_student_id: Optional[bool] = None
    # None صریح در بدنه = حذف تنظیم گروه (با model_fields_set تشخیص داده می‌شود)
    log_group_admin: Optional[int] = None
    log_group_content: Optional[int] = None
    donation_enabled: Optional[bool] = None
    # '' یا None = حذف لینک
    donation_link: Optional[str] = None
    auto_backup_enabled: Optional[bool] = None
    # ساعت اجرا به‌وقت تهران ۰ تا ۲۳
    auto_backup_hour: Optional[int] = None

@router.patch("/settings")
async def bot_settings_patch(body: BotSettingsPatch, admin=Depends(require_perm("settings.manage"))):
    """تغییر تنظیمات — دقیقاً با همان سطح حساسیت لاگ پنل ربات:
    حالت تعمیر → CRITICAL، الزام شماره دانشجویی → HIGH."""
    changed = []

    if body.maintenance_mode is not None:
        old = bool(await db.get_setting("maintenance_mode", False))
        if old != body.maintenance_mode:
            await db.set_setting("maintenance_mode", body.maintenance_mode)
            await _audit(admin,
                "فعال‌شدن حالت تعمیر" if body.maintenance_mode else "غیرفعال‌شدن حالت تعمیر",
                "Settings", severity="CRITICAL",
                before={"وضعیت": "غیرفعال" if body.maintenance_mode else "فعال"},
                after={"وضعیت": "فعال" if body.maintenance_mode else "غیرفعال"},
                tags=["حالت_تعمیر", "پنل_وب"])
            changed.append("maintenance_mode")

    if body.maintenance_text is not None:
        text = body.maintenance_text.strip()
        if len(text) > 400:
            raise HTTPException(422, "متن حالت تعمیر نباید بیشتر از ۴۰۰ کاراکتر باشد")
        old = (await db.get_setting("maintenance_text", "")) or ""
        if old != text:
            await db.set_setting("maintenance_text", text)
            await _audit(admin, "تغییر متن حالت تعمیر", "Settings", severity="HIGH",
                before={"متن": old or "(پیش‌فرض)"},
                after={"متن": text or "(پیش‌فرض)"},
                tags=["حالت_تعمیر", "پنل_وب"])
            changed.append("maintenance_text")

    if body.require_student_id is not None:
        old = bool(await db.get_setting("require_student_id", False))
        if old != body.require_student_id:
            await db.set_setting("require_student_id", body.require_student_id)
            await _audit(admin,
                "اجباری‌شدن شماره دانشجویی" if body.require_student_id else "اختیاری‌شدن شماره دانشجویی",
                "Settings", severity="HIGH",
                before={"شماره دانشجویی": "اختیاری" if body.require_student_id else "اجباری"},
                after={"شماره دانشجویی": "اجباری" if body.require_student_id else "اختیاری"},
                tags=["تنظیمات_ثبت_نام", "پنل_وب"])
            changed.append("require_student_id")

    # ── گروه‌های لاگ تلگرام — None صریح یعنی حذف تنظیم ──
    for field, key, label in (
        ("log_group_admin",   "log_group_admin",   "گروه لاگ مدیریت"),
        ("log_group_content", "log_group_content", "گروه لاگ محتوا"),
    ):
        if field in body.model_fields_set:
            val = getattr(body, field)
            if val is not None and val >= 0:
                raise HTTPException(422,
                    "آیدی گروه باید عدد منفی باشد (مثل -1001234567890) — عدد مثبت آیدی کاربر است")
            old = await db.get_setting(key, None)
            if old != val:
                await db.set_setting(key, val)
                await _audit(admin,
                    f"تنظیم {label}" if val is not None else f"حذف {label}",
                    "Settings", severity="HIGH",
                    before={"گروه": str(old) if old else "تنظیم نشده"},
                    after={"گروه": str(val) if val is not None else "حذف شد"},
                    tags=["گروه_لاگ", "پنل_وب"])
                changed.append(key)

    # ── 💙 حمایت مالی — برچسب‌های لاگ دقیقاً مثل پنل ربات ──
    if body.donation_enabled is not None:
        old = bool(await db.get_setting("donation_enabled", False))
        if old != body.donation_enabled:
            await db.set_setting("donation_enabled", body.donation_enabled)
            await _audit(admin,
                "فعال‌شدن بخش حمایت مالی" if body.donation_enabled else "غیرفعال‌شدن بخش حمایت مالی",
                "Settings", severity="HIGH",
                before={"وضعیت": "غیرفعال" if body.donation_enabled else "فعال"},
                after={"وضعیت": "فعال" if body.donation_enabled else "غیرفعال"},
                tags=["حمایت_مالی", "پنل_وب"])
            changed.append("donation_enabled")

    if body.donation_link is not None or "donation_link" in body.model_fields_set:
        link = (body.donation_link or "").strip()
        if link and not (link.startswith("http://") or link.startswith("https://")):
            raise HTTPException(422, "لینک باید با http:// یا https:// شروع شود")
        if len(link) > 300:
            raise HTTPException(422, "لینک نباید بیشتر از ۳۰۰ کاراکتر باشد")
        new_val = link or None
        old = await db.get_setting("donation_link", None)
        if old != new_val:
            await db.set_setting("donation_link", new_val)
            await _audit(admin,
                "تنظیم لینک حمایت مالی" if new_val else "حذف لینک حمایت مالی",
                "Settings", severity="HIGH",
                before={"لینک": old or "تنظیم نشده"},
                after={"لینک": new_val or "حذف شد"},
                tags=["حمایت_مالی", "پنل_وب"])
            changed.append("donation_link")

    # ── 💾 بکاپ خودکار — همان منطق backup:auto_settings در ربات ──
    if body.auto_backup_enabled is not None:
        old = bool(await db.get_setting("auto_backup_enabled", False))
        if old != body.auto_backup_enabled:
            await db.set_setting("auto_backup_enabled", body.auto_backup_enabled)
            await _audit(admin,
                "فعال‌سازی بکاپ خودکار روزانه" if body.auto_backup_enabled else "غیرفعال‌سازی بکاپ خودکار روزانه",
                "Backup", severity="HIGH",
                before={"بکاپ خودکار": "غیرفعال" if body.auto_backup_enabled else "فعال"},
                after={"بکاپ خودکار": "فعال" if body.auto_backup_enabled else "غیرفعال"},
                tags=["بکاپ", "پنل_وب"])
            changed.append("auto_backup_enabled")

    if body.auto_backup_hour is not None:
        if not (0 <= body.auto_backup_hour <= 23):
            raise HTTPException(422, "ساعت بکاپ خودکار باید بین ۰ تا ۲۳ باشد")
        old = int(await db.get_setting("auto_backup_hour", 3) or 0)
        if old != body.auto_backup_hour:
            await db.set_setting("auto_backup_hour", body.auto_backup_hour)
            await _audit(admin, "تغییر ساعت بکاپ خودکار", "Backup", severity="HIGH",
                before={"ساعت": f"{old}:00"},
                after={"ساعت": f"{body.auto_backup_hour}:00"},
                tags=["بکاپ", "پنل_وب"])
            changed.append("auto_backup_hour")

    return {"ok": True, "changed": changed}

class LogGroupTestBody(BaseModel):
    kind: str  # 'admin' | 'content'

@router.post("/settings/test-log-group")
async def test_log_group(body: LogGroupTestBody, admin=Depends(require_perm("settings.manage"))):
    """ارسال پیام تست به گروه لاگ از مسیر واقعی ربات (صف bot_notifications)
    تا سلامت کل زنجیره‌ی وب→دیتابیس→ربات→گروه با یک دکمه قابل بررسی باشد."""
    if body.kind not in ("admin", "content"):
        raise HTTPException(422, "kind باید admin یا content باشد")
    key   = "log_group_admin" if body.kind == "admin" else "log_group_content"
    label = "🛡 لاگ مدیریت" if body.kind == "admin" else "🎓 لاگ محتوا"
    chat_id = await db.get_setting(key, None)
    if not chat_id:
        raise HTTPException(404, "این گروه هنوز تنظیم نشده است")
    await _notify(int(chat_id),
        f"🧪 <b>پیام تست گروه {label}</b>\n\n"
        "این پیام از پنل وب مینی‌اپ ارسال شد — اگر آن را می‌خوانی، "
        "اتصال کامل وب ← ربات ← گروه لاگ سالم است. ✅",
        "log_group_test")
    await _audit(admin, f"ارسال پیام تست به گروه {label}", "Settings",
        severity="INFO", target_id=str(chat_id), target_type="group",
        tags=["گروه_لاگ", "پنل_وب"])
    return {"ok": True, "message": "پیام تست از طریق ربات ارسال می‌شود (ظرف چند ثانیه در گروه می‌رسد)."}


# ══════════════════════════════════════════════
# 🛠 Fix-Foundation — عملیات نهایی مالک (Parity-Final)
# endpointهای owner موجود آزاد نشده‌اند؛ این routeها صرفاً افزودنی‌اند.
# ══════════════════════════════════════════════

@router.post("/prestige/backfill")
async def prestige_backfill(admin=Depends(require_perm("prestige.manage"))):
    raw = await db.prestige_backfill()
    firsts = raw.get("firsts") or []
    report = {
        "scanned": int(raw.get("scanned") or 0),
        "migrated": int(raw.get("migrated") or 0),
        "founders": int(raw.get("founders") or 0),
        "firsts": len(firsts) if isinstance(firsts, list) else int(firsts or 0),
        "first_items": firsts[:10] if isinstance(firsts, list) else [],
        "errors": int(raw.get("errors") or 0),
        "fatal": raw.get("fatal") or "",
    }
    await _audit(admin, "اجرای Backfill Prestige", "Prestige",
                 severity="HIGH", after=report,
                 tags=["پرستیژ", "backfill", "پنل_وب"])
    return {"ok": not bool(report["fatal"]), "report": report}


@router.post("/notifications/force-send")
async def notifications_force_send(admin=Depends(require_perm("notifications.manage"))):
    """ثبت سیگنال؛ اجرای واقعی با bot instance در outbox job انجام می‌شود."""
    await _notify(admin["id"], "__FORCE_RES_NOTIF__", "force_resources_notification")
    await _audit(admin, "درخواست ارسال فوری اعلان منابع", "Notifications",
                 severity="HIGH", tags=["اعلان_منابع", "ارسال_فوری", "پنل_وب"])
    return {
        "ok": True,
        "message": "📨 درخواست ثبت شد؛ نتیجه‌ی اجرای واقعی در گفت‌وگوی ربات ارسال می‌شود.",
    }


@router.post("/log-groups/test")
async def log_groups_test(admin=Depends(require_perm("settings.manage"))):
    """تست واقعی هر دو گروه از مسیر Bot API، بدون افشای token به مرورگر."""
    import time
    import httpx
    from api.telegram_send import API_BASE, BOT_TOKEN

    specs = [
        ("admin", "log_group_admin", "🛡 لاگ مدیریت"),
        ("content", "log_group_content", "🎓 لاگ محتوا"),
    ]
    results = []
    for kind, key, label in specs:
        chat_id = await db.get_setting(key, None)
        if not chat_id:
            results.append({"key": kind, "label": label, "status": "unset", "ms": None, "error": ""})
            continue
        if not BOT_TOKEN:
            results.append({"key": kind, "label": label, "status": "error", "ms": None,
                            "error": "TELEGRAM_TOKEN تنظیم نشده است"})
            continue
        started = time.monotonic()
        status = "error"
        error = ""
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(f"{API_BASE}/sendMessage", json={
                    "chat_id": int(chat_id),
                    "text": (f"🧪 <b>تست اتصال {label}</b>\n\n"
                             "ارسال مستقیم از Web Admin با موفقیت انجام شد. ✅"),
                    "parse_mode": "HTML",
                })
            payload = resp.json() if resp.content else {}
            if resp.status_code == 200 and payload.get("ok"):
                status = "sent"
            else:
                error = str(payload.get("description") or f"HTTP {resp.status_code}")[:160]
        except Exception as e:
            error = str(e)[:160]
        results.append({
            "key": kind, "label": label, "status": status,
            "ms": int((time.monotonic() - started) * 1000), "error": error,
        })

    await _audit(admin, "تست اتصال گروه‌های لاگ", "Settings",
                 severity="INFO", after={r["key"]: r["status"] for r in results},
                 tags=["گروه_لاگ", "تست_اتصال", "پنل_وب"])
    return {"ok": all(r["status"] in ("sent", "unset") for r in results),
            "results": results}


# ══════════════════════════════════════════════
# 🛡 لاگ فعالیت مدیران (نمایش در پنل وب)
# ══════════════════════════════════════════════

def build_audit_query(
    category=None, min_severity=None, q=None, actor=None, actor_role=None,
    module=None, action=None, target_type=None, target=None,
    date_from=None, date_to=None, correlation_id=None,
):
    """Query builder مشترک list/export؛ یک semantics برای فیلترهای audit."""
    import re
    text = lambda value: value if isinstance(value, str) else None
    actor, actor_role, module, action = map(text, (actor, actor_role, module, action))
    target_type, target, date_from, date_to, correlation_id = map(
        text, (target_type, target, date_from, date_to, correlation_id))
    query = {}
    if category in ("admin", "content", "user"):
        query["category"] = category
    if min_severity:
        order = ["INFO", "WARNING", "HIGH", "CRITICAL"]
        idx = order.index(min_severity) if min_severity in order else 0
        query["severity"] = {"$in": order[idx:]}
    if q:
        pat = re.compile(re.escape(q), re.IGNORECASE)
        query["$or"] = [{"action": pat}, {"actor.name": pat}, {"target.label": pat},
                        {"details": pat}, {"module": pat}]
    if actor:
        actor_pat = re.compile(re.escape(actor.strip()), re.IGNORECASE)
        actor_or = [{"actor.name": actor_pat}]
        if actor.strip().isdigit():
            actor_or.extend([{"actor.id": int(actor.strip())}, {"actor.id": actor.strip()}])
        query.setdefault("$and", []).append({"$or": actor_or})
    if actor_role:
        query["actor.role"] = re.compile(re.escape(actor_role.strip()), re.IGNORECASE)
    if module:
        query["module"] = module.strip()
    if action:
        query["action"] = re.compile(re.escape(action.strip()), re.IGNORECASE)
    if target_type:
        query["target.type"] = target_type.strip()
    if target:
        target_pat = re.compile(re.escape(target.strip()), re.IGNORECASE)
        query.setdefault("$and", []).append({"$or": [
            {"target.label": target_pat}, {"target.id": target.strip()}, {"target_id": target.strip()}]})
    if date_from or date_to:
        ts = {}
        try:
            if date_from:
                ts["$gte"] = day_bounds_utc(parse_gregorian_date(date_from))[0].isoformat()
            if date_to:
                ts["$lt"] = day_bounds_utc(parse_gregorian_date(date_to))[1].isoformat()
        except ValueError:
            raise HTTPException(422, "بازه تاریخ معتبر نیست")
        query["timestamp"] = ts
    if correlation_id:
        query["correlation_id"] = correlation_id.strip()[:120]
    return query


@router.get("/audit-logs")
async def audit_logs_admin(
    admin=Depends(require_perm("audit.view")),
    category: Optional[str] = Query(None),
    min_severity: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    actor: Optional[str] = Query(None),
    actor_role: Optional[str] = Query(None),
    module: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    target_type: Optional[str] = Query(None),
    target: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    correlation_id: Optional[str] = Query(None),
    sort_dir: str = Query("desc"),
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
):
    """فهرست لاگ فعالیت با فیلتر دسته/سطح/جست‌وجو + شمارنده سطوح.

    داده همان audit_logs مشترک با بات است؛ اکشن‌های ثبت‌شده از پنل وب
    (تگ «پنل_وب») و اکشن‌های بات هر دو اینجا دیده می‌شوند.
    """
    query = build_audit_query(
        category=category, min_severity=min_severity, q=q, actor=actor,
        actor_role=actor_role, module=module, action=action, target_type=target_type,
        target=target, date_from=date_from, date_to=date_to,
        correlation_id=correlation_id,
    )

    total = await db.audit_logs.count_documents(query)

    # شمارنده سطوح (با همان فیلترهای دسته/جست‌وجو، بدون فیلتر سطح)
    counter_query = {k: v for k, v in query.items() if k != "severity"}
    sev_counts = await db.audit_logs.aggregate([
        {"$match": counter_query},
        {"$group": {"_id": "$severity", "count": {"$sum": 1}}},
    ]).to_list(10)
    counters = {
        r["_id"]: r["count"] for r in sev_counts if r.get("_id")
    }

    direction = 1 if isinstance(sort_dir, str) and sort_dir == "asc" else -1
    rows = await db.audit_logs.find(query).sort(
        "timestamp", direction
    ).skip(skip).limit(limit).to_list(limit)

    logs = [{
        "id": str(r.get("_id")),
        "timestamp": r.get("timestamp", ""),
        "severity": r.get("severity", "INFO"),
        "category": r.get("category", "admin"),
        "module": r.get("module", ""),
        "action": r.get("action", ""),
        "actor": r.get("actor") or {},
        "target": r.get("target") or {},
        "details": r.get("details", ""),
        "changes": r.get("changes") or [],
        "tags": r.get("tags") or [],
        "correlation_id": r.get("correlation_id"),
        "metadata": r.get("metadata") or {},
    } for r in rows]

    return {"logs": logs, "total": total, "counters": counters}


@router.get("/audit-health")
async def audit_health(admin=Depends(require_perm("audit.view"))):
    """🆕 Audit Refactor §52 — سلامت سیستم حسابرسی (Delivery + DB)."""
    try:
        db_health = await db.get_audit_health_metrics()
    except Exception as e:
        db_health = {"error": str(e)[:200]}
    # delivery health از audit.py (in-memory)
    try:
        from audit import get_delivery_health as _adh
        delivery = _adh()
    except Exception:
        delivery = {}
    # outbox/queue عمق
    try:
        pending_outbox = await db.client["medicalbot"]["audit_outbox"].count_documents({"status": {"$in": ["PENDING","RETRY"]}})
    except Exception:
        try:
            pending_outbox = await db.client["medicalbot"]["bot_notifications"].count_documents({"sent": False, "type": {"$regex": "audit"}})
        except Exception:
            pending_outbox = None
    return {"db": db_health, "delivery": delivery, "pending_outbox": pending_outbox}


# ══════════════════════════════════════════════
# 📊 آمار تحلیلی (نمودارهای پنل وب)
# ══════════════════════════════════════════════

@router.get("/analytics")
async def analytics_admin(
    admin=Depends(require_perm("stats.deep")),
    days: int = Query(14, ge=1, le=90),
):
    """آمار روزانه بازه اخیر + کاربران فعال + توزیع عملیات و ساعات اوج.

    🌊 موج Analytics-Filters — بدنه به db.stats_analytics_bundle منتقل شد
    (تک‌منبع حقیقت: هم این endpoint مالک، هم wa-analytics با گیت stats.deep).
    خروجی دقیقاً همان شکل قبلی است.
    """
    return await db.stats_analytics_bundle(days)


# ══════════════════════════════════════════════════
#  👑 P3 — Prestige: تنظیمات زنده‌ی تعادل + پایش چالش
# ══════════════════════════════════════════════════

# کلیدهای مجاز اورراید (آستانه‌ی رنک‌ها عمداً اینجا نیست — Design Lock)
# key: (برچسب فارسی, حداقل, حداکثر)
PRESTIGE_CFG_KEYS = {
    "xp_easy":               ("XP پاسخ آسان", 0, 200),
    "xp_medium":             ("XP پاسخ متوسط", 0, 300),
    "xp_hard":               ("XP پاسخ سخت", 0, 500),
    "xp_unknown":            ("XP پاسخ بدون سختی", 0, 300),
    "xp_wrong_first":        ("XP تلاش اولین‌بار", 0, 50),
    "xp_streak_day":         ("XP فعالیت روزانه (استریک)", 0, 200),
    "xp_exam_complete":      ("XP تکمیل آزمون", 0, 500),
    "xp_exam_acc80":         ("بونوس دقت ≥۸۰٪ آزمون", 0, 300),
    "xp_exam_perfect":       ("بونوس برگ کامل آزمون", 0, 300),
    "xp_file_download":      ("XP اولین دانلود هر فایل", 0, 100),
    "xp_ai_daily":           ("XP گفت‌وگوی روزانه‌ی هوشیار", 0, 100),
    "xp_question_approved":  ("XP تأیید سؤال طراحی‌شده", 0, 300),
    "xp_report_useful":      ("XP گزارش مفید", 0, 300),
    "xp_challenge_win":      ("جایزه‌ی برد چالش ارتقا", 0, 1000),
    "xp_apex_win":           ("جایزه‌ی برد چالش Apex (یک‌بار)", 0, 2000),
    "xp_weekly_champion":    ("جایزه‌ی قهرمان هفته", 0, 1000),
    "daily_cap":             ("سقف روزانه‌ی XP پاسخ‌محور", 10, 1000),
    "diminish_after":        ("آستانه‌ی diminishing (صحیح/روز)", 5, 400),
    "shield_answers":        ("سپر ارتقا (تعداد پاسخ)", 0, 200),
    "shield_days":           ("سپر ارتقا (روز)", 0, 90),
    "decay_idle_days":       ("پنجره‌ی رکود Decay (روز)", 3, 90),
    "challenge_cooldown_h":  ("کول‌داون شکست چالش (ساعت)", 1, 168),
    "challenge_cooldown_apex_h": ("کول‌داون شکست Apex (ساعت)", 1, 720),
}


def _prestige_cfg_defaults() -> dict:
    return {
        "xp_easy": db.XP_BY_DIFF["easy"], "xp_medium": db.XP_BY_DIFF["medium"],
        "xp_hard": db.XP_BY_DIFF["hard"], "xp_unknown": db.XP_BY_DIFF["unknown"],
        "xp_wrong_first": db.XP_WRONG_FIRST, "xp_streak_day": db.XP_DAILY_STREAK,
        "xp_exam_complete": db.XP_EXAM_COMPLETE,
        "xp_exam_acc80": db.XP_EXAM_ACC_BONUS,
        "xp_exam_perfect": db.XP_EXAM_PERFECT,
        "xp_file_download": db.XP_FILE_DOWNLOAD, "xp_ai_daily": db.XP_AI_DAILY,
        "xp_question_approved": db.XP_Q_APPROVED,
        "xp_report_useful": db.XP_REPORT_USEFUL,
        "xp_challenge_win": db.XP_CHALLENGE_WIN, "xp_apex_win": db.XP_APEX_WIN,
        "xp_weekly_champion": db.XP_WEEKLY_CHAMPION,
        "daily_cap": db.DAILY_ANSWER_CAP, "diminish_after": db.DIMINISH_AFTER,
        "shield_answers": db.SHIELD_ANSWERS, "shield_days": db.SHIELD_DAYS,
        "decay_idle_days": db.DECAY_IDLE_DAYS,
        "challenge_cooldown_h": db.CH_COOLDOWN_H,
        "challenge_cooldown_apex_h": db.CH_APEX_COOLDOWN_H,
    }


@router.get("/prestige-config")
async def prestige_config_get(admin=Depends(require_perm("prestige.manage"))):
    """خواندن تنظیمات زنده‌ی پرستیژ: پیش‌فرض + اورراید + مؤثر + آمار چالش"""
    try:
        doc = await db.settings.find_one({"_id": "prestige_config"}) or {}
    except Exception:
        doc = {}
    values = doc.get("values") or {}
    if not isinstance(values, dict):
        values = {}
    defaults = _prestige_cfg_defaults()
    effective = dict(defaults)
    for k, v in values.items():
        if k in PRESTIGE_CFG_KEYS and isinstance(v, (int, float)):
            effective[k] = int(v)
    stats = {}
    try:
        stats = await db.prestige_challenge_stats()
    except Exception:
        stats = {}
    return {
        "defaults": defaults, "overrides": values, "effective": effective,
        "meta": {k: {"label": v[0], "min": v[1], "max": v[2]}
                 for k, v in PRESTIGE_CFG_KEYS.items()},
        "updated_at": doc.get("updated_at", ""),
        "challenge_stats": stats,
    }


class PrestigeConfigPut(BaseModel):
    values: dict = {}


@router.put("/prestige-config")
async def prestige_config_put(body: PrestigeConfigPut, admin=Depends(require_perm("prestige.manage"))):
    """ذخیره‌ی اوررایدها — بدون ری‌دیپلوی (کش ۶۰ثانیه‌ای فوراً باطل می‌شود).
    مقادیر نامعتبر/کلید ناشناخته ⇒ rejected، بدون ذخیره‌ی آن کلید."""
    if not isinstance(body.values, dict):
        raise HTTPException(422, "ساختار values نامعتبر است")
    clean, rejected = {}, []
    for k, v in (body.values or {}).items():
        if k not in PRESTIGE_CFG_KEYS:
            rejected.append(k)
            continue
        try:
            num = float(v)
        except Exception:
            rejected.append(k)
            continue
        lo, hi = PRESTIGE_CFG_KEYS[k][1], PRESTIGE_CFG_KEYS[k][2]
        if not (lo <= num <= hi):
            rejected.append(k)
            continue
        clean[k] = int(num)
    try:
        old_doc = await db.settings.find_one({"_id": "prestige_config"}) or {}
    except Exception:
        old_doc = {}
    old = old_doc.get("values") or {}
    await db.settings.update_one(
        {"_id": "prestige_config"},
        {"$set": {"values": clean,
                  "updated_at": utc_now_iso()}},
        upsert=True)
    try:
        setattr(db, "_pcfgc", None)      # باطل‌سازی فوری کش ۶۰ثانیه‌ای موتور
    except Exception:
        pass
    await _audit(admin, "به‌روزرسانی تنظیمات زنده‌ی پرستیژ", "Prestige",
                 severity="HIGH", before=old, after=clean,
                 tags=["پرستیژ", "تعادل", "پنل_وب"])
    return {"ok": True, "applied": clean, "rejected": rejected}
