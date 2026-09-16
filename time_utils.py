"""HUMSYAR global time contract.

Storage/machine timestamps are UTC and timezone-aware. Business boundaries and
all Persian-facing display are Asia/Tehran. Date-only academic fields remain
Gregorian ``YYYY-MM-DD`` machine dates and are interpreted as Tehran civil
calendar days; they are not instants.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import jdatetime

APP_TIMEZONE = "Asia/Tehran"
APP_LOCALE = "fa-IR"
APP_CALENDAR = "persian"
UTC = timezone.utc
TEHRAN = ZoneInfo(APP_TIMEZONE)

PERSIAN_MONTHS = (
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
)
PERSIAN_WEEKDAYS = (
    "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یکشنبه",
)
_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_EN = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_JALALI_INPUT = re.compile(
    r"^\s*([0-9۰-۹٠-٩]{4})[/-]([0-9۰-۹٠-٩]{1,2})[/-]([0-9۰-۹٠-٩]{1,2})"
    r"(?:[ T،-]+([0-9۰-۹٠-٩]{1,2}):([0-9۰-۹٠-٩]{2})(?::([0-9۰-۹٠-٩]{2}))?)?\s*$"
)


class TimeContractError(ValueError):
    """Invalid or ambiguous user/machine time input."""


def fa_digits(value: Any) -> str:
    return str(value).translate(_FA)


def en_digits(value: Any) -> str:
    return str(value).translate(_EN)


def now_utc() -> datetime:
    return datetime.now(UTC)


def utc_now_iso(timespec: str = "microseconds") -> str:
    return now_utc().isoformat(timespec=timespec)


def now_tehran() -> datetime:
    return now_utc().astimezone(TEHRAN)


def today_tehran() -> date:
    return now_tehran().date()


def _aware(value: datetime, *, naive_source=UTC) -> datetime:
    """Normalize a datetime; legacy naive machine timestamps are UTC.

    Existing HUMSYAR writers used ``datetime.now().isoformat()`` on UTC Railway.
    That historical fact is documented, but rows from unknown external sources
    must be classified before migration instead of passed here blindly.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=naive_source)
    return value


def parse_machine_datetime(value: Any, *, naive_source=UTC) -> datetime:
    if isinstance(value, datetime):
        return _aware(value, naive_source=naive_source)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, UTC)
    raw = str(value or "").strip()
    if not raw or _DATE_ONLY.fullmatch(raw):
        raise TimeContractError("instant_required")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TimeContractError("invalid_machine_timestamp") from exc
    return _aware(parsed, naive_source=naive_source)


def to_utc(value: Any, *, naive_source=UTC) -> datetime:
    return parse_machine_datetime(value, naive_source=naive_source).astimezone(UTC)


def to_tehran(value: Any, *, naive_source=UTC) -> datetime:
    return parse_machine_datetime(value, naive_source=naive_source).astimezone(TEHRAN)


def canonical_utc(value: Any) -> str:
    return to_utc(value).isoformat(timespec="microseconds")


def gregorian_to_jalali(value: date) -> jdatetime.date:
    return jdatetime.date.fromgregorian(date=value)


def jalali_to_gregorian(year: int, month: int, day: int) -> date:
    try:
        return jdatetime.date(int(year), int(month), int(day)).togregorian()
    except (TypeError, ValueError) as exc:
        raise TimeContractError("invalid_jalali_date") from exc


def parse_clock_time(value: str) -> time:
    """Validate a business wall-clock value in strict HH:MM form."""
    raw = en_digits(str(value or "").strip())
    try:
        if len(raw) != 5 or raw[2] != ":":
            raise ValueError
        return time.fromisoformat(raw)
    except ValueError as exc:
        raise TimeContractError("invalid_time") from exc


def parse_gregorian_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(en_digits(value).strip()[:10])
    except (TypeError, ValueError) as exc:
        raise TimeContractError("invalid_gregorian_date") from exc


