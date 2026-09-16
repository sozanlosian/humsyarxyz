import React, { useEffect, useMemo, useState } from 'react';
import { api, errText } from '../api.js';
import { B, Confirm, Drawer, Empty, ErrorState, FaDateTime, Loading, PageHeader, Tabs, toast } from '../ui.jsx';
import { writeHashQuery } from '../urlState.js';

const fa = n => Number(n ?? 0).toLocaleString('fa-IR');
const TABS = [['work', '📌 کارهای من'], ['alerts', '🔔 هشدارها'], ['quality', '🧬 کیفیت داده']];
const sevKind = value => value === 'critical' ? 'bad' : value === 'warning' ? 'warn' : value === 'high' ? 'bad' : 'acc';
const CONTENT_TYPES = ['video', 'ppt', 'pdf', 'note', 'test', 'voice'];
const FIELD_FA = { name: 'نام', type: 'نوع', description: 'توضیح' };

export default function Operations({ route = '', me, go }) {
  const requested = new URLSearchParams(route.split('?')[1] || '').get('tab');
  const allowedTabs = useMemo(() => TABS.filter(([key]) => key !== 'quality' || me?.is_owner || (me?.perms || []).includes('system.manage')), [me]);
  const [tab, setTab] = useState(allowedTabs.some(([key]) => key === requested) ? requested : 'work');
  const changeTab = value => { setTab(value); writeHashQuery('/operations', { tab: value !== 'work' ? value : '' }); };
  useEffect(() => { if (allowedTabs.some(([key]) => key === requested)) setTab(requested); }, [requested, allowedTabs]);
  return <>
    <PageHeader title="مرکز عملیات" description="کارهای تخصیص‌یافته، هشدارهای واقعی و کیفیت داده — هر مورد قابل‌فهم و قابل‌اصلاح، نه فقط گزارش" />
    <Tabs items={allowedTabs} value={tab} onChange={changeTab} label="بخش‌های مرکز عملیات" />
    {tab === 'work' && <MyWork go={go} />}
    {tab === 'alerts' && <Alerts go={go} />}
    {tab === 'quality' && <DataQuality />}
  </>;
}

function MyWork({ go }) {
  const [data, setData] = useState(null); const [err, setErr] = useState('');
  const load = () => { setErr(''); setData(null); api.myWork().then(setData).catch(e => setErr(errText(e))); };
  useEffect(load, []);
  if (err) return <ErrorState error={err} onRetry={load} />;
  if (!data) return <Loading rows={5} />;
  const tasks = data.tasks || [];
  if (!tasks.length) return <Empty icon="📌" text="برای مجوزهای فعلی صف کاری تعریف‌شده‌ای وجود ندارد" />;
  return <div className="grid g2 operations-grid">
    {tasks.map(item => <button key={item.key} className="panel panel-pad operation-card" onClick={() => go?.(item.go)}>
      <span className="operation-icon">{item.icon}</span>
      <span className="operation-body"><b>{item.label}</b><span className="muted">{item.oldest_at ? <>قدیمی‌ترین: <FaDateTime value={item.oldest_at} /></> : item.empty ? 'صف خالی است' : 'زمان ثبت موجود نیست'}</span></span>
      <B kind={item.count ? sevKind(item.urgency) : 'ok'}>{fa(item.count)}</B><span aria-hidden="true">‹</span>
    </button>)}
  </div>;
}

function Alerts({ go }) {
  const [data, setData] = useState(null); const [err, setErr] = useState('');
  const load = () => { setErr(''); setData(null); api.operationAlerts().then(setData).catch(e => setErr(errText(e))); };
  useEffect(load, []);
  if (err) return <ErrorState error={err} onRetry={load} />;
  if (!data) return <Loading rows={4} />;
  const alerts = data.alerts || [];
  if (!alerts.length) return <Empty icon="✅" text="هشدار عملیاتی فعالی وجود ندارد" />;
  return <div className="grid">
    {alerts.map(item => <button key={item.key} className={`panel panel-pad operation-card attention-${item.severity || 'warning'}`} onClick={() => go?.(item.go)}>
      <span className="operation-icon">{item.icon}</span><span className="operation-body"><b>{item.label}</b>
        <span className="muted">{item.timestamp ? <FaDateTime value={item.timestamp} /> : 'زمان رویداد در منبع ثبت نشده'}</span></span>
      <B kind={sevKind(item.severity)}>{fa(item.count)}</B><span>‹</span>
    </button>)}
  </div>;
}

