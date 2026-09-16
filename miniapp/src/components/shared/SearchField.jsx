import {
  Spinner,
} from './Loading';


/* ─────────────────────────────────────────────
   فیلد جست‌وجوی یکپارچه‌ی سیستم دیزاین
   نسخه‌ی واحد برای همه‌ی صفحه‌ها و پنل‌ها:
   آیکون وکتوری (crisp در هر اندازه، رنگ از
   توکن‌ها و واکنش‌گر به فوکوس)، اسپینر وضعیت
   و دکمه‌ی پاک‌کردن — جایگزین آیکون‌های
   کوچک و ناهماهنگِ پراکنده (⌕، 🔍 ریز و…)

   قرارداد: کاملاً کنترل‌شده — onChange با
   همان event استاندارد input صدا زده می‌شود
   و دکمه‌ی پاک‌کردن یک event مصنوعی با مقدار
   '' می‌سازد تا همه‌ی handlerهای موجود بدون
   تغییر کار کنند.
───────────────────────────────────────────── */


export default function SearchField({
  value,
  onChange,
  placeholder = 'جست‌وجو...',
  loading = false,
  autoFocus = false,
  inputMode,
  maxLength = 100,
  onFocus,
  onBlur,
  onKeyDown,
  ariaLabel,
  style,
}) {
  const clear = () => {
    if (!value) return;

    onChange?.({
      target: { value: '' },
    });
  };


  return (
    <div
      className="search-field"
      style={style}
    >
      <svg
        className="search-field__icon"
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
      >
        <circle
          cx="11"
          cy="11"
          r="7"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
        />

        <path
          d="M20 20l-3.35-3.35"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>

      <input
        className={
          'inp search-field__inp'
        }
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        aria-label={
          ariaLabel || placeholder
        }
        autoFocus={autoFocus}
        inputMode={inputMode}
        maxLength={maxLength}
        onFocus={onFocus}
        onBlur={onBlur}
        onKeyDown={onKeyDown}
      />

      {loading ? (
        <span
          className={
            'search-field__meta'
          }
        >
          <Spinner size={15} />
        </span>
      ) : value ? (
        <button
          type="button"
          className={
            'search-field__clear'
          }
          aria-label="پاک‌کردن جست‌وجو"
          onMouseDown={(event) =>
            event.preventDefault()
          }
          onClick={clear}
        >
          <svg
            width="10"
            height="10"
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
      ) : null}
    </div>
  );
}
