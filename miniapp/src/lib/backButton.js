import {
  useEffect,
} from 'react';

import {
  tg,
} from './telegram';


/* ─────────────────────────────────────────────
   کنترل‌کننده‌ی متمرکز BackButton نیتیو تلگرام

   🧯 ریشه‌ی باگ لرزش Back/Close در آزمون:
   هر صفحه به‌تنهایی show()/hide()/onClick()
   را صدا می‌زد و cleanup همان صفحه هر بار
   offClick()+hide() می‌کرد. چون هندلرِ برگشت
   یک arrow function اینلاین بود، با هر رندر
   (تایمر آزمون هر ثانیه رندر می‌کند!) کل چرخه‌ی
   hide→show تکرار می‌شد و دکمه‌ی نیتیو بین
   Back و Close چشمک می‌زد.

   قواعد این ماژول:
   - onClick فقط یک‌بار در کل عمر اپ ثبت می‌شود
     و یک trampoline ثابت است که هندلرِ جاری را
     از ref می‌خواند (تغییر هندلر = هیچ تماس
     دوباره‌ای با API نیتیو)
   - show/hide فقط زمانی صدا زده می‌شود که
     نتیجه واقعاً عوض شود (idempotent)
   - مخفی‌کردن با تأخیر کوتاه انجام می‌شود؛ اگر
     در همان سیکِ کامیت، هدرِ صفحه‌ی بعد ثبت
     شود، مخفی‌کردن لغو می‌گردد — بین دو صفحه‌ی
     دارای Back هیچ گذر Close دیده نمی‌شود
───────────────────────────────────────────── */

let registered = false;

let ownerId = 0;

let nextId = 0;

let lastVisible = null;

let hideTimer = 0;

let currentHandler = null;


function backApi() {
  return tg?.BackButton ?? null;
}


function fire() {
  try {
    currentHandler?.();
  } catch (_) {
    // هندلرِ بازگشت صفحه از کار افتاده — نباید
    // هیچ‌وقت به کرش کل اپ تبدیل شود
  }
}


function ensureRegistered() {
  const api = backApi();

  if (registered || !api) {
    return;
  }

  try {
    api.onClick(fire);
    registered = true;
  } catch (error) {
    console.warn(
      '[back-button]',
      error,
    );
  }
}


function setVisible(visible) {
  const api = backApi();

  if (!api || lastVisible === visible) {
    return;
  }

  try {
    if (visible) {
      api.show();
    } else {
      api.hide();
    }

    lastVisible = visible;

  } catch (error) {
    console.warn(
      '[back-button]',
      error,
    );
  }
}


/* مخفی‌کردن مستقیم برای صفحه‌های تمام‌صفحه
   (Auth/Register/Onboarding) — از همان کانالِ
   مدیریت‌شده می‌رود تا lastVisible با واقعیت
   هرگز ناسازگار نشود و show بعدی گم نشود */
export function hideBackButton() {
  clearTimeout(hideTimer);
  ownerId = 0;
  currentHandler = null;
  setVisible(false);
}


export function useTelegramBack(
  visible,
  handler,
) {
  /* جایگزینی بی‌صدای هندلر با هر رندر —
     هیچ تماسی با API نیتیو نمی‌گیرد؛ همین‌جا
     نقطه‌ی مُهر لرزش تایمر آزمون است */
  useEffect(() => {
    currentHandler = handler;
  });


  useEffect(() => {
    ensureRegistered();

    clearTimeout(hideTimer);

    const id = ++nextId;

    ownerId = id;

    const want = Boolean(visible);

    /* show/hide فقط در صورت تغییر واقعی وضعیت:
       صفحه‌ی back=false بلافاصله مخفی می‌کند تا
       دکمه با محتوای صفحه هماهنگ بماند */
    setVisible(want);


    return () => {
      if (ownerId !== id) {
        return;
      }

      ownerId = 0;
      currentHandler = null;
      clearTimeout(hideTimer);

      /* مخفی‌کردنِ واقعی را یک نبض عقب بینداز —
         اگر هدرِ صفحه‌ی بعد در همان ترنزیشن
         ثبت شود (مثل گذر بین دو صفحه‌ی Backدار)
         این مخفی‌کردن لغو می‌شود و دکمه هرگز
         Back⇄Close چشمک نمی‌زند؛ اگر واقعاً
         صفحه‌ای بدون هدر بیاید، بعد از نبضِ
         کوتاه مخفی می‌شود */
      if (!want) {
        setVisible(false);
        return;
      }

      hideTimer = setTimeout(
        () => {
          if (ownerId === 0) {
            setVisible(false);
          }
        },
        120,
      );
    };

    // ترتیب ثابت هوک‌ها؛ visible در deps است تا
    // تغییر prop صفحه (back=false↔true) بلافاصله
    // در دکمه‌سیوهمجو منعکس شود
    // eslint-disable-next-line
    // react-hooks/exhaustive-deps
  }, [visible]);
}
