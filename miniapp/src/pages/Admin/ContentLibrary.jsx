import EmptyState from '../../components/shared/EmptyState';

import { number, errorText } from '../../lib/format';

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
  useContentScope,
} from '../../hooks/useContentScope';

import {
  useNavigate,
} from 'react-router-dom';

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











/* 🌊 موج C1 — گیت انتخاب ورودی برای ادمین ارشد:
   مدیریت محتوا فقط در متن یک ورودی معتبر انجام می‌شود */
function ContentScopeGate() {
  const navigate = useNavigate();

  return (
    <>
      <Header
        title="مدیریت محتوا"
        subtitle="انتخاب ورودی"
      />

      <main className="page fade-up">
        <div className="empty card">
          برای مدیریت محتوا ابتدا ورودی
          را انتخاب کنید.

          <button
            type="button"
            className="btn btn-p"
            style={{ marginTop: 12 }}
            onClick={() =>
              navigate('/admin/content')
            }
          >
            📅 انتخاب ورودی
          </button>
        </div>
      </main>
    </>
  );
}


/* 🌊 C1 — بنر کوچک «ورودی فعلی» بالای ابزارها */
function ContentScopeBanner({
  scope,
}) {
  return (
    <div
      className="card"
      style={{
        display: 'flex',

        alignItems: 'center',

        gap: 8,

        padding: 10,

        marginBottom: 12,
      }}
    >
      <span>📅</span>

      <span
        style={{
          color: 'var(--txm)',

          fontSize: 'var(--fs-cap)',
        }}
      >
        {scope.isScoped
          ? 'ورودی تحت مدیریت:'
          : 'ورودی فعلی:'}
      </span>

      <b>{scope.label}</b>
    </div>
  );
}


function DeleteButton({
  pending,
  onClick,
}) {
  return (
    <button
      type="button"
      className="btn btn-d"
      style={{
        minHeight: 33,
        padding: '5px 9px',
      }}
      disabled={pending}
      onClick={onClick}
    >
      🗑
    </button>
  );
}


/* مدیریت علوم پایه */

