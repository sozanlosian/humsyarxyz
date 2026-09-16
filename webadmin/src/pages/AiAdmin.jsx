import React, { useEffect, useState } from 'react';
import { api, errText } from '../api.js';
import { Loading, ErrorState, Empty, Stat, B, FaDateTime, PageHeader, Tabs, Switch, toast, NoPerm, Confirm, Modal, DiffViewer } from '../ui.jsx';
import { PersianDatePicker } from '../PersianDatePicker.jsx';

// 🤖🌊 W-Admin — مرکز فرماندهی هوشیار: KPI ساخت‌یافته + برترین‌ها + گزارش‌ها + دسترسی + پیکربندی
// (رفع نقص قبلی: داده‌ی خام tuple/comma دیگر به UI تخلیه نمی‌شود — سریالایزر سمت API)
const AI_TABS = [['overview', '📊 نمای کلی'], ['reports', '🚩 گزارش‌ها'], ['access', '🔐 دسترسی و سهمیه'], ['personas', '🎭 Personaها'], ['config', '⚙️ پیکربندی']];

export default function AiAdmin({ me }) {
  const [tab, setTab] = useState('overview');
  const [stats, setStats] = useState(null);
  const [cfg, setCfg] = useState(null);
  const [err, setErr] = useState('');
  const [permErr, setPermErr] = useState(false);

  const load = async () => {
    setErr('');
    try {
      const [s, c] = await Promise.all([api.aiStats(), api.aiConfig()]);
      setStats(s); setCfg(c);
    } catch (e) {
      if (e.status === 403) setPermErr(true); else setErr(errText(e));
    }
  };
  useEffect(() => { load(); }, []);

  if (permErr) return <NoPerm text="مدیریت هوشیار نیازمند مجوز «مدیریت هوشیار» (ai.manage) است" />;
  if (err) return <ErrorState title="بارگذاری داده‌های هوشیار ناموفق بود" error={err} onRetry={load} />;
  if (stats === null && cfg === null) return <Loading rows={4} />;

  const kpis = stats ? [
    { icon: '💬', label: 'پرسش امروز', v: stats.total_today, tint: 'var(--acc)' },
    { icon: '👥', label: 'کاربران فعال امروز', v: stats.users_today, tint: 'var(--ok)' },
    { icon: '🪙', label: 'توکن امروز', v: stats.tokens_today, tint: 'var(--warn)' },
    { icon: '📈', label: 'کل پرسش‌ها', v: stats.total_alltime, tint: 'var(--purple)' },
    { icon: '🧑‍🎓', label: 'کل کاربران هوشیار', v: stats.users_alltime, tint: 'var(--teal)' },
    { icon: '🏦', label: 'کل توکن مصرفی', v: stats.tokens_alltime, tint: 'var(--acc2)' },
  ] : [];

  const TopList = ({ title, rows }) => (
    <div className="panel panel-pad">
      <b>{title}</b>
      {!rows?.length && <div className="muted" style={{ marginTop: 8 }}>داده‌ای نیست</div>}
      {(rows || []).map((r, i) => (
        <div key={r.user_id} className="minibar-row" style={{ marginTop: 8 }}>
          <B kind={i < 3 ? 'acc' : ''}>{Number(i + 1).toLocaleString('fa')}</B>
          <div style={{ minWidth: 0, flex: '0 0 44%' }}>
            <div style={{ color: 'var(--txt)', fontSize: 'var(--fs-body)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name}</div>
            <div className="muted code">#{r.user_id}</div>
          </div>
          <div className="minibar-track">
            <div className="minibar-fill" style={{ width: `${Math.max(3, Math.round(r.count * 100 / Math.max(1, rows[0]?.count || 1)))}%` }} />
          </div>
          <B kind="ok">{Number(r.count).toLocaleString('fa')}</B>
        </div>
      ))}
    </div>
  );

  return (
    <>
      <PageHeader title="مرکز فرماندهی هوشیار" description="مصرف، سلامت سرویس، گزارش کاربران، دسترسی و پیکربندی مدل"
        actions={cfg ? <><B kind={cfg.enabled ? 'ok' : 'bad'}>{cfg.enabled ? '● سرویس فعال' : '● سرویس غیرفعال'}</B><B>{cfg.provider} · {cfg.model}</B></> : null} />
      <Tabs items={AI_TABS.filter(([k]) => k !== 'personas' || me?.is_owner)} value={tab} onChange={setTab} label="بخش‌های هوشیار" />

      {tab === 'overview' && (
        <>
          {!stats ? <Empty icon="📭" text="آمار مصرف در دسترس نیست" /> : (
            <>
              <div className="grid g4">
                {kpis.map((c, i) => <Stat key={i} icon={c.icon} label={c.label}
                  value={Number(c.v ?? 0).toLocaleString('fa')} tint={c.tint} />)}
              </div>
              <div className="grid g2" style={{ marginTop: 14 }}>
                <TopList title="🏅 برترین کاربران امروز" rows={stats.top_today_users} />
                <TopList title="🏆 برترین کاربران همه‌ی زمان‌ها" rows={stats.top_alltime_users} />
              </div>
            </>
          )}
        </>
      )}

      {tab === 'reports' && <AiReports />}
      {tab === 'access' && <AiAccess me={me} />}
      {tab === 'personas' && me?.is_owner && <AiPersonas />}
      {tab === 'config' && <AiConfig cfg={cfg} me={me} onSaved={load} />}
    </>
  );
}

/* ── 🚩 گزارش‌های کاربران از پاسخ هوشیار ── */
function AiReports() {
  const [data, setData] = useState(null); const [err, setErr] = useState('');
  const [q, setQ] = useState(''); const [userId, setUserId] = useState('');
  const [dateFrom, setDateFrom] = useState(''); const [dateTo, setDateTo] = useState(''); const [page, setPage] = useState(1); const limit = 30;
  const params = { q, user_id: userId, date_from: dateFrom, date_to: dateTo, skip: (page - 1) * limit, limit };
  const load = async () => { setErr(''); try { setData(await api.aiReports(params)); } catch (e) { setErr(errText(e)); } };
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [q, userId, dateFrom, dateTo, page]);
  if (err) return <ErrorState title="بارگذاری گزارش‌های هوشیار ناموفق بود" error={err} onRetry={load} />;
  const items = data?.reports || [];
  return <>
    <div className="panel panel-pad row" style={{ marginBottom: 10, flexWrap: 'wrap' }}>
      <input className="inp" placeholder="جست‌وجو در نام، پرسش و پاسخ…" value={q} onChange={e => { setQ(e.target.value); setPage(1); }} />
      <input className="inp" dir="ltr" placeholder="User ID" value={userId} onChange={e => { setUserId(e.target.value.replace(/\D/g, '')); setPage(1); }} />
      <PersianDatePicker value={dateFrom} onChange={value => { setDateFrom(value); setPage(1); }} placeholder="از تاریخ شمسی" />
      <PersianDatePicker value={dateTo} onChange={value => { setDateTo(value); setPage(1); }} placeholder="تا تاریخ شمسی" />
      <button className="btn sm" title="خروجی CSV از گزارش‌های هوش مصنوعی با همین فیلترها" onClick={() => api.exportAiReports(params)}>📤 CSV</button>
      {data && <B>{Number(data.total || 0).toLocaleString('fa')} گزارش</B>}
    </div>
    {!data ? <Loading rows={3} /> : !items.length ? <Empty icon="🎉" text="گزارشی با این فیلترها ثبت نشده" /> : <div className="grid" style={{ gap: 8 }}>
      {items.map(r => <div key={r.id} className="panel panel-pad">
        <div className="row"><b>{r.name || '—'}</b><span className="code muted">#{r.user_id}</span><span className="spacer" /><FaDateTime value={r.created_at} /></div>
        <div style={{ marginTop: 8 }}><div className="muted">❓ پرسش</div><div>{r.question}</div></div>
        <div style={{ marginTop: 6 }}><div className="muted">🤖 پاسخ گزارش‌شده</div><div style={{ color: 'var(--txt2)' }}>{r.answer}</div></div>
      </div>)}
      <div className="row" style={{ justifyContent: 'center' }}><button className="btn sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>قبلی</button><B>{page.toLocaleString('fa')}</B><button className="btn sm" disabled={page * limit >= (data.total || 0)} onClick={() => setPage(p => p + 1)}>بعدی</button></div>
    </div>}
  </>;
}

/* ── 🔐 دسترسی: جست‌وجو + مسدود/رفع + صفرکردن سهمیه ── */
function AiAccess({ me }) {
  const [q, setQ] = useState('');
  const [hits, setHits] = useState(null);
  const [banned, setBanned] = useState(null); const [bTotal, setBTotal] = useState(0);
  const [bq, setBq] = useState(''); const [bPage, setBPage] = useState(1); const bLimit = 30;
  const [err, setErr] = useState('');
  const [pending, setPending] = useState(null);
  const [profile, setProfile] = useState(null);

  const loadBanned = async () => {
    try { const r = await api.aiBanned({ q: bq, skip: (bPage - 1) * bLimit, limit: bLimit }); setBanned(r.users || []); setBTotal(r.total || 0); }
    catch (e) { setErr(errText(e)); }
  };
  useEffect(() => { const t = setTimeout(loadBanned, 250); return () => clearTimeout(t); }, [bq, bPage]);

  const search = async () => {
    if (q.trim().length < 2) return toast('حداقل ۲ حرف', 'err');
    try { setHits((await api.aiUsers(q.trim())).users || []); }
    catch (e) { toast(errText(e), 'err'); }
  };
  const act = async (fn, okMsg) => {
    try { await fn(); toast(okMsg); setHits(null); loadBanned(); }
    catch (e) { toast(errText(e), 'err'); }
  };

  if (err) return <ErrorState title="بارگذاری فهرست دسترسی ناموفق بود" error={err} onRetry={loadBanned} />;
  return (
    <>
      <div className="panel panel-pad row" style={{ marginBottom: 12 }}>
        <input className="inp" style={{ flex: 1, minWidth: 200 }} placeholder="🔎 نام/یوزرنیم/شماره…"
               value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === 'Enter' && search()} />
        <button className="btn primary sm" onClick={search}>جست‌وجو</button>
      </div>
      {hits && (
        <div className="panel" style={{ marginBottom: 12 }}>
          {hits.length === 0 && <Empty icon="🔍" text="کاربری یافت نشد" />}
          {hits.map(u => (
            <div key={u.id} className="tree-row" style={{ padding: '9px 12px' }}>
              <span>👤</span>
              <b style={{ color: 'var(--txt)' }}>{u.name}</b>
              <span className="code muted">#{u.id}</span>
              {u.banned && <B kind="bad">مسدود از هوشیار</B>}
              <span className="spacer" />
              <button className={`btn sm ${u.banned ? 'ok' : 'danger'}`}
                      onClick={() => setPending({ fn: () => api.aiBan(u.id), msg: u.banned ? 'رفع مسدودیت شد ✅' : 'مسدود شد ⛔', text: `${u.banned ? 'رفع مسدودیت' : 'مسدودسازی'} دسترسی هوشیار برای «${u.name}»؟`, danger: !u.banned })}>
                {u.banned ? '✅ رفع مسدودیت' : '⛔ مسدود'}
              </button>
              <button className="btn sm" title="صفرکردن سهمیه‌ی امروز"
                      onClick={() => setPending({ fn: () => api.aiResetQuota(u.id), msg: 'سهمیه‌ی امروز صفر شد 🔄', text: `سهمیه امروز «${u.name}» از ${u.usage_today || 0} به صفر تغییر کند؟`, danger: true })}>🔄 سهمیه</button>
              {me?.is_owner && <button className="btn sm" onClick={async () => { try { setProfile(await api.aiProfile(u.id)); } catch (e) { toast(errText(e), 'err'); } }}>🧠 پروفایل</button>}
            </div>
          ))}
        </div>
      )}
      <div className="panel panel-pad">
        <div className="row"><b>⛔ مسدودشدگان از هوشیار</b><span className="spacer" /><B>{Number(bTotal).toLocaleString('fa')}</B></div>
        <input className="inp" style={{ width: '100%', marginTop: 8 }} placeholder="جست‌وجو در مسدودشدگان…" value={bq} onChange={e => { setBq(e.target.value); setBPage(1); }} />
        {!banned ? <Loading rows={2} /> : banned.length === 0 ? (
          <p className="muted" style={{ marginTop: 8 }}>هیچ کاربر مسدودی نیست 🕊</p>
        ) : (
          <div className="grid" style={{ gap: 6, marginTop: 10 }}>
            {banned.map(u => (
              <div key={u.id} className="row" style={{ padding: '7px 10px', border: '1px solid var(--line)', borderRadius: 10 }}>
                <span>⛔</span>
                <b style={{ color: 'var(--txt)' }}>{u.name}</b>
                <span className="code muted">#{u.id}</span>
                <span className="spacer" />
                <button className="btn sm ok" onClick={() => setPending({ fn: () => api.aiBan(u.id), msg: 'رفع مسدودیت شد ✅', text: `رفع مسدودیت هوشیار برای «${u.name}»؟` })}>✅ رفع مسدودیت</button>
              </div>
            ))}
          </div>
        )}
        {bTotal > bLimit && <div className="row" style={{ justifyContent: 'center', marginTop: 8 }}><button className="btn sm" disabled={bPage <= 1} onClick={() => setBPage(p => p - 1)}>قبلی</button><B>{bPage.toLocaleString('fa')}</B><button className="btn sm" disabled={bPage * bLimit >= bTotal} onClick={() => setBPage(p => p + 1)}>بعدی</button></div>}
      </div>
      {pending && <Confirm danger={pending.danger} text={pending.text}
        onNo={() => setPending(null)} onYes={async () => { const p = pending; setPending(null); await act(p.fn, p.msg); }} />}
      {profile && <Modal title={`🧠 پروفایل ماندگار — ${profile.user?.name || profile.user?.id}`} onClose={() => setProfile(null)}>
        <div className="muted">فقط profile notes و حافظه legacy نمایش داده می‌شود؛ گفتگوهای شخصی چندگانه در این scope نیستند.</div>
        {(profile.notes || []).length ? <ul>{profile.notes.map((n, i) => <li key={i}>{n}</li>)}</ul> : <Empty text="یادداشت ماندگاری ثبت نشده" />}
        <div className="row"><B>{profile.legacy_memory_present ? 'حافظه legacy موجود است' : 'حافظه legacy ندارد'}</B><span className="spacer" />
          <button className="btn danger" onClick={() => setPending({ fn: () => api.aiProfileClear(profile.user.id), msg: 'پروفایل و حافظه legacy پاک شد', text: 'Profile notes و حافظه legacy پاک شوند؟ این عملیات گفتگوهای چندگانه را حذف نمی‌کند.', danger: true })}>پاک‌سازی</button></div>
      </Modal>}
    </>
  );
}

