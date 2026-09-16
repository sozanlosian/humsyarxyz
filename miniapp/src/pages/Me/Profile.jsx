import Switch from '../../components/shared/Switch';

import StatTile from '../../components/shared/StatTile';

import PageError from '../../components/shared/PageError';

import { faDate, number, percent, errorText } from '../../lib/format';

import { useState } from 'react';

import {
  useNavigate,
} from 'react-router-dom';

import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import api from '../../lib/api';
import Header from '../../components/layout/Header';

import PrestigeHero from '../../components/shared/PrestigeHero';

import {
  Spinner,
} from '../../components/shared/Loading';

import {
  ProfileSkeleton,
} from '../../components/shared/skeletons';

import {
  haptic,
  hapticNotif,
} from '../../lib/telegram';

import {
  useUIStore,
} from '../../stores/uiStore';

import {
  useAuthStore,
} from '../../stores/authStore';


function Picker({
  title,
  options,
  current,
  loading,
  pending,
  onSelect,
  onClose,
}) {
  return (
    <div
      className="more-sheet"
      onClick={onClose}
      role="presentation"
    >
      <div
        className={
          'more-sheet__panel ' +
          'glass sheet-in'
        }
        role="dialog"
        aria-modal="true"
        onClick={(event) =>
          event.stopPropagation()
        }
      >
        <div className="more-sheet__handle" />

        <div className="more-sheet__title">
          {title}
        </div>

        {loading ? (
          <div
            style={{
              display: 'grid',
              placeItems: 'center',
              padding: 24,
            }}
          >
            <Spinner />
          </div>
        ) : options.length === 0 ? (
          <div className="empty">
            گزینه‌ای موجود نیست.
          </div>
        ) : (
          options.map((item) => (
            <button
              type="button"
              key={item.value}
              className="more-sheet__item"
              disabled={pending}
              onClick={() => {
                if (
                  item.value === current
                ) {
                  onClose();
                } else {
                  onSelect(
                    item.value
                  );
                }
              }}
            >
              <span className="more-sheet__item-icon">
                {item.icon || '📌'}
              </span>

              <span className="more-sheet__item-text">
                <span className="more-sheet__item-title">
                  {item.label}
                </span>
              </span>

              {item.value ===
              current ? (
                <span className="badge b-grn">
                  انتخاب فعلی
                </span>
              ) : (
                <span className="more-sheet__arrow">
                  ←
                </span>
              )}
            </button>
          ))
        )}
      </div>
    </div>
  );
}


function WeekChart({
  rows = [],
}) {
  const safeRows =
    Array.isArray(rows)
      ? rows
      : [];

  const values =
    safeRows.map(
      (item) =>
        number(item?.count)
    );

  const max = Math.max(
    ...values,
    1
  );

  if (!safeRows.length) {
    return null;
  }

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-end',
        height: 70,
        gap: 6,
      }}
    >
      {safeRows.map(
        (item, index) => {
          const value =
            values[index];

          return (
            <div
              key={`${
                item?.date
              }-${index}`}
              style={{
                flex: 1,

                display:
                  'flex',

                height:
                  '100%',

                flexDirection:
                  'column',

                alignItems:
                  'center',

                justifyContent:
                  'flex-end',

                gap: 'var(--sp-1)',
              }}
            >
              <div
                style={{
                  width:
                    '100%',

                  minHeight:
                    4,

                  height:
                    `${Math.max(
                      4,

                      (
                        value /
                        max
                      ) * 44
                    )}px`,

                  borderRadius:
                    '6px 6px 2px 2px',

                  background:
                    value
                      ? 'var(--grad-brand)'
                      : 'var(--ovr)',
                }}
              />

              <span
                style={{
                  color:
                    'var(--txm)',

                  fontSize: 'var(--fs-cap)',
                }}
              >
                {String(
                  item?.date ||
                  ''
                ).slice(-2)}
              </span>
            </div>
          );
        }
      )}
    </div>
  );
}


