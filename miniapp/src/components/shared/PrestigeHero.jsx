import { number } from '../../lib/format';

import { useQuery } from '@tanstack/react-query';

import { Link } from 'react-router-dom';

import api from '../../lib/api';

/* 👑 PrestigeHero — موج P0 (v3 LOCKED)
   کارت قهرمان هویت رقابتی — تک‌منبع داده:
   GET /api/profile/prestige (db.prestige_state)
   با queryKey مشترک ['prestige'] تا داشبورد/
   پروفایل یک فچ داشته باشند. prop ِcompact
   نسخه‌ی فشرده برای داشبورد است.
   هر مقدار (رنگ/گرادیان/آستانه) از پیلود
   می‌آید — هیچ آستانه‌ای اینجا هاردکد نیست. */


/* ارقام فارسی برای متن‌های کوتاه نمایشی */
const faDigits = (value) =>
  String(value ?? '').replace(
    /\d/g,
    (digit) => '۰۱۲۳۴۵۶۷۸۹'[digit]
  );


;


/* درصد پر شدن نوار از have/span پیلود —
   محاسبات آستانه فقط سمت بک‌اند است */
const barPercent = (next) => {
  const span = number(next?.span);
  const have = number(next?.have);

  if (span <= 0) {
    return 0;
  }

  return Math.min(
    100,
    Math.round((have / span) * 100)
  );
};


/* اسکلت لودینگ — همان آینه‌ی چیدمان کارت
   (الگوی FaqListSkeleton: هیچ فاصله‌ی خالی) */
function PrestigeSkeleton() {
  return (
    <section
      className="card fade-up"
      style={{
        display: 'grid',
        gap: 11,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
        }}
      >
        <span
          className="skeleton"
          style={{
            width: 56,
            height: 56,
            borderRadius: '50%',
          }}
        />

        <div
          style={{
            display: 'grid',
            flex: 1,
            gap: 'var(--sp-2)',
          }}
        >
          <span
            className="skeleton"
            style={{
              width: '55%',
              height: 13,
            }}
          />

          <span
            className="skeleton"
            style={{
              width: '80%',
              height: 9,
            }}
          />
        </div>
      </div>

      <span
        className="skeleton"
        style={{
          width: '100%',
          height: 5,
          borderRadius: 'var(--r-pill)',
        }}
      />
    </section>
  );
}


/* خط رقیب — «تنها N XP تا …» */
function RivalLine({
  rival,
  side,
}) {
  if (!rival) {
    return null;
  }

  return (
    <div
      style={{
        color: 'var(--tx2)',
        fontSize: 'var(--fs-cap)',
        lineHeight: 1.8,
      }}
    >
      {side === 'up'
        ? `⚔️ تنها ${faDigits(
            rival.gap
          )} XP با ${
            rival.icon || '🎓'
          } «${
            rival.name
          }» فاصله داری`
        : `🛡 ${faDigits(
            rival.gap
          )} XP جلوتر از ${
            rival.icon || '🎓'
          } «${
            rival.name
          }» هستی`}
    </div>
  );
}


