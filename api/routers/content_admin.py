"""🎓 Content Admin — 🌊 موج C1: enforce اسکوپ ورودی در سطح endpoint"""
import logging
import os
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel, Field
from typing import Optional, List
from api.auth import get_content_admin_user, get_content_global_user, get_current_user, resolve_content_intake
from api.telegram_send import upload_and_get_file_id
from api.routers.admin_panel import _audit
from database import db
from time_utils import TimeContractError, parse_gregorian_date
from question_bank import QuestionBankService, QuestionDomainError
from question_bank.contracts import canonical_difficulty, canonical_status, status_query

logger = logging.getLogger(__name__)

router = APIRouter()
question_bank = QuestionBankService(db)


def _qerror(exc: QuestionDomainError):
    raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message,
                                          **({"details": exc.details} if exc.details else {})})
TERMS = ['ترم ۱', 'ترم ۲', 'ترم ۳', 'ترم ۴', 'ترم ۵']
CONTENT_TYPES = ['video', 'ppt', 'pdf', 'note', 'test', 'voice']
# سقف آپلود: زیر سقف ۵۰MB بات تلگرام (deployment رسمی) با حاشیه‌ی امن
MAX_UPLOAD_BYTES = 45 * 1024 * 1024


async def _read_capped(file: UploadFile, cap: int) -> bytes:
    """خواندن stream با سقف — فایل بیش‌ازحد به‌جای بلعیدن کامل حافظه،
    در همان نقطه‌ی عبور از سقف با ۴۱۳ رد می‌شود (منطق قبلی: read کامل
    و بعد چک — برای ویدیوی بزرگ هم حافظه هم پهنای باند هدر می‌رفت)."""
    chunks = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > cap:
            raise HTTPException(413, "حجم فایل بیش از حد مجاز است (۴۵MB)")
        chunks.append(chunk)
    return b"".join(chunks)

# 🛡 W1 — magic-byte validation (content-type spoofing defence)
# Only checks obvious mismatches; passes unknown types through (fail-open for valid but rare formats).
def _validate_magic(data: bytes, declared_mime: str, filename: str = "") -> None:
    if not data or len(data) < 4:
        return
    head = data[:12]
    mime = (declared_mime or "").lower()
    name = (filename or "").lower()
    # PDF must be %PDF
    if mime == "application/pdf" or name.endswith(".pdf"):
        if not head.startswith(b"%PDF"):
            raise HTTPException(422, "فایل PDF نامعتبر است (امضای فایل هم‌خوانی ندارد)")
    # ZIP-based: pptx/xlsx/docx are ZIP archives (PK..)
    if any(name.endswith(x) for x in (".pptx",".xlsx",".docx",".zip")):
        if not head.startswith(b"PK"):
            # Some old .ppt/.doc are OLE (D0 CF 11 E0) — allow both
            if not head.startswith(b"\xD0\xCF\x11\xE0"):
                raise HTTPException(422, "فایل Office نامعتبر است")
    if mime.startswith("image/"):
        # JPEG FF D8, PNG 89 50 4E 47, GIF 47 49 46, WEBP RIFF....WEBP
        if head.startswith(b"\xFF\xD8\xFF"):
            return
        if head.startswith(b"\x89PNG"):
            return
        if head.startswith(b"GIF8"):
            return
        if head.startswith(b"RIFF") and b"WEBP" in head:
            return
        # allow but log mismatch for images
        logger.warning("IMAGE_MAGIC_MISMATCH mime=%s filename=%s head=%s", mime, filename, head[:8].hex())
    if mime.startswith("video/"):
        # MP4 ftyp, WEBM 1A 45 DF A3, etc — just ensure not PDF/zip masquerading as video
        if head.startswith(b"%PDF") or head.startswith(b"PK"):
            raise HTTPException(422, "فایل ویدیویی نامعتبر است")
GLOBAL_USER = get_content_global_user  # بخش‌های بدون scope (schedule/grades/reports) — رفتار دقیق قبلی


async def get_question_reviewer(user=Depends(get_current_user)) -> dict:
    try:
        scope = await question_bank.permissions.review_scope(user)
    except QuestionDomainError as exc:
        _qerror(exc)
    return {**user, "_scope": scope}


async def _deny_intake(item_intake: str, admin: dict):
    """۴۰۳ اگر آیتم خارج از scope کاربر باشد.

    wrapperهای permission-based می‌توانند scope حل‌شده را روی admin بگذارند؛
    مسیرهای قدیمی بدون آن همچنان از منبع واحد db استفاده می‌کنند.
    """
    scope = admin.get("_scope")
    if scope:
        if scope.get("kind") == "global":
            return
        own = scope.get("intake") or ""
        # 🛡 C3.1 — scope تنظیم‌نشده ⇒ هیچ سطلی برای نوشتن؛ سراسری هم نه
        if own and (item_intake or "") == own:
            return
        raise HTTPException(403, "intake_out_of_scope")
    if not await db.can_access_intake(admin["id"], item_intake or ''):
        raise HTTPException(403, "intake_out_of_scope")


async def _read_intake(item_intake: str, admin: dict) -> bool:
    """🌊 C1.5 — گیت مشاهده؛ سراسری برای scoped فقط‌خواندنی است."""
    scope = admin.get("_scope")
    if scope:
        if scope.get("kind") == "global":
            return False
        own = scope.get("intake") or ""
        if own and (item_intake or "") == own:
            return False
        if (item_intake or "") == "":
            return True
        raise HTTPException(403, "intake_out_of_scope")
    if await db.can_access_intake(admin["id"], item_intake or ''):
        return False
    scope = admin.get("_scope") or {}
    if scope.get("kind") == "scoped" and (item_intake or '') == '':
        return True
    raise HTTPException(403, "intake_out_of_scope")


async def _deny_create_in(bucket: str, admin: dict):
    """🛡 C3.1 — «آیا اجازه دارد *در این سطل* آیتم بسازد؟»

    مسیرهای ساختِ آیتم‌های سطح‌بالا (درس، موضوع رفرنس) آیتمِ موجودی را
    mutate نمی‌کنند، پس _deny_intake رویشان صدق نمی‌کند؛ بدون این گیت،
    ادمین scopedِ بدون-scope با resolve_content_intake سطل '' (سراسری) را
    تحویل می‌گرفت و روی هسته‌ی مشترک می‌نوشت. تصمیم از همان منبع واحد
    (db.can_access_intake) گرفته می‌شود."""
    if await db.can_access_intake(admin["id"], bucket or ''):
        return
    scope = admin.get("_scope") or {}
    if scope.get("kind") == "scoped" and not (scope.get("intake") or ""):
        raise HTTPException(403, "intake_not_configured")
    raise HTTPException(403, "intake_out_of_scope")


@router.get("/intakes")
async def content_intakes(admin=Depends(get_content_admin_user)):
    """🌊 C1 — لیست ورودی‌های فعال برای picker مینی‌اپ + scope فعلی کاربر.
    ادمین ورودی خاص: فقط scope خودش را می‌بیند (گزینه‌ای برای انتخاب ندارد)."""
    scope = admin.get("_scope") or {"kind": "global", "intake": None}
    items = await db.get_all_intakes()
    active = [{"code": i["code"], "label": i["label"]}
              for i in items if i.get("active", True)]
    own = scope.get("intake") or ""
    own_label = next((i["label"] for i in items if i["code"] == own), own)
    return {
        "scope_kind": scope.get("kind"),
        "scope_intake": own if scope.get("kind") == "scoped" else None,
        "scope_label": own_label if scope.get("kind") == "scoped" else None,
        "intakes": active if scope.get("kind") == "global"
                   else [{"code": own, "label": own_label}],
    }


@router.get("/overview")
async def overview(admin=Depends(get_content_admin_user),
                   intake: Optional[str] = Query(None),
                   effective: Optional[bool] = Query(False)):
    iv = resolve_content_intake(admin, intake)
    # آمار هم‌scope با ورودی انتخاب‌شده (§۱۷ spec) — بدون نشت cross-intake
    s = await db.content_admin_stats(intake=iv)
    out = {"intake": iv,
        "pending_questions":s["q_pending"],
        "approved_questions":s["q_total"],
        "total_resources":s["bs_total"],
        "upcoming_exams":0,"total_faq":0}
    # 🌊 C1.5 — زیرساخت «آمار مؤثر» (§۲۳ spec): اختصاصی + سراسری —
    # فقط وقتی صراحتاً درخواست شود (رفتار پیش‌فرض دست‌نخورده)
    if effective:
        e = await db.content_admin_stats(intake=iv, effective=True)
        out["effective"] = {
            "pending_questions": e["q_pending"],
            "approved_questions": e["q_total"],
            "total_resources": e["bs_total"],
        }
    return out

@router.get("/questions/pending")
async def pending_questions(admin=Depends(get_question_reviewer),
                            intake: Optional[str] = Query(None),
                            skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                            after: Optional[str] = Query(None, max_length=32, description="cursor _id")):
    iv = resolve_content_intake(admin, intake)
    query = {"$and": [status_query("pending"), {"intake": iv}]}
    # 🌊 W4 — cursor pagination
    if after:
        try:
            from bson import ObjectId as _OID
            if _OID.is_valid(after):
                query["$and"].append({"_id": {"$gt": _OID(after)}})
                docs = await db.questions.find(query).sort("_id", 1).limit(limit + 1).to_list(limit + 1)
                has_more = len(docs) > limit
                if has_more:
                    docs = docs[:limit]
                next_cursor = str(docs[-1]["_id"]) if docs and has_more else None
                # for cursor we don't need total
                return {"intake": iv, "total": None, "skip": None, "limit": limit, "next_cursor": next_cursor, "has_more": has_more,
        "questions":[{"id":str(d["_id"]),"lesson_id":str(d.get("lesson_id") or ""),
        "topic_id":str(d.get("topic_id") or ""),"lesson":d.get("lesson",""),"topic":d.get("topic",""),
        "difficulty":canonical_difficulty(d.get("difficulty"), strict=False),"question":d.get("question",""),"options":d.get("options",[]),
        "correct":d.get("correct_answer",0),"explanation":d.get("explanation",""),
        "creator_name":d.get("creator_name",""),"creator_id":d.get("creator_id"),
        "creator_type":d.get("creator_type","student"),"created_at":d.get("created_at") or None,
        "updated_at":d.get("updated_at") or None,"intake":d.get("intake",""),
        "status":canonical_status(d),"review_reason":d.get("review_reason", ""),
        "source":d.get("source","system")} for d in docs]}
        except Exception:
            pass
    total = await db.questions.count_documents(query)
    docs = await db.questions.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    return {"intake": iv, "total": total, "skip": skip, "limit": limit, "next_cursor": None, "has_more": skip + len(docs) < total,
        "questions":[{"id":str(d["_id"]),"lesson_id":str(d.get("lesson_id") or ""),
        "topic_id":str(d.get("topic_id") or ""),"lesson":d.get("lesson",""),"topic":d.get("topic",""),
        "difficulty":canonical_difficulty(d.get("difficulty"), strict=False),"question":d.get("question",""),"options":d.get("options",[]),
        "correct":d.get("correct_answer",0),"explanation":d.get("explanation",""),
        "creator_name":d.get("creator_name",""),"creator_id":d.get("creator_id"),
        "creator_type":d.get("creator_type","student"),"created_at":d.get("created_at") or None,
        "updated_at":d.get("updated_at") or None,"intake":d.get("intake",""),
        "status":canonical_status(d),"review_reason":d.get("review_reason", ""),
        "source":d.get("source","system")} for d in docs]}

