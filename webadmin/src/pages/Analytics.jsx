import React, { useEffect, useMemo, useRef, useState } from 'react';
import { api, errText, exportCSV } from '../api.js';
import { B, Empty, ErrorState, FaDateTime, Loading, NoPerm, PageHeader } from '../ui.jsx';
import { fileDateStamp, formatFaDate, formatFaDayMonth } from '../time.js';
import SavedViews from '../SavedViews.jsx';
import { writeHashQuery } from '../urlState.js';
import {
  ACTION_LABELS, ANALYTICS_DICTIONARY, NOTIFICATION_JOBS,
  flattenDictionary, metricDefinition,
} from '../analyticsDictionary.js';

const RANGES = [[1, 'امروز'], [7, '۷ روز'], [30, '۳۰ روز'], [90, '۹۰ روز']];
const TABS = [
  ['overview', 'نمای کلی', '📊'], ['users', 'کاربران', '👥'], ['learning', 'یادگیری', '🧠'],
  ['content', 'محتوا', '📚'], ['support', 'پشتیبانی', '🎫'], ['finance', 'اشتراک و مالی', '💎'],
  ['notifications', 'اعلان‌ها', '🔔'], ['ai', 'هوشیار', '🤖'], ['operations', 'عملیات و سلامت', '⚙️'],
];
const fa = value => Number(value ?? 0).toLocaleString('fa-IR');
const money = value => `${fa(value)} تومان`;
const isNumber = value => typeof value === 'number' && Number.isFinite(value);

function formatMetric(value, unit) {
  if (value === null || value === undefined) return 'داده موجود نیست';
  if (unit === 'تومان') return money(value);
  if (unit === 'درصد') return `${fa(value)}٪`;
  if (unit === 'ساعت' && isNumber(value)) return `${fa(value)} ساعت`;
  if (unit === 'نام پلن') return String(value || 'داده موجود نیست');
  return isNumber(value) ? fa(value) : String(value);
}

function MetricInfo({ definition, metricKey }) {
  return <details className="an-info">
    <summary aria-label={`تعریف شاخص ${definition.label}`} title="این عدد چیست؟">؟</summary>
    <div className="an-info-pop">
      <b>{definition.label}</b>
      <span><strong>بازه:</strong> {definition.range}</span>
      <span><strong>محاسبه:</strong> {definition.calculation}</span>
      <span><strong>منبع:</strong> <code dir="ltr">{definition.source}</code></span>
      <span><strong>روش داده:</strong> {definition.storage || 'محاسبه زنده روی داده‌های persisted'}</span>
      <span><strong>کلید فنی:</strong> <code dir="ltr">{metricKey}</code></span>
    </div>
  </details>;
}

function Comparison({ item, days }) {
  if (!item) return <span className="an-compare unavailable">مقایسه دوره‌ای برای این شاخص موجود نیست</span>;
  if (item.change_pct === null || item.change_pct === undefined) {
    return <span className="an-compare unavailable">دوره قبل صفر بوده؛ درصد تغییر قابل محاسبه نیست</span>;
  }
  const icon = item.direction === 'up' ? '▲' : item.direction === 'down' ? '▼' : '━';
  const word = item.direction === 'up' ? 'افزایش' : item.direction === 'down' ? 'کاهش' : 'بدون تغییر';
  return <span className={`an-compare ${item.direction}`}>{icon} {fa(Math.abs(item.change_pct))}٪ {word} نسبت به {fa(days)} روز قبل</span>;
}

function MetricCard({ domain, metricKey, value, icon = '◆', comparison, compareEnabled = false, tone = '', action, override }) {
  const definition = { ...metricDefinition(domain, metricKey), ...(override || {}) };
  const href = action || definition.action;
  return <article className={`an-metric ${tone}`.trim()}>
    <div className="an-metric-head"><span className="an-metric-icon" aria-hidden="true">{icon}</span><span>{definition.label}</span><span className="spacer" /><MetricInfo definition={definition} metricKey={`${domain}.${metricKey}`} /></div>
    <div className="an-metric-value">{formatMetric(value, definition.unit)}</div>
    <div className="an-metric-context">{definition.range}{definition.unit && definition.unit !== 'تومان' && definition.unit !== 'درصد' && definition.unit !== 'نام پلن' ? ` · واحد: ${definition.unit}` : ''}</div>
    {compareEnabled && <Comparison item={comparison} days={comparison?.days} />}
    {href && <a className="an-drill" href={`#${href}`}>مشاهده جزئیات ←</a>}
  </article>;
}

function SectionHeader({ icon, title, description, action }) {
  return <header className="an-section-head">
    <div><h2><span aria-hidden="true">{icon}</span> {title}</h2>{description && <p>{description}</p>}</div>
    {action}
  </header>;
}

function SemanticBars({ title, purpose, rows = [], unit = 'مورد', empty = 'داده‌ای برای این نمودار وجود ندارد' }) {
  const clean = rows.filter(row => row && isNumber(Number(row.value)));
  if (!clean.length) return <div className="an-chart panel panel-pad"><h3>{title}</h3><p className="an-purpose">❔ {purpose}</p><Empty icon="📭" title="داده کافی نیست" description={empty} /></div>;
  const max = Math.max(1, ...clean.map(row => Math.abs(Number(row.value))));
  return <div className="an-chart panel panel-pad">
    <h3>{title}</h3><p className="an-purpose">❔ {purpose}</p>
    <div className="an-bars" role="img" aria-label={`${title}؛ واحد ${unit}`}>
      {clean.map((row, index) => <div className="an-bar-row" key={`${row.label}-${index}`}>
        <span className="an-bar-label">{row.label}</span>
        <div className="an-bar-track"><div className="an-bar-fill" style={{ width: `${Math.max(2, Math.round(Math.abs(Number(row.value)) * 100 / max))}%` }} /></div>
        <b>{fa(row.value)}</b>
      </div>)}
    </div>
    <table className="an-data-table"><caption>مقادیر دقیق {title}</caption><thead><tr><th>دسته</th><th>{unit}</th></tr></thead><tbody>{clean.map((row, index) => <tr key={`${row.label}-table-${index}`}><td>{row.label}</td><td>{fa(row.value)}</td></tr>)}</tbody></table>
  </div>;
}

