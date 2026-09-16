"""Canonical contracts for the shared Question Bank domain."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

QUESTION_STATUSES = frozenset({"pending", "approved", "rejected", "needs_changes"})
QUESTION_SOURCES = frozenset({
    "student_bot", "student_webapp", "admin_bot", "web_admin",
    "ai_student", "ai_admin_import", "system",
})
CREATOR_TYPES = frozenset({"student", "admin", "ai", "system"})
DIFFICULTY_LABELS = {
    "easy": "آسان 🟢", "medium": "متوسط 🟡", "hard": "سخت 🔴",
}
_DIFFICULTY_ALIASES = {
    "easy": "easy", "آسان": "easy", "آسان 🟢": "easy",
    "medium": "medium", "متوسط": "medium", "متوسط 🟡": "medium",
    "hard": "hard", "سخت": "hard", "سخت 🔴": "hard",
}
_SOURCE_ALIASES = {
    "webapp": "student_webapp", "web_import": "web_admin", "user": "student_bot",
    "bot": "admin_bot",
}


@dataclass
class QuestionDomainError(ValueError):
    code: str
    message: str
    status_code: int = 422
    details: dict | None = None

    def __str__(self) -> str:
        return self.message


def clean_text(value: Any, limit: int = 0) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit] if limit else text


def canonical_difficulty(value: Any, *, strict: bool = True) -> str:
    normalized = _DIFFICULTY_ALIASES.get(clean_text(value).lower())
    if normalized:
        return normalized
    if strict:
        raise QuestionDomainError("invalid_difficulty", "سطح سختی معتبر نیست")
    return "medium"


def canonical_status(document_or_value: Mapping | str | None) -> str:
    if isinstance(document_or_value, Mapping):
        status = clean_text(document_or_value.get("status"))
        if status in QUESTION_STATUSES:
            return status
        return "approved" if document_or_value.get("approved") else "pending"
    value = clean_text(document_or_value)
    return value if value in QUESTION_STATUSES else "pending"


def canonical_source(value: Any, creator_type: str = "student") -> str:
    value = clean_text(value)
    if value in QUESTION_SOURCES:
        return value
    if value in _SOURCE_ALIASES:
        return _SOURCE_ALIASES[value]
    return "system" if creator_type == "system" else "student_bot"


def approved_query() -> dict:
    """Read new status and legacy approved=True without a destructive migration."""
    return {"$or": [
        {"status": "approved"},
        {"status": {"$exists": False}, "approved": True},
    ]}


def status_query(status: str) -> dict:
    if status == "approved":
        return approved_query()
    if status == "pending":
        return {"$or": [
            {"status": "pending"},
            {"status": {"$exists": False}, "approved": {"$ne": True}},
        ]}
    return {"status": status}


def and_query(*parts: dict | None) -> dict:
    valid = [part for part in parts if part]
    if not valid:
        return {}
    if len(valid) == 1:
        return valid[0]
    return {"$and": valid}


def normalized_question_text(value: Any) -> str:
    text = clean_text(value).casefold()
    text = text.translate(str.maketrans("يىكۀة", "ییکهه"))
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def question_content_hash(question: Any, options: list[Any]) -> str:
    payload = {
        "question": normalized_question_text(question),
        "options": sorted(normalized_question_text(item) for item in options),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def validate_question_payload(payload: Mapping[str, Any]) -> dict:
    question = clean_text(payload.get("question"), 2000)
    if len(question) < 10:
        raise QuestionDomainError("question_too_short", "متن سؤال باید حداقل ۱۰ کاراکتر باشد")
    raw_options = payload.get("options")
    if not isinstance(raw_options, list) or len(raw_options) != 4:
        raise QuestionDomainError("four_options_required", "سؤال باید دقیقاً چهار گزینه داشته باشد")
    options = [clean_text(item, 500) for item in raw_options]
    if any(not item for item in options) or len({normalized_question_text(x) for x in options}) != 4:
        raise QuestionDomainError("unique_options_required", "چهار گزینه متفاوت و غیرخالی لازم است")
    try:
        correct = int(payload.get("correct_answer", payload.get("correct", payload.get("correct_option"))))
    except (TypeError, ValueError):
        raise QuestionDomainError("invalid_correct_option", "گزینه صحیح معتبر نیست")
    if not 0 <= correct < 4:
        raise QuestionDomainError("invalid_correct_option", "گزینه صحیح باید بین ۱ تا ۴ باشد")
    difficulty = canonical_difficulty(payload.get("difficulty") or "medium")
    return {
        "question": question,
        "options": options,
        "correct_answer": correct,
        "difficulty": difficulty,
        "explanation": clean_text(payload.get("explanation"), 4000),
        "content_hash": question_content_hash(question, options),
    }


def public_question(document: Mapping[str, Any], *, reveal: bool = False) -> dict:
    result = {
        "id": str(document.get("_id") or document.get("id") or ""),
        "lesson_id": str(document.get("lesson_id") or ""),
        "topic_id": str(document.get("topic_id") or ""),
        "lesson": clean_text(document.get("lesson")),
        "topic": clean_text(document.get("topic")),
        "difficulty": canonical_difficulty(document.get("difficulty"), strict=False),
        "difficulty_label": DIFFICULTY_LABELS[canonical_difficulty(document.get("difficulty"), strict=False)],
        "question": clean_text(document.get("question")),
        "options": [str(x) for x in (document.get("options") or [])],
        "source": canonical_source(document.get("source"), clean_text(document.get("creator_type"))),
        "creator_type": clean_text(document.get("creator_type")) or "student",
        "provenance": dict(document.get("provenance") or {}),
    }
    if reveal:
        result.update({
            "correct_answer": int(document.get("correct_answer", 0) or 0),
            "explanation": clean_text(document.get("explanation")),
        })
    return result
