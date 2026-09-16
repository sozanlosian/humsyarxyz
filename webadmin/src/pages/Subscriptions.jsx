import React, { useEffect, useState } from 'react';
import { api, errText } from '../api.js';
import {
  DataTable, Loading, ErrorState, KpiCard, KpiGrid, Section, B, FaDate,
  FaDateTime, PageHeader, Tabs, toast, Confirm, Drawer, Empty, NoPerm,
  Modal, Switch,
} from '../ui.jsx';
import { PersianDatePicker } from '../PersianDatePicker.jsx';
import { formatFaDate, formatFaDayMonth } from '../time.js';
import SavedViews from '../SavedViews.jsx';
import { writeHashQuery } from '../urlState.js';

const fa = n => Number(n ?? 0).toLocaleString('fa-IR');
const money = n => `${Number(n ?? 0).toLocaleString('fa-IR')} تومان`;
const TABS = [
  ['control', '⚙️ مرکز کنترل'],
  ['gateway', '💳 درگاه زرین‌پال'],
  ['payments', '🧾 رسیدها'],
  ['subscribers', '👥 مشترکین'],
  ['discounts', '🎁 تخفیف و کمپین'],
  ['finance', '💰 مالی'],
  ['reconcile', '⚖️ مغایرت‌گیری'],
  ['wallets', '👛 کیف پول‌ها'],
  ['gifts', '🎀 هدایا'],
];

export default function Subscriptions({ route = '' }) {
  const params = new URLSearchParams(route.split('?')[1] || '');
  const requested = params.get('tab');
  const [tab, setTab] = useState(TABS.some(([k]) => k === requested) ? requested : 'control');
  useEffect(() => { if (TABS.some(([k]) => k === requested)) setTab(requested); }, [requested]);
  const changeTab = value => { setDeep(null); setTab(value); writeHashQuery('/subscriptions', { tab: value !== 'control' ? value : '' }); };
  // 🌊 W5 — دیپ‌لینک داخلی از مغایرت‌گیری به رسیدها/مشترکین با همان q
  const [deep, setDeep] = useState(null);
  const internalGo = path => {
    const u = new URLSearchParams((path || '').split('?')[1] || '');
    const t = TABS.some(([k]) => k === u.get('tab')) ? u.get('tab') : 'payments';
    setDeep({ tab: t, q: u.get('q') || '', status: u.get('status') || '' });
    setTab(t);
  };
  const [ov, setOv] = useState(null);
  const [err, setErr] = useState('');
  const [denied, setDenied] = useState(false);

  const loadOverview = async () => {
    setErr('');
    try { setOv(await api.subOverview()); }
    catch (e) { if (e.status === 403) setDenied(true); else setErr(errText(e)); }
  };
  useEffect(() => { loadOverview(); }, []);

  if (denied) return <NoPerm text="مدیریت اشتراک نیازمند مجوز subscription.manage است" />;
  if (err) return <ErrorState title="بارگذاری مرکز اشتراک ناموفق بود" error={err} onRetry={loadOverview} />;
  if (!ov) return <Loading rows={6} />;

  const stats = ov.stats || {};
  return (
    <>
      <PageHeader title="مرکز کنترل اشتراک هامزیار" description="پلن‌ها، رسیدها، مشترکین، اعطای دستی، تخفیف و کمپین با یک منبع داده"
        actions={<><B kind={ov.settings?.subscription_enforced ? 'warn' : 'ok'}>{ov.settings?.subscription_enforced ? '🔒 اشتراک اجباری' : '🔓 دسترسی عمومی'}</B>
          <B kind={ov.settings?.protect_content_enabled ? 'ok' : 'warn'}>{ov.settings?.protect_content_enabled ? '🛡 محافظت محتوا روشن' : '⚠️ محافظت محتوا خاموش'}</B></>} />

      {/* §DW2 — رنگ‌ها از «tint» خام به «tone» معنایی رفتند: رسیدِ
          در انتظار هشدار است و نزدیکِ پایان هم، پس در کلِ پنل یک
          ظاهرِ هشدار دارند. */}
      <KpiGrid className="dw-sub-kpis">
        <KpiCard tone="ok"   icon="💎" label="اشتراک فعال" enter="dw-enter-1"
                 value={fa(stats.active)} />
        <KpiCard tone="warn" icon="🧾" label="رسید در انتظار" enter="dw-enter-2"
                 value={fa(stats.pending)} />
        <KpiCard tone="warn" icon="⏳" label="نزدیک پایان (۷ روز)" enter="dw-enter-3"
                 value={fa(stats.expiring)} />
        <KpiCard tone="acc"  icon="💰" label="درآمد ماه" enter="dw-enter-3"
                 value={money(stats.revenue_month)} />
      </KpiGrid>

      <Tabs items={TABS} value={tab} onChange={changeTab} label="بخش‌های اشتراک" />

      {tab === 'control' && <ControlPanel ov={ov} refresh={loadOverview} />}
      {tab === 'gateway' && <GatewayPanel />}
      {tab === 'payments' && <PaymentsPanel initial={{ status: params.get('status') ?? 'pending', q: params.get('q') || '', page: Number(params.get('page')) || 1 }} />}
      {tab === 'subscribers' && <SubscribersPanel ov={ov} refreshOverview={loadOverview} initial={{ status: params.get('status') || 'active', q: params.get('q') || '', page: Number(params.get('page')) || 1 }} />}
      {tab === 'discounts' && <DiscountsPanel plans={ov.plans || []} refreshOverview={loadOverview} />}
      {tab === 'finance' && <FinancialPanel />}
      {tab === 'reconcile' && <ReconcilePanel onGo={internalGo} />}
      {tab === 'wallets' && <WalletsPanel initial={{ q: params.get('q') || '' }} />}
      {tab === 'gifts' && <GiftsPanel />}
    </>
  );
}

function ControlPanel({ ov, refresh }) {
  const [planEdit, setPlanEdit] = useState(null); // {} = new
  const [deletePlan, setDeletePlan] = useState(null);
  const [busy, setBusy] = useState('');

  const setPolicy = async (key, value) => {
    setBusy(key);
    try { await api.subSettingsUpdate({ [key]: value }); toast('سیاست اشتراک ذخیره شد ✅'); await refresh(); }
    catch (e) { toast(errText(e), 'err'); }
    setBusy('');
  };
  const planToggle = async p => {
    try { await api.subPlanToggle(p.id); toast(p.active ? 'پلن غیرفعال شد' : 'پلن فعال شد ✅'); refresh(); }
    catch (e) { toast(errText(e), 'err'); }
  };
  const planDelete = async p => {
    try { await api.subPlanDelete(p.id); toast('پلن حذف شد'); refresh(); }
    catch (e) { toast(errText(e), 'err'); }
  };

  return (
    <>
      <div className="grid g2">
        <div className="panel panel-pad">
          <b>🔐 سیاست دسترسی</b>
          <div className="grid" style={{ gap: 10, marginTop: 12 }}>
            <div className="row" style={{ alignItems: 'flex-start' }}>
              <Switch on={!!ov.settings?.subscription_enforced} disabled={!!busy}
                onChange={v => setPolicy('subscription_enforced', v)} />
              <div><b>اجباری‌بودن اشتراک هامزیار</b>
                <div className="muted">روشن: منابع مشمول فقط برای مشترک فعال باز می‌شوند؛ خاموش: همه دسترسی دارند.</div></div>
            </div>
            <div className="row" style={{ alignItems: 'flex-start' }}>
              <Switch on={!!ov.settings?.protect_content_enabled} disabled={!!busy}
                onChange={v => setPolicy('protect_content_enabled', v)} />
              <div><b>محافظت کپی‌رایت فایل‌ها</b>
                <div className="muted">ارسال فایل با protect_content؛ فوروارد و ذخیره مستقیم محدود می‌شود.</div></div>
            </div>
          </div>
        </div>
        <CardPanel card={ov.card || {}} refresh={refresh} />
      </div>

      <div className="panel panel-pad" style={{ marginTop: 14 }}>
        <div className="row"><div><b>📦 پلن‌های اشتراک</b>
          <div className="muted">مدت و قیمت هر پلن؛ غیرفعال‌سازی اطلاعات و تاریخچه را حذف نمی‌کند.</div></div>
          <span className="spacer" /><button className="btn primary" onClick={() => setPlanEdit({})}>➕ پلن جدید</button></div>
        <div className="grid g3" style={{ marginTop: 12 }}>
          {(ov.plans || []).map(p => <div key={p.id} className="panel panel-pad" style={{ background: 'var(--bg)' }}>
            <div className="row"><b>{p.name}</b><span className="spacer" />
              <B kind={p.active ? 'ok' : 'bad'}>{p.active ? 'فعال' : 'غیرفعال'}</B></div>
            <div className="row" style={{ marginTop: 10 }}><B>{fa(p.days)} روز</B><B kind="acc">{money(p.price)}</B>{Number(p.ai_daily_limit) > 0 && <B>🤖 {fa(p.ai_daily_limit)}/روز</B>}{Number(p.max_members) > 1 && <B kind="ok">👨‍👩‍👧 {fa(p.max_members)} نفره</B>}</div>
            <div className="row" style={{ marginTop: 10, gap: 5 }}>
              <button className="btn sm" onClick={() => setPlanEdit(p)}>✏️ ویرایش</button>
              <button className="btn sm" onClick={() => setPlanEdit({ ...p, _clone: true })}>📄 کپی</button>
              <button className="btn sm" onClick={() => planToggle(p)}>{p.active ? '⏸ غیرفعال' : '▶ فعال'}</button>
              <button className="btn sm danger" onClick={() => setDeletePlan(p)} aria-label={`حذف پلن ${p.name}`}>🗑</button>
            </div>
          </div>)}
          {!(ov.plans || []).length && <Empty text="هنوز پلنی تعریف نشده" />}
        </div>
      </div>

      {planEdit && <PlanModal plan={planEdit.id ? planEdit : null}
        onClose={() => setPlanEdit(null)} onDone={() => { setPlanEdit(null); refresh(); }} />}
      {deletePlan && <Confirm danger text={`حذف پلن «${deletePlan.name}»؟ تاریخچه خریدها حفظ می‌شود.`}
        onYes={async () => { const p = deletePlan; setDeletePlan(null); await planDelete(p); }}
        onNo={() => setDeletePlan(null)} />}
    </>
  );
}

