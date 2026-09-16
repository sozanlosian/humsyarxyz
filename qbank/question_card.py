"""
🃏 qbank.question_card — رسم یک کارت سوال کامل

طراحی این کارت مطابق نمونه‌ای است که کاربر پسندید: شماره‌ی سوال در
دایره‌ی سبز، سوال، گزینه‌ها در گرید ۲ ستونه با برچسب حرف در دایره‌ی
کوچک، خط جداکننده‌ی نقطه‌چین، نوار سبز پاسخ صحیح، و بخش «تحلیل».

هر تابع این ماژول فقط روی یک reportlab.Canvas می‌کشد و ارتفاع مصرفی یا
موردنیاز را برمی‌گرداند — هیچ تصمیمی درباره‌ی page-break اینجا گرفته
نمی‌شود (آن منطق در builder.py است).
"""
from reportlab.lib.units import mm

from qbank.fonts_rtl import rtl, fa_digits, wrap_rtl, text_width, REGULAR, MEDIUM, BOLD
from qbank.styles import (
    PAGE_W, MARGIN, CONTENT_W, TEXT_DARK, TEXT_BODY, GRAY, WHITE,
    BRAND_GREEN, CARD_BG, CARD_BORDER, OPT_BG, OPT_BORDER, OPT_LETTERS,
    DIFF_STYLE, normalize_difficulty,
)

CARD_PAD = 5 * mm
IMG_MAX_H = 45 * mm
HEADER_ROW_H = 10 * mm  # ردیف بالای کارت: شماره + سختی + مبحث — همیشه یک ارتفاع ثابت


def _draw_checkmark(c, cx, cy, size, color):
    """تیک درست به‌صورت وکتور — مستقل از پشتیبانی گلیف فونت، همیشه یکسان چاپ می‌شود"""
    c.setStrokeColor(color)
    c.setLineWidth(1.8)
    c.setLineCap(1)
    c.setLineJoin(1)
    p = c.beginPath()
    p.moveTo(cx - size * 0.5, cy)
    p.lineTo(cx - size * 0.12, cy - size * 0.42)
    p.lineTo(cx + size * 0.55, cy + size * 0.5)
    c.drawPath(p, stroke=1, fill=0)


def _image_height(image_reader, target_w) -> float:
    iw, ih = image_reader.getSize()
    h = target_w * (ih / iw)
    return min(h, IMG_MAX_H)


def measure_card_height(q: dict, show_answer: bool = True, question_image=None) -> float:
    """
    ارتفاع تقریبیِ لازم برای یک کارت را از قبل محاسبه می‌کند — بدون
    این‌که چیزی رسم شود. builder از این برای تصمیم page-break استفاده
    می‌کند (تا هیچ‌وقت یک سوال نیمه روی صفحه‌ی بعد پخش نشود).
    """
    options = q.get('options', [])
    q_lines = wrap_rtl(q.get('question', ''), BOLD, 12, CONTENT_W - 2 * CARD_PAD)
    h = CARD_PAD + HEADER_ROW_H + len(q_lines) * 6 * mm + 4 * mm

    if question_image is not None:
        h += _image_height(question_image, CONTENT_W - 2 * CARD_PAD) + 4 * mm

    col_w = (CONTENT_W - 2 * CARD_PAD - 4 * mm) / 2
    n_rows = (len(options) + 1) // 2
    for row in range(n_rows):
        row_opts = options[row * 2: row * 2 + 2]
        row_h = 0
        for opt in row_opts:
            ol = wrap_rtl(opt, REGULAR, 10, col_w - 12 * mm)
            row_h = max(row_h, len(ol) * 4.6 * mm + 6 * mm)
        h += row_h + 4 * mm

    if show_answer:
        correct = q.get('correct_answer', 0)
        opt_text = options[correct] if correct < len(options) else ''
        letter = OPT_LETTERS[correct] if correct < len(OPT_LETTERS) else str(correct + 1)
        ans_lines = wrap_rtl(f"پاسخ صحیح: {letter} — {opt_text}", BOLD, 10.5,
                              CONTENT_W - 2 * CARD_PAD - 16 * mm)
        h += 6 * mm + len(ans_lines) * 5 * mm + 5 * mm + 6 * mm

        expl = q.get('explanation', '')
        if expl:
            expl_lines = wrap_rtl(expl, REGULAR, 9.5, CONTENT_W - 2 * CARD_PAD - 4 * mm)
            h += 5.5 * mm + len(expl_lines) * 4.8 * mm

    return h + CARD_PAD + 6 * mm  # + فاصله‌ی بین کارت‌ها


