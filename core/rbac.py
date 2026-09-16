# -*- coding: utf-8 -*-
"""
🛡️ هسته — RBAC واحد

قبل:  Bot با `db.has_permission` + رشته role، API با `_perm()` + decorator،
  MiniApp فقط `me.perms` را نمایش می‌داد — ماتریس مجوز در ۲ جا تعریف بود.

بعد:  همین ماژول thin-wrapper روی db/rbac است؛ هر لایه همین را صدا می‌زند.
"""
from typing import Set
from database import db
from .errors import Code

async def has_permission(uid: int, perm: str) -> bool:
    return bool(await db.has_permission(int(uid), perm))

async def get_user_perms(uid: int) -> Set[str]:
    return set(await db.get_user_perms(int(uid)))

async def require_perm(uid: int, perm: str):
    if not await has_permission(int(uid), perm):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail={"code": Code.PERMISSION_DENIED, "message": f"forbidden: {perm}"})

def perm_any(*perms: str):
    async def checker(uid: int) -> bool:
        for p in perms:
            if await has_permission(int(uid), p):
                return True
        return False
    return checker