function DailyChart({ title, purpose, rows = [], unit = 'رویداد', note }) {
  const clean = rows.filter(row => row?.date && isNumber(Number(row.count)));
  if (!clean.length) return <div className="an-chart panel panel-pad"><h3>{title}</h3><p className="an-purpose">❔ {purpose}</p><Empty icon="📉" title="داده کافی نیست" description="در بازه انتخابی رویداد روزانه‌ای ثبت نشده است." /></div>;
  const max = Math.max(1, ...clean.map(row => Number(row.count)));
  const total = clean.reduce((sum, row) => sum + Number(row.count), 0);
  const peak = clean.reduce((best, row) => Number(row.count) > Number(best.count) ? row : best, clean[0]);
  return <div className="an-chart panel panel-pad">
    <h3>{title}</h3><p className="an-purpose">❔ {purpose}</p>
    <div className="an-daily" dir="ltr" role="img" aria-label={`${title}؛ ${fa(total)} ${unit}`}>
      {clean.map(row => <div className="an-day" key={row.date} title={`${formatFaDayMonth(row.date)} — ${fa(row.count)} ${unit}`}><div className="an-day-bar" style={{ height: `${Math.max(3, Math.round(Number(row.count) * 100 / max))}%` }} /><span>{formatFaDayMonth(row.date)}</span></div>)}
    </div>
    <p className="an-chart-summary">جمع بازه: <b>{fa(total)}</b> {unit} · اوج ثبت‌شده: <b>{formatFaDate(peak.date)}</b> با {fa(peak.count)} {unit}{note ? ` · ${note}` : ''}</p>
    <table className="an-data-table"><caption>داده روزانه {title}</caption><thead><tr><th>تاریخ</th><th>{unit}</th></tr></thead><tbody>{clean.map(row => <tr key={`${row.date}-table`}><td>{formatFaDate(row.date)}</td><td>{fa(row.count)}</td></tr>)}</tbody></table>
  </div>;
}

function DomainFailure({ title, onRetry, restricted = false }) {
  return <div className="an-domain-state"><div aria-hidden="true">{restricted ? '🔒' : '⚠️'}</div><b>{title}</b><p>{restricted ? 'مجوز لازم برای مشاهده این دامنه در نقش فعلی وجود ندارد.' : 'این دامنه فعلاً در دسترس نیست؛ سایر تحلیل‌ها همچنان قابل استفاده‌اند.'}</p>{onRetry && !restricted && <button className="btn" onClick={onRetry}>↻ تلاش مجدد</button>}</div>;
}

function AttentionPanel({ items, loading, error, onRetry }) {
  return <section className="an-attention">
    <SectionHeader icon="🚨" title="نیازمند توجه" description="موارد واقعی که اکنون بررسی مدیریتی یا اقدام عملیاتی می‌خواهند" />
    {loading ? <Loading rows={2} /> : error ? <DomainFailure title="هشدارهای مدیریتی بارگذاری نشد" onRetry={onRetry} /> : items.length === 0 ?
      <div className="an-all-clear"><span aria-hidden="true">✅</span><div><b>مورد فوری در داده‌های موجود دیده نشد</b><p>این نتیجه فقط بر اساس قواعد و داده‌های ثبت‌شده فعلی است.</p></div></div> :
      <div className="an-alert-list">{items.map(item => <article className={`an-alert ${item.severity || 'warning'}`} key={item.id}><span className="an-alert-icon" aria-hidden="true">{item.icon || '⚠️'}</span><div><b>{item.title}</b>{item.detail && <p>{item.detail}</p>}{item.scope && <span className="an-scope">دامنه: {item.scope}</span>}</div>{item.href && <a className="btn sm" href={`#${item.href}`}>بررسی و اقدام</a>}</article>)}</div>}
  </section>;
}

function RawDetails({ title, data, domain }) {
  const dictionary = Object.entries(ANALYTICS_DICTIONARY[domain] || {});
  return <details className="an-raw panel panel-pad"><summary>🔍 جزئیات فنی و واژه‌نامه این بخش</summary><div className="an-raw-grid"><div><h3>قرارداد خام API</h3><pre dir="ltr">{JSON.stringify(data || {}, null, 2)}</pre></div><div><h3>واژه‌نامه {title}</h3><div className="an-dict-mini">{dictionary.map(([key, item]) => <div key={key}><code dir="ltr">{key}</code><b>{item.label}</b><span>{item.range}</span></div>)}</div></div></div></details>;
}

function InsightCards({ data }) {
  const content = data.content || {};
  const question = data.questions || {};
  const pulse = data.pulse || {};
  const sub = data.sub || {};
  const downloads = [
    ['علوم پایه', content.bs_downloads], ['رفرنس‌ها', content.ref_downloads], ['بانک سؤال', content.qbank_downloads],
  ].filter(([, value]) => isNumber(value));
  const topDownload = downloads.length ? downloads.reduce((best, row) => row[1] > best[1] ? row : best) : null;
  const insights = [];
  if (topDownload && topDownload[1] > 0) insights.push({ icon: '📚', title: `${topDownload[0]} بیشترین دانلود تجمعی را دارد`, text: `${fa(topDownload[1])} دانلود ثبت‌شده؛ این مقایسه تجمعی است، نه محدود به بازه انتخابی.` });
  if (isNumber(question.accuracy)) insights.push({ icon: '🧠', title: `درصد پاسخ صحیح تجمعی ${fa(question.accuracy)}٪ است`, text: `بر پایه ${fa(question.total_attempts)} پاسخ ثبت‌شده برای سؤالات تأییدشده.` });
  if (pulse.peak_hour !== null && pulse.peak_hour !== undefined) insights.push({ icon: '🕐', title: `ساعت ${fa(pulse.peak_hour)} پرترافیک‌ترین ساعت ۷ روز اخیر بوده`, text: `${fa(pulse.peak_hour_count)} کنش ثبت‌شده در این ساعت.` });
  if (sub.top_plan && sub.top_plan !== '-') insights.push({ icon: '💎', title: `«${sub.top_plan}» پرتکرارترین پلن اشتراک است`, text: 'بر اساس تعداد رسیدهای تأییدشده تجمعی.' });
  if (!insights.length) return <Empty icon="💡" title="داده کافی برای بینش مدیریتی وجود ندارد" description="با ثبت فعالیت بیشتر، خلاصه‌های مبتنی بر داده در این قسمت نمایش داده می‌شوند." />;
  return <div className="an-insights">{insights.map((item, index) => <article key={index}><span aria-hidden="true">{item.icon}</span><div><b>{item.title}</b><p>{item.text}</p></div></article>)}</div>;
}

