# -*- coding: utf-8 -*-
"""📥 URL-Import — پایپ‌لاین درون‌ریزی محتوای راه‌دور (Canonical Service).

مسیر: URL → اعتبارسنجی امن (SSRF) → دانلود استریمی با سقف سخت →
اعتبارسنجی فایل (magic bytes) → هش/تکراری‌یابی → آپلود تلگرام
(همان upload_and_get_file_id موجود) → ثبت محتوا با همان db.*های
موجود (qbank/bs/ref) → audit.

اصول (§spec): سرور منتقل می‌کند نه ادمین؛ Job سندِ حقیقت پیشرفت است؛
idempotency با idem_key؛ retry با backoff فقط برای خطاهای گذرا؛
cancel با Task-registry؛ cleanup تضمینی temp؛ لاگ بدون query-string.

این ماژول تنها نقطه‌ی اجرای پایپ‌لاین است — روتر وب/بات/مینی‌اپ همه
به همین سرویس وصل می‌شوند (§106)."""
import asyncio
import hashlib
import ipaddress
import logging
import os
import re
import shutil
import socket
import tempfile
from urllib.parse import urlparse, urljoin, unquote

import httpx

from database import db
from time_utils import utc_now_iso

logger = logging.getLogger("url_import")

BOT_UA = "HumsYar-ContentImport/1.0 (+server-side ingestion)"

# ── تنظیمات (همه قابل تنظیم؛ عدد سخت ممنوع) ─────────────────────
MAX_REDIRECTS = int(os.getenv("URLIMPORT_MAX_REDIRECTS", "5"))
CONNECT_TIMEOUT = float(os.getenv("URLIMPORT_CONNECT_TIMEOUT", "10"))
READ_TIMEOUT = float(os.getenv("URLIMPORT_READ_TIMEOUT", "30"))
OVERALL_TIMEOUT = float(os.getenv("URLIMPORT_OVERALL_TIMEOUT", "600"))
MAX_RETRIES = int(os.getenv("URLIMPORT_MAX_RETRIES", "3"))
BACKOFF_S = [2, 5, 12]
def _trusted_hosts() -> set:
    """فقط برای تست/توسعه: میزبان‌های مجاز صریح (host:port) — پیش‌فرض
    خالی؛ lazy خوانده می‌شود تا بدون restart قابل تنظیم باشد."""
    return {h.strip() for h in
            os.getenv("URLIMPORT_TRUSTED_HOSTS", "").split(",") if h.strip()}

DEFAULT_MAX_MB = 45  # سقف deployment رسمی Bot API (sendDocument ≈ 50MB؛
# endpointهای موجود محتوا 45MB را enforce می‌کنند — همان عدد، نه بیشتر)

TERMINAL = {"completed", "failed", "cancelled", "duplicate"}
RUNNING = {"created", "validating", "downloading", "validating_file",
           "uploading", "registering"}

# extensionهای مجاز بر اساس انواع واقعی سیستم محتوا (آیکون‌ها/مدل‌ها):
# pdf/doc(x)/ppt(x)/zip/تصویر/صدا/ویدیو — چیزی خارج از این یعنی رد.
ALLOWED_EXT = {"pdf", "doc", "docx", "ppt", "pptx", "zip",
               "mp4", "mp3", "m4a", "jpg", "jpeg", "png"}
MAGIC = {
    "pdf": (b"%PDF",),
    "zip": (b"PK\x03\x04",),
    "docx": (b"PK\x03\x04",), "pptx": (b"PK\x03\x04",),
    "png": (b"\x89PNG",),
    "jpg": (b"\xff\xd8\xff",), "jpeg": (b"\xff\xd8\xff",),
    "mp3": (b"ID3", b"\xff\xfb", b"\xff\xf3"),
    "mp4": (b"ftyp",), "m4a": (b"ftyp",),
}


