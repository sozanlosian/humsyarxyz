import { faNum } from '../../lib/format';

import { useState } from 'react';

import {
  useNavigate,
  useParams,
} from 'react-router-dom';

import { useQuery } from '@tanstack/react-query';

import api from '../../lib/api';
import Header from '../../components/layout/Header';

import {
  ProfileSkeleton,
} from '../../components/shared/skeletons';

import {
  haptic,
  hapticNotif,
} from '../../lib/telegram';

/* 👑 موج P2 Prestige — Hero Card عمومی:
   بنر رنک + Top٪ + شوکیس + رکوردها (بدون
   آمار حساس). احترام کامل به privacy:
   limited ⇒ فقط کارت محدود. QR/لینک اشتراک
   از سرور می‌آید؛ خالی بود ⇒ بلوک پنهان. */



function RecordCell({ icon, label, value }) {
  return (
    <div
      className="card"
      style={{
        display: 'grid',
        gap: 3,
        textAlign: 'center',
        padding: '10px 6px',
      }}
    >
      <span style={{ fontSize: 'var(--fs-xl)' }}>
        {icon}
      </span>

      <b style={{ fontSize: 'var(--fs-sm)' }}>
        {value}
      </b>

      <span
        style={{
          color: 'var(--txm)',
          fontSize: 'var(--fs-cap)',
        }}
      >
        {label}
      </span>
    </div>
  );
}

