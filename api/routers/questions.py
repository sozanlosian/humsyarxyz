"""Question practice, persistent exams and designs."""

from __future__ import annotations

import random
import time
import uuid

from html import escape
from typing import (
    Any,
    List,
    Mapping,
    Optional,
)

from bson import ObjectId

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)

from fastapi.responses import Response

from pydantic import (
    BaseModel,
    Field,
)

from api.auth import (
    ADMIN_ID,
    get_question_access_user,
    require_feature,  # 🌊 W7
)

from api.user_metrics import (
    non_negative_int,
)

from database import db
from api.rate_limit import rate_limit_user  # 🛡 W3/SEC-03
from time_utils import utc_now_iso
from question_bank import ExamService, QuestionBankService, QuestionDomainError
from question_bank.ai_practice import AIPersonalPracticeService


router = APIRouter()

exam_sessions = db.exam_sessions
question_bank = QuestionBankService(db)
exam_domain = ExamService(db)
ai_practice = AIPersonalPracticeService(db)


def _domain_error(exc: QuestionDomainError):
    raise HTTPException(status_code=exc.status_code,
                        detail={"code": exc.code, "message": exc.message,
                                **({"details": exc.details} if exc.details else {})})


def _pub_prestige(ev):
    """شکل‌دهی عمومی خروجی موتور Prestige برای کلاینت (افزایشی روی پاسخ‌های موجود).
    مهم: منطق در database.py است؛ این فقط «presentation» است (قرارداد §د)."""
    if not ev or ev.get('ignored'):
        return None
    d = ev.get('display') or {}
    e = ev.get('events') or {}
    celeb = None
    if e.get('rank_up'):
        ru = e['rank_up']
        celeb = {'kind': 'rank', 'title': ru.get('to'), 'from_title': ru.get('from'),
                 'icon': ru.get('icon'), 'roman': d.get('roman'),
                 'color': d.get('color'), 'gradient': d.get('gradient')}
    elif e.get('div_up'):
        du = e['div_up']
        celeb = {'kind': 'div', 'title': du.get('rank'), 'roman': du.get('roman'),
                 'icon': du.get('icon'),
                 'color': d.get('color'), 'gradient': d.get('gradient')}
    return {
        'xp_gained': ev.get('xp_gained', 0),
        'breakdown': ev.get('breakdown', []),
        'streak': ev.get('streak'),
        'display': d,
        'challenge_ready': bool(e.get('challenge_ready')),
        'celebration': celeb,
    }


async def _answer_first_time(user_id: int, question_id: str) -> bool:
    """پیش‌چک یک‌بارهرسؤال — باید **قبل** از db.save_answer صدا زده شود."""
    try:
        return (await db.answers.find_one(
            {'user_id': user_id, 'question_id': question_id}, {'_id': 1})) is None
    except Exception:
        return True


async def _answer_prestige(user_id: int, question: dict,
                           is_correct: bool, first_time: bool) -> dict:
    """رویداد موتور پس از ثبت پاسخ — هرگز قرارداد اصلی را نمی‌شکند (در خطا None)."""
    try:
        ev = await db.prestige_event(
            user_id, 'answer',
            {'is_correct': is_correct,
             'difficulty': question.get('difficulty', ''),
             'first_time': first_time})
        return _pub_prestige(ev)
    except Exception:
        return None

ALLOWED_DIFFICULTIES = {
    "آسان 🟢",
    "متوسط 🟡",
    "سخت 🔴",
}


async def ensure_indexes():
    await exam_sessions.create_index(
        "session_id",
        unique=True,
        background=True,
    )

    await exam_sessions.create_index(
        [
            ("user_id", 1),
            ("started_at", -1),
        ],
        background=True,
    )

    await db.answers.create_index(
        [
            ("user_id", 1),
            ("answered_at", -1),
        ],
        background=True,
    )


def text(
    value: Any,
    default: str = "",
) -> str:
    if value is None:
        return default

    return str(value).strip()


def safe_question(
    document: Mapping[
        str,
        Any,
    ] | None,
) -> dict | None:
    if not isinstance(
        document,
        Mapping,
    ):
        return None

    options = document.get(
        "options"
    )

    if not isinstance(
        options,
        list,
    ):
        options = []

    return {
        "id": text(
            document.get("_id")
        ),

        "lesson": text(
            document.get("lesson")
        ),

        "topic": text(
            document.get("topic")
        ),

        "difficulty": (
            text(
                document.get(
                    "difficulty"
                )
            )
            or "متوسط 🟡"
        ),

        "question": text(
            document.get("question")
        ),

        "options": [
            str(item)
            for item in options
        ],
    }


def exclude_ids(
    value: str | None,
) -> list[str]:
    if not value:
        return []

    result = []

    for item in value.split(",")[:100]:
        item = item.strip()

        if ObjectId.is_valid(item):
            result.append(item)

    return result


