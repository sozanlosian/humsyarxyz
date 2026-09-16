import PageError from '../../components/shared/PageError';
import EmptyState from '../../components/shared/EmptyState';

import { errorText } from '../../lib/format';

import { confirmAction } from '../../lib/confirm';
import { useState } from 'react';

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
  LibraryTilesSkeleton,
  LibraryRowsSkeleton,
} from '../../components/shared/skeletons';

import {
  hapticNotif,
} from '../../lib/telegram';

import {
  useUIStore,
} from '../../stores/uiStore';

import {
  useContentScope,
} from '../../hooks/useContentScope';


const LETTERS = [
  'الف',
  'ب',
  'ج',
  'د',
  'هـ',
  'و',
];








function QuestionDetails({
  question,
  pending,
  onApprove,
  onReject,
  onClose,
}) {
  const options =
    Array.isArray(
      question.options
    )
      ? question.options
      : [];

  return (
    <div
      className="more-sheet"
      role="presentation"
      onClick={onClose}
    >
      <div
        className={
          'more-sheet__panel ' +
          'glass sheet-in'
        }
        role="dialog"
        aria-modal="true"
        aria-label="جزئیات سؤال"
        onClick={(event) =>
          event.stopPropagation()
        }
      >
        <div className="more-sheet__handle" />

        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 5,
            marginBottom: 11,
          }}
        >
          <span className="badge b-acc">
            {question.lesson ||
              'درس'}
          </span>

          <span className="badge b-gray">
            {question.topic ||
              'مبحث'}
          </span>

          <span
            className={`badge ${
              question.difficulty
                ?.includes('سخت')
                ? 'b-red'

                : question.difficulty
                    ?.includes('آسان')
                  ? 'b-grn'

                  : 'b-yel'
            }`}
          >
            {question.difficulty ||
              'متوسط'}
          </span>
        </div>


        <div
          style={{
            fontSize: 'var(--fs-md)',
            fontWeight: 750,
            lineHeight: 1.9,
            marginBottom: 12,
          }}
        >
          {question.question ||
            'متن سؤال موجود نیست'}
        </div>


        <div
          style={{
            display: 'grid',
            gap: 'var(--sp-2)',
          }}
        >
          {options.map(
            (
              option,
              index
            ) => {
              const correct =
                index ===
                question.correct;

              return (
                <div
                  key={index}
                  style={{
                    display: 'flex',
                    gap: 8,
                    padding:
                      '9px 10px',

                    color:
                      correct
                        ? 'var(--ok)'
                        : 'var(--tx2)',

                    background:
                      correct
                        ? 'var(--soft-ok)'
                        : 'var(--soft-mut)',

                    border:
                      `1px solid ${
                        correct
                          ? 'var(--bd-ok)'
                          : 'var(--bd)'
                      }`,

                    borderRadius: 'var(--r-md)',
                  }}
                >
                  <b>
                    {LETTERS[index] ||
                      index + 1}
                  </b>

                  <span>
                    {option}
                  </span>

                  {correct && (
                    <span
                      style={{
                        marginRight:
                          'auto',
                      }}
                    >
                      ✓ صحیح
                    </span>
                  )}
                </div>
              );
            }
          )}
        </div>


        {question.explanation && (
          <div
            style={{
              marginTop: 11,
              padding:
                '10px 11px',

              color:
                'var(--tx2)',

              background:
                'var(--soft-acc)',

              borderRadius: 'var(--r-md)',

              fontSize: 'var(--fs-cap)',

              lineHeight:
                1.8,
            }}
          >
            <b
              style={{
                color:
                  'var(--acc2)',
              }}
            >
              توضیح پاسخ:
            </b>

            <br />

            {question.explanation}
          </div>
        )}


        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            marginTop: 12,
            color: 'var(--txm)',
            fontSize: 'var(--fs-cap)',
          }}
        >
          <span>
            طراح:{' '}

            {question.creator_name ||
              'نامشخص'}
          </span>

          <span>•</span>

          <span>
            {question.created_at ||
              '—'}
          </span>

          <span
            className="badge b-gray"
            style={{
              marginRight:
                'auto',
            }}
          >
            {question.source ===
            'webapp'
              ? 'Mini App'
              : 'ربات'}
          </span>
        </div>


        <div
          style={{
            display: 'flex',
            gap: 8,
            marginTop: 'var(--sp-4)',
          }}
        >
          <button
            className="btn btn-p"
            style={{
              flex: 1,
            }}
            disabled={pending}
            onClick={onApprove}
          >
            {pending ? (
              <Spinner size={14} />
            ) : (
              '✅ تأیید سؤال'
            )}
          </button>

          <button
            className="btn btn-d"
            style={{
              flex: 1,
            }}
            disabled={pending}
            onClick={onReject}
          >
            ❌ رد سؤال
          </button>
        </div>
      </div>
    </div>
  );
}


