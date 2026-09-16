import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { api, errText } from '../api.js';
import {
  B, Confirm, DataTable, Empty, ErrorState, Field, FaDateTime, KeyValue,
  KeyValueGrid, KpiCard, KpiGrid, Loading, Modal, NoPerm, PageHeader,
  SectionHeader, StatusBadge, Switch, Tabs, toast,
} from '../ui.jsx';

// 💍 رینگ استریت — پنل نظارت (§۳۲، §۶۶..§۷۴)
// همه‌ی داده‌ها از /api/ring/* می‌آیند و همه‌ی اکشن‌ها در بک‌اند با مجوز
// ring.manage + audit دوبل (ring_admin_audit + audit_logs) ثبت می‌شوند.
// این صفحه عمداً هیچ محتوای گفت‌وگویی نشان نمی‌دهد؛ فقط شواهدِ گزارش‌ها.

const TABS = [
  ['overview', '📊 نمای کلی'], ['queue', '⏳ صف'], ['chats', '💬 گفت‌وگوها'],
  ['reports', '🚩 گزارش‌ها'], ['blocks', '🚫 مسدودسازی‌ها'], ['users', '👤 کاربران'],
  ['debug', '🔍 بررسی مچ'], ['rules', '📜 قوانین'],
  ['settings', '⚙️ تنظیمات'], ['analytics', '📈 تحلیل'], ['audit', '🧭 حسابرسی'],
];

// §۴۵ — سه حالت از یک منبع حقیقت (Mongo)؛ هیچ flag سخت‌کدشده‌ای در UI نیست
const STATE_OPTS = [
  ['active', '🟢 فعال'], ['maintenance', '🟡 نگهداری'], ['disabled', '🔴 غیرفعال'],
];
const STATE_HINT = {
  active: 'صف و گفت‌وگوها عادی کار می‌کنند.',
  maintenance: 'گفت‌وگوهای جاری تمام می‌شوند؛ جفت تازه ساخته نمی‌شود.',
  disabled: 'دکمهٔ رینگ از منوی همه حذف می‌شود و /ring پیام خاموشی می‌دهد.',
};

const fa = (n) => Number(n || 0).toLocaleString('fa-IR');
const MODE = { serious: '💍 جدی', fun: '🎭 فان' };
const PSTATUS = { active: 'فعال', paused: '⛔ محدود', banned: 'بن', deleted: 'حذف‌شده' };
const GENDER = { female: 'دختر', male: 'پسر', undisclosed: 'نامشخص' };

// §DW2 — `Kpi` و `Stat` محلی حذف شدند.
//
// هر دو کارِ primitiveهای مشترک را با فاصله و اندازه‌های دستی تکرار
// می‌کردند. بدتر اینکه `Stat` محلی با `Stat` مشترک هم‌نام بود ولی
// مفهومِ دیگری داشت (ردیفِ ساده در برابر کارتِ سنجه) — خواننده فکر
// می‌کرد یکی‌اند. حالا: KpiCard برای کارت، KeyValue برای ردیف.

