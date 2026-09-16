import { useState } from 'react';

import {
  useSearchParams,
} from 'react-router-dom';

import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import api from '../../lib/api';
import Header from '../../components/layout/Header';
import PageError from '../../components/shared/PageError';
import EmptyState from '../../components/shared/EmptyState';

import {
  Spinner,
} from '../../components/shared/Loading';

import {
  FaqListSkeleton,
  SkRowList,
} from '../../components/shared/skeletons';

import {
  hapticNotif,
} from '../../lib/telegram';

import {
  useUIStore,
} from '../../stores/uiStore';


export function Faq() {
  const [
    query,
    setQuery,
  ] = useState('');

  const [
    openId,
    setOpenId,
  ] = useState(null);


  const {
    data,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: [
      'faq',
    ],

    queryFn: () =>
      api
        .get('/api/faq')
        .then(
          (response) =>
            response.data
              ?.categories || []
        ),

    staleTime:
      10 * 60 * 1000,
  });


  const {
    data:
      searchResults = [],

    isFetching,
  } = useQuery({
    queryKey: [
      'faq-search',
      query,
    ],

    queryFn: () =>
      api
        .get(
          '/api/faq/search',

          {
            params: {
              q: query.trim(),
            },
          }
        )
        .then(
          (response) =>
            response.data
              ?.results || []
        ),

    enabled:
      query.trim().length >= 2,
  });


  const categories =
    Array.isArray(data)
      ? data
      : [];


  const results =
    Array.isArray(
      searchResults
    )
      ? searchResults
      : [];


  const searching =
    query.trim().length >= 2;


  const Item = ({
    item,
    category,
  }) => {
    const id =
      `${category}-${item.id}`;

    const open =
      openId === id;

    return (
      <button
        type="button"
        className={
          'card card-tap'
        }
        onClick={() =>
          setOpenId(
            open
              ? null
              : id
          )
        }
        style={{
          width: '100%',
          padding: 13,
          textAlign: 'right',

          borderColor:
            open
              ? 'var(--bdg)'
              : 'var(--bd)',
        }}
      >
        <span
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 9,
          }}
        >
          <span
            style={{
              display: 'grid',

              width: 34,
              height: 34,

              placeItems:
                'center',

              borderRadius: 'var(--r-md)',

              background:
                'var(--acc-soft)',

              color:
                'var(--acc2)',

              fontWeight:
                900,
            }}
          >
            ؟
          </span>

          <b
            style={{
              flex: 1,

              fontSize: 'var(--fs-sm)',

              lineHeight:
                1.7,
            }}
          >
            {item.question}
          </b>

          <span
            style={{
              color:
                'var(--txm)',

              transform:
                open
                  ? 'rotate(90deg)'
                  : 'none',

              transition:
                'transform .2s',
            }}
          >
            ←
          </span>
        </span>

        {open && (
          <span
            style={{
              display:
                'block',

              padding:
                '11px 43px 2px 0',

              color:
                'var(--tx2)',

              fontSize:
                10.8,

              lineHeight:
                1.9,
            }}
          >
            {item.answer}
          </span>
        )}
      </button>
    );
  };


  return (
    <>
      <Header
        title="سؤالات متداول"
        subtitle={
          'پاسخ سریع به پرسش‌ها'
        }
      />

      <main className="page fade-up">
        <section
          className={
            'card card-glow'
          }
          style={{
            padding:
              17,

            marginBottom: 'var(--sp-4)',

            /* موج ۳.۱۰ — سینک با دستورِ
               hero-card--purple */
            background:
              'linear-gradient(145deg,var(--soft-pur),var(--surf-card) 55%,var(--soft-acc))',
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
                  50,

                height:
                  50,

                placeItems:
                  'center',

                borderRadius: 'var(--r-lg)',

                background:
                  'linear-gradient(135deg,var(--pur-dim),var(--acc))',

                fontSize:
                  24,
              }}
            >
              💡
            </span>

            <div>
              <b
                style={{
                  fontSize: 'var(--fs-lg)',
                }}
              >
                چطور می‌تونیم راهنمایی
                کنیم؟
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
                بین سؤال‌های رایج جست‌وجو
                کنید.
              </div>
            </div>
          </div>

          <div
            style={{
              position:
                'relative',

              marginTop:
                13,
            }}
          >
            <input
              className="inp"
              value={query}
              onChange={(event) =>
                setQuery(
                  event.target.value
                )
              }
              placeholder={
                'جست‌وجوی سؤال یا پاسخ...'
              }
              style={{
                paddingLeft:
                  38,
              }}
            />

            {isFetching && (
              <span
                style={{
                  position:
                    'absolute',

                  left:
                    12,

                  top:
                    12,
                }}
              >
                <Spinner size={16} />
              </span>
            )}
          </div>
        </section>


        {isLoading ? (
          <FaqListSkeleton />
        ) : isError ? (
          <PageError
            text="دریافت راهنما انجام نشد."
            onRetry={() => refetch()}
          />
        ) : searching ? (
          <section
            style={{
              display:
                'grid',

              gap:
                8,
            }}
          >
            <div className="sec-title">
              نتایج جست‌وجو (
              {results.length})
            </div>

            {results.length ? (
              results.map(
                (item) => (
                  <Item
                    key={item.id}
                    item={item}

                    category={
                      item.category ||
                      'result'
                    }
                  />
                )
              )
            ) : (
              !isFetching && (
                <EmptyState icon="🔍">
                  نتیجه‌ای پیدا نشد.
                </EmptyState>
              )
            )}
          </section>
        ) : (
          <div
            style={{
              display:
                'grid',

              gap:
                17,
            }}
          >
            {categories.map(
              (category) => (
                <section
                  key={
                    category.name
                  }
                >
                  <div className="sec-title">
                    {category.name}
                  </div>

                  <div
                    style={{
                      display:
                        'grid',

                      gap:
                        8,
                    }}
                  >
                    {(
                      Array.isArray(
                        category.items
                      )
                        ? category.items
                        : []
                    ).map(
                      (item) => (
                        <Item
                          key={item.id}
                          item={item}
                          category={
                            category.name
                          }
                        />
                      )
                    )}
                  </div>
                </section>
              )
            )}
          </div>
        )}
      </main>
    </>
  );
}


