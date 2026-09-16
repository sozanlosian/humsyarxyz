// ── EmptyState — موج W2 Design Refactor
// حالت خالی مشترک کل پروژه. تا امروز ۶ پیاده‌ی
// محلی Empty(...) با تفاوت‌های جزئی (آیکن 40/42px،
// مارجین دستی) وجود داشت؛ حالا یک کامپوننت:
// <EmptyState icon="📭">…</EmptyState>
// کاملاً بر پایه‌ی کلاس‌های DS (.empty/.empty__ic).

export default function EmptyState({
  icon,
  children,
  card = true,
  style,
}) {
  return (
    <div
      className={card ? 'empty card' : 'empty'}
      style={style}
    >
      {icon ? (
        <div className="empty__ic">
          {icon}
        </div>
      ) : null}

      <div>{children}</div>
    </div>
  );
}
