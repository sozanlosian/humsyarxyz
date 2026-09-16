import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { formatFaDate, formatFaDateTime, formatFaTime, formatFaTooltip, formatRelativeTime } from './time.js';

// ── Toast ─────────────────────────────────────────────────────────
let _push;
let _toastSeq = 0;
export function toast(msg, kind = 'ok') { _push && _push(msg, kind); }

export function ToastHost() {
  const [items, setItems] = useState([]);
  const timers = useRef(new Map());
  const dismiss = useCallback(id => {
    window.clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setItems(s => s.filter(t => t.id !== id));
  }, []);
  useEffect(() => {
    _push = (msg, kind) => {
      const id = `toast-${++_toastSeq}`;
      setItems(s => [...s.slice(-3), { id, msg: String(msg || ''), kind }]);
      // خطاها بیشتر می‌مانند: پیام خطا معمولاً باید خوانده و گاهی
      // یادداشت شود، در حالی که تأیید موفقیت گذراست.
      const ttl = kind === 'err' ? 7000 : 3400;
      timers.current.set(id, window.setTimeout(() => dismiss(id), ttl));
    };
    const map = timers.current;
    return () => { _push = undefined; map.forEach(window.clearTimeout); map.clear(); };
  }, [dismiss]);
  // دو ناحیه‌ی جدا: خطا assertive اعلام می‌شود (بلافاصله)، بقیه polite.
  // یک ناحیه‌ی مشترک باعث می‌شد خطاها پشت پیام‌های موفقیت صف بکشند.
  const split = kind => items.filter(t => (kind === 'err' ? t.kind === 'err' : t.kind !== 'err'));
  const render = t => <div key={t.id} className={`toast ${t.kind}`} role={t.kind === 'err' ? 'alert' : 'status'}>
    <span className="toast-msg">{t.msg}</span>
    <button type="button" className="toast-x" onClick={() => dismiss(t.id)} aria-label="بستن پیام">✕</button>
  </div>;
  return (
    <div className="toast-box">
      <div aria-live="assertive" aria-atomic="false">{split('err').map(render)}</div>
      <div aria-live="polite" aria-atomic="false">{split('ok').map(render)}</div>
    </div>
  );
}

