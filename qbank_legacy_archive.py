#!/usr/bin/env python3
"""Inspect/export/archive the retired qbank_files feature without dropping data.

Examples:
  python qbank_legacy_archive.py inspect
  python qbank_legacy_archive.py export --output backups/qbank-files.jsonl
  python qbank_legacy_archive.py archive --apply --confirmed-count 123 \
      --export-manifest backups/qbank-files.jsonl.manifest.json

There is deliberately no drop/delete command. Production removal requires a
separate, reviewed change after export checksum and archive count validation.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from bson import json_util
from time_utils import utc_now_iso

SOURCE = "qbank_files"
ARCHIVE = "qbank_files_archive_v1"


def collections():
    from database import db
    mongo = db.client["medicalbot"]
    return mongo[SOURCE], mongo[ARCHIVE]


async def inspect() -> dict:
    source, archive = collections()
    count = await source.count_documents({})
    archive_count = await archive.count_documents({})
    sample = await source.find({}, {"file_id": 0}).sort("_id", 1).limit(10).to_list(10)
    fields = sorted({key for row in sample for key in row})
    return {"source": SOURCE, "count": count, "archive": ARCHIVE,
            "archive_count": archive_count, "sample_size": len(sample),
            "sample_fields": fields, "checked_at": utc_now_iso(),
            "destructive_action": False}


async def export(output: Path) -> dict:
    source, _ = collections()
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0; digest = hashlib.sha256()
    with output.open("wb") as handle:
        async for document in source.find({}).sort("_id", 1):
            line = (json_util.dumps(document, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
            handle.write(line); digest.update(line); count += 1
    manifest = {"source": SOURCE, "count": count, "sha256": digest.hexdigest(),
                "file": str(output), "exported_at": utc_now_iso(),
                "format": "Mongo Extended JSON Lines", "destructive_action": False}
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**manifest, "manifest": str(manifest_path)}


async def archive(*, apply: bool, confirmed_count: int | None,
                  export_manifest: Path | None = None) -> dict:
    source, archived = collections()
    source_count = await source.count_documents({})
    if not apply:
        return {"dry_run": True, "source_count": source_count, "archive": ARCHIVE,
                "would_copy": source_count, "would_drop": False,
                "requires_export_manifest": True}
    if confirmed_count is None or int(confirmed_count) != source_count:
        raise RuntimeError(f"confirmed count mismatch: expected live count {source_count}")
    if not export_manifest or not export_manifest.is_file():
        raise RuntimeError("a verified --export-manifest is required before archive --apply")
    manifest = json.loads(export_manifest.read_text(encoding="utf-8"))
    export_file = Path(manifest.get("file") or "")
    if manifest.get("source") != SOURCE or int(manifest.get("count", -1)) != source_count or not export_file.is_file():
        raise RuntimeError("export manifest source/count/file validation failed")
    digest = hashlib.sha256(export_file.read_bytes()).hexdigest()
    if digest != manifest.get("sha256"):
        raise RuntimeError("export checksum validation failed")
    now = utc_now_iso()
    # Idempotent copy keyed by original _id. Existing archive rows are replaced
    # only with the same source row plus fresh archive metadata.
    pipeline = [
        {"$set": {"_archive": {"source": SOURCE, "archived_at": now, "schema": 1}}},
        {"$merge": {"into": ARCHIVE, "on": "_id", "whenMatched": "replace", "whenNotMatched": "insert"}},
    ]
    await source.aggregate(pipeline).to_list(1)
    archive_count = await archived.count_documents({})
    missing = await source.aggregate([
        {"$lookup": {"from": ARCHIVE, "localField": "_id", "foreignField": "_id", "as": "copy"}},
        {"$match": {"copy.0": {"$exists": False}}}, {"$count": "count"},
    ]).to_list(1)
    missing_count = int(missing[0]["count"]) if missing else 0
    if missing_count:
        raise RuntimeError(f"archive verification failed: {missing_count} source rows missing")
    return {"dry_run": False, "source_count": source_count, "archive_count": archive_count,
            "verified_missing": 0, "archived_at": now, "dropped": False,
            "next_step": "retain source until backup/export and production validation are signed off"}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["inspect", "export", "archive"])
    parser.add_argument("--output", default="backups/qbank-files.jsonl")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirmed-count", type=int)
    parser.add_argument("--export-manifest", help="Manifest produced by the export command")
    args = parser.parse_args()
    if args.command == "inspect": result = await inspect()
    elif args.command == "export": result = await export(Path(args.output))
    else: result = await archive(apply=args.apply, confirmed_count=args.confirmed_count,
                                 export_manifest=Path(args.export_manifest) if args.export_manifest else None)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
