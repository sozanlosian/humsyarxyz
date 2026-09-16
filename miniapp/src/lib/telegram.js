export const tg =
  typeof window !== 'undefined'
    ? window.Telegram?.WebApp
    : undefined;

function safeCall(fn) {
  try {
    fn();
  } catch (error) {
    console.warn('[telegram webapp]', error);
  }
}

export function initTelegram() {
  if (!tg) return;

  safeCall(() => tg.ready());
  safeCall(() => tg.expand());

  /* هم‌ترازی دقیق کروم تلگرام با گرادیان ثابت صفحه —
     هدر با بالای گرادیان، ناحیه overscroll با پایین آن
     تا هیچ ناپیوستگی نوری لمس نشود */
  safeCall(() => tg.setHeaderColor('#0A1020'));
  safeCall(() => tg.setBackgroundColor('#070B14'));

  safeCall(() => tg.enableClosingConfirmation());

  /* جلوگیری از بسته‌شدن تصادفی اپ با سوایپ عمودی به
     پایین (Bot API 7.7+ — در کلاینت‌های قدیمی presence
     چک می‌شود و بی‌خطر رد می‌شود) */
  safeCall(() => {
    if (typeof tg.disableVerticalSwipes === 'function') {
      tg.disableVerticalSwipes();
    }
  });
}

export const getInitData = () => tg?.initData || '';

export const getTgUser = () =>
  tg?.initDataUnsafe?.user || null;

/* پارامتر startapp دیپ‌لینک (Bot API 6.x+)
   — مثل rank_<uid> در لینک اشتراک Prestige؛
   اگر کلاینت قدیمی باشد رشته‌ی خالی می‌دهد */
export const getStartParam = () =>
  tg?.initDataUnsafe?.start_param || '';

export const haptic = (type = 'light') => {
  safeCall(() => tg?.HapticFeedback?.impactOccurred(type));
};

export const hapticNotif = (type = 'success') => {
  safeCall(() =>
    tg?.HapticFeedback?.notificationOccurred(type)
  );
};

export const isTelegram = Boolean(tg);

/* 🌊 W2 — بازکردن لینک خارجی (درگاه پرداخت) در مرورگر بیرون تلگرام؛
   در کلاینت قدیمی یا وب، fallback به window.open */
export const openExternalLink = (url) => {
  if (!url) return false;
  if (typeof tg?.openLink === 'function') {
    try {
      tg.openLink(url);
      return true;
    } catch {
      /* fallback پایین */
    }
  }
  try {
    window.open(url, '_blank', 'noopener');
    return true;
  } catch {
    return false;
  }
};
