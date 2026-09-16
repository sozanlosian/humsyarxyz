# -*- coding: utf-8 -*-
"""🎛 W7 — کاتالوگ مرکزی فیچرها (leaf: بدون هیچ وارداتی).

تک‌منبع حقیقت «چه فیچری وجود دارد». استخراج‌شده از کد واقعی
(روترها/ماژول‌های ربات) — نه از حدس:
- enforced=True یعنی نقطه‌ی اعمال (API/Bot/MiniApp) همین امروز سیم‌کشی است؛
- enforced=False یعنی «policy-ready»: سوییچ ادمین از امروز کار می‌کند و
  نقطه‌ی اعمال با اولین نیاز گیت می‌خورد (بدون تغییر معماری).

حالت‌های access: free | subscription | admin_only | disabled
- حالت TRIAL جداگانه نداریم (تصمیم W7): tier تریال با
  access=subscription + trial_allowed=True/False بیان می‌شود؛
  تریال plan_id ارزان‌ترین پلن را دارد پس entitlements پلن را به ارث می‌برد.
- quota.kind: none | daily | monthly (0 = نامحدود).
"""
from __future__ import annotations

ACCESS_MODES = ("free", "subscription", "admin_only", "disabled")
QUOTA_KINDS = ("none", "daily", "monthly")

# key → spec. ترتیب = ترتیب نمایش در پنل ادمین.
FEATURE_CATALOG: dict = {
    # ── enforced از روز اول ──
    "question_bank": {
        "label": "بانک سؤال", "category": "content",
        "desc": "بانک سؤال، تمرین، تاریخچه پاسخ‌گویی",
        "enforced": True, "quota_kind": "none",
    },
    "resources": {
        "label": "منابع علوم پایه", "category": "content",
        "desc": "ویدیو/جزوه/پاورپوینت جلسات",
        "enforced": True, "quota_kind": "none",
    },
    "references": {
        "label": "رفرنس‌ها", "category": "content",
        "desc": "کتاب‌های مرجع فارسی و لاتین",
        "enforced": True, "quota_kind": "none",
    },
    "ai_chat": {
        "label": "هوشیار (گفتگو)", "category": "ai",
        "desc": "پرسش متنی/چندرسانه‌ای از هوشیار",
        "enforced": True, "quota_kind": "daily",
    },
    "ai_image": {
        "label": "ساخت تصویر", "category": "ai",
        "desc": "تولید تصویر با هوش مصنوعی",
        "enforced": True, "quota_kind": "daily",
    },
    "ai_practice": {
        "label": "تمرین‌ساز هوشمند", "category": "ai",
        "desc": "تولید تمرین با AI از بانک سؤال",
        "enforced": True, "quota_kind": "daily",
    },
    "mock_exam": {
        "label": "آزمون آزمایشی", "category": "exam",
        "desc": "ساخت و اجرای آزمون (custom-exam)",
        "enforced": True, "quota_kind": "none",
    },
    "pdf_generation": {
        "label": "تولید PDF آزمون", "category": "exam",
        "desc": "خروجی PDF کارنامه/سؤالات",
        "enforced": True, "quota_kind": "monthly",
    },
    # ── policy-ready (سوییچ فعال، نقطه‌ی اعمال بعدی) ──
    "schedule": {
        "label": "برنامه درسی", "category": "study",
        "desc": "برنامه کلاسی و امتحانات",
        "enforced": False, "quota_kind": "none",
    },
    "grades": {
        "label": "نمرات", "category": "study",
        "desc": "کارنامه و نمرات",
        "enforced": False, "quota_kind": "none",
    },
    "tickets": {
        "label": "تیکت پشتیبانی", "category": "support",
        "desc": "گفتگو با پشتیبانی",
        "enforced": False, "quota_kind": "none",
    },
    "wallet": {
        "label": "کیف پول", "category": "money",
        "desc": "موجودی و تراکنش‌ها",
        "enforced": False, "quota_kind": "none",
    },
    "analytics": {
        "label": "داشبورد و تحلیل", "category": "insight",
        "desc": "آمار مطالعه، لیدربورد، فید",
        "enforced": False, "quota_kind": "none",
    },
    "global_search": {
        "label": "جستجوی سراسری", "category": "utility",
        "desc": "جستجو در همه‌ی محتوا",
        "enforced": False, "quota_kind": "none",
    },
}


def default_policy(feature: str) -> dict:
    """پالیسی پیش‌فرض FREE (W7: ارزش امروز آزاد، سوییچ از امروز)."""
    spec = FEATURE_CATALOG.get(feature, {})
    return {
        "_id": feature,
        "enabled": True,
        "access": "free",
        "trial_allowed": True,
        "quota": {"kind": spec.get("quota_kind", "none"), "limit": 0},
        "fail_open": None,  # None = خودکار (free→باز، بقیه→بسته)
        "note": "",
        "pending_access": None,
        "effective_from": None,
        "prev": None,
        "updated_at": None, "updated_by": 0, "updated_by_name": "",
    }
