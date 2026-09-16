import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { api, errText } from '../api.js';
import { B, Empty, ErrorState, FaDateTime, KpiCard, KpiGrid, Loading, PageHeader, toast } from '../ui.jsx';

/* ─────────────────────────────────────────────────────────────
   🌊 WA21 — مرکز اقدام (Action Center)

   چرا این صفحه: `/api/web-admin/attention` از قبل وجود داشت و permission-aware
   هم بود، ولی در UI فقط به یک badge روی 🔔 تبدیل می‌شد
   (`app.jsx` → `setAttention(sum of counts)`). یعنی موتور Action Center بود،
   خودِ Action Center نه. این صفحه همان موتور را به محصول تبدیل می‌کند.

   هیچ منبع داده‌ی جدیدی ساخته نشده: همه‌ی شمارش‌ها از کالکشن‌های موجود
   (users, questions, tickets, sub_payments, content_reports, notif_runs,
   bot_notifications, question_import_jobs) و از `_quality_summary` می‌آیند.

   طراحی: فقط از کلاس‌های موجود استفاده می‌کند (`panel`, `panel-pad`,
   `panel--attention`, `operation-card`, `operation-icon`, `operation-body`,
   `grid g2`). عمداً کلاس CSS جدید اضافه نشده تا زبان بصری Admin نشکند.
   ───────────────────────────────────────────────────────────── */

const fa = (n) => Number(n ?? 0).toLocaleString('fa-IR');

const SEVERITY = {
  critical: { label: 'بحرانی', tone: 'bad', border: 'var(--c-bad)' },
  warning: { label: 'نیازمند بررسی', tone: 'warn', border: 'var(--c-warn)' },
  info: { label: 'اطلاع', tone: 'acc', border: 'var(--c-acc)' },
};

const GROUPS = [
  { key: 'critical', title: 'بحرانی — اول این‌ها' },
  { key: 'warning', title: 'نیازمند اقدام' },
  { key: 'info', title: 'در جریان' },
];

const badgeFor = (item) => {
  const d = item.detail;
  if (!d) return null;
  const parts = [];
  if (d.critical) parts.push(`${fa(d.critical)} بحرانی`);
  if (d.warning) parts.push(`${fa(d.warning)} هشدار`);
  if (d.info) parts.push(`${fa(d.info)} اطلاع`);
  return parts.join(' · ');
};

export default function Actions({ go }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const [onlyOpen, setOnlyOpen] = useState(true);

  const load = useCallback(() => {
    setErr('');
    api.attention().then(setData).catch((e) => setErr(errText(e)));
  }, []);
  useEffect(load, [load]);

  const items = data?.items || [];
  const grouped = useMemo(() => {
    const rows = onlyOpen ? items.filter((i) => i.count > 0) : items;
    return GROUPS.map((g) => ({
      ...g,
      items: rows.filter((i) => (i.severity || 'info') === g.key),
    })).filter((g) => g.items.length);
  }, [items, onlyOpen]);

  const openCount = items.reduce((a, i) => a + (i.count > 0 ? 1 : 0), 0);
  const totalCount = items.reduce((a, i) => a + Number(i.count || 0), 0);
  const criticalCount = items
    .filter((i) => i.severity === 'critical')
    .reduce((a, i) => a + Number(i.count || 0), 0);

  if (err) return <ErrorState title="مرکز اقدام بارگذاری نشد" error={err} onRetry={load} />;
  if (!data) return <><PageHeader title="مرکز اقدام" description="در حال خواندن صف‌های واقعی سامانه" /><Loading rows={6} /></>;

  return <>
    <PageHeader
      title="🎯 مرکز اقدام"
      description="همه‌ی صف‌هایی که همین لحظه نیاز به اقدام دارند — از داده‌ی واقعی سامانه، بدون task ساختگی"
      actions={<>
        <button className={`btn sm${onlyOpen ? ' primary' : ''}`} onClick={() => setOnlyOpen((v) => !v)}>
          {onlyOpen ? 'فقط موارد باز' : 'نمایش همه'}
        </button>
        <button className="btn sm" onClick={load}>🔄 تازه‌سازی</button>
      </>}
    />

    <KpiGrid>
      <KpiCard icon="🎯" label="صف فعال" value={fa(openCount)} hint={`${fa(items.length)} صف پایش‌شده`} />
      <KpiCard icon="📚" label="کل موارد" value={fa(totalCount)} hint="مجموع آیتم‌های باز" />
      <KpiCard icon="⛔" label="بحرانی" value={fa(criticalCount)} tone={criticalCount ? 'bad' : 'ok'}
        hint={criticalCount ? 'نیازمند اقدام فوری' : 'مورد بحرانی نیست'} />
    </KpiGrid>

    {data.checked_at && <div className="muted" style={{ marginBottom: 12 }}>
      آخرین بررسی: <FaDateTime value={data.checked_at} />
    </div>}

    {!grouped.length && <Empty icon="✅" text={onlyOpen
      ? 'هیچ مورد بازی وجود ندارد — همه‌ی صف‌ها خالی‌اند'
      : 'هیچ صفی تعریف نشده است'} />}

    {grouped.map((group) => <section key={group.key} style={{ marginBottom: 18 }}>
      <h3 className="section-title">{group.title} <B kind={SEVERITY[group.key].tone}>{fa(group.items.length)}</B></h3>
      <div className="grid g2">
        {group.items.map((item) => <ActionCard key={item.key} item={item} go={go} onActed={load} />)}
      </div>
    </section>)}
  </>;
}