class UrlImportError(Exception):
    def __init__(self, code: str, message: str, retryable=False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


# ═══════════════ SSRF / اعتبارسنجی URL (§7/8/62) ═══════════════

def _ip_blocked(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return True
    return (ip.is_private or ip.is_loopback or ip.is_link_local or
            ip.is_reserved or ip.is_multicast or ip.is_unspecified or
            str(ip) == "169.254.169.254")


def redact_url(url: str) -> str:
    """لاگ امن (§69): فقط host+path — query (توکن signed) هرگز."""
    try:
        p = urlparse(url)
        return f"{p.hostname or ''}{p.path or ''}"[:200]
    except Exception:
        return "<invalid>"


async def validate_url(url: str) -> urlparse:
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise UrlImportError("INVALID_URL", "پروتکل پشتیبانی نمی‌شود (فقط http/https)")
    host = (p.hostname or "").lower().strip('.')
    if not host or len(host) > 253 or re.search(r"[^a-z0-9.\-:\[\]]", host):
        raise UrlImportError("INVALID_URL", "hostname نامعتبر است")
    if host in ("localhost",) or host.endswith(".localhost") or host.endswith(".internal"):
        raise UrlImportError("SSRF_BLOCKED", "دسترسی به این میزبان مجاز نیست")
    port = p.port or (443 if p.scheme == "https" else 80)
    if f"{host}:{port}" in _trusted_hosts():
        return p  # hook تست/توسعه — فقط با env صریح
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise UrlImportError("INVALID_URL", "نام میزبان قابل_resolve نیست")
    for info in infos:
        addr = info[4][0]
        if _ip_blocked(addr):
            raise UrlImportError("SSRF_BLOCKED",
                                 "آدرس مقصد در بازه‌ی ممنوع است (private/loopback/link-local)")
    return p


def sanitize_filename(name: str, fallback: str) -> str:
    """§16 — بدون path traversal/null/control؛ هرگز مسیر مستقیم remote."""
    name = (name or "").replace("\x00", "").strip()
    name = name.replace("\\", "/").split("/")[-1].split("\\")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    name = name.strip().strip('"')
    if not name or name in (".", "..") or len(name) > 180:
        name = fallback
    return name or fallback


# ═══════════════ Job CRUD ═══════════════

def _timeline(doc: dict, event: str) -> None:
    doc.setdefault("timeline", []).append(
        {"at": utc_now_iso(), "event": event})


async def create_import_job(admin: dict, payload: dict, idem_key: str) -> dict:
    """ساخت job (ایدمپوتنت با idem_key) — بدون شروع خودکار؛ روتر
    بلافاصله start را صدا می‌زند (§24: پاسخ سریع + worker جدا)."""
    if idem_key:
        existing = await db.url_import_jobs.find_one({"idem_key": idem_key})
        if existing:
            return existing
    kind = payload.get("kind", "qbank")
    if kind not in ("qbank", "bs", "ref"):
        raise UrlImportError("INVALID_KIND", "نوع محتوای مقصد نامعتبر است")
    doc = {
        "admin_id": admin["id"],
        "intake": payload.get("intake") or "",
        "kind": kind,
        "target_id": payload.get("target_id") or "",
        "meta": {k: (payload.get(k) or "") for k in
                 ("lesson", "topic", "description", "extra_info",
                  "ctype", "lang", "volume", "filename")},
        "url": payload["url"],
        "url_safe": redact_url(payload["url"]),
        "status": "created",
        "progress": {"phase": "created", "bytes": 0, "total": None,
                     "percent": 0},
        "sha256": None, "size": None, "filename": None, "mime": None,
        "telegram_file_id": None, "content_id": None,
        "error": None, "retries": 0, "timeline": [],
        "idem_key": idem_key or "",
        "created_at": utc_now_iso(), "started_at": None, "finished_at": None,
    }
    _timeline(doc, "import_created")
    try:
        r = await db.url_import_jobs.insert_one(doc)
        doc["_id"] = r.inserted_id
    except Exception:
        # برخورد idem هم‌زمان — سند قبلی را برگردان
        found = await db.url_import_jobs.find_one({"idem_key": idem_key})
        if found:
            return found
        raise
    return doc


async def get_import_job(job_id: str) -> dict | None:
    from bson import ObjectId
    try:
        return await db.url_import_jobs.find_one({"_id": ObjectId(job_id)})
    except Exception:
        return None


async def _patch(job_id, fields: dict, event: str = None) -> None:
    upd = {"$set": fields}
    if event:
        upd["$push"] = {"timeline": {"at": utc_now_iso(), "event": event}}
    from bson import ObjectId
    await db.url_import_jobs.update_one({"_id": ObjectId(job_id)}, upd)


# ═══════════════ اجرای پایپ‌لاین ═══════════════

_tasks: dict[str, asyncio.Task] = {}
_sem: asyncio.Semaphore | None = None


def _semaphore() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(
            int(os.getenv("URLIMPORT_MAX_CONCURRENT", "2")))
    return _sem


async def _telegram_upload(admin_id: int, filename: str, raw: bytes,
                           mime: str) -> str | None:
    """پوششِ همان helper موجود — تست‌ها همین نقطه را stub می‌کنند."""
    from api.telegram_send import upload_and_get_file_id
    return await upload_and_get_file_id(admin_id, filename, raw, mime)


def _check_magic(head: bytes, ext: str) -> bool:
    sigs = MAGIC.get(ext)
    if not sigs:
        return True  # نوع بدون امضای ثابت (doc/ppt/…) — extension کافی
    if ext in ("mp4", "m4a"):
        return head[4:8] == sigs[0]
    return any(head.startswith(s) for s in sigs)


async def _download_stream(client: httpx.AsyncClient, url: str, path: str,
                           max_bytes: int, job_id: str) -> tuple[int, str, str]:
    """دانلود با redirect کنترل‌شده + شمارنده‌ی سخت بایت (§9/12/64)."""
    for _hop in range(MAX_REDIRECTS + 1):
        await validate_url(url)  # هر هاپ دوباره (§62)
        req = client.build_request("GET", url, headers={"User-Agent": BOT_UA})
        resp = await client.send(req, stream=True)
        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("location")
            await resp.aclose()
            if not loc:
                raise UrlImportError("DOWNLOAD_FAILED", "redirect بدون location")
            url = urljoin(url, loc)
            continue
        if resp.status_code == 404:
            await resp.aclose(); raise UrlImportError("DOWNLOAD_NOT_FOUND", "فایل در مقصد پیدا نشد")
        if resp.status_code in (401, 403):
            await resp.aclose(); raise UrlImportError("DOWNLOAD_FORBIDDEN", "سرور مقصد اجازه‌ی دانلود نداد")
        if resp.status_code == 429:
            await resp.aclose(); raise UrlImportError("DOWNLOAD_RATE", "مقصد ما را محدود کرد", retryable=True)
        if resp.status_code >= 500:
            await resp.aclose(); raise UrlImportError("DOWNLOAD_5XX", "خطای سرور مقصد", retryable=True)
        if resp.status_code != 200:
            await resp.aclose(); raise UrlImportError("DOWNLOAD_FAILED", f"HTTP {resp.status_code}")
        # Content-Length فقط hint (§64)
        cl = resp.headers.get("content-length")
        total = int(cl) if cl and cl.isdigit() else None
        if total and total > max_bytes:
            await resp.aclose()
            raise UrlImportError("DOWNLOAD_TOO_LARGE", "حجم فایل از سقف پردازش بیشتر است")
        ctype = resp.headers.get("content-type", "") or ""
        disp = resp.headers.get("content-disposition", "") or ""
        written = 0
        sha = hashlib.sha256()
        with open(path, "wb") as fh:
            async for chunk in resp.aiter_bytes(64 * 1024):
                written += len(chunk)
                if written > max_bytes:  # سقف سخت حین stream
                    await resp.aclose()
                    raise UrlImportError("DOWNLOAD_TOO_LARGE",
                                         "حجم واقعی فایل از سقف بیشتر شد")
                sha.update(chunk)
                fh.write(chunk)
                if written % (512 * 1024) < 64 * 1024:
                    await _patch(job_id, {"progress": {
                        "phase": "downloading", "bytes": written,
                        "total": total,
                        "percent": min(60, int(written * 60 / total))
                        if total else None}})
        await resp.aclose()
        return written, sha.hexdigest(), (ctype.split(";")[0].strip(), disp)
    raise UrlImportError("REDIRECT_LOOP", f"بیش از {MAX_REDIRECTS} redirect")


def _filename_from_disp(disp: str) -> str:
    m = re.search(r"filename\*?=(?:UTF-8''|\"?)([^\";]+)", disp or "", re.I)
    return unquote(m.group(1)).strip() if m else ""


async def _register_content(job: dict, file_id: str, filename: str,
                            mime: str, size: int) -> str:
    meta = job.get("meta") or {}
    if job["kind"] == "qbank":
        item = await db.qbank_file_add(
            intake=job.get("intake") or "", lesson=meta.get("lesson") or "درون‌ریزی URL",
            topic=meta.get("topic") or "درون‌ریزی URL",
            description=meta.get("description") or "",
            filename=filename, mime_type=mime, size=size,
            telegram_file_id=file_id, uploaded_by=job["admin_id"])
        return str(item["_id"])
    if job["kind"] == "bs":
        cid = await db.bs_add_content(job["target_id"], meta.get("ctype") or "pdf",
                                      file_id, meta.get("description") or "",
                                      meta.get("extra_info") or "")
        return str(cid)
    item = await db.ref_add_file(job["target_id"], meta.get("lang") or "fa",
                                 file_id, int(meta.get("volume") or 1),
                                 meta.get("description") or "")
    return str(item["_id"])


async def _run_pipeline(job_id: str) -> None:
    job = await get_import_job(job_id)
    if not job or job["status"] in TERMINAL:
        return
    tmp_root = tempfile.mkdtemp(prefix="humsyar-import-",
                                dir=os.getenv("URLIMPORT_TMP", "/tmp"))
    tmp_dir = tempfile.mkdtemp(prefix=f"{job_id}-", dir=tmp_root)
    attempt = 0
    try:
        while True:
            try:
                await _execute(job_id, job, tmp_dir)
                return
            except UrlImportError as e:
                if not e.retryable or attempt >= MAX_RETRIES:
                    await _patch(job_id, {
                        "status": "failed", "finished_at": utc_now_iso(),
                        "error": {"code": e.code, "message": e.message}},
                        f"import_failed:{e.code}")
                    logger.warning("url_import %s failed: %s %s",
                                   job_id, e.code, job.get("url_safe"))
                    return
                attempt += 1
                delay = BACKOFF_S[min(attempt - 1, len(BACKOFF_S) - 1)]
                await _patch(job_id, {"retries": attempt, "status": "created",
                                      "error": {"code": e.code,
                                                "message": f"retry {attempt} پس از {delay}s"}},
                             f"import_retry:{attempt}")
                await asyncio.sleep(delay)
                job = await get_import_job(job_id)
                if job["status"] == "cancelled":
                    return
            except asyncio.CancelledError:
                raise
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)  # §19/61 — کل درخت موقت


async def _execute(job_id: str, job: dict, tmp_dir: str) -> None:
    max_mb = int(await db.get_setting("url_import_max_mb", DEFAULT_MAX_MB) or
                 DEFAULT_MAX_MB)
    max_bytes = max_mb * 1024 * 1024

    await _patch(job_id, {"status": "validating", "started_at": utc_now_iso(),
                          "progress": {"phase": "validating", "bytes": 0,
                                       "total": None, "percent": 2}},
                 "download_started")
    await validate_url(job["url"])

    path = os.path.join(tmp_dir, "download.part")
    timeout = httpx.Timeout(connect=CONNECT_TIMEOUT, read=READ_TIMEOUT,
                            write=READ_TIMEOUT, pool=CONNECT_TIMEOUT)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        async with asyncio.timeout(OVERALL_TIMEOUT):
            size, sha, (ctype, disp) = await _download_stream(
                client, job["url"], path, max_bytes, job_id)

    # ── اعتبارسنجی فایل (§13/14/15/16) ──
    await _patch(job_id, {"status": "validating_file",
                          "progress": {"phase": "validating_file", "bytes": size,
                                       "total": size, "percent": 62}})
    with open(path, "rb") as fh:
        head = fh.read(16)
    fname_pref = _filename_from_disp(disp)
    from urllib.parse import urlparse as _up
    url_name = _up(job["url"]).path.rsplit("/", 1)[-1]
    admin_name = (job.get("meta") or {}).get("filename") or ""
    filename = sanitize_filename(
        fname_pref or url_name or admin_name,
        f"import-{job_id[:8]}.bin")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXT:
        raise UrlImportError("UNSUPPORTED_TYPE",
                             "این نوع فایل توسط سیستم محتوا پشتیبانی نمی‌شود")
    if not _check_magic(head, ext):
        raise UrlImportError("UNSUPPORTED_TYPE",
                             "امضای فایل با پسوند آن هم‌خوان نیست")
    # §50 — جزئیات job حتی در شکست قابل مشاهده باشد
    await _patch(job_id, {"sha256": sha, "size": size, "filename": filename,
                          "mime": ctype or "application/octet-stream"})

    # ── تکراری‌یابی (§21): هش در jobهای کامل‌شده ──
    dup = await db.url_import_jobs.find_one(
        {"sha256": sha, "status": "completed",
         "_id": {"$ne": job["_id"]}})
    if dup and not job.get("force"):
        await _patch(job_id, {"status": "duplicate",
                              "sha256": sha, "size": size,
                              "finished_at": utc_now_iso(),
                              "duplicate_of": str(dup["_id"]),
                              "telegram_file_id": dup.get("telegram_file_id"),
                              "error": {"code": "DUPLICATE_FILE",
                                        "message": "این فایل قبلاً درون‌ریزی شده است"}},
                     "import_duplicate")
        return

    # ── آپلود تلگرام (§33/40) — اگر checkpoint دارد، دوباره آپلود نکن (§80) ──
    file_id = job.get("telegram_file_id")
    if not file_id:
        await _patch(job_id, {"status": "uploading",
                              "progress": {"phase": "uploading", "bytes": size,
                                           "total": size, "percent": 70}},
                     "telegram_upload_started")
        with open(path, "rb") as fh:
            raw = fh.read()
        file_id = await _telegram_upload(job["admin_id"], filename, raw,
                                         ctype or "application/octet-stream")
        if not file_id:
            raise UrlImportError("TELEGRAM_UPLOAD_FAILED",
                                 "انتقال فایل به تلگرام ناموفق بود", retryable=True)
        await _patch(job_id, {"telegram_file_id": file_id},
                     "telegram_upload_completed")

    # ── ثبت محتوا (§41/42) ──
    await _patch(job_id, {"status": "registering",
                          "progress": {"phase": "registering", "bytes": size,
                                       "total": size, "percent": 95}})
    try:
        content_id = await _register_content(job, file_id, filename,
                                             ctype or "application/octet-stream",
                                             size)
    except Exception as exc:
        # آپلود موفق + ثبت ناموفق (§43): فایل تلگرام در checkpoint job
        # ماند؛ retry دستی بدون آپلود مجدد ثبت را کامل می‌کند.
        raise UrlImportError("CONTENT_REGISTRATION_FAILED",
                             "ثبت محتوا ناموفق بود؛ فایل تلگرام حفظ شد",
                             retryable=True) from exc
    await _patch(job_id, {"status": "completed", "content_id": content_id,
                          "sha256": sha, "size": size, "filename": filename,
                          "mime": ctype or "application/octet-stream",
                          "finished_at": utc_now_iso(),
                          "progress": {"phase": "done", "bytes": size,
                                       "total": size, "percent": 100},
                          "error": None},
                 "import_completed")
    logger.info("url_import %s ok: %s %sB sha=%s", job_id,
                job.get("url_safe"), size, sha[:12])


# ═══════════════ start / cancel / retry / recover ═══════════════

async def start_import_job(job_id: str) -> None:
    if job_id in _tasks and not _tasks[job_id].done():
        return
    async def _go():
        async with _semaphore():
            await _run_pipeline(job_id)
    _tasks[job_id] = asyncio.create_task(_go())


async def cancel_import_job(job_id: str) -> bool:
    task = _tasks.get(job_id)
    if task and not task.done():
        task.cancel()
    job = await get_import_job(job_id)
    if not job or job["status"] in TERMINAL:
        return False
    await _patch(job_id, {"status": "cancelled",
                          "finished_at": utc_now_iso()}, "import_cancelled")
    return True


async def retry_import_job(job_id: str, force: bool = False) -> dict:
    job = await get_import_job(job_id)
    if not job:
        raise UrlImportError("JOB_NOT_FOUND", "job پیدا نشد")
    if job["status"] not in TERMINAL:
        raise UrlImportError("JOB_RUNNING", "job هنوز در جریان است")
    await _patch(job_id, {"status": "created", "error": None,
                          "finished_at": None,
                          **({"force": True} if force else {})},
                 f"import_retry_manual{'_force' if force else ''}")
    await start_import_job(job_id)
    return await get_import_job(job_id)


async def recover_stale_jobs() -> int:
    """§82 — jobهای نیمه‌کاره‌ی مانده از restart قبلی: failed با
    WORKER_RESTART تا ادمین دستی retry کند (نه اجرای کور)."""
    n = 0
    async for doc in db.url_import_jobs.find({"status": {"$in": sorted(RUNNING)}}):
        await db.url_import_jobs.update_one(
            {"_id": doc["_id"]},
            {"$set": {"status": "failed", "finished_at": utc_now_iso(),
                      "error": {"code": "WORKER_RESTART",
                                "message": "سرور هنگام اجرای job ری‌استارت شد؛ Retry بزنید"}},
             "$push": {"timeline": {"at": utc_now_iso(),
                                    "event": "import_worker_restart"}}})
        n += 1
    return n
