import PageError from '../../components/shared/PageError';
import EmptyState from '../../components/shared/EmptyState';

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
import Switch from '../../components/shared/Switch';

import {
  Spinner,
} from '../../components/shared/Loading';

import {
  AdminOpsSkeleton,
  SkRowList,
} from '../../components/shared/skeletons';

import {
  hapticNotif,
} from '../../lib/telegram';

import {
  useUIStore,
} from '../../stores/uiStore';











/* تیکت‌های پشتیبانی ادمین */

export function AdminTickets() {
  const [
    filter,
    setFilter,
  ] = useState('open');

  const [
    selected,
    setSelected,
  ] = useState(null);

  const [
    reply,
    setReply,
  ] = useState('');

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
      'admin-tickets',
      filter,
    ],

    queryFn: () =>
      api
        .get(
          '/api/admin/tickets',

          {
            params: {
              status:
                filter ||
                undefined,
            },
          }
        )
        .then(
          (response) =>
            response.data
              ?.tickets || []
        ),
  });


  const {
    data: detail,
    isLoading:
      detailLoading,
  } = useQuery({
    queryKey: [
      'admin-ticket',
      selected,
    ],

    queryFn: () =>
      api
        .get(
          `/api/admin/tickets/${selected}`
        )
        .then(
          (response) =>
            response.data
              ?.ticket
        ),

    enabled:
      selected != null,
  });


  const refresh = async () => {
    await Promise.all([
      queryClient
        .invalidateQueries({
          queryKey:
            ['admin-tickets'],
        }),

      queryClient
        .invalidateQueries({
          queryKey: [
            'admin-ticket',
            selected,
          ],
        }),

      queryClient
        .invalidateQueries({
          queryKey:
            ['admin-stats'],
        }),
    ]);
  };


  const action = useMutation({
    mutationFn: ({
      type,
    }) => {
      if (type === 'reply') {
        return api.post(
          `/api/admin/tickets/${selected}/reply`,

          {
            message:
              reply.trim(),
          }
        );
      }

      return api.post(
        `/api/admin/tickets/${selected}/${type}`
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
        'تیکت به‌روزرسانی شد ✅',
        'success'
      );

      if (
        variables.type ===
        'reply'
      ) {
        setReply('');
      }

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


  const tickets =
    Array.isArray(data)
      ? data
      : [];


  const ticket =
    detail || {};


  if (selected != null) {
    const replies =
      Array.isArray(
        ticket.replies
      )
        ? ticket.replies
        : [];

    return (
      <>
        <Header
          title={`تیکت #${selected}`}
          subtitle={
            ticket.subject ||
            'جزئیات تیکت'
          }
          onBack={() =>
            setSelected(null)
          }
        />

        <main className="page fade-up">
          {detailLoading ? (
            <SkRowList
              n={2}
              icon={38}
              lines={2}
            />
          ) : (
            <div
              style={{
                display:
                  'grid',

                gap: 'var(--sp-3)',
              }}
            >
              <section
                className={
                  'card card-glow'
                }
              >
                <div
                  style={{
                    display:
                      'flex',

                    gap:
                      11,
                  }}
                >
                  <span
                    className="avatar"
                    style={{
                      width:
                        47,

                      height:
                        47,
                    }}
                  >
                    {ticket.user
                      ?.name?.[0] ||
                      '؟'}
                  </span>

                  <div
                    style={{
                      flex:
                        1,
                    }}
                  >
                    <b>
                      {ticket.user
                        ?.name ||
                        'کاربر'}
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
                      {ticket.user
                        ?.student_id ||
                        'بدون شماره'}

                      {' • ورودی '}

                      {ticket.user
                        ?.intake ||
                        '—'}

                      {' • گروه '}

                      {ticket.user
                        ?.group ||
                        '—'}
                    </div>
                  </div>

                  <span
                    className={`badge ${
                      ticket.status ===
                      'closed'
                        ? 'b-gray'
                        : 'b-grn'
                    }`}
                  >
                    {ticket.status ===
                    'closed'
                      ? 'بسته'
                      : 'باز'}
                  </span>
                </div>

                <div
                  style={{
                    marginTop:
                      11,

                    padding:
                      '10px 11px',

                    color:
                      'var(--tx2)',

                    background:
                      'var(--soft-mut)',

                    borderRadius: 'var(--r-md)',

                    fontSize: 'var(--fs-meta)',

                    lineHeight:
                      1.8,
                  }}
                >
                  {ticket.message ||
                    'پیامی ثبت نشده است.'}
                </div>
              </section>


              <div className="sec-title">
                💬 گفت‌وگو
              </div>


              {replies.length ===
                0 ? (
                <EmptyState>
                  هنوز پاسخی ثبت نشده است.
                </EmptyState>
              ) : (
                replies.map(
                  (
                    item,
                    index
                  ) => (
                    <div
                      key={`${
                        item.at
                      }-${index}`}
                      style={{
                        display:
                          'flex',

                        justifyContent:
                          item.sender ===
                          'support'
                            ? 'flex-start'
                            : 'flex-end',
                      }}
                    >
                      <div
                        style={{
                          maxWidth:
                            '88%',

                          padding:
                            '9px 11px',

                          background:
                            item.sender ===
                            'support'
                              ? 'var(--soft-acc)'
                              : 'var(--soft-ok)',

                          borderRadius: 'var(--r-md)',

                          fontSize: 'var(--fs-cap)',

                          lineHeight:
                            1.8,
                        }}
                      >
                        {item.text}

                        <div
                          style={{
                            color:
                              'var(--txm)',

                            fontSize: 'var(--fs-cap)',

                            marginTop:
                              3,
                          }}
                        >
                          {item.sender ===
                          'support'
                            ? 'پشتیبانی'
                            : 'دانشجو'}

                          {' • '}

                          {faDateTime(item.at)}
                        </div>
                      </div>
                    </div>
                  )
                )
              )}


              {ticket.status !==
                'closed' && (
                <section className="card">
                  <textarea
                    className="inp"
                    rows={3}
                    value={reply}
                    onChange={(event) =>
                      setReply(
                        event.target
                          .value
                      )
                    }
                    placeholder={
                      'پاسخ پشتیبانی...'
                    }
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
                      !reply.trim() ||
                      action.isPending
                    }
                    onClick={() =>
                      action.mutate({
                        type:
                          'reply',
                      })
                    }
                  >
                    {action.isPending ? (
                      <Spinner
                        size={14}
                      />
                    ) : (
                      'ارسال پاسخ'
                    )}
                  </button>
                </section>
              )}


              <button
                className={
                  'btn btn-dark btn-full'
                }
                disabled={
                  action.isPending
                }
                onClick={() =>
                  action.mutate({
                    type:
                      ticket.status ===
                      'closed'
                        ? 'reopen'
                        : 'close',
                  })
                }
              >
                {ticket.status ===
                'closed'
                  ? '🔓 بازگشایی تیکت'
                  : '🔒 بستن تیکت'}
              </button>
            </div>
          )}
        </main>
      </>
    );
  }


  return (
    <>
      <Header
        title="تیکت‌های پشتیبانی"
        subtitle={`${tickets.length} مورد`}
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
              'linear-gradient(145deg,var(--soft-warn),var(--surf-card))',
          }}
        >
          <span
            style={{
              fontSize:
                28,
            }}
          >
            🎫
          </span>

          <div>
            <b>
              صندوق پشتیبانی
            </b>

            <div
              style={{
                color:
                  'var(--txm)',

                fontSize: 'var(--fs-cap)',
              }}
            >
              پاسخ و پیگیری درخواست‌های
              دانشجویان
            </div>
          </div>
        </section>


        <div className="tab-bar">
          {[
            [
              'open',
              'باز',
            ],

            [
              'closed',
              'بسته',
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
                  setFilter(key)
                }
                style={{
                  color:
                    filter === key
                      ? 'var(--t-white)'
                      : 'var(--tx2)',

                  background:
                    filter === key
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
          <AdminOpsSkeleton />
        ) : isError ? (
          <PageError
            text="دریافت تیکت‌ها انجام نشد."
            onRetry={() => refetch()}
          />
        ) : tickets.length === 0 ? (
          <EmptyState>
            تیکتی در این وضعیت نیست.
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
            {tickets.map(
              (item) => (
                <button
                  type="button"
                  key={item.id}
                  className={
                    'card card-tap'
                  }
                  onClick={() =>
                    setSelected(
                      item.id
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

                    textAlign:
                      'right',
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
                        item.status ===
                        'closed'
                          ? 'var(--soft-mut)'
                          : 'var(--soft-warn)',
                    }}
                  >
                    🎫
                  </span>

                  <span
                    style={{
                      flex:
                        1,
                    }}
                  >
                    <b>
                      {item.user_name ||
                        'کاربر'}

                      {' • #'}

                      {item.id}
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
                      {item.subject}

                      {' • '}

                      {number(
                        item.reply_count
                      )}{' '}

                      پاسخ
                    </span>
                  </span>

                  <span
                    className={`badge ${
                      item.status ===
                      'closed'
                        ? 'b-gray'
                        : 'b-yel'
                    }`}
                  >
                    {item.status ===
                    'closed'
                      ? 'بسته'
                      : 'باز'}
                  </span>

                  <span>←</span>
                </button>
              )
            )}
          </section>
        )}
      </main>
    </>
  );
}


/* ارسال همگانی */

export function BroadcastAdmin() {
  const [
    form,
    setForm,
  ] = useState({
    text: '',
    scope: 'all',
    intake: '',
    group: '',
    send_at: '',
  });

  const [
    preview,
    setPreview,
  ] = useState(null);

  const toast = useUIStore(
    (state) => state.toast
  );

  const queryClient =
    useQueryClient();


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
  });


  const {
    data: history = [],
  } = useQuery({
    queryKey: [
      'broadcast-history',
    ],

    queryFn: () =>
      api
        .get(
          '/api/admin/broadcast/history'
        )
        .then(
          (response) =>
            response.data
              ?.history || []
        ),
  });


  const target = {
    scope:
      form.scope,

    intake:
      form.intake ||
      null,

    group:
      form.group ||
      null,
  };


  const previewMutation =
    useMutation({
      mutationFn: () =>
        api.post(
          '/api/admin/broadcast/preview',
          {
            target,
          }
        ),

      onSuccess: (
        response
      ) =>
        setPreview(
          response.data
            ?.recipient_count || 0
        ),

      onError: (error) =>
        toast(
          errorText(
            error,
            'پیش‌نمایش انجام نشد'
          ),
          'error'
        ),
    });


  const sendMutation =
    useMutation({
      mutationFn: () =>
        api.post(
          '/api/admin/broadcast',

          {
            text:
              form.text.trim(),

            target,

            send_at:
              form.send_at
                ? new Date(
                    form.send_at
                  ).toISOString()
                : null,
          }
        ),

      onSuccess: async (
        response
      ) => {
        hapticNotif(
          'success'
        );

        toast(
          `${
            response.data
              ?.queued || 0
          } پیام در صف قرار گرفت ✅`,

          'success'
        );

        setForm({
          text: '',
          scope: 'all',
          intake: '',
          group: '',
          send_at: '',
        });

        setPreview(null);

        await queryClient
          .invalidateQueries({
            queryKey: [
              'broadcast-history',
            ],
          });
      },

      onError: (error) =>
        toast(
          errorText(
            error,
            'ارسال انجام نشد'
          ),
          'error'
        ),
    });


  return (
    <>
      <Header
        title="ارسال همگانی"
        subtitle={
          'پیام هدفمند و زمان‌بندی‌شده'
        }
      />

      <main className="page fade-up">
        <section
          className={
            'card card-glow'
          }
          style={{
            marginBottom:
              13,

            background:
              'linear-gradient(145deg,var(--soft-info),var(--surf-card))',
          }}
        >
          <div
            style={{
              display:
                'flex',

              gap:
                11,
            }}
          >
            <span
              style={{
                fontSize:
                  28,
              }}
            >
              📣
            </span>

            <div>
              <b>
                مرکز ارتباط با کاربران
              </b>

              <div
                style={{
                  color:
                    'var(--txm)',

                  fontSize: 'var(--fs-cap)',
                }}
              >
                پیام فوری یا زمان‌بندی‌شده
                ارسال کنید.
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
          }}
        >
          <textarea
            className="inp"
            rows={6}
            maxLength={4000}
            value={
              form.text
            }
            onChange={(event) => {
              setForm({
                ...form,

                text:
                  event.target.value,
              });

              setPreview(null);
            }}
            placeholder="متن پیام..."
          />

          <select
            className="inp"
            value={
              form.scope
            }
            onChange={(event) => {
              setForm({
                ...form,

                scope:
                  event.target.value,
              });

              setPreview(null);
            }}
          >
            <option value="all">
              همه کاربران
            </option>

            <option value="intake">
              یک ورودی
            </option>

            <option value="intake_group">
              یک ورودی و گروه
            </option>
          </select>

          {form.scope !==
            'all' && (
            <select
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
            >
              <option value="">
                انتخاب ورودی
              </option>

              {intakes.map(
                (item) => (
                  <option
                    key={item.code}
                    value={item.code}
                  >
                    {item.label ||
                      item.code}
                  </option>
                )
              )}
            </select>
          )}

          {form.scope ===
            'intake_group' && (
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
              <option value="">
                انتخاب گروه
              </option>

              <option value="1">
                گروه ۱
              </option>

              <option value="2">
                گروه ۲
              </option>
            </select>
          )}

          <label
            style={{
              color:
                'var(--txm)',

              fontSize: 'var(--fs-cap)',
            }}
          >
            زمان ارسال؛ خالی یعنی فوری
          </label>

          <input
            className="inp"
            type="datetime-local"
            value={
              form.send_at
            }
            onChange={(event) =>
              setForm({
                ...form,

                send_at:
                  event.target.value,
              })
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
            className={
              'btn btn-dark'
            }
            style={{
              flex:
                1,
            }}
            disabled={
              form.text
                .trim()
                .length < 5 ||
              previewMutation
                .isPending
            }
            onClick={() =>
              previewMutation.mutate()
            }
          >
            {previewMutation
              .isPending ? (
              <Spinner size={14} />
            ) : (
              'پیش‌نمایش مخاطبان'
            )}
          </button>

          <button
            className="btn btn-p"
            style={{
              flex:
                1,
            }}
            disabled={
              form.text
                .trim()
                .length < 5 ||
              preview == null ||
              sendMutation.isPending
            }
            onClick={async () => {
              const accepted =
                await confirmAction(
                  `پیام برای ${
                    preview || 0
                  } نفر ارسال شود؟`
                );

              if (accepted) {
                sendMutation.mutate();
              }
            }}
          >
            {sendMutation
              .isPending ? (
              <Spinner size={14} />
            ) : (
              `ارسال به ${
                preview ?? '—'
              } نفر`
            )}
          </button>
        </div>


        <div
          className="sec-title"
          style={{
            marginTop:
              17,
          }}
        >
          تاریخچه ارسال
        </div>

        {history.length === 0 ? (
          <EmptyState>
            ارسالی ثبت نشده است.
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
            {history.map(
              (
                item,
                index
              ) => (
                <article
                  key={`${
                    item.created_at
                  }-${index}`}
                  className="card"
                >
                  <div
                    style={{
                      fontSize: 'var(--fs-meta)',

                      lineHeight:
                        1.7,
                    }}
                  >
                    {item.text}
                  </div>

                  <div
                    style={{
                      display:
                        'flex',

                      gap:
                        5,

                      marginTop: 'var(--sp-2)',
                    }}
                  >
                    <span className="badge b-gray">
                      {number(
                        item.total
                      )}{' '}

                      کل
                    </span>

                    <span className="badge b-grn">
                      {number(
                        item.sent
                      )}{' '}

                      موفق
                    </span>

                    {number(
                      item.failed
                    ) > 0 && (
                      <span className="badge b-red">
                        {number(
                          item.failed
                        )}{' '}

                        ناموفق
                      </span>
                    )}
                  </div>
                </article>
              )
            )}
          </section>
        )}
      </main>
    </>
  );
}