function CardPanel({ card, refresh }) {
  const [f, setF] = useState({ card_number: card.card_number || '', card_owner: card.card_owner || '' });
  const [busy, setBusy] = useState(false);
  useEffect(() => setF({ card_number: card.card_number || '', card_owner: card.card_owner || '' }), [card.card_number, card.card_owner]);
  const save = async () => {
    setBusy(true);
    try { await api.subCardUpdate(f); toast('اطلاعات کارت ذخیره شد ✅'); refresh(); }
    catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  return <div className="panel panel-pad">
    <b>💳 کارت پرداخت</b>
    <div className="grid" style={{ gap: 9, marginTop: 12 }}>
      <label className="fld"><span>شماره کارت</span><input className="inp" dir="ltr" value={f.card_number}
        onChange={e => setF({ ...f, card_number: e.target.value })} /></label>
      <label className="fld"><span>نام صاحب کارت</span><input className="inp" value={f.card_owner}
        onChange={e => setF({ ...f, card_owner: e.target.value })} /></label>
      <button className="btn primary" disabled={busy || f.card_number.trim().length < 4 || f.card_owner.trim().length < 2}
        onClick={save}>{busy ? '⏳ …' : '💾 ذخیره کارت'}</button>
    </div>
  </div>;
}

function PlanModal({ plan, onClose, onDone }) {
  const clone = !!plan?._clone; const edit = !!plan && !clone;
  const [f, setF] = useState({ name: clone ? `${plan.name} — کپی` : plan?.name || '', days: plan?.days || 30, price: plan?.price || 0, ai_daily_limit: plan?.ai_daily_limit || 0, max_members: plan?.max_members || 1 });
  const [ent, setEnt] = useState({ ...(plan?.entitlements || {}) });
  const [featList, setFeatList] = useState([]);
  // 🌊 W7 — کاتالوگ فیچرها از همان API پنل دسترسی (تک‌منبع)
  useEffect(() => { api.featuresList().then(r => setFeatList(r.items || [])).catch(() => {}); }, []);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      const body = { name: f.name.trim(), days: Number(f.days), price: Number(f.price), ai_daily_limit: Number(f.ai_daily_limit) || 0, entitlements: ent, max_members: Math.max(1, Math.min(50, Number(f.max_members) || 1)) };
      if (edit) await api.subPlanUpdate(plan.id, body); else await api.subPlanAdd(body);
      toast(edit ? 'پلن ویرایش شد ✅' : 'پلن ساخته شد ✅'); onDone();
    } catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  return <Modal title={edit ? `✏️ ویرایش ${plan.name}` : clone ? `📄 کپی پلن ${plan.name}` : '➕ پلن اشتراک جدید'} onClose={onClose}>
    <div className="grid" style={{ gap: 10 }}>
      <input className="inp" placeholder="نام پلن" value={f.name} onChange={e => setF({ ...f, name: e.target.value })} />
      <div className="row"><label className="fld" style={{ flex: 1 }}><span>تعداد روز</span>
        <input className="inp" type="number" min="1" max="3650" value={f.days} onChange={e => setF({ ...f, days: e.target.value })} /></label>
        <label className="fld" style={{ flex: 1 }}><span>قیمت (تومان)</span>
        <input className="inp" type="number" min="0" value={f.price} onChange={e => setF({ ...f, price: e.target.value })} /></label>
        <label className="fld" style={{ flex: 1 }}><span>سهمیه هوشیار/روز (۰=سراسری)</span>
        <input className="inp" type="number" min="0" max="100000" value={f.ai_daily_limit} onChange={e => setF({ ...f, ai_daily_limit: e.target.value })} /></label>
        <label className="fld" style={{ flex: 1 }}><span>ظرفیت خانواده (۱=شخصی)</span>
        <input className="inp" type="number" min="1" max="50" value={f.max_members} onChange={e => setF({ ...f, max_members: e.target.value })} /></label></div>
      {!!featList.length && <div><span className="muted">فیچرهای این پلن (پیش‌فرض: همه باز)</span>
        <div className="grid g3" style={{ marginTop: 6 }}>
          {featList.map(it => <label key={it.key} className="row" style={{ gap: 6, cursor: 'pointer' }}>
            <input type="checkbox" checked={ent[it.key] !== false}
              onChange={e => setEnt({ ...ent, [it.key]: e.target.checked })} />
            <span>{it.label}</span>
          </label>)}
        </div></div>}
      <div className="row"><button className="btn primary" disabled={busy || f.name.trim().length < 2 || Number(f.days) < 1}
        onClick={save}>{busy ? '⏳ …' : 'ذخیره'}</button><button className="btn" onClick={onClose}>انصراف</button></div>
    </div>
  </Modal>;
}

function PaymentsPanel({ initial = {} }) {
  const [status, setStatus] = useState(initial.status ?? 'pending');
  const [kind, setKind] = useState(''); // 🌊 W7 — نوع رسید: ''|normal|topup|gift
  const [q, setQ] = useState(initial.q || '');
  const [search, setSearch] = useState(initial.q || '');
  const [page, setPage] = useState(initial.page || 1);
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const [rcpt, setRcpt] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const [refund, setRefund] = useState(null); // 🌊 W5
  const [visibleColumns, setVisibleColumns] = useState([]);
  const LIMIT = 25;

  const load = async () => {
    setErr(''); setData(null);
    try { setData(await api.subPayments({ status, kind, search, skip: (page - 1) * LIMIT, limit: LIMIT })); }
    catch (e) { setErr(errText(e)); }
  };
  useEffect(() => { load(); }, [status, kind, search, page]);
  useEffect(() => { writeHashQuery('/subscriptions', { tab: 'payments', status: status !== 'pending' ? status : '', q: search, page: page > 1 ? page : '' }); }, [status, search, page]);
  const decide = (pay, approved, note = '') => setConfirm({ pay, approved, note });
  const doDecision = async () => {
    const c = confirm; setConfirm(null);
    try { await api.subPaymentDecision(c.pay.id, c.approved, c.note); toast('تصمیم ثبت شد ✅'); setRcpt(null); load(); }
    catch (e) { toast(errText(e), 'err'); }
  };
  const cols = [
    { k: 'user_name', label: 'دانشجو', render: r => <div><b>{r.user_name}</b><div className="muted">{r.student_id || `#${r.user_id}`}</div></div> },
    { k: 'plan_name', label: 'پلن' },
    { k: 'final_price', label: 'مبلغ', render: r => money(r.final_price) },
    { k: 'discount_code', label: 'تخفیف', render: r => r.discount_code ? <B kind="purple">{r.discount_code} {r.discount_percent ? `· ${fa(r.discount_percent)}٪` : ''}</B> : '—' },
    { k: 'has_receipt', label: 'رسید', render: r => r.has_receipt ? <B kind="acc">🖼 دارد</B> : '—' },
    { k: 'submitted_at', label: 'ثبت', render: r => <FaDateTime value={r.submitted_at} /> },
    { k: 'status', label: 'وضعیت', render: r => <B kind={r.status === 'pending' ? 'warn' : r.status === 'approved' ? 'ok' : 'bad'}>{r.status}</B> },
    { k: 'ops', label: '', stop: true, render: r => <div className="row" style={{ gap: 4 }}>
      {r.status === 'pending' && <>
        <button className="btn sm ok" onClick={() => decide(r, true)} aria-label="تأیید رسید پرداخت">✅</button>
        <button className="btn sm danger" onClick={() => decide(r, false)} aria-label="رد رسید پرداخت">❌</button></>}
      {r.status === 'approved' && <button className="btn sm danger" onClick={() => setRefund(r)} aria-label="بازگشت وجه" title="بازگشت وجه رسید تأییدشده (W5)">💸</button>}
    </div> },
  ];
  if (err) return <ErrorState error={err} onRetry={load} />;
  const total = data?.total || 0;
  return <>
    <div className="panel panel-pad row" style={{ marginBottom: 12, flexWrap: 'wrap' }}>
      <div className="tabs" style={{ border: 0, margin: 0 }} role="tablist" aria-label="وضعیت پرداخت‌ها">
        {[['pending', 'در انتظار'], ['approved', 'تأیید'], ['rejected', 'رد'], ['', 'همه']].map(([k, l]) =>
          <button key={k} type="button" role="tab" aria-selected={status === k} className={`tab ${status === k ? 'on' : ''}`} onClick={() => { setStatus(k); setPage(1); }}>{l}</button>)}
      </div>
      {/* 🌊 W7 — تفکیک نوع رسید (اشتراک/شارژ/هدیه) — همان داده، بدون ستون جدید */}
      <div className="tabs" style={{ border: 0, margin: 0 }} role="tablist" aria-label="نوع رسید">
        {[['', 'همه انواع'], ['normal', '🧾 اشتراک'], ['topup', '💰 شارژ'], ['gift', '🎁 هدیه']].map(([k, l]) =>
          <button key={k || 'all'} type="button" role="tab" aria-selected={kind === k} className={`tab ${kind === k ? 'on' : ''}`} onClick={() => { setKind(k); setPage(1); }}>{l}</button>)}
      </div>
      <span className="spacer" />
      <input className="inp" style={{ minWidth: 250 }} value={q} onChange={e => setQ(e.target.value)}
        onKeyDown={e => e.key === 'Enter' && (setSearch(q.trim()), setPage(1))} placeholder="نام، آیدی، پلن یا کد تخفیف…" />
      <button className="btn sm" onClick={() => { setSearch(q.trim()); setPage(1); }}>🔎 جست‌وجو</button>
    </div>
    <SavedViews scope="payments" filters={{ status, search }} columns={visibleColumns} onApply={(f, item) => { setStatus(f.status ?? 'pending'); setQ(f.search || ''); setSearch(f.search || ''); setVisibleColumns(item.columns || []); setPage(1); }} label="نماهای رسید" />
    {!data ? <Loading rows={5} /> : <DataTable columns={cols} rows={data.payments || []} rowKey="id" colToggle visibleColumns={visibleColumns} onColumnsChange={setVisibleColumns}
      onRow={setRcpt} pager={{ page, pages: Math.max(1, Math.ceil(total / LIMIT)), total, onPage: setPage }} />}
    {rcpt && <ReceiptDrawer pay={rcpt} decide={(ok, note) => decide(rcpt, ok, note)}
      onClose={() => setRcpt(null)} />}
    {confirm && <Confirm danger={!confirm.approved}
      text={confirm.approved ? `تأیید رسید ${confirm.pay.user_name} و فعال‌سازی اشتراک؟` : `رد رسید ${confirm.pay.user_name}؟`}
      onYes={doDecision} onNo={() => setConfirm(null)} />}
    {refund && <RefundModal pay={refund} onClose={() => setRefund(null)} onDone={() => { setRefund(null); load(); }} />}
  </>;
}

