"""Persistent shared exam domain for Bot, API and PDF output."""
from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from datetime import timedelta
from typing import Mapping

from bson import ObjectId

from time_utils import now_utc, parse_machine_datetime, utc_now_iso
from .contracts import QuestionDomainError, public_question
from .service import QuestionBankService

OUTPUT_MODES = frozenset({"bot", "app", "pdf_practice", "pdf_exam"})
EXAM_STATUSES = frozenset({"active", "finished", "expired", "abandoned"})


# 🌊 W6/PERF-03 — کش کوتاه‌مدت PDF (همان ورودی ⇒ همان بایت؛ باطل‌سازی با
# updated_at سؤال). کرانه‌دار و TTLدار تا حافظه نشت نکند.
_PDF_CACHE: dict = {}
_PDF_CACHE_TTL_S = 600
_PDF_CACHE_MAX = 30


class ExamService:
    def __init__(self, database):
        self.db = database
        self.qbank = QuestionBankService(database)
        self.sessions = database.exam_sessions

    async def preview(self, *, user: Mapping, taxonomy: Mapping,
                      requested_count: int, minutes: int, output_mode: str,
                      difficulty: str | None = None) -> dict:
        if output_mode not in OUTPUT_MODES:
            raise QuestionDomainError("invalid_output_mode", "نوع اجرای آزمون معتبر نیست")
        if not 5 <= int(requested_count) <= 100:
            raise QuestionDomainError("invalid_question_count", "تعداد سؤال باید بین ۵ تا ۱۰۰ باشد")
        if not 0 <= int(minutes) <= 180:
            raise QuestionDomainError("invalid_exam_duration", "زمان آزمون معتبر نیست")
        available = await self.qbank.capacity(user=user, taxonomy=taxonomy, difficulty=difficulty)
        return {"requested_count": int(requested_count), "available_count": available,
                "can_start": available >= int(requested_count),
                "max_count": available, "minutes": int(minutes), "output_mode": output_mode,
                "taxonomy": dict(taxonomy)}

    async def create(self, *, user: Mapping, taxonomy: Mapping,
                     requested_count: int, minutes: int, output_mode: str,
                     difficulty: str | None = None,
                     allow_smaller: bool = False) -> dict:
        existing = await self.active(user=user)
        if existing and existing.get("status") == "active":
            raise QuestionDomainError("active_exam_exists", "ابتدا آزمون فعال را ادامه دهید یا رها کنید", 409,
                                      {"exam": existing})
        preview = await self.preview(user=user, taxonomy=taxonomy, requested_count=requested_count,
                                     minutes=minutes, output_mode=output_mode, difficulty=difficulty)
        if not preview["available_count"]:
            raise QuestionDomainError("no_questions", "برای این فیلتر سؤالی وجود ندارد", 404, preview)
        if not preview["can_start"] and not allow_smaller:
            raise QuestionDomainError("insufficient_questions", "تعداد سؤال‌های موجود کمتر از انتخاب شماست", 409, preview)
        actual = min(int(requested_count), preview["available_count"])
        query = self.qbank.eligible_query(taxonomy, intakes=self.qbank.student_intakes(user), difficulty=difficulty)
        rows = await self.db.questions.aggregate([
            {"$match": query}, {"$sample": {"size": actual}}, {"$project": {"_id": 1}},
        ]).to_list(actual)
        if len(rows) != actual:
            raise QuestionDomainError("capacity_changed", "ظرفیت بانک هم‌زمان تغییر کرد؛ دوباره تلاش کنید", 409)
        now = now_utc()
        session_id = uuid.uuid4().hex[:20]
        deadline = now + timedelta(minutes=int(minutes)) if minutes else None
        # 🌊 W3 — TTL field for auto-cleanup (7d after deadline or start) — Date for TTL
        from datetime import timedelta as _td
        expires_at = (deadline + _td(days=7) if deadline else now + _td(days=7))
        document = {
            "session_id": session_id, "user_id": int(user.get("id") or 0),
            "lesson_id": str(taxonomy.get("lesson_id") or ""),
            "topic_id": str(taxonomy.get("topic_id") or ""),
            "lesson": taxonomy.get("lesson", ""), "topic": taxonomy.get("topic", ""),
            "difficulty": difficulty or "", "question_ids": [str(x["_id"]) for x in rows],
            "requested_count": int(requested_count), "actual_count": actual,
            "minutes": int(minutes), "duration_seconds": int(minutes) * 60,
            "deadline": deadline.isoformat() if deadline else None,
            "deadline_ts": int(deadline.timestamp()) if deadline else None,
            "expires_at": expires_at,
            "index": 0, "current_index": 0, "correct": 0, "correct_count": 0,
            "answered": 0, "answers": [], "status": "active",
            "output_mode": output_mode, "started_at": now.isoformat(), "created_at": now.isoformat(),
            "finished_at": None, "exam_code": f"HYB-{now.strftime('%y%m%d')}-{session_id[-4:].upper()}",
            "generation": None,
        }
        await self.sessions.insert_one(document)
        return self.summary(document)

    async def load(self, session_id: str, user_id: int) -> dict:
        session = await self.sessions.find_one({"session_id": session_id, "user_id": int(user_id)})
        if not session:
            raise QuestionDomainError("exam_not_found", "آزمون پیدا نشد", 404)
        return await self.expire(session)

    async def expire(self, session: dict) -> dict:
        if session.get("status") != "active":
            return session
        deadline = session.get("deadline")
        expired = False
        if deadline:
            try: expired = now_utc() >= parse_machine_datetime(deadline)
            except Exception: expired = False
        elif session.get("deadline_ts"):
            expired = int(time.time()) >= int(session["deadline_ts"])
        if expired:
            now = utc_now_iso()
            result = await self.sessions.update_one(
                {"_id": session["_id"], "status": "active"},
                {"$set": {"status": "expired", "finished_at": now}})
            if result.modified_count:
                session.update({"status": "expired", "finished_at": now})
        return session

    async def next_question(self, *, session_id: str, user: Mapping) -> dict:
        session = await self.load(session_id, int(user.get("id") or 0))
        if session.get("status") != "active":
            return {"finished": True, **self.summary(session)}
        ids = list(session.get("question_ids") or [])
        index = int(session.get("current_index", session.get("index", 0)) or 0)
        while index < len(ids):
            question = await self.db.questions.find_one({"_id": ObjectId(ids[index])}) if ObjectId.is_valid(ids[index]) else None
            if question:
                try:
                    await self.qbank.verify_access(question, user)
                    seconds = None
                    if session.get("deadline"):
                        seconds = max(0, int((parse_machine_datetime(session["deadline"]) - now_utc()).total_seconds()))
                    return {"finished": False, "question": public_question(question),
                            "progress": index + 1, "total": len(ids), "seconds_left": seconds,
                            "session_id": session_id, "output_mode": session.get("output_mode", "app")}
                except QuestionDomainError:
                    pass
            index += 1
            await self.sessions.update_one({"_id": session["_id"]}, {"$set": {"index": index, "current_index": index}})
        now = utc_now_iso()
        await self.sessions.update_one({"_id": session["_id"], "status": "active"},
                                       {"$set": {"status": "finished", "finished_at": now,
                                                  "index": index, "current_index": index}})
        session.update({"status": "finished", "finished_at": now, "index": index, "current_index": index})
        return {"finished": True, **self.summary(session)}

    async def answer(self, *, session_id: str, user: Mapping, selected: int) -> dict:
        if not 0 <= int(selected) < 4:
            raise QuestionDomainError("invalid_answer", "گزینه انتخابی معتبر نیست")
        session = await self.load(session_id, int(user.get("id") or 0))
        if session.get("status") != "active":
            raise QuestionDomainError("exam_not_active", "زمان یا وضعیت آزمون فعال نیست", 409)
        ids = list(session.get("question_ids") or [])
        index = int(session.get("current_index", session.get("index", 0)) or 0)
        if index >= len(ids):
            raise QuestionDomainError("exam_finished", "آزمون تمام شده است", 409)
        question = await self.db.questions.find_one({"_id": ObjectId(ids[index])}) if ObjectId.is_valid(ids[index]) else None
        if not question:
            raise QuestionDomainError("question_not_found", "سؤال پیدا نشد", 404)
        await self.qbank.verify_access(question, user)
        correct_answer = int(question.get("correct_answer") or 0)
        is_correct = int(selected) == correct_answer
        now = utc_now_iso(); final = index + 1 >= len(ids)
        update = {"$inc": {"index": 1, "current_index": 1, "answered": 1,
                            "correct": 1 if is_correct else 0,
                            "correct_count": 1 if is_correct else 0},
                  "$push": {"answers": {"question_id": ids[index], "selected": int(selected),
                                            "correct_answer": correct_answer, "is_correct": is_correct,
                                            "answered_at": now}}}
        if final:
            update["$set"] = {"status": "finished", "finished_at": now}
        result = await self.sessions.update_one({"_id": session["_id"], "status": "active",
                                                 "$or": [{"current_index": index},
                                                          {"current_index": {"$exists": False}, "index": index}]}, update)
        if result.modified_count != 1:
            raise QuestionDomainError("answer_conflict", "این سؤال قبلاً پاسخ داده شده است", 409)
        await self.qbank.record_answer(user=user, question=question, selected=int(selected),
                                       is_correct=is_correct, mode="exam", session_id=session_id)
        response = {"accepted": True, "progress": index + 1, "total": len(ids),
                    "finished": final, "session_id": session_id}
        if final:
            response["result"] = {"answered": index + 1,
                                  "correct": int(session.get("correct_count", session.get("correct", 0)) or 0) + (1 if is_correct else 0),
                                  "percentage": round((int(session.get("correct_count", session.get("correct", 0)) or 0) + (1 if is_correct else 0)) * 100 / len(ids), 1)}
        return response

    async def abandon(self, *, session_id: str, user: Mapping) -> dict:
        now = utc_now_iso()
        result = await self.sessions.update_one({"session_id": session_id, "user_id": int(user.get("id") or 0),
                                                 "status": "active"},
                                                {"$set": {"status": "abandoned", "finished_at": now}})
        if not result.modified_count:
            raise QuestionDomainError("active_exam_not_found", "آزمون فعال پیدا نشد", 404)
        return {"ok": True, "session_id": session_id, "status": "abandoned"}

    async def history(self, *, user: Mapping, skip: int = 0, limit: int = 30) -> dict:
        query = {"user_id": int(user.get("id") or 0), "promotion": {"$ne": True}}
        total = await self.sessions.count_documents(query)
        docs = await self.sessions.find(query).sort("started_at", -1).skip(skip).limit(limit).to_list(limit)
        items = [self.summary(await self.expire(doc)) for doc in docs]
        return {"exams": items, "total": total, "skip": skip, "limit": limit}

    async def active(self, *, user: Mapping) -> dict | None:
        doc = await self.sessions.find_one({"user_id": int(user.get("id") or 0), "status": "active",
                                            "promotion": {"$ne": True}}, sort=[("started_at", -1)])
        return self.summary(await self.expire(doc)) if doc else None

    async def generate_pdf(self, *, session_id: str, user: Mapping, mode: str) -> tuple[bytes, dict]:
        if mode not in {"practice", "exam"}:
            raise QuestionDomainError("invalid_pdf_mode", "نوع PDF معتبر نیست")
        session = await self.load(session_id, int(user.get("id") or 0))
        configured_output = session.get("output_mode", "")
        if configured_output.startswith("pdf_") and configured_output != f"pdf_{mode}":
            raise QuestionDomainError("pdf_mode_mismatch", "نوع PDF با انتخاب ثبت‌شده آزمون یکسان نیست", 409)
        ids = list(session.get("question_ids") or [])
        oids = [ObjectId(x) for x in ids if ObjectId.is_valid(x)]
        docs = await self.db.questions.find({"_id": {"$in": oids}}).to_list(len(oids))
        by_id = {str(x["_id"]): x for x in docs}
        questions = []
        for question_id in ids:
            question = by_id.get(question_id)
            if not question:
                continue
            try:
                await self.qbank.verify_access(question, user)
                questions.append(question)
            except QuestionDomainError:
                continue
        if not questions:
            raise QuestionDomainError("no_questions", "سؤالی برای تولید PDF باقی نمانده است", 404)
        from qbank import generate_exam_pdf
        from qbank.query import ExamMeta
        db_user = user.get("_db") or user
        meta = ExamMeta(lesson=session.get("lesson", ""), topic=session.get("topic", ""),
                        difficulty=session.get("difficulty") or None,
                        student_name=self.db.display_name_of(db_user),
                        exam_code=session.get("exam_code") or session_id)
        # 🌊 W6/PERF-03 — کش + عدم‌بلاک event-loop (reportlab همگام است)
        _pdf_key_src = "|".join(
            sorted(f"{q.get('_id')}:{q.get('updated_at', '')}"
                   for q in questions))
        _pdf_key = hashlib.sha256(
            f"{session_id}:{mode}:{_pdf_key_src}".encode("utf-8")).hexdigest()
        _pdf_hit = _PDF_CACHE.get(_pdf_key)
        if _pdf_hit and _pdf_hit[0] > time.monotonic():
            return _pdf_hit[1], _pdf_hit[2]
        content = await asyncio.to_thread(
            generate_exam_pdf, questions, meta, mode=mode)
        generated_at = utc_now_iso(); generation_id = uuid.uuid4().hex
        checksum = hashlib.sha256(content).hexdigest()
        generation = {"generation_id": generation_id, "session_id": session_id,
                      "user_id": int(user.get("id") or 0), "mode": mode,
                      "generated_at": generated_at, "size": len(content),
                      "sha256": checksum, "exam_code": meta.exam_code,
                      "question_ids": [str(x.get("_id")) for x in questions],
                      "file_name": f"humsyar_exam_{meta.exam_code}.pdf",
                      "delivery": "stream", "status": "generated"}
        await self.db.question_pdf_generations.insert_one(dict(generation))
        session_set = {"generation": generation, "last_pdf_mode": f"pdf_{mode}"}
        # A PDF-configured session is a generated artifact, not an answerable Bot/App exam.
        if configured_output.startswith("pdf_"):
            session_set.update({"status": "finished", "finished_at": generated_at})
        await self.sessions.update_one(
            {"_id": session["_id"]},
            # 🛡 AUDIT-V3 — کرانه: فایل‌ها در question_pdf_generations می‌مانند؛
                # اینجا فقط ۱۰۰ اشاره‌گرِ آخر نگه داشته می‌شود.
                {"$set": session_set,
                 "$push": {"generation_ids": {"$each": [generation_id], "$slice": -100}}})
        _pdf_out = {"session_id": session_id, "generation_id": generation_id,
                      "exam_code": meta.exam_code, "mode": mode,
                      "questions": len(questions), "generated_at": generated_at,
                      "sha256": checksum, "file_name": generation["file_name"]}
        if len(_PDF_CACHE) >= _PDF_CACHE_MAX:
            _PDF_CACHE.pop(next(iter(_PDF_CACHE)))
        _PDF_CACHE[_pdf_key] = (time.monotonic() + _PDF_CACHE_TTL_S,
                                content, _pdf_out)
        return content, _pdf_out

    @staticmethod
    def summary(session: Mapping) -> dict:
        ids = list(session.get("question_ids") or [])
        answered = int(session.get("answered") or 0); correct = int(session.get("correct_count", session.get("correct", 0)) or 0)
        return {"session_id": str(session.get("session_id") or ""),
                "lesson_id": str(session.get("lesson_id") or ""), "topic_id": str(session.get("topic_id") or ""),
                "lesson": session.get("lesson", ""), "topic": session.get("topic", ""),
                "status": session.get("status", "active"), "output_mode": session.get("output_mode", "app"),
                "requested_count": int(session.get("requested_count", len(ids)) or len(ids)),
                "actual_count": int(session.get("actual_count", len(ids)) or len(ids)),
                "total": len(ids), "answered": answered, "correct": correct,
                "percentage": round(correct * 100 / answered, 1) if answered else 0,
                "current_index": int(session.get("current_index", session.get("index", 0)) or 0),
                "minutes": int(session.get("minutes") or 0), "deadline": session.get("deadline"),
                "started_at": session.get("started_at"), "finished_at": session.get("finished_at"),
                "exam_code": session.get("exam_code"), "generation": session.get("generation")}
