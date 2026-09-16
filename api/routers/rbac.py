"""🛡 RBAC Management API — موج W1 (Execution Contract 🔒)

تک‌منبع حقیقت نقش/مجوز: db.roles / db.user_roles / db.perm_catalog
(§۴ قرارداد — هیچ برچسب/رنگ/آیکون/کلیدی در این فایل هاردکد نیست؛
همه‌چیز از db می‌آید). همه‌ی جهش‌ها با Audit (module='Roles' +
before/after) ثبت می‌شوند (§گزارش‌دهی سند RBAC)."""
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import get_current_user, require_perm
from database import db

router = APIRouter()

# گیت‌های موج W1 — تصمیم فقط بر اساس Permission (نه role، نه ADMIN_ID
# مستقیم؛ بای‌پس مالک داخل db.has_perm است)
_roles_guard = Depends(require_perm("roles.manage"))
_users_guard = Depends(require_perm("users.manage"))

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


# ──────────────────────────────────────────
#  ابزار داخلی
# ──────────────────────────────────────────

async def _audit_rbac(actor: dict, action: str, target_label: str,
                      before: dict = None, after: dict = None,
                      severity: str = "WARNING", target_id: str = ""):
    """ثبت لاگ حساس برای همه‌ی تغییرات نقش (مدل غنی فعلی پروژه)."""
    uid = actor["id"]
    name = actor.get("first_name") or actor.get("username") or str(uid)
    role_label = await db.get_actor_role_label(uid) \
        if hasattr(db, "get_actor_role_label") else "مدیر"
    await db.log_action(
        uid, name, role_label, action,
        module="Roles", category="security", severity=severity,
        target_id=target_id, target_type="role",
        target_label=target_label, before=before, after=after,
        tags=["rbac"],
    )


def _role_view(doc: dict, users_count: int = 0) -> dict:
    return {
        "key":         doc["_id"],
        "label":       doc.get("label", doc["_id"]),
        "desc":        doc.get("desc", ""),
        "icon":        doc.get("icon", "🛡"),
        "color":       doc.get("color", "#70A7FF"),
        "priority":    doc.get("priority", 90),
        "system":      bool(doc.get("system")),
        "active":      bool(doc.get("active", True)),
        "visible":     bool(doc.get("visible", True)),
        "perms":       list(doc.get("perms") or []),
        "perm_count":  len(doc.get("perms") or []),
        "users_count": users_count,
        "created_at":  doc.get("created_at", ""),
        "updated_at":  doc.get("updated_at", ""),
    }


def _err(status: int, detail: str):
    raise HTTPException(status_code=status, detail=detail)


async def _compensate_or_fail(restore, message: str):
    try:
        await restore
    except Exception:
        raise HTTPException(500, "ثبت حسابرسی و بازگردانی RBAC هر دو ناموفق شدند")
    raise HTTPException(503, message)


# ──────────────────────────────────────────
#  رجیستری مجوزها (ماتریس دسته‌بندی‌شده)
# ──────────────────────────────────────────

@router.get("/permissions")
async def list_permissions(user=_roles_guard):
    """کاتالوگ کامل سوییچ‌های تکی — از کالکشن (نه ثابت کد)."""
    docs = await db.perm_catalog.find({}).to_list(1000)   # 🛡 AUDIT-V4 کرانه
    if not docs:  # fallback اضطراری قبل از اجرای seed
        docs = [{"_id": k, "label": l, "category": c}
                for k, l, c in db.PERMISSION_CATALOG]
    cats = [{"key": k, "label": l} for k, l in db.PERM_CATEGORIES]
    return {
        "categories": cats,
        "permissions": [
            {"key": d["_id"], "label": d.get("label", d["_id"]),
             "category": d.get("category", "system")}
            for d in sorted(docs, key=lambda d: (d.get("category", ""),
                                                 d.get("label", "")))
        ],
    }


# ──────────────────────────────────────────
#  CRUD نقش‌ها
# ──────────────────────────────────────────

@router.get("/roles")
async def list_roles(user=_roles_guard):
    roles = await db.list_roles()
    counts = await db.users_count_by_role()
    return {"roles": [_role_view(r, counts.get(r["_id"], 0))
                      for r in roles]}


class RoleCreate(BaseModel):
    key:      Optional[str] = None
    label:    str = Field(min_length=2, max_length=60)
    desc:     str = Field(default="", max_length=200)
    icon:     str = Field(default="🛡", max_length=4)
    color:    str = "#70A7FF"
    priority: int = Field(default=90, ge=1, le=999)
    perms:    List[str] = []


@router.post("/roles")
async def create_role(body: RoleCreate, user=_roles_guard):
    if body.key and not _KEY_RE.match(body.key):
        _err(422, "کلید نقش نامعتبر است (حروف کوچک/عدد/underline)")
    if not _COLOR_RE.match(body.color):
        _err(422, "فرمت رنگ نامعتبر است (مثل #70A7FF)")
    doc, err = await db.create_role(body.model_dump(), actor=user["id"])
    if err:
        _err(409 if err == "key_exists" else 422, err)
    try:
        await _audit_rbac(user, "ساخت نقش جدید", doc["label"],
                          after=_role_view(doc), target_id=doc["_id"])
    except Exception:
        await _compensate_or_fail(
            db.rbac_restore_role(doc["_id"], None),
            "ثبت حسابرسی ممکن نشد؛ ساخت نقش بازگردانده شد",
        )
    return {"ok": True, "role": _role_view(doc)}