def exam_summary(
    session: Mapping[
        str,
        Any,
    ],
) -> dict:
    question_ids = (
        session.get(
            "question_ids"
        )
        or []
    )

    total = len(question_ids)

    answered = non_negative_int(
        session.get("answered")
    )

    correct = min(
        non_negative_int(
            session.get("correct")
        ),
        answered,
    )

    return {
        "session_id": text(
            session.get(
                "session_id"
            )
        ),

        "lesson": text(
            session.get("lesson")
        ),

        "topic": text(
            session.get("topic")
        ),

        "status": (
            text(
                session.get(
                    "status"
                )
            )
            or "active"
        ),

        "started_at": text(
            session.get(
                "started_at"
            )
        ),

        "finished_at": text(
            session.get(
                "finished_at"
            )
        ),

        "minutes":
            non_negative_int(
                session.get(
                    "minutes"
                )
            ),

        "progress": min(
            non_negative_int(
                session.get("index")
            ),
            total,
        ),

        "correct": correct,

        "answered": answered,

        "total": total,

        "percentage": (
            round(
                correct
                / answered
                * 100
            )
            if answered
            else 0
        ),
    }


async def load_session(
    session_id: str,
    user_id: int,
) -> dict:
    session = (
        await exam_sessions.find_one(
            {
                "session_id":
                    session_id,

                "user_id":
                    user_id,
            }
        )
    )

    if not session:
        raise HTTPException(
            status_code=404,
            detail="آزمون پیدا نشد",
        )

    return session


async def expire_if_needed(
    session: dict,
) -> dict:
    deadline = session.get(
        "deadline_ts"
    )

    if (
        session.get("status")
        == "active"
        and deadline
        and int(time.time())
        >= int(deadline)
    ):
        finished_at = (
            utc_now_iso()
        )

        await exam_sessions.update_one(
            {
                "_id": session["_id"],
                "status": "active",
            },

            {
                "$set": {
                    "status":
                        "expired",

                    "finished_at":
                        finished_at,
                }
            },
        )

        session["status"] = (
            "expired"
        )

        session["finished_at"] = (
            finished_at
        )

    return session


@router.get("/taxonomy")
async def taxonomy(user=Depends(get_question_access_user)):
    return {"lessons": await question_bank.taxonomy_tree(
        visible_intakes=question_bank.student_intakes(user), only_with_questions=False)}


@router.get("/lessons")
async def get_lessons(user=Depends(get_question_access_user)):
    tree = await question_bank.taxonomy_tree(
        visible_intakes=question_bank.student_intakes(user), only_with_questions=False)
    return {"lessons": [{"id": row["id"], "name": row["name"],
                          "term": row["term"], "count": row["question_count"]}
                         for row in tree]}


@router.get("/topics/{lesson}")
async def get_topics(lesson: str, user=Depends(get_question_access_user)):
    tree = await question_bank.taxonomy_tree(
        visible_intakes=question_bank.student_intakes(user), only_with_questions=False)
    selected = next((row for row in tree if row["id"] == lesson or row["name"] == lesson.strip()), None)
    if not selected:
        raise HTTPException(404, "درس پیدا نشد")
    return {"lesson_id": selected["id"], "topics": [
        {"id": topic["id"], "name": topic["name"], "count": topic["question_count"]}
        for topic in selected["topics"]]}


async def _request_taxonomy(user, lesson_id=None, topic_id=None, lesson=None, topic=None):
    if not any((lesson_id, topic_id, lesson, topic)):
        return {}
    try:
        return await question_bank.resolve_taxonomy(
            lesson_id=lesson_id, topic_id=topic_id, lesson=lesson, topic=topic,
            visible_intakes=question_bank.student_intakes(user),
            require_topic=bool(topic_id or topic))
    except QuestionDomainError as exc:
        _domain_error(exc)


@router.get("/practice")
async def practice(
    user=Depends(get_question_access_user),
    lesson_id: str | None = Query(None), topic_id: str | None = Query(None),
    lesson: str | None = Query(None, max_length=100),
    topic: str | None = Query(None, max_length=100),
    exclude: str | None = Query(None, deprecated=True),
):
    taxonomy = await _request_taxonomy(user, lesson_id, topic_id, lesson, topic)
    try:
        return await question_bank.practice_next(user=user, taxonomy=taxonomy, mode="free")
    except QuestionDomainError as exc:
        _domain_error(exc)


@router.get("/weak")
async def weak(user=Depends(get_question_access_user)):
    stats = await question_bank.stats(user=user)
    weak_topics = sorted(stats["weak_topics"], key=lambda x: (x["accuracy"], -x["attempts"]))
    if not weak_topics:
        return {"question": None, "message": "برای تشخیص نقاط ضعف، تمرین بیشتری لازم است", "stats": stats}
    selected = weak_topics[0]
    taxonomy = {"lesson_id": selected["lesson_id"], "topic_id": selected["topic_id"],
                "lesson": selected["lesson"], "topic": selected["topic"]}
    result = await question_bank.practice_next(user=user, taxonomy=taxonomy, mode="weak")
    result["weak_topic"] = selected
    return result


