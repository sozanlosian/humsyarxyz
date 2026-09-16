# -*- coding: utf-8 -*-
"""
📚 هسته — Content Scope واحد
"""
from database import db

async def is_content_admin(uid: int) -> bool:
    return bool(await db.is_content_admin(int(uid)))

async def get_content_scope(uid: int) -> dict:
    return await db.get_content_scope(int(uid)) or {"kind": "none"}

async def get_scoped_intake(uid: int):
    return await db.get_scoped_intake(int(uid))
