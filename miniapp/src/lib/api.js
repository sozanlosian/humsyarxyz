import axios from 'axios';
import { getInitData } from './telegram';

/* ─────────────────────────────────────────────────────────────
   🚂 مهاجرت Railway — مبدأ API «هم‌ریشه» (same-origin) است

   مینی‌اپ و FastAPI روی یک دامنه‌ی Railway زندگی می‌کنند:
     /app/   → همین SPA
     /api/*  → بک‌اند

   پس درخواست‌ها نسبی (`/api/...`) ساخته می‌شوند و baseURL خالی
   است. این یعنی:
     • هیچ domain بک‌اندی در باندل هاردکد نمی‌شود
     • CORS در production لازم نیست
     • با جابه‌جا شدن دامنه، مینی‌اپ از نو build نمی‌خواهد

   🔒 قانون مهم: هرگز fallback به localhost نگذارید. الگوی قبلی
   (VITE_API_URL يا یک آدرس local به‌عنوان پیش‌فرض) در production با
   env خالی، مرورگر را به localhost خودِ کاربر می‌فرستاد — خرابی کامل
   که فقط روی گوشی‌ِ توسعه‌دهنده کار می‌کرد.

   VITE_API_URL فقط برای یک حالت است: جدا دوختن فرانت از بک‌اند
   (مثلاً build محلی علیه یک API ریموت). اگر ست شده باشد مطلق
   (http/https) باید باشد؛ در غیر این صورت نادیده گرفته می‌شود.
   ───────────────────────────────────────────────────────────── */
const RAW = (import.meta.env?.VITE_API_URL ?? '').trim();

/* فقط یک مبدأ مطلق و معتبر پذیرفته می‌شود؛ هر چیز دیگر = same-origin */
const API_BASE = /^[a-z][a-z0-9+.-]*\/\/[^/]+/i.test(RAW)
  ? RAW.replace(/\/+$/, '')
  : '';

export const API_ORIGIN = API_BASE ||
  (typeof window !== 'undefined' ? window.location.origin : '');

/* لینک‌های preconnect فقط وقتی مفیدند که API روی مبدأ دیگری باشد؛
   در same-origin خودِ صفحه اتصال را باز کرده است. */
try {
  if (
    API_BASE &&
    typeof document !== 'undefined' &&
    API_ORIGIN &&
    API_ORIGIN !== window.location.origin
  ) {
    const preconnect = document.createElement('link');
    preconnect.rel = 'preconnect';
    preconnect.href = API_BASE;

    const dnsPrefetch = document.createElement('link');
    dnsPrefetch.rel = 'dns-prefetch';
    dnsPrefetch.href = API_BASE;

    document.head.append(preconnect, dnsPrefetch);
  }
} catch (_) {
  /* در صورت خطا، بدون preconnect ادامه می‌دهیم */
}

const api = axios.create({
  baseURL: API_BASE,
  timeout: 15000,
  headers: { Accept: 'application/json' },
  /* سشن کوکی وب‌ادمین اینجا مصرف نمی‌شود، ولی برای webhookها
     و deployment های دامنه‌جدا بی‌ضرر است. */
  withCredentials: Boolean(API_BASE),
});

api.interceptors.request.use((config) => {
  const initData = getInitData();

  if (initData) {
    config.headers = config.headers || {};
    config.headers['X-Init-Data'] = initData;
  }

  return config;
});

// 🌊 W4 — offline + retry + online-awareness
if (typeof window !== 'undefined') {
  window.addEventListener('offline', () => window.dispatchEvent(new CustomEvent('app:offline')));
  window.addEventListener('online', () => window.dispatchEvent(new CustomEvent('app:online')));
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error.config || {};
    const status = error.response?.status;
    const detail = error.response?.data?.detail;

    if (detail === 'not_registered') {
      window.dispatchEvent(new CustomEvent('auth:not_registered'));
    } else if (detail === 'pending_approval') {
      window.dispatchEvent(new CustomEvent('auth:pending'));
    } else if (detail === 'suspended') {
      window.dispatchEvent(new CustomEvent('auth:suspended'));
    } else if (status === 401) {
      window.dispatchEvent(new CustomEvent('auth:invalid'));
    }

    // retry: network error (no response) or 5xx / 429
    const shouldRetry = (!error.response && typeof navigator !== 'undefined' && navigator.onLine !== false)
      || (status >= 500 && status < 600)
      || status === 429;
    const isIdempotent = !config.method || ['get','head','options','put','delete'].includes((config.method||'').toLowerCase());
    const maxRetries = (isIdempotent || (config.method||'').toLowerCase() === 'get') ? 2 : 1;
    // exponential backoff: 400ms * 2^retry + jitter
    if (shouldRetry && (config.__retryCount || 0) < maxRetries) {
      config.__retryCount = (config.__retryCount || 0) + 1;
      const retryAfter = parseInt(error.response?.headers?.['retry-after'] || '0', 10);
      const backoff = retryAfter ? retryAfter * 1000 : (400 * Math.pow(2, config.__retryCount - 1) + Math.random() * 200);
      // respect Retry-After for 429
      await new Promise(r => setTimeout(r, Math.min(backoff, 3000)));
      // if offline, wait for online before retry
      if (typeof navigator !== 'undefined' && !navigator.onLine) {
        await new Promise(res => {
          const onOnline = () => { window.removeEventListener('online', onOnline); res(); };
          window.addEventListener('online', onOnline);
          setTimeout(() => { window.removeEventListener('online', onOnline); res(); }, 5000);
        });
      }
      return api(config);
    }

    // offline hint for UI: dispatch global error for toasts
    if (!error.response && typeof navigator !== 'undefined' && !navigator.onLine) {
      window.dispatchEvent(new CustomEvent('app:offline_error', { detail: error }));
    }

    return Promise.reject(error);
  }
);

export default api;
