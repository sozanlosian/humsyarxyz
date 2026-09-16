# -*- coding: utf-8 -*-
"""
💳 Payment Gateway Admin — Zarinpal config (DB-backed, no restart)
"""
import re
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from api.auth import require_perm
# 🛡 W4/SEC-04 — گیت از «فقط مالک» به مجوز RBAC (همان چیزی که UI می‌گوید)
from database import db
from payments.zarinpal import _clear_cfg_cache
import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/gateway", tags=["payment-gateway"])

def _mask(mid: str) -> str:
    if not mid: return ""
    mid = mid.strip()
    if len(mid) <= 8: return "****"
    return mid[:4] + "****" + mid[-4:]

class GatewayGetOut(BaseModel):
    merchant_id_masked: str
    merchant_id_set: bool
    sandbox: bool
    callback_url: str
    enabled: bool
    is_mock: bool
    docs_url: str = "https://www.zarinpal.com/docs/howToUse/"

class GatewayPutBody(BaseModel):
    merchant_id: Optional[str] = Field(None, max_length=100, description="36-char UUID from Zarinpal panel")
    sandbox: Optional[bool] = None
    callback_url: Optional[str] = Field(None, max_length=300)
    enabled: Optional[bool] = None

@router.get("/zarinpal", response_model=GatewayGetOut)
async def get_zarinpal_cfg(admin=Depends(require_perm("subscription.manage"))):
    mid = (await db.get_setting("zarinpal_merchant_id", "") or "").strip()
    sb = await db.get_setting("zarinpal_sandbox", None)
    # fallback to env via payments module cache? we just check DB; if None, show env default from payments module
    if sb is None:
        try:
            from payments.zarinpal import SANDBOX, MERCHANT_ID
            sb = SANDBOX if not mid else False
            if not mid and not MERCHANT_ID:
                sb = True
        except: sb = True
    cb = (await db.get_setting("zarinpal_callback_url", "") or "").strip()
    enabled = await db.get_setting("zarinpal_enabled", True)
    if enabled is None: enabled = True
    is_mock = not bool(mid) or mid.lower() in ("test","mock","sandbox")
    return GatewayGetOut(
        merchant_id_masked=_mask(mid) if mid else "",
        merchant_id_set=bool(mid),
        sandbox=bool(sb),
        callback_url=cb,
        enabled=bool(enabled),
        is_mock=is_mock,
    )

@router.put("/zarinpal")
async def put_zarinpal_cfg(body: GatewayPutBody, admin=Depends(require_perm("subscription.manage"))):
    # Validate merchant_id format (Zarinpal UUID 36 chars, but allow test/mock for mock mode)
    if body.merchant_id is not None:
        mid = body.merchant_id.strip()
        if mid and mid.lower() not in ("test","mock","sandbox"):
            # Zarinpal merchant is UUID like xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx (36 chars with dashes)
            if not re.match(r"^[0-9a-fA-F-]{30,40}$", mid):
                # allow but warn — some merchants are shorter? we allow but log
                logger.warning("zarinpal merchant format suspicious: len=%d",
                                 len(mid))
            if len(mid) < 10:
                raise HTTPException(422, "merchant_id کوتاه است (باید UUID 36 کاراکتری باشد)")
        await db.set_setting("zarinpal_merchant_id", mid)
    if body.sandbox is not None:
        await db.set_setting("zarinpal_sandbox", bool(body.sandbox))
    if body.callback_url is not None:
        cb = body.callback_url.strip().rstrip("/")
        if cb and not cb.startswith("https://") and not cb.startswith("http://"):
            raise HTTPException(422, "callback_url باید با https:// شروع شود")
        await db.set_setting("zarinpal_callback_url", cb)
    if body.enabled is not None:
        await db.set_setting("zarinpal_enabled", bool(body.enabled))
    # clear cache so next request uses new config immediately
    try: _clear_cfg_cache()
    except: pass
    # audit
    try:
        from utils import send_audit_log
        # need bot? we don't have bot here; just log to db via database
        _audit_after = {k: v for k, v in body.model_dump(exclude_none=True).items()
                        if k != "merchant_id"}
        if body.merchant_id is not None:
            # 🛡 W4/SEC-06 — خودِ مرچنت هرگز در audit لاگ نمی‌شود
            _audit_after["merchant_id"] = _mask(body.merchant_id) if body.merchant_id.strip() else "(cleared)"
        await db.log_action(admin["id"], admin.get("name","ادمین"), "مدیر ارشد", "ویرایش درگاه زرین‌پال", "Payment", "admin", "HIGH", target_id="zarinpal", target_type="gateway", after=_audit_after)
    except: pass
    return {"ok": True}

@router.post("/zarinpal/test")
async def test_zarinpal_cfg(admin=Depends(require_perm("subscription.manage"))):
    # Light test: try request with 1000 Toman mock amount (will be mock if no merchant, else real request but we don't actually pay)
    # We do a dry-run: check merchant format and sandbox flag
    cfg = await get_zarinpal_cfg(admin)
    if cfg.is_mock:
        return {"ok": True, "mock": True, "message": "حالت آزمایشی (mock) فعال است — بدون merchant واقعی، پرداخت شبیه‌سازی می‌شود."}
    # if real merchant, we could try a 1000 Toman request with TEST callback and immediately verify it will fail? Better not hit real API without amount.
    # So just return config check
    return {"ok": True, "mock": False, "sandbox": cfg.sandbox, "message": f"درگاه {'سندباکس' if cfg.sandbox else 'اصلی'} با merchant {_mask(await db.get_setting('zarinpal_merchant_id',''))} آماده است."}
