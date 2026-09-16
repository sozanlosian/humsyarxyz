"""📤 ارسال فایل به کاربر از طریق ربات — دقیقاً مطابق فرمتی که خود ربات
(basic_science.py و references.py) استفاده می‌کنه: کپشن رسمی، دکمه‌ی
گزارش ایراد/بازگشت، و انتخاب نوع پیام بر اساس نوع فایل."""
import logging
import os
import httpx
from database import db

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
BRAND_NAME = os.getenv("BRAND_NAME", "HumsyarX")

CONTENT_ICONS = {
    "video": "🎥 ویدیو کلاس",
    "ppt":   "📊 پاورپوینت",
    "pdf":   "📄 جزوه PDF",
    "note":  "📝 نکات",
    "test":  "🧪 تست",
    "voice": "🎙 ویس استاد",
}


async def upload_and_get_file_id(chat_id: int, filename: str, file_bytes: bytes,
                                  mime_type: str = "application/octet-stream") -> str | None:
    """
    آپلود فایل خام (که از مرورگر اومده) به تلگرام تا یه file_id قابل‌استفاده
    برگرده — چون تلگرام فقط فایلی که از طریق خود ربات فرستاده بشه رو
    file_id میده؛ آپلود مستقیم HTTP از مرورگر همچین چیزی تولید نمی‌کنه.
    فایل به‌صورت بی‌صدا برای خود ادمینی که آپلود کرده فرستاده می‌شه.

    🐛 FIX آپلود ویدیو — دو تغییر ریشه‌ای:
    ۱) timeout ساخت‌یافته: عدد ثابت ۶۰ برای ویدیوهای چندده‌مگابایتی
       کم بود (هم آپلود write و هم انتظار پاسخ تلگرام read). حالا هر
       مرحله کرانه‌ی مستقل و متناسب با فایل بزرگ دارد.
    ۲) علت واقعی شکست دیگر بلعیده نمی‌شود: status/description تلگرام و
       نوع خطای شبکه لاگ می‌شود (بدون token/URL — هرگز secret لاگ
       نمی‌شود) تا «آپلود ناموفق» در لاگ سرور قابل تشخیص باشد.
    """
    if not BOT_TOKEN:
        logger.warning("UPLOAD_FAILED stage=storage reason=missing_bot_token")
        return None
    size = len(file_bytes)
    try:
        timeout = httpx.Timeout(connect=15.0, read=180.0, write=300.0,
                                pool=15.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{API_BASE}/sendDocument",
                data={"chat_id": chat_id, "disable_notification": True},
                files={"document": (filename, file_bytes, mime_type)},
            )
    except httpx.HTTPError as e:
        # نوع خطا کافی است — URL حاوی token است و هرگز لاگ نمی‌شود
        logger.warning(
            "UPLOAD_FAILED stage=storage reason=telegram_http_error "
            "err=%s size=%s mime=%s", type(e).__name__, size, mime_type)
        return None
    if resp.status_code != 200:
        try:
            desc = str(resp.json().get("description") or "")[:200]
        except Exception:
            desc = ""
        logger.warning(
            "UPLOAD_FAILED stage=storage reason=telegram_status "
            "status=%s desc=%s size=%s mime=%s",
            resp.status_code, desc, size, mime_type)
        return None
    data = resp.json()
    if not data.get("ok"):
        logger.warning(
            "UPLOAD_FAILED stage=storage reason=telegram_not_ok size=%s",
            size)
        return None
    logger.info("STORAGE_UPLOAD_COMPLETED size=%s mime=%s", size, mime_type)
    file_id = data["result"]["document"]["file_id"]
    # سایلنت: پیام موقت را پاک کن تا چت ادمین شلوغ نشود (فایل روی سرور تلگرام می‌ماند)
    try:
        msg_id = data["result"].get("message_id")
        if msg_id:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5, read=10)) as _cl:
                await _cl.post(f"{API_BASE}/deleteMessage", data={"chat_id": chat_id, "message_id": msg_id})
    except Exception:
        pass
    return file_id


# 🌊 W8/UX-03 — mimeهای قابل‌پیش‌نمایش داخل مرورگر
PREVIEWABLE_MIME_PREFIXES = ('video/', 'audio/', 'image/')
PREVIEWABLE_MIME_EXACT = frozenset({'application/pdf'})


def is_previewable(mime_type: str, file_extension: str = '') -> bool:
    mime = (mime_type or '').strip().lower()
    if mime.startswith(PREVIEWABLE_MIME_PREFIXES) or mime in PREVIEWABLE_MIME_EXACT:
        return True
    # رکوردهای قدیمی بدون mime: حدس از پسوند
    ext = (file_extension or '').strip().lower().lstrip('.')
    return ext in {'mp4', 'webm', 'mkv', 'mov', 'm4v', 'mp3', 'ogg', 'oga',
                   'wav', 'm4a', 'flac', 'jpg', 'jpeg', 'png', 'gif', 'webp',
                   'pdf'}


