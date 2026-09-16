import { number, errorText, faDateTime } from '../../lib/format';

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
import EmptyState from '../../components/shared/EmptyState';
import Switch from '../../components/shared/Switch';

import {
  Spinner,
} from '../../components/shared/Loading';

import {
  SkMenuCard,
} from '../../components/shared/skeletons';

import {
  hapticNotif,
} from '../../lib/telegram';

import {
  useUIStore,
} from '../../stores/uiStore';








const TABS = [
  [
    'config',
    'تنظیمات',
  ],

  [
    'stats',
    'آمار',
  ],

  [
    'users',
    'کاربران',
  ],

  [
    'reports',
    'گزارش‌ها',
  ],
];


export default function AiAdmin() {
  const [
    tab,
    setTab,
  ] = useState('config');

  const [
    form,
    setForm,
  ] = useState(null);

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
    data: config,
    isLoading,
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
  });


  useEffect(() => {
    if (config) {
      setForm({
        ...config,

        // این مقدار عمداً خالی است؛
        // کلید قبلی از سرور دریافت نمی‌شود.
        api_key: '',
      });
    }
  }, [config]);


  /* 🌊 W9 — کاتالوگ مرکزی providerها/مدل‌ها (بدون تایپ دستی) */
  const {
    data: catalog,
  } = useQuery({
    queryKey: [
      'ai-admin-models',
    ],

    queryFn: () => api
      .get('/api/ai-admin/models')
      .then((response) => response.data),

    staleTime: 300_000,
  });


  const {
    data: stats,
  } = useQuery({
    queryKey: [
      'ai-admin-stats',
    ],

    queryFn: () =>
      api
        .get(
          '/api/ai-admin/stats'
        )
        .then(
          (response) =>
            response.data
        ),

    enabled:
      tab === 'stats',
  });


  const {
    data: reports = [],
  } = useQuery({
    queryKey: [
      'ai-admin-reports',
    ],

    queryFn: () =>
      api
        .get(
          '/api/ai-admin/reports'
        )
        .then(
          (response) =>
            response.data
              ?.reports || []
        ),

    enabled:
      tab === 'reports',
  });


  const {
    data: users = [],
    isFetching,
  } = useQuery({
    queryKey: [
      'ai-admin-users',
      search,
    ],

    queryFn: () =>
      api
        .get(
          '/api/ai-admin/users',

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
              ?.users || []
        ),

    enabled:
      tab === 'users' &&
      search.trim().length >= 2,
  });


  const refresh = () =>
    Promise.all([
      queryClient
        .invalidateQueries({
          queryKey: [
            'ai-admin-config',
          ],
        }),

      queryClient
        .invalidateQueries({
          queryKey: [
            'ai-admin-stats',
          ],
        }),

      queryClient
        .invalidateQueries({
          queryKey: [
            'ai-admin-users',
          ],
        }),

      queryClient
        .invalidateQueries({
          queryKey: [
            'ai-status',
          ],
        }),
    ]);


  const mutation = useMutation({
    mutationFn: ({
      type,
      id,
    }) => {
      if (type === 'save') {
        return api.put(
          '/api/ai-admin/config',

          {
            ...form,

            daily_limit:
              Number(
                form.daily_limit
              ),

            image_daily_limit:
              Number(
                form.image_daily_limit
              ),

            api_key: (
              form.api_key.trim()
              || null
            ),
          }
        );
      }

      if (type === 'test') {
        return api.post(
          '/api/ai-admin/test'
        );
      }

      if (type === 'ban') {
        return api.post(
          '/api/ai-admin/users/ban',

          {
            user_id:
              id,
          }
        );
      }

      if (type === 'reset') {
        return api.post(
          '/api/ai-admin/users/reset-quota',

          {
            user_id:
              id,
          }
        );
      }

      return api.delete(
        `/api/ai-admin/users/${id}/profile`
      );
    },

    onSuccess: async (
      response,
      variables
    ) => {
      hapticNotif(
        'success'
      );

      toast(
        variables.type === 'test'
          ? (
              response.data
                ?.answer ||
              'اتصال موفق است'
            )
          : 'عملیات انجام شد ✅',

        'success'
      );

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


  if (
    isLoading ||
    !form
  ) {
    return (
      <>
        <Header title="مدیریت هوشیار" />

        <main className="page">
          <SkMenuCard n={3} />

          <div style={{ height: 12 }} />

          <SkMenuCard n={2} />
        </main>
      </>
    );
  }


  return (
    <>
      <Header
        title="مدیریت هوشیار"
        subtitle={
          `${form.provider} • ${form.model}`
        }
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

            marginBottom:
              13,

            background:
              'linear-gradient(145deg,var(--soft-pur),var(--surf-card))',
          }}
        >
          <span
            style={{
              fontSize:
                29,
            }}
          >
            🤖
          </span>

          <div
            style={{
              flex:
                1,
            }}
          >
            <b>
              مرکز کنترل هوشیار
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
              {form.enabled
                ? 'فعال'
                : 'غیرفعال'}

              {' • کلید API '}

              {form.has_api_key
                ? 'تنظیم شده'
                : 'تنظیم نشده'}
            </div>
          </div>

          <span
            className={`badge ${
              form.enabled
                ? 'b-grn'
                : 'b-red'
            }`}
          >
            {form.enabled
              ? 'فعال'
              : 'خاموش'}
          </span>
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


        {tab === 'config' ? (
          <>
            <section
              className="card"
              style={{
                display:
                  'grid',

                gap:
                  9,
              }}
            >
              {/* label → div: کنترل حالا <button role="switch"> است و
                  قراردادنِ button داخل label نه معتبر است نه کلیکِ
                  label را به سوییچ می‌رساند. */}
              <div className="menu-row">
                <span
                  style={{
                    flex:
                      1,
                  }}
                >
                  <b>
                    فعال‌بودن هوشیار
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
                    دسترسی کاربران به
                    گفت‌وگوی هوش مصنوعی
                  </span>
                </span>

                <Switch
                  on={form.enabled}
                  onToggle={(next) =>
                    setForm({
                      ...form,

                      enabled: next,
                    })
                  }
                />
              </div>


              <div className="grid2">
                <select
                  className="inp"
                  value={
                    form.provider
                  }
                  onChange={(event) => {
                    const pid = event.target.value;

                    const prov = (
                      catalog?.providers || []
                    ).find(
                      (item) => item.id === pid
                    );

                    /* با تغییر provider، مدل فعلی
                       نامعتبر می‌شود ⇒ پیش‌فرض
                       همان provider */
                    setForm({
                      ...form,

                      provider: pid,

                      model:
                        prov?.default_model
                        || form.model,
                    });
                  }}
                >
                  {(
                    catalog?.providers
                    || [
                      { id: 'gemini', label: 'Gemini' },
                      { id: 'openrouter', label: 'OpenRouter' },
                    ]
                  ).map((item) => (
                    <option
                      key={item.id}
                      value={item.id}
                    >
                      {item.label}
                    </option>
                  ))}
                </select>

                <select
                  className="inp"
                  value={
                    form.thinking
                  }
                  onChange={(event) =>
                    setForm({
                      ...form,

                      thinking:
                        event.target
                          .value,
                    })
                  }
                >
                  <option value="auto">
                    Thinking خودکار
                  </option>

                  <option value="high">
                    Thinking بالا
                  </option>
                </select>
              </div>


              {(() => {
                const providers =
                  catalog?.providers || [];

                const prov = providers.find(
                  (item) => item.id === form.provider
                );

                const ids = (prov?.models || [])
                  .map((item) => item.id);

                const isCustom = form.model
                  && !ids.includes(form.model);

                return (
                  <>
                    <select
                      className="inp"
                      value={
                        isCustom
                          ? '__custom'
                          : form.model
                      }
                      onChange={(event) =>
                        setForm({
                          ...form,

                          model:
                            event.target.value
                            === '__custom'
                              ? ''
                              : event.target.value,
                        })
                      }
                    >
                      {(prov?.models || []).map(
                        (item) => (
                          <option
                            key={item.id}
                            value={item.id}
                          >
                            {item.label}
                          </option>
                        )
                      )}

                      <option value="__custom">
                        ✏️ سفارشی (تایپ دستی)
                      </option>
                    </select>

                    {isCustom && (
                      <input
                        className="inp"
                        style={{ marginTop: 6 }}
                        placeholder="شناسه‌ی دقیق مدل"
                        value={form.model}
                        onChange={(event) =>
                          setForm({
                            ...form,

                            model:
                              event.target.value,
                          })
                        }
                      />
                    )}
                  </>
                );
              })()}


              <input
                className="inp"
                type="number"
                min="0"
                max="1000"
                value={
                  form.daily_limit
                }
                onChange={(event) =>
                  setForm({
                    ...form,

                    daily_limit:
                      event.target.value,
                  })
                }
                placeholder={
                  'محدودیت روزانه؛ صفر یعنی نامحدود'
                }
              />


              <div className="fld-label">
                🎨 تولید تصویر
              </div>

              <select
                className="inp"
                value={
                  form.image_enabled
                    ? 'on'
                    : 'off'
                }
                onChange={(event) =>
                  setForm({
                    ...form,

                    image_enabled:
                      event.target.value
                      === 'on',
                  })
                }
              >
                <option value="on">
                  تولید تصویر فعال
                </option>

                <option value="off">
                  تولید تصویر غیرفعال
                </option>
              </select>

              <select
                className="inp"
                value={
                  form.image_model
                  || catalog?.default_image_model
                  || ''
                }
                onChange={(event) =>
                  setForm({
                    ...form,

                    image_model:
                      event.target.value,
                  })
                }
              >
                {(catalog?.image_models || []).map(
                  (item) => (
                    <option
                      key={item.id}
                      value={item.id}
                    >
                      {item.label}
                    </option>
                  )
                )}
              </select>

              <input
                className="inp"
                type="number"
                min="0"
                max="1000"
                value={
                  form.image_daily_limit
                }
                onChange={(event) =>
                  setForm({
                    ...form,

                    image_daily_limit:
                      event.target.value,
                  })
                }
                placeholder={
                  'سهمیه روزانه تصویر؛ صفر یعنی نامحدود'
                }
              />


              <input
                className="inp"
                type="password"
                value={
                  form.api_key
                }
                onChange={(event) =>
                  setForm({
                    ...form,

                    api_key:
                      event.target.value,
                  })
                }
                placeholder={
                  form.has_api_key
                    ? 'کلید جدید؛ خالی یعنی بدون تغییر'
                    : 'API Key'
                }
                autoComplete="new-password"
              />


              <textarea
                className="inp"
                rows={9}
                maxLength={20000}
                value={
                  form.system_prompt
                }
                onChange={(event) =>
                  setForm({
                    ...form,

                    system_prompt:
                      event.target.value,
                  })
                }
                placeholder="System Prompt"
              />


              <textarea
                className="inp"
                rows={3}
                maxLength={1000}
                value={
                  form.disabled_message
                }
                onChange={(event) =>
                  setForm({
                    ...form,

                    disabled_message:
                      event.target.value,
                  })
                }
                placeholder={
                  'پیام حالت خاموش'
                }
              />
            </section>


            <div
              style={{
                display:
                  'flex',

                gap:
                  8,

                marginTop: 'var(--sp-3)',
              }}
            >
              <button
                className="btn btn-p"
                style={{
                  flex:
                    2,
                }}
                disabled={
                  mutation.isPending
                }
                onClick={() =>
                  mutation.mutate({
                    type:
                      'save',
                  })
                }
              >
                {mutation.isPending ? (
                  <Spinner size={15} />
                ) : (
                  'ذخیره تنظیمات'
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
                disabled={
                  mutation.isPending
                }
                onClick={() =>
                  mutation.mutate({
                    type:
                      'test',
                  })
                }
              >
                تست اتصال
              </button>
            </div>
          </>
        ) : tab === 'stats' ? (
          <section className="grid2">
            {[
              [
                'سؤال‌های امروز',

                stats
                  ?.total_today,
              ],

              [
                'کاربران امروز',

                stats
                  ?.users_today,
              ],

              [
                'کل سؤال‌ها',

                stats
                  ?.total_alltime,
              ],

              [
                'توکن کل',

                stats
                  ?.tokens_alltime,
              ],
            ].map(
              ([
                label,
                value,
              ]) => (
                <div
                  className="card"
                  key={label}
                  style={{
                    textAlign:
                      'center',
                  }}
                >
                  <b
                    style={{
                      color:
                        'var(--acc2)',

                      fontSize: 'var(--fs-xl)',
                    }}
                  >
                    {number(value)}
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
                    {label}
                  </div>
                </div>
              )
            )}
          </section>
        ) : tab === 'users' ? (
          <>
            <div
              style={{
                position:
                  'relative',

                marginBottom:
                  12,
              }}
            >
              <input
                className="inp"
                value={search}
                onChange={(event) =>
                  setSearch(
                    event.target.value
                  )
                }
                placeholder={
                  'جست‌وجوی کاربر...'
                }
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
                  <Spinner size={14} />
                </span>
              )}
            </div>


            <section
              style={{
                display:
                  'grid',

                gap:
                  8,
              }}
            >
              {users.map((user) => (
                <article
                  key={user.id}
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
                      className="avatar"
                      style={{
                        width:
                          40,

                        height:
                          40,
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
                      <b>
                        {user.name ||
                          `#${user.id}`}
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
                        امروز{' '}

                        {number(
                          user
                            .usage_today
                        )}

                        {' • کل '}

                        {number(
                          user
                            .usage_total
                        )}
                      </div>
                    </div>

                    <span
                      className={`badge ${
                        user.banned
                          ? 'b-red'
                          : 'b-grn'
                      }`}
                    >
                      {user.banned
                        ? 'مسدود'
                        : 'فعال'}
                    </span>
                  </div>

                  <div
                    style={{
                      display:
                        'flex',

                      gap:
                        6,

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
                            'reset',

                          id:
                            user.id,
                        })
                      }
                    >
                      ریست سهمیه
                    </button>

                    <button
                      className="btn btn-d"
                      style={{
                        flex:
                          1,
                      }}
                      onClick={() =>
                        mutation.mutate({
                          type:
                            'ban',

                          id:
                            user.id,
                        })
                      }
                    >
                      {user.banned
                        ? 'رفع مسدودیت'
                        : 'مسدودسازی'}
                    </button>

                    <button
                      className="btn btn-d"
                      onClick={async () => {
                        const accepted =
                          await confirmAction(
                            'حافظه و پروفایل هوشیار پاک شود؟'
                          );

                        if (accepted) {
                          mutation.mutate({
                            type:
                              'clear',

                            id:
                              user.id,
                          });
                        }
                      }}
                    >
                      🧠✕
                    </button>
                  </div>
                </article>
              ))}
            </section>
          </>
        ) : (
          <section
            style={{
              display:
                'grid',

              gap:
                8,
            }}
          >
            {reports.length ? (
              reports.map((report) => (
                <article
                  key={report.id}
                  className="card"
                >
                  <b>
                    {report.name ||
                      `#${report.user_id}`}
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
                    {faDateTime(report.created_at)}
                  </div>

                  <div
                    style={{
                      marginTop:
                        8,

                      fontSize: 'var(--fs-cap)',

                      lineHeight:
                        1.7,
                    }}
                  >
                    <span className="badge b-yel">
                      سؤال
                    </span>

                    {' '}

                    {report.question}
                  </div>

                  <div
                    style={{
                      marginTop: 'var(--sp-2)',

                      color:
                        'var(--tx2)',

                      fontSize: 'var(--fs-cap)',

                      lineHeight:
                        1.7,
                    }}
                  >
                    <span className="badge b-red">
                      پاسخ
                    </span>

                    {' '}

                    {report.answer}
                  </div>
                </article>
              ))
            ) : (
              <EmptyState icon="📭">
                گزارشی ثبت نشده است.
              </EmptyState>
            )}
          </section>
        )}
      </main>
    </>
  );
}
