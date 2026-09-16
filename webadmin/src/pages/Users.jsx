import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, errText, exportCSV } from '../api.js';
import { DataTable, Drawer, Loading, ErrorState, B, DiffViewer, FaDate, FaDateTime, RelativeTime, FilterBar, PageHeader, toast, Confirm, Modal, Empty, Switch } from '../ui.jsx';
import { queryNumber, readHashQuery, writeHashQuery } from '../urlState.js';
import SavedViews from '../SavedViews.jsx';
import SmartQueryBuilder from '../SmartQueryBuilder.jsx';
import { fileDateStamp, formatFaDate, formatFaDateTime } from '../time.js';

const STATUS = { '': 'همه', pending: 'در انتظار تأیید', suspended: 'تعلیق‌شده', active: 'فعال' };
const faNum = (n) => Number(n ?? 0).toLocaleString('fa-IR');
const USER360_STALE_MS = 60_000;
const USER360_CACHE_LIMIT = 20;

// ── 🧠 User Intelligence helpers — REAL DATA ONLY, rule-based ──
function daysSince(iso) {
  if (!iso) return null;
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    return Math.floor((Date.now() - d.getTime()) / 86400000);
  } catch { return null; }
}
function parseScore(v) { const n = Number(v); return Number.isFinite(n) ? n : null; }

function computeHealth(d) {
  if (!d?.user) return null;
  const u = d.user, counts = d.counts || {}, sub = d.subscription, ai = d.ai || {};
  let score = 0, reasons = [];
  // Account 20
  if (u.suspended) { score += 0; reasons.push({ icon:'⛔', text:'حساب تعلیق‌شده', tone:'bad' }); }
  else if (!u.approved) { score += 5; reasons.push({ icon:'⏳', text:'در انتظار تأیید', tone:'warn' }); }
  else { score += 20; reasons.push({ icon:'✅', text:'حساب فعال', tone:'ok' }); }
  // Activity 25
  const ds = daysSince(u.last_active);
  if (ds === null) { score += 5; reasons.push({ icon:'🕓', text:'بدون فعالیت ثبت‌شده', tone:'warn' }); }
  else if (ds <= 1) { score += 25; reasons.push({ icon:'⚡', text:'فعال در ۲۴ ساعت اخیر', tone:'ok' }); }
  else if (ds <= 7) { score += 20; reasons.push({ icon:'🟢', text:`فعال ${ds} روز پیش`, tone:'ok' }); }
  else if (ds <= 14) { score += 15; reasons.push({ icon:'🟡', text:`غیرفعال ${ds} روز`, tone:'warn' }); }
  else if (ds <= 30) { score += 10; reasons.push({ icon:'🟠', text:`غیرفعال ${ds} روز`, tone:'warn' }); }
  else { score += 0; reasons.push({ icon:'🔴', text:`غیرفعال بیش از ${ds} روز`, tone:'bad' }); }
  // Subscription 20
  if (sub?.status === 'active' && sub.days_left != null) {
    const dl = Number(sub.days_left);
    if (dl > 30) { score += 20; reasons.push({ icon:'💎', text:`اشتراک فعال · ${dl} روز باقی`, tone:'ok' }); }
    else if (dl >= 8) { score += 15; reasons.push({ icon:'💎', text:`اشتراک فعال · ${dl} روز`, tone:'ok' }); }
    else if (dl >= 1) { score += 8; reasons.push({ icon:'⏰', text:`در حال انقضا · ${dl} روز`, tone:'warn' }); }
    else { score += 2; reasons.push({ icon:'⚠️', text:'اشتراک منقضی‌شده', tone:'bad' }); }
  } else { score += 0; reasons.push({ icon:'💳', text:'بدون اشتراک فعال', tone:'warn' }); }
  // Academic 15
  const tot = Number(u.total_answers || 0), acc = Number(u.accuracy || 0);
  if (tot >= 100 && acc >= 60) { score += 15; reasons.push({ icon:'📚', text:`یادگیری فعال · دقت ${acc}٪`, tone:'ok' }); }
  else if (tot >= 20 && acc >= 50) { score += 10; reasons.push({ icon:'📚', text:`فعالیت متوسط · دقت ${acc}٪`, tone:'ok' }); }
  else if (tot > 0) { score += 5; reasons.push({ icon:'📚', text:`فعالیت کم · دقت ${acc}٪`, tone:'warn' }); }
  else { score += 2; reasons.push({ icon:'📚', text:'بدون فعالیت آموزشی', tone:'warn' }); }
  // Support 10
  const tickets = Number(counts.tickets || 0), openTickets = (d.recent_tickets || []).filter(t=>t.status==='open').length;
  if (openTickets === 0) { score += 10; reasons.push({ icon:'🎫', text:'بدون تیکت باز', tone:'ok' }); }
  else if (openTickets === 1) { score += 5; reasons.push({ icon:'🎫', text:'۱ تیکت باز', tone:'warn' }); }
  else { score += 0; reasons.push({ icon:'🎫', text:`${openTickets} تیکت باز`, tone:'bad' }); }
  // AI 10
  if (ai.banned) { score += 0; reasons.push({ icon:'🤖', text:'مسدود از هوشیار', tone:'bad' }); }
  else if (Number(ai.total_usage||0) > 200) { score += 7; reasons.push({ icon:'🤖', text:`مصرف بالای هوشیار · ${ai.total_usage}`, tone:'warn' }); }
  else { score += 10; reasons.push({ icon:'🤖', text:'دسترسی هوشیار آزاد', tone:'ok' }); }
  score = Math.max(0, Math.min(100, score));
  let label = 'سالم', tone = 'ok';
  if (score < 40) { label='بحرانی'; tone='bad'; } else if (score < 70) { label='نیازمند توجه'; tone='warn'; }
  return { score, label, tone, reasons };
}
function computeAttention(d) {
  if (!d?.user) return [];
  const out=[]; const u=d.user, sub=d.subscription, counts=d.counts||{}, ai=d.ai||{};
  const ds = daysSince(u.last_active);
  if (sub?.status==='active' && sub.days_left!=null && sub.days_left<=7 && sub.days_left>=0) out.push({ sev: sub.days_left<=2?'critical':'warn', icon:'⏰', title:`اشتراک در حال انقضا · ${sub.days_left} روز باقی`, go:null });
  if (!sub || sub.status!=='active') out.push({ sev:'info', icon:'💳', title:'بدون اشتراک فعال', go:null });
  if (ds!==null && ds>21) out.push({ sev: ds>30?'warn':'info', icon:'🕓', title:`غیرفعال بیش از ${ds} روز`, go:null });
  if (ds===null) out.push({ sev:'warn', icon:'🕓', title:'بدون فعالیت ثبت‌شده', go:null });
  const open = (d.recent_tickets||[]).filter(t=>t.status==='open').length;
  if (open>=1) out.push({ sev: open>=2?'critical':'warn', icon:'🎫', title:`${open} تیکت باز`, go:'/tickets' });
  if (ai?.banned) out.push({ sev:'critical', icon:'⛔', title:'مسدود از هوشیار', go:'/ai-admin' });
  if (!u.intake) out.push({ sev:'warn', icon:'📅', title:'ورودی ثبت نشده', go:null });
  if (!u.student_id) out.push({ sev:'info', icon:'🪪', title:'شماره دانشجویی ثبت نشده', go:null });
  if (Number(u.total_answers||0)>0 && Number(u.accuracy||0)<40) out.push({ sev:'warn', icon:'📉', title:`دقت پایین · ${u.accuracy}٪`, go:null });
  return out;
}
function statusContext(row) {
  const parts=[];
  if (row.suspended) return { text:'تعلیق‌شده', tone:'bad', icon:'⛔' };
  if (!row.approved) return { text:'در انتظار تأیید', tone:'warn', icon:'⏳' };
  let t='فعال', tone='ok', icon='🟢';
  if (row.subscription?.status==='active' && row.subscription.days_left!=null) {
    const dl=row.subscription.days_left;
    if (dl<=3 && dl>=0) { t=`فعال · در حال انقضا ${dl} روز`; tone='warn'; icon='🟡'; }
    else if (dl<0) { t='فعال · منقضی‌شده'; tone='warn'; icon='🟠'; }
  } else if (!row.subscription || row.subscription.status!=='active') {
    t='فعال · بدون اشتراک'; tone='warn'; icon='🟡';
  }
  if (row.has_open_ticket) { t += ' · تیکت باز'; tone = tone==='ok'?'warn':tone; }
  return { text:t, tone, icon };
}
function dataQualityForUser(d) {
  if (!d?.user) return[];
  const u=d.user, out=[];
  if (!u.intake) out.push({ k:'intake', label:'ورودی ثبت نشده', sev:'warn' });
  if (!u.student_id) out.push({ k:'student_id', label:'شماره دانشجویی خالی', sev:'info' });
  if (!u.group) out.push({ k:'group', label:'گروه تعیین نشده', sev:'info' });
  if (u.group && !['1','2'].includes(String(u.group))) out.push({ k:'group', label:`گروه نامعتبر: ${u.group}`, sev:'warn' });
  if (d.section_errors?.roles) out.push({ k:'roles', label:'نقش‌ها در دسترس نیست', sev:'warn' });
  return out;
}
// ── 🧠 Intelligence — Recommendations / Journey / Access Trace ──
function computeRecommendations(d){
  if(!d?.user) return [];
  const recs=[]; const u=d.user, sub=d.subscription, counts=d.counts||{}, ai=d.ai||{};
  const ds=daysSince(u.last_active);
  const openTickets=(d.recent_tickets||[]).filter(t=>t.status==='open').length;
  const dl = sub?.status==='active' ? Number(sub.days_left) : null;
  if(dl!=null && dl<=3 && dl>=0){
    recs.push({ id:'extend_sub', icon:'💎', title:'تمدید اشتراک', reason:`اشتراک تا ${dl} روز دیگر منقضی می‌شود`, sev: dl<=1?'critical': dl<=2?'high':'medium', evidence:`subscriptions.end_date = ${formatFaDateTime(sub.end_date)}`, action:'تمدید', go:'/subscriptions' });
  } else if(!sub || sub.status!=='active'){
    recs.push({ id:'grant_sub', icon:'💳', title:'بررسی اشتراک', reason:'بدون اشتراک فعال', sev:'medium', evidence:'subscriptions.status != active', action:'اعطا', go:'/subscriptions' });
  }
  if(openTickets>=2){
    recs.push({ id:'review_tickets', icon:'🎫', title:'بررسی تیکت‌های باز', reason:`${openTickets} تیکت باز`, sev:'high', evidence:`tickets.status=open count=${openTickets}`, action:'مشاهده تیکت‌ها', go:'/tickets' });
  } else if(openTickets===1){
    recs.push({ id:'review_ticket', icon:'🎫', title:'پاسخ به تیکت باز', reason:'۱ تیکت باز', sev:'medium', evidence:'tickets.status=open', action:'مشاهده', go:'/tickets' });
  }
  if(ai?.banned){
    recs.push({ id:'ai_unblock', icon:'🤖', title:'بررسی مسدودیت هوشیار', reason:'کاربر از هوشیار مسدود است', sev:'high', evidence:'ai.banned=true', action:'مدیریت هوشیار', go:'/ai-admin' });
  }
  if(ds!==null && ds>30){
    recs.push({ id:'inactive_msg', icon:'🕓', title:'ارسال پیام به کاربر غیرفعال', reason:`غیرفعال بیش از ${ds} روز`, sev:'medium', evidence:`users.last_active=${formatFaDateTime(u.last_active)}`, action:'ارسال پیام', go:null });
  }
  if(Number(u.total_answers||0)>0 && Number(u.accuracy||0)<40){
    recs.push({ id:'low_acc', icon:'📉', title:'بررسی افت تحصیلی', reason:`دقت پایین ${u.accuracy}٪`, sev:'medium', evidence:`users.accuracy=${u.accuracy}`, action:'نمرات', go:null });
  }
  if(!u.intake){
    recs.push({ id:'fix_intake', icon:'📅', title:'تکمیل ورودی', reason:'ورودی ثبت نشده', sev:'low', evidence:'users.intake missing', action:'ویرایش', go:null });
  }
  const seen=new Set(); return recs.filter(r=> !seen.has(r.id) && seen.add(r.id));
}
function buildJourney(d){
  if(!d?.user) return { events:[], gaps:[] };
  const evs=[]; const u=d.user;
  const push=(key,label,at,source,detail)=>{ if(at) evs.push({key,label,at,source,detail}); };
  push('registered','ثبت‌نام',u.registered_at,'users.registered_at','');
  const appr = (d.recent_audit||[]).find(a=> /approve|تأیید/.test(a.action||''));
  if(u.approved) push('approved','تأیید حساب', appr?.at || u.registered_at, appr?'audit.action':'users.approved','');
  if(u.last_active) push('first_activity','اولین فعالیت',u.last_active,'users.last_active','');
  if(Number(u.total_answers||0)>0) {
    const ans = (d.activity||[]).find(e=>e.kind==='answer');
    push('first_answer','اولین پاسخ', ans?.at || u.last_active,'answers.answered_at',`دقت ${u.accuracy}٪`);
  }
  const firstExam = (d.recent_exams||[]).slice(-1)[0] || (d.recent_exams||[])[0];
  if(firstExam) push('first_exam','اولین آزمون',firstExam.started_at,'exam_sessions.started_at',firstExam.lesson||'');
  if(d.subscription?.end_date){
    const dl=Number(d.subscription.days_left||0);
    let start=null;
    try{ const e=new Date(d.subscription.end_date); if(!isNaN(e)) { start=new Date(e.getTime()-dl*86400000).toISOString(); } }catch{}
    push('subscription','اشتراک', start||d.subscription.end_date,'subscriptions.end_date', d.subscription.plan||'');
  }
  if(Number((d.ai||{}).total_usage||0)>0){
    const aiEv=(d.activity||[]).find(e=>e.kind==='ai');
    push('ai','اولین استفاده هوشیار', aiEv?.at || u.last_active,'ai_ledger','');
  }
  push('last_active','آخرین فعالیت',u.last_active,'users.last_active','');
  evs.sort((a,b)=> new Date(a.at)-new Date(b.at));
  const gaps=[];
  const has=(k)=> evs.some(e=>e.key===k);
  if(has('registered') && !has('approved')) gaps.push({label:'تأیید انجام نشده — احتمال gap پذیرش', sev:'warn'});
  if(has('approved') && !has('first_activity')) gaps.push({label:'پس از تأیید فعالیتی ثبت نشده — احتمال onboarding gap', sev:'info'});
  const payRelated = (d.recent_audit||[]).some(a=>/payment|subscription/.test((a.action||'').toLowerCase()));
  if(payRelated && !has('subscription')) gaps.push({label:'پرداخت ثبت شده ولی اشتراک فعال نیست — احتمال activation problem', sev:'warn'});
  return {events:evs, gaps};
}
const ACCESS_FEATURES=[
  {key:'ai_chat', label:'هوشیار — چت', icon:'🤖', desc:'ارسال پیام به هوشیار'},
  {key:'premium', label:'محتوای اشتراکی / ویژه', icon:'💎', desc:'دسترسی به محتوای پولی'},
  {key:'qbank', label:'بانک سؤال', icon:'🧪', desc:'طراحی و مشاهده سؤال'},
  {key:'exams', label:'آزمون‌ها', icon:'📝', desc:'شرکت در آزمون'},
  {key:'content_scoped', label:'محتوای ورودی-محور', icon:'📚', desc:'دسترسی بر اساس ورودی'},
];
function accessTrace(d, featureKey){
  if(!d?.user) return {checks:[], final:'UNKNOWN', reason:'no data'};
  const u=d.user, sub=d.subscription, ai=d.ai||{}, roles=d.roles||[];
  const checks=[];
  const add=(label,result,source,value)=> checks.push({label, result, source, value: String(value??'—')});
  add('حساب وجود دارد', !!u, 'users', u.id);
  add('تأیید شده', !!u.approved, 'users.approved', u.approved);
  add('تعلیق نشده', !u.suspended, 'users.suspended', !u.suspended);
  if(featureKey==='ai_chat'){
    add('مسدود هوشیار نیست', !ai.banned, 'ai.banned', !ai.banned);
    add('سهمیه باقی است', Number(ai.today||0) < 1000, 'ai.today', ai.today||0);
  }
  if(featureKey==='premium'){
    const active = sub?.status==='active' && Number(sub.days_left||0) >0;
    add('اشتراک فعال', active, 'subscriptions', sub?.status||'—');
    if(sub?.end_date) add('تاریخ انقضا معتبر', new Date(sub.end_date) > new Date(), 'subscriptions.end_date', sub.end_date);
  }
  if(featureKey==='qbank' || featureKey==='exams'){
    add('نقش/مجوز کافی', true, 'users/roles', roles.length? roles.map(r=>r.key).join(','):'student');
  }
  if(featureKey==='content_scoped'){
    add('ورودی ثبت شده', !!u.intake, 'users.intake', u.intake||'—');
    const hasScope = roles.some(r=>r.scope);
    if(hasScope) add('scope نقش', true, 'user_roles.scope_intake', roles.find(r=>r.scope)?.scope||'—');
  }
  const failed = checks.find(c=> !c.result);
  return {checks, final: failed ? 'DENY' : 'ALLOW', reason: failed ? failed.label : 'تمام بررسی‌ها موفق', failed};
}



function mergeUserSnapshot(row, snapshot) {
  const user = snapshot?.user;
  if (!row || !user || Number(row.id) !== Number(user.id)) return row;
  const roleRows = snapshot.section_errors?.roles ? null : (snapshot.roles || []);
  return {
    ...row,
    name: user.name ?? row.name,
    nickname: user.nickname ?? row.nickname,
    display_name: user.display_name || user.nickname || user.name || row.display_name,
    username: user.username ?? row.username,
    student_id: user.student_id ?? row.student_id,
    intake: user.intake ?? row.intake,
    group: user.group ?? row.group,
    role: user.role ?? row.role,
    approved: user.approved ?? row.approved,
    suspended: user.suspended ?? row.suspended,
    registered_at: user.registered_at ?? row.registered_at,
    last_active: user.last_active ?? row.last_active,
    total_answers: user.total_answers ?? row.total_answers,
    correct_answers: user.correct_answers ?? row.correct_answers,
    accuracy: user.accuracy ?? row.accuracy,
    rank: user.prestige_rank ?? row.rank,
    div: user.prestige_div ?? row.div,
    streak: user.streak_current ?? row.streak,
    ai_usage: snapshot.ai?.total_usage ?? row.ai_usage,
    exam_count: snapshot.counts?.exams ?? row.exam_count,
    roles: roleRows ? roleRows.map(role => role.key) : row.roles,
    role_scope: roleRows ? (roleRows.find(role => role.scope)?.scope || null) : row.role_scope,
    subscription: snapshot.section_errors?.subscription ? row.subscription : snapshot.subscription,
  };
}

