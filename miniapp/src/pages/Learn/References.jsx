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

import ResourceAccessGate
  from '../../components/shared/ResourceAccessGate';
import PreviewModal from '../../components/shared/PreviewModal';

import SubscriptionLock, {
  isSubscriptionLock,
  lockKind,
} from '../../components/shared/SubscriptionLock';

import {
  haptic,
  hapticNotif,
} from '../../lib/telegram';

import {
  useUIStore,
} from '../../stores/uiStore';
import { useSearchParams } from 'react-router-dom';


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


function ReferenceFile({
  item,
  rowKey,
  sendingKey,
  sendDisabled,
  language,
  onSend,
  onPreview,
}) {
  // فقط همان ردیفی که روی آن کلیک شده،
  // حالت لودینگ خواهد داشت.
  const isSending =
    sendingKey === rowKey;

  const isPersian =
    language === 'fa';

  const title =
    `جلد ${
      Number(item?.volume) || 1
    }`;

  return (
    <article
      className="card"
      style={styles.fileCard}
    >
      <div
        style={{
          ...styles.fileIcon,

          color:
            isPersian
              ? 'var(--t-ok)'
              : 'var(--t-acc)',

          background:
            isPersian
              ? 'var(--soft-ok)'
              : 'var(--soft-acc)',
        }}
      >
        {
          isPersian
            ? '🇮🇷'
            : '🌐'
        }
      </div>

      <div style={styles.fileBody}>
        <strong style={styles.fileTitle}>
          {title}
        </strong>

        <span style={styles.fileMeta}>
          {
            isPersian
              ? 'ترجمه فارسی'
              : 'نسخه لاتین'
          }

          {' • '}

          {
            Number(
              item?.downloads
            ) || 0
          }

          {' دانلود'}
        </span>

        {
          item?.description
          && (
            <p style={styles.description}>
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


function ReferencesPage({ hlFlash = false }) {
  const [
    view,
    setView,
  ] = useState('subjects');

  const [
    subject,
    setSubject,
  ] = useState(null);

  const [
    book,
    setBook,
  ] = useState(null);

  const [
    language,
    setLanguage,
  ] = useState('fa');

  const [
    sendingKey,
    setSendingKey,
  ] = useState(null);

  // این قفل بلافاصله و قبل از Render بعدی تغییر می‌کند.
  // بنابراین لمس سریع و چندباره هم درخواست دوم ایجاد نمی‌کند.
  const sendLockRef =
    useRef(null);

  const toast =
    useUIStore(
      (state) => state.toast
    );

  const queryClient =
    useQueryClient();

  const {
    data: subjects = [],
    isLoading: subjectsLoading,
    isError: subjectsError,
    error: subjectsErr,
    refetch: refetchSubjects,
  } = useQuery({
    queryKey: [
      'reference-subjects',
    ],

    queryFn: () =>
      api
        .get(
          '/api/references/subjects'
        )
        .then(
          (response) =>
            safeArray(
              response.data?.subjects
            )
        ),

    staleTime:
      10 * 60 * 1000,
  });

  const {
    data: booksData,
    isLoading: booksLoading,
    isError: booksError,
    error: booksErr,
    refetch: refetchBooks,
  } = useQuery({
    queryKey: [
      'reference-books',
      subject?.id,
    ],

    queryFn: () =>
      api
        .get(
          `/api/references/books/${
            subject.id
          }`
        )
        .then(
          (response) =>
            response.data || {}
        ),

    enabled:
      view === 'books'
      && Boolean(subject?.id),
  });

  const {
    data: filesData,
    isLoading: filesLoading,
    isError: filesError,
    error: filesErr,
    refetch: refetchFiles,
  } = useQuery({
    queryKey: [
      'reference-files',
      book?.id,
    ],

    queryFn: () =>
      api
        .get(
          `/api/references/files/${
            book.id
          }`
        )
        .then(
          (response) =>
            response.data || {}
        ),

    enabled:
      view === 'files'
      && Boolean(book?.id),
  });

  const books =
    safeArray(
      booksData?.books
    );

  const faFiles =
    safeArray(
      filesData?.fa_files
    );

  const enFiles =
    safeArray(
      filesData?.en_files
    );

  const visibleFiles =
    language === 'fa'
      ? faFiles
      : enFiles;

  const downloadMutation =
    useMutation({
      mutationFn: ({
        id,
      }) =>
        api.post(
          `/api/references/download/${id}`
        ),

      onSuccess: async (
        response
      ) => {
        hapticNotif(
          'success'
        );

        toast(
          `جلد ${
            response.data?.volume
            || ''
          } در ربات ارسال شد ✅`,
          'success'
        );

        await queryClient
          .invalidateQueries({
            queryKey: [
              'reference-files',
            ],
          });
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

    // قفل قبل از شروع mutation فعال می‌شود.
    sendLockRef.current =
      rowKey;

    // فقط شناسه همان ردیف انتخاب‌شده ذخیره می‌شود.
    setSendingKey(
      rowKey
    );

    haptic('medium');

    downloadMutation.mutate({
      id: fileId,
      key: rowKey,
    });
  };

  /* 🔒 گیت اشتراک — بک‌اند مرجع نهایی است
     (همان قانون has_access ربات) */
  const subLock =
    isSubscriptionLock(subjectsErr) ||
    isSubscriptionLock(booksErr) ||
    isSubscriptionLock(filesErr);

  /* 🌊 W7 — خطای قفل برای mode و ایونت */
  const lockErr = [subjectsErr, booksErr, filesErr].find(isSubscriptionLock);


  const goBack = () => {
    haptic('light');

    if (view === 'files') {
      setBook(null);
      setLanguage('fa');
      setView('books');

    } else if (
      view === 'books'
    ) {
      setSubject(null);
      setView('subjects');
    }
  };

  const title =
    view === 'files'
      ? (
        filesData?.book?.name
        || book?.name
        || 'جلدهای کتاب'
      )
      : view === 'books'
        ? (
          booksData?.subject?.name
          || subject?.name
          || 'کتاب‌ها'
        )
        : 'رفرنس‌های درسی';

  const subtitle =
    view === 'subjects'
      ? (
        'کتاب‌های مرجع فارسی و لاتین'
      )
      : view === 'books'
        ? (
          'کتاب موردنظر را انتخاب کنید'
        )
        : (
          'فقط جلد انتخاب‌شده در ربات ارسال می‌شود'
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
          view !== 'subjects'
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
            feature="رفرنس‌های درسی"
            featureKey="references"
            mode={lockKind(lockErr).kind}
          />
        )}

        {
          !subLock &&
          view === 'subjects'
          && (
            <>
              <section
                className="card card-glow"
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
                    کتابخانه رفرنس
                  </strong>

                  <p
                    style={styles.heroText}
                  >
                    کتاب، زبان و جلد موردنظر را انتخاب کنید؛ فقط همان فایل ارسال می‌شود.
                  </p>
                </div>
              </section>

              {
                subjectsLoading
                  ? (
                    <LoadingList />
                  )
                  : subjectsError
                    ? (
                      renderError(
                        'دریافت موضوعات رفرنس انجام نشد.',
                        refetchSubjects
                      )
                    )
                    : safeArray(
                      subjects
                    ).length === 0
                      ? (
                        <EmptyState
                          text="هنوز موضوعی برای رفرنس‌ها ثبت نشده است."
                        />
                      )
                      : (
                        <section>
                          <div
                            className="sec-title"
                          >
                            دسته‌بندی رفرنس‌ها
                          </div>

                          <div
                            style={styles.grid}
                          >
                            {
                              safeArray(
                                subjects
                              ).map(
                                (
                                  item,
                                  index
                                ) => (
                                  <button
                                    key={
                                      `${
                                        item.id
                                      }-${index}`
                                    }
                                    type="button"
                                    className="card card-tap"
                                    style={
                                      styles.subjectCard
                                    }
                                    onClick={
                                      () => {
                                        haptic(
                                          'light'
                                        );

                                        setSubject(
                                          item
                                        );

                                        setView(
                                          'books'
                                        );
                                      }
                                    }
                                  >
                                    <span
                                      style={
                                        styles.subjectIcon
                                      }
                                    >
                                      📖
                                    </span>

                                    <strong
                                      style={
                                        styles.subjectName
                                      }
                                    >
                                      {
                                        item.name
                                        || 'موضوع بدون نام'
                                      }
                                    </strong>

                                    <span
                                      style={
                                        styles.subjectMeta
                                      }
                                    >
                                      {
                                        Number(
                                          item.book_count
                                        ) || 0
                                      }{' '}
                                      کتاب
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
          view === 'books'
          && (
            booksLoading
              ? (
                <LoadingList />
              )
              : booksError
                ? (
                  renderError(
                    'دریافت کتاب‌ها انجام نشد.',
                    refetchBooks
                  )
                )
                : books.length === 0
                  ? (
                    <EmptyState
                      text="برای این موضوع کتابی ثبت نشده است."
                    />
                  )
                  : (
                    <div
                      style={styles.list}
                    >
                      {
                        books.map(
                          (
                            item,
                            index
                          ) => (
                            <button
                              key={
                                `${
                                  item.id
                                }-${index}`
                              }
                              type="button"
                              className="card card-tap"
                              style={
                                styles.bookCard
                              }
                              onClick={
                                () => {
                                  haptic(
                                    'light'
                                  );

                                  setBook(
                                    item
                                  );

                                  setLanguage(
                                    Number(
                                      item.fa_count
                                    ) > 0
                                      ? 'fa'
                                      : 'en'
                                  );

                                  setView(
                                    'files'
                                  );
                                }
                              }
                            >
                              <span
                                style={
                                  styles.bookIcon
                                }
                              >
                                📘
                              </span>

                              <span
                                style={
                                  styles.bookBody
                                }
                              >
                                <strong>
                                  {
                                    item.name
                                    || 'کتاب بدون نام'
                                  }
                                </strong>

                                <small>
                                  فارسی:{' '}
                                  {
                                    Number(
                                      item.fa_count
                                    ) || 0
                                  }

                                  {' • '}

                                  لاتین:{' '}
                                  {
                                    Number(
                                      item.en_count
                                    ) || 0
                                  }
                                </small>
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
                    'دریافت جلدهای کتاب انجام نشد.',
                    refetchFiles
                  )
                )
                : (
                  <>
                    <div
                      style={
                        styles.languageTabs
                      }
                      role="tablist"
                      aria-label="زبان رفرنس"
                    >
                      <button
                        type="button"
                        role="tab"
                        aria-selected={
                          language === 'fa'
                        }
                        className={
                          language === 'fa'
                            ? 'btn btn-p'
                            : 'btn btn-dark'
                        }
                        style={
                          styles.languageButton
                        }
                        onClick={
                          () => {
                            haptic(
                              'light'
                            );

                            setLanguage(
                              'fa'
                            );
                          }
                        }
                        disabled={
                          downloadMutation
                            .isPending
                        }
                      >
                        🇮🇷 فارسی

                        <span
                          className="badge b-gray"
                        >
                          {faFiles.length}
                        </span>
                      </button>

                      <button
                        type="button"
                        role="tab"
                        aria-selected={
                          language === 'en'
                        }
                        className={
                          language === 'en'
                            ? 'btn btn-p'
                            : 'btn btn-dark'
                        }
                        style={
                          styles.languageButton
                        }
                        onClick={
                          () => {
                            haptic(
                              'light'
                            );

                            setLanguage(
                              'en'
                            );
                          }
                        }
                        disabled={
                          downloadMutation
                            .isPending
                        }
                      >
                        🌐 لاتین

                        <span
                          className="badge b-gray"
                        >
                          {enFiles.length}
                        </span>
                      </button>
                    </div>

                    <div
                      className="card"
                      style={styles.notice}
                    >
                      <span>ℹ️</span>

                      با زدن «ارسال»، فقط همان جلد انتخاب‌شده در ربات فرستاده می‌شود.
                    </div>

                    {
                      visibleFiles.length === 0
                        ? (
                          <EmptyState
                            icon="📚"
                            text={
                              language === 'fa'
                                ? 'نسخه فارسی این کتاب ثبت نشده است.'
                                : 'نسخه لاتین این کتاب ثبت نشده است.'
                            }
                          />
                        )
                        : (
                          <div
                            style={
                              styles.list
                            }
                          >
                            {
                              visibleFiles.map(
                                (
                                  item,
                                  index
                                ) => {
                                  // کلید هر ردیف مستقل است.
                                  // بنابراین Spinner فقط روی همان دکمه ظاهر می‌شود.
                                  const rowKey =
                                    `${
                                      language
                                    }-${
                                      item.id
                                    }-${index}`;

                                  return (
                                    <ReferenceFile
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
                                      language={
                                        language
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
                        )
                    }
                  </>
                )
          )
        }
        {previewFile && (
          <PreviewModal
            scope="references"
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

  hero: {
    display: 'flex',
    alignItems: 'center',
    gap: 13,
    padding: 17,

    /* موج ۳.۱۰ — سینک با دستورِ .hero-card
       (دمِ بنفشِ شاخه‌ی رفرنس حفظ شده) */
    background:
      'linear-gradient(145deg,var(--soft-acc-deep),var(--surf-card) 52%,var(--soft-pur))',
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
      'linear-gradient(135deg,var(--acc-dim),var(--acc) 55%,var(--pur))',

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

  subjectCard: {
    display: 'flex',
    alignItems: 'center',
    minHeight: 128,
    flexDirection: 'column',
    gap: 6,
    fontFamily: 'inherit',
    cursor: 'pointer',
  },

  subjectIcon: {
    fontSize: 30,
  },

  subjectName: {
    overflow: 'hidden',
    maxWidth: '100%',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },

  subjectMeta: {
    color: 'var(--tx2)',
    fontSize: 'var(--fs-cap)',
  },

  bookCard: {
    display: 'flex',
    alignItems: 'center',
    width: '100%',
    gap: 'var(--sp-3)',
    fontFamily: 'inherit',
    textAlign: 'right',
    cursor: 'pointer',
  },

  bookIcon: {
    display: 'grid',
    placeItems: 'center',
    flex: '0 0 43px',
    height: 43,
    fontSize: 22,
    borderRadius: 'var(--r-md)',

    background:
      'var(--soft-pur)',
  },

  bookBody: {
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

  languageTabs: {
    display: 'grid',

    gridTemplateColumns:
      'repeat(2,minmax(0,1fr))',

    gap: 8,
  },

  languageButton: {
    width: '100%',
    gap: 'var(--sp-2)',
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
    fontSize: 'var(--fs-meta)',
  },

  fileMeta: {
    color: 'var(--tx2)',
    fontSize: 'var(--fs-cap)',
  },

  description: {
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
export default function References() {
  /* 🧠 موج N3 — Deep Link: ?hl=new ⇒ فلش یک‌باره‌ی
     قسمت فایل‌های تازه (منابع/رفرنس‌های پرتابی) */
  const [searchParams] = useSearchParams();
  const hlFlash = searchParams.get('hl') === 'new';

  return (
    <ResourceAccessGate
      featureKey="references"
      feature="رفرنس‌های درسی"
    >
      <ReferencesPage
        hlFlash={hlFlash}
      />
    </ResourceAccessGate>
  );
}