function AiPersonas() {
  const [items, setItems] = useState(null); const [err, setErr] = useState('');
  const [create, setCreate] = useState(false); const [name, setName] = useState(''); const [prompt, setPrompt] = useState('');
  const [pending, setPending] = useState(null);
  const load = async () => { try { setItems((await api.aiPersonas()).personas || []); setErr(''); } catch (e) { setErr(errText(e)); } };
  useEffect(() => { load(); }, []);
  if (err) return <ErrorState error={err} onRetry={load} />;
  if (!items) return <Loading rows={4} />;
  const execute = async p => { try { await p.fn(); toast(p.ok); load(); } catch (e) { toast(errText(e), 'err'); } };
  return <>
    <div className="row" style={{ marginBottom: 10 }}><B>{items.length.toLocaleString('fa')} Persona</B><span className="spacer" /><button className="btn primary" onClick={() => { setName(''); setPrompt(''); setCreate(true); }}>➕ ذخیره Persona</button></div>
    {!items.length ? <Empty text="Persona ذخیره‌شده‌ای نیست" /> : <div className="grid g2">{items.map(p => <div className="panel panel-pad" key={p.name}>
      <div className="row"><b>{p.name}</b>{p.active && <B kind="ok">فعال</B>}<span className="spacer" /><button className="btn sm" disabled={p.active} onClick={() => setPending({ danger: true, text: `Persona «${p.name}» فعال شود؟ System Prompt فعلی با prompt این Persona جایگزین می‌شود.`, before: 'System Prompt فعلی', after: p.prompt, fn: () => api.aiPersonaActivate(p.name), ok: 'Persona فعال شد' })}>▶ فعال‌سازی</button><button className="btn sm danger" onClick={() => setPending({ danger: true, text: `Persona «${p.name}» حذف شود؟`, fn: () => api.aiPersonaDelete(p.name), ok: 'Persona حذف شد' })}>🗑</button></div>
      <div className="muted text-wrap" style={{ marginTop: 8 }}>{p.prompt}</div>
      <div className="muted">{p.created_at ? <>ساخته‌شده: <FaDateTime value={p.created_at} /></> : 'متادیتای ساخت برای رکورد قدیمی موجود نیست'}</div>
    </div>)}</div>}
    {create && <Modal title="ذخیره Persona" onClose={() => setCreate(false)}><input className="inp" style={{ width: '100%' }} placeholder="نام Persona" value={name} onChange={e => setName(e.target.value)} /><textarea className="inp" rows={8} style={{ width: '100%', marginTop: 8 }} placeholder="Prompt؛ خالی = System Prompt فعلی" value={prompt} onChange={e => setPrompt(e.target.value)} /><div className="row" style={{ marginTop: 10 }}><button className="btn primary" disabled={!name.trim() || (!!prompt && prompt.trim().length < 20)} onClick={async () => { try { await api.aiPersonaCreate({ name: name.trim(), prompt: prompt.trim() || null }); setCreate(false); toast('Persona ذخیره شد'); load(); } catch (e) { toast(errText(e), 'err'); } }}>ذخیره</button></div></Modal>}
    {pending && <Confirm danger={pending.danger} text={pending.text} onNo={() => setPending(null)} onYes={async () => { const p = pending; setPending(null); await execute(p); }}>{pending.after && <DiffViewer before={{ system_prompt: pending.before }} after={{ system_prompt: pending.after }} />}</Confirm>}
  </>;
}

