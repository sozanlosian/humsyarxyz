/* 👑 NameChip — موج P0 Prestige (v3 LOCKED)
   چیپ کوچک «آیکون رنک + نام» برای جاهایی که
   هویت رقابتی باید کنار نام دیده شود.
   رنگ از پیلود Prestige (--prc) می‌آید؛ منبع
   یکتای رنگ‌ها بک‌اند است، اینجا فقط مصرف. */
export default function NameChip({
  icon = '🌱',
  name,
  color,
  div,
  roman,
}) {
  return (
    <span
      className="name-chip"
      style={
        color
          ? { '--prc': color }
          : undefined
      }
    >
      <span
        className="name-chip__icon"
        aria-hidden="true"
      >
        {icon}
      </span>

      <span>
        {name || 'کاربر هامزیار'}
      </span>

      {roman && (
        <span
          style={{
            color: 'var(--txm)',
            fontSize: 'var(--fs-cap)',
          }}
        >
          {roman}
        </span>
      )}
    </span>
  );
}
