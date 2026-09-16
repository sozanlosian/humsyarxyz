import React, { useEffect, useRef, useState } from 'react';
import { api, errText } from '../api.js';
import { DataTable, Loading, ErrorState, Stat, B, DiffViewer, FaDateTime, PageHeader, StatusBadge, toast, Confirm, Switch } from '../ui.jsx';
import HealthCenter from '../HealthCenter.jsx';
import DlqCenter from '../DlqCenter.jsx';

const fa = (n) => Number(n ?? 0).toLocaleString('fa-IR');
const DETAIL_LABELS = {
  checked_at: 'زمان بررسی', bot_pid: 'شناسه فرایند ربات', bot_error: 'خطای ربات',
  db_ping_ms: 'تأخیر MongoDB (ms)', db_error: 'خطای پایگاه‌داده',
};

// 🖥 سلامت سامانه + 💾 مدیریت پشتیبان‌گیری (🌊 موج Backup-Mgmt)
// همان بخش‌های منوی «پشتیبان‌گیری» ربات + وضعیت/کنترل بکاپ خودکار —
// همه از endpointهای موجود؛ هیچ متریک ساختگی نمایش داده نمی‌شود.
const SECTIONS = [
  ['all',          '💾', 'کامل — همه بخش‌ها', 'کل دیتابیس (توصیه می‌شود)'],
  ['users',        '👥', 'کاربران',           'اطلاعات ثبت‌نام‌شدگان'],
  ['content',      '📚', 'علوم پایه',         'درس‌ها، جلسات و محتوا'],
  ['refs',         '📖', 'رفرنس‌ها',          'کتاب‌ها و فایل‌های درسی'],
  ['qbank',        '🧪', 'بانک سؤال',         'سؤال‌ها و فایل‌ها'],
  ['subscription', '💳', 'اشتراک و پرداخت',   'پلن‌ها، رسیدها، کدهای تخفیف'],
  ['grades',       '📊', 'نمرات',             'نمرات ثبت‌شده'],
  ['access',       '🔐', 'دسترسی‌ها و تنظیمات', 'نقش‌ها، بلک‌لیست، ورودی‌ها'],
];

