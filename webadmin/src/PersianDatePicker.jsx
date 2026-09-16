import React from 'react';
import DatePickerPackage from 'react-multi-date-picker';
import TimePickerPackage from 'react-multi-date-picker/plugins/time_picker';
import persian from 'react-date-object/calendars/persian';
import persianFa from 'react-date-object/locales/persian_fa';
import { jalaliInputToGregorian, tehranInputToUtc, toJalaliInput } from './time.js';

// Both packages publish CommonJS-compatible defaults. Vite dev and production
// expose them differently, so unwrap once at this integration boundary.
const DatePicker = DatePickerPackage?.default || DatePickerPackage;
const TimePicker = TimePickerPackage?.default || TimePickerPackage;

export function PersianDatePicker({ value, onChange, minDate, maxDate, disabled = false, placeholder = '۱۴۰۵/۰۵/۲۴', id, ariaLabel = 'تاریخ شمسی' }) {
  const display = value ? toJalaliInput(value) : '';
  const input = <input id={id} className="inp fa-date-input" placeholder={placeholder}
    inputMode="numeric" aria-label={ariaLabel} disabled={disabled} />;
  return <DatePicker value={display} calendar={persian} locale={persianFa} format="YYYY/MM/DD"
    weekStartDayIndex={0} minDate={minDate} maxDate={maxDate} disabled={disabled} render={input}
    containerClassName="fa-picker" calendarPosition="bottom-right"
    onChange={date => onChange?.(date ? jalaliInputToGregorian(date.format('YYYY/MM/DD')) : '')} />;
}

export function PersianDateTimePicker({ value, onChange, disabled = false, placeholder = '۱۴۰۵/۰۵/۲۴ ۱۸:۳۰', id, ariaLabel = 'تاریخ و ساعت تهران' }) {
  const display = value ? toJalaliInput(value, { withTime: true }) : '';
  const input = <input id={id} className="inp fa-date-input" placeholder={placeholder}
    inputMode="numeric" aria-label={ariaLabel} disabled={disabled} />;
  return <DatePicker value={display} calendar={persian} locale={persianFa} format="YYYY/MM/DD HH:mm"
    weekStartDayIndex={0} disabled={disabled} render={input}
    plugins={[<TimePicker key="time" position="bottom" hideSeconds />]}
    containerClassName="fa-picker" calendarPosition="bottom-right"
    onChange={date => onChange?.(date ? tehranInputToUtc(date.format('YYYY/MM/DD HH:mm')) : '')} />;
}
