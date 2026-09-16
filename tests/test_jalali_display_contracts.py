# -*- coding: utf-8 -*-
"""🛡 قرارداد نمایشی جلالی/تهران — نگهبان استاتیک.

هر تاریخ/ساعتی که چشم کاربر یا ادمین می‌بیند باید از هلپرهای جلالی رد شود:
- وب‌ادمین: FaDate/FaDateTime/FaTime/RelativeTime یا formatFa* از time.js
- مینی‌اپ: faDate/faDateTime/faDayMonth/faTime یا toLocale*‎('fa-IR')
- ربات: fmt_jalali*/format_*_fa/fa_digits

فرمت‌های ماشینی (ISO ذخیره‌سازی، ورودی‌های date/time، کلیدهای نمودار،
شناسه‌ها، iCal، diagnostics فنی) عمداً دست‌نخورده‌اند و این سوئیت
کاری به آن‌ها ندارد — فقط رندرهای کاربرنما را قفل می‌کند.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding='utf-8')


class WebadminJalaliContracts(unittest.TestCase):
    def test_time_helpers_exist(self):
        src = read('webadmin', 'src', 'time.js')
        for token in ('formatFaDate', 'formatFaDateTime', 'formatFaTime',
                      'formatFaDayMonth', "timeZone: 'Asia/Tehran'",
                      'fa-IR-u-ca-persian'):
            self.assertIn(token, src)

    def test_exam_table_uses_fa_date(self):
        src = read('webadmin', 'src', 'pages', 'Exams.jsx')
        self.assertIn('<FaDate value={r.date} />', src)
        self.assertNotIn('<span className="code">{r.date}</span>', src)

    def test_feature_schedule_uses_fa_date(self):
        src = read('webadmin', 'src', 'pages', 'Features.jsx')
        self.assertIn('formatFaDate(r.policy.effective_from)', src)
        self.assertNotIn("effective_from || '').slice(0, 10)", src)

    def test_analytics_daily_chart_jalali(self):
        src = read('webadmin', 'src', 'pages', 'Analytics.jsx')
        self.assertIn('formatFaDayMonth(row.date)', src)
        self.assertIn('formatFaDate(peak.date)', src)
        self.assertNotIn('row.date.slice(5)', src)
        self.assertNotIn('<b>{peak.date}</b>', src)
        self.assertNotIn('<td dir="ltr">{row.date}</td>', src)

    def test_finance_chart_jalali(self):
        src = read('webadmin', 'src', 'pages', 'Subscriptions.jsx')
        self.assertIn('formatFaDayMonth(d.day)', src)
        self.assertIn('formatFaDate(d.day)', src)
        self.assertNotIn('d.day.slice(5)', src)

    def test_report_tooltip_jalali(self):
        src = read('webadmin', 'src', 'pages', 'Questions.jsx')
        self.assertIn('formatFaDateTime(info.last_report_at)', src)

    def test_schedule_times_use_fa_time(self):
        src = read('webadmin', 'src', 'pages', 'contentTabs.jsx')
        self.assertGreaterEqual(src.count('formatFaTime('), 8)
        for raw in ('{f.time} تا {f.end_time}', '{r.time}',
                    '`${s.time} تا ${s.end_time}`',
                    '(${s.time} تا ${s.end_time})'):
            self.assertNotIn(raw, src)

    def test_recommendation_evidence_jalali(self):
        src = read('webadmin', 'src', 'pages', 'Users.jsx')
        self.assertIn('formatFaDateTime(sub.end_date)', src)
        self.assertIn('formatFaDateTime(u.last_active)', src)
        self.assertNotIn('end_date = ${sub.end_date}', src)
        self.assertNotIn('last_active=${u.last_active}', src)

    def test_user_csv_export_jalali(self):
        src = read('webadmin', 'src', 'pages', 'Users.jsx')
        self.assertIn('formatFaDate(r.subscription.end_date)', src)
        self.assertIn('formatFaDateTime(r.last_active)', src)
        self.assertIn('formatFaDateTime(r.registered_at)', src)

    def test_uptime_is_persian_duration(self):
        src = read('api', 'routers', 'admin_panel.py')
        self.assertIn('uptime_fa', src)
        self.assertIn('روز و', src)
        self.assertNotIn('f"{h}h {m}m"', src)


class MiniappJalaliContracts(unittest.TestCase):
    def test_format_helpers_exist(self):
        src = read('miniapp', 'src', 'lib', 'format.js')
        for token in ('export const faDate', 'export const faDateTime',
                      'export const faDayMonth', 'export const faTime',
                      "timeZone: 'Asia/Tehran'"):
            self.assertIn(token, src)

    def test_no_raw_created_at_renders(self):
        for page in (('pages', 'Admin', 'AiAdmin.jsx'),
                     ('pages', 'Learn', 'MyQuestions.jsx'),
                     ('pages', 'Admin', 'AdminOperations.jsx')):
            src = read('miniapp', 'src', *page)
            self.assertNotIn('{report.created_at}', src)
            self.assertNotIn('{item.created_at}', src)
            self.assertNotIn('{item.at}', src)

    def test_fixed_renders_use_helpers(self):
        self.assertIn('faDateTime(report.created_at)',
                      read('miniapp', 'src', 'pages', 'Admin', 'AiAdmin.jsx'))
        self.assertIn('faDate(item.created_at)',
                      read('miniapp', 'src', 'pages', 'Learn', 'MyQuestions.jsx'))
        self.assertIn('faDateTime(item.at)',
                      read('miniapp', 'src', 'pages', 'Admin', 'AdminOperations.jsx'))

    def test_dashboard_exams_jalali(self):
        src = read('miniapp', 'src', 'pages', 'Dashboard', 'index.jsx')
        self.assertIn('faDate(exam.date)', src)
        self.assertIn('faTime(exam.time)', src)
        self.assertIn('faNum(days)', src)
        self.assertNotIn('{exam.date ||', src)

    def test_schedule_admin_jalali(self):
        src = read('miniapp', 'src', 'pages', 'Admin', 'AcademicScheduleAdmin.jsx')
        self.assertIn('faTime(form.time)', src)
        self.assertIn('faDate(item.date)', src)
        self.assertNotIn('⏰ {form.time} تا {form.end_time}', src)


class BotJalaliContracts(unittest.TestCase):
    def test_subscription_activation_jalali(self):
        src = read('subscription.py')
        self.assertIn("_fmt_jalali_dt(act.get('end_date', ''), with_time=False)", src)
        self.assertNotIn('📅 تا: {act.get(', src)

    def test_ai_tool_results_jalali(self):
        src = read('ai_solver.py')
        self.assertIn("format_datetime_fa(u.get('registered_at',''), fallback='—')", src)
        self.assertIn("format_datetime_fa(user.get('registered_at',''), fallback='—')", src)
        self.assertNotIn("{user.get('registered_at','—')}", src)
        self.assertNotIn("{u.get('registered_at','—')}", src)

    def test_admin_durations_fa_digits(self):
        src = read('admin.py')
        for token in ('fa_digits(wallet_cooldown)', 'fmt_jalali_dt(wallet_muted)',
                      'fa_digits(hours)', 'fa_digits(h)} ساعت',
                      "fa_digits(f'{h:02d}"):
            self.assertIn(token, src)
        self.assertNotIn('| ضداسپم {wallet_cooldown}ساعت', src)
        self.assertNotIn('بی‌صدا تا {wallet_muted}', src)


if __name__ == '__main__':
    unittest.main()