export default function PrestigeHero({
  compact = false,
}) {
  const {
    data,
    isLoading,
  } = useQuery({
    queryKey: ['prestige'],

    queryFn: () =>
      api
        .get('/api/profile/prestige')
        .then(
          (response) =>
            response.data?.prestige ||
            null
        ),

    staleTime: 60 * 1000,

    /* قفلِ کم‌نبض: پنل بدون دیتا هرگز
       خطای خام نمایش نمی‌دهد */
    retry: 1,
  });

  if (isLoading) {
    return <PrestigeSkeleton />;
  }

  /* خرابی اتصال/پیلود خالی → کارت به‌صورت
     افزایشی نمایش داده نمی‌شود (قرارداد
     افزایشی: هیچ رفتار فعلی نشکسته شود) */
  if (!data) {
    return null;
  }

  const pb = {
    '--prc': data.color || undefined,
    '--prg': data.gradient || undefined,
  };

  const next = data.next || {};
  const streak = data.streak || {};
  const shield = data.shield || {};
  const records = data.records || {};
  const pct = barPercent(next);

  /* متن سپر: پاسخی یا زمانی، هرکدام فعال */
  const shieldText = shield.active
    ? number(shield.answers_left) > 0
      ? `🛡 سپر: ${faDigits(
          shield.answers_left
        )} پاسخ`
      : '🛡 سپر فعال'
    : null;

  /* ── نسخه‌ی فشرده (داشبورد): یک ردیف
        اطلاعاتی کلیکی به سمت پروفایل ── */
  if (compact) {
    return (
      <Link
        to="/me/profile"
        className="card card-tap pr-hero fade-up"
        style={{
          ...pb,
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: 12,
          textDecoration: 'none',
        }}
      >
        <span
          className="pr-hero__glow"
          aria-hidden="true"
        />

        <span
          className="pr-hero__badge"
          style={{
            width: 44,
            height: 44,
            fontSize: 21,
          }}
        >
          {data.icon}
        </span>

        <span
          style={{
            display: 'grid',
            flex: 1,
            minWidth: 0,
            gap: 3,
          }}
        >
          <b
            className="pr-title"
            style={{
              fontSize: 'var(--fs-md)',
            }}
          >
            {data.title} {data.roman}

            <span
              className="pr-stars"
              style={{
                marginInlineStart: 6,
              }}
            >
              {data.stars}
            </span>
          </b>

          <span
            style={{
              overflow: 'hidden',
              color: 'var(--tx2)',
              fontSize: 'var(--fs-cap)',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            🎯 {next.label || '—'}
          </span>

          <span
            className="pr-bar"
          >
            <span
              className="pr-bar__fill"
              style={{
                transform: `scaleX(${
                  pct / 100
                })`,
              }}
            />
          </span>
        </span>

        {number(streak.current) > 0 && (
          <span
            className="pr-chip"
            aria-label={`استریک ${
              streak.current
            } روز`}
          >
            🔥 {faDigits(streak.current)}
          </span>
        )}
      </Link>
    );
  }

  /* ── نسخه‌ی کامل (پروفایل) ── */
  return (
    <section
      className="card pr-hero fade-up"
      style={{
        ...pb,
        display: 'grid',
        gap: 12,
      }}
    >
      <span
        className="pr-hero__glow"
        aria-hidden="true"
      />

      {/* ردیف رنک: دایس آیکون + عنوان + ستاره */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 13,
        }}
      >
        <span
          className="pr-hero__badge"
          aria-hidden="true"
        >
          {data.icon}
        </span>

        <div
          style={{
            flex: 1,
            minWidth: 0,
          }}
        >
          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              alignItems: 'baseline',
              gap: 'var(--sp-2)',
            }}
          >
            <b
              className="pr-title"
              style={{
                fontSize: 'var(--fs-lg)',
                lineHeight: 1.7,
              }}
            >
              {data.title} {data.roman}
            </b>

            <span
              className="pr-stars"
              aria-label={`دسته ${data.roman}`}
            >
              {data.stars}
            </span>
          </div>

          <div
            style={{
              color: 'var(--txm)',
              fontSize: 'var(--fs-cap)',
              lineHeight: 1.8,
            }}
          >
            رتبه‌ی Prestige هامزیار
          </div>
        </div>

        {/* Top٪ و رتبه‌ی عددی (غیر-lite) */}
        {data.top_pct != null && (
          <span className="pr-chip">
            🏅 Top{' '}
            {faDigits(
              `${data.top_pct}٪`
            )}
          </span>
        )}

        {data.rank_number != null &&
          data.total_active != null && (
            <span className="pr-chip">
              #{faDigits(data.rank_number)}{' '}
              از{' '}
              {faDigits(data.total_active)}
            </span>
          )}
      </div>

      {/* هشدار افت دیویژن (بنر — نه مودال) */}
      {data.demoted && (
        <div
          style={{
            padding: '8px 11px',

            color: 'var(--warn)',
            fontSize: 'var(--fs-cap)',
            fontWeight: 700,
            lineHeight: 1.8,

            background:
              'var(--soft-warn)',

            border:
              '1px solid var(--bd-warn)',

            borderRadius: 'var(--r-md)',
          }}
        >
          ⚠️ به‌خاطر رکود، یک دیویژن افت
          دادی: {data.demoted.icon}{' '}
          {data.demoted.rank}{' '}
          {data.demoted.roman} — رنکت
          محفوظ است، با چند سؤال برگرد 💪
        </div>
      )}

      {/* هدف فعلی + نوار پیشرفت نازک */}
      <div
        style={{
          display: 'grid',
          gap: 'var(--sp-2)',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent:
              'space-between',
            gap: 8,
          }}
        >
          <span
            style={{
              color: 'var(--tx2)',
              fontSize: 'var(--fs-meta)',
              fontWeight: 700,
              lineHeight: 1.8,
            }}
          >
            🎯 {next.label || '—'}
          </span>

          <span
            style={{
              color: 'var(--txm)',
              fontSize: 'var(--fs-cap)',
              whiteSpace: 'nowrap',
            }}
          >
            ⚡ {faDigits(
              data.effective_xp
            )}{' '}
            XP
          </span>
        </div>

        <div
          className="pr-bar"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
        >
          <div
            className="pr-bar__fill"
            style={{
              transform: `scaleX(${
                pct / 100
              })`,
            }}
          />
        </div>

        {/* XP ذخیره‌شده در انتظار چالش (P1) */}
        {number(data.overflow_xp) > 0 && (
          <div
            style={{
              color: 'var(--tx2)',
              fontSize: 'var(--fs-cap)',
              lineHeight: 1.8,
            }}
          >
            ⭐ {faDigits(
              data.overflow_xp
            )}{' '}
            XP مازاد ذخیره شده — بعد از
            بُرد چالش ارتقا اعمال می‌شود
          </div>
        )}
      </div>

      {/* آمار هویتی: استریک + سپر + رکوردها */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 6,
        }}
      >
        {number(streak.current) > 0 && (
          <span className="pr-chip">
            🔥 {faDigits(streak.current)}{' '}
            روز
            {number(streak.best) >
              number(streak.current) && (
              <span
                style={{
                  color: 'var(--txm)',
                }}
              >
                · اوج{' '}
                {faDigits(streak.best)}
              </span>
            )}
          </span>
        )}

        {shieldText && (
          <span className="pr-chip">
            {shieldText}
          </span>
        )}

        {number(records.best_acc) > 0 && (
          <span className="pr-chip">
            🎯 بهترین دقت{' '}
            {faDigits(
              `${records.best_acc}٪`
            )}
          </span>
        )}
      </div>

      {/* نزدیک‌ترین رقیبها (با effective_xp) */}
      <RivalLine
        rival={data.rival_above}
        side="up"
      />

      <RivalLine
        rival={data.rival_below}
        side="down"
      />
    </section>
  );
}
