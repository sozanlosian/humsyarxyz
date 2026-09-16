"""Personal AI practice questions, isolated from the shared bank."""
from __future__ import annotations

from datetime import timedelta
from typing import Mapping
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from time_utils import day_bounds_utc, now_utc, utc_now_iso
from .contracts import QuestionDomainError, clean_text, public_question, validate_question_payload
from .service import QuestionBankService

PROMPT_VERSION = "qbank-personal-v1"


class AIPersonalPracticeService:
    def __init__(self, database):
        self.db = database
        self.qbank = QuestionBankService(database)

    async def quota(self, user_id: int) -> dict:
        daily = int(await self.db.get_setting("qbank_ai_daily_limit", 5) or 5)
        per_topic = int(await self.db.get_setting("qbank_ai_topic_daily_limit", 2) or 2)
        start, end = day_bounds_utc()
        query = {"user_id": int(user_id), "generated_at": {"$gte": start.isoformat(), "$lt": end.isoformat()}}
        used = await self.db.ai_practice_questions.count_documents(query)
        return {"daily_limit": daily, "used_today": used, "remaining_today": max(0, daily - used),
                "topic_daily_limit": per_topic, "range": query["generated_at"]}

    async def _reserve(self, *, user_id: int, topic_id: str,
                       daily_limit: int, topic_limit: int) -> list[str]:
        """Atomically reserve both daily and per-topic capacity."""
        start, end = day_bounds_utc()
        day = start.date().isoformat()
        keys = [(f"day:{user_id}:{day}", daily_limit, "daily"),
                (f"topic:{user_id}:{topic_id}:{day}", topic_limit, "topic")]
        reserved = []
        for key, limit, kind in keys:
            try:
                doc = await self.db.question_ai_quotas.find_one_and_update(
                    {"_id": key, "used": {"$lt": limit}},
                    {"$setOnInsert": {"user_id": user_id, "topic_id": topic_id if kind == "topic" else "",
                                      "day": day, "kind": kind, "created_at": now_utc(),
                                      "expires_at": end + timedelta(days=2)},
                     "$set": {"updated_at": now_utc(), "limit": limit}, "$inc": {"used": 1}},
                    upsert=True, return_document=ReturnDocument.AFTER)
            except DuplicateKeyError:
                doc = None
            if not doc:
                if reserved:
                    await self._release(reserved)
                code = "ai_daily_limit" if kind == "daily" else "ai_topic_limit"
                message = ("سهمیه روزانه سؤال هوشمند تمام شده است" if kind == "daily" else
                           "سهمیه امروز این مبحث تمام شده است")
                raise QuestionDomainError(code, message, 429)
            reserved.append(key)
        return reserved

    async def _release(self, reservation_keys: list[str]) -> None:
        for key in reservation_keys:
            await self.db.question_ai_quotas.update_one(
                {"_id": key, "used": {"$gt": 0}}, {"$inc": {"used": -1}})

    async def generate(self, *, user: Mapping, taxonomy: Mapping,
                       difficulty: str = "medium", note: str = "",
                       require_exhaustion: bool = True) -> dict:
        uid = int(user.get("id") or 0)
        if require_exhaustion:
            state = await self.qbank.practice_next(user=user, taxonomy=taxonomy, mode="free")
            if not state["progress"]["exhausted"]:
                raise QuestionDomainError("bank_not_exhausted", "هنوز سؤال معتبر حل‌نشده در بانک وجود دارد", 409,
                                          state["progress"])
        quota = await self.quota(uid)
        topic_id = str(taxonomy.get("topic_id") or "")
        reservations = await self._reserve(
            user_id=uid, topic_id=topic_id,
            daily_limit=quota["daily_limit"], topic_limit=quota["topic_daily_limit"])
        try:
            grounding_rows = await self.db.bs_content.find(
                {"session_id": topic_id}, {"description": 1, "name": 1}).limit(8).to_list(8)
            grounding = [clean_text(x.get("description") or x.get("name"), 300) for x in grounding_rows]
            if not any(grounding):
                bank_rows = await self.db.questions.find(
                    self.qbank.eligible_query(taxonomy, intakes=self.qbank.student_intakes(user)),
                    {"question": 1, "explanation": 1}).sort("created_at", -1).limit(8).to_list(8)
                grounding = [clean_text(
                    f"{x.get('question','')} — {x.get('explanation','')}", 500) for x in bank_rows]
            grounding = [x for x in grounding if x]
            if not grounding:
                raise QuestionDomainError("ai_grounding_unavailable",
                                          "برای ساخت سؤال هوشمند، منبع تأییدشده کافی برای این مبحث نداریم", 409)
            from ai_solver import generate_question_ai
            try:
                generated = await generate_question_ai(
                    lesson=taxonomy.get("lesson", ""), topic=taxonomy.get("topic", ""),
                    difficulty=difficulty, note=note, grounding=[x for x in grounding if x])
            except Exception as exc:
                raise QuestionDomainError(
                    "ai_generation_failed", "ساخت سؤال هوشمند انجام نشد؛ دوباره تلاش کنید", 502) from exc
            normalized = validate_question_payload({
                "question": generated.get("question"), "options": generated.get("options"),
                "correct_answer": generated.get("correct_index"),
                "explanation": generated.get("explanation"), "difficulty": difficulty,
            })
            if len(normalized.get("explanation") or "") < 20:
                raise QuestionDomainError("ai_quality_failed",
                                          "خروجی هوشمند تحلیل علمی کافی نداشت و ذخیره نشد", 502)
            duplicates = await self.qbank.duplicate_candidates(
                taxonomy=taxonomy, question=normalized["question"], content_hash=normalized["content_hash"],
                correct_answer=normalized["correct_answer"], intakes=self.qbank.student_intakes(user))
            quality = "duplicate_warning" if duplicates["exact"] or duplicates["probable"] or duplicates["conflict"] else "validated"
            now = utc_now_iso()
            document = {**normalized, **dict(taxonomy), "user_id": uid,
                        "generated_by": "gemini", "model": generated.get("model") or "configured-gemini",
                        "prompt_version": PROMPT_VERSION, "generated_at": now,
                        "source_context": grounding, "quality_status": quality,
                        "duplicate_summary": {"exact": len(duplicates["exact"]),
                                              "probable": len(duplicates["probable"]),
                                              "conflict": len(duplicates["conflict"])},
                        "status": "ready", "answered_at": None, "selected": None,
                        "is_correct": None, "proposed_question_id": None}
            result = await self.db.ai_practice_questions.insert_one(document)
        except Exception:
            await self._release(reservations)
            raise
        document["_id"] = result.inserted_id
        public = public_question(document)
        public.update({"ai_question_id": str(result.inserted_id), "provenance": {
            "generated_by": document["generated_by"], "model": document["model"],
            "prompt_version": PROMPT_VERSION, "generated_at": now,
            "quality_status": quality,
        }})
        return {"question": public, "quota": await self.quota(uid)}
    async def answer(self, *, user: Mapping, ai_question_id: str, selected: int) -> dict:
        if not ObjectId.is_valid(str(ai_question_id)) or not 0 <= int(selected) < 4:
            raise QuestionDomainError("invalid_ai_answer", "پاسخ سؤال هوشمند معتبر نیست")
        uid = int(user.get("id") or 0); now = utc_now_iso()
        document = await self.db.ai_practice_questions.find_one({"_id": ObjectId(str(ai_question_id)), "user_id": uid})
        if not document:
            raise QuestionDomainError("ai_question_not_found", "سؤال هوشمند پیدا نشد", 404)
        if document.get("answered_at"):
            raise QuestionDomainError("ai_question_answered", "این سؤال قبلاً پاسخ داده شده است", 409)
        correct = int(document.get("correct_answer") or 0); is_correct = int(selected) == correct
        result = await self.db.ai_practice_questions.update_one(
            {"_id": document["_id"], "user_id": uid, "answered_at": None},
            {"$set": {"selected": int(selected), "is_correct": is_correct,
                      "answered_at": now, "status": "answered"}})
        if result.modified_count != 1:
            raise QuestionDomainError("ai_answer_conflict", "پاسخ قبلاً ثبت شده است", 409)
        topic_key = str(document.get("topic_id") or document.get("topic") or "")
        if topic_key:
            await self.db.question_topic_stats.update_one(
                {"_id": f"{uid}:{topic_key}"},
                {"$setOnInsert": {"user_id": uid, "topic_key": topic_key,
                                   "lesson_id": document.get("lesson_id", ""), "topic_id": document.get("topic_id", ""),
                                   "lesson": document.get("lesson", ""), "topic": document.get("topic", "")},
                 "$set": {"updated_at": now},
                 "$inc": {"ai_attempts": 1, "ai_correct": 1 if is_correct else 0}}, upsert=True)
        return {"is_correct": is_correct, "correct_answer": correct,
                "explanation": document.get("explanation", ""),
                "can_propose": not bool(document.get("proposed_question_id"))}

    async def propose(self, *, user: Mapping, ai_question_id: str) -> dict:
        if not ObjectId.is_valid(str(ai_question_id)):
            raise QuestionDomainError("invalid_ai_question", "شناسه سؤال هوشمند معتبر نیست")
        uid = int(user.get("id") or 0)
        document = await self.db.ai_practice_questions.find_one({"_id": ObjectId(str(ai_question_id)),
                                                                 "user_id": uid, "answered_at": {"$ne": None}})
        if not document:
            raise QuestionDomainError("ai_question_not_answered", "ابتدا سؤال را پاسخ دهید", 409)
        if document.get("proposed_question_id"):
            return {"question_id": document["proposed_question_id"], "already_proposed": True}
        result = await self.qbank.create_question(
            actor=user, payload=document, source="ai_student", creator_type="ai",
            auto_approve=False, intake=clean_text((user.get("_db") or user).get("intake")),
            allow_probable_duplicate=False)
        qid = str(result["question"]["_id"])
        await self.db.ai_practice_questions.update_one({"_id": document["_id"], "proposed_question_id": None},
                                                       {"$set": {"proposed_question_id": qid, "proposed_at": utc_now_iso()}})
        return {"question_id": qid, "already_proposed": False, "status": "pending"}