class RolePatch(BaseModel):
    label:    Optional[str] = Field(default=None, min_length=2, max_length=60)
    desc:     Optional[str] = Field(default=None, max_length=200)
    icon:     Optional[str] = Field(default=None, max_length=4)
    color:    Optional[str] = None
    priority: Optional[int] = Field(default=None, ge=1, le=999)
    active:   Optional[bool] = None
    visible:  Optional[bool] = None
    perms:    Optional[List[str]] = None


@router.patch("/roles/{key}")
async def update_role(key: str, body: RolePatch, user=_roles_guard):
    old = await db.get_role(key)
    if not old:
        _err(404, "نقش پیدا نشد")
    changes = body.model_dump(exclude_none=True)
    if changes.get("color") and not _COLOR_RE.match(changes["color"]):
        _err(422, "فرمت رنگ نامعتبر است (مثل #70A7FF)")
    doc, err = await db.update_role(key, changes, actor=user["id"])
    if err:
        _err(422, err)
    try:
        await _audit_rbac(
            user, "ویرایش نقش", doc["label"],
            before={k: old.get(k) for k in changes},
            after={k: doc.get(k) for k in changes},
            target_id=key,
        )
    except Exception:
        await _compensate_or_fail(
            db.rbac_restore_role(key, old),
            "ثبت حسابرسی ممکن نشد؛ ویرایش نقش بازگردانده شد",
        )
    return {"ok": True, "role": _role_view(doc)}


@router.delete("/roles/{key}")
async def delete_role(key: str, user=_roles_guard):
    old = await db.get_role(key)
    label = old.get("label", key) if old else key
    ok, err, count = await db.delete_role(key)
    if not ok:
        if err == "not_found":
            _err(404, "نقش پیدا نشد")
        if err == "system_role":
            _err(409, "نقش سیستمی حذف‌ناپذیر است (فقط قابل ویرایش)")
        if err == "in_use":
            _err(409, f"این نقش به {count} کارگران وابسته است؛ ابتدا نقش را از آن‌ها بگیر")
    try:
        await _audit_rbac(user, "حذف نقش", label,
                          before=_role_view(old), severity="HIGH",
                          target_id=key)
    except Exception:
        await _compensate_or_fail(
            db.rbac_restore_role(key, old),
            "ثبت حسابرسی ممکن نشد؛ حذف نقش بازگردانده شد",
        )
    return {"ok": True}


# ──────────────────────────────────────────
#  تخصیص نقش به کاربر (چندنقشی)
# ──────────────────────────────────────────

async def _user_rbac_view(uid: int) -> dict:
    user = await db.get_user(uid)
    if not user:
        _err(404, "کاربر پیدا نشد")
    info = await db.get_user_roles(uid)
    perms = await db.get_user_perms(uid)
    return {
        "uid": uid,
        "roles": [_role_view(r) for r in info["roles"]],
        "keys": info["keys"],
        "scope_intake": info["scope_intake"],
        "perms": sorted(perms),
        "legacy_role": user.get("role", "student"),
    }


@router.get("/users/{uid}")
async def get_user_roles(uid: int, user=_users_guard):
    return await _user_rbac_view(uid)


class AssignBody(BaseModel):
    add:          List[str] = []
    remove:       List[str] = []
    scope_intake: Optional[str] = None


@router.post("/users/{uid}/roles")
async def assign_roles(uid: int, body: AssignBody, user=_users_guard):
    target = await db.get_user(uid)
    if not target:
        _err(404, "کاربر پیدا نشد")
    known = {r["_id"] for r in await db.list_roles()}
    for key in body.add:
        if key not in known:
            _err(422, f"نقش ناشناخته: {key}")
    before_info = await db.get_user_roles(uid)
    before = before_info["keys"]
    assignment_snapshot = await db.rbac_assignment_snapshot(uid)
    try:
        for key in body.add:
            await db._add_role_key(uid, key, body.scope_intake)
        for key in body.remove:
            await db._remove_role_key(uid, key)
        # RBAC-Execution: scope باید حتی بدون add/remove هم قابل ویرایش باشد.
        # رشته‌ی خالی یعنی پاک‌کردن scope؛ Noneِ ارسال‌نشده یعنی دست‌نخوردن.
        if "scope_intake" in body.model_fields_set:
            await db.user_roles.update_one(
                {"_id": uid},
                {"$set": {"scope_intake": body.scope_intake or None}},
                upsert=True,
            )
            await db._sync_admin_role_projection(uid)
        # §۵ Sync: آینه‌ی users.role هم همیشه یکدست می‌ماند
        await db.sync_legacy_role_mirror(uid)
        after_info = await db.get_user_roles(uid)
        after = after_info["keys"]
        await _audit_rbac(
            user, "تغییر نقش‌های کاربر",
            target.get("name", str(uid)),
            before={"roles": sorted(before), "scope_intake": before_info.get("scope_intake")},
            after={"roles": sorted(after), "scope_intake": after_info.get("scope_intake")},
            target_id=str(uid),
        )
    except Exception:
        await _compensate_or_fail(
            db.rbac_restore_assignment(uid, assignment_snapshot),
            "تغییر نقش کامل نشد؛ وضعیت پیشین بازگردانده شد",
        )
    return await _user_rbac_view(uid)
