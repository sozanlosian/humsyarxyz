"""Read-only timestamp inventory for HUMSYAR MongoDB.

No migration runs from this module. Production operators can inspect actual
field types/counts before approving an idempotent migration. Ambiguous naive
strings are reported, never guessed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from typing import Literal

TimestampKind = Literal["instant", "date_only", "epoch", "technical"]


@dataclass(frozen=True)
class TimestampField:
    collection: str
    field: str
    kind: TimestampKind
    current_contract: str
    source_timezone: str
    consumers: tuple[str, ...]
    migration: str


FIELDS = (
    TimestampField("users", "registered_at", "instant", "legacy ISO string; new UTC aware ISO", "legacy deployment UTC; sample required", ("Bot", "WebAdmin", "Analytics", "User360"), "AMBIGUOUS until production type/sample audit"),
    TimestampField("users", "last_active", "instant", "legacy ISO string; new UTC aware ISO", "legacy deployment UTC; sample required", ("Bot", "WebAdmin", "Analytics"), "AMBIGUOUS until production type/sample audit"),
    TimestampField("users", "nickname_updated_at", "instant", "ISO string", "UTC", ("Profile", "Identity policy"), "normalize only after dry-run"),
    TimestampField("questions", "created_at", "instant", "ISO string", "UTC", ("Bot", "MiniApp API", "WebAdmin", "Export"), "normalize only after dry-run"),
    TimestampField("answers", "answered_at", "instant", "ISO string", "UTC", ("Practice", "User360", "Analytics"), "normalize only after dry-run"),
    TimestampField("stats", "timestamp", "instant", "ISO string", "UTC", ("Analytics", "Dashboard"), "keep; Mongo conversion occurs inside timezone-aware aggregation"),
    TimestampField("schedules", "date", "date_only", "Gregorian YYYY-MM-DD", "Tehran civil day", ("Bot", "MiniApp API", "WebAdmin", "Jobs"), "do not convert to BSON instant"),
    TimestampField("schedules", "created_at", "instant", "ISO string", "UTC", ("Audit", "Admin"), "normalize only after dry-run"),
    TimestampField("grades", "exam_date", "date_only", "Gregorian YYYY-MM-DD", "Tehran civil day", ("Bot", "MiniApp API", "WebAdmin"), "do not convert to BSON instant"),
    TimestampField("grades", "created_at", "instant", "ISO string", "UTC", ("WebAdmin", "Audit"), "normalize only after dry-run"),
    TimestampField("tickets", "created_at", "instant", "ISO string", "UTC", ("Bot", "MiniApp API", "WebAdmin", "Analytics"), "normalize only after dry-run"),
    TimestampField("tickets", "last_reply_at", "instant", "ISO string", "UTC", ("WebAdmin", "Support"), "normalize only after dry-run"),
    TimestampField("tickets", "closed_at", "instant", "ISO string", "UTC", ("WebAdmin", "Analytics"), "normalize only after dry-run"),
    TimestampField("user_notifications", "created_at", "instant", "ISO string", "UTC", ("MiniApp API", "User360"), "normalize only after dry-run"),
    TimestampField("bot_notifications", "created_at", "instant", "ISO string", "UTC", ("Outbox", "Correlation"), "normalize only after dry-run"),
    TimestampField("bot_notifications", "send_at", "instant", "UTC aware ISO", "UTC", ("Outbox scheduler", "Broadcast"), "canonical for new writes; audit legacy strings"),
    TimestampField("notif_runs", "started_at", "instant", "ISO string", "UTC", ("Bot jobs", "WebAdmin", "Analytics"), "normalize only after dry-run"),
    TimestampField("notif_runs", "finished_at", "instant", "ISO string", "UTC", ("Bot jobs", "WebAdmin"), "normalize only after dry-run"),
    TimestampField("broadcast_campaigns", "created_at", "instant", "UTC aware ISO", "UTC", ("Bot", "WebAdmin", "Audit"), "canonical for new writes"),
    TimestampField("broadcast_campaigns", "send_at", "instant", "UTC aware ISO", "UTC", ("Bot", "WebAdmin", "Outbox"), "canonical for new writes; audit legacy strings"),
    TimestampField("broadcast_campaigns", "finished_at", "instant", "UTC aware ISO", "UTC", ("WebAdmin", "Audit"), "canonical for new writes"),
    TimestampField("subscriptions", "start_date", "instant", "UTC aware ISO", "UTC", ("Bot", "MiniApp API", "WebAdmin"), "audit legacy naive strings"),
    TimestampField("subscriptions", "end_date", "instant", "UTC aware ISO", "UTC", ("Access", "Jobs", "Bot", "WebAdmin"), "audit legacy naive strings before conversion"),
    TimestampField("sub_payments", "submitted_at", "instant", "ISO string", "UTC", ("Bot", "MiniApp API", "WebAdmin"), "normalize only after dry-run"),
    TimestampField("sub_payments", "reviewed_at", "instant", "ISO string", "UTC", ("Bot", "WebAdmin", "Analytics"), "normalize only after dry-run"),
    TimestampField("discount_codes", "expires_at", "instant", "legacy date-only or ISO; new UTC aware ISO", "legacy date means end of Tehran day", ("Validation", "Bot", "WebAdmin"), "idempotently normalize on use; report legacy date-only rows"),
    TimestampField("discount_codes", "created_at", "instant", "UTC aware ISO", "UTC", ("Bot", "WebAdmin"), "canonical for new writes"),
    TimestampField("discount_uses", "used_at", "instant", "UTC aware ISO", "UTC", ("Finance", "Audit"), "canonical for new writes"),
    TimestampField("audit_logs", "timestamp", "instant", "UTC aware ISO", "UTC", ("Bot", "WebAdmin", "Export"), "canonical for new writes; never rewrite without archive"),
    TimestampField("prestige_history", "at", "instant", "UTC aware ISO", "UTC", ("Bot", "MiniApp API", "User360"), "canonical for new writes"),
    TimestampField("exam_sessions", "started_at", "instant", "UTC aware ISO", "UTC", ("MiniApp API", "Prestige", "Analytics"), "canonical for new writes"),
    TimestampField("ai_reports", "created_at", "instant", "BSON Date", "UTC", ("AI Admin", "Export"), "already canonical"),
    TimestampField("ai_conversations", "created_at", "instant", "UTC aware ISO", "UTC", ("MiniApp API"), "canonical for new writes"),
    TimestampField("web_admin_sessions", "created_at", "instant", "BSON Date", "UTC", ("Auth", "Security Center"), "already canonical"),
    TimestampField("web_admin_sessions", "expires_at", "instant", "BSON Date + TTL", "UTC", ("Auth", "Security Center"), "legacy ISO migration already idempotent"),
    TimestampField("wa_api_metrics", "at", "technical", "BSON Date + TTL", "UTC", ("Observability"), "already canonical"),
    TimestampField("wa_saved_filters", "updated_at", "instant", "UTC aware ISO", "UTC", ("WebAdmin"), "canonical for new writes"),
    TimestampField("bot_settings", "auto_backup_last_run", "instant", "UTC aware ISO", "UTC", ("Bot", "Settings", "System"), "canonical for new writes; audit legacy strings"),
)


# Additional persisted fields found by static source tracing. Their exact
# production type/null ratios remain deliberately unresolved until --all runs.
_EXTRA_INSTANTS = {
    "users": ("blocked_at", "blocked_bot_at", "resource_notif_last_sent", "challenge.last_fail_at"),
    "bs_lessons": ("created_at", "updated_at"),
    "bs_sessions": ("created_at", "updated_at"),
    "bs_content": ("created_at", "uploaded_at", "last_edited_at"),
    "ref_subjects": ("created_at", "updated_at"),
    "ref_books": ("created_at", "updated_at"),
    "ref_files": ("created_at", "uploaded_at", "updated_at"),
    "faq": ("created_at", "updated_at"),
    "tickets": ("replies.at", "user_seen_at"),
    "content_reports": ("created_at", "resolved_at"),
    "user_notifications": ("read_at",),
    "bot_notifications": ("sent_at",),
    "notif_runs": ("updated_at",),
    "broadcast_campaigns": ("updated_at", "sent_at"),
    "prestige_history": ("updated_at",),
    "feed_reactions": ("at",),
    "exam_sessions": ("finished_at", "updated_at"),
    "blacklist": ("blocked_at",),
    "admin_roles": ("created_at", "updated_at"),
    "roles": ("created_at", "updated_at"),
    "user_roles": ("added_at", "updated_at"),
    "perm_catalog": ("created_at", "updated_at"),
    "migrations": ("first_run_at", "last_run_at"),
    "web_admin_otps": ("created_at", "expires_at"),
    "web_admin_sessions": ("revoked_at",),
    "wa_saved_filters": ("last_opened_at",),
    "settings_meta": ("updated_at",),
    "sub_plans": ("created_at", "updated_at"),
    "subscriptions": ("updated_at", "revoked_at"),
    "sub_payments": ("created_at", "updated_at"),
    "discount_broadcasts": ("created_at", "updated_at", "soldout_at"),
    "ai_reports": ("updated_at",),
    "ai_conversations": ("updated_at", "items.at"),
}
_EXTRA_DATE_ONLY = {
    "users": ("ai_usage_date", "last_active_day", "last_gain_at", "shield_until", "challenge.cooldown_until", "records.top_rank_at"),
}
FIELDS += tuple(
    TimestampField(collection, field, "instant", "static source evidence; runtime type audit required",
                   "UTC for new writes; legacy sample required", ("Backend", "Bot/API/WebAdmin as applicable"),
                   "AMBIGUOUS until production type/null/sample audit")
    for collection, fields in _EXTRA_INSTANTS.items() for field in fields
)
FIELDS += tuple(
    TimestampField(collection, field, "date_only", "Gregorian YYYY-MM-DD business key",
                   "Tehran civil day", ("Prestige", "Analytics", "AI quota"),
                   "keep date-only; validate runtime values")
    for collection, fields in _EXTRA_DATE_ONLY.items() for field in fields
)


def inventory() -> list[dict]:
    return [asdict(item) for item in FIELDS]


def _path_value(document: dict, dotted: str):
    value = document
    for part in dotted.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list):
            value = [item.get(part) for item in value if isinstance(item, dict)]
        else:
            return None
    return value


async def inspect_collection(database, collection_name: str) -> dict:
    fields = [item for item in FIELDS if item.collection == collection_name]
    if not fields:
        raise ValueError("unknown_collection")
    collection = database[collection_name]
    total = await collection.count_documents({})
    result = {"collection": collection_name, "count": total, "fields": []}
    for spec in fields:
        rows = await collection.aggregate([
            {"$group": {"_id": {"$type": f"${spec.field}"}, "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]).to_list(20)
        sample = await collection.find(
            {spec.field: {"$exists": True, "$ne": None}}, {spec.field: 1}
        ).limit(3).to_list(3)
        result["fields"].append({
            **asdict(spec), "types": {str(row.get("_id")): int(row.get("count") or 0) for row in rows},
            "samples": [str(_path_value(row, spec.field))[:120] for row in sample],
        })
    return result


async def _main(args):
    from database import db
    database = db.client["medicalbot"]
    names = sorted({item.collection for item in FIELDS}) if args.all else [args.collection]
    output = [await inspect_collection(database, name) for name in names]
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read-only HUMSYAR timestamp audit")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--collection", choices=sorted({item.collection for item in FIELDS}))
    group.add_argument("--all", action="store_true")
    asyncio.run(_main(parser.parse_args()))
