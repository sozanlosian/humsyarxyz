import PageError from '../../components/shared/PageError';
import EmptyState from '../../components/shared/EmptyState';

import { faNum, number, errorText } from '../../lib/format';

import { confirmAction } from '../../lib/confirm';
import {
  useEffect,
  useMemo,
  useState,
} from 'react';

import {
  useNavigate,
  useParams,
} from 'react-router-dom';

import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import api from '../../lib/api';
import Header from '../../components/layout/Header';

import {
  Spinner,
} from '../../components/shared/Loading';

import {
  UsersActionsSkeleton,
  UsersListSkeleton,
  SkRowList,
  SkHero,
} from '../../components/shared/skeletons';

import SearchField from '../../components/shared/SearchField';

import {
  haptic,
  hapticNotif,
} from '../../lib/telegram';

import {
  useUIStore,
} from '../../stores/uiStore';











/* مدیریت کاربران */

export function AdminUsers() {
  const navigate =
    useNavigate();

  const [
    search,
    setSearch,
  ] = useState('');

  const [
    group,
    setGroup,
  ] = useState('');

  const [
    intake,
    setIntake,
  ] = useState('');

  const [
    status,
    setStatus,
  ] = useState('all');

  /* 📄 رندر افزایشی (موج ۴.۶۰) — لیست تا ۵۰۰
     کاربر می‌تواند باشد؛ رندر یکجای ۵۰۰ کارت
     DOMِ سنگین + اسکرول لکنت‌دار می‌سازد. ۴۰
     تای اول + «نمایش بیشتر» — با هر تغییر
     فیلتر/جست‌وجو ریست می‌شود. */
  const [
    visible,
    setVisible,
  ] = useState(40);

  useEffect(() => {
    setVisible(40);
  }, [search, group, intake, status]);


  const {
    data,
    isLoading,
    isError,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: [
      'admin-users',
      search,
      group,
      intake,
    ],

    queryFn: () =>
      api
        .get(
          '/api/admin/users',

          {
            params: {
              search:
                search.trim() ||
                undefined,

              group:
                group ||
                undefined,

              intake:
                intake ||
                undefined,
            },
          }
        )
        .then(
          (response) =>
            response.data
              ?.users || []
        ),

    staleTime:
      30_000,
  });


  const {
    data: intakes = [],
  } = useQuery({
    queryKey: [
      'admin-intakes',
    ],

    queryFn: () =>
      api
        .get(
          '/api/admin/intakes'
        )
        .then(
          (response) =>
            response.data
              ?.intakes || []
        ),

    staleTime:
      5 * 60 * 1000,
  });


  const all =
    Array.isArray(data)
      ? data
      : [];


  const users =
    all.filter((item) => {
      if (
        status === 'pending'
      ) {
        return !item.approved;
      }

      if (
        status === 'active'
      ) {
        return (
          item.approved &&
          !item.suspended
        );
      }

      if (
        status === 'suspended'
      ) {
        return item.suspended;
      }

      return true;
    });


  const pending =
    all.filter(
      (item) =>
        !item.approved
    ).length;


  return (
    <>
      <Header
        title="مدیریت کاربران"
        subtitle={`${all.length} کاربر`}
        right={
          <button
            type="button"
            onClick={() =>
              refetch()
            }
            aria-label="به‌روزرسانی"
            style={{
              width: 35,
              height: 35,

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
              16,

            marginBottom:
              13,

            background:
              'linear-gradient(145deg,var(--soft-acc),var(--surf-card))',
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
                  'var(--grad-brand)',

                fontSize:
                  23,
              }}
            >
              👥
            </span>

            <div
              style={{
                flex:
                  1,
              }}
            >
              <b
                style={{
                  fontSize: 'var(--fs-lg)',
                }}
              >
                کاربران هامزیار
              </b>

              <div
                style={{
                  display:
                    'flex',

                  gap:
                    5,

                  marginTop:
                    6,
                }}
              >
                <span className="badge b-grn">
                  {all.filter(
                    (item) =>
                      item.approved
                  ).length}{' '}

                  تأییدشده
                </span>

                {pending > 0 && (
                  <span className="badge b-yel">
                    {pending} در انتظار
                  </span>
                )}
              </div>
            </div>
          </div>
        </section>


        <section
          className="card"
          style={{
            display:
              'grid',

            gap:
              9,

            marginBottom:
              13,
          }}
        >
          <SearchField
            value={search}
            onChange={(event) =>
              setSearch(
                event.target.value
              )
            }
            placeholder={
              'نام، یوزرنیم، شماره یا آیدی عددی...'
            }
            ariaLabel="جست‌وجوی کاربران"
            loading={isFetching}
          />

          <div className="grid2">
            <select
              className="inp"
              value={group}
              onChange={(event) =>
                setGroup(
                  event.target.value
                )
              }
            >
              <option value="">
                همه گروه‌ها
              </option>

              <option value="1">
                گروه ۱
              </option>

              <option value="2">
                گروه ۲
              </option>
            </select>

            <select
              className="inp"
              value={intake}
              onChange={(event) =>
                setIntake(
                  event.target.value
                )
              }
            >
              <option value="">
                همه ورودی‌ها
              </option>

              {(
                Array.isArray(
                  intakes
                )
                  ? intakes
                  : []
              ).map((item) => (
                <option
                  key={item.code}
                  value={item.code}
                >
                  {item.label ||
                    item.code}
                </option>
              ))}
            </select>
          </div>
        </section>


        <div className="tab-bar">
          {[
            [
              'all',
              'همه',
            ],

            [
              'active',
              'فعال',
            ],

            [
              'pending',
              'در انتظار',
            ],

            [
              'suspended',
              'تعلیق',
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
                  setStatus(key)
                }
                style={{
                  color:
                    status === key
                      ? 'var(--t-white)'
                      : 'var(--tx2)',

                  background:
                    status === key
                      ? 'var(--grad-brand)'
                      : 'transparent',
                }}
              >
                {label}
              </button>
            )
          )}
        </div>


        {isLoading ? (
          <UsersActionsSkeleton />
        ) : isError ? (
          <PageError
            text="دریافت کاربران انجام نشد."
            onRetry={() => refetch()}
          />
        ) : users.length === 0 ? (
          <EmptyState>
            کاربری با این فیلتر پیدا نشد.
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
            {users.slice(
              0,
              visible
            ).map(
              (
                user,
                index
              ) => (
                <button
                  type="button"
                  key={user.id}
                  className={
                    'card card-tap pop-in'
                  }
                  onClick={() =>
                    navigate(
                      `/admin/users/${user.id}`
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

                    padding:
                      12,

                    textAlign:
                      'right',

                    animationDelay:
                      `${
                        Math.min(
                          index,
                          8
                        ) * 25
                      }ms`,
                  }}
                >
                  <span
                    className="avatar"
                    style={{
                      width:
                        43,

                      height:
                        43,
                    }}
                  >
                    {user.name?.[0] ||
                      '؟'}
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
                          'block',

                        overflow:
                          'hidden',

                        fontSize: 'var(--fs-sm)',

                        textOverflow:
                          'ellipsis',

                        whiteSpace:
                          'nowrap',
                      }}
                    >
                      {user.name ||
                        `#${user.id}`}

                      {/* 👑 P3 — مینی-چیپ پرستیژ کنار نام */}
                      {user.prestige?.icon && (
                        <span
                          title={
                            user.prestige
                              .title || ''
                          }
                          style={{
                            color:
                              user.prestige
                                .color ||
                              'var(--txm)',
                            fontSize: 'var(--fs-cap)',
                            fontWeight: 700,
                            marginRight: 5,
                          }}
                        >
                          {
                            user.prestige
                              .icon
                          }{' '}
                          {
                            user.prestige
                              .roman
                          }
                        </span>
                      )}
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
                      {user.student_id ||
                        'بدون شماره'}

                      {' • ورودی '}

                      {user.intake ||
                        '—'}

                      {' • گروه '}

                      {user.group ||
                        '—'}
                    </span>
                  </span>

                  <span
                    className={`badge ${
                      user.suspended
                        ? 'b-red'

                        : !user.approved
                          ? 'b-yel'

                          : user.role !==
                              'student'
                            ? 'b-pur'

                            : 'b-grn'
                    }`}
                  >
                    {user.suspended
                      ? 'تعلیق'

                      : !user.approved
                        ? 'در انتظار'

                        : user.role ===
                            'content_admin'
                          ? 'ادمین ارشد محتوا'

                          : user.role ===
                              'support'
                            ? 'پشتیبان'

                            : 'فعال'}
                  </span>

                  <span>←</span>
                </button>
              )
            )}
          </section>
        )}

        {!isLoading &&
          !isError &&
          users.length >
            visible && (
            <button
              type="button"
              className={
                'btn btn-dark btn-full'
              }
              style={{
                marginTop:
                  9,
              }}
              onClick={() =>
                setVisible(
                  (current) =>
                    current + 40
                )
              }
            >
              نمایش بیشتر (
              {users.length -
                visible}{' '}
              مورد دیگر)
            </button>
          )}
      </main>
    </>
  );
}


