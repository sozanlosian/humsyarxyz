import jalaali from 'jalaali-js';
const { isValidJalaaliDate, jalaaliMonthLength, toGregorian } = jalaali;

export const HUMSYAR_TIME = Object.freeze({
  timeZone: 'Asia/Tehran', locale: 'fa-IR', calendar: 'persian', weekStart: 'شنبه',
});
const LOCALE = 'fa-IR-u-ca-persian-nu-arabext';
const LATIN = 'en-CA-u-ca-gregory-nu-latn';
const FA_TO_EN = Object.freeze({ '۰':'0','۱':'1','۲':'2','۳':'3','۴':'4','۵':'5','۶':'6','۷':'7','۸':'8','۹':'9','٠':'0','١':'1','٢':'2','٣':'3','٤':'4','٥':'5','٦':'6','٧':'7','٨':'8','٩':'9' });

export const enDigits = value => String(value ?? '').replace(/[۰-۹٠-٩]/g, char => FA_TO_EN[char]);
export const faDigits = value => String(value ?? '').replace(/\d/g, char => '۰۱۲۳۴۵۶۷۸۹'[Number(char)]);

function machineDate(value) {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  if (typeof value === 'number') { const date = new Date(value); return Number.isNaN(date.getTime()) ? null : date; }
  let raw = String(value ?? '').trim();
  if (!raw) return null;
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) raw += 'T12:00:00Z';
  else {
    raw = raw.replace(' ', 'T');
    // Legacy HUMSYAR ISO strings were emitted by UTC Railway without an offset.
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(raw)) raw += 'Z';
  }
  const date = new Date(raw);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatter(options) {
  return new Intl.DateTimeFormat(LOCALE, { timeZone: HUMSYAR_TIME.timeZone, ...options });
}
const DATE = formatter({ year: 'numeric', month: '2-digit', day: '2-digit' });
const LONG_DATE = formatter({ year: 'numeric', month: 'long', day: 'numeric' });
const DATE_TIME = formatter({ year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
const LONG_DATE_TIME = formatter({ year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
const TOOLTIP = formatter({ year: 'numeric', month: 'long', day: 'numeric', weekday: 'long', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' });
const TIME = formatter({ hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
const GREGORIAN_STAMP = new Intl.DateTimeFormat(LATIN, { timeZone: HUMSYAR_TIME.timeZone, year: 'numeric', month: '2-digit', day: '2-digit' });

const clean = text => text.replace(/\u200e|\u200f/g, '').replace(/[,،]\s*/g, '، ');
export function formatFaDate(value, { long = false, fallback = '—' } = {}) {
  const date = machineDate(value); return date ? clean((long ? LONG_DATE : DATE).format(date)) : fallback;
}
export function formatFaDateTime(value, { long = false, fallback = '—' } = {}) {
  const date = machineDate(value); return date ? clean((long ? LONG_DATE_TIME : DATE_TIME).format(date)) : fallback;
}
export function formatFaTime(value, fallback = '—') {
  const raw = enDigits(value).trim();
  if (/^\d{2}:\d{2}$/.test(raw)) return faDigits(raw);
  const date = machineDate(value); return date ? TIME.format(date) : fallback;
}
/* روز+ماه شمسی کوتاه — برای لیبل نمودارها و تولتیپ‌های فشرده */
const DAY_MONTH = formatter({ day: 'numeric', month: 'long' });
export function formatFaDayMonth(value, fallback = '—') {
  const date = machineDate(value); return date ? clean(DAY_MONTH.format(date)) : fallback;
}
export function formatFaTooltip(value, fallback = '—') {
  const raw = enDigits(value).trim();
  if (/^\d{2}:\d{2}$/.test(raw)) return formatFaTime(raw, fallback);
  const date = machineDate(value); return date ? clean(TOOLTIP.format(date)) : fallback;
}
export function formatTableDateTime(value, fallback = '—') { return formatFaDateTime(value, { fallback }); }
export function formatRelativeTime(value, now = new Date()) {
  const date = machineDate(value); if (!date) return '—';
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);
  if (seconds < -60) return formatFaDateTime(date);
  if (seconds < 45) return 'همین الان';
  const rtf = new Intl.RelativeTimeFormat(LOCALE, { numeric: 'auto' });
  if (seconds < 3600) return rtf.format(-Math.floor(seconds / 60), 'minute');
  if (seconds < 86400) return rtf.format(-Math.floor(seconds / 3600), 'hour');
  if (seconds < 604800) return rtf.format(-Math.floor(seconds / 86400), 'day');
  return formatFaDate(date);
}
export function fileDateStamp(value = new Date()) { return GREGORIAN_STAMP.format(machineDate(value) || new Date()); }
export function machineIso(value) { const date = machineDate(value); return date ? date.toISOString() : ''; }
export function isFutureInstant(value, now = new Date()) { const date = machineDate(value); return !!date && date.getTime() > now.getTime(); }
export function toJalaliInput(value, { withTime = false } = {}) {
  const date = machineDate(value); if (!date) return '';
  const options = { timeZone: HUMSYAR_TIME.timeZone, calendar: 'persian', numberingSystem: 'latn',
    year: 'numeric', month: '2-digit', day: '2-digit', ...(withTime ? { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' } : {}) };
  const values = Object.fromEntries(new Intl.DateTimeFormat('en-US', options).formatToParts(date).map(part => [part.type, part.value]));
  return `${values.year}/${values.month}/${values.day}${withTime ? ` ${values.hour}:${values.minute}` : ''}`;
}

export function jalaliDateParts(value) {
  const raw = toJalaliInput(value);
  const match = raw.match(/^(\d{4})\/(\d{2})\/(\d{2})$/);
  return match ? { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]), monthKey: `${match[1]}/${match[2]}` } : null;
}
export function jalaliMonthLengthFor(value) {
  const parts = jalaliDateParts(value);
  return parts ? jalaaliMonthLength(parts.year, parts.month) : 0;
}

export function jalaliInputToGregorian(value) {
  const raw = enDigits(value).trim();
  const match = raw.match(/^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$/);
  if (!match) return '';
  const [, jy, jm, jd] = match.map(Number);
  if (!isValidJalaaliDate(jy, jm, jd)) return '';
  const { gy, gm, gd } = toGregorian(jy, jm, jd);
  return `${gy}-${String(gm).padStart(2, '0')}-${String(gd).padStart(2, '0')}`;
}

export function tehranInputToUtc(value) {
  const raw = enDigits(value).trim();
  const match = raw.match(/^(\d{4})[/-](\d{1,2})[/-](\d{1,2})(?:[ T،-]+(\d{1,2}):(\d{2}))?$/);
  if (!match) return '';
  const gregorian = jalaliInputToGregorian(match.slice(1, 4).join('/'));
  if (!gregorian) return '';
  const hour = Number(match[4] || 0); const minute = Number(match[5] || 0);
  if (hour > 23 || minute > 59) return '';
  // Resolve Tehran civil input through Intl offset rather than browser timezone.
  const [year, month, day] = gregorian.split('-').map(Number);
  const utcGuess = Date.UTC(year, month - 1, day, hour, minute);
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: HUMSYAR_TIME.timeZone, timeZoneName: 'longOffset', hour: '2-digit' }).formatToParts(new Date(utcGuess));
  const zone = parts.find(part => part.type === 'timeZoneName')?.value || '';
  const offset = zone.match(/GMT([+-])(\d{2}):(\d{2})/);
  if (!offset) return '';
  const minutes = (Number(offset[2]) * 60 + Number(offset[3])) * (offset[1] === '+' ? 1 : -1);
  return new Date(utcGuess - minutes * 60_000).toISOString();
}

export function systemTimeDiagnostics(now = new Date()) {
  const date = machineDate(now) || new Date();
  const offsetPart = new Intl.DateTimeFormat('en-US', { timeZone: HUMSYAR_TIME.timeZone, timeZoneName: 'longOffset', hour: '2-digit' }).formatToParts(date).find(part => part.type === 'timeZoneName')?.value;
  return { timezone: HUMSYAR_TIME.timeZone, locale: HUMSYAR_TIME.locale, calendar: HUMSYAR_TIME.calendar,
    utc: date.toISOString(), tehran: formatFaTooltip(date), offset: offsetPart || '—', unix: Math.floor(date.getTime() / 1000) };
}
