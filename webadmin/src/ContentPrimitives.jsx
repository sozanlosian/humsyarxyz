import React, { useEffect, useState } from 'react';
import { B, Empty, ErrorState, Loading, ScopeBadge } from './ui.jsx';
export { ScopeBadge };

export function useDebouncedValue(value, delay = 180) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

export function useContentDensity() {
  const [density, setDensityState] = useState(() => {
    try { return localStorage.getItem('wa_content_density') || 'compact'; } catch { return 'compact'; }
  });
  const setDensity = value => {
    const next = value === 'comfortable' ? 'comfortable' : 'compact';
    try { localStorage.setItem('wa_content_density', next); } catch {}
    setDensityState(next);
  };
  return [density, setDensity];
}

export function ContentDensityToggle({ value, onChange }) {
  return <div className="content-density" role="group" aria-label="چگالی فهرست محتوا"><button type="button" className={`btn sm ${value === 'compact' ? 'primary' : ''}`} aria-pressed={value === 'compact'} onClick={() => onChange('compact')}>فشرده</button><button type="button" className={`btn sm ${value === 'comfortable' ? 'primary' : ''}`} aria-pressed={value === 'comfortable'} onClick={() => onChange('comfortable')}>راحت</button></div>;
}

export function ContentShell({ children, density = 'compact', className = '' }) {
  return <section className={`content-shell density-${density} ${className}`.trim()}>{children}</section>;
}

export function ContentToolbar({ children, className = '' }) {
  return <div className={`content-toolbar ${className}`.trim()}>{children}</div>;
}

export function ContentWorkspace({ children, columns = 3, className = '' }) {
  return <div className={`content-workspace cols-${columns} ${className}`.trim()}>{children}</div>;
}

export function ContentPane({ icon, title, subtitle, count, actions, inspector = false, children, className = '' }) {
  return <section className={`content-pane ${inspector ? 'is-inspector' : ''} ${className}`.trim()}>
    <header className="content-pane-header">
      <span className="content-pane-title">{icon && <span aria-hidden="true">{icon}</span>} {title}</span>
      {subtitle && <span className="content-pane-subtitle" title={typeof subtitle === 'string' ? subtitle : undefined}>{subtitle}</span>}
      {count !== undefined && count !== null && <ContentCountBadge>{count}</ContentCountBadge>}
      <span className="spacer" />
      {actions && <ContentActionGroup>{actions}</ContentActionGroup>}
    </header>
    <div className="content-pane-body">{children}</div>
  </section>;
}

export function ContentSection({ icon, title, count, actions, open = true, onToggle, children, className = '' }) {
  return <section className={`content-section ${className}`.trim()}>
    <header className="content-section-header">
      {onToggle ? <button type="button" className="content-section-toggle" aria-expanded={open} onClick={onToggle}>
        <span aria-hidden="true">{icon}</span><b>{title}</b><ContentCountBadge>{count}</ContentCountBadge><span className="spacer" /><span aria-hidden="true">{open ? '▾' : '◂'}</span>
      </button> : <><span aria-hidden="true">{icon}</span><b>{title}</b><ContentCountBadge>{count}</ContentCountBadge><span className="spacer" /></>}
      {actions && <ContentActionGroup onClick={e => e.stopPropagation()}>{actions}</ContentActionGroup>}
    </header>
    {open && <div className="content-section-body">{children}</div>}
  </section>;
}

export function ContentItem({ icon, title, meta, selection, selected = false, active = false,
  readonly = false, scope, scopeLabel, metrics, actions, onClick, level = 0,
  as = 'div', className = '', titleDir }) {
  const Tag = as;
  const keyboard = onClick ? {
    role: 'button', tabIndex: 0, 'aria-pressed': active,
    onKeyDown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(e); } },
  } : {};
  return <Tag className={`content-item ${active ? 'is-active' : ''} ${selected ? 'is-selected' : ''} ${readonly ? 'is-readonly' : ''} ${className}`.trim()}
    style={{ '--content-level': level }} onClick={onClick} {...keyboard}>
    <div className="content-item-main">
      {selection && <span className="content-item-select" onClick={e => e.stopPropagation()}>{selection}</span>}
      {icon && <span className="content-item-icon" aria-hidden="true">{icon}</span>}
      <div className="content-item-copy">
        <div className="content-item-title" dir={titleDir}>{title || '—'}</div>
        {meta && <div className="content-item-meta">{meta}</div>}
      </div>
      <div className="content-item-badges">
        {readonly && <B>🔒 فقط‌خواندنی</B>}
        {scope !== undefined && <ScopeBadge scope={scope} label={scopeLabel} />}
      </div>
    </div>
    {(metrics || actions) && <div className="content-item-foot">
      <div className="content-item-metrics">{metrics}</div>
      <span className="spacer" />
      {actions && <ContentActionGroup onClick={e => e.stopPropagation()}>{actions}</ContentActionGroup>}
    </div>}
  </Tag>;
}

export function ContentActionGroup({ children, onClick, className = '' }) {
  return <div className={`content-actions ${className}`.trim()} onClick={onClick}>{children}</div>;
}

export function ContentIconButton({ icon, label, kind = 'secondary', disabled, onClick, className = '' }) {
  return <button type="button" className={`content-icon-btn ${kind} ${className}`.trim()}
    disabled={disabled} onClick={onClick} title={label} aria-label={label}>{icon}</button>;
}

