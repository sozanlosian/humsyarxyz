"""Dashboard endpoints for the Telegram Mini App."""
import asyncio
from datetime import date
from typing import Any, Mapping, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import ADMIN_ID, get_current_user
from api.user_metrics import (
    non_negative_int,
    normalize_stats,
    normalize_weekly,
    same_user_id,
)
from api.rate_limit import rate_limit_user  # 🛡 W10/RATE-01
from database import db
from time_utils import parse_gregorian_date
from utils import now_tehran

router = APIRouter()


def _text(value: Any, default: str = "") -> str:
    return str(value).strip() if value is not None else default


def _exam_item(exam: Mapping[str, Any], today: date) -> dict:
    raw_date = _text(exam.get("date"))
    try:
        days_left = max(0, (parse_gregorian_date(raw_date) - today).days)
    except (TypeError, ValueError):
        days_left = None

    return {
        "id": _text(exam.get("_id")),
        "lesson": _text(exam.get("lesson")),
        "date": raw_date,
        "time": _text(exam.get("time")),
        "days_left": days_left,
    }


@router.get("")
async def get_dashboard(user=Depends(get_current_user)):
    uid = user["id"]
    db_user = user["_db"] if isinstance(user.get("_db"), Mapping) else {}
    group = _text(db_user.get("group"))

    raw_stats, raw_exams, raw_tickets, prestige = await asyncio.gather(
        db.user_stats(uid),
        db.upcoming_exams(7, group=group),
        db.ticket_get_user(uid),
        # 👑 موج P0 — بریف Prestige (افزایشی؛ هم‌شکل با /api/profile/prestige)
        db.prestige_state(uid),
    )

    stats = normalize_stats(raw_stats)
    stats["weak_topics"] = stats["weak_topics"][:3]
    exams = raw_exams if isinstance(raw_exams, list) else []
    tickets = raw_tickets if isinstance(raw_tickets, list) else []
    role = "admin" if uid == ADMIN_ID else _text(db_user.get("role"), "student")

    return {
        "user": {
            "name": _text(db_user.get("name")),
            # 🏷 Identity v1 (افزایشی)
            "nickname": db_user.get("nickname"),
            "display_name": db.display_name_of(db_user),
            "intake": _text(db_user.get("intake")),
            "group": group,
            "role": role or "student",
        },
        "stats": stats,
        "upcoming_exams": [
            _exam_item(exam, now_tehran().date())
            for exam in exams[:3]
            if isinstance(exam, Mapping)
        ],
        "open_tickets": sum(
            1
            for ticket in tickets
            if isinstance(ticket, Mapping) and ticket.get("status") == "open"
        ),
        "prestige": prestige,
    }


@router.get("/weekly")
async def weekly(user=Depends(get_current_user)):
    data = await db.weekly_activity(user["id"])
    return {"weekly": normalize_weekly(data)}


@router.get("/leaderboard")
async def leaderboard(
    range_: Optional[str] = None,
    scope: Optional[str] = None,
    tab: Optional[str] = None,
    limit: int = 50,
    user=Depends(get_current_user),
):
    await rate_limit_user(user["id"], "leaderboard", 60, 60)  # 🛡 W10

    # 👑 P2 — حالت توسعه‌یافته (با حتی یک پارامتر): ماتریس بازه×دامنه×تب.
    # بدون پارامتر: شکل legacy دست‌نخورده (قرارداد Dashboard FE قدیمی).
    if range_ is None and scope is None and tab is None:
        leaders = await db.get_leaderboard(10)
        uid = user["id"]
        result = []

        for item in leaders if isinstance(leaders, list) else []:
            if not isinstance(item, Mapping):
                continue
            total = non_negative_int(item.get("total_answers"))
            correct = non_negative_int(item.get("correct_answers"))
            percent = round(correct / total * 100) if total else 0
            result.append(
                {
                    "rank": len(result) + 1,
                    # 🏷 Identity v1 — سطح اجتماعی Leaderboard:
                    # display_name (بدون کوئری اضافه — سند کامل اینجاست)
                    "name": _text(
                        item.get("nickname") or item.get("name"),
                        "کاربر",
                    ) or "کاربر",
                    "correct": correct,
                    "total": total,
                    "percent": min(100, percent),
                    "is_me": same_user_id(item.get("user_id"), uid),
                }
            )

        return {"leaderboard": result}

    rng = (range_ or "week").strip()
    if rng not in ("week", "month", "all", "season"):
        rng = "week"
    scp = (scope or "all").strip()
    if scp not in ("all", "intake", "group"):
        scp = "all"
    tb = (tab or "xp").strip()
    if tb not in ("xp", "acc", "exam", "contrib"):
        tb = "xp"
    try:
        limit = max(1, min(int(limit or 50), 100))
    except Exception:
        limit = 50
    return await db.prestige_leaderboard(user["id"], rng, scp, tb, limit)


@router.get("/feed")
async def get_feed(
    limit: int = 5,
    user=Depends(get_current_user),
):
    """👑 P2 — فید رویدادهای عمومی (۴۸ ساعت، بدون کامنت — Spec §۶.۳)"""
    try:
        limit = max(1, min(int(limit), 10))
    except Exception:
        limit = 5
    return await db.prestige_feed(user["id"], limit)


class FeedReactInput(BaseModel):
    event_id: str
    kind: Optional[str] = None     # clap|fire|crown؛ None/همان‌واکنش ⇒ حذف


@router.post("/feed/react")
async def feed_react_ep(
    body: FeedReactInput,
    user=Depends(get_current_user),
):
    """👑 P2 — واکنش ناشناس به رویداد فید (تک‌واکنش قابل‌تعویض/حذف)"""
    kind = (body.kind or "").strip() or None
    if kind not in (None, "clap", "fire", "crown"):
        raise HTTPException(status_code=422, detail="واکنش نامعتبر")
    if not (body.event_id or "").strip():
        raise HTTPException(status_code=422, detail="رویداد نامعتبر")
    return await db.feed_react(user["id"], body.event_id.strip(), kind)