const STATUS = {
  new: [
    'در انتظار',
    'b-yel',
    '🕘',
  ],

  reviewing: [
    'در حال بررسی',
    'b-acc',
    '🔎',
  ],

  resolved: [
    'برطرف شد',
    'b-grn',
    '✅',
  ],

  rejected: [
    'رد شد',
    'b-red',
    '❌',
  ],
};


export function Reports() {
  const [
    params,
  ] = useSearchParams();

  const [
    tab,
    setTab,
  ] = useState('new');

  const [
    form,
    setForm,
  ] = useState({
    target_type:
      params.get('type') ===
      'question'
        ? 'question'
        : 'resource',

    target_id:
      params.get('id') ||
      '',

    reason:
      '',

    note:
      '',
  });

  const toast = useUIStore(
    (state) => state.toast
  );

  const queryClient =
    useQueryClient();


  const {
    data:
      reasons = [],
  } = useQuery({
    queryKey: [
      'report-reasons',
    ],

    queryFn: () =>
      api
        .get(
          '/api/reports/reasons'
        )
        .then(
          (response) =>
            response.data
              ?.reasons || []
        ),

    staleTime:
      30 * 60 * 1000,
  });


  const {
    data:
      history = [],

    isLoading:
      historyLoading,

    isError:
      historyError,
  } = useQuery({
    queryKey: [
      'my-reports',
    ],

    queryFn: () =>
      api
        .get(
          '/api/reports/my'
        )
        .then(
          (response) =>
            response.data
              ?.reports || []
        ),

    enabled:
      tab === 'history',
  });


  const createMutation =
    useMutation({
      mutationFn: () =>
        api.post(
          '/api/reports',

          {
            ...form,

            target_id:
              form.target_id
                .trim(),

            note:
              form.note.trim(),
          }
        ),

      onSuccess: async (
        response
      ) => {
        hapticNotif(
          'success'
        );

        toast(
          response.data
            ?.message ||
            'گزارش ثبت شد ✅',

          'success'
        );

        setForm({
          target_type:
            'resource',

          target_id:
            '',

          reason:
            '',

          note:
            '',
        });

        setTab(
          'history'
        );

        await queryClient
          .invalidateQueries({
            queryKey:
              ['my-reports'],
          });
      },

      onError: (error) =>
        toast(
          error?.response
            ?.data
            ?.detail ||
            'ثبت گزارش انجام نشد',

          'error'
        ),
    });


  const reasonList =
    Array.isArray(reasons)
      ? reasons
      : [];


  const reports =
    Array.isArray(history)
      ? history
      : [];


  const valid =
    form.target_id.trim() &&
    form.reason;


  return (
    <>
      <Header
        title="گزارش ایراد"
        subtitle={
          'به بهبود محتوای هامزیار کمک کنید'
        }
      />

      <main className="page fade-up">
        <section
          className={
            'card card-glow'
          }
          style={{
            padding:
              17,

            marginBottom: 'var(--sp-4)',

            background:
              'linear-gradient(145deg,var(--soft-err-2),var(--surf-card) 55%,var(--soft-warn))',
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
                  50,

                height:
                  50,

                placeItems:
                  'center',

                borderRadius: 'var(--r-lg)',

                background:
                  'var(--soft-err)',

                fontSize:
                  24,
              }}
            >
              🚩
            </span>

            <div>
              <b
                style={{
                  fontSize: 'var(--fs-lg)',
                }}
              >
                گزارش دقیق، محتوای بهتر
              </b>

              <div
                style={{
                  color:
                    'var(--txm)',

                  fontSize: 'var(--fs-cap)',

                  lineHeight:
                    1.6,

                  marginTop:
                    3,
                }}
              >
                گزارش شما توسط ادمین محتوا
                بررسی و نتیجه ثبت می‌شود.
              </div>
            </div>
          </div>
        </section>


        <div className="tab-bar">
          <button
            className="tab-btn"
            onClick={() =>
              setTab('new')
            }
            style={{
              color:
                tab === 'new'
                  ? 'var(--t-white)'
                  : 'var(--tx2)',

              background:
                tab === 'new'
                  ? 'var(--grad-brand)'
                  : 'transparent',
            }}
          >
            ＋ گزارش جدید
          </button>

          <button
            className="tab-btn"
            onClick={() =>
              setTab('history')
            }
            style={{
              color:
                tab === 'history'
                  ? 'var(--t-white)'
                  : 'var(--tx2)',

              background:
                tab === 'history'
                  ? 'var(--grad-brand)'
                  : 'transparent',
            }}
          >
            🕘 پیگیری گزارش‌ها
          </button>
        </div>


        {tab === 'new' ? (
          <>
            <section
              className="card"
              style={{
                display:
                  'grid',

                gap: 'var(--sp-3)',
              }}
            >
              <label
                style={{
                  color:
                    'var(--txm)',

                  fontSize: 'var(--fs-cap)',
                }}
              >
                نوع محتوا
              </label>

              <div className="grid2">
                <button
                  type="button"
                  className={`btn ${
                    form.target_type ===
                    'question'
                      ? 'btn-p'
                      : 'btn-dark'
                  }`}
                  onClick={() =>
                    setForm({
                      ...form,

                      target_type:
                        'question',
                    })
                  }
                >
                  🧪 سؤال
                </button>

                <button
                  type="button"
                  className={`btn ${
                    form.target_type ===
                    'resource'
                      ? 'btn-p'
                      : 'btn-dark'
                  }`}
                  onClick={() =>
                    setForm({
                      ...form,

                      target_type:
                        'resource',
                    })
                  }
                >
                  📎 فایل یا منبع
                </button>
              </div>

              <label
                style={{
                  color:
                    'var(--txm)',

                  fontSize: 'var(--fs-cap)',
                }}
              >
                شناسه{' '}

                {form.target_type ===
                'question'
                  ? 'سؤال'
                  : 'فایل'}
              </label>

              <input
                className="inp"
                value={
                  form.target_id
                }
                onChange={(event) =>
                  setForm({
                    ...form,

                    target_id:
                      event.target
                        .value,
                  })
                }
                placeholder={
                  'شناسه محتوا را وارد کنید'
                }
              />

              <label
                style={{
                  color:
                    'var(--txm)',

                  fontSize: 'var(--fs-cap)',
                }}
              >
                دلیل گزارش
              </label>

              <div
                style={{
                  display:
                    'flex',

                  flexWrap:
                    'wrap',

                  gap:
                    6,
                }}
              >
                {reasonList.map(
                  (item) => (
                    <button
                      type="button"
                      key={item.key}
                      className={`badge ${
                        form.reason ===
                        item.key
                          ? 'b-red'
                          : 'b-gray'
                      }`}
                      onClick={() =>
                        setForm({
                          ...form,

                          reason:
                            item.key,
                        })
                      }
                      style={{
                        padding:
                          '7px 10px',

                        border:
                          form.reason ===
                          item.key
                            ? '1px solid var(--bd-err)'
                            : '1px solid transparent',

                        cursor:
                          'pointer',
                      }}
                    >
                      {item.label}
                    </button>
                  )
                )}
              </div>

              <label
                style={{
                  color:
                    'var(--txm)',

                  fontSize: 'var(--fs-cap)',
                }}
              >
                توضیح بیشتر (اختیاری)
              </label>

              <textarea
                className="inp"
                rows={4}
                maxLength={1000}
                value={
                  form.note
                }
                onChange={(event) =>
                  setForm({
                    ...form,

                    note:
                      event.target
                        .value,
                  })
                }
                placeholder={
                  'مشکل را دقیق‌تر توضیح دهید...'
                }
              />
            </section>

            <button
              className={
                'btn btn-d btn-full'
              }
              style={{
                marginTop:
                  12,
              }}
              disabled={
                !valid ||
                createMutation
                  .isPending
              }
              onClick={() =>
                createMutation.mutate()
              }
            >
              {createMutation
                .isPending ? (
                <Spinner size={15} />
              ) : (
                '🚩 ثبت گزارش'
              )}
            </button>
          </>
        ) : historyLoading ? (
          <SkRowList
            n={3}
            icon={40}
          />
        ) : historyError ? (
          <div className="empty card">
            دریافت گزارش‌ها انجام نشد.
          </div>
        ) : reports.length === 0 ? (
          <div className="empty card">
            هنوز گزارشی ثبت نکرده‌اید.
          </div>
        ) : (
          <section
            style={{
              display:
                'grid',

              gap:
                9,
            }}
          >
            {reports.map(
              (item) => {
                const [
                  label,
                  badge,
                  icon,
                ] = (
                  STATUS[
                    item.status
                  ] || [
                    item
                      .status_label ||
                      'نامشخص',

                    'b-gray',

                    '📌',
                  ]
                );

                return (
                  <article
                    key={item.id}
                    className="card"
                  >
                    <div
                      style={{
                        display:
                          'flex',

                        alignItems:
                          'flex-start',

                        gap: 'var(--sp-3)',
                      }}
                    >
                      <span
                        style={{
                          display:
                            'grid',

                          width:
                            42,

                          height:
                            42,

                          placeItems:
                            'center',

                          borderRadius: 'var(--r-md)',

                          background:
                            'var(--soft-mut)',

                          fontSize: 'var(--fs-xl)',
                        }}
                      >
                        {icon}
                      </span>

                      <div
                        style={{
                          flex:
                            1,
                        }}
                      >
                        <b
                          style={{
                            fontSize: 'var(--fs-sm)',
                          }}
                        >
                          {item.target_type ===
                          'question'
                            ? 'گزارش سؤال'
                            : 'گزارش منبع'}

                          {' #'}

                          {item.id}
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
                          {item.reason}

                          {' • '}

                          {item.created_at ||
                            '—'}
                        </div>
                      </div>

                      <span
                        className={`badge ${badge}`}
                      >
                        {label}
                      </span>
                    </div>

                    {item.note && (
                      <div
                        style={{
                          marginTop:
                            9,

                          padding:
                            '8px 10px',

                          color:
                            'var(--tx2)',

                          background:
                            'var(--soft-mut)',

                          borderRadius: 'var(--r-md)',

                          fontSize: 'var(--fs-cap)',
                        }}
                      >
                        «{item.note}»
                      </div>
                    )}
                  </article>
                );
              }
            )}
          </section>
        )}
      </main>
    </>
  );
}