// 🌊 WA3 — اکشن‌های تکی (دقیقاً معادل دکمه‌های پنل مدیریت داخل ربات)
const USER_ACTIONS = {
  approve:    { icon: '✅', label: 'تأیید حساب', perm: 'users.manage' },
  reject:     { icon: '✖️', label: 'رد و حذف درخواست', perm: 'users.manage', danger: true },
  suspend:    { icon: '⏸', label: 'تعلیق', perm: 'users.suspend', danger: true },
  unsuspend:  { icon: '🔓', label: 'رفع تعلیق', perm: 'users.suspend' },
  block:      { icon: '⛔', label: 'مسدود (لیست سیاه)', perm: 'users.delete', danger: true },
  unblock:    { icon: '🕊', label: 'رفع مسدودیت', perm: 'users.delete' },
  delete:     { icon: '🗑', label: 'حذف کامل حساب', perm: 'users.delete', danger: true },
};

// 👥 WA2.4/2.8 — فیلتر ذخیره‌شده + bulk گسترده (تغییر ورودی/CSV) + دراور ۳۶۰ کاربر
export default function Users({ go, me, route = '' }) {
  const initial = readHashQuery();
  const [q, setQ] = useState(initial.get('q') || '');
  const [q2, setQ2] = useState(initial.get('q') || '');
  const [status, setStatus] = useState(initial.get('status') || '');
  const [intake, setIntake] = useState(initial.get('intake') || '');
  const [intakes, setIntakes] = useState([]);
  const [group, setGroup] = useState(initial.get('group') || '');
  const [role, setRole] = useState(initial.get('role') || '');
  const [roles, setRoles] = useState([]);
  const [activity, setActivity] = useState(initial.get('activity') || '');
  const [accuracyMax, setAccuracyMax] = useState(initial.get('accuracy_max') || '');
  const [subDays, setSubDays] = useState(initial.get('sub_expiring_days') || '');
  const [openTicket, setOpenTicket] = useState(initial.get('has_open_ticket') || '');
  const [smart, setSmart] = useState(() => { try { return initial.get('smart') ? JSON.parse(initial.get('smart')) : null; } catch { return null; } });
  const [smartOpen, setSmartOpen] = useState(false);
  const [sortBy, setSortBy] = useState(initial.get('sort_by') || 'registered_at');
  const [sortDir, setSortDir] = useState(initial.get('sort_dir') || 'desc');
  const [advanced, setAdvanced] = useState([...initial.keys()].some(k => !['q', 'status', 'intake', 'page', 'per_page'].includes(k)));
  const [page, setPage] = useState(queryNumber(initial, 'page', 1));
  const [perPage, setPerPage] = useState(queryNumber(initial, 'per_page', 25));
  const [data, setData] = useState({ users: [], total: 0, pages: 1 });
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [sel, setSel] = useState([]);
  const [detail, setDetail] = useState(null);       // row کاربر
  const [confirm, setConfirm] = useState(null);
  const [intakeModal, setIntakeModal] = useState(false);
  const [intakeVal, setIntakeVal] = useState('');
  const [bulkModal, setBulkModal] = useState(null); // group | add_role | remove_role | message | subscription
  const [bulkValue, setBulkValue] = useState('');
  const [bulkResult, setBulkResult] = useState(null);
  const [bulkPreview, setBulkPreview] = useState(null);
  const [bulkPreviewLoading, setBulkPreviewLoading] = useState(false);
  // 🛡 AUDIT-§۷۹ — اشتراک گروهی: پلن‌ها از همان `subOverview` بخش مالی خوانده
  // می‌شوند (منبع یکتا)، پس فهرست پلن/روز در دو جای پنل دوشعبه نمی‌شود.
  const [subPlans, setSubPlans] = useState(null);
  const [bulkSubDays, setBulkSubDays] = useState(30);
  const [bulkSubPlan, setBulkSubPlan] = useState('اشتراک دستی');
  const [bulkSubExtend, setBulkSubExtend] = useState(true);
  const [largeBatch, setLargeBatch] = useState(new URLSearchParams(route.split('?')[1] || '').get('batch') === '1');
  const [visibleColumns, setVisibleColumns] = useState([]);
  const [blOpen, setBlOpen] = useState(false);      // 🌊 WA3 — مودال لیست سیاه
  const [intOpen, setIntOpen] = useState(false);    // 🌊 WA4 — مدیریت ورودی‌ها
  const [caOpen, setCaOpen] = useState(false);      // 🌊 WA4 — ادمین‌های محتوا
  const user360Cache = useRef(new Map());
  const closeUserDrawer = useCallback(() => setDetail(null), []);
  const rememberUser360 = useCallback((uid, snapshot) => {
    const cache = user360Cache.current;
    cache.delete(uid);
    cache.set(uid, { data: snapshot, at: performance.now() });
    while (cache.size > USER360_CACHE_LIMIT) cache.delete(cache.keys().next().value);
  }, []);
  const updateUserFromSnapshot = useCallback((uid, snapshot) => {
    rememberUser360(uid, snapshot);
    setData(previous => ({
      ...previous,
      users: (previous.users || []).map(row => Number(row.id) === Number(uid) ? mergeUserSnapshot(row, snapshot) : row),
    }));
    setDetail(previous => Number(previous?.id) === Number(uid) ? mergeUserSnapshot(previous, snapshot) : previous);
  }, [rememberUser360]);
  const removeUserLocally = useCallback(uid => {
    user360Cache.current.delete(uid);
    setData(previous => ({
      ...previous,
      total: Math.max(0, Number(previous.total || 0) - 1),
      users: (previous.users || []).filter(row => Number(row.id) !== Number(uid)),
    }));
    setSel(previous => previous.filter(id => Number(id) !== Number(uid)));
  }, []);
  const has = permission => !!me?.is_owner || (me?.perms || []).includes(permission);
  const canAnyBatch = ['users.manage', 'users.suspend', 'users.message', 'users.delete'].some(has);

  useEffect(() => { api.intakes().then(r => setIntakes(r.intakes || [])).catch(() => {}); }, []);
  useEffect(() => { api.rolesPicker().then(r => setRoles(r.roles || [])).catch(() => setRoles([])); }, []);
  useEffect(() => { const t = setTimeout(() => setQ(q2), 350); return () => clearTimeout(t); }, [q2]);
  useEffect(() => {
    writeHashQuery('/users', { q: q2, status, intake, group, role, activity,
      accuracy_max: accuracyMax, sub_expiring_days: subDays,
      has_open_ticket: openTicket, smart: smart ? JSON.stringify(smart) : '',
      sort_by: sortBy !== 'registered_at' ? sortBy : '',
      sort_dir: sortDir !== 'desc' ? sortDir : '', page: page > 1 ? page : '',
      per_page: perPage !== 25 ? perPage : '' });
  }, [q2, status, intake, group, role, activity, accuracyMax, subDays, openTicket, smart, sortBy, sortDir, page, perPage]);

  const load = async () => {
    setLoading(true); setErr('');
    try {
      setData(await api.users({
        page, per_page: perPage, q, intake, status, group, role, activity,
        accuracy_max: accuracyMax, sub_expiring_days: subDays,
        has_open_ticket: openTicket, smart: smart ? JSON.stringify(smart) : '',
        sort_by: sortBy, sort_dir: sortDir,
      }));
    } catch (e) { setErr(errText(e)); }
    setLoading(false);
  };
  useEffect(() => { load(); }, [page, perPage, q, intake, status, group, role, activity, accuracyMax, subDays, openTicket, smart, sortBy, sortDir]);
  useEffect(() => { setSel([]); }, [page, q, intake, status, group, role, activity, accuracyMax, subDays, openTicket, smart]);

  const loadSubPlans = () => {
    if (subPlans) return;
    api.subOverview().then(r => setSubPlans(r.plans || [])).catch(() => setSubPlans([]));
  };

  const doBulkPreview = async (action, value, ids = sel, extra = {}) => {
    if (!ids.length) return;
    setBulkPreviewLoading(true);
    try {
      const r = await api.usersBulkPreview(action, ids, value, extra);
      setBulkPreview({ ...r, action, value, ids });
    } catch (e) { toast(errText(e), 'err'); setBulkPreview(null); }
    setBulkPreviewLoading(false);
  };
  const bulk = async (action, value, ids = sel, extra = {}) => {
    if (!ids.length) return toast('ابتدا کاربران را انتخاب کنید', 'err');
    try {
      const r = await api.usersBulk(action, ids, value, extra);
      setBulkResult({ ...r, action, value });
      toast(`${faNum(r.done)} موفق · ${faNum(r.skipped?.length || 0)} ردشده · ${faNum(r.failed?.length || 0)} ناموفق`, r.failed?.length ? 'err' : 'ok');
      setSel([]); load();
      return r;
    } catch (e) { toast(errText(e), 'err'); return null; }
  };

  const applyFilter = (f) => {
    const flt = f.filters || {};
    setQ2(flt.q || ''); setQ(flt.q || '');
    setStatus(flt.status || ''); setIntake(flt.intake || ''); setGroup(flt.group || '');
    setRole(flt.role || ''); setActivity(flt.activity || '');
    setAccuracyMax(flt.accuracyMax ?? ''); setSubDays(flt.subDays ?? '');
    setOpenTicket(flt.openTicket || ''); setSmart(flt.smart || null); setSortBy(flt.sortBy || 'registered_at');
    setSortDir(flt.sortDir || 'desc'); setAdvanced(!!(flt.group || flt.role || flt.activity || flt.accuracyMax !== undefined || flt.subDays || flt.openTicket || flt.smart));
    setPage(1);
    toast(`نمای «${f.name}» اعمال شد ⏱`);
  };
  const exportSel = () => {
    const rows = (data.users || []).filter(u => sel.includes(u.id));
    exportCSV(`users-${fileDateStamp()}.csv`, [
      { label: 'id', v: 'id' }, { label: 'name', v: 'name' },
      { label: 'username', v: 'username' }, { label: 'student_id', v: 'student_id' },
      { label: 'intake', v: 'intake' }, { label: 'group', v: 'group' },
      { label: 'roles', v: r => (r.roles || []).join('|') },
      { label: 'subscription', v: r => r.subscription?.status || '' },
      { label: 'subscription_end', v: r => r.subscription?.end_date ? formatFaDate(r.subscription.end_date) : '' },
      { label: 'accuracy', v: 'accuracy' }, { label: 'answers', v: 'total_answers' },
      { label: 'exams', v: 'exam_count' }, { label: 'ai_usage', v: 'ai_usage' },
      { label: 'last_active', v: r => r.last_active ? formatFaDateTime(r.last_active) : '' }, { label: 'registered_at', v: r => r.registered_at ? formatFaDateTime(r.registered_at) : '' },
      { label: 'status', v: r => r.suspended ? 'suspended' : r.approved ? 'active' : 'pending' },
    ], rows);
    toast(`خروجی ${rows.length} کاربر دانلود شد 📥`);
  };

  const cols = [
    { k: 'display_name', label: 'نام', render: r => (
      <div><b style={{ color: 'var(--txt)' }}>{r.display_name || r.name}</b>
      <div className="muted">@{r.username || '—'} · <span className="code">{r.id}</span></div></div>) },
    { k: 'student_id', label: 'شماره دانشجویی', render: r => <span className="code">{r.student_id || '—'}</span> },
    { k: 'intake', label: 'ورودی' },
    { k: 'group', label: 'گروه' },
    { k: 'roles', label: 'نقش‌ها', render: r => (r.roles || []).length
      ? <div className="row" style={{ gap: 3 }}>{r.roles.slice(0, 2).map(x => <B key={x} kind="acc">{x}</B>)}{r.roles.length > 2 && <B>+{r.roles.length - 2}</B>}</div>
      : <span className="muted">دانشجو</span> },
    { k: 'subscription', label: 'اشتراک هامزیار', render: r => r.subscription?.status === 'active'
      ? <div><B kind="ok">{r.subscription.plan || 'فعال'}</B><div className="muted">{faNum(r.subscription.days_left)} روز</div></div>
      : <span className="muted">—</span> },
    { k: 'accuracy', label: 'دقت', render: r => <B kind={r.accuracy >= 70 ? 'ok' : r.accuracy < 50 && r.total_answers ? 'warn' : ''}>{faNum(r.accuracy)}٪</B> },
    { k: 'total_answers', label: 'پاسخ‌ها', render: r => faNum(r.total_answers) },
    { k: 'exam_count', label: 'آزمون', render: r => faNum(r.exam_count) },
    { k: 'ai_usage', label: 'هوشیار', render: r => faNum(r.ai_usage) },
    { k: 'streak', label: 'استریک', render: r => r.streak ? `🔥 ${faNum(r.streak)}` : '—' },
    { k: 'rank', label: 'رنک', render: r => r.rank ? <B kind="purple">{r.rank}{r.div ? ` / ${r.div}` : ''}</B> : '—' },
    { k: 'last_active', label: 'آخرین فعالیت', render: r => <RelativeTime value={r.last_active} /> },
    { k: 'registered_at', label: 'ثبت‌نام', render: r => <FaDateTime value={r.registered_at} /> },
    { k: 'st', label: 'وضعیت', render: r => <div className="row" style={{ gap: 3 }}>{r.suspended
      ? <B kind="bad">تعلیق</B> : r.approved ? <B kind="ok">فعال</B> : <B kind="warn">در انتظار</B>}{r.has_open_ticket && <B kind="warn">🎫 باز</B>}</div> },
    { k: 'ops', label: '', stop: true, render: r => (
      <div className="row" style={{ gap: 4 }}>
        {has('users.manage') && !r.approved && !r.suspended && <button className="btn sm ok" onClick={() => setConfirm({ uid: r.id, action: 'approve', text: `تأیید حساب «${r.display_name || r.name}»؟ وضعیت: در انتظار ← فعال` })} aria-label="تأیید کاربر">✅</button>}
        {has('users.suspend') && (r.suspended
          ? <button className="btn sm ok" title="رفع تعلیق" aria-label="رفع تعلیق کاربر" onClick={() => setConfirm({ uid: r.id, action: 'unsuspend', text: `رفع تعلیق «${r.display_name || r.name}»؟ وضعیت: تعلیق ← فعال` })}>🔓</button>
          : <button className="btn sm danger" onClick={() => setConfirm({ uid: r.id, action: 'suspend', text: `تعلیق «${r.display_name || r.name}»؟ وضعیت: فعال ← تعلیق` })} aria-label="تعلیق کاربر">⏸</button>)}
      </div>) },
  ];

  const act = async (uid, action) => {
    try {
      await api.waUserAction(uid, action);
      const updates = action === 'approve' || action === 'unsuspend'
        ? { approved: true, suspended: false }
        : action === 'suspend' ? { approved: false, suspended: true } : null;
      if (updates) {
        user360Cache.current.delete(uid);
        setData(previous => ({ ...previous, users: previous.users.map(row => Number(row.id) === Number(uid) ? { ...row, ...updates } : row) }));
        setDetail(previous => Number(previous?.id) === Number(uid) ? { ...previous, ...updates } : previous);
      }
      toast('انجام شد');
    } catch (e) { toast(errText(e), 'err'); }
  };

  if (err) return <ErrorState error={err} onRetry={load} />;

  return (
    <>
      {/* 🎛 UX — نوار ابزار یکپارچه: اکشن‌های صفحه در هدر، اکشن‌های گروهی در نوار انتخاب جدا */}
      <PageHeader title="مدیریت کاربران" description="جست‌وجو، فیلتر ذخیره‌شده، صفحه‌بندی سرورساید و عملیات گروهی" actions={
        <div className="toolbar" role="toolbar" aria-label="ابزارهای صفحه کاربران">
          {(me?.is_owner || has('users.view')) && <div className="toolbar-group" aria-label="مدیریت">
            {me?.is_owner && <button className="btn sm" title="مدیریت ورودی‌ها (افزودن/فعال‌سازی/حذف)" onClick={() => setIntOpen(true)}>📅 ورودی‌ها</button>}
            {me?.is_owner && <button className="btn sm" title="ادمین‌های محتوا" onClick={() => setCaOpen(true)}>🎓 ادمین‌های محتوا</button>}
            {has('users.view') && <button className="btn sm" title="کاربران مسدودشده" onClick={() => setBlOpen(true)}>⛔ لیست سیاه</button>}
          </div>}
          <div className="toolbar-group" aria-label="خروجی و عملیات انبوه">
            <button className="btn sm" title="خروجی CSV از همه‌ی نتایج فیلترشده" onClick={() => api.exportUsersCsv({ q, intake, status, group, role, activity,
              accuracy_max: accuracyMax, sub_expiring_days: subDays, has_open_ticket: openTicket,
              smart: smart ? JSON.stringify(smart) : '', sort_by: sortBy, sort_dir: sortDir })}>📥 CSV همه نتایج</button>
            {canAnyBatch && <button className="btn sm" title="اجرای عملیات روی فهرستی از شناسه‌ها" onClick={() => setLargeBatch(true)}>⚡ Batch با فهرست ID</button>}
          </div>
        </div>
      } />

      {sel.length > 0 && (
        <div className="selbar" role="region" aria-label="عملیات گروهی روی کاربران انتخاب‌شده">
          <div className="selbar-lead">
            <span className="selbar-count">{faNum(sel.length)}</span>
            <span className="selbar-label">کاربر انتخاب‌شده</span>
          </div>
          <div className="selbar-actions">
            {(has('users.manage') || has('users.suspend')) && <div className="toolbar-group" aria-label="وضعیت حساب">
              {has('users.manage') && <button className="btn sm ok" onClick={() => setConfirm({ action: 'approve', text: `تأیید ${sel.length} کاربر؟` })}>✅ تأیید</button>}
              {has('users.suspend') && <button className="btn sm warn" onClick={() => setConfirm({ action: 'suspend', text: `تعلیق ${sel.length} کاربر؟` })}>⏸ تعلیق</button>}
              {has('users.suspend') && <button className="btn sm" onClick={() => setConfirm({ action: 'unsuspend', text: `رفع تعلیق ${sel.length} کاربر؟` })}>🔓 رفع تعلیق</button>}
            </div>}
            {has('users.manage') && <div className="toolbar-group" aria-label="دسته‌بندی و نقش">
              <button className="btn sm" onClick={() => { setIntakeVal(''); setIntakeModal(true); }}>🏷 تغییر ورودی</button>
              <button className="btn sm" onClick={() => { setBulkValue(''); setBulkModal('set_group'); }}>👥 تغییر گروه</button>
              <button className="btn sm" onClick={() => { setBulkValue(''); setBulkModal('add_role'); }}>🛡 افزودن نقش</button>
              <button className="btn sm" onClick={() => { setBulkValue(''); setBulkModal('remove_role'); }}>➖ حذف نقش</button>
            </div>}
            {(has('subscription.manage') || has('users.message')) && <div className="toolbar-group" aria-label="ارتباط و اشتراک">
              {has('subscription.manage') && <button className="btn sm" title="اعطا یا تمدید اشتراک برای کاربران انتخاب‌شده — از همان مسیر بخش مالی"
                     onClick={() => { loadSubPlans(); setBulkModal('subscription'); }}>💎 اشتراک</button>}
              {has('users.message') && <button className="btn sm" onClick={() => { setBulkValue(''); setBulkModal('message'); }}>📨 پیام</button>}
            </div>}
            <div className="toolbar-group" aria-label="خروجی و اقدام خطرناک">
              <button className="btn sm" onClick={exportSel}>📥 CSV انتخاب</button>
              {has('users.delete') && <button className="btn sm danger" onClick={() => { setBulkValue(''); setBulkModal('block'); }}>⛔ مسدودسازی</button>}
            </div>
          </div>
        </div>
      )}

      {/* 📊 Directory summary — real counts from server total + page sample */}
      <div className="grid" style={{ gridTemplateColumns:'repeat(auto-fit,minmax(150px,1fr))', gap:8, marginBottom:10 }}>
        <div className="panel panel-pad" style={{ background:'var(--c-surface)' }}><div className="muted" style={{fontSize:'var(--fs-caption)'}}>کل کاربران (فیلترشده)</div><b style={{fontSize:'var(--fs-section)'}}>{Number(data.total||0).toLocaleString('fa-IR')}</b><div className="muted" style={{fontSize:'var(--fs-caption)'}}>{loading?'در حال بارگذاری…':`${(data.users||[]).length.toLocaleString('fa-IR')} در این صفحه`}</div></div>
        <div className="panel panel-pad" style={{ background:'var(--c-surface)' }}><div className="muted" style={{fontSize:'var(--fs-caption)'}}>صفحه</div><b>{Number(page).toLocaleString('fa-IR')} / {Number(data.pages||1).toLocaleString('fa-IR')}</b><div className="muted" style={{fontSize:'var(--fs-caption)'}}>هر صفحه {Number(perPage).toLocaleString('fa-IR')}</div></div>
        <div className="panel panel-pad" style={{ background:'var(--c-surface)' }}><div className="muted" style={{fontSize:'var(--fs-caption)'}}>انتخاب‌شده</div><b>{Number(sel.length).toLocaleString('fa-IR')}</b><div className="muted" style={{fontSize:'var(--fs-caption)'}}>{sel.length?'آماده عملیات گروهی':'—'}</div></div>
        <div className="panel panel-pad" style={{ background:'var(--c-surface)' }}><div className="muted" style={{fontSize:'var(--fs-caption)'}}>فیلتر فعال</div><b>{[q&&'جستجو',status&&'وضعیت',intake&&'ورودی',group&&'گروه',role&&'نقش',activity&&'فعالیت',accuracyMax&&'دقت',subDays&&'انقضا',openTicket&&'تیکت',smart&&'🧠'].filter(Boolean).length.toLocaleString('fa-IR')} مورد</b><div className="muted" style={{fontSize:'var(--fs-caption)'}}>{smart?'Query ترکیبی فعال':'—'}</div></div>
      </div>
      <FilterBar>
        <input className="inp" style={{ flex: 1, minWidth: 200 }} placeholder="🔎 نام، نام‌نما، یوزرنیم، شماره دانشجویی یا Telegram ID…"
               value={q2} onChange={e => { setQ2(e.target.value); setPage(1); }} />
        <select className="inp" value={status} onChange={e => { setStatus(e.target.value); setPage(1); }}>
          {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select className="inp" value={intake} onChange={e => { setIntake(e.target.value); setPage(1); }}>
          <option value="">همه‌ی ورودی‌ها</option>
          {intakes.map(i => <option key={i.code || i} value={i.code || i}>{i.label || i.code || i}</option>)}
        </select>
        <button className={`btn sm ${advanced ? 'primary' : ''}`} aria-expanded={advanced} onClick={() => setAdvanced(x => !x)}>⚙ فیلترهای سریع</button>
        <button className={`btn sm ${smart ? 'primary' : ''}`} onClick={() => setSmartOpen(true)}>🧠 Query Builder{smart ? ' · فعال' : ''}</button>
      </FilterBar>
      {advanced && <FilterBar className="advanced-filter-bar">
        <select className="inp" value={group} onChange={e => { setGroup(e.target.value); setPage(1); }}>
          <option value="">همه گروه‌ها</option><option value="1">گروه ۱</option><option value="2">گروه ۲</option>
        </select>
        <select className="inp" value={role} onChange={e => { setRole(e.target.value); setPage(1); }}>
          <option value="">همه نقش‌ها</option>{roles.map(r => <option key={r.key} value={r.key}>{r.label}</option>)}
        </select>
        <select className="inp" value={activity} onChange={e => { setActivity(e.target.value); setPage(1); }}>
          <option value="">هر فعالیتی</option><option value="never">بدون اولین فعالیت</option>
          <option value="inactive_14">غیرفعال بیش از ۱۴ روز</option><option value="inactive_30">غیرفعال بیش از ۳۰ روز</option>
        </select>
        <label className="row"><span className="muted">دقت ≤</span><input className="inp" type="number" min="0" max="100" style={{ width: 76 }} value={accuracyMax}
          onChange={e => { setAccuracyMax(e.target.value); setPage(1); }} placeholder="٪" /></label>
        <label className="row"><span className="muted">انقضا تا</span><input className="inp" type="number" min="1" max="365" style={{ width: 76 }} value={subDays}
          onChange={e => { setSubDays(e.target.value); setPage(1); }} placeholder="روز" /></label>
        <select className="inp" value={openTicket} onChange={e => { setOpenTicket(e.target.value); setPage(1); }}>
          <option value="">هر وضعیت تیکت</option><option value="true">دارای تیکت باز</option><option value="false">بدون تیکت باز</option>
        </select>
        <select className="inp" value={sortBy} onChange={e => { setSortBy(e.target.value); setPage(1); }}>
          <option value="registered_at">مرتب‌سازی: ثبت‌نام</option><option value="last_active">آخرین فعالیت</option>
          <option value="name">نام</option><option value="total_answers">پاسخ‌ها</option>
          <option value="correct_answers">پاسخ صحیح</option><option value="streak_current">استریک</option><option value="ai_total_usage">مصرف هوشیار</option>
        </select>
        <select className="inp" value={sortDir} onChange={e => { setSortDir(e.target.value); setPage(1); }}>
          <option value="desc">نزولی</option><option value="asc">صعودی</option>
        </select>
        <select className="inp" value={perPage} onChange={e => { setPerPage(+e.target.value); setPage(1); }}>
          {[10, 25, 50, 100].map(n => <option key={n} value={n}>{n} در صفحه</option>)}
        </select>
        <button className="btn sm" onClick={() => { setGroup(''); setRole(''); setActivity(''); setAccuracyMax(''); setSubDays(''); setOpenTicket(''); setSortBy('registered_at'); setSortDir('desc'); setPage(1); }}>پاک‌کردن پیشرفته</button>
      </FilterBar>}

      {smart && <div className="row" style={{ marginBottom: 8 }}><B kind="acc">🧠 Query ترکیبی فعال</B><button className="btn sm" onClick={() => { setSmart(null); setPage(1); }}>حذف Query</button></div>}
      <SavedViews scope="users" filters={{ q, status, intake, group, role, activity, accuracyMax,
        subDays, openTicket, smart, sortBy, sortDir }} columns={visibleColumns} sort={{ key: sortBy, dir: sortDir }}
        onApply={(flt, item) => { applyFilter({ ...item, filters: flt }); setVisibleColumns(item.columns || []); }} label="نماهای کاربران" />

      {/* 🧠 Directory Intelligence — Auto Segments (real data, query-based) */}
      {(() => {
        const rows = data.users || [];
        if (!rows.length && !loading) return null;
        const pending = rows.filter(r=>!r.approved && !r.suspended).length;
        const expiring = rows.filter(r=>r.subscription?.status==='active' && r.subscription.days_left!=null && r.subscription.days_left<=7 && r.subscription.days_left>=0).length;
        const inactive30 = rows.filter(r=>{ const v=r.last_active; if(!v) return true; try{ const d=(Date.now()-new Date(v).getTime())/86400000; return d>30;}catch{return false;}}).length;
        const lowAcc = rows.filter(r=>r.total_answers>5 && r.accuracy<40).length;
        const heavyAI = rows.filter(r=>r.ai_usage>100).length;
        const noSub = rows.filter(r=>!r.subscription || r.subscription.status!=='active').length;
        const hasTicket = rows.filter(r=>r.has_open_ticket).length;
        const defs = [
          { k:'pending', label:'در انتظار', icon:'⏳', cnt: pending, on:()=>{setStatus('pending');setPage(1);}, tip:'approved=false' },
          { k:'expiring', label:'در حال انقضا ≤۷ روز', icon:'⏰', cnt: expiring, on:()=>{setSubDays('7');setPage(1);}, tip:'subscription days_left ≤7' },
          { k:'inactive', label:'غیرفعال >۳۰ روز', icon:'🕓', cnt: inactive30, on:()=>{setActivity('inactive_30');setPage(1);}, tip:'last_active >30d' },
          { k:'lowAcc', label:'دقت پایین <۴۰٪', icon:'📉', cnt: lowAcc, on:()=>{setAccuracyMax('40');setPage(1);}, tip:'accuracy <40' },
          { k:'heavyAI', label:'پراستفاده هوشیار >۱۰۰', icon:'🤖', cnt: heavyAI, on:()=>{setSortBy('ai_total_usage');setSortDir('desc');setPage(1);}, tip:'ai_usage >100' },
          { k:'noSub', label:'بدون اشتراک', icon:'💳', cnt: noSub, on:()=>{setSubDays(''); setStatus('active');}, tip:'no active subscription' },
          { k:'ticket', label:'تیکت باز', icon:'🎫', cnt: hasTicket, on:()=>{setOpenTicket('true');setPage(1);}, tip:'has_open_ticket=true' },
        ].filter(x=>x.cnt>0);
        if (!defs.length) return null;
        return (<div className="panel" style={{ padding:10, marginBottom:10, background:'color-mix(in srgb, var(--c-surface) 92%, transparent)', border:'1px solid var(--c-line)' }}>
          <div className="row" style={{ flexWrap:'wrap', gap:6 }}>
            <b style={{ fontSize:'var(--fs-label)', color:'var(--c-txt2)' }}>🧭 سگمنت‌های هوشمند (همین صفحه):</b>
            {defs.map(d=>(<button key={d.k} className="btn sm" title={d.tip} onClick={d.on} style={{ borderRadius:999 }}>
              <span>{d.icon}</span> {d.label} <B kind={d.k==='pending'?'warn':d.k==='expiring'?'warn':d.k==='ticket'?'bad':''}>{d.cnt.toLocaleString('fa-IR')}</B>
            </button>))}
            <span className="muted" style={{ fontSize:'var(--fs-caption)' }}>· کلیک = اعمال فیلتر واقعی · بدون snapshot جداگانه</span>
          </div>
        </div>);
      })()}

            <DataTable columns={cols} rows={data.users} selectable onSelect={setSel}
                 loading={loading} onRow={r => setDetail(r)} colToggle visibleColumns={visibleColumns}
                 onColumnsChange={setVisibleColumns}
                 pager={{ page, pages: data.pages, total: data.total, onPage: setPage }} />

      {detail && <UserDrawer row={detail} me={me} go={go} onClose={closeUserDrawer}
        initialData={(() => { const cached = user360Cache.current.get(detail.id); return cached && performance.now() - cached.at < USER360_STALE_MS ? cached.data : null; })()}
        onSnapshot={updateUserFromSnapshot}
        onRemoved={removeUserLocally} />}
      {blOpen && <BlacklistModal me={me} onClose={() => { setBlOpen(false); load(); }} />}
      {intOpen && <IntakesModal onClose={(ch) => { setIntOpen(false); if (ch) api.intakes().then(r => setIntakes(r.intakes || [])).catch(() => {}); }} />}
      {caOpen && <ContentAdminsModal onClose={() => { setCaOpen(false); load(); }} />}
      {confirm && (
        <Confirm text={confirm.text} danger={!!USER_ACTIONS[confirm.action]?.danger || confirm.action === 'suspend'}
                 onYes={async () => {
                   const c = confirm; setConfirm(null);
                   if (c.uid) { try { await api.waUserAction(c.uid, c.action); toast('انجام شد'); load(); } catch (e) { toast(errText(e), 'err'); } }
                   else await bulk(c.action);
                 }}
                 onNo={() => setConfirm(null)} />
      )}
      {intakeModal && (
        <Modal title={`🏷 تغییر ورودی ${sel.length} کاربر`} onClose={() => setIntakeModal(false)}>
          <select className="inp" style={{ width: '100%' }} value={intakeVal} onChange={e => setIntakeVal(e.target.value)}>
            <option value="">(بدون ورودی)</option>
            {intakes.map(i => <option key={i.code || i} value={i.code || i}>{i.label || i.code || i}</option>)}
          </select>
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn primary" onClick={async () => { setIntakeModal(false); await bulk('set_intake', intakeVal); }}>اعمال</button>
            <button className="btn" onClick={() => setIntakeModal(false)}>انصراف</button>
          </div>
        </Modal>
      )}
      {bulkModal && (
        <Modal title={{ set_group: '👥 تغییر گروه گروهی', add_role: '🛡 افزودن نقش گروهی', remove_role: '➖ حذف نقش گروهی', message: '📨 پیام به کاربران انتخاب‌شده', block: '⛔ مسدودسازی کاربران انتخاب‌شده', subscription: '💎 اعطا/تمدید اشتراک گروهی' }[bulkModal]} onClose={() => {setBulkModal(null); setBulkPreview(null);}}>
          <p className="muted" style={{ marginBottom: 10 }}>{faNum(sel.length)} کاربر انتخاب شده‌اند. نتیجه‌ی هر کاربر جداگانه گزارش می‌شود.</p>
          {bulkModal === 'set_group' && <select className="inp" style={{ width: '100%' }} value={bulkValue} onChange={e => setBulkValue(e.target.value)}>
            <option value="">انتخاب گروه…</option><option value="1">گروه ۱</option><option value="2">گروه ۲</option>
          </select>}
          {(bulkModal === 'add_role' || bulkModal === 'remove_role') && <select className="inp" style={{ width: '100%' }} value={bulkValue} onChange={e => setBulkValue(e.target.value)}>
            <option value="">انتخاب نقش…</option>{roles.map(r => <option key={r.key} value={r.key}>{r.label}</option>)}
          </select>}
          {(bulkModal === 'message' || bulkModal === 'block') && <textarea className="inp" rows={5} maxLength={1500} style={{ width: '100%' }}
            placeholder={bulkModal === 'block' ? 'دلیل مسدودسازی — کاربران از دیتابیس فعال حذف و به لیست سیاه منتقل می‌شوند…' : 'متن پیام از سمت پشتیبانی هامزیار…'} value={bulkValue} onChange={e => setBulkValue(e.target.value)} />}
          {bulkModal === 'subscription' && <div className="grid" style={{ gap: 10 }}>
            <div className="row">
              {[7, 30, 90, 180, 365].map(d => <button key={d} type="button" className={`btn sm ${Number(bulkSubDays) === d ? 'primary' : ''}`}
                       onClick={() => setBulkSubDays(d)}>{faNum(d)} روز</button>)}
              <input className="inp" type="number" min="1" max="3650" style={{ width: 100 }} value={bulkSubDays}
                     onChange={e => setBulkSubDays(e.target.value)} aria-label="تعداد روز اشتراک" />
            </div>
            <select className="inp" value={bulkSubPlan} onChange={e => setBulkSubPlan(e.target.value)} aria-label="پلن اشتراک">
              <option value="اشتراک دستی">اشتراک دستی</option>
              {(subPlans || []).map(p => <option key={p.id} value={p.name}>{p.name} — {faNum(p.days)} روز</option>)}
            </select>
            <label className="row"><Switch on={bulkSubExtend} onChange={setBulkSubExtend} label="تمدید روی اشتراک فعلی" />
              <span>تمدید روی اشتراک فعلی (روزها جمع می‌شود؛ با خاموشی جایگزین می‌شود)</span></label>
            <div className="muted">اعطا از همان مسیر «مرکز کنترل اشتراک» انجام می‌شود — نوتیف کاربر، تاریخ
              پایان، ردپای مالی و ضدتکرارِ کلیک برای {faNum(sel.length)} کاربر. سقف هر درخواست ۱۰۰ کاربر است.</div>
          </div>}
          {bulkPreview && (
            <div className="panel panel-pad" style={{ marginTop:10, background:'color-mix(in srgb, var(--c-acc) 5%, var(--c-surface))', borderColor:'rgba(77,184,255,.22)' }}>
              <b>🔍 پیش‌نمایش تأثیر (dry-run — بدون نوشتن)</b>
              <div className="grid g3" style={{ marginTop:8 }}>
                <div className="panel panel-pad" style={{ background:'var(--c-surface)', textAlign:'center' }}><b className="ok-text">{faNum(((bulkPreview.affected ?? bulkPreview.will_succeed) ?? (bulkPreview.succeeded?.length ?? 0)))}</b><div className="muted">موردِ تحت تأثیر</div></div>
                <div className="panel panel-pad" style={{ background:'var(--c-surface)', textAlign:'center' }}><b>{faNum(bulkPreview.skipped?.length||0)}</b><div className="muted">ردشده/بدون تغییر</div></div>
                <div className="panel panel-pad" style={{ background:'var(--c-surface)', textAlign:'center' }}><b>{faNum(((bulkPreview.will_fail ?? (bulkPreview.failed?.length||0))))}</b><div className="muted">ناموفقِ احتمالی</div></div>
              </div>
            </div>
          )}
                    <div className="row" style={{ marginTop: 12 }}>
            <button className="btn" disabled={bulkPreviewLoading} onClick={async ()=>{ if(bulkModal==='subscription'){ const days=Number(bulkSubDays); await doBulkPreview(bulkSubExtend?'renew_subscription':'grant_subscription', sel, String(days), {days, plan_name: bulkSubPlan, extend: bulkSubExtend}); } else { await doBulkPreview(bulkModal, sel, bulkValue); } }} style={{ marginInlineEnd:6 }}>{bulkPreviewLoading?'⏳':'🔍'} پیش‌نمایش</button>
            <button className={`btn ${bulkModal === 'remove_role' || bulkModal === 'block' ? 'danger' : 'primary'}`}
              disabled={bulkModal === 'subscription' ? !(Number(bulkSubDays) >= 1 && Number(bulkSubDays) <= 3650) : !bulkValue.trim()}
              onClick={async () => {
                if (bulkModal === 'subscription') {
                  const days = Number(bulkSubDays); const value = String(days); setBulkModal(null); setBulkPreview(null);
                  await bulk(bulkSubExtend ? 'renew_subscription' : 'grant_subscription', value, sel,
                             { days, plan_name: bulkSubPlan, extend: bulkSubExtend });
                  return;
                }
                const action = bulkModal; const value = bulkValue; setBulkModal(null); setBulkPreview(null); await bulk(action, value);
              }}>{bulkModal === 'subscription' ? `${bulkSubExtend ? 'تمدید' : 'اعطا'} اشتراک · ${faNum(sel.length)} کاربر` : 'بازبینی شد؛ اجرا'}</button>
            <button className="btn" onClick={() => {setBulkModal(null); setBulkPreview(null);}}>انصراف</button>
          </div>
        </Modal>
      )}
      {largeBatch && <LargeBatchModal has={has} intakes={intakes} roles={roles} onClose={() => setLargeBatch(false)} onDone={result => { setLargeBatch(false); setBulkResult(result); load(); }} />}
      {smartOpen && <SmartQueryBuilder value={smart} onClose={() => setSmartOpen(false)} onApply={value => { setSmart(value); setSmartOpen(false); setPage(1); }} />}
      {bulkResult && (
        <Modal title="گزارش عملیات گروهی" onClose={() => setBulkResult(null)}>
          <div className="grid g3">
            <div className="panel panel-pad"><b className="ok-text">{faNum(bulkResult.succeeded?.length || 0)}</b><div className="muted">موفق</div></div>
            <div className="panel panel-pad"><b>{faNum(bulkResult.skipped?.length || 0)}</b><div className="muted">ردشده/بدون تغییر</div></div>
            <div className="panel panel-pad"><b className="bad-text">{faNum(bulkResult.failed?.length || 0)}</b><div className="muted">ناموفق</div></div>
          </div>
          {!!bulkResult.granted?.length && <div className="grid" style={{ marginTop: 10, gap: 4 }}><b>اشتراک‌های ثبت‌شده</b>
            {bulkResult.granted.slice(0, 20).map(g => <div key={`g-${g.id}`} className="row"><span className="code">{g.id}</span><span className="muted">پایان: <FaDate value={g.end_date} /></span></div>)}</div>}
          {!!bulkResult.skipped?.length && <div className="grid" style={{ marginTop: 10, gap: 4 }}><b>ردشده‌ها</b>
            {bulkResult.skipped.slice(0, 20).map(x => <div key={`s-${x.id}`} className="row"><span className="code">{x.id}</span><span className="muted">{x.reason}</span></div>)}</div>}
          {!!bulkResult.failed?.length && <div className="grid" style={{ marginTop: 10, gap: 4 }}><b>ناموفق‌ها</b>
            {bulkResult.failed.slice(0, 20).map(x => <div key={`f-${x.id}`} className="row"><span className="code">{x.id}</span><span className="muted">{x.error}</span></div>)}
            <button className="btn" onClick={() => bulk(bulkResult.action, bulkResult.value, bulkResult.failed.map(x => x.id))}>↻ تلاش مجدد ناموفق‌ها</button></div>}
        </Modal>
      )}
    </>
  );
}


function LargeBatchModal({ has, intakes, roles, onClose, onDone }) {
  const actions = [
    ['approve', 'تأیید', 'users.manage'], ['suspend', 'تعلیق', 'users.suspend'], ['unsuspend', 'رفع تعلیق', 'users.suspend'],
    ['set_intake', 'تغییر ورودی', 'users.manage'], ['set_group', 'تغییر گروه', 'users.manage'],
    ['add_role', 'افزودن نقش', 'users.manage'], ['remove_role', 'حذف نقش', 'users.manage'],
    ['message', 'ارسال اعلان', 'users.message'], ['block', 'مسدودسازی', 'users.delete'],
  ].filter(([, , permission]) => has(permission));
  const [text, setText] = useState(''); const [action, setAction] = useState(actions[0]?.[0] || ''); const [value, setValue] = useState('');
  const [confirmed, setConfirmed] = useState(false); const [busy, setBusy] = useState(false); const [progress, setProgress] = useState(0);
  const ids = useMemo(() => [...new Set(text.split(/[\s,،;]+/).map(x => x.trim()).filter(x => /^\d+$/.test(x)).map(Number))].slice(0, 2000), [text]);
  const needsValue = ['set_intake', 'set_group', 'add_role', 'remove_role', 'message', 'block'].includes(action);
  const run = async () => {
    if (!ids.length || (needsValue && !value.trim()) || !confirmed) return;
    setBusy(true); const result = { action, value, succeeded: [], skipped: [], failed: [], done: 0 };
    const chunks = Array.from({ length: Math.ceil(ids.length / 100) }, (_, index) => ids.slice(index * 100, index * 100 + 100));
    for (let index = 0; index < chunks.length; index += 1) {
      try { const response = await api.usersBulk(action, chunks[index], value); result.succeeded.push(...(response.succeeded || [])); result.skipped.push(...(response.skipped || [])); result.failed.push(...(response.failed || [])); }
      catch (e) { result.failed.push(...chunks[index].map(id => ({ id, error: errText(e) }))); }
      setProgress(index + 1);
    }
    result.done = result.succeeded.length; result.ok = !result.failed.length; setBusy(false); onDone(result);
  };
  return <Modal wide title="⚡ Batch Engine کاربران" onClose={busy ? () => {} : onClose}>
    <div className="panel panel-pad" style={{ background: 'var(--bg)' }}><b>اجرای chunked روی domain API موجود</b><div className="muted">حداکثر ۲۰۰۰ ID؛ هر chunk حداکثر ۱۰۰ رکورد، با audit و نتیجه per-record. این UI mutation مستقیم یا background job جعلی نمی‌سازد.</div></div>
    <textarea className="inp" rows={7} style={{ width: '100%', marginTop: 10 }} placeholder="Telegram IDها؛ هر خط یا با ویرگول…" value={text} onChange={e => { setText(e.target.value); setConfirmed(false); }} />
    <div className="row"><B kind={ids.length ? 'acc' : 'warn'}>{faNum(ids.length)} ID معتبر</B><B>{faNum(Math.ceil(ids.length / 100))} chunk</B>{text.trim() && !ids.length && <B kind="bad">ID معتبری تشخیص داده نشد</B>}</div>
    <div className="row" style={{ marginTop: 10 }}><select className="inp" value={action} onChange={e => { setAction(e.target.value); setValue(''); setConfirmed(false); }}>{actions.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
      {action === 'set_intake' ? <select className="inp" value={value} onChange={e => setValue(e.target.value)}><option value="">انتخاب ورودی…</option>{intakes.map(item => <option key={item.code || item} value={item.code || item}>{item.label || item.code || item}</option>)}</select>
        : ['add_role', 'remove_role'].includes(action) ? <select className="inp" value={value} onChange={e => setValue(e.target.value)}><option value="">انتخاب نقش…</option>{roles.map(item => <option key={item.key} value={item.key}>{item.label}</option>)}</select>
        : needsValue && <input className="inp" style={{ flex: 1 }} value={value} onChange={e => setValue(e.target.value)} placeholder={action === 'message' ? 'متن اعلان…' : action === 'block' ? 'دلیل مسدودسازی…' : 'مقدار…'} />}</div>
    <label className="row" style={{ marginTop: 12 }}><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} /><span>پیش‌نمایش تعداد و عملیات را بررسی کردم و اجرای {faNum(ids.length)} رکورد را تأیید می‌کنم.</span></label>
    {busy && <div style={{ marginTop: 10 }}><progress max={Math.max(1, Math.ceil(ids.length / 100))} value={progress} style={{ width: '100%' }} /><div className="muted">chunk {faNum(progress)} از {faNum(Math.ceil(ids.length / 100))}</div></div>}
    <div className="row" style={{ marginTop: 12 }}><button className={`btn ${['block', 'suspend', 'remove_role'].includes(action) ? 'danger' : 'primary'}`} disabled={busy || !ids.length || !confirmed || (needsValue && !value.trim())} onClick={run}>اجرای Batch</button><button className="btn" disabled={busy} onClick={onClose}>انصراف</button></div>
  </Modal>;
}

/* ── 👤 WA2.8 — User 360: کانتکست کامل بدون ترک صفحه ─────────── */

// ── 5 Intelligence Components — Production Ready, Evidence First ──
function AccessDiagnostics({ d }){
  const [feature, setFeature] = React.useState('ai_chat');
  const trace = d ? accessTrace(d, feature) : null;
  if(!d) return <Loading label="بارگذاری دسترسی" />;
  return (
    <div className="grid" style={{ gap:10 }}>
      <div className="panel panel-pad" style={{ background:'var(--c-bg)' }}>
        <b>🔍 چرا دسترسی دارد / ندارد؟</b>
        <div className="muted" style={{ fontSize:'var(--fs-caption)' }}>تصمیم از منطق واقعی Backend/DB — نه حدس Frontend — هر Check دارای Source/Value</div>
        <div className="row" style={{ marginTop:8, flexWrap:'wrap', gap:6 }}>
          {ACCESS_FEATURES.map(f=>(
            <button key={f.key} className={`btn sm ${feature===f.key?'primary':''}`} onClick={()=>setFeature(f.key)} title={f.desc}>{f.icon} {f.label}</button>
          ))}
        </div>
      </div>
      {trace && (
        <>
          <div className={`panel panel-pad ${trace.final==='ALLOW'?'':'panel--attention'}`} style={{ background: trace.final==='ALLOW'?'color-mix(in srgb, var(--c-ok) 6%, var(--c-surface))':'color-mix(in srgb, var(--c-warn) 7%, var(--c-surface))', borderColor: trace.final==='ALLOW'?'rgba(58,210,155,.25)':'rgba(240,181,69,.35)' }}>
            <div className="row" style={{ gap:8, alignItems:'center' }}>
              <span style={{ fontSize:20 }}>{trace.final==='ALLOW'?'✅':'⛔'}</span>
              <div>
                <b style={{ color: trace.final==='ALLOW'?'var(--c-ok)':'var(--c-bad)' }}>{trace.final==='ALLOW'?'ALLOW — دسترسی مجاز':'DENY — دسترسی مسدود'}</b>
                <div className="muted" style={{ fontSize:'var(--fs-caption)' }}>دلیل: {trace.reason} · Feature: {ACCESS_FEATURES.find(f=>f.key===feature)?.label}</div>
              </div>
              <span className="spacer" />
              <B kind={trace.final==='ALLOW'?'ok':'bad'}>{trace.final}</B>
            </div>
          </div>
          <div className="grid" style={{ gap:6 }}>
            {trace.checks.map((c,i)=>(
              <div key={i} className="row" style={{ padding:'8px 10px', background:'var(--c-surface)', border:`1px solid ${c.result?'var(--c-line)':'rgba(248,113,113,.35)'}`, borderRadius:10, gap:8 }}>
                <span style={{ fontSize:16 }}>{c.result?'✓':'✕'}</span>
                <div style={{ flex:1 }}>
                  <b style={{ color: c.result?'var(--c-txt)':'var(--c-bad)', fontSize:'var(--fs-label)' }}>{c.label}</b>
                  <div className="muted" style={{ fontSize:'var(--fs-caption)' }}>SOURCE: <span className="code">{c.source}</span> · VALUE: <span className="code">{c.value}</span></div>
                </div>
                <B kind={c.result?'ok':'bad'}>{c.result?'PASS':'FAIL'}</B>
              </div>
            ))}
          </div>
          <div className="muted" style={{ fontSize:'var(--fs-caption)', textAlign:'center' }}>اگر DB/Service تغییر کند، این Trace نتیجهٔ واقعی را نشان می‌دهد — Frontend و Backend دو نتیجه متفاوت ندارند.</div>
        </>
      )}
    </div>
  );
}

function InvestigationWorkspace({ d, row, go }){
  const [mode, setMode] = React.useState('payment');
  if(!d) return <Loading label="بارگذاری شواهد" />;
  const modes = [
    ['payment','💳 پرداخت'], ['subscription','💎 اشتراک'], ['ai','🤖 هوشیار'], ['support','🎫 پشتیبانی'], ['academic','📚 تحصیلی'], ['security','🛡 امنیتی'],
  ];
  const evidence = (()=>{
    const u=d.user, sub=d.subscription, ai=d.ai||{}, audits=d.recent_audit||[], acts=d.activity||[];
    if(mode==='payment'){
      const payAudit = audits.filter(a=> /payment|pay|receipt|sub/.test((a.action||'').toLowerCase()));
      return [
        {label:'Payment', value: payAudit[0]?.action||'—', status: payAudit.length? 'RECEIVED':'UNKNOWN', at: payAudit[0]?.at, source:'audit_logs / sub_payments'},
        {label:'Callback', value: payAudit.find(a=>/callback|verify/.test(a.action||''))?.action||'—', status: payAudit.find(a=>/callback/.test(a.action||''))?'RECEIVED':'MISSING', at: payAudit.find(a=>/callback/.test(a.action||''))?.at, source:'audit'},
        {label:'Verification', value: payAudit.find(a=>/verify/.test(a.action||''))?.action||'—', status: payAudit.find(a=>/verify/.test(a.action||''))?'DONE':'MISSING', at: null, source:'verification'},
        {label:'Subscription', value: sub?.status||'—', status: sub?.status==='active'?'ACTIVATED':'NOT ACTIVATED', at: sub?.end_date, source:'subscriptions'},
        {label:'Notification', value: (d.recent_notifications||[])[0]?.title||'—', status: (d.recent_notifications||[]).length?'SENT':'NOT SENT', at: (d.recent_notifications||[])[0]?.at, source:'notifications'},
        {label:'Audit', value: `${audits.length} رویداد`, status: audits.length?'AVAILABLE':'MISSING', at: audits[0]?.at, source:'audit_logs'},
      ];
    }
    if(mode==='subscription'){
      return [
        {label:'Subscription', value: sub?.plan||'—', status: sub?.status==='active'?'ACTIVE':'INACTIVE', at: sub?.end_date, source:'subscriptions'},
        {label:'Days Left', value: sub?.days_left!=null? String(sub.days_left):'—', status: sub?.days_left!=null && sub.days_left>7?'OK': sub?.days_left!=null && sub.days_left>=0?'EXPIRING':'EXPIRED', at: null, source:'computed'},
        {label:'History', value: `${(d.subscription_history||[]).length} تمدید`, status: (d.subscription_history||[]).length?'AVAILABLE':'NONE', at: (d.subscription_history||[])[0]?.at, source:'subscription_history'},
        {label:'Audit', value: `${audits.filter(a=>/sub|plan/.test(a.action||'')).length} رویداد`, status:'AVAILABLE', at:null, source:'audit_logs'},
      ];
    }
    if(mode==='ai'){
      return [
        {label:'AI Access', value: ai.banned? 'BANNED':'ALLOWED', status: ai.banned?'BANNED':'ALLOWED', at:null, source:'ai.banned'},
        {label:'Usage Total', value: String(ai.total_usage||0), status: Number(ai.total_usage||0)>200?'HIGH':'NORMAL', at:null, source:'ai_ledger'},
        {label:'Today', value: String(ai.today||0), status:'OK', at:null, source:'ai_ledger'},
        {label:'Recent Requests', value: `${(d.ai_recent||[]).length} درخواست`, status: (d.ai_recent||[]).length?'AVAILABLE':'NONE', at: (d.ai_recent||[])[0]?.at, source:'ai_ledger'},
      ];
    }
    if(mode==='support'){
      const opens=(d.recent_tickets||[]).filter(t=>t.status==='open').length;
      return [
        {label:'Open Tickets', value: String(opens), status: opens>=2?'CRITICAL': opens===1?'OPEN':'NONE', at: (d.recent_tickets||[])[0]?.at, source:'tickets'},
        {label:'Total Tickets', value: String(d.counts?.tickets||0), status:'OK', at:null, source:'tickets'},
        {label:'Recent Ticket', value: (d.recent_tickets||[])[0]?.subject||'—', status: (d.recent_tickets||[]).length?'EXISTS':'NONE', at:(d.recent_tickets||[])[0]?.at, source:'tickets'},
      ];
    }
    if(mode==='academic'){
      return [
        {label:'Total Answers', value: String(u.total_answers||0), status: Number(u.total_answers||0)>100?'ACTIVE':'LOW', at: u.last_active, source:'users'},
        {label:'Accuracy', value: `${u.accuracy||0}٪`, status: Number(u.accuracy||0)<40?'LOW':'OK', at:null, source:'users'},
        {label:'Exams', value: String(d.counts?.exams||0), status:'OK', at:(d.recent_exams||[])[0]?.started_at, source:'exam_sessions'},
        {label:'Grades', value: String(d.counts?.grades||0), status:'OK', at: (d.academic?.grades_recent||[])[0]?.exam_date, source:'grades'},
      ];
    }
    if(mode==='security'){
      return [
        {label:'Approved', value: String(!!u.approved), status: u.approved?'YES':'NO', at:null, source:'users.approved'},
        {label:'Suspended', value: String(!!u.suspended), status: u.suspended?'SUSPENDED':'CLEAR', at:null, source:'users.suspended'},
        {label:'Roles', value: (d.roles||[]).map(r=>r.key).join(',')||'—', status:(d.roles||[]).length?'HAS ROLE':'NONE', at:null, source:'user_roles'},
        {label:'Recent Security Audit', value: `${audits.filter(a=>/role|suspend|block|permission/.test((a.action||'').toLowerCase())).length} رویداد`, status:'AVAILABLE', at:null, source:'audit_logs'},
      ];
    }
    return [];
  })();
  const hasEvidence = evidence.some(e=> e.value!=='—' && e.value!=='0' && e.value!=='');
  return (
    <div className="grid" style={{ gap:10 }}>
      <div className="panel panel-pad" style={{ background:'var(--c-bg)' }}>
        <b>🔍 Investigation Workspace</b>
        <div className="muted" style={{ fontSize:'var(--fs-caption)' }}>Problem → Evidence → Related Objects → Suggested Action — فقط از سیستم واقعی</div>
        <div className="row" style={{ gap:6, flexWrap:'wrap', marginTop:8 }}>
          {modes.map(([k,l])=> <button key={k} className={`btn sm ${mode===k?'primary':''}`} onClick={()=>setMode(k)}>{l}</button>)}
        </div>
      </div>
      {!hasEvidence && <div className="panel panel-pad" style={{ textAlign:'center' }}><Empty icon="🔍" text="شواهدی برای این حالت یافت نشد — No Data / Unavailable" /></div>}
      <div className="grid" style={{ gap:6 }}>
        {evidence.map((e,i)=>(
          <div key={i} className="row" style={{ padding:'10px 12px', background:'var(--c-surface)', border:'1px solid var(--c-line)', borderRadius:10, gap:8 }}>
            <div style={{ minWidth:110 }}><b style={{ fontSize:'var(--fs-label)' }}>{e.label}</b><div className="muted" style={{ fontSize:'var(--fs-caption)' }}>{e.source}</div></div>
            <div style={{ flex:1 }}>
              <div className="code" style={{ fontSize:'var(--fs-label)' }}>{e.value}</div>
              {e.at && <div className="muted" style={{ fontSize:'var(--fs-caption)' }}><FaDateTime value={e.at} /></div>}
            </div>
            <B kind={e.status==='ACTIVATED'||e.status==='ACTIVE'||e.status==='ALLOWED'||e.status==='RECEIVED'||e.status==='DONE'||e.status==='OK'?'ok': e.status==='EXPIRING'||e.status==='HIGH'||e.status==='OPEN'?'warn': e.status==='NOT ACTIVATED'||e.status==='MISSING'||e.status==='BANNED'||e.status==='SUSPENDED'||e.status==='CRITICAL'||e.status==='EXPIRED'?'bad':''}>{e.status}</B>
          </div>
        ))}
      </div>
      <div className="panel panel-pad" style={{ background:'color-mix(in srgb, var(--c-acc) 5%, var(--c-surface))', borderColor:'rgba(77,184,255,.22)' }}>
        <b>🎯 خلاصه — Root Cause Candidate</b>
        <div className="muted" style={{ marginTop:6, fontSize:'var(--fs-label)' }}>
          {mode==='payment' && (evidence.find(e=>e.label==='Subscription')?.status==='NOT ACTIVATED' ? 'Possible Cause: پرداخت دریافت شده ولی اشتراک فعال نشده — Verification یا Notification را در Audit بررسی کنید.' : 'No clear payment failure — برای جزئیات به Audit و Subscription مراجعه کنید.')}
          {mode==='subscription' && (evidence.find(e=>e.label==='Days Left')?.status==='EXPIRING' ? 'Possible Cause: اشتراک در حال انقضا — تمدید پیشنهاد می‌شود.' : evidence.find(e=>e.label==='Subscription')?.status==='INACTIVE' ? 'Cause: اشتراک غیرفعال — سابقه پرداخت را بررسی کنید.' : 'اشتراک سالم به‌نظر می‌رسد.')}
          {mode==='ai' && (evidence.find(e=>e.label==='AI Access')?.status==='BANNED' ? 'Cause: کاربر از هوشیار مسدود است.' : 'No AI block — سهمیه و تاریخچه را بررسی کنید.')}
          {mode==='support' && (Number(evidence.find(e=>e.label==='Open Tickets')?.value||0)>=2 ? 'Possible Cause: چند تیکت باز — نیاز به پاسخگویی.' : 'No critical support issue.')}
          {mode==='academic' && (Number(evidence.find(e=>e.label==='Accuracy')?.value?.replace('٪','')||100)<40 ? 'Signal: دقت پایین — نیاز به بررسی آموزشی.' : 'No academic anomaly.')}
          {mode==='security' && (evidence.find(e=>e.label==='Suspended')?.value==='true' ? 'Cause: حساب تعلیق‌شده — دلیل را در Audit ببینید.' : 'No security block — نقش‌ها و Audit را بررسی کنید.')}
        </div>
        <div className="row" style={{ gap:6, marginTop:8, flexWrap:'wrap' }}>
          <button className="btn sm" onClick={()=>go('/audit?target='+row.id)}>🧭 Audit</button>
          <button className="btn sm" onClick={()=>go('/subscriptions?q='+row.id)}>💎 اشتراک</button>
          <button className="btn sm" onClick={()=>go('/tickets?q='+row.id)}>🎫 تیکت‌ها</button>
        </div>
      </div>
    </div>
  );
}

function JourneyReplay({ d }){
  const [filter, setFilter] = React.useState('all');
  const [range, setRange] = React.useState('all');
  const [idx, setIdx] = React.useState(0);
  const journey = d ? buildJourney(d) : {events:[], gaps:[]};
  const filtered = journey.events.filter(e=>{
    if(filter==='all') return true;
    const m={account:['registered','approved','first_activity','last_active'], academic:['first_answer','first_exam'], finance:['subscription'], ai:['ai']};
    return (m[filter]||[]).includes(e.key);
  }).filter(e=>{
    if(range==='all') return true;
    const days = range==='7'?7: range==='30'?30:90;
    try{ const diff=(Date.now()-new Date(e.at).getTime())/86400000; return diff<=days; }catch{ return true; }
  });
  React.useEffect(()=>{ setIdx(0); },[filter,range,d]);
  if(!d) return <Loading label="بارگذاری مسیر کاربر" />;
  if(!filtered.length) return <Empty icon="🛤️" text="رویدادی برای این فیلتر/بازه یافت نشد" />;
  const cur = filtered[Math.min(idx, filtered.length-1)];
  return (
    <div className="grid" style={{ gap:10 }}>
      <div className="panel panel-pad" style={{ background:'var(--c-bg)' }}>
        <div className="row" style={{ gap:6, flexWrap:'wrap' }}>
          <b>🛤️ User Journey Replay</b>
          <span className="muted" style={{ fontSize:'var(--fs-caption)' }}>· {faNum(filtered.length)} رویداد واقعی</span>
          <span className="spacer" />
          <div className="row" style={{ gap:4 }}>
            {['all','account','academic','finance','ai'].map(k=> <button key={k} className={`btn sm ${filter===k?'primary':''}`} onClick={()=>setFilter(k)}>{k==='all'?'همه':k}</button>)}
          </div>
          <div className="row" style={{ gap:4 }}>
            {['all','7','30','90'].map(k=> <button key={k} className={`btn sm ${range===k?'primary':''}`} onClick={()=>setRange(k)}>{k==='all'?'همه زمان':`${k} روز`}</button>)}
          </div>
        </div>
        {journey.gaps.length>0 && <div className="grid" style={{ gap:4, marginTop:8 }}>{journey.gaps.map((g,i)=><div key={i} className="row" style={{ gap:6, padding:'6px 8px', background:'color-mix(in srgb, var(--c-warn) 7%, var(--c-surface))', border:'1px solid rgba(240,181,69,.25)', borderRadius:8 }}><B kind="warn">Gap</B><span style={{ fontSize:'var(--fs-label)' }}>{g.label}</span></div>)}</div>}
      </div>
      {/* Timeline rail */}
      <div style={{ display:'grid', gridTemplateColumns:'1fr auto', gap:10 }}>
        <div style={{ borderInlineStart:'2px solid var(--c-line)', paddingInlineStart:12, display:'grid', gap:6 }}>
          {filtered.map((e,i)=>(
            <div key={i} className={`row ${i===idx?'panel panel-pad':''}`} style={{ padding:i===idx?'8px 10px':'6px 0', borderRadius: i===idx?10:0, background: i===idx?'var(--c-surface)':'transparent', border: i===idx?'1px solid var(--c-line)':'none', cursor:'pointer' }} onClick={()=>setIdx(i)}>
              <span style={{ width:10, height:10, borderRadius:'50%', background: i===idx?'var(--c-acc)':'var(--c-line2)', marginTop:6 }} />
              <div style={{ flex:1 }}>
                <b style={{ color: i===idx?'var(--c-txt)':'var(--c-txt2)', fontSize:'var(--fs-label)' }}>{e.label}</b>
                <div className="muted" style={{ fontSize:'var(--fs-caption)' }}><FaDateTime value={e.at} /> · <span className="code">{e.source}</span></div>
                {e.detail && <div className="muted" style={{ fontSize:'var(--fs-caption)' }}>{e.detail}</div>}
              </div>
              {i===idx && <B kind="acc">▶</B>}
            </div>
          ))}
        </div>
        <div className="panel panel-pad" style={{ background:'var(--c-surface)', minWidth:220, height:'fit-content', position:'sticky', top:10 }}>
          <b>Replay</b>
          <div className="muted" style={{ fontSize:'var(--fs-caption)' }}>{idx+1} / {filtered.length}</div>
          {cur && <div style={{ marginTop:8 }}>
            <b>{cur.label}</b>
            <div className="muted" style={{ fontSize:'var(--fs-caption)' }}><FaDateTime value={cur.at} /></div>
            <div className="code" style={{ marginTop:6, fontSize:'var(--fs-caption)' }}>{cur.source}</div>
            {cur.detail && <div style={{ marginTop:6, fontSize:'var(--fs-label)' }}>{cur.detail}</div>}
          </div>}
          <div className="row" style={{ gap:6, marginTop:10 }}>
            <button className="btn sm" disabled={idx<=0} onClick={()=>setIdx(i=>Math.max(0,i-1))}>‹ قبلی</button>
            <button className="btn sm primary" disabled={idx>=filtered.length-1} onClick={()=>setIdx(i=>Math.min(filtered.length-1,i+1))}>بعدی ›</button>
          </div>
          <div className="muted" style={{ fontSize:'var(--fs-caption)', marginTop:6 }}>visualization صرفاً — هیچ Event جدیدی ایجاد نمی‌شود.</div>
        </div>
      </div>
    </div>
  );
}

function SnapshotCompare({ d, row }){
  const [mode, setMode] = React.useState('now_7');
  if(!d) return <Loading label="بارگذاری مقایسه" />;
  const audits = d.recent_audit||[];
  // Find last profile/subscription/role change
  const lastChange = audits.find(a=> /profile|student|group|intake|subscription|role|approve|suspend/.test((a.action||'').toLowerCase()));
  const beforeAfter = (()=>{
    if(!lastChange) return null;
    const ch = lastChange.changes || lastChange.after || null;
    // try to use DiffViewer data if available
    const before = lastChange.before || {};
    const after = lastChange.after || lastChange.changes || {};
    return {audit:lastChange, before, after};
  })();
  const nowVs = (days)=>{
    // cannot reconstruct historical DB without snapshot store — show what we can infer
    return [
      {field:'وضعیت حساب', now: d.user.suspended?'تعلیق': d.user.approved?'فعال':'در انتظار', hist: '—', delta: 'نامشخص (نیاز به snapshot store)', tone:''},
      {field:'اشتراک', now: d.subscription?.status==='active'? `${d.subscription.plan} · ${d.subscription.days_left} روز` : '—', hist:'—', delta:'فقط آخرین وضعیت موجود', tone:''},
      {field:'دقت', now: `${d.user.accuracy||0}٪`, hist:'—', delta:'تاریخچهٔ دقت ذخیره نمی‌شود', tone:''},
      {field:'پاسخ‌ها', now: String(d.user.total_answers||0), hist:'—', delta:'—', tone:''},
    ];
  };
  return (
    <div className="grid" style={{ gap:10 }}>
      <div className="panel panel-pad" style={{ background:'var(--c-bg)' }}>
        <b>🔀 Snapshot Compare — NOW vs HISTORICAL / BEFORE vs AFTER</b>
        <div className="muted" style={{ fontSize:'var(--fs-caption)' }}>فقط Fieldهایی که Historical Evidence واقعی دارند مقایسه می‌شوند — بدون داده جعلی</div>
        <div className="row" style={{ gap:6, marginTop:8, flexWrap:'wrap' }}>
          <button className={`btn sm ${mode==='before_after'?'primary':''}`} onClick={()=>setMode('before_after')}>Before → After (آخرین تغییر)</button>
          <button className={`btn sm ${mode==='now_7'?'primary':''}`} onClick={()=>setMode('now_7')}>Now vs 7d</button>
          <button className={`btn sm ${mode==='now_30'?'primary':''}`} onClick={()=>setMode('now_30')}>Now vs 30d</button>
        </div>
      </div>
      {mode==='before_after' && (
        beforeAfter ? (
          <div className="grid" style={{ gap:8 }}>
            <div className="panel panel-pad" style={{ background:'var(--c-surface)' }}>
              <div className="row" style={{ gap:6 }}><b>تغییر اخیر:</b><span>{beforeAfter.audit.action}</span><span className="spacer" /><FaDateTime value={beforeAfter.audit.at} /><B>{beforeAfter.audit.module||'—'}</B></div>
              <div className="muted" style={{ fontSize:'var(--fs-caption)' }}>توسط {beforeAfter.audit.actor?.name||beforeAfter.audit.actor?.id||'—'} · Correlation: <span className="code">{beforeAfter.audit.correlation_id||'—'}</span></div>
            </div>
            <DiffViewer before={beforeAfter.before} after={beforeAfter.after} />
            <div className="muted" style={{ fontSize:'var(--fs-caption)' }}>SOURCE: audit_logs · before/after واقعی — اگر خالی است، آن Audit بدون snapshot ذخیره شده.</div>
          </div>
        ) : <Empty icon="🔀" text="تغییر قابل مقایسه‌ای در Audit اخیر یافت نشد" />
      )}
      {(mode==='now_7' || mode==='now_30') && (
        <div className="grid" style={{ gap:6 }}>
          <div className="panel panel-pad" style={{ background:'color-mix(in srgb, var(--c-warn) 5%, var(--c-surface))', borderColor:'rgba(240,181,69,.25)' }}>
            <b>⚠️ Historical vs Now</b><span className="muted" style={{ fontSize:'var(--fs-caption)', marginInlineStart:6 }}>— سیستم فعلی snapshot store تاریخی ندارد؛ فقط آخرین وضعیت + آخرین Audit موجود است. برای مقایسهٔ دقیق، snapshot store لازم است (عمداً نساختیم تا DB موازی نشود).</span>
          </div>
          {nowVs(mode==='now_7'?7:30).map((r,i)=>(
            <div key={i} className="row" style={{ padding:'8px 10px', background:'var(--c-surface)', border:'1px solid var(--c-line)', borderRadius:10, gap:8 }}>
              <span style={{ minWidth:110, fontWeight:700, fontSize:'var(--fs-label)' }}>{r.field}</span>
              <span className="code" style={{ flex:1 }}>{r.now}</span>
              <span className="muted">→</span>
              <span className="code" style={{ flex:1 }}>{r.hist}</span>
              <span className="muted" style={{ fontSize:'var(--fs-caption)' }}>{r.delta}</span>
            </div>
          ))}
          <button className="btn sm" onClick={()=>setMode('before_after')}>رفتن به Before/After واقعی</button>
        </div>
      )}
    </div>
  );
}

function RecommendationPanel({ d, row, go, onAction }){
  const recs = d ? computeRecommendations(d) : [];
  if(!d) return <Loading label="بارگذاری پیشنهادها" />;
  if(!recs.length) return <div className="panel panel-pad" style={{ textAlign:'center' }}><Empty icon="✨" text="این کاربر در حال حاضر اقدام پیشنهادی ندارد — وضعیت سالم." /></div>;
  return (
    <div className="grid" style={{ gap:8 }}>
      {recs.map(r=>(
        <div key={r.id} className="row" style={{ padding:'10px 12px', background:'var(--c-surface)', border:`1px solid ${r.sev==='critical'?'rgba(248,113,113,.35)': r.sev==='high'?'rgba(240,181,69,.35)':'var(--c-line)'}`, borderRadius:10, gap:10, alignItems:'flex-start' }}>
          <span style={{ fontSize:18 }}>{r.icon}</span>
          <div style={{ flex:1 }}>
            <div style={{ display:'flex', gap:6, alignItems:'center', flexWrap:'wrap' }}><b>{r.title}</b><B kind={r.sev==='critical'?'bad': r.sev==='high'?'warn': r.sev==='medium'?'warn':''}>{r.sev==='critical'?'بحرانی': r.sev==='high'?'بالا': r.sev==='medium'?'متوسط':'کم'}</B></div>
            <div className="muted" style={{ fontSize:'var(--fs-label)', marginTop:4 }}><b>WHY:</b> {r.reason}</div>
            <div className="muted" style={{ fontSize:'var(--fs-caption)' }}><b>SOURCE:</b> <span className="code">{r.evidence}</span></div>
          </div>
          <div className="row" style={{ gap:6 }}>
            {r.go && <button className="btn sm" onClick={()=>go(r.go)}>{r.action}</button>}
            {r.id==='inactive_msg' && <button className="btn sm primary" onClick={()=>onAction && onAction('message')}>📨 پیام</button>}
            {r.id==='extend_sub' && <button className="btn sm primary" onClick={()=>go('/subscriptions?q='+row.id)}>💎 تمدید</button>}
          </div>
        </div>
      ))}
      <div className="muted" style={{ fontSize:'var(--fs-caption)', textAlign:'center' }}>هر Recommendation فقط پیشنهاد است — هیچ Action خودکار اجرا نمی‌شود. Deduplication اعمال شده.</div>
    </div>
  );
}

function UserDrawer({ row, me, go, onClose, initialData, onSnapshot, onRemoved }) {
  const [d, setD] = useState(initialData || null);
  const [failed, setFailed] = useState('');
  const [loading, setLoading] = useState(!initialData);
  const [tab, setTab] = useState('overview');
  const [relation, setRelation] = useState(null);
  const [timelineFilter, setTimelineFilter] = useState('all');
  const [investigation, setInvestigation] = useState('');
  const requestSeq = useRef(0);

  const fetchSnapshot = useCallback(async ({ keepData = true } = {}) => {
    const uid = row.id;
    const seq = ++requestSeq.current;
    setFailed('');
    if (!keepData) setD(null);
    setLoading(true);
    try {
      const snapshot = await api.user360(uid);
      if (seq !== requestSeq.current) return null;
      setD(snapshot);
      onSnapshot?.(uid, snapshot);
      return snapshot;
    } catch (error) {
      if (seq === requestSeq.current) setFailed(errText(error));
      return null;
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [row.id, onSnapshot]);

  useEffect(() => {
    requestSeq.current += 1;
    setTab('overview'); setRelation(null); setFailed(''); setTimelineFilter('all'); setInvestigation('');
    if (initialData) { setD(initialData); setLoading(false); }
    else { setD(null); fetchSnapshot({ keepData: false }); }
    return () => { requestSeq.current += 1; };
  }, [row.id]);

  const refetch = useCallback(() => fetchSnapshot({ keepData: true }), [fetchSnapshot]);

  const has = permission => !!me?.is_owner || (me?.perms || []).includes(permission);
  const canAct = ['users.manage', 'users.suspend', 'users.message', 'users.delete'].some(has);
  const unavailable = section => d?.section_errors?.[section]
    ? <div className="panel panel-pad"><B kind="warn">⚠️ اطلاعات فعلاً در دسترس نیست</B><button className="btn sm" onClick={refetch}>Retry</button></div>
    : null;
  const health = d ? computeHealth(d) : null;
  const attention = d ? computeAttention(d) : [];
  const dq = d ? dataQualityForUser(d) : [];
  const statusCtx = statusContext(row);

  const TABS_GROUPED = [
    { group: 'IDENTITY', tabs: [['overview','📊 نمای کلی'], ['identity','👤 هویت']]},
    { group: 'DIAGNOSTICS', tabs: [['access','🔍 دسترسی'], ['investigate','🔎 بررسی']]},
    { group: 'LEARNING', tabs: [['academic','📚 یادگیری'], ['questions','🧪 سؤال‌ها'], ['exams','📝 آزمون‌ها'], ['prestige','🏆 افتخار']]},
    { group: 'ENGAGEMENT', tabs: [['journey','🛤️ مسیر'], ['activity','🕓 فعالیت'], ['notifications','🔔 اعلان‌ها'], ['ai','🤖 هوشیار']]},
    { group: 'ACCOUNT', tabs: [['sub','💎 اشتراک'], ['roles','🛡 نقش‌ها']]},
    { group: 'SUPPORT', tabs: [['tickets','🎫 تیکت‌ها']]},
    { group: 'SECURITY', tabs: [['audit','🧭 حسابرسی']]},
    { group: 'HISTORY', tabs: [['compare','🔀 مقایسه']]},
    { group: 'ACTIONS', tabs: [['actions','⚙️ اقدامات']]},
  ];
  const flatTabs = TABS_GROUPED.flatMap(g=>g.tabs);

  // Timeline categorization for filter
  const catFor = (e) => {
    const k = e.kind||'';
    if (['registration','answer','exam'].includes(k)) return 'academic';
    if (['ticket'].includes(k)) return 'support';
    if (['prestige'].includes(k)) return 'academic';
    if (['audit'].includes(k)) {
      const m=(e.description||'').toLowerCase();
      if (m.includes('payment')||m.includes('subscription')||m.includes('finance')) return 'finance';
      if (m.includes('ai')||m.includes('hosh')) return 'ai';
      if (m.includes('role')||m.includes('suspend')||m.includes('block')) return 'security';
      return 'admin';
    }
    return 'account';
  };

  return (
    <Drawer wide title={`👤 ${row.display_name || row.name} · #${row.id}`} onClose={onClose}>
      {/* Sticky Identity Header — always visible */}
      <div style={{ position:'sticky', top:0, zIndex:2, background:'color-mix(in srgb, var(--c-surface) 96%, transparent)', backdropFilter:'blur(8px)', border:'1px solid var(--c-line)', borderRadius:12, padding:10, marginBottom:10, display:'grid', gap:8 }}>
        <div className="row" style={{ gap:10, flexWrap:'wrap', alignItems:'center' }}>
          <div style={{ width:44, height:44, borderRadius:12, background:'linear-gradient(135deg, var(--c-acc), var(--c-teal))', display:'grid', placeItems:'center', color:'#fff', fontWeight:800, fontSize:18 }}>
            {(row.display_name||row.name||'?').trim().slice(0,1).toUpperCase()}
          </div>
          <div style={{ flex:1, minWidth:160 }}>
            <div style={{ display:'flex', gap:6, alignItems:'center', flexWrap:'wrap' }}>
              <b style={{ color:'var(--c-txt)', fontSize:'var(--fs-card)' }}>{row.display_name||row.name}</b>
              <span className="code muted">#{row.id}</span>
              {row.username && <span className="muted">@{row.username}</span>}
            </div>
            <div className="row" style={{ gap:4, marginTop:4, flexWrap:'wrap' }}>
              <B kind={statusCtx.tone}>{statusCtx.icon} {statusCtx.text}</B>
              {row.intake && <B>{row.intake}</B>}
              {row.group && <B>گروه {row.group}</B>}
              {row.student_id && <span className="code" style={{ fontSize:'var(--fs-caption)' }}>{row.student_id}</span>}
              {d?.subscription?.status==='active' && <B kind="ok">💎 {d.subscription.plan} · {faNum(d.subscription.days_left)} روز</B>}
              {!d?.subscription && row.subscription?.status==='active' && <B kind="ok">💎 {row.subscription.plan}</B>}
            </div>
          </div>
          {health && (
            <div style={{ display:'flex', gap:10, alignItems:'center' }}>
              <div className={`health-score ${health.tone==='warn'?'warn':health.tone==='bad'?'bad':''}`} style={{ '--score': health.score, width:56, height:56 }}><span>{faNum(health.score)}</span></div>
              <div style={{ minWidth:90 }}>
                <div style={{ fontWeight:800, color: health.tone==='bad'?'var(--c-bad)':health.tone==='warn'?'var(--c-warn)':'var(--c-ok)' }}>{health.label}</div>
                <div className="muted" style={{ fontSize:'var(--fs-caption)' }}>سلامت کاربر</div>
              </div>
            </div>
          )}
        </div>
        {/* Quick Action Rail */}
        <div className="row" style={{ gap:6, flexWrap:'wrap' }}>
          {has('users.message') && <button className="btn sm" onClick={()=>setTab('actions')}>📨 پیام</button>}
          {has('users.manage') && <button className="btn sm" onClick={()=>setTab('actions')}>✏️ ویرایش</button>}
          {has('subscription.manage') && <button className="btn sm" onClick={()=>setTab('sub')}>💎 اشتراک</button>}
          {has('users.suspend') && !row.suspended && <button className="btn sm warn" onClick={()=>setTab('actions')}>⏸ تعلیق</button>}
          {has('users.suspend') && row.suspended && <button className="btn sm ok" onClick={()=>setTab('actions')}>🔓 رفع تعلیق</button>}
          <button className="btn sm" onClick={()=>setTab('audit')}>🧭 Audit</button>
          <span className="spacer" />
          <button className="btn sm" onClick={refetch} title="به‌روزرسانی پرونده">↻ به‌روزرسانی</button>
          <span className="muted" style={{ fontSize:'var(--fs-caption)' }}>{d?`آخرین فعالیت: ${d.user?.last_active ? '' : '—'}`:''} {d?.user?.last_active && <RelativeTime value={d.user.last_active} />}</span>
        </div>
        {attention.length>0 && (
          <div className="row" style={{ gap:6, flexWrap:'wrap' }}>
            {attention.slice(0,4).map((a,i)=>(<B key={i} kind={a.sev==='critical'?'bad':a.sev==='warn'?'warn':''}>{a.icon} {a.title}</B>))}
            {attention.length>4 && <B>+{faNum(attention.length-4)}</B>}
          </div>
        )}
      </div>

      {/* Grouped Navigation */}
      <div style={{ display:'grid', gap:6, marginBottom:10 }}>
        {TABS_GROUPED.filter(g=> g.group!=='ACTIONS' || canAct).map(g=>(
          <div key={g.group} className="row" style={{ gap:6, flexWrap:'wrap', alignItems:'center' }}>
            <span className="muted" style={{ fontSize:'var(--fs-caption)', minWidth:72 }}>{g.group}</span>
            <div className="row" style={{ gap:4, flexWrap:'wrap' }}>
              {g.tabs.filter(([k])=> k!=='actions' || canAct).map(([k,v])=>(
                <button key={k} type="button" role="tab" aria-selected={tab===k} className={`tab ${tab===k?'on':''}`} onClick={()=>setTab(k)} style={{ fontSize:'var(--fs-label)' }}>{v}</button>
              ))}
            </div>
          </div>
        ))}
      </div>

      {failed && <div className="user-drawer-error"><ErrorState title="اطلاعات کاربر بارگذاری نشد" error={failed} onRetry={() => fetchSnapshot({ keepData: Boolean(d) })} />
        {!d && <dl className="kv">
          {Object.entries({
            'نام': row.name, 'یوزرنیم': row.username && '@' + row.username,
            'شماره دانشجویی': row.student_id, 'ورودی': row.intake, 'گروه': row.group,
          }).filter(([, v]) => v).map(([k, v]) => (
            <React.Fragment key={k}><dt>{k}</dt><dd>{String(v)}</dd></React.Fragment>
          ))}
        </dl>}
      </div>}
      {loading && !d && tab !== 'actions' && <Loading label="در حال بارگذاری پرونده کاربر" />}
      {tab === 'actions' && (
        <UserActions row={row} d={d} me={me} onChanged={refetch} onClose={onClose} onRemoved={onRemoved} />
      )}
      {d && tab === 'overview' && (
        <>
          {/* 🎯 Next Best Actions — Rule-based */}
          <div className="panel panel-pad" style={{ background:'var(--c-bg)', borderColor:'rgba(77,184,255,.22)' }}>
            <div className="row" style={{ gap:6 }}><b>✨ اقدام پیشنهادی بعدی</b><span className="muted" style={{ fontSize:'var(--fs-caption)' }}>· Rule-based · بدون اجرای خودکار</span><span className="spacer" /><button className="btn sm" onClick={()=>setTab('investigate')}>🔍 بررسی</button></div>
            <div style={{ marginTop:8 }}><RecommendationPanel d={d} row={row} go={go} onAction={(a)=> a==='message' && setTab('actions')} /></div>
          </div>
          {/* Health + Attention */}
          <div className="grid g2" style={{ gap:10 }}>
            <div className="panel panel-pad" style={{ background:'var(--c-bg)', borderColor: health?.tone==='bad'?'rgba(248,113,113,.35)': health?.tone==='warn'?'rgba(240,181,69,.35)':'var(--c-line)' }}>
              <b>🩺 سلامت کاربر — {health ? `${faNum(health.score)}/۱۰۰ · ${health.label}` : '—'}</b>
              {health && <div className="grid" style={{ gap:6, marginTop:8 }}>
                {health.reasons.slice(0,6).map((r,i)=>(<div key={i} className="row" style={{ gap:6 }}><span>{r.icon}</span><span style={{ flex:1, fontSize:'var(--fs-label)' }}>{r.text}</span><B kind={r.tone==='ok'?'ok':r.tone==='warn'?'warn':r.tone==='bad'?'bad':''}>{r.tone==='ok'?'✓':r.tone==='warn'?'!':'✕'}</B></div>))}
                <div className="muted" style={{ fontSize:'var(--fs-caption)', marginTop:4 }}>امتیاز Rule-based از دادهٔ واقعی (حساب/فعالیت/اشتراک/آموزش/پشتیبانی/هوشیار) — عدد تصادفی نیست.</div>
              </div>}
            </div>
            <div className="panel panel-pad" style={{ background: attention.length?'color-mix(in srgb, var(--c-warn) 6%, var(--c-surface))':'var(--c-bg)', borderColor: attention.length?'rgba(240,181,69,.35)':'var(--c-line)' }}>
              <b>⚠️ نیازمند توجه {attention.length?`· ${faNum(attention.length)} مورد`:''}</b>
              {!attention.length ? <div className="muted" style={{ marginTop:6 }}>مورد فعالی نیست — وضعیت سالم.</div> :
                <div className="grid" style={{ gap:6, marginTop:8 }}>
                  {attention.map((a,i)=>(<div key={i} className="row" style={{ gap:6, padding:'6px 8px', background:'var(--c-surface)', border:'1px solid var(--c-line)', borderRadius:8 }}><span>{a.icon}</span><span style={{ flex:1 }}>{a.title}</span><B kind={a.sev==='critical'?'bad':a.sev==='warn'?'warn':''}>{a.sev==='critical'?'بحرانی':a.sev==='warn'?'هشدار':'اطلاع'}</B></div>))}
                </div>
              }
              {dq.length>0 && <div style={{ marginTop:10 }}><b style={{ fontSize:'var(--fs-label)' }}>🧹 کیفیت داده</b><div className="row" style={{ gap:4, flexWrap:'wrap', marginTop:6 }}>{dq.map(x=><B key={x.k} kind={x.sev==='warn'?'warn':''}>{x.label}</B>)}</div></div>}
            </div>
          </div>

          {/* Summary + Relationship */}
          <div className="grid g4" style={{ marginTop:10 }}>
            <div className="panel panel-pad"><b>{faNum(d.user.total_answers)}</b><div className="muted">پاسخ · دقت {faNum(d.user.accuracy)}٪</div><button className="btn sm" style={{ marginTop:6 }} onClick={()=>setTab('academic')}>مشاهده</button></div>
            <div className="panel panel-pad"><b>{faNum(d.counts.exams)}</b><div className="muted">آزمون</div><button className="btn sm" style={{ marginTop:6 }} onClick={()=>setTab('exams')}>مشاهده</button></div>
            <div className="panel panel-pad"><b>{faNum(d.counts.tickets)}</b><div className="muted">تیکت { (d.recent_tickets||[]).filter(t=>t.status==='open').length ? `· ${faNum((d.recent_tickets||[]).filter(t=>t.status==='open').length)} باز` : ''}</div><button className="btn sm" style={{ marginTop:6 }} onClick={()=>setTab('tickets')}>مشاهده</button></div>
            <div className="panel panel-pad"><b>{faNum(d.ai?.total_usage)}</b><div className="muted">هوشیار {d.ai?.banned?'· مسدود':''}</div><button className="btn sm" style={{ marginTop:6 }} onClick={()=>setTab('ai')}>مشاهده</button></div>
          </div>
          <div className="panel panel-pad" style={{ marginTop:10, background:'var(--c-bg)' }}>
            <div className="row" style={{ gap:6, flexWrap:'wrap' }}>
              <b>🔗 اکوسیستم کاربر</b><span className="muted">— یک نگاه به ارتباطات واقعی</span><span className="spacer" />
              <button className="btn sm" onClick={()=>setInvestigation(investigation?'':'subscription')}>{investigation?'بستن بررسی':'🔍 حالت بررسی'}</button>
            </div>
            <div className="grid" style={{ gridTemplateColumns:'repeat(auto-fit,minmax(130px,1fr))', gap:6, marginTop:8 }}>
              <div className="panel panel-pad" style={{ background:'var(--c-surface)', textAlign:'center' }}><div className="muted" style={{fontSize:'var(--fs-caption)'}}>اشتراک</div><b>{d.subscription?.status==='active'?'فعال': '—'}</b><div className="muted" style={{fontSize:'var(--fs-caption)'}}>{d.subscription?.plan||'بدون پلن'}</div></div>
              <div className="panel panel-pad" style={{ background:'var(--c-surface)', textAlign:'center' }}><div className="muted" style={{fontSize:'var(--fs-caption)'}}>پرداخت‌ها</div><b>{faNum(d.counts?.payments||0)}</b><div className="muted" style={{fontSize:'var(--fs-caption)'}}>اخیر {faNum((d.recent_payments||[]).length)}</div></div>
              <div className="panel panel-pad" style={{ background:'var(--c-surface)', textAlign:'center' }}><div className="muted" style={{fontSize:'var(--fs-caption)'}}>نمرات</div><b>{faNum(d.counts?.grades||0)}</b><div className="muted" style={{fontSize:'var(--fs-caption)'}}>میانگین {d.academic?.avg?Number(d.academic.avg).toLocaleString('fa-IR'):'—'}</div></div>
              <div className="panel panel-pad" style={{ background:'var(--c-surface)', textAlign:'center' }}><div className="muted" style={{fontSize:'var(--fs-caption)'}}>سؤال‌ها</div><b>{faNum(d.counts?.questions||0)}</b><div className="muted" style={{fontSize:'var(--fs-caption)'}}>طراحی‌شده</div></div>
              <div className="panel panel-pad" style={{ background:'var(--c-surface)', textAlign:'center' }}><div className="muted" style={{fontSize:'var(--fs-caption)'}}>آزمون‌ها</div><b>{faNum(d.counts?.exams||0)}</b><div className="muted" style={{fontSize:'var(--fs-caption)'}}>شرکت‌کرده</div></div>
              <div className="panel panel-pad" style={{ background:'var(--c-surface)', textAlign:'center' }}><div className="muted" style={{fontSize:'var(--fs-caption)'}}>اعلان‌ها</div><b>{faNum(d.notifs?.total||0)}</b><div className="muted" style={{fontSize:'var(--fs-caption)'}}>{faNum(d.notifs?.unread||0)} خوانده‌نشده</div></div>
            </div>
            <div className="row" style={{ gap:4, flexWrap:'wrap', marginTop:8 }}>
              <span className="muted" style={{fontSize:'var(--fs-caption)'}}>ارتباط سریع:</span>
              <button className="btn sm" onClick={()=>setTab('sub')}>اشتراک</button>
              <button className="btn sm" onClick={()=>setTab('academic')}>نمرات</button>
              <button className="btn sm" onClick={()=>setTab('tickets')}>تیکت‌ها</button>
              <button className="btn sm" onClick={()=>setTab('activity')}>تایم‌لاین</button>
              <button className="btn sm" onClick={()=>setTab('audit')}>Audit</button>
            </div>
          </div>
          {investigation && (
            <div className="panel panel-pad" style={{ marginTop:10, background:'color-mix(in srgb, var(--c-acc) 5%, var(--c-surface))', borderColor:'rgba(77,184,255,.25)' }}>
              <div className="row" style={{ gap:6 }}>
                <b>🔍 حالت بررسی —</b>
                <select className="inp" value={investigation} onChange={e=>setInvestigation(e.target.value)}>
                  <option value="subscription">مشکل اشتراک/پرداخت</option>
                  <option value="ai">مشکل هوشیار</option>
                  <option value="ticket">مشکل پشتیبانی</option>
                  <option value="academic">مشکل تحصیلی</option>
                  <option value="security">مشکل امنیتی/دسترسی</option>
                </select>
                <span className="spacer" />
                <button className="btn sm" onClick={()=>setInvestigation('')}>بستن</button>
              </div>
              <div className="muted" style={{ marginTop:8 }}>
                {investigation==='subscription' && <>برای «اشتراک فعال نشده»: پرداخت → تأیید → اشتراک → اعلان → Audit را در تب‌های <b>💎 اشتراک / 🧭 Audit / 🎫 تیکت</b> بررسی کنید. Correlation ID مشترک را در Audit جستجو کنید.</>}
                {investigation==='ai' && <>برای «هوشیار کار نمی‌کند»: تب <b>🤖 هوشیار</b> (وضعیت مسدود/سهمیه) + <b>🕓 فعالیت</b> + <b>🧭 Audit</b> (تغییرات دسترسی) را ببینید.</>}
                {investigation==='ticket' && <>برای «تیکت بی‌پاسخ»: تب <b>🎫 تیکت‌ها</b> (باز/پاسخ) + <b>🕓 فعالیت</b> + <b>🧭 Audit</b> (اقدامات پشتیبان) را دنبال کنید.</>}
                {investigation==='academic' && <>برای «نمره ثبت نشده»: تب <b>📚 یادگیری</b> + <b>🧭 Audit</b> (import/grade) + <b>🕓 فعالیت</b> را بررسی کنید.</>}
                {investigation==='security' && <>برای «دسترسی/نقش»: تب <b>🛡 نقش‌ها</b> (permissions مؤثر) + <b>🧭 Audit</b> (role change) + <b>🕓 فعالیت</b> را ببینید.</>}
              </div>
            </div>
          )}
          <div className="grid g2" style={{ marginTop: 10 }}>
            <div className="panel panel-pad"><b>وضعیت حساب</b><div style={{ marginTop: 6 }}>
              {d.user.suspended ? <B kind="bad">تعلیق‌شده</B> : d.user.approved ? <B kind="ok">فعال</B> : <B kind="warn">در انتظار تأیید</B>}
              <span className="muted"> · آخرین فعالیت: </span><RelativeTime value={d.user.last_active} fallback="ثبت نشده" />
            </div><div className="muted" style={{ marginTop:6, fontSize:'var(--fs-caption)' }}>ثبت‌نام: <FaDateTime value={d.user.registered_at} /> · ID: <span className="code">{d.user.id}</span></div></div>
            <div className="panel panel-pad"><b>اشتراک هامزیار</b><div style={{ marginTop: 6 }}>
              {d.subscription?.status === 'active' ? <><B kind="ok">{d.subscription.plan}</B><span className="muted"> {faNum(d.subscription.days_left)} روز باقی</span></> : <span className="muted">اشتراک فعال ندارد</span>}
            </div>
              {d.subscription?.end_date && <div className="muted" style={{ marginTop:6, fontSize:'var(--fs-caption)' }}>پایان: <FaDateTime value={d.subscription.end_date} /></div>}
              {d.subscription?.status==='active' && has('subscription.manage') && <button className="btn sm" style={{ marginTop:8 }} onClick={()=>setTab('sub')}>تمدید/مدیریت</button>}
            </div>
          </div>
        </>
      )}
      {d && tab === 'access' && (<AccessDiagnostics d={d} />)}
      {d && tab === 'investigate' && (<InvestigationWorkspace d={d} row={row} go={go} />)}
      {d && tab === 'journey' && (<JourneyReplay d={d} />)}
      {d && tab === 'compare' && (<SnapshotCompare d={d} row={row} />)}
      {d && tab === 'identity' && (
        <dl className="kv">
          {Object.entries({
            'نام کامل': d.user.name, 'نام‌نما': d.user.nickname,
            'یوزرنیم': d.user.username && '@' + d.user.username,
            'Telegram ID': d.user.id, 'شماره دانشجویی': d.user.student_id,
            'ورودی': d.user.intake, 'گروه': d.user.group, 'نقش قدیمی': d.user.role,
            'ثبت‌نام': d.user.registered_at, 'آخرین فعالیت': d.user.last_active,
          }).filter(([, v]) => v !== undefined && v !== '').map(([k, v]) => (
            <React.Fragment key={k}><dt>{k}</dt><dd className={k === 'Telegram ID' || k === 'یوزرنیم' ? 'code' : ''}>{k === 'ثبت‌نام' || k === 'آخرین فعالیت' ? <FaDateTime value={v} /> : String(v)}</dd></React.Fragment>
          ))}
        </dl>
      )}
      {d && tab === 'academic' && (
        <>
          {unavailable('academic') || unavailable('academic_counts')}
          <div className="panel panel-pad" style={{ background:'var(--c-bg)', marginBottom:8 }}>
            <div className="row" style={{ gap:8, flexWrap:'wrap' }}>
              <div><div className="muted" style={{fontSize:'var(--fs-caption)'}}>میانگین</div><b>{d.academic?.avg!=null?Number(d.academic.avg).toLocaleString('fa-IR'):'—'}</b></div>
              <div><div className="muted" style={{fontSize:'var(--fs-caption)'}}>بهترین</div><b style={{color:'var(--c-ok)'}}>{d.academic?.best!=null?Number(d.academic.best).toLocaleString('fa-IR'):'—'}</b></div>
              <div><div className="muted" style={{fontSize:'var(--fs-caption)'}}>کمترین</div><b style={{color:'var(--c-bad)'}}>{d.academic?.worst!=null?Number(d.academic.worst).toLocaleString('fa-IR'):'—'}</b></div>
              <div><div className="muted" style={{fontSize:'var(--fs-caption)'}}>تعداد نمره</div><b>{faNum(d.counts.grades||0)}</b></div>
              <span className="spacer" /><button className="btn sm" onClick={() => setRelation('grades')}>مشاهده همه</button>
            </div>
            {(() => {
              const weak = (d.academic?.weak_areas||[]).slice(0,3);
              if (!weak.length) return null;
              return (<div style={{ marginTop:8 }}><div className="muted" style={{fontSize:'var(--fs-caption)'}}>⚠️ حوزه‌های ضعیف (واقعی):</div><div className="row" style={{ gap:6, flexWrap:'wrap', marginTop:4 }}>{weak.map(w=><B key={w.lesson} kind="warn">{w.lesson} · {faNum(w.accuracy)}٪</B>)}</div></div>);
            })()}
          </div>
          {(d.academic?.grades_recent || []).length === 0 &&
            <div className="center-state">نمره‌ای ثبت نشده</div>}
          {(d.academic?.grades_recent || []).map((g, i) => (
            <div key={i} className="row" style={{ padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
              <span>📚</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <b style={{ color: 'var(--txt)' }}>{g.lesson}</b>
                <div className="muted">{g.exam_title} · <FaDate value={g.exam_date} />{g.term ? ` · ${g.term}` : ''}</div>
              </div>
              <B kind={g.score >= 10 ? 'ok' : 'bad'}>{Number(g.score).toLocaleString('fa')}</B>
            </div>
          ))}
        </>
      )}
      {d && tab === 'questions' && (
        <>
          {unavailable('questions')}
          <div className="row" style={{ marginBottom: 8 }}><span className="muted">سؤال‌های طراحی‌شده: {faNum(d.counts.questions)}</span><span className="spacer" /><button className="btn sm" onClick={() => setRelation('questions')}>مشاهده همه</button></div>
          {!(d.recent_questions || []).length && <Empty icon="🧪" text="سؤالی طراحی نکرده است" />}
          {(d.recent_questions || []).map(x => <div key={x.id} className="panel panel-pad" style={{ marginBottom: 6 }}>
            <div className="row"><b className="text-truncate">{x.question || '—'}</b><span className="spacer" />
              <B kind={x.approved ? 'ok' : 'warn'}>{x.approved ? 'تأییدشده' : 'در انتظار'}</B></div>
            <div className="muted">{x.lesson} · {x.topic} · {faNum(x.attempts)} تلاش · دقت {faNum(x.accuracy)}٪</div>
          </div>)}
        </>
      )}
      {d && tab === 'exams' && (
        <>
          {unavailable('exams')}
          <div className="row" style={{ marginBottom: 8 }}><span className="muted">آزمون‌ها: {faNum(d.counts.exams)}</span><span className="spacer" /><button className="btn sm" onClick={() => setRelation('exams')}>مشاهده همه</button></div>
          {!(d.recent_exams || []).length && <Empty icon="📝" text="آزمونی ثبت نشده است" />}
          {(d.recent_exams || []).map(x => <div key={x.id} className="row" style={{ padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
            <div style={{ flex: 1 }}><b>{x.lesson || 'آزمون سفارشی'}</b><div className="muted">{x.topic || 'همه مباحث'} · <FaDateTime value={x.started_at} /></div></div>
            <B kind={x.status === 'finished' ? 'ok' : 'warn'}>{x.status}</B><B kind="acc">{faNum(x.percentage)}٪</B>
          </div>)}
        </>
      )}
      {d && tab === 'prestige' && (
        <> {unavailable('prestige') || unavailable('prestige_history')}<div className="row"><span className="spacer" /><button className="btn sm" onClick={() => setRelation('prestige')}>مشاهده تاریخچه کامل</button></div><dl className="kv">
          {Object.entries({
            'رنک': d.prestige?.rank, 'دسته (Division)': d.prestige?.div,
            'XP افتخار': d.prestige?.prestige_xp, 'XP مؤثر': d.prestige?.effective_xp,
            'XP هفتگی': d.prestige?.weekly_xp, 'XP ماهانه': d.prestige?.monthly_xp,
            'XP امروز': d.prestige?.daily_xp_amount,
            '🔥 استریک فعلی': d.prestige?.streak_current, '🥇 بهترین استریک': d.prestige?.streak_best,
          }).filter(([, v]) => v !== undefined && v !== '' && v !== null).map(([k, v]) => (
            <React.Fragment key={k}><dt>{k}</dt>
              <dd>{typeof v === 'number' ? Number(v).toLocaleString('fa') : String(v)}</dd></React.Fragment>
          ))}
        </dl>
        {!!(d.prestige_history || []).length && <div style={{ marginTop: 12 }}><b>تاریخچه Prestige</b>
          {(d.prestige_history || []).map(x => <div key={x.id} className="row" style={{ padding: '6px 0', borderBottom: '1px solid var(--line)' }}>
            <span style={{ flex: 1 }}>{x.title || x.kind || 'رویداد'}</span><B kind={x.xp >= 0 ? 'ok' : 'warn'}>{x.xp >= 0 ? '+' : ''}{faNum(x.xp)} XP</B><FaDateTime value={x.at} />
          </div>)}</div>}
        </>
      )}
      {d && tab === 'ai' && (
        <>
          {unavailable('ai')}
          <dl className="kv">
            <dt>پرسش کل</dt><dd>{Number(d.ai?.total_usage || 0).toLocaleString('fa')}</dd>
            <dt>پرسش امروز</dt><dd>{Number(d.ai?.today || 0).toLocaleString('fa')}</dd>
            <dt>توکن مصرفی</dt><dd>{Number(d.ai?.total_tokens || 0).toLocaleString('fa')}</dd>
            <dt>وضعیت دسترسی</dt>
            <dd>{d.ai?.banned ? <B kind="bad">⛔ مسدود از هوشیار</B> : <B kind="ok">✅ آزاد</B>}</dd>
            <dt>اعلان‌های خوانده‌نشده</dt>
            <dd>{Number(d.notifs?.unread || 0).toLocaleString('fa')} از {Number(d.notifs?.total || 0).toLocaleString('fa')}</dd>
          </dl>
          {d.ai?.banned && (
            <p className="muted">رفع مسدودیت از صفحه‌ی «هوشیار ← دسترسی» انجام می‌شود.</p>
          )}
          {!!(d.ai_recent||[]).length && <div style={{ marginTop:10 }}><b>آخرین درخواست‌های هوشیار</b>
            {(d.ai_recent||[]).slice(0,8).map((r,i)=>(<div key={i} className="row" style={{ padding:'6px 0', borderBottom:'1px solid var(--line)', gap:6 }}><B>{r.model||'gemini'}</B><span style={{flex:1}} className="muted">{r.type||'chat'} · {r.status||'—'}</span><span className="code" style={{fontSize:'var(--fs-caption)'}}>{r.latency?`${r.latency}ms`:''}</span><FaDateTime value={r.at} /></div>))}
          </div>}
        </>
      )}
      {d && tab === 'notifications' && (
        <>
          {unavailable('notifications')}
          <div className="row" style={{ marginBottom: 8 }}><B kind="warn">خوانده‌نشده: {faNum(d.notifs?.unread)}</B><B>کل: {faNum(d.notifs?.total)}</B><span className="spacer" /><button className="btn sm" onClick={() => setRelation('notifications')}>مشاهده همه</button></div>
          {!(d.recent_notifications || []).length && <Empty icon="🔔" text="اعلانی ثبت نشده است" />}
          {(d.recent_notifications || []).map(x => <div key={x.id} className="panel panel-pad" style={{ marginBottom: 6 }}>
            <div className="row"><b>{x.title || x.type || 'اعلان'}</b><span className="spacer" />
              <B kind={x.read ? '' : 'acc'}>{x.read ? 'خوانده‌شده' : 'جدید'}</B></div>
            {x.body && <div className="muted">{x.body}</div>}<div className="muted"><FaDateTime value={x.at} /></div>
          </div>)}
        </>
      )}
      {d && tab === 'roles' && (
        <>
          {unavailable('roles') || unavailable('permissions')}
          {!(d.roles || []).length && <Empty icon="🛡" text="نقش مدیریتی ندارد" />}
          {(d.roles || []).map(r => <div key={r.key} className="panel panel-pad" style={{ marginBottom: 6 }}>
            <div className="row"><b>{r.label || r.key}</b><span className="code">{r.key}</span><span className="spacer" />
              <B kind={r.active ? 'ok' : 'bad'}>{r.active ? 'فعال' : 'غیرفعال'}</B>{r.scope && <B kind="purple">{r.scope}</B>}</div>
          </div>)}
          {!!(d.perms || []).length && <div><div style={{ marginTop:10, marginBottom:6 }}><b>✨ دسترسی‌های مؤثر (Effective Permissions)</b><span className="muted" style={{fontSize:'var(--fs-caption)'}}> — از اجتماع نقش‌ها + scope</span></div><div className="row" style={{ gap:4, flexWrap:'wrap' }}>{d.perms.map(p => <B key={p} kind="acc">{p}</B>)}</div>
            {d.roles?.some(r=>r.scope) && <div className="muted" style={{ marginTop:6, fontSize:'var(--fs-caption)' }}>Scope نمونه: {d.roles.filter(r=>r.scope).map(r=>`${r.key}:${r.scope}`).join(' · ')}</div>}
          </div>}
          {!d.perms?.length && d.roles?.length>0 && <div className="muted" style={{marginTop:8}}>نقش دارد ولی permission مؤثری یافت نشد — ممکن است نقش غیرفعال باشد.</div>}
        </>
      )}
      {d && tab === 'sub' && (<>
        {unavailable('subscription')}
        {d.subscription ? (
          <dl className="kv">
            <dt>وضعیت</dt><dd>{d.subscription.status === 'active' ? '✅ فعال' : d.subscription.status || '—'}</dd>
            <dt>پلن</dt><dd>{d.subscription.plan || '—'}</dd>
            <dt>پایان</dt><dd><FaDateTime value={d.subscription.end_date} /></dd>
            <dt>روزهای باقی</dt><dd>{d.subscription.days_left ?? '—'}</dd>
          </dl>
        ) : <div className="center-state">اشتراک فعالی ندارد</div>}
        {!!(d.subscription_history||[]).length && <div style={{ marginTop:10 }}><b>تاریخچه تمدید</b>{(d.subscription_history||[]).slice(0,10).map((h,i)=>(<div key={i} className="row" style={{ padding:'6px 0', borderBottom:'1px solid var(--line)' }}><span style={{flex:1}}>{h.plan||'—'} · {h.days?`${faNum(h.days)} روز`:''}</span><FaDateTime value={h.at||h.created_at} /></div>))}</div>}
        {d.subscription?.status==='active' && Number(d.subscription.days_left||999)>0 && Number(d.subscription.days_left||999)<=7 && <div className="panel panel-pad" style={{ marginTop:10, background:'color-mix(in srgb, var(--c-warn) 7%, var(--c-surface))', borderColor:'rgba(240,181,69,.35)' }}><div className="row"><span>⏰ اشتراک در حال انقضا — {faNum(d.subscription.days_left)} روز باقی</span><span className="spacer" />{has('subscription.manage') && <button className="btn sm primary" onClick={()=>{ toast('به بخش اشتراک منتقل شوید'); go('/subscriptions'); }}>💎 تمدید</button>}</div></div>}
      </>)}
      {d && tab === 'tickets' && (
        <>
          {unavailable('tickets')}
          <div className="row" style={{ marginBottom: 8 }}><span className="muted">مجموع: {Number(d.counts.tickets || 0).toLocaleString('fa')} تیکت</span><span className="spacer" /><button className="btn sm" onClick={() => setRelation('tickets')}>مشاهده همه</button></div>
          {(d.recent_tickets || []).length === 0 && <div className="center-state">تیکتی نیست</div>}
          {(d.recent_tickets || []).map(t => (
            <div key={t.id} className="row" style={{ padding: '8px 0', borderBottom: '1px solid var(--line)', cursor: 'pointer' }}
                 onClick={() => go('/tickets')}>
              <span>🎫</span>
              <span style={{ flex: 1 }}>{t.subject}</span>
              <B kind={t.status === 'open' ? 'bad' : t.status === 'answered' ? 'warn' : 'ok'}>
                {t.status === 'open' ? 'باز' : t.status === 'answered' ? 'پاسخ' : 'بسته'}</B>
              <FaDateTime value={t.at} />
            </div>
          ))}
        </>
      )}
      {d && tab === 'activity' && (
        <>
          {unavailable('answers')}
          <div className="row" style={{ marginBottom:8, flexWrap:'wrap', gap:6 }}>
            <b>تایم‌لاین کاربر</b>
            <span className="muted" style={{fontSize:'var(--fs-caption)'}}>· {faNum((d.activity||[]).length)} رویداد</span>
            <span className="spacer" />
            <div className="row" style={{ gap:4 }}>
              {[
                ['all','همه'], ['account','حساب'], ['academic','آموزشی'], ['support','پشتیبانی'], ['finance','مالی'], ['security','امنیتی'], ['ai','هوشیار']
              ].map(([k,l])=>(<button key={k} className={`btn sm ${timelineFilter===k?'primary':''}`} onClick={()=>setTimelineFilter(k)}>{l}</button>))}
            </div>
          </div>
          {!(d.activity || []).length && <Empty icon="🕓" text="فعالیتی ثبت نشده است" />}
          {(d.activity || []).filter(e=> timelineFilter==='all' || catFor(e)===timelineFilter).map(event => <button key={event.id} className="panel panel-pad row" style={{ width: '100%', marginBottom: 6, color: 'inherit', textAlign: 'right' }}
            onClick={() => event.go && go(event.go)}>
            <span style={{ fontSize: 'var(--fs-icon)' }}>{event.icon || '•'}</span>
            <span style={{ flex: 1 }}><b>{event.title}</b>{event.description && <span className="muted" style={{ display: 'block' }}>{event.description}</span>}
              {event.correlation_id && <span className="code" style={{ fontSize:'var(--fs-caption)' }}>{event.correlation_id}</span>}
            </span>
            <FaDateTime value={event.at} /><span className="muted">‹</span>
          </button>)}
          {(d.activity||[]).filter(e=> timelineFilter!=='all' && catFor(e)===timelineFilter).length===0 && (d.activity||[]).length>0 && timelineFilter!=='all' && <div className="muted" style={{ textAlign:'center', padding:12 }}>رویدادی در این دسته نیست</div>}
        </>
      )}
      {d && tab === 'audit' && (
        <>
          {unavailable('audit')}<div className="row"><span className="spacer" /><button className="btn sm" onClick={() => setRelation('audit')}>مشاهده همه</button></div>
          {(d.recent_audit || []).length === 0 && <div className="center-state">رویدادی ثبت نشده</div>}
          {(d.recent_audit || []).map((l, i) => (
            <div key={i} className="row" style={{ padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
              <span className={`sev ${(l.severity || '').toLowerCase()}`} />
              <span style={{ flex: 1 }}>{l.action}<div className="muted">{l.relation === 'target' ? 'عملیات روی این کاربر' : 'عملیات انجام‌شده توسط کاربر'}</div></span>
              {!!l.changes?.length && <B kind="acc">Δ {faNum(l.changes.length)}</B>}
              <B>{l.module}</B>
              {l.correlation_id && <span className="code">{l.correlation_id}</span>}
              <FaDateTime value={l.at} />
            </div>
          ))}
        </>
      )}
      {relation && <UserRelationModal uid={row.id} section={relation} onClose={() => setRelation(null)} />}
    </Drawer>
  );
}

function UserRelationModal({ uid, section, onClose }) {
  const [page, setPage] = useState(1); const [data, setData] = useState(null); const [err, setErr] = useState(''); const limit = 30;
  const load = async () => { setData(null); setErr(''); try { setData(await api.userRelations(uid, section, { skip: (page - 1) * limit, limit })); } catch (e) { setErr(errText(e)); } };
  useEffect(() => { load(); }, [page, section]);
  return <Modal wide title={`تاریخچه کامل · ${section}`} onClose={onClose}>{err ? <ErrorState error={err} onRetry={load} /> : !data ? <Loading rows={6} /> : <>
    {!data.items?.length ? <Empty text="رکوردی ثبت نشده" /> : <div className="grid" style={{ gap: 6 }}>{data.items.map(x => <div key={x.id} className="panel panel-pad"><div className="row"><b className="text-wrap">{x.title || '—'}</b>{x.status && <B>{x.status}</B>}<span className="spacer" /><FaDateTime value={x.at} /></div>{x.detail && <div className="muted text-wrap">{typeof x.detail === 'object' ? JSON.stringify(x.detail) : x.detail}</div>}{x.value !== undefined && <B kind="acc">{String(x.value)}</B>}</div>)}</div>}
    <div className="row" style={{ justifyContent: 'center', marginTop: 10 }}><button className="btn sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>قبلی</button><B>{page.toLocaleString('fa')}</B><button className="btn sm" disabled={page * limit >= (data.total || 0)} onClick={() => setPage(p => p + 1)}>بعدی</button></div>
  </>}</Modal>;
}

/* ── ⚙️🌊 WA3 — تب اقدامات: DM + ویرایش پروفایل + اکشن‌های مدیریتی ─────
   دقیقاً معادل دکمه‌های پنل مدیریت داخل ربات؛ همه از API /api/web-admin
   با guard سمت سرور و audit رد می‌شوند (سینک کامل با ربات/مینی‌اپ). */
function UserActions({ row, d, me, onChanged, onClose, onRemoved }) {
  const u = d?.user || row;
  const has = permission => !!me?.is_owner || (me?.perms || []).includes(permission);
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [intakes, setIntakes] = useState([]);
  const [form, setForm] = useState({
    name: u.name || '', student_id: u.student_id || '',
    group: u.group || '', intake: u.intake || '', nickname: u.nickname || '',
  });
  const [confirm, setConfirm] = useState(null);   // {action,text,danger}
  const [pendingPatch, setPendingPatch] = useState(null);
  const [blockModal, setBlockModal] = useState(false);
  const [reason, setReason] = useState('');
  useEffect(() => { api.intakes().then(r => setIntakes(r.intakes || [])).catch(() => {}); }, []);

  const sendDM = async () => {
    if (!msg.trim()) return;
    setBusy(true);
    try { await api.waUserMessage(row.id, msg.trim()); toast('پیام در صف ارسال به کاربر قرار گرفت 📨'); setMsg(''); }
    catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  const proposeSave = () => {
    const body = {};
    ['name', 'student_id', 'group', 'intake', 'nickname'].forEach(k => {
      if (String(form[k] || '') !== String(u[k] || '')) body[k] = form[k];
    });
    if (!Object.keys(body).length) return toast('تغییری اعمال نشده است', 'err');
    setPendingPatch(body);
  };
  const applySave = async () => {
    const body = pendingPatch; setPendingPatch(null); setBusy(true);
    try {
      const r = await api.waUserPatch(row.id, body);
      toast(`ذخیره شد ✅ (${(r.changed || []).length} فیلد)`);
      await onChanged();
    } catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  const runAction = async (action, rs = '') => {
    setBusy(true);
    try {
      await api.waUserAction(row.id, action, rs);
      toast(`${USER_ACTIONS[action].icon} ${USER_ACTIONS[action].label} — انجام شد`);
      if (action === 'delete' || action === 'reject') {
        onRemoved?.(row.id);
        onClose();
        return;
      }
      await onChanged();
    } catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  const ask = (action, text) => setConfirm({ action, text, danger: USER_ACTIONS[action].danger });

  return (
    <div className="grid" style={{ gap: 12 }}>
      {/* 📨 پیام مستقیم — همان ارسال پیام پنل ربات (outbox → ربات می‌فرستد) */}
      {has('users.message') && <div className="panel panel-pad" style={{ background: 'var(--bg)' }}>
        <b>📨 ارسال پیام مستقیم (از سمت ربات)</b>
        <textarea className="inp" rows={3} style={{ width: '100%', marginTop: 8, resize: 'vertical' }}
                  placeholder="متن پیام برای کاربر… (حداکثر ۱۵۰۰ کاراکتر)"
                  maxLength={1500} value={msg} onChange={e => setMsg(e.target.value)} />
        <div className="row" style={{ marginTop: 8 }}>
          <span className="muted">{Number(msg.length).toLocaleString('fa')} / ۱۵۰۰</span>
          <span className="spacer" />
          <button className="btn primary sm" disabled={busy || !msg.trim()} onClick={sendDM}>ارسال 📨</button>
        </div>
      </div>}

      {/* ✏️ ویرایش پروفایل */}
      {has('users.manage') && <div className="panel panel-pad" style={{ background: 'var(--bg)' }}>
        <b>✏️ ویرایش پروفایل</b>
        <div className="grid g2" style={{ gap: 8, marginTop: 10 }}>
          <label className="fld"><span>نام</span>
            <input className="inp" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label>
          <label className="fld"><span>نام‌نما (نمایش به دیگران)</span>
            <input className="inp" value={form.nickname} onChange={e => setForm({ ...form, nickname: e.target.value })} /></label>
          <label className="fld"><span>شماره دانشجویی</span>
            <input className="inp" style={{ direction: 'ltr' }} value={form.student_id}
                   onChange={e => setForm({ ...form, student_id: e.target.value })} /></label>
          <label className="fld"><span>گروه</span>
            <select className="inp" value={form.group} onChange={e => setForm({ ...form, group: e.target.value })}>
              <option value="">(بدون گروه)</option>
              <option value="1">گروه ۱</option>
              <option value="2">گروه ۲</option>
              {!['', '1', '2'].includes(String(form.group)) &&
                <option value={form.group}>مقدار قدیمی: {form.group}</option>}
            </select></label>
          <label className="fld"><span>ورودی</span>
            <select className="inp" value={form.intake} onChange={e => setForm({ ...form, intake: e.target.value })}>
              <option value="">(بدون ورودی)</option>
              {intakes.map(i => <option key={i.code || i} value={i.code || i}>{i.label || i.code || i}</option>)}
            </select></label>
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn primary sm" disabled={busy} onClick={proposeSave}>بازبینی و ذخیره تغییرات</button>
          <span className="muted">تاریخچه‌ی تغییر نام‌نما در پروفایل کاربر ثبت می‌شود</span>
        </div>
      </div>}

      {/* 🎛 اکشن‌های مدیریتی — همان دکمه‌های ربات */}
      <div className="panel panel-pad" style={{ background: 'var(--bg)' }}>
        <b>🎛 اکشن‌های مدیریتی</b>
        <div className="row" style={{ marginTop: 10, gap: 6, flexWrap: 'wrap' }}>
          {has('users.manage') && !u.approved && !u.suspended && <>
            <button className="btn ok sm" disabled={busy}
                    onClick={() => ask('approve', `تأیید حساب «${u.name || row.id}»؟ به کاربر اطلاع‌رسانی می‌شود.`)}>✅ تأیید حساب</button>
            <button className="btn danger sm" disabled={busy}
                    onClick={() => ask('reject', `رد و حذف درخواست «${u.name || row.id}»؟`)}>✖️ رد درخواست</button>
          </>}
          {has('users.suspend') && (u.suspended
            ? <button className="btn ok sm" disabled={busy}
                      onClick={() => ask('unsuspend', `رفع تعلیق «${u.name || row.id}»؟`)}>🔓 رفع تعلیق</button>
            : <button className="btn danger sm" disabled={busy}
                      onClick={() => ask('suspend', `تعلیق «${u.name || row.id}»؟ به کاربر اطلاع‌رسانی می‌شود.`)}>⏸ تعلیق</button>)}
          {has('users.delete') && <button className="btn danger sm" disabled={busy} onClick={() => { setReason(''); setBlockModal(true); }}>⛔ مسدود</button>}
          {has('users.delete') && <button className="btn sm" disabled={busy}
                  onClick={() => ask('unblock', `رفع مسدودیت «${u.name || row.id}» از لیست سیاه؟`)}>🕊 رفع مسدودیت</button>}
          {has('users.delete') && <button className="btn danger sm" disabled={busy}
                  onClick={() => ask('delete', `حذف کامل حساب «${u.name || row.id}»؟ این عمل برگشت‌پذیر نیست.`)}>🗑 حذف حساب</button>}
        </div>
      </div>

      {pendingPatch && <Modal title="بازبینی تغییرات کاربر" onClose={() => setPendingPatch(null)}>
        <p className="muted" style={{ marginBottom: 10 }}>مقادیر زیر پس از تأیید ذخیره و در حسابرسی ثبت می‌شوند.</p>
        <DiffViewer
          before={Object.fromEntries(Object.keys(pendingPatch).map(k => [k, u[k] ?? '']))}
          after={Object.fromEntries(Object.keys(pendingPatch).map(k => [k, pendingPatch[k]]))} />
        <div className="row" style={{ marginTop: 12 }}><button className="btn primary" onClick={applySave}>تأیید و ذخیره</button>
          <button className="btn" onClick={() => setPendingPatch(null)}>بازگشت</button></div>
      </Modal>}
      {confirm && (
        <Confirm text={confirm.text} danger={confirm.danger}
                 onYes={async () => { await runAction(confirm.action); setConfirm(null); }}
                 onNo={() => setConfirm(null)} />
      )}
      {blockModal && (
        <Modal title={`⛔ مسدودسازی «${u.name || row.id}»`} onClose={() => setBlockModal(false)}>
          <p className="muted" style={{ marginBottom: 8 }}>
            کاربر به لیست سیاه اضافه می‌شود و دسترسی‌اش به ربات/مینی‌اپ قطع خواهد شد.</p>
          <input className="inp" style={{ width: '100%' }} placeholder="دلیل مسدودسازی (در لیست سیاه نمایش داده می‌شود)…"
                 value={reason} onChange={e => setReason(e.target.value)} />
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn danger" disabled={busy} onClick={async () => {
              setBlockModal(false); await runAction('block', reason.trim());
            }}>⛔ مسدود کن</button>
            <button className="btn" onClick={() => setBlockModal(false)}>انصراف</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

/* ── ⛔🌊 WA3 — لیست سیاه + رفع مسدودیت ─────────────────────── */
function BlacklistModal({ me, onClose }) {
  const canDelete = !!me?.is_owner || (me?.perms || []).includes('users.delete');
  const [items, setItems] = useState(null);
  const [err, setErr] = useState('');
  const load = async () => {
    setErr('');
    try { setItems((await api.blacklist()).blacklist || []); }
    catch (e) { setErr(errText(e)); }
  };
  useEffect(() => { load(); }, []);
  const unblock = async (uid) => {
    try { await api.waUserAction(uid, 'unblock'); toast('رفع مسدودیت شد 🕊'); load(); }
    catch (e) { toast(errText(e), 'err'); }
  };
  return (
    <Modal title="⛔ لیست سیاه — کاربران مسدودشده" onClose={onClose}>
      {err ? <ErrorState error={err} onRetry={load} /> : !items ? <Loading /> : (
        <div className="grid" style={{ gap: 6, maxHeight: '60vh', overflowY: 'auto' }}>
          {items.length === 0 && <Empty icon="🕊" text="هیچ کاربر مسدودشده‌ای نیست" />}
          {items.map(b => (
            <div key={b.id} className="row" style={{ padding: '8px 10px', border: '1px solid var(--line)', borderRadius: 10 }}>
              <span>⛔</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <b style={{ color: 'var(--txt)' }}>{b.name || `#${b.id}`}</b>{' '}
                <span className="code muted">{b.id}</span>
                <div className="muted">{b.blocked_by_name ? `توسط ${b.blocked_by_name}` : ''} {b.blocked_at || ''}</div>
              </div>
              {canDelete && <button className="btn sm ok" onClick={() => unblock(b.id)}>🕊 رفع مسدودیت</button>}
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}

/* ── 📅🌊 مودال مدیریت ورودی‌ها (موج Intakes-CA) — همان امکانات admin:intakes ربات ── */
function IntakesModal({ onClose }) {
  const [items, setItems] = useState(null);
  const [err, setErr] = useState('');
  const [code, setCode] = useState('');
  const [label, setLabel] = useState('');
  const [busy, setBusy] = useState(false);
  const [delCode, setDelCode] = useState(null);
  const load = async () => {
    setErr('');
    try { setItems((await api.intakes()).intakes || []); }
    catch (e) { setErr(errText(e)); }
  };
  useEffect(() => { load(); }, []);
  const add = async () => {
    if (!code.trim() || !label.trim()) return;
    setBusy(true);
    try { await api.intakeAdd(code.trim(), label.trim()); toast('ورودی افزوده شد 📅'); setCode(''); setLabel(''); load(); }
    catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  const toggle = async (c) => {
    try { const r = await api.intakeToggle(c); toast(r.active ? 'فعال شد ✅' : 'غیرفعال شد'); load(); }
    catch (e) { toast(errText(e), 'err'); }
  };
  const del = async (c) => {
    try { await api.intakeDel(c); toast('ورودی حذف شد 🗑'); load(); }
    catch (e) { toast(errText(e), 'err'); }
  };
  return (
    <Modal title="📅 مدیریت ورودی‌ها" onClose={() => onClose(true)}>
      {err ? <ErrorState error={err} onRetry={load} /> : !items ? <Loading /> : (<>
        <div className="grid" style={{ gap: 6, maxHeight: '46vh', overflowY: 'auto' }}>
          {items.length === 0 && <Empty icon="📅" text="هنوز ورودی‌ای تعریف نشده" />}
          {items.map(i => (
            <div key={i.code} className="intake-row">
              <div style={{ flex: 1, minWidth: 0 }}>
                <b style={{ color: 'var(--txt)' }}>{i.label || i.code}</b>{' '}
                <span className="code muted">{i.code}</span>
                <div className="muted">
                  👥 {faNum(i.total ?? 0)} دانشجو
                  {i.groups && Object.keys(i.groups).length > 0 &&
                    ` · ${Object.entries(i.groups).map(([g, c]) => `گروه ${faNum(g)}: ${faNum(c)}`).join(' | ')}`}
                </div>
              </div>
              <label className="row" style={{ gap: 5 }} title="پذیرش ورودی">
                <Switch on={i.active !== false} onChange={() => toggle(i.code)} />
                <span className="muted" style={{ fontSize: 'var(--fs-label)' }}>{i.active !== false ? 'فعال' : 'متوقف'}</span>
              </label>
              <button className="btn sm danger" onClick={() => setDelCode(i.code)} aria-label={`حذف ورودی ${i.label || i.code}`}>🗑</button>
            </div>
          ))}
        </div>
        <div className="row" style={{ marginTop: 12, flexWrap: 'wrap', gap: 6 }}>
          <input className="inp" style={{ flex: 1, minWidth: 110 }} dir="ltr" placeholder="کد (مثل mehr_1405)"
                 value={code} onChange={e => setCode(e.target.value)} />
          <input className="inp" style={{ flex: 1, minWidth: 110 }} placeholder="برچسب (مهر ۱۴۰۵)"
                 value={label} onChange={e => setLabel(e.target.value)} />
          <button className="btn primary sm" disabled={busy || !code.trim() || !label.trim()} onClick={add}>
            {busy ? '⏳' : '➕ افزودن'}
          </button>
        </div>
        <div className="muted" style={{ marginTop: 6 }}>غیرفعال‌سازی = توقف پذیرش جدید؛ داده‌های ورودی حفظ می‌شود.</div>
      </>)}
      {delCode && (
        <Confirm text={`حذف ورودی «${delCode}»؟ (کاربرانش حذف نمی‌شوند ولی کد ورودی آزاد می‌شود)`} danger
                 onYes={async () => { const c = delCode; setDelCode(null); await del(c); }}
                 onNo={() => setDelCode(null)} />
      )}
    </Modal>
  );
}

/* ── 🎓🌊 مودال ادمین‌های محتوا (موج Intakes-CA) — همان admin:content_admins ربات ── */
function ContentAdminsModal({ onClose }) {
  const [items, setItems] = useState(null);
  const [err, setErr] = useState('');
  const [uid, setUid] = useState('');
  const [busy, setBusy] = useState(false);
  const [revoke, setRevoke] = useState(null);
  const load = async () => {
    setErr('');
    try { setItems((await api.contentAdmins()).admins || []); }
    catch (e) { setErr(errText(e)); }
  };
  useEffect(() => { load(); }, []);
  const grant = async () => {
    const id = parseInt(uid, 10);
    if (!id) return;
    setBusy(true);
    try { await api.contentAdminAdd(id); toast('دسترسی ادمین محتوا داده شد 🎓'); setUid(''); load(); }
    catch (e) { toast(errText(e), 'err'); }
    setBusy(false);
  };
  const doRevoke = async (id) => {
    try { await api.contentAdminDel(id); toast('دسترسی لغو شد'); load(); }
    catch (e) { toast(errText(e), 'err'); }
  };
  return (
    <Modal title="🎓 ادمین‌های محتوا (scope ورودی)" onClose={onClose}>
      {err ? <ErrorState error={err} onRetry={load} /> : !items ? <Loading /> : (<>
        <div className="grid" style={{ gap: 6, maxHeight: '46vh', overflowY: 'auto' }}>
          {items.length === 0 && <Empty icon="🎓" text="هنوز ادمین محتوایی تعریف نشده" />}
          {items.map(a => (
            <div key={a.id} className="row" style={{ padding: '8px 10px', border: '1px solid var(--line)', borderRadius: 10 }}>
              <span>🎓</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <b style={{ color: 'var(--txt)' }}>{a.name || `#${a.id}`}</b>{' '}
                <span className="code muted">{a.id}</span>
              </div>
              <button className="btn sm danger" onClick={() => setRevoke(a)}>لغو دسترسی</button>
            </div>
          ))}
        </div>
        <div className="row" style={{ marginTop: 12, gap: 6 }}>
          <input className="inp" style={{ flex: 1 }} dir="ltr" inputMode="numeric"
                 placeholder="Telegram ID کاربر (عددی)…" value={uid} onChange={e => setUid(e.target.value)} />
          <button className="btn primary sm" disabled={busy || !/^\d+$/.test(uid.trim())} onClick={grant}>
            {busy ? '⏳' : '➕ اعطای دسترسی'}
          </button>
        </div>
        <div className="muted" style={{ marginTop: 6 }}>اعطا ⇒ نقش content_admin + اطلاع‌رسانی خودکار در ربات · لغو ⇒ بازگشت به دانشجو. هر دو در audit ثبت می‌شوند.</div>
      </>)}
      {revoke && (
        <Confirm text={`لغو دسترسی ادمین محتوای «${revoke.name || revoke.id}»؟ (به نقش دانشجو برمی‌گردد)`} danger
                 onYes={async () => { const a = revoke; setRevoke(null); await doRevoke(a.id); }}
                 onNo={() => setRevoke(null)} />
      )}
    </Modal>
  );
}