// 🏷 موج Identity v1 — کارت لقب و
// حریم نمایش نام واقعی (§۳/§Privacy)
function NicknameCard({
  user,
  onSaved,
}) {
  const toast = useUIStore(
    (state) => state.toast
  );

  const [editing, setEditing] =
    useState(false);

  const [value, setValue] =
    useState('');


  const saveMutation =
    useMutation({
      mutationFn: (raw) =>
        api.patch(
          '/api/profile/nickname',

          { nickname: raw }
        ),

      onSuccess: async () => {
        hapticNotif('success');

        toast(
          'لقب به‌روزرسانی شد ✅',
          'success'
        );

        setEditing(false);

        await onSaved();
      },

      onError: (error) => {
        hapticNotif('error');

        toast(
          errorText(
            error,
            'ثبت لقب انجام نشد'
          ),
          'error'
        );
      },
    });


  const privacyMutation =
    useMutation({
      mutationFn: (on) =>
        api.patch(
          '/api/profile/privacy',

          {
            show_real_name: on,
          }
        ),

      onSuccess: async () => {
        hapticNotif('success');

        toast(
          'تنظیم نمایش ذخیره شد ✅',
          'success'
        );

        await onSaved();
      },

      onError: (error) => {
        hapticNotif('error');

        toast(
          errorText(
            error,
            'ذخیره انجام نشد'
          ),
          'error'
        );
      },
    });


  const nick = user.nickname || '';

  const canChange =
    user.can_change_nickname !==
    false;

  const coolDays =
    number(
      user.nickname_cooldown_days
    ) || 30;

  const showReal =
    user.show_real_name !== false;

  const nextText = faDate(
    user.next_change_at, ''
  );

  const pending =
    saveMutation.isPending;


  const startEdit = () => {
    haptic();

    setValue(nick);
    setEditing(true);
  };


  const submit = (event) => {
    event.preventDefault();

    if (!pending) {
      saveMutation.mutate(
        value.trim()
      );
    }
  };


  return (
    <section className="card">
      <div className="sec-title">
        🏷 لقب و نام نمایشی
      </div>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 9,
        }}
      >
        <div
          style={{
            flex: 1,
            minWidth: 0,
          }}
        >
          <div
            style={{
              overflow: 'hidden',

              fontSize: 'var(--fs-lg)',

              fontWeight: 900,

              textOverflow:
                'ellipsis',

              whiteSpace:
                'nowrap',
            }}
          >
            {nick || '—'}
          </div>

          <div
            style={{
              color:
                'var(--txm)',

              fontSize:
                'var(--fs-cap)',

              marginTop: 3,
            }}
          >
            {nick
              ? 'این نام در رتبه‌بندی، فید و نشان‌ها دیده می‌شود'
              : 'لقبی ندارید؛ نام واقعی شما نمایش داده می‌شود'}
          </div>
        </div>

        {!editing && (
          <button
            type="button"
            className="btn btn-dark"
            disabled={
              !canChange || pending
            }
            onClick={startEdit}
          >
            {nick
              ? 'ویرایش'
              : 'انتخاب لقب'}
          </button>
        )}
      </div>

      {editing && (
        <form
          onSubmit={submit}
          style={{
            display: 'flex',
            gap: 'var(--sp-2)',
            marginTop: 12,
          }}
        >
          <input
            className="inp"
            value={value}
            maxLength={24}
            placeholder={
              'لقب (۳ تا ۲۴ نویسه)'
            }
            autoFocus
            onChange={(event) =>
              setValue(
                event.target.value
              )
            }
          />

          <button
            className="btn btn-p"
            type="submit"
            disabled={pending}
          >
            {pending ? (
              <Spinner size={14} />
            ) : (
              'ذخیره'
            )}
          </button>

          <button
            className="btn btn-dark"
            type="button"
            onClick={() =>
              setEditing(false)
            }
          >
            لغو
          </button>
        </form>
      )}

      {nick && !editing && (
        <button
          type="button"
          disabled={pending}
          onClick={() =>
            saveMutation.mutate('')
          }
          style={{
            padding: 0,
            marginTop: 8,
            color: 'var(--txm)',
            background: 'none',
            border: 0,
            fontSize: 'var(--fs-cap)',
            cursor: 'pointer',
          }}
        >
          حذف لقب ✕
        </button>
      )}

      <div
        style={{
          color: 'var(--txm)',
          fontSize: 'var(--fs-cap)',
          marginTop: 9,
        }}
      >
        {canChange
          ? `تغییر لقب هر ${coolDays} روز یک‌بار ممکن است؛ نام واقعی در ثبت نمره و گزارش‌ها همیشه ثابت می‌ماند.`
          : `تغییر بعدی لقب از ${nextText} ممکن می‌شود.`}
      </div>

      <div className="divider" />

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--sp-3)',
        }}
      >
        <div style={{ flex: 1 }}>
          <b style={{ fontSize: 'var(--fs-sm)' }}>
            نمایش اسم واقعی
          </b>

          <div
            style={{
              color:
                'var(--txm)',

              fontSize:
                'var(--fs-cap)',

              marginTop: 2,
            }}
          >
            {showReal
              ? 'در فضای عمومی نام واقعی شما هم دیده می‌شود'
              : 'در فضای عمومی فقط لقب شما دیده می‌شود'}
          </div>
        </div>

        <Switch
          on={showReal}
          loading={
            privacyMutation
              .isPending
          }
          onToggle={() =>
            privacyMutation.mutate(
              !showReal
            )
          }
        />
      </div>
    </section>
  );
}