def draw_question_card(c, q: dict, index: int, y: float, show_answer: bool = True,
                        question_image=None, answer_image=None) -> float:
    """
    رسم کامل یک کارت سوال، شروع از ارتفاع y (بالای کارت).
    خروجی: y جدید بعد از این کارت (برای سوال بعدی).

    show_answer=False → فقط سوال و گزینه‌ها رسم می‌شود، بدون نوار پاسخ
    و بدون تحلیل (هوک آماده برای «نسخه‌ی بدون پاسخ»، یکی از قابلیت‌های
    توسعه‌ی آینده‌ی خواسته‌شده).
    """
    options = q.get('options', [])
    correct = q.get('correct_answer', 0)
    diff_key = normalize_difficulty(q.get('difficulty', ''))
    diff_color, diff_bg = DIFF_STYLE[diff_key]
    topic = q.get('topic', '')

    card_h = measure_card_height(q, show_answer, question_image) - 6 * mm
    card_top = y

    # soft shadow
    from reportlab.lib.colors import HexColor
    c.setFillColor(HexColor('#e6e8ec'))
    c.setFillAlpha(0.55)
    c.roundRect(MARGIN + 0.7*mm, card_top - card_h - 0.7*mm, CONTENT_W, card_h, 3 * mm, fill=1, stroke=0)
    c.setFillAlpha(1)
    c.setFillColor(CARD_BG)
    c.roundRect(MARGIN, card_top - card_h, CONTENT_W, card_h, 3 * mm, fill=1, stroke=0)
    c.setStrokeColor(CARD_BORDER)
    c.setLineWidth(0.8)
    c.roundRect(MARGIN, card_top - card_h, CONTENT_W, card_h, 3 * mm, fill=0, stroke=1)

    y = card_top - CARD_PAD

    # ── ردیف بالا: شماره (راست) + سختی + مبحث — همه روی یک خط ثابت ──
    badge_r = 4.2 * mm
    row_y = y - badge_r
    bx = PAGE_W - MARGIN - CARD_PAD - badge_r
    c.setFillColor(BRAND_GREEN)
    c.circle(bx, row_y, badge_r, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont(BOLD, 11)
    c.drawCentredString(bx, row_y - 3.6, fa_digits(index))

    cursor_x = bx - badge_r - 4 * mm  # لبه‌ی راستِ فضای باقی‌مانده، برای عناصر بعدی سمت چپ بج

    diff_label = f"{diff_key}"
    pill_w = text_width(diff_label, MEDIUM, 8.5) + 8 * mm
    c.setFillColor(diff_bg)
    c.roundRect(cursor_x - pill_w, row_y - 3 * mm, pill_w, 6 * mm, 3 * mm, fill=1, stroke=0)
    c.setFillColor(diff_color)
    c.setFont(MEDIUM, 8.5)
    c.drawCentredString(cursor_x - pill_w / 2, row_y - 1.2 * mm, rtl(diff_label))
    cursor_x -= pill_w + 3 * mm

    if topic:
        # فضای باقی‌مانده تا لبه‌ی چپ کارت — اگه مبحث خیلی بلند باشه، کوتاه می‌شود
        # تا هرگز از فضای خودش بیرون نزند و با چیز دیگری تداخل نکند
        avail_w = cursor_x - (MARGIN + CARD_PAD)
        topic_show = topic
        while topic_show and text_width(topic_show, REGULAR, 8.5) > avail_w:
            topic_show = topic_show[:-1]
        if topic_show:
            suffix = '…' if topic_show != topic else ''
            c.setFont(REGULAR, 8.5)
            c.setFillColor(GRAY)
            c.drawRightString(cursor_x, row_y - 1.2 * mm, rtl(topic_show + suffix))

    y = row_y - badge_r - 4 * mm  # پایین‌تر از کل ردیف هدر — سوال از اینجا شروع می‌شود

    # ── متن سوال (تمام عرض کارت) ──
    c.setFont(BOLD, 12)
    c.setFillColor(TEXT_DARK)
    ty = y
    q_max_w = CONTENT_W - 2 * CARD_PAD
    for line in wrap_rtl(q.get('question', ''), BOLD, 12, q_max_w):
        c.drawRightString(PAGE_W - MARGIN - CARD_PAD, ty, line)
        ty -= 6 * mm
    y = ty - 2 * mm

    # ── تصویر سوال (اختیاری، Responsive) ──
    if question_image is not None:
        img_w = CONTENT_W - 2 * CARD_PAD
        img_h = _image_height(question_image, img_w)
        c.drawImage(question_image, MARGIN + CARD_PAD, y - img_h, width=img_w, height=img_h,
                    preserveAspectRatio=True, anchor='n', mask='auto')
        y -= img_h + 4 * mm

    # ── گزینه‌ها (گرید ۲ ستونه) ──
    col_w = (CONTENT_W - 2 * CARD_PAD - 4 * mm) / 2
    right_col_x = MARGIN + CARD_PAD + col_w + 4 * mm
    left_col_x = MARGIN + CARD_PAD

    def draw_opt(cx0, cy0, w, opt_idx, text):
        lines = wrap_rtl(text, REGULAR, 10, w - 12 * mm)
        h = max(len(lines), 1) * 4.6 * mm + 6 * mm
        c.setFillColor(OPT_BG)
        c.roundRect(cx0, cy0 - h, w, h, 2.2 * mm, fill=1, stroke=0)
        c.setStrokeColor(OPT_BORDER)
        c.setLineWidth(0.7)
        c.roundRect(cx0, cy0 - h, w, h, 2.2 * mm, fill=0, stroke=1)
        lr = 3.2 * mm
        lx, ly = cx0 + w - 5 * mm - lr, cy0 - h / 2
        c.setFillColor(WHITE)
        c.setStrokeColor(OPT_BORDER)
        c.setLineWidth(0.7)
        c.circle(lx, ly, lr, fill=1, stroke=1)
        c.setFillColor(TEXT_DARK)
        c.setFont(MEDIUM, 8.5)
        letter = OPT_LETTERS[opt_idx] if opt_idx < len(OPT_LETTERS) else str(opt_idx + 1)
        c.drawCentredString(lx, ly - 2.8, rtl(letter))
        c.setFont(REGULAR, 10)
        c.setFillColor(TEXT_DARK)
        tyy = cy0 - 4.5 * mm
        for line in lines:
            c.drawRightString(cx0 + w - 5 * mm - 2 * lr - 2 * mm, tyy, line)
            tyy -= 4.6 * mm
        return h

    n_rows = (len(options) + 1) // 2
    for row in range(n_rows):
        idx_r, idx_l = row * 2, row * 2 + 1
        h_r = draw_opt(right_col_x, y, col_w, idx_r, options[idx_r]) if idx_r < len(options) else 0
        h_l = draw_opt(left_col_x, y, col_w, idx_l, options[idx_l]) if idx_l < len(options) else 0
        y -= max(h_r, h_l) + 4 * mm

    if not show_answer:
        return card_top - card_h - 6 * mm

    # ── خط جداکننده‌ی نقطه‌چین با برچسب ──
    y -= 2 * mm
    c.setDash(2, 2)
    c.setStrokeColor(CARD_BORDER)
    c.setLineWidth(0.8)
    c.line(MARGIN + CARD_PAD, y, PAGE_W - MARGIN - CARD_PAD, y)
    c.setDash([])
    label = rtl("پاسخ و تحلیل")
    lw = text_width("پاسخ و تحلیل", REGULAR, 8)
    c.setFillColor(CARD_BG)
    c.rect(PAGE_W / 2 - lw / 2 - 3 * mm, y - 2.3 * mm, lw + 6 * mm, 4.6 * mm, fill=1, stroke=0)
    c.setFillColor(GRAY)
    c.setFont(REGULAR, 8)
    c.drawCentredString(PAGE_W / 2, y - 1.3 * mm, label)
    y -= 6 * mm

    # ── نوار سبز پاسخ صحیح ──
    opt_text = options[correct] if correct < len(options) else ''
    letter = OPT_LETTERS[correct] if correct < len(OPT_LETTERS) else str(correct + 1)
    ans_lines = wrap_rtl(f"پاسخ صحیح: {letter} — {opt_text}", BOLD, 10.5,
                          CONTENT_W - 2 * CARD_PAD - 16 * mm)
    bar_h = len(ans_lines) * 5 * mm + 5 * mm
    c.setFillColor(BRAND_GREEN)
    c.roundRect(MARGIN + CARD_PAD, y - bar_h, CONTENT_W - 2 * CARD_PAD, bar_h, 2.5 * mm, fill=1, stroke=0)
    _draw_checkmark(c, MARGIN + CARD_PAD + 7 * mm, y - bar_h / 2, 3.4 * mm, WHITE)
    c.setFont(BOLD, 10.5)
    c.setFillColor(WHITE)
    tyy = y - 4.2 * mm
    for line in ans_lines:
        c.drawRightString(PAGE_W - MARGIN - CARD_PAD - 5 * mm, tyy, line)
        tyy -= 5 * mm
    y -= bar_h + 6 * mm

    # ── تحلیل ──
    expl = q.get('explanation', '')
    if expl:
        c.setFont(BOLD, 10)
        c.setFillColor(TEXT_DARK)
        c.drawRightString(PAGE_W - MARGIN - CARD_PAD, y, rtl("تحلیل"))
        y -= 5.5 * mm
        c.setFont(REGULAR, 9.5)
        c.setFillColor(TEXT_BODY)
        for line in wrap_rtl(expl, REGULAR, 9.5, CONTENT_W - 2 * CARD_PAD - 4 * mm):
            c.drawRightString(PAGE_W - MARGIN - CARD_PAD, y, line)
            y -= 4.8 * mm

        if answer_image is not None:
            img_w = CONTENT_W - 2 * CARD_PAD
            img_h = _image_height(answer_image, img_w)
            c.drawImage(answer_image, MARGIN + CARD_PAD, y - img_h, width=img_w, height=img_h,
                        preserveAspectRatio=True, anchor='n', mask='auto')
            y -= img_h + 2 * mm

    return card_top - card_h - 6 * mm
