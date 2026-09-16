import StatTile from '../../components/shared/StatTile';

import { number } from '../../lib/format';

import {
  useMutation,
  useQuery,
} from '@tanstack/react-query';

import {
  useNavigate,
} from 'react-router-dom';

import api from '../../lib/api';
import Header from '../../components/layout/Header';
import PageError from '../../components/shared/PageError';

import {
  Spinner,
} from '../../components/shared/Loading';

import {
  AdminHomeSkeleton,
} from '../../components/shared/skeletons';

import {
  haptic,
  hapticNotif,
} from '../../lib/telegram';

import {
  useUIStore,
} from '../../stores/uiStore';





const SECTIONS = [
  {
    icon: '👥',
    title: 'مدیریت کاربران',
    description:
      'جست‌وجو، تأیید، ویرایش و تعلیق',
    route: '/admin/users',
    color: 'var(--t-acc)',
    soft:
      'var(--soft-acc)',
  },

  {
    icon: '💳',
    title: 'اشتراک و پرداخت',
    description:
      'پلن‌ها، رسیدها، مشترکین و تخفیف',
    route:
      '/admin/subscription',
    color: 'var(--t-ok)',
    soft:
      'var(--soft-ok)',
  },

  {
    icon: '🤖',
    title: 'مدیریت هوشیار',
    description:
      'مدل، API Key، سهمیه و گزارش‌ها',
    route: '/admin/ai',
    color: 'var(--t-pur)',
    soft:
      'var(--soft-pur)',
  },

  {
    icon: '📅',
    title: 'مدیریت ورودی‌ها',
    description:
      'ورودی‌ها، گروه‌ها و آمار دانشجویان',
    route: '/admin/intakes',
    color: 'var(--t-ok)',
    soft:
      'var(--soft-ok)',
  },

  {
    icon: '🎓',
    title: 'مدیران محتوا',
    description:
      'اعطا و لغو دسترسی محتوا',
    route:
      '/admin/content-admins',
    color: 'var(--t-pur)',
    soft:
      'var(--soft-pur)',
  },

  {
    icon: '🎫',
    title: 'تیکت‌های پشتیبانی',
    description:
      'پاسخ، بستن و بازگشایی تیکت',
    route: '/admin/tickets',
    color: 'var(--t-warn)',
    soft:
      'var(--soft-warn)',
  },

  {
    icon: '📣',
    title: 'ارسال همگانی',
    description:
      'ارسال هدفمند به کاربران',
    route: '/admin/broadcast',
    color: 'var(--t-info)',
    soft:
      'var(--soft-info)',
  },

  {
    icon: '📊',
    title: 'نظرسنجی',
    description:
      'ساخت نظرسنجی در کانال',
    route: '/admin/poll',
    color: 'var(--t-acc)',
    soft:
      'var(--soft-acc)',
  },

  {
    icon: '🔔',
    title: 'مدیریت اعلان‌ها',
    description:
      'تنظیم، تاریخچه و ارسال مجدد',
    route:
      '/admin/notifications',
    color: 'var(--t-warn)',
    soft:
      'var(--soft-warn)',
  },

  {
    icon: '🚫',
    title: 'فهرست مسدودها',
    description:
      'مشاهده و رفع مسدودیت کاربران',
    route: '/admin/blacklist',
    color: 'var(--t-err)',
    soft:
      'var(--soft-err)',
  },

  {
    icon: '📚',
    title: 'پنل محتوا',
    description:
      'سؤال، منابع، برنامه و نمرات',
    route: '/admin/content',
    color: 'var(--t-ok)',
    soft:
      'var(--soft-ok)',
  },
  {
    icon: '📊',
    title: 'آمار و تحلیل',
    description:
      'رشد، فعالیت و گزارش‌های کلیدی',
    route: '/admin/analytics',
    color: 'var(--t-info)',
    soft:
      'var(--soft-info)',
  },

  {
    icon: '🛡',
    title: 'مدیریت نقش‌ها',
    description:
      'نقش‌ها و مجوزهای RBAC',
    route: '/admin/roles',
    color: 'var(--t-pur)',
    soft:
      'var(--soft-pur)',
  },

  {
    icon: '📜',
    title: 'گزارش فعالیت‌ها',
    description:
      'لاگ حساس ادمین‌ها (Audit)',
    route: '/admin/audit',
    color: 'var(--t-warn)',
    soft:
      'var(--soft-warn)',
  },

  {
    icon: '⚙️',
    title: 'تنظیمات سیستم',
    description:
      'هوش مصنوعی، اعلان و گریندها',
    route: '/admin/settings',
    color: 'var(--t-err)',
    soft:
      'var(--soft-err)',
  },

];



