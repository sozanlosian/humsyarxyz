"""
🔤 qbank.fonts_rtl — فونت فارسی + کمک‌کننده‌های راست‌چین (RTL)

این ماژول تنها مسئولیتش متن است: ثبت فونت Vazirmatn، شکل‌دهی صحیح
حروف فارسی (reshape)، ترتیب‌دهی راست‌به‌چپ (bidi)، و تقسیم متن به خطوط
متناسب با عرض موجود (word-wrap). هیچ منطق طراحی یا دیتابیسی اینجا نیست.
"""
import os
import logging

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger(__name__)

_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')
_READY = False

# نام فونت‌های ثبت‌شده — بقیه‌ی ماژول‌ها همین ثابت‌ها را import می‌کنند
REGULAR = 'Vazir'
MEDIUM  = 'Vazir-Medium'
BOLD    = 'Vazir-Bold'


def ensure_fonts():
    """ثبت فونت‌ها در reportlab — idempotent (فقط بار اول واقعاً کاری می‌کند)"""
    global _READY
    if _READY:
        return
    try:
        pdfmetrics.registerFont(TTFont(REGULAR, os.path.join(_FONT_DIR, 'Vazirmatn-Regular.ttf')))
        pdfmetrics.registerFont(TTFont(MEDIUM,  os.path.join(_FONT_DIR, 'Vazirmatn-Medium.ttf')))
        pdfmetrics.registerFont(TTFont(BOLD,    os.path.join(_FONT_DIR, 'Vazirmatn-Bold.ttf')))
        _READY = True
    except Exception:
        logger.exception("qbank.fonts_rtl: خطا در بارگذاری فونت Vazirmatn")
        raise


_FA_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')


def fa_digits(value) -> str:
    """تبدیل اعداد لاتین به فارسی — 12 → ۱۲"""
    return str(value).translate(_FA_DIGITS)


def _reshape(text: str) -> str:
    """اتصال صحیح حروف فارسی به هم (شکل ابتدایی/میانی/پایانی/جدا)"""
    return arabic_reshaper.reshape(text or '')


def rtl(text: str) -> str:
    """آماده‌سازی یک تکه متنِ تک‌خطی برای drawString با جهت درست"""
    return get_display(_reshape(text or ''))


def text_width(text: str, font: str, size: float) -> float:
    """عرض واقعی متنِ شکل‌دهی‌شده (نه متن خام) — برای layout دقیق"""
    return pdfmetrics.stringWidth(_reshape(text or ''), font, size)


def wrap_rtl(text: str, font: str, size: float, max_width: float) -> list:
    """
    Word-wrap متن فارسی برای عرض مشخص.

    نکته‌ی فنی مهم: عرض هر خط باید روی متنِ shape-شده (نه bidi-شده)
    اندازه‌گیری شود، و bidi باید جداگانه روی هر خطِ *کامل* اجرا شود —
    نه روی کل پاراگراف و نه کلمه‌به‌کلمه. اجرای bidi روی واحد اشتباه
    باعث می‌شود کلمات در جای غلط ظاهر شوند.
    """
    text = (text or '').strip()
    if not text:
        return []
    words = text.split(' ')
    lines, cur = [], []
    for w in words:
        trial = cur + [w]
        width = pdfmetrics.stringWidth(_reshape(' '.join(trial)), font, size)
        if width <= max_width or not cur:
            cur = trial
        else:
            lines.append(' '.join(cur))
            cur = [w]
    if cur:
        lines.append(' '.join(cur))
    return [get_display(_reshape(l)) for l in lines]
