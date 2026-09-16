"""
🗄️ qbank.query — لایه‌ی Query و Randomizer

تنها ماژولی که با دیتابیس صحبت می‌کند. بقیه‌ی ماژول‌های qbank (کاور،
کارت سوال، پاسخنامه، توضیح تشریحی) فقط دیکشنری پایتون می‌بینند و هیچ
وابستگی‌ای به Mongo/Motor ندارند — یعنی تئوریاً می‌شود منبع داده را
بعداً عوض کرد بدون این‌که یک خط از منطق PDF عوض شود.
"""
import random
import string
from datetime import datetime
from dataclasses import dataclass, field
from time_utils import now_tehran


def generate_exam_code() -> str:
    """
    کد آزمون یکتا و کوتاه — روی جلد PDF چاپ می‌شود و به‌عنوان هوک آماده
    برای قابلیت‌های آینده (QR Code، ردیابی نسخه، جلوگیری از تقلب) هم
    قابل استفاده است.
    """
    ts = now_tehran().strftime('%y%m%d')
    rand = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"HYB-{ts}-{rand}"


@dataclass
class ExamMeta:
    """اطلاعات هدر/جلد آزمون — از منطق رسم PDF کاملاً جداست"""
    lesson: str
    chapter: str = None
    topic: str = None
    difficulty: str = None
    student_name: str = None
    exam_code: str = field(default_factory=generate_exam_code)
    version: int = 1
    with_answers: bool = True  # هوک آماده برای «نسخه‌ی بدون پاسخ»


async def fetch_exam_questions(db, lesson: str, chapter: str = None, topic: str = None,
                                difficulty: str = None, tags: list = None, count: int = 20,
                                randomize: bool = True, exclude_ids: list = None,
                                intake=None) -> list:
    """
    گرفتن سوالات از دیتابیس (لایه‌ی نازک روی db.get_exam_questions) +
    غنی‌سازی هر سوال با نام طراح (creator_name) به‌صورت دسته‌ای.
    🌊 C1.5 — intake اختیاری (None=رفتار قدیمی ادمین/داخلی؛ مسیر
    دانشجو student_intake_filter پاس می‌دهد).
    """
    questions = await db.get_exam_questions(
        lesson=lesson, chapter=chapter, topic=topic, difficulty=difficulty,
        tags=tags, count=count, randomize=randomize, exclude_ids=exclude_ids,
        intake=intake,
    )
    creator_ids = [q.get('creator_id') for q in questions if q.get('creator_id')]
    names_map = await db.get_users_map(creator_ids) if creator_ids else {}
    for q in questions:
        q['creator_name'] = names_map.get(q.get('creator_id'), '') or ('تیم هامیار' if q.get('by_bot') else '')
    return questions
