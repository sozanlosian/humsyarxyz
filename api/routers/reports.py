import logging
"""🚩 Reports"""
import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from api.auth import get_current_user
from database import db
from api.rate_limit import rate_limit_user  # 🛡 W3/SEC-03
from request_context import current_request_id
from time_utils import utc_now_iso

router = APIRouter()
REASONS = [{"key":"wrong_answer","label":"❌ پاسخ اشتباه"},{"key":"wrong_option","label":"🔤 گزینه اشتباه"},
    {"key":"incomplete","label":"✂️ متن ناقص"},{"key":"broken_file","label":"💔 فایل خراب"},
    {"key":"outdated","label":"📅 محتوا قدیمی"},{"key":"other","label":"🔍 سایر"}]

@router.get("/reasons")
async def reasons(user=Depends(get_current_user)):
    return {"reasons":REASONS}

class ReportIn(BaseModel):
    target_type: str; target_id: str; reason: str
    note: Optional[str] = ""

@router.post("")
async def create_report(body: ReportIn, user=Depends(get_current_user)):
    if body.target_type not in ("question","resource"): raise HTTPException(422)
    if body.reason not in {r["key"] for r in REASONS}: raise HTTPException(422)
    uid = user["id"]; db_user = user["_db"]
    # 🛡 W3/SEC-03 — ضد اسپم گزارش تخلف
    await rate_limit_user(uid, "report_create", 10, 60)
    designer_id = None; target_label = "فایل"
    if body.target_type == "question":
        q = await db.get_question_by_id(body.target_id)
        if not q: raise HTTPException(404)
        designer_id = q.get("creator_id"); target_label = f"{q.get('lesson','')} — {q.get('topic','')}"
    rid = await db.create_content_report(target_type=body.target_type,target_id=body.target_id,
        reporter_id=uid,reporter_name=db_user.get("name",""),reason=body.reason,note=body.note or "",designer_id=designer_id)
    # AUDIT — user report creation (user-initiated, INFO, redacted note)
    try:
        _role = await db.get_actor_role_label(uid)
    except Exception:
        _role = "student"
    try:
        await db.log_action(
            uid, db_user.get("name",""), _role,
            "ثبت گزارش محتوا", "Reports", category="content", severity="INFO",
            target_id=str(rid), target_type=body.target_type, target_label=target_label[:80],
            after={"reason": body.reason, "target_id": body.target_id[:24]},
            details=(body.note or "")[:120],
        )
    except Exception:
        pass
    try:
        reason_lbl = next((r["label"] for r in REASONS if r["key"]==body.reason),body.reason)
        notif = db.client["medicalbot"]["bot_notifications"]
        await notif.insert_one({"type":"content_report","chat_id":int(os.getenv("ADMIN_ID","0")),
            "text":f"🚩 <b>گزارش #{rid}</b>\n👤 {db_user.get('name','')}\n📦 {target_label}\n⚠️ {reason_lbl}",
            "sent":False,"created_at":utc_now_iso()})
    except Exception as _ne:
        # 🛡 AUDIT-R6 — اگر درجِ صف اعلان شکست بخورد، ادمین هرگز از این گزارش
        # باخبر نمی‌شود. درخواست کاربر را نمی‌شکنیم، ولی ردپا می‌ماند.
        logging.getLogger(__name__).warning("notif enqueue failed (گزارش): %s", _ne)
    return {"ok":True,"message":"✅ گزارش ثبت شد."}

@router.get("/my")
async def my_reports(user=Depends(get_current_user)):
    docs = await db.content_reports.find({"reporter_id":user["id"]}).sort("created_at",-1).to_list(50)
    STATUS = {"new":"در انتظار","reviewing":"در بررسی","resolved":"برطرف شد","rejected":"رد شد"}
    return {"reports":[{"id":d.get("report_id",str(d["_id"])),"target_type":d.get("target_type",""),
        "reason":next((r["label"] for r in REASONS if r["key"]==d.get("reason")),d.get("reason","")),
        "note":d.get("note",""),"status":d.get("status","new"),
        "status_label":STATUS.get(d.get("status","new"),"نامشخص"),
        "created_at":d.get("created_at") or None} for d in docs]}
