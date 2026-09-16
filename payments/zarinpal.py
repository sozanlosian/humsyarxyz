# -*- coding: utf-8 -*-
"""
💳 Zarinpal Gateway — sandbox + production

Env:
  ZARINPAL_MERCHANT_ID  — 36-char UUID (if empty → mock mode)
  ZARINPAL_SANDBOX      — 1/0 (default 1 if merchant empty else 0)
  ZARINPAL_CALLBACK_URL — frontend callback base, e.g. https://humsyar.ir/payment/verify
  WEBAPP_URL            — fallback

API v4: request.json + verify.json  (amount in Rial)
Our plan.price is in Toman → Rial = Toman * 10

Mock mode: when merchant unset, we generate TEST-authority and verify always succeeds.
This allows local dev / Railway without real Zarinpal credentials.

Idempotency: authority is stored on sub_payments doc (field zarinpal_authority)
and verified only once via atomic CAS (pending_zarinpal → approved).

"""
import os
import uuid
import logging
import httpx

logger = logging.getLogger(__name__)

# Env fallbacks (DB settings take precedence when set)
MERCHANT_ID = os.getenv("ZARINPAL_MERCHANT_ID", "").strip()
_sandbox_env = os.getenv("ZARINPAL_SANDBOX", "").strip().lower()
if _sandbox_env in ("1", "true", "yes", "on"):
    SANDBOX = True
elif _sandbox_env in ("0", "false", "no", "off"):
    SANDBOX = False
else:
    SANDBOX = not bool(MERCHANT_ID)

CALLBACK_BASE = (os.getenv("ZARINPAL_CALLBACK_URL", "") or os.getenv("WEBAPP_URL", "")).strip().rstrip("/")

# 🌊 W6 — DB-backed config with 30s cache (admin can change via panel without restart)
import time as _t
_CFG_CACHE = {"at": 0, "data": None}
_CFG_TTL = 30

async def _get_cfg() -> dict:
    now = _t.time()
    if _CFG_CACHE["data"] is not None and now - _CFG_CACHE["at"] < _CFG_TTL:
        return _CFG_CACHE["data"]
    cfg = {"merchant_id": MERCHANT_ID, "sandbox": SANDBOX, "callback_base": CALLBACK_BASE, "enabled": True}
    try:
        from database import db as _db
        mid = await _db.get_setting("zarinpal_merchant_id", None)
        if isinstance(mid, str) and mid.strip():
            cfg["merchant_id"] = mid.strip()
        sb = await _db.get_setting("zarinpal_sandbox", None)
        if isinstance(sb, bool):
            cfg["sandbox"] = sb
        elif isinstance(sb, str):
            cfg["sandbox"] = sb.lower() in ("1","true","yes","on")
        cb = await _db.get_setting("zarinpal_callback_url", None)
        if isinstance(cb, str) and cb.strip():
            cfg["callback_base"] = cb.strip().rstrip("/")
        en = await _db.get_setting("zarinpal_enabled", None)
        if isinstance(en, bool):
            cfg["enabled"] = en
    except Exception:
        pass
    # fallback: if merchant still empty, mock mode
    if not cfg["merchant_id"]:
        cfg["sandbox"] = True
    _CFG_CACHE["at"] = now
    _CFG_CACHE["data"] = cfg
    return cfg

def _clear_cfg_cache():
    _CFG_CACHE["at"] = 0
    _CFG_CACHE["data"] = None

async def _is_mock_async() -> bool:
    cfg = await _get_cfg()
    mid = cfg.get("merchant_id") or ""
    return not mid or mid.lower() in ("test", "mock", "sandbox")

def _is_mock() -> bool:
    # sync fallback for legacy callers (uses env only) — prefer _is_mock_async in async paths
    return not MERCHANT_ID or MERCHANT_ID.lower() in ("test", "mock", "sandbox")