export default function HeroCard() {
  const { uid } = useParams();

  const navigate = useNavigate();

  const [copied, setCopied] =
    useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ['rank-public', uid],
    queryFn: () =>
      api
        .get(
          `/api/profile/prestige/public/${encodeURIComponent(uid)}`
        )
        .then(
          (response) => response.data
        ),
    staleTime: 5 * 60 * 1000,
  });

  const share = async () => {
    haptic();

    const link = data?.share_link;

    if (!link) {
      return;
    }

    const text = `کارت رقابتی من در هامزیار 👑`;

    try {
      const tg =
        window?.Telegram?.WebApp;

      if (tg?.openTelegramLink) {
        tg.openTelegramLink(
          `https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent(text)}`
        );

        return;
      }
    } catch (err) {
      /* fallback به کپی */
    }

    try {
      await navigator.clipboard.writeText(
        link
      );

      setCopied(true);

      hapticNotif('success');

      window.setTimeout(
        () => setCopied(false),
        1800
      );
    } catch (err) {
      /* سکوت */
    }
  };

  if (isLoading || !data) {
    return (
      <>
        <Header
          title="کارت رقابتی"
          onBack={() => navigate(-1)}
        />

        <main className="page">
          <ProfileSkeleton />
        </main>
      </>
    );
  }

  if (data.limited) {
    return (
      <>
        <Header
          title="کارت رقابتی"
          onBack={() => navigate(-1)}
        />

        <main className="page fade-up">
          <section
            className="card"
            style={{
              padding: 30,
              textAlign: 'center',
              display: 'grid',
              gap: 8,
            }}
          >
            <span style={{ fontSize: 40 }}>
              🕶️
            </span>

            <b>این کاربر ، کارت خود را خصوصی کرده است</b>

            <span
              style={{
                color: 'var(--txm)',
                fontSize: 'var(--fs-cap)',
              }}
            >
              فقط رنک و دسته‌ی او در لیدربرد دیده می‌شود.
            </span>
          </section>
        </main>
      </>
    );
  }

  const records = data.records || {};

  const streak = data.streak || {};

  return (
    <>
      <Header
        title="کارت رقابتی"
        onBack={() => navigate(-1)}
      />

      <main className="page fade-up">
        {/* بنر رنک */}
        <section
          className="card card-glow"
          style={{
            background:
              data.gradient ||
              'var(--elev)',
            padding: '26px 18px',
            textAlign: 'center',
            color: 'var(--bg-soft)',
            display: 'grid',
            gap: 5,
          }}
        >
          <div style={{ fontSize: 54 }}>
            {data.icon}
          </div>

          <b style={{ fontSize: 'var(--fs-xl)' }}>
            {data.name}
          </b>

          <div
            style={{
              fontSize: 'var(--fs-sm)',
              fontWeight: 800,
            }}
          >
            {data.title} {data.roman}{' '}
            {data.stars}
          </div>

          {(data.rank_number ||
            data.top_pct) && (
            <div
              style={{
                display: 'inline-flex',
                gap: 6,
                justifyContent:
                  'center',
                marginTop: 6,
              }}
            >
              {data.rank_number && (
                <span
                  style={{
                    background:
                      'var(--scrim)',
                    color: 'var(--t-white)',
                    borderRadius: 'var(--r-pill)',
                    padding:
                      '3px 11px',
                    fontSize: 'var(--fs-cap)',
                    fontWeight: 700,
                  }}
                >
                  🏆 رتبه‌ی{' '}
                  {faNum(data.rank_number)}
                </span>
              )}

              {data.top_pct && (
                <span
                  style={{
                    background:
                      'var(--scrim)',
                    color: 'var(--t-white)',
                    borderRadius: 'var(--r-pill)',
                    padding:
                      '3px 11px',
                    fontSize: 'var(--fs-cap)',
                    fontWeight: 700,
                  }}
                >
                  Top {faNum(data.top_pct)}٪
                </span>
              )}
            </div>
          )}
        </section>

        {/* شوکیس */}
        {!!(data.showcase || []).length && (
          <section>
            <div className="sec-title">
              📌 نشان‌های منتخب
            </div>

            <div
              style={{
                display: 'flex',
                gap: 8,
                flexWrap: 'wrap',
              }}
            >
              {data.showcase.map(
                (badge) => (
                  <div
                    key={badge.key}
                    className="card"
                    style={{
                      display: 'flex',
                      alignItems:
                        'center',
                      gap: 6,
                      border: `1px solid ${
                        badge.color ||
                        'var(--bd)'
                      }`,
                      padding:
                        '7px 11px',
                    }}
                  >
                    <span
                      style={{
                        fontSize: 'var(--fs-lg)',
                      }}
                    >
                      {badge.icon}
                    </span>

                    <b
                      style={{
                        fontSize: 'var(--fs-cap)',
                      }}
                    >
                      {badge.title}
                    </b>
                  </div>
                )
              )}
            </div>
          </section>
        )}

        {/* رکوردها */}
        <section>
          <div className="sec-title">
            🏆 رکوردها
          </div>

          <div
            className="grid2"
            style={{
              display: 'grid',
              gap: 8,
            }}
          >
            <RecordCell
              icon="🔥"
              label="بهترین استریک"
              value={`${faNum(
                streak.best || 0
              )} روز`}
            />

            <RecordCell
              icon="🎯"
              label="بهترین دقت"
              value={`${faNum(
                records.best_acc || 0
              )}٪`}
            />

            <RecordCell
              icon="📝"
              label="بهترین آزمون"
              value={`${faNum(
                records.best_exam_pct ||
                  0
              )}٪`}
            />

            <RecordCell
              icon={
                records.top_rank_icon ||
                '🌱'
              }
              label="اوج رنک"
              value={
                records.top_rank_title ||
                '—'
              }
            />
          </div>
        </section>

        {/* اشتراک‌گذاری */}
        <section
          className="card"
          style={{
            display: 'grid',
            gap: 'var(--sp-3)',
            textAlign: 'center',
          }}
        >
          {!!data.qr_svg && (
            <div
              aria-hidden="true"
              style={{
                width: 140,
                margin: '0 auto',
              }}
              dangerouslySetInnerHTML={{
                __html: data.qr_svg,
              }}
            />
          )}

          <button
            type="button"
            className={
              'btn btn-p btn-full'
            }
            onClick={share}
            disabled={!data.share_link}
          >
            {data.share_link
              ? copied
                ? '✅ لینک کپی شد'
                : '🔗 اشتراک‌گذاری کارت'
              : 'اشتراک‌گذاری فعلاً در دسترس نیست'}
          </button>

          <span
            style={{
              color: 'var(--txm)',
              fontSize: 'var(--fs-cap)',
            }}
          >
            لینک کارت — بدون نمایش آمار حساس
          </span>
        </section>
      </main>
    </>
  );
}
