"""Read-first, idempotent migration helpers. Never runs automatically."""
from __future__ import annotations

from .contracts import canonical_difficulty, canonical_source, question_content_hash
from time_utils import utc_now_iso


async def inspect_questions(database, sample_limit: int = 20) -> dict:
    total = await database.questions.count_documents({})
    pipeline = [{"$facet": {
        "status": [{"$group": {"_id": {"status": "$status", "approved": "$approved"}, "count": {"$sum": 1}}}],
        "difficulty": [{"$group": {"_id": "$difficulty", "count": {"$sum": 1}}}],
        "options": [{"$project": {"n": {"$cond": [{"$isArray": "$options"}, {"$size": "$options"}, -1]}}},
                    {"$group": {"_id": "$n", "count": {"$sum": 1}}}],
        "source": [{"$group": {"_id": "$source", "count": {"$sum": 1}}}],
        "taxonomy": [{"$group": {"_id": {"lesson_id": {"$type": "$lesson_id"},
                                              "topic_id": {"$type": "$topic_id"}}, "count": {"$sum": 1}}}],
    }}]
    rows = await database.questions.aggregate(pipeline).to_list(1)
    samples = await database.questions.find({}, {"question": 1, "lesson": 1, "topic": 1,
                                                  "difficulty": 1, "options": 1, "source": 1,
                                                  "approved": 1, "status": 1}).limit(sample_limit).to_list(sample_limit)
    return {"total": total, "distribution": rows[0] if rows else {},
            "samples": [{**x, "_id": str(x.get("_id"))} for x in samples],
            "safe_to_auto_migrate": False,
            "reason": "taxonomy ambiguity and invalid option counts require runtime review"}


