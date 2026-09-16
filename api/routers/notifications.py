"""🔔 Notifications — ترجیحات کاربر + مرکز اعلان (Inbox)"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Dict, List, Optional
from api.auth import get_current_user
from database import db
from request_context import current_request_id

async def _notif_audit(actor: dict, action: str, *, before=None, after=None):
    try:
        db_user = actor.get("_db") if isinstance(actor.get("_db"), dict) else {}
        name = (db_user.get("name") or actor.get("name") or str(actor.get("id") or ""))
        try:
            role_label = await db.get_actor_role_label(actor["id"])
        except Exception:
            role_label = "student"
        await db.log_action(
            actor["id"], name, role_label,
            action, "Notifications", category="notification", severity="INFO",
            target_id=str(actor["id"]), target_type="user", target_label=name,
            before=before, after=after,
        )
    except Exception:
        pass

router = APIRouter()

# ══════════════════════════════════════════════════
#  🎚 ترجیحات اعلان — 🧠 موج N3: کاتالوگ یکپارچه
#  منبع لیست دسته‌ها دیگر این فایل نیست؛ db.notif_catalog()
#  تک‌منبعِ API/BAT است. کلیدهای قدیمی از طریق PREF_ALIAS
#  به Canonical ترجمه می‌شوند (سازگاری سندهای کهنه).
# ══════════════════════════════════════════════════

@router.get("/settings")
async def get_settings(user=Depends(get_current_user)):
    s = (user["_db"].get("notification_settings") or {})
    cat = await db.notif_catalog()
    return {"settings": [
        {"key": c["key"], "label": c["label"], "desc": c["desc"],
         "enabled": db.notif_pref_on(s, c["key"])}
        for c in cat
    ]}


class Toggle(BaseModel):
    settings: Dict[str, bool]

@router.patch("/settings")
async def update(body: Toggle, user=Depends(get_current_user)):
    # 🧠 N3 — accept old keys too؛ canonical می‌شوند (بدون مهاجرت دستی)
    valid = {k for k, _, _, _ in db.NOTIF_CATALOG}
    updates = {}
    for k, v in body.settings.items():
        canon = db.PREF_ALIAS.get(k, k)
        if canon and canon in valid:
            updates[f"notification_settings.{canon}"] = bool(v)
    if updates:
        await db.update_user(user["id"], updates)
        await _notif_audit(user, "ویرایش تنظیمات اعلان", after={"keys": list(updates.keys())[:5]})
    return {"ok": True}


class ToggleAll(BaseModel):
    enabled: bool

@router.patch("/settings/all")
async def toggle_all(body: ToggleAll, user=Depends(get_current_user)):
    updates = {f"notification_settings.{k}": body.enabled
               for k, _, _, _ in db.NOTIF_CATALOG}
    await db.update_user(user["id"], updates)
    await _notif_audit(user, "ویرایش کلی تنظیمات اعلان", after={"enabled": bool(body.enabled)})
    return {"ok": True, "enabled": body.enabled}


# ══════════════════════════════════════════════════
#  🔔 مرکز اعلان (inbox) — موج ۴.۹۰ + 🧠 N3 (فیلتر/pin/badge)
#  قرارداد پاسخ {items, unread} دست‌نخورده می‌ماند؛
#  پارامترها اختیاری‌اند (کلاینت فعلی بدون آن‌ها کار می‌کند).
# ══════════════════════════════════════════════════

@router.get("/inbox")
async def get_inbox(user=Depends(get_current_user),
                    category: Optional[str] = Query(None),
                    q: Optional[str] = Query(None),
                    unread: int = Query(0)):
    """فهرست اعلان‌ها + شمارش خوانده‌نشده (بج و صفحه یک پاسخ مشترک دارند)"""
    return await db.inbox_list(user["id"], limit=60,
                               category=category, q=q,
                               unread_only=bool(unread))


@router.get("/inbox/unread-count")
async def get_unread_count(user=Depends(get_current_user)):
    """🔢 بج سبک خوانده‌نشده — برای پول‌های دوره‌ای ارزان (بدون آیتم)"""
    return {"unread": await db.inbox_unread_count(user["id"])}


class InboxRead(BaseModel):
    # None → خواندن همه («خواندن همه» از کلاینت ids=null می‌فرستد؛
    # در pydantic v2 باید صراحتاً Optional باشد وگرنه 422 می‌شد)
    ids: Optional[List[str]] = None

@router.post("/inbox/read")
async def mark_read(body: InboxRead, user=Depends(get_current_user)):
    unread = await db.inbox_mark_read(user["id"], body.ids)
    return {"ok": True, "unread": unread}


class InboxPin(BaseModel):
    pinned: bool

@router.post("/inbox/{nid}/pin")
async def pin_one(nid: str, body: InboxPin, user=Depends(get_current_user)):
    """📌 سنجاق/برداشتن سنجاق — pin‌شده‌ها بالاتر و مصونِ هرس"""
    ok = await db.inbox_pin(user["id"], nid, body.pinned)
    if not ok:
        raise HTTPException(404, "اعلان پیدا نشد")
    return {"ok": True, "pinned": body.pinned}


@router.delete("/inbox/{nid}")
async def delete_inbox(nid: str, user=Depends(get_current_user)):
    ok = await db.inbox_delete(user["id"], nid)
    if not ok:
        raise HTTPException(404, "اعلان پیدا نشد")
    return {"ok": True, "unread": await db.inbox_unread_count(user["id"])}
