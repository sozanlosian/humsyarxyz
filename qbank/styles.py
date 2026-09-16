"""
🎨 qbank.styles — رنگ‌ها، اندازه‌ها و ثابت‌های طراحی

همه‌ی مقادیر ظاهری PDF یک‌جا اینجا هستند — برای «شخصی‌سازی قالب PDF»
(یکی از قابلیت‌های توسعه‌ی آینده‌ی خواسته‌شده) کافیست همین فایل تغییر
کند؛ هیچ رنگ یا اندازه‌ی hardcode‌شده‌ای در بقیه‌ی ماژول‌ها نیست.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor

# ── ابعاد صفحه ──
PAGE_W, PAGE_H = A4
MARGIN    = 16 * mm
CONTENT_W = PAGE_W - 2 * MARGIN
FOOTER_Y  = 14 * mm
MIN_Y     = FOOTER_Y + 10 * mm  # کمترین ارتفاعی که قبل از page-break مجازه

# ── رنگ‌های اصلی برند (هامیار) ──
BRAND_GREEN      = HexColor('#1fae5e')
BRAND_GREEN_DARK = HexColor('#159052')
NAVY             = HexColor('#1a2456')
NAVY_LIGHT       = HexColor('#3a4a8c')

# ── رنگ‌های خنثی ──
TEXT_DARK   = HexColor('#20242c')
TEXT_BODY   = HexColor('#4b5563')
GRAY        = HexColor('#8a919c')
WHITE       = HexColor('#ffffff')

# ── کارت سوال ──
CARD_BG     = HexColor('#fbfbfc')
CARD_BORDER = HexColor('#e6e8ec')
OPT_BG      = HexColor('#f3f4f6')
OPT_BORDER  = HexColor('#e3e5e9')

# ── سطح سختی ──
DIFF_STYLE = {
    'آسان':  (HexColor('#1e8e5a'), HexColor('#e6f6ee')),
    'متوسط': (HexColor('#b8860b'), HexColor('#fdf3d9')),
    'سخت':   (HexColor('#c62828'), HexColor('#fbe9e9')),
}

OPT_LETTERS = ['الف', 'ب', 'ج', 'د', 'ه', 'و']

# ── فونت‌ها (اندازه‌ها) ──
FS_TITLE    = 22
FS_SUBTITLE = 13
FS_META     = 10
FS_QUESTION = 12
FS_OPTION   = 10
FS_ANSWER   = 10.5
FS_EXPL     = 9.5
FS_FOOTER   = 8


def normalize_difficulty(raw: str) -> str:
    """
    سطح سختی در دیتابیس ممکن است با ایموجی ذخیره شده باشد (مثلاً
    'متوسط 🟡'). این تابع فقط کلمه‌ی فارسی خالص را برای تطبیق با
    رنگ‌بندی DIFF_STYLE استخراج می‌کند.
    """
    raw = (raw or '').strip()
    for key in DIFF_STYLE:
        if raw.startswith(key):
            return key
    return 'متوسط'
