# -*- coding: utf-8 -*-
"""
🗄️ W3 — Migration runner (versioned, idempotent)

Each migration is a small async function; runner tracks `db_version` in settings (`_id: 'global'`).
Current version: 4
- v1: initial (legacy)
- v2: W1 security (init_nonces TTL) — already handled via ensure_indexes
- v3: W3 exam_sessions expires_at backfill + wallet/broadcast guards
- v4: W7 feature_policies seed (all FREE) + subscription_enforced migration

Run via `await run_migrations(db)` in lifespan / ensure_indexes.
Idempotent: re-running does nothing.
"""
import logging
from time_utils import utc_now_iso, parse_machine_datetime, now_utc

logger = logging.getLogger("database")
CURRENT_DB_VERSION = 4

async def _migrate_v3_exam_sessions(db):
    """Backfill expires_at for existing exam_sessions without it.
    - promotion/challenge: expires_at = now + CH_TTL_HOURS (from expires_ts)
    - normal exam: expires_at = deadline + 7 days, or started_at + 7 days if no deadline
    Uses bulk write in batches to avoid OOM.
    """
    from datetime import datetime, timedelta, timezone
    try:
        # Find sessions missing expires_at
        cursor = db.exam_sessions.find({"expires_at": {"$exists": False}})
        batch = []
        migrated = 0
        async for doc in cursor:
            try:
                expires_at = None
                if doc.get("promotion"):
                    ts = doc.get("expires_ts")
                    if ts:
                        expires_at = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                    else:
                        # fallback 48h from started_at
                        try:
                            sa = parse_machine_datetime(doc.get("started_at") or doc.get("created_at") or utc_now_iso())
                            expires_at = sa + timedelta(hours=48)
                        except:
                            expires_at = now_utc() + timedelta(hours=48)
                else:
                    dl = doc.get("deadline")
                    if dl:
                        try:
                            d = parse_machine_datetime(dl)
                            expires_at = d + timedelta(days=7)
                        except:
                            expires_at = now_utc() + timedelta(days=7)
                    else:
                        try:
                            sa = parse_machine_datetime(doc.get("started_at") or doc.get("created_at") or utc_now_iso())
                            expires_at = sa + timedelta(days=7)
                        except:
                            expires_at = now_utc() + timedelta(days=7)
                if expires_at:
                    batch.append((doc["_id"], expires_at))
                if len(batch) >= 500:
                    for _id, iso in batch:
                        await db.exam_sessions.update_one({"_id": _id}, {"$set": {"expires_at": iso}})
                    migrated += len(batch)
                    batch.clear()
            except Exception as e:
                logger.warning(f"migration v3 exam_sessions doc {doc.get('_id')} failed: {e}")
        if batch:
            for _id, iso in batch:
                await db.exam_sessions.update_one({"_id": _id}, {"$set": {"expires_at": iso}})
            migrated += len(batch)
        if migrated:
            logger.info(f"migration v3: backfilled expires_at for {migrated} exam_sessions")
        return migrated
    except Exception as e:
        logger.warning(f"migration v3 failed: {e}")
        return 0

async def _migrate_v4_feature_policies(db):
    """🌊 W7 — بذر پالیسی همه‌ی فیچرها (FREE/enabled) + مهاجرت سوییچ قدیمی.

    اگر subscription_enforced روشن بود، question_bank و resources و
    references به subscription می‌روند تا رفتار عیناً حفظ شود. idempotent.
    """
    try:
        from core.features import FEATURE_CATALOG, default_policy
    except ImportError as e:
        logger.warning(f"migration v4: catalog import failed: {e}")
        return 0
    try:
        enforced = await db.get_setting("subscription_enforced", False)
    except Exception:
        enforced = False
    n = 0
    for key in FEATURE_CATALOG:
        try:
            cur = await db.feature_policies.find_one({"_id": key})
            if cur:
                continue
            pol = default_policy(key)
            if enforced and key in ("question_bank", "resources",
                                    "references"):
                pol["access"] = "subscription"
                pol["note"] = "مهاجرت خودکار از subscription_enforced (v4)"
            pol["updated_at"] = utc_now_iso()
            await db.feature_policies.insert_one(pol)
            n += 1
        except Exception as e:
            logger.warning(f"migration v4 seed {key} failed: {e}")
    if n:
        logger.info(f"migration v4: seeded {n} feature policies "
                    f"(enforced_was={bool(enforced)})")
    return n


async def run_migrations(db):
    try:
        raw = await db.settings.find_one({"_id": "global"})
        cur = int((raw or {}).get("db_version", 1) or 1)
        if cur >= CURRENT_DB_VERSION:
            return {"migrated": False, "version": cur}
        logger.info(f"migrations: {cur} -> {CURRENT_DB_VERSION}")
        if cur < 3:
            await _migrate_v3_exam_sessions(db)
        if cur < 4:
            await _migrate_v4_feature_policies(db)
        await db.settings.update_one({"_id": "global"}, {"$set": {"db_version": CURRENT_DB_VERSION, "db_version_updated_at": utc_now_iso()}}, upsert=True)
        return {"migrated": True, "from": cur, "to": CURRENT_DB_VERSION}
    except Exception as e:
        logger.warning(f"run_migrations failed: {e}")
        return {"migrated": False, "error": str(e)}