// 🌊 W5 — کارت‌های کیفیت داده + اصلاح مستقیم همان‌جا (SEE→UNDERSTAND→ACT→VERIFY).
function DataQuality() {
  const [data, setData] = useState(null); const [err, setErr] = useState(''); const [selected, setSelected] = useState(null);
  const load = () => { setErr(''); setData(null); api.dataQuality().then(setData).catch(e => setErr(errText(e))); };
  useEffect(load, []);
  if (err) return <ErrorState title="بررسی کیفیت داده اجرا نشد" error={err} onRetry={load} />;
  if (!data) return <Loading rows={6} />;
  const fixable = new Set(data.fixable || []);
  const totalIssues = (data.items || []).reduce((s, i) => s + (i.count || 0), 0);
  return <>
    {totalIssues === 0 && <div className="panel panel-pad q-zero">✅ کیفیت داده خوب است — هیچ مورد بازِ قابل‌اثباتی پیدا نشد.</div>}
    <div className="panel panel-pad data-quality-note"><B kind="warn">تشخیص + اصلاح</B><span>هر مورد با عنوان انسانی و context واقعی نمایش داده می‌شود و همان‌جا قابل اصلاح است؛ پس از اصلاح، rule دوباره اجرا می‌شود و شمارش‌ها از بک‌اند تازه می‌شوند. گونه‌های هویتی/مالی عمداً دستی می‌مانند.</span></div>
    <div className="grid g2 operations-grid">
      {(data.items || []).map(item => <button key={item.kind} className="panel panel-pad operation-card" disabled={!item.available} onClick={() => setSelected(item)}>
        <span className="operation-icon">{item.severity === 'critical' ? '⛔' : item.severity === 'warning' ? '⚠️' : 'ℹ️'}</span>
        <span className="operation-body"><b>{item.label}</b><span className="muted">{item.suggestion}</span></span>
        <B kind={item.available ? (item.count ? sevKind(item.severity) : 'ok') : ''}>{item.available ? fa(item.count) : 'ناموجود'}</B><span>‹</span>
      </button>)}
    </div>
    {selected && <QualityDrawer item={selected} canFix={fixable.has(selected.kind)}
      onClose={() => setSelected(null)} onCounts={load} />}
  </>;
}

