import {
  useEffect,
} from 'react';

import {
  useQuery,
} from '@tanstack/react-query';

import {
  useNavigate,
} from 'react-router-dom';

import api from '../../lib/api';

import {
  useContentScopeStore,
} from '../../stores/contentScopeStore';
import Header from '../../components/layout/Header';
import PageError from '../../components/shared/PageError';

import {
} from '../../components/shared/Loading';

import {
  ContentHomeSkeleton,
} from '../../components/shared/skeletons';

import {
  haptic,
} from '../../lib/telegram';


const TOOLS = [
  {
    icon: '🧪',
    title: 'بررسی سؤال‌ها',

    desc:
      'تأیید یا رد سؤال‌های جدید',

    route:
      '/admin/content/questions',

    color:
      'var(--t-pur)',

    soft:
      'var(--soft-pur)',
  },

  {
    icon: '📅',
    title: 'برنامه درسی',

    desc:
      'کلاس، امتحان و زمان منعطف',

    route:
      '/admin/content/schedule',

    color:
      'var(--t-acc)',

    soft:
      'var(--soft-acc)',
  },

  {
    icon: '📊',
    title: 'مدیریت نمرات',

    desc:
      'ثبت دسته‌ای، ویرایش و حذف',

    route:
      '/admin/content/grades',

    color:
      'var(--t-ok)',

    soft:
      'var(--soft-ok)',
  },

  {
    icon: '🔬',
    title: 'علوم پایه',

    desc:
      'درس، جلسه و محتوای آموزشی',

    route:
      '/admin/content/basic-science',

    color:
      'var(--t-info)',

    soft:
      'var(--soft-info)',
  },

  {
    icon: '📘',
    title: 'رفرنس‌ها',

    desc:
      'درس، کتاب و جلدهای فارسی و لاتین',

    route:
      '/admin/content/references',

    color:
      'var(--t-acc)',

    soft:
      'var(--soft-acc)',
  },

  {
    icon: '📦',
    title: 'بانک فایل سؤال',

    desc:
      'فایل‌های تست و بانک سؤال',

    route:
      '/admin/content/qbank',

    color:
      'var(--t-warn)',

    soft:
      'var(--soft-warn)',
  },

  // 📥 URL-Import — سرور دانلود و به تلگرام منتقل می‌کند
  {
    icon: '📥',
    title: 'درون‌ریزی از URL',

    desc:
      'سرور فایل را دانلود و به تلگرام منتقل می‌کند',

    route:
      '/admin/content/url-import',

    color:
      'var(--t-info)',

    soft:
      'var(--soft-info)',
  },

  {
    icon: '❓',
    title: 'سؤالات متداول',

    desc:
      'ایجاد و حذف پاسخ‌های راهنما',

    route:
      '/admin/content/faq',

    color:
      'var(--t-pur)',

    soft:
      'var(--soft-pur)',
  },

  {
    icon: '🚩',
    title: 'گزارش‌های محتوا',

    desc:
      'بررسی و تعیین وضعیت گزارش‌ها',

    route:
      '/admin/content/reports',

    color:
      'var(--t-err)',

    soft:
      'var(--soft-err)',
  },
];


/* 🌊 موج C1 — ابزارهایی که در بک‌اند فقط برای
   ادمین ارشد محتوا/مالک باز هستند (GLOBAL_USER)؛
   برای ادمین ورودی خاص پنهان می‌شوند (بک‌اند هم ۴۰۳ می‌دهد) */
const SCOPED_HIDDEN_ROUTES = new Set([
  '/admin/content/schedule',
  '/admin/content/grades',
  '/admin/content/reports',
]);