async def _api_base_async() -> str:
    cfg = await _get_cfg()
    return "https://sandbox.zarinpal.com/pg/v4/payment" if cfg.get("sandbox") else "https://api.zarinpal.com/pg/v4/payment"

def _api_base() -> str:
    return "https://sandbox.zarinpal.com/pg/v4/payment" if SANDBOX else "https://api.zarinpal.com/pg/v4/payment"

async def _pay_url_async(authority: str) -> str:
    cfg = await _get_cfg()
    if cfg.get("sandbox"):
        return f"https://sandbox.zarinpal.com/pg/StartPay/{authority}"
    return f"https://www.zarinpal.com/pg/StartPay/{authority}"

def _pay_url(authority: str) -> str:
    if SANDBOX:
        return f"https://sandbox.zarinpal.com/pg/StartPay/{authority}"
    return f"https://www.zarinpal.com/pg/StartPay/{authority}"

async def gateway_public_status() -> dict:
    """🌊 W2 — وضعیت عمومی درگاه برای کلاینت‌ها (فقط boolean؛ بدون هیچ secret)."""
    cfg = await _get_cfg()
    mid = (cfg.get("merchant_id") or "").strip()
    mock = (not mid) or (mid.lower() in ("test", "mock", "sandbox"))
    return {
        "online_pay_enabled": bool(cfg.get("enabled")),
        "mock": mock,
        "sandbox": bool(cfg.get("sandbox")),
        "bot_username": (os.environ.get("BOT_USERNAME") or "").strip(),
    }


async def zarinpal_request(amount_toman: int, description: str, callback_url: str = None,
                            mobile: str = None, email: str = None) -> dict:
    """
    Create payment request. Returns {authority, url, code}
    amount_toman: price in Toman (int)
    callback_url: where Zarinpal redirects after pay (with Authority & Status)
    """
    cfg = await _get_cfg()
    merchant_id = cfg.get("merchant_id") or MERCHANT_ID
    sandbox = cfg.get("sandbox") if cfg.get("sandbox") is not None else SANDBOX
    callback_base = cfg.get("callback_base") or CALLBACK_BASE
    # if gateway disabled and not mock, raise
    if not cfg.get("enabled", True) and not (not merchant_id or merchant_id.lower() in ("test","mock","sandbox")):
        raise RuntimeError("zarinpal gateway disabled by admin")
    amount_rial = int(amount_toman) * 10
    if amount_rial < 1000:
        raise ValueError("amount too small for Zarinpal (min 1000 Rial)")
    if not description:
        description = "خرید اشتراک هامشیار"
    description = description[:120]
    cb = (callback_url or callback_base or "https://humsyar.ir/payment/verify").strip()
    # Mock
    is_mock = not merchant_id or merchant_id.lower() in ("test", "mock", "sandbox")
    if is_mock:
        authority = f"A000000000000000000000000000{uuid.uuid4().hex[:6]}"
        # Use deterministic prefix for mock detection in verify
        authority = "TEST-" + uuid.uuid4().hex[:28].upper()
        url = f"https://sandbox.zarinpal.com/pg/StartPay/{authority}" if sandbox else f"https://www.zarinpal.com/pg/StartPay/{authority}"
        logger.info(f"[ZARINPAL MOCK] request amount={amount_toman}T ({amount_rial}R) desc={description} cb={cb} -> {authority}")
        return {"authority": authority, "url": url, "code": 100, "mock": True}

    url = f"{'https://sandbox.zarinpal.com/pg/v4/payment' if sandbox else 'https://api.zarinpal.com/pg/v4/payment'}/request.json"
    payload = {
        "merchant_id": merchant_id,
        "amount": amount_rial,
        "callback_url": cb,
        "description": description,
    }
    metadata = {}
    if mobile:
        metadata["mobile"] = mobile
    if email:
        metadata["email"] = email
    if metadata:
        payload["metadata"] = metadata

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    # Zarinpal returns {"data": {"code":100, "authority":"...", ...}, "errors": {...}}
    d = data.get("data") or {}
    code = int(d.get("code", 0))
    authority = d.get("authority", "")
    if code != 100 or not authority:
        logger.warning(f"zarinpal request failed code={code} resp={data}")
        # Try to extract error message
        err = data.get("errors") or {}
        # errors may be dict with message/code
        raise RuntimeError(f"zarinpal_request_failed code={code} err={err}")
    pay_url = _pay_url(authority)
    return {"authority": authority, "url": pay_url, "code": code, "mock": False}