def parse_jalali_date(value: str) -> date:
    match = _JALALI_INPUT.fullmatch(str(value or ""))
    if not match or match.group(4):
        raise TimeContractError("invalid_jalali_date")
    year, month, day = (int(en_digits(part)) for part in match.groups()[:3])
    return jalali_to_gregorian(year, month, day)


def parse_jalali_datetime(value: str) -> datetime:
    match = _JALALI_INPUT.fullmatch(str(value or ""))
    if not match or match.group(4) is None:
        raise TimeContractError("invalid_jalali_datetime")
    parts = [int(en_digits(part or 0)) for part in match.groups()]
    year, month, day, hour, minute, second = parts
    gregorian = jalali_to_gregorian(year, month, day)
    try:
        local = datetime.combine(gregorian, time(hour, minute, second), tzinfo=TEHRAN)
    except ValueError as exc:
        raise TimeContractError("invalid_jalali_datetime") from exc
    return local.astimezone(UTC)


def parse_user_datetime(value: str, *, date_only_end: bool = False) -> datetime:
    """Interpret Persian input as Tehran and return a canonical UTC instant."""
    match = _JALALI_INPUT.fullmatch(str(value or ""))
    if not match:
        raise TimeContractError("invalid_jalali_datetime")
    if match.group(4) is not None:
        return parse_jalali_datetime(value)
    gregorian = parse_jalali_date(value)
    local_time = time.max if date_only_end else time.min
    return datetime.combine(gregorian, local_time, tzinfo=TEHRAN).astimezone(UTC)


def _local_date(value: Any, *, date_only: bool = False) -> date:
    if date_only or isinstance(value, date) and not isinstance(value, datetime):
        return parse_gregorian_date(value)
    if isinstance(value, str) and _DATE_ONLY.fullmatch(value.strip()):
        return parse_gregorian_date(value)
    return to_tehran(value).date()


def format_date_fa(value: Any, *, long: bool = False, weekday: bool = False,
                   date_only: bool = False, fallback: str = "—") -> str:
    try:
        local_date = _local_date(value, date_only=date_only)
        jalali = gregorian_to_jalali(local_date)
        if long:
            result = f"{jalali.day} {PERSIAN_MONTHS[jalali.month - 1]} {jalali.year}"
        else:
            result = f"{jalali.year:04d}/{jalali.month:02d}/{jalali.day:02d}"
        if weekday:
            result = f"{result} ({PERSIAN_WEEKDAYS[local_date.weekday()]})"
        return fa_digits(result)
    except (TimeContractError, ValueError, TypeError):
        return fallback


def format_time_fa(value: Any, *, seconds: bool = False, fallback: str = "—") -> str:
    """Format either an absolute instant or a date-only wall-clock HH:MM."""
    try:
        raw = str(value or "").strip()
        if len(raw) == 5 and raw[2] == ":":
            return fa_digits(parse_clock_time(raw).strftime("%H:%M"))
        local = to_tehran(value)
        pattern = "%H:%M:%S" if seconds else "%H:%M"
        return fa_digits(local.strftime(pattern))
    except (TimeContractError, ValueError, TypeError):
        return fallback


def format_datetime_fa(value: Any, *, long: bool = False, seconds: bool = False,
                       fallback: str = "—") -> str:
    try:
        local = to_tehran(value)
        date_part = format_date_fa(local, long=long)
        time_part = fa_digits(local.strftime("%H:%M:%S" if seconds else "%H:%M"))
        if long:
            return f"{date_part}، ساعت {time_part}"
        return f"{date_part}، {time_part}"
    except (TimeContractError, ValueError, TypeError):
        return fallback


def format_table_datetime(value: Any, fallback: str = "—") -> str:
    return format_datetime_fa(value, fallback=fallback)


def remaining_days(value: Any, *, now: datetime | None = None) -> int:
    """Ceiling count of 24-hour periods until an absolute expiry instant."""
    import math
    current = to_utc(now) if now is not None else now_utc()
    seconds = (to_utc(value) - current).total_seconds()
    return max(0, math.ceil(seconds / 86400))


