"""
📇 qbank.cover — صفحه‌ی جلد آزمون — Hamsyar Premium v2

طراحی v2: برندینگ یکدست با schedule_pdf، واترمارک کم‌رنگ، لوگوی دوحلقه‌ای،
نوارِ برند در بالا، عنوانِ هایلایت‌شده، باکس اطلاعات با هدر سرمه‌ای و
سطرهای تفکیک‌شده، و چیپِ کد آزمون در بالای باکس.
"""
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor

from qbank.fonts_rtl import rtl, fa_digits, text_width, REGULAR, MEDIUM, BOLD
from qbank.styles import (
    PAGE_W, PAGE_H, MARGIN, NAVY, NAVY_LIGHT, BRAND_GREEN,
    GRAY, TEXT_DARK, WHITE, CARD_BG, CARD_BORDER,
)

_TOP_BAR_H = 3.8 * mm


def _draw_brand_bar(c):
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - _TOP_BAR_H, PAGE_W, _TOP_BAR_H, fill=1, stroke=0)
    c.setFillColor(BRAND_GREEN)
    c.rect(0, PAGE_H - _TOP_BAR_H - 0.9*mm, PAGE_W, 0.9*mm, fill=1, stroke=0)


def _draw_watermark(c):
    c.saveState()
    c.setFillColor(NAVY)
    c.setFillAlpha(0.03)
    c.setFont(BOLD, 52)
    c.translate(PAGE_W/2, PAGE_H/2)
    c.rotate(32)
    c.drawCentredString(0, 0, rtl("هامزیار"))
    c.restoreState()
    c.setFillAlpha(1)


