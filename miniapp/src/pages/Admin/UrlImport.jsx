import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../../lib/api';
import Header from '../../components/layout/Header';
import EmptyState from '../../components/shared/EmptyState';
import { haptic, hapticNotif } from '../../lib/telegram';
import { useUIStore } from '../../stores/uiStore';

/* 📥 URL-Import — درون‌ریزی محتوای راه‌دور.
   فایل روی سرور دریافت و مستقیم به تلگرام منتقل می‌شود؛
   پیشرفت فقط از job state می‌آید (§112) — بدون progress ساختگی. */

const STATUS_FA = {
  created: ['در صف', 'b-gray'],
  validating: ['بررسی لینک', 'b-yel'],
  downloading: ['دریافت فایل', 'b-yel'],
  validating_file: ['بررسی فایل', 'b-yel'],
  uploading: ['انتقال به تلگرام', 'b-yel'],
  registering: ['ثبت محتوا', 'b-yel'],
  completed: ['کامل شد ✅', 'b-grn'],
  failed: ['ناموفق ❌', 'b-red'],
  cancelled: ['لغو شد', 'b-gray'],
  duplicate: ['تکراری ⚠️', 'b-yel'],
};

export default function UrlImport() {
  const toast = useUIStore((s) => s.toast);
  const [url, setUrl] = useState('');
  const [kind, setKind] = useState('qbank');
  const [targetId, setTargetId] = useState('');
  const [lesson, setLesson] = useState('');
  const [topic, setTopic] = useState('');
  const [ctype, setCtype] = useState('pdf');
  const [desc, setDesc] = useState('');
  const [busy, setBusy] = useState(false);

  const jobsQuery = useQuery({
    queryKey: ['url-import-jobs'],
    queryFn: () => api.get('/api/content/url-import/jobs', { params: { per_page: 20 } }),
    refetchInterval: (q) =>
      (q.state.data?.data?.jobs || []).some(
        (j) => !['completed', 'failed', 'cancelled', 'duplicate'].includes(j.status))
        ? 2500 : false,
  });

  const submit = async () => {
    if (!url.trim()) return;
    setBusy(true);
    try {
      await api.post('/api/content/url-import/jobs', {
        url: url.trim(),
        kind,
        target_id: targetId.trim(),
        lesson, topic,
        ctype,
        description: desc,
        idem: `ma-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      });
      hapticNotif('success');
      toast('Job ساخته شد — سرور در حال انتقال فایل است', 'success');
      setUrl('');
      jobsQuery.refetch();
    } catch (e) {
      toast(e?.response?.data?.detail || 'ساخت job انجام نشد', 'error');
    } finally {
      setBusy(false);
    }
  };

  const cancel = async (id) => {
    try { await api.post(`/api/content/url-import/jobs/${id}/cancel`); jobsQuery.refetch(); }
    catch (e) { toast(e?.response?.data?.detail || 'لغو نشد', 'error'); }
  };

  const retry = async (id, force) => {
    try { await api.post(`/api/content/url-import/jobs/${id}/retry`, { force }); jobsQuery.refetch(); }
    catch (e) { toast(e?.response?.data?.detail || 'retry نشد', 'error'); }
  };

  const jobs = jobsQuery.data?.data?.jobs || [];

  return (
    <>
      <Header title="درون‌ریزی از URL" back />
      <main className="page" style={{ padding: 'var(--sp-4)', display: 'grid', gap: 'var(--sp-3)' }}>
        <section className="card">
          <div className="sec-title">📥 درون‌ریزی محتوا از URL</div>
          <div style={{ color: 'var(--tx2)', fontSize: 'var(--fs-cap)', lineHeight: 1.8 }}>
            فایل روی سرور دریافت و مستقیماً به تلگرام منتقل می‌شود —
            دانلود و آپلود دستی لازم نیست.
          </div>

          <div style={{ display: 'grid', gap: 8, marginTop: 10 }}>
            <input className="inp" dir="ltr" placeholder="https://example.com/file.pdf"
              value={url} onChange={(e) => setUrl(e.target.value)} />

            <select className="inp" value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="qbank">بانک فایل سؤال</option>
              <option value="bs">علوم پایه (جلسه)</option>
              <option value="refs">رفرنس (کتاب)</option>
            </select>

            {kind !== 'qbank' && (
              <input className="inp" placeholder="شناسه جلسه/کتاب مقصد"
                value={targetId} onChange={(e) => setTargetId(e.target.value)} />
            )}

            {kind === 'qbank' && (
              <>
                <input className="inp" placeholder="درس" value={lesson}
                  onChange={(e) => setLesson(e.target.value)} />
                <input className="inp" placeholder="مبحث" value={topic}
                  onChange={(e) => setTopic(e.target.value)} />
              </>
            )}

            {kind === 'bs' && (
              <select className="inp" value={ctype} onChange={(e) => setCtype(e.target.value)}>
                {['video', 'ppt', 'pdf', 'note', 'test', 'voice'].map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            )}

            <input className="inp" placeholder="توضیح (اختیاری)" value={desc}
              onChange={(e) => setDesc(e.target.value)} />

            <button type="button" className="btn btn-pri" disabled={busy || !url.trim()}
              onClick={() => { haptic('medium'); submit(); }}>
              📥 شروع درون‌ریزی
            </button>
          </div>
        </section>

        <section>
          <div className="sec-title">🕘 Jobهای من</div>
          {jobs.length === 0 && (
            <EmptyState icon="📥">هنوز درون‌ریزی‌ای ثبت نشده است.</EmptyState>
          )}
          <div style={{ display: 'grid', gap: 8 }}>
            {jobs.map((j) => {
              const [label, badge] = STATUS_FA[j.status] || [j.status, 'b-gray'];
              const done = ['completed', 'failed', 'cancelled', 'duplicate'].includes(j.status);
              return (
                <article key={j.id} className="card">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <b style={{ direction: 'ltr', fontSize: 'var(--fs-sm)' }}>{j.url_safe}</b>
                    <span className={`badge ${badge}`}>{label}</span>
                    <span style={{ flex: 1 }} />
                    {!done && (
                      <button type="button" className="btn btn-xs" onClick={() => cancel(j.id)}>لغو</button>
                    )}
                    {(j.status === 'failed' || j.status === 'duplicate') && (
                      <button type="button" className="btn btn-xs"
                        onClick={() => retry(j.id, j.status === 'duplicate')}>
                        {j.status === 'duplicate' ? 'ثبت با وجود تکرار' : '🔁'}
                      </button>
                    )}
                  </div>

                  {typeof j.progress?.percent === 'number' && (
                    <div style={{ marginTop: 8, height: 6, background: 'var(--elev)', borderRadius: 4 }}>
                      <div style={{ width: `${j.progress.percent}%`, height: 6, background: 'var(--acc)', borderRadius: 4 }} />
                    </div>
                  )}

                  <div style={{ color: 'var(--txm)', fontSize: 'var(--fs-cap)', marginTop: 6 }}>
                    {j.kind}
                    {j.filename ? ` · ${j.filename}` : ''}
                    {j.progress?.bytes ? ` · ${Number(j.progress.bytes).toLocaleString('fa-IR')} بایت` : ''}
                  </div>

                  {j.error && (
                    <div style={{ color: 'var(--err)', fontSize: 'var(--fs-cap)', marginTop: 6 }}>
                      {j.error.code}: {j.error.message}
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        </section>
      </main>
    </>
  );
}