# کش کوتاه file_path تلگرام (getFile برای هر seek تکرار نشود)
_FILE_URL_CACHE: dict = {}
_FILE_URL_CACHE_TTL = 300


async def telegram_file_url(file_id: str) -> str | None:
    """getFile → آدرس دانلود (توکن فقط سمت سرور). کش ۵دقیقه‌ای."""
    if not BOT_TOKEN or not file_id:
        return None
    import time as _t
    now = _t.monotonic()
    hit = _FILE_URL_CACHE.get(file_id)
    if hit and hit[1] > now:
        return hit[0]
    try:
        async with httpx.AsyncClient(
                timeout=httpx.Timeout(10, read=20)) as client:
            r = await client.get(f"{API_BASE}/getFile",
                                 params={"file_id": file_id})
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    try:
        if not r.json().get("ok"):
            return None
        file_path = r.json()["result"].get("file_path")
    except Exception:
        return None
    if not file_path:
        return None
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    if len(_FILE_URL_CACHE) > 2000:
        _FILE_URL_CACHE.clear()
    _FILE_URL_CACHE[file_id] = (url, now + _FILE_URL_CACHE_TTL)
    return url


def _preview_key() -> bytes:
    """کلید دامنه‌جدا از BOT_TOKEN (بدون env جدید)."""
    import hashlib as _h
    import hmac as _m
    return _m.new(b"humsyarx-preview-v1",
                  BOT_TOKEN.encode("utf-8"), _h.sha256).digest()


def preview_token(uid: int, scope: str, fid: str, exp: int) -> str:
    """توکن HMAC تک‌فایل با انقضا (برای <video>/<audio> بدون هدر)."""
    import hashlib as _h
    import hmac as _m
    msg = f"{int(uid)}:{scope}:{fid}:{int(exp)}".encode("utf-8")
    return _m.new(_preview_key(), msg, _h.sha256).hexdigest()[:48]


def verify_preview_token(token: str, uid: int, scope: str,
                         fid: str, exp: int) -> bool:
    import hmac as _m
    import time as _t
    try:
        if int(exp) < int(_t.time()):
            return False
    except (TypeError, ValueError):
        return False
    if not BOT_TOKEN:
        return False
    good = preview_token(uid, scope, fid, exp)
    return bool(token) and _m.compare_digest(str(token), good)


async def proxy_telegram_preview(file_id: str, mime: str, name: str,
                                 range_header: str | None = None):
    """🌊 W8/UX-03 — پاسخ استریمینگ فایل تلگرام با پشتیبانی Range.

    توکن فقط سمت سرور می‌ماند؛ خطا ⇒ HTTPException (502).
    صداکننده باید قبلاً دسترسی/ورودی را گارد کرده باشد.
    """
    from urllib.parse import quote
    from fastapi import HTTPException as _HTTP
    from fastapi.responses import StreamingResponse as _SR

    url = await telegram_file_url(file_id)
    if not url:
        raise _HTTP(status_code=502,
                    detail="دریافت فایل از تلگرام ناموفق بود")
    fwd = {"Range": range_header} if range_header else {}
    timeout = httpx.Timeout(connect=10.0, read=300.0, write=60.0, pool=10.0)
    client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
    try:
        req = client.build_request("GET", url, headers=fwd)
        upstream = await client.send(req, stream=True)
    except httpx.HTTPError:
        await client.aclose()
        raise _HTTP(status_code=502,
                    detail="دریافت فایل از تلگرام ناموفق بود")
    if upstream.status_code not in (200, 206):
        await upstream.aclose()
        await client.aclose()
        raise _HTTP(status_code=502,
                    detail="دریافت فایل از تلگرام ناموفق بود")

    async def _gen():
        try:
            async for chunk in upstream.aiter_bytes(256 * 1024):
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition":
            f"inline; filename*=UTF-8''{quote((name or 'file')[:120])}",
        "Cache-Control": "private, max-age=3600",
    }
    for h in ("Content-Length", "Content-Range"):
        if upstream.headers.get(h):
            headers[h] = upstream.headers[h]
    return _SR(_gen(), status_code=upstream.status_code,
               media_type=mime or "application/octet-stream",
               headers=headers)


