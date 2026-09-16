import { confirmAction } from '../../lib/confirm';
import { useState, useEffect } from 'react';
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
  GradesAdminSkeleton,
} from '../../components/shared/skeletons';
import {
  haptic,
  hapticNotif,
} from '../../lib/telegram';
import { useUIStore } from '../../stores/uiStore';

const EMPTY_EXAM = {
  lesson: '',
  exam_title: '',
  exam_date: '',
  // 🛡 §۸۲-ج — ترمِ صریح و الزامی؛ هر ترم جدا (بدون «بدون ترم»).
  term: '',
};

const validScore = (value) => {
  if (value === '') {
    return false;
  }

  const number = Number(value);

  return (
    Number.isFinite(number) &&
    number >= 0 &&
    number <= 20
  );
};

const apiError = (
  error,
  fallback
) => {
  const detail =
    error?.response?.data?.detail;

  if (typeof detail === 'string') {
    return detail;
  }

  if (
    Array.isArray(detail) &&
    detail[0]?.msg
  ) {
    return detail[0].msg;
  }

  return fallback;
};

export default function AcademicGradesAdmin() {
  const [view, setView] =
    useState('list');

  const [exam, setExam] =
    useState(EMPTY_EXAM);

  const [search, setSearch] =
    useState('');

  // 🛡 AUDIT-§۸۲ — فیلتر ترم در پنل ادمینِ مینی‌اپ.
  // خالی = همه‌ی ترم‌ها (رفتار قبلی، بدون تغییر).
  const [termFilter, setTermFilter] =
    useState('');

  const [entries, setEntries] =
    useState([]);

  const [editing, setEditing] =
    useState(null);

  const toast = useUIStore(
    (state) => state.toast
  );

  const queryClient =
    useQueryClient();

  const {
    data,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: [
      'academic-grades',
      termFilter,
    ],

    queryFn: () =>
      api
        .get(
          '/api/academic-admin/grades/recent',
          {
            params: {
              limit: 100,

              // ترمِ خالی اصلاً فرستاده نمی‌شود تا قرارداد قبلی
              // (بدون فیلتر) دست‌نخورده بماند.
              ...(termFilter
                ? { term: termFilter }
                : {}),
            },
          }
        )
        .then(
          (response) =>
            response.data
        ),

    enabled: view === 'list',

    // موقع تعویض ترم لیست خالی-و-پُر نشود.
    keepPreviousData: true,
  });

  // 🛡 §۸۲-ب — گزینه‌های ترم برای فرمِ ثبت.
  // جدا از data?.terms است: آن فقط ترم‌هایی را دارد که *از قبل* نمره دارند،
  // پس ترمِ تازه هرگز قابل انتخاب نمی‌شد. این مسیر ترم‌های تعریف‌شده را هم
  // برمی‌گرداند. فقط وقتی فرم باز است fetch می‌شود.
  const { data: termOptionsData } = useQuery({
    queryKey: [
      'academic-grade-term-options',
    ],

    queryFn: () =>
      api
        .get(
          '/api/academic-admin/grades/term-options'
        )
        .then(
          (response) =>
            response.data?.terms || []
        ),

    enabled: view === 'bulk',

    staleTime: 300_000,
  });

  const entryTermOptions = Array.isArray(
    termOptionsData
  )
    ? termOptionsData
    : [];

  // 🛡 §۸۲-ج — حدس ترم از روی درس برای پرکردن خودکار منوی ترم (اما ثبت همچنان ترم صریح می‌خواهد)
  const [
    suggestedTerm,
    setSuggestedTerm,
  ] = useState('');

  useEffect(() => {
    const name = exam.lesson.trim();
    if (!name || name.length < 2 || exam.term) {
      setSuggestedTerm('');
      return;
    }
    let cancelled = false;
    const t = setTimeout(() => {
      api
        .get('/api/academic-admin/grades/lesson-term', {
          params: { lesson: name },
        })
        .then((res) => {
          if (!cancelled) setSuggestedTerm(res.data?.term || '');
        })
        .catch(() => {
          if (!cancelled) setSuggestedTerm('');
        });
    }, 450);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [exam.lesson, exam.term]);

  useEffect(() => {
    if (suggestedTerm && !exam.term) {
      setExam((cur) => ({ ...cur, term: suggestedTerm }));
    }
  }, [suggestedTerm]);

  const {
    data: searchResults,
    isFetching: searching,
  } = useQuery({
    queryKey: [
      'academic-grade-students',
      search,
    ],

    queryFn: () =>
      api
        .get(
          '/api/academic-admin/grades/find-student',
          {
            params: {
              query: search.trim(),
            },
          }
        )
        .then(
          (response) =>
            response.data
              ?.students || []
        ),

    enabled:
      view === 'bulk' &&
      search.trim().length >= 2,

    staleTime: 30_000,
  });

  // invalidate روی prefix عمل می‌کند، پس همه‌ی ترم‌ها تازه می‌شوند —
  // نه فقط ترمی که همین حالا باز است (وگرنه بعد از ثبت/حذف، ترم‌های
  // دیگر داده‌ی کهنه نشان می‌دادند).
  const refresh = () =>
    queryClient.invalidateQueries({
      queryKey: [
        'academic-grades',
      ],
    });

  const bulkMutation = useMutation({
    mutationFn: () =>
      api.post(
        '/api/academic-admin/grades/bulk',
        {
          lesson:
            exam.lesson.trim(),

          exam_title:
            exam.exam_title.trim(),

          exam_date:
            exam.exam_date,

          // 🛡 §۸۲-ج — ترم الزامی است؛ سرور بدون ترم ۴۲۲ می‌دهد.
          term: exam.term.trim(),

          entries: entries.map(
            (entry) => ({
              user_id:
                entry.user_id,

              score:
                Number(
                  entry.score
                ),
            })
          ),
        }
      ),

    onSuccess: async (
      response
    ) => {
      hapticNotif('success');

      toast(
        `${
          response.data?.updated || 0
        } نمره ثبت شد ✅`,
        'success'
      );

      setEntries([]);
      setExam(EMPTY_EXAM);
      setSearch('');
      setView('list');

      await refresh();
    },

    onError: (error) => {
      hapticNotif('error');

      toast(
        apiError(
          error,
          'ثبت نمرات انجام نشد'
        ),
        'error'
      );
    },
  });

  const editMutation = useMutation({
    mutationFn: () =>
      api.patch(
        `/api/academic-admin/grades/${editing.id}`,
        {
          score: Number(
            editing.score
          ),
        }
      ),

    onSuccess: async () => {
      hapticNotif('success');

      toast(
        'نمره ویرایش شد ✅',
        'success'
      );

      setEditing(null);

      await refresh();
    },

    onError: (error) =>
      toast(
        apiError(
          error,
          'ویرایش انجام نشد'
        ),
        'error'
      ),
  });

  const deleteMutation =
    useMutation({
      mutationFn: (id) =>
        api.delete(
          `/api/academic-admin/grades/${id}`
        ),

      onSuccess: async () => {
        toast(
          'نمره حذف شد',
          'info'
        );

        await refresh();
      },

      onError: (error) =>
        toast(
          apiError(
            error,
            'حذف انجام نشد'
          ),
          'error'
        ),
    });

  const students = Array.isArray(
    searchResults
  )
    ? searchResults
    : [];

  const grades = Array.isArray(
    data?.grades
  )
    ? data.grades
    : [];

  // فهرست ترم‌ها از سرور و *فیلترنشده* می‌آید تا با انتخاب یک ترم،
  // بقیه‌ی چیپ‌ها ناپدید نشوند و راه برگشت بسته نشود.
  const termOptions = Array.isArray(
    data?.terms
  )
    ? data.terms
    : [];

  const termCounts = Array.isArray(
    data?.by_term
  )
    ? data.by_term
    : [];

  const canSubmit =
    exam.lesson.trim().length >= 2 &&
    exam.exam_title.trim().length >=
      2 &&
    /^\d{4}-\d{2}-\d{2}$/.test(
      exam.exam_date
    ) &&
    !!exam.term.trim() &&
    entries.length > 0 &&
    entries.every(
      (entry) =>
        validScore(entry.score)
    );

  const addStudent = (student) => {
    const alreadyExists =
      entries.some(
        (entry) =>
          entry.user_id === student.id
      );

    if (alreadyExists) {
      toast(
        'این دانشجو قبلاً اضافه شده است',
        'info'
      );

      return;
    }

    haptic();

    setEntries(
      (current) => [
        ...current,

        {
          user_id:
            student.id,

          name:
            student.name ||
            `#${student.id}`,

          student_id:
            student.student_id ||
            '',

          score:
            '',
        },
      ]
    );

    setSearch('');
  };

  if (view === 'bulk') {
    return (
      <>
        <Header
          title="📊 ثبت دسته‌ای نمرات"
          onBack={() =>
            setView('list')
          }
        />

        <div className="page fade-up">
          <div
            className="card card-glow"
            style={{
              marginBottom: 12,
            }}
          >
            <div className="sec-title">
              📝 اطلاعات امتحان
            </div>

            <label
              style={{
                display: 'block',
                fontSize: 'var(--fs-meta)',
                color: 'var(--txm)',
                marginBottom: 5,
              }}
            >
              نام درس *
            </label>

            <input
              className="inp"
              maxLength={100}
              value={exam.lesson}
              onChange={(event) =>
                setExam({
                  ...exam,

                  lesson:
                    event.target
                      .value,
                })
              }
              placeholder="مثلاً فیزیولوژی"
              style={{
                marginBottom: 9,
              }}
            />

            <label
              style={{
                display: 'block',
                fontSize: 'var(--fs-meta)',
                color: 'var(--txm)',
                marginBottom: 5,
              }}
            >
              عنوان امتحان *
            </label>

            <input
              className="inp"
              maxLength={100}
              value={
                exam.exam_title
              }
              onChange={(event) =>
                setExam({
                  ...exam,

                  exam_title:
                    event.target
                      .value,
                })
              }
              placeholder="مثلاً میان‌ترم"
              style={{
                marginBottom: 9,
              }}
            />

            <label
              style={{
                display: 'block',
                fontSize: 'var(--fs-meta)',
                color: 'var(--txm)',
                marginBottom: 5,
              }}
            >
              تاریخ امتحان *
            </label>

            <input
              className="inp"
              type="date"
              value={
                exam.exam_date
              }
              onChange={(event) =>
                setExam({
                  ...exam,

                  exam_date:
                    event.target
                      .value,
                })
              }
            />

            <label
              style={{
                display: 'block',
                fontSize: 'var(--fs-meta)',
                color: 'var(--txm)',
                marginBottom: 5,
                marginTop: 10,
              }}
            >
              ترم * <span style={{ color: 'var(--c-err, #e11)' }}>(الزامی — هر ترم جدا)</span>
            </label>

            <select
              className="inp"
              aria-label="ترم نمره"
              value={exam.term}
              onChange={(event) =>
                setExam({
                  ...exam,

                  term: event.target
                    .value,
                })
              }
              style={{
                borderColor: !exam.term ? 'var(--c-err, #e11)' : undefined,
                background: !exam.term ? 'var(--bg-warn, var(--card))' : undefined,
              }}
            >
              <option value="" disabled>
                — ترم را انتخاب کنید * —
              </option>

              {entryTermOptions.map(
                (item) => (
                  <option
                    key={item}
                    value={item}
                  >
                    {item}
                    {suggestedTerm === item
                      ? ' (پیشنهادی)'
                      : ''}
                  </option>
                )
              )}
            </select>

            {suggestedTerm &&
              exam.term === suggestedTerm && (
                <div
                  style={{
                    fontSize: 'var(--fs-meta)',
                    color: 'var(--c-ok, #0a7)',
                    marginTop: 5,
                  }}
                >
                  ✓ ترم پیشنهادی از روی درس: {suggestedTerm} — قابل تغییر دستی
                </div>
              )}

            {!exam.term && (
              <div
                style={{
                  fontSize: 'var(--fs-meta)',
                  color: 'var(--c-err, #e11)',
                  marginTop: 5,
                }}
              >
                ⚠️ ترم الزامی است — بدون انتخاب ترم ثبت انجام نمی‌شود.
              </div>
            )}

            <div
              style={{
                fontSize: 'var(--fs-meta)',
                color: 'var(--txm)',
                marginTop: 6,
                background: 'var(--soft-purple, var(--bg))',
                border: '1px solid var(--bd)',
                borderRadius: 8,
                padding: '7px 8px',
                lineHeight: 1.7,
              }}
            >
              🎓 هر درس به یک ترم متصل است و کارنامه‌ی
              دانشجو <b>هر ترم را جدا</b> با میانگین جدا
              نشان می‌دهد. ترم را دقیق انتخاب کنید تا
              نمرات «بدون ترم» تولید نشود.
            </div>
          </div>

          <div
            className="card"
            style={{
              marginBottom: 12,
            }}
          >
            <div className="sec-title">
              👤 افزودن دانشجو
            </div>

            <input
              className="inp"
              value={search}
              onChange={(event) =>
                setSearch(
                  event.target.value
                )
              }
              placeholder={
                'نام، شماره دانشجویی، ' +
                'یوزرنیم یا آیدی...'
              }
            />

            {searching && (
              <div
                style={{
                  display: 'flex',
                  justifyContent:
                    'center',
                  padding: 12,
                }}
              >
                <Spinner size={18} />
              </div>
            )}

            {!searching &&
              search.trim().length >=
                2 &&
              students.length === 0 && (
                <div
                  style={{
                    color:
                      'var(--txm)',
                    fontSize: 'var(--fs-meta)',
                    padding:
                      '10px 2px',
                  }}
                >
                  دانشجویی پیدا نشد.
                </div>
              )}

            {students.length > 0 && (
              <div
                style={{
                  maxHeight: 210,
                  overflowY: 'auto',
                  marginTop: 8,
                }}
              >
                {students.map(
                  (student) => (
                    <button
                      key={student.id}
                      className="menu-row"
                      style={{
                        width: '100%',
                      }}
                      onClick={() =>
                        addStudent(
                          student
                        )
                      }
                    >
                      <span
                        style={{
                          flex: 1,
                          textAlign:
                            'right',
                        }}
                      >
                        <b>
                          {student.name ||
                            `#${student.id}`}
                        </b>

                        <span
                          style={{
                            display:
                              'block',

                            color:
                              'var(--txm)',

                            fontSize: 'var(--fs-cap)',

                            marginTop: 2,
                          }}
                        >
                          {student
                            .student_id ||
                            'بدون شماره دانشجویی'}

                          {' • گروه '}

                          {student.group ||
                            '—'}

                          {' • ورودی '}

                          {student.intake ||
                            '—'}
                        </span>
                      </span>

                      <span>＋</span>
                    </button>
                  )
                )}
              </div>
            )}
          </div>

          {entries.length > 0 && (
            <div
              className="card"
              style={{
                marginBottom: 12,
              }}
            >
              <div className="sec-title">
                🎯 نمرات (
                {entries.length} نفر)
              </div>

              {entries.map(
                (entry, index) => (
                  <div
                    key={
                      entry.user_id
                    }
                    style={{
                      display: 'flex',
                      alignItems:
                        'center',
                      gap: 8,
                      marginBottom: 9,
                    }}
                  >
                    <div
                      style={{
                        flex: 1,
                        minWidth: 0,
                      }}
                    >
                      <div
                        style={{
                          fontSize: 'var(--fs-sm)',

                          fontWeight:
                            600,
                        }}
                      >
                        {entry.name}
                      </div>

                      {entry.student_id && (
                        <div
                          style={{
                            fontSize: 'var(--fs-cap)',

                            color:
                              'var(--txm)',
                          }}
                        >
                          {
                            entry.student_id
                          }
                        </div>
                      )}
                    </div>

                    <input
                      className="inp"
                      type="number"
                      min="0"
                      max="20"
                      step="0.01"
                      inputMode="decimal"
                      value={entry.score}
                      onChange={(
                        event
                      ) =>
                        setEntries(
                          (
                            current
                          ) =>
                            current.map(
                              (
                                item,
                                itemIndex
                              ) =>
                                itemIndex ===
                                index
                                  ? {
                                      ...item,

                                      score:
                                        event
                                          .target
                                          .value,
                                    }
                                  : item
                            )
                        )
                      }
                      placeholder="۰ تا ۲۰"
                      style={{
                        width: 90,

                        borderColor:
                          entry.score !==
                            '' &&
                          !validScore(
                            entry.score
                          )
                            ? 'var(--err)'
                            : undefined,
                      }}
                    />

                    <button
                      onClick={() =>
                        setEntries(
                          (
                            current
                          ) =>
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
                      aria-label={
                        'حذف دانشجو'
                      }
                      style={{
                        background:
                          'none',

                        border:
                          'none',

                        color:
                          'var(--err)',

                        cursor:
                          'pointer',

                        fontSize: 'var(--fs-lg)',
                      }}
                    >
                      🗑
                    </button>
                  </div>
                )
              )}
            </div>
          )}

          <button
            className="btn btn-p btn-full"
            disabled={
              !canSubmit ||
              bulkMutation.isPending
            }
            onClick={() =>
              bulkMutation.mutate()
            }
          >
            {bulkMutation.isPending ? (
              <Spinner size={16} />
            ) : (
              `💾 ثبت ${entries.length} نمره`
            )}
          </button>
        </div>
      </>
    );
  }

  return (
    <>
      <Header
        title="📊 مدیریت نمرات"
        subtitle={`${
          Number(data?.total) || 0
        } نمره ثبت‌شده`}
      />

      <div className="page fade-up">
        <button
          className="btn btn-p btn-full"
          style={{
            marginBottom: 'var(--sp-4)',
          }}
          onClick={() => {
            haptic();
            setView('bulk');
          }}
        >
          + ثبت دسته‌ای نمرات
        </button>

        {termOptions.length > 0 && (
          <div
            className="tab-bar"
            role="tablist"
            aria-label="فیلتر ترم"
            style={{
              marginBottom: 'var(--sp-4)',
            }}
          >
            <button
              type="button"
              role="tab"
              aria-selected={!termFilter}
              className={`tab-btn${
                termFilter ? '' : ' active'
              }`}
              onClick={() => {
                haptic('light');
                setTermFilter('');
              }}
            >
              همه
            </button>

            {termOptions.map((item) => {
              const stat = termCounts.find(
                (row) => row.term === item
              );

              return (
                <button
                  key={item}
                  type="button"
                  role="tab"
                  aria-selected={
                    termFilter === item
                  }
                  className={`tab-btn${
                    termFilter === item
                      ? ' active'
                      : ''
                  }`}
                  onClick={() => {
                    haptic('light');
                    setTermFilter(item);
                  }}
                >
                  {item}

                  {stat?.avg != null
                    ? ` · ${stat.avg}`
                    : ''}
                </button>
              );
            })}
          </div>
        )}

        {isLoading ? (
          <GradesAdminSkeleton />
        ) : isError ? (
          <PageError
            text="دریافت نمرات انجام نشد."
            onRetry={() => refetch()}
          />
        ) : grades.length === 0 ? (
          <EmptyState icon="📭">
            {termFilter
              ? `برای «${termFilter}» نمره‌ای ثبت نشده است. ترم دیگری را انتخاب کنید.`
              : 'هنوز نمره‌ای ثبت نشده است.'}
          </EmptyState>
        ) : (
          grades.map((grade) => (
            <div
              key={grade.id}
              className="card"
              style={{
                marginBottom: 9,
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent:
                    'space-between',
                  gap: 'var(--sp-3)',
                  alignItems:
                    'flex-start',
                }}
              >
                <div
                  style={{
                    flex: 1,
                  }}
                >
                  <div
                    style={{
                      fontWeight: 700,
                    }}
                  >
                    {grade
                      .student_name ||
                      `#${grade.student_id}`}
                  </div>

                  <div
                    style={{
                      color:
                        'var(--txm)',

                      fontSize: 'var(--fs-meta)',

                      marginTop: 3,
                    }}
                  >
                    {grade.lesson ||
                      'درس'}

                    {' — '}

                    {grade.exam_title ||
                      'امتحان'}

                    {' • '}

                    {grade.exam_date ||
                      '—'}

                    {grade.term
                      ? ` • 🎓 ${grade.term}`
                      : ''}
                  </div>
                </div>

                {editing?.id ===
                grade.id ? (
                  <div
                    style={{
                      display:
                        'flex',
                      gap: 5,
                      alignItems:
                        'center',
                    }}
                  >
                    <input
                      className="inp"
                      type="number"
                      min="0"
                      max="20"
                      step="0.01"
                      value={
                        editing.score
                      }
                      onChange={(
                        event
                      ) =>
                        setEditing({
                          ...editing,

                          score:
                            event
                              .target
                              .value,
                        })
                      }
                      style={{
                        width: 76,
                      }}
                      autoFocus
                    />

                    <button
                      className="btn btn-p"
                      style={{
                        padding:
                          '6px 8px',
                      }}
                      disabled={
                        !validScore(
                          editing.score
                        ) ||
                        editMutation
                          .isPending
                      }
                      onClick={() =>
                        editMutation.mutate()
                      }
                    >
                      ✓
                    </button>

                    <button
                      className="btn btn-dark"
                      style={{
                        padding:
                          '6px 8px',
                      }}
                      onClick={() =>
                        setEditing(null)
                      }
                    >
                      ✕
                    </button>
                  </div>
                ) : (
                  <div
                    style={{
                      textAlign:
                        'center',
                    }}
                  >
                    <div
                      style={{
                        fontSize: 'var(--fs-xl)',

                        fontWeight:
                          800,

                        color:
                          'var(--acc)',
                      }}
                    >
                      {grade.score ??
                        '—'}{' '}
                      /{' '}
                      {grade.max_score ||
                        20}
                    </div>

                    <div
                      style={{
                        fontSize: 'var(--fs-cap)',

                        color:
                          'var(--txm)',
                      }}
                    >
                      {grade.percentage ??
                        0}
                      ٪
                    </div>
                  </div>
                )}
              </div>

              {editing?.id !==
                grade.id && (
                <div
                  style={{
                    display: 'flex',
                    gap: 'var(--sp-2)',
                    marginTop: 'var(--sp-3)',
                  }}
                >
                  <button
                    className="btn btn-dark"
                    style={{
                      flex: 1,
                      fontSize: 'var(--fs-meta)',
                    }}
                    onClick={() =>
                      setEditing({
                        id: grade.id,

                        score:
                          grade.score ??
                          '',
                      })
                    }
                  >
                    ✏️ ویرایش
                  </button>

                  <button
                    className="btn btn-d"
                    style={{
                      flex: 1,
                      fontSize: 'var(--fs-meta)',
                    }}
                    disabled={
                      deleteMutation
                        .isPending
                    }
                    onClick={async () => {
                      const confirmed =
                        await confirmAction(
                          'این نمره حذف شود؟'
                        );

                      if (confirmed) {
                        deleteMutation.mutate(
                          grade.id
                        );
                      }
                    }}
                  >
                    🗑 حذف
                  </button>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </>
  );
}
