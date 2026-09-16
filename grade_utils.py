"""Shared grade normalization helpers."""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping


def safe_text(
    value: Any,
    default: str = "",
) -> str:
    if value is None:
        return default

    return str(value).strip()


def finite_number(
    value: Any,
) -> float | None:
    """Convert values to a finite number.

    Invalid, empty, infinite and boolean values
    return None and cannot crash calculations.
    """

    if (
        value is None
        or isinstance(value, bool)
    ):
        return None

    try:
        number = float(value)
    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None

    if not math.isfinite(number):
        return None

    return number


def display_number(
    value: float,
) -> int | float:
    """Remove unnecessary .0 from numbers."""

    rounded = round(value, 2)

    if rounded.is_integer():
        return int(rounded)

    return rounded


def normalize_grade(
    record: Mapping[str, Any] | None,
) -> dict | None:
    """Normalize one grade database record."""

    if not isinstance(record, Mapping):
        return None

    max_score = finite_number(
        record.get("max_score")
    )

    if (
        max_score is None
        or max_score <= 0
    ):
        max_score = 20.0

    score = finite_number(
        record.get("score")
    )

    if (
        score is not None
        and score < 0
    ):
        score = None

    if score is None:
        percentage = None
        normalized_score = None
        output_score = None

    else:
        raw_percentage = (
            score / max_score
        ) * 100

        percentage = round(
            max(
                0,
                min(
                    100,
                    raw_percentage,
                ),
            ),
            1,
        )

        raw_normalized = (
            score / max_score
        ) * 20

        normalized_score = round(
            max(
                0,
                min(
                    20,
                    raw_normalized,
                ),
            ),
            2,
        )

        output_score = display_number(
            score
        )

    exam_date = safe_text(
        record.get("exam_date")
    )

    if (
        len(exam_date) >= 10
        and exam_date[4:5] == "-"
        and exam_date[7:8] == "-"
    ):
        exam_date = exam_date[:10]

    return {
        "id": safe_text(
            record.get("_id")
        ),

        # 🛡 AUDIT-§۸۲ — ترم، بخشی از هویتِ نمره است (نمره‌ی ترم ۱ با ترم ۲
        # قاطی نشود); روی همه‌ی مسیرهای نمایش (پنل/مینی‌اپ/ربات) می‌رود.
        "term": safe_text(
            record.get("term")
        ),

        "lesson": safe_text(
            record.get("lesson")
        ),

        "exam_title": safe_text(
            record.get("exam_title")
        ),

        "score": output_score,

        "max_score": display_number(
            max_score
        ),

        "exam_date": exam_date,

        "note": safe_text(
            record.get("note")
        ),

        "percentage": percentage,

        "normalized_score":
            normalized_score,
    }


def summarize_grades(
    records: Iterable[Any] | None,
) -> dict:
    """Normalize grades and calculate average.

    The average:
    - ignores invalid and empty scores;
    - converts every grade to a score out of 20;
    - never divides by all rows when some grades
      are empty;
    - cannot crash on old malformed records.
    """

    grades = []
    normalized_scores = []

    if not records:
        records = []

    for record in records:
        grade = normalize_grade(record)

        if grade is None:
            continue

        grades.append(grade)

        normalized_score = grade.get(
            "normalized_score"
        )

        if normalized_score is not None:
            normalized_scores.append(
                normalized_score
            )

    graded_count = len(
        normalized_scores
    )

    if graded_count:
        average = round(
            sum(normalized_scores)
            / graded_count,
            2,
        )

        average_percentage = round(
            (average / 20) * 100,
            1,
        )

    else:
        average = None
        average_percentage = None

    for grade in grades:
        grade.pop(
            "normalized_score",
            None,
        )

    return {
        "grades": grades,
        "avg": average,

        "avg_percentage":
            average_percentage,

        "total": len(grades),

        "graded_count":
            graded_count,
    }


# ══════════════════════════════════════════════════════════════
#  §۸۲ — طبقه‌بندی نمرات به تفکیک ترم (ترم ۱ … ۵ جدا از هم)
# ══════════════════════════════════════════════════════════════

TERM_ORDER = ["ترم ۱", "ترم ۲", "ترم ۳", "ترم ۴", "ترم ۵", "ترم ۶", "ترم ۷", "ترم ۸"]


def _term_rank(term) -> int:
    """ترتیبِ ترم‌ها: همان ترتیبِ فهرست درسی؛ ناشناخته/خالی آخر."""
    t = safe_text(term)
    if t in TERM_ORDER:
        return TERM_ORDER.index(t)
    digits = "".join(ch for ch in t if ch.isdigit())
    if digits:
        return 100 + int(digits)
    return 10_000 if not t else 1_000


def term_label(term) -> str:
    t = safe_text(term)
    return t or "بدون ترم"


def group_grades_by_term(
    records: Iterable[Any] | None,
) -> list[dict]:
    """نمرات نرمال‌شده را به تفکیک ترم گروه می‌کند و میانگینِ هر ترم را می‌دهد.

    میانگین عمداً همان منطق `summarize_grades` است (نمره‌ی تهی/نامعتبر
    نادیده گرفته می‌شود، مخرج = تعدادِ نمره‌دارها) تا عددِ «میانگین ترم» با
    «میانگین کل» و با عددی که ربات نشان می‌دهد یکی باشد — نه فرمول دوم.
    """
    grouped: dict[str, list] = {}
    for record in (records or []):
        grade = normalize_grade(record)
        if grade is None:
            continue
        grouped.setdefault(safe_text(record.get("term") if isinstance(record, Mapping) else ""), []).append(grade)

    out = []
    for term in sorted(grouped, key=_term_rank):
        grades = grouped[term]
        scored = [g["normalized_score"] for g in grades if g.get("normalized_score") is not None]
        for g in grades:
            g.pop("normalized_score", None)
        out.append({
            "term": term or "",
            "label": term_label(term),
            "total": len(grades),
            "graded_count": len(scored),
            "avg": round(sum(scored) / len(scored), 2) if scored else None,
            "grades": grades,
        })
    return out


def summarize_grades_by_term(
    records: Iterable[Any] | None,
) -> dict:
    """همان خلاصه‌ی کلی + تفکیک ترم‌به‌ترم (منبعِ یکتای API مینی‌اپ و پنل)."""
    summary = summarize_grades(records)
    by_term = group_grades_by_term(records)
    return {
        **summary,
        "by_term": [{k: v for k, v in g.items() if k != "grades"} for g in by_term],
        "terms": [g["term"] for g in by_term if g["term"]],
    }
