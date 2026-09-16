import {
  useRef,
  useState,
} from 'react';

import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import Header from '../../components/layout/Header';

import {
  Spinner,
} from '../../components/shared/Loading';

import {
  SkRowList,
} from '../../components/shared/skeletons';

import api from '../../lib/api';

import SubscriptionLock, {
  isSubscriptionLock,
  lockKind,
} from '../../components/shared/SubscriptionLock';

import ResourceAccessGate
  from '../../components/shared/ResourceAccessGate';
import PreviewModal
  from '../../components/shared/PreviewModal';

import SearchField
  from '../../components/shared/SearchField';

import {
  haptic,
  hapticNotif,
} from '../../lib/telegram';

import {
  useUIStore,
} from '../../stores/uiStore';
import { useSearchParams } from 'react-router-dom';


const TYPES = {
  video: [
    '🎬',
    'ویدیو',
    'var(--t-err)',
    'var(--soft-err)',
  ],

  ppt: [
    '📊',
    'اسلاید',
    'var(--t-warn)',
    'var(--soft-warn)',
  ],

  pdf: [
    '📄',
    'PDF',
    'var(--t-acc)',
    'var(--soft-acc)',
  ],

  note: [
    '📝',
    'جزوه',
    'var(--t-ok)',
    'var(--soft-ok)',
  ],

  test: [
    '🧪',
    'آزمون',
    'var(--t-pur)',
    'var(--soft-pur)',
  ],

  voice: [
    '🎧',
    'صوت',
    'var(--t-info)',
    'var(--soft-info)',
  ],
};


function safeArray(value) {
  return Array.isArray(value)
    ? value
    : [];
}


function errorText(
  error,
  fallback,
) {
  const detail =
    error?.response?.data?.detail;

  return (
    typeof detail === 'string'
    && detail.trim()
  )
    ? detail
    : fallback;
}


function ResourceFile({
  item,
  rowKey,
  sendingKey,
  sendDisabled,
  searchMode = false,
  onSend,
  onPreview,
}) {
  const [
    icon,
    label,
    color,
    soft,
  ] = (
    TYPES[item?.type]
    || [
      '📎',
      'فایل',
      'var(--t-acc)',
      'var(--soft-acc)',
    ]
  );

  // فقط ردیفی که واقعاً کلیک شده، لودینگ نشان می‌دهد.
  const isSending =
    sendingKey === rowKey;

  const title = (
    item?.name
    || item?.description
    || label
  );

  const context = [
    item?.lesson,
    item?.session,
  ]
    .filter(Boolean)
    .join(' • ');

  return (
    <article
      className="card"
      style={styles.fileCard}
    >
      <div
        style={{
          ...styles.fileIcon,
          color,
          background: soft,
        }}
      >
        {icon}
      </div>

      <div style={styles.fileBody}>
        <strong style={styles.fileTitle}>
          {title}
        </strong>

        <span style={styles.fileMeta}>
          {
            searchMode
              ? context || label
              : `${label} • ${
                  Number(
                    item?.downloads
                  ) || 0
                } دانلود`
          }
        </span>

        {
          item?.description
          && item.description !== title
          && (
            <p style={styles.fileDescription}>
              {item.description}
            </p>
          )
        }
      </div>

      {!!item?.preview && (
        <button
          type="button"
          className="btn sm"
          style={{ flexShrink: 0 }}
          onClick={() => onPreview(item)}
          aria-label="پیش‌نمایش فایل"
        >
          👁
        </button>
      )}

      <button
        type="button"
        className="btn btn-g"
        style={styles.sendButton}
        onClick={
          () => onSend(
            item?.id,
            rowKey,
          )
        }
        disabled={
          sendDisabled
          || !item?.id
        }
        aria-busy={isSending}
        aria-label={
          `ارسال ${title} در ربات`
        }
      >
        {
          isSending
            ? (
              <>
                <Spinner size={15} />
                ارسال...
              </>
            )
            : 'ارسال'
        }
      </button>
    </article>
  );
}


