import {
  useEffect,
} from 'react';

import {
  haptic,
} from '../../lib/telegram';


/* ─────────────────────────────────────────────
   اکشن‌شیت عملیات روی یک گفت‌وگو — هفت عمل
   یکدست در هر دو نقطه (صفحه‌ی تاریخچه و شیت
   سوییچ سریع داخل چت) استفاده می‌شود تا الگوی
   تعامل کاملاً یکسان بماند.
───────────────────────────────────────────── */


function buildActions(item) {
  const actions = [];

  if (!item.legacy) {
    if (!item.archived) {
      actions.push({
        id: 'pin',
        icon: '📌',
        label: item.pinned
          ? 'برداشتن پین'
          : 'پین‌کردن',
        desc: item.pinned
          ? 'بازگشت به ترتیب معمول'
          : 'ثابت‌ماندن بالای فهرست',
      });
    }

    actions.push({
      id: 'rename',
      icon: '✏️',
      label: 'تغییر نام',
      desc: 'عنوان نمایشی گفت‌وگو',
    });
  }

  actions.push({
    id: 'duplicate',
    icon: '⧉',
    label: 'ایجاد رونوشت',
    desc: item.legacy
      ? 'تبدیل حافظه‌ی مشترک به رشته‌ی مستقل'
      : 'کپی کامل در گفت‌وگوی جدید',
  });

  actions.push({
    id: 'export',
    icon: '⬇️',
    label: 'خروجی متنی',
    desc: 'فایل متنی کامل گفت‌وگو',
  });

  actions.push({
    id: 'share',
    icon: '↗️',
    label: 'اشتراک‌گذاری',
    desc: 'خلاصه‌ی مرتب برای ارسال',
  });

  if (!item.legacy) {
    actions.push({
      id: 'archive',
      icon: item.archived ? '📤' : '📥',
      label: item.archived
        ? 'خروج از بایگانی'
        : 'بایگانی',
      desc: item.archived
        ? 'بازگشت به فهرست اصلی'
        : 'پنهان از فهرست اصلی',
    });
  }

  actions.push({
    id: 'delete',
    icon: '🗑',
    label: item.legacy
      ? 'پاک‌کردن حافظه‌ی مشترک'
      : 'حذف گفت‌وگو',
    desc: 'برگشت‌ناپذیر',
    danger: true,
  });

  return actions;
}


export default function ConvActionSheet({
  conv,
  busy = false,
  onClose,
  onAction,
}) {

  useEffect(() => {
    const closeWithEscape = (event) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    window.addEventListener(
      'keydown',
      closeWithEscape,
    );

    return () =>
      window.removeEventListener(
        'keydown',
        closeWithEscape,
      );
  }, [onClose]);


  const actions = buildActions(conv);


  const run = (action) => {
    haptic('light');

    onClose();

    onAction(action.id);
  };


  return (
    // لایه‌ی بالاتر از شیت تاریخچه (۳۰۰) تا در
    // حالت سوییچ سریع داخل چت هم روشن بماند
    <div
      className="more-sheet"
      style={{ zIndex: 320 }}
      role="presentation"
      onClick={(event) => {
        // ⚠️ حیاتی وقتی روی شیتِ تاریخچه سوار
        // شده‌ایم: بدون stopPropagation کلیکِ
        // بک‌دراپ به شیتِ مادر حباب می‌کند و هر
        // دو را با هم می‌بندد
        event.stopPropagation();

        onClose();
      }}
    >
      <div
        className={
          'more-sheet__panel ' +
          'glass sheet-in'
        }
        role="dialog"
        aria-modal="true"
        aria-label="عملیات گفت‌وگو"
        onClick={(event) =>
          event.stopPropagation()
        }
      >
        <div className="more-sheet__handle" />

        <div
          className="more-sheet__title"
          style={{
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {conv.title}
        </div>

        {actions.map((action, index) => (
          <button
            type="button"
            key={action.id}
            className={
              'more-sheet__item pop-in' +
              (
                action.danger
                  ? ' more-sheet__item--danger'
                  : ''
              )
            }
            style={{
              animationDelay:
                `${index * 28}ms`,
            }}
            onClick={() => run(action)}
            disabled={busy}
          >
            <span className="more-sheet__item-icon">
              {action.icon}
            </span>

            <span className="more-sheet__item-text">
              <span className="more-sheet__item-title">
                {action.label}
              </span>

              <span className="more-sheet__item-desc">
                {action.desc}
              </span>
            </span>

            <span className="more-sheet__arrow">
              ←
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
