import {
  useCallback,
  useState,
} from 'react';

import {
  useNavigate,
  useSearchParams,
} from 'react-router-dom';

import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import api from '../../lib/api';
import Header from '../../components/layout/Header';
import SubscriptionLock, {
  isSubscriptionLock,
  lockKind,
} from '../../components/shared/SubscriptionLock';
import QuestionCard from '../../components/shared/QuestionCard';
import CelebrationOverlay from '../../components/shared/CelebrationOverlay';

import {

  Spinner,
} from '../../components/shared/Loading';

import {
  SkTileGrid,
} from '../../components/shared/skeletons';

import {
  haptic,
  hapticNotif,
} from '../../lib/telegram';

import {
  useUIStore,
} from '../../stores/uiStore';


const DIFFICULTIES = [
  [
    'آسان 🟢',
    'آسان',
  ],

  [
    'متوسط 🟡',
    'متوسط',
  ],

  [
    'سخت 🔴',
    'سخت',
  ],
];


const LETTERS = [
  'الف',
  'ب',
  'ج',
  'د',
];


function ResultBox({
  result,
  onNext,
}) {
  /* 👑 موج P0 — خلاصه‌ی Prestige پاسخ
     (افزایشی؛ در نبودش هیچ خطی کشیده نمی‌شود) */
  const prestige =
    result?.prestige || null;

  const xpGained =
    Number(prestige?.xp_gained) || 0;

  return (
    <section
      className={
        'card pop-in'
      }
      style={{
        marginBottom:
          12,

        borderColor:
          result.is_correct
            ? 'var(--bd-ok)'
            : 'var(--bd-err)',
      }}
    >
      <div
        style={{
          color:
            result.is_correct
              ? 'var(--ok)'
              : 'var(--err)',

          fontSize: 'var(--fs-lg)',

          fontWeight:
            900,
        }}
      >
        {result.is_correct
          ? '✅ پاسخ صحیح؛ آفرین!'
          : '❌ پاسخ نادرست'}
      </div>

      {prestige && (
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            gap: 6,
            marginTop: 'var(--sp-2)',

            color: 'var(--tx2)',
            fontSize: 'var(--fs-cap)',
            fontWeight: 700,
          }}
        >
          {xpGained > 0 && (
            <span
              style={{
                color: 'var(--warn)',
              }}
            >
              ⚡ +{xpGained} XP
            </span>
          )}

          {prestige.display?.title && (
            <span>
              {prestige.display.icon}{' '}
              {prestige.display.title}{' '}
              {prestige.display.stars}
            </span>
          )}

          {Number(
            prestige.streak?.current
          ) > 1 && (
            <span>
              · 🔥{' '}
              {prestige.streak.current}{' '}
              روز
            </span>
          )}
        </div>
      )}

      {result.explanation && (
        <div
          style={{
            marginTop:
              8,

            color:
              'var(--tx2)',

            fontSize: 'var(--fs-meta)',

            lineHeight:
              1.9,
          }}
        >
          {result.explanation}
        </div>
      )}

      <button
        className={
          'btn btn-p btn-full'
        }
        style={{
          marginTop:
            12,
        }}
        onClick={onNext}
      >
        سؤال بعدی ←
      </button>
    </section>
  );
}