export function ContentMoreActions({ label = 'اقدامات بیشتر', children }) {
  return <details className="content-more" onKeyDown={event => {
    if (event.key === 'Escape') { event.currentTarget.open = false; event.currentTarget.querySelector('summary')?.focus(); }
  }}>
    <summary className="content-icon-btn secondary" title={label} aria-label={label}>•••</summary>
    <div className="content-more-menu" onClick={event => { event.currentTarget.closest('details').open = false; }}>{children}</div>
  </details>;
}

export function ContentReorderControls({ canUp = true, canDown = true, onUp, onDown, noun = 'مورد' }) {
  return <div className="content-reorder" role="group" aria-label={`تغییر ترتیب ${noun}`}>
    <ContentIconButton icon="↑" label={`انتقال ${noun} به بالا`} disabled={!canUp} onClick={onUp} />
    <ContentIconButton icon="↓" label={`انتقال ${noun} به پایین`} disabled={!canDown} onClick={onDown} />
  </div>;
}

export function ContentCountBadge({ children, kind = '' }) {
  return <B kind={kind} className="content-count-badge">{children}</B>;
}

export function ContentMetric({ icon, value, label, kind = '' }) {
  return <B kind={kind} className="content-metric">{icon && <span aria-hidden="true">{icon}</span>}{value} {label}</B>;
}

const FILE_META = {
  pdf: ['PDF', '📕', 'pdf'], ppt: ['PPT', '📽', 'ppt'], pptx: ['PPT', '📽', 'ppt'],
  video: ['VIDEO', '🎬', 'video'], audio: ['AUDIO', '🎵', 'audio'], voice: ['VOICE', '🎙', 'voice'],
  note: ['NOTE', '📝', 'note'], test: ['TEST', '🧪', 'test'], document: ['DOC', '📎', 'document'],
  doc: ['DOC', '📎', 'document'], docx: ['DOC', '📎', 'document'],
  image: ['IMAGE', '🖼', 'image'], photo: ['IMAGE', '🖼', 'image'], jpg: ['IMAGE', '🖼', 'image'], jpeg: ['IMAGE', '🖼', 'image'], png: ['IMAGE', '🖼', 'image'],
  mp3: ['AUDIO', '🎵', 'audio'], wav: ['AUDIO', '🎵', 'audio'], mp4: ['VIDEO', '🎬', 'video'], mov: ['VIDEO', '🎬', 'video'],
};
export function FileTypeBadge({ type, fileName = '', withIcon = true, compact = false }) {
  const extension = String(fileName).split('.').pop().toLowerCase();
  const requested = String(type || '').toLowerCase();
  const key = FILE_META[requested] ? requested : (FILE_META[extension] ? extension : 'document');
  const [label, icon, variant] = FILE_META[key] || [key.toUpperCase(), '📎', 'document'];
  return <B className={`file-type-badge ${variant} ${compact ? 'compact' : ''}`.trim()}>{withIcon && <span aria-hidden="true">{icon}</span>}{label}</B>;
}
export function fileTypeIcon(type) { return (FILE_META[String(type || 'document').toLowerCase()] || ['','📎'])[1]; }

export function ContentBulkBar({ count, actions, children, onClear }) {
  if (!count) return null;
  return <div className="content-bulk-bar"><ContentCountBadge kind="acc">{Number(count).toLocaleString('fa')} انتخاب</ContentCountBadge>{actions || children}<span className="spacer" />{onClear && <button className="btn sm" onClick={onClear}>لغو انتخاب</button>}</div>;
}

export function ContentKV({ label, value, children, strong = false }) {
  const content = value !== undefined ? value : children;
  return <div className="content-kv"><span className="muted">{label}</span>{strong ? <b>{content}</b> : <span>{content}</span>}</div>;
}

export function ContentStats({ items }) {
  return <div className="content-stats">{items.map(item => <div className="content-stat" key={item.label}><b>{item.value}</b><span>{item.label}</span></div>)}</div>;
}

export function ContentEmptyState({ icon = '📭', title, description, action }) {
  return <Empty icon={icon} text={title}>{description && <div className="muted">{description}</div>}{action}</Empty>;
}

export function ContentErrorState({ title = 'بارگذاری محتوا ناموفق بود', error, onRetry, compact = false }) {
  return <div className={compact ? 'content-state-compact' : ''}><ErrorState title={title} error={error} onRetry={onRetry} /></div>;
}

export function ContentSkeleton({ panes = 3, rows = 7 }) {
  if (panes === 1) return <div className="content-skeleton-inline"><Loading rows={rows} variant="tree" label="در حال بارگذاری محتوا" /></div>;
  return <div className={`content-workspace cols-${panes}`} aria-label="در حال بارگذاری فضای محتوا">
    {Array.from({ length: panes }, (_, i) => <section className="content-pane" key={i}><header className="content-pane-header"><span className="skeleton-line" /></header><div className="content-pane-body"><Loading rows={i === panes - 1 ? Math.min(rows, 4) : rows} variant="tree" /></div></section>)}
  </div>;
}

export function ContentBreadcrumb({ items = [] }) {
  return <nav className="content-breadcrumb" aria-label="مسیر محتوا">{items.map((item, i) => <React.Fragment key={`${item.label}-${i}`}>{i > 0 && <span aria-hidden="true">‹</span>}{item.onClick ? <button onClick={item.onClick}>{item.label}</button> : <span aria-current={i === items.length - 1 ? 'page' : undefined}>{item.label}</span>}</React.Fragment>)}</nav>;
}