async def migrate_questions(database, *, apply: bool = False, limit: int = 100000,
                            expected_total: int | None = None) -> dict:
    """Backfill only unambiguous fields with an idempotent original snapshot."""
    live_total = await database.questions.count_documents({})
    if apply and (expected_total is None or int(expected_total) != live_total):
        raise RuntimeError(f"inspection total mismatch: live={live_total}, confirmed={expected_total}")
    if apply and live_total > limit:
        raise RuntimeError(f"live total {live_total} exceeds migration safety limit {limit}")
    migration_id = "question_bank_v2_schema_1"
    report = {"migration": migration_id, "live_total": live_total,
              "scanned": 0, "migrated": 0, "ambiguous": [], "invalid": [],
              "ambiguous_count": 0, "invalid_count": 0}
    def issue(kind: str, payload: dict) -> None:
        report[f"{kind}_count"] += 1
        if len(report[kind]) < 200:
            report[kind].append(payload)
    # Resolve each legacy lesson/topic pair in bulk; no per-question taxonomy N+1.
    pairs = await database.questions.aggregate([
        {"$match": {"$or": [{"lesson_id": {"$in": [None, ""]}},
                              {"topic_id": {"$in": [None, ""]}},
                              {"lesson_id": {"$exists": False}}, {"topic_id": {"$exists": False}}]}},
        {"$group": {"_id": {"lesson": "$lesson", "topic": "$topic"}}}, {"$limit": 20000},
    ]).to_list(20000)
    from .importer import QuestionImportService
    taxonomy_context = await QuestionImportService(database)._classification_context(
        [{"lesson": (row.get("_id") or {}).get("lesson"),
          "topic": (row.get("_id") or {}).get("topic")} for row in pairs], include_duplicates=False)
    report["taxonomy_pairs_sampled"] = len(pairs)
    report["taxonomy_pairs_truncated"] = len(pairs) >= 20000
    if apply and report["taxonomy_pairs_truncated"]:
        raise RuntimeError("taxonomy pair preflight reached safety cap; split migration before apply")
    cursor = database.questions.find({}).sort("_id", 1).limit(limit)
    async for doc in cursor:
        report["scanned"] += 1; updates = {}
        options = doc.get("options") if isinstance(doc.get("options"), list) else []
        if len(options) != 4:
            issue("invalid", {"id": str(doc["_id"]), "reason": "options_count", "count": len(options)})
            continue
        try: updates["difficulty"] = canonical_difficulty(doc.get("difficulty"))
        except Exception:
            issue("invalid", {"id": str(doc["_id"]), "reason": "difficulty"}); continue
        updates["status"] = doc.get("status") if doc.get("status") in {"pending", "approved", "rejected", "needs_changes"} else ("approved" if doc.get("approved") else "pending")
        updates["approved"] = updates["status"] == "approved"
        creator_type = doc.get("creator_type") or (
            "ai" if str(doc.get("source") or "").startswith("ai") else
            "admin" if doc.get("by_bot") else "student")
        updates["creator_type"] = creator_type
        updates["source"] = canonical_source(doc.get("source"), creator_type)
        updates["provenance"] = doc.get("provenance") or {
            "source": updates["source"], "creator_type": creator_type,
            "created_by": int(doc.get("creator_id") or 0), "migrated_from": "legacy_question"}
        updates["content_hash"] = doc.get("content_hash") or question_content_hash(doc.get("question"), options)
        updates["version"] = int(doc.get("version") or 1)
        if not isinstance(doc.get("review_history"), list):
            updates["review_history"] = ([{"from": None, "to": "approved",
                "by": int(doc.get("reviewed_by") or 0),
                "at": doc.get("reviewed_at") or doc.get("created_at") or utc_now_iso(),
                "reason": "وضعیت تأیید legacy پیش از migration"}] if updates["status"] == "approved" else [])
        updates["review_reason"] = str(doc.get("review_reason") or "")
        if not doc.get("lesson_id") or not doc.get("topic_id"):
            key = (str(doc.get("lesson") or "").strip(), str(doc.get("topic") or "").strip())
            tax_info = (taxonomy_context.get("taxonomies") or {}).get(key, {"state": "unmatched"})
            taxonomy = tax_info.get("taxonomy")
            if not taxonomy:
                issue("ambiguous", {"id": str(doc["_id"]), "lesson": doc.get("lesson"),
                                    "topic": doc.get("topic"), "reason": tax_info.get("state", "taxonomy")})
                continue
            # Preserve an explicit legacy question intake when taxonomy is global.
            if doc.get("intake") and not taxonomy.get("intake"):
                taxonomy = {**taxonomy, "intake": doc.get("intake")}
            updates.update(taxonomy)
        if apply:
            updates["updated_at"] = doc.get("updated_at") or utc_now_iso()
            await database.question_migration_backups.update_one(
                {"_id": f"{migration_id}:{doc['_id']}"},
                {"$setOnInsert": {"migration": migration_id, "question_id": str(doc["_id"]),
                                  "captured_at": utc_now_iso(), "original": doc}}, upsert=True)
            await database.questions.update_one({"_id": doc["_id"]}, {"$set": updates})
        report["migrated"] += 1
    report["applied"] = bool(apply)
    report["backup_rows"] = (await database.question_migration_backups.count_documents(
        {"migration": migration_id})) if apply else 0
    report["rollback_command"] = "python qbank_migrate.py rollback --apply --migration question_bank_v2_schema_1"
    return report


async def rollback_questions(database, *, migration: str, apply: bool = False,
                             expected_count: int | None = None) -> dict:
    query = {"migration": migration}
    count = await database.question_migration_backups.count_documents(query)
    if not apply:
        return {"migration": migration, "backup_rows": count, "would_restore": count, "applied": False}
    if expected_count is None or int(expected_count) != count:
        raise RuntimeError(f"backup count mismatch: live={count}, confirmed={expected_count}")
    restored = 0
    async for backup in database.question_migration_backups.find(query).sort("question_id", 1):
        original = backup.get("original")
        if not isinstance(original, dict) or "_id" not in original:
            continue
        await database.questions.replace_one({"_id": original["_id"]}, original, upsert=True)
        restored += 1
    return {"migration": migration, "backup_rows": count, "restored": restored, "applied": True,
            "warning": "Answers and reviews created after migration are not rolled back by schema restore."}