/* نظرسنجی */

export function PollAdmin() {
  const [
    channel,
    setChannel,
  ] = useState('');

  const [
    question,
    setQuestion,
  ] = useState('');

  const [
    options,
    setOptions,
  ] = useState([
    '',
    '',
  ]);

  const [
    anonymous,
    setAnonymous,
  ] = useState(false);

  const toast = useUIStore(
    (state) => state.toast
  );

  const queryClient =
    useQueryClient();


  const {
    data: status,
  } = useQuery({
    queryKey: [
      'poll-status',
    ],

    queryFn: () =>
      api
        .get(
          '/api/admin/poll/status'
        )
        .then(
          (response) =>
            response.data
        ),
  });


  const channelMutation =
    useMutation({
      mutationFn: () =>
        api.post(
          '/api/admin/poll/channel',

          {
            channel_id:
              channel.trim(),
          }
        ),

      onSuccess: async () => {
        toast(
          'کانال ذخیره شد ✅',
          'success'
        );

        await queryClient
          .invalidateQueries({
            queryKey:
              ['poll-status'],
          });
      },

      onError: (error) =>
        toast(
          errorText(
            error,
            'ذخیره کانال انجام نشد'
          ),
          'error'
        ),
    });


  const pollMutation =
    useMutation({
      mutationFn: () =>
        api.post(
          '/api/admin/poll',

          {
            question:
              question.trim(),

            options:
              options.map(
                (item) =>
                  item.trim()
              ),

            anonymous,
          }
        ),

      onSuccess: () => {
        hapticNotif(
          'success'
        );

        toast(
          'نظرسنجی ارسال شد ✅',
          'success'
        );

        setQuestion('');

        setOptions([
          '',
          '',
        ]);
      },

      onError: (error) =>
        toast(
          errorText(
            error,
            'ارسال نظرسنجی انجام نشد'
          ),
          'error'
        ),
    });


  const valid =
    question.trim().length >= 3 &&
    options.length >= 2 &&
    options.every(
      (item) =>
        item.trim()
    );


  return (
    <>
      <Header
        title="نظرسنجی کانال"
        subtitle={
          status?.configured
            ? `کانال ${status.channel_id}`
            : 'کانال تنظیم نشده'
        }
      />

      <main className="page fade-up">
        <section
          className={
            'card card-glow'
          }
          style={{
            marginBottom:
              13,
          }}
        >
          <div className="sec-title">
            📡 تنظیم کانال
          </div>

          <div
            style={{
              display:
                'flex',

              gap: 'var(--sp-2)',
            }}
          >
            <input
              className="inp"
              value={channel}
              onChange={(event) =>
                setChannel(
                  event.target.value
                )
              }
              placeholder={
                '@channel یا chat_id'
              }
            />

            <button
              className="btn btn-p"
              disabled={
                !channel.trim() ||
                channelMutation
                  .isPending
              }
              onClick={() =>
                channelMutation
                  .mutate()
              }
            >
              ذخیره
            </button>
          </div>
        </section>


        <section
          className="card"
          style={{
            display:
              'grid',

            gap:
              9,
          }}
        >
          <div className="sec-title">
            📊 نظرسنجی جدید
          </div>

          <textarea
            className="inp"
            rows={3}
            value={question}
            onChange={(event) =>
              setQuestion(
                event.target.value
              )
            }
            placeholder={
              'سؤال نظرسنجی'
            }
          />

          {options.map(
            (
              item,
              index
            ) => (
              <div
                key={index}
                style={{
                  display:
                    'flex',

                  gap: 'var(--sp-2)',
                }}
              >
                <input
                  className="inp"
                  value={item}
                  onChange={(event) =>
                    setOptions(
                      (current) =>
                        current.map(
                          (
                            value,
                            itemIndex
                          ) =>
                            itemIndex ===
                            index
                              ? event
                                  .target
                                  .value
                              : value
                        )
                    )
                  }
                  placeholder={`گزینه ${index + 1}`}
                />

                {options.length >
                  2 && (
                  <button
                    className="btn btn-d"
                    onClick={() =>
                      setOptions(
                        (current) =>
                          current.filter(
                            (
                              _,
                              itemIndex
                            ) =>
                              itemIndex !==
                              index
                          )
                      )
                    }
                  >
                    ✕
                  </button>
                )}
              </div>
            )
          )}

          <button
            className={
              'btn btn-dark'
            }
            disabled={
              options.length >= 10
            }
            onClick={() =>
              setOptions(
                (current) => [
                  ...current,
                  '',
                ]
              )
            }
          >
            ＋ افزودن گزینه
          </button>

          {/* label → div چون کنترل دیگر input نیست بلکه
              <button role="switch"> است. */}
          <div className="menu-row">
            <span
              style={{
                flex:
                  1,
              }}
            >
              <b>
                رأی‌گیری ناشناس
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
                نام رأی‌دهندگان نمایش داده
                نشود
              </span>
            </span>

            <Switch
              on={anonymous}
              onToggle={setAnonymous}
            />
          </div>
        </section>


        <button
          className={
            'btn btn-p btn-full'
          }
          style={{
            marginTop:
              12,
          }}
          disabled={
            !status?.configured ||
            !valid ||
            pollMutation.isPending
          }
          onClick={async () => {
            const accepted =
              await confirmAction(
                'نظرسنجی در کانال ارسال شود؟'
              );

            if (accepted) {
              pollMutation.mutate();
            }
          }}
        >
          {pollMutation
            .isPending ? (
            <Spinner size={15} />
          ) : (
            '📤 ارسال نظرسنجی'
          )}
        </button>
      </main>
    </>
  );
}


