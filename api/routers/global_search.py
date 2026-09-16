"""Unified Mini App search across educational content."""

import asyncio
import re

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)

from api.auth import (
    get_current_user,
)

from api.rate_limit import rate_limit_user  # 🛡 W10/RATE-01
from database import db
from question_bank.contracts import approved_query


router = APIRouter()

# 🌊 W6/PERF-02 — سقف‌های شفاف fan-out: هر کوئری maxTimeMS، کل گدر timeout.
_SEARCH_TIMEOUT_S = 8
_SEARCH_MAX_TIME_MS = 5000


def text(
    value,
) -> str:
    return str(
        value or ""
    ).strip()


@router.get("")
async def search(
    q: str = Query(
        ...,
        min_length=2,
        max_length=100,
    ),

    user=Depends(
        get_current_user
    ),
):
    await rate_limit_user(user["id"], "search_q", 30, 60)  # 🛡 W10

    query = " ".join(
        q.split()
    )

    pattern = {
        "$regex":
            re.escape(query),

        "$options":
            "i",
    }


    # 🌊 C1.5 — جستجوی سراسری scope-aware است (همان تعریف واحد scope):
    # دانشجو → [ورودی خودش، سراسری]؛ مدیر محتوا/مالک → بدون فیلتر
    # (پیش‌نمایش). حتی *عنوان* محتوای ورودی دیگر هم نمایش داده نمی‌شود.
    _filt = (
        None
        if await db.is_content_admin(user["id"])
        else db.student_intake_filter(
            (user.get("_db") or {}).get("intake", "")
        )
    )
    _scope_q = (
        {"intake": {"$in": _filt}}
        if _filt is not None
        else {}
    )

    # 🌊 W4 — try text search first (uses txt_* indexes), fallback to regex
    async def _q_text_or_regex():
        try:
            # text search respects language none (no stemming) — better for Persian
            cur = db.questions.find({"$and": [approved_query(), {"$text": {"$search": query}}, _scope_q]})
            # project score for sort
            cur = cur.sort([("score", {"$meta": "textScore"})]).limit(10)
            docs = await cur.to_list(10)
            if docs:
                return docs
        except Exception:
            pass
        return await db.questions.find({
            "$and": [approved_query(), {"$or": [
                {"question": pattern}, {"lesson": pattern}, {"topic": pattern},
            ], **_scope_q}],
        }).limit(10).to_list(10)
    async def _faq_text_or_regex():
        try:
            cur = db.faq.find({"$text": {"$search": query}}).sort([("score", {"$meta": "textScore"})]).limit(10)
            docs = await cur.to_list(10)
            if docs:
                return docs
        except Exception:
            pass
        return await db.faq.find({"$or": [{"question": pattern}, {"answer": pattern}]}).limit(10).to_list(10)

    # 🌊 W6/PERF-02 — timeout کلی: به‌جای آویزان‌ماندن، ۵۰۳ صادقانه
    try:
        (
            resources,
            questions,
            faqs,
            schedules,
            subjects,
            books,
        ) = await asyncio.wait_for(asyncio.gather(
            db.search_resources(
                query,
                intake=_filt,
            ),
    
            _q_text_or_regex(),
    
            _faq_text_or_regex(),
    
            db.schedules.find({
                "$or": [
                    {
                        "lesson":
                            pattern,
                    },
    
                    {
                        "teacher":
                            pattern,
                    },
    
                    {
                        "notes":
                            pattern,
                    },
                ],
            })
            .sort(
                "date",
                -1,
            )
            .limit(10)
            .max_time_ms(_SEARCH_MAX_TIME_MS)
            .to_list(10),
    
            db.ref_subjects.find({
                "name":
                    pattern,
    
                **_scope_q,
            })
            .limit(10)
            .max_time_ms(_SEARCH_MAX_TIME_MS)
            .to_list(10),
    
            db.ref_books.find({
                "name":
                    pattern,
            })
            .limit(10)
            .max_time_ms(_SEARCH_MAX_TIME_MS)
            .to_list(10),

        ), timeout=_SEARCH_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=503,
                                detail="جستجو طولانی شد؛ دوباره تلاش کن.")


    results = []


    for item in (
        resources or []
    )[:10]:
        subtitle = " • ".join(
            filter(
                None,
                [
                    text(
                        item.get(
                            "lesson_name"
                        )
                    ),

                    text(
                        item.get(
                            "session_topic"
                        )
                    ),
                ],
            )
        )

        results.append({
            "id":
                text(
                    item.get("_id")
                ),

            "type":
                "resource",

            "icon":
                "📗",

            "title": (
                text(
                    item.get("name")
                )
                or "منبع آموزشی"
            ),

            "subtitle":
                subtitle,

            "route":
                "/learn/resources",
        })


    for item in questions:
        subtitle = " • ".join(
            filter(
                None,
                [
                    text(
                        item.get(
                            "lesson"
                        )
                    ),

                    text(
                        item.get(
                            "topic"
                        )
                    ),
                ],
            )
        )

        results.append({
            "id":
                text(
                    item.get("_id")
                ),

            "type":
                "question",

            "icon":
                "🧪",

            "title":
                text(
                    item.get(
                        "question"
                    )
                )[:140],

            "subtitle":
                subtitle,

            "route":
                "/learn/questions",
        })


    for item in faqs:
        results.append({
            "id":
                text(
                    item.get("_id")
                ),

            "type":
                "faq",

            "icon":
                "❓",

            "title":
                text(
                    item.get(
                        "question"
                    )
                ),

            "subtitle": (
                text(
                    item.get(
                        "category"
                    )
                )
                or "راهنما"
            ),

            "route":
                "/me/faq",
        })


    for item in schedules:
        subtitle = " • ".join(
            filter(
                None,
                [
                    text(
                        item.get(
                            "date"
                        )
                    ),

                    text(
                        item.get(
                            "time"
                        )
                    ),

                    text(
                        item.get(
                            "teacher"
                        )
                    ),
                ],
            )
        )

        results.append({
            "id":
                text(
                    item.get("_id")
                ),

            "type":
                "schedule",

            "icon":
                "📅",

            "title": (
                text(
                    item.get(
                        "lesson"
                    )
                )
                or "برنامه درسی"
            ),

            "subtitle":
                subtitle,

            "route":
                "/schedule",
        })


    for item in subjects:
        results.append({
            "id":
                text(
                    item.get("_id")
                ),

            "type":
                "reference",

            "icon":
                "📘",

            "title":
                text(
                    item.get("name")
                ),

            "subtitle":
                "موضوع رفرنس",

            "route":
                "/learn/references",
        })


    # ⚡ W1 — prefetch گروهی (ضد N+1): قبلاً به‌ازای هر کتاب یک
    # resolver‌کوئری + یک کوئری fork می‌رفت؛ حالا موضوع والد و forkها
    # یک‌جا با $in خوانده می‌شوند. معنای ref_book_intake عیناً حفظ شده:
    # intake صریح کتاب (fork) مقدم بر intake موضوع والد است.
    if _filt is not None and books:
        from bson import ObjectId as _OId

        def _safe_oid(v):
            try:
                return _OId(text(v))
            except Exception:
                return None

        _need_subj = {
            text(b.get("subject_id"))
            for b in books if "intake" not in b
        }
        _soids = [o for o in (_safe_oid(x) for x in _need_subj) if o]
        _sdocs = await db.ref_subjects.find(
            {"_id": {"$in": _soids}}).to_list(50) if _soids else []
        _subj_intake = {
            text(s.get("_id")): s.get("intake") or ""
            for s in _sdocs
        }

        _viewer = next((v for v in _filt if v), "")
        _suppressed = set()
        if _viewer:
            _fdocs = await db.ref_books.find({
                "intake": _viewer,
                "fork_of": {"$in": [text(b.get("_id")) for b in books]},
            }).to_list(50)
            _suppressed = {text(f.get("fork_of")) for f in _fdocs}

    for item in books:
        # 🌊 C1.5 — کتاب فرزند موضوع است؛ scope از resolver والد می‌آید
        if _filt is not None:
            _bi = (
                (item.get("intake") or "")
                if "intake" in item
                else _subj_intake.get(text(item.get("subject_id")), "")
            )
            if _bi not in _filt:
                continue

            # 🍴 Q1 — baseای که برای ورودیِ بیننده fork دارد سرکوب می‌شود
            # (جستجو نباید نسخه‌ی سراسری+اختصاصی را با هم تکراری نشان دهد)
            if _viewer and text(item.get("_id")) in _suppressed:
                continue

        results.append({
            "id":
                text(
                    item.get("_id")
                ),

            "type":
                "reference",

            "icon":
                "📕",

            "title":
                text(
                    item.get("name")
                ),

            "subtitle":
                "کتاب مرجع",

            "route":
                "/learn/references",
        })



    order = {
        "question": 0,
        "resource": 1,
        "reference": 3,
        "schedule": 4,
        "faq": 5,
    }


    results.sort(
        key=lambda item:
            order.get(
                item["type"],
                99,
            )
    )


    return {
        "query":
            query,

        "results":
            results[:50],

        "total":
            len(results),
    }
