import {
  Routes,
  Route,
  Navigate,
  useLocation,
  useNavigationType,
  useNavigate,
} from 'react-router-dom';

import {
  lazy,
  Suspense,
  useEffect,
  useRef,
} from 'react';

import {
  getStartParam,
  initTelegram,
} from './lib/telegram';

import {
  useAuthStore,
} from './stores/authStore';

import BottomNav from './components/layout/BottomNav';
import SwipeBack from './components/layout/SwipeBack';
import Toast from './components/shared/Toast';

import ErrorBoundary from './components/shared/ErrorBoundary';

import {
  LoadingScreen,
} from './components/shared/Loading';

import AuthError from './components/shared/AuthError';

import Register from './components/shared/Register';

import Onboarding from './components/shared/Onboarding';


/* صفحات اصلی — ۵ تب اصلی EAGER می‌مانند:
   سوییچ تب‌های پرتردد بدون حتی یک فریم
   انتظار چانک (هماهنگ با قانون Smooth
   First). هر مسیر دیگر = چانک جدای خودش
   (Code Splitting موج ۴.۶۰) */

import Dashboard from './pages/Dashboard';
import Learn from './pages/Learn';
import Schedule from './pages/Schedule';
import Grades from './pages/Grades';
import Me from './pages/Me';


/* ── خانواده‌ی اسکلت برای Fallback مسیرها ──
   کروم لودینگِ هر صفحه = همان صفحه؛ یعنی
   لود چانک هم با آینه‌ی Layout واقعی رخ
   می‌دهد، نه صفحه‌ی خالی (Perceived
   Performance) */
import {
  SkPlanCard,
  SkRowList,
  MeSkeleton,
  NotificationsSkeleton,
  ProfileSkeleton,
  SubscriptionSkeleton,
  QuestionBankSkeleton,
  ExamLessonsSkeleton,
  ExamHistorySkeleton,
  QuestionsListSkeleton,
  SearchResultsSkeleton,
  TicketsSkeleton,
  FaqListSkeleton,
  AdminHomeSkeleton,
  AnalyticsSkeleton,
  AuditLogSkeleton,
  SettingsSkeleton,
  GradesAdminSkeleton,
  ScheduleAdminSkeleton,
  LibraryTilesSkeleton,
  LibraryRowsSkeleton,
  UsersListSkeleton,
  UsersActionsSkeleton,
  AdminOpsSkeleton,
  ContentHomeSkeleton,
} from './components/shared/skeletons';


/* هوشیار و جست‌وجو */

/* ─────────────────────────────────────────────
   Code Splitting مبتنی بر مسیر (موج ۴.۶۰)
   چرا: تک‌چانک قبلی ~۶۱۷KB بود و ۳۴ صفحه —
   از جمله ۲۱ صفحه‌ی مدیریتی که دانشجوی عادی
   هرگز نمی‌بیند — همگی در اولین لود دانلود
   و parse می‌شدند (هزینه‌ی FCP/TTI روی
   گوشی‌های ضعیف). حالا هر مسیر چانک خودش را
   دارد و Vite آن‌ها را On-Demand می‌آورد.
   قراردادها:
   ۱) کامپوننت Lazy ثابت در سطح ماژول ساخته
      می‌شود ⇒ ریمونت/ری‌فچ چانک هرگز.
   ۲) Fallback = اسکلت اختصاصی همان صفحه
      (نه صفحه‌ی خالی، نه اسپینر عمومی) ⇒
      صفر Flicker و ظاهر «همیشه آماده».
   ۳) prefetch بیکار (پایین فایل) مسیرهای
      محتمل را از قبل گرم می‌کند.
───────────────────────────────────────────── */


function lazyScreen(
  importer,
  Fallback,
  exportName = 'default'
) {
  const Comp = lazy(() =>
    importer().then((module) => ({
      default: module[exportName],
    }))
  );

  return function LazyScreen() {
    return (
      <Suspense
        fallback={
          <main className="page">
            <Fallback />
          </main>
        }
      >
        <Comp />
      </Suspense>
    );
  };
}


