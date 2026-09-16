"""
🗝️ qbank.answer_key — صفحه‌ی پاسخنامه

یک جدول/گرید فشرده و قابل‌اسکن: «سوال ۱ ← ب»، «سوال ۲ ← الف» و...
مناسب برای حالت «آزمون» (سوالات بدون پاسخ داخل متن، پاسخ‌ها همه‌جا یکجا).
"""
from reportlab.lib.units import mm

from qbank.fonts_rtl import rtl, fa_digits, REGULAR, BOLD
from qbank.styles import (
    PAGE_W, PAGE_H, MARGIN, CONTENT_W, NAVY, TEXT_DARK, GRAY, WHITE,
    BRAND_GREEN, CARD_BG, CARD_BORDER, OPT_LETTERS,
)

COLS = 5
CELL_H = 12 * mm


def draw_answer_key_header(c, exam_code: str) -> float:
    y = PAGE_H - MARGIN
    c.setFont(BOLD, 18)
    c.setFillColor(NAVY)
    c.drawRightString(PAGE_W - MARGIN, y, rtl("پاسخنامه"))
    y -= 7 * mm
    c.setFont(REGULAR, 9.5)
    c.setFillColor(GRAY)
    c.drawRightString(PAGE_W - MARGIN, y, rtl(f"کد آزمون: {exam_code}"))
    y -= 5 * mm
    c.setStrokeColor(CARD_BORDER)
    c.setLineWidth(1)
    c.line(MARGIN, y, PAGE_W - MARGIN, y)
    return y - 10 * mm


def draw_answer_key_grid(c, questions: list, y: float) -> float:
    """
    شبکه‌ای از سلول‌های «شماره ← حرف». برمی‌گرداند y باقی‌مانده (برای
    این‌که builder بداند آیا جا برای ادامه هست یا باید صفحه عوض شود).
    """
    cell_w = CONTENT_W / COLS
    for i, q in enumerate(questions):
        col = i % COLS
        correct = q.get('correct_answer', 0)
        letter = OPT_LETTERS[correct] if correct < len(OPT_LETTERS) else str(correct + 1)
        cx = PAGE_W - MARGIN - col * cell_w
        cell_left = cx - cell_w + 2 * mm
        cell_bottom = y - CELL_H + 2 * mm
        cell_w_in = cell_w - 4 * mm
        cell_h_in = CELL_H - 4 * mm

        c.setFillColor(CARD_BG)
        c.roundRect(cell_left, cell_bottom, cell_w_in, cell_h_in, 2 * mm, fill=1, stroke=0)
        c.setStrokeColor(CARD_BORDER)
        c.setLineWidth(0.7)
        c.roundRect(cell_left, cell_bottom, cell_w_in, cell_h_in, 2 * mm, fill=0, stroke=1)

        mid_y = cell_bottom + cell_h_in / 2
        # شماره‌ی سوال — سمت راستِ سلول
        c.setFont(BOLD, 10)
        c.setFillColor(TEXT_DARK)
        c.drawRightString(cell_left + cell_w_in - 3 * mm, mid_y - 1.6, fa_digits(i + 1))
        # فلش کوچک
        c.setFont(REGULAR, 8)
        c.setFillColor(GRAY)
        c.drawCentredString(cell_left + cell_w_in / 2, mid_y - 1.4, "←")
        # حرفِ گزینه‌ی صحیح — داخل دایره‌ی سبز، سمت چپِ سلول
        badge_cx = cell_left + 6 * mm
        c.setFillColor(BRAND_GREEN)
        c.circle(badge_cx, mid_y, 3.4 * mm, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont(BOLD, 8.5)
        c.drawCentredString(badge_cx, mid_y - 2.8, rtl(letter))

        if col == COLS - 1:
            y -= CELL_H
    if len(questions) % COLS != 0:
        y -= CELL_H
    return y
