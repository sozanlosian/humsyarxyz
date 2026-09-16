"""
📅 schedule_pdf — خروجی پریمیوم PDF از برنامه‌ی کلاس/امتحان/جبرانی — Hamsyar v2

ویژگی‌های v2 (Shahrivar 1405):
  • هماهنگ با هسته‌ی interval-aware جدید: نمایش «۰۸:۰۰ تا ۱۰:۰۰» (time + end_time)
    دقیقاً مثل webadmin / bot / miniapp، با اعداد فارسی و واژه‌ی «تا» شکل‌دهی‌شده.
  • تاریخ شمسی یکدست: «۱۴۰۵/۰۵/۱۸ (شنبه)» با weekday درست و rtl سالم.
  • هدر برندِ هامزیار: نوار Navy + اکسنت سبز، لوگوی دوحلقه‌ای، عنوان داینامیک
    برحسب stype، چیپ‌های متا (گروه/تعداد/تاریخ/نام دانشجو) و کارت‌های آماری
    تفکیکی (کلاس/امتحان/جبرانی) — حس پریمیومِ یکدست با qbank.
  • سطرها به‌صورت کارتِ گرد با فاصله‌ی تنفسی، بجِ رنگیِ نوع، خط اکسنت باریک،
    خطوط عمودیِ ظریف بین ستون‌ها، و واترمارک بسیار کم‌رنگ «هامزیار».
  • فوتر برند + شماره صفحه فارسی + زمان تولید.
  • بدون تکرار کدِ رنگ/فونت — مستقیم از qbank/styles و qbank/fonts_rtl.

امضا سازگار: generate_schedule_pdf(items, group_label, student_name='', stype=None)
که فراخوان قدیمیِ schedule.py همچنان کار می‌کند.
"""

import io
import logging
from datetime import datetime

from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor

from qbank.fonts_rtl import ensure_fonts, rtl, fa_digits, wrap_rtl, text_width, REGULAR, MEDIUM, BOLD
from qbank.styles import (
    PAGE_W, PAGE_H, MARGIN, CONTENT_W, MIN_Y, FOOTER_Y,
    NAVY, NAVY_LIGHT, BRAND_GREEN, GRAY, TEXT_DARK, WHITE, CARD_BORDER, CARD_BG,
)

logger = logging.getLogger(__name__)

# ── رنگ‌ها ──
_EXAM_RED = HexColor('#c62828')
_EXAM_BG = HexColor('#fff1f1')
_EXAM_BORDER = HexColor('#f1c0c0')
_CLASS_BG = HexColor('#eef0f7')
_CLASS_BORDER = HexColor('#d9dff0')
_MAKEUP_BG = HexColor('#e6f6ee')
_MAKEUP_BORDER = HexColor('#bfe8d0')
_ZEBRA_BG = HexColor('#f7f8fa')
_SOFT_BG = HexColor('#f3f4f6')
_PILL_BORDER = HexColor('#e6e8ec')
_TOP_BAR_H = 3.8 * mm

TYPE_STYLE = {
    # icon,  label,     fill,        bg,        border
    'class':  ('🏫', 'کلاس',   NAVY_LIGHT,  _CLASS_BG,  _CLASS_BORDER),
    'exam':   ('📝', 'امتحان', _EXAM_RED,   _EXAM_BG,   _EXAM_BORDER),
    'makeup': ('🔄', 'جبرانی', BRAND_GREEN, _MAKEUP_BG, _MAKEUP_BORDER),
}

# ستون‌ها — جمع دقیقا CONTENT_W (≈178mm روی A4 با حاشیه 16mm)
_COL = {
    'type': 22 * mm,
    'lesson': 40 * mm,
    'date': 34 * mm,
    'time': 32 * mm,
    'location': 26 * mm,
}
_COL['teacher'] = CONTENT_W - sum(_COL.values())  # ~24mm

ROW_H = 13.5 * mm
ROW_GAP = 1.8 * mm
TABLE_HEADER_H = 9 * mm

STYPE_TITLES = {
    'class':  ('🏫', 'برنامه‌ی کلاسی'),
    'exam':   ('📝', 'برنامه‌ی امتحانات'),
    'makeup': ('🔄', 'برنامه‌ی جبرانی'),
    None:     ('📅', 'برنامه‌ی کلاس‌ها و امتحانات'),
}


def _today_jalali() -> str:
    from time_utils import format_date_fa, now_utc
    return format_date_fa(now_utc(), long=True)


def _now_tehran_str() -> str:
    try:
        from time_utils import format_datetime_fa, now_utc
        return format_datetime_fa(now_utc(), long=True)
    except Exception:
        return _today_jalali()


def _fa_interval_for_item(item: dict) -> str:
    """
    نمایش بازه‌ی زمانی: اگر end_time موجود باشد «08:00 تا 10:00» با اعداد فارسی.
    سازگار با همه‌ی نام‌گذاری‌های تاریخی: end_time / time_end / end
    خروجی خام (بدون rtl) — رسم‌کننده خودش rtl می‌کند.
    """
    start = (item.get('time') or '').strip()
    end = (item.get('end_time') or item.get('time_end') or item.get('end') or '').strip()
    if end and end != start:
        if 'تا' in start or 'تا' in end:
            raw = start if 'تا' in start else f"{start} تا {end}"
            return fa_digits(raw)
        if ':' in start and ':' in end:
            return fa_digits(f"{start} تا {end}")
        return fa_digits(f"{start} تا {end}")
    if start:
        if 'تا' in start:
            return fa_digits(start)
        return fa_digits(start) if ':' in start else fa_digits(start)
    return '—'


def _counts(items: list) -> dict:
    c = {'class': 0, 'exam': 0, 'makeup': 0}
    for it in items:
        t = it.get('type', 'class')
        if t in c:
            c[t] += 1
    c['total'] = len(items)
    return c


def _days_left(item: dict):
    try:
        from time_utils import parse_gregorian_date, today_tehran
        d = (item.get('date') or '')[:10]
        if not d:
            return None
        target = parse_gregorian_date(d)
        return (target - today_tehran()).days
    except Exception:
        return None