function UsersDomain({ data, technical }) {
  const users = data.users || {};
  const byIntake = Array.isArray(users.by_intake) ? users.by_intake.map(row => ({ label: row[0], value: Number(row[1]) })) : [];
  const growth = Array.isArray(users.growth_7d) ? users.growth_7d.map(row => ({ date: row[0], count: Number(row[1]) })) : [];
  return <section className="an-domain">
    <SectionHeader icon="👥" title="کاربران" description="جمعیت دانشجویان، ثبت‌نام و آخرین فعالیت ثبت‌شده" />
    <div className="an-metric-grid"><MetricCard domain="users" metricKey="total_approved" value={users.total_approved} icon="👥" /><MetricCard domain="users" metricKey="active_today" value={users.active_today} icon="📡" /><MetricCard domain="users" metricKey="new_week" value={users.new_week} icon="🆕" /><MetricCard domain="users" metricKey="total_pending" value={users.total_pending} icon="⏳" tone={users.total_pending > 0 ? 'warning' : ''} /></div>
    <div className="an-chart-grid"><DailyChart title="ثبت‌نام دانشجویان تأییدشده در ۷ روز اخیر" purpose="در هر روز چند ثبت‌نام تأییدشده ایجاد شده است؟" rows={growth} unit="ثبت‌نام" note="این سری فقط کاربران تأییدشده را شامل می‌شود" /><SemanticBars title="توزیع دانشجویان بر اساس ورودی" purpose="جمعیت تأییدشده در کدام ورودی‌ها متمرکز است؟" rows={byIntake} unit="دانشجو" /></div>
    <div className="an-metric-grid secondary"><MetricCard domain="users" metricKey="active_week" value={users.active_week} icon="🗓" /><MetricCard domain="users" metricKey="inactive_14d" value={users.inactive_14d} icon="🌙" /><MetricCard domain="users" metricKey="inactive_30d" value={users.inactive_30d} icon="🕸" /><MetricCard domain="users" metricKey="group_unset" value={users.group_unset} icon="🏷" tone={users.group_unset > 0 ? 'warning' : ''} /></div>
    {Array.isArray(users.top_users) && users.top_users.length > 0 && <div className="panel panel-pad an-table-card"><h3>دانشجویان برتر بر اساس پاسخ‌های تجمعی</h3><p className="an-purpose">این رتبه‌بندی از leaderboard واقعی و شمارنده‌های پاسخ ساخته شده است.</p><table className="an-data-table"><thead><tr><th>دانشجو</th><th>پاسخ</th><th>صحیح</th><th>دقت</th><th></th></tr></thead><tbody>{users.top_users.map(row => <tr key={row.user_id}><td>{row.name}</td><td>{fa(row.total_answers)}</td><td>{fa(row.correct_answers)}</td><td>{fa(row.accuracy)}٪</td><td><a href={`#/users?q=${row.user_id}`}>مشاهده</a></td></tr>)}</tbody></table></div>}
    {technical && <RawDetails title="کاربران" domain="users" data={users} />}
  </section>;
}

function LearningDomain({ data, examState, technical, onRetryExams }) {
  const questions = data.questions || {};
  const difficulties = Object.entries(questions.by_difficulty || {}).map(([label, value]) => ({ label, value: Number(value) }));
  const topLessons = (questions.top_lessons || []).map(row => ({ label: row[0], value: Number(row[1]) }));
  const hardest = Array.isArray(questions.hardest_questions) ? questions.hardest_questions : [];
  return <section className="an-domain">
    <SectionHeader icon="🧠" title="یادگیری، سؤال و آزمون" description="شاخص‌های واقعی بانک سؤال و پاسخ‌های تجمعی دانشجویان" />
    <div className="an-metric-grid"><MetricCard domain="questions" metricKey="total_attempts" value={questions.total_attempts} icon="✍️" /><MetricCard domain="questions" metricKey="accuracy" value={questions.accuracy} icon="🎯" /><MetricCard domain="questions" metricKey="approved" value={questions.approved} icon="✅" /><MetricCard domain="questions" metricKey="pending" value={questions.pending} icon="⏳" tone={questions.pending > 0 ? 'warning' : ''} /></div>
    <div className="an-chart-grid"><SemanticBars title="توزیع تعداد سؤال بر اساس سختی" purpose="بانک سؤال از نظر برچسب سختی چگونه توزیع شده است؟" rows={difficulties} unit="سؤال" empty="برچسب سختی برای سؤال‌ها ثبت نشده است." /><SemanticBars title="درس‌های دارای بیشترین سؤال" purpose="بیشترین پوشش بانک سؤال مربوط به کدام درس‌هاست؟" rows={topLessons} unit="سؤال" /></div>
    <div className="an-data-gap"><span aria-hidden="true">ℹ️</span><div><b>دقت پاسخ بر اساس سختی قابل محاسبه نیست</b><p>داده فعلی فقط تعداد سؤال در هر سطح سختی را می‌دهد؛ attempts/correct تفکیک‌شده بر اساس سختی در این قرارداد وجود ندارد.</p></div></div>
    <SectionHeader icon="📝" title="آزمون‌های تمرینی" description="اجراهای واقعی exam_sessions؛ میانگین دقت بر نمونه حداکثر ۵۰۰ آزمون تکمیل‌شده اخیر" action={<a className="btn" href="#/exams">مدیریت آزمون‌ها</a>} />
    {examState.loading ? <Loading rows={2} /> : examState.restricted ? <DomainFailure title="تحلیل آزمون برای نقش فعلی قابل مشاهده نیست" restricted /> : examState.error ? <DomainFailure title="تحلیل آزمون فعلاً در دسترس نیست" onRetry={onRetryExams} /> : <div className="an-metric-grid"><MetricCard domain="exams" metricKey="total_runs" value={examState.data?.total_runs} icon="▶" /><MetricCard domain="exams" metricKey="finished" value={examState.data?.finished} icon="✅" /><MetricCard domain="exams" metricKey="runs_7d" value={examState.data?.runs_7d} icon="🗓" /><MetricCard domain="exams" metricKey="avg_pct" value={examState.data?.avg_pct} icon="🎯" /></div>}
    <div className="an-chart-grid"><SemanticBars title="منبع ایجاد سؤالات تأییدشده" purpose="سؤال‌های تأییدشده توسط کاربران ساخته شده‌اند یا ربات؟" rows={[{ label: 'ارسالی کاربران', value: Number(questions.by_users || 0) }, { label: 'ساخته ربات', value: Number(questions.by_bot || 0) }]} unit="سؤال" /><div className="panel panel-pad an-table-card"><h3>سؤال‌های دارای بیشترین نرخ خطا</h3><p className="an-purpose">فقط سؤال‌های تأییدشده با حداقل ۵ تلاش؛ نرخ خطا از شمارنده‌های persisted محاسبه شده است.</p>{hardest.length ? <table className="an-data-table"><thead><tr><th>سؤال</th><th>درس / مبحث</th><th>تلاش</th><th>خطا</th></tr></thead><tbody>{hardest.map((row, index) => <tr key={index}><td>{row.question}</td><td>{row.lesson}{row.topic ? ` / ${row.topic}` : ''}</td><td>{fa(row.attempts)}</td><td><B kind={row.wrong_rate >= 70 ? 'bad' : 'warn'}>{fa(row.wrong_rate)}٪</B></td></tr>)}</tbody></table> : <Empty icon="🧪" title="داده کافی نیست" description="هر سؤال برای ورود به این فهرست حداقل ۵ تلاش نیاز دارد." />}<a className="an-drill" href="#/questions">بازبینی سؤال‌ها ←</a></div></div>
    {technical && <RawDetails title="یادگیری" domain="questions" data={questions} />}
  </section>;
}

