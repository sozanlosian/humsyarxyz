import PageError from '../../components/shared/PageError';
import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import api from '../../lib/api';
import Header from '../../components/layout/Header';

import {
  GradesSkeleton,
  Spinner,
} from '../../components/shared/Loading';

import { haptic } from '../../lib/telegram';


const finite = (value) => {
  if (
    value === null ||
    value === undefined ||
    value === ''
  ) {
    return null;
  }

  const parsed = Number(value);

  return Number.isFinite(parsed)
    ? parsed
    : null;
};


const percentage = (value) => {
  const parsed = finite(value);

  if (parsed === null) {
    return null;
  }

  return Math.max(
    0,
    Math.min(
      100,
      parsed
    )
  );
};


const visual = (value) => {
  const safe =
    percentage(value);

  if (safe === null) {
    return {
      color: 'var(--txm)',

      soft:
        'var(--soft-mut)',

      label:
        'در انتظار',

      icon:
        '⏳',
    };
  }

  if (safe >= 85) {
    return {
      color:
        'var(--t-ok)',

      soft:
        'var(--soft-ok)',

      label:
        'عالی',

      icon:
        '🌟',
    };
  }

  if (safe >= 70) {
    return {
      color:
        'var(--t-acc)',

      soft:
        'var(--soft-acc)',

      label:
        'خوب',

      icon:
        '👍',
    };
  }

  if (safe >= 50) {
    return {
      color:
        'var(--t-warn)',

      soft:
        'var(--soft-warn)',

      label:
        'متوسط',

      icon:
        '📖',
    };
  }

  return {
    color:
      'var(--t-err)',

    soft:
      'var(--soft-err)',

    label:
      'نیازمند تلاش',

    icon:
      '💪',
  };
};


function GradeRow({
  grade,
  index,
  flash,
}) {
  const score =
    finite(grade.score);

  const maxScore =
    finite(
      grade.max_score
    ) || 20;

  const value =
    percentage(
      grade.percentage ??
      (
        score === null
          ? null
          : (
              score /
              maxScore
            ) * 100
      )
    );

  const style =
    visual(value);

  return (
    <article
      data-gidx={index}
      className={
        flash
          ? 'card pop-in hl-flash'
          : 'card pop-in'
      }
      style={{
        padding: 13,

        animationDelay:
          `${
            Math.min(
              index,
              8
            ) * 35
          }ms`,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 11,
        }}
      >
        <div
          style={{
            display: 'grid',

            flex:
              '0 0 54px',

            height:
              54,

            placeItems:
              'center',

            borderRadius: 'var(--r-lg)',

            background:
              style.soft,

            border:
              `1px solid ${style.soft}`,

            textAlign:
              'center',
          }}
        >
          <div>
            <div
              style={{
                color:
                  style.color,

                fontSize: 'var(--fs-xl)',

                fontWeight:
                  900,

                lineHeight:
                  1.1,
              }}
            >
              {score ?? '—'}
            </div>

            <div
              style={{
                color:
                  'var(--txm)',

                fontSize: 'var(--fs-cap)',

                marginTop:
                  2,
              }}
            >
              از {maxScore}
            </div>
          </div>
        </div>

        <div
          style={{
            flex: 1,
            minWidth: 0,
          }}
        >
          <h3
            style={{
              overflow:
                'hidden',

              fontSize: 'var(--fs-md)',

              fontWeight:
                850,

              textOverflow:
                'ellipsis',

              whiteSpace:
                'nowrap',
            }}
          >
            {grade.lesson ||
              'درس بدون عنوان'}
          </h3>

          <div
            style={{
              color:
                'var(--tx2)',

              fontSize: 'var(--fs-cap)',

              marginTop:
                3,
            }}
          >
            {grade.exam_title ||
              'امتحان'}
          </div>

          <div
            style={{
              color:
                'var(--txm)',

              fontSize: 'var(--fs-cap)',

              marginTop:
                3,
            }}
          >
            📆{' '}

            {grade.exam_date ||
              'تاریخ نامشخص'}
          </div>
        </div>

        <div
          style={{
            textAlign:
              'center',
          }}
        >
          <div
            style={{
              fontSize: 'var(--fs-xl)',
            }}
          >
            {style.icon}
          </div>

          <span
            style={{
              color:
                style.color,

              fontSize: 'var(--fs-cap)',

              fontWeight:
                800,
            }}
          >
            {style.label}
          </span>
        </div>
      </div>

      <div
        style={{
          marginTop:
            11,
        }}
      >
        <div
          style={{
            display:
              'flex',

            justifyContent:
              'space-between',

            marginBottom:
              5,
          }}
        >
          <span
            style={{
              color:
                'var(--txm)',

              fontSize: 'var(--fs-cap)',
            }}
          >
            درصد کسب‌شده
          </span>

          <span
            style={{
              color:
                style.color,

              fontSize: 'var(--fs-cap)',

              fontWeight:
                800,
            }}
          >
            {value ?? 0}٪
          </span>
        </div>

        <div className="pbar">
          <div
            className="pbar-f"
            style={{
              width:
                `${value ?? 0}%`,

              background:
                style.color,
            }}
          />
        </div>
      </div>

      {grade.note && (
        <div
          style={{
            marginTop:
              9,

            padding:
              '8px 10px',

            color:
              'var(--tx2)',

            background:
              'var(--soft-mut)',

            borderRadius: 'var(--r-md)',

            fontSize: 'var(--fs-cap)',

            lineHeight:
              1.7,
          }}
        >
          📝 {grade.note}
        </div>
      )}
    </article>
  );
}


