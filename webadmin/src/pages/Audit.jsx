import React, { useEffect, useState } from 'react';
import { api, errText } from '../api.js';
import { DataTable, Loading, ErrorState, B, FaDateTime, FilterBar, PageHeader, Drawer, NoPerm, Empty, Timeline, Modal, toast } from '../ui.jsx';
import { PersianDatePicker } from '../PersianDatePicker.jsx';
import SavedViews from '../SavedViews.jsx';
import { queryNumber, readHashQuery, writeHashQuery } from '../urlState.js';
import ObjectInspector from '../ObjectInspector.jsx';

const fa = (n) => Number(n ?? 0).toLocaleString('fa-IR');

// 🧭 لاگ حسابرسی + 🌊 موج Audit-Diff: کشوی «قبل/بعد» برای رویدادهای دارای
// changes (db.log_action از همیشه آن‌ها را ذخیره می‌کرد؛ حالا پنل وب هم
// می‌نویسد و هم اینجا به‌صورت بصری نمایش می‌دهد). FIX: متادیتای تو در تو
// (actor/target/timestamp) — قبلاً فیلدهای تخت خوانده می‌شد و خالی می‌ماند.
const SEV = { INFO: '', WARNING: 'warn', HIGH: 'bad', CRITICAL: 'bad' };
const SEV_RANK = { INFO: 0, WARNING: 1, HIGH: 2, CRITICAL: 3 };
const SEV_ICON = { INFO: 'ℹ️', WARNING: '⚠️', HIGH: '🔥', CRITICAL: '⛔' };
const MOD_FA = {
  Users: 'کاربران', Roles: 'نقش‌ها', Settings: 'تنظیمات', Questions: 'سوالات',
  Content: 'محتوا', Schedules: 'برنامه کلاسی', Tickets: 'تیکت‌ها', Reports: 'گزارش‌ها',
  Notifications: 'اعلان‌ها', Backup: 'بکاپ', System: 'سیستم', Auth: 'ورود/خروج',
  Subscription: 'اشتراک', Grades: 'نمرات', WebAdmin: 'پنل وب',
};
const CAT_FA = { admin: 'مدیریت', content: 'محتوا', user: 'کاربر' };

const actorName = (r) => r.actor?.name ?? r.actor_name ?? '—';
const actorRole = (r) => r.actor?.role ?? r.actor_role ?? '';
const actorId = (r) => r.actor?.id ?? r.actor_id ?? '';
const targetLabel = (r) => r.target?.label ?? r.target_label ?? '';
const targetId = (r) => r.target?.id ?? r.target_id ?? '';
const targetType = (r) => r.target?.type ?? r.target_type ?? '';
const atOf = (r) => r.timestamp ?? r.at ?? r.created_at ?? '';

const valText = (v) => {
  if (v === null || v === undefined) return '—';
  if (v === true) return 'فعال';
  if (v === false) return 'غیرفعال';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v) === '' ? '(خالی)' : String(v);
};