// ── Page / section primitives ─────────────────────────────────────
export function PageHeader({ title, description, eyebrow, actions, children }) {
  return (
    <header className="page-header">
      <div className="page-header-main">
        {eyebrow && <div className="muted">{eyebrow}</div>}
        <h1 className="page-title">{title}</h1>
        {description && <div className="page-description">{description}</div>}
        {children}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function SectionHeader({ title, description, actions }) {
  return (
    <div className="section-header">
      <div><div className="section-title">{title}</div>{description && <div className="section-description">{description}</div>}</div>
      <span className="spacer" />
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

export function FilterBar({ children, className = '' }) {
  return <div className={`filter-bar ${className}`.trim()}>{children}</div>;
}

export function Field({ label, hint, error, children, className = '' }) {
  return <label className={`fld ${className}`.trim()}>
    {label && <span>{label}</span>}{children}
    {error ? <small className="field-error">{error}</small> : hint ? <small className="field-help">{hint}</small> : null}
  </label>;
}

export function FormSection({ title, description, actions, children }) {
  return <section className="form-section">
    {(title || actions) && <SectionHeader title={title} description={description} actions={actions} />}
    {children}
  </section>;
}

export function Tabs({ items, value, onChange, label = 'بخش‌ها' }) {
  return <div className="tabs" role="tablist" aria-label={label}>
    {items.map(item => {
      const [key, text] = Array.isArray(item) ? item : [item.key, item.label];
      return <button key={key} type="button" role="tab" aria-selected={value === key}
        className={`tab ${value === key ? 'on' : ''}`} onClick={() => onChange(key)}>{text}</button>;
    })}
  </div>;
}

export function SegmentedControl({ items, value, onChange, label = 'انتخاب' }) {
  return <div className="segmented" role="group" aria-label={label}>
    {items.map(([key, text]) => <button type="button" key={key} className={value === key ? 'on' : ''}
      aria-pressed={value === key} onClick={() => onChange(key)}>{text}</button>)}
  </div>;
}

// ── Data states ───────────────────────────────────────────────────
export function Loading({ rows = 4, variant = 'rows', label = 'در حال بارگذاری' }) {
  const cls = {
    rows: 'skeleton-row', kpi: 'skeleton-kpi', chart: 'skeleton-chart',
    tree: 'skeleton-tree', chat: 'skeleton-chat',
  }[variant] || 'skeleton-row';
  return <div className="skeleton-list" role="status" aria-label={label} aria-busy="true">
    <span className="sr-only">{label}</span>
    {Array.from({ length: rows }).map((_, i) => <div key={i} className={`skel ${cls}`} />)}
  </div>;
}

export function Empty({ icon = '🗂', text = 'موردی یافت نشد', title, description, children, action }) {
  return <div className="state-shell">
    <div className="state-content">
      <div className="state-icon" role="img" aria-hidden="true">{icon}</div>
      <div className="state-title">{title || text}</div>
      {description && <div className="state-description">{description}</div>}
      {(children || action) && <div className="state-actions">{children || action}</div>}
    </div>
  </div>;
}

function errorInfo(error) {
  if (!error) return { message: 'خطای ناشناخته', technical: '', id: '' };
  if (typeof error === 'string') return { message: error, technical: '', id: '' };
  return {
    message: error.friendly || error.message || 'خطای ناشناخته',
    technical: error.technical || error.detail || '',
    id: error.errorId || error.error_id || '',
  };
}

export function ErrorState({ error, onRetry, title, description }) {
  const info = errorInfo(error);
  return <div className="state-shell" role="alert">
    <div className="state-content">
      <div className="state-icon" aria-hidden="true">⚠️</div>
      <div className="state-title">{title || 'در بارگذاری اطلاعات مشکلی پیش آمد'}</div>
      <div className="state-description">{description || info.message}</div>
      {info.id && <div className="error-id">Error ID: {info.id}</div>}
      {info.technical && info.technical !== info.message && <details className="error-details">
        <summary>جزئیات فنی</summary><pre>{info.technical}</pre>
      </details>}
      {onRetry && <div className="state-actions"><button className="btn" onClick={onRetry}>↻ تلاش مجدد</button></div>}
    </div>
  </div>;
}

export function NoPerm({ text = 'دسترسی لازم برای این بخش را ندارید' }) {
  return <div className="state-shell" role="alert"><div className="state-content">
    <div className="state-icon" aria-hidden="true">🔒</div>
    <div className="state-title">دسترسی محدود است</div><div className="state-description">{text}</div>
  </div></div>;
}

// ── Badges / status ───────────────────────────────────────────────
export function B({ kind = '', children, className = '', ...rest }) {
  return <span className={`badge ${kind} ${className}`.trim()} {...rest}>{children}</span>;
}

export function FaDate({ value, long = false, fallback = '—', className = '' }) {
  return <time className={`fa-time ${className}`.trim()} dateTime={value || undefined} title={formatFaTooltip(value, fallback)}>{formatFaDate(value, { long, fallback })}</time>;
}
export function FaDateTime({ value, long = false, fallback = '—', className = '' }) {
  return <time className={`fa-time ${className}`.trim()} dateTime={value || undefined} title={formatFaTooltip(value, fallback)}>{formatFaDateTime(value, { long, fallback })}</time>;
}
export function FaTime({ value, fallback = '—', className = '' }) {
  return <time className={`fa-time ${className}`.trim()} dateTime={value || undefined} title={formatFaTooltip(value, fallback)}>{formatFaTime(value, fallback)}</time>;
}
export function RelativeTime({ value, fallback = '—', className = '' }) {
  return <time className={`fa-time ${className}`.trim()} dateTime={value || undefined} title={formatFaTooltip(value, fallback)}>{value ? formatRelativeTime(value) : fallback}</time>;
}

export function StatusBadge({ status, label }) {
  const key = String(status || '').toLowerCase();
  const kind = ['active', 'approved', 'done', 'completed', 'healthy', 'ok'].includes(key) ? 'ok'
    : ['pending', 'warning', 'scheduled', 'reviewing', 'degraded'].includes(key) ? 'warn'
    : ['failed', 'rejected', 'critical', 'blocked', 'suspended', 'error'].includes(key) ? 'bad' : '';
  return <B kind={kind} className="status-badge"><span className="status-dot" />{label || status || '—'}</B>;
}

export function ScopeBadge({ scope, label }) {
  const key = scope === 'global' || !scope ? 'global' : scope === 'fork' || scope === 'override' ? 'override' : 'intake';
  const icon = key === 'global' ? '🌐' : key === 'override' ? '⭐' : '🏷';
  return <B className={`scope-badge ${key}`}>{icon} {label || (key === 'global' ? 'سراسری' : key === 'override' ? 'Override' : scope)}</B>;
}

export function Switch({ on, onChange, disabled, label }) {
  return <button type="button" className={`switch ${on ? 'on' : ''}`} disabled={disabled}
    onClick={() => onChange && onChange(!on)} role="switch" aria-checked={!!on}
    aria-label={label || (on ? 'روشن' : 'خاموش')}>
    <span className="knob" />
  </button>;
}

// ── DataTable v3 ──────────────────────────────────────────────────
const DATE_ONLY_KEYS = new Set(['date', 'exam_date']);
const isInstantKey = key => /(?:^timestamp$|_at$|^last_active$|^registered_at$|^last_run$|^end_date$|^start_date$)/.test(String(key || ''));
function defaultTableCell(column, row) {
  const value = row?.[column.k];
  if (value == null || value === '') return '—';
  if (DATE_ONLY_KEYS.has(column.k)) return <FaDate value={value} />;
  if (isInstantKey(column.k)) return <FaDateTime value={value} />;
  return value;
}

export function DataTable({ columns, rows, rowKey = 'id', selectable, onSelect,
  pager, loading, onRow, empty, colToggle, caption = 'جدول داده‌ها', density = 'compact',
  visibleColumns, onColumnsChange, sortState, onSort }) {
  const [sel, setSel] = useState(new Set());
  const [localSort, setLocalSort] = useState(null);
  const [densityMode, setDensityMode] = useState(() => localStorage.getItem('wa_table_density') || density);
  const [hidden, setHidden] = useState(() => new Set(visibleColumns?.length
    ? columns.filter(c => !visibleColumns.includes(c.k)).map(c => c.k) : []));
  const sort = sortState === undefined ? localSort : sortState;
  const [colMenu, setColMenu] = useState(false);
  const keyOf = (r, i) => typeof rowKey === 'function' ? rowKey(r, i) : r?.[rowKey];
  const rowList = rows || [];
  const rowSignature = rowList.map((r, i) => String(keyOf(r, i))).join('|');

  useEffect(() => {
    setSel(new Set());
    onSelect && onSelect([]);
  }, [rowSignature, pager?.page]);
  useEffect(() => {
    if (Array.isArray(visibleColumns)) setHidden(new Set(visibleColumns.length
      ? columns.filter(c => !visibleColumns.includes(c.k)).map(c => c.k) : []));
  }, [visibleColumns?.join('|'), columns.map(c => c.k).join('|')]);

  const toggle = (id) => {
    const next = new Set(sel); next.has(id) ? next.delete(id) : next.add(id);
    setSel(next); onSelect && onSelect([...next]);
  };
  const allIds = rowList.map(keyOf).filter(v => v !== undefined && v !== null);
  const allOn = allIds.length > 0 && allIds.every(id => sel.has(id));
  const toggleAll = () => {
    const next = allOn ? new Set() : new Set(allIds);
    setSel(next); onSelect && onSelect([...next]);
  };
  const visCols = columns.filter(c => !hidden.has(c.k));
  const sorted = useMemo(() => {
    if (!sort || onSort) return rowList;
    const col = columns.find(c => c.k === sort.k);
    if (!col?.sortable) return rowList;
    const val = r => col.sortVal ? col.sortVal(r) : r[col.k];
    return [...rowList].sort((a, b) => {
      const va = val(a); const vb = val(b); const na = Number(va); const nb = Number(vb);
      const cmp = va !== '' && vb !== '' && Number.isFinite(na) && Number.isFinite(nb)
        ? na - nb : String(va ?? '').localeCompare(String(vb ?? ''), 'fa');
      return sort.dir === 'asc' ? cmp : -cmp;
    });
  }, [rows, sort, columns, onSort]);
  const clickSort = c => {
    if (!c.sortable) return;
    const next = !sort || sort.k !== c.k ? { k: c.k, dir: 'asc' }
      : sort.dir === 'asc' ? { k: c.k, dir: 'desc' } : null;
    if (onSort) onSort(next); else setLocalSort(next);
  };
  const toggleColumn = key => setHidden(h => {
    const next = new Set(h); next.has(key) ? next.delete(key) : next.add(key);
    if (next.size >= columns.length) return h;
    onColumnsChange?.(columns.filter(c => !next.has(c.k)).map(c => c.k));
    return next;
  });

  return <div className="panel tbl-wrap" aria-busy={!!loading}>
    {colToggle && <div className="tbl-tools">
      <button className="btn sm" onClick={() => setDensityMode(current => {
        const next = current === 'compact' ? 'comfortable' : 'compact'; localStorage.setItem('wa_table_density', next); return next;
      })} aria-label="تغییر تراکم جدول">{densityMode === 'compact' ? '↕ فشرده' : '↕ راحت'}</button>
      <button className="btn sm" onClick={() => setColMenu(v => !v)} aria-expanded={colMenu}
        aria-haspopup="menu" aria-label="انتخاب ستون‌های جدول">☰ ستون‌ها</button>
      {colMenu && <div className="colmenu" role="menu">
        {columns.map(c => <label key={c.k} className="colmenu-item">
          <input type="checkbox" checked={!hidden.has(c.k)} onChange={() => toggleColumn(c.k)} /><span>{c.label || c.k}</span>
        </label>)}
      </div>}
    </div>}
    <div className="tbl-scroll">
      <table className={`tbl ${densityMode}`}>
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead><tr>
          {selectable && <th className="tbl-check"><input type="checkbox" checked={allOn} onChange={toggleAll} aria-label="انتخاب همه ردیف‌های صفحه" /></th>}
          {visCols.map(c => <th key={c.k} style={c.width ? { width: c.width } : undefined}
            onClick={() => clickSort(c)} aria-sort={c.sortable ? (sort?.k === c.k ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none') : undefined}>
            {c.sortable ? <button type="button" className="th-sort" onClick={e => { e.stopPropagation(); clickSort(c); }}>
              {c.label}<span className="sort-ic">{sort?.k === c.k ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ' ⇅'}</span>
            </button> : c.label}
          </th>)}
        </tr></thead>
        <tbody>
          {loading && <tr><td colSpan={visCols.length + (selectable ? 1 : 0)}><Loading rows={4} /></td></tr>}
          {!loading && !sorted.length && <tr><td colSpan={visCols.length + (selectable ? 1 : 0)}>{empty || <Empty />}</td></tr>}
          {!loading && sorted.map((r, i) => {
            const id = keyOf(r, i) ?? `row-${i}`;
            return <tr key={id} className={sel.has(id) ? 'sel' : ''} aria-selected={sel.has(id) || undefined}
              tabIndex={onRow ? 0 : undefined} onClick={() => onRow && onRow(r)}
              onKeyDown={e => {
                if (onRow && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onRow(r); }
                if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                  const rows = [...e.currentTarget.parentElement.querySelectorAll('tr[tabindex="0"]')];
                  const at = rows.indexOf(e.currentTarget); const next = e.key === 'ArrowDown' ? rows[at + 1] : rows[at - 1];
                  if (next) { e.preventDefault(); next.focus(); }
                }
              }}>
              {selectable && <td onClick={e => e.stopPropagation()}><input type="checkbox" checked={sel.has(id)}
                onChange={() => toggle(id)} aria-label={`انتخاب ردیف ${i + 1}`} /></td>}
              {visCols.map(c => <td key={c.k} onClick={c.stop ? e => e.stopPropagation() : undefined}>
                {c.render ? c.render(r) : defaultTableCell(c, r)}
              </td>)}
            </tr>;
          })}
        </tbody>
      </table>
    </div>
    {pager && <Pagination {...pager} />}
  </div>;
}

export function Pagination({ page, pages, total, onPage }) {
  const safePages = Math.max(1, Number(pages || 1));
  return <nav className="pager" aria-label="صفحه‌بندی">
    <span>{Number(total || 0).toLocaleString('fa')} مورد</span>
    <button className="btn sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>‹ قبلی</button>
    <span>صفحه {Number(page).toLocaleString('fa')} از {safePages.toLocaleString('fa')}</span>
    <button className="btn sm" disabled={page >= safePages} onClick={() => onPage(page + 1)}>بعدی ›</button>
  </nav>;
}

// ── Dialogs ───────────────────────────────────────────────────────
let _overlayLocks = 0;
let _overlayScroll = { x: 0, y: 0 };
let _overlayPaddingRight = '';
function lockOverlayScroll() {
  if (_overlayLocks === 0) {
    _overlayScroll = { x: window.scrollX, y: window.scrollY };
    _overlayPaddingRight = document.body.style.paddingRight;
    const scrollbarWidth = Math.max(0, window.innerWidth - document.documentElement.clientWidth);
    if (scrollbarWidth) document.body.style.paddingRight = `${scrollbarWidth}px`;
    document.body.classList.add('overlay-open');
  }
  _overlayLocks += 1;
}
function unlockOverlayScroll() {
  _overlayLocks = Math.max(0, _overlayLocks - 1);
  if (_overlayLocks === 0) {
    document.body.classList.remove('overlay-open');
    document.body.style.paddingRight = _overlayPaddingRight;
    window.scrollTo(_overlayScroll.x, _overlayScroll.y);
  }
}
function useDialog(onClose, active = true) {
  const ref = useRef(null);
  const previous = useRef(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    if (!active) return;
    previous.current = document.activeElement;
    lockOverlayScroll();
    const root = ref.current;
    const focusables = () => [...(root?.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])') || [])];
    const focusTimer = window.setTimeout(() => (focusables()[0] || root)?.focus({ preventScroll: true }), 0);
    const key = e => {
      if (e.key === 'Escape') { e.preventDefault(); closeRef.current(); }
      if (e.key === 'Tab') {
        const list = focusables(); if (!list.length) return;
        const first = list[0]; const last = list[list.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener('keydown', key);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener('keydown', key);
      unlockOverlayScroll();
      previous.current?.focus?.({ preventScroll: true });
    };
  }, [active]);
  return ref;
}

function DialogHeader({ title, onClose, titleId }) {
  return <div className="dialog-head"><b className="dialog-title" id={titleId}>{title}</b>
    <button className="btn sm dialog-close" onClick={onClose} aria-label="بستن پنجره">✕</button></div>;
}

export function Drawer({ title, onClose, children, wide }) {
  const id = useId();
  const [closing, setClosing] = useState(false);
  const closingRef = useRef(false);
  const requestClose = useCallback(() => {
    if (closingRef.current) return;
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) { onClose(); return; }
    closingRef.current = true;
    setClosing(true);
  }, [onClose]);
  const ref = useDialog(requestClose);
  const finishClose = event => {
    if (closing && event.target === event.currentTarget && event.animationName === 'drawerOut') onClose();
  };
  return <><div className={`scrim ${closing ? 'closing' : ''}`} onMouseDown={requestClose} aria-hidden="true" />
    <aside ref={ref} className={`drawer ${wide ? 'wide' : ''} ${closing ? 'closing' : ''}`.trim()}
      onAnimationEnd={finishClose} role="dialog" aria-modal="true" aria-labelledby={id} tabIndex={-1}>
      <DialogHeader title={title} onClose={requestClose} titleId={id} />{children}
    </aside></>;
}

export function Modal({ title, onClose, children, wide }) {
  const id = useId(); const ref = useDialog(onClose);
  return <><div className="scrim" onMouseDown={onClose} aria-hidden="true" />
    <div ref={ref} className={`modal ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true" aria-labelledby={id} tabIndex={-1}>
      <DialogHeader title={title} onClose={onClose} titleId={id} />{children}
    </div></>;
}

export function Confirm({ text, onYes, onNo, danger, children }) {
  return <Modal title="تأیید عملیات" onClose={onNo}>
    {children || <p className="state-description">{text}</p>}
    <div className="row" style={{ marginTop: 16 }}>
      <button className={`btn ${danger ? 'danger' : 'primary'}`} onClick={onYes}>تأیید</button>
      <button className="btn" onClick={onNo}>انصراف</button>
    </div>
  </Modal>;
}

export function DiffViewer({ before = {}, after = {} }) {
  const keys = [...new Set([...Object.keys(before || {}), ...Object.keys(after || {})])];
  if (!keys.length) return <Empty icon="Δ" text="تغییری ثبت نشده" />;
  return <div className="diff-tbl">
    <div className="diff-head"><span>فیلد</span><span>قبل</span><span>←</span><span>بعد</span></div>
    {keys.map(k => <div className="diff-row" key={k}>
      <span className="diff-f">{k}</span><span className="diff-v b">{displayValue(before?.[k], k)}</span>
      <span className="diff-arrow">←</span><span className="diff-v a">{displayValue(after?.[k], k)}</span>
    </div>)}
  </div>;
}
const displayValue = (v, key = '') => {
  if (v === undefined || v === null || v === '') return '—';
  if (typeof v === 'object') return JSON.stringify(v);
  const text = String(v);
  const temporalKey = /(?:^|_)(?:at|date|time)$|تاریخ|زمان|ثبت|پایان|انقضا|فعالیت/i.test(String(key));
  if (temporalKey && /^\d{4}-\d{2}-\d{2}(?:[T ]|$)/.test(text))
    return text.length === 10 ? <FaDate value={text} /> : <FaDateTime value={text} />;
  return text;
};

export function Timeline({ items = [], empty = 'رویدادی ثبت نشده' }) {
  if (!items.length) return <Empty icon="🕓" text={empty} />;
  return <div className="timeline">{items.map((it, i) => <div className="timeline-item" key={it.id || i}>
    <div className="timeline-rail"><span className="timeline-dot" /></div>
    {it.onClick ? <button type="button" className="timeline-content" onClick={it.onClick}><span>{it.title || it.action || 'رویداد'}</span>{it.description && <span className="muted">{it.description}</span>}
      <span className="timeline-meta">{it.actor ? `${it.actor} · ` : ''}<FaDateTime value={it.at || it.time} fallback="" /></span></button>
      : <div><div>{it.title || it.action || 'رویداد'}</div>{it.description && <div className="muted">{it.description}</div>}
        <div className="timeline-meta">{it.actor ? `${it.actor} · ` : ''}<FaDateTime value={it.at || it.time} fallback="" /></div></div>}
  </div>)}</div>;
}

export function ChartCard({ title, question, children, empty, actions }) {
  return <section className="panel panel-pad chart-card"><SectionHeader title={title} description={question} actions={actions} />
    {empty ? <div className="chart-empty">داده‌ی کافی برای این نمودار وجود ندارد</div> : children}
  </section>;
}

// ── Command Palette ───────────────────────────────────────────────
// جست‌وجوی فارسی با includes خام شکننده است: صفحه‌کلیدهای عربی «ي/ك» را
// می‌فرستند، کاربر گاهی ارقام لاتین تایپ می‌کند، و «‌» (نیم‌فاصله) در
// عبارت‌هایی مثل «سؤال‌ها» تطبیق را می‌شکند. همه به یک شکل نرمال می‌شوند.
const FA_FOLD = {
  '\u064a': '\u06cc', '\u0649': '\u06cc', '\u0643': '\u06a9',
  '\u0623': '\u0627', '\u0625': '\u0627', '\u0622': '\u0627', '\u0629': '\u0647',
  // همزه روی کرسی: کاربر «سوال/مسیول» تایپ می‌کند ولی متن «سؤال/مسئول» است.
  '\u0624': '\u0648', '\u0626': '\u06cc', '\u0621': '',
};
function normalizeFa(value) {
  return String(value ?? '')
    .replace(/[\u064a\u0649\u0643\u0623\u0625\u0622\u0629\u0624\u0626\u0621]/g, ch => FA_FOLD[ch])
    .replace(/[\u06f0-\u06f9]/g, ch => String(ch.charCodeAt(0) - 0x06f0))
    .replace(/[\u0660-\u0669]/g, ch => String(ch.charCodeAt(0) - 0x0660))
    .replace(/[\u200c\u200f\u200e]/g, '')
    .replace(/[\u064b-\u0652]/g, '')
    .toLowerCase()
    .trim();
}
export function Palette({ open, onClose, commands, search, go }) {
  const [q, setQ] = useState('');
  const [idx, setIdx] = useState(0);
  const [results, setResults] = useState(null);
  const [searching, setSearching] = useState(false);
  const inputRef = useRef(null);
  const debounce = useRef(null);
  const close = React.useCallback(() => onClose(false), [onClose]);
  const dialogRef = useDialog(close, open);
  useEffect(() => { if (open) { setQ(''); setIdx(0); setResults(null); window.setTimeout(() => inputRef.current?.focus(), 20); } }, [open]);
  useEffect(() => {
    const h = e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); onClose(!open); }
      if (e.key === 'Escape' && open) close();
    };
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h);
  }, [open, onClose]);
  useEffect(() => {
    if (!search) return;
    window.clearTimeout(debounce.current);
    if (q.trim().length < 2) { setResults(null); setSearching(false); return; }
    setSearching(true);
    debounce.current = window.setTimeout(async () => {
      try { setResults(await search(q.trim())); } catch { setResults([]); }
      setSearching(false);
    }, 280);
    return () => window.clearTimeout(debounce.current);
  }, [q, search]);
  if (!open) return null;
  const nq = normalizeFa(q);
  const local = commands.filter(c => !nq
    || normalizeFa(c.label).includes(nq) || normalizeFa(c.hint || '').includes(nq));
  const list = q.trim().length >= 2 && results ? results : local;
  const runAt = i => {
    const it = list[i]; if (!it) return;
    if (it.run) it.run(); else if (it.go && go) go(it.go);
    close();
  };
  return <><div className="scrim" onMouseDown={close} aria-hidden="true" />
    <div ref={dialogRef} className="palette" role="dialog" aria-modal="true" aria-label="جست‌وجو و فرمان" tabIndex={-1}>
      <input ref={inputRef} placeholder="جست‌وجو در کاربران، محتوا، سؤال، آزمون، تیکت، پرداخت و لاگ…"
        value={q} onChange={e => { setQ(e.target.value); setIdx(0); }}
        onKeyDown={e => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setIdx(i => Math.min(i + 1, Math.max(0, list.length - 1))); }
          if (e.key === 'ArrowUp') { e.preventDefault(); setIdx(i => Math.max(i - 1, 0)); }
          if (e.key === 'Enter') runAt(idx);
        }} />
      <div className="palette-results">
        {searching && <Loading rows={3} />}
        {!searching && !list.length && <Empty icon="🔎" text={q ? `نتیجه‌ای برای «${q}» نیست` : 'فرمانی در دسترس نیست'} />}
        {!searching && list.map((it, i) => <React.Fragment key={`${it.group || 'local'}-${it.id || it.label}-${i}`}>
          {it.group && (i === 0 || list[i - 1]?.group !== it.group) && <div className="pal-sec">{it.group}</div>}
          <button type="button" className={`opt ${i === idx ? 'on' : ''}`} onMouseEnter={() => setIdx(i)} onClick={() => runAt(i)}>
            <span>{it.icon}</span><span className="text-truncate">{it.label}</span><span className="spacer" /><span className="muted">{it.hint}</span>
          </button>
        </React.Fragment>)}
      </div>
    </div></>;
}

export function Stat({ icon, label, value, tint = 'var(--acc)', delta, hint }) {
  return <div className="panel stat">
    <div className="ic" style={{ background: `color-mix(in srgb, ${tint} 12%, transparent)`, border: `1px solid color-mix(in srgb, ${tint} 28%, transparent)` }}>{icon}</div>
    <div className="text-truncate"><div className="row stat-value-row"><div className="v">{value ?? '—'}</div>
      {delta != null && <span className={`trend ${delta >= 0 ? 'up' : 'down'}`}>{delta >= 0 ? '▲' : '▼'} {Number(Math.abs(delta)).toLocaleString('fa')}٪</span>}
    </div><div className="l">{label}</div>{hint && <div className="l stat-hint">{hint}</div>}</div>
  </div>;
}

/* ══════════════════════════════════════════════════════════════════
   §DW1 — primitiveهای مشترکِ چیدمان و سنجه
   ══════════════════════════════════════════════════════════════════
   ممیزیِ موجِ ۱۱: ۵۱٪ کلاس‌های CSS مخصوصِ یک صفحه بودند. علت نبودِ
   ابزارِ مشترک بود، نه سلیقه. این‌ها همان ابزارِ غایب‌اند.

   `Stat` قدیمی حذف نشد — هنوز در چند صفحه استفاده می‌شود و شکستنش
   بی‌دلیل است. `KpiCard` جانشینِ غنی‌ترِ آن است و مهاجرت تدریجی
   انجام می‌شود (موج‌های بعد).
   ────────────────────────────────────────────────────────────────── */

/** نمودارِ خطیِ کوچک — بدونِ وابستگیِ بیرونی، فقط SVG. */
export function Sparkline({ data, tone = '', height = 28, area = true }) {
  const pts = (data || []).map(Number).filter(n => Number.isFinite(n));
  if (pts.length < 2) return null;
  const max = Math.max(...pts), min = Math.min(...pts);
  const span = max - min || 1;
  const W = 100, H = height;
  const step = W / (pts.length - 1);
  const xy = pts.map((v, i) => [i * step, H - ((v - min) / span) * (H - 6) - 3]);
  const line = xy.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(2)},${y.toFixed(2)}`).join(' ');
  const fill = `${line} L${W},${H} L0,${H} Z`;
  return (
    <svg className={`sparkline ${tone ? `is-${tone}` : ''}`} viewBox={`0 0 ${W} ${H}`}
         preserveAspectRatio="none" aria-hidden="true" focusable="false">
      {area && <path className="spark-area" d={fill} />}
      <path className="spark-line" d={line} />
    </svg>
  );
}

/**
 * کارتِ سنجه. `tone` معنایی است (ok/warn/bad/acc) نه رنگِ خام، تا یک
 * وضعیت در همهٔ صفحات یک ظاهر داشته باشد.
 */
export function KpiCard({ icon, label, value, tone = '', delta, hint,
                          trend, onClick, enter }) {
  const clickable = typeof onClick === 'function';
  const showDelta = delta != null && Number.isFinite(Number(delta));
  return (
    <div
      className={`panel kpi ${tone ? `is-${tone}` : ''} ${enter ? `dw-enter ${enter}` : ''}`}
      onClick={onClick}
      onKeyDown={clickable ? e => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(e); }
      } : undefined}
      role={clickable ? 'button' : undefined}
      tabIndex={clickable ? 0 : undefined}
      style={clickable ? { cursor: 'pointer' } : undefined}
    >
      <div className="kpi-head">
        {icon && <span className="kpi-ic" aria-hidden="true">{icon}</span>}
        <span className="kpi-label" title={label}>{label}</span>
      </div>
      {/* مقدارِ متنیِ بلند یک پله کوچک‌تر می‌شود تا وزنِ بصریِ ردیف
          یکسان بماند — از بازبینیِ چشمیِ موجِ ۲. */}
      <div className={`kpi-value${
        typeof value === 'string' && value.length > 6 && !/^[\d\u06F0-\u06F9٬,.\s]+$/.test(value)
          ? ' is-text' : ''}`}>{value}</div>
      {(showDelta || hint) && (
        <div className="kpi-foot">
          {showDelta && (
            <span className={`trend ${Number(delta) >= 0 ? 'up' : 'down'}`}>
              {Number(delta) >= 0 ? '▲' : '▼'}{' '}
              {Math.abs(Number(delta)).toLocaleString('fa')}٪
            </span>
          )}
          {hint && <span>{hint}</span>}
        </div>
      )}
      {trend?.length > 1 && <Sparkline data={trend} tone={tone} />}
    </div>
  );
}

/** ردیفِ KPI با چیدمانِ واکنش‌گرای یکسان در همهٔ صفحات. */
export function KpiGrid({ children, className = '' }) {
  return <div className={`kpi-grid ${className}`}>{children}</div>;
}

/**
 * نوارِ ابزار. `FilterBar` فقط در ۵ صفحه بود و بقیه ردیفِ دستی
 * می‌ساختند؛ این نسخه محلِ اکشن‌های انتهایی را هم استاندارد می‌کند.
 */
export function Toolbar({ children, end, className = '' }) {
  return (
    <div className={`tbar ${className}`}>
      {children}
      {end && <div className="tbar-end">{end}</div>}
    </div>
  );
}

/** سربرگِ بخش — عنوان/توضیح/اکشن با فاصله‌گذاریِ یکسان. */
export function Section({ title, description, actions, children, className = '' }) {
  return (
    <div className={className}>
      {(title || actions) && (
        <div className="sec">
          <div className="sec-main">
            {title && <div className="sec-title">{title}</div>}
            {description && <div className="sec-desc">{description}</div>}
          </div>
          {actions && <div className="sec-actions">{actions}</div>}
        </div>
      )}
      {children}
    </div>
  );
}

/**
 * §DW2 — ردیفِ «برچسب: مقدار».
 *
 * RingStreet یک `Stat` محلیِ کاملاً متفاوت تعریف کرده بود (۴۶ مورد
 * مصرف) که با `Stat` مشترک هم‌نام ولی هم‌معنا نبود: آن یکی کارتِ سنجه
 * است، این یکی ردیفِ ساده. هم‌نامیِ دو مفهومِ متفاوت بدترین شکلِ
 * duplication است، چون خواننده فکر می‌کند یکی‌اند.
 *
 * حالا مفهوم نامِ درستِ خودش را دارد و فاصله/رنگش از توکن می‌آید.
 */
export function KeyValue({ label, value, mono }) {
  return (
    <div className="kv-row">
      <span className="kv-k">{label}</span>
      <b className={`kv-v${mono ? ' ltr' : ''}`}>{value ?? '—'}</b>
    </div>
  );
}

/** شبکهٔ ردیف‌های برچسب/مقدار با چیدمانِ واکنش‌گرا. */
export function KeyValueGrid({ children, className = '' }) {
  return <div className={`kv-grid ${className}`}>{children}</div>;
}
