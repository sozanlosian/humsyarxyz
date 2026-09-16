import React, { useEffect, useState } from 'react';
import { api, errText } from '../api.js';
import { Loading, ErrorState, Empty, B, FaDateTime, FilterBar, PageHeader, toast, NoPerm, Modal, Confirm } from '../ui.jsx';
import { PersianDatePicker } from '../PersianDatePicker.jsx';
import SavedViews from '../SavedViews.jsx';
import { queryNumber, readHashQuery, writeHashQuery } from '../urlState.js';

// 🎫🌊 W-Admin — Support Command Center سه‌ستونه: صف | گفت‌وگو | کانتکست کاربر
// (اصلاح باگ: فیلد پاسخ = message — قبلاً text می‌رفت و 422 می‌شد؛ حباب support راست‌چین شد)
export default function Tickets({ go, me }) {
  const initial = readHashQuery();
  const [status, setStatus] = useState(initial.get('status') || 'open');
  const [list, setList] = useState(null);
  const [err, setErr] = useState('');
  const [denied, setDenied] = useState(false);
  const [cur, setCur] = useState(null);
  const [detail, setDetail] = useState(null);
  const [ctx, setCtx] = useState(null);          // user360-lite برای کانتکست
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [sel, setSel] = useState([]);
  const [bulkResult, setBulkResult] = useState(null);
  const [bulkConfirm, setBulkConfirm] = useState(null);
  const [q, setQ] = useState(initial.get('q') || '');
  const [search, setSearch] = useState(initial.get('q') || '');
  const [intake, setIntake] = useState(initial.get('intake') || '');
  const [priority, setPriority] = useState(initial.get('priority') || '');
  const [assignee, setAssignee] = useState(initial.get('assignee') || '');
  const [unanswered, setUnanswered] = useState(initial.get('unanswered') || '');
  const [dateFrom, setDateFrom] = useState(initial.get('date_from') || '');
  const [dateTo, setDateTo] = useState(initial.get('date_to') || '');
  const [sortBy, setSortBy] = useState(initial.get('sort_by') || 'created_at');
  const [sortDir, setSortDir] = useState(initial.get('sort_dir') || 'desc');
  const [advanced, setAdvanced] = useState(!!(initial.get('unanswered') || initial.get('date_from') || initial.get('date_to') || initial.get('sort_by')));
  const [page, setPage] = useState(queryNumber(initial, 'page', 1));
  const [options, setOptions] = useState({ assignees: [], intakes: [] });
  const [analytics, setAnalytics] = useState(null);
  const [note, setNote] = useState('');
  const [tags, setTags] = useState('');
  const LIMIT = 30;
  const canManage = !!me?.is_owner || (me?.perms || []).includes('tickets.manage');
  const canReply = !!me?.is_owner || (me?.perms || []).includes('tickets.reply');

  const bulk = async (action, ids = sel) => {
    if (!ids.length) return;
    try {
      const r = await api.ticketsBulk(action, ids);
      setBulkResult({ ...r, action });
      toast(`${r.done} موفق · ${r.skipped?.length || 0} ردشده · ${r.failed?.length || 0} ناموفق`, r.failed?.length ? 'err' : 'ok');
      setSel([]); load();
    } catch (e) { toast(errText(e), 'err'); }
  };

  const load = async () => {
    setErr('');
    try { setList(await api.tickets({ status, q, intake, priority, assignee_id: assignee,
      unanswered, date_from: dateFrom, date_to: dateTo, sort_by: sortBy, sort_dir: sortDir,
      page, limit: LIMIT })); }
    catch (e) { if (e.status === 403) setDenied(true); else setErr(errText(e)); }
  };
  useEffect(() => { const t = setTimeout(() => { setQ(search.trim()); setPage(1); }, 350); return () => clearTimeout(t); }, [search]);
  useEffect(() => { writeHashQuery('/tickets', { status: status !== 'open' ? status : '', q: search,
    intake, priority, assignee, unanswered, date_from: dateFrom, date_to: dateTo,
    sort_by: sortBy !== 'created_at' ? sortBy : '', sort_dir: sortDir !== 'desc' ? sortDir : '',
    page: page > 1 ? page : '' });
  }, [status, search, intake, priority, assignee, unanswered, dateFrom, dateTo, sortBy, sortDir, page]);
  useEffect(() => { load(); setSel([]); }, [status, q, intake, priority, assignee, unanswered, dateFrom, dateTo, sortBy, sortDir, page]);
  // 🌊 W8/UX-04 — پاسخ‌های آماده
  const [canned, setCanned] = useState([]);
  const [cannedOpen, setCannedOpen] = useState(false);
  useEffect(() => {
    api.ticketAssignees().then(setOptions).catch(() => {});
    if (canManage) api.ticketAnalytics().then(setAnalytics).catch(() => {});
    api.cannedList().then(r => setCanned(r.items || [])).catch(() => {});
  }, [canManage]);

  const open = async (t) => {
    const id = t.id ?? t.tid;
    setCur(id); setDetail(null); setCtx(null);
    try {
      const d = (await api.ticket(id)).ticket;
      setDetail(d); setTags((d.tags || []).join('، ')); setNote('');
      // کانتکست غنی: user360 موجود (users.view) — ضدخطا، اختیاری
      if (d.user?.id) api.user360(d.user.id).then(x => setCtx(x)).catch(() => {});
    } catch (e) { toast(errText(e), 'err'); }
  };
  const send = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try { await api.ticketReply(cur, text.trim()); setText(''); open({ id: cur }); load(); }
    catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  const act = async (fn, okMsg) => {
    try { await fn(cur); open({ id: cur }); load(); toast(okMsg); }
    catch (e) { toast(errText(e), 'err'); }
  };
  const patchMeta = async (body) => {
    try { await api.ticketMeta(cur, body); toast('متادیتای تیکت ذخیره شد'); open({ id: cur }); load(); if (canManage) api.ticketAnalytics().then(setAnalytics).catch(() => {}); }
    catch (e) { toast(errText(e), 'err'); }
  };
  const addNote = async () => {
    if (!note.trim()) return;
    try { await api.ticketNote(cur, note.trim()); setNote(''); toast('یادداشت داخلی ثبت شد'); open({ id: cur }); }
    catch (e) { toast(errText(e), 'err'); }
  };

  if (denied) return <NoPerm text="این بخش نیازمند tickets.reply یا tickets.manage است" />;
  if (err) return <ErrorState title="بارگذاری تیکت‌ها ناموفق بود" error={err} onRetry={load} />;
  const items = (list && (list.tickets || list)) || [];

  return (
    <>
      <PageHeader title="کنسول پشتیبانی" description="صف، گفت‌وگو و کانتکست کاربر بدون ترک صفحه"
        actions={<><button className="btn sm" title="خروجی CSV از تیکت‌های فیلترشده" onClick={() => api.exportTicketsCsv({ status, q: search, intake, priority,
          assignee_id: assignee, unanswered, date_from: dateFrom, date_to: dateTo, sort_by: sortBy, sort_dir: sortDir })}>📥 CSV همین صف</button>
          {canManage && sel.length > 0 && <><B kind="acc">{sel.length} انتخاب‌شده</B>
          <button className="btn sm ok" onClick={() => setBulkConfirm('close')}>✅ بستن گروهی</button>
          <button className="btn sm" onClick={() => setBulkConfirm('reopen')}>🔓 بازگشایی</button></>}</>} />

      {analytics && <div className="row" style={{ marginBottom: 10, flexWrap: 'wrap' }}>
        <B kind="warn">باز: {Number((analytics.status?.open || 0) + (analytics.status?.in_progress || 0) + (analytics.status?.waiting_user || 0) + (analytics.status?.resolved || 0)).toLocaleString('fa')}</B>
        <B kind="ok">بسته: {Number(analytics.status?.closed || 0).toLocaleString('fa')}</B>
        {analytics.avg_first_response_minutes != null && <B kind="acc">میانگین پاسخ نخست: {Number(analytics.avg_first_response_minutes).toLocaleString('fa')} دقیقه</B>}
        {analytics.avg_resolution_minutes != null && <B>میانگین حل: {Number(analytics.avg_resolution_minutes).toLocaleString('fa')} دقیقه</B>}
        {analytics.sample_limited && <span className="muted">آمار زمان بر مبنای ۵۰۰۰ تیکت اخیر</span>}
      </div>}
      <FilterBar>
        <div className="tabs" style={{ flex: 1, marginBottom: 0 }} role="tablist" aria-label="وضعیت تیکت‌ها">
          {[['open', '🟡 باز'], ['in_progress', '🔵 در حال بررسی'], ['waiting_user', '🟣 منتظر کاربر'], ['resolved', '✅ حل‌شده'], ['closed', '🟢 بسته'], ['', 'همه']].map(([k, v]) => (
            <button key={k} type="button" role="tab" aria-selected={status === k} className={`tab ${status === k ? 'on' : ''}`} onClick={() => { setStatus(k); setPage(1); }}>{v}</button>
          ))}
        </div>
        <input className="inp" style={{ width: 220 }} placeholder="🔎 موضوع/نام/متن…"
               value={search} onChange={e => setSearch(e.target.value)} />
        <select className="inp" value={intake} onChange={e => { setIntake(e.target.value); setPage(1); }}>
          <option value="">همه ورودی‌ها</option>{(options.intakes || []).map(i => <option key={i.code} value={i.code}>{i.label}</option>)}
        </select>
        <select className="inp" value={priority} onChange={e => { setPriority(e.target.value); setPage(1); }}>
          <option value="">همه اولویت‌ها</option><option value="urgent">فوری</option><option value="high">بالا</option><option value="normal">عادی</option><option value="low">کم</option>
        </select>
        {canManage && <select className="inp" value={assignee} onChange={e => { setAssignee(e.target.value); setPage(1); }}>
          <option value="">همه مسئولان</option>{(options.assignees || []).map(a => <option key={a.id} value={a.id}>{a.name || a.id}</option>)}
        </select>}
        <button className={`btn sm ${advanced ? 'primary' : ''}`} aria-expanded={advanced} onClick={() => setAdvanced(x => !x)}>⚙ پیشرفته</button>
      </FilterBar>
      {advanced && <FilterBar className="advanced-filter-bar">
        <label className="row"><input type="checkbox" checked={unanswered === 'true'} onChange={e => { setUnanswered(e.target.checked ? 'true' : ''); setPage(1); }} />بدون پاسخ پشتیبان</label>
        <label className="row"><span className="muted">از</span><PersianDatePicker value={dateFrom} onChange={value => { setDateFrom(value); setPage(1); }} ariaLabel="از تاریخ شمسی تیکت" /></label>
        <label className="row"><span className="muted">تا</span><PersianDatePicker value={dateTo} onChange={value => { setDateTo(value); setPage(1); }} ariaLabel="تا تاریخ شمسی تیکت" /></label>
        <select className="inp" value={sortBy} onChange={e => setSortBy(e.target.value)}><option value="created_at">مرتب‌سازی ثبت</option><option value="last_reply_at">آخرین پاسخ</option></select>
        <select className="inp" value={sortDir} onChange={e => setSortDir(e.target.value)}><option value="desc">نزولی</option><option value="asc">صعودی</option></select>
        <button className="btn sm" onClick={() => { setUnanswered(''); setDateFrom(''); setDateTo(''); setSortBy('created_at'); setSortDir('desc'); setPage(1); }}>پاک‌کردن</button>
      </FilterBar>}

      <SavedViews scope="tickets" filters={{ status, q: search, intake, priority, assignee, unanswered,
        date_from: dateFrom, date_to: dateTo, sort_by: sortBy, sort_dir: sortDir }} sort={{ key: sortBy, dir: sortDir }} onApply={f => {
        setStatus(f.status || 'open'); setSearch(f.q || ''); setIntake(f.intake || '');
        setPriority(f.priority || ''); setAssignee(f.assignee || ''); setUnanswered(f.unanswered || '');
        setDateFrom(f.date_from || ''); setDateTo(f.date_to || ''); setSortBy(f.sort_by || 'created_at'); setSortDir(f.sort_dir || 'desc');
        setAdvanced(!!(f.unanswered || f.date_from || f.date_to || f.sort_by)); setPage(1);
      }} label="صف‌های ذخیره‌شده" />

      <div className="tk-grid">
        {/* ستون ۱ — صف */}
        <div className="panel" style={{ maxHeight: '74vh', overflowY: 'auto' }}>
          {!list && <div className="panel-pad"><Loading /></div>}
          {list && !items.length && <Empty icon="🎫" text="تیکتی در این صف نیست" />}
          {items.map(t => {
            const id = t.id ?? t.tid;
            return (
              <div key={id} className={`tree-row ${cur === id ? 'on' : ''}`} role="button" tabIndex={0}
                   style={{ cursor: 'pointer', borderBottom: '1px solid var(--line)', alignItems: 'flex-start',
                            background: cur === id ? 'var(--panel2)' : '' }}
                   onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(t); } }}
                   onClick={() => open(t)}>
                {canManage && <input type="checkbox" checked={sel.includes(id)} aria-label="انتخاب تیکت"
                       onClick={e => e.stopPropagation()}
                       onChange={() => setSel(x => x.includes(id) ? x.filter(i => i !== id) : [...x, id])} />}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ color: 'var(--txt)', fontSize: 'var(--fs-body)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {t.subject || `تیکت ${id}`}
                  </div>
                  <div className="muted">
                    {t.user_name || ''} · <FaDateTime value={t.created_at} fallback="" />
                    {t.reply_count ? ` · 💬 ${Number(t.reply_count).toLocaleString('fa')}` : ''}
                  </div>
                </div>
                {t.priority !== 'normal' && <B kind={t.priority === 'urgent' ? 'bad' : 'warn'}>{t.priority === 'urgent' ? 'فوری' : t.priority === 'high' ? 'بالا' : 'کم'}</B>}
                {t.sla?.breached && <B kind="bad">🔴 SLA</B>}
                {t.assignee_name && <B>{t.assignee_name}</B>}
                <B kind={t.status === 'closed' ? 'ok' : t.status === 'open' ? 'bad' : 'warn'}>
                  {{ open: 'باز', in_progress: 'در حال بررسی', waiting_user: 'منتظر کاربر', resolved: 'حل‌شده', answered: 'پاسخ', closed: 'بسته' }[t.status] || t.status}
                </B>
              </div>
            );
          })}
          {list && Number(list.pages || 1) > 1 && <div className="panel-pad row" style={{ position: 'sticky', bottom: 0, background: 'var(--panel)' }}>
            <button className="btn sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>قبلی</button>
            <span className="spacer" /><span className="muted">{Number(list.total || 0).toLocaleString('fa')} تیکت · صفحه {page.toLocaleString('fa')} از {Number(list.pages).toLocaleString('fa')}</span><span className="spacer" />
            <button className="btn sm" disabled={page >= list.pages} onClick={() => setPage(p => p + 1)}>بعدی</button>
          </div>}
        </div>

        {/* ستون ۲ — گفت‌وگو */}
        <div className="panel" style={{ minHeight: '66vh', display: 'flex', flexDirection: 'column' }}>
          {!cur && <Empty icon="💬" text="یک تیکت را از صف انتخاب کنید" />}
          {cur && !detail && <div className="panel-pad"><Loading /></div>}
          {detail && (
            <>
              <div className="panel-pad row" style={{ borderBottom: '1px solid var(--line)', padding: '10px 14px' }}>
                <b style={{ color: 'var(--txt)', fontSize: 'var(--fs-card)' }}>{detail.subject || `تیکت ${detail.id}`}</b>
                <span className="muted">#{detail.id} · <FaDateTime value={detail.created_at} /></span>
                <span className="spacer" />
                <B kind={detail.status === 'closed' ? 'ok' : detail.status === 'open' ? 'bad' : 'warn'}>
                  {{ open: 'باز', in_progress: 'در حال بررسی', waiting_user: 'منتظر کاربر', resolved: 'حل‌شده', answered: 'پاسخ‌داده‌شده', closed: 'بسته' }[detail.status] || detail.status}
                </B>
                {detail.sla?.breached && <B kind="bad">🔴 مهلت SLA گذشته</B>}
                {!detail.sla?.breached && !detail.sla?.responded && !!detail.sla?.due_at && <B>⏱ <FaDateTime value={detail.sla.due_at} fallback="" /></B>}
              </div>
              <div className="chat" style={{ flex: 1, overflowY: 'auto', maxHeight: '48vh' }}>
                {detail.message && (
                  <div className="bubble user">
                    {detail.message}
                    <div className="muted" style={{ marginTop: 4 }}><FaDateTime value={detail.created_at} fallback="" /></div>
                  </div>
                )}
                {(detail.replies || []).map((m, i) => (
                  <div key={i} className={`bubble ${(m.sender || m.by) === 'support' || (m.sender || m.by) === 'admin' ? 'admin' : 'user'}`}>
                    {m.text || m.message}
                    <div className="muted" style={{ marginTop: 4 }}>
                      {(m.sender || m.by) === 'support' || (m.sender || m.by) === 'admin' ? '🛟 پشتیبانی · ' : ''}<FaDateTime value={m.at || m.created_at} fallback="" />
                    </div>
                  </div>
                ))}
              </div>
              {detail.status !== 'closed' ? (<>
                {canReply && !!canned.filter(c => c.active !== false).length && <div className="panel-pad row" style={{ borderTop: '1px solid var(--line)' }}>
                  <select className="inp" style={{ flex: 1 }} value="" onChange={e => { const c = canned.find(x => x.id === e.target.value); if (c) setText(c.text); }}>
                    <option value="">⚡ درج پاسخ آماده…</option>
                    {canned.filter(c => c.active !== false).map(c => <option key={c.id} value={c.id}>{c.category ? `[${c.category}] ` : ''}{c.title}</option>)}
                  </select>
                  {canManage && <button className="btn sm" onClick={() => setCannedOpen(true)}>مدیریت</button>}
                </div>}
                <div className="panel-pad row" style={{ borderTop: '1px solid var(--line)', flexWrap: 'nowrap' }}>
                  {canReply ? <>
                    <textarea className="inp" rows={1} style={{ flex: 1, resize: 'none' }}
                              placeholder="پاسخ پشتیبانی… (Enter برای ارسال)"
                              value={text} onChange={e => setText(e.target.value)}
                              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }} />
                    <button className="btn primary" disabled={busy || !text.trim()} onClick={send}>ارسال ➤</button>
                  </> : <span className="muted">مجوز پاسخ‌گویی ندارید</span>}
                  {canManage && <button className="btn sm" onClick={() => act(api.ticketClose, 'تیکت بسته شد ✅')}>✅ بستن</button>}
                </div>
              </>) : (
                <div className="panel-pad row" style={{ borderTop: '1px solid var(--line)' }}>
                  <span className="muted">این تیکت بسته شده است.</span>
                  <span className="spacer" />
                  {canManage && <button className="btn sm" onClick={() => act(api.ticketReopen, 'بازگشایی شد 🔓')}>🔓 بازگشایی</button>}
                </div>
              )}
            </>
          )}
        </div>

        {/* ستون ۳ — کانتکست کاربر */}
        <div className="panel panel-pad tk-ctx">
          {!detail && <Empty icon="👤" text="کانتکست کاربر" />}
          {detail && (
            <>
              <div className="row" style={{ flexWrap: 'nowrap' }}>
                <div className="avatar" style={{ width: 38, height: 38, fontSize: 'var(--fs-section)' }}>
                  {(detail.user?.name || '?')[0]}
                </div>
                <div style={{ minWidth: 0 }}>
                  <b style={{ color: 'var(--txt)' }}>{detail.user?.name || '—'}</b>
                  <div className="muted code">#{detail.user?.id}</div>
                </div>
              </div>
              <dl className="kv" style={{ gridTemplateColumns: '92px 1fr' }}>
                {Object.entries({
                  'شماره دانشجویی': detail.user?.student_id,
                  'ورودی': detail.user?.intake,
                  'گروه': detail.user?.group,
                }).filter(([, v]) => v).map(([k, v]) => (
                  <React.Fragment key={k}><dt>{k}</dt><dd>{String(v)}</dd></React.Fragment>
                ))}
              </dl>
              {ctx ? (
                <dl className="kv" style={{ gridTemplateColumns: '92px 1fr' }}>
                  <dt>وضعیت حساب</dt>
                  <dd>{ctx.user?.suspended ? '⏸ تعلیق' : ctx.user?.approved ? '✅ فعال' : '🕓 در انتظار'}</dd>
                  <dt>اشتراک</dt>
                  <dd>{ctx.subscription?.status === 'active'
                    ? `💎 ${ctx.subscription.plan} · ${ctx.subscription.days_left ?? '—'} روز` : '—'}</dd>
                  <dt>پاسخ‌ها</dt>
                  <dd>{Number(ctx.user?.total_answers || 0).toLocaleString('fa')}</dd>
                  <dt>تیکت‌ها</dt>
                  <dd>{Number(ctx.counts?.tickets || 0).toLocaleString('fa')}</dd>
                </dl>
              ) : detail && <div className="muted" style={{ fontSize: 'var(--fs-label)' }}>در حال تکمیل کانتکست…</div>}
              {canManage && <div className="grid" style={{ gap: 7, marginTop: 12 }}>
                <b>مدیریت صف</b>
                <div className="row"><select className="inp" style={{ flex: 1 }} value={detail.priority || 'normal'} onChange={e => patchMeta({ priority: e.target.value })}>
                  <option value="low">اولویت کم</option><option value="normal">اولویت عادی</option><option value="high">اولویت بالا</option><option value="urgent">اولویت فوری</option>
                </select>
                <select className="inp" style={{ flex: 1 }} value={detail.assignee_id || ''} onChange={e => patchMeta({ assignee_id: e.target.value ? Number(e.target.value) : null })}>
                  <option value="">بدون مسئول</option>{(options.assignees || []).map(a => <option key={a.id} value={a.id}>{a.name || a.id}</option>)}
                </select></div>
                <div className="row"><select className="inp" style={{ flex: 1 }} value={detail.status || 'open'} onChange={e => patchMeta({ status: e.target.value })}>
                  <option value="open">🟡 باز</option><option value="in_progress">🔵 در حال بررسی</option><option value="waiting_user">🟣 منتظر کاربر</option><option value="resolved">✅ حل‌شده</option><option value="closed">🟢 بسته</option>
                </select>
                {detail.assignee_id != null && detail.assignee_active === false && <B kind="bad">⚠️ مسئول غیرفعال</B>}</div>
                <div className="row"><input className="inp" style={{ flex: 1 }} placeholder="برچسب‌ها با ویرگول…" value={tags} onChange={e => setTags(e.target.value)} />
                  <button className="btn sm" onClick={() => patchMeta({ tags: tags.split(/[،,]/).map(x => x.trim()).filter(Boolean) })}>ذخیره برچسب</button></div>
                {!!(detail.internal_notes || []).length && <div className="grid" style={{ gap: 5 }}>
                  {detail.internal_notes.map(n => <div key={n.id} className="panel panel-pad" style={{ background: 'var(--bg)' }}><div>{n.text}</div><div className="muted">فقط ادمین · {n.actor_name} · <FaDateTime value={n.at} /></div></div>)}
                </div>}
                <textarea className="inp" rows={2} maxLength={1500} placeholder="یادداشت داخلی — برای دانشجو ارسال نمی‌شود…" value={note} onChange={e => setNote(e.target.value)} />
                <button className="btn sm" disabled={!note.trim()} onClick={addNote}>افزودن یادداشت داخلی</button>
              </div>}
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn sm primary" onClick={() => go && go(`/users?q=${detail.user?.id || ''}`)}>👤 بازکردن در کاربران</button>
              </div>
            </>
          )}
        </div>
      </div>
      {bulkConfirm && <Confirm danger={bulkConfirm === 'close'} text={`${bulkConfirm === 'close' ? 'بستن' : 'بازگشایی'} ${sel.length} تیکت انتخاب‌شده؟`}
        onNo={() => setBulkConfirm(null)} onYes={async () => { const action = bulkConfirm; setBulkConfirm(null); await bulk(action); }} />}
      {cannedOpen && <CannedModal items={canned} onClose={() => setCannedOpen(false)}
        onChanged={() => api.cannedList().then(r => setCanned(r.items || [])).catch(() => {})} />}
      {bulkResult && <Modal title="گزارش عملیات گروهی تیکت" onClose={() => setBulkResult(null)}>
        <div className="row"><B kind="ok">موفق: {bulkResult.succeeded?.length || 0}</B><B>ردشده: {bulkResult.skipped?.length || 0}</B><B kind="bad">ناموفق: {bulkResult.failed?.length || 0}</B></div>
        {[...(bulkResult.skipped || []).map(x => ({ ...x, message: x.reason })), ...(bulkResult.failed || []).map(x => ({ ...x, message: x.error }))].slice(0, 30)
          .map((x, i) => <div className="row" key={`${x.id}-${i}`}><span className="code">{x.id}</span><span className="muted">{x.message}</span></div>)}
        {!!bulkResult.failed?.length && <button className="btn" onClick={() => bulk(bulkResult.action, bulkResult.failed.map(x => x.id))}>↻ تلاش مجدد ناموفق‌ها</button>}
      </Modal>}
    </>
  );
}

