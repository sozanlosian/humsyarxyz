import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import api from '../../lib/api';
import Header from '../../components/layout/Header';
import PageError from '../../components/shared/PageError';
import EmptyState from '../../components/shared/EmptyState';
import Switch from '../../components/shared/Switch';

import {
  Spinner,
} from '../../components/shared/Loading';

import {
  NotificationsSkeleton,
} from '../../components/shared/skeletons';

import {
  haptic,
  hapticNotif,
} from '../../lib/telegram';

import {
  useUIStore,
} from '../../stores/uiStore';


const TONES = {
  /* 🧠 موج N3 — آیکون/تُن هر دسته‌ی کاتالوگ
     (منابع وب کمک‌رنگ سلفیِ خودِ label است) */
  resources: ['📚', 'var(--t-ok)', 'var(--soft-ok)'],
  references: ['📖', 'var(--t-pur)', 'var(--soft-pur)'],
  basic_sci: ['🩺', 'var(--t-info)', 'var(--soft-info)'],
  qbank: ['❓', 'var(--t-pur)', 'var(--soft-pur)'],
  schedule: ['📅', 'var(--t-acc)', 'var(--soft-acc)'],
  exams: ['📝', 'var(--t-err)', 'var(--soft-err)'],
  grades: ['📊', 'var(--t-ok)', 'var(--soft-ok)'],
  tickets: ['🎫', 'var(--t-ok)', 'var(--soft-ok)'],
  subscription: ['💳', 'var(--t-warn)', 'var(--soft-warn)'],
  discounts: ['🎁', 'var(--t-warn)', 'var(--soft-warn)'],
  ai: ['🤖', 'var(--t-info)', 'var(--soft-info)'],
  announcement: ['📢', 'var(--t-acc)', 'var(--soft-acc)'],
  polls: ['🗳️', 'var(--t-warn)', 'var(--soft-warn)'],
  gamification: ['🎮', 'var(--t-pur)', 'var(--soft-pur)'],
  profile: ['👤', 'var(--t-ok)', 'var(--soft-ok)'],
  system: ['⚙️', 'var(--txm)', 'var(--bd)'],

  /* کلیدهای قدیمی (اگر سرور کاتالوگ کهنه بدهد) */
  new_resources: ['📚', 'var(--t-ok)', 'var(--soft-ok)'],
  exam: ['📝', 'var(--t-err)', 'var(--soft-err)'],
  makeup: ['🔄', 'var(--t-warn)', 'var(--soft-warn)'],
  daily_question: ['🧪', 'var(--t-pur)', 'var(--soft-pur)'],
  edu_message: ['🎓', 'var(--t-info)', 'var(--soft-info)'],
  general: ['📢', 'var(--t-acc)', 'var(--soft-acc)'],
  grade_release: ['📊', 'var(--t-ok)', 'var(--soft-ok)'],
  sub_expiry: ['💳', 'var(--t-warn)', 'var(--soft-warn)'],
};