@router.get("/hard")
async def hard(
    user=Depends(get_question_access_user),
    lesson_id: str | None = Query(None), topic_id: str | None = Query(None),
    lesson: str | None = Query(None), topic: str | None = Query(None),
    exclude: str | None = Query(None, deprecated=True),
):
    taxonomy = await _request_taxonomy(user, lesson_id, topic_id, lesson, topic)
    return await question_bank.practice_next(user=user, taxonomy=taxonomy, mode="hard")


class AnswerInput(BaseModel):
    question_id: str = Field(min_length=24, max_length=24)
    selected: int = Field(ge=0, le=3)


@router.post("/answer")
async def answer(body: AnswerInput, user=Depends(get_question_access_user)):
    # 🛡 W3/SEC-03 — سقف گشاد برای آزمون سرعتی، ولی ضد بات
    await rate_limit_user(user["id"], "q_answer", 100, 60)
    question = await db.get_question_by_id(body.question_id)
    if not question:
        raise HTTPException(404, "سؤال پیدا نشد")
    try:
        await question_bank.verify_access(question, user)
    except QuestionDomainError as exc:
        _domain_error(exc)
    correct_answer = int(question.get("correct_answer", 0) or 0)
    is_correct = body.selected == correct_answer
    first_time = await _answer_first_time(user["id"], body.question_id)
    try:
        await question_bank.record_answer(user=user, question=question,
                                          selected=body.selected, is_correct=is_correct)
    except QuestionDomainError as exc:
        _domain_error(exc)
    prestige = await _answer_prestige(user["id"], question, is_correct, first_time)
    from question_bank.contracts import public_question
    return {"is_correct": is_correct, "correct_answer": correct_answer,
            "explanation": text(question.get("explanation")),
            "question": public_question(question, reveal=True), "prestige": prestige}


@router.get("/practice/stats")
async def practice_stats(user=Depends(get_question_access_user)):
    return await question_bank.stats(user=user)


class AIGenerateInput(BaseModel):
    lesson_id: str
    topic_id: str
    difficulty: str = "medium"
    note: str = Field(default="", max_length=500)


@router.post("/practice/ai/generate")
async def generate_ai_practice(body: AIGenerateInput, user=Depends(require_feature("ai_practice"))):
    # 🛡 W3/SEC-03 — تولید AI هزینه دارد؛ سقف سخت‌گیرانه
    await rate_limit_user(user["id"], "ai_generate", 10, 60)
    taxonomy = await _request_taxonomy(user, body.lesson_id, body.topic_id)
    try:
        return await ai_practice.generate(user=user, taxonomy=taxonomy,
                                          difficulty=body.difficulty, note=body.note,
                                          require_exhaustion=True)
    except QuestionDomainError as exc:
        _domain_error(exc)


class AIAnswerInput(BaseModel):
    selected: int = Field(ge=0, le=3)


@router.post("/practice/ai/{ai_question_id}/answer")
async def answer_ai_practice(ai_question_id: str, body: AIAnswerInput,
                             user=Depends(require_feature("ai_practice"))):
    try: return await ai_practice.answer(user=user, ai_question_id=ai_question_id, selected=body.selected)
    except QuestionDomainError as exc: _domain_error(exc)


@router.post("/practice/ai/{ai_question_id}/propose")
async def propose_ai_practice(ai_question_id: str, user=Depends(require_feature("ai_practice"))):
    try: return await ai_practice.propose(user=user, ai_question_id=ai_question_id)
    except QuestionDomainError as exc: _domain_error(exc)


