import {
  tg,
} from './telegram';


/**
 * تأییدیه Promise-based برای عملیات حساس.
 *
 * ⚠️ چرا window.confirm کافی نیست؟
 * در WebView تلگرام (به‌خصوص iOS) متدهای native
 * مرورگر مثل confirm/alert/prompt یا کلاً کار
 * نمی‌کنند یا no-op هستند — یعنی تأیید حذف هرگز
 * به کاربر نشان داده نمی‌شد. تلگرام برای همین
 * API رسمی showConfirm ارائه داده است.
 *
 * رفتار:
 *  - داخل تلگرام → پنجره native تلگرام (RTL-friendly)
 *  - خارج از تلگرام (مرورگر توسعه) → window.confirm
 *  - هر خطایی → false (امن؛ عملیات انجام نمی‌شود)
 */
export function confirmAction(
  message,
) {
  return new Promise((resolve) => {
    if (
      typeof tg?.showConfirm ===
      'function'
    ) {
      try {
        tg.showConfirm(
          message,
          (confirmed) =>
            resolve(
              Boolean(confirmed)
            ),
        );

        return;

      } catch (_) {
        // نسخه قدیمی کلاینت → fallback
      }
    }

    try {
      resolve(
        Boolean(
          window.confirm(message)
        )
      );

    } catch (_) {
      resolve(false);
    }
  });
}
