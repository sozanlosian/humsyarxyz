import {
  useMemo,
  useState,
} from 'react';

import {
  useInfiniteQuery,
} from '@tanstack/react-query';

import api from '../../lib/api';
import { faDate } from '../../lib/format';
import Header from '../../components/layout/Header';
import PageError from '../../components/shared/PageError';
import EmptyState from '../../components/shared/EmptyState';

import {
  Spinner,
} from '../../components/shared/Loading';

import {
  AuditLogSkeleton,
} from '../../components/shared/skeletons';

import {
  haptic,
} from '../../lib/telegram';


/* ═══════════ نگاشت‌های نمایشی ═══════════ */

const MODULE_FA = {
  Users: 'کاربران',
  Roles: 'نقش‌ها',
  Settings: 'تنظیمات',
  Questions: 'سؤالات',
  Content: 'محتوا',
  Schedules: 'برنامه کلاسی',
  Tickets: 'تیکت‌ها',
  Reports: 'گزارش‌ها',
  Notifications: 'اعلان‌ها',
  Backup: 'بکاپ',
  System: 'سیستم',
  Auth: 'ورود/خروج',
  Subscription: 'اشتراک',
  Grades: 'نمرات',
  AI: 'هوشیار',
};

const MODULE_ICON = {
  Users: '👥',
  Roles: '🎓',
  Settings: '⚙️',
  Questions: '❓',
  Content: '📚',
  Schedules: '📅',
  Tickets: '🎫',
  Reports: '🚩',
  Notifications: '🔔',
  Backup: '💾',
  System: '🖥',
  Auth: '🔐',
  Subscription: '💎',
  Grades: '📊',
  AI: '🤖',
};

const SEVERITY_META = {
  INFO: [
    '🟢',
    'عادی',
    'b-gray',
  ],

  WARNING: [
    '🟡',
    'توجه',
    'b-yel',
  ],

  HIGH: [
    '🟠',
    'مهم',
    'b-acc',
  ],

  CRITICAL: [
    '🔴',
    'بحرانی',
    'b-red',
  ],
};

const CATEGORY_FILTERS = [
  ['', 'همه'],
  ['admin', '🛡 مدیریتی'],
  ['content', '🎓 محتوایی'],
];

const SEVERITY_FILTERS = [
  ['', 'همه سطوح'],
  ['CRITICAL', '🔴 بحرانی'],
  ['HIGH', '🟠 مهم'],
  ['WARNING', '🟡 توجه'],
  ['INFO', '🟢 عادی'],
];

const PAGE_SIZE = 25;


/* ═══════════ ابزارها ═══════════ */

function timeAgo(iso) {
  if (!iso) return '—';

  const then = new Date(iso).getTime();

  if (!Number.isFinite(then)) {
    return iso.slice(0, 16);
  }

  const diff = Math.max(
    0,
    Date.now() - then
  );

  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;

  if (diff < minute) return 'همین الان';
  if (diff < hour)
    return `${Math.floor(diff / minute)} دقیقه پیش`;
  if (diff < day)
    return `${Math.floor(diff / hour)} ساعت پیش`;
  if (diff < 7 * day)
    return `${Math.floor(diff / day)} روز پیش`;

  return faDate(iso, iso.slice(0, 10));
}


function AuditItem({ log }) {
  const [
    sevIcon,
    sevLabel,
    sevBadge,
  ] =
    SEVERITY_META[log.severity] ||
    SEVERITY_META.INFO;

  const moduleFa =
    MODULE_FA[log.module] ||
    log.module ||
    '—';

  const moduleIcon =
    MODULE_ICON[log.module] ||
    '📝';

  const actor = log.actor || {};
  const target =
    log.target || {};

  const changes =
    log.changes || [];


  return (
    <div className="audit-item pop-in">
      <span className="audit-item__icon">
        {moduleIcon}
      </span>

      <div className="audit-item__body">
        <div className="audit-item__top">
          <div className="audit-item__action">
            {log.action || '—'}
          </div>

          <span className="audit-item__time">
            {timeAgo(log.timestamp)}
          </span>
        </div>

        <div className="audit-item__meta">
          👤 {actor.name || '—'}

          {actor.role && actor.role !== 'نامشخص' && (
            <span
              className="role-tag"
              style={{ marginRight: 5 }}
            >
              {actor.role}
            </span>
          )}

          {' • '}📂 {moduleFa}

          {(target.label ||
            target.id) && (
            <>
              {' • '}🎯{' '}
              {target.label ||
                `#${target.id}`}
            </>
          )}
        </div>

        {log.details && (
          <div className="audit-item__details">
            {log.details}
          </div>
        )}

        {changes.length > 0 && (
          <div className="audit-item__changes">
            {changes.map(
              (change, index) => (
                <div
                  key={index}
                  className="audit-item__change"
                >
                  <b>
                    {change.field}:
                  </b>

                  <span className="audit-item__before">
                    {String(
                      change.before ??
                        '—'
                    )}
                  </span>

                  <span>←</span>

                  <span className="audit-item__after">
                    {String(
                      change.after ??
                        '—'
                    )}
                  </span>
                </div>
              )
            )}
          </div>
        )}

        <div
          style={{
            display: 'flex',
            gap: 5,
            marginTop: 'var(--sp-2)',
          }}
        >
          <span
            className={`badge ${sevBadge}`}
          >
            {sevIcon} {sevLabel}
          </span>

          {(log.tags || [])
            .slice(0, 3)
            .map((tag) => (
              <span
                key={tag}
                className="badge b-gray"
              >
                #{tag}
              </span>
            ))}
        </div>
      </div>
    </div>
  );
}


