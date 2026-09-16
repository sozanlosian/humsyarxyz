import PageError from '../../components/shared/PageError';
import EmptyState from '../../components/shared/EmptyState';

import { number, errorText } from '../../lib/format';

import { confirmAction } from '../../lib/confirm';
import {
  useEffect,
  useState,
} from 'react';

import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import api from '../../lib/api';
import Header from '../../components/layout/Header';

import {
  SkPlanCard,
} from '../../components/shared/skeletons';

import SearchField from '../../components/shared/SearchField';

import UserSearchSelect from '../../components/shared/UserSearchSelect';

import {
  useDebouncedValue,
} from '../../lib/useDebounce';

import {
  haptic,
  hapticNotif,
} from '../../lib/telegram';

import {
  useUIStore,
} from '../../stores/uiStore';





const money = (value) => {
  const formatted =
    new Intl.NumberFormat(
      'fa-IR'
    ).format(
      number(value)
    );

  return `${formatted} تومان`;
};





const TABS = [
  [
    'overview',
    'نمای کلی',
  ],

  [
    'payments',
    'رسیدها',
  ],

  [
    'plans',
    'پلن‌ها',
  ],

  [
    'subscribers',
    'مشترکین',
  ],

  [
    'discounts',
    'تخفیف',
  ],
];





