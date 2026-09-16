# -*- coding: utf-8 -*-
"""
🚀 PERF-O4 + WAVE2 — Shared HTTP client (production-grade)

Design:
  startup  → get_shared_client()  (1 pool per event-loop)
  request  → client.post(..., timeout=...) with keep-alive reuse
  shutdown → aclose_shared_client()

Env tunables:
  HTTP_MAX_CONNECTIONS=80
  HTTP_MAX_KEEPALIVE=30
  HTTP_KEEPALIVE_EXPIRY=30
  HTTP_BROADCAST_CONCURRENCY=10
  HTTP_RETRY_MAX=2
"""
import os
import asyncio
import random
import logging
import httpx

logger = logging.getLogger(__name__)

_shared_client: httpx.AsyncClient | None = None
_lock = asyncio.Lock()

# Bounded concurrency for broadcast — prevents Telegram 429 flood + pool exhaustion
_broadcast_sem = asyncio.Semaphore(int(os.getenv("HTTP_BROADCAST_CONCURRENCY", "10")))

def _limits() -> httpx.Limits:
    return httpx.Limits(
        max_keepalive_connections=int(os.getenv("HTTP_MAX_KEEPALIVE", "30")),
        max_connections=int(os.getenv("HTTP_MAX_CONNECTIONS", "80")),
        keepalive_expiry=int(os.getenv("HTTP_KEEPALIVE_EXPIRY", "30")),
    )

def _timeout(default: httpx.Timeout | None = None) -> httpx.Timeout:
    return default or httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=10.0)

async def get_shared_client(timeout: httpx.Timeout | None = None) -> httpx.AsyncClient:
    global _shared_client
    # fast path without lock
    if _shared_client is not None and not _shared_client.is_closed:
        return _shared_client
    async with _lock:
        if _shared_client is None or _shared_client.is_closed:
            _shared_client = httpx.AsyncClient(
                timeout=timeout or _timeout(),
                limits=_limits(),
                http2=False,
                follow_redirects=True,
            )
            logger.info("HTTP shared client created limits=%s", _limits())
        return _shared_client

async def aclose_shared_client():
    global _shared_client
    async with _lock:
        if _shared_client and not _shared_client.is_closed:
            await _shared_client.aclose()
            logger.info("HTTP shared client closed")
            _shared_client = None

async def telegram_post(url: str, json: dict | None = None, data: dict | None = None, files: dict | None = None, timeout: httpx.Timeout | None = None) -> httpx.Response:
    """
    P0 — Telegram POST with bounded retry.
    Retries ONLY on retryable: 429 (respect Retry-After), 5xx, network errors.
    Never retries 400/401/403.
    """
    max_retries = int(os.getenv("HTTP_RETRY_MAX", "2"))
    client = await get_shared_client(timeout=timeout)
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            if files:
                resp = await client.post(url, data=data, files=files)
            elif json is not None:
                resp = await client.post(url, json=json)
            else:
                resp = await client.post(url, data=data)
            # 429 — respect Retry-After
            if resp.status_code == 429:
                ra = resp.headers.get("Retry-After") or (resp.json().get("parameters", {}).get("retry_after") if resp.headers.get("content-type","").startswith("application/json") else None)
                try:
                    sleep_s = float(ra) if ra else (1.5 * (attempt + 1))
                except:
                    sleep_s = 1.5 * (attempt + 1)
                sleep_s = min(sleep_s + random.uniform(0, 0.5), 10)
                if attempt < max_retries:
                    logger.warning("telegram 429 retry_after=%s attempt=%s", sleep_s, attempt)
                    await asyncio.sleep(sleep_s)
                    continue
            # 5xx retry with jitter
            if 500 <= resp.status_code < 600 and attempt < max_retries:
                sleep_s = (0.8 * (2 ** attempt)) + random.uniform(0, 0.4)
                await asyncio.sleep(sleep_s)
                continue
            return resp
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as e:
            last_exc = e
            if attempt < max_retries:
                sleep_s = (0.8 * (2 ** attempt)) + random.uniform(0, 0.4)
                await asyncio.sleep(sleep_s)
                continue
            raise
        except httpx.HTTPError as e:
            last_exc = e
            if attempt < max_retries and attempt == 0:
                await asyncio.sleep(0.5)
                continue
            raise
    if last_exc:
        raise last_exc
    return resp  # fallback

def broadcast_semaphore() -> asyncio.Semaphore:
    return _broadcast_sem
