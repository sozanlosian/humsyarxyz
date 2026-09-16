import {
  useEffect,
  useRef,
  useState,
} from 'react';

import {
  useQuery,
} from '@tanstack/react-query';

import {
  useLocation,
  useNavigate,
} from 'react-router-dom';

import api from '../../lib/api';

import {
  haptic,
} from '../../lib/telegram';


const TABS = [
  {
    path: '/',
    icon: '🩺',
    label: 'داشبورد',
  },

  {
    path: '/learn',
    icon: '📖',
    label: 'یادگیری',
  },

  {
    path: '/schedule',
    icon: '📅',
    label: 'برنامه',
  },

  {
    path: '/grades',
    icon: '📊',
    label: 'نمرات',
  },

  {
    path: '/me',
    icon: '🙋',
    label: 'من',
  },
];


const MORE = [
  {
    path: '/ai',
    icon: '🤖',
    label: 'هوشیار',
    desc: 'دستیار آموزشی هوشمند',
  },

  {
    path: '/search',
    icon: '🔍',
    label: 'جست‌وجوی سراسری',
    desc: 'سؤال، منبع و کتاب در یک‌جا',
  },

  {
    path: '/me/profile',
    icon: '👤',
    label: 'پروفایل',
    desc: 'اطلاعات و آمار حساب',
  },

  {
    path: '/me/notifications',
    icon: '🔔',
    label: 'اعلان‌ها',
    desc: 'تنظیم یادآوری‌ها',
  },

  {
    path: '/me/subscription',
    icon: '💳',
    label: 'اشتراک',
    desc: 'مدیریت پلن و خرید',
  },

  {
    path: '/me/tickets',
    icon: '🎫',
    label: 'پشتیبانی',
    desc: 'تیکت و گفت‌وگو',
  },

  {
    path: '/me/faq',
    icon: '❓',
    label: 'سؤالات متداول',
    desc: 'پاسخ‌های سریع',
  },

  {
    path: '/me/reports',
    icon: '🚩',
    label: 'گزارش ایراد',
    desc: 'اعلام خطای محتوا',
  },
];


function prefersReducedMotion() {
  try {
    return Boolean(
      window.matchMedia?.(
        '(prefers-reduced-motion: reduce)',
      )?.matches,
    );

  } catch (_) {
    return false;
  }
}


function matchesPath(
  pathname,
  path,
) {
  if (path === '/') {
    return pathname === '/';
  }

  return (
    pathname === path ||
    pathname.startsWith(
      `${path}/`,
    )
  );
}


function MoreSheet({
  onClose,
  unread = 0,
}) {
  const navigate =
    useNavigate();


  useEffect(() => {
    const previousOverflow =
      document.body
        .style
        .overflow;

    const closeWithEscape = (
      event,
    ) => {
      if (
        event.key === 'Escape'
      ) {
        onClose();
      }
    };

    document.body.style.overflow =
      'hidden';

    window.addEventListener(
      'keydown',
      closeWithEscape,
    );

    return () => {
      document.body.style.overflow =
        previousOverflow;

      window.removeEventListener(
        'keydown',
        closeWithEscape,
      );
    };
  }, [onClose]);


  const open = (path) => {
    haptic('light');

    onClose();

    navigate(path);
  };


  return (
    <div
      className="more-sheet"
      role="presentation"
      onClick={onClose}
    >
      <div
        className={
          'more-sheet__panel ' +
          'glass sheet-in'
        }
        role="dialog"
        aria-modal="true"
        aria-label="منوی بیشتر"
        onClick={(event) =>
          event.stopPropagation()
        }
      >
        <div className="more-sheet__handle" />

        <div className="more-sheet__title">
          دسترسی سریع
        </div>

        {MORE.map(
          (
            item,
            index,
          ) => (
            <button
              type="button"
              key={item.path}
              className={
                'more-sheet__item ' +
                'pop-in'
              }
              style={{
                animationDelay:
                  `${index * 32}ms`,
              }}
              onClick={() =>
                open(item.path)
              }
            >
              <span className="more-sheet__item-icon">
                {item.icon}
              </span>

              <span className="more-sheet__item-text">
                <span className="more-sheet__item-title">
                  {item.label}
                </span>

                <span className="more-sheet__item-desc">
                  {item.desc}
                </span>
              </span>

              {item.path === '/ai' && (
                <span className="badge b-pur">
                  AI
                </span>
              )}

              {item.path ===
                '/me/tickets' &&
                unread > 0 && (
                  <span className="badge b-red">
                    {unread > 9
                      ? '+9'
                      : unread}{' '}
                    پاسخ جدید
                  </span>
                )}

              <span className="more-sheet__arrow">
                ←
              </span>
            </button>
          ),
        )}
      </div>
    </div>
  );
}


