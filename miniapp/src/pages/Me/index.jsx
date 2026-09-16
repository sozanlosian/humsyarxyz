import MenuRow from '../../components/shared/MenuRow';

import { number, percent } from '../../lib/format';

import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import api from '../../lib/api';
import Header from '../../components/layout/Header';
import PageError from '../../components/shared/PageError';
import {
  Spinner,
} from '../../components/shared/Loading';

import {
  MeSkeleton,
} from '../../components/shared/skeletons';
import { haptic } from '../../lib/telegram';
import { useAuthStore } from '../../stores/authStore';


export default function Me() {
  const navigate =
    useNavigate();

  const authUser =
    useAuthStore(
      (state) => state.user
    );

  const {
    data: profile,
    isLoading,
    isError,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: [
      'profile',
    ],

    queryFn: () =>
      api
        .get('/api/profile')
        .then(
          (response) =>
            response.data
        ),

    staleTime:
      3 * 60 * 1000,
  });

  const {
    data: rank,
  } = useQuery({
    queryKey: [
      'rank',
    ],

    queryFn: () =>
      api
        .get(
          '/api/profile/rank'
        )
        .then(
          (response) =>
            response.data
        ),

    staleTime:
      5 * 60 * 1000,
  });

  /* 💙 حمایت مالی — همگام با ربات */
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

  /* 🔔 موج ۴.۹۰ — بج خوانده‌نشده‌های مرکز
     اعلان. کلید عمداً با صفحه‌ی مرکز اعلان
     یکی است (همان کش مشترک) ولی بدون ایمپورت
     استاتیک آن فایل تا code-split نشکند */
  const {
    data: inbox,
  } = useQuery({
    queryKey: ['notif-inbox'],

    queryFn: () =>
      api
        .get('/api/notifications/inbox')
        .then(
          (response) =>
            response.data
        ),

    staleTime: 15_000,
    retry: false,
  });

  const notifUnread = number(
    inbox?.unread
  );

  const {
    data: subscription,
  } = useQuery({
    queryKey: [
      'sub-status',
    ],

    queryFn: () =>
      api
        .get(
          '/api/subscription/status'
        )
        .then(
          (response) =>
            response.data
        ),

    staleTime:
      5 * 60 * 1000,
  });

  const user =
    profile?.user ||
    authUser ||
    {};

  const stats =
    profile?.stats || {};

  const readiness =
    percent(
      stats.percentage
    );

  const openTickets =
    number(
      profile?.tickets?.open
    );

  /* 🛡 RBAC-W3 (افزایشی): هر مجوز RBAC هم ورودی
     مدیریت را فعال می‌کند؛ سطح دسترسی واقعی را
     سرور با require_perm اعمال می‌کند (§۸) */
  const manager =
    [
      'admin',
      'content_admin',
    ].includes(user.role) ||
    (user.perms || []).length > 0;

  /* برچسب نقش: اولویت با نقش‌های دیتابیسی
     (roles_detail از /api/profile)، fallback به
     نقش قدیمی — هیچ برچسب جدیدی هاردکد نشده */
  const rbacPrimary =
    (profile?.user || user).roles_detail?.[0];

  const roleLabel = rbacPrimary
    ? `${rbacPrimary.icon} ${rbacPrimary.label}`
    : {
      admin: 'مدیر اصلی',

      content_admin:
        'ادمین ارشد محتوا',

      support:
        'پشتیبان',
    }[user.role] ||
      'دانشجو';

  return (
    <>
      <Header
        title="حساب من"
        subtitle={
          'پروفایل، خدمات و تنظیمات'
        }
        back={false}
      />

      <main className="page fade-up">
        {isLoading ? (
          <MeSkeleton />
        ) : isError ? (
          <PageError
            text="دریافت اطلاعات حساب انجام نشد."
            onRetry={() => refetch()}
            pending={isRefetching}
          />
        ) : (
          <div
            style={{
              display: 'grid',
              gap: 13,
            }}
          >
            <section
              className={
                'card card-glow card-tap ' +
                'hero-card'
              }
              role="button"
              tabIndex={0}
              onClick={() =>
                navigate(
                  '/me/profile'
                )
              }
              onKeyDown={(event) => {
                if (
                  event.key ===
                  'Enter'
                ) {
                  navigate(
                    '/me/profile'
                  );
                }
              }}
              style={{
                cursor: 'pointer',
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
                  className="avatar"
                  style={{
                    width: 58,
                    height: 58,
                    fontSize: 23,
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
                  <h2
                    style={{
                      overflow:
                        'hidden',

                      fontSize: 'var(--fs-xl)',

                      fontWeight:
                        900,

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
                  </h2>

                  {/* 🏷 Identity v1 —
                      نام واقعی زیر لقب */}
                  {user.nickname && (
                    <div
                      style={{
                        color:
                          'var(--txm)',

                        fontSize: 'var(--fs-cap)',

                        marginTop:
                          2,
                      }}
                    >
                      نام واقعی:{' '}
                      {user.name ||
                        '—'}
                    </div>
                  )}

                  <div
                    style={{
                      display: 'flex',

                      flexWrap:
                        'wrap',

                      gap:
                        5,

                      marginTop:
                        6,
                    }}
                  >
                    <span className="badge b-acc">
                      ورودی{' '}
                      {user.intake ||
                        '—'}
                    </span>

                    <span className="badge b-acc">
                      گروه{' '}
                      {user.group ||
                        '—'}
                    </span>

                    <span className="badge b-pur">
                      {roleLabel}
                    </span>
                  </div>
                </div>

                <span
                  style={{
                    color:
                      'var(--txm)',

                    fontSize: 'var(--fs-xl)',
                  }}
                >
                  ←
                </span>
              </div>

              <div
                style={{
                  marginTop: 15,
                }}
              >
                <div
                  style={{
                    display: 'flex',

                    justifyContent:
                      'space-between',

                    marginBottom:
                      6,
                  }}
                >
                  <span
                    style={{
                      color:
                        'var(--txm)',

                      fontSize: 'var(--fs-cap)',
                    }}
                  >
                    آمادگی تستی
                  </span>

                  <b
                    style={{
                      color:
                        'var(--acc2)',

                      fontSize: 'var(--fs-meta)',
                    }}
                  >
                    {readiness}٪
                  </b>
                </div>

                <div className="pbar">
                  <div
                    className="pbar-f"
                    style={{
                      width:
                        `${readiness}%`,
                    }}
                  />
                </div>

                <div
                  style={{
                    display: 'flex',

                    justifyContent:
                      'space-between',

                    marginTop: 'var(--sp-2)',

                    color:
                      'var(--txm)',

                    fontSize: 'var(--fs-cap)',
                  }}
                >
                  <span>
                    {number(
                      stats
                        .total_answers
                    )}{' '}

                    سؤال •{' '}

                    {number(
                      stats
                        .correct_answers
                    )}{' '}

                    صحیح
                  </span>

                  {rank?.rank && (
                    <span
                      style={{
                        color:
                          'var(--warn)',
                      }}
                    >
                      🏅 رتبه{' '}

                      {number(
                        rank.rank
                      )}{' '}

                      از{' '}

                      {number(
                        rank.total_users
                      )}
                    </span>
                  )}
                </div>
              </div>
            </section>

            {subscription?.active ? (
              <section
                className="card"
                style={{
                  borderColor:
                    'var(--bd-ok)',

                  background:
                    'linear-gradient(145deg,var(--soft-ok),var(--surf-card))',
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems:
                      'center',
                    gap: 11,
                  }}
                >
                  <span
                    style={{
                      display:
                        'grid',

                      width:
                        44,

                      height:
                        44,

                      placeItems:
                        'center',

                      borderRadius: 'var(--r-md)',

                      background:
                        'var(--soft-ok)',

                      fontSize:
                        21,
                    }}
                  >
                    💎
                  </span>

                  <div
                    style={{
                      flex: 1,
                    }}
                  >
                    <b
                      style={{
                        color:
                          'var(--ok)',

                        fontSize: 'var(--fs-sm)',
                      }}
                    >
                      اشتراک{' '}

                      {subscription
                        .plan_name ||
                        'هامزیار'}{' '}

                      فعال است
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
                        subscription
                          .days_left
                      )}{' '}

                      روز باقی‌مانده

                      {subscription
                        .expires
                        ? ` • تا ${subscription.expires}`
                        : ''}
                    </div>
                  </div>

                  <button
                    className={
                      'btn btn-dark'
                    }
                    style={{
                      minHeight:
                        34,

                      padding:
                        '6px 10px',

                      fontSize: 'var(--fs-cap)',
                    }}
                    onClick={() =>
                      navigate(
                        '/me/subscription'
                      )
                    }
                  >
                    مدیریت
                  </button>
                </div>
              </section>
            ) : subscription ? (
              <button
                type="button"
                className={
                  'card card-tap'
                }
                onClick={() =>
                  navigate(
                    '/me/subscription'
                  )
                }
                style={{
                  width:
                    '100%',

                  display:
                    'flex',

                  alignItems:
                    'center',

                  gap:
                    11,

                  textAlign:
                    'right',

                  borderColor:
                    'var(--bd-warn)',

                  background:
                    'linear-gradient(145deg,var(--soft-warn),var(--surf-card))',
                }}
              >
                <span
                  style={{
                    fontSize: 23,
                  }}
                >
                  🔐
                </span>

                <span
                  style={{
                    flex: 1,
                  }}
                >
                  <b
                    style={{
                      color:
                        'var(--warn)',

                      fontSize: 'var(--fs-sm)',
                    }}
                  >
                    اشتراک فعال نیست
                  </b>

                  <span
                    style={{
                      display:
                        'block',

                      color:
                        'var(--txm)',

                      fontSize: 'var(--fs-cap)',

                      marginTop:
                        2,
                    }}
                  >
                    برای دسترسی کامل، پلن
                    مناسب را انتخاب کنید.
                  </span>
                </span>

                <span className="badge b-yel">
                  مشاهده پلن‌ها
                </span>
              </button>
            ) : null}

            <section>
              <div className="sec-title">
                👤 حساب و تنظیمات
              </div>

              <div
                className="card"
                style={{
                  padding:
                    '0 14px',
                }}
              >
                <MenuRow
                  icon="👤"
                  title={
                    'پروفایل و اطلاعات تحصیلی'
                  }
                  description={
                    'نام، شماره دانشجویی، ورودی و گروه'
                  }
                  onClick={() =>
                    navigate(
                      '/me/profile'
                    )
                  }
                />

                <MenuRow
                  icon="🏅"
                  title={
                    'نشان‌های من'
                  }
                  description={
                    'کلکسیون نشان‌ها و شوکیس'
                  }
                  tone="yellow"
                  onClick={() =>
                    navigate(
                      '/me/badges'
                    )
                  }
                />

                <MenuRow
                  icon="🏟️"
                  title={
                    'میدان رقابت'
                  }
                  description={
                    'لیدربرد هفته، ماه و سیزن'
                  }
                  tone="green"
                  onClick={() =>
                    navigate(
                      '/leaderboard'
                    )
                  }
                />

                <MenuRow
                  icon="🔔"
                  title={
                    'مرکز اعلان‌ها'
                  }
                  description={
                    'همه‌ی رویدادهای مهم حسابت،'
                    + ' یک‌جا'
                  }
                  badge={
                    notifUnread
                      ? notifUnread
                          .toLocaleString('fa-IR')
                      : ''
                  }
                  tone="yellow"
                  onClick={() =>
                    navigate(
                      '/me/notifications/inbox'
                    )
                  }
                />

                <MenuRow
                  icon="⚙️"
                  title={
                    'تنظیمات اعلان‌ها'
                  }
                  description={
                    'مدیریت یادآوری کلاس، امتحان و محتوا'
                  }
                  tone="purple"
                  onClick={() =>
                    navigate(
                      '/me/notifications'
                    )
                  }
                  last
                />
              </div>
            </section>

            <section>
              <div className="sec-title">
                🆘 پشتیبانی و راهنما
              </div>

              <div
                className="card"
                style={{
                  padding:
                    '0 14px',
                }}
              >
                <MenuRow
                  icon="🎫"
                  title={
                    'تیکت پشتیبانی'
                  }
                  description={
                    'گفت‌وگو با تیم پشتیبانی'
                  }
                  badge={
                    openTickets
                      ? `${openTickets} باز`
                      : ''
                  }
                  tone="green"
                  onClick={() =>
                    navigate(
                      '/me/tickets'
                    )
                  }
                />

                <MenuRow
                  icon="❓"
                  title={
                    'سؤالات متداول'
                  }
                  description={
                    'پاسخ سریع به پرسش‌های رایج'
                  }
                  tone="purple"
                  onClick={() =>
                    navigate(
                      '/me/faq'
                    )
                  }
                />

                <MenuRow
                  icon="🚩"
                  title={
                    'گزارش ایراد محتوا'
                  }
                  description={
                    'اعلام مشکل سؤال، جزوه یا فایل'
                  }
                  tone="red"
                  onClick={() =>
                    navigate(
                      '/me/reports'
                    )
                  }
                  last={!showDonation}
                />

                {/* 💙 فقط وقتی مدیر فعال
                    کرده — سینک با ربات */}
                {showDonation && (
                  <MenuRow
                    icon="💙"
                    title={
                      'حمایت از هامزیار'
                    }
                    description={
                      'کمک به ادامه‌دار ماندن و رشد هامزیار'
                    }
                    tone="red"
                    onClick={() => {
                      try {
                        window.Telegram
                          ?.WebApp
                          ?.openLink?.(
                            donation.link
                          ) ||
                          window.open(
                            donation.link,
                            '_blank',
                            'noopener'
                          );
                      } catch (_) {
                        window.open(
                          donation.link,
                          '_blank',
                          'noopener'
                        );
                      }
                    }}
                    last
                  />
                )}
              </div>
            </section>

            {manager && (
              <section>
                <div className="sec-title">
                  ⚙️ ابزارهای مدیریتی
                </div>

                <div
                  className="card"
                  style={{
                    padding:
                      '0 14px',

                    borderColor:
                      'var(--bd-warn)',
                  }}
                >
                  {user.role ===
                    'admin' && (
                    <MenuRow
                      icon="👑"
                      title={
                        'پنل مدیریت'
                      }
                      description={
                        'کاربران، ارتباطات و تنظیمات'
                      }
                      tone="yellow"
                      onClick={() =>
                        navigate(
                          '/admin'
                        )
                      }
                    />
                  )}

                  <MenuRow
                    icon="🎓"
                    title={
                      'مدیریت محتوا'
                    }
                    description={
                      'سؤال‌ها، برنامه، نمرات و منابع'
                    }
                    tone="purple"
                    onClick={() =>
                      navigate(
                        '/admin/content'
                      )
                    }
                    last
                  />
                </div>
              </section>
            )}
          </div>
        )}
      </main>
    </>
  );
}
