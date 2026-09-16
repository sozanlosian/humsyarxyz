import React, { useEffect, useState } from 'react';
import { api, errText } from '../api.js';
import { DataTable, Loading, ErrorState, B, FaDate, PageHeader, Tabs, DiffViewer, toast, Confirm, Modal, Stat, NoPerm } from '../ui.jsx';
import { PersianDatePicker } from '../PersianDatePicker.jsx';
import { fileDateStamp, formatFaDate, formatFaTime } from '../time.js';
import SavedViews from '../SavedViews.jsx';
import { writeHashQuery } from '../urlState.js';

const fa = n => Number(n ?? 0).toLocaleString('fa-IR');
const ST = [
  ['', 'همه'],
  ['scheduled', 'زمان‌بندی‌شده'],
  ['active', 'در حال برگزاری'],
  ['finished', 'برگزارشده'],
];

// 📝🌊 WA2.2 — مدیریت آزمون‌ها: CRUD روی schedules type=exam + آمار آزمون‌های تمرینی
// 🌊 WA3 — تب دوم «نمرات»: recent + جستجوی دانشجو + ثبت گروهی (معادل ربات)
export default function Exams({ route = '' }) {
  const params = new URLSearchParams(route.split('?')[1] || '');
  const requested = params.get('tab');
  const [tab, setTab] = useState(requested === 'grades' ? 'grades' : 'exams');
  useEffect(() => { setTab(requested === 'grades' ? 'grades' : 'exams'); }, [requested]);
  const changeTab = value => { setTab(value); writeHashQuery('/exams', { tab: value === 'grades' ? 'grades' : '' }); };
  return (
    <>
      <Tabs items={[['exams', '📝 آزمون‌ها'], ['grades', '📊 نمرات']]} value={tab} onChange={changeTab} label="آزمون و نمرات" />
      {tab === 'exams' ? <ExamsTab autoCreate={params.get('new') === 'exam'} initialStatus={params.get('status') || ''} /> : <GradesTab autoCreate={params.get('new') === 'grade'} initial={{ q: params.get('q') || '', lesson: params.get('lesson') || '', group: params.get('group') || '', intake: params.get('intake') || '', dateFrom: params.get('date_from') || '', dateTo: params.get('date_to') || '', page: Number(params.get('page')) || 1 }} />}
    </>
  );
}