def _draw_logo(c, cx, cy, r):
    # outer subtle shadow/ring
    c.setFillColor(HexColor('#0f1a3a'))
    c.setFillAlpha(0.09)
    c.circle(cx + 0.6*mm, cy - 0.6*mm, r + 1.2*mm, fill=1, stroke=0)
    c.setFillAlpha(1)
    # outer white ring
    c.setFillColor(WHITE)
    c.circle(cx, cy, r + 1.4*mm, fill=1, stroke=0)
    c.setStrokeColor(BRAND_GREEN)
    c.setLineWidth(0.5)
    c.circle(cx, cy, r + 1.4*mm, fill=0, stroke=1)
    # main green
    c.setFillColor(BRAND_GREEN)
    c.circle(cx, cy, r, fill=1, stroke=0)
    # inner highlight dot (premium)
    c.setFillColor(WHITE)
    c.setFillAlpha(0.18)
    c.circle(cx - r*0.28, cy + r*0.28, r*0.32, fill=1, stroke=0)
    c.setFillAlpha(1)
    c.setFillColor(WHITE)
    c.setFont(BOLD, r * 0.88)
    c.drawCentredString(cx, cy - r * 0.33, rtl("ها"))


def _draw_brand_bar(c):
    # solid navy top
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - _TOP_BAR_H, PAGE_W, _TOP_BAR_H, fill=1, stroke=0)
    # thin green accent just below
    c.setFillColor(BRAND_GREEN)
    c.rect(0, PAGE_H - _TOP_BAR_H - 0.9*mm, PAGE_W, 0.9*mm, fill=1, stroke=0)


def _draw_watermark(c):
    c.saveState()
    c.setFillColor(NAVY)
    c.setFillAlpha(0.03)
    c.setFont(BOLD, 52)
    # center page, rotated
    c.translate(PAGE_W/2, PAGE_H/2)
    c.rotate(32)
    c.drawCentredString(0, 0, rtl("هامزیار"))
    c.restoreState()
    c.setFillAlpha(1)


def _draw_header(c, group_label: str, student_name: str, count: int, stype=None, items=None) -> float:
    _draw_brand_bar(c)
    # light watermark behind header area
    _draw_watermark(c)

    cy = PAGE_H - 24 * mm
    _draw_logo(c, PAGE_W / 2, cy, 10.5 * mm)

    c.setFont(BOLD, 18)
    c.setFillColor(NAVY)
    c.drawCentredString(PAGE_W / 2, cy - 17.5 * mm, rtl("هامزیار"))

    c.setFont(REGULAR, 8.2)
    c.setFillColor(GRAY)
    c.drawCentredString(PAGE_W / 2, cy - 22.2 * mm, rtl("@humsyarbot  —  سامانه‌ی آموزشی دانشجویان پزشکی"))

    # dynamic title per stype
    icon, title = STYPE_TITLES.get(stype, STYPE_TITLES[None])
    y = cy - 32 * mm
    # subtle pill behind title
    title_text = f"{icon} {title}"
    title_w = text_width(title_text, BOLD, 13) + 10 * mm
    c.setFillColor(HexColor('#f1f5ff'))
    c.roundRect(PAGE_W/2 - title_w/2, y - 3*mm, title_w, 9*mm, 4*mm, fill=1, stroke=0)
    c.setStrokeColor(HexColor('#d9e1ff'))
    c.setLineWidth(0.6)
    c.roundRect(PAGE_W/2 - title_w/2, y - 3*mm, title_w, 9*mm, 4*mm, fill=0, stroke=1)
    c.setFont(BOLD, 13)
    c.setFillColor(NAVY)
    c.drawCentredString(PAGE_W / 2, y, rtl(title_text))

    y -= 9 * mm
    # ── meta pills row ──
    jalali = _today_jalali()
    pills = []
    # گروه و تعداد — نام دانشجو و تاریخ از هدر حذف شد (تاریخ به فوتر رفت)
    g = (group_label or 'همه').strip()
    if g in ('', 'هر دو'):
        g_text = "👥 گروه هر دو"
    else:
        g_text = f"👥 گروه {fa_digits(g)}"
    pills.append((g_text, NAVY, HexColor('#eef0f7')))
    pills.append((f"🔢 {fa_digits(count)} مورد", NAVY_LIGHT, HexColor('#f3f4f6')))

    # measure total width
    pill_h = 6.2 * mm
    gap = 2.2 * mm
    widths = []
    for txt, _, _ in pills:
        w = text_width(txt, MEDIUM, 7.8) + 7 * mm
        # minimal width handling for emoji duplicates
        w = max(w, 22*mm if len(txt) < 12 else w)
        widths.append(w)
    total_w = sum(widths) + gap*(len(pills)-1)
    # if too wide, fallback to centered line style (no pills) — but on A4 should fit
    if total_w > CONTENT_W:
        # fallback: single line with •
        y2 = y - 1*mm
        meta_parts = [p[0] for p in pills]
        # keep student at front if exists
        line = "  •  ".join(meta_parts)
        c.setFont(MEDIUM, 8.5)
        c.setFillColor(NAVY_LIGHT)
        c.drawCentredString(PAGE_W/2, y2, rtl(line))
        y = y2 - 4*mm
    else:
        pill_y = y - 1*mm
        cur_x = PAGE_W/2 - total_w/2
        for (txt, fg, bg), w in zip(pills, widths):
            # pill bg
            c.setFillColor(bg)
            c.roundRect(cur_x, pill_y - pill_h/2 - 1*mm, w, pill_h, pill_h/2, fill=1, stroke=0)
            c.setStrokeColor(_PILL_BORDER)
            c.setLineWidth(0.55)
            c.roundRect(cur_x, pill_y - pill_h/2 - 1*mm, w, pill_h, pill_h/2, fill=0, stroke=1)
            c.setFont(MEDIUM, 7.8)
            c.setFillColor(fg if fg != WHITE else WHITE)
            # if pill bg is dark (BRAND_GREEN), text white else dark
            if bg == BRAND_GREEN:
                c.setFillColor(WHITE)
            else:
                c.setFillColor(fg)
            c.drawCentredString(cur_x + w/2, pill_y - 1.6*mm, rtl(txt))
            cur_x += w + gap
        y = pill_y - pill_h/2 - 5*mm

    # ── stats strip (only if items provided and >0) ──
    # حرفه‌ای: وقتی خروجی اختصاصی یک بخش است فقط همان کارت وسط‌چین نمایش داده شود
    if items is not None and len(items) > 0:
        counts = _counts(items)
        if stype in ('class', 'exam', 'makeup'):
            kinds = [stype]
            card_h = 16 * mm
            card_w = 58 * mm
            gap_c = 0
            start_x = PAGE_W/2 - card_w/2
        else:
            card_h = 15 * mm
            card_w = (CONTENT_W - 8*mm) / 3
            gap_c = 4 * mm
            start_x = MARGIN
            kinds = ['class', 'exam', 'makeup']
        y_top = y + 2*mm
        y_bottom_cards = y_top - card_h
        for idx, kind in enumerate(kinds):
            icon_k, label_k, color_k, bg_k, border_k = TYPE_STYLE[kind]
            x = start_x + idx*(card_w+gap_c)
            is_active_filter = (stype == kind)
            # card bg
            fill_bg = WHITE if not is_active_filter else bg_k
            c.setFillColor(fill_bg)
            c.roundRect(x, y_bottom_cards, card_w, card_h, 3*mm, fill=1, stroke=0)
            # border: thicker if active
            c.setStrokeColor(color_k if is_active_filter else CARD_BORDER)
            c.setLineWidth(1 if is_active_filter else 0.7)
            c.roundRect(x, y_bottom_cards, card_w, card_h, 3*mm, fill=0, stroke=1)
            # top accent
            c.setFillColor(color_k)
            c.roundRect(x+1*mm, y_top - 2.2*mm, card_w-2*mm, 2.2*mm, 1*mm, fill=1, stroke=0)
            # icon circle
            cx_icon = x + card_w/2
            cy_icon = y_top - 6*mm
            # small icon bg light
            c.setFillColor(bg_k)
            c.circle(cx_icon, cy_icon, 5*mm, fill=1, stroke=0)
            c.setFont(BOLD, 9)
            c.setFillColor(color_k)
            c.drawCentredString(cx_icon, cy_icon - 3, icon_k)
            # number
            num = counts.get(kind, 0)
            c.setFont(BOLD, 14)
            c.setFillColor(TEXT_DARK if not is_active_filter else color_k)
            c.drawCentredString(cx_icon, y_bottom_cards + 6.5*mm, fa_digits(num))
            # label
            c.setFont(MEDIUM, 7.5)
            c.setFillColor(GRAY)
            c.drawCentredString(cx_icon, y_bottom_cards + 2.8*mm, rtl(label_k))
        y = y_bottom_cards - 6*mm
        c.setStrokeColor(_PILL_BORDER)
        c.setLineWidth(0.6)
        c.line(MARGIN, y, PAGE_W - MARGIN, y)
        y -= 4*mm
    else:
        y -= 2*mm
        c.setStrokeColor(_PILL_BORDER)
        c.setLineWidth(0.6)
        c.line(MARGIN, y, PAGE_W - MARGIN, y)
        y -= 4*mm

    return y