// 🌱 W13 — کارت دعوت دوستان (فقط وقتی بک‌اند enabled بدهد رندر می‌شود)
function ReferralCard({ data }) {
  const toast = useUIStore((s) => s.toast);
  const stats = data?.stats || {};
  const byStatus = stats.by_status || {};
  const earned = stats.earned || {};
  const rewards = data?.rewards || {};
  const rewardLine = [
    rewards.sub_days ? `🎁 ${rewards.sub_days.amount} روز اشتراک` : '',
    rewards.wallet ? `👛 ${Number(rewards.wallet.amount).toLocaleString('fa-IR')} تومان` : '',
    rewards.discount ? `🎟 تخفیف ${rewards.discount.amount}٪` : '',
    rewards.xp ? `⚡ ${rewards.xp.amount} XP` : '',
  ].filter(Boolean).join(' · ');

  const copyLink = async () => {
    haptic('light');
    try {
      await navigator.clipboard.writeText(data.link || '');
      toast('لینک دعوت کپی شد ✅');
    } catch {
      toast('کپی نشد — لینک را دستی کپی کن', 'err');
    }
  };

  return (
    <section className="card" style={{ marginTop: 12 }}>
      <div className="sec-title">
        🎁 دعوت دوستان
      </div>
      <div
        className="row"
        style={{ gap: 8, marginTop: 6 }}
      >
        <div
          dir="ltr"
          style={{
            flex: 1, overflow: 'hidden', textOverflow: 'ellipsis',
            whiteSpace: 'nowrap', fontSize: 'var(--fs-cap)',
            color: 'var(--txm)',
          }}
        >
          {data.link || '—'}
        </div>
        <button
          type="button"
          className="btn sm"
          onClick={copyLink}
        >
          📋 کپی
        </button>
      </div>
      <div
        className="row"
        style={{ gap: 8, marginTop: 10 }}
      >
        <span className="badge b-acc">👥 {stats.total || 0} دعوت</span>
        <span className="badge b-grn">✅ {byStatus.counted || 0}</span>
        {(stats.awaiting_buy || 0) > 0 && (
          <span className="badge b-yel">⏳ {stats.awaiting_buy} در انتظار خرید</span>
        )}
      </div>
      {!!rewardLine && (
        <div
          className="muted"
          style={{ marginTop: 8, fontSize: 'var(--fs-cap)' }}
        >
          با هر دعوت موفق: {rewardLine}
        </div>
      )}
      {(earned.sub_days || earned.wallet || earned.xp) ? (
        <div
          className="muted"
          style={{ marginTop: 4, fontSize: 'var(--fs-cap)' }}
        >
          مجموع جوایزت: {earned.sub_days || 0} روز،{' '}
          {Number(earned.wallet || 0).toLocaleString('fa-IR')} تومان،{' '}
          {earned.xp || 0} XP
        </div>
      ) : null}
    </section>
  );
}