const AiHomeScreen = lazyScreen(
  () => import('./pages/Ai/AiHome'),
  () => <SkRowList n={4} />
);

const AiImageScreen = lazyScreen(
  () => import('./pages/Ai/AiImage'),
  () => <SkRowList n={3} />
);

const GlobalSearchScreen = lazyScreen(
  () => import('./pages/Search/GlobalSearch'),
  SearchResultsSkeleton
);


/* صفحات یادگیری */

const QuestionsScreen = lazyScreen(
  () => import('./pages/Learn/Questions'),
  QuestionsListSkeleton
);

const ExamCenterScreen = lazyScreen(
  () => import('./pages/Learn/ExamCenter'),
  ExamLessonsSkeleton
);

const QuestionHistoryScreen = lazyScreen(
  () =>
    import('./pages/Learn/QuestionHistory'),
  ExamHistorySkeleton
);

const MyQuestionsScreen = lazyScreen(
  () => import('./pages/Learn/MyQuestions'),
  QuestionBankSkeleton
);

const ResourcesScreen = lazyScreen(
  () => import('./pages/Learn/Resources'),
  LibraryTilesSkeleton
);

const ReferencesScreen = lazyScreen(
  () => import('./pages/Learn/References'),
  LibraryRowsSkeleton
);


/* حساب کاربری */

const ProfileScreen = lazyScreen(
  () => import('./pages/Me/Profile'),
  ProfileSkeleton
);

/* 👑 موج P1/P2 — Prestige: نشان‌ها، میدان رقابت، HeroCard */
const BadgesScreen = lazyScreen(
  () => import('./pages/Me/Badges'),
  TicketsSkeleton
);

const LeaderboardScreen = lazyScreen(
  () => import('./pages/Leaderboard/index'),
  UsersListSkeleton
);

const RankHeroScreen = lazyScreen(
  () => import('./pages/Rank/HeroCard'),
  ProfileSkeleton
);

const NotificationsScreen = lazyScreen(
  () => import('./pages/Me/Notifications'),
  NotificationsSkeleton,
  'Notifications'
);

// 🔔 موج ۴.۹۰ — مرکز اعلان (inbox) جدا از
// «تنظیمات اعلان‌ها»؛‌ اسکلت فهرستی تیکت‌ها
// چیدمان همین صفحه را هم پوشش می‌دهد
const NotificationCenterScreen = lazyScreen(
  () => import('./pages/Me/NotificationCenter'),
  FaqListSkeleton,
  'NotificationCenter'
);

const SubscriptionScreen = lazyScreen(
  () => import('./pages/Me/Subscription'),
  SubscriptionSkeleton
);

// 🌊 W2 — لندینگ بازگشت از درگاه زرین‌پال
const PaymentVerifyScreen = lazyScreen(
  () => import('./pages/Payment/Verify'),
  SubscriptionSkeleton
);

const TicketsScreen = lazyScreen(
  () => import('./pages/Me/Tickets'),
  TicketsSkeleton
);

const FaqScreen = lazyScreen(
  () => import('./pages/Me/FaqReports'),
  FaqListSkeleton,
  'Faq'
);

const ReportsScreen = lazyScreen(
  () => import('./pages/Me/FaqReports'),
  FaqListSkeleton,
  'Reports'
);


/* خانه‌های مدیریت */

const AdminHomeScreen = lazyScreen(
  () => import('./pages/Admin/AdminHome'),
  AdminHomeSkeleton
);

const ContentHomeScreen = lazyScreen(
  () => import('./pages/Admin/ContentHome'),
  ContentHomeSkeleton
);

const SubscriptionAdminScreen = lazyScreen(
  () =>
    import('./pages/Admin/SubscriptionAdmin'),
  () => (
    <>
      <SkPlanCard />
      <SkPlanCard />
      <SkPlanCard />
    </>
  )
);

const AiAdminScreen = lazyScreen(
  () => import('./pages/Admin/AiAdmin'),
  SettingsSkeleton
);

