import {
  useNavigate,
} from 'react-router-dom';

import {
  useQuery,
} from '@tanstack/react-query';

import api from '../../lib/api';
import Header from '../../components/layout/Header';

import {
  haptic,
} from '../../lib/telegram';


const safePercent = (value) =>
  Math.max(
    0,
    Math.min(
      100,
      Number(value) || 0
    )
  );


const QUICK_LINKS = [
  {
    icon: '⚡',
    label: 'نقاط ضعف',

    route:
      '/learn/questions?mode=weak',

    color:
      'var(--t-warn)',

    soft:
      'var(--soft-warn)',
  },

  {
    icon: '📝',
    label: 'آزمون',

    route:
      '/learn/exams',

    color:
      'var(--t-acc)',

    soft:
      'var(--soft-acc)',
  },

  {
    icon: '🔴',
    label: 'سطح سخت',

    route:
      '/learn/questions?mode=hard',

    color:
      'var(--t-err)',

    soft:
      'var(--soft-err)',
  },

  {
    icon: '✏️',
    label: 'طراحی سؤال',

    route:
      '/learn/questions?mode=design',

    color:
      'var(--t-pur)',

    soft:
      'var(--soft-pur)',
  },
];


const LIBRARY = [
  {
    icon: '📗',

    title:
      'منابع علوم پایه',

    desc:
      'جزوه، ویدیو، صوت و تست جلسه‌به‌جلسه',

    meta:
      'کتابخانه آموزشی',

    route:
      '/learn/resources',

    soft:
      'var(--soft-ok)',

    color:
      'var(--t-ok)',
  },

  {
    icon: '📘',

    title:
      'رفرنس‌های درسی',

    desc:
      'کتاب‌های مرجع فارسی و لاتین',

    meta:
      'منابع معتبر',

    route:
      '/learn/references',

    soft:
      'var(--soft-acc)',

    color:
      'var(--t-acc)',
  },

  {
    icon: '🕘',

    title:
      'تاریخچه پاسخ‌ها',

    desc:
      'مرور پاسخ‌های صحیح و اشتباه گذشته',

    meta:
      'تحلیل عملکرد',

    route:
      '/learn/question-history',

    soft:
      'var(--soft-warn)',

    color:
      'var(--t-warn)',
  },

  {
    icon: '📄',

    title:
      'خروجی PDF بانک سوال',

    desc:
      'PDF تمرینی یا آزمونی با طراحی هامزیار — دانلود مستقیم',

    meta:
      'خروجی چاپی',

    route:
      '/learn/exams',

    soft:
      'var(--soft-acc)',

    color:
      'var(--t-acc)',
  },

  {
    icon: '✍️',

    title:
      'سؤال‌های من',

    desc:
      'وضعیت تأیید، ویرایش و مدیریت سؤال‌ها',

    meta:
      'مشارکت علمی',

    route:
      '/learn/my-questions',

    soft:
      'var(--soft-pur)',

    color:
      'var(--t-pur)',
  },
];


