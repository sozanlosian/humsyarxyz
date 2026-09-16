import {
  useEffect,
  useMemo,
} from 'react';

/* 👑 CelebrationOverlay — موج P0 (v3 LOCKED)
   جشن لحظه‌ی ارتقای رنک/دیویژن:
   بک‌دراپ کم‌نور + کارت قاب‌گرادیانی رنک +
   بارش یک‌باره‌ی کاغذرنگی (GPU) + هپتیک.
   مصرف‌کننده: payload.celebration از
   /api/questions/answer و custom-exam.
   کاغذرنگی در reduced-motion حذف می‌شود
   (نمایش ساده) و صدا فعلاً no-op است. */

import {
  hapticNotif,
} from '../../lib/telegram';


/* پالت کاغذرنگی — پیرامون رنگ رنک + رنگ‌های برند */
const CONFETTI_COLORS = [
  'var(--t-warn)', 'var(--t-ok)', 'var(--t-acc-md)',
  'var(--t-pink)', 'var(--t-pur)', 'var(--t-info)',
  'var(--t-warn)', 'var(--tx)',
];


function ConfettiPiece({
  index,
  color,
}) {
  /* توزیع قطعه‌ها حول محور مرکزی با ضرب‌کننده
     حلقه‌ای — تصادفیِ Render-driven بدون
     وابستگی به RNG خارجی (قطعی و تکرارپذیر) */
  const style = useMemo(() => {
    const seed = index * 137.51;

    const rad =
      (seed % 360) * (Math.PI / 180);

    const dist =
      70 + (seed % 130);

    return {
      '--dx': `${Math.round(
        Math.cos(rad) * dist
      )}px`,

      '--dy': `${Math.round(
        150 + ((seed * 1.7) % 260)
      )}px`,

      '--rot': `${Math.round(
        260 + ((seed * 3.1) % 460)
      )}deg`,

      '--dur': `${
        (1.7 + ((seed * 7) % 130) / 100)
          .toFixed(2)
      }s`,

      '--delay': `${
        ((seed * 13) % 70) / 100
      }s`,

      '--w': `${
        5 + Math.round((seed * 11) % 5)
      }px`,

      '--h': `${
        8 + Math.round((seed * 5) % 8)
      }px`,

      '--c':
        index % 3 === 0 && color
          ? color
          : CONFETTI_COLORS[
              index %
              CONFETTI_COLORS.length
            ],
    };
  }, [index, color]);

  return <span style={style} />;
}


export default function CelebrationOverlay({
  celebration,
  onClose,
}) {
  /* هپتیک موفقیت هنگام نمایش جشن */
  useEffect(() => {
    try {
      hapticNotif('success');
    } catch (_) {
      /* خارج از تلگرام بی‌خطر */
    }
  }, []);

  if (!celebration) {
    return null;
  }

  const isRank =
    celebration.kind === 'rank';

  const fromLine =
    isRank && celebration.from_title
      ? `از ${celebration.from_title} به`
      : null;

  return (
    <div
      className="prx-backdrop"
      role="presentation"
      onClick={onClose}
      style={{
        '--prc': celebration.color,
        '--prg': celebration.gradient,
      }}
    >
      <div
        className="prx-card"
        role="dialog"
        aria-modal="true"
        aria-label={
          isRank
            ? 'جشن ارتقای رنک'
            : 'جشن ارتقای دسته'
        }
        onClick={(event) =>
          event.stopPropagation()
        }
      >
        <div
          className="prx-confetti"
          aria-hidden="true"
        >
          {Array.from(
            { length: 60 },
            (_, index) => (
              <ConfettiPiece
                key={index}
                index={index}
                color={
                  celebration.color
                }
              />
            )
          )}
        </div>

        <div
          className="prx-icon"
          aria-hidden="true"
        >
          {celebration.icon || '🎉'}
        </div>

        <div
          style={{
            color: 'var(--txm)',
            fontSize: 'var(--fs-meta)',
            fontWeight: 700,
          }}
        >
          {isRank
            ? '🎉 ارتقای رنک!'
            : '⭐ ارتقای دسته!'}
        </div>

        {fromLine && (
          <div
            style={{
              marginTop: 8,
              color: 'var(--txm)',
              fontSize: 'var(--fs-meta)',
            }}
          >
            {fromLine}
          </div>
        )}

        <h2
          className="pr-title"
          style={{
            margin: '6px 0 0',
            fontSize: isRank ? 21 : 18,
            lineHeight: 1.9,
          }}
        >
          {celebration.title || ''}

          {celebration.roman
            ? ` ${celebration.roman}`
            : ''}
        </h2>

        <p
          style={{
            margin: '10px 0 0',
            color: 'var(--tx2)',
            fontSize: 'var(--fs-cap)',
            lineHeight: 1.9,
          }}
        >
          {isRank
            ? 'سپر ارتقا فعال شد؛ بدون دغدغه ادامه بده 🛡'
            : 'یک پله دیگر نزدیک‌تر شدی؛ سپرت فعال است 🛡'}
        </p>

        <button
          type="button"
          className="btn btn-p btn-full"
          style={{ marginTop: 18 }}
          onClick={onClose}
        >
          عالیه، ادامه بده 🚀
        </button>
      </div>
    </div>
  );
}
