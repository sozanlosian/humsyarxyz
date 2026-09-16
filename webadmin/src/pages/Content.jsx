import React, { useEffect, useMemo, useRef, useState } from 'react';
import { api, errText } from '../api.js';
import { Loading, ErrorState, B, PageHeader, Timeline, toast, Confirm, Modal, Empty, NoPerm } from '../ui.jsx';
import { ContentActionGroup, ContentBreadcrumb, ContentBulkBar, ContentCountBadge, ContentDensityToggle, ContentEmptyState, ContentErrorState, ContentIconButton, ContentItem, ContentKV, ContentMetric, ContentMoreActions, ContentPane, ContentReorderControls, ContentSection, ContentShell, ContentSkeleton, ContentStats, ContentToolbar, ContentWorkspace, FileTypeBadge, ScopeBadge, fileTypeIcon, useContentDensity, useDebouncedValue } from '../ContentPrimitives.jsx';
import { writeHashQuery } from '../urlState.js';
import SavedViews from '../SavedViews.jsx';

const TERM_ICON = '📚';
const KIND = {
  global:    { icon: '🌐', label: 'سراسری', kind: 'acc' },
  fork:      { icon: '⭐', label: 'Override', kind: 'warn' },
  exclusive: { icon: '🏷', label: 'اختصاصی', kind: 'purple' },
};
const CTYPE = { video: '🎬', ppt: '📽', pdf: '📕', note: '📝', test: '🧪', voice: '🎙' };
const EXT_MAP = { pdf: 'pdf', ppt: 'ppt', pptx: 'ppt', mp4: 'video', mov: 'video', mkv: 'video', webm: 'video', mp3: 'voice', ogg: 'voice', wav: 'voice', m4a: 'voice' };
const fa = (n) => Number(n ?? 0).toLocaleString('fa-IR');

// 📚🌊 WA2.1 — مرکز فرماندهی محتوا · 🌊 موج Content-Split:
// چیدمان سه‌ستونه‌ی دسکتاپ‌محور «درخت درس‌ها | جلسات | بازرس» روی همان APIهای
// موجود (بدون هیچ تغییر بک‌اندی) — همه‌ی اکشن‌های قبلی (fork/کلون/انتقال/حذف
// گروهی/reorder/آپلود چندفایلی/گزارش‌ها) حفظ شده‌اند.
import { RefsTab, ScheduleTab, FaqTab, ReportsTab } from './contentTabs.jsx';

const CCONTENT_TABS = [
  ['bs', '📚 علوم پایه'],
  ['refs', '📖 رفرنس‌ها'],
  ['schedule', '🗓 کلاس‌ها/برنامه'],
  ['faq', '❓ راهنما/FAQ'],
  ['reports', '🚩 گزارش‌ها'],
  ['import', '📥 درون‌ریزی URL'],
];

export default function Content({ route = '' }) {
  const params = new URLSearchParams(route.split('?')[1] || '');
  const requested = params.get('tab');
  const [tab, setTab] = useState(CCONTENT_TABS.some(([k]) => k === requested) ? requested : 'bs');
  useEffect(() => { if (CCONTENT_TABS.some(([k]) => k === requested)) setTab(requested); }, [requested]);
  const changeTab = value => { setTab(value); writeHashQuery('/content', { tab: value !== 'bs' ? value : '' }); };
  return (
    <>
      <div className="tabs content-tabs" role="tablist" aria-label="بخش‌های مدیریت محتوا">
        {CCONTENT_TABS.map(([k, label]) => (
          <button key={k} type="button" role="tab" aria-selected={tab === k} className={`tab ${tab === k ? 'on' : ''}`} onClick={() => changeTab(k)}>{label}</button>
        ))}
      </div>
      {tab === 'bs' && <BsTab initial={{ intake: params.get('intake') || '', q: params.get('q') || '', lesson: params.get('lesson') || null, session: params.get('session') || null }} />}
      {tab === 'refs' && <RefsTab />}
      {tab === 'schedule' && <ScheduleTab />}
      {tab === 'faq' && <FaqTab />}
      {tab === 'reports' && <ReportsTab />}
      {tab === 'import' && <UrlImportTab />}
    </>
  );
}

/* ═══  تب درون‌ریزی از URL — پایپ‌لاین راه‌دور ═══
   سرور فایل را دانلود و مستقیم به تلگرام منتقل می‌کند (§93).
   پیشرفت فقط از job state می‌آید (§112) — هیچ progress ساختگی نیست. */
const UI_STATUS_FA = {
  created: ['در صف', ''],
  validating: ['بررسی لینک', 'warn'],
  downloading: ['دریافت فایل', 'warn'],
  validating_file: ['بررسی فایل', 'warn'],
  uploading: ['انتقال به تلگرام', 'warn'],
  registering: ['ثبت محتوا', 'warn'],
  completed: ['کامل شد', 'ok'],
  failed: ['ناموفق', 'bad'],
  cancelled: ['لغو شد', ''],
  duplicate: ['تکراری', 'warn'],
};

