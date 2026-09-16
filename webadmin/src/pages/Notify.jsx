import React, { useEffect, useMemo, useState } from 'react';
import { api, errText } from '../api.js';
import { Loading, ErrorState, B, FaDateTime, PageHeader, toast, NoPerm, Empty, Confirm, Switch, Modal } from '../ui.jsx';
import { PersianDateTimePicker } from '../PersianDatePicker.jsx';
import { formatFaDateTime, isFutureInstant } from '../time.js';
import { writeHashQuery } from '../urlState.js';

const fa = (n) => Number(n ?? 0).toLocaleString('fa-IR');
const STEPS = [
  ['مخاطب', '🎯'],
  ['محتوا', '✍️'],
  ['پیش‌نمایش', '👁'],
  ['زمان‌بندی', '🗓'],
  ['تأیید و ارسال', '📢'],
];

// 🔔📢 جادوگر ارسال همگانی (موج Broadcast-Wizard) — ۵ گام کامل:
// مخاطب ← محتوا ← پیش‌نمایش ← زمان‌بندی (فوری/زمان‌دار) ← تأیید ← ارسال.
// بک‌اند: همان /api/admin/broadcast* سطح مالک (آیینه‌ی دقیق payload مینی‌اپ).
// ⚠️ هیچ endpoint سطح مالک آزاد نشده — فقط UX کامل‌تر شده است.
export default function Notify({ route = '', go }) {
  const initial = useMemo(() => new URLSearchParams(route.split('?')[1] || ''), []);
  const [step, setStep] = useState(Math.min(5, Math.max(1, Number(initial.get('step')) || 1)));
  const [scope, setScope] = useState(initial.get('scope') || 'all');
  const [intakes, setIntakes] = useState([]);
  const [intake, setIntake] = useState(initial.get('intake') || '');
  const [group, setGroup] = useState(initial.get('group') || '1');
  const [role, setRole] = useState(initial.get('role') || '');
  const [subscriptionStatus, setSubscriptionStatus] = useState(initial.get('subscription') || 'active');
  const [audienceOptions, setAudienceOptions] = useState({ roles: [], subscription_statuses: [] });
  const [text, setText] = useState('');
  const [messageType, setMessageType] = useState('text');
  const [media, setMedia] = useState(null); const [fileId, setFileId] = useState(''); const [caption, setCaption] = useState('');
  const [uploading, setUploading] = useState(false); const [aiOpen, setAiOpen] = useState(false); const [aiNotes, setAiNotes] = useState('');
  const [count, setCount] = useState(null);
  const [mode, setMode] = useState('now');           // now | later
  const [sendAt, setSendAt] = useState('');
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(null);            // {queued, scheduled}
  const [history, setHistory] = useState(null);
  const [runs, setRuns] = useState(null);
  const [runDetail, setRunDetail] = useState(null);
  const [campaignDetail, setCampaignDetail] = useState(null);
  const [sched, setSched] = useState(null);          // 🌊 ارسال‌های زمان‌دار در انتظار
  const [cancelOf, setCancelOf] = useState(null);
  const [auxErr, setAuxErr] = useState('');
  const [segments, setSegments] = useState([]);
  const [drafts, setDrafts] = useState([]);
  const [saveOpen, setSaveOpen] = useState(null); // segment | draft
  const [saveName, setSaveName] = useState('');
  const [saveShared, setSaveShared] = useState(false);
  const [deleteSaved, setDeleteSaved] = useState(null);
  const [denied, setDenied] = useState(false);       // سطح مالک

  useEffect(() => { writeHashQuery('/notify', { step: step > 1 ? step : '', scope: scope !== 'all' ? scope : '',
    intake: (scope === 'intake' || scope === 'intake_group') ? intake : '', group: scope === 'intake_group' ? group : '',
    role: scope === 'role' ? role : '', subscription: scope === 'subscription' ? subscriptionStatus : '' });
  }, [step, scope, intake, group, role, subscriptionStatus]);
  useEffect(() => {
    api.waIntakes().then(r => setIntakes(r.intakes || [])).catch(() => {});
    api.broadcastOptions().then(r => setAudienceOptions({ roles: r.roles || [], subscription_statuses: r.subscription_statuses || [] })).catch(() => {});
    loadHist(); loadRuns(); loadSched(); loadSaved();
  }, []);
  const loadSaved = async () => {
    try {
      const [s, d] = await Promise.all([api.savedFilters('broadcast_segment'), api.savedFilters('broadcast_draft')]);
      setSegments(s.filters || []); setDrafts(d.filters || []);
    } catch { setSegments([]); setDrafts([]); }
  };
  const loadSched = async () => {
    try { setSched((await api.broadcastScheduled()).scheduled || []); }
    catch { setSched([]); }
  };
  const cancelBatch = async () => {
    const it = cancelOf;
    setCancelOf(null);
    try {
      const r = await api.broadcastCancel(it.campaign_id);
      toast(`ارسال زمان‌دار برای ${fa(r.cancelled)} گیرنده لغو شد 🗑`);
      loadSched(); loadHist();
    } catch (e) { toast(errText(e), 'err'); loadSched(); }
  };
  const loadHist = async () => {
    try { setHistory((await api.broadcastHistory()).history || []); }
    catch (e) {
      if (e.status === 403) { setDenied(true); setHistory([]); }
      else setHistory([]);
    }
  };
  const loadRuns = async () => {
    try { setRuns((await api.notifRuns()).runs || []); }
    catch (e) { if (e.status !== 403) setAuxErr(errText(e)); setRuns([]); }
  };
  const retry = async (id) => {
    try {
      const r = await api.notifRetry(id);
      toast(`${fa(r.requeued)} گیرنده دوباره در صف قرار گرفت 🔁`);
      loadRuns();
    } catch (e) { toast(errText(e), 'err'); }
  };

  const intakeLabel = (code) => intakes.find(i => (i.code || i) === code)?.label
    || intakes.find(i => (i.code || i) === code)?.code || code;
  const target = useMemo(() => {
    const t = { scope };
    if (scope === 'intake' || scope === 'intake_group') t.intake = intake;
    if (scope === 'intake_group') t.group = group;
    if (scope === 'role') t.role = role;
    if (scope === 'subscription') t.subscription_status = subscriptionStatus;
    return t;
  }, [scope, intake, group, role, subscriptionStatus]);
  const audienceLabel = useMemo(() => {
    if (scope === 'all') return 'همه‌ی کاربران تأییدشده';
    if (scope === 'intake') return `ورودی «${intakeLabel(intake)}»`;
    if (scope === 'intake_group') return `ورودی «${intakeLabel(intake)}» — گروه ${fa(group)}`;
    if (scope === 'role') return `نقش «${audienceOptions.roles.find(x => x.key === role)?.label || role}»`;
    return audienceOptions.subscription_statuses.find(x => x.key === subscriptionStatus)?.label || 'وضعیت اشتراک';
  }, [scope, intake, group, role, subscriptionStatus, audienceOptions, intakes]);

  const uploadMedia = async () => {
    if (!media || messageType === 'text') return;
    setUploading(true);
    try { const fd = new FormData(); fd.append('media_type', messageType); fd.append('file', media); const r = await api.broadcastUpload(fd); setFileId(r.file_id); toast('رسانه در تلگرام آماده شد ✅'); }
    catch (e) { toast(errText(e), 'err'); setFileId(''); }
    setUploading(false);
  };
  const payloadBody = () => ({ text: messageType === 'text' ? text.trim() : '', message_type: messageType,
    file_id: messageType === 'text' ? '' : fileId, caption: messageType === 'text' ? '' : caption.trim(), target, send_at: null });
  const testSend = async () => { try { await api.broadcastTest(payloadBody()); toast('پیام آزمایشی به تلگرام شما ارسال شد ✅'); } catch (e) { toast(errText(e), 'err'); } };
  const generateDraft = async () => { try { const r = await api.aiBroadcastDraft(aiNotes.trim()); setText(r.draft || ''); setMessageType('text'); setAiOpen(false); toast('پیش‌نویس هوشیار آماده شد'); } catch (e) { toast(`${errText(e)} — نوشتن دستی همچنان فعال است`, 'err'); } };

  const preview = async () => {
    setBusy(true);
    try {
      const r = await api.broadcastPreview({ target });
      setCount(r.recipient_count);
      setStep(3);
      if (!r.recipient_count) toast('برای این مخاطب، گیرنده‌ای یافت نشد ⚠️', 'err');
    } catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };

  const send = async () => {
    setBusy(true);
    try {
      const body = { text: messageType === 'text' ? text.trim() : '', message_type: messageType,
        file_id: messageType === 'text' ? '' : fileId, caption: messageType === 'text' ? '' : caption.trim(), target, send_at: null };
      if (mode === 'later') body.send_at = sendAt;
      const r = await api.broadcast(body);
      setSent({ queued: r.queued || 0, scheduled: !!r.scheduled });
      loadHist(); loadSched();
    } catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  const reset = () => {
    setStep(1); setScope('all'); setIntake(''); setGroup('1'); setRole(''); setSubscriptionStatus('active'); setText('');
    setMessageType('text'); setMedia(null); setFileId(''); setCaption('');
    setCount(null); setMode('now'); setSendAt(''); setSent(null);
  };
  const saveCurrent = async () => {
    if (!saveName.trim() || !saveOpen) return;
    const isDraft = saveOpen === 'draft';
    try {
      await api.saveFilter({ name: saveName.trim(), scope: isDraft ? 'broadcast_draft' : 'broadcast_segment', shared: saveShared,
        filters: isDraft ? { scope, intake, group, role, subscriptionStatus, text, messageType, fileId, caption, mode, sendAt } : { scope, intake, group, role, subscriptionStatus } });
      toast(isDraft ? 'پیش‌نویس ذخیره شد' : 'Segment مخاطبان ذخیره شد');
      setSaveOpen(null); setSaveName(''); setSaveShared(false); loadSaved();
    } catch (e) { toast(errText(e), 'err'); }
  };
  const applySaved = (item, isDraft = false) => {
    const f = item.filters || {};
    setScope(f.scope || 'all'); setIntake(f.intake || ''); setGroup(f.group || '1');
    setRole(f.role || ''); setSubscriptionStatus(f.subscriptionStatus || 'active');
    if (isDraft) { setText(f.text || ''); setMessageType(f.messageType || 'text'); setFileId(f.fileId || ''); setCaption(f.caption || ''); setMode(f.mode || 'now'); setSendAt(f.sendAt || ''); }
    setCount(null); setSent(null); setStep(isDraft && f.text ? 2 : 1);
    toast(`«${item.name}» بارگذاری شد`);
  };
  const removeSaved = async (item) => {
    try { await api.delFilter(item.id); loadSaved(); }
    catch (e) { toast(errText(e), 'err'); }
  };

  const mediaUrl = useMemo(() => media ? URL.createObjectURL(media) : '', [media]);
  useEffect(() => () => { if (mediaUrl) URL.revokeObjectURL(mediaUrl); }, [mediaUrl]);
  const sendAtFa = useMemo(() => sendAt ? formatFaDateTime(sendAt, { long: true }) : '', [sendAt]);

  const canNext1 = scope === 'all' || ((scope === 'intake' || scope === 'intake_group') && !!intake)
    || (scope === 'role' && !!role) || (scope === 'subscription' && !!subscriptionStatus);
  const canPreview = (messageType === 'text' ? text.trim().length >= 5 : !!fileId) && !busy;
  const canConfirm = mode === 'now' || (!!sendAt && isFutureInstant(sendAt));

  return (
    <>
      <PageHeader title="مرکز اعلان‌ها و ارسال همگانی" description="طراحی، پیش‌نمایش، زمان‌بندی، ارسال و پایش اعلان‌ها"
        actions={<><button className="btn" onClick={() => { setSaveName(''); setSaveShared(false); setSaveOpen('segment'); }}>💾 ذخیره Segment</button>
          <button className="btn" disabled={!text.trim()} onClick={() => { setSaveName(''); setSaveShared(false); setSaveOpen('draft'); }}>📝 ذخیره پیش‌نویس</button></>} />
      {auxErr && <div className="panel panel-pad" style={{ marginBottom: 12 }}><ErrorState title="بخشی از داده‌های اعلان بارگذاری نشد" error={auxErr} onRetry={() => { setAuxErr(''); loadHist(); loadRuns(); loadSched(); }} /></div>}
      <div className="notify-layout">
      {/* ═══ جادوگر ═══ */}
      <div className="panel panel-pad">
        <div className="h1" style={{ fontSize: 'var(--fs-section)' }}>📢 جادوگر ارسال همگانی</div>
        <div className="sub">از مسیر صف outbox ربات · ثبت در تاریخچه و مرکز اعلان مینی‌اپ</div>

        {denied ? (
          <NoPerm text="ارسال همگانی نیازمند مجوز broadcast.send است" />
        ) : sent ? (
          <div className="grid" style={{ gap: 12, marginTop: 14, textAlign: 'center', padding: '10px 0' }}>
            <div style={{ fontSize: 'var(--fs-icon-xl)' }}>{sent.scheduled ? '🗓' : '✅'}</div>
            <b style={{ fontSize: 'var(--fs-section)' }}>
              {sent.scheduled ? 'زمان‌بندی و در صف قرار گرفت' : 'ارسال به صف رفت'}
            </b>
            <div><B kind="acc">{fa(sent.queued)} گیرنده</B>{' '}
              <B kind={sent.scheduled ? 'warn' : 'ok'}>{sent.scheduled ? 'زمان‌دار' : 'فوری'}</B></div>
            <p className="muted" style={{ margin: 0 }}>
              {sent.scheduled ? `در ${sendAtFa || 'زمان تعیین‌شده'} ارسال می‌شود.` : 'ربات به‌تدریج و امن برای همه می‌فرستد.'}
            </p>
            <div className="row" style={{ justifyContent: 'center' }}>
              <button className="btn primary" onClick={reset}>📢 ارسال جدید</button>
              <button className="btn" onClick={() => { setSent(null); setStep(5); }}>بازبینی آخرین ارسال</button>
            </div>
          </div>
        ) : (
          <>
            {/* ریل گام‌ها */}
            <div className="wiz-steps" style={{ margin: '14px 0 16px' }}>
              {STEPS.map(([label, icon], i) => (
                <div key={label}
                     className={`wiz-step ${step === i + 1 ? 'on' : ''} ${step > i + 1 ? 'done' : ''}`}
                     onClick={() => { if (step > i + 1) setStep(i + 1); }}
                     title={step > i + 1 ? 'بازگشت به این گام' : ''}>
                  <span className="wiz-n">{step > i + 1 ? '✓' : fa(i + 1)}</span>
                  <span className="wiz-l">{icon} {label}</span>
                </div>
              ))}
            </div>

            {step === 1 && (
              <div className="grid" style={{ gap: 10 }}>
                {[
                  ['all', '🌐', 'همه‌ی کاربران تأییدشده', 'هر کاربر فعال سامانه'],
                  ['intake', '🏷', 'یک ورودی خاص', 'مثلاً فقط ورودی بهمن'],
                  ['intake_group', '👥', 'یک ورودی + گروه', 'هدف‌گیری آموزشی دقیق'],
                  ['role', '🛡', 'یک نقش دسترسی', 'اعضای واقعی نقش در RBAC'],
                  ['subscription', '💳', 'وضعیت اشتراک هامزیار', 'فعال، غیرفعال یا رو به پایان'],
                ].map(([v, icon, title, desc]) => (
                  <label key={v} className={`pick ${scope === v ? 'on' : ''}`}>
                    <input type="radio" checked={scope === v} onChange={() => setScope(v)} />
                    <span style={{ fontSize: 'var(--fs-icon)' }}>{icon}</span>
                    <span style={{ flex: 1 }}>
                      <b style={{ display: 'block', fontSize: 'var(--fs-card)' }}>{title}</b>
                      <span className="muted" style={{ fontSize: 'var(--fs-label)' }}>{desc}</span>
                    </span>
                  </label>
                ))}
                {(scope === 'intake' || scope === 'intake_group') && (
                  <select className="inp" value={intake} onChange={e => setIntake(e.target.value)}>
                    <option value="">انتخاب ورودی…</option>
                    {intakes.map(i => <option key={i.code || i} value={i.code || i}>{i.label || i.code || i}</option>)}
                  </select>
                )}
                {scope === 'role' && <select className="inp" value={role} onChange={e => setRole(e.target.value)}>
                  <option value="">انتخاب نقش…</option>{audienceOptions.roles.map(r => <option key={r.key} value={r.key}>{r.label}</option>)}
                </select>}
                {scope === 'subscription' && <select className="inp" value={subscriptionStatus} onChange={e => setSubscriptionStatus(e.target.value)}>
                  {audienceOptions.subscription_statuses.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
                </select>}
                {scope === 'intake_group' && (
                  <div className="row">
                    {['1', '2'].map(g => (
                      <label key={g} className={`pick ${group === g ? 'on' : ''}`} style={{ flex: 1 }}>
                        <input type="radio" checked={group === g} onChange={() => setGroup(g)} />
                        <b>{g === '1' ? '1️⃣ گروه ۱' : '2️⃣ گروه ۲'}</b>
                      </label>
                    ))}
                  </div>
                )}
                <button className="btn primary" disabled={!canNext1} onClick={() => setStep(2)}>ادامه ←</button>
              </div>
            )}

            {step === 2 && (
              <div className="grid" style={{ gap: 10 }}>
                <div className="row" style={{ alignItems: 'center' }}>
                  <b>محتوای کمپین</b><span className="spacer" />
                  <button className="btn sm" onClick={() => { setAiNotes(''); setAiOpen(true); }}>🤖 نوشتن با هوشیار</button>
                  <B kind={audienceLabel.startsWith('همه') ? 'acc' : 'purple'}>🎯 {audienceLabel}</B>
                </div>
                <div className="row" style={{ flexWrap: 'wrap' }}>{[['text','📝 متن'],['photo','🖼 عکس'],['video','🎥 ویدیو'],['document','📎 فایل'],['voice','🎙 ویس'],['audio','🎵 صدا']].map(([k,l]) => <button key={k} className={`btn sm ${messageType === k ? 'primary' : ''}`} onClick={() => { setMessageType(k); setFileId(''); setMedia(null); }}>{l}</button>)}</div>
                {messageType === 'text' ? <textarea className="inp" rows={8} placeholder="متن اعلان… (حداقل ۵ نویسه)" value={text} onChange={e => setText(e.target.value)} /> : <>
                  <input className="inp" type="file" onChange={e => { setMedia(e.target.files?.[0] || null); setFileId(''); }} />
                  <textarea className="inp" rows={4} maxLength={1024} placeholder="Caption اختیاری…" value={caption} onChange={e => setCaption(e.target.value)} />
                  <div className="row"><button className="btn primary sm" disabled={!media || uploading} onClick={uploadMedia}>{uploading ? '⏳ آپلود…' : '⬆️ آپلود به تلگرام'}</button>{fileId && <B kind="ok">رسانه آماده است</B>}</div>
                </>}
                <div className="row">
                  <span className="muted" style={{ fontSize: 'var(--fs-label)' }}>{messageType === 'text' ? `${fa(text.trim().length)} نویسه · HTML ساده پشتیبانی می‌شود` : `${fa(caption.length)} / ۱٬۰۲۴ نویسه Caption`}</span>
                  <span className="spacer" />
                  {messageType === 'text' && text.trim().length > 0 && text.trim().length < 5 && <B kind="bad">خیلی کوتاه</B>}
                </div>
                <div className="row">
                  <button className="btn" onClick={() => setStep(1)}>→ بازگشت</button>
                  <button className="btn primary" disabled={!canPreview} onClick={preview}>
                    {busy ? '⏳ شمار مخاطبان…' : '👁 پیش‌نمایش مخاطبان'}
                  </button>
                </div>
              </div>
            )}

            {step === 3 && (
              <div className="grid" style={{ gap: 10 }}>
                <div className="ct3-kv"><span className="muted">مخاطب</span><span>{audienceLabel}</span></div>
                <div className="ct3-kv"><span className="muted">گیرندگان</span>
                  <B kind={count ? 'acc' : 'bad'}>{count == null ? '…' : `${fa(count)} نفر`}</B>
                </div>
                <div className="panel panel-pad" style={{ background: 'var(--bg)' }}>
                  <div className="muted" style={{ fontSize: 'var(--fs-label)', marginBottom: 6 }}>پیش‌نمایش همان فایل و payload ارسالی:</div>
                  {messageType === 'photo' && mediaUrl && <img src={mediaUrl} alt="پیش‌نمایش عکس کمپین" style={{ maxWidth: '100%', maxHeight: 260, borderRadius: 10 }} />}
                  {messageType === 'video' && mediaUrl && <video src={mediaUrl} controls style={{ maxWidth: '100%', maxHeight: 260 }} />}
                  {(messageType === 'audio' || messageType === 'voice') && mediaUrl && <audio src={mediaUrl} controls style={{ width: '100%' }} />}
                  {messageType === 'document' && media && <div className="surface-inset">📎 {media.name} · {fa(Math.round(media.size / 1024))} KB</div>}
                  <div className="bubble user" style={{ maxWidth: '100%', whiteSpace: 'pre-wrap' }}>{messageType === 'text' ? text.trim() : `${{photo:'🖼 عکس',video:'🎥 ویدیو',document:'📎 فایل',voice:'🎙 ویس',audio:'🎵 صدا'}[messageType]}\n${caption.trim()}`}</div>
                </div>
                <button className="btn" onClick={testSend}>🧪 ارسال آزمایشی به تلگرام من</button>
                <p className="muted" style={{ fontSize: 'var(--fs-label)', margin: 0 }}>
                  📱 علاوه بر پیام تلگرام، در «مرکز اعلان» مینی‌اپ هم به‌عنوان اطلاعیه‌ی مدیریت ثبت می‌شود.
                </p>
                <div className="row">
                  <button className="btn" onClick={() => setStep(2)}>→ ویرایش</button>
                  <button className="btn primary" disabled={!count} onClick={() => setStep(4)}>ادامه ←</button>
                </div>
              </div>
            )}

            {step === 4 && (
              <div className="grid" style={{ gap: 10 }}>
                <label className={`pick ${mode === 'now' ? 'on' : ''}`}>
                  <input type="radio" checked={mode === 'now'} onChange={() => setMode('now')} />
                  <span style={{ fontSize: 'var(--fs-icon)' }}>⚡</span>
                  <span style={{ flex: 1 }}>
                    <b style={{ display: 'block', fontSize: 'var(--fs-card)' }}>ارسال فوری</b>
                    <span className="muted" style={{ fontSize: 'var(--fs-label)' }}>بلافاصله وارد صف ارسال می‌شود</span>
                  </span>
                </label>
                <label className={`pick ${mode === 'later' ? 'on' : ''}`}>
                  <input type="radio" checked={mode === 'later'} onChange={() => setMode('later')} />
                  <span style={{ fontSize: 'var(--fs-icon)' }}>🗓</span>
                  <span style={{ flex: 1 }}>
                    <b style={{ display: 'block', fontSize: 'var(--fs-card)' }}>ارسال زمان‌دار</b>
                    <span className="muted" style={{ fontSize: 'var(--fs-label)' }}>تا زمان مقرر در صف می‌ماند</span>
                  </span>
                </label>
                {mode === 'later' && (
                  <>
                    <PersianDateTimePicker value={sendAt} onChange={setSendAt} ariaLabel="زمان ارسال شمسی به وقت تهران" />
                    {sendAt && (
                      <div className="ct3-kv"><span className="muted">زمان ارسال</span>
                        <B kind={isFutureInstant(sendAt) ? 'warn' : 'bad'}>{sendAtFa}</B>
                      </div>
                    )}
                    {sendAt && !isFutureInstant(sendAt) &&
                      <span className="muted" style={{ color: 'var(--c-bad)', fontSize: 'var(--fs-label)' }}>زمان انتخابی در گذشته است — زمان آینده برگزینید.</span>}
                  </>
                )}
                <div className="row">
                  <button className="btn" onClick={() => setStep(3)}>→ بازگشت</button>
                  <button className="btn primary" disabled={!canConfirm} onClick={() => setStep(5)}>ادامه ←</button>
                </div>
              </div>
            )}

            {step === 5 && (
              <div className="grid" style={{ gap: 10 }}>
                <div className="ct3-kv"><span className="muted">مخاطب</span><span>{audienceLabel} — <B kind="acc">{fa(count)} نفر</B></span></div>
                <div className="ct3-kv"><span className="muted">زمان</span>
                  {mode === 'now' ? <B kind="ok">⚡ فوری</B> : <B kind="warn">🗓 {sendAtFa}</B>}
                </div>
                <div className="panel panel-pad" style={{ background: 'var(--bg)', fontSize: 'var(--fs-body)', color: 'var(--txt2)', whiteSpace: 'pre-wrap', maxHeight: 120, overflowY: 'auto' }}>
                  {messageType === 'text' ? text.trim() : `${messageType.toUpperCase()} · ${caption.trim() || 'بدون caption'}`}
                </div>
                <p className="muted" style={{ fontSize: 'var(--fs-label)', margin: 0 }}>
                  ⚠️ این عمل در تاریخچه و حسابرسی (severity: HIGH) ثبت می‌شود و قابل بازگشت نیست.
                </p>
                <div className="row">
                  <button className="btn" onClick={() => setStep(4)}>→ بازگشت</button>
                  <button className="btn danger" style={{ flex: 1 }} disabled={busy} onClick={send}>
                    {busy ? '⏳ در حال ثبت در صف…' : `📢 ارسال قطعی به ${fa(count)} نفر`}
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* ═══ ستون کناری: زمان‌دارها + تاریخچه + اجراها ═══ */}
      <div className="grid" style={{ gap: 14, alignContent: 'start' }}>
        {(segments.length > 0 || drafts.length > 0) && <div className="panel panel-pad">
          <b>نماهای ذخیره‌شده</b>
          {!!segments.length && <div style={{ marginTop: 8 }}><div className="muted">Segmentهای مخاطبان</div>
            <div className="row" style={{ marginTop: 5 }}>{segments.map(s => <span className="chip" key={s.id}>
              <button type="button" className="chip-link" onClick={() => applySaved(s)}>{s.shared ? '👥 ' : ''}{s.name}</button>
              {s.editable !== false && <button className="chip-x" aria-label={`حذف Segment ${s.name}`} onClick={() => setDeleteSaved(s)}>✕</button>}
            </span>)}</div></div>}
          {!!drafts.length && <div style={{ marginTop: 8 }}><div className="muted">پیش‌نویس‌ها</div>
            <div className="grid" style={{ gap: 5, marginTop: 5 }}>{drafts.map(d => <div className="row" key={d.id}>
              <button className="btn sm" style={{ flex: 1, textAlign: 'right' }} onClick={() => applySaved(d, true)}>📝 {d.shared ? '👥 ' : ''}{d.name}</button>
              {d.editable !== false && <button className="btn sm danger" aria-label={`حذف پیش‌نویس ${d.name}`} onClick={() => setDeleteSaved(d)}>🗑</button>}
            </div>)}</div></div>}
        </div>}
        {/* 🌊 موج Notif-Scheduled — ارسال‌های زمان‌دار در انتظار + لغو */}
        {!denied && sched !== null && (
          <div className="panel panel-pad">
            <div className="row"><b>🗓 ارسال‌های زمان‌دار در انتظار</b><span className="spacer" />
              <B kind={sched.length ? 'warn' : 'ok'}>{fa(sched.length)}</B>
              <button className="btn sm" onClick={loadSched} aria-label="تازه‌سازی ارسال‌های زمان‌دار">🔄</button></div>
            {sched.length === 0 ? (
              <p className="muted" style={{ marginTop: 8 }}>ارسال زمان‌داری در صف نیست.</p>
            ) : (
              <div className="grid" style={{ gap: 8, marginTop: 10 }}>
                {sched.map((it, i) => (
                  <div key={i} className="panel panel-pad" style={{ background: 'var(--bg)' }}>
                    <div className="row" style={{ flexWrap: 'wrap', gap: 5 }}>
                      <B kind="warn">🗓 <FaDateTime value={it.send_at} /></B>
                      <B kind="acc">{fa(it.total)} گیرنده</B>
                      <span className="spacer" />
                      <button className="btn sm danger" onClick={() => setCancelOf(it)}>🗑 لغو ارسال</button>
                    </div>
                    <div style={{ marginTop: 6, fontSize: 'var(--fs-body)', color: 'var(--txt2)' }}>{it.payload?.text || it.payload?.caption || `[${it.message_type}]`}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="panel panel-pad">
          <div className="row"><b>تاریخچه‌ی ارسال‌های همگانی</b><span className="spacer" />
            <button className="btn sm" onClick={loadHist} aria-label="تازه‌سازی تاریخچه ارسال‌ها">🔄</button></div>
          {!history ? <Loading rows={3} /> : !history.length ? (
            <Empty icon="📭" text="ارسالی ثبت نشده است" />
          ) : (
            <div className="grid" style={{ gap: 8, marginTop: 10 }}>
              {history.map((h, i) => {
                const pending = Math.max(0, (h.total || 0) - (h.success || 0) - (h.failed || 0) - (h.skipped || 0));
                const pct = h.total ? Math.round(((h.success || 0) / h.total) * 100) : 0;
                return (
                  <div key={i} className="panel panel-pad" style={{ background: 'var(--bg)' }}>
                    <div className="row" style={{ flexWrap: 'wrap', gap: 5 }}>
                      <B kind="acc">{fa(h.total)} نفر</B>
                      <B kind="ok">✔ {fa(h.success)}</B>
                      {h.failed > 0 && <B kind="bad">✖ {fa(h.failed)}</B>}
                      {h.skipped > 0 && <B>⏭ {fa(h.skipped)}</B>}
                      {pending > 0 && <B kind="warn">⏳ {fa(pending)}</B>}
                      <B>{h.source === 'bot' ? 'Bot' : 'Web'}</B>
                      <span className="spacer" />
                      <button className="btn sm" onClick={() => { const a = h.audience || { scope: 'all' }; const p = h.payload || {}; reset(); setScope(a.scope || 'all'); setIntake(a.intake || ''); setGroup(a.group || '1'); setRole(a.role || ''); setSubscriptionStatus(a.subscription_status || 'active'); setMessageType(p.type || 'text'); setText(p.text || ''); setFileId(p.file_id || ''); setCaption(p.caption || ''); setStep(2); }}>📄 تکثیر Campaign</button>
                      <button className="btn sm" onClick={() => setCampaignDetail(h.campaign_id)}>جزئیات</button>
                      {h.failed > 0 && <button className="btn sm" onClick={async () => { try { const r = await api.broadcastRetryFailed(h.campaign_id); toast(`${fa(r.requeued)} گیرنده دوباره در صف قرار گرفت`); loadHist(); } catch (e) { toast(errText(e), 'err'); } }}>🔁 Retry Failed</button>}
                      {h.correlation_id && <button className="btn sm" onClick={() => go?.(`/audit?correlation_id=${encodeURIComponent(h.correlation_id)}`)}>🧬 ردیابی</button>}
                      <FaDateTime value={h.created_at} />
                    </div>
                    <div className="minibar-track" style={{ marginTop: 7 }}>
                      <div className="minibar-fill" style={{ width: `${pct}%` }} />
                    </div>
                    <div style={{ marginTop: 6, fontSize: 'var(--fs-body)', color: 'var(--txt2)' }}>
                      {(h.payload?.text || h.payload?.caption || `[${h.message_type}]`).slice(0, 120)}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* 🌊 موج Poll-Notif — نظرسنجی کانال + فاصله‌ی اعلان منابع (سطح مالک) */}
        <PollPanel />
        <NotifIntervalPanel />

        {/* 🌊 WA2.7 — اجراهای جاب‌های اعلان + تلاش مجدد */}
        <div className="panel panel-pad">
          <div className="row"><b>🔔 اجراهای اخیر اعلان‌ها</b><span className="spacer" />
            <button className="btn sm" onClick={loadRuns} aria-label="تازه‌سازی اجراهای اعلان‌ها">🔄</button></div>
          {!runs ? <Loading rows={3} /> : !runs.length ? <p className="muted" style={{ marginTop: 10 }}>اجلاسی ثبت نشده — یا مجوز notifications.manage ندارید</p> : (
            <div className="grid" style={{ gap: 6, marginTop: 10 }}>
              {runs.map(r => (
                <div key={r.id} className="row" style={{ padding: '7px 0', borderBottom: '1px solid var(--line)' }}>
                  <B kind={r.status === 'done' || r.status === 'finished' ? 'ok' : r.failed > 0 ? 'warn' : 'acc'}>{r.status || '—'}</B>
                  <span style={{ minWidth: 130 }}>{r.job_name}</span>
                  <span className="muted">✔{fa(r.sent)} · ✖{fa(r.failed)} · {fa(r.total)}</span>
                  <span className="spacer" />
                  <FaDateTime value={r.started_at} />
                  <button className="btn sm" onClick={() => setRunDetail(r.id)}>جزئیات ‹</button>
                  {r.failed > 0 && <button className="btn sm" onClick={() => retry(r.id)}>🔁 تلاش مجدد</button>}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {runDetail && <NotificationRunDetail id={runDetail} go={go} onClose={() => setRunDetail(null)} onRetry={retry} />}
      {campaignDetail && <CampaignDetail id={campaignDetail} go={go} onClose={() => setCampaignDetail(null)} onRefresh={() => { loadHist(); loadSched(); }} />}
      {saveOpen && <Modal title={saveOpen === 'draft' ? 'ذخیره پیش‌نویس ارسال' : 'ذخیره Segment مخاطبان'} onClose={() => setSaveOpen(null)}>
        <p className="muted" style={{ marginBottom: 8 }}>{saveOpen === 'draft' ? 'مخاطب، متن و زمان‌بندی فعلی ذخیره می‌شود.' : `مخاطب فعلی: ${audienceLabel}`}</p>
        <input className="inp" style={{ width: '100%' }} placeholder="نام قابل تشخیص…" value={saveName} onChange={e => setSaveName(e.target.value)} />
        <label className="row" style={{ marginTop: 10 }}><input type="checkbox" checked={saveShared} onChange={e => setSaveShared(e.target.checked)} />اشتراک با مدیران دارای مجوز ارسال همگانی</label>
        <div className="row" style={{ marginTop: 12 }}><button className="btn primary" disabled={!saveName.trim()} onClick={saveCurrent}>ذخیره</button>
          <button className="btn" onClick={() => setSaveOpen(null)}>انصراف</button></div>
      </Modal>}
      {aiOpen && <Modal title="🤖 نوشتن اطلاعیه با هوشیار" onClose={() => setAiOpen(false)}><textarea className="inp" rows={6} style={{ width: '100%' }} placeholder="موضوع و نکات اصلی اطلاعیه…" value={aiNotes} onChange={e => setAiNotes(e.target.value)} /><div className="muted" style={{ marginTop: 8 }}>اگر AI ناموفق باشد، composer دستی بدون اختلال باقی می‌ماند.</div><div className="row" style={{ marginTop: 12 }}><button className="btn primary" disabled={aiNotes.trim().length < 3} onClick={generateDraft}>ساخت پیش‌نویس</button><button className="btn" onClick={() => setAiOpen(false)}>انصراف</button></div></Modal>}
      {deleteSaved && <Confirm danger text={`«${deleteSaved.name}» برای همیشه حذف شود؟`} onNo={() => setDeleteSaved(null)} onYes={() => { const item = deleteSaved; setDeleteSaved(null); removeSaved(item); }} />}
      {cancelOf && (
        <Confirm danger
                 text={`لغو ارسال زمان‌دار برای ${fa(cancelOf.total)} گیرنده؟ پیام‌ها از صف حذف می‌شوند و این عمل در حسابرسی (HIGH) ثبت می‌شود.`}
                 onYes={cancelBatch}
                 onNo={() => setCancelOf(null)} />
      )}
      </div>
    </>
  );
}


function CampaignDetail({ id, go, onClose, onRefresh }) {
  const [data, setData] = useState(null); const [err, setErr] = useState('');
  const load = () => { setData(null); setErr(''); api.broadcastCampaign(id).then(setData).catch(e => setErr(errText(e))); };
  useEffect(load, [id]);
  return <Modal wide title={`📢 Campaign · ${id}`} onClose={onClose}>{err ? <ErrorState error={err} onRetry={load} /> : !data ? <Loading rows={5} /> : <>
    <div className="grid g4"><div className="panel panel-pad"><b>{fa(data.campaign.total)}</b><div className="muted">Recipients</div></div><div className="panel panel-pad"><b className="ok-text">{fa(data.campaign.success)}</b><div className="muted">Success</div></div><div className="panel panel-pad"><b>{fa(data.campaign.skipped)}</b><div className="muted">Skipped</div></div><div className="panel panel-pad"><b className="bad-text">{fa(data.campaign.failed)}</b><div className="muted">Failed</div></div></div>
    <dl className="kv"><dt>Status</dt><dd><B>{data.campaign.status}</B></dd><dt>Source</dt><dd>{data.campaign.source}</dd><dt>Type</dt><dd>{data.campaign.message_type}</dd><dt>Correlation ID</dt><dd className="code">{data.campaign.correlation_id || '—'}</dd><dt>زمان‌بندی تهران</dt><dd><FaDateTime value={data.campaign.send_at} /></dd><dt>پایان</dt><dd><FaDateTime value={data.campaign.finished_at} /></dd></dl>
    {!!data.failures?.length && <div className="grid" style={{ gap: 5 }}><b>Failed recipients</b>{data.failures.map((x, i) => <div className="row" key={`${x.user_id}-${i}`}><span className="code">{x.user_id}</span><span className="muted">{x.error}</span></div>)}</div>}
    <div className="row" style={{ marginTop: 12 }}>{data.campaign.failed > 0 && <button className="btn" onClick={async () => { try { const r = await api.broadcastRetryFailed(id); toast(`${fa(r.requeued)} گیرنده دوباره در صف قرار گرفت`); load(); onRefresh(); } catch (e) { toast(errText(e), 'err'); } }}>🔁 Retry Failed</button>}{data.campaign.correlation_id && <button className="btn primary" onClick={() => go?.(`/audit?correlation_id=${encodeURIComponent(data.campaign.correlation_id)}`)}>🧬 Investigation Chain</button>}</div>
  </>}</Modal>;
}

function NotificationRunDetail({ id, go, onClose, onRetry }) {
  const [data, setData] = useState(null); const [err, setErr] = useState('');
  const load = () => { setErr(''); setData(null); api.notifRunDetail(id).then(r => setData(r.run)).catch(e => setErr(errText(e))); };
  useEffect(load, [id]);
  return <Modal wide title="🔔 جزئیات اجرای اعلان" onClose={onClose}>
    {err ? <ErrorState error={err} onRetry={load} /> : !data ? <Loading rows={5} /> : <>
      <div className="grid g4"><div className="panel panel-pad"><b>{fa(data.total)}</b><div className="muted">کل</div></div><div className="panel panel-pad"><b className="ok-text">{fa(data.sent)}</b><div className="muted">موفق</div></div><div className="panel panel-pad"><b>{fa(data.skipped)}</b><div className="muted">ردشده</div></div><div className="panel panel-pad"><b className="bad-text">{fa(data.failed)}</b><div className="muted">ناموفق</div></div></div>
      <dl className="kv"><dt>Job</dt><dd>{data.job_name}</dd><dt>وضعیت</dt><dd><B kind={data.status === 'completed' ? 'ok' : data.status === 'failed' ? 'bad' : 'warn'}>{data.status}</B></dd><dt>شروع</dt><dd><FaDateTime value={data.started_at} /></dd><dt>پایان</dt><dd><FaDateTime value={data.finished_at} /></dd><dt>Correlation ID</dt><dd className="code">{data.correlation_id || '—'}</dd></dl>
      {data.message_preview && <div className="surface-inset"><div className="muted">پیش‌نمایش پیام ذخیره‌شده</div><div style={{ whiteSpace: 'pre-wrap' }}>{data.message_preview}</div></div>}
      {data.error && <div className="badge bad" style={{ marginTop: 8 }}>{data.error}</div>}
      {!!data.failed_targets?.length && <div style={{ marginTop: 10 }}><b>گیرندگان ناموفق</b><div className="grid" style={{ gap: 4 }}>{data.failed_targets.map((target, index) => <div className="row" key={`${target.user_id}-${index}`}><span className="code">{target.user_id}</span><span className="muted">{target.error}</span></div>)}</div>{data.failed_targets_truncated && <div className="muted">فهرست به ۱۰۰ مورد محدود شده است.</div>}</div>}
      <div className="row" style={{ marginTop: 12 }}>{data.failed > 0 && <button className="btn" onClick={() => onRetry(id)}>🔁 تلاش مجدد ناموفق‌ها</button>}{data.correlation_id && <button className="btn primary" onClick={() => go?.(`/audit?correlation_id=${encodeURIComponent(data.correlation_id)}`)}>🧬 ردیابی Correlation</button>}</div>
    </>}
  </Modal>;
}

/* ── 📊🌊 پنل نظرسنجی کانال (موج Poll-Notif) — همان admin:poll_main ربات ── */
export function PollPanel() {
  const [st, setSt] = useState(null);               // {channel_id, configured}
  const [editing, setEditing] = useState(false);
  const [ch, setCh] = useState('');
  const [q, setQ] = useState('');
  const [opts, setOpts] = useState(['', '']);
  const [anon, setAnon] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const load = async () => {
    try { const r = await api.pollStatus(); setSt(r); setCh(r.channel_id || ''); }
    catch { setSt(null); }
  };
  useEffect(() => { load(); }, []);
  if (!st) return null;
  const saveCh = async () => {
    setBusy(true);
    try { await api.pollSetChannel(ch.trim()); toast('کانال نظرسنجی ذخیره شد 📊'); setEditing(false); load(); }
    catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  const validOpts = opts.map(o => o.trim()).filter(Boolean);
  const send = async () => {
    setConfirm(false); setBusy(true);
    try {
      await api.pollCreate(q.trim(), validOpts, anon);
      toast('نظرسنجی در کانال منتشر شد 🗳'); setQ(''); setOpts(['', '']); setAnon(false);
    } catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  return (
    <div className="panel panel-pad">
      <div className="row"><b>📊 نظرسنجی کانال</b><span className="spacer" />
        {st.configured
          ? <B kind="ok">کانال: <span className="code">{st.channel_id}</span></B>
          : <B kind="warn">کانال تنظیم نشده</B>}
        <button className="btn sm" onClick={() => setEditing(e => !e)}>{editing ? 'انصراف' : '✏️ تغییر کانال'}</button>
      </div>
      {editing && (
        <div className="row" style={{ marginTop: 10, gap: 6 }}>
          <input className="inp" style={{ flex: 1 }} dir="ltr" placeholder="@channel یا -100…"
                 value={ch} onChange={e => setCh(e.target.value)} />
          <button className="btn primary sm" disabled={busy || !ch.trim()} onClick={saveCh}>{busy ? '⏳' : 'ذخیره'}</button>
        </div>
      )}
      {st.configured && !editing && (<>
        <input className="inp" style={{ width: '100%', marginTop: 10 }} placeholder="سؤال نظرسنجی…"
               value={q} onChange={e => setQ(e.target.value)} maxLength={300} />
        <div className="grid" style={{ gap: 6, marginTop: 8 }}>
          {opts.map((o, i) => (
            <div key={i} className="row" style={{ gap: 6 }}>
              <input className="inp" style={{ flex: 1 }} placeholder={`گزینه‌ی ${fa(i + 1)}`} maxLength={100}
                     value={o}
                     onChange={e => setOpts(s => s.map((x, j) => j === i ? e.target.value : x))} />
              {opts.length > 2 && (
                <button className="btn sm danger" title="حذف گزینه" aria-label="حذف گزینه"
                        onClick={() => setOpts(s => s.filter((_, j) => j !== i))}>🗑</button>
              )}
            </div>
          ))}
        </div>
        <div className="row" style={{ marginTop: 8, flexWrap: 'wrap', gap: 8 }}>
          <button className="btn sm" disabled={opts.length >= 10}
                  onClick={() => setOpts(s => [...s, ''])}>➕ گزینه</button>
          <label className="row" style={{ gap: 6 }}>
            <Switch on={anon} onChange={setAnon} /><span className="muted">ناشناس</span>
          </label>
          <span className="spacer" />
          <button className="btn primary sm" disabled={busy || q.trim().length < 3 || validOpts.length < 2}
                  onClick={() => setConfirm(true)}>{busy ? '⏳' : '🗳 انتشار در کانال'}</button>
        </div>
      </>)}
      {confirm && (
        <Confirm text={`انتشار نظرسنجی «${q.trim().slice(0, 60)}» با ${fa(validOpts.length)} گزینه در کانال؟ (بلافاصله ارسال می‌شود)`}
                 onYes={send} onNo={() => setConfirm(false)} />
      )}
    </div>
  );
}

/* ── ⏱🌊 پنل فاصله‌ی اعلان منابع (موج Poll-Notif) — همان admin:notif_manage ربات ── */
export function NotifIntervalPanel() {
  const [st, setSt] = useState(null);
  const [hours, setHours] = useState(24);
  const [busy, setBusy] = useState(false);
  const load = async () => {
    try { const r = await api.notifSettings(); setSt(r); setHours(r.interval_hours ?? 24); }
    catch { setSt(null); }
  };
  useEffect(() => { load(); }, []);
  if (!st) return null;
  const save = async () => {
    setBusy(true);
    try { await api.notifSetInterval(Number(hours)); toast('فاصله‌ی اعلان ذخیره شد ⏱'); load(); }
    catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  return (
    <div className="panel panel-pad">
      <b>⏱ اعلان خودکار منابع جدید</b>
      <div className="row" style={{ marginTop: 10, gap: 6 }}>
        <span className="muted">هر</span>
        {[24, 48, 72].map(h => (
          <button key={h} className={`btn sm ${Number(hours) === h ? 'primary' : ''}`}
                  onClick={() => setHours(h)}>{fa(h)} ساعت</button>
        ))}
        <button className="btn primary sm" disabled={busy}
                onClick={save}>{busy ? '⏳' : 'ذخیره'}</button>
      </div>
      <div className="muted" style={{ marginTop: 8 }}>
        🕐 آخرین ارسال: <FaDateTime value={st.last_sent} />
      </div>
      {st.last_error && (
        <div className="badge bad" style={{ marginTop: 6 }} title={st.last_error}>
          خطای آخرین اجرا: {st.last_error.slice(0, 60)}…
        </div>
      )}
    </div>
  );
}