function LoadingList() {
  return (
    <div style={styles.list}>
      <SkRowList
        n={3}
        icon={46}
        lines={2}
      />
    </div>
  );
}


function EmptyState({
  icon = '📭',
  text,
}) {
  return (
    <div
      className="card empty"
      style={styles.empty}
    >
      <span style={styles.emptyIcon}>
        {icon}
      </span>

      <p>{text}</p>
    </div>
  );
}


function ResourcesPage({ hlFlash = false }) {
  const [
    view,
    setView,
  ] = useState('terms');

  const [
    term,
    setTerm,
  ] = useState(null);

  const [
    lesson,
    setLesson,
  ] = useState(null);

  const [
    session,
    setSession,
  ] = useState(null);

  const [
    search,
    setSearch,
  ] = useState('');

  const [
    sendingKey,
    setSendingKey,
  ] = useState(null);

  // این ref به‌صورت هم‌زمان تغییر می‌کند.
  // بنابراین چند لمس سریع قبل از Render بعدی هم
  // نمی‌تواند درخواست دوم بسازد.
  const sendLockRef =
    useRef(null);

  const toast =
    useUIStore(
      (state) => state.toast
    );

  const queryClient =
    useQueryClient();

  const {
    data: terms = [],
    isLoading: termsLoading,
    isError: termsError,
    error: termsErr,
    refetch: refetchTerms,
  } = useQuery({
    queryKey: [
      'resource-terms',
    ],

    queryFn: () =>
      api
        .get(
          '/api/resources/terms'
        )
        .then(
          (response) =>
            safeArray(
              response.data?.terms
            )
        ),

    staleTime:
      10 * 60 * 1000,
  });

  const {
    data: lessons = [],
    isLoading: lessonsLoading,
    isError: lessonsError,
    error: lessonsErr,
    refetch: refetchLessons,
  } = useQuery({
    queryKey: [
      'resource-lessons',
      term?.name,
    ],

    queryFn: () =>
      api
        .get(
          `/api/resources/lessons/${
            encodeURIComponent(
              term.name
            )
          }`
        )
        .then(
          (response) =>
            safeArray(
              response.data?.lessons
            )
        ),

    enabled:
      view === 'lessons'
      && Boolean(term?.name),
  });

  const {
    data: sessions = [],
    isLoading: sessionsLoading,
    isError: sessionsError,
    error: sessionsErr,
    refetch: refetchSessions,
  } = useQuery({
    queryKey: [
      'resource-sessions',
      lesson?._id,
    ],

    queryFn: () =>
      api
        .get(
          `/api/resources/sessions/${
            lesson._id
          }`
        )
        .then(
          (response) =>
            safeArray(
              response.data?.sessions
            )
        ),

    enabled:
      view === 'sessions'
      && Boolean(lesson?._id),
  });

  const {
    data: files = [],
    isLoading: filesLoading,
    isError: filesError,
    error: filesErr,
    refetch: refetchFiles,
  } = useQuery({
    queryKey: [
      'resource-files',
      session?._id,
    ],

    queryFn: () =>
      api
        .get(
          `/api/resources/files/${
            session._id
          }`
        )
        .then(
          (response) =>
            safeArray(
              response.data?.files
            )
        ),

    enabled:
      view === 'files'
      && Boolean(session?._id),
  });

  const normalizedSearch =
    search.trim();

  const {
    data: results = [],
    isFetching: searching,
    isError: searchError,
    error: searchErr,
  } = useQuery({
    queryKey: [
      'resource-search',
      normalizedSearch,
    ],

    queryFn: () =>
      api
        .get(
          '/api/resources/search',
          {
            params: {
              q: normalizedSearch,
            },
          }
        )
        .then(
          (response) =>
            safeArray(
              response.data?.results
            )
        ),

    enabled:
      normalizedSearch.length >= 2,
  });

  const downloadMutation =
    useMutation({
      mutationFn: ({
        id,
      }) =>
        api.post(
          `/api/resources/download/${id}`
        ),

      onSuccess: async (
        response
      ) => {
        hapticNotif(
          'success'
        );

        toast(
          `${
            response.data?.name
            || 'فایل'
          } در ربات ارسال شد ✅`,
          'success'
        );

        await Promise.all([
          queryClient
            .invalidateQueries({
              queryKey: [
                'resource-files',
              ],
            }),

          queryClient
            .invalidateQueries({
              queryKey: [
                'resource-search',
              ],
            }),
        ]);
      },

      onError: (error) => {
        hapticNotif(
          'error'
        );

        toast(
          errorText(
            error,
            'ارسال فایل انجام نشد'
          ),
          'error'
        );
      },

      onSettled: (
        _data,
        _error,
        variables
      ) => {
        if (
          sendLockRef.current
          === variables?.key
        ) {
          sendLockRef.current =
            null;
        }

        setSendingKey(
          (current) =>
            current === variables?.key
              ? null
              : current
        );
      },
    });

  /* 🌊 W8/UX-03 — فایل در حال پیش‌نمایش */
  const [
    previewFile,
    setPreviewFile,
  ] = useState(null);

  const sendFile = (
    id,
    key,
  ) => {
    const fileId =
      String(
        id || ''
      ).trim();

    const rowKey =
      String(
        key || ''
      ).trim();

    if (
      !fileId
      || !rowKey
      || sendLockRef.current
      || downloadMutation.isPending
    ) {
      return;
    }

    // قفل بلافاصله و قبل از mutation فعال می‌شود.
    sendLockRef.current =
      rowKey;

    // فقط کلید همین ردیف ذخیره می‌شود.
    setSendingKey(
      rowKey
    );

    haptic('medium');

    downloadMutation.mutate({
      id: fileId,
      key: rowKey,
    });
  };

  /* 🔒 گیت اشتراک — بک‌اند مرجع نهایی است.
     اگر هرکدام از کوئری‌های این صفحه 403 با
     detail='subscription_required' بگیرند (دقیقاً
     همان قانون has_access ربات)، به‌جای کارت خطای
     عمومی، صفحه‌ی قفل حرفه‌ای نمایش داده می‌شود */
  const subLock =
    isSubscriptionLock(termsErr) ||
    isSubscriptionLock(lessonsErr) ||
    isSubscriptionLock(sessionsErr) ||
    isSubscriptionLock(filesErr) ||
    isSubscriptionLock(searchErr);

  /* 🌊 W7 — خطای قفل برای mode و ایونت */
  const lockErr = [termsErr, lessonsErr, sessionsErr, filesErr, searchErr].find(isSubscriptionLock);


  const goBack = () => {
    haptic('light');

    if (view === 'files') {
      setSession(null);
      setView('sessions');

    } else if (
      view === 'sessions'
    ) {
      setLesson(null);
      setView('lessons');

    } else if (
      view === 'lessons'
    ) {
      setTerm(null);
      setView('terms');
    }
  };

  const title =
    view === 'files'
      ? (
        session?.topic
        || 'فایل‌های جلسه'
      )
      : view === 'sessions'
        ? (
          lesson?.name
          || 'جلسات درس'
        )
        : view === 'lessons'
          ? (
            term?.name
            || 'درس‌ها'
          )
          : 'منابع علوم پایه';

  const subtitle =
    view === 'terms'
      ? (
        'جزوه، ویدیو، اسلاید و فایل‌های آموزشی'
      )
      : view === 'lessons'
        ? (
          'یک درس را انتخاب کنید'
        )
        : view === 'sessions'
          ? (
            'جلسه موردنظر را انتخاب کنید'
          )
          : (
            'فقط فایل انتخاب‌شده در ربات ارسال می‌شود'
          );

  const renderError = (
    message,
    retry,
  ) => (
    <div
      className="card"
      style={styles.errorCard}
    >
      <span>⚠️</span>

      <p>{message}</p>

      <button
        type="button"
        className="btn btn-g"
        onClick={
          () => retry()
        }
      >
        تلاش دوباره
      </button>
    </div>
  );

  return (
    <>
      <Header
        title={title}
        subtitle={subtitle}
        back
        onBack={
          view !== 'terms'
            ? goBack
            : undefined
        }
      />

      <main
        className={
          hlFlash
            ? 'page fade-up hl-flash'
            : 'page fade-up'
        }
        style={styles.page}
      >
        {subLock && (
          <SubscriptionLock
            feature="منابع علوم پایه"
            featureKey="resources"
            mode={lockKind(lockErr).kind}
          />
        )}

        {
          !subLock &&
          view === 'terms'
          && (
            <>
              <section
                className="card card-glow hero-card"
                style={styles.hero}
              >
                <div
                  style={styles.heroIcon}
                >
                  📚
                </div>

                <div>
                  <strong
                    style={styles.heroTitle}
                  >
                    کتابخانه علوم پایه
                  </strong>

                  <p
                    style={styles.heroText}
                  >
                    فایل موردنظر را پیدا کنید و همان یک فایل را در ربات تحویل بگیرید.
                  </p>
                </div>
              </section>

              <SearchField
                value={search}
                onChange={
                  (event) =>
                    setSearch(
                      event.target.value
                    )
                }
                placeholder="جست‌وجوی نام درس، جلسه یا فایل..."
                maxLength={100}
                ariaLabel="جست‌وجوی منابع"
              />

              {
                normalizedSearch
                  .length >= 2
                  ? (
                    <section>
                      <div
                        className="sec-title"
                      >
                        نتیجه جست‌وجو
                      </div>

                      {
                        searching
                          ? (
                            <LoadingList />
                          )
                          : searchError
                            ? (
                              <EmptyState
                                icon="⚠️"
                                text="جست‌وجو انجام نشد؛ دوباره تلاش کنید."
                              />
                            )
                            : safeArray(
                              results
                            ).length === 0
                              ? (
                                <EmptyState
                                  icon="🔎"
                                  text="فایلی با این عبارت پیدا نشد."
                                />
                              )
                              : (
                                <div
                                  style={
                                    styles.list
                                  }
                                >
                                  {
                                    safeArray(
                                      results
                                    ).map(
                                      (
                                        item,
                                        index
                                      ) => {
                                        const rowKey =
                                          `search-${
                                            item.id
                                          }-${index}`;

                                        return (
                                          <ResourceFile
                                            key={
                                              rowKey
                                            }
                                            item={
                                              item
                                            }
                                            rowKey={
                                              rowKey
                                            }
                                            sendingKey={
                                              sendingKey
                                            }
                                            sendDisabled={
                                              downloadMutation
                                                .isPending
                                            }
                                            searchMode
                                            onSend={
                                              sendFile
                                            }
                                            onPreview={
                                              setPreviewFile
                                            }
                                          />
                                        );
                                      }
                                    )
                                  }
                                </div>
                              )
                      }
                    </section>
                  )
                  : termsLoading
                    ? (
                      <LoadingList />
                    )
                    : termsError
                      ? (
                        renderError(
                          'دریافت ترم‌ها انجام نشد.',
                          refetchTerms
                        )
                      )
                      : safeArray(
                        terms
                      ).length === 0
                        ? (
                          <EmptyState
                            text="هنوز ترمی ثبت نشده است."
                          />
                        )
                        : (
                          <section>
                            <div
                              className="sec-title"
                            >
                              انتخاب ترم
                            </div>

                            <div
                              style={
                                styles.grid
                              }
                            >
                              {
                                safeArray(
                                  terms
                                ).map(
                                  (
                                    item,
                                    index
                                  ) => (
                                    <button
                                      key={
                                        `${
                                          item.name
                                        }-${index}`
                                      }
                                      type="button"
                                      className="card card-tap"
                                      style={
                                        styles.navCard
                                      }
                                      onClick={
                                        () => {
                                          haptic(
                                            'light'
                                          );

                                          setTerm(
                                            item
                                          );

                                          setView(
                                            'lessons'
                                          );
                                        }
                                      }
                                    >
                                      <span
                                        style={
                                          styles.navIcon
                                        }
                                      >
                                        🎓
                                      </span>

                                      <strong>
                                        {
                                          item.name
                                          || 'ترم بدون نام'
                                        }
                                      </strong>

                                      <span
                                        style={
                                          styles.navMeta
                                        }
                                      >
                                        {
                                          Number(
                                            item.lesson_count
                                          ) || 0
                                        }{' '}
                                        درس
                                      </span>
                                    </button>
                                  )
                                )
                              }
                            </div>
                          </section>
                        )
              }
            </>
          )
        }

        {
          view === 'lessons'
          && (
            lessonsLoading
              ? (
                <LoadingList />
              )
              : lessonsError
                ? (
                  renderError(
                    'دریافت درس‌ها انجام نشد.',
                    refetchLessons
                  )
                )
                : safeArray(
                  lessons
                ).length === 0
                  ? (
                    <EmptyState
                      text="برای این ترم درسی ثبت نشده است."
                    />
                  )
                  : (
                    <div
                      style={styles.list}
                    >
                      {
                        safeArray(
                          lessons
                        ).map(
                          (
                            item,
                            index
                          ) => (
                            <button
                              key={
                                `${
                                  item._id
                                }-${index}`
                              }
                              type="button"
                              className="card card-tap"
                              style={
                                styles.rowCard
                              }
                              onClick={
                                () => {
                                  haptic(
                                    'light'
                                  );

                                  setLesson(
                                    item
                                  );

                                  setView(
                                    'sessions'
                                  );
                                }
                              }
                            >
                              <span
                                style={
                                  styles.rowIcon
                                }
                              >
                                📘
                              </span>

                              <span
                                style={
                                  styles.rowBody
                                }
                              >
                                <strong>
                                  {
                                    item.name
                                    || 'درس بدون نام'
                                  }
                                </strong>

                                <small>
                                  {
                                    item.teacher
                                    || 'استاد ثبت نشده'
                                  }
                                </small>
                              </span>

                              <span
                                className="badge b-acc"
                              >
                                {
                                  Number(
                                    item.session_count
                                  ) || 0
                                }{' '}
                                جلسه
                              </span>

                              <span
                                style={
                                  styles.arrow
                                }
                              >
                                ‹
                              </span>
                            </button>
                          )
                        )
                      }
                    </div>
                  )
          )
        }

        {
          view === 'sessions'
          && (
            sessionsLoading
              ? (
                <LoadingList />
              )
              : sessionsError
                ? (
                  renderError(
                    'دریافت جلسات انجام نشد.',
                    refetchSessions
                  )
                )
                : safeArray(
                  sessions
                ).length === 0
                  ? (
                    <EmptyState
                      text="برای این درس جلسه‌ای ثبت نشده است."
                    />
                  )
                  : (
                    <div
                      style={styles.list}
                    >
                      {
                        safeArray(
                          sessions
                        ).map(
                          (
                            item,
                            index
                          ) => (
                            <button
                              key={
                                `${
                                  item._id
                                }-${index}`
                              }
                              type="button"
                              className="card card-tap"
                              style={
                                styles.rowCard
                              }
                              onClick={
                                () => {
                                  haptic(
                                    'light'
                                  );

                                  setSession(
                                    item
                                  );

                                  setView(
                                    'files'
                                  );
                                }
                              }
                            >
                              <span
                                style={
                                  styles.sessionNumber
                                }
                              >
                                {
                                  Number(
                                    item.number
                                  )
                                  || index + 1
                                }
                              </span>

                              <span
                                style={
                                  styles.rowBody
                                }
                              >
                                <strong>
                                  {
                                    item.topic
                                    || `جلسه ${
                                      index + 1
                                    }`
                                  }
                                </strong>

                                <small>
                                  {
                                    item.teacher
                                    || lesson?.teacher
                                    || 'استاد ثبت نشده'
                                  }
                                </small>
                              </span>

                              <span
                                className="badge b-gray"
                              >
                                {
                                  Number(
                                    item.file_count
                                  ) || 0
                                }{' '}
                                فایل
                              </span>

                              <span
                                style={
                                  styles.arrow
                                }
                              >
                                ‹
                              </span>
                            </button>
                          )
                        )
                      }
                    </div>
                  )
          )
        }

        {
          view === 'files'
          && (
            filesLoading
              ? (
                <LoadingList />
              )
              : filesError
                ? (
                  renderError(
                    'دریافت فایل‌های جلسه انجام نشد.',
                    refetchFiles
                  )
                )
                : safeArray(
                  files
                ).length === 0
                  ? (
                    <EmptyState
                      text="برای این جلسه فایلی ثبت نشده است."
                    />
                  )
                  : (
                    <>
                      <div
                        className="sec-title"
                      >
                        فایل‌های این جلسه
                      </div>

                      <div
                        className="card"
                        style={
                          styles.notice
                        }
                      >
                        <span>ℹ️</span>

                        با زدن «ارسال»، فقط همان ردیف انتخاب‌شده در ربات فرستاده می‌شود.
                      </div>

                      <div
                        style={styles.list}
                      >
                        {
                          safeArray(
                            files
                          ).map(
                            (
                              item,
                              index
                            ) => {
                              const rowKey =
                                `file-${
                                  item.id
                                }-${index}`;

                              return (
                                <ResourceFile
                                  key={
                                    rowKey
                                  }
                                  item={
                                    item
                                  }
                                  rowKey={
                                    rowKey
                                  }
                                  sendingKey={
                                    sendingKey
                                  }
                                  sendDisabled={
                                    downloadMutation
                                      .isPending
                                  }
                                  onSend={
                                    sendFile
                                  }
                                  onPreview={
                                    setPreviewFile
                                  }
                                />
                              );
                            }
                          )
                        }
                      </div>
                    </>
                  )
          )
        }
        {previewFile && (
          <PreviewModal
            scope="resources"
            file={previewFile}
            onClose={() => setPreviewFile(null)}
          />
        )}
      </main>
    </>
  );
}