function UrlImportTab() {
  const [form, setForm] = useState({ url: '', kind: 'qbank', target_id: '', lesson: '', topic: '', description: '', ctype: 'pdf' });
  const [jobs, setJobs] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(null);

  const load = () => api.urlImportJobs({ page: 1, per_page: 30 }).then(setJobs).catch(e => setErr(errText(e)));
  useEffect(() => { load(); }, []);
  // فقط تا وقتی job غیرنهایی داریم poll سبک (§49 — زیرساخت تازه نیست)
  useEffect(() => {
    const active = (jobs?.jobs || []).some(j => !['completed', 'failed', 'cancelled', 'duplicate'].includes(j.status));
    if (!active) return;
    const t = setInterval(load, 2500);
    return () => clearInterval(t);
  }, [jobs]);

  const submit = async () => {
    setBusy(true); setErr('');
    try {
      const r = await api.urlImportCreate({ ...form, idem: `wa-${Date.now()}-${Math.random().toString(36).slice(2, 8)}` });
      toast('Job درون‌ریزی ساخته شد — سرور در حال انتقال فایل است');
      setForm(f => ({ ...f, url: '' }));
      load();
    } catch (e) { setErr(errText(e)); }
    finally { setBusy(false); }
  };

  const act = async (id, fn) => { try { await fn(); load(); } catch (e) { toast(errText(e), 'err'); } };

  return (
    <div className="panel panel-pad" style={{ marginTop: 12 }}>
      <div className="row" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
        <b>📥 درون‌ریزی محتوا از URL</b>
        <span className="muted small">فایل روی سرور دریافت و مستقیماً به تلگرام منتقل می‌شود — دانلود/آپلود دستی لازم نیست.</span>
        <span className="spacer" />
        <button className="btn sm" onClick={load}>↻ تازه‌سازی</button>
      </div>

      <div className="grid" style={{ gap: 8, gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
        <input className="inp" dir="ltr" placeholder="https://example.com/file.pdf" value={form.url}
          onChange={e => setForm({ ...form, url: e.target.value })} />
        <select className="inp" value={form.kind} onChange={e => setForm({ ...form, kind: e.target.value })}>
          <option value="qbank">بانک سؤال (درس/مبحث)</option>
          <option value="bs">علوم پایه (جلسه)</option>
          <option value="refs">رفرنس (کتاب)</option>
        </select>
        <input className="inp" placeholder="شناسه مقصد (جلسه/کتاب — برای qbank خالی)" value={form.target_id}
          onChange={e => setForm({ ...form, target_id: e.target.value })} />
        {form.kind === 'qbank' && <>
          <input className="inp" placeholder="درس" value={form.lesson} onChange={e => setForm({ ...form, lesson: e.target.value })} />
          <input className="inp" placeholder="مبحث" value={form.topic} onChange={e => setForm({ ...form, topic: e.target.value })} />
        </>}
        {form.kind === 'bs' && (
          <select className="inp" value={form.ctype} onChange={e => setForm({ ...form, ctype: e.target.value })}>
            {['video', 'ppt', 'pdf', 'note', 'test', 'voice'].map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        )}
        <input className="inp" placeholder="توضیح (اختیاری)" value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} />
        <button className="btn primary" disabled={busy || !form.url.trim()} onClick={submit}>📥 شروع درون‌ریزی</button>
      </div>
      {err && <div className="state-description" style={{ color: 'var(--c-bad)', marginTop: 8 }}>{err}</div>}

      <div style={{ marginTop: 14 }}>
        {!jobs && <Loading rows={3} />}
        {jobs && (jobs.jobs || []).length === 0 && <Empty icon="📥" text="هنوز درون‌ریزی‌ای ثبت نشده" />}
        {jobs && (jobs.jobs || []).map(j => {
          const [label, kind] = UI_STATUS_FA[j.status] || [j.status, ''];
          const pct = j.progress?.percent;
          return (
            <div key={j.id} className="panel panel-pad" style={{ marginBottom: 8, background: 'var(--bg)' }}>
              <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
                <b style={{ direction: 'ltr' }}>{j.url_safe}</b>
                <B kind={kind}>{label}</B>
                <span className="muted small">{j.kind}{j.filename ? ` · ${j.filename}` : ''}{j.size ? ` · ${fa(j.size)}B` : ''}</span>
                <span className="spacer" />
                {!['completed', 'failed', 'cancelled', 'duplicate'].includes(j.status) &&
                  <button className="btn sm danger" onClick={() => act(j.id, () => api.urlImportCancel(j.id))}>لغو</button>}
                {['failed', 'duplicate'].includes(j.status) &&
                  <button className="btn sm" onClick={() => act(j.id, () => api.urlImportRetry(j.id, j.status === 'duplicate'))}>
                    {j.status === 'duplicate' ? 'ثبت با وجود تکرار' : '🔁 Retry'}</button>}
                <button className="btn sm" onClick={() => setOpen(open === j.id ? null : j.id)}>جزئیات</button>
              </div>
              {typeof pct === 'number' && (
                <div style={{ marginTop: 6, height: 6, background: 'var(--elev)', borderRadius: 4 }}>
                  <div style={{ width: `${pct}%`, height: 6, background: 'var(--acc)', borderRadius: 4 }} />
                </div>
              )}
              {j.progress?.bytes > 0 && <div className="muted small" style={{ marginTop: 4 }}>{fa(j.progress.bytes)}{j.progress.total ? ` / ${fa(j.progress.total)}` : ''} بایت دریافت شد</div>}
              {j.error && <div className="muted small" style={{ marginTop: 4, color: 'var(--c-bad)' }}>{j.error.code}: {j.error.message}</div>}
              {open === j.id && (
                <dl className="kv" style={{ marginTop: 8 }}>
                  <dt>وضعیت</dt><dd>{j.status}</dd>
                  <dt>SHA256</dt><dd className="code">{j.sha256 ? j.sha256.slice(0, 20) + '…' : '—'}</dd>
                  <dt>تلگرام</dt><dd>{j.telegram_file_id ? 'file_id ذخیره شد ✅' : '—'}</dd>
                  <dt>محتوا</dt><dd>{j.content_id ? `ثبت شد (${j.content_id.slice(0, 8)}…)` : '—'}</dd>
                  <dt>تلاش‌ها</dt><dd>{fa(j.retries)}</dd>
                  <dt>رویدادها</dt><dd>{(j.timeline || []).map(t => t.event).join(' ← ')}</dd>
                </dl>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ═══ تب علوم پایه — Split View سه‌ستونه ═══ */
function BsTab({ initial = {} }) {
  const [intake, setIntake] = useState(initial.intake || '');
  const [scopeKind, setScopeKind] = useState('global');
  const [tree, setTree] = useState(null);
  const [intakes, setIntakes] = useState([]);
  const [err, setErr] = useState('');
  const [permErr, setPermErr] = useState(false);
  const [openTerms, setOpenTerms] = useState({});
  const [q, setQ] = useState(initial.q || '');
  const [sel, setSel] = useState([]);            // session ids برای عملیات گروهی
  const [lesId, setLesId] = useState(initial.lesson);      // درس منتخب (ستون دوم)
  const [sesId, setSesId] = useState(initial.session);      // جلسه‌ی منتخب (بازرس)
  const [editLes, setEditLes] = useState(null);  // lesson
  const [editSes, setEditSes] = useState(null);  // {lesson_id, s}
  const [confirm, setConfirm] = useState(null);
  const [moveTo, setMoveTo] = useState(null);    // {ids:[…]}
  const [quick, setQuick] = useState(false);
  const [addLes, setAddLes] = useState(null);    // term برای درس جدید
  const [addSes, setAddSes] = useState(null);    // lesson برای جلسه جدید
  const [studentPreview, setStudentPreview] = useState(false);
  const [rootMove, setRootMove] = useState(null); // {kind,id,label,from}
  const [density, setDensity] = useContentDensity();
  const deferredQ = useDebouncedValue(q.trim(), 180);
  const firstLoad = useRef(true);
  const preserveSelection = useRef(false);

  const load = async () => {
    setErr('');
    try {
      const r = await api.contentTree(intake || undefined);
      setTree(r.tree || []);
      setIntakes(r.intakes || []); setScopeKind(r.scope_kind || 'global');
      if (!intake && r.intake) setIntake(r.intake);
    } catch (e) {
      if (e.status === 403) setPermErr(true);
      else setErr(errText(e));
    }
  };
  useEffect(() => {
    setTree(null); setSel([]);
    if (!firstLoad.current && !preserveSelection.current) { setLesId(null); setSesId(null); }
    firstLoad.current = false; preserveSelection.current = false; load();
  }, [intake]);
  useEffect(() => { writeHashQuery('/content', { intake, q: deferredQ, lesson: lesId || '', session: sesId || '' }); }, [intake, deferredQ, lesId, sesId]);

  // انتخاب‌ها به‌صورت مشتق از درخت — بعد از هر reload همیشه تازه‌اند
  const selLesson = useMemo(() => {
    for (const t of (tree || [])) {
      const l = t.lessons.find(x => x.id === lesId);
      if (l) return { ...l, term: t.term, _tLessons: t.lessons };
    }
    return null;
  }, [tree, lesId]);
  const selSession = useMemo(
    () => (selLesson ? (selLesson.sessions.find(s => s.id === sesId) || null) : null),
    [selLesson, sesId]);
  // اگر درس/جلسه‌ی منتخب بعد از reload دیگر وجود نداشت، انتخاب پاک شود
  useEffect(() => { if (tree && lesId && !selLesson) { setLesId(null); setSesId(null); } }, [tree, lesId, selLesson]);
  useEffect(() => { if (selLesson && sesId && !selSession) setSesId(null); }, [selLesson, sesId, selSession]);

  const flatLessons = useMemo(() => {
    const out = [];
    (tree || []).forEach(t => t.lessons.forEach(l => out.push({ ...l, term: t.term })));
    return out;
  }, [tree]);
  const totals = useMemo(() => ({
    lessons: flatLessons.length,
    sessions: flatLessons.reduce((a, l) => a + (l.session_count || 0), 0),
    files: flatLessons.reduce((a, l) => a + (l.content_count || 0), 0),
  }), [flatLessons]);

  const intakeLabel = (code) => intakes.find(i => i.code === code)?.label || code;
  const lesMatch = (l) => !deferredQ || (l.name || '').includes(deferredQ) || (l.teacher || '').includes(deferredQ);
  const sesMatch = (s) => !deferredQ || (s.topic || '').includes(deferredQ) || (s.teacher || '').includes(deferredQ) || String(s.number) === deferredQ;

  const act = async (fn, okMsg = 'انجام شد') => {
    try { await fn(); toast(okMsg); load(); }
    catch (e) { toast(errText(e), 'err'); }
  };
  // 🌊 WA3 — reorder: پاسخ {ok:false} یعنی به مرز لیست رسیده‌ایم (خطا نیست)
  const reorder = async (fn, okMsg) => {
    try {
      const r = await fn();
      if (r && r.ok === false) return toast('به ابتدا/انتهای لیست رسیده‌اید', 'err');
      toast(okMsg); load();
    } catch (e) { toast(errText(e), 'err'); }
  };
  const bulk = async (body) => act(() => api.sessionsBulk(body).then(r => toast(`${fa(r.done)} مورد انجام شد`)));
  const toggleSel = (id) => setSel(x => x.includes(id) ? x.filter(i => i !== id) : [...x, id]);

  const delLesson = async (l) => {
    let impact = null; try { impact = await api.contentImpact('lesson', l.id); } catch {}
    setConfirm({ text: `حذف درس «${l.name}» با همه‌ی جلسات و فایل‌هایش؟${impact ? ` اثر بالقوه: ${fa(impact.affected_users)} کاربر، ${fa(impact.affected_sessions)} جلسه و ${fa(impact.affected_files)} فایل.` : ''}`,
      run: () => act(() => api.caDelLesson(l.id), 'درس حذف شد') });
  };
  const delSession = async (s) => {
    let impact = null; try { impact = await api.contentImpact('session', s.id); } catch {}
    setConfirm({ text: `حذف جلسه ${s.number} «${s.topic}» و فایل‌هایش؟${impact ? ` اثر بالقوه: ${fa(impact.affected_users)} کاربر و ${fa(impact.affected_files)} فایل.` : ''}`,
      run: async () => { await act(() => api.caDelSession(s.id), 'جلسه حذف شد'); setSesId(null); } });
  };

  if (permErr) return <NoPerm text="مدیریت محتوا فقط برای مدیران محتوا (سراسری/ورودی) است" />;
  if (err) return <ErrorState error={err} onRetry={load} />;

  const visSessions = selLesson ? selLesson.sessions.filter(sesMatch) : [];

  return (
    <>
      <ContentShell density={density}>
      <PageHeader title="مرکز فرماندهی محتوا" description="درس‌ها ← جلسات ← بازرس فایل · نمای مؤثر سراسری و Override ورودی"
        actions={<><ContentMetric icon="📘" value={fa(totals.lessons)} label="درس" /><ContentMetric icon="🗂" value={fa(totals.sessions)} label="جلسه" kind="acc" />
          <ContentMetric icon="📎" value={fa(totals.files)} label="فایل" kind="ok" /><button className="btn" onClick={() => setStudentPreview(true)}>👁 مشاهده به‌عنوان دانشجو</button><button className="btn primary" onClick={() => setQuick(true)}>⚡ آپلود سریع</button></>} />
      <ContentBreadcrumb items={[{ label: 'محتوا' }, { label: intake ? intakeLabel(intake) : 'سراسری' }, ...(selLesson ? [{ label: selLesson.name }] : []), ...(selSession ? [{ label: `جلسه ${fa(selSession.number)}` }] : [])]} />
      <SavedViews scope="content" filters={{ intake, q, lesson: lesId || '', session: sesId || '' }} density={density} onApply={f => {
        preserveSelection.current = (f.intake || '') !== intake; setIntake(f.intake || ''); setQ(f.q || ''); setLesId(f.lesson || null); setSesId(f.session || null);
      }} label="نماهای محتوایی" />
      <ContentToolbar>
        <select className="inp" value={intake} disabled={scopeKind === 'scoped'} onChange={e => setIntake(e.target.value)} aria-label="محدوده محتوای علوم پایه">
          {scopeKind === 'global' && <option value="">🌐 سراسری (پایه)</option>}
          {intakes.map(i => <option key={i.code} value={i.code}>🏷 {i.label || i.code}</option>)}
        </select>
        <input className="inp content-grow" placeholder="🔎 جست‌وجوی درس، استاد یا موضوع جلسه…" value={q} onChange={e => setQ(e.target.value)} aria-label="جست‌وجوی محتوای علوم پایه" />
        <ContentDensityToggle value={density} onChange={setDensity} />
      </ContentToolbar>

      {!tree ? <ContentSkeleton panes={3} /> : (
        <ContentWorkspace columns={3}>
          {/* ── ستون ۱: درخت درس‌ها ─────────────────────── */}
          <ContentPane icon="📚" title="درس‌ها" count={fa(totals.lessons)}>
            {tree.map(t => {
              const visLes = t.lessons.filter(lesMatch);
              if (deferredQ && visLes.length === 0) return null;
              return (
                <ContentSection key={t.term} icon={TERM_ICON} title={t.term} count={fa(t.lessons.length)}
                  open={openTerms[t.term] !== false}
                  onToggle={() => setOpenTerms(state => ({ ...state, [t.term]: !state[t.term] }))}
                  actions={<ContentIconButton icon="＋" label={`افزودن درس به ${t.term}`} kind="primary" onClick={() => setAddLes(t.term)} />}>
                  {visLes.length === 0 ? (
                    <ContentEmptyState icon="🌱" title="هنوز درسی برای این ترم ثبت نشده"
                      description={deferredQ ? 'نتیجه‌ای برای جست‌وجوی فعلی نیست.' : 'نخستین درس این ترم را ایجاد کنید.'}
                      action={!deferredQ ? <button className="btn sm primary" onClick={() => setAddLes(t.term)}>افزودن درس</button> : null} />
                  ) : visLes.map(l => {
                    const idx = t.lessons.findIndex(x => x.id === l.id);
                    return <ContentItem key={l.id} icon={lesId === l.id ? '📖' : '📘'} title={l.name}
                      meta={l.teacher || 'استاد ثبت نشده'} active={lesId === l.id} readonly={l.readonly}
                      scope={l.intake ? 'intake' : 'global'} scopeLabel={l.intake ? intakeLabel(l.intake) : 'سراسری'}
                      onClick={() => { setLesId(l.id); setSesId(null); setSel([]); }}
                      metrics={<><ContentMetric icon="🗂" value={fa(l.session_count)} label="جلسه" /><ContentMetric icon="📎" value={fa(l.content_count)} label="فایل" kind="acc" /></>}
                      actions={!l.readonly ? <>
                        <ContentReorderControls noun="درس" canUp={idx > 0} canDown={idx < t.lessons.length - 1}
                          onUp={() => reorder(() => api.waReorderLesson(l.id, 'up'), 'درس مرتب شد ↑')}
                          onDown={() => reorder(() => api.waReorderLesson(l.id, 'down'), 'درس مرتب شد ↓')} />
                        <ContentIconButton icon="✎" label="ویرایش نام و استاد" kind="primary" onClick={() => setEditLes(l)} />
                        <ContentMoreActions>
                          <ContentIconButton icon="＋" label="جلسه‌ی جدید" kind="primary" onClick={() => setAddSes(l)} />
                          <ContentIconButton icon="🗑" label="حذف درس" kind="danger" onClick={() => delLesson(l)} />
                        </ContentMoreActions>
                      </> : null} />;
                  })}
                </ContentSection>
              );
            })}
            {tree.length === 0 && <ContentEmptyState icon="🌱" title="هنوز ساختار محتوایی نیست"
              description="با افزودن نخستین درس به یکی از ترم‌ها شروع کنید." />}
          </ContentPane>

          {/* ── ستون ۲: جلسات درس منتخب ─────────────────── */}
          <ContentPane icon="🗂" title="جلسات" subtitle={selLesson?.name} count={selLesson ? fa(selLesson.sessions.length) : null}
            actions={selLesson && (!selLesson.readonly || selLesson.can_create_sessions) ? <button className="btn sm primary" onClick={() => setAddSes(selLesson)}>{selLesson.readonly ? '➕ جلسه (ورودی من)' : '➕ جلسه'}</button> : null}>
            <ContentBulkBar count={sel.length} onClear={() => setSel([])} actions={<>
              <button className="btn sm" onClick={() => bulk({ action: 'duplicate', ids: sel }).then(() => setSel([]))}>📄 کلون</button>
              <button className="btn sm" onClick={() => setMoveTo({ ids: sel })}>📦 انتقال</button>
              <button className="btn sm danger" onClick={() => setConfirm({
                text: `حذف ${fa(sel.length)} جلسه (به‌همراه فایل‌ها و نسخه‌های اختصاصی وابسته)؟`,
                run: () => bulk({ action: 'delete', ids: sel }).then(() => { setSel([]); setSesId(null); }),
              })}>🗑 حذف</button>
            </>} />
            {!selLesson ? (
              <ContentEmptyState icon="📚" title="هنوز درسی انتخاب نشده" description="برای مدیریت جلسه‌ها، یک درس را از ستون درخت انتخاب کنید." />
            ) : visSessions.length === 0 ? (
              <ContentEmptyState icon="📭" title={deferredQ ? 'جلسه‌ای با این جست‌وجو نیست' : 'این درس هنوز جلسه‌ای ندارد'}
                description={deferredQ ? 'عبارت جست‌وجو را تغییر دهید.' : 'برای شروع، نخستین جلسه را ایجاد کنید.'}
                action={!deferredQ && (!selLesson.readonly || selLesson.can_create_sessions) ? <button className="btn primary" onClick={() => setAddSes(selLesson)}>➕ نخستین جلسه</button> : null} />
            ) : visSessions.map(s => {
              const idx = selLesson.sessions.findIndex(x => x.id === s.id);
              return (
                <ContentItem key={s.id}
                  selection={!s.readonly ? <input type="checkbox" checked={sel.includes(s.id)}
                    onChange={() => toggleSel(s.id)} aria-label={`انتخاب جلسه ${fa(s.number)}`} /> : null}
                  icon={<span>{fa(s.number)}</span>}
                  title={s.topic || 'موضوع ثبت نشده'} meta={s.teacher || 'استاد ثبت نشده'}
                  active={sesId === s.id} selected={sel.includes(s.id)} readonly={s.readonly}
                  scope={s.kind === 'fork' ? 'override' : (s.kind === 'global' ? 'global' : 'intake')}
                  scopeLabel={s.kind === 'global' ? 'سراسری' : (s.intake_label || s.intake)}
                  onClick={() => setSesId(s.id)}
                  metrics={<span className="content-type-summary">{Object.entries(s.types || {}).map(([k, v]) => `${CTYPE[k] || '📎'} ${fa(v)}`).join(' · ') || 'بدون فایل'}</span>}
                  actions={<>
                    {s.kind === 'global' && intake && <ContentIconButton icon="🍴" label="ساخت نسخه اختصاصی برای این ورودی" kind="primary"
                      onClick={() => act(() => api.caForkSession(s.id, intake), 'نسخه‌ی اختصاصی ساخته شد ⭐')} />}
                    {!s.readonly && <>
                      <ContentReorderControls noun="جلسه" canUp={idx > 0} canDown={idx < selLesson.sessions.length - 1}
                        onUp={() => reorder(() => api.waReorderSession(s.id, 'up'), 'مرتب شد ↑')}
                        onDown={() => reorder(() => api.waReorderSession(s.id, 'down'), 'مرتب شد ↓')} />
                      <ContentIconButton icon="✎" label="ویرایش شماره/موضوع/استاد" kind="primary" onClick={() => setEditSes({ lesson_id: selLesson.id, s })} />
                      <ContentMoreActions>
                        {s.kind === 'fork' && <ContentIconButton icon="↩" label="حذف نسخه اختصاصی و بازگشت به سراسری" onClick={() => act(() => api.caUnforkSession(s.id), 'به نسخه‌ی سراسری برگشت ↩️')} />}
                        <ContentIconButton icon="⧉" label="کلون جلسه" onClick={() => act(() => api.dupSession(s.id), 'کلون ساخته شد 📄')} />
                        <ContentIconButton icon="🗑" label="حذف جلسه" kind="danger" onClick={() => delSession(s)} />
                      </ContentMoreActions>
                    </>}
                  </>} />
              );
            })}
          </ContentPane>

          {/* ── ستون ۳: بازرس ──────────────────────────── */}
          <ContentPane icon="🔎" title="بازرس" inspector
            actions={selSession ? <ScopeBadge scope={selSession.kind === 'fork' ? 'override' : (selSession.kind === 'global' ? 'global' : 'intake')} label={KIND[selSession.kind].label} /> : null}>
            {!selLesson ? (
              <ContentEmptyState icon="🧭" title="موردی برای بازبینی انتخاب نشده" description="نخست یک درس و سپس یک جلسه را انتخاب کنید." />
            ) : !selSession ? (
              <>
                <ContentKV label="درس" value={selLesson.name} strong />
                <ContentKV label="ترم" value={selLesson.term} />
                <ContentKV label="استاد" value={selLesson.teacher || '—'} />
                <ContentKV label="دامنه" value={<ScopeBadge scope={selLesson.intake ? 'intake' : 'global'} label={selLesson.intake ? intakeLabel(selLesson.intake) : 'سراسری'} />} />
                <ContentStats items={[
                  { value: fa(selLesson.session_count), label: 'جلسه' },
                  { value: fa(selLesson.content_count), label: 'فایل' },
                  { value: fa(selLesson.sessions.filter(s => s.kind !== 'global').length), label: 'نسخه‌ی خاص' },
                ]} />
                <ContentActionGroup>
                  {selLesson.readonly ? <>
                    <B>🔒 این درس سراسری برای scope شما فقط‌خواندنی است</B>
                    {selLesson.can_create_sessions && <button className="btn primary" onClick={() => setAddSes(selLesson)}>➕ جلسه برای ورودی من</button>}
                  </> : <>
                    <button className="btn primary" onClick={() => setAddSes(selLesson)}>➕ جلسه‌ی جدید</button>
                    <button className="btn" onClick={() => setEditLes(selLesson)}>✏️ ویرایش درس</button>
                    <ContentMoreActions>
                      {scopeKind === 'global' && <button className="btn" onClick={() => setRootMove({ kind: 'lesson', id: selLesson.id, label: selLesson.name, from: selLesson.intake || '' })}>📦 انتقال سطل ورودی</button>}
                      <button className="btn danger" onClick={() => delLesson(selLesson)}>🗑 حذف درس</button>
                    </ContentMoreActions>
                  </>}
                </ContentActionGroup>
                <ContentHistory targetType="lesson" targetId={selLesson.id} />
                <p className="muted content-help">💡 برای دیدن و مدیریت فایل‌ها، از ستون میانی یک جلسه را برگزینید.</p>
              </>
            ) : (
              <SessionInspector lesson={selLesson} session={selSession} intake={intake}
                onTreeChanged={load}
                onEdit={(s) => setEditSes({ lesson_id: selLesson.id, s })}
                onFork={(s) => act(() => api.caForkSession(s.id, intake), 'نسخه‌ی اختصاصی ساخته شد ⭐')}
                onUnfork={(s) => act(() => api.caUnforkSession(s.id), 'به نسخه‌ی سراسری برگشت ↩️')}
                onClone={(s) => act(() => api.dupSession(s.id), 'کلون ساخته شد 📄')}
                onMove={(s) => setMoveTo({ ids: [s.id] })}
                onDelete={delSession} />
            )}
          </ContentPane>
        </ContentWorkspace>
      )}

      {editLes && <EditLesson lesson={editLes} onClose={(ch) => { setEditLes(null); if (ch) load(); }} />}
      {editSes && <EditSession {...editSes} onClose={(ch) => { setEditSes(null); if (ch) load(); }} />}
      {quick && <QuickUpload intakes={intakes} intake={intake} onClose={(ch) => { setQuick(false); if (ch) load(); }} />}
      {addLes && <AddLesson term={addLes} intake={intake} onClose={(ch) => { setAddLes(null); if (ch) load(); }} />}
      {addSes && <AddSession lesson={addSes} onClose={(ch) => { setAddSes(null); if (ch) { load(); setLesId(addSes.id); } }} />}
      {moveTo && <MoveSessions lessons={flatLessons} sel={moveTo.ids}
                               onClose={(ch) => {
                                 setMoveTo(null);
                                 if (ch) {
                                   setSel([]);
                                   setSesId(prev => (moveTo.ids.includes(prev) ? null : prev));
                                   load();
                                 }
                               }} />}
      {confirm && <Confirm text={confirm.text} danger
                           onYes={async () => { await confirm.run(); setConfirm(null); }}
                           onNo={() => setConfirm(null)} />}
      {studentPreview && <StudentPreview onClose={() => setStudentPreview(false)} />}
      {rootMove && <RootMoveModal item={rootMove} intakes={intakes} onClose={(changed) => { setRootMove(null); if (changed) load(); }} />}
      </ContentShell>
    </>
  );
}

/* ── 🔎 بازرس جلسه: مشخصات + اکشن‌ها + مدیریت کامل فایل‌ها ── */
function SessionInspector({ lesson, session, intake, onTreeChanged, onEdit, onFork, onUnfork, onClone, onMove, onDelete }) {
  const scope = session.kind === 'fork' ? 'override' : (session.kind === 'global' ? 'global' : 'intake');
  return (
    <>
      <ContentKV label="جلسه" value={fa(session.number)} strong />
      <ContentKV label="موضوع" value={session.topic || '—'} />
      <ContentKV label="درس" value={<>{lesson.name} <span className="muted">· {lesson.term}</span></>} />
      <ContentKV label="استاد" value={session.teacher || lesson.teacher || '—'} />
      <ContentKV label="وضعیت" value={<ScopeBadge scope={scope} label={session.kind === 'global' ? 'سراسری' : (session.intake_label || session.intake)} />} />
      <ContentKV label="مالکیت و ویرایش" value={`${session.kind === 'global' ? 'مالک سراسری محتوا' : `ورودی ${session.intake_label || session.intake}`} · ${session.readonly ? 'فقط مشاهده' : 'قابل ویرایش در scope فعلی'}`} />
      <ContentActionGroup>
        {session.readonly && <B>🔒 فقط‌خواندنی</B>}
        {session.kind === 'global' && intake && <button className="btn sm primary" onClick={() => onFork(session)}>🍴 نسخه‌ی اختصاصی</button>}
        {!session.readonly && <>
          <button className="btn sm primary" onClick={() => onEdit(session)}>✏️ ویرایش</button>
          <ContentMoreActions>
            {session.kind === 'fork' && <button className="btn sm" onClick={() => onUnfork(session)}>↩️ بازگشت به سراسری</button>}
            <button className="btn sm" onClick={() => onClone(session)}>📄 کلون</button>
            <button className="btn sm" onClick={() => onMove(session)}>📦 انتقال</button>
            <button className="btn sm danger" onClick={() => onDelete(session)}>🗑 حذف</button>
          </ContentMoreActions>
        </>}
      </ContentActionGroup>
      <ImpactPanel targetType="session" targetId={session.id} />
      <ContentHistory targetType="session" targetId={session.id} />
      <SessionFiles session={session} onTreeChanged={onTreeChanged} />
    </>
  );
}

function ImpactPanel({ targetType, targetId }) {
  const [data, setData] = useState(null);
  const load = () => {
    let active = true;
    setData(null);
    api.contentImpact(targetType, targetId).then(r => active && setData(r)).catch(() => active && setData(false));
    return () => { active = false; };
  };
  useEffect(load, [targetType, targetId]);
  return <div className="content-inset">
    <div className="content-inset-title">🎯 تحلیل اثر واقعی</div>
    {data === false ? <ContentErrorState title="تحلیل اثر بارگذاری نشد" compact onRetry={load} />
      : !data ? <ContentSkeleton panes={1} rows={1} />
        : <><ContentStats items={[
          { value: fa(data.affected_users), label: 'کاربر بالقوه' },
          { value: fa(data.affected_sessions), label: 'جلسه' },
          { value: fa(data.affected_files), label: 'فایل' },
        ]} />
        <div className="content-inset-meta"><ScopeBadge scope={data.intake ? 'intake' : 'global'} label={data.intake || 'سراسری'} /> <span>{data.explanation}</span></div></>}
  </div>;
}

function StudentPreview({ onClose }) {
  const [q, setQ] = useState(''); const [hits, setHits] = useState(null); const [student, setStudent] = useState(null);
  const [root, setRoot] = useState(null); const [lessons, setLessons] = useState([]); const [sessions, setSessions] = useState([]); const [files, setFiles] = useState([]);
  const [term, setTerm] = useState(''); const [lesson, setLesson] = useState(''); const [session, setSession] = useState(''); const [busy, setBusy] = useState(false); const [err, setErr] = useState('');
  const search = async () => { if (q.trim().length < 2) return; setBusy(true); setErr(''); try { const r = await api.studentPreviewStudents(q.trim()); setHits(r.students || []); } catch (e) { setErr(errText(e)); } setBusy(false); };
  const choose = async user => { setBusy(true); setErr(''); try { const r = await api.studentPreview(user.id); setStudent(user); setRoot(r); setHits(null); } catch (e) { setErr(errText(e)); } setBusy(false); };
  const chooseTerm = async value => { setTerm(value); setLesson(''); setSession(''); setSessions([]); setFiles([]); setBusy(true); try { setLessons((await api.studentPreviewLessons(student.id, value)).lessons || []); } catch (e) { setErr(errText(e)); } setBusy(false); };
  const chooseLesson = async value => { setLesson(value); setSession(''); setFiles([]); setBusy(true); try { setSessions((await api.studentPreviewSessions(student.id, value)).sessions || []); } catch (e) { setErr(errText(e)); } setBusy(false); };
  const chooseSession = async value => { setSession(value); setBusy(true); try { setFiles((await api.studentPreviewFiles(student.id, value)).files || []); } catch (e) { setErr(errText(e)); } setBusy(false); };
  return <Modal wide title="👁 مشاهده محتوا به‌عنوان دانشجو" onClose={onClose}>
    <div className="panel panel-pad content-preview-note"><B kind="acc">Resolver مشترک Mini App</B><span className="muted content-inline-note">این نما مستقیماً همان توابع terms/lessons/sessions/files دانشجو را اجرا می‌کند.</span></div>
    {!student ? <><div className="row content-row-top-sm"><input className="inp content-grow" value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === 'Enter' && search()} placeholder="نام، شماره دانشجویی، یوزرنیم یا Telegram ID…" /><button className="btn" disabled={busy} onClick={search}>جست‌وجو</button></div>
      <div className="grid content-grid-tight">{(hits || []).map(user => <button key={user.id} className="pick" onClick={() => choose(user)}><b>{user.display_name || user.name}</b><span className="muted">{user.student_id || `#${user.id}`} · {user.intake || 'بدون ورودی'}</span></button>)}</div></> : <>
      <div className="row content-row-top-sm"><B kind="purple">{root?.student?.name}</B><B>{root?.student?.intake || 'بدون ورودی'}</B><B>گروه {root?.student?.group || '—'}</B><button className="btn sm" onClick={() => { setStudent(null); setRoot(null); }}>تغییر دانشجو</button></div>
      <div className="student-preview-grid">
        <div><b>ترم‌ها</b>{(root?.terms || []).map(item => <button key={item.name} className={`pick ${term === item.name ? 'on' : ''}`} onClick={() => chooseTerm(item.name)}>{item.name}<B>{fa(item.lesson_count)}</B></button>)}</div>
        <div><b>درس‌ها</b>{lessons.map(item => <button key={item._id} className={`pick ${lesson === item._id ? 'on' : ''}`} onClick={() => chooseLesson(item._id)}>{item.name}<span className="muted">{item.teacher}</span></button>)}</div>
        <div><b>جلسات</b>{sessions.map(item => <button key={item._id} className={`pick ${session === item._id ? 'on' : ''}`} onClick={() => chooseSession(item._id)}>جلسه {fa(item.number)} · {item.topic}<B>{fa(item.file_count)}</B></button>)}</div>
        <div><b>فایل‌های قابل مشاهده</b>{files.map(item => <div className="panel panel-pad" key={item.id}><b>{item.name}</b><div className="muted">{item.type} · {fa(item.downloads)} دریافت</div></div>)}</div>
      </div></>}
    {busy && <Loading rows={2} />}{err && <ErrorState error={err} onRetry={() => setErr('')} />}
  </Modal>;
}

function ContentHistory({ targetType, targetId }) {
  const [items, setItems] = useState(null);
  const [err, setErr] = useState('');
  const requestSeq = useRef(0);

  const load = async () => {
    const seq = ++requestSeq.current;
    setItems(null); setErr('');
    try {
      const r = await api.contentHistory(targetType, targetId);
      if (seq === requestSeq.current) setItems(r.items || []);
    } catch (e) {
      if (seq === requestSeq.current) setErr(errText(e));
    }
  };

  useEffect(() => {
    load();
    return () => { requestSeq.current += 1; };
  }, [targetType, targetId]);

  return <div className="content-inset">
    <div className="content-inset-title">🕓 تاریخچه تغییرات</div>
    {err ? <ContentErrorState title="تاریخچه بارگذاری نشد" error={err} compact onRetry={load} />
      : !items ? <ContentSkeleton panes={1} rows={2} />
        : <Timeline items={items.slice(0, 6)} empty="هنوز رویدادی برای این مورد ثبت نشده" />}
  </div>;
}

/* ── 📁 فایل‌های جلسه (داخل بازرس): لیست + آپلود + گروهی ── */
function SessionFiles({ session, onTreeChanged }) {
  const [items, setItems] = useState(null);
  const [readonly, setReadonly] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [showUp, setShowUp] = useState(false);
  const [form, setForm] = useState({ ctype: 'pdf', description: '', extra_info: '' });
  const [file, setFile] = useState(null);
  const [sel, setSel] = useState([]);
  // window.confirm پنجره‌ی بومیِ مرورگر است: از زبان/جهت و تم پنل پیروی
  // نمی‌کند، قابل استایل‌دهی نیست و رشته‌ی فارسی را در دیالوگ LTR نشان
  // می‌دهد. همان الگوی <Confirm> که بقیه‌ی صفحه استفاده می‌کند.
  const [confirm, setConfirm] = useState(null);
  const fileRef = useRef(null);

  const load = async () => {
    setErr('');
    try {
      const r = await api.caSessionContent(session.id);
      setItems(r.content || []); setReadonly(!!r.readonly);
    } catch (e) { setErr(errText(e)); }
  };
  useEffect(() => { setItems(null); setSel([]); setShowUp(false); load(); }, [session.id]);

  const changed = () => { load(); onTreeChanged(); };
  const upload = async () => {
    if (!file) return toast('ابتدا فایل را انتخاب کنید', 'err');
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append('ctype', form.ctype);
      fd.append('description', form.description || file.name);
      fd.append('extra_info', form.extra_info);
      fd.append('file', file);
      await api.caAddContent(session.id, fd);
      toast('آپلود شد ✅'); setFile(null); setForm({ ctype: 'pdf', description: '', extra_info: '' });
      if (fileRef.current) fileRef.current.value = '';
      setShowUp(false); changed();
    } catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  const del = (cid) => {
    const item = (items || []).find(entry => entry.id === cid);
    setConfirm({
      text: `فایل «${item?.description || cid}» حذف شود؟ این عملیات قابل بازگشت نیست.`,
      run: async () => {
        try { await api.caDelContent(cid); toast('حذف شد'); changed(); }
        catch (e) { toast(errText(e), 'err'); }
      },
    });
  };
  const reorderItem = async (cid, direction) => {
    try {
      const r = await api.waReorderItem(cid, direction);
      if (r && r.ok === false) return toast('به ابتدا/انتهای لیست رسیده‌اید', 'err');
      changed();
    } catch (e) { toast(errText(e), 'err'); }
  };
  const guess = (name) => EXT_MAP[(name.split('.').pop() || '').toLowerCase()] || 'pdf';
  const toggleSel = (id) => setSel(x => x.includes(id) ? x.filter(i => i !== id) : [...x, id]);

  return (
    <div className="content-files">
      <ContentSection icon="📁" title="فایل‌ها" count={items ? fa(items.length) : null} open
        actions={readonly ? <B>🔒 فقط‌خواندنی</B> : <button className="btn sm primary" onClick={() => setShowUp(x => !x)}>{showUp ? '✕ بستن' : '➕ افزودن فایل'}</button>}>
        {showUp && (
          <div className="content-upload">
            <label className="fld"><span>فایل</span><input ref={fileRef} type="file" className="inp"
              onChange={e => {
                const selectedFile = e.target.files[0] || null;
                setFile(selectedFile);
                if (selectedFile) setForm(x => ({ ...x, ctype: guess(selectedFile.name), description: x.description || selectedFile.name }));
              }} /></label>
            <div className="row content-form-row">
              <label className="fld"><span>نوع فایل</span><select className="inp" value={form.ctype} onChange={e => setForm({ ...form, ctype: e.target.value })}>
                {Object.entries(CTYPE).map(([k, v]) => <option key={k} value={k}>{v} {k}</option>)}
              </select></label>
              <label className="fld content-form-grow"><span>عنوان نمایشی</span><input className="inp" placeholder="توضیح…"
                value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} /></label>
            </div>
            <label className="fld"><span>اطلاعات تکمیلی</span><input className="inp" placeholder="اختیاری…"
              value={form.extra_info} onChange={e => setForm({ ...form, extra_info: e.target.value })} /></label>
            <button className="btn primary" disabled={busy || !file} onClick={upload}>
              {busy ? '⏳ در حال آپلود…' : '⬆️ آپلود (از مسیر تلگرام)'}</button>
          </div>
        )}
        {err ? <ContentErrorState title="فایل‌های جلسه بارگذاری نشد" error={err} compact onRetry={load} /> : !items ? <ContentSkeleton panes={1} rows={3} /> : (
          <>
            <ContentBulkBar count={sel.length} onClear={() => setSel([])} actions={<>
              <button className="btn sm danger" onClick={() => setConfirm({
                text: `حذف ${fa(sel.length)} فایل انتخاب‌شده؟ این عملیات قابل بازگشت نیست.`,
                run: async () => {
                  try {
                    const r = await api.itemsBulk({ action: 'delete', ids: sel });
                    toast(`${fa(r.done)} فایل حذف شد`); setSel([]); changed();
                  } catch (e) { toast(errText(e), 'err'); }
                },
              })}>🗑 حذف گروهی</button>
              <MoveItemsButton sel={sel} sessionId={session.id} onDone={() => { setSel([]); changed(); }} />
            </>} />
            {items.length === 0 && <ContentEmptyState icon="📭" title="فایلی برای این جلسه نیست"
              description={readonly ? 'در این دامنه فایلی ثبت نشده است.' : 'با افزودن نخستین فایل، محتوای جلسه را کامل کنید.'}
              action={!readonly ? <button className="btn sm primary" onClick={() => setShowUp(true)}>افزودن فایل</button> : null} />}
            {items.map((c, i) => (
              <ContentItem key={c.id}
                selection={!readonly ? <input type="checkbox" checked={sel.includes(c.id)} onChange={() => toggleSel(c.id)} aria-label={`انتخاب فایل ${c.description || c.id}`} /> : null}
                icon={<FileTypeBadge type={c.type} fileName={c.description} compact />}
                title={c.description || '(بدون توضیح)'} meta={c.extra_info || c.type} selected={sel.includes(c.id)}
                metrics={<ContentMetric icon="⬇" value={fa(c.downloads)} label="دریافت" />}
                actions={!readonly ? <>
                  <ContentReorderControls noun="فایل" canUp={i > 0} canDown={i < items.length - 1}
                    onUp={() => reorderItem(c.id, 'up')} onDown={() => reorderItem(c.id, 'down')} />
                  <ContentIconButton icon="🗑" label="حذف فایل" kind="danger" onClick={() => del(c.id)} />
                </> : null} />
            ))}
          </>
        )}
      </ContentSection>
      {confirm && <Confirm text={confirm.text} danger
        onYes={() => { const run = confirm.run; setConfirm(null); run(); }}
        onNo={() => setConfirm(null)} />}
    </div>
  );
}

function MoveItemsButton({ sel, sessionId, onDone }) {
  const [target, setTarget] = useState('');
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className="btn sm" onClick={() => setOpen(true)}>📦 انتقال به جلسه…</button>
      {open && (
        <Modal title="انتقال فایل‌ها به جلسه‌ی دیگر" onClose={() => setOpen(false)}>
          <p className="muted content-dialog-copy">شناسه‌ی جلسه‌ی مقصد را وارد کنید (از نشانی/کارت جلسه کپی کنید):</p>
          <input className="inp content-input-full content-ltr" placeholder="session id مقصد…"
                 value={target} onChange={e => setTarget(e.target.value)} />
          <div className="row content-row-top">
            <button className="btn primary" disabled={!target.trim()} onClick={async () => {
              try {
                const r = await api.itemsBulk({ action: 'move', ids: sel, target_session: target.trim() });
                toast(`${fa(r.done)} فایل منتقل شد`); setOpen(false); onDone();
              } catch (e) { toast(errText(e), 'err'); }
            }}>انتقال</button>
            <button className="btn" onClick={() => setOpen(false)}>انصراف</button>
          </div>
        </Modal>
      )}
    </>
  );
}

function RootMoveModal({ item, intakes, onClose }) {
  const [to, setTo] = useState(item.from || ''); const [busy, setBusy] = useState(false);
  const run = async () => { setBusy(true); try {
    if (item.kind === 'lesson') await api.caMoveLessonRoot(item.id, to);
    else if (item.kind === 'subject') await api.refSubjectMoveRoot(item.id, to);
    // 🛡 شاخه‌ی سوم قبلاً api.caMoveQbankRoot را صدا می‌زد که نه در
    // api.js تعریف شده و نه endpointی در بک‌اند دارد ⇒ TypeError خام.
    // امروز غیرقابل‌دسترس است (فقط kind های lesson/subject ساخته
    // می‌شوند) اما هر kind جدیدی مستقیم اینجا می‌افتاد. خطای صریح
    // به‌جای کرش مبهم:
    else throw new Error(`انتقال root برای نوع «${item.kind}» هنوز پشتیبانی نمی‌شود`);
    toast('انتقال root با موفقیت انجام شد ✅'); onClose(true);
  } catch (e) { let conflict = ''; if (e.status === 409) { try { const d = JSON.parse(e.technical || '{}'); conflict = `${d.reason || 'تعارض مقصد'}${d.existing_id ? ` · Existing: ${d.existing_id}` : ''}`; } catch {} } toast(conflict || errText(e), 'err'); setBusy(false); } };
  const fromLabel = item.from ? (intakes.find(x => (x.code || x) === item.from)?.label || item.from) : 'سراسری';
  const toLabel = to ? (intakes.find(x => (x.code || x) === to)?.label || to) : 'سراسری';
  return <Modal title={`📦 انتقال «${item.label}»`} onClose={() => onClose(false)}>
    <div className="panel panel-pad"><div className="row"><B>مبدأ: {fromLabel}</B><span>←</span><B kind="warn">مقصد: {toLabel}</B></div><div className="muted">این عملیات مالکیت root object را تغییر می‌دهد؛ overwrite ضمنی انجام نمی‌شود و تعارض همنام با 409 متوقف خواهد شد.</div></div>
    <select className="inp content-input-full content-row-top-sm" value={to} onChange={e => setTo(e.target.value)}><option value="">🌐 سراسری</option>{intakes.map(x => <option key={x.code || x} value={x.code || x}>{x.label || x.code || x}</option>)}</select>
    <div className="row content-row-top"><button className="btn danger" disabled={busy || to === item.from} onClick={run}>{busy ? '⏳' : 'تأیید انتقال'}</button><button className="btn" onClick={() => onClose(false)}>انصراف</button></div>
  </Modal>;
}

/* ── ✏️ ویرایش درس/جلسه ───────────────────────────────── */
function EditLesson({ lesson, onClose }) {
  const [name, setName] = useState(lesson.name || '');
  const [teacher, setTeacher] = useState(lesson.teacher || '');
  const [busy, setBusy] = useState(false);
  return <Modal title={`✏️ ویرایش درس — ${lesson.name}`} onClose={() => onClose(false)}>
    <div className="grid content-modal-grid">
      <label className="fld"><span>نام درس</span><input className="inp" value={name} onChange={e => setName(e.target.value)} /></label>
      <label className="fld"><span>استاد</span><input className="inp" value={teacher} onChange={e => setTeacher(e.target.value)} /></label>
      <div className="row"><button className="btn primary" disabled={busy || !name.trim()} onClick={async () => {
        setBusy(true);
        try { await api.caEditLesson(lesson.id, { name: name.trim(), teacher: teacher.trim() }); toast('درس ویرایش شد ✅'); onClose(true); }
        catch (e) { toast(errText(e), 'err'); setBusy(false); }
      }}>ذخیره</button><button className="btn" onClick={() => onClose(false)}>انصراف</button></div>
    </div>
  </Modal>;
}


function EditSession({ s, onClose }) {
  const [number, setNumber] = useState(s.number || 1);
  const [topic, setTopic] = useState(s.topic || '');
  const [teacher, setTeacher] = useState(s.teacher || '');
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={`✏️ ویرایش جلسه ${fa(s.number)}`} onClose={() => onClose(false)}>
      <div className="grid content-modal-grid">
        <label className="fld"><span>شماره جلسه</span><input className="inp" type="number" min="1" value={number} onChange={e => setNumber(e.target.value)} /></label>
        <input className="inp" placeholder="موضوع جلسه…" value={topic} onChange={e => setTopic(e.target.value)} />
        <input className="inp" placeholder="استاد…" value={teacher} onChange={e => setTeacher(e.target.value)} />
        <div className="row">
          <button className="btn primary" disabled={busy || Number(number) < 1 || !topic.trim()} onClick={async () => {
            setBusy(true);
            try {
              await api.caEditSession(s.id, { number: Number(number), topic: topic.trim(), teacher: teacher.trim() });
              toast('شماره و اطلاعات جلسه ذخیره شد ✅'); onClose(true);
            } catch (e) { toast(errText(e), 'err'); setBusy(false); }
          }}>ذخیره</button>
          <button className="btn" onClick={() => onClose(false)}>انصراف</button>
        </div>
      </div>
    </Modal>
  );
}

function AddSession({ lesson, onClose }) {
  // 🌊 C3 — روی درس فقط‌خواندنی، سرور جلسه را در سطل scope کاربر می‌نویسد
  const ownOnly = Boolean(lesson.readonly && lesson.can_create_sessions);
  const [number, setNumber] = useState((lesson.sessions?.length ? Math.max(...lesson.sessions.map(x => x.number || 0)) : 0) + 1);
  const [topic, setTopic] = useState('');
  const [teacher, setTeacher] = useState('');
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={`➕ جلسه‌ی جدید — ${lesson.name}`} onClose={() => onClose(false)}>
      <div className="grid content-modal-grid">
        {ownOnly && <p className="muted">📅 این جلسه فقط برای ورودی شما ساخته می‌شود؛ نسخه‌ی سراسریِ درس تغییر نمی‌کند.</p>}
        <input className="inp" type="number" min="1" value={number} onChange={e => setNumber(+e.target.value)} />
        <input className="inp" placeholder="موضوع جلسه…" value={topic} onChange={e => setTopic(e.target.value)} />
        <input className="inp" placeholder="استاد…" value={teacher} onChange={e => setTeacher(e.target.value)} />
        <div className="row">
          <button className="btn primary" disabled={busy || !topic.trim()} onClick={async () => {
            setBusy(true);
            try {
              await api.caAddSession(lesson.id, { number, topic: topic.trim(), teacher: teacher.trim() });
              toast('جلسه ساخته شد'); onClose(true);
            } catch (e) { toast(errText(e), 'err'); }
            setBusy(false);
          }}>ایجاد</button>
          <button className="btn" onClick={() => onClose(false)}>انصراف</button>
        </div>
      </div>
    </Modal>
  );
}

/* ── ➕ درس ─────────────────────────────────────────── */
function AddLesson({ term, intake, onClose }) {
  const [name, setName] = useState('');
  const [teacher, setTeacher] = useState('');
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={`➕ درس جدید — ${term}${intake ? ' · مختص ورودی' : ' · سراسری'}`} onClose={() => onClose(false)}>
      <div className="grid content-modal-grid">
        <input className="inp" placeholder="نام درس…" value={name} onChange={e => setName(e.target.value)} />
        <input className="inp" placeholder="استاد…" value={teacher} onChange={e => setTeacher(e.target.value)} />
        <div className="row">
          <button className="btn primary" disabled={busy || !name.trim()} onClick={async () => {
            setBusy(true);
            try {
              await api.caAddLesson({ term, name: name.trim(), teacher: teacher.trim(), intake: intake || '' });
              toast('درس ساخته شد'); onClose(true);
            } catch (e) { toast(errText(e), 'err'); }
            setBusy(false);
          }}>ایجاد</button>
          <button className="btn" onClick={() => onClose(false)}>انصراف</button>
        </div>
      </div>
    </Modal>
  );
}

/* ── 📦 انتقال گروهی/تکی جلسات ─────────────────────── */
function MoveSessions({ lessons, sel, onClose }) {
  const [target, setTarget] = useState('');
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={`📦 انتقال ${fa(sel.length)} جلسه به درس دیگر`} onClose={() => onClose(false)}>
      <select className="inp content-input-full" value={target} onChange={e => setTarget(e.target.value)}>
        <option value="">انتخاب درس مقصد…</option>
        {lessons.map(l => <option key={l.id} value={l.id}>{l.term} — {l.name}</option>)}
      </select>
      <div className="row content-row-top">
        <button className="btn primary" disabled={busy || !target} onClick={async () => {
          setBusy(true);
          try {
            const r = await api.sessionsBulk({ action: 'move', ids: sel, target_lesson: target });
            toast(`${fa(r.done)} جلسه منتقل شد`); onClose(true);
          } catch (e) { toast(errText(e), 'err'); }
          setBusy(false);
        }}>انتقال</button>
        <button className="btn" onClick={() => onClose(false)}>انصراف</button>
      </div>
    </Modal>
  );
}

/* ── ⚡ آپلود سریع چندفایلی — پیشنهاد خودکار نوع از پسوند ─ */
function QuickUpload({ intakes, intake, onClose }) {
  const [scIntake, setScIntake] = useState(intake || '');
  const [tree, setTree] = useState(null);
  const [lessonId, setLessonId] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [files, setFiles] = useState([]);       // {file, ctype, description, status, error}
  const [prog, setProg] = useState(null);       // {done,total,ok,failed}
  const [dragging, setDragging] = useState(false);
  const pickerRef = useRef(null);

  useEffect(() => {
    setTree(null);
    api.contentTree(scIntake || undefined).then(r => setTree(r.tree || [])).catch(e => toast(errText(e), 'err'));
  }, [scIntake]);

  const lessons = useMemo(() => {
    const out = [];
    (tree || []).forEach(t => t.lessons.forEach(l => out.push({ ...l, term: t.term })));
    return out;
  }, [tree]);
  const lesson = lessons.find(l => l.id === lessonId);
  const sessions = lesson ? lesson.sessions : [];

  const addFiles = (fl) => {
    const next = [...files];
    const seen = new Set(next.map(x => `${x.file.name}:${x.file.size}`));
    for (const f of Array.from(fl || [])) {
      const signature = `${f.name}:${f.size}`;
      if (seen.has(signature)) continue;
      seen.add(signature);
      const ext = (f.name.split('.').pop() || '').toLowerCase();
      const ctype = EXT_MAP[ext];
      let error = '';
      if (!ctype) error = 'پسوند این فایل در Content Typeهای فعلی پشتیبانی نمی‌شود';
      else if (f.size > 45 * 1024 * 1024) error = 'حجم بیشتر از سقف ۴۵MB است';
      next.push({
        file: f, ctype: ctype || 'pdf', description: f.name.replace(/\.[^.]+$/, ''),
        status: error ? 'invalid' : 'pending', error,
      });
    }
    setFiles(next.slice(0, 30));
  };
  const ready = files.filter(x => ['pending', 'error'].includes(x.status) && !x.error.includes('پشتیبانی') && !x.error.includes('۴۵MB'));
  const guess_ok = ready.length > 0 && lessonId && sessionId;

  const run = async (retryOnly = false) => {
    const indexes = files.map((it, i) => ({ it, i })).filter(({ it }) =>
      retryOnly ? it.status === 'error' : ['pending', 'error'].includes(it.status) && !it.error.includes('پشتیبانی') && !it.error.includes('۴۵MB'));
    if (!indexes.length) return;
    setProg({ done: 0, total: indexes.length, ok: 0, failed: 0 });
    for (const { it, i } of indexes) {
      setFiles(xs => xs.map((x, j) => j === i ? { ...x, status: 'uploading', error: '' } : x));
      try {
        const fd = new FormData();
        fd.append('ctype', it.ctype);
        fd.append('description', it.description || it.file.name);
        fd.append('extra_info', '');
        fd.append('file', it.file);
        await api.caAddContent(sessionId, fd);
        setFiles(xs => xs.map((x, j) => j === i ? { ...x, status: 'success', error: '' } : x));
        setProg(p => ({ ...p, done: p.done + 1, ok: p.ok + 1 }));
      } catch (e) {
        const error = errText(e);
        setFiles(xs => xs.map((x, j) => j === i ? { ...x, status: 'error', error } : x));
        setProg(p => ({ ...p, done: p.done + 1, failed: p.failed + 1 }));
      }
    }
  };

  return (
    <Modal title="⚡ آپلود سریع به جلسه (چندفایلی)" onClose={() => onClose(false)}>
      <div className="grid content-modal-grid">
        <div className="row">
          <select className="inp" value={scIntake} onChange={e => { setScIntake(e.target.value); setLessonId(''); setSessionId(''); }}>
            <option value="">🌐 سراسری</option>
            {intakes.map(i => <option key={i.code} value={i.code}>🏷 {i.label || i.code}</option>)}
          </select>
          <select className="inp content-grow" value={lessonId} onChange={e => { setLessonId(e.target.value); setSessionId(''); }}>
            <option value="">{tree ? 'درس…' : '…'}</option>
            {lessons.map(l => <option key={l.id} value={l.id}>{l.term} — {l.name}</option>)}
          </select>
        </div>
        <select className="inp" value={sessionId} onChange={e => setSessionId(e.target.value)} disabled={!lessonId}>
          <option value="">جلسه…</option>
          {sessions.map(s => (
            <option key={s.id} value={s.id}>
              جلسه {s.number} — {s.topic || '—'} {s.kind === 'fork' ? '⭐' : ''}
            </option>
          ))}
        </select>
        <input ref={pickerRef} type="file" multiple hidden accept=".pdf,.ppt,.pptx,.mp4,.mov,.mkv,.webm,.mp3,.ogg,.wav,.m4a"
          onChange={e => { addFiles(e.target.files); e.target.value = ''; }} />
        <div className={`upload-dropzone ${dragging ? 'on' : ''}`} role="button" tabIndex={0}
          onClick={() => pickerRef.current?.click()}
          onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pickerRef.current?.click(); } }}
          onDragEnter={e => { e.preventDefault(); setDragging(true); }} onDragOver={e => e.preventDefault()}
          onDragLeave={e => { e.preventDefault(); setDragging(false); }}
          onDrop={e => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files); }}>
          <b>فایل‌ها را اینجا رها کنید یا برای انتخاب کلیک کنید</b>
          <div className="muted">PDF، PowerPoint، Video و Voice · حداکثر ۳۰ فایل · سقف هر فایل ۴۵MB</div>
        </div>
        {files.map((f, i) => (
          <div key={`${f.file.name}-${f.file.size}`} className={`row file-row upload-${f.status}`}>
            <span>{f.status === 'success' ? '✅' : f.status === 'error' || f.status === 'invalid' ? '⚠️' : f.status === 'uploading' ? '⏳' : CTYPE[f.ctype] || '📎'}</span>
            <div className="content-upload-file-name"><b className="text-truncate">{f.file.name}</b><div className="muted">{(f.file.size / 1024 / 1024).toFixed(2)} MB</div></div>
            <input className="inp content-grow" value={f.description} disabled={f.status === 'uploading' || f.status === 'success'}
                   onChange={e => setFiles(x => x.map((y, j) => j === i ? { ...y, description: e.target.value } : y))} />
            <select className="inp" value={f.ctype} disabled={f.status === 'uploading' || f.status === 'success' || f.status === 'invalid'}
                    onChange={e => setFiles(x => x.map((y, j) => j === i ? { ...y, ctype: e.target.value } : y))}>
              {Object.entries(CTYPE).map(([k]) => <option key={k} value={k}>{k}</option>)}
            </select>
            {f.error && <span className="field-error" title={f.error}>{f.error}</span>}
            <button className="btn sm danger" disabled={f.status === 'uploading'} onClick={() => setFiles(x => x.filter((_, j) => j !== i))} aria-label={`حذف فایل ${i + 1} از صف`}>✕</button>
          </div>
        ))}
        {prog && <div className="panel panel-pad">
          <div className="row"><span>پیشرفت {fa(prog.done)} از {fa(prog.total)}</span><span className="spacer" />
            <B kind="ok">موفق {fa(prog.ok)}</B><B kind={prog.failed ? 'bad' : ''}>ناموفق {fa(prog.failed)}</B></div>
          <div className="minibar-track content-progress"><div className="minibar-fill" style={{ width: `${prog.total ? Math.round(prog.done * 100 / prog.total) : 0}%` }} /></div>
        </div>}
        <div className="row">
          <button className="btn primary" disabled={!guess_ok || (prog && prog.done < prog.total)} onClick={() => run(false)}>
            ⬆️ آپلود {ready.length ? `(${fa(ready.length)} فایل آماده)` : ''}
          </button>
          {files.some(x => x.status === 'error') && <button className="btn" disabled={prog && prog.done < prog.total} onClick={() => run(true)}>↻ تلاش مجدد ناموفق‌ها</button>}
          {files.some(x => x.status === 'success') && <button className="btn ok" onClick={() => onClose(true)}>پایان و تازه‌سازی</button>}
          <button className="btn" onClick={() => onClose(false)}>بستن</button>
        </div>
      </div>
    </Modal>
  );
}
