import { faNum } from '../../lib/format';

import { useState } from 'react';

import { useNavigate } from 'react-router-dom';

import { useQuery } from '@tanstack/react-query';

import api from '../../lib/api';
import Header from '../../components/layout/Header';
import NameChip from '../../components/shared/NameChip';

import {
  UsersListSkeleton,
} from '../../components/shared/skeletons';
import PageError from '../../components/shared/PageError';
import EmptyState from '../../components/shared/EmptyState';

import { haptic } from '../../lib/telegram';

/* 👑 موج P2 Prestige — میدان رقابت:
   ماتریس بازه × دامنه × تب (کاملاً سرورمحور)
   + ردیف چسبان «من» با Jump هفتگی + رقبا.
   هیچ فرمول رتبه‌بندی در FE نیست. */



const RANGES = [
  ['week', 'هفته'],
  ['month', 'ماه'],
  ['all', 'کل'],
  ['season', 'سیزن'],
];

const SCOPES = [
  ['all', 'همه'],
  ['intake', 'ورودی من'],
  ['group', 'گروه من'],
];

const TABS = [
  ['xp', '⚡ XP', 'XP'],
  ['acc', '🎯 دقت', '٪'],
  ['exam', '📝 آزمون', 'آزمون'],
  ['contrib', '✍️ مشارکت', 'سؤال'],
];