async def rollback_progress(database, *, apply: bool = False,
                            expected_count: int | None = None) -> dict:
    migration = "question_bank_v2_progress_1"; query = {"migration": migration}
    count = await database.question_migration_backups.count_documents(query)
    if not apply:
        return {"migration": migration, "backup_rows": count, "would_restore": count, "applied": False}
    if expected_count is None or int(expected_count) != count:
        raise RuntimeError(f"backup count mismatch: live={count}, confirmed={expected_count}")
    restored = removed = 0
    async for backup in database.question_migration_backups.find(query).sort("progress_id", 1):
        if backup.get("existed") and isinstance(backup.get("original"), dict):
            original = backup["original"]
            await database.question_progress.replace_one({"_id": original["_id"]}, original, upsert=True)
            restored += 1
        else:
            result = await database.question_progress.delete_one({"_id": backup.get("progress_id")})
            removed += int(getattr(result, "deleted_count", 0))
    return {"migration": migration, "backup_rows": count, "restored": restored,
            "removed_created_rows": removed, "applied": True}


async def backfill_progress(database, *, apply: bool = False, limit: int = 1000000) -> dict:
    unique_count_rows = await database.answers.aggregate([
        {"$group": {"_id": {"user_id": "$user_id", "question_id": "$question_id"}}},
        {"$count": "count"},
    ], allowDiskUse=True).to_list(1)
    unique_total = int(unique_count_rows[0]["count"]) if unique_count_rows else 0
    if apply and unique_total > limit:
        raise RuntimeError(f"unique progress rows {unique_total} exceed safety limit {limit}")
    report = {"answers": 0, "unique": 0, "unique_total": unique_total,
              "truncated": unique_total > limit, "applied": bool(apply)}
    pipeline = [
        {"$sort": {"answered_at": 1}},
        {"$group": {"_id": {"user_id": "$user_id", "question_id": "$question_id"},
                    "attempts": {"$sum": 1}, "correct": {"$sum": {"$cond": ["$is_correct", 1, 0]}},
                    "first": {"$first": "$answered_at"}, "last": {"$last": "$answered_at"},
                    "last_correct": {"$last": "$is_correct"}}},
        {"$limit": limit},
        {"$set": {"question_oid": {"$convert": {"input": "$_id.question_id", "to": "objectId",
                                                   "onError": None, "onNull": None}},
                  "progress_id": {"$concat": [{"$toString": "$_id.user_id"}, ":", {"$toString": "$_id.question_id"}]}}},
        {"$lookup": {"from": "questions", "localField": "question_oid", "foreignField": "_id",
                     "pipeline": [{"$project": {"lesson_id": 1, "topic_id": 1, "lesson": 1, "topic": 1}}],
                     "as": "question"}},
        {"$set": {"question": {"$first": "$question"}}},
        {"$lookup": {"from": "question_progress", "localField": "progress_id", "foreignField": "_id",
                     "as": "original_progress"}},
        {"$set": {"original_progress": {"$first": "$original_progress"}}},
    ]
    async for row in database.answers.aggregate(pipeline, allowDiskUse=True):
        report["answers"] += int(row.get("attempts") or 0); report["unique"] += 1
        if apply:
            key = row["_id"]; qid = str(key.get("question_id")); uid = int(key.get("user_id"))
            progress_id = f"{uid}:{qid}"; question = row.get("question") or {}
            original = row.get("original_progress")
            await database.question_migration_backups.update_one(
                {"_id": f"question_bank_v2_progress_1:{progress_id}"},
                {"$setOnInsert": {"migration": "question_bank_v2_progress_1",
                                  "progress_id": progress_id, "captured_at": utc_now_iso(),
                                  "existed": bool(original), "original": original}}, upsert=True)
            await database.question_progress.update_one({"_id": progress_id}, {"$set": {
                "user_id": uid, "question_id": qid, "attempts": row.get("attempts", 0),
                "correct_count": row.get("correct", 0), "first_answered_at": row.get("first"),
                "last_answered_at": row.get("last"), "last_correct": row.get("last_correct"),
                "lesson_id": str((question or {}).get("lesson_id") or ""),
                "topic_id": str((question or {}).get("topic_id") or ""),
                "lesson": (question or {}).get("lesson", ""), "topic": (question or {}).get("topic", ""),
            }}, upsert=True)
    report["backup_rows"] = (await database.question_migration_backups.count_documents(
        {"migration": "question_bank_v2_progress_1"})) if apply else 0
    report["rollback_command"] = "python qbank_migrate.py rollback-progress --apply --confirmed-backup-count <count>"
    return report