const styles = {
  page: {
    display: 'flex',
    flexDirection: 'column',
    gap: 13,
    paddingInline: 13,
  },

  /* موج ۴.۲۰ — پس‌زمینه و padding به کلاسِ
     مشترک .hero-card سپرده شد (مقادیر قبل از
     این دقیقاً همان بود؛ حالا منبع حقیقتِ
     طراحی فقط globals.css است) */
  hero: {
    display: 'flex',
    alignItems: 'center',
    gap: 13,
  },

  heroIcon: {
    display: 'grid',
    placeItems: 'center',
    flex: '0 0 52px',
    width: 52,
    height: 52,
    fontSize: 25,
    borderRadius: 'var(--r-lg)',

    background:
      'var(--grad-brand)',

    boxShadow:
      'var(--shd-glow)',
  },

  heroTitle: {
    fontSize: 'var(--fs-lg)',
  },

  heroText: {
    marginTop: 'var(--sp-1)',
    color: 'var(--tx2)',
    fontSize: 'var(--fs-cap)',
    lineHeight: 1.9,
  },

  list: {
    display: 'flex',
    flexDirection: 'column',
    gap: 9,
  },

  grid: {
    display: 'grid',

    gridTemplateColumns:
      'repeat(2,minmax(0,1fr))',

    gap: 9,
  },

  navCard: {
    display: 'flex',
    alignItems: 'center',
    flexDirection: 'column',
    gap: 6,
    minHeight: 124,
    fontFamily: 'inherit',
    cursor: 'pointer',
  },

  navIcon: {
    fontSize: 29,
  },

  navMeta: {
    color: 'var(--tx2)',
    fontSize: 'var(--fs-cap)',
  },

  rowCard: {
    display: 'flex',
    alignItems: 'center',
    width: '100%',
    gap: 'var(--sp-3)',
    fontFamily: 'inherit',
    textAlign: 'right',
    cursor: 'pointer',
  },

  rowIcon: {
    display: 'grid',
    placeItems: 'center',
    flex: '0 0 42px',
    height: 42,
    fontSize: 21,
    borderRadius: 'var(--r-md)',
    background: 'var(--acc-soft)',
  },

  sessionNumber: {
    display: 'grid',
    placeItems: 'center',
    flex: '0 0 38px',
    height: 38,
    color: 'var(--t-acc)',
    fontWeight: 900,
    borderRadius: 'var(--r-md)',
    background: 'var(--acc-soft)',
  },

  rowBody: {
    display: 'flex',
    flex: 1,
    minWidth: 0,
    flexDirection: 'column',
    gap: 3,
  },

  arrow: {
    color: 'var(--txm)',
    fontSize: 23,
  },

  fileCard: {
    display: 'flex',
    alignItems: 'center',
    gap: 'var(--sp-3)',
    padding: 11,
  },

  fileIcon: {
    display: 'grid',
    placeItems: 'center',
    flex: '0 0 43px',
    width: 43,
    height: 43,
    fontSize: 21,
    borderRadius: 'var(--r-md)',
  },

  fileBody: {
    display: 'flex',
    flex: 1,
    minWidth: 0,
    flexDirection: 'column',
    gap: 2,
  },

  fileTitle: {
    overflow: 'hidden',
    fontSize: 'var(--fs-meta)',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },

  fileMeta: {
    color: 'var(--tx2)',
    fontSize: 'var(--fs-cap)',
  },

  fileDescription: {
    marginTop: 3,
    color: 'var(--txm)',
    fontSize: 'var(--fs-cap)',
    lineHeight: 1.7,
  },

  sendButton: {
    flex: '0 0 auto',
    minWidth: 68,
    minHeight: 34,
    padding: '6px 9px',
    fontSize: 'var(--fs-cap)',
  },

  notice: {
    display: 'flex',
    alignItems: 'center',
    gap: 'var(--sp-2)',
    padding: 'var(--sp-3)',
    color: 'var(--tx2)',
    fontSize: 'var(--fs-cap)',
    lineHeight: 1.8,
  },

  empty: {
    padding: '45px 14px',
  },

  emptyIcon: {
    display: 'block',
    marginBottom: 8,
    fontSize: 31,
  },

  errorCard: {
    display: 'flex',
    alignItems: 'center',
    flexDirection: 'column',
    gap: 'var(--sp-3)',
    padding: 25,
    color: 'var(--tx2)',
    textAlign: 'center',
  },
};


/* ── دروازه‌ی اشتراک (موج ۴.۳۰) ──
   خودِ صفحه فقط برای کاربرِ دارای دسترسی
   Mount می‌شود — بدون حتی یک فریم لودینگ یا
   ریکوئستِ محتوا برای کاربرِ بدون اشتراک.
   جزئیات معماری در ResourceAccessGate */
export default function Resources() {
  /* 🧠 موج N3 — Deep Link: ?hl=new ⇒ فلش یک‌باره‌ی
     قسمت فایل‌های تازه (منابع/رفرنس‌های پرتابی) */
  const [searchParams] = useSearchParams();
  const hlFlash = searchParams.get('hl') === 'new';

  return (
    <ResourceAccessGate
      featureKey="resources"
      feature="منابع علوم پایه"
    >
      <ResourcesPage
        hlFlash={hlFlash}
      />
    </ResourceAccessGate>
  );
}
