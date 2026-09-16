import React, { useEffect, useState } from 'react';
import { api, errText } from './api.js';
import { B, DiffViewer, Drawer, Empty, ErrorState, Loading, Tabs, Timeline } from './ui.jsx';

export default function ObjectInspector({ type, id, go, onClose }) {
  const [summary, setSummary] = useState(null); const [history, setHistory] = useState(null); const [err, setErr] = useState(''); const [tab, setTab] = useState('summary'); const [event, setEvent] = useState(null);
  const load = async () => { setErr(''); try { const [s, h] = await Promise.all([api.objectSummary(type, id), api.objectHistory(type, id).catch(() => ({ items: [] }))]); setSummary(s); setHistory(h.items || []); } catch (e) { setErr(errText(e)); } };
  useEffect(() => { load(); }, [type, id]);
  return <Drawer wide title={`Object Inspector · ${type}`} onClose={onClose}>
    {err ? <ErrorState error={err} onRetry={load} /> : !summary ? <Loading rows={6} /> : <>
      <div className="object-identity"><div><div className="muted">{summary.identity?.type}</div><b>{summary.identity?.label || summary.identity?.id}</b><div className="code">{summary.identity?.id}</div></div><B kind="acc">{summary.status || '—'}</B></div>
      <Tabs items={[['summary', 'خلاصه'], ['relations', 'ارتباط‌ها'], ['history', 'تاریخچه']]} value={tab} onChange={setTab} label="بخش‌های بازرس object" />
      {tab === 'summary' && <><dl className="kv">{Object.entries(summary.metadata || {}).map(([key, value]) => <React.Fragment key={key}><dt>{key}</dt><dd className={/id|username|date|at/.test(key) ? 'code' : ''}>{format(value)}</dd></React.Fragment>)}</dl>
        {!!summary.available_actions?.length && <div className="surface-inset"><div className="muted">عملیات پشتیبانی‌شده در صفحه domain</div><div className="row">{summary.available_actions.map(action => <B key={action}>{action}</B>)}</div></div>}</>}
      {tab === 'relations' && (!(summary.relations || []).length ? <Empty icon="🔗" text="رابطه ثبت‌شده‌ای برای این object نیست" /> : <div className="grid">{summary.relations.map((relation, index) => <button key={`${relation.type}-${index}`} className="panel panel-pad operation-card" disabled={!relation.go} onClick={() => relation.go && go?.(relation.go)}><span>🔗</span><span className="operation-body"><b>{relation.label}</b><span className="muted">{relation.type}{relation.id ? ` · ${relation.id}` : ''}</span></span>{relation.count != null && <B>{Number(relation.count).toLocaleString('fa')}</B>}<span>‹</span></button>)}</div>)}
      {tab === 'history' && <><Timeline items={(history || []).map(item => ({ title: item.title, at: item.at, description: item.actor, severity: item.severity, onClick: () => setEvent(item) }))} empty="تاریخچه‌ای ثبت نشده" />
        {event && <div className="surface-inset" style={{ marginTop: 10 }}><div className="row"><b>{event.title}</b><button className="btn sm" onClick={() => setEvent(null)}>بستن Diff</button></div><DiffViewer before={Object.fromEntries((event.changes || []).map(x => [x.field, x.before]))} after={Object.fromEntries((event.changes || []).map(x => [x.field, x.after]))} /></div>}</>}
    </>}
  </Drawer>;
}

function format(value) {
  if (value === null || value === undefined || value === '') return '—';
  if (Array.isArray(value)) return value.join('، ') || '—';
  if (typeof value === 'object') return JSON.stringify(value);
  if (value === true) return 'بله'; if (value === false) return 'خیر';
  return String(value);
}
