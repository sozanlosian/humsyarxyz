import {
  useEffect,
} from 'react';

import {
  useNavigate,
} from 'react-router-dom';

import api from '../../lib/api';

import {
  haptic,
} from '../../lib/telegram';


/* ─────────────────────────────────────────────
   🔒 صفحه‌ی قفل اشتراک (Sync با ربات)

   بک‌اند مرجع نهایی است: وقتی GETِ بخش محافظت‌شده
   با 403 + detail='subscription_required' جواب
   بدهد (همان قانونِ واحدِ has_access ربات)،
   صفحه‌های علوم پایه/رفرنس به‌جای کارت خطای
   عمومی این صفحه را می‌آورند. هیچ قضاوتِ
   اشتراکی سمت فرانت انجام نمی‌شود.

   زبان بصری = همان کارت مرجعِ برنامه درسی:
   card-glow + گرادیان hero ــــــــــــــــ */
const BENEFITS = [
  {
    icon: '🔬',
    text: 'همه‌ی محتوای جلسات علوم پایه (ویدیو، جزوه، پاورپوینت)',
  },

  {
    icon: '📖',
    text: 'کتاب‌های مرجع فارسی و لاتین به‌صورت کامل',
  },

  {
    icon: '📥',
    text: 'دانلود مستقیم در تلگرام بدون محدودیت',
  },

  {
    icon: '🔄',
    text: 'دسترسی هم‌زمان در ربات و مینی‌اپ با یک اشتراک',
  },
];



/* تشخیص قفل اشتراک — W8 هسته: بک‌اند {code: SUB_REQUIRED} برمی‌گرداند
   (402 یا 403). برای سازگاری عقب‌رو، رشته‌ی قدیمی هم پذیرفته می‌شود. */
export function isSubscriptionLock(
  error,
) {
  const d = error?.response?.data?.detail;
  const code = typeof d === 'object' ? d?.code : null;
  const msg = typeof d === 'object' ? d?.message : d;
  const status = error?.response?.status;
  if (code === 'SUB_REQUIRED' || code === 'SUB_EXPIRED' || code === 'SUB_PENDING') return true;
  if (status === 402 && code) return true;
  // 🌊 W7 — سهمیه‌ی فیچر (429) هم قفل است؛ ولی ریت‌لیمیت (429 بدون کد سهمیه) نه
  if (status === 429 && code === 'QUOTA_EXHAUSTED') return true;
  return (
    status === 403 &&
    (msg === 'subscription_required' || d === 'subscription_required')
  );
}


/* 🌊 W7 — نوع قفل از روی خطا: بنر/پی‌وال درست + ایونت درست */
export function lockKind(
  error,
) {
  const d = error?.response?.data?.detail;
  const code = typeof d === 'object' ? d?.code : null;
  const feature = typeof d === 'object' ? d?.feature : null;
  if (code === 'FEATURE_DISABLED') return { kind: 'disabled', feature };
  if (code === 'QUOTA_EXHAUSTED') return { kind: 'quota', feature };
  return { kind: 'sub', feature };
}


export default function SubscriptionLock({
  feature = 'این بخش',
  featureKey = '',
  mode = 'sub',
}) {
  const navigate =
    useNavigate();

  /* 🌊 W7 — ایونت دیده‌شدن پی‌وال (best-effort، بدون اثر روی UX) */
  useEffect(() => {
    if (!featureKey) return;
    api.post('/api/subscription/feature-events', {
      feature: featureKey, event: 'paywall_viewed', extra: { mode },
    }).catch(() => {});
  }, [featureKey]);


  const goPlans = () => {
    haptic('light');

    if (featureKey) {
      api.post('/api/subscription/feature-events', {
        feature: featureKey, event: 'subscription_cta_clicked', extra: {},
      }).catch(() => {});
    }

    navigate(
      '/me/subscription',
    );
  };

  const isDisabled = mode === 'disabled';
  const isQuota = mode === 'quota';


  return (
    <section
      className={
        'card card-glow fade-up'
      }
      style={{
        padding: 22,

        textAlign: 'center',

        /* زبان hero ـــ دمِ بنفش برای حس
           «محتوای ویژه» هم‌راستا با شاخه‌ی
           رفرنس/منابع */
        background:
          'linear-gradient(145deg,var(--soft-acc-deep),var(--surf-card) 55%,var(--soft-pur))',
      }}
    >
      <div
        style={{
          display: 'grid',
          width: 66,
          height: 66,
          placeItems: 'center',
          margin: '0 auto',

          background:
            'var(--soft-pur)',

          border:
            '1px solid var(--bd-pur)',

          borderRadius: 'var(--r-lg)',
          fontSize: 30,
        }}
      >
        {isDisabled ? '🛠' : isQuota ? '📊' : '🔒'}
      </div>

      <h2
        style={{
          marginTop: 13,
          fontSize: 'var(--fs-lg)',
          fontWeight: 900,
        }}
      >
        {isDisabled
          ? `${feature} فعلاً غیرفعال است`
          : isQuota
            ? `سقف مصرف ${feature} تمام شد`
            : `${feature} مخصوص مشترک‌هاست`}
      </h2>

      <p
        style={{
          marginTop: 'var(--sp-2)',
          color: 'var(--tx2)',
          fontSize: 'var(--fs-meta)',
          lineHeight: 1.9,
        }}
      >
        {isDisabled
          ? 'این قابلیت موقتاً توسط تیم فنی خاموش شده است؛ به‌زودی برمی‌گردد.'
          : isQuota
            ? 'سهمیه‌ی این دوره تمام شد؛ با شروع دوره‌ی بعد یا ارتقای اشتراک دوباره باز می‌شود.'
            : `برای باز شدن کامل ${feature}، یکی از
        پلن‌های اشتراک را فعال کنید؛ دسترسی
        شما بلافاصله در ربات و مینی‌اپ
        هم‌زمان باز می‌شود.`}
      </p>

      <div
        style={{
          display: 'grid',
          gap: 8,
          marginTop: 15,
          textAlign: 'right',
        }}
      >
        {BENEFITS.map(
          (item) => (
            <div
              key={item.icon}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 'var(--sp-3)',

                padding: '9px 12px',

                background:
                  'var(--ovr)',

                border:
                  '1px solid var(--bd)',

                borderRadius: 'var(--r-md)',
                fontSize: 'var(--fs-cap)',
                lineHeight: 1.7,
              }}
            >
              <span
                style={{
                  fontSize: 'var(--fs-lg)',
                  flexShrink: 0,
                }}
              >
                {item.icon}
              </span>

              <span>{item.text}</span>
            </div>
          ),
        )}
      </div>

      {!isDisabled && (
        <button
          type="button"
          className={
            'btn btn-p btn-full'
          }
          style={{
            marginTop: 16,
          }}
          onClick={goPlans}
        >
          💎 مشاهده پلن‌ها و فعال‌سازی
        </button>
      )}
    </section>
  );
}