def _draw_table_header(c, y: float) -> float:
    x_right = PAGE_W - MARGIN
    y_top = y
    y_bottom = y - TABLE_HEADER_H
    c.setFillColor(NAVY)
    c.roundRect(MARGIN, y_bottom, CONTENT_W, TABLE_HEADER_H, 2.2*mm, fill=1, stroke=0)
    # subtle inner highlight line at top of header
    c.setStrokeColor(HexColor('#2a3a8a'))
    c.setLineWidth(0.7)
    c.line(MARGIN+2*mm, y_top - 1*mm, PAGE_W-MARGIN-2*mm, y_top - 1*mm)
    c.setFont(BOLD, 8.8)
    c.setFillColor(WHITE)
    labels = [
        ('type', 'نوع'),
        ('lesson', 'درس'),
        ('date', 'تاریخ'),
        ('time', 'ساعت'),
        ('location', 'مکان'),
        ('teacher', 'استاد'),
    ]
    cx = x_right
    mid = y_bottom + TABLE_HEADER_H/2 - 1.4*mm
    for key, label in labels:
        w = _COL[key]
        # add tiny dot before label for premium separators (optional)
        c.drawCentredString(cx - w/2, mid, rtl(label))
        cx -= w
        # vertical divider faint white 0.15 opacity
        if key != 'teacher':
            c.saveState()
            c.setStrokeColor(WHITE)
            c.setStrokeAlpha(0.18)
            c.setLineWidth(0.6)
            c.line(cx, y_bottom + 2*mm, cx, y_top - 2*mm)
            c.restoreState()
    return y_bottom


