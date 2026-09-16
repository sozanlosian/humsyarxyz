# -*- coding: utf-8 -*-
"""📥 URL-Import — روتر درون‌ریزی محتوای راه‌دور.

تنها سطح API برای پایپ‌لاین (§106): وب‌ادمین، مینی‌اپ و بات هر سه به
همین endpointها وصل می‌شوند؛ منطق فقط در url_import_service است.
RBAC: همان get_content_admin_user (global/scoped) — مجوز جدید نداریم
(§55). bs/ref فقط global؛ qbank برای scoped با intake خودش."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional

from api.auth import get_content_admin_user, resolve_content_intake
from api.routers.admin_panel import _audit
from database import db
from api.rate_limit import rate_limit_user  # 🛡 W3/SEC-03
import url_import_service as svc

logger = logging.getLogger("url_import")

router = APIRouter()

CONTENT_TYPES = ['video', 'ppt', 'pdf', 'note', 'test', 'voice']


class ImportCreateBody(BaseModel):
    url: str = Field(..., max_length=2048)
    kind: str = Field("qbank")
    target_id: str = Field("", max_length=64)
    intake: Optional[str] = Field(None, max_length=50)
    lesson: str = Field("", max_length=100)
    topic: str = Field("", max_length=100)
    description: str = Field("", max_length=500)
    extra_info: str = Field("", max_length=300)
    ctype: str = Field("", max_length=16)
    lang: str = Field("fa", max_length=4)
    volume: int = Field(1, ge=1, le=500)
    filename: str = Field("", max_length=180)
    idem: str = Field("", max_length=80)


class RetryBody(BaseModel):
    force: bool = False


def _shape(doc: dict) -> dict:
    return {
        "id": str(doc.get("_id", "")),
        "admin_id": doc.get("admin_id"),
        "kind": doc.get("kind"),
        "target_id": doc.get("target_id", ""),
        "intake": doc.get("intake", ""),
        "meta": doc.get("meta") or {},
        "url_safe": doc.get("url_safe", ""),
        "status": doc.get("status"),
        "progress": doc.get("progress") or {},
        "sha256": doc.get("sha256"),
        "size": doc.get("size"),
        "filename": doc.get("filename"),
        "mime": doc.get("mime"),
        "telegram_file_id": bool(doc.get("telegram_file_id")),
        "content_id": doc.get("content_id"),
        "error": doc.get("error"),
        "retries": doc.get("retries", 0),
        "duplicate_of": doc.get("duplicate_of"),
        "timeline": (doc.get("timeline") or [])[-12:],
        "created_at": doc.get("created_at"),
        "finished_at": doc.get("finished_at"),
    }


@router.post("/url-import/jobs")
async def create_job(body: ImportCreateBody,
                     admin=Depends(get_content_admin_user)):
    """ساخت job درون‌ریزی — پاسخ سریع با job_id (§24)؛ پایپ‌لاین در
    worker اجرا می‌شود. اعتبارسنجی مقصد همین‌جا سرور-ساید است."""
    # 🛡 W3/SEC-03 — ساخت job هزینه‌بر است (worker + پهنای باند)
    await rate_limit_user(admin["id"], "urlimport_job", 30, 60)
    payload = body.dict()
    kind = body.kind
    if kind == "qbank":
        payload["intake"] = resolve_content_intake(admin, body.intake)
        if not await db.can_access_intake(admin["id"], payload["intake"]):
            raise HTTPException(403, "intake_out_of_scope")
    elif kind in ("bs", "ref"):
        # §37 — هدف باید موجود باشد؛ bs/ref فقط دسترسی سراسری
        if (admin.get("_scope") or {}).get("kind") == "scoped":
            raise HTTPException(403, "درون‌ریزی علوم پایه/رفرنس فقط برای دسترسی سراسری")
        if kind == "bs":
            sess = await db.bs_get_session(body.target_id)
            if not sess:
                raise HTTPException(404, "جلسه‌ی مقصد پیدا نشد")
            if body.ctype not in CONTENT_TYPES:
                raise HTTPException(422, "نوع محتوا نامعتبر")
            payload["ctype"] = body.ctype
        else:
            book = await db.ref_get_book(body.target_id)
            if not book:
                raise HTTPException(404, "کتاب رفرنس مقصد پیدا نشد")
            if body.lang not in ("fa", "en"):
                raise HTTPException(422, "زبان نامعتبر")
    else:
        raise HTTPException(422, "نوع محتوای مقصد نامعتبر است")

    try:
        doc = await svc.create_import_job(admin, payload, body.idem)
    except svc.UrlImportError as e:
        raise HTTPException(422, e.message)
    await svc.start_import_job(str(doc["_id"]))
    await _audit(admin, "درون‌ریزی محتوا از URL", "Content", severity="INFO",
                 target_id=str(doc["_id"]), target_type="url_import_job",
                 target_label=doc.get("url_safe", ""),
                 after={"kind": kind}, tags=["محتوا", "درون‌ریزی_URL", "پنل_وب"])
    return {"ok": True, "job": _shape(doc)}


@router.get("/url-import/jobs")
async def list_jobs(status: str = Query("all"), page: int = Query(1, ge=1),
                    per_page: int = Query(20, ge=1, le=100),
                    admin=Depends(get_content_admin_user)):
    """فهرست jobها — scoped فقط jobهای خودش (§حریم)."""
    q = {}
    if (admin.get("_scope") or {}).get("kind") == "scoped":
        q["admin_id"] = admin["id"]
    if status != "all":
        q["status"] = status
    total = await db.url_import_jobs.count_documents(q)
    docs = await db.url_import_jobs.find(q).sort("created_at", -1) \
        .skip((page - 1) * per_page).limit(per_page).to_list(per_page)
    return {"ok": True, "total": total, "page": page, "per_page": per_page,
            "jobs": [_shape(d) for d in docs]}


@router.get("/url-import/jobs/{job_id}")
async def job_detail(job_id: str, admin=Depends(get_content_admin_user)):
    doc = await svc.get_import_job(job_id)
    if not doc:
        raise HTTPException(404, "job پیدا نشد")
    if (admin.get("_scope") or {}).get("kind") == "scoped" \
            and doc.get("admin_id") != admin["id"]:
        raise HTTPException(403, "job_out_of_scope")
    return {"ok": True, "job": _shape(doc)}


@router.post("/url-import/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, admin=Depends(get_content_admin_user)):
    doc = await svc.get_import_job(job_id)
    if not doc:
        raise HTTPException(404, "job پیدا نشد")
    if not await svc.cancel_import_job(job_id):
        raise HTTPException(409, "job قابل لغو نیست")
    await _audit(admin, "لغو درون‌ریزی URL", "Content", severity="MEDIUM",
                 target_id=job_id, target_type="url_import_job",
                 target_label=doc.get("url_safe", ""),
                 tags=["محتوا", "درون‌ریزی_URL", "پنل_وب"])
    return {"ok": True, "status": "cancelled"}


@router.post("/url-import/jobs/{job_id}/retry")
async def retry_job(job_id: str, body: RetryBody = None,
                    admin=Depends(get_content_admin_user)):
    doc = await svc.get_import_job(job_id)
    if not doc:
        raise HTTPException(404, "job پیدا نشد")
    try:
        new = await svc.retry_import_job(job_id, force=bool(body and body.force))
    except svc.UrlImportError as e:
        raise HTTPException(409, e.message)
    await _audit(admin, "تلاش مجدد درون‌ریزی URL", "Content", severity="MEDIUM",
                 target_id=job_id, target_type="url_import_job",
                 target_label=doc.get("url_safe", ""),
                 after={"force": bool(body and body.force)},
                 tags=["محتوا", "درون‌ریزی_URL", "پنل_وب"])
    return {"ok": True, "job": _shape(new)}
