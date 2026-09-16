import { SkeletonLine } from './Loading';


/* ─────────────────────────────────────────────
   🦴 Skeleton Loading System — موج ۴.۴۰

   قانون طلایی: اسکلت «نسخه‌ی در حال ساخته‌شدن
   همان صفحه» است، نه چند باکس عمومی.

   معماری: همه‌ی بلوک‌ها از پایه‌ی مشترکِ
   `.skeleton` (شیم GPU در globals.css) و
   کرومِ واقعی کارت‌ها (card / card-glow /
   menu-row / grid2 / pbar / sec-title)
   ساخته می‌شوند؛ پس Border/Radius/Shadow/
   Spacing اسکلت با نسخه‌ی نهایی یکی است و
   لحظه‌ی پایانِ لودینگ نه Layout Shift داریم
   نه فلش.

   این فایل دو لایه دارد:
   ۱) بیلدرهای عمومیِ کوچک (SkHero، SkRowList…)
   ۲) کامپوزیتِ اختصاصی هر صفحه (Dashboard…)
───────────────────────────────────────────── */


/* ═══════════ لایه‌ی ۱: بیلدرها ═══════════ */


function SkCircle({ size }) {
  return (
    <div
      className="skeleton"
      style={{
        width: size,
        height: size,
        flexShrink: 0,
        borderRadius: '50%',
      }}
    />
  );
}


function SkSquare({ size, r = 14 }) {
  return (
    <div
      className="skeleton"
      style={{
        width: size,
        height: size,
        flexShrink: 0,
        borderRadius: r,
      }}
    />
  );
}


function SkPbar() {
  return (
    <div className="pbar">
      <div
        className="skeleton"
        style={{
          width: '100%',
          height: '100%',
          borderRadius: 'inherit',
        }}
      />
    </div>
  );
}


/* تیتر بخش — مثل «📋 جزئیات نمرات» */
export function SkSecTitle({ w = 110 }) {
  return (
    <div className="sec-title">
      <SkeletonLine width={w} height={11} />
    </div>
  );
}


/* ردیف چیپ‌ها (تب/فیلتر) */
export function SkChipRow({ n = 3, w = 62 }) {
  return (
    <div
      style={{
        display: 'flex',
        gap: 8,
        marginBottom: 12,
      }}
    >
      {Array.from(
        { length: n },
        (_u, i) => (
          <div
            key={i}
            className="skeleton"
            style={{
              width: w,
              height: 26,
              borderRadius: 'var(--r-pill)',
            }}
          />
        )
      )}
    </div>
  );
}


/* کارت هیرو — کرومِ واقعی + آواتار/خطوط/نوار */
export function SkHero({
  avatar = 56,
  lines = 2,
  pbar = false,
  badge = false,
}) {
  return (
    <section
      className="card card-glow hero-card"
      aria-hidden="true"
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 13,
        }}
      >
        <SkCircle size={avatar} />

        <div
          style={{ flex: 1, minWidth: 0 }}
        >
          <SkeletonLine
            width="34%"
            height={15}
          />

          <div style={{ marginTop: 'var(--sp-2)' }}>
            <SkeletonLine
              width="58%"
              height={10}
            />
          </div>

          {lines > 2 && (
            <div style={{ marginTop: 6 }}>
              <SkeletonLine
                width="44%"
                height={9}
              />
            </div>
          )}
        </div>

        {badge && (
          <div
            className="skeleton"
            style={{
              width: 46,
              height: 20,
              borderRadius: 'var(--r-pill)',
            }}
          />
        )}
      </div>

      {pbar && (
        <div style={{ marginTop: 15 }}>
          <div
            style={{
              display: 'flex',
              justifyContent:
                'space-between',
              marginBottom: 6,
            }}
          >
            <SkeletonLine
              width={64}
              height={10}
            />
            <SkeletonLine
              width={26}
              height={10}
            />
          </div>

          <SkPbar />
        </div>
      )}
    </section>
  );
}


/* گرید آماری (عدد + لیبل) */
export function SkStatGrid({ n = 2 }) {
  return (
    <section className="grid2">
      {Array.from(
        { length: n },
        (_u, i) => (
          <div
            key={i}
            className="card"
            style={{
              textAlign: 'center',
              padding: 12,
            }}
          >
            <div
              style={{
                display: 'grid',
                gap: 6,
                justifyItems: 'center',
              }}
            >
              <SkeletonLine
                width={34}
                height={16}
              />
              <SkeletonLine
                width={54}
                height={9}
              />
            </div>
          </div>
        )
      )}
    </section>
  );
}