/* ═══════════ صفحه اصلی ═══════════ */

export default function AuditLog() {
  const [category, setCategory] =
    useState('');

  const [severity, setSeverity] =
    useState('');

  const [query, setQuery] =
    useState('');

  const [search, setSearch] =
    useState('');


  const {
    data,
    isLoading,
    isError,
    refetch,
    isRefetching,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: [
      'admin-audit-logs',
      category,
      severity,
      search,
    ],

    queryFn: ({ pageParam = 0 }) =>
      api
        .get(
          '/api/admin/audit-logs',
          {
            params: {
              category:
                category ||
                undefined,
              min_severity:
                severity ||
                undefined,
              q:
                search ||
                undefined,
              skip: pageParam,
              limit: PAGE_SIZE,
            },
          }
        )
        .then(
          (response) =>
            response.data
        ),

    getNextPageParam: (
      lastPage,
      pages
    ) => {
      const loaded =
        pages.length *
        PAGE_SIZE;

      return loaded <
        (lastPage.total || 0)
        ? loaded
        : undefined;
    },

    staleTime: 20_000,
  });


  const logs = useMemo(
    () =>
      (data?.pages || []).flatMap(
        (page) => page.logs || []
      ),

    [data]
  );

  const total =
    data?.pages?.[0]?.total || 0;

  const counters =
    data?.pages?.[0]?.counters ||
    {};


  const submitSearch = (event) => {
    event.preventDefault();
    haptic('light');
    setSearch(query.trim());
  };


  return (
    <>
      <Header
        title="لاگ فعالیت مدیران"
        subtitle={
          'ردیابی اقدامات حساس سامانه'
        }
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
        <div className="page-hint">
          <span>🛡</span>

          <span>
            هر اقدام حساس مدیران (تأیید و
            تعلیق کاربر، ارسال همگانی، تغییر
            تنظیمات و…) اینجا با جزئیات
            کامل، انجام‌دهنده و تغییرات
            قبل‌/بعد ثبت می‌شود.
          </span>
        </div>

        {/* شمارنده سطوح */}
        {Object.keys(counters).length >
          0 && (
          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 6,
              marginBottom: 11,
            }}
          >
            {Object.entries(
              counters
            ).map(
              ([sev, count]) => {
                const meta =
                  SEVERITY_META[
                    sev
                  ];

                return (
                  <span
                    key={sev}
                    className={`badge ${
                      meta?.[2] ||
                      'b-gray'
                    }`}
                  >
                    {meta?.[0] ||
                      '⚪'}{' '}
                    {count}
                  </span>
                );
              }
            )}
          </div>
        )}

        {/* جست‌وجو */}
        <form
          onSubmit={submitSearch}
          style={{
            display: 'flex',
            gap: 'var(--sp-2)',
            marginBottom: 'var(--sp-3)',
          }}
        >
          <input
            className="inp"
            style={{ flex: 1 }}
            value={query}
            onChange={(event) =>
              setQuery(
                event.target.value
              )
            }
            placeholder="جست‌وجو در عملیات، نام مدیر یا هدف…"
          />

          <button
            type="submit"
            className="btn btn-p"
            style={{
              minHeight: 38,
              padding: '0 14px',
            }}
          >
            🔍
          </button>
        </form>

        {/* فیلتر دسته */}
        <div className="chip-row">
          {CATEGORY_FILTERS.map(
            ([value, label]) => (
              <button
                type="button"
                key={value}
                className={`chip ${
                  category === value
                    ? 'chip--active'
                    : ''
                }`}
                onClick={() => {
                  haptic('light');
                  setCategory(value);
                }}
              >
                {label}
              </button>
            )
          )}

          <span
            style={{
              width: 1,
              flex: '0 0 1px',
              margin: '4px 3px',
              background:
                'var(--bd)',
            }}
          />

          {SEVERITY_FILTERS.map(
            ([value, label]) => (
              <button
                type="button"
                key={value}
                className={`chip ${
                  severity === value
                    ? 'chip--active'
                    : ''
                }`}
                onClick={() => {
                  haptic('light');
                  setSeverity(value);
                }}
              >
                {label}
              </button>
            )
          )}
        </div>

        {isLoading ? (
          <AuditLogSkeleton />
        ) : isError ? (
          <PageError
            text="دریافت لاگ انجام نشد."
            onRetry={() => refetch()}
          />
        ) : logs.length === 0 ? (
          <EmptyState icon="📭">
            موردی با این فیلترها پیدا نشد.
          </EmptyState>
        ) : (
          <>
            <div
              className="card"
              style={{
                padding: '4px 14px',
              }}
            >
              {logs.map((log) => (
                <AuditItem
                  key={log.id}
                  log={log}
                />
              ))}
            </div>

            <div
              style={{
                marginTop: 11,
                textAlign: 'center',
                color: 'var(--txm)',
                fontSize: 'var(--fs-cap)',
              }}
            >
              نمایش {logs.length} از{' '}
              {total} رویداد
            </div>

            {hasNextPage && (
              <button
                className="btn btn-dark btn-full"
                style={{
                  marginTop: 'var(--sp-3)',
                }}
                disabled={
                  isFetchingNextPage
                }
                onClick={() =>
                  fetchNextPage()
                }
              >
                {isFetchingNextPage ? (
                  <Spinner
                    size={15}
                  />
                ) : (
                  'نمایش رویدادهای قدیمی‌تر'
                )}
              </button>
            )}
          </>
        )}
      </main>
    </>
  );
}
