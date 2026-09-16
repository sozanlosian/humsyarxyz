"""Operator CLI for guarded, reversible Question Bank migration."""
import argparse
import asyncio
import json
from pathlib import Path


async def main(args):
    from database import db
    from question_bank.migration import (
        inspect_questions, migrate_questions, backfill_progress, rollback_questions,
        rollback_progress,
    )
    if args.action == "inspect":
        result = await inspect_questions(db)
        if args.output:
            path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            result["report_file"] = str(path)
    elif args.action == "schema":
        expected = None
        if args.apply:
            if not args.inspection_file or not args.backup_manifest:
                raise RuntimeError("--inspection-file and --backup-manifest are required with --apply")
            inspection = json.loads(Path(args.inspection_file).read_text(encoding="utf-8"))
            expected = int(inspection["total"])
            if not Path(args.backup_manifest).is_file():
                raise RuntimeError("backup manifest does not exist")
        result = await migrate_questions(db, apply=args.apply, expected_total=expected,
                                         limit=args.limit or 100000)
    elif args.action == "progress":
        result = await backfill_progress(db, apply=args.apply, limit=args.limit or 1000000)
    elif args.action == "rollback":
        result = await rollback_questions(
            db, migration=args.migration, apply=args.apply,
            expected_count=args.confirmed_backup_count if args.apply else None)
    else:
        result = await rollback_progress(
            db, apply=args.apply,
            expected_count=args.confirmed_backup_count if args.apply else None)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HUMSYAR Question Bank migration (dry-run by default)")
    parser.add_argument("action", choices=["inspect", "schema", "progress", "rollback", "rollback-progress"])
    parser.add_argument("--apply", action="store_true", help="Apply guarded writes; default is read-only")
    parser.add_argument("--output", help="Write inspection JSON")
    parser.add_argument("--inspection-file", help="Previously reviewed inspect JSON; required for schema --apply")
    parser.add_argument("--backup-manifest", help="Existing full-backup manifest; required for schema --apply")
    parser.add_argument("--migration", default="question_bank_v2_schema_1")
    parser.add_argument("--limit", type=int, help="Optional safety cap (schema default 100k; progress 1m)")
    parser.add_argument("--confirmed-backup-count", type=int)
    asyncio.run(main(parser.parse_args()))
