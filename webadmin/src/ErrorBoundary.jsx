import React from 'react';

// 🛡️ مرز خطا — تا این لحظه پنل هیچ ErrorBoundary نداشت.
//
// چرا مهم است: صفحات با React.lazy بارگذاری می‌شوند. هر throw در رندرِ
// یک صفحه (یا یک chunk قدیمی بعد از دیپلوی) کل درخت را unmount می‌کرد و
// کاربر یک صفحه‌ی کاملاً سفید می‌دید — بدون پیام، بدون راه بازگشت.
// حالا خطا در همان ناحیه‌ی محتوا مهار می‌شود و سایدبار/تاپ‌بار سالم
// می‌مانند تا کاربر بتواند به صفحه‌ی دیگری برود.

const isChunkError = error => /Loading chunk|dynamically imported module|Importing a module script failed/i.test(
  String(error?.message || ''),
);

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // بدون سرویس لاگ بیرونی؛ فقط کنسول تا در devtools قابل ردیابی باشد.
    console.error('[webadmin] render error:', error, info?.componentStack);
  }

  componentDidUpdate(prev) {
    // بدون این، خطا «چسبنده» می‌شود: کاربر به صفحه‌ی سالم می‌رود ولی
    // همچنان کارت خطا را می‌بیند، چون state خودبه‌خود پاک نمی‌شود.
    if (this.state.error && prev.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    // chunkِ قدیمی بعد از دیپلوی با reload حل می‌شود، نه با «تلاش مجدد».
    const stale = isChunkError(error);
    return (
      <div className="state-shell" role="alert">
        <div className="state-content">
          <div className="state-icon" aria-hidden="true">{stale ? '🔄' : '⚠️'}</div>
          <div className="state-title">
            {stale ? 'نسخه‌ی جدیدی از پنل منتشر شده است' : 'این بخش با خطای غیرمنتظره متوقف شد'}
          </div>
          <div className="state-description">
            {stale
              ? 'برای بارگذاری نسخه‌ی تازه، صفحه را دوباره بارگذاری کنید.'
              : 'بقیه‌ی بخش‌های پنل سالم‌اند و می‌توانید از منوی کناری به صفحه‌ی دیگری بروید.'}
          </div>
          <details className="error-details">
            <summary>جزئیات فنی</summary>
            <pre>{String(error?.stack || error?.message || error)}</pre>
          </details>
          <div className="state-actions">
            {stale
              ? <button className="btn primary" onClick={() => window.location.reload()}>↻ بارگذاری مجدد</button>
              : <button className="btn" onClick={() => this.setState({ error: null })}>↻ تلاش مجدد</button>}
            <button className="btn" onClick={() => { window.location.hash = '/dashboard'; }}>رفتن به داشبورد</button>
          </div>
        </div>
      </div>
    );
  }
}
