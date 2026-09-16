import {
  useState,
} from 'react';

import {
  useQuery,
} from '@tanstack/react-query';

import api from '../../lib/api';

import {
  useDebouncedValue,
} from '../../lib/useDebounce';

import {
  haptic,
} from '../../lib/telegram';

import SearchField from './SearchField';


/* ─────────────────────────────────────────────
   انتخاب‌گر دانشجو با جست‌وجوی یکپارچه
   به موتور سراسری بک‌اند وصل است
   (db.search_users — همان قرارداد ربات و
   پنل کاربران): آیدی عددی تلگرام، یوزرنیم
   با/بدون @، نام و شماره دانشجویی.

   به‌محض انتخاب، فیلد به «چیپ دانشجو» تبدیل
   می‌شود تا مدیر قبل از عمل (مثل اعطای
   اشتراک) دقیقاً ببیند چه کسی هدف است؛
   پاک‌کردن چیپ برمی‌گردد به حالت جست‌وجو.
───────────────────────────────────────────── */


function subline(user) {
  return [
    user.student_id,
    user.username
      ? `@${user.username}`
      : '',
    user.id ? `#${user.id}` : '',
  ]
    .filter(Boolean)
    .join(' • ');
}


export default function UserSearchSelect({
  selected,
  onPick,
  onClear,
  placeholder =
    'نام، یوزرنیم، شماره یا آیدی عددی دانشجو...',
}) {
  const [
    query,
    setQuery,
  ] = useState('');

  const [open, setOpen] =
    useState(false);


  const debounced =
    useDebouncedValue(query, 350)
      .trim();

  const canSearch =
    debounced.length >= 2;


  /* وقتی کسی انتخاب شده، فیلد دیده نمی‌شود،
     پس کوئری هم غیرفعال است (enabled گزینه
     است، نه هوک شرطی) */
  const {
    data: results = [],
    isFetching,
  } = useQuery({
    queryKey: [
      'user-search-select',
      debounced,
    ],

    queryFn: () =>
      api
        .get(
          '/api/subscription-admin/users/search',

          {
            params: {
              q: debounced,
            },
          }
        )
        .then((response) =>
          Array.isArray(
            response.data?.users
          )
            ? response.data.users
            : []
        ),

    enabled:
      canSearch && !selected,

    staleTime: 30_000,
    retry: false,
  });


  if (selected) {
    return (
      <div className="user-pick">
        <span
          className="avatar"
          style={{
            width: 40,
            height: 40,
            flex: '0 0 40px',
          }}
        >
          {selected.name?.[0] ||
            '؟'}
        </span>

        <span className="user-pick__meta">
          <b>{selected.name}</b>

          <span className="user-pick__sub">
            {subline(selected)}
          </span>
        </span>

        <button
          type="button"
          className={
            'user-pick__clear'
          }
          aria-label="پاک‌کردن انتخاب"
          onClick={() => {
            haptic('light');
            onClear?.();
          }}
        >
          <svg
            width="11"
            height="11"
            viewBox="0 0 24 24"
            fill="none"
            aria-hidden="true"
          >
            <path
              d="M6 6l12 12M18 6L6 18"
              stroke="currentColor"
              strokeWidth="2.6"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </div>
    );
  }


  return (
    <div
      className="user-pick__box"
    >
      <SearchField
        value={query}
        onChange={(event) => {
          setQuery(
            event.target.value
          );
          setOpen(true);
        }}
        placeholder={placeholder}
        ariaLabel="جست‌وجوی دانشجو"
        loading={
          isFetching && canSearch
        }
        onFocus={() =>
          setOpen(true)
        }
        onBlur={() =>
          setOpen(false)
        }
      />

      {open && canSearch && (
        <div
          className={
            'user-pick__drop card pop-in'
          }
          role="listbox"
          aria-label="نتایج جست‌وجوی دانشجو"
        >
          {!isFetching &&
          results.length === 0 ? (
            <div className="user-pick__empty">
              دانشجویی با این عبارت
              پیدا نشد.
            </div>
          ) : (
            results.map((user) => (
              <button
                type="button"
                role="option"
                aria-selected="false"
                key={user.id}
                className={
                  'user-pick__row'
                }
                onMouseDown={(event) =>
                  event.preventDefault()
                }
                onClick={() => {
                  haptic('light');
                  onPick?.(user);
                  setQuery('');
                  setOpen(false);
                }}
              >
                <span
                  className="avatar"
                  style={{
                    width: 36,
                    height: 36,
                    flex: '0 0 36px',
                    fontSize: 'var(--fs-lg)',
                  }}
                >
                  {user.name?.[0] ||
                    '؟'}
                </span>

                <span className="user-pick__meta">
                  <b>
                    {user.name ||
                      'بدون نام'}
                  </b>

                  <span className="user-pick__sub">
                    {subline(user)}
                  </span>
                </span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
