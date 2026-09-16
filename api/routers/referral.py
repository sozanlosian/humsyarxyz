# -*- coding: utf-8 -*-
"""🌱 W13 — ریفرال کاربری: لینک و آمار «دعوت‌های من» برای مینی‌اپ.

با کلید خاموش فقط {"enabled": False} برمی‌گردد و فرانت چیزی نشان نمی‌دهد.
"""
import os

from fastapi import APIRouter, Depends

import growth_rules as gr
from api.auth import get_current_user
from api.rate_limit import rate_limit_dependency
from database import db

router = APIRouter()


@router.get(
    "/mine",
    dependencies=[
        Depends(rate_limit_dependency("referral_mine", 60, 60, by_user=True))
    ],
)
async def referral_mine(user=Depends(get_current_user)):
    uid = user["id"]
    cfg = gr.merge_ref_config(await db.get_setting("ref_cfg", None))
    if not cfg["enabled"]:
        return {"enabled": False}
    code = await db.ref_ensure_code(uid)
    link = gr.ref_link(os.environ.get("BOT_USERNAME") or "", code)
    stats = await db.ref_inviter_stats(uid)
    return {
        "enabled": True,
        "code": code,
        "link": link,
        "stats": stats,
        "timing": cfg["timing"],
        # فقط جایزه‌های روشن (مقدارها برای نمایش «با هر دعوت چی می‌گیری»)
        "rewards": {
            k: v for k, v in cfg["rewards"].items() if v.get("on")
        },
    }
