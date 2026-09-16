# -*- coding: utf-8 -*-
"""
🛡 W1 — Global Rate Limiter (single-container, no Redis)

- In-memory sliding-window per-key (IP / user_id / composite)
- No external deps, O(1) per request, auto-eviction
- Designed for 1 container / 1-2 workers (Railway). If you scale to
  multiple containers, replace _store with Redis — interface stays same.

Usage:
    from api.rate_limit import rate_limit, RateLimitConfig
    @router.post("/otp")
    async def otp(req: Request, body=...):
        await rate_limit(req, "otp", limit=5, window=600)   # raises 429 if exceeded

Or as dependency:
    @router.post("/ai/ask", dependencies=[Depends(rate_limit_dependency("ai", 30, 60))])

Environment tunables (all optional):
    RATE_LIMIT_ENABLED=1  (0 to disable globally for tests)
    RATE_LIMIT_AI_PER_MIN=30
    RATE_LIMIT_OTP_PER_10M=5
    RATE_LIMIT_SUBMIT_PER_MIN=10
"""
import time
import asyncio
import os
from typing import Dict, Tuple
from fastapi import Request, HTTPException

_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "1").strip().lower() not in ("0","false","no","off")

# { key: (window_start_ts, count, window_seconds) }
_store: Dict[str, Tuple[float, int, int]] = {}
_lock = asyncio.Lock()
_MAX_KEYS = 8192  # cap memory under attack (key = ip:scope or user:scope)

def _client_key(request: Request) -> str:
    # Railway sets X-Forwarded-For; starlette's client.host is already the real IP behind proxy
    try:
        # prefer XFF first entry
        xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if xff:
            return xff
    except Exception:
        pass
    try:
        return request.client.host if request.client else "unknown"
    except Exception:
        return "unknown"

async def _check(key: str, limit: int, window: int) -> Tuple[bool, int]:
    """Return (allowed, retry_after_seconds). Mutates _store."""
    if not _ENABLED or limit <= 0 or window <= 0:
        return True, 0
    now = time.time()
    async with _lock:
        # lazy sweep if too big: remove expired windows
        if len(_store) > _MAX_KEYS:
            expired = [k for k,(s,c,w) in _store.items() if now - s >= w]
            for k in expired[:2048]:
                _store.pop(k, None)
            if len(_store) > _MAX_KEYS:
                # still full → drop oldest 25%
                oldest = sorted(_store.items(), key=lambda kv: kv[1][0])[: _MAX_KEYS // 4]
                for k,_ in oldest:
                    _store.pop(k, None)
        ent = _store.get(key)
        if ent is None or now - ent[0] >= ent[2]:
            _store[key] = (now, 1, window)
            return True, 0
        start, cnt, win = ent
        if cnt < limit:
            _store[key] = (start, cnt+1, win)
            return True, 0
        retry = int((start + win) - now) + 1
        return False, max(1, retry)

async def rate_limit(request: Request, scope: str, limit: int, window: int, *, key: str = None, by_user: bool = False):
    """
    Enforce limit for scope. Raises HTTP 429 with Retry-After if exceeded.
    - scope: e.g. "otp", "ai_ask", "sub_buy"
    - key: override composite key; if None uses IP (or user if by_user)
    """
    if not _ENABLED:
        return
    if key is None:
        if by_user:
            # per-user limiter — requires authenticated user in request.state or header fallback
            # caller should pass user_id explicitly if possible; fallback to IP
            try:
                uid = getattr(request.state, "user_id", None)
                if uid:
                    comp = f"u:{uid}:{scope}"
                else:
                    comp = f"ip:{_client_key(request)}:{scope}"
            except Exception:
                comp = f"ip:{_client_key(request)}:{scope}"
        else:
            comp = f"ip:{_client_key(request)}:{scope}"
    else:
        comp = f"{key}:{scope}" if ":" not in key else key
    allowed, retry = await _check(comp, limit, window)
    if not allowed:
        raise HTTPException(status_code=429, detail="rate_limited", headers={"Retry-After": str(retry)})

def rate_limit_dependency(scope: str, limit: int, window: int, *, by_user: bool=False):
    """Factory for Depends() — captures scope/limit/window."""
    async def _dep(request: Request):
        await rate_limit(request, scope, limit, window, by_user=by_user)
    _dep.__name__ = f"rl_{scope}"
    return _dep

# Presets (read from env, sane defaults)
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or default)
    except: return default

PRESETS = {
    "otp":      (_env_int("RATE_LIMIT_OTP_PER_10M", 5), 600),
    "ai_ask":   (_env_int("RATE_LIMIT_AI_PER_MIN", 30), 60),
    "ai_image": (_env_int("RATE_LIMIT_AI_IMAGE_PER_H", 20), 3600),
    "sub_buy":  (_env_int("RATE_LIMIT_SUBMIT_PER_MIN", 10), 60),
    "global_api": (_env_int("RATE_LIMIT_GLOBAL_PER_MIN", 120), 60),
}


async def rate_limit_user(user_id: int, scope: str, limit: int, window: int):
    """Per-user throttle (used inside handlers after auth). Raises 429."""
    if not _ENABLED: return
    key = f"u:{int(user_id)}:{scope}"
    allowed, retry = await _check(key, limit, window)
    if not allowed:
        raise HTTPException(status_code=429, detail="rate_limited", headers={"Retry-After": str(retry)})

async def check_global(request: Request):
    """Optional global throttle per IP (120/min). Call from middleware if desired."""
    if not _ENABLED: return
    lim, win = PRESETS["global_api"]
    # only for /api/* to avoid static
    try:
        p = request.url.path or ""
        if not p.startswith("/api/"): return
    except: return
    await rate_limit(request, "global", lim, win)
