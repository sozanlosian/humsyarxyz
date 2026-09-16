import React, { useCallback, useEffect, useState } from 'react';
import { api, errText } from './api.js';
import { Loading, ErrorState, FaDateTime, B } from './ui.jsx';

// 🩺 مرکز سلامت سامانه
//
// مصرف‌کننده‌ی `/api/health/deep` — این endpoint از قبل در backend وجود
// داشت و هیچ‌جای پنل صدا زده نمی‌شد (endpoint یتیم).
//
// 🛡 بازنویسی UI: نسخه‌ی اول این فایل inline style با نام‌توکن‌های
// ساختگی (--bd, --card, --fg2, --fs1, --r2 …) داشت که هیچ‌کدام در
// styles.css وجود نداشتند؛ عملاً روی fallbackهای hardcoded رندر می‌شد
// و از تم پنل جدا بود. حالا فقط کلاس‌ها و توکن‌های واقعیِ پروژه.
//
// هیچ متریک تازه‌ای اختراع نمی‌شود؛ فقط آنچه سرور واقعاً می‌دهد. هر
// فیلدی که نیاید «—» می‌ماند، نه صفرِ گمراه‌کننده.

const fa = (n) => (n === null || n === undefined || n === '')
  ? '—'
  : Number(n).toLocaleString('fa-IR');

// وضعیت → کلاس تینتِ موجود در styles.css (.ic-ok / .ic-warn / .ic-bad)
const TONE = {
  ok:      { cls: 'ic-ok',   kind: 'ok',   icon: '🟢', label: 'سالم' },
  warn:    { cls: 'ic-warn', kind: 'warn', icon: '🟡', label: 'نیمه‌فعال' },
  bad:     { cls: 'ic-bad',  kind: 'bad',  icon: '🔴', label: 'خطا' },
  unknown: { cls: 'ic-acc',  kind: '',     icon: '⚪️', label: 'نامشخص' },
};

function toneOf(state) {
  if (state === true || state === 'ok' || state === 'ready') return TONE.ok;
  if (state === false || state === 'down') return TONE.bad;
  if (state === 'degraded' || state === 'not_ready') return TONE.warn;
  return TONE.unknown;
}

function uptimeText(seconds) {
  const s = Number(seconds);
  if (!Number.isFinite(s) || s < 0) return '—';
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d) return `${fa(d)} روز و ${fa(h)} ساعت`;
  if (h) return `${fa(h)} ساعت و ${fa(m)} دقیقه`;
  if (m) return `${fa(m)} دقیقه`;
  return `${fa(Math.floor(s))} ثانیه`;
}

function HealthCard({ icon, title, state, lines = [], error }) {
  const tone = toneOf(state);
  return (
    <section
      className={`panel panel-pad hc-card ${error ? 'panel--attention' : ''} ${tone.kind==='ok' ? '' : ''}`}
      aria-label={`${title} — ${tone.label}`}
      style={tone.kind==='ok' ? {borderColor:'rgba(58,210,155,.18)'} : undefined}
    >
      <div className="row">
        <span className={`ic ${tone.cls} hc-ic`} aria-hidden="true">{icon}</span>
        <b className="hc-title">{title}</b>
        <span className="spacer" />
        <B kind={tone.kind}>{tone.icon} {tone.label}</B>
      </div>

      {lines.filter(Boolean).length > 0 && (
        <dl className="kv hc-kv">
          {lines.filter(Boolean).map(([k, v]) => (
            <React.Fragment key={k}>
              <dt>{k}</dt>
              <dd className="num">{v}</dd>
            </React.Fragment>
          ))}
        </dl>
      )}

      {error ? <p className="hc-err" role="status">{error}</p> : null}
    </section>
  );
}

