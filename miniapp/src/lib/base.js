/* ─────────────────────────────────────────────────────────────
   🚂 مبدأ (base) که مینی‌اپ زیر آن سرو می‌شود — تک‌منبع حقیقت

   مقدار در build توسط Vite از `base` (vite.config.js ← VITE_BASE)
   داخل import.meta.env.BASE_URL تزریق می‌شود. اینجا همان را به
   دو شکل سالم بیرون می‌دهیم:

     APP_BASE        → با اسلش پایانی، برای پرش‌های location.*
                       («/app/») — تا مقصد هرگز ریشه‌ی دامنه نشود
     ROUTER_BASENAME → بدون اسلش پایانی، برای <BrowserRouter basename>
                       («/app») — و در حالت ریشه undefined

   چرا APP_BASE لازم است؟
   `window.location.replace('/')` زیر /app/ یعنی «برو ریشه‌ی دامنه»
   که آنجا دیگر مینی‌اپ نیست (روی Railway ریشه redirect است، ولی در
   هر استقرار دیگری ممکن است ۴۰۴ بدهد). همه‌ی پرش‌های دستی باید از
   این ثابت استفاده کنند.
   ───────────────────────────────────────────────────────────── */

const RAW_BASE = import.meta.env.BASE_URL || '/';

export const APP_BASE =
  RAW_BASE === '/' ? '/' : RAW_BASE.replace(/\/+$/, '') + '/';

export const ROUTER_BASENAME =
  RAW_BASE === '/' ? undefined : RAW_BASE.replace(/\/+$/, '');

/** یک مسیر منطقی مینی‌اپ (مثل '/schedule') را به URL کامل تبدیل می‌کند. */
export function appUrl(path = '') {
  if (/^(?:[a-z][a-z0-9+.-]*:)?\/\//i.test(path)) return path; // کامل
  const tail = path && !path.startsWith('/') ? `/${path}` : path;
  return APP_BASE === '/' ? (tail || '/') : `${APP_BASE.replace(/\/$/, '')}${tail}`;
}
