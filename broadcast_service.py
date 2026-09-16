"""📢 Broadcast Control Plane مشترک Telegram Bot و WebAdmin.

این ماژول تنها منبع payload، audience resolution، campaign persistence،
schedule/cancel/history و renderer تلگرام است. UIها فقط client هستند.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
from bson import ObjectId

from database import db
from api.telegram_send import API_BASE, BOT_TOKEN
from time_utils import now_utc, parse_machine_datetime, utc_now_iso

MESSAGE_TYPES = {"text", "photo", "video", "document", "voice", "audio"}
MEDIA_METHOD = {
    "photo": ("sendPhoto", "photo"),
    "video": ("sendVideo", "video"),
    "document": ("sendDocument", "document"),
    "voice": ("sendVoice", "voice"),
    "audio": ("sendAudio", "audio"),
}


def now_iso() -> str:
    return utc_now_iso()


def campaign_id(value: Any) -> str:
    return str(value or "")


def normalize_payload(payload: dict) -> dict:
    p = dict(payload or {})
    kind = str(p.get("type") or "text")
    if kind not in MESSAGE_TYPES:
        raise ValueError("unsupported_message_type")
    if kind == "text":
        text = str(p.get("text") or "").strip()
        if len(text) < 5 or len(text) > 4096:
            raise ValueError("invalid_text_length")
        return {"type": "text", "text": text}
    file_id = str(p.get("file_id") or "").strip()
    if not file_id:
        raise ValueError("media_file_id_required")
    caption = str(p.get("caption") or "").strip()
    if len(caption) > 1024:
        raise ValueError("caption_too_long")
    return {"type": kind, "file_id": file_id, "caption": caption}


def legacy_target_to_dict(target: str | dict) -> dict:
    if isinstance(target, dict):
        return dict(target)
    value = str(target or "all")
    if value == "all": return {"scope": "all"}
    if value in ("g1", "g2"):
        return {"scope": "group", "group": value[-1]}
    if value.startswith("intake_"):
        rest = value[7:]
        if rest.endswith("_g1") or rest.endswith("_g2"):
            return {"scope": "intake_group", "intake": rest[:-3], "group": rest[-1]}
        return {"scope": "intake", "intake": rest}
    return {"scope": "all"}


async def resolve_recipients(target: str | dict, actor_id: int | None = None,
                             database=None) -> list[dict]:
    """Audience resolver واحد برای Bot/Web؛ فقط کاربران تأییدشده."""
    store = database or db
    target = legacy_target_to_dict(target)
    scope = target.get("scope") or "all"
    if scope == "saved_segment":
        raw_id = str(target.get("saved_segment_id") or "")
        try: oid = ObjectId(raw_id)
        except Exception: raise ValueError("saved_segment_not_found")
        saved = await store.wa_saved_filters.find_one({"_id": oid, "scope": "broadcast_segment"})
        if not saved or not (saved.get("shared") or saved.get("owner") == actor_id):
            raise ValueError("saved_segment_not_found")
        return await resolve_recipients(saved.get("filters") or {"scope": "all"}, actor_id, store)

    users = await store.all_users(approved_only=True)
    if scope == "intake":
        intake = str(target.get("intake") or "")
        if not intake: raise ValueError("intake_required")
        users = [u for u in users if u.get("intake") == intake]
    elif scope == "group":
        group = store.normalize_group(target.get("group"))
        if not group: raise ValueError("group_required")
        users = [u for u in users if store.normalize_group(u.get("group")) == group]
    elif scope == "intake_group":
        intake = str(target.get("intake") or "")
        group = store.normalize_group(target.get("group"))
        if not intake or not group: raise ValueError("intake_and_group_required")
        users = [u for u in users if u.get("intake") == intake and store.normalize_group(u.get("group")) == group]
    elif scope == "role":
        role = str(target.get("role") or "")
        if not role: raise ValueError("role_required")
        allowed = set(await store.user_ids_by_role(role, limit=100000))
        users = [u for u in users if u.get("user_id") in allowed]
    elif scope == "subscription":
        status = str(target.get("subscription_status") or "")
        now = now_utc()
        if status == "active":
            ids = await store.subscriptions.distinct("_id", {"status": "active", "end_date": {"$gte": now.isoformat()}})
        elif status == "expiring_7":
            ids = await store.subscriptions.distinct("_id", {"status": "active", "end_date": {"$gte": now.isoformat(), "$lte": (now + timedelta(days=7)).isoformat()}})
        elif status == "inactive":
            active = set(await store.subscriptions.distinct("_id", {"status": "active", "end_date": {"$gte": now.isoformat()}}))
            ids = [u.get("user_id") for u in users if u.get("user_id") not in active]
        else: raise ValueError("subscription_status_required")
        allowed = set(ids); users = [u for u in users if u.get("user_id") in allowed]
    elif scope != "all":
        raise ValueError("unsupported_audience")
    owner = int(__import__("os").getenv("ADMIN_ID", "0") or 0)
    return [u for u in users if u.get("user_id") and u.get("user_id") != owner]


async def preview(target: str | dict, actor_id: int | None = None) -> dict:
    users = await resolve_recipients(target, actor_id)
    return {"recipient_count": len(users), "audience": legacy_target_to_dict(target)}


async def create_campaign(*, payload: dict, target: str | dict, created_by: int,
                          created_by_name: str = "", source: str = "web",
                          send_at: str | None = None, correlation_id: str | None = None,
                          enqueue: bool = True) -> dict:
    payload = normalize_payload(payload)
    audience = legacy_target_to_dict(target)
    users = await resolve_recipients(audience, created_by)
    now = now_iso()
    if send_at:
        try:
            if parse_machine_datetime(send_at) <= now_utc():
                raise ValueError("send_at_must_be_future")
        except ValueError as exc:
            if str(exc) == "send_at_must_be_future": raise
            raise ValueError("invalid_send_at")
    doc = {
        "created_by": created_by, "created_by_name": created_by_name,
        "source": source, "message_type": payload["type"], "payload": payload,
        "audience": audience, "send_at": send_at, "status": "scheduled" if send_at else "queued",
        "created_at": now, "updated_at": now, "started_at": None, "finished_at": None,
        "total": len(users), "success": 0, "failed": 0, "skipped": 0,
        "correlation_id": correlation_id,
    }
    inserted = await db.broadcast_campaigns.insert_one(doc)
    cid = str(inserted.inserted_id)
    if enqueue and users:
        base = {"type": "broadcast", "campaign_id": cid, "message_type": payload["type"],
                "payload": payload, "text": payload.get("text") or payload.get("caption") or "[media]",
                "sent": False, "created_at": now, "send_at": send_at,
                "correlation_id": correlation_id, "audience": audience}
        for start in range(0, len(users), 1000):
            await db.bot_notifs.insert_many([{**base, "chat_id": u["user_id"],
                                               "inbox_mirrored": False}
                                              for u in users[start:start + 1000]])
        # Inbox mirror در زمان اجرای واقعی outbox انجام می‌شود؛ کمپین
        # زمان‌دارِ لغوشده نباید پیش از موعد در Mini App دیده شود.
    if not users:
        await db.broadcast_campaigns.update_one({"_id": inserted.inserted_id}, {"$set": {"status": "completed", "finished_at": now, "updated_at": now}})
        doc["status"] = "completed"
    return {"campaign_id": cid, "recipient_count": len(users), "status": doc["status"],
            "payload": payload, "audience": audience, "send_at": send_at}


async def send_payload(bot, chat_id: int, payload: dict):
    """Renderer واحد test، Bot direct و outbox."""
    p = normalize_payload(payload)
    kind = p["type"]
    if kind == "text":
        return await bot.send_message(chat_id, p["text"], parse_mode="HTML")
    kwargs = {"chat_id": chat_id, MEDIA_METHOD[kind][1]: p["file_id"]}
    if p.get("caption"): kwargs.update({"caption": p["caption"], "parse_mode": "HTML"})
    return await getattr(bot, MEDIA_METHOD[kind][0].replace("send", "send_").lower())(**kwargs)


async def send_payload_http(chat_id: int, payload: dict) -> dict:
    """همان normalize/payload برای test-send وب، از Telegram HTTP transport — با shared client + bounded retry."""
    p = normalize_payload(payload)
    if not BOT_TOKEN:
        raise RuntimeError("telegram_not_configured")
    if p["type"] == "text":
        method, body = "sendMessage", {"chat_id": chat_id, "text": p["text"], "parse_mode": "HTML"}
    else:
        method, field = MEDIA_METHOD[p["type"]]
        body = {"chat_id": chat_id, field: p["file_id"]}
        if p.get("caption"): body.update({"caption": p["caption"], "parse_mode": "HTML"})
    from http_client import telegram_post, _timeout
    import httpx
    # reuse shared client; per-call timeout 30s
    resp = await telegram_post(f"{API_BASE}/{method}", json=body, timeout=_timeout(httpx.Timeout(15, read=30)))
    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.status_code != 200 or not data.get("ok"):
        raise RuntimeError("telegram_test_send_failed")
    return {"ok": True, "message_id": (data.get("result") or {}).get("message_id")}


async def upload_media(chat_id: int, kind: str, filename: str, raw: bytes, mime: str) -> str:
    if kind not in MEDIA_METHOD or not BOT_TOKEN:
        raise ValueError("unsupported_media_type")
    method, field = MEDIA_METHOD[kind]
    from http_client import telegram_post, _timeout
    import httpx
    resp = await telegram_post(f"{API_BASE}/{method}",
        data={"chat_id": chat_id, "disable_notification": True},
        files={field: (filename, raw, mime or "application/octet-stream")},
        timeout=_timeout(httpx.Timeout(connect=15, read=180, write=300, pool=15)))
    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.status_code != 200 or not data.get("ok"):
        raise RuntimeError("telegram_media_upload_failed")
    result = data["result"]
    if kind == "photo": return result["photo"][-1]["file_id"]
    return result[field]["file_id"]


async def record_delivery(campaign: str, *, success: bool = False,
                          skipped: bool = False, error: str = "") -> None:
    try: oid = ObjectId(campaign)
    except Exception: return
    inc = {"success" if success else "skipped" if skipped else "failed": 1}
    update = {"$inc": inc, "$set": {"updated_at": now_iso(), "status": "running"}}
    if error:
        update["$push"] = {"failure_samples": {"$each": [
            {"error": str(error)[:200], "at": now_iso()}], "$slice": -100}}
    await db.broadcast_campaigns.update_one({"_id": oid}, update)


async def refresh_campaign(campaign: str) -> dict | None:
    try: oid = ObjectId(campaign)
    except Exception: return None
    doc = await db.broadcast_campaigns.find_one({"_id": oid})
    if not doc: return None
    pending = await db.bot_notifs.count_documents({"campaign_id": campaign, "sent": False})
    if not pending and doc.get("status") not in ("cancelled", "completed", "failed"):
        status = "completed" if not doc.get("failed") else "failed"
        await db.broadcast_campaigns.update_one({"_id": oid}, {"$set": {"status": status, "finished_at": now_iso(), "updated_at": now_iso()}})
        doc["status"] = status
    doc["pending"] = pending
    return doc


async def finish_direct(campaign: str, success: int, failed: int, skipped: int = 0) -> None:
    try: oid = ObjectId(campaign)
    except Exception: return
    await db.broadcast_campaigns.update_one({"_id": oid}, {"$set": {
        "success": int(success), "failed": int(failed), "skipped": int(skipped),
        "status": "completed" if not failed else "failed", "started_at": now_iso(),
        "finished_at": now_iso(), "updated_at": now_iso()}})


async def cancel(campaign: str) -> dict:
    """Soft-cancel قابل rollback؛ رکورد گیرنده برای audit/result حفظ می‌شود."""
    try: oid = ObjectId(campaign)
    except Exception: raise ValueError("campaign_not_found")
    doc = await db.broadcast_campaigns.find_one({"_id": oid})
    if not doc or doc.get("status") not in ("scheduled", "queued"):
        raise ValueError("campaign_not_cancellable")
    result = await db.bot_notifs.update_many(
        {"campaign_id": campaign, "sent": False},
        {"$set": {"sent": True, "cancelled": True, "skipped": True,
                  "sent_at": now_iso()}})
    count = int(getattr(result, "modified_count", 0))
    await db.broadcast_campaigns.update_one({"_id": oid}, {"$set": {
        "status": "cancelled", "finished_at": now_iso(), "updated_at": now_iso(),
        "skipped": count}})
    return {"cancelled": count, "previous_status": doc.get("status", "queued")}


async def rollback_cancel(campaign: str, previous_status: str) -> None:
    try: oid = ObjectId(campaign)
    except Exception: return
    await db.bot_notifs.update_many(
        {"campaign_id": campaign, "cancelled": True},
        {"$set": {"sent": False, "cancelled": False, "skipped": False},
         "$unset": {"sent_at": ""}})
    await db.broadcast_campaigns.update_one({"_id": oid}, {"$set": {
        "status": previous_status, "finished_at": None, "updated_at": now_iso(),
        "skipped": 0}})


def campaign_row(doc: dict) -> dict:
    return {"campaign_id": str(doc.get("_id", "")), "source": doc.get("source", ""),
        "message_type": doc.get("message_type", "text"), "payload": doc.get("payload") or {},
        "audience": doc.get("audience") or {}, "status": doc.get("status", ""),
        "created_by": doc.get("created_by"), "created_by_name": doc.get("created_by_name", ""),
        "created_at": doc.get("created_at", ""), "send_at": doc.get("send_at"),
        "started_at": doc.get("started_at"), "finished_at": doc.get("finished_at"),
        "total": int(doc.get("total") or 0), "success": int(doc.get("success") or 0),
        "failed": int(doc.get("failed") or 0), "skipped": int(doc.get("skipped") or 0),
        "correlation_id": doc.get("correlation_id")}
