"""Hoshyar AI endpoints for the Telegram Mini App.

The router deliberately keeps provider credentials and remote file URIs on the
backend. The Mini App only receives safe metadata for an active reference
file. Media is read with a hard byte limit and validated from its signature,
not merely from the client supplied Content-Type header.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import PurePath

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ai_solver import (
    MAX_INPUT_CHARS,
    MAX_MEDIA_BYTES,
    AIError,
    AiImageError,
    IMAGE_ASPECT_RATIOS,
    IMAGE_PROMPT_MAX,
    IMAGE_PROMPT_MIN,
    ai_claim_inflight,
    ai_is_inflight,
    ai_release_inflight,
    _clear_memory,
    _gemini_upload_file,
    _get_history,
    _remember,
    _transcode_ogg_opus_to_wav,
    ask_ai,
    check_and_consume_quota,
    generate_image,
    get_ai_config,
    record_token_usage,
)
from api.auth import get_current_user, require_feature  # 🌊 W7
from api.rate_limit import rate_limit_dependency, rate_limit_user
from database import db
from time_utils import now_utc, parse_machine_datetime, today_tehran, utc_now_iso

logger = logging.getLogger(__name__)
router = APIRouter()

REFERENCE_TTL_HOURS = 48
_READ_CHUNK_BYTES = 1024 * 1024

_SUPPORTED_AUDIO_MIMES = {
    "audio/aac",
    "audio/flac",
    "audio/m4a",
    "audio/mp3",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
    "audio/x-aac",
    "audio/x-m4a",
    "audio/x-wav",
}


class AskRequest(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=MAX_INPUT_CHARS,
    )
    # گفت‌وگوی چندگانه — مقدار None یا 'legacy' یعنی رشته‌ی مشترک قدیمی
    # با ربات؛ مقدار آیدی، یعنی گفت‌وگوی مستقل مینی‌اپ (مسیر افزایشی).
    conversation_id: str | None = Field(
        default=None,
        max_length=40,
    )


class ConversationCreate(BaseModel):
    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
    )


class ConversationPatch(BaseModel):
    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
    )
    pinned: bool | None = None
    archived: bool | None = None


class ReportRequest(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=MAX_INPUT_CHARS,
    )
    answer: str = Field(
        min_length=1,
        max_length=12000,
    )


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return default


def _public_history(items: list) -> list[dict]:
    result = []

    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue

        role = item.get("role")
        if role not in ("user", "assistant", "model"):
            continue

        result.append(
            {
                "role": "assistant" if role == "model" else role,
                "text": str(item.get("text") or "")[:12000],
            }
        )

    return result


def _parse_datetime(value) -> datetime | None:
    try:
        return parse_machine_datetime(value)
    except (TypeError, ValueError):
        return None


def _now_for(_value: datetime) -> datetime:
    return now_utc()


def _public_reference(document: dict | None) -> dict | None:
    """Return metadata without exposing Gemini private file URI."""

    if not isinstance(document, dict):
        return None

    if not document.get("uri"):
        return None

    uploaded_at = _parse_datetime(document.get("at"))

    expires_at = (
        uploaded_at + timedelta(hours=REFERENCE_TTL_HOURS)
        if uploaded_at
        else None
    )

    expired = bool(
        expires_at
        and _now_for(expires_at) >= expires_at
    )

    return {
        "name": str(
            document.get("name") or "سند مرجع"
        )[:100],
        "mime": str(
            document.get("mime") or "application/pdf"
        )[:100],
        "uploaded_at": (
            uploaded_at.isoformat()
            if uploaded_at
            else None
        ),
        "expires_at": (
            expires_at.isoformat()
            if expires_at
            else None
        ),
        "expired": expired,
    }


async def _active_reference(user_id: int) -> dict | None:
    document = await db.ai_get_doc(user_id)
    public = _public_reference(document)

    if public and public["expired"]:
        await db.ai_clear_doc(user_id)
        return None

    return public


def _clean_filename(
    filename: str | None,
    fallback: str,
) -> str:
    raw = PurePath(
        str(filename or fallback).replace("\\", "/")
    ).name

    cleaned = re.sub(
        r"[\x00-\x1f\x7f]",
        "",
        raw,
    ).strip(" .")

    return (cleaned or fallback)[:100]


def _normalise_content_type(value: str | None) -> str:
    return (
        str(value or "")
        .split(";", 1)[0]
        .strip()
        .lower()
    )


def _detect_media(
    data: bytes,
    declared_type: str | None,
    filename: str | None,
) -> tuple[str, str]:
    """Detect supported media using magic bytes."""

    head = data[:64]
    declared = _normalise_content_type(declared_type)
    suffix = PurePath(filename or "").suffix.lower()

    if head.startswith(b"%PDF-"):
        return "pdf", "application/pdf"

    if head.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg"

    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "image/png"

    if (
        len(head) >= 12
        and head[:4] == b"RIFF"
        and head[8:12] == b"WEBP"
    ):
        return "image", "image/webp"

    if (
        len(head) >= 12
        and head[:4] == b"RIFF"
        and head[8:12] == b"WAVE"
    ):
        return "audio", "audio/wav"

    if head.startswith(b"OggS"):
        return "audio", "audio/ogg"

    if head.startswith(b"fLaC"):
        return "audio", "audio/flac"

    if head.startswith(b"\x1aE\xdf\xa3"):
        return "audio", "audio/webm"

    if head.startswith(b"ID3") or (
        len(head) >= 2
        and head[0] == 0xFF
        and (head[1] & 0xE0) == 0xE0
    ):
        if (
            declared in {"audio/aac", "audio/x-aac"}
            or suffix == ".aac"
        ):
            return "audio", "audio/aac"

        return "audio", "audio/mpeg"

    if len(head) >= 12 and head[4:8] == b"ftyp":
        if declared.startswith("video/"):
            raise HTTPException(
                status_code=415,
                detail=(
                    "فایل ویدیویی پشتیبانی نمی‌شود؛ "
                    "فقط فایل صوتی بفرستید"
                ),
            )

        return "audio", "audio/mp4"

    if head.startswith(b"ADIF"):
        return "audio", "audio/aac"

    audio_extensions = {
        ".aac",
        ".flac",
        ".m4a",
        ".mp3",
        ".mp4",
        ".oga",
        ".ogg",
        ".wav",
        ".webm",
    }

    if (
        declared in _SUPPORTED_AUDIO_MIMES
        and suffix in audio_extensions
    ):
        canonical = {
            "audio/mp3": "audio/mpeg",
            "audio/m4a": "audio/mp4",
            "audio/x-m4a": "audio/mp4",
            "audio/x-wav": "audio/wav",
            "audio/x-aac": "audio/aac",
        }.get(
            declared,
            declared,
        )

        return "audio", canonical

    raise HTTPException(
        status_code=415,
        detail=(
            "فرمت فایل پشتیبانی نمی‌شود؛ "
            "عکس JPG/PNG/WEBP، فایل PDF "
            "یا فایل صوتی بفرستید"
        ),
    )


async def _read_upload_limited(upload: UploadFile) -> bytes:
    declared_size = getattr(
        upload,
        "size",
        None,
    )

    if declared_size and declared_size > MAX_MEDIA_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "حجم فایل نباید بیشتر از "
                f"{MAX_MEDIA_BYTES // (1024 * 1024)} "
                "مگابایت باشد"
            ),
        )

    chunks: list[bytes] = []
    total = 0

    while True:
        chunk = await upload.read(_READ_CHUNK_BYTES)

        if not chunk:
            break

        total += len(chunk)

        if total > MAX_MEDIA_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    "حجم فایل نباید بیشتر از "
                    f"{MAX_MEDIA_BYTES // (1024 * 1024)} "
                    "مگابایت باشد"
                ),
            )

        chunks.append(chunk)

    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="فایل خالی است",
        )

    return b"".join(chunks)


def _validate_message(
    message: str | None,
    *,
    required: bool,
) -> str:
    text = str(message or "").strip()

    if required and not text:
        raise HTTPException(
            status_code=422,
            detail="متن سؤال را وارد کنید",
        )

    if len(text) > MAX_INPUT_CHARS:
        raise HTTPException(
            status_code=422,
            detail=(
                "متن سؤال نباید بیشتر از "
                f"{MAX_INPUT_CHARS} کاراکتر باشد"
            ),
        )

    return text


async def _acquire_user(user_id: int) -> None:
    """ادعای «یک پرسشِ در جریان» — مشترک با پراسسِ ربات.

    🔧 FIX: قبلاً فقط `_busy_users` (setِ همین پراسس) چک می‌شد، پس یک
    کاربر می‌توانست هم‌زمان از ربات و از مینی‌اپ بپرسد و هر دو رد شوند.
    حالا همان قفلِ دیتابیسیِ `ai_inflight` گرفته می‌شود که ربات هم
    می‌گیرد ⇒ «یکی در لحظه» واقعاً سراسری است. رفتار روی خطا (۴۰۹ با
    همان متن) دست‌نخورده مانده تا فرانت‌اند تغییری لازم نداشته باشد.
    """
    if not await ai_claim_inflight(user_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "پاسخ قبلی هنوز "
                "در حال آماده‌شدن است"
            ),
        )


async def _ensure_available(user_id: int) -> dict:
    if await db.ai_is_banned(user_id):
        raise HTTPException(
            status_code=403,
            detail=(
                "دسترسی شما به هوشیار "
                "مسدود شده است"
            ),
        )

    config = await get_ai_config()

    if not config.get("enabled"):
        raise HTTPException(
            status_code=503,
            detail=(
                config.get("disabled_message")
                or (
                    "هوشیار فعلاً توسط "
                    "مدیریت غیرفعال است"
                )
            ),
        )

    if not config.get("api_key"):
        raise HTTPException(
            status_code=503,
            detail=(
                "هوشیار هنوز توسط "
                "مدیریت آماده نشده است"
            ),
        )

    return config


async def _consume_quota(user_id: int) -> tuple[int, int]:
    allowed, used, limit = await check_and_consume_quota(
        user_id
    )

    used = max(
        0,
        _safe_int(used),
    )
    limit = max(
        0,
        _safe_int(limit),
    )

    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=(
                "سهمیه روزانه هوشیار "
                f"تمام شده است ({used}/{limit})"
            ),
        )

    return used, limit


def _usage_payload(
    used: int,
    limit: int,
) -> dict:
    return {
        "used_today": used,
        "daily_limit": limit,
        "remaining": (
            max(0, limit - used)
            if limit
            else None
        ),
        "unlimited": limit == 0,
    }


async def _ask_provider(
    *,
    user_id: int,
    prompt: str,
    history_items: list,
    memory_label: str,
    used: int,
    limit: int,
    media_bytes: bytes | None = None,
    media_mime: str = "image/jpeg",
    conv: tuple | None = None,
) -> dict:
    answer, tokens = await ask_ai(
        text=prompt or None,
        image_bytes=media_bytes,
        image_mime=media_mime,
        history=history_items,
        uid=user_id,
    )

    answer = str(answer or "").strip()

    if not answer:
        raise HTTPException(
            status_code=502,
            detail="هوشیار پاسخی برنگرداند",
        )

    token_count = max(
        0,
        _safe_int(tokens),
    )

    if conv is not None:
        # مسیر گفت‌وگوی مستقل مینی‌اپ — به‌جای حافظه‌ی مشترک ai_mem،
        # دورِ پرسش/پاسخ در سندِ خودِ گفت‌وگو ذخیره می‌شود (اتمیک).
        conv_id, conv_doc = conv
        now_iso = utc_now_iso()

        title = None
        if not _safe_int(conv_doc.get("msg_count")):
            # اولین دور — عنوان خودکار از خودِ پیام کاربر
            raw_title = re.sub(
                r"^\[[^\]]*\]\s*", "", memory_label or ""
            ).strip().split("\n")[0][:38]
            title = raw_title or "گفت‌وگوی رسانه‌ای"

        ok = await db.ai_conv_append(
            conv_id,
            user_id,
            {
                "r": "user",
                "t": (memory_label or "")[:12000],
                "at": now_iso,
            },
            {
                "r": "assistant",
                "t": answer[:12000],
                "at": now_iso,
            },
            title,
            preview=answer,
            max_items=CONV_MAX_ITEMS,
        )

        if not ok:
            logger.warning(
                "append به گفت‌وگوی %s ناموفق بود", conv_id
            )
    else:
        # مسیر legacy — دقیقاً همان رفتار قبلی: حافظه‌ی مشترک با ربات
        await _remember(
            user_id,
            "user",
            memory_label,
        )

        await _remember(
            user_id,
            "assistant",
            answer,
        )

    await record_token_usage(
        user_id,
        token_count,
    )

    result = {
        "answer": answer,
        "tokens": token_count,
        **_usage_payload(
            used,
            limit,
        ),
    }

    if conv is not None:
        result["conversation_id"] = conv_id

    return result


def _gemini_file_name(
    file_info: dict | None,
) -> str | None:
    if (
        isinstance(file_info, dict)
        and file_info.get("name")
    ):
        name = str(
            file_info["name"]
        ).strip().lstrip("/")

        if name.startswith("files/"):
            return name

        return None

    uri = str(
        (file_info or {}).get("uri")
        or ""
    )

    match = re.search(
        r"/(files/[^/?#]+)",
        uri,
    )

    return (
        match.group(1)
        if match
        else None
    )


async def _wait_for_gemini_file(
    api_key: str,
    file_info: dict,
) -> dict:
    """Wait for Gemini PDF processing."""

    state = str(
        file_info.get("state") or ""
    ).upper()

    if state == "ACTIVE" or not state:
        return file_info

    if state == "FAILED":
        raise AIError(
            "پردازش PDF توسط سرویس "
            "هوش مصنوعی ناموفق بود"
        )

    remote_name = _gemini_file_name(
        file_info
    )

    if not remote_name:
        return file_info

    url = (
        "https://generativelanguage."
        "googleapis.com/v1beta/"
        f"{remote_name}"
    )

    headers = {
        "x-goog-api-key": api_key,
    }

    try:
        async with httpx.AsyncClient(
            timeout=20
        ) as client:
            for _ in range(15):
                await asyncio.sleep(1.5)

                response = await client.get(
                    url,
                    headers=headers,
                )

                if response.status_code != 200:
                    continue

                current = response.json() or {}

                current_state = str(
                    current.get("state")
                    or ""
                ).upper()

                if current_state == "ACTIVE":
                    return current

                if current_state == "FAILED":
                    raise AIError(
                        "پردازش PDF توسط سرویس "
                        "هوش مصنوعی ناموفق بود"
                    )

    except AIError:
        raise

    except (
        httpx.HTTPError,
        ValueError,
    ):
        logger.warning(
            "Checking Gemini reference "
            "state failed",
            exc_info=True,
        )

    raise AIError(
        "آماده‌سازی PDF بیش از حد "
        "طول کشید؛ کمی بعد دوباره "
        "امتحان کنید"
    )


async def _delete_remote_reference(
    config: dict,
    document: dict | None,
) -> None:
    """Best-effort privacy cleanup."""

    if (
        config.get("provider") != "gemini"
        or not config.get("api_key")
    ):
        return

    remote_name = _gemini_file_name(
        document
    )

    if not remote_name:
        return

    try:
        async with httpx.AsyncClient(
            timeout=15
        ) as client:
            await client.delete(
                (
                    "https://generativelanguage."
                    "googleapis.com/v1beta/"
                    f"{remote_name}"
                ),
                headers={
                    "x-goog-api-key": (
                        config["api_key"]
                    )
                },
            )

    except httpx.HTTPError:
        logger.info(
            "Remote Gemini reference "
            "cleanup failed",
            exc_info=True,
        )


async def _store_pdf_reference(
    *,
    user_id: int,
    config: dict,
    data: bytes,
    filename: str,
) -> dict:
    previous = await db.ai_get_doc(
        user_id
    )

    uploaded = await _gemini_upload_file(
        config["api_key"],
        data,
        "application/pdf",
        filename,
    )

    uploaded = await _wait_for_gemini_file(
        config["api_key"],
        uploaded,
    )

    uri = uploaded.get("uri")

    if not uri:
        raise AIError(
            "سرویس هوش مصنوعی "
            "شناسه فایل را برنگرداند"
        )

    mime = (
        uploaded.get("mimeType")
        or "application/pdf"
    )

    await db.ai_set_doc(
        user_id,
        uri,
        mime,
        filename,
    )

    if (
        previous
        and previous.get("uri") != uri
    ):
        await _delete_remote_reference(
            config,
            previous,
        )

    return await _active_reference(
        user_id
    )


@router.get("/status")
async def status(
    user=Depends(get_current_user),
):
    config = await get_ai_config()
    database_user = user.get("_db") or {}

    banned = await db.ai_is_banned(
        user["id"]
    )

    # 🌊 W6/MISS-04 — نمایش سقف پلنی (نه سراسری)
    limit = max(
        0,
        _safe_int(
            await db.ai_limit_for_user(
                user["id"], config.get("daily_limit")
            )
        ),
    )

    today = today_tehran().isoformat()

    used = (
        max(
            0,
            _safe_int(
                database_user.get(
                    "ai_usage_count"
                )
            ),
        )
        if database_user.get("ai_usage_date") == today
        else 0
    )

    provider = str(
        config.get("provider") or ""
    )

    return {
        "enabled": bool(
            config.get("enabled")
        ),
        "banned": bool(banned),
        "provider": provider,
        "model": str(
            config.get("model") or ""
        ),
        "daily_limit": limit,
        "used_today": used,
        "remaining": (
            max(0, limit - used)
            if limit
            else None
        ),
        "unlimited": limit == 0,
        "disabled_message": str(
            config.get(
                "disabled_message"
            )
            or ""
        ),
        "max_input_chars": MAX_INPUT_CHARS,
        "max_media_bytes": MAX_MEDIA_BYTES,
        "capabilities": {
            "text": True,
            "image": provider in {
                "gemini",
                "openrouter",
            },
            "pdf": provider == "gemini",
            "audio": provider == "gemini",
            "reference_document": (
                provider == "gemini"
            ),
        },
        "active_reference": (
            await _active_reference(
                user["id"]
            )
        ),
    }


@router.get("/history")
async def history(
    user=Depends(require_feature("ai_chat")),
):
    items = await _get_history(
        user["id"]
    )

    return {
        "messages": _public_history(
            items
        )
    }


# ══════════════════════════════════════════════════
#  گفت‌وگوهای چندگانه‌ی مینی‌اپ — افزایشی:
#  مسیر legacy (حافظه‌ی مشترک ai_mem با ربات) بالا
#  عیناً حفظ است؛ این بخش فقط رشته‌های مستقلِ
#  مدیریت‌شده (پین/آرشیو/حذف/تغییر نام) را اضافه
#  می‌کند. رشته‌ی legacy در لیست با id ثابت 'legacy'
#  دیده می‌شود تا هیچ چیزی پنهان نشود.
# ══════════════════════════════════════════════════

CONV_MAX_ITEMS = 120       # سقف پیام‌های ذخیره‌شده در هر گفت‌وگو
CONV_CONTEXT_ITEMS = 10    # ۵ دورِ آخر → کانتکست مدل


def _conv_public(doc: dict) -> dict:
    return {
        "id": str(doc.get("_id")),
        "title": str(doc.get("title") or "گفت‌وگوی جدید"),
        "pinned": bool(doc.get("pinned")),
        "archived": bool(doc.get("archived")),
        "preview": str(doc.get("preview") or "")[:90],
        "count": _safe_int(doc.get("msg_count")),
        "legacy": False,
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def _conv_context_items(doc: dict) -> list:
    """۵ دورِ آخر گفت‌وگو به شکل مورد انتظار ask_ai —
    متن هر آیتم برای کنترل توکن مثل حافظه‌ی مشترک پیرایش می‌شود."""
    items = doc.get("items") or []
    return [
        {
            "role": it.get("r"),
            "text": str(it.get("t") or "")[:1200],
        }
        for it in items[-CONV_CONTEXT_ITEMS:]
        if it.get("r") in ("user", "assistant", "model")
    ]


def _conv_messages_public(doc: dict) -> list:
    messages = []
    for it in doc.get("items") or []:
        if it.get("r") not in ("user", "assistant", "model"):
            continue
        messages.append({
            "role": "assistant" if it.get("r") == "model" else it.get("r"),
            "text": str(it.get("t") or "")[:12000],
            "at": it.get("at"),
        })
    return messages


async def _load_conv(cid: str, user_id: int) -> dict:
    doc = await db.ai_conv_get(cid, user_id)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail="گفت‌وگو پیدا نشد",
        )
    return doc


@router.get("/conversations")
async def list_conversations(
    user=Depends(require_feature("ai_chat")),
    include_archived: bool = False,
):
    user_id = user["id"]
    docs = await db.ai_conv_list(
        user_id,
        include_archived=include_archived,
    )
    items = [_conv_public(d) for d in docs]

    # رشته‌ی مشترک با ربات تلگرام — همان حافظه‌ی ai_mem که امروز هم
    # بین دو کانال مشترک است؛ بعد از گفت‌وگوهای پین‌شده می‌نشیند.
    mem, mem_at = await db.ai_get_memory(user_id)
    if mem:
        last = mem[-1]
        legacy = {
            "id": "legacy",
            "title": "گفت‌وگوی مشترک با ربات",
            "pinned": False,
            "archived": False,
            "preview": str(last.get("t") or "")[:90],
            "count": len(mem),
            "legacy": True,
            "created_at": None,
            "updated_at": (
                mem_at.isoformat()
                if isinstance(mem_at, datetime)
                else None
            ),
        }
        pinned_count = sum(
            1 for i in items if i["pinned"]
        )
        items.insert(pinned_count, legacy)

    return {"conversations": items}


@router.post("/conversations")
async def create_conversation(
    body: ConversationCreate,
    user=Depends(require_feature("ai_chat")),
):
    user_id = user["id"]
    # تمیزکاری: گفت‌وگوهای خالیِ رهاشده‌ی قبلی نمانند
    await db.ai_conv_delete_empty(user_id)
    cid = await db.ai_conv_create(
        user_id,
        title=(body.title or "گفت‌وگوی جدید"),
    )
    return {"id": cid}


@router.get("/conversations/{cid}/messages")
async def conversation_messages(
    cid: str,
    user=Depends(require_feature("ai_chat")),
):
    if cid == "legacy":
        # رشته‌ی مشترک — نسخه‌ی خام ai_mem بدون محدودیت TTL
        raw, _ = await db.ai_get_memory(user["id"])
        return {
            "messages": [
                {
                    "role": (
                        "assistant"
                        if it.get("r") == "model"
                        else it.get("r")
                    ),
                    "text": str(it.get("t") or "")[:12000],
                    "at": None,
                }
                for it in raw
                if it.get("r") in ("user", "assistant", "model")
            ]
        }

    doc = await _load_conv(cid, user["id"])
    return {"messages": _conv_messages_public(doc)}


@router.patch("/conversations/{cid}")
async def update_conversation(
    cid: str,
    body: ConversationPatch,
    user=Depends(require_feature("ai_chat")),
):
    if cid == "legacy":
        raise HTTPException(
            status_code=400,
            detail="رشته‌ی مشترک با ربات قابل ویرایش نیست",
        )

    patch = body.model_dump(exclude_unset=True)
    ok = await db.ai_conv_update(
        cid, user["id"], patch
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="گفت‌وگو پیدا نشد یا تغییری نکرد",
        )
    return {"ok": True}


@router.delete("/conversations/{cid}")
async def delete_conversation(
    cid: str,
    user=Depends(require_feature("ai_chat")),
):
    user_id = user["id"]

    if cid == "legacy":
        # پاک‌کردن رشته‌ی مشترک = همان DELETE /history + سند مرجع
        await _clear_memory(user_id)
        document = await db.ai_get_doc(user_id)
        if document:
            await _delete_remote_reference(
                document.get("references") or []
            )
            await db.ai_clear_doc(user_id)
        return {"ok": True, "legacy": True}

    ok = await db.ai_conv_delete(cid, user_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="گفت‌وگو پیدا نشد",
        )
    return {"ok": True}


@router.post("/conversations/{cid}/duplicate")
async def duplicate_conversation(
    cid: str,
    user=Depends(require_feature("ai_chat")),
):
    """رونوشت کامل گفت‌وگو در یک رشته‌ی جدید.
    legacy هم پشتیبانی می‌شود: حافظه‌ی مشترک با ربات به یک رشته‌ی
    مستقل تبدیل می‌شود (بدون دست‌خوردن به خودِ حافظه‌ی مشترک)."""
    user_id = user["id"]
    now_iso = utc_now_iso()

    if cid == "legacy":
        raw, _ = await db.ai_get_memory(user_id)
        items = [
            {
                "r": (
                    "assistant"
                    if it.get("r") == "model"
                    else it.get("r")
                ),
                "t": str(it.get("t") or "")[:12000],
                "at": now_iso,
            }
            for it in raw
            if it.get("r") in ("user", "assistant", "model")
        ]
        title = "رونوشت گفت‌وگوی مشترک"

    else:
        doc = await _load_conv(cid, user_id)
        items = [
            {
                "r": it.get("r"),
                "t": str(it.get("t") or "")[:12000],
                "at": now_iso,
            }
            for it in doc.get("items") or []
            if it.get("r") in ("user", "assistant", "model")
        ]
        title = (
            "رونوشت: "
            + str(doc.get("title") or "گفت‌وگو")
        )[:80]

    new_id = await db.ai_conv_insert_copy(
        user_id,
        title,
        items,
        max_items=CONV_MAX_ITEMS,
    )

    try:
        _u = await db.get_user(user_id) or {}
        _name = _u.get("name", str(user_id))
        try:
            _role = await db.get_actor_role_label(user_id)
        except Exception:
            _role = "student"
        await db.log_action(
            user_id, _name, _role,
            "ai_duplicate_conversation", "AI", "ai", "LOW",
            target_id=str(user_id), target_type="ai_conversation", target_label=f"conv:{cid}"[:80],
            metadata={"source": str(cid)},
            tags=["هوشیار", "رونوشت"],
        )
    except Exception:
        pass

    return {"id": new_id}


@router.post("/ask", dependencies=[Depends(rate_limit_dependency("ai_ask", 30, 60, by_user=True))])
async def ask(
    body: AskRequest,
    user=Depends(require_feature("ai_chat")),
):
    user_id = user["id"]
    await rate_limit_user(user_id, "ai_ask", 30, 60)

    message = _validate_message(
        body.message,
        required=True,
    )

    await _ensure_available(user_id)
    await _acquire_user(user_id)

    try:
        used, limit = await _consume_quota(
            user_id
        )

        # انشعاب چندگفت‌وگو: با conversation_id معتبر (غیر legacy)
        # کانتکست و ذخیره از سند خودِ گفت‌وگو می‌آید، نه حافظه‌ی مشترک
        conv_id = (body.conversation_id or "").strip()
        if conv_id and conv_id != "legacy":
            conv_doc = await _load_conv(conv_id, user_id)
            result = await _ask_provider(
                user_id=user_id,
                prompt=message,
                history_items=_conv_context_items(
                    conv_doc
                ),
                memory_label=message,
                used=used,
                limit=limit,
                conv=(conv_id, conv_doc),
            )
        else:
            result = await _ask_provider(
                user_id=user_id,
                prompt=message,
                history_items=(
                    await _get_history(
                        user_id
                    )
                ),
                memory_label=message,
                used=used,
                limit=limit,
            )

        # 👑 P1 — گفت‌وگوی روزانه‌ی هوشیار (idempotent per روز در DB)
        try:
            await db.prestige_event(user_id, "ai_daily")
        except Exception:
            pass

        return result

    except HTTPException:
        raise

    except AIError as error:
        raise HTTPException(
            status_code=503,
            detail=str(error),
        ) from error

    except Exception as error:
        logger.exception(
            "Hoshyar text request failed "
            "for user %s",
            user_id,
        )

        raise HTTPException(
            status_code=502,
            detail=(
                "ارتباط با سرویس "
                "هوش مصنوعی ناموفق بود"
            ),
        ) from error

    finally:
        await ai_release_inflight(
            user_id
        )


@router.post("/ask-media", dependencies=[Depends(rate_limit_dependency("ai_ask_media", 30, 60, by_user=True))])
async def ask_media(
    message: str = Form(default=""),
    file: UploadFile = File(...),
    conversation_id: str | None = Form(default=None),
    user=Depends(require_feature("ai_chat")),
):
    """Ask with image, PDF or audio."""

    user_id = user["id"]
    await rate_limit_user(user_id, "ai_ask_media", 30, 60)

    prompt = _validate_message(
        message,
        required=False,
    )

    config = await _ensure_available(
        user_id
    )

    await _acquire_user(user_id)

    try:
        try:
            data = await _read_upload_limited(
                file
            )
        finally:
            await file.close()

        kind, mime = _detect_media(
            data,
            file.content_type,
            file.filename,
        )

        fallback_names = {
            "image": "تصویر.jpg",
            "pdf": "سند.pdf",
            "audio": "صدای ضبط‌شده.webm",
        }

        filename = _clean_filename(
            file.filename,
            fallback_names[kind],
        )

        if (
            kind in {"pdf", "audio"}
            and config.get("provider") != "gemini"
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "پردازش PDF و صدا فقط "
                    "وقتی ارائه‌دهنده هوشیار "
                    "Gemini باشد در دسترس است"
                ),
            )

        active_reference = await _active_reference(
            user_id
        )

        media_bytes: bytes | None = data

        if kind == "pdf":
            active_reference = await _store_pdf_reference(
                user_id=user_id,
                config=config,
                data=data,
                filename=filename,
            )

            media_bytes = None

        elif (
            kind == "audio"
            and mime == "audio/ogg"
        ):
            converted = await _transcode_ogg_opus_to_wav(
                data
            )

            if not converted:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "این فرمت پیام صوتی "
                        "قابل پردازش نیست؛ "
                        "فایل MP3/WAV بفرستید "
                        "یا سؤال را تایپ کنید"
                    ),
                )

            media_bytes = converted
            mime = "audio/wav"

        default_prompts = {
            "image": (
                "این تصویر را دقیق بررسی کن؛ "
                "اگر سؤال درسی است آن را حل "
                "و پاسخ را توضیح بده."
            ),
            "pdf": (
                "این PDF را به‌عنوان سند "
                "مرجع فعال بررسی کن، موضوع "
                "و نکات اصلی آن را کوتاه "
                "معرفی کن."
            ),
            "audio": (
                "محتوای این فایل صوتی را "
                "درک کن و به سؤال یا درخواست "
                "مطرح‌شده در آن پاسخ بده."
            ),
        }

        provider_prompt = (
            prompt
            or default_prompts[kind]
        )

        labels = {
            "image": "تصویر",
            "pdf": "سند مرجع PDF",
            "audio": "فایل صوتی",
        }

        memory_label = (
            f"[{labels[kind]}: {filename}]"
        )

        if prompt:
            memory_label += f"\n{prompt}"

        used, limit = await _consume_quota(
            user_id
        )

        # انشعاب چندگفت‌وگو برای رسانه هم — همان قرارداد متن
        conv_id = (conversation_id or "").strip()
        if conv_id and conv_id != "legacy":
            conv_doc = await _load_conv(conv_id, user_id)
            result = await _ask_provider(
                user_id=user_id,
                prompt=provider_prompt,
                history_items=_conv_context_items(
                    conv_doc
                ),
                memory_label=memory_label,
                used=used,
                limit=limit,
                media_bytes=media_bytes,
                media_mime=mime,
                conv=(conv_id, conv_doc),
            )
        else:
            result = await _ask_provider(
                user_id=user_id,
                prompt=provider_prompt,
                history_items=(
                    await _get_history(
                        user_id
                    )
                ),
                memory_label=memory_label,
                used=used,
                limit=limit,
                media_bytes=media_bytes,
                media_mime=mime,
            )

        result["attachment"] = {
            "kind": kind,
            "name": filename,
            "mime": mime,
            "size_bytes": len(data),
            "reference_active": (
                kind == "pdf"
            ),
        }

        result["active_reference"] = (
            active_reference
        )

        # 👑 P1 — گفت‌وگوی رسانه‌ای هم رویداد روزانه دارد
        try:
            await db.prestige_event(user_id, "ai_daily")
        except Exception:
            pass

        return result

    except HTTPException:
        raise

    except AIError as error:
        raise HTTPException(
            status_code=503,
            detail=str(error),
        ) from error

    except Exception as error:
        logger.exception(
            "Hoshyar media request failed "
            "for user %s",
            user_id,
        )

        raise HTTPException(
            status_code=502,
            detail=(
                "پردازش فایل یا ارتباط "
                "با سرویس هوش مصنوعی "
                "ناموفق بود"
            ),
        ) from error

    finally:
        await ai_release_inflight(
            user_id
        )


@router.post("/reference", dependencies=[Depends(rate_limit_dependency("ai_ref", 15, 60, by_user=True))])
async def upload_reference(
    file: UploadFile = File(...),
    user=Depends(require_feature("ai_chat")),
):
    """Attach PDF without quota use."""

    user_id = user["id"]

    config = await _ensure_available(
        user_id
    )

    if config.get("provider") != "gemini":
        raise HTTPException(
            status_code=422,
            detail=(
                "سند مرجع فقط وقتی "
                "ارائه‌دهنده هوشیار Gemini "
                "باشد در دسترس است"
            ),
        )

    await _acquire_user(user_id)

    try:
        try:
            data = await _read_upload_limited(
                file
            )
        finally:
            await file.close()

        kind, _ = _detect_media(
            data,
            file.content_type,
            file.filename,
        )

        if kind != "pdf":
            raise HTTPException(
                status_code=415,
                detail=(
                    "برای سند مرجع فقط "
                    "فایل PDF مجاز است"
                ),
            )

        filename = _clean_filename(
            file.filename,
            "سند.pdf",
        )

        reference = await _store_pdf_reference(
            user_id=user_id,
            config=config,
            data=data,
            filename=filename,
        )

        return {
            "ok": True,
            "active_reference": reference,
        }

    except HTTPException:
        raise

    except AIError as error:
        raise HTTPException(
            status_code=503,
            detail=str(error),
        ) from error

    except Exception as error:
        logger.exception(
            "Reference upload failed "
            "for user %s",
            user_id,
        )

        raise HTTPException(
            status_code=502,
            detail="آپلود سند مرجع ناموفق بود",
        ) from error

    finally:
        await ai_release_inflight(
            user_id
        )


@router.delete("/reference")
async def clear_reference(
    user=Depends(get_current_user),
):
    user_id = user["id"]

    # گاردِ مخرب: پاک‌کردن حافظه/سندِ مرجع وسطِ یک پاسخِ در جریان (که
    # ممکن است در پراسسِ ربات باشد) باعث پاسخِ ناقص می‌شود ⇒ همان قفلِ
    # مشترک خوانده می‌شود، نه فقط setِ همین پراسس.
    if await ai_is_inflight(user_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "پاسخ قبلی هنوز "
                "در حال آماده‌شدن است"
            ),
        )

    document = await db.ai_get_doc(
        user_id
    )

    config = await get_ai_config()

    await db.ai_clear_doc(
        user_id
    )

    await _delete_remote_reference(
        config,
        document,
    )

    return {
        "ok": True,
    }


@router.delete("/history")
async def clear_history(
    clear_reference: bool = False,
    user=Depends(get_current_user),
):
    user_id = user["id"]

    # گاردِ مخرب: پاک‌کردن حافظه/سندِ مرجع وسطِ یک پاسخِ در جریان (که
    # ممکن است در پراسسِ ربات باشد) باعث پاسخِ ناقص می‌شود ⇒ همان قفلِ
    # مشترک خوانده می‌شود، نه فقط setِ همین پراسس.
    if await ai_is_inflight(user_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "پاسخ قبلی هنوز "
                "در حال آماده‌شدن است"
            ),
        )

    await _clear_memory(
        user_id
    )

    reference_cleared = False

    if clear_reference:
        document = await db.ai_get_doc(
            user_id
        )

        config = await get_ai_config()

        await db.ai_clear_doc(
            user_id
        )

        await _delete_remote_reference(
            config,
            document,
        )

        reference_cleared = True

    return {
        "ok": True,
        "reference_cleared": (
            reference_cleared
        ),
    }


@router.post("/report")
async def report(
    body: ReportRequest,
    user=Depends(get_current_user),
):
    database_user = (
        user.get("_db") or {}
    )

    await db.ai_log_report(
        user["id"],
        str(
            database_user.get("name")
            or ""
        ),
        body.question.strip(),
        body.answer.strip(),
    )

    return {
        "ok": True,
    }


# ══════════════════════════════════════════════════════════════
#  🎨 تولید تصویر با Gemini — همان زیرساخت هوشیار:
#  ban/enabled/api_key (get_ai_config) + قفل سراسری ai_inflight +
#  سهمیه‌ی روزانه‌ی مستقل تصویر. کلید API هرگز از این لایه بیرون
#  نمی‌رود؛ تصویر به‌صورت base64 یک‌بارمصرف برمی‌گردد (بدون فایلِ
#  ماندگار روی سرور ⇒ بدون نیاز به cleanup).
# ══════════════════════════════════════════════════════════════

_IMAGE_ERR_STATUS = {
    'GEMINI_SAFETY_BLOCK': 422,
    'GEMINI_INVALID_REQUEST': 422,
    'GEMINI_RATE_LIMIT': 429,
    'GEMINI_TIMEOUT': 504,
    'GEMINI_UNAVAILABLE': 502,
    'GEMINI_AUTH_ERROR': 503,
    'IMAGE_PARSE_FAILED': 502,
    'IMAGE_STORAGE_FAILED': 500,
}


class ImageGenBody(BaseModel):
    prompt: str = Field(..., description="توضیح تصویر")
    aspect_ratio: str = Field('1:1', description='مثلاً 1:1 یا 16:9')


@router.post("/generate-image", dependencies=[Depends(rate_limit_dependency("ai_image", 20, 3600, by_user=True))])
async def generate_image_ep(body: ImageGenBody,
                            user=Depends(require_feature("ai_image"))):
    import time as _time
    import uuid as _uuid
    uid = user["id"]
    request_id = f"imggen_{_uuid.uuid4().hex[:12]}"

    prompt = (body.prompt or "").strip()
    if not (IMAGE_PROMPT_MIN <= len(prompt) <= IMAGE_PROMPT_MAX):
        raise HTTPException(
            status_code=422,
            detail=(f"توضیح تصویر باید بین {IMAGE_PROMPT_MIN} و "
                    f"{IMAGE_PROMPT_MAX} نویسه باشد"))
    aspect_ratio = (body.aspect_ratio or "1:1").strip()
    if aspect_ratio not in IMAGE_ASPECT_RATIOS:
        raise HTTPException(
            status_code=422,
            detail="نسبت تصویر معتبر نیست — یکی از: "
                   + "، ".join(IMAGE_ASPECT_RATIOS))

    config = await _ensure_available(uid)
    if not config.get("image_enabled"):
        raise HTTPException(
            status_code=503, detail="تولید تصویر فعلاً غیرفعال است")
    effective_key = config.get("image_api_key") or config.get("api_key") or ""
    effective_model = config.get("image_model") or config.get("model") or "gemini-2.5-flash-image"
    effective_provider = config.get("image_provider") or config.get("provider") or "gemini"
    if not effective_key:
        raise HTTPException(status_code=503, detail="کلید API برای ساخت تصویر تنظیم نشده — از پنل مدیریت کلید مربوطه را وارد کن")

    limit = max(0, int(config.get("image_daily_limit") or 0))
    today = today_tehran().isoformat()
    used = await db.ai_image_used_today(uid, today)
    is_vip = uid == int(os.getenv("ADMIN_ID", "0"))
    if limit and not is_vip and used >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"سهمیه روزانه ساخت تصویر تمام شده است ({used}/{limit})")

    # یک عملیات AI در لحظه — همان قفل مشترک ربات/مینی‌اپ
    await _acquire_user(uid)
    started = _time.monotonic()
    try:
        try:
            res = await generate_image(
                effective_key, effective_model, prompt,
                aspect_ratio, provider=effective_provider)
        except AiImageError as e:
            logger.warning(
                "IMAGE_GENERATION_FAILED rid=%s uid=%s model=%s code=%s "
                "latency_ms=%s", request_id, uid,
                config.get("image_model"), e.code,
                int((_time.monotonic() - started) * 1000))
            raise HTTPException(
                status_code=_IMAGE_ERR_STATUS.get(e.code, 502),
                detail=e.user_message)
        # سهمیه فقط پس از موفقیت مصرف می‌شود (شکست provider = سهمیه سالم)
        used_after = used + 1
        if limit or is_vip:
            try:
                used_after = await db.ai_image_inc(uid, today)
            except Exception:
                logger.exception("ثبت مصرف تصویر ناموفق بود rid=%s",
                                 request_id)
        latency_ms = int((_time.monotonic() - started) * 1000)
        # prompt کاربر لاگ نمی‌شود (حریم خصوصی) — فقط متادیتا
        logger.info(
            "IMAGE_GENERATION_OK rid=%s uid=%s model=%s latency_ms=%s "
            "bytes_b64=%s", request_id, uid, config.get("image_model"),
            latency_ms, len(res["data_b64"]))
        return {
            "ok": True,
            "image": res["data_b64"],
            "mime": res["mime"],
            "model": config.get("image_model"),
            "aspect_ratio": aspect_ratio,
            "usage": {
                "used_today": used_after,
                "daily_limit": limit,
                "remaining": (max(0, limit - used_after) if limit
                              else None),
                "unlimited": limit == 0 or is_vip,
            },
        }
    finally:
        await ai_release_inflight(uid)