export function Notifications() {
  const toast = useUIStore(
    (state) => state.toast
  );

  const queryClient =
    useQueryClient();


  const {
    data = [],
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: [
      'notification-settings',
    ],

    queryFn: () =>
      api
        .get(
          '/api/notifications/settings'
        )
        .then(
          (response) =>
            response.data
              ?.settings || []
        ),
  });


  const refresh = () =>
    queryClient.invalidateQueries({
      queryKey: [
        'notification-settings',
      ],
    });


  const toggleMutation =
    useMutation({
      mutationFn: ({
        key,
        enabled,
      }) =>
        api.patch(
          '/api/notifications/settings',
          {
            settings: {
              [key]: enabled,
            },
          }
        ),

      onSuccess: async () => {
        hapticNotif(
          'success'
        );

        await refresh();
      },

      onError: () =>
        toast(
          'ذخیره تنظیمات انجام نشد',
          'error'
        ),
    });


  const allMutation =
    useMutation({
      mutationFn: (enabled) =>
        api.patch(
          '/api/notifications/settings/all',
          {
            enabled,
          }
        ),

      onSuccess: async (
        _,
        enabled
      ) => {
        hapticNotif(
          'success'
        );

        toast(
          enabled
            ? 'همه اعلان‌ها فعال شدند'
            : 'همه اعلان‌ها غیرفعال شدند',

          'success'
        );

        await refresh();
      },

      onError: () =>
        toast(
          'تغییر تنظیمات انجام نشد',
          'error'
        ),
    });


  const settings =
    Array.isArray(data)
      ? data
      : [];


  const enabledCount =
    settings.filter(
      (item) =>
        item.enabled
    ).length;


  const allEnabled =
    settings.length > 0 &&
    enabledCount ===
      settings.length;


  const pending =
    toggleMutation.isPending ||
    allMutation.isPending;


  return (
    <>
      <Header
        title="اعلان‌ها"
        subtitle={
          'یادآوری‌ها و اطلاع‌رسانی'
        }
      />

      <main className="page fade-up">
        <section
          className={
            'card card-glow hero-card'
          }
          style={{
            marginBottom: 'var(--sp-4)',
          }}
        >
          <div
            style={{
              display: 'flex',

              alignItems:
                'center',

              gap:
                13,
            }}
          >
            <div
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
                  'var(--grad-brand)',

                boxShadow:
                  'var(--shd-glow)',

                fontSize:
                  24,
              }}
            >
              🔔
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
                مرکز اعلان هامزیار
              </div>

              <div
                style={{
                  fontSize: 'var(--fs-lg)',

                  fontWeight:
                    900,

                  marginTop:
                    2,
                }}
              >
                {enabledCount} از{' '}

                {settings.length ||
                  0}{' '}

                اعلان فعال
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
                فقط پیام‌هایی را دریافت
                کنید که برایتان مهم‌اند.
              </div>
            </div>

            <div
              style={{
                display:
                  'grid',

                width:
                  48,

                height:
                  48,

                placeItems:
                  'center',

                color:
                  allEnabled
                    ? 'var(--ok)'
                    : 'var(--warn)',

                background:
                  allEnabled
                    ? 'var(--soft-ok)'
                    : 'var(--soft-warn)',

                borderRadius:
                  '50%',

                fontSize: 'var(--fs-sm)',

                fontWeight:
                  900,
              }}
            >
              {settings.length
                ? Math.round(
                    (
                      enabledCount /
                      settings.length
                    ) * 100
                  )
                : 0}
              ٪
            </div>
          </div>
        </section>


        <div
          style={{
            display:
              'flex',

            gap:
              8,

            marginBottom: 'var(--sp-4)',
          }}
        >
          <button
            className="btn btn-p"
            style={{
              flex: 1,
            }}
            disabled={
              pending ||
              allEnabled
            }
            onClick={() => {
              haptic();

              allMutation.mutate(
                true
              );
            }}
          >
            فعال‌کردن همه
          </button>

          <button
            className="btn btn-dark"
            style={{
              flex: 1,
            }}
            disabled={
              pending ||
              enabledCount === 0
            }
            onClick={() => {
              haptic();

              allMutation.mutate(
                false
              );
            }}
          >
            خاموش‌کردن همه
          </button>
        </div>


        <div className="sec-title">
          تنظیم جداگانه
        </div>


        {isLoading ? (
          <NotificationsSkeleton />
        ) : isError ? (
          <PageError
            text="دریافت تنظیمات انجام نشد."
            onRetry={() => refetch()}
          />
        ) : settings.length ===
          0 ? (
          <EmptyState icon="🔔">
            تنظیمی برای اعلان‌ها تعریف
            نشده است.
          </EmptyState>
        ) : (
          <section
            className="card"
            style={{
              padding:
                '2px 14px',
            }}
          >
            {settings.map(
              (
                item,
                index
              ) => {
                const [
                  icon,
                  color,
                  soft,
                ] = (
                  TONES[item.key] || [
                    '🔔',

                    'var(--t-acc)',

                    'var(--soft-acc)',
                  ]
                );

                return (
                  <div
                    key={item.key}
                    style={{
                      display:
                        'flex',

                      alignItems:
                        'center',

                      minHeight:
                        68,

                      gap:
                        11,

                      padding:
                        '9px 0',

                      borderBottom:
                        index <
                        settings.length -
                          1
                          ? '1px solid var(--bd)'
                          : 0,
                    }}
                  >
                    <span
                      style={{
                        display:
                          'grid',

                        flex:
                          '0 0 42px',

                        height:
                          42,

                        placeItems:
                          'center',

                        color,

                        background:
                          soft,

                        borderRadius: 'var(--r-md)',

                        fontSize: 'var(--fs-xl)',
                      }}
                    >
                      {icon}
                    </span>

                    <div
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
                            'block',

                          fontSize: 'var(--fs-sm)',
                        }}
                      >
                        {item.label ||
                          'اعلان'}
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

                          lineHeight:
                            1.5,
                        }}
                      >
                        {item.desc ||
                          ''}
                      </span>
                    </div>

                    <Switch
                      on={Boolean(
                        item.enabled
                      )}
                      loading={pending}
                      label={
                        `تغییر ${
                          item.label
                        }`
                      }
                      onToggle={(
                        next
                      ) =>
                        toggleMutation
                          .mutate({
                            key:
                              item.key,

                            enabled:
                              next,
                          })
                      }
                    />
                  </div>
                );
              }
            )}
          </section>
        )}


        {pending && (
          <div
            style={{
              display:
                'flex',

              alignItems:
                'center',

              justifyContent:
                'center',

              gap: 'var(--sp-2)',

              marginTop:
                12,

              color:
                'var(--txm)',

              fontSize: 'var(--fs-cap)',
            }}
          >
            <Spinner size={14} />

            در حال ذخیره تنظیمات...
          </div>
        )}
      </main>
    </>
  );
}
