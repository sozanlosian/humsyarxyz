import {
  Component,
} from 'react';

import { APP_BASE } from '../../lib/base';


/* ─────────────────────────────────────────────
   دیوار آتش رندر (Error Boundary)

   قانون طلایی: هیچ exception تک‌نقطه‌ای نباید
   کل مینی‌اپ را به «صفحه‌ی تاریک» تبدیل کند.

   - هر خطای رندر در هر صفحه به‌جای unmountِ
     کامل React، به این صفحه‌ی بازیابی می‌رسد
   - متن خطا (به‌همراه مسیر) نمایش داده می‌شود
     تا اسکرین‌شاتِ گزارش کاربر = سرنخ واقعی
   - آخرین ۸ خطا در localStorage حلقه‌ای نگه
     داشته می‌شود (کاربر در Mini App به DevTools
     دسترسی ندارد — این تنها پنجره‌ی دیباگ ماست)
   - در App با key = pathname رزت می‌شود؛ یعنی
     تغییر مسیر = دیوارِ تازه (خودترمیمی)
───────────────────────────────────────────── */

const LOG_KEY =
  'humsyar_err_log_v1';


function pushErrorLog(entry) {
  try {
    const raw =
      localStorage.getItem(LOG_KEY);

    const list = raw
      ? JSON.parse(raw)
      : [];

    list.unshift(entry);

    localStorage.setItem(
      LOG_KEY,
      JSON.stringify(
        list.slice(0, 8)
      )
    );

  } catch (_) {
    /* WebViewهای سخت‌گیر — مهم نیست */
  }
}