@router.get("/history")
async def answer_history(
    user=Depends(get_question_access_user),
    skip: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100),
    after: Optional[str] = Query(None, max_length=32, description="cursor _id"),
):
    query = {"user_id": user["id"]}
    # 🌊 W4 — cursor pagination
    if after:
        try:
            from bson import ObjectId as _OID
            if _OID.is_valid(after):
                query["_id"] = {"$lt": _OID(after)}
                records = await db.answers.find(query).sort("_id", -1).limit(limit + 1).to_list(limit + 1)
                has_more = len(records) > limit
                if has_more:
                    records = records[:limit]
                next_cursor = str(records[-1]["_id"]) if records and has_more else None
                # we still need docs mapping but skip total for cursor
                ids = [ObjectId(str(x.get("question_id"))) for x in records if ObjectId.is_valid(str(x.get("question_id")))]
                docs = await db.questions.find({"_id": {"$in": ids}}).to_list(len(ids) or 1)
                by_id = {str(x["_id"]): x for x in docs}
                result = []
                for record in records:
                    qid = text(record.get("question_id")); question = by_id.get(qid)
                    if not question: continue
                    result.append({"id": text(record.get("_id")), "question_id": qid,
                                   "lesson_id": str(question.get("lesson_id") or ""),
                                   "topic_id": str(question.get("topic_id") or ""),
                                   "lesson": text(question.get("lesson")), "topic": text(question.get("topic")),
                                   "question": text(question.get("question")),
                                   "selected": non_negative_int(record.get("selected")),
                                   "correct_answer": non_negative_int(question.get("correct_answer")),
                                   "is_correct": bool(record.get("is_correct")),
                                   "answered_at": text(record.get("answered_at"))})
                return {"answers": result, "total": None, "skip": None, "limit": limit, "next_cursor": next_cursor, "has_more": has_more}
        except Exception:
            pass
    total = await db.answers.count_documents(query)
    records = await db.answers.find(query).sort("answered_at", -1).skip(skip).limit(limit).to_list(limit)
    ids = [ObjectId(str(x.get("question_id"))) for x in records if ObjectId.is_valid(str(x.get("question_id")))]
    docs = await db.questions.find({"_id": {"$in": ids}}).to_list(len(ids) or 1)
    by_id = {str(x["_id"]): x for x in docs}
    result = []
    for record in records:
        qid = text(record.get("question_id")); question = by_id.get(qid)
        if not question: continue
        result.append({"id": text(record.get("_id")), "question_id": qid,
                       "lesson_id": str(question.get("lesson_id") or ""),
                       "topic_id": str(question.get("topic_id") or ""),
                       "lesson": text(question.get("lesson")), "topic": text(question.get("topic")),
                       "question": text(question.get("question")),
                       "selected": non_negative_int(record.get("selected")),
                       "correct_answer": non_negative_int(question.get("correct_answer")),
                       "is_correct": bool(record.get("is_correct")),
                       "answered_at": text(record.get("answered_at"))})
    return {"answers": result, "total": non_negative_int(total), "skip": skip, "limit": limit, "next_cursor": None, "has_more": skip + len(result) < total}


@router.get(
    "/stats/by-lesson"
)
async def stats_by_lesson(
    user=Depends(
        get_question_access_user
    ),
):
    pipeline = [
        {
            "$match": {
                "user_id":
                    user["id"],
            }
        },

        {
            "$addFields": {
                "qid_object": {
                    "$convert": {
                        "input":
                            "$question_id",

                        "to":
                            "objectId",

                        "onError":
                            None,
                    }
                }
            }
        },

        {
            "$lookup": {
                "from":
                    "questions",

                "localField":
                    "qid_object",

                "foreignField":
                    "_id",

                "as":
                    "question",
            }
        },

        {
            "$unwind": {
                "path":
                    "$question",

                "preserveNullAndEmptyArrays":
                    False,
            }
        },

        {
            "$group": {
                "_id":
                    "$question.lesson",

                "total": {
                    "$sum": 1,
                },

                "correct": {
                    "$sum": {
                        "$cond": [
                            "$is_correct",
                            1,
                            0,
                        ]
                    }
                },
            }
        },

        {
            "$sort": {
                "total": -1,
            }
        },
    ]

    try:
        rows = (
            await db.answers
            .aggregate(pipeline)
            .to_list(100)
        )

    except Exception:
        rows = []

    result = []

    for row in rows:
        total = non_negative_int(
            row.get("total")
        )

        correct = (
            non_negative_int(
                row.get("correct")
            )
        )

        if total <= 0:
            continue

        result.append({
            "lesson": (
                text(
                    row.get("_id")
                )
                or "نامشخص"
            ),

            "total":
                total,

            "correct":
                correct,

            "percentage":
                round(
                    correct
                    / total
                    * 100
                ),
        })

    return {
        "lessons": result,
    }


class ExamStartInput(BaseModel):
    lesson_id: Optional[str] = None
    topic_id: Optional[str] = None
    lesson: str = Field(default="", max_length=100)
    topic: Optional[str] = Field(default=None, max_length=100)
    count: int = Field(ge=5, le=100)
    minutes: int = Field(ge=0, le=180)
    output_mode: str = Field(default="app", pattern="^(bot|app|pdf_practice|pdf_exam)$")
    allow_smaller: bool = False
    # ⚔️ True ⇒ شروع چالش ارتقا؛ قواعد سرورمحور قبلی حفظ می‌شود.
    promotion: bool = False


@router.get("/custom-exam/history")
async def exam_history(
    user=Depends(require_feature("mock_exam")),
    skip: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100),
):
    return await exam_domain.history(user=user, skip=skip, limit=limit)


@router.get("/custom-exam/active")
async def active_exam(user=Depends(require_feature("mock_exam"))):
    return {"exam": await exam_domain.active(user=user)}