export default function AdminHome() {
  const navigate =
    useNavigate();

  const toast = useUIStore(
    (state) => state.toast
  );


  const {
    data: stats,
    isLoading,
    isError,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey:
      ['admin-stats'],

    queryFn: () =>
      api
        .get('/api/admin/stats')
        .then(
          (response) =>
            response.data
        ),

    refetchInterval:
      60_000,
  });


  const {
    data: bot,
  } = useQuery({
    queryKey:
      ['admin-bot-status'],

    queryFn: () =>
      api
        .get(
          '/api/admin/bot-status'
        )
        .then(
          (response) =>
            response.data
        ),

    staleTime:
      30_000,
  });


  const {
    data: subscription,
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

    staleTime:
      30_000,
  });


  const {
    data: aiStatus,
  } = useQuery({
    queryKey: [
      'ai-admin-config',
    ],

    queryFn: () =>
      api
        .get(
          '/api/ai-admin/config'
        )
        .then(
          (response) =>
            response.data
        ),

    staleTime:
      30_000,
  });


  const exportMutation =
    useMutation({
      mutationFn: () =>
        api.post(
          '/api/admin/export/excel'
        ),

      onSuccess: (
        response
      ) => {
        hapticNotif(
          'success'
        );

        toast(
          response.data
            ?.message ||
            'خروجی در ربات ارسال می‌شود',

          'success'
        );
      },

      onError: () =>
        toast(
          'درخواست خروجی انجام نشد',
          'error'
        ),
    });


  const open = (route) => {
    haptic('light');
    navigate(route);
  };


  const pendingUsers =
    number(
      stats?.users?.pending
    );

  const openTickets =
    number(
      stats?.tickets?.open
    );

  const openReports =
    number(
      stats?.reports?.open
    );

  const pendingPayments =
    number(
      subscription
        ?.stats
        ?.pending
    );


  return (
    <>
      <Header
        title="پنل مدیریت"
        subtitle={
          'کنترل مرکزی هامزیار'
        }
        right={
          <button
            type="button"
            onClick={() =>
              refetch()
            }
            disabled={
              isRefetching
            }
            aria-label="به‌روزرسانی"
            style={{
              width: 36,
              height: 36,
              borderRadius: 'var(--r-md)',
              background:
                'var(--elev)',
              border:
                '1px solid var(--bd)',
              cursor: 'pointer',
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
            padding: 18,
            marginBottom: 'var(--sp-4)',

            background:
              'linear-gradient(145deg,var(--soft-warn-2),var(--surf-card) 55%,var(--soft-acc))',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 13,
            }}
          >
            <span
              style={{
                display: 'grid',
                width: 56,
                height: 56,
                placeItems: 'center',
                borderRadius: 'var(--r-lg)',

                background:
                  'linear-gradient(135deg,var(--warn-dim),var(--warn))',

                fontSize: 27,
              }}
            >
              👑
            </span>

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
                مرکز فرمان هامزیار
              </div>

              <b
                style={{
                  display: 'block',
                  fontSize: 'var(--fs-xl)',
                  marginTop: 2,
                }}
              >
                مدیریت کل سامانه
              </b>

              <div
                style={{
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 5,
                  marginTop: 6,
                }}
              >
                <span className="badge b-grn">
                  {bot?.db_status ||
                    'در حال بررسی'}
                </span>

                <span className="badge b-acc">
                  Ping:{' '}

                  {bot?.db_ping ||
                    '—'}
                </span>

                <span
                  className={`badge ${
                    aiStatus?.enabled
                      ? 'b-pur'
                      : 'b-gray'
                  }`}
                >
                  هوشیار{' '}

                  {aiStatus?.enabled
                    ? 'فعال'
                    : 'خاموش'}
                </span>
              </div>
            </div>
          </div>
        </section>


        {isLoading ? (
          <AdminHomeSkeleton />
        ) : isError ? (
          <PageError
            text="دریافت آمار انجام نشد."
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
            <StatTile variant="row"
              icon="👥"
              value={
                number(
                  stats?.users
                    ?.total
                )
              }
              label="کاربر فعال"
              color="var(--t-acc)"
              soft={
                'var(--soft-acc)'
              }
            />

            <StatTile variant="row"
              icon="⏳"
              value={
                pendingUsers
              }
              label="کاربر منتظر"
              color="var(--t-warn)"
              soft={
                'var(--soft-warn)'
              }
            />

            <StatTile variant="row"
              icon="💎"
              value={
                number(
                  subscription
                    ?.stats
                    ?.active
                )
              }
              label="مشترک فعال"
              color="var(--t-ok)"
              soft={
                'var(--soft-ok)'
              }
            />

            <StatTile variant="row"
              icon="💳"
              value={
                pendingPayments
              }
              label="رسید منتظر"
              color="var(--t-err)"
              soft={
                'var(--soft-err)'
              }
            />
          </section>
        )}


        {(
          pendingUsers > 0 ||
          openTickets > 0 ||
          openReports > 0 ||
          pendingPayments > 0
        ) && (
          <section
            className="card"
            style={{
              marginBottom:
                15,

              borderColor:
                'var(--bd-warn)',
            }}
          >
            <div className="sec-title">
              ⚠️ نیازمند رسیدگی
            </div>

            <div
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: 6,
              }}
            >
              {pendingUsers >
                0 && (
                <span className="badge b-yel">
                  {pendingUsers} کاربر جدید
                </span>
              )}

              {openTickets >
                0 && (
                <span className="badge b-red">
                  {openTickets} تیکت باز
                </span>
              )}

              {openReports >
                0 && (
                <span className="badge b-pur">
                  {openReports} گزارش
                </span>
              )}

              {pendingPayments >
                0 && (
                <span className="badge b-grn">
                  {pendingPayments} رسید
                  منتظر
                </span>
              )}
            </div>
          </section>
        )}


        <div className="sec-title">
          ابزارهای مدیریت
        </div>

        <section
          style={{
            display: 'grid',
            gap: 9,
          }}
        >
          {SECTIONS.map(
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
                display: 'flex',
                alignItems: 'center',
                width: '100%',
                gap: 11,
                padding: 13,
                textAlign: 'right',

                animationDelay:
                  `${
                    index * 28
                  }ms`,
              }}
            >
              <span
                style={{
                  display: 'grid',
                  width: 44,
                  height: 44,
                  placeItems: 'center',
                  borderRadius: 'var(--r-md)',
                  color: item.color,
                  background: item.soft,
                  fontSize: 'var(--fs-xl)',
                }}
              >
                {item.icon}
              </span>

              <span
                style={{
                  flex: 1,
                }}
              >
                <b
                  style={{
                    display: 'block',
                    fontSize: 'var(--fs-sm)',
                  }}
                >
                  {item.title}
                </b>

                <span
                  style={{
                    display: 'block',
                    color:
                      'var(--txm)',
                    fontSize: 'var(--fs-cap)',
                    marginTop: 3,
                  }}
                >
                  {item.description}
                </span>
              </span>

              {item.route ===
                '/admin/subscription' &&
                pendingPayments >
                  0 && (
                <span className="badge b-red">
                  {pendingPayments}
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
          ))}
        </section>


        <button
          className={
            'btn btn-dark btn-full'
          }
          style={{
            marginTop:
              12,
          }}
          disabled={
            exportMutation
              .isPending
          }
          onClick={() =>
            exportMutation.mutate()
          }
        >
          {exportMutation
            .isPending ? (
            <Spinner size={15} />
          ) : (
            '📥 دریافت خروجی Excel در ربات'
          )}
        </button>
      </main>
    </>
  );
}
