import {
  useEffect,
  useState,
} from 'react';

import {
  tg,
  haptic,
} from '../../lib/telegram';

import {
  hideBackButton,
} from '../../lib/backButton';

import {
  useAuthStore,
} from '../../stores/authStore';

import {
  useUIStore,
} from '../../stores/uiStore';


const STORAGE_KEY =
  'humsyar_onboarded_v1';


export function hasSeenOnboarding() {
  try {
    return Boolean(
      localStorage.getItem(STORAGE_KEY)
    );
  } catch (_) {
    /* در بعضی WebView ها دسترسی به
       localStorage خطا می‌دهد */
    return true;
  }
}


function markOnboardingSeen() {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      '1'
    );
  } catch (_) {
    /* مهم نیست — فلگ حافظه‌ای نشست
       جاری کار را انجام می‌دهد */
  }
}


const SLIDES = [
  {
    icon: '🩺',
    title: 'به هامزیار خوش اومدی!',

    text:
      'دستیار کامل تو برای مسیر دانشجویی پزشکی؛\nسؤال، جزوه، برنامه کلاسی، نمره و پشتیبانی — همه توی یک‌جا.',

    tint:
      'var(--soft-acc-2)',

    gradient:
      'linear-gradient(135deg,var(--acc-dim),var(--acc))',
  },

  {
    icon: '🤖',
    title: 'هوشیار؛ دستیار هوشمند',

    text:
      'هر مبحثی رو ساده بخواه، از متن جزوه‌هات سؤال بساز\nیا عکس پاورپوینت بفرستی تا برات توضیحش بده.',

    tint:
      'var(--soft-pur)',

    gradient:
      'linear-gradient(135deg,var(--pur-dim),var(--t-pur))',
  },

  {
    icon: '🧪',
    title: 'تمرین و آزمون هدفمند',

    text:
      'از نقاط ضعفت شروع کن؛ هر پاسخ غلط به «ضعف‌ها» اضافه می‌شه\nتا مرور بعدی دقیقاً سراغ همون‌ها بری.',

    tint:
      'var(--soft-ok)',

    gradient:
      'linear-gradient(135deg,var(--ok-dim),var(--t-ok))',
  },

  {
    icon: '📅',
    title: 'همیشه در جریان',

    text:
      'برنامه هفته، امتحانهای پیش‌رو و نمره‌هات با یادآوری زنده؛\nو اگر جایی گیر کردی، پشتیبانی فقط یک تیکت فاصله‌ست.',

    tint:
      'var(--soft-warn)',

    gradient:
      'linear-gradient(135deg,var(--warn-dim),var(--t-warn))',
  },
];


export default function Onboarding() {
  const user = useAuthStore(
    (state) => state.user
  );

  const showOnboarding =
    useUIStore(
      (state) => state.showOnboarding
    );

  const onboardingDone =
    useUIStore(
      (state) => state.onboardingDone
    );

  const closeOnboarding =
    useUIStore(
      (state) =>
        state.closeOnboarding
    );


  /* ✅ سد سه‌لایه در برابر گیر کردن صفحه:
     ۱) dismissed — state محلی همین رندر
     ۲) onboardingDone — فلگ نشست در store
     ۳) hasSeenOnboarding — localStorage
     اگر هر کدام «تمام شده» باشد، اوورلی می‌رود. */
  const [dismissed, setDismissed] =
    useState(false);


  const shouldShow =
    Boolean(user) &&
    !dismissed &&
    !onboardingDone &&
    (showOnboarding ||
      !hasSeenOnboarding());


  const [index, setIndex] =
    useState(0);


  /* دکمه‌های نیتیو تلگرام روی اوورلی
     نباید دیده بشن */
  useEffect(() => {
    if (!shouldShow) return undefined;

    try {
      hideBackButton();
      tg?.MainButton?.hide?.();
    } catch (_) {
      /* نسخه قدیمی */
    }

    /* قفل اسکرول پس‌زمینه */
    const prev =
      document.body.style.overflow;

    document.body.style.overflow =
      'hidden';

    return () => {
      document.body.style.overflow =
        prev;
    };
  }, [shouldShow]);


  if (!shouldShow) return null;


  const isLast =
    index === SLIDES.length - 1;

  const slide = SLIDES[index];


  /* بستن قطعی: اول state محلی (فوری،
     حتی اگر store/storage خراب باشند)
     بعد store و در نهایت localStorage */
  const finish = () => {
    haptic('medium');
    setDismissed(true);
    markOnboardingSeen();
    closeOnboarding();
  };


  const next = () => {
    haptic('light');

    if (isLast) {
      finish();
      return;
    }

    setIndex((current) =>
      current + 1
    );
  };


  return (
    <div
      className="onb"
      role="dialog"
      aria-modal="true"
      aria-label="معرفی هامزیار"
    >
      {/* هاله رنگی سینک با اسلاید */}
      <div
        className="onb__glow"
        style={{
          background: slide.tint,
        }}
      />

      <div
        key={index}
        className="onb__body pop-in"
      >
        <div
          className="onb__icon"
          style={{
            background:
              slide.gradient,
          }}
        >
          {slide.icon}
        </div>

        <h2 className="onb__title">
          {slide.title}
        </h2>

        <p className="onb__text">
          {slide.text}
        </p>
      </div>


      {/* نقطه‌های پیشرفت */}
      <div className="onb__dots">
        {SLIDES.map((_, dotIndex) => (
          <button
            type="button"
            key={dotIndex}
            className={`step-dot ${
              dotIndex === index
                ? 'step-dot--now'
                : dotIndex < index
                  ? 'step-dot--done'
                  : ''
            }`}
            aria-label={`اسلاید ${dotIndex + 1}`}
            onClick={() => {
              haptic('light');
              setIndex(dotIndex);
            }}
          />
        ))}
      </div>


      {/* دکمه‌ها */}
      <div className="onb__actions">
        <button
          type="button"
          className="btn btn-p btn-full"
          onClick={next}
        >
          {isLast
            ? '🚀 بزن بریم!'
            : 'بعدی ←'}
        </button>

        {!isLast && (
          <button
            type="button"
            className="onb__skip"
            onClick={finish}
          >
            رد کردن
          </button>
        )}
      </div>
    </div>
  );
}
