import PageError from '../../components/shared/PageError';
import { faNum, number, percent, faDate, faTime } from '../../lib/format';

import { useState } from 'react';
import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { useNavigate, Link } from 'react-router-dom';
import api from '../../lib/api';
import Header from '../../components/layout/Header';
import PrestigeHero from '../../components/shared/PrestigeHero';
import {
  Spinner,
} from '../../components/shared/Loading';

import {
  DashboardSkeleton,
} from '../../components/shared/skeletons';
import { haptic, tg } from '../../lib/telegram';

/* 👑 موج P2 Prestige — ارقام فارسی کوتاه */


/* ⚔️ کارت «چالش ارتقا آماده است» — از نمای
   چالش داخل همان پیلود یکتای ['prestige'] */
export function ChallengeCard() {
  const { data: prestige } = useQuery({
    queryKey: ['prestige'],
    queryFn: () =>
      api
        .get('/api/profile/prestige')
        .then(
          (response) =>
            response.data?.prestige
        ),
    staleTime: 60 * 1000,
  });

  const ch = prestige?.challenge;

  if (!ch || ch.mode === 'none') {
    return null;
  }

  if (ch.mode === 'ready') {
    return (
      <Link
        to="/learn/exams?promo=1"
        className="card card-tap fade-up"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--sp-3)',
          border:
            '1.5px solid var(--warn)',
          textDecoration: 'none',
          color: 'var(--tx)',
        }}
      >
        <span style={{ fontSize: 26 }}>
          ⚔️
        </span>

        <div style={{ flex: 1 }}>
          <b style={{ fontSize: 'var(--fs-sm)' }}>
            چالش ارتقا آماده است — {ch.icon}{' '}
            {ch.title}
          </b>

          <div
            style={{
              color: 'var(--txm)',
              fontSize: 'var(--fs-cap)',
            }}
          >
            {ch.apex
              ? 'باس‌فایت: ۳۰ سؤال با قبولی ۹۰٪ — برو برای افسانه شدن!'
              : '۲۰ سؤال با قبولی ۸۰٪ · مهلت ۲۴ ساعت'}
          </div>
        </div>

        <span
          style={{
            color: 'var(--warn)',
            fontSize: 'var(--fs-sm)',
          }}
        >
          ›
        </span>
      </Link>
    );
  }

  if (ch.mode === 'cooldown') {
    return (
      <div
        className="card fade-up"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 9,
          color: 'var(--txm)',
          fontSize: 'var(--fs-cap)',
        }}
      >
        <span style={{ fontSize: 'var(--fs-xl)' }}>
          ⏳
        </span>
        چالش ارتقا در کول‌داون است — XP‌ات
        محفوظ است، کمی دیگر برگرد 💪
      </div>
    );
  }

  if (ch.mode === 'locked') {
    return (
      <div
        className="card fade-up"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 9,
          color: 'var(--txm)',
          fontSize: 'var(--fs-cap)',
        }}
      >
        <span style={{ fontSize: 'var(--fs-xl)' }}>
          🔒
        </span>
        چالش Apex هنوز قفل است — پیش‌شرط‌ها را
        در کارت قهرمان ببین.
      </div>
    );
  }

  return null;
}

/* ✨ کارت فید رویدادها — ۵ رویداد عمومی ۴۸
   ساعت اخیر + واکنش ناشناس (بدون کامنت) */
export function FeedCard() {
  const queryClient = useQueryClient();

  const { data } = useQuery({
    queryKey: ['prestige-feed'],
    queryFn: () =>
      api
        .get('/api/dashboard/feed?limit=5')
        .then(
          (response) => response.data
        ),
    staleTime: 60 * 1000,
  });

  const reactMutation = useMutation({
    mutationFn: ({ id, kind }) =>
      api.post('/api/dashboard/feed/react', {
        event_id: id,
        kind,
      }),

    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ['prestige-feed'],
      }),
  });

  const items = data?.items || [];

  if (!items.length) {
    return null;
  }

  const EMOJI = {
    clap: '👏',
    fire: '🔥',
    crown: '👑',
  };

  return (
    <section
      className="card fade-up"
      style={{
        display: 'grid',
        gap: 'var(--sp-3)',
      }}
    >
      <div
        className="sec-title"
        style={{ margin: 0 }}
      >
        ✨ تازه‌های میدان
      </div>

      {items.map((item) => (
        <div
          key={item.id}
          style={{
            display: 'grid',
            gap: 5,
          }}
        >
          <div
            style={{
              fontSize: 'var(--fs-meta)',
              lineHeight: 1.8,
            }}
          >
            {item.text}
          </div>

          <div
            style={{
              display: 'flex',
              gap: 6,
            }}
          >
            {['clap', 'fire', 'crown'].map(
              (kind) => (
                <button
                  key={kind}
                  type="button"
                  className={
                    'tab-btn' +
                    (item.my_reaction ===
                    kind
                      ? ' active'
                      : '')
                  }
                  style={{
                    fontSize: 'var(--fs-cap)',
                    padding: '3px 10px',
                  }}
                  onClick={() => {
                    haptic();

                    reactMutation.mutate({
                      id: item.id,
                      kind:
                        item.my_reaction ===
                        kind
                          ? null
                          : kind,
                    });
                  }}
                >
                  {EMOJI[kind]}{' '}
                  {faNum(
                    item.reactions?.[
                      kind
                    ] || 0
                  )}
                </button>
              )
            )}
          </div>
        </div>
      ))}
    </section>
  );
}