/* مدیریت سؤال‌ها */

export function ContentQuestions() {
  const [
    selected,
    setSelected,
  ] = useState(null);

  const [
    filter,
    setFilter,
  ] = useState('all');

  const toast = useUIStore(
    (state) => state.toast
  );

  const queryClient =
    useQueryClient();

  /* 🌊 C1 — scope ورودی پنل محتوا */
  const cscope = useContentScope();

  const iv = cscope.intake ?? '';


  const {
    data = [],
    isLoading,
    isError,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: [
      'pending-content-questions',
      iv,
    ],

    queryFn: () =>
      api
        .get(
          '/api/content/questions/pending',

          {
            params: {
              intake: iv,
            },
          }
        )
        .then(
          (response) =>
            response.data
              ?.questions || []
        ),

    enabled:
      cscope.intake !== null,
  });


  const refresh = () =>
    queryClient.invalidateQueries({
      queryKey: [
        'pending-content-questions',
      ],
    });


  const action = useMutation({
    mutationFn: ({
      id,
      type,
    }) =>
      api.post(
        `/api/content/questions/${id}/${type}`
      ),

    onSuccess: async (
      _,
      variables
    ) => {
      hapticNotif(
        'success'
      );

      toast(
        variables.type ===
        'approve'
          ? 'سؤال تأیید شد ✅'
          : 'سؤال رد و حذف شد',

        variables.type ===
        'approve'
          ? 'success'
          : 'info'
      );

      setSelected(null);

      await Promise.all([
        refresh(),

        queryClient
          .invalidateQueries({
            queryKey: [
              'content-overview',
            ],
          }),
      ]);
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


  const questions =
    Array.isArray(data)
      ? data
      : [];


  const lessons = [
    ...new Set(
      questions
        .map(
          (item) =>
            item.lesson
        )
        .filter(Boolean)
    ),
  ];


  const rows =
    filter === 'all'
      ? questions

      : questions.filter(
          (item) =>
            item.lesson === filter
        );


  return (
    <>
      <Header
        title="بررسی سؤال‌ها"
        subtitle={`${questions.length} سؤال در انتظار · ${cscope.label || '—'}`}
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


      {selected && (
        <QuestionDetails
          question={selected}
          pending={
            action.isPending
          }
          onClose={() => {
            if (
              !action.isPending
            ) {
              setSelected(null);
            }
          }}
          onApprove={() =>
            action.mutate({
              id:
                selected.id,

              type:
                'approve',
            })
          }
          onReject={async () => {
            const accepted =
              await confirmAction(
                'این سؤال رد و حذف شود؟'
              );

            if (accepted) {
              action.mutate({
                id:
                  selected.id,

                type:
                  'reject',
              });
            }
          }}
        />
      )}


      <main className="page fade-up">
        <section
          className={
            'card card-glow'
          }
          style={{
            padding: 17,
            marginBottom: 'var(--sp-4)',

            background:
              'linear-gradient(145deg,var(--soft-pur),var(--surf-card) 55%,var(--soft-warn))',
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
                width: 52,
                height: 52,
                placeItems: 'center',
                borderRadius: 'var(--r-lg)',

                background:
                  'linear-gradient(135deg,var(--pur-dim),var(--acc))',

                fontSize: 25,
              }}
            >
              🔍
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
                صف بررسی علمی
              </div>

              <b
                style={{
                  display: 'block',
                  fontSize: 'var(--fs-lg)',
                  marginTop: 2,
                }}
              >
                {questions.length} سؤال
                نیازمند تصمیم
              </b>

              <div
                style={{
                  color:
                    'var(--tx2)',

                  fontSize: 'var(--fs-cap)',

                  marginTop:
                    3,
                }}
              >
                متن، گزینه صحیح و توضیح را
                قبل از انتشار بررسی کنید.
              </div>
            </div>
          </div>
        </section>


        {lessons.length > 1 && (
          <div className="tab-bar">
            <button
              className="tab-btn"
              onClick={() =>
                setFilter('all')
              }
              style={{
                color:
                  filter === 'all'
                    ? 'var(--t-white)'
                    : 'var(--tx2)',

                background:
                  filter === 'all'
                    ? 'var(--grad-brand)'
                    : 'transparent',
              }}
            >
              همه ({questions.length})
            </button>

            {lessons.map(
              (lesson) => (
                <button
                  key={lesson}
                  className="tab-btn"
                  onClick={() =>
                    setFilter(
                      lesson
                    )
                  }
                  style={{
                    color:
                      filter === lesson
                        ? 'var(--t-white)'
                        : 'var(--tx2)',

                    background:
                      filter === lesson
                        ? 'var(--grad-brand)'
                        : 'transparent',
                  }}
                >
                  {lesson}
                </button>
              )
            )}
          </div>
        )}


        {isLoading ? (
          <LibraryTilesSkeleton />
        ) : isError ? (
          <PageError
            text="دریافت سؤال‌ها انجام نشد."
            onRetry={() => refetch()}
          />
        ) : rows.length === 0 ? (
          <EmptyState icon="✅">
            سؤالی در انتظار بررسی نیست.
          </EmptyState>
        ) : (
          <section
            style={{
              display: 'grid',
              gap: 9,
            }}
          >
            {rows.map(
              (
                item,
                index
              ) => (
                <article
                  key={item.id}
                  className={
                    'card pop-in'
                  }
                  style={{
                    animationDelay:
                      `${
                        Math.min(
                          index,
                          8
                        ) * 30
                      }ms`,
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      flexWrap: 'wrap',
                      gap: 5,
                      marginBottom: 8,
                    }}
                  >
                    <span className="badge b-acc">
                      {item.lesson ||
                        'درس'}
                    </span>

                    <span className="badge b-gray">
                      {item.topic ||
                        'مبحث'}
                    </span>

                    <span
                      className={`badge ${
                        item.difficulty
                          ?.includes(
                            'سخت'
                          )
                          ? 'b-red'

                          : item.difficulty
                              ?.includes(
                                'آسان'
                              )
                            ? 'b-grn'

                            : 'b-yel'
                      }`}
                    >
                      {item.difficulty ||
                        'متوسط'}
                    </span>
                  </div>

                  <div
                    style={{
                      display:
                        '-webkit-box',

                      overflow:
                        'hidden',

                      fontSize: 'var(--fs-sm)',

                      fontWeight:
                        650,

                      lineHeight:
                        1.8,

                      WebkitBoxOrient:
                        'vertical',

                      WebkitLineClamp:
                        3,
                    }}
                  >
                    {item.question}
                  </div>

                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      marginTop: 9,
                      color: 'var(--txm)',
                      fontSize: 'var(--fs-cap)',
                    }}
                  >
                    <span>
                      ✍️{' '}

                      {item.creator_name ||
                        'نامشخص'}
                    </span>

                    <span
                      style={{
                        marginRight:
                          'auto',
                      }}
                    >
                      {item.created_at ||
                        '—'}
                    </span>
                  </div>

                  <div
                    style={{
                      display: 'flex',
                      gap: 'var(--sp-2)',
                      marginTop: 'var(--sp-3)',
                    }}
                  >
                    <button
                      className={
                        'btn btn-dark'
                      }
                      style={{
                        flex: 1,
                      }}
                      onClick={() =>
                        setSelected(
                          item
                        )
                      }
                    >
                      مشاهده کامل
                    </button>

                    <button
                      className={
                        'btn btn-p'
                      }
                      style={{
                        flex: 1,
                      }}
                      disabled={
                        action.isPending
                      }
                      onClick={() =>
                        action.mutate({
                          id:
                            item.id,

                          type:
                            'approve',
                        })
                      }
                    >
                      ✅ تأیید
                    </button>

                    <button
                      className={
                        'btn btn-d'
                      }
                      disabled={
                        action.isPending
                      }
                      onClick={async () => {
                        const accepted =
                          await confirmAction(
                            'سؤال رد شود؟'
                          );

                        if (accepted) {
                          action.mutate({
                            id:
                              item.id,

                            type:
                              'reject',
                          });
                        }
                      }}
                    >
                      ✕
                    </button>
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


/* مدیریت FAQ */

export function ContentFaq() {
  const [
    formOpen,
    setFormOpen,
  ] = useState(false);

  const [
    editTarget,
    setEditTarget,
  ] = useState(null);

  const [
    form,
    setForm,
  ] = useState({
    category:
      'عمومی',

    question:
      '',

    answer:
      '',
  });

  const [
    openId,
    setOpenId,
  ] = useState(null);

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
      'content-faq',
    ],

    queryFn: () =>
      api
        .get(
          '/api/content/faq'
        )
        .then(
          (response) =>
            response.data
              ?.items || []
        ),
  });


  const refresh = () =>
    queryClient.invalidateQueries({
      queryKey: [
        'content-faq',
      ],
    });


  const mutation = useMutation({
    mutationFn: ({
      type,
      id,
      payload,
    }) => {
      if (type === 'add') {
        return api.post(
          '/api/content/faq',
          form
        );
      }
      if (type === 'edit') {
        return api.patch(
          `/api/content/faq/${id}`,
          payload
        );
      }

      return api.delete(
        `/api/content/faq/${id}`
      );
    },

    onSuccess: async (
      _,
      variables
    ) => {
      hapticNotif(
        'success'
      );

      if (variables.type === 'edit') {
        toast('سؤال ویرایش شد ✅', 'success');
      } else {
        toast(
          variables.type === 'add'
            ? 'سؤال متداول اضافه شد ✅'
            : 'سؤال حذف شد',

          variables.type === 'add'
            ? 'success'
            : 'info'
        );
      }

      setForm({
        category:
          'عمومی',

        question:
          '',

        answer:
          '',
      });

      setEditTarget(null);
      setFormOpen(false);

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


  const categories = [
    ...new Set(
      items
        .map(
          (item) =>
            item.category
        )
        .filter(Boolean)
    ),
  ];


  const valid =
    form.question
      .trim()
      .length >= 5 &&
    form.answer
      .trim()
      .length >= 5;


  if (formOpen || editTarget) {
    const isEdit = !!editTarget;
    return (
      <>
        <Header
          title={isEdit ? 'ویرایش FAQ' : 'FAQ جدید'}
          subtitle={
            isEdit ? 'ویرایش پاسخ راهنما' : 'افزودن پاسخ به راهنمای کاربران'
          }
          onBack={() => {
            setFormOpen(false);
            setEditTarget(null);
          }}
        />

        <main className="page fade-up">
          <section
            className={
              'card card-glow'
            }
            style={{
              display: 'grid',
              gap: 'var(--sp-3)',
            }}
          >
            <input
              className="inp"
              list="faq-categories"
              value={
                form.category
              }
              onChange={(event) =>
                setForm({
                  ...form,

                  category:
                    event.target
                      .value,
                })
              }
              placeholder="دسته‌بندی"
            />

            <datalist id="faq-categories">
              {categories.map(
                (item) => (
                  <option
                    key={item}
                    value={item}
                  />
                )
              )}
            </datalist>

            <textarea
              className="inp"
              rows={3}
              maxLength={500}
              value={
                form.question
              }
              onChange={(event) =>
                setForm({
                  ...form,

                  question:
                    event.target
                      .value,
                })
              }
              placeholder="متن سؤال..."
            />

            <textarea
              className="inp"
              rows={7}
              maxLength={4000}
              value={
                form.answer
              }
              onChange={(event) =>
                setForm({
                  ...form,

                  answer:
                    event.target
                      .value,
                })
              }
              placeholder={
                'پاسخ کامل و واضح...'
              }
            />
          </section>

          <button
            className={
              'btn btn-p btn-full'
            }
            style={{
              marginTop: 12,
            }}
            disabled={
              !valid ||
              mutation.isPending
            }
            onClick={() => {
              if (isEdit) {
                const payload = {};
                if (form.category.trim() !== (editTarget.category||'')) payload.category = form.category.trim();
                if (form.question.trim() !== (editTarget.question||'')) payload.question = form.question.trim();
                if (form.answer.trim() !== (editTarget.answer||'')) payload.answer = form.answer.trim();
                if (!Object.keys(payload).length) { toast('تغییری ایجاد نشد','info'); return; }
                mutation.mutate({ type: 'edit', id: editTarget.id, payload });
              } else {
                mutation.mutate({ type: 'add' });
              }
            }}
          >
            {mutation.isPending ? (
              <Spinner size={15} />
            ) : isEdit ? (
              '💾 ذخیره ویرایش'
            ) : (
              '💾 ذخیره سؤال متداول'
            )}
          </button>
        </main>
      </>
    );
  }


  return (
    <>
      <Header
        title="مدیریت FAQ"
        subtitle={`${items.length} سؤال متداول`}
      />

      <main className="page fade-up">
        <section
          className={
            'card card-glow'
          }
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            marginBottom: 13,

            background:
              'linear-gradient(145deg,var(--soft-pur),var(--surf-card))',
          }}
        >
          <span
            style={{
              display: 'grid',
              width: 50,
              height: 50,
              placeItems: 'center',
              borderRadius: 'var(--r-lg)',

              background:
                'linear-gradient(135deg,var(--pur-dim),var(--acc))',

              fontSize: 24,
            }}
          >
            ❓
          </span>

          <div
            style={{
              flex: 1,
            }}
          >
            <b
              style={{
                fontSize: 'var(--fs-lg)',
              }}
            >
              راهنمای کاربران
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
              پاسخ‌های واضح، تعداد تیکت‌ها
              را کاهش می‌دهد.
            </div>
          </div>
        </section>


        <button
          className={
            'btn btn-p btn-full'
          }
          style={{
            marginBottom: 'var(--sp-4)',
          }}
          onClick={() =>
            setFormOpen(true)
          }
        >
          ＋ افزودن سؤال متداول
        </button>


        {isLoading ? (
          <LibraryRowsSkeleton />
        ) : isError ? (
          <EmptyState icon="🌐">
            دریافت FAQ انجام نشد.

            <button
              className="btn btn-p"
              style={{
                marginTop: 12,
              }}
              onClick={() =>
                refetch()
              }
            >
              تلاش دوباره
            </button>
          </EmptyState>
        ) : items.length === 0 ? (
          <EmptyState>
            هنوز سؤالی ثبت نشده است.
          </EmptyState>
        ) : (
          <section
            style={{
              display: 'grid',
              gap: 8,
            }}
          >
            {items.map(
              (
                item,
                index
              ) => {
                const open =
                  openId === item.id;

                return (
                  <article
                    key={item.id}
                    className={
                      'card pop-in'
                    }
                    style={{
                      animationDelay:
                        `${
                          Math.min(
                            index,
                            8
                          ) * 30
                        }ms`,

                      borderColor:
                        open
                          ? 'var(--bdg)'
                          : 'var(--bd)',
                    }}
                  >
                    <button
                      type="button"
                      onClick={() =>
                        setOpenId(
                          open
                            ? null
                            : item.id
                        )
                      }
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        width: '100%',
                        gap: 9,
                        color: 'var(--tx)',
                        textAlign: 'right',
                        background: 'none',
                        border: 0,
                        cursor: 'pointer',
                      }}
                    >
                      <span className="badge b-pur">
                        {item.category ||
                          'عمومی'}
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
                    </button>

                    {open && (
                      <>
                        <div
                          style={{
                            padding:
                              '11px 0 3px',

                            color:
                              'var(--tx2)',

                            fontSize: 'var(--fs-cap)',

                            lineHeight:
                              1.9,
                            whiteSpace:
                              'pre-wrap',
                          }}
                        >
                          {item.answer}
                        </div>

                        <div style={{ display:'flex', gap:8, marginTop:9 }}>
                          <button
                            className={'btn btn-dark'}
                            style={{ flex:1 }}
                            disabled={mutation.isPending}
                            onClick={() => {
                              setEditTarget(item);
                              setForm({ category: item.category || 'عمومی', question: item.question || '', answer: item.answer || '' });
                              setFormOpen(false);
                            }}
                          >
                            ✏️ ویرایش
                          </button>
                          <button
                            className={'btn btn-d'}
                            style={{ flex:1 }}
                            disabled={mutation.isPending}
                            onClick={async () => {
                              const accepted =
                                await confirmAction(
                                  'این سؤال متداول حذف شود؟'
                                );

                              if (accepted) {
                                mutation.mutate({
                                  type:
                                    'delete',

                                  id:
                                    item.id,
                                });
                              }
                            }}
                          >
                            🗑 حذف
                          </button>
                        </div>
                      </>
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
