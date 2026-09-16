"""Shared Question Bank service: taxonomy, lifecycle, practice and attempts."""
from __future__ import annotations

import difflib
import logging
import os
from datetime import timedelta
from html import escape as html_escape
from typing import Any, Mapping

from bson import ObjectId
from pymongo import ReturnDocument

from time_utils import day_bounds_utc, now_utc, utc_now_iso
from .contracts import (
    DIFFICULTY_LABELS, QUESTION_STATUSES, QuestionDomainError, and_query,
    approved_query, canonical_difficulty, canonical_source, canonical_status,
    clean_text, normalized_question_text, public_question, status_query,
    validate_question_payload,
)
from .permissions import QuestionPermissionService

logger = logging.getLogger(__name__)


def _direct_reason(creator_type: str) -> str:
    """متنِ دلیل برای ثبتِ مستقیم — منبعِ اعتماد را صریح می‌کند.

    در سابقه‌ی بازبینی باید بشود فهمید چرا سؤالی بدونِ بازبینِ دوم
    «تأییدشده» شده است.
    """
    if creator_type == "system":
        return "ثبت مستقیم توسط سیستم"
    return "ثبت مستقیم توسط ادمین محتوا (دارای مجوز بررسی)"


class QuestionBankService:
    def __init__(self, database):
        self.db = database
        self.permissions = QuestionPermissionService(database)

    @staticmethod
    def student_intakes(user: Mapping) -> list[str]:
        db_user = user.get("_db") if isinstance(user.get("_db"), Mapping) else user
        intake = clean_text((db_user or {}).get("intake"))
        return list(dict.fromkeys([intake, ""])) if intake else [""]

    async def resolve_taxonomy(
        self, *, lesson_id: str | None = None, topic_id: str | None = None,
        lesson: str | None = None, topic: str | None = None,
        visible_intakes: list[str] | None = None, require_topic: bool = True,
    ) -> dict:
        intake_filter = {} if visible_intakes is None else {"intake": {"$in": visible_intakes}}
        lesson_doc = None
        if lesson_id and ObjectId.is_valid(str(lesson_id)):
            lesson_doc = await self.db.bs_lessons.find_one({"_id": ObjectId(str(lesson_id)), **intake_filter})
        if not lesson_doc and clean_text(lesson):
            candidates = await self.db.bs_lessons.find({"name": clean_text(lesson), **intake_filter}).sort("intake", -1).limit(10).to_list(10)
            if len(candidates) == 1:
                lesson_doc = candidates[0]
            elif len(candidates) > 1:
                own = [x for x in candidates if x.get("intake") and x.get("intake") in (visible_intakes or [])]
                lesson_doc = own[0] if len(own) == 1 else None
                if not lesson_doc:
                    raise QuestionDomainError("ambiguous_lesson", "درس انتخاب‌شده مبهم است", 409,
                                              {"matches": [{"id": str(x["_id"]), "name": x.get("name"), "intake": x.get("intake", "")} for x in candidates]})
        if not lesson_doc:
            raise QuestionDomainError("lesson_not_found", "درس در taxonomy معتبر پیدا نشد", 422)

        topic_doc = None
        lesson_key = str(lesson_doc["_id"])
        if topic_id and ObjectId.is_valid(str(topic_id)):
            topic_doc = await self.db.bs_sessions.find_one({"_id": ObjectId(str(topic_id)), "lesson_id": lesson_key})
        if not topic_doc and clean_text(topic):
            candidates = await self.db.bs_sessions.find({"lesson_id": lesson_key, "topic": clean_text(topic)}).limit(10).to_list(10)
            if len(candidates) == 1:
                topic_doc = candidates[0]
            elif len(candidates) > 1:
                raise QuestionDomainError("ambiguous_topic", "مبحث انتخاب‌شده مبهم است", 409,
                                          {"matches": [{"id": str(x["_id"]), "name": x.get("topic")} for x in candidates]})
        if require_topic and not topic_doc:
            raise QuestionDomainError("topic_not_found", "مبحث در taxonomy معتبر پیدا نشد", 422)
        return {
            "lesson_id": lesson_key,
            "topic_id": str(topic_doc["_id"]) if topic_doc else "",
            "lesson": clean_text(lesson_doc.get("name")),
            "topic": clean_text((topic_doc or {}).get("topic")),
            "term": clean_text(lesson_doc.get("term")),
            "intake": clean_text(lesson_doc.get("intake")),
        }

    async def taxonomy_tree(self, *, visible_intakes: list[str] | None = None,
                            only_with_questions: bool = False) -> list[dict]:
        query = {} if visible_intakes is None else {"intake": {"$in": visible_intakes}}
        lessons = await self.db.bs_lessons.find(query).sort([("term", 1), ("order", 1)]).to_list(1000)
        if not lessons:
            return []
        lesson_ids = [str(x["_id"]) for x in lessons]
        sessions = await self.db.bs_sessions.find({"lesson_id": {"$in": lesson_ids}}).sort("number", 1).to_list(5000)
        counts = {}
        pipeline = [
            {"$match": and_query(approved_query(), {"intake": {"$in": visible_intakes}} if visible_intakes is not None else {})},
            {"$group": {"_id": {"lesson_id": "$lesson_id", "topic_id": "$topic_id"}, "count": {"$sum": 1}}},
        ]
        try:
            for row in await self.db.questions.aggregate(pipeline).to_list(10000):
                key = row.get("_id") or {}
                counts[(str(key.get("lesson_id") or ""), str(key.get("topic_id") or ""))] = int(row.get("count") or 0)
        except Exception:
            logger.exception("question taxonomy counts failed")
            counts = {}
        by_lesson = {}
        for session in sessions:
            lid = str(session.get("lesson_id") or "")
            count = counts.get((lid, str(session.get("_id"))), 0)
            by_lesson.setdefault(lid, []).append({
                "id": str(session.get("_id")), "name": clean_text(session.get("topic")),
                "number": session.get("number"), "question_count": count,
            })
        result = []
        for item in lessons:
            lid = str(item["_id"])
            topics = by_lesson.get(lid, [])
            total = sum(x["question_count"] for x in topics)
            if only_with_questions and not total:
                continue
            result.append({"id": lid, "name": clean_text(item.get("name")),
                           "term": clean_text(item.get("term")), "intake": clean_text(item.get("intake")),
                           "question_count": total, "topics": topics})
        return result

    def taxonomy_scope_query(self, taxonomy: Mapping, *, intakes: list[str] | None) -> dict:
        parts = []
        if taxonomy.get("lesson_id") or taxonomy.get("lesson"):
            parts.append({"$or": [
                {"lesson_id": str(taxonomy.get("lesson_id") or ""),
                 **({"topic_id": str(taxonomy.get("topic_id"))} if taxonomy.get("topic_id") else {})},
                {"lesson_id": {"$exists": False}, "lesson": taxonomy.get("lesson"),
                 **({"topic": taxonomy.get("topic")} if taxonomy.get("topic") else {})},
            ]})
        if intakes is not None:
            parts.append({"intake": {"$in": intakes}})
        return and_query(*parts)

    def eligible_query(self, taxonomy: Mapping, *, intakes: list[str] | None,
                       difficulty: str | None = None) -> dict:
        parts = [approved_query(), self.taxonomy_scope_query(taxonomy, intakes=intakes)]
        if difficulty:
            canonical = canonical_difficulty(difficulty)
            legacy = DIFFICULTY_LABELS[canonical]
            parts.append({"difficulty": {"$in": [canonical, legacy]}})
        return and_query(*parts)

    #  §W8 — سقفِ کرانه‌دار برای `$nin`.
    #
    #  آرایه‌ی بی‌کران در `$nin` هم کوئری را کند می‌کند و هم به سقفِ ۱۶
    #  مگابایتیِ سند می‌خورد. در عمل یک دانشجو ده‌ها گزارش می‌دهد نه
    #  ده‌ها هزار؛ این سقف محافظِ سناریوی سوءاستفاده است.
    REPORT_EXCLUSION_CAP = 500

    async def reported_question_ids(self, user_id: int) -> list:
        """شناسه‌ی سؤال‌هایی که این کاربر گزارشِ باز روی‌شان دارد."""
        if not user_id:
            return []
        try:
            rows = await self.db.content_reports.find(
                {"reporter_id": int(user_id), "target_type": "question",
                 "status": {"$in": ["new", "reviewing"]}},
                {"target_id": 1},
            ).limit(self.REPORT_EXCLUSION_CAP).to_list(self.REPORT_EXCLUSION_CAP)
        except Exception:
            logger.exception("reported question lookup failed user_id=%s", user_id)
            return []
        out = []
        for row in rows:
            raw = str(row.get("target_id") or "")
            if ObjectId.is_valid(raw):
                out.append(ObjectId(raw))
        return out

    async def duplicate_candidates(self, *, taxonomy: Mapping, question: str,
                                   content_hash: str, intakes: list[str] | None,
                                   correct_answer: int | None = None,
                                   limit: int = 5,
                                   exclude_question_id: str | None = None) -> dict:
        base = and_query(self.taxonomy_scope_query(taxonomy, intakes=intakes),
                         {"status": {"$ne": "rejected"}})
        if exclude_question_id and ObjectId.is_valid(str(exclude_question_id)):
            base = and_query(base, {"_id": {"$ne": ObjectId(str(exclude_question_id))}})
        exact = await self.db.questions.find_one(and_query(base, {"content_hash": content_hash}))
        if exact:
            item = {"id": str(exact["_id"]), "question": exact.get("question", ""), "ratio": 1.0,
                    "correct_answer": exact.get("correct_answer")}
            if correct_answer is not None and int(exact.get("correct_answer", -1)) != int(correct_answer):
                return {"exact": [], "probable": [], "conflict": [item]}
            return {"exact": [item], "probable": [], "conflict": []}
        docs = await self.db.questions.find(base, {"question": 1}).sort("created_at", -1).limit(80).to_list(80)
        target = normalized_question_text(question)
        probable = []
        for doc in docs:
            ratio = difflib.SequenceMatcher(None, target, normalized_question_text(doc.get("question"))).ratio()
            if ratio >= 0.82:
                probable.append({"id": str(doc["_id"]), "question": doc.get("question", ""), "ratio": round(ratio, 3)})
        probable.sort(key=lambda x: x["ratio"], reverse=True)
        return {"exact": [], "probable": probable[:limit], "conflict": []}

    async def create_question(self, *, actor: Mapping, payload: Mapping,
                              source: str, creator_type: str,
                              auto_approve: bool = False,
                              intake: str | None = None,
                              allow_probable_duplicate: bool = False) -> dict:
        normalized = validate_question_payload(payload)
        # 🐛 §W6-1 — «ثبت مستقیمِ ادمینِ محتوا».
        #
        # پیش‌تر فقط `creator_type == "system"` اجازه‌ی auto_approve داشت، پس
        # سؤالی که ادمینِ محتوا می‌ساخت هم `pending` می‌شد. چون قانونِ
        # ضدِ خودتأییدی (`self_approval_forbidden`) هم اجازه نمی‌دهد سازنده
        # سؤالِ خودش را تأیید کند، سؤال در صف گیر می‌کرد مگر بازبینِ دومی
        # وجود داشته باشد — در عمل روی نصبِ تک‌ادمینه یعنی «هرگز».
        #
        # حالا `creator_type == "admin"` هم مجاز است، ولی این اعتماد
        # *ادعاییِ فراخوان* نیست: پایین‌تر با `questions.review` روی خودِ
        # دیتابیس راستی‌آزمایی می‌شود. یعنی فراخوانی که صرفاً
        # `creator_type="admin"` بفرستد چیزی به دست نمی‌آورد.
        if auto_approve and creator_type not in ("system", "admin"):
            raise QuestionDomainError("self_approval_forbidden",
                                      "سؤال ساخته‌شده توسط همان کاربر باید توسط بازبین دیگری تأیید شود", 409)
        if auto_approve and creator_type == "admin":
            # مرجعِ اعتماد فقط RBAC است، نه ورودیِ فراخوان.
            if not await self.db.has_permission(int(actor.get("id") or 0), "questions.review"):
                raise QuestionDomainError(
                    "question_permission_denied",
                    "ثبتِ مستقیم نیازمند مجوز بررسی سؤال است", 403,
                    {"required": "questions.review"})
        actor_scope = actor.get("_scope") if isinstance(actor.get("_scope"), Mapping) else {}
        if actor.get("is_owner") or actor_scope.get("kind") == "global":
            visible = None
        elif actor_scope.get("kind") == "scoped":
            visible = [clean_text(actor_scope.get("intake")), ""]
        else:
            visible = self.student_intakes(actor)
        taxonomy = await self.resolve_taxonomy(
            lesson_id=payload.get("lesson_id"), topic_id=payload.get("topic_id"),
            lesson=payload.get("lesson"), topic=payload.get("topic"),
            visible_intakes=visible,
        )
        final_intake = clean_text(intake if intake is not None else taxonomy.get("intake"))
        if actor_scope.get("kind") == "scoped" and final_intake != clean_text(actor_scope.get("intake")):
            raise QuestionDomainError("question_out_of_scope", "سؤال خارج از محدوده شماست", 403)
        if creator_type == "student":
            final_intake = clean_text((actor.get("_db") or actor).get("intake"))
        duplicates = await self.duplicate_candidates(
            taxonomy=taxonomy, question=normalized["question"], content_hash=normalized["content_hash"],
            correct_answer=normalized["correct_answer"],
            intakes=[final_intake, ""] if final_intake else [""],
        )
        if duplicates["conflict"]:
            raise QuestionDomainError("answer_conflict_duplicate", "سؤال مشابه با پاسخ صحیح متفاوت در بانک وجود دارد", 409, duplicates)
        if duplicates["exact"]:
            raise QuestionDomainError("exact_duplicate", "این سؤال قبلاً در بانک ثبت شده است", 409, duplicates)
        if duplicates["probable"] and not allow_probable_duplicate:
            raise QuestionDomainError("probable_duplicate", "سؤال مشابهی در بانک وجود دارد", 409, duplicates)
        now = utc_now_iso()
        status = "approved" if auto_approve else "pending"
        db_user = actor.get("_db") if isinstance(actor.get("_db"), Mapping) else actor
        document = {
            **normalized, **taxonomy,
            "creator_id": int(actor.get("id") or actor.get("user_id") or 0),
            "creator_name": self.db.display_name_of(db_user) if db_user else "",
            "creator_type": creator_type,
            "source": canonical_source(source, creator_type),
            "provenance": {
                "source": canonical_source(source, creator_type),
                "creator_type": creator_type,
                "created_by": int(actor.get("id") or actor.get("user_id") or 0),
                **({"ai": {"generated_by": clean_text(payload.get("generated_by")),
                            "model": clean_text(payload.get("model")),
                            "prompt_version": clean_text(payload.get("prompt_version")),
                            "generated_at": payload.get("generated_at"),
                            "personal_question_id": str(payload.get("_id") or "")}}
                   if canonical_source(source, creator_type) == "ai_student" else {}),
            },
            "intake": final_intake,
            "status": status, "approved": status == "approved",
            "created_at": now, "updated_at": now, "version": 1,
            "reviewed_by": int(actor.get("id") or 0) if auto_approve else None,
            "reviewed_at": now if auto_approve else None,
            "review_reason": _direct_reason(creator_type) if auto_approve else "",
            "review_history": ([{"from": None, "to": "approved", "by": int(actor.get("id") or 0), "at": now,
                                 "reason": _direct_reason(creator_type)}] if auto_approve else []),
            "attempt_count": 0, "correct_count": 0,
        }
        result = await self.db.questions.insert_one(document)
        document["_id"] = result.inserted_id
        if not auto_approve:
            await self.notify_review_queue(document)
        return {"question": document, "duplicates": duplicates}

    # 🛡 AUDIT-V3 — تاریخچه‌ی بازبینی روی سند سؤال کرانه دارد (هر گذار ~۱۲۰
    # بایت؛ رکوردِ دائمی در audit_logs باقی می‌ماند، پس این کرانه فقط
    # پیش‌گیری از سقف ۱۶ مگابایتِ Mongo است، نه حذف سابقه).
    REVIEW_HISTORY_CAP = 200

    @staticmethod
    def _capped(item, cap: int) -> dict:
        """$push با کرانه — تنها شکل مجاز `$slice` (همراه `$each`)."""
        return {"$each": [item], "$slice": -int(cap)}

    async def notify_review_queue(self, question: Mapping) -> None:
        """Enqueue only authorized reviewers using bulk role/scope resolution."""
        admin_id = int(os.getenv("ADMIN_ID", "0")); creator = int(question.get("creator_id") or 0)
        question_intake = clean_text(question.get("intake"))
        authorized = {admin_id} if admin_id and admin_id != creator else set()
        try:
            legacy = await self.db.admin_roles.find(
                {"role": {"$in": ["reviewer", "bot_admin", "content_admin", "content_scoped"]}}
            ).to_list(500)
            for assignment in legacy:
                uid = int(assignment["_id"]); role = assignment.get("role")
                if uid == creator:
                    continue
                if role != "content_scoped" or clean_text(assignment.get("scope_intake")) == question_intake:
                    authorized.add(uid)

            role_docs = await self.db.roles.find(
                {"perms": {"$in": ["questions.review", "questions.review_scoped"]},
                 "active": {"$ne": False}}).to_list(200)
            roles = {str(role.get("_id")): set(role.get("perms") or []) for role in role_docs}
            if roles:
                assignments = await self.db.user_roles.find({"roles": {"$in": list(roles)}}).to_list(2000)
                for assignment in assignments:
                    uid = int(assignment["_id"])
                    if uid == creator:
                        continue
                    perms = set().union(*(roles.get(str(key), set()) for key in assignment.get("roles") or []))
                    if "questions.review" in perms:
                        authorized.add(uid)
                    elif ("questions.review_scoped" in perms and
                          clean_text(assignment.get("scope_intake")) == question_intake):
                        authorized.add(uid)
        except Exception:
            logger.exception("question review recipient resolution failed question_id=%s", question.get("_id"))
        now = utc_now_iso()
        docs = [{"type": "question_review", "chat_id": uid,
                 "text": (f"🔔 <b>سؤال جدید برای بررسی</b>\n📚 {html_escape(str(question.get('lesson','')))} — "
                          f"{html_escape(str(question.get('topic','')))}\n✏️ "
                          f"{html_escape(str(question.get('creator_name','')))}"),
                 "sent": False, "created_at": now,
                 "question_id": str(question.get("_id") or ""), "intake": question_intake}
                for uid in sorted(authorized)]
        if docs:
            try:
                await self.db.bot_notifs.insert_many(docs)
            except Exception:
                logger.exception("question review notification enqueue failed question_id=%s", question.get("_id"))

    async def transition(self, *, question_id: str, reviewer: Mapping,
                         target: str, reason: str = "") -> dict:
        if target not in QUESTION_STATUSES - {"pending"}:
            raise QuestionDomainError("invalid_transition", "وضعیت مقصد معتبر نیست")
        if not ObjectId.is_valid(str(question_id)):
            raise QuestionDomainError("invalid_question_id", "شناسه سؤال معتبر نیست")
        document = await self.db.questions.find_one({"_id": ObjectId(str(question_id))})
        if not document:
            raise QuestionDomainError("question_not_found", "سؤال پیدا نشد", 404)
        current = canonical_status(document)
        # 🐛 §W6-3 — نگاشتِ وضعیتِ مقصد به نامِ اکشنِ مجوز.
        #
        # پیش‌تر فقط "approved" نگاشت می‌شد و بقیه خامْ عبور می‌کردند، پس
        # `target="rejected"` به اکشنِ «rejected» تبدیل می‌شد در حالی که
        # کلیدِ مجاز «reject» است ⇒ هر «رد با دلیل» با
        # `invalid_review_action` شکست می‌خورد. مسیرِ واقعیِ ربات
        # (`_h_ca_q_del`) دقیقاً همین را می‌فرستد، یعنی دکمه در تولید مرده بود.
        _ACTION_OF_TARGET = {"approved": "approve", "rejected": "reject",
                             "needs_changes": "needs_changes"}
        action = _ACTION_OF_TARGET.get(target, target)
        await self.permissions.authorize_review(actor=reviewer, question=document, action=action)
        if current == target:
            return document
        reason = clean_text(reason, 1000)
        if target in {"rejected", "needs_changes"} and len(reason) < 3:
            raise QuestionDomainError("review_reason_required", "دلیل بررسی الزامی است")
        if current == "approved" and target != "rejected":
            raise QuestionDomainError("approved_question_locked", "سؤال تأییدشده قفل است", 409)
        if current in {"rejected", "needs_changes"}:
            raise QuestionDomainError("resubmit_required", "ابتدا طراح باید سؤال را اصلاح و دوباره ارسال کند", 409)
        now = utc_now_iso()
        rid = int(reviewer.get("id") or reviewer.get("user_id") or 0)
        update = {
            "status": target, "approved": target == "approved",
            "reviewed_by": rid, "reviewed_at": now, "review_reason": reason,
            "updated_at": now,
        }
        if target == "rejected":
            update["rejected_at"] = now
        result = await self.db.questions.find_one_and_update(
            {"_id": document["_id"], "$or": [{"status": current}, {"status": {"$exists": False}}]},
            {"$set": update, "$inc": {"version": 1},
             "$push": {"review_history": self._capped(
                 {"from": current, "to": target, "by": rid, "at": now, "reason": reason},
                 self.REVIEW_HISTORY_CAP)}},
            return_document=ReturnDocument.AFTER,
        )
        if not result:
            raise QuestionDomainError("concurrent_review", "وضعیت سؤال هم‌زمان تغییر کرده است", 409)
        await self._notify_creator(result, target, reason)
        if target == "approved" and current != "approved":
            try:
                creator = int(result.get("creator_id") or 0)
                if creator and result.get("creator_type") == "student":
                    await self.db.prestige_event(creator, "question_approved", {"qid": str(result["_id"])})
            except Exception:
                logger.exception("question approval prestige event failed question_id=%s", result.get("_id"))
        return result

    async def _notify_creator(self, question: Mapping, status: str, reason: str) -> None:
        creator = int(question.get("creator_id") or 0)
        if not creator:
            return
        labels = {"approved": ("✅ سؤالت تأیید شد", "سؤال به بانک مشترک اضافه شد."),
                  "rejected": ("❌ سؤالت رد شد", reason),
                  "needs_changes": ("✏️ سؤالت نیازمند اصلاح است", reason)}
        if status not in labels:
            return
        title, body = labels[status]
        try:
            await self.db.notify_user(creator, f"question_{status}", title=title, body=body,
                                      link=f"/learn/my-questions?hl={question.get('_id')}",
                                      dm=f"<b>{html_escape(title)}</b>\n\n{html_escape(str(body or ''))}")
        except Exception:
            logger.exception("question creator notification failed question_id=%s status=%s",
                             question.get("_id"), status)

    #  🐛 §W7 — ویرایشِ بازبین در هر وضعیت، با سیاستِ «بازبینیِ مجدد».
    #
    #  فیلدهایی که تغییرشان معنای علمیِ سؤال را عوض می‌کند. تغییر این‌ها
    #  روی سؤالِ تأییدشده باید دوباره بازبینی شود، وگرنه محتوای
    #  بازبینی‌نشده بی‌صدا در بانکِ عمومی می‌ماند (§۱۴).
    SUBSTANTIVE_FIELDS = ("question", "options", "correct_answer",
                          "lesson_id", "topic_id")

    async def edit_pending(self, *, question_id: str, reviewer: Mapping,
                           payload: Mapping, allow_probable_duplicate: bool = False) -> dict:
        """ویرایشِ بازبین — با اعتبارسنجی، scope، نسخه و تاریخچه.

        پیش‌تر فقط سؤالِ `pending` قابلِ ویرایش بود، پس سؤالِ تأییدشده در
        بن‌بست می‌ماند: نه ویرایش می‌شد، نه حذف (قفلِ approved) و در UI هم
        هیچ دکمه‌ای نداشت. حالا هر وضعیتی قابلِ ویرایش است، اما امنیت
        تضعیف نشده:

        • تغییرِ محتواییِ سؤالِ تأییدشده  → به `pending` برمی‌گردد و از
          بانکِ عمومی خارج می‌شود تا دوباره تأیید شود.
        • تغییرِ جزئی (سختی/توضیح)        → وضعیت دست‌نخورده می‌ماند.
        """
        if not ObjectId.is_valid(str(question_id)):
            raise QuestionDomainError("invalid_question_id", "شناسه سؤال معتبر نیست")
        existing = await self.db.questions.find_one({"_id": ObjectId(str(question_id))})
        if not existing:
            raise QuestionDomainError("question_not_found", "سؤال پیدا نشد", 404)
        await self.permissions.authorize_review(actor=reviewer, question=existing, action="edit")
        status = canonical_status(existing)
        merged = {
            "question": payload.get("question", existing.get("question")),
            "options": payload.get("options", existing.get("options")),
            "correct_answer": payload.get("correct_answer", payload.get("correct", existing.get("correct_answer"))),
            "difficulty": payload.get("difficulty", existing.get("difficulty")),
            "explanation": payload.get("explanation", existing.get("explanation")),
        }
        normalized = validate_question_payload(merged)
        taxonomy = await self.resolve_taxonomy(
            lesson_id=payload.get("lesson_id", existing.get("lesson_id")),
            topic_id=payload.get("topic_id", existing.get("topic_id")),
            lesson=payload.get("lesson", existing.get("lesson")),
            topic=payload.get("topic", existing.get("topic")),
            visible_intakes=None if self.permissions.is_owner(reviewer) else [clean_text(existing.get("intake")), ""],
        )
        taxonomy = {**taxonomy, "intake": clean_text(existing.get("intake"))}
        duplicates = await self.duplicate_candidates(
            taxonomy=taxonomy, question=normalized["question"], content_hash=normalized["content_hash"],
            correct_answer=normalized["correct_answer"],
            intakes=[clean_text(existing.get("intake")), ""], exclude_question_id=question_id)
        if duplicates["conflict"]:
            raise QuestionDomainError("answer_conflict_duplicate", "سؤال مشابه با پاسخ صحیح متفاوت در بانک وجود دارد", 409, duplicates)
        if duplicates["exact"]:
            raise QuestionDomainError("exact_duplicate", "این سؤال قبلاً در بانک ثبت شده است", 409, duplicates)
        if duplicates["probable"] and not allow_probable_duplicate:
            raise QuestionDomainError("probable_duplicate", "سؤال مشابهی در بانک وجود دارد", 409, duplicates)
        # آیا تغییر «محتوایی» است؟ مقایسه با مقادیرِ ذخیره‌شده، نه با
        # چیزی که کلاینت ادعا کرده فرستاده است.
        substantive = False
        for field in self.SUBSTANTIVE_FIELDS:
            before = existing.get(field)
            after = normalized.get(field, taxonomy.get(field, before))
            if field == "options":
                before = [clean_text(x) for x in (before or [])]
                after = [clean_text(x) for x in (after or [])]
            if field in ("lesson_id", "topic_id"):
                before, after = str(before or ""), str(after or "")
            if before != after:
                substantive = True
                break

        # §۱۴ — تغییرِ محتواییِ سؤالِ تأییدشده باید دوباره بازبینی شود.
        # تغییرِ جزئی (سختی/توضیح) وضعیت را دست نمی‌زند.
        demote = substantive and status == "approved"
        target = "pending" if demote else status

        now = utc_now_iso(); rid = int(reviewer.get("id") or reviewer.get("user_id") or 0)
        update = {**normalized, **taxonomy, "updated_at": now}
        if demote:
            update.update({"status": "pending", "approved": False,
                           "reviewed_by": None, "reviewed_at": None,
                           "review_reason": "ویرایشِ محتوایی — نیازمند تأیید مجدد"})
        reason = ("ویرایشِ محتوایی توسط بازبین — بازگشت به صف بررسی" if demote
                  else "ویرایش توسط بازبین")
        result = await self.db.questions.find_one_and_update(
            # قفلِ خوش‌بینانه روی نسخه: اگر سؤال بینِ خواندن و نوشتن عوض
            # شده باشد، ویرایشِ کهنه اعمال نمی‌شود (§۲۴).
            {"_id": existing["_id"], "version": int(existing.get("version") or 1)},
            {"$set": update, "$inc": {"version": 1},
             "$push": {"review_history": self._capped(
                 {"from": status, "to": target, "by": rid,
                  "at": now, "reason": reason, "action": "edit"},
                 self.REVIEW_HISTORY_CAP)}},
            return_document=ReturnDocument.AFTER,
        )
        if not result:
            raise QuestionDomainError("edit_conflict", "سؤال هم‌زمان تغییر کرده است", 409)
        return result

    async def update_contribution(self, *, question_id: str, user: Mapping,
                                  payload: Mapping, resubmit: bool = False) -> dict:
        if not ObjectId.is_valid(str(question_id)):
            raise QuestionDomainError("invalid_question_id", "شناسه سؤال معتبر نیست")
        existing = await self.db.questions.find_one({"_id": ObjectId(str(question_id)),
                                                     "creator_id": int(user.get("id") or 0)})
        if not existing:
            raise QuestionDomainError("question_not_found", "سؤال پیدا نشد", 404)
        status = canonical_status(existing)
        if status == "approved":
            raise QuestionDomainError("approved_question_locked", "سؤال تأییدشده قابل ویرایش نیست", 409)
        if status not in {"rejected", "needs_changes"}:
            raise QuestionDomainError("question_not_editable", "فقط سؤال ردشده یا نیازمند اصلاح قابل ویرایش است", 409)
        if not resubmit:
            raise QuestionDomainError("resubmit_required", "اصلاح باید همراه با ارسال مجدد به صف بررسی باشد", 409)
        normalized = validate_question_payload(payload)
        taxonomy = await self.resolve_taxonomy(
            lesson_id=payload.get("lesson_id"), topic_id=payload.get("topic_id"),
            lesson=payload.get("lesson"), topic=payload.get("topic"),
            visible_intakes=self.student_intakes(user),
        )
        taxonomy = {**taxonomy, "intake": clean_text(existing.get("intake"))}
        duplicates = await self.duplicate_candidates(
            taxonomy=taxonomy, question=normalized["question"], content_hash=normalized["content_hash"],
            correct_answer=normalized["correct_answer"],
            intakes=[clean_text(existing.get("intake")), ""], exclude_question_id=question_id)
        if duplicates["conflict"]:
            raise QuestionDomainError("answer_conflict_duplicate", "سؤال مشابه با پاسخ صحیح متفاوت در بانک وجود دارد", 409, duplicates)
        if duplicates["exact"]:
            raise QuestionDomainError("exact_duplicate", "این سؤال قبلاً در بانک ثبت شده است", 409, duplicates)
        if duplicates["probable"]:
            raise QuestionDomainError("probable_duplicate", "سؤال مشابهی در بانک وجود دارد", 409, duplicates)
        now = utc_now_iso()
        update = {**normalized, **taxonomy, "updated_at": now}
        if resubmit:
            update.update({"status": "pending", "approved": False, "review_reason": "",
                           "reviewed_by": None, "reviewed_at": None})
        await self.db.questions.update_one(
            {"_id": existing["_id"], "creator_id": int(user.get("id") or 0)},
            {"$set": update, "$inc": {"version": 1},
             **({"$push": {"review_history": self._capped(
                   {"from": status, "to": "pending", "by": int(user.get("id") or 0),
                    "at": now, "reason": "ارسال مجدد"}, self.REVIEW_HISTORY_CAP)}} if resubmit else {})},
        )
        current = await self.db.questions.find_one({"_id": existing["_id"]})
        if resubmit:
            await self.notify_review_queue(current)
        return current

    async def withdraw_contribution(self, *, question_id: str, user: Mapping) -> dict:
        """Non-destructive replacement for the legacy student DELETE endpoint."""
        if not ObjectId.is_valid(str(question_id)):
            raise QuestionDomainError("invalid_question_id", "شناسه سؤال معتبر نیست")
        uid = int(user.get("id") or user.get("user_id") or 0)
        document = await self.db.questions.find_one({"_id": ObjectId(str(question_id)), "creator_id": uid})
        if not document:
            raise QuestionDomainError("question_not_found", "سؤال پیدا نشد", 404)
        current = canonical_status(document)
        if current == "approved":
            raise QuestionDomainError("approved_question_locked", "سؤال تأییدشده قابل حذف یا برداشت نیست", 409)
        if current == "rejected" and document.get("withdrawn_by_creator"):
            return document
        now = utc_now_iso(); reason = "برداشت توسط طراح"
        result = await self.db.questions.find_one_and_update(
            {"_id": document["_id"], "creator_id": uid, "status": {"$ne": "approved"}},
            {"$set": {"status": "rejected", "approved": False, "review_reason": reason,
                      "withdrawn_by_creator": True, "withdrawn_at": now, "updated_at": now},
             "$inc": {"version": 1},
             "$push": {"review_history": self._capped(
                 {"from": current, "to": "rejected", "by": uid, "at": now, "reason": reason},
                 self.REVIEW_HISTORY_CAP)}},
            return_document=ReturnDocument.AFTER,
        )
        if not result:
            raise QuestionDomainError("withdraw_conflict", "وضعیت سؤال هم‌زمان تغییر کرده است", 409)
        return result

    async def delete_question(self, *, question_id: str, actor: Mapping,
                              reason: str = "") -> dict:
        """🛡 §۸۴ — حذفِ سختِ ادمین؛ تنها مصرف‌کننده‌ی `questions.delete`.

        عمداً *سخت* است و نه یک وضعیت دیگر: «برداشتِ» طراح از قبل با
        `withdraw_contribution` پوشش داده شده و سؤالِ رد‌شده هم در آرشیو
        می‌ماند. این مسیر برای محتوای اسپم/کپی‌رایت است که باید واقعاً برود.

        سؤالِ تأییدشده قفل است — همان قاعده‌ی `transition`/`withdraw`، چون
        ممکن است در آزمون‌ها و پاسخ‌های ثبت‌شده ارجاع داشته باشد.
        """
        if not ObjectId.is_valid(str(question_id)):
            raise QuestionDomainError("invalid_question_id", "شناسه سؤال معتبر نیست")
        document = await self.db.questions.find_one({"_id": ObjectId(str(question_id))})
        if not document:
            raise QuestionDomainError("question_not_found", "سؤال پیدا نشد", 404)
        await self.permissions.authorize_delete(actor=actor, question=document)
        if canonical_status(document) == "approved":
            raise QuestionDomainError(
                "approved_question_locked",
                "سؤال تأییدشده قفل است؛ ابتدا آن را رد کنید", 409)
        result = await self.db.questions.delete_one(
            {"_id": document["_id"], "status": {"$ne": "approved"}})
        if not getattr(result, "deleted_count", 0):
            # بین خواندن و حذف، سؤال تأیید شده است.
            raise QuestionDomainError("concurrent_review",
                                      "وضعیت سؤال هم‌زمان تغییر کرده است", 409)
        return {"id": str(document["_id"]),
                "status": canonical_status(document),
                "question": clean_text(document.get("question"))[:120],
                "creator_id": int(document.get("creator_id") or 0),
                "intake": clean_text(document.get("intake")),
                "reason": clean_text(reason, 1000)}

    async def list_my_contributions(self, user_id: int, *, skip: int = 0, limit: int = 30) -> dict:
        query = {"creator_id": int(user_id)}
        total = await self.db.questions.count_documents(query)
        docs = await self.db.questions.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
        items = []
        for doc in docs:
            items.append({**public_question(doc), "status": canonical_status(doc),
                          "review_reason": clean_text(doc.get("review_reason")),
                          "created_at": doc.get("created_at"), "updated_at": doc.get("updated_at"),
                          "version": int(doc.get("version") or 1)})
        return {"questions": items, "total": total, "skip": skip, "limit": limit}

    async def verify_access(self, question: Mapping, user: Mapping) -> None:
        if canonical_status(question) != "approved":
            raise QuestionDomainError("question_not_available", "سؤال در دسترس نیست", 404)
        if clean_text(question.get("intake")) not in self.student_intakes(user):
            raise QuestionDomainError("question_out_of_scope", "سؤال خارج از محدوده شماست", 403)

    async def record_answer(self, *, user: Mapping, question: Mapping, selected: int,
                            is_correct: bool, mode: str = "practice",
                            session_id: str = "") -> None:
        await self.verify_access(question, user)
        uid = int(user.get("id") or user.get("user_id") or 0)
        qid = str(question.get("_id"))
        await self.db.save_answer(uid, qid, selected, is_correct)
        now = utc_now_iso()
        progress_id = f"{uid}:{qid}"
        await self.db.question_progress.update_one(
            {"_id": progress_id},
            {"$setOnInsert": {"user_id": uid, "question_id": qid, "first_answered_at": now,
                               "lesson_id": str(question.get("lesson_id") or ""),
                               "topic_id": str(question.get("topic_id") or ""),
                               "lesson": question.get("lesson", ""), "topic": question.get("topic", "")},
             "$set": {"last_answered_at": now, "last_correct": bool(is_correct)},
             "$inc": {"attempts": 1, "correct_count": 1 if is_correct else 0}}, upsert=True)
        topic_key = str(question.get("topic_id") or normalized_question_text(question.get("topic")))
        if topic_key:
            await self.db.question_topic_stats.update_one(
                {"_id": f"{uid}:{topic_key}"},
                {"$setOnInsert": {"user_id": uid, "topic_key": topic_key,
                                   "lesson_id": str(question.get("lesson_id") or ""),
                                   "topic_id": str(question.get("topic_id") or ""),
                                   "lesson": question.get("lesson", ""), "topic": question.get("topic", "")},
                 "$set": {"updated_at": now},
                 "$inc": {"attempts": 1, "correct": 1 if is_correct else 0}}, upsert=True)

    async def practice_next(self, *, user: Mapping, taxonomy: Mapping,
                            mode: str = "free") -> dict:
        """Return one unsolved question without a client/Python-side ID fetch.

        The progress lookup is executed in MongoDB and uses the unique
        `(user_id, question_id)` index. This avoids the legacy unbounded
        `distinct → $nin` array as the bank grows toward 100k questions.
        """
        intakes = self.student_intakes(user)
        difficulty = "hard" if mode == "hard" else None
        eligible = self.eligible_query(taxonomy, intakes=intakes, difficulty=difficulty)
        uid = int(user.get("id") or 0)

        # 🐛 §W8 — سؤالی که همین کاربر گزارش کرده نباید دوباره به او
        # نشان داده شود.
        #
        # پیش‌تر فقط `question_progress` (سؤال‌های حل‌شده) دیده می‌شد، پس
        # سؤالِ گزارش‌شده در نمونه‌برداریِ تصادفی دوباره بالا می‌آمد —
        # در آزمون واقعی ۱۴ بار از ۴۰ نمونه.
        #
        # فیلتر عمداً «کاربر-محور» است: گزارشِ یک دانشجو نباید سؤال را
        # برای بقیه حذف کند. حذفِ سراسری کارِ چرخهٔ عمرِ سؤال است، نه
        # گزارش.
        excluded = await self.reported_question_ids(uid)
        if excluded:
            eligible = and_query(eligible, {"_id": {"$nin": excluded}})

        total = await self.db.questions.count_documents(eligible)
        lookup = {"$lookup": {
            "from": "question_progress",
            "let": {"qid": {"$toString": "$_id"}},
            "pipeline": [
                {"$match": {"$expr": {"$and": [
                    {"$eq": ["$user_id", uid]}, {"$eq": ["$question_id", "$$qid"]},
                ]}}},
                {"$limit": 1}, {"$project": {"_id": 1}},
            ],
            "as": "_user_progress",
        }}
        unsolved_pipeline = [
            {"$match": eligible}, lookup,
            {"$match": {"_user_progress.0": {"$exists": False}}},
            {"$sample": {"size": 1}}, {"$project": {"_user_progress": 0}},
        ]
        rows = await self.db.questions.aggregate(unsolved_pipeline).to_list(1)
        solved_rows = await self.db.questions.aggregate([
            {"$match": eligible}, lookup,
            {"$match": {"_user_progress.0": {"$exists": True}}},
            {"$count": "count"},
        ]).to_list(1)
        solved_in_scope = int(solved_rows[0]["count"]) if solved_rows else 0
        remaining = max(0, total - solved_in_scope)
        exhausted = not bool(rows)
        return {"question": public_question(rows[0]) if rows else None,
                "progress": {"total": total, "solved_unique": min(solved_in_scope, total),
                             "remaining": remaining, "exhausted": exhausted},
                "ai_available": exhausted}

    async def capacity(self, *, user: Mapping, taxonomy: Mapping,
                       difficulty: str | None = None) -> int:
        return await self.db.questions.count_documents(
            self.eligible_query(taxonomy, intakes=self.student_intakes(user), difficulty=difficulty))

    async def stats(self, *, user: Mapping) -> dict:
        uid = int(user.get("id") or 0)
        rows = await self.db.question_progress.aggregate([
            {"$match": {"user_id": uid}},
            {"$group": {"_id": None, "unique": {"$sum": 1}, "attempts": {"$sum": "$attempts"},
                        "correct": {"$sum": "$correct_count"}}},
        ]).to_list(1)
        summary = rows[0] if rows else {}
        attempts = int(summary.get("attempts") or 0)
        correct = int(summary.get("correct") or 0)
        weak_min = int(await self.db.get_setting("qbank_weak_min_attempts", 3) or 3)
        weak_threshold = float(await self.db.get_setting("qbank_weak_accuracy_pct", 60) or 60)
        topics = await self.db.question_topic_stats.find({"user_id": uid, "attempts": {"$gte": weak_min}}).sort("updated_at", -1).to_list(500)
        topic_rows = []
        for row in topics:
            ta = int(row.get("attempts") or 0); tc = int(row.get("correct") or 0)
            accuracy = round(tc * 100 / ta, 1) if ta else 0
            topic_rows.append({"lesson_id": row.get("lesson_id", ""), "topic_id": row.get("topic_id", ""),
                               "lesson": row.get("lesson", ""), "topic": row.get("topic", ""),
                               "attempts": ta, "correct": tc, "accuracy": accuracy,
                               "weak": accuracy < weak_threshold})
        return {"attempts": attempts, "solved_unique": int(summary.get("unique") or 0),
                "correct": correct, "wrong": max(0, attempts - correct),
                "accuracy": round(correct * 100 / attempts, 1) if attempts else 0,
                "weak_topics": [x for x in topic_rows if x["weak"]], "topics": topic_rows}
