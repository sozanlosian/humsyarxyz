import React, { useEffect, useRef, useState, useCallback } from 'react';
import { api, errText } from '../api.js';
import { Stat, KpiCard, KpiGrid, Section, Loading, ErrorState, B, FaDateTime, RelativeTime, PageHeader, toast } from '../ui.jsx';

// 📊 داشبورد عملیات + ⚠️ نیازمند اقدام (WA2.7) + 🕓 فید فعالیت واقعی (WA2.7)
// 🌊 موج Dash-Personalize — نمایش/پنهان بخش‌ها (ترجیح محلی هر مرورگر، localStorage)
const WKEY = 'wa_dash_widgets';
const WIDGETS = [
  ['attn', '⚠️ نیازمند اقدام'],
  ['insights', '🧠 مرکز هوش'],
  ['kpis', '📊 کارت‌های عملیات'],
  ['sys', '📈 شاخص‌های سامانه'],
  ['feed', '🕓 جریان فعالیت'],
];

// 🌊 موج Parity-Final — نگاشت اکشن‌های هشدار ربات به مسیرهای SPA
const ALERT_GO = {
  'admin:pending': '/users?status=pending',
  'ticket:manage': '/tickets',
  'admin:stats_questions': '/analytics',
  'admin:stats_users': '/analytics',
  'admin:cat_users': '/users',
  'admin:cat_content': '/content',
  'report:manage:all': '/content',
};
const faW = ['این هفته', '۱ هفته پیش', '۲ هفته پیش', '۳ هفته پیش'];

