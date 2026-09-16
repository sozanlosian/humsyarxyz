import { faNum } from '../../lib/format';

import { useState } from 'react';

import { useNavigate } from 'react-router-dom';

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
  TicketsSkeleton,
} from '../../components/shared/skeletons';

import {
  haptic,
  hapticNotif,
} from '../../lib/telegram';

/* 👑 موج P1 Prestige — کلکسیون کامل نشان‌ها
   (۵ تکاملی + تکی‌ها + جهانی‌ها) + پین شوکیس
   (حداکثر ۳) + تب «سفر من». تمام متن/آیکون/
   رنگ/XP از پیلود بک‌اند است — هیچ مقداری
   اینجا هاردکد نمی‌شود. */



const KIND_TITLES = {
  lifetime: 'لحظه‌ای‌ها',
  accuracy: 'دقت',
  community: 'مشارکت',
  secret: 'مخفی‌ها',
  ancient: 'باستانی‌ها',
  founder: 'بنیان‌گذار',
  competition: 'رقابتی',
};

const KIND_ORDER = [
  'lifetime',
  'accuracy',
  'community',
  'secret',
  'ancient',
  'competition',
  'founder',
];


function RarityDot({ color }) {
  return (
    <span
      aria-hidden="true"
      style={{
        width: 7,
        height: 7,
        borderRadius: '50%',
        background:
          color || 'var(--txm)',
        display: 'inline-block',
        flexShrink: 0,
      }}
    />
  );
}


function BadgeTile({
  icon,
  title,
  desc,
  color,
  earned,
  secret,
  pinned,
  onTogglePin,
  extra,
}) {
  return (
    <button
      type="button"
      className="card card-tap"
      onClick={onTogglePin}
      style={{
        display: 'grid',
        gap: 'var(--sp-1)',
        textAlign: 'right',
        border: pinned
          ? '1.5px solid var(--acc)'
          : '1px solid var(--bd)',
        opacity: earned || secret ? 1 : 0.55,
        position: 'relative',
      }}
    >
      {pinned && (
        <span
          title="پین‌شده"
          style={{
            position: 'absolute',
            top: 6,
            left: 8,
            fontSize: 'var(--fs-cap)',
          }}
        >
          📌
        </span>
      )}

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}
      >
        <span style={{ fontSize: 21 }}>
          {icon}
        </span>

        <b
          style={{
            fontSize: 'var(--fs-meta)',
            flex: 1,
          }}
        >
          {title}
        </b>

        <RarityDot color={color} />
      </div>

      <div
        style={{
          color: 'var(--txm)',
          fontSize: 'var(--fs-cap)',
          lineHeight: 1.6,
        }}
      >
        {desc}
      </div>

      {extra}
    </button>
  );
}