def _draw_row(c, item: dict, y: float):
    """
    Draw premium card-row at y (top). Height = ROW_H, gap handled by caller.
    No zebra — each row is isolated white card with rounded border and type accent.
    """
    # از time_utils مستقیم (بدون وابستگی به telegram)
    def _fmt_jalali_local(ds: str) -> str:
        try:
            from time_utils import format_date_fa
            raw = str(ds or '').strip()[:10]
            if not raw:
                return ''
            return format_date_fa(raw, long=True, weekday=True, date_only=True, fallback=raw)
        except Exception:
            return str(ds or '')
    _fmt = _fmt_jalali_local

    x_right = PAGE_W - MARGIN
    y_top = y
    y_bottom = y - ROW_H

    # card background
    c.setFillColor(WHITE)
    c.roundRect(MARGIN, y_bottom, CONTENT_W, ROW_H, 2.8*mm, fill=1, stroke=0)
    c.setStrokeColor(CARD_BORDER)
    c.setLineWidth(0.7)
    c.roundRect(MARGIN, y_bottom, CONTENT_W, ROW_H, 2.8*mm, fill=0, stroke=1)

    # type accent vertical strip on the right side (type column edge)
    icon, label, color, _, _ = TYPE_STYLE.get(item.get('type', 'class'), TYPE_STYLE['class'])
    accent_w = 3.2 * mm
    accent_h = ROW_H - 4*mm
    accent_y = y_bottom + 2*mm
    accent_x = PAGE_W - MARGIN - accent_w - 0.8*mm
    c.setFillColor(color)
    c.roundRect(accent_x, accent_y, accent_w, accent_h, 1.2*mm, fill=1, stroke=0)

    # vertical dividers between columns (very subtle)
    cx_iter = x_right
    for key in ['type', 'lesson', 'date', 'time', 'location']:
        cx_iter -= _COL[key]
        c.saveState()
        c.setStrokeColor(CARD_BORDER)
        c.setStrokeAlpha(0.55)
        c.setLineWidth(0.45)
        # dashed-like short divider
        c.line(cx_iter, y_bottom + 3*mm, cx_iter, y_top - 3*mm)
        c.restoreState()

    mid = y_bottom + ROW_H/2 - 1.4*mm

    # ── نوع (badge) ──
    w = _COL['type']
    cx_type = x_right - w/2
    badge_w = min(w - 4*mm, 18*mm)
    badge_h = 6.6*mm
    c.setFillColor(color)
    c.roundRect(cx_type - badge_w/2, y_bottom + ROW_H/2 - badge_h/2, badge_w, badge_h, badge_h/2, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont(BOLD, 7.4)
    c.drawCentredString(cx_type, y_bottom + ROW_H/2 - 1.35*mm, rtl(f"{icon} {label}"))

    # ── درس (+ گروه کوچک زیرش اگر لازم) ──
    w = _COL['lesson']
    cx_lesson = x_right - _COL['type'] - w/2
    lesson_raw = (item.get('lesson') or '').strip()
    # group badge under lesson if needed
    grp = (item.get('group') or '').strip()
    show_group = grp not in ('', 'هر دو', 'both', None)
    # wrap lesson
    avail_w = w - 4*mm
    lesson_lines = wrap_rtl(lesson_raw, BOLD, 8.7, avail_w)[:2]
    # if two lines, lift up a bit; if one, centered plus group offset
    if len(lesson_lines) == 2:
        # slightly higher to make room for potential group
        ly = mid + 2.2*mm
        c.setFont(BOLD, 8.7)
        c.setFillColor(TEXT_DARK)
        for line in lesson_lines:
            c.drawCentredString(cx_lesson, ly, line)
            ly -= 3.8*mm
        if show_group:
            # tiny pill below
            g_txt = f"گ{fa_digits(grp)}"
            gw = text_width(g_txt, MEDIUM, 6.2) + 4*mm
            gy = y_bottom + 2.3*mm
            c.setFillColor(HexColor('#eef2ff'))
            c.roundRect(cx_lesson - gw/2, gy, gw, 3.6*mm, 1.8*mm, fill=1, stroke=0)
            c.setFont(MEDIUM, 6.2)
            c.setFillColor(NAVY)
            c.drawCentredString(cx_lesson, gy + 0.55*mm, rtl(g_txt))
    else:
        # single line — center vertically, leave space below for group pill if needed
        c.setFont(BOLD, 9.0)
        c.setFillColor(TEXT_DARK)
        line = lesson_lines[0] if lesson_lines else rtl("—")
        # raise a little if group exists
        y_off = 1.2*mm if show_group else 0
        c.drawCentredString(cx_lesson, mid + y_off, line)
        if show_group:
            g_txt = f"گ{fa_digits(grp)}"
            gw = text_width(g_txt, MEDIUM, 6.2) + 4*mm
            gy = y_bottom + 2.3*mm
            c.setFillColor(HexColor('#eef2ff'))
            c.roundRect(cx_lesson - gw/2, gy, gw, 3.6*mm, 1.8*mm, fill=1, stroke=0)
            c.setFont(MEDIUM, 6.2)
            c.setFillColor(NAVY)
            c.drawCentredString(cx_lesson, gy + 0.55*mm, rtl(g_txt))
    # ── تاریخ (+ روز هفته + شمارش معکوس برای امتحان) ──
    w = _COL['date']
    cx_date = x_right - _COL['type'] - _COL['lesson'] - w/2
    full_date = _fmt(item.get('date', '') or '')
    if '(' in full_date:
        date_part, wd_part = full_date.split('(', 1)
        date_part = date_part.strip()
        wd_part = '(' + wd_part
    else:
        date_part, wd_part = full_date, ''
    c.setFont(BOLD, 8.9)
    c.setFillColor(NAVY_LIGHT)
    if wd_part:
        c.drawCentredString(cx_date, mid + 2.6*mm, rtl(fa_digits(date_part)))
        c.setFont(REGULAR, 6.9)
        c.setFillColor(GRAY)
        c.drawCentredString(cx_date, mid - 1.2*mm, rtl(fa_digits(wd_part)))
    else:
        c.setFont(BOLD, 9)
        c.setFillColor(NAVY_LIGHT)
        c.drawCentredString(cx_date, mid, rtl(fa_digits(date_part)) if date_part else rtl("—"))

    # urgent exam countdown small under date (if exam and within 14 days)
    if item.get('type') == 'exam':
        dl = _days_left(item)
        if dl is not None and dl <= 14:
            # label
            if dl < 0:
                lbl = f"({fa_digits(abs(dl))} روز پیش)"
                col = GRAY
            elif dl == 0:
                lbl = "امروز!"
                col = _EXAM_RED
            elif dl == 1:
                lbl = "فردا!"
                col = HexColor('#e65100')
            elif dl <= 3:
                lbl = f"{fa_digits(dl)} روز دیگر"
                col = _EXAM_RED
            elif dl <= 7:
                lbl = f"{fa_digits(dl)} روز دیگر"
                col = HexColor('#ef6c00')
            else:
                lbl = f"{fa_digits(dl)} روز دیگر"
                col = GRAY
            # only show if near (<=7) or negative? show small chip below weekday
            if dl <= 7 or dl < 0:
                c.setFont(MEDIUM, 6.3)
                c.setFillColor(col)
                # position a bit lower than weekday
                c.drawCentredString(cx_date, y_bottom + 1.6*mm, rtl(lbl))

    # ── ساعت (interval) ──
    w = _COL['time']
    cx_time = x_right - _COL['type'] - _COL['lesson'] - _COL['date'] - w/2
    interval = _fa_interval_for_item(item)
    # flex indicator
    is_flex = item.get('is_flex') or (item.get('flex_type') not in (None, '', 'off') and item.get('flex_type') != 'fixed')
    has_time = bool((item.get('time') or '').strip())
    if has_time:
        c.setFont(MEDIUM, 8.3)
        c.setFillColor(TEXT_DARK)
        txt = rtl(interval)
        c.drawCentredString(cx_time, mid + (1.4*mm if is_flex else 0), txt)
        if is_flex:
            c.setFont(REGULAR, 5.8)
            c.setFillColor(BRAND_GREEN)
            c.drawCentredString(cx_time, y_bottom + 1.9*mm, rtl("🔁 انعطاف‌پذیر"))
    else:
        c.setFont(REGULAR, 8)
        c.setFillColor(GRAY)
        c.drawCentredString(cx_time, mid, rtl("—"))

    # ── مکان (+ آیکون یادداشت) ──
    w = _COL['location']
    cx_loc = x_right - _COL['type'] - _COL['lesson'] - _COL['date'] - _COL['time'] - w/2
    loc_raw = (item.get('location') or '').strip() or '—'
    # notes presence indicator — tiny dot
    notes = (item.get('notes') or '').strip()
    c.setFont(REGULAR, 7.8)
    c.setFillColor(TEXT_DARK)
    loc_line = wrap_rtl(loc_raw, REGULAR, 7.8, w - 3*mm)
    line = loc_line[0] if loc_line else rtl("—")
    y_loc = mid + (1*mm if notes else 0)
    c.drawCentredString(cx_loc, y_loc, line)
    if notes:
        # small note icon + maybe truncated note hint (hidden) — just icon
        c.setFont(REGULAR, 5.5)
        c.setFillColor(NAVY_LIGHT)
        c.drawCentredString(cx_loc, y_bottom + 1.9*mm, rtl("📝 یادداشت"))

    # ── استاد ──
    w = _COL['teacher']
    cx_teacher = MARGIN + w/2
    teacher_raw = (item.get('teacher') or '').strip() or '—'
    c.setFont(REGULAR, 7.8)
    c.setFillColor(TEXT_DARK)
    t_lines = wrap_rtl(teacher_raw, REGULAR, 7.8, w - 3*mm)
    t_line = t_lines[0] if t_lines else rtl("—")
    c.drawCentredString(cx_teacher, mid, t_line)


def _draw_footer(c, page_num: int):
    c.setStrokeColor(CARD_BORDER)
    c.setLineWidth(0.6)
    c.line(MARGIN, FOOTER_Y, PAGE_W - MARGIN, FOOTER_Y)
    c.setFont(REGULAR, 7.2)
    c.setFillColor(GRAY)
    # فوتر حرفه‌ای: تگ ربات با فاصله بیشتر از تاریخ — تاریخ رندر (۱۸ شهریور ۱۴۰۵) از هدر به اینجا منتقل شد
    # سه بخش با بولت‌های با فاصله
    footer_text = f"تولید شده توسط ربات هامزیار    @humsyarbot    •    {fa_digits(_now_tehran_str())}    •    صفحه {fa_digits(page_num)}"
    c.drawCentredString(PAGE_W / 2, FOOTER_Y - 5.2*mm, rtl(footer_text))
    # tiny brand dot
    c.setFillColor(BRAND_GREEN)
    c.circle(PAGE_W/2, FOOTER_Y - 5.2*mm + 8*mm, 0.9*mm, fill=1, stroke=0)



def _weekday_fa(idx: int) -> str:
    # 0=شنبه ... 6=جمعه
    names = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"]
    try:
        return names[int(idx) % 7]
    except:
        return str(idx)


def _should_use_weekly_grid(items: list, stype) -> bool:
    """تشخیص اینکه PDF کلاس باید به‌صورت جدول هفتگی یک‌صفحه‌ای رندر شود نه فهرست ۱۷۲ ردیفی."""
    if not items:
        return False
    # فقط برای کلاس یا همه (که اکثر کلاس است)
    class_items = [it for it in items if (it.get('type') or 'class') == 'class']
    if stype not in (None, 'class') and stype != 'class':
        return False
    if len(class_items) < 20:
        return False
    # اگر الگوی هفتگی تکرار شده باشد، تعداد (weekday, time) متمایز خیلی کمتر از کل است
    try:
        from utils import jalali_weekday_index
    except Exception:
        return False
    distinct = set()
    for it in class_items:
        try:
            wd = jalali_weekday_index(it.get('date') or '')
        except:
            continue
        t = (it.get('time') or '').strip()[:5]
        e = (it.get('end_time') or it.get('time_end') or '').strip()[:5]
        distinct.add((wd, t, e))
    # اگر هر slot هفتگی چندین بار تکرار شده (چند هفته)، distinct خیلی کوچکتر است
    if len(distinct) == 0:
        return False
    # نسبت: اگر هر slot به‌طور متوسط >2.5 بار تکرار شده، یعنی بازه‌ی چند هفته‌ای است
    repeat_ratio = len(class_items) / max(1, len(distinct))
    # همچنین distinct نباید خیلی بزرگ باشد (الگوی هفتگی حداکثر 30 خانه)
    if repeat_ratio >= 2.2 and len(distinct) <= 32 and len(distinct) >= 5:
        return True
    # حالت دیگر: حتی اگر repeat کم باشد ولی تعداد کل >40 و distinct <=25، باز هم جدول هفتگی بهتر است
    if len(class_items) >= 40 and len(distinct) <= 28:
        return True
    return False


def _collect_weekly_slots(items: list):
    """از فهرست تاریخ‌دار، نگاشت (weekday -> {interval_key -> [lessons]} ) می‌سازد."""
    try:
        from utils import jalali_weekday_index
    except:
        return None, None
    # interval -> label
    intervals = {}
    slot_map = {i: {} for i in range(7)}  # 0=شنبه
    for it in items:
        if (it.get('type') or 'class') != 'class':
            continue
        try:
            wd = jalali_weekday_index(it.get('date') or '')
        except:
            continue
        if wd < 0 or wd > 6:
            continue
        start = (it.get('time') or '').strip()[:5]
        end = (it.get('end_time') or it.get('time_end') or '').strip()[:5]
        if not start:
            continue
        # normalize interval key
        if end and end != start:
            key = f"{start}-{end}"
            label = f"{fa_digits(start)} تا {fa_digits(end)}"
        else:
            key = start
            label = fa_digits(start)
        # infer end if missing (1h)
        if not end:
            try:
                h, m = map(int, start.split(':'))
                end = f"{h+2:02d}:{m:02d}" if (h % 2 == 0) else f"{h+1:02d}:{m:02d}"
                # but for 8,10,13,15,17 typical 2h
                # use 2h for even start
                key = f"{start}-{end}"
                label = f"{fa_digits(start)} تا {fa_digits(end)}"
            except:
                pass
        intervals[key] = label
        # keep per slot list of distinct lessons (avoid duplicate same lesson same slot across weeks)
        cell = slot_map[wd].get(key)
        if cell is None:
            slot_map[wd][key] = []
            cell = slot_map[wd][key]
        lesson = (it.get('lesson') or '').strip()
        if not lesson:
            continue
        # dedup by lesson name within same slot
        if lesson not in [x['lesson'] for x in cell]:
            cell.append({
                'lesson': lesson,
                'teacher': (it.get('teacher') or '').strip(),
                'group': (it.get('group') or '').strip(),
                'location': (it.get('location') or '').strip(),
            })
    # sort intervals by start time
    def _p(k):
        try:
            return int(k.split('-')[0].split(':')[0])*60 + int(k.split('-')[0].split(':')[1])
        except:
            return 9999
    sorted_keys = sorted(intervals.keys(), key=_p)
    sorted_labels = [intervals[k] for k in sorted_keys]
    return slot_map, (sorted_keys, sorted_labels)


def _draw_weekly_class_grid(c, y_top: float, slot_map, intervals, group_label: str) -> float:
    """رسم جدول هفتگی کلاس‌ها (شنبه تا پنجشنبه) — یک صفحه، شبیه برگه‌ی دانشگاه."""
    keys, labels = intervals
    # layout: first col weekday, rest intervals
    # total width CONTENT_W, weekday col 22mm, rest split equally
    wd_w = 22 * mm
    avail = CONTENT_W - wd_w
    if not keys:
        return y_top
    col_w = avail / len(keys)
    # header row
    row_h_header = 9 * mm
    row_h = 13 * mm  # per weekday row, enough for 1-2 lessons
    # check fit
    needed = row_h_header + 6 * row_h + 6 * mm
    if y_top - needed < MIN_Y:
        # will be called only when there is space (first page), assume fit
        pass
    x0 = MARGIN
    # draw header background
    y = y_top
    y_header_bottom = y - row_h_header
    c.setFillColor(NAVY)
    c.roundRect(x0, y_header_bottom, CONTENT_W, row_h_header, 2.2*mm, fill=1, stroke=0)
    c.setStrokeColor(HexColor('#2a3a8a'))
    c.setLineWidth(0.7)
    c.line(x0+2*mm, y - 1*mm, x0+CONTENT_W-2*mm, y - 1*mm)
    c.setFont(BOLD, 8.4)
    c.setFillColor(WHITE)
    # RTL: weekday header on the right
    x_wd = x0 + CONTENT_W - wd_w
    c.drawCentredString(x_wd + wd_w/2, y_header_bottom + row_h_header/2 - 1.2*mm, rtl("ایام هفته"))
    # interval headers from right to left (intervals to the left of weekday)
    for idx, lab in enumerate(labels):
        # idx 0 is earliest interval (08-10) should be rightmost among intervals (closest to weekday)
        # So we place intervals from right to left
        rev_idx = len(labels) - 1 - idx
        # Actually keep chronological left-to-right but weekday on right means intervals fill left side
        # For RTL, earliest interval should be rightmost interval column (just left of weekday)
        # So we map idx 0 -> rightmost interval slot
        col_x = x0 + col_w * rev_idx
        cx = col_x + col_w/2
        short = lab.replace(" تا ", " - ")
        c.drawCentredString(cx, y_header_bottom + row_h_header/2 - 1.2*mm, rtl(short))
        if idx < len(labels)-1:
            c.saveState()
            c.setStrokeColor(WHITE)
            c.setStrokeAlpha(0.18)
            c.setLineWidth(0.6)
            cx_line = col_x
            c.line(cx_line, y_header_bottom + 2*mm, cx_line, y - 2*mm)
            c.restoreState()
    # vertical divider between weekday and intervals
    c.saveState()
    c.setStrokeColor(WHITE)
    c.setStrokeAlpha(0.18)
    c.setLineWidth(0.6)
    c.line(x_wd, y_header_bottom+2*mm, x_wd, y-2*mm)
    c.restoreState()

    y = y_header_bottom
    # rows شنبه(0) تا پنجشنبه(5) — جمعه(6) را نمایش نمی‌دهیم چون تعطیل است، ولی اگر داده داشت نشان بده
    display_days = [0,1,2,3,4,5]  # شنبه تا پنجشنبه
    # check if جمعه has any data
    has_friday = any(slot_map.get(6, {}).get(k) for k in keys)
    if has_friday:
        display_days.append(6)

    for d_idx, wd in enumerate(display_days):
        y_row_top = y
        y_row_bottom = y - row_h
        # zebra
        bg = WHITE if d_idx % 2 == 0 else HexColor('#f7f8fc')
        c.setFillColor(bg)
        c.rect(x0, y_row_bottom, CONTENT_W, row_h, fill=1, stroke=0)
        # border
        c.setStrokeColor(CARD_BORDER)
        c.setLineWidth(0.6)
        c.rect(x0, y_row_bottom, CONTENT_W, row_h, fill=0, stroke=1)
        # weekday cell on the RIGHT
        x_wd = x0 + CONTENT_W - wd_w
        c.setFillColor(HexColor('#eef2ff') if d_idx % 2 == 0 else HexColor('#e6ebff'))
        c.rect(x_wd, y_row_bottom, wd_w, row_h, fill=1, stroke=0)
        c.setStrokeColor(CARD_BORDER)
        c.rect(x_wd, y_row_bottom, wd_w, row_h, fill=0, stroke=1)
        c.setFont(BOLD, 8.2)
        c.setFillColor(NAVY)
        c.drawCentredString(x_wd + wd_w/2, y_row_bottom + row_h/2 - 1.1*mm, rtl(_weekday_fa(wd)))
        # vertical line before weekday (left edge of weekday column)
        c.setStrokeColor(CARD_BORDER)
        c.line(x_wd, y_row_bottom, x_wd, y_row_top)
        # cells to the left of weekday
        for col_idx, key in enumerate(keys):
            rev_idx = len(keys) - 1 - col_idx
            cx0 = x0 + col_w*rev_idx
            # vertical divider
            if col_idx > 0:
                c.setStrokeColor(CARD_BORDER)
                c.setStrokeAlpha(0.7)
                c.line(cx0, y_row_bottom, cx0, y_row_top)
                c.setStrokeAlpha(1)
            lessons = slot_map.get(wd, {}).get(key, [])
            if not lessons:
                # dash
                c.setFont(REGULAR, 8)
                c.setFillColor(GRAY)
                c.drawCentredString(cx0 + col_w/2, y_row_bottom + row_h/2 - 1*mm, rtl("—"))
                continue
            # if multiple lessons in same slot (e.g., دختر/پسر), stack vertically
            # limit to 2 lines per cell
            max_show = 2
            to_show = lessons[:max_show]
            # calculate line height
            if len(to_show) == 1:
                # single lesson centered
                lesson = to_show[0]['lesson']
                # wrap
                avail_w = col_w - 3*mm
                lines = wrap_rtl(lesson, MEDIUM, 7.2, avail_w)[:1]
                line = lines[0] if lines else rtl(lesson)
                c.setFont(MEDIUM, 7.2)
                c.setFillColor(TEXT_DARK)
                c.drawCentredString(cx0 + col_w/2, y_row_bottom + row_h/2 + 1*mm, line)
                # teacher small if exists
                teacher = to_show[0]['teacher']
                if teacher and teacher != '—':
                    c.setFont(REGULAR, 5.6)
                    c.setFillColor(GRAY)
                    # truncate
                    t_line = wrap_rtl(teacher, REGULAR, 5.6, avail_w)[:1]
                    t = t_line[0] if t_line else rtl(teacher)
                    c.drawCentredString(cx0 + col_w/2, y_row_bottom + row_h/2 - 2.8*mm, t)
            else:
                # two lessons stacked
                for li, lesson_obj in enumerate(to_show):
                    wy = y_row_top - 4*mm - li*5.2*mm
                    lesson = lesson_obj['lesson']
                    avail_w = col_w - 3*mm
                    lines = wrap_rtl(lesson, MEDIUM, 6.6, avail_w)[:1]
                    line = lines[0] if lines else rtl(lesson)
                    c.setFont(MEDIUM, 6.6)
                    c.setFillColor(TEXT_DARK)
                    c.drawCentredString(cx0 + col_w/2, wy, line)
                    # small group hint if needed
                    grp = lesson_obj['group']
                    if grp and grp not in ('هر دو', ''):
                        c.setFont(REGULAR, 5.0)
                        c.setFillColor(NAVY_LIGHT)
                        # draw tiny group pill below lesson?
                        pass
                if len(lessons) > max_show:
                    c.setFont(REGULAR, 5.2)
                    c.setFillColor(GRAY)
                    c.drawCentredString(cx0 + col_w/2, y_row_bottom + 1.2*mm, rtl(f"+{fa_digits(len(lessons)-max_show)}"))
        y = y_row_bottom
        # horizontal line
        c.setStrokeColor(CARD_BORDER)
        c.setLineWidth(0.5)
        c.line(x0, y, x0+CONTENT_W, y)

    # (subtitle removed per user request)
    y -= 2*mm
    return y

def _consolidate_intervals(items: list) -> list:
    """ادغام جلسات پیوسته‌ی هم‌نام/هم‌گروه/هم‌مکان در یک روز به یک بازه واحد.

    اگر دو سند متوالی با lesson/date/group/type/location/teacher یکسان
    و end_time جلسه‌ی اول == time جلسه‌ی دوم باشد، آن‌ها یک جلسه‌ی
    ۲ساعته (یا بیشتر) هستند که قبلاً به‌صورت دو ردیف ۱ساعته جدا ذخیره
    شده‌اند. این تابع آن‌ها را به یک ردیف با time=start و end_time=end
    ادغام می‌کند تا جدول و PDF «یک درس در یک بازه» را نشان دهند.
    """
    if not items:
        return items
    def _p(t):
        m = __import__('re').match(r'(\d{1,2}):(\d{2})', str(t or '').strip())
        return int(m.group(1))*60+int(m.group(2)) if m else None
    def _f(m):
        return f"{m//60:02d}:{m%60:02d}"
    # sort first
    try:
        items = sorted(list(items), key=lambda it: ((it.get('date') or '9999-12-31')[:10], _p(it.get('time')) or 9999))
    except Exception:
        items = list(items)
    out = []
    for cur in items:
        cur = dict(cur)  # copy to avoid mutating original
        prev = out[-1] if out else None
        if prev and prev.get('date')==cur.get('date') and prev.get('lesson')==cur.get('lesson') and (prev.get('group') or '')==(cur.get('group') or '') and (prev.get('type') or 'class')==(cur.get('type') or 'class') and (prev.get('location') or '')==(cur.get('location') or '') and (prev.get('teacher') or '')==(cur.get('teacher') or ''):
            # فقط دو ردیف ۱ساعته‌ی پشت‌سرهمِ یک درس را ادغام کن (باگ قدیمی ۰۸:۰۰-۰۹:۰۰ + ۰۹:۰۰-۱۰:۰۰ → ۰۸:۰۰ تا ۱۰:۰۰)
            # دو بازه‌ی ۲ساعته‌ی مجزا (مثل ۱۵:۰۰-۱۷:۰۰ + ۱۷:۰۰-۱۹:۰۰) نباید ادغام شوند — هر کدام یک کلاس جدا در ستون خودش است
            prev_start = _p(prev.get('time'))
            prev_end = _p(prev.get('end_time') or prev.get('time_end') or '')
            if prev_end is None and prev_start is not None:
                prev_end = prev_start + 60
                prev_dur = 60
            else:
                prev_dur = (prev_end - prev_start) if (prev_end is not None and prev_start is not None) else None
            cur_start = _p(cur.get('time'))
            cur_end = _p(cur.get('end_time') or cur.get('time_end') or '')
            if cur_end is None and cur_start is not None:
                cur_end = cur_start + 60
                cur_dur = 60
            else:
                cur_dur = (cur_end - cur_start) if (cur_end is not None and cur_start is not None) else None
            # فقط اگر هر دو ۶۰ دقیقه‌ای بودند و پشت‌سرهم بودند، ادغام کن
            if prev_end is not None and cur_start is not None and prev_end == cur_start and cur_end is not None and prev_dur == 60 and cur_dur == 60:
                # extend prev
                prev['end_time'] = _f(cur_end)
                # keep longest notes
                if not prev.get('notes') and cur.get('notes'):
                    prev['notes'] = cur.get('notes')
                # mark merged
                prev['_merged'] = int(prev.get('_merged') or 1) + 1
                continue
        out.append(cur)
    return out


def generate_schedule_pdf(items: list, group_label: str, student_name: str = '', stype: str | None = None) -> bytes:
    """
    items: خروجی db.get_schedules() — لیست دیکشنری با کلیدهای
        type/lesson/teacher/date/time/(end_time|time_end)/location/group/notes/is_flex...
        date به فرمت %Y-%m-%d میلادی
    group_label: برچسب گروه برای هدر
    student_name: نام دانشجو
    stype: اگر مشخص باشد عنوان هدر و هایلایت کارت آماری همان نوع خواهد بود
    """
    ensure_fonts()
    # consolidate legacy split entries before any sorting/header counts
    try:
        items = _consolidate_intervals(items or [])
    except Exception:
        pass
    # sort chronological just in case (by date, then start time)
    def _sort_key(it):
        d = (it.get('date') or '9999-12-31')[:10]
        t = (it.get('time') or '99:99')[:5]
        # type order: exam before class? keep date order primary
        return (d, t, it.get('type',''))
    try:
        items = sorted(list(items or []), key=_sort_key)
    except Exception:
        pass

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    # improve PDF metadata
    try:
        c.setTitle("Hamsyar — برنامه‌ی کلاس/امتحان")
        c.setAuthor("humsyarbot")
    except Exception:
        pass
    page_num = 1

    # پیش‌محاسبه برای هدر: اگر جدول هفتگی استفاده می‌شود، تعداد باید تعداد کلاس‌های یک هفته باشد نه مجموع تاریخ‌دار
    _weekly_for_header = False
    _weekly_header_items = None
    _weekly_header_count = len(items)
    try:
        if _should_use_weekly_grid(items, stype):
            _sm, (_wk_keys, _wk_labels) = _collect_weekly_slots(items) or (None, (None, None))
            if _sm and _wk_keys:
                # تعداد خانه‌های پر در هفته (distinct lessons)
                _weekly_header_count = sum(len(v) for day in _sm.values() for v in day.values())
                # برای کارت‌های آماری هدر: یک لیست مصنوعی با همان تعداد بساز تا _counts درست کار کند
                _weekly_header_items = [{"type":"class"} for _ in range(_weekly_header_count)]
                _weekly_for_header = True
    except Exception:
        pass
    header_count = _weekly_header_count if _weekly_for_header else len(items)
    header_items = _weekly_header_items if _weekly_for_header else items
    y = _draw_header(c, group_label, student_name, header_count, stype=stype, items=header_items)
    # subtle watermark for content pages already drawn via header; redraw faint for new pages later

    if not items:
        # empty state premium
        c.setFillColor(CARD_BG)
        c.roundRect(MARGIN, MIN_Y + 18*mm, CONTENT_W, 26*mm, 4*mm, fill=1, stroke=0)
        c.setStrokeColor(CARD_BORDER)
        c.setLineWidth(0.7)
        c.roundRect(MARGIN, MIN_Y + 18*mm, CONTENT_W, 26*mm, 4*mm, fill=0, stroke=1)
        c.setFont(MEDIUM, 11)
        c.setFillColor(GRAY)
        c.drawCentredString(PAGE_W/2, MIN_Y + 30*mm, rtl("📭 موردی برای نمایش وجود ندارد"))
        c.setFont(REGULAR, 9)
        c.setFillColor(NAVY_LIGHT)
        c.drawCentredString(PAGE_W/2, MIN_Y + 24*mm, rtl("فیلتر گروه یا نوع را تغییر دهید یا بعداً دوباره تلاش کنید."))
        _draw_footer(c, page_num)
        c.save()
        buf.seek(0)
        return buf.getvalue()

    # ── اگر الگوی هفتگی تکرار شده (۱۷۲ ردیف تاریخ‌دار برای ۲۶ خانه‌ی هفتگی)، به‌جای ۱۲ صفحه فهرست، یک جدول هفتگی یک‌صفحه‌ای بکش
    try:
        if _should_use_weekly_grid(items, stype):
            slot_map, intervals = _collect_weekly_slots(items)
            if slot_map and intervals and intervals[0]:
                y_after_grid = _draw_weekly_class_grid(c, y, slot_map, intervals, group_label)
                # برای PDF خالص کلاسی، همین یک صفحه کافی است — دیگر فهرست ۱۷۲ ردیفی را نکش
                is_pure_class = (stype == 'class') or (stype is None and all((it.get('type') or 'class') == 'class' for it in items))
                if is_pure_class:
                    _draw_footer(c, page_num)
                    c.save()
                    buf.seek(0)
                    return buf.getvalue()
                # برای حالت ترکیبی (همه)، بعد از جدول هفتگی، فقط امتحان/جبرانی را به‌صورت فهرست ادامه بده
                remaining = [it for it in items if (it.get('type') or 'class') != 'class']
                if remaining:
                    items = remaining
                    # عنوان فرعی برای بخش بعدی
                    y = y_after_grid - 2*mm
                    c.setFont(BOLD, 9)
                    c.setFillColor(NAVY)
                    c.drawRightString(PAGE_W - MARGIN, y, rtl(" —  ادامه: فهرست امتحانات/جبرانی  — "))
                    y -= 6*mm
                    y = _draw_table_header(c, y)
                    y -= ROW_GAP
                else:
                    _draw_footer(c, page_num)
                    c.save()
                    buf.seek(0)
                    return buf.getvalue()
    except Exception as e:
        logger.exception(f"weekly grid failed, fallback to list: {e}")

    y = _draw_table_header(c, y)
    y -= ROW_GAP  # initial gap

    for item in items:
        needed = ROW_H + ROW_GAP
        if y - needed < MIN_Y:
            _draw_footer(c, page_num)
            c.showPage()
            page_num += 1
            _draw_brand_bar(c)
            # faint watermark on new page
            _draw_watermark(c)
            y = PAGE_H - MARGIN - 8*mm
            y = _draw_table_header(c, y)
            y -= ROW_GAP
        _draw_row(c, item, y)
        y -= ROW_H + ROW_GAP

    _draw_footer(c, page_num)
    c.save()
    buf.seek(0)
    return buf.getvalue()