// 🌊 W5 — بازگشت وجه: تأیید صریح + دلیل اجباری + revoke اختیاری اشتراک
// 💰 W6 — مقصد بازگشت، کیف پول داخلی دانشجوست؛ پیش‌نمایش اثر قبل از تأیید
function RefundModal({ pay, onClose, onDone }) {
  const [reason, setReason] = useState('');
  const [revoke, setRevoke] = useState(false);
  const [busy, setBusy] = useState(false);
  const [balance, setBalance] = useState(null);
  useEffect(() => {
    api.subWalletDetail(pay.user_id, { limit: 1 })
      .then(d => setBalance(d.summary.balance)).catch(() => {});
  }, [pay.user_id]);
  const amount = pay.final_price ?? pay.price ?? 0;
  const run = async () => {
    setBusy(true);
    try {
      const r = await api.subRefund(pay.id, { confirm: true, reason: reason.trim(), revoke_subscription: revoke });
      toast(r.wallet_credited
        ? `بازگشت وجه ثبت شد 💸 — ${money(amount)} به کیف پول دانشجو منتقل شد`
        : 'بازگشت وجه ثبت شد 💸', r.wallet_credited ? 'ok' : 'warn');
      // 🌊 W3/MISS-02 — بازوی درگاهی دستی
      if (r.gateway_reversal === 'manual_required') {
        toast('⚠️ پول واقعی در درگاه گرفته شده — در پنل زرین‌پال هم برگشت وجه را ثبت کن', 'warn');
      }
      onDone();
    } catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  return <Modal title={`💸 بازگشت وجه به کیف پول — ${pay.user_name || pay.user_id}`} onClose={onClose}>
    <p className="muted" style={{ marginTop: 0 }}>
      مبلغ معتبرِ خودِ رسید (سرور-ساید) به <b>کیف پول داخلی دانشجو</b> منتقل می‌شود؛
      گذار approved→refunded اتمیک و برگشت‌ناپذیر است و در حسابرسی با شدت بحرانی
      ثبت می‌شود. اگر اشتراک revoke نشود، مغایرت‌گیری پرچم نگه می‌دارد.
    </p>
    <div className="row q-missing" style={{ marginBottom: 10 }}>
      <B kind="acc">👤 {pay.user_name || `کاربر ${pay.user_id}`}</B>
      {pay.plan_name && <B kind="acc">📦 {pay.plan_name}</B>}
      <B kind="ok">مبلغ قابل بازگشت: {money(amount)}</B>
      {balance != null && <B kind="ok">کیف پول: {money(balance)} ← {money(balance + amount)}</B>}
    </div>
    <input className="inp" placeholder="دلیل بازگشت وجه (حداقل ۳ نویسه) *" value={reason} onChange={e => setReason(e.target.value)} />
    <label className="row" style={{ marginTop: 10 }}>
      <input type="checkbox" checked={revoke} onChange={e => setRevoke(e.target.checked)} />
      <span>هم‌زمان اشتراک کاربر نیز revoke شود</span>
    </label>
    <div className="row" style={{ marginTop: 12 }}>
      <button className="btn danger" disabled={busy || reason.trim().length < 3} onClick={run}>
        {`ثبت بازگشت ${money(amount)} به کیف پول`}
      </button>
      <button className="btn" onClick={onClose}>انصراف</button>
    </div>
  </Modal>;
}

// 🌊 W5 — مغایرت‌گیری مالی: ناهم‌خوانی‌های پول/دسترسی بین sub_payments و subscriptions
// 🌊 GIFT — پنل مدیریت هدیه‌ها: فهرست/فیلتر/صفحه‌بندی + لغو pending
// و ارسال دوباره‌ی اعلان. تأیید هدیه همان تصمیم رسید است (تب رسیدها) —
// هیچ «فعال‌سازی دستی کور» وجود ندارد.
const GIFT_STATUS_FA = {
  pending: ['در انتظار', 'warn'],
  approved: ['فعال‌شده', 'ok'],
  rejected: ['رد شده', 'bad'],
  refunded: ['بازگشت وجه', 'bad'],
  cancelled: ['لغو شده', ''],
};

function GiftsPanel() {
  const [status, setStatus] = useState('all');
  const [payer, setPayer] = useState('');
  const [recipient, setRecipient] = useState('');
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState('');
  const [cancelTarget, setCancelTarget] = useState(null);
  const PER = 20;
  const load = () => {
    setErr(''); setData(null);
    api.subGifts({ status, payer: payer || 0, recipient: recipient || 0, page, per_page: PER })
      .then(setData).catch(e => setErr(errText(e)));
  };
  useEffect(() => { load(); }, [status, payer, recipient, page]);
  useEffect(() => { writeHashQuery('/subscriptions', { tab: 'gifts', status: status !== 'all' ? status : '', page: page > 1 ? page : '' }); }, [status, page]);

  const doCancel = async () => {
    const r = cancelTarget; setCancelTarget(null);
    if (!r) return;
    setBusy(r.id);
    try { await api.subGiftCancel(r.id); toast('هدیه لغو شد'); load(); }
    catch (e) { toast(errText(e), 'err'); }
    finally { setBusy(''); }
  };

  const retryNotify = async (r) => {
    setBusy(r.id);
    try { await api.subGiftRetryNotify(r.id); toast('اعلان گیرنده دوباره در صف ارسال قرار گرفت'); }
    catch (e) { toast(errText(e), 'err'); }
    finally { setBusy(''); }
  };

  const pages = data ? Math.max(1, Math.ceil(data.total / PER)) : 1;

  return <div className="panel panel-pad" style={{ marginTop: 12 }}>
    <div className="row" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
      <b>🎀 هدیه‌های اشتراک</b>
      <select className="inp" style={{ width: 'auto' }} value={status} onChange={e => { setStatus(e.target.value); setPage(1); }}>
        <option value="all">همه</option>
        <option value="pending">در انتظار</option>
        <option value="approved">فعال‌شده</option>
        <option value="rejected">رد شده</option>
        <option value="refunded">بازگشت وجه</option>
        <option value="cancelled">لغو شده</option>
      </select>
      <input className="inp" style={{ width: 150 }} placeholder="آیدی پرداخت‌کننده…" value={payer}
        onChange={e => setPayer(e.target.value.replace(/\D/g, ''))} />
      <input className="inp" style={{ width: 150 }} placeholder="آیدی گیرنده…" value={recipient}
        onChange={e => setRecipient(e.target.value.replace(/\D/g, ''))} />
      <span className="spacer" />
      <button className="btn sm" onClick={load}>↻ تازه‌سازی</button>
    </div>
    <div className="row" style={{ gap: 8, marginBottom: 8 }}>
      <span className="muted small">تأیید/رد هدیه از تب «رسیدها» انجام می‌شود — همان رسید، همان تصمیم. اینجا فقط لغو pending و retry اعلان.</span>
    </div>
    {err && <ErrorState error={err} onRetry={load} />}
    {!err && !data && <Loading rows={4} />}
    {data && <>
      <DataTable rowKey="id" rows={data.items}
        empty={<Empty icon="🎀" text="هدیه‌ای ثبت نشده است" />} columns={[
          { k: 'payer', label: 'پرداخت‌کننده', render: r => <span>{r.payer_name} <span className="muted">#{fa(r.payer_id)}</span></span> },
          { k: 'recipient', label: 'گیرنده', render: r => <span>{r.recipient_name} <span className="muted">#{fa(r.recipient_id)}</span></span> },
          { k: 'plan_name', label: 'پلن' },
          { k: 'final_price', label: 'مبلغ', render: r => money(r.final_price) },
          { k: 'status', label: 'وضعیت', render: r => { const [l, kind] = GIFT_STATUS_FA[r.status] || [r.status, '']; return <B kind={kind}>{l}</B>; } },
          { k: 'message', label: 'پیام', render: r => r.message ? <span title={r.message}>{r.message.length > 40 ? r.message.slice(0, 40) + '…' : r.message}</span> : '—' },
          { k: 'submitted_at', label: 'ثبت', render: r => <FaDateTime value={r.submitted_at} /> },
          { k: 'activated_at', label: 'فعال‌سازی', render: r => r.activated_at ? <FaDateTime value={r.activated_at} /> : '—' },
          { k: 'ops', label: 'عملیات', render: r => <div className="row" style={{ gap: 6 }}>
            {r.status === 'pending' && <button className="btn sm danger" disabled={busy === r.id} onClick={() => setCancelTarget(r)}>لغو</button>}
            {r.status === 'approved' && <button className="btn sm" disabled={busy === r.id} onClick={() => retryNotify(r)}>📨 اعلان دوباره</button>}
          </div> },
        ]} />
      <div className="row" style={{ justifyContent: 'center', gap: 8, marginTop: 10 }}>
        <button className="btn sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>‹ قبلی</button>
        <span className="muted">صفحه {fa(page)} از {fa(pages)} — {fa(data.total)} هدیه</span>
        <button className="btn sm" disabled={page >= pages} onClick={() => setPage(p => p + 1)}>بعدی ›</button>
      </div>
    </>}
    {cancelTarget && <Confirm danger
      text={`هدیه‌ی «${cancelTarget.plan_name}» از ${cancelTarget.payer_name} به ${cancelTarget.recipient_name} لغو شود؟ ظرفیت کد تخفیف (اگر داشت) آزاد می‌شود.`}
      onYes={doCancel} onNo={() => setCancelTarget(null)} />}
  </div>;
}

// 🌊 W5 — مغایرت‌گیری مالی انسانی: هر ناهم‌خوانی یک جمله‌ی قابل‌فهم است
// (چه چیزی، چرا، چه اثری) + اقدام مستقیم یا دیپ‌لینک. ID فقط در جزئیات فنی.
function ReconcilePanel({ onGo }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const [confirmAct, setConfirmAct] = useState(null);
  const [confirmRecredit, setConfirmRecredit] = useState(null);
  const [confirmResync, setConfirmResync] = useState(null);
  const [confirmResolve, setConfirmResolve] = useState(null);
  const [confirmFinalize, setConfirmFinalize] = useState(null);
  const [busy, setBusy] = useState('');
  const load = () => { setErr(''); setData(null); api.subReconcile().then(setData).catch(e => setErr(errText(e))); };
  useEffect(load, []);
  const activate = async item => {
    setBusy(item.payment_id);
    try {
      await api.subReconcileActivate(item.payment_id);
      toast('اشتراک با فعال‌سازی امن فعال شد ✅ — مورد از مغایرت خارج شد', 'ok');
      setConfirmAct(null); load();
    } catch (e) { toast(errText(e), 'err'); }
    finally { setBusy(''); }
  };
  // 💰 W6 — اقدام امن «اعتبار مجدد کیف پول»: idempotent در بک‌اند
  const recredit = async item => {
    setBusy(item.payment_id);
    try {
      const r = await api.subWalletRecredit(item.payment_id);
      toast(`مبلغ ${money(item.amount)} به کیف پول اعتبار شد ✅`, 'ok');
      setConfirmRecredit(null); load();
    } catch (e) { toast(errText(e), 'err'); }
    finally { setBusy(''); }
  };
  // 🌊 W6.2 — اعمال اعتبار رسید شارژ (اجرای دوباره‌ی finalize — idempotent)
  const finalizeTopup = async item => {
    setBusy(item.payment_id);
    try {
      const r = await api.subReconFinalizeTopup(item.payment_id);
      toast(r.already_credited
        ? 'اعتبار قبلاً ثبت شده بود — اثر دوم ساخته نشد ✅'
        : `اعتبار شارژ ${money(r.amount)} اعمال شد ✅`, 'ok');
      setConfirmFinalize(null); load();
    } catch (e) { toast(errText(e), 'err'); }
    finally { setBusy(''); }
  };
  // 💰 W6 — هم‌ترازسازی موجودی کش با ledger (ledger منبع حقیقت است)
  const resync = async item => {
    setBusy(`resync-${item.user_id}`);
    try {
      const r = await api.subWalletResync(item.user_id);
      toast(`موجودی با ledger هم‌تراز شد: ${money(r.balance)} ✅`, 'ok');
      setConfirmResync(null); load();
    } catch (e) { toast(errText(e), 'err'); }
    finally { setBusy(''); }
  };
  // 🌊 W6.1 — تعیین تکلیف تراکنش معلق (کرش): تشخیص اعمالِ اثر در بک‌اند
  // evidence-based است؛ اینجا فقط انتخاب ادمین + تأیید است.
  const resolveTx = async (txId, action) => {
    setBusy(`tx-${txId}`);
    try {
      const r = await api.subWalletTxResolve(txId, action);
      toast(action === 'complete'
        ? (r.resolution === 'applied_now'
          ? 'اثر تراکنش همین حالا اتمیک اعمال شد ✅'
          : 'اثر مالی قبلاً اعمال شده بود — فقط نشان‌گذاری شد (بدون اثر دوم) ✅')
        : 'تراکنش لغو شد — در صورت لزوم جبران مالی ثبت شد ✅', 'ok');
      setConfirmResolve(null); load();
    } catch (e) { toast(errText(e), 'err'); }
    finally { setBusy(''); }
  };
  return <div className="panel panel-pad" style={{ marginTop: 12 }}>
    <div className="row" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
      <b>⚖️ مغایرت‌گیری مالی</b>
      {data && <B kind={data.summary.total ? 'bad' : 'ok'}>{data.summary.total ? `${fa(data.summary.total)} ناهم‌خوانی باز` : 'بدون ناهم‌خوانی ✅'}</B>}
      {data && data.summary.resolved_today > 0 && <B kind="ok">✅ رفع‌شده امروز: {fa(data.summary.resolved_today)}</B>}
      <span className="spacer" />
      <button className="btn sm" onClick={load}>↻ تازه‌سازی</button>
    </div>
    <div className="panel panel-pad data-quality-note" style={{ marginBottom: 10 }}>
      <B kind="acc">مغایرت یعنی چه؟</B>
      <span>مقایسه‌ی «رسید ↔ اشتراک ↔ وضعیت مالی»: مثلاً پول تأیید شده ولی دسترسی فعال نشده، یا برعکس. هر مورد زیر دقیقاً می‌گوید چه چیزی ناهم‌خوان است و چه اقدامی ممکن است.</span>
    </div>
    {err && <ErrorState error={err} onRetry={load} />}
    {!err && !data && <Loading rows={4} />}
    {data && !data.items.length && <Empty icon="✅" text="مغایرت مالی فعالی وجود ندارد — رسیدها و اشتراک‌ها هم‌خوان‌اند." />}
    {data && !!data.items.length && <div className="q-list">
      {data.items.map((r, i) => <div key={`${r.type}-${r.payment_id || r.user_id}-${i}`} className={`q-issue q-issue--${r.severity === 'warning' ? 'warning' : 'critical'}`}>
        <div className="q-issue-head">
          <span className="q-issue-icon">⚖️</span>
          <div style={{ flex: 1 }}>
            <b>{r.user_name || `کاربر #${fa(r.user_id)}`}</b>
            <div className="muted" style={{ marginTop: 2 }}>{r.summary}</div>
          </div>
          <B kind={r.severity === 'warning' ? 'warn' : 'bad'}>{r.label}</B>
        </div>
        <div className="row q-missing">
          {r.user_name && <B kind="acc">👤 {r.user_name}</B>}
          {r.student_id && <B kind="acc">🎓 {r.student_id}</B>}
          {r.amount != null && <B kind="ok">💰 {money(r.amount)}</B>}
          {r.plan_name && <B kind="acc">📦 {r.plan_name}</B>}
          {r.at && <B kind="warn">🕓 <FaDateTime value={r.at} /></B>}
        </div>
        <div className="row" style={{ marginTop: 8, gap: 8, flexWrap: 'wrap' }}>
          {(r.actions || []).map(a => a.key === 'activate'
            ? <button key={a.key} className="btn sm ok" disabled={!!busy} onClick={() => setConfirmAct(r)}>✅ {a.label}</button>
            : a.key === 'recredit'
            ? <button key={a.key} className="btn sm ok" disabled={!!busy} onClick={() => setConfirmRecredit(r)}>💰 {a.label}</button>
            : a.key === 'finalize_topup'
            ? <button key={a.key} className="btn sm ok" disabled={!!busy} onClick={() => setConfirmFinalize(r)}>💳 {a.label}</button>
            : a.key === 'resync'
            ? <button key={a.key} className="btn sm ok" disabled={!!busy} onClick={() => setConfirmResync(r)}>⚖️ {a.label}</button>
            : a.key === 'resolve_tx'
            ? <button key={a.key} className="btn sm ok" disabled={!!busy} onClick={() => setConfirmResolve({ item: r, tx_id: a.tx_id })}>⏳ {a.label}</button>
            : <button key={a.key} className="btn sm" onClick={() => onGo?.(a.go)}>{a.label} ‹</button>)}
          {(busy === r.payment_id || busy === `resync-${r.user_id}`) && <span className="muted">…</span>}
        </div>
        {r.technical && <details className="q-tech"><summary>جزئیات فنی</summary><div className="code muted">{r.technical}</div></details>}
      </div>)}
    </div>}
    {confirmAct && <Confirm onNo={() => setConfirmAct(null)} onYes={() => activate(confirmAct)}
      text={`فعال‌سازی امن اشتراک برای ${confirmAct.user_name || `کاربر #${fa(confirmAct.user_id)}`}؟ دوره از پلن واقعی رسید (${confirmAct.plan_name || 'نامشخص'}) محاسبه می‌شود و اقدام با شدت بحرانی در حسابرسی ثبت می‌شود.`} />}
    {confirmRecredit && <Confirm onNo={() => setConfirmRecredit(null)} onYes={() => recredit(confirmRecredit)}
      text={`اعتبار مجدد ${money(confirmRecredit.amount)} به کیف پول ${confirmRecredit.user_name || `کاربر #${fa(confirmRecredit.user_id)}`}؟ این اقدام idempotent است (اجرای دوباره = یک اثر) و با شدت بحرانی در حسابرسی ثبت می‌شود.`} />}
    {confirmFinalize && <Confirm onNo={() => setConfirmFinalize(null)} onYes={() => finalizeTopup(confirmFinalize)}
      text={`اعمال اعتبار شارژ ${money(confirmFinalize.amount)} به کیف پول ${confirmFinalize.user_name || `کاربر #${fa(confirmFinalize.user_id)}`}؟ همان primitive مشترک تأیید رسید اجرا می‌شود (idempotent — اجرای دوباره اثر دوم نمی‌سازد) و با شدت بحرانی در حسابرسی ثبت می‌شود.`} />}
    {confirmResolve && <Modal title="⏳ تعیین تکلیف تراکنش معلق" onClose={() => setConfirmResolve(null)}>
      <p className="muted" style={{ marginTop: 0 }}>
        تراکنش معلق یعنی فرآیند بین «ثبت در ledger» و «اعمال اثر» قطع شده (کرش).
        بک‌اند با مقایسه‌ی موجودی و جمع ledger تشخیص می‌دهد اثر مالی قبلاً اعمال
        شده یا نه — هیچ‌وقت اثر دوم ساخته نمی‌شود. هر دو اقدام با شدت بحرانی
        در حسابرسی ثبت می‌شوند.
      </p>
      <div className="row q-missing" style={{ marginBottom: 10 }}>
        <B kind="warn">💰 {money(confirmResolve.item.amount)}</B>
        <B kind="acc">👤 {confirmResolve.item.user_name || `کاربر #${fa(confirmResolve.item.user_id)}`}</B>
      </div>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <button className="btn ok" disabled={!!busy} onClick={() => resolveTx(confirmResolve.tx_id, 'complete')}>
          ✅ تکمیل — اگر اثر اعمال نشده، اتمیک اعمال شود</button>
        <button className="btn danger" disabled={!!busy} onClick={() => resolveTx(confirmResolve.tx_id, 'cancel')}>
          🚫 لغو — اگر اثر اعمال شده، جبران شود</button>
      </div>
    </Modal>}
    {confirmResync && <Confirm onNo={() => setConfirmResync(null)} onYes={() => resync(confirmResync)}
      text={`موجودی کیف پول ${confirmResync.user_name || `کاربر #${fa(confirmResync.user_id)}`} با جمع ledger هم‌تراز شود؟ ledger منبع حقیقت است و اختلاف ${money(confirmResync.amount)} تومانی حذف می‌شود. اگر جمع ledger منفی باشد، بک‌اند اصلاح خودکار را رد می‌کند. اقدام با شدت بحرانی در حسابرسی ثبت می‌شود.`} />}
  </div>;
}

// 🌊 W5 — مرکز مالی: KPIها و روند درآمد از aggregate واقعی بک‌اند،
// نه شمارش فرانت. بازگشت وجه و نرخ‌ها جدا دیده می‌شوند + خروجی CSV.
function FinancialPanel() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const load = () => { setErr(''); setData(null); api.subFinance().then(setData).catch(e => setErr(errText(e))); };
  useEffect(load, []);
  if (err) return <ErrorState error={err} onRetry={load} />;
  if (!data) return <Loading rows={5} />;
  const maxDay = Math.max(1, ...data.daily.map(d => d.total));
  const pct = v => v == null ? '—' : `${Number(v).toLocaleString('fa-IR')}٪`;
  return <>
    <KpiGrid className="dw-sub-kpis">
      <KpiCard tone="ok" icon="💰" label="درآمد کل (تأییدشده)" value={money(data.revenue_total)} />
      <KpiCard tone="acc" icon="📅" label="درآمد ۷ روز" value={money(data.revenue_week)} />
      <KpiCard tone="warn" icon="💸" label="بازگشت وجه" value={`${fa(data.refunded_count)} مورد · ${money(data.revenue_refunded)}`} />
      <KpiCard tone="warn" icon="🧾" label="در انتظار بررسی" value={fa(data.pending_count)} />
      <KpiCard tone="acc" icon="📈" label="نرخ تأیید / نرخ بازگشت" value={`${pct(data.success_rate)} / ${pct(data.refund_rate)}`} />
      {data.wallet && <KpiCard tone="ok" icon="👛" label="موجودی کل کیف پول‌ها" value={`${money(data.wallet.balance)} · ${fa(data.wallet.wallets)} کیف پول`} />}
    </KpiGrid>
    {data.wallet && !!Object.keys(data.wallet.by_type || {}).length && <div className="panel panel-pad" style={{ marginTop: 12 }}>
      <div className="row"><b>👛 جریان کیف پول</b>
        <span className="muted">اعتبار/کسر از ledger — تفکیک نوع تراکنش</span></div>
      <div className="row" style={{ flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
        {Object.entries(data.wallet.by_type).map(([k, v]) => {
          const [label, kind] = TX_KIND[k] || [k, 'acc'];
          return <B key={k} kind={kind}>{label}: {fa(v.count)} تراکنش · {money(v.total)}</B>;
        })}
      </div>
    </div>}
    <div className="panel panel-pad" style={{ marginTop: 12 }}>
      <div className="row"><b>📈 درآمد ۱۴ روز اخیر</b><span className="spacer" />
        <button className="btn sm" onClick={() => api.exportPaymentsCsv({})}>⬇️ خروجی CSV رسیدها</button></div>
      {!data.daily.length ? <Empty icon="📈" text="در این بازه رسید تأییدشده‌ای ثبت نشده" /> :
        <div className="fin-bars" role="img" aria-label="نمودار درآمد روزانه">
          {data.daily.map(d => <div key={d.day} className="fin-bar-col">
            <div className="fin-bar" style={{ height: `${Math.max(4, Math.round(100 * d.total / maxDay))}%` }} title={`${formatFaDate(d.day)}: ${money(d.total)}`} />
            <span className="fin-bar-day">{formatFaDayMonth(d.day)}</span>
          </div>)}
        </div>}
    </div>
    <div className="panel panel-pad" style={{ marginTop: 12 }}>
      <div className="row"><b>💸 آخرین بازگشت وجه‌ها</b></div>
      {!data.refunds.length ? <Empty icon="💸" text="بازگشت وجهی ثبت نشده است" /> :
        <DataTable rowKey="payment_id" rows={data.refunds} columns={[
          { k: 'user_name', label: 'کاربر', render: r => <div><b>{r.user_name || `#${fa(r.user_id)}`}</b></div> },
          { k: 'amount', label: 'مبلغ', render: r => money(r.amount) },
          { k: 'reason', label: 'دلیل' },
          { k: 'at', label: 'تاریخ', render: r => <FaDateTime value={r.at} /> },
        ]} />}
    </div>
  </>;
}

function ReceiptDrawer({ pay: r, decide, onClose }) {
  const [note, setNote] = useState('');
  const [imgErr, setImgErr] = useState(false);
  // 🌊 W5 — ردیابی کامل: User → Payment → Subscription → Refund → Audit
  const [trace, setTrace] = useState(null); const [traceOpen, setTraceOpen] = useState(false);
  const loadTrace = () => { setTrace(null); api.subPaymentTrace(r.id).then(setTrace).catch(e => toast(errText(e), 'err')); };
  const sendToMe = async () => {
    try { await api.subSendReceipt(r.id); toast('تصویر رسید در تلگرام برای شما ارسال شد'); }
    catch (e) { toast(errText(e), 'err'); }
  };
  return <Drawer wide title={`🧾 رسید — ${r.user_name || r.user_id}`} onClose={onClose}>
    <div className="rcpt">
      <div><dl className="kv" style={{ marginTop: 0 }}>
        {Object.entries({ 'دانشجو': r.user_name, 'شماره دانشجویی': r.student_id,
          'یوزرنیم': r.username && '@' + r.username, 'پلن': r.plan_name,
          'مبلغ پایه': money(r.price), 'مبلغ نهایی': money(r.final_price),
          'کد تخفیف': r.discount_code, 'درصد تخفیف': r.discount_percent != null ? `${r.discount_percent}٪` : '',
          'ثبت': r.submitted_at, 'یادداشت بررسی': r.review_note,
        }).filter(([, v]) => v).map(([k, v]) => <React.Fragment key={k}><dt>{k}</dt><dd>{k === 'ثبت' ? <FaDateTime value={v} /> : String(v)}</dd></React.Fragment>)}</dl>
        <button className="btn sm" onClick={sendToMe}>📨 ارسال تصویر به تلگرام من</button>
        <button className="btn sm" style={{ marginInlineStart: 6 }} onClick={() => { setTraceOpen(o => !o); if (!trace) loadTrace(); }}>🔗 ردیابی کامل (کاربر→پرداخت→اشتراک→حسابرسی)</button>
        {traceOpen && <div className="q-form" style={{ marginTop: 10 }}>
          {!trace ? <Loading rows={3} /> : <>
            <div className="row q-missing">
              <B kind="acc">👤 {trace.user?.name || `#${fa(trace.user?.user_id)}`}</B>
              {trace.user?.student_id && <B kind="acc">🎓 {trace.user.student_id}</B>}
              <B kind={trace.payment?.status === 'approved' ? 'ok' : trace.payment?.status === 'pending' ? 'warn' : 'bad'}>وضعیت رسید: {trace.payment?.status}</B>
              {trace.subscription
                ? <B kind={trace.subscription.status === 'active' ? 'ok' : 'warn'}>اشتراک: {trace.subscription.status} · پایان <FaDateTime value={trace.subscription.end_date} /></B>
                : <B kind="warn">اشتراک: فعال نشده</B>}
              {trace.refund && <B kind="bad">💸 بازگشت وجه: {trace.refund.reason}</B>}
              {trace.gift && <B kind="acc">🎀 هدیه به #{fa(trace.gift.to)}</B>}
            </div>
            {!!(trace.wallet_txs || []).length && <>
              <div className="muted" style={{ marginTop: 8, fontSize: 'var(--fs-label)' }}>زنجیره‌ی کیف پول:</div>
              {trace.wallet_txs.map(t => <div key={t.id} className="row" style={{ gap: 6, marginTop: 4 }}>
                <B kind={t.direction === 'credit' ? 'ok' : 'bad'}>
                  {t.direction === 'credit' ? '➕' : '➖'} {money(t.amount)}
                </B>
                <span className="muted">{t.label} · موجودی پس از آن: {money(t.balance_after)} · <FaDateTime value={t.at} /></span>
              </div>)}
            </>}
            <div className="muted" style={{ marginTop: 8, fontSize: 'var(--fs-label)' }}>خط زمانی حسابرسی:</div>
            {!trace.audit.length ? <div className="muted">رویداد حسابرسی برای این رسید ثبت نشده.</div> :
              <ul className="trace-timeline">
                {trace.audit.map(a => <li key={a.id}><FaDateTime value={a.at} /> — <b>{a.actor_name}</b>: {a.action}</li>)}
              </ul>}
          </>}
        </div>}
        {r.status === 'pending' && <div className="panel panel-pad" style={{ background: 'var(--bg)', marginTop: 10 }}>
          <input className="inp" style={{ width: '100%' }} placeholder="یادداشت بررسی…" value={note} onChange={e => setNote(e.target.value)} />
          <div className="row" style={{ marginTop: 8 }}><button className="btn ok" onClick={() => decide(true, note)}>✅ تأیید</button>
            <button className="btn danger" onClick={() => decide(false, note)}>❌ رد</button></div>
        </div>}
      </div>
      <div className="rcpt-img">{r.has_receipt && !imgErr ? <img src={api.subReceiptSrc(r.id)} alt="تصویر رسید"
        onError={() => setImgErr(true)} /> : <Empty icon="🖼" text="تصویر رسید در دسترس نیست" />}</div>
    </div>
  </Drawer>;
}

function SubscribersPanel({ ov, refreshOverview, initial = {} }) {
  const [status, setStatus] = useState(initial.status || 'active');
  const [q, setQ] = useState(initial.q || '');
  const [search, setSearch] = useState(initial.q || '');
  const [page, setPage] = useState(initial.page || 1);
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const [selected, setSelected] = useState(null);
  const [grantOpen, setGrantOpen] = useState(false);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [visibleColumns, setVisibleColumns] = useState([]);
  const LIMIT = 30;
  const load = async () => {
    setErr(''); setData(null);
    try { setData(await api.subSubscribers({ status, search, skip: (page - 1) * LIMIT, limit: LIMIT })); }
    catch (e) { setErr(errText(e)); }
  };
  useEffect(() => { load(); }, [status, search, page]);
  useEffect(() => { writeHashQuery('/subscriptions', { tab: 'subscribers', status: status !== 'active' ? status : '', q: search, page: page > 1 ? page : '' }); }, [status, search, page]);
  if (err) return <ErrorState error={err} onRetry={load} />;
  const total = data?.total || 0;
  const cols = [
    { k: 'name', label: 'دانشجو', render: r => <div><b>{r.name}</b><div className="muted">{r.student_id || `#${r.user_id}`}</div></div> },
    { k: 'plan_name', label: 'پلن' },
    { k: 'end_date', label: 'پایان', render: r => <FaDateTime value={r.end_date} /> },
    { k: 'status', label: 'وضعیت', render: r => <B kind={r.status === 'active' ? 'ok' : r.status === 'expired' ? 'warn' : 'bad'}>{r.status}</B> },
    { k: 'ops', label: '', stop: true, render: r => <button className="btn sm" onClick={() => setSelected(r.user_id)}>مدیریت ‹</button> },
  ];
  return <>
    <div className="row" style={{ marginBottom: 12, flexWrap: 'wrap' }}>
      <div className="tabs" style={{ border: 0, margin: 0 }} role="tablist" aria-label="وضعیت اشتراک‌ها">
        {[['active', 'فعال'], ['expired', 'منقضی'], ['revoked', 'لغوشده']].map(([k, l]) =>
          <button key={k} type="button" role="tab" aria-selected={status === k} className={`tab ${status === k ? 'on' : ''}`} onClick={() => { setStatus(k); setPage(1); }}>{l}</button>)}
      </div>
      <input className="inp" style={{ minWidth: 230 }} value={q} onChange={e => setQ(e.target.value)}
        onKeyDown={e => e.key === 'Enter' && (setSearch(q.trim()), setPage(1))} placeholder="دانشجو، پلن یا آیدی…" />
      <button className="btn sm" onClick={() => { setSearch(q.trim()); setPage(1); }} aria-label="جست‌وجوی مشترک‌ها">🔎</button>
      <span className="spacer" />
      <button className="btn" onClick={() => setGrantOpen(true)}>👤 اعطای دستی</button>
      <button className="btn primary" onClick={() => setBulkOpen(true)}>🎁 اعطای دسته‌جمعی</button>
    </div>
    <SavedViews scope="subscriptions" filters={{ status, search }} columns={visibleColumns} onApply={(f, item) => { setStatus(f.status || 'active'); setQ(f.search || ''); setSearch(f.search || ''); setVisibleColumns(item.columns || []); setPage(1); }} label="نماهای مشترک‌ها" />
    {!data ? <Loading rows={5} /> : <DataTable columns={cols} rows={data.subscribers || []} rowKey="user_id" colToggle visibleColumns={visibleColumns} onColumnsChange={setVisibleColumns}
      onRow={r => setSelected(r.user_id)} pager={{ page, pages: Math.max(1, Math.ceil(total / LIMIT)), total, onPage: setPage }} />}
    {selected && <SubscriberDrawer uid={selected} plans={ov.plans || []} onClose={() => setSelected(null)}
      onChanged={() => { load(); refreshOverview(); }} />}
    {grantOpen && <ManualGrantModal plans={ov.plans || []} onClose={() => setGrantOpen(false)}
      onDone={() => { setGrantOpen(false); load(); refreshOverview(); }} />}
    {bulkOpen && <BulkGrantModal roles={ov.roles || []} onClose={() => setBulkOpen(false)}
      onDone={() => { load(); refreshOverview(); }} />}
  </>;
}

function ManualGrantModal({ plans, onClose, onDone }) {
  const [q, setQ] = useState('');
  const [hits, setHits] = useState(null);
  const [user, setUser] = useState(null);
  const [days, setDays] = useState(30);
  const [planName, setPlanName] = useState('اشتراک دستی');
  const [extend, setExtend] = useState(true);
  const [busy, setBusy] = useState(false);
  const search = async () => {
    if (q.trim().length < 2) return;
    try { setHits((await api.subUserSearch(q.trim())).users || []); } catch (e) { toast(errText(e), 'err'); }
  };
  const grant = async () => {
    setBusy(true);
    try { await api.subGrant({ user_id: user.id, days: Number(days), plan_name: planName.trim(), extend }); toast('اشتراک فعال شد ✅'); onDone(); }
    catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  return <Modal title="👤 اعطای دستی اشتراک" onClose={onClose}>
    {!user ? <><div className="row"><input className="inp" style={{ flex: 1 }} value={q} onChange={e => setQ(e.target.value)}
      onKeyDown={e => e.key === 'Enter' && search()} placeholder="نام، یوزرنیم، شماره یا آیدی…" /><button className="btn" onClick={search} aria-label="جست‌وجوی کاربر">🔎</button></div>
      <div className="grid" style={{ gap: 6, marginTop: 8 }}>{(hits || []).map(u => <button key={u.id} className="pick" onClick={() => setUser(u)}>
        <b>{u.name}</b><span className="muted">{u.student_id || `#${u.id}`}</span></button>)}</div></> : <div className="grid" style={{ gap: 10 }}>
      <div className="panel panel-pad" style={{ background: 'var(--bg)' }}><b>{user.name}</b> <span className="code">#{user.id}</span></div>
      <div className="row">{[7, 30, 90].map(d => <button key={d} className={`btn sm ${Number(days) === d ? 'primary' : ''}`} onClick={() => setDays(d)}>{fa(d)} روز</button>)}
        <input className="inp" type="number" min="1" max="3650" style={{ width: 100 }} value={days} onChange={e => setDays(e.target.value)} /></div>
      <select className="inp" value={planName} onChange={e => setPlanName(e.target.value)}>
        <option value="اشتراک دستی">اشتراک دستی</option>{plans.map(p => <option key={p.id} value={p.name}>{p.name}</option>)}
      </select>
      <label className="row"><Switch on={extend} onChange={setExtend} /><span>تمدید روی اشتراک فعلی</span></label>
      <div className="row"><button className="btn primary" disabled={busy || Number(days) < 1} onClick={grant}>فعال‌سازی</button>
        <button className="btn" onClick={() => setUser(null)}>تغییر کاربر</button></div>
    </div>}
  </Modal>;
}

function BulkGrantModal({ roles, onClose, onDone }) {
  const [mode, setMode] = useState('list');
  const [ids, setIds] = useState('');
  const [role, setRole] = useState('');
  const [days, setDays] = useState(30);
  const [planName, setPlanName] = useState('اشتراک رایگان');
  const [extend, setExtend] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const run = async () => {
    setBusy(true); setResult(null);
    try {
      const r = await api.subGrantBulk({ mode, role: mode === 'role' ? role : null,
        identifiers: mode === 'list' ? ids.split('\n').map(x => x.trim()).filter(Boolean) : [],
        days: Number(days), plan_name: planName.trim(), extend });
      setResult(r); toast(`${fa(r.granted)} اشتراک فعال شد ✅`); onDone();
    } catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  return <Modal title="🎁 اعطای رایگان دسته‌جمعی" onClose={onClose}>
    <div className="tabs" role="tablist" aria-label="روش اعطای دسته‌جمعی"><button type="button" role="tab" aria-selected={mode === 'list'} className={`tab ${mode === 'list' ? 'on' : ''}`} onClick={() => setMode('list')}>فهرست کاربران</button>
      <button type="button" role="tab" aria-selected={mode === 'role'} className={`tab ${mode === 'role' ? 'on' : ''}`} onClick={() => setMode('role')}>براساس نقش</button></div>
    <div className="grid" style={{ gap: 10 }}>
      {mode === 'list' ? <textarea className="inp" rows={7} value={ids} onChange={e => setIds(e.target.value)}
        placeholder={'هر خط: آیدی عددی، @username، شماره دانشجویی یا نام دقیق'} /> :
        <select className="inp" value={role} onChange={e => setRole(e.target.value)}><option value="">انتخاب نقش…</option>
          {roles.filter(r => r.active !== false).map(r => <option key={r.key} value={r.key}>{r.icon} {r.label}</option>)}</select>}
      <div className="row"><input className="inp" type="number" min="1" max="3650" value={days} onChange={e => setDays(e.target.value)} />
        <input className="inp" style={{ flex: 1 }} value={planName} onChange={e => setPlanName(e.target.value)} placeholder="نام پلن" /></div>
      <label className="row"><Switch on={extend} onChange={setExtend} /><span>تمدید اشتراک موجود</span></label>
      <button className="btn primary" disabled={busy || Number(days) < 1 || (mode === 'role' ? !role : !ids.trim())} onClick={run}>
        {busy ? '⏳ در حال پردازش…' : 'اجرای اعطای دسته‌جمعی'}</button>
      {result && <div className="grid" style={{ gap: 6 }}><div className="row"><B kind="ok">موفق: {fa(result.granted)}</B><B kind={result.failed_ids?.length ? 'bad' : ''}>ناموفق: {fa(result.failed_ids?.length)}</B>
        <B kind={result.unresolved?.length ? 'warn' : ''}>پیدانشد: {fa(result.unresolved?.length)}</B></div>
        {!!result.failed_ids?.length && <div className="muted">آیدی‌های ناموفق: {result.failed_ids.slice(0, 30).join('، ')}</div>}
        {!!result.unresolved?.length && <div className="muted">ورودی‌های پیدانشده: {result.unresolved.slice(0, 30).join('، ')}</div>}</div>}
    </div>
  </Modal>;
}

// 🌊 W8/MISS-03 — مدیریت خانواده‌ی این کاربر (به‌عنوان مالک)
function FamilyBlock({ uid }) {
  const [fam, setFam] = useState(null);
  const [newUid, setNewUid] = useState('');
  const [busy, setBusy] = useState(false);
  const load = async () => { try { setFam(await api.subFamily(uid)); } catch (e) { /* پلن شخصی/بدون اشتراک */ } };
  useEffect(() => { load(); }, [uid]);
  if (!fam || Number(fam.total) <= 1) return null;
  const act = async (fn, okMsg) => {
    setBusy(true);
    try { await fn(); toast(okMsg); setNewUid(''); load(); }
    catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  return <div className="panel panel-pad" style={{ marginTop: 12 }}><b>👨‍👩‍👧 خانواده</b>
    <span className="muted"> ({fa(fam.used)} از {fa(Number(fam.total) - 1)} صندلی)</span>
    <div className="grid" style={{ gap: 6, marginTop: 8 }}>
      {(fam.members || []).filter(m => m.status === 'active').map(m => <div key={m.user_id} className="row">
        <span style={{ flex: 1 }}>👤 {m.name || `#${m.user_id}`}</span>
        <button className="btn sm" disabled={busy} onClick={() => act(() => api.subFamilyRemove(uid, m.user_id), 'عضو حذف شد')}>حذف</button>
      </div>)}
    </div>
    <div className="row" style={{ marginTop: 8 }}><input className="inp" style={{ flex: 1 }} placeholder="user_id عضو جدید…"
      value={newUid} onChange={e => setNewUid(e.target.value)} />
      <button className="btn primary sm" disabled={busy || !newUid.trim()} onClick={() => act(() => api.subFamilyAdd(uid, Number(newUid)), 'عضو اضافه شد ✅')}>➕ افزودن</button></div>
  </div>;
}

function SubscriberDrawer({ uid, plans, onClose, onChanged }) {
  const [data, setData] = useState(null);
  const [days, setDays] = useState(30);
  const [planName, setPlanName] = useState('اشتراک دستی');
  const [extend, setExtend] = useState(true);
  const [reason, setReason] = useState('');
  const [confirm, setConfirm] = useState(false);
  const load = async () => { try { setData(await api.subSubscriber(uid)); } catch (e) { toast(errText(e), 'err'); } };
  useEffect(() => { load(); }, [uid]);
  const grant = async () => {
    try { await api.subGrant({ user_id: uid, days: Number(days), plan_name: planName, extend }); toast('اشتراک به‌روزرسانی شد ✅'); load(); onChanged(); }
    catch (e) { toast(errText(e), 'err'); }
  };
  const revoke = async () => {
    setConfirm(false);
    try { await api.subRevoke(uid, reason.trim()); toast('اشتراک لغو شد'); load(); onChanged(); }
    catch (e) { toast(errText(e), 'err'); }
  };
  return <Drawer wide title="💎 پرونده اشتراک کاربر" onClose={onClose}>
    {!data ? <Loading rows={5} /> : <>
      <div className="panel panel-pad"><div className="row"><b>{data.user.name}</b><span className="code">#{uid}</span>
        <span className="spacer" />{data.subscription ? <B kind={data.subscription.status === 'active' ? 'ok' : 'warn'}>{data.subscription.status}</B> : <B>بدون اشتراک</B>}</div>
        <dl className="kv">{Object.entries({ 'شماره دانشجویی': data.user.student_id, 'ورودی': data.user.intake, 'گروه': data.user.group,
          'پلن فعلی': data.subscription?.plan_name, 'پایان': data.subscription?.end_date,
          'روز باقی': data.subscription?.days_left,
        }).filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => <React.Fragment key={k}><dt>{k}</dt><dd>{k === 'پایان' ? <FaDateTime value={v} /> : String(v)}</dd></React.Fragment>)}</dl></div>
      <div className="panel panel-pad" style={{ marginTop: 12 }}><b>➕ فعال‌سازی / تمدید</b>
        <div className="row" style={{ marginTop: 8 }}>{[7, 30, 90].map(d => <button key={d} className={`btn sm ${Number(days) === d ? 'primary' : ''}`} onClick={() => setDays(d)}>{fa(d)} روز</button>)}
          <input className="inp" type="number" min="1" max="3650" style={{ width: 90 }} value={days} onChange={e => setDays(e.target.value)} />
          <select className="inp" value={planName} onChange={e => setPlanName(e.target.value)}><option>اشتراک دستی</option>{plans.map(p => <option key={p.id}>{p.name}</option>)}</select>
          <label className="row"><Switch on={extend} onChange={setExtend} /> تمدید</label>
          <button className="btn primary" onClick={grant}>ثبت</button></div>
        {data.subscription?.status === 'active' && <div className="row" style={{ marginTop: 10 }}><input className="inp" style={{ flex: 1 }} value={reason}
          onChange={e => setReason(e.target.value)} placeholder="دلیل لغو…" /><button className="btn danger" disabled={reason.trim().length < 2} onClick={() => setConfirm(true)}>لغو اشتراک</button></div>}
      </div>
      <FamilyBlock uid={uid} />
      <div className="sec" style={{ marginTop: 'var(--sp4)' }}>
        <div className="sec-main"><div className="sec-title">📜 تاریخچه پرداخت</div></div>
      </div>
      {!(data.payments || []).length ? <Empty text="پرداختی ثبت نشده" /> : <div className="grid" style={{ gap: 6 }}>
        {data.payments.map(p => <div key={p.id} className="panel panel-pad row"><B kind={p.status === 'approved' ? 'ok' : p.status === 'rejected' ? 'bad' : 'warn'}>{p.status}</B>
          <span style={{ flex: 1 }}>{p.plan_name}</span><span>{money(p.final_price)}</span><FaDateTime value={p.submitted_at} /></div>)}</div>}
    </>}
    {confirm && <Confirm danger text={`لغو اشتراک «${data?.user?.name}» با دلیل «${reason}»؟`} onYes={revoke} onNo={() => setConfirm(false)} />}
  </Drawer>;
}

function DiscountsPanel({ plans, refreshOverview }) {
  const [items, setItems] = useState(null);
  const [err, setErr] = useState('');
  const [addOpen, setAddOpen] = useState(false);
  const [cloneSeed, setCloneSeed] = useState(null);
  const [detail, setDetail] = useState(null);
  const [del, setDel] = useState(null);
  const load = async () => { setErr(''); try { setItems((await api.discounts()).discounts || []); } catch (e) { setErr(errText(e)); } };
  useEffect(() => { load(); }, []);
  const toggle = async c => { try { await api.discountToggle(c.code); toast('وضعیت کد تغییر کرد'); load(); } catch (e) { toast(errText(e), 'err'); } };
  const remove = async c => { try { await api.discountDelete(c.code); toast('کد حذف شد'); load(); refreshOverview(); } catch (e) { toast(errText(e), 'err'); } };
  const planMap = Object.fromEntries(plans.map(p => [String(p.id), p.name]));
  if (err) return <ErrorState error={err} onRetry={load} />;
  return <>
    <div className="row" style={{ marginBottom: 12 }}><div><b>🎁 کدهای تخفیف و کمپین</b>
      <div className="muted">هدف پلن، ظرفیت، محدودیت هر کاربر، آمار مالی و انتشار هدفمند</div></div><span className="spacer" />
      <button className="btn primary" onClick={() => { setCloneSeed(null); setAddOpen(true); }}>➕ کد جدید</button></div>
    {!items ? <Loading rows={5} /> : <div className="grid g2">{items.map(c => <div key={c.code} className="panel panel-pad">
      <div className="row"><span className="code" style={{ fontSize: 'var(--fs-section)', fontWeight: 800 }}>{c.code}</span><B kind="purple">{fa(c.percent)}٪</B>
        <span className="spacer" /><B kind={c.active ? 'ok' : 'bad'}>{c.active ? 'فعال' : 'غیرفعال'}</B></div>
      <div className="row" style={{ marginTop: 8, flexWrap: 'wrap' }}><B>مصرف {fa(c.used_count)} / {c.max_uses ? fa(c.max_uses) : '∞'}</B>
        <B>هر کاربر: {c.per_user_limit ? fa(c.per_user_limit) : '∞'}</B><B>{c.expires_at ? <FaDateTime value={c.expires_at} /> : 'بدون انقضا'}</B></div>
      <div className="muted" style={{ marginTop: 7 }}>پلن‌ها: {(c.target_plan_ids || []).length ? c.target_plan_ids.map(id => planMap[String(id)] || id).join('، ') : 'همه‌ی پلن‌ها'}</div>
      <div className="row" style={{ marginTop: 10 }}><button className="btn sm" onClick={() => setDetail(c)}>📊 آمار و کمپین</button>
        <button className="btn sm" onClick={() => { setCloneSeed(c); setAddOpen(true); }}>📄 کپی</button>
        <button className="btn sm" onClick={() => toggle(c)} aria-label={`${c.active ? 'غیرفعال‌کردن' : 'فعال‌کردن'} کد ${c.code}`}>{c.active ? '⏸' : '▶'}</button><button className="btn sm danger" onClick={() => setDel(c)} aria-label={`حذف کد ${c.code}`}>🗑</button></div>
    </div>)}{!items.length && <Empty text="کد تخفیفی نیست" />}</div>}
    {addOpen && <DiscountAddModal plans={plans} seed={cloneSeed} onClose={() => { setAddOpen(false); setCloneSeed(null); }} onDone={() => { setAddOpen(false); setCloneSeed(null); load(); refreshOverview(); }} />}
    {detail && <DiscountDrawer item={detail} onClose={() => setDetail(null)} />}
    {del && <Confirm danger text={`حذف کد «${del.code}»؟ snapshot پرداخت‌های قبلی حفظ می‌شود.`}
      onYes={async () => { const c = del; setDel(null); await remove(c); }} onNo={() => setDel(null)} />}
  </>;
}

function DiscountAddModal({ plans, seed, onClose, onDone }) {
  const [f, setF] = useState({ code: seed ? `${seed.code}_COPY` : '', percent: seed?.percent || 10, max_uses: seed?.max_uses || 0,
    per_user_limit: seed?.per_user_limit || 0, expires_at: seed?.expires_at || '', target_plan_ids: seed?.target_plan_ids || [] });
  const [busy, setBusy] = useState(false);
  const togglePlan = id => setF(x => ({ ...x, target_plan_ids: x.target_plan_ids.includes(id) ? x.target_plan_ids.filter(v => v !== id) : [...x.target_plan_ids, id] }));
  const save = async () => {
    setBusy(true);
    try { await api.discountAdd({ ...f, code: f.code.trim(), percent: Number(f.percent), max_uses: Number(f.max_uses),
      per_user_limit: Number(f.per_user_limit), expires_at: f.expires_at || null }); toast('کد تخفیف ساخته شد ✅'); onDone(); }
    catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  return <Modal title={seed ? `📄 کپی کد ${seed.code}` : '➕ کد تخفیف جدید'} onClose={onClose}><div className="grid" style={{ gap: 10 }}>
    <div className="row"><input className="inp" dir="ltr" placeholder="CODE" value={f.code} onChange={e => setF({ ...f, code: e.target.value.toUpperCase() })} />
      <label className="fld"><span>درصد</span><input className="inp" type="number" min="1" max="100" value={f.percent} onChange={e => setF({ ...f, percent: e.target.value })} /></label></div>
    <div className="row"><label className="fld"><span>ظرفیت کل (۰=نامحدود)</span><input className="inp" type="number" min="0" value={f.max_uses} onChange={e => setF({ ...f, max_uses: e.target.value })} /></label>
      <label className="fld"><span>سقف هر کاربر (۰=نامحدود)</span><input className="inp" type="number" min="0" value={f.per_user_limit} onChange={e => setF({ ...f, per_user_limit: e.target.value })} /></label>
      <label className="fld"><span>انقضا به وقت تهران</span><PersianDatePicker value={f.expires_at} onChange={value => setF({ ...f, expires_at: value })} ariaLabel="تاریخ انقضای شمسی" /></label></div>
    <div><div className="muted" style={{ marginBottom: 6 }}>پلن‌های هدف — خالی یعنی همه</div><div className="row">{plans.map(p => <label key={p.id} className={`badge ${f.target_plan_ids.includes(p.id) ? 'acc' : ''}`}>
      <input type="checkbox" checked={f.target_plan_ids.includes(p.id)} onChange={() => togglePlan(p.id)} /> {p.name}</label>)}</div></div>
    <div className="row"><button className="btn primary" disabled={busy || f.code.trim().length < 2 || Number(f.percent) < 1} onClick={save}>ساخت کد</button>
      <button className="btn" onClick={onClose}>انصراف</button></div>
  </div></Modal>;
}

function DiscountDrawer({ item, onClose }) {
  const [stats, setStats] = useState(null);
  const [preview, setPreview] = useState(null);
  const [runs, setRuns] = useState(null);
  const [target, setTarget] = useState('all');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const load = async () => {
    try { const [s, p, r] = await Promise.all([api.discountStats(item.code), api.discountPreview(item.code), api.discountBroadcasts(item.code)]);
      setStats(s); setPreview(p); setRuns(r.broadcasts || []); }
    catch (e) { toast(errText(e), 'err'); }
  };
  useEffect(() => { load(); }, [item.code]);
  const broadcast = async () => {
    setBusy(true);
    try { const r = await api.discountBroadcast(item.code, { target, title: title.trim() || null, description: description.trim() || null });
      toast(`کمپین برای ${fa(r.total)} نفر شروع شد 📢`); load(); }
    catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  const cancel = async bid => { try { await api.discountBroadcastCancel(item.code, bid); toast('کمپین متوقف شد'); load(); } catch (e) { toast(errText(e), 'err'); } };
  return <Drawer wide title={`🎁 آمار و کمپین — ${item.code}`} onClose={onClose}>
    {!stats ? <Loading rows={4} /> : <>
      <KpiGrid>
        <KpiCard icon="🎟" label="مصرف" value={fa(stats.used_count)} />
        <KpiCard icon="⏳" label="باقی‌مانده"
                 value={stats.remaining_uses == null ? 'نامحدود' : fa(stats.remaining_uses)} />
        <KpiCard tone="ok" icon="💰" label="درآمد با تخفیف"
                 value={money(stats.payments?.revenue)} />
        <KpiCard tone="warn" icon="📉" label="مبلغ تخفیف"
                 value={money(stats.payments?.discount_given)} />
      </KpiGrid>
      <div className="panel panel-pad" style={{ marginTop: 12 }}><b>👁 پیش‌نمایش پیام</b>
        <div style={{ whiteSpace: 'pre-wrap', marginTop: 8, color: 'var(--txt2)', maxHeight: 220, overflowY: 'auto' }}>{preview?.text || '—'}</div></div>
      <div className="panel panel-pad" style={{ marginTop: 12 }}><b>📢 انتشار کمپین</b>
        <div className="row" style={{ marginTop: 8 }}><select className="inp" value={target} onChange={e => setTarget(e.target.value)}>
          <option value="all">همه کاربران</option><option value="subscribers">مشترکین</option><option value="no_sub">بدون اشتراک فعال</option></select>
          <input className="inp" style={{ flex: 1 }} value={title} onChange={e => setTitle(e.target.value)} placeholder="عنوان سفارشی (اختیاری)" /></div>
        <textarea className="inp" rows={2} style={{ width: '100%', marginTop: 8 }} value={description} onChange={e => setDescription(e.target.value)} placeholder="توضیح سفارشی (اختیاری)" />
        <button className="btn primary" style={{ marginTop: 8 }} disabled={busy || item.active === false} onClick={broadcast}>{busy ? '⏳ شروع…' : '📢 شروع انتشار'}</button></div>
      <div className="row" style={{ marginTop: 16 }}><div className="h1" style={{ fontSize: 'var(--fs-section)' }}>تاریخچه انتشار</div>
        <span className="spacer" /><button className="btn sm" onClick={load}>↻ تازه‌سازی وضعیت</button></div>
      {!(runs || []).length ? <Empty text="انتشاری ثبت نشده" /> : <div className="grid" style={{ gap: 6 }}>{runs.map(r => <div key={r.broadcast_id} className="panel panel-pad">
        <div className="row"><B kind={r.status === 'completed' ? 'ok' : r.status === 'sending' ? 'warn' : 'bad'}>{r.status}</B><B>{r.target}</B>
          <span className="spacer" /><FaDateTime value={r.created_at} />{r.status === 'sending' && <button className="btn sm danger" onClick={() => cancel(r.broadcast_id)}>توقف</button>}</div>
        <div className="row" style={{ marginTop: 6 }}><span>کل {fa(r.total)}</span><span>✅ {fa(r.sent)}</span><span>❌ {fa(r.failed)}</span><span>🚫 {fa(r.blocked)}</span></div>
      </div>)}</div>}
    </>}
  </Drawer>;
}

// ════════════════════════════════════════════════════════════════
// 💰 W6 — کیف پول‌ها: لیست + جزئیات ledger + تنظیم دستی (audit‌شده)
// موجودی همیشه از بک‌اند می‌آید؛ فرانت هیچ عددی را تعیین نمی‌کند.
// ════════════════════════════════════════════════════════════════
const TX_KIND = {
  refund_credit: ['بازگشت وجه', 'ok'],
  subscription_purchase: ['خرید اشتراک با کیف پول', 'acc'],
  admin_credit: ['افزایش دستی', 'warn'],
  admin_debit: ['کسر دستی', 'bad'],
  reversal: ['اصلاح مالی (جبرانی)', 'warn'],
  topup_credit: ['شارژ کیف پول (رسید بانکی)', 'ok'],
};

function WalletsPanel({ initial = {} }) {
  const [q, setQ] = useState(initial.q || '');
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const [selected, setSelected] = useState(null);
  const limit = 30;
  const load = () => {
    setErr('');
    api.subWallets({ q, skip: (page - 1) * limit, limit }).then(setData).catch(e => setErr(errText(e)));
  };
  useEffect(load, [page]);
  useEffect(() => { const t = setTimeout(() => { setPage(1); load(); }, q ? 250 : 0); return () => clearTimeout(t); }, [q]);
  return <div className="panel panel-pad" style={{ marginTop: 12 }}>
    <div className="row" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
      <b>👛 کیف پول‌ها</b>
      {data && <B kind="acc">{fa(data.total)} کیف پول</B>}
      <span className="spacer" />
      <input className="inp" style={{ width: 220 }} placeholder="جست‌وجو: نام / شماره دانشجویی / آیدی"
        value={q} onChange={e => setQ(e.target.value)} />
      <button className="btn sm" onClick={load}>↻</button>
      <button className="btn sm" onClick={() => api.exportWalletCsv(q && /^\d+$/.test(q) ? { user_id: q } : {})} title="خروجی ledger کامل (۲۰۰۰ ردیف آخر)">⬇️ خروجی CSV ledger</button>
    </div>
    <div className="panel panel-pad data-quality-note" style={{ marginBottom: 10 }}>
      <B kind="acc">کیف پول یعنی چه؟</B>
      <span>موجودی داخلی دانشجو (تومان). بازگشت وجه به‌جای درگاه به کیف پول می‌نشیند و دانشجو می‌تواند با آن اشتراک بخرد. هر تغییر موجودی یک تراکنش ledger با مرجع مالی دارد.</span>
    </div>
    {err && <ErrorState error={err} onRetry={load} />}
    {!err && !data && <Loading rows={4} />}
    {data && !data.items.length && <Empty icon="👛" text="کیف پولی با این جست‌وجو پیدا نشد" />}
    {data && !!data.items.length && <div className="q-list">
      {data.items.map(w => <button key={w.user_id} className="panel panel-pad operation-card" style={{ textAlign: 'right' }} onClick={() => setSelected(w)}>
        <span className="operation-icon">👛</span>
        <span className="operation-body">
          <b>{w.user_name || `کاربر #${fa(w.user_id)}`}</b>
          <span className="muted">{w.student_id ? `🎓 ${w.student_id} · ` : ''}آخرین تغییر: {w.updated_at ? <FaDateTime value={w.updated_at} /> : '—'}</span>
        </span>
        <B kind={w.balance > 0 ? 'ok' : ''}>{money(w.balance)}</B><span>‹</span>
      </button>)}
    </div>}
    {data && data.total > limit && <div className="row" style={{ marginTop: 10 }}>
      <button className="btn sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>‹ قبلی</button>
      <span className="muted">صفحه {fa(page)} از {fa(Math.ceil(data.total / limit))}</span>
      <span className="spacer" />
      <button className="btn sm" disabled={page * limit >= data.total} onClick={() => setPage(p => p + 1)}>بعدی ›</button>
    </div>}
    {selected && <WalletDrawer uid={selected.user_id} onClose={() => setSelected(null)} onChanged={load} />}
  </div>;
}

function WalletDrawer({ uid, onClose, onChanged }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [askAdjust, setAskAdjust] = useState(false);
  const [amount, setAmount] = useState('');
  const [reason, setReason] = useState('');
  const [txConfirm, setTxConfirm] = useState(null);
  const load = () => { setErr(''); api.subWalletDetail(uid, { limit: 30 }).then(setData).catch(e => setErr(errText(e))); };
  useEffect(load, [uid]);
  const adjust = async () => {
    const amt = parseInt(String(amount).replace(/[^\d-]/g, ''), 10);
    if (!amt || Math.abs(amt) > 50000000) { toast('مبلغ نامعتبر است', 'err'); return; }
    setBusy(true);
    try {
      const r = await api.subWalletAdjust(uid, { amount: amt, reason: reason.trim(), confirm: true });
      toast(`موجودی پس از تنظیم: ${money(r.balance_after)}`, 'ok');
      setAskAdjust(false); setAmount(''); setReason(''); load(); onChanged?.();
    } catch (e) { toast(errText(e), 'err'); }
    finally { setBusy(false); }
  };
  const s = data?.summary;
  return <Drawer wide title={`👛 کیف پول — ${s?.user_name || `کاربر #${fa(uid)}`}`} onClose={onClose}>
    {err && <ErrorState error={err} onRetry={load} />}
    {!err && !data && <Loading rows={4} />}
    {data && <>
      <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
        <B kind={s.balance > 0 ? 'ok' : ''}>موجودی: {money(s.balance)}</B>
        <B kind="ok">جمع اعتبارها: {money(s.credits_total)}</B>
        <B kind="bad">جمع کسرها: {money(s.debits_total)}</B>
        <span className="spacer" />
        <button className="btn sm" disabled={busy} onClick={() => setAskAdjust(v => !v)}>⚖️ تنظیم دستی موجودی</button>
      </div>
      {askAdjust && <div className="q-form">
        <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
          <input className="inp" style={{ width: 160 }} placeholder="مبلغ (منفی = کسر)" value={amount} onChange={e => setAmount(e.target.value)} />
          <input className="inp" style={{ flex: 1, minWidth: 180 }} placeholder="دلیل (اجباری — در حسابرسی ثبت می‌شود)" value={reason} onChange={e => setReason(e.target.value)} />
        </div>
        <div className="row" style={{ marginTop: 8, gap: 8 }}>
          <button className="btn sm ok" disabled={busy || reason.trim().length < 3} onClick={() => adjust()}>💾 ثبت تنظیم</button>
          <span className="muted">⚠️ این یک اقدام مالی حساس است: دلیل + تأیید + حسابرسی بحرانی الزامی است.</span>
        </div>
      </div>}
      <div className="muted" style={{ margin: '12px 0 6px', fontSize: 'var(--fs-label)' }}>تراکنش‌ها ({fa(data.tx_total)}):</div>
      {!data.transactions.length ? <Empty icon="✅" text="تراکنشی ثبت نشده" /> :
        <div className="q-list">
          {data.transactions.map(t => {
            const [label, kind] = TX_KIND[t.type] || [t.label || t.type, 'acc'];
            const pending = t.status === 'pending';
            return <div key={t.id} className={`q-issue ${pending ? 'q-issue--warning' : 'q-issue--info'}`}>
              <div className="q-issue-head">
                <span className="q-issue-icon">{pending ? '⏳' : t.direction === 'credit' ? '➕' : '➖'}</span>
                <div style={{ flex: 1 }}>
                  <b>{t.label || label}</b>
                  <div className="muted" style={{ marginTop: 2 }}>
                    {pending
                      ? <>معلق — احتمال کرش بین مراحل؛ اثر مالی هنوز قطعی نیست · <FaDateTime value={t.at} /></>
                      : <>موجودی پس از تراکنش: {money(t.balance_after)} · <FaDateTime value={t.at} /></>}
                  </div>
                </div>
                {pending
                  ? <button className="btn sm" disabled={busy === `tx-${t.id}`} onClick={() => setTxConfirm(t)}>⏳ تعیین تکلیف</button>
                  : <B kind={t.direction === 'credit' ? 'ok' : 'bad'}>
                      {t.direction === 'credit' ? '+' : '−'}{money(t.amount)}
                    </B>}
              </div>
              <details className="q-tech"><summary>جزئیات فنی</summary>
                <div className="code muted">{t.id} · {t.reference_type || ''}:{t.reference_id || ''} · actor {t.actor_id}</div>
              </details>
            </div>;
          })}
        </div>}
    </>}
    {txConfirm && <Modal title="⏳ تعیین تکلیف تراکنش معلق" onClose={() => setTxConfirm(null)}>
      <p className="muted" style={{ marginTop: 0 }}>
        تراکنش <b>{txConfirm.label || txConfirm.type}</b> در حالت معلق است (احتمال کرش بین مراحل).
        بک‌اند با بررسی ledger تشخیص می‌دهد اثر مالی قبلاً اعمال شده یا نه — هیچ‌وقت اثر دوم ساخته نمی‌شود.
      </p>
      <div className="row q-missing" style={{ marginBottom: 10 }}>
        <B kind="acc">👤 {txConfirm.label || txConfirm.type}</B>
        <B kind={txConfirm.direction === 'credit' ? 'ok' : 'bad'}>{txConfirm.direction === 'credit' ? '+' : '−'}{money(txConfirm.amount)}</B>
      </div>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <button className="btn ok" disabled={!!busy} onClick={async () => {
          const tx = txConfirm; setBusy(`tx-${tx.id}`);
          try {
            const r = await api.subWalletTxResolve(tx.id, 'complete');
            toast(r.resolution === 'applied_now' ? 'اثر تراکنش همین حالا اتمیک اعمال شد ✅' : 'اثر مالی قبلاً اعمال شده بود — فقط نشان‌گذاری شد ✅', 'ok');
            setTxConfirm(null); load(); onChanged?.();
          } catch (e) { toast(errText(e), 'err'); }
          finally { setBusy(''); }
        }}>✅ تکمیل — اعمال اثر اگر نشده</button>
        <button className="btn danger" disabled={!!busy} onClick={async () => {
          const tx = txConfirm; setBusy(`tx-${tx.id}`);
          try {
            const r = await api.subWalletTxResolve(tx.id, 'cancel');
            toast('تراکنش لغو شد — در صورت لزوم جبران مالی ثبت شد ✅', 'ok');
            setTxConfirm(null); load(); onChanged?.();
          } catch (e) { toast(errText(e), 'err'); }
          finally { setBusy(''); }
        }}>🚫 لغو — جبران اگر لازم است</button>
        <button className="btn" onClick={() => setTxConfirm(null)}>انصراف</button>
      </div>
    </Modal>}
  </Drawer>;
}

// ════════════════════════════════════════════════════════════════
// 💳 W6 — درگاه زرین‌پال: وضعیت + تنظیم مرچنت/سندباکس/کالبک + تست اتصال
// تنظیمات DB-backed است؛ ذخیره بدون ری‌استارت اعمال می‌شود (کش ۳۰ ثانیه‌ای).
// مرچنت هرگز کامل برنمی‌گردد (masked)؛ فقط با تایپ مقدار جدید جایگزین می‌شود.
// ════════════════════════════════════════════════════════════════
function GatewayPanel() {
  const [cfg, setCfg] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testRes, setTestRes] = useState(null);
  const [mid, setMid] = useState('');
  const [showMid, setShowMid] = useState(false);
  const [sandbox, setSandbox] = useState(true);
  const [callbackUrl, setCallbackUrl] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [confirmClear, setConfirmClear] = useState(false);

  const load = async () => {
    setErr(''); setTestRes(null);
    try {
      const c = await api.gatewayZarinpal();
      setCfg(c);
      setMid('');
      setSandbox(!!c.sandbox);
      setCallbackUrl(c.callback_url || '');
      setEnabled(c.enabled !== false);
    } catch (e) { setErr(errText(e)); }
  };
  useEffect(() => { load(); }, []);

  if (err) return <ErrorState error={err} onRetry={load} />;
  if (!cfg) return <Loading rows={5} />;

  const dirty = mid.trim() !== '' || sandbox !== !!cfg.sandbox
    || (callbackUrl.trim() || '') !== (cfg.callback_url || '')
    || enabled !== !!cfg.enabled;

  const save = async () => {
    setBusy(true);
    try {
      const body = { sandbox, callback_url: callbackUrl.trim(), enabled };
      // مرچنت فقط وقتی ارسال می‌شود که ادمین مقدار جدید تایپ کرده باشد
      if (mid.trim()) body.merchant_id = mid.trim();
      await api.gatewayZarinpalUpdate(body);
      toast('تنظیمات درگاه ذخیره شد ✅');
      await load();
    } catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };

  const runTest = async () => {
    setTesting(true); setTestRes(null);
    try {
      const r = await api.gatewayZarinpalTest();
      setTestRes(r);
      toast(r.message || 'تست موفق بود ✅', 'ok');
    } catch (e) { toast(errText(e), 'err'); }
    setTesting(false);
  };

  const clearMerchant = async () => {
    setConfirmClear(false); setBusy(true);
    try {
      await api.gatewayZarinpalUpdate({ merchant_id: '' });
      toast('مرچنت حذف شد — درگاه به حالت آزمایشی (mock) برگشت');
      await load();
    } catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };

  return <>
    {/* وضعیت فعلی درگاه */}
    <div className="panel panel-pad">
      <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
        <b>💳 وضعیت درگاه زرین‌پال</b>
        <span className="spacer" />
        <button className="btn sm" onClick={load}>↻ تازه‌سازی</button>
      </div>
      <div className="row" style={{ flexWrap: 'wrap', gap: 8, marginTop: 10 }}>
        <B kind={cfg.enabled ? 'ok' : 'bad'}>{cfg.enabled ? '✅ درگاه فعال' : '⏸ درگاه غیرفعال'}</B>
        <B kind={cfg.sandbox ? 'warn' : 'acc'}>{cfg.sandbox ? '🧪 حالت سندباکس (تست)' : '🌐 حالت اصلی (واقعی)'}</B>
        {cfg.merchant_id_set
          ? <B kind="ok">🔑 مرچنت ثبت شده: <span dir="ltr">{cfg.merchant_id_masked}</span></B>
          : <B kind="warn">🔑 مرچنت ثبت نشده</B>}
        {cfg.is_mock
          ? <B kind="warn">⚠️ حالت آزمایشی (mock) — پرداخت واقعی انجام نمی‌شود</B>
          : <B kind="ok">🔗 متصل به زرین‌پال واقعی</B>}
      </div>
      {cfg.is_mock && <div className="panel panel-pad data-quality-note" style={{ marginTop: 10 }}>
        <B kind="warn">حالت آزمایشی یعنی چه؟</B>
        <span>چون مرچنت واقعی ثبت نشده، پرداخت‌ها شبیه‌سازی می‌شوند (authority با پیشوند TEST). برای دریافت پول واقعی، مرچنت ۳۶ کاراکتری پنل زرین‌پال را ثبت و سندباکس را خاموش کنید.</span>
      </div>}
    </div>

    <div className="grid g2" style={{ marginTop: 14 }}>
      {/* فرم تنظیمات */}
      <div className="panel panel-pad">
        <b>⚙️ تنظیمات درگاه</b>
        <div className="grid" style={{ gap: 10, marginTop: 12 }}>
          <label className="fld"><span>مرچنت‌کد (Merchant ID)</span>
            <div className="row" style={{ gap: 6 }}>
              <input className="inp" dir="ltr" style={{ flex: 1 }}
                type={showMid ? 'text' : 'password'}
                value={mid} onChange={e => setMid(e.target.value)}
                placeholder={cfg.merchant_id_masked || 'مثل 8a7f3b2c-… (۳۶ کاراکتر)'} />
              <button className="btn sm" onClick={() => setShowMid(v => !v)}
                aria-label={showMid ? 'پنهان‌کردن مرچنت' : 'نمایش مرچنت'}>{showMid ? '🙈' : '👁'}</button>
            </div>
            <span className="muted" style={{ fontSize: 'var(--fs-label)' }}>
              {cfg.merchant_id_set
                ? 'مرچنت فعلی ذخیره است — خالی بماند یعنی بدون تغییر.'
                : 'هنوز مرچنتی ثبت نشده — بدون آن درگاه در حالت آزمایشی کار می‌کند.'}
            </span>
          </label>
          <div className="row" style={{ alignItems: 'flex-start' }}>
            <Switch on={enabled} disabled={busy} onChange={setEnabled} />
            <div><b>فعال‌بودن درگاه</b>
              <div className="muted">خاموش: دکمه پرداخت آنلاین در مینی‌اپ نمایش داده نمی‌شود.</div></div>
          </div>
          <div className="row" style={{ alignItems: 'flex-start' }}>
            <Switch on={sandbox} disabled={busy} onChange={setSandbox} />
            <div><b>حالت سندباکس (تست زرین‌پال)</b>
              <div className="muted">روشن: پرداخت در محیط تست زرین‌پال؛ خاموش: درگاه واقعی و کسر پول واقعی.</div></div>
          </div>
          <label className="fld"><span>آدرس بازگشت (Callback URL)</span>
            <input className="inp" dir="ltr" value={callbackUrl}
              onChange={e => setCallbackUrl(e.target.value)}
              placeholder="مثل https://yourdomain.ir/payment/verify" />
            <span className="muted" style={{ fontSize: 'var(--fs-label)' }}>
              خالی بماند یعنی پیش‌فرض خودکار (همان دامنه مینی‌اپ + ‎/payment/verify‎). باید با https شروع شود.
            </span>
          </label>
          <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
            <button className="btn primary" disabled={busy || !dirty} onClick={save}>
              {busy ? '⏳ …' : '💾 ذخیره تنظیمات'}</button>
            <button className="btn" disabled={testing || busy} onClick={runTest}>
              {testing ? '⏳ …' : '🔌 تست اتصال'}</button>
            {cfg.merchant_id_set && <button className="btn sm danger" disabled={busy}
              onClick={() => setConfirmClear(true)}>🗑 حذف مرچنت</button>}
          </div>
          {testRes && <div className="panel panel-pad" style={{ background: 'var(--bg)' }}>
            <B kind={testRes.mock ? 'warn' : 'ok'}>{testRes.mock ? '🧪 نتیجه تست (mock)' : '✅ نتیجه تست'}</B>
            <div style={{ marginTop: 6 }}>{testRes.message}</div>
          </div>}
        </div>
      </div>

      {/* راهنما */}
      <div className="panel panel-pad">
        <b>📖 راهنمای اتصال زرین‌پال</b>
        <ol className="muted" style={{ paddingInlineStart: 18, lineHeight: 2 }}>
          <li>در <b>پنل زرین‌پال</b> یک درگاه پرداخت بسازید و <b>مرچنت‌کد ۳۶ کاراکتری</b> را کپی کنید.</li>
          <li>مرچنت را در فرم روبه‌رو وارد و ذخیره کنید.</li>
          <li>برای تست، <b>سندباکس را روشن</b> نگه دارید؛ بعد از اطمینان، آن را <b>خاموش</b> کنید تا پول واقعی جابه‌جا شود.</li>
          <li>با دکمه <b>«تست اتصال»</b> از آماده‌بودن درگاه مطمئن شوید.</li>
        </ol>
        <div className="panel panel-pad data-quality-note">
          <B kind="acc">نکته‌های فنی</B>
          <span>مبلغ پلن‌ها به تومان است و خودکار ×۱۰ به ریال تبدیل می‌شود. ذخیره تنظیمات بدون ری‌استارت اعمال می‌شود (حداکثر ۳۰ ثانیه تأخیر کش). هر تغییر با شدت بالا در حسابرسی ثبت می‌شود.</span>
        </div>
        {cfg.docs_url && <div style={{ marginTop: 10 }}>
          <a className="btn sm" href={cfg.docs_url} target="_blank" rel="noreferrer">📚 مستندات زرین‌پال ↗</a>
        </div>}
      </div>
    </div>

    {confirmClear && <Confirm danger
      text="مرچنت حذف شود و درگاه به حالت آزمایشی (mock) برگردد؟ پرداخت‌های واقعی تا ثبت مرچنت جدید ممکن نخواهد بود."
      onYes={clearMerchant} onNo={() => setConfirmClear(null)} />}
  </>;
}
