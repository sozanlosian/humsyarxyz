# -*- coding: utf-8 -*-
"""
📝 هسته — Audit واحد
"""
from database import db

async def log_action(actor_id: int, actor_name: str, actor_role: str, action: str, module: str = "Core", **kw):
    return await db.log_action(actor_id, actor_name, actor_role, action, module, **kw)