/* باز کردن لینک خارجی از داخل مینی‌اپ —
   اولویت با openLink نیتیو تلگرام */
export const openExternal = (url) => {
  try {
    if (tg?.openLink) {
      tg.openLink(url);
      return;
    }
  } catch (_) {
    /* fallback به مرورگر */
  }
  window.open(url, '_blank', 'noopener');
};





/* ✅ سلام متناسب با ساعت روز —
   میکروجزئیتی که محصول را زنده
   و شخصی حس می‌کند */
const dayGreeting = () => {
  const hour = new Date().getHours();

  if (hour >= 5 && hour < 12)
    return 'صبح بخیر ☀️';
  if (hour >= 12 && hour < 17)
    return 'ظهر بخیر 👋';
  if (hour >= 17 && hour < 20)
    return 'عصر بخیر 🌆';
  return 'شب بخیر 🌙';
};

function Ring({
  value = 0,
}) {
  const safe = percent(value);
  const radius = 29;

  const circumference =
    2 * Math.PI * radius;

  return (
    <div
      style={{
        position: 'relative',
        width: 82,
        height: 82,
        flexShrink: 0,
      }}
    >
      <svg
        width="82"
        height="82"
        viewBox="0 0 82 82"
        style={{
          transform:
            'rotate(-90deg)',
        }}
      >
        <circle
          cx="41"
          cy="41"
          r={radius}
          fill="none"
          stroke="var(--ovr)"
          strokeWidth="7"
        />

        <circle
          cx="41"
          cy="41"
          r={radius}
          fill="none"
          stroke="url(#dashboard-ring)"
          strokeWidth="7"
          strokeLinecap="round"
          strokeDasharray={`${
            (safe / 100) *
            circumference
          } ${circumference}`}
        />

        <defs>
          <linearGradient
            id="dashboard-ring"
            x1="0"
            y1="0"
            x2="1"
            y2="1"
          >
            <stop
              stopColor="var(--acc)"
            />

            <stop
              offset="1"
              stopColor="var(--t-info)"
            />
          </linearGradient>
        </defs>
      </svg>

      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'grid',
          placeItems: 'center',
        }}
      >
        <div
          style={{
            textAlign: 'center',
          }}
        >
          <div
            style={{
              color: 'var(--tx)',
              fontSize: 'var(--fs-xl)',
              fontWeight: 900,
              lineHeight: 1,
            }}
          >
            {safe}٪
          </div>

          <div
            style={{
              color: 'var(--txm)',
              fontSize: 'var(--fs-cap)',
              marginTop: 3,
            }}
          >
            آمادگی
          </div>
        </div>
      </div>
    </div>
  );
}

function Metric({
  icon,
  value,
  label,
  color,
  soft,
}) {
  return (
    <div
      className="card"
      style={{
        padding: 12,
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--sp-3)',
      }}
    >
      <div
        style={{
          width: 38,
          height: 38,
          borderRadius: 'var(--r-md)',
          display: 'grid',
          placeItems: 'center',
          background: soft,
          fontSize: 'var(--fs-xl)',
        }}
      >
        {icon}
      </div>

      <div>
        <div
          style={{
            color,
            fontSize: 'var(--fs-xl)',
            fontWeight: 900,
            lineHeight: 1.2,
          }}
        >
          {value}
        </div>

        <div
          style={{
            color: 'var(--txm)',
            fontSize: 'var(--fs-cap)',
            marginTop: 2,
          }}
        >
          {label}
        </div>
      </div>
    </div>
  );
}

