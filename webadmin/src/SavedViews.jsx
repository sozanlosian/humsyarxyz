import React, { useEffect, useState } from 'react';
import { api, errText } from './api.js';
import { B, Modal, Confirm, toast } from './ui.jsx';
import { formatFaDateTime } from './time.js';

/** Generic per-admin saved views. The backend owns identity/scope; pages own filters. */
export default function SavedViews({ scope, filters, columns = [], sort = {}, density = '', onApply, label = 'نماهای ذخیره‌شده' }) {
  const [items, setItems] = useState(null);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [shared, setShared] = useState(false);
  const [editing, setEditing] = useState(null);
  const [replaceState, setReplaceState] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);
  const load = async () => {
    try { setItems((await api.savedFilters(scope)).filters || []); }
    catch { setItems([]); }
  };
  useEffect(() => { load(); }, [scope]);
  const save = async () => {
    if (!name.trim()) return;
    try {
      if (editing) {
        const body = { name: name.trim(), shared };
        if (replaceState) Object.assign(body, { filters, columns, sort, density });
        await api.updateFilter(editing.id, body);
        toast('نمای ذخیره‌شده ویرایش شد');
      } else {
        await api.saveFilter({ name: name.trim(), scope, filters, columns, sort, density, shared });
        toast(shared ? 'نمای اشتراکی ذخیره شد' : 'نمای شخصی ذخیره شد');
      }
      setName(''); setShared(false); setEditing(null); setReplaceState(false); setOpen(false); load();
    } catch (e) { toast(errText(e), 'err'); }
  };
  const remove = async id => {
    try { await api.delFilter(id); load(); }
    catch (e) { toast(errText(e), 'err'); }
  };
  return <>
    <div className="row saved-views" style={{ marginBottom: 10, gap: 6 }}>
      <span className="muted">⏱ {label}:</span>
      {(items || []).map(item => <span className="chip" key={item.id} title={`${item.shared ? `اشتراکی · سازنده: ${item.owner_name || item.owner}` : 'شخصی'} · به‌روزرسانی: ${formatFaDateTime(item.updated_at)} · آخرین استفاده: ${formatFaDateTime(item.last_opened_at)}`}>
        <button type="button" className="chip-link" onClick={() => { api.touchFilter(item.id).catch(() => {}); onApply(item.filters || {}, item); }}>{item.shared ? '👥 ' : '👤 '}{item.name}</button>
        {item.editable !== false && <button className="chip-x" aria-label={`ویرایش نمای ${item.name}`} onClick={() => {
          setEditing(item); setName(item.name); setShared(!!item.shared); setReplaceState(false); setOpen(true);
        }}>✎</button>}
        {item.editable !== false && <button className="chip-x" aria-label={`حذف نمای ${item.name}`} onClick={() => setPendingDelete(item)}>✕</button>}
      </span>)}
      {items && !items.length && <B>هنوز نمایی نیست</B>}
      <button className="btn sm" onClick={() => { setEditing(null); setName(''); setShared(false); setReplaceState(false); setOpen(true); }}>💾 ذخیره نمای فعلی</button>
    </div>
    {open && <Modal title={editing ? 'ویرایش نمای ذخیره‌شده' : 'ذخیره نمای فعلی'} onClose={() => { setOpen(false); setEditing(null); }}>
      <input className="inp" style={{ width: '100%' }} placeholder="نام نما…" value={name} onChange={e => setName(e.target.value)} />
      <label className="row" style={{ marginTop: 10 }}><input type="checkbox" checked={shared} onChange={e => setShared(e.target.checked)} />
        <span>اشتراک با مدیرانی که به همین بخش دسترسی دارند</span></label>
      {editing && <label className="row" style={{ marginTop: 10 }}><input type="checkbox" checked={replaceState} onChange={e => setReplaceState(e.target.checked)} />
        <span>جایگزینی فیلتر، ترتیب و ستون‌ها با وضعیت فعلی صفحه</span></label>}
      <div className="muted" style={{ marginTop: 6 }}>فیلتر، ترتیب و ستون‌های قابل‌ارسال همراه نما ذخیره می‌شوند.</div>
      <div className="row" style={{ marginTop: 12 }}><button className="btn primary" disabled={!name.trim()} onClick={save}>{editing ? 'ذخیره تغییرات' : 'ذخیره'}</button>
        <button className="btn" onClick={() => { setOpen(false); setEditing(null); }}>انصراف</button></div>
    </Modal>}
    {pendingDelete && <Confirm danger text={`نمای «${pendingDelete.name}» برای همیشه حذف شود؟`} onNo={() => setPendingDelete(null)} onYes={() => {
      const id = pendingDelete.id; setPendingDelete(null); remove(id);
    }} />}
  </>;
}
