import React, { useState } from 'react';
import { Modal } from './ui.jsx';

const FIELDS = [
  ['status', 'وضعیت'], ['intake', 'ورودی'], ['group', 'گروه'], ['role', 'نقش'],
  ['last_active', 'آخرین فعالیت (ISO)'], ['inactive_days', 'عدم فعالیت (روز)'],
  ['accuracy', 'دقت پاسخ'], ['total_answers', 'تعداد پاسخ'], ['exam_count', 'تعداد آزمون'],
  ['streak', 'استریک'], ['ai_usage', 'مصرف هوشیار'],
  ['subscription_days_left', 'روز باقی‌مانده اشتراک'], ['open_tickets', 'تیکت باز'],
  ['name', 'نام'], ['nickname', 'لقب'], ['username', 'یوزرنیم'], ['student_id', 'شماره دانشجویی'],
];
const OPS = [['eq', '='], ['ne', '≠'], ['gte', '≥'], ['lte', '≤'], ['gt', '>'], ['lt', '<'], ['contains', 'شامل']];
const leaf = () => ({ field: 'status', op: 'eq', value: 'active' });
const emptyTree = () => ({ logic: 'and', conditions: [leaf()] });
const PRESETS = [
  ['expiring', 'اشتراک رو به پایان', { logic: 'and', conditions: [{ field: 'status', op: 'eq', value: 'active' }, { field: 'subscription_days_left', op: 'lte', value: 7 }] }],
  ['inactive', 'بدون فعالیت ۱۴ روز', { logic: 'and', conditions: [{ field: 'inactive_days', op: 'gte', value: 14 }] }],
  ['ticket', 'فعال با تیکت باز', { logic: 'and', conditions: [{ field: 'status', op: 'eq', value: 'active' }, { field: 'open_tickets', op: 'eq', value: true }] }],
];

export default function SmartQueryBuilder({ value, onApply, onClose }) {
  const [tree, setTree] = useState(() => value?.conditions?.length ? structuredClone(value) : emptyTree());
  const updateRoot = patch => setTree(current => ({ ...current, ...patch }));
  const updateCondition = (index, next) => setTree(current => ({ ...current, conditions: current.conditions.map((item, i) => i === index ? next : item) }));
  const removeCondition = index => setTree(current => ({ ...current, conditions: current.conditions.filter((_, i) => i !== index) }));
  const addGroup = () => updateRoot({ conditions: [...tree.conditions, { logic: 'and', conditions: [leaf()] }] });
  return <Modal wide title="🧠 سازنده فیلتر هوشمند" onClose={onClose}>
    <div className="row smart-presets"><span className="muted">Recipe:</span>{PRESETS.map(([key, label, preset]) =>
      <button key={key} className="btn sm" onClick={() => setTree(structuredClone(preset))}>{label}</button>)}</div>
    <GroupEditor group={tree} root onChange={next => setTree(next)} updateItem={updateCondition} removeItem={removeCondition} />
    <div className="row" style={{ marginTop: 12 }}>
      <button className="btn sm" onClick={() => updateRoot({ conditions: [...tree.conditions, leaf()] })}>＋ شرط</button>
      <button className="btn sm" onClick={addGroup}>＋ گروه تو در تو</button><span className="spacer" />
      <button className="btn" onClick={() => onApply(null)}>پاک‌کردن فیلتر</button>
      <button className="btn primary" disabled={!tree.conditions.length} onClick={() => onApply(tree)}>اعمال فیلتر</button>
    </div>
  </Modal>;
}

function GroupEditor({ group, root = false, onChange }) {
  const update = (index, next) => onChange({ ...group, conditions: group.conditions.map((item, i) => i === index ? next : item) });
  const remove = index => onChange({ ...group, conditions: group.conditions.filter((_, i) => i !== index) });
  return <fieldset className={`smart-group ${root ? 'root' : ''}`}>
    <legend>{root ? 'منطق اصلی' : 'گروه شرط'}</legend>
    <div className="row"><select className="inp" value={group.logic} onChange={e => onChange({ ...group, logic: e.target.value })} aria-label="منطق گروه">
      <option value="and">همه شروط (AND)</option><option value="or">حداقل یکی (OR)</option>
    </select></div>
    <div className="grid smart-condition-list">
      {group.conditions.map((item, index) => item.conditions
        ? <div className="smart-nested" key={index}><GroupEditor group={item} onChange={next => update(index, next)} /><button className="btn sm danger" onClick={() => remove(index)}>حذف گروه</button></div>
        : <Condition key={index} value={item} onChange={next => update(index, next)} onRemove={() => remove(index)} />)}
    </div>
    {!root && <button className="btn sm" onClick={() => onChange({ ...group, conditions: [...group.conditions, leaf()] })}>＋ شرط داخل گروه</button>}
  </fieldset>;
}

function Condition({ value, onChange, onRemove }) {
  const special = value.field === 'status' ? [['active', 'فعال'], ['pending', 'در انتظار'], ['suspended', 'تعلیق']]
    : value.field === 'open_tickets' ? [['true', 'دارد'], ['false', 'ندارد']] : null;
  return <div className="row smart-condition">
    <select className="inp" value={value.field} onChange={e => onChange({ ...value, field: e.target.value, op: 'eq', value: e.target.value === 'status' ? 'active' : '' })} aria-label="فیلد شرط">
      {FIELDS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
    </select>
    <select className="inp" value={value.op} onChange={e => onChange({ ...value, op: e.target.value })} aria-label="عملگر شرط">
      {OPS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
    </select>
    {special ? <select className="inp" value={String(value.value)} onChange={e => onChange({ ...value, value: e.target.value === 'true' ? true : e.target.value === 'false' ? false : e.target.value })} aria-label="مقدار شرط">
      {special.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
    </select> : <input className="inp" value={value.value ?? ''} onChange={e => onChange({ ...value, value: e.target.value })} placeholder="مقدار…" aria-label="مقدار شرط" />}
    <button className="btn sm danger" onClick={onRemove} aria-label="حذف شرط">✕</button>
  </div>;
}