function DesignQuestion({
  onBack,
}) {
  const [
    form,
    setForm,
  ] = useState({
    lesson: '',
    topic: '',
    question: '',

    options: [
      '',
      '',
      '',
      '',
    ],

    correct: 0,
    explanation: '',
    difficulty: 'متوسط 🟡',
  });

  const toast = useUIStore(
    (state) => state.toast
  );

  const queryClient =
    useQueryClient();


  const {
    data: lessons = [],
  } = useQuery({
    queryKey: [
      'question-lessons',
    ],

    queryFn: () =>
      api
        .get(
          '/api/questions/lessons'
        )
        .then(
          (response) =>
            response.data
              ?.lessons || []
        ),

    staleTime:
      10 * 60 * 1000,
  });


  const {
    data: topics = [],
  } = useQuery({
    queryKey: [
      'question-topics',
      form.lesson,
    ],

    queryFn: () =>
      api
        .get(
          `/api/questions/topics/${
            encodeURIComponent(
              form.lesson
            )
          }`
        )
        .then(
          (response) =>
            response.data
              ?.topics || []
        ),

    enabled:
      Boolean(form.lesson),

    staleTime:
      10 * 60 * 1000,
  });


  const mutation =
    useMutation({
      mutationFn: () =>
        api.post(
          '/api/questions/design',

          {
            ...form,

            lesson:
              form.lesson.trim(),

            topic:
              form.topic.trim(),

            question:
              form.question.trim(),

            options:
              form.options.map(
                (item) =>
                  item.trim()
              ),
          }
        ),

      onSuccess: async (
        response
      ) => {
        hapticNotif(
          'success'
        );

        toast(
          response.data
            ?.message ||
            'سؤال ثبت شد ✅',

          'success'
        );

        await queryClient
          .invalidateQueries({
            queryKey: [
              'my-question-designs',
            ],
          });

        onBack();
      },

      onError: (error) =>
        toast(
          error?.response
            ?.data
            ?.detail ||
            'ثبت سؤال انجام نشد',

          'error'
        ),
    });


  const normalizedOptions =
    form.options.map(
      (item) =>
        item.trim()
    );


  const valid =
    form.lesson.trim() &&
    form.topic.trim() &&
    form.question
      .trim()
      .length >= 10 &&
    normalizedOptions.every(
      Boolean
    ) &&
    new Set(
      normalizedOptions
    ).size === 4;


  return (
    <>
      <Header
        title="طراحی سؤال"
        subtitle={
          'مشارکت در بانک سؤال هامزیار'
        }
        onBack={onBack}
      />

      <main className="page fade-up">
        <section
          className={
            'card card-glow ' +
            'hero-card hero-card--purple'
          }
          style={{
            marginBottom:
              12,
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
                  'linear-gradient(135deg,var(--pur-dim),var(--acc))',

                fontSize:
                  24,
              }}
            >
              ✍️
            </span>

            <div>
              <b>
                یک سؤال استاندارد طراحی کن
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
                سؤال دانشجو پس از بررسی
                ادمین محتوا منتشر می‌شود.
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
            <select
              className="inp"
              value={
                form.lesson
              }
              onChange={(event) =>
                setForm({
                  ...form,

                  lesson:
                    event.target
                      .value,

                  topic:
                    '',
                })
              }
            >
              <option value="">
                انتخاب درس
              </option>

              {lessons.map(
                (item) => (
                  <option
                    key={item.name}
                    value={item.name}
                  >
                    {item.name}
                  </option>
                )
              )}
            </select>

            <input
              className="inp"
              list="question-topics"
              value={
                form.topic
              }
              onChange={(event) =>
                setForm({
                  ...form,

                  topic:
                    event.target
                      .value,
                })
              }
              placeholder="مبحث"
            />

            <datalist id="question-topics">
              {topics.map(
                (item) => (
                  <option
                    key={item.name}
                    value={item.name}
                  />
                )
              )}
            </datalist>
          </div>

          <textarea
            className="inp"
            rows={4}
            maxLength={2000}
            value={
              form.question
            }
            onChange={(event) =>
              setForm({
                ...form,

                question:
                  event.target.value,
              })
            }
            placeholder={
              'متن سؤال را بنویسید...'
            }
          />

          <div
            style={{
              color:
                'var(--txm)',

              fontSize: 'var(--fs-cap)',
            }}
          >
            گزینه‌ها؛ روی حرف پاسخ صحیح
            بزنید
          </div>

          {form.options.map(
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
                    form.correct ===
                    index
                      ? 'b-grn'
                      : 'b-gray'
                  }`}
                  onClick={() =>
                    setForm({
                      ...form,

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
                      form.correct ===
                      index
                        ? '1px solid var(--bd-ok)'
                        : '1px solid var(--bd)',
                  }}
                >
                  {LETTERS[index]}
                </button>

                <input
                  className="inp"
                  value={option}
                  onChange={(event) =>
                    setForm({
                      ...form,

                      options:
                        form.options.map(
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

          <div
            style={{
              display:
                'flex',

              gap:
                6,
            }}
          >
            {DIFFICULTIES.map(
              ([
                value,
                label,
              ]) => (
                <button
                  type="button"
                  key={value}
                  className={`btn ${
                    form.difficulty ===
                    value
                      ? 'btn-p'
                      : 'btn-dark'
                  }`}
                  style={{
                    flex:
                      1,
                  }}
                  onClick={() =>
                    setForm({
                      ...form,

                      difficulty:
                        value,
                    })
                  }
                >
                  {label}
                </button>
              )
            )}
          </div>

          <textarea
            className="inp"
            rows={3}
            maxLength={3000}
            value={
              form.explanation
            }
            onChange={(event) =>
              setForm({
                ...form,

                explanation:
                  event.target.value,
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
            mutation.isPending
          }
          onClick={() =>
            mutation.mutate()
          }
        >
          {mutation.isPending ? (
            <Spinner size={15} />
          ) : (
            '📨 ثبت سؤال'
          )}
        </button>
      </main>
    </>
  );
}


export default function Questions() {
  const [
    params,
  ] = useSearchParams();

  const navigate =
    useNavigate();

  const initial =
    params.get('mode') ||
    'menu';

  const [
    view,
    setView,
  ] = useState(
    initial === 'design'
      ? 'design'

      : (
          initial === 'weak' ||
          initial === 'hard'
        )
        ? 'practice'

        : 'menu'
  );

  const [
    mode,
    setMode,
  ] = useState(
    initial === 'weak' ||
    initial === 'hard'
      ? initial
      : 'free'
  );

  const [
    selectedLesson,
    setSelectedLesson,
  ] = useState(null);

  const [
    question,
    setQuestion,
  ] = useState(null);

  const [
    result,
    setResult,
  ] = useState(null);

  const [
    excluded,
    setExcluded,
  ] = useState([]);

  const [
    summary,
    setSummary,
  ] = useState({
    total: 0,
    correct: 0,
  });

  const [
    loadingQuestion,
    setLoadingQuestion,
  ] = useState(false);

  /* 👑 موج P0 — جشن ارتقا (پیلود
     celebration پاسخ)؛ null = پنهان */
  const [
    celebration,
    setCelebration,
  ] = useState(null);

  const toast = useUIStore(
    (state) => state.toast
  );

  const queryClient =
    useQueryClient();


  const {
    data: lessons = [],
    isLoading: lessonsLoading,
    isError: lessonsError,
    refetch: refetchLessons,
  } = useQuery({
    queryKey: [
      'question-lessons',
    ],

    queryFn: () =>
      api
        .get(
          '/api/questions/lessons'
        )
        .then(
          (response) =>
            response.data
              ?.lessons || []
        ),

    staleTime:
      10 * 60 * 1000,
  });


  const fetchQuestion =
    useCallback(
      async (
        practiceMode,
        lesson,
        excludeList
      ) => {
        setLoadingQuestion(
          true
        );

        setQuestion(null);
        setResult(null);

        try {
          const exclude =
            excludeList.join(
              ','
            );

          let url;

          if (
            practiceMode ===
            'weak'
          ) {
            url =
              '/api/questions/weak';

          } else if (
            practiceMode ===
            'hard'
          ) {
            url =
              `/api/questions/hard?exclude=${exclude}`;

          } else {
            const lessonQuery =
              lesson
                ? `lesson=${
                    encodeURIComponent(
                      lesson
                    )
                  }&`
                : '';

            url =
              `/api/questions/practice?${lessonQuery}exclude=${exclude}`;
          }

          const response =
            await api.get(url);

          if (
            !response.data
              ?.question
          ) {
            toast(
              response.data
                ?.message ||
                'سؤال بیشتری موجود نیست 🎉',

              'info'
            );

            setView('menu');

            return;
          }

          setQuestion(
            response.data.question
          );

        } catch (error) {
          /* 🌊 W7 — قفل دسترسی فیچر: پی‌وال به‌جای تست */
          if (isSubscriptionLock(error)) {
            setLockErr(error);
            return;
          }

          toast(
            error?.response
              ?.data
              ?.detail ||
              'دریافت سؤال انجام نشد',

            'error'
          );

          setView('menu');

        } finally {
          setLoadingQuestion(
            false
          );
        }
      },

      [toast]
    );


  const answerMutation =
    useMutation({
      mutationFn: ({
        questionId,
        selected,
      }) =>
        api.post(
          '/api/questions/answer',

          {
            question_id:
              questionId,

            selected,
          }
        ),

      onSuccess: (
        response
      ) => {
        const answer =
          response.data;

        setResult(answer);

        setSummary(
          (current) => ({
            total:
              current.total + 1,

            correct:
              current.correct +
              (
                answer.is_correct
                  ? 1
                  : 0
              ),
          })
        );

        hapticNotif(
          answer.is_correct
            ? 'success'
            : 'error'
        );

        /* 👑 موج P0 — جشن ارتقا در صورت
           وجود + تازه‌سازی کش قهرمان */
        if (
          answer?.prestige
            ?.celebration
        ) {
          setCelebration(
            answer.prestige
              .celebration
          );
        }

        if (answer?.prestige) {
          queryClient
            .invalidateQueries({
              queryKey: ['prestige'],
            });

          queryClient
            .invalidateQueries({
              queryKey: ['dashboard'],
            });
        }
      },

      onError: () =>
        toast(
          'ثبت پاسخ انجام نشد',
          'error'
        ),
    });


  const start = (
    practiceMode,
    lesson = null
  ) => {
    haptic();

    setMode(
      practiceMode
    );

    setSelectedLesson(
      lesson
    );

    setExcluded([]);

    setSummary({
      total: 0,
      correct: 0,
    });

    setView('practice');

    fetchQuestion(
      practiceMode,
      lesson,
      []
    );
  };


  const next = () => {
    const nextExcluded =
      question
        ? [
            ...excluded,
            question.id,
          ]
        : excluded;

    setExcluded(
      nextExcluded
    );

    fetchQuestion(
      mode,
      selectedLesson,
      nextExcluded
    );
  };


  const [
    lockErr,
    setLockErr,
  ] = useState(null);


  const back = () => {
    setLockErr(null);
    setView('menu');
    setQuestion(null);
    setResult(null);
  };


  if (view === 'design') {
    return (
      <DesignQuestion
        onBack={back}
      />
    );
  }


  /* 🌊 W7 — پی‌وال بانک سؤال */
  if (lockErr) {
    return (
      <main className="page">
        <SubscriptionLock
          feature="بانک سؤال"
          featureKey="question_bank"
          mode={lockKind(lockErr).kind}
        />
      </main>
    );
  }


  const modeTitle =
    mode === 'weak'
      ? 'تمرین نقاط ضعف'

      : mode === 'hard'
        ? 'چالش سطح سخت'

        : selectedLesson ||
          'تمرین آزاد';


  return (
    <>
      <Header
        title={
          view === 'practice'
            ? modeTitle
            : 'بانک سؤال'
        }
        subtitle={
          view === 'practice'
            ? `${summary.correct} صحیح از ${summary.total}`
            : 'تمرین، چالش و طراحی سؤال'
        }
        onBack={
          view === 'practice'
            ? back
            : undefined
        }
      />

      <main className="page fade-up">
        {view === 'menu' ? (
          <>
            <section
              className={
                'card card-glow ' +
                'hero-card hero-card--purple'
              }
              style={{
                marginBottom: 'var(--sp-4)',
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
                  🧪
                </span>

                <div>
                  <b
                    style={{
                      fontSize: 'var(--fs-lg)',
                    }}
                  >
                    تمرین هوشمند و هدفمند
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
                    با تمرین مستمر، نقاط
                    ضعف را به تسلط تبدیل
                    کن.
                  </div>
                </div>
              </div>
            </section>


            <div
              style={{
                display:
                  'grid',

                gap:
                  9,

                marginBottom:
                  17,
              }}
            >
              <button
                className={
                  'card card-tap'
                }
                onClick={() =>
                  start('weak')
                }
                style={{
                  display:
                    'flex',

                  alignItems:
                    'center',

                  width:
                    '100%',

                  gap:
                    11,

                  textAlign:
                    'right',
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
                      'var(--soft-warn)',

                    fontSize:
                      21,
                  }}
                >
                  ⚡
                </span>

                <span
                  style={{
                    flex:
                      1,
                  }}
                >
                  <b>
                    تمرین نقاط ضعف
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
                    سؤال از مباحثی که
                    بیشتر اشتباه داشته‌اید
                  </span>
                </span>

                <span>←</span>
              </button>


              <button
                className={
                  'card card-tap'
                }
                onClick={() =>
                  start('hard')
                }
                style={{
                  display:
                    'flex',

                  alignItems:
                    'center',

                  width:
                    '100%',

                  gap:
                    11,

                  textAlign:
                    'right',
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
                      'var(--soft-err)',

                    fontSize:
                      21,
                  }}
                >
                  🔴
                </span>

                <span
                  style={{
                    flex:
                      1,
                  }}
                >
                  <b>
                    چالش سطح سخت
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
                    سؤال‌های دشوار برای
                    محک‌زدن تسلط شما
                  </span>
                </span>

                <span>←</span>
              </button>


              <button
                className={
                  'card card-tap'
                }
                onClick={() =>
                  navigate(
                    '/learn/exams'
                  )
                }
                style={{
                  display:
                    'flex',

                  alignItems:
                    'center',

                  width:
                    '100%',

                  gap:
                    11,

                  textAlign:
                    'right',
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
                      'var(--acc-soft)',

                    fontSize:
                      21,
                  }}
                >
                  📝
                </span>

                <span
                  style={{
                    flex:
                      1,
                  }}
                >
                  <b>
                    آزمون سفارشی
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
                    تعداد، مبحث و زمان دلخواه
                  </span>
                </span>

                <span>←</span>
              </button>
            </div>


            <div className="sec-title">
              تمرین آزاد براساس درس
            </div>

            {lessonsLoading ? (
              <SkTileGrid n={6} />
            ) : lessonsError && lessons.length === 0 ? (
              <button
                type="button"
                className="btn btn-full"
                onClick={() => refetchLessons()}
              >
                🌐 دریافت درس‌ها ناموفق بود — تلاش دوباره
              </button>
            ) : (
              <section className="grid2">
                {lessons.map(
                  (
                    item,
                    index
                  ) => (
                    <button
                      type="button"
                      key={item.name}
                      className={
                        'card card-tap pop-in'
                      }
                      onClick={() =>
                        start(
                          'free',
                          item.name
                        )
                      }
                      style={{
                        padding: 'var(--sp-4)',

                        textAlign:
                          'center',

                        animationDelay:
                          `${
                            index *
                            30
                          }ms`,
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

                          margin:
                            '0 auto 7px',

                          borderRadius: 'var(--r-md)',

                          background:
                            'var(--acc-soft)',

                          fontSize:
                            21,
                        }}
                      >
                        📖
                      </span>

                      <b
                        style={{
                          fontSize: 'var(--fs-meta)',
                        }}
                      >
                        {item.name}
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
                        {item.count ||
                          0}{' '}

                        سؤال
                      </div>
                    </button>
                  )
                )}
              </section>
            )}


            <div
              style={{
                display:
                  'flex',

                gap:
                  8,

                marginTop: 'var(--sp-4)',
              }}
            >
              <button
                className="btn btn-g"
                style={{
                  flex:
                    1,
                }}
                onClick={() =>
                  setView(
                    'design'
                  )
                }
              >
                ✍️ طراحی سؤال
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
                  navigate(
                    '/learn/my-questions'
                  )
                }
              >
                📋 سؤال‌های من
              </button>
            </div>
          </>
        ) : (
          <>
            {loadingQuestion ? (
              <div
                style={{
                  display:
                    'grid',

                  placeItems:
                    'center',

                  padding:
                    50,
                }}
              >
                <Spinner size={30} />
              </div>
            ) : (
              question && (
                <QuestionCard
                  question={question}
                  answered={result}
                  onAnswer={(
                    questionId,
                    selected
                  ) =>
                    answerMutation
                      .mutate({
                        questionId,
                        selected,
                      })
                  }
                  showReport={
                    Boolean(result)
                  }
                  onReport={() =>
                    navigate(
                      `/me/reports?type=question&id=${question.id}`
                    )
                  }
                />
              )
            )}

            {result && (
              <ResultBox
                result={result}
                onNext={next}
              />
            )}

            {summary.total > 0 && (
              <section
                className="card"
                style={{
                  display:
                    'grid',

                  gridTemplateColumns:
                    'repeat(3,1fr)',

                  gap:
                    8,

                  textAlign:
                    'center',
                }}
              >
                <div>
                  <b
                    style={{
                      color:
                        'var(--acc2)',
                    }}
                  >
                    {summary.total}
                  </b>

                  <div
                    style={{
                      color:
                        'var(--txm)',

                      fontSize: 'var(--fs-cap)',
                    }}
                  >
                    کل
                  </div>
                </div>

                <div>
                  <b
                    style={{
                      color:
                        'var(--ok)',
                    }}
                  >
                    {summary.correct}
                  </b>

                  <div
                    style={{
                      color:
                        'var(--txm)',

                      fontSize: 'var(--fs-cap)',
                    }}
                  >
                    صحیح
                  </div>
                </div>

                <div>
                  <b
                    style={{
                      color:
                        'var(--warn)',
                    }}
                  >
                    {summary.total
                      ? Math.round(
                          (
                            summary.correct /
                            summary.total
                          ) * 100
                        )
                      : 0}
                    ٪
                  </b>

                  <div
                    style={{
                      color:
                        'var(--txm)',

                      fontSize: 'var(--fs-cap)',
                    }}
                  >
                    درصد
                  </div>
                </div>
              </section>
            )}
          </>
        )}
      </main>

      {/* 👑 موج P0 — جشن ارتقا روی
          همه‌ی ویوهای این صفحه */}
      {celebration && (
        <CelebrationOverlay
          celebration={celebration}
          onClose={() =>
            setCelebration(null)
          }
        />
      )}
    </>
  );
}
