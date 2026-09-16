// HUMSYAR Analytics Dictionary — human semantics for persisted backend metrics.
// UI labels must come from this dictionary instead of exposing raw keys.
export const ANALYTICS_DICTIONARY = {
  users: {
    total_approved: { label: 'دانشجویان تأییدشده', unit: 'نفر', range: 'وضعیت فعلی', source: 'users', calculation: 'تعداد کاربران با approved=true', action: '/users?status=approved' },
    total_pending: { label: 'ثبت‌نام‌های در انتظار تأیید', unit: 'نفر', range: 'وضعیت فعلی', source: 'users', calculation: 'تعداد کاربران با approved=false', action: '/users?status=pending', attention: true },
    new_today: { label: 'ثبت‌نام جدید امروز', unit: 'نفر', range: 'از آغاز امروز به وقت تهران', source: 'users.registered_at', calculation: 'تعداد همه ثبت‌نام‌های ایجادشده از آغاز امروز' },
    new_week: { label: 'ثبت‌نام‌های ۷ روز اخیر', unit: 'نفر', range: '۷ روز rolling', source: 'users.registered_at', calculation: 'تعداد همه ثبت‌نام‌های ایجادشده در ۷ روز اخیر' },
    new_month: { label: 'ثبت‌نام‌های ۳۰ روز اخیر', unit: 'نفر', range: '۳۰ روز rolling', source: 'users.registered_at', calculation: 'تعداد همه ثبت‌نام‌های ایجادشده در ۳۰ روز اخیر' },
    group1: { label: 'دانشجویان گروه ۱', unit: 'نفر', range: 'وضعیت فعلی', source: 'users', calculation: 'کاربران تأییدشده با group=1' },
    group2: { label: 'دانشجویان گروه ۲', unit: 'نفر', range: 'وضعیت فعلی', source: 'users', calculation: 'کاربران تأییدشده با group=2' },
    group_unset: { label: 'دانشجویان بدون گروه', unit: 'نفر', range: 'وضعیت فعلی', source: 'users', calculation: 'تأییدشده‌ها منهای گروه ۱ و ۲', attention: true },
    active_today: { label: 'کاربران فعال امروز', unit: 'نفر', range: 'از آغاز امروز به وقت تهران', source: 'users.last_active', calculation: 'کاربرانی که last_active آن‌ها از آغاز امروز است' },
    active_week: { label: 'کاربران فعال در ۷ روز اخیر', unit: 'نفر', range: '۷ روز rolling', source: 'users.last_active', calculation: 'کاربرانی که آخرین فعالیتشان در ۷ روز اخیر است' },
    inactive_14d: { label: 'غیرفعال برای ۱۴ روز یا بیشتر', unit: 'نفر', range: 'وضعیت فعلی', source: 'users.last_active', calculation: 'کاربران تأییدشده با آخرین فعالیت قدیمی‌تر از ۱۴ روز یا بدون فعالیت' },
    inactive_30d: { label: 'غیرفعال برای ۳۰ روز یا بیشتر', unit: 'نفر', range: 'وضعیت فعلی', source: 'users.last_active', calculation: 'کاربران تأییدشده با آخرین فعالیت قدیمی‌تر از ۳۰ روز یا بدون فعالیت' },
    blocked_bot: { label: 'کاربران مسدودکننده ربات', unit: 'نفر', range: 'وضعیت فعلی', source: 'users.blocked_bot', calculation: 'تعداد کاربران با blocked_bot=true' },
    content_admins: { label: 'مدیران محتوای ثبت‌شده', unit: 'نفر', range: 'وضعیت فعلی', source: 'users.role', calculation: 'تعداد کاربران با role=content_admin' },
  },
  content: {
    bs_lessons: { label: 'درس‌های علوم پایه', unit: 'درس', range: 'وضعیت فعلی', source: 'bs_lessons', calculation: 'تعداد کل سندهای درس علوم پایه', action: '/content' },
    bs_sessions: { label: 'جلسه‌های علوم پایه', unit: 'جلسه', range: 'وضعیت فعلی', source: 'bs_sessions', calculation: 'تعداد کل جلسه‌های علوم پایه', action: '/content' },
    bs_total_content: { label: 'فایل‌های علوم پایه', unit: 'فایل', range: 'وضعیت فعلی', source: 'bs_content', calculation: 'جمع تعداد فایل‌های علوم پایه بر اساس نوع', action: '/content' },
    ref_subjects: { label: 'موضوع‌های رفرنس', unit: 'موضوع', range: 'وضعیت فعلی', source: 'ref_subjects', calculation: 'تعداد کل موضوع‌های رفرنس', action: '/content?tab=refs' },
    ref_books: { label: 'کتاب‌های رفرنس', unit: 'کتاب', range: 'وضعیت فعلی', source: 'ref_books', calculation: 'تعداد کل کتاب‌های رفرنس', action: '/content?tab=refs' },
    ref_total_files: { label: 'فایل‌های رفرنس', unit: 'فایل', range: 'وضعیت فعلی', source: 'ref_files', calculation: 'جمع فایل‌های رفرنس بر اساس زبان', action: '/content?tab=refs' },
    qbank_questions: { label: 'سؤال‌های ساختاریافته تأییدشده', unit: 'سؤال', range: 'وضعیت فعلی', source: 'questions.status', calculation: 'تعداد سؤال‌های approved در دامنه مشترک', action: '/questions?status=approved' },
    qbank_attempts: { label: 'تلاش‌های بانک سؤال', unit: 'پاسخ', range: 'تجمعی', source: 'answers', calculation: 'تعداد پاسخ‌های ثبت‌شده برای سؤال‌های ساختاریافته', action: '/questions' },
    faq_count: { label: 'پرسش‌های راهنما', unit: 'مورد', range: 'وضعیت فعلی', source: 'faq', calculation: 'تعداد کل پرسش‌های FAQ', action: '/content?tab=faq' },
    bs_downloads: { label: 'دانلود منابع علوم پایه', unit: 'دانلود', range: 'تجمعی از ابتدای ثبت داده', source: 'bs_content.downloads', calculation: 'جمع شمارنده downloads همه فایل‌های علوم پایه', action: '/content' },
    ref_downloads: { label: 'دانلود رفرنس‌ها', unit: 'دانلود', range: 'تجمعی از ابتدای ثبت داده', source: 'ref_files.downloads', calculation: 'جمع شمارنده downloads همه فایل‌های رفرنس', action: '/content?tab=refs' },
    new_this_week: { label: 'محتوای افزوده‌شده در ۷ روز اخیر', unit: 'مورد', range: '۷ روز rolling', source: 'bs_content + ref_files + questions', calculation: 'فایل‌های علوم پایه، رفرنس و سؤال‌های جدید در ۷ روز اخیر' },
  },
  questions: {
    approved: { label: 'سؤالات تأییدشده', unit: 'سؤال', range: 'وضعیت فعلی', source: 'questions', calculation: 'تعداد سؤالات با approved=true', action: '/questions?status=approved' },
    pending: { label: 'سؤالات در انتظار بازبینی', unit: 'سؤال', range: 'وضعیت فعلی', source: 'questions', calculation: 'تعداد سؤالات با approved=false', action: '/questions?status=pending', attention: true },
    by_bot: { label: 'سؤالات تأییدشده ساخته ربات', unit: 'سؤال', range: 'وضعیت فعلی', source: 'questions.by_bot', calculation: 'سؤالات تأییدشده با by_bot=true' },
    by_users: { label: 'سؤالات تأییدشده ارسالی کاربران', unit: 'سؤال', range: 'وضعیت فعلی', source: 'questions.by_bot', calculation: 'سؤالات تأییدشده که by_bot=true ندارند' },
    total_attempts: { label: 'پاسخ‌های ثبت‌شده', unit: 'پاسخ', range: 'تجمعی از شمارنده سؤال‌ها', source: 'questions.attempt_count', calculation: 'جمع attempt_count سؤالات تأییدشده' },
    total_correct: { label: 'پاسخ‌های صحیح ثبت‌شده', unit: 'پاسخ صحیح', range: 'تجمعی از شمارنده سؤال‌ها', source: 'questions.correct_count', calculation: 'جمع correct_count سؤالات تأییدشده' },
    accuracy: { label: 'درصد پاسخ‌های صحیح', unit: 'درصد', range: 'تجمعی از شمارنده سؤال‌ها', source: 'questions attempt/correct', calculation: 'مجموع پاسخ صحیح تقسیم بر مجموع تلاش سؤالات تأییدشده × ۱۰۰' },
  },
  tickets: {
    open: { label: 'تیکت‌های باز', unit: 'تیکت', range: 'وضعیت فعلی', source: 'tickets.status', calculation: 'تیکت‌های با status=open', action: '/tickets?status=open', attention: true },
    closed: { label: 'تیکت‌های بسته‌شده', unit: 'تیکت', range: 'تجمعی', source: 'tickets.status', calculation: 'تیکت‌های با status=closed', action: '/tickets?status=closed' },
    total: { label: 'کل تیکت‌ها', unit: 'تیکت', range: 'تجمعی', source: 'tickets', calculation: 'تیکت‌های باز + بسته' },
    new_week: { label: 'تیکت‌های ایجادشده در ۷ روز اخیر', unit: 'تیکت', range: '۷ روز rolling', source: 'tickets.created_at', calculation: 'تیکت‌های ایجادشده در ۷ روز اخیر' },
    new_month: { label: 'تیکت‌های ایجادشده در ۳۰ روز اخیر', unit: 'تیکت', range: '۳۰ روز rolling', source: 'tickets.created_at', calculation: 'تیکت‌های ایجادشده در ۳۰ روز اخیر' },
    closed_week: { label: 'تیکت‌های بسته‌شده در ۷ روز اخیر', unit: 'تیکت', range: '۷ روز rolling', source: 'tickets.closed_at', calculation: 'تیکت‌های بسته با closed_at در ۷ روز اخیر' },
    avg_resolution_h: { label: 'میانگین زمان حل تیکت', unit: 'ساعت', range: 'تیکت‌های حل‌شده ۳۰ روز اخیر', source: 'tickets.created_at/closed_at', calculation: 'میانگین فاصله ایجاد تا بسته‌شدن روی نمونه معتبر' },
    resolved_sample: { label: 'نمونه معتبر زمان حل', unit: 'تیکت', range: '۳۰ روز اخیر', source: 'tickets', calculation: 'تعداد تیکت‌های دارای تاریخ معتبر در محاسبه زمان حل' },
  },
  subscriptions: {
    active: { label: 'اشتراک‌های فعال', unit: 'اشتراک', range: 'وضعیت فعلی', source: 'subscriptions.status', calculation: 'تعداد اشتراک‌های با status=active', action: '/subscriptions?status=active' },
    expired: { label: 'اشتراک‌های منقضی‌شده', unit: 'اشتراک', range: 'وضعیت فعلی', source: 'subscriptions.status', calculation: 'تعداد اشتراک‌های با status=expired' },
    revoked: { label: 'اشتراک‌های لغوشده', unit: 'اشتراک', range: 'وضعیت فعلی', source: 'subscriptions.status', calculation: 'تعداد اشتراک‌های با status=revoked' },
    pending: { label: 'پرداخت‌های در انتظار بررسی', unit: 'رسید', range: 'وضعیت فعلی', source: 'sub_payments.status', calculation: 'تعداد رسیدهای با status=pending', action: '/subscriptions?tab=payments&status=pending', attention: true },
    approved_total: { label: 'رسیدهای تأییدشده', unit: 'رسید', range: 'تجمعی', source: 'sub_payments.status', calculation: 'تعداد رسیدهای با status=approved' },
    rejected_total: { label: 'رسیدهای ردشده', unit: 'رسید', range: 'تجمعی', source: 'sub_payments.status', calculation: 'تعداد رسیدهای با status=rejected' },
    revenue: { label: 'درآمد ثبت‌شده', unit: 'تومان', range: 'تجمعی رسیدهای تأییدشده', source: 'sub_payments.final_price', calculation: 'جمع final_price یا price رسیدهای تأییدشده' },
    revenue_month: { label: 'درآمد ماه جاری', unit: 'تومان', range: 'ماه جاری به وقت تهران', source: 'sub_payments.final_price/reviewed_at', calculation: 'جمع مبلغ رسیدهای تأییدشده با reviewed_at از آغاز ماه' },
    conv_rate: { label: 'نرخ تأیید رسیدهای بررسی‌شده', unit: 'درصد', range: 'تجمعی', source: 'sub_payments.status', calculation: 'تأییدشده تقسیم بر مجموع تأییدشده و ردشده × ۱۰۰' },
    top_plan: { label: 'پرتکرارترین پلن اشتراک', unit: 'نام پلن', range: 'رسیدهای تأییدشده تجمعی', source: 'sub_payments.plan_name', calculation: 'پلن با بیشترین تعداد رسید تأییدشده' },
  },
  pulse: {
    total_actions_week: { label: 'کنش‌های ثبت‌شده در ۷ روز اخیر', unit: 'کنش', range: '۷ روز rolling', source: 'stats.timestamp', calculation: 'تعداد رویدادهای persisted در stats_col طی ۷ روز اخیر' },
    peak_hour: { label: 'پرترافیک‌ترین ساعت', unit: 'ساعت', range: '۷ روز اخیر', source: 'stats.timestamp', calculation: 'ساعتی با بیشترین تعداد رویداد ثبت‌شده' },
    peak_hour_count: { label: 'کنش در ساعت اوج', unit: 'کنش', range: '۷ روز اخیر', source: 'stats.timestamp', calculation: 'تعداد رویدادهای پرترافیک‌ترین ساعت' },
  },
  notifications: {
    runs_checked: { label: 'اجرای اعلان بررسی‌شده', unit: 'اجرا', range: 'حداکثر ۱۰ اجرای اخیر هر job', source: 'notif_runs', calculation: 'تعداد runهای بازیابی‌شده برای job' },
    total_sent: { label: 'پیام ارسال‌شده در نمونه اجراها', unit: 'ارسال', range: 'حداکثر ۱۰ اجرای اخیر هر job', source: 'notif_runs.sent', calculation: 'جمع sent در runهای بررسی‌شده' },
    total_failed: { label: 'ارسال ناموفق در نمونه اجراها', unit: 'ارسال ناموفق', range: 'حداکثر ۱۰ اجرای اخیر هر job', source: 'notif_runs.failed', calculation: 'جمع failed در runهای بررسی‌شده' },
    last_status: { label: 'وضعیت آخرین اجرای اعلان', unit: 'وضعیت', range: 'آخرین run', source: 'notif_runs.status', calculation: 'status جدیدترین run بر اساس started_at' },
    last_at: { label: 'زمان آخرین اجرای اعلان', unit: 'زمان', range: 'آخرین run', source: 'notif_runs.started_at', calculation: 'started_at جدیدترین run' },
  },
  exams: {
    total_runs: { label: 'کل اجرای آزمون تمرینی', unit: 'اجرا', range: 'تجمعی', source: 'exam_sessions', calculation: 'تعداد کل sessionهای آزمون ثبت‌شده', action: '/exams' },
    finished: { label: 'آزمون‌های تکمیل‌شده', unit: 'اجرا', range: 'تجمعی', source: 'exam_sessions.status', calculation: 'تعداد sessionهای آزمون با status=finished', action: '/exams' },
    runs_7d: { label: 'اجرای آزمون در ۷ روز اخیر', unit: 'اجرا', range: '۷ روز rolling', source: 'exam_sessions.started_at', calculation: 'تعداد آزمون‌های شروع‌شده در ۷ روز اخیر', action: '/exams' },
    avg_pct: { label: 'میانگین درصد آزمون‌های تکمیل‌شده', unit: 'درصد', range: 'نمونه حداکثر ۵۰۰ آزمون تکمیل‌شده اخیر', source: 'exam_sessions.correct/total', calculation: 'میانگین درصد پاسخ صحیح آزمون‌های دارای total معتبر' },
  },
  ai: {
    total_today: { label: 'درخواست‌های هوشیار امروز', unit: 'درخواست', range: 'امروز سرور', source: 'users.ai_usage_count', calculation: 'جمع مصرف روزانه کاربرانی که ai_usage_date امروز است', action: '/ai' },
    users_today: { label: 'کاربران هوشیار امروز', unit: 'نفر', range: 'امروز سرور', source: 'users.ai_usage_count/date', calculation: 'کاربران با مصرف هوشیار بیشتر از صفر در امروز' },
    total_alltime: { label: 'کل درخواست‌های هوشیار', unit: 'درخواست', range: 'تجمعی', source: 'users.ai_total_usage', calculation: 'جمع ai_total_usage کاربران' },
    users_alltime: { label: 'کاربران استفاده‌کننده از هوشیار', unit: 'نفر', range: 'تجمعی', source: 'users.ai_total_usage', calculation: 'کاربران با ai_total_usage بیشتر از صفر' },
    tokens_today: { label: 'توکن مصرف‌شده امروز', unit: 'توکن', range: 'امروز سرور', source: 'users.ai_tokens_today', calculation: 'جمع ai_tokens_today کاربران فعال امروز' },
    tokens_alltime: { label: 'کل توکن مصرف‌شده', unit: 'توکن', range: 'تجمعی', source: 'users.ai_total_tokens', calculation: 'جمع ai_total_tokens کاربران' },
  },
};

