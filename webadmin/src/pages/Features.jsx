import React, { useEffect, useState } from 'react';
import { api, errText } from '../api.js';
import { B, DataTable, Modal, Confirm, Switch, PageHeader, toast, Empty, Loading } from '../ui.jsx';
import { formatFaDate } from '../time.js';

// 🌊 W7 — کنترل مرکزی دسترسی فیچرها (FREE NOW, PAY LATER).
// هر سطر = یک سوییچ monetization: تغییر access از FREE به SUBSCRIPTION
// بدون deploy روی بات/مینی‌اپ/API اعمال می‌شود (بک‌اند مرجع نهایی است).
const ACCESS_FA = {
  free: 'رایگان', subscription: 'اشتراکی', admin_only: 'فقط مالک', disabled: 'خاموش',
};
const ACCESS_KIND = { free: 'ok', subscription: 'warn', admin_only: 'acc', disabled: 'bad' };
const KIND_FA = { none: 'نامحدود', daily: 'روزانه', monthly: 'ماهانه' };

export default function Features({ me }) {
  const [items, setItems] = useState(null);
  const [err, setErr] = useState('');
  const [edit, setEdit] = useState(null);
  const [rollback, setRollback] = useState(null);
  const [busy, setBusy] = useState(false);

  const can = !!me?.is_owner || (me?.perms || []).includes('subscription.manage');
  const load = async () => {
    setErr('');
    try { setItems((await api.featuresList()).items || []); }
    catch (e) { setErr(errText(e)); }
  };
  useEffect(() => { if (can) load(); }, [can]);
  if (!can) return <PageHeader title="🎚 دسترسی فیچرها" sub="نیازمند مجوز «مدیریت اشتراک‌ها» (subscription.manage)" />;
  if (err) return <div className="panel panel-pad">❌ {err}</div>;
  if (!items) return <Loading />;

  const doRollback = async () => {
    const k = rollback; setRollback(null); setBusy(true);
    try { await api.featureRollback(k); toast('به پالیسی قبلی برگشت ✅'); load(); }
    catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };

  return <>
    <PageHeader title="🎚 دسترسی فیچرها" sub="سوییچ monetization هر قابلیت — تغییر بدون نیاز به deploy" />
    <div className="panel panel-pad">
      <DataTable rowKey="key" columns={[
        { k: 'label', label: 'فیچر', render: r => <div><b>{r.label}</b><div className="muted">{r.desc}</div></div> },
        { k: 'enabled', label: 'وضعیت', render: r => <B kind={r.policy.enabled ? 'ok' : 'bad'}>{r.policy.enabled ? '🟢 روشن' : '🔴 خاموش'}</B> },
        { k: 'access', label: 'دسترسی', render: r => <B kind={ACCESS_KIND[r.policy.access] || ''}>{ACCESS_FA[r.policy.access] || r.policy.access}</B> },
        { k: 'trial', label: 'تریال', render: r => <span>{r.policy.trial_allowed ? '✓' : '✗'}</span> },
        { k: 'quota', label: 'سهمیه', render: r => quotaText(r.policy.quota) },
        { k: 'sched', label: 'زمان‌بندی', render: r => r.policy.pending_access ? <B kind="acc">{ACCESS_FA[r.policy.pending_access]} از {formatFaDate(r.policy.effective_from)}</B> : <span className="muted">—</span> },
        { k: 'enforced', label: 'اعمال', render: r => r.enforced ? <span>🛡</span> : <span className="muted" title="سوییچ فعال؛ نقطه‌ی اعمال بعدی">policy</span> },
        { k: 'act', label: '', render: r => <div className="row" style={{ gap: 5 }}>
          <button className="btn sm" disabled={busy} onClick={() => setEdit(r)}>✏️ ویرایش</button>
          {r.has_prev && <button className="btn sm" disabled={busy} onClick={() => setRollback(r.key)} title={`بازگشت به نسخه‌ی ${r.prev_by || ''}`}>↩️</button>}
        </div> },
      ]} rows={items} />
      {!items.length && <Empty text="فیچری ثبت نشده" />}
      <div className="muted" style={{ marginTop: 10 }}>هر تغییر audit می‌شود و نسخه‌ی قبلی برای rollback نگه داشته می‌شود. kill-switch (خاموش) همه — حتی مالک — را می‌بندد.</div>
    </div>
    {edit && <FeatureModal item={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); load(); }} />}
    {rollback && <Confirm text={`بازگردانی «${rollback}» به پالیسی قبلی؟`} onYes={doRollback} onNo={() => setRollback(null)} />}
  </>;
}

