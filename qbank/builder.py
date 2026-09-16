"""
🏗️ qbank.builder — Orchestrator نهایی — Premium v2

هم‌خانواده با schedule_pdf v2: واترمارک، نوار برند، فوتر تاریخ‌دار، هدرِ بخشِ سوالاتِ ارتقا یافته.
دو حالت: practice (پاسخ زیر سوال) و exam (پاسخنامهٔ مجزا + تشریحی)
"""

import io
import logging

from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor

from qbank.fonts_rtl import ensure_fonts, rtl, fa_digits, text_width, REGULAR, BOLD, MEDIUM
from qbank.styles import PAGE_W, PAGE_H, MARGIN, MIN_Y, FOOTER_Y, NAVY, NAVY_LIGHT, BRAND_GREEN, GRAY, CARD_BORDER, WHITE
from qbank.query import ExamMeta
from qbank.cover import draw_cover_page
from qbank.question_card import draw_question_card, measure_card_height
from qbank.answer_key import draw_answer_key_header, draw_answer_key_grid, CELL_H
from qbank.explanations import draw_explanations_header, draw_explanation_block, measure_explanation_height

logger = logging.getLogger(__name__)

_TOP_BAR_H = 3.0 * mm


def _draw_brand_bar(c):
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - _TOP_BAR_H, PAGE_W, _TOP_BAR_H, fill=1, stroke=0)
    c.setFillColor(BRAND_GREEN)
    c.rect(0, PAGE_H - _TOP_BAR_H - 0.7*mm, PAGE_W, 0.7*mm, fill=1, stroke=0)


def _draw_watermark(c, alpha=0.025):
    c.saveState()
    c.setFillColor(NAVY)
    c.setFillAlpha(alpha)
    c.setFont(BOLD, 48)
    c.translate(PAGE_W/2, PAGE_H/2)
    c.rotate(32)
    c.drawCentredString(0, 0, rtl("هامزیار"))
    c.restoreState()
    c.setFillAlpha(1)


def _today_pretty():
    try:
        from time_utils import format_datetime_fa, now_utc
        return format_datetime_fa(now_utc(), long=True)
    except Exception:
        from time_utils import format_date_fa, now_utc
        return format_date_fa(now_utc(), long=True)


def _draw_footer(c, page_num: int):
    c.setStrokeColor(CARD_BORDER)
    c.setLineWidth(0.6)
    c.line(MARGIN, FOOTER_Y, PAGE_W - MARGIN, FOOTER_Y)
    c.setFont(REGULAR, 7.2)
    c.setFillColor(GRAY)
    # centered: brand · date · page
    c.drawCentredString(PAGE_W / 2, FOOTER_Y - 5.2 * mm,
                         rtl(f"تولید شده توسط ربات هامزیار (@humsyarbot)  •  {fa_digits(_today_pretty())}  •  صفحه {fa_digits(page_num)}"))
    c.setFillColor(BRAND_GREEN)
    c.circle(PAGE_W/2, FOOTER_Y - 5.2*mm + 7.5*mm, 0.85*mm, fill=1, stroke=0)


def _draw_section_header(c, lesson: str, topic: str, meta: ExamMeta | None = None) -> float:
    """هدر فشرده‌ی صفحات دوم‌به‌بعدِ بخش سوالات — با نوار برند و چیپ کد"""
    _draw_brand_bar(c)
    _draw_watermark(c, alpha=0.022)
    y = PAGE_H - 11 * mm
    # exam code chip on left (RTL: چپ)
    if meta and getattr(meta, 'exam_code', None):
        chip = f"کد: {meta.exam_code}"
        w = text_width(chip, MEDIUM, 7) + 10*mm
        c.setFillColor(HexColor('#eef0ff'))
        c.roundRect(MARGIN, y - 3*mm, w, 6*mm, 3*mm, fill=1, stroke=0)
        c.setStrokeColor(HexColor('#d9e1ff'))
        c.setLineWidth(0.5)
        c.roundRect(MARGIN, y - 3*mm, w, 6*mm, 3*mm, fill=0, stroke=1)
        c.setFont(MEDIUM, 7)
        c.setFillColor(NAVY_LIGHT)
        c.drawCentredString(MARGIN + w/2, y - 1.1*mm, rtl(chip))
        # pushed title a bit to right
        title_x = PAGE_W - MARGIN
    else:
        title_x = PAGE_W - MARGIN

    c.setFont(BOLD, 11.5)
    c.setFillColor(NAVY)
    title = f"بانک سوال — {lesson}" + (f" ({topic})" if topic and topic != 'همه' else '')
    c.drawRightString(title_x, y, rtl(title))
    y -= 5.5 * mm
    c.setStrokeColor(HexColor('#e6e8ec'))
    c.setLineWidth(0.6)
    c.line(MARGIN, y, PAGE_W - MARGIN, y)
    # tiny green dash in middle
    c.setStrokeColor(BRAND_GREEN)
    c.setLineWidth(1.2)
    c.line(PAGE_W/2 - 10*mm, y, PAGE_W/2 + 10*mm, y)
    return y - 8 * mm