/* ── ⚙️ پیکربندی مدل (PUT /config — همان guard و منطق مینی‌اپ) ── */
function AiConfig({ cfg, me, onSaved }) {
  const [f, setF] = useState(null);
  const [busy, setBusy] = useState(false);
  const [confirmSave, setConfirmSave] = useState(false);
  /* 🌊 W9 — کاتالوگ مرکزی مدل‌ها (بدون تایپ دستی) */
  const [cat, setCat] = useState(null);
  useEffect(() => { api.aiModels().then(setCat).catch(() => {}); }, []);
  const [keyOpen, setKeyOpen] = useState(false); const [apiKey, setApiKey] = useState('');
  const [testResult, setTestResult] = useState(null);
  useEffect(() => { if (cfg) setF({ ...cfg }); }, [cfg]);
  if (!cfg) return <Empty icon="⚙️" text="پیکربندی در دسترس نیست" />;
  if (!f) return <Loading rows={3} />;

  const set = (k, v) => setF(x => ({ ...x, [k]: v }));
  const save = async () => {
    setBusy(true);
    try {
      await api.aiConfigUpdate({
        enabled: !!f.enabled, provider: f.provider, model: f.model.trim(),
        daily_limit: Number(f.daily_limit) || 0, thinking: f.thinking,
        system_prompt: f.system_prompt, disabled_message: f.disabled_message || '',
      });
      toast('پیکربندی ذخیره شد ✅'); onSaved();
    } catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };

  return (
    <>
    <div className="grid g2">
      <div className="panel panel-pad">
        <b>وضعیت سرویس</b>
        <div className="row" style={{ marginTop: 12 }}>
          <Switch on={!!f.enabled} onChange={v => set('enabled', v)} />
          <span>{f.enabled ? 'فعال — کاربران می‌توانند بپرسند' : 'غیرفعال — پیام disabled نمایش داده می‌شود'}</span>
        </div>
        <div className="grid" style={{ gap: 10, marginTop: 14 }}>
          <label className="fld"><span>ارائه‌دهنده</span>
            <select className="inp" value={f.provider} onChange={e => {
              const pid = e.target.value;
              const prov = (cat?.providers || []).find(p => p.id === pid);
              /* با تغییر provider، مدلِ فعلی احتمالاً نامعتبر است ⇒ پیش‌فرض همان provider */
              setF(x => ({ ...x, provider: pid, model: prov?.default_model || x.model }));
            }}>
              {(cat?.providers || [{ id: 'gemini', label: 'Gemini' }, { id: 'openrouter', label: 'OpenRouter' }])
                .map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select></label>
          <label className="fld"><span>مدل {(() => {
            const prov = (cat?.providers || []).find(p => p.id === f.provider);
            const ids = (prov?.models || []).map(m => m.id);
            const isCustom = f.model && !ids.includes(f.model);
            return (
              <>
                <select className="inp" style={{ direction: 'ltr' }}
                        value={isCustom ? '__custom' : f.model}
                        onChange={e => set('model', e.target.value === '__custom' ? '' : e.target.value)}>
                  {(prov?.models || []).map(m => (
                    <option key={m.id} value={m.id}>{m.label}</option>))}
                  <option value="__custom">✏️ سفارشی (تایپ دستی)</option>
                </select>
                {isCustom && (
                  <input className="inp" style={{ direction: 'ltr', marginTop: 6 }}
                         placeholder="شناسه‌ی دقیق مدل" value={f.model}
                         onChange={e => set('model', e.target.value)} />)}
              </>);
          })()}</span></label>
          <label className="fld"><span>سهمیه‌ی روزانه‌ی هر کاربر</span>
            <input className="inp" type="number" min="0" max="1000" value={f.daily_limit}
                   onChange={e => set('daily_limit', e.target.value)} /></label>
          <label className="fld"><span>حالت تفکر</span>
            <select className="inp" value={f.thinking} onChange={e => set('thinking', e.target.value)}>
              <option value="auto">auto</option>
              <option value="high">high</option>
            </select></label>
          <div className="row">
            <B kind={cfg.has_api_key ? 'ok' : 'warn'}>{cfg.has_api_key ? '🔑 ●●●●●●●● · تنظیم شده' : '⚠️ کلید API ندارد'}</B>
            <span className="muted">Secret هرگز از API برگردانده نمی‌شود.</span>
            {me?.is_owner && <button className="btn sm" onClick={() => { setApiKey(''); setKeyOpen(true); }}>🔐 چرخش کلید</button>}
            {me?.is_owner && <button className="btn sm" onClick={async () => { try { setTestResult(await api.aiTest()); toast('اتصال هوشیار موفق بود ✅'); } catch (e) { toast(errText(e), 'err'); } }}>🧪 تست اتصال</button>}
          </div>
          {testResult && <div className="muted">پاسخ: {testResult.answer} · {Number(testResult.tokens || 0).toLocaleString('fa')} توکن · {Number(testResult.response_time_ms || 0).toLocaleString('fa')} ms · Request ID: <span className="code">{testResult.request_id}</span></div>}
        </div>
      </div>
      <div className="panel panel-pad">
        <b>پیام و پرامپت</b>
        <div className="grid" style={{ gap: 10, marginTop: 12 }}>
          <label className="fld"><span>System Prompt (۲۰ تا ۲۰هزار کاراکتر)</span>
            <textarea className="inp" rows={7} style={{ resize: 'vertical' }} value={f.system_prompt}
                      onChange={e => set('system_prompt', e.target.value)} /></label>
          <label className="fld"><span>پیام هنگام غیرفعال‌بودن سرویس</span>
            <input className="inp" value={f.disabled_message || ''}
                   onChange={e => set('disabled_message', e.target.value)} /></label>
          <div className="row">
            <button className="btn primary" disabled={busy || f.system_prompt.length < 20 || !f.model.trim()}
                    onClick={() => setConfirmSave(true)}>{busy ? '⏳ …' : '💾 بازبینی پیکربندی'}</button>
            <span className="muted">تغییرات در تنظیمات مشترک (`ai_*`) ثبت و در audit دیده می‌شود</span>
          </div>
        </div>
      </div>
    </div>
    {confirmSave && <Confirm danger text="پیکربندی فعال هوشیار برای همه کاربران تغییر می‌کند. اختلاف‌ها را بازبینی کنید." onNo={() => setConfirmSave(false)} onYes={async () => { setConfirmSave(false); await save(); }}>
      <DiffViewer before={{ enabled: cfg.enabled, provider: cfg.provider, model: cfg.model, daily_limit: cfg.daily_limit, thinking: cfg.thinking, system_prompt: cfg.system_prompt, disabled_message: cfg.disabled_message }} after={{ enabled: f.enabled, provider: f.provider, model: f.model, daily_limit: Number(f.daily_limit) || 0, thinking: f.thinking, system_prompt: f.system_prompt, disabled_message: f.disabled_message }} />
    </Confirm>}
    {keyOpen && <Modal title="🔐 چرخش API Key — فقط مالک" onClose={() => { setApiKey(''); setKeyOpen(false); }}>
      <input className="inp" type="password" autoComplete="new-password" style={{ width: '100%', direction: 'ltr' }} placeholder="کلید جدید…" value={apiKey} onChange={e => setApiKey(e.target.value)} />
      <div className="muted" style={{ marginTop: 8 }}>مقدار کلید هرگز نمایش، ذخیره در localStorage یا وارد audit نمی‌شود.</div>
      <div className="row" style={{ marginTop: 12 }}><button className="btn danger" disabled={apiKey.trim().length < 8} onClick={async () => { const secret = apiKey; setApiKey(''); setKeyOpen(false); try { await api.aiKeyRotate(secret); toast('API Key با موفقیت چرخش یافت ✅'); onSaved(); } catch (e) { toast(errText(e), 'err'); } }}>تأیید و چرخش</button><button className="btn" onClick={() => { setApiKey(''); setKeyOpen(false); }}>انصراف</button></div>
    </Modal>}
    </>
  );
}