export default function HealthCenter() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [at, setAt] = useState(null);
  const [auto, setAuto] = useState(true);

  const load = useCallback(async (isAuto=false) => {
    if (!isAuto) setBusy(true);
    if (!isAuto) setErr('');
    try {
      const r = await api.healthDeep();
      setData(r);
      setAt(new Date().toISOString());
    } catch (e) {
      if (!isAuto) setErr(errText(e));
    } finally {
      if (!isAuto) setBusy(false);
    }
  }, []);

  useEffect(() => { load(false); }, [load]);
  useEffect(() => {
    if (!auto) return;
    const id = setInterval(()=> load(true), 30000);
    return () => clearInterval(id);
  }, [auto, load]);

  if (err && !data) return <ErrorState error={err} onRetry={load} />;
  if (!data) return <Loading rows={3} variant="cards" label="در حال سنجش سلامت" />;

  const bot = data.bot || {};
  const hb = bot.heartbeat || {};
  const mongo = data.mongo || {};
  const boot = data.bootstrap || {};
  const routes = data.routes || {};
  const miniapp = data.miniapp || {};
  const webadmin = data.webadmin || {};

  const flat = (obj, skip, max) => Object.entries(obj)
    .filter(([k, v]) => k !== skip && typeof v !== 'object')
    .slice(0, max)
    .map(([k, v]) => [k, typeof v === 'boolean' ? (v ? 'بله' : 'خیر') : String(v ?? '—')]);

  return (
    <div className="hc">
      <div className="section-header">
        <div>
          <div className="section-title">🩺 سلامت سامانه</div>
          <div className="section-description">
            دیاگنوستیک عمیق — هر بخش مستقل سنجیده می‌شود و خطای یکی بقیه را متوقف نمی‌کند.
          </div>
        </div>
        <span className="spacer" />
        <button type="button" className="btn" onClick={load} disabled={busy}>
          {busy ? 'در حال بررسی…' : '🔄 بررسی مجدد'}
        </button>
      </div>

      {(() => {
        const checks = [data.api?.ok, data.mongo?.ok, data.bot?.process_ok, data.bootstrap?.ready].filter(v=>v!==undefined);
        const okCount = checks.filter(v=>v===true || v==='ok' || v==='ready').length;
        const score = checks.length ? Math.round(okCount/checks.length*100) : 100;
        const scoreTone = score===100 ? '' : score>=70 ? 'warn' : 'bad';
        return (
        <div className="glass-panel live-pulse-bar" style={{marginBottom:12}}>
          <span className={`live-dot ${busy ? 'warn' : toneOf(data.status).kind==='bad' ? 'bad' : ''}`} />
          <B kind={toneOf(data.status).kind}>وضعیت کلی: {toneOf(data.status).label}</B>
          <span className="muted">نسخه {data.version || '—'} • آپ‌تایم {uptimeText(data.uptime_s)}</span>
          <span className="pulse-meta" style={{marginInlineStart:12}}>
            {at ? <>آخرین: <FaDateTime value={at} /></> : null}
          </span>
          <div className="pulse-actions" style={{marginInlineStart:'auto', gap:10}}>
            <div className={`health-score ${scoreTone}`} style={{"--score": score}}><span>{score}%</span></div>
            <label className="row" style={{gap:6, fontSize:'var(--fs-label)', cursor:'pointer'}}>
              <input type="checkbox" checked={auto} onChange={e=>setAuto(e.target.checked)} /> خودکار 30ثانیه
            </label>
            <button type="button" className="btn sm" onClick={()=>load(false)} disabled={busy}>{busy ? '…' : '🔄 اکنون'}</button>
          </div>
        </div>
        );
      })()}

      {err ? (
        <p className="hc-err" role="alert">
          بروزرسانی ناموفق بود ({err}) — داده‌های زیر مربوط به بررسی قبلی است.
        </p>
      ) : null}

      <div className="grid g2 hc-grid">
        <HealthCard
          icon="⚙️"
          title="API"
          state={data.api?.ok}
          lines={[['شناسه فرایند', fa(data.api?.pid)]]}
        />

        <HealthCard
          icon="🗄"
          title="MongoDB"
          state={mongo.ok}
          error={mongo.error}
          lines={[['تأخیر پینگ', mongo.ping_ms == null ? '—' : `${fa(mongo.ping_ms)} ms`]]}
        />

        <HealthCard
          icon="🤖"
          title="ربات تلگرام"
          state={bot.process_ok}
          error={bot.note}
          lines={[
            ['شناسه فرایند', fa(bot.process_pid)],
            ['ضربان دیده‌شده', hb.seen ? 'بله' : 'خیر'],
            hb.at ? ['آخرین ضربان', <FaDateTime key="hb" value={hb.at} />] : null,
          ]}
        />

        <HealthCard
          icon="🚀"
          title="راه‌اندازی"
          state={boot.ready}
          lines={flat(boot, 'ready', 4)}
        />

        <HealthCard
          icon="📱"
          title="Mini App"
          state={miniapp.built}
          lines={flat(miniapp, 'built', 3)}
        />

        <HealthCard
          icon="🖥"
          title="وب‌ادمین"
          state={webadmin.built}
          lines={flat(webadmin, 'built', 3)}
        />

        <HealthCard
          icon="🧭"
          title="فهرست مسیرها"
          state={routes.routes_match_baseline}
          lines={[
            ['عملیات OpenAPI', fa(routes.openapi_operations)],
            ['شیء مسیر زیر /api', fa(routes.api_route_objects)],
            ['خط‌مبنا', fa(routes.baseline_expected)],
          ]}
          error={
            routes.routes_match_baseline === false
              ? 'تعداد عملیات با خط‌مبنا نمی‌خواند — یا API عمداً تغییر کرده (خط‌مبنا را به‌روز کنید) یا مسیری ناخواسته اضافه/حذف شده است.'
              : ''
          }
        />
      </div>
    </div>
  );
}