// 🌊 W8/UX-04 — مدیریت پاسخ‌های آماده
function CannedModal({ items, onClose, onChanged }) {
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [cat, setCat] = useState('');
  const [fcat, setFcat] = useState('');
  const [edit, setEdit] = useState(null);
  const [busy, setBusy] = useState(false);
  const cats = [...new Set((items || []).map(c => c.category).filter(Boolean))];
  const shown = fcat ? (items || []).filter(c => c.category === fcat) : (items || []);
  const save = async () => {
    if (!title.trim() || !text.trim()) return;
    setBusy(true);
    try {
      if (edit) await api.cannedUpdate(edit, { title: title.trim(), text: text.trim(), active: true, category: cat.trim() });
      else await api.cannedAdd({ title: title.trim(), text: text.trim(), active: true, category: cat.trim() });
      toast(edit ? 'ویرایش شد ✅' : 'افزوده شد ✅');
      setTitle(''); setText(''); setCat(''); setEdit(null); onChanged();
    } catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  const del = async (id) => {
    setBusy(true);
    try { await api.cannedDelete(id); toast('حذف شد'); onChanged(); }
    catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  return <Modal title="⚡ پاسخ‌های آماده" onClose={onClose} wide>
    <div className="grid" style={{ gap: 8 }}>
      {!!cats.length && <div className="row"><select className="inp" style={{ flex: 1 }} value={fcat} onChange={e => setFcat(e.target.value)}>
        <option value="">همه دسته‌ها</option>{cats.map(k => <option key={k} value={k}>{k}</option>)}
      </select></div>}
      {shown.map(c => <div key={c.id} className="panel panel-pad">
        <div className="row"><b style={{ flex: 1 }}>{c.title}</b>
          {c.category && <B>{c.category}</B>}
          <button className="btn sm" onClick={() => { setEdit(c.id); setTitle(c.title); setText(c.text); setCat(c.category || ''); }}>✏️</button>
          <button className="btn sm" disabled={busy} onClick={() => del(c.id)}>🗑</button></div>
        <div className="muted" style={{ whiteSpace: 'pre-wrap' }}>{(c.text || '').slice(0, 200)}</div>
      </div>)}
      {!items?.length && <Empty text="هنوز پاسخ آماده‌ای ثبت نشده" />}
      <div className="panel panel-pad"><b>{edit ? '✏️ ویرایش' : '➕ جدید'}</b>
        <div className="row" style={{ marginTop: 6 }}><input className="inp" style={{ flex: 2 }} placeholder="عنوان…" value={title} onChange={e => setTitle(e.target.value)} />
          <input className="inp" style={{ flex: 1 }} placeholder="دسته…" value={cat} onChange={e => setCat(e.target.value)} /></div>
        <textarea className="inp" style={{ marginTop: 6 }} rows={3} placeholder="متن پاسخ…" value={text} onChange={e => setText(e.target.value)} />
        <div className="row" style={{ marginTop: 6 }}><button className="btn primary sm" disabled={busy || !title.trim() || !text.trim()} onClick={save}>💾 ذخیره</button>
          {edit && <button className="btn sm" onClick={() => { setEdit(null); setTitle(''); setText(''); setCat(''); }}>انصراف</button>}</div>
      </div>
    </div>
  </Modal>;
}