@router.post("/custom-exam/preview")
async def preview_exam(body: ExamStartInput, user=Depends(require_feature("mock_exam"))):
    if body.promotion:
        raise HTTPException(422, "چالش ارتقا preview عمومی ندارد")
    taxonomy = await _request_taxonomy(user, body.lesson_id, body.topic_id, body.lesson, body.topic)
    try:
        return await exam_domain.preview(user=user, taxonomy=taxonomy,
            requested_count=body.count, minutes=body.minutes,
            output_mode=body.output_mode)
    except QuestionDomainError as exc:
        _domain_error(exc)


@router.post(
    "/custom-exam/start"
)
async def start_exam(
    body: ExamStartInput,

    user=Depends(
        get_question_access_user
    ),
):
    # ⚔️ جریان چالش ارتقا (Spec §۳.۱) — استخر و قواعد کاملاً سرورمحور است؛
    # lesson/topic/count/minutes از کلاینت در این حالت نادیده گرفته می‌شود.
    if getattr(body, "promotion", False):
        chk = await db.challenge_start_check(user["id"])
        if not chk.get("ok"):
            detail = {"code": chk.get("code") or "locked",
                      "view": chk.get("view") or {}}
            if chk.get("hours_left"):
                detail["hours_left"] = chk["hours_left"]
            if chk.get("pool_meta"):
                detail["pool_meta"] = chk["pool_meta"]
            raise HTTPException(status_code=409, detail=detail)
        if chk.get("resume"):
            prev = await exam_sessions.find_one(
                {"user_id": user["id"], "session_id": chk["session_id"]})
            return {
                "session_id": chk["session_id"],
                "total": len((prev or {}).get("question_ids") or []),
                "minutes": 0,
                "ends_at": None,
                "promotion": True,
                "resume": True,
                "index": int((prev or {}).get("index", 0) or 0),
                "target_rank": (prev or {}).get("target_rank"),
                "apex": bool((prev or {}).get("apex")),
                "expires_ts": (prev or {}).get("expires_ts"),
            }
        view = chk.get("view") or {}
        selected_ids = list(chk.get("pool") or [])
        apex = bool(chk.get("apex"))
        now_ts = int(time.time())
        # 🌊 W3 TTL — Date for TTL index
        _expires_at_dt = __import__('datetime', fromlist=['datetime']).datetime.fromtimestamp(now_ts + db.CH_TTL_HOURS * 3600, tz=__import__('datetime', fromlist=['timezone']).timezone.utc)
        document = {
            "session_id": uuid.uuid4().hex[:16],
            "user_id": user["id"],
            "lesson": "⚔️ چالش ارتقا",
            "topic": view.get("title") or "",
            "question_ids": selected_ids,
            "index": 0,
            "minutes": 0,
            "deadline_ts": None,
            "correct": 0,
            "answered": 0,
            "answers": [],
            "status": "active",
            "started_at": utc_now_iso(),
            "finished_at": "",
            "promotion": True,
            "target_rank": view.get("target_rank") or "",
            "apex": apex,
            "expires_ts": now_ts + db.CH_TTL_HOURS * 3600,
            "expires_at": _expires_at_dt,
        }
        await exam_sessions.insert_one(document)
        await db.users.update_one({"user_id": user["id"]},
            {"$set": {"challenge.target_rank": view.get("target_rank") or "",
                      "challenge.apex": apex}})
        return {
            "session_id": document["session_id"],
            "total": len(selected_ids),
            "minutes": 0,
            "ends_at": None,
            "promotion": True,
            "resume": False,
            "index": 0,
            "target_rank": view.get("target_rank"),
            "target_title": view.get("title"),
            "target_icon": view.get("icon"),
            "apex": apex,
            "pass_pct": db.CH_APEX_PASS_PCT if apex else db.CH_PASS_PCT,
            "expires_ts": document["expires_ts"],
        }

    taxonomy = await _request_taxonomy(user, body.lesson_id, body.topic_id, body.lesson, body.topic)
    try:
        return await exam_domain.create(
            user=user, taxonomy=taxonomy, requested_count=body.count,
            minutes=body.minutes, output_mode=body.output_mode,
            allow_smaller=body.allow_smaller)
    except QuestionDomainError as exc:
        _domain_error(exc)



