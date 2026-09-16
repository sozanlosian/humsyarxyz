import {
  useEffect,
  useState,
} from 'react';

import {
  useQuery,
} from '@tanstack/react-query';

import {
  useNavigate,
  useSearchParams,
} from 'react-router-dom';

import api from '../../lib/api';
import {
  useDebouncedValue,
} from '../../lib/useDebounce';
import Header from '../../components/layout/Header';
import PageError from '../../components/shared/PageError';
import EmptyState from '../../components/shared/EmptyState';

import SearchField from '../../components/shared/SearchField';

import {
  SearchResultsSkeleton,
} from '../../components/shared/skeletons';

import {
  haptic,
} from '../../lib/telegram';


const TYPES = {
  question: [
    'سؤال',
    'b-pur',
  ],

  resource: [
    'منبع',
    'b-grn',
  ],

  qbank: [
    'بانک فایل',
    'b-yel',
  ],

  reference: [
    'رفرنس',
    'b-acc',
  ],

  schedule: [
    'برنامه',
    'b-red',
  ],

  faq: [
    'راهنما',
    'b-gray',
  ],
};


export default function GlobalSearch() {
  /* ── منبع حقیقت: پارامترهای URL ──
     عبارت جست‌وجو و فیلتر نوع در آدرس ماندگار
     می‌شوند تا با بازگشت (Back) از صفحه‌ی
     نتیجه، دقیقاً همان وضعیت بازیابی شود —
     بدون اینکه دیپ‌لینک هم قابل اشتراک باشد */
  const [
    searchParams,
    setSearchParams,
  ] = useSearchParams();

  const urlQuery =
    searchParams.get('q') || '';

  const type =
    searchParams.get('type') || 'all';

  const [
    query,
    setQueryLocal,
  ] = useState(urlQuery);

  // URL → ورودی (مثل بازگشت با Back)
  useEffect(() => {
    setQueryLocal(urlQuery);
  }, [urlQuery]);

  // ورودی → URL با دیبونس (بدون ساخت رکورد
  // جدید در تاریخچه — replace)
  const queryForUrl =
    useDebouncedValue(query, 420);

  useEffect(() => {
    const current =
      searchParams.get('q') || '';

    if (current === queryForUrl) {
      return;
    }

    setSearchParams(
      (previous) => {
        const next = new URLSearchParams(
          previous,
        );

        if (queryForUrl) {
          next.set('q', queryForUrl);

        } else {
          next.delete('q');
        }

        return next;
      },
      { replace: true },
    );

    // eslint-disable-next-line
    // react-hooks/exhaustive-deps
  }, [queryForUrl]);

  const setQuery = (value) =>
    setQueryLocal(value);

  const setType = (value) =>
    setSearchParams(
      (previous) => {
        const next = new URLSearchParams(
          previous,
        );

        if (value && value !== 'all') {
          next.set('type', value);

        } else {
          next.delete('type');
        }

        return next;
      },
      { replace: true },
    );

  /* ✅ جلوگیری از ریکوئست با هر ضربه کلید */
  const debouncedQuery =
    useDebouncedValue(query, 380);

  const navigate =
    useNavigate();


  const {
    data,
    isFetching,
    isError,
    refetch,
  } = useQuery({
    queryKey: [
      'global-search',
      debouncedQuery.trim(),
    ],

    queryFn: () =>
      api
        .get(
          '/api/search',

          {
            params: {
              q:
                debouncedQuery.trim(),
            },
          }
        )
        .then(
          (response) =>
            response.data
        ),

    enabled:
      debouncedQuery.trim().length >= 2,

    staleTime:
      60_000,
  });


  const allResults =
    Array.isArray(
      data?.results
    )
      ? data.results
      : [];


  const results =
    type === 'all'
      ? allResults

      : allResults.filter(
          (item) =>
            item.type === type
        );


  const availableTypes = [
    ...new Set(
      allResults.map(
        (item) =>
          item.type
      )
    ),
  ];


  const open = (item) => {
    haptic('light');

    navigate(
      item.route
    );
  };


  return (
    <>
      <Header
        title="جست‌وجوی سراسری"
        subtitle={
          'سؤال، منبع، رفرنس، برنامه و راهنما'
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
              'linear-gradient(145deg,var(--soft-info),var(--surf-card) 55%,var(--soft-acc))',
          }}
        >
          <div
            style={{
              display:
                'flex',

              alignItems:
                'center',

              gap:
                12,
            }}
          >
            <span
              style={{
                display:
                  'grid',

                width:
                  52,

                height:
                  52,

                placeItems:
                  'center',

                borderRadius: 'var(--r-lg)',

                background:
                  'linear-gradient(135deg,var(--info-dim),var(--acc))',

                fontSize:
                  25,
              }}
            >
              🔎
            </span>

            <div>
              <b
                style={{
                  fontSize: 'var(--fs-lg)',
                }}
              >
                همه‌چیز را یکجا پیدا کن
              </b>

              <div
                style={{
                  color:
                    'var(--txm)',

                  fontSize: 'var(--fs-cap)',

                  marginTop:
                    3,
                }}
              >
                حداقل دو حرف از عنوان، درس
                یا محتوا بنویسید.
              </div>
            </div>
          </div>


          <div
            style={{
              marginTop: 'var(--sp-4)',
            }}
          >
            <SearchField
              value={query}
              onChange={(event) => {
                setQuery(
                  event.target.value
                );

                setType('all');
              }}
              placeholder={
                'مثلاً فیزیولوژی، قلب یا امتحان...'
              }
              loading={isFetching}
              autoFocus
            />
          </div>
        </section>


        {query.trim().length <
          2 ? (
          <section className="grid2">
            {[
              [
                '🧪',
                'سؤال‌ها',
              ],

              [
                '📚',
                'منابع',
              ],

              [
                '📘',
                'رفرنس‌ها',
              ],

              [
                '📅',
                'برنامه',
              ],
            ].map(
              ([
                icon,
                label,
              ]) => (
                <div
                  key={label}
                  className="card"
                  style={{
                    padding: 'var(--sp-4)',

                    textAlign:
                      'center',
                  }}
                >
                  <div
                    style={{
                      fontSize:
                        24,
                    }}
                  >
                    {icon}
                  </div>

                  <div
                    style={{
                      color:
                        'var(--txm)',

                      fontSize: 'var(--fs-cap)',

                      marginTop:
                        5,
                    }}
                  >
                    {label}
                  </div>
                </div>
              )
            )}
          </section>
        ) : isError ? (
          <PageError
            text="جست‌وجو انجام نشد."
            onRetry={() => refetch()}
          />
        ) : (
          !isFetching &&
          allResults.length === 0
        ) ? (
          <EmptyState icon="🔍">
            نتیجه‌ای برای «{query}» پیدا
            نشد.
          </EmptyState>
        ) : (
          <>
            {availableTypes.length >
              1 && (
              <div className="tab-bar">
                <button
                  className="tab-btn"
                  onClick={() =>
                    setType('all')
                  }
                  style={{
                    color:
                      type === 'all'
                        ? 'var(--t-white)'
                        : 'var(--tx2)',

                    background:
                      type === 'all'
                        ? 'var(--grad-brand)'
                        : 'transparent',
                  }}
                >
                  همه (
                  {allResults.length})
                </button>

                {availableTypes.map(
                  (key) => (
                    <button
                      key={key}
                      className="tab-btn"
                      onClick={() =>
                        setType(key)
                      }
                      style={{
                        color:
                          type === key
                            ? 'var(--t-white)'
                            : 'var(--tx2)',

                        background:
                          type === key
                            ? 'var(--grad-brand)'
                            : 'transparent',
                      }}
                    >
                      {TYPES[key]
                        ?.[0] || key}
                    </button>
                  )
                )}
              </div>
            )}


            {isFetching &&
            allResults.length ===
              0 ? (
              <SearchResultsSkeleton />
            ) : (
              <section
                style={{
                  display:
                    'grid',

                  gap:
                    8,
                }}
              >
                {results.map(
                  (
                    item,
                    index
                  ) => {
                    const [
                      label,
                      badge,
                    ] = (
                      TYPES[
                        item.type
                      ] || [
                        item.type,

                        'b-gray',
                      ]
                    );

                    return (
                      <button
                        type="button"
                        key={`${
                          item.type
                        }-${
                          item.id
                        }-${index}`}
                        className={
                          'card card-tap pop-in'
                        }
                        onClick={() =>
                          open(item)
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
                              Math.min(
                                index,
                                10
                              ) * 25
                            }ms`,
                        }}
                      >
                        <span
                          style={{
                            display:
                              'grid',

                            flex:
                              '0 0 44px',

                            height:
                              44,

                            placeItems:
                              'center',

                            borderRadius: 'var(--r-md)',

                            background:
                              'var(--soft-mut)',

                            fontSize:
                              21,
                          }}
                        >
                          {item.icon ||
                            '🔎'}
                        </span>

                        <span
                          style={{
                            flex:
                              1,

                            minWidth:
                              0,
                          }}
                        >
                          <b
                            style={{
                              display:
                                '-webkit-box',

                              overflow:
                                'hidden',

                              fontSize: 'var(--fs-sm)',

                              lineHeight:
                                1.7,

                              WebkitBoxOrient:
                                'vertical',

                              WebkitLineClamp:
                                2,
                            }}
                          >
                            {item.title ||
                              'نتیجه جست‌وجو'}
                          </b>

                          {item.subtitle && (
                            <span
                              style={{
                                display:
                                  'block',

                                overflow:
                                  'hidden',

                                color:
                                  'var(--txm)',

                                fontSize: 'var(--fs-cap)',

                                marginTop:
                                  3,

                                textOverflow:
                                  'ellipsis',

                                whiteSpace:
                                  'nowrap',
                              }}
                            >
                              {item.subtitle}
                            </span>
                          )}
                        </span>

                        <span
                          className={`badge ${badge}`}
                        >
                          {label}
                        </span>

                        <span>←</span>
                      </button>
                    );
                  }
                )}
              </section>
            )}
          </>
        )}
      </main>
    </>
  );
}