export function BasicScienceAdmin() {
  const [
    term,
    setTerm,
  ] = useState('ترم ۱');

  const [
    lesson,
    setLesson,
  ] = useState(null);

  const [
    session,
    setSession,
  ] = useState(null);

  const [
    lessonForm,
    setLessonForm,
  ] = useState({
    name: '',
    teacher: '',
  });

  const [
    sessionForm,
    setSessionForm,
  ] = useState({
    number: 1,
    topic: '',
    teacher: '',
  });

  const [
    upload,
    setUpload,
  ] = useState({
    type: 'pdf',
    description: '',
    extra_info: '',
    file: null,
  });

  const toast = useUIStore(
    (state) => state.toast
  );

  const queryClient =
    useQueryClient();

  /* 🌊 C1 — scope ورودی پنل محتوا */
  const cscope = useContentScope();

  const iv = cscope.intake ?? '';

  {/* 🌊 C1.5 — درس سراسری برای ادمین ورودی خاص: فقط‌خواندنی */}
  const lessonRO = Boolean(lesson?.readonly);


  const {
    data: terms = [
      'ترم ۱',
      'ترم ۲',
      'ترم ۳',
      'ترم ۴',
      'ترم ۵',
    ],
  } = useQuery({
    queryKey: [
      'bs-admin-terms',
    ],

    queryFn: () =>
      api
        .get(
          '/api/content/basic-science/terms'
        )
        .then(
          (response) =>
            response.data
              ?.terms || []
        ),
  });


  const {
    data: lessons = [],
    isLoading: lessonsLoading,
  } = useQuery({
    queryKey: [
      'bs-admin-lessons',
      iv,
      term,
    ],

    queryFn: () =>
      api
        .get(
          '/api/content/basic-science/lessons',

          {
            params: {
              term,
              intake: iv,
            },
          }
        )
        .then(
          (response) =>
            response.data
              ?.lessons || []
        ),

    enabled:
      cscope.intake !== null,
  });


  const {
    data: sessionsPayload,
    isLoading: sessionsLoading,
  } = useQuery({
    queryKey: [
      'bs-admin-sessions',
      iv,
      lesson?.id,
    ],

    queryFn: () =>
      api
        .get(
          `/api/content/basic-science/lessons/${lesson.id}/sessions`
        )
        .then(
          (response) =>
            response.data || {}
        ),

    enabled:
      Boolean(lesson?.id),
  });

  const sessions = sessionsPayload?.sessions || [];

  /* 🌊 C3 — درس 🌐 سراسری برای ادمین ورودی خاص فقط‌خواندنی است،
     ولی ساختن «جلسه‌ای که فقط برای ورودی خودش است» آزاد است؛
     سرور تصمیم می‌گیرد (can_create_own) — فرانت فقط نمایش می‌دهد. */
  const canAddOwnSession = Boolean(
    sessionsPayload?.can_create_own
  );


  const {
    data: sessionData,
    isLoading: contentLoading,
  } = useQuery({
    queryKey: [
      'bs-admin-content',
      iv,
      session?.id,
    ],

    queryFn: () =>
      api
        .get(
          `/api/content/basic-science/sessions/${session.id}/content`
        )
        .then(
          (response) =>
            response.data
        ),

    enabled:
      Boolean(session?.id),
  });

  const content =
    sessionData?.content || [];

  /* 🍴 C2 — قفل در سطح «جلسه» resolve می‌شود: نسخه‌ی
     اختصاصی (fork) روی درس سراسری، برای مالک ورودی
     قابل ویرایش است حتی اگر خود درس فقط‌خواندنی باشد */
  const sessionRO = Boolean(
    sessionData?.readonly
  );

  const sessionIsFork = Boolean(
    sessionData?.is_fork
  );


  const refresh = async () => {
    await Promise.all([
      queryClient
        .invalidateQueries({
          queryKey: [
            'bs-admin-lessons',
          ],
        }),

      queryClient
        .invalidateQueries({
          queryKey: [
            'bs-admin-sessions',
          ],
        }),

      queryClient
        .invalidateQueries({
          queryKey: [
            'bs-admin-content',
          ],
        }),
    ]);
  };


  const mutation = useMutation({
    mutationFn: async ({
      type,
      id,
    }) => {
      if (
        type === 'lesson-add'
      ) {
        return api.post(
          '/api/content/basic-science/lessons',

          {
            term,
            intake: iv,

            ...lessonForm,
          }
        );
      }

      if (
        type === 'lesson-delete'
      ) {
        return api.delete(
          `/api/content/basic-science/lessons/${id}`
        );
      }

      if (
        type === 'session-add'
      ) {
        return api.post(
          `/api/content/basic-science/lessons/${lesson.id}/sessions`,

          {
            ...sessionForm,

            number:
              Number(
                sessionForm.number
              ),
          }
        );
      }

      if (
        type === 'session-delete'
      ) {
        return api.delete(
          `/api/content/basic-science/sessions/${id}`
        );
      }

      /* 🍴 C2 — ساخت/حذف نسخه‌ی اختصاصی جلسه‌ی سراسری */
      if (
        type === 'session-fork'
      ) {
        return api.post(
          `/api/content/basic-science/sessions/${id}/fork`,

          null,

          {
            params: {
              intake: iv,
            },
          }
        );
      }

      if (
        type === 'session-unfork'
      ) {
        return api.delete(
          `/api/content/basic-science/sessions/${id}/fork`
        );
      }

      if (
        type === 'content-delete'
      ) {
        return api.delete(
          `/api/content/basic-science/content/${id}`
        );
      }

      const body =
        new FormData();

      body.append(
        'ctype',
        upload.type
      );

      body.append(
        'description',
        upload.description
      );

      body.append(
        'extra_info',
        upload.extra_info
      );

      body.append(
        'file',
        upload.file
      );

      // 🐛 FIX آپلود ویدیو — تایم‌اوت سراسری ۱۵ ثانیه است؛ آپلود فایل
      // (به‌ویژه ویدیو) دو هاپ دارد (مرورگر→سرور→تلگرام) و عملاً همیشه
      // از ۱۵ ثانیه بیشتر می‌شود. فقط همین درخواست مهلت طولانی می‌گیرد.
      return api.post(
        `/api/content/basic-science/sessions/${session.id}/content`,

        body,
        { timeout: 600000 }
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

      if (
        variables.type ===
        'lesson-add'
      ) {
        setLessonForm({
          name: '',
          teacher: '',
        });
      }

      if (
        variables.type ===
        'session-add'
      ) {
        // 🌊 C3 — سرور شماره‌ی بعدی را در همان سطل پیشنهاد می‌دهد
        // (برای ادمین ورودی خاص: ماکزیمم «سراسری + ورودی خودش» + ۱)
        setSessionForm({
          number: sessionsPayload?.next_number ?? 1,
          topic: '',
          teacher: '',
        });
      }

      if (
        variables.type ===
        'upload'
      ) {
        setUpload({
          type: 'pdf',
          description: '',
          extra_info: '',
          file: null,
        });
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


  const goBack = () => {
    if (session) {
      setSession(null);

    } else if (lesson) {
      setLesson(null);
    }
  };


  const title =
    session
      ? session.topic

      : lesson
        ? lesson.name

        : 'مدیریت علوم پایه';


  const typeIcon = {
    video: '🎬',
    ppt: '📊',
    pdf: '📄',
    note: '📝',
    test: '🧪',
    voice: '🎧',
  };


  /* 🌊 C1 — بدون انتخاب ورودی، ابزار باز نمی‌شود */
  if (cscope.needsPicker) {
    return <ContentScopeGate />;
  }


  return (
    <>
      <Header
        title={
          title ||
          'علوم پایه'
        }
        subtitle={
          session
            ? 'محتوای جلسه'

            : lesson
              ? 'جلسات درس'

              : 'درس‌ها و محتوای آموزشی'
        }
        back
        onBack={
          lesson
            ? goBack
            : undefined
        }
      />

      <main className="page fade-up">
        <ContentScopeBanner scope={cscope} />
        {!lesson && (
          <>
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
                🔬 کتابخانه علوم پایه
              </div>

              <div className="tab-bar">
                {terms.map(
                  (item) => (
                    <button
                      key={item}
                      className="tab-btn"
                      onClick={() =>
                        setTerm(item)
                      }
                      style={{
                        color:
                          term === item
                            ? 'var(--t-white)'
                            : 'var(--tx2)',

                        background:
                          term === item
                            ? 'var(--grad-brand)'
                            : 'transparent',
                      }}
                    >
                      {item}
                    </button>
                  )
                )}
              </div>

              <div className="grid2">
                <input
                  className="inp"
                  value={
                    lessonForm.name
                  }
                  onChange={(event) =>
                    setLessonForm({
                      ...lessonForm,

                      name:
                        event.target
                          .value,
                    })
                  }
                  placeholder="نام درس"
                />

                <input
                  className="inp"
                  value={
                    lessonForm.teacher
                  }
                  onChange={(event) =>
                    setLessonForm({
                      ...lessonForm,

                      teacher:
                        event.target
                          .value,
                    })
                  }
                  placeholder="استاد"
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
                  !lessonForm
                    .name
                    .trim() ||
                  mutation.isPending
                }
                onClick={() =>
                  mutation.mutate({
                    type:
                      'lesson-add',
                  })
                }
              >
                ＋ افزودن درس
              </button>
            </section>


            {lessonsLoading ? (
              <LibraryTilesSkeleton />
            ) : lessons.length ===
              0 ? (
              <EmptyState>
                درسی در این ترم ثبت نشده
                است.
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
                {lessons.map(
                  (item) => (
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
                              'var(--soft-ok)',

                            fontSize: 'var(--fs-xl)',
                          }}
                        >
                          📗
                        </span>

                        <button
                          type="button"
                          onClick={() =>
                            setLesson(
                              item
                            )
                          }
                          style={{
                            flex:
                              1,

                            color:
                              'var(--tx)',

                            textAlign:
                              'right',

                            background:
                              'none',

                            border:
                              0,

                            cursor:
                              'pointer',
                          }}
                        >
                          <b>
                            {item.name}
                          </b>

                          {/* 🌊 C1.5 — بج سراسری (فقط‌خواندنی) */}
                          {item.readonly && (
                            <span
                              style={{
                                display:
                                  'block',

                                color:
                                  'var(--gold, #d4a017)',

                                fontSize: 'var(--fs-cap)',

                                marginTop:
                                  2,
                              }}
                            >
                              🔒 سراسری — فقط‌خواندنی
                            </span>
                          )}

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
                            {item.teacher ||
                              'بدون استاد'}
                          </span>
                        </button>

                        {/* 🌊 C1.5 — حذف روی سراسری برای scoped مخفی */}
                        {!item.readonly && (
                        <DeleteButton
                          pending={
                            mutation
                              .isPending
                          }
                          onClick={async () => {
                            const accepted =
                              await confirmAction(
                                'درس و زیرمجموعه‌های آن حذف شود؟'
                              );

                            if (accepted) {
                              mutation
                                .mutate({
                                  type:
                                    'lesson-delete',

                                  id:
                                    item.id,
                                });
                            }
                          }}
                        />
                        )}
                      </div>
                    </article>
                  )
                )}
              </section>
            )}
          </>
        )}


        {lesson &&
          !session && (
          <>
            {/* 🌊 C1.5/C3 — افزودن جلسه روی درس سراسری برای scoped مخفی بود؛
                حالا اگر سرور اجازه‌ی «فرزند ورودی‌خاص» را بدهد (can_create_own)
                فرم باز می‌شود و جلسه فقط برای ورودی خودِ کاربر ساخته می‌شود. */}
            {(!lessonRO || canAddOwnSession) && (
            <section
              className={
                'card card-glow'
              }
              style={{
                display:
                  'grid',

                gap:
                  9,

                marginBottom:
                  13,
              }}
            >
              <div className="sec-title">
                ＋ جلسه جدید
                {lessonRO && canAddOwnSession
                  ? ' • فقط ورودی من'
                  : ''}
              </div>

              {lessonRO && canAddOwnSession ? (
                <div
                  style={{
                    color: 'var(--txm)',

                    fontSize: 'var(--fs-cap)',
                  }}
                >
                  📅 این جلسه فقط برای ورودی شما ساخته می‌شود؛
                  نسخه‌ی سراسریِ درس تغییر نمی‌کند.
                </div>
              ) : null}

              <div className="grid2">
                <input
                  className="inp"
                  type="number"
                  min="1"
                  value={
                    sessionForm.number
                  }
                  onChange={(event) =>
                    setSessionForm({
                      ...sessionForm,

                      number:
                        event.target
                          .value,
                    })
                  }
                  placeholder="شماره"
                />

                <input
                  className="inp"
                  value={
                    sessionForm.topic
                  }
                  onChange={(event) =>
                    setSessionForm({
                      ...sessionForm,

                      topic:
                        event.target
                          .value,
                    })
                  }
                  placeholder="موضوع جلسه"
                />
              </div>

              <input
                className="inp"
                value={
                  sessionForm.teacher
                }
                onChange={(event) =>
                  setSessionForm({
                    ...sessionForm,

                    teacher:
                      event.target
                        .value,
                  })
                }
                placeholder="استاد جلسه"
              />

              <button
                className={
                  'btn btn-p btn-full'
                }
                disabled={
                  !sessionForm
                    .topic
                    .trim() ||
                  mutation.isPending
                }
                onClick={() =>
                  mutation.mutate({
                    type:
                      'session-add',
                  })
                }
              >
                افزودن جلسه
              </button>
            </section>
            )}


            {sessionsLoading ? (
              <LibraryRowsSkeleton />
            ) : sessions.length ===
              0 ? (
              <EmptyState>
                جلسه‌ای ثبت نشده است.
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
                {sessions.map(
                  (item) => (
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
                              'var(--acc-soft)',

                            color:
                              'var(--acc2)',

                            fontWeight:
                              900,
                          }}
                        >
                          {item.number}
                        </span>

                        <button
                          type="button"
                          onClick={() =>
                            setSession(
                              item
                            )
                          }
                          style={{
                            flex:
                              1,

                            color:
                              'var(--tx)',

                            textAlign:
                              'right',

                            background:
                              'none',

                            border:
                              0,

                            cursor:
                              'pointer',
                          }}
                        >
                          <b>
                            {item.topic}
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
                            {item.teacher ||
                              'بدون استاد'}

                            {/* 🍴 C2 — نشان نسخه‌ی اختصاصی */}
                            {item.is_fork &&
                              ' • ⭐ نسخه‌ی اختصاصی'}

                            {/* 🌊 C3 — جلسه‌ای که فقط برای ورودی
                                خودِ کاربر است (فرزند، نه فورک) */}
                            {item.own &&
                              ' • 📅 فقط ورودی من'}
                          </span>
                        </button>

                        {/* 🍴 C2 — روی درس سراسری (فقط‌خواندنی برای
                             ادمین ورودی‌خاص): ✂️ ساخت نسخه‌ی اختصاصی
                             برای ورودی خودش؛ ↩️ حذف نسخه‌ی من
                             🌊 C3 — روی «فرزند ورودی من» فورک معنا ندارد
                             (مستقیماً ویرایش می‌شود) ⇒ دکمه مخفی */}
                        {lessonRO &&
                          !item.is_fork &&
                          !item.own && (
                            <button
                              type="button"
                              title="سفارشی‌سازی برای ورودی من"
                              onClick={async () => {
                                const accepted =
                                  await confirmAction(
                                    'نسخه‌ی اختصاصی این جلسه برای ورودی شما ساخته و جایگزین نسخه‌ی سراسری شود؟'
                                  );

                                if (
                                  accepted
                                ) {
                                  mutation.mutate(
                                    {
                                      type: 'session-fork',

                                      id: item.id,
                                    }
                                  );
                                }
                              }}
                              style={{
                                background:
                                  'none',

                                border: 0,

                                cursor:
                                  'pointer',

                                fontSize:
                                  17,
                              }}
                            >
                              ✂️
                            </button>
                          )}

                        {lessonRO &&
                          item.is_fork && (
                            <button
                              type="button"
                              title="حذف نسخه‌ی من و بازگشت به نسخه‌ی سراسری"
                              onClick={async () => {
                                const accepted =
                                  await confirmAction(
                                    'نسخه‌ی اختصاصی شما حذف و نسخه‌ی سراسری بازگردانده شود؟'
                                  );

                                if (
                                  accepted
                                ) {
                                  mutation.mutate(
                                    {
                                      type: 'session-unfork',

                                      id: item.id,
                                    }
                                  );
                                }
                              }}
                              style={{
                                background:
                                  'none',

                                border: 0,

                                cursor:
                                  'pointer',

                                fontSize:
                                  17,
                              }}
                            >
                              ↩️
                            </button>
                          )}

                        {/* 🌊 C1.5 — حذف جلسه‌ی سراسری برای scoped مخفی
                            🌊 C3 — ولی «فرزند ورودی من» مالِ خود اوست ⇒ حذف‌پذیر */}
                        {(!lessonRO || item.own) && (
                        <DeleteButton
                          pending={
                            mutation
                              .isPending
                          }
                          onClick={async () => {
                            const accepted =
                              await confirmAction(
                                'جلسه حذف شود؟'
                              );

                            if (accepted) {
                              mutation
                                .mutate({
                                  type:
                                    'session-delete',

                                  id:
                                    item.id,
                                });
                            }
                          }}
                        />
                        )}
                      </div>
                    </article>
                  )
                )}
              </section>
            )}
          </>
        )}


        {session && (
          <>
            {/* 🍴 C2 — آپلود در سطح جلسه enforce می‌شود:
                 جلسه‌ی سراسری برای scoped مخفی؛ نسخه‌ی fork مجاز */}
            {!sessionRO && (
            <section
              className={
                'card card-glow'
              }
              style={{
                display:
                  'grid',

                gap:
                  9,

                marginBottom:
                  13,
              }}
            >
              <div className="sec-title">
                📤 افزودن محتوا
              </div>

              <select
                className="inp"
                value={
                  upload.type
                }
                onChange={(event) =>
                  setUpload({
                    ...upload,

                    type:
                      event.target
                        .value,
                  })
                }
              >
                {Object.entries(
                  typeIcon
                ).map(
                  ([
                    key,
                    icon,
                  ]) => (
                    <option
                      key={key}
                      value={key}
                    >
                      {icon} {key}
                    </option>
                  )
                )}
              </select>

              <input
                className="inp"
                value={
                  upload.description
                }
                onChange={(event) =>
                  setUpload({
                    ...upload,

                    description:
                      event.target
                        .value,
                  })
                }
                placeholder="توضیحات"
              />

              <input
                className="inp"
                value={
                  upload.extra_info
                }
                onChange={(event) =>
                  setUpload({
                    ...upload,

                    extra_info:
                      event.target
                        .value,
                  })
                }
                placeholder="اطلاعات تکمیلی"
              />

              <input
                className="inp"
                type="file"
                accept={
                  // 🐛 FIX آپلود ویدیو — انتخابگر فایل هم‌راستا با نوع
                  // محتوا؛ قبلاً بدون accept بود (انتخاب فایل اشتباه).
                  upload.type === 'video' ? 'video/*'
                  : upload.type === 'voice' ? 'audio/*'
                  : upload.type === 'pdf' ? 'application/pdf,.pdf'
                  : upload.type === 'ppt'
                    ? '.ppt,.pptx,application/vnd.ms-powerpoint,application/vnd.openxmlformats-officedocument.presentationml.presentation'
                  : 'image/*,application/pdf,.pdf'
                }
                onChange={(event) =>
                  setUpload({
                    ...upload,

                    file:
                      event.target
                        .files?.[0] ||
                      null,
                  })
                }
              />

              {/* 🐛 FIX آپلود ویدیو — سقف حجم قبل از ارسال (۴۵MB = سقف
                  سرور)؛ پیام شفاف به‌جای خطای عمومی پس از آپلود کامل. */}
              {upload.file && upload.file.size > 45 * 1024 * 1024 && (
                <div
                  className="muted"
                  style={{ color: 'var(--red, #e5484d)', margin: '0 2px 9px' }}
                >
                  ⚠️ حجم این فایل بیش از ۴۵ مگابایت است — آپلود نمی‌شود.
                </div>
              )}

              <button
                className={
                  'btn btn-p btn-full'
                }
                disabled={
                  !upload.file ||
                  upload.file.size > 45 * 1024 * 1024 ||
                  mutation.isPending
                }
                onClick={() =>
                  mutation.mutate({
                    type:
                      'upload',
                  })
                }
              >
                {mutation.isPending ? (
                  <Spinner size={14} />
                ) : (
                  'آپلود فایل'
                )}
              </button>
            </section>
            )}


            {/* 🍴 C2 — راهنمای وضعیت نسخه‌ی اختصاصی */}
            {sessionIsFork && (
              <div
                style={{
                  color:
                    'var(--gold, #d4a017)',

                  fontSize:
                    'var(--fs-cap)',

                  margin:
                    '0 2px 9px',
                }}
              >
                ⭐ نسخه‌ی اختصاصی ورودی
                شما — ویرایش این بخش روی
                نسخه‌ی سراسری اثری ندارد.
              </div>
            )}

            {contentLoading ? (
              <LibraryRowsSkeleton />
            ) : content.length ===
              0 ? (
              <EmptyState>
                محتوایی ثبت نشده است.
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
                {content.map(
                  (item) => (
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
                              'var(--soft-pur)',

                            fontSize: 'var(--fs-xl)',
                          }}
                        >
                          {typeIcon[
                            item.type
                          ] || '📎'}
                        </span>

                        <div
                          style={{
                            flex:
                              1,
                          }}
                        >
                          <b>
                            {item.description ||
                              item.type}
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
                            {item.extra_info ||
                              ''}

                            {' • '}

                            {number(
                              item.downloads
                            )}{' '}

                            دانلود
                          </div>
                        </div>

                        {/* 🍴 C2 — حذف محتوا در سطح جلسه enforce می‌شود:
                             محتوای fork برای مالک ورودی حذف‌پذیر است */}
                        {!sessionRO && (
                        <DeleteButton
                          pending={
                            mutation
                              .isPending
                          }
                          onClick={async () => {
                            const accepted =
                              await confirmAction(
                                'محتوا حذف شود؟'
                              );

                            if (accepted) {
                              mutation
                                .mutate({
                                  type:
                                    'content-delete',

                                  id:
                                    item.id,
                                });
                            }
                          }}
                        />
                        )}
                      </div>
                    </article>
                  )
                )}
              </section>
            )}
          </>
        )}
      </main>
    </>
  );
}