# ── §W8 — نمای تجمیعیِ گزارش‌های یک سؤال ──────────────────────────
#
# طراح نباید برای فهمیدنِ «این سؤال ایراد دارد» ۳۰ کارتِ جدا باز کند.
# یک درخواست، خلاصهٔ دسته‌بندی‌شده + جزئیاتِ کرانه‌دار می‌دهد.
@router.get("/questions/{qid}/reports")
async def question_reports(qid: str, admin=Depends(get_question_reviewer),
                           limit: int = Query(50, ge=1, le=200)):
    """گزارش‌های یک سؤال: شمارش، تفکیکِ دلیل، و آخرین موارد."""
    q = await db.get_question_by_id(qid)
    if not q:
        raise HTTPException(404, "سؤال پیدا نشد")
    await _deny_intake(q.get("intake", ""), admin)

    base = {"target_type": "question", "target_id": str(qid)}
    total = await db.content_reports.count_documents(base)
    open_count = await db.content_reports.count_documents(
        {**base, "status": {"$in": ["new", "reviewing"]}})

    by_reason = {}
    try:
        rows = await db.content_reports.aggregate([
            {"$match": base},
            {"$group": {"_id": "$reason", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]).to_list(50)
        by_reason = {str(r["_id"] or "other"): int(r["count"]) for r in rows}
    except Exception:
        logger.exception("report aggregation failed qid=%s", qid)

    docs = await db.content_reports.find(base).sort(
        "created_at", -1).limit(limit).to_list(limit)
    # 🔒 هویتِ گزارش‌دهنده به طراح داده نمی‌شود مگر ادمینِ سراسری باشد
    # (§۵۷). طراح برای اصلاحِ سؤال به نامِ دانشجو نیازی ندارد.
    scope = (admin.get("_scope") or {})
    full = bool(admin.get("is_owner")) or scope.get("kind") == "global"
    items = [{
        "report_id": d.get("report_id"),
        "reason": d.get("reason", ""),
        "note": d.get("note", ""),
        "status": d.get("status", "new"),
        "created_at": d.get("created_at"),
        "resolved_at": d.get("resolved_at"),
        **({"reporter_id": d.get("reporter_id"),
            "reporter_name": d.get("reporter_name", "")} if full else {}),
    } for d in docs]

    # §W9 — سطحِ شدت از تعدادِ گزارشِ *باز* محاسبه می‌شود. چون گزارشِ
    # تکراریِ یک کاربر مسدود است، هر گزارش یعنی یک کاربرِ متمایز.
    thresholds = await db.report_severity_thresholds()
    severity = await db.report_severity_of(open_count, thresholds)

    return {"question_id": str(qid), "total": total, "open": open_count,
            "by_reason": by_reason, "severity": severity,
            "thresholds": thresholds,
            "last_report_at": docs[0].get("created_at") if docs else None,
            "reports": items}


@router.get("/questions/reported")
async def reported_questions(admin=Depends(get_question_reviewer),
                             intake: Optional[str] = Query(None),
                             min_reports: int = Query(1, ge=1, le=1000),
                             skip: int = Query(0, ge=0),
                             limit: int = Query(50, ge=1, le=100)):
    """§۸۳ — سؤالاتِ گزارش‌دار با شمارش، مرتب بر اساسِ شدت.

    بدونِ این، طراح باید تک‌تکِ سؤال‌ها را باز کند تا بفهمد کدام مشکل
    دارد. تجمیع در دیتابیس انجام می‌شود نه در پایتون (§۵۸ — پرهیز از
    N+1: صد سؤال ⇒ صد کوئریِ شمارش).
    """
    iv = resolve_content_intake(admin, intake)

    pipeline = [
        {"$match": {"target_type": "question",
                    "status": {"$in": ["new", "reviewing"]}}},
        {"$group": {"_id": "$target_id",
                    "open": {"$sum": 1},
                    "last_report_at": {"$max": "$created_at"},
                    "reasons": {"$push": "$reason"}}},
        {"$match": {"open": {"$gte": int(min_reports)}}},
        {"$sort": {"open": -1, "last_report_at": -1}},
        {"$skip": int(skip)}, {"$limit": int(limit)},
    ]
    rows = await db.content_reports.aggregate(pipeline).to_list(limit)
    if not rows:
        return {"intake": iv, "total": 0, "questions": []}

    oids = [ObjectId(r["_id"]) for r in rows if ObjectId.is_valid(str(r["_id"]))]
    qdocs = {str(d["_id"]): d for d in
             await db.questions.find({"_id": {"$in": oids}}).to_list(len(oids))}

    thresholds = await db.report_severity_thresholds()
    out = []
    for r in rows:
        q = qdocs.get(str(r["_id"]))
        if not q:
            continue                      # سؤالِ حذف‌شده
        # scope: ادمینِ محدود فقط ورودیِ خودش را می‌بیند
        if iv and str(q.get("intake") or "").strip() != iv:
            continue
        reasons = {}
        for x in r.get("reasons") or []:
            reasons[str(x or "other")] = reasons.get(str(x or "other"), 0) + 1
        out.append({
            "id": str(q["_id"]),
            "question": q.get("question", "")[:200],
            "lesson": q.get("lesson", ""), "topic": q.get("topic", ""),
            "status": canonical_status(q),
            "creator_name": q.get("creator_name", ""),
            "creator_id": q.get("creator_id"),
            "intake": q.get("intake", ""),
            "open": int(r["open"]),
            "by_reason": reasons,
            "last_report_at": r.get("last_report_at"),
            "severity": await db.report_severity_of(int(r["open"]), thresholds),
        })
    return {"intake": iv, "total": len(out), "thresholds": thresholds,
            "questions": out}


class QuestionReviewInput(BaseModel):
    reason: str = Field(default="", max_length=1000)


async def _review_question(qid: str, target: str, reason: str, admin: dict):
    q = await db.get_question_by_id(qid)
    if not q: raise HTTPException(404, "سؤال پیدا نشد")
    await _deny_intake(q.get("intake", ""), admin)
    try:
        updated = await question_bank.transition(
            question_id=qid, reviewer=admin, target=target, reason=reason)
    except QuestionDomainError as exc:
        _qerror(exc)
    labels = {"approved": "تأیید سؤال پیشنهادی", "rejected": "رد سؤال پیشنهادی",
              "needs_changes": "درخواست اصلاح سؤال"}
    await _audit(admin, labels[target], "Questions",
        severity="INFO" if target == "approved" else "WARNING",
        target_id=qid, target_type="question",
        target_label=f"{q.get('lesson','')} — {q.get('topic','')}"[:300],
        before={"status": canonical_status(q)}, after={"status": target, "reason": reason},
        tags=["سؤال", target, "پنل_وب"])
    return {"ok": True, "status": target, "version": updated.get("version")}


@router.post("/questions/{qid}/approve")
async def approve_question(qid: str, body: QuestionReviewInput = None,
                           admin=Depends(get_question_reviewer)):
    return await _review_question(qid, "approved", (body or QuestionReviewInput()).reason, admin)


@router.post("/questions/{qid}/reject")
async def reject_question(qid: str, body: QuestionReviewInput,
                          admin=Depends(get_question_reviewer)):
    return await _review_question(qid, "rejected", body.reason, admin)


@router.post("/questions/{qid}/needs-changes")
async def needs_changes_question(qid: str, body: QuestionReviewInput,
                                 admin=Depends(get_question_reviewer)):
    return await _review_question(qid, "needs_changes", body.reason, admin)


@router.delete("/questions/{qid}")
async def delete_question(qid: str, reason: str = Query(default="", max_length=1000),
                          admin=Depends(get_question_reviewer)):
    """🛡 §۸۴ — حذفِ سختِ سؤال؛ تنها مسیرِ اعمالِ مجوز `questions.delete`.

    این مجوز در کاتالوگ RBAC وجود داشت ولی هیچ کجا چک نمی‌شد (نه در پنل، نه
    در ربات) — یعنی ادمین می‌توانست آن را به یک نقش بدهد یا از آن بگیرد
    بدون کوچک‌ترین اثری. حالا این endpoint آن را واقعی می‌کند.

    مجوزسنجی داخل `question_bank` انجام می‌شود (منبع یکتا)، نه اینجا؛
    `_deny_intake` هم مثل بقیه‌ی مسیرها لایه‌ی دومِ scope است.
    """
    q = await db.get_question_by_id(qid)
    if not q:
        raise HTTPException(404, "سؤال پیدا نشد")
    await _deny_intake(q.get("intake", ""), admin)
    try:
        removed = await question_bank.delete_question(
            question_id=qid, actor=admin, reason=reason)
    except QuestionDomainError as exc:
        _qerror(exc)
    await _audit(admin, "حذف سؤال", "Questions", severity="CRITICAL",
        target_id=qid, target_type="question",
        target_label=f"{q.get('lesson','')} — {q.get('topic','')}"[:300],
        before={"status": removed.get("status"), "question": removed.get("question"),
                "creator_id": removed.get("creator_id")},
        after={"deleted": True, "reason": removed.get("reason")},
        tags=["سؤال", "حذف", "پنل_وب"])
    return {"ok": True, "deleted": True, "id": removed.get("id")}


# ── 🌊 موج Q-Editor — ویرایش سؤال پیش از تأیید (scope-aware + audit) ──
class QuestionPatch(BaseModel):
    lesson_id: Optional[str] = None
    topic_id: Optional[str] = None
    question: Optional[str] = None
    options: Optional[List[str]] = None
    correct: Optional[int] = None                    # ایندکس گزینه‌ی صحیح (۰-مبنا)
    explanation: Optional[str] = None
    difficulty: Optional[str] = None                 # easy | medium | hard
    lesson: Optional[str] = None
    topic: Optional[str] = None

@router.patch("/questions/{qid}")
async def patch_question(qid: str, body: QuestionPatch,
                         admin=Depends(get_question_reviewer)):
    """Canonical reviewer edit; permission/scope/version live in the domain."""
    q = await db.get_question_by_id(qid)
    if not q:
        raise HTTPException(404, "سؤال پیدا نشد")
    payload = body.model_dump(exclude_none=True)
    if "correct" in payload:
        payload["correct_answer"] = payload.pop("correct")
    if not payload:
        raise HTTPException(422, "چیزی برای ویرایش نیست")
    try:
        updated = await question_bank.edit_pending(
            question_id=qid, reviewer=admin, payload=payload)
    except QuestionDomainError as exc:
        _qerror(exc)
    try:
        await db.log_action(
            admin["id"], (admin.get("_db") or {}).get("name", str(admin["id"])),
            await db.get_actor_role_label(admin["id"]),
            "ویرایش سؤال توسط بازبین", "QBank", "qbank", "WARNING",
            str(qid), "question", f"{q.get('lesson','')} — {q.get('topic','')}"[:300],
            {"version": q.get("version", 1)},
            {"version": updated.get("version"), "fields": sorted(payload)},
            "", ["ویرایش_سؤال", "پنل_وب"])
    except Exception:
        # Best-effort compensating rollback guarded by the version written above.
        # §W7 — «status» و همراهانش هم باید بازگردانده شوند: ویرایشِ
        # محتواییِ سؤالِ تأییدشده آن را به صف برمی‌گرداند، و اگر ثبتِ
        # حسابرسی شکست بخورد، بدونِ این کلیدها سؤال در `pending` گیر
        # می‌کرد و بی‌صدا از بانکِ عمومی خارج می‌ماند.
        restore_keys = ("question", "options", "correct_answer", "difficulty", "explanation",
                        "content_hash", "lesson_id", "topic_id", "lesson", "topic", "term", "intake", "updated_at",
                        "status", "approved", "reviewed_by", "reviewed_at", "review_reason")
        rollback = await db.questions.update_one(
            {"_id": q["_id"], "version": updated.get("version")},
            {"$set": {key: q.get(key) for key in restore_keys},
             "$inc": {"version": -1}, "$pop": {"review_history": 1}})
        if not rollback.modified_count:
            raise HTTPException(503, "ثبت حسابرسی ناموفق بود و تغییر هم‌زمان مانع بازگردانی شد")
        raise HTTPException(503, "ثبت حسابرسی ناموفق بود؛ ویرایش بازگردانده شد")
    # وضعیت را برمی‌گردانیم تا کلاینت بفهمد ویرایشِ محتوایی سؤال را به
    # صفِ بررسی برگردانده است (§W7).
    return {"ok": True, "changed": sorted(payload), "version": updated.get("version"),
            "status": canonical_status(updated),
            "requeued": canonical_status(updated) == "pending" and canonical_status(q) == "approved"}

# ── 🌊 موج Q-Import — درون‌ریزی گروهی سؤال (scope-aware + audit) ──
class QuestionImportItem(BaseModel):
    lesson: str = ""
    topic: str = ""
    difficulty: str = ""
    question: str = ""
    options: List[str] = []
    correct: int = 0
    explanation: str = ""

class QuestionImportBody(BaseModel):
    items: List[QuestionImportItem] = Field(default_factory=list, max_length=200)
    approve: bool = False           # درج مستقیمِ تأییدشده؟ (پیش‌فرض: به صف بازبینی)

@router.post("/questions/bulk-import")
async def bulk_import_questions(body: QuestionImportBody, intake: Optional[str] = Query(None),
                                admin=Depends(get_question_reviewer)):
    """Retired unsafe path: use owner JSON preview/confirm ingestion."""
    raise HTTPException(
        status_code=410,
        detail={"code": "preview_required",
                "message": "درون‌ریزی مستقیم غیرفعال است؛ از جریان JSON نسخه‌دار، پیش‌نمایش و تأیید نهایی استفاده کنید"})

@router.get("/schedule")
async def schedule_list(admin=Depends(GLOBAL_USER), stype: Optional[str]=Query(None)):
    items=await db.get_schedules(stype=stype, upcoming=False)
    return {"schedule":[{"id":str(s["_id"]),"type":s.get("type",""),"lesson":s.get("lesson",""),
        "teacher":s.get("teacher",""),"date":s.get("date",""),"time":s.get("time",""),
        "location":s.get("location",""),"group":db.normalize_group(s.get("group","هر دو")) or "هر دو","note":s.get("notes",""),
        "flex_type":s.get("flex_type","fixed"),"flex_note":s.get("flex_note","")} for s in items]}

class ScheduleCreate(BaseModel):
    type: str; lesson: str; teacher: str=""; date: str; time: str=""; group: str="هر دو"
    location: str=""; note: str=""; flex_type: str="fixed"

@router.post("/schedule")
async def add_schedule(body: ScheduleCreate, admin=Depends(GLOBAL_USER)):
    if body.type not in ("class", "exam", "makeup"):
        raise HTTPException(422, "نوع برنامه نامعتبر است")
    if body.flex_type not in ("fixed", "flexible"):
        raise HTTPException(422, "نوع زمان‌بندی نامعتبر")
    try:
        parse_gregorian_date(body.date)
    except (TimeContractError, ValueError):
        raise HTTPException(422, "فرمت تاریخ YYYY-MM-DD")
    group = db.normalize_group(body.group) or "هر دو"
    sid = await db.add_schedule(
        stype=body.type, lesson=body.lesson.strip(), teacher=body.teacher.strip(),
        date=body.date, time=body.time, location=body.location.strip(),
        notes=body.note.strip(), group=group, flex_type=body.flex_type)
    item = await db.get_schedule_by_id(str(sid)) or {
        "_id": sid, "type": body.type, "lesson": body.lesson.strip(),
        "teacher": body.teacher.strip(), "date": body.date, "time": body.time,
        "location": body.location.strip(), "notes": body.note.strip(), "group": group,
    }
    notice = await db.schedule_notify_event(item, "created")
    await _audit(
        admin, "ایجاد برنامه آموزشی", "Schedules", severity="INFO",
        target_id=str(sid), target_type="schedule", target_label=body.lesson.strip(),
        after={"type": body.type, "date": body.date, "time": body.time,
               "group": group, "notified": notice.get("notified", 0)},
        tags=["برنامه", body.type, "پنل_وب"],
    )
    # 🌊 W8/UX-05 — هشدار تداخل (غیرمسدودکننده)
    conflicts = await db.schedule_find_conflicts(
        group, body.date, body.time, '', exclude_id=str(sid))
    return {"ok": True, "id": str(sid), "notified": notice.get("notified", 0),
            "warnings": {"schedule_conflicts": conflicts}}


class ScheduleUpdate(BaseModel):
    lesson: str; teacher: str=""; date: str; time: str=""; group: str="هر دو"
    location: str=""; note: str=""; flex_type: str="fixed"

@router.patch("/schedule/{sid}")
async def edit_schedule(sid: str, body: ScheduleUpdate, admin=Depends(GLOBAL_USER)):
    try:
        parse_gregorian_date(body.date)
    except (TimeContractError, ValueError):
        raise HTTPException(422, "فرمت تاریخ YYYY-MM-DD")
    old = await db.get_schedule_by_id(sid)
    if not old:
        raise HTTPException(404, "برنامه پیدا نشد")
    group = db.normalize_group(body.group) or "هر دو"
    ok = await db.update_schedule_full(
        sid, body.lesson.strip(), body.teacher.strip(), body.date, body.time,
        body.location.strip(), body.note.strip(), group, body.flex_type)
    if not ok:
        raise HTTPException(404, "برنامه پیدا نشد")
    item = await db.get_schedule_by_id(sid) or {
        **old, "lesson": body.lesson.strip(), "teacher": body.teacher.strip(),
        "date": body.date, "time": body.time, "location": body.location.strip(),
        "notes": body.note.strip(), "group": group, "flex_type": body.flex_type,
    }
    notice = await db.schedule_notify_event(item, "updated")
    await _audit(
        admin, "ویرایش برنامه آموزشی", "Schedules", severity="WARNING",
        target_id=sid, target_type="schedule", target_label=body.lesson.strip(),
        before={"lesson": old.get("lesson"), "date": old.get("date"),
                "time": old.get("time"), "group": old.get("group")},
        after={"lesson": body.lesson.strip(), "date": body.date,
               "time": body.time, "group": group,
               "notified": notice.get("notified", 0)},
        tags=["برنامه", old.get("type", ""), "پنل_وب"],
    )
    return {"ok": True, "notified": notice.get("notified", 0)}


@router.delete("/schedule/{sid}")
async def del_schedule(sid: str, admin=Depends(GLOBAL_USER)):
    old = await db.get_schedule_by_id(sid)
    if not old:
        raise HTTPException(404, "برنامه پیدا نشد")
    _res = await db.delete_schedule(sid)
    if _res is None:              # 🛡 AUDIT-R6 — خطای دیتابیس، نه حذف موفق
        raise HTTPException(status_code=500, detail="حذف انجام نشد — دوباره تلاش کنید")
    notice = await db.schedule_notify_event(old, "cancelled")
    await _audit(
        admin, "حذف و لغو برنامه آموزشی", "Schedules", severity="HIGH",
        target_id=sid, target_type="schedule", target_label=old.get("lesson", ""),
        before={"type": old.get("type"), "date": old.get("date"),
                "time": old.get("time"), "group": old.get("group")},
        after={"deleted": True, "notified": notice.get("notified", 0)},
        tags=["برنامه", "لغو", old.get("type", ""), "پنل_وب"],
    )
    return {"ok": True, "notified": notice.get("notified", 0)}


# ── 🔄 اعلام تغییر زمان کلاس منعطف (flex) ──

@router.get("/schedule/flex")
async def flex_list(admin=Depends(GLOBAL_USER)):
    items = await db.get_schedules(upcoming=True)
    flex = [s for s in items if s.get("flex_type")=="flexible"]
    return {"items":[{"id":str(s["_id"]),"lesson":s.get("lesson",""),"teacher":s.get("teacher",""),
        "date":s.get("date",""),"time":s.get("time",""),"flex_note":s.get("flex_note","")} for s in flex]}

class FlexChange(BaseModel):
    date: str; time: str; note: str=""

@router.post("/schedule/{sid}/flex-change")
async def flex_change(sid: str, body: FlexChange, admin=Depends(GLOBAL_USER)):
    try:
        parse_gregorian_date(body.date)
    except (TimeContractError, ValueError):
        raise HTTPException(422, "فرمت تاریخ YYYY-MM-DD")
    sched = await db.get_schedule_by_id(sid)
    if not sched:
        raise HTTPException(404, "برنامه پیدا نشد")
    ok = await db.update_schedule_time(sid, body.date, body.time, body.note)
    if not ok:
        raise HTTPException(500, "تغییر زمان ذخیره نشد")
    item = {**sched, "date": body.date, "time": body.time,
            "flex_note": body.note}
    notice = await db.schedule_notify_event(item, "time_changed")
    await _audit(
        admin, "اعلام تغییر زمان برنامه", "Schedules", severity="WARNING",
        target_id=sid, target_type="schedule", target_label=sched.get("lesson", ""),
        before={"date": sched.get("date"), "time": sched.get("time")},
        after={"date": body.date, "time": body.time,
               "notified": notice.get("notified", 0)},
        tags=["برنامه", "تغییر_زمان", sched.get("type", ""), "پنل_وب"],
    )
    return {"ok": True, "notified": notice.get("notified", 0)}


@router.get("/faq")
async def faq_list(admin=Depends(get_content_admin_user)):
    docs=await db.faq_get_all()
    return {"items":[{"id":str(d["_id"]),"category":d.get("category","عمومی"),
        "question":d.get("question",""),"answer":d.get("answer","")} for d in docs]}

class FaqCreate(BaseModel):
    category: str="عمومی"; question: str=Field(min_length=5); answer: str=Field(min_length=5)

@router.post("/faq")
async def add_faq(body: FaqCreate, admin=Depends(get_content_admin_user)):
    fid = await db.faq_add(body.question, body.answer, body.category)
    await _audit(admin, "ایجاد پرسش متداول", "Content", severity="INFO",
        target_id=str(fid or ""), target_type="faq", target_label=body.question[:300],
        after={"category": body.category}, tags=["FAQ", "ایجاد", "پنل_وب"])
    return {"ok":True}

@router.delete("/faq/{fid}")
async def del_faq(fid: str, admin=Depends(get_content_admin_user)):
    old = await db.faq_get(fid)
    if not old: raise HTTPException(404, "پرسش متداول پیدا نشد")
    _res = await db.faq_delete(fid)
    if _res is None:              # 🛡 AUDIT-R6 — خطای دیتابیس، نه حذف موفق
        raise HTTPException(status_code=500, detail="حذف انجام نشد — دوباره تلاش کنید")
    await _audit(admin, "حذف پرسش متداول", "Content", severity="HIGH",
        target_id=fid, target_type="faq", target_label=old.get("question", "")[:300],
        before={"category": old.get("category")}, after={"deleted": True},
        tags=["FAQ", "حذف", "پنل_وب"])
    return {"ok":True}

class FaqUpdate(BaseModel):
    category: Optional[str] = Field(default=None, min_length=1, max_length=120)
    question: Optional[str] = Field(default=None, min_length=5, max_length=500)
    answer: Optional[str] = Field(default=None, min_length=5, max_length=5000)

@router.patch("/faq/{fid}")
async def edit_faq(fid: str, body: FaqUpdate, admin=Depends(get_content_admin_user)):
    old = await db.faq_get(fid)
    if not old:
        raise HTTPException(404, "پرسش متداول پیدا نشد")
    payload = body.model_dump(exclude_none=True)
    # strip
    for k in list(payload.keys()):
        if isinstance(payload[k], str):
            payload[k] = payload[k].strip()
            if not payload[k]:
                del payload[k]
    if not payload:
        raise HTTPException(422, "چیزی برای ویرایش نیست")
    ok = await db.faq_update(fid, payload)
    if not ok:
        raise HTTPException(500, "ویرایش انجام نشد")
    await _audit(admin, "ویرایش پرسش متداول", "Content", severity="WARNING",
        target_id=fid, target_type="faq", target_label=payload.get("question", old.get("question",""))[:300],
        before={"question": old.get("question",""), "answer": old.get("answer","")[:300], "category": old.get("category","")},
        after=payload,
        tags=["FAQ", "ویرایش", "پنل_وب"])
    return {"ok": True, "changed": list(payload.keys())}

class GradeBulk(BaseModel):
    entries: List[dict]; lesson: str; exam_title: str; exam_date: str

@router.post("/grades/bulk")
async def bulk_grades(body: GradeBulk, admin=Depends(GLOBAL_USER)):
    from api.routers import academic_admin as academic_api
    try:
        entries = [academic_api.GradeEntry(
            user_id=e.get("user_id", e.get("student_id")), score=e.get("score"))
            for e in body.entries]
        payload = academic_api.GradeBulkCreate(
            entries=entries, lesson=body.lesson,
            exam_title=body.exam_title, exam_date=body.exam_date)
    except Exception as exc:
        raise HTTPException(422, f"داده نمرات نامعتبر است: {exc}")
    return await academic_api.grades_bulk_create(body=payload, admin=admin)

@router.get("/grades/recent")
async def grades_recent(admin=Depends(GLOBAL_USER), skip: int=Query(0), limit: int=Query(30),
                         intake: Optional[str]=Query(None),
                         # 🛡 AUDIT-§۸۲ — این روتر مصرف‌کننده‌ی صفحه‌ی «نمرات» در
                         # مینی‌اپِ ادمین است. پنل وب از academic_admin ترم می‌گیرد
                         # ولی این مسیر پارامتر را نداشت، پس ترم‌بندی از مینی‌اپ
                         # بی‌اثر بود. طولِ ۴۰ و strip دقیقاً مثل academic_admin و
                         # web_admin است تا هر سه لایه یک نرمال‌سازی داشته باشند.
                         term: Optional[str]=Query(None, max_length=40)):
    term = term.strip()[:40] if isinstance(term, str) and term.strip() else None
    items = await db.grade_list_recent(skip=skip, limit=limit, intake=intake, term=term)
    total = await db.grade_count_recent(intake=intake, term=term)
    # اسم دانشجوها رو batch می‌گیریم تا برای هر نمره کوئری جدا نزنیم
    uids = list({g.get("student_id") for g in items if g.get("student_id")})
    names = {}
    for uid in uids:
        u = await db.get_user(uid)
        names[uid] = u.get("name","") if u else f"#{uid}"
    # فهرست ترم‌ها عمداً *فیلترنشده* است تا وقتی ادمین یک ترم را انتخاب کرد
    # بقیه‌ی گزینه‌ها از منو ناپدید نشوند و راه برگشت بسته نشود.
    terms = await db.grade_terms()
    return {"total": total, "terms": terms, "active_term": term,
        "grades":[{"id":str(g["_id"]),"student_id":g.get("student_id"),
        "student_name":names.get(g.get("student_id"),""),"lesson":g.get("lesson",""),
        "exam_title":g.get("exam_title",""),"exam_date":g.get("exam_date",""),
        "term":g.get("term",""),
        "score":g.get("score",0)} for g in items]}

@router.get("/grades/find-student")
async def grades_find_student(name: str = Query(...), admin=Depends(GLOBAL_USER)):
    # FIX جدید: به‌جای تطبیق دقیق نام (find_students_by_name که با کوچیک‌ترین
    # اختلاف تایپی یا سرچ جزئی هیچی برنمی‌گردوند)، حالا از search_users
    # استفاده می‌شه — همون تابع جامعی که توی خود ربات (پنل ادمین، جست‌وجوی
    # اشتراک، AI ادمین) استفاده می‌شه: نام (جزئی)، شماره دانشجویی (جزئی)،
    # یوزرنیم تلگرام با/بدون @ (جزئی)، آیدی عددی تلگرام (دقیق) — همه با یک کوئری.
    results = await db.search_users(name)
    students = [s for s in results if s.get("approved")]
    return {"students":[{"id":s.get("user_id"),"name":s.get("name",""),
        "student_id":s.get("student_id",""),"group":s.get("group","")} for s in students]}

class GradeUpdate(BaseModel):
    score: float = Field(ge=0, le=20)

@router.patch("/grades/{gid}")
async def edit_grade(gid: str, body: GradeUpdate, admin=Depends(GLOBAL_USER)):
    # همان business entry point امنی که Web Admin مصرف می‌کند.
    from api.routers import academic_admin as academic_api
    return await academic_api.grade_update(
        grade_id=gid, body=academic_api.GradeUpdate(score=body.score), admin=admin)

@router.delete("/grades/{gid}")
async def del_grade(gid: str, admin=Depends(GLOBAL_USER)):
    from api.routers import academic_admin as academic_api
    return await academic_api.grade_delete(grade_id=gid, admin=admin)

# ══════════════════════════════════════════════
# 🧬 علوم پایه — ترم‌ها / درس‌ها / جلسات / محتوا
# ══════════════════════════════════════════════

@router.get("/basic-science/terms")
async def bs_terms(admin=Depends(get_content_admin_user)):
    return {"terms": TERMS}

@router.get("/basic-science/lessons")
async def bs_lessons(term: str = Query(...), admin=Depends(get_content_admin_user),
                     intake: Optional[str] = Query(None)):
    iv = resolve_content_intake(admin, intake)
    scope = admin.get("_scope") or {}
    # 🌊 C1.5 — ادمین ورودی خاص: درس‌های سراسری هم با فلگ readonly
    # دیده می‌شوند (§۲۲ spec: Global=هسته‌ی پایه، فقط‌خواندنی)
    if scope.get("kind") == "scoped":
        items = await db.bs_get_lessons(term, intake=[iv, ''])
        # 🛡 C3.1 — «ورودی من» تنها وقتی معنای نوشتن دارد که scope تنظیم شده
        # باشد؛ برای scopedِ بدون-scope همه‌چیز فقط‌خواندنی است (iv='' و
        # own='' نباید با «سطل سراسری مال من است» اشتباه گرفته شود).
        own = scope.get("intake") or ""
        # 🌊 C3 — روی درس سراسری «فقط‌خواندنی» است، ولی می‌تواند جلسه‌ی
        # فقط-ورودی‌خودش را زیرش بسازد ⇒ UI باید دکمه‌ی افزودن را باز بگذارد.
        return {"intake": iv,
            "lessons":[{"id":str(l["_id"]),"name":l.get("name",""),
                        "teacher":l.get("teacher",""),
                        "readonly": not own or (l.get("intake") or '') != own,
                        "can_create_sessions": bool(own) and (l.get("intake") or '') == ''} for l in items]}
    items = await db.bs_get_lessons(term, intake=iv)
    return {"intake": iv,
        "lessons":[{"id":str(l["_id"]),"name":l.get("name",""),"teacher":l.get("teacher",""),
                    "readonly": False} for l in items]}

class BsLessonCreate(BaseModel):
    term: str; name: str = Field(min_length=1); teacher: str = ""; intake: str = ""


class BsLessonUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    teacher: Optional[str] = Field(default=None, max_length=120)


@router.post("/basic-science/lessons")
async def bs_add_lesson_ep(body: BsLessonCreate, admin=Depends(get_content_admin_user)):
    if body.term not in TERMS: raise HTTPException(422, "ترم نامعتبر")
    iv = resolve_content_intake(admin, body.intake)
    await _deny_create_in(iv, admin)
    r = await db.bs_add_lesson(body.term, body.name.strip(), body.teacher.strip(), intake=iv)
    if r is None: raise HTTPException(409, "این درس قبلاً در این ترم ثبت شده")
    await _audit(admin, "ایجاد درس علوم پایه", "Content", severity="INFO",
        target_id=str(r), target_type="lesson", target_label=body.name.strip(),
        after={"term": body.term, "teacher": body.teacher.strip(), "intake": iv},
        tags=["محتوا", "ایجاد_درس", "پنل_وب"])
    return {"ok":True, "id":str(r)}


@router.patch("/basic-science/lessons/{lid}")
async def bs_edit_lesson_ep(lid: str, body: BsLessonUpdate,
                            admin=Depends(get_content_admin_user)):
    old = await db.bs_get_lesson(lid)
    if not old:
        raise HTTPException(404, "درس پیدا نشد")
    await _deny_intake(old.get("intake", ""), admin)
    updates = {}
    if body.name is not None:
        updates["name"] = body.name.strip()
    if body.teacher is not None:
        updates["teacher"] = body.teacher.strip()
    if not updates:
        raise HTTPException(422, "چیزی برای ویرایش نیست")
    ok = await db.bs_update_lesson(lid, updates)
    if not ok:
        raise HTTPException(500, "ویرایش درس انجام نشد")
    await _audit(
        admin, "ویرایش درس علوم پایه", "Content", severity="WARNING",
        target_id=lid, target_type="lesson", target_label=updates.get("name", old.get("name", "")),
        before={k: old.get(k, "") for k in updates}, after=updates,
        tags=["محتوا", "ویرایش_درس", "پنل_وب"],
    )
    return {"ok": True, "changed": list(updates)}


@router.delete("/basic-science/lessons/{lid}")
async def bs_del_lesson_ep(lid: str, admin=Depends(get_content_admin_user)):
    old = await db.bs_get_lesson(lid)
    if not old: raise HTTPException(404, "درس پیدا نشد")
    await _deny_intake(old.get("intake", ""), admin)
    await db.bs_delete_lesson(lid)
    await _audit(admin, "حذف درس علوم پایه", "Content", severity="HIGH",
        target_id=lid, target_type="lesson", target_label=old.get("name", ""),
        before={"term": old.get("term"), "teacher": old.get("teacher"),
                "intake": old.get("intake", "")}, after={"deleted": True},
        tags=["محتوا", "حذف_درس", "پنل_وب"])
    return {"ok":True}

@router.get("/basic-science/lessons/{lid}/sessions")
async def bs_sessions_ep(lid: str, admin=Depends(get_content_admin_user)):
    # 🌊 C1.5 — مشاهده‌ی فقط‌خواندنیِ جلساتِ درسِ سراسری برای scoped
    li = await db.lesson_intake(lid)
    ro = await _read_intake(li, admin)
    scope = admin.get("_scope") or {}
    # 🍴 C2 — نمای مؤثر برای scoped روی درس سراسری: fork خودش جایگزین base
    if ro and scope.get("kind") == "scoped":
        items = await db.bs_get_sessions_effective(
            lid, [scope.get("intake") or '', ''])
    else:
        items = await db.bs_get_sessions(lid)
    # 🌊 C3 — والد قفل است ولی «فرزند ورودی‌خاص» ساختنی است؟
    child = await db.scoped_child_intake(admin["id"], li)
    own_iv = (scope.get("intake") or '') if scope.get("kind") == "scoped" else ''
    next_number = await db.bs_next_session_number(lid, (child or None) if child else None)
    return {"readonly": ro,
        # can_create_own: درس برای این کاربر فقط‌خواندنی است ولی می‌تواند
        # جلسه‌ای که فقط برای ورودی خودش است اضافه کند (§۱۱ گزارش)
        "can_create_own": bool(child not in (None, '')),
        "next_number": next_number,
        "sessions":[{"id":str(s["_id"]),"number":s.get("number",0),"topic":s.get("topic",""),
        "teacher":s.get("teacher",""),
        # 🍴 C2 — متادیتای fork برای رندر دکمه‌های ✂️/↩️ و نشان ⭐ در مینی‌اپ
        "intake":s.get("intake") or "", "is_fork":bool(s.get("fork_of")),
        # 🌊 C3 — own = فرزندِ سطل خودِ کاربر ⇒ بدون فورک هم قابل ویرایش/حذف
        "own": (not bool(s.get("fork_of"))) and bool(own_iv)
                and (s.get("intake") or '') == own_iv} for s in items]}

class BsSessionCreate(BaseModel):
    number: int = Field(ge=1, le=10000)
    topic: str = Field(min_length=1, max_length=200)
    teacher: str = Field(default="", max_length=120)
    # 🌊 C3 — سطل فرزند؛ برای scoped همیشه scope خودش (ورودی کلاینت نادیده)
    intake: Optional[str] = Field(default="", max_length=40)


class BsSessionUpdate(BaseModel):
    number: Optional[int] = Field(default=None, ge=1, le=10000)
    topic: Optional[str] = Field(default=None, min_length=1, max_length=200)
    teacher: Optional[str] = Field(default=None, max_length=120)


@router.post("/basic-science/lessons/{lid}/sessions")
async def bs_add_session_ep(lid: str, body: BsSessionCreate, admin=Depends(get_content_admin_user)):
    li = await db.lesson_intake(lid)
    # 🌊 C3 — دو حالت مجاز:
    #  ۱) والد در scope کاربر است → رفتار قدیمی (فرزند بدون فیلد intake، از والد ارث می‌برد)
    #  ۲) والد 🌐 سراسری و کاربر 📅 است → فرزند در سطل scope خودش؛ والد دست‌نخورده
    child = await db.scoped_child_intake(admin["id"], li)
    if child is None:
        raise HTTPException(403, "intake_out_of_scope")
    if body.intake and (body.intake or '') != (child or ''):
        # body.intake خالی = «همان که سرور تصمیم گرفته» (مسیر عادی کلاینت‌های قدیمی).
        # فقط وقتی intake صریح و *متفاوت* فرستاده شود بحث جعل intake است؛
        # و آن هم تنها برای ادمین ارشد معنا دارد (scoped: scope خودش اجباری است)
        if (admin.get("_scope") or {}).get("kind") != "global":
            raise HTTPException(403, "intake_out_of_scope")
        if body.intake not in await _intakes_active_codes():
            raise HTTPException(422, "کد ورودی نامعتبر است")
        child = body.intake
    sid = await db.bs_add_session(lid, body.number, body.topic.strip(), body.teacher.strip(),
                                  intake=(child or None))
    await _audit(admin, "ایجاد جلسه علوم پایه", "Content", severity="INFO",
        target_id=str(sid), target_type="session",
        target_label=f"جلسه {body.number} — {body.topic.strip()}",
        after={"lesson_id": lid, "number": body.number, "teacher": body.teacher.strip(),
               "intake": child or ""},
        tags=["محتوا", "ایجاد_جلسه", "پنل_وب"] + (["فرزند_ورودی"] if child else []))
    return {"ok":True, "id":sid, "intake": child or ""}


@router.patch("/basic-science/sessions/{sid}")
async def bs_edit_session_ep(sid: str, body: BsSessionUpdate,
                             admin=Depends(get_content_admin_user)):
    old = await db.bs_get_session(sid)
    if not old:
        raise HTTPException(404, "جلسه پیدا نشد")
    await _deny_intake(await db.session_intake(sid), admin)
    updates = {}
    if body.number is not None:
        updates["number"] = body.number
    if body.topic is not None:
        updates["topic"] = body.topic.strip()
    if body.teacher is not None:
        updates["teacher"] = body.teacher.strip()
    if not updates:
        raise HTTPException(422, "چیزی برای ویرایش نیست")
    ok = await db.bs_update_session(sid, updates)
    if not ok:
        raise HTTPException(500, "ویرایش جلسه انجام نشد")
    await _audit(
        admin, "ویرایش جلسه علوم پایه", "Content", severity="WARNING",
        target_id=sid, target_type="session",
        target_label=f"جلسه {updates.get('number', old.get('number',''))} — {updates.get('topic', old.get('topic',''))}",
        before={k: old.get(k, "") for k in updates}, after=updates,
        tags=["محتوا", "ویرایش_جلسه", "پنل_وب"],
    )
    return {"ok": True, "changed": list(updates)}


@router.delete("/basic-science/sessions/{sid}")
async def bs_del_session_ep(sid: str, admin=Depends(get_content_admin_user)):
    old = await db.bs_get_session(sid)
    if not old: raise HTTPException(404, "جلسه پیدا نشد")
    await _deny_intake(await db.session_intake(sid), admin)
    # 🍴 Q1 — حذف baseای که fork دارد ⇒ orphan؛ با 409 مسدود می‌شود
    if await db.bs_session_has_forks(sid):
        raise HTTPException(409,
            "این جلسه نسخه‌ی اختصاصی (fork) دارد؛ ابتدا نسخه‌ها را بازگردانید")
    await db.bs_delete_session(sid)
    await _audit(admin, "حذف جلسه علوم پایه", "Content", severity="HIGH",
        target_id=sid, target_type="session",
        target_label=f"جلسه {old.get('number','')} — {old.get('topic','')}",
        before={"lesson_id": old.get("lesson_id"), "teacher": old.get("teacher")},
        after={"deleted": True}, tags=["محتوا", "حذف_جلسه", "پنل_وب"])
    return {"ok":True}

@router.get("/basic-science/sessions/{sid}/content")
async def bs_content_ep(sid: str, admin=Depends(get_content_admin_user)):
    # 🌊 C1.5 — مشاهده‌ی فقط‌خواندنیِ محتوای جلسه‌ی سراسری برای scoped
    ro = await _read_intake(await db.session_intake(sid), admin)
    items = await db.bs_get_content(sid)
    # 🍴 C2 — نشان نسخه‌ی اختصاصی برای سربرگ مینی‌اپ
    sdoc = await db.bs_get_session(sid) or {}
    def _display(c):
        return c.get("display_file_name") or c.get("display_name") or c.get("original_file_name") or c.get("description") or ""
    return {"readonly": ro, "is_fork": bool(sdoc.get("fork_of")),
        "content":[{"id":str(c["_id"]),"type":c.get("type",""),"description":c.get("description",""),
        "display_name": _display(c), "original_name": c.get("original_file_name",""),
        "file_extension": c.get("file_extension",""), "file_size": c.get("file_size",0),
        "branding_enabled": c.get("branding_enabled", False),
        "extra_info":c.get("extra_info",""),"downloads":c.get("downloads",0)} for c in items]}

@router.post("/basic-science/sessions/{sid}/content")
async def bs_add_content_ep(sid: str, ctype: str = Form(...), description: str = Form(""),
                             extra_info: str = Form(""), display_name: str = Form(""),
                             branding_enabled: bool = Form(False),
                             file: UploadFile = File(...),
                             admin=Depends(get_content_admin_user)):
    if ctype not in CONTENT_TYPES: raise HTTPException(422, "نوع محتوا نامعتبر")
    await _deny_intake(await db.session_intake(sid), admin)
    # File naming pipeline — sanitize + preserve extension
    orig_fname = (file.filename or "file").strip() or "file"
    # Use utility for final name; caller may send display_name empty -> fallback to original
    from utils_file_naming import prepare_rename, get_extension
    # If no display_name provided, use original
    desired = (display_name or "").strip() or orig_fname
    # Resolve final via DB dedup logic later, but need to decide filename to upload
    # Build upload filename as sanitized display (so Telegram stores correct name)
    # We precompute via prepare_rename with existing set (peek)
    existing_for_upload = set()
    try:
        async for d in db.bs_content.find({'session_id': sid}, {'display_name': 1, 'display_file_name': 1}):
            n = d.get('display_file_name') or d.get('display_name') or ''
            if n:
                existing_for_upload.add(n)
    except Exception:
        pass
    prep_for_upload = prepare_rename(desired, orig_fname, existing_names=existing_for_upload, fallback='فایل')
    upload_fname = prep_for_upload['display_name']
    # but preserve original extension if caller provided different one? prepare_rename already does
    logger.info("UPLOAD_REQUEST_RECEIVED route=session_content sid=%s ctype=%s "
                "filename=%s display=%s admin=%s", sid, ctype, orig_fname, upload_fname, admin["id"])
    raw = await _read_capped(file, MAX_UPLOAD_BYTES)
    _validate_magic(raw, file.content_type or "", upload_fname)
    logger.info("FILE_VALIDATED size=%s mime=%s", len(raw),
                file.content_type or "")
    # upload with final sanitized name (single upload, no re-upload needed per spec)
    try:
        file_id = await upload_and_get_file_id(admin["id"], upload_fname, raw,
            file.content_type or "application/octet-stream")
    except Exception as e:
        logger.warning("UPLOAD_FAILED stage=storage route=session_content "
                       "err=%s size=%s", type(e).__name__, len(raw))
        raise HTTPException(502, "آپلود فایل به تلگرام ناموفق بود — "
                                 "جزئیات در لاگ سرور ثبت شد")
    if not file_id: raise HTTPException(502, "آپلود فایل به تلگرام ناموفق بود — "
                                            "جزئیات در لاگ سرور ثبت شد")
    ext_for_db = get_extension(upload_fname)
    cid = await db.bs_add_content(sid, ctype, file_id, description.strip(), extra_info.strip(),
                                   original_name=orig_fname, display_name=upload_fname,
                                   file_extension=ext_for_db,
                                   mime_type=file.content_type or "application/octet-stream",
                                   file_size=len(raw),
                                   branding_enabled=bool(branding_enabled))
    logger.info("UPLOAD_SUCCESS route=session_content sid=%s content_id=%s "
                "size=%s display=%s", sid, cid, len(raw), upload_fname)
    await _audit(admin, "افزودن فایل جلسه", "Content", severity="INFO",
        target_id=str(cid), target_type="content_item",
        target_label=description.strip() or upload_fname,
        after={"session_id": sid, "type": ctype, "display_name": upload_fname,
               "original_name": orig_fname, "branding": bool(branding_enabled)},
        tags=["محتوا", "افزودن_فایل", "پنل_وب"])
    return {"ok":True, "id":str(cid), "display_name": upload_fname}

@router.delete("/basic-science/content/{cid}")
async def bs_del_content_ep(cid: str, admin=Depends(get_content_admin_user)):
    old = await db.bs_get_content_item(cid)
    if not old: raise HTTPException(404, "فایل پیدا نشد")
    await _deny_intake(await db.content_intake(cid), admin)
    _res = await db.bs_delete_content(cid)
    if _res is None:              # 🛡 AUDIT-R6 — خطای دیتابیس، نه حذف موفق
        raise HTTPException(status_code=500, detail="حذف انجام نشد — دوباره تلاش کنید")
    await _audit(admin, "حذف فایل جلسه", "Content", severity="HIGH",
        target_id=cid, target_type="content_item", target_label=old.get("description", ""),
        before={"session_id": old.get("session_id"), "type": old.get("type")},
        after={"deleted": True}, tags=["محتوا", "حذف_فایل", "پنل_وب"])
    return {"ok":True}

class RenameBody(BaseModel):
    new_name: str = Field(min_length=1, max_length=220)

@router.patch("/basic-science/content/{cid}/rename")
async def bs_rename_content_ep(cid: str, body: RenameBody, admin=Depends(get_content_admin_user)):
    old = await db.bs_get_content_item(cid)
    if not old:
        raise HTTPException(404, "فایل پیدا نشد")
    await _deny_intake(await db.content_intake(cid), admin)
    sess_id = old.get("session_id", "")
    # Build sanitized new display via utility (dedup)
    from utils_file_naming import prepare_rename, get_extension
    orig = old.get("original_file_name", "") or old.get("display_file_name", "") or "file.pdf"
    existing = set()
    try:
        async for d in db.bs_content.find({'session_id': sess_id, '_id': {'$ne': old["_id"]}}, {'display_name': 1, 'display_file_name': 1}):
            n = d.get('display_file_name') or d.get('display_name') or ''
            if n:
                existing.add(n)
    except Exception:
        pass
    prep = prepare_rename(body.new_name.strip(), orig, existing_names=existing, fallback='فایل')
    new_display = prep['display_name']
    # Try re-upload to change Telegram filename (best effort). If fails, just DB rename.
    new_file_id = old.get("file_id", "")
    reuploaded = False
    try:
        from api.telegram_send import download_telegram_file, upload_and_get_file_id
        data = await download_telegram_file(old.get("file_id",""))
        if data is not None:
            # need mime
            mime = old.get("mime_type", "application/octet-stream")
            # Re-upload with new name (single upload)
            nf = await upload_and_get_file_id(admin["id"], new_display, data, mime)
            if nf:
                new_file_id = nf
                reuploaded = True
    except Exception as e:
        logger.warning("RENAME_REUPLOAD_FAILED cid=%s err=%s", cid, type(e).__name__)
    await db.bs_content.update_one({'_id': old["_id"]}, {'$set': {
        'display_file_name': new_display,
        'display_name': new_display,
        'file_extension': get_extension(new_display),
        'file_id': new_file_id,
    }})
    await _audit(admin, "تغییر نام فایل جلسه", "Content", severity="WARNING",
        target_id=cid, target_type="content_item",
        target_label=old.get("display_file_name", "") or old.get("description",""),
        before={"display_name": old.get("display_file_name","")}, after={"display_name": new_display, "reuploaded": reuploaded},
        tags=["محتوا", "تغییر_نام", "پنل_وب"])
    return {"ok": True, "display_name": new_display, "reuploaded": reuploaded}

# ══════════════════════════════════════════════
# 📖 رفرنس‌ها — موضوع‌ها / کتاب‌ها / فایل‌ها
# ══════════════════════════════════════════════

@router.get("/references/subjects")
async def ref_subjects_ep(admin=Depends(get_content_admin_user),
                          intake: Optional[str] = Query(None)):
    iv = resolve_content_intake(admin, intake)
    scope = admin.get("_scope") or {}
    # 🌊 C1.5 — ادمین ورودی خاص: موضوعات سراسری هم با فلگ readonly (§۲۲)
    if scope.get("kind") == "scoped":
        items = await db.ref_get_subjects(intake=[iv, ''])
        # 🛡 C3.1 — همان قاعده‌ی bs_lessons: بدون scope تنظیم‌شده همه‌چیز 🔒
        own = scope.get("intake") or ""
        return {"intake": iv,
            "subjects":[{"id":str(s["_id"]),"name":s.get("name",""),
                         "intake": s.get("intake") or "",
                         "readonly": not own or (s.get("intake") or '') != own} for s in items]}
    items = await db.ref_get_subjects(intake=iv)
    return {"intake": iv,
        "subjects":[{"id":str(s["_id"]),"name":s.get("name",""),
                     "intake": s.get("intake") or "", "readonly": False} for s in items]}

class RefSubjectCreate(BaseModel):
    name: str = Field(min_length=1); intake: str = ""


class RefNameUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class ReorderBody(BaseModel):
    direction: str = Field(pattern="^(up|down)$")


@router.post("/references/subjects")
async def ref_add_subject_ep(body: RefSubjectCreate, admin=Depends(get_content_admin_user)):
    iv = resolve_content_intake(admin, body.intake)
    await _deny_create_in(iv, admin)
    r = await db.ref_add_subject(body.name.strip(), intake=iv)
    if r is None: raise HTTPException(409, "این موضوع قبلاً ثبت شده")
    await _audit(admin, "ایجاد موضوع رفرنس", "Content", severity="INFO",
        target_id=str(r), target_type="reference_subject", target_label=body.name.strip(),
        after={"intake": iv}, tags=["رفرنس", "ایجاد", "پنل_وب"])
    return {"ok":True, "id":str(r)}


@router.patch("/references/subjects/{sid}")
async def ref_edit_subject_ep(sid: str, body: RefNameUpdate,
                              admin=Depends(get_content_admin_user)):
    old = await db.ref_get_subject(sid)
    if not old:
        raise HTTPException(404, "موضوع رفرنس پیدا نشد")
    await _deny_intake(old.get("intake", ""), admin)
    name = body.name.strip()
    ok = await db.ref_update_subject(sid, {"name": name})
    if not ok:
        raise HTTPException(500, "ویرایش موضوع انجام نشد")
    await _audit(
        admin, "ویرایش نام موضوع رفرنس", "Content", severity="WARNING",
        target_id=sid, target_type="reference_subject", target_label=name,
        before={"name": old.get("name", "")}, after={"name": name},
        tags=["رفرنس", "ویرایش", "پنل_وب"],
    )
    return {"ok": True}


@router.post("/references/subjects/{sid}/reorder")
async def ref_reorder_subject_ep(sid: str, body: ReorderBody,
                                 admin=Depends(get_content_admin_user)):
    item = await db.ref_get_subject(sid)
    if not item:
        raise HTTPException(404, "موضوع رفرنس پیدا نشد")
    await _deny_intake(item.get("intake", ""), admin)
    fn = db.reorder_up if body.direction == "up" else db.reorder_down
    ok = await fn("ref_subjects", sid, {"intake": item.get("intake") or ""})
    if ok:
        await _audit(
            admin, "تغییر ترتیب موضوع رفرنس", "Content", severity="INFO",
            target_id=sid, target_type="reference_subject",
            target_label=item.get("name", ""), after={"direction": body.direction},
            tags=["رفرنس", "ترتیب", "پنل_وب"],
        )
    return {"ok": bool(ok)}


@router.delete("/references/subjects/{sid}")
async def ref_del_subject_ep(sid: str, admin=Depends(get_content_admin_user)):
    old = await db.ref_get_subject(sid)
    if not old: raise HTTPException(404, "موضوع رفرنس پیدا نشد")
    await _deny_intake(old.get("intake", ""), admin)
    await db.ref_delete_subject(sid)
    await _audit(admin, "حذف موضوع رفرنس", "Content", severity="HIGH",
        target_id=sid, target_type="reference_subject", target_label=old.get("name", ""),
        before={"intake": old.get("intake", "")}, after={"deleted": True},
        tags=["رفرنس", "حذف", "پنل_وب"])
    return {"ok":True}

@router.get("/references/subjects/{sid}/books")
async def ref_books_ep(sid: str, admin=Depends(get_content_admin_user)):
    # 🌊 C1.5 — مشاهده‌ی فقط‌خواندنیِ کتاب‌های موضوع سراسری برای scoped
    _si = await db.ref_subject_intake(sid)
    ro = await _read_intake(_si, admin)
    scope = admin.get("_scope") or {}
    # 🍴 C2 — نمای مؤثر برای scoped روی موضوع سراسری: fork جایگزین base
    if ro and scope.get("kind") == "scoped":
        items = await db.ref_get_books_effective(
            sid, [scope.get("intake") or '', ''])
    else:
        items = await db.ref_get_books(sid)
    # 🌊 C3 — والد قفل است ولی «فرزند ورودی‌خاص» ساختنی است؟
    child = await db.scoped_child_intake(admin["id"], _si)
    own_iv = (scope.get("intake") or '') if scope.get("kind") == "scoped" else ''
    return {"readonly": ro,
        # can_create_own: موضوع فقط‌خواندنی است ولی کاربر می‌تواند کتابی که
        # فقط برای ورودی خودش است اضافه کند (قرارداد هم‌نامِ bs_sessions_ep)
        "can_create_own": bool(child not in (None, '')),
        "books":[{"id":str(b["_id"]),"name":b.get("name",""),
        "intake":b.get("intake") or "", "is_fork":bool(b.get("fork_of")),
        # 🌊 C3 — own = فرزندِ سطل خودِ کاربر ⇒ بدون فورک هم قابل ویرایش/حذف
        "own": (not bool(b.get("fork_of"))) and bool(own_iv)
                and (b.get("intake") or '') == own_iv} for b in items]}

class RefBookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # 🌊 C3 — سطل فرزند؛ برای scoped همیشه scope خودش (ورودی کلاینت نادیده)
    intake: Optional[str] = Field(default="", max_length=40)

@router.post("/references/subjects/{sid}/books")
async def ref_add_book_ep(sid: str, body: RefBookCreate, admin=Depends(get_content_admin_user)):
    # 🌊 C3 — دو حالت مجاز (قرارداد bs_add_session_ep):
    #  ۱) والد در scope کاربر → رفتار قدیمی: فرزند بدون فیلد intake، از والد ارث می‌برد
    #  ۲) والد 🌐 و کاربر 📅 → فرزند در سطل scope خودش؛ والد دست‌نخورده
    _si = await db.ref_subject_intake(sid)
    child = await db.scoped_child_intake(admin["id"], _si)
    if child is None:
        raise HTTPException(403, "intake_out_of_scope")
    if body.intake and (body.intake or '') != (child or ''):
        # intake خالی = «همان که سرور تصمیم گرفته»؛ صریح و متفاوت = جعل intake،
        # که فقط برای ادمین ارشد معنا دارد
        if (admin.get("_scope") or {}).get("kind") != "global":
            raise HTTPException(403, "intake_out_of_scope")
        if body.intake not in await _intakes_active_codes():
            raise HTTPException(422, "کد ورودی نامعتبر است")
        child = body.intake
    r = await db.ref_add_book(sid, body.name.strip(), intake=(child or None))
    await _audit(admin, "ایجاد کتاب رفرنس", "Content", severity="INFO",
        target_id=str(r), target_type="reference_book", target_label=body.name.strip(),
        after={"subject_id": sid, "intake": child or ""},
        tags=["رفرنس", "ایجاد", "پنل_وب"] + (["فرزند_ورودی"] if child else []))
    return {"ok":True, "id":str(r), "intake": child or ""}


@router.patch("/references/books/{bid}")
async def ref_edit_book_ep(bid: str, body: RefNameUpdate,
                           admin=Depends(get_content_admin_user)):
    old = await db.ref_get_book(bid)
    if not old:
        raise HTTPException(404, "کتاب رفرنس پیدا نشد")
    await _deny_intake(await db.ref_book_intake(bid), admin)
    name = body.name.strip()
    ok = await db.ref_update_book(bid, {"name": name})
    if not ok:
        raise HTTPException(500, "ویرایش کتاب انجام نشد")
    await _audit(
        admin, "ویرایش نام کتاب رفرنس", "Content", severity="WARNING",
        target_id=bid, target_type="reference_book", target_label=name,
        before={"name": old.get("name", "")}, after={"name": name},
        tags=["رفرنس", "ویرایش", "پنل_وب"],
    )
    return {"ok": True}


@router.post("/references/books/{bid}/reorder")
async def ref_reorder_book_ep(bid: str, body: ReorderBody,
                              admin=Depends(get_content_admin_user)):
    item = await db.ref_get_book(bid)
    if not item:
        raise HTTPException(404, "کتاب رفرنس پیدا نشد")
    await _deny_intake(await db.ref_book_intake(bid), admin)
    fn = db.reorder_up if body.direction == "up" else db.reorder_down
    # 🌊 C3 — قانون «هم‌سطل» به db منتقل شد تا ربات و وب یک رفتار داشته باشند
    ok = await fn("ref_books", bid, db.ref_books_order_filter(item))
    if ok:
        await _audit(
            admin, "تغییر ترتیب کتاب رفرنس", "Content", severity="INFO",
            target_id=bid, target_type="reference_book",
            target_label=item.get("name", ""), after={"direction": body.direction},
            tags=["رفرنس", "ترتیب", "پنل_وب"],
        )
    return {"ok": bool(ok)}


@router.delete("/references/books/{bid}")
async def ref_del_book_ep(bid: str, admin=Depends(get_content_admin_user)):
    old = await db.ref_get_book(bid)
    if not old: raise HTTPException(404, "کتاب رفرنس پیدا نشد")
    await _deny_intake(await db.ref_book_intake(bid), admin)
    # 🍴 Q1 — حذف کتابی که fork دارد ⇒ orphan؛ با 409 مسدود می‌شود
    if await db.ref_book_has_forks(bid):
        raise HTTPException(409,
            "این کتاب نسخه‌ی اختصاصی (fork) دارد؛ ابتدا نسخه‌ها را بازگردانید")
    await db.ref_delete_book(bid)
    await _audit(admin, "حذف کتاب رفرنس", "Content", severity="HIGH",
        target_id=bid, target_type="reference_book", target_label=old.get("name", ""),
        before={"subject_id": old.get("subject_id")}, after={"deleted": True},
        tags=["رفرنس", "حذف", "پنل_وب"])
    return {"ok":True}

@router.get("/references/books/{bid}/files")
async def ref_files_ep(bid: str, skip: int = Query(0, ge=0),
                       limit: int = Query(50, ge=1, le=100),
                       admin=Depends(get_content_admin_user)):
    # 🌊 C1.5 — مشاهده‌ی فقط‌خواندنیِ فایل‌های کتاب سراسری برای scoped
    ro = await _read_intake(await db.ref_book_intake(bid), admin)
    items, total = await db.ref_get_files_page(bid, skip=skip, limit=limit)
    # 🍴 C2 — نشان نسخه‌ی اختصاصی برای سربرگ مینی‌اپ
    bdoc = await db.ref_get_book(bid) or {}
    def _disp(f):
        return f.get("display_file_name") or f.get("display_name") or f.get("original_file_name") or f.get("description") or ""
    return {"readonly": ro, "is_fork": bool(bdoc.get("fork_of")),
        "total": total, "skip": skip, "limit": limit,
        "has_more": skip + len(items) < total,
        "files":[{"id":str(f["_id"]),"lang":f.get("lang","fa"),"volume":f.get("volume",1),
        "description":f.get("description",""),"display_name": _disp(f),
        "original_name": f.get("original_file_name",""),"file_extension": f.get("file_extension",""),
        "downloads":f.get("downloads",0)} for f in items]}

@router.post("/references/books/{bid}/files")
async def ref_add_file_ep(bid: str, lang: str = Form("fa"), volume: int = Form(1),
                           description: str = Form(""), display_name: str = Form(""),
                           branding_enabled: bool = Form(False),
                           file: UploadFile = File(...),
                           admin=Depends(get_content_admin_user)):
    if lang not in ("fa","en"): raise HTTPException(422, "زبان نامعتبر")
    await _deny_intake(await db.ref_book_intake(bid), admin)
    orig_fname = (file.filename or "file").strip() or "file"
    from utils_file_naming import prepare_rename, get_extension
    desired = (display_name or "").strip() or orig_fname
    existing_for_upload = set()
    try:
        async for d in db.ref_files.find({'book_id': bid}, {'display_name': 1, 'display_file_name': 1}):
            n = d.get('display_file_name') or d.get('display_name') or ''
            if n:
                existing_for_upload.add(n)
    except Exception:
        pass
    prep = prepare_rename(desired, orig_fname, existing_names=existing_for_upload, fallback='فایل')
    upload_fname = prep['display_name']
    logger.info("UPLOAD_REQUEST_RECEIVED route=ref_file bid=%s filename=%s display=%s "
                "admin=%s", bid, orig_fname, upload_fname, admin["id"])
    raw = await _read_capped(file, MAX_UPLOAD_BYTES)
    _validate_magic(raw, file.content_type or "", upload_fname)
    try:
        file_id = await upload_and_get_file_id(admin["id"], upload_fname, raw,
            file.content_type or "application/octet-stream")
    except Exception as e:
        logger.warning("UPLOAD_FAILED stage=storage route=ref_file "
                       "err=%s size=%s", type(e).__name__, len(raw))
        raise HTTPException(502, "آپلود فایل به تلگرام ناموفق بود — "
                                 "جزئیات در لاگ سرور ثبت شد")
    if not file_id: raise HTTPException(502, "آپلود فایل به تلگرام ناموفق بود — "
                                            "جزئیات در لاگ سرور ثبت شد")
    ext_for_db = get_extension(upload_fname)
    fid = await db.ref_add_file(bid, lang, file_id, volume, description.strip(),
                                original_name=orig_fname, display_name=upload_fname,
                                file_extension=ext_for_db,
                                mime_type=file.content_type or "application/octet-stream",
                                file_size=len(raw), branding_enabled=bool(branding_enabled))
    logger.info("UPLOAD_SUCCESS route=ref_file bid=%s file_id=%s size=%s display=%s",
                bid, fid, len(raw), upload_fname)
    await _audit(admin, "افزودن فایل رفرنس", "Content", severity="INFO",
        target_id=str(fid), target_type="reference_file",
        target_label=description.strip() or upload_fname,
        after={"book_id": bid, "lang": lang, "volume": volume, "display_name": upload_fname,
               "original_name": orig_fname, "branding": bool(branding_enabled)},
        tags=["رفرنس", "افزودن_فایل", "پنل_وب"])
    return {"ok":True, "id":fid, "display_name": upload_fname}

@router.delete("/references/files/{fid}")
async def ref_del_file_ep(fid: str, admin=Depends(get_content_admin_user)):
    old = await db.ref_get_file(fid)
    if not old: raise HTTPException(404, "فایل رفرنس پیدا نشد")
    await _deny_intake(await db.ref_file_intake(fid), admin)
    await db.ref_delete_file(fid)
    await _audit(admin, "حذف فایل رفرنس", "Content", severity="HIGH",
        target_id=fid, target_type="reference_file", target_label=old.get("description", ""),
        before={"book_id": old.get("book_id"), "lang": old.get("lang"),
                "volume": old.get("volume")}, after={"deleted": True},
        tags=["رفرنس", "حذف_فایل", "پنل_وب"])
    return {"ok":True}

@router.patch("/references/files/{fid}/rename")
async def ref_rename_file_ep(fid: str, body: RenameBody, admin=Depends(get_content_admin_user)):
    old = await db.ref_get_file(fid)
    if not old:
        raise HTTPException(404, "فایل رفرنس پیدا نشد")
    await _deny_intake(await db.ref_file_intake(fid), admin)
    book_id = old.get("book_id", "")
    from utils_file_naming import prepare_rename, get_extension
    orig = old.get("original_file_name", "") or old.get("display_file_name", "") or "file.pdf"
    existing = set()
    try:
        async for d in db.ref_files.find({'book_id': book_id, '_id': {'$ne': old["_id"]}}, {'display_name': 1, 'display_file_name': 1}):
            n = d.get('display_file_name') or d.get('display_name') or ''
            if n:
                existing.add(n)
    except Exception:
        pass
    prep = prepare_rename(body.new_name.strip(), orig, existing_names=existing, fallback='فایل')
    new_display = prep['display_name']
    new_file_id = old.get("file_id", "")
    reuploaded = False
    try:
        from api.telegram_send import download_telegram_file, upload_and_get_file_id
        data = await download_telegram_file(old.get("file_id",""))
        if data is not None:
            mime = old.get("mime_type", "application/octet-stream")
            nf = await upload_and_get_file_id(admin["id"], new_display, data, mime)
            if nf:
                new_file_id = nf
                reuploaded = True
    except Exception as e:
        logger.warning("RENAME_REUPLOAD_FAILED fid=%s err=%s", fid, type(e).__name__)
    await db.ref_files.update_one({'_id': old["_id"]}, {'$set': {
        'display_file_name': new_display,
        'display_name': new_display,
        'file_extension': get_extension(new_display),
        'file_id': new_file_id,
    }})
    await _audit(admin, "تغییر نام فایل رفرنس", "Content", severity="WARNING",
        target_id=fid, target_type="reference_file",
        target_label=old.get("display_file_name","") or old.get("description",""),
        before={"display_name": old.get("display_file_name","")}, after={"display_name": new_display, "reuploaded": reuploaded},
        tags=["رفرنس", "تغییر_نام", "پنل_وب"])
    return {"ok": True, "display_name": new_display, "reuploaded": reuploaded}

# ══════════════════════════════════════════════
# 🍴 موج C2 — Fork/Unfork (سفارشی‌سازی سراسری برای یک ورودی)
# قواعد: فقط آیتم «سراسری» fork می‌شود؛ هدف = scope خود ادمینِ
# ورودی‌خاص یا ctx انتخابیِ ادمین ارشد؛ سربار دانلود/اعلان صفر است
# (کپی با downloads=0 و notif_sent=True — بدون دوباره‌اعلانی).
# ══════════════════════════════════════════════

async def _fork_target(admin, requested):
    """هدف fork: ادمین ورودی‌خاص → scope خودش؛ ادمین ارشد → ورودی درخواستی."""
    scope = admin.get("_scope") or {}
    if scope.get("kind") == "scoped":
        return scope.get("intake") or ''
    # فقط رشته‌ی واقعی intake معتبر است (فراخوانی بدون پارامتر ⇒ سطل سراسری)
    if not isinstance(requested, str):
        requested = None
    return resolve_content_intake(admin, requested) or ''

async def _intakes_active_codes() -> list:
    items = await db.get_all_intakes()
    return [i["code"] for i in items if i.get("active", True)]

@router.post("/basic-science/sessions/{sid}/fork")
async def bs_fork_session_ep(sid: str, admin=Depends(get_content_admin_user),
                             intake: Optional[str] = Query(None)):
    target = await _fork_target(admin, intake)
    if not target:
        raise HTTPException(422,
            "سفارشی‌سازی روی سطل سراسری معنا ندارد؛ ابتدا یک ورودی را انتخاب کنید")
    # 🌊 C3 — فورک فقط روی «پایه‌ی سراسری» معنا دارد؛ اگر جلسه خودش فرزندِ
    # یک ورودی است (fork_of ندارد ولی intake دارد) پیام دقیق می‌دهیم —
    # قبلاً 422 گمراه‌کننده‌ی «پایه یافت نشد» برمی‌گشت.
    if await db.session_intake(sid) != '':
        raise HTTPException(409,
            "این جلسه نسخه‌ی سراسری نیست؛ همان را مستقیماً ویرایش کنید")
    new_sid = await db.bs_fork_session(sid, target)
    if not new_sid:
        raise HTTPException(422, "فقط جلسه‌ی سراسری قابل سفارشی‌سازی است")
    try:
        from api.routers.admin_panel import _audit
        _docs = await db.get_all_intakes()
        _lbl = next((i["label"] for i in _docs if i["code"] == target), target)
        _base = await db.bs_get_session(sid) or {}
        await _audit(admin, "ساخت نسخه‌ی اختصاصی (Fork) جلسه", "Content",
            severity="INFO", target_id=str(sid), target_type="session",
            target_label=_base.get("topic", ""),
            details=f"🍴 Fork Session\n🏷 ورودی: {_lbl}", tags=["فورک_محتوا"])
    except Exception:
        pass
    return {"ok":True, "fork_id":new_sid}

@router.delete("/basic-science/sessions/{sid}/fork")
async def bs_unfork_session_ep(sid: str, admin=Depends(get_content_admin_user)):
    _fi = await db.session_intake(sid)
    await _deny_intake(_fi, admin)
    base_id = await db.bs_unfork_session(sid)
    if not base_id:
        raise HTTPException(422, "این جلسه نسخه‌ی اختصاصی نیست")
    try:
        from api.routers.admin_panel import _audit
        await _audit(admin, "بازگردانی جلسه به نسخه‌ی سراسری (حذف Fork)",
            "Content", severity="INFO", target_id=str(sid),
            target_type="session",
            details=f"↩️ Unfork Session\n🏷 ورودی: {_fi or 'سراسری'}",
            tags=["فورک_محتوا"])
    except Exception:
        pass
    return {"ok":True, "base_id":base_id}

@router.post("/references/books/{bid}/fork")
async def ref_fork_book_ep(bid: str, admin=Depends(get_content_admin_user),
                           intake: Optional[str] = Query(None)):
    target = await _fork_target(admin, intake)
    if not target:
        raise HTTPException(422,
            "سفارشی‌سازی روی سطل سراسری معنا ندارد؛ ابتدا یک ورودی را انتخاب کنید")
    # 🌊 C3 — فورک فقط روی «پایه‌ی سراسری» معنا دارد (همان قاعده‌ی جلسات)
    if await db.ref_book_intake(bid) != '':
        raise HTTPException(409,
            "این کتاب نسخه‌ی سراسری نیست؛ همان را مستقیماً ویرایش کنید")
    new_bid = await db.ref_fork_book(bid, target)
    if not new_bid:
        raise HTTPException(422, "فقط کتاب سراسری قابل سفارشی‌سازی است")
    try:
        from api.routers.admin_panel import _audit
        _docs = await db.get_all_intakes()
        _lbl = next((i["label"] for i in _docs if i["code"] == target), target)
        _base = await db.ref_get_book(bid) or {}
        await _audit(admin, "ساخت نسخه‌ی اختصاصی (Fork) کتاب", "Content",
            severity="INFO", target_id=str(bid), target_type="book",
            target_label=_base.get("name", ""),
            details=f"🍴 Fork Book\n🏷 ورودی: {_lbl}", tags=["فورک_محتوا"])
    except Exception:
        pass
    return {"ok":True, "fork_id":new_bid}

@router.delete("/references/books/{bid}/fork")
async def ref_unfork_book_ep(bid: str, admin=Depends(get_content_admin_user)):
    _fi = await db.ref_book_intake(bid)
    await _deny_intake(_fi, admin)
    base_id = await db.ref_unfork_book(bid)
    if not base_id:
        raise HTTPException(422, "این کتاب نسخه‌ی اختصاصی نیست")
    try:
        from api.routers.admin_panel import _audit
        await _audit(admin, "بازگردانی کتاب به نسخه‌ی سراسری (حذف Fork)",
            "Content", severity="INFO", target_id=str(bid),
            target_type="book",
            details=f"↩️ Unfork Book\n🏷 ورودی: {_fi or 'سراسری'}",
            tags=["فورک_محتوا"])
    except Exception:
        pass
    return {"ok":True, "base_id":base_id}

# ══════════════════════════════════════════════
# 📦 ابزار Move — بازتخصیص آیتم‌های قدیمیِ سراسری به یک ورودی
# (فقط ادمین ارشد؛ anti-duplicate در لایه‌ی DB: 409 همنام)
# ══════════════════════════════════════════════

class MoveBody(BaseModel):
    intake: str = ""

@router.post("/basic-science/lessons/{lid}/move")
async def bs_move_lesson_ep(lid: str, body: MoveBody, admin=Depends(GLOBAL_USER)):
    iv = body.intake or ''
    if iv and iv not in (await _intakes_active_codes()):
        raise HTTPException(422, "کد ورودی نامعتبر است")
    source = await db.bs_get_lesson(lid)
    status, info = await db.bs_move_lesson_intake(lid, iv)
    if status == 'err':
        if info == 'not_found': raise HTTPException(404, "درس یافت نشد")
        duplicate = await db.bs_lessons.find_one({
            'term': (source or {}).get('term', ''), 'name': (source or {}).get('name', ''),
            'intake': iv, '_id': {'$ne': (source or {}).get('_id')}})
        raise HTTPException(409, {"code": "duplicate_name", "object": (source or {}).get('name', ''),
            "destination": iv or "global", "existing_id": str((duplicate or {}).get('_id', '')),
            "reason": "درسی با همین نام در سطل مقصد موجود است"})
    try:
        await _audit(admin, "انتقال درس به سطل ورودی", "Content",
            severity="HIGH", target_id=str(lid), target_type="lesson",
            details=f"📦 Move Lesson: {info or 'سراسری'} → {iv or 'سراسری'}",
            tags=["فورک_محتوا"])
    except Exception:
        await db.bs_move_lesson_intake(lid, info or '')
        raise HTTPException(503, "ثبت حسابرسی ناموفق بود؛ انتقال بازگردانده شد")
    return {"ok":True, "from":info, "to":iv}

@router.post("/references/subjects/{sid}/move")
async def ref_move_subject_ep(sid: str, body: MoveBody, admin=Depends(GLOBAL_USER)):
    iv = body.intake or ''
    if iv and iv not in (await _intakes_active_codes()):
        raise HTTPException(422, "کد ورودی نامعتبر است")
    source = await db.ref_get_subject(sid)
    status, info = await db.ref_move_subject_intake(sid, iv)
    if status == 'err':
        if info == 'not_found': raise HTTPException(404, "موضوع یافت نشد")
        duplicate = await db.ref_subjects.find_one({
            'name': (source or {}).get('name', ''), 'intake': iv,
            '_id': {'$ne': (source or {}).get('_id')}})
        raise HTTPException(409, {"code": "duplicate_name", "object": (source or {}).get('name', ''),
            "destination": iv or "global", "existing_id": str((duplicate or {}).get('_id', '')),
            "reason": "موضوعی با همین نام در سطل مقصد موجود است"})
    try:
        await _audit(admin, "انتقال موضوع به سطل ورودی", "Content",
            severity="HIGH", target_id=str(sid), target_type="subject",
            details=f"📦 Move Subject: {info or 'سراسری'} → {iv or 'سراسری'}",
            tags=["فورک_محتوا"])
    except Exception:
        await db.ref_move_subject_intake(sid, info or '')
        raise HTTPException(503, "ثبت حسابرسی ناموفق بود؛ انتقال بازگردانده شد")
    return {"ok":True, "from":info, "to":iv}

# QBank file manager (additive compatibility API for the existing Mini App).
# The files are stored as Telegram file_ids; question records remain the
# canonical structured Question Bank source of truth.

def _qbank_file_response(item: dict, *, readonly: bool = False) -> dict:
    return {
        "id": str(item.get("_id", "")),
        "lesson": item.get("lesson", ""),
        "topic": item.get("topic", ""),
        "description": item.get("description", ""),
        "filename": item.get("filename", ""),
        "mime_type": item.get("mime_type", ""),
        "size": int(item.get("size", 0) or 0),
        "file_type": item.get("file_type", "document"),
        "downloads": int(item.get("downloads", 0) or 0),
        "upload_date": item.get("created_at", ""),
        "readonly": readonly,
    }


@router.get("/qbank/files")
async def qbank_files_list(
    intake: Optional[str] = Query(None, max_length=50),
    admin=Depends(get_content_admin_user),
):
    scope = admin.get("_scope") or {}
    if scope.get("kind") == "scoped":
        own = resolve_content_intake(admin, intake)
        own_items = await db.qbank_file_list(own)
        # Scoped users may read global material but never mutate it.
        global_items = [] if own == "" else await db.qbank_file_list("")
        items = [
            *[_qbank_file_response(item, readonly=False) for item in own_items],
            *[_qbank_file_response(item, readonly=True) for item in global_items],
        ]
    else:
        target = resolve_content_intake(admin, intake)
        items = [_qbank_file_response(item) for item in await db.qbank_file_list(target)]
    return {"files": items}


@router.get("/qbank/files/{file_id}")
async def qbank_file_detail(file_id: str, admin=Depends(get_content_admin_user)):
    item = await db.qbank_file_get(file_id)
    if not item:
        raise HTTPException(404, "فایل پیدا نشد")
    scope = admin.get("_scope") or {}
    item_intake = item.get("intake") or ""
    if scope.get("kind") == "scoped" and item_intake not in ("", scope.get("intake")):
        raise HTTPException(403, "intake_out_of_scope")
    return {"file": _qbank_file_response(item, readonly=scope.get("kind") == "scoped" and item_intake == "")}


@router.post("/qbank/files")
async def qbank_file_upload(
    lesson: str = Form(..., min_length=2, max_length=100),
    topic: str = Form(..., min_length=2, max_length=100),
    description: str = Form("", max_length=500),
    intake: Optional[str] = Form(None, max_length=50),
    file: UploadFile = File(...),
    admin=Depends(get_content_admin_user),
):
    target = resolve_content_intake(admin, intake)
    if target and target not in await _intakes_active_codes():
        raise HTTPException(422, "کد ورودی نامعتبر است")
    if not await db.can_access_intake(admin["id"], target):
        raise HTTPException(403, "intake_out_of_scope")
    raw = await _read_capped(file, 50 * 1024 * 1024)
    _validate_magic(raw, file.content_type or "", file.filename or "")
    if not raw:
        raise HTTPException(413, "حجم فایل باید بین ۱ بایت و ۵۰ مگابایت باشد")
    telegram_file_id = await upload_and_get_file_id(
        admin["id"], file.filename or "file", raw,
        file.content_type or "application/octet-stream")
    if not telegram_file_id:
        raise HTTPException(503, "آپلود فایل به تلگرام انجام نشد")
    item = await db.qbank_file_add(
        intake=target, lesson=lesson, topic=topic, description=description,
        filename=file.filename or "file", mime_type=file.content_type or "application/octet-stream",
        size=len(raw), telegram_file_id=telegram_file_id, uploaded_by=admin["id"],
    )
    try:
        await _audit(
            admin, "آپلود فایل بانک سؤال", "QuestionBank", severity="INFO",
            target_id=str(item["_id"]), target_type="qbank_file",
            target_label=f"{lesson} — {topic}",
            after={"intake": target, "filename": item["filename"], "size": len(raw)},
            tags=["بانک_سؤال", "آپلود", "پنل_وب"],
        )
    except Exception:
        # The Telegram upload already succeeded, so compensate the metadata
        # write when the mandatory durable audit is unavailable.
        await db.qbank_file_delete(str(item["_id"]))
        raise
    return {"ok": True, "file": _qbank_file_response(item)}


@router.delete("/qbank/files/{file_id}")
async def qbank_file_remove(file_id: str, admin=Depends(get_content_admin_user)):
    item = await db.qbank_file_get(file_id)
    if not item:
        raise HTTPException(404, "فایل پیدا نشد")
    await _deny_intake(item.get("intake", ""), admin)
    if not await db.qbank_file_delete(file_id):
        raise HTTPException(500, "حذف فایل انجام نشد")
    try:
        await _audit(
            admin, "حذف فایل بانک سؤال", "QuestionBank", severity="HIGH",
            target_id=file_id, target_type="qbank_file", target_label=item.get("filename", ""),
            before={"intake": item.get("intake", ""), "filename": item.get("filename", "")},
            after={"deleted": True}, tags=["بانک_سؤال", "حذف", "پنل_وب"],
        )
    except Exception:
        # Compensate the destructive mutation if its audit record cannot be
        # persisted. The original _id is restored to keep links stable.
        await db.qbank_files.insert_one(item)
        raise
    return {"ok": True}


# Legacy structured-question import remains retired; QBank file metadata above
# is kept only for the existing Mini App file-manager compatibility contract.

# ══════════════════════════════════════════════
# 🚩 گزارش‌های ایراد (سوال/جزوه)
# ══════════════════════════════════════════════

@router.get("/reports/stats")
async def reports_stats_ep(admin=Depends(GLOBAL_USER)):
    return await db.content_reports_stats()

@router.get("/reports")
async def reports_list_ep(
    status: Optional[str] = Query(None), skip: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100), admin=Depends(GLOBAL_USER),
):
    if status and status not in ("new", "reviewing", "resolved", "rejected"):
        raise HTTPException(422, "وضعیت نامعتبر")
    items = await db.get_content_reports(status=status, skip=skip, limit=limit)
    total = await db.content_reports_count(status=status)
    REASON_FA = {'wrong_answer':'پاسخ اشتباه','unclear':'گنگ/نامفهوم','duplicate':'تکراری',
        'broken_file':'فایل خراب','outdated':'محتوای قدیمی','other':'سایر'}
    return {"total": total, "skip": skip, "limit": limit,
        "reports":[{"id":r.get("report_id"),"target_type":r.get("target_type",""),
        "target_id":r.get("target_id",""),"reporter_name":r.get("reporter_name",""),
        "reason":REASON_FA.get(r.get("reason",""), r.get("reason","")),"note":r.get("note",""),
        "status":r.get("status","new"),"created_at":r.get("created_at") or None,
        "resolved_at":r.get("resolved_at") or None} for r in items]}

class ReportStatusUpdate(BaseModel):
    status: str

@router.post("/reports/{rid}/status")
async def report_status_ep(rid: int, body: ReportStatusUpdate, admin=Depends(GLOBAL_USER)):
    if body.status not in ("new","reviewing","resolved","rejected"): raise HTTPException(422,"وضعیت نامعتبر")
    r = await db.get_content_report(rid)
    if not r: raise HTTPException(404)
    old_status = r.get("status", "new")
    await db.update_report_status(rid, body.status, resolved_by=admin["id"])
    await _audit(
        admin, "تغییر وضعیت گزارش محتوا", "Reports", severity="WARNING",
        target_id=str(rid), target_type="content_report",
        target_label=f"{r.get('target_type','')} · {r.get('reason','')}"[:300],
        before={"status": old_status}, after={"status": body.status},
        tags=["گزارش_محتوا", "بازبینی", "پنل_وب"],
    )
    return {"ok":True}