const AnalyticsScreen = lazyScreen(
  () => import('./pages/Admin/Analytics'),
  AnalyticsSkeleton
);

const AuditLogScreen = lazyScreen(
  () => import('./pages/Admin/AuditLog'),
  AuditLogSkeleton
);

const SystemSettingsScreen = lazyScreen(
  () => import('./pages/Admin/SystemSettings'),
  SettingsSkeleton
);

/* 🛡 مدیریت نقش‌ها — موج RBAC-W2 */
const RolesScreen = lazyScreen(
  () => import('./pages/Admin/Roles'),
  UsersListSkeleton,
  'AdminRoles'
);


/* مدیریت کاربران */

const AdminUsersScreen = lazyScreen(
  () => import('./pages/Admin/UserManagement'),
  UsersListSkeleton,
  'AdminUsers'
);

const AdminUserDetailScreen = lazyScreen(
  () => import('./pages/Admin/UserManagement'),
  UsersListSkeleton,
  'AdminUserDetail'
);

const AdminIntakesScreen = lazyScreen(
  () => import('./pages/Admin/UserManagement'),
  UsersActionsSkeleton,
  'AdminIntakes'
);

const AdminContentAdminsScreen = lazyScreen(
  () => import('./pages/Admin/UserManagement'),
  UsersActionsSkeleton,
  'AdminContentAdmins'
);

const AdminBlacklistScreen = lazyScreen(
  () => import('./pages/Admin/UserManagement'),
  UsersListSkeleton,
  'AdminBlacklist'
);


/* عملیات مدیریتی */

const AdminTicketsScreen = lazyScreen(
  () => import('./pages/Admin/AdminOperations'),
  AdminOpsSkeleton,
  'AdminTickets'
);

const BroadcastAdminScreen = lazyScreen(
  () => import('./pages/Admin/AdminOperations'),
  AdminOpsSkeleton,
  'BroadcastAdmin'
);

const PollAdminScreen = lazyScreen(
  () => import('./pages/Admin/AdminOperations'),
  AdminOpsSkeleton,
  'PollAdmin'
);

const NotificationsAdminScreen = lazyScreen(
  () => import('./pages/Admin/AdminOperations'),
  AdminOpsSkeleton,
  'NotificationsAdmin'
);


/* مدیریت سؤال و FAQ */

const ContentQuestionsScreen = lazyScreen(
  () => import('./pages/Admin/ContentAdmin'),
  QuestionsListSkeleton,
  'ContentQuestions'
);

const ContentFaqScreen = lazyScreen(
  () => import('./pages/Admin/ContentAdmin'),
  FaqListSkeleton,
  'ContentFaq'
);


/* مدیریت کتابخانه */

const BasicScienceAdminScreen = lazyScreen(
  () => import('./pages/Admin/ContentLibrary'),
  LibraryRowsSkeleton,
  'BasicScienceAdmin'
);

const ReferencesAdminScreen = lazyScreen(
  () => import('./pages/Admin/ContentLibrary'),
  LibraryRowsSkeleton,
  'ReferencesAdmin'
);

// 📥 URL-Import — صفحه‌ی درون‌ریزی محتوای راه‌دور
const UrlImportScreen = lazyScreen(
  () => import('./pages/Admin/UrlImport'),
  LibraryRowsSkeleton,
  'UrlImport'
);

const QbankAdminScreen = lazyScreen(
  () => import('./pages/Admin/ContentLibrary'),
  LibraryRowsSkeleton,
  'QbankAdmin'
);

const ContentReportsAdminScreen = lazyScreen(
  () => import('./pages/Admin/ContentLibrary'),
  AdminOpsSkeleton,
  'ContentReportsAdmin'
);


/* مدیریت برنامه و نمرات */

const AcademicScheduleAdminScreen = lazyScreen(
  () =>
    import(
      './pages/Admin/AcademicScheduleAdmin'
    ),
  ScheduleAdminSkeleton
);

const AcademicGradesAdminScreen = lazyScreen(
  () =>
    import(
      './pages/Admin/AcademicGradesAdmin'
    ),
  GradesAdminSkeleton
);