function ContentDomain({ data, technical }) {
  const content = data.content || {};
  const bsTypes = Object.entries(content.bs_types || {}).map(([label, value]) => ({ label, value: Number(value) }));
  const refLangs = Object.entries(content.ref_langs || {}).map(([label, value]) => ({ label, value: Number(value) }));
  const qbankLessons = (content.top_qbank_lessons || []).map(row => ({ label: row[0], value: Number(row[1]) }));
  const qbankDownloads = (content.top_downloaded_qbank || []).map(row => ({ label: row[0], value: Number(row[1]) }));
  return <section className="an-domain">
    <SectionHeader icon="📚" title="محتوا" description="حجم ساختار آموزشی و مصرف تجمعی منابع ثبت‌شده" />
    <div className="an-metric-grid"><MetricCard domain="content" metricKey="bs_lessons" value={content.bs_lessons} icon="📘" /><MetricCard domain="content" metricKey="bs_sessions" value={content.bs_sessions} icon="🗂" /><MetricCard domain="content" metricKey="bs_total_content" value={content.bs_total_content} icon="📎" /><MetricCard domain="content" metricKey="new_in_range" value={data.new_resources_in_range} icon="🆕" override={{ label: 'منابع افزوده‌شده در بازه انتخابی', unit: 'فایل', range: `${fa(data.days)} روز انتخابی`, source: 'bs_content + ref_files', calculation: 'فایل‌های علوم پایه و رفرنس با uploaded_at در بازه انتخابی' }} /></div>
    <SectionHeader icon="⬇️" title="مصرف محتوا" description="شمارنده‌های دانلود تجمعی؛ فیلتر بازه زمانی روی این سه شاخص اعمال نمی‌شود" />
    <div className="an-metric-grid secondary"><MetricCard domain="content" metricKey="bs_downloads" value={content.bs_downloads} icon="📚" /><MetricCard domain="content" metricKey="ref_downloads" value={content.ref_downloads} icon="📖" /><MetricCard domain="content" metricKey="qbank_downloads" value={content.qbank_downloads} icon="🧪" /></div>
    <div className="an-chart-grid"><SemanticBars title="فایل‌های علوم پایه بر اساس نوع" purpose="ترکیب فایل‌های علوم پایه از چه نوع‌هایی تشکیل شده است؟" rows={bsTypes} unit="فایل" /><SemanticBars title="فایل‌های رفرنس بر اساس زبان" purpose="پوشش رفرنس فارسی و انگلیسی چگونه است؟" rows={refLangs} unit="فایل" /></div>
    <div className="an-chart-grid"><SemanticBars title="درس‌های پرتکرار در فایل‌های بانک سؤال" purpose="بیشترین تعداد فایل بانک سؤال مربوط به کدام درس‌هاست؟" rows={qbankLessons} unit="فایل" /><SemanticBars title="پرمصرف‌ترین فایل‌های بانک سؤال" purpose="کدام فایل‌های بانک سؤال بیشترین دانلود تجمعی را دارند؟" rows={qbankDownloads} unit="دانلود" /></div>
    {technical && <RawDetails title="محتوا" domain="content" data={content} />}
  </section>;
}

function SupportDomain({ data, technical }) {
  const tickets = data.tickets || {};
  const bundle = data.bundle || {};
  return <section className="an-domain">
    <SectionHeader icon="🎫" title="پشتیبانی" description="وضعیت فعلی صف و عملکرد حل تیکت در بازه‌های واقعی backend" />
    <div className="an-metric-grid"><MetricCard domain="tickets" metricKey="open" value={tickets.open} icon="📬" tone={tickets.open > 0 ? 'warning' : ''} /><MetricCard domain="tickets" metricKey="closed_week" value={tickets.closed_week} icon="✅" /><MetricCard domain="tickets" metricKey="new_week" value={tickets.new_week} icon="🆕" /><MetricCard domain="tickets" metricKey="avg_resolution_h" value={tickets.avg_resolution_h} icon="⏱" /></div>
    {bundle.daily?.tickets ? <DailyChart title="تیکت‌های ایجادشده در بازه انتخابی" purpose="حجم ورود تیکت در روزهای این بازه چگونه تغییر کرده است؟" rows={bundle.daily.tickets} unit="تیکت" /> : <div className="an-data-gap"><span>🔒</span><div><b>روند روزانه تیکت در دسترس نیست</b><p>این نمودار به مجوز تحلیل عمیق بازه‌ای نیاز دارد.</p></div></div>}
    <div className="an-data-gap"><span>ℹ️</span><div><b>نتیجه‌گیری خودکار درباره کاهش صف نمایش داده نمی‌شود</b><p>قرارداد فعلی روند تاریخی backlog را برنمی‌گرداند؛ فقط وضعیت فعلی، ایجاد و بسته‌شدن را نشان می‌دهد.</p></div></div>
    {technical && <RawDetails title="پشتیبانی" domain="tickets" data={tickets} />}
  </section>;
}

function FinanceDomain({ data, technical }) {
  const sub = data.sub || {};
  return <section className="an-domain">
    <SectionHeader icon="💎" title="اشتراک و مالی" description="وضعیت پلن اشتراک، رسیدها و درآمد واقعی ثبت‌شده؛ همه مبالغ به تومان" />
    <div className="an-metric-grid"><MetricCard domain="subscriptions" metricKey="active" value={sub.active} icon="💎" /><MetricCard domain="subscriptions" metricKey="pending" value={sub.pending} icon="🧾" tone={sub.pending > 0 ? 'warning' : ''} /><MetricCard domain="subscriptions" metricKey="revenue_month" value={sub.revenue_month} icon="💰" /><MetricCard domain="subscriptions" metricKey="revenue" value={sub.revenue} icon="🏦" /></div>
    <div className="an-metric-grid secondary"><MetricCard domain="subscriptions" metricKey="expired" value={sub.expired} icon="⌛" /><MetricCard domain="subscriptions" metricKey="revoked" value={sub.revoked} icon="⛔" /><MetricCard domain="subscriptions" metricKey="conv_rate" value={sub.conv_rate} icon="✅" /><MetricCard domain="subscriptions" metricKey="top_plan" value={sub.top_plan} icon="🏷" /></div>
    <div className="an-data-gap"><span>ℹ️</span><div><b>روند درآمد در قرارداد فعلی وجود ندارد</b><p>فقط درآمد تجمعی و ماه جاری از رسیدهای تأییدشده محاسبه می‌شود؛ نمودار تاریخی یا «درآمد ازدست‌رفته» ساخته نشده است.</p></div></div>
    {technical && <RawDetails title="اشتراک و مالی" domain="subscriptions" data={sub} />}
  </section>;
}

