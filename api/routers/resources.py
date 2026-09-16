"""Basic-science resource endpoints for the Telegram Mini App."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.auth import get_current_user, get_resource_access_user
from api.telegram_send import (
    is_previewable, preview_token, proxy_telegram_preview,
    send_bs_content, verify_preview_token,
)
from database import db

logger = logging.getLogger(__name__)
router = APIRouter()

# تا زمانی که ارسال قبلی یک کاربر تمام نشده،
# درخواست ارسال جدید برای همان کاربر قبول نمی‌شود.
# این Guard از چند بار لمس سریع دکمه و ارسال تکراری جلوگیری می‌کند.
_sending_users: set[int] = set()


async def _viewer_intake(user: dict):
    """🌊 C1 — scope دید محتوا: دانشجو → [ورودی خودش، سراسری]؛
    مدیر محتوا/مالک → None (بدون فیلتر، رفتار پیش‌نمایش قدیمی).
    enforce در همین لایه (Backend) انجام می‌شود، نه فرانت."""
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


def _public_file(
    item: dict,
) -> dict:
    file_type = _text(
        item.get("type"),
        "file",
    )

    description = _text(
        item.get("description")
    )

    return {
        "id": str(
            item.get("_id") or ""
        ),
        "type": file_type,
        "name": (
            _text(item.get("name"))
            or description
            or "فایل آموزشی"
        ),
        "description": description,
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


@router.get("/terms")
async def terms(
    user=Depends(get_resource_access_user),
):
    # 🌊 C1 — ترم‌ها/شمارش درس‌ها فقط در scope دید کاربر
    filt = await _viewer_intake(user)
    fq = (
        {"intake": {"$in": filt}}
        if filt is not None
        else {}
    )
    raw_terms = await db.bs_lessons.distinct(
        "term",
        fq,
    )

    term_names = sorted(
        {
            _text(value)
            for value in raw_terms
            if _text(value)
        }
    )

    # 🌊 Q2-W10 — شمارش گروهی با یک کوئری به‌جای N+1 count_documents
    _tcounts = {}
    async for _d in db.bs_lessons.find(fq):
        _t = _d.get('term')
        _tcounts[_t] = _tcounts.get(_t, 0) + 1

    result = []

    for term in term_names:
        count = _tcounts.get(term, 0)

        result.append(
            {
                "name": term,
                "lesson_count": max(
                    0,
                    _safe_int(count),
                ),
            }
        )

    return {
        "terms": result,
    }


@router.get("/lessons/{term}")
async def lessons(
    term: str,
    user=Depends(get_resource_access_user),
):
    items = await db.bs_get_lessons(
        term,
        intake=await _viewer_intake(user),
    )

    # 🌊 Q2-W10 — شمارش گروهی جلسات با یک کوئری به‌جای N+1 count_documents
    _scounts = {}
    async for _s in db.bs_sessions.find({}):
        _lid = _s.get('lesson_id')
        _scounts[_lid] = _scounts.get(_lid, 0) + 1

    result = []

    for item in (
        items
        if isinstance(items, list)
        else []
    ):
        lesson_id = str(
            item.get("_id") or ""
        )

        if not lesson_id:
            continue

        session_count = _scounts.get(lesson_id, 0)

        result.append(
            {
                "_id": lesson_id,
                "name": _text(
                    item.get("name"),
                    "درس بدون نام",
                ),
                "teacher": _text(
                    item.get("teacher")
                ),
                "term": _text(
                    item.get("term"),
                    term,
                ),
                "session_count": max(
                    0,
                    _safe_int(
                        session_count
                    ),
                ),
            }
        )

    return {
        "lessons": result,
    }


@router.get("/sessions/{lesson_id}")
async def sessions(
    lesson_id: str,
    user=Depends(get_resource_access_user),
):
    # 🌊 C1 — ضد ID-manipulation: درس ورودی دیگر ⇒ ۴۰۳
    _intake_guard(
        await db.lesson_intake(lesson_id),
        await _viewer_intake(user),
        "این درس",
    )
    # 🍴 C2 — نمای مؤثر: fork جایگزین base؛ مدیر محتوا = همه (پیش‌نمایش)
    items = await db.bs_get_sessions_effective(
        lesson_id,
        intake=await _viewer_intake(user),
    )

    # 🌊 Q2-W10 — شمارش گروهی فایل‌ها با یک کوئری به‌جای N+1 count_documents
    _fcounts = {}
    async for _f in db.bs_content.find({}):
        _sid = _f.get('session_id')
        _fcounts[_sid] = _fcounts.get(_sid, 0) + 1

    result = []

    for item in (
        items
        if isinstance(items, list)
        else []
    ):
        session_id = str(
            item.get("_id") or ""
        )

        if not session_id:
            continue

        file_count = _fcounts.get(session_id, 0)

        result.append(
            {
                "_id": session_id,
                "number": max(
                    0,
                    _safe_int(
                        item.get("number")
                    ),
                ),
                "topic": _text(
                    item.get("topic"),
                    "جلسه بدون عنوان",
                ),
                "teacher": _text(
                    item.get("teacher")
                ),
                "file_count": max(
                    0,
                    _safe_int(
                        file_count
                    ),
                ),
            }
        )

    return {
        "sessions": result,
    }


@router.get("/files/{session_id}")
async def files(
    session_id: str,
    user=Depends(get_resource_access_user),
):
    # 🌊 C1 — ضد ID-manipulation: جلسه ورودی دیگر ⇒ ۴۰۳
    _filt = await _viewer_intake(user)
    _intake_guard(
        await db.session_intake(session_id),
        _filt,
        "این جلسه",
    )
    # 🍴 C2 — جلسه‌ی base جایگزین‌شده → محتوای همان fork ورودی دانشجو
    if _filt is not None:
        _fk = await db.session_superseded_by_fork(
            session_id,
            (user.get("_db") or {}).get("intake", ""),
        )
        if _fk:
            session_id = str(_fk["_id"])
    items = await db.bs_get_content(
        session_id
    )

    return {
        "files": [
            _public_file(item)
            for item in (
                items
                if isinstance(
                    items,
                    list,
                )
                else []
            )
            if (
                isinstance(item, dict)
                and item.get("_id")
            )
        ]
    }


@router.post("/download/{content_id}")
async def download(
    content_id: str,
    user=Depends(get_resource_access_user),
):
    """فقط همان فایل انتخاب‌شده را در تلگرام ارسال می‌کند."""

    user_id = int(
        user["id"]
    )

    # فقط یک رکورد با شناسه‌ای که کاربر روی آن کلیک کرده
    # از دیتابیس خوانده می‌شود.
    item = await db.bs_get_content_item(
        content_id
    )

    if not item:
        raise HTTPException(
            status_code=404,
            detail="فایل پیدا نشد",
        )

    # 🌊 C1 — ضد دانلود متقاطع (Backend-enforced)
    _filt = await _viewer_intake(user)
    _intake_guard(
        await db.content_intake(content_id),
        _filt,
        "این فایل",
    )
    # 🍴 C2 — دانلود معادلِ fork (اگر جلسه برای ورودی دانشجو fork دارد)
    if _filt is not None:
        _sess_fk = await db.session_superseded_by_fork(
            item.get("session_id", ""),
            (user.get("_db") or {}).get("intake", ""),
        )
        if _sess_fk:
            _fk_content = await db.bs_content.find_one({
                "session_id": str(_sess_fk["_id"]),
                "fork_of": content_id,
            })
            if _fk_content:
                item = _fk_content
                content_id = str(_fk_content["_id"])

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

    # اگر ارسال دیگری برای همین کاربر در حال انجام است،
    # اجازه شروع درخواست دوم داده نمی‌شود.
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

        # فقط همین یک سند به تابع ارسال تلگرام داده می‌شود.
        # هیچ لیست جلسه یا فایل کناری وارد تابع ارسال نمی‌شود.
        send_item = {
            **item,
            "downloads": next_downloads,
        }

        sent = await send_bs_content(
            user_id,
            content_id,
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

        # شمارنده فقط بعد از ارسال موفق فایل افزایش پیدا می‌کند.
        try:
            await db.bs_inc_download(
                content_id,
                user_id,
            )
        except Exception:
            # فایل قبلاً به کاربر رسیده است.
            # خطای شمارنده نباید باعث شود کاربر دوباره فایل را
            # ارسال کند و دو نسخه دریافت کند.
            logger.exception(
                "Updating basic-science "
                "download count failed"
            )

        public = _public_file(
            send_item
        )

        return {
            "sent": True,
            "file_id": public["id"],
            "type": public["type"],
            "name": public["name"],
            "downloads": next_downloads,
        }

    finally:
        # حتی در صورت خطا، قفل کاربر حتماً آزاد می‌شود.
        _sending_users.discard(
            user_id
        )


async def _preview_user(request: Request) -> dict:
    """🌊 W8/UX-03 — احراز پیش‌نمایش: هدر initData یا توکن امضای تک‌فایل.

    تگ‌های <video>/<audio> هدر نمی‌فرستند؛ مینی‌اپ اول از preview-url
    توکن ۱۰دقیقه‌ای می‌گیرد. مسیر توکن هم گارد فیچر W7 را رد می‌کند و
    گارد ورودی پایین‌تر با کاربر تازه‌خوانده‌شده اعمال می‌شود.
    """
    from core.access import require_feature_access
    if request.headers.get("X-Init-Data"):
        user = await get_current_user(
            request, request.headers.get("X-Init-Data", ""))
        await require_feature_access(user["id"], "resources")
        return user
    qp = request.query_params
    try:
        uid, exp = int(qp.get("uid") or 0), int(qp.get("exp") or 0)
    except (TypeError, ValueError):
        uid, exp = 0, 0
    fid = (request.path_params.get("content_id") or "")
    if uid and verify_preview_token(qp.get("token", ""), uid, "res",
                                    fid, exp):
        db_user = await db.get_user(uid) or {}
        if db_user:
            await require_feature_access(uid, "resources")
            return {"id": uid, "_db": db_user}
    raise HTTPException(status_code=401, detail="unauthorized")


@router.get("/preview-url/{content_id}")
async def preview_url(
    content_id: str,
    user=Depends(get_resource_access_user),
):
    """🌊 W8/UX-03 — صدور آدرس امضاشده‌ی پیش‌نمایش (۱۰ دقیقه، تک‌فایل)."""
    import time as _t
    item = await db.bs_get_content_item(content_id)
    if not item:
        raise HTTPException(status_code=404, detail="فایل پیدا نشد")
    _filt = await _viewer_intake(user)
    _intake_guard(await db.content_intake(content_id), _filt, "این فایل")
    mime = _text(item.get("mime_type")) or "application/octet-stream"
    if not is_previewable(mime, _text(item.get("file_extension"))):
        raise HTTPException(
            status_code=415,
            detail="این نوع فایل پیش‌نمایش ندارد؛ از دانلود استفاده کنید")
    exp = int(_t.time()) + 600
    tok = preview_token(int(user["id"]), "res", content_id, exp)
    return {"url": (f"/api/resources/preview/{content_id}"
                    f"?uid={int(user['id'])}&exp={exp}&token={tok}")}


@router.get("/preview/{content_id}")
async def preview(
    content_id: str,
    request: Request,
    user=Depends(_preview_user),
):
    """🌊 W8/UX-03 — استریم فایل برای پخش داخل مینی‌اپ (Range پشتیبانی می‌شود).

    همان گاردهای download (دسترسی + ورودی + fork)؛ توکن تلگرام هرگز
    به کلاینت داده نمی‌شود — بایت‌ها از همین سرور پروکسی می‌شوند.
    """
    from api.rate_limit import rate_limit_user as _rl

    user_id = int(user["id"])
    await _rl(user_id, "preview", 300, 3600)

    item = await db.bs_get_content_item(content_id)
    if not item:
        raise HTTPException(status_code=404, detail="فایل پیدا نشد")
    _filt = await _viewer_intake(user)
    _intake_guard(await db.content_intake(content_id), _filt, "این فایل")
    if _filt is not None:
        _sess_fk = await db.session_superseded_by_fork(
            item.get("session_id", ""),
            (user.get("_db") or {}).get("intake", ""),
        )
        if _sess_fk:
            _fk_content = await db.bs_content.find_one({
                "session_id": str(_sess_fk["_id"]),
                "fork_of": content_id,
            })
            if _fk_content:
                item = _fk_content
    file_id = _text(item.get("file_id"))
    if not file_id:
        raise HTTPException(status_code=422,
                            detail="شناسه تلگرام این فایل ثبت نشده است")
    mime = _text(item.get("mime_type")) or "application/octet-stream"
    if not is_previewable(mime, _text(item.get("file_extension"))):
        raise HTTPException(
            status_code=415,
            detail="این نوع فایل پیش‌نمایش ندارد؛ از دانلود استفاده کنید")
    name = (_text(item.get("display_file_name"))
            or _text(item.get("name")) or "file")
    return await proxy_telegram_preview(
        file_id, mime, name, request.headers.get("range"))


@router.get("/search")
async def search(
    q: str = Query(
        ...,
        min_length=2,
        max_length=100,
    ),
    user=Depends(get_resource_access_user),
):
    # 🌊 C1.5 — جستجو هم scope-aware است: حتی عنوان محتوای ورودی
    # دیگر در نتایج دانشجو نمی‌آید (enforce در همین لایه)
    results = await db.search_resources(
        q.strip(),
        intake=await _viewer_intake(user),
    )

    public_results = []

    for item in (
        results
        if isinstance(results, list)
        else []
    ):
        if (
            not isinstance(item, dict)
            or not item.get("_id")
        ):
            continue

        session = (
            item.get("_session")
            if isinstance(
                item.get("_session"),
                dict,
            )
            else {}
        )

        lesson = (
            item.get("_lesson")
            if isinstance(
                item.get("_lesson"),
                dict,
            )
            else {}
        )

        public = _public_file(
            item
        )

        public.update(
            {
                "lesson": _text(
                    lesson.get("name")
                    or item.get(
                        "lesson_name"
                    )
                ),
                "session": _text(
                    session.get("topic")
                    or item.get(
                        "session_topic"
                    )
                ),
            }
        )

        public_results.append(
            public
        )

    return {
        "results": public_results,
    }