export default function BottomNav() {
  const location =
    useLocation();

  const navigate =
    useNavigate();

  const [
    showMore,
    setShowMore,
  ] = useState(false);


  const indicatorRef = useRef(null);

  // موقعیت قبلی اندیکاتور — مسافتِ جابه‌جایی،
  // مدت‌زمانِ سفر را تعیین می‌کند تا حرکت‌های
  // کوتاه چابک و پرش‌های دور، روان‌تر و کشدارتر
  // باشند (همان رفتاری که در اپ‌های سطح‌اول دیده
  // می‌شود)
  const prevIndexRef = useRef(null);

  const firstRunRef = useRef(true);


  /* 🧯 قانون طلایی هوک‌های React (ریشه‌ی باگ
     صفحه‌ی تاریک): هیچ هوکی نباید بعد از یک
     return شرطی بیاید. نسخه‌ی قبلی دو هوک
     (useRef + useEffect) را بعد از
     «if (…/admin) return null» صدا می‌زد؛
     با هر ورود به بخش مدیریت شمار هوک‌ها
     ۹→۷ کم می‌شد، React خطای مرگبارِ
     "Rendered fewer hooks than expected"
     می‌انداخت و چون این کامپوننت بیرونِ
     ErrorBoundary بود، کل درخت اپ unmount
     می‌شد. حالا همه‌ی هوک‌ها قبل از هر
     return شرطی‌اند و ترتیبشان در همه‌ی
     مسیرها ثابت است. */
  const isAdminSection =
    location.pathname.startsWith(
      '/admin',
    );


  useEffect(() => {
    setShowMore(false);
  }, [location.pathname]);


  /* ✅ Badge پاسخ جدید پشتیبانی —
     پولینگ سبک هر ۴۵ ثانیه؛ وقتی کاربر
     گفت‌وگو را باز کند، سمت سرور seen
     می‌شود و Badge خودکار پاک می‌شود.
     در مسیرهای مدیریت نوار دیده نمی‌شود،
     پس پولینگ خاموش است ولی خودِ هوک
     همیشه صدا زده می‌شود تا ترتیب هوک‌ها
     ثابت بماند (enabled گزینه است، هوک
     شرطی نیست). */
  const {
    data: unreadData,
  } = useQuery({
    queryKey: ['ticket-unread'],

    queryFn: () =>
      api
        .get('/api/tickets/unread-count')
        .then(
          (response) =>
            response.data,
        ),

    refetchInterval: 45_000,
    staleTime: 20_000,
    retry: false,
    enabled: !isAdminSection,
  });

  const unread = Math.max(
    0,
    Number(unreadData?.unread) || 0,
  );


  const moreActive =
    MORE.some(
      (item) =>
        matchesPath(
          location.pathname,
          item.path,
        ),
    );


  const tabIndex =
    TABS.findIndex(
      (item) =>
        matchesPath(
          location.pathname,
          item.path,
        ),
    );


  const activeIndex =
    moreActive
      ? TABS.length
      : Math.max(
          0,
          tabIndex,
        );


  // مسافت و مدت سفر اندیکاتور
  const previousIndex =
    prevIndexRef.current
    ?? activeIndex;

  const travelDistance = Math.abs(
    activeIndex - previousIndex,
  );

  const travelMs = Math.min(
    680,
    300 + travelDistance * 95,
  );


  // کش‌وجمع ارگانیک اندیکاتور (squash & stretch)
  // — تنها چیزی که در ناوبری «جریان» دارد همین
  // کپسول است؛ خودِ بار کاملاً بی‌حرکت می‌ماند.
  // نکته: guard مسیر مدیریت «داخل» افکت است —
  // خودِ هوک همیشه ثبت می‌شود (ترتیب هوک‌ها
  // ثابت می‌ماند) ولی در /admin هیچ کاری نمی‌کند
  // و prevIndex به‌روز نمی‌شود تا با بازگشت،
  // انیمیشن از همان تبِ قبلی ادامه یابد.
  useEffect(() => {
    if (isAdminSection) {
      return;
    }

    prevIndexRef.current = activeIndex;

    if (firstRunRef.current) {
      firstRunRef.current = false;
      return;
    }

    const indicator =
      indicatorRef.current;

    if (
      !indicator ||
      typeof indicator.animate !==
        'function' ||
      prefersReducedMotion()
    ) {
      return;
    }

    indicator.animate(
      [
        {
          transform:
            'scaleX(1) scaleY(1)',
        },

        {
          transform:
            'scaleX(1.34) ' +
            'scaleY(.84)',
          offset: 0.42,
        },

        {
          transform:
            'scaleX(1) scaleY(1)',
        },
      ],

      {
        duration:
          travelMs + 70,

        easing:
          'cubic-bezier(.22,.9,.26,1)',
      },
    );

    // eslint-disable-next-line
    // react-hooks/exhaustive-deps
  }, [location.pathname]);


  /* در بخش مدیریت (پنل/محتوا) نوار پایین
     نمایش داده نمی‌شود — این تنها return
     شرطی مجاز است: بعد از ثبتِ همه‌ی هوک‌ها */
  if (isAdminSection) {
    return null;
  }


  const go = (path) => {
    haptic('light');

    if (
      location.pathname !== path
    ) {
      navigate(path);
    }
  };


  return (
    <>
      {showMore && (
        <MoreSheet
          unread={unread}
          onClose={() =>
            setShowMore(false)
          }
        />
      )}

      <nav
        className="bottom-nav glass"
        aria-label="ناوبری اصلی"
        style={{
          '--active-index':
            activeIndex,
        }}
      >
        <div
          ref={indicatorRef}
          className="bottom-nav__indicator"
          aria-hidden="true"
          style={{
            transitionDuration:
              `${travelMs}ms`,
          }}
        />

        {TABS.map(
          (
            tab,
            index,
          ) => {
            const active =
              !moreActive &&
              index ===
                activeIndex;

            return (
              <button
                type="button"
                key={tab.path}
                className={
                  'bottom-nav__item ' +
                  (
                    active
                      ? 'bottom-nav__item--active'
                      : ''
                  )
                }
                onClick={() =>
                  go(tab.path)
                }
                aria-label={
                  tab.label
                }
                aria-current={
                  active
                    ? 'page'
                    : undefined
                }
              >
                <span
                  className="bottom-nav__icon"
                  style={{
                    position:
                      'relative',
                  }}
                >
                  {tab.icon}

                  {tab.path === '/me' &&
                    unread > 0 && (
                      <span
                        className="nav-badge"
                        aria-label={`${unread} پاسخ خوانده‌نشده`}
                      >
                        {unread > 99
                          ? '+99'
                          : unread}
                      </span>
                    )}
                </span>

                <span className="bottom-nav__label">
                  {tab.label}
                </span>
              </button>
            );
          },
        )}

        <button
          type="button"
          className={
            'bottom-nav__item ' +
            (
              moreActive
                ? 'bottom-nav__item--active'
                : ''
            )
          }
          onClick={() => {
            haptic('light');

            setShowMore(true);
          }}
          aria-label="بیشتر"
          aria-expanded={showMore}
        >
          <span className="bottom-nav__icon">
            ☰
          </span>

          <span className="bottom-nav__label">
            بیشتر
          </span>
        </button>
      </nav>
    </>
  );
}