function NotificationsDomain({ data, technical }) {
  const notif = data.notif || {};
  return <section className="an-domain">
    <SectionHeader icon="🔔" title="اعلان‌ها" description="سلامت سه job خودکار بر اساس اجراهای persisted؛ هر کارت دقیقاً می‌گوید چند اجرا بررسی شده است" action={<a className="btn" href="#/notify">مشاهده مرکز اعلان‌ها</a>} />
    <div className="an-job-grid">{Object.entries(NOTIFICATION_JOBS).map(([key, meta]) => {
      const job = notif[key];
      if (!job) return <article className="an-job" key={key}><div className="an-job-head"><b>{meta.label}</b><code dir="ltr">{meta.technical}</code></div><Empty icon="📭" title="اجرایی ثبت نشده" description="برای این job در داده‌های موجود run ثبت نشده است." /></article>;
      const failed = Number(job.total_failed || 0);
      const badStatus = ['failed', 'error', 'partial'].includes(String(job.last_status || '').toLowerCase());
      const state = failed > 0 || badStatus ? 'warning' : 'ok';
      return <article className={`an-job ${state}`} key={key}>
        <div className="an-job-head"><div><b>{meta.label}</b><code dir="ltr">{meta.technical}</code></div><B kind={state === 'ok' ? 'ok' : 'warn'}>{state === 'ok' ? '✅ بدون خطا در نمونه' : '⚠️ نیازمند بررسی'}</B></div>
        <p className="an-job-context">جمع روی {fa(job.runs_checked)} اجرای اخیر؛ این بازه زمانی ثابت نیست.</p>
        <div className="an-job-values"><div><span>ارسال‌شده</span><b>{fa(job.total_sent)}</b></div><div><span>ناموفق</span><b>{fa(job.total_failed)}</b></div><div><span>آخرین اجرا</span><b dir="ltr">{job.last_at || '—'}</b></div></div>
        <p>{failed > 0 ? `${fa(failed)} ارسال ناموفق در ${fa(job.runs_checked)} اجرای بررسی‌شده ثبت شده است.` : `در ${fa(job.runs_checked)} اجرای بررسی‌شده، ارسال ناموفق ثبت نشده است.`}</p>
        <a className="an-drill" href="#/notify">مشاهده اجراها ←</a>
      </article>;
    })}</div>
    {technical && <RawDetails title="اعلان‌ها" domain="notifications" data={notif} />}
  </section>;
}

function AiDomain({ aiState, technical, onRetry }) {
  if (aiState.loading) return <Loading rows={5} />;
  if (aiState.restricted) return <DomainFailure title="تحلیل هوشیار برای نقش فعلی قابل مشاهده نیست" restricted />;
  if (aiState.error) return <DomainFailure title="اطلاعات هوشیار فعلاً در دسترس نیست" onRetry={onRetry} />;
  const ai = aiState.data || {};
  return <section className="an-domain">
    <SectionHeader icon="🤖" title="هوشیار" description="درخواست، کاربر و توکن مصرف‌شده از شمارنده‌های persisted روی کاربران" action={<a className="btn" href="#/ai">مرکز هوشیار</a>} />
    <div className="an-metric-grid"><MetricCard domain="ai" metricKey="total_today" value={ai.total_today} icon="💬" /><MetricCard domain="ai" metricKey="users_today" value={ai.users_today} icon="👥" /><MetricCard domain="ai" metricKey="tokens_today" value={ai.tokens_today} icon="◈" /><MetricCard domain="ai" metricKey="total_alltime" value={ai.total_alltime} icon="∞" /></div>
    <div className="an-chart-grid"><SemanticBars title="پرمصرف‌ترین کاربران هوشیار امروز" purpose="کدام کاربران امروز بیشترین درخواست هوشیار را ثبت کرده‌اند؟" rows={(ai.top_today_users || []).map(row => ({ label: row.name || `#${row.user_id}`, value: Number(row.count) }))} unit="درخواست" /><SemanticBars title="پرمصرف‌ترین کاربران هوشیار در کل دوره" purpose="بیشترین استفاده تجمعی هوشیار متعلق به چه کسانی است؟" rows={(ai.top_alltime_users || []).map(row => ({ label: row.name || `#${row.user_id}`, value: Number(row.count) }))} unit="درخواست" /></div>
    {technical && <RawDetails title="هوشیار" domain="ai" data={ai} />}
  </section>;
}

function OperationsDomain({ data, systemState, technical, onRetry }) {
  const pulse = data.pulse || {};
  return <section className="an-domain">
    <SectionHeader icon="⚙️" title="عملیات و سلامت سیستم" description="کنش‌های persisted سامانه و وضعیت سرویس‌های عملیاتی؛ جدا از تحلیل کسب‌وکار" action={<a className="btn" href="#/system">مرکز سلامت سیستم</a>} />
    <div className="an-metric-grid"><MetricCard domain="pulse" metricKey="total_actions_week" value={pulse.total_actions_week} icon="⚡" /><MetricCard domain="pulse" metricKey="peak_hour" value={pulse.peak_hour} icon="🕐" override={{ unit: 'ساعت' }} /><MetricCard domain="pulse" metricKey="peak_hour_count" value={pulse.peak_hour_count} icon="📡" /></div>
    {systemState.loading ? <Loading rows={3} /> : systemState.restricted ? <DomainFailure title="وضعیت فنی برای نقش فعلی قابل مشاهده نیست" restricted /> : systemState.error ? <DomainFailure title="وضعیت عملیاتی فعلاً در دسترس نیست" onRetry={onRetry} /> : systemState.data && <div className="an-health-grid">{[
      ['API', systemState.data.api_ok], ['ربات', systemState.data.bot_ok], ['پایگاه داده', systemState.data.db_ok],
    ].map(([label, ok]) => <div className={`an-health ${ok ? 'ok' : 'bad'}`} key={label}><span>{ok ? '●' : '●'}</span><b>{label}</b><small>{ok ? 'پاسخ‌گو' : 'نیازمند بررسی'}</small></div>)}{isNumber(systemState.data.db_ping_ms) && <div className="an-health"><span>◷</span><b>پاسخ پایگاه داده</b><small>{fa(systemState.data.db_ping_ms)} میلی‌ثانیه · اندازه‌گیری آخرین بررسی</small></div>}</div>}
    {technical && <RawDetails title="عملیات" domain="pulse" data={{ pulse, system: systemState.data }} />}
  </section>;
}