export default function Learn() {
  const navigate =
    useNavigate();


  const {
    data: statsData = [],
    isError: statsError,
    refetch: refetchStats,
  } = useQuery({
    queryKey: [
      'stats-by-lesson',
    ],

    queryFn: () =>
      api
        .get(
          '/api/questions/stats/by-lesson'
        )
        .then(
          (response) =>
            response.data
              ?.lessons || []
        ),

    staleTime:
      5 * 60 * 1000,
  });


  const stats =
    Array.isArray(statsData)
      ? statsData
      : [];


  const totalAnswers =
    stats.reduce(
      (sum, item) =>
        sum +
        (
          Number(item.total) ||
          0
        ),

      0
    );


  const totalCorrect =
    stats.reduce(
      (sum, item) =>
        sum +
        (
          Number(
            item.correct
          ) || 0
        ),

      0
    );


  const overall =
    totalAnswers
      ? Math.round(
          (
            totalCorrect /
            totalAnswers
          ) * 100
        )
      : 0;


  const open = (route) => {
    haptic('light');
    navigate(route);
  };


  return (
    <>
      <Header
        title="یادگیری"
        subtitle={
          'مسیر شخصی‌سازی‌شدهٔ مطالعه'
        }
        back={false}
      />

      <main className="page fade-up">
        <section
          className={
            'card card-glow hero-card'
          }
          style={{
            marginBottom: 16,
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 13,
            }}
          >
            <div
              style={{
                width: 54,
                height: 54,

                display: 'grid',
                placeItems:
                  'center',

                borderRadius:
                  17,

                background:
                  'var(--grad-brand)',

                boxShadow:
                  'var(--shd-glow)',

                fontSize: 26,
              }}
            >
              🧠
            </div>

            <div
              style={{
                flex: 1,
              }}
            >
              <div
                style={{
                  color:
                    'var(--txm)',
                  fontSize: 'var(--fs-cap)',
                }}
              >
                مرکز یادگیری هامزیار
              </div>

              <div
                style={{
                  fontSize: 'var(--fs-xl)',
                  fontWeight: 900,
                  marginTop: 2,
                }}
              >
                امروز چی یاد می‌گیری؟
              </div>

              <div
                style={{
                  color:
                    'var(--tx2)',

                  fontSize: 'var(--fs-cap)',

                  marginTop:
                    3,
                }}
              >
                منابع، آزمون و تحلیل
                عملکرد در یک مسیر
              </div>
            </div>

            {totalAnswers >
              0 && (
              <div
                style={{
                  textAlign:
                    'center',
                }}
              >
                <div
                  style={{
                    color:
                      'var(--acc2)',

                    fontSize: 'var(--fs-xl)',

                    fontWeight:
                      900,
                  }}
                >
                  {overall}٪
                </div>

                <div
                  style={{
                    color:
                      'var(--txm)',

                    fontSize: 'var(--fs-cap)',
                  }}
                >
                  عملکرد کل
                </div>
              </div>
            )}
          </div>
        </section>


        <div className="sec-title">
          ⚡ شروع سریع
        </div>

        <section
          style={{
            display: 'grid',

            gridTemplateColumns:
              'repeat(4,minmax(0,1fr))',

            gap: 'var(--sp-2)',

            marginBottom:
              18,
          }}
        >
          {QUICK_LINKS.map(
            (item) => (
              <button
                type="button"
                key={item.label}

                className={
                  'card card-tap'
                }

                onClick={() =>
                  open(item.route)
                }

                style={{
                  padding:
                    '11px 3px',

                  minWidth:
                    0,

                  textAlign:
                    'center',
                }}
              >
                <span
                  style={{
                    display:
                      'grid',

                    width:
                      38,

                    height:
                      38,

                    placeItems:
                      'center',

                    margin:
                      '0 auto 6px',

                    borderRadius: 'var(--r-md)',

                    background:
                      item.soft,

                    fontSize: 'var(--fs-xl)',
                  }}
                >
                  {item.icon}
                </span>

                <span
                  style={{
                    display:
                      'block',

                    overflow:
                      'hidden',

                    color:
                      item.color,

                    fontSize: 'var(--fs-cap)',

                    fontWeight:
                      800,

                    textOverflow:
                      'ellipsis',

                    whiteSpace:
                      'nowrap',
                  }}
                >
                  {item.label}
                </span>
              </button>
            )
          )}
        </section>


        <div className="sec-title">
          📚 کتابخانه و ابزارها
        </div>

        <section
          style={{
            display: 'grid',
            gap: 9,
            marginBottom: 18,
          }}
        >
          {LIBRARY.map(
            (item) => (
              <button
                type="button"
                key={item.title}

                className={
                  'card card-tap'
                }

                onClick={() =>
                  open(item.route)
                }

                style={{
                  display:
                    'flex',

                  alignItems:
                    'center',

                  width:
                    '100%',

                  gap:
                    12,

                  padding:
                    13,

                  textAlign:
                    'right',
                }}
              >
                <span
                  style={{
                    display:
                      'grid',

                    flex:
                      '0 0 48px',

                    height:
                      48,

                    placeItems:
                      'center',

                    borderRadius:
                      15,

                    background:
                      item.soft,

                    fontSize:
                      23,
                  }}
                >
                  {item.icon}
                </span>

                <span
                  style={{
                    flex: 1,
                    minWidth: 0,
                  }}
                >
                  <span
                    style={{
                      display:
                        'flex',

                      alignItems:
                        'center',

                      gap: 'var(--sp-2)',
                    }}
                  >
                    <b
                      style={{
                        fontSize: 'var(--fs-md)',
                      }}
                    >
                      {item.title}
                    </b>

                    <span
                      style={{
                        color:
                          item.color,

                        fontSize: 'var(--fs-cap)',
                      }}
                    >
                      {item.meta}
                    </span>
                  </span>

                  <span
                    style={{
                      display:
                        'block',

                      color:
                        'var(--txm)',

                      fontSize: 'var(--fs-cap)',

                      marginTop:
                        3,

                      lineHeight:
                        1.6,
                    }}
                  >
                    {item.desc}
                  </span>
                </span>

                <span
                  style={{
                    color:
                      'var(--txm)',
                  }}
                >
                  ←
                </span>
              </button>
            )
          )}
        </section>


        <section
          className={
            'card card-tap'
          }
          onClick={() =>
            open(
              '/learn/questions'
            )
          }
          onKeyDown={(event) => {
            if (
              event.key ===
              'Enter'
            ) {
              open(
                '/learn/questions'
              );
            }
          }}
          role="button"
          tabIndex={0}
          style={{
            padding: 16,
            marginBottom: 18,
            cursor: 'pointer',

            background:
              'linear-gradient(145deg,var(--soft-pur),var(--surf-card))',

            borderColor:
              'var(--bd-pur)',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
            }}
          >
            <div
              style={{
                width: 52,
                height: 52,

                display:
                  'grid',

                placeItems:
                  'center',

                borderRadius: 'var(--r-lg)',

                background:
                  'var(--soft-pur)',

                fontSize:
                  25,
              }}
            >
              🧪
            </div>

            <div
              style={{
                flex: 1,
              }}
            >
              <div
                style={{
                  fontWeight:
                    900,

                  fontSize: 'var(--fs-lg)',
                }}
              >
                بانک سؤال و تمرین
              </div>

              <div
                style={{
                  color:
                    'var(--txm)',

                  fontSize: 'var(--fs-cap)',

                  lineHeight:
                    1.7,

                  marginTop:
                    3,
                }}
              >
                تمرین آزاد، نقاط ضعف،
                سطح سخت و طراحی سؤال
              </div>
            </div>

            <span className="badge b-pur">
              شروع
            </span>
          </div>
        </section>


        {/* 🌊 W8/UX-02 — خطای آمار هاب */}
        {statsError && stats.length === 0 && (
          <button
            type="button"
            className="btn btn-full"
            onClick={() => refetchStats()}
          >
            🌐 دریافت آمار ناموفق بود — تلاش دوباره
          </button>
        )}

        {stats.length > 0 && (
          <section>
            <div className="sec-title">
              📊 عملکرد به تفکیک درس
            </div>

            <div className="card">
              {stats.map(
                (
                  item,
                  index
                ) => {
                  const value =
                    safePercent(
                      item.percentage
                    );

                  return (
                    <div
                      key={
                        item.lesson ||
                        index
                      }
                      style={{
                        padding:
                          '8px 0',

                        borderBottom:
                          index <
                          stats.length -
                            1
                            ? '1px solid var(--bd)'
                            : 0,
                      }}
                    >
                      <div
                        style={{
                          display:
                            'flex',

                          justifyContent:
                            'space-between',

                          marginBottom: 'var(--sp-2)',
                        }}
                      >
                        <span
                          style={{
                            fontSize: 'var(--fs-sm)',

                            fontWeight:
                              700,
                          }}
                        >
                          {item.lesson ||
                            'نامشخص'}
                        </span>

                        <span
                          style={{
                            color:
                              value >= 70
                                ? 'var(--ok)'
                                : value >=
                                    40
                                  ? 'var(--warn)'
                                  : 'var(--err)',

                            fontSize: 'var(--fs-cap)',

                            fontWeight:
                              800,
                          }}
                        >
                          {value}٪
                        </span>
                      </div>

                      <div className="pbar">
                        <div
                          className="pbar-f"
                          style={{
                            width:
                              `${value}%`,
                          }}
                        />
                      </div>

                      <div
                        style={{
                          color:
                            'var(--txm)',

                          fontSize: 'var(--fs-cap)',

                          marginTop: 'var(--sp-1)',
                        }}
                      >
                        {Number(
                          item.correct
                        ) || 0}{' '}

                        پاسخ صحیح از{' '}

                        {Number(
                          item.total
                        ) || 0}
                      </div>
                    </div>
                  );
                }
              )}
            </div>
          </section>
        )}
      </main>
    </>
  );
}
