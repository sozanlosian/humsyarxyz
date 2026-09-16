/* ─────────────────────────────────────────────
   سامانه‌ی برگشتِ یکپارچه‌ی مینی‌اپ

   هر سه مصرف‌کننده — دکمه‌ی Header، ژست سوایپ
   از لبه و BackButton نیتیو تلگرام — از همین
   تابع واحد استفاده می‌کنند تا رفتار برگشت در
   کل پروژه کاملاً قابل‌پیش‌بینی بماند:

   ۱) onBack صریح (ویوهای داخلی/فرم چندمرحله‌ای)
   ۲) backTo صریح
   ۳) صفحه‌ی قبلی داخل مینی‌اپ (history.back)
   ۴) مسیر والدِ استخراج‌شده از URL (دیپ‌لینک،
      رفرش، ورود از اعلان — هیچ بن‌بستی)
───────────────────────────────────────────── */


/* صفحات ریشه‌ی تب‌بار — این‌ها «خانه» هستند و
   هدف برگشت ندارند (دکمه‌ی برگشت در آن‌ها مخفی
   و ژست سوایپ غیرفعال است) */
export const ROOT_PATHS = new Set([
  '/',
  '/learn',
  '/schedule',
  '/grades',
  '/me',
]);


/* آیا تاریخچه مرورگر صفحه‌ی قبلی داخل مینی‌اپ
   دارد؟ (react-router در history.state.idx
   موقعیت فعلی را نگه می‌دارد) */
export function canGoBackInApp() {
  try {
    const state = window.history.state;

    return (
      typeof state?.idx === 'number' &&
      state.idx > 0
    );

  } catch (_) {
    return false;
  }
}


/* مسیر والد را از آدرس استخراج می‌کند؛
   /admin/content/questions → /admin/content
   /me/tickets              → /me

   قطعاتِ پارامترمانند (آی‌دی ObjectId،
   legacy، یا قطعه‌ی تک‌حرفی مثل «c» در
   /ai/c/:id) پی‌درپی حذف می‌شوند تا نقطه‌ی
   فرود همیشه یک صفحه‌ی واقعی باشد:
   /ai/c/507f… → /ai    /ai/c/legacy → /ai */
export function deriveParentPath(pathname) {
  const parts = pathname
    .split('/')
    .filter(Boolean);

  parts.pop();

  const looksLikeParam = (segment) =>
    /^[a-f0-9]{20,}$/i.test(segment) ||
    segment === 'legacy' ||
    segment.length <= 1;

  while (
    parts.length > 1 &&
    looksLikeParam(parts[parts.length - 1])
  ) {
    parts.pop();
  }

  return parts.length
    ? `/${parts.join('/')}`
    : '/';
}


export function isRootPath(pathname) {
  return ROOT_PATHS.has(pathname);
}


/* آیا برای این مسیر، هدف برگشتِ معناداری هست؟
   (برای فعال‌بودن ژست سوایپ و نمایش دکمه) */
export function hasBackTarget(pathname) {
  return !isRootPath(pathname);
}


/* حل‌واجرای برگشت — خروجی: true اگر ناوبری انجام شد */
export function navigateBack({
  navigate,
  pathname,
  onBack,
  backTo,
}) {
  if (typeof onBack === 'function') {
    onBack();
    return true;
  }

  const fallback =
    backTo || deriveParentPath(pathname);

  if (canGoBackInApp()) {
    navigate(-1);
    return true;
  }

  if (
    !isRootPath(pathname) &&
    pathname !== fallback
  ) {
    navigate(fallback, { replace: true });
    return true;
  }

  return false;
}