export default function System({ me, route = '' }) {
  const [bs, setBs] = useState(null);
  const [st, setSt] = useState(null);          // تنظیمات ربات (وضعیت بکاپ خودکار)
  const [jobs, setJobs] = useState([]);
  const [observability, setObservability] = useState(null);
  const [clientErrs, setClientErrs] = useState(null); // 🌊 W5/REL-03
  const [timeStandard, setTimeStandard] = useState(null);
  const [sessions, setSessions] = useState(null);
  const [err, setErr] = useState('');
  const [confirm, setConfirm] = useState(null); // section در انتظار تأیید
  const [busySec, setBusySec] = useState('');
  const [autoBusy, setAutoBusy] = useState(false);
  const [excelBusy, setExcelBusy] = useState(false);
  const [restoreFile, setRestoreFile] = useState(null);
  const [restorePreview, setRestorePreview] = useState(null);
  // 🌊 WA21 — مقصد deep-link مرکز اقدام (`/system?focus=dlq` / `?focus=outbox`).
  // بدون این، کارت‌های DLQ و صف خروجی کاربر را به صفحه می‌آوردند ولی نه به
  // همان بخش؛ یعنی عملاً deep-link بی‌اثر بود.
  const dlqRef = useRef(null);
  const outboxRef = useRef(null);
  const focusKey = new URLSearchParams(route.split('?')[1] || '').get('focus');
  const [restorePhrase, setRestorePhrase] = useState('');
  const [restoreBusy, setRestoreBusy] = useState(false);

  const has = (p) => !!me?.is_owner || (me?.perms || []).includes(p);
  const canBackup = has('backup.manage');
  const canPrestige = has('prestige.manage');
  const canForce = has('notifications.manage');
  const canLogTest = has('settings.manage') || has('system.manage');
  const canObserve = has('system.manage');

  const load = async () => {
    setErr('');
    try {
      const [b, s, j, o, ts, sec, ce] = await Promise.all([
        api.botStatus(), canBackup ? api.settings() : Promise.resolve(null),
        api.systemJobs().catch(() => ({ jobs: [] })),
        canObserve ? api.systemObservability().catch(() => null) : Promise.resolve(null),
        canObserve ? api.systemTimeStandard().catch(() => null) : Promise.resolve(null),
        canObserve ? api.securitySessions().catch(() => null) : Promise.resolve(null),
        canObserve ? api.systemClientErrors(24, 20).catch(() => null) : Promise.resolve(null),
      ]);
      setBs(b); setSt(s); setJobs(j.jobs || []); setObservability(o); setTimeStandard(ts); setSessions(sec); setClientErrs(ce);
    } catch (e) { setErr(errText(e)); }
  };
  useEffect(() => { load(); }, []);

  // 🌊 WA21 — اسکرول به بخش مقصد + highlight کوتاه. data هنوز نرسیده باشد
  // هم ref وجود دارد (DlqCenter همیشه رندر می‌شود)، پس ریسک race ندارد.
  useEffect(() => {
    if (!focusKey) return;
    const el = focusKey === 'dlq' ? dlqRef.current : focusKey === 'outbox' ? outboxRef.current : null;
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    el.classList.add('panel--attention');
    const t = setTimeout(() => el.classList.remove('panel--attention'), 2600);
    return () => clearTimeout(t);
  }, [focusKey]);

  const doBackup = async (section) => {
    setBusySec(section);
    try {
      const r = await api.backup(section === 'all' ? undefined : section);
      toast(r.message || '💾 درخواست پشتیبان ثبت شد — فایل در گفت‌وگوی ربات می‌آید');
    } catch (e) { toast(errText(e), 'err'); }
    setBusySec('');
  };
  const doExcel = async () => {
    setExcelBusy(true);
    try {
      await api.exportExcel();
      toast('درخواست ثبت شد 📑 ربات فایل اکسل را در گفت‌وگوی شما می‌فرستد');
    } catch (e) { toast(errText(e), 'err'); }
    setExcelBusy(false);
  };
  const validateRestore = async (file) => {
    setRestoreFile(file || null); setRestorePreview(null); setRestorePhrase('');
    if (!file) return;
    setRestoreBusy(true);
    try { setRestorePreview(await api.restoreValidate(file)); }
    catch (e) { toast(errText(e), 'err'); setRestoreFile(null); }
    setRestoreBusy(false);
  };
  const confirmRestore = async () => {
    if (!restoreFile || !restorePreview) return;
    setRestoreBusy(true);
    try {
      const r = await api.restoreConfirm(restoreFile, restorePreview.digest, restorePhrase);
      toast(`${fa(r.total)} رکورد بازیابی شد`); setRestoreFile(null); setRestorePreview(null); setRestorePhrase(''); load();
    } catch (e) { toast(errText(e), 'err'); }
    setRestoreBusy(false);
  };
  // ⏰ کنترل بکاپ خودکار — همان کلیدهای backup:auto_settings ربات (PATCH دارای audit)
  const setAuto = async (patch) => {
    setAutoBusy(true);
    try {
      await api.patchSettings(patch);
      setSt(s => ({ ...s, ...patch }));
      toast('تنظیمات بکاپ خودکار ذخیره شد ✅');
    } catch (e) { toast(errText(e), 'err'); }
    setAutoBusy(false);
  };

  if (err) return <ErrorState error={err} onRetry={load} />;
  if (!bs) return <Loading rows={4} />;

  const health = v => v === true ? ['🟢', 'ok', 'سالم'] : ['🔴', 'bad', 'مشکل'];
  const botOk = bs.bot_ok === true;
  const dbOk = bs.db_ok === true;
  const apiOk = bs.api_ok === true;
  const auto = st || {};
  const lastRun = auto.auto_backup_last_run || '';

  return (
    <>
      <PageHeader title="سلامت سامانه" description="وضعیت زنده Bot، API، MongoDB، صف اعلان و پشتیبان‌گیری؛ بدون متریک ساختگی"
        actions={<StatusBadge status={botOk && dbOk && apiOk ? 'healthy' : 'critical'} label={botOk && dbOk && apiOk ? 'سامانه سالم' : 'نیازمند بررسی'} />} />
      <div className="grid g4">
        <div className="panel stat">
          <div className="ic ic-ok">{health(botOk)[0]}</div>
          <div><div className="v"><B kind={health(botOk)[1]}>{health(botOk)[2]}</B></div>
            <div className="l">process ربات تلگرام{bs.bot_pid ? ` · PID ${bs.bot_pid}` : ''}</div></div>
        </div>
        <div className="panel stat">
          <div className="ic ic-acc">{health(dbOk)[0]}</div>
          <div><div className="v"><B kind={health(dbOk)[1]}>{health(dbOk)[2]}</B></div>
            <div className="l">پایگاه‌داده{bs.db_ping_ms != null ? ` · ${fa(bs.db_ping_ms)}ms` : ''}</div></div>
        </div>
        <div className="panel stat">
          <div className="ic ic-purple">{health(apiOk)[0]}</div>
          <div><div className="v"><B kind={health(apiOk)[1]}>{health(apiOk)[2]}</B></div>
            <div className="l">API{bs.sys?.uptime ? ` · ${bs.sys.uptime}` : ''}</div></div>
        </div>
        {bs.notifications && <Stat icon="🔔" label="پیام در صف ارسال" value={fa(bs.notifications.pending_queue)}
          hint={`${fa(bs.notifications.recent_failed_runs)} اجرای اخیر دارای خطا`} tint={bs.notifications.recent_failed_runs ? 'var(--warn)' : 'var(--ok)'} />}
        {bs.backup && <Stat icon="💾" label="پشتیبان‌گیری خودکار" value={bs.backup.enabled ? 'فعال' : 'غیرفعال'}
          hint={bs.backup.last_run ? <>آخرین: <FaDateTime value={bs.backup.last_run} /></> : 'هنوز اجرا نشده'} tint={bs.backup.enabled ? 'var(--ok)' : 'var(--warn)'} />}
      </div>

      <div className="panel panel-pad" style={{ marginTop: 14 }}>
        <b>جزئیات فنی سلامت</b>
        <dl className="kv" style={{ marginTop: 8 }}>
          {Object.entries(bs).filter(([k, v]) => typeof v !== 'object' && DETAIL_LABELS[k] && v !== '' && v != null).map(([k, v]) => (
            <React.Fragment key={k}><dt>{DETAIL_LABELS[k]}</dt><dd className={k.includes('pid') ? 'code' : ''}>{k === 'checked_at' ? <FaDateTime value={v} /> : String(v)}</dd></React.Fragment>
          ))}
        </dl>
      </div>

      {/* 🩺 دیاگنوستیک عمیق — مصرف‌کننده‌ی /api/health/deep.
          مکمل کارت‌های بالا (که از system/status می‌آیند) است، نه جایگزین:
          اینجا ضربان ربات، وضعیت بیلدها و فهرست مسیرها هم دیده می‌شود. */}
      {canObserve && (
        <div className="panel panel-pad" style={{ marginTop: 14 }}>
          <HealthCenter />
        </div>
      )}

      {timeStandard && <section className="panel panel-pad" style={{ marginTop: 14 }} aria-labelledby="time-standard-title">
        <div className="row"><div><b id="time-standard-title">🕰 زمان و تاریخ سیستم</b><div className="muted">یک instant، نمایش تهران و تقویم رسمی شمسی</div></div><span className="spacer" /><B kind="acc">{timeStandard.timezone}</B><B>{timeStandard.calendar} · {timeStandard.locale}</B></div>
        <div className="grid g4" style={{ marginTop: 10 }}>
          <div className="panel panel-pad"><span className="muted">زمان UTC ماشین</span><div className="code ltr">{timeStandard.server_utc}</div></div>
          <div className="panel panel-pad"><span className="muted">زمان فعلی تهران</span><div><FaDateTime value={timeStandard.server_utc} long /></div></div>
          <div className="panel panel-pad"><span className="muted">امروز</span><div>{timeStandard.today_jalali}</div></div>
          <div className="panel panel-pad"><span className="muted">Offset / Unix</span><div className="code ltr">{timeStandard.utc_offset} · {timeStandard.unix_timestamp}</div></div>
        </div>
        <div className="callout" style={{ marginTop: 10 }}>Storage: <span className="code ltr">{timeStandard.storage_contract}</span> · Display: {timeStandard.display_contract} · شروع هفته: {timeStandard.week_start}</div>
      </section>}

      {!!jobs.length && <div ref={outboxRef} className="panel panel-pad" style={{ marginTop: 14 }}>
        <div className="row"><div><b>⚙️ Job Center</b><div className="muted">آخرین اجرای جاب‌های اعلان، صف خروجی و بکاپ واقعی</div></div>
          <span className="spacer" /><button className="btn sm" onClick={load}>↻ تازه‌سازی</button></div>
        <div className="grid g3" style={{ marginTop: 10 }}>
          {jobs.map(job => <div key={job.key} className="panel panel-pad" style={{ background: 'var(--bg)' }}>
            <div className="row"><b>{job.label}</b><span className="spacer" />
              <StatusBadge status={job.failed ? 'failed' : ['done', 'finished', 'enabled', 'idle'].includes(job.status) ? 'healthy' : 'pending'} label={job.status} /></div>
            <div className="row" style={{ marginTop: 7 }}>
              {job.pending != null && <B kind={job.pending ? 'warn' : 'ok'}>در صف: {fa(job.pending)}</B>}
              {job.sent != null && <B kind="ok">ارسال: {fa(job.sent)}</B>}
              {job.failed != null && <B kind={job.failed ? 'bad' : ''}>خطا: {fa(job.failed)}</B>}
              {job.scheduled != null && <B>زمان‌دار: {fa(job.scheduled)}</B>}
            </div>
            {job.last_run && <div className="muted" style={{ marginTop: 7 }}>آخرین اجرا: <FaDateTime value={job.last_run} /></div>}
          </div>)}
        </div>
      </div>}

      {observability && <div className="panel panel-pad" style={{ marginTop: 14 }}>
        <div className="row"><div><b>📡 Observability پنل وب</b><div className="muted">متریک persisted و TTLدار از درخواست‌های واقعی ۲۴ ساعت اخیر</div></div><span className="spacer" /><B>{fa(observability.total)} درخواست</B><B kind={observability.errors ? 'bad' : 'ok'}>{fa(observability.errors)} خطا</B><B kind="acc">نرخ خطا: {observability.error_rate == null ? 'داده موجود نیست' : `${fa(observability.error_rate)}٪`}</B></div>
        <div style={{ marginTop: 10 }}><DataTable columns={[
          { k: 'route', label: 'Route', render: r => <span className="code">{r.route}</span> },
          { k: 'requests', label: 'درخواست', render: r => fa(r.requests) },
          { k: 'errors', label: 'خطا', render: r => <B kind={r.errors ? 'bad' : 'ok'}>{fa(r.errors)}</B> },
          { k: 'avg_ms', label: 'میانگین ms', render: r => fa(r.avg_ms) },
          { k: 'max_ms', label: 'بیشینه ms', render: r => fa(r.max_ms) },
        ]} rows={observability.routes || []} rowKey="route" colToggle /></div>
        {!!observability.recent_errors?.length && <details style={{ marginTop: 10 }}><summary>خطاهای اخیر و Request ID</summary><div className="grid">{observability.recent_errors.map((e, i) => <div className="row" key={`${e.request_id}-${i}`}><B kind="bad">{e.status}</B><span className="code">{e.route}</span><span className="spacer" /><span className="code">{e.request_id}</span></div>)}</div></details>}
        {/* 🌊 W5/REL-03 — شمارنده‌ی موقت همه‌ی /api (با ری‌استارت صفر می‌شود) */}
        {!!observability.api && <div style={{ marginTop: 10 }} className="row"><B kind="acc">{fa(observability.api.total)} درخواست /api</B><B kind={observability.api.recent_5xx?.length ? 'bad' : 'ok'}>{fa(observability.api.recent_5xx?.length || 0)} خطای 5xx</B><span className="muted">موقت (ری‌استارت: صفر)</span></div>}
        {!!observability.api?.routes?.length && <details style={{ marginTop: 10 }}><summary>پرترافیک‌ترین روت‌های /api</summary><div className="grid">{observability.api.routes.slice(0, 12).map((r) => <div className="row" key={r.route}><span className="code">{r.route}</span><span className="spacer" /><B kind="acc">{fa(r.requests)}</B></div>)}</div></details>}
        {!!observability.api?.recent_5xx?.length && <details style={{ marginTop: 10 }}><summary>خطاهای 5xx اخیر همه‌ی API</summary><div className="grid">{observability.api.recent_5xx.map((e, i) => <div className="row" key={`${e.request_id}-${i}`}><B kind="bad">{e.status}</B><span className="code">{e.method} {e.route}</span><span className="spacer" /><span className="code">{e.request_id}</span></div>)}</div></details>}
        {/* 🌊 W5/REL-03 — خطاهای گزارش‌شده‌ی فرانت */}
        {!!clientErrs?.items?.length && <details style={{ marginTop: 10 }} open><summary>خطاهای کلاینت ۲۴ساعت اخیر ({fa(clientErrs.items.length)})</summary><div className="grid">{clientErrs.items.map((e, i) => <div className="row" key={i}><B kind={e.app === 'webadmin' ? 'acc' : 'bad'}>{e.app}</B><span className="code">{e.message}</span><span className="spacer" /><span className="muted">{e.path}</span></div>)}</div></details>}
      </div>}

      {/* 💀 DLQ — پیام‌های مرده‌ی صف. خواندن با notifications.manage هم مجاز است
          (همان قرارداد بک‌اند)، ولی اکشن بازپخش/کنارگذاشتن فقط system.manage. */}
      {(canObserve || has('notifications.manage')) && (
        <div ref={dlqRef} className="panel" style={{ borderRadius: 'var(--r-lg)' }}>
          <DlqCenter canManage={canObserve} />
        </div>
      )}

      {canObserve && <WalletAlertPanel />}
      {canObserve && <SecuritySessionsPanel data={sessions} onReload={load} />}

      {/* ── ⏰ بکاپ خودکار روزانه (داده واقعی settings؛ PATCH دارای audit) ── */}
      {st && (
        <div className="panel panel-pad" style={{ marginTop: 14 }}>
          <div className="row" style={{ flexWrap: 'wrap', gap: 10 }}>
            <div>
              <b>⏰ بکاپ خودکار روزانه</b>
              <div className="muted" style={{ marginTop: 4 }}>
                {auto.auto_backup_enabled
                  ? `فعال — هر روز ساعت ${fa(auto.auto_backup_hour)}:۰۰ به‌وقت تهران؛ فایل مستقیماً در گفت‌وگوی مالک ارسال می‌شود.`
                  : 'غیرفعال — بکاپ کامل روزانه‌ی خودکار ساخته نمی‌شود.'}
              </div>
              <div className="muted" style={{ marginTop: 3 }}>
                🕐 آخرین اجرا: {lastRun ? <FaDateTime value={lastRun} /> : 'هنوز اجرا نشده'}
              </div>
            </div>
            <span className="spacer" />
            <label className="row" style={{ gap: 6 }}>
              <Switch on={!!auto.auto_backup_enabled} disabled={autoBusy}
                      onChange={v => setAuto({ auto_backup_enabled: v })} />
              <span className="muted">فعال</span>
            </label>
            <select className="inp" style={{ maxWidth: 110 }} disabled={autoBusy}
                    value={auto.auto_backup_hour ?? 3}
                    onChange={e => setAuto({ auto_backup_hour: Number(e.target.value) })}>
              {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{fa(h)}:۰۰</option>)}
            </select>
          </div>
        </div>
      )}

      {/* ── 💾 پشتیبان دستی بخش‌بندی‌شده — دقیقاً همان بخش‌های منوی ربات ── */}
      {canBackup && <div className="panel panel-pad" style={{ marginTop: 14 }}>
        <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
          <div><b>💾 پشتیبان‌گیری دستی</b>
            <div className="muted" style={{ marginTop: 4 }}>بخش موردنظر را انتخاب کنید — فایل JSON از طریق ربات در گفت‌وگوی شما می‌آید (در audit ثبت می‌شود).</div>
          </div>
          <span className="spacer" />
          <button className="btn" disabled={excelBusy} onClick={doExcel}>
            {excelBusy ? '⏳ …' : '📑 خروجی اکسل کامل'}
          </button>
        </div>
        <div className="grid g4" style={{ marginTop: 12 }}>
          {SECTIONS.map(([key, icon, label, hint]) => (
            <div key={key} className="panel panel-pad bk-sec" style={{ background: 'var(--bg)' }}>
              <div className="row">
                <span style={{ fontSize: 'var(--fs-icon)' }}>{icon}</span>
                <b style={{ fontSize: 'var(--fs-card)' }}>{label}</b>
              </div>
              <div className="muted" style={{ marginTop: 4, minHeight: 30 }}>{hint}</div>
              <button className={`btn sm ${key === 'all' ? 'primary' : ''}`} style={{ marginTop: 8, width: '100%' }}
                      disabled={!!busySec}
                      onClick={() => setConfirm(key)}>
                {busySec === key ? '⏳ در حال ثبت…' : key === 'all' ? 'ساخت پشتیبان کامل' : 'پشتیبان این بخش'}
              </button>
            </div>
          ))}
        </div>
        {!!me?.is_owner && <div className="panel panel-pad" style={{ marginTop: 14, borderColor: 'color-mix(in srgb, var(--c-bad) 42%, var(--c-line))' }}>
          <b>📥 بازیابی پشتیبان — فقط مالک</b>
          <p className="muted" style={{ marginTop: 5 }}>فایل ابتدا بدون mutation اعتبارسنجی و fingerprint می‌شود؛ اجرای مرحله دوم فقط با همان فایل و عبارت تأیید ممکن است. بازیابی از نوع merge/upsert است، رکوردهای غایب از فایل حذف نمی‌شوند و عملیات در audit با CRITICAL ثبت می‌شود.</p>
          <input type="file" className="inp" accept=".json,application/json" disabled={restoreBusy} onChange={e => validateRestore(e.target.files?.[0])} />
          {restoreBusy && !restorePreview && <Loading rows={2} />}
          {restorePreview && <div style={{ marginTop: 10 }}>
            <div className="row"><B kind="ok">فایل معتبر</B><B>نسخه {restorePreview.backup_version}</B><B>{(restorePreview.size / 1024 / 1024).toFixed(2)} MB</B>
              <span className="code">{restorePreview.digest.slice(0, 16)}…</span></div>
            {!!restorePreview.integrity?.complete && <div className="callout ok" style={{ marginTop: 8 }}>✅ manifest یکپارچگی فایل کامل است؛ نشست، OTP، کلید API هوشیار و outbox اجرایی عمداً داخل پشتیبان نیستند.</div>}
            {!!restorePreview.warnings?.length && <div className="callout warn" style={{ marginTop: 8 }}>{restorePreview.warnings.map(w => <div key={w}>⚠️ {w}</div>)}</div>}
            <div className="grid g4" style={{ marginTop: 8 }}>{restorePreview.sections.map(s => <div className="panel panel-pad" style={{ background: 'var(--bg)' }} key={s.key}><b>{s.key}</b><div className="muted">{fa(s.records)} رکورد</div></div>)}</div>
            <label className="fld" style={{ marginTop: 10 }}><span>برای تأیید دقیقاً بنویسید: <span className="code">RESTORE HUMSYAR</span></span>
              <input className="inp code" value={restorePhrase} onChange={e => setRestorePhrase(e.target.value)} /></label>
            <button className="btn danger" disabled={restoreBusy || restorePhrase !== 'RESTORE HUMSYAR'} onClick={confirmRestore}>
              {restoreBusy ? '⏳ در حال بازیابی…' : 'بازیابی قطعی داده‌های فایل'}
            </button>
          </div>}
        </div>}
      </div>}

      {canPrestige && <PrestigeConfigPanel />}

      {/* 🛠 عملیات حساس با نمایش مبتنی بر permission */}
      <OwnerOpsPanel canPrestige={canPrestige} canForce={canForce} canLogTest={canLogTest} />

      {confirm && (
        <Confirm text={`ساخت پشتیبان «${SECTIONS.find(s => s[0] === confirm)?.[2]}»؟ (عملیات حساس — فایل در گفت‌وگوی ربات می‌آید و در audit ثبت می‌شود)`}
                 onYes={async () => { const s = confirm; setConfirm(null); await doBackup(s); }}
                 onNo={() => setConfirm(null)} />
      )}
    </>
  );
}