/* ─────────────────────────────────────────────
   بازیابی موقعیت اسکرول (Scroll Restoration)

   - POP (برگشت/جلو): موقعیت ذخیره‌شده‌ی همان
     ورودیِ تاریخچه بازیابی می‌شود — کاربر دقیقاً
     به جایی که بود برمی‌گردد
   - PUSH: از بالای صفحه‌ی جدید
   - REPLACE با همان pathname (مثل سینک پارامتر
     جست‌وجو): اسکرول دست‌نخورده می‌ماند
   - کلید ذخیره‌سازی location.key است که در POP
     همان کلیدِ قبلی برمی‌گردد (قرارداد
     react-router)
───────────────────────────────────────────── */
const scrollPositions = new Map();


function ScrollRestoration() {
  const location = useLocation();
  const navigationType = useNavigationType();

  const keyRef = useRef(location.key);
  const pathRef = useRef(location.pathname);

  // مرورگر نباید خودش بازیابی کند — ما
  // مسئولیم تا رفتار با POP/PUSH سازگار بماند
  useEffect(() => {
    try {
      if (
        'scrollRestoration' in window.history
      ) {
        const previous =
          window.history.scrollRestoration;

        window.history.scrollRestoration =
          'manual';

        return () => {
          window.history.scrollRestoration =
            previous;
        };

      }

    } catch (_) {
      // ignore
    }

    return undefined;
  }, []);


  // ذخیره‌ی پیوسته‌ی موقعیت ورودیِ جاری
  useEffect(() => {
    let raf = 0;

    const onScroll = () => {
      window.cancelAnimationFrame(raf);

      raf = window.requestAnimationFrame(
        () => {
          scrollPositions.set(
            keyRef.current,
            window.scrollY,
          );

          // سقف حافظه — قدیمی‌ترین ورودی‌ها
          // حذف می‌شوند
          if (scrollPositions.size > 80) {
            const oldest =
              scrollPositions
                .keys()
                .next()
                .value;

            scrollPositions.delete(oldest);
          }
        },
      );
    };

    window.addEventListener(
      'scroll',
      onScroll,
      { passive: true },
    );

    return () => {
      window.cancelAnimationFrame(raf);

      window.removeEventListener(
        'scroll',
        onScroll,
      );
    };
  }, []);


  useEffect(() => {
    const previousPath = pathRef.current;

    const pathChanged =
      previousPath !== location.pathname;

    pathRef.current = location.pathname;
    keyRef.current = location.key;

    const saved =
      navigationType === 'POP'
        ? scrollPositions.get(location.key)
        : undefined;

    if (typeof saved === 'number') {
      // بازیابی — دو فریم صبر تا پِیِنت کامل
      // شود + یک تلاش مجدد برای محتوای دیررشد
      window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
          window.scrollTo(0, saved);
        });
      });

      const retry = window.setTimeout(() => {
        if (
          window.scrollY === 0 &&
          saved > 0
        ) {
          window.scrollTo(0, saved);
        }
      }, 340);

      return () =>
        window.clearTimeout(retry);
    }

    if (
      pathChanged ||
      navigationType === 'PUSH'
    ) {
      window.scrollTo(0, 0);
    }

    return undefined;

    // eslint-disable-next-line
    // react-hooks/exhaustive-deps
  }, [location.key]);


  return null;
}