function ActionCard({ item, go, onActed }) {
  const [busy, setBusy] = useState(false);
  const sev = SEVERITY[item.severity] || SEVERITY.info;
  const detail = badgeFor(item);

  // «اقدام» برای کارت‌هایی که اکشن مستقیم و امن دارند؛ بقیه فقط Review.
  // عمداً همه‌ی کارت‌ها اکشن مخرب ندارند — حذف/تصمیم انسانی در صفحه‌ی مقصد است.
  const action = ACTIONS[item.key];

  const run = async () => {
    if (!action) return;
    setBusy(true);
    try {
      const r = await action.run(item);
      toast(action.done(r), 'ok');
      onActed?.();
    } catch (e) {
      toast(errText(e), 'bad');
    } finally {
      setBusy(false);
    }
  };

  return <div
    className={`panel panel-pad operation-card${item.count ? ' panel--attention' : ''}`}
    style={{ borderColor: item.count ? sev.border : undefined, cursor: 'default' }}
  >
    <span className="operation-icon" aria-hidden="true">{item.icon}</span>
    <span className="operation-body">
      <b>{item.label}</b>
      <span className="muted">
        {detail || (item.timestamp ? <FaDateTime value={item.timestamp} /> : 'زمان رویداد در منبع ثبت نشده')}
      </span>
      {/* `.action-row` در styles.css نیست؛ عمداً inline تا کلاس مرده نسازیم */}
      <span style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <button className="btn sm" onClick={() => go?.(item.go)} title={item.go}>
          بررسی <span aria-hidden="true">‹</span>
        </button>
        {action && <button className="btn sm" disabled={busy || !item.count} onClick={run}>
          {busy ? '…' : action.label}
        </button>}
      </span>
    </span>
    <B kind={item.count ? sev.tone : 'ok'}>{fa(item.count)}</B>
  </div>;
}

/* اکشن‌های مستقیم — فقط آن‌هایی که بک‌اندِ موجود و امن دارند.
   هر سه مورد پایین پیش‌تر تست شده‌اند و audit ثبت می‌کنند. */
const ACTIONS = {
  dlq: {
    label: '♻️ بازپخش همه',
    run: () => api.dlqRequeue({ all_dead: true }),
    done: (r) => `بازپخش شد: ${fa(r.requeued ?? 0)} پیام`,
  },
  failed_jobs: {
    label: '↻ تلاش مجدد',
    run: async () => {
      // `/notif/runs` کلید `id` برمی‌گرداند (web_admin.py: `{"runs": [{"id": ...}]}`)؛
      // اولین اجرای شکست‌خورده retry می‌شود.
      const r = await api.notifRuns();
      const failed = (r.runs || []).find((x) => Number(x.failed || 0) > 0);
      if (!failed) throw new Error('اجرای شکست‌خورده‌ای برای تلاش مجدد پیدا نشد');
      return api.notifRetry(failed.id);
    },
    done: () => 'تلاش مجدد زمان‌بندی شد',
  },
  // کارت data_quality عمداً اکشن مستقیم ندارد: اصلاح هر ناهنجاری یک تصمیم
  // دامنه‌ای جداست که در مرکز کیفیت (با تأیید) انجام می‌شود، نه روی کارت.
};
