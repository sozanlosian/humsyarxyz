# -*- coding: utf-8 -*-
"""
📂 Dedicated Telegram File Rename Pipeline — HamsYar
فقط همین ماژول از Local Bot API استفاده می‌کند؛ بقیه ربات همچنان Cloud API.

Pipeline:
old file_id → download (via Local API) → temp bytes → upload with new filename → new file_id → verify
"""

import os
import logging
import httpx

logger = logging.getLogger(__name__)

# Cloud API (normal bot)
CLOUD_TOKEN = os.getenv("TELEGRAM_TOKEN", "") or os.getenv("BOT_TOKEN", "")
CLOUD_API = f"https://api.telegram.org/bot{CLOUD_TOKEN}"

# Local API (only rename) — اگر ست نباشد، از Cloud استفاده می‌کنیم ولی 20MB limit دارد
def _local_available() -> bool:
    return bool((os.getenv("TELEGRAM_LOCAL_API_URL") or "").strip() and CLOUD_TOKEN)

def _get_local_url() -> str:
    return (os.getenv("TELEGRAM_LOCAL_API_URL") or "").strip().rstrip("/")

def _api_base_for_rename() -> str:
    """فقط Rename باید Local را ترجیح دهد."""
    if _local_available():
        return f"{_get_local_url()}/bot{CLOUD_TOKEN}"
    return CLOUD_API

def _file_base_for_rename() -> str:
    """برای دانلود فایل: Local -> {LOCAL_URL}/file/bot<token>/ ; Cloud -> https://api.telegram.org/file/bot<token>/"""
    if _local_available():
        return f"{_get_local_url()}/file/bot{CLOUD_TOKEN}"
    return f"https://api.telegram.org/file/bot{CLOUD_TOKEN}"

async def _get_file_path(file_id: str, base_api: str) -> str | None:
    if not file_id or not CLOUD_TOKEN:
        return None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, read=30)) as client:
            r = await client.get(f"{base_api}/getFile", params={"file_id": file_id})
            if r.status_code != 200:
                logger.warning("RENAME_GETFILE_FAIL status=%s file_id=%s api=%s", r.status_code, file_id[:12], "local" if _local_available() else "cloud")
                return None
            js = r.json()
            if not js.get("ok"):
                logger.warning("RENAME_GETFILE_NOT_OK file_id=%s desc=%s", file_id[:12], js.get("description","")[:120])
                return None
            return js["result"].get("file_path")
    except Exception as e:
        logger.warning("RENAME_GETFILE_EXC %s file_id=%s", type(e).__name__, file_id[:12])
        return None

async def download_for_rename(file_id: str) -> bytes | None:
    """دانلود بایت‌ها مخصوص Rename — ترجیحا Local (تا 2GB)."""
    if not file_id:
        return None
    base_api = _api_base_for_rename()
    file_path = await _get_file_path(file_id, base_api)
    if not file_path:
        return None
    file_base = _file_base_for_rename()
    url = f"{file_base}/{file_path}"
    try:
        # Local API ممکنه فایل را روی دیسک نگه دارد — استریم با cap 2GB
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, read=300, write=60), follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    logger.warning("RENAME_DOWNLOAD_STATUS %s file_id=%s", resp.status_code, file_id[:12])
                    return None
                chunks = []
                total = 0
                async for chunk in resp.aiter_bytes(chunk_size=1024*1024):
                    total += len(chunk)
                    if total > 2000*1024*1024:
                        logger.warning("RENAME_DOWNLOAD_TOO_LARGE file_id=%s", file_id[:12])
                        return None
                    chunks.append(chunk)
                data = b"".join(chunks)
                logger.info("RENAME_DOWNLOAD_OK size=%s file_id=%s via=%s", total, file_id[:12], "local" if _local_available() else "cloud")
                return data
    except Exception as e:
        logger.warning("RENAME_DOWNLOAD_EXC %s file_id=%s", type(e).__name__, file_id[:12])
        return None

async def upload_with_new_filename(chat_id: int, new_filename: str, data: bytes, mime_type: str = "application/octet-stream") -> tuple[str | None, str | None]:
    """آپلود با نام جدید مخصوص Rename — ترجیحا Local. برمی‌گرداند (new_file_id, new_file_name)."""
    if not data or not chat_id or not new_filename:
        return None, None
    base_api = _api_base_for_rename()
    # Local API هم sendDocument با multipart می‌خواهد
    try:
        timeout = httpx.Timeout(connect=15.0, read=180.0, write=300.0, pool=15.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{base_api}/sendDocument",
                data={"chat_id": str(chat_id), "disable_notification": "true"},
                files={"document": (new_filename, data, mime_type)},
            )
        if resp.status_code != 200:
            try:
                desc = resp.json().get("description","")[:200]
            except: desc = resp.text[:200]
            logger.warning("RENAME_UPLOAD_STATUS %s desc=%s via=%s", resp.status_code, desc, "local" if _local_available() else "cloud")
            return None, None
        js = resp.json()
        if not js.get("ok"):
            logger.warning("RENAME_UPLOAD_NOT_OK via=%s", "local" if _local_available() else "cloud")
            return None, None
        result = js["result"]
        # document field
        doc = result.get("document")
        if not doc:
            logger.warning("RENAME_UPLOAD_NO_DOCUMENT")
            return None, None
        new_file_id = doc.get("file_id")
        new_file_name = doc.get("file_name")
        # Verify filename
        if new_file_name != new_filename:
            logger.warning("RENAME_FILENAME_MISMATCH expected=%s got=%s", new_filename, new_file_name)
            # باز هم file_id را برمی‌گردانیم چون file_name نزدیک است، ولی لاگ می‌کنیم
        # سایلنت: پیام موقت را پاک کن
        try:
            msg_id = result.get("message_id")
            if msg_id:
                async with httpx.AsyncClient(timeout=httpx.Timeout(5, read=10)) as c2:
                    await c2.post(f"{base_api}/deleteMessage", data={"chat_id": str(chat_id), "message_id": str(msg_id)})
        except Exception:
            pass
        logger.info("RENAME_UPLOAD_OK new_file_id=%s new_name=%s via=%s", (new_file_id or "")[:12], new_file_name, "local" if _local_available() else "cloud")
        return new_file_id, new_file_name
    except Exception as e:
        logger.warning("RENAME_UPLOAD_EXC %s via=%s", type(e).__name__, "local" if _local_available() else "cloud")
        return None, None