@router.get(
    "/custom-exam/"
    "{session_id}/next"
)
async def exam_next(
    session_id: str,

    user=Depends(
        get_question_access_user
    ),
):
    session = (
        await load_session(
            session_id,
            user["id"],
        )
    )

    if not session.get("promotion"):
        try:
            return await exam_domain.next_question(session_id=session_id, user=user)
        except QuestionDomainError as exc:
            _domain_error(exc)

    session = (
        await expire_if_needed(
            session
        )
    )

    if (
        session.get("status")
        != "active"
    ):
        return {
            "finished": True,
            **exam_summary(session),
        }

    question_ids = (
        session.get(
            "question_ids"
        )
        or []
    )

    index = non_negative_int(
        session.get("index")
    )

    while index < len(
        question_ids
    ):
        question = (
            await db.get_question_by_id(
                question_ids[index]
            )
        )

        formatted = (
            safe_question(question)
        )

        if formatted:
            if session.get(
                "deadline_ts"
            ):
                seconds_left = max(
                    0,

                    int(
                        session[
                            "deadline_ts"
                        ]
                    )
                    - int(time.time()),
                )

            else:
                seconds_left = None

            return {
                "finished": False,

                "question":
                    formatted,

                "progress":
                    index + 1,

                "total":
                    len(
                        question_ids
                    ),

                "seconds_left":
                    seconds_left,
            }

        index += 1

        await exam_sessions.update_one(
            {
                "_id":
                    session["_id"],
            },

            {
                "$set": {
                    "index":
                        index,
                }
            },
        )

    finished_at = (
        utc_now_iso()
    )

    await exam_sessions.update_one(
        {
            "_id":
                session["_id"],
        },

        {
            "$set": {
                "status":
                    "finished",

                "finished_at":
                    finished_at,

                "index":
                    index,
            }
        },
    )

    session.update({
        "status":
            "finished",

        "finished_at":
            finished_at,

        "index":
            index,
    })

    return {
        "finished": True,
        **exam_summary(session),
    }


class ExamAnswerInput(BaseModel):
    selected: int = Field(
        ge=0,
        le=3,
    )


@router.post(
    "/custom-exam/"
    "{session_id}/answer"
)
async def exam_answer(
    session_id: str,
    body: ExamAnswerInput,

    user=Depends(
        get_question_access_user
    ),
):
    session = (
        await load_session(
            session_id,
            user["id"],
        )
    )

    session = (
        await expire_if_needed(
            session
        )
    )

    # Normal custom exams use the single shared domain. Promotion challenge
    # keeps its locked Prestige policy below.
    if not session.get("promotion"):
        try:
            return await exam_domain.answer(session_id=session_id, user=user, selected=body.selected)
        except QuestionDomainError as exc:
            _domain_error(exc)

    # ⚔️ TTL چالش ارتقا (۲۴ساعته) — انقضا = Fail خودکار سرورمحور
    if (
        session.get("promotion")
        and session.get("status") == "active"
        and session.get("expires_ts")
        and int(time.time()) >= int(session["expires_ts"])
    ):
        try:
            await db.challenge_expire_session(session)
        except Exception:
            pass
        _ans = int(session.get("answered", 0) or 0)
        _cor = int(session.get("correct", 0) or 0)
        raise HTTPException(
            status_code=409,
            detail={
                "code": "promotion_failed_ttl",
                "win": False,
                "pct": round(_cor / _ans * 100, 1) if _ans else 0,
                "cooldown_h": (db.CH_APEX_COOLDOWN_H
                               if session.get("apex")
                               else db.CH_COOLDOWN_H),
            },
        )

    if (
        session.get("status")
        != "active"
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "زمان آزمون "
                "تمام شده است"
            ),
        )

    question_ids = (
        session.get(
            "question_ids"
        )
        or []
    )

    index = non_negative_int(
        session.get("index")
    )

    if index >= len(
        question_ids
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "آزمون تمام شده است"
            ),
        )

    question_id = (
        question_ids[index]
    )

    question = (
        await db.get_question_by_id(
            question_id
        )
    )

    if not question:
        raise HTTPException(
            status_code=404,
            detail="سؤال پیدا نشد",
        )

    correct_answer = (
        non_negative_int(
            question.get(
                "correct_answer"
            )
        )
    )

    is_correct = (
        body.selected
        == correct_answer
    )

    final_answer = (
        index + 1
        >= len(question_ids)
    )

    answered_at = (
        utc_now_iso()
    )

    update = {
        "$inc": {
            "index":
                1,

            "answered":
                1,

            "correct": (
                1
                if is_correct
                else 0
            ),
        },

        "$push": {
            "answers": {
                "question_id":
                    question_id,

                "selected":
                    body.selected,

                "correct_answer":
                    correct_answer,

                "is_correct":
                    is_correct,

                "answered_at":
                    answered_at,
            }
        },
    }

    if final_answer:
        update["$set"] = {
            "status":
                "finished",

            "finished_at":
                answered_at,
        }

    result = (
        await exam_sessions
        .update_one(
            {
                "_id":
                    session["_id"],

                "status":
                    "active",

                "index":
                    index,
            },

            update,
        )
    )

    if result.modified_count != 1:
        raise HTTPException(
            status_code=409,
            detail=(
                "این سؤال قبلاً "
                "پاسخ داده شده است"
            ),
        )

    # 👑 Prestige: FT چک → ثبت → رویداد پاسخ → (در پایانی: رویداد تکمیل آزمون)
    first_time = await _answer_first_time(user["id"], question_id)

    await db.save_answer(
        user["id"],
        question_id,
        body.selected,
        is_correct,
    )

    prestige = await _answer_prestige(
        user["id"], question, is_correct, first_time)

    prestige_exam = None
    promotion_result = None
    if final_answer and session.get("promotion"):
        # ⚔️ پایان چالش: نتیجه‌ی سرورمحور — بدون رویداد exam_complete
        # (چالش جزو آمار/XP آزمون‌ها شمرده نمی‌شود؛ پاسخ‌ها XP خود را گرفته‌اند)
        try:
            new_correct = non_negative_int(session.get("correct")) + (1 if is_correct else 0)
            answered_now = index + 1
            pct = round(new_correct / answered_now * 100, 1) if answered_now else 0
            apex = bool(session.get("apex"))
            need = db.CH_APEX_COUNT if apex else db.CH_COUNT
            pass_pct = db.CH_APEX_PASS_PCT if apex else db.CH_PASS_PCT
            won = answered_now >= need and pct >= pass_pct
            res = await db.challenge_resolve(user["id"], session, won, pct)
            promotion_result = {
                "win": bool(res.get("win")),
                "pct": pct,
                "pass_pct": pass_pct,
                "need": need,
                "apex": apex,
                "reward": ((db.CH_APEX_WIN if apex else db.CH_CHALLENGE_WIN)
                           if res.get("win") else 0),
                "celebration": res.get("celebration"),
                "cooldown_h": res.get("cooldown_h"),
                "cooldown_until": res.get("cooldown_until"),
                "target_rank": (session.get("target_rank")
                                or (session.get("view") or {}).get("target_rank")),
            }
        except Exception:
            promotion_result = None
    elif final_answer:
        try:
            new_correct = non_negative_int(session.get("correct")) + (1 if is_correct else 0)
            answered_now = index + 1
            pct = round(new_correct / answered_now * 100, 1) if answered_now else 0
            ev = await db.prestige_event(
                user["id"], 'exam_complete',
                {'pct': pct, 'total': len(question_ids)})
            prestige_exam = _pub_prestige(ev)
        except Exception:
            prestige_exam = None

    return {
        "is_correct":
            is_correct,

        "correct_answer":
            correct_answer,

        "explanation":
            text(
                question.get(
                    "explanation"
                )
            ),

        "progress":
            index + 1,

        "total":
            len(question_ids),

        "finished":
            final_answer,

        "prestige": prestige,
        "prestige_exam": prestige_exam,
        "promotion_result": promotion_result,
    }