function ExamsTab({ autoCreate = false, initialStatus = '' }) {
  const [status, setStatus] = useState(initialStatus);
  const [visibleColumns, setVisibleColumns] = useState([]);
  const [data, setData] = useState(null);
  const [stats, setStats] = useState(null);
  const [err, setErr] = useState('');
  const [permErr, setPermErr] = useState(false);
  const [edit, setEdit] = useState(autoCreate ? {} : null);       // null | {} new | {row}
  const [confirm, setConfirm] = useState(null);
  useEffect(() => { if (autoCreate) setEdit({}); }, [autoCreate]);

  const load = async () => {
    setErr('');
    try {
      const r = await api.exams(status || undefined);
      setData(r);
    } catch (e) {
      if (e.status === 403) setPermErr(true); else setErr(errText(e));
    }
  };
  useEffect(() => { setData(null); load(); }, [status]);
  useEffect(() => { writeHashQuery('/exams', { status }); }, [status]);
  useEffect(() => { api.examStats().then(setStats).catch(() => {}); }, []);

  if (permErr) return <NoPerm text="مدیریت آزمون‌ها نیازمند مجوز «مدیریت برنامه و امتحان» (schedules.manage) است" />;
  if (err) return <ErrorState error={err} onRetry={load} />;

  const counts = (data && data.counts) || {};
  const cols = [
    { k: 'lesson', label: 'درس / عنوان', render: r => (
      <div><b style={{ color: 'var(--txt)' }}>{r.lesson}</b>
        <div className="muted">{r.teacher || ''}</div></div>) },
    { k: 'date', label: 'تاریخ', render: r => <FaDate value={r.date} /> },
    { k: 'time', label: 'ساعت', render: r => r.time || '—' },
    { k: 'group', label: 'گروه' },
    { k: 'location', label: 'مکان', render: r => r.location || '—' },
    { k: 'status', label: 'وضعیت', render: r => (
      <B kind={r.status === 'active' ? 'bad' : r.status === 'scheduled' ? 'acc' : 'ok'}>{r.status_fa}</B>) },
    { k: 'reminded', label: 'یادآوری', render: r => (r.reminded || []).length
      ? <B kind="purple">{(r.reminded || []).join(' ')}</B> : <span className="muted">—</span> },
    { k: 'ops', label: '', stop: true, render: r => (
      <div className="row" style={{ gap: 4 }}>
        <button className="btn sm" onClick={() => setEdit(r)} aria-label={`ویرایش آزمون ${r.lesson}`}>✏️</button>
        <button className="btn sm" onClick={() => setEdit({ clone: r })} aria-label={`کپی آزمون ${r.lesson}`}>📄</button>
        <button className="btn sm danger" onClick={() => setConfirm(r)} aria-label={`حذف آزمون ${r.lesson}`}>🗑</button>
      </div>) },
  ];

  return (
    <>
      <PageHeader title="مدیریت آزمون‌ها" description="آزمون‌های رسمی با اطلاع‌رسانی خودکار ۷، ۳ و ۱ روز قبل"
        actions={<button className="btn primary" onClick={() => setEdit({})}>➕ آزمون جدید</button>} />

      {stats && (
        <div className="grid g4" style={{ marginBottom: 14 }}>
          <Stat icon="🧪" label="کل آزمون‌های تمرینی اجراشده" value={Number(stats.total_runs || 0).toLocaleString('fa')} tint="var(--acc)" />
          <Stat icon="🏁" label="تکمیل‌شده" value={Number(stats.finished || 0).toLocaleString('fa')} tint="var(--ok)" />
          <Stat icon="🎯" label="میانگین درصد (آزمون تمرینی)" value={stats.avg_pct != null ? `${Number(stats.avg_pct).toLocaleString('fa')}٪` : '—'} tint="var(--purple)" />
          <Stat icon="🗓" label="اجرا در ۷ روز اخیر" value={Number(stats.runs_7d || 0).toLocaleString('fa')} tint="var(--warn)" />
        </div>
      )}

      <div className="tabs" role="tablist" aria-label="وضعیت آزمون‌ها">
        {ST.map(([k, v]) => (
          <button key={k} type="button" role="tab" aria-selected={status === k} className={`tab ${status === k ? 'on' : ''}`} onClick={() => setStatus(k)}>
            {v}{k && counts[k] != null ? ` (${Number(counts[k]).toLocaleString('fa')})` : ''}
          </button>
        ))}
      </div>

      <SavedViews scope="exams" filters={{ status }} columns={visibleColumns} onApply={(f, item) => { setStatus(f.status || ''); setVisibleColumns(item.columns || []); }} label="نماهای آزمون" />
      {!data ? <Loading /> : (
        <DataTable columns={cols} rows={data.exams} colToggle visibleColumns={visibleColumns} onColumnsChange={setVisibleColumns} empty={
          <div className="center-state">آزمونی در این وضعیت نیست</div>} />
      )}

      {edit && <ExamModal row={edit.id ? edit : null} seed={edit.clone || null} onClose={(ch) => { setEdit(null); if (ch) load(); }} />}
      {confirm && (
        <Confirm text={`حذف آزمون «${confirm.lesson}» (${formatFaDate(confirm.date)})؟`} danger
                 onYes={async () => {
                   try { const r = await api.examDelete(confirm.id); toast(`آزمون لغو و به ${Number(r.notified || 0).toLocaleString('fa')} نفر اطلاع داده شد`); setConfirm(null); load(); }
                   catch (e) { toast(errText(e), 'err'); setConfirm(null); }
                 }}
                 onNo={() => setConfirm(null)} />
      )}
    </>
  );
}

// 🌊 موج Exams-Builder — سازنده‌ی مرحله‌ای: مشخصات ← زمان/مکان ← بازبینی و ثبت
// (همان payload قبلی؛ فقط UX گام‌به‌گام با اعتبارسنجی هر گام)
const EX_STEPS = [['مشخصات', '📚'], ['زمان و مکان', '🗓'], ['بازبینی و ثبت', '✅']];

