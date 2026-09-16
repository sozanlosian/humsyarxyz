// ── lib/format — موج W2 Design Refactor
// تک‌منبع مشترک قالب‌بندی/امنیت مقدار برای کل مینی‌اپ.
// تا امروز این هلپرها در ۱۵+ فایل کپی شده بودند
// (faNum×۷، number×۱۳، percent×۳، errorText×۷، faDate×۲).
// قرارداد: پیاده‌سازی عیناً همان قبلی — رفتار صفر تغییر.


/* عدد امن نامنفی — برای شمارنده‌ها */
export const number = (value) => {
  const parsed = Number(value);

  return Number.isFinite(parsed)
    ? Math.max(0, parsed)
    : 0;
};


/* درصد امن ۰ تا ۱۰۰ */
export const percent = (value) =>
  Math.min(
    100,
    number(value)
  );


/* رقم‌های فارسی — نمایش هر مقدار */
export const faNum = (value) =>
  String(value ?? '').replace(
    /\d/g,
    (digit) => '۰۱۲۳۴۵۶۷۸۹'[digit]
  );


/* متن امن خطای سرور برای Toast */
export const errorText = (error, fallback) => {
  const detail =
    error?.response?.data?.detail;

  if (typeof detail === 'string') {
    return detail;
  }

  // 🐛 FIX آپلود ویدیو — تایم‌اوت/قطعی شبکه هیچ response ندارند؛ پیام
  // عمومی «عملیات انجام نشد» علت واقعی (اتصال کند/فایل بزرگ) را پنهان
  // می‌کرد. دسته‌بندی شفاف، بدون افشای جزئیات فنی.
  const code = error?.code || '';

  if (code === 'ECONNABORTED' ||
      /timeout/i.test(error?.message || '')) {
    return 'زمان عملیات به پایان رسید — اتصال کند یا فایل خیلی بزرگ است. دوباره تلاش کنید.';
  }

  if (code === 'ERR_NETWORK') {
    return 'اتصال به سرور برقرار نشد — اتصال اینترنت را بررسی کنید.';
  }

  if (error?.response?.status === 413) {
    return 'حجم فایل بیش از حد مجاز است (۴۵ مگابایت).';
  }

  return fallback;
};


/* تاریخ شمسی کوتاه — fallback قابل‌تنظیم
   (Roles: «—» / Profile: «») */
export const faDate = (iso, empty = '—') => {
  if (!iso) {
    return empty;
  }

  const time = new Date(iso).getTime();

  if (!Number.isFinite(time)) {
    return empty;
  }

  try {
    return new Date(
      time
    ).toLocaleDateString('fa-IR');
  } catch {
    return empty;
  }
};


/* تاریخ+ساعت شمسی — برای نمایش‌های مدیریتی (تهران) */
export const faDateTime = (iso, empty = '—') => {
  if (!iso) {
    return empty;
  }

  const time = new Date(iso).getTime();

  if (!Number.isFinite(time)) {
    return empty;
  }

  try {
    return new Date(time).toLocaleString('fa-IR', {
      timeZone: 'Asia/Tehran',
      dateStyle: 'medium',
      timeStyle: 'short',
    });
  } catch {
    return empty;
  }
};


/* روز+ماه شمسی کوتاه — برای لیبل نمودارها */
export const faDayMonth = (iso, empty = '—') => {
  if (!iso) {
    return empty;
  }

  const time = new Date(iso).getTime();

  if (!Number.isFinite(time)) {
    return empty;
  }

  try {
    return new Date(time).toLocaleDateString('fa-IR', {
      timeZone: 'Asia/Tehran',
      day: 'numeric',
      month: 'long',
    });
  } catch {
    return empty;
  }
};


/* ساعت wall-clock «HH:MM» با ارقام فارسی — برای نمایش بازه‌های کلاسی */
export const faTime = (value, empty = '—') => {
  const raw = String(value ?? '').trim();

  if (!raw) {
    return empty;
  }

  if (/^\d{1,2}:\d{2}$/.test(raw)) {
    return raw.replace(/\d/g, (char) => '۰۱۲۳۴۵۶۷۸۹'[Number(char)]);
  }

  const time = new Date(raw).getTime();

  if (!Number.isFinite(time)) {
    return empty;
  }

  try {
    return new Date(time).toLocaleTimeString('fa-IR', {
      timeZone: 'Asia/Tehran',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return empty;
  }
};