@router.delete(
    "/custom-exam/{session_id}"
)
async def abandon_exam(
    session_id: str,

    user=Depends(
        get_question_access_user
    ),
):
    # ⚔️ رها کردن چالش ارتقا = Fail + کول‌داون (ضدتقلب — Spec §۳.۱)
    sess_doc = await exam_sessions.find_one(
        {"session_id": session_id, "user_id": user["id"],
         "status": "active"})
    if sess_doc and not sess_doc.get("promotion"):
        try:
            return await exam_domain.abandon(session_id=session_id, user=user)
        except QuestionDomainError as exc:
            _domain_error(exc)
    result = (
        await exam_sessions
        .update_one(
            {
                "session_id":
                    session_id,

                "user_id":
                    user["id"],

                "status":
                    "active",
            },

            {
                "$set": {
                    "status":
                        "abandoned",

                    "finished_at":
                        utc_now_iso(),
                }
            },
        )
    )

    if result.matched_count == 0:
        raise HTTPException(
            status_code=404,
            detail=(
                "آزمون فعال "
                "پیدا نشد"
            ),
        )

    promotion_result = None
    if (sess_doc or {}).get("promotion"):
        try:
            _ans = int(sess_doc.get("answered", 0) or 0)
            _cor = int(sess_doc.get("correct", 0) or 0)
            res = await db.challenge_resolve(
                user["id"], sess_doc, False,
                round(_cor / _ans * 100, 1) if _ans else 0)
            promotion_result = {
                "win": False,
                "pct": res.get("pct"),
                "cooldown_h": res.get("cooldown_h"),
                "cooldown_until": res.get("cooldown_until"),
            }
        except Exception:
            promotion_result = None

    return {
        "ok": True,
        "promotion_result": promotion_result,
    }