function Overview({ data, compareEnabled, aiState, attention, insightsState, reloadInsights, technical }) {
  const bundle = data.bundle || {};
  const comparisons = bundle.comparison || {};
  const questions = data.questions || {};
  const content = data.content || {};
  const tickets = data.tickets || {};
  const sub = data.sub || {};
  const notifFailed = Object.values(data.notif || {}).filter(Boolean).reduce((sum, job) => sum + Number(job.total_failed || 0), 0);
  const active = bundle.kpis?.active_users ?? data.active_today;
  const activeDefinition = bundle.kpis ? { label: 'کاربران فعال در بازه انتخابی', unit: 'نفر', range: `${fa(bundle.days)} روز انتخابی`, source: 'stats.user_id/timestamp', calculation: 'تعداد user_id یکتای دارای رویداد persisted در بازه' } : undefined;
  return <section className="an-domain overview">
    <AttentionPanel items={attention} loading={insightsState.loading} error={insightsState.error} onRetry={reloadInsights} />
    <SectionHeader icon="📊" title="خلاصه مدیریتی" description="مهم‌ترین وضعیت‌های قابل اتکا؛ زمان هر شاخص روی همان کارت نوشته شده است" />
    <div className="an-executive-grid">
      <MetricCard domain="users" metricKey="active_today" value={active} icon="👥" override={activeDefinition} comparison={comparisons.active_users ? { ...comparisons.active_users, days: bundle.days } : null} compareEnabled={compareEnabled && Boolean(bundle.kpis)} />
      <MetricCard domain="questions" metricKey="total_attempts" value={questions.total_attempts} icon="🧠" />
      <MetricCard domain="content" metricKey="bs_downloads" value={Number(content.bs_downloads || 0) + Number(content.ref_downloads || 0)} icon="📚" override={{ label: 'کل دانلود منابع آموزشی', unit: 'دانلود', range: 'تجمعی در دو دامنه فایل', source: 'bs_content + ref_files', calculation: 'جمع دانلود علوم پایه و رفرنس‌ها' }} />
      <MetricCard domain="tickets" metricKey="open" value={tickets.open} icon="🎫" tone={tickets.open > 0 ? 'warning' : ''} />
      <MetricCard domain="subscriptions" metricKey="active" value={sub.active} icon="💎" />
      <MetricCard domain="subscriptions" metricKey="pending" value={sub.pending} icon="🧾" tone={sub.pending > 0 ? 'warning' : ''} />
      <MetricCard domain="notifications" metricKey="failed_recent" value={notifFailed} icon="🔔" tone={notifFailed > 0 ? 'danger' : ''} override={{ label: 'ارسال‌های ناموفق در نمونه اجراها', unit: 'ارسال', range: 'جمع حداکثر ۱۰ اجرای اخیر هر job', source: 'notif_runs.failed', calculation: 'جمع total_failed سه job اعلان خودکار' }} action="/notify" />
      {aiState.data ? <MetricCard domain="ai" metricKey="total_today" value={aiState.data.total_today} icon="🤖" /> : <article className="an-metric muted-card"><div className="an-metric-head"><span>🤖</span><span>هوشیار</span></div><div className="an-metric-context">{aiState.restricted ? 'مجوز تحلیل هوشیار در نقش فعلی موجود نیست' : aiState.error ? 'اطلاعات هوشیار فعلاً در دسترس نیست' : 'در حال بارگذاری اطلاعات هوشیار…'}</div></article>}
    </div>
    <SectionHeader icon="📈" title="روندهای مهم" description="فقط سری‌هایی که واقعاً برای بازه انتخابی در backend محاسبه شده‌اند" />
    {bundle.daily ? <><div className="an-chart-grid"><DailyChart title="کنش‌های ثبت‌شده روزانه" purpose="تعامل ثبت‌شده کاربران در روزهای بازه چگونه تغییر کرده است؟" rows={bundle.daily.activity} unit="کنش" /><DailyChart title="ثبت‌نام روزانه" purpose="چند ثبت‌نام جدید در هر روز بازه ایجاد شده است؟" rows={bundle.daily.users} unit="ثبت‌نام" /></div><div className="an-chart-grid"><SemanticBars title="پرکاربردترین عملیات" purpose="کاربران در این بازه بیشتر چه کنش‌هایی ثبت کرده‌اند؟" rows={(bundle.top_actions || []).map(row => ({ label: ACTION_LABELS[row.action] || 'سایر رویدادهای ثبت‌شده', value: Number(row.count) }))} unit="کنش" /><SemanticBars title="فعالیت بر اساس ساعت" purpose="رویدادهای بازه در چه ساعت‌هایی بیشتر ثبت شده‌اند؟" rows={(bundle.hourly || []).map(row => ({ label: `ساعت ${fa(row.hour)}`, value: Number(row.count) }))} unit="کنش" /></div></> : <div className="an-data-gap"><span>🔒</span><div><b>روند بازه‌ای در دسترس نیست</b><p>مجوز stats.deep برای سری روزانه و مقایسه دوره قبل لازم است. شاخص‌های snapshot بالا همچنان واقعی و قابل استفاده‌اند.</p></div></div>}
    <SectionHeader icon="💡" title="بینش مدیریتی" description="خلاصه‌های deterministic از داده واقعی؛ بدون تولید یا حدس LLM" />
    <InsightCards data={data} />
    {technical && <RawDetails title="نمای کلی" domain="pulse" data={data} />}
  </section>;
}

const insightAction = action => ({
  'admin:pending': '/users?status=pending', 'ticket:manage': '/tickets?status=open',
  'admin:stats_questions': '/questions', 'admin:cat_users': '/users',
  'admin:cat_content': '/content', 'report:manage:all': '/content?tab=reports',
  'admin:stats_users': '/analytics?tab=users',
}[action] || '');