/* گرید KPI ادمین (آیکون + عدد بزرگ + لیبل) */
export function SkKpiGrid({ n = 4 }) {
  return (
    <section className="grid2">
      {Array.from(
        { length: n },
        (_u, i) => (
          <div
            key={i}
            className="card"
            style={{ padding: 13 }}
          >
            <div
              className="skeleton"
              style={{
                width: 40,
                height: 40,
                marginBottom: 9,
                borderRadius: 'var(--r-md)',
              }}
            />
            <SkeletonLine
              width={44}
              height={17}
            />
            <div style={{ marginTop: 'var(--sp-1)' }}>
              <SkeletonLine
                width={58}
                height={9}
              />
            </div>
          </div>
        )
      )}
    </section>
  );
}


/* ردیفِ کارتِ لیستی (آیکون + خطوط + ستون راست) */
export function SkRowCard({
  icon = 46,
  circle = false,
  lines = 3,
}) {
  const IconShape = circle
    ? SkCircle
    : SkSquare;

  return (
    <article
      className="card"
      aria-hidden="true"
      style={{ padding: 13 }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 11,
        }}
      >
        <IconShape size={icon} />

        <div
          style={{ flex: 1, minWidth: 0 }}
        >
          <SkeletonLine
            width="58%"
            height={12}
          />

          {lines > 1 && (
            <div style={{ marginTop: 5 }}>
              <SkeletonLine
                width="42%"
                height={9}
              />
            </div>
          )}

          {lines > 2 && (
            <div style={{ marginTop: 5 }}>
              <SkeletonLine
                width="30%"
                height={8}
              />
            </div>
          )}
        </div>

        <div
          style={{
            display: 'grid',
            gap: 5,
            justifyItems: 'center',
          }}
        >
          <SkeletonLine
            width={22}
            height={15}
          />
          <SkeletonLine
            width={32}
            height={8}
          />
        </div>
      </div>
    </article>
  );
}


/* لیست از ردیف‌های کارت */
export function SkRowList({
  n = 3,
  icon = 46,
  circle = false,
  lines = 3,
  gap = 9,
}) {
  return (
    <section
      style={{
        display: 'grid',
        gap,
      }}
    >
      {Array.from(
        { length: n },
        (_u, i) => (
          <SkRowCard
            key={i}
            icon={icon}
            circle={circle}
            lines={lines}
          />
        )
      )}
    </section>
  );
}


/* کارتِ منوی ردیفی (تاگل/لینک) — کروم menu-row */
export function SkMenuCard({ n = 4 }) {
  return (
    <section
      className="card"
      aria-hidden="true"
      style={{ padding: '2px 14px' }}
    >
      {Array.from(
        { length: n },
        (_u, i) => (
          <div
            key={i}
            className="menu-row"
          >
            <div
              className="skeleton"
              style={{
                width: 40,
                height: 40,
                flexShrink: 0,
                borderRadius: 'var(--r-md)',
              }}
            />

            <div
              style={{
                flex: 1,
                minWidth: 0,
              }}
            >
              <SkeletonLine
                width="48%"
                height={11}
              />
              <div style={{ marginTop: 5 }}>
                <SkeletonLine
                  width="70%"
                  height={8}
                />
              </div>
            </div>

            <div
              className="skeleton"
              style={{
                width: 22,
                height: 22,
                borderRadius: 'var(--r-sm)',
              }}
            />
          </div>
        )
      )}
    </section>
  );
}


/* گرید تایل‌ها (درس‌ها/بخش‌های مدیریت) */
export function SkTileGrid({ n = 4 }) {
  return (
    <section
      style={{
        display: 'grid',
        gridTemplateColumns:
          'repeat(2,minmax(0,1fr))',
        gap: 9,
      }}
    >
      {Array.from(
        { length: n },
        (_u, i) => (
          <div
            key={i}
            className="card"
            style={{ padding: 13 }}
          >
            <div
              className="skeleton"
              style={{
                width: 36,
                height: 36,
                marginBottom: 8,
                borderRadius: 'var(--r-md)',
              }}
            />
            <SkeletonLine
              width="62%"
              height={11}
            />
            <div style={{ marginTop: 5 }}>
              <SkeletonLine
                width="40%"
                height={9}
              />
            </div>
          </div>
        )
      )}
    </section>
  );
}


