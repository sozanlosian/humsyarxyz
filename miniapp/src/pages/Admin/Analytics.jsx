import { number, faDayMonth } from '../../lib/format';

import {
  useMemo,
  useState,
} from 'react';

import {
  useQuery,
} from '@tanstack/react-query';

import api from '../../lib/api';
import Header from '../../components/layout/Header';
import PageError from '../../components/shared/PageError';

import {
} from '../../components/shared/Loading';

import {
  AnalyticsSkeleton,
} from '../../components/shared/skeletons';

import {
  haptic,
} from '../../lib/telegram';


/* ═══════════ نگاشت‌های نمایشی ═══════════ */

const ACTION_FA = {
  answer: 'پاسخ به سؤال',
  exam: 'آزمون',
  ai_ask: 'پرسش هوشیار',
  bs_download: 'دانلود جزوه',
  ref_download: 'دانلود کتاب',
  qbank_download: 'دانلود بانک فایل',
  search: 'جست‌وجو',
  ticket: 'تیکت',
  login: 'ورود',
};

const RANGE_OPTIONS = [7, 14, 30];




/* ═══════════ نمودار میله‌ای SVG ═══════════ */

function BarChart({
  data,
  color = 'var(--acc)',
  height = 118,
  formatLabel,
}) {
  if (!data.length) return null;

  const max = Math.max(
    1,
    ...data.map((item) => item.count)
  );

  const width = Math.max(
    data.length * 26,
    240
  );

  const barWidth = 16;

  const gap =
    (width -
      data.length * barWidth) /
    (data.length + 1);

  const chartHeight = height - 26;


  return (
    <div
      style={{ overflowX: 'auto' }}
      className="chart__scroller"
    >
      <svg
        className="chart__svg"
        viewBox={`0 0 ${width} ${height}`}
        style={{
          minWidth: '100%',
          width: width,
          height,
        }}
        role="img"
      >
        {/* خط مبنا */}
        <line
          x1="0"
          x2={width}
          y1={chartHeight}
          y2={chartHeight}
          stroke="var(--bd)"
          strokeWidth="1"
        />

        {data.map((item, index) => {
          const barHeight = Math.max(
            item.count > 0 ? 3 : 0,
            (item.count / max) *
              (chartHeight - 14)
          );

          const x =
            gap +
            index *
              (barWidth + gap);

          return (
            <g key={item.date}>
              <rect
                className="chart__bar"
                x={x}
                y={
                  chartHeight -
                  barHeight
                }
                width={barWidth}
                height={barHeight}
                rx="4"
                fill={
                  item.count > 0
                    ? color
                    : 'var(--ovr)'
                }
                opacity={
                  0.35 +
                  0.65 *
                    (item.count /
                      max ||
                      0.06)
                }
              >
                <title>
                  {
                    formatLabel(
                      item.date
                    )
                  }
                  : {item.count}
                </title>
              </rect>

              {item.count > 0 && (
                <text
                  className="chart__val"
                  x={
                    x +
                    barWidth / 2
                  }
                  y={
                    chartHeight -
                    barHeight -
                    4
                  }
                  textAnchor="middle"
                >
                  {item.count}
                </text>
              )}

              <text
                className="chart__lbl"
                x={
                  x + barWidth / 2
                }
                y={height - 8}
                textAnchor="middle"
              >
                {formatLabel(
                  item.date
                )}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}


/* ═══════════ کارت KPI ═══════════ */

function Kpi({
  icon,
  value,
  label,
  color,
  soft,
  trend,
}) {
  return (
    <div className="card kpi">
      <span
        className="kpi__icon"
        style={{
          color,
          background: soft,
        }}
      >
        {icon}
      </span>

      <b className="kpi__value">
        {value}
      </b>

      <span className="kpi__label">
        {label}
      </span>

      {trend && (
        <span
          className={`kpi__trend kpi__trend--${trend.type}`}
        >
          {trend.type === 'up'
            ? '▲'
            : trend.type === 'down'
              ? '▼'
              : '●'}{' '}
          {trend.text}
        </span>
      )}
    </div>
  );
}


/* ═══════════ صفحه اصلی ═══════════ */

export default function Analytics() {
  const [days, setDays] =
    useState(14);


  const {
    data,
    isLoading,
    isError,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: [
      'admin-analytics',
      days,
    ],

    queryFn: () =>
      api
        .get(
          '/api/admin/analytics',
          {
            params: { days },
          }
        )
        .then(
          (response) =>
            response.data
        ),

    staleTime: 60_000,
  });


  /* پرکردن روزهای بدون داده */
  const fillSeries = useMemo(
    () =>
      (series) => {
        const map = new Map(
          (series || []).map((item) => [
            item.date,
            item.count,
          ])
        );

        const result = [];
        const today = new Date();

        for (
          let i = days - 1;
          i >= 0;
          i -= 1
        ) {
          const date = new Date(
            today.getTime() -
              i * 86_400_000
          );

          const iso = date
            .toISOString()
            .slice(0, 10);

          result.push({
            date: iso,
            count: map.get(iso) || 0,
          });
        }

        return result;
      },

    [days]
  );


  const kpis = data?.kpis || {};

  const usersSeries = fillSeries(
    data?.daily?.users
  );

  const activitySeries = fillSeries(
    data?.daily?.activity
  );

  const ticketsSeries = fillSeries(
    data?.daily?.tickets
  );

  const topActions =
    data?.top_actions || [];

  const hourly = data?.hourly || [];

  const maxHourly = Math.max(
    1,
    ...hourly.map((item) =>
      number(item.count)
    )
  );

  const maxAction = Math.max(
    1,
    ...topActions.map((item) =>
      number(item.count)
    )
  );

  const dayLabel = (iso) => {
    const jalali = faDayMonth(iso, '');

    if (jalali) {
      return jalali;
    }

    const [, month, day] =
      String(iso || '').split('-');

    return `${Number(day)}/${Number(month)}`;
  };


  return (
    <>
      <Header
        title="آمار تحلیلی"
        subtitle={
          'نمای کلی عملکرد سامانه'
        }
        backTo="/admin"
        right={
          <button
            type="button"
            onClick={() => refetch()}
            disabled={isRefetching}
            aria-label="به‌روزرسانی"
            style={{
              width: 36,
              height: 36,
              borderRadius: 'var(--r-md)',
              background:
                'var(--elev)',
              border:
                '1px solid var(--bd)',
              cursor: 'pointer',
            }}
          >
            ↻
          </button>
        }
      />

      <main className="page fade-up">
        {/* بازه زمانی */}
        <div className="chip-row">
          {RANGE_OPTIONS.map(
            (option) => (
              <button
                type="button"
                key={option}
                className={`chip ${
                  days === option
                    ? 'chip--active'
                    : ''
                }`}
                onClick={() => {
                  haptic('light');
                  setDays(option);
                }}
              >
                {option} روز اخیر
              </button>
            )
          )}
        </div>

        {isLoading ? (
          <AnalyticsSkeleton />
        ) : isError ? (
          <PageError
            text="دریافت آمار انجام نشد."
            onRetry={() => refetch()}
          />
        ) : (
          <>
            {/* KPI ها */}
            <section
              className="grid2"
              style={{
                marginBottom: 15,
              }}
            >
              <Kpi
                icon="👥"
                value={number(
                  kpis.active_users
                )}
                label={`کاربر فعال در ${days} روز`}
                color="var(--t-acc)"
                soft="var(--soft-acc)"
              />

              <Kpi
                icon="🆕"
                value={number(
                  kpis.new_users
                )}
                label={`عضویت جدید در ${days} روز`}
                color="var(--t-ok)"
                soft="var(--soft-ok)"
              />

              <Kpi
                icon="⚡"
                value={number(
                  kpis.total_actions
                )}
                label="کل فعالیت ثبت‌شده"
                color="var(--t-pur)"
                soft="var(--soft-pur)"
              />

              <Kpi
                icon="🎫"
                value={number(
                  kpis.new_tickets
                )}
                label={`تیکت جدید در ${days} روز`}
                color="var(--t-warn)"
                soft="var(--soft-warn)"
              />
            </section>

            {/* نمودار عضویت */}
            <section
              className="card chart"
              style={{
                marginBottom: 12,
              }}
            >
              <div className="chart__title">
                <span>
                  🌱 کاربران جدید
                </span>

                <span>
                  مجموع:{' '}
                  {usersSeries.reduce(
                    (sum, item) =>
                      sum + item.count,
                    0
                  )}
                </span>
              </div>

              <BarChart
                data={usersSeries}
                color="var(--ok)"
                formatLabel={dayLabel}
              />
            </section>

            {/* نمودار فعالیت */}
            <section
              className="card chart"
              style={{
                marginBottom: 12,
              }}
            >
              <div className="chart__title">
                <span>
                  ⚡ فعالیت روزانه کاربران
                </span>

                <span>
                  پاسخ، دانلود و…
                </span>
              </div>

              <BarChart
                data={activitySeries}
                color="var(--acc)"
                formatLabel={dayLabel}
              />
            </section>

            {/* نمودار تیکت */}
            <section
              className="card chart"
              style={{
                marginBottom: 12,
              }}
            >
              <div className="chart__title">
                <span>
                  🎫 تیکت‌های جدید
                </span>

                <span>
                  مجموع:{' '}
                  {ticketsSeries.reduce(
                    (sum, item) =>
                      sum + item.count,
                    0
                  )}
                </span>
              </div>

              <BarChart
                data={ticketsSeries}
                color="var(--warn)"
                formatLabel={dayLabel}
              />
            </section>

            {/* پرکاربردترین عملیات */}
            {topActions.length > 0 && (
              <section
                className="card"
                style={{
                  marginBottom: 12,
                }}
              >
                <div className="sec-title">
                  🏆 پرکاربردترین قابلیت‌ها
                </div>

                {topActions.map(
                  (item) => (
                    <div
                      key={item.action}
                      className="hbar"
                    >
                      <span>
                        {ACTION_FA[
                          item.action
                        ] ||
                          item.action}
                      </span>

                      <span className="hbar__track">
                        <span
                          className="hbar__fill"
                          style={{
                            width: `${Math.max(
                              5,
                              (number(
                                item.count
                              ) /
                                maxAction) *
                                100
                            )}%`,
                          }}
                        />
                      </span>

                      <span className="hbar__count">
                        {number(
                          item.count
                        )}
                      </span>
                    </div>
                  )
                )}
              </section>
            )}

            {/* توزیع ساعتی */}
            {hourly.length > 0 && (
              <section
                className="card"
                style={{
                  marginBottom: 12,
                }}
              >
                <div className="sec-title">
                  🕐 ساعت‌های اوج فعالیت
                </div>

                {hourly.map((item) => (
                  <div
                    key={item.hour}
                    className="hbar"
                  >
                    <span>
                      {String(
                        item.hour
                      ).padStart(
                        2,
                        '0'
                      )}:۰۰ تا{' '}
                      {String(
                        (item.hour +
                          1) %
                          24
                      ).padStart(
                        2,
                        '0'
                      )}:۰۰
                    </span>

                    <span className="hbar__track">
                      <span
                        className="hbar__fill"
                        style={{
                          width: `${Math.max(
                            4,
                            (number(
                              item.count
                            ) /
                              maxHourly) *
                              100
                          )}%`,

                          background:
                            'linear-gradient(90deg,var(--pur),var(--t-info))',
                        }}
                      />
                    </span>

                    <span className="hbar__count">
                      {number(
                        item.count
                      )}
                    </span>
                  </div>
                ))}
              </section>
            )}
          </>
        )}
      </main>
    </>
  );
}