async def _rename_via_mtproto(chat_id: int, old_file_id: str, new_filename: str) -> tuple[str | None, str | None]:
    """Fallback MTProto برای فایل‌های بزرگ (>20MB) — بدون نیاز به Local Bot API binary، همون منابع Railway."""
    api_id = (os.getenv("TELEGRAM_API_ID") or "").strip()
    api_hash = (os.getenv("TELEGRAM_API_HASH") or "").strip()
    token = CLOUD_TOKEN
    if not api_id or not api_hash or not token:
        logger.info("MTPROTO_SKIP missing API_ID/HASH")
        return None, None
    try:
        api_id_int = int(api_id)
    except:
        logger.warning("MTPROTO_BAD_API_ID")
        return None, None
    try:
        from pyrogram import Client
        from io import BytesIO
        # in_memory session، بدون فایل session روی دیسک
        async with Client(
            name="rename_mtproto",
            api_id=api_id_int,
            api_hash=api_hash,
            bot_token=token,
            workdir="/tmp",
            in_memory=True,
            no_updates=True,
        ) as app:
            # دانلود مستقیم با file_id (تا 2GB via MTProto)
            file_obj = await app.download_media(old_file_id, in_memory=True)
            if not file_obj:
                logger.warning("MTPROTO_DOWNLOAD_NONE file_id=%s", old_file_id[:12])
                return None, None
            try:
                data = bytes(file_obj.getbuffer())
            except:
                # file_obj may be BytesIO already
                data = file_obj.read() if hasattr(file_obj, 'read') else bytes(file_obj)
            if not data:
                logger.warning("MTPROTO_DOWNLOAD_EMPTY")
                return None, None
            logger.info("MTPROTO_DOWNLOAD_OK size=%s file_id=%s", len(data), old_file_id[:12])
            bio = BytesIO(data)
            bio.name = new_filename
            # آپلود با نام جدید به چت ادمین (سایلنت)
            msg = await app.send_document(chat_id=chat_id, document=bio, file_name=new_filename, disable_notification=True)
            new_id = None
            new_name = None
            if getattr(msg, 'document', None):
                new_id = msg.document.file_id
                new_name = getattr(msg.document, 'file_name', new_filename)
            elif getattr(msg, 'video', None):
                new_id = msg.video.file_id
                new_name = getattr(msg.video, 'file_name', new_filename)
            elif getattr(msg, 'audio', None):
                new_id = msg.audio.file_id
                new_name = getattr(msg.audio, 'file_name', new_filename)
            else:
                logger.warning("MTPROTO_UPLOAD_NO_MEDIA")
                return None, None
            # سایلنت: پاک کردن پیام موقت
            try:
                await app.delete_messages(chat_id, msg.id)
            except:
                pass
            logger.info("MTPROTO_UPLOAD_OK new_id=%s name=%s", (new_id or "")[:12], new_name)
            return new_id, new_name
    except Exception as e:
        logger.warning("MTPROTO_EXC %s", type(e).__name__)
        import traceback
        logger.debug(traceback.format_exc())
        return None, None

async def rename_telegram_file(chat_id: int, old_file_id: str, new_filename: str, mime_type: str = "application/octet-stream") -> tuple[str | None, str | None]:
    """
    Pipeline اختصاصی Rename — فقط همین تابع از Local API/MTProto استفاده می‌کند.
    برمی‌گرداند (new_file_id, new_file_name) یا (None, None) اگر Fail.
    هیچ Crash ای برای ربات ایجاد نمی‌کند.
    """
    if not old_file_id or not new_filename:
        return None, None
    # اگر Local URL ست نیست، باز هم تلاش می‌کنیم با Cloud (تا 20MB) — ولی لاگ می‌کنیم که محدوده
    # 1. تلاش با Local/Cloud (تا 20MB یا اگر Local ست باشد تا 2GB)
    if not _local_available():
        logger.info("RENAME_TRY_CLOUD file_id=%s name=%s (fallback to MTProto for >20MB)", old_file_id[:12], new_filename)
    data = await download_for_rename(old_file_id)
    if data is not None:
        new_id, new_name = await upload_with_new_filename(chat_id, new_filename, data, mime_type)
        if new_id:
            return new_id, new_name
        logger.warning("RENAME_CLOUD_UPLOAD_FAIL try MTProto")
    else:
        logger.warning("RENAME_CLOUD_DOWNLOAD_FAIL try MTProto file_id=%s", old_file_id[:12])
    # 2. Fallback MTProto (Pyrogram) برای فایل‌های بزرگ — بدون نیاز به باینری Local
    mt_id, mt_name = await _rename_via_mtproto(chat_id, old_file_id, new_filename)
    if mt_id:
        return mt_id, mt_name
    logger.warning("RENAME_ALL_FAILED name=%s", new_filename)
    return None, None