/* کارت پلن اشتراک */
export function SkPlanCard() {
  return (
    <article
      className="card"
      aria-hidden="true"
      style={{ padding: 'var(--sp-4)' }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 11,
        }}
      >
        <SkSquare size={42} r={14} />

        <div
          style={{ flex: 1, minWidth: 0 }}
        >
          <SkeletonLine
            width="40%"
            height={13}
          />
          <div style={{ marginTop: 5 }}>
            <SkeletonLine
              width="56%"
              height={9}
            />
          </div>
        </div>

        <div
          className="skeleton"
          style={{
            width: 46,
            height: 20,
            borderRadius: 'var(--r-pill)',
          }}
        />
      </div>

      <div
        style={{
          marginTop: 12,
        }}
      >
        <SkeletonLine
          width="82%"
          height={9}
        />
      </div>

      <div
        className="skeleton"
        style={{
          width: '100%',
          height: 38,
          marginTop: 12,
          borderRadius: 'var(--r-md)',
        }}
      />
    </article>
  );
}


/* کارت نمودار میله‌ای */
export function SkChartCard() {
  const heights = [
    58, 82, 44, 96, 70, 88, 62,
  ];

  return (
    <section
      className="card"
      aria-hidden="true"
      style={{
        padding: '14px 12px 8px',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent:
            'space-between',
          marginBottom: 12,
        }}
      >
        <SkeletonLine
          width="42%"
          height={12}
        />
        <SkeletonLine
          width={30}
          height={9}
        />
      </div>

      <div
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          gap: 6,
          height: 74,
        }}
      >
        {heights.map((h, i) => (
          <div
            key={i}
            className="skeleton"
            style={{
              flex: 1,
              height: `${h}%`,
              borderRadius:
                '6px 6px 3px 3px',
            }}
          />
        ))}
      </div>
    </section>
  );
}


/* ═══ لایه‌ی ۲: کامپوزیتِ اختصاصی صفحات ═══ */


/* صفحه‌ی «من» — هیرو(آواتار+نوار آمادگی) + آمار + منو */
export function MeSkeleton() {
  return (
    <div
      style={{ display: 'grid', gap: 13 }}
    >
      <SkHero avatar={58} pbar />
      <SkStatGrid />
      <SkMenuCard n={5} />
    </div>
  );
}


/* داشبورد — هیرو + متریک‌ها + نمودار هفتگی */
export function DashboardSkeleton() {
  return (
    <div
      style={{ display: 'grid', gap: 12 }}
    >
      <SkHero avatar={52} />
      <SkStatGrid />
      <SkChartCard />
    </div>
  );
}


/* برنامه درسی — تب‌ها + ردیف برنامه‌ها */
export function ScheduleSkeleton() {
  return (
    <>
      <SkChipRow n={2} w={92} />
      <SkRowList n={4} icon={40} />
    </>
  );
}


/* اعلان‌ها — یک کارت منویی از ردیف‌های تاگل */
export function NotificationsSkeleton() {
  return <SkMenuCard n={6} />;
}


/* پروفایل — هیرو + اطلاعات + ردیف‌ها */
export function ProfileSkeleton() {
  return (
    <div
      style={{ display: 'grid', gap: 13 }}
    >
      <SkHero avatar={60} lines={3} />
      <SkMenuCard n={4} />
      <SkRowList n={2} icon={38} />
    </div>
  );
}


/* اشتراک — کارت وضعیت + پلن‌ها */
export function SubscriptionSkeleton() {
  return (
    <div
      style={{ display: 'grid', gap: 'var(--sp-4)' }}
    >
      <section
        className="card card-glow"
        aria-hidden="true"
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 13,
          }}
        >
          <SkSquare size={46} r={15} />

          <div
            style={{ flex: 1, minWidth: 0 }}
          >
            <SkeletonLine
              width="44%"
              height={14}
            />
            <div style={{ marginTop: 'var(--sp-2)' }}>
              <SkeletonLine
                width="64%"
                height={10}
              />
            </div>
          </div>

          <div
            className="skeleton"
            style={{
              width: 52,
              height: 22,
              borderRadius: 'var(--r-pill)',
            }}
          />
        </div>
      </section>

      <SkSecTitle w={96} />

      <SkPlanCard />
      <SkPlanCard />
    </div>
  );
}


/* بانک سؤال — فیلترها + تایل درس‌ها */
export function QuestionBankSkeleton() {
  return (
    <>
      <SkChipRow n={3} />
      <SkTileGrid n={6} />
    </>
  );
}


