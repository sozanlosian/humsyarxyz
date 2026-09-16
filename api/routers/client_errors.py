# -*- coding: utf-8 -*-
"""🌊 W5/REL-03 — گزارش خطای کلاینت (مینی‌اپ/وب‌ادمین).

ErrorBoundary فرانت خطای رندر را best-effort همین‌جا می‌فرستد تا خطاهای
فرانت که قبلاً فقط در localStorage کاربر می‌ماند، برای اپراتور دیده شود.
ذخیره‌سازی TTLدار (۳۰ روز) و کرانه‌دار است؛ خواندن فقط با system.manage.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.auth import get_current_user
from api.rate_limit import rate_limit_user
from database import db
from time_utils import now_utc

router = APIRouter(tags=["client-errors"])


class ClientErrorBody(BaseModel):
    app: str = Field(default="miniapp", max_length=16)
    path: str = Field(default="", max_length=200)
    message: str = Field(default="", max_length=500)
    stack: str = Field(default="", max_length=2000)


@router.post("/client-errors")
async def report_client_error(body: ClientErrorBody,
                              user=Depends(get_current_user)):
    # ضد اسپم/حلقه‌ی گزارش (۱۰ در دقیقه برای هر کاربر کافی است)
    await rate_limit_user(user["id"], "client_error", 10, 60)
    await db.client_errors.insert_one({
        "user_id": int(user["id"]),
        "app": (body.app or "miniapp")[:16],
        "path": (body.path or "")[:200],
        "message": (body.message or "")[:500],
        "stack": (body.stack or "")[:2000],
        "at": now_utc(),
    })
    return {"ok": True}