export default function Audit({ go }) {
  const initial = readHashQuery();
  const initialFilters = Object.fromEntries(['category', 'min_severity', 'q', 'actor', 'actor_role', 'module', 'action', 'target_type', 'target', 'date_from', 'date_to', 'correlation_id'].map(k => [k, initial.get(k) || '']));
  const [filters, setFilters] = useState(initialFilters);
  const [q2, setQ2] = useState(initialFilters.q);
  const [advanced, setAdvanced] = useState(['actor', 'actor_role', 'module', 'action', 'target_type', 'target', 'date_from', 'date_to', 'correlation_id'].some(k => initialFilters[k]));
  const [sortDir, setSortDir] = useState(initial.get('sort_dir') || 'desc');
  const [skip, setSkip] = useState((queryNumber(initial, 'page', 1) - 1) * 25);
  const [rows, setRows] = useState(null);
  const [counters, setCounters] = useState(null);
  const [total, setTotal] = useState(0);
  const [err, setErr] = useState('');
  const [denied, setDenied] = useState(false);
  const [detail, setDetail] = useState(null);
  const [inspect, setInspect] = useState(null);
  // ↩️ §۸۸ — بازگردانی: {log, reason} تا تأیید صریح گرفته شود.
  const [undoT, setUndoT] = useState(null);
  const [chain, setChain] = useState(null);
  const [visibleColumns, setVisibleColumns] = useState([]);
  const [undoBusy, setUndoBusy] = useState(false);
  const [csvBusy, setCsvBusy] = useState(false);
  const LIMIT = 25;

  useEffect(() => { const t = setTimeout(() => setFilters(f => ({ ...f, q: q2 })), 350); return () => clearTimeout(t); }, [q2]);
  useEffect(() => { writeHashQuery('/audit', { ...filters, q: q2, sort_dir: sortDir !== 'desc' ? sortDir : '', page: skip ? skip / 25 + 1 : '' }); }, [filters, q2, sortDir, skip]);

  // ↩️ بازگردانی مخرب و برگشت‌ناپذیر است؛ بدون گاردِ همزمانی، دو کلیک
  // سریع دو درخواست می‌فرستد و دومی روی رکوردِ همین‌حالا بازگردانده‌شده
  // می‌افتد (۴۰۹ یا بدتر: drift). قفل در finally آزاد می‌شود تا حتی
  // با خطای شبکه هم دکمه قفل نماند.
  const runUndo = async () => {
    if (!undoT || undoBusy) return;
    setUndoBusy(true);
    try {
      await api.auditUndo(undoT.log._id || undoT.log.id, undoT.reason);
      toast('تغییر بازگردانده شد ↩️');
      setUndoT(null); setDetail(null); load();
    } catch (e) { toast(errText(e), 'err'); }
    finally { setUndoBusy(false); }
  };
  const load = async () => {
    setErr('');
    try {
      const r = await api.auditLogs({ ...filters, sort_dir: sortDir, skip, limit: LIMIT });
      setRows(r.logs || r.items || []);
      setCounters(r.counters || null);
      setTotal(r.total || 0);
    } catch (e) {
      if (e.status === 403) setDenied(true);
      else setErr(errText(e));
    }
  };
  useEffect(() => { load(); }, [filters, sortDir, skip]);

  if (denied) return <NoPerm text="مشاهده‌ی لاگ حسابرسی نیازمند مجوز audit.view است" />;
  if (err) return <ErrorState error={err} onRetry={load} />;

  const setSev = (s) => { setFilters(f => ({ ...f, min_severity: f.min_severity === s ? '' : s })); setSkip(0); };
  const objectRoute = (type, id) => ({ user: `/users?q=${id}`, ticket: `/tickets?q=${id}`,
    payment: '/subscriptions?tab=payments', subscription: '/subscriptions?tab=subscribers',
    question: `/questions?q=${id}`, exam: '/exams' }[type]);

  const cols = [
    { k: 'at', label: 'زمان', sortable: true,
      render: r => <FaDateTime value={atOf(r)} /> },
    { k: 'actor', label: 'عامل', stop: true, render: r => (
      <button className="btn sm" disabled={!actorId(r)} onClick={() => actorId(r) && go?.(`/users?q=${actorId(r)}`)}>{actorName(r)}<span className="muted" style={{ display: 'block' }}>{actorRole(r)}</span></button>) },
    { k: 'action', label: 'عمل', render: r => <b style={{ color: 'var(--txt)' }}>{r.action}</b> },
    { k: 'module', label: 'ماژول', render: r => <B>{MOD_FA[r.module] || r.module || '—'}</B> },
    { k: 'target', label: 'هدف', stop: true, render: r => objectRoute(targetType(r), targetId(r))
      ? <button className="btn sm" onClick={() => go?.(objectRoute(targetType(r), targetId(r)))}>{targetLabel(r) || targetId(r) || '—'}</button>
      : <span className="muted">{targetLabel(r) || targetId(r) || '—'}</span> },
    { k: 'diff', label: 'Δ', width: 46, render: r =>
      (r.changes || []).length > 0
        ? <B kind="acc" title={`${fa(r.changes.length)} تغییر میدانی`}>Δ {fa(r.changes.length)}</B>
        : <span className="muted">·</span> },
    { k: 'severity', label: 'شدت',
      render: r => <B kind={SEV[r.severity] || ''}>{SEV_ICON[r.severity] || ''} {r.severity || 'INFO'}</B> },
  ];

  return (
    <>
      <PageHeader title="لاگ حسابرسی" description="ردیابی اعمال حساس با عامل، هدف، شدت و تغییرات قبل/بعد"
        actions={<>{rows && <B>{fa(total)} رویداد</B>}<button className="btn sm" title="خروجی CSV از همه‌ی رویدادهای فیلترشده" onClick={() => api.exportAuditCsv({ ...filters, sort_dir: sortDir })}>📥 CSV همین فیلترها</button></>} />

      {/* شمارنده‌ی سطوح (کلیک ⇒ فیلتر سریع) */}
      {counters && (
        <div className="row" style={{ marginBottom: 10, flexWrap: 'wrap', gap: 6 }}>
          {['INFO', 'WARNING', 'HIGH', 'CRITICAL'].map(s => (
            <button key={s}
                    className={`btn sm ${filters.min_severity === s ? 'primary' : ''}`}
                    onClick={() => setSev(s)}>
              {SEV_ICON[s]} {s} <span className="num">{fa(counters[s] || 0)}</span>
            </button>
          ))}
        </div>
      )}

      <FilterBar>
        <input className="inp" style={{ flex: 1, minWidth: 200 }} placeholder="🔎 جست‌وجو در عمل/عامل/هدف…"
               value={q2} onChange={e => { setQ2(e.target.value); setSkip(0); }} />
        <select className="inp" value={filters.category}
                onChange={e => { setFilters(f => ({ ...f, category: e.target.value })); setSkip(0); }}>
          <option value="">همه‌ی دسته‌ها</option>
          <option value="admin">مدیریت</option>
          <option value="content">محتوا</option>
          <option value="user">کاربر</option>
        </select>
        <select className="inp" value={filters.min_severity}
                onChange={e => { setFilters(f => ({ ...f, min_severity: e.target.value })); setSkip(0); }}>
          <option value="">همه‌ی شدت‌ها</option>
          <option value="WARNING">از WARNING</option>
          <option value="HIGH">از HIGH</option>
          <option value="CRITICAL">فقط CRITICAL</option>
        </select>
        <button className={`btn sm ${advanced ? 'primary' : ''}`} aria-expanded={advanced} onClick={() => setAdvanced(x => !x)}>⚙ بررسی پیشرفته</button>
      </FilterBar>
      {advanced && <FilterBar className="advanced-filter-bar">
        <input className="inp" placeholder="عامل یا Actor ID…" value={filters.actor} onChange={e => { setFilters(f => ({ ...f, actor: e.target.value })); setSkip(0); }} />
        <input className="inp" placeholder="نقش عامل…" value={filters.actor_role} onChange={e => { setFilters(f => ({ ...f, actor_role: e.target.value })); setSkip(0); }} />
        <select className="inp" value={filters.module} onChange={e => { setFilters(f => ({ ...f, module: e.target.value })); setSkip(0); }}>
          <option value="">همه ماژول‌ها</option>{Object.keys(MOD_FA).map(m => <option key={m} value={m}>{MOD_FA[m]}</option>)}
        </select>
        <input className="inp" placeholder="عمل مشخص…" value={filters.action} onChange={e => { setFilters(f => ({ ...f, action: e.target.value })); setSkip(0); }} />
        <input className="inp" placeholder="نوع هدف…" value={filters.target_type} onChange={e => { setFilters(f => ({ ...f, target_type: e.target.value })); setSkip(0); }} />
        <input className="inp" placeholder="هدف/شناسه…" value={filters.target} onChange={e => { setFilters(f => ({ ...f, target: e.target.value })); setSkip(0); }} />
        <label className="row"><span className="muted">از</span><PersianDatePicker value={filters.date_from} onChange={value => { setFilters(f => ({ ...f, date_from: value })); setSkip(0); }} ariaLabel="از تاریخ شمسی حسابرسی" /></label>
        <label className="row"><span className="muted">تا</span><PersianDatePicker value={filters.date_to} onChange={value => { setFilters(f => ({ ...f, date_to: value })); setSkip(0); }} ariaLabel="تا تاریخ شمسی حسابرسی" /></label>
        <input className="inp code" placeholder="Correlation ID…" value={filters.correlation_id} onChange={e => { setFilters(f => ({ ...f, correlation_id: e.target.value })); setSkip(0); }} />
        <button className="btn sm" onClick={() => { setFilters(f => ({ ...f, actor: '', actor_role: '', module: '', action: '', target_type: '', target: '', date_from: '', date_to: '', correlation_id: '' })); setSkip(0); }}>پاک‌کردن پیشرفته</button>
      </FilterBar>}

      <SavedViews scope="audit" filters={{ ...filters, sortDir }} columns={visibleColumns} sort={{ key: 'timestamp', dir: sortDir }} onApply={(f, item) => { setFilters(x => ({ ...x, ...f, sortDir: undefined })); setQ2(f.q || ''); setSortDir(f.sortDir || item.sort?.dir || 'desc'); setVisibleColumns(item.columns || []); setAdvanced(!!(f.actor || f.actor_role || f.module || f.action || f.target || f.date_from || f.date_to || f.correlation_id)); setSkip(0); }} label="تحقیق‌های ذخیره‌شده" />

      {!rows ? <Loading /> : rows.length === 0 ? (
        <Empty icon="🧾" text="رویدادی با این فیلترها نیست" />
      ) : (
        <DataTable columns={cols} rows={rows} rowKey={(r) => r.id || r._id}
          onRow={setDetail} colToggle visibleColumns={visibleColumns} onColumnsChange={setVisibleColumns}
          sortState={{ k: 'at', dir: sortDir }} onSort={next => { setSortDir(next?.dir || 'desc'); setSkip(0); }}
                   pager={{ page: skip / LIMIT + 1, pages: Math.max(1, Math.ceil(total / LIMIT)),
                            total, onPage: p => setSkip((p - 1) * LIMIT) }} />
      )}

      {inspect && <ObjectInspector type={inspect.type} id={inspect.id} go={go} onClose={() => setInspect(null)} />}
      {chain && <CorrelationDrawer id={chain} onClose={() => setChain(null)} />}
      {undoT && <Modal title="↩️ بازگردانی تغییر" onClose={() => setUndoT(null)}>
        <p className="muted" style={{ marginTop: 0 }}>
          مقادیر پیشین این رویداد دوباره نوشته می‌شوند. اگر بعد از این
          رویداد کسی همان فیلدها را عوض کرده باشد، بازگردانی انجام
          <b> نمی‌شود</b> تا کارِ او بی‌صدا پاک نشود.
        </p>
        <div className="diff-tbl" style={{ marginBottom: 10 }}>
          <div className="diff-head"><span>فیلد</span><span>اکنون</span><span /><span>بازگردانی به</span></div>
          {(undoT.log.changes || []).map((c, i) => (
            <div key={i} className="diff-row">
              <span className="diff-f">{c.field}</span>
              <span className="diff-v b">{valText(c.after)}</span>
              <span className="diff-arrow">←</span>
              <span className="diff-v a">{valText(c.before)}</span>
            </div>
          ))}
        </div>
        <input className="inp" placeholder="دلیل بازگردانی (اختیاری)"
               value={undoT.reason}
               onChange={e => setUndoT({ ...undoT, reason: e.target.value })} />
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn danger" disabled={undoBusy} onClick={runUndo}>{undoBusy ? '⏳ در حال بازگردانی…' : '↩️ بازگردانی کن'}</button>
          <button className="btn" disabled={undoBusy} onClick={() => setUndoT(null)}>انصراف</button>
        </div>
      </Modal>}
      {detail && (
        <Drawer title="🔍 جزئیات و تغییرات رویداد" onClose={() => setDetail(null)} wide>
          <div className="row" style={{ flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
            <b style={{ fontSize: 'var(--fs-section)' }}>{detail.action}</b>
            <B kind={SEV[detail.severity] || ''}>{SEV_ICON[detail.severity] || ''} {detail.severity || 'INFO'}</B>
            <B>{MOD_FA[detail.module] || detail.module || '—'}</B>
            {detail.category && <B kind="purple">{CAT_FA[detail.category] || detail.category}</B>}
          </div>

          <div className="grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <div className="ct3-kv"><span className="muted">زمان</span>
              <FaDateTime value={atOf(detail)} /></div>
            <div className="ct3-kv"><span className="muted">عامل</span>
              <span>{actorName(detail)} <span className="muted">{actorRole(detail)}</span>{' '}
                <span className="code">{actorId(detail)}</span></span></div>
            <div className="ct3-kv"><span className="muted">هدف</span>
              <span>{targetLabel(detail) || '—'} {targetType(detail) && <span className="muted">({targetType(detail)})</span>}</span></div>
            <div className="ct3-kv"><span className="muted">شناسه‌ی هدف</span>
              <span className="code" style={{ fontSize: 'var(--fs-label)' }}>{targetId(detail) || '—'}</span></div>
            <div className="ct3-kv"><span className="muted">Correlation ID</span>
              <span className="code" style={{ fontSize: 'var(--fs-label)' }}>{detail.correlation_id || '—'}</span></div>
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            {actorId(detail) && <button className="btn sm" onClick={() => go?.(`/users?q=${actorId(detail)}`)}>👤 پرونده عامل</button>}
            {objectRoute(targetType(detail), targetId(detail)) && <button className="btn sm primary" onClick={() => go?.(objectRoute(targetType(detail), targetId(detail)))}>بازکردن هدف ‹</button>}
            {targetType(detail) && targetId(detail) && <button className="btn sm" onClick={() => { setInspect({ type: targetType(detail), id: targetId(detail) }); setDetail(null); }}>▤ Object Inspector</button>}
            {detail.correlation_id && <button className="btn sm" onClick={() => { setChain(detail.correlation_id); setDetail(null); }}>🧬 زنجیره Correlation</button>}
            {/* ↩️ §۸۸ — فقط برای رویدادهای بازگردانی‌پذیر و بازگردانی‌نشده. */}
            {detail.undone_at
              ? <B kind="ok">↩️ بازگردانده شده</B>
              : (detail.target?.type === 'users' && (detail.changes || []).length > 0 &&
                 <button className="btn sm danger"
                         onClick={() => setUndoT({ log: detail, reason: '' })}>
                   ↩️ بازگردانی
                 </button>)}
          </div>

          {/* ── Diff قبل/بعد ── */}
          <div style={{ marginTop: 14 }}>
            <b>🧬 تغییرات میدانی</b>
            {(detail.changes || []).length === 0 ? (
              <p className="muted" style={{ marginTop: 8 }}>
                این رویداد تغییر میدانی (before/after) ندارد
                {detail.details ? '' : ' — جزئیات در متن عمل ثبت شده است.'}
              </p>
            ) : (
              <div className="diff-tbl" style={{ marginTop: 8 }}>
                <div className="diff-head">
                  <span>فیلد</span><span>قبل</span><span /><span>بعد</span>
                </div>
                {detail.changes.map((c, i) => {
                  const b = valText(c.before), a = valText(c.after);
                  return (
                    <div key={i} className="diff-row">
                      <span className="diff-f">{c.field}</span>
                      <span className={`diff-v b ${b === '—' ? 'none' : ''}`} title={b}>{b}</span>
                      <span className="diff-arrow">←</span>
                      <span className={`diff-v a ${a === '—' ? 'none' : ''}`} title={a}>{a}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {detail.details && (
            <div style={{ marginTop: 12 }}>
              <b>📝 جزئیات</b>
              <div className="panel panel-pad" style={{ background: 'var(--bg)', marginTop: 6, whiteSpace: 'pre-wrap', fontSize: 'var(--fs-body)' }}>
                {detail.details}
              </div>
            </div>
          )}
          {(detail.tags || []).length > 0 && (
            <div className="row" style={{ marginTop: 12, flexWrap: 'wrap', gap: 5 }}>
              {(detail.tags || []).map(t => <B key={t}>#{t}</B>)}
            </div>
          )}
          {detail.correlation_id && (
            <div className="muted" style={{ marginTop: 10, fontSize: 'var(--fs-label)' }}>
              Correlation: <span className="code">{detail.correlation_id}</span>
            </div>
          )}
        </Drawer>
      )}
    </>
  );
}

function CorrelationDrawer({ id, onClose }) {
  const [data, setData] = useState(null); const [err, setErr] = useState('');
  const load = () => { setErr(''); setData(null); api.correlationChain(id).then(setData).catch(e => setErr(errText(e))); };
  useEffect(load, [id]);
  return <Drawer wide title="🧬 زنجیره Correlation" onClose={onClose}>
    <div className="code" style={{ marginBottom: 10 }}>{id}</div>
    {err ? <ErrorState error={err} onRetry={load} /> : !data ? <Loading rows={5} /> : <>
      <div className="row" style={{ marginBottom: 10 }}><B kind="acc">Audit: {fa(data.counts?.audit)}</B><B>Outbox: {fa(data.counts?.outbox)}</B></div>
      <Timeline items={(data.events || []).map(event => ({ id: event.id, title: `${event.stage === 'audit' ? '🧭' : '📤'} ${event.title}`, description: `${event.status} · ${Object.entries(event.metadata || {}).filter(([, v]) => v).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · ')}`, at: event.at || '' }))} empty="رویدادی برای این Correlation ثبت نشده" />
    </>}
  </Drawer>;
}