function SparklinePro({ values, tone="acc", width=120, height=32 }) {
  if (!values || values.length < 2) return null;
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const range = Math.max(max - min, 1);
  const pad = 2;
  const stepX = (width - pad*2) / (values.length - 1);
  const points = values.map((v,i) => {
    const x = pad + i*stepX;
    const y = height - pad - ((v - min)/range)*(height - pad*2);
    return [x,y];
  });
  const lineD = points.map((p,i) => `${i===0?'M':'L'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ');
  const areaD = lineD + ` L${points[points.length-1][0].toFixed(1)},${height-pad} L${points[0][0].toFixed(1)},${height-pad} Z`;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className={`sparkline-pro is-${tone}`} width={width} height={height} aria-hidden="true">
      <path className="s-area" d={areaD} />
      <path className="s-line" d={lineD} />
    </svg>
  );
}

export default function Dashboard({ me, go }) {
  const [ov, setOv] = useState(null);
  const [stats, setStats] = useState(null);
  const [attn, setAttn] = useState(null);
  const [feed, setFeed] = useState(null);
  const [ins, setIns] = useState(null);        // 🌊 مرکز هوش (مرکز rule-based واقعی db)
  const [err, setErr] = useState('');
  const [prefsOpen, setPrefsOpen] = useState(false);
  const prefsRef = useRef(null);
  const [wcfg, setWcfg] = useState(() => {
    try { return JSON.parse(localStorage.getItem(WKEY)) || {}; } catch { return {}; }
  });
  const won = (k) => wcfg[k] !== false;
  const toggleW = (k) => setWcfg(s => {
    const n = { ...s, [k]: !(s[k] !== false) };
    try { localStorage.setItem(WKEY, JSON.stringify(n)); } catch { /* حریم خصوصی */ }
    return n;
  });
  useEffect(() => {
    if (!prefsOpen) return;
    const h = (e) => { if (prefsRef.current && !prefsRef.current.contains(e.target)) setPrefsOpen(false); };
    const esc = (e) => { if (e.key === 'Escape') setPrefsOpen(false); };
    document.addEventListener('mousedown', h);
    document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('mousedown', h); document.removeEventListener('keydown', esc); };
  }, [prefsOpen]);

  // CSV به‌صورت stream از سرور می‌آید؛ dataset کامل وارد RAM مرورگر نمی‌شود.
  const [expBusy, setExpBusy] = useState(false);
  const exportUsers = async () => {
    setExpBusy(true);
    try { await api.exportUsersCsv(); toast('خروجی CSV کاربران آماده شد'); }
    catch (e) { toast(errText(e), 'err'); }
    setExpBusy(false);
  };

  const [lastSync, setLastSync] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [liveBusy, setLiveBusy] = useState(false);

  const load = useCallback(async (isAuto=false) => {
    if (isAuto) setLiveBusy(true);
    else setErr('');
    try {
      const bundle = await api.dashboardBundle();
      setOv(bundle.overview || null);
      setStats(bundle.stats || null);
      setAttn(bundle.attention || { items: [], backup: null });
      setFeed(bundle.activity || []);
      setIns(bundle.insights || null);
      setLastSync(new Date().toISOString());
    } catch (e) { if (!isAuto) setErr(e); else toast(errText(e),'err'); }
    finally { if (isAuto) setLiveBusy(false); }
  }, []);

  useEffect(() => { load(false); }, [load]);
  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(() => load(true), 30000);
    return () => clearInterval(id);
  }, [autoRefresh, load]);

  const handleIntegrityRun = async () => {
    toast('در حال اجرای بررسی یکپارچگی…');
    try { const r = await api.dataQuality(); toast(`بررسی کامل شد — ${r.issues?.length ?? 0} مورد`); } catch(e){ toast(errText(e),'err'); }
  };
  const handleOrphanScan = async () => {
    toast('اسکن فایل‌های یتیم…');
    try { const r = await api.dataQuality(); const m = (r.issues||[]).filter(x=>String(x.kind).includes('orphan')).length; toast(m? `${m} فایل یتیم یافت شد` : 'هیچ فایل یتیمی نیست 🎉'); } catch(e){ toast(errText(e),'err'); }
  };
  const handleDlqRetry = async () => {
    try { const r = await api.dlqList(1,1); const total = r.total ?? r.items?.length ?? 0; if(!total) return toast('DLQ خالی است 🎉'); toast(`DLQ: ${total} پیام — به مرکز DLQ بروید`); go('/system?tab=dlq'); } catch(e){ toast(errText(e),'err'); }
  };
  const handleBackupNow = async () => {
    try { await api.backup('all'); toast('بکاپ آغاز شد — وضعیت در System → Backup'); } catch(e){ toast(errText(e),'err'); }
  };

  if (err) return <ErrorState error={err} onRetry={load} />;
  if (!ov) return <Loading rows={5} />;

  const cards = [
    { icon: '👥', label: 'کل کاربران', v: ov.total_users, tint: 'var(--acc)' },
    { icon: '📝', label: 'در انتظار تأیید', v: ov.pending_users, tint: 'var(--warn)', go: '/users?status=pending' },
    { icon: '🧾', label: 'رسیدهای در انتظار', v: ov.pending_payments, tint: 'var(--warn)', go: '/subscriptions' },
    { icon: '🧪', label: 'سوالات در انتظار بازبینی', v: ov.pending_questions, tint: 'var(--purple)', go: '/questions' },
    { icon: '🎫', label: 'تیکت‌های باز', v: ov.open_tickets, tint: 'var(--bad)', go: '/tickets' },
    { icon: '💎', label: 'اشتراک‌های فعال', v: ov.active_subs, tint: 'var(--teal)' },
    { icon: '⏳', label: 'اشتراک‌های نزدیک به پایان', v: ov.expiring_soon, tint: 'var(--warn)' },
    { icon: '🚩', label: 'گزارش‌های باز', v: ov.open_reports, tint: 'var(--warn)', go: '/content?tab=reports' },
  ].filter(card => card.v !== null && card.v !== undefined);
  const attnItems = (attn?.items || []).filter(i => i.count > 0);
  const activeAttn = attnItems.filter(i => !i.dismissed);
  const dismissedAttn = attnItems.filter(i => i.dismissed);
  const healthOk = activeAttn.filter(i=>i.severity==='critical').length === 0;
  const weekVals = (ins?.week_counts || []).slice().reverse(); // oldest->newest for sparkline
  return (
    <>
      <PageHeader title="داشبورد عملیات" description="مرکز فرماندهی زنده — وضعیت، صف‌های نیازمند اقدام و هوشِ عملیاتی"

        actions={<div className="menu-anchor" ref={prefsRef}>
          <button className="btn sm" title="سفارشی‌سازی ویجت‌ها" aria-label="سفارشی‌سازی داشبورد"
                  aria-haspopup="true" aria-expanded={prefsOpen ? 'true' : 'false'}
                  onClick={() => setPrefsOpen(x => !x)}>⚙️ ویجت‌ها</button>
          {prefsOpen && (
            <div className="colmenu colmenu--end" role="menu">
              {WIDGETS.map(([k, label]) => (
                <label key={k} className="colmenu-item">
                  <input type="checkbox" checked={won(k)} onChange={() => toggleW(k)} />
                  <span>{label}</span>
                </label>
              ))}
              <div className="muted" style={{ padding: '4px 8px', fontSize: 'var(--fs-caption)' }}>ترجیح فقط روی همین مرورگر ذخیره می‌شود</div>
            </div>
          )}
        </div>} />

      {/* ✨ Hybrid Pro — Live Pulse Bar */}
      <div className="glass-panel live-pulse-bar">
        <span className={`live-dot ${liveBusy ? 'warn' : healthOk ? '' : 'bad'}`} aria-hidden="true" />
        <b style={{fontSize:'var(--fs-label)'}}>{liveBusy ? 'در حال همگام‌سازی…' : healthOk ? 'زنده — همه صف‌ها پایش می‌شود' : 'نیازمند توجه — مورد بحرانی'}</b>
        <span className="pulse-meta">
          <span>آخرین همگام‌سازی: {lastSync ? <FaDateTime value={lastSync} /> : '—'}</span>
          <span style={{opacity:.5}}>•</span>
          <span>30ثانیه</span>
        </span>
        <div className="pulse-actions">
          <label className="row" style={{gap:6, fontSize:'var(--fs-label)', cursor:'pointer'}}>
            <input type="checkbox" checked={autoRefresh} onChange={e=>setAutoRefresh(e.target.checked)} /> خودکار
          </label>
          <button className="btn sm" onClick={()=>load(false)} disabled={liveBusy}>🔄 اکنون</button>
          <button className="btn sm" onClick={()=>{ const el=document.querySelector('.kpi-premium'); el?.scrollIntoView({behavior:'smooth'});}}>📊 KPI</button>
        </div>
      </div>

      {/* ⚙️ Automation Quick Bar — REAL ACTIONS ONLY */}
      <div className="automation-bar">
        <span className="auto-label">⚡ عملیات سریع:</span>
        <button className="btn sm" onClick={handleIntegrityRun} title="اجرای بررسی یکپارچگی داده (Data Quality)">🛡️ بررسی یکپارچگی</button>
        <button className="btn sm" onClick={handleOrphanScan} title="اسکن فایل‌های یتیم">🧹 یتیم‌ها</button>
        <button className="btn sm" onClick={handleDlqRetry} title="نمایش DLQ و تلاش مجدد">💀 DLQ</button>
        <button className="btn sm primary" onClick={handleBackupNow} title="بکاپ فوری">💾 بکاپ</button>
        <span className="muted" style={{marginInlineStart:'auto', fontSize:'var(--fs-caption)'}}>همه عملیات واقعی — با Audit</span>
      </div>

      {/* ⚠️ WA2.7 — نیازمند اقدام (کلیک → مستقیم به همان صف) */}
      {attn && won('attn') && (
        <div className={`panel panel-pad ${activeAttn.length ? 'panel--attention' : 'panel--clear'}`} style={{ marginBottom: 14 }}>
          <div className="row">
            <b>⚠️ نیازمند اقدام</b>
            <span className="spacer" />
            {attn.backup && (
              <B kind={attn.backup.enabled ? 'ok' : 'warn'}>
                💾 بکاپ خودکار {attn.backup.enabled ? 'فعال' : 'غیرفعال'}
                {attn.backup.last_run ? <> · آخرین: <FaDateTime value={attn.backup.last_run} /></> : null}
              </B>
            )}
            {!attnItems.length && <B kind="ok">همه‌ی صف‌ها خالی‌اند 🎉</B>}
          </div>
          {attnItems.length > 0 && (
            <div style={{ marginTop: 12 }}>
              {/* 🌊 W5 — گروه‌بندی معنایی (§۹۱): مالی/محتوا/پشتیبانی/سیستم */}
              {(() => {
                const GROUPS = [
                  ['💰 مالی', ['payments', 'wallet_issues']],
                  ['📚 محتوا', ['questions', 'reports', 'imports', 'data_quality']],
                  ['🧑‍🎓 کاربران و پشتیبانی', ['users', 'tickets']],
                  ['⚙️ سیستم', ['failed_jobs', 'outbox_backlog', 'outbox_scheduled', 'dlq', 'backup_issue']],
                ];
                const inGroup = new Set(GROUPS.flatMap(([, ks]) => ks));
                const rest = activeAttn.filter(i => !inGroup.has(i.key));
                const groups = GROUPS.map(([title, ks]) => [title, activeAttn.filter(i => ks.includes(i.key))])
                  .filter(([, items]) => items.length);
                if (rest.length) groups.push(['📌 سایر', rest]);
                // 🌊 W7 — dismiss control per item
                const DismissBtn = ({it}) => {
                  const [busy,setBusy]=React.useState(false);
                  const [show,setShow]=React.useState(false);
                  const [reason,setReason]=React.useState('');
                  const [hours,setHours]=React.useState(24);
                  const doDismiss = async()=>{ if(!reason.trim()||reason.trim().length<3) return toast('دلیل حداقل ۳ حرف','err'); setBusy(true); try{ await api.attentionDismiss(it.key, reason.trim(), Number(hours)); toast('هشدار بسته شد ✅'); const b=await api.dashboardBundle(); setAttn(b.attention); setShow(false); setReason(''); }catch(e){ toast(errText(e),'err'); } setBusy(false); };
                  return <>{!it.dismissed ? <div style={{display:'flex',gap:6,marginTop:6}}><button className="btn sm" title="بستن هشدار (با دلیل)" onClick={e=>{e.stopPropagation(); setShow(v=>!v);}} disabled={busy}>🔕 بستن</button>{show && <span className="panel panel-pad" style={{position:'absolute',zIndex:5,background:'var(--bg)',border:'1px solid var(--line)',padding:8,display:'flex',flexDirection:'column',gap:6,minWidth:220}} onClick={e=>e.stopPropagation()}><input className="inp" placeholder="دلیل بستن (مثلاً بررسی شد، هشدار نادرست)" value={reason} onChange={e=>setReason(e.target.value)} /><select className="inp" value={hours} onChange={e=>setHours(e.target.value)}><option value={24}>۲۴ ساعت</option><option value={72}>۷۲ ساعت</option><option value={168}>۱ هفته</option><option value={0}>دائم</option></select><div className="row" style={{gap:6}}><button className="btn primary sm" onClick={doDismiss} disabled={busy}>تأیید بستن</button><button className="btn sm" onClick={()=>setShow(false)}>لغو</button></div></span>}</div> : null}</>;
                };
                return <>{groups.map(([title, items]) => (
                  <div key={title} className="attn-group">
                    <div className="attn-group-title">{title}</div>
                    <div className="attn-grid">
                      {items.map(i => (
                        <div key={i.key} className={`attn-item ${i.severity || ''}`} style={{position:'relative', display:'flex', alignItems:'center', gap:8, padding:10, borderRadius:8, background:'var(--card)', cursor:'pointer'}} onClick={() => i.go && go(i.go)}>
                          <span style={{ fontSize: 'var(--fs-icon)' }}>{i.icon}</span>
                          <div style={{ flex: 1 }} onClick={() => i.go && go(i.go)}>
                            <div className="row"><b style={{ color: 'var(--txt)', fontSize: 'var(--fs-section)' }}>{Number(i.count).toLocaleString('fa')}</b>
                              {i.severity && <B kind={i.severity === 'critical' ? 'bad' : 'warn'}>{i.severity === 'critical' ? 'بحرانی' : 'هشدار'}</B>}</div>
                            <div className="muted">{i.label}</div>
                            {i.timestamp && <div className="muted" style={{ marginTop: 3 }}><FaDateTime value={i.timestamp} /></div>}
                          </div>
                          <DismissBtn it={i} />
                          <span className="muted">‹</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
                {dismissedAttn.length>0 && <div className="panel panel-pad" style={{marginTop:12, background:'color-mix(in srgb, var(--bg) 90%, var(--line))'}}><b>🔕 هشدارهای بسته‌شده ({dismissedAttn.length})</b><div className="muted" style={{marginTop:4}}>این موارد تا پایان بازه به‌عنوان خطا شمرده نمی‌شوند و اعلان کیف پول هم اسپم نمی‌کند. می‌توانی بازگردانی.</div><div className="grid" style={{marginTop:8, gap:8}}>{dismissedAttn.map(i=>{const RestoreBtn=()=>{const [b,setB]=React.useState(false); return <button className="btn sm" disabled={b} onClick={async e=>{e.stopPropagation(); setB(true); try{ await api.attentionRestore(i.key); toast('بازگردانی شد ✅'); const bb=await api.dashboardBundle(); setAttn(bb.attention);}catch(err){ toast(errText(err),'err'); } setB(false);}}>↩️ بازگردانی</button>;}; return <div key={i.key} className="row" style={{gap:8, background:'var(--card)', padding:8, borderRadius:8}}><span>{i.icon}</span><b>{i.label}</b><span className="muted">{i.dismiss_reason || '—'}</span><span className="spacer"/><B kind="acc">بسته‌شده</B>{i.dismissed_until ? <span className="muted" style={{fontSize:'var(--fs-caption)'}}>تا <FaDateTime value={i.dismissed_until}/></span> : <span className="muted">دائم</span>}<RestoreBtn/></div>;})}</div></div>}
                {activeAttn.length===0 && dismissedAttn.length>0 && <div className="muted" style={{marginTop:8, textAlign:'center'}}>همهٔ هشدارهای فعال بسته شده‌اند — داشبورد در حالت آرام 🎉</div>}
                {activeAttn.length===0 && dismissedAttn.length===0 && groups.length===0 && <div className="muted">موردی نیست</div>}
                </>;
              })()}
            </div>
          )}
        </div>
      )}

      {/* 🧠🌊 موج Parity-Final — مرکز هوش ربات (داده‌ی واقعی db.admin_insights؛ همان صفحه‌ی ربات) */}
      {ins && won('insights') && (
        <div className="panel panel-pad glass-panel" style={{ marginBottom: 14, position:'relative', overflow:'hidden' }}>
          <div style={{position:'absolute', insetBlockStart:0, insetInline:0, height:2, background:'linear-gradient(90deg, var(--c-acc), var(--c-teal))', opacity:.9}} />
          <div className="row"><b>🧠 مرکز هوش — پیش‌بینی و هشدارِ زنده</b><span className="spacer" />
            {ins.forecast_next_week != null && (
              <B kind="acc">🔮 پیش‌بینی هفته‌ی آینده: ~{Number(ins.forecast_next_week).toLocaleString('fa-IR')} ثبت‌نام</B>)}
          </div>
          <div className="sub" style={{ marginTop: 2 }}>هشدارهای rule-based روی داده‌ی واقعی — کلیک روی هر هشدار می‌برد به محل رسیدگی</div>
          <div className="grid g2" style={{ marginTop: 10 }}>
            <div>
              {(ins.alerts || []).length === 0
                ? <span className="muted">✅ هیچ هشدار فعالی نیست — همه‌چیز مرتب است.</span>
                : (ins.alerts || []).map((a, i) => (
                    <div key={i} className="insight-alert" title="رسیدگی"
                         onClick={() => ALERT_GO[a.action] && go(ALERT_GO[a.action])}>
                      <span>{a.icon}</span>
                      <div style={{ flex: 1 }}>
                        <b style={{ fontSize: 'var(--fs-body)' }}>{a.title}</b>
                        {a.detail && <div className="muted" style={{ fontSize: 'var(--fs-label)' }}>{a.detail}</div>}
                      </div>
                      <span className="muted">‹</span>
                    </div>
                  ))}
            </div>
            <div>
              <div className="muted" style={{ marginBottom: 6 }}>📈 روند ثبت‌نام ۴ هفته‌ی اخیر</div>
              {(ins.week_counts || []).map((c, i) => (
                <div key={i} className="minibar-row">
                  <span className="muted" style={{ minWidth: 76 }}>{faW[i]}</span>
                  <div className="minibar-track">
                    <div className="minibar-fill" style={{
                      width: `${Math.round(c * 100 / Math.max(1, ...(ins.week_counts || [1])))}%` }} />
                  </div>
                  <B kind="acc">{Number(c).toLocaleString('fa-IR')}</B>
                </div>
              ))}
              {(ins.top_admins || []).length > 0 && (<>
                <div className="muted" style={{ margin: '10px 0 6px' }}>👑 پرکارترین ادمین‌های فرعی (۷ روز)</div>
                {ins.top_admins.slice(0, 5).map((a, i) => (
                  <div key={i} className="row" style={{ fontSize: 'var(--fs-body)', padding: '2px 0' }}>
                    <span>{['🥇','🥈','🥉','4️⃣','5️⃣'][i]}</span>
                    <span style={{ flex: 1 }}>{a.name} {a.role ? <span className="muted">({a.role})</span> : ''}</span>
                    <B>{Number(a.count).toLocaleString('fa-IR')} کنش</B>
                  </div>
                ))}
              </>)}
            </div>
          </div>
        </div>
      )}

      {won('kpis') && (
        <div className="kpi-grid" style={{marginBottom:14}}>
          {cards.map((c, i) => {
            const tone = c.tint === 'var(--warn)' ? 'warn' : c.tint === 'var(--bad)' ? 'bad' : c.tint === 'var(--purple)' ? 'purple' : c.tint === 'var(--teal)' ? 'ok' : 'acc';
            // sparkline for first 4 cards if weekVals available
            const showSpark = i < 4 && weekVals.length >= 2;
            return (
              <div key={i} className={`kpi-premium is-${tone}`} onClick={() => c.go && go(c.go)} style={{ cursor: c.go ? 'pointer' : 'default' }} role={c.go ? 'button' : undefined} tabIndex={c.go ? 0 : -1} onKeyDown={e=>{ if(c.go && (e.key==='Enter'||e.key===' ')){ e.preventDefault(); go(c.go); }}}>
                <div className="row" style={{gap:8}}>
                  <span className="kpi-ic" style={{width:32,height:32,borderRadius:8,display:'grid',placeItems:'center',fontSize:16,background:'var(--c-acc-soft)'}}>{c.icon}</span>
                  <span className="kpi-label" style={{fontSize:'var(--fs-label)',color:'var(--c-txt2)',flex:1}}>{c.label}</span>
                  {c.go && <span className="muted">‹</span>}
                </div>
                <div className="kpi-value" style={{fontSize:'clamp(18px,1.6vw,24px)',fontWeight:850}}>{Number(c.v ?? 0).toLocaleString('fa')}</div>
                {showSpark ? <SparklinePro values={weekVals} tone={tone==='warn'?'warn':tone==='bad'?'bad':'acc'} /> : <div className="muted" style={{fontSize:'var(--fs-caption)',height:18}}>{c.go ? 'کلیک برای جزئیات' : '—'}</div>}
              </div>
            );
          })}
        </div>
      )}

      {stats && won('sys') && (() => {
        const today = Number(stats.active_today ?? 0);
        const othersAvg = Math.max(0, (Number(stats.active_week ?? 0) - today)) / 6;
        const delta = othersAvg > 0 ? Math.round((today - othersAvg) / othersAvg * 100) : null;
        return (
        <Section title="شاخص‌های زنده — نبضِ امروز" description="مقایسه با میانگین ۶ روز قبل · دادهٔ واقعی"
                 className="dash-metrics" >
          <KpiGrid>
            <KpiCard icon="📡" label="کاربران فعال امروز" tone="ok" enter="dw-enter-1"
                     value={today.toLocaleString('fa')} delta={delta}
                     hint="نسبت به میانگین ۶ روز قبل" />
            <KpiCard icon="📅" label="کاربران فعال هفته" tone="ok" enter="dw-enter-2"
                     value={Number(stats.active_week ?? 0).toLocaleString('fa')} />
            <KpiCard icon="🆕" label="ثبت‌نام‌های امروز" tone="acc" enter="dw-enter-3"
                     value={Number(stats.new_today ?? stats.today_new ?? 0).toLocaleString('fa')} />
            <KpiCard icon="📥" label="کل پاسخ‌های ثبت‌شده" tone="acc" enter="dw-enter-3"
                     value={Number(stats.total_answers ?? 0).toLocaleString('fa')} />
          </KpiGrid>
        </Section>
        );
      })()}

      {/* 🕓 WA2.7 — فید فعالیت واقعی */}
      {feed !== null && won('feed') && (
        <>
          <div className="h1" style={{ marginTop: 22, fontSize: 'var(--fs-section)' }}>🕓 جریان فعالیت</div>
          <div className="panel" style={{ marginTop: 10 }}>
            {feed.length === 0 && <div className="center-state">رویدادی نیست</div>}
            {feed.slice(0, 14).map(f => (
              <div key={f.id} className="feed-row">
                <span className="muted" style={{ minWidth: 132 }}><RelativeTime value={f.at} /></span>
                <span className={`sev ${(f.severity || '').toLowerCase()}`} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ color: 'var(--txt)' }}>{f.actor_name}</span>
                  {f.actor_role ? <span className="muted"> ({f.actor_role})</span> : null}
                  <span> — {f.action}</span>
                  {f.target_label ? <span className="hl"> · {f.target_label}</span> : null}
                </div>
                {f.module && <B>{f.module}</B>}
              </div>
            ))}
          </div>
        </>
      )}

      {/* 🌊 موج Export — خروجی داده (سمت مرورگر، از همان داده‌ی واقعی API) */}
      {me?.is_owner && (
        <>
          <div className="h1" style={{ marginTop: 22, fontSize: 'var(--fs-section)' }}>📥 خروجی داده</div>
          <div className="panel panel-pad" style={{ marginTop: 10 }}>
            <div className="row" style={{ flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
              <button className="btn" disabled={expBusy} onClick={exportUsers}>
                {expBusy ? '⏳ در حال آماده‌سازی…' : '⬇️ کاربران (CSV کامل)'}
              </button>
              <span className="muted" style={{ fontSize: 'var(--fs-label)' }}>
                همان داده‌ی واقعی جدول کاربران با صفحه‌بندی خودکار · دانلود مستقیم مرورگر (بدون IDM) — برای خروجی اکسل گروهی، از بخش «سیستم → خروجی اکسل» استفاده کنید.
              </span>
            </div>
          </div>
        </>
      )}
    </>
  );
}