def generate_exam_pdf(questions: list, meta: ExamMeta, mode: str = 'practice',
                       question_images: dict = None, answer_images: dict = None) -> bytes:
    """
    نقطه‌ی ورود اصلی. همه‌چیز را می‌سازد و bytes نهایی PDF را برمی‌گرداند.

    questions: خروجی qbank.query.fetch_exam_questions (لیست دیکشنری)
    meta: qbank.query.ExamMeta
    mode: 'practice' یا 'exam'
    question_images/answer_images: dict اختیاری {question_id: ImageReader}
    """
    ensure_fonts()
    question_images = question_images or {}
    answer_images = answer_images or {}
    show_answer_inline = (mode == 'practice')

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    try:
        c.setTitle(f"Hamsyar — آزمون {meta.lesson} — {meta.exam_code}")
        c.setAuthor("humsyarbot")
    except Exception:
        pass
    page_num = 1

    # ── جلد ──
    draw_cover_page(c, meta, len(questions))
    _draw_footer(c, page_num)
    c.showPage()
    page_num += 1

    # ── صفحات سوالات ──
    y = _draw_section_header(c, meta.lesson, meta.topic, meta)
    for i, q in enumerate(questions, 1):
        qid = str(q.get('_id', i))
        q_img = question_images.get(qid)
        a_img = answer_images.get(qid) if show_answer_inline else None

        needed = measure_card_height(q, show_answer_inline, q_img)
        if y - needed < MIN_Y:
            _draw_footer(c, page_num)
            c.showPage()
            page_num += 1
            y = _draw_section_header(c, meta.lesson, meta.topic, meta)

        y = draw_question_card(c, q, i, y, show_answer=show_answer_inline,
                                question_image=q_img, answer_image=a_img)

    if mode == 'exam':
        # ── پاسخنامه ──
        _draw_footer(c, page_num)
        c.showPage()
        page_num += 1
        _draw_brand_bar(c)
        _draw_watermark(c, alpha=0.022)
        y = draw_answer_key_header(c, meta.exam_code)
        remaining = questions
        while remaining:
            rows_left = int((y - MIN_Y) // CELL_H)
            take = min(len(remaining), max(rows_left, 1) * 5)
            chunk, remaining = remaining[:take], remaining[take:]
            y = draw_answer_key_grid(c, chunk, y)
            if remaining:
                _draw_footer(c, page_num)
                c.showPage()
                page_num += 1
                _draw_brand_bar(c)
                _draw_watermark(c, alpha=0.022)
                y = PAGE_H - MARGIN

        # ── پاسخ تشریحی ──
        _draw_footer(c, page_num)
        c.showPage()
        page_num += 1
        _draw_brand_bar(c)
        _draw_watermark(c, alpha=0.022)
        y = draw_explanations_header(c)
        for i, q in enumerate(questions, 1):
            qid = str(q.get('_id', i))
            a_img = answer_images.get(qid)
            needed = measure_explanation_height(q, a_img)
            if y - needed < MIN_Y:
                _draw_footer(c, page_num)
                c.showPage()
                page_num += 1
                _draw_brand_bar(c)
                _draw_watermark(c, alpha=0.022)
                y = draw_explanations_header(c)
            y = draw_explanation_block(c, q, i, y, answer_image=a_img)

    _draw_footer(c, page_num)
    c.save()
    buf.seek(0)
    return buf.getvalue()