@router.get("/custom-exam/{session_id}/pdf")
async def exam_pdf(session_id: str, mode: str = Query("exam", pattern="^(practice|exam)$"),
                   user=Depends(require_feature("pdf_generation"))):
    # 🌊 W7 — مصرف سهمیه‌ی ژنریک (پیش‌فرض نامحدود؛ با ۴۲۹ صادقانه)
    try:
        _pol = await db.get_feature_policy("pdf_generation") or {}
        _q = _pol.get("quota") or {}
        if _q.get("kind") in ("daily", "monthly") and int(_q.get("limit") or 0) > 0:
            _ok, _used = await db.feature_consume(
                user["id"], "pdf_generation", _q["kind"], int(_q["limit"]))
            if not _ok:
                from core.errors import Code, DEFAULT_MESSAGE
                await db.log_feature_event("pdf_generation", "quota_exhausted",
                                           user["id"], {})
                raise HTTPException(status_code=429, detail={
                    "code": Code.QUOTA_EXHAUSTED,
                    "message": DEFAULT_MESSAGE[Code.QUOTA_EXHAUSTED],
                    "feature": "pdf_generation"})
    except HTTPException:
        raise
    except Exception:
        pass  # خطای زیرساخت سهمیه: UX را خراب نکن (لاگ در لایه‌ی db)
    try:
        content, meta = await exam_domain.generate_pdf(session_id=session_id, user=user, mode=mode)
    except QuestionDomainError as exc:
        _domain_error(exc)
    filename = f"humsyar-exam-{meta['exam_code']}.pdf"
    return Response(content=content, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"',
                             "X-Exam-Session": session_id,
                             "X-PDF-Generation": meta["generation_id"],
                             "X-Content-SHA256": meta["sha256"]})


class QuestionDesignInput(BaseModel):
    lesson_id: Optional[str] = None
    topic_id: Optional[str] = None
    lesson: str = Field(default="", max_length=100)
    topic: str = Field(default="", max_length=100)

    question: str = Field(
        min_length=10,
        max_length=2000,
    )

    options: List[str] = Field(
        min_length=4,
        max_length=4,
    )

    correct: int = Field(
        ge=0,
        le=3,
    )

    explanation: Optional[str] = Field(
        default="",
        max_length=3000,
    )

    difficulty: str = (
        "متوسط 🟡"
    )


def design_data(
    body: QuestionDesignInput,
) -> dict:
    options = [
        " ".join(item.split())
        for item in body.options
    ]

    if (
        any(
            not item
            for item in options
        )
        or len(set(options)) != 4
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "چهار گزینه متفاوت "
                "و غیرخالی لازم است"
            ),
        )

    from question_bank.contracts import canonical_difficulty
    difficulty = canonical_difficulty(body.difficulty or "medium")

    return {
        "lesson_id": body.lesson_id,
        "topic_id": body.topic_id,
        "lesson":
            " ".join(
                body.lesson.split()
            ),

        "topic":
            " ".join(
                body.topic.split()
            ),

        "difficulty":
            difficulty,

        "question":
            " ".join(
                body.question.split()
            ),

        "options":
            options,

        "correct_answer":
            body.correct,

        "explanation":
            str(
                body.explanation
                or ""
            ).strip(),
    }


@router.post("/design")
async def design(body: QuestionDesignInput, user=Depends(get_question_access_user)):
    privileged = await db.has_permission(user["id"], "questions.review")
    try:
        result = await question_bank.create_question(
            actor=user, payload=design_data(body),
            source="web_admin" if privileged else "student_webapp",
            creator_type="admin" if privileged else "student",
            auto_approve=False,
            intake=(await db.get_scoped_intake(user["id"])) if privileged else None)
    except QuestionDomainError as exc:
        _domain_error(exc)
    return {"ok": True, "question_id": str(result["question"]["_id"]),
            "auto_approved": False,
            "status": result["question"]["status"],
            "message": "✅ سؤال برای بررسی مستقل ارسال شد"}


@router.get("/my-designs")
async def my_designs(
    user=Depends(get_question_access_user),
    skip: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100),
):
    return await question_bank.list_my_contributions(user["id"], skip=skip, limit=limit)


@router.put("/my-designs/{question_id}")
async def update_my_design(
    question_id: str, body: QuestionDesignInput,
    resubmit: bool = Query(False), user=Depends(get_question_access_user),
):
    try:
        document = await question_bank.update_contribution(
            question_id=question_id, user=user, payload=design_data(body), resubmit=resubmit)
    except QuestionDomainError as exc:
        _domain_error(exc)
    return {"ok": True, "status": document.get("status"), "version": document.get("version")}


@router.post("/my-designs/{question_id}/resubmit")
async def resubmit_my_design(question_id: str, body: QuestionDesignInput,
                             user=Depends(get_question_access_user)):
    try:
        document = await question_bank.update_contribution(
            question_id=question_id, user=user, payload=design_data(body), resubmit=True)
    except QuestionDomainError as exc:
        _domain_error(exc)
    return {"ok": True, "status": document.get("status"), "version": document.get("version")}


@router.delete("/my-designs/{question_id}")
async def delete_my_design(
    question_id: str,
    user=Depends(get_question_access_user),
):
    """Compatibility verb: withdraws a contribution without deleting data."""
    try:
        document = await question_bank.withdraw_contribution(
            question_id=question_id, user=user)
    except QuestionDomainError as exc:
        _domain_error(exc)
    return {"ok": True, "deleted": False, "status": document.get("status"),
            "message": "سؤال بدون حذف داده از صف خارج شد"}