/* تایل‌های انتخاب درس در مرکز آزمون */
export function ExamLessonsSkeleton() {
  return <SkTileGrid n={4} />;
}


/* تاریخچه‌ی آزمون‌ها */
export function ExamHistorySkeleton() {
  return <SkRowList n={3} icon={44} />;
}


/* سؤالات من / تاریخچه‌ی پاسخ‌ها */
export function QuestionsListSkeleton() {
  return (
    <>
      <SkSecTitle w={124} />
      <SkRowList n={4} icon={42} />
    </>
  );
}


/* نتایج جست‌وجوی سراسری */
export function SearchResultsSkeleton() {
  return (
    <>
      <SkSecTitle w={104} />
      <SkRowList n={3} icon={36} />
    </>
  );
}


/* تیکت‌ها */
export function TicketsSkeleton() {
  return <SkRowList n={4} icon={44} />;
}


/* سوالات متداول/گزارش‌ها */
export function FaqListSkeleton() {
  return (
    <>
      <SkSecTitle w={132} />
      <SkRowList n={4} icon={40} />
    </>
  );
}


/* ── ادمین ── */

/* خانه‌ی مدیریت — تایل‌های عملیات */
export function AdminHomeSkeleton() {
  return <SkTileGrid n={6} />;
}


/* آنالitیکس — فیلتر بازه + KPI + دو نمودار */
export function AnalyticsSkeleton() {
  return (
    <>
      <SkChipRow n={4} w={56} />
      <SkKpiGrid n={4} />
      <div style={{ height: 12 }} />
      <SkChartCard />
      <div style={{ height: 12 }} />
      <SkChartCard />
    </>
  );
}


/* لاگ فعالیت — فیلترها + ردیف لاگ */
export function AuditLogSkeleton() {
  return (
    <>
      <SkChipRow n={4} w={58} />
      <SkRowList n={5} icon={34} />
    </>
  );
}


/* تنظیمات سیستم — سکشن‌ها + کارت متن */
export function SettingsSkeleton() {
  return (
    <div
      style={{ display: 'grid', gap: 2 }}
    >
      <SkSecTitle w={92} />

      <SkMenuCard n={1} />

      <div style={{ height: 10 }} />

      <SkSecTitle w={118} />

      <section
        className="card"
        aria-hidden="true"
        style={{ padding: 'var(--sp-4)' }}
      >
        <div
          className="skeleton"
          style={{
            width: '100%',
            height: 62,
            borderRadius: 'var(--r-sm)',
          }}
        />

        <div
          style={{
            display: 'flex',
            justifyContent:
              'space-between',
            alignItems: 'center',
            marginTop: 'var(--sp-3)',
          }}
        >
          <SkeletonLine
            width={92}
            height={8}
          />
          <div
            className="skeleton"
            style={{
              width: 66,
              height: 32,
              borderRadius: 'var(--r-md)',
            }}
          />
        </div>
      </section>

      <div style={{ height: 10 }} />

      <SkSecTitle w={84} />

      <SkMenuCard n={1} />
    </div>
  );
}


/* مدیریت نمرات — ردیف‌هایی شبیه GradeRow */
export function GradesAdminSkeleton() {
  return <SkRowList n={4} icon={54} />;
}


/* مدیریت برنامه — ردیف برنامه‌ها */
export function ScheduleAdminSkeleton() {
  return <SkRowList n={4} icon={38} />;
}


/* تایل‌های کتابخانه‌ی محتوا */
export function LibraryTilesSkeleton() {
  return <SkTileGrid n={6} />;
}


/* ردیف‌های کتابخانه‌ی محتوا */
export function LibraryRowsSkeleton() {
  return <SkRowList n={4} icon={40} />;
}


/* فهرست کاربران — آواتار دایره‌ای */
export function UsersListSkeleton() {
  return (
    <SkRowList
      n={5}
      icon={40}
      circle
    />
  );
}


/* اکشن‌های مدیریت کاربران */
export function UsersActionsSkeleton() {
  return <SkTileGrid n={4} />;
}


/* پیش‌نمایش/لیست عملیات مدیریتی */
export function AdminOpsSkeleton() {
  return (
    <>
      <SkSecTitle w={116} />
      <SkRowList n={4} icon={36} />
    </>
  );
}


/* خانه‌ی محتوا */
export function ContentHomeSkeleton() {
  return <SkTileGrid n={6} />;
}