export default function Analytics({ route = '', me }) {
  const params = new URLSearchParams(route.split('?')[1] || '');
  const requestedTab = TABS.some(([key]) => key === params.get('tab')) ? params.get('tab') : 'overview';
  const [tab, setTab] = useState(requestedTab);
  const [mode, setMode] = useState(params.get('mode') === 'operations' ? 'operations' : 'executive');
  const [days, setDays] = useState(Math.max(1, Math.min(90, Number(params.get('days')) || 7)));
  const [customDays, setCustomDays] = useState(14);
  const [compare, setCompare] = useState(params.get('compare') === 'none' ? 'none' : 'previous');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [permissionError, setPermissionError] = useState(false);
  const [insightsState, setInsightsState] = useState({ loading: true, error: '', data: null });
  const [aiState, setAiState] = useState({ loading: false, error: '', restricted: false, data: null });
  const [examState, setExamState] = useState({ loading: false, error: '', restricted: false, data: null });
  const [systemState, setSystemState] = useState({ loading: false, error: '', restricted: false, data: null });
  const requestSeq = useRef(0);

  const can = permission => Boolean(me?.is_owner || (me?.perms || []).includes(permission));

  const loadInsights = async () => {
    setInsightsState(previous => ({ ...previous, loading: true, error: '' }));
    try { setInsightsState({ loading: false, error: '', data: await api.waInsights() }); }
    catch (requestError) { setInsightsState({ loading: false, error: errText(requestError), data: null }); }
  };

  const loadAi = async () => {
    if (!can('ai.manage')) { setAiState({ loading: false, error: '', restricted: true, data: null }); return; }
    setAiState(previous => ({ ...previous, loading: true, error: '', restricted: false }));
    try { setAiState({ loading: false, error: '', restricted: false, data: await api.aiStats() }); }
    catch (requestError) { setAiState({ loading: false, error: errText(requestError), restricted: requestError.status === 403, data: null }); }
  };

  const loadExams = async () => {
    if (!can('schedules.manage')) { setExamState({ loading: false, error: '', restricted: true, data: null }); return; }
    setExamState(previous => ({ ...previous, loading: true, error: '', restricted: false }));
    try { setExamState({ loading: false, error: '', restricted: false, data: await api.examStats() }); }
    catch (requestError) { setExamState({ loading: false, error: errText(requestError), restricted: requestError.status === 403, data: null }); }
  };

  const loadSystem = async () => {
    if (!can('system.manage')) { setSystemState({ loading: false, error: '', restricted: true, data: null }); return; }
    setSystemState(previous => ({ ...previous, loading: true, error: '', restricted: false }));
    try { setSystemState({ loading: false, error: '', restricted: false, data: await api.botStatus() }); }
    catch (requestError) { setSystemState({ loading: false, error: errText(requestError), restricted: requestError.status === 403, data: null }); }
  };

  const load = async (selectedDays = days) => {
    const seq = ++requestSeq.current;
    setLoading(true); setError(''); setPermissionError(false);
    try {
      let response;
      try { response = await api.waAnalytics(selectedDays); }
      catch (requestError) {
        if (requestError.status !== 403) throw requestError;
        try {
          const legacyBundle = await api.analytics(selectedDays);
          response = { days: selectedDays, deep: true, bundle: legacyBundle, generated_at: legacyBundle.generated_at, domain_status: { bundle: { ok: true } } };
        } catch { setPermissionError(true); return; }
      }
      if (seq === requestSeq.current) setData(response);
    } catch (requestError) { if (seq === requestSeq.current) setError(errText(requestError)); }
    finally { if (seq === requestSeq.current) setLoading(false); }
  };

  useEffect(() => { load(days); }, [days]);
  useEffect(() => { loadInsights(); loadAi(); }, []);
  useEffect(() => { if (tab === 'operations' && !systemState.data && !systemState.loading && !systemState.restricted) loadSystem(); }, [tab]);
  useEffect(() => { if (tab === 'learning' && !examState.data && !examState.loading && !examState.restricted) loadExams(); }, [tab]);
  useEffect(() => { setTab(requestedTab); }, [requestedTab]);
  useEffect(() => { writeHashQuery('/analytics', { tab: tab !== 'overview' ? tab : '', mode: mode !== 'executive' ? mode : '', days: days !== 7 ? days : '', compare: compare === 'none' ? 'none' : '' }); }, [tab, mode, days, compare]);
  useEffect(() => () => { requestSeq.current += 1; }, []);

  if (permissionError) return <NoPerm text="تحلیل‌ها نیازمند مجوز «آمار و داشبورد مدیریتی» (stats.view) است" />;

  const domainFailed = key => data?.domain_status?.[key]?.ok === false && data?.domain_status?.[key]?.error === 'temporarily_unavailable';
  const attention = useMemo(() => {
    const items = (insightsState.data?.alerts || []).map((item, index) => ({ id: `insight-${index}-${item.action}`, icon: item.icon, title: item.title, detail: item.detail, href: insightAction(item.action), severity: 'warning' }));
    const present = new Set(items.map(item => item.href));
    const sub = data?.sub || {};
    const questions = data?.questions || {};
    const failed = Object.values(data?.notif || {}).filter(Boolean).reduce((sum, job) => sum + Number(job.total_failed || 0), 0);
    if (Number(sub.pending) > 0 && !present.has('/subscriptions?tab=payments&status=pending')) items.push({ id: 'pending-payments', icon: '🧾', title: `${fa(sub.pending)} پرداخت در انتظار بررسی است`, detail: 'وضعیت فعلی صف رسیدهای اشتراک هامزیار', href: '/subscriptions?tab=payments&status=pending', severity: 'warning' });
    if (Number(questions.pending) > 0 && !present.has('/questions?status=pending')) items.push({ id: 'pending-questions', icon: '🧪', title: `${fa(questions.pending)} سؤال در انتظار بازبینی است`, detail: 'بر اساس وضعیت فعلی بانک سؤال', href: '/questions?status=pending', severity: 'warning' });
    if (failed > 0) items.push({ id: 'notification-failures', icon: '🔔', title: `${fa(failed)} ارسال ناموفق در نمونه اجراهای اعلان ثبت شده است`, detail: 'جمع حداکثر ۱۰ اجرای اخیر هر job؛ بازه زمانی ثابت نیست', href: '/notify', severity: 'danger' });
    return items;
  }, [data, insightsState.data]);

  const updatedAt = data?.generated_at || data?.bundle?.generated_at;
  const exportCurrent = () => {
    const rows = [];
    for (const [domain, values] of Object.entries({ users: data?.users, content: data?.content, questions: data?.questions, exams: examState.data, tickets: data?.tickets, subscriptions: data?.sub, pulse: data?.pulse, ai: aiState.data })) {
      for (const [key, value] of Object.entries(values || {})) {
        if (typeof value !== 'number' && typeof value !== 'string') continue;
        const definition = metricDefinition(domain, key);
        rows.push({ domain, key, label: definition.label, value, unit: definition.unit, range: definition.range, source: definition.source, storage: definition.storage || 'محاسبه زنده روی داده‌های persisted', calculation: definition.calculation });
      }
    }
    exportCSV(`humsyar-analytics-${fileDateStamp()}.csv`, [
      { label: 'دامنه', v: 'domain' }, { label: 'کلید فنی', v: 'key' }, { label: 'عنوان انسانی', v: 'label' },
      { label: 'مقدار', v: 'value' }, { label: 'واحد', v: 'unit' }, { label: 'بازه', v: 'range' },
      { label: 'منبع', v: 'source' }, { label: 'روش داده', v: 'storage' }, { label: 'محاسبه', v: 'calculation' },
    ], rows);
  };

  const technical = mode === 'operations' && Boolean(me?.is_owner);
  const rangeControls = <div className="an-header-actions">
    <div className="an-range" role="group" aria-label="بازه تحلیل">{RANGES.map(([value, label]) => <button key={value} className={`btn sm ${days === value ? 'primary' : ''}`} aria-pressed={days === value} onClick={() => setDays(value)}>{label}</button>)}<label><span>روز سفارشی</span><input className="inp" type="number" min="1" max="90" value={customDays} onChange={event => setCustomDays(Math.max(1, Math.min(90, Number(event.target.value) || 1)))} /><button className="btn sm" onClick={() => setDays(customDays)}>اعمال</button></label></div>
    <label className="an-compare-select"><span>مقایسه با</span><select className="inp" value={compare} onChange={event => setCompare(event.target.value)}><option value="previous">دوره قبل هم‌اندازه</option><option value="none">بدون مقایسه</option></select></label>
    <button className="btn" onClick={() => { load(days); loadInsights(); loadAi(); if (tab === 'learning') loadExams(); if (tab === 'operations') loadSystem(); }} disabled={loading}>↻ تازه‌سازی</button>
    <button className="btn" onClick={exportCurrent} disabled={!data}>⬇ خروجی CSV</button>
  </div>;

  return <div className="analytics-center">
    <PageHeader title="مرکز تحلیل و هوش مدیریتی هامزیار" description="وضعیت کاربران، یادگیری، محتوا، پشتیبانی، اشتراک هامزیار، اعلان‌ها و عملکرد عملیاتی سیستم" actions={rangeControls} />
    <div className="an-meta"><span>دامنه داده: {data?.scope?.label || 'کل سامانه'}</span><span>·</span><span>بازه انتخابی: {fa(days)} روز اخیر</span><span>·</span><span>{compare === 'previous' ? `مقایسه با ${fa(days)} روز قبل` : 'بدون مقایسه'}</span><span>·</span><span>آخرین بروزرسانی: {updatedAt ? <FaDateTime value={updatedAt} /> : loading ? 'در حال دریافت…' : 'زمان ثبت نشده'}</span></div>
    <div className="an-range-note">بازه انتخابی روی روندها، مقایسه دوره‌ای و «منابع جدید در بازه» اعمال می‌شود؛ KPIهای snapshot یا تجمعی، بازه مستقل خود را روی کارت اعلام می‌کنند.</div>
    <SavedViews scope="analytics" filters={{ days, tab, mode, compare }} onApply={filters => { setDays(Number(filters.days) || 7); setTab(filters.tab || 'overview'); setMode(filters.mode || 'executive'); setCompare(filters.compare || 'previous'); }} label="نماهای تحلیلی" />
    <div className="an-nav-row"><div className="an-mode" role="group" aria-label="نوع نمای تحلیل"><button className={mode === 'executive' ? 'on' : ''} aria-pressed={mode === 'executive'} onClick={() => setMode('executive')}>نمای مدیریتی</button><button className={mode === 'operations' ? 'on' : ''} aria-pressed={mode === 'operations'} onClick={() => setMode('operations')}>نمای عملیاتی</button></div><div className="an-tabs" role="tablist" aria-label="دامنه‌های تحلیل">{TABS.map(([key, label, icon]) => <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? 'on' : ''} onClick={() => setTab(key)}><span aria-hidden="true">{icon}</span>{label}</button>)}</div></div>
    {mode === 'operations' && <div className="an-operations-note">نمای عملیاتی فعال است: قرارداد خام و واژه‌نامه فنی هر دامنه برای مالک سامانه در انتهای همان بخش نمایش داده می‌شود.</div>}
    {error ? <ErrorState error={error} title="داده‌های اصلی Analytics بارگذاری نشد" onRetry={() => load(days)} /> : !data ? <div className="an-loading"><Loading rows={6} /></div> : <>
      {tab === 'overview' && <Overview data={data} compareEnabled={compare === 'previous'} aiState={aiState} attention={attention} insightsState={insightsState} reloadInsights={loadInsights} technical={technical} />}
      {tab === 'users' && (domainFailed('users') ? <DomainFailure title="تحلیل کاربران فعلاً در دسترس نیست" onRetry={() => load(days)} /> : <UsersDomain data={data} technical={technical} />)}
      {tab === 'learning' && (domainFailed('questions') ? <DomainFailure title="تحلیل یادگیری فعلاً در دسترس نیست" onRetry={() => load(days)} /> : <LearningDomain data={data} examState={examState} technical={technical} onRetryExams={loadExams} />)}
      {tab === 'content' && (domainFailed('content') ? <DomainFailure title="تحلیل محتوا فعلاً در دسترس نیست" onRetry={() => load(days)} /> : <ContentDomain data={data} technical={technical} />)}
      {tab === 'support' && (domainFailed('tickets') ? <DomainFailure title="تحلیل پشتیبانی فعلاً در دسترس نیست" onRetry={() => load(days)} /> : <SupportDomain data={data} technical={technical} />)}
      {tab === 'finance' && (domainFailed('sub') ? <DomainFailure title="تحلیل اشتراک و مالی فعلاً در دسترس نیست" onRetry={() => load(days)} /> : <FinanceDomain data={data} technical={technical} />)}
      {tab === 'notifications' && (domainFailed('notif') ? <DomainFailure title="تحلیل اعلان‌ها فعلاً در دسترس نیست" onRetry={() => load(days)} /> : <NotificationsDomain data={data} technical={technical} />)}
      {tab === 'ai' && <AiDomain aiState={aiState} technical={technical} onRetry={loadAi} />}
      {tab === 'operations' && <OperationsDomain data={data} systemState={systemState} technical={technical} onRetry={loadSystem} />}
    </>}
    {me?.is_owner && <details className="an-dictionary panel panel-pad"><summary>📖 واژه‌نامه کامل Analytics</summary><p>تعریف انسانی، منبع، محاسبه، واحد و بازه تمام شاخص‌هایی که در UI مصرف می‌شوند.</p><div className="tbl-wrap"><table className="an-data-table"><thead><tr><th>دامنه</th><th>کلید فنی</th><th>عنوان انسانی</th><th>واحد</th><th>بازه</th><th>منبع</th></tr></thead><tbody>{flattenDictionary().map(row => <tr key={`${row.domain}-${row.key}`}><td>{row.domain}</td><td><code dir="ltr">{row.key}</code></td><td>{row.label}</td><td>{row.unit}</td><td>{row.range}</td><td><code dir="ltr">{row.source}</code></td></tr>)}</tbody></table></div></details>}
  </div>;
}