function WeekChart({
  rows = [],
}) {
  const values = rows.map(
    (item) =>
      number(item?.count)
  );

  const max = Math.max(
    ...values,
    1
  );

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-end',
        height: 84,
        gap: 'var(--sp-2)',
        paddingTop: 8,
      }}
    >
      {rows.map(
        (item, index) => {
          const value =
            values[index];

          return (
            <div
              key={`${
                item?.date || 'day'
              }-${index}`}
              style={{
                flex: 1,
                display: 'flex',
                height: '100%',
                flexDirection:
                  'column',
                alignItems:
                  'center',
                justifyContent:
                  'flex-end',
                gap: 5,
              }}
            >
              <div
                style={{
                  color:
                    'var(--tx2)',
                  fontSize: 'var(--fs-cap)',
                }}
              >
                {value || ''}
              </div>

              <div
                style={{
                  width: '100%',
                  minHeight: 4,

                  height: `${Math.max(
                    4,
                    (
                      value / max
                    ) * 48
                  )}px`,

                  borderRadius:
                    '7px 7px 3px 3px',

                  background:
                    value
                      ? 'var(--grad-brand)'
                      : 'var(--ovr)',

                  boxShadow:
                    value
                      ? '0 5px 14px var(--acc-glow)'
                      : 'none',
                }}
              />

              <div
                style={{
                  color:
                    'var(--txm)',
                  fontSize: 'var(--fs-cap)',
                }}
              >
                {String(
                  item?.date || ''
                ).slice(-2)}
              </div>
            </div>
          );
        }
      )}
    </div>
  );
}

