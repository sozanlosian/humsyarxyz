"""💍 Ring Street — رجیستری گفت‌وگو در RAM (§۴۲/§۴۳)

قاعده: **Mongo منبع حقیقت است، RAM فقط کش.** اما روتر پیام‌های متنی
باید *سمک* و O(1) تصمیم بگیرد که «این پیام کاربر به پارتنرش رله شود یا
به مسیریاب همیشگی ربات؟» — پس این رجیستری نگه داشته می‌شود و در
`post_init` از دیتابیس بازسازی می‌گردد؛ یعنی ری‌استارت ربات (deploy،
restart، کرش) هیچ session فعالی را گم نمی‌کند و هیچ کاربری «گیر در
چت» نمی‌ماند.

فیلدهای هر entry فقط شناسه‌های لازم برای رله‌اند: هیچ متن/فایلی اینجا
ذخیره نمی‌شود.
"""
from __future__ import annotations

import logging

from ring import models as M

logger = logging.getLogger(__name__)

_CHATS: dict[int, dict] = {}        # uid -> {sid, peer, alias, mode}
_LOCK_NOTE: dict[int, str] = {}     # uid -> پیام‌های یک‌باره‌ی safety (idempotent)


def attach(uid_a: int, uid_b: int, session_id: str, mode: str,
           alias_a: str = "", alias_b: str = "") -> None:
    a, b = int(uid_a), int(uid_b)
    _CHATS[a] = {"sid": session_id, "peer": b, "alias": alias_a or "شما", "mode": mode}
    _CHATS[b] = {"sid": session_id, "peer": a, "alias": alias_b or "شما", "mode": mode}


def detach(uid: int) -> dict | None:
    return _CHATS.pop(int(uid), None)


def detach_session(session_id: str) -> list[int]:
    gone = []
    for uid in [u for u, e in _CHATS.items() if e.get("sid") == session_id]:
        _CHATS.pop(uid, None)
        gone.append(uid)
    return gone


def get(uid: int) -> dict | None:
    return _CHATS.get(int(uid))


def in_chat(uid: int) -> bool:
    return int(uid) in _CHATS


def uids() -> list[int]:
    return list(_CHATS.keys())


def count() -> int:
    return len(_CHATS) // 2


def snapshot() -> list[dict]:
    out, seen = [], set()
    for uid, e in _CHATS.items():
        if e["sid"] in seen:
            continue
        seen.add(e["sid"])
        out.append({"session_id": e["sid"], "mode": e.get("mode"),
                    "users": sorted([uid, e["peer"]])})
    return out


def clear() -> None:
    """فقط برای تست/تاریک‌سازی (§۷۶)."""
    _CHATS.clear()
    _LOCK_NOTE.clear()


async def load_from_db(mark=None) -> dict:
    """بازسازی RAM از sessionهای فعال + flowهای متنی معلق. بی‌خطر اگر خالی باشد.

    `mark(uid, field)` توسط `ring.handlers.flow_mark` داده می‌شود تا
    import-cycle ساخته نشود."""
    from database import db
    loaded = dropped = 0
    try:
        rows = await db.ring_cols.sessions.find({"status": "active"}).to_list(2000)
    except Exception as e:
        logger.warning("ring recovery ناتمام ماند: %s", e)
        return {"loaded": 0, "dropped": 0, "error": str(e)}
    for s in rows:
        slots = s.get("slots") or []
        if len(slots) != 2:
            await db.ring_session_end(s["session_id"], "reconcile_malformed", None)
            dropped += 1
            continue
        a, b = int(slots[0]), int(slots[1])
        prof_a = await db.ring_profile(a)
        prof_b = await db.ring_profile(b)
        attach(a, b, s["session_id"], s.get("mode", "fun"),
               (prof_a or {}).get("session_alias", "") or f"#{a % 10000:04d}",
               (prof_b or {}).get("session_alias", "") or f"#{b % 10000:04d}")
        loaded += 1
    flows = 0
    if mark is not None:
        try:
            cur = db.ring_cols.profiles.find(
                {"state": {"$in": [M.PROFILE, M.REPORT_WHY]}},
                {"state": 1, "pending_field": 1}).limit(2000)
            async for p in cur:
                fld = p.get("pending_field") or ("report" if p.get("state") == M.REPORT_WHY else None)
                if fld:
                    mark(int(p["_id"]), fld)
                    flows += 1
        except Exception as e:
            logger.debug("ring flow recovery skipped: %s", e)
    if loaded or flows:
        logger.info("💍 رینگ استریت: %d گفت‌وگو و %d flow از دیتابیس بازیابی شد", loaded, flows)
    return {"loaded": loaded, "dropped": dropped, "flows": flows}


def drop_staleuids(valid_sids: set[str]) -> int:
    """اگر session در DB بسته شده ولی entry جا مانده، پاکش کن (idempotent)."""
    n = 0
    for uid, e in list(_CHATS.items()):
        if e.get("sid") not in valid_sids:
            _CHATS.pop(uid, None)
            n += 1
    return n