export default function Badges() {
  const navigate = useNavigate();

  const queryClient =
    useQueryClient();

  const [
    tab,
    setTab,
  ] = useState('badges');

  const {
    data,
    isLoading,
    isError,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: ['prestige-badges'],
    queryFn: () =>
      api
        .get(
          '/api/profile/prestige/badges'
        )
        .then(
          (response) =>
            response.data?.badges
        ),
    staleTime: 60 * 1000,
  });

  const {
    data: historyItems = [],
  } = useQuery({
    queryKey: ['prestige-history'],
    queryFn: () =>
      api
        .get(
          '/api/profile/prestige/history?limit=40'
        )
        .then(
          (response) =>
            response.data?.items ||
            []
        ),
    enabled: tab === 'journey',
    staleTime: 60 * 1000,
  });

  const pinMutation = useMutation({
    mutationFn: (keys) =>
      api.put(
        '/api/profile/prestige/showcase',
        { keys }
      ),

    onSuccess: (response) => {
      queryClient.setQueryData(
        ['prestige-badges'],
        (old) =>
          old
            ? {
                ...old,
                showcase:
                  response.data
                    ?.showcase
                    ?.map(
                      (item) => item.key
                    )
                    .filter(Boolean) ||
                  [],
              }
            : old
      );

      queryClient.invalidateQueries({
        queryKey: ['prestige'],
      });

      hapticNotif('success');
    },
  });

  /* 🌊 W8/UX-02 — خطا دیگر اسکلت ابدی نیست */
  if (isError && !data) {
    return (
      <>
        <Header
          title="نشان‌های من"
          onBack={() => navigate('/me')}
        />

        <main className="page">
          <PageError
            text="دریافت نشان‌ها انجام نشد."
            onRetry={() => refetch()}
            pending={isRefetching}
          />
        </main>
      </>
    );
  }

  if (isLoading || !data) {
    return (
      <>
        <Header
          title="نشان‌های من"
          onBack={() => navigate('/me')}
        />

        <main className="page">
          <TicketsSkeleton />
        </main>
      </>
    );
  }

  const showcase =
    data.showcase || [];

  const togglePin = (key, earned) => {
    if (!earned) {
      return;
    }

    haptic();

    const next = showcase.includes(key)
      ? showcase.filter(
          (item) => item !== key
        )
      : [...showcase, key];

    if (next.length > 3 && !showcase.includes(key)) {
      return;
    }

    pinMutation.mutate(
      next.slice(0, 3)
    );
  };

  const progressive =
    data.progressive || [];

  const singles = data.singles || [];

  const globals = data.global || [];

  const earnedSingles = singles.filter(
    (item) => item.earned
  ).length;

  return (
    <>
      <Header
        title="🏅 نشان‌های من"
        onBack={() => navigate('/me')}
      />

      <main className="page fade-up">
        {/* سگمنت تب‌ها */}
        <div
          style={{
            display: 'flex',
            gap: 8,
          }}
        >
          {[
            ['badges', '🏅 نشان‌ها'],
            ['journey', '📜 سفر من'],
          ].map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={
                'tab-btn' +
                (tab === key
                  ? ' active'
                  : '')
              }
              style={{ flex: 1 }}
              onClick={() => {
                haptic();
                setTab(key);
              }}
            >
              {label}
            </button>
          ))}
        </div>

        {tab === 'badges' && (
          <>
            {/* شوکیس پین‌شده */}
            <section>
              <div className="sec-title">
                📌 شوکیس (حداکثر ۳ نشان)
              </div>

              <div
                className="card"
                style={{
                  color: 'var(--txm)',
                  fontSize: 'var(--fs-cap)',
                  lineHeight: 1.8,
                }}
              >
                {showcase.length
                  ? `${faNum(
                      showcase.length
                    )} نشان پین شده — روی کارت نشان‌ها در
                    صفحه‌ی عمومی‌ات دیده می‌شود.`
                  : 'هنوز نشانی پین نکردی — روی هر نشان بازشده بزن تا به شوکیس برود.'}
              </div>
            </section>

            {/* پنج نشان تکاملی */}
            <section>
              <div className="sec-title">
                🪜 نشان‌های تکاملی
              </div>

              <div
                style={{
                  display: 'grid',
                  gap: 9,
                }}
              >
                {progressive.map(
                  (badge) => (
                    <div
                      key={badge.key}
                      className="card"
                      style={{
                        display: 'grid',
                        gap: 'var(--sp-2)',
                      }}
                    >
                      <div
                        style={{
                          display:
                            'flex',
                          alignItems:
                            'center',
                          gap: 'var(--sp-2)',
                        }}
                      >
                        <span
                          style={{
                            fontSize: 'var(--fs-xl)',
                          }}
                        >
                          {badge.icon}
                        </span>

                        <b
                          style={{
                            fontSize: 'var(--fs-sm)',
                            flex: 1,
                          }}
                        >
                          {badge.title}
                        </b>

                        <span
                          style={{
                            color:
                              badge.color,
                            fontSize: 'var(--fs-cap)',
                          }}
                        >
                          پله{' '}
                          {faNum(
                            badge.tier
                          )}
                          /
                          {faNum(
                            badge.tiers_count
                          )}
                        </span>
                      </div>

                      {/* پله‌ها */}
                      <div
                        style={{
                          display:
                            'flex',
                          gap: 'var(--sp-1)',
                        }}
                      >
                        {(
                          badge.tiers ||
                          []
                        ).map(
                          (
                            tier,
                            index
                          ) => (
                            <span
                              key={
                                index
                              }
                              style={{
                                flex: 1,
                                height: 5,
                                borderRadius: 4,
                                background:
                                  index <
                                  badge.tier
                                    ? badge.color
                                    : 'var(--elev)',
                              }}
                            />
                          )
                        )}
                      </div>

                      <div
                        style={{
                          color:
                            'var(--txm)',
                          fontSize: 'var(--fs-cap)',
                        }}
                      >
                        {badge.next_target
                          ? `${faNum(
                              badge.value
                            )} از ${faNum(
                              badge.next_target
                            )} · پله بعد: +${faNum(
                              badge.next_xp
                            )} XP`
                          : 'به بالاترین پله رسیدی — اسطوره‌ای! 🌟'}
                      </div>
                    </div>
                  )
                )}
              </div>
            </section>

            {/* تکی‌ها گروه‌بندی‌شده */}
            {KIND_ORDER.map(
              (kind) => {
                const group =
                  singles.filter(
                    (item) =>
                      item.kind ===
                      kind
                  );

                if (!group.length) {
                  return null;
                }

                return (
                  <section key={kind}>
                    <div className="sec-title">
                      {KIND_TITLES[kind] ||
                        kind}{' '}
                      <span
                        style={{
                          color:
                            'var(--txm)',
                          fontSize: 'var(--fs-cap)',
                        }}
                      >
                        (
                        {
                          group.filter(
                            (g) =>
                              g.earned
                          ).length
                        }
                        /{group.length})
                      </span>
                    </div>

                    <div
                      className="grid2"
                      style={{
                        display: 'grid',
                        gap: 8,
                      }}
                    >
                      {group.map(
                        (item) => (
                          <BadgeTile
                            key={item.key}
                            icon={item.icon}
                            title={
                              item.title
                            }
                            desc={item.desc}
                            color={
                              item.color
                            }
                            earned={
                              item.earned
                            }
                            secret={
                              item.secret
                            }
                            pinned={showcase.includes(
                              item.key
                            )}
                            onTogglePin={() =>
                              togglePin(
                                item.key,
                                item.earned
                              )
                            }
                            extra={
                              item.count >
                              1 ? (
                                <div
                                  style={{
                                    color:
                                      'var(--acc)',
                                    fontSize: 'var(--fs-cap)',
                                  }}
                                >
                                  ×
                                  {faNum(
                                    item.count
                                  )}{' '}
                                  بار
                                </div>
                              ) : null
                            }
                          />
                        )
                      )}
                    </div>
                  </section>
                );
              }
            )}

            {/* جهانی‌ها */}
            <section>
              <div className="sec-title">
                🏆 نشان‌های جهانی — فقط یک نفر در تاریخ
              </div>

              <div
                style={{
                  display: 'grid',
                  gap: 'var(--sp-2)',
                }}
              >
                {globals.map((g) => (
                  <div
                    key={g.key}
                    className="card"
                    style={{
                      display: 'flex',
                      alignItems:
                        'center',
                      gap: 8,
                      opacity:
                        g.claimed &&
                        !g.owned_by_me
                          ? 0.72
                          : 1,
                    }}
                  >
                    <span
                      style={{
                        fontSize: 'var(--fs-xl)',
                      }}
                    >
                      {g.icon}
                    </span>

                    <div
                      style={{ flex: 1 }}
                    >
                      <b
                        style={{
                          fontSize: 'var(--fs-meta)',
                        }}
                      >
                        {g.title}
                      </b>

                      <div
                        style={{
                          color:
                            'var(--txm)',
                          fontSize: 'var(--fs-cap)',
                        }}
                      >
                        {g.claimed
                          ? g.owned_by_me
                            ? '👑 مال توئه!'
                            : `تصاحب شد: ${g.owner_name}`
                          : 'هنوز آزاد است…'}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <div
              style={{
                color: 'var(--txm)',
                fontSize: 'var(--fs-cap)',
                textAlign: 'center',
              }}
            >
              {faNum(earnedSingles)} نشان
              تکی باز کرده‌ای · روی نشان بازشده
              بزن تا پین شود 📌
            </div>
          </>
        )}

        {tab === 'journey' && (
          <section
            style={{
              display: 'grid',
              gap: 8,
            }}
          >
            {!historyItems.length && (
              <EmptyState icon="⚡">
                هنوز رویدادی ثبت نشده — اولین
                قدم را بردار
              </EmptyState>
            )}

            {historyItems.map((row, i) => (
              <div
                key={i}
                className="card"
                style={{
                  display: 'grid',
                  gap: 3,
                }}
              >
                <b
                  style={{
                    fontSize: 'var(--fs-meta)',
                  }}
                >
                  {row.title}
                </b>

                {row.detail?.rank && (
                  <span
                    style={{
                      color:
                        'var(--tx2)',
                      fontSize: 'var(--fs-cap)',
                    }}
                  >
                    {row.detail.rank}
                  </span>
                )}

                <span
                  style={{
                    color: 'var(--txm)',
                    fontSize: 'var(--fs-cap)',
                  }}
                >
                  {row.at_jalali}
                </span>
              </div>
            ))}
          </section>
        )}
      </main>
    </>
  );
}
