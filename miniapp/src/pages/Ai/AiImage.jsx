import {
  useMemo,
  useState,
} from 'react';

import Header from '../../components/layout/Header';
import SubscriptionLock, {
  isSubscriptionLock,
  lockKind,
} from '../../components/shared/SubscriptionLock';
import api from '../../lib/api';
import {
  haptic,
  hapticNotif,
} from '../../lib/telegram';


/* ─────────────────────────────────────────────
   🎨 ساخت تصویر با هوشیار (Gemini)
   - توضیح + نسبت تصویر → POST /api/ai/generate-image
   - کلید API سمت سرور می‌ماند؛ تصویر base64
     یک‌بارمصرف برمی‌گردد (بدون فایلِ ماندگار)
   - تایم‌اوت طولانی: تولید تصویر تا ~۹۰ ثانیه
     طول می‌کشد (تایم‌اوت پیش‌فرض api کوتاه است)
───────────────────────────────────────────── */


const RATIOS = [
  { id: '1:1', label: '۱:۱ مربع' },
  { id: '4:3', label: '۴:۳' },
  { id: '3:4', label: '۳:۴' },
  { id: '16:9', label: '۱۶:۹' },
  { id: '9:16', label: '۹:۱۶' },
  { id: '3:2', label: '۳:۲' },
  { id: '2:3', label: '۲:۳' },
  { id: '21:9', label: '۲۱:۹' },
  { id: '5:4', label: '۵:۴' },
  { id: '4:5', label: '۴:۵' },
];

const MIN_LEN = 3;
const MAX_LEN = 1000;


function getErrorMessage(error, fallback) {
  const detail = error?.response?.data?.detail;

  if (typeof detail === 'string' && detail.trim()) {
    return detail;
  }

  if (error?.code === 'ECONNABORTED') {
    return 'ساخت تصویر طول کشید؛ دوباره تلاش کن.';
  }

  return fallback;
}


export default function AiImage() {
  const [prompt, setPrompt] = useState('');

  const [ratio, setRatio] = useState('1:1');

  const [busy, setBusy] = useState(false);

  const [error, setError] = useState('');
  const [errObj, setErrObj] = useState(null);

  const [result, setResult] = useState(null);

  const [usage, setUsage] = useState(null);


  const trimmed = prompt.trim();

  const valid = trimmed.length >= MIN_LEN
    && trimmed.length <= MAX_LEN;

  const imageSrc = useMemo(() => {
    if (!result) return '';

    return `data:${result.mime};base64,${result.image}`;
  }, [result]);


  const generate = async () => {
    if (!valid || busy) return;

    haptic('light');

    setBusy(true);

    setError('');

    try {
      const response = await api.post(
        '/api/ai/generate-image',
        {
          prompt: trimmed,
          aspect_ratio: ratio,
        },
        { timeout: 150_000 },
      );

      setResult(response.data);

      setUsage(response.data?.usage || null);

      hapticNotif();
    } catch (err) {
      setResult(null);
      setErrObj(err);

      setError(getErrorMessage(
        err,
        'ساخت تصویر ناموفق بود؛ دوباره تلاش کن.',
      ));
    } finally {
      setBusy(false);
    }
  };


  return (
    <main className="page fade-up">
      <Header
        title="ساخت تصویر"
        subtitle="توضیح بده، هوشیار می‌سازد 🎨"
      />

      <section className="card aiimg-card">
        <label className="fld-label" htmlFor="aiimg-prompt">
          توضیح تصویر
        </label>

        <textarea
          id="aiimg-prompt"
          className="inp aiimg-prompt"
          rows={4}
          maxLength={MAX_LEN}
          placeholder="مثلاً: یک کتابخانه‌ی چوبیِ گرم با نور عصرگاهی، سبک واقع‌گرایانه"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          disabled={busy}
        />

        <div className="aiimg-count">
          {`${trimmed.length}/${MAX_LEN}`}
        </div>

        <div className="aiimg-ratios">
          {RATIOS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={
                ratio === item.id
                  ? 'aiimg-chip aiimg-chip--on'
                  : 'aiimg-chip'
              }
              disabled={busy}
              onClick={() => {
                setRatio(item.id);
                haptic('light');
              }}
            >
              {item.label}
            </button>
          ))}
        </div>

        <button
          type="button"
          className="btn btn-p aiimg-go"
          disabled={!valid || busy}
          onClick={generate}
        >
          {busy
            ? 'در حال ساخت تصویر...'
            : '🎨 ساخت تصویر'}
        </button>

        {usage && !usage.unlimited && (
          <div className="aiimg-quota">
            📊 امروز
            {' '}
            {usage.used_today}
            /
            {usage.daily_limit}
            {' '}
            تصویر ساخته‌ای
          </div>
        )}
      </section>

      {error && isSubscriptionLock(errObj) && (
        <SubscriptionLock
          feature="ساخت تصویر"
          featureKey="ai_image"
          mode={lockKind(errObj).kind}
        />
      )}

      {error && !isSubscriptionLock(errObj) && (
        <section className="card aiimg-error" role="alert">
          ⚠️
          {' '}
          {error}
        </section>
      )}

      {busy && !result && (
        <section className="card aiimg-loading">
          <div className="aiimg-spin" />
          <div>هوشیار داره تصویرتو می‌سازه...</div>
          <div className="aiimg-hint">
            ممکنه تا یک دقیقه طول بکشه — این صفحه رو نبند
          </div>
        </section>
      )}

      {result && (
        <section className="card aiimg-result">
          <img
            className="aiimg-img"
            src={imageSrc}
            alt="تصویر ساخته‌شده"
          />

          <div className="aiimg-actions">
            <a
              className="btn btn-p"
              href={imageSrc}
              download={`humsyar-${Date.now()}.png`}
            >
              ⬇️ دانلود
            </a>

            <button
              type="button"
              className="btn"
              disabled={busy}
              onClick={generate}
            >
              🔄 ساخت دوباره
            </button>
          </div>
        </section>
      )}
    </main>
  );
}