def format_relative_fa(value: Any, *, now: datetime | None = None,
                       fallback: str = "—") -> str:
    try:
        current = _aware(now or now_utc()).astimezone(UTC)
        target = to_utc(value)
        seconds = int((current - target).total_seconds())
        if seconds < -60:
            return format_datetime_fa(target)
        if seconds < 45:
            return "همین الان"
        minutes = seconds // 60
        if minutes < 60:
            return f"{fa_digits(minutes)} دقیقه پیش"
        hours = minutes // 60
        if hours < 24:
            return f"{fa_digits(hours)} ساعت پیش"
        local_now = current.astimezone(TEHRAN).date()
        local_target = target.astimezone(TEHRAN).date()
        days = (local_now - local_target).days
        if days == 1:
            return "دیروز"
        if days < 7:
            return f"{fa_digits(days)} روز پیش"
        return format_date_fa(target)
    except (TimeContractError, ValueError, TypeError):
        return fallback


def start_of_day_tehran(value: date | datetime | None = None) -> datetime:
    local_date = today_tehran() if value is None else (
        value.astimezone(TEHRAN).date() if isinstance(value, datetime) else value
    )
    return datetime.combine(local_date, time.min, tzinfo=TEHRAN)


def end_of_day_tehran(value: date | datetime | None = None) -> datetime:
    return start_of_day_tehran(value) + timedelta(days=1) - timedelta(microseconds=1)


def day_bounds_utc(value: date | datetime | None = None) -> tuple[datetime, datetime]:
    """Return [start, next_start) UTC bounds for one Tehran civil day."""
    start = start_of_day_tehran(value)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def jalali_day_bounds_utc(value: str) -> tuple[datetime, datetime]:
    day = parse_jalali_date(value)
    return day_bounds_utc(day)


def start_of_month_tehran(value: date | None = None) -> datetime:
    """Start of the Persian/Jalali business month containing ``value``."""
    day = value or today_tehran()
    jalali = jdatetime.date.fromgregorian(date=day)
    first = jdatetime.date(jalali.year, jalali.month, 1).togregorian()
    return start_of_day_tehran(first)


def start_of_year_tehran(value: date | None = None) -> datetime:
    """Nowruz boundary for the Persian/Jalali business year."""
    day = value or today_tehran()
    jalali = jdatetime.date.fromgregorian(date=day)
    first = jdatetime.date(jalali.year, 1, 1).togregorian()
    return start_of_day_tehran(first)


def start_of_week_tehran(value: date | None = None) -> datetime:
    day = value or today_tehran()
    # Python Monday=0; Persian week starts Saturday=5.
    days_since_saturday = (day.weekday() - 5) % 7
    return start_of_day_tehran(day - timedelta(days=days_since_saturday))


def week_key_tehran(value: date | None = None) -> str:
    """Stable Saturday-start business-week key (Gregorian storage date)."""
    return start_of_week_tehran(value).date().isoformat()


def month_key_tehran(value: date | None = None) -> str:
    """Stable ASCII key for the Persian/Jalali business month."""
    jalali = jdatetime.date.fromgregorian(date=value or today_tehran())
    return f"{jalali.year:04d}-{jalali.month:02d}"


def diagnostics() -> dict:
    utc = now_utc()
    local = utc.astimezone(TEHRAN)
    return {
        "timezone": APP_TIMEZONE,
        "locale": APP_LOCALE,
        "calendar": APP_CALENDAR,
        "server_utc": utc.isoformat(),
        "tehran": local.isoformat(),
        "tehran_display": format_datetime_fa(utc, long=True, seconds=True),
        "today_jalali": format_date_fa(utc, long=True),
        "utc_offset": local.strftime("%z"),
        "unix_timestamp": int(utc.timestamp()),
        "week_start": "شنبه",
    }
