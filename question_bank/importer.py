"""Versioned, preview-first, idempotent JSON ingestion for owner admins."""
from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

from bson import ObjectId
from pymongo import UpdateOne

from time_utils import utc_now_iso
from .contracts import (
    QuestionDomainError, canonical_difficulty, clean_text,
    normalized_question_text, question_content_hash, validate_question_payload,
)
from .service import QuestionBankService

IMPORT_SCHEMA_VERSION = "1.0"
PROMPT_PATH = Path(__file__).with_name("prompts") / "qbank_import_v1.txt"


class QuestionImportService:
    def __init__(self, database):
        self.db = database
        self.qbank = QuestionBankService(database)

    @staticmethod
    def prompt() -> dict:
        return {"schema_version": IMPORT_SCHEMA_VERSION, "prompt": PROMPT_PATH.read_text(encoding="utf-8")}

    @staticmethod
    def parse(raw: bytes, file_name: str) -> tuple[dict, str]:
        if not raw or len(raw) > 15 * 1024 * 1024:
            raise QuestionDomainError("invalid_import_size", "فایل JSON خالی یا بیش از ۱۵ مگابایت است", 413)
        fingerprint = hashlib.sha256(raw).hexdigest()
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise QuestionDomainError("malformed_json", "ساختار فایل JSON معتبر نیست") from exc
        if not isinstance(data, dict) or data.get("schema_version") != IMPORT_SCHEMA_VERSION:
            raise QuestionDomainError("unsupported_schema", f"schema_version باید {IMPORT_SCHEMA_VERSION} باشد")
        if not isinstance(data.get("questions"), list) or not data["questions"]:
            raise QuestionDomainError("empty_questions", "فایل هیچ سؤال قابل بررسی ندارد")
        if len(data["questions"]) > 5000:
            raise QuestionDomainError("too_many_questions", "حداکثر ۵۰۰۰ سؤال در هر job مجاز است", 413)
        source = data.get("source") if isinstance(data.get("source"), dict) else {}
        source.setdefault("file_name", file_name)
        data["source"] = source
        return data, fingerprint

    async def _classification_context(self, raw_items: list[Any], *, include_duplicates: bool = True) -> dict:
        """Bulk-prefetch taxonomy and optional duplicate candidates."""
        lesson_names = sorted({clean_text(x.get("lesson")) for x in raw_items if isinstance(x, dict) and clean_text(x.get("lesson"))})
        lesson_cap = min(50000, max(1000, len(lesson_names) * 20))
        lesson_docs = await self.db.bs_lessons.find({"name": {"$in": lesson_names}}).to_list(lesson_cap)
        if len(lesson_docs) >= lesson_cap:
            raise QuestionDomainError("taxonomy_prefetch_limit", "تعداد تطبیق‌های درس بیش از حد ایمن است", 409)
        lessons_by_name = defaultdict(list)
        for lesson in lesson_docs:
            lessons_by_name[clean_text(lesson.get("name"))].append(lesson)
        lesson_ids = [str(x["_id"]) for x in lesson_docs]
        session_docs = await self.db.bs_sessions.find({"lesson_id": {"$in": lesson_ids}}).to_list(100000)
        if len(session_docs) >= 100000:
            raise QuestionDomainError("taxonomy_prefetch_limit", "تعداد تطبیق‌های مبحث بیش از حد ایمن است", 409)
        sessions_by_key = defaultdict(list)
        for session in session_docs:
            sessions_by_key[(str(session.get("lesson_id") or ""), clean_text(session.get("topic")))].append(session)

        taxonomies = {}
        topic_ids = set()
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            key = (clean_text(item.get("lesson")), clean_text(item.get("topic")))
            matches = lessons_by_name.get(key[0], [])
            if len(matches) != 1:
                taxonomies[key] = {"state": "ambiguous" if len(matches) > 1 else "unmatched",
                                   "candidates": [{"id": str(x["_id"]), "name": x.get("name"),
                                                   "intake": x.get("intake", "")} for x in matches]}
                continue
            lesson = matches[0]; topics = sessions_by_key.get((str(lesson["_id"]), key[1]), [])
            if len(topics) != 1:
                taxonomies[key] = {"state": "ambiguous" if len(topics) > 1 else "unmatched",
                                   "candidates": [{"id": str(x["_id"]), "name": x.get("topic")} for x in topics]}
                continue
            topic = topics[0]
            taxonomy = {"lesson_id": str(lesson["_id"]), "topic_id": str(topic["_id"]),
                        "lesson": clean_text(lesson.get("name")), "topic": clean_text(topic.get("topic")),
                        "term": clean_text(lesson.get("term")), "intake": clean_text(lesson.get("intake"))}
            taxonomies[key] = {"state": "matched", "taxonomy": taxonomy, "candidates": []}
            topic_ids.add(taxonomy["topic_id"])

        if not include_duplicates:
            return {"taxonomies": taxonomies, "exact": {}, "candidates": {}}

        hashes = set()
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            try:
                normalized = validate_question_payload({"question": item.get("question"), "options": item.get("options"),
                    "correct_answer": item.get("correct_option"), "explanation": item.get("explanation"),
                    "difficulty": item.get("difficulty") or "medium"})
                hashes.add(normalized["content_hash"])
            except QuestionDomainError:
                pass
        exact_docs = await self.db.questions.find(
            {"content_hash": {"$in": list(hashes)}},
            {"content_hash": 1, "question": 1, "correct_answer": 1}).to_list(max(1, len(hashes)))
        exact_by_hash = {x.get("content_hash"): x for x in exact_docs}

        candidates_by_topic = defaultdict(list)
        if topic_ids:
            pipeline = [
                {"$match": {"topic_id": {"$in": list(topic_ids)}}},
                {"$setWindowFields": {"partitionBy": "$topic_id", "sortBy": {"created_at": -1},
                                      "output": {"_topic_rank": {"$documentNumber": {}}}}},
                {"$match": {"_topic_rank": {"$lte": 80}}},
                {"$project": {"question": 1, "correct_answer": 1, "options": 1, "topic_id": 1}},
            ]
            docs = await self.db.questions.aggregate(pipeline, allowDiskUse=True).to_list(min(100000, len(topic_ids) * 80))
            for document in docs:
                candidates_by_topic[str(document.get("topic_id") or "")].append(document)
        return {"taxonomies": taxonomies, "exact": exact_by_hash, "candidates": candidates_by_topic}

    async def create_preview(self, *, admin: Mapping, raw: bytes, file_name: str) -> dict:
        await self.qbank.permissions.authorize_import(admin)
        data, fingerprint = self.parse(raw, file_name)
        admin_id = int(admin.get("id") or 0)
        previous = await self.db.question_import_jobs.find_one(
            {"admin_id": admin_id, "fingerprint": fingerprint})
        if previous and previous.get("status") not in {"cancelled", "failed"}:
            return await self.preview(str(previous["_id"]))
        now = utc_now_iso(); job_id = str(previous["_id"]) if previous else uuid.uuid4().hex[:20]
        job = {"_id": job_id, "job_id": job_id, "admin_id": admin_id,
               "file_name": clean_text(file_name, 240), "schema_version": IMPORT_SCHEMA_VERSION,
               "fingerprint": fingerprint, "source": data.get("source") or {},
               "status": "validating", "started_at": now, "created_at": (previous or {}).get("created_at", now),
               "finished_at": None, "counts": {}, "mapping": {}, "error": None}
        if previous:
            await self.db.question_import_items.delete_many({"job_id": job_id})
            await self.db.question_import_jobs.replace_one({"_id": job_id}, job)
        else:
            await self.db.question_import_jobs.insert_one(job)
        try:
            context = await self._classification_context(data["questions"])
            items = []
            for index, raw_item in enumerate(data["questions"]):
                items.append(await self._classify(job_id, index, raw_item, data.get("source") or {}, admin_id,
                                                  context=context))
        except Exception as exc:
            await self.db.question_import_jobs.update_one(
                {"_id": job_id}, {"$set": {"status": "failed", "finished_at": utc_now_iso(),
                                           "error": "validation_failed"}})
            if isinstance(exc, QuestionDomainError):
                raise
            raise QuestionDomainError("import_validation_failed",
                                      "اعتبارسنجی فایل کامل نشد؛ بدون ثبت سؤال دوباره تلاش کنید", 503) from exc
        seen_external = {}
        seen_hash = {}
        for item in items:
            external = item["external_id"]
            if external in seen_external:
                item["classification"] = "error"
                item["errors"].append(f"external_id تکراری با ردیف {seen_external[external]}")
                item["external_id"] = f"{external}#ROW-{item['row']}"
            else:
                seen_external[external] = item["row"]
            normalized = item.get("normalized") or {}
            content_hash = normalized.get("content_hash")
            if content_hash and content_hash in seen_hash and item["classification"] not in {"error", "unmatched", "ambiguous"}:
                first = seen_hash[content_hash]
                answer_conflict = first["correct_answer"] != normalized.get("correct_answer")
                item["classification"] = "conflict" if answer_conflict else "exact_duplicate"
                item["duplicate"] = {"external_id": first["external_id"], "question": normalized.get("question", ""),
                                     "ratio": 1.0, "within_file": True, "answer_conflict": answer_conflict}
            elif content_hash:
                seen_hash[content_hash] = {"external_id": item["external_id"],
                                           "correct_answer": normalized.get("correct_answer")}
        if items:
            try:
                await self.db.question_import_items.insert_many(items, ordered=False)
            except Exception as exc:
                await self.db.question_import_jobs.update_one(
                    {"_id": job_id}, {"$set": {"status": "failed", "finished_at": utc_now_iso(),
                                               "error": "preview_persistence_failed"}})
                raise QuestionDomainError("import_preview_failed",
                                          "ذخیره پیش‌نمایش انجام نشد و هیچ سؤالی وارد بانک نشد", 503) from exc
        counts = Counter(x["classification"] for x in items)
        totals = {"total": len(items), "ready": counts["ready"], "errors": counts["error"],
                  "unmatched": counts["unmatched"], "ambiguous": counts["ambiguous"],
                  "exact_duplicates": counts["exact_duplicate"],
                  "probable_duplicates": counts["probable_duplicate"],
                  "conflicts": counts["conflict"], "imported": 0, "skipped": 0}
        await self.db.question_import_jobs.update_one({"_id": job_id},
            {"$set": {"status": "preview_ready", "counts": totals, "validated_at": utc_now_iso()}})
        return await self.preview(job_id)

    async def _classify(self, job_id: str, index: int, raw: Any, source: Mapping, admin_id: int,
                        context: Mapping | None = None) -> dict:
        item = raw if isinstance(raw, dict) else {}
        external_id = clean_text(item.get("external_id")) or f"ROW-{index + 1:04d}"
        errors = [clean_text(x, 500) for x in (item.get("errors") or []) if clean_text(x)]
        image = item.get("image") if isinstance(item.get("image"), Mapping) else {}
        if image.get("required"):
            errors.append("سؤال وابسته به تصویر است و تا اتصال تصویر قابل import نیست")
        confidence = item.get("confidence") if isinstance(item.get("confidence"), Mapping) else {}
        thresholds = {"question": 0.75, "options": 0.75, "answer": 0.70, "classification": 0.60}
        for key, threshold in thresholds.items():
            value = confidence.get(key)
            if value is not None:
                try:
                    if float(value) < threshold:
                        errors.append(f"اطمینان {key} کمتر از حد مجاز است")
                except (TypeError, ValueError):
                    errors.append(f"confidence.{key} معتبر نیست")
        normalized = None
        try:
            normalized = validate_question_payload({
                "question": item.get("question"), "options": item.get("options"),
                "correct_answer": item.get("correct_option"),
                "explanation": item.get("explanation"),
                "difficulty": item.get("difficulty") or "medium",
            })
        except QuestionDomainError as exc:
            errors.append(exc.message)
        taxonomy = None; taxonomy_state = "unmatched"; taxonomy_candidates = []
        if context is not None:
            tax_info = (context.get("taxonomies") or {}).get(
                (clean_text(item.get("lesson")), clean_text(item.get("topic"))), {"state": "unmatched"})
            taxonomy_state = tax_info.get("state", "unmatched")
            taxonomy = tax_info.get("taxonomy")
            taxonomy_candidates = tax_info.get("candidates") or []
        else:
            try:
                taxonomy = await self.qbank.resolve_taxonomy(lesson=item.get("lesson"), topic=item.get("topic"),
                                                              visible_intakes=None)
                taxonomy_state = "matched"
            except QuestionDomainError as exc:
                taxonomy_state = "ambiguous" if exc.code.startswith("ambiguous") else "unmatched"
                taxonomy_candidates = (exc.details or {}).get("matches", [])
        classification = "error" if errors or normalized is None else taxonomy_state
        duplicate = None
        if normalized and taxonomy and not errors:
            exact = ((context.get("exact") or {}).get(normalized["content_hash"])
                     if context is not None else
                     await self.db.questions.find_one({"content_hash": normalized["content_hash"]}))
            if exact:
                same_answer = int(exact.get("correct_answer", -1)) == normalized["correct_answer"]
                classification = "exact_duplicate" if same_answer else "conflict"
                duplicate = {"id": str(exact["_id"]), "question": exact.get("question", ""),
                             "ratio": 1.0, "answer_conflict": not same_answer}
            else:
                if context is not None:
                    candidates = list((context.get("candidates") or {}).get(taxonomy["topic_id"], []))
                else:
                    candidates = await self.db.questions.find({
                        "$or": [{"topic_id": taxonomy["topic_id"]},
                                 {"topic_id": {"$exists": False}, "lesson": taxonomy["lesson"], "topic": taxonomy["topic"]}]
                    }, {"question": 1, "correct_answer": 1, "options": 1}).sort("created_at", -1).limit(80).to_list(80)
                import difflib
                target = normalized_question_text(normalized["question"])
                best = None
                for candidate in candidates:
                    ratio = difflib.SequenceMatcher(None, target, normalized_question_text(candidate.get("question"))).ratio()
                    if ratio >= 0.82 and (best is None or ratio > best["ratio"]):
                        best = {"id": str(candidate["_id"]), "question": candidate.get("question", ""), "ratio": round(ratio, 3)}
                if best:
                    same_answer = int((next((x for x in candidates if str(x.get("_id")) == best["id"]), {}) or {}).get("correct_answer", -1)) == normalized["correct_answer"]
                    classification = "probable_duplicate" if same_answer else "conflict"
                    duplicate = best
                elif taxonomy_state == "matched":
                    classification = "ready"
        return {"job_id": job_id, "row": index + 1, "external_id": external_id,
                "source_page": item.get("page"), "raw": item, "normalized": normalized,
                "taxonomy": taxonomy, "taxonomy_state": taxonomy_state,
                "taxonomy_candidates": taxonomy_candidates, "classification": classification,
                "errors": errors, "duplicate": duplicate, "decision": None,
                "admin_id": admin_id, "source": dict(source), "created_at": utc_now_iso()}

    async def preview(self, job_id: str) -> dict:
        job = await self.db.question_import_jobs.find_one({"_id": job_id})
        if not job:
            raise QuestionDomainError("import_job_not_found", "job درون‌ریزی پیدا نشد", 404)
        breakdown = await self.db.question_import_items.aggregate([
            {"$match": {"job_id": job_id}},
            {"$group": {"_id": {"lesson": "$taxonomy.lesson", "topic": "$taxonomy.topic",
                                  "classification": "$classification"}, "count": {"$sum": 1}}},
        ]).to_list(10000)
        lessons = defaultdict(lambda: {"count": 0, "topics": Counter()})
        for row in breakdown:
            key = row.get("_id") or {}; lesson = key.get("lesson") or "نامشخص"; topic = key.get("topic") or "نامشخص"
            count = int(row.get("count") or 0); lessons[lesson]["count"] += count; lessons[lesson]["topics"][topic] += count
        return {"job_id": job_id, "status": job.get("status"), "file_name": job.get("file_name"),
                "schema_version": job.get("schema_version"), "counts": job.get("counts") or {},
                "source": job.get("source") or {}, "started_at": job.get("started_at"),
                "finished_at": job.get("finished_at"),
                "classification": [{"lesson": lesson, "count": value["count"],
                                    "topics": [{"topic": topic, "count": count} for topic, count in value["topics"].most_common()]}
                                   for lesson, value in sorted(lessons.items())]}

    async def list_items(self, job_id: str, *, classification: str | None = None,
                         skip: int = 0, limit: int = 50) -> dict:
        query = {"job_id": job_id}
        if classification:
            query["classification"] = classification
        total = await self.db.question_import_items.count_documents(query)
        docs = await self.db.question_import_items.find(query).sort("row", 1).skip(skip).limit(limit).to_list(limit)
        for doc in docs:
            doc["id"] = str(doc.pop("_id"))
        return {"items": docs, "total": total, "skip": skip, "limit": limit}

    async def map_item(self, *, job_id: str, item_id: str,
                       lesson_id: str, topic_id: str) -> dict:
        if not await self.db.question_import_jobs.find_one({"_id": job_id, "status": "preview_ready"}, {"_id": 1}):
            raise QuestionDomainError("import_not_ready", "job برای نگاشت آماده نیست", 409)
        if not ObjectId.is_valid(item_id):
            raise QuestionDomainError("invalid_import_item", "ردیف import معتبر نیست")
        taxonomy = await self.qbank.resolve_taxonomy(lesson_id=lesson_id, topic_id=topic_id, visible_intakes=None)
        item = await self.db.question_import_items.find_one({"_id": ObjectId(item_id), "job_id": job_id})
        if not item:
            raise QuestionDomainError("import_item_not_found", "ردیف پیدا نشد", 404)
        classification = item.get("classification")
        duplicate = item.get("duplicate")
        if item.get("normalized") and not item.get("errors"):
            duplicate_result = await self.qbank.duplicate_candidates(
                taxonomy=taxonomy, question=item["normalized"]["question"],
                content_hash=item["normalized"]["content_hash"],
                correct_answer=item["normalized"]["correct_answer"],
                intakes=[taxonomy.get("intake", ""), ""])
            if duplicate_result["conflict"]:
                classification = "conflict"; duplicate = duplicate_result["conflict"][0]
            elif duplicate_result["exact"]:
                classification = "exact_duplicate"; duplicate = duplicate_result["exact"][0]
            elif duplicate_result["probable"]:
                classification = "probable_duplicate"; duplicate = duplicate_result["probable"][0]
            else:
                classification = "ready"; duplicate = None
        await self.db.question_import_items.update_one({"_id": item["_id"]},
            {"$set": {"taxonomy": taxonomy, "taxonomy_state": "matched", "classification": classification,
                      "duplicate": duplicate, "decision": None, "mapped_at": utc_now_iso()}})
        await self.recount(job_id)
        return {"ok": True, "classification": classification, "taxonomy": taxonomy}

    async def set_decision(self, *, job_id: str, item_id: str, decision: str) -> dict:
        if not await self.db.question_import_jobs.find_one({"_id": job_id, "status": "preview_ready"}, {"_id": 1}):
            raise QuestionDomainError("import_not_ready", "job برای تصمیم آماده نیست", 409)
        if decision not in {"import", "skip"} or not ObjectId.is_valid(item_id):
            raise QuestionDomainError("invalid_import_decision", "تصمیم import معتبر نیست")
        item = await self.db.question_import_items.find_one({"_id": ObjectId(item_id), "job_id": job_id})
        if not item:
            raise QuestionDomainError("import_item_not_found", "ردیف پیدا نشد", 404)
        if decision == "import" and item.get("classification") in {"error", "unmatched", "ambiguous", "exact_duplicate"}:
            raise QuestionDomainError("unsafe_import_decision", "این ردیف پیش از رفع خطا قابل import نیست", 409)
        await self.db.question_import_items.update_one({"_id": item["_id"]}, {"$set": {"decision": decision}})
        return {"ok": True}

    async def recount(self, job_id: str) -> dict:
        rows = await self.db.question_import_items.aggregate([
            {"$match": {"job_id": job_id}}, {"$group": {"_id": "$classification", "count": {"$sum": 1}}}
        ]).to_list(20)
        c = {x["_id"]: int(x["count"]) for x in rows}; total = sum(c.values())
        counts = {"total": total, "ready": c.get("ready", 0), "errors": c.get("error", 0),
                  "unmatched": c.get("unmatched", 0), "ambiguous": c.get("ambiguous", 0),
                  "exact_duplicates": c.get("exact_duplicate", 0),
                  "probable_duplicates": c.get("probable_duplicate", 0), "conflicts": c.get("conflict", 0)}
        await self.db.question_import_jobs.update_one({"_id": job_id}, {"$set": {"counts": counts}})
        return counts

    async def confirm(self, *, job_id: str, admin: Mapping) -> dict:
        await self.qbank.permissions.authorize_import(admin)
        job = await self.db.question_import_jobs.find_one({"_id": job_id, "admin_id": int(admin.get("id") or 0)})
        if not job:
            raise QuestionDomainError("import_job_not_found", "job درون‌ریزی پیدا نشد", 404)
        if job.get("status") == "completed":
            return {"ok": True, **(job.get("result") or {}), "idempotent": True}
        if job.get("status") != "preview_ready":
            raise QuestionDomainError("import_not_ready", "پیش‌نمایش برای تأیید آماده نیست", 409)
        claimed = await self.db.question_import_jobs.update_one({"_id": job_id, "status": "preview_ready"},
                                                                {"$set": {"status": "importing", "import_started_at": utc_now_iso()}})
        if claimed.modified_count != 1:
            raise QuestionDomainError("import_in_progress", "درون‌ریزی هم‌زمان در حال اجراست", 409)
        candidate_query = {"job_id": job_id, "$or": [
            {"classification": "ready"},
            {"classification": {"$in": ["probable_duplicate", "conflict"]}, "decision": "import"},
        ]}
        candidates = await self.db.question_import_items.find(candidate_query).sort("row", 1).to_list(5000)
        imported = skipped = failed = 0; errors = []
        prepared = []
        for item in candidates:
            identity = hashlib.sha256(
                f"{job['fingerprint']}:{item['external_id']}:{item['normalized']['content_hash']}".encode()).hexdigest()
            now = utc_now_iso(); taxonomy = item["taxonomy"]; normalized = item["normalized"]
            document = {**normalized, **taxonomy, "intake": taxonomy.get("intake", ""),
                        "status": "approved", "approved": True,
                        "source": "ai_admin_import", "creator_type": "admin",
                        "provenance": {"source": "ai_admin_import", "creator_type": "admin",
                                       "created_by": int(admin.get("id") or 0),
                                       "import": {"job_id": job_id, "schema_version": IMPORT_SCHEMA_VERSION,
                                                  "file_name": job.get("file_name"),
                                                  "source_page": item.get("source_page"),
                                                  "external_id": item.get("external_id")}},
                        "creator_id": int(admin.get("id") or 0),
                        "creator_name": self.db.display_name_of(admin.get("_db") or admin),
                        "import_job_id": job_id, "import_identity": identity,
                        "source_file_name": job.get("file_name"), "source_page": item.get("source_page"),
                        "external_question_id": item.get("external_id"),
                        "created_at": now, "updated_at": now, "reviewed_at": now,
                        "reviewed_by": int(admin.get("id") or 0), "review_reason": "درون‌ریزی تأییدشده توسط مالک",
                        "version": 1, "review_history": [{"from": None, "to": "approved",
                            "by": int(admin.get("id") or 0), "at": now, "reason": "درون‌ریزی JSON تأییدشده"}],
                        "attempt_count": 0, "correct_count": 0}
            prepared.append((item, identity, document))

        # Bounded bulk upserts replace the old per-row find+insert+update N+1 path.
        for offset in range(0, len(prepared), 500):
            batch = prepared[offset:offset + 500]
            operations = [UpdateOne({"import_identity": identity}, {"$setOnInsert": document}, upsert=True)
                          for _, identity, document in batch]
            try:
                write = await self.db.questions.bulk_write(operations, ordered=False)
                inserted_indexes = set((write.upserted_ids or {}).keys())
                inserted_item_ids = [item["_id"] for index, (item, _, _) in enumerate(batch)
                                     if index in inserted_indexes]
                imported += len(inserted_item_ids)
                skipped += len(batch) - len(inserted_item_ids)
                if inserted_item_ids:
                    await self.db.question_import_items.update_many(
                        {"_id": {"$in": inserted_item_ids}},
                        {"$set": {"imported": True, "imported_at": utc_now_iso()}})
            except Exception:
                # Rare batch-level failure is isolated and reported without raw DB errors.
                failed += len(batch)
                errors.extend({"external_id": item.get("external_id"), "error": "bulk_insert_failed"}
                              for item, _, _ in batch)
        total_items = await self.db.question_import_items.count_documents({"job_id": job_id})
        # Every row is accounted for exactly once: inserted, failed insertion,
        # or intentionally skipped (validation/taxonomy/duplicate/decision/idempotency).
        skipped = max(skipped, total_items - imported - failed)
        result = {"imported": imported, "skipped": skipped, "failed": failed, "errors": errors[:100]}
        # Failed batches return to preview_ready so the owner can retry safely;
        # import_identity upserts make already inserted rows idempotent.
        status = "completed" if not failed else "preview_ready"
        await self.db.question_import_jobs.update_one({"_id": job_id},
            {"$set": {"status": status, "finished_at": utc_now_iso(), "result": result,
                      "counts.imported": imported, "counts.skipped": skipped, "counts.failed": failed}})
        return {"ok": not failed, **result, "idempotent": False}

    async def cancel(self, *, job_id: str, admin_id: int) -> dict:
        result = await self.db.question_import_jobs.update_one(
            {"_id": job_id, "admin_id": int(admin_id), "status": {"$in": ["validating", "preview_ready"]}},
            {"$set": {"status": "cancelled", "finished_at": utc_now_iso()}})
        if not result.modified_count:
            raise QuestionDomainError("import_not_cancellable", "این job قابل لغو نیست", 409)
        return {"ok": True, "status": "cancelled"}