function SecuritySessionsPanel({ data, onReload }) {
  const [target, setTarget] = useState(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const revoke = async () => {
    if (reason.trim().length < 3) return toast('دلیل لغو نشست را وارد کنید', 'err');
    setBusy(true);
    try {
      await api.revokeSecuritySession(target.id, reason.trim());
      toast('نشست با ثبت حسابرسی لغو شد');
      setTarget(null); setReason(''); await onReload();
    } catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  return <section className="panel panel-pad" style={{ marginTop: 14 }}>
    <div className="row"><div><b>🔐 نشست‌های فعال پنل وب</b>
      <div className="muted">نشست‌های واقعی HttpOnly؛ انقضا با TTL و لغو از سمت سرور اعمال می‌شود.</div></div>
      <span className="spacer" />{data && <B kind="acc">{fa(data.total)} نشست فعال</B>}
      <button className="btn sm" onClick={onReload}>↻ تازه‌سازی</button></div>
    {!data ? <ErrorState title="فهرست نشست‌ها در دسترس نیست" error="داده امنیتی بارگذاری نشد" onRetry={onReload} /> :
      <div style={{ marginTop: 10 }}><DataTable columns={[
        { k: 'admin', label: 'مدیر', render: r => <div><b>{r.name}</b><div className="muted ltr">{r.username ? `@${r.username} · ` : ''}{r.uid}</div></div> },
        { k: 'created_at', label: 'شروع', render: r => <FaDateTime value={r.created_at} /> },
        { k: 'expires_at', label: 'انقضا', render: r => <FaDateTime value={r.expires_at} /> },
        { k: 'peer_ip', label: 'IP مستقیم', render: r => <span className="code">{r.peer_ip || 'ثبت‌نشده'}</span> },
        { k: 'device', label: 'عامل کاربر', render: r => <span className="muted ltr" title={r.user_agent}>{r.user_agent ? r.user_agent.slice(0, 46) : 'legacy / ثبت‌نشده'}</span> },
        { k: 'status', label: 'وضعیت', render: r => r.current ? <B kind="ok">نشست جاری</B> : <B>فعال</B> },
        { k: 'action', label: '', render: r => r.current ? null : <button className="btn sm danger" onClick={() => { setTarget(r); setReason(''); }}>لغو نشست</button> },
      ]} rows={data.sessions || []} rowKey="id" colToggle empty="نشست فعال دیگری وجود ندارد" /></div>}
    {target && <Confirm onNo={() => { if (!busy) { setTarget(null); setReason(''); } }} onYes={revoke} danger>
      <p className="state-description">نشست «{target.name}» بلافاصله بی‌اعتبار می‌شود. نشست مالک فقط توسط مالک قابل لغو است.</p>
      <label className="fld" style={{ marginTop: 10 }}><span>دلیل لغو</span>
        <input className="inp" maxLength={300} value={reason} onChange={e => setReason(e.target.value)} placeholder="مثلاً دستگاه ناشناس یا پایان همکاری" disabled={busy} /></label>
    </Confirm>}
  </section>;
}

function WalletAlertPanel() {
  const [cfg,setCfg]=React.useState(null);
  const [err,setErr]=React.useState('');
  const [busy,setBusy]=React.useState(false);
  const load=async()=>{ setErr(''); try{ const r=await api.walletAlerts(); setCfg(r); }catch(e){ setErr(errText(e)); } };
  React.useEffect(()=>{ load(); },[]);
  const toggleEnabled=async(v)=>{ setBusy(true); try{ await api.walletAlertsPatch({enabled:v}); await load(); toast(v?'هشدار کیف پول فعال شد':'هشدار کیف پول غیرفعال شد'); }catch(e){ toast(errText(e),'err'); } setBusy(false); };
  const setCooldown=async(h)=>{ setBusy(true); try{ await api.walletAlertsPatch({cooldown_hours:Number(h)}); await load(); toast('بازه ضداسپم ذخیره شد ✅'); }catch(e){ toast(errText(e),'err'); } setBusy(false); };
  const mute24=async()=>{ const until=new Date(Date.now()+24*3600*1000).toISOString(); setBusy(true); try{ await api.walletAlertsPatch({muted_until:until}); await load(); toast('تا ۲۴ ساعت بی‌صدا شد 🔕'); }catch(e){ toast(errText(e),'err'); } setBusy(false); };
  const unmute=async()=>{ setBusy(true); try{ await api.walletAlertsPatch({muted_until:''}); await load(); toast('بی‌صدا لغو شد'); }catch(e){ toast(errText(e),'err'); } setBusy(false); };
  const dismissWallet=async()=>{ const reason=prompt('دلیل بستن هشدار کیف پول؟ (حداقل ۳ حرف)'); if(!reason||reason.trim().length<3) return; const h=prompt('بازه بستن به ساعت (24/72/168 یا 0 برای دائم)','24'); const hours=Number(h||24); try{ await api.attentionDismiss('wallet_issues', reason.trim(), hours); toast('هشدار کیف پول در «نیازمند اقدام» بسته شد ✅'); await load(); }catch(e){ toast(errText(e),'err'); } };
  const restoreWallet=async()=>{ try{ await api.attentionRestore('wallet_issues'); toast('بازگردانی شد ✅'); await load(); }catch(e){ toast(errText(e),'err'); } };
  if(err) return <div className="panel panel-pad" style={{marginTop:14}}><ErrorState error={err} onRetry={load} /></div>;
  if(!cfg) return <div className="panel panel-pad" style={{marginTop:14}}><Loading rows={2} /></div>;
  const isMuted = cfg.muted_until && new Date(cfg.muted_until) > new Date();
  const isDismissed = cfg.dismiss?.active;
  return <section className="panel panel-pad" style={{marginTop:14}}>
    <div className="row"><div><b>👛 هشدار مغایرت کیف پول — ضداسپم</b><div className="muted">هشدار تکراری «1 مورد بحرانی» حالا با جزئیات، cooldown و قابلیت بستن. بستن در داشبورد = بی‌صداشدن ربات.</div></div><span className="spacer"/><B kind={cfg.enabled?'ok':'bad'}>{cfg.enabled?'فعال':'غیرفعال'}</B>{isMuted && <B kind="warn">بی‌صدا تا <FaDateTime value={cfg.muted_until}/></B>}{isDismissed && <B kind="acc">بسته‌شده {cfg.dismiss.until ? <>تا <FaDateTime value={cfg.dismiss.until}/></> : 'دائم'}</B>}</div>
    <div className="row" style={{marginTop:10,flexWrap:'wrap',gap:8}}>
      <label className="row" style={{gap:6}}><Switch on={!!cfg.enabled} disabled={busy} onChange={toggleEnabled}/> هشدار فعال</label>
      <span className="muted">بازه ضداسپم (تکرار یکسان):</span>
      <select className="inp" style={{maxWidth:110}} disabled={busy} value={cfg.cooldown_hours} onChange={e=>setCooldown(e.target.value)}>{[1,2,3,6,12,24].map(h=><option key={h} value={h}>{h} ساعت</option>)}</select>
      {!isMuted ? <button className="btn sm" disabled={busy} onClick={mute24}>🔕 ۲۴ساعت بی‌صدا</button> : <button className="btn sm" disabled={busy} onClick={unmute}>🔔 لغو بی‌صدا</button>}
      {!isDismissed ? <button className="btn sm" disabled={busy} onClick={dismissWallet}>🔕 بستن هشدار «نیازمند اقدام»</button> : <button className="btn sm" disabled={busy} onClick={restoreWallet}>↩️ بازکردن</button>}
    </div>
    <div className="muted" style={{marginTop:8}}>متن جدید ربات شامل جزئیات (نام کاربر، نوع مغایرت، مبلغ) + لینک /subscriptions?tab=reconcile است و فقط وقتی هشدار جدید/متفاوت باشد و cooldown گذشته باشد ارسال می‌شود. بستن از داشبورد (🔕 بستن) همان dismissal را می‌بندد و ربات تا پایان بازه دیگر پیام نمی‌دهد.</div>
  </section>;
}

function PrestigeConfigPanel() {
  const [data, setData] = useState(null);
  const [values, setValues] = useState({});
  const [err, setErr] = useState('');
  const [confirmSave, setConfirmSave] = useState(false);
  const load = async () => {
    setErr('');
    try { const r = await api.prestigeConfig(); setData(r); setValues(r.effective || {}); }
    catch (e) { setErr(errText(e)); }
  };
  useEffect(() => { load(); }, []);
  if (err) return <div className="panel panel-pad" style={{ marginTop: 14 }}><ErrorState title="تنظیمات Prestige بارگذاری نشد" error={err} onRetry={load} /></div>;
  if (!data) return <div className="panel panel-pad" style={{ marginTop: 14 }}><Loading rows={4} /></div>;
  const changed = Object.keys(values).filter(k => Number(values[k]) !== Number(data.effective?.[k]));
  const save = async () => {
    setConfirmSave(false);
    const overrides = Object.fromEntries(Object.entries(values).filter(([k, v]) => Number(v) !== Number(data.defaults?.[k])));
    try { await api.prestigeConfigUpdate(overrides); toast('تنظیمات Prestige ذخیره شد ✅'); load(); }
    catch (e) { toast(errText(e), 'err'); }
  };
  const cs = data.challenge_stats || {};
  return <section className="panel panel-pad" style={{ marginTop: 14 }}>
    <div className="row"><div><b>🏅 تعادل زنده Prestige</b><div className="muted">اوررایدهای معتبر بدون redeploy؛ آستانه‌های Design Lock تغییر نمی‌کنند</div></div>
      <span className="spacer" />{data.updated_at && <B>آخرین تغییر: <FaDateTime value={data.updated_at} /></B>}
      <button className="btn primary sm" disabled={!changed.length} onClick={() => setConfirmSave(true)}>بازبینی {fa(changed.length)} تغییر</button></div>
    {Object.keys(cs).length > 0 && <div className="row" style={{ marginTop: 10 }}>
      {cs.active != null && <B kind="acc">چالش فعال: {fa(cs.active)}</B>}
      {cs.completed != null && <B kind="ok">تکمیل‌شده: {fa(cs.completed)}</B>}
      {cs.failed != null && <B kind={cs.failed ? 'warn' : 'ok'}>ناموفق: {fa(cs.failed)}</B>}
    </div>}
    <div className="form-grid" style={{ marginTop: 12 }}>
      {Object.entries(data.meta || {}).map(([key, meta]) => <label className="fld" key={key}>
        <span>{meta.label}</span><input className="inp" type="number" min={meta.min} max={meta.max}
          value={values[key] ?? ''} onChange={e => setValues(v => ({ ...v, [key]: Number(e.target.value) }))} />
        <small className="field-help">بازه {fa(meta.min)} تا {fa(meta.max)} · پیش‌فرض {fa(data.defaults?.[key])}</small>
      </label>)}
    </div>
    {confirmSave && <Confirm onNo={() => setConfirmSave(false)} onYes={save}>
      <p className="muted" style={{ marginBottom: 10 }}>فقط اختلاف‌های زیر به‌عنوان override ذخیره می‌شوند.</p>
      <DiffViewer before={Object.fromEntries(changed.map(k => [data.meta[k]?.label || k, data.effective[k]]))}
        after={Object.fromEntries(changed.map(k => [data.meta[k]?.label || k, values[k]]))} />
    </Confirm>}
  </section>;
}

/* ── 🛠 عملیات مالک — همان دکمه‌های پراکنده‌ی پنل ربات (admin:prestige_backfill / notif_force_send / test_log_groups) ── */
function OwnerOpsPanel({ canPrestige, canForce, canLogTest }) {
  const [confirm, setConfirm] = useState(null);   // 'prestige' | 'force'
  const [busy, setBusy] = useState('');
  const [prestigeRep, setPrestigeRep] = useState(null);
  const [logRes, setLogRes] = useState(null);

  const runPrestige = async () => {
    setBusy('prestige');
    try {
      const r = await api.prestigeBackfill();
      setPrestigeRep(r.report);
      toast('Backfill Prestige کامل شد 🏅');
    } catch (e) {
      const t = errText(e);
      if (e.status === 403) return;               // غیرمالک: پنل بی‌فایده — پنهانش کن
      toast(t, 'err');
    } finally { setBusy(''); }
  };
  const runForce = async () => {
    setBusy('force');
    try {
      const r = await api.forceResNotif();
      toast(r.message || '📨 درخواست ثبت شد');
    } catch (e) { toast(errText(e), 'err'); }
    finally { setBusy(''); }
  };
  const runLogTest = async () => {
    setBusy('logtest'); setLogRes(null);
    try { setLogRes((await api.logGroupsTest()).results || []); }
    catch (e) { toast(errText(e), 'err'); }
    finally { setBusy(''); }
  };
  const LOG_ST = { sent: ['ok', '✅ ارسال شد'], unset: ['', '⬜ تنظیم نشده'], error: ['bad', '❌ خطا'] };

  if (!canPrestige && !canForce && !canLogTest) return null;
  return (
    <div className="panel panel-pad" style={{ marginTop: 14 }}>
      <b>🛠 عملیات مالک</b>
      <div className="muted" style={{ marginTop: 4 }}>همان اکشن‌های پراکنده‌ی پنل ربات — idempotent یا دارای Confirm؛ همه در audit ثبت می‌شوند.</div>
      <div className="row" style={{ marginTop: 10, flexWrap: 'wrap', gap: 8 }}>
        {canPrestige && <button className="btn" disabled={!!busy} onClick={() => setConfirm('prestige')}>
          {busy === 'prestige' ? '⏳ در حال محاسبه…' : '🏅 محاسبه‌ی Prestige (Backfill)'}
        </button>}
        {canForce && <button className="btn" disabled={!!busy} onClick={() => setConfirm('force')}>
          {busy === 'force' ? '⏳ …' : '📨 ارسال فوری اعلان منابع'}
        </button>}
        {canLogTest && <button className="btn" disabled={!!busy} onClick={runLogTest}>
          {busy === 'logtest' ? '⏳ …' : '🧪 تست اتصال گروه‌های لاگ'}
        </button>}
      </div>
      {prestigeRep && (
        <div className="row" style={{ marginTop: 10, flexWrap: 'wrap', gap: 6 }}>
          <B kind="acc">👥 پیمایش: {fa(prestigeRep.scanned)}</B>
          <B kind="ok">✅ مهاجرت: {fa(prestigeRep.migrated)}</B>
          <B kind="acc">🏛 بنیان‌گذار: {fa(prestigeRep.founders)}</B>
          <B kind="acc">🏆 نشان: {fa(prestigeRep.firsts)}</B>
          <B kind={prestigeRep.errors ? 'bad' : 'ok'}>⚠️ خطا: {fa(prestigeRep.errors)}</B>
        </div>
      )}
      {logRes && (
        <div className="grid" style={{ gap: 6, marginTop: 10 }}>
          {logRes.map(r => (
            <div key={r.key} className="row" style={{ gap: 6 }}>
              <B kind={LOG_ST[r.status]?.[0] || ''}>{LOG_ST[r.status]?.[1] || r.status}</B>
              <span style={{ fontSize: 'var(--fs-body)' }}>{r.label}</span>
              {r.ms != null && <span className="muted">({fa(r.ms)}ms)</span>}
              {r.error && <span className="muted code" title={r.error}>{r.error.slice(0, 60)}</span>}
            </div>
          ))}
        </div>
      )}
      {confirm === 'prestige' && (
        <Confirm text="اجرای Backfill Prestige روی همه‌ی کاربران؟ (idempotent — چندبار اجرا اشکال ندارد؛ در audit با HIGH ثبت می‌شود)"
                 onYes={async () => { setConfirm(null); await runPrestige(); }}
                 onNo={() => setConfirm(null)} />
      )}
      {confirm === 'force' && (
        <Confirm text="ارسال فوری اعلان منابع جدید به همه‌ی کاربران دارای این اعلان؟ (خارج از نوبتِ بازه‌ی ۲۴/۴۸/۷۲ ساعته)"
                 onYes={async () => { setConfirm(null); await runForce(); }}
                 onNo={() => setConfirm(null)} />
      )}
    </div>
  );
}