def _draw_logo(c, cx, cy, r):
    c.setFillColor(HexColor('#0f1a3a'))
    c.setFillAlpha(0.09)
    c.circle(cx + 0.6*mm, cy - 0.6*mm, r + 1.4*mm, fill=1, stroke=0)
    c.setFillAlpha(1)
    c.setFillColor(WHITE)
    c.circle(cx, cy, r + 1.6*mm, fill=1, stroke=0)
    c.setStrokeColor(BRAND_GREEN)
    c.setLineWidth(0.5)
    c.circle(cx, cy, r + 1.6*mm, fill=0, stroke=1)
    c.setFillColor(BRAND_GREEN)
    c.circle(cx, cy, r, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFillAlpha(0.18)
    c.circle(cx - r*0.28, cy + r*0.28, r*0.32, fill=1, stroke=0)
    c.setFillAlpha(1)
    c.setFillColor(WHITE)
    c.setFont(BOLD, r * 0.9)
    c.drawCentredString(cx, cy - r * 0.32, rtl("ها"))


def _today_jalali() -> str:
    from time_utils import format_date_fa, now_utc
    return format_date_fa(now_utc(), long=True)


def _now_tehran_pretty() -> str:
    try:
        from time_utils import format_datetime_fa, now_utc
        return format_datetime_fa(now_utc(), long=True)
    except Exception:
        return _today_jalali()


def draw_cover_page(c, meta, question_count: int):
    """صفحه‌ی اول PDF را کامل رسم می‌کند (فرض بر این‌ست که c تازه showPage شده یا صفحه‌ی خالی اول است)"""
    _draw_brand_bar(c)
    _draw_watermark(c)

    cy = PAGE_H - 34 * mm
    _draw_logo(c, PAGE_W / 2, cy, 14 * mm)

    c.setFont(BOLD, 21)
    c.setFillColor(NAVY)
    c.drawCentredString(PAGE_W / 2, cy - 24 * mm, rtl("هامزیار"))

    c.setFont(REGULAR, 9.5)
    c.setFillColor(GRAY)
    c.drawCentredString(PAGE_W / 2, cy - 29.5 * mm, rtl("@humsyarbot  —  سامانه‌ی آموزشی دانشجویان پزشکی"))

    # چیپِ کد آزمون در بالا سمت چپ (RTL: چپِ صفحه)
    code_chip_w = text_width(meta.exam_code or '', MEDIUM, 8) + 14*mm
    code_chip_w = max(code_chip_w, 38*mm)
    code_chip_x = MARGIN
    code_chip_y = PAGE_H - 22*mm
    c.setFillColor(HexColor('#eef0ff'))
    c.roundRect(code_chip_x, code_chip_y - 6*mm, code_chip_w, 7*mm, 3.5*mm, fill=1, stroke=0)
    c.setStrokeColor(HexColor('#d9e1ff'))
    c.setLineWidth(0.6)
    c.roundRect(code_chip_x, code_chip_y - 6*mm, code_chip_w, 7*mm, 3.5*mm, fill=0, stroke=1)
    c.setFont(MEDIUM, 7.5)
    c.setFillColor(NAVY_LIGHT)
    c.drawCentredString(code_chip_x + code_chip_w/2, code_chip_y - 4.1*mm, rtl(f"کد: {meta.exam_code or '—'}"))

    # تاریخچه تولید کوچک سمت راست بالا
    c.setFont(REGULAR, 7)
    c.setFillColor(GRAY)
    c.drawRightString(PAGE_W - MARGIN, code_chip_y - 4*mm, rtl(_now_tehran_pretty()))

    # خط جداکننده‌ی ظریف زیر لوگو
    y = cy - 39 * mm
    c.setStrokeColor(CARD_BORDER)
    c.setLineWidth(0.8)
    # gradient-ish: thicker center
    c.line(PAGE_W / 2 - 32 * mm, y, PAGE_W / 2 + 32 * mm, y)
    c.setFillColor(BRAND_GREEN)
    c.circle(PAGE_W/2, y, 1.1*mm, fill=1, stroke=0)

    # عنوان آزمون — با هایلایت درس
    y -= 12 * mm
    # background pill for title
    title_raw = f"آزمون بانک سوال — {meta.lesson}"
    tw = text_width(title_raw, BOLD, 15) + 14*mm
    tw = min(tw, 150*mm)
    c.setFillColor(HexColor('#f1f5ff'))
    c.roundRect(PAGE_W/2 - tw/2, y - 5*mm, tw, 11*mm, 5*mm, fill=1, stroke=0)
    c.setStrokeColor(HexColor('#d9e1ff'))
    c.setLineWidth(0.6)
    c.roundRect(PAGE_W/2 - tw/2, y - 5*mm, tw, 11*mm, 5*mm, fill=0, stroke=1)
    c.setFont(BOLD, 15)
    c.setFillColor(TEXT_DARK)
    c.drawCentredString(PAGE_W / 2, y, rtl(title_raw))

    # زیرعنوان مبحث/سطح
    y -= 8 * mm
    sub_parts = []
    topic_disp = meta.topic if meta.topic and meta.topic != 'همه' else 'همه‌ی مباحث'
    sub_parts.append(topic_disp)
    if meta.difficulty:
        sub_parts.append(meta.difficulty)
    if meta.chapter:
        sub_parts.append(f"فصل {meta.chapter}")
    sub_line = "  •  ".join(sub_parts)
    c.setFont(MEDIUM, 9)
    c.setFillColor(NAVY_LIGHT)
    c.drawCentredString(PAGE_W/2, y, rtl(sub_line))

    # جدول اطلاعات — باکس مدرن
    y -= 10 * mm
    rows = [("درس", meta.lesson)]
    if meta.chapter:
        rows.append((f"فصل {getattr(meta,'chapter','')}", meta.chapter))
    rows.append(("مبحث", topic_disp))
    if meta.difficulty:
        rows.append(("سطح سختی", meta.difficulty))
    rows.append(("تعداد سوالات", fa_digits(question_count)))
    rows.append(("تاریخ تولید", _today_jalali()))
    rows.append(("کد آزمون", meta.exam_code))
    if meta.student_name:
        rows.append(("نام دانشجو", meta.student_name))

    box_w = 124 * mm
    row_h = 9 * mm
    header_h = 10 * mm
    box_h = header_h + row_h * len(rows)
    box_x = (PAGE_W - box_w) / 2
    box_top = y

    # shadow soft
    c.setFillColor(HexColor('#eef0f7'))
    c.setFillAlpha(0.55)
    c.roundRect(box_x + 0.9*mm, box_top - box_h - 0.9*mm, box_w, box_h, 3.5 * mm, fill=1, stroke=0)
    c.setFillAlpha(1)

    # main box
    c.setFillColor(WHITE)
    c.roundRect(box_x, box_top - box_h, box_w, box_h, 3.5 * mm, fill=1, stroke=0)
    c.setStrokeColor(CARD_BORDER)
    c.setLineWidth(0.8)
    c.roundRect(box_x, box_top - box_h, box_w, box_h, 3.5 * mm, fill=0, stroke=1)

    # header strip inside box
    c.setFillColor(NAVY)
    # top rounded only — simulate by clipping: draw rect with rounded top
    # simplest: draw rounded rect for header then overlay white bottom to hide bottom rounding
    c.roundRect(box_x, box_top - header_h, box_w, header_h, 3.5*mm, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.rect(box_x, box_top - header_h, box_w, 3.5*mm, fill=1, stroke=0)
    # header text
    c.setFillColor(WHITE)
    c.setFont(BOLD, 10.5)
    c.drawCentredString(PAGE_W/2, box_top - header_h/2 - 2.8*mm, rtl("📋 اطلاعات آزمون"))
    # tiny green dot on header
    c.setFillColor(BRAND_GREEN)
    c.circle(box_x + box_w - 9*mm, box_top - header_h/2, 1.2*mm, fill=1, stroke=0)

    ry = box_top - header_h - row_h / 2 - 2.2
    for i, (label, value) in enumerate(rows):
        if i > 0:
            c.setStrokeColor(HexColor('#eef0f2'))
            c.setLineWidth(0.5)
            c.line(box_x + 6 * mm, box_top - header_h - i * row_h, box_x + box_w - 6 * mm, box_top - header_h - i * row_h)
        # zebra subtle
        if i % 2 == 1:
            c.setFillColor(HexColor('#fafbfc'))
            c.rect(box_x + 1*mm, box_top - header_h - (i+1)*row_h + 0.4*mm, box_w - 2*mm, row_h - 0.8*mm, fill=1, stroke=0)
        c.setFont(MEDIUM, 9.6)
        c.setFillColor(GRAY)
        c.drawRightString(box_x + box_w - 7 * mm, ry, rtl(label))
        c.setFont(BOLD, 10)
        c.setFillColor(NAVY_LIGHT)
        # values on left side need rtl properly — draw as right-aligned from left edge? Use drawString with rtl from left
        # we mirror: draw at left inset but right-aligned inside
        # simplest: use drawRightString from near left? we want LTR numbers stay LTR? use rtl wrapper
        val_str = str(value)
        # if value contains digits, keep fa_digits already
        c.drawString(box_x + 7 * mm, ry, rtl(val_str))
        ry -= row_h

    # پانویس جلد — با آیکون
    c.setFillColor(HexColor('#f3f4f6'))
    c.roundRect(PAGE_W/2 - 62*mm, 18*mm, 124*mm, 9*mm, 4*mm, fill=1, stroke=0)
    c.setStrokeColor(CARD_BORDER)
    c.setLineWidth(0.6)
    c.roundRect(PAGE_W/2 - 62*mm, 18*mm, 124*mm, 9*mm, 4*mm, fill=0, stroke=1)
    c.setFont(REGULAR, 8)
    c.setFillColor(GRAY)
    c.drawCentredString(PAGE_W / 2, 21.6*mm,
                         rtl("این آزمون به‌صورت خودکار توسط ربات هامزیار تولید شده است — @humsyarbot"))
