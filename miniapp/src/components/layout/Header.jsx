import {
  useCallback,
  useEffect,
} from 'react';

import {
  useLocation,
  useNavigate,
} from 'react-router-dom';

import {
  tg,
  haptic,
} from '../../lib/telegram';

import {
  navigateBack,
} from '../../lib/navBack';

import {
  useTelegramBack,
} from '../../lib/backButton';


/* ─────────────────────────────────────────────
   هدر استاندارد کل مینی‌اپ
   - دکمه‌ی برگشت همیشه سمت راست، موقعیت و سایز
     ثابت (توجه RTL: فلش → یعنی بازگشت)
   - حل‌مسیر یکپارچه از lib/navBack
   - BackButton نیتیو تلگرام هم سینک می‌شود تا
     دکمه‌ی فیزیکی Android کاربر را بیرون نیندازد
   - onRefresh: دکمه‌ی ↻ استاندارد Design System
     (موج ۳.۱۰) با چرخشِ زنده حین به‌روزرسانی —
     جایگزین استایل inline تکراریِ ۱۲ صفحه
───────────────────────────────────────────── */


export default function Header({
  title,
  subtitle,
  right,
  back = true,
  onBack,
  backTo,
  onRefresh,
  refreshing = false,
}) {
  const navigate =
    useNavigate();

  const location =
    useLocation();


  const handleBack =
    useCallback(() => {
      haptic('light');

      navigateBack({
        navigate,
        pathname: location.pathname,
        onBack,
        backTo,
      });

    }, [
      navigate,
      location.pathname,
      onBack,
      backTo,
    ]);


  const handleRefresh =
    useCallback(() => {
      haptic('light');
      onRefresh?.();

    }, [onRefresh]);


  /* 🧯 سینک متمرکز BackButton نیتیو — منطق
     show/hide/onClick به lib/backButton سپرده
     شده؛ هندلرِ تازه (با هر رندرِ تایمر آزمون)
     فقط به‌صورت ref جایگزین می‌شود و دیگر هیچ
     چرخه‌ی offClick/hide→onClick/show رخ نمی‌دهد
     — پایان چشمک Back⇄Close */
  useTelegramBack(
    back,
    handleBack,
  );


  return (
    <header className="app-header glass">
      <div className="app-header__main">
        {back && (
          <button
            type="button"
            className="app-header__back"
            onClick={
              handleBack
            }
            aria-label="بازگشت به صفحه‌ی قبل"
          >
            →
          </button>
        )}

        <div className="app-header__text">
          <div className="app-header__title">
            {title}
          </div>

          {subtitle && (
            <div className="app-header__subtitle">
              {subtitle}
            </div>
          )}
        </div>
      </div>

      {(right || onRefresh) && (
        <div className="app-header__right">
          {right}

          {onRefresh && (
            <button
              type="button"
              className="icon-btn"
              onClick={
                handleRefresh
              }
              disabled={refreshing}
              aria-label="به‌روزرسانی"
            >
              <span
                className={
                  refreshing
                    ? 'icon-btn__spin'
                    : undefined
                }
              >
                ↻
              </span>
            </button>
          )}
        </div>
      )}
    </header>
  );
}
