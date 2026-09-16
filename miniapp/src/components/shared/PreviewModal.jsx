import {
  useEffect,
  useState,
} from 'react';

import api from '../../lib/api';

import {
  Spinner,
} from './Loading';


/* ─────────────────────────────────────────────
   🌊 W8/UX-03 — پیش‌نمایش داخل مینی‌اپ

   آدرس امضاشده‌ی ۱۰دقیقه‌ای از preview-url
   گرفته می‌شود (تگ‌های media هدر نمی‌فرستند)
   و بر اساس mime رندر می‌شود:
   ویدیو / صوت / عکس / PDF.
───────────────────────────────────────────── */


function kindOf(mime) {
  const m =
    String(mime || '').toLowerCase();

  if (m.startsWith('video/')) {
    return 'video';
  }

  if (m.startsWith('audio/')) {
    return 'audio';
  }

  if (m.startsWith('image/')) {
    return 'image';
  }

  if (m === 'application/pdf') {
    return 'pdf';
  }

  return 'other';
}


export default function PreviewModal({
  scope,
  file,
  onClose,
}) {
  const [
    url,
    setUrl,
  ] = useState('');

  const [
    error,
    setError,
  ] = useState('');

  useEffect(() => {
    let alive = true;

    api
      .get(
        `/api/${scope}/preview-url/${file.id}`
      )
      .then(
        (response) => {
          if (alive) {
            setUrl(
              response.data?.url || ''
            );
          }
        }
      )
      .catch((e) => {
        if (alive) {
          setError(
            e?.response?.data?.detail
            || 'پیش‌نمایش ناموفق بود'
          );
        }
      });

    return () => {
      alive = false;
    };
  }, [scope, file.id]);

  const kind =
    kindOf(file.mime);

  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 90,
        display: 'grid',
        placeItems: 'center',
        padding: 14,
        background: 'rgba(0,0,0,.72)',
      }}
    >
      <div
        className="card"
        onClick={(e) =>
          e.stopPropagation()
        }
        style={{
          width: '100%',
          maxWidth: 560,
          maxHeight: '86vh',
          overflow: 'auto',
          padding: 12,
        }}
      >
        <div
          className="row"
          style={{
            marginBottom: 10,
            gap: 8,
          }}
        >
          <b
            style={{
              flex: 1,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            👁 {file.name || 'پیش‌نمایش'}
          </b>

          <button
            type="button"
            className="btn sm"
            onClick={onClose}
          >
            ✕
          </button>
        </div>

        {!url && !error && (
          <div
            style={{
              display: 'grid',
              placeItems: 'center',
              minHeight: 160,
            }}
          >
            <Spinner size={26} />
          </div>
        )}

        {error && (
          <div
            className="empty card"
            role="alert"
          >
            {error}
          </div>
        )}

        {url && kind === 'video' && (
          <video
            src={url}
            controls
            playsInline
            preload="metadata"
            style={{
              width: '100%',
              maxHeight: '60vh',
              borderRadius: 'var(--r-md)',
              background: '#000',
            }}
          />
        )}

        {url && kind === 'audio' && (
          <audio
            src={url}
            controls
            preload="metadata"
            style={{ width: '100%' }}
          />
        )}

        {url && kind === 'image' && (
          <img
            src={url}
            alt={file.name || ''}
            style={{
              width: '100%',
              borderRadius: 'var(--r-md)',
            }}
          />
        )}

        {url && kind === 'pdf' && (
          <iframe
            src={url}
            title={file.name || 'PDF'}
            style={{
              width: '100%',
              height: '62vh',
              border: 0,
              borderRadius: 'var(--r-md)',
              background: '#fff',
            }}
          />
        )}
      </div>
    </div>
  );
}