function AdminRoute({
  children,
}) {
  const user = useAuthStore((state) => state.user);
  const location = useLocation();
  const path = location.pathname;
  const requiredByRoute = [
    ['/admin/subscription', ['subscription.manage']],
    ['/admin/ai', ['ai.manage']],
    ['/admin/analytics', ['stats.view']],
    ['/admin/audit', ['audit.view']],
    ['/admin/settings', ['settings.manage', 'notifications.manage', 'backup.manage']],
    ['/admin/users', ['users.view', 'users.manage']],
    ['/admin/roles', ['roles.manage']],
    ['/admin/intakes', ['users.manage']],
    ['/admin/content-admins', ['roles.manage', 'users.manage']],
    ['/admin/blacklist', ['users.delete']],
    ['/admin/tickets', ['tickets.reply', 'tickets.manage']],
    ['/admin/broadcast', ['broadcast.send']],
    ['/admin/poll', ['broadcast.send']],
    ['/admin/notifications', ['notifications.manage', 'broadcast.send']],
  ];
  const required = requiredByRoute.find(([prefix]) => path === prefix
    || path.startsWith(`${prefix}/`))?.[1] || [];
  const legacy = {
    content_admin: ['content.manage'],
    content_scoped: ['content.scoped'],
    bot_admin: ['users.view', 'schedules.manage', 'broadcast.send'],
    broadcaster: ['broadcast.send'],
    support: ['tickets.reply'],
    reviewer: ['reports.review'],
    grade_rep: ['grades.scoped'],
  }[user?.role] || [];
  const actual = new Set([...(user?.perms || []), ...legacy]);
  const allowed = user?.role === 'admin'
    || (required.length ? required.some((permission) => actual.has(permission)) : actual.size > 0);

  if (!user || !allowed) return <Navigate to="/" replace />;
  return children;
}


function PermissionRoute({
  children,
  any = [],
}) {
  const user = useAuthStore((state) => state.user);
  const perms = new Set(user?.perms || []);
  const legacy = {
    content_admin: ['content.manage'],
    content_scoped: ['content.scoped'],
    bot_admin: ['schedules.manage'],
    grade_rep: ['grades.scoped'],
  }[user?.role] || [];
  const allowed = user?.role === 'admin'
    || any.some((permission) => perms.has(permission) || legacy.includes(permission));

  if (!user || !allowed) {
    return <Navigate to="/" replace />;
  }
  return children;
}


function ContentAdminRoute({
  children,
}) {
  const user = useAuthStore(
    (state) => state.user
  );

  const allowedRoles = [
    'admin',
    'content_admin',
  ];

  /* 🛡 RBAC-W3 (افزایشی): مجوز content.* هم عبور
     می‌دهد — معادل دقیق گیت get_content_admin_user
     و هوک has_perm در بک‌اند */
  const hasContentPerm = (user?.perms || []).some(
    (perm) =>
      perm === 'content.manage' ||
      perm === 'content.scoped'
  );

  if (
    !user ||
    (
      !allowedRoles.includes(
        user.role
      ) && !hasContentPerm
    )
  ) {
    return (
      <Navigate
        to="/"
        replace
      />
    );
  }

  return children;
}


