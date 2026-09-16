"""🏥 هامزیار Mini App — FastAPI Backend v2.0"""
import asyncio
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from api.routers import (
    academic_admin,
    admin_panel,
    ai,
    ai_management,
    client_errors,
    content_admin,
    dashboard,
    faq,
    global_search,
    grades,
    notifications,
    payment_gateway,
    profile,
    questions,
    rbac,
    referral,
    references,
    registration,
    reports,
    resources,
    ring_admin,
    schedule,
    subscription,
    subscription_management,
    tickets,
    url_import,
    web_admin,
)
from database import db
from request_context import current_request_id
from time_utils import now_utc
# 🛡 W1 — rate limiter (optional, env RATE_LIMIT_ENABLED=1)
try:
    from api.rate_limit import check_global as _rl_check_global
except Exception:
    _rl_check_global = None


_BOOTSTRAP_STATE = {"ready": False, "steps": {}, "started_at": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    _BOOTSTRAP_STATE["started_at"] = now_utc().isoformat()
    # 🚀 WAVE2 — warm shared http client at startup (pool ready before first request)
    try:
        from http_client import get_shared_client
        await get_shared_client()
    except Exception: pass
    # 🌊 W3 — migrations قبل از هر چیز
    try:
        from db.migrations import run_migrations
        await run_migrations(db)
    except Exception as _e:
        _BOOTSTRAP_STATE.setdefault("steps", {})["migrations"] = {"ok": False, "error": str(_e)}
    shared, question_indexes = await asyncio.gather(
        db.bootstrap_shared(),
        questions.ensure_indexes(),
        return_exceptions=True,
    )
    if isinstance(shared, BaseException):
        _BOOTSTRAP_STATE.update({"ready": False, "error": f"{type(shared).__name__}: {shared}"})
    else:
        _BOOTSTRAP_STATE.update(shared)
    if isinstance(question_indexes, BaseException):
        _BOOTSTRAP_STATE["ready"] = False
        _BOOTSTRAP_STATE.setdefault("steps", {})["question_indexes"] = {
            "ok": False, "error": f"{type(question_indexes).__name__}: {question_indexes}"
        }
    else:
        _BOOTSTRAP_STATE.setdefault("steps", {})["question_indexes"] = {"ok": True}

    # 📥 URL-Import — §82: jobهای نیمه‌کاره‌ی پیش از restart علامت‌گذاری
    try:
        import url_import_service as _uis
        _BOOTSTRAP_STATE.setdefault("steps", {})["url_import_recover"] = {
            "ok": True, "recovered": await _uis.recover_stale_jobs()}
    except Exception as exc:  # pragma: no cover
        _BOOTSTRAP_STATE.setdefault("steps", {})["url_import_recover"] = {
            "ok": False, "error": str(exc)}

    yield

    # 🌊 W3 — graceful: shared http client + cancel pending tasks
    try:
        from http_client import aclose_shared_client
        await aclose_shared_client()
    except Exception: pass
    # allow in-flight requests to finish (best-effort 2s)
    try:
        await asyncio.sleep(0.1)
    except: pass
    try:
        db.client.close()
    except: pass


# 🛡 W4/SEC-01 — مستندات تعاملی API به‌صورت پیش‌فرض بسته است؛ اسکیمای
# اندپوینت‌های ادمین نباید عمومی باشد. برای بازکردن در dev:
# API_DOCS_ENABLED=1
_DOCS_ON = (os.getenv("API_DOCS_ENABLED", "0").strip().lower()
            in ("1", "true", "yes", "on"))

app = FastAPI(
    title="Humsyar API",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if _DOCS_ON else None,
    redoc_url="/redoc" if _DOCS_ON else None,
    openapi_url="/openapi.json" if _DOCS_ON else None,
)

#: مبنای محاسبه‌ی uptime برای /api/health — در زمان import تنظیم می‌شود.
#: (monotonic: تحت تأثیر پرش ساعت سیستم/NTP قرار نمی‌گیرد.)
_APP_STARTED_MONO = time.monotonic()

_api_logger = logging.getLogger("api")

#: 🛡 AUDIT-R3 — کرانه‌ی هدر Range (PYSEC-2026-1942 / CVE-2025-…):
#: ستاره‌ت 0.41.x که FastAPI این ریپو روی آن قفل است، پارس/ادغام چندrange
#: را O(n²) انجام می‌دهد و StaticFiles (اسناد miniapp/webadmin که همین‌جا
#: mount شده‌اند) با یک هدرِ ساخته‌شده می‌تواند CPU یک ورکر را قفل کند.
#: راه‌حل اصلی ارتقای starlette است (در گزارش §۶۷)، ولی تا آن زمان این
#: میان‌افزار بی‌خطرِ ۸ خطی، درخواست‌های چندتاییِ غیرمعمول را رد می‌کند.
#: مرورگرها برای تماشای ویدیو/دانلود تک‌range می‌فرستند ⇒ رفتار عادی تغییر
#: نمی‌کند؛ فقط الگوی آلوده (۱۶+ بازه یا رشته‌ی خیلی بلند) رد می‌شود.
_RANGE_MAX_INTERVALS = 16
_RANGE_MAX_LEN = 512


def _raw_path(request) -> str:
    """مسیر خام درخواست از `scope` — **نه** مسیرِ بازسازی‌شده‌ی `request.url`.

    🛡 AUDIT-R4 (PYSEC-2026-161 و PYSEC-2026-248، starlette 0.41.3): در این
    نسخه `request.url` را از `Host` + path بازسازی و دوباره پارس می‌کند، پس
    با `Host: x/evil?y=` مقدار مسیرِ بازسازی‌شده با مسیری که واقعاً route
    شده فرق می‌کند. هر تصمیم امنیتی که به `.startswith('/admin')` وابسته باشد
    (هدرهای CSP/X-Frame-Options و کش اsets) با آن مقدار گمراه‌شونده است؛
    `scope["path"]` همان مقداری است که FastAPI برای مسیریابی استفاده کرده.
    """
    try:
        return request.scope.get("path") or ""
    except Exception:                                  # pragma: no cover
        return ""


@app.middleware("http")
async def _bound_range_header(request, call_next):
    rng = request.headers.get("range")
    if rng and rng.startswith("bytes="):
        spec = rng[len("bytes="):]
        if len(spec) > _RANGE_MAX_LEN or spec.count(",") + 1 > _RANGE_MAX_INTERVALS:
            from starlette.responses import PlainTextResponse

            return PlainTextResponse("range too broad", status_code=416,
                                     headers={"Content-Range": "*"})
    return await call_next(request)


@app.middleware("http")
async def request_context_and_safe_errors(request: Request, call_next):
    """Request ID برای ردیابی و پاسخ انسانی برای exceptionهای کنترل‌نشده.

    HTTPExceptionهای معتبر همچنان توسط FastAPI با status/detail اصلی مدیریت
    می‌شوند؛ فقط crashهای واقعی از نمایش traceback/500 خام به کاربر جلوگیری می‌کنند.
    """
    started = time.perf_counter()
    supplied = (request.headers.get("x-request-id") or "").strip()
    if supplied and re.fullmatch(r"[A-Za-z0-9._:-]{1,80}", supplied):
        request_id = supplied
    else:
        # 🆕 Audit Refactor §10 — HY-YYYYMMDD-XXXXXX برای قابلیت جستجو/مرتب‌سازی
        try:
            from time_utils import now_tehran
            today = now_tehran().strftime("%Y%m%d")
        except Exception:
            from datetime import datetime, timezone
            today = datetime.now(timezone.utc).strftime("%Y%m%d")
        request_id = f"HY-{today}-{uuid.uuid4().hex[:6].upper()}"
    token = current_request_id.set(request_id)
    try:
        try:
            response = await call_next(request)
        except Exception:
            _api_logger.exception("unhandled API error request_id=%s path=%s",
                                  request_id, _raw_path(request))
            response = JSONResponse(
                status_code=500,
                content={"detail": "internal_error", "error_id": request_id},
            )
        response.headers["X-Request-ID"] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        if _raw_path(request).startswith("/api/web-admin/"):
            route_template = getattr(request.scope.get("route"), "path", "")
            route = route_template or re.sub(r"/(?:(?:[0-9]+)|(?:[0-9a-fA-F]{24}))(?=/|$)", "/:id", _raw_path(request))
            metric = {"at": now_utc(), "route": route[:180], "method": request.method,
                      "status": int(response.status_code),
                      "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                      "request_id": request_id}
            async def persist_metric():
                try:
                    await db.wa_api_metrics.insert_one(metric)
                except Exception as _me:
                    # 🛡 AUDIT-§۲۰ — دیگر «pass» بی‌صدا نیست: شکستِ نوشتن متریک
                    # دیده می‌شود، ولی هرگز درخواست کاربر را نمی‌شکند.
                    _api_logger.debug("wa_api_metrics insert failed: %s", _me)
            # 🛡 AUDIT-M1 — تسک با مرجع و لاگ خطا
            from utils import spawn_bg
            spawn_bg(persist_metric(), 'wa_api_metric')
        # 🌊 W5/REL-03 — شمارنده‌ی ارزانِ همه‌ی /api/* (درون‌حافظه‌ای؛
        # wa_api_metrics همچنان منبع ماندگار وب‌ادمین است)
        try:
            from api.api_counters import record as _api_count
            _p = _raw_path(request)
            if _p.startswith("/api/"):
                _tpl = (getattr(request.scope.get("route"), "path", "")
                        or re.sub(r"/(?:(?:[0-9]+)|(?:[0-9a-fA-F]{24}))(?=/|$)",
                                  "/:id", _p))
                _api_count(request.method, _tpl,
                           int(response.status_code), request_id)
        except Exception:
            pass
        return response
    finally:
        current_request_id.reset(token)


# ──────────────────────────────────────────────────────────
#  🚂 مهاجرت Railway — CORS
#
#  Mini App و API حالا روی *یک origin* هستند (/app/ و /api/* روی
#  همان دامنه)، پس مرورگر اصلاً preflight نمی‌فرستد و CORS در
#  production عملاً بی‌مصرف است. با این حال آن را حذف نمی‌کنیم:
#  ممکن است یک دامنه‌ی سفارشی/موقت یا کلاینت خارجی در میانه باشد.
#
#  🔧 اصلاح یک باگ واقعی: WEBAPP_URL آدرس *صفحه* است
#     (مثلاً https://example.com/app — مسیر مینی‌اپ)
#  ولی CORS به *origin* نیاز دارد (https://example.com). گذاشتن
#  مقدار کامل داخل allow_origins یعنی هیچ‌وقت match نمی‌شود و
#  همه‌ی درخواست‌های CORS‌دار رد می‌شدند. پس مبدأ parse می‌شود.
#
#  سازگاری عقب‌رو: WEBAPP_URL می‌تواند لیست جداشده با کاما باشد؛
#  مقدار تنظیم‌نشده همچنان "*" است (رفتار قبلی).
# ──────────────────────────────────────────────────────────
def _cors_origins(raw: str) -> list[str]:
    """از هر ورودی، فقط «scheme://host[:port]» را بیرون می‌کشد."""
    from urllib.parse import urlsplit

    out: list[str] = []
    for item in (raw or "").split(","):
        item = item.strip().rstrip("/")
        if not item:
            continue
        if item == "*":
            return ["*"]
        # host خام بدون scheme (مثلاً example.com/app)
        candidate = item if "://" in item else f"https://{item}"
        parts = urlsplit(candidate)
        if not parts.netloc:
            continue
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in out:
            out.append(origin)
    return out or ["*"]


WEBAPP_URL = os.getenv(
    "WEBAPP_URL",
    "*",
)

_CORS_ALLOW_CREDENTIALS = os.getenv("CORS_ALLOW_CREDENTIALS", "true").strip().lower() not in (
    "0", "false", "no", "off",
)
_CORS_ORIGINS = _cors_origins(WEBAPP_URL)
# با allow_credentials=True، فرستادن "*" از نظر مرورگر نامعتبر است؛
# در همان حالت فقط originهای صریح مجازند.
if _CORS_ORIGINS == ["*"] and _CORS_ALLOW_CREDENTIALS:
    _local_dev = ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173"]
    _CORS_ORIGINS = _local_dev  # فقط dev؛ production با WEBAPP_URL صریح کار می‌کند

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=_CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🛡🌊 WA2.9 — سربرگ‌های امنیتی (افزایشی؛ هیچ پاسخ/رفتار فعلی تغییر نمی‌کند):
# برای همه‌ی مسیر‌ها nosniff/no-referrer-safe؛ CSP سخت‌گیر فقط روی /admin
# (SPA وب‌ادمین) اعمال می‌شود تا مینی‌اپ/وب‌هوک‌های دیگر دست‌نخورده بمانند.
@app.middleware("http")
async def _wa2_security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    try:
        path = _raw_path(request)   # 🛡 AUDIT-R4 — مسیر خام (ضدِ Host-header confusion)
    except Exception:
        path = ""
    if path.startswith("/admin"):
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    return resp


# 🗜 موج ۴.۶۰ — فشرده‌سازی پاسخ‌های JSON بزرگ؛
# payloadهای چند‌ده‌KB (لیست کاربران/رسیدها/آمار)
# روی شبکه‌ی موبایل محسوس کوچک‌تر و سریع‌تر می‌شوند.
# فقط بالای ۱KB — پاسخ‌های کوچک سربار نمی‌گیرند.
app.add_middleware(
    GZipMiddleware,
    minimum_size=1000,
)


app.include_router(
    dashboard.router,
    prefix="/api/dashboard",
)

app.include_router(
    client_errors.router,
    prefix="/api",
)

app.include_router(
    questions.router,
    prefix="/api/questions",
)

app.include_router(
    schedule.router,
    prefix="/api/schedule",
)

app.include_router(
    resources.router,
    prefix="/api/resources",
)

app.include_router(
    profile.router,
    prefix="/api/profile",
)

app.include_router(
    notifications.router,
    prefix="/api/notifications",
)

app.include_router(
    references.router,
    prefix="/api/references",
)

app.include_router(
    faq.router,
    prefix="/api/faq",
)

app.include_router(
    tickets.router,
    prefix="/api/tickets",
)

app.include_router(
    referral.router,
    prefix="/api/referral",
)

app.include_router(
    registration.router,
    prefix="/api/auth",
)

app.include_router(
    reports.router,
    prefix="/api/reports",
)

app.include_router(
    grades.router,
    prefix="/api/grades",
)

app.include_router(
    subscription.router,
    prefix="/api/subscription",
)

app.include_router(
    ai.router,
    prefix="/api/ai",
)

app.include_router(
    global_search.router,
    prefix="/api/search",
)

app.include_router(
    subscription_management.router,
    prefix="/api/subscription-admin",
)

app.include_router(
    ai_management.router,
    prefix="/api/ai-admin",
)

app.include_router(
    content_admin.router,
    prefix="/api/content",
)

# 📥 URL-Import — همان prefix محتوا؛ تنها پایپ‌لاین canonical درون‌ریزی
app.include_router(
    url_import.router,
    prefix="/api/content",
)

app.include_router(
    academic_admin.router,
    prefix="/api/academic-admin",
)

app.include_router(
    admin_panel.router,
    prefix="/api/admin",
)

# 🛡 موج RBAC-W1 — مدیریت نقش‌ها/مجوزها (تک‌منبع حقیقت)
# افزایشی خالص: هیچ route قدیمی جابه‌جا/تغییر نکرده است.
app.include_router(
    rbac.router,
    prefix="/api/admin/rbac",
    tags=["rbac"],
)

# 💍 Ring Street — API ادمینِ رینگ استریت (افزودنی خالص؛ هیچ route
# قدیمی جابه‌جا یا تغییر نکرده). همه‌ی اندپوینت‌ها پشت مجوز ring.manage‌اند.
app.include_router(
    ring_admin.router,
    prefix="/api/ring",
    tags=["ring"],
)

# 🖥️ موج WA — Web Admin API (احراز هویت OTP + سشن، داشبورد و اکشن‌های وب)
app.include_router(
    web_admin.router,
    prefix="/api/web-admin",
    tags=["web-admin"],
)

app.include_router(
    payment_gateway.router,
    prefix="/api",
    tags=["payment-gateway"],
)


@app.get("/api/health")
async def health():
    """سلامت سبک — فقط «API پاسخ می‌دهد».

    عمداً ارزان است و هیچ وابستگی بیرونی (Mongo/تلگرام/ربات) را
    نمی‌سنجد: Railway همین endpoint را healthcheck می‌کند و نباید
    با مردن ربات یا کندی Mongo کل سرویس را unhealthy و restart کند.
    تشخیص کامل → /api/health/deep
    """
    return {
        "status": "ok",
        "version": "2.0.0",
        "uptime_s": round(time.monotonic() - _APP_STARTED_MONO, 1),
        "miniapp": _MINIAPP_DIST_STATE["built"],
    }


@app.get("/api/health/ready", include_in_schema=False)
async def health_ready():
    """Dependency-aware readiness probe; unlike /api/health it may fail."""
    ready = bool(_BOOTSTRAP_STATE.get("ready"))
    if ready:
        try:
            await db.client.admin.command("ping")
        except Exception:
            ready = False
    payload = {
        "status": "ready" if ready else "not_ready",
        "api": {"ok": True},
        "bootstrap": dict(_BOOTSTRAP_STATE),
    }
    if not ready:
        return JSONResponse(status_code=503, content=payload)
    return payload


@app.get("/api/health/deep", include_in_schema=False)
async def health_deep():
    """دیاگنوستیک کامل برای انسان: API + ربات + Mongo + بیلدها.

    هر بخش مستقل سنجیده می‌شود و خطای یکی بقیه را نمی‌کُشد.
    هرگز به‌عنوان healthcheck استقرار استفاده نشود (کندتر است و
    به فرایند ربات و دیتابیس وابسته است).
    """
    from bot_heartbeat import read_heartbeat

    hb = read_heartbeat()

    db_ok = False
    db_ms = None
    db_error = ""
    try:
        t0 = time.perf_counter()
        await db.client.admin.command("ping")
        db_ms = round((time.perf_counter() - t0) * 1000, 1)
        db_ok = True
    except Exception as exc:
        db_error = f"{type(exc).__name__}: {str(exc)[:160]}"

    deep_ok = db_ok and bool(_BOOTSTRAP_STATE.get("ready"))
    return {
        "status": "ok" if deep_ok else "degraded",
        "version": "2.0.0",
        "uptime_s": round(time.monotonic() - _APP_STARTED_MONO, 1),
        "api": {"ok": True, "pid": os.getpid()},
        "bootstrap": dict(_BOOTSTRAP_STATE),
        "bot": {
            "process_ok": _bot_process_ok()[0],
            "process_pid": _bot_process_ok()[1],
            "heartbeat": hb,
            "note": ("heartbeat هیچ‌وقت دیده نشده — آیا bot.py بالا آمده است؟"
                     if not hb.get("seen") else None),
        },
        "mongo": {"ok": db_ok, "ping_ms": db_ms, "error": db_error},
        "miniapp": dict(_MINIAPP_DIST_STATE),
        "webadmin": dict(_WEBADMIN_DIST_STATE),
        "routes": _count_api_operations(),
    }


# 📌 خط‌مبنای رگرسیون مسیرها.
# قبلاً ۴۵۰ بود و با رشد API به ۴۹۴ رسید، اما چون هیچ تستی
# routes_match_baseline را نمی‌خواند، گارد در سکوت False می‌ماند و
# عملاً بی‌اثر بود. حالا tests/test_route_inventory.py آن را می‌خواند؛
# تغییر عمدیِ سطح API باید همین عدد را هم آگاهانه به‌روز کند.
# ۴۹۴ → ۴۹۷ با افزودن DLQ (GET /system/dlq و POST requeue/discard).
# §W8 — ۴۹۷ → ۴۹۸ با افزودنِ `GET /api/content/questions/{qid}/reports`
#        (نمای تجمیعیِ گزارش‌های یک سؤال).
# §W9 — ۴۹۸ → ۵۰۱ با سه endpoint:
#        `GET /api/content/questions/reported` (فهرستِ سؤالاتِ گزارش‌دار)
#        + دو delegate در web_admin برای مصرفِ پنل.
# تغییرِ این عدد باید همیشه عمدی و مستند باشد؛ همین محافظ است که
# افزودنِ ناخواستهٔ endpoint را لو می‌دهد.
_ROUTE_BASELINE = 501


def _walk_included_routes(routes, prefix: str = "") -> list:
    """فهرست واقعی (method, path) با بازکردن routerهای تنبل.

    از FastAPI 0.141 به بعد `include_router` دیگر routeها را مسطح
    داخل `app.routes` نمی‌ریزد؛ یک شیء `_IncludedRouter` می‌گذارد که
    `path` آن "?" است و routerِ اصلی را تنبل نگه می‌دارد.

    شمارشِ سطح‌بالا به همین دلیل ۴ می‌داد به‌جای ۵۱۰ — عددی که در
    /api/health/deep نمایش داده می‌شد و کاملاً گمراه‌کننده بود.
    """
    out = []
    for r in routes:
        if type(r).__name__ == "_IncludedRouter":
            ctx = getattr(r, "include_context", None)
            pfx = getattr(ctx, "prefix", "") if ctx else ""
            out += _walk_included_routes(
                getattr(r.original_router, "routes", []),
                prefix + (pfx or ""),
            )
            continue
        path = prefix + (getattr(r, "path", "") or "")
        for m in getattr(r, "methods", None) or []:
            if m not in ("HEAD", "OPTIONS"):
                out.append((m, path))
    return out


def _count_api_operations() -> dict:
    """شماریک خط‌مبِ رگرسیون: ۴۵۰ عملیات OpenAPI (بدون گاردهای schema-less).

    دو عدد کنار هم، چون معیارهای متفاوتی‌اند و هر دو مفیدند:
      openapi_operations  — آنچه در /openapi.json مستند شده. این همان
                            خط‌مب مهاجرت است: پیش از تغییرات ۴۵۰ بود و
                            یک مهاجرت معماری نباید این عدد را جابه‌جا کند
      api_route_objects   — تعداد شیء route زیر /api در app.routes
                            (mountهای استاتیک شمرده نمی‌شوند)
    """
    paths = app.openapi()["paths"]
    ops = sum(len([m for m in v if m in
                   ("get", "post", "put", "patch", "delete", "head", "options")])
              for p, v in paths.items() if p.startswith("/api"))
    routes = len([p for _, p in _walk_included_routes(app.routes)
                  if p.startswith("/api")])
    return {"openapi_operations": ops, "api_route_objects": routes,
            "baseline_expected": _ROUTE_BASELINE,
            "routes_match_baseline": ops == _ROUTE_BASELINE}


# ──────────────────────────────────────────────────────────
#  🚂 مهاجرت Railway — گارد 404 برای /api/*
#
#  بدون این route، هر مسیر اشتباه زیر /api به دست handlerهای دیگر
#  یا (در صورت اضافه‌شدن catch-all ریشه در آینده) HTML مینی‌اپ
#  می‌افتاد. با این گارد، /api/nope همیشه JSON 404 است — یعنی یک
#  fetch شکست‌خورده هرگز «index.html با status 200» تحویل نمی‌دهد
#  که در فرانت به خطای رمزگشانی JSON منجر می‌شود.
#  include_in_schema=False → تعداد عملیات OpenAPI دست‌نخورده می‌ماند.
# ──────────────────────────────────────────────────────────
@app.api_route(
    "/api/{missing_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
async def _api_not_found(missing_path: str, request: Request):
    return JSONResponse(
        status_code=404,
        content={"detail": "not_found", "path": f"/api/{missing_path}"},
    )


# ══════════════════════════════════════════════════════════
#  🚂 مهاجرت Railway — سرو دو SPA روی یک سرویس
#
#     /app/*    → Telegram Mini App   (miniapp/dist)
#     /admin/*  → Web Admin           (webadmin/dist)  ← بدون تغییر
#     /api/*    → FastAPI              (routeهای بالاتر همین فایل)
#
#  چرا مینی‌اپ روی ریشه نیست؟
#  مینی‌اپ routeهایی مثل /admin، /admin/users و … دارد. اگر روی ریشه
#  سرو می‌شد، هر ورودی به /admin می‌توانست توسط SPA-fallback مینی‌اپ
#  قورت داده شود و وب‌ادمین عملاً دیده نشود. جدا بودن namespace،
#  تداخل را از ریشه حذف می‌کند.
#
#  ترتیب ثبت (FastAPI از بالا به پایین تطبیق می‌دهد):
#     ۱) همه‌ی routerهای /api          ← هیچ‌وقت SPA نمی‌شوند
#     ۲) گارد 404 برای /api/*           ← بالا تعریف شده
#     ۳) mount /admin                   ← Web Admin، اولویت مطلق
#     ۴) mount /app                     ← فقط پیشوند خودش
#  mount با پیشوند /app هر مسیری جز /app/… را نمی‌گیرد، پس /admin
#  و /api هرگز توسط مینی‌اپ shadow نمی‌شوند.
# ══════════════════════════════════════════════════════════
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WA_DIST = os.path.join(_ROOT, "webadmin", "dist")
_MA_DIST = os.path.join(_ROOT, "miniapp", "dist")

#: درخواست‌هایی که پسوند فایل دارند، SPA fallback نمی‌گیرند.
#: چرا؟ اگر deploy نیمه‌کاره بماند، درخواست /app/assets/index-<hash>.js
#: که وجود ندارد با fallback به index.html پاسخ داده می‌شد: مرورگر
#: HTML را به‌عنوان JS parse می‌کرد و کاربر «Unexpected token '<'»
#: می‌دید — یعنی یک صفحه‌ی کاملاً خراب، بی‌سرنخ. حالا همان حالت
#: 404 است: شکستِ واضح، و «نگهبان مونت» داخل index.html پیام بازیابی
#: را نشان می‌دهد. با SPA_ASSET_404=0 می‌توان به رفتار قبلی برگشت.
_SPA_ASSET_404 = os.getenv("SPA_ASSET_404", "1").strip().lower() not in ("0", "false", "no", "off")
_EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,8}$")


class _SpaStaticFiles(StaticFiles):
    """StaticFiles با fallback به index.html، اما نه برای فایلِ درخواستی.

    مسیرهای بدون پسوند (= route منطقی SPA) → index.html
    مسیرهای با پسوند (= asset)             → 404 واقعی
    """

    async def get_response(self, path: str, scope):   # noqa: D102
        from starlette.exceptions import HTTPException as StarletteHTTPException
        from starlette.responses import Response as _Resp

        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            if _SPA_ASSET_404 and _EXT_RE.search(path.split("?")[0]):
                raise
            try:
                return await super().get_response("index.html", scope)
            except StarletteHTTPException:
                # index.html هم نیست → بیلد انجام نشده؛ 405 مثل قبل نه، 404 روشن
                return _Resp(status_code=404, content=b"")


def _mount_spa(prefix: str, dist: str, name: str, state: dict) -> bool:
    """اگر بیلد موجود است mount می‌کند؛ در غیر این صورت False."""
    ok = os.path.isdir(dist) and os.path.isfile(os.path.join(dist, "index.html"))
    state["built"] = ok
    state["path"] = os.path.relpath(dist, _ROOT)
    if ok:
        app.mount(prefix, _SpaStaticFiles(directory=dist, html=True), name=name)
    return ok


#: وضعیت بیلدها برای /api/health — در زمان import یک‌بار محاسبه می‌شود
#: (ls‌کردنِ dir در هر healthcheck بی‌مصرف است).
_MINIAPP_DIST_STATE: dict = {"built": False, "path": "miniapp/dist"}
_WEBADMIN_DIST_STATE: dict = {"built": False, "path": "webadmin/dist"}

# اول /admin (تا مینی‌اپ هیچ‌وقت فرصت تصاحب این پیشوند را پیدا نکند)
_WA_MOUNTED = _mount_spa("/admin", _WA_DIST, "web-admin-spa", _WEBADMIN_DIST_STATE)
# بعد /app
_MA_MOUNTED = _mount_spa("/app", _MA_DIST, "mini-app-spa", _MINIAPP_DIST_STATE)


if not _WA_MOUNTED:
    # رفتار قبلی حفظ شد (پاسخ تشخیصی به‌جای 404 بی‌نام‌ونشان)، فقط
    # با status دقیق‌تر و راهنمای build.
    @app.get("/admin", include_in_schema=False)
    @app.get("/admin/", include_in_schema=False)
    async def _wa_not_built():
        return JSONResponse(
            status_code=503,
            content={
                "detail": "web-admin build not present (webadmin/dist)",
                "hint": "build it: cd webadmin && npm ci && npm run build",
            },
        )



if not _MINIAPP_DIST_STATE["built"]:
    @app.get("/app", include_in_schema=False)
    @app.get("/app/", include_in_schema=False)
    async def _ma_not_built():
        return JSONResponse(
            status_code=503,
            content={
                "detail": "mini_app_build_not_present",
                "hint": "miniapp/dist/index.html not found — build it "
                        "(cd miniapp && npm ci && npm run build) or let the "
                        "Docker image build it",
                "expected": os.path.relpath(_MA_DIST, _ROOT),
            },
        )


# ──────────────────────────────────────────────────────────
#  ریشه‌ی دامنه → مینی‌اپ
#  (روی دامنه‌ی Railway، کاربر/لینک قدیمی ممکن است / را بزند؛
#   302 به /app/ او را به مقصد می‌رساند. /admin و /api دست‌نخورده‌اند.)
# ──────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def _root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/app/", status_code=307)


# ──────────────────────────────────────────────────────────
#  🗂️ سربرگ‌های کشِ فایل‌های استاتیک مینی‌اپ
#  معادل رفتار vercel.json قبلی، تا حذف Vercel تغییر رفتاری ایجاد نکند:
#    /app/assets/<hash>  → immutable، یک‌ساله (اسم با hash عوض می‌شود)
#    بقیه‌ی /app/*        → must-revalidate (تا deploy تازه سریع دیده شود)
# ──────────────────────────────────────────────────────────
@app.middleware("http")
async def _spa_cache_headers(request, call_next):
    resp = await call_next(request)
    try:
        path = _raw_path(request)   # 🛡 AUDIT-R4 — مسیر خام (ضدِ Host-header confusion)
    except Exception:
        path = ""
    if path.startswith("/app/assets/") or path.startswith("/admin/assets/"):
        resp.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
    elif path == "/app" or path.startswith("/app/") or path == "/admin" or path.startswith("/admin/"):
        if resp.headers.get("Cache-Control") is None and resp.status_code == 200:
            resp.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
    # 📱 Telegram Mini App در WebView باز می‌شود ⇒ هرگز نباید
    # X-Frame-Options/CSPframe-ancestors روی /app/* بگذاریم.
    # (پالیسی امنیتی وب‌ادمین عمداً به اینجا سرایت نمی‌کند.)
    return resp


# 🛡 W1 — global rate limit (120/min per IP on /api/*) — best-effort
@app.middleware("http")
async def _w1_rate_limit(request, call_next):
    if _rl_check_global is not None:
        try:
            await _rl_check_global(request)
        except Exception as e:
            # rate limited → return 429 (preserves Retry-After header)
            from fastapi import HTTPException as _HE
            if isinstance(e, _HE) and getattr(e, "status_code", None) == 429:
                from fastapi.responses import JSONResponse as _JR
                return _JR(status_code=429, content={"detail": "rate_limited"}, headers=getattr(e, "headers", None) or {"Retry-After": "60"})
            # other errors → fail-open
            pass
    return await call_next(request)


# ──────────────────────────────────────────────────────────
#  👁️ حضور process ربات (برای /api/health/deep)
#  همان ایده‌ی /api/admin/bot-status، اما کش‌شده: سلامت‌سنجی هر
#  چند ثانیه نباید هر بار /proc را اسکن کند.
# ──────────────────────────────────────────────────────────
_BOT_PROC_CACHE = {"at": 0.0, "ok": False, "pid": None}
_BOT_PROC_TTL = float(os.getenv("BOT_PROC_CACHE_TTL", "10"))


def _bot_process_ok() -> tuple[bool, int | None]:
    now = time.monotonic()
    if now - _BOT_PROC_CACHE["at"] < _BOT_PROC_TTL:
        return _BOT_PROC_CACHE["ok"], _BOT_PROC_CACHE["pid"]
    ok, pid = False, None
    try:
        import psutil

        me = os.getpid()
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                args = p.info.get("cmdline") or []
                name = (p.info.get("name") or "").lower()
                exe = os.path.basename(args[0]).lower() if args else ""
                if p.info.get("pid") == me:
                    continue
                if ("python" in name or exe.startswith("python")) and any(
                    os.path.basename(str(a)) == "bot.py" for a in args[1:]
                ):
                    ok, pid = True, p.info.get("pid")
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        ok, pid = False, None
    _BOT_PROC_CACHE.update({"at": now, "ok": ok, "pid": pid})
    return ok, pid