export const NOTIFICATION_JOBS = {
  exam_reminder: { label: 'یادآوری آزمون', technical: 'exam_reminder' },
  daily_question: { label: 'سؤال روزانه', technical: 'daily_question' },
  new_resources: { label: 'اعلان منابع جدید', technical: 'new_resources' },
};

export const ACTION_LABELS = {
  answer: 'پاسخ به سؤال', bs_download: 'دانلود منبع علوم پایه', ref_download: 'دانلود رفرنس',
  qbank_download: 'دانلود فایل بانک سؤال', ai_usage: 'استفاده از هوشیار',
  exam_complete: 'تکمیل آزمون', question_submit: 'ارسال سؤال',
};

export function metricDefinition(domain, key) {
  return ANALYTICS_DICTIONARY[domain]?.[key] || {
    label: 'شاخص فنی ثبت‌شده', unit: 'مقدار', range: 'بازه در منبع مشخص نشده',
    source: `${domain}.${key}`, calculation: 'تعریف انسانی این شاخص هنوز در واژه‌نامه ثبت نشده است', technicalOnly: true,
  };
}

export function flattenDictionary() {
  return Object.entries(ANALYTICS_DICTIONARY).flatMap(([domain, values]) =>
    Object.entries(values).map(([key, definition]) => ({ domain, key, ...definition })));
}
