# -*- coding: utf-8 -*-
"""
🧩 هسته — کدهای خطای ماشین‌خوان (واحد در هر ۳ لایه)

قبل از W8: هر لایه پیام فارسی hard-coded می‌داد و MiniApp با
  String.includes("اشتراک") حدس می‌زد. نتیجه: تغییر یک پیام = شکست UI.

بعد از W8: هر خطای دسترسی یک `code` ثابت دارد؛ پیام فارسی فقط برای
  نمایش است و می‌تواند تغییر کند بدون شکستن کلاینت.
"""

class Code:
    # اشتراک
    SUB_REQUIRED = "SUB_REQUIRED"          # هیچ اشتراک فعالی ندارد
    SUB_EXPIRED = "SUB_EXPIRED"            # اشتراک منقضی شده
    SUB_PENDING = "SUB_PENDING"            # رسید در انتظار بررسی
    # دسترسی
    FORBIDDEN = "FORBIDDEN"
    NOT_REGISTERED = "NOT_REGISTERED"
    INTAKE_OUT_OF_SCOPE = "INTAKE_OUT_OF_SCOPE"
    INTAKE_NOT_CONFIGURED = "INTAKE_NOT_CONFIGURED"
    CONTENT_ADMIN_ONLY = "CONTENT_ADMIN_ONLY"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    # فیچرگیتینگ (W7)
    FEATURE_DISABLED = "FEATURE_DISABLED"      # kill switch / حالت disabled
    ADMIN_ONLY = "ADMIN_ONLY"                  # فقط مالک
    PLAN_EXCLUDES_FEATURE = "PLAN_EXCLUDES_FEATURE"  # پلن این فیچر را ندارد
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"        # سقف مصرف تمام شده
    POLICY_UNAVAILABLE = "POLICY_UNAVAILABLE"  # خطای موقت سرویس دسترسی
    # ورودی/اعتبارسنجی
    VALIDATION_ERROR = "VALIDATION_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    # عمومی
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"

# نگاشت کد → پیام فارسی پیش‌فرض (قابل override در هر لایه)
DEFAULT_MESSAGE = {
    Code.SUB_REQUIRED: "⚠️ این بخش نیازمند اشتراک فعال است.",
    Code.SUB_EXPIRED: "⌛ اشتراکت تموم شده — برای ادامه تمدید کن.",
    Code.SUB_PENDING: "⏳ رسیدت در انتظار بررسیه — بزودی فعال می‌شه.",
    Code.FORBIDDEN: "⛔ دسترسی نداری.",
    Code.NOT_REGISTERED: "❌ اول /start بزن و ثبت‌نام کن.",
    Code.INTAKE_OUT_OF_SCOPE: "⛔ این مورد خارج از ورودی توست.",
    Code.INTAKE_NOT_CONFIGURED: "⚙️ ورودی نقش‌ات هنوز تنظیم نشده.",
    Code.CONTENT_ADMIN_ONLY: "🎓 فقط ادمین محتوا.",
    Code.PERMISSION_DENIED: "⛔ مجوز لازم را نداری.",
    # W7
    Code.FEATURE_DISABLED: "🛠 این قابلیت فعلاً غیرفعال است.",
    Code.ADMIN_ONLY: "⛔ این قابلیت فعلاً فقط برای مالک سامانه است.",
    Code.PLAN_EXCLUDES_FEATURE: "🔒 پلن فعلی‌ات این قابلیت را ندارد.",
    Code.QUOTA_EXHAUSTED: "📊 سقف مصرف این قابلیت تمام شده است.",
    Code.POLICY_UNAVAILABLE: "⚠️ سرویس دسترسی موقتاً در دسترس نیست؛ دوباره تلاش کن.",
}