export default function RingStreet({ me }) {
  const [tab, setTab] = useState('overview');
  const [ov, setOv] = useState(null);
  const [box, setBox] = useState({});
  const [err, setErr] = useState('');
  const [noPerm, setNoPerm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState('');
  const [rStat, setRStat] = useState('pending');
  const [drawer, setDrawer] = useState(null);
  const [edit, setEdit] = useState(null);
  const [force, setForce] = useState(null);
  const [confirmEnd, setConfirmEnd] = useState(null);
  const [repairing, setRepairing] = useState('');
  const [killMode, setKillMode] = useState('soft');

  const load = useCallback(async () => {
    setErr('');
    try {
      const o = await api.ringOverview();
      setOv(o);
      if (tab === 'queue') setBox(await api.ringQueue({ limit: 120 }));
      else if (tab === 'chats') setBox(await api.ringSessions({ status: 'active', page, size: 25 }));
      else if (tab === 'reports') setBox(await api.ringReports({ status: rStat || '', page, size: 25 }));
      else if (tab === 'users') setBox(await api.ringProfiles({ q, page, size: 25 }));
      else if (tab === 'blocks') setBox(await api.ringBlocks({ limit: 150 }));
      else if (tab === 'rules') setBox(await api.ringRules());
      else if (tab === 'settings') setBox(await api.ringSettings());
      else if (tab === 'analytics') {
        const base = await api.ringAnalytics(7);
        // §۴۹ (V6) — اگر بک‌اندِ دیپلوی‌شده هنوز /api/ring/metrics را نداشته باشد،
        // پنل نباید بشکند؛ فقط همان بخش مخفی می‌ماند.
        let cycle = null;
        try { cycle = await api.ringMetrics(7); } catch (_) { cycle = null; }
        setBox({ ...base, cycle });
      }
      else if (tab === 'audit') setBox(await api.ringAuditList(120));
      else setBox({});
      setEdit(null);
    } catch (e) {
      if (e.status === 403) setNoPerm(true); else setErr(errText(e));
    }
  }, [tab, page, q, rStat]);

  useEffect(() => { load(); }, [load]);

  const act = async (fn, ok) => {
    setBusy(true);
    try { await fn(); if (ok) toast(ok); await load(); }
    catch (e) { toast(errText(e), 'bad'); }
    finally { setBusy(false); }
  };

  const live0 = (ov && ov.live) || {};
  const nh = live0.notify_health || {};
  const rows = box.sessions || box.reports || box.profiles || box.queue || box.blocks || box.audit || [];

  const cols = useMemo(() => {
    if (tab === 'queue') return [
      { k: 'uid', label: 'کاربر', render: r => <span className="code">{fa(r.uid)}</span> },
      { k: 'anon', label: 'ناشناس', render: r => <B kind="acc">#{r.anon || '—'}</B> },
      { k: 'mode', label: 'حالت', render: r => MODE[r.mode] || r.mode || '—' },
      { k: 'status', label: 'وضعیت', render: r => <B>{r.status}</B> },
      { k: 'wait', label: 'انتظار', render: r => (r.wait_s == null ? '—' : `${fa(Math.round(r.wait_s / 60))} دقیقه`) },
    ];
    if (tab === 'chats') return [
      { k: 'sid', label: 'جلسه', render: r => <span className="code">{r.session_id}</span> },
      { k: 'mode', label: 'حالت', render: r => MODE[r.mode] || r.mode },
      { k: 'users', label: 'دو کاربر', render: r => <div className="row" style={{ gap: 4 }}>
        {(r.slots || []).map(u => <B key={u} className="code">{fa(u)}</B>)}</div> },
      { k: 'msgs', label: 'پیام/مدیا', render: r => `${fa(r.messages_count)} / ${fa(r.media_count)}` },
      { k: 'at', label: 'آخرین فعالیت', render: r => <FaDateTime value={r.last_activity_at} /> },
      { k: 'x', label: 'اقدام', render: r => <div className="row" style={{ gap: 4 }}>
        <button className="btn sm" disabled={busy} title="سلامتِ چرخهٔ مچ این جلسه (§۴۶)"
          onClick={() => act(async () => setDrawer({ kind: 'health',
            body: await api.ringSessionHealth(r.session_id) }), '')}>🩺 سلامت</button>
        <button className="btn sm" disabled={busy} title="فقط فلگ‌های جامانده را درست می‌کند (§۴۷)"
          onClick={() => act(() => api.ringSessionRepair(r.session_id),
            'ترمیمِ محافظه‌کارانه اعمال شد')}>🔧 ترمیم</button>
        <button className="btn sm danger" disabled={busy} onClick={() => setConfirmEnd(r.session_id)}>⛔ بستن</button>
      </div> },
    ];
    if (tab === 'reports') return [
      { k: 'id', label: 'کد', render: r => <span className="code">R{fa(r.report_id)}</span> },
      { k: 'why', label: 'دلیل', render: r => <B kind={r.severity >= 3 ? 'bad' : 'warn'}>{r.reason}</B> },
      { k: 'sev', label: 'شدت', render: r => fa(r.severity) },
      { k: 'target', label: 'مظنون', render: r => <span className="code">{fa(r.reported_uid)}</span> },
      { k: 'status', label: 'وضعیت', render: r => <StatusBadge status={r.status === 'pending' ? 'pending' : 'active'}
        label={r.status === 'pending' ? 'در انتظار' : r.status} /> },
      { k: 'at', label: 'زمان', render: r => <FaDateTime value={r.created_at} /> },
      { k: 'x', label: 'بررسی', render: r => <button className="btn sm" disabled={busy}
        onClick={() => act(async () => setDrawer({ kind: 'report', body: await api.ringReport(r.report_id) }), '')}>🔎</button> },
    ];
    if (tab === 'blocks') return [
      { k: 'pair', label: 'چه کسی ← چه کسی', render: r => <div className="row" style={{ gap: 4 }}>
        <span className="code">{fa(r.user_id)}</span><span className="muted">را مسدود کرد</span>
        <span className="code">{fa(r.blocked_user_id)}</span></div> },
      { k: 'anons', label: 'ناشناس‌‌آی‌دی‌ها', render: r => <B kind="acc">{`#${r.user_anon || '—'} → #${r.blocked_anon || '—'}`}</B> },
      { k: 'src', label: 'منبع', render: r => (String(r.source || '').startsWith('report')
          ? <B kind="bad">🚨 گزارش</B> : <B>👤 کاربر</B>) },
      { k: 'at', label: 'زمان', render: r => <FaDateTime value={r.created_at} /> },
    ];
    if (tab === 'users') return [
      { k: 'uid', label: 'آیدی تلگرام', render: r => <span className="code">{fa(r.user_id ?? r._id)}</span> },
      { k: 'anon', label: 'ناشناس', render: r => <B kind="acc">#{r.anon_id || '—'}</B> },
      { k: 'mode', label: 'حالت', render: r => MODE[r.mode] || '—' },
      { k: 'status', label: 'وضعیت', render: r => <B kind={r.status === 'active' ? 'ok' : 'warn'}>{PSTATUS[r.status] || r.status || 'active'}</B> },
      { k: 'score', label: 'امتیاز گزارش', render: r => (r.report_score ? <B kind="bad">{fa(r.report_score)}</B> : '—') },
      { k: 'at', label: 'آخرین فعالیت', render: r => <FaDateTime value={r.updated_at || r.created_at} /> },
      { k: 'x', label: 'پرونده', render: r => <button className="btn sm" disabled={busy}
        onClick={() => act(async () => setDrawer({ kind: 'profile', body: await api.ringProfile(r.user_id ?? r._id) }), '')}>🗂</button> },
    ];
    return [
      { k: 'at', label: 'زمان', render: r => <FaDateTime value={r.created_at} /> },
      { k: 'who', label: 'توسط', render: r => <span className="code">{fa(r.admin_id)}</span> },
      { k: 'action', label: 'اقدام', render: r => <B kind="acc">{r.action}</B> },
      { k: 'target', label: 'هدف', render: r => <span className="code">{String(r.target ?? '—')}</span> },
      { k: 'note', label: 'یادداشت', render: r => <span className="muted">{r.note || '—'}</span> },
    ];
  }, [tab, busy]);

  if (noPerm) return <NoPerm text="مدیریت رینگ استریت نیازمند مجوز «ring.manage» است." />;
  if (err) return <ErrorState title="بارگذاری داده‌های رینگ ناموفق بود" error={err} onRetry={load} />;
  if (!ov) return <Loading rows={5} />;

  const live = ov.live || {};
  const qs = ov.queue || {};
  const state = ov.state || (ov.maintenance ? 'maintenance' : (ov.flag ? 'active' : 'disabled'));

  return <>
    <PageHeader
      eyebrow="💍 ماژول گفت‌وگوی ناشناس"
      title="رینگ استریت"
      description="صف تطبیق، گفت‌وگوها، نظارت و تنظیمات. هیچ پیام گفت‌وگویی اینجا نمایش داده نمی‌شود."
      actions={<div className="row" style={{ gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <Field label="وضعیت رینگ استریت"><div className="row" style={{ gap: 6 }}>
          {STATE_OPTS.map(([v, lbl]) => <button key={v} className="btn sm" disabled={busy}
            onClick={() => act(() => api.ringSetState(v, killMode), `وضعیت: ${lbl}`)}
            style={state === v ? { outline: '2px solid var(--c-acc)', fontWeight: 700 } : undefined}>{lbl}</button>)}
        </div></Field>
        <Field label="نوع خاموشی (برای 🔴)"><select value={killMode} onChange={e => setKillMode(e.target.value)}>
          <option value="soft">soft — گفت‌وگوهای موجود تمام شوند</option>
          <option value="hard">hard — همه را همین حالا ببند</option>
        </select></Field>
      </div>}
    />

    <div className="muted" style={{ fontSize: 'var(--fs-body)', margin: '6px 2px 0' }}>
      {STATE_HINT[state] || ''}{state === 'maintenance' ? ' — کاربر هیچ خطایی نمی‌بیند؛ فقط «جفت تازه ساخته نمی‌شود».' : ''}
    </div>

    <Tabs items={TABS} value={tab} onChange={t => { setTab(t); setPage(1); setDrawer(null); }} />

    {tab === 'overview' && <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))' }}>
      <KpiCard icon="⏳" label="در صف" value={fa(qs.waiting || live.waiting)} hint={`claim‌شده: ${fa(qs.claimed)}`} />
      <KpiCard icon="💬" label="گفت‌وگوی فعال" value={fa(live.in_chat)} hint={`RAM: ${fa(ov.ram?.in_chat)}`} />
      <KpiCard icon="👤" label="پروفایل‌ها" value={fa(live.active_profiles || live.profiles)} hint={`مکث: ${fa(live.paused)} · بن: ${fa(live.banned)}`} />
      <KpiCard tone="warn" icon="🚩" label="گزارش باز" value={fa(live.reports_pending)} hint={`امروز: ${fa(live.reports_today)}`} />
      <KpiCard tone="bad" icon="🧱" label="بلاک‌ها" value={fa(live.blocks)} />
      <KpiCard tone="acc" icon="📅" label="جلسه‌ی امروز" value={fa(live.sessions_today)} hint={`کل: ${fa(live.sessions_total)}`} />
      <KpiCard tone={nh.bound ? 'ok' : 'bad'} icon={nh.bound ? '🟢' : '🔴'} label="لایهٔ ارسال پیام"
        value={nh.bound ? 'آماده' : 'بدون بات'}
        hint={nh.bound ? `منبع: ${nh.source || 'bind'}` : 'post_init بات را bind نکرده — اطلاعیه‌ها ارسال نمی‌شوند'} />
      <div className="panel panel-pad" style={{ gridColumn: '1 / -1' }}>
        <KeyValueGrid>
          <KeyValue label="حالت جدی" value={ov.settings?.serious_enabled ? '✅' : '⛔'} />
          <KeyValue label="حالت فان" value={ov.settings?.fun_enabled ? '✅' : '⛔'} />
          <KeyValue label="کمترین سن" value={fa(ov.settings?.min_age)} />
          <KeyValue label="سقف پیام/دقیقه" value={fa(ov.settings?.max_msg_per_min)} />
          <KeyValue label="ثبت محتوا" value={ov.settings?.evidence_mode} />
          <KeyValue label="وضعیت" value={ov.state_label || (ov.flag ? '🟢 فعال' : '🔴 غیرفعال')} />
          <KeyValue label="نسخهٔ قوانین" value={fa(ov.rules_version || 1)} />
          <KeyValue label="ترکیب جنسیتی صف" value={Object.entries(qs.by_gender || {}).length
            ? Object.entries(qs.by_gender).map(([k, n]) => `${GENDER[k] || k}: ${fa(n)}`).join(' · ') : '—'} />
          <KeyValue label="به‌روزرسانی" value={<FaDateTime value={live.last_updated} />} />
        </KeyValueGrid>
        <div className="row" style={{ gap: 8, marginTop: 10 }}>
          <button className="btn sm" disabled={busy} onClick={() => setForce({})}>🎯 force match</button>
          <button className="btn sm" disabled={busy} onClick={() => act(api.ringReconcile, 'ناهمانگی‌ها ترمیم شد')}>🧩 reconcile</button>
          <button className="btn sm" disabled={busy} onClick={() => act(api.ringPurge, 'شواهد منقضی پاک شد')}>🧹 پاک‌سازی شواهد</button>
          <button className="btn sm danger" disabled={busy}
            onClick={() => act(async () => { await api.ringFlag(false, 'hard'); }, 'رینگ با زور خاموش شد')}>
            🛑 خاموشی اضطراری</button>
        </div>
      </div>
    </div>}

    {(tab === 'queue' || tab === 'chats' || tab === 'reports' || tab === 'users' || tab === 'blocks' || tab === 'audit') && <>
      <div className="row" style={{ gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
        {tab === 'users' && <input style={{ minWidth: 200 }} placeholder="جست‌وجو با آیدی تلگرام یا #ناشناس"
          value={q} onChange={e => { setQ(e.target.value); setPage(1); }} />}
        {tab === 'reports' && <select value={rStat} onChange={e => { setRStat(e.target.value); setPage(1); }}>
          <option value="pending">در انتظار</option><option value="reviewing">در حال بررسی</option>
          <option value="action_taken">اقدام شد</option><option value="resolved">حل‌شده</option>
          <option value="dismissed">رد‌شده</option><option value="">همه</option>
        </select>}
        {['users', 'reports', 'blocks'].includes(tab) && <KeyValue label="کل" value={fa(box.total)} />}
      </div>
      <DataTable columns={cols} rows={rows} rowKey={r => r.session_id || r.report_id || r._id || r.uid || r.user_id || Math.random()}
        loading={!box} onRow={tab === 'chats' ? (r => setDrawer({ kind: 'session', body: r })) : undefined}
        pager={{ page, pages: Math.max(1, Math.ceil((box.total || rows.length) / (box.size || 25))), total: fa(box.total || rows.length), onPage: setPage }} />
    </>}

    {tab === 'rules' && <RulesPanel box={box} busy={busy}
      onSave={(text, bump) => act(() => api.ringSaveRules(text, bump),
        bump ? 'قوانین ذخیره شد و نسخه بالا رفت (همه دوباره می‌پذیرند)' : 'قوانین ذخیره شد')}
      onReset={() => act(() => api.ringSaveRules('', false), 'متن پیش‌فرض برگشت')} />}

    {tab === 'settings' && <SettingsPanel box={box} edit={edit} setEdit={setEdit} busy={busy}
      onSave={() => act(() => api.ringSaveSettings(edit), 'تنظیمات ذخیره شد')} />}

    {tab === 'debug' && <DebugMatch busy={busy} onForce={(a, b) => act(
      () => api.ringForceMatch(a, b), 'match دستی ساخته شد')} />}

    {tab === 'analytics' && <AnalyticsPanel box={box} />}

    {confirmEnd && <Confirm text={`جلسه‌ی ${confirmEnd} بسته شود؟ هر دو طرف اطلاع می‌گیرند.`}
      onYes={() => { act(() => api.ringEndSession(confirmEnd, 'admin_panel'), 'جلسه بسته شد'); setConfirmEnd(null); }}
      onNo={() => setConfirmEnd(null)} danger />}

    {force && <ForceMatch busy={busy} onClose={() => setForce(null)}
      onSubmit={(a, b) => act(() => api.ringForceMatch(a, b), 'match دستی ساخته شد')} />}

    {drawer && <Modal title={drawer.kind === 'report' ? `گزارش R${fa(drawer.body.report?.report_id)}`
                    : drawer.kind === 'profile' ? `پرونده‌ی ${fa(drawer.body.profile?._id)}`
                    : drawer.kind === 'health' ? `سلامتِ جلسه ${drawer.body.session_id || ''}` : 'جلسه'}
      onClose={() => setDrawer(null)} wide>
      <ReportDrawerBody drawer={drawer} busy={busy}
        onReview={a => act(() => api.ringReview(drawer.body.report.report_id, a, ''), `اقدام «${a}» ثبت شد`)}
        onBan={uid => act(() => api.ringBan({ user_id: uid, kind: 'temporary', hours: 24, reason: 'report' }), '۲۴ ساعت بن شد')}
        onLift={uid => act(() => api.ringUnban(uid), 'محدودیت برداشته شد')}
        onPause={uid => act(() => api.ringPause(uid), 'کاربر محدود شد (خارج از صف)')}
        onResume={uid => act(() => api.ringResume(uid), 'محدودیت کاربر برداشته شد')}
        onEnd={sid => act(() => api.ringEndSession(sid, 'admin_panel'), 'جلسه بسته شد')}
        onRepair={sid => act(async () => { await api.ringSessionRepair(sid);
          setDrawer({ kind: 'health', body: await api.ringSessionHealth(sid) }); },
          'ترمیم اعمال شد — سلامتِ تازه بارگذاری شد')}
        repairing={repairing} />
    </Modal>}
  </>;
}

function SettingsPanel({ box, edit, setEdit, onSave, busy }) {
  const settings = box.settings || {};
  const labels = box.labels || {};
  const draft = edit || {};
  const val = k => (k in draft ? draft[k] : settings[k]);
  const set = (k, v) => setEdit({ ...(edit || {}), [k]: v });
  const keys = Object.keys(labels);
  const isNum = v => typeof v === 'number';
  return <div className="panel panel-pad">
    <SectionHeader title="تنظیمات رینگ استریت" description="هر تغییر بلافاصله در دیتابیس نوشته می‌شود و ربات آن را تا چند ثانیه بعد می‌خواند." />
    <div style={{ display: 'grid', gap: 8, gridTemplateColumns: 'repeat(auto-fit,minmax(240px,1fr))' }}>
      {keys.map(k => <Field key={k} label={labels[k]}>
        {typeof val(k) === 'boolean'
          ? <Switch on={!!val(k)} onChange={v => set(k, v)} />
          : isNum(val(k))
            ? <input type="number" value={val(k)} onChange={e => set(k, Number(e.target.value))} />
            : ['report_only', 'all', 'off'].includes(val(k))
              ? <select value={val(k)} onChange={e => set(k, e.target.value)}>
                <option value="report_only">فقط هنگام گزارش</option>
                <option value="all">همه (برای تست)</option>
                <option value="off">هیچ</option>
              </select>
              : <input value={val(k) ?? ''} onChange={e => set(k, e.target.value)} />}
      </Field>)}
    </div>
    <div className="row" style={{ gap: 8, marginTop: 10 }}>
      <button className="btn" disabled={busy || !Object.keys(draft).length} onClick={onSave}>
        💾 ذخیره‌ی {fa(Object.keys(draft).length)} تغییر</button>
      {Object.keys(draft).length > 0 && <button className="btn ghost sm" onClick={() => setEdit(null)}>لغو</button>}
    </div>
  </div>;
}

function DebugMatch({ busy, onForce }) {
  // §۳۷/§۳۸ — پاسخ همین کارت، دقیقاً همان دلیلی است که در لاگ
  // RING_MATCH_ATTEMPT … reason= می‌آید (یک الگوریتم، دو نمایش).
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  const [res, setRes] = useState(null);
  const [err, setErr] = useState('');
  const [run, setRun] = useState(false);
  const go = async () => {
    setRun(true); setErr('');
    try { setRes(await api.ringDebugMatch(Number(a), Number(b))); }
    catch (e) { setErr(errText(e)); setRes(null); }
    finally { setRun(false); }
  };
  const checks = (res && res.checks) || {};
  const hints = (res && res.hints) || {};
  const LABEL = {
    self: 'خودت نباشی', mode: 'یکی‌بودن حالت', mode_enabled: 'حالت روشن در پنل',
    gender_of_me: 'جنسیت او ← ترجیح من', age_of_me: 'سن او ← بازهٔ من',
    gender_of_cand: 'جنسیت من ← ترجیح او', age_of_cand: 'سن من ← بازهٔ او',
    min_age: 'حداقل سن', blocked: 'بلاک دوطرفه', recent: 'کول‌داون rematch',
    my_session: 'جلسهٔ فعال من', cand_session: 'جلسهٔ فعال او',
    cand_available: 'پروفایل او فعال است', queue_valid: 'ردیف صف او معتبر است',
  };
  return <div className="grid" style={{ display: 'grid', gap: 10 }}>
    <div className="panel panel-pad" style={{ display: 'grid', gap: 10 }}>
      <SectionHeader title="🔍 بررسی مچ (§۳۷)"
        description="دو uid بده: می‌گوید چرا این دو به هم مچ نمی‌شوند — با همان چک‌های مسیرِ واقعی." />
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <Field label="آیدی تلگرام A"><input value={a} onChange={e => setA(e.target.value)} /></Field>
        <Field label="آیدی تلگرام B"><input value={b} onChange={e => setB(e.target.value)} /></Field>
        <button className="btn" disabled={busy || run || !a || !b} onClick={go}>
          {run ? '…' : 'بررسی کن'}</button>
        {res && res.ok && <button className="btn sm" disabled={busy}
          onClick={() => onForce(Number(a), Number(b))}>🎯 ساخت جلسه</button>}
      </div>
      {err && <ErrorState error={err} onRetry={go} />}
      {!res && !err && <Empty icon="🔍" text="دو آیدی را وارد کن تا چک‌ها را ببینی." />}
      {res && <div style={{ display: 'grid', gap: 8 }}>
        <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
          {res.ok
            ? <B kind="ok">✅ این دو با هم سازگارند — اگر مچ نشدند، صف/زمان‌بندی را ببین</B>
            : <B kind="bad">⛔ دلیل: {LABEL[String(res.reason).split(':').pop()] || res.reason}</B>}
          <span className="muted">حالت بررسی‌شده: {MODE[res.mode] || res.mode || '—'}</span>
        </div>
        <div className="row" style={{ gap: 14, flexWrap: 'wrap' }}>
          <KeyValue label="وضعیت A" value={`${res.a?.state_label || '—'} (${res.a?.queue_status || 'خارج از صف'})`} />
          <KeyValue label="وضعیت B" value={`${res.b?.state_label || '—'} (${res.b?.queue_status || 'خارج از صف'})`} />
        </div>
        <DataTable rowKey={r => r.k}
          rows={Object.keys(checks).map(k => ({ k, ok: checks[k], hint: hints[k] }))}
          columns={[
            { k: 'k', label: 'چک', render: r => LABEL[r.k] || r.k },
            { k: 'ok', label: '', render: r => r.ok ? <B kind="ok">✓</B> : <B kind="bad">✗</B> },
            { k: 'hint', label: 'توضیح', render: r => <span className="muted">{r.hint || '—'}</span> },
          ]} />
        <div className="muted" style={{ fontSize: 'var(--fs-body)' }}>
          📌 این کارت هیچ محتوای گفت‌وگو یا اطلاعات خصوصی نشان نمی‌دهد؛ فقط نتیجهٔ
          چک‌ها. اگر «✅ سازگار» دیدی و مچ نشد، یعنی یا کسی در صف نمانده (توقف
          جست‌وجو/پایان)، یا claim زنده است، یا کول‌داون rematch (§۱۲) — لاگ
          `RING_MATCH_ATTEMPT` همان لحظه را ثبت کرده.
        </div>
      </div>}
    </div>
  </div>;
}


const CYCLE_LABELS = {
  match_attempts: ['🎯', 'تلاش مچ'], candidate_found: ['🔎', 'کاندید پیدا شد'],
  candidate_rejected: ['🚫', 'کاندید رد شد'], match_created: ['✅', 'match ساخته شد'],
  notify_ok: ['📬', 'اطلاعیه رسید'], notify_fail: ['📵', 'اطلاعیه نرسید'],
  search_ui_finalized: ['🖼', 'حباب جست‌وجو نهایی شد'],
  state_transition: ['🔁', 'تغییر وضعیت'], queue_removed: ['🚪', 'خروج از صف'],
  timer_cancelled: ['⏹', 'توقف تایمر'], orphan_matches: ['👻', 'match یتیم'],
  queue_orphans: ['👻', 'یتیمِ صف'], timer_orphans: ['👻', 'یتیمِ تایمر'],
  stuck_searches: ['⚠️', 'گیرکرده (کارت/پیام)'],
};

function CyclePanel({ c }) {
  const nh = c.notify_health || {};
  return <div className="panel panel-pad" style={{ gridColumn: '1 / -1' }}>
    <SectionHeader title="چرخهٔ match (§۴۹ V6)"
      description="هر حلقهٔ «match ساخته شد ولی کاربر در جست‌وجو ماند» با این شمارنده‌ها دیده می‌شود" />
    <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))' }}>
      {Object.keys(CYCLE_LABELS).map(k => <KpiCard key={k} icon={CYCLE_LABELS[k][0]}
        label={CYCLE_LABELS[k][1]} value={fa(c[k] || 0)} />)}
    </div>
    <div className="row" style={{ gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
      <B kind={nh.bound ? 'ok' : 'bad'}>{nh.bound ? `🟢 بات bind شده (${nh.source})` : '🔴 بات bind نشده'}</B>
      <B kind="muted">ردشده: {fa(nh.drops || 0)}</B>
      {c.window_days ? <B kind="muted">بازه: {fa(c.window_days)} روز</B> : null}
    </div>
    {nh.last_error ? <div style={{ marginTop: 6, fontSize: 'var(--fs-body)', opacity: .8 }}>
      آخرین خطا: {String(nh.last_error).slice(0, 200)}</div> : null}
    {c.live_error ? <div style={{ marginTop: 6, fontSize: 'var(--fs-body)' }}><B kind="warn">وضعیت زنده خوانده نشد: {String(c.live_error).slice(0, 120)}</B></div> : null}
  </div>;
}

function AnalyticsPanel({ box }) {
  const f = box.funnel || {}, m = box.modes || {}, mo = box.moderation || {};
  const rr = box.reject_reasons || {};   // §۳۹ — «چرا مچ نشد»
  const pct = x => `${fa(Math.round((x || 0) * 100))}٪`;   // noqa: استفاده‌شده در پایین
  return <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit,minmax(240px,1fr))' }}>
    {box.cycle ? <CyclePanel c={box.cycle} /> : null}
    <div className="panel panel-pad">
      <SectionHeader title="قیف (§۳۶)" description="پروفایل ← صف ← match ← گفت‌وگو" />
      <KeyValue label="پروفایل‌ها" value={fa(f.profiles)} />
      <KeyValue label="ورود به صف" value={fa(f.joins)} />
      <KeyValue label="matchها" value={fa(f.matches)} />
      <KeyValue label="نرخ match" value={pct(f.match_rate)} />
      <KeyValue label="میانگین انتظار" value={`${fa(Math.round(f.avg_wait_s || 0))} ثانیه`} />
      <KeyValue label="بیشترین انتظار" value={`${fa(Math.round(f.max_wait_s || 0))} ثانیه`} />
      <KeyValue label="rematch بعد از کول‌داون" value={fa(f.rematch)} />
      <KeyValue label="میانگین طول گفت‌وگو" value={`${fa(Math.round(f.avg_session_s || 0))} ثانیه`} />
      <KeyValue label="پیام به ازای match" value={fa(f.msgs_per_match)} />
    </div>
    <div className="panel panel-pad">
      <SectionHeader title="حالت‌ها" description="تقسیم جدی/فان" />
      {Object.keys(m).length === 0 && <Empty icon="📭" text="داده‌ای نیست" />}
      {Object.entries(m).map(([k, v]) => <div key={k} style={{ marginBottom: 8 }}>
        <b>{MODE[k] || k}</b>
        <div className="muted">جلسه: {fa(v.sessions)} · پیام: {fa(v.messages)} · مدت: {fa(v.avg_duration_s)} ثانیه</div>
      </div>)}
    </div>
    <div className="panel panel-pad">
      <SectionHeader title="🔍 چرا مچ نمی‌شوند؟ (§۳۸/§۳۹)"
        description="تفکیک دلیلِ ردِ کاندیدوها در ۷ روز گذشته" />
      {Object.keys(rr).length === 0 && <Empty icon="✅" text="هیچ ردی ثبت نشده" />}
      {Object.entries(rr).map(([k, v]) => <div key={k} className="row"
        style={{ gap: 8, justifyContent: 'space-between' }}>
        <span className="muted">{k}</span><b>{fa(v)}</b>
      </div>)}
      <KeyValue label="متوقف‌های جست‌وجو (§۲۳)" value={fa(box.paused)} />
    </div>
    <div className="panel panel-pad">
      <SectionHeader title="مدیریت ریسک" description="گزارش‌ها، تکراری‌ها و بن‌ها" />
      <KeyValue label="گزارش‌ها" value={fa(mo.total)} />
      <KeyValue label="تکراری" value={pct(mo.dup_share)} />
      <KeyValue label="بن‌ها" value={fa(mo.bans)} />
      <div style={{ marginTop: 8 }}>{Object.entries(mo.by_reason || {}).map(([k, v]) =>
        <div key={k} className="muted">{k}: {fa(v.n)}</div>)}</div>
    </div>
    <div className="panel panel-pad">
      <SectionHeader title="موضوع‌های داغ" description="ترجیحات ثبت‌شده در پروفایل‌ها" />
      {(box.topics || []).length === 0 && <Empty icon="🏷" text="موضوعی ثبت نشده" />}
      {(box.topics || []).map(t => <div key={t.topic} className="row" style={{ justifyContent: 'space-between' }}>
        <span>{t.topic}</span><B kind="acc">{fa(t.users)}</B></div>)}
    </div>
  </div>;
}

const HEALTH_STEPS = [
  ['state', 'وضعیت کاربر (current_session)', 'پروفایل هر دو به این جلسه وصل است'],
  ['queue', 'خروج از صف', 'هیچ‌کدام دوباره match نمی‌شوند'],
  ['timer', 'توقف تایمر/حباب جست‌وجو', 'پیام «۰۰:۰۰» روی صفحه نمانده'],
  ['notify', 'ارسال کارت مچ برای هر دو', 'هر دو طرف پیام را گرفته‌اند'],
  ['relay', 'رجیستری رله (aliases)', 'پیام‌ها به هم می‌رسند'],
];

function HealthBody({ body, busy, onRepair, repairing }) {
  const st = (body && body.steps) || {};
  if (!body || body.found === false) {
    return <div style={{ padding: 8 }}>
      <B kind="bad">جلسه در دیتابیس پیدا نشد</B>
      <div style={{ marginTop: 8, fontSize: 'var(--fs-card)' }}>اگر id را از لاگِ بات آورده‌اید، ممکن است
        پاک شده یا archive شده باشد.</div>
    </div>;
  }
  return <div style={{ padding: 4 }}>
    <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
      <B kind={body.status === 'active' ? 'ok' : 'muted'}>{body.status === 'active' ? 'فعال' : body.status}</B>
      <B kind="acc">{MODE[body.mode] || body.mode || '—'}</B>
      {(body.slots || []).map(u => <B key={u} className="code">{fa(u)}</B>)}
      {body.notify_health && <B kind={body.notify_health.bound ? 'ok' : 'bad'}>
        {body.notify_health.bound ? '🟢 لایهٔ ارسال سالم' : '🔴 باتِ اطلاعیه bind نشده'}</B>}
    </div>
    {HEALTH_STEPS.map(([k, label, hint]) => {
      const m = st[k] || {};
      const vals = Object.values(m);
      const allOk = vals.length > 0 && vals.every(Boolean);
      const none = vals.length === 0;
      return <div key={k} className="row hairline-b" style={{ justifyContent: 'space-between', padding: '6px 0' }}>
        <div>
          <div style={{ fontSize: 'var(--fs-card)' }}>{label}</div>
          <div style={{ fontSize: 'var(--fs-label)', opacity: .6 }}>{hint}</div>
        </div>
        <div className="row" style={{ gap: 4 }}>
          {none ? <B kind="muted">—</B> : Object.entries(m).map(([u, v]) =>
            <B key={u} kind={v ? 'ok' : 'bad'} className="code">{fa(u)}: {v ? '✓' : '✗'}</B>)}
        </div>
      </div>;
    })}
    {st.notify_tries && Object.keys(st.notify_tries).length > 0 && <div style={{ marginTop: 8, fontSize: 'var(--fs-body)', opacity: .75 }}>
      تلاش‌های اطلاعیه: {Object.entries(st.notify_tries).map(([u, n]) => `${fa(u)}→${fa(n)}`).join(' · ')}
      {' '} (سقف ۳ تلاش با backoff ۵/۱۵/۶۰ ثانیه)
    </div>}
    <div className="row" style={{ gap: 8, marginTop: 10 }}>
      <button className="btn sm" disabled={busy || !body.needs_repair}
        title="فقط فلگ‌ها/پیام‌های جامانده را درست می‌کند؛ جلسه را نمی‌بندد و پیام تکراری نمی‌فرستد"
        onClick={() => onRepair(body.session_id)}>
        {repairing === body.session_id ? 'در حال ترمیم…' : '🔧 ترمیم محافظه‌کارانه'}</button>
      {!body.needs_repair && <B kind="ok">همهٔ مراحل کامل است — چیزی برای ترمیم نیست</B>}
    </div>
  </div>;
}

function ReportDrawerBody({ drawer, busy, onReview, onBan, onLift, onPause, onResume, onEnd, onRepair, repairing }) {
  if (drawer.kind === 'health') {
    return <HealthBody body={drawer.body} busy={busy} onRepair={onRepair} repairing={repairing} />;
  }
  if (drawer.kind === 'session') {
    const s = drawer.body || {};
    return <div style={{ padding: 4 }}>
      <KeyValue label="حالت" value={MODE[s.mode] || s.mode} />
      <KeyValue label="پیام‌ها" value={fa(s.messages_count)} />
      <KeyValue label="مدیا" value={fa(s.media_count)} />
      <KeyValue label="شروع" value={<FaDateTime value={s.created_at} />} />
      <div className="row" style={{ gap: 8, marginTop: 10 }}>
        <button className="btn sm danger" disabled={busy} onClick={() => onEnd(s.session_id)}>⛔ بستن جلسه</button>
      </div>
    </div>;
  }
  if (drawer.kind === 'profile') {
    const p = drawer.body.profile || {}, ban = drawer.body.ban;
    return <div style={{ padding: 4 }}>
      <KeyValue label="ناشناس" value={`#${p.anon_id || '—'}`} />
      <KeyValue label="حالت" value={MODE[p.mode] || '—'} />
      <KeyValue label="امتیاز گزارش" value={fa(p.report_score)} />
      <KeyValue label="هشدارها" value={fa(p.warnings)} />
      <KeyValue label="جلسه‌ها" value={fa(drawer.body.sessions?.length)} />
      <KeyValue label="میانگین امتیاز" value={drawer.body.rating?.avg ?? '—'} />
      {ban && <B kind="bad">بن فعال تا {ban.until || 'همیشه'}</B>}
      <div className="row" style={{ gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
        <button className="btn sm" disabled={busy} onClick={() => onPause(p._id)}>⏸ مکث</button>
        <button className="btn sm" disabled={busy} onClick={() => onResume(p._id)}>▶️ بازگشت</button>
        <button className="btn sm danger" disabled={busy} onClick={() => onBan(p._id)}>🚫 بن ۲۴ ساعته</button>
        <button className="btn sm" disabled={busy} onClick={() => onLift(p._id)}>✅ برداشتن محدودیت</button>
      </div>
    </div>;
  }
  const r = drawer.body.report || {}, ev = drawer.body.evidence || [];
  return <div style={{ padding: 4 }}>
    <KeyValue label="دلیل" value={r.reason} />
    <KeyValue label="شدت" value={fa(r.severity)} />
    <KeyValue label="وضعیت" value={r.status} />
    <KeyValue label="توضیح" value={r.details || '—'} />
    <KeyValue label="شواهد" value={fa(ev.length)} />
    {ev.length > 0 && <div className="panel" style={{ marginTop: 8, padding: 8 }}>
      {ev.map(e => <div key={e._id} className="muted" style={{ marginBottom: 4 }}>
        <span className="code">{e.alias}</span> · {e.kind} · {e.text ? `«${e.text}»` : '(بدون متن)'}
      </div>)}
    </div>}
    <div className="row" style={{ gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
      {['review', 'resolve', 'dismiss', 'warn', 'temp_ban', 'perm_ban'].map(a =>
        <button key={a} className={`btn sm ${a.includes('ban') ? 'danger' : ''}`} disabled={busy}
          onClick={() => onReview(a)}>{a}</button>)}
    </div>
  </div>;
}

function ForceMatch({ busy, onClose, onSubmit }) {
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  return <Modal title="🎯 force match" onClose={onClose}>
    <div style={{ padding: 8, display: 'grid', gap: 8 }}>
      <Field label="آیدی تلگرام کاربر A"><input value={a} onChange={e => setA(e.target.value)} /></Field>
      <Field label="آیدی تلگرام کاربر B" hint="هر دو باید ۱۸+ و بدون بلاک متقابل باشند."><input value={b} onChange={e => setB(e.target.value)} /></Field>
      <div className="row" style={{ gap: 8 }}>
        <button className="btn" disabled={busy || !a || !b} onClick={() => { onSubmit(Number(a), Number(b)); onClose(); }}>ساخت جلسه</button>
        <button className="btn ghost sm" onClick={onClose}>انصراف</button>
      </div>
    </div>
  </Modal>;
}


function RulesPanel({ box, busy, onSave, onReset }) {
  // §۲۶/§۲۷/§۴۰ — متن ۱۱بندی پیش‌فرض در بک‌اند است؛ اینجا فقط جایگزینِ ادمین و
  // «بالا بردن نسخه» که همه را مجبور به پذیرش دوباره می‌کند.
  const [txt, setTxt] = useState(null);
  const [bump, setBump] = useState(true);
  if (!box) return <Loading rows={3} />;
  const val = txt === null ? (box.text || '') : txt;
  return <div className="panel panel-pad" style={{ display: 'grid', gap: 10 }}>
    <div className="row" style={{ gap: 14, flexWrap: 'wrap' }}>
      <KeyValue label="نسخهٔ فعلی" value={fa(box.version)} />
      <KeyValue label="پذیرفته‌اند" value={fa(box.accepted)} />
      <KeyValue label="در انتظار پذیرش" value={fa(box.pending)} />
      <KeyValue label="متن" value={box.overridden ? '✏️ جایگزینِ ادمین' : '🛡 پیش‌فرض (۱۱ بند)'} />
      <KeyValue label="حداقل سن" value={fa(box.min_age)} />
    </div>
    {box.pending > 0 && <div className="muted" style={{ fontSize: 'var(--fs-body)' }}>
      ⚠️ {fa(box.pending)} کاربر فعال نسخهٔ فعلی قوانین را نپذیرفته؛ تا پذیرش وارد
      صف نمی‌شوند (پیام «قوانین به‌روز شده» را می‌بینند، نه خطا).
    </div>}
    <textarea dir="rtl" style={{ minHeight: 320, width: '100%', fontFamily: 'inherit', lineHeight: 1.8 }}
      value={val} maxLength={3500} disabled={busy}
      onChange={e => setTxt(e.target.value)}
      placeholder="متن پیش‌فرض ۱۱بندی را اینجا ویرایش کنید… {min_age} با حداقل سن جایگزین می‌شود." />
    <div className="row" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
      <label className="muted" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <input type="checkbox" checked={bump} disabled={busy} onChange={e => setBump(e.target.checked)} />
        بالا بردن نسخه (همه باید دوباره بپذیرند)
      </label>
      <span className="muted" style={{ fontSize: 'var(--fs-body)' }}>{fa(val.length)} / ۳۵۰۰</span>
      <button className="btn sm" disabled={busy || !val.trim()} onClick={() => onSave(val, bump)}>💾 ذخیره</button>
      <button className="btn sm" disabled={busy} onClick={() => setTxt(box.default_text || '')}>📋 بارگذاری متن پیش‌فرض</button>
      <button className="btn sm danger" disabled={busy || !box.overridden} onClick={onReset}>↩️ حذف متن جایگزین</button>
    </div>
    <div className="muted" style={{ fontSize: 'var(--fs-body)' }}>
      🛡 متن جایگزین فقط «بدنه» را عوض می‌کند؛ پاورقیِ حالت‌ها و یادآوری‌های ایمنی
      سرِ جایشان می‌مانند. اگر نگارش curly-brace داخل متن خراب باشد، همان متن
      بدون جایگزینی نمایش داده می‌شود و صفحه نمی‌شکند.
    </div>
  </div>;
}