export default class ErrorBoundary
  extends Component {

  state = {
    error: null,
  };


  static getDerivedStateFromError(error) {
    return { error };
  }


  componentDidCatch(error, info) {
    console.error(
      '[humsyar error boundary]',
      error,
      info,
    );

    pushErrorLog({
      at:
        new Date().toISOString(),

      path:
        window.location?.pathname || '?',

      message:
        String(
          error?.message || error
        ).slice(0, 220),

      stack:
        String(
          info?.componentStack || ''
        ).slice(0, 220),
    });

    /* 🌊 W5/REL-03 — گزارش best-effort به سرور تا خطای فرانت فقط در
       localStorage نماند؛ dynamic-import = صفر ریسک چرخه‌ی وارداتی،
       هیچ‌وقت رندر fallback را خراب نمی‌کند */
    try {
      import('../../lib/api').then(({ default: api }) => {
        api.post('/api/client-errors', {
          app: 'miniapp',
          path: window.location?.pathname || '?',
          message: String(error?.message || error).slice(0, 500),
          stack: String(info?.componentStack || '').slice(0, 2000),
        }).catch(() => {});
      }).catch(() => {});
    } catch (_) { /* سکوت — گزارش اختیاری است */ }
  }


  reset = () =>
    this.setState({ error: null });


  reload = () =>
    window.location.reload();


  goHome = () =>
    window.location.replace(APP_BASE);


  isChunkError(err) {
    const msg = String(err?.message || err || '').toLowerCase();
    return msg.includes('chunkloaderror') || msg.includes('failed to fetch dynamically imported module') || msg.includes('loading chunk') || msg.includes('cannot find module');
  }

  render() {
    const { error } = this.state;

    if (!error) {
      return this.props.children;
    }

    // 🌊 W4 — chunk load failed after deploy → suggest hard reload
    if (this.isChunkError(error)) {
      return (
        <main dir="rtl" style={{display:'flex',alignItems:'center',justifyContent:'center',width:'100%',minHeight:'100dvh',padding:'24px 16px',color:'var(--tx)',background:'transparent'}}>
          <section className={'card card-glow fade-up'} style={{width:'100%',maxWidth:390,padding:22,textAlign:'center'}}>
            <div style={{display:'grid',width:68,height:68,placeItems:'center',margin:'0 auto',background:'var(--soft-err)',border:'1px solid var(--bd-err)',borderRadius:'var(--r-xl)',fontSize:32}}>🔄</div>
            <h1 style={{marginTop:'var(--sp-4)',fontSize:'var(--fs-xl)',fontWeight:900}}>نسخه جدید در دسترس است</h1>
            <p style={{marginTop:'var(--sp-2)',color:'var(--tx2)',fontSize:'var(--fs-cap)',lineHeight:1.9}}>برنامه به‌روزرسانی شده است. برای ادامه، صفحه را بازگذاری کنید.</p>
            <div style={{display:'grid',gap:8,marginTop:16}}>
              <button type="button" className={'btn btn-p btn-full'} onClick={this.reload}>↻ بارگذاری مجدد</button>
              <button type="button" className={'btn btn-dark btn-full'} onClick={this.goHome}>بازگشت به داشبورد</button>
            </div>
          </section>
        </main>
      );
    }

    /* fallback سفارشی برای کرومِ اپ (مثل BottomNav):
       خطا در componentDidCatch داخل حلقه‌ی دیباگ ثبت
       شده، ولی به‌جای صفحه‌ی بازیابیِ تمام‌صفحه همین
       مقدار رندر می‌شود تا بقیه‌ی اپ زنده بماند —
       کرش نوار ناوبری = فقط نوار می‌رود، نه کل اپ */
    if (
      this.props.fallback !==
      undefined
    ) {
      return this.props.fallback;
    }

    return (
      <main
        dir="rtl"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: '100%',
          minHeight: '100dvh',
          padding: '24px 16px',
          color: 'var(--tx)',
          background: 'transparent',
        }}
      >
        <section
          className={
            'card card-glow fade-up'
          }
          style={{
            width: '100%',
            maxWidth: 390,
            padding: 22,
            textAlign: 'center',
          }}
        >
          <div
            style={{
              display: 'grid',
              width: 68,
              height: 68,
              placeItems: 'center',
              margin: '0 auto',

              background:
                'var(--soft-err)',

              border:
                '1px solid var(--bd-err)',

              borderRadius: 'var(--r-xl)',
              fontSize: 32,
            }}
          >
            🧯
          </div>

          <h1
            style={{
              marginTop: 'var(--sp-4)',
              fontSize: 'var(--fs-xl)',
              fontWeight: 900,
            }}
          >
            یک خطای غیرمنتظره رخ داد
          </h1>

          <p
            style={{
              marginTop: 'var(--sp-2)',
              color: 'var(--tx2)',
              fontSize: 'var(--fs-cap)',
              lineHeight: 1.9,
            }}
          >
            برنامه متوقف نشده و هیچ
            اطلاعاتی از دست نرفته است؛
            با یکی از دکمه‌های زیر ادامه
            دهید.
          </p>

          {/* متن دقیق خطا — برای اسکرین‌شات
              و ارسال به پشتیبانی */}
          <code
            dir="ltr"
            style={{
              display: 'block',
              maxHeight: 90,
              overflow: 'auto',
              marginTop: 'var(--sp-4)',
              padding: '9px 11px',

              color: 'var(--t-err)',

              background:
                'var(--scrim)',

              border:
                '1px solid var(--bd-err)',

              borderRadius: 'var(--r-md)',
              fontSize: 'var(--fs-cap)',
              lineHeight: 1.7,
              textAlign: 'left',
              wordBreak: 'break-word',
            }}
          >
            {String(
              error?.message || error
            )}
          </code>

          <div
            style={{
              display: 'grid',
              gap: 8,
              marginTop: 16,
            }}
          >
            <button
              type="button"
              className={
                'btn btn-p btn-full'
              }
              onClick={this.reset}
            >
              تلاش دوباره
            </button>

            <button
              type="button"
              className={
                'btn btn-dark btn-full'
              }
              onClick={this.goHome}
            >
              بازگشت به داشبورد
            </button>

            <button
              type="button"
              className={
                'btn btn-dark btn-full'
              }
              onClick={this.reload}
            >
              ↻ بارگذاری مجدد
            </button>
          </div>
        </section>
      </main>
    );
  }
}
