// ── MenuRow — موج W2/W3 Design Refactor
// ردیف منوی مشترک کل پروژه (استخراج از Me/index).
// ساختار: آیکن‌باکس ۴۰ با tone + عنوان + توضیح +
// بج اختیاری + فلش. همه‌ی منوها بعداً همین الگو
// را دارند؛ نسخه‌های دستی (آیکن/متن inline) حذف
// می‌شوند. رفتار: همان onClick + haptic قبلی.

import { haptic } from '../../lib/telegram';


const TONES = {
  blue: [
    'var(--soft-acc)',
    'var(--t-acc)',
  ],

  green: [
    'var(--soft-ok)',
    'var(--t-ok)',
  ],

  yellow: [
    'var(--soft-warn)',
    'var(--t-warn)',
  ],

  red: [
    'var(--soft-err)',
    'var(--t-err)',
  ],

  purple: [
    'var(--soft-pur)',
    'var(--t-pur)',
  ],

  cyan: [
    'var(--soft-info)',
    'var(--t-info)',
  ],
};


export default function MenuRow({
  icon,
  title,
  description,
  badge,
  tone = 'blue',
  onClick,
  last = false,
  disabled = false,
}) {
  const [soft, color] =
    TONES[tone] || TONES.blue;

  return (
    <button
      type="button"
      className="menu-row"
      disabled={disabled}
      onClick={() => {
        haptic();
        onClick();
      }}
      style={{
        borderBottom:
          last
            ? 0
            : undefined,
      }}
    >
      <span
        style={{
          display: 'grid',
          flex: '0 0 40px',
          height: 40,
          placeItems: 'center',
          borderRadius: 'var(--r-md)',
          background: soft,
          color,
          fontSize: 'var(--fs-xl)',
        }}
      >
        {icon}
      </span>

      <span
        style={{
          flex: 1,
          minWidth: 0,
          textAlign: 'right',
        }}
      >
        <b
          style={{
            display: 'block',
            fontSize: 'var(--fs-sm)',
          }}
        >
          {title}
        </b>

        {description && (
          <span
            style={{
              display: 'block',
              color: 'var(--txm)',
              fontSize: 'var(--fs-cap)',
              marginTop: 2,
            }}
          >
            {description}
          </span>
        )}
      </span>

      {badge ? (
        typeof badge === 'string' ? (
          <span className="badge b-yel">
            {badge}
          </span>
        ) : (
          badge
        )
      ) : null}

      <span
        style={{
          color: 'var(--txm)',
        }}
      >
        ←
      </span>
    </button>
  );
}