function quotaText(q) {
  q = q || {};
  if (!q.kind || q.kind === 'none' || !(Number(q.limit) > 0)) return <span className="muted">نامحدود</span>;
  return <span>{Number(q.limit).toLocaleString('fa-IR')}/{KIND_FA[q.kind]}</span>;
}

function FeatureModal({ item, onClose, onDone }) {
  const p = item.policy || {};
  const q = p.quota || {};
  const [f, setF] = useState({
    enabled: !!p.enabled, access: p.access || 'free', trial_allowed: p.trial_allowed !== false,
    quota_kind: q.kind || 'none', quota_limit: q.limit || 0, note: p.note || '',
    pending_access: p.pending_access || '', effective_from: (p.effective_from || '').slice(0, 16),
  });
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await api.featureUpdate(item.key, {
        enabled: f.enabled, access: f.access, trial_allowed: f.trial_allowed,
        quota_kind: f.quota_kind, quota_limit: Number(f.quota_limit) || 0,
        note: f.note, pending_access: f.pending_access || '',
        effective_from: f.pending_access ? (f.effective_from || '') : '',
      });
      toast('پالیسی ذخیره شد ✅'); onDone();
    } catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  return <Modal title={`🎚 ${item.label}`} onClose={onClose}>
    <div className="grid" style={{ gap: 10 }}>
      <div className="row"><Switch on={f.enabled} onChange={v => setF({ ...f, enabled: v })} />
        <div><b>روشن (kill-switch)</b><div className="muted">خاموش = بسته برای همه حتی مالک</div></div></div>
      <label className="fld"><span>حالت دسترسی</span>
        <select className="inp" value={f.access} onChange={e => setF({ ...f, access: e.target.value })}>
          {Object.keys(ACCESS_FA).map(k => <option key={k} value={k}>{ACCESS_FA[k]}</option>)}
        </select></label>
      <div className="row"><Switch on={f.trial_allowed} onChange={v => setF({ ...f, trial_allowed: v })} />
        <div><b>تریال قبول است</b><div className="muted">فقط وقتی دسترسی = اشتراکی</div></div></div>
      <div className="row">
        <label className="fld" style={{ flex: 1 }}><span>سهمیه</span>
          <select className="inp" value={f.quota_kind} onChange={e => setF({ ...f, quota_kind: e.target.value })}>
            {Object.keys(KIND_FA).map(k => <option key={k} value={k}>{KIND_FA[k]}</option>)}
          </select></label>
        <label className="fld" style={{ flex: 1 }}><span>سقف (۰=نامحدود)</span>
          <input className="inp" type="number" min="0" max="1000000" value={f.quota_limit}
            onChange={e => setF({ ...f, quota_limit: e.target.value })} /></label>
      </div>
      <div className="row">
        <label className="fld" style={{ flex: 1 }}><span>تغییر زمان‌بندی‌شده</span>
          <select className="inp" value={f.pending_access} onChange={e => setF({ ...f, pending_access: e.target.value })}>
            <option value="">— بدون زمان‌بندی —</option>
            {Object.keys(ACCESS_FA).map(k => <option key={k} value={k}>{ACCESS_FA[k]}</option>)}
          </select></label>
        <label className="fld" style={{ flex: 1 }}><span>از تاریخ (ISO)</span>
          <input className="inp" dir="ltr" placeholder="2026-12-01T00:00" value={f.effective_from}
            onChange={e => setF({ ...f, effective_from: e.target.value })} /></label>
      </div>
      <label className="fld"><span>یادداشت (داخلی)</span>
        <input className="inp" value={f.note} onChange={e => setF({ ...f, note: e.target.value })} /></label>
      <div className="row"><button className="btn primary" disabled={busy} onClick={save}>{busy ? '⏳ …' : '💾 ذخیره پالیسی'}</button>
        <button className="btn" onClick={onClose}>انصراف</button></div>
    </div>
  </Modal>;
}