export default function App() {
  const loading = useAuthStore(
    (state) => state.loading
  );

  const error = useAuthStore(
    (state) => state.error
  );

  const init = useAuthStore(
    (state) => state.init
  );

  /* key = pathname → با هر تغییر مسیر، دیوار
     خطا رزت می‌شود؛ اگر یک صفحه کرش کند، رفتن
     به جای دیگر دیوارِ تازه می‌آورد و کاربر در
     صفحه‌ی خطا گیر نمی‌کند */
  const location = useLocation();


  useEffect(() => {
    initTelegram();
    init();
  }, [init]);


  const user = useAuthStore(
    (state) => state.user
  );


  /* 👑 موج P0 — دیپ‌لینک startapp سبک:
     rank_<uid> (اشتراک کارت رنک) فعلاً به
     همان کارت Prestigeِ پروفایل می‌رسد؛
     HeroCard عمومی در P2 می‌آید. هر پارامتر
     ناشناخته بی‌خطر نادیده گرفته می‌شود. */
  const navigate = useNavigate();

  useEffect(() => {
    if (!user) return;

    const startParam = (
      getStartParam() || ''
    ).trim();

    if (!startParam) return;

    try {
      if (
        /^rank_[0-9a-zA-Z]+$/.test(
          startParam
        )
      ) {
        navigate('/me/profile');
      }
      /* پارامترهای ناشناخته: ignore */
    } catch (_) {
      /* ناوبری دیپ‌لینک هرگز اپ را نمی‌شکند */
    }
    /* eslint-disable-next-line
       react-hooks/exhaustive-deps */
  }, [user]);


  /* 🔥 Prefetch بیکار (موج ۴.۶۰) — وقتی اپ بالا
     آمد و کاربر شناخته شد، در زمان بیکارِ
     مرورگر چانک مسیرهای محتمل‌بعدی دانلود می‌شود
     تا اولین ناوبری هم «آنی» باشد. هزینه: چند
     ده KB در پس‌زمینه — اثر روی FCP: صفر. */
  useEffect(() => {
    if (!user) return undefined;

    const warm = () => {
      /* هوشیار — پرترددترین مقصد فرعی همه */
      import('./pages/Ai/AiHome');

      if (
        ['admin', 'content_admin'].includes(
          user.role
        )
      ) {
        import('./pages/Admin/AdminHome');
        import('./pages/Admin/ContentHome');
      }
    };

    if (
      typeof window.requestIdleCallback ===
      'function'
    ) {
      const idleId =
        window.requestIdleCallback(warm, {
          timeout: 4500,
        });

      return () =>
        window.cancelIdleCallback(idleId);
    }

    const timerId = window.setTimeout(
      warm,
      1800
    );

    return () =>
      window.clearTimeout(timerId);
  }, [user]);


  /* رویدادهای احراز هویت api.js — وقتی وسط نشست
     دسترسی کاربر باطل شود (تعلیق، حذف، و…) به‌جای
     صفحات نیمه‌شکسته، مستقیم به صفحه وضعیت می‌رویم */
  const forceError = useAuthStore(
    (state) => state.forceError
  );


  useEffect(() => {
    const EVENT_TO_STATE = {
      'auth:not_registered':
        'not_registered',
      'auth:pending':
        'pending_approval',
      'auth:suspended':
        'suspended',
      'auth:invalid':
        'invalid_init_data',
    };

    const listeners = Object.entries(
      EVENT_TO_STATE
    ).map(([event, code]) => {
      const handler = () =>
        forceError(code);

      window.addEventListener(
        event,
        handler
      );

      return [event, handler];
    });


    return () => {
      listeners.forEach(
        ([event, handler]) =>
          window.removeEventListener(
            event,
            handler
          )
      );
    };
  }, [forceError]);


  if (loading) {
    return (
      <LoadingScreen />
    );
  }


  /* ثبت‌نام انجام نشده یا در انتظار
     تأیید → ویزارد ثبت‌نام داخل
     مینی‌اپ (سینک کامل با بات) */

  if (
    error === 'not_registered' ||
    error === 'pending_approval'
  ) {
    return (
      <Register />
    );
  }


  if (error) {
    return (
      <AuthError
        error={error}
      />
    );
  }


  return (
    <div
      className="app-root"
      dir="rtl"
    >
      <ScrollRestoration />

      <Toast />

      {/* معرفی اولین ورود — بعد از
          تأیید حساب نمایش داده می‌شود */}
      <Onboarding />

      {/* ژست بازگشت از لبه‌ی راست — کل
          ناوبری را با همان قواعد Header هدایت
          می‌کند */}
      <SwipeBack />

      {/* 🧯 دیوار آتش: کرش هر صفحه = صفحه‌ی
          بازیابی، نه صفحه‌ی تاریک */}
      <ErrorBoundary
        key={location.pathname}
      >
      <Routes>
        {/* صفحات اصلی */}

        <Route
          path="/"
          element={
            <Dashboard />
          }
        />

        <Route
          path="/learn"
          element={
            <Learn />
          }
        />

        <Route
          path="/schedule"
          element={
            <Schedule />
          }
        />

        <Route
          path="/grades"
          element={
            <Grades />
          }
        />


        {/* هوشیار و جست‌وجو */}

        <Route
          path="/ai"
          element={
            <AiHomeScreen />
          }
        />

        <Route
          path="/ai/c/:convId"
          element={
            <AiHomeScreen />
          }
        />

        <Route
          path="/ai/image"
          element={
            <AiImageScreen />
          }
        />

        <Route
          path="/search"
          element={
            <GlobalSearchScreen />
          }
        />


        {/* یادگیری */}

        <Route
          path="/learn/questions"
          element={
            <QuestionsScreen />
          }
        />

        <Route
          path="/learn/exams"
          element={
            <ExamCenterScreen />
          }
        />

        <Route
          path="/learn/question-history"
          element={
            <QuestionHistoryScreen />
          }
        />

        <Route
          path="/learn/my-questions"
          element={
            <MyQuestionsScreen />
          }
        />

        <Route
          path="/learn/resources"
          element={
            <ResourcesScreen />
          }
        />

        <Route
          path="/learn/references"
          element={
            <ReferencesScreen />
          }
        />


        {/* حساب کاربری */}

        <Route
          path="/me"
          element={
            <Me />
          }
        />

        <Route
          path="/me/profile"
          element={
            <ProfileScreen />
          }
        />

        <Route
          path="/me/badges"
          element={
            <BadgesScreen />
          }
        />

        <Route
          path="/leaderboard"
          element={
            <LeaderboardScreen />
          }
        />

        <Route
          path="/rank/:uid"
          element={
            <RankHeroScreen />
          }
        />

        <Route
          path="/me/notifications"
          element={
            <NotificationsScreen />
          }
        />

        <Route
          path="/me/notifications/inbox"
          element={
            <NotificationCenterScreen />
          }
        />

        <Route
          path="/me/subscription"
          element={
            <SubscriptionScreen />
          }
        />

        <Route
          path="/payment/verify"
          element={
            <PaymentVerifyScreen />
          }
        />

        <Route
          path="/me/tickets"
          element={
            <TicketsScreen />
          }
        />

        <Route
          path="/me/faq"
          element={
            <FaqScreen />
          }
        />

        <Route
          path="/me/reports"
          element={
            <ReportsScreen />
          }
        />


        {/* خانه مدیریت */}

        <Route
          path="/admin"
          element={
            <AdminRoute>
              <AdminHomeScreen />
            </AdminRoute>
          }
        />


        {/* مدیریت اشتراک */}

        <Route
          path="/admin/subscription"
          element={
            <AdminRoute>
              <SubscriptionAdminScreen />
            </AdminRoute>
          }
        />


        {/* مدیریت هوشیار */}

        <Route
          path="/admin/ai"
          element={
            <AdminRoute>
              <AiAdminScreen />
            </AdminRoute>
          }
        />


        {/* آمار و لاگ فعالیت */}

        <Route
          path="/admin/analytics"
          element={
            <AdminRoute>
              <AnalyticsScreen />
            </AdminRoute>
          }
        />

        <Route
          path="/admin/audit"
          element={
            <AdminRoute>
              <AuditLogScreen />
            </AdminRoute>
          }
        />

        <Route
          path="/admin/settings"
          element={
            <AdminRoute>
              <SystemSettingsScreen />
            </AdminRoute>
          }
        />


        {/* مدیریت کاربران */}

        <Route
          path="/admin/users"
          element={
            <AdminRoute>
              <AdminUsersScreen />
            </AdminRoute>
          }
        />

        <Route
          path="/admin/users/:uid"
          element={
            <AdminRoute>
              <AdminUserDetailScreen />
            </AdminRoute>
          }
        />

        {/* 🛡 RBAC-W2 — مدیریت نقش‌ها/مجوزها */}
        <Route
          path="/admin/roles"
          element={
            <AdminRoute>
              <RolesScreen />
            </AdminRoute>
          }
        />

        <Route
          path="/admin/intakes"
          element={
            <AdminRoute>
              <AdminIntakesScreen />
            </AdminRoute>
          }
        />

        <Route
          path="/admin/content-admins"
          element={
            <AdminRoute>
              <AdminContentAdminsScreen />
            </AdminRoute>
          }
        />

        <Route
          path="/admin/blacklist"
          element={
            <AdminRoute>
              <AdminBlacklistScreen />
            </AdminRoute>
          }
        />


        {/* عملیات مدیریتی */}

        <Route
          path="/admin/tickets"
          element={
            <AdminRoute>
              <AdminTicketsScreen />
            </AdminRoute>
          }
        />

        <Route
          path="/admin/broadcast"
          element={
            <AdminRoute>
              <BroadcastAdminScreen />
            </AdminRoute>
          }
        />

        <Route
          path="/admin/poll"
          element={
            <AdminRoute>
              <PollAdminScreen />
            </AdminRoute>
          }
        />

        <Route
          path="/admin/notifications"
          element={
            <AdminRoute>
              <NotificationsAdminScreen />
            </AdminRoute>
          }
        />


        {/* خانه محتوا */}

        <Route
          path="/admin/content"
          element={
            <ContentAdminRoute>
              <ContentHomeScreen />
            </ContentAdminRoute>
          }
        />


        {/* سؤال و FAQ */}

        <Route
          path="/admin/content/questions"
          element={
            <ContentAdminRoute>
              <ContentQuestionsScreen />
            </ContentAdminRoute>
          }
        />

        <Route
          path="/admin/content/faq"
          element={
            <ContentAdminRoute>
              <ContentFaqScreen />
            </ContentAdminRoute>
          }
        />


        {/* برنامه و نمرات */}

        <Route
          path="/admin/content/schedule"
          element={
            <PermissionRoute any={['schedules.manage', 'content.manage']}>
              <AcademicScheduleAdminScreen />
            </PermissionRoute>
          }
        />

        <Route
          path="/admin/content/grades"
          element={
            <PermissionRoute any={['grades.manage', 'grades.scoped', 'content.manage', 'content.scoped']}>
              <AcademicGradesAdminScreen />
            </PermissionRoute>
          }
        />


        {/* کتابخانه محتوا */}

        <Route
          path="/admin/content/basic-science"
          element={
            <ContentAdminRoute>
              <BasicScienceAdminScreen />
            </ContentAdminRoute>
          }
        />

        <Route
          path="/admin/content/references"
          element={
            <ContentAdminRoute>
              <ReferencesAdminScreen />
            </ContentAdminRoute>
          }
        />

        <Route
          path="/admin/content/qbank"
          element={
            <PermissionRoute any={['content.manage', 'content.scoped']}>
              <QbankAdminScreen />
            </PermissionRoute>
          }
        />

        {/* 📥 URL-Import — سرور دانلود و به تلگرام منتقل می‌کند */}
        <Route
          path="/admin/content/url-import"
          element={
            <PermissionRoute any={['content.manage', 'content.scoped']}>
              <UrlImportScreen />
            </PermissionRoute>
          }
        />

        <Route
          path="/admin/content/reports"
          element={
            <ContentAdminRoute>
              <ContentReportsAdminScreen />
            </ContentAdminRoute>
          }
        />


        {/* مسیرهای سازگاری */}

        <Route
          path="/questions"
          element={
            <Navigate
              to="/learn/questions"
              replace
            />
          }
        />

        <Route
          path="/resources"
          element={
            <Navigate
              to="/learn/resources"
              replace
            />
          }
        />

        <Route
          path="/references"
          element={
            <Navigate
              to="/learn/references"
              replace
            />
          }
        />

        <Route
          path="/hoshyar"
          element={
            <Navigate
              to="/ai"
              replace
            />
          }
        />

        <Route
          path="/find"
          element={
            <Navigate
              to="/search"
              replace
            />
          }
        />


        {/* مسیر نامعتبر */}

        <Route
          path="*"
          element={
            <Navigate
              to="/"
              replace
            />
          }
        />
      </Routes>
      </ErrorBoundary>

      {/* کرومِ ناوبری بیرون از دیوارِ صفحه‌هاست؛
          پس دیوارِ مخصوصِ خودش را دارد — fallback={null}
          یعنی اگر نوار کرش کند فقط نوار می‌رود و اپ
          زنده می‌ماند (هیچ خطای تک‌کامپوننتی دیگر کل
          درخت را با خود نمی‌برد = پایان صفحه‌ی تاریک) */}
      <ErrorBoundary
        fallback={null}
      >
        <BottomNav />
      </ErrorBoundary>
    </div>
  );
}