/* جزئیات کاربر */

/* عدد فارسی محلی — این صفحه faNum خارجی ندارد */



/* 🛡 کارت نقش‌های RBAC — موج RBAC-W2 (قرارداد §UserManagement)
   نقش‌ها کاملاً داینامیک از /api/admin/rbac می‌آیند (بدون لیست
   استاتیک): تخصیص/حذف چندنقشی، جست‌وجو، پیش‌نمایش‌ی مجوزهای
   موروثی. سازگاری: mirror سرور users.role را هم‌زمان به‌روز نگه
   می‌دارد و این صفحه هم آن‌را از کوئری admin-user بازخوانی می‌کند. */
function UserRbacCard({ uid }) {
  const toast = useUIStore(
    (state) => state.toast,
  );
  const queryClient = useQueryClient();

  const [q, setQ] = useState('');
  const [showPerms, setShowPerms] =
    useState(false);

  const rolesQ = useQuery({
    queryKey: ['rbac-roles'],
    queryFn: () =>
      api
        .get('/api/admin/rbac/roles')
        .then((response) => response.data),
    staleTime: 30_000,
  });

  const permsQ = useQuery({
    queryKey: ['rbac-perms'],
    queryFn: () =>
      api
        .get('/api/admin/rbac/permissions')
        .then((response) => response.data),
    staleTime: 300_000,
  });

  const userQ = useQuery({
    queryKey: ['rbac-user', uid],
    queryFn: () =>
      api
        .get(`/api/admin/rbac/users/${uid}`)
        .then((response) => response.data),
  });

  const assignM = useMutation({
    mutationFn: (payload) =>
      api.post(
        `/api/admin/rbac/users/${uid}/roles`,
        payload,
      ),

    onSuccess: () => {
      hapticNotif('success');
      queryClient.invalidateQueries({
        queryKey: ['rbac-user', uid],
      });
      /* mirror سرور users.role را هم عوض می‌کند —
         بج نقش قدیمی این صفحه باید بازخوانی شود */
      queryClient.invalidateQueries({
        queryKey: ['admin-user', uid],
        exact: true,
      });
      queryClient.invalidateQueries({
        queryKey: ['admin-users'],
      });
      queryClient.invalidateQueries({
        queryKey: ['rbac-roles'],
      });
    },

    onError: (error) => {
      hapticNotif('error');
      const detail =
        error?.response?.data?.detail;
      toast(
        typeof detail === 'string' && detail
          ? detail
          : 'تغییر نقش انجام نشد',
        'error',
      );
    },
  });

  const assigned = userQ.data?.roles || [];
  const assignedKeys = new Set(
    userQ.data?.keys || [],
  );
  const userPerms = userQ.data?.perms || [];

  const permLabels = useMemo(() => {
    const catalog = permsQ.data?.permissions || [];
    return Object.fromEntries(
      catalog.map((perm) => [perm.key, perm.label]),
    );
  }, [permsQ.data]);

  const needle = q.trim().toLowerCase();
  const available = (
    rolesQ.data?.roles || []
  ).filter((role) =>
    !assignedKeys.has(role.key) &&
    (!needle ||
      role.label.toLowerCase().includes(needle) ||
      role.key.toLowerCase().includes(needle)),
  );

  return (
    <section
      className="card fade-up"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        padding: '11px 13px',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--sp-2)',
        }}
      >
        <b style={{ fontSize: 'var(--fs-meta)' }}>
          🛡 نقش‌های RBAC
        </b>
        <span
          className="badge b-gray"
          style={{ fontSize: 'var(--fs-cap)' }}
        >
          {faNum(assigned.length)} نقش ·
          {' '}{faNum(userPerms.length)} مجوز
        </span>
        <button
          type="button"
          className="tab-btn"
          style={{
            marginInlineStart: 'auto',
            fontSize: 'var(--fs-cap)',
            minHeight: 24,
            padding: '2px 8px',
          }}
          onClick={() =>
            setShowPerms((value) => !value)
          }
          aria-expanded={showPerms}
        >
          {showPerms
            ? 'بستن مجوزها ▲'
            : 'پیش‌نمایش مجوزها ▼'}
        </button>
      </div>

      {/* بج‌های نقش تخصیص‌یافته — رنگ از سرور */}
      <div
        style={{
          display: 'flex',
          gap: 6,
          flexWrap: 'wrap',
        }}
      >
        {userQ.isPending && (
          <span
            className="skeleton"
            style={{ height: 22, width: 90, borderRadius: 'var(--r-sm)' }}
          />
        )}
        {!userQ.isPending &&
          assigned.length === 0 && (
            <span
              style={{
                color: 'var(--txm)',
                fontSize: 'var(--fs-cap)',
              }}
            >
              هنوز نقشی ندارد (دانشجوِ عادی)
            </span>
          )}
        {assigned.map((role) => (
          <span
            key={role.key}
            className="badge"
            title={role.desc || role.label}
            style={{
              fontSize: 'var(--fs-cap)',
              background: `${role.color}1f`,
              color: role.color,
              border: `1px solid ${role.color}55`,
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
            }}
          >
            {role.icon} {role.label}
            <button
              type="button"
              aria-label={`حذف نقش ${role.label}`}
              disabled={assignM.isPending}
              onClick={() => {
                haptic('light');
                assignM.mutate({
                  add: [],
                  remove: [role.key],
                });
              }}
              style={{
                all: 'unset',
                cursor: 'pointer',
                fontSize: 'var(--fs-cap)',
                opacity: 0.7,
              }}
            >
              ✕
            </button>
          </span>
        ))}
      </div>

      {/* افزودن نقش — جست‌وجو + چیپ‌های دردسترس */}
      <input
        type="search"
        className="input"
        style={{ minHeight: 32, fontSize: 'var(--fs-cap)' }}
        placeholder="جست‌وجوی نقش برای افزودن…"
        value={q}
        onChange={(event) =>
          setQ(event.target.value)
        }
        aria-label="جست‌وجوی نقش"
      />
      {needle && (
        <div
          style={{
            display: 'flex',
            gap: 6,
            flexWrap: 'wrap',
          }}
        >
          {available.length === 0 && (
            <span
              style={{
                color: 'var(--txm)',
                fontSize: 'var(--fs-cap)',
              }}
            >
              نقشی پیدا نشد
            </span>
          )}
          {available.map((role) => (
            <button
              key={role.key}
              type="button"
              className="tab-btn"
              disabled={assignM.isPending}
              style={{
                fontSize: 'var(--fs-cap)',
                minHeight: 26,
                borderColor: `${role.color}66`,
                color: role.color,
              }}
              onClick={() => {
                haptic('light');
                setQ('');
                assignM.mutate({
                  add: [role.key],
                  remove: [],
                  scope_intake:
                    role.key.endsWith('scoped') ||
                      role.key === 'grade_rep'
                      ? undefined
                      : undefined,
                });
              }}
            >
              + {role.icon} {role.label}
            </button>
          ))}
        </div>
      )}

      {/* پیش‌نمایش‌ی مجوزهای موروثی (Union نقش‌ها) */}
      {showPerms && (
        <div
          style={{
            display: 'flex',
            gap: 5,
            flexWrap: 'wrap',
            borderTop: '1px solid var(--line)',
            paddingTop: 8,
          }}
        >
          {userPerms.length === 0 && (
            <span
              style={{
                color: 'var(--txm)',
                fontSize: 'var(--fs-cap)',
              }}
            >
              مجوزی در کار نیست
            </span>
          )}
          {userPerms.map((permKey) => (
            <span
              key={permKey}
              className="badge b-gray"
              title={permKey}
              style={{ fontSize: 'var(--fs-cap)' }}
            >
              {permLabels[permKey] || permKey}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}


export function AdminUserDetail() {
  const {
    uid,
  } = useParams();

  const navigate =
    useNavigate();

  const [
    editing,
    setEditing,
  ] = useState(false);

  const [
    form,
    setForm,
  ] = useState({});

  /* ✉️ موج ۴.۸۰ — پیام مستقیم به کاربر */
  const [
    dmOpen,
    setDmOpen,
  ] = useState(false);

  const [
    dmText,
    setDmText,
  ] = useState('');

  const [
    dmBusy,
    setDmBusy,
  ] = useState(false);

  const toast = useUIStore(
    (state) => state.toast
  );

  const queryClient =
    useQueryClient();


  const {
    data: user,
    isLoading,
    isError,
  } = useQuery({
    queryKey: [
      'admin-user',
      uid,
    ],

    queryFn: () =>
      api
        .get(
          `/api/admin/users/${uid}`
        )
        .then(
          (response) =>
            response.data
              ?.user
        ),
  });


  const refresh = async () => {
    await Promise.all([
      queryClient
        .invalidateQueries({
          queryKey: [
            'admin-user',
            uid,
          ],
        }),

      queryClient
        .invalidateQueries({
          queryKey: [
            'admin-users',
          ],
        }),
    ]);
  };


  /* ✉️ ارسال پیام مستقیم به همین کاربر — موج ۴.۸۰
     (سمت سرور در صف outbox قرار می‌گیرد) */
  const sendDm = async () => {
    const text = dmText.trim();

    if (text.length < 2 || dmBusy) return;

    haptic('light');
    setDmBusy(true);

    try {
      await api.post(
        `/api/admin/users/${uid}/message`,
        { text }
      );

      hapticNotif('success');

      toast(
        'پیام در صف ارسال به کاربر قرار گرفت ✅',
        'success'
      );

      setDmText('');
      setDmOpen(false);
    } catch (error) {
      hapticNotif('error');

      toast(
        errorText(
          error,
          'ارسال پیام ناموفق بود'
        ),
        'error'
      );
    } finally {
      setDmBusy(false);
    }
  };


  const action = useMutation({
    mutationFn: ({
      type,
      payload,
    }) => {
      if (type === 'edit') {
        return api.patch(
          `/api/admin/users/${uid}`,
          payload
        );
      }

      return api.post(
        `/api/admin/users/${uid}/${type}`
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

      setEditing(false);

      await refresh();

      if (
        [
          'delete',
          'block',
          'reject',
        ].includes(
          variables.type
        )
      ) {
        navigate(
          '/admin/users'
        );
      }
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


  const startEdit = () => {
    setForm({
      name:
        user.name || '',

      student_id:
        user.student_id || '',

      intake:
        user.intake || '',

      group:
        user.group || '1',

      role:
        user.role ||
        'student',
    });

    setEditing(true);
  };


  const run = async (
    type,
    message
  ) => {
    if (
      await confirmAction(message)
    ) {
      action.mutate({
        type,
      });
    }
  };


  return (
    <>
      <Header
        title="جزئیات کاربر"
        subtitle={`شناسه ${uid}`}
      />

      <main className="page fade-up">
        {isLoading ? (
          <>
            <SkHero avatar={50} />

            <div
              style={{ height: 12 }}
            />

            <SkRowList
              n={2}
              icon={40}
              circle
            />
          </>
        ) : isError || !user ? (
          <EmptyState icon="🌐">
            کاربر پیدا نشد.
          </EmptyState>
        ) : (
          <div
            style={{
              display:
                'grid',

              gap:
                12,
            }}
          >
            <section
              className={
                'card card-glow'
              }
              style={{
                padding:
                  17,

                background:
                  'linear-gradient(145deg,var(--soft-acc),var(--surf-card))',
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
                  className="avatar"
                  style={{
                    width:
                      58,

                    height:
                      58,

                    fontSize:
                      22,
                  }}
                >
                  {user.name?.[0] ||
                    '؟'}
                </span>

                <div
                  style={{
                    flex:
                      1,
                  }}
                >
                  <h2
                    style={{
                      fontSize: 'var(--fs-xl)',
                    }}
                  >
                    {user.name ||
                      `#${uid}`}
                  </h2>

                  <div
                    style={{
                      display:
                        'flex',

                      gap:
                        5,

                      marginTop:
                        6,
                    }}
                  >
                    <span
                      className={`badge ${
                        user.suspended
                          ? 'b-red'

                          : user.approved
                            ? 'b-grn'

                            : 'b-yel'
                      }`}
                    >
                      {user.suspended
                        ? 'تعلیق‌شده'

                        : user.approved
                          ? 'فعال'

                          : 'در انتظار'}
                    </span>

                    <span className="badge b-pur">
                      {user.role ||
                        'student'}
                    </span>
                  </div>
                </div>

                <button
                  className={
                    'btn btn-dark'
                  }
                  onClick={
                    startEdit
                  }
                >
                  ✏️
                </button>
              </div>
            </section>

            {/* 🛡 RBAC-W2 — نقش‌های چندتایی دیتابیس‌محور */}
            <UserRbacCard uid={uid} />


            {editing ? (
              <section
                className="card"
                style={{
                  display:
                    'grid',

                  gap:
                    9,
                }}
              >
                <input
                  className="inp"
                  value={form.name}
                  onChange={(event) =>
                    setForm({
                      ...form,

                      name:
                        event.target
                          .value,
                    })
                  }
                  placeholder="نام"
                />

                <input
                  className="inp"
                  value={
                    form.student_id
                  }
                  onChange={(event) =>
                    setForm({
                      ...form,

                      student_id:
                        event.target
                          .value,
                    })
                  }
                  placeholder={
                    'شماره دانشجویی'
                  }
                />

                <div className="grid2">
                  <input
                    className="inp"
                    value={
                      form.intake
                    }
                    onChange={(event) =>
                      setForm({
                        ...form,

                        intake:
                          event.target
                            .value,
                      })
                    }
                    placeholder="ورودی"
                  />

                  <select
                    className="inp"
                    value={
                      form.group
                    }
                    onChange={(event) =>
                      setForm({
                        ...form,

                        group:
                          event.target
                            .value,
                      })
                    }
                  >
                    <option value="1">
                      گروه ۱
                    </option>

                    <option value="2">
                      گروه ۲
                    </option>
                  </select>
                </div>

                {/* 🛡 RBAC-W2: سلکت سه‌تایی هاردکد حذف شد؛ نقش‌ها
                    فقط از کارت RBAC بالای صفحه (دیتابیس‌محور، چندنقشی)
                    مدیریت می‌شوند — users.role به‌عنوان mirror از
                    سرور می‌آید (تک‌منبع، بدون تعریف موازی) */}
                <div
                  style={{
                    color: 'var(--txm)',
                    fontSize: 'var(--fs-cap)',
                    lineHeight: 1.8,
                  }}
                >
                  🛡 نقش‌های کاربر (چندنقشی) از کارت
                  RBAC بالای صفحه مدیریت می‌شود، نه از این فرم.
                </div>

                <div
                  style={{
                    display:
                      'flex',

                    gap: 'var(--sp-2)',
                  }}
                >
                  <button
                    className="btn btn-p"
                    style={{
                      flex:
                        2,
                    }}
                    disabled={
                      action.isPending ||
                      !form.name.trim()
                    }
                    onClick={() =>
                      action.mutate({
                        type:
                          'edit',

                        payload:
                          form,
                      })
                    }
                  >
                    {action.isPending ? (
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
                    style={{
                      flex:
                        1,
                    }}
                    onClick={() =>
                      setEditing(
                        false
                      )
                    }
                  >
                    لغو
                  </button>
                </div>
              </section>
            ) : (
              <section className="card">
                <div className="sec-title">
                  اطلاعات حساب
                </div>

                {[
                  [
                    '🎓',
                    'شماره دانشجویی',
                    user.student_id ||
                      '—',
                  ],

                  [
                    '📅',
                    'ورودی',
                    user.intake ||
                      '—',
                  ],

                  [
                    '👥',
                    'گروه',
                    user.group ||
                      '—',
                  ],

                  [
                    '📆',
                    'تاریخ ثبت‌نام',
                    user
                      .registered_at ||
                      '—',
                  ],

                  [
                    '🧪',
                    'سؤال‌های پاسخ‌داده',
                    number(
                      user
                        .total_answers
                    ),
                  ],

                  [
                    '✅',
                    'پاسخ صحیح',
                    number(
                      user
                        .correct_answers
                    ),
                  ],
                ].map(
                  ([
                    icon,
                    label,
                    value,
                  ], index) => (
                    <div
                      key={label}
                      style={{
                        display:
                          'flex',

                        padding:
                          '9px 0',

                        borderBottom:
                          index < 5
                            ? '1px solid var(--bd)'
                            : 0,
                      }}
                    >
                      <span>
                        {icon}
                      </span>

                      <span
                        style={{
                          marginRight:
                            8,

                          color:
                            'var(--txm)',

                          fontSize: 'var(--fs-cap)',
                        }}
                      >
                        {label}
                      </span>

                      <b
                        style={{
                          marginRight:
                            'auto',

                          fontSize: 'var(--fs-meta)',
                        }}
                      >
                        {value}
                      </b>
                    </div>
                  )
                )}
              </section>
            )}


            <section className="card">
              <div className="sec-title">
                عملیات مدیریتی
              </div>

              <div className="grid2">
                {!user.approved && (
                  <button
                    className="btn btn-p"
                    onClick={() =>
                      action.mutate({
                        type:
                          'approve',
                      })
                    }
                  >
                    ✅ تأیید
                  </button>
                )}

                <button
                  className={
                    'btn btn-dark'
                  }
                  onClick={() =>
                    run(
                      'suspend',

                      user.suspended
                        ? 'تعلیق کاربر برداشته شود؟'
                        : 'کاربر تعلیق شود؟'
                    )
                  }
                >
                  {user.suspended
                    ? '🔓 رفع تعلیق'
                    : '⏸ تعلیق'}
                </button>

                <button
                  className="btn btn-d"
                  onClick={() =>
                    run(
                      'delete',
                      'کاربر حذف شود؟'
                    )
                  }
                >
                  🗑 حذف
                </button>

                <button
                  className="btn btn-d"
                  onClick={() =>
                    run(
                      'block',

                      'کاربر حذف و برای همیشه مسدود شود؟'
                    )
                  }
                >
                  🚫 مسدودسازی
                </button>

                <button
                  className="btn btn-dark"
                  onClick={() => {
                    haptic('light');
                    setDmOpen(
                      (open) => !open
                    );
                  }}
                >
                  ✉️ ارسال پیام
                </button>
              </div>

              {/* ✉️ کامپوزر پیام مستقیم
                  — گیرنده: همین کاربر */}
              {dmOpen && (
                <div
                  className="pop-in"
                  style={{
                    marginTop: 'var(--sp-3)',
                  }}
                >
                  <textarea
                    className="inp"
                    style={{
                      minHeight: 76,
                      resize:
                        'vertical',
                    }}
                    placeholder={`متن پیام برای ${user.name}...`}
                    value={dmText}
                    maxLength={3500}
                    onChange={(event) =>
                      setDmText(
                        event.target
                          .value
                      )
                    }
                  />

                  <div
                    style={{
                      display: 'flex',
                      gap: 8,
                      marginTop: 8,
                    }}
                  >
                    <button
                      className="btn btn-p"
                      style={{ flex: 1 }}
                      disabled={
                        dmBusy ||
                        dmText.trim()
                          .length < 2
                      }
                      onClick={sendDm}
                    >
                      {dmBusy
                        ? '⏳ در حال ارسال...'
                        : '📨 ارسال'}
                    </button>

                    <button
                      className="btn btn-dark"
                      onClick={() => {
                        haptic('light');
                        setDmOpen(false);
                        setDmText('');
                      }}
                    >
                      لغو
                    </button>
                  </div>
                </div>
              )}
            </section>
          </div>
        )}
      </main>
    </>
  );
}


/* مدیریت ورودی‌ها */

export function AdminIntakes() {
  const [
    form,
    setForm,
  ] = useState({
    code: '',
    label: '',
  });

  const toast = useUIStore(
    (state) => state.toast
  );

  const queryClient =
    useQueryClient();


  const {
    data = [],
    isLoading,
  } = useQuery({
    queryKey: [
      'admin-intakes',
    ],

    queryFn: () =>
      api
        .get(
          '/api/admin/intakes'
        )
        .then(
          (response) =>
            response.data
              ?.intakes || []
        ),
  });


  const refresh = () =>
    queryClient.invalidateQueries({
      queryKey: [
        'admin-intakes',
      ],
    });


  const mutation = useMutation({
    mutationFn: ({
      type,
      value,
    }) => {
      if (type === 'add') {
        return api.post(
          '/api/admin/intakes',
          form
        );
      }

      if (type === 'toggle') {
        return api.post(
          `/api/admin/intakes/${
            encodeURIComponent(
              value
            )
          }/toggle`
        );
      }

      return api.delete(
        `/api/admin/intakes/${
          encodeURIComponent(
            value
          )
        }`
      );
    },

    onSuccess: async () => {
      hapticNotif(
        'success'
      );

      toast(
        'تغییرات ذخیره شد ✅',
        'success'
      );

      setForm({
        code: '',
        label: '',
      });

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


  const items =
    Array.isArray(data)
      ? data
      : [];


  return (
    <>
      <Header
        title="مدیریت ورودی‌ها"
        subtitle={`${items.length} ورودی`}
      />

      <main className="page fade-up">
        <section
          className={
            'card card-glow'
          }
          style={{
            padding:
              16,

            marginBottom:
              13,
          }}
        >
          <div className="sec-title">
            ＋ ورودی جدید
          </div>

          <div className="grid2">
            <input
              className="inp"
              value={form.code}
              onChange={(event) =>
                setForm({
                  ...form,

                  code:
                    event.target.value,
                })
              }
              placeholder="کد؛ مثل ۱۴۰۳"
            />

            <input
              className="inp"
              value={form.label}
              onChange={(event) =>
                setForm({
                  ...form,

                  label:
                    event.target.value,
                })
              }
              placeholder="عنوان ورودی"
            />
          </div>

          <button
            className={
              'btn btn-p btn-full'
            }
            style={{
              marginTop:
                9,
            }}
            disabled={
              !form.code.trim() ||
              !form.label.trim() ||
              mutation.isPending
            }
            onClick={() =>
              mutation.mutate({
                type:
                  'add',
              })
            }
          >
            {mutation.isPending ? (
              <Spinner size={14} />
            ) : (
              'افزودن ورودی'
            )}
          </button>
        </section>


        {isLoading ? (
          <SkRowList
            n={4}
            icon={40}
          />
        ) : items.length === 0 ? (
          <EmptyState>
            ورودی‌ای ثبت نشده است.
          </EmptyState>
        ) : (
          <section
            style={{
              display:
                'grid',

              gap:
                9,
            }}
          >
            {items.map((item) => (
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

                    gap:
                      11,
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
                        item.active
                          ? 'var(--soft-ok)'
                          : 'var(--soft-mut)',

                      fontSize: 'var(--fs-xl)',
                    }}
                  >
                    📅
                  </span>

                  <div
                    style={{
                      flex:
                        1,
                    }}
                  >
                    <b>
                      {item.label ||
                        item.code}
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
                        item.total
                      )}{' '}

                      دانشجو • گروه ۱:{' '}

                      {number(
                        item
                          .groups
                          ?.['1']
                      )}{' '}

                      • گروه ۲:{' '}

                      {number(
                        item
                          .groups
                          ?.['2']
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

                    marginTop: 'var(--sp-3)',
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
                          'toggle',

                        value:
                          item.code,
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
                          'این ورودی حذف شود؟'
                        );

                      if (accepted) {
                        mutation.mutate({
                          type:
                            'delete',

                          value:
                            item.code,
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
        )}
      </main>
    </>
  );
}


/* مدیران محتوا */

export function AdminContentAdmins() {
  const [
    search,
    setSearch,
  ] = useState('');

  const toast = useUIStore(
    (state) => state.toast
  );

  const queryClient =
    useQueryClient();


  const {
    data: admins = [],
    isLoading,
  } = useQuery({
    queryKey: [
      'content-admins',
    ],

    queryFn: () =>
      api
        .get(
          '/api/admin/content-admins'
        )
        .then(
          (response) =>
            response.data
              ?.admins || []
        ),
  });


  const {
    data: students = [],
    isFetching,
  } = useQuery({
    queryKey: [
      'admin-student-search',
      search,
    ],

    queryFn: () =>
      api
        .get(
          '/api/admin/students',

          {
            params: {
              q:
                search.trim(),
            },
          }
        )
        .then(
          (response) =>
            response.data
              ?.students || []
        ),

    enabled:
      search.trim().length >= 2,
  });


  const refresh = () =>
    queryClient.invalidateQueries({
      queryKey: [
        'content-admins',
      ],
    });


  const mutation = useMutation({
    mutationFn: ({
      type,
      id,
    }) => {
      if (type === 'add') {
        return api.post(
          `/api/admin/content-admins/${id}`
        );
      }

      return api.delete(
        `/api/admin/content-admins/${id}`
      );
    },

    onSuccess: async () => {
      toast(
        'دسترسی به‌روزرسانی شد ✅',
        'success'
      );

      setSearch('');

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


  const adminList =
    Array.isArray(admins)
      ? admins
      : [];


  return (
    <>
      <Header
        title="مدیران محتوا"
        subtitle={`${adminList.length} مدیر`}
      />

      <main className="page fade-up">
        <section
          className="card"
          style={{
            marginBottom:
              13,
          }}
        >
          <div className="sec-title">
            افزودن ادمین ارشد محتوا
          </div>

          <SearchField
            value={search}
            onChange={(event) =>
              setSearch(
                event.target.value
              )
            }
            placeholder={
              'نام، یوزرنیم یا آیدی عددی دانشجو...'
            }
            ariaLabel="جست‌وجوی دانشجو"
            loading={isFetching}
          />

          {(
            Array.isArray(students)
              ? students
              : []
          ).map((item) => (
            <button
              type="button"
              key={item.id}
              className="menu-row"
              onClick={() =>
                mutation.mutate({
                  type:
                    'add',

                  id:
                    item.id,
                })
              }
            >
              <span
                className="avatar"
                style={{
                  width:
                    37,

                  height:
                    37,
                }}
              >
                {item.name?.[0] ||
                  '؟'}
              </span>

              <span
                style={{
                  flex:
                    1,
                }}
              >
                <b>
                  {item.name}
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
                  گروه{' '}

                  {item.group ||
                    '—'}
                </span>
              </span>

              <span>＋</span>
            </button>
          ))}
        </section>


        <div className="sec-title">
          فهرست مدیران
        </div>


        {isLoading ? (
          <SkRowList
            n={3}
            icon={40}
            circle
          />
        ) : adminList.length === 0 ? (
          <EmptyState>
            ادمین ارشد محتوایی ثبت نشده است.
          </EmptyState>
        ) : (
          <section
            className="card"
            style={{
              padding:
                '0 14px',
            }}
          >
            {adminList.map(
              (item) => (
                <div
                  key={item.id}
                  className="menu-row"
                >
                  <span
                    className="avatar"
                    style={{
                      width:
                        39,

                      height:
                        39,
                    }}
                  >
                    {item.name?.[0] ||
                      '؟'}
                  </span>

                  <span
                    style={{
                      flex:
                        1,
                    }}
                  >
                    <b>
                      {item.name ||
                        `#${item.id}`}
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
                      ادمین ارشد محتوا
                    </span>
                  </span>

                  <button
                    className="btn btn-d"
                    style={{
                      minHeight:
                        32,

                      padding:
                        '5px 9px',
                    }}
                    onClick={async () => {
                      const accepted =
                        await confirmAction(
                          'دسترسی لغو شود؟'
                        );

                      if (accepted) {
                        mutation.mutate({
                          type:
                            'remove',

                          id:
                            item.id,
                        });
                      }
                    }}
                  >
                    لغو
                  </button>
                </div>
              )
            )}
          </section>
        )}
      </main>
    </>
  );
}


/* فهرست مسدودها */

export function AdminBlacklist() {
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
      'admin-blacklist',
    ],

    queryFn: () =>
      api
        .get(
          '/api/admin/blacklist'
        )
        .then(
          (response) =>
            response.data
              ?.blacklist || []
        ),
  });


  const mutation = useMutation({
    mutationFn: (id) =>
      api.post(
        `/api/admin/users/${id}/unblock`
      ),

    onSuccess: async () => {
      hapticNotif(
        'success'
      );

      toast(
        'مسدودیت برداشته شد ✅',
        'success'
      );

      await queryClient
        .invalidateQueries({
          queryKey: [
            'admin-blacklist',
          ],
        });
    },

    onError: (error) =>
      toast(
        errorText(
          error,
          'رفع مسدودیت انجام نشد'
        ),
        'error'
      ),
  });


  const rows =
    Array.isArray(data)
      ? data
      : [];


  return (
    <>
      <Header
        title="فهرست مسدودها"
        subtitle={`${rows.length} کاربر`}
      />

      <main className="page fade-up">
        <section
          className={
            'card card-glow'
          }
          style={{
            display:
              'flex',

            alignItems:
              'center',

            gap:
              12,

            marginBottom: 'var(--sp-4)',

            borderColor:
              'var(--bd-err)',

            background:
              'linear-gradient(145deg,var(--soft-err),var(--surf-card))',
          }}
        >
          <span
            style={{
              fontSize:
                27,
            }}
          >
            🚫
          </span>

          <div>
            <b>
              کاربران مسدودشده
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
              این کاربران امکان ثبت‌نام
              مجدد ندارند.
            </div>
          </div>
        </section>


        {isLoading ? (
          <UsersListSkeleton />
        ) : isError ? (
          <EmptyState icon="🌐">
            دریافت فهرست انجام نشد.

            <button
              className="btn btn-p"
              style={{
                marginTop:
                  12,
              }}
              onClick={() =>
                refetch()
              }
            >
              تلاش دوباره
            </button>
          </EmptyState>
        ) : rows.length === 0 ? (
          <EmptyState icon="✅">
            هیچ کاربری مسدود نیست.
          </EmptyState>
        ) : (
          <section
            style={{
              display:
                'grid',

              gap:
                9,
            }}
          >
            {rows.map((item) => (
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
                      display:
                        'grid',

                      width:
                        43,

                      height:
                        43,

                      placeItems:
                        'center',

                      borderRadius: 'var(--r-md)',

                      background:
                        'var(--soft-err)',

                      fontSize: 'var(--fs-xl)',
                    }}
                  >
                    🚫
                  </span>

                  <div
                    style={{
                      flex:
                        1,
                    }}
                  >
                    <b>
                      {item.name ||
                        `#${item.id}`}
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
                      مسدودکننده:{' '}

                      {item
                        .blocked_by_name ||
                        'مدیریت'}

                      {' • '}

                      {item.blocked_at ||
                        '—'}
                    </div>
                  </div>

                  <button
                    className="btn btn-g"
                    style={{
                      minHeight:
                        34,

                      padding:
                        '5px 9px',
                    }}
                    disabled={
                      mutation.isPending
                    }
                    onClick={async () => {
                      const accepted =
                        await confirmAction(
                          'مسدودیت برداشته شود؟'
                        );

                      if (accepted) {
                        mutation.mutate(
                          item.id
                        );
                      }
                    }}
                  >
                    رفع مسدودیت
                  </button>
                </div>
              </article>
            ))}
          </section>
        )}
      </main>
    </>
  );
}
