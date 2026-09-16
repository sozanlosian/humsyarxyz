// ── PageError — موج W2 Design Refactor
// حالت خطای تمام‌صفحه مشترک: آیکن شبکه + متن
// فارسی + دکمه‌ی «تلاش دوباره» (با حالت pending).
// تا امروز این الگو در ~۲۰ فایل کپی بود.

import { Spinner } from './Loading';


export default function PageError({
  text = 'دریافت اطلاعات انجام نشد.',
  detail,
  onRetry,
  pending = false,
  retryLabel = 'تلاش دوباره',
}) {
  return (
    <div className="empty card">
      <div className="empty__ic">🌐</div>

      <div>{text}</div>

      {detail ? (
        <div
          style={{
            color: 'var(--txm)',
            fontSize: 'var(--fs-cap)',
          }}
        >
          {detail}
        </div>
      ) : null}

      {onRetry ? (
        <button
          type="button"
          className="btn btn-p"
          style={{ marginTop: 12 }}
          onClick={onRetry}
          disabled={pending}
        >
          {pending ? (
            <Spinner size={15} />
          ) : (
            retryLabel
          )}
        </button>
      ) : null}
    </div>
  );
}
