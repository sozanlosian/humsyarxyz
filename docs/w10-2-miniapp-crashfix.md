# W10.2 — رفع کرش برنامه و اشتراک مینی‌اپ (2026-09-10)

دو کرش زنده از اسکرین‌شات کاربر. هر دو فرانت‌اندی، هر دو با SSR بازتولید و تأیید شدند.

## C-01 — برنامه: `faDate is not defined`

- **فایل:** `miniapp/src/pages/Schedule/index.jsx`
- **علت:** استفاده از `faDate()`/`faNum()` بدون `import` (۶+ فراخوانی در شاخه‌ی لودشده).
  بیلد Vite ارجاع به گلوبال تعریف‌نشده را خطا نمی‌گیرد — فقط در ران‌تایم می‌ترکد.
- **فیکس (۱ خط):** `import { faNum, faDate } from '../../lib/format';`

## C-02 — اشتراک: `Cannot access 'R' before initialization`

- **فایل:** `miniapp/src/pages/Me/Subscription.jsx`
- **علت (TDZ):** افکت resume پرداخت زرین‌پال (W2) آرایه‌ی deps خود
  (`[payments, zp]`، خط ۳۰۱) را **قبل** از `const payments` (خط ۳۴۴) داشت.
  deps هنگام **رندر** خوانده می‌شود، نه هنگام اجرای افکت ⇒
  `Cannot access 'payments' before initialization` که در باندل مینیفای‌شده
  به شکل `Cannot access 'R' before initialization` دیده می‌شد.
- **فیکس:** انتقال کل افکت به بعد از بلاک `const payments` + کامنت نگهبان ترتیب.
  ترتیب فراخوانی هوک‌ها همان دنباله‌ی بدون‌شرط سابق است (قانون هوک‌ها سالم).

## بازتولید (بدون مرورگر)

باندل مسیر با esbuild (`keepNames`) + `renderToString` با QueryClient/Router واقعی:

| سناریو | قبل از فیکس | بعد از فیکس |
|---|---|---|
| اشتراک (رندر اول) | `Cannot access 'payments' before initialization` در خط ۳۰۱ | RENDER OK |
| برنامه (دیتای لودشده) | `faDate is not defined` | RENDER OK + آیتم‌ها در HTML |

## Sweep پیشگیرانه (همین موج)

- **TDZ روی همه‌ی صفحات/کامپوننت‌های مینی‌اپ** (تحلیل استاتیک سفارشی):
  ۷۴ هیت ⇒ هر ۷۴ FP (پارامتر arrow، تگ/اتریبیوت JSX، کال‌بک deferred مثل
  `claimTrial`/`setLockErr`). هیچ TDZ واقعی دیگری نیست.
- **no-undef با ESLint روی هر دو فرانت:** مینی‌اپ و وب‌ادمین (۳۶ فایل) صفر خطا —
  هیچ missing-import دیگری در هیچ‌کدام نیست.
- **چرخه‌ی import (madge):** صفر چرخه.

## تست ماندگار

`tests/test_audit_w10_2.py` (۳ تست): import هلپرهای فرمت در Schedule،
ترتیب اثر/payments در Subscription، و گارد no-undef هلپرها در کل `miniapp/src`.

## دیپلوی

آپلود ۲ فایل `humsyarx-W10.2.zip` در همان مسیرها + ری‌بیلد فرانت.
بدون تغییر بک‌اند/API/دیتابیس.