async def zarinpal_verify(authority: str, amount_toman: int) -> dict:
    """
    Verify payment after redirect. Returns {ok, ref_id, card_pan, fee, code, mock}
    amount_toman must match original request (Toman)
    """
    cfg = await _get_cfg()
    merchant_id = cfg.get("merchant_id") or MERCHANT_ID
    sandbox = cfg.get("sandbox") if cfg.get("sandbox") is not None else SANDBOX
    amount_rial = int(amount_toman) * 10
    if not authority:
        raise ValueError("authority required")
    # Mock verify
    is_mock = authority.startswith("TEST-") or not merchant_id or merchant_id.lower() in ("test","mock","sandbox")
    if is_mock:
        # In mock, authority starting with TEST- always succeeds
        ref_id = int(uuid.uuid4().int % 900000) + 100000
        logger.info(f"[ZARINPAL MOCK] verify authority={authority} amount={amount_toman}T -> ref {ref_id}")
        return {"ok": True, "ref_id": str(ref_id), "code": 100, "mock": True, "card_pan": "6037-****-****-0000"}

    url = f"{'https://sandbox.zarinpal.com/pg/v4/payment' if sandbox else 'https://api.zarinpal.com/pg/v4/payment'}/verify.json"
    payload = {
        "merchant_id": merchant_id,
        "amount": amount_rial,
        "authority": authority,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    d = data.get("data") or {}
    code = int(d.get("code", -1))
    # 100 success, 101 already verified
    if code in (100, 101):
        return {"ok": True, "ref_id": str(d.get("ref_id", "")), "code": code,
                "card_pan": d.get("card_pan", ""), "card_hash": d.get("card_hash", ""),
                "fee": d.get("fee", 0), "mock": False}
    logger.warning(f"zarinpal verify failed authority={authority} code={code} resp={data}")
    return {"ok": False, "code": code, "errors": data.get("errors"), "mock": False}


async def zarinpal_reverse(authority: str) -> dict:
    """🌊 W3/MISS-02 — Reverse پرداختِ verifyنشده (آزادسازی فوری hold).

    فقط برای authorityهایی که پول داده شده ولی verify نشده‌اند؛ روی
    تراکنشِ verifyشده درگاه خطا برمی‌گرداند (بازگشت آن‌ها دستی است).
    Returns {ok, code, mock}
    """
    cfg = await _get_cfg()
    merchant_id = cfg.get("merchant_id") or MERCHANT_ID
    sandbox = cfg.get("sandbox") if cfg.get("sandbox") is not None else SANDBOX
    if not authority:
        raise ValueError("authority required")
    is_mock = (authority.startswith("TEST-") or not merchant_id
               or merchant_id.lower() in ("test", "mock", "sandbox"))
    if is_mock:
        logger.info(f"[ZARINPAL MOCK] reverse authority={authority}")
        return {"ok": True, "code": 100, "mock": True}
    url = (f"{'https://sandbox.zarinpal.com/pg/v4/payment' if sandbox else 'https://api.zarinpal.com/pg/v4/payment'}"
           f"/reverse.json")
    payload = {"merchant_id": merchant_id, "authority": authority}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    d = data.get("data") or {}
    code = int(d.get("code", -1))
    if code == 100:
        return {"ok": True, "code": code, "mock": False}
    logger.warning(f"zarinpal reverse failed authority={authority} code={code} resp={data}")
    return {"ok": False, "code": code, "errors": data.get("errors"), "mock": False}