function ExamModal({ row, seed, onClose }) {
  const base = row || seed || {};
  const [f, setF] = useState({
    lesson: seed ? `${base.lesson || ''} — کپی` : base.lesson || '', date: base.date || '', time: base.time || '',
    teacher: base.teacher || '', location: base.location || '',
    notes: base.notes || '', group: base.group || 'هر دو',
  });
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setF(x => ({ ...x, [k]: v }));

  const faDate = f.date ? formatFaDate(f.date, { long: true }) : '—';
  const okStep1 = !!f.lesson.trim();
  const okStep2 = !!f.date;
  const todayIso = fileDateStamp();

  const submit = async () => {
    setBusy(true);
    try {
      const r = row ? await api.examUpdate(row.id, f) : await api.examCreate(f);
      toast(`${row ? 'ویرایش آزمون' : 'آزمون جدید'} ثبت و به ${Number(r.notified || 0).toLocaleString('fa')} نفر اطلاع داده شد ✅`);
      // 🌊 W8/UX-05 — هشدار تداخل زمانی (غیرمسدودکننده)
      if (!row && r.warnings?.schedule_conflicts?.length)
        toast(`⚠️ تداخل با ${r.warnings.schedule_conflicts.length} برنامه: ${r.warnings.schedule_conflicts.map(c => c.lesson).join('، ')}`, 'warn');
      onClose(true);
    } catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };

  return (
    <Modal title={row ? `✏️ ویرایش آزمون — ${row.lesson}` : seed ? `📄 کپی آزمون — ${seed.lesson}` : '📝 سازنده‌ی آزمون جدید'} onClose={() => onClose(false)}>
      <div className="wiz-steps" style={{ marginBottom: 14 }}>
        {EX_STEPS.map(([label, icon], i) => (
          <div key={label} className={`wiz-step ${step === i + 1 ? 'on' : ''} ${step > i + 1 ? 'done' : ''}`}
               onClick={() => { if (step > i + 1) setStep(i + 1); }}>
            <span className="wiz-n">{step > i + 1 ? '✓' : Number(i + 1).toLocaleString('fa')}</span>
            <span className="wiz-l">{icon} {label}</span>
          </div>
        ))}
      </div>

      {step === 1 && (
        <div className="grid" style={{ gap: 10 }}>
          <label className="muted" style={{ fontSize: 'var(--fs-label)' }}>درس / عنوان آزمون *
            <input className="inp" placeholder="مثلاً فیزیولوژی — آزمون میانترم قلب" value={f.lesson}
                   onChange={e => set('lesson', e.target.value)} autoFocus /></label>
          <label className="muted" style={{ fontSize: 'var(--fs-label)' }}>استاد
            <input className="inp" placeholder="نام استاد…" value={f.teacher} onChange={e => set('teacher', e.target.value)} /></label>
          <label className="muted" style={{ fontSize: 'var(--fs-label)' }}>گروه هدف
            <div className="row">
              {[
                ['هر دو', '👥 هر دو گروه'],
                ['1', '1️⃣ گروه ۱'],
                ['2', '2️⃣ گروه ۲'],
              ].map(([g, label]) => (
                <label key={g} className={`pick ${f.group === g ? 'on' : ''}`} style={{ flex: 1 }}>
                  <input type="radio" checked={f.group === g} onChange={() => set('group', g)} />
                  <b>{label}</b>
                </label>
              ))}
            </div>
          </label>
          <button className="btn primary" disabled={!okStep1} onClick={() => setStep(2)}>ادامه ←</button>
        </div>
      )}

      {step === 2 && (
        <div className="grid" style={{ gap: 10 }}>
          <div className="row">
            <label className="muted" style={{ fontSize: 'var(--fs-label)', flex: 1 }}>تاریخ شمسی *
              <PersianDatePicker value={f.date} onChange={value => set('date', value)} ariaLabel="تاریخ شمسی آزمون" /></label>
            <label className="muted" style={{ fontSize: 'var(--fs-label)', width: 130 }}>ساعت
              <input className="inp" type="time" style={{ direction: 'ltr' }} value={f.time}
                     onChange={e => set('time', e.target.value)} /></label>
          </div>
          {f.date && (
            <div className="ct3-kv"><span className="muted">نمایش به دانشجو</span>
              <B kind={f.date < todayIso ? 'warn' : 'acc'}>{faDate}{f.time ? ` · ساعت ${formatFaTime(f.time)}` : ''}</B>
            </div>
          )}
          {f.date && f.date < todayIso && !row && (
            <span className="muted" style={{ color: 'var(--c-warn)', fontSize: 'var(--fs-label)' }}>
              ⚠️ تاریخ در گذشته است — آزمون «برگزارشده» ثبت می‌شود و اطلاع‌رسانی نخواهد داشت.</span>
          )}
          <label className="muted" style={{ fontSize: 'var(--fs-label)' }}>مکان
            <input className="inp" placeholder="سایت امتحانات / سالن…" value={f.location} onChange={e => set('location', e.target.value)} /></label>
          <label className="muted" style={{ fontSize: 'var(--fs-label)' }}>یادداشت (اختیاری)
            <textarea className="inp" rows={2} placeholder="نکته‌ی تکمیلی برای دانشجویان…" value={f.notes}
                      onChange={e => set('notes', e.target.value)} /></label>
          <div className="row">
            <button className="btn" onClick={() => setStep(1)}>→ بازگشت</button>
            <button className="btn primary" disabled={!okStep2} onClick={() => setStep(3)}>ادامه ←</button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="grid" style={{ gap: 8 }}>
          <div className="ct3-kv"><span className="muted">عنوان</span><b>{f.lesson}</b></div>
          <div className="ct3-kv"><span className="muted">استاد</span><span>{f.teacher || '—'}</span></div>
          <div className="ct3-kv"><span className="muted">گروه</span><B>{f.group}</B></div>
          <div className="ct3-kv"><span className="muted">زمان</span><span>{faDate}{f.time ? ` · ${formatFaTime(f.time)}` : ''}</span></div>
          <div className="ct3-kv"><span className="muted">مکان</span><span>{f.location || '—'}</span></div>
          {f.notes && <div className="ct3-kv"><span className="muted">یادداشت</span><span>{f.notes}</span></div>}
          <div className="panel panel-pad" style={{ background: 'var(--bg)', fontSize: 'var(--fs-body)' }}>
            🤖 پس از ثبت، ربات <b>۷، ۳ و ۱ روز قبل</b> به دانشجویانِ {f.group === 'هر دو' ? 'هر دو گروه' : `گروه ${f.group}`} خودکار یادآوری می‌کند.
          </div>
          <div className="row">
            <button className="btn" onClick={() => setStep(2)}>→ بازگشت</button>
            <button className="btn primary" style={{ flex: 1 }} disabled={busy} onClick={submit}>
              {busy ? '⏳ …' : row ? '💾 ذخیره‌ی تغییرات' : '📝 ثبت آزمون'}
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}

/* ── 📊🌊 WA3 — تب نمرات: لیست اخیر + ثبت گروهی (همان grades ربات) ───── */
function GradesTab({ autoCreate = false, initial = {} }) {
  const [skip, setSkip] = useState((initial.page - 1) * 30);
  const [q, setQ] = useState(initial.q || '');
  const [search, setSearch] = useState(initial.q || '');
  const [lesson, setLesson] = useState(initial.lesson || '');
  const [group, setGroup] = useState(initial.group || '');
  const [intake, setIntake] = useState(initial.intake || '');
  const [dateFrom, setDateFrom] = useState(initial.dateFrom || '');
  const [dateTo, setDateTo] = useState(initial.dateTo || '');
  // 🛡 AUDIT-§۸۲ — ترم، یک محورِ فیلترِ واقعی است (نه فقط برچسبِ متنی)
  const [term, setTerm] = useState(initial.term || '');
  const [intakes, setIntakes] = useState([]);
  const [visibleColumns, setVisibleColumns] = useState([]);
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const [permErr, setPermErr] = useState(false);
  const [bulkOpen, setBulkOpen] = useState(autoCreate);
  const [editGrade, setEditGrade] = useState(null);
  const [deleteGrade, setDeleteGrade] = useState(null);
  useEffect(() => { if (autoCreate) setBulkOpen(true); }, [autoCreate]);
  useEffect(() => { api.gradeIntakes().then(r => setIntakes(r.intakes || [])).catch(() => setIntakes([])); }, []);
  const LIMIT = 30;

  const load = async () => {
    setErr('');
    try { setData(await api.gradesRecent(skip, LIMIT, { q, lesson, group, intake, date_from: dateFrom, date_to: dateTo, term })); }
    catch (e) { if (e.status === 403) setPermErr(true); else setErr(errText(e)); }
  };
  useEffect(() => { const t = setTimeout(() => { setQ(search.trim()); setSkip(0); }, 350); return () => clearTimeout(t); }, [search]);
  useEffect(() => { setData(null); load(); }, [skip, q, lesson, group, intake, dateFrom, dateTo, term]);
  useEffect(() => { writeHashQuery('/exams', { tab: 'grades', q: search, lesson, group, intake, date_from: dateFrom, date_to: dateTo, term, page: skip ? Math.floor(skip / LIMIT) + 1 : '' }); }, [search, lesson, group, intake, dateFrom, dateTo, term, skip]);

  if (permErr) return <NoPerm text="مدیریت نمرات نیازمند مجوز «مدیریت نمرات» (grades.manage) است" />;
  if (err) return <ErrorState error={err} onRetry={load} />;

  const total = data?.total || 0;
  const page = Math.floor(skip / LIMIT) + 1;
  const pages = Math.max(1, Math.ceil(total / LIMIT));
  const cols = [
    { k: 'student_name', label: 'دانشجو', render: r => (
      <div><b style={{ color: 'var(--txt)' }}>{r.student_name || '—'}</b>
        <div className="muted code">{r.student_number || `#${r.student_id}`}</div></div>) },
    { k: 'lesson', label: 'درس' },
    { k: 'term', label: 'ترم', render: r => (r.term ? <B kind="purple">{r.term}</B> : <span className="muted">—</span>) },
    { k: 'exam_title', label: 'عنوان آزمون' },
    { k: 'exam_date', label: 'تاریخ', render: r => <FaDate value={r.exam_date} /> },
    { k: 'score', label: 'نمره', render: r => (
      <B kind={r.score >= 10 ? 'ok' : 'bad'}>{Number(r.score).toLocaleString('fa')}</B>) },
    { k: 'ops', label: '', stop: true, render: r => <div className="row" style={{ gap: 4 }}>
      <button className="btn sm" onClick={() => setEditGrade(r)}>✏️ اصلاح</button>
      <button className="btn sm danger" onClick={() => setDeleteGrade(r)} aria-label={`حذف نمره ${r.student_name}`}>🗑</button>
    </div> },
  ];
  return (
    <>
      <div className="row">
        <div><div className="h1">نمرات</div>
          <div className="sub">ثبت گروهی نمره — همان «📊 مدیریت نمرات» پنل ربات؛ به هر دانشجو از سمت ربات خبر می‌رسد</div></div>
        <span className="spacer" />
        <button className="btn primary" onClick={() => setBulkOpen(true)}>➕ ثبت گروهی نمره</button>
      </div>
      <div className="filter-bar" style={{ marginTop: 10 }}>
        <input className="inp" style={{ flex: 1 }} placeholder="جست‌وجوی دانشجو، شماره، درس یا عنوان آزمون…" value={search} onChange={e => setSearch(e.target.value)} />
        <input className="inp" placeholder="فیلتر درس…" value={lesson} onChange={e => { setLesson(e.target.value); setSkip(0); }} />
        <select className="inp" value={group} onChange={e => { setGroup(e.target.value); setSkip(0); }}><option value="">همه گروه‌ها</option><option value="1">گروه ۱</option><option value="2">گروه ۲</option></select>
        <select className="inp" value={intake} onChange={e => { setIntake(e.target.value); setSkip(0); }}><option value="">همه ورودی‌ها</option>{intakes.map(item => <option key={item.code} value={item.code}>{item.label}</option>)}</select>
        <select className="inp" value={term} onChange={e => { setTerm(e.target.value); setSkip(0); }} aria-label="فیلتر ترم">
          <option value="">همه ترم‌ها</option>{(data?.terms || []).map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <label className="row"><span className="muted">از</span><PersianDatePicker value={dateFrom} onChange={value => { setDateFrom(value); setSkip(0); }} ariaLabel="از تاریخ شمسی" /></label>
        <label className="row"><span className="muted">تا</span><PersianDatePicker value={dateTo} onChange={value => { setDateTo(value); setSkip(0); }} ariaLabel="تا تاریخ شمسی" /></label>
      </div>
      <SavedViews scope="grades" filters={{ q: search, lesson, group, intake, date_from: dateFrom, date_to: dateTo, term }} columns={visibleColumns} onApply={(f, item) => { setSearch(f.q || ''); setLesson(f.lesson || ''); setGroup(f.group || ''); setIntake(f.intake || ''); setDateFrom(f.date_from || ''); setDateTo(f.date_to || ''); setTerm(f.term || ''); setVisibleColumns(item.columns || []); setSkip(0); }} label="نماهای نمره" />

      {!data ? <Loading /> : (
        <>
          {(data.by_term || []).length > 0 && <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginBottom: 10, padding: '8px 10px', background: 'var(--soft-purple, var(--bg))', borderRadius: 'var(--r-md)', border: '1px solid var(--bd)' }}>
            <span className="muted" style={{ fontSize: 12, fontWeight: 800 }}>🎓 فیلتر ترم (هر ترم جدا):</span>
            <button type="button" className={`btn sm ${term ? '' : 'primary'}`} onClick={() => { setTerm(''); setSkip(0); }}>همه · {Number(total).toLocaleString('fa')}</button>
            {data.by_term.map(t => <button key={t.term || 'none'} type="button"
                  className={`btn sm ${term === t.term ? 'primary' : ''}`}
                  onClick={() => { setTerm(t.term); setSkip(0); }}
                  title={t.term || 'نمره‌هایی که درسشان در فهرست دروسِ ترم پیدا نشد'}>
              {t.term || 'بدون ترم'} · {Number(t.count).toLocaleString('fa')}
              {t.avg != null ? ` · میانگین ${Number(t.avg).toLocaleString('fa')}` : ''}
            </button>)}
          </div>}
          {term ? (
            <DataTable columns={cols} rows={data.grades} colToggle visibleColumns={visibleColumns} onColumnsChange={setVisibleColumns} empty={
              <div className="center-state">برای «{term}» نمره‌ای ثبت نشده است.</div>} />
          ) : (data.by_term || []).length > 1 ? (
            <div style={{ display: 'grid', gap: 14 }}>
              {data.by_term.map(group => {
                const rows = (data.grades || []).filter(r => (r.term || '') === (group.term || ''));
                if (!rows.length) return null;
                return (
                  <div key={group.term || 'none'} className="card" style={{ overflow: 'hidden' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 12px', background: 'var(--bg)', borderBottom: '1px solid var(--bd)', flexWrap: 'wrap' }}>
                      <B kind="purple">{group.term || 'بدون ترم'}</B>
                      <span className="muted" style={{ fontSize: 12 }}>{Number(group.count).toLocaleString('fa')} نمره</span>
                      {group.avg != null && <B kind={group.avg >= 10 ? 'ok' : 'bad'}>میانگین {Number(group.avg).toLocaleString('fa')} / ۲۰</B>}
                      <span className="spacer" />
                      <button className="btn sm" onClick={() => { setTerm(group.term); setSkip(0); }}>فقط همین ترم ←</button>
                    </div>
                    <DataTable columns={cols} rows={rows} colToggle visibleColumns={visibleColumns} onColumnsChange={setVisibleColumns} empty={<div className="center-state">نمره‌ای نیست</div>} />
                  </div>
                );
              })}
              {!(data.by_term || []).some(g => (data.grades || []).some(r => (r.term || '') === (g.term || ''))) && (
                <DataTable columns={cols} rows={data.grades} colToggle visibleColumns={visibleColumns} onColumnsChange={setVisibleColumns} empty={<div className="center-state">نمره‌ای ثبت نشده</div>} />
              )}
            </div>
          ) : (
            <DataTable columns={cols} rows={data.grades} colToggle visibleColumns={visibleColumns} onColumnsChange={setVisibleColumns} empty={
              <div className="center-state">نمره‌ای ثبت نشده</div>} />
          )}
          <div className="row" style={{ marginTop: 10 }}>
            <span className="muted">مجموع: {Number(total).toLocaleString('fa')} نمره</span>
            <span className="spacer" />
            <button className="btn sm" disabled={skip <= 0} onClick={() => setSkip(Math.max(0, skip - LIMIT))}>قبلی ◂</button>
            <B>{Number(page).toLocaleString('fa')} / {Number(pages).toLocaleString('fa')}</B>
            <button className="btn sm" disabled={skip + LIMIT >= total} onClick={() => setSkip(skip + LIMIT)}>▸ بعدی</button>
          </div>
        </>
      )}
      {bulkOpen && <GradeBulkModal onClose={(ch) => { setBulkOpen(false); if (ch) { setSkip(0); load(); } }} />}
      {editGrade && <GradeEditModal row={editGrade} onClose={(ok) => { setEditGrade(null); if (ok) load(); }} />}
      {deleteGrade && <Confirm danger text={`حذف نمره ${deleteGrade.student_name} در «${deleteGrade.lesson} — ${deleteGrade.exam_title}»؟ به دانشجو اطلاع داده می‌شود.`}
        onYes={async () => { const g = deleteGrade; setDeleteGrade(null); try { await api.gradeDelete(g.id); toast('نمره حذف و به دانشجو اطلاع داده شد'); load(); } catch (e) { toast(errText(e), 'err'); } }}
        onNo={() => setDeleteGrade(null)} />}
    </>
  );
}

function GradeEditModal({ row, onClose }) {
  const [score, setScore] = useState(row.score);
  const [busy, setBusy] = useState(false);
  return <Modal title={`✏️ اصلاح نمره — ${row.student_name}`} onClose={() => onClose(false)}>
    <div className="grid" style={{ gap: 10 }}>
      <div className="panel panel-pad"><b>{row.lesson}</b> — {row.exam_title}<div className="muted">نمره فعلی: {Number(row.score).toLocaleString('fa')}</div></div>
      <label className="fld"><span>نمره جدید از ۲۰</span><input className="inp" type="number" min="0" max="20" step="0.25" value={score} onChange={e => setScore(e.target.value)} /></label>
      <DiffViewer before={{ نمره: row.score }} after={{ نمره: score === '' ? '—' : Number(score) }} />
      <div className="muted">پس از ذخیره، اصلاح نمره در Inbox و پیام ربات دانشجو اعلام می‌شود.</div>
      <div className="row"><button className="btn primary" disabled={busy || Number(score) < 0 || Number(score) > 20 || score === ''} onClick={async () => {
        setBusy(true); try { await api.gradeUpdate(row.id, Number(score)); toast('نمره اصلاح و به دانشجو اطلاع داده شد ✅'); onClose(true); }
        catch (e) { toast(errText(e), 'err'); setBusy(false); }
      }}>ثبت اصلاح</button><button className="btn" onClick={() => onClose(false)}>انصراف</button></div>
    </div>
  </Modal>;
}

function GradeBulkModal({ onClose }) {
  const [meta, setMeta] = useState({ lesson: '', exam_title: '', exam_date: '', term: '' });
  const [rows, setRows] = useState([{ q: '', hits: null, picked: null, score: '' }]);
  const [busy, setBusy] = useState(false);
  const [termTouched, setTermTouched] = useState(false);
  // 🛡 §۸۲-ج — طبقه‌بندی ترمی: ترم الزامی است و هر ترم جدا ذخیره می‌شود (بدون «بدون ترم»).
  const [termOptions, setTermOptions] = useState([]);
  const [suggestedTerm, setSuggestedTerm] = useState('');
  useEffect(() => {
    api.gradeTermOptions().then(r => setTermOptions(r.terms || [])).catch(() => setTermOptions([]));
  }, []);
  // حدس ترم از روی درس برای پرکردن خودکار منو (اما ثبت همچنان ترم صریح می‌خواهد)
  useEffect(() => {
    const name = meta.lesson.trim();
    if (!name || name.length < 2) { setSuggestedTerm(''); return; }
    if (meta.term) { setSuggestedTerm(''); return; }
    let cancelled = false;
    const t = setTimeout(() => {
      api.gradeLessonTerm(name).then(r => {
        if (!cancelled && r?.term) setSuggestedTerm(r.term);
        else if (!cancelled) setSuggestedTerm('');
      }).catch(() => { if (!cancelled) setSuggestedTerm(''); });
    }, 450);
    return () => { cancelled = true; clearTimeout(t); };
  }, [meta.lesson]);
  // اگر ترم خالی و پیشنهاد آمد، خودکار انتخاب کن (قابل ویرایش دستی)
  useEffect(() => {
    if (suggestedTerm && !meta.term) {
      setMeta(m => ({ ...m, term: suggestedTerm }));
    }
  }, [suggestedTerm]);
  const [importReport, setImportReport] = useState(null);
  const setRow = (i, patch) => setRows(rs => rs.map((r, j) => j === i ? { ...r, ...patch } : r));
  const importCSV = async (file) => {
    if (!file) return;
    const text = await file.text();
    const lines = text.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
    const parsed = []; const failed = []; const seen = new Set();
    lines.forEach((line, index) => {
      const parts = line.split(/[;,\t]/).map(x => x.trim().replace(/^"|"$/g, ''));
      const id = Number(parts[0]); const score = Number(parts[1]);
      if (index === 0 && !Number.isFinite(id)) return;
      if (!Number.isInteger(id) || id <= 0 || !Number.isFinite(score) || score < 0 || score > 20) {
        failed.push({ line: index + 1, value: line }); return;
      }
      if (seen.has(id)) { failed.push({ line: index + 1, value: 'Telegram ID تکراری' }); return; }
      seen.add(id); parsed.push({ q: `#${id}`, hits: null, picked: { id, name: `کاربر #${id}` }, score });
    });
    setRows(parsed.length ? parsed : [{ q: '', hits: null, picked: null, score: '' }]);
    setImportReport({ parsed: parsed.length, failed });
  };

  const find = async (i) => {
    const q = rows[i].q.trim();
    if (q.length < 2) return toast('حداقل ۲ حرف برای جست‌وجو', 'err');
    try { setRow(i, { hits: (await api.gradesFind(q)).students || [], picked: null }); }
    catch (e) { toast(errText(e), 'err'); }
  };
  const submit = async () => {
    const entries = rows.filter(r => r.picked && r.score !== '').map(r => ({
      student_id: r.picked.id, score: Number(r.score),
    }));
    if (!entries.length) return toast('حداقل یک دانشجو با نمره لازم است', 'err');
    setBusy(true);
    try {
      const r = await api.gradesBulk({ entries, lesson: meta.lesson.trim(),
        exam_title: meta.exam_title.trim(), exam_date: meta.exam_date,
        term: meta.term });
      toast(`${r.updated} نمره ثبت شد و برای دانشجویان ارسال شد 📊`);
      onClose(true);
    } catch (e) { toast(errText(e), 'err'); setBusy(false); }
  };

  return (
    <Modal title="➕ ثبت گروهی نمره" onClose={() => onClose(false)}>
      <div className="grid" style={{ gap: 10 }}>
        <div className="row">
          <input className="inp" placeholder="درس *" value={meta.lesson}
                 onChange={e => setMeta({ ...meta, lesson: e.target.value })} />
          <input className="inp" placeholder="عنوان آزمون *" value={meta.exam_title}
                 onChange={e => setMeta({ ...meta, exam_title: e.target.value })} />
          <PersianDatePicker value={meta.exam_date} onChange={value => setMeta({ ...meta, exam_date: value })} ariaLabel="تاریخ شمسی نمره" />
        </div>
        <div className="row" style={{ alignItems: 'flex-start' }}>
          <div style={{ flex: 1 }}>
            <label className="fld" style={{ margin: 0 }}><span>ترم * <span style={{ color: 'var(--c-err)' }}>(الزامی — هر ترم جدا ثبت می‌شود)</span></span>
              <select className="inp" value={meta.term} aria-label="ترم نمره"
                      onChange={e => { setMeta({ ...meta, term: e.target.value }); setTermTouched(true); }}
                      style={{ borderColor: termTouched && !meta.term ? 'var(--c-err)' : undefined, background: !meta.term ? 'var(--bg-warn, var(--bg))' : undefined }}>
                <option value="" disabled>— ترم را انتخاب کنید * —</option>
                {termOptions.map(t => <option key={t} value={t}>{t}{suggestedTerm === t ? ' (پیشنهادی)' : ''}</option>)}
              </select>
            </label>
            {suggestedTerm && !termTouched && meta.term === suggestedTerm && (
              <div className="muted" style={{ fontSize: 12, marginTop: 4, color: 'var(--c-ok)' }}>✓ ترم پیشنهادی از روی درس: <b>{suggestedTerm}</b> — قابل تغییر دستی</div>
            )}
            {termTouched && !meta.term && (
              <div style={{ fontSize: 12, marginTop: 4, color: 'var(--c-err)' }}>⚠️ ترم الزامی است — بدون انتخاب ترم ثبت انجام نمی‌شود.</div>
            )}
          </div>
          <div className="panel panel-pad" style={{ background: 'var(--soft-purple, var(--bg))', borderColor: 'var(--bd-purple, var(--bd))', minWidth: 220, flex: '0 0 260px' }}>
            <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--c-purple, var(--txt))' }}>🎓 طبقه‌بندی ترمی</div>
            <div className="muted" style={{ fontSize: 12, lineHeight: 1.7, marginTop: 4 }}>
              هر درس به یک ترم متصل است و کارنامه‌ی دانشجو <b>هر ترم را جدا</b> با میانگین جدا نشان می‌دهد. ترم را دقیق انتخاب کنید تا نمرات «بدون ترم» تولید نشود.
            </div>
          </div>
        </div>
        <div className="panel panel-pad" style={{ background: 'var(--bg)' }}>
          <div className="row"><div><b>درون‌ریزی CSV</b><div className="muted">دو ستون: Telegram ID و نمره؛ جداشده با comma، semicolon یا tab</div></div>
            <span className="spacer" /><input type="file" className="inp" accept=".csv,text/csv,text/plain" onChange={e => importCSV(e.target.files?.[0])} /></div>
          {importReport && <div className="row" style={{ marginTop: 8 }}><B kind="ok">معتبر: {fa(importReport.parsed)}</B>
            <B kind={importReport.failed.length ? 'bad' : 'ok'}>خطادار/تکراری: {fa(importReport.failed.length)}</B>
            {!!importReport.failed.length && <span className="muted">خطوط: {importReport.failed.slice(0, 8).map(x => x.line).join('، ')}</span>}</div>}
        </div>
        {rows.map((r, i) => (
          <div key={i} className="panel panel-pad" style={{ background: 'var(--bg)' }}>
            <div className="row">
              <input className="inp" style={{ flex: 1 }} placeholder="نام/شماره دانشجویی/یوزرنیم…"
                     value={r.q} onChange={e => setRow(i, { q: e.target.value, hits: null, picked: null })}
                     onKeyDown={e => e.key === 'Enter' && find(i)} />
              <button className="btn sm" onClick={() => find(i)} aria-label={`جست‌وجوی کاربر ردیف ${i + 1}`}>🔎</button>
              <input className="inp" type="number" step="0.25" min="0" max="20" style={{ width: 90 }}
                     placeholder="نمره" value={r.score} onChange={e => setRow(i, { score: e.target.value })} />
              <button className="btn sm danger" disabled={rows.length === 1}
                      onClick={() => setRows(rs => rs.filter((_, j) => j !== i))} aria-label={`حذف ردیف ${i + 1}`}>✕</button>
            </div>
            {r.hits && !r.picked && (
              <div style={{ marginTop: 6 }}>
                {r.hits.length === 0 && <span className="muted">دانشجویی یافت نشد</span>}
                {r.hits.slice(0, 5).map(s => (
                  <button key={s.id} className="btn sm" style={{ margin: '3px 0 3px 5px' }}
                          onClick={() => setRow(i, { picked: s, hits: null, q: `${s.name} (${s.student_id || s.id})` })}>
                    {s.name} · <span className="code">{s.student_id || s.id}</span> {s.group ? `· ${s.group}` : ''}
                  </button>
                ))}
              </div>
            )}
            {r.picked && <div className="muted" style={{ marginTop: 5 }}>✅ {r.picked.name} انتخاب شد</div>}
          </div>
        ))}
        <div className="row">
          <button className="btn sm" onClick={() => setRows(rs => [...rs, { q: '', hits: null, picked: null, score: '' }])}>➕ ردیف جدید</button>
          <span className="spacer" />
          <span className="muted">{rows.filter(r => r.picked && r.score !== '').length} دانشجو آماده</span>
        </div>
        <div className="row">
          <button className="btn primary" disabled={busy || !meta.lesson.trim() || !meta.exam_title.trim() || !meta.exam_date || !meta.term}
                  onClick={() => { if (!meta.term) { setTermTouched(true); return toast('ترم الزامی است — لطفاً ترم را انتخاب کنید', 'err'); } submit(); }}>{busy ? '⏳ …' : 'ثبت و ارسال به دانشجویان'}</button>
          <button className="btn" onClick={() => onClose(false)}>انصراف</button>
        </div>
        {!meta.term && <div style={{ fontSize: 12, color: 'var(--c-err)', marginTop: 4 }}>⚠️ بدون انتخاب ترم، ثبت گروهی انجام نمی‌شود — لطفاً از منوی ترم یک گزینه را برگزینید.</div>}
      </div>
    </Modal>
  );
}