/* مدیریت رفرنس‌ها */

export function ReferencesAdmin() {
  const [
    subject,
    setSubject,
  ] = useState(null);

  const [
    book,
    setBook,
  ] = useState(null);

  const [
    name,
    setName,
  ] = useState('');

  const [
    upload,
    setUpload,
  ] = useState({
    lang: 'fa',
    volume: 1,
    description: '',
    file: null,
  });

  const toast = useUIStore(
    (state) => state.toast
  );

  const queryClient =
    useQueryClient();

  /* 🌊 C1 — scope ورودی پنل محتوا */
  const cscope = useContentScope();

  const iv = cscope.intake ?? '';

  {/* 🌊 C1.5 — موضوع سراسری برای ادمین ورودی خاص: فقط‌خواندنی */}
  const subjectRO = Boolean(subject?.readonly);


  const {
    data: subjects = [],
    isLoading,
  } = useQuery({
    queryKey: [
      'ref-admin-subjects',
      iv,
    ],

    queryFn: () =>
      api
        .get(
          '/api/content/references/subjects',

          {
            params: {
              intake: iv,
            },
          }
        )
        .then(
          (response) =>
            response.data
              ?.subjects || []
        ),

    enabled:
      cscope.intake !== null,
  });


  const {
    data: booksPayload,
  } = useQuery({
    queryKey: [
      'ref-admin-books',
      iv,
      subject?.id,
    ],

    queryFn: () =>
      api
        .get(
          `/api/content/references/subjects/${subject.id}/books`
        )
        .then(
          (response) =>
            response.data || {}
        ),

    enabled:
      Boolean(subject?.id),
  });

  const books = booksPayload?.books || [];

  /* 🌊 C3 — موضوع 🌐 سراسری برای ادمین ورودی خاص فقط‌خواندنی است، ولی
     ساختن «کتابی که فقط برای ورودی خودش است» آزاد است؛ تصمیم با سرور
     است (can_create_own) و فرانت فقط نمایش می‌دهد. */
  const booksCanCreate = Boolean(
    booksPayload?.can_create_own
  );


  const {
    data: bookData,
  } = useQuery({
    queryKey: [
      'ref-admin-files',
      iv,
      book?.id,
    ],

    queryFn: () =>
      api
        .get(
          `/api/content/references/books/${book.id}/files`
        )
        .then(
          (response) =>
            response.data
        ),

    enabled:
      Boolean(book?.id),
  });

  const files = bookData?.files || [];

  /* 🍴 C2 — قفل در سطح «کتاب» resolve می‌شود: fork روی موضوع
     سراسری برای مالک ورودی قابل ویرایش است */
  const bookRO = Boolean(bookData?.readonly);

  const bookIsFork = Boolean(bookData?.is_fork);


  const refresh = async () => {
    await Promise.all([
      queryClient
        .invalidateQueries({
          queryKey: [
            'ref-admin-subjects',
          ],
        }),

      queryClient
        .invalidateQueries({
          queryKey: [
            'ref-admin-books',
          ],
        }),

      queryClient
        .invalidateQueries({
          queryKey: [
            'ref-admin-files',
          ],
        }),
    ]);
  };


  const mutation = useMutation({
    mutationFn: async ({
      type,
      id,
    }) => {
      if (
        type === 'subject-add'
      ) {
        return api.post(
          '/api/content/references/subjects',

          {
            name:
              name.trim(),
            intake: iv,
          }
        );
      }

      if (
        type === 'subject-delete'
      ) {
        return api.delete(
          `/api/content/references/subjects/${id}`
        );
      }

      if (
        type === 'book-add'
      ) {
        return api.post(
          `/api/content/references/subjects/${subject.id}/books`,

          {
            name:
              name.trim(),
          }
        );
      }

      if (
        type === 'book-delete'
      ) {
        return api.delete(
          `/api/content/references/books/${id}`
        );
      }

      /* 🍴 C2 — ساخت/حذف نسخه‌ی اختصاصی کتاب سراسری */
      if (
        type === 'book-fork'
      ) {
        return api.post(
          `/api/content/references/books/${id}/fork`,

          null,

          {
            params: {
              intake: iv,
            },
          }
        );
      }

      if (
        type === 'book-unfork'
      ) {
        return api.delete(
          `/api/content/references/books/${id}/fork`
        );
      }

      if (
        type === 'file-delete'
      ) {
        return api.delete(
          `/api/content/references/files/${id}`
        );
      }

      const body =
        new FormData();

      body.append(
        'lang',
        upload.lang
      );

      body.append(
        'volume',
        String(upload.volume)
      );

      body.append(
        'description',
        upload.description
      );

      body.append(
        'file',
        upload.file
      );

      return api.post(
        `/api/content/references/books/${book.id}/files`,

        body,
        // 🐛 FIX آپلود ویدیو — مهلت طولانی فقط برای آپلود فایل
        { timeout: 600000 }
      );
    },

    onSuccess: async () => {
      toast(
        'عملیات انجام شد ✅',
        'success'
      );

      setName('');

      setUpload({
        lang: 'fa',
        volume: 1,
        description: '',
        file: null,
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


  const back = () => {
    if (book) {
      setBook(null);

    } else if (subject) {
      setSubject(null);
    }
  };


  /* 🌊 C1 — بدون انتخاب ورودی، ابزار باز نمی‌شود */
  if (cscope.needsPicker) {
    return <ContentScopeGate />;
  }


  return (
    <>
      <Header
        title={
          book?.name ||
          subject?.name ||
          'مدیریت رفرنس‌ها'
        }
        back
        onBack={
          subject
            ? back
            : undefined
        }
      />

      <main className="page fade-up">
        <ContentScopeBanner scope={cscope} />
        {/* 🍴 C2 — در سطح کتاب، قفل کتابِ انتخاب‌شده enforce می‌شود:
             fork روی موضوع سراسری برای مالک ورودی باز (آپلود جلد مجاز) */}
        {(book ? !bookRO : (!subjectRO || booksCanCreate)) && (
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
            {book
              ? '📤 افزودن جلد'

              : subject
                ? `＋ افزودن کتاب${
                    subjectRO && booksCanCreate
                      ? ' • فقط ورودی من'
                      : ''
                  }`

                : '＋ افزودن موضوع'}
          </div>

          {book ? (
            <div
              style={{
                display:
                  'grid',

                gap:
                  8,
              }}
            >
              <div className="grid2">
                <select
                  className="inp"
                  value={
                    upload.lang
                  }
                  onChange={(event) =>
                    setUpload({
                      ...upload,

                      lang:
                        event.target
                          .value,
                    })
                  }
                >
                  <option value="fa">
                    فارسی
                  </option>

                  <option value="en">
                    انگلیسی
                  </option>
                </select>

                <input
                  className="inp"
                  type="number"
                  min="1"
                  value={
                    upload.volume
                  }
                  onChange={(event) =>
                    setUpload({
                      ...upload,

                      volume:
                        event.target
                          .value,
                    })
                  }
                  placeholder="جلد"
                />
              </div>

              <input
                className="inp"
                value={
                  upload.description
                }
                onChange={(event) =>
                  setUpload({
                    ...upload,

                    description:
                      event.target
                        .value,
                  })
                }
                placeholder="توضیحات"
              />

              <input
                className="inp"
                type="file"
                onChange={(event) =>
                  setUpload({
                    ...upload,

                    file:
                      event.target
                        .files?.[0] ||
                      null,
                  })
                }
              />

              <button
                className="btn btn-p"
                disabled={
                  !upload.file ||
                  // 🐛 FIX آپلود ویدیو — سقف ۴۵MB سمت کلاینت هم اعمال
                  // می‌شود (سرور همچنان مرجع است).
                  upload.file.size > 45 * 1024 * 1024 ||
                  mutation.isPending
                }
                onClick={() =>
                  mutation.mutate({
                    type:
                      'file-add',
                  })
                }
              >
                آپلود جلد
              </button>
            </div>
          ) : (
            <div
              style={{
                display:
                  'flex',

                gap: 'var(--sp-2)',
              }}
            >
              <input
                className="inp"
                value={name}
                onChange={(event) =>
                  setName(
                    event.target.value
                  )
                }
                placeholder={
                  subject
                    ? 'نام کتاب'
                    : 'نام درس یا موضوع'
                }
              />

              <button
                className="btn btn-p"
                disabled={
                  !name.trim() ||
                  mutation.isPending
                }
                onClick={() =>
                  mutation.mutate({
                    type:
                      subject
                        ? 'book-add'
                        : 'subject-add',
                  })
                }
              >
                افزودن
              </button>
            </div>
          )}
        </section>
        )}


        {!subject ? (
          isLoading ? (
            <LibraryTilesSkeleton />
          ) : (
            <section
              style={{
                display:
                  'grid',

                gap:
                  8,
              }}
            >
              {subjects.map((item) => (
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
                        fontSize:
                          22,
                      }}
                    >
                      🩺
                    </span>

                    <button
                      type="button"
                      onClick={() =>
                        setSubject(
                          item
                        )
                      }
                      style={{
                        flex:
                          1,

                        textAlign:
                          'right',

                        background:
                          'none',

                        border:
                          0,

                        color:
                          'var(--tx)',
                      }}
                    >
                      <b>
                        {item.name}
                      </b>

                      {/* 🌊 C1.5 — بج سراسری (فقط‌خواندنی) */}
                      {item.readonly && (
                        <span
                          style={{
                            display:
                              'block',

                            color:
                              'var(--gold, #d4a017)',

                            fontSize: 'var(--fs-cap)',

                            marginTop:
                              2,
                          }}
                        >
                          🔒 سراسری — فقط‌خواندنی
                        </span>
                      )}
                    </button>

                    {/* 🌊 C1.5 — حذف روی سراسری برای scoped مخفی */}
                    {!item.readonly && (
                    <DeleteButton
                      pending={
                        mutation
                          .isPending
                      }
                      onClick={async () => {
                        const accepted =
                          await confirmAction(
                            'موضوع حذف شود؟'
                          );

                        if (accepted) {
                          mutation
                            .mutate({
                              type:
                                'subject-delete',

                              id:
                                item.id,
                            });
                        }
                      }}
                    />
                    )}
                  </div>
                </article>
              ))}
            </section>
          )
        ) : !book ? (
          <section
            style={{
              display:
                'grid',

              gap:
                8,
            }}
          >
            {books.length ? (
              books.map((item) => (
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
                        fontSize:
                          22,
                      }}
                    >
                      📕
                    </span>

                    <button
                      type="button"
                      onClick={() =>
                        setBook(item)
                      }
                      style={{
                        flex:
                          1,

                        textAlign:
                          'right',

                        background:
                          'none',

                        border:
                          0,

                        color:
                          'var(--tx)',
                      }}
                    >
                      <b>
                        {item.name}

                        {/* 🍴 C2 — نشان نسخه‌ی اختصاصی */}
                        {item.is_fork &&
                          ' ⭐'}

                        {/* 🌊 C3 — کتابی که فقط برای ورودی خودِ کاربر است */}
                        {item.own &&
                          ' • 📅 فقط ورودی من'}
                      </b>
                    </button>

                    {/* 🍴 C2 — روی موضوع سراسری (فقط‌خواندنی برای
                         ادمین ورودی‌خاص): ✂️ fork / ↩️ unfork */}
                    {subjectRO &&
                      !item.is_fork &&
                      !item.own && (
                        <button
                          type="button"
                          title="سفارشی‌سازی برای ورودی من"
                          onClick={async () => {
                            const accepted =
                              await confirmAction(
                                'نسخه‌ی اختصاصی این کتاب برای ورودی شما ساخته و جایگزین نسخه‌ی سراسری شود؟'
                              );

                            if (
                              accepted
                            ) {
                              mutation.mutate(
                                {
                                  type: 'book-fork',

                                  id: item.id,
                                }
                              );
                            }
                          }}
                          style={{
                            background:
                              'none',

                            border: 0,

                            cursor:
                              'pointer',

                            fontSize: 17,
                          }}
                        >
                          ✂️
                        </button>
                      )}

                    {subjectRO &&
                      item.is_fork && (
                        <button
                          type="button"
                          title="حذف نسخه‌ی من و بازگشت به نسخه‌ی سراسری"
                          onClick={async () => {
                            const accepted =
                              await confirmAction(
                                'نسخه‌ی اختصاصی شما حذف و نسخه‌ی سراسری بازگردانده شود؟'
                              );

                            if (
                              accepted
                            ) {
                              mutation.mutate(
                                {
                                  type: 'book-unfork',

                                  id: item.id,
                                }
                              );
                            }
                          }}
                          style={{
                            background:
                              'none',

                            border: 0,

                            cursor:
                              'pointer',

                            fontSize: 17,
                          }}
                        >
                          ↩️
                        </button>
                      )}

                    {/* 🌊 C1.5/C3 — حذف کتابِ سراسری برای scoped مخفی؛
                         فرزندِ «فقط ورودی من» خودِ کاربر می‌تواند حذف کند */}
                    {(!subjectRO || item.own) && (
                    <DeleteButton
                      pending={
                        mutation
                          .isPending
                      }
                      onClick={async () => {
                        const accepted =
                          await confirmAction(
                            'کتاب حذف شود؟'
                          );

                        if (accepted) {
                          mutation
                            .mutate({
                              type:
                                'book-delete',

                              id:
                                item.id,
                            });
                        }
                      }}
                    />
                    )}
                  </div>
                </article>
              ))
            ) : (
              <EmptyState>
                کتابی ثبت نشده است.
              </EmptyState>
            )}
          </section>
        ) : (
          <section
            style={{
              display:
                'grid',

              gap:
                8,
            }}
          >
            {/* 🍴 C2 — راهنمای وضعیت نسخه‌ی اختصاصی کتاب */}
            {bookIsFork && (
              <div
                style={{
                  color:
                    'var(--gold, #d4a017)',

                  fontSize:
                    'var(--fs-cap)',

                  margin: '0 2px 1px',
                }}
              >
                ⭐ نسخه‌ی اختصاصی ورودی شما
                — ویرایش این بخش روی نسخه‌ی
                سراسری اثری ندارد.
              </div>
            )}

            {files.length ? (
              files.map((item) => (
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
                        fontSize:
                          22,
                      }}
                    >
                      {item.lang ===
                      'fa'
                        ? '🇮🇷'
                        : '🇬🇧'}
                    </span>

                    <div
                      style={{
                        flex:
                          1,
                      }}
                    >
                      <b>
                        جلد {item.volume}
                      </b>

                      <div
                        style={{
                          color:
                            'var(--txm)',

                          fontSize: 'var(--fs-cap)',
                        }}
                      >
                        {item.description}

                        {' • '}

                        {number(
                          item.downloads
                        )}{' '}

                        دانلود
                      </div>
                    </div>

                    {/* 🍴 C2 — حذف فایل در سطح کتاب enforce می‌شود:
                         فایل fork برای مالک ورودی حذف‌پذیر است */}
                    {!bookRO && (
                    <DeleteButton
                      pending={
                        mutation
                          .isPending
                      }
                      onClick={async () => {
                        const accepted =
                          await confirmAction(
                            'فایل حذف شود؟'
                          );

                        if (accepted) {
                          mutation
                            .mutate({
                              type:
                                'file-delete',

                              id:
                                item.id,
                            });
                        }
                      }}
                    />
                    )}
                  </div>
                </article>
              ))
            ) : (
              <EmptyState>
                فایلی ثبت نشده است.
              </EmptyState>
            )}
          </section>
        )}
      </main>
    </>
  );
}


