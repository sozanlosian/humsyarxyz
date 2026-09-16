import { faNum } from '../../lib/format';

import {
  useMemo,
  useState,
} from 'react';

import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import {
  useNavigate,
} from 'react-router-dom';

import Header from '../../components/layout/Header';
import PageError from '../../components/shared/PageError';
import EmptyState from '../../components/shared/EmptyState';
import {
  Spinner,
} from '../../components/shared/Loading';
import api from '../../lib/api';
import {
  haptic,
  hapticNotif,
} from '../../lib/telegram';
import {
  useUIStore,
} from '../../stores/uiStore';


/* ─────────────────────────────────────────────
   🧠 مرکز اعلان‌ها — بازطراحی موج N3
   بازتاب همه‌ی رویدادهای مهم حساب با معماری
   Notification Spine: دسته/آیکون/تُن/اولویت/pin
   و count از خودِ سرور می‌آید (هیچ مقدار بصری
   اینجا ساخته نمی‌شود)؛ کش با ردیف «من» و
   BottomNav مشترک است — بج همیشه یکدست.
───────────────────────────────────────────── */


export const INBOX_KEY = ['notif-inbox'];

/* ⚙ قرارداد رجیستری App.lazyScreen: این صفحه با
   exportName='NotificationCenter' resolve می‌شود؛
   export ایمن‌نام نباید حذف شود — حذفش = صفحهٔ
   تیره در روت /me/notifications/inbox (regression
   lock: رجیستری ۳۸ مسیر باید با exportها ۳۸/۳۸
   تطبیق داشته باشد) */
export { NotificationCenter };


/* برچسب‌های رایج دسته‌ها — آیکون سروری استفاده
   می‌شود ولی انسانی‌نویسی چیپ‌ها از همین نگاشت
   تطبیقی است (fallback به خودِ کلید برای تازه‌ها) */
const CAT_LABELS = {
  resources: 'منابع',
  references: 'رفرنس‌ها',
  basic_sci: 'علوم پایه',
  qbank: 'بانک سؤال',
  schedule: 'برنامه',
  exams: 'امتحان‌ها',
  grades: 'نمرات',
  tickets: 'تیکت‌ها',
  subscription: 'اشتراک',
  discounts: 'تخفیف‌ها',
  ai: 'هوشیار',
  announcement: 'اعلان‌ها',
  polls: 'نظرسنجی',
  gamification: 'بازی‌واری',
  profile: 'حساب',
  system: 'سیستم',
};


const TONE_COLORS = {
  blue:   ['var(--soft-acc-2)',  'var(--t-acc-hi)'],
  green:  ['var(--soft-ok)',  'var(--t-ok)'],
  yellow: ['var(--soft-warn)',  'var(--t-warn)'],
  red:    ['var(--soft-err)',   'var(--t-err)'],
  purple: ['var(--soft-pur)',  'var(--t-pur)'],
  acc:    ['var(--soft-info)',  'var(--t-info)'],
};


const PRIO_META = {
  critical: ['⚫ حیاتی', 'var(--t-err)'],
  high:     ['🟠 مهم',  'var(--t-warn)'],
  normal:   [null,       null],
  low:      [null,       null],
};





function getErrorMessage(error, fallback) {
  const detail = error?.response?.data?.detail;

  if (typeof detail === 'string' && detail.trim()) {
    return detail;
  }

  return fallback;
}


/* زمان نسبی فارسی — «همین الان» تا «x روز پیش»؛
   قدیمی‌تر از یک هفته = تاریخ کامل fa-IR */
function timeAgo(iso) {
  const then = new Date(iso).getTime();

  if (!iso || Number.isNaN(then)) {
    return '';
  }

  const seconds = Math.max(
    0,
    Math.floor((Date.now() - then) / 1000),
  );

  if (seconds < 60) {
    return 'همین الان';
  }

  const steps = [
    [60,           'دقیقه'],
    [60,           'ساعت'],
    [24,           'روز'],
  ];

  let value = seconds;
  let unit  = 'ثانیه';

  for (const [size, name] of steps) {
    if (value < size) {
      break;
    }

    value = Math.floor(value / size);
    unit  = name;
  }

  if (unit === 'روز' && value >= 7) {
    return new Date(iso)
      .toLocaleDateString('fa-IR');
  }

  return `${value.toLocaleString('fa-IR')} ${unit} پیش`;
}


