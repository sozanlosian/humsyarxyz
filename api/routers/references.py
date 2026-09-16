"""Educational-reference endpoints for the Telegram Mini App."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from api.auth import (
    get_current_user, get_references_access_user,
)
from api.telegram_send import (
    is_previewable, preview_token, proxy_telegram_preview,
    send_ref_file, verify_preview_token,
)
from database import db
from api.rate_limit import rate_limit_user  # 🛡 W3/SEC-03

logger = logging.getLogger(__name__)
router = APIRouter()

# جلوگیری از ارسال‌های تکراری ناشی از لمس سریع یا درخواست هم‌زمان.
_sending_users: set[int] = set()


def _text(
    value,
    default: str = "",
) -> str:
    return str(
        value
        if value is not None
        else default
    ).strip()


def _safe_int(
    value,
    default: int = 0,
) -> int:
    try:
        return int(value or 0)

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return default


def _public_reference_file(
    item: dict,
) -> dict:
    return {
        "id": str(
            item.get("_id") or ""
        ),
        "lang": (
            "en"
            if _text(
                item.get("lang")
            ).lower() == "en"
            else "fa"
        ),
        "volume": max(
            1,
            _safe_int(
                item.get("volume"),
                1,
            ),
        ),
        "description": _text(
            item.get("description")
        ),
        "downloads": max(
            0,
            _safe_int(
                item.get("downloads")
            ),
        ),
        # 🌊 W8/UX-03 — پیش‌نمایش داخل مینی‌اپ
        "mime": _text(item.get("mime_type")),
        "size": max(0, _safe_int(item.get("file_size"))),
        "preview": bool(is_previewable(
            _text(item.get("mime_type")),
            _text(item.get("file_extension")))),
    }


async def _viewer_intake(user: dict):
    """🌊 C1 — دانشجو: [ورودی خودش، سراسری]؛ مدیر محتوا/مالک: بدون فیلتر."""
    if await db.is_content_admin(user["id"]):
        return None
    return db.student_intake_filter(
        (user.get("_db") or {}).get("intake", ""))


def _intake_guard(item_intake: str, filt, what: str = "این بخش"):
    if filt is not None and (item_intake or "") not in filt:
        raise HTTPException(
            status_code=403,
            detail=f"{what} برای ورودی شما نیست",
        )


@router.get("/subjects")
async def subjects(
    user=Depends(get_references_access_user),
):
    items = await db.ref_get_subjects(
        intake=await _viewer_intake(user)
    )

    result = []

    for item in (
        items
        if isinstance(items, list)
        else []
    ):
        subject_id = str(
            item.get("_id") or ""
        )

        if not subject_id:
            continue

        books = await db.ref_get_books(
            subject_id
        )

        result.append(
            {
                "id": subject_id,
                "name": _text(
                    item.get("name"),
                    "موضوع بدون نام",
                ),
                "book_count": (
                    len(books)
                    if isinstance(
                        books,
                        list,
                    )
                    else 0
                ),
            }
        )

    return {
        "subjects": result,
    }


@router.get("/books/{subject_id}")
async def books(
    subject_id: str,
    user=Depends(get_references_access_user),
):
    subject = await db.ref_get_subject(
        subject_id
    )

    if not subject:
        raise HTTPException(
            status_code=404,
            detail="موضوع پیدا نشد",
        )

    # 🌊 C1 — ضد ID-manipulation: موضوع ورودی دیگر ⇒ ۴۰۳
    _intake_guard(
        await db.ref_subject_intake(subject_id),
        await _viewer_intake(user),
        "این موضوع",
    )

    # 🍴 C2 — نمای مؤثر: fork جایگزین base؛ مدیر محتوا = همه (پیش‌نمایش)
    book_items = await db.ref_get_books_effective(
        subject_id,
        intake=await _viewer_intake(user),
    )

    result = []

    for item in (
        book_items
        if isinstance(
            book_items,
            list,
        )
        else []
    ):
        book_id = str(
            item.get("_id") or ""
        )

        if not book_id:
            continue

        file_items = await db.ref_get_files(
            book_id
        )

        safe_files = (
            file_items
            if isinstance(
                file_items,
                list,
            )
            else []
        )

        result.append(
            {
                "id": book_id,
                "name": _text(
                    item.get("name"),
                    "کتاب بدون نام",
                ),
                "fa_count": sum(
                    1
                    for file in safe_files
                    if file.get("lang") == "fa"
                ),
                "en_count": sum(
                    1
                    for file in safe_files
                    if file.get("lang") == "en"
                ),
            }
        )

    return {
        "subject": {
            "id": subject_id,
            "name": _text(
                subject.get("name"),
                "موضوع بدون نام",
            ),
        },
        "books": result,
    }


@router.get("/files/{book_id}")
async def files(
    book_id: str,
    user=Depends(get_references_access_user),
):
    book = await db.ref_get_book(
        book_id
    )

    if not book:
        raise HTTPException(
            status_code=404,
            detail="کتاب پیدا نشد",
        )

    # 🌊 C1 — ضد ID-manipulation: کتاب ورودی دیگر ⇒ ۴۰۳
    _filt = await _viewer_intake(user)
    _intake_guard(
        await db.ref_book_intake(book_id),
        _filt,
        "این کتاب",
    )

    # 🍴 C2 — کتاب base جایگزین‌شده → فایل‌های همان fork ورودی دانشجو
    if _filt is not None:
        _fk = await db.book_superseded_by_fork(
            book_id,
            (user.get("_db") or {}).get("intake", ""),
        )
        if _fk:
            book_id = str(_fk["_id"])

    file_items = await db.ref_get_files(
        book_id
    )

    safe_files = (
        file_items
        if isinstance(
            file_items,
            list,
        )
        else []
    )

    fa_files = sorted(
        [
            item
            for item in safe_files
            if item.get("lang") == "fa"
        ],
        key=lambda item: max(
            1,
            _safe_int(
                item.get("volume"),
                1,
            ),
        ),
    )

    en_files = sorted(
        [
            item
            for item in safe_files
            if item.get("lang") == "en"
        ],
        key=lambda item: max(
            1,
            _safe_int(
                item.get("volume"),
                1,
            ),
        ),
    )

    return {
        "book": {
            "id": book_id,
            "name": _text(
                book.get("name"),
                "کتاب بدون نام",
            ),
        },
        "fa_files": [
            _public_reference_file(
                item
            )
            for item in fa_files
        ],
        "en_files": [
            _public_reference_file(
                item
            )
            for item in en_files
        ],
    }


@router.post("/download/{file_id}")
async def download(
    file_id: str,
    user=Depends(get_references_access_user),
):
    """فقط همان جلد انتخاب‌شده را ارسال می‌کند."""

    user_id = int(
        user["id"]
    )

    # 🛡 W3/SEC-03 — دانلود فایل = پهنای باند تلگرام؛ ضد اسکریپ
    await rate_limit_user(user_id, "ref_download", 60, 60)

    # فقط رکورد همان جلدی که کاربر روی آن کلیک کرده
    # از دیتابیس گرفته می‌شود.
    item = await db.ref_get_file(
        file_id
    )

    if not item:
        raise HTTPException(
            status_code=404,
            detail=(
                "فایل رفرنس پیدا نشد"
            ),
        )

    # 🌊 C1 — ضد دانلود متقاطع (Backend-enforced)
    _filt = await _viewer_intake(user)
    _intake_guard(
        await db.ref_file_intake(file_id),
        _filt,
        "این فایل",
    )
    # 🍴 C2 — دانلود معادلِ fork (اگر کتاب برای ورودی دانشجو fork دارد)
    if _filt is not None:
        _fork_b = await db.book_superseded_by_fork(
            item.get("book_id", ""),
            (user.get("_db") or {}).get("intake", ""),
        )
        if _fork_b:
            _fk_file = await db.ref_files.find_one({
                "book_id": str(_fork_b["_id"]),
                "fork_of": file_id,
            })
            if _fk_file:
                item = _fk_file

    if not _text(
        item.get("file_id")
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "شناسه تلگرام این فایل "
                "ثبت نشده است"
            ),
        )

    # تا پایان ارسال قبلی، درخواست ارسال جدید
    # برای همین کاربر قبول نمی‌شود.
    if user_id in _sending_users:
        raise HTTPException(
            status_code=409,
            detail=(
                "ارسال فایل قبلی هنوز تمام نشده است؛ "
                "چند لحظه صبر کنید"
            ),
        )

    _sending_users.add(
        user_id
    )

    try:
        next_downloads = (
            max(
                0,
                _safe_int(
                    item.get("downloads")
                ),
            )
            + 1
        )

        # فقط همین یک رکورد برای تابع ارسال تلگرام فرستاده می‌شود.
        # فایل‌های زبان دیگر یا جلدهای دیگر وارد این تابع نمی‌شوند.
        send_item = {
            **item,
            "downloads": next_downloads,
        }

        sent = await send_ref_file(
            user_id,
            send_item,
        )

        if not sent:
            raise HTTPException(
                status_code=502,
                detail=(
                    "ارسال فایل از طریق ربات ناموفق بود. "
                    "لطفاً ابتدا یک پیام به ربات بفرستید "
                    "یا دوباره تلاش کنید."
                ),
            )

        # شمارنده فقط پس از ارسال موفق افزایش پیدا می‌کند.
        try:
            await db.ref_inc_download(
                file_id,
                user_id,
            )

        except Exception:
            # فایل قبلاً برای کاربر ارسال شده است؛
            # خطای ثبت آمار نباید باعث ارسال مجدد شود.
            logger.exception(
                "Updating reference "
                "download count failed"
            )

        public = _public_reference_file(
            send_item
        )

        return {
            "sent": True,
            "file_id": public["id"],
            "lang": public["lang"],
            "volume": public["volume"],
            "downloads": next_downloads,
        }

    finally:
        # قفل در موفقیت و خطا حتماً آزاد می‌شود.
        _sending_users.discard(
            user_id
        )


async def _preview_user(request: Request) -> dict:
    """🌊 W8/UX-03 — احراز پیش‌نمایش رفرنس (هدر یا توکن تک‌فایل)."""
    from core.access import require_feature_access
    if request.headers.get("X-Init-Data"):
        user = await get_current_user(
            request, request.headers.get("X-Init-Data", ""))
        await require_feature_access(user["id"], "references")
        return user
    qp = request.query_params
    try:
        uid, exp = int(qp.get("uid") or 0), int(qp.get("exp") or 0)
    except (TypeError, ValueError):
        uid, exp = 0, 0
    fid = (request.path_params.get("file_id") or "")
    if uid and verify_preview_token(qp.get("token", ""), uid, "ref",
                                    fid, exp):
        db_user = await db.get_user(uid) or {}
        if db_user:
            await require_feature_access(uid, "references")
            return {"id": uid, "_db": db_user}
    raise HTTPException(status_code=401, detail="unauthorized")


@router.get("/preview-url/{file_id}")
async def preview_url(
    file_id: str,
    user=Depends(get_references_access_user),
):
    """🌊 W8/UX-03 — صدور آدرس امضاشده‌ی پیش‌نمایش رفرنس."""
    import time as _t
    item = await db.ref_get_file(file_id)
    if not item:
        raise HTTPException(status_code=404, detail="فایل رفرنس پیدا نشد")
    _filt = await _viewer_intake(user)
    _intake_guard(await db.ref_file_intake(file_id), _filt, "این فایل")
    mime = _text(item.get("mime_type")) or "application/octet-stream"
    if not is_previewable(mime, _text(item.get("file_extension"))):
        raise HTTPException(
            status_code=415,
            detail="این نوع فایل پیش‌نمایش ندارد؛ از دانلود استفاده کنید")
    exp = int(_t.time()) + 600
    tok = preview_token(int(user["id"]), "ref", file_id, exp)
    return {"url": (f"/api/references/preview/{file_id}"
                    f"?uid={int(user['id'])}&exp={exp}&token={tok}")}


@router.get("/preview/{file_id}")
async def preview(
    file_id: str,
    request: Request,
    user=Depends(_preview_user),
):
    """🌊 W8/UX-03 — استریم فایل رفرنس برای پیش‌نمایش داخل مینی‌اپ."""
    user_id = int(user["id"])
    await rate_limit_user(user_id, "ref_preview", 300, 3600)

    item = await db.ref_get_file(file_id)
    if not item:
        raise HTTPException(status_code=404, detail="فایل رفرنس پیدا نشد")
    _filt = await _viewer_intake(user)
    _intake_guard(await db.ref_file_intake(file_id), _filt, "این فایل")
    if _filt is not None:
        _fork_b = await db.book_superseded_by_fork(
            item.get("book_id", ""),
            (user.get("_db") or {}).get("intake", ""),
        )
        if _fork_b:
            _fk_file = await db.ref_files.find_one({
                "book_id": str(_fork_b["_id"]),
                "fork_of": file_id,
            })
            if _fk_file:
                item = _fk_file
    tg_id = _text(item.get("file_id"))
    if not tg_id:
        raise HTTPException(status_code=422,
                            detail="شناسه تلگرام این فایل ثبت نشده است")
    mime = _text(item.get("mime_type")) or "application/octet-stream"
    if not is_previewable(mime, _text(item.get("file_extension"))):
        raise HTTPException(
            status_code=415,
            detail="این نوع فایل پیش‌نمایش ندارد؛ از دانلود استفاده کنید")
    name = (_text(item.get("display_file_name"))
            or _text(item.get("description")) or "file")
    return await proxy_telegram_preview(
        tg_id, mime, name, request.headers.get("range"))
