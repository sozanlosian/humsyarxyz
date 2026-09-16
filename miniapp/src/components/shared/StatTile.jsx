// ── StatTile — موج W2 Design Refactor
// تایل آمار مشترک کل پروژه — دو چیدمان:
//   variant="row"  → کارت افقی (آیکن‌باکس ۳۸ + متن)
//                    همان الگوی Stat قدیمی AdminHome
//   variant="grid" → تایل مرکزگرای muted (الگوی
//                    grid آمار پروفایل/داشبورد)
// رنگ‌ها فقط از مسیر توکن‌های tone می‌آیند.

export default function StatTile({
  icon,
  value,
  label,
  color = 'var(--t-acc)',
  soft = 'var(--soft-acc)',
  variant = 'row',
  onClick,
}) {
  /* تایل دکمه‌ای مرکزگرا — الگوی گرید آمار
     AdminPanel (قابل‌کلیک با card-tap) */
  if (variant === 'btn') {
    return (
      <button
        type="button"
        className="card card-tap"
        onClick={onClick || undefined}
        style={{
          textAlign: 'center',
          padding: '11px 7px',
          border: `1px solid ${color}28`,
          cursor: onClick
            ? 'pointer'
            : 'default',
          background: 'var(--surf)',
        }}
      >
        <div style={{ fontSize: 'var(--fs-xl)' }}>
          {icon}
        </div>

        <div
          style={{
            fontSize: 'var(--fs-xl)',
            fontWeight: 800,
            color,
            margin: '2px 0',
          }}
        >
          {value}
        </div>

        <div
          style={{
            fontSize: 'var(--fs-cap)',
            color: 'var(--txm)',
          }}
        >
          {label}
        </div>
      </button>
    );
  }

  if (variant === 'grid') {
    return (
      <div
        style={{
          padding: 'var(--sp-3)',
          textAlign: 'center',
          background: 'var(--soft-mut)',
          borderRadius: 'var(--r-md)',
        }}
      >
        <div>{icon}</div>

        <div
          style={{
            color,

            fontSize: 'var(--fs-xl)',

            fontWeight: 900,

            marginTop: 2,
          }}
        >
          {value}
        </div>

        <div
          style={{
            color: 'var(--txm)',

            fontSize:
              'var(--fs-cap)',
          }}
        >
          {label}
        </div>
      </div>
    );
  }

  return (
    <div
      className="card"
      style={{
        padding: 12,
        display: 'flex',
        alignItems: 'center',
        gap: 9,
      }}
    >
      <span
        style={{
          display: 'grid',
          width: 38,
          height: 38,
          placeItems: 'center',
          borderRadius: 'var(--r-md)',
          color,
          background: soft,
          fontSize: 'var(--fs-xl)',
        }}
      >
        {icon}
      </span>

      <div>
        <b
          style={{
            display: 'block',
            color,
            fontSize: 'var(--fs-xl)',
          }}
        >
          {value}
        </b>

        <span
          style={{
            color: 'var(--txm)',
            fontSize:
              'var(--fs-cap)',
          }}
        >
          {label}
        </span>
      </div>
    </div>
  );
}