/* 🎓 ترم‌بندی — نوارِ انتخاب ترم با طبقه‌بندیِ جدا و میانگین هر ترم.
   کارنامه پیش‌تر همه‌ی ترم‌ها را در یک لیستِ صاف نشان می‌داد و «میانگین»
   یعنی میانگینِ درس‌های ترم ۱ تا ۴ با هم؛ عددی که هیچ معنای تحصیلی ندارد.
   حالا ترم واحدِ اصلیِ کارنامه است و هر تب میانگین همان ترم را نشان می‌دهد. */
function TermTabs({ terms, active, onPick, byTerm = [] }) {
  if (!terms.length) return null;
  const meta = new Map(byTerm.map((t) => [t.term || '', t]));
  const items = [['', 'همه'], ...terms.map((t) => [t, t])];
  return (
    <div
      className="tab-bar"
      role="tablist"
      aria-label="انتخاب ترم — هر ترم جدا"
    >
      {items.map(([value, label]) => {
        const on = active === value;
        const stat = meta.get(value || '');
        const sub = value === '' ? '' : stat?.avg != null ? ` · ${stat.avg}` : '';
        return (
          <button
            key={value || 'all'}
            type="button"
            role="tab"
            aria-selected={on}
            className={
              'tab-btn' + (on ? ' on' : '')
            }
            style={
              on
                ? {
                    background:
                      'var(--ovr)',

                    color:
                      'var(--tx)',
                  }
                : undefined
            }
            onClick={() => {
              if (on) return;
              haptic('light');
              onPick(value);
            }}
          >
            {label}{sub}
          </button>
        );
      })}
    </div>
  );
}