/* 🗂 گروه‌بندی تاریخی — امروز / دیروز / این هفته /
   قدیمی‌تر (منطقه‌ی زمانی دستگاه — همان حس زمان) */
function dateGroup(iso) {
  const then = new Date(iso);

  if (!iso || Number.isNaN(then.getTime())) {
    return 3;
  }

  const now = new Date();

  const startOfToday = new Date(
    now.getFullYear(), now.getMonth(), now.getDate(),
  );

  const startOfThen = new Date(
    then.getFullYear(), then.getMonth(), then.getDate(),
  );

  const dayMs = 86_400_000;
  const diffDays = Math.round(
    (startOfToday - startOfThen) / dayMs,
  );

  if (diffDays <= 0) return 0;
  if (diffDays === 1) return 1;
  if (diffDays < 7) return 2;
  return 3;
}


const GROUP_TITLES = [
  'امروز',
  'دیروز',
  'این هفته',
  'قدیمی‌تر',
];


export default function NotificationCenter() {
  const navigate = useNavigate();

  const toast = useUIStore(
    (state) => state.toast,
  );

  const queryClient = useQueryClient();

  const [query, setQuery]         = useState('');
  const [unreadOnly, setUnreadOnly] =
    useState(false);
  const [cat, setCat]             = useState('all');
  const [openIds, setOpenIds]     =
    useState(() => new Set());


  const {
    data,
    isPending,
    isError,
    refetch,
  } = useQuery({
    queryKey: INBOX_KEY,

    queryFn: () =>
      api
        .get('/api/notifications/inbox')
        .then((response) => response.data),

    staleTime: 15_000,

    /* 🧠 realtime نرم — کل صفحه بدون رفلش؛
       فقط همین یک کوئری دوره‌ای (پولینگ مازاد
       ممنوع: دقیقاً همان ریتم بج تیکت) */
    refetchInterval: 45_000,

    refetchOnWindowFocus: 'always',
  });

  const items  = data?.items  || [];
  const unread = data?.unread || 0;


  /* به‌روزرسانی خوش‌بینانه‌ی کش — بج و لیست
     هر دو از همین یک منبع خوانده می‌شوند */
  const patchCache = (updater) => {
    const previous =
      queryClient.getQueryData(INBOX_KEY);

    queryClient.setQueryData(
      INBOX_KEY,
      (old) =>
        old
          ? updater(old)
          : old,
    );

    return previous;
  };


  const readMutation = useMutation({
    mutationFn: (ids) =>
      api.post(
        '/api/notifications/inbox/read',
        { ids },
      ),

    onMutate: (ids) =>
      patchCache((old) => ({
        ...old,
        items: old.items.map((item) =>
          !ids || ids.includes(item.id)
            ? { ...item, read: true }
            : item
        ),
        unread: 0,
      })),

    onError: (_error, _ids, previous) => {
      if (previous) {
        queryClient.setQueryData(
          INBOX_KEY,
          previous,
        );
      }
    },

    onSettled: () =>
      queryClient.invalidateQueries({
        queryKey: INBOX_KEY,
      }),
  });


  const deleteMutation = useMutation({
    mutationFn: (id) =>
      api.delete(
        `/api/notifications/inbox/${id}`,
      ),

    onMutate: (id) => {
      const previous = patchCache((old) => {
        const removed = old.items.find(
          (item) => item.id === id,
        );

        return {
          ...old,
          items: old.items.filter(
            (item) => item.id !== id,
          ),
          unread:
            removed && !removed.read
              ? Math.max(0, old.unread - 1)
              : old.unread,
        };
      });

      hapticNotif('success');

      return previous;
    },

    onError: (error, _id, previous) => {
      if (previous) {
        queryClient.setQueryData(
          INBOX_KEY,
          previous,
        );
      }

      hapticNotif('error');

      toast(
        getErrorMessage(
          error,
          'حذف اعلان انجام نشد',
        ),
        'error',
      );
    },

    onSettled: () =>
      queryClient.invalidateQueries({
        queryKey: INBOX_KEY,
      }),
  });


  /* 📌 سنجاق — رفتهرفت به سرور؛ نمایش فوری در همین
     کش (pin‌ها در سرور هم بالا می‌آیند، اینجا
     صرفاً حفظ معنای سریع است) */
  const pinMutation = useMutation({
    mutationFn: ({ id, pinned }) =>
      api.post(
        `/api/notifications/inbox/${id}/pin`,
        { pinned },
      ),

    onMutate: ({ id, pinned }) =>
      patchCache((old) => ({
        ...old,
        items: old.items.map((item) =>
          item.id === id
            ? { ...item, pinned }
            : item
        ),
      })),

    onError: (_error, _vars, previous) => {
      if (previous) {
        queryClient.setQueryData(
          INBOX_KEY,
          previous,
        );
      }

      hapticNotif('error');
    },

    onSettled: () =>
      queryClient.invalidateQueries({
        queryKey: INBOX_KEY,
      }),
  });


  /* 🔎 فیلتر محلی روی همان داده‌ی سرور —
     بدون هیچ درخواست اضافی (قانون پرفورمنس) */
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();

    return items.filter((item) => {
      if (unreadOnly && item.read) return false;

      if (cat !== 'all' && item.category !== cat) {
        return false;
      }

      if (!needle) return true;

      return (
        (item.title || '')
          .toLowerCase()
          .includes(needle) ||
        (item.body || '')
          .toLowerCase()
          .includes(needle)
      );
    });
  }, [items, unreadOnly, cat, query]);


  /* 🗂 گروه‌بندی — پین‌شده‌ها جداگانه بالای همه */
  const pinned = filtered.filter(
    (item) => item.pinned,
  );

  const rest = filtered.filter(
    (item) => !item.pinned,
  );

  const groups = useMemo(() => {
    const buckets = [[], [], [], []];

    for (const item of rest) {
      buckets[dateGroup(item.created_at)].push(item);
    }

    return buckets;
  }, [rest]);


  const cats = useMemo(() => {
    const seen = new Set(
      items.map((item) => item.category),
    );

    return Object.keys(CAT_LABELS).filter(
      (key) => seen.has(key),
    );
  }, [items]);


  /* ✔ Smart Read — «بازکردن اعلان» (= کلیک) خودش
     خواندن است؛ مشاهده‌ی لیست هیچ‌کدام را خوانده
     نمی‌کند. با لینک ⇒ ناوبری Deep Link؛ بدون لینک
     ⇒ بازشدن بدنه در همان‌جا (بازشدن = خواندن). */
  const openItem = (item) => {
    haptic('light');

    if (!item.read) {
      readMutation.mutate([item.id]);
    }

    if (item.link) {
      navigate(item.link);
      return;
    }

    setOpenIds((prev) => {
      const next = new Set(prev);

      if (next.has(item.id)) {
        next.delete(item.id);
      } else {
        next.add(item.id);
      }

      return next;
    });
  };


  const headerAction = unread > 0
    ? (
      <button
        type="button"
        className="btn btn-d"
        style={{
          minHeight: 32,
          padding: '5px 9px',
          fontSize: 'var(--fs-cap)',
        }}
        onClick={() => {
          haptic('light');

          readMutation.mutate(null);
        }}
        disabled={readMutation.isPending}
        aria-label="خواندن همه"
      >
        {
          readMutation.isPending
            ? <Spinner size={14} />
            : '✓'
        }

        خواندن همه
      </button>
    )
    : null;


  const renderRow = (item, index) => {
    const [
      soft,
      color,
    ] = TONE_COLORS[item.tone] || TONE_COLORS.blue;

    const [prioLabel, prioColor] =
      PRIO_META[item.priority] ||
      PRIO_META.normal;

    const expanded = openIds.has(item.id);

    return (
      <div
        key={item.id}
        className="pop-in"
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: 'var(--sp-3)',
          padding: '11px 4px',
          borderTop:
            index === 0
              ? 'none'
              : '1px solid var(--line)',
          animationDelay: `${Math.min(
            index * 25, 240)}ms`,
        }}
      >
        <div
          style={{
            width: 34,
            height: 34,
            borderRadius: 'var(--r-md)',
            background: soft,
            color,
            display: 'grid',
            placeItems: 'center',
            fontSize: 'var(--fs-lg)',
            flexShrink: 0,
          }}
        >
          {item.icon}
        </div>

        <button
          type="button"
          onClick={() => openItem(item)}
          style={{
            all: 'unset',
            flex: 1,
            minWidth: 0,
            cursor: 'pointer',
          }}
          aria-expanded={
            item.link
              ? undefined
              : expanded
          }
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            {!item.read && (
              <span
                aria-hidden="true"
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: '50%',
                  background: 'var(--t-acc-md)',
                  flexShrink: 0,
                }}
              />
            )}

            {item.pinned && (
              <span
                aria-label="سنجاق‌شده"
                style={{ fontSize: 'var(--fs-cap)' }}
              >
                📌
              </span>
            )}

            <b
              style={{
                fontSize: 'var(--fs-meta)',
                flex: 1,
                minWidth: 0,
              }}
            >
              {item.title}
            </b>

            {item.count > 1 && (
              <span
                className="badge b-pur"
                title="موجهای چندباره‌ی یکدست"
                style={{
                  fontSize: 'var(--fs-cap)',
                  padding: '1px 6px',
                }}
              >
                ×{faNum(item.count)}
              </span>
            )}

            {prioLabel && (
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: 'var(--r-pill)',
                  background: prioColor,
                  flexShrink: 0,
                }}
                title={prioLabel}
              />
            )}
          </div>

          <div
            style={{
              color: 'var(--tx2)',
              fontSize: 'var(--fs-cap)',
              marginTop: 3,
              lineHeight: 1.7,
              whiteSpace: 'pre-line',
              display: expanded
                ? 'block'
                : '-webkit-box',
              WebkitLineClamp: expanded
                ? 'unset'
                : 2,
              WebkitBoxOrient: 'vertical',
              overflow: 'hidden',
            }}
          >
            {item.body}
          </div>

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--sp-2)',
              marginTop: 5,
              color: 'var(--txm)',
              fontSize: 'var(--fs-cap)',
            }}
          >
            <span>
              {timeAgo(item.created_at)}
            </span>

            <span
              className="badge b-gray"
              style={{
                fontSize: 'var(--fs-cap)',
                padding: '1px 5px',
              }}
            >
              {CAT_LABELS[item.category] ||
                item.category}
            </span>

            {item.link ? (
              <span
                style={{
                  marginInlineStart: 'auto',
                  color: 'var(--acc)',
                  fontSize: 'var(--fs-sm)',
                }}
                aria-hidden="true"
              >
                ←
              </span>
            ) : (
              <span
                style={{
                  marginInlineStart: 'auto',
                }}
                aria-hidden="true"
              >
                {expanded ? '▲' : '▼'}
              </span>
            )}
          </div>
        </button>

        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 'var(--sp-1)',
            flexShrink: 0,
          }}
        >
          <button
            type="button"
            onClick={() => {
              haptic('light');

              pinMutation.mutate({
                id: item.id,
                pinned: !item.pinned,
              });
            }}
            disabled={pinMutation.isPending}
            title={
              item.pinned
                ? 'برداشتن سنجاق'
                : 'سنجاق بالا'
            }
            aria-label={
              item.pinned
                ? 'برداشتن سنجاق'
                : 'سنجاق بالا'
            }
            style={{
              all: 'unset',
              cursor: 'pointer',
              opacity: item.pinned ? 1 : 0.5,
              fontSize: 'var(--fs-meta)',
            }}
          >
            📌
          </button>

          <button
            type="button"
            onClick={() => {
              haptic('light');

              deleteMutation.mutate(item.id);
            }}
            disabled={deleteMutation.isPending}
            title="حذف اعلان"
            aria-label="حذف اعلان"
            style={{
              all: 'unset',
              cursor: 'pointer',
              color: 'var(--txm)',
              fontSize: 'var(--fs-meta)',
            }}
          >
            ✕
          </button>
        </div>
      </div>
    );
  };


  return (
    <>
      <Header
        title="مرکز اعلان‌ها"
        subtitle={
          unread > 0
            ? `${faNum(unread)} اعلان خوانده‌نشده`
            : 'همه‌ی رویدادهای مهم حسابت'
        }
        right={headerAction}
        backTo="/me"
      />

      <main
        className="page fade-up"
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 'var(--sp-3)',
          paddingInline: 12,
        }}
      >
        {/* 🎛 نوار ابزار — جست‌وجو + سوییچ unread + دسته‌ها */}
        <div
          className="card fade-up"
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 9,
            padding: '10px 12px',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}
          >
            <span
              style={{
                color: 'var(--txm)',
                fontSize: 'var(--fs-md)',
              }}
              aria-hidden="true"
            >
              🔎
            </span>

            <input
              type="search"
              value={query}
              onChange={(event) =>
                setQuery(event.target.value)
              }
              placeholder="جست‌وجو در اعلان‌ها…"
              aria-label="جست‌وجو در اعلان‌ها"
              className="input"
              style={{
                flex: 1,
                minHeight: 34,
                padding: '7px 11px',
                fontSize: 'var(--fs-meta)',
              }}
            />

            <button
              type="button"
              onClick={() => {
                haptic('light');

                setUnreadOnly((v) => !v);
              }}
              aria-pressed={unreadOnly}
              className="tab-btn"
              style={{
                minHeight: 30,
                padding: '4px 9px',
                fontSize: 'var(--fs-cap)',
                flexShrink: 0,
                ...(unreadOnly
                  ? {
                    background:
                      'var(--soft-acc-2)',
                    borderColor: 'var(--t-acc-md)',
                    color: 'var(--t-acc-hi)',
                  }
                  : {}),
              }}
            >
              خوانده‌نشده
            </button>
          </div>

          {cats.length > 0 && (
            <div
              style={{
                display: 'flex',
                gap: 6,
                flexWrap: 'nowrap',
                overflowX: 'auto',
                scrollbarWidth: 'none',
                paddingBottom: 2,
              }}
              role="tablist"
              aria-label="فیلتر دسته"
            >
              {['all', ...cats].map((key) => {
                const active = cat === key;

                return (
                  <button
                    key={key}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    onClick={() => {
                      haptic('light');

                      setCat(key);
                    }}
                    className={
                      active
                        ? 'tab-btn active'
                        : 'tab-btn'
                    }
                    style={{
                      fontSize: 'var(--fs-cap)',
                      padding: '4px 9px',
                      minHeight: 28,
                      flexShrink: 0,
                    }}
                  >
                    {
                      key === 'all'
                        ? 'همه'
                        : CAT_LABELS[key] || key
                    }
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {
          isPending
          && [0, 1, 2, 3].map((key) => (
            <div
              key={key}
              className="skeleton"
              style={{
                height: 66,
                borderRadius: 'var(--r-md)',
              }}
            />
          ))
        }

        {
          isError
          && (
            <PageError
              text="اعلان‌ها بارگذاری نشد"
              onRetry={() => refetch()}
            />
          )
        }

        {
          !isPending
          && !isError
          && items.length === 0
          && (
            <EmptyState icon="🔔">
              هنوز اعلانی نداری
              <br />
              هر اتفاق مهم حسابت
              این‌جا خبرت می‌کنیم
            </EmptyState>
          )
        }

        {
          !isPending
          && !isError
          && items.length > 0
          && filtered.length === 0
          && (
            <div className="empty card">
              <div style={{ fontSize: 24 }}>
                🔍
              </div>

              <p>
                نتیجه‌ای پیدا نشد
              </p>

              <span
                style={{
                  color: 'var(--txm)',
                  fontSize: 'var(--fs-cap)',
                }}
              >
                فیلترها یا کلمات را ساده‌تر کن
              </span>
            </div>
          )
        }

        {/* 📌 سنجاق‌شده‌ها — همیشه بالای همه */}
        {
          pinned.length > 0
          && (
            <section
              className="card fade-up"
              style={{ padding: '0 12px' }}
            >
              <div
                style={{
                  color: 'var(--txm)',
                  fontSize: 'var(--fs-cap)',
                  padding: '9px 4px 0',
                  fontWeight: 700,
                }}
              >
                📌 سنجاق‌شده‌ها
              </div>

              {pinned.map(renderRow)}
            </section>
          )
        }

        {/* 🗂 گروه‌های تاریخی */}
        {
          groups.map((bucket, gi) => (
            bucket.length > 0 && (
              <section
                key={gi}
                className="card fade-up"
                style={{ padding: '0 12px' }}
              >
                <div
                  style={{
                    color: 'var(--txm)',
                    fontSize: 'var(--fs-cap)',
                    padding: '9px 4px 0',
                    fontWeight: 700,
                  }}
                >
                  {GROUP_TITLES[gi]}
                  {' · '}
                  <span style={{ fontWeight: 400 }}>
                    {faNum(bucket.length)}
                  </span>
                </div>

                {bucket.map(renderRow)}
              </section>
            )
          ))
        }
      </main>
    </>
  );
}