/* بانک فایل سؤال */

export function QbankAdmin() {
  const [
    form,
    setForm,
  ] = useState({
    lesson: '',
    topic: '',
    description: '',
    file: null,
  });

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
  } = useQuery({
    queryKey: [
      'qbank-admin',
      iv,
    ],

    queryFn: () =>
      api
        .get(
          '/api/content/qbank/files',

          {
            params: {
              intake: iv,
            },
          }
        )
        .then(
          (response) =>
            response.data
              ?.files || []
        ),

    enabled:
      cscope.intake !== null,
  });


  const refresh = () =>
    queryClient.invalidateQueries({
      queryKey: [
        'qbank-admin',
      ],
    });


  const mutation = useMutation({
    mutationFn: async ({
      type,
      id,
    }) => {
      if (type === 'delete') {
        return api.delete(
          `/api/content/qbank/files/${id}`
        );
      }

      const body =
        new FormData();

      body.append(
        'lesson',
        form.lesson.trim()
      );

      body.append(
        'intake',
        iv
      );

      body.append(
        'topic',
        form.topic.trim()
      );

      body.append(
        'description',
        form.description.trim()
      );

      body.append(
        'file',
        form.file
      );

      return api.post(
        '/api/content/qbank/files',
        body
      );
    },

    onSuccess: async () => {
      toast(
        'عملیات انجام شد ✅',
        'success'
      );

      setForm({
        lesson: '',
        topic: '',
        description: '',
        file: null,
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


  const files =
    Array.isArray(data)
      ? data
      : [];


  /* 🌊 C1 — بدون انتخاب ورودی، ابزار باز نمی‌شود */
  if (cscope.needsPicker) {
    return <ContentScopeGate />;
  }


  return (
    <>
      <Header
        title="بانک فایل سؤال"
        subtitle={`${files.length} فایل`}
      />

      <main className="page fade-up">
        <ContentScopeBanner scope={cscope} />
        <section
          className={
            'card card-glow'
          }
          style={{
            display:
              'grid',

            gap:
              8,

            marginBottom:
              13,
          }}
        >
          <div className="sec-title">
            📤 فایل جدید
          </div>

          <div className="grid2">
            <input
              className="inp"
              value={form.lesson}
              onChange={(event) =>
                setForm({
                  ...form,

                  lesson:
                    event.target.value,
                })
              }
              placeholder="درس"
            />

            <input
              className="inp"
              value={form.topic}
              onChange={(event) =>
                setForm({
                  ...form,

                  topic:
                    event.target.value,
                })
              }
              placeholder="مبحث"
            />
          </div>

          <input
            className="inp"
            value={
              form.description
            }
            onChange={(event) =>
              setForm({
                ...form,

                description:
                  event.target.value,
              })
            }
            placeholder="توضیحات"
          />

          <input
            className="inp"
            type="file"
            onChange={(event) =>
              setForm({
                ...form,

                file:
                  event.target
                    .files?.[0] ||
                  null,
              })
            }
          />

          <button
            className="btn btn-p"
            disabled={
              !form.lesson.trim() ||
              !form.topic.trim() ||
              !form.file ||
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
              'آپلود فایل'
            )}
          </button>
        </section>


        {isLoading ? (
          <LibraryRowsSkeleton />
        ) : isError ? (
          <EmptyState>
            دریافت فایل‌ها انجام نشد.

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
        ) : files.length === 0 ? (
          <EmptyState>
            فایلی ثبت نشده است.
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
            {files.map((item) => (
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
                      fontSize:
                        22,
                    }}
                  >
                    {item.file_type ===
                    'video'
                      ? '🎬'

                      : item.file_type ===
                          'voice'
                        ? '🎧'

                        : '📄'}
                  </span>

                  <div
                    style={{
                      flex:
                        1,
                    }}
                  >
                    <b>
                      {item.lesson}
                      {' — '}
                      {item.topic}
                    </b>

                    {/* 🌊 C1.5 — بج سراسری (فقط‌خواندنی) */}
                    {item.readonly && (
                      <div
                        style={{
                          color:
                            'var(--gold, #d4a017)',

                          fontSize: 'var(--fs-cap)',

                          marginTop:
                            2,
                        }}
                      >
                        🔒 سراسری — فقط‌خواندنی
                      </div>
                    )}

                    <div
                      style={{
                        color:
                          'var(--txm)',

                        fontSize: 'var(--fs-cap)',

                        marginTop:
                          3,
                      }}
                    >
                      {item.description ||
                        'بدون توضیح'}

                      {' • '}

                      {number(
                        item.downloads
                      )}{' '}

                      دانلود

                      {' • '}

                      {item.upload_date ||
                        '—'}
                    </div>
                  </div>

                  {/* 🌊 C1.5 — حذف روی سراسری برای scoped مخفی */}
                  {!item.readonly && (
                  <DeleteButton
                    pending={
                      mutation.isPending
                    }
                    onClick={async () => {
                      const accepted =
                        await confirmAction(
                          'فایل حذف شود؟'
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
                  />
                  )}
                </div>
              </article>
            ))}
          </section>
        )}
      </main>
    </>
  );
}


/* گزارش‌های محتوا */

export function ContentReportsAdmin() {
  const [
    status,
    setStatus,
  ] = useState('new');

  const toast = useUIStore(
    (state) => state.toast
  );

  const queryClient =
    useQueryClient();


  const {
    data: stats,
  } = useQuery({
    queryKey: [
      'content-report-stats',
    ],

    queryFn: () =>
      api
        .get(
          '/api/content/reports/stats'
        )
        .then(
          (response) =>
            response.data
        ),
  });


  const {
    data = [],
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: [
      'content-reports',
      status,
    ],

    queryFn: () =>
      api
        .get(
          '/api/content/reports',

          {
            params: {
              status,
            },
          }
        )
        .then(
          (response) =>
            response.data
              ?.reports || []
        ),
  });


  const mutation = useMutation({
    mutationFn: ({
      id,
      value,
    }) =>
      api.post(
        `/api/content/reports/${id}/status`,

        {
          status:
            value,
        }
      ),

    onSuccess: async () => {
      hapticNotif(
        'success'
      );

      toast(
        'وضعیت گزارش تغییر کرد ✅',
        'success'
      );

      await Promise.all([
        queryClient
          .invalidateQueries({
            queryKey: [
              'content-reports',
            ],
          }),

        queryClient
          .invalidateQueries({
            queryKey: [
              'content-report-stats',
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


  const reports =
    Array.isArray(data)
      ? data
      : [];


  const tabs = [
    [
      'new',
      'جدید',
    ],

    [
      'reviewing',
      'در بررسی',
    ],

    [
      'resolved',
      'برطرف‌شده',
    ],

    [
      'rejected',
      'ردشده',
    ],
  ];


  return (
    <>
      <Header
        title="گزارش‌های محتوا"
        subtitle={`${
          Number(stats?.new) ||
          0
        } گزارش جدید`}
      />

      <main className="page fade-up">
        <section
          className="grid2"
          style={{
            marginBottom:
              13,
          }}
        >
          <div
            className="card"
            style={{
              textAlign:
                'center',
            }}
          >
            <b
              style={{
                color:
                  'var(--warn)',

                fontSize: 'var(--fs-xl)',
              }}
            >
              {number(
                stats?.new
              )}
            </b>

            <div
              style={{
                color:
                  'var(--txm)',

                fontSize: 'var(--fs-cap)',
              }}
            >
              جدید
            </div>
          </div>

          <div
            className="card"
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
              {number(
                stats?.reviewing
              )}
            </b>

            <div
              style={{
                color:
                  'var(--txm)',

                fontSize: 'var(--fs-cap)',
              }}
            >
              در بررسی
            </div>
          </div>
        </section>


        <div className="tab-bar">
          {tabs.map(
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
                {label}{' '}

                ({number(
                  stats?.[key]
                )})
              </button>
            )
          )}
        </div>


        {isLoading ? (
          <LibraryRowsSkeleton />
        ) : isError ? (
          <EmptyState>
            دریافت گزارش‌ها انجام نشد.

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
        ) : reports.length === 0 ? (
          <EmptyState>
            گزارشی در این وضعیت نیست.
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
            {reports.map((item) => (
              <article
                key={item.id}
                className="card"
              >
                <div
                  style={{
                    display:
                      'flex',

                    gap:
                      8,
                  }}
                >
                  <span
                    style={{
                      fontSize:
                        22,
                    }}
                  >
                    {item.target_type ===
                    'question'
                      ? '🧪'
                      : '📎'}
                  </span>

                  <div
                    style={{
                      flex:
                        1,
                    }}
                  >
                    <b>
                      گزارش #{item.id}
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
                      {item.reason}

                      {' • '}

                      {item.reporter_name ||
                        'ناشناس'}

                      {' • '}

                      {item.created_at ||
                        '—'}
                    </div>
                  </div>

                  <span className="badge b-gray">
                    {status}
                  </span>
                </div>

                {item.note && (
                  <div
                    style={{
                      marginTop:
                        8,

                      padding:
                        '8px 9px',

                      background:
                        'var(--soft-mut)',

                      borderRadius: 'var(--r-sm)',

                      fontSize: 'var(--fs-cap)',
                    }}
                  >
                    {item.note}
                  </div>
                )}

                <div
                  style={{
                    display:
                      'flex',

                    gap:
                      6,

                    marginTop:
                      9,
                  }}
                >
                  {status === 'new' && (
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
                          id:
                            item.id,

                          value:
                            'reviewing',
                        })
                      }
                    >
                      🔍 بررسی
                    </button>
                  )}

                  {![
                    'resolved',
                    'rejected',
                  ].includes(
                    status
                  ) && (
                    <>
                      <button
                        className="btn btn-g"
                        style={{
                          flex:
                            1,
                        }}
                        onClick={() =>
                          mutation.mutate({
                            id:
                              item.id,

                            value:
                              'resolved',
                          })
                        }
                      >
                        ✅ حل شد
                      </button>

                      <button
                        className="btn btn-d"
                        style={{
                          flex:
                            1,
                        }}
                        onClick={() =>
                          mutation.mutate({
                            id:
                              item.id,

                            value:
                              'rejected',
                          })
                        }
                      >
                        رد
                      </button>
                    </>
                  )}
                </div>
              </article>
            ))}
          </section>
        )}
      </main>
    </>
  );
}