export default function Dashboard() {
  const navigate =
    useNavigate();

  const [
    tab,
    setTab,
  ] = useState('stats');

  const {
    data,
    isLoading,
    isError,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: [
      'dashboard',
    ],

    queryFn: () =>
      api
        .get('/api/dashboard')
        .then(
          (response) =>
            response.data
        ),

    staleTime:
      3 * 60 * 1000,
  });

  const {
    data: weeklyData = [],
  } = useQuery({
    queryKey: [
      'weekly',
    ],

    queryFn: () =>
      api
        .get(
          '/api/dashboard/weekly'
        )
        .then(
          (response) =>
            response.data
              ?.weekly || []
        ),

    staleTime:
      5 * 60 * 1000,
  });

  /* 💙 تنظیمات زنده حمایت مالی —
     سینک با دکمه «حمایت مالی» ربات */
  const {
    data: donation,
  } = useQuery({
    queryKey: ['donation-config'],

    queryFn: () =>
      api
        .get('/api/profile/donation')
        .then(
          (response) =>
            response.data
        ),

    staleTime:
      10 * 60 * 1000,
    retry: false,
  });

  const showDonation = Boolean(
    donation?.enabled && donation?.link
  );

  const {
    data: leaderboard = [],

    isLoading:
      rankLoading,

    isError:
      rankError,

    refetch:
      refetchRank,
  } = useQuery({
    queryKey: [
      'leaderboard',
    ],

    queryFn: () =>
      api
        .get(
          '/api/dashboard/leaderboard'
        )
        .then(
          (response) =>
            response.data
              ?.leaderboard || []
        ),

    enabled:
      tab === 'rank',

    staleTime:
      5 * 60 * 1000,
  });

  const user =
    data?.user || {};

  const stats =
    data?.stats || {};

  const exams =
    Array.isArray(
      data?.upcoming_exams
    )
      ? data.upcoming_exams
      : [];

  const weakTopics =
    Array.isArray(
      stats.weak_topics
    )
      ? stats.weak_topics
      : [];

  const weekly =
    Array.isArray(weeklyData)
      ? weeklyData
      : [];

  const leaders =
    Array.isArray(leaderboard)
      ? leaderboard
      : [];

  const openTickets =
    number(
      data?.open_tickets
    );

  const role = {
    admin: '👑 مدیر',

    content_admin:
      '🎓 ادمین ارشد محتوا',

    support:
      '🛟 پشتیبان',
  }[user.role];

  return (
    <>
      <Header
        title="داشبورد"
        back={false}
        subtitle={`ورودی ${
          user.intake || '—'
        } • گروه ${
          user.group || '—'
        }`}
        onRefresh={refetch}
        refreshing={isRefetching}
      />

      <main className="page fade-up">
        {isLoading ? (
          <DashboardSkeleton />
        ) : isError ? (
          <PageError
            text={
              'دریافت اطلاعات داشبورد انجام نشد.'
            }
            onRetry={() => refetch()}
            pending={isRefetching}
          />
        ) : (
          <div
            style={{
              display: 'grid',
              gap: 12,
            }}
          >
            <section
              className={
                'card card-glow hero-card'
              }
            >
              <div
                style={{
                  display: 'flex',
                  alignItems:
                    'center',
                  gap: 13,
                }}
              >
                <div
                  className="avatar"
                  style={{
                    width: 52,
                    height: 52,
                    fontSize: 21,
                  }}
                >
                  {(
                    user
                      .display_name ||
                    user.name
                  )?.[0] || 'ه'}
                </div>

                <div
                  style={{
                    flex: 1,
                    minWidth: 0,
                  }}
                >
                  <div
                    style={{
                      color:
                        'var(--txm)',
                      fontSize: 'var(--fs-cap)',
                    }}
                  >
                    {dayGreeting()}
                  </div>

                  <div
                    style={{
                      fontSize: 'var(--fs-xl)',
                      fontWeight: 900,
                      marginTop: 2,
                      overflow:
                        'hidden',
                      textOverflow:
                        'ellipsis',
                      whiteSpace:
                        'nowrap',
                    }}
                  >
                    {user
                      .display_name ||
                      user.name ||
                      'کاربر هامزیار'}
                  </div>

                  <div
                    style={{
                      display: 'flex',
                      flexWrap:
                        'wrap',
                      gap: 5,
                      marginTop: 'var(--sp-2)',
                    }}
                  >
                    {role && (
                      <span className="badge b-yel">
                        {role}
                      </span>
                    )}

                    {stats.level && (
                      <span className="badge b-acc">
                        {stats
                          .level
                          .icon ||
                          '📈'}{' '}

                        {stats
                          .level
                          .label ||
                          'سطح کاربر'}
                      </span>
                    )}
                  </div>
                </div>

                <Ring
                  value={
                    stats.percentage
                  }
                />
              </div>
            </section>

            {/* 👑 موج P0 — بریف فشرده‌ی
                Prestige (جری/هدف/استریک) */}
            <PrestigeHero compact />

            {/* 👑 P2 — کارت چالش آماده + فید تازه‌های میدان */}
            <ChallengeCard />
            <FeedCard />

            {/* 💙 حمایت مالی — فقط وقتی
                مدیر فعالش کرده (سینک با ربات) */}
            {showDonation && (
              <button
                type="button"
                className="card card-tap fade-up"
                onClick={() => {
                  haptic('light');
                  openExternal(
                    donation.link
                  );
                }}
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 11,
                  padding: 13,
                  textAlign: 'right',
                  borderColor:
                    'var(--soft-pink)',
                  background:
                    'linear-gradient(145deg,var(--soft-pink),var(--surf-card) 55%,var(--soft-pink))',
                }}
              >
                <span
                  style={{
                    display: 'grid',
                    width: 42,
                    height: 42,
                    placeItems: 'center',
                    borderRadius: 'var(--r-md)',
                    background:
                      'var(--soft-pink)',
                    fontSize: 'var(--fs-xl)',
                  }}
                >
                  💙
                </span>

                <span
                  style={{ flex: 1 }}
                >
                  <b
                    style={{
                      display: 'block',
                      color: 'var(--t-pink)',
                      fontSize: 'var(--fs-sm)',
                    }}
                  >
                    حمایت از هامزیار
                  </b>

                  <span
                    style={{
                      display: 'block',
                      color: 'var(--txm)',
                      fontSize: 'var(--fs-cap)',
                      marginTop: 3,
                      lineHeight: 1.7,
                    }}
                  >
                    با حمایت کوچیکت به ادامه‌دار
                    بودن و پیشرفت هامزیار کمک کن 🙏
                  </span>
                </span>

                <span
                  className="badge"
                  style={{
                    background:
                      'var(--soft-pink)',
                    color: 'var(--t-pink)',
                  }}
                >
                  💙 حمایت
                </span>
              </button>
            )}

            <section className="grid2">
              <Metric
                icon="🧪"
                value={
                  number(
                    stats
                      .total_answers
                  )
                }
                label="سؤال پاسخ‌داده"
                color="var(--t-acc)"
                soft={
                  'var(--soft-acc)'
                }
              />

              <Metric
                icon="✅"
                value={
                  number(
                    stats
                      .correct_answers
                  )
                }
                label="پاسخ صحیح"
                color="var(--t-ok)"
                soft={
                  'var(--soft-ok)'
                }
              />

              <Metric
                icon="📥"
                value={
                  number(
                    stats.downloads
                  )
                }
                label="دانلود منابع"
                color="var(--t-info)"
                soft={
                  'var(--soft-info)'
                }
              />

              <Metric
                icon="🔥"
                value={
                  number(
                    stats
                      .week_activity
                  )
                }
                label="فعالیت این هفته"
                color="var(--t-warn)"
                soft={
                  'var(--soft-warn)'
                }
              />
            </section>

            <div
              className="tab-bar"
              role="tablist"
            >
              {[
                [
                  'stats',
                  '📈 عملکرد',
                ],

                [
                  'exams',
                  '⏳ امتحانات',
                ],

                [
                  'rank',
                  '🏅 رتبه‌بندی',
                ],
              ].map(
                ([
                  key,
                  label,
                ]) => (
                  <button
                    type="button"
                    key={key}
                    className={`tab-btn ${
                      tab === key
                        ? 'tab-btn--on'
                        : ''
                    }`}
                    role="tab"
                    aria-selected={
                      tab === key
                    }
                    onClick={() => {
                      haptic();
                      setTab(key);
                    }}
                  >
                    {label}
                  </button>
                )
              )}
            </div>

            {tab === 'stats' && (
              <>
                {weekly.length >
                  0 && (
                  <section className="card">
                    <div className="sec-title">
                      فعالیت هفت روز اخیر
                    </div>

                    <WeekChart
                      rows={weekly}
                    />
                  </section>
                )}

                {weakTopics.length >
                  0 && (
                  <section className="card">
                    <div className="sec-title">
                      ⚡ مباحث نیازمند تمرین
                    </div>

                    <div
                      style={{
                        display:
                          'flex',

                        flexWrap:
                          'wrap',

                        gap: 'var(--sp-2)',
                      }}
                    >
                      {weakTopics.map(
                        (topic) => (
                          <button
                            type="button"
                            key={topic}
                            className={
                              'badge b-red'
                            }
                            style={{
                              padding:
                                '6px 11px',
                            }}
                            onClick={() =>
                              navigate(
                                '/learn/questions?mode=weak'
                              )
                            }
                          >
                            {topic}
                          </button>
                        )
                      )}
                    </div>
                  </section>
                )}

                <button
                  className={
                    'btn btn-p btn-full'
                  }
                  onClick={() => {
                    haptic(
                      'medium'
                    );

                    navigate(
                      '/learn/questions?mode=weak'
                    );
                  }}
                >
                  ⚡ شروع تمرین هوشمند
                </button>
              </>
            )}

            {tab === 'exams' && (
              <section
                style={{
                  display: 'grid',
                  gap: 9,
                }}
              >
                {exams.length ===
                0 ? (
                  <div className="empty card">
                    📭 امتحانی در هفت روز
                    آینده ثبت نشده است.
                  </div>
                ) : (
                  exams.map(
                    (
                      exam,
                      index
                    ) => {
                      const days =
                        exam.days_left ==
                        null
                          ? null
                          : number(
                              exam.days_left
                            );

                      const urgent =
                        days != null &&
                        days <= 3;

                      return (
                        <div
                          key={
                            exam.id ||
                            index
                          }
                          className="card"
                          style={{
                            borderColor:
                              urgent
                                ? 'var(--bd-err)'
                                : 'var(--bd)',
                          }}
                        >
                          <div
                            style={{
                              display:
                                'flex',

                              alignItems:
                                'center',

                              gap: 11,
                            }}
                          >
                            <div
                              style={{
                                width:
                                  44,

                                height:
                                  44,

                                display:
                                  'grid',

                                placeItems:
                                  'center',

                                borderRadius: 'var(--r-md)',

                                background:
                                  urgent
                                    ? 'var(--soft-err)'
                                    : 'var(--acc-soft)',

                                fontSize: 'var(--fs-xl)',
                              }}
                            >
                              📝
                            </div>

                            <div
                              style={{
                                flex: 1,
                              }}
                            >
                              <div
                                style={{
                                  fontWeight:
                                    800,
                                }}
                              >
                                {exam.lesson ||
                                  'امتحان'}
                              </div>

                              <div
                                style={{
                                  color:
                                    'var(--txm)',

                                  fontSize: 'var(--fs-cap)',

                                  marginTop:
                                    3,
                                }}
                              >
                                {exam.date
                                  ? faDate(exam.date)
                                  : 'تاریخ نامشخص'}

                                {exam.time
                                  ? ` • ${faTime(exam.time)}`
                                  : ''}
                              </div>
                            </div>

                            {days !=
                              null && (
                              <span
                                className={`badge ${
                                  urgent
                                    ? 'b-red'
                                    : 'b-grn'
                                }`}
                              >
                                {days === 0
                                  ? 'امروز'
                                  : days ===
                                      1
                                    ? 'فردا'
                                    : `${faNum(days)} روز`}
                              </span>
                            )}
                          </div>
                        </div>
                      );
                    }
                  )
                )}

                <button
                  className={
                    'btn btn-dark btn-full'
                  }
                  onClick={() =>
                    navigate(
                      '/schedule'
                    )
                  }
                >
                  مشاهده برنامه کامل
                </button>
              </section>
            )}

            {tab === 'rank' && (
              <section className="card">
                <div className="sec-title">
                  🏆 برترین دانشجویان
                </div>

                {rankLoading ? (
                  <div
                    style={{
                      display: 'grid',
                      placeItems:
                        'center',
                      padding: 30,
                    }}
                  >
                    <Spinner />
                  </div>
                ) : rankError ? (
                  <button
                    className={
                      'btn btn-dark btn-full'
                    }
                    onClick={() =>
                      refetchRank()
                    }
                  >
                    تلاش دوباره
                  </button>
                ) : leaders.length ===
                  0 ? (
                  <div className="empty">
                    هنوز رتبه‌ای ثبت نشده
                    است.
                  </div>
                ) : (
                  leaders.map(
                    (
                      item,
                      index
                    ) => (
                      <div
                        key={`${
                          item.rank
                        }-${
                          item.name
                        }-${index}`}
                        style={{
                          display:
                            'flex',

                          alignItems:
                            'center',

                          gap: 'var(--sp-3)',

                          padding:
                            '10px 0',

                          borderBottom:
                            index <
                            leaders.length -
                              1
                              ? '1px solid var(--bd)'
                              : 0,
                        }}
                      >
                        <div
                          style={{
                            width: 30,
                            textAlign:
                              'center',
                            fontWeight:
                              900,
                          }}
                        >
                          {item.rank ===
                          1
                            ? '🥇'
                            : item.rank ===
                                2
                              ? '🥈'
                              : item.rank ===
                                  3
                                ? '🥉'
                                : item.rank}
                        </div>

                        <div
                          style={{
                            flex: 1,

                            color:
                              item.is_me
                                ? 'var(--acc2)'
                                : 'var(--tx)',

                            fontWeight:
                              item.is_me
                                ? 800
                                : 600,
                          }}
                        >
                          {item.name ||
                            'کاربر'}

                          {item.is_me
                            ? ' • شما'
                            : ''}
                        </div>

                        <div
                          style={{
                            textAlign:
                              'left',
                          }}
                        >
                          <div
                            style={{
                              color:
                                'var(--ok)',

                              fontSize: 'var(--fs-sm)',

                              fontWeight:
                                800,
                            }}
                          >
                            {percent(
                              item.percent
                            )}
                            ٪
                          </div>

                          <div
                            style={{
                              color:
                                'var(--txm)',

                              fontSize: 'var(--fs-cap)',
                            }}
                          >
                            {number(
                              item.correct
                            )}
                            /
                            {number(
                              item.total
                            )}
                          </div>
                        </div>
                      </div>
                    )
                  )
                )}
              </section>
            )}

            {openTickets > 0 && (
              <button
                type="button"
                className={
                  'card card-tap'
                }
                onClick={() =>
                  navigate(
                    '/me/tickets'
                  )
                }
                style={{
                  display: 'flex',
                  alignItems:
                    'center',
                  gap: 11,
                  width: '100%',
                  textAlign:
                    'right',

                  borderColor:
                    'var(--bd-warn)',
                }}
              >
                <span
                  style={{
                    fontSize: 22,
                  }}
                >
                  🎫
                </span>

                <span
                  style={{
                    flex: 1,
                  }}
                >
                  <b>
                    {openTickets} تیکت باز
                  </b>

                  <span
                    style={{
                      display:
                        'block',

                      color:
                        'var(--txm)',

                      fontSize: 'var(--fs-cap)',
                    }}
                  >
                    پیگیری گفت‌وگوهای
                    پشتیبانی
                  </span>
                </span>

                <span>←</span>
              </button>
            )}
          </div>
        )}
      </main>
    </>
  );
}