async def download_telegram_file(file_id: str) -> bytes | None:
    """Download file bytes via getFile -> download. Streaming safe, 45MB cap."""
    if not BOT_TOKEN or not file_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, read=60, write=60)) as client:
            r = await client.get(f"{API_BASE}/getFile", params={"file_id": file_id})
            if r.status_code != 200 or not r.json().get("ok"):
                logger.warning("TG_GETFILE_FAILED file_id=%s", file_id[:16])
                return None
            file_path = r.json()["result"].get("file_path")
            if not file_path:
                return None
            url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
            # stream download with size cap
            async with httpx.AsyncClient(timeout=httpx.Timeout(15, read=180, write=60), follow_redirects=True) as dl:
                async with dl.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        return None
                    chunks = []
                    total = 0
                    async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                        total += len(chunk)
                        if total > 2000 * 1024 * 1024:
                            logger.warning("TG_DOWNLOAD_TOO_LARGE file_id=%s", file_id[:16])
                            return None
                        chunks.append(chunk)
                    return b"".join(chunks)
    except Exception as e:
        logger.warning("TG_DOWNLOAD_FAILED err=%s", type(e).__name__)
        return None


async def reupload_with_new_filename(chat_id: int, original_file_id: str,
                                     new_filename: str, mime_type: str = "application/octet-stream") -> str | None:
    """Download file_id and re-upload as document with new_filename. Returns new file_id."""
    data = await download_telegram_file(original_file_id)
    if data is None:
        return None
    return await upload_and_get_file_id(chat_id, new_filename, data, mime_type)


def _branding_caption(caption: str, item: dict) -> str:
    """Append branding line if enabled (separate from filename per spec)."""
    if not item.get("branding_enabled"):
        return caption
    # do not inject into filename, only caption
    brand = (BRAND_NAME or "HumsyarX").strip()
    if brand and brand not in caption:
        return caption + f"\n🏷 {brand}"
    return caption


async def _send(method: str, payload: dict) -> bool:
    if not BOT_TOKEN:
        return False
    # 🚀 PERF: shared client + keep-alive (before: new TLS per send → 22ms)
    try:
        from http_client import get_shared_client
        client = get_shared_client(timeout=httpx.Timeout(15, read=30))
        resp = await client.post(f"{API_BASE}/{method}", json=payload)
    except Exception:
        # fallback isolated client
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{API_BASE}/{method}", json=payload)
    if resp.status_code != 200:
        return False
    return bool(resp.json().get("ok"))


async def send_bs_content(chat_id: int, content_id: str, item: dict) -> bool:
    """محتوای علوم پایه — دقیقاً مثل _download_content توی basic_science.py"""
    ctype = item.get("type", "pdf")
    parts = [CONTENT_ICONS.get(ctype, "📎")]
    # prefer display filename if available (shown in caption as hint, but real name is Telegram file)
    display_hint = (item.get("display_file_name") or item.get("display_name") or "").strip()
    if display_hint:
        parts.append(f"📄 {display_hint}")
    if item.get("description"):
        parts.append(f"📝 {item['description']}")
    if item.get("extra_info"):
        parts.append(item["extra_info"])
    parts.append(f"📥 {item.get('downloads', 0)} دانلود")
    caption = "\n".join(parts)
    caption = _branding_caption(caption, item)

    protect = await db.get_setting("protect_content_enabled", True)
    reply_markup = {"inline_keyboard": [[
        {"text": "⚠️ گزارش ایراد", "callback_data": f"report:resource:{content_id}"}
    ]]}
    file_id = item.get("file_id", "")

    base = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML",
            "reply_markup": reply_markup, "protect_content": protect}

    if ctype == "video":
        return await _send("sendVideo", {**base, "video": file_id})
    if ctype == "voice":
        return await _send("sendVoice", {**base, "voice": file_id})
    return await _send("sendDocument", {**base, "document": file_id})


async def send_ref_file(chat_id: int, item: dict) -> bool:
    """رفرنس/منبع — دقیقاً مثل _download_ref توی references.py"""
    lang = item.get("lang", "fa")
    vol  = item.get("volume", 1)
    desc = item.get("description", "")
    dl   = item.get("downloads", 0)
    display_hint = (item.get("display_file_name") or item.get("display_name") or "").strip()

    lang_icon  = "🇮🇷" if lang == "fa" else "🌐"
    lang_label = "ترجمه فارسی" if lang == "fa" else "نسخه لاتین (اصلی)"

    caption_parts = [f"📘 {lang_icon} {lang_label} — جلد {vol}"]
    if display_hint:
        caption_parts.append(f"📄 {display_hint}")
    if desc:
        caption_parts.append(f"📝 {desc}")
    caption_parts.append(f"📥 {dl} دانلود")
    caption = "\n".join(caption_parts)
    caption = _branding_caption(caption, item)

    protect = await db.get_setting("protect_content_enabled", True)
    book_id = str(item.get("book_id", ""))
    reply_markup = None
    if book_id:
        reply_markup = {"inline_keyboard": [[
            {"text": "🔙 بازگشت به کتاب", "callback_data": f"ref:book:{book_id}"}
        ]]}

    payload = {"chat_id": chat_id, "document": item.get("file_id", ""),
               "caption": caption, "parse_mode": "HTML", "protect_content": protect}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return await _send("sendDocument", payload)
