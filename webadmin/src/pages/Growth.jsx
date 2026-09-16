import React, { useEffect, useState } from 'react';
import { api, errText } from '../api.js';
import { B, DataTable, Confirm, Switch, PageHeader, toast, Empty, Loading, FaDateTime } from '../ui.jsx';

// 🌱 W13 / 💳 W14 — مدیریت رشد: دعوت‌ها + پیگیری پرداخت نیمه‌تمام.
// همه‌چیز config-driven است؛ پیش‌فرض هر دو کلید خاموش.
const TABS = [['referral', 'دعوت‌ها 🎁'], ['dunning', 'پیگیری پرداخت 💳']];
const TIMING_FA = { on_register: 'موقع ثبت‌نام', on_first_buy: 'موقع اولین خرید', split: 'نصف‌نصف (ثبت‌نام + خرید)' };
const RW_META = {
  sub_days: { label: 'روز اشتراک', unit: 'روز' },
  wallet: { label: 'شارژ کیف پول', unit: 'تومان' },
  discount: { label: 'کد تخفیف اختصاصی', unit: 'درصد' },
  xp: { label: 'امتیاز پرستیژ', unit: 'XP' },
};
const ST_FA = { counted: ['شمرده شد ✅', 'ok'], flagged: ['مشکوک 🚩', 'warn'], capped: ['سقفی ⛔', 'acc'], rejected: ['رد شد ❌', 'bad'] };
const fa = (v) => Number(v ?? 0).toLocaleString('fa-IR');

export default function Growth({ me }) {
  const [tab, setTab] = useState('referral');
  const can = !!me?.is_owner || (me?.perms || []).includes('subscription.manage');
  if (!can) return <PageHeader title="🌱 رشد" sub="نیازمند مجوز «مدیریت اشتراک‌ها» (subscription.manage)" />;
  return <>
    <PageHeader title="🌱 رشد" sub="دعوت دوستان و پیگیری پرداخت نیمه‌تمام — همه‌چیز بدون نیاز به deploy" />
    <div className="tab-bar" role="tablist" style={{ marginBottom: 12 }}>
      {TABS.map(([k, label]) => (
        <button key={k} type="button" role="tab" aria-selected={tab === k}
          className={`tab-btn ${tab === k ? 'tab-btn--on' : ''}`} onClick={() => setTab(k)}>
          {label}
        </button>
      ))}
    </div>
    {tab === 'referral' ? <ReferralTab /> : <DunningTab />}
  </>;
}

