"""Student grade endpoints for the Telegram Mini App."""

from fastapi import APIRouter, Depends, Query

from api.auth import get_current_user
from database import db
from grade_utils import summarize_grades_by_term


router = APIRouter()


@router.get("")
async def get_grades(
    # 🎓 ترم‌بندی — دانشجو می‌تواند کارنامه را به یک ترم محدود کند.
    # پیش‌فرض `None` است تا رفتار قبلی (همه‌ی ترم‌ها) دست‌نخورده بماند و
    # کلاینت‌های قدیمی نشکنند.
    term: str | None = Query(default=None, max_length=40),
    user=Depends(get_current_user),
):
    # همان نرمال‌سازی‌ای که پنل ادمین روی `term` انجام می‌دهد: مقدار به
    # کوئری Mongo می‌رسد، پس trim/کوتاه‌سازی اینجا هم لازم است.
    term = term.strip()[:40] if isinstance(term, str) and term.strip() else None

    records = await db.grade_list_for_student(
        user["id"],
        term=term,
    )

    if not isinstance(records, list):
        records = []

    # 🛡 AUDIT-§۸۲ — تفکیک ترم هم در همین بدنه می‌آید (کلیدهای قبلی دست‌نخورده)
    payload = summarize_grades_by_term(records)

    # فهرستِ ترم‌ها باید از *کل* نمرات دانشجو بیاید، نه از نتیجه‌ی فیلترشده؛
    # وگرنه با انتخاب «ترم ۲» بقیه‌ی تب‌ها ناپدید می‌شدند و کاربر راهی برای
    # برگشتن نداشت.
    payload["all_terms"] = await db.grade_terms_of_student(user["id"])
    payload["active_term"] = term or ""

    return payload
