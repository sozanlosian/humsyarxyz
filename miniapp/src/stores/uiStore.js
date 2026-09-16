import { create } from 'zustand';
import { hapticNotif } from '../lib/telegram';

let _id = 0;

/* 🧯 سخت‌سازی: FastAPI در خطاهای اعتبارسنجی
   (422) فیلد detail را به‌صورت لیست/آبجکت
   برمی‌گرداند، نه رشته. اگر همان به Toast
   برسد، رندر آبجکت = کرش کل اپ (صفحه‌ی تاریک).
   هر پیام اینجا به متن امن تبدیل می‌شود. */
const toText = (value) => {
  if (typeof value === 'string' && value.trim()) {
    return value;
  }

  if (Array.isArray(value)) {
    /* خطاهای 422 FastAPI: [{msg, loc, ...}] */
    const parts = value
      .map((item) =>
        typeof item === 'string'
          ? item
          : item?.msg || item?.detail
      )
      .filter(Boolean);

    if (parts.length) {
      return parts.join(' • ');
    }
  }

  if (value && typeof value === 'object') {
    return (
      value.msg ||
      value.detail ||
      'خطای سرور (جزئیات در کنسول)'
    );
  }

  return 'خطایی رخ داد';
};

export const useUIStore = create((set) => ({
  toasts: [],
  toast: (msg, type = 'info', ms = 2600) => {
    const id = ++_id;

    /* ✅ بازخورد لمسی سینک با نوع پیام —
       مثل اپ‌های نیتیو درجه یک */
    if (type === 'success') hapticNotif('success');
    else if (type === 'error') hapticNotif('error');
    else if (type === 'warning') hapticNotif('warning');

    set(s => ({ toasts: [...s.toasts, { id, msg: toText(msg), type }] }));
    setTimeout(() => set(s => ({ toasts: s.toasts.filter(t => t.id !== id) })), ms);
  },

  /* ✅ Onboarding — ورود اول + اجرای دستی از پروفایل.
     onboardingDone فلگ حافظه‌ای نشست جاری است تا اگر
     localStorage در WebView تلگرام سایلنت فیل کرد،
     صفحه معرفی هرگز گیر نکند. */
  showOnboarding: false,
  onboardingDone: false,
  openOnboarding: () => set({ showOnboarding: true, onboardingDone: false }),
  closeOnboarding: () => set({ showOnboarding: false, onboardingDone: true }),
}));
