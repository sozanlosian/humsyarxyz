"""
📖 qbank.explanations — صفحات پاسخ تشریحی

برای حالت «آزمون»: بعد از پاسخنامه، برای هر سوال به‌صورت کامل‌تر
شماره، پاسخ صحیح و توضیح تشریحی (+ تصویر پاسخ در صورت وجود) نمایش
داده می‌شود.
"""
from reportlab.lib.units import mm

from qbank.fonts_rtl import rtl, wrap_rtl, fa_digits, REGULAR, BOLD
from qbank.styles import (
    PAGE_W, PAGE_H, MARGIN, CONTENT_W, NAVY, TEXT_DARK, TEXT_BODY,
    WHITE, BRAND_GREEN, CARD_BORDER, OPT_LETTERS,
)

IMG_MAX_H = 40 * mm


def draw_explanations_header(c) -> float:
    y = PAGE_H - MARGIN
    c.setFont(BOLD, 18)
    c.setFillColor(NAVY)
    c.drawRightString(PAGE_W - MARGIN, y, rtl("پاسخ تشریحی"))
    y -= 7 * mm
    c.setStrokeColor(CARD_BORDER)
    c.setLineWidth(1)
    c.line(MARGIN, y, PAGE_W - MARGIN, y)
    return y - 10 * mm


def measure_explanation_height(q: dict, answer_image=None) -> float:
    letter_w = CONTENT_W - 20 * mm
    ans_lines = wrap_rtl(_answer_line(q), BOLD, 10.5, letter_w)
    expl_lines = wrap_rtl(q.get('explanation', ''), REGULAR, 9.5, CONTENT_W - 4 * mm)
    h = 8 * mm + len(ans_lines) * 5 * mm + 3 * mm + len(expl_lines) * 4.8 * mm
    if answer_image is not None:
        iw, ih = answer_image.getSize()
        h += min(CONTENT_W * (ih / iw), IMG_MAX_H) + 4 * mm
    return h + 8 * mm


def _answer_line(q: dict) -> str:
    correct = q.get('correct_answer', 0)
    options = q.get('options', [])
    letter = OPT_LETTERS[correct] if correct < len(OPT_LETTERS) else str(correct + 1)
    opt_text = options[correct] if correct < len(options) else ''
    return f"پاسخ صحیح: {letter} — {opt_text}"


def draw_explanation_block(c, q: dict, index: int, y: float, answer_image=None) -> float:
    """یک بلوک پاسخ‌تشریحی (شماره + پاسخ + توضیح + تصویر اختیاری) را رسم می‌کند"""
    badge_r = 4 * mm
    bx, by = PAGE_W - MARGIN - badge_r, y - badge_r
    c.setFillColor(BRAND_GREEN)
    c.circle(bx, by, badge_r, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont(BOLD, 10.5)
    c.drawCentredString(bx, by - 3.4, fa_digits(index))

    c.setFont(BOLD, 10.5)
    c.setFillColor(TEXT_DARK)
    ans_lines = wrap_rtl(_answer_line(q), BOLD, 10.5, CONTENT_W - 2 * badge_r - 8 * mm)
    ty = y - 1.5 * mm
    for line in ans_lines:
        c.drawRightString(PAGE_W - MARGIN - 2 * badge_r - 4 * mm, ty, line)
        ty -= 5 * mm
    y = min(ty, y - 2 * badge_r) - 2 * mm

    expl = q.get('explanation', '')
    if expl:
        c.setFont(REGULAR, 9.5)
        c.setFillColor(TEXT_BODY)
        for line in wrap_rtl(expl, REGULAR, 9.5, CONTENT_W - 4 * mm):
            c.drawRightString(PAGE_W - MARGIN, y, line)
            y -= 4.8 * mm

    if answer_image is not None:
        img_w = CONTENT_W - 10 * mm
        iw, ih = answer_image.getSize()
        img_h = min(img_w * (ih / iw), IMG_MAX_H)
        c.drawImage(answer_image, MARGIN + 5 * mm, y - img_h, width=img_w, height=img_h,
                    preserveAspectRatio=True, anchor='n', mask='auto')
        y -= img_h + 4 * mm

    y -= 3 * mm
    c.setStrokeColor(CARD_BORDER)
    c.setLineWidth(0.6)
    c.line(MARGIN, y, PAGE_W - MARGIN, y)
    return y - 8 * mm