export default function ContentHome() {
  const navigate =
    useNavigate();

  /* ── 🌊 C1: متن ورودی پنل محتوا ── */
  const intake =
    useContentScopeStore(
      (state) => state.intake
    );

  const intakeLabel =
    useContentScopeStore(
      (state) => state.label
    );

  const scopeMode =
    useContentScopeStore(
      (state) => state.mode
    );

  const setScope =
    useContentScopeStore(
      (state) => state.setScope
    );

  const setIntake =
    useContentScopeStore(
      (state) => state.setIntake
    );

  /* ورودی‌های فعال + scope واقعی از بک‌اند
     (منبع تصمیم: سرور — این صفحه فقط UX است) */
  const {
    data: scopeData,
    isLoading: scopeLoading,
  } = useQuery({
    queryKey: [
      'content-intakes',
    ],

    queryFn: () =>
      api
        .get(
          '/api/content/intakes'
        )
        .then(
          (response) =>
            response.data
        ),

    staleTime:
      60_000,
  });


  const backendKind =
    scopeData?.scope_kind;


  const storeReady =
    Boolean(scopeData);


  /* قفل‌کردن scope از روی پاسخ بک‌اند:
     scoped → همیشه scope خودش، بدون انتخاب */
  useEffect(() => {
    if (!scopeData) {
      return;
    }

    if (
      scopeData.scope_kind === 'scoped'
    ) {
      setScope(
        scopeData.scope_intake || '',
        scopeData.scope_label || '',
        'scoped'
      );
    } else if (
      scopeMode !== 'global'
    ) {
      setScope(
        intake,
        intakeLabel,
        'global'
      );
    }
    /* eslint-disable-next-line react-hooks/exhaustive-deps */
  }, [scopeData]);


  const {
    data,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: [
      'content-overview',
      intake,
    ],

    queryFn: () =>
      api
        .get(
          '/api/content/overview',
          {
            params: {
              intake:
                intake || '',

              /* 🍴 C2 — درخواست آمار مؤثر
                 (آنچه دانشجوی این ورودی واقعاً
                 می‌بیند) در یک پاسخ */
              effective: 1,
            },
          }
        )
        .then(
          (response) =>
            response.data
        ),

    enabled:
      intake !== null,

    staleTime:
      60_000,
  });


  const open = (route) => {
    haptic('light');
    navigate(route);
  };


  const pending =
    Number(
      data?.pending_questions
    ) || 0;


  /* ── 🌊 C1: اولین صفحه‌ی ادمین ارشد = انتخاب ورودی ── */
  const showPicker =
    storeReady &&
    backendKind === 'global' &&
    intake === null;


  const activeIntakes = (
    scopeData?.intakes || []
  ).filter(
    (item) =>
      item.code !== '' &&
      item.code != null
  );


  if (showPicker) {
    return (
      <>
        <Header
          title="پنل ادمین محتوا"
          subtitle={
            'انتخاب ورودی برای مدیریت'
          }
        />

        <main className="page fade-up">
          <div className="sec-title">
            🎓 محتوای کدام ورودی را
            مدیریت می‌کنید؟
          </div>

          <section
            style={{
              display: 'grid',
              gap: 9,
            }}
          >
            {activeIntakes.map(
              (item) => (
                <button
                  type="button"
                  key={item.code}
                  className={
                    'card card-tap pop-in'
                  }
                  onClick={() => {
                    haptic('light');
                    setIntake(
                      item.code,
                      item.label
                    );
                  }}
                  style={{
                    display: 'flex',

                    alignItems:
                      'center',

                    gap: 11,

                    padding: 14,

                    width: '100%',

                    textAlign: 'right',
                  }}
                >
                  <span
                    style={{
                      fontSize: 22,
                    }}
                  >
                    📅
                  </span>

                  <b
                    style={{
                      flex: 1,
                    }}
                  >
                    {item.label}
                  </b>

                  <span>←</span>
                </button>
              )
            )}

            <button
              type="button"
              className={
                'card card-tap pop-in'
              }
              onClick={() => {
                haptic('light');
                setIntake(
                  '',
                  '🌐 سراسری'
                );
              }}
              style={{
                display: 'flex',

                alignItems:
                  'center',

                gap: 11,

                padding: 14,

                width: '100%',

                textAlign: 'right',
              }}
            >
              <span
                style={{
                  fontSize: 22,
                }}
              >
                🌐
              </span>

              <b
                style={{
                  flex: 1,
                }}
              >
                سراسری
              </b>

              <span
                style={{
                  color: 'var(--txm)',

                  fontSize:
                    'var(--fs-cap)',
                }}
              >
                محتوای مشترک و قدیمی
              </span>

              <span>←</span>
            </button>
          </section>
        </main>
      </>
    );
  }


  /* ابزارهای قابل استفاده در این scope
     (بک‌اند مرجع نهایی است؛ این فقط UX) */
  const visibleTools =
    scopeMode === 'scoped'
      ? TOOLS.filter(
          (item) =>
            !SCOPED_HIDDEN_ROUTES.has(
              item.route
            )
        )
      : TOOLS;


  const shownIntakeLabel =
    intakeLabel ||
    (intake === ''
      ? '🌐 سراسری'
      : intake);


  return (
    <>
      <Header
        title="مدیریت محتوا"
        subtitle={
          'کتابخانه، سؤال و برنامه'
        }
      />

      <main className="page fade-up">
        <section
          className={
            'card card-glow'
          }
          style={{
            padding:
              18,

            marginBottom: 'var(--sp-4)',

            background:
              'linear-gradient(145deg,var(--soft-ok),var(--surf-card) 55%,var(--soft-info))',
          }}
        >
          <div
            style={{
              display:
                'flex',

              alignItems:
                'center',

              gap:
                13,
            }}
          >
            <span
              style={{
                display:
                  'grid',

                width:
                  56,

                height:
                  56,

                placeItems:
                  'center',

                borderRadius: 'var(--r-lg)',

                background:
                  'linear-gradient(135deg,var(--ok-dim),var(--info))',

                fontSize:
                  27,
              }}
            >
              🎓
            </span>

            <div
              style={{
                flex:
                  1,
              }}
            >
              <div
                style={{
                  color:
                    'var(--txm)',

                  fontSize: 'var(--fs-cap)',
                }}
              >
                مرکز محتوای آموزشی
              </div>

              <b
                style={{
                  display:
                    'block',

                  fontSize: 'var(--fs-xl)',

                  marginTop:
                    2,
                }}
              >
                کنترل کیفیت و انتشار محتوا
              </b>

              <div
                style={{
                  color:
                    'var(--tx2)',

                  fontSize: 'var(--fs-cap)',

                  marginTop:
                    3,
                }}
              >
                تمام ابزارهای علمی هامزیار
                در یک صفحه
              </div>
            </div>
          </div>
        </section>


        {/* 🌊 C1 — بنر scope ورودی (scoped: قفل؛
            global: نمایش انتخاب فعلی + تغییر ورودی) */}
        <section
          className="card"
          style={{
            display: 'flex',

            alignItems: 'center',

            gap: 'var(--sp-3)',

            padding: 12,

            marginBottom: 'var(--sp-4)',
          }}
        >
          <span
            style={{
              fontSize: 20,
            }}
          >
            📅
          </span>

          <span
            style={{
              flex: 1,
            }}
          >
            <span
              style={{
                color: 'var(--txm)',

                fontSize:
                  'var(--fs-cap)',
              }}
            >
              {scopeMode === 'scoped'
                ? 'ورودی تحت مدیریت'
                : 'ورودی فعلی'}
            </span>

            <b
              style={{
                display: 'block',
              }}
            >
              {shownIntakeLabel}
            </b>
          </span>

          {scopeMode === 'global' && (
            <button
              type="button"
              className="btn"
              onClick={() => {
                haptic('light');
                setIntake(null, '');
              }}
              style={{
                fontSize:
                  'var(--fs-cap)',
              }}
            >
              🔄 تغییر ورودی
            </button>
          )}
        </section>


        {isLoading ? (
          <ContentHomeSkeleton />
        ) : isError ? (
          <PageError
            text="دریافت آمار محتوا انجام نشد."
            onRetry={() => refetch()}
          />
        ) : (
          <section
            className="grid2"
            style={{
              marginBottom:
                16,
            }}
          >
            <div
              className="card"
              style={{
                textAlign:
                  'center',

                padding:
                  12,
              }}
            >
              <b
                style={{
                  color:
                    pending
                      ? 'var(--warn)'
                      : 'var(--ok)',

                  fontSize: 'var(--fs-xl)',
                }}
              >
                {pending}
              </b>

              <div
                style={{
                  color:
                    'var(--txm)',

                  fontSize: 'var(--fs-cap)',
                }}
              >
                سؤال در انتظار
              </div>
            </div>

            <div
              className="card"
              style={{
                textAlign:
                  'center',

                padding:
                  12,
              }}
            >
              <b
                style={{
                  color:
                    'var(--ok)',

                  fontSize: 'var(--fs-xl)',
                }}
              >
                {Number(
                  data
                    ?.approved_questions
                ) || 0}
              </b>

              <div
                style={{
                  color:
                    'var(--txm)',

                  fontSize: 'var(--fs-cap)',
                }}
              >
                سؤال تأییدشده
              </div>
            </div>

            <div
              className="card"
              style={{
                textAlign:
                  'center',

                padding:
                  12,
              }}
            >
              <b
                style={{
                  color:
                    'var(--acc2)',

                  fontSize: 'var(--fs-xl)',
                }}
              >
                {Number(
                  data
                    ?.total_resources
                ) || 0}
              </b>

              <div
                style={{
                  color:
                    'var(--txm)',

                  fontSize: 'var(--fs-cap)',
                }}
              >
                محتوای آموزشی
              </div>
            </div>

            <div
              className="card"
              style={{
                textAlign:
                  'center',

                padding:
                  12,
              }}
            >
              <b
                style={{
                  color:
                    'var(--err)',

                  fontSize: 'var(--fs-xl)',
                }}
              >
                {Number(
                  data
                    ?.upcoming_exams
                ) || 0}
              </b>

              <div
                style={{
                  color:
                    'var(--txm)',

                  fontSize: 'var(--fs-cap)',
                }}
              >
                امتحان پیش‌رو
              </div>
            </div>
          </section>
        )}


        {/* 🍴 C2 — آمار مؤثر: آنچه دانشجوی این ورودی
             واقعاً می‌بیند (اختصاصی ورودی + سراسری) — فقط
             وقتی ctx یک ورودی مشخص است بک‌اند برمی‌گرداند */}
        {Boolean(intake) &&
          data?.effective && (
            <div
              style={{
                color:
                  'var(--txm)',

                fontSize:
                  'var(--fs-cap)',

                margin:
                  '-8px 2px var(--sp-4)',
              }}
            >
              🔭 مؤثر برای این ورودی:
              {' '}
              {Number(
                data.effective
                  .total_resources
              ) || 0}{' '}
              محتوا •{' '}
              {Number(
                data.effective
                  .approved_questions
              ) || 0}{' '}
              سؤال تأییدشده •{' '}
              {Number(
                data.effective
                  .pending_questions
              ) || 0}{' '}
              در انتظار
            </div>
          )}


        {pending > 0 && (
          <button
            type="button"
            className={
              'card card-tap'
            }
            onClick={() =>
              open(
                '/admin/content/questions'
              )
            }
            style={{
              display:
                'flex',

              alignItems:
                'center',

              width:
                '100%',

              gap: 'var(--sp-3)',

              marginBottom: 'var(--sp-4)',

              textAlign:
                'right',

              borderColor:
                'var(--bd-warn)',
            }}
          >
            <span
              style={{
                fontSize:
                  22,
              }}
            >
              ⏳
            </span>

            <span
              style={{
                flex:
                  1,
              }}
            >
              <b
                style={{
                  color:
                    'var(--warn)',
                }}
              >
                {pending} سؤال منتظر بررسی
                است
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
                برای حفظ کیفیت بانک سؤال
                بررسی کنید.
              </span>
            </span>

            <span>←</span>
          </button>
        )}


        <div className="sec-title">
          ابزارهای محتوا
        </div>

        <section
          style={{
            display:
              'grid',

            gap:
              9,
          }}
        >
          {visibleTools.map(
            (
              item,
              index
            ) => (
              <button
                type="button"
                key={item.route}
                className={
                  'card card-tap pop-in'
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
                    11,

                  padding:
                    13,

                  textAlign:
                    'right',

                  animationDelay:
                    `${
                      index * 28
                    }ms`,
                }}
              >
                <span
                  style={{
                    display:
                      'grid',

                    width:
                      45,

                    height:
                      45,

                    placeItems:
                      'center',

                    borderRadius: 'var(--r-md)',

                    color:
                      item.color,

                    background:
                      item.soft,

                    fontSize:
                      21,
                  }}
                >
                  {item.icon}
                </span>

                <span
                  style={{
                    flex:
                      1,
                  }}
                >
                  <b
                    style={{
                      display:
                        'block',

                      fontSize: 'var(--fs-sm)',
                    }}
                  >
                    {item.title}
                  </b>

                  <span
                    style={{
                      display:
                        'block',

                      color:
                        'var(--txm)',

                      fontSize: 'var(--fs-cap)',

                      marginTop:
                        3,
                    }}
                  >
                    {item.desc}
                  </span>
                </span>

                {item.route ===
                  '/admin/content/questions' &&
                  pending > 0 && (
                  <span className="badge b-yel">
                    {pending}
                  </span>
                )}

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
      </main>
    </>
  );
}
