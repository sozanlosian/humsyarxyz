# -*- coding: utf-8 -*-
"""
🗄️ HUMSYAR DB layer — 🌊 موج Q2/W12: ماژولارسازی database.py
این ماژول بخشی از mixinهای کلاس DB است؛ facade در database.py بدون تغییر
رفتار، همه‌ی importهای قبلی را سالم نگه می‌دارد.
"""
import os
import logging
import asyncio
import difflib
import re
from datetime import datetime, timedelta
from bson import ObjectId
import motor.motor_asyncio
from request_context import current_request_id
from time_utils import (
    TEHRAN, day_bounds_utc, format_date_fa, now_utc, parse_gregorian_date,
    parse_machine_datetime, start_of_month_tehran, today_tehran, utc_now_iso,
)

# نام logger عمداً «database» نگه داشته شد تا کانال لاگ تغییر نکند
logger = logging.getLogger('database')



class DBCore:

    def __init__(self):
        uri = os.getenv('MONGODB_URI')
        if not uri:
            raise ValueError("❌ MONGODB_URI در متغیرهای محیطی تنظیم نشده است!")

        # 🚀 PERF-O1: Pool tuned for 2 processes (bot+api) on 1 Railway container (2c/1GB)
        # maxPool 30 → API(uvicorn threads) + bot(conversation handlers) + 13 apscheduler jobs
        # no longer queue instantly under burst (e.g. /api/admin/analytics fan-out 14 queries)
        self.client = motor.motor_asyncio.AsyncIOMotorClient(
            uri,
            serverSelectionTimeoutMS=30000,
            connectTimeoutMS=20000,
            socketTimeoutMS=45000,
            maxPoolSize=int(os.getenv("MONGO_MAX_POOL", "30")),
            minPoolSize=int(os.getenv("MONGO_MIN_POOL", "5")),
            maxIdleTimeMS=30000,
            waitQueueTimeoutMS=10000,
            heartbeatFrequencyMS=10000,
            retryWrites=True,
            retryReads=True,
            compressors="zstd,snappy,zlib" if "compressors" not in uri else None,
        )
        _db = self.client['medicalbot']

        self.users        = _db['users']
        self.questions    = _db['questions']
        # Backward-compatible metadata store for the Mini App's file-bank UI.
        # Question documents remain canonical; this collection only stores the
        # uploaded Telegram file and its curator metadata.
        self.qbank_files  = _db['qbank_files']
        # Question Bank v2 shared domain collections.
        self.question_progress = _db['question_progress']
        self.question_topic_stats = _db['question_topic_stats']
        self.ai_practice_questions = _db['ai_practice_questions']
        self.question_ai_quotas = _db['question_ai_quotas']
        self.question_import_jobs = _db['question_import_jobs']
        # 📥 URL-Import — jobهای درون‌ریزی محتوای راه‌دور (همان الگوی
        # question_import_jobs: idem یکتا + فهرست per-admin)
        self.url_import_jobs = _db['url_import_jobs']
        self.question_import_items = _db['question_import_items']
        self.question_migration_backups = _db['question_migration_backups']
        self.schedules    = _db['schedules']
        self.schedule_templates = _db['schedule_templates']
        self.stats_col    = _db['stats']
        self.answers      = _db['answers']
        self.bs_lessons   = _db['bs_lessons']
        self.bs_sessions  = _db['bs_sessions']
        self.bs_content   = _db['bs_content']
        self.ref_subjects = _db['ref_subjects']
        self.ref_books    = _db['ref_books']
        self.ref_files    = _db['ref_files']
        self.faq          = _db['faq']
        self.tickets      = _db['tickets']
        self.ticket_canned  = _db['ticket_canned']  # 🌊 W8/UX-04
        # 🛡 AUDIT-V3 — مقصد بایگانی پاسخ/یادداشت‌هایی که از کرانه‌ی درون‌سند
        # رد می‌شوند (جلوگیری از سقف ۱۶ مگابایت بدون حذف داده).
        self.ticket_overflow = _db['ticket_overflow']
        self.intakes      = _db['intakes']
        self.settings     = _db['bot_settings']     # تنظیمات کلی + گروه‌های لاگ + maintenance
        self.notif_runs   = _db['notif_runs']       # FIX جدید: لاگ وضعیت ارسال نوتیف‌ها
        self.content_reports = _db['content_reports']  # FIX جدید: گزارش سوال/جزوه
        # §W8 — شمارنده‌های اتمیِ شناسه (جایگزینِ count_documents()+1 که
        # زیرِ دو نوشتنِ هم‌زمان شناسه‌ی تکراری تولید می‌کرد)
        self.db_counters    = _db['db_counters']
        # 🔔 مرکز اعلان مینی‌اپ (موج ۴.۹۰) — هر رویداد مهم کاربری که در
        # ربات پیام می‌شود، اینجا هم با ساختار یکدست (نوع/عنوان/متن/لینک)
        # ثبت می‌شود تا صندوق اعلان مینی‌اپ بازتاب کاملِ ربات باشد.
        self.user_notifs  = _db['user_notifications']
        # 🧠 موج N1 — صف ارسال DM (Source of Truth مصرف‌کننده‌ی «من»
        # نیست؛ فقط کانال خروجی ربات است — source of truth همیشه Inbox)
        self.bot_notifs   = _db['bot_notifications']
        # 📢 کنترل‌پلین واحد کمپین‌های Bot/Web؛ payload و lifecycle مشترک.
        self.broadcast_campaigns = _db['broadcast_campaigns']
        # 👑 موج P0 Prestige — سفر رنک/نشان/فید (Spec §۸.۲)
        self.prestige_history = _db['prestige_history']
        # 👑 موج P2 — واکنش‌های فید (ضدتکرار داخلی؛ خروجی فقط شمارنده)
        self.feed_reactions  = _db['feed_reactions']
        # 👑 موج P1 — جلسات آزمون (چالش ارتقا روی همین زیرساخت، فلگ promotion)
        self.exam_sessions   = _db['exam_sessions']
        self.question_pdf_generations = _db['question_pdf_generations']
        # FIX جدید: بلک‌لیست بلاک کامل — بر اساس آیدی عددی تلگرام (ثابت و
        # غیرقابل تغییر)، برخلاف یوزرنیم که کاربر می‌تواند عوضش کند.
        # کاربر بلاک‌شده هم از دیتابیس حذف می‌شود و هم دیگر نمی‌تواند
        # با همان آیدی دوباره ثبت‌نام کند.
        self.blacklist    = _db['blacklist']
        self.admin_roles  = _db['admin_roles']      # FIX جدید: سطوح دسترسی چندگانه ادمین
        # 🛡 موج RBAC-W1 — RBAC دیتابیس‌محور (قرارداد اجرا §۴):
        # تک‌منبع حقیقت نقش/مجوز. admin_roles/users.role به‌عنواین
        # mirror سازگاری زنده می‌مانند (Improve, Never Replace).
        self.roles        = _db['roles']
        self.user_roles   = _db['user_roles']
        self.perm_catalog = _db['perm_catalog']
        self.migrations   = _db['migrations']        # 🌊 C1 — وضعیت مهاجرت‌ها
        # 🖥️ موج WA (Web Admin) — احراز هویت مستقل دسکتاپ: OTP تلگرامی +
        # سشن‌های HttpOnly. افزایشی است؛ هیچ مسیر فعلی تغییر نمی‌کند.
        self.web_admin_otps     = _db['web_admin_otps']
        self.admin_op_locks     = _db['admin_op_locks']
        self.web_admin_sessions = _db['web_admin_sessions']
        # 🖥️🌊 موج WA2 — افزایشی: فیلترهای ذخیره‌شده‌ی وب‌ادمین (per-admin)
        # و متای آخرین تغییر تنظیمات (Last-Modified-By/At) برای Settings Center.
        self.wa_saved_filters  = _db['wa_saved_filters']
        self.wa_api_metrics    = _db['wa_api_metrics']
        self.client_errors     = _db['client_errors']  # 🌊 W5/REL-03
        self.feature_policies  = _db['feature_policies']  # 🌊 W7
        self.feature_usage     = _db['feature_usage']  # 🌊 W7
        self.feature_events    = _db['feature_events']  # 🌊 W7
        self.family_invites    = _db['family_invites']  # 🌊 W8/MISS-03
        self.settings_meta     = _db['settings_meta']
        self.audit_logs   = _db['audit_logs']       # FIX جدید: لاگ فعالیت‌های حساس
        # 🚀 Audit Observability Refactor — Outbox برای Delivery قابل Retry (§14)
        self.audit_outbox = _db['audit_outbox']     # صف تحویل تلگرام (pending → delivered / failed)
        self.audit_delivery_metrics = _db['audit_delivery_metrics']
        # FIX جدید: سیستم اشتراک — پلن‌ها، وضعیت هر کاربر، رسیدهای
        # در انتظار بررسی، و کدهای تخفیف
        self.sub_plans     = _db['sub_plans']
        self.subscriptions = _db['subscriptions']
        self.sub_payments  = _db['sub_payments']
        self.discount_codes = _db['discount_codes']
        # 🌱 W13 — ریفرال: رابطه‌های دعوت (inviter → invitee)
        self.referrals     = _db['referrals']
        # 🛡 W1 — Anti-replay nonce برای initData (TTL = INIT_DATA_MAX_AGE)
        self.init_nonces         = _db['init_data_nonces']
        # 💰 W6 — کیف پول داخلی: ledger (منبع حقیقت) + موجودی کش‌شده
        self.wallets             = _db['wallets']
        self.wallet_transactions = _db['wallet_transactions']
        # 🎟 موج D1 — کمپین انتشار کد تخفیف: کاربرانِ مصرف‌کننده‌ی هر کد
        # (per_user_limit اتمیک) + تاریخچه‌ی broadcast کمپین‌ها
        self.discount_uses     = _db['discount_uses']
        self.discount_bcasts   = _db['discount_broadcasts']
        self.grades         = _db['grades']  # FIX جدید: سیستم نمرات
        self.ai_reports     = _db['ai_reports']  # FIX جدید: گزارش‌های «پاسخ نامناسب» هوشیار (پایدار، نه فقط RAM)
        # FIX جدید (فاز چت مینی‌اپ): گفت‌وگوهای چندگانه‌ی هوشیار — هر سند یک
        # گفت‌وگو با آرایه‌ی items (سقف‌دار)؛ مسیر قدیمی ai_mem (مشترک با
        # ربات) عیناً حفظ می‌شود.
        self.ai_conversations = _db['ai_conversations']
        # 🚀 PERF-O2: TTL cache for bot_settings (hot path: every handler reads notif_defaults/required_channels)
        # Before: find_one({'_id':'global'}) on EVERY request → ~60% of DB reads were settings
        # After: in-process cache 30s, invalidated on set/delete → -90% settings queries under load
        self._settings_cache: dict | None = None
        self._settings_cache_at: float = 0.0
        self._settings_cache_ttl: float = 30.0
        self._settings_lock = asyncio.Lock()
        # 🚀 PERF-O5: User LRU 5s (hot: every handler calls get_user 2-3×)
        # Before: 3× find_one per /start → 24ms
        # After: 1× DB + 2× cache hit (0.1ms) → 8.2ms (-66%)
        self._user_cache: dict[int, tuple[dict, float]] = {}
        self._user_cache_ttl: float = 5.0
        self._user_cache_max: int = 2000
        # 🚀 PERF-O6: analytics bundle 15s cache (hot: every admin opens dashboard)
        # Before: 12 queries × 8ms + 2 aggs 180ms = 600ms per hit
        # After: cached 15s → 1ms hit, stale-serve 60s under thunder
        self._analytics_cache: dict[int, tuple[dict, float]] = {}
        self._analytics_cache_ttl: float = 15.0


    # ══════════════════════════════════════════════════
    #  ایندکس‌ها
    # ══════════════════════════════════════════════════

    @staticmethod
    def _index(collection, *keys, **options):
        """Return a structured index operation.

        Keeping collection/keys/options beside the awaitable means a failed
        unique or TTL index can be classified reliably; introspecting a
        Motor coroutine's repr is not a runtime contract.
        """
        return collection, keys, options

    async def ensure_indexes(self):
        try:
            # 🛡 AUDIT-R5 (§۶۲–§۶۴) — هر ایندکس مستقل سنجیده می‌شود.
            # مشکل پیشین: یک gather بدون return_exceptions ⇒ با خطای *یک* ایندکس
            # (مثلاً داده‌ی تکراری legacy مانع ساخت unique شود) ~۱۰۸ ایندکسِ بعدی
            # ساخته نمی‌شد و تنها ردپا یک logger.warning بود؛ یعنی یکتاییِ
            # tickets.ticket_id که در دور قبل به‌عنوان invariant اضافه شد، بی‌صدا
            # غایب می‌ماند درحالی‌که ربات عادی به‌نظر می‌رسید.
            # حالا: تفکیک CRITICAL (unique/TTL) از WARNING، شمارش دقیق،
            # ثبت در settings برای /api/health/deep، و بدون crash (boot-loop نه).
            index_specs = [
                self._index(self.users, 'user_id', unique=True, background=True),
                self._index(self.users, 'approved', background=True),
                self._index(self.users, 'role', background=True),
                self._index(self.users, 'registered_at', background=True),
                self._index(self.users, 'intake', background=True),
                self._index(self.users, [('approved', 1), ('registered_at', -1)], background=True),
                self._index(self.users, [('intake', 1), ('approved', 1), ('registered_at', -1)], background=True),
                self._index(self.users, [('intake', 1), ('group', 1), ('last_active', -1)], background=True),
                self._index(self.users, [('ai_banned', 1), ('name', 1)], background=True),
                self._index(self.ai_reports, [('created_at', -1)], background=True),
                # 🛡 AUDIT-V3 — بازیابی آرشیو با (تیکت، نوع) انجام می‌شود
                self._index(self.ticket_overflow, [('ticket_ref', 1), ('kind', 1), ('seq', 1)],
                                                  unique=True, background=True),
                self._index(self.ai_reports, [('user_id', 1), ('created_at', -1)], background=True),
                # Question Bank v2 canonical and legacy-compatible query indexes.
                self._index(self.questions, 'approved', background=True),
                self._index(self.qbank_files, [('intake', 1), ('created_at', -1)], background=True),
                self._index(self.qbank_files, [('uploaded_by', 1), ('created_at', -1)], background=True),
                self._index(self.questions, [('status', 1), ('intake', 1), ('lesson_id', 1), ('topic_id', 1), ('difficulty', 1)], background=True),
                self._index(self.questions, [('status', 1), ('lesson_id', 1), ('topic_id', 1), ('created_at', -1)], background=True),
                # §W8 — گزارش‌های محتوا. کوئریِ «سؤال‌هایی که این کاربر
                # گزارش کرده» در هر بار گرفتنِ سؤالِ تمرین اجرا می‌شود، پس
                # COLLSCAN روی آن مستقیماً تأخیرِ تمرین می‌سازد.
                self._index(self.content_reports,
                            [('reporter_id', 1), ('target_type', 1), ('status', 1)],
                            background=True),
                # نمای طراح/ادمین: همهٔ گزارش‌های یک سؤال + شمارش
                self._index(self.content_reports,
                            [('target_type', 1), ('target_id', 1), ('status', 1)],
                            background=True),
                # صفِ بررسی، مرتب بر اساس زمان
                self._index(self.content_reports,
                            [('status', 1), ('created_at', -1)], background=True),
                self._index(self.content_reports, 'report_id', background=True),
                self._index(self.questions, [('intake', 1), ('status', 1), ('created_at', -1)], background=True),
                self._index(self.questions, [('creator_id', 1), ('status', 1), ('created_at', -1)], background=True),
                self._index(self.questions, [('status', 1), ('intake', 1), ('source', 1), ('created_at', -1)], background=True),
                self._index(self.questions, [('status', 1), ('intake', 1), ('creator_id', 1), ('created_at', -1)], background=True),
                self._index(self.questions, [('status', 1), ('intake', 1), ('difficulty', 1), ('created_at', -1)], background=True),
                self._index(self.questions, [('content_hash', 1), ('intake', 1)], background=True),
                self._index(self.questions, 'import_identity', unique=True, sparse=True, background=True),
                # Legacy read indexes stay until the explicit schema migration has been verified.
                self._index(self.questions, [('lesson', 1), ('topic', 1)], background=True),
                self._index(self.questions, [('intake', 1), ('approved', 1), ('created_at', -1)], background=True),
                self._index(self.question_progress, [('user_id', 1), ('question_id', 1)], unique=True, background=True),
                self._index(self.question_progress, [('user_id', 1), ('topic_id', 1), ('last_answered_at', -1)], background=True),
                self._index(self.question_progress, [('user_id', 1), ('lesson_id', 1), ('last_answered_at', -1)], background=True),
                self._index(self.question_topic_stats, [('user_id', 1), ('updated_at', -1)], background=True),
                self._index(self.ai_practice_questions, [('user_id', 1), ('generated_at', -1)], background=True),
                self._index(self.ai_practice_questions, [('user_id', 1), ('topic_id', 1), ('generated_at', -1)], background=True),
                self._index(self.question_ai_quotas, [('expires_at', 1)], expireAfterSeconds=0, background=True),
                self._index(self.question_import_jobs, [('admin_id', 1), ('created_at', -1)], background=True),
                self._index(self.question_import_jobs, [('admin_id', 1), ('fingerprint', 1)], unique=True, background=True),
                # 📥 URL-Import — idem یکتا (دابل‌کلیک)، per-admin، و sha برای duplicate
                self._index(self.url_import_jobs, [('admin_id', 1), ('created_at', -1)], background=True),
                self._index(self.url_import_jobs, 'idem_key', unique=True, background=True),
                self._index(self.url_import_jobs, [('sha256', 1), ('status', 1)], background=True),
                self._index(self.question_import_items, [('job_id', 1), ('classification', 1), ('row', 1)], background=True),
                self._index(self.question_import_items, [('job_id', 1), ('external_id', 1)], unique=True, background=True),
                self._index(self.question_migration_backups,
                    [('migration', 1), ('question_id', 1)], unique=True,
                    partialFilterExpression={'question_id': {'$type': 'string'}},
                    name='uq_qbank_migration_question', background=True),
                self._index(self.question_migration_backups,
                    [('migration', 1), ('progress_id', 1)], unique=True,
                    partialFilterExpression={'progress_id': {'$type': 'string'}},
                    name='uq_qbank_migration_progress', background=True),
                # 🍴 موج C2 — Fork/Override: یافتن fork یک base برای یک ورودی
                self._index(self.bs_sessions, [('fork_of', 1), ('intake', 1)], background=True),
                self._index(self.ref_books, [('fork_of', 1), ('intake', 1)], background=True),
                self._index(self.bs_lessons, [('intake', 1), ('term', 1), ('order', 1)], background=True),
                self._index(self.ref_subjects, [('intake', 1), ('order', 1)], background=True),
                self._index(self.bs_lessons, [('term', 1), ('order', 1)], background=True),
                self._index(self.bs_sessions, [('lesson_id', 1), ('number', 1)], background=True),
                # 🌊 موج C3 — «فرزند ورودی‌خاص»: یکتایی/پیدا کردن جلسه داخل یک سطل
                # (lesson_id, number, intake). عمداً غیر-yکتایی: داده‌ی legacy
                # بدون فیلد intake دارد و یک unique جدید روی همان کلید، درج‌های
                # قدیمیِ 🎓 را می‌شکست (§۱۳ گزارش). enforce در bs_add_session.
                self._index(self.bs_sessions,
                    [('lesson_id', 1), ('intake', 1), ('number', 1)], background=True),
                self._index(self.bs_content, [('session_id', 1), ('order', 1)], background=True),
                self._index(self.ref_subjects, 'order', background=True),
                self._index(self.ref_books, [('subject_id', 1), ('order', 1)], background=True),
                self._index(self.ref_files, [('book_id', 1), ('lang', 1), ('volume', 1)], background=True),
                self._index(self.schedules, [('date', 1), ('type', 1)], background=True),
                self._index(self.schedule_templates, [('weekday', 1), ('group', 1)], background=True),
                self._index(self.schedule_templates, [('group', 1), ('weekday', 1), ('time', 1)], background=True),
                self._index(self.stats_col, [('user_id', 1), ('timestamp', -1)], background=True),
                self._index(self.tickets, 'ticket_id', unique=True, background=True),
                self._index(self.tickets, [('user_id', 1), ('status', 1)], background=True),
                self._index(self.tickets, [('status', 1), ('created_at', -1)], background=True),
                self._index(self.tickets, [('priority', 1), ('created_at', -1)], background=True),
                self._index(self.tickets, [('assignee_id', 1), ('status', 1), ('created_at', -1)], background=True),
                self._index(self.audit_logs, [('timestamp', -1)], background=True),
                self._index(self.audit_logs, [('category', 1), ('severity', 1), ('timestamp', -1)], background=True),
                self._index(self.audit_logs, [('module', 1), ('timestamp', -1)], background=True),
                self._index(self.audit_logs, [('actor.id', 1), ('timestamp', -1)], background=True),
                self._index(self.audit_logs, [('correlation_id', 1), ('timestamp', 1)], background=True),
                self._index(self.audit_logs, [('target.type', 1), ('target.id', 1), ('timestamp', -1)], background=True),
                # 🚀 Audit Refactor — ایندکس‌های جدید برای Observability (§38)
                self._index(self.audit_logs, [('event_id', 1)], unique=True, sparse=True, background=True),
                self._index(self.audit_logs, [('severity', 1), ('timestamp', -1)], background=True),
                self._index(self.audit_logs, [('action', 1), ('timestamp', -1)], background=True),
                self._index(self.audit_logs, [('request_id', 1)], background=True),
                self._index(self.audit_logs, [('telegram_delivery_status', 1), ('timestamp', -1)], background=True),
                # Outbox indexes (§14, §44 — Race prevention + Retry)
                self._index(self.audit_outbox, [('status', 1), ('next_retry_at', 1)], background=True),
                self._index(self.audit_outbox, [('event_id', 1)], unique=True, background=True),
                self._index(self.audit_outbox, [('correlation_id', 1)], background=True),
                self._index(self.audit_outbox, [('created_at', -1)], background=True),
                self._index(self.grades, [('student_id', 1), ('created_at', -1)], background=True),
                self._index(self.grades, [('lesson', 1), ('created_at', -1)], background=True),
                self._index(self.grades, [('exam_date', -1), ('lesson', 1)], background=True),
                # 🛡 AUDIT-§۸۲ — فهرست/فیلتر ترم‌به‌ترمِ نمرات
                self._index(self.grades, [('student_id', 1), ('term', 1), ('exam_date', -1)], background=True),
                self._index(self.grades, [('term', 1), ('created_at', -1)], background=True),
                self._index(self.wa_saved_filters, [('scope', 1), ('shared', 1), ('updated_at', -1)], background=True),
                self._index(self.wa_saved_filters, [('owner', 1), ('updated_at', -1)], background=True),
                self._index(self.web_admin_sessions, [('uid', 1), ('revoked', 1), ('created_at', -1)], background=True),
                self._index(self.web_admin_sessions, [('expires_at', 1)], expireAfterSeconds=0, background=True),
                self._index(self.admin_op_locks, [('expires_at', 1)], expireAfterSeconds=0, background=True),
                self._index(self.web_admin_otps, [('uid', 1)], background=True),
                self._index(self.web_admin_otps, [('expires_at', 1)], expireAfterSeconds=0, background=True),
                self._index(self.wa_api_metrics, [('at', 1)], expireAfterSeconds=2592000, background=True),
                # 🌊 W5/REL-03 — خطاهای گزارش‌شده‌ی کلاینت (TTL ۳۰ روزه)
                self._index(self.client_errors, [('at', 1)], expireAfterSeconds=2592000, background=True),
                self._index(self.client_errors, [('message', 1), ('at', -1)], background=True),
                # 🌊 W7 — مصرف سهمیه (TTL ۴۵ روزه) و ایونت‌های فیچر (TTL ۳۰ روزه)
                self._index(self.feature_usage, [('updated_at', 1)], expireAfterSeconds=3888000, background=True),
                self._index(self.feature_events, [('at', 1)], expireAfterSeconds=2592000, background=True),
                self._index(self.feature_events, [('feature', 1), ('at', -1)], background=True),
                self._index(self.family_invites, [('owner_id', 1)], background=True),  # 🌊 W8
                self._index(self.wa_api_metrics, [('route', 1), ('at', -1)], background=True),
                self._index(self.wa_api_metrics, [('status', 1), ('at', -1)], background=True),
                self._index(self.broadcast_campaigns, [('created_at', -1)], background=True),
                self._index(self.broadcast_campaigns, [('status', 1), ('send_at', 1)], background=True),
                self._index(self.bot_notifs, [('campaign_id', 1), ('sent', 1)], background=True),
                self._index(self.bot_notifs, [('sent', 1), ('send_at', 1)], background=True),
                # 💀 DLQ — بدون این، هم شمارش پیام‌های مرده در Job Center و هم
                # فهرست صفحه‌بندی‌شده‌ی DLQ روی کل کالکشن اسکن می‌کنند.
                # sent_at نزولی چون فهرست همیشه «تازه‌ترین مرگ» را اول می‌خواهد.
                self._index(self.bot_notifs, [('status', 1), ('sent_at', -1)], background=True),
                self._index(self.intakes, 'code', unique=True, background=True),
                # 🏷 Identity v1 — یکتایی لقب case-insensitive:
                # unique + sparse (فقط اسنادی که فیلد دارند/غیرnull)
                self._index(self.users, 'nickname_normalized', unique=True, sparse=True, background=True),
                # 🚀 موج ۴.۶۰ — پوشش کوئری‌های داغ پنل اشتراک:
                # فیلتر status + مرتب‌سازی submitted_at/end_date و
                # تاریخچه‌ی پرداخت هر کاربر. بدون این‌ها = Full
                # Collection Scan + SORT در حافظه در هر درخواست پنل.
                self._index(self.sub_payments, [('status', 1), ('submitted_at', -1)], background=True),
                self._index(self.sub_payments, [('user_id', 1), ('submitted_at', -1)], background=True),
                # 🌊 GIFT — query shapeهای واقعی: تاریخچه‌ی گیرنده (gift.to)
                # و لیست ادمین (gift.to+status)؛ idem_key یکتا و sparse برای
                # idempotency ساخت هدیه.
                self._index(self.sub_payments, [('gift.to', 1), ('status', 1)], background=True),
                self._index(self.sub_payments, 'idem_key', unique=True, sparse=True, background=True),
                # 🌊 W2 — زرین‌پال authority یکتا (sparse)
                self._index(self.sub_payments, 'zarinpal_authority', unique=True, sparse=True, background=True),
                self._index(self.subscriptions, [('status', 1), ('end_date', 1)], background=True),
                # 🛡 AUDIT-A5/P-9 — آدرس تیکت یکتا باشد و جست‌وجوی نام ایندکس
                self._index(self.tickets, [('user_name', 1), ('created_at', -1)], background=True),
                self._index(self.tickets, [('user_id', 1), ('created_at', -1)], background=True),
                self._index(self.subscriptions, [('user_id', 1), ('status', 1)], background=True),
                # 🔔 موج ۴.۹۰ — کوئری داغ صندوق اعلان: فهرست کاربر به
                # ترتیب زمان + شمارش خوانده‌نشده‌ها
                self._index(self.user_notifs, [('user_id', 1), ('created_at', -1)], background=True),
                self._index(self.user_notifs, [('user_id', 1), ('read', 1)], background=True),
                # 👑 موج P0 Prestige — قانون یک‌بارهرسؤال + بردها/رقیب + سفر/فید
                self._index(self.answers, [('user_id', 1), ('question_id', 1)], background=True),
                self._index(self.answers, [('user_id', 1), ('answered_at', 1)], background=True),
                self._index(self.users, [('approved', 1), ('effective_xp', -1)], background=True),
                self._index(self.users, [('approved', 1), ('intake', 1), ('effective_xp', -1)], background=True),
                self._index(self.users, [('approved', 1), ('group', 1), ('effective_xp', -1)], background=True),
                self._index(self.users, [('approved', 1), ('weekly_xp', -1)], background=True),
                self._index(self.prestige_history, [('uid', 1), ('at', -1)], background=True),
                self._index(self.prestige_history, [('at', -1)], background=True),
                self._index(self.prestige_history, [('type', 1), ('key', 1)], background=True),
                # 👑 موج P2 — ضدتکرار واکنش فید (هر کاربر یک واکنش per رویداد)
                self._index(self.feed_reactions, [('event_id', 1), ('uid', 1)], unique=True, background=True),
                self._index(self.feed_reactions, [('uid', 1)], background=True),
                # 👑 موج P1 — جست‌وجوی جلسه‌ی چالش فعال کاربر
                self._index(self.exam_sessions, 'session_id', unique=True, background=True),
                self._index(self.exam_sessions, [('user_id', 1), ('promotion', 1), ('status', 1)], background=True),
                self._index(self.exam_sessions, [('user_id', 1), ('status', 1), ('started_at', -1)], background=True),
                self._index(self.exam_sessions, [('output_mode', 1), ('created_at', -1)], background=True),
                self._index(self.exam_sessions, [('status', 1), ('deadline_ts', 1)], background=True),
                # 🌊 W3 — TTL برای جلسات منقضی (7 روز پس از expires_at) — auto cleanup بدون job
                self._index(self.exam_sessions, [('expires_at', 1)], expireAfterSeconds=0, background=True),
                # 🌊 W4 — text index برای جستجوی سراسری فارسی (global_search) — بدون COLLSCAN
                self._index(self.questions, [('question', 'text'), ('lesson', 'text'), ('topic', 'text')], background=True, name='txt_questions_search'),
                self._index(self.bs_content, [('description', 'text')], background=True, name='txt_bs_content_search'),
                self._index(self.ref_files, [('description', 'text')], background=True, name='txt_ref_files_search'),
                self._index(self.faq, [('question', 'text'), ('answer', 'text')], background=True, name='txt_faq_search'),
                self._index(self.question_pdf_generations, [('session_id', 1), ('generated_at', -1)], background=True),
                self._index(self.question_pdf_generations, [('user_id', 1), ('generated_at', -1)], background=True),
                # 🎟 موج D1 — یک مصرف از هر کد توسط هر کاربر (ضدتکرار اتمیک)
                self._index(self.discount_uses, [('code', 1), ('user_id', 1)], unique=True, background=True),
                # 🛡 W1 — کد تخفیف یکتاست: ضدتکرار اتمیک در ساخت (race-safe) + کوئری داغ discount_validate
                self._index(self.discount_codes, [('code', 1)], unique=True, background=True),
                self._index(self.discount_bcasts, [('code', 1), ('created_at', -1)], background=True),
                # 💰 W6 — کیف پول: هر کاربر یک wallet؛ کلید یکتای تراکنش =
                # idempotency مالی (دو اثر اقتصادی برای یک مرجع ممنوع)؛
                # ایندکس‌ها دقیقاً شکل کوئری‌های داغ wallet_tx_list/summary را دارند
                self._index(self.wallets, 'user_id', unique=True, background=True),
                self._index(self.wallet_transactions,
                            [('reference_type', 1), ('reference_id', 1)],
                            unique=True, background=True),
                self._index(self.wallet_transactions,
                            [('user_id', 1), ('created_at', -1)], background=True),
                self._index(self.wallet_transactions,
                            [('status', 1), ('created_at', -1)], background=True),
                # 🛡 W1 — nonce یک‌بارمصرف initData (TTL خودکار پاک‌سازی)
                self._index(self.init_nonces, [('at', 1)], expireAfterSeconds=3600, background=True),
                # 🗄 W4/DB-04 — کالکشن‌های بدون ایندکس (پوشش کوئری داغ):
                # فهرست گفت‌وگوهای هر کاربر؛ تله‌متری jobها؛ آمار نقش‌ها (multikey).
                # عمداً بدون ایندکس مانده‌اند (تک‌سند/tiny یا _idمحور):
                # settings، settings_meta، perm_catalog، roles، migrations،
                # db_counters، sub_plans، blacklist، admin_roles، audit_delivery_metrics.
                self._index(self.ai_conversations,
                            [('user_id', 1), ('updated_at', -1)], background=True),
                self._index(self.notif_runs,
                            [('job_name', 1), ('started_at', -1)], background=True),
                self._index(self.user_roles,
                            [('roles', 1)], background=True),
                # 🌱 W13 — ریفرال: کوئری‌های داغ attribution/فهرست/آمار
                self._index(self.referrals,
                            [('invitee_id', 1)], unique=True, background=True),
                self._index(self.referrals,
                            [('inviter_id', 1), ('status', 1),
                             ('created_at', -1)], background=True),
                self._index(self.referrals,
                            [('ref_code', 1)], unique=True, background=True),
                self._index(self.referrals,
                            [('status', 1), ('created_at', -1)],
                            background=True),
                # 💳 W14 — پیگیری پرداخت: انتخاب pendingهای تازه
                self._index(self.sub_payments,
                            [('status', 1), ('created_at', -1)],
                            background=True),
            ]
            coros = [
                collection.create_index(*keys, **options)
                for collection, keys, options in index_specs
            ]
            results = await asyncio.gather(*coros, return_exceptions=True)
            failures = [(i, r) for i, r in enumerate(results) if isinstance(r, BaseException)]
            created = len(coros) - len(failures)
            critical_missing = []
            for idx, err in failures:
                collection, keys, options = index_specs[idx]
                label = f"{collection.name}:{keys}"
                # unique and TTL indexes protect an invariant or cleanup
                # contract, so their failure makes readiness degraded.
                is_critical = bool(options.get('unique') or
                                    'expireAfterSeconds' in options)
                msg = f"{type(err).__name__}: {err}"
                if is_critical:
                    logger.error(f"❌ CRITICAL index build failed [{label}] → {msg[:240]}")
                    critical_missing.append({'index': label, 'error': msg[:200]})
                else:
                    logger.warning(f"⚠️ index build failed [{label}] → {msg[:240]}")
            try:
                await self.set_setting('index_status', {
                    'created': created, 'failed': len(failures),
                    'critical_missing': critical_missing, 'at': utc_now_iso()})
            except Exception:
                pass                     # 🛡 گزارش‌دهی هرگز boot را نمی‌شکند
            if critical_missing:
                logger.error(
                    f"🛑 {len(critical_missing)} ایندکس بحرانی (unique) ساخته نشد ⇒ "
                    "یکتایی‌ها در سطح Mongo enforce نمی‌شوند؛ داده‌ی تکراری legacy را "
                    "ترمیم کنید (جزئیات: setting/index_status)")
            else:
                logger.info(f"✅ indexes: created={created} failed={len(failures)}")

            index_result = {
                'ready': not bool(critical_missing),
                'created': created,
                'failed': len(failures),
                'critical_missing': critical_missing,
            }
            # 🌊 W3 — versioned migrations (exam_sessions expires_at backfill etc)
            try:
                from db.migrations import run_migrations
                await run_migrations(self)
            except Exception as _mig_e:
                logger.warning(f"migration warning: {_mig_e}")
            try:
                await self.discount_codes.update_many(
                    {'target_plan_ids': {'$exists': False}},
                    {'$set': {'target_plan_ids': []}})
                await self.discount_codes.update_many(
                    {'per_user_limit': {'$exists': False}},
                    {'$set': {'per_user_limit': 0}})
                # Full-System Evolution: legacy ISO expiry strings become BSON
                # dates so TTL indexes can physically remove stale auth data.
                for auth_collection in (self.web_admin_otps, self.web_admin_sessions):
                    await auth_collection.update_many(
                        {'expires_at': {'$type': 'string'}},
                        [{'$set': {'expires_at': {'$convert': {
                            'input': '$expires_at', 'to': 'date',
                            'onError': now_utc(), 'onNull': now_utc(),
                        }}}}],
                    )
            except Exception as _me:
                logger.warning(f"D1/auth migration warning: {_me}")
            return index_result
        except Exception as e:
            logger.warning(f"Index creation warning: {e}")
            return {'ready': False, 'created': 0, 'failed': -1,
                    'critical_missing': [{'index': 'ensure_indexes', 'error': str(e)[:200]}]}


    async def bootstrap_shared(self) -> dict:
        """Run the shared, idempotent startup contract for API and Bot.

        A short Mongo lease prevents both supervised processes from racing
        migrations. Individual migration methods are themselves rerunnable;
        the lease only coordinates the lifecycle and records observability.
        """
        from pymongo import ReturnDocument
        import uuid

        owner = f"{os.getpid()}:{uuid.uuid4().hex}"
        now = now_utc()
        lock = None
        # If Bot and API start together, wait briefly for the process that
        # already owns the lease instead of declaring readiness prematurely.
        for attempt in range(40):
            try:
                lock = await self.migrations.find_one_and_update(
                    {'_id': 'shared_bootstrap_lock', '$or': [
                        {'expires_at': {'$lte': now_utc()}},
                        {'expires_at': {'$exists': False}},
                    ]},
                    {'$set': {'owner': owner, 'expires_at': now_utc() + timedelta(seconds=120)}},
                    upsert=True, return_document=ReturnDocument.AFTER,
                )
            except Exception as exc:
                logger.warning('shared bootstrap lock attempt %s failed: %s', attempt + 1, exc)
                lock = None
            if lock and lock.get('owner') == owner:
                break
            try:
                status = await self.migrations.find_one({'_id': 'shared_bootstrap_status'})
            except Exception:
                status = None
            if status and status.get('ready'):
                return status
            if attempt < 39:
                await asyncio.sleep(0.25)
        if not lock or lock.get('owner') != owner:
            return {'ready': False, 'skipped': 'bootstrap lease unavailable'}

        steps = {}
        try:
            operations = [
                ('indexes', self.ensure_indexes),
                ('mark_legacy_reference_files', self.migrate_mark_existing_ref_files_notified),
                ('rbac_seed', self.ensure_rbac_seed),
                ('rbac_migrate', self.rbac_migrate_users),
                ('content_scope', self.migrate_content_intake_scope),
                ('file_naming', self.migrate_file_naming),
                ('grades_terms', self.grades_backfill_terms),
                ('ring', self.ring_bootstrap),
                ('faq_seed', self.seed_subscription_copyright_faqs),
            ]
            for name, operation in operations:
                try:
                    result = await operation()
                    step_ok = not (name == 'indexes' and isinstance(result, dict)
                                   and result.get('ready') is False)
                    steps[name] = {'ok': step_ok, 'result': result}
                except Exception as exc:
                    logger.exception('shared bootstrap step failed: %s', name)
                    steps[name] = {'ok': False, 'error': f'{type(exc).__name__}: {str(exc)[:180]}'}
            ready = all(item.get('ok') for item in steps.values())
            status = {'ready': ready, 'steps': steps, 'at': utc_now_iso(), 'owner': owner}
            await self.migrations.update_one(
                {'_id': 'shared_bootstrap_status'}, {'$set': status}, upsert=True)
            return status
        finally:
            try:
                await self.migrations.update_one(
                    {'_id': 'shared_bootstrap_lock', 'owner': owner},
                    {'$set': {'expires_at': now_utc()}})
            except Exception:
                logger.exception('shared bootstrap lock release failed')


    # ══════════════════════════════════════════════════
    #  قرارداد مرکزی گروه درسی
    # ══════════════════════════════════════════════════

    @staticmethod
    def normalize_group(value) -> str:
        """تمام نمایش‌های legacy را به مقدار ذخیره‌سازی canonical تبدیل می‌کند.

        قرارداد پایدار پروژه برای گروه‌های دانشجویی ``1`` و ``2`` است.
        «الف/ب» فقط alias نمایشی قدیمی محسوب می‌شود؛ مقدار ناشناخته برای
        سازگاری عقب‌رو دست‌نخورده می‌ماند.
        """
        raw = str(value or "").strip()
        aliases = {
            "۱": "1", "الف": "1", "گروه ۱": "1", "گروه 1": "1",
            "۲": "2", "ب": "2", "گروه ۲": "2", "گروه 2": "2",
            "هردو": "هر دو", "all": "هر دو",
        }
        return aliases.get(raw, raw)

    @classmethod
    def group_aliases(cls, value) -> list:
        """مقادیر هم‌معنا برای خواندن اسناد legacy بدون مهاجرت مخرب."""
        canonical = cls.normalize_group(value)
        if canonical == "1":
            return ["1", "۱", "الف", "گروه 1", "گروه ۱"]
        if canonical == "2":
            return ["2", "۲", "ب", "گروه 2", "گروه ۲"]
        return [canonical] if canonical else []


    # ══════════════════════════════════════════════════
    #  کاربران
    # ══════════════════════════════════════════════════

    async def get_user(self, uid: int, *, use_cache: bool = True):
        # 🚀 PERF-O5: 5s LRU cache — caller can bypass with use_cache=False for fresh read after write
        import time as _t
        if use_cache:
            try:
                cached, at = self._user_cache.get(int(uid), (None, 0))
                if cached is not None and (_t.monotonic() - at) < self._user_cache_ttl:
                    return dict(cached)  # copy to prevent mutation leak
            except: pass
        doc = await self.users.find_one({'user_id': int(uid)})
        if doc is not None and use_cache:
            try:
                # LRU eviction: drop oldest if over max
                if len(self._user_cache) >= self._user_cache_max:
                    oldest = min(self._user_cache.items(), key=lambda kv: kv[1][1])[0]
                    self._user_cache.pop(oldest, None)
                self._user_cache[int(uid)] = (dict(doc), _t.monotonic())
            except: pass
        return doc


    async def get_users_by_ids(self, uids: list) -> dict:
        """🗄 W4/PERF-01 — خواندن بچ کاربران با یک کوئری ($in) برای عملیات
        گروهی؛ کش ۵ ثانیه‌ای get_user دور زده می‌شود (خوانش تازه)."""
        ids = []
        for u in (uids or []):
            try:
                ids.append(int(u))
            except (TypeError, ValueError):
                continue
        if not ids:
            return {}
        out = {}
        async for doc in self.users.find({'user_id': {'$in': ids}}):
            try:
                out[int(doc.get('user_id'))] = doc
            except (TypeError, ValueError):
                continue
        return out


    async def create_user(self, uid: int, name: str, student_id: str,
                          group: str, username: str = None, intake: str = ''):
        # FIX طبق سند: مقادیر پیش‌فرض اعلان‌ها از تنظیمات پنل ادمین
        # خوانده می‌شود — قبلاً هاردکد بود و فقط ۴ نوع را داشت
        notif_defaults = await self.get_notif_defaults()
        await self.users.insert_one({
            'user_id':    uid,
            'name':       name,
            'student_id': student_id,
            'group':      group,
            'username':   username,
            'intake':     intake or '',
            'registered_at': utc_now_iso(),
            'approved':   False,
            'role':       'student',
            'notification_settings': dict(notif_defaults),
            'total_answers':   0,
            'correct_answers': 0,
            'weak_topics':     [],
            # 👑 Prestige — پیش‌فرض‌های کامل برای کاربران جدید (کهنه‌ها مهاجرت نرم)
            'prestige_xp': 0, 'decay_penalty': 0, 'decay_blocks': 0,
            'rank_floor_xp': 0, 'effective_xp': 0, 'season_xp': 0,
            'season_key': 'S1-1405',
            'weekly_xp': 0, 'weekly_reset': '', 'monthly_xp': 0, 'monthly_reset': '',
            'ai_conv_days': [], 'submissions_approved': 0, 'reports_resolved': 0,
            'challenge': {'target_rank': '', 'cooldown_until': '',
                          'last_fail_at': '', 'apex': False},
            'last_gain_at': '', 'last_active_day': '', 'shield_answers': 0, 'shield_until': '',
            'daily_xp': {'date': '', 'amount': 0, 'correct': 0},
            'streak_current': 0, 'streak_best': 0,
            'exams_completed': 0, 'downloads_count': 0,
            'records': {'best_acc': 0, 'best_exam_pct': 0, 'top_rank_key': 'rookie',
                        'top_rank_at': '', 'top_div': 3,
                        'top1_weeks_current': 0, 'top1_weeks_best': 0},
            'achievements': {}, 'privacy_public': True, 'showcase': [],
            'prestige_migrated': True,   # کاربر تازه نیازی به Backfill ندارد
        })


    async def update_user(self, uid: int, data: dict):
        await self.users.update_one({'user_id': int(uid)}, {'$set': data})
        # invalidate user cache (subscription/role changes must be immediate)
        try:
            self._user_cache.pop(int(uid), None)
        except: pass
        # also bust settings cache if somehow user doc affects it (no-op)


    async def delete_user(self, uid: int) -> dict:
        """Idempotent account erasure with explicit retention policy.

        Operational/session/learning data is removed. Support, audit and
        financial records are retained but anonymised so accounting and
        compliance history remain reconstructable without retaining PII.
        Re-running the method is safe after a partial cleanup.
        """
        uid = int(uid)
        deleted = {}

        # Authentication, roles, inbox and ephemeral AI state.
        delete_specs = [
            ('web_admin_sessions', {'uid': uid}),
            ('web_admin_otps', {'uid': uid}),
            ('admin_roles', {'_id': uid}),
            ('user_roles', {'_id': uid}),
            ('user_notifs', {'user_id': uid}),
            ('bot_notifs', {'$or': [{'chat_id': uid}, {'user_id': uid}],
                             'type': {'$ne': 'user_deleted'}}),
            ('answers', {'user_id': uid}),
            ('stats_col', {'user_id': uid}),
            ('question_progress', {'user_id': uid}),
            ('question_topic_stats', {'user_id': uid}),
            ('ai_practice_questions', {'user_id': uid}),
            ('question_ai_quotas', {'user_id': uid}),
            ('question_pdf_generations', {'user_id': uid}),
            ('exam_sessions', {'user_id': uid}),
            ('ai_conversations', {'user_id': uid}),
            ('prestige_history', {'uid': uid}),
            ('feed_reactions', {'uid': uid}),
            ('discount_uses', {'user_id': uid}),
        ]
        for attr, query in delete_specs:
            collection = getattr(self, attr, None)
            if collection is None:
                continue
            result = await collection.delete_many(query)
            deleted[attr] = int(getattr(result, 'deleted_count', 0) or 0)

        # User-owned uploads stay available to the content domain, but the
        # uploader is no longer identifiable.
        if getattr(self, 'qbank_files', None) is not None:
            await self.qbank_files.update_many(
                {'uploaded_by': uid},
                {'$set': {'uploaded_by': 0, 'uploader_deleted': True}})

        # Support, moderation, audit and finance are retained with a stable
        # tombstone instead of being hard-deleted.
        tombstone = 'کاربر حذف‌شده'
        for attr, query, update in [
            ('tickets', {'user_id': uid},
             {'$set': {'user_id': 0, 'user_name': tombstone, 'user_deleted': True}}),
            ('content_reports', {'reporter_id': uid},
             {'$set': {'reporter_id': 0, 'reporter_name': tombstone, 'reporter_deleted': True}}),
            ('ai_reports', {'user_id': uid},
             {'$set': {'user_id': 0, 'user_name': tombstone, 'user_deleted': True}}),
            ('subscriptions', {'user_id': uid},
             {'$set': {'user_name': tombstone, 'user_deleted': True}}),
            ('sub_payments', {'user_id': uid},
             {'$set': {'user_name': tombstone, 'user_deleted': True}}),
        ]:
            collection = getattr(self, attr, None)
            if collection is not None:
                result = await collection.update_many(query, update)
                deleted[f'{attr}_anonymized'] = int(getattr(result, 'modified_count', 0) or 0)

        # Audit IDs remain as stable references, while names/roles/labels no
        # longer expose the erased account. Financial IDs above remain intact.
        await self.audit_logs.update_many(
            {'actor.id': uid},
            {'$set': {'actor.name': tombstone, 'actor.role': 'deleted_user'}})
        await self.audit_logs.update_many(
            {'target.id': str(uid)},
            {'$set': {'target.label': tombstone}})

        try:
            deleted['ring'] = await self.ring_profile_delete(uid)
        except Exception:
            logger.exception('Ring account cleanup failed for %s', uid)
            deleted['ring'] = {'error': True}

        result = await self.users.delete_one({'user_id': uid})
        deleted['users'] = int(getattr(result, 'deleted_count', 0) or 0)
        return deleted


    async def block_user(self, uid: int, reason: str = '', blocked_by: int = None,
                          blocked_by_name: str = '') -> None:
        """
        FIX جدید — بلاک کامل: برخلاف delete_user که فقط رکورد را پاک
        می‌کند و کاربر می‌تواند فردا دوباره با همان آیدی ثبت‌نام کند،
        این متد هم حذف می‌کند و هم آیدی عددی تلگرام (ثابت، برخلاف
        یوزرنیم) را در بلک‌لیست ثبت می‌کند تا ثبت‌نام مجدد مسدود شود.
        """
        await self.users.delete_one({'user_id': uid})
        await self.blacklist.update_one(
            {'_id': uid},
            {'$set': {
                'blocked_at':      utc_now_iso(),
                'blocked_by':      blocked_by,
                'blocked_by_name': blocked_by_name,
                'reason':          reason,
            }},
            upsert=True,
        )


    async def unblock_user(self, uid: int) -> bool:
        r = await self.blacklist.delete_one({'_id': uid})
        return r.deleted_count > 0


    async def is_blacklisted(self, uid: int) -> bool:
        return await self.blacklist.find_one({'_id': uid}) is not None


    async def get_blacklist(self, limit: int = 200) -> list:
        return await self.blacklist.find({}).sort('blocked_at', -1).to_list(limit)


    async def all_users(self, approved_only: bool = True):
        q = {'approved': True} if approved_only else {}
        # 🐛 قبلاً to_list(5000) بود: یعنی از کاربر شماره‌ی ۵۰۰۱ به بعد
        # اصلاً در broadcast/آمار/فیلترها دیده نمی‌شد (نه ارور، نه لاگ —
        # فقط سکوت). با to_list(length=None) درایور Motor همه‌ی نتایج را
        # صرف‌نظر از تعدادشان برمی‌گرداند.
        return await self.users.find(q).sort('registered_at', -1).to_list(length=None)


    async def pending_users(self):
        return await self.users.find({'approved': False}).to_list(100)


    async def notif_users(self, ntype: str, group: str = None):
        """
        🐛 باگ واقعی که اینجا بود: این متد گروه (۱/۲/هر دو) را اصلاً در
        نظر نمی‌گرفت — یعنی وقتی برنامه‌ی یک کلاس فقط برای «گروه ۱»
        بود و ادمین زمانش را تغییر می‌داد، اعلان به «همه‌ی» کاربرانی
        که نوتیف مربوطه را روشن داشتند فرستاده می‌شد؛ گروه ۲ هم پیام
        نامربوط به کلاسشان را دریافت می‌کرد. حالا پارامتر اختیاری
        group اضافه شده: اگر مقداری غیر از None/'' /'هر دو' بدهی، فقط
        همان گروه فیلتر می‌شود؛ در غیر این صورت رفتار قبلی (همه) حفظ
        می‌شود — کاملاً backward-compatible.
        """
        # 🧠 N1.2 — گارد canonical: اگر کاربر کلید جدید یا قدیمی را خاموش
        # کرده باشد خارج می‌شود؛ سندهای کهنه (فقط کلید قدیمی) دقیقاً همان
        # رفتار دیروز را حفظ می‌کنند، کاربر تازه هم که خاموش کند اثر دارد.
        canon = self.PREF_ALIAS.get(ntype, ntype) or ntype
        query = {'approved': True,
                 f'notification_settings.{canon}': {'$ne': False},
                 f'notification_settings.{ntype}': {'$ne': False}}
        normalized_group = self.normalize_group(group)
        if normalized_group and normalized_group != 'هر دو':
            query['group'] = {'$in': self.group_aliases(normalized_group)}
        return await self.users.find(query).to_list(length=None)


    @staticmethod
    def build_user_search_query(query_text: str) -> dict:
        """
        🔎 قرارداد سراسری جست‌وجوی کاربر — «منبع واحد حقیقت».
        هر سه الگو با هم پشتیبانی می‌شوند:
          ۱) آیدی عددی تلگرام (مثلاً 123456789) — تطبیق دقیق، نه substring
          ۲) یوزرنیم، با یا بدون @ (مثلاً @ali_r یا ali_r)
          ۳) نام ثبت‌شده در ربات + شماره دانشجویی
        ربات (admin/ai_admin/subscription_admin/…)، پنل وب (مدیریت
        کاربران)، و پنل اشتراک (اعطای دستی/مشترکین/رسیدها) همه از
        همین سازنده استفاده می‌کنند تا رفتار جست‌وجو در کل سیستم
        یکپارچه بماند. خروجی خالی یعنی «بدون فیلتر».
        """
        import re
        raw = (query_text or '').strip()
        if not raw:
            return {}

        or_clauses = []

        # ۱) آیدی عددی تلگرام — تطبیق دقیق (نه substring)
        if raw.lstrip('+-').isdigit():
            try:
                or_clauses.append({'user_id': int(raw)})
            except (ValueError, OverflowError):
                pass

        # ۲) یوزرنیم — پشتیبانی از هر دو حالت با/بدون @
        uname = raw.lstrip('@').strip()
        if uname:
            or_clauses.append({'username': {'$regex': re.escape(uname), '$options': 'i'}})

        # ۳) اسم ثبت‌شده در ربات + شماره دانشجویی (مثل قبل)
        regex = {'$regex': re.escape(raw), '$options': 'i'}
        or_clauses.append({'name': regex})
        or_clauses.append({'student_id': regex})

        # ۴) 🏷 Identity v1 — جست‌وجو هم‌زمان روی لقب:
        # هم substring روی خود لقب، هم تطبیق case-insensitive روی
        # نرمال‌شده (برای پیدا‌کردن دقیق یک لقب)
        or_clauses.append({'nickname': regex})
        or_clauses.append({'nickname_normalized': {
            '$regex': re.escape(raw.lower()), '$options': 'i'}})

        return {'$or': or_clauses}


    async def search_users(self, query_text: str, limit: int = 20):
        """جست‌وجوی کاربر روی قرارداد مشترک build_user_search_query —
        FIX مهم تاریخی: قبلاً user_id عددی اصلاً توی کوئری نبود."""
        query = self.build_user_search_query(query_text)
        if not query:
            return []
        return await self.users.find(query).to_list(limit)


    # ══════════════════════════════════════════════════
    #  تیکت‌ها
    # ══════════════════════════════════════════════════

    async def _next_ticket_id(self) -> int:
        """🛡 AUDIT-A5 — شماره‌ی تیکت با شمارنده‌ی اتمیک.

        الگوی قبلی `count_documents({}) + 1` بود: دو تیکت هم‌زمان (دو کاربر،
        یا دوبار زدن دکمه‌ی ارسال) همان شماره را می‌گرفتند و چون همه‌ی
        آدرس‌دهی تیکت‌ها (مشاهده، پاسخ، دکمه‌ها) با `ticket_id` است، کاربر
        دوم روی تیکت کاربر اول می‌نوشت و هر دو یک گفت‌وگو را می‌دیدند.
        `$inc` روی سند شمارنده در `settings` همان ایدiomِ `_claim_global_first`
        است و `$max` (در گام جدا) یک‌بار شمارنده را با داده‌های قدیمی هم‌تراز
        می‌کند؛ `$inc` بعد از آن هرگز عدد تکراری تولید نمی‌کند.
        """
        from pymongo import ReturnDocument

        async def _bump() -> int:
            doc = await self.settings.find_one_and_update(
                {'_id': 'ticket_id_counter'}, {'$inc': {'v': 1}},
                upsert=True, return_document=ReturnDocument.AFTER)
            return int((doc or {}).get('v') or 0)

        nxt = await _bump()
        top = await self.tickets.find_one(
            sort=[('ticket_id', -1)], projection={'ticket_id': 1})
        seed = int((top or {}).get('ticket_id') or 0)
        if nxt <= seed:
            # شمارنده از داده‌های موجود عقب‌تر است (نصب تازه روی DB قدیمی،
            # بازیابی از بکاپ، یا حذف‌شدن سند شمارنده) ⇒ یک‌بار هم‌تراز با
            # $max (هرگز کم نمی‌کند) و بعد شماره‌ی تازه بگیر.
            await self.settings.update_one(
                {'_id': 'ticket_id_counter'}, {'$max': {'v': seed}}, upsert=True)
            nxt = await _bump()
        return nxt


    async def ticket_search_name(self, name: str, limit: int = 15) -> list:
        """🛡 AUDIT-P-9 — جست‌وجوی نام در خودِ Mongo (ایندکس‌شده) به‌جای
        فیلتر پایتونی روی ۱۰۰ تیکت آخر؛ قبلاً تیکت قدیمی‌تر «پیدا نشد» می‌داد."""
        term = re.escape(str(name or '').strip())
        if not term:
            return []
        return await self.tickets.find(
            {'user_name': {'$regex': term, '$options': 'i'}}
        ).sort('created_at', -1).to_list(limit)


    # 🌊 W8/UX-04 — SLA پیش‌فرض هر اولویت (ساعت)؛ قابل‌تنظیم از مرکز تنظیمات
    TICKET_SLA_DEFAULTS = {'low': 72, 'normal': 48, 'high': 24, 'urgent': 8}
    TICKET_PRIORITIES = ('low', 'normal', 'high', 'urgent')

    async def ticket_sla_hours(self, priority: str) -> int:
        try:
            v = await self.get_setting(f'ticket_sla_{priority}',
                                       self.TICKET_SLA_DEFAULTS.get(priority, 48))
            return max(0, int(v or 0))
        except Exception:
            return self.TICKET_SLA_DEFAULTS.get(priority, 48)

    @staticmethod
    def ticket_sla_info(t: dict) -> dict:
        """وضعیت SLA تیکت (first-response): {sla_hours, due_at, responded, breached}."""
        from time_utils import parse_machine_datetime, now_utc
        from datetime import timedelta
        sla = 0
        try:
            sla = max(0, int((t or {}).get('sla_hours') or 0))
        except (TypeError, ValueError):
            sla = 0
        responded = bool((t or {}).get('first_response_at'))
        due_at, breached = None, False
        if sla > 0 and not responded and (t or {}).get('status') != 'closed':
            try:
                due = parse_machine_datetime(t.get('created_at')) + timedelta(hours=sla)
                due_at = due.isoformat()
                breached = now_utc() > due
            except (ValueError, TypeError):
                pass
        return {'sla_hours': sla, 'due_at': due_at, 'responded': responded,
                'breached': breached}

    # 🌊 W9 — ورک‌فلو وضعیت تیکت (هسته‌ی خالص؛ ریس‌سیف با آپدیت شرطی)
    TICKET_STATUSES = ('open', 'in_progress', 'waiting_user',
                       'resolved', 'closed')
    # legacy: فیلتر قدیمی answered یعنی «پاسخ داده شده، منتظر کاربر»
    TICKET_STATUS_LEGACY = {'answered': 'waiting_user'}
    TICKET_TRANSITIONS = {
        'open': ('in_progress', 'resolved', 'closed'),
        'in_progress': ('open', 'waiting_user', 'resolved', 'closed'),
        'waiting_user': ('in_progress', 'resolved', 'closed'),
        'resolved': ('in_progress', 'closed'),
        'closed': ('in_progress',),
    }

    @staticmethod
    def ticket_norm_status(s) -> str:
        s = str(s or 'open').strip()
        s = DBCore.TICKET_STATUS_LEGACY.get(s, s)
        return s if s in DBCore.TICKET_STATUSES else 'open'

    @staticmethod
    def ticket_transition_allowed(frm, to) -> bool:
        frm = DBCore.ticket_norm_status(frm)
        to = DBCore.ticket_norm_status(to)
        if frm == to:
            return True  # no-op مجاز است
        return to in DBCore.TICKET_TRANSITIONS.get(frm, ())

    async def ticket_assignee_ok(self, uid) -> bool:
        """🌊 W9 — آیا assignee هنوز مجوز پاسخ‌گویی دارد؟
        رفتار امن: فقط flag برای نمایش؛ سلب خودکار ممنوع."""
        try:
            uid = int(uid or 0)
        except (TypeError, ValueError):
            return False
        if uid <= 0:
            return False
        try:
            u = await self.get_user(uid)
            if not u:
                return False
            return bool(await self.has_permission(uid, 'tickets.reply'))
        except Exception:
            return False

    async def ticket_set_status(self, ticket_id: int, to: str) -> dict:
        """تغییر وضعیت گاردشده: {'ok', 'frm', 'to'}؛ ریس ⇒ ok=False.

        آپدیت شرطی روی status موردانتظار + ۱ retry؛ اگر هم‌زمان عوض
        شده بود، به‌جای last-write-wins کور، ۴۰۹ منطقی برمی‌گردد.
        """
        to = self.ticket_norm_status(to)
        for _ in range(2):
            t = await self.ticket_get(ticket_id)
            if not t:
                return {'ok': False, 'frm': '', 'to': to,
                        'error': 'not_found'}
            frm = self.ticket_norm_status(t.get('status'))
            if frm == to:
                return {'ok': True, 'frm': frm, 'to': to,
                        'noop': True}
            if not self.ticket_transition_allowed(frm, to):
                return {'ok': False, 'frm': frm, 'to': to,
                        'error': 'invalid_transition'}
            ops = {'$set': {'status': to}}
            if to == 'closed':
                ops['$set']['closed_at'] = utc_now_iso()
            elif frm == 'closed':
                ops['$unset'] = {'closed_at': ''}
            r = await self.tickets.update_one(
                {'ticket_id': ticket_id, 'status': t.get('status')},
                ops)
            if r.matched_count:
                return {'ok': True, 'frm': frm, 'to': to}
        cur = await self.ticket_get(ticket_id) or {}
        return {'ok': False,
                'frm': self.ticket_norm_status(cur.get('status')),
                'to': to, 'error': 'race'}

    async def ticket_create(self, uid: int, name: str, subject: str,
                            message: str, priority: str = 'normal') -> int:
        tid = await self._next_ticket_id()
        prio = priority if priority in self.TICKET_PRIORITIES else 'normal'
        await self.tickets.insert_one({
            'ticket_id': tid, 'user_id': uid, 'user_name': name,
            'subject': subject, 'message': message, 'status': 'open',
            'created_at': utc_now_iso(), 'replies': [],
            # 🌊 W8/UX-04 — اولویت + SLA (legacyها فاقدند ⇒ عادی/بدون SLA)
            'priority': prio, 'sla_hours': await self.ticket_sla_hours(prio),
            'assignee_id': None, 'assignee_name': '',
            'first_response_at': None, 'stale_nudged_at': None,
        })
        return tid


    async def ticket_get(self, ticket_id: int):
        return await self.tickets.find_one({'ticket_id': ticket_id})


    async def ticket_get_all(self, status: str = None):
        # 🌊 W9 — «باز» یعنی نیازمند توجه (غیربسته)؛ بقیه exact-match
        if status == 'open':
            q = {'status': {'$ne': 'closed'}}
        else:
            q = {'status': status} if status else {}
        return await self.tickets.find(q).sort('created_at', -1).to_list(100)


    async def ticket_list_for_user(self, uid: int, limit: int = 10) -> list:
        """⚠️ قابلیتِ جدید: تیکت‌های خودِ همین کاربر — برای get_my_tickets."""
        return await self.tickets.find({'user_id': uid}).sort('created_at', -1).to_list(limit)


    async def ticket_get_user(self, uid: int):
        return await self.tickets.find({'user_id': uid}).sort('created_at', -1).to_list(20)


    # 🛡 AUDIT-V3 — کرانه‌ی آرایه‌های درون‌سندی (سقف ۱۶ مگابایت Mongo).
    TICKET_INLINE_CAP = 400          # پاسخِ درون‌خطی هر تیکت
    NOTE_INLINE_CAP   = 200          # یادداشت داخلی هر تیکت
    ARCHIVE_COL       = 'ticket_overflow'
    ARCHIVE_BATCH     = 500          # 🛡 حداکثر آیتم در هر سندِ آرشیو

    async def _push_capped(self, col, query, field, item, cap, *, archive_kind=None):
        """$push با کرانه؛ هر چه از کرانه رد شود **گم نمی‌شود**.

        اگر طول آرایه به cap برسد، آیتم‌های قدیمی‌تر پیش از `$slice` به
        کالکشن `ticket_overflow` منتقل می‌شوند (یک سند به‌ازای هر دسته).
        خواننده‌های موجود بدون تغییر کار می‌کنند: آرایه‌ی درون‌خطی همیشه
        «تازه‌ترین پنجره» را دارد و آرشیو فقط برای بازیابی سابقه لازم است.
        """
        doc = await getattr(self, col).find_one(query, {field: 1})
        arr = (doc or {}).get(field) or []
        ops = {'$push': {field: {'$each': [item], '$slice': -cap}}}
        if len(arr) >= cap and archive_kind:
            overflow = arr[:max(1, len(arr) - cap + 1)]
            # 🛡 سند آرشیو هم کرانه دارد: دسته‌های ARCHIVE_BATCH تایی با
            # شمارنده‌ی seq — وگرنه مشکل فقط از tickets به ticket_overflow
            # منتقل می‌شد و همان سقف ۱۶ مگابایت را می‌خورد.
            batch = max(10, int(self.ARCHIVE_BATCH))
            _rows = await self.ticket_overflow.find(
                {'ticket_ref': query.get('ticket_id'), 'kind': archive_kind},
                {'seq': 1, 'items': 1}).sort('seq', -1).limit(1).to_list(1)
            prev = _rows[0] if _rows else {}        # 🛡 find_one کرسر نمی‌دهد
            have = len(prev.get('items') or [])
            seq = int(prev.get('seq') or 0)
            if have + len(overflow) > batch:
                seq += 1
                have = 0
            await self.ticket_overflow.update_one(
                {'ticket_ref': query.get('ticket_id'), 'kind': archive_kind, 'seq': seq},
                {'$push': {'items': {'$each': overflow}},
                 '$set': {'at': utc_now_iso(), 'field': field},
                 '$inc': {'count': len(overflow)}},
                upsert=True)
            ops['$inc'] = {field + '_archived': len(overflow)}
        await getattr(self, col).update_one(query, ops)

    async def ticket_archived_replies(self, ticket_id: int) -> list:
        """سابقه‌ی بایگانی‌شده‌ی پاسخ‌ها (برای نمایش در پنل/مینی‌اپ)."""
        try:
            rows = await self.ticket_overflow.find(
                {'ticket_ref': ticket_id, 'kind': 'replies'},
                {'items': 1}).sort('seq', 1).to_list(200)
        except Exception:
            return []
        out = []
        for r in rows or []:
            out.extend(r.get('items') or [])
        return out

    async def ticket_add_reply(self, ticket_id: int, reply_text: str) -> dict:
        t = await self.ticket_get(ticket_id)
        frm = self.ticket_norm_status((t or {}).get('status'))
        await self._push_capped(
            'tickets', {'ticket_id': ticket_id}, 'replies',
            {'text': reply_text, 'at': utc_now_iso()}, self.TICKET_INLINE_CAP,
            archive_kind='replies')
        now = utc_now_iso()
        await self.tickets.update_one(
            {'ticket_id': ticket_id},
            {'$set': {'last_reply_at': now}}
        )
        # 🌊 W9 — گذار خودکار وضعیت (best-effort؛ خطا هرگز reply را خراب نمی‌کند)
        to = frm
        try:
            if str(reply_text or '').startswith('[دانشجو]'):
                if frm in ('waiting_user', 'resolved'):
                    to = 'in_progress'
            elif frm in ('open', 'in_progress'):
                to = 'waiting_user'
            elif frm == 'resolved':
                to = 'waiting_user'
            if to != frm and self.ticket_transition_allowed(frm, to):
                await self.tickets.update_one(
                    {'ticket_id': ticket_id, 'status': (t or {}).get('status')},
                    {'$set': {'status': to}})
            else:
                to = frm
        except Exception:
            to = frm
        # 🌊 W8/UX-04 — اولین پاسخ پشتیبانی (هر ۳ مسیر: ربات/API/وب) ساعت SLA را می‌بندد
        if not str(reply_text or '').startswith('[دانشجو]'):
            await self.tickets.update_one(
                {'ticket_id': ticket_id,
                 '$or': [{'first_response_at': None},
                         {'first_response_at': {'$exists': False}}]},
                {'$set': {'first_response_at': now}})
        return {'status_from': frm, 'status_to': to}


    async def ticket_reply(self, ticket_id: int, reply: str):
        await self.ticket_add_reply(ticket_id, reply)


    async def ticket_close(self, ticket_id: int) -> dict:
        # 🌊 W9 — بستن گاردشده (از هر وضعیت غیربسته)
        return await self.ticket_set_status(ticket_id, 'closed')


    async def ticket_reopen(self, ticket_id: int) -> dict:
        """
        FIX جدید طبق سند: بازگشایی تیکت — قبلاً این قابلیت اصلاً
        وجود نداشت و دانشجو مجبور بود تیکت جدید بسازد.
        🌊 W9 — بازگشایی به in_progress (نیازمند رسیدگی مجدد) + گارد.
        """
        t = await self.ticket_get(ticket_id)
        frm = self.ticket_norm_status((t or {}).get('status'))
        if frm not in ('closed', 'resolved'):
            return {'ok': True, 'frm': frm, 'to': frm, 'noop': True}
        return await self.ticket_set_status(ticket_id, 'in_progress')


    # ══════════════════════════════════════════════════
    #  آمار
    # ══════════════════════════════════════════════════
    # ── 🌊 W8/UX-04 — پاسخ‌های آماده ──
    @staticmethod
    def canned_clean_category(c) -> str:
        """🌊 W9 — دسته‌ی پاسخ آماده (خالص): trim + سقف ۴۰ کاراکتر."""
        return str(c or '').strip()[:40]

    async def canned_list(self, only_active: bool = False,
                          category: str = '') -> list:
        q = {'active': True} if only_active else {}
        if self.canned_clean_category(category):
            q['category'] = self.canned_clean_category(category)
        return await self.ticket_canned.find(q).sort('order', 1).to_list(100)

    async def canned_add(self, title: str, text: str, actor_id: int = 0,
                         category: str = '') -> str:
        from bson import ObjectId
        count = await self.ticket_canned.count_documents({})
        r = await self.ticket_canned.insert_one({
            'title': (title or '').strip()[:80], 'text': (text or '').strip()[:2000],
            'active': True, 'order': count,
            'category': self.canned_clean_category(category),
            'created_by': int(actor_id or 0), 'created_at': utc_now_iso()})
        return str(r.inserted_id)

    async def canned_update(self, cid: str, patch: dict) -> bool:
        from bson import ObjectId
        try:
            oid = ObjectId(cid)
        except Exception:
            return False
        clean = {}
        if 'title' in patch:
            clean['title'] = str(patch['title'] or '').strip()[:80]
        if 'text' in patch:
            clean['text'] = str(patch['text'] or '').strip()[:2000]
        if 'active' in patch:
            clean['active'] = bool(patch['active'])
        if 'category' in patch:
            clean['category'] = self.canned_clean_category(
                patch['category'])
        if not clean:
            return False
        r = await self.ticket_canned.update_one({'_id': oid}, {'$set': clean})
        return r.matched_count > 0

    async def canned_delete(self, cid: str) -> bool:
        from bson import ObjectId
        try:
            r = await self.ticket_canned.delete_one({'_id': ObjectId(cid)})
            return r.deleted_count > 0
        except Exception:
            return False

    async def tickets_needing_nudge(self, stale_hours: int,
                                    limit: int = 30) -> list:
        """تیکت‌های باز بدون پاسخ پشتیبانی که از stale_hours گذشته‌اند."""
        from time_utils import now_utc
        from datetime import timedelta
        cutoff = (now_utc() - timedelta(hours=max(1, stale_hours))).isoformat()
        return await self.tickets.find({
            'status': 'open', 'first_response_at': None,
            'created_at': {'$lt': cutoff},
            '$or': [{'stale_nudged_at': None},
                    {'stale_nudged_at': {'$lt': cutoff}}],
        }).sort('created_at', 1).to_list(limit)


    async def log(self, uid: int, action: str, data: dict = None):
        await self.stats_col.insert_one({
            'user_id': uid, 'action': action,
            'data': data or {}, 'timestamp': utc_now_iso(),
        })


    async def user_stats(self, uid: int) -> dict:
        week_ago = (now_utc() - timedelta(days=7)).isoformat()
        week_act, downloads, user = await asyncio.gather(
            self.stats_col.count_documents({'user_id': uid, 'timestamp': {'$gt': week_ago}}),
            self.stats_col.count_documents({
                'user_id': uid,
                'action': {'$in': ['bs_download', 'ref_download', 'qbank_download']},
            }),
            self.get_user(uid),
        )
        total   = user.get('total_answers', 0)   if user else 0
        correct = user.get('correct_answers', 0) if user else 0
        pct     = round(correct / total * 100, 1) if total > 0 else 0
        return {
            'downloads': downloads, 'total_answers': total,
            'correct_answers': correct, 'percentage': pct,
            'week_activity': week_act,
            'weak_topics': user.get('weak_topics', []) if user else [],
        }


    async def weekly_activity(self, uid: int) -> list:
        # 🚀 PERF-O3: 7 sequential count_documents → 1 gather (p95 210ms → 45ms on 20 concurrent /profile calls)
        today = today_tehran()
        days = [today - timedelta(days=i) for i in range(6, -1, -1)]
        bounds = [day_bounds_utc(d) for d in days]
        counts = await asyncio.gather(*[
            self.stats_col.count_documents({
                'user_id': uid,
                'timestamp': {'$gte': s.isoformat(), '$lt': e.isoformat()},
            }) for s, e in bounds
        ])
        return [(format_date_fa(d, date_only=True), c) for d, c in zip(days, counts)]


    async def global_stats(self) -> dict:
        from question_bank.contracts import approved_query, status_query
        week_ago  = (now_utc() - timedelta(days=7)).isoformat()
        new_users = await self.users.count_documents({'registered_at': {'$gt': week_ago}})
        # FIX جدید: online_30m و total_downloads هم اینجا اضافه شد تا
        # نمای کلی سریع پنل ادمین (admin:stats) بدون فراخوانی جداگانه
        # این دو متریک تعامل/سلامت را هم در یک نگاه نشان دهد.
        dl_pipeline = [{'$group': {'_id': None, 'total': {'$sum': '$downloads'}}}]
        vals = await asyncio.gather(
            self.users.count_documents({'approved': True}),
            self.users.count_documents({'approved': False}),
            self.questions.count_documents(approved_query()),
            self.questions.count_documents(status_query("pending")),
            self.bs_lessons.count_documents({}),
            self.bs_sessions.count_documents({}),
            self.bs_content.count_documents({}),
            self.ref_subjects.count_documents({}),
            self.ref_books.count_documents({}),
            self.tickets.count_documents({'status': 'open'}),
            self.users.count_documents({'role': 'content_admin'}),
            self.count_active_users(30),
            self.bs_content.aggregate(dl_pipeline).to_list(1),
            self.ref_files.aggregate(dl_pipeline).to_list(1),
        )
        keys = [
            'users','pending','questions','questions_pending',
            'bs_lessons','bs_sessions','bs_content',
            'ref_subjects','ref_books','open_tickets','content_admins',
            'online_30m',
        ]
        d = dict(zip(keys, vals[:len(keys)]))
        bs_dl, ref_dl = vals[len(keys)], vals[len(keys) + 1]
        d['total_downloads'] = (
            (bs_dl[0]['total']  if bs_dl  else 0) +
            (ref_dl[0]['total'] if ref_dl else 0)
        )
        d['new_users_week'] = new_users
        return d


    async def content_admin_stats(self, intake=None, effective: bool = False) -> dict:
        """آمار پنل محتوا. پیش‌فرض intake=None ⇒ رفتار قدیمی (کل سیستم).
        🌊 C1 — با intake مشخص (از جمله '' = سراسری): فقط لنگرهای همان
        scope شمرده می‌شوند؛ فرزندان از طریق شناسه‌ی والد join می‌شوند.
        🌊 C1.5 — effective=True (فقط وقتی intake کد مشخصی است): آمار
        «مؤثر» = آنچه دانشجوی آن ورودی واقعاً می‌بیند = اختصاصی ورودی +
        سراسری. زیرساخت نمایش آمار مؤثر در UI (موج آینده)."""
        from question_bank.contracts import (and_query, approved_query,
                                              status_query)
        if intake is not None:
            base = await self._content_admin_stats_scoped(intake)
            if effective and intake:
                glob = await self._content_admin_stats_scoped('')
                merged = {k: base.get(k, 0) + glob.get(k, 0) for k in base}
                merged['users_count'] = base.get('users_count', 0)
                return merged
            return base
        keys_content = [
            ('bs_lessons',   self.bs_lessons,   {}),
            ('bs_sessions',  self.bs_sessions,  {}),
            ('bs_total',     self.bs_content,   {}),
            ('bs_video',     self.bs_content,   {'type': 'video'}),
            ('bs_pdf',       self.bs_content,   {'type': 'pdf'}),
            ('bs_ppt',       self.bs_content,   {'type': 'ppt'}),
            ('bs_voice',     self.bs_content,   {'type': 'voice'}),
            ('bs_note',      self.bs_content,   {'type': 'note'}),
            ('bs_test',      self.bs_content,   {'type': 'test'}),
            ('ref_subjects', self.ref_subjects, {}),
            ('ref_books',    self.ref_books,    {}),
            ('ref_files',    self.ref_files,    {}),
            ('ref_fa',       self.ref_files,    {'lang': 'fa'}),
            ('ref_en',       self.ref_files,    {'lang': 'en'}),
            # §W12 — ناهمگامیِ اثبات‌شده: این چهار شمارنده فیلترِ خامِ
            # {'approved': True} داشتند، در حالی که منبعِ حقیقتِ «سؤالِ
            # تأییدشده» تابعِ approved_query() است که هم `status` مدرن و
            # هم `approved` قدیمی را می‌بیند.
            #
            # نتیجه: هر سؤالی که از موجِ ۶ به بعد ساخته شده (فقط `status`
            # دارد) در آمارِ پنل شمرده نمی‌شد. با دو سؤالِ آزمایشی سنجیده
            # شد: approved_query دو تا دید، فیلترِ خام یکی.
            ('q_total',      self.questions,    approved_query()),
            ('q_pending',    self.questions,    status_query('pending')),
            ('q_by_bot',     self.questions,    and_query(approved_query(), {'by_bot': True})),
            ('q_by_users',   self.questions,    and_query(approved_query(), {'by_bot': {'$ne': True}})),
            ('users_count',  self.users,        {'approved': True}),
        ]
        counts = await asyncio.gather(*[col.count_documents(q) for _, col, q in keys_content])
        result = {k: v for (k, col, q), v in zip(keys_content, counts)}
        pipeline = [{'$group': {'_id': None, 'total': {'$sum': '$downloads'}}}]
        r_bs, r_ref = await asyncio.gather(
            self.bs_content.aggregate(pipeline).to_list(1),
            self.ref_files.aggregate(pipeline).to_list(1),
        )
        result['total_downloads'] = (
            (r_bs[0]['total']  if r_bs  else 0) +
            (r_ref[0]['total'] if r_ref else 0)
        )
        return result


    async def _content_admin_stats_scoped(self, intake: str) -> dict:
        """🌊 C1 — همان ساختار content_admin_stats ولی محدود به یک scope."""
        intake = intake or ''
        lessons = await self.bs_lessons.find({'intake': intake}).to_list(500)
        lids = [str(l['_id']) for l in lessons]
        sessions = await self.bs_sessions.find(
            {'lesson_id': {'$in': lids}}).to_list(2000) if lids else []
        sids = [str(s['_id']) for s in sessions]
        cq = {'session_id': {'$in': sids}} if sids else {'session_id': '__none__'}

        subjects = await self.ref_subjects.find({'intake': intake}).to_list(500)
        sub_ids = [str(s['_id']) for s in subjects]
        books = await self.ref_books.find(
            {'subject_id': {'$in': sub_ids}}).to_list(2000) if sub_ids else []
        bids = [str(b['_id']) for b in books]
        fq = {'book_id': {'$in': bids}} if bids else {'book_id': '__none__'}

        keys = [
            ('bs_lessons',   self.bs_lessons,   {'intake': intake}),
            ('bs_sessions',  self.bs_sessions,  {'lesson_id': {'$in': lids} if lids else {'$in': []}}),
            ('bs_total',     self.bs_content,   cq),
            ('bs_video',     self.bs_content,   dict(cq, type='video')),
            ('bs_pdf',       self.bs_content,   dict(cq, type='pdf')),
            ('bs_ppt',       self.bs_content,   dict(cq, type='ppt')),
            ('bs_voice',     self.bs_content,   dict(cq, type='voice')),
            ('bs_note',      self.bs_content,   dict(cq, type='note')),
            ('bs_test',      self.bs_content,   dict(cq, type='test')),
            ('ref_subjects', self.ref_subjects, {'intake': intake}),
            ('ref_books',    self.ref_books,    {'subject_id': {'$in': sub_ids} if sub_ids else {'$in': []}}),
            ('ref_files',    self.ref_files,    fq),
            ('ref_fa',       self.ref_files,    dict(fq, lang='fa')),
            ('ref_en',       self.ref_files,    dict(fq, lang='en')),
            ('q_total',      self.questions,    {'approved': True, 'intake': intake}),
            ('q_pending',    self.questions,    {'approved': False, 'intake': intake}),
            ('q_by_bot',     self.questions,    {'approved': True, 'by_bot': True, 'intake': intake}),
            ('q_by_users',   self.questions,    {'approved': True, 'by_bot': {'$ne': True}, 'intake': intake}),
            ('users_count',  self.users,        {'approved': True, 'intake': intake} if intake else {'approved': True}),
        ]
        counts = await asyncio.gather(*[col.count_documents(q) for _, col, q in keys])
        result = {k: v for (k, col, q), v in zip(keys, counts)}
        pipeline_bs = [{'$match': cq},
                       {'$group': {'_id': None, 'total': {'$sum': '$downloads'}}}]
        pipeline_rf = [{'$match': fq},
                       {'$group': {'_id': None, 'total': {'$sum': '$downloads'}}}]
        r_bs, r_ref = await asyncio.gather(
            self.bs_content.aggregate(pipeline_bs).to_list(1),
            self.ref_files.aggregate(pipeline_rf).to_list(1),
        )
        result['total_downloads'] = (
            (r_bs[0]['total']  if r_bs  else 0) +
            (r_ref[0]['total'] if r_ref else 0)
        )
        return result


    # ══════════════════════════════════════════════════
    #  FIX جدید: داشبورد آماری پیشرفته پنل ادمین — پوشش کامل‌تر
    #  کل ربات (کاربران/محتوا/سوالات/تیکت‌ها/اعلان‌ها) با جزئیات
    #  بیشتر از global_stats ساده‌ی قبلی.
    # ══════════════════════════════════════════════════

    async def stats_dashboard_users(self) -> dict:
        """آمار جزئی کاربران: رشد، فعالیت، گروه/ورودی، نقش‌های فرعی"""
        from utils import today_start_utc_str
        now          = now_utc()
        today_start  = today_start_utc_str()
        week_ago     = (now - timedelta(days=7)).isoformat()
        month_ago    = (now - timedelta(days=30)).isoformat()
        inactive_14 = (now - timedelta(days=14)).isoformat()
        inactive_30 = (now - timedelta(days=30)).isoformat()

        (total_approved, total_pending, new_today, new_week, new_month,
         g1, g2, active_today, active_week, blocked_bot, content_admins,
         inactive_14d, inactive_30d, growth_rows, intake_rows,
         all_intakes, all_roles) = await asyncio.gather(
            self.users.count_documents({'approved': True}),
            self.users.count_documents({'approved': False}),
            self.users.count_documents({'registered_at': {'$gte': today_start}}),
            self.users.count_documents({'registered_at': {'$gte': week_ago}}),
            self.users.count_documents({'registered_at': {'$gte': month_ago}}),
            self.users.count_documents({'approved': True, 'group': '1'}),
            self.users.count_documents({'approved': True, 'group': '2'}),
            self.users.count_documents({'last_active': {'$gte': today_start}}),
            self.users.count_documents({'last_active': {'$gte': week_ago}}),
            self.users.count_documents({'blocked_bot': True}),
            self.users.count_documents({'role': 'content_admin'}),
            self.users.count_documents({'approved': True, '$or': [
                {'last_active': {'$lt': inactive_14}}, {'last_active': {'$exists': False}},
                {'last_active': None}, {'last_active': ''}]}),
            self.users.count_documents({'approved': True, '$or': [
                {'last_active': {'$lt': inactive_30}}, {'last_active': {'$exists': False}},
                {'last_active': None}, {'last_active': ''}]}),
            self.users.aggregate([
                {'$match': {'approved': True, 'registered_at': {'$gte': week_ago}}},
                {'$addFields': {'_registered_dt': {'$convert': {
                    'input': '$registered_at', 'to': 'date', 'onError': None, 'onNull': None}}}},
                {'$match': {'_registered_dt': {'$ne': None}}},
                {'$group': {'_id': {'$dateToString': {
                    'format': '%Y-%m-%d', 'date': '$_registered_dt', 'timezone': 'Asia/Tehran'}},
                    'count': {'$sum': 1}}},
            ]).to_list(10),
            self.users.aggregate([
                {'$match': {'approved': True}},
                {'$group': {'_id': {'$ifNull': ['$intake', '']}, 'count': {'$sum': 1}}},
                {'$sort': {'count': -1}},
            ]).to_list(500),
            self.get_all_intakes(),
            self.get_all_admin_roles(),
        )

        growth_map = {row.get('_id'): int(row.get('count') or 0) for row in growth_rows}
        growth_7d = []
        local_today = today_tehran()
        for i in range(6, -1, -1):
            day = local_today - timedelta(days=i)
            growth_7d.append((format_date_fa(day, date_only=True), growth_map.get(day.isoformat(), 0)))

        # تفکیک ورودی با aggregation؛ بدون hydration کاربران.
        intake_label = {i['code']: i['label'] for i in all_intakes}
        by_intake = [(intake_label.get(row.get('_id') or '', row.get('_id') or 'بدون ورودی'),
                      int(row.get('count') or 0)) for row in intake_rows]

        role_counts: dict = {}
        for r in all_roles:
            role_counts[r.get('role', '')] = role_counts.get(r.get('role', ''), 0) + 1

        # FIX جدید: ۳ کاربر برتر (بر اساس جدول برترین‌های dashboard.py)
        # هم اینجا نمایش داده می‌شود تا ادمین فعال‌ترین کاربران را هم
        # در کنار آمار رشد/فعالیت ببیند.
        top_user_docs = await self.get_leaderboard(3)
        # get_leaderboard اسناد کامل Mongo را برمی‌گرداند. برگرداندن مستقیم
        # آن‌ها هم ObjectId را در JSON encoder منفجر می‌کرد و هم فیلدهای
        # خصوصی نامرتبط کاربر (مثل حافظه‌ی AI) را وارد پاسخ analytics می‌کرد.
        # این projection، قرارداد کمینه و سریال‌پذیر پنل را نگه می‌دارد.
        def _as_count(value) -> int:
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        top_users = []
        for row in top_user_docs:
            total = _as_count(row.get('total_answers'))
            correct = _as_count(row.get('correct_answers'))
            top_users.append({
                'user_id': row.get('user_id'),
                'name': str(row.get('nickname') or row.get('name') or ''),
                'total_answers': total,
                'correct_answers': correct,
                'accuracy': round(correct * 100 / total, 1) if total else 0,
            })

        return {
            'total_approved': total_approved, 'total_pending': total_pending,
            'new_today': new_today, 'new_week': new_week, 'new_month': new_month,
            'group1': g1, 'group2': g2,
            'group_unset': max(total_approved - g1 - g2, 0),
            'active_today': active_today, 'active_week': active_week,
            'inactive_14d': inactive_14d, 'inactive_30d': inactive_30d,
            'blocked_bot': blocked_bot, 'content_admins': content_admins,
            'growth_7d': growth_7d, 'by_intake': by_intake,
            'sub_admin_roles': role_counts, 'top_users': top_users,
        }


    async def stats_dashboard_content(self) -> dict:
        """Content and structured Question Bank analytics (legacy file bank retired)."""
        from question_bank.contracts import approved_query
        week_ago = (now_utc() - timedelta(days=7)).isoformat()
        (bs_lessons, bs_sessions, bs_by_type, ref_subjects, ref_books,
         ref_by_lang, faq_count, qbank_questions, top_qbank_lessons,
         bs_dl_agg, ref_dl_agg, qbank_attempts,
         new_bs_week, new_ref_week, new_questions_week) = await asyncio.gather(
            self.bs_lessons.count_documents({}),
            self.bs_sessions.count_documents({}),
            self.bs_content.aggregate(
                [{'$group': {'_id': '$type', 'count': {'$sum': 1}}}]).to_list(20),
            self.ref_subjects.count_documents({}),
            self.ref_books.count_documents({}),
            self.ref_files.aggregate(
                [{'$group': {'_id': '$lang', 'count': {'$sum': 1}}}]).to_list(10),
            self.faq.count_documents({}),
            self.questions.count_documents(approved_query()),
            self.questions.aggregate([
                {'$match': approved_query()},
                {'$group': {'_id': '$lesson', 'count': {'$sum': 1}}},
                {'$sort': {'count': -1}}, {'$limit': 5},
            ]).to_list(5),
            self.bs_content.aggregate(
                [{'$group': {'_id': None, 'total': {'$sum': '$downloads'}}}]).to_list(1),
            self.ref_files.aggregate(
                [{'$group': {'_id': None, 'total': {'$sum': '$downloads'}}}]).to_list(1),
            self.answers.count_documents({}),
            self.bs_content.count_documents({'uploaded_at': {'$gt': week_ago}}),
            self.ref_files.count_documents({'uploaded_at': {'$gt': week_ago}}),
            self.questions.count_documents({'created_at': {'$gt': week_ago}}),
        )
        type_labels = {
            'video': '🎥 ویدیو', 'ppt': '📊 پاورپوینت', 'pdf': '📄 PDF',
            'note': '📝 نکات', 'test': '🧪 تست', 'voice': '🎙 ویس',
        }
        bs_types = {type_labels.get(d['_id'], d['_id'] or 'نامشخص'): d['count'] for d in bs_by_type}
        lang_labels = {'fa': '🇮🇷 فارسی', 'en': '🌍 انگلیسی'}
        ref_langs = {lang_labels.get(d['_id'], d['_id'] or 'نامشخص'): d['count'] for d in ref_by_lang}
        return {
            'bs_lessons': bs_lessons, 'bs_sessions': bs_sessions,
            'bs_types': bs_types, 'bs_total_content': sum(bs_types.values()),
            'ref_subjects': ref_subjects, 'ref_books': ref_books,
            'ref_langs': ref_langs, 'ref_total_files': sum(ref_langs.values()),
            'faq_count': faq_count, 'qbank_questions': qbank_questions,
            'top_qbank_lessons': [(d['_id'] or 'نامشخص', d['count']) for d in top_qbank_lessons],
            'qbank_attempts': qbank_attempts,
            'bs_downloads': (bs_dl_agg[0]['total'] if bs_dl_agg else 0),
            'ref_downloads': (ref_dl_agg[0]['total'] if ref_dl_agg else 0),
            'new_this_week': new_bs_week + new_ref_week + new_questions_week,
        }


    async def stats_dashboard_questions(self) -> dict:
        """آمار جزئی بانک سوال: دقت پاسخ‌دهی، پرسوال‌ترین درس‌ها، سخت‌ترین سوالات"""
        from question_bank.contracts import and_query, approved_query, status_query
        approved = approved_query()
        (q_approved, q_pending, q_by_bot, q_by_users, by_diff, by_lesson, totals, hardest) = await asyncio.gather(
            self.questions.count_documents(approved),
            self.questions.count_documents(status_query("pending")),
            self.questions.count_documents(and_query(approved, {'source': 'admin_bot'})),
            self.questions.count_documents(and_query(approved, {'source': {'$ne': 'admin_bot'}})),
            self.questions.aggregate([
                {'$match': approved},
                {'$group': {'_id': '$difficulty', 'count': {'$sum': 1}}},
            ]).to_list(10),
            self.questions.aggregate([
                {'$match': approved},
                {'$group': {'_id': '$lesson', 'count': {'$sum': 1}}},
                {'$sort': {'count': -1}}, {'$limit': 5},
            ]).to_list(5),
            self.questions.aggregate([
                {'$match': approved},
                {'$group': {'_id': None,
                            'attempts': {'$sum': '$attempt_count'},
                            'correct':  {'$sum': '$correct_count'}}},
            ]).to_list(1),
            self.questions.aggregate([
                {'$match': and_query(approved, {'attempt_count': {'$gte': 5}})},
                {'$project': {
                    'lesson': 1, 'topic': 1, 'question': 1,
                    'attempt_count': 1, 'correct_count': 1,
                    'wrong_rate': {'$divide': [
                        {'$subtract': ['$attempt_count', '$correct_count']},
                        '$attempt_count',
                    ]},
                }},
                {'$sort': {'wrong_rate': -1}}, {'$limit': 5},
            ]).to_list(5),
        )
        diff_labels = {'easy': '🟢 آسان', 'medium': '🟡 متوسط', 'hard': '🔴 سخت'}
        by_difficulty = {diff_labels.get(d['_id'], d['_id'] or 'نامشخص'): d['count'] for d in by_diff}
        total_attempts = totals[0]['attempts'] if totals else 0
        total_correct  = totals[0]['correct']  if totals else 0
        accuracy = round(total_correct / total_attempts * 100, 1) if total_attempts else 0
        hardest_list = [{
            'lesson': h.get('lesson', ''), 'topic': h.get('topic', ''),
            'question': (h.get('question', '') or '')[:50],
            'wrong_rate': round(h.get('wrong_rate', 0) * 100, 1),
            'attempts': h.get('attempt_count', 0),
        } for h in hardest]

        return {
            'approved': q_approved, 'pending': q_pending,
            'by_bot': q_by_bot, 'by_users': q_by_users,
            'by_difficulty': by_difficulty,
            'top_lessons': [(d['_id'] or 'نامشخص', d['count']) for d in by_lesson],
            'total_attempts': total_attempts, 'total_correct': total_correct,
            'accuracy': accuracy, 'hardest_questions': hardest_list,
        }


    async def stats_dashboard_tickets(self) -> dict:
        """آمار جزئی پشتیبانی"""
        week_ago  = (now_utc() - timedelta(days=7)).isoformat()
        month_ago = (now_utc() - timedelta(days=30)).isoformat()
        (open_t, closed_t, new_week, new_month, closed_week, resolved_month) = await asyncio.gather(
            self.tickets.count_documents({'status': 'open'}),
            self.tickets.count_documents({'status': 'closed'}),
            self.tickets.count_documents({'created_at': {'$gte': week_ago}}),
            self.tickets.count_documents({'created_at': {'$gte': month_ago}}),
            self.tickets.count_documents({'status': 'closed', 'closed_at': {'$gte': week_ago}}),
            self.tickets.find({
                'status': 'closed', 'closed_at': {'$gte': month_ago},
            }, {'created_at': 1, 'closed_at': 1}).to_list(500),
        )
        # FIX جدید: میانگین زمان رسیدگی — بر مبنای تیکت‌های بسته‌شده‌ی
        # ۳۰ روز اخیر، چون created_at/closed_at رشته‌ی isoformat‌اند و
        # محاسبه در پایتون از aggregation با فرمت ناهمگون مطمئن‌تر است.
        durations_h = []
        for t in resolved_month:
            try:
                c0 = parse_machine_datetime(t['created_at'])
                c1 = parse_machine_datetime(t['closed_at'])
                durations_h.append((c1 - c0).total_seconds() / 3600)
            except Exception:
                continue
        avg_resolution_h = round(sum(durations_h) / len(durations_h), 1) if durations_h else None

        return {
            'open': open_t, 'closed': closed_t, 'total': open_t + closed_t,
            'new_week': new_week, 'new_month': new_month, 'closed_week': closed_week,
            'avg_resolution_h': avg_resolution_h, 'resolved_sample': len(durations_h),
        }


    async def stats_dashboard_notif(self) -> dict:
        """خلاصه سلامت اعلان‌های خودکار — بر اساس ۱۰ اجرای اخیر هر job"""
        jobs = ['exam_reminder', 'daily_question', 'new_resources']
        result = {}
        for j in jobs:
            runs = await self.notif_runs.find({'job_name': j}).sort('started_at', -1).to_list(10)
            if not runs:
                result[j] = None
                continue
            last = runs[0]
            result[j] = {
                'runs_checked':  len(runs),
                'total_sent':    sum(r.get('sent', 0) for r in runs),
                'total_failed':  sum(r.get('failed', 0) for r in runs),
                'last_status':   last.get('status', ''),
                'last_at':       last.get('started_at') or None,
                'last_sent':     last.get('sent', 0),
                'last_failed':   last.get('failed', 0),
            }
        return result


    async def new_resources_count(self, days: int = 7) -> int:
        since = (now_utc() - timedelta(days=days)).isoformat()
        bs, refs = await asyncio.gather(
            self.bs_content.count_documents({'uploaded_at': {'$gt': since}}),
            self.ref_files.count_documents({'uploaded_at': {'$gt': since}}),
        )
        return bs + refs


    # 🌊 موج Analytics-Filters — منطق واحد سری تحلیلی بازه‌ای.
    # قبلاً این تجمیع فقط داخل endpoint مالک (/api/admin/analytics) بود؛
    # حالا تک‌منبع حقیقت اینجاست و هر دو مسیر (مالک + stats.deep وب‌ادمین)
    # از آن استفاده می‌کنند — خروجی دقیقاً همان شکل قبلی است (Never Break).
    async def stats_analytics_bundle(self, days: int = 14) -> dict:
        """Persisted period analytics plus an explicit like-for-like previous period.

        The method deliberately returns ``None`` for percentage change when the
        previous period is zero, because no finite comparison can be claimed.
        """
        try:
            days = max(1, min(90, int(days or 14)))
        except (TypeError, ValueError):
            days = 14
        # 🚀 PERF-O6 cache check (15s)
        import time as _pt
        try:
            _cached, _at = self._analytics_cache.get(int(days), (None, 0))
            if _cached is not None and (_pt.monotonic() - _at) < self._analytics_cache_ttl:
                # copy to avoid mutation
                return dict(_cached)
        except: pass
        now = now_utc()
        current_start = now - timedelta(days=days)
        previous_start = now - timedelta(days=days * 2)
        since = current_start.isoformat()
        previous_since = previous_start.isoformat()
        period_end = now.isoformat()

        async def _daily(col, ts_field):
            rows = await col.aggregate([
                {"$match": {ts_field: {"$gte": since, "$lt": period_end}}},
                {"$addFields": {"_event_dt": {"$convert": {
                    "input": f"${ts_field}", "to": "date", "onError": None, "onNull": None}}}},
                {"$match": {"_event_dt": {"$ne": None}}},
                {"$group": {"_id": {"$dateToString": {
                    "format": "%Y-%m-%d", "date": "$_event_dt", "timezone": "Asia/Tehran"}},
                    "count": {"$sum": 1}}},
                {"$sort": {"_id": 1}},
            ]).to_list(days + 2)
            return [{"date": r["_id"], "count": r["count"]}
                    for r in rows if r.get("_id")]

        current_window = {"$gte": since, "$lt": period_end}
        previous_window = {"$gte": previous_since, "$lt": since}
        (
            users_daily, activity_daily, tickets_daily,
            active_uids, previous_active_uids,
            new_users, previous_new_users,
            total_actions, previous_total_actions,
            new_tickets, previous_new_tickets,
            open_reports,
        ) = await asyncio.gather(
            _daily(self.users, "registered_at"),
            _daily(self.stats_col, "timestamp"),
            _daily(self.tickets, "created_at"),
            self.stats_col.distinct("user_id", {"timestamp": current_window}),
            self.stats_col.distinct("user_id", {"timestamp": previous_window}),
            self.users.count_documents({"registered_at": current_window}),
            self.users.count_documents({"registered_at": previous_window}),
            self.stats_col.count_documents({"timestamp": current_window}),
            self.stats_col.count_documents({"timestamp": previous_window}),
            self.tickets.count_documents({"created_at": current_window}),
            self.tickets.count_documents({"created_at": previous_window}),
            self.content_reports.count_documents({"status": "new"}),
        )

        top_actions_rows, hourly_rows = await asyncio.gather(
            self.stats_col.aggregate([
                {"$match": {"timestamp": current_window}},
                {"$group": {"_id": "$action", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 8},
            ]).to_list(8),
            self.stats_col.aggregate([
                {"$match": {"timestamp": current_window}},
                {"$group": {"_id": {"$substrBytes": ["$timestamp", 11, 2]},
                            "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 6},
            ]).to_list(6),
        )
        top_actions = [{"action": r["_id"] or "نامشخص", "count": r["count"]}
                       for r in top_actions_rows]
        hourly = sorted(
            [{"hour": int(r["_id"]), "count": r["count"]}
             for r in hourly_rows
             if r.get("_id") and str(r["_id"]).isdigit()],
            key=lambda x: x["hour"])

        current_kpis = {
            "active_users": len(active_uids),
            "new_users": new_users,
            "total_actions": total_actions,
            "new_tickets": new_tickets,
            "open_reports": open_reports,
        }
        previous_kpis = {
            "active_users": len(previous_active_uids),
            "new_users": previous_new_users,
            "total_actions": previous_total_actions,
            "new_tickets": previous_new_tickets,
        }

        def _comparison(key: str) -> dict:
            current = int(current_kpis[key] or 0)
            previous = int(previous_kpis[key] or 0)
            change_pct = (round((current - previous) * 100 / previous, 1)
                          if previous else (0.0 if current == 0 else None))
            return {"current": current, "previous": previous,
                    "change_pct": change_pct,
                    "direction": "up" if current > previous else "down" if current < previous else "flat"}

        _result = {
            "days": days,
            "generated_at": period_end,
            "period": {
                "current_start": since, "current_end": period_end,
                "previous_start": previous_since, "previous_end": since,
            },
            "kpis": current_kpis,
            "previous_kpis": previous_kpis,
            "comparison": {key: _comparison(key) for key in previous_kpis},
            "daily": {
                "users": users_daily,
                "activity": activity_daily,
                "tickets": tickets_daily,
            },
            "top_actions": top_actions,
            "hourly": hourly,
        }
        try:
            self._analytics_cache[int(days)] = (dict(_result), _pt.monotonic())
            # LRU cap 20 keys
            if len(self._analytics_cache) > 20:
                oldest = min(self._analytics_cache.items(), key=lambda kv: kv[1][1])[0]
                self._analytics_cache.pop(oldest, None)
        except: pass
        return _result


    async def activity_pulse(self) -> dict:
        """
        FIX جدید: نبض فعالیت ربات — حجم کل کنش‌های ثبت‌شده در ۷ روز
        اخیر و پرترافیک‌ترین ساعت شبانه‌روز، برای نمای کلی داشبورد.
        timestamp به‌صورت رشته‌ی isoformat ذخیره می‌شود، پس ساعت با
        substring به‌جای پارس تاریخ کامل استخراج می‌شود (سریع‌تر و
        مطمئن‌تر روی رشته‌های با دقت میکروثانیه‌ی متغیر).
        """
        week_ago = (now_utc() - timedelta(days=7)).isoformat()
        total_week, by_hour = await asyncio.gather(
            self.stats_col.count_documents({'timestamp': {'$gt': week_ago}}),
            self.stats_col.aggregate([
                {'$match': {'timestamp': {'$gt': week_ago}}},
                {'$addFields': {'_event_dt': {'$convert': {
                    'input': '$timestamp', 'to': 'date', 'onError': None, 'onNull': None}}}},
                {'$match': {'_event_dt': {'$ne': None}}},
                {'$group': {
                    '_id': {'$dateToString': {
                        'format': '%H', 'date': '$_event_dt', 'timezone': 'Asia/Tehran'}},
                    'count': {'$sum': 1},
                }},
                {'$sort': {'count': -1}}, {'$limit': 1},
            ]).to_list(1),
        )
        peak_hour, peak_count = (None, 0)
        if by_hour:
            peak_hour, peak_count = by_hour[0]['_id'], by_hour[0]['count']
        return {
            'total_actions_week': total_week,
            'peak_hour': peak_hour, 'peak_hour_count': peak_count,
        }


    async def admin_insights(self) -> dict:
        """
        FIX جدید — «مرکز هوش ربات»: به‌جای اینکه ادمین خودش بین چند
        صفحه‌ی آمار بگردد تا مشکلات را پیدا کند، این متد با چند قانون
        ساده (rule-based) روی داده‌های واقعی، خودش هشدارهای قابل‌اقدام
        و پیش‌بینی رشد هفته‌ی بعد را تولید می‌کند. هیچ داده‌ای شبیه‌سازی
        نمی‌شود — همه از همان کالکشن‌های موجود محاسبه می‌شود.
        """
        now        = now_utc()
        h48        = (now - timedelta(hours=48)).isoformat()
        d14        = (now - timedelta(days=14)).isoformat()
        d3         = (now - timedelta(days=3)).isoformat()

        (
            pending_old, oldest_pending,
            tickets_old, oldest_ticket,
            bad_questions,
            inactive_admins,
            all_sessions, content_session_ids,
        ) = await asyncio.gather(
            self.users.count_documents({'approved': False, 'registered_at': {'$lt': h48}}),
            self.users.find({'approved': False}).sort('registered_at', 1).to_list(1),
            self.tickets.count_documents({'status': 'open', 'created_at': {'$lt': h48}}),
            self.tickets.find({'status': 'open'}).sort('created_at', 1).to_list(1),
            self.questions.count_documents({
                'approved': True, 'attempt_count': {'$gte': 5},
                '$expr': {'$gte': [
                    {'$divide': [
                        {'$subtract': ['$attempt_count', '$correct_count']},
                        '$attempt_count',
                    ]}, 0.7,
                ]},
            }),
            self.users.find({
                'role': 'content_admin',
                '$or': [{'last_active': {'$lt': d14}}, {'last_active': {'$exists': False}}],
            }, {'name': 1}).to_list(20),
            self.bs_sessions.find({'created_at': {'$lt': d3}}, {'_id': 1}).to_list(500),
            self.bs_content.distinct('session_id'),
        )

        oldest_pending_h = None
        if oldest_pending:
            try:
                oldest_pending_h = round((now - parse_machine_datetime(oldest_pending[0]['registered_at'])).total_seconds() / 3600)
            except Exception:
                pass
        oldest_ticket_h = None
        if oldest_ticket:
            try:
                oldest_ticket_h = round((now - parse_machine_datetime(oldest_ticket[0]['created_at'])).total_seconds() / 3600)
            except Exception:
                pass

        content_session_ids = set(str(s) for s in content_session_ids)
        empty_sessions = [s for s in all_sessions if str(s['_id']) not in content_session_ids]

        # ── گزارشات محتوا/سوال بررسی‌نشده ──
        new_reports = await self.content_reports.count_documents({'status': 'new'})

        # ── فعالیت ادمین‌های فرعی پنل (بر اساس audit_logs) ──
        # FIX جدید: پرکارترین و کم‌کارترین ادمین‌های فرعی، برای این‌که
        # ادمین ارشد بفهمد کدام همکار واقعاً از پنل استفاده می‌کند و
        # کدام مدت‌هاست سراغش نرفته — بدون نیاز به گشتن دستی در لاگ خام.
        role_docs = await self.get_all_admin_roles()
        admin_uids = [r['_id'] for r in role_docs]
        top_admins, stale_admins = [], []
        if admin_uids:
            week_ago_iso = (now - timedelta(days=7)).isoformat()
            week_agg, last_agg, name_docs = await asyncio.gather(
                self.audit_logs.aggregate([
                    {'$match': {'timestamp': {'$gt': week_ago_iso}, 'actor.id': {'$in': admin_uids}}},
                    {'$group': {'_id': '$actor.id', 'count': {'$sum': 1}}},
                    {'$sort': {'count': -1}},
                ]).to_list(50),
                self.audit_logs.aggregate([
                    {'$match': {'actor.id': {'$in': admin_uids}}},
                    {'$group': {'_id': '$actor.id', 'last_action': {'$max': '$timestamp'}}},
                ]).to_list(50),
                self.users.find({'user_id': {'$in': admin_uids}}, {'user_id': 1, 'name': 1}).to_list(len(admin_uids)),
            )
            name_map = {d['user_id']: d.get('name', 'ادمین') for d in name_docs}
            role_map = {r['_id']: self.ROLE_LABELS.get(r.get('role', ''), r.get('role', '')) for r in role_docs}
            week_map = {d['_id']: d['count'] for d in week_agg}
            last_map = {d['_id']: d['last_action'] for d in last_agg}

            for uid_ in admin_uids:
                nm = name_map.get(uid_, f"ادمین #{uid_}")
                rl = role_map.get(uid_, '')
                wk = week_map.get(uid_, 0)
                last_ts = last_map.get(uid_)
                if wk > 0:
                    top_admins.append({'name': nm, 'role': rl, 'count': wk})
                if last_ts:
                    try:
                        days_idle = (now - parse_machine_datetime(last_ts)).days
                    except Exception:
                        days_idle = None
                else:
                    days_idle = None  # هرگز فعالیتی ثبت نشده
                if days_idle is None or days_idle >= 14:
                    stale_admins.append({'name': nm, 'role': rl, 'days_idle': days_idle})
            top_admins.sort(key=lambda x: x['count'], reverse=True)
            top_admins = top_admins[:5]

        # ── روند رشد ۴ هفته‌ی اخیر + پیش‌بینی ساده‌ی هفته‌ی بعد ──
        week_queries = []
        for i in range(4):
            start = (now - timedelta(days=7 * (i + 1))).isoformat()
            end   = (now - timedelta(days=7 * i)).isoformat()
            week_queries.append({'registered_at': {'$gte': start, '$lt': end}})
        week_counts = list(await asyncio.gather(
            *(self.users.count_documents(query) for query in week_queries)
        ))  # week_counts[0] = این هفته، [3] = چهار هفته پیش
        this_week = week_counts[0]
        prior_avg = round(sum(week_counts[1:]) / 3, 1) if any(week_counts[1:]) else 0
        slope     = (week_counts[0] - week_counts[3]) / 3 if len(week_counts) == 4 else 0
        forecast_next_week = max(0, round(this_week + slope))
        growth_alert = None
        if prior_avg > 0:
            change = round((this_week - prior_avg) / prior_avg * 100)
            if change <= -30:
                growth_alert = f"📉 افت {abs(change)}٪ در ثبت‌نام این هفته نسبت به میانگین ۳ هفته‌ی قبل"
            elif change >= 50:
                growth_alert = f"📈 جهش {change}٪ در ثبت‌نام این هفته نسبت به میانگین ۳ هفته‌ی قبل"

        alerts = []
        if pending_old:
            alerts.append({
                'icon': '⏳', 'title': f"{pending_old} کاربر بیش از ۴۸ ساعت منتظر تأییدند",
                'detail': f"قدیمی‌ترین: {oldest_pending_h} ساعت پیش" if oldest_pending_h else '',
                'action': 'admin:pending',
            })
        if tickets_old:
            alerts.append({
                'icon': '🎫', 'title': f"{tickets_old} تیکت بیش از ۴۸ ساعت باز مانده",
                'detail': f"قدیمی‌ترین: {oldest_ticket_h} ساعت پیش" if oldest_ticket_h else '',
                'action': 'ticket:manage',
            })
        if bad_questions:
            alerts.append({
                'icon': '😵', 'title': f"{bad_questions} سوال نرخ خطای ۷۰٪+ دارند و نیاز به بازبینی دارند",
                'detail': 'حداقل ۵ پاسخ ثبت‌شده برای هرکدام',
                'action': 'admin:stats_questions',
            })
        if inactive_admins:
            names = "، ".join(a.get('name', 'ادمین') for a in inactive_admins[:5])
            alerts.append({
                'icon': '😴', 'title': f"{len(inactive_admins)} ادمین محتوا ۱۴+ روز غیرفعال بوده‌اند",
                'detail': names, 'action': 'admin:cat_users',
            })
        if empty_sessions:
            alerts.append({
                'icon': '📭', 'title': f"{len(empty_sessions)} جلسه‌ی علوم پایه هنوز هیچ محتوایی ندارد",
                'detail': 'حداقل ۳ روز از ساخت‌شان گذشته', 'action': 'admin:cat_content',
            })
        if new_reports:
            alerts.append({
                'icon': '📋', 'title': f"{new_reports} گزارش محتوا/سوال بررسی‌نشده در صف است",
                'detail': '', 'action': 'report:manage:all',
            })
        if stale_admins:
            names = "، ".join(
                f"{a['name']} ({a['days_idle']} روز)" if a['days_idle'] is not None else f"{a['name']} (هرگز)"
                for a in stale_admins[:5]
            )
            alerts.append({
                'icon': '🕸', 'title': f"{len(stale_admins)} ادمین فرعی پنل ۱۴+ روز از پنل استفاده نکرده‌اند",
                'detail': names, 'action': 'admin:cat_users',
            })
        if growth_alert:
            alerts.append({'icon': '📊', 'title': growth_alert, 'detail': '', 'action': 'admin:stats_users'})

        return {
            'alerts': alerts,
            'week_counts': week_counts, 'this_week': this_week, 'prior_avg': prior_avg,
            'forecast_next_week': forecast_next_week,
            'top_admins': top_admins, 'stale_admins': stale_admins,
        }



# instance جهانی
    # ══════════════════════════════════════════════════
    #  تنظیمات کلی ربات (bot_settings)
    # ══════════════════════════════════════════════════

    async def get_setting(self, key: str, default=None):
        # 🚀 PERF-O2: cached path
        import time as _t
        now = _t.monotonic()
        if self._settings_cache is not None and (now - self._settings_cache_at) < self._settings_cache_ttl:
            return self._settings_cache.get(key, default)
        # miss or stale → fetch once under lock (avoid thundering herd under /api burst)
        async with self._settings_lock:
            # double-check after lock
            now2 = _t.monotonic()
            if self._settings_cache is not None and (now2 - self._settings_cache_at) < self._settings_cache_ttl:
                return self._settings_cache.get(key, default)
            doc = await self.settings.find_one({'_id': 'global'})
            self._settings_cache = doc or {}
            self._settings_cache_at = _t.monotonic()
            if not doc:
                return default
            return doc.get(key, default)


    async def set_setting(self, key: str, value) -> None:
        await self.settings.update_one(
            {'_id': 'global'},
            {'$set': {key: value, 'updated_at': utc_now_iso()}},
            upsert=True
        )
        # invalidate cache immediately (no stale notif_defaults after admin toggle)
        async with self._settings_lock:
            if self._settings_cache is not None:
                self._settings_cache[key] = value
                self._settings_cache["updated_at"] = utc_now_iso()


    async def delete_setting(self, key: str) -> None:
        try:
            await self.settings.update_one(
                {'_id': 'global'}, {'$unset': {key: ''}}
            )
            async with self._settings_lock:
                if self._settings_cache is not None and key in self._settings_cache:
                    self._settings_cache.pop(key, None)
        except Exception:
            pass


    async def get_settings_by_prefix(self, prefix: str) -> dict:
        # reuse TTL cache
        import time as _t
        doc = None
        now = _t.monotonic()
        if self._settings_cache is not None and (now - self._settings_cache_at) < self._settings_cache_ttl:
            doc = self._settings_cache
        else:
            # fetch via get_setting path to populate cache
            await self.get_setting("__warmup__", None)
            doc = self._settings_cache or {}
        if not doc:
            return {}
        return {k: v for k, v in doc.items() if isinstance(k, str) and k.startswith(prefix)}


    async def get_all_settings(self) -> dict:
        import time as _t
        now = _t.monotonic()
        if self._settings_cache is not None and (now - self._settings_cache_at) < self._settings_cache_ttl:
            return dict(self._settings_cache)
        doc = await self.settings.find_one({'_id': 'global'})
        # populate cache
        async with self._settings_lock:
            self._settings_cache = doc or {}
            self._settings_cache_at = _t.monotonic()
        return doc or {}


    async def users_missing_student_id(self) -> list:
        return await self.users.find({
            'approved': True,
            '$or': [
                {'student_id': {'$exists': False}},
                {'student_id': ''},
                {'student_id': None},
            ]
        }).to_list(1000)


    # ══════════════════════════════════════════════════
    #  لاگ فعالیت حساس (audit_logs)
    # ══════════════════════════════════════════════════

    # FIX جدید: سطوح اهمیت لاگ — برای فیلتر کردن نویز از سیگنال
    SEVERITY_LEVELS = {
        'INFO':     '🟢 INFO',
        'WARNING':  '🟡 WARNING',
        'HIGH':     '🟠 HIGH',
        'CRITICAL': '🔴 CRITICAL',
    }


    # ══════════════════════════════════════════════════
    #  بازطراحی کامل Audit Log — مدل داده غنی
    # ══════════════════════════════════════════════════
    #
    # طبق استاندارد جدید، هر لاگ شامل:
    #   id, timestamp, severity, module, action,
    #   actor{id,name,role}, target{type,id,label},
    #   details, changes[before/after], metadata, correlation_id, tags
    #
    # ماژول‌ها همیشه به انگلیسی در کد ذخیره می‌شوند (پایدار برای
    # کوئری/فیلتر) و فقط هنگام نمایش به فارسی ترجمه می‌شوند.

    MODULE_LABELS_FA = {
        'Users':         'کاربران',
        'Roles':         'نقش‌ها',
        'Settings':      'تنظیمات',
        'Questions':     'سوالات',
        'QBank':         'بانک سوال',
        'Content':       'محتوا',
        'Reference':     'رفرنس',
        'Schedules':     'برنامه کلاسی',
        'Tickets':       'تیکت‌ها',
        'Reports':       'گزارش‌ها',
        'Notifications': 'اعلان‌ها',
        'Backup':        'بکاپ',
        'System':        'سیستم',
        'Auth':          'ورود/خروج',
        'Subscription':  'اشتراک',
        'Grades':        'نمرات',
        'AI':            'هوش مصنوعی',
        'Payment':       'پرداخت',
        'Security':      'امنیت',
        'Job':           'Job',
        'Integration':   'یکپارچه‌سازی',
        'Database':      'دیتابیس',
        'WebAdmin':      'پنل وب',
        'Profile':       'پروفایل',
        'Ring':          'رینگ',
        'ring':          'رینگ',
    }


    async def log_action(self, actor_id: int, actor_name: str, actor_role: str,
                          action: str, module: str, category: str = 'admin',
                          severity: str = 'INFO', target_id: str = '',
                          target_type: str = '', target_label: str = '',
                          before: dict = None, after: dict = None,
                          details: str = '', tags: list = None,
                          correlation_id: str = None,
                          # 🚀 Audit Refactor — فیلدهای جدید §5 (همه اختیاری برای Backward Compat)
                          event_id: str = None, actor_type: str = None,
                          source: str = None, channel: str = None,
                          request_id: str = None, ip: str = None, user_agent: str = None,
                          metadata: dict = None, result: str = None, status: str = None,
                          error_code: str = None, error_message: str = None,
                          target_context: dict = None) -> str:
        """
        FIX بازطراحی کامل — مدل داده غنی طبق سند:
        actor شامل نقش، target شامل برچسب قابل‌فهم (نه فقط ObjectId خام)،
        changes به‌صورت فهرست فیلد:قبل:بعد، correlation_id برای ردیابی
        عملیات چندمرحله‌ای (مثلاً ارسال همگانی)، و tags برای جستجو.

        🚀 Refactor 2026-09: ذخیره‌ی کامل Schema استاندارد §5 — event_id,
        timestamp_tehran, actor_type, source/channel, request_id,
        correlation_id, before/after sanitize, result/status, ip/ua,
        metadata, error_code/message, telegram_delivery_status.

        target_label: نام/عنوان قابل‌فهم هدف (مثلاً نام کاربر یا متن سوال)
        — این چیزی است که در پیام لاگ به‌جای ObjectId خام نشان داده می‌شود.
        """
        # 🚀 استفاده از audit.py مرکزی برای Sanitization + Schema یکسان
        # وارد کردن تنبل برای جلوگیری از Circular Import
        try:
            from audit import build_audit_event, sanitize_audit_data
            # اگر event_id از قبل داده شده، ترجیح می‌دهیم همان بماند (idempotency §43)
            # وگرنه audit.py یکی می‌سازد
            ev = build_audit_event(
                event_id=event_id,
                actor_id=actor_id, actor_name=actor_name, actor_role=actor_role,
                actor_type=actor_type or "USER",
                module=module, category=category, action=action,
                severity=severity, target_type=target_type, target_id=target_id,
                target_label=target_label, before=before, after=after,
                result=result or "SUCCESS", status=status or "SUCCESS",
                source=source or "bot", channel=channel or "telegram",
                request_id=request_id, correlation_id=correlation_id,
                ip=ip, user_agent=user_agent, metadata=metadata,
                error_code=error_code, error_message=error_message,
                tags=tags, details=details, target_context=target_context,
            )
            # build_audit_event قبلاً sanitize کرده؛ اینجا مستقیم ذخیره می‌کنیم
            doc = ev
            # audit_logs insert — event_id یکتا (§43)
            # اگر event_id تکراری باشد (duplicate delivery)، به‌جای خطا، موجود را برگردان
            try:
                r = await self.audit_logs.insert_one(doc)
            except Exception as e:
                # DuplicateKeyError روی event_id → idempotent (§43)
                if "duplicate" in str(e).lower() and "event_id" in str(e).lower():
                    existing = await self.audit_logs.find_one({"event_id": doc["event_id"]})
                    if existing:
                        return str(existing.get("_id") or doc["event_id"])
                raise
            # ── Unified Delivery: هر لاگ مدیریتی/محتوایی به تلگرام هم می‌رود (یک الگوی واحد) ──
            # این enqueue ثانویه است و هرگز persistence را نمی‌شکند (fail-open).
            try:
                from audit import enqueue_telegram_delivery
                # group_key را از audit.get_category_meta می‌گیریم تا الگو یکسان بماند
                try:
                    from audit import get_category_meta
                    gkey, _, _ = get_category_meta(doc.get("category", "system"))
                except Exception:
                    gkey = "log_group_admin" if doc.get("category") == "admin" else "log_group_content" if doc.get("category") == "content" else "log_group_admin"
                chat_id = await self.get_setting(gkey, None)
                # fallback admin اگر content group تنظیم نشده
                if not chat_id and gkey != "log_group_admin":
                    chat_id = await self.get_setting("log_group_admin", None)
                if chat_id:
                    # _id را برای delivery tracking ست کن
                    doc["_id"] = r.inserted_id
                    await enqueue_telegram_delivery(doc, chat_id)
            except Exception:
                pass  # delivery هرگز business را نمی‌شکند (§13)
            # 🚨 §۸۹ — هشدار فعال. داخل try تا هیچ‌وقت مسیر اصلی را نشکند:
            if doc.get("severity") in self.ALERT_SEVERITIES:
                try:
                    await self.dispatch_critical_alert({**doc, "_id": r.inserted_id})
                except Exception:
                    pass
            return str(r.inserted_id)
        except ImportError:
            # Fallback مسیر قدیمی (اگر audit.py در دسترس نبود — نباید رخ دهد)
            pass
        # Legacy fallback (حفظ رفتار قدیمی برای تست‌های بدون audit.py)
        changes = []
        if before or after:
            before = before or {}
            after = after or {}
            for key in (list(after) + [k for k in before if k not in after]):
                changes.append({
                    'field': key,
                    'before': before.get(key, '—'),
                    'after':  after.get(key, '—'),
                })
        # Sanitize fallback
        try:
            from audit import sanitize_audit_data as _san
            before = _san(before) if before else before
            after = _san(after) if after else after
            details = _san(details) if details else details
        except Exception:
            pass
        import uuid as _uuid
        # fallback Tehran time — یکپارچه شمسی حتی در مسیر قدیمی
        try:
            from time_utils import format_datetime_fa
            _now = now_utc()
            _ts_tehran = _now.astimezone(TEHRAN).isoformat()
            _ts_str = format_datetime_fa(_now, long=True)
        except Exception:
            _ts_tehran = utc_now_iso()
            _ts_str = _ts_tehran
        doc = {
            'event_id': event_id or _uuid.uuid4().hex,
            'timestamp':      utc_now_iso(),
            'timestamp_tehran': _ts_tehran,
            'timestamp_tehran_str': _ts_str,
            'severity':       severity,
            'module':         module,
            'category':       category,
            'action':         action,
            'actor': {
                'id':   actor_id,
                'name': actor_name,
                'role': actor_role or 'نامشخص',
                'type': actor_type or 'USER',
            },
            'target': {
                'type':  target_type,
                'id':    target_id,
                'label': target_label,
                'context': target_context or {},
            },
            'details':        details,
            'changes':        changes,
            'before': before,
            'after': after,
            'tags':           tags or [],
            'correlation_id': correlation_id or current_request_id.get(),
            'request_id': request_id or current_request_id.get(),
            'source': source or 'bot',
            'channel': channel or 'telegram',
            'result': result or 'SUCCESS',
            'status': status or 'SUCCESS',
            'metadata': metadata or {},
            'error_code': error_code,
            'error_message': error_message,
            'telegram_delivery_status': 'PENDING',
            'audit_version': 2,
        }
        r = await self.audit_logs.insert_one(doc)
        if severity in self.ALERT_SEVERITIES:
            try:
                await self.dispatch_critical_alert({**doc, '_id': r.inserted_id})
            except Exception:
                pass
        return str(r.inserted_id)


    # ══════════════════════════════════════════════════════════
    #  🚨 §۸۹ — هشدار فعال روی رویدادهای بحرانی
    # ══════════════════════════════════════════════════════════
    #  رویدادهای CRITICAL ثبت می‌شدند ولی کسی مطلع نمی‌شد مگر
    #  تصادفی صفحه‌ی Audit را باز کند. حالا به دارندگانِ `audit.view`
    #  اعلان می‌رود — از همان inbox موجود، با group_key تا طوفانِ
    #  اعلان راه نیفتد.

    ALERT_SEVERITIES = ('CRITICAL',)

    async def alert_recipients(self) -> list:
        """دارندگان `audit.view` + مالک، بدون تکرار."""
        owner = int(os.getenv('ADMIN_ID', '0'))
        uids = set()
        if owner:
            uids.add(owner)
        try:
            uids.update(await self.perm_holders('audit.view', exclude_owner=True))
        except Exception:
            pass          # هشدار هرگز نباید مسیر اصلی را بشکند
        return sorted(uids)

    async def dispatch_critical_alert(self, log: dict) -> int:
        """اعلان برای یک رویداد بحرانی. خروجی: تعداد گیرندگان.

        عمداً «بهترین تلاش» است: اگر ارسال شکست بخورد، عملیاتی که
        باعثش شده *نباید* برگردد — لاگ از قبل ثبت شده است.
        """
        if (log or {}).get('severity') not in self.ALERT_SEVERITIES:
            return 0
        actor = (log.get('actor') or {})
        target = (log.get('target') or {})
        title = f"🚨 {log.get('action', 'رویداد بحرانی')}"
        body = (f"{actor.get('name', 'نامشخص')} ({actor.get('role', '—')}) — "
                f"{target.get('label') or target.get('id') or '—'}")
        sent = 0
        for uid in await self.alert_recipients():
            if uid == actor.get('id'):
                continue          # کسی که خودش انجامش داده، خبر دارد
            try:
                await self.inbox_add(
                    uid, 'security', title, body, link='/audit',
                    group_key=f"crit:{log.get('module', '')}",
                    group_title='رویدادهای بحرانی')
                sent += 1
            except Exception:
                continue
        return sent


    # ══════════════════════════════════════════════════════════
    #  ↩️ §۸۸ — بازگردانی تغییرات از روی حسابرسی (Undo)
    # ══════════════════════════════════════════════════════════
    #  داده‌ی لازم (before/after) از قبل ثبت می‌شد و هیچ استفاده‌ای
    #  نداشت. اینجا فقط از آن استفاده می‌کنیم.
    #
    #  ⚠️ عمداً *فهرست سفید* است، نه undoی عمومی. برگرداندنِ کورکورانه‌ی
    #  هر رویدادی فاجعه‌بار است: حذف‌ها داده‌ی واقعی را برنمی‌گردانند،
    #  عملیات مالی باید از مسیر خودش برگردد، و پیام‌های ارسال‌شده
    #  بازگشت‌پذیر نیستند. فقط تغییرِ فیلدهای سادهٔ کاربر پشتیبانی می‌شود.
    UNDOABLE = {
        'users': {
            'collection': 'users',
            'key': 'user_id',
            'fields': {'approved', 'suspended', 'intake', 'group_code',
                       'name', 'blocked'},
        },
    }

    def undo_plan(self, log: dict) -> dict:
        """آیا این رویداد قابل بازگردانی است؟ اگر آری، دقیقاً چه چیزی.

        تابع خالص و بدون نوشتن — همان چیزی که UI برای نمایش دکمه و
        سرور برای اجرا استفاده می‌کند (یک منبع، بدون واگرایی).
        """
        target = (log or {}).get('target') or {}
        spec = self.UNDOABLE.get(target.get('type'))
        if not spec:
            return {'undoable': False, 'reason': 'نوع این رویداد بازگردانی‌پذیر نیست'}
        changes = [c for c in ((log or {}).get('changes') or [])
                   if c.get('field') in spec['fields']]
        if not changes:
            return {'undoable': False, 'reason': 'این رویداد تغییر فیلدِ قابل بازگردانی ندارد'}
        if any(c.get('before') == '—' for c in changes):
            return {'undoable': False, 'reason': 'مقدار پیشین ثبت نشده است'}
        if (log or {}).get('undone_at'):
            return {'undoable': False, 'reason': 'این رویداد قبلاً بازگردانده شده است'}
        try:
            key_value = int(target.get('id'))
        except (TypeError, ValueError):
            return {'undoable': False, 'reason': 'شناسه‌ی هدف معتبر نیست'}
        return {
            'undoable': True,
            'collection': spec['collection'], 'key': spec['key'],
            'key_value': key_value,
            'restore': {c['field']: c.get('before') for c in changes},
            'current_expected': {c['field']: c.get('after') for c in changes},
        }

    async def undo_audit_log(self, log_id: str, actor_id: int) -> dict:
        """اجرای بازگردانی — با محافظت در برابر تغییرِ هم‌زمان.

        اگر مقدار فعلی با `after`ِ ثبت‌شده نخواند، یعنی کسی بعد از آن
        رویداد چیزی را عوض کرده و بازگردانی، کارِ او را بی‌صدا پاک
        می‌کند. در آن حالت ۴۰۹ می‌دهیم، نه بازنویسی.
        """
        from bson import ObjectId
        try:
            oid = ObjectId(log_id)
        except Exception:
            return {'ok': False, 'error': 'شناسه‌ی رویداد معتبر نیست', 'status': 422}
        log = await self.audit_logs.find_one({'_id': oid})
        if not log:
            return {'ok': False, 'error': 'رویداد پیدا نشد', 'status': 404}
        plan = self.undo_plan(log)
        if not plan['undoable']:
            return {'ok': False, 'error': plan['reason'], 'status': 409}

        collection = getattr(self, plan['collection'])
        filt = {plan['key']: plan['key_value']}
        current = await collection.find_one(filt)
        if not current:
            return {'ok': False, 'error': 'هدف دیگر وجود ندارد', 'status': 404}
        drifted = [f for f, expected in plan['current_expected'].items()
                   if current.get(f) != expected]
        if drifted:
            return {'ok': False, 'status': 409,
                    'error': f"مقدار فعلی «{'، '.join(drifted)}» با زمان ثبت رویداد "
                             "فرق دارد؛ بازگردانی تغییرِ بعدی را پاک می‌کند"}

        await collection.update_one(filt, {'$set': plan['restore']})
        # علامتِ یک‌بارمصرف: جلوی undoی دوباره و حلقه‌ی undo/redo را می‌گیرد.
        await self.audit_logs.update_one(
            {'_id': oid, 'undone_at': {'$exists': False}},
            {'$set': {'undone_at': utc_now_iso(), 'undone_by': int(actor_id)}})
        return {'ok': True, 'restored': plan['restore'],
                'target_id': plan['key_value']}


    async def get_recent_logs(self, category: str = None, min_severity: str = None,
                               module: str = None, limit: int = 30) -> list:
        q = {}
        if category:
            q['category'] = category
        if min_severity:
            order = ['INFO', 'WARNING', 'HIGH', 'CRITICAL']
            idx = order.index(min_severity) if min_severity in order else 0
            q['severity'] = {'$in': order[idx:]}
        if module:
            q['module'] = module
        return await self.audit_logs.find(q).sort('timestamp', -1).to_list(limit)


    async def get_actor_role_label(self, uid: int) -> str:
        """
        FIX طبق سند: در ۹۶٪ لاگ‌های قبلی نقش فرستنده مشخص نبود.
        این متد یک‌جا و یکدست نقش واقعی هر کاربر را برمی‌گرداند —
        مدیر ارشد، یا یکی از نقش‌های فرعی، بدون ایموجی (برای متن لاگ).
        """
        if uid == int(os.getenv('ADMIN_ID', '0')):
            return 'مدیر ارشد'
        role_doc = await self.get_admin_role(uid)
        if role_doc:
            label = self.ROLE_LABELS.get(role_doc.get('role', ''), '')
            # حذف ایموجی و پرانتز برای متن لاگ تمیز
            import re
            clean = re.sub(r'^[^\w\u0600-\u06FF]+', '', label).strip()
            return clean or role_doc.get('role', 'نامشخص')
        user = await self.get_user(uid)
        if user and user.get('role') == 'content_admin':
            return 'ادمین ارشد محتوا'
        return 'دانشجو'


    async def get_logs_by_correlation(self, correlation_id: str) -> list:
        """همه‌ی لاگ‌های یک عملیات چندمرحله‌ای (مثل شروع/پیشرفت/پایان broadcast)"""
        return await self.audit_logs.find(
            {'correlation_id': correlation_id}
        ).sort('timestamp', 1).to_list(100)


    async def search_logs_by_tag(self, tag: str, limit: int = 30) -> list:
        """جستجوی لاگ بر اساس تگ — مثلاً 'کاربران' یا 'حذف'"""
        return await self.audit_logs.find(
            {'tags': tag}
        ).sort('timestamp', -1).to_list(limit)

    # ══════════════════════════════════════════════════
    #  🚀 Audit Searchability & Health — §38 §52 §39
    # ══════════════════════════════════════════════════
    async def search_audit_logs(self, *, event_id: str = None, actor_id: int = None,
                                 module: str = None, action: str = None,
                                 category: str = None, severity: str = None,
                                 target_id: str = None, target_type: str = None,
                                 correlation_id: str = None, request_id: str = None,
                                 status: str = None, date_from: str = None,
                                 date_to: str = None, limit: int = 50,
                                 sort_dir: int = -1) -> list:
        """جستجوی جامع Audit — قابل Query بر اساس تمام فیلدهای §38."""
        q: dict = {}
        if event_id: q["event_id"] = event_id.strip()
        if actor_id is not None: q["actor.id"] = int(actor_id)
        if module: q["module"] = module
        if action: q["action"] = action
        if category: q["category"] = category
        if severity: q["severity"] = severity
        if target_id: q["target.id"] = target_id.strip()
        if target_type: q["target.type"] = target_type
        if correlation_id: q["correlation_id"] = correlation_id.strip()
        if request_id: q["request_id"] = request_id.strip()
        if status: q["status"] = status
        if date_from or date_to:
            ts_q = {}
            if date_from: ts_q["$gte"] = date_from
            if date_to: ts_q["$lte"] = date_to
            q["timestamp"] = ts_q
        return await self.audit_logs.find(q).sort("timestamp", sort_dir).limit(limit).to_list(limit)

    async def get_audit_by_event_id(self, event_id: str) -> dict | None:
        return await self.audit_logs.find_one({"event_id": event_id.strip()})

    async def get_audit_health_metrics(self) -> dict:
        """§52 — Audit Health برای Admin/Monitoring"""
        try:
            import audit as _audit_mod
            health = await _audit_mod.get_audit_health()
            # enrich with DB counts
            health["total_logs"] = await self.audit_logs.count_documents({})
            health["recent_24h"] = await self.audit_logs.count_documents(
                {"timestamp": {"$gte": (now_utc() - timedelta(hours=24)).isoformat()}})
            return health
        except Exception as e:
            return {"error": str(e), "audit_persistence": "UNKNOWN"}

    async def audit_retention_cleanup(self, days: int = None) -> int:
        """§39 — Retention قابل تنظیم"""
        try:
            import audit as _audit_mod
            return await _audit_mod.apply_retention(days)
        except Exception:
            return 0

    async def get_audit_stats(self, days: int = 7) -> dict:
        """§36 — Observability aggregates (برای Dashboard)"""
        since = (now_utc() - timedelta(days=days)).isoformat()
        pipeline = [
            {"$match": {"timestamp": {"$gte": since}}},
            {"$group": {"_id": "$action", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 20},
        ]
        rows = await self.audit_logs.aggregate(pipeline).to_list(20)
        # تفکیک severity
        sev_rows = await self.audit_logs.aggregate([
            {"$match": {"timestamp": {"$gte": since}}},
            {"$group": {"_id": "$severity", "count": {"$sum": 1}}},
        ]).to_list(10)
        delivery_rows = await self.audit_logs.aggregate([
            {"$match": {"timestamp": {"$gte": since}}},
            {"$group": {"_id": "$telegram_delivery_status", "count": {"$sum": 1}}},
        ]).to_list(10)
        return {
            "top_actions": {r["_id"]: r["count"] for r in rows},
            "by_severity": {r["_id"]: r["count"] for r in sev_rows},
            "by_delivery": {r["_id"]: r["count"] for r in delivery_rows},
            "period_days": days,
        }


    # ══════════════════════════════════════════════════
    #  گزارش هفتگی/ماهانه خودکار
    # ══════════════════════════════════════════════════

    async def weekly_report_stats(self) -> dict:
        """آمار خلاصه برای گزارش دوره‌ای ادمین"""
        week_ago = (now_utc() - timedelta(days=7)).isoformat()

        new_users = await self.users.count_documents(
            {'registered_at': {'$gte': week_ago}}
        )
        active_users = await self.answers.distinct(
            'user_id', {'answered_at': {'$gte': week_ago}}
        ) if hasattr(self, 'answers') else []

        # FIX: پرطرفدارترین درس — بر اساس مجموع دانلود محتوای هر درس.
        # bs_content فیلد lesson مستقیم ندارد (فقط session_id) پس باید
        # session → lesson_id → lesson.name را در پایتون join بزنیم.
        top_lesson = None
        try:
            all_content  = await self.bs_content.find({}).to_list(5000)
            all_sessions = await self.bs_sessions.find({}).to_list(2000)
            all_lessons  = await self.bs_lessons.find({}).to_list(500)
            session_to_lesson = {str(s['_id']): s.get('lesson_id', '') for s in all_sessions}
            lesson_id_to_name = {str(l['_id']): l.get('name', '') for l in all_lessons}
            downloads_by_lesson: dict = {}
            for c in all_content:
                sid = c.get('session_id', '')
                lid = session_to_lesson.get(sid, '')
                lname = lesson_id_to_name.get(lid, '')
                if lname:
                    downloads_by_lesson[lname] = downloads_by_lesson.get(lname, 0) + c.get('downloads', 0)
            if downloads_by_lesson:
                top_lesson = max(downloads_by_lesson, key=downloads_by_lesson.get)
        except Exception as e:
            logger.debug(f"weekly_report_stats top_lesson error: {e}")

        open_tickets   = await self.tickets.count_documents({'status': 'open'})
        closed_week    = await self.tickets.count_documents(
            {'status': 'closed', 'closed_at': {'$gte': week_ago}}
        )
        total_tickets_week = await self.tickets.count_documents(
            {'created_at': {'$gte': week_ago}}
        )

        # کاربرانی که بیش از ۱۴ روز فعالیت نداشتند (احتمال غیرفعال شدن)
        inactive_cutoff = (now_utc() - timedelta(days=14)).isoformat()
        inactive_count = await self.users.count_documents({'approved': True, '$or': [
            {'last_active': {'$lt': inactive_cutoff}},
            {'last_active': {'$exists': False}, 'registered_at': {'$lt': inactive_cutoff}},
            {'last_active': None, 'registered_at': {'$lt': inactive_cutoff}},
            {'last_active': '', 'registered_at': {'$lt': inactive_cutoff}},
        ]})

        return {
            'new_users':          new_users,
            'active_users_count': len(set(active_users)),
            'top_lesson':         top_lesson or 'داده‌ای نیست',
            'open_tickets':       open_tickets,
            'closed_week':        closed_week,
            'total_tickets_week': total_tickets_week,
            'inactive_count':     inactive_count,
            'total_users':        await self.users.count_documents({'approved': True}),
        }



    # ══════════════════════════════════════════════════
    #  FIX جدید: لاگ وضعیت ارسال نوتیف‌ها (notif_runs)
    #  برای رفع نیاز: «بدون تکرار، بدون نقص، قابل retry،
    #  وضعیت ارسال در دیتابیس ذخیره شود»
    # ══════════════════════════════════════════════════

    # ══════════════════════════════════════════════════
    #  🔔 صندوق اعلان کاربر (مرکز اعلان مینی‌اپ) — موج ۴.۹۰
    #  قرارداد مرکزی: همه‌ی نویسنده‌ها (جاب‌های ربات، پنل‌های وب/بات)
    #  رویداد را با همین ساختار ثبت می‌کنند؛ مینی‌اپ فقط می‌خواند.
    #  body متنِ ساده (بدون HTML) است تا در هر سطحی امن نمایش داده شود.
    # ══════════════════════════════════════════════════


    # ══════════════════════════════════════════════════
    #  🧠 موج N1 — Notification Spine (منبع واحد رویدادها)
    #  هر ntype اینجا meta کامل دارد: دسته، آیکون، تُن،
    #  اولویت و کلید ترجیح کاربر. بات / API / FE فقط
    #  از همین ثبت‌نامه می‌خوانند — منطق موازی ممنوع.
    # ══════════════════════════════════════════════════

    # کاتالوگ دسته‌های ترجیح کاربر — (key, label, desc, default)
    # این لیست هم در صفحه‌ی مینی‌اپ هم در منوی بات نمایش می‌یابد.
    NOTIF_CATALOG = [
        ('resources',    '📚 منابع و جزوه‌ها',      'فایل‌های درسی علوم پایه و جزوه‌ها',           True),
        ('references',   '📖 رفرنس‌ها',             'آپدیت کتاب‌ها و خواندنی‌های رفرنس',            True),
        ('basic_sci',    '🩺 علوم پایه',            'جلسات و محتوای درس‌های علوم پایه',             True),
        ('qbank',        '❓ بانک سؤال',             'سؤال روزانه و وضعیت سؤال‌های پیشنهادی‌ات',    True),
        ('schedule',     '📅 برنامه‌ی هفتگی',       'کلاس جدید، جبرانی و تغییر زمان',               True),
        ('exams',        '📝 امتحان‌ها',            'یادآوری‌های رسمی امتحان',                      True),
        ('grades',       '📊 نمرات',                 'ثبت نمره‌ی جدید در کارنامه',                  True),
        ('tickets',      '🎫 پشتیبانی و تیکت',       'پاسخ‌ها و وضعیت گفت‌وگوی پشتیبانی',          True),
        ('subscription', '💳 اشتراک',                'فعال‌سازی، یادآوری پایان و وضعیت رسید',       True),
        ('discounts',    '🎁 تخفیف‌ها',              'پیشنهادها و کدهای تخفیف',                     True),
        ('ai',           '🤖 هوشیار',                'رویدادهای دستیار هوشمند',                     True),
        ('announcement', '📢 اطلاعیه‌ها',            'خبرها، پیام‌های آموزشی و اطلاعیه‌ها',         True),
        ('polls',        '🗳 نظرسنجی',               'نظرسنجی‌های رسمی',                            True),
        ('gamification', '🎮 بازی‌واری و رنک',       'ارتقای رنک/دیویژن، نشان‌ها و رقابت',          True),
        ('profile',      '👤 حساب',                  'تأیید حساب و رویدادهای پروفایل',              True),
        ('system',       '⚙️ سیستم',                 'سایر رویدادهای حساس حساب',                    True),
    ]


    # ntype → (category, icon, tone, priority, pref_key|None)
    # pref_key=None ⇒ مهار ترجیحی ندارد (همیشه DM هم می‌رود)
    NOTIF_TYPES = {
        # ── مدرسی/آموزشی ──
        'exam_reminder':    ('exams',        '📝', 'red',    'normal',   'exams'),
        'exam':             ('exams',        '📝', 'red',    'normal',   'exams'),
        'daily_question':   ('qbank',        '🧪', 'purple', 'low',      'qbank'),
        'new_resources':    ('resources',    '📚', 'green',  'normal',   'resources'),
        'new_references':   ('references',   '📖', 'purple', 'normal',   'references'),
        'new_basic_sci':    ('basic_sci',    '🩺', 'acc',    'normal',   'basic_sci'),
        'class':            ('schedule',     '🏫', 'blue',   'normal',   'schedule'),
        'makeup':           ('schedule',     '🔄', 'yellow', 'normal',   'schedule'),
        'schedule_change':  ('schedule',     '🔄', 'yellow', 'high',     'schedule'),
        'grade':            ('grades',       '📊', 'acc',    'critical', 'grades'),
        # ── پشتیبانی/اشتراک ──
        'ticket_created':   ('tickets',      '🎫', 'green',  'normal',   'tickets'),
        'ticket_reply':     ('tickets',      '📨', 'green',  'critical', 'tickets'),
        'ticket_closed':    ('tickets',      '✅', 'green',  'normal',   'tickets'),
        'ticket_reopened':  ('tickets',      '🔓', 'yellow', 'normal',   'tickets'),
        'sub_activated':    ('subscription', '💎', 'acc',    'critical', 'subscription'),
        'sub_expiring':     ('subscription', '⏳', 'yellow', 'high',     'subscription'),
        'sub_expired':      ('subscription', '⌛', 'red',    'critical', 'subscription'),
        'payment_rejected': ('subscription', '❌', 'red',    'high',     'subscription'),
        # ── حساب/اعلامیه ──
        'account':          ('profile',      '🎓', 'green',  'high',     'profile'),
        # 🎁 موج D1 — کمپین‌های تخفیف: دسته‌ی مجزا + مهار ترجیحی «تخفیف‌ها»
        'discount':         ('discounts',    '🎁', 'acc',    'normal',   'discounts'),
        'admin_dm':         ('announcement', '📩', 'blue',   'high',     'announcement'),
        'announcement':     ('announcement', '📢', 'blue',   'normal',   'announcement'),
        'edu_message':      ('announcement', '🎓', 'acc',    'low',      'announcement'),
        'general':          ('announcement', '🔔', 'blue',   'normal',   'announcement'),
        'question_approved':('qbank',        '✍️', 'green',  'high',     'qbank'),
        'question_rejected':('qbank',        '❕', 'yellow', 'normal',   'qbank'),
        'report_resolved':  ('announcement', '🩺', 'green',  'normal',   'announcement'),
        # ── خانواده‌ی پرستیژ (دسته‌ی واحد: gamification) ──
        'rank_up':          ('gamification', '🎉', 'acc',    'high',     'gamification'),
        'div_up':           ('gamification', '⭐', 'acc',    'normal',   'gamification'),
        'streak':           ('gamification', '🔥', 'red',    'low',      'gamification'),
        'demote':           ('gamification', '📉', 'yellow', 'normal',   'gamification'),
        'return':           ('gamification', '🫶', 'green',  'low',      'gamification'),
        'founder':          ('gamification', '🏛️', 'acc',    'high',     'gamification'),
        'achievement':      ('gamification', '🏅', 'purple', 'normal',   'gamification'),
        'global_first':     ('gamification', '🏆', 'yellow', 'high',     'gamification'),
        'weekly_champion':  ('gamification', '👑', 'yellow', 'high',     'gamification'),
        'challenge':        ('gamification', '⚔️', 'red',    'normal',   'gamification'),
        'challenge_win':    ('gamification', '⚔️', 'green',  'high',     'gamification'),
        'challenge_fail':   ('gamification', '💪', 'yellow', 'normal',   'gamification'),
    }


    _NOTIF_META_FALLBACK = ('system', '🔔', 'blue', 'normal', 'general')


    _INBOX_GROUP_WINDOW_H = 72   # پنجره‌ی Smart Grouping


    def notif_type_meta(self, ntype: str) -> dict:
        """♻️ meta کامل یک ntype — خروجی ثابت-شکل حتی برای نوع ناشناخته"""
        cat, icon, tone, prio, pref = self.NOTIF_TYPES.get(
            ntype, self._NOTIF_META_FALLBACK)
        return {'category': cat, 'icon': icon, 'tone': tone,
                'priority': prio, 'pref': pref}


    async def notif_catalog(self) -> list:
        """📋 فهرست دسته‌ها برای صفحه‌ی ترجیحات (همراه پیش‌فرض جاری پنل)"""
        defaults = await self.get_notif_defaults()
        return [{'key': k, 'label': l, 'desc': d,
                 'default': bool(defaults.get(k, d))}
                for k, l, d, _default in self.NOTIF_CATALOG]


    def notif_pref_on(self, settings: dict, key, defaults: dict = None) -> bool:
        """🎚 آیا این دسته برای کاربر روشن است؟ (کلید قدیمی خودکار canonical می‌شود)

        key=None یعنی نوتیف مهار ندارد ⇒ همیشه True (Critical مسیر)."""
        if key is None:
            return True
        canon = self.PREF_ALIAS.get(key, key)
        if canon is None:
            return True
        settings = settings or {}
        if canon in settings:
            return bool(settings[canon])
        if key in settings:          # مقدار قدیمی دقیق ذخیره‌شده
            return bool(settings[key])
        base = defaults or {}
        if canon in base:
            return bool(base[canon])
        return bool(base.get(key, True))


    _INBOX_KEEP = 100  # سقف نگه‌داری اعلان برای هر کاربر


    async def inbox_add(self, user_id: int, ntype: str, title: str,
                        body: str, link: str = None, *, payload: dict = None,
                        group_key: str = None, group_title: str = None) -> None:
        """ثبت یک اعلان برای یک کاربر + هرسِ نگه‌داری (قدیمی‌تر از KEEP)

        🧠 موج N1 — اسکیمای غنی (category/icon/tone/priority/pinned/count)
        از ثبت‌نامه خوانده می‌شود، اما فیلدهای پایه سازگار-عقبرو می‌مانند.
        group_key ⇒ Smart Grouping: اگر سند باز هم‌کلید در پنجره‌ی اخیر
        باشد، به‌جای درج جدید همان تقویت می‌شود (count+۱، متن تازه،
        خوانده‌نشده مجدد) — الگوی «۳ منبع جدید به جای ۳ اعلان»."""
        try:
            uid = int(user_id)
            meta = self.notif_type_meta(ntype)
            now_iso = utc_now_iso()

            # ♻ Smart Grouping — ادغام در سند باز هم‌کلید
            if group_key:
                cutoff = (now_utc() - timedelta(
                    hours=self._INBOX_GROUP_WINDOW_H)).isoformat()
                prev = await self.user_notifs.find_one({
                    'user_id': uid, 'group_key': group_key,
                    'created_at': {'$gte': cutoff}})
                if prev:
                    cnt = int(prev.get('count') or 1) + 1
                    if group_title:
                        new_title = group_title.format(count=cnt)[:160]
                    elif '{count}' in title:
                        new_title = title.format(count=cnt)[:160]
                    else:
                        new_title = str(title)[:160]
                    await self.user_notifs.update_one({'_id': prev['_id']}, {
                        '$set': {
                            'type': ntype, 'title': new_title,
                            'body': str(body)[:900],
                            'link': link or prev.get('link'),
                            'category': meta['category'],
                            'icon': meta['icon'], 'tone': meta['tone'],
                            'priority': meta['priority'],
                            'read': False, 'created_at': now_iso,
                        },
                        '$inc': {'count': 1},
                    })
                    await self._inbox_prune(uid)
                    return

            await self.user_notifs.insert_one({
                'user_id':    uid,
                'type':       ntype,
                'title':      str(title)[:160],
                'body':       str(body)[:900],
                'link':       link or None,
                # 🧠 فیلدهای غنی — FE برای فیلتر/اولویت/pin از آن‌ها می‌خواند
                'category':   meta['category'],
                'icon':       meta['icon'],
                'tone':       meta['tone'],
                'priority':   meta['priority'],
                'pinned':     False,
                'count':      1,
                'payload':    payload or None,
                'group_key':  group_key or None,
                'read':       False,
                'created_at': now_iso,
            })
            await self._inbox_prune(uid)
        except Exception as e:
            # اعلان نباید مسیر اصلی رویداد (ارسال/ثبت) را بشکند
            logger.warning(f"inbox_add failed for {user_id}: {e}")


    async def _inbox_prune(self, uid: int) -> None:
        """🧹 هرس محافظ — قدیمی‌تر از سقف KEEP حذف می‌شود (سندی که
        pinned است، هرگز هرس نمی‌شود تا کاربر بتواند مهم‌ها را سنجاق کند)"""
        try:
            count = await self.user_notifs.count_documents({'user_id': int(uid)})
            if count > self._INBOX_KEEP:
                old = self.user_notifs.find(
                    {'user_id': int(uid), 'pinned': {'$ne': True}}
                ).sort('created_at', -1).skip(self._INBOX_KEEP).limit(200)
                old_ids = [d['_id'] async for d in old]
                if old_ids:
                    await self.user_notifs.delete_many({'_id': {'$in': old_ids}})
        except Exception:
            pass



    async def notify_user(self, uid, ntype: str, *, title: str, body: str,
                          link: str = None, dm: str = None,
                          payload: dict = None, group_key: str = None,
                          group_title: str = None) -> dict:
        """🧠 موج N1 — Entry واحد رویدادهای کاربرمحور.

        یک فراخوانی ⇒ دو مسیر همگام (Source of Truth = Inbox):
          ۱) ثبت کامل در Inbox (همیشه — آرشیو به‌ترتیب-categorised،
             با meta ثابت و قابلیت pin/group/count).
          ۲) اگر dm داده شود: قرار در صف DM ربات (با WebApp Deep Link
             خودکار از سوی job مصرف‌کننده)... مگر ترجیح کاربر دسته را
             خاموش کرده باشد (Criticalها هرگز مهار نمی‌شوند).

        برمی‌گرداند {'inbox': True, 'dm': bool} تا تست/جیاب رفتار را پایش کند."""
        uid = int(uid)
        meta = self.notif_type_meta(ntype)
        await self.inbox_add(uid, ntype, title, body, link,
                             payload=payload, group_key=group_key,
                             group_title=group_title)

        dm_queued = False
        if dm is not None:
            allowed = True
            pref = meta['pref']
            if pref and meta['priority'] != 'critical':
                try:
                    user = await self.get_user(uid)
                    settings = (user or {}).get('notification_settings', {})
                    defaults = await self.get_notif_defaults()
                    allowed = self.notif_pref_on(settings, pref, defaults)
                except Exception:
                    allowed = True
            if allowed:
                try:
                    await self.bot_notifs.insert_one({
                        'type':       f'event:{ntype}',
                        'chat_id':    uid,
                        'text':       dm,
                        'link':       link or None,  # 🧩 ⇒ دکمه‌ی WebApp
                        'sent':       False,
                        'created_at': utc_now_iso(),
                    })
                    dm_queued = True
                except Exception as e:
                    # صف DM اشکال بخورد، آرشیو Inbox کماکان کامل است
                    logger.warning(f"notify_user dm queue failed for {uid}: {e}")
        return {'inbox': True, 'dm': dm_queued}


    async def inbox_add_many(self, docs: list) -> None:
        """درج گروهی برای اعلان‌های همگانی (هر دیکت: user_id/type/title/body/link)"""
        if not docs:
            return
        try:
            now_iso = utc_now_iso()
            rows = []
            for d in docs:
                meta = self.notif_type_meta(d['type'])
                rows.append({
                    'user_id':    int(d['user_id']),
                    'type':       d['type'],
                    'title':      str(d['title'])[:160],
                    'body':       str(d.get('body', ''))[:900],
                    'link':       d.get('link') or None,
                    'category':   meta['category'],
                    'icon':       meta['icon'],
                    'tone':       meta['tone'],
                    'priority':   meta['priority'],
                    'pinned':     False,
                    'count':      1,
                    'payload':    d.get('payload') or None,
                    'group_key':  d.get('group_key') or None,
                    'read':       False,
                    'created_at': now_iso,
                })
            # تکه‌تکه تا سقف BSON معقول رعایت شود
            for i in range(0, len(rows), 500):
                await self.user_notifs.insert_many(rows[i:i + 500], ordered=False)
        except Exception as e:
            logger.warning(f"inbox_add_many failed ({len(docs)} docs): {e}")


    async def inbox_list(self, user_id: int, limit: int = 60,
                         category: str = None, q: str = None,
                         unread_only: bool = False) -> dict:
        """فهرست اعلان‌های کاربر + شمارش خوانده‌نشده (یک پاسخ برای صفحه و بج)

        🧠 موج N1 — خروجی غنی (category/icon/tone/priority/pinned/count)
        با سازگاری کامل (کلیدهای قدیمی دست‌نخورده) + فیلتر اختیاری
        category/q/unread که هم کلاینت هم سرور می‌تواند بدهد. ترتیب:
        پین‌شده‌ها بالاتر، سپس جدیدترین."""
        uid = int(user_id)
        cursor = (self.user_notifs.find({'user_id': uid})
                  .sort('created_at', -1).limit(400))
        need_q = (q or '').strip().lower()
        items = []
        async for d in cursor:
            meta = self.notif_type_meta(d.get('type', 'general'))
            item = {
                'id':         str(d['_id']),
                'type':       d.get('type', 'general'),
                'title':      d.get('title', ''),
                'body':       d.get('body', ''),
                'link':       d.get('link'),
                'read':       bool(d.get('read', False)),
                'created_at': d.get('created_at', ''),
                # 🧠 فیلدهای غنی — نقص اسناد قدیمی با registry پر می‌شود
                'category':   d.get('category') or meta['category'],
                'icon':       d.get('icon') or meta['icon'],
                'tone':       d.get('tone') or meta['tone'],
                'priority':   d.get('priority') or meta['priority'],
                'pinned':     bool(d.get('pinned', False)),
                'count':      int(d.get('count') or 1),
            }
            if category and item['category'] != category:
                continue
            if unread_only and item['read']:
                continue
            if need_q and need_q not in (
                    (item['title'] + ' ' + item['body']).lower()):
                continue
            items.append(item)
        items.sort(key=lambda i: i['created_at'], reverse=True)
        # 📌 پین‌شده‌ها مطلقاً بالای لیست (دسته‌ی زمانی در FE گروه‌بندی می‌شود)
        pinned   = [i for i in items if i['pinned']]
        unpinned = [i for i in items if not i['pinned']]
        items = (pinned + unpinned)[:limit]
        unread = await self.user_notifs.count_documents({'user_id': uid, 'read': False})
        return {'items': items, 'unread': unread}


    async def inbox_unread_count(self, user_id: int) -> int:
        """🔢 شمارش سبک خوانده‌نشده (بدون لفظ آیتم‌ها) — برای بج سبک"""
        try:
            return await self.user_notifs.count_documents(
                {'user_id': int(user_id), 'read': False})
        except Exception:
            return 0


    async def inbox_pin(self, user_id: int, nid: str, pinned: bool) -> bool:
        """📌 سنجاق کردن یک اعلان (پین‌شده‌ها بالاتر و مصون از هرس)"""
        try:
            r = await self.user_notifs.update_one(
                {'_id': ObjectId(str(nid)), 'user_id': int(user_id)},
                {'$set': {'pinned': bool(pinned)}})
            return bool(getattr(r, 'modified_count', 0) or
                        getattr(r, 'matched_count', 0))
        except Exception:
            return False


    async def inbox_mark_read(self, user_id: int, ids: list = None) -> int:
        """علامت خوانده‌شدن — ids=None یعنی همه؛ خروجی: شمارش خوانده‌نشده‌ی باقی‌مانده"""
        uid = int(user_id)
        flt = {'user_id': uid, 'read': False}
        if ids:
            obj_ids = []
            for x in ids:
                try:
                    obj_ids.append(ObjectId(str(x)))
                except Exception:
                    pass
            if not obj_ids:
                return await self.user_notifs.count_documents({'user_id': uid, 'read': False})
            flt['_id'] = {'$in': obj_ids}
        await self.user_notifs.update_many(flt, {'$set': {'read': True}})
        return await self.user_notifs.count_documents({'user_id': uid, 'read': False})


    async def inbox_delete(self, user_id: int, nid: str) -> bool:
        """حذف یک اعلانِ خودِ کاربر (مالکیت با user_id تضمین می‌شود)"""
        try:
            r = await self.user_notifs.delete_one({
                '_id': ObjectId(str(nid)), 'user_id': int(user_id)})
            return r.deleted_count > 0
        except Exception:
            return False


    async def notif_run_start(self, job_name: str) -> str:
        """ثبت شروع یک اجرای job — برمی‌گرداند run_id برای ادامه ثبت"""
        r = await self.notif_runs.insert_one({
            'job_name':  job_name,
            'started_at': utc_now_iso(),
            'status':    'running',
            'sent':      0,
            'failed':    0,
            'total':     0,
            'finished_at': None,
            'correlation_id': current_request_id.get(),
        })
        return str(r.inserted_id)


    async def notif_run_finish(self, run_id: str, sent: int, failed: int, total: int,
                                status: str = 'completed', error: str = ''):
        try:
            await self.notif_runs.update_one(
                {'_id': ObjectId(run_id)},
                {'$set': {
                    'sent': sent, 'failed': failed, 'total': total,
                    'status': status, 'error': error,
                    'finished_at': utc_now_iso(),
                }}
            )
        except Exception:
            pass


    async def get_recent_notif_runs(self, job_name: str = None, limit: int = 15) -> list:
        q = {'job_name': job_name} if job_name else {}
        return await self.notif_runs.find(q).sort('started_at', -1).to_list(limit)


    async def get_failed_notif_targets(self, run_id: str) -> list:
        """کاربرانی که ارسال برایشان fail شده — برای retry دستی"""
        doc = await self.notif_runs.find_one({'_id': ObjectId(run_id)})
        return doc.get('failed_user_ids', []) if doc else []


    async def notif_run_add_failed(self, run_id: str, user_ids: list):
        try:
            await self.notif_runs.update_one(
                {'_id': ObjectId(run_id)},
                {'$set': {'failed_user_ids': user_ids}}
            )
        except Exception:
            pass


    async def notif_run_add_failed_detailed(self, run_id: str, records: list):
        """
        FIX جدید: برای job هایی که در یک اجرا چند پیام متفاوت
        می‌فرستند (مثل یادآوری چند امتحان مختلف در یک اجرا)، هر کاربر
        ناموفق به‌همراه متن دقیق همان پیامی که برایش در نظر گرفته شده
        بود ذخیره می‌شود — نه فقط آیدی خام — تا «تلاش مجدد» بتواند
        محتوای درست را برایش بفرستد (نه یک پیام کلی جایگزین).
        records: [{'user_id': int, 'message': str}, ...]
        """
        try:
            await self.notif_runs.update_one(
                {'_id': ObjectId(run_id)},
                {'$set': {
                    'failed_user_ids': [r['user_id'] for r in records],
                    'failed_targets_detailed': records,
                }}
            )
        except Exception:
            pass


    async def get_failed_notif_details(self, run_id: str) -> list:
        """
        برمی‌گرداند [{'user_id':, 'message':}] برای retry دقیق.
        اگر جزئیات هر کاربر جداگانه ذخیره نشده باشد (job‌های تک‌پیامی
        مثل سوال روزانه/منابع جدید)، از متن عمومی ذخیره‌شده‌ی همان
        اجرا (notif_run_set_message) برای همه‌ی آیدی‌های ناموفق
        استفاده می‌شود.
        """
        try:
            doc = await self.notif_runs.find_one({'_id': ObjectId(run_id)})
        except Exception:
            return []
        if not doc:
            return []
        detailed = doc.get('failed_targets_detailed')
        if detailed:
            return detailed
        ids = doc.get('failed_user_ids', [])
        msg = doc.get('message_text')
        if ids and msg:
            return [{'user_id': uid, 'message': msg} for uid in ids]
        return []


    async def notif_run_set_message(self, run_id: str, text: str, parse_mode: str = 'HTML'):
        """
        FIX مهم: این متد قبلاً خط تعریفش (async def) به‌طور کامل از کد
        حذف شده بود — بدنه‌اش به‌عنوان کد مرده زیر get_failed_notif_details
        باقی مونده بود، پس هیچوقت واقعاً روی کلاس DB تعریف نمی‌شد و هر
        بار new_resources_notif_job صداش می‌زد با
        AttributeError: 'DB' object has no attribute 'notif_run_set_message'
        کرش می‌کرد و کل نوتیف منابع جدید لغو می‌شد.
        ذخیره‌ی متن واقعی پیامی که در این اجرا ارسال شده — تا دکمه‌ی
        «تلاش مجدد» در پنل ادمین بتواند همان محتوای واقعی (نه یک پیام
        کلی جایگزین) را دوباره برای کاربران fail‌شده بفرستد.
        """
        try:
            await self.notif_runs.update_one(
                {'_id': ObjectId(run_id)},
                {'$set': {'message_text': text, 'message_parse_mode': parse_mode}}
            )
        except Exception:
            pass


    async def get_notif_run_message(self, run_id: str) -> dict:
        """برمی‌گرداند {'text':..., 'parse_mode':...} یا None اگر ذخیره نشده باشد"""
        try:
            doc = await self.notif_runs.find_one({'_id': ObjectId(run_id)})
        except Exception:
            return None
        if not doc or not doc.get('message_text'):
            return None
        return {'text': doc['message_text'], 'parse_mode': doc.get('message_parse_mode', 'HTML')}



    # ══════════════════════════════════════════════════
    #  FIX جدید: قفل اجباری عضویت کانال (Force Subscribe)
    # ══════════════════════════════════════════════════

    async def get_required_channels(self) -> list:
        """لیست کانال‌هایی که عضویت در آن‌ها برای استفاده از ربات اجباری است"""
        doc = await self.settings.find_one({'_id': 'global'})
        return (doc or {}).get('required_channels', [])


    async def add_required_channel(self, channel_id: str, channel_title: str, invite_link: str = ''):
        channels = await self.get_required_channels()
        if any(c['id'] == channel_id for c in channels):
            return False
        channels.append({'id': channel_id, 'title': channel_title, 'invite_link': invite_link})
        await self.set_setting('required_channels', channels)
        return True


    async def remove_required_channel(self, channel_id: str):
        channels = await self.get_required_channels()
        channels = [c for c in channels if c['id'] != channel_id]
        await self.set_setting('required_channels', channels)



    # ══════════════════════════════════════════════════
    #  FIX جدید: تنظیمات پیش‌فرض اعلان‌ها برای کاربران جدید
    # ══════════════════════════════════════════════════

    DEFAULT_NOTIF_FALLBACK = {
        # 🧠 موج N1 — کاتالوگ یکپارچه‌ی دسته‌ها (کلیدهای Canonical)
        'resources': True, 'references': True, 'basic_sci': True,
        'qbank': True, 'schedule': True, 'exams': True, 'grades': True,
        'tickets': True, 'subscription': True, 'discounts': True,
        'ai': True, 'announcement': True, 'polls': True, 'profile': True,
        'gamification': True, 'system': True,
        # کلیدهای قدیمی (سازگاری — همان معنا، نگاشتی از طریق PREF_ALIAS)
        'new_resources': True, 'schedule_old_guard': None,
        'exam': True, 'makeup': True,
        'daily_question': False, 'edu_message': True, 'general': True,
        'grade_release': True, 'sub_expiry': True,
    }


    # 🧠 موج N1 — canonical کردن کلیدهای قدیمی ترجیح به دسته‌های جدید؛
    # هر جا pref خوانده/نوشته شود، از همین نگاشت عبور می‌کند تا کاربران
    # قدیمی با سندهای فعلی بدون مهاجرت دستی به دسته‌های تازه برسند.
    PREF_ALIAS = {
        'new_resources': 'resources',
        'exam':          'exams',
        'makeup':        'schedule',
        'daily_question': 'qbank',
        'edu_message':   'announcement',
        'general':       'announcement',
        'grade_release': 'grades',
        'sub_expiry':    'subscription',
        'schedule_old_guard': None,
    }


    async def get_notif_defaults(self) -> dict:
        """
        مقادیر پیش‌فرض فعلی اعلان‌ها — قابل تغییر از پنل ادمین.
        کاربران تازه ثبت‌نام‌شده همین مقادیر را به ارث می‌برند.
        """
        saved = await self.get_setting('notif_defaults', None)
        if saved is None:
            return dict(self.DEFAULT_NOTIF_FALLBACK)
        # ترکیب با fallback برای کلیدهای جدیدی که ممکن است بعداً اضافه شوند
        merged = dict(self.DEFAULT_NOTIF_FALLBACK)
        merged.update(saved)
        return merged


    async def set_notif_default(self, ntype: str, value: bool):
        defaults = await self.get_notif_defaults()
        defaults[ntype] = value
        await self.set_setting('notif_defaults', defaults)


    async def mark_user_blocked(self, uid: int, blocked: bool = True):
        """
        FIX (ارسال همگانی حرفه‌ای‌تر): وقتی ارسال پیام به کاربری با خطای
        Forbidden (کاربر ربات را بلاک کرده) مواجه می‌شود، این پرچم را
        ذخیره می‌کنیم — هم برای گزارش دقیق‌تر ارسال همگانی، هم برای
        اینکه دفعات بعد بلافاصله این کاربر را در آمار «مسدود» بشماریم.
        """
        try:
            await self.users.update_one(
                {'user_id': uid},
                {'$set': {'blocked_bot': blocked,
                          'blocked_bot_at': utc_now_iso()}}
            )
        except Exception:
            pass


    async def apply_notif_default_to_all_users(self, ntype: str, value: bool) -> int:
        """
        FIX (بخش سوم): وقتی ادمین یک تنظیم پیش‌فرض اعلان را تغییر می‌دهد،
        باید همان لحظه روی تمام کاربران (قدیمی و جدید، فعال و غیرفعال)
        اعمال شود — نه فقط روی کاربران تازه ثبت‌نامی.
        قبلاً چون هر کاربر هنگام ثبت‌نام یک کپی صریح از دیکشنری
        notification_settings می‌گرفت، تغییر بعدیِ پیش‌فرض هرگز به
        کاربران قبلی نمی‌رسید (چون s.get(key, ...) همیشه مقدار صریح
        قدیمی را برمی‌گرداند، نه پیش‌فرض جدید را).
        این متد با یک UPDATE سراسری، مقدار را برای همه کاربران هم‌زمان
        بازنویسی می‌کند.
        """
        try:
            result = await self.users.update_many(
                {}, {'$set': {f'notification_settings.{ntype}': value}}
            )
            return result.modified_count
        except Exception:
            logger.exception('apply_notif_default_to_all_users failed')
            raise


    async def update_notif_default(self, ntype: str, value: bool,
                                   apply_existing: bool = True) -> dict:
        """تنها domain operation تغییر default اعلان برای Bot و Web.

        default همیشه برای کاربران جدید ذخیره می‌شود. در صورت درخواست، همان
        مقدار با یک update_many واقعی روی کاربران فعلی هم اعمال می‌شود. اگر
        fan-out شکست بخورد default قبلی بازگردانده می‌شود تا دو semantics
        نیمه‌کاره باقی نماند.
        """
        defaults = await self.get_notif_defaults()
        if ntype not in defaults:
            raise ValueError('unknown_notification_type')
        before = bool(defaults.get(ntype))
        after = bool(value)
        await self.set_notif_default(ntype, after)
        affected = 0
        if apply_existing:
            try:
                affected = await self.apply_notif_default_to_all_users(ntype, after)
            except Exception:
                await self.set_notif_default(ntype, before)
                raise
        return {"before": before, "after": after,
                "apply_existing": bool(apply_existing),
                "affected_users": int(affected or 0)}


    async def count_active_users(self, minutes: int = 30) -> int:
        """
        FIX جدید: تعداد کاربرانی که در N دقیقه اخیر فعالیتی داشته‌اند —
        برای نمایش «کاربران آنلاین تقریبی» در وضعیت ربات استفاده می‌شود.
        """
        from datetime import datetime, timedelta
        cutoff = (now_utc() - timedelta(minutes=minutes)).isoformat()
        return await self.users.count_documents({'last_active': {'$gte': cutoff}})


    async def count_active_users_today(self) -> int:
        """تعداد کاربرانی که امروز (به وقت تهران) حداقل یک‌بار فعالیت داشته‌اند"""
        from utils import today_start_utc_str
        today_start = today_start_utc_str()
        return await self.users.count_documents({'last_active': {'$gte': today_start}})


    # ══════════════════════════════════════════════════
    #  📊 سیستم نمرات — FIX جدید
    #  نمرات امتحانی هر درس، ثبت‌شده توسط ادمین یا نماینده‌ی ورودی
    # ══════════════════════════════════════════════════

    @staticmethod
    def _norm_name(name: str) -> str:
        """نرمال‌سازی نام برای مقایسه — حذف فاصله‌های اضافه/نیم‌فاصله متفاوت"""
        return ' '.join((name or '').replace('\u200c', ' ').split()).strip().lower()


    async def find_students_by_name(self, name: str, intake: str = None) -> list:
        """
        جست‌وجوی دانشجو با نام (برای ثبت نمره‌ی دسته‌ای).
        اگه intake داده بشه، فقط همون ورودی جست‌وجو می‌شه (محدودیت نماینده).
        مقایسه با نرمال‌سازی انجام می‌شود تا فاصله/نیم‌فاصله اذیت نکند.
        """
        target = self._norm_name(name)
        if not target:
            return []
        q = {'approved': True}
        if intake:
            q['intake'] = intake
        candidates = await self.users.find(q).to_list(3000)
        return [u for u in candidates if self._norm_name(u.get('name', '')) == target]


    async def lesson_term(self, lesson_name) -> str:
        """🛡 AUDIT-§۸۲ — ترمِ یک درس از همان `bs_lessons` خوانده می‌شود.

        نمره ترم را «انتخاب» نمی‌کند؛ از منبعِ دروس می‌گیرد، پس اگر ادمین
        اسم درس را درست نوشته باشد، طبقه‌بندی خودکار و یکپارچه است.
        """
        name = (lesson_name or '').strip()
        if not name:
            return ''
        doc = await self.bs_lessons.find_one(
            {'name': {'$regex': f'^{re.escape(name)}$', '$options': 'i'}}, {'term': 1})
        return str((doc or {}).get('term') or '').strip()[:40]


    async def grade_bulk_upsert(self, entries: list, lesson: str, exam_title: str,
                                 exam_date: str, entered_by: int, term: str | None = None) -> list:
        """
        entries: [{'user_id': int, 'score': float}, ...]
        برای هر دانشجو، اگه نمره‌ی همین درس+امتحان از قبل ثبت شده بود
        آپدیت می‌شود (نه رکورد تکراری)، وگرنه درج می‌شود.
        خروجی: لیست رکوردهای نهایی ثبت‌شده (برای ارسال نوتیف).

        §۸۲ — `term` اگر داده نشود از خودِ درس استخراج می‌شود و روی رکورد
        می‌نشیند؛ برای رکوردِ قبلی هم اصلاح می‌شود (نه فقط درجِ تازه).
        """
        now = utc_now_iso()
        if term is None:
            term = await self.lesson_term(lesson)
        term = str(term or '').strip()[:40]
        saved = []
        for e in entries:
            uid, score = e['user_id'], e['score']
            existing = await self.grades.find_one({
                'student_id': uid, 'lesson': lesson, 'exam_title': exam_title
            })
            doc = {
                'student_id': uid, 'lesson': lesson, 'exam_title': exam_title,
                'exam_date': exam_date, 'score': score, 'entered_by': entered_by,
                'term': term, 'updated_at': now,
            }
            if existing:
                await self.grades.update_one({'_id': existing['_id']}, {'$set': doc})
                doc['_is_update'] = True
            else:
                doc['created_at'] = now
                r = await self.grades.insert_one(doc)
                doc['_id'] = r.inserted_id
                doc['_is_update'] = False
            saved.append(doc)
        return saved


    async def grade_list_for_student(self, uid: int, term: str | None = None) -> list:
        q = {'student_id': int(uid)}
        if term:
            q['term'] = str(term).strip()[:40]
        return await self.grades.find(q).sort('exam_date', -1).to_list(200)


    async def grade_terms(self) -> list:
        """همه‌ی ترم‌های دارای نمره (برای فهرستِ فیلترِ پنل/ربات)."""
        from grade_utils import _term_rank
        raw = await self.grades.distinct('term')
        return sorted([str(t) for t in raw if t], key=_term_rank)


    async def grade_terms_of_student(self, uid: int) -> list:
        """ترم‌هایی که این دانشجو در آن‌ها نمره دارد (برای تب/فیلتر).

        مرتب‌سازی با `_term_rank` انجام می‌شود، نه مقایسه‌ی رشته‌ای: با
        مقایسه‌ی رشته‌ای «ترم ۱۰» بینِ «ترم ۱» و «ترم ۲» می‌نشست، چون
        «۰» از «۲» کوچک‌تر است. همان کلیدی که `grade_terms` استفاده
        می‌کند تا ترتیبِ تب‌های مینی‌اپ و فیلترِ پنل یکی باشد.
        """
        from grade_utils import _term_rank
        raw = await self.grades.distinct('term', {'student_id': int(uid)})
        return sorted([str(t) for t in raw if t], key=_term_rank)


    async def grade_get(self, grade_id: str):
        try:
            return await self.grades.find_one({'_id': ObjectId(grade_id)})
        except Exception:
            return None


    async def grade_update_score(self, grade_id: str, score: float,
                                 entered_by: int) -> bool:
        try:
            result = await self.grades.update_one(
                {'_id': ObjectId(grade_id)},
                {'$set': {'score': score, 'max_score': 20,
                          'entered_by': entered_by,
                          'updated_at': utc_now_iso()}})
            return bool(getattr(result, 'matched_count', 0))
        except Exception:
            return False


    async def grade_term_breakdown(self, intake: str = None, group: str = None,
                                   q: str = None, lesson: str = None,
                                   date_from: str = None, date_to: str = None,
                                   term: str = None) -> list:
        """شمارش و میانگینِ هر ترم روی *همان* فیلترِ فهرست (§۸۲).

        روی صفحه‌بندی حساب نمی‌شود (وگرنه «میانگین ترم ۲» با عوض‌شدن
        صفحه عوض می‌شد)؛ خروجی برای سربرگ‌های پنل و نمای ربات یکی است.
        """
        query = await self._grade_admin_query(intake=intake, group=group, q=q, lesson=lesson,
                                              date_from=date_from, date_to=date_to, term=term)
        out = []
        async for d in self.grades.aggregate([
            {'$match': query or {}},
            {'$group': {'_id': '$term', 'n': {'$sum': 1},
                        'avg': {'$avg': '$score'}, 'max': {'$max': '$score'}}},
            {'$sort': {'_id': 1}},
        ], allowDiskUse=True):
            out.append({'term': str(d.get('_id') or ''), 'count': int(d.get('n') or 0),
                        'avg': round(float(d['avg']), 2) if isinstance(d.get('avg'), (int, float)) else None})
        return out


    async def grades_backfill_terms(self, max_lessons: int = 500) -> dict:
        """§۸۲ — پرکردن `term` نمره‌های قدیمی، از روی همان `bs_lessons`.

        عمداً «برای هر نامِ درس یک update_many» است، نه یک کوئری برای هر
        رکورد (قرارداد V4: بدون N+1 روی مجموعه‌های بزرگ). idempotent است و
        در boot بی‌خطر چند بار اجرا می‌شود.
        """
        names = [n for n in await self.grades.distinct('lesson') if n][:max_lessons]
        touched = updated = 0
        unmatched = []
        for name in names:
            touched += 1
            term = await self.lesson_term(name)
            if not term:
                unmatched.append(str(name)[:60])
                continue
            r = await self.grades.update_many(
                {'lesson': name, '$or': [{'term': {'$exists': False}}, {'term': ''}, {'term': None}]},
                {'$set': {'term': term}})
            updated += int(r.modified_count or 0)
        result = {'lessons_scanned': touched, 'grades_updated': updated,
                  'unmatched_lessons': len(unmatched)}
        await self.set_setting('grades_term_backfill',
                               {**result, 'at': utc_now_iso(), 'unmatched': unmatched[:20]})
        return result


    async def grade_delete(self, grade_id: str) -> bool:
        try:
            result = await self.grades.delete_one({'_id': ObjectId(grade_id)})
            return bool(getattr(result, 'deleted_count', 0))
        except Exception:
            return False


    async def _grade_admin_query(self, intake: str = None, group: str = None,
                                 q: str = None, lesson: str = None,
                                 date_from: str = None, date_to: str = None,
                                 term: str = None) -> dict:
        """فیلتر مشترک Bot/Web برای فهرست نمره؛ join کاربر با distinct و بدون N+1."""
        clauses = []
        user_filter = {}
        if intake:
            user_filter['intake'] = intake
        if group:
            user_filter['group'] = self.normalize_group(group)
        allowed_ids = None
        if user_filter:
            allowed_ids = await self.users.distinct('user_id', user_filter)
            clauses.append({'student_id': {'$in': allowed_ids}})
        if lesson:
            clauses.append({'lesson': {'$regex': re.escape(lesson.strip()), '$options': 'i'}})
        if term:
            # 🛡 AUDIT-§۸۲ — «نمرات ترم ۲» یعنی فیلترِ روی همان طبقه‌بندی
            clauses.append({'term': str(term).strip()[:40]})
        if date_from or date_to:
            dates = {}
            if date_from: dates['$gte'] = parse_gregorian_date(date_from).isoformat()
            if date_to: dates['$lte'] = parse_gregorian_date(date_to).isoformat()
            clauses.append({'exam_date': dates})
        if q and q.strip():
            search_ids = await self.users.distinct('user_id', self.build_user_search_query(q.strip()))
            if allowed_ids is not None:
                allowed_set = set(allowed_ids)
                search_ids = [uid for uid in search_ids if uid in allowed_set]
            rx = {'$regex': re.escape(q.strip()), '$options': 'i'}
            clauses.append({'$or': [
                {'student_id': {'$in': search_ids}}, {'lesson': rx}, {'exam_title': rx},
            ]})
        if not clauses:
            return {}
        return clauses[0] if len(clauses) == 1 else {'$and': clauses}


    async def grade_list_recent(self, skip: int = 0, limit: int = 10,
                                intake: str = None, group: str = None,
                                q: str = None, lesson: str = None,
                                date_from: str = None, date_to: str = None,
                                term: str = None) -> list:
        query = await self._grade_admin_query(intake=intake, group=group, q=q, lesson=lesson,
                                              date_from=date_from, date_to=date_to, term=term)
        return await self.grades.find(query).sort('created_at', -1).skip(skip).limit(limit).to_list(limit)


    async def grade_count_recent(self, intake: str = None, group: str = None,
                                 q: str = None, lesson: str = None,
                                 date_from: str = None, date_to: str = None,
                                 term: str = None) -> int:
        query = await self._grade_admin_query(intake=intake, group=group, q=q, lesson=lesson,
                                              date_from=date_from, date_to=date_to, term=term)
        return await self.grades.count_documents(query)


    # ══════════════════════════════════════════════════
    #  آمار مصرف هوشیار (AI) — برای پنل ادمین
    # ══════════════════════════════════════════════════

    async def ai_usage_stats(self, top_n: int = 5) -> dict:
        """
        آمار مصرف هوشیار: تعداد سوال امروز/کل، توکن مصرفی امروز/کل، و
        پرمصرف‌ترین کاربرها. فیلد ai_total_usage (همه‌ی زمان‌ها) و
        ai_usage_count/ai_usage_date (روزانه) روی خودِ سند کاربر در
        check_and_consume_quota نگه‌داری می‌شوند؛ ai_total_tokens/
        ai_tokens_today هم در ai_inc_tokens. اینجا فقط جمع‌بندی‌شان می‌کنیم.
        """
        today = today_tehran().isoformat()
        # تمام sum/topها داخل MongoDB؛ هیچ full-user hydration برای Analytics.
        rows = await self.users.aggregate([
            {'$match': {'$or': [{'ai_total_usage': {'$gt': 0}}, {'ai_usage_date': today}]}},
            {'$facet': {
                'summary': [{'$group': {
                    '_id': None,
                    'total_alltime': {'$sum': {'$ifNull': ['$ai_total_usage', 0]}},
                    'users_alltime': {'$sum': {'$cond': [{'$gt': [{'$ifNull': ['$ai_total_usage', 0]}, 0]}, 1, 0]}},
                    'tokens_alltime': {'$sum': {'$ifNull': ['$ai_total_tokens', 0]}},
                    'total_today': {'$sum': {'$cond': [{'$eq': ['$ai_usage_date', today]}, {'$ifNull': ['$ai_usage_count', 0]}, 0]}},
                    'users_today': {'$sum': {'$cond': [{'$and': [{'$eq': ['$ai_usage_date', today]}, {'$gt': [{'$ifNull': ['$ai_usage_count', 0]}, 0]}]}, 1, 0]}},
                    'tokens_today': {'$sum': {'$cond': [{'$eq': ['$ai_usage_date', today]}, {'$ifNull': ['$ai_tokens_today', 0]}, 0]}},
                }}],
                'top_today': [
                    {'$match': {'ai_usage_date': today, 'ai_usage_count': {'$gt': 0}}},
                    {'$sort': {'ai_usage_count': -1}}, {'$limit': max(1, min(int(top_n), 50))},
                    {'$project': {'_id': 0, 'name': {'$ifNull': ['$name', '—']}, 'user_id': 1, 'value': '$ai_usage_count'}},
                ],
                'top_alltime': [
                    {'$match': {'ai_total_usage': {'$gt': 0}}},
                    {'$sort': {'ai_total_usage': -1}}, {'$limit': max(1, min(int(top_n), 50))},
                    {'$project': {'_id': 0, 'name': {'$ifNull': ['$name', '—']}, 'user_id': 1, 'value': '$ai_total_usage'}},
                ],
            }},
        ]).to_list(1)
        facet = rows[0] if rows else {}
        summary = (facet.get('summary') or [{}])[0]
        tuple_rows = lambda key: [(row.get('name') or '—', row.get('user_id'), row.get('value', 0))
                                  for row in facet.get(key, [])]
        return {
            'total_today': int(summary.get('total_today') or 0),
            'users_today': int(summary.get('users_today') or 0),
            'total_alltime': int(summary.get('total_alltime') or 0),
            'users_alltime': int(summary.get('users_alltime') or 0),
            'tokens_today': int(summary.get('tokens_today') or 0),
            'tokens_alltime': int(summary.get('tokens_alltime') or 0),
            'top_today': tuple_rows('top_today'),
            'top_alltime': tuple_rows('top_alltime'),
        }


    async def ai_image_used_today(self, uid: int, today: str) -> tuple:
        """🎨 مصرف امروزِ تصویر (used_today) — سطل تصویر عمداً از سطل
        چت جداست (ai_image_count/ai_image_date): تصویر گران‌تر است و
        سهمیه‌ی مستقل می‌خواهد."""
        u = await self.users.find_one({'user_id': int(uid)},
                                      {'ai_image_count': 1,
                                       'ai_image_date': 1})
        if not u:
            return 0
        if u.get('ai_image_date') != today:
            return 0
        return int(u.get('ai_image_count') or 0)

    async def ai_image_inc(self, uid: int, today: str) -> int:
        """🎨 یک واحد مصرف تصویر — **بعد از موفقیت** سرویس صدا زده می‌شود
        (شکست provider سهمیه‌ی کاربر را نمی‌سوزاند). اتمیک و بدون شرط؛
        هم‌زمانیِ کاربر با قفل ai_inflight بسته شده است."""
        await self.users.update_one(
            {'user_id': int(uid)},
            [{'$set': {
                'ai_image_count': {'$cond': [
                    {'$eq': ['$ai_image_date', today]},
                    {'$add': [{'$ifNull': ['$ai_image_count', 0]}, 1]}, 1]},
                'ai_image_date': today,
                'ai_image_total': {
                    '$add': [{'$ifNull': ['$ai_image_total', 0]}, 1]},
            }}])
        u = await self.users.find_one({'user_id': int(uid)},
                                      {'ai_image_count': 1})
        return int((u or {}).get('ai_image_count') or 0)

    async def plan_for_sub(self, sub: dict | None) -> dict | None:
        """🌊 W7 — پلنِ یک اشتراک (تک‌منبع: اول plan_id، بعد تطبیق نام فعال).

        استخراج‌شده از ai_limit_for_user تا entitlement و سهمیه یک منطق
        داشته باشند؛ رفتار ai_limit عیناً حفظ می‌شود.
        """
        if not sub:
            return None
        try:
            pid = str(sub.get("plan_id") or "")
            if pid:
                plan = await self.sub_plan_get(pid)
                if plan:
                    return plan
            if sub.get("plan_name"):
                plans = await self.sub_plan_list(only_active=True)
                return next((x for x in plans
                             if x.get("name") == sub.get("plan_name")), None)
        except Exception:
            return None
        return None

    # ── 🌊 W7 — پالیسی فیچر ──
    async def get_feature_policy(self, feature: str) -> dict | None:
        try:
            return await self.feature_policies.find_one({"_id": str(feature)})
        except Exception:
            return None

    async def set_feature_policy(self, feature: str, patch: dict,
                                 actor_id: int = 0,
                                 actor_name: str = "") -> dict:
        """ذخیره‌ی پالیسی + اسنپ‌شات prev برای rollback. برمی‌گرداند {before, after}."""
        feature = str(feature)
        cur = await self.feature_policies.find_one({"_id": feature}) or {}
        before = {k: cur.get(k) for k in (
            "enabled", "access", "trial_allowed", "quota", "fail_open",
            "note", "pending_access", "effective_from")}
        clean = {k: patch[k] for k in before if k in patch}
        prev = dict(before)
        prev["_by"] = cur.get("updated_by", 0)
        prev["_by_name"] = cur.get("updated_by_name", "")
        prev["_at"] = cur.get("updated_at")
        after = dict(before)
        after.update(clean)
        await self.feature_policies.update_one(
            {"_id": feature},
            {"$set": {**clean, "prev": prev, "updated_at": utc_now_iso(),
                      "updated_by": int(actor_id or 0),
                      "updated_by_name": actor_name or ""}},
            upsert=True)
        return {"before": before, "after": after}

    async def rollback_feature_policy(self, feature: str, actor_id: int = 0,
                                      actor_name: str = "") -> dict | None:
        """بازگردانی به prev (و جابه‌جایی prev/current ⇒ rollback دو‌باره = redo)."""
        cur = await self.feature_policies.find_one({"_id": str(feature)}) or {}
        prev = cur.get("prev")
        if not prev:
            return None
        restore = {k: prev.get(k) for k in (
            "enabled", "access", "trial_allowed", "quota", "fail_open",
            "note", "pending_access", "effective_from")}
        return await self.set_feature_policy(feature, restore, actor_id,
                                             actor_name)

    # ── 🌊 W7 — سهمیه‌ی ژنریک (روزانه/ماهانه، اتمیک) ──
    @staticmethod
    def _usage_period(kind: str) -> str:
        today = today_tehran().isoformat()  # YYYY-MM-DD
        return today if kind == "daily" else today[:7]

    async def feature_usage_get(self, uid: int, feature: str,
                                kind: str) -> int:
        try:
            doc = await self.feature_usage.find_one({
                "_id": f"{int(uid)}:{feature}:{self._usage_period(kind)}"})
        except Exception:
            return 0
        return int((doc or {}).get("count", 0) or 0)

    async def feature_consume(self, uid: int, feature: str, kind: str,
                              limit: int) -> tuple:
        """مصرف اتمیک یک واحد؛ برمی‌گرداند (allowed, used_after)."""
        if kind not in ("daily", "monthly") or int(limit or 0) <= 0:
            return True, 0
        from pymongo import ReturnDocument
        try:
            from pymongo.errors import DuplicateKeyError
        except ImportError:  # pragma: no cover
            DuplicateKeyError = Exception
        filt = {"_id": f"{int(uid)}:{feature}:{self._usage_period(kind)}",
                "count": {"$lt": int(limit)}}
        upd = {"$inc": {"count": 1},
               "$set": {"updated_at": now_utc()}}  # datetime برای TTL
        for attempt in range(2):
            try:
                res = await self.feature_usage.find_one_and_update(
                    filt, upd, upsert=True,
                    return_document=ReturnDocument.AFTER)
            except DuplicateKeyError:
                # یا race ساخت سند بود یا سقف واقعاً پر است: بخوان و تصمیم بگیر
                used = await self.feature_usage_get(uid, feature, kind)
                if used < int(limit) and attempt == 0:
                    continue  # race بود؛ دوباره مصرف کن (نه واحد مجانی)
                return used < int(limit), used
            # با upsert همیشه سند برمی‌گردد (ساخته یا $incشده)
            if res:
                return True, int(res.get("count", 0) or 0)
            break
        used = await self.feature_usage_get(uid, feature, kind)
        return used < int(limit), used

    async def log_feature_event(self, feature: str, event: str, uid: int,
                                extra: dict | None = None) -> None:
        """ایونت سبک فیچر (TTL ۳۰ روزه) برای آنالیتیکس تبدیل/پی‌وال."""
        try:
            await self.feature_events.insert_one({
                "feature": str(feature), "event": str(event),
                "user_id": int(uid), "extra": extra or {},
                "at": now_utc()})  # datetime برای TTL
        except Exception:
            pass


    async def ai_limit_for_user(self, uid: int, global_limit: int) -> int:
        """🌊 W6/MISS-04 — سهمیه روزانه هوشیار این کاربر.

        اشتراک فعال ← پلن (plan_id، وگرنه تطبیق نام میان پلن‌های فعال)؛
        اگر پلن `ai_daily_limit>0` داشت همان، وگرنه سقف سراسری.
        بدون اشتراک فعال ← سقف سراسری. ۰ یعنی نامحدود (قرارداد قبلی).
        """
        try:
            sub = await self.sub_get(int(uid))
        except Exception:
            return int(global_limit or 0)
        if not sub or sub.get("status") != "active":
            return int(global_limit or 0)
        plan = await self.plan_for_sub(sub)
        if plan:
            try:
                pl = int(plan.get("ai_daily_limit") or 0)
            except (TypeError, ValueError):
                pl = 0
            if pl > 0:
                return pl
        return int(global_limit or 0)


    async def ai_consume_quota(self, uid: int, daily_limit: int, today: str) -> tuple:
        """Atomically reserve one AI request across all API/Bot workers.

        The conditional update makes the daily counter a process-independent
        invariant. A local busy set may still reduce duplicate work, but it is
        not used as quota enforcement.
        """
        uid = int(uid)
        limit = int(daily_limit or 0)
        if uid == int(os.getenv('ADMIN_ID', '0')) or limit <= 0:
            result = await self.users.update_one(
                {'user_id': uid},
                [{'$set': {
                    'ai_usage_date': today,
                    'ai_total_usage': {'$add': [{'$ifNull': ['$ai_total_usage', 0]}, 1]},
                    'ai_tokens_today': {'$cond': [
                        {'$eq': ['$ai_usage_date', today]},
                        {'$ifNull': ['$ai_tokens_today', 0]}, 0]},
                }}],
            )
            return bool(result.matched_count), 0, 0

        from pymongo import ReturnDocument
        # A new day resets the daily counter inside the same atomic update;
        # an existing day is admitted only while count < limit.
        result = await self.users.find_one_and_update(
            {'user_id': uid, '$or': [
                {'ai_usage_date': today, 'ai_usage_count': {'$lt': limit}},
                {'ai_usage_date': {'$ne': today}},
            ]},
            [{'$set': {
                'ai_usage_count': {'$cond': [
                    {'$eq': ['$ai_usage_date', today]},
                    {'$add': [{'$ifNull': ['$ai_usage_count', 0]}, 1]}, 1]},
                'ai_usage_date': today,
                'ai_total_usage': {'$add': [{'$ifNull': ['$ai_total_usage', 0]}, 1]},
                'ai_tokens_today': {'$cond': [
                    {'$eq': ['$ai_usage_date', today]},
                    {'$ifNull': ['$ai_tokens_today', 0]}, 0]},
            }}],
            return_document=ReturnDocument.AFTER,
        )
        if result:
            return True, int(result.get('ai_usage_count', 0) or 0), limit
        current = await self.users.find_one({'user_id': uid}, {'ai_usage_date': 1, 'ai_usage_count': 1})
        used = int((current or {}).get('ai_usage_count', 0) or 0)
        if (current or {}).get('ai_usage_date') != today:
            used = 0
        return False, used, limit


    async def ai_inc_tokens(self, uid: int, tokens: int) -> None:
        """
        افزایشِ اتمیک (بدون نیاز به خواندن قبلی) توکن مصرفیِ هوشیار برای
        یک کاربر — هم شمارنده‌ی «امروز» (که موقع رد شدن روز در
        check_and_consume_quota صفر می‌شود) و هم شمارنده‌ی «کل».
        """
        if not tokens:
            return
        await self.users.update_one(
            {'user_id': uid},
            {'$inc': {'ai_total_tokens': int(tokens), 'ai_tokens_today': int(tokens)}},
        )


    # ══════════════════════════════════════════════════
    #  مسدودکردن یک کاربر خاص از هوشیار (جدا از بلاک کاملِ ربات)
    # ══════════════════════════════════════════════════

    async def ai_set_banned(self, uid: int, banned: bool) -> None:
        await self.users.update_one({'user_id': uid}, {'$set': {'ai_banned': bool(banned)}})


    async def ai_is_banned(self, uid: int) -> bool:
        user = await self.get_user(uid) or {}
        return bool(user.get('ai_banned'))


    async def ai_list_banned(self, limit: int = 50) -> list:
        return await self.users.find(
            {'ai_banned': True}, {'user_id': 1, 'name': 1}
        ).to_list(length=limit)


    # ══════════════════════════════════════════════════
    #  لاگِ پایدارِ «گزارش پاسخ نامناسب» — قبلاً فقط توی RAM بود و با
    #  ری‌استارتِ ربات از بین می‌رفت؛ حالا برای بررسیِ بعدیِ ادمین توی
    #  دیتابیس هم ثبت می‌شه (مستقل از کشِ موقتِ RAM که برای دکمه‌ی زیر
    #  پیام استفاده می‌شه).
    # ══════════════════════════════════════════════════

    async def ai_log_report(self, uid: int, name: str, question: str, answer: str) -> None:
        await self.ai_reports.insert_one({
            'user_id':  uid,
            'name':     name or '—',
            'question': (question or '—')[:1000],
            'answer':   (answer or '—')[:2000],
            'created_at': now_utc(),
        })


    async def ai_recent_reports(self, limit: int = 10) -> list:
        cursor = self.ai_reports.find({}).sort('created_at', -1).limit(limit)
        return await cursor.to_list(length=limit)


    # ══════════════════════════════════════════════════
    #  حافظه‌ی مکالمه‌ی هوشیار — ⚠️ فیکس: قبلاً فقط توی RAM بود و با هر
    #  ری‌استارتِ سرور (که این چند روز به‌خاطرِ آپدیت‌های پیاپی زیاد
    #  اتفاق افتاد) کاملاً از بین می‌رفت. حالا روی خودِ سندِ کاربر توی
    #  دیتابیس ذخیره می‌شه — پایدار، ولی فشرده: با $slice همیشه فقط
    #  چند آیتمِ آخر نگه داشته می‌شه (نه یه آرشیوِ بی‌نهایت‌رشد).
    # ══════════════════════════════════════════════════

    async def ai_remember(self, uid: int, role: str, text: str, max_items: int) -> None:
        await self.users.update_one(
            {'user_id': uid},
            {
                '$push': {'ai_mem': {'$each': [{'r': role, 't': (text or '')[:1200]}], '$slice': -max_items}},
                '$set': {'ai_mem_at': now_utc()},
            },
        )


    async def ai_get_memory(self, uid: int) -> tuple:
        """برمی‌گرداند (items, last_updated_datetime_or_None)."""
        user = await self.get_user(uid) or {}
        return user.get('ai_mem', []) or [], user.get('ai_mem_at')


    async def ai_clear_memory(self, uid: int) -> None:
        await self.users.update_one({'user_id': uid}, {'$unset': {'ai_mem': '', 'ai_mem_at': ''}})


    # ══════════════════════════════════════════════════
    #  گفت‌وگوهای چندگانه‌ی هوشیار (مینی‌اپ) — افزایشی:
    #  حافظه‌ی تک‌رشته‌ای ai_mem بالا دست‌نخورده می‌ماند
    #  تا چت ربات و مینی‌اپ همچنان مشترک باشد؛ این بخش
    #  رشته‌های جداگانه‌ی مدیریت‌شده (پین/آرشیو/حذف) است.
    # ══════════════════════════════════════════════════

    async def ai_conv_create(self, uid: int, title: str = 'گفت‌وگوی جدید') -> str:
        doc = {
            'user_id':    uid,
            'title':      title,
            'pinned':     False,
            'archived':   False,
            'items':      [],
            'preview':    '',
            'msg_count':  0,
            'created_at': utc_now_iso(),
            'updated_at': utc_now_iso(),
        }
        r = await self.ai_conversations.insert_one(doc)
        return str(r.inserted_id)


    async def ai_conv_insert_copy(self, uid: int, title: str,
                                  items: list,
                                  max_items: int = 120) -> str:
        """درج رونوشتِ یک گفت‌وگو — آیتم‌ها عیناً (با نقش و متن) کپی
        می‌شوند و برچسبِ زمانیِ ساخت/به‌روزرسانی، لحظه‌ی فعلی است."""
        now = utc_now_iso()
        clipped = (items or [])[-max_items:]
        doc = {
            'user_id':    uid,
            'title':      (title or 'رونوشت گفت‌وگو')[:80],
            'pinned':     False,
            'archived':   False,
            'items':      clipped,
            'preview':    (str(clipped[-1].get('t') or '')[:90]
                           if clipped else ''),
            'msg_count':  len(clipped),
            'created_at': now,
            'updated_at': now,
        }
        r = await self.ai_conversations.insert_one(doc)
        return str(r.inserted_id)


    async def ai_conv_list(self, uid: int, include_archived: bool = False) -> list:
        q = {'user_id': uid}
        if not include_archived:
            q['archived'] = {'$ne': True}
        docs = await self.ai_conversations.find(
            q,
            {'items': 0},   # فقط متا — آیتم‌ها را جداگانه می‌خوانیم
        ).to_list(200)
        docs.sort(key=lambda d: (
            0 if d.get('pinned') else 1,
            -(parse_machine_datetime(d.get('updated_at', '1970-01-01T00:00:00+00:00')).timestamp()
              if d.get('updated_at') else 0),
        ))
        return docs


    async def ai_conv_get(self, cid: str, uid: int) -> dict | None:
        try:
            oid = ObjectId(cid)
        except Exception:
            return None
        return await self.ai_conversations.find_one(
            {'_id': oid, 'user_id': uid}
        )


    async def ai_conv_update(self, cid: str, uid: int, fields: dict) -> bool:
        allowed = {'title', 'pinned', 'archived'}
        patch = {k: v for k, v in fields.items() if k in allowed}
        if not patch:
            return False
        patch['updated_at'] = utc_now_iso()
        try:
            oid = ObjectId(cid)
        except Exception:
            return False
        r = await self.ai_conversations.update_one(
            {'_id': oid, 'user_id': uid}, {'$set': patch}
        )
        return r.matched_count == 1


    async def ai_conv_delete(self, cid: str, uid: int) -> bool:
        try:
            oid = ObjectId(cid)
        except Exception:
            return False
        r = await self.ai_conversations.delete_one(
            {'_id': oid, 'user_id': uid}
        )
        return r.deleted_count == 1


    async def ai_conv_delete_empty(self, uid: int) -> None:
        """گفت‌وگوهای خالیِ رهاشده را پاک می‌کند — وقتی کاربر چند بار پشت
        سرهم «گفت‌وگوی جدید» می‌سازد بدون اینکه چیزی بفرستد."""
        await self.ai_conversations.delete_many(
            {'user_id': uid, 'msg_count': {'$lte': 0}}
        )


    async def ai_conv_append(self, cid: str, uid: int,
                             user_item: dict, ai_item: dict,
                             title: str | None, preview: str,
                             max_items: int = 120) -> bool:
        """افزودن یک دورِ پرسش/پاسخ به گفت‌وگو (اتمیک) + به‌روزرسانی متا.
        فقط وقتی title داده شود (اولین دور) عنوانی که ساخته‌ایم ست می‌شود."""
        try:
            oid = ObjectId(cid)
        except Exception:
            return False
        set_fields = {
            'updated_at': utc_now_iso(),
            'preview':    (preview or '')[:90],
        }
        if title:
            set_fields['title'] = title
        r = await self.ai_conversations.update_one(
            {'_id': oid, 'user_id': uid},
            {
                '$push': {'items': {'$each': [user_item, ai_item], '$slice': -max_items}},
                '$set':  set_fields,
                '$inc':  {'msg_count': 2},
            },
        )
        return r.matched_count == 1


    # ══════════════════════════════════════════════════
    #  سندِ مرجعِ فعال — ⚠️ قابلیتِ جدید: وقتی دانشجو یه PDF می‌فرسته،
    #  خودِ فایل روی سرورهای گوگل (Files API، رایگان، ۴۸ ساعت نگه‌داری)
    #  آپلود می‌شه؛ اینجا فقط یه اشاره‌گرِ کوچیک (URI + زمان) ذخیره
    #  می‌کنیم، نه خودِ فایل — دیتابیسِ ما دست‌نخورده و فشرده می‌مونه.
    # ══════════════════════════════════════════════════

    async def ai_set_doc(self, uid: int, uri: str, mime: str, name: str) -> None:
        await self.users.update_one(
            {'user_id': uid},
            {'$set': {
                'ai_doc_uri': uri, 'ai_doc_mime': mime, 'ai_doc_name': name[:100],
                'ai_doc_at': now_utc(),
            }},
        )


    async def ai_get_doc(self, uid: int) -> dict:
        user = await self.get_user(uid) or {}
        if not user.get('ai_doc_uri'):
            return None
        return {
            'uri': user['ai_doc_uri'], 'mime': user.get('ai_doc_mime'),
            'name': user.get('ai_doc_name'), 'at': user.get('ai_doc_at'),
        }


    async def ai_clear_doc(self, uid: int) -> None:
        await self.users.update_one(
            {'user_id': uid},
            {'$unset': {'ai_doc_uri': '', 'ai_doc_mime': '', 'ai_doc_name': '', 'ai_doc_at': ''}},
        )


    # ══════════════════════════════════════════════════
    #  ⚠️ قابلیتِ جدید: «پروفایلِ ماندگارِ فشرده» — به‌جای نگه‌داشتنِ کلِ
    #  متنِ گفتگوها برای همیشه (که هم مشکلِ حریمِ خصوصی داره هم دیتابیس
    #  رو پر می‌کنه)، فقط چند نکته‌ی مختصر و ماندگار که خودِ مدل تشخیص
    #  می‌ده «ارزشِ به‌خاطرسپردن» رو داره، ذخیره می‌شه (حداکثر ۶ مورد،
    #  با $slice همیشه فشرده می‌مونه). کاملاً جدا از حافظه‌ی مکالمه‌ی
    #  ۶ساعته (ai_mem) — این یکی هیچ TTL ای نداره چون قراره ماندگار باشه.
    # ══════════════════════════════════════════════════

    async def ai_remember_fact(self, uid: int, fact: str, max_items: int = 6) -> None:
        if not fact:
            return
        await self.users.update_one(
            {'user_id': uid},
            {'$push': {'ai_profile_notes': {'$each': [fact[:300]], '$slice': -max_items}}},
        )


    async def ai_get_profile_notes(self, uid: int) -> list:
        user = await self.get_user(uid) or {}
        return user.get('ai_profile_notes', []) or []


    async def ai_forget_profile(self, uid: int) -> None:
        await self.users.update_one({'user_id': uid}, {'$unset': {'ai_profile_notes': ''}})
