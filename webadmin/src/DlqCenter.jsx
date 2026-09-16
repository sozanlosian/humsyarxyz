import React, { useCallback, useEffect, useState } from 'react';
import { api, errText } from './api.js';
import { B, Confirm, DataTable, ErrorState, FaDateTime, Loading, SectionHeader, toast } from './ui.jsx';

const fa = (n) => Number(n ?? 0).toLocaleString('fa-IR');

/**
 * 💀 مرکز پیام‌های مرده (DLQ)
 *
 * چرا وجود دارد: مصرف‌کننده‌ی صف در bot.py پس از ۴ تلاش ناموفق، سند را
 * `status="dead"` و `sent=True` می‌کند. آن `sent=True` باعث می‌شود پیام از
 * شمارش «در صف» بیرون بیفتد در حالی که هرگز تحویل نشده — یعنی پیام بی‌صدا
 * گم می‌شد. این صفحه همان اسناد را قابل دیدن و بازپخش می‌کند.
 *
 * فقط با مجوز system.manage اکشن نشان داده می‌شود؛ خواندن با
 * notifications.manage هم ممکن است (همان قرارداد بک‌اند).
 */
export default function DlqCenter({ canManage = false }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const [page, setPage] = useState(1);
  const [sel, setSel] = useState([]);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(null);

  const load = useCallback(() => {
    setErr('');
    api.dlqList(page)
      .then((r) => { setData(r); setSel([]); })
      .catch((e) => setErr(errText(e)));
  }, [page]);
  useEffect(load, [load]);

  const act = async (kind, body, label) => {
    setBusy(true);
    try {
      const r = await api[kind === 'requeue' ? 'dlqRequeue' : 'dlqDiscard'](body);
      const n = r.requeued ?? r.discarded ?? 0;
      toast(`${label}: ${fa(n)} پیام`, n ? 'ok' : 'warn');
      load();
    } catch (e) {
      toast(errText(e), 'bad');
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  };

  if (err) return <ErrorState msg={err} onRetry={load} />;
  if (!data) return <Loading rows={3} />;

  const items = data.items || [];
  const empty = !items.length && page === 1;

  return (
    <div className="panel panel-pad" style={{ marginTop: 14 }}>
      <SectionHeader
        title="💀 پیام‌های مرده (DLQ)"
        description="پیام‌هایی که پس از سقف تلاش تحویل نشدند. اینها در شمارش «در صف» دیده نمی‌شوند."
        actions={<>
          <B kind={data.total ? 'bad' : 'ok'}>{fa(data.total)} مورد</B>
          <button className="btn sm" onClick={load} disabled={busy}>↻ تازه‌سازی</button>
        </>}
      />

      {empty ? (
        <div className="muted" style={{ marginTop: 10 }}>
          ✅ هیچ پیام مرده‌ای نیست — همه‌ی پیام‌ها یا تحویل شده‌اند یا هنوز در صف‌اند.
        </div>
      ) : (
        <>
          {canManage && (
            <div className="row" style={{ gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
              <B>{fa(sel.length)} انتخاب‌شده</B>
              <button className="btn sm" disabled={!sel.length || busy}
                onClick={() => act('requeue', { ids: sel }, 'بازپخش شد')}>
                ↻ بازپخش انتخاب‌شده‌ها
              </button>
              <button className="btn sm danger" disabled={!sel.length || busy}
                onClick={() => setConfirm('discard-sel')}>
                🗑 کنارگذاشتن انتخاب‌شده‌ها
              </button>
              <span className="spacer" />
              <button className="btn sm" disabled={busy} onClick={() => setConfirm('requeue-all')}>
                ↻ بازپخش همه
              </button>
            </div>
          )}

          <div style={{ marginTop: 10 }}>
            <DataTable
              rows={items}
              rowKey="id"
              selectable={canManage}
              onSelect={setSel}
              columns={[
                { k: 'user_id', label: 'کاربر', render: (r) => <span className="code">#{fa(r.user_id)}</span> },
                { k: 'text', label: 'متن', render: (r) => <span className="text-truncate" title={r.text}>{r.text || '—'}</span> },
                { k: 'attempts', label: 'تلاش', render: (r) => <B kind="bad">{fa(r.attempts)}</B> },
                { k: 'error', label: 'خطا', render: (r) => <span className="muted code" title={r.error}>{(r.error || '—').slice(0, 60)}</span> },
                { k: 'died_at', label: 'زمان مرگ', render: (r) => <FaDateTime value={r.died_at} /> },
              ]}
              colToggle
            />
          </div>

          {data.pages > 1 && (
            <div className="row" style={{ gap: 6, marginTop: 10 }}>
              <button className="btn sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>قبلی</button>
              <span className="muted">صفحه {fa(page)} از {fa(data.pages)}</span>
              <button className="btn sm" disabled={page >= data.pages} onClick={() => setPage((p) => p + 1)}>بعدی</button>
            </div>
          )}
        </>
      )}

      {confirm === 'requeue-all' && (
        <Confirm
          text={`بازپخش همه‌ی پیام‌های مرده (حداکثر ۵۰۰ مورد در هر بار)؟ شمارنده‌ی تلاش صفر می‌شود و پیام‌ها دوباره به تلگرام ارسال خواهند شد.`}
          onYes={() => act('requeue', { all_dead: true }, 'بازپخش شد')}
          onNo={() => setConfirm(null)}
        />
      )}
      {confirm === 'discard-sel' && (
        <Confirm
          text={`کنارگذاشتن ${fa(sel.length)} پیام؟ سند حذف نمی‌شود و برای بررسی بعدی می‌ماند، ولی دیگر ارسال نخواهد شد. در حسابرسی با شدت HIGH ثبت می‌شود.`}
          onYes={() => act('discard', { ids: sel }, 'کنار گذاشته شد')}
          onNo={() => setConfirm(null)}
        />
      )}
    </div>
  );
}