export default function Profile() {
  const [
    editField,
    setEditField,
  ] = useState(null);

  const [
    fieldValue,
    setFieldValue,
  ] = useState('');

  const [
    picker,
    setPicker,
  ] = useState(null);

  const toast = useUIStore(
    (state) => state.toast
  );

  const refreshAuth =
    useAuthStore(
      (state) =>
        state.refresh
    );

  const queryClient =
    useQueryClient();


  const {
    data,
    isLoading,
    isError,
    refetch,
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


  // 🌱 W13 — دعوت‌های من (با کلید خاموش، enabled=false و کارت مخفی)
  const {
    data: referral,
  } = useQuery({
    queryKey: [
      'referral-mine',
    ],

    queryFn: () =>
      api
        .get('/api/referral/mine')
        .then(
          (response) =>
            response.data
        ),

    staleTime:
      5 * 60 * 1000,
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


  const {
    data: badges = [],
  } = useQuery({
    queryKey: [
      'badges',
    ],

    queryFn: () =>
      api
        .get(
          '/api/profile/badges'
        )
        .then(
          (response) =>
            response.data
              ?.badges || []
        ),

    staleTime:
      10 * 60 * 1000,
  });


  const {
    data: intakes = [],

    isLoading:
      intakesLoading,
  } = useQuery({
    queryKey: [
      'intakes',
    ],

    queryFn: () =>
      api
        .get(
          '/api/profile/intakes'
        )
        .then(
          (response) =>
            response.data
              ?.intakes || []
        ),

    enabled:
      picker === 'intake',

    staleTime:
      30 * 60 * 1000,
  });


  const refreshAll = async () => {
    await Promise.all([
      queryClient
        .invalidateQueries({
          queryKey:
            ['profile'],
        }),

      queryClient
        .invalidateQueries({
          queryKey:
            ['dashboard'],
        }),

      queryClient
        .invalidateQueries({
          queryKey:
            ['rank'],
        }),

      queryClient
        .invalidateQueries({
          queryKey:
            ['badges'],
        }),

      queryClient
        .invalidateQueries({
          queryKey:
            ['schedule'],
        }),

      queryClient
        .invalidateQueries({
          queryKey:
            ['referral-mine'],
        }),

      refreshAuth(),
    ]);
  };


  const updateMutation =
    useMutation({
      mutationFn: ({
        field,
        value,
      }) => {
        const endpoint = {
          name:
            'name',

          student_id:
            'student-id',

          group:
            'group',

          intake:
            'intake',
        }[field];

        return api.patch(
          `/api/profile/${endpoint}`,

          {
            [field]:
              value,
          }
        );
      },

      onSuccess:
        async () => {
          hapticNotif(
            'success'
          );

          toast(
            'اطلاعات با موفقیت ذخیره شد ✅',
            'success'
          );

          setEditField(null);
          setPicker(null);

          await refreshAll();
        },

      onError: (error) => {
        hapticNotif('error');

        toast(
          errorText(
            error,
            'ذخیره اطلاعات انجام نشد'
          ),
          'error'
        );
      },
    });


  const user =
    data?.user || {};

  const stats =
    data?.stats || {};

  const badgeList =
    Array.isArray(badges)
      ? badges
      : [];

  const weak =
    Array.isArray(
      stats.weak_topics
    )
      ? stats.weak_topics
      : [];

  const readiness =
    percent(
      stats.percentage
    );


  const startEdit = (
    field,
    value
  ) => {
    haptic();

    setEditField(field);

    setFieldValue(
      value || ''
    );
  };


  const validField =
    editField === 'name'
      ? fieldValue
          .trim()
          .length >= 3

      : editField ===
          'student_id'

        ? /^\d{3,20}$/.test(
            fieldValue.trim()
          )

        : false;


  const submitEdit = (
    event
  ) => {
    event.preventDefault();

    if (validField) {
      updateMutation.mutate({
        field:
          editField,

        value:
          fieldValue.trim(),
      });
    }
  };


  return (
    <>
      <Header
        title="پروفایل من"
        subtitle={
          'اطلاعات تحصیلی و پیشرفت'
        }
      />


      {picker ===
        'group' && (
        <Picker
          title={
            'انتخاب گروه درسی'
          }
          current={
            user.group
          }
          pending={
            updateMutation
              .isPending
          }
          onClose={() => {
            if (
              !updateMutation
                .isPending
            ) {
              setPicker(null);
            }
          }}
          onSelect={(value) =>
            updateMutation.mutate({
              field:
                'group',

              value,
            })
          }
          options={[
            {
              value: '1',
              label: 'گروه ۱',
              icon: '1️⃣',
            },

            {
              value: '2',
              label: 'گروه ۲',
              icon: '2️⃣',
            },
          ]}
        />
      )}


      {picker ===
        'intake' && (
        <Picker
          title={
            'انتخاب ورودی'
          }
          current={
            user.intake
          }
          loading={
            intakesLoading
          }
          pending={
            updateMutation
              .isPending
          }
          onClose={() => {
            if (
              !updateMutation
                .isPending
            ) {
              setPicker(null);
            }
          }}
          onSelect={(value) =>
            updateMutation.mutate({
              field:
                'intake',

              value,
            })
          }
          options={
            (
              Array.isArray(
                intakes
              )
                ? intakes
                : []
            ).map(
              (item) => ({
                value:
                  item.code,

                label:
                  item.label ||
                  item.code,

                icon:
                  '📅',
              })
            )
          }
        />
      )}


      <main className="page fade-up">
        {isLoading ? (
          <ProfileSkeleton />
        ) : isError ? (
          <PageError
            text={
              'دریافت پروفایل انجام نشد.'
            }
            onRetry={() => refetch()}
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
                'card card-glow hero-card'
              }
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
                    width: 60,
                    height: 60,
                    fontSize: 24,
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

                  <button
                    type="button"
                    onClick={() =>
                      startEdit(
                        'student_id',
                        user.student_id
                      )
                    }
                    style={{
                      display: 'block',

                      padding:
                        0,

                      marginTop:
                        3,

                      color:
                        'var(--txm)',

                      background:
                        'none',

                      border:
                        0,

                      fontSize: 'var(--fs-cap)',

                      cursor:
                        'pointer',
                    }}
                  >
                    شماره دانشجویی:{' '}

                    {user.student_id ||
                      'ثبت نشده'}{' '}

                    ✎
                  </button>

                  <div
                    style={{
                      display: 'flex',

                      flexWrap:
                        'wrap',

                      gap:
                        5,

                      marginTop: 'var(--sp-2)',
                    }}
                  >
                    <button
                      type="button"
                      className={
                        'badge b-acc'
                      }
                      onClick={() =>
                        setPicker(
                          'intake'
                        )
                      }
                    >
                      ورودی{' '}

                      {user.intake ||
                        '—'}{' '}

                      ✎
                    </button>

                    <button
                      type="button"
                      className={
                        'badge b-acc'
                      }
                      onClick={() =>
                        setPicker(
                          'group'
                        )
                      }
                    >
                      گروه{' '}

                      {user.group ||
                        '—'}{' '}

                      ✎
                    </button>
                  </div>
                </div>

                <button
                  type="button"
                  className="icon-btn"
                  aria-label="ویرایش نام"
                  onClick={() =>
                    startEdit(
                      'name',
                      user.name
                    )
                  }
                >
                  ✎
                </button>
              </div>

              {editField && (
                <form
                  onSubmit={
                    submitEdit
                  }
                  style={{
                    display: 'flex',
                    gap: 'var(--sp-2)',
                    marginTop: 'var(--sp-4)',
                  }}
                >
                  <input
                    className="inp"
                    value={
                      fieldValue
                    }
                    maxLength={
                      editField ===
                      'name'
                        ? 50
                        : 20
                    }
                    inputMode={
                      editField ===
                      'student_id'
                        ? 'numeric'
                        : 'text'
                    }
                    onChange={(
                      event
                    ) =>
                      setFieldValue(
                        editField ===
                        'student_id'
                          ? event
                              .target
                              .value
                              .replace(
                                /\D/g,
                                ''
                              )
                          : event
                              .target
                              .value
                      )
                    }
                    placeholder={
                      editField ===
                      'name'
                        ? 'نام و نام خانوادگی'
                        : 'شماره دانشجویی'
                    }
                    autoFocus
                  />

                  <button
                    className={
                      'btn btn-p'
                    }
                    type="submit"
                    disabled={
                      !validField ||
                      updateMutation
                        .isPending
                    }
                  >
                    {updateMutation
                      .isPending ? (
                      <Spinner
                        size={14}
                      />
                    ) : (
                      'ذخیره'
                    )}
                  </button>

                  <button
                    className={
                      'btn btn-dark'
                    }
                    type="button"
                    onClick={() =>
                      setEditField(
                        null
                      )
                    }
                  >
                    لغو
                  </button>
                </form>
              )}
            </section>


            {/* 🏷 موج Identity v1 —
                لقب + حریم نام واقعی */}
            <NicknameCard
              user={user}
              onSaved={refreshAll}
            />


            {/* 👑 موج P0 — کارت قهرمان
                Prestige (رنک/هدف/رقیب/سپر) */}
            <PrestigeHero />


            {rank?.rank && (
              <section
                className="card"
                style={{
                  display: 'flex',

                  alignItems:
                    'center',

                  gap: 11,

                  borderColor:
                    'var(--bd-warn)',

                  background:
                    'linear-gradient(145deg,var(--soft-warn),var(--surf-card))',
                }}
              >
                <span
                  style={{
                    fontSize: 29,
                  }}
                >
                  🏅
                </span>

                <div>
                  <b
                    style={{
                      color:
                        'var(--warn)',

                      fontSize: 'var(--fs-lg)',
                    }}
                  >
                    رتبه{' '}

                    {number(
                      rank.rank
                    )}{' '}

                    از{' '}

                    {number(
                      rank.total_users
                    )}
                  </b>

                  <div
                    style={{
                      color:
                        'var(--txm)',

                      fontSize: 'var(--fs-cap)',

                      marginTop:
                        2,
                    }}
                  >
                    بهتر از{' '}

                    {percent(
                      rank.percentile
                    )}
                    ٪ دانشجویان
                  </div>
                </div>
              </section>
            )}


            <WalletMiniCard />


            {referral?.enabled && (
              <ReferralCard data={referral} />
            )}

            <section className="card">
              <div className="sec-title">
                📊 عملکرد تحصیلی
              </div>

              <div
                className="grid2"
                style={{
                  marginBottom: 'var(--sp-4)',
                }}
              >
                {[
                  [
                    '🧪',

                    number(
                      stats
                        .total_answers
                    ),

                    'سؤال',

                    'var(--t-acc)',
                  ],

                  [
                    '✅',

                    number(
                      stats
                        .correct_answers
                    ),

                    'صحیح',

                    'var(--t-ok)',
                  ],

                  [
                    '📥',

                    number(
                      stats.downloads
                    ),

                    'دانلود',

                    'var(--t-info)',
                  ],

                  [
                    '📈',

                    `${readiness}٪`,

                    'موفقیت',

                    'var(--t-warn)',
                  ],
                ].map(
                  ([
                    icon,
                    value,
                    label,
                    color,
                  ]) => (
                    <StatTile
                      key={label}
                      variant="grid"
                      icon={icon}
                      value={value}
                      label={label}
                      color={color}
                    />
                  )
                )}
              </div>

              {stats.level && (
                <div
                  style={{
                    display: 'flex',

                    alignItems:
                      'center',

                    gap:
                      8,

                    padding:
                      '9px 11px',

                    marginBottom:
                      12,

                    color:
                      stats
                        .level
                        .color ||
                      'var(--acc)',

                    background:
                      `${
                        stats
                          .level
                          .color ||
                        'var(--acc)'
                      }15`,

                    borderRadius: 'var(--r-md)',
                  }}
                >
                  <span
                    style={{
                      fontSize: 'var(--fs-xl)',
                    }}
                  >
                    {stats
                      .level
                      .icon ||
                      '📈'}
                  </span>

                  <b>
                    {stats
                      .level
                      .label ||
                      'سطح کاربر'}
                  </b>

                  <span
                    style={{
                      marginRight:
                        'auto',

                      color:
                        'var(--txm)',

                      fontSize: 'var(--fs-cap)',
                    }}
                  >
                    سطح فعلی
                  </span>
                </div>
              )}

              <WeekChart
                rows={
                  stats.weekly_chart
                }
              />

              {weak.length >
                0 && (
                <>
                  <div className="divider" />

                  <div
                    style={{
                      color:
                        'var(--txm)',

                      fontSize: 'var(--fs-cap)',

                      marginBottom: 'var(--sp-2)',
                    }}
                  >
                    ⚡ مباحث نیازمند تمرین
                  </div>

                  <div
                    style={{
                      display:
                        'flex',

                      flexWrap:
                        'wrap',

                      gap:
                        5,
                    }}
                  >
                    {weak.map(
                      (item) => (
                        <span
                          key={item}
                          className={
                            'badge b-red'
                          }
                        >
                          {item}
                        </span>
                      )
                    )}
                  </div>
                </>
              )}
            </section>


            {badgeList.length >
              0 && (
              <section className="card">
                <div className="sec-title">
                  🏆 نشان‌های پیشرفت
                </div>

                <div
                  style={{
                    display: 'grid',

                    gridTemplateColumns:
                      'repeat(4,minmax(0,1fr))',

                    gap:
                      9,
                  }}
                >
                  {badgeList.map(
                    (badge) => (
                      <div
                        key={badge.id}
                        style={{
                          textAlign:
                            'center',

                          opacity:
                            badge.earned
                              ? 1
                              : .3,
                        }}
                      >
                        <div
                          style={{
                            display:
                              'grid',

                            width:
                              46,

                            height:
                              46,

                            placeItems:
                              'center',

                            margin:
                              '0 auto',

                            background:
                              badge.earned
                                ? 'var(--acc-soft)'
                                : 'var(--elev)',

                            border:
                              `1px solid ${
                                badge.earned
                                  ? 'var(--bdg)'
                                  : 'var(--bd)'
                              }`,

                            borderRadius:
                              '50%',

                            fontSize:
                              21,
                          }}
                        >
                          {badge.icon}
                        </div>

                        <div
                          style={{
                            color:
                              'var(--tx2)',

                            fontSize: 'var(--fs-cap)',

                            marginTop:
                              5,
                          }}
                        >
                          {badge.title}
                        </div>
                      </div>
                    )
                  )}
                </div>
              </section>
            )}
          </div>
        )}
      </main>
    </>
  );
}


// ════════════════════════════════════════════════════════════════
// 💰 W6 — کارت کوچک کیف پول در پروفایل (§۱۴): موجودی از API canonical
// + میان‌بر به صفحه‌ی اشتراک برای خرید/تاریخچه. READ-ONLY در فرانت.
// ════════════════════════════════════════════════════════════════
export function WalletMiniCard() {
  const nav = useNavigate();
  const walletQuery = useQuery({
    queryKey: ['wallet'],
    queryFn: () => api.get('/api/subscription/wallet').then((r) => r.data),
  });
  const w = walletQuery.data;
  return (
    <section className="card">
      <div className="sec-title">👛 کیف پول</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <b style={{ fontSize: 18 }}>
          {walletQuery.isLoading ? '…' : `${number(w?.balance ?? 0)} تومان`}
        </b>
        <span style={{ flex: 1 }} />
        <button type="button" className="btn btn-xs" onClick={() => nav('/me/subscription?wallet=topup')}>
          💳 شارژ کیف پول
        </button>
        <button type="button" className="btn btn-xs" onClick={() => nav('/me/subscription')}>
          💰 خرید اشتراک
        </button>
        <button type="button" className="btn btn-xs" onClick={() => nav('/me/subscription')}>
          🧾 تاریخچه
        </button>
      </div>
      {w?.last_tx && (
        <div className="muted" style={{ marginTop: 6 }}>
          آخرین تراکنش: {w.last_tx.direction === 'credit' ? '➕' : '➖'}{' '}
          {number(w.last_tx.amount)} — {w.last_tx.label}
        </div>
      )}
    </section>
  );
}