export default function Grades() {
  const [searchParams, setSearchParams] =
    useSearchParams();

  // ترمِ فعال در URL نگه داشته می‌شود تا back/deep-link و رفرش، انتخاب
  // کاربر را از دست ندهند (همان الگوی `hl` که این صفحه از قبل داشت).
  const activeTerm =
    searchParams.get('term') || '';

  const {
    data,
    isLoading,
    isError,
    refetch,
    isRefetching,
  } = useQuery({
    // ترم بخشی از کلید است، وگرنه react-query پاسخِ ترمِ قبلی را
    // برای ترمِ جدید برمی‌گرداند.
    queryKey: [
      'grades',
      activeTerm,
    ],

    queryFn: () =>
      api
        .get('/api/grades', {
          params: activeTerm
            ? { term: activeTerm }
            : undefined,
        })
        .then(
          (response) =>
            response.data
        ),

    // داده‌ی ترمِ قبلی تا رسیدنِ پاسخِ جدید نگه داشته می‌شود تا لیست
    // موقع سوییچ‌کردنِ تب پرش نکند.
    keepPreviousData: true,

    staleTime:
      5 * 60 * 1000,
  });

  const pickTerm = (value) => {
    const next = new URLSearchParams(
      searchParams
    );
    if (value) next.set('term', value);
    else next.delete('term');
    // انتخاب ترم نباید یک ورودیِ جدید در history بسازد.
    setSearchParams(next, {
      replace: true,
    });
  };

  const allTerms = Array.isArray(
    data?.all_terms
  )
    ? data.all_terms
    : [];

  const byTerm = Array.isArray(
    data?.by_term
  )
    ? data.by_term
    : [];


  const grades =
    Array.isArray(
      data?.grades
    )
      ? data.grades
      : [];

  /* 🧠 موج N3 — Deep Link برنامه/نمرات:
     /grades?hl=<درس> ⇒ اسکرول + فلش روی نمره‌ی همان درس */
  const [flashIdx, setFlashIdx] = useState(-1);
  const hlDone = useRef(false);

  useEffect(() => {
    if (hlDone.current || !grades.length) return;

    const hl = searchParams.get('hl');
    if (!hl) return;

    const match = grades.findIndex(
      (g) =>
        (g.lesson || '') === hl ||
        (g.lesson || '').includes(hl)
    );

    if (match < 0) return;

    hlDone.current = true;
    setFlashIdx(match);

    const el = document.querySelector(
      `[data-gidx="${match}"]`
    );

    if (el) {
      setTimeout(() => {
        el.scrollIntoView({
          behavior: 'smooth',
          block: 'center',
        });
      }, 60);

      setTimeout(() => setFlashIdx(-1), 3200);
    }
  }, [grades, searchParams]);


  const average =
    finite(data?.avg);


  const averagePercent =
    percentage(
      data?.avg_percentage ??
      (
        average === null
          ? null
          : (
              average /
              20
            ) * 100
      )
    );


  const averageStyle =
    visual(
      averagePercent
    );


  const totalValue =
    Number(data?.total);


  const total =
    Number.isFinite(
      totalValue
    )
      ? Math.max(
          0,
          totalValue
        )
      : grades.length;


  const countValue =
    Number(
      data?.graded_count
    );


  const graded =
    Number.isFinite(
      countValue
    )
      ? Math.max(
          0,
          countValue
        )
      : grades.filter(
          (item) =>
            finite(
              item?.score
            ) !== null
        ).length;


  const passed =
    grades.filter(
      (item) =>
        (
          percentage(
            item.percentage
          ) || 0
        ) >= 50
    ).length;


  /* گروه‌بندیِ نمرات برای نمایش: وقتی «همه» انتخاب است هر ترم بلوکِ
     خودش را با میانگینِ خودش دارد؛ وقتی یک ترم انتخاب شده فقط همان بلوک.
     میانگینِ هر بلوک از `by_term` سرور می‌آید (همان فرمولی که ربات و پنل
     استفاده می‌کنند) تا سه جا سه عدد متفاوت نگویند. */
  const termGroups = (() => {
    const meta = new Map(
      byTerm.map((t) => [
        t.term || '',
        t,
      ])
    );

    const buckets = new Map();
    grades.forEach((g) => {
      const key = String(
        g?.term || ''
      );
      if (!buckets.has(key))
        buckets.set(key, []);
      buckets.get(key).push(g);
    });

    // ترتیب از `by_term` سرور می‌آید که با _term_rank مرتب شده؛ ترم‌های
    // بدون متادیتا (مثلاً نمره‌ی قدیمیِ بدون ترم) در انتها می‌آیند.
    const ordered = [
      ...byTerm.map(
        (t) => t.term || ''
      ),
      ...[...buckets.keys()].filter(
        (k) => !meta.has(k)
      ),
    ];

    const seen = new Set();
    return ordered
      .filter((k) => {
        if (seen.has(k)) return false;
        seen.add(k);
        return buckets.has(k);
      })
      .map((k) => ({
        term: k,
        label:
          meta.get(k)?.label ||
          k ||
          'بدون ترم',
        avg:
          meta.get(k)?.avg ?? null,
        rows: buckets.get(k) || [],
      }));
  })();


  const best =
    grades.reduce(
      (
        current,
        item
      ) =>
        Math.max(
          current,

          percentage(
            item.percentage
          ) || 0
        ),

      0
    );


  return (
    <>
      <Header
        title="کارنامه من"
        subtitle={
          total
            ? `${total} نمره ثبت‌شده`
            : 'نمرات و ارزیابی‌ها'
        }
        back={false}
        onRefresh={refetch}
        refreshing={isRefetching}
      />

      <main className="page fade-up">
        {/* تب‌ها بیرونِ شاخه‌ی خالی رندر می‌شوند: اگر ترمی انتخاب باشد که
            نمره ندارد، کاربر باید همچنان بتواند به ترمِ دیگر برگردد. */}
        {!isLoading &&
          !isError && (
            <TermTabs
              terms={allTerms}
              active={activeTerm}
              onPick={pickTerm}
              byTerm={byTerm}
            />
          )}

        {isLoading ? (
          <GradesSkeleton />
        ) : isError ? (
          <PageError
            text={
              'دریافت نمرات انجام نشد.'
            }
            onRetry={() => refetch()}
            pending={isRefetching}
          />
        ) : grades.length ===
          0 ? (
          <div className="empty card">
            <div className="empty__ic">
              📊
            </div>

            <div
              style={{
                color:
                  'var(--tx2)',

                fontWeight:
                  700,
              }}
            >
              {activeTerm
                ? `برای «${activeTerm}» نمره‌ای ثبت نشده است`
                : 'هنوز نمره‌ای ثبت نشده است'}
            </div>

            <div
              style={{
                fontSize: 'var(--fs-cap)',
              }}
            >
              {activeTerm
                ? 'می‌توانید ترم دیگری را از نوار بالا انتخاب کنید.'
                : 'بعد از ثبت توسط ادمین محتوا، نتیجه اینجا نمایش داده می‌شود.'}
            </div>
          </div>
        ) : (
          <div
            style={{
              display:
                'grid',

              gap:
                12,
            }}
          >
            <section
              className={
                'card card-glow hero-card'
              }
            >
              <div
                style={{
                  display:
                    'flex',

                  alignItems:
                    'center',

                  gap:
                    15,
                }}
              >
                <div
                  style={{
                    position:
                      'relative',

                    display:
                      'grid',

                    flex:
                      '0 0 90px',

                    height:
                      90,

                    placeItems:
                      'center',

                    borderRadius:
                      '50%',

                    background:
                      `conic-gradient(${
                        averageStyle.color
                      } ${
                        averagePercent ||
                        0
                      }%,var(--ovr) 0)`,

                    boxShadow:
                      'var(--shd-glow)',
                  }}
                >
                  <div
                    style={{
                      display:
                        'grid',

                      width:
                        72,

                      height:
                        72,

                      placeItems:
                        'center',

                      background:
                        'var(--surf)',

                      borderRadius:
                        '50%',

                      textAlign:
                        'center',
                    }}
                  >
                    <div>
                      <div
                        style={{
                          color:
                            averageStyle.color,

                          fontSize:
                            23,

                          fontWeight:
                            900,

                          lineHeight:
                            1,
                        }}
                      >
                        {average ===
                        null
                          ? '—'
                          : average.toFixed(
                              2
                            )}
                      </div>

                      <div
                        style={{
                          color:
                            'var(--txm)',

                          fontSize: 'var(--fs-cap)',

                          marginTop: 'var(--sp-1)',
                        }}
                      >
                        از ۲۰
                      </div>
                    </div>
                  </div>
                </div>

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
                    میانگین کل شما
                  </div>

                  <div
                    style={{
                      color:
                        averageStyle.color,

                      fontSize: 'var(--fs-xl)',

                      fontWeight:
                        900,

                      marginTop:
                        3,
                    }}
                  >
                    {averageStyle.icon}{' '}
                    {averageStyle.label}
                  </div>

                  <div
                    style={{
                      color:
                        'var(--tx2)',

                      fontSize: 'var(--fs-cap)',

                      lineHeight:
                        1.7,

                      marginTop:
                        5,
                    }}
                  >
                    {graded} نمره در محاسبهٔ
                    میانگین لحاظ شده است.
                  </div>
                </div>
              </div>
            </section>

            <section className="grid2">
              <div
                className="card"
                style={{
                  textAlign:
                    'center',

                  padding:
                    12,
                }}
              >
                <div
                  style={{
                    color:
                      'var(--ok)',

                    fontSize: 'var(--fs-xl)',

                    fontWeight:
                      900,
                  }}
                >
                  {passed}
                </div>

                <div
                  style={{
                    color:
                      'var(--txm)',

                    fontSize: 'var(--fs-cap)',
                  }}
                >
                  نمره قبولی
                </div>
              </div>

              <div
                className="card"
                style={{
                  textAlign:
                    'center',

                  padding:
                    12,
                }}
              >
                <div
                  style={{
                    color:
                      'var(--acc2)',

                    fontSize: 'var(--fs-xl)',

                    fontWeight:
                      900,
                  }}
                >
                  {best}٪
                </div>

                <div
                  style={{
                    color:
                      'var(--txm)',

                    fontSize: 'var(--fs-cap)',
                  }}
                >
                  بهترین عملکرد
                </div>
              </div>
            </section>

            {total > graded && (
              <div
                className="card"
                style={{
                  display:
                    'flex',

                  alignItems:
                    'center',

                  gap: 'var(--sp-3)',

                  borderColor:
                    'var(--bd-warn)',
                }}
              >
                <span
                  style={{
                    fontSize:
                      21,
                  }}
                >
                  ⏳
                </span>

                <div>
                  <b
                    style={{
                      fontSize: 'var(--fs-sm)',
                    }}
                  >
                    {total -
                      graded}{' '}

                    نمره در انتظار محاسبه
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
                    پس از تکمیل نمره،
                    میانگین خودکار
                    به‌روزرسانی می‌شود.
                  </div>
                </div>
              </div>
            )}

            {byTerm.length > 1 && !activeTerm && (
              <section className="card" style={{ padding: 12 }}>
                <div style={{ fontWeight: 800, fontSize: 'var(--fs-sm)', marginBottom: 8 }}>🎓 نمای کلی ترم‌ها — هر ترم جدا</div>
                <div style={{ display: 'grid', gap: 8 }}>
                  {byTerm.map((t) => (
                    <button
                      key={t.term || 'none'}
                      type="button"
                      onClick={() => pickTerm(t.term)}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 8, padding: '9px 10px',
                        borderRadius: 'var(--r-md)', border: '1px solid var(--bd)', background: 'var(--bg)',
                        textAlign: 'right', cursor: 'pointer'
                      }}
                    >
                      <span style={{ fontWeight: 800, fontSize: 'var(--fs-sm)' }}>{t.label || t.term || 'بدون ترم'}</span>
                      <span style={{ color: 'var(--txm)', fontSize: 'var(--fs-cap)' }}>{t.total} نمره{t.avg != null ? ` · میانگین ${t.avg}/20` : ''}</span>
                      <span style={{ flex: 1 }} />
                      <span style={{ color: 'var(--acc)', fontSize: 'var(--fs-cap)', fontWeight: 800 }}>نمایش ←</span>
                    </button>
                  ))}
                </div>
              </section>
            )}

            <div
              className="sec-title"
              style={{
                marginTop: 'var(--sp-1)',
              }}
            >
              📋 جزئیات نمرات
            </div>

            {termGroups.map(
              (group) => (
                <section
                  key={
                    group.term || '_none'
                  }
                  style={{
                    display:
                      'grid',

                    gap:
                      9,
                  }}
                >
                  {/* سربرگِ ترم فقط وقتی معنا دارد که بیش از یک بلوک
                      روی صفحه باشد؛ در نمای تک‌ترم تکراری است. */}
                  {termGroups.length >
                    1 && (
                    <div
                      style={{
                        display:
                          'flex',

                        alignItems:
                          'center',

                        gap:
                          8,

                        marginTop:
                          'var(--sp-1)',
                      }}
                    >
                      <b
                        style={{
                          fontSize:
                            'var(--fs-sm)',
                        }}
                      >
                        🎓 {group.label}
                      </b>

                      <span
                        style={{
                          color:
                            'var(--txm)',

                          fontSize:
                            'var(--fs-cap)',
                        }}
                      >
                        {group.rows.length}{' '}
                        نمره
                        {group.avg !==
                        null
                          ? ` · میانگین ${group.avg}/20`
                          : ''}
                      </span>
                    </div>
                  )}

                  {group.rows.map(
                    (
                      grade,
                      index
                    ) => {
                      const globalIndex =
                        grades.indexOf(
                          grade
                        );
                      return (
                        <GradeRow
                          key={
                            grade.id ||
                            `${
                              grade.lesson
                            }-${index}`
                          }
                          grade={grade}
                          index={
                            globalIndex
                          }
                          flash={
                            flashIdx ===
                            globalIndex
                          }
                        />
                      );
                    }
                  )}
                </section>
              )
            )}
          </div>
        )}
      </main>
    </>
  );
}