/* مدیریت اعلان‌ها */

export function NotificationsAdmin() {
  const [
    interval,
    setIntervalValue,
  ] = useState(24);

  const toast = useUIStore(
    (state) => state.toast
  );

  const queryClient =
    useQueryClient();


  const {
    data: settings,
  } = useQuery({
    queryKey: [
      'admin-notif-settings',
    ],

    queryFn: () =>
      api
        .get(
          '/api/admin/notifications/settings'
        )
        .then(
          (response) =>
            response.data
        ),
  });


  useEffect(() => {
    if (
      settings?.interval_hours
    ) {
      setIntervalValue(
        settings.interval_hours
      );
    }
  }, [
    settings?.interval_hours,
  ]);


  const {
    data: history = [],
    isLoading,
  } = useQuery({
    queryKey: [
      'admin-notif-history',
    ],

    queryFn: () =>
      api
        .get(
          '/api/admin/notifications/history'
        )
        .then(
          (response) =>
            response.data
              ?.runs || []
        ),
  });


  const saveMutation =
    useMutation({
      mutationFn: () =>
        api.post(
          '/api/admin/notifications/settings',

          {
            interval_hours:
              Number(interval),
          }
        ),

      onSuccess: async () => {
        toast(
          'تنظیمات ذخیره شد ✅',
          'success'
        );

        await queryClient
          .invalidateQueries({
            queryKey: [
              'admin-notif-settings',
            ],
          });
      },

      onError: (error) =>
        toast(
          errorText(
            error,
            'ذخیره انجام نشد'
          ),
          'error'
        ),
    });


  const retryMutation =
    useMutation({
      mutationFn: (id) =>
        api.post(
          `/api/admin/notifications/history/${id}/retry`
        ),

      onSuccess: (
        response
      ) =>
        toast(
          `${
            response.data
              ?.requeued || 0
          } پیام دوباره در صف قرار گرفت`,

          'success'
        ),

      onError: (error) =>
        toast(
          errorText(
            error,
            'ارسال مجدد انجام نشد'
          ),
          'error'
        ),
    });


  const runs =
    Array.isArray(history)
      ? history
      : [];


  return (
    <>
      <Header
        title="مدیریت اعلان‌ها"
        subtitle={
          'فاصله ارسال، تاریخچه و Retry'
        }
      />

      <main className="page fade-up">
        <section
          className={
            'card card-glow'
          }
          style={{
            marginBottom:
              13,
          }}
        >
          <div className="sec-title">
            ⚙️ تنظیم فاصله ارسال منابع
          </div>

          <div
            style={{
              display:
                'flex',

              gap: 'var(--sp-2)',
            }}
          >
            {[
              24,
              48,
              72,
            ].map((value) => (
              <button
                key={value}
                className={`btn ${
                  Number(interval) ===
                  value
                    ? 'btn-p'
                    : 'btn-dark'
                }`}
                style={{
                  flex:
                    1,
                }}
                onClick={() =>
                  setIntervalValue(
                    value
                  )
                }
              >
                {value} ساعت
              </button>
            ))}
          </div>

          <button
            className={
              'btn btn-g btn-full'
            }
            style={{
              marginTop:
                9,
            }}
            disabled={
              saveMutation
                .isPending
            }
            onClick={() =>
              saveMutation.mutate()
            }
          >
            ذخیره تنظیمات
          </button>

          {settings?.last_sent && (
            <div
              style={{
                color:
                  'var(--txm)',

                fontSize: 'var(--fs-cap)',

                marginTop: 'var(--sp-2)',
              }}
            >
              آخرین ارسال:{' '}

              {settings.last_sent}
            </div>
          )}

          {settings?.last_error && (
            <div
              style={{
                color:
                  'var(--err)',

                fontSize: 'var(--fs-cap)',

                marginTop: 'var(--sp-1)',
              }}
            >
              آخرین خطا:{' '}

              {settings.last_error}
            </div>
          )}
        </section>


        <div className="sec-title">
          🕘 تاریخچه اجرا
        </div>


        {isLoading ? (
          <SkRowList
            n={3}
            icon={36}
          />
        ) : runs.length === 0 ? (
          <EmptyState>
            تاریخچه‌ای ثبت نشده است.
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
            {runs.map((item) => (
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
                        42,

                      height:
                        42,

                      placeItems:
                        'center',

                      borderRadius: 'var(--r-md)',

                      background:
                        item.status ===
                        'success'
                          ? 'var(--soft-ok)'
                          : 'var(--soft-err)',
                    }}
                  >
                    {item.status ===
                    'success'
                      ? '✅'
                      : '⚠️'}
                  </span>

                  <div
                    style={{
                      flex:
                        1,
                    }}
                  >
                    <b>
                      {item.job_name ||
                        'ارسال اعلان'}
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
                        item.sent
                      )}{' '}

                      موفق •{' '}

                      {number(
                        item.failed
                      )}{' '}

                      ناموفق •{' '}

                      {number(
                        item.total
                      )}{' '}

                      کل
                    </div>
                  </div>

                  <span
                    className={`badge ${
                      item.status ===
                      'success'
                        ? 'b-grn'
                        : 'b-red'
                    }`}
                  >
                    {item.status}
                  </span>
                </div>

                {number(
                  item.failed
                ) > 0 && (
                  <button
                    className={
                      'btn btn-d btn-full'
                    }
                    style={{
                      marginTop:
                        9,
                    }}
                    disabled={
                      retryMutation
                        .isPending
                    }
                    onClick={() =>
                      retryMutation
                        .mutate(
                          item.id
                        )
                    }
                  >
                    {retryMutation
                      .isPending ? (
                      <Spinner
                        size={13}
                      />
                    ) : (
                      '↻ تلاش مجدد ناموفق‌ها'
                    )}
                  </button>
                )}
              </article>
            ))}
          </section>
        )}
      </main>
    </>
  );
}
