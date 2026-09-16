import { confirmAction } from '../../lib/confirm';
import {
  useEffect,
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
  ExamHistorySkeleton,
} from '../../components/shared/skeletons';

import {
  haptic,
  hapticNotif,
} from '../../lib/telegram';

import {
  useUIStore,
} from '../../stores/uiStore';


const clock = (seconds) => {
  if (seconds == null) {
    return '∞';
  }

  const safe = Math.max(
    0,
    Number(seconds) || 0
  );

  const minutes = Math.floor(
    safe / 60
  );

  const remaining =
    safe % 60;

  return (
    `${String(minutes).padStart(
      2,
      '0'
    )}:` +
    `${String(remaining).padStart(
      2,
      '0'
    )}`
  );
};


const STATUS = {
  active: [
    'در حال انجام',
    'b-yel',
    '▶️',
  ],

  finished: [
    'تمام‌شده',
    'b-grn',
    '✅',
  ],

  expired: [
    'زمان تمام‌شده',
    'b-red',
    '⏱',
  ],

  abandoned: [
    'رهاشده',
    'b-gray',
    '⏹',
  ],
};


export default function ExamCenter() {
  const [
    view,
    setView,
  ] = useState('setup');

  const [
    config,
    setConfig,
  ] = useState({
    lesson: '',
    topic: 'همه',
    count: 10,
    minutes: 20,
  });

  const [outputMode, setOutputMode] =
    useState('app');

  const [
    session,
    setSession,
  ] = useState(null);

  const [
    question,
    setQuestion,
  ] = useState(null);

  const [
    answer,
    setAnswer,
  ] = useState(null);

  const [
    result,
    setResult,
  ] = useState(null);

  const [
    progress,
    setProgress,
  ] = useState(0);

  const [
    secondsLeft,
    setSecondsLeft,
  ] = useState(null);

  /* 👑 موج P0 — جشن ارتقا (پیلود
     celebration آزمون/پاسخ) */
  const [
    celebration,
    setCelebration,
  ] = useState(null);

  /* ⚔️ موج P1 — جریان چالش ارتقا (?promo=1):
     promoInfo = وضعیت چالش از سرور،
     promoResult = نتیجه‌ی سرورمحور پایان */
  const [searchParams] =
    useSearchParams();

  const [
    promoInfo,
    setPromoInfo,
  ] = useState(null);

  const [
    promoResult,
    setPromoResult,
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


  const {
    data: topics = [],
  } = useQuery({
    queryKey: [
      'question-topics',
      config.lesson,
    ],

    queryFn: () =>
      api
        .get(
          `/api/questions/topics/${
            encodeURIComponent(
              config.lesson
            )
          }`
        )
        .then(
          (response) =>
            response.data
              ?.topics || []
        ),

    enabled:
      Boolean(config.lesson),

    staleTime:
      10 * 60 * 1000,
  });


  const {
    data: history = [],
    isLoading: historyLoading,
    isError: historyError,
    error: historyErr,
    refetch: refetchHistory,
  } = useQuery({
    queryKey: [
      'exam-history',
    ],

    queryFn: () =>
      api
        .get(
          '/api/questions/custom-exam/history'
        )
        .then(
          (response) =>
            response.data
              ?.exams || []
        ),

    enabled:
      view === 'history',
  });


  const refreshHistory = () =>
    queryClient.invalidateQueries({
      queryKey: [
        'exam-history',
      ],
    });

  const downloadPdf = async (sid, mode) => {
    try {
      const res = await api.get(
        `/api/questions/custom-exam/${sid}/pdf?mode=${mode}`,
        { responseType: 'blob' }
      );
      const blob = res.data;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `humsyar-exam-${String(sid).slice(0, 8)}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast('PDF آماده شد — دانلود شروع شد 📄', 'success');
      haptic('medium');
    } catch (e) {
      toast(
        e?.response?.data?.detail || 'دانلود PDF انجام نشد',
        'error'
      );
    }
  };


  const loadNext = async (
    sessionId
  ) => {
    setQuestion(null);
    setAnswer(null);

    try {
      const response =
        await api.get(
          `/api/questions/custom-exam/${sessionId}/next`
        );

      if (
        response.data.finished
      ) {
        setResult(
          response.data
        );

        setView('result');

        await refreshHistory();

        return;
      }

      setQuestion(
        response.data.question
      );

      setProgress(
        response.data.progress ||
        0
      );

      setSecondsLeft(
        response.data
          .seconds_left ?? null
      );

      setView('active');

    } catch (error) {
      toast(
        error?.response
          ?.data
          ?.detail ||
          'دریافت آزمون انجام نشد',

        'error'
      );

      setView('history');
    }
  };


  const startMutation =
    useMutation({
      mutationFn: () =>
        api.post(
          '/api/questions/custom-exam/start',

          {
            lesson:
              config.lesson,

            topic:
              config.topic ===
              'همه'
                ? null
                : config.topic,

            count:
              Number(
                config.count
              ),

            minutes:
              Number(
                config.minutes
              ),

            output_mode: outputMode,
          }
        ),

      onSuccess: async (
        response
      ) => {
        const data = response.data || {};
        // PDF mode: directly download
        if (String(outputMode).startsWith('pdf')) {
          const mode = outputMode === 'pdf_practice' ? 'practice' : 'exam';
          toast('⏳ در حال ساخت PDF...', 'info');
          await downloadPdf(data.session_id, mode);
          await refreshHistory();
          setView('history');
          return;
        }
        setSession(data);
        setResult(null);
        await loadNext(data.session_id);
      },

      onError: (error) =>
        toast(
          error?.response
            ?.data
            ?.detail ||
            'ساخت آزمون انجام نشد',

          'error'
        ),
    });


  const answerMutation =
    useMutation({
      mutationFn: ({
        selected,
      }) =>
        api.post(
          `/api/questions/custom-exam/${session.session_id}/answer`,

          {
            selected,
          }
        ),

      onSuccess: (
        response
      ) => {
        setAnswer(
          response.data
        );

        hapticNotif(
          response.data
            .is_correct
            ? 'success'
            : 'error'
        );

        /* ⚔️ موج P1 — نتیجه‌ی چالش در پاسخ
           پایانی: جشن برد یا کارت آرام شکست */
        const promoRes =
          response.data
            ?.promotion_result;

        if (promoRes) {
          setPromoResult(promoRes);

          if (promoRes.celebration) {
            setCelebration(
              promoRes.celebration
            );
          }

          queryClient
            .invalidateQueries({
              queryKey: ['prestige'],
            });
        }

        /* 👑 موج P0 — جشن ارتقا: اولویت
           با رویداد تکمیل آزمون (جشن کلان‌تر)
           وگرنه جشن خودِ پاسخ */
        const prestigeCelebration =
          promoRes?.celebration ||
          response.data?.prestige_exam
            ?.celebration ||
          response.data?.prestige
            ?.celebration;

        if (prestigeCelebration) {
          setCelebration(
            prestigeCelebration
          );
        }

        if (
          response.data?.prestige ||
          response.data?.prestige_exam ||
          promoRes
        ) {
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

      onError: (error) => {
        /* ⚔️ TTL چالش: 409 با detail شی —
           Fail خودکار + کول‌داون */
        const detail =
          error?.response?.data?.detail;

        if (
          detail &&
          typeof detail === 'object' &&
          detail.code === 'promotion_failed_ttl'
        ) {
          setPromoResult({
            win: false,
            pct: detail.pct,
            cooldown_h:
              detail.cooldown_h,
            ttl: true,
          });

          setSession(null);
          setQuestion(null);
          setView('result');

          return;
        }

        toast(
          typeof detail === 'string'
            ? detail
            : 'ثبت پاسخ انجام نشد',

          'error'
        );
      },
    });


  const abandonMutation =
    useMutation({
      mutationFn: () =>
        api.delete(
          `/api/questions/custom-exam/${session.session_id}`
        ),

      onSuccess: async (response) => {
        /* ⚔️ رهاسازی چالش = Fail سروری */
        const pr =
          response?.data
            ?.promotion_result;

        if (pr) {
          setPromoResult(pr);
          setSession(null);
          setQuestion(null);
          setView('result');

          queryClient
            .invalidateQueries({
              queryKey: ['prestige'],
            });

          return;
        }

        setSession(null);
        setQuestion(null);
        setView('history');

        await refreshHistory();
      },
    });

  /* ⚔️ موج P1 — بوت جریان چالش با ?promo=1 */
  useEffect(() => {
    if (
      searchParams.get('promo') !== '1'
    ) {
      return undefined;
    }

    let alive = true;

    (async () => {
      try {
        const resp = await api.get(
          '/api/profile/prestige'
        );

        if (!alive) {
          return;
        }

        const ch =
          resp.data?.prestige
            ?.challenge || null;

        setPromoInfo(
          ch || { mode: 'none' }
        );

        if (
          ch &&
          ['ready', 'cooldown', 'locked']
            .includes(ch.mode)
        ) {
          setResult(null);
          setPromoResult(null);
          setView('promo');
        }
      } catch (err) {
        /* سکوت — مرکز آزمون معمول می‌ماند */
      }
    })();

    return () => {
      alive = false;
    };
  }, []);

  const promoMutation =
    useMutation({
      mutationFn: () =>
        api.post(
          '/api/questions/custom-exam/start',
          {
            lesson: 'چالش',
            count: 5,
            minutes: 0,
            promotion: true,
          }
        ),

      onSuccess: async (response) => {
        const data =
          response.data || {};

        setSession({
          ...data,
          promotion: true,
        });

        setResult(null);
        setPromoResult(null);

        await loadNext(
          data.session_id
        );
      },

      onError: (error) => {
        const d =
          error?.response?.data?.detail;

        if (d && typeof d === 'object') {
          if (d.code === 'cooldown') {
            setPromoInfo((prev) => ({
              ...(prev || {}),
              mode: 'cooldown',
              cooldown_until:
                d.cooldown_until,
              hours_left: d.hours_left,
            }));

            setView('promo');

            return;
          }

          if (
            d.code === 'insufficient_pool'
          ) {
            toast(
              'بانک سؤال فعلاً برای چالش کافی نیست',
              'error'
            );

            return;
          }
        }

        toast(
          typeof d === 'string'
            ? d
            : 'شروع چالش انجام نشد',
          'error'
        );
      },
    });


  useEffect(() => {
    if (
      view !== 'active' ||
      secondsLeft == null
    ) {
      return undefined;
    }

    if (secondsLeft <= 0) {
      if (
        session?.session_id
      ) {
        loadNext(
          session.session_id
        );
      }

      return undefined;
    }

    const timer =
      window.setTimeout(
        () => {
          setSecondsLeft(
            (current) =>
              Math.max(
                0,
                (
                  current || 0
                ) - 1
              )
          );
        },

        1000
      );

    return () =>
      window.clearTimeout(
        timer
      );

  }, [
    view,
    session?.session_id,
    secondsLeft,
  ]);


  const resume = async (
    item
  ) => {
    setSession({
      session_id:
        item.session_id,

      total:
        item.total,

      minutes:
        item.minutes,
    });

    setResult(null);

    await loadNext(
      item.session_id
    );
  };


  if (view === 'active') {
    const total =
      Number(
        session?.total
      ) || 0;

    const examProgress =
      total
        ? Math.min(
            100,

            Math.round(
              (
                progress /
                total
              ) * 100
            )
          )
        : 0;

    return (
      <>
        <Header
          title="آزمون در حال اجرا"
          subtitle={`${
            config.lesson ||
            'آزمون سفارشی'
          } • سؤال ${
            progress
          } از ${
            total || '—'
          }`}
          onBack={() =>
            setView('history')
          }
        />

        <main className="page fade-up">
          <section
            className={
              'card card-glow hero-card'
            }
            style={{
              marginBottom:
                12,

              padding:
                13,
            }}
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
              <span className="badge b-acc">
                سؤال {progress}/
                {total || '—'}
              </span>

              <div
                className="pbar"
                style={{
                  flex:
                    1,
                }}
              >
                <div
                  className="pbar-f"
                  style={{
                    width:
                      `${examProgress}%`,
                  }}
                />
              </div>

              <span
                className={`badge ${
                  secondsLeft !=
                    null &&
                  secondsLeft < 60
                    ? 'b-red'
                    : 'b-yel'
                }`}
              >
                ⏱{' '}

                {clock(
                  secondsLeft
                )}
              </span>
            </div>
          </section>


          {!question ? (
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
            <>
              <QuestionCard
                question={question}
                answered={answer}
                onAnswer={(
                  _,
                  selected
                ) =>
                  answerMutation
                    .mutate({
                      selected,
                    })
                }
                showReport={false}
              />

              {answer && (
                <section
                  className={
                    'card pop-in'
                  }
                  style={{
                    borderColor:
                      answer.is_correct
                        ? 'var(--bd-ok)'
                        : 'var(--bd-err)',
                  }}
                >
                  <div
                    style={{
                      color:
                        answer.is_correct
                          ? 'var(--ok)'
                          : 'var(--err)',

                      fontSize: 'var(--fs-lg)',

                      fontWeight:
                        900,
                    }}
                  >
                    {answer.is_correct
                      ? '✅ پاسخ صحیح؛ آفرین!'
                      : '❌ پاسخ نادرست'}
                  </div>

                  {/* 👑 موج P0 — XP کسب‌شده
                      (پاسخ + تکمیل آزمون) */}
                  {(() => {
                    const xpTotal =
                      (Number(
                        answer.prestige
                          ?.xp_gained
                      ) || 0) +
                      (Number(
                        answer.prestige_exam
                          ?.xp_gained
                      ) || 0);

                    const display =
                      answer.prestige_exam
                        ?.display ||
                      answer.prestige
                        ?.display;

                    return xpTotal > 0 ||
                      display?.title ? (
                      <div
                        style={{
                          display: 'flex',
                          flexWrap: 'wrap',
                          alignItems:
                            'center',
                          gap: 6,
                          marginTop: 'var(--sp-2)',

                          color:
                            'var(--tx2)',
                          fontSize: 'var(--fs-cap)',
                          fontWeight: 700,
                        }}
                      >
                        {xpTotal > 0 && (
                          <span
                            style={{
                              color:
                                'var(--warn)',
                            }}
                          >
                            ⚡ +{xpTotal}{' '}
                            XP
                          </span>
                        )}

                        {display?.title && (
                          <span>
                            {display.icon}{' '}
                            {display.title}{' '}
                            {display.stars}
                          </span>
                        )}
                      </div>
                    ) : null;
                  })()}

                  {answer.explanation && (
                    <div
                      style={{
                        marginTop:
                          9,

                        color:
                          'var(--tx2)',

                        fontSize: 'var(--fs-meta)',

                        lineHeight:
                          1.9,
                      }}
                    >
                      {
                        answer.explanation
                      }
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
                    onClick={() =>
                      loadNext(
                        session.session_id
                      )
                    }
                  >
                    {answer.finished
                      ? 'مشاهده نتیجه'
                      : 'سؤال بعدی ←'}
                  </button>
                </section>
              )}
            </>
          )}


          <button
            className={
              'btn btn-d btn-full'
            }
            style={{
              marginTop:
                12,
            }}
            disabled={
              abandonMutation
                .isPending
            }
            onClick={async () => {
              const accepted =
                await confirmAction(
                  'آزمون رها شود؟'
                );

              if (accepted) {
                abandonMutation
                  .mutate();
              }
            }}
          >
            رهاکردن آزمون
          </button>
        </main>

        {/* 👑 موج P0 — جشن ارتقا روی
            کارت نتیجه‌ی آزمون */}
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


  /* ⚔️ موج P1 — کارت معارفه/قفل چالش ارتقا */
  if (view === 'promo') {
    const ch = promoInfo || {};

    const mode =
      ch.mode || 'ready';

    const hoursLeft =
      ch.hours_left ??
      (ch.cooldown_until
        ? Math.max(
            1,
            Math.ceil(
              (new Date(
                ch.cooldown_until
              ).getTime() -
                Date.now()) /
                36e5
            )
          )
        : null);

    return (
      <>
        <Header
          title="چالش ارتقا"
          onBack={() =>
            setView('setup')
          }
        />

        <main className="page fade-up">
          <section
            className={
              'card card-glow hero-card'
            }
            style={{
              padding: 25,
              textAlign: 'center',
            }}
          >
            <div
              style={{ fontSize: 53 }}
            >
              {ch.icon || '⚔️'}
            </div>

            <h2
              style={{
                margin: '8px 0 4px',
                fontSize: 'var(--fs-xl)',
              }}
            >
              {mode === 'ready'
                ? `چالش ارتقا به ${
                    ch.title || 'رنک بعدی'
                  }`
                : mode === 'cooldown'
                  ? 'چالش در کول‌داون است'
                  : mode === 'locked'
                    ? 'چالش Apex قفل است'
                    : 'چالش ارتقا'}
            </h2>

            {mode === 'ready' && (
              <>
                <p
                  style={{
                    color: 'var(--txm)',
                    fontSize: 'var(--fs-meta)',
                    lineHeight: 2,
                  }}
                >
                  {ch.apex
                    ? 'باس‌فایت نهایی: ۳۰ سؤال، قبولی با ۹۰٪ — افسانه‌ای شو 🌌'
                    : '۲۰ سؤال ترکیبی از سراسر بانک · قبولی با ۸۰٪ · مهلت ۲۴ ساعت'}
                </p>

                <button
                  type="button"
                  className={
                    'btn btn-p btn-full'
                  }
                  style={{ marginTop: 16 }}
                  disabled={
                    promoMutation.isPending
                  }
                  onClick={() => {
                    haptic();
                    promoMutation.mutate();
                  }}
                >
                  {promoMutation.isPending
                    ? 'در حال ساخت چالش…'
                    : `⚔️ شروع چالش${
                        ch.apex ? ' Apex' : ''
                      }`}
                </button>
              </>
            )}

            {mode === 'cooldown' && (
              <p
                style={{
                  color: 'var(--txm)',
                  fontSize: 'var(--fs-meta)',
                  lineHeight: 2,
                }}
              >
                ⏳{' '}
                {hoursLeft != null
                  ? `حدود ${hoursLeft} ساعت دیگر`
                  : 'کمی بعد'}{' '}
                می‌توانی دوباره تلاش کنی. هیچ
                XP‌ای از دست نرفته است 💪
              </p>
            )}

            {mode === 'locked' && (
              <p
                style={{
                  color: 'var(--txm)',
                  fontSize: 'var(--fs-meta)',
                  lineHeight: 2,
                }}
              >
                🔒 پیش‌شرط‌ها: بهترین استریک ≥{' '}
                {ch?.need?.streak_best ?? '—'}{' '}
                روز (الان:{' '}
                {ch?.have?.streak_best ?? 0})
                {' · '}
                {ch?.need?.contrib ?? '—'}{' '}
                مشارکت تأییدشده (الان:{' '}
                {ch?.have?.contrib ?? 0})
              </p>
            )}

            <button
              type="button"
              className={
                'btn btn-g btn-full'
              }
              style={{ marginTop: 'var(--sp-3)' }}
              onClick={() =>
                setView('setup')
              }
            >
              بازگشت به مرکز آزمون
            </button>
          </section>
        </main>
      </>
    );
  }

  /* ⚔️ موج P1 — نتیجه‌ی چالش (برد جشن‌دار /
     شکست آرام — بدون احساس جریمه) */
  if (
    view === 'result' &&
    promoResult
  ) {
    const won = Boolean(promoResult.win);

    return (
      <>
        <Header
          title={
            won
              ? '🎉 ارتقا رسمی شد'
              : 'نتیجه چالش'
          }
          onBack={() => {
            setPromoResult(null);
            setView('history');
          }}
        />

        <main className="page fade-up">
          <section
            className={
              'card card-glow hero-card'
            }
            style={{
              padding: 25,
              textAlign: 'center',
            }}
          >
            <div
              style={{ fontSize: 53 }}
            >
              {won ? '🏆' : '💪'}
            </div>

            <div
              style={{
                color: won
                  ? 'var(--ok)'
                  : 'var(--warn)',
                fontSize: 32,
                fontWeight: 900,
                marginTop: 8,
              }}
            >
              {promoResult.pct ?? 0}٪
            </div>

            <h3
              style={{
                fontSize: 'var(--fs-lg)',
                margin: '6px 0',
              }}
            >
              {won
                ? `چالش را بردی — ${
                    promoInfo?.title ||
                    'رنک جدید'
                  } رسمی شد!`
                : 'این بار نشد — نزدیک بود'}
            </h3>

            <p
              style={{
                color: 'var(--txm)',
                fontSize: 'var(--fs-meta)',
                lineHeight: 2,
              }}
            >
              {won
                ? `${
                    promoResult.reward || 0
                  }+ XP جایزه‌ی چالش · سپر ارتقا فعال شد 🛡`
                : promoResult.ttl
                  ? `مهلت ۲۴ ساعته تمام شد. XP‌ات محفوظ است — ${
                      promoResult.cooldown_h ??
                      12
                    } ساعت دیگر دوباره.`
                  : `حد قبولی ${
                      promoResult.pass_pct ??
                      80
                    }٪ بود. XP‌ات محفوظ است — ${
                      promoResult.cooldown_h ??
                      12
                    } ساعت دیگر دوباره.`}
            </p>

            <button
              type="button"
              className={
                'btn btn-p btn-full'
              }
              style={{ marginTop: 17 }}
              onClick={() => {
                setPromoResult(null);
                setView('history');
              }}
            >
              {won ? 'ادامه' : 'بازگشت'}
            </button>
          </section>
        </main>

        {/* ⚔️ موج P1 — جشن ارتقای رنک روی
            نتیجه‌ی چالش (هم‌پوشانی با نمای
            فعال — تا از دست نرود) */}
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

  if (view === 'result') {
    const score =
      Number(
        result?.percentage
      ) || 0;

    return (
      <>
        <Header
          title="نتیجه آزمون"
          onBack={() =>
            setView('history')
          }
        />

        <main className="page fade-up">
          <section
            className={
              'card card-glow hero-card'
            }
            style={{
              padding:
                25,

              textAlign:
                'center',
            }}
          >
            <div
              style={{
                fontSize:
                  53,
              }}
            >
              {score >= 70
                ? '🏆'
                : score >= 40
                  ? '💪'
                  : '📚'}
            </div>

            <div
              style={{
                color:
                  score >= 70
                    ? 'var(--ok)'
                    : score >= 40
                      ? 'var(--warn)'
                      : 'var(--err)',

                fontSize:
                  32,

                fontWeight:
                  900,

                marginTop:
                  8,
              }}
            >
              {score}٪
            </div>

            <div
              style={{
                color:
                  'var(--txm)',

                fontSize: 'var(--fs-cap)',
              }}
            >
              نتیجه نهایی آزمون
            </div>

            <div
              className="grid2"
              style={{
                marginTop:
                  18,
              }}
            >
              <div className="card">
                <b
                  style={{
                    color:
                      'var(--ok)',

                    fontSize: 'var(--fs-xl)',
                  }}
                >
                  {result?.correct ||
                    0}
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

              <div className="card">
                <b
                  style={{
                    color:
                      'var(--err)',

                    fontSize: 'var(--fs-xl)',
                  }}
                >
                  {Math.max(
                    0,

                    (
                      result
                        ?.answered ||
                      0
                    ) -
                    (
                      result
                        ?.correct ||
                      0
                    )
                  )}
                </b>

                <div
                  style={{
                    color:
                      'var(--txm)',

                    fontSize: 'var(--fs-cap)',
                  }}
                >
                  اشتباه
                </div>
              </div>
            </div>

            <button
              className={
                'btn btn-p btn-full'
              }
              style={{
                marginTop:
                  17,
              }}
              onClick={() =>
                setView(
                  'history'
                )
              }
            >
              تاریخچه آزمون‌ها
            </button>
          </section>
        </main>

        {/* 👑 موج P0 — جشن ارتقا روی نتیجه‌ی
            آزمون (تکمیل آزمون ممکن است خودش
            چالش‌زننده‌ی رنک باشد) */}
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


  if (view === 'history') {
    const rows =
      Array.isArray(history)
        ? history
        : [];

    return (
      <>
        <Header
          title="تاریخچه آزمون‌ها"
          onBack={() =>
            setView('setup')
          }
        />

        <main className="page fade-up">
          <button
            className={
              'btn btn-p btn-full'
            }
            style={{
              marginBottom: 'var(--sp-4)',
            }}
            onClick={() =>
              setView('setup')
            }
          >
            ＋ آزمون جدید
          </button>

          {historyLoading ? (
            <ExamHistorySkeleton />
          ) : historyError ? (
            isSubscriptionLock(historyErr) ? (
              <SubscriptionLock
                feature="آزمون‌ها"
                featureKey="mock_exam"
                mode={lockKind(historyErr).kind}
              />
            ) : (
              <PageError
                text="دریافت تاریخچه انجام نشد."
                onRetry={() => refetchHistory()}
              />
            )
          ) : rows.length === 0 ? (
            <EmptyState icon="📝">
              هنوز آزمونی ثبت نشده است.
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
              {rows.map(
                (item) => {
                  const [
                    label,
                    badge,
                    icon,
                  ] = (
                    STATUS[
                      item.status
                    ] || [
                      item.status,

                      'b-gray',

                      '📌',
                    ]
                  );

                  return (
                    <article
                      key={
                        item.session_id
                      }
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
                              'var(--acc-soft)',

                            fontSize: 'var(--fs-xl)',
                          }}
                        >
                          {icon}
                        </span>

                        <div
                          style={{
                            flex:
                              1,
                          }}
                        >
                          <b
                            style={{
                              fontSize: 'var(--fs-sm)',
                            }}
                          >
                            {item.lesson ||
                              'آزمون سفارشی'}
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
                            {item.topic ||
                              'همه مباحث'}

                            {' • '}

                            {item.answered ||
                              0}
                            /
                            {item.total ||
                              0}{' '}

                            پاسخ
                          </div>
                        </div>

                        <span
                          className={`badge ${badge}`}
                        >
                          {item.status ===
                          'active'
                            ? label
                            : `${item.percentage || 0}٪`}
                        </span>
                      </div>

                      {item.status ===
                        'active' && (
                        <button
                          className={
                            'btn btn-p btn-full'
                          }
                          style={{
                            marginTop: 'var(--sp-3)',
                          }}
                          onClick={() =>
                            resume(item)
                          }
                        >
                          ▶️ ادامه آزمون
                        </button>
                      )}

                      {String(item.output_mode || '').startsWith('pdf') && (
                        <button
                          className={
                            'btn btn-dark btn-full'
                          }
                          style={{
                            marginTop: 8,
                          }}
                          onClick={() =>
                            downloadPdf(
                              item.session_id,
                              item.output_mode === 'pdf_practice'
                                ? 'practice'
                                : 'exam'
                            )
                          }
                        >
                          📄 دانلود PDF
                        </button>
                      )}

                      {String(item.output_mode || '').startsWith('pdf') && item.status !== 'active' && (
                        <div
                          style={{
                            marginTop: 6,
                            fontSize: 'var(--fs-cap)',
                            color: 'var(--txm)',
                            textAlign: 'center',
                          }}
                        >
                          {item.output_mode === 'pdf_practice'
                            ? '📄 PDF تمرینی — پاسخ زیر هر سوال'
                            : '📝 PDF آزمونی — پاسخنامه در انتها'}
                        </div>
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


  return (
    <>
      <Header
        title="مرکز آزمون"
        subtitle={
          'آزمون شخصی‌سازی‌شده و ماندگار'
        }
      />

      <main className="page fade-up">
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
                  54,

                height:
                  54,

                placeItems:
                  'center',

                borderRadius:
                  17,

                background:
                  'linear-gradient(135deg,var(--pur-dim),var(--acc))',

                fontSize:
                  26,
              }}
            >
              🧪
            </span>

            <div>
              <b
                style={{
                  fontSize: 'var(--fs-xl)',
                }}
              >
                آزمون خودت رو بساز
              </b>

              <div
                style={{
                  color:
                    'var(--txm)',

                  fontSize: 'var(--fs-cap)',

                  lineHeight:
                    1.6,

                  marginTop:
                    3,
                }}
              >
                درس، مبحث، تعداد سؤال و
                زمان را خودت انتخاب کن.
              </div>
            </div>
          </div>
        </section>


        <button
          className={
            'btn btn-dark btn-full'
          }
          style={{
            marginBottom: 'var(--sp-4)',
          }}
          onClick={() =>
            setView('history')
          }
        >
          🕘 تاریخچه و ادامه آزمون
        </button>


        <section
          className="card"
          style={{
            display:
              'grid',

            gap: 'var(--sp-3)',
          }}
        >
          <label className="fld-label">
            درس
          </label>

          {lessonsLoading ? (
            <div
              className="skeleton"
              style={{
                width: '100%',
                height: 42,
                borderRadius: 'var(--r-md)',
              }}
            />
          ) : (
            <select
              className="inp"
              value={
                config.lesson
              }
              onChange={(event) =>
                setConfig({
                  ...config,

                  lesson:
                    event.target
                      .value,

                  topic:
                    'همه',
                })
              }
            >
              <option value="">
                انتخاب درس
              </option>

              {lessonsError && lessons.length === 0 && (
                <option value="" disabled>
                  🌐 دریافت درس‌ها ناموفق بود
                </option>
              )}

              {lessons.map(
                (item) => (
                  <option
                    key={item.name}
                    value={item.name}
                  >
                    {item.name} (
                    {item.count})
                  </option>
                )
              )}
            </select>
          )}

          {/* 🌊 W8/UX-02 */}
          {lessonsError && lessons.length === 0 && (
            <button
              type="button"
              className="btn sm"
              style={{ marginTop: 6 }}
              onClick={() => refetchLessons()}
            >
              تلاش دوباره برای درس‌ها
            </button>
          )}

          <label className="fld-label">
            مبحث
          </label>

          <select
            className="inp"
            value={
              config.topic
            }
            disabled={
              !config.lesson
            }
            onChange={(event) =>
              setConfig({
                ...config,

                topic:
                  event.target
                    .value,
              })
            }
          >
            <option value="همه">
              همه مباحث
            </option>

            {topics.map(
              (item) => (
                <option
                  key={item.name}
                  value={item.name}
                >
                  {item.name} (
                  {item.count})
                </option>
              )
            )}
          </select>

          <div className="grid2">
            <div>
              <label className="fld-label">
                تعداد سؤال
              </label>

              <select
                className="inp"
                value={
                  config.count
                }
                onChange={(event) =>
                  setConfig({
                    ...config,

                    count:
                      Number(
                        event.target
                          .value
                      ),
                  })
                }
              >
                {[
                  5,
                  10,
                  15,
                  20,
                  30,
                  40,
                ].map(
                  (value) => (
                    <option
                      key={value}
                      value={value}
                    >
                      {value} سؤال
                    </option>
                  )
                )}
              </select>
            </div>

            <div>
              <label className="fld-label">
                زمان
              </label>

              <select
                className="inp"
                value={
                  config.minutes
                }
                onChange={(event) =>
                  setConfig({
                    ...config,

                    minutes:
                      Number(
                        event.target
                          .value
                      ),
                  })
                }
              >
                <option value={0}>
                  بدون محدودیت
                </option>

                {[
                  10,
                  20,
                  30,
                  60,
                  90,
                ].map(
                  (value) => (
                    <option
                      key={value}
                      value={value}
                    >
                      {value} دقیقه
                    </option>
                  )
                )}
              </select>
            </div>
          </div>

          <label className="fld-label">نوع خروجی</label>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr 1fr',
              gap: 8,
            }}
          >
            {[
              { id: 'app', icon: '🤖', label: 'داخل اپ', desc: 'تعاملی' },
              { id: 'pdf_practice', icon: '📄', label: 'PDF تمرینی', desc: 'پاسخ زیر سوال' },
              { id: 'pdf_exam', icon: '📝', label: 'PDF آزمونی', desc: 'پاسخنامه جدا' },
            ].map((m) => (
              <button
                key={m.id}
                type="button"
                className={`card ${outputMode === m.id ? 'card-glow' : ''}`}
                onClick={() => setOutputMode(m.id)}
                style={{
                  padding: '10px 6px',
                  textAlign: 'center',
                  border:
                    outputMode === m.id
                      ? '1.5px solid var(--acc)'
                      : '1px solid var(--bd)',
                  background:
                    outputMode === m.id ? 'var(--acc-soft)' : 'var(--surf-card)',
                  cursor: 'pointer',
                }}
              >
                <div style={{ fontSize: 18 }}>{m.icon}</div>
                <div
                  style={{
                    fontSize: 'var(--fs-cap)',
                    fontWeight: 700,
                    marginTop: 4,
                    color: outputMode === m.id ? 'var(--acc)' : 'var(--tx)',
                  }}
                >
                  {m.label}
                </div>
                <div
                  style={{
                    fontSize: 10,
                    color: 'var(--txm)',
                    marginTop: 2,
                  }}
                >
                  {m.desc}
                </div>
              </button>
            ))}
          </div>

          {String(outputMode).startsWith('pdf') && (
            <div
              className="card"
              style={{
                background: 'var(--soft-acc)',
                border: '1px solid var(--bd-acc)',
                padding: 10,
                fontSize: 'var(--fs-cap)',
                color: 'var(--txm)',
                lineHeight: 1.6,
              }}
            >
              {outputMode === 'pdf_practice'
                ? '📄 PDF تمرینی: هر سوال با پاسخ و تحلیل بلافاصله زیر آن — مناسب تمرین و مرور.'
                : '📝 PDF آزمونی: سوالات بدون پاسخ + پاسخنامه جداگانه در پایان — مناسب چاپ و برگزاری آزمون.'}
            </div>
          )}
        </section>

        <button
          className={
            'btn btn-p btn-full'
          }
          style={{
            marginTop:
              13,
          }}
          disabled={
            !config.lesson ||
            startMutation.isPending
          }
          onClick={() => {
            haptic('medium');

            startMutation.mutate();
          }}
        >
          {startMutation.isPending ? (
            <Spinner size={16} />
          ) : (
            '🚀 شروع آزمون'
          )}
        </button>
      </main>
    </>
  );
}