function QualityDrawer({ item, canFix = false, onClose, onCounts }) {
  const [page, setPage] = useState(1); const [data, setData] = useState(null); const [err, setErr] = useState(''); const limit = 30;
  const [busy, setBusy] = useState(''); const [askBulk, setAskBulk] = useState(false);
  const [editing, setEditing] = useState(null); const [attaching, setAttaching] = useState(null); const [removing, setRemoving] = useState(null);
  const load = () => { setErr(''); setData(null); api.dataQualityItems(item.kind, { skip: (page - 1) * limit, limit }).then(setData).catch(e => setErr(errText(e))); };
  useEffect(load, [page, item.kind]);
  const resolved = msg => { toast(msg, 'ok'); setEditing(null); setAttaching(null); load(); onCounts?.(); };

  const bulkFix = async () => {
    setBusy('bulk');
    try {
      const r = await api.dataQualityFix(item.kind);
      toast(`${item.label}: ${fa(r.removed)} رکورد اصلاح شد`, r.removed ? 'ok' : 'warn');
      setAskBulk(false); load(); onCounts?.();
    } catch (e) { toast(errText(e), 'bad'); }
    finally { setBusy(''); }
  };
  const removeOne = async row => {
    setBusy(row.id);
    try {
      await api.dataQualityRemove(item.kind, row.id);
      resolved('رکورد حذف شد و مورد از صف خارج شد ✅');
    } catch (e) { toast(errText(e), 'bad'); }
    finally { setBusy(''); setRemoving(null); }
  };
  const attachOne = async (row, parentId) => {
    setBusy(row.id);
    try {
      await api.dataQualityAttach(item.kind, row.id, parentId);
      resolved('اتصال به والد معتبر انجام شد ✅');
    } catch (e) { toast(errText(e), 'bad'); }
    finally { setBusy(''); }
  };

  return <Drawer wide title={`🧬 ${item.label}`} onClose={onClose}>
    {canFix && !!data?.total && <div className="row" style={{ marginBottom: 10 }}>
      <span className="muted">این رکوردها والدِ معتبر ندارند و هیچ‌جا نمایش داده نمی‌شدند.</span>
      <span className="spacer" />
      <button className="btn sm danger" disabled={!!busy} onClick={() => setAskBulk(true)}>
        {busy === 'bulk' ? '…' : `🔧 اصلاح دسته‌ای ${fa(data.total)} رکورد`}</button>
    </div>}
    {err ? <ErrorState error={err} onRetry={load} /> : !data ? <Loading rows={5} /> :
      !data.total ? <Empty icon="✅" text="همه موارد این بررسی برطرف شده‌اند" /> : <>
        <div className="q-list">
          {(data.items || []).map(row => <QualityIssueCard key={row.id} row={row} busy={busy}
            editing={editing === row.id} attaching={attaching === row.id}
            onEdit={() => { setEditing(editing === row.id ? null : row.id); setAttaching(null); }}
            onAttach={() => { setAttaching(attaching === row.id ? null : row.id); setEditing(null); }}
            onRemove={() => setRemoving(row.id)}
            onAttached={pid => attachOne(row, pid)}
            onSave={async body => {
              setBusy(row.id);
              try {
                const r = await api.dataQualityRepair(row.id, body);
                resolved(r.resolved ? 'اصلاح ذخیره شد و مورد برطرف شد ✅' : 'ذخیره شد؛ هنوز فیلد الزامی ناقص است');
              } catch (e) { toast(errText(e), 'bad'); }
              finally { setBusy(''); }
            }} />)}
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>‹ قبلی</button>
          <span className="muted">صفحه {fa(page)} از {fa(Math.max(1, Math.ceil((data.total || 0) / limit)))} · {fa(data.total)} مورد</span>
          <span className="spacer" />
          <button className="btn sm" disabled={page * limit >= (data.total || 0)} onClick={() => setPage(p => p + 1)}>بعدی ›</button>
        </div>
      </>}
    {askBulk && <Confirm danger onNo={() => setAskBulk(false)} onYes={bulkFix}
      text={`این عملیات ${fa(data?.total || 0)} رکوردِ «${item.label}» را حذف می‌کند. این رکوردها والدِ معتبر ندارند و هیچ‌جا نمایش داده نمی‌شدند. تغییر در حسابرسی ثبت می‌شود و بازگشت‌پذیر نیست.`} />}
    {removing && <Confirm danger onNo={() => setRemoving(null)} onYes={() => removeOne((data?.items || []).find(r => r.id === removing))}
      text="این رکورد یتیم حذف می‌شود. تغییر در حسابرسی ثبت می‌شود و بازگشت‌پذیر نیست." />}
  </Drawer>;
}