function ChipRow({ options, value, onPick }) {
  return (
    <div
      style={{
        display: 'flex',
        gap: 6,
        flexWrap: 'wrap',
      }}
    >
      {options.map(([key, label]) => (
        <button
          key={key}
          type="button"
          className={
            'tab-btn' +
            (value === key ? ' active' : '')
          }
          style={{ fontSize: 'var(--fs-meta)' }}
          onClick={() => {
            haptic();
            onPick(key);
          }}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function JumpBadge({ jump }) {
  if (jump == null) {
    return null;
  }

  if (jump === 0) {
    return (
      <span
        style={{
          color: 'var(--txm)',
          fontSize: 'var(--fs-cap)',
        }}
      >
        ▬ بدون تغییر
      </span>
    );
  }

  return (
    <span
      style={{
        color:
          jump > 0
            ? 'var(--ok)'
            : 'var(--err)',
        fontSize: 'var(--fs-cap)',
        fontWeight: 700,
      }}
    >
      {jump > 0 ? '▲' : '▼'} {faNum(
        Math.abs(jump)
      )}{' '}
      نسبت به هفته‌ی قبل
    </span>
  );
}

export default function Leaderboard() {
  const navigate = useNavigate();

  const [range, setRange] =
    useState('week');

  const [scope, setScope] =
    useState('all');

  const [tab, setTab] =
    useState('xp');

  const { data, isLoading, isError, refetch, isRefetching } = useQuery({
    queryKey: [
      'leaderboard',
      range,
      scope,
      tab,
    ],
    queryFn: () =>
      api
        .get('/api/dashboard/leaderboard', {
          params: {
            range_: range,
            scope,
            tab,
            limit: 50,
          },
        })
        .then(
          (response) => response.data
        ),
    staleTime: 30 * 1000,
  });

  const tabMeta =
    TABS.find(([key]) => key === tab) ||
    TABS[0];

  const rows = data?.rows || [];

  const me = data?.me;

  const valueLabel = (row) =>
    `${faNum(row.value)} ${tabMeta[2]}`;

  const renderRow = (row) => (
    <div
      key={row.uid}
      className="card"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        border: row.is_me
          ? '1.5px solid var(--acc)'
          : '1px solid var(--bd)',
      }}
    >
      <b
        style={{
          width: 26,
          textAlign: 'center',
          color:
            row.rank === 1
              ? 'var(--warn)'
              : 'var(--txm)',
          fontSize: 'var(--fs-md)',
        }}
      >
        {faNum(row.rank)}
      </b>

      <div style={{ flex: 1 }}>
        <NameChip
          icon={row.icon}
          name={
            row.is_me
              ? `${row.name} (تو)`
              : row.name
          }
          color={row.color}
          roman={row.roman}
        />
      </div>

      <div
        style={{
          display: 'grid',
          justifyItems: 'end',
          gap: 2,
        }}
      >
        <b style={{ fontSize: 'var(--fs-sm)' }}>
          {valueLabel(row)}
        </b>

        <JumpBadge jump={row.jump} />
      </div>
    </div>
  );

  return (
    <>
      <Header
        title="🏟️ میدان رقابت"
        onBack={() => navigate(-1)}
      />

      <main className="page fade-up">
        {range === 'season' &&
          data?.season?.label && (
            <div
              className="card"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 'var(--sp-2)',
                color: 'var(--acc)',
                fontSize: 'var(--fs-meta)',
              }}
            >
              🗓 {data.season.label}
              <span
                style={{
                  color: 'var(--txm)',
                  fontSize: 'var(--fs-cap)',
                }}
              >
                — All-Time هرگز ریست نمی‌شود
              </span>
            </div>
          )}

        <div
          className="card"
          style={{
            display: 'grid',
            gap: 9,
          }}
        >
          <ChipRow
            options={RANGES}
            value={range}
            onPick={setRange}
          />

          <ChipRow
            options={SCOPES}
            value={scope}
            onPick={setScope}
          />

          <ChipRow
            options={TABS.map(
              ([key, label]) => [
                key,
                label,
              ]
            )}
            value={tab}
            onPick={setTab}
          />
        </div>

        {/* ردیف چسبان «من» */}
        {me && (
          <section
            className="card card-glow"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 9,
              border:
                '1.5px solid var(--acc)',
            }}
          >
            <b
              style={{
                fontSize: 'var(--fs-lg)',
                color: 'var(--acc)',
              }}
            >
              #{faNum(me.rank)}
            </b>

            <div style={{ flex: 1 }}>
              <NameChip
                icon={me.icon}
                name="تو"
                color={me.color}
                roman={me.roman}
              />
            </div>

            <div
              style={{
                display: 'grid',
                justifyItems: 'end',
                gap: 2,
              }}
            >
              <b style={{ fontSize: 'var(--fs-sm)' }}>
                {valueLabel(me)}
              </b>

              <JumpBadge jump={me.jump} />
            </div>
          </section>
        )}

        {/* رقبای نزدیک (با XP مؤثر — منبع state) */}
        {(data?.rival_above ||
          data?.rival_below) && (
          <div
            style={{
              display: 'flex',
              gap: 'var(--sp-2)',
              color: 'var(--txm)',
              fontSize: 'var(--fs-cap)',
              justifyContent: 'center',
              flexWrap: 'wrap',
            }}
          >
            {data?.rival_above && (
              <span>
                ⬆️ {data.rival_above.icon}{' '}
                {data.rival_above.name} · فاصله{' '}
                {faNum(data.rival_above.gap)} XP
              </span>
            )}

            {data?.rival_below && (
              <span>
                ⬇️ {data.rival_below.icon}{' '}
                {data.rival_below.name} · فاصله{' '}
                {faNum(data.rival_below.gap)} XP
              </span>
            )}
          </div>
        )}

        {isLoading && <UsersListSkeleton />}

        {/* 🌊 W8/UX-02 */}
        {!isLoading && isError && (
          <PageError
            text="دریافت جدول رقابت انجام نشد."
            onRetry={() => refetch()}
            pending={isRefetching}
          />
        )}

        {!isLoading && !isError &&
          !rows.length && (
            <EmptyState icon="🌱">
              هنوز کسی در این جدول نیست —
              اولین نفر باش!
            </EmptyState>
          )}

        <div
          style={{
            display: 'grid',
            gap: 'var(--sp-2)',
          }}
        >
          {rows.map(renderRow)}
        </div>

        <div
          style={{
            color: 'var(--txm)',
            fontSize: 'var(--fs-cap)',
            textAlign: 'center',
          }}
        >
          {faNum(data?.total_users || 0)}{' '}
          رقبا در این جدول · صدر هفته با بستن
          هفته (دوشنبه ۰۰:۰۰) +۱۰۰ XP می‌گیرد 👑
        </div>
      </main>
    </>
  );
}
