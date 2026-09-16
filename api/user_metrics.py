"""Shared normalization helpers for user-facing API statistics."""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

from api.level import get_level


def non_negative_int(value: Any, default: int = 0) -> int:
    """Convert database values to a safe non-negative integer."""
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(0, number)


def safe_percentage(value: Any) -> float:
    """Return a finite percentage constrained to the 0..100 range."""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    if not math.isfinite(number):
        return 0
    return max(0, min(100, round(number, 1)))


def normalize_stats(raw: Mapping[str, Any] | None) -> dict:
    """Build the stable statistics contract consumed by the Mini App."""
    source = raw if isinstance(raw, Mapping) else {}
    total = non_negative_int(source.get("total_answers"))
    correct = non_negative_int(source.get("correct_answers"))

    # Keep percentage consistent with the displayed answer counters. The
    # database currently calculates it the same way, but old records can have
    # missing or malformed cached values.
    percentage = safe_percentage(correct / total * 100) if total else 0

    weak_topics = []
    seen = set()
    raw_topics = source.get("weak_topics")
    if isinstance(raw_topics, (list, tuple, set)):
        for item in raw_topics:
            if not isinstance(item, str):
                continue
            topic = item.strip()
            if topic and topic not in seen:
                seen.add(topic)
                weak_topics.append(topic)

    return {
        "downloads": non_negative_int(source.get("downloads")),
        "total_answers": total,
        "correct_answers": correct,
        "percentage": percentage,
        "week_activity": non_negative_int(source.get("week_activity")),
        "weak_topics": weak_topics,
        "level": get_level(percentage),
    }


def normalize_weekly(data: Iterable[Any] | None) -> list[dict]:
    """Serialize weekly activity tuples/dicts without trusting DB contents."""
    if not data:
        return []

    result = []
    for item in data:
        if isinstance(item, Mapping):
            date = item.get("date", "")
            count = item.get("count", 0)
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            date, count = item[0], item[1]
        else:
            continue
        result.append({"date": str(date or ""), "count": non_negative_int(count)})
    return result[:7]


def same_user_id(left: Any, right: Any) -> bool:
    """Compare Telegram IDs safely across legacy int/string records."""
    try:
        return int(left) == int(right)
    except (TypeError, ValueError, OverflowError):
        return False
