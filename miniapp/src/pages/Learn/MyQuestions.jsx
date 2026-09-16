import { confirmAction } from '../../lib/confirm';
import { faDate } from '../../lib/format';
import {
  useEffect,
  useRef,
  useState,
} from 'react';
import { useSearchParams } from 'react-router-dom';

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
  QuestionsListSkeleton,
} from '../../components/shared/skeletons';

import {
  hapticNotif,
} from '../../lib/telegram';

import {
  useUIStore,
} from '../../stores/uiStore';


const LETTERS = [
  'الف',
  'ب',
  'ج',
  'د',
];


export default function MyQuestions() {
  const [
    editing,
    setEditing,
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
      'my-question-designs',
    ],

    queryFn: () =>
      api
        .get(
          '/api/questions/my-designs'
        )
        .then(
          (response) =>
            response.data
              ?.questions || []
        ),
  });


  const refresh = () =>
    queryClient.invalidateQueries({
      queryKey: [
        'my-question-designs',
      ],
    });


  const updateMutation =
    useMutation({
      mutationFn: () =>
        api.put(
          `/api/questions/my-designs/${editing.id}`,

          {
            lesson:
              editing.lesson.trim(),

            topic:
              editing.topic.trim(),

            question:
              editing.question.trim(),

            options:
              editing.options.map(
                (item) =>
                  item.trim()
              ),

            correct:
              Number(
                editing.correct
              ),

            explanation:
              editing.explanation
                ?.trim() || '',

            difficulty:
              editing.difficulty ||
              'متوسط 🟡',
          }
        ),

      onSuccess: async () => {
        hapticNotif(
          'success'
        );

        toast(
          'سؤال ویرایش شد ✅',
          'success'
        );

        setEditing(null);

        await refresh();
      },

      onError: (error) =>
        toast(
          error?.response
            ?.data
            ?.detail ||
            'ویرایش انجام نشد',

          'error'
        ),
    });


  const deleteMutation =
    useMutation({
      mutationFn: (id) =>
        api.delete(
          `/api/questions/my-designs/${id}`
        ),

      onSuccess: async () => {
        toast(
          'سؤال حذف شد',
          'info'
        );

        await refresh();
      },

      onError: (error) =>
        toast(
          error?.response
            ?.data
            ?.detail ||
            'حذف انجام نشد',

          'error'
        ),
    });


  const questions =
    Array.isArray(data)
      ? data
      : [];

  /* 🧠 موج N3 — Deep Link: ?hl=<qid> ⇒ اسکرول + فلش روی
     همان سؤال (اعلان «سؤالت تأیید شد» مستقیم همین‌جا می‌آید) */
  const [flashId, setFlashId] = useState(null);
  const [searchParams] = useSearchParams();
  const hlDone = useRef(false);

  useEffect(() => {
    if (hlDone.current || !questions.length) return;

    const hl = searchParams.get('hl');
    if (!hl) return;

    const found = questions.find(
      (it) => String(it.id) === String(hl)
    );

    if (!found) return;

    hlDone.current = true;
    setFlashId(String(found.id));

    const el = document.querySelector(
      `[data-mid="${found.id}"]`
    );

    if (el) {
      setTimeout(() => {
        el.scrollIntoView({
          behavior: 'smooth',
          block: 'center',
        });
      }, 60);

      setTimeout(() => setFlashId(null), 3200);
    }
  }, [questions, searchParams]);


  const approved =
    questions.filter(
      (item) =>
        item.approved
    ).length;


  const valid =
    editing &&
    editing.lesson.trim() &&
    editing.topic.trim() &&
    editing.question
      .trim()
      .length >= 10 &&
    editing.options?.length ===
      4 &&
    editing.options.every(
      (item) =>
        item.trim()
    );


  if (editing) {
    return (
      <>
        <Header
          title="ویرایش سؤال"
          subtitle={
            'تا قبل از تأیید قابل ویرایش است'
          }
          onBack={() =>
            setEditing(null)
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
                12,

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
                  11,
              }}
            >
              <span
                style={{
                  display:
                    'grid',

                  width:
                    46,

                  height:
                    46,

                  placeItems:
                    'center',

                  borderRadius: 'var(--r-md)',

                  background:
                    'var(--soft-pur)',

                  fontSize:
                    22,
                }}
              >
                ✏️
              </span>

              <div>
                <b>
                  ویرایش سؤال طراحی‌شده
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
                  گزینه صحیح را با لمس حرف
                  گزینه مشخص کنید.
                </div>
              </div>
            </div>
          </section>


          <section
            className="card"
            style={{
              display:
                'grid',

              gap: 'var(--sp-3)',
            }}
          >
            <div className="grid2">
              <input
                className="inp"
                value={
                  editing.lesson
                }
                onChange={(event) =>
                  setEditing({
                    ...editing,

                    lesson:
                      event.target
                        .value,
                  })
                }
                placeholder="نام درس"
              />

              <input
                className="inp"
                value={
                  editing.topic
                }
                onChange={(event) =>
                  setEditing({
                    ...editing,

                    topic:
                      event.target
                        .value,
                  })
                }
                placeholder="مبحث"
              />
            </div>

            <textarea
              className="inp"
              rows={4}
              maxLength={2000}
              value={
                editing.question
              }
              onChange={(event) =>
                setEditing({
                  ...editing,

                  question:
                    event.target
                      .value,
                })
              }
              placeholder="متن سؤال"
            />

            <div
              style={{
                color:
                  'var(--txm)',

                fontSize: 'var(--fs-cap)',
              }}
            >
              گزینه‌ها
            </div>

            {editing.options.map(
              (
                option,
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
                  <button
                    type="button"
                    className={`badge ${
                      editing.correct ===
                      index
                        ? 'b-grn'
                        : 'b-gray'
                    }`}
                    onClick={() =>
                      setEditing({
                        ...editing,

                        correct:
                          index,
                      })
                    }
                    style={{
                      width:
                        43,

                      justifyContent:
                        'center',

                      border:
                        editing.correct ===
                        index
                          ? '1px solid var(--bd-ok)'
                          : '1px solid var(--bd)',

                      cursor:
                        'pointer',
                    }}
                  >
                    {LETTERS[index]}
                  </button>

                  <input
                    className="inp"
                    value={option}
                    onChange={(event) =>
                      setEditing({
                        ...editing,

                        options:
                          editing.options.map(
                            (
                              item,
                              itemIndex
                            ) =>
                              itemIndex ===
                              index
                                ? event
                                    .target
                                    .value
                                : item
                          ),
                      })
                    }
                    placeholder={`گزینه ${LETTERS[index]}`}
                  />
                </div>
              )
            )}

            <select
              className="inp"
              value={
                editing.difficulty
              }
              onChange={(event) =>
                setEditing({
                  ...editing,

                  difficulty:
                    event.target
                      .value,
                })
              }
            >
              <option value="آسان 🟢">
                آسان
              </option>

              <option value="متوسط 🟡">
                متوسط
              </option>

              <option value="سخت 🔴">
                سخت
              </option>
            </select>

            <textarea
              className="inp"
              rows={3}
              maxLength={3000}
              value={
                editing.explanation ||
                ''
              }
              onChange={(event) =>
                setEditing({
                  ...editing,

                  explanation:
                    event.target
                      .value,
                })
              }
              placeholder={
                'توضیح پاسخ (اختیاری)'
              }
            />
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
              !valid ||
              updateMutation.isPending
            }
            onClick={() =>
              updateMutation.mutate()
            }
          >
            {updateMutation
              .isPending ? (
              <Spinner size={15} />
            ) : (
              '💾 ذخیره تغییرات'
            )}
          </button>
        </main>
      </>
    );
  }


  return (
    <>
      <Header
        title="سؤال‌های من"
        subtitle={
          'طراحی‌ها و وضعیت بررسی'
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
                13,
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
                  'linear-gradient(135deg,var(--pur-dim),var(--acc))',

                fontSize:
                  25,
              }}
            >
              ✍️
            </span>

            <div
              style={{
                flex:
                  1,
              }}
            >
              <div
                style={{
                  color:
                    'var(--txm)',

                  fontSize: 'var(--fs-cap)',
                }}
              >
                مشارکت علمی شما
              </div>

              <b
                style={{
                  display:
                    'block',

                  fontSize: 'var(--fs-lg)',

                  marginTop:
                    2,
                }}
              >
                {questions.length} سؤال
                طراحی‌شده
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
                  {approved} تأییدشده
                </span>

                <span className="badge b-yel">
                  {questions.length -
                    approved}{' '}

                  در انتظار
                </span>
              </div>
            </div>
          </div>
        </section>


        {isLoading ? (
          <QuestionsListSkeleton />
        ) : isError ? (
          <PageError
            text="دریافت سؤال‌ها انجام نشد."
            onRetry={() => refetch()}
          />
        ) : questions.length === 0 ? (
          <EmptyState icon="✍️">
            هنوز سؤالی طراحی نکرده‌اید.
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
            {questions.map(
              (
                item,
                index
              ) => (
                <article
                  key={item.id}
                  data-mid={item.id}
                  className={
                    flashId ===
                    String(item.id)
                      ? 'card pop-in hl-flash'
                      : 'card pop-in'
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
                      display:
                        'flex',

                      flexWrap:
                        'wrap',

                      gap:
                        5,

                      marginBottom:
                        8,
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
                        item.approved
                          ? 'b-grn'
                          : 'b-yel'
                      }`}
                      style={{
                        marginRight:
                          'auto',
                      }}
                    >
                      {item.approved
                        ? '✓ تأییدشده'
                        : '⏳ در انتظار'}
                    </span>
                  </div>

                  <div
                    style={{
                      fontSize: 'var(--fs-sm)',

                      fontWeight:
                        650,

                      lineHeight:
                        1.85,
                    }}
                  >
                    {item.question}
                  </div>

                  {item.created_at && (
                    <div
                      style={{
                        color:
                          'var(--txm)',

                        fontSize: 'var(--fs-cap)',

                        marginTop:
                          6,
                      }}
                    >
                      📆 {faDate(item.created_at)}
                    </div>
                  )}

                  {!item.approved && (
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
                          setEditing({
                            ...item,

                            options:
                              Array.isArray(
                                item.options
                              )
                                ? item.options
                                : [
                                    '',
                                    '',
                                    '',
                                    '',
                                  ],

                            correct:
                              Number(
                                item.correct
                              ) || 0,
                          })
                        }
                      >
                        ✏️ ویرایش
                      </button>

                      <button
                        className={
                          'btn btn-d'
                        }
                        style={{
                          flex:
                            1,
                        }}
                        disabled={
                          deleteMutation
                            .isPending
                        }
                        onClick={async () => {
                          const accepted =
                            await confirmAction(
                              'این سؤال حذف شود؟'
                            );

                          if (accepted) {
                            deleteMutation
                              .mutate(
                                item.id
                              );
                          }
                        }}
                      >
                        🗑 حذف
                      </button>
                    </div>
                  )}
                </article>
              )
            )}
          </section>
        )}
      </main>
    </>
  );
}
