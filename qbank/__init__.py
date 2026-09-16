"""
📦 qbank — سیستم ماژولار «بانک سوالات» برای تولید آزمون PDF

اجزا (هرکدام یک مسئولیت مشخص، طبق اصل جداسازی نگرانی‌ها):
    fonts_rtl.py    → فونت فارسی + کمک‌کننده‌های راست‌چین/word-wrap
    styles.py       → رنگ‌ها، اندازه‌ها، ثابت‌های طراحی (یک‌جا، قابل شخصی‌سازی)
    query.py        → لایه‌ی داده: گرفتن سوالات از دیتابیس + Randomizer
    cover.py        → رسم صفحه‌ی اول (جلد آزمون)
    question_card.py→ رسم هر کارت سوال (متن، گزینه‌ها، تصویر اختیاری)
    answer_key.py   → رسم صفحه‌ی پاسخنامه (جدول سوال → گزینه)
    explanations.py → رسم صفحات پاسخ تشریحی
    builder.py       → orchestrator نهایی: generate_exam_pdf(...)

نقطه‌ی ورود عمومی همینه:
    from qbank import generate_exam_pdf
"""
from qbank.builder import generate_exam_pdf

__all__ = ['generate_exam_pdf']
