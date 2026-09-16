# 🌊 W9 — ورک‌فلو وضعیت تیکت

## وضعیت‌ها

`open` (باز) → `in_progress` (در حال بررسی) → `waiting_user` (منتظر کاربر)
→ `resolved` (حل‌شده) → `closed` (بسته)

## ماتریس گذار مجاز

| از \ به | open | in_progress | waiting_user | resolved | closed |
|---|---|---|---|---|---|
| open | – | ✅ | ❌ | ✅ | ✅ |
| in_progress | ✅ | – | ✅ | ✅ | ✅ |
| waiting_user | ❌ | ✅ | – | ✅ | ✅ |
| resolved | ❌ | ✅ | ❌ | – | ✅ |
| closed | ❌ | ✅ (reopen) | ❌ | ❌ | – |

- گذار نامعتبر از API ⇒ `۴۰۹`، از ربات ⇒ پیام «گذار مجاز نیست».
- تغییر هم‌زمان دو ادمین ⇒ آپدیت شرطی + ۱ retry؛ اگر نشد `race` (۴۰۹)
  به‌جای last-write-wins کور.

## گذار خودکار (reply)

- پاسخ پشتیبانی روی `open/in_progress/resolved` ⇒ `waiting_user`
- پاسخ دانشجو (`[دانشجو]`) روی `waiting_user/resolved` ⇒ `in_progress`
  (یعنی پیگیری روی تیکت حل‌شده = بازگشایی ضمنی)
- best-effort: خطای گذار هرگز خود reply را خراب نمی‌کند.

## reopen

فقط از `closed/resolved` به `in_progress`؛ بقیه no-op. در همه‌ی مسیرها
(تکی/گروهی/ربات) با before/after audit می‌شود.

## مسئول غیرفعال

- assign همچنان موقع تخصیص پرم `tickets.reply` را چک می‌کند.
- اگر بعداً پرم سلب شد: **سلب خودکار ممنوع** — فقط ⚠️ در ربات/وب‌ادمین
  نمایش داده می‌شود تا ادمین reassigned کند.

## Audit

تغییر وضعیت/اولویت (ربات + API)، پاسخ، بستن/بازگشایی (تکی + گروهی)،
افزودن/ویرایش/حذف canned — همه با before/after در `audit_logs`.

## canned

فیلد `category` (۴۰ کاراکتر) + فیلتر سمت سرور (`?category=`) و فیلتر
دسته در مودال وب‌ادمین. رکوردهای قدیمی بدون دسته = «بدون دسته».
