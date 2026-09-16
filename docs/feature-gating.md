# 🎚 فیچرگیتینگ مرکزی (W7) — FREE NOW, PAY LATER

> همه‌ی قابلیت‌های ارزشمند **امروز رایگان‌اند**؛ زیرساخت کامل اشتراک/دسترسی
> از **پنل وب → دسترسی فیچرها** بدون کدنویسی و بدون deploy قابل فعال‌سازی است.

## ۱. معماری

```
کاتالوگ (core/features.py) ── قرارداد ثابت: ۱۴ فیچر، حالت‌ها، پیش‌فرض‌ها
        │
پالیسی (Mongo: feature_policies) ── یک سند برای هر فیچر + prev برای rollback
        │
تصمیم (core/access.py :: check_feature) ── تنها مرجع تصمیم کل محصول
        ├── ربات (subscription.feature_allowed / check_and_show_paywall)
        ├── API (api/auth.require_feature + require_feature_access)
        └── مینی‌اپ (نقشه‌ی features در sub-status + پی‌وال — فقط UX؛ امنیت با بک‌اند)
```

**سه لایه‌ی مستقل:** ‏`enabled` (kill-switch) ≠ ‏`access` (free/subscription/admin_only/disabled)
≠ سهمیه (`quota.kind/limit` + مصرف اتمیک). ترتیب ارزیابی: flag ← access ←
کاربر/trial/پلن ← سهمیه (peek).

## ۲. حالت‌های دسترسی

| حالت | یعنی | مالک |
|---|---|---|
| `free` | باز برای همه (پیش‌فرض همه) | باز |
| `subscription` | نیازمند اشتراک فعال (trial طبق `trial_allowed`) | بای‌پس |
| `admin_only` | فقط مالک | باز |
| `disabled` | بسته برای همه (kill-switch دوم) | **بسته** |
| `enabled=false` | kill-switch اصلی | **بسته** |

سوییچ قدیمی `subscription_enforced` حالا **ماکرو** است: روی هر ۳ پالیسی
`question_bank/resources/references` می‌نویسد (مایگریشن v4 همین را منتقل کرد).

## ۳. عملیات از پنل وب (🎚 دسترسی فیچرها)

- **روشن/خاموش:** kill-switch؛ خاموش = بسته حتی برای مالک.
- **حالت دسترسی:** تغییر free ←→ subscription بدون deploy (اثر ≤ ۶۰ ثانیه؛ کش با ابطال خودکار).
- **تریال:** اگر خاموش، کاربر trial پیام «دوره‌ی آزمایشی شامل این قابلیت نیست» می‌گیرد.
- **سهمیه:** روزانه/ماهانه + سقف؛ API مصرف واقعی را اتمیک کم می‌کند (۴۲۹ در اتمام).
- **زمان‌بندی:** `pending_access` + `effective_from` (ISO) — مثلاً «از اول آذر اشتراکی».
- **rollback:** هر ذخیره نسخه‌ی قبلی را نگه می‌دارد؛ rollback دوباره = redo.
- **audit:** هر تغییر با before/after ثبت می‌شود؛ اگر audit شکست بخورد تغییر **برگردانده می‌شود**.

## ۴. entitlement پلن‌ها

هر پلن نقشه‌ی `entitlements` دارد (چک‌باکس در مودال پلن، تب مالی).
خالی/ناقص = **سازگار عقب‌رو (دسترسی کامل)**؛ فقط `false` صریح می‌بندد.
پس پلن‌های قدیمی با فعال‌سازی subscription هیچ‌چیز از دست نمی‌دهند.

## ۵. کدهای خطای API (detail.code)

`SUB_REQUIRED / SUB_PENDING / SUB_EXPIRED` (۴۰۲) • `FEATURE_DISABLED / ADMIN_ONLY /
PLAN_EXCLUDES_FEATURE` (۴۰۲) • `QUOTA_EXHAUSTED` (۴۲۹) • `POLICY_UNAVAILABLE` (۵۰۳ موقت)
• `FORBIDDEN` (۴۰۳ فیچر ناشناخته). پیام فارسی `detail.message` نمایشی است؛ کلاینت
فقط روی `code` تصمیم می‌گیرد.

## ۶. fail-safe

- خوانش پالیسی ناموفق + کش موجود ⇒ **کش کهنه** (بهتر از تصمیم کور).
- خوانش ناموفق + بی‌کش ⇒ ‏۵۰۳ صادقانه (نه allow کور، نه deny دروغین).
- peek سهمیه ناموفق ⇒ ‏None (fail-open در مشاهده؛ مصرف واقعی اتمیک و صادقانه است).

## ۷. ایونت‌ها (Mongo: feature_events، TTL سی‌روزه)

`feature_denied / quota_exhausted / trial_feature_used / feature_policy_changed /
paywall_viewed / subscription_cta_clicked` — دو تای آخر را مینی‌اپ می‌فرستد
(`POST /api/subscription/feature-events`، allow-listed).

## ۸. تست

`tests/test_w7_access.py` — ‏۲۸ تست: FREE/SUB/TRIAL/DISABLED/ADMIN_ONLY/QUOTA/
زمان‌بندی/کش+ابطال/fail-safe/rollback+redo/race مصرف/مایگریشن v4.