function useGrowthConfig() {
  const [cfg, setCfg] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const load = async () => {
    setErr('');
    try { setCfg(await api.growthConfig()); }
    catch (e) { setErr(errText(e)); }
  };
  useEffect(() => { load(); }, []);
  const save = async (patch) => {
    setBusy(true);
    try {
      const r = await api.growthUpdateConfig(patch);
      setCfg({ ref: r.ref, dun: r.dun });
      toast('ذخیره شد ✅');
    } catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  return { cfg, err, busy, load, save };
}

function ReferralTab() {
  const { cfg, err, busy, save } = useGrowthConfig();
  const [stats, setStats] = useState(null);
  const [rows, setRows] = useState(null);
  const [total, setTotal] = useState(0);
  const [fStatus, setFStatus] = useState('');
  const [fInviter, setFInviter] = useState('');
  const [skip, setSkip] = useState(0);
  const [review, setReview] = useState(null);
  const limit = 20;

  const loadStats = async () => {
    try { setStats((await api.growthStats()).referral); } catch { /* بعداً */ }
  };
  const loadRows = async (s = skip) => {
    try {
      const r = await api.growthReferrals({ status: fStatus, inviter: fInviter ? Number(fInviter) : '', skip: s, limit });
      setRows(r.items || []); setTotal(r.total || 0);
    } catch (e) { toast(errText(e), 'err'); }
  };
  useEffect(() => { loadStats(); }, []);
  useEffect(() => { setSkip(0); loadRows(0); }, [fStatus]);

  if (err) return <div className="panel panel-pad">❌ {err}</div>;
  if (!cfg) return <Loading />;
  const ref = cfg.ref || {};
  const setRef = (patch) => save({ ref: { ...ref, ...patch } });
  const setReward = (key, patch) => save({ ref: { rewards: { ...(ref.rewards || {}), [key]: { ...(ref.rewards || {})[key], ...patch } } } });

  const doReview = async () => {
    const { id, approve } = review; setReview(null);
    try {
      await api.growthReview(id, approve);
      toast(approve ? 'تأیید و اعطا شد ✅' : 'رد شد');
      loadRows(skip); loadStats();
    } catch (e) { toast(errText(e), 'err'); }
  };

  return <>
    <div className="panel panel-pad" style={{ marginBottom: 12 }}>
      <div className="row" style={{ gap: 14, flexWrap: 'wrap' }}>
        <Stat label="کل دعوت‌ها" value={stats?.total} />
        <Stat label="شمرده‌شده" value={stats?.counted} />
        <Stat label="مشکوک" value={stats?.flagged} />
        <Stat label="سقفی" value={stats?.capped} />
        <Stat label="اولین خریدها" value={stats?.first_buys} />
      </div>
    </div>

    <div className="panel panel-pad" style={{ marginBottom: 12 }}>
      <div className="row"><Switch on={!!ref.enabled} onChange={(v) => setRef({ enabled: v })} disabled={busy} />
        <div><b>کلید اصلی ریفرال</b><div className="muted">خاموش = لینک‌ها ثبت می‌شوند ولی جایزه‌ای داده نمی‌شود و دکمه‌ها مخفی‌اند</div></div></div>
      <div className="grid" style={{ gap: 10, marginTop: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
        <label className="fld"><span>زمان پرداخت جایزه</span>
          <select className="inp" value={ref.timing || 'split'} disabled={busy}
            onChange={(e) => setRef({ timing: e.target.value })}>
            {Object.keys(TIMING_FA).map((k) => <option key={k} value={k}>{TIMING_FA[k]}</option>)}
          </select></label>
        <NumField label="سقف روزانه هر نفر" value={ref.cap_daily} disabled={busy} onCommit={(v) => setRef({ cap_daily: v })} />
        <NumField label="سقف ماهانه هر نفر" value={ref.cap_monthly} disabled={busy} onCommit={(v) => setRef({ cap_monthly: v })} />
        <NumField label="آستانه انفجار (تعداد)" value={ref.burst_n} disabled={busy} onCommit={(v) => setRef({ burst_n: v })} />
        <NumField label="پنجره انفجار (دقیقه)" value={ref.burst_minutes} disabled={busy} onCommit={(v) => setRef({ burst_minutes: v })} />
      </div>
    </div>

    <div className="panel panel-pad" style={{ marginBottom: 12 }}>
      <b>🎁 انواع جایزه (هرکدام سوییچ جدا)</b>
      <DataTable rowKey="key" columns={[
        { k: 'label', label: 'جایزه', render: (r) => <b>{RW_META[r.key]?.label || r.key}</b> },
        { k: 'on', label: 'وضعیت', render: (r) => <Switch on={!!r.on} disabled={busy} onChange={(v) => setReward(r.key, { on: v })} /> },
        { k: 'amount', label: 'مقدار', render: (r) => <NumField value={r.amount} disabled={busy} onCommit={(v) => setReward(r.key, { amount: v })} /> },
        { k: 'unit', label: 'واحد', render: (r) => <span className="muted">{RW_META[r.key]?.unit || ''}</span> },
      ]} rows={Object.keys(RW_META).map((k) => ({ key: k, on: !!(ref.rewards || {})[k]?.on, amount: (ref.rewards || {})[k]?.amount ?? '' }))} />
      <div className="muted" style={{ marginTop: 8 }}>حالت «نصف‌نصف»: روز/تومان نصف می‌شود؛ کد تخفیف و XP موقع ثبت‌نام داده می‌شود.</div>
    </div>

    <div className="panel panel-pad">
      <div className="row" style={{ gap: 8, marginBottom: 10 }}>
        <select className="inp" value={fStatus} onChange={(e) => setFStatus(e.target.value)}>
          <option value="">همه وضعیت‌ها</option>
          {Object.keys(ST_FA).map((k) => <option key={k} value={k}>{ST_FA[k][0]}</option>)}
        </select>
        <input className="inp" placeholder="آیدی دعوت‌کننده…" value={fInviter}
          onChange={(e) => setFInviter(e.target.value.replace(/\D/g, ''))} style={{ maxWidth: 170 }} />
        <button className="btn sm" onClick={() => { setSkip(0); loadRows(0); }}>🔍 جست‌وجو</button>
      </div>
      {!rows ? <Loading /> : !rows.length ? <Empty text="دعوتی ثبت نشده" /> : <>
        <DataTable rowKey="id" columns={[
          { k: 'inviter', label: 'دعوت‌کننده', render: (r) => <div><b>{r.inviter_name || r.inviter_id}</b><div className="muted">{r.inviter_id}</div></div> },
          { k: 'invitee', label: 'دعوت‌شده', render: (r) => <div><b>{r.invitee_name || r.invitee_id}</b><div className="muted">{r.invitee_id}</div></div> },
          { k: 'status', label: 'وضعیت', render: (r) => <B kind={(ST_FA[r.status] || [])[1] || ''}>{(ST_FA[r.status] || [r.status])[0]}{r.flag_reason ? ` (${r.flag_reason})` : ''}</B> },
          { k: 'grant', label: 'جایزه', render: (r) => <span>{r.reward_register ? '✓ثبت' : '·'} {r.reward_buy ? '✓خرید' : '·'}</span> },
          { k: 'at', label: 'زمان', render: (r) => <span className="muted"><FaDateTime value={r.created_at} /></span> },
          {
            k: 'act', label: '', render: (r) => (r.status === 'flagged' || r.status === 'capped') ? (
              <div className="row" style={{ gap: 5 }}>
                <button className="btn sm" onClick={() => setReview({ id: r.id, approve: true })}>✅ تأیید</button>
                <button className="btn sm" onClick={() => setReview({ id: r.id, approve: false })}>❌ رد</button>
              </div>
            ) : <span className="muted">—</span>,
          },
        ]} rows={rows} />
        <div className="row" style={{ gap: 8, marginTop: 10 }}>
          <button className="btn sm" disabled={skip <= 0} onClick={() => { const s = Math.max(0, skip - limit); setSkip(s); loadRows(s); }}>→ قبلی</button>
          <span className="muted">{fa(skip + 1)}–{fa(Math.min(skip + limit, total))} از {fa(total)}</span>
          <button className="btn sm" disabled={skip + limit >= total} onClick={() => { const s = skip + limit; setSkip(s); loadRows(s); }}>بعدی ←</button>
        </div>
      </>}
    </div>
    {review && <Confirm text={review.approve ? 'تأیید این دعوت؟ (جوایز سررسیده اعطا می‌شود)' : 'رد این دعوت؟ (جایزه‌ای داده نمی‌شود)'}
      onYes={doReview} onNo={() => setReview(null)} />}
  </>;
}

function DunningTab() {
  const { cfg, err, busy, save } = useGrowthConfig();
  const [stats, setStats] = useState(null);
  useEffect(() => { api.growthStats().then((r) => setStats(r.dunning)).catch(() => {}); }, []);
  if (err) return <div className="panel panel-pad">❌ {err}</div>;
  if (!cfg) return <Loading />;
  const dun = cfg.dun || {};
  const setDun = (patch) => save({ dun: { ...dun, ...patch } });
  const hours = [...Array(24).keys()];
  return <>
    <div className="panel panel-pad" style={{ marginBottom: 12 }}>
      <div className="row" style={{ gap: 14, flexWrap: 'wrap' }}>
        <Stat label="در انتظار فعلی" value={stats?.pending_now} />
        <Stat label="یادآوری‌شده" value={stats?.reminded} />
        <Stat label="کلیک ادامه پرداخت" value={stats?.clicks} />
        <Stat label="پرداخت بعد از یادآوری" value={stats?.paid_after_reminder} />
      </div>
      <div className="muted" style={{ marginTop: 8 }}>«پرداخت بعد از یادآوری» تقریبی است: رسیدهایی که یادآوری گرفته‌اند و بعد تأیید شده‌اند.</div>
    </div>
    <div className="panel panel-pad">
      <div className="row"><Switch on={!!dun.enabled} onChange={(v) => setDun({ enabled: v })} disabled={busy} />
        <div><b>کلید اصلی پیگیری</b><div className="muted">خاموش = هیچ یادآوری ارسال نمی‌شود</div></div></div>
      <div className="grid" style={{ gap: 10, marginTop: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
        <NumField label="گام اول (دقیقه بعد از ساخت)" value={Math.round((dun.step1_s || 3600) / 60)} disabled={busy}
          onCommit={(v) => setDun({ step1_s: v * 60 })} />
        <NumField label="گام دوم (ساعت بعد از ساخت)" value={Math.round((dun.step2_s || 86400) / 3600)} disabled={busy}
          onCommit={(v) => setDun({ step2_s: v * 3600 })} />
        <label className="fld"><span>شروع سکوت شبانه (تهران)</span>
          <select className="inp" value={dun.quiet_start ?? 0} disabled={busy}
            onChange={(e) => setDun({ quiet_start: Number(e.target.value) })}>
            {hours.map((h) => <option key={h} value={h}>{fa(h)}:۰۰</option>)}
          </select></label>
        <label className="fld"><span>پایان سکوت شبانه (تهران)</span>
          <select className="inp" value={dun.quiet_end ?? 7} disabled={busy}
            onChange={(e) => setDun({ quiet_end: Number(e.target.value) })}>
            {hours.map((h) => <option key={h} value={h}>{fa(h)}:۰۰</option>)}
          </select></label>
      </div>
      <div className="muted" style={{ marginTop: 8 }}>شروع = پایان یعنی بدون سکوت. پرداختِ کامل/منقضی‌شده خودکار از صف یادآوری می‌افتد.</div>
    </div>
  </>;
}

function Stat({ label, value }) {
  return (
    <div style={{ minWidth: 110 }}>
      <div className="muted" style={{ fontSize: 12 }}>{label}</div>
      <b style={{ fontSize: 20 }}>{value === null || value === undefined ? '…' : fa(value)}</b>
    </div>
  );
}

function NumField({ label, value, onCommit, disabled }) {
  const [v, setV] = useState(value ?? '');
  useEffect(() => { setV(value ?? ''); }, [value]);
  const commit = () => {
    const n = Number(v);
    if (Number.isFinite(n) && n >= 0 && String(n) !== String(value)) onCommit(Math.floor(n));
    else setV(value ?? '');
  };
  return (
    <label className="fld"><span>{label}</span>
      <input className="inp" type="number" min="0" value={v} disabled={disabled}
        onChange={(e) => setV(e.target.value)} onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') commit(); }} />
    </label>
  );
}
