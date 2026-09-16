import { useQuery } from '@tanstack/react-query';
import api from '../../lib/api';
import { faDate } from '../../lib/format';
import Header from '../../components/layout/Header';
import PageError from '../../components/shared/PageError';
import EmptyState from '../../components/shared/EmptyState';

import {

  Spinner,
} from '../../components/shared/Loading';

import {
  SkRowList,
} from '../../components/shared/skeletons';


const LETTERS = [
  'الف',
  'ب',
  'ج',
  'د',
];


export default function QuestionHistory() {
  const {
    data,
    isLoading,
    isError,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: [
      'answer-history',
    ],

    queryFn: () =>
      api
        .get(
          '/api/questions/history',

          {
            params: {
              limit: 100,
            },
          }
        )
        .then(
          (response) =>
            response.data
        ),
  });


  const answers =
    Array.isArray(
      data?.answers
    )
      ? data.answers
      : [];


  const correct =
    answers.filter(
      (item) =>
        item.is_correct
    ).length;


  const score =
    answers.length
      ? Math.round(
          (
            correct /
            answers.length
          ) * 100
        )
      : 0;


  return (
    <>
      <Header
        title="تاریخچه پاسخ‌ها"
        subtitle={`${
          Number(data?.total) || 0
        } پاسخ ثبت‌شده`}
      />

      <main className="page fade-up">
        <section
          className={
            'card card-glow hero-card'
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
                  'var(--grad-brand)',

                fontSize:
                  24,
              }}
            >
              🕘
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
                مرور عملکرد گذشته
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
                {correct} پاسخ صحیح از{' '}
                {answers.length}
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
                با مرور اشتباهات، نقاط ضعف
                را به نقطه قوت تبدیل کن.
              </div>
            </div>

            <div
              style={{
                color:
                  score >= 70
                    ? 'var(--ok)'
                    : score >= 40
                      ? 'var(--warn)'
                      : 'var(--err)',

                fontSize: 'var(--fs-xl)',

                fontWeight:
                  900,
              }}
            >
              {score}٪
            </div>
          </div>
        </section>


        {isLoading ? (
          <SkRowList
            n={3}
            icon={42}
          />
        ) : isError ? (
          <PageError
            text="دریافت تاریخچه انجام نشد."
            onRetry={() => refetch()}
            pending={isRefetching}
          />
        ) : answers.length === 0 ? (
          <EmptyState icon="📭">
            هنوز پاسخی ثبت نشده است.
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
            {answers.map(
              (
                item,
                index
              ) => (
                <article
                  key={
                    item.id ||
                    item.question_id ||
                    index
                  }
                  className={
                    'card pop-in'
                  }
                  style={{
                    padding:
                      13,

                    borderColor:
                      item.is_correct
                        ? 'var(--bd-ok)'
                        : 'var(--bd-err)',

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

                    {item.topic && (
                      <span className="badge b-gray">
                        {item.topic}
                      </span>
                    )}

                    <span
                      className={`badge ${
                        item.is_correct
                          ? 'b-grn'
                          : 'b-red'
                      }`}
                      style={{
                        marginRight:
                          'auto',
                      }}
                    >
                      {item.is_correct
                        ? '✓ صحیح'
                        : '✕ اشتباه'}
                    </span>
                  </div>

                  <div
                    style={{
                      fontSize: 'var(--fs-sm)',

                      fontWeight:
                        650,

                      lineHeight:
                        1.8,
                    }}
                  >
                    {item.question ||
                      'متن سؤال موجود نیست'}
                  </div>

                  <div
                    style={{
                      display:
                        'grid',

                      gridTemplateColumns:
                        '1fr 1fr',

                      gap: 'var(--sp-2)',

                      marginTop: 'var(--sp-3)',
                    }}
                  >
                    <div
                      style={{
                        padding:
                          '7px 9px',

                        color:
                          item.is_correct
                            ? 'var(--ok)'
                            : 'var(--err)',

                        background:
                          item.is_correct
                            ? 'var(--soft-ok)'
                            : 'var(--soft-err)',

                        borderRadius: 'var(--r-sm)',

                        fontSize: 'var(--fs-cap)',
                      }}
                    >
                      پاسخ شما:{' '}

                      <b>
                        {LETTERS[
                          item.selected
                        ] ??
                          item.selected}
                      </b>
                    </div>

                    <div
                      style={{
                        padding:
                          '7px 9px',

                        color:
                          'var(--ok)',

                        background:
                          'var(--soft-ok)',

                        borderRadius: 'var(--r-sm)',

                        fontSize: 'var(--fs-cap)',
                      }}
                    >
                      پاسخ صحیح:{' '}

                      <b>
                        {LETTERS[
                          item
                            .correct_answer
                        ] ??
                          item
                            .correct_answer}
                      </b>
                    </div>
                  </div>

                  {item.answered_at && (
                    <div
                      style={{
                        color:
                          'var(--txm)',

                        fontSize: 'var(--fs-cap)',

                        marginTop: 'var(--sp-2)',
                      }}
                    >
                      📆{' '}

                      {faDate(item.answered_at)}
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