// 🌊 W5 — کارت انسانی هر issue: عنوان، context، کمبودها، اقدام مستقیم، جزئیات فنی جمع‌شده.
function QualityIssueCard({ row, busy, editing, attaching, onEdit, onAttach, onRemove, onSave, onAttached }) {
  return <div className={`q-issue q-issue--${row.severity || 'info'}`}>
    <div className="q-issue-head">
      <span className="q-issue-icon">{row.severity === 'critical' ? '⛔' : row.severity === 'warning' ? '⚠️' : '📄'}</span>
      <div style={{ flex: 1 }}>
        <b>{row.title}</b>
        {row.context && <div className="muted" style={{ marginTop: 2 }}>{row.context}</div>}
      </div>
      <B kind={row.severity === 'critical' ? 'bad' : row.severity === 'warning' ? 'warn' : 'acc'}>{row.severity === 'critical' ? 'بحرانی' : row.severity === 'warning' ? 'هشدار' : 'اطلاعات'}</B>
    </div>
    {!!(row.missing || []).length && <div className="row q-missing">
      <span className="muted">ناقص:</span>
      {row.missing.map(m => <B key={m} kind="warn">{FIELD_FA[m] || m}</B>)}
    </div>}
    <div className="muted" style={{ marginTop: 6 }}>چرا مهم است: {row.reason} · اقدام پیشنهادی: {row.suggestion}</div>
    <details className="q-tech"><summary>جزئیات فنی</summary>
      <div className="code muted text-wrap">{row.technical}{Object.entries(row.metadata || {}).length ? ' · ' + Object.entries(row.metadata).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join('|') : v}`).join(' · ') : ''}</div>
    </details>
    <div className="row" style={{ marginTop: 8, gap: 8 }}>
      {row.repair?.edit && <button className="btn sm primary" disabled={!!busy} onClick={onEdit}>{editing ? 'بستن فرم' : '✏️ تکمیل/ویرایش اطلاعات'}</button>}
      {row.repair?.attach && <button className="btn sm" disabled={!!busy} onClick={onAttach}>{attaching ? 'بستن' : '🔗 اتصال به والد معتبر'}</button>}
      {row.repair?.delete && <button className="btn sm danger" disabled={!!busy} onClick={onRemove}>🗑 حذف رکورد</button>}
      {busy === row.id && <span className="muted">…</span>}
    </div>
    {editing && <EditMetaForm initial={row.current || {}} onSave={onSave} />}
    {attaching && <AttachPicker parentKind={row.repair?.attach} onPick={onAttached} />}
  </div>;
}

function EditMetaForm({ initial, onSave }) {
  const [name, setName] = useState(initial.name || '');
  const [type, setType] = useState(initial.type || '');
  const [description, setDescription] = useState(initial.description || '');
  return <div className="q-form">
    <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
      <input className="inp" style={{ flex: 1, minWidth: 180 }} placeholder="نام/عنوان فایل" value={name} onChange={e => setName(e.target.value)} />
      <select className="inp" style={{ width: 130 }} value={type} onChange={e => setType(e.target.value)}>
        <option value="">— نوع —</option>
        {CONTENT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
      </select>
    </div>
    <textarea className="inp" rows={2} style={{ marginTop: 8, width: '100%' }} placeholder="توضیح (برای دانشجو نمایش داده می‌شود)" value={description} onChange={e => setDescription(e.target.value)} />
    <div className="row" style={{ marginTop: 8 }}>
      <button className="btn sm ok" onClick={() => onSave({ name: name.trim(), type: type.trim(), description: description.trim() })}>💾 ذخیره و بازبررسی</button>
      <span className="muted">پس از ذخیره، rule دوباره اجرا می‌شود؛ اگر کامل باشد مورد حذف می‌شود.</span>
    </div>
  </div>;
}

function AttachPicker({ parentKind, onPick }) {
  const [q, setQ] = useState(''); const [hits, setHits] = useState(null); const [err, setErr] = useState('');
  const load = () => { setErr(''); api.dataQualityParents(parentKind, q).then(setHits).catch(e => setErr(errText(e))); };
  useEffect(() => { const t = setTimeout(load, q ? 250 : 0); return () => clearTimeout(t); }, [q]);
  return <div className="q-form">
    <input className="inp" style={{ width: '100%' }} placeholder="جست‌وجوی والد معتبر (نام…) — خالی = ۲۰ تای اول" value={q} onChange={e => setQ(e.target.value)} />
    {err && <div className="muted" style={{ color: 'var(--bad)', marginTop: 6 }}>{err}</div>}
    <div className="q-parents">
      {(hits?.items || []).map(p => <button key={p.id} className="btn sm" onClick={() => onPick(p.id)}>🔗 {p.label}</button>)}
      {hits && !hits.items.length && <span className="muted">موردی پیدا نشد</span>}
    </div>
  </div>;
}
