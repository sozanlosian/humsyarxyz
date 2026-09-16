import React, { useEffect, useMemo, useState } from 'react';
import { api, errText } from '../api.js';
import { Loading, ErrorState, B, DiffViewer, FaDateTime, FilterBar, PageHeader, toast, Switch, NoPerm, Empty, Confirm } from '../ui.jsx';

const faN = (n) => Number(n ?? 0).toLocaleString('fa-IR');

const CATS = {
  general:  { icon: '⚙️', label: 'عمومی' },
  logs:     { icon: '📣', label: 'گروه‌های لاگ' },
  donation: { icon: '💙', label: 'حمایت مالی' },
  backup:   { icon: '💾', label: 'بکاپ' },
  notif:    { icon: '🔔', label: 'پیش‌فرض اعلان‌ها' },
  time:     { icon: '🕰', label: 'زمان و تاریخ سیستم' },
};

// ⚙️🌊 WA2.3 — مرکز کنترل تنظیمات: مقدار فعلی + توضیح + آخرین تغییردهنده/زمان + ذخیره + audit
export default function Settings() {
  const [cats, setCats] = useState(null);
  const [cat, setCat] = useState('general');
  const [qs, setQs] = useState('');           // 🌊 موج Settings-Search
  const [err, setErr] = useState('');
  const [permErr, setPermErr] = useState(false);
  const [edited, setEdited] = useState({});   // key → value محلی
  const [notifApply, setNotifApply] = useState({}); // key → new_only | all
  const [pendingNotif, setPendingNotif] = useState(null);

  const load = async () => {
    setErr('');
    try {
      const list = (await api.settingsCenter()).categories || [];
      setCats(list);
      if (list.length && !list.some(c => c.key === cat)) setCat(list[0].key);
    }
    catch (e) {
      if (e.status === 403) setPermErr(true); else setErr(errText(e));
    }
  };
  useEffect(() => { load(); }, []);

  const cur = useMemo(() => (cats || []).find(c => c.key === cat), [cats, cat]);
  const valueOf = (it) => (it.key in edited ? edited[it.key] : it.value);

  const applySave = async (it, applyExisting = false) => {
    const v = valueOf(it);
    try {
      const r = await api.patchSetting(it.key, v, applyExisting);
      toast(applyExisting
        ? `«${it.label}» ذخیره و روی ${faN(r.affected_users)} کاربر فعلی اعمال شد ✅`
        : `«${it.label}» ذخیره شد ✅`);
      setEdited(x => { const y = { ...x }; delete y[it.key]; return y; });
      load();
    } catch (e) { toast(errText(e), 'err'); }
  };
  const save = (it) => {
    if (it.key.startsWith('notif_default:')) {
      setPendingNotif({ it, applyExisting: (notifApply[it.key] || 'new_only') === 'all' });
      return;
    }
    applySave(it, false);
  };

  if (permErr) return <NoPerm text="تنظیمات سیستم نیازمند مجوز «تنظیمات سیستم» (settings.manage) است" />;
  if (err) return <ErrorState error={err} onRetry={load} />;
  if (!cats) return <Loading rows={5} />;

  // 🌊 جست‌وجوی سراسری: فیلتر همه‌ی دسته‌ها بر اساس عنوان/توضیح/کلید
  const q = qs.trim();
  const filteredCats = q
    ? cats.map(c => ({
        ...c,
        items: c.items.filter(it =>
          (it.label || '').includes(q) || (it.desc || '').includes(q) || it.key.includes(q)),
      })).filter(c => c.items.length)
    : null;

  return (
    <>
      <PageHeader title="مرکز کنترل تنظیمات" description="تنظیمات مشترک ربات، مینی‌اپ و Web Admin با متادیتای تغییر و حسابرسی" />
      <FilterBar>
        <input className="inp" style={{ flex: 1, maxWidth: 380 }}
               placeholder="🔎 جست‌وجو در تنظیمات (عنوان/توضیح/کلید)…"
               value={qs} onChange={e => setQs(e.target.value)} />
        {q && <B kind="acc">{filteredCats.reduce((a, c) => a + c.items.length, 0).toLocaleString('fa')} نتیجه در {filteredCats.length.toLocaleString('fa')} دسته</B>}
      </FilterBar>
      <div className="settings-layout">
      <aside className="settings-nav" aria-label="دسته‌های تنظیمات">
        {cats.map(c => (
          <button key={c.key} className={`tab ${cat === c.key && !q ? 'on' : ''}`} onClick={() => { setCat(c.key); setQs(''); }}>
            {CATS[c.key]?.icon} {CATS[c.key]?.label || c.key}
            <span className="muted"> ({c.items.length.toLocaleString('fa')})</span>
          </button>
        ))}
      </aside>
      <div className="settings-main">
      {(filteredCats || (cur ? [cur] : [])).length === 0 ? <Empty text={q ? 'تنظیمی با این جست‌وجو نیست' : 'دسته‌ای نیست'} /> : (
        <div className="grid" style={{ gap: 10 }}>
          {(filteredCats || [cur]).map(cc => (
          <React.Fragment key={cc.key}>
          {q && <div className="h1" style={{ fontSize: 'var(--fs-section)', marginTop: 6 }}>{CATS[cc.key]?.icon} {CATS[cc.key]?.label || cc.key}</div>}
          {cc.items.map(it => (
            <div key={it.key} className="panel panel-pad">
              <div className="row" style={{ alignItems: 'flex-start' }}>
                <div style={{ flex: 1, minWidth: 220 }}>
                  <div className="row">
                    <b>{it.label}</b>
                    <span className="code" style={{ direction: 'ltr' }}>{it.key}</span>
                  </div>
                  <div className="muted" style={{ marginTop: 4, lineHeight: 1.7 }}>{it.desc}</div>
                  {(it.updated_by || it.updated_at) && (
                    <div className="muted" style={{ marginTop: 6 }}>
                      🕓 آخرین تغییر: {it.updated_by || '—'} · <FaDateTime value={it.updated_at} />
                      <B kind="acc" >🧭 در audit ثبت شده</B>
                    </div>
                  )}
                </div>
                <div style={{ minWidth: 240, display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-end' }}>
                  {it.type === 'bool' && (<>
                    <Switch on={!!valueOf(it)}
                            onChange={v => { setEdited(x => ({ ...x, [it.key]: v })); }} />
                    {it.key.startsWith('notif_default:') && (
                      <div className="grid" style={{ gap: 4, width: '100%' }}>
                        <label className="row"><input type="radio" name={`scope-${it.key}`}
                          checked={(notifApply[it.key] || 'new_only') === 'new_only'}
                          onChange={() => setNotifApply(x => ({ ...x, [it.key]: 'new_only' }))} /> فقط کاربران جدید</label>
                        <label className="row"><input type="radio" name={`scope-${it.key}`}
                          checked={(notifApply[it.key] || 'new_only') === 'all'}
                          onChange={() => setNotifApply(x => ({ ...x, [it.key]: 'all' }))} />
                          کاربران جدید + {faN(it.existing_users)} کاربر فعلی</label>
                      </div>
                    )}
                  </>)}
                  {it.type === 'text' && (
                    <textarea className="inp" rows={2} style={{ width: '100%' }}
                              value={valueOf(it) ?? ''}
                              onChange={e => setEdited(x => ({ ...x, [it.key]: e.target.value }))} />
                  )}
                  {(it.type === 'group' || it.type === 'link') && (
                    <input className="inp" style={{ width: '100%', direction: 'ltr' }}
                           placeholder={it.type === 'group' ? '-100…' : 'https://…'}
                           value={valueOf(it) ?? ''}
                           onChange={e => setEdited(x => ({ ...x, [it.key]: e.target.value }))} />
                  )}
                  {it.type === 'hour' && (
                    <input className="inp" type="number" min="0" max="23" style={{ width: 90 }}
                           value={valueOf(it) ?? ''}
                           onChange={e => setEdited(x => ({ ...x, [it.key]: e.target.value }))} />
                  )}
                  {it.type === 'number' && (
                    <input className="inp" type="number" min="0" dir="ltr" style={{ width: 180 }}
                           placeholder="خالی = پیش‌فرض سیستم"
                           value={valueOf(it) ?? ''}
                           onChange={e => setEdited(x => ({ ...x, [it.key]: e.target.value }))} />
                  )}
                  {it.type === 'readonly' && (
                    <B kind="acc">{it.value ? <FaDateTime value={it.value} /> : 'هنوز اجرا نشده'}</B>
                  )}
                  {it.type === 'technical_time' && <span className="code ltr">{it.value || '—'}</span>}
                  {it.type === 'info' && <B kind="acc">{it.value || '—'}</B>}
                  {!['readonly', 'technical_time', 'info'].includes(it.type) && (it.key in edited) && JSON.stringify(edited[it.key]) !== JSON.stringify(it.value) && (
                    <button className="btn primary sm" onClick={() => save(it)}>💾 ذخیره</button>
                  )}
                </div>
              </div>
            </div>
          ))}
          </React.Fragment>
          ))}
        </div>
      )}
      </div>
      </div>

      {pendingNotif && (
        <Confirm danger={pendingNotif.applyExisting}
          text={pendingNotif.applyExisting
            ? `این تغییر روی ${faN(pendingNotif.it.existing_users)} کاربر فعلی نیز اعمال می‌شود. مقدار قبلی: ${pendingNotif.it.value ? 'فعال' : 'غیرفعال'}؛ مقدار جدید: ${valueOf(pendingNotif.it) ? 'فعال' : 'غیرفعال'}. ادامه می‌دهید؟`
            : `این تغییر فقط default کاربران جدید را عوض می‌کند و کاربران فعلی دست‌نخورده می‌مانند. ادامه می‌دهید؟`}
          onYes={async () => { const p = pendingNotif; setPendingNotif(null); await applySave(p.it, p.applyExisting); }}
          onNo={() => setPendingNotif(null)} />
      )}

      <IdentityPolicyPanel />
      {/* 🔒🌊 موج ChannelLock — قفل اجباری عضویت کانال (سطح مالک؛ معادل admin:channel_lock ربات) */}
      <ChannelLockPanel />
    </>
  );
}

function IdentityPolicyPanel() {
  const [base, setBase] = useState(null); const [f, setF] = useState(null);
  const [err, setErr] = useState(''); const [confirm, setConfirm] = useState(false);
  const load = async () => { try { const r = await api.identityPolicy(); setBase(r.policy); setF(r.policy); setErr(''); } catch (e) { if (e.status !== 403) setErr(errText(e)); } };
  useEffect(() => { load(); }, []);
  if (!f && !err) return null; // 403: panel owner/permission-aware hidden
  if (err) return <div className="panel panel-pad" style={{ marginTop: 16 }}><ErrorState error={err} onRetry={load} /></div>;
  const words = key => (f[key] || []).join('\n');
  const setWords = (key, value) => setF(x => ({ ...x, [key]: value.split(/[,\n]/).map(s => s.trim()).filter(Boolean) }));
  const changed = JSON.stringify(base) !== JSON.stringify(f);
  const valid = Number(f.min_length) <= Number(f.max_length);
  const save = async () => { setConfirm(false); try { await api.identityPolicyUpdate(f); toast('سیاست نام‌نما ذخیره شد ✅'); load(); } catch (e) { toast(errText(e), 'err'); } };
  return <section className="panel panel-pad" style={{ marginTop: 16 }}>
    <div className="row"><div><b>🏷 سیاست نام‌نما و هویت</b><div className="muted">همان validator مشترک Bot، Mini App و Web؛ بدون rule موازی در مرورگر</div></div><span className="spacer" />
      <button className="btn primary sm" disabled={!changed || !valid} onClick={() => setConfirm(true)}>بازبینی و ذخیره</button></div>
    {!valid && <div className="muted" style={{ color: 'var(--bad)', marginTop: 8 }}>حداقل طول نمی‌تواند بیشتر از حداکثر باشد.</div>}
    <div className="form-grid" style={{ marginTop: 12 }}>
      <label className="fld"><span>حداقل طول</span><input className="inp" type="number" min="1" max="40" value={f.min_length} onChange={e => setF({ ...f, min_length: +e.target.value })} /></label>
      <label className="fld"><span>حداکثر طول</span><input className="inp" type="number" min="2" max="80" value={f.max_length} onChange={e => setF({ ...f, max_length: +e.target.value })} /></label>
      <label className="fld"><span>Cooldown تغییر (روز)</span><input className="inp" type="number" min="0" max="365" value={f.cooldown_days} onChange={e => setF({ ...f, cooldown_days: +e.target.value })} /></label>
      <label className="fld"><span>اجازه ایموجی</span><Switch on={!!f.allow_emoji} onChange={v => setF({ ...f, allow_emoji: v })} /></label>
      <label className="fld"><span>اجازه فاصله</span><Switch on={!!f.allow_spaces} onChange={v => setF({ ...f, allow_spaces: v })} /></label>
      <label className="fld"><span>Blacklist — هر خط یک واژه</span><textarea className="inp" rows={4} value={words('blacklist')} onChange={e => setWords('blacklist', e.target.value)} /></label>
      <label className="fld"><span>Reserved words — هر خط یک واژه</span><textarea className="inp" rows={4} value={words('reserved_words')} onChange={e => setWords('reserved_words', e.target.value)} /></label>
    </div>
    <div className="muted" style={{ marginTop: 8 }}>پیش‌نمایش قاعده: طول مجاز {faN(f.min_length)} تا {faN(f.max_length)}؛ ایموجی {f.allow_emoji ? 'مجاز' : 'غیرمجاز'}؛ فاصله {f.allow_spaces ? 'مجاز' : 'غیرمجاز'}.</div>
    {confirm && <Confirm danger text="تغییر policy بلافاصله روی اعتبارسنجی نام‌نما در همه کلاینت‌ها اثر می‌گذارد. ادامه می‌دهید؟" onNo={() => setConfirm(false)} onYes={save}>
      <DiffViewer before={base || {}} after={f} />
    </Confirm>}
  </section>;
}

function ChannelLockPanel() {
  const [chs, setChs] = useState(null);
  const [cid, setCid] = useState('');
  const [ctitle, setCtitle] = useState('');
  const [clink, setClink] = useState('');
  const [busy, setBusy] = useState(false);
  const [delId, setDelId] = useState(null);
  const load = async () => {
    try { setChs((await api.channelLock()).channels || []); }
    catch { setChs(null); }                 // غیرمالک: پنل پنهان می‌ماند
  };
  useEffect(() => { load(); }, []);
  if (chs === null) return null;
  const add = async () => {
    setBusy(true);
    try {
      await api.channelLockAdd({ id: cid.trim(), title: ctitle.trim(), invite_link: clink.trim() });
      toast('کانال اجباری افزوده شد 🔒'); setCid(''); setCtitle(''); setClink(''); load();
    } catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  const del = async (id) => {
    try { await api.channelLockDel(id); toast('کانال حذف شد 🗑'); load(); }
    catch (e) { toast(errText(e), 'err'); }
  };
  return (
    <div className="panel panel-pad" style={{ marginTop: 16 }}>
      <div className="row"><b>🔒 قفل اجباری عضویت کانال</b><span className="spacer" />
        {chs.length
          ? <B kind="warn">{faN(chs.length)} کانال فعال — کاربران عادی باید عضو همه باشند</B>
          : <B kind="ok">قفل غیرفعال است</B>}</div>
      <div className="sub" style={{ marginTop: 4 }}>ربات باید ادمین کانال باشد تا عضویت را بررسی کند · حذف/افزودن در audit (WARNING) ثبت می‌شود</div>
      <div className="grid" style={{ gap: 6, marginTop: 10 }}>
        {chs.map(c => (
          <div key={c.id} className="row" style={{ padding: '8px 10px', border: '1px solid var(--line)', borderRadius: 10 }}>
            <span>📣</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <b style={{ color: 'var(--txt)' }}>{c.title}</b>{' '}
              <span className="code muted">{c.id}</span>
              {c.invite_link && <div className="muted code" dir="ltr" style={{ fontSize: 'var(--fs-label)' }}>{c.invite_link}</div>}
            </div>
            <button className="btn sm danger" onClick={() => setDelId(c.id)}>🗑 حذف</button>
          </div>
        ))}
      </div>
      <div className="row" style={{ marginTop: 12, flexWrap: 'wrap', gap: 6 }}>
        <input className="inp" style={{ flex: 1, minWidth: 150 }} dir="ltr" placeholder="آیدی عددی کانال (با منفی) — مثل -1001234567890"
               value={cid} onChange={e => setCid(e.target.value)} />
        <input className="inp" style={{ flex: 1, minWidth: 120 }} placeholder="نام کانال"
               value={ctitle} onChange={e => setCtitle(e.target.value)} />
        <input className="inp" style={{ flex: 1, minWidth: 130 }} dir="ltr" placeholder="لینک دعوت (اختیاری)"
               value={clink} onChange={e => setClink(e.target.value)} />
        <button className="btn primary sm" disabled={busy || !cid.trim() || !ctitle.trim()} onClick={add}>
          {busy ? '⏳' : '➕ افزودن کانال'}
        </button>
      </div>
      {delId && (
        <Confirm danger
                 text={`حذف کانال «${chs.find(c => c.id === delId)?.title || delId}» از قفل اجباری؟ (کاربران دیگر موظف به عضویت در آن نیستند)`}
                 onYes={async () => { const id = delId; setDelId(null); await del(id); }}
                 onNo={() => setDelId(null)} />
      )}
    </div>
  );
}