export default function SubscriptionAdmin() {
  const [
    tab,
    setTab,
  ] = useState('overview');

  const [
    paymentStatus,
    setPaymentStatus,
  ] = useState('pending');

  const [
    subscriberStatus,
    setSubscriberStatus,
  ] = useState('active');

  const [
    plan,
    setPlan,
  ] = useState({
    name: '',
    days: 30,
    price: '',
  });

  const [
    discount,
    setDiscount,
  ] = useState({
    code: '',
    percent: 10,
    max_uses: 0,
    expires_at: '',
    target_plan_ids: [],
    per_user_limit: 0,
  });

  // 🎟 موج D1 — کمپین تخفیف (پیش‌نمایش/انتشار/آمار)
  const [
    discountPreview,
    setDiscountPreview,
  ] = useState(null);

  const [
    discountStats,
    setDiscountStats,
  ] = useState(null);

  const [
    broadcastTarget,
    setBroadcastTarget,
  ] = useState('all');

  const [
    broadcastResult,
    setBroadcastResult,
  ] = useState(null);

  const [
    campaignLoading,
    setCampaignLoading,
  ] = useState(null);

  const [
    card,
    setCard,
  ] = useState({
    card_number: '',
    card_owner: '',
  });

  const [
    grant,
    setGrant,
  ] = useState({
    user_id: '',
    days: 30,
    plan_name:
      'اشتراک دستی',
    extend: true,
  });

  const [
    notes,
    setNotes,
  ] = useState({});

  /* 🔎 جست‌وجوی یکپارچه — همان عبارت،
     هم رسیدها هم مشترکین؛ سمت سرور با
     قرارداد سراسری (نام، یوزرنیم، شماره
     دانشجویی، آیدی عددی) فیلتر می‌شود */
  const [
    paySearch,
    setPaySearch,
  ] = useState('');

  const [
    subSearch,
    setSubSearch,
  ] = useState('');

  const payQuery =
    useDebouncedValue(paySearch, 400)
      .trim();

  const subQuery =
    useDebouncedValue(subSearch, 400)
      .trim();

  /* دانشجوی انتخاب‌شده برای اعطای دستی */
  const [
    grantUser,
    setGrantUser,
  ] = useState(null);

  /* ردیفی که جریان لغودرون‌کارتیش باز
     است (جایگزین window.prompt مرده در
     WebView تلگرام) */
  const [
    revokeFor,
    setRevokeFor,
  ] = useState(null);

  /* 📄 رندر افزایشی (موج ۴.۶۰) — رسیدها و
     مشترکین تا ۱۰۰ ردیف؛ ۴۰ تای اول آنی رندر
     می‌شود و بقیه با یک تپ. */
  const [
    payVisible,
    setPayVisible,
  ] = useState(40);

  const [
    subVisible,
    setSubVisible,
  ] = useState(40);

  useEffect(() => {
    setPayVisible(40);
  }, [paymentStatus, payQuery]);

  useEffect(() => {
    setSubVisible(40);
  }, [subscriberStatus, subQuery]);

  const toast = useUIStore(
    (state) => state.toast
  );

  const queryClient =
    useQueryClient();


  const {
    data: overview,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: [
      'subscription-admin-overview',
    ],

    queryFn: () =>
      api
        .get(
          '/api/subscription-admin/overview'
        )
        .then(
          (response) =>
            response.data
        ),
  });


  const {
    data: payments = [],
    isFetching: paymentsFetching,
  } = useQuery({
    queryKey: [
      'subscription-admin-payments',
      paymentStatus,
      payQuery,
    ],

    queryFn: () =>
      api
        .get(
          '/api/subscription-admin/payments',

          {
            params: {
              status:
                paymentStatus ||
                undefined,

              search:
                payQuery ||
                undefined,

              limit:
                100,
            },
          }
        )
        .then(
          (response) =>
            response.data
              ?.payments || []
        ),

    enabled:
      tab === 'payments',
  });


  const {
    data: subscribers = [],
    isFetching: subscribersFetching,
  } = useQuery({
    queryKey: [
      'subscription-admin-subscribers',
      subscriberStatus,
      subQuery,
    ],

    queryFn: () =>
      api
        .get(
          '/api/subscription-admin/subscribers',

          {
            params: {
              status:
                subscriberStatus,

              search:
                subQuery ||
                undefined,

              limit:
                100,
            },
          }
        )
        .then(
          (response) =>
            response.data
              ?.subscribers || []
        ),

    enabled:
      tab === 'subscribers',
  });


  const {
    data: discounts = [],
  } = useQuery({
    queryKey: [
      'subscription-admin-discounts',
    ],

    queryFn: () =>
      api
        .get(
          '/api/subscription-admin/discounts'
        )
        .then(
          (response) =>
            response.data
              ?.discounts || []
        ),

    enabled:
      tab === 'discounts',
  });


  const refresh = async () => {
    await Promise.all([
      queryClient
        .invalidateQueries({
          queryKey: [
            'subscription-admin-overview',
          ],
        }),

      queryClient
        .invalidateQueries({
          queryKey: [
            'subscription-admin-payments',
          ],
        }),

      queryClient
        .invalidateQueries({
          queryKey: [
            'subscription-admin-subscribers',
          ],
        }),

      queryClient
        .invalidateQueries({
          queryKey: [
            'subscription-admin-discounts',
          ],
        }),

      queryClient
        .invalidateQueries({
          queryKey:
            ['sub-status'],
        }),
    ]);
  };


  const mutation = useMutation({
    mutationFn: ({
      type,
      id,
      payload,
    }) => {
      if (
        type === 'plan-add'
      ) {
        return api.post(
          '/api/subscription-admin/plans',

          {
            name:
              plan.name,

            days:
              Number(
                plan.days
              ),

            price:
              Number(
                plan.price
              ),
          }
        );
      }

      if (
        type === 'plan-toggle'
      ) {
        return api.post(
          `/api/subscription-admin/plans/${id}/toggle`
        );
      }

      if (
        type === 'plan-delete'
      ) {
        return api.delete(
          `/api/subscription-admin/plans/${id}`
        );
      }

      if (
        type === 'decision'
      ) {
        return api.post(
          `/api/subscription-admin/payments/${id}/decision`,

          payload
        );
      }

      if (
        type === 'receipt'
      ) {
        return api.post(
          `/api/subscription-admin/payments/${id}/send-receipt`
        );
      }

      if (
        type === 'grant'
      ) {
        return api.post(
          '/api/subscription-admin/subscribers/grant',

          {
            ...grant,

            user_id:
              Number(
                grant.user_id
              ),

            days:
              Number(
                grant.days
              ),
          }
        );
      }

      if (
        type === 'revoke'
      ) {
        return api.post(
          `/api/subscription-admin/subscribers/${id}/revoke`,

          payload
        );
      }

      if (
        type === 'discount-add'
      ) {
        return api.post(
          '/api/subscription-admin/discounts',

          {
            ...discount,

            percent:
              Number(
                discount.percent
              ),

            max_uses:
              Number(
                discount.max_uses
              ),

            expires_at:
              discount.expires_at ||
              null,

            // 🎟 موج D1 — خالی = همه پلن‌های فعال
            target_plan_ids:
              (discount.target_plan_ids ||
                []).length
                ? discount.target_plan_ids
                : null,

            per_user_limit:
              Number(
                discount.per_user_limit ||
                0
              ),
          }
        );
      }

      if (
        type === 'discount-toggle'
      ) {
        return api.post(
          `/api/subscription-admin/discounts/${
            encodeURIComponent(id)
          }/toggle`
        );
      }

      if (
        type === 'discount-delete'
      ) {
        return api.delete(
          `/api/subscription-admin/discounts/${
            encodeURIComponent(id)
          }`
        );
      }

      return api.put(
        '/api/subscription-admin/card',

        card
      );
    },

    onSuccess: async (
      _,
      variables
    ) => {
      hapticNotif(
        'success'
      );

      toast(
        'عملیات با موفقیت انجام شد ✅',
        'success'
      );

      if (
        variables.type ===
        'plan-add'
      ) {
        setPlan({
          name: '',
          days: 30,
          price: '',
        });
      }

      if (
        variables.type ===
        'discount-add'
      ) {
        setDiscount({
          code: '',
          percent: 10,
          max_uses: 0,
          expires_at: '',
          target_plan_ids: [],
          per_user_limit: 0,
        });
      }

      if (
        variables.type === 'grant'
      ) {
        setGrant({
          ...grant,
          user_id: '',
        });

        setGrantUser(null);
      }

      if (
        variables.type === 'revoke'
      ) {
        setRevokeFor(null);
      }

      setNotes({});

      await refresh();
    },

    onError: (error) =>
      toast(
        errorText(
          error,
          'عملیات انجام نشد'
        ),
        'error'
      ),
  });


  const stats =
    overview?.stats || {};

  const plans =
    Array.isArray(
      overview?.plans
    )
      ? overview.plans
      : [];

  const paymentRows =
    Array.isArray(payments)
      ? payments
      : [];

  const subscriberRows =
    Array.isArray(
      subscribers
    )
      ? subscribers
      : [];

  const discountRows =
    Array.isArray(
      discounts
    )
      ? discounts
      : [];


  // 🎟 موج D1 — کمپین: Preview / Stats / Broadcast
  const handleDiscountPreview = async (code) => {
    if (discountPreview?.code === code) {
      setDiscountPreview(null);
      return;
    }
    setCampaignLoading(code);
    haptic('light');
    try {
      const { data: dl } = await api.post(
        `/api/subscription-admin/discounts/${encodeURIComponent(code)}/preview`
      );
      setDiscountStats(null);
      setBroadcastResult(null);
      setDiscountPreview({ code, text: dl.text });
      hapticNotif('success');
    } catch (e) {
      toast(
        e?.response?.data?.detail || 'پیش‌نمایش ناموفق بود',
        'error'
      );
    } finally {
      setCampaignLoading(null);
    }
  };

  const handleDiscountStats = async (code) => {
    if (discountStats?.code === code) {
      setDiscountStats(null);
      return;
    }
    setCampaignLoading(code);
    haptic('light');
    try {
      const { data: dl } = await api.get(
        `/api/subscription-admin/discounts/${encodeURIComponent(code)}/stats`
      );
      setDiscountPreview(null);
      setBroadcastResult(null);
      setDiscountStats({ code, ...dl });
      hapticNotif('success');
    } catch (e) {
      toast(
        e?.response?.data?.detail || 'دریافت آمار ناموفق بود',
        'error'
      );
    } finally {
      setCampaignLoading(null);
    }
  };

  const handleBroadcastStart = (code) => {
    haptic('light');
    setDiscountPreview(null);
    setDiscountStats(null);
    setBroadcastTarget('all');
    setBroadcastResult({ code, state: 'picking' });
  };

  const handleBroadcastSend = async (code) => {
    setCampaignLoading(code);
    setBroadcastResult({ code, state: 'sending' });
    haptic('light');
    try {
      const { data: dl } = await api.post(
        `/api/subscription-admin/discounts/${encodeURIComponent(code)}/broadcast`,
        { target: broadcastTarget }
      );
      const bid = dl.broadcast_id;
      // نظرس پویا هر ۳ ثانیه تا تکمیل
      const poll = async () => {
        try {
          const { data: st } = await api.get(
            `/api/subscription-admin/discounts/${encodeURIComponent(code)}/broadcast/${bid}`
          );
          if (st.status === 'sending') {
            setBroadcastResult({ code, state: 'sending', status: st, bid });
            setTimeout(poll, 3000);
          } else {
            setBroadcastResult({ code, state: 'done', summary: st, bid });
            if (st.status === 'cancelled') {
              toast('انتشار متوقف شد ⛔', 'info');
            } else {
              hapticNotif('success');
              toast('انتشار کامل شد ✅', 'success');
            }
            refresh();
          }
        } catch {
          setBroadcastResult({ code, state: 'done', summary: null });
        }
      };
      setTimeout(poll, 2500);
    } catch (e) {
      setBroadcastResult(null);
      toast(
        e?.response?.data?.detail || 'شروع انتشار ناموفق بود',
        'error'
      );
    } finally {
      setCampaignLoading(null);
    }
  };

  // ⛔ توقف انتشار در حال اجرا — حلقه‌ی بک‌اند هر ۲۰ نفر وضعیت را می‌خواند
  const handleBroadcastCancel = async (code, bid) => {
    if (!bid) return;
    haptic('light');
    try {
      await api.post(
        `/api/subscription-admin/discounts/${encodeURIComponent(code)}/broadcast/${bid}/cancel`
      );
      toast('درخواست توقف ثبت شد ⛔', 'info');
    } catch (e) {
      toast(
        e?.response?.data?.detail || 'توقف انتشار ممکن نشد',
        'error'
      );
    }
  };


  if (isLoading) {
    return (
      <>
        <Header title="مدیریت اشتراک" />

        <main className="page">
          <SkPlanCard />
          <SkPlanCard />
          <SkPlanCard />
        </main>
      </>
    );
  }


  return (
    <>
      <Header
        title="مدیریت اشتراک"
        subtitle={
          'پلن، پرداخت، مشترک و تخفیف'
        }
        right={
          <button
            type="button"
            onClick={() =>
              refetch()
            }
            aria-label="به‌روزرسانی"
            style={{
              width:
                35,

              height:
                35,

              borderRadius: 'var(--r-md)',

              background:
                'var(--elev)',

              border:
                '1px solid var(--bd)',
            }}
          >
            ↻
          </button>
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

            marginBottom:
              13,

            background:
              'linear-gradient(145deg,var(--soft-ok),var(--surf-card) 55%,var(--soft-acc))',
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
                  'linear-gradient(135deg,var(--ok-dim),var(--acc))',

                fontSize:
                  25,
              }}
            >
              💳
            </span>

            <div>
              <b
                style={{
                  fontSize: 'var(--fs-lg)',
                }}
              >
                مرکز مالی هامزیار
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
                {number(
                  stats.active
                )}{' '}

                مشترک فعال •{' '}

                {number(
                  stats.pending
                )}{' '}

                رسید در انتظار
              </div>
            </div>
          </div>
        </section>


        <div className="tab-bar">
          {TABS.map(
            ([
              key,
              label,
            ]) => (
              <button
                type="button"
                key={key}
                className="tab-btn"
                onClick={() =>
                  setTab(key)
                }
                style={{
                  color:
                    tab === key
                      ? 'var(--t-white)'
                      : 'var(--tx2)',

                  background:
                    tab === key
                      ? 'var(--grad-brand)'
                      : 'transparent',
                }}
              >
                {label}
              </button>
            )
          )}
        </div>


        {isError ? (
          <PageError
            text="دریافت اطلاعات انجام نشد."
            onRetry={() => refetch()}
          />
        ) : tab ===
          'overview' ? (
          <>
            <section className="grid2">
              {[
                [
                  '💎',
                  stats.active,
                  'فعال',
                  'var(--t-ok)',
                ],

                [
                  '⏳',
                  stats.pending,
                  'رسید منتظر',
                  'var(--t-warn)',
                ],

                [
                  '💰',
                  money(
                    stats.revenue_month
                  ),
                  'درآمد ماه',
                  'var(--t-info)',
                ],

                [
                  '📈',
                  `${number(
                    stats.conv_rate
                  )}٪`,
                  'نرخ تأیید',
                  'var(--t-acc)',
                ],
              ].map(
                ([
                  icon,
                  value,
                  label,
                  color,
                ]) => (
                  <div
                    key={label}
                    className="card"
                    style={{
                      textAlign:
                        'center',
                    }}
                  >
                    <div>
                      {icon}
                    </div>

                    <b
                      style={{
                        display:
                          'block',

                        color,

                        fontSize:
                          (
                            typeof value ===
                              'string' &&
                            value.length >
                              8
                          )
                            ? 13
                            : 20,

                        marginTop:
                          3,
                      }}
                    >
                      {value}
                    </b>

                    <span
                      style={{
                        color:
                          'var(--txm)',

                        fontSize: 'var(--fs-cap)',
                      }}
                    >
                      {label}
                    </span>
                  </div>
                )
              )}
            </section>


            <section
              className="card"
              style={{
                marginTop:
                  12,
              }}
            >
              <div className="sec-title">
                💳 اطلاعات کارت
              </div>

              <input
                className="inp"
                value={
                  card.card_number ||
                  overview?.card
                    ?.card_number ||
                  ''
                }
                onChange={(event) =>
                  setCard({
                    ...card,

                    card_number:
                      event.target
                        .value,
                  })
                }
                placeholder="شماره کارت"
                style={{
                  marginBottom:
                    8,
                }}
              />

              <input
                className="inp"
                value={
                  card.card_owner ||
                  overview?.card
                    ?.card_owner ||
                  ''
                }
                onChange={(event) =>
                  setCard({
                    ...card,

                    card_owner:
                      event.target
                        .value,
                  })
                }
                placeholder="نام صاحب کارت"
              />

              <button
                className={
                  'btn btn-p btn-full'
                }
                style={{
                  marginTop:
                    8,
                }}
                disabled={
                  mutation.isPending
                }
                onClick={() =>
                  mutation.mutate({
                    type:
                      'card',
                  })
                }
              >
                ذخیره اطلاعات کارت
              </button>
            </section>


            <section
              className="card"
              style={{
                marginTop:
                  12,
              }}
            >
              <div className="sec-title">
                🎁 اعطای دستی
              </div>

              <UserSearchSelect
                selected={grantUser}
                onPick={(user) => {
                  setGrantUser(user);

                  setGrant({
                    ...grant,

                    user_id:
                      String(user.id),
                  });
                }}
                onClear={() => {
                  setGrantUser(null);

                  setGrant({
                    ...grant,
                    user_id: '',
                  });
                }}
              />

              <div
                className="grid2"
                style={{
                  marginTop:
                    8,
                }}
              >
                <input
                  className="inp"
                  type="number"
                  value={
                    grant.days
                  }
                  onChange={(event) =>
                    setGrant({
                      ...grant,

                      days:
                        event.target
                          .value,
                    })
                  }
                  placeholder="روز"
                />

                <input
                  className="inp"
                  value={
                    grant.plan_name
                  }
                  onChange={(event) =>
                    setGrant({
                      ...grant,

                      plan_name:
                        event.target
                          .value,
                    })
                  }
                  placeholder="نام پلن"
                />
              </div>

              <button
                className={
                  'btn btn-g btn-full'
                }
                style={{
                  marginTop:
                    8,
                }}
                disabled={
                  !grant.user_id ||
                  !grant.days ||
                  mutation.isPending
                }
                onClick={() =>
                  mutation.mutate({
                    type:
                      'grant',
                  })
                }
              >
                فعال‌سازی یا تمدید
              </button>
            </section>
          </>
        ) : tab ===
          'plans' ? (
          <>
            <section
              className="card"
              style={{
                display:
                  'grid',

                gap:
                  8,

                marginBottom:
                  12,
              }}
            >
              <div className="sec-title">
                ＋ پلن جدید
              </div>

              <input
                className="inp"
                value={
                  plan.name
                }
                onChange={(event) =>
                  setPlan({
                    ...plan,

                    name:
                      event.target
                        .value,
                  })
                }
                placeholder="نام پلن"
              />

              <div className="grid2">
                <input
                  className="inp"
                  type="number"
                  value={
                    plan.days
                  }
                  onChange={(event) =>
                    setPlan({
                      ...plan,

                      days:
                        Number(
                          event.target
                            .value
                        ),
                    })
                  }
                  placeholder="روز"
                />

                <input
                  className="inp"
                  type="number"
                  value={
                    plan.price
                  }
                  onChange={(event) =>
                    setPlan({
                      ...plan,

                      price:
                        Number(
                          event.target
                            .value
                        ),
                    })
                  }
                  placeholder="قیمت تومان"
                />
              </div>

              <button
                className="btn btn-p"
                disabled={
                  !plan.name.trim() ||
                  !plan.days ||
                  plan.price === '' ||
                  mutation.isPending
                }
                onClick={() =>
                  mutation.mutate({
                    type:
                      'plan-add',
                  })
                }
              >
                افزودن پلن
              </button>
            </section>


            <section
              style={{
                display:
                  'grid',

                gap:
                  8,
              }}
            >
              {plans.map((item) => (
                <article
                  key={item.id}
                  className="card"
                >
                  <div
                    style={{
                      display:
                        'flex',

                      alignItems:
                        'center',

                      gap: 'var(--sp-3)',
                    }}
                  >
                    <span
                      style={{
                        fontSize:
                          22,
                      }}
                    >
                      💠
                    </span>

                    <div
                      style={{
                        flex:
                          1,
                      }}
                    >
                      <b>
                        {item.name}
                      </b>

                      <div
                        style={{
                          color:
                            'var(--txm)',

                          fontSize: 'var(--fs-cap)',
                        }}
                      >
                        {number(
                          item.days
                        )}{' '}

                        روز •{' '}

                        {money(
                          item.price
                        )}
                      </div>
                    </div>

                    <span
                      className={`badge ${
                        item.active
                          ? 'b-grn'
                          : 'b-gray'
                      }`}
                    >
                      {item.active
                        ? 'فعال'
                        : 'غیرفعال'}
                    </span>
                  </div>

                  <div
                    style={{
                      display:
                        'flex',

                      gap: 'var(--sp-2)',

                      marginTop:
                        9,
                    }}
                  >
                    <button
                      className={
                        'btn btn-dark'
                      }
                      style={{
                        flex:
                          1,
                      }}
                      onClick={() =>
                        mutation.mutate({
                          type:
                            'plan-toggle',

                          id:
                            item.id,
                        })
                      }
                    >
                      {item.active
                        ? 'غیرفعال‌کردن'
                        : 'فعال‌کردن'}
                    </button>

                    <button
                      className="btn btn-d"
                      onClick={async () => {
                        const accepted =
                          await confirmAction(
                            'پلن حذف شود؟'
                          );

                        if (accepted) {
                          mutation.mutate({
                            type:
                              'plan-delete',

                            id:
                              item.id,
                          });
                        }
                      }}
                    >
                      🗑
                    </button>
                  </div>
                </article>
              ))}
            </section>
          </>
        ) : tab ===
          'payments' ? (
          <>
            <div className="tab-bar">
              {[
                [
                  'pending',
                  'در انتظار',
                ],

                [
                  'approved',
                  'تأیید',
                ],

                [
                  'rejected',
                  'رد',
                ],

                [
                  '',
                  'همه',
                ],
              ].map(
                ([
                  key,
                  label,
                ]) => (
                  <button
                    key={label}
                    className="tab-btn"
                    onClick={() =>
                      setPaymentStatus(
                        key
                      )
                    }
                    style={{
                      color:
                        paymentStatus ===
                        key
                          ? 'var(--t-white)'
                          : 'var(--tx2)',

                      background:
                        paymentStatus ===
                        key
                          ? 'var(--grad-brand)'
                          : 'transparent',
                    }}
                  >
                    {label}
                  </button>
                )
              )}
            </div>


            <SearchField
              value={paySearch}
              onChange={(event) =>
                setPaySearch(
                  event.target.value
                )
              }
              placeholder="جست‌وجو: نام، یوزرنیم، شماره، آیدی عددی یا پلن..."
              ariaLabel="جست‌وجوی رسیدها"
              loading={paymentsFetching}
              style={{
                marginBottom: 'var(--sp-3)',
              }}
            />


            {paymentRows.length ===
              0 ? (
              <EmptyState>
                {payQuery
                  ? 'رسیدی با این عبارت پیدا نشد.'
                  : 'رسیدی در این وضعیت نیست.'}
              </EmptyState>
            ) : (
              <section
                style={{
                  display:
                    'grid',

                  gap:
                    8,
                }}
              >
                {paymentRows.slice(
                  0,
                  payVisible
                ).map(
                  (item) => (
                    <article
                      key={item.id}
                      className="card"
                    >
                      <div
                        style={{
                          display:
                            'flex',

                          gap:
                            9,
                        }}
                      >
                        <span
                          style={{
                            fontSize:
                              22,
                          }}
                        >
                          🧾
                        </span>

                        <div
                          style={{
                            flex:
                              1,
                          }}
                        >
                          <b>
                            {item.user_name}
                            {' • '}
                            {item.plan_name}
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
                            {item.student_id ||
                              'بدون شماره'}

                            {item.username
                              ? ` • @${item.username}`
                              : ''}

                            {' • '}

                            {money(
                              item.final_price
                            )}

                            {' • '}

                            {item.submitted_at}
                          </div>
                        </div>

                        <span
                          className={`badge ${
                            item.status ===
                            'approved'
                              ? 'b-grn'

                              : item.status ===
                                  'rejected'
                                ? 'b-red'

                                : 'b-yel'
                          }`}
                        >
                          {item.status}
                        </span>
                      </div>

                      <button
                        className={
                          'btn btn-dark btn-full'
                        }
                        style={{
                          marginTop:
                            8,
                        }}
                        onClick={() =>
                          mutation.mutate({
                            type:
                              'receipt',

                            id:
                              item.id,
                          })
                        }
                      >
                        📨 ارسال رسید به تلگرام من
                      </button>

                      {item.status ===
                        'pending' && (
                        <>
                          <textarea
                            className="inp"
                            rows={2}
                            value={
                              notes[
                                item.id
                              ] || ''
                            }
                            onChange={(event) =>
                              setNotes({
                                ...notes,

                                [item.id]:
                                  event
                                    .target
                                    .value,
                              })
                            }
                            placeholder={
                              'یادداشت بررسی'
                            }
                            style={{
                              marginTop:
                                8,
                            }}
                          />

                          <div
                            style={{
                              display:
                                'flex',

                              gap: 'var(--sp-2)',

                              marginTop: 'var(--sp-2)',
                            }}
                          >
                            <button
                              className="btn btn-g"
                              style={{
                                flex:
                                  1,
                              }}
                              onClick={() =>
                                mutation.mutate({
                                  type:
                                    'decision',

                                  id:
                                    item.id,

                                  payload: {
                                    approved:
                                      true,

                                    note:
                                      notes[
                                        item.id
                                      ] ||
                                      '',
                                  },
                                })
                              }
                            >
                              ✅ تأیید
                            </button>

                            <button
                              className="btn btn-d"
                              style={{
                                flex:
                                  1,
                              }}
                              disabled={
                                !(
                                  notes[
                                    item.id
                                  ] || ''
                                ).trim()
                              }
                              onClick={() =>
                                mutation.mutate({
                                  type:
                                    'decision',

                                  id:
                                    item.id,

                                  payload: {
                                    approved:
                                      false,

                                    note:
                                      notes[
                                        item.id
                                      ],
                                  },
                                })
                              }
                            >
                              ❌ رد
                            </button>
                          </div>
                        </>
                      )}
                    </article>
                  )
                )}
              </section>
            )}

          {paymentRows.length >
            payVisible && (
            <button
              type="button"
              className={
                'btn btn-dark btn-full'
              }
              style={{
                marginTop: 9,
              }}
              onClick={() =>
                setPayVisible(
                  (current) =>
                    current + 40
                )
              }
            >
              نمایش بیشتر (
              {paymentRows.length -
                payVisible}{' '}
              رسید دیگر)
            </button>
          )}
          </>
        ) : tab ===
          'subscribers' ? (
          <>
            <div className="tab-bar">
              {[
                [
                  'active',
                  'فعال',
                ],

                [
                  'expired',
                  'منقضی',
                ],

                [
                  'revoked',
                  'لغوشده',
                ],
              ].map(
                ([
                  key,
                  label,
                ]) => (
                  <button
                    key={key}
                    className="tab-btn"
                    onClick={() =>
                      setSubscriberStatus(
                        key
                      )
                    }
                    style={{
                      color:
                        subscriberStatus ===
                        key
                          ? 'var(--t-white)'
                          : 'var(--tx2)',

                      background:
                        subscriberStatus ===
                        key
                          ? 'var(--grad-brand)'
                          : 'transparent',
                    }}
                  >
                    {label}
                  </button>
                )
              )}
            </div>


            <SearchField
              value={subSearch}
              onChange={(event) =>
                setSubSearch(
                  event.target.value
                )
              }
              placeholder="جست‌وجو: نام، یوزرنیم، شماره یا آیدی عددی..."
              ariaLabel="جست‌وجوی مشترکین"
              loading={subscribersFetching}
              style={{
                marginBottom: 'var(--sp-3)',
              }}
            />


            {subscriberRows.length ===
              0 ? (
              <EmptyState>
                {subQuery
                  ? 'مشترکی با این عبارت پیدا نشد.'
                  : 'مشترکی در این وضعیت نیست.'}
              </EmptyState>
            ) : (
              <section
                style={{
                  display:
                    'grid',

                  gap:
                    8,
                }}
              >
                {subscriberRows.slice(
                  0,
                  subVisible
                ).map(
                  (item) => (
                    <article
                      key={
                        item.user_id
                      }
                      className="card"
                    >
                      <div
                        style={{
                          display:
                            'flex',

                          alignItems:
                            'center',

                          gap: 'var(--sp-3)',
                        }}
                      >
                        <span
                          className="avatar"
                          style={{
                            width:
                              42,

                            height:
                              42,
                          }}
                        >
                          {item.name?.[0] ||
                            '؟'}
                        </span>

                        <div
                          style={{
                            flex:
                              1,
                          }}
                        >
                          <b>
                            {item.name}
                          </b>

                          <div
                            style={{
                              color:
                                'var(--txm)',

                              fontSize: 'var(--fs-cap)',
                            }}
                          >
                            {item.username
                              ? `@${item.username} • `
                              : ''}

                            {item.plan_name}

                            {' • تا '}

                            {item.end_date ||
                              '—'}
                          </div>
                        </div>

                        <span className="badge b-grn">
                          {item.status}
                        </span>
                      </div>

                      {item.status ===
                        'active' && (
                        revokeFor ===
                        item.user_id ? (
                          <div
                            className="pop-in"
                            style={{
                              display:
                                'grid',

                              gap: 'var(--sp-2)',

                              marginTop:
                                8,
                            }}
                          >
                            <textarea
                              className="inp"
                              rows={2}
                              value={
                                notes[
                                  item.user_id
                                ] || ''
                              }
                              onChange={(event) =>
                                setNotes({
                                  ...notes,

                                  [item.user_id]:
                                    event
                                      .target
                                      .value,
                                })
                              }
                              placeholder={
                                'دلیل لغو اشتراک (اختیاری)'
                              }
                              style={{
                                marginTop: 0,
                              }}
                            />

                            <div
                              style={{
                                display:
                                  'flex',

                                gap: 'var(--sp-2)',
                              }}
                            >
                              <button
                                className="btn btn-d"
                                style={{
                                  flex:
                                    1,
                                }}
                                disabled={
                                  mutation.isPending
                                }
                                onClick={() =>
                                  mutation.mutate({
                                    type:
                                      'revoke',

                                    id:
                                      item.user_id,

                                    payload: {
                                      reason:
                                        (
                                          notes[
                                            item.user_id
                                          ] || ''
                                        ).trim() ||
                                        'لغو توسط مدیریت',
                                    },
                                  })
                                }
                              >
                                تأیید لغو
                              </button>

                              <button
                                className="btn btn-dark"
                                onClick={() =>
                                  setRevokeFor(
                                    null
                                  )
                                }
                              >
                                انصراف
                              </button>
                            </div>
                          </div>
                        ) : (
                          <button
                            className={
                              'btn btn-d btn-full'
                            }
                            style={{
                              marginTop:
                                8,
                            }}
                            onClick={() => {
                              haptic(
                                'light'
                              );

                              setRevokeFor(
                                item.user_id
                              );
                            }}
                          >
                            لغو اشتراک
                          </button>
                        )
                      )}
                    </article>
                  )
                )}
              </section>
            )}

          {subscriberRows.length >
            subVisible && (
            <button
              type="button"
              className={
                'btn btn-dark btn-full'
              }
              style={{
                marginTop: 9,
              }}
              onClick={() =>
                setSubVisible(
                  (current) =>
                    current + 40
                )
              }
            >
              نمایش بیشتر (
              {subscriberRows.length -
                subVisible}{' '}
              مشترک دیگر)
            </button>
          )}
          </>
        ) : (
          <>
            <section
              className="card"
              style={{
                display:
                  'grid',

                gap:
                  8,

                marginBottom:
                  12,
              }}
            >
              <div className="sec-title">
                ＋ کد تخفیف
              </div>

              <div className="grid2">
                <input
                  className="inp"
                  value={
                    discount.code
                  }
                  onChange={(event) =>
                    setDiscount({
                      ...discount,

                      code:
                        event.target
                          .value
                          .toUpperCase(),
                    })
                  }
                  placeholder="کد"
                />

                <input
                  className="inp"
                  type="number"
                  min="1"
                  max="100"
                  value={
                    discount.percent
                  }
                  onChange={(event) =>
                    setDiscount({
                      ...discount,

                      percent:
                        event.target
                          .value,
                    })
                  }
                  placeholder="درصد"
                />
              </div>

              <div className="grid2">
                <input
                  className="inp"
                  type="number"
                  min="0"
                  value={
                    discount.max_uses
                  }
                  onChange={(event) =>
                    setDiscount({
                      ...discount,

                      max_uses:
                        event.target
                          .value,
                    })
                  }
                  placeholder="سقف استفاده"
                />

                <input
                  className="inp"
                  type="date"
                  value={
                    discount.expires_at
                  }
                  onChange={(event) =>
                    setDiscount({
                      ...discount,

                      expires_at:
                        event.target
                          .value,
                    })
                  }
                />
              </div>

              {/* 🎟 موج D1 — هدف پلن + سقف هر کاربر */}
              <div
                style={{
                  display: 'grid',
                  gap: 6,
                }}
              >
                <span
                  style={{
                    fontSize: 'var(--fs-cap)',
                    color: 'var(--txm)',
                  }}
                >
                  📦 پلن‌های قابل استفاده
                  (خالی = همه پلن‌های فعال)
                </span>

                <div className="chip-row">
                  {plans.map((pl) => {
                    const on = (
                      discount.target_plan_ids ||
                      []
                    ).includes(pl.id);
                    return (
                      <button
                        key={pl.id}
                        type="button"
                        className={
                          'chip' +
                          (on
                            ? ' chip--active'
                            : '')
                        }
                        onClick={() => {
                          const cur =
                            discount.target_plan_ids ||
                            [];
                          setDiscount({
                            ...discount,

                            target_plan_ids: on
                              ? cur.filter(
                                  (x) => x !== pl.id
                                )
                              : [...cur, pl.id],
                          });
                        }}
                      >
                        {pl.name}
                      </button>
                    );
                  })}
                </div>

                <input
                  className="inp"
                  type="number"
                  min="0"
                  value={
                    discount.per_user_limit ||
                    0
                  }
                  onChange={(event) =>
                    setDiscount({
                      ...discount,

                      per_user_limit:
                        event.target
                          .value,
                    })
                  }
                  placeholder="سقف استفاده‌ی هر کاربر (0 = نامحدود)"
                />
              </div>

              <button
                className="btn btn-p"
                disabled={
                  !discount.code
                    .trim() ||
                  mutation.isPending
                }
                onClick={() =>
                  mutation.mutate({
                    type:
                      'discount-add',
                  })
                }
              >
                افزودن کد
              </button>
            </section>


            <section
              style={{
                display:
                  'grid',

                gap:
                  8,
              }}
            >
              {discountRows.map(
                (item) => (
                  <article
                    key={item.code}
                    className="card"
                  >
                    <div
                      style={{
                        display:
                          'flex',

                        alignItems:
                          'center',

                        gap: 'var(--sp-3)',
                      }}
                    >
                      <span
                        style={{
                          fontSize:
                            22,
                        }}
                      >
                        🎟
                      </span>

                      <div
                        style={{
                          flex:
                            1,
                        }}
                      >
                        <b>
                          {item.code}
                          {' • '}
                          {item.percent}٪
                        </b>

                        <div
                          style={{
                            color:
                              'var(--txm)',

                            fontSize: 'var(--fs-cap)',
                          }}
                        >
                          {number(
                            item.used_count
                          )}{' '}

                          استفاده از{' '}

                          {item.max_uses
                            ? number(
                                item.max_uses
                              )
                            : 'نامحدود'}

                          {' • تا '}

                          {item.expires_at ||
                            'بدون انقضا'}
                        </div>
                      </div>

                      <span
                        className={`badge ${
                          item.active
                            ? 'b-grn'
                            : 'b-gray'
                        }`}
                      >
                        {item.active
                          ? 'فعال'
                          : 'غیرفعال'}
                      </span>
                    </div>

                    {/* 🎟 موج D1 — نمایش پلن‌های هدف */}
                    {item.target_plan_ids?.length ? (
                      <div
                        style={{
                          marginTop: 6,
                          color: 'var(--txm)',
                          fontSize: 'var(--fs-cap)',
                        }}
                      >
                        📦 فقط {_fa(item.target_plan_ids.length)} پلن خاص
                      </div>
                    ) : (
                      <div
                        style={{
                          marginTop: 6,
                          color: 'var(--txm)',
                          fontSize: 'var(--fs-cap)',
                        }}
                      >
                        📦 همه پلن‌های فعال
                      </div>
                    )}

                    <div
                      style={{
                        display:
                          'flex',

                        gap: 'var(--sp-2)',

                        marginTop:
                          8,
                      }}
                    >
                      <button
                        className={
                          'btn btn-dark'
                        }
                        style={{
                          flex:
                            1,
                        }}
                        onClick={() =>
                          mutation.mutate({
                            type:
                              'discount-toggle',

                            id:
                              item.code,
                          })
                        }
                      >
                        تغییر وضعیت
                      </button>

                      <button
                        className="btn btn-d"
                        onClick={async () => {
                          const accepted =
                            await confirmAction(
                              'کد حذف شود؟'
                            );

                          if (accepted) {
                            mutation.mutate({
                              type:
                                'discount-delete',

                              id:
                                item.code,
                            });
                          }
                        }}
                      >
                        🗑
                      </button>
                    </div>

                    {/* 🎟 موج D1 — اکشن‌های کمپین */}
                    <div
                      style={{
                        display:
                          'flex',

                        gap: 'var(--sp-2)',

                        marginTop:
                          7,
                      }}
                    >
                      <button
                        className="btn btn-p"
                        style={{ flex: 1 }}
                        disabled={campaignLoading === item.code}
                        onClick={() => handleDiscountPreview(item.code)}
                      >
                        👁 پیش‌نمایش
                      </button>

                      <button
                        className="btn btn-p"
                        style={{ flex: 1 }}
                        disabled={campaignLoading === item.code}
                        onClick={() =>
                          handleDiscountStats(item.code)
                        }
                      >
                        📊 آمار
                      </button>

                      <button
                        className="btn btn-dark"
                        style={{ flex: 1 }}
                        disabled={campaignLoading === item.code}
                        onClick={() =>
                          handleBroadcastStart(item.code)
                        }
                      >
                        📣 انتشار
                      </button>
                    </div>

                    {/* پیش‌نمایش پیام کمپین */}
                    {discountPreview?.code === item.code && (
                      <div
                        className="card"
                        style={{
                          marginTop: 8,
                          background: 'var(--soft-acc)',
                          whiteSpace: 'pre-wrap',
                          fontSize: 'var(--fs-sm)',
                          lineHeight: 1.8,
                        }}
                      >
                        {discountPreview.text}
                      </div>
                    )}

                    {/* آمار کد */}
                    {discountStats?.code === item.code && (
                      <div
                        className="card"
                        style={{
                          marginTop: 8,
                          display: 'grid',
                          gap: 6,
                          fontSize: 'var(--fs-sm)',
                        }}
                      >
                        <b>📊 آمار {item.code}</b>
                        <span>
                          🎟 مصرف: {faNum(discountStats.used_count)}
                          {discountStats.max_uses
                            ? ` از ${faNum(discountStats.max_uses)} — باقی ${faNum(discountStats.remaining_uses ?? 0)}`
                            : ' (نامحدود)'}
                        </span>
                        <span>
                          💳 تأییدشده: {faNum(discountStats.payments?.usage_approved ?? 0)}
                        </span>
                        <span>
                          💰 تخفیف‌داده‌شده: {fmtToman(discountStats.payments?.discount_given ?? 0)}
                        </span>
                        <span>
                          📥 درآمد: {fmtToman(discountStats.payments?.revenue ?? 0)}
                        </span>
                        {discountStats.remaining_uses != null &&
                          discountStats.remaining_uses <= 5 && (
                            <span style={{ color: 'var(--t-warn)' }}>
                              ⚡ فقط {faNum(discountStats.remaining_uses)} استفاده باقی!
                            </span>
                          )}
                      </div>
                    )}

                    {/* وضعیت انتشار */}
                    {broadcastResult?.code === item.code && (
                      <div
                        className="card"
                        style={{
                          marginTop: 8,
                          fontSize: 'var(--fs-sm)',
                        }}
                      >
                        {broadcastResult.state === 'picking' ? (
                          <>
                            <b>📣 انتشار {item.code}</b>
                            <div
                              style={{
                                marginTop: 6,
                                display: 'grid',
                                gap: 6,
                              }}
                            >
                              {['all', 'subscribers', 'no_sub'].map((t) => (
                                <label
                                  key={t}
                                  style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 6,
                                    fontSize: 'var(--fs-sm)',
                                  }}
                                >
                                  <input
                                    type="radio"
                                    name={`bc-${item.code}`}
                                    checked={broadcastTarget === t}
                                    onChange={() => setBroadcastTarget(t)}
                                  />
                                  {t === 'all'
                                    ? '📨 همه کاربران تأییدشده'
                                    : t === 'subscribers'
                                      ? '💎 فقط دارای اشتراک فعال'
                                      : '🆓 فقط بدون اشتراک فعال'}
                                </label>
                              ))}
                              <div style={{ display: 'flex', gap: 7 }}>
                                <button
                                  className="btn btn-p"
                                  style={{ flex: 1 }}
                                  disabled={campaignLoading === item.code}
                                  onClick={() =>
                                    handleBroadcastSend(item.code)
                                  }
                                >
                                  شروع ارسال
                                </button>
                                <button
                                  className="btn btn-dark"
                                  onClick={() => setBroadcastResult(null)}
                                >
                                  انصراف
                                </button>
                              </div>
                            </div>
                          </>
                        ) : broadcastResult.state === 'sending' ? (
                          <div style={{ display: 'grid', gap: 4 }}>
                            <b>⏳ در حال ارسال…</b>
                            {broadcastResult.status && (
                              <span>
                                {faNum(broadcastResult.status.sent || 0)}/
                                {faNum(broadcastResult.status.total || 0)}
                                {broadcastResult.status.blocked
                                  ? ` — 🚫 ${faNum(broadcastResult.status.blocked)}`
                                  : ''}
                              </span>
                            )}
                            {broadcastResult.bid && (
                              <button
                                className="btn btn-dark"
                                style={{ marginTop: 4 }}
                                onClick={() =>
                                  handleBroadcastCancel(
                                    item.code,
                                    broadcastResult.bid,
                                  )
                                }
                              >
                                ⛔ توقف انتشار
                              </button>
                            )}
                          </div>
                        ) : (
                          <div style={{ display: 'grid', gap: 4 }}>
                            <b>
                              {broadcastResult.summary?.status === 'cancelled'
                                ? '⛔ انتشار متوقف شد'
                                : '✅ گزارش انتشار'}
                            </b>
                            {broadcastResult.summary && (
                              <>
                                <span>
                                  👥 {_fa(broadcastResult.summary.total)} نفر — ✅{' '}
                                  {faNum(broadcastResult.summary.sent)} | ❌{' '}
                                  {faNum(broadcastResult.summary.failed)} | 🚫{' '}
                                  {faNum(broadcastResult.summary.blocked)}
                                </span>
                                <span>
                                  📨 نرخ موفقیت:{' '}
                                  {faNum(
                                    broadcastResult.summary.total
                                      ? Math.round(
                                          (broadcastResult.summary.sent /
                                            broadcastResult.summary.total) *
                                            10000,
                                        ) / 100
                                      : 0,
                                  )}
                                  ٪
                                </span>
                              </>
                            )}
                            <button
                              className="btn btn-dark"
                              style={{ marginTop: 4 }}
                              onClick={() => setBroadcastResult(null)}
                            >
                              بستن
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </article>
                )
              )}
            </section>
          </>
        )}
      </main>
    </>
  );
}

// ── کمک‌نمایش ──
function faNum(n) {
  return String(Number(n) || 0).replace(/[0-9]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d]);
}
function fmtToman(n) {
  const v = Number(n) || 0;
  return v.toLocaleString('en-US').replace(/,/g, '٬') + ' تومان';
}
function _fa(n) {
  return faNum(n);
}
