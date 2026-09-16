import {
  useRef,
} from 'react';

import {
  useLocation,
  useNavigate,
} from 'react-router-dom';

import {
  haptic,
} from '../../lib/telegram';

import {
  hasBackTarget,
  navigateBack,
} from '../../lib/navBack';

import {
  useUIStore,
} from '../../stores/uiStore';


/* ─────────────────────────────────────────────
   ژست بازگشت از لبه‌ی راست (Swipe Back — RTL)

   - شروع ژست فقط از نوار ۱۳px لبه‌ی راست؛
     تشخیص جهت: افقی‌غالب + حرکت به چپ
   - نشان شیشه‌ای به‌تبعِ انگشت از لبه بیرون
     می‌آید (فقط transform/opacity)
   - رها بالای آستانه → همان navigateBackِ
     سیستم یکپارچه (history یا مسیر والد)
   - غیرفعال در: صفحات ریشه، ادمین، شیت‌ها و
     آنبوردینگ (هدفِ ژست از target خوانده می‌شود)
───────────────────────────────────────────── */

const START_BAND_PX = 10;
const TRIGGER_PX = 64;
const FULL_TRAVEL_PX = 96;


export default function SwipeBack() {
  const location = useLocation();
  const navigate = useNavigate();

  const showOnboarding = useUIStore(
    (state) => state.showOnboarding,
  );

  const edgeRef = useRef(null);
  const indRef = useRef(null);

  /* وضعیت ژست — فقط ref؛ بدون هیچ setState
     حین حرکت تا ۶۰fps واقعی بماند */
  const gestureRef = useRef({
    pointerId: null,
    startX: 0,
    startY: 0,
    started: false,
    aborted: false,
  });


  const resetIndicator = () => {
    const indicator = indRef.current;

    if (!indicator) {
      return;
    }

    // برگشت فنریِ نشان به داخل لبه
    indicator.classList.remove(
      'swipe-ind--out',
    );

    indicator.style.opacity = '0';

    indicator.style.transform =
      'translateY(-50%) translateX(46px)';

    indicator.classList.remove(
      'swipe-ind--ready',
    );
  };


  const gestureBlocked = (event) => {
    // جلوگیری از تداخل با شیت‌ها/دیالوگ‌ها و
    // آنبوردینگ — خودشان مدیریت بستن دارند
    if (showOnboarding) {
      return true;
    }

    if (
      document.querySelector(
        '.more-sheet, .onb',
      )
    ) {
      return true;
    }

    return Boolean(
      event.target?.closest?.(
        '.more-sheet, .onb, dialog',
      ),
    );
  };


  const onPointerDown = (event) => {
    if (
      event.pointerType === 'mouse' &&
      event.button !== 0
    ) {
      return;
    }

    if (
      !hasBackTarget(location.pathname)
    ) {
      return;
    }

    if (gestureBlocked(event)) {
      return;
    }

    gestureRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      started: false,
      aborted: false,
    };
  };


  const onPointerMove = (event) => {
    const gesture = gestureRef.current;

    if (
      gesture.pointerId === null ||
      event.pointerId !== gesture.pointerId
    ) {
      return;
    }

    // حرکت به چپ = رفتن به صفحه‌ی قبل (RTL)
    const leftward =
      gesture.startX - event.clientX;

    const absY = Math.abs(
      event.clientY - gesture.startY,
    );

    if (!gesture.started) {
      if (gesture.aborted) {
        return;
      }

      // ژست عمودی → تحویل به اسکرول صفحه
      if (
        absY > START_BAND_PX &&
        absY > Math.abs(leftward)
      ) {
        gesture.aborted = true;
        return;
      }

      if (leftward <= START_BAND_PX) {
        return;
      }

      gesture.started = true;

      try {
        edgeRef.current
          ?.setPointerCapture(
            event.pointerId,
          );

      } catch (_) {
        // کلاینت‌های قدیمی
      }

      indRef.current?.classList.add(
        'swipe-ind--out',
      );

      haptic('light');
    }

    if (gesture.aborted) {
      return;
    }

    const progress = Math.min(
      1,
      Math.max(
        0,
        leftward / FULL_TRAVEL_PX,
      ),
    );

    const indicator = indRef.current;

    if (indicator) {
      // از داخل لبه (۴۶px) تا بیرون‌آمدگی کامل
      const offset =
        46 - progress * 52;

      indicator.style.opacity =
        String(
          0.25 + progress * 0.75,
        );

      indicator.style.transform =
        'translateY(-50%) ' +
        `translateX(${offset}px) ` +
        `scale(${
          0.86 + progress * 0.14
        })`;

      indicator.classList.toggle(
        'swipe-ind--ready',
        leftward >= TRIGGER_PX,
      );
    }
  };


  const endGesture = (event) => {
    const gesture = gestureRef.current;

    if (
      gesture.pointerId === null ||
      (
        event.pointerId !==
          undefined &&
        event.pointerId !==
          gesture.pointerId
      )
    ) {
      return;
    }

    const leftward =
      gesture.startX - event.clientX;

    const wasStarted = gesture.started;

    gestureRef.current = {
      pointerId: null,
      startX: 0,
      startY: 0,
      started: false,
      aborted: false,
    };

    if (!wasStarted) {
      return;
    }

    if (leftward >= TRIGGER_PX) {
      haptic('medium');

      resetIndicator();

      navigateBack({
        navigate,
        pathname: location.pathname,
      });

      return;
    }

    resetIndicator();
  };


  if (!hasBackTarget(location.pathname)) {
    return null;
  }

  return (
    <>
      <div
        ref={edgeRef}
        className="swipe-edge"
        aria-hidden="true"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endGesture}
        onPointerCancel={endGesture}
        onLostPointerCapture={endGesture}
      />

      <div
        ref={indRef}
        className="swipe-ind"
        aria-hidden="true"
      >
        →
      </div>
    </>
  );
}
