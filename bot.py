"""
🩺 ربات پزشکی — نسخه نهایی کامل
  ✅ broadcast کاملاً خارج از ConversationHandler
  ✅ unified_file/text_handler با broadcast + qbank
  ✅ job_queue برای یادآوری‌ها
  ✅ error_handler مرکزی با گزارش به ادمین
  ✅ سازگار با python-telegram-bot 21.x
"""
import os
import sys
import html
import re
import time
import logging
import asyncio
from datetime import time as dtime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler,
    filters, ContextTypes, Application, TypeHandler,
    ApplicationHandlerStop
)

# ── ایمپورت ماژول‌ها ──
# 🧠 FIX معماری «دو مغز»: قبلاً ثبت‌نام، ساخت سوال، پنل محتوا، پروفایل
# و تیکت هم داخل ConversationHandler مرکزی state داشتند و هم موازی
# با آن از context.user_data['mode' / 'ca_mode' / 'ticket_mode'] در
# unified_text_handler/unified_file_handler/message_router پیروی
# می‌کردند. دو سیستم مستقل که هر دو فکر می‌کردند مسئول مسیر کاربرند
# دقیقاً همان چیزی بود که باعث شد یک بار پیام broadcast ادمین به‌جای
# مقصد درست، وسط یک state قدیمی (مثلاً ساخت سوال) قورت داده شود.
# الان ConversationHandler فقط مسئول تنها فلوی واقعاً چندمرحله‌ای‌ای
# است که معادل mode-based ندارد: «ثبت‌نام». همه‌ی بقیه (ساخت سوال،
# پنل محتوا، پروفایل، تیکت، پاسخ به سوال) از قبل به‌طور کامل توسط
# unified_text_handler / unified_file_handler / CallbackQueryHandlerهای
# standalone پایین همین فایل پوشش داده می‌شوند — همان‌ها تنها مرجع
# باقی می‌مانند تا همیشه state واقعی و به‌روز را ببینند.
from start import (
    start_handler, register_start_callback, step_name_handler,
    register_intake_callback, step_student_id_handler,
    REGISTER, STEP_NAME, STEP_GROUP, STEP_INTAKE, STEP_STUDENT_ID
)
from dashboard import dashboard_callback
from questions import questions_callback, handle_difficulty_choice
from schedule import schedule_callback
from stats import stats_callback
from notifications import notifications_callback
from admin import (
    admin_callback, admin_broadcast_handler,
    handle_admin_text, BROADCAST
)
from backup import backup_callback, backup_file_handler, backup_confirm_restore
from utils import cancel_handler, ADMIN_ID, is_maintenance_on, maintenance_message, send_audit_log, safe_send, safe_send_ex, safe_send_status, spawn_bg, CONTENT_ICONS, fmt_jalali, now_tehran_str, webapp_kb
from time_utils import (
    TEHRAN, format_time_fa, now_tehran, now_utc, parse_gregorian_date,
    parse_machine_datetime, remaining_days, utc_now_iso, week_key_tehran,
)
from subscription import subscription_callback, screenshot_handler as sub_screenshot_handler
from subscription_admin import subscription_admin_callback
from grades import grades_callback
from profile import profile_callback
from referral import referral_callback          # 🌱 W13 — دعوت دوستان
from dunning import dunning_job, dunning_click  # 💳 W14 — پیگیری پرداخت
from message_router import route_message
from basic_science import basic_science_callback

# 🌊 W5 — Flood-Control per-user (in-memory token bucket)
import collections as _coll
_FLOOD_WINDOW = 5  # seconds
_FLOOD_LIMIT = 5  # msgs per window
_FLOOD_BLOCK = 30  # seconds block
_FLOOD_HIST: dict[int, _coll.deque] = {}
_FLOOD_BLOCKED: dict[int, float] = {}
def _check_flood(uid: int) -> tuple[bool, int]:
    now = time.time()
    blocked_until = _FLOOD_BLOCKED.get(uid, 0)
    if now < blocked_until:
        return True, int(blocked_until - now)
    dq = _FLOOD_HIST.get(uid)
    if dq is None:
        dq = _coll.deque()
        _FLOOD_HIST[uid] = dq
    # prune
    while dq and now - dq[0] > _FLOOD_WINDOW:
        dq.popleft()
    dq.append(now)
    if len(dq) > _FLOOD_LIMIT:
        _FLOOD_BLOCKED[uid] = now + _FLOOD_BLOCK
        # keep only last
        dq.clear()
        return True, _FLOOD_BLOCK
    # also 30 per minute guard
    if len(dq) > 30:
        # check 60s window approximate
        pass
    return False, 0
_FLOOD_WARNED: dict[int, float] = {}

from resources import resources_callback
from references import references_callback
from content_admin import content_admin_callback, ca_file_handler, ca_text_handler
from faq import faq_callback
from ticket import ticket_callback, ticket_message_handler
from reports import report_callback, handle_report_note_text   # FIX جدید
from ai_admin import ai_admin_callback, ai_admin_text_handler   # 🤖 هوشیار
from ai_solver import (                                          # 🤖 هوشیار
    handle_ai_text, handle_ai_media, handle_ai_image_prompt,
    ai_user_callback,
)
from database import db

logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# 💍 Ring Street — ماژول افزودنی و ایزوله. اگر import آن (به هر دلیلی)
# شکست بخورد، ربات مثل قبل بالا می‌آید و فقط رینگ ثبت نمی‌شود.
try:
    import ring as ring_street
    from ring import handlers as ring_handlers
    from ring import jobs as ring_jobs
except Exception as _ring_import_error:          # pragma: no cover
    ring_street = ring_handlers = ring_jobs = None
    logger.warning("⚠️ ماژول رینگ استریت بارگذاری نشد: %s", _ring_import_error)

TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TOKEN:
    logger.error("❌ TELEGRAM_TOKEN تنظیم نشده!")
    sys.exit(1)


# ══════════════════════════════════════════════════
#  Job: یادآوری امتحانات — هر روز ۰۸:۰۰ تهران
# ══════════════════════════════════════════════════

async def exam_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    """
    FIX جدید: لاگ کامل وضعیت ارسال در notif_runs برای پایش و retry.
    ضد-تکرار از قبل با mark_exam_notified/notified_days درست بود — حفظ شد.
    """
    logger.info("🔔 اجرای job یادآوری امتحان...")
    run_id = await db.notif_run_start('exam_reminder')
    total_sent, total_failed, total_targets = 0, 0, 0
    failed_records = []  # FIX جدید: [{'user_id':, 'message':}, ...] برای retry دقیق
    day_labels = {1: "⚠️ فردا امتحان دارید!", 3: "📅 ۳ روز دیگر", 7: "📅 ۷ روز دیگر"}
    try:
        for days, label in day_labels.items():
            exams = await db.get_exams_for_reminder(days)
            for exam in exams:
                sid = str(exam['_id'])
                msg = (
                    f"🔔 <b>یادآوری امتحان</b>\n\n"
                    f"📚 <b>{exam.get('lesson', '')}</b>\n"
                    f"⏰ {label}\n"
                    f"📅 تاریخ: {fmt_jalali(exam.get('date', ''))}  ساعت {format_time_fa(exam.get('time'), fallback='—')}\n"
                    f"📍 مکان: {exam.get('location', '')}\n"
                    f"👨‍🏫 استاد: {exam.get('teacher', '')}\n\n"
                    f"<i>⚙️ خاموش‌کردن: 🔔 اعلان‌ها ← یادآوری امتحان</i>"
                )
                users = await db.notif_users('exam', group=exam.get('group'))
                sent  = 0
                total_targets += len(users)
                import urllib.parse as _upq
                # 🧠 موج N2 — Deep Link: باز شدن روز/درسِ امتحان در مینی‌اپ
                _ekb = webapp_kb('/schedule?hl=' + _upq.quote(str(exam.get('lesson') or '')))
                # 🔔 موج ۴.۹۰ — اینباکس مینی‌اپ: سابقه‌ی رویداد برای همه‌ی
                # مخاطبان ثبت می‌شود (حتی اگر تلگرام بلاک باشد، کاربر در
                # مینی‌اپ یادآوری را می‌بیند) — Deep Link به تب «برنامه»
                import urllib.parse as _upq2
                _ex_hl = ('/schedule?hl=' +
                          _upq2.quote(str(exam.get('lesson') or '')))
                await db.inbox_add_many([
                    {'user_id': u['user_id'], 'type': 'exam_reminder',
                     'title': f"🔔 یادآوری امتحان — {label}",
                     'body': (f"📚 {exam.get('lesson', '')}\n"
                              f"📅 {fmt_jalali(exam.get('date', ''))}  ساعت {format_time_fa(exam.get('time'), fallback='—')}\n"
                              f"📍 {exam.get('location', '')}"),
                     # 🧠 N2 — Deep Link: همان روز/درس+Anchor فلش در مینی‌اپ
                     'link': _ex_hl}
                    for u in users if u.get('user_id')
                ])
                for u in users:
                    ok = await safe_send(context.bot, u['user_id'], msg,
                                         parse_mode='HTML', reply_markup=_ekb)
                    if ok:
                        sent += 1
                    else:
                        total_failed += 1
                        failed_records.append({'user_id': u['user_id'], 'message': msg})
                    await asyncio.sleep(0.05)
                total_sent += sent
                if sent:
                    await db.mark_exam_notified(sid, days)
                    logger.info(f"امتحان {exam.get('lesson')} — {sent} نفر مطلع شدند")
        await db.notif_run_finish(run_id, total_sent, total_failed, total_targets)
        if failed_records:
            await db.notif_run_add_failed_detailed(run_id, failed_records)
    except Exception as e:
        logger.error(f"exam_reminder_job error: {e}")
        await db.notif_run_finish(run_id, total_sent, total_failed, total_targets,
                                   status='error', error=str(e))


async def daily_question_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Job: سوال روزانه — هر روز ۰۹:۰۰ تهران.
    FIX باگ قبلی: همیشه یک سوال ثابت می‌فرستاد. حالا با چرخش
    (get_daily_rotation_question) واقعاً هر روز سوال عوض می‌شود.
    FIX جدید: وضعیت ارسال در notif_runs ثبت می‌شود تا قابل پایش
    و retry باشد.
    """
    run_id = await db.notif_run_start('daily_question')
    sent, failed = 0, 0
    failed_ids = []
    try:
        q = await db.get_daily_rotation_question()
        if not q:
            await db.notif_run_finish(run_id, 0, 0, 0, status='skipped', error='no questions')
            return
        opts    = q.get('options', [])
        letters = ['🅐', '🅑', '🅒', '🅓']
        opts_text = '\n'.join(
            f"{letters[i]} {opt}" for i, opt in enumerate(opts)
        )
        text = (
            f"🧪 <b>سوال روزانه</b>\n\n"
            f"📚 {q.get('lesson', '')} — {q.get('topic', '')}\n\n"
            f"❓ {q.get('question', '')}\n\n"
            f"{opts_text}\n\n"
            f"<i>برای تمرین بیشتر از بانک سوال استفاده کنید 👇</i>\n"
            f"<i>⚙️ خاموش‌کردن: 🔔 اعلان‌ها ← سوال روزانه</i>"
        )
        users = await db.notif_users('daily_question')
        await db.notif_run_set_message(run_id, text)
        # 🌊 W5 — Deep-Link به همان سؤال (qid)
        _qid = str(q.get('_id') or q.get('id') or '')
        _deep = f"/learn/questions?hl={_qid}" if _qid else '/learn/questions'
        _qkb = webapp_kb(_deep)
        # 🔔 موج ۴.۹۰ — اینباکس مینی‌اپ (Deep Link به همان سؤال)
        await db.inbox_add_many([
            {'user_id': u['user_id'], 'type': 'daily_question',
             'title': '🧪 سؤال روزانه رسید',
             'body': (f"📚 {q.get('lesson', '')} — {q.get('topic', '')}\n"
                      f"❓ {q.get('question', '')[:140]}"),
             'link': _deep}
            for u in users if u.get('user_id')
        ])
        for u in users:
            ok = await safe_send(context.bot, u['user_id'], text,
                                 parse_mode='HTML', reply_markup=_qkb)
            if ok:
                sent += 1
            else:
                failed += 1
                failed_ids.append(u['user_id'])
            await asyncio.sleep(0.05)
        await db.notif_run_finish(run_id, sent, failed, len(users))
        if failed_ids:
            await db.notif_run_add_failed(run_id, failed_ids)
    except Exception as e:
        logger.error(f"daily_question_job error: {e}")
        await db.notif_run_finish(run_id, sent, failed, sent + failed, status='error', error=str(e))


# ── آیکون هر نوع فایل — جایگزین پیشوند متنی «PDF:» / «نمونه سوال:» قبلی؛
#    آیکون خودش نوع فایل را می‌گوید، پس چشم مستقیم می‌رود سراغ اسم فایل.
#    FIX: به‌جای یک دیکشنری جداگانه و ناهماهنگ، مستقیماً از CONTENT_ICONS
#    مرکزی (utils.py) خوانده می‌شود — همان چیزی که داشبورد، پنل محتوا و
#    بخش «منابع علوم پایه» استفاده می‌کنند — تا آیکون هر نوع فایل در
#    همه‌جای بات یکسان بماند (مثلاً ویدیو همیشه 🎥، ویس همیشه 🎙). فقط
#    'audio' به‌عنوان alias برای 'voice' نگه داشته شده برای سازگاری با
#    محتوای قدیمی که ممکن است این مقدار را داشته باشد.
_RESOURCE_ICONS = {**CONTENT_ICONS, 'audio': CONTENT_ICONS.get('voice', '🎙'), 'ref': '📖'}
_DEFAULT_RESOURCE_ICON = '📎'


async def _build_new_resources_text(new_items: list) -> str:
    """
    ساخت متن نوتیف «منابع جدید» — بازطراحی UX:
      • آیکون به‌جای پیشوند متنی نوع فایل (📄 به‌جای «PDF:»)
      • همه‌ی منابع نمایش داده می‌شوند، نه فقط چند مورد اول
      • گروه‌بندی بر اساس درس با هدر بولد
      • کل لیست داخل یک <blockquote> واحد تلگرام قرار می‌گیرد تا پیام
        فشرده و جمع‌وجور بماند (نه پراکنده روی کل صفحه)
      • توضیح فایل عیناً همان چیزی است که ادمین تایپ کرده (شامل هر
        اعتبار/نام تیم که خودش در انتهای توضیح نوشته) — بدون افزودن
        هیچ برچسب/فلش مصنوعی اضافه که معنای مستقلی ندارد
      • FIX جدید: علاوه بر محتوای علوم‌پایه (bs_content)، فایل‌های
        رفرنس (ref_files) هم پشتیبانی می‌شوند — هرکدام بسته به
        '_source' از تابع full-path مخصوص خودشان خوانده می‌شوند.
    """
    by_lesson: dict = {}
    lesson_order: list = []

    for item in new_items:
        source = item.get('_source', 'bs_content')
        if source == 'ref_files':
            path = await db.ref_get_file_full_path(str(item['_id']))
        else:
            path = await db.bs_get_content_full_path(str(item['_id']))
        lesson_name = path.get('lesson_name') or 'سایر'
        if lesson_name not in by_lesson:
            by_lesson[lesson_name] = []
            lesson_order.append(lesson_name)
        content_type = 'ref' if source == 'ref_files' else path.get('content_type', '')
        icon = _RESOURCE_ICONS.get(content_type, _DEFAULT_RESOURCE_ICON)
        desc = html.escape(path.get('description') or path.get('topic') or 'بدون عنوان')
        by_lesson[lesson_name].append(f"{icon} {desc}")

    lesson_blocks = []
    for lesson_name in lesson_order:
        header = f"📘 <b>{html.escape(lesson_name)}</b>"
        lesson_blocks.append(header + "\n" + "\n".join(by_lesson[lesson_name]))

    quote_body = "\n\n".join(lesson_blocks)
    title  = f"🆕 <b>{len(new_items)} منبع جدید اضافه شد</b>"
    footer = (
        "\n\n📚 مشاهده کامل ← بخش «منابع»\n"
        "<i>⚙️ خاموش‌کردن: 🔔 اعلان‌ها ← منابع جدید</i>"
    )

    # ایمنی: اگر (به‌ندرت) تعداد منابع خیلی زیاد باشد و پیام از سقف
    # ۴۰۹۶ کاراکتری تلگرام رد شود، فقط داخل Quote کوتاه می‌شود — نه وسط
    # پیام — تا تگ <blockquote> همیشه درست بسته شود و کل پیام رد نشود.
    shell_len = len(title) + len(footer) + len("\n\n<blockquote></blockquote>")
    budget    = 4096 - shell_len - 100
    if len(quote_body) > budget:
        quote_body = quote_body[:max(budget, 0)] + "\n…"

    return f"{title}\n\n<blockquote>{quote_body}</blockquote>{footer}"


async def _run_new_resources_notif(bot, force: bool = False) -> dict:
    """🛡 AUDIT-A2 — پوسته‌ی «قفل اجرا» روی هسته‌ی نوتیف منابع.

    سه راه ورود به این هسته وجود دارد: جاب زمان‌بندی‌شده، دکمه‌ی «🚀 ارسال
    فوری» در پنل ادمین (admin.py) و سیگنال outboxِ __FORCE_RES_NOTIF__؛
    هم‌پوشانی آن‌ها قبلاً می‌توانست یک batch را دو بار برای همان کاربران
    بفرستد (دورِ دوم هنوز last_sent را ثبت نکرده و `seen_by` هم به‌روز
    نشده). با ادعای یکتای `res_notif_run` دورِ دوم بی‌اثر برمی‌گردد؛ TTL
    ۱۵ دقیقه‌ای هم اگر پروسه میانه‌ی کار بمیرد قفل را آزاد می‌کند (وگرنه
    نوتیف برای همیشه خاموش می‌ماند).
    """
    if not await db.op_claim('res_notif_run', 'global', ttl_seconds=15 * 60):
        logger.warning("📚 new_resources_notif: دور قبلی هنوز در حال اجراست — این فراخوانی رد شد")
        return {'sent': False, 'reason': 'already_running'}
    try:
        return await _new_resources_run(bot, force=force)
    finally:
        await db.op_release('res_notif_run', 'global')


async def _new_resources_run(bot, force: bool = False) -> dict:
    """
    FIX جدید: هسته‌ی مشترک نوتیف منابع جدید — هم توسط جاب ساعتی و هم
    توسط دکمه‌ی «🚀 ارسال فوری» در پنل ادمین صدا زده می‌شود.
    force=True یعنی از چک فاصله‌ی زمانی (۲۴/۴۸/۷۲ ساعت) رد شو و همین
    الان بفرست، حتی اگه هنوز وقتش نشده.
    خروجی یک dict وضعیت برمی‌گرداند تا هم لاگ و هم دکمه‌ی دستی بتوانند
    نتیجه را نشان بدهند (چند نفر، چند مورد، یا چرا ارسال نشد).
    """
    try:
        interval_hours = await db.get_setting('resource_notif_interval_hours', 24)
        last_sent_str  = await db.get_setting('resource_notif_last_sent', None)

        if not force and last_sent_str:
            last_sent = parse_machine_datetime(last_sent_str)
            elapsed_hours = (now_utc() - last_sent.astimezone(timezone.utc)).total_seconds() / 3600
            if elapsed_hours < interval_hours:
                return {'sent': False, 'reason': 'not_due', 'elapsed_hours': round(elapsed_hours, 1),
                        'interval_hours': interval_hours}

        new_items = await db.get_unnotified_resources()
        if not new_items:
            # حتی اگه چیزی نبود، last_sent را آپدیت نمی‌کنیم — منتظر محتوای واقعی می‌مانیم
            return {'sent': False, 'reason': 'no_items'}

        run_id = await db.notif_run_start('new_resources')

        # 🌊 C1.5 — نوتیف scope-aware: آیتم‌ها پیشاً در DB لایه‌ی
        # get_unnotified_resources کلید '_intake' گرفته‌اند (resolver والد).
        # گروه‌بندی: '' = سراسری → همه‌ی کاربران واجد شرایط؛
        # کد ورودی → فقط دانشجویان همان ورودی (notif_users_by_intake).
        groups: dict = {}
        for _it in new_items:
            groups.setdefault(_it.get('_intake') or '', []).append(_it)

        sent, failed, failed_ids, total_recipients = 0, 0, [], 0
        first_message = None
        for _icode, _gitems in groups.items():
            text = await _build_new_resources_text(_gitems)
            if first_message is None:
                first_message = text
            if _icode:
                users = await db.notif_users_by_intake(_icode, 'new_resources')
            else:
                users = await db.notif_users('new_resources')
            if not users:
                continue
            total_recipients += len(users)
            # 🧠 موج N2 — دایجست تفکیک‌شدهٔ منابع/رفرنس + Smart Grouping:
            # موج خوانده‌نشدهٔ قبلی ـبه‌جای انباشت سطرهاـ تازه می‌شود (count).
            bs_items  = [i for i in _gitems if i.get('_source', 'bs_content') == 'bs_content']
            ref_items = [i for i in _gitems if i.get('_source') == 'ref_files']
            if bs_items:
                await db.inbox_add_many([
                    {'user_id': u['user_id'], 'type': 'new_resources',
                     'title': f"🆕 {len(bs_items)} منبع جدید اضافه شد",
                     'body': ('محتوای تازهٔ درسی (علوم پایه/جزوه) منتشر شد؛ '
                              'از بخش یادگیری بازش کنید.'),
                     'link': '/learn/resources?hl=new',
                     'group_key': 'digest_resources',
                     'group_title': '🆕 منابع جدید (×{count} موج)'}
                    for u in users if u.get('user_id')
                ])
            if ref_items:
                await db.inbox_add_many([
                    {'user_id': u['user_id'], 'type': 'new_references',
                     'title': f"🆕 {len(ref_items)} رفرنس جدید اضافه شد",
                     'body': ('کتاب/خواندنی‌های تازهٔ رفرنس رسید؛ '
                              'از بخش رفرنس‌ها بازش کنید.'),
                     'link': '/learn/references?hl=new',
                     'group_key': 'digest_refs',
                     'group_title': '🆕 رفرنس‌های جدید (×{count} موج)'}
                    for u in users if u.get('user_id')
                ])
            for u in users:
                ok = await safe_send(bot, u['user_id'], text, parse_mode='HTML')
                if ok:
                    sent += 1
                else:
                    failed += 1
                    failed_ids.append(u['user_id'])
                await asyncio.sleep(0.05)

        await db.notif_run_set_message(run_id, first_message or '(—)')

        bs_ids  = [item['_id'] for item in new_items if item.get('_source', 'bs_content') == 'bs_content']
        ref_ids = [item['_id'] for item in new_items if item.get('_source') == 'ref_files']
        await db.mark_resources_notified(bs_ids)
        await db.mark_ref_files_notified(ref_ids)
        await db.set_setting('resource_notif_last_sent', utc_now_iso())
        await db.set_setting('resource_notif_last_error', None)
        await db.notif_run_finish(run_id, sent, failed, total_recipients)
        if failed_ids:
            await db.notif_run_add_failed(run_id, failed_ids)
        logger.info(f"📚 نوتیف منابع جدید: {len(new_items)} مورد به {sent} نفر ارسال شد")
        return {'sent': True, 'items': len(new_items), 'users_sent': sent, 'users_failed': failed}
    except Exception as e:
        logger.error(f"new_resources_notif_job error: {e}")
        try:
            from utils import now_tehran
            await db.set_setting('resource_notif_last_error',
                                  f"{now_tehran_str()} | {e}")
        except Exception:
            pass
        return {'sent': False, 'reason': 'error', 'error': str(e)}


async def new_resources_notif_job(context: ContextTypes.DEFAULT_TYPE):
    """FIX جدید: wrapper سبک برای job زمان‌بندی‌شده — هسته‌ی اصلی به _run_new_resources_notif منتقل شد"""
    await _run_new_resources_notif(context.bot, force=False)


async def _discount_soldout_edit_task(bot, code: str):
    """
    ⛔ موج D2 — ادیت همگانی «اتمام موجودی»:
    همه‌ی پیام‌های کمپینِ این کد (در هر دو مسیر بات و وب) که مرجعشان در
    سند کمپین ذخیره شده، به متن «ظرفیت تکمیل شد» (بدون دکمه‌ی CTA) ادیت
    می‌خورند. RetryAfter با صبر دقیق + گام ۰٫۰۵ثانیه؛ پیام حذف‌شده/
    از‌دست‌رفته نادیده گرفته می‌شود. ایدمپوتنت: هر کمپین با فلگ
    soldout_marked فقط یک‌بار پردازش می‌شود.
    """
    from telegram.error import RetryAfter, BadRequest, TimedOut, NetworkError
    try:
        discount = await db.discount_get(code)
        if not discount:
            return
        from discount_campaign import build_soldout_message
        soldout = build_soldout_message(discount)
        bcasts = await db.discount_bcast_with_msgs(code)
        if not bcasts:
            return
        total = edited = skipped = 0
        for bc in bcasts:
            refs = bc.get('sent_msgs') or []
            bc_edited = 0
            for ref in refs:
                total += 1
                done = False
                for _attempt in range(3):
                    try:
                        await bot.edit_message_text(
                            chat_id=ref['c'], message_id=ref['m'],
                            text=soldout, parse_mode='HTML', reply_markup=None)
                        done = True
                        break
                    except RetryAfter as e:
                        await asyncio.sleep(e.retry_after + 0.5)
                        continue
                    except BadRequest:
                        break  # «پیام پیدا نشد»/«محتوا یکسان» — نادیده
                    except (TimedOut, NetworkError):
                        await asyncio.sleep(1.5)
                        continue
                    except Exception:
                        break
                if done:
                    edited += 1
                    bc_edited += 1
                else:
                    skipped += 1
                await asyncio.sleep(0.05)  # گام‌بندی نرخ تلگرام
            await db.discount_bcast_update(bc['broadcast_id'], {
                'soldout_marked': True,
                'soldout_at': utc_now_iso(),
                'soldout_edited': bc_edited,
            })
        logger.info(f"⛔ D2 soldout edit: {code} → ✅{edited} ⏭{skipped} (مجموع {total})")
        try:
            from utils import send_audit_log
            await send_audit_log(
                bot, 'system', 'سیستم کمپین', 0,
                f"⛔ کد تخفیف {code} تکمیل ظرفیت شد — {edited} پیام کمپین به «اتمام موجودی» ادیت شد",
                module='Discounts', severity='INFO',
                target_label=code, tags=['اتمام_ظرفیت_کد', 'کمپین'])
        except Exception:
            pass
    except Exception as e:
        logger.error(f"_discount_soldout_edit_task error ({code}): {e}")


async def mini_app_outbox_job(context: ContextTypes.DEFAULT_TYPE):
    """
    🔴 FIX حیاتی: پردازش صف «bot_notifications» که بک‌اند Mini App
    (FastAPI) توش پیام می‌ذاره — تأیید/رد/تعلیق/بلاک کاربر، پاسخ
    تیکت، تغییر زمان کلاس، نمره‌ی جدید، broadcast و... .
    قبل از این job، هیچ‌چیزی این کالکشن رو نمی‌خوند — یعنی این پیام‌ها
    فقط توی دیتابیس می‌موندن و هرگز واقعاً برای کاربر ارسال نمی‌شدن.
    از فیلد send_at هم پشتیبانی می‌کنه — یعنی broadcast زمان‌دار هم از
    همین صف رد می‌شه، فقط تا زمان مقرر sent:False می‌مونه.
    """
    try:
        coll = db.client["medicalbot"]["bot_notifications"]
        now_iso = utc_now_iso()
        cursor = coll.find({
            "sent": False,
            "$or": [{"send_at": {"$exists": False}}, {"send_at": None}, {"send_at": {"$lte": now_iso}}],
        }).limit(200)
        docs = await cursor.to_list(200)
        for d in docs:
            text = d.get("text", "")

            # 🧠 موج N2 — Deep Link: هر صف که link دارد،
            # دکمه‌ی «📱 باز کردن در هامزیار» (web_app) می‌گیرد
            _dl_kb = webapp_kb(d.get("link")) if d.get("link") else None

            # ── سیگنال ارسال فوری اعلان منابع از Web Admin ──
            # اجرای واقعی باید در process ربات انجام شود چون bot instance
            # فقط این‌جا در دسترس است. نتیجه همیشه مصرف و به درخواست‌کننده
            # گزارش می‌شود تا سیگنال در چرخه‌ی retry بی‌نهایت نماند.
            if text == "__FORCE_RES_NOTIF__":
                try:
                    result = await _run_new_resources_notif(context.bot, force=True)
                    await coll.update_one({"_id": d["_id"]}, {"$set": {
                        "sent": True, "sent_at": utc_now_iso(),
                        "result": result,
                    }})
                    if result.get("sent"):
                        msg = (
                            "✅ <b>ارسال فوری اعلان منابع انجام شد</b>\n\n"
                            f"📚 منابع: {result.get('items', 0)}\n"
                            f"👥 موفق: {result.get('users_sent', 0)}\n"
                            f"❌ ناموفق: {result.get('users_failed', 0)}"
                        )
                    elif result.get("reason") == "no_items":
                        msg = "ℹ️ منبع اعلام‌نشده‌ای در صف نبود."
                    elif result.get("reason") == "already_running":
                        msg = "⚠️ یک دور ارسال قبلاً همین حالا در جریان است؛ این درخواست رد شد."
                    else:
                        msg = ("❌ ارسال فوری انجام نشد.\n"
                               f"<code>{html.escape(str(result.get('error') or result.get('reason') or 'نامشخص')[:300])}</code>")
                    await safe_send(context.bot, d["chat_id"], msg, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"__FORCE_RES_NOTIF__ failed: {e}")
                    await coll.update_one({"_id": d["_id"]}, {"$set": {
                        "sent": True, "failed": True, "error": str(e)[:200],
                        "sent_at": utc_now_iso(),
                    }})
                    try:
                        await safe_send(context.bot, d["chat_id"],
                                        "❌ اجرای ارسال فوری اعلان منابع ناموفق بود.")
                    except Exception:
                        pass
                continue

            # ── سیگنال درخواست خروجی اکسل از پنل وب ──
            # قبلاً همه پیام‌های __* به‌صورت skipped رد می‌شدند و
            # خروجی هرگز به ادمین نمی‌رسید (فیچر مرده). حالا مصرف می‌شود.
            if text == "__EXCEL_EXPORT__":
                try:
                    from excel_report import build_database_excel
                    buf, fname, caption, _counts = await build_database_excel()
                    buf.seek(0)
                    await context.bot.send_document(
                        chat_id=d["chat_id"], document=buf,
                        filename=fname, caption=caption, parse_mode="HTML",
                    )
                    await coll.update_one({"_id": d["_id"]}, {"$set": {
                        "sent": True, "sent_at": utc_now_iso()}})
                except Exception as e:
                    logger.error(f"__EXCEL_EXPORT__ failed: {e}")
                    # FIX باگ پنهان: قبلاً sent:False می‌ماند و پیام هر چرخه
                    # بی‌نهایت retry می‌شد. حالا مصرف‌شده علامت می‌خورد و
                    # به درخواست‌کننده هم اطلاع می‌دهیم.
                    await coll.update_one({"_id": d["_id"]}, {"$set": {
                        "sent": True, "failed": True,
                        "error": str(e)[:200],
                        "sent_at": utc_now_iso(),
                    }})
                    try:
                        await safe_send(context.bot, d["chat_id"],
                            "❌ ساخت فایل اکسل ناموفق بود — جزئیات در لاگ سرور.")
                    except Exception:
                        pass
                continue

            # ── سیگنال درخواست فایل پشتیبان از پنل وب (فاز B) ──
            # الگوی مشترک با اکسل: وب می‌نویسد، ربات می‌سازد و می‌فرستد.
            if text.startswith("__BACKUP_REQUEST__"):
                try:
                    section = text.split(":", 1)[1] if ":" in text else "all"
                    from backup import send_backup_from_web
                    total = await send_backup_from_web(
                        context.bot, d["chat_id"], section)
                    await coll.update_one({"_id": d["_id"]}, {"$set": {
                        "sent": True, "sent_at": utc_now_iso()}})
                    logger.info(
                        f"💾 web backup sent: section={section} records={total}")
                except Exception as e:
                    logger.error(f"__BACKUP_REQUEST__ failed: {e}")
                    await coll.update_one({"_id": d["_id"]}, {"$set": {
                        "sent": True, "failed": True,
                        "error": str(e)[:200],
                        "sent_at": utc_now_iso(),
                    }})
                    try:
                        await safe_send(context.bot, d["chat_id"],
                            "❌ ساخت فایل پشتیبان ناموفق بود — جزئیات در لاگ سرور.")
                    except Exception:
                        pass
                continue

            # ── ⛔ موج D2 — سیگنال اتمام ظرفیت کد تخفیف ──
            # با آخرین مصرف (گذار اتمیک max-1→max) دقیقاً یک‌بار نوشته می‌شود؛
            # پیام‌های کمپینِ ذخیره‌شده به «اتمام موجودی» ادیت می‌خورند.
            if text.startswith("__DISCOUNT_EXHAUSTED__"):
                try:
                    _code = text.split(":", 1)[1] if ":" in text else ""
                    await coll.update_one({"_id": d["_id"]}, {"$set": {
                        "sent": True, "sent_at": utc_now_iso()}})
                    if _code:
                        # 🛡 AUDIT-M1 — مرجع + لاگ خطا (قبلاً تسک بی‌صاحب بود)
                        spawn_bg(_discount_soldout_edit_task(context.bot, _code),
                                 'discount_soldout_edit')
                except Exception as e:
                    # 🛡 AUDIT-A3 — مثل الگوی __EXCEL_EXPORT__: حتی در شکست هم
                    # مصرف می‌شود، وگرنه سیگنال هر ۲۰ ثانیه تا ابد تکرار می‌شود.
                    logger.error(f"__DISCOUNT_EXHAUSTED__ failed: {e}")
                    await coll.update_one({"_id": d["_id"]}, {"$set": {
                        "sent": True, "failed": True, "error": str(e)[:200],
                        "sent_at": utc_now_iso(),
                    }})
                continue

            # سایر سیگنال‌های داخلی (__*) متنی نیستند — skip
            if text.startswith("__"):
                await coll.update_one({"_id": d["_id"]}, {"$set": {"sent": True, "skipped": True}})
                continue
            # 📢 Campaign payload از renderer واحد Bot/Web عبور می‌کند؛
            # پیام‌های عادی قدیمی همچنان safe_send خودشان را دارند.
            campaign = d.get("campaign_id")
            if campaign and d.get("payload"):
                from broadcast_service import send_payload, record_delivery, refresh_campaign
                if not d.get("inbox_mirrored"):
                    raw_body = d["payload"].get("text") or d["payload"].get("caption") or ""
                    inbox_body = re.sub(r"<[^>]+>", "", raw_body).strip() or "پیام همگانی مدیریت"
                    await db.inbox_add(d["chat_id"], "announcement", "📢 اطلاعیه‌ی مدیریت",
                                       inbox_body, payload={"campaign_id": campaign})
                    await coll.update_one({"_id": d["_id"]},
                                          {"$set": {"inbox_mirrored": True}})
                try:
                    await send_payload(context.bot, d["chat_id"], d["payload"])
                    ok, error = True, ""
                except Exception as exc:
                    ok, error = False, str(exc)[:200]
                    logger.warning("broadcast campaign=%s uid=%s failed: %s",
                                   campaign, d.get("chat_id"), error)
                await coll.update_one({"_id": d["_id"]}, {"$set": {
                    "sent": True, "delivered": ok, "sent_at": utc_now_iso(),
                    "failed": not ok, "error": error,
                }})
                await record_delivery(campaign, success=ok, error=error)
                await refresh_campaign(campaign)
            else:
                # 🧠 N2 — دکمه‌ی Deep Link (اگر صف لینک داشت)
                ok, err, exc = await safe_send_ex(context.bot, d["chat_id"], text,
                                                  parse_mode="HTML", reply_markup=_dl_kb)
                if ok:
                    await coll.update_one({"_id": d["_id"]}, {"$set": {
                        "sent": True, "failed": False, "status": "sent",
                        "sent_at": utc_now_iso(),
                    }})
                else:
                    # 🛡 AUDIT-A3 — سه سرنوشت جدا، نه «sent:False» تا ابد:
                    # permanent ⇒ سند بسته می‌شود (skipped) تا صفِ مرده هر ۲۰
                    # ثانیه بی‌نهایت retry نشود و پنالتی تلگرام نسازد؛
                    # backoff ⇒ دقیقاً به اندازه‌ی retry_after عقب؛
                    # retry ⇒ بک‌آف نمایی تا ۴ تلاش، بعد «dead» (قابل دیدن در
                    # لاگ/پنل، نه گم‌شده در حلقه).
                    kind = safe_send_status(exc)
                    attempts = int(d.get("attempts") or 0) + 1
                    base = {"attempts": attempts, "failed": True,
                            "error": str(err or "")[:300]}
                    if kind == "permanent":
                        base.update({"sent": True, "skipped": True,
                                     "status": "skipped", "sent_at": utc_now_iso()})
                        logger.info(f"📤 outbox #{d['_id']} بسته شد (غیرقابل‌ارسال): "
                                    f"uid={d['chat_id']} err={str(err)[:120]}")
                    elif kind == "backoff":
                        delay = min(max(int(getattr(exc, "retry_after", 5) or 5), 5), 900)
                        base.update({"status": "backoff", "sent": False,
                                     "send_at": (now_utc() + timedelta(seconds=delay)).isoformat(timespec="microseconds")})
                    elif attempts >= 4:
                        base.update({"sent": True, "skipped": False, "status": "dead",
                                     "sent_at": utc_now_iso()})
                        logger.warning(f"📤 outbox #{d['_id']} بعد از {attempts} تلاش مرد "
                                       f"(uid={d['chat_id']}): {str(err)[:120]}")
                    else:
                        delay = 60 * (2 ** (attempts - 1))
                        base.update({"status": "retry", "sent": False,
                                     "send_at": (now_utc() + timedelta(seconds=delay)).isoformat(timespec="microseconds")})
                    await coll.update_one({"_id": d["_id"]}, {"$set": base})
        if docs:
            logger.info(f"📤 mini_app_outbox: {len(docs)} پیام پردازش شد")
    except Exception as e:
        logger.error(f"mini_app_outbox_job error: {e}")


async def subscription_expiry_job(context: ContextTypes.DEFAULT_TYPE):
    """
    FIX جدید: جاب روزانه‌ی سیستم اشتراک —
      ۱) اشتراک‌هایی که تاریخشون گذشته را expired می‌کند و به کاربر خبر می‌دهد
      ۲) یادآوری پلکانی: ۳ روز قبل و ۱ روز قبل (هرکدام فقط یک‌بار،
         دقیقاً مثل الگوی یادآوری امتحان)، همراه با دکمه‌ی «تمدید سریع»
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    # 🧠 موج N2 — ردیف دوم: بازکردن مستقیم صفحه‌ی تمدید در مینی‌اپ
    _sub_rows = [[InlineKeyboardButton("🔄 تمدید کن", callback_data='sub:back')]]
    _sk = webapp_kb('/me/subscription')
    if _sk: _sub_rows += _sk.inline_keyboard
    renew_kb = InlineKeyboardMarkup(_sub_rows)
    try:
        expired = await db.sub_expire_due()
        for s in expired:
            # 🔔 موج ۴.۹۰ — اینباکس (انقضا): تنها کانال قطعی دیده‌شدن
            await db.inbox_add(s['_id'], 'sub_expired',
                "⌛ اشتراکت تموم شد",
                "برای تمدید، از بخش اشتراک اقدام کن.",
                link='/me/subscription')
            await safe_send(
                context.bot, s['_id'],
                "⌛ <b>اشتراکت تموم شد</b>\n\n"
                "برای تمدید، دوباره از بخش «📚 منابع» یا «🧪 بانک سوال» اقدام کن.",
                parse_mode='HTML', reply_markup=renew_kb
            )
        if expired:
            logger.info(f"⌛ اشتراک {len(expired)} کاربر منقضی شد")

        for days_before, flag in ((3, 'reminder_3d_sent'), (1, 'reminder_1d_sent')):
            expiring = await db.sub_expiring_soon(days_before=days_before, flag_field=flag)
            for s in expiring:
                days_left = remaining_days(s['end_date'])
                icon = "🔴" if days_before == 1 else "⏳"
                # 🔔 موج ۴.۹۰ — اینباکس (یادآوری پایان اشتراک)
                await db.inbox_add(s['_id'], 'sub_expiring',
                    f"{icon} اشتراکت رو به پایانه",
                    f"{days_left} روز دیگه مونده — برای جلوگیری از وقفه، تمدید کن.",
                    link='/me/subscription')
                await safe_send(
                    context.bot, s['_id'],
                    f"{icon} <b>اشتراکت داره تموم می‌شه!</b>\n\n"
                    f"{days_left} روز دیگه مونده. اگه می‌خوای وقفه نیفته، از حالا تمدید کن.",
                    parse_mode='HTML', reply_markup=renew_kb
                )
                await db.sub_mark_reminder_sent(s['_id'], flag)
            if expiring:
                logger.info(f"⏳ یادآوری {days_before}روزه برای {len(expiring)} کاربر ارسال شد")
    except Exception as e:
        logger.error(f"subscription_expiry_job error: {e}")


async def subscription_expiry_sweep_job(context: ContextTypes.DEFAULT_TYPE):
    """🌊 W2 — sweep سبک هر ساعت: فقط expiredها را status می‌زند (بدون نوتیف تکراری).
    نوتیف اصلی روزانه ساعت ۹:۱۵ می‌ماند؛ این فقط خلأ ۲۴ساعته را پر می‌کند
    (کاربر ساعت ۰۹:۱۶ منقضی شود تا فردا بی‌خبر نماند)."""
    try:
        expired = await db.sub_expire_due()
        if expired:
            logger.info(f"⌛ sweep: {len(expired)} اشتراک منقضی شد (hourly)")
    except Exception as e:
        logger.warning(f"subscription_expiry_sweep error: {e}")

async def ticket_stale_job(context: ContextTypes.DEFAULT_TYPE):
    """🌊 W8/UX-04 — یادآوری تیکت‌های بازِ بدون پاسخ (هر ۶ ساعت).

    برای هر تیکت: به مسئول تخصیص‌یافته (وگرنه مالک) پیام می‌دهد؛
    اگر SLA هم رد شده باشد با پرچم 🔴. ضدتکرار با stale_nudged_at.
    """
    try:
        try:
            stale_h = max(1, int(await db.get_setting('ticket_stale_hours', 24) or 24))
        except Exception:
            stale_h = 24
        tickets = await db.tickets_needing_nudge(stale_h)
        if not tickets:
            return
        from time_utils import utc_now_iso
        now = utc_now_iso()
        for t in tickets:
            tid = t.get('ticket_id')
            sla = db.ticket_sla_info(t)
            target = int(t.get('assignee_id') or 0) or ADMIN_ID
            icon = '🔴' if sla.get('breached') else '⏳'
            extra = ' — <b>مهلت SLA گذشته!</b>' if sla.get('breached') else ''
            try:
                await safe_send(
                    context.bot, target,
                    f"{icon} <b>تیکت #{tid} بی‌پاسخ مانده</b>{extra}\n"
                    f"👤 {t.get('user_name', '')} — 📋 {t.get('subject', '')[:60]}",
                    parse_mode='HTML')
            except Exception:
                pass
            try:
                await db.tickets.update_one(
                    {'ticket_id': tid}, {'$set': {'stale_nudged_at': now}})
            except Exception:
                pass
        logger.info(f"🎫 ticket stale nudge: {len(tickets)}")
    except Exception as e:
        logger.warning(f"ticket_stale_job error: {e}")


async def wallet_reconcile_job(context: ContextTypes.DEFAULT_TYPE):
    """🌊 W2 — مغایرت‌گیری کیف پول هر ۳۰ دقیقه + گزارش به لاگ/ادمین.
    🌊 W7 — ضداسپم + توضیح‌دار: dismiss respected + cooldown + hash + mute + جزئیات انسانی.
    stuck pending قدیمی را فقط لاگ می‌کند (تصمیم دستی) — auto-complete نمی‌کند
    چون 증거 جبران نیازمند تایید انسانی است."""
    try:
        from time_utils import parse_machine_datetime as _parse_dt, now_utc as _now_utc, utc_now_iso as _utc_iso
        import hashlib, json as _json
        items = await db.wallet_reconcile_items(limit=20)
        if not items:
            return
        crit = [x for x in items if x.get('severity') == 'critical']
        if not crit:
            logger.info(f"wallet reconcile: {len(items)} warnings (no critical)")
            return
        logger.warning(f"💰 wallet reconcile {len(items)} items ({len(crit)} critical): {crit[:3]}")
        # ── W7: settings ──
        try:
            enabled = await db.get_setting("wallet_alert_enabled", True)
            if enabled is None:
                enabled = True
            if not enabled:
                logger.info("wallet reconcile: alerts disabled via setting")
                return
            muted_until = await db.get_setting("wallet_alert_muted_until", None)
            if muted_until:
                try:
                    if _parse_dt(muted_until) > _now_utc():
                        logger.info(f"wallet reconcile muted until {muted_until}")
                        return
                except Exception:
                    pass
            # attention dismissal for wallet_issues
            try:
                ddoc = await db.client["medicalbot"]["attention_dismissals"].find_one({"key": "wallet_issues"})
                if ddoc:
                    until = ddoc.get("dismissed_until")
                    dismissed = not until or _parse_dt(until) > _now_utc()
                    if dismissed:
                        logger.info(f"wallet reconcile suppressed by attention dismissal: {ddoc.get('reason','')}")
                        return
            except Exception:
                pass
            # cooldown + hash dedup
            cooldown = int(await db.get_setting("wallet_alert_cooldown_hours", 6) or 6)
            last_at = await db.get_setting("wallet_alert_last_at", None)
            last_hash = await db.get_setting("wallet_alert_last_hash", None)
            cur_hash = hashlib.sha256(_json.dumps(sorted([(c.get("type"), c.get("user_id"), int(c.get("amount") or 0)) for c in crit]), sort_keys=True).encode()).hexdigest()[:16]
            if last_hash and last_at and last_hash == cur_hash:
                try:
                    elapsed_h = (_now_utc() - _parse_dt(last_at).astimezone(__import__('datetime').timezone.utc)).total_seconds() / 3600
                    if elapsed_h < cooldown:
                        logger.info(f"wallet reconcile throttled: same {len(crit)} crit within {elapsed_h:.1f}h < {cooldown}h")
                        return
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"wallet reconcile settings check failed: {e}")
            cur_hash = "unknown"
            cooldown = 6
        # ── W7: ساخت پیام توضیح‌دار (تا ۳ مورد، human-readable) ──
        try:
            # نام کاربران برای جزئیات
            uids = list({int(c.get("user_id") or 0) for c in crit[:5] if c.get("user_id")})
            names = {}
            if uids:
                for u in await db.users.find({"user_id": {"$in": uids}}, {"user_id": 1, "name": 1}).to_list(20):
                    names[int(u["user_id"])] = u.get("name") or ""
            _type_fa = {
                "wallet_balance_mismatch": "مغایرت حسابداری",
                "refund_without_wallet_credit": "بازگشت وجه بدون اعتبار",
                "topup_without_wallet_credit": "شارژ بدون اعتبار",
                "wallet_debit_without_payment": "کسر بی‌پشتوانه",
                "wallet_tx_stuck_pending": "تراکنش معلق",
            }
            lines = []
            for c in crit[:3]:
                uid = int(c.get("user_id") or 0)
                nm = names.get(uid) or f"کاربر {uid}"
                tp = _type_fa.get(c.get("type"), c.get("type") or "نامشخص")
                amt = c.get("amount")
                if amt is not None:
                    lines.append(f"• {nm} — {tp} ({int(amt):,} تومان)")
                else:
                    lines.append(f"• {nm} — {tp}")
            if len(crit) > 3:
                lines.append(f"… و {len(crit)-3} مورد دیگر")
            detail = "\n".join(lines) if lines else ""
            text = f"⚠️ مغایرت کیف پول: {len(crit)} مورد بحرانی"
            if detail:
                text += "\n" + detail
            text += "\n\n📊 مغایرت‌گیری: /subscriptions?tab=reconcile  |  👛 کیف پول‌ها: /subscriptions?tab=wallets"
            text += "\n🔕 بستن هشدار تا ۲۴ساعته: /api/web-admin/attention/dismiss  یا از داشبورد «نیازمند اقدام» ببندید"
            await db.bot_notifs.insert_one({'type': 'wallet_reconcile', 'chat_id': __import__('os').getenv('ADMIN_ID','0'), 'text': text, 'sent': False, 'created_at': _utc_iso()})
            # ذخیره برای dedup بعدی
            try:
                await db.set_setting("wallet_alert_last_at", _utc_iso())
                await db.set_setting("wallet_alert_last_hash", cur_hash)
            except Exception:
                pass
        except Exception as ie:
            logger.warning(f"wallet reconcile notify failed: {ie}")
            try:
                await db.bot_notifs.insert_one({'type': 'wallet_reconcile', 'chat_id': __import__('os').getenv('ADMIN_ID','0'), 'text': f"⚠️ مغایرت کیف پول: {len(crit)} مورد بحرانی", 'sent': False, 'created_at': _utc_iso()})
            except: pass
    except Exception as e:
        logger.warning(f"wallet_reconcile_job error: {e}")

async def audit_retention_job(context: ContextTypes.DEFAULT_TYPE):
    """🗄 W4/DB-02 — retention روزانه‌ی audit_logs + هشدار حجم.

    اگر audit_retention_days=0 باشد نگهداری نامحدود است (apply_retention
    خودش ۰ برمی‌گرداند). آستانه‌ی هشدار حجم با audit_log_alert_count
    قابل تنظیم است (پیش‌فرض ۵۰۰٬۰۰۰ سند)."""
    try:
        deleted = await db.audit_retention_cleanup()
        try:
            await db.set_setting("audit_retention_last_run",
                                 __import__("time_utils").utc_now_iso())
            await db.set_setting("audit_retention_last_deleted",
                                 int(deleted or 0))
        except Exception:
            pass
        try:
            alert_at = int(
                await db.get_setting("audit_log_alert_count", 500000)
                or 500000)
        except Exception:
            alert_at = 500000
        if alert_at > 0:
            total = await db.audit_logs.count_documents({})
            if total > alert_at:
                logger.warning(
                    "audit_logs volume %d exceeds alert threshold %d",
                    total, alert_at)
        logger.info("audit retention cleanup deleted=%d", deleted)
    except Exception as e:
        logger.warning(f"audit_retention error: {e}")


async def zarinpal_cleanup_job(context: ContextTypes.DEFAULT_TYPE):
    """🌊 W2 — پرداخت‌های zarinpal_pending که بیش‌از ۱ ساعت رها شده → لغو + آزادسازی کد تخفیف."""
    try:
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        pending = await db.sub_payments.find({'status': 'zarinpal_pending', 'submitted_at': {'$lt': cutoff}}).to_list(50)
        for doc in pending:
            try:
                flipped = await db.sub_payments.update_one({'_id': doc['_id'], 'status': 'zarinpal_pending'}, {'$set': {'status': 'cancelled', 'cancel_reason': 'timeout 1h', 'cancelled_at': __import__('time_utils').utc_now_iso()}})
                code = (doc.get('discount_code') or '').strip()
                if code:
                    await db.discount_release(code, user_id=doc.get('user_id'))
                # 🌊 W3/MISS-02 — آزادسازی فوری hold درگاه اگر کاربر پول داده
                # ولی verify نکرده بود؛ best-effort و ثبت نتیجه روی سند.
                if flipped.modified_count == 1 and doc.get('zarinpal_authority'):
                    try:
                        from payments.zarinpal import zarinpal_reverse as _zp_rev
                        rev = await _zp_rev(doc['zarinpal_authority'])
                        await db.sub_payments.update_one({'_id': doc['_id']}, {'$set': {
                            'zarinpal_reversed': bool(rev.get('ok')),
                            'zarinpal_reverse_code': rev.get('code'),
                            'zarinpal_reversed_at': __import__('time_utils').utc_now_iso()}})
                    except Exception as e2:
                        logger.warning(f"zarinpal reverse failed {doc.get('_id')}: {e2}")
                logger.info(f"zarinpal cleanup cancelled {doc['_id']} authority={doc.get('zarinpal_authority')}")
            except Exception as e:
                logger.warning(f"zarinpal cleanup failed {doc.get('_id')}: {e}")
    except Exception as e:
        logger.warning(f"zarinpal_cleanup error: {e}")

async def auto_backup_job(context: ContextTypes.DEFAULT_TYPE):
    """
    FIX جدید: بکاپ خودکار روزانه. این job هر ساعت اجرا می‌شود و
    خودش تشخیص می‌دهد آیا الان همان ساعتی است که ادمین تنظیم کرده
    (auto_backup_hour، با timezone رسمی Asia/Tehran) — تا بتوان از پنل
    ادمین ساعت را آزادانه تغییر داد بدون نیاز به ری‌استارت ربات.
    """
    try:
        enabled = await db.get_setting('auto_backup_enabled', False)
        if not enabled:
            return

        target_hour = await db.get_setting('auto_backup_hour', 3)
        tehran_now = now_tehran()
        if tehran_now.hour != target_hour:
            return

        # جلوگیری از اجرای تکراری در همان ساعت (چون job هر ساعت چک می‌شود)
        last_run = await db.get_setting('auto_backup_last_run', None)
        if last_run:
            last_dt = parse_machine_datetime(last_run)
            if (now_utc() - last_dt.astimezone(timezone.utc)).total_seconds() < 3600 * 20:
                return  # کمتر از ۲۰ ساعت از آخرین بکاپ گذشته — رد کن

        # 🌊 W3 — streaming backup to temp file (memory-safe) + send
        from backup import build_full_backup_file
        from utils import send_audit_log
        import os as _os
        temp_path, _auto_summary = await build_full_backup_file()
        # 🌊 W5/REL-04 — گیت حجم: ارسالِ محکوم‌به‌شکستِ بالای ۵۰MB تلگرام
        # انجام نمی‌شود؛ خطا به مسیر consec_fail/alert موجود می‌رود.
        try:
            import os as _sz
            _size = _sz.path.getsize(temp_path)
        except Exception:
            _size = 0
        if _size >= 48 * 1024 * 1024:
            raise RuntimeError(
                f"backup file too large for Telegram ({_size // (1024 * 1024)}MB ≥ 48MB) — "
                f"offsite لازم است (docs/runbook.md §۸)")
        if _size >= 40 * 1024 * 1024:
            logger.warning("backup size %dMB approaching Telegram 50MB limit",
                           _size // (1024 * 1024))
        # 🌊 W5/REL-04 — رمزنگاری بکاپ خودکار اگر کلید تنظیم شده باشد
        _enc_suffix = ""
        try:
            from utils_crypto import is_encryption_enabled, encrypt_bytes
            if is_encryption_enabled():
                with open(temp_path, 'rb') as _rf:
                    _enc = encrypt_bytes(_rf.read())
                if _enc is not None:
                    with open(temp_path, 'wb') as _wf:
                        _wf.write(_enc)
                    _enc_suffix = ".enc"
                    logger.info("auto backup encrypted (Fernet)")
        except Exception as _ee:
            logger.warning(f"backup encryption skipped: {_ee}")
        try:
            # send file without holding json string in RAM
            from backup import build_backup_caption
            try:
                _send_size = _os.path.getsize(temp_path)
            except Exception:
                _send_size = _size
            with open(temp_path, 'rb') as f:
                now_str = now_tehran().strftime('%Y%m%d_%H%M')
                fname = f"backup_auto_{now_str}.json.gz{_enc_suffix}"
                _cap = build_backup_caption(
                    {'summary': _auto_summary or {}}, _send_size,
                    encrypted=bool(_enc_suffix))
                # use bot.send_document with file handle
                sent = await context.bot.send_document(
                    chat_id=ADMIN_ID, document=f, caption=_cap,
                    filename=fname, parse_mode='HTML')
                msg_id = getattr(sent, 'message_id', None)
        finally:
            try: _os.unlink(temp_path)
            except: pass
        # summary واقعی برای audit log و history (دیگر حدس صفر نیست)
        data = {"summary": _auto_summary or {}}
        await db.set_setting('auto_backup_last_run', utc_now_iso())
        logger.info("💾 بکاپ خودکار با موفقیت ارسال شد")
        # 🛡 AUDIT-V2 — نگهداریِ کرانه‌دار: سابقه‌ی بکاپ‌های خودکار در یک
        # لیست bounded نگه داشته می‌شود و پیام‌های قدیمی‌تر از
        # BACKUP_AUTO_KEEP (پیش‌فرض ۱۴) best-effort پاک می‌شوند.
        # سه قاعده‌ی ایمنی: (۱) فقط پیام‌های خودِ همین job (msg_id که
        # خودمان گرفته‌ایم) هدف قرار می‌گیرند؛ (۲) همیشه KEEP تایِ آخر
        # دست‌نخورده می‌ماند؛ (۳) مسیر پاک‌سازی در try مستقل است —
        # شکستِ آن هرگز بکاپ‌گیری موفق را ناموفق گزارش نمی‌کند.
        try:
            keep = max(3, int(os.getenv('BACKUP_AUTO_KEEP', '14') or 14))
            hist = await db.get_setting('auto_backup_history', []) or []
            if not isinstance(hist, list):
                hist = []
            hist.append({'at': utc_now_iso(), 'msg_id': msg_id,
                         'size_kb': (int(_send_size) // 1024) if '_send_size' in dir() and _send_size else None,
                         'users': (data.get('summary') or {}).get('users', 0)})
            hist = hist[-(keep * 3):]                       # کرانه‌ی خودِ سابقه
            stale = hist[:-keep] if len(hist) > keep else []
            for row in stale:
                mid = row.get('msg_id')
                if not mid or row.get('deleted'):
                    continue
                try:
                    await context.bot.delete_message(ADMIN_ID, int(mid))
                    row['deleted'] = True
                except Exception as de:
                    logger.debug(f"پاک‌سازی بکاپ کهنه ناموفق (بی‌خطر): {de}")
            await db.set_setting('auto_backup_history', hist)
            await db.set_setting('auto_backup_consec_fail', 0)
        except Exception as re_err:
            logger.warning(f"auto_backup retention خطای جزئی: {re_err}")
        # FIX جدید طبق سند: بکاپ‌گیری باید لاگ شود — این یک job
        # سیستمی است (نه عمل یک ادمین خاص)، پس actor خود ربات است.
        summary = data.get('summary', {})
        await send_audit_log(
            context.bot, 'admin', 'سیستم (Job خودکار)', 0,
            "بکاپ‌گیری خودکار", module='Backup', severity='WARNING',
            actor_role='سیستم',
            details=f"کاربران: {summary.get('users',0)} | سوالات: {summary.get('questions',0)}",
            tags=['بکاپ_خودکار']
        )
    except Exception as e:
        # 🛡 AUDIT-V2 — شکست‌ها شمرده می‌شوند و بعد از ۳ بار به ادمین
        # گفته می‌شود؛ قبلاً یک بکاپ‌گیریِ خراب می‌توانست ماه‌ها بی‌صدا بماند.
        logger.error(f"auto_backup_job error: {e}")
        try:
            nf = int(await db.get_setting('auto_backup_consec_fail', 0) or 0) + 1
            await db.set_setting('auto_backup_consec_fail', nf)
            if nf in (3, 7):
                from utils import safe_send as _ss
                await _ss(context.bot, ADMIN_ID,
                          f"⚠️ بکاپ خودکار {nf} بار پشت‌سرهم ناموفق بود.\n"
                          f"آخرین خطا: {str(e)[:200]}")
        except Exception:
            pass
        try:
            # 🛡 AUDIT-§۲۴/§۸۲ — در مسیر خطا هم safe_send: اگر ادمین بات را
            # بلاک کرده باشد یا متنِ خطا HTML را بشکند، خودِ اطلاع‌رسانی
            # نباید دوباره منفجر شود (قبلاً خطای دوم در except بی‌صدا می‌مرد).
            await safe_send(
                context.bot, ADMIN_ID,
                f"⚠️ <b>خطا در بکاپ خودکار</b>\n<code>{html.escape(str(e)[:300])}</code>",
                parse_mode='HTML'
            )
            # FIX جدید: خطای بکاپ هم باید در Audit Log ثبت شود — CRITICAL
            from utils import send_audit_log
            await send_audit_log(
                context.bot, 'admin', 'سیستم (Job خودکار)', 0,
                "خطا در بکاپ خودکار", module='Backup', severity='CRITICAL',
                actor_role='سیستم', details=str(e)[:200],
                tags=['خطای_بکاپ']
            )
        except Exception as _be:
            # 🛡 AUDIT-§۲۰ — «pass» با دلیل: لاگ، نه سکوت
            logger.warning(f"auto_backup_job: اطلاع‌رسانی خطای بکاپ هم شکست خورد: {_be}")


async def weekly_report_job(context: ContextTypes.DEFAULT_TYPE):
    """
    FIX باگ مهم: گزارش هفتگی دیگر به پیوی شخصی ادمین ارشد ارسال
    نمی‌شود — طبق درخواست صریح، فقط به گروه لاگ ادمین می‌رود.
    اگر گروه تنظیم نشده باشد، گزارش فقط در لاگ سرور ثبت می‌شود
    (و ارسالی به هیچ‌جا صورت نمی‌گیرد).
    """
    logger.info("📊 اجرای job گزارش هفتگی...")
    try:
        chat_id = await db.get_setting('log_group_admin', None)
        if not chat_id:
            logger.info("گزارش هفتگی: گروه لاگ ادمین تنظیم نشده — ارسالی صورت نگرفت.")
            return
        s = await db.weekly_report_stats()
        text = (
            "📊 <b>گزارش هفتگی ربات</b>\n"
            "━━━━━━━━━━━━━━━━\n\n"
            f"👥 کاربران جدید این هفته: <b>{s['new_users']}</b>\n"
            f"👤 کل کاربران تأییدشده: <b>{s['total_users']}</b>\n"
            f"🟢 کاربران فعال این هفته: <b>{s['active_users_count']}</b>\n"
            f"😴 کاربران غیرفعال (۱۴+ روز): <b>{s['inactive_count']}</b>\n\n"
            f"📚 پرطرفدارترین درس هفته: <b>{s['top_lesson']}</b>\n\n"
            f"🎫 تیکت باز فعلی: <b>{s['open_tickets']}</b>\n"
            f"✅ تیکت بسته‌شده این هفته: <b>{s['closed_week']}</b>\n"
            f"📨 کل تیکت‌های این هفته: <b>{s['total_tickets_week']}</b>\n\n"
            "<i>گزارش بعدی: یکشنبه آینده 🗓</i>"
        )
        await context.bot.send_message(int(chat_id), text, parse_mode='HTML')
    except Exception as e:
        logger.error(f"weekly_report_job error: {e}")


# ══════════════════════════════════════════════════
#  👑 جاب‌های Prestige (بستن هفته + یادآوری چالش آماده)
# ══════════════════════════════════════════════════

async def prestige_weekly_close_job(context: ContextTypes.DEFAULT_TYPE):
    """👑 بستن هفته‌ی پرستیژ — دوشنبه ۰۰:۰۵ تهران (یکشنبه ۲۰:۳۵ UTC).
    خود متد DB با پرچم weekly_closed:<week> کاملاً idempotent است."""
    logger.info("👑 اجرای job بستن هفته‌ی پرستیژ...")
    try:
        rep = await db.prestige_weekly_close()
        if rep.get('skipped'):
            return
        champ = rep.get('champion') or {}
        # DM نرم به قهرمان هفته (شکست ارسال، جاب را نمی‌شکند)
        if champ.get('uid'):
            try:
                await context.bot.send_message(
                    chat_id=int(champ['uid']),
                    text=("👑 <b>صدر جدول هفتگی مال تو شد!</b>\n\n"
                          f"این هفته با <b>{champ.get('weekly_xp', 0)}</b> XP قهرمان شدی. "
                          "جایزه‌ی +۱۰۰ XP و نشان «صدرنشین هفته» به حسابت نشست 🏅"),
                    parse_mode='HTML', reply_markup=webapp_kb('/leaderboard'))
            except Exception:
                pass
        try:
            await send_audit_log(
                context.bot, 'PRESTIGE', 'job:weekly_close', 0,
                'بستن هفته', 'prestige',
                details=(f"هفته {rep.get('week')} · ردیف‌ها {rep.get('rows', 0)} · "
                         f"قهرمان: {champ.get('name', '—')} ({champ.get('weekly_xp', 0)} XP)"),
                severity='INFO')
        except Exception:
            pass
    except Exception as e:
        logger.error(f"prestige_weekly_close_job error: {e}")


async def prestige_challenge_scan_job(context: ContextTypes.DEFAULT_TYPE):
    """⚔️ بررسی هفتگی چالش آماده — یکشنبه ۱۹:۴۰ تهران (۱۶:۱۰ UTC).
    به هر کاربر واجد شرط (ready) حداکثر یک‌بار در هفته یک اینباکس می‌رود."""
    logger.info("⚔️ اجرای job اسکن چالش آماده...")
    try:
        today = db._tehran_today()
        business_week = week_key_tehran(parse_gregorian_date(today))
        cursor = db.users.find({'approved': True,
                                'effective_xp': {'$gte': 2400}})
        docs = await cursor.to_list(5000)
        sent = 0
        for u in docs:
            try:
                uid = int(u.get('user_id') or 0)
                if not uid or (u.get('challenge_notified_week') or '') == business_week:
                    continue
                st = await db.prestige_state(uid, lite=True)
                ch = (st or {}).get('challenge') or {}
                if ch.get('mode') != 'ready':
                    continue
                # 🧠 N2 — سینک‌فیکس: رویداد آمادگی چالش فقط Inbox بود؛
                # الان تک‌منبع (Inbox + DM با دکمه‌ی Deep Link) می‌رود
                await db.notify_user(
                    uid, 'challenge',
                    title=f"⚔️ چالش ارتقا آمده: {ch.get('icon', '')} {ch.get('title', '')}",
                    body=('استخر ۲۰ سؤال با قبولی ۸۰٪ — مهلت ۲۴ ساعت پس از شروع. '
                          'هر وقت آماده بودی از مرکز آزمون برو سراغش! 💪'),
                    link='/learn/exams?promo=1',
                    dm=(f"⚔️ <b>چالش ارتقا رسید: {ch.get('icon', '')} {ch.get('title', '')}</b>\n\n"
                        'استخر ۲۰ سؤال، قبولی با ۸۰٪ و مهلت ۲۴ ساعت پس از شروع. '
                        'هر وقت آماده بودی شروعش کن! 💪'))
                await db.users.update_one({'user_id': uid},
                    {'$set': {'challenge_notified_week': business_week}})
                sent += 1
            except Exception:
                continue
        if sent:
            logger.info(f"⚔️ challenge scan: {sent} کاربر مطلع شدند")
    except Exception as e:
        logger.error(f"prestige_challenge_scan_job error: {e}")


# ══════════════════════════════════════════════════
#  Error Handler مرکزی
# ══════════════════════════════════════════════════

# FIX باگ: این خطاها کاملاً طبیعی و بی‌خطر هستند — رفتار عادی
# کاربران (کلیک روی دکمه قدیمی، زدن دکمه‌ای که چیزی تغییر نمی‌دهد)
# نه نشانه‌ی یک مشکل واقعی. بدون این فیلتر، هر کدام پیوی شخصی
# ادمین ارشد را شلوغ می‌کرد و خطاهای واقعی در میانشان گم می‌شدند.
SILENT_ERRORS = (
    'Query is too old',
    'query id is invalid',
    'Message is not modified',
    'MESSAGE_ID_INVALID',
    'message to edit not found',
    'message to delete not found',
    "Message can't be deleted",
    'Have no rights to send a message',
    # 🌊 WA3 — تداخل getUpdates هنگام redeploy/روی‌ل‌اوور Railway: دو نمونه‌ی
    # موقتِ ربات (قدیمی در حال خاموش‌شدن + جدید) هم‌زمان poll می‌کنند؛ چند
    # ثانیه بعد خودکار حل می‌شود. پیویِ مالک نباید با این نویز بمباردان شود.
    'terminated by other getUpdates request',
)

# 🛡 AUDIT-§۷۸ — «نویزِ گذرا» با «خطای واقعی» قاطی نشود.
# لاگ پروداکشن (Railway، ۱۴۰۵/۰۶/۱۱): برای uid 7101933086 یک
# `⚠️ خطای ربات` رفت که متنش دقیقاً `httpx.ConnectError:` بود — یعنی
# استثنای شبکه‌ی بدون‌پیام، با <code> خالی. دو ایراد یکی‌جا:
#   ۱) این‌ها خطای برنامه نیستند (blip خروجیِ DNS/TLS روی پود؛ PTB خودش
#      retry می‌کند) و در انبوه، خطای واقعی را در پیوی ادمین گم می‌کنند؛
#   ۲) بعضی استثناها `str()` تهی دارند ⇒ هشدارِ بی‌محتوا.
# رفتار جدید: لاگِ warning + شمارش، و به‌جای DMِ موردی، **یک خلاصه** در
# هر پنجره — و متن هشدار همیشه `نامِ کلاس: پیام` است، حتی اگر پیام خالی باشد.
TRANSIENT_ERRORS = (
    "httpx.ConnectError", "httpx.ConnectTimeout", "httpx.ReadTimeout",
    "httpx.WriteTimeout", "httpx.PoolTimeout", "httpx.RemoteProtocolError",
    "httpx.ReadError", "httpx.WriteError", "Connection error",
    "Server disconnected", "Temporary failure in name resolution",
    "Network is unreachable", "Connection reset by peer", "timed out",
)
# نامِ کلاس‌هایی که همیشه گذرا هستند. عمداً isinstance نه: در PTB 21.3
# `BadRequest ⊂ NetworkError` است و با isinstance، خطای منطقیِ API هم
# «گذرا» برچسب می‌خورد و گم می‌شد.
TRANSIENT_TYPES = {
    "ConnectError", "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout",
    "RemoteProtocolError", "ReadError", "WriteError", "ProxyError", "TimedOut",
    "ServerError",
}
TRANSIENT_WINDOW_S = 600          # هر ۱۰ دقیقه حداکثر یک خلاصه به ادمین
_TRANSIENT_STATE = {"count": 0, "sample": "", "last_report": 0.0}


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    err_str = str(context.error)
    # 🛡 AUDIT-§۷۸ — `httpx.ConnectError: ` در لاگ یعنی str() تهی بود؛ پس
    # همیشه نامِ کلاس جلویش می‌آید و اگر متن نبود همان repr می‌نشیند.
    err_name = type(context.error).__name__
    err_body = err_str.strip() or (repr(context.error).strip() or "")
    err_line = f"{err_name}: {err_body}" if err_body else (err_name or "Unknown error")

    # خطای بی‌خطر — فقط در لاگ سرور، بدون پیوی به ادمین
    if any(e in err_str for e in SILENT_ERRORS):
        logger.warning(f"⚠️ Silent error (نادیده گرفته شد): {err_str[:150]}")
        if isinstance(update, Update) and update.callback_query:
            try:
                await update.callback_query.answer()
            except Exception:
                pass
        return

    # 🛡 AUDIT-§۷۸ — گذرا؟ لاگ + شمارش + خلاصه‌ی نرخ‌دار؛ بدون DMِ موردی
    if err_name in TRANSIENT_TYPES or any(t in err_line for t in TRANSIENT_ERRORS):
        _TRANSIENT_STATE["count"] = int(_TRANSIENT_STATE["count"]) + 1
        _TRANSIENT_STATE["sample"] = err_line[:200]
        logger.warning(f"🌐 خطای گذرای شبکه (PTB تلاش مجدد می‌کند): {err_line[:200]}")
        if isinstance(update, Update) and update.callback_query:
            try:
                await update.callback_query.answer(
                    text="⏳ اتصال کوتاه بود؛ یک لحظه دیگر دوباره بزن.", show_alert=False)
            except Exception:
                pass
        now_ts = asyncio.get_running_loop().time()
        if now_ts - float(_TRANSIENT_STATE["last_report"]) >= TRANSIENT_WINDOW_S:
            _TRANSIENT_STATE["last_report"] = now_ts
            n = int(_TRANSIENT_STATE["count"])
            _TRANSIENT_STATE["count"] = 0
            if ADMIN_ID and n:
                await safe_send(
                    context.bot, ADMIN_ID,
                    f"🌐 <b>{n} خطای گذرای شبکه</b> در {TRANSIENT_WINDOW_S // 60} دقیقه‌ی اخیر\n"
                    f"نمونه: <code>{html.escape(str(_TRANSIENT_STATE['sample']))}</code>\n"
                    "خودِ ربات دوباره تلاش می‌کند؛ فقط اگر پیوسته تکرار شد "
                    "خروجی شبکه‌ی سرویس (DNS/TLS) را بررسی کن.",
                    parse_mode='HTML')
        return

    # از اینجا به بعد فقط خطاهای واقعی
    logger.error(f"Exception: {err_line}", exc_info=context.error)
    if ADMIN_ID:
        try:
            uid_info = ""
            ctx_info = ""
            if isinstance(update, Update):
                u = update.effective_user
                if u:
                    # 🛡 AUDIT-T1b — full_name ورودیِ خودِ کاربر است: بدون escape
                    # می‌توانست با <a href> در DM خطای ادمین لینک کاذب بسازد.
                    uid_info = f"\n👤 کاربر: {html.escape(u.full_name or '')} | آیدی: {u.id}"
                if update.callback_query and update.callback_query.data:
                    # 🛡 AUDIT-§۳۲ — بدون این خط، «کدام دکمه» قابل بازسازی نبود
                    ctx_info = f"\n🔘 data: <code>{html.escape(str(update.callback_query.data)[:80])}</code>"
                elif update.message and update.message.text:
                    ctx_info = f"\n💬 متن: <code>{html.escape(update.message.text[:80])}</code>"
            # 🛡 AUDIT-§۲۴ — خودِ متن خطا هم کاربر-کنترل می‌تواند باشد (پیام
            # تلگرام شامل متن ورودی)؛ escape نشسته بود و با «<» پیامِ هشدار
            # می‌ترکید و در `except: pass` گم می‌شد ⇒ ادمین هرگز از خطا خبردار
            # نمی‌شد. safe_send هم فالبکِ بدون HTML دارد.
            # 🛡 AUDIT-§۷۸ — err_line (نه err_str خام): نامِ کلاس همیشه هست،
            # پس «<code></code>» تهی دیگر تولید نمی‌شود.
            err_text = (
                f"⚠️ <b>خطای ربات</b>{uid_info}{ctx_info}\n"
                f"<code>{html.escape(err_line[:300])}</code>"
            )
            await safe_send(context.bot, ADMIN_ID, err_text, parse_mode='HTML')
        except Exception as _eh:
            logger.warning(f"error_handler: ارسال هشدار به ادمین شکست خورد: {_eh}")


# ══════════════════════════════════════════════════
#  هندلرهای یکپارچه — FIX کامل
# ══════════════════════════════════════════════════

async def unified_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    # 🌊 W5 — Flood-Control برای فایل هم (جلوگیری از اسپم و هزینه)
    if uid != ADMIN_ID:
        is_blocked, wait = _check_flood(uid)
        if is_blocked:
            try:
                await update.message.reply_text(f"⏳ لطفاً کمی صبر کنید ({wait}s)")
            except: pass
            return


    # ۰. FIX جدید: اسکرین‌شات رسید پرداخت اشتراک
    if context.user_data.get('sub_mode') == 'awaiting_screenshot' and update.message.photo:
        return await sub_screenshot_handler(update, context)

    # 🌊 W6.2 — اسکرین‌شات رسید شارژ کیف پول
    if context.user_data.get('sub_mode') == 'awaiting_topup_screenshot' and update.message.photo:
        from subscription import topup_screenshot_handler
        return await topup_screenshot_handler(update, context)

    # 🤖 هوشیار — عکس/PDF/صدا در حالت «پرسش از AI»
    # ⚠️ قابلیتِ جدید: قبلاً فقط عکس پشتیبانی می‌شد؛ حالا PDF (جزوه/برگه‌ی
    # اسکن‌شده) و پیامِ صوتی/فایلِ صوتی (سوالِ گفتاری) هم قبول می‌شه —
    # جزئیاتِ تشخیصِ نوع و اعتبارسنجی داخلِ خودِ handle_ai_media است.
    if context.user_data.get('mode') == 'ai_query' and (
        update.message.photo or update.message.voice or update.message.audio or
        (update.message.document and (
            (update.message.document.mime_type or '').startswith('image/') or
            update.message.document.mime_type == 'application/pdf'
        ))
    ):
        return await handle_ai_media(update, context)

    # ۱. بکاپ restore
    if uid == ADMIN_ID and context.user_data.get('backup_mode') == 'waiting_restore':
        return await backup_file_handler(update, context)

    # ۲. FIX: broadcast — عکس/ویدیو/فایل در حالت broadcast
    if uid == ADMIN_ID and context.user_data.get('mode') == 'broadcast':
        return await admin_broadcast_handler(update, context)

    # 📅 اسکن برنامه هفتگی/امتحانات با هوشیار (عکس جدول)
    scan_mode = context.user_data.get('mode', '')
    if scan_mode in ('schedule_scan_weekly', 'schedule_scan_exam'):
        # فقط ادمین برنامه
        if await db.has_permission(uid, "schedules.manage") or (await db.get_content_scope(uid) or {}).get("kind") == "global":
            if update.message.photo or (update.message.document and (update.message.document.mime_type or '').startswith('image/')):
                from schedule import handle_schedule_scan_photo
                return await handle_schedule_scan_photo(update, context)

    # ۳. محتوا ادمین
    ca_mode = context.user_data.get('ca_mode', '')
    if ca_mode in ('waiting_file', 'waiting_ref_file') and await db.is_content_admin(uid):
        return await ca_file_handler(update, context)


async def maintenance_gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    FIX جدید: حالت تعمیر و نگهداری — اجرا می‌شود با group=-1 یعنی
    قبل از همه‌ی handlerهای دیگر (پیام و callback). اگر maintenance
    فعال باشد و کاربر ادمین ارشد نباشد، پیام تعمیر نشان داده می‌شود
    و با ApplicationHandlerStop از اجرای ادامه‌ی handlerها جلوگیری
    می‌شود — بدون نیاز به لمس کردن ده‌ها تابع callback موجود.
    """
    # FIX باگ مهم: این گیت فقط باید روی پیوی خصوصی اثر کند —
    # وگرنه پیام «ربات در حال بروزرسانی است» در گروه‌های لاگ
    # (ادمین/محتوا) هم به اعضای آن گروه نمایش داده می‌شد.
    if update.effective_chat is None or update.effective_chat.type != 'private':
        return

    uid = update.effective_user.id if update.effective_user else None
    if uid is None or uid == ADMIN_ID:
        return  # ادمین ارشد همیشه دسترسی کامل دارد

    if not await is_maintenance_on():
        return

    msg = await maintenance_message()
    try:
        if update.callback_query:
            await update.callback_query.answer("🔧 ربات در حال بروزرسانی است", show_alert=True)
        elif update.message:
            await update.message.reply_text(msg, parse_mode='HTML')
    except Exception:
        pass
    raise ApplicationHandlerStop


async def channel_lock_gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    FIX جدید: قفل اجباری عضویت کانال. اگر ادمین یک یا چند کانال را
    در تنظیمات اضافه کرده باشد، هر کاربر عادی (غیر از ادمین ارشد و
    نقش‌های فرعی ادمین) باید عضو همه آن‌ها باشد تا بتواند از ربات
    استفاده کند. با group=-1 یعنی قبل از maintenance_gate نیست —
    اجرا می‌شود بعد از آن، چون اگر maintenance فعال باشد آن پیام
    اولویت دارد (maintenance_gate با ApplicationHandlerStop متوقف
    می‌کند و این تابع اصلاً اجرا نمی‌شود).
    """
    # FIX باگ مهم: همین مشکل maintenance_gate — فقط پیوی خصوصی
    if update.effective_chat is None or update.effective_chat.type != 'private':
        return

    uid = update.effective_user.id if update.effective_user else None
    if uid is None or uid == ADMIN_ID:
        return

    # دکمه «بررسی مجدد عضویت» با callback خاص — نباید مسدود شود
    if update.callback_query and update.callback_query.data == 'channel_lock:check':
        return

    channels = await db.get_required_channels()
    if not channels:
        return

    # نقش‌های فرعی ادمین هم معاف هستند
    role_doc = await db.get_admin_role(uid)
    if role_doc:
        return

    not_joined = []
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(ch['id'], uid)
            if member.status in ('left', 'kicked'):
                not_joined.append(ch)
        except Exception:
            # اگر ربات نتواند وضعیت را چک کند (مثلاً ادمین کانال نیست)
            # برای امنیت، آن کانال را به‌عنوان عضو‌نشده در نظر می‌گیریم
            not_joined.append(ch)

    if not not_joined:
        return

    keyboard = []
    for ch in not_joined:
        if ch.get('invite_link'):
            keyboard.append([InlineKeyboardButton(f"📢 عضویت در {ch['title']}", url=ch['invite_link'])])
    keyboard.append([InlineKeyboardButton("✅ عضو شدم، بررسی کن", callback_data='channel_lock:check')])

    text = (
        "🔒 <b>عضویت در کانال الزامی است</b>\n\n"
        "برای استفاده از ربات، ابتدا باید در کانال(های) زیر عضو شوید:\n\n"
        + '\n'.join(f"• {ch['title']}" for ch in not_joined)
    )
    try:
        if update.callback_query:
            await update.callback_query.answer("🔒 ابتدا باید عضو کانال شوید", show_alert=True)
        elif update.message:
            await update.message.reply_text(text, parse_mode='HTML',
                                             reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        pass
    raise ApplicationHandlerStop


async def broadcast_gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    FIX باگ اصلی گزارش‌شده: «گاهی پیام همگانی خونده میشه، گاهی نه».
    علت: ConversationHandler اصلی (conv) و MessageHandler عمومی متن
    (unified_text_handler) هر دو در همون گروه پیش‌فرض (group=0) ثبت
    می‌شن و conv زودتر ثبت می‌شه. در PTB، توی هر گروه فقط اولین
    هندلری که check_update‌ش True بشه اجرا میشه. پس اگه ادمین قبلاً
    (حتی خیلی وقت پیش) وارد یکی از state های conv شده باشه (مثلاً
    پنل محتوا، ساخت سوال، ویرایش پروفایل، تیکت) و بدون /cancel یا
    رسیدن به END از اون خارج نشده باشه، اون state گیر می‌مونه و از
    اون به بعد پیام‌های متنی خصوصی — از جمله متن broadcast — اول به
    هندلر state قدیمی می‌افتن، نه به admin_broadcast_handler.

    راه‌حل: این گیت با group جداگانه‌ی خودش (قبل از conv) ثبت می‌شه، پس
    همیشه — فارغ از هر state گیرافتاده‌ای — اول چک می‌کنه mode ==
    'broadcast' هست یا نه و در صورت وجود مستقیم admin_broadcast_handler
    رو صدا می‌زنه و با ApplicationHandlerStop جلوی ادامه رو می‌گیره.

    ⛔️ نکته‌ی مهم‌تر (ریشه‌ی واقعی باگ که این گیت به‌تنهایی حلش
    نمی‌کرد): این تابع و maintenance_gate/channel_lock_gate/
    update_last_active قبلاً همگی با group=-1 مشترک ثبت شده بودند.
    در PTB، توی هر group فقط اولین Handler ای که check_update اش True
    بشه اجرا می‌شه و بقیه‌ی همون group اصلاً چک نمی‌شن. چون
    TypeHandler(Update, ...) روی هر آپدیتی True برمی‌گردونه، فقط
    maintenance_gate (که زودتر ثبت شده بود) واقعاً اجرا می‌شد و این
    تابع هیچ‌وقت حتی صدا زده نمی‌شد! الان در bot.py هرکدام از این ۴
    گیت group منفیِ مجزای خودشان را دارند (-4 تا -1) تا واقعاً همه
    برای هر آپدیت اجرا شوند.
    """
    if update.effective_chat is None or update.effective_chat.type != 'private':
        return
    msg = update.message
    if msg is None:
        return
    uid = update.effective_user.id if update.effective_user else None
    if uid is None:
        return
    if context.user_data.get('mode') != 'broadcast':
        return

    if uid != ADMIN_ID:
        role_doc = await db.get_admin_role(uid)
        perms = db.ROLE_PERMISSIONS.get(role_doc.get('role', ''), set()) if role_doc else set()
        if 'broadcast' not in perms:
            return

    if not (msg.text or msg.photo or msg.video or msg.document or msg.voice or msg.audio):
        return

    await admin_broadcast_handler(update, context)
    raise ApplicationHandlerStop


async def channel_lock_check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دکمه «عضو شدم، بررسی کن» — چک مجدد و عبور در صورت موفقیت"""
    query = update.callback_query
    uid   = update.effective_user.id
    channels = await db.get_required_channels()
    still_not_joined = []
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(ch['id'], uid)
            if member.status in ('left', 'kicked'):
                still_not_joined.append(ch)
        except Exception:
            still_not_joined.append(ch)

    if still_not_joined:
        await query.answer("❌ هنوز عضو همه کانال‌ها نشده‌اید!", show_alert=True)
        return

    await query.answer("✅ عضویت تأیید شد!", show_alert=True)
    await query.edit_message_text("✅ عضویت شما تأیید شد. لطفاً /start را بزنید.")


async def update_last_active(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    برای گزارش هفتگی نیاز داریم بدانیم آخرین فعالیت هر کاربر کِی
    بوده. فقط در پیوی خصوصی معنی دارد — فعالیت یک کاربر در گروه
    لاگ ربات (که اصلاً عضو معمولی ربات نیست) را نباید به‌عنوان
    «فعالیت در ربات» ثبت کرد.
    """
    if update.effective_chat is None or update.effective_chat.type != 'private':
        return
    uid = update.effective_user.id if update.effective_user else None
    if uid is None:
        return
    try:
        from database import db
        await db.users.update_one(
            {'user_id': uid},
            {'$set': {'last_active': utc_now_iso()}}
        )
    except Exception:
        pass


# FIX باگ: این modeها وقتی کاربر دکمه‌ی اصلی منو را می‌زند (یعنی
# قصد خروج از فلوی نیمه‌کاره را دارد) باید پاک شوند — وگرنه پیام
# بعدی او در هر بخش دیگری از ربات به اشتباه به همین mode می‌رسد.
INTERRUPTIBLE_SIMPLE_MODES = {
    'search_user', 'edit_user', 'add_intake', 'add_admin_role',
    'add_schedule', 'flex_time_change', 'schedule_scan_weekly', 'schedule_scan_exam',
    'set_auto_backup_hour', 'report_note', 'ticket_search',
    'set_maintenance_text', 'set_log_group_admin', 'set_log_group_content',
    'add_required_channel', 'edit_schedule_field', 'set_donation_link',
    # FIX جدید: هوشیار — اگر کاربر وسط حالت «پرسش از AI» باشد و دکمه‌ی
    # دیگری از منو بزند، باید از حالت خارج شود نه اینکه پیامش به‌عنوان
    # سوال جدید برای هوش مصنوعی ارسال شود.
    'ai_query',
    # FIX جدید: همین موضوع برای modeهای پنل مدیریت هوشیار (ادمین) هم
    # صادق است — قبلاً این‌ها اینجا نبودند، برای همین اگر ادمین وسط
    # «ویرایش دستور سیستمی» (یا کلید/محدودیت/ریست سهمیه) دکمه‌ی دیگری
    # از منو می‌زد، متنِ آن دکمه به‌جای ناوبری، به‌عنوان ورودیِ همان
    # حالتِ نیمه‌کاره ذخیره می‌شد (مثلاً «📚 منابع» به‌عنوان دستور
    # سیستمیِ جدید ست می‌شد).
    'ai_set_key', 'ai_set_model', 'ai_set_limit', 'ai_set_prompt',
    'ai_reset_quota_search', 'ai_save_persona_name', 'ai_set_disabled_msg',
    'ai_ban_search', 'ai_profile_search',
    # FIX جدید: طراحی سوال با هوشیار (AI) — همین موضوع برای مرحله‌ی
    # «نکته‌ی اختیاری» هم صادقه.
    'ai_question_note',
    # FIX جدید: دستیارِ نوشتنِ اطلاعیه با هوشیار
    'bc_ai_notes',
}
def _menu_button_texts() -> set:
    """برچسب‌های دکمه‌های کیبورد اصلی (ReplyKeyboard).

    🔧 باگ واقعیِ پروداکشن: لیست دستیِ زیر «💎 اشتراک ویژه» و «💙 حمایت مالی»
    رو نداشت — یعنی اگه کاربر وسط یه mode گیرکرده (مثلاً waiting_file) روی
    یکی از این دو می‌زد، mode پاک نمی‌شد و کاربر گیر می‌موند. پس حالا لیست از
    *خودِ کیبورد* ساخته می‌شه و مقدار دستی فقط fallback است (keyboards رینگ
    هم از همین مجموعه برای گارد «تپ منو وسط چت رله نشه» استفاده می‌کنه).
    """
    base = {
        '🩺 داشبورد', '📚 منابع', '🧪 بانک سوال', '❓ سوالات متداول',
        '📅 برنامه', '👤 پروفایل', '🔔 اعلان‌ها', '🎫 پشتیبانی',
        '🎓 پنل محتوا', '👨\u200d⚕️ پنل ادمین', '🤖 هوشیار',
    }
    try:
        from utils import main_keyboard as _main_kb
        for row in (getattr(_main_kb(), 'keyboard', None) or []):
            for bt in row:
                t = getattr(bt, 'text', None)
                if t:
                    base.add(str(t))
    except Exception as _e:      # کیبورد در دسترس نبود ⇒ همان fallback
        import logging
        logging.getLogger(__name__).debug("MENU_BUTTON_TEXTS fallback: %s", _e)
    return base


MENU_BUTTON_TEXTS = _menu_button_texts()


async def unified_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    # 🌊 W5 — Flood-Control: 5 msg/5s → 30s block (admin exempt)
    if uid != ADMIN_ID:
        is_blocked, wait = _check_flood(uid)
        if is_blocked:
            # warn at most once per block
            last = _FLOOD_WARNED.get(uid, 0)
            now = time.time()
            if now - last > 8:
                _FLOOD_WARNED[uid] = now
                try:
                    await update.message.reply_text(f"⏳ لطفاً کمی صبر کنید ({wait}s) — پیام‌های شما خیلی سریع است.")
                except: pass
            return


    # FIX باگ لغو رول/گزارش/و غیره گیر کردن: اگر کاربر دکمه منو زده
    # و در یکی از modeهای ساده گیر بود، آن mode را پاک کن و رد شو
    # تا روتر اصلی پیام را عادی پردازش کند.
    msg_text = update.message.text.strip() if update.message and update.message.text else ''
    if msg_text in MENU_BUTTON_TEXTS and context.user_data.get('mode') in INTERRUPTIBLE_SIMPLE_MODES:
        for k in ('mode', 'new_role_type', 'new_role_intake', 'flex_change_sid',
                  'report_target_type', 'report_target_id', 'report_reason',
                  'edit_schedule_sid', 'edit_schedule_field', 'schedule_edit_sid',
                  'schedule_type', 'pending_schedule'):
            context.user_data.pop(k, None)
        # ادامه نده — اجازه بده همین تابع پایین‌تر پیام دکمه را عادی مسیر کند

    # FIX باگ مهم: 'NoneType' object has no attribute 'text' —
    # وقتی mode فعال است (منتظر یک ورودی متنی) ولی کاربر media
    # (عکس/فایل/استیکر/ویس) بدون متن می‌فرستد، update.message.text
    # می‌شود None و توابع پایین‌دستی با .strip() کرش می‌کنند.
    # broadcast و چند mode خاص که خودشان از فایل/عکس پشتیبانی
    # می‌کنند (مثل آپلود فایل بانک سوال) از این گارد معاف هستند.
    active_mode    = context.user_data.get('mode', '')
    active_ca_mode = context.user_data.get('ca_mode', '')
    active_ticket_mode = context.user_data.get('ticket_mode', '')
    MEDIA_ALLOWED_MODES = {
        'broadcast', 'waiting_description',
        'waiting_ref_description', 'creating_question',
        'waiting_file', 'waiting_ref_file',  # ca_mode هایی که فایل می‌گیرند
    }
    any_active_mode = active_mode or active_ca_mode or active_ticket_mode
    is_media_allowed = (
        active_mode in MEDIA_ALLOWED_MODES or active_ca_mode in MEDIA_ALLOWED_MODES
    )
    if (any_active_mode and not is_media_allowed
            and update.message is not None and not update.message.text):
        await update.message.reply_text(
            "⚠️ لطفاً پاسخ خود را به‌صورت متن ارسال کنید."
        )
        return

    # ۱. FIX: broadcast — باید اول از همه چک بشه
    if uid == ADMIN_ID and context.user_data.get('mode') == 'broadcast':
        return await admin_broadcast_handler(update, context)

    # ⚠️ قابلیتِ جدید: نکته‌های اطلاعیه برای هوشیار (دستیارِ نوشتنِ اطلاعیه)
    if uid == ADMIN_ID and context.user_data.get('mode') == 'bc_ai_notes':
        from admin import _broadcast_ai_generate
        context.user_data['mode'] = ''
        context.user_data['bc_ai_notes'] = update.message.text or ''
        return await _broadcast_ai_generate(update.message, context, is_message=True)

    # ۲. FIX: profile_edit — ویرایش نام/شماره دانشجویی (هر کاربری)
    if context.user_data.get('mode') == 'profile_edit':
        from profile import profile_text_handler
        return await profile_text_handler(update, context)

    # ۳. FIX: search_user ادمین
    if uid == ADMIN_ID and context.user_data.get('mode') == 'search_user':
        return await handle_admin_text(update, context)

    # ۳b. ✉️ موج ۴.۸۰: پیام مستقیم ادمین به کاربر (از کارت مدیریت)
    if uid == ADMIN_ID and context.user_data.get('mode') == 'admin_dm':
        return await handle_admin_text(update, context)

    # ۳. FIX: edit_user ادمین
    if uid == ADMIN_ID and context.user_data.get('mode') == 'edit_user':
        return await handle_admin_text(update, context)

    # ۴. FIX: add_intake ادمین
    if uid == ADMIN_ID and context.user_data.get('mode') == 'add_intake':
        return await handle_admin_text(update, context)

    # ۴b. FIX جدید: add_admin_role — افزودن نقش فرعی (فقط مدیر ارشد)
    if uid == ADMIN_ID and context.user_data.get('mode') == 'add_admin_role':
        return await handle_admin_text(update, context)

    # ۴c. FIX جدید: تنظیمات ربات — متن تعمیر و گروه‌های لاگ (فقط مدیر ارشد)
    if uid == ADMIN_ID and context.user_data.get('mode') in (
        'set_maintenance_text', 'set_log_group_admin', 'set_log_group_content',
        'set_poll_channel',
        'poll_question', 'poll_option',
        'set_donation_link',
    ):
        return await handle_admin_text(update, context)

    # ۴d. 🤖 هوشیار — تنظیمات پنل ادمین (API Key/مدل/محدودیت/prompt/ریست سهمیه/پرسونا/بن/پیام‌خاموش)
    if uid == ADMIN_ID and context.user_data.get('mode') in (
        'ai_set_key', 'ai_set_model', 'ai_set_limit', 'ai_set_prompt',
        'ai_reset_quota_search', 'ai_save_persona_name', 'ai_set_disabled_msg',
        'ai_ban_search', 'ai_profile_search',
    ):
        return await ai_admin_text_handler(update, context)

    # ۴e. 🤖 هوشیار — حالت «پرسش از AI» برای هر کاربر تأییدشده
    if context.user_data.get('mode') == 'ai_image_prompt':
        return await handle_ai_image_prompt(update, context)
    if context.user_data.get('mode') == 'ai_query':
        return await handle_ai_text(update, context)

    # ۵. افزودن برنامه کلاسی/امتحان
    if context.user_data.get('mode') == 'add_schedule':
        from schedule import handle_add_schedule_text
        return await handle_add_schedule_text(update, context)

    # ۵c. FIX جدید: flex_time_change — اعلام تغییر زمان کلاس منعطف
    if uid == ADMIN_ID and context.user_data.get('mode') == 'flex_time_change':
        from schedule import handle_flex_time_change_text
        return await handle_flex_time_change_text(update, context)

    # ۵c2. FIX جدید (بخش اول): edit_schedule_field — ویرایش تک‌فیلدی برنامه
    if uid == ADMIN_ID and context.user_data.get('mode') == 'edit_schedule_field':
        from schedule import handle_edit_schedule_field_text
        return await handle_edit_schedule_field_text(update, context)

    # ۵d. FIX جدید: ساعت دلخواه بکاپ خودکار
    if uid == ADMIN_ID and context.user_data.get('mode') == 'set_auto_backup_hour':
        from backup import handle_auto_backup_hour_text
        return await handle_auto_backup_hour_text(update, context)

    # ۵e. FIX جدید: توضیح گزارش ایراد (دلیل 'سایر')
    if context.user_data.get('mode') == 'report_note':
        return await handle_report_note_text(update, context)

    # ۵f. FIX جدید: افزودن کانال اجباری
    if uid == ADMIN_ID and context.user_data.get('mode') == 'add_required_channel':
        return await handle_admin_text(update, context)

    # ۶. ca_text_handler
    ca_mode = context.user_data.get('ca_mode', '')
    ca_text_modes = {
        'add_lesson', 'add_session', 'waiting_filename', 'confirming_filename',
        'waiting_description', 'waiting_ref_description',
        'add_faq', 'add_ref_subject',
        'ui_url', 'ui_lesson', 'ui_topic',  # 📥 URL-Import
        'add_ref_book', 'edit_lesson', 'edit_session',
        'edit_ref_subject', 'edit_ref_book',
    }
    if ca_mode in ca_text_modes and await db.is_content_admin(uid):
        return await ca_text_handler(update, context)

    # ۷. ticket mode — شامل user_reply و admin_search هم هست
    if context.user_data.get('ticket_mode') in (
        'waiting_message', 'admin_reply', 'user_reply',
        'admin_search', 'awaiting_confirm'
    ):
        return await ticket_message_handler(update, context)

    # ۷b. ticket_search mode برای ادمین
    if uid == ADMIN_ID and context.user_data.get('mode') == 'ticket_search':
        return await ticket_message_handler(update, context)

    # ۸. روتر اصلی
    return await route_message(update, context)


# ══════════════════════════════════════════════════
#  منوی منابع
# ══════════════════════════════════════════════════

async def route_resources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🔬 علوم پایه", callback_data='bs:main')],
        [InlineKeyboardButton("📖 رفرنس‌ها",  callback_data='ref:main')],
        [InlineKeyboardButton("🔙 بازگشت",    callback_data='dashboard:refresh')],
    ]
    await query.edit_message_text(
        "📚 <b>منابع درسی</b>\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🔬 <b>علوم پایه:</b> محتوای جلسات (ویدیو، جزوه، پاورپوینت و...)\n"
        "📖 <b>رفرنس‌ها:</b> کتاب‌های مرجع (PDF فارسی/لاتین)",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ══════════════════════════════════════════════════
#  ساخت Application
# ══════════════════════════════════════════════════

def build_application() -> Application:
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .concurrent_updates(True)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(15)
        .pool_timeout(15)
        .build()
    )

    # ── ConversationHandler مرکزی ──
    # NOTE: BROADCAST از اینجا حذف شد — در unified_text_handler مدیریت میشه
    conv = ConversationHandler(
        entry_points=[
            # FIX باگ مهم: /start و همه‌ی mode‌های گفتگو فقط در پیوی
            # خصوصی فعال باشند — وگرنه ربات روی پیام‌های گروه‌های لاگ
            # (ادمین/محتوا) هم واکنش می‌داد و می‌گفت «/start بزنید».
            #
            # 🧠 FIX معماری: ورودی‌های questions:cr_topic: و ^ca: قبلاً
            # هم اینجا entry_point بودند هم پایین‌تر standalone
            # CallbackQueryHandler داشتند — یعنی یک تپ روی «ca:...»
            # می‌توانست یک conversation جدید و بی‌مصرف باز کند (چون
            # دیگر هیچ‌کدام از state هایش را نگه نمی‌داریم) درحالی‌که
            # نسخه‌ی standalone پایین همین فایل به‌تنهایی کاملاً کافی
            # است. حذف شدند تا ConversationHandler فقط برای «ثبت‌نام»
            # — تنها فلوی واقعاً چندمرحله‌ای بدون معادل mode-based —
            # یک conversation باز کند.
            CommandHandler('start', start_handler, filters=filters.ChatType.PRIVATE),
        ],
        states={
            REGISTER: [
                CallbackQueryHandler(register_start_callback, pattern=r'^register:')
            ],
            STEP_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, step_name_handler),
                CallbackQueryHandler(register_start_callback, pattern=r'^register:cancel'),
            ],
            STEP_GROUP: [
                CallbackQueryHandler(
                    register_start_callback,
                    pattern=r'^register:(group1|group2|cancel)'
                )
            ],
            STEP_INTAKE: [
                CallbackQueryHandler(register_intake_callback, pattern=r'^register:intake:')
            ],
            STEP_STUDENT_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, step_student_id_handler),
            ],
            # 🧠 FIX معماری «دو مغز» (پرریسک‌ترین ایراد معماری پروژه):
            # state های ANSWERING، CREATING_Q، CA_WAITING_FILE/TEXT،
            # PROFILE_EDIT_WAITING، TICKET_WAITING/REPLY_WAITING از
            # اینجا حذف شدند. بررسی کد نشان داد هر کدام از قبل و به‌طور
            # کامل معادل mode-based خودشان را داشتند (ANSWERING حتی
            # هیچ‌وقت واقعاً وارد نمی‌شد — یک state کاملاً مرده بود):
            #   • answer:            → questions_callback (استاندالون پایین همین فایل)
            #   • creating_question  → unified_text_handler → route_message
            #   • qd:                → استاندالون شد (لیست cbs پایین‌تر)
            #   • ca_mode (فایل/متن) → unified_file_handler / unified_text_handler
            #   • profile_edit       → unified_text_handler
            #   • ticket_mode        → unified_text_handler
            # نگه‌داشتن این state ها همزمان با معادل mode-based شان
            # دقیقاً همان چیزی بود که باعث شد یک بار پیام broadcast
            # ادمین وسط یک state قدیمی گم شود: وقتی کاربر از یک فلوی
            # چندمرحله‌ای خارج می‌شد بدون رسیدن به پایانش، conv در همان
            # state قدیمی «گیر» می‌ماند و پیام بعدی‌اش را — حتی اگر
            # مربوط به بخش کاملاً متفاوتی بود — با handler همان state
            # قدیمی قورت می‌داد. حالا چون این مسیرها هیچ state ای در
            # ConversationHandler ندارند، هر پیام همیشه مستقیم به
            # unified_text_handler/unified_file_handler می‌رسد و مقدار
            # واقعیِ همین‌الانِ mode/ca_mode/ticket_mode را می‌بیند —
            # نه یک state منجمد از چند دقیقه قبل.
        },
        fallbacks=[
            CommandHandler('start', start_handler, filters=filters.ChatType.PRIVATE),
            CommandHandler('cancel', cancel_handler, filters=filters.ChatType.PRIVATE),
        ],
        allow_reentry=True,
        per_message=False,
        conversation_timeout=1800,
    )
    # ══════════════════════════════════════════════════
    # ⛔️ باگ اصلیِ واقعی «پیام همگانی گاهی دریافت نمی‌شود» اینجا بود:
    # کتابخانه python-telegram-bot توی هر group فقط اولین Handler ای
    # که check_update اش True برگردونه رو اجرا می‌کنه و فوراً break
    # می‌کنه — بدون اینکه بقیه‌ی Handlerهای همون group اصلاً چک بشن
    # (منبع خود کتابخونه: «Only a max of 1 handler per group is
    # handled»). چون maintenance_gate و channel_lock_gate و
    # broadcast_gate و update_last_active هر چهارتا TypeHandler(Update, ...)
    # بودن و همگی توی یک group مشترک (-1) ثبت شده بودن، و
    # TypeHandler(Update, ...) روی *هر* آپدیتی True برمی‌گردونه، همیشه
    # فقط maintenance_gate واقعاً اجرا می‌شد و broadcast_gate هیچ‌وقت
    # حتی یک‌بار هم فراخوانی نمی‌شد — صرف‌نظر از اینکه ادمین چی
    # می‌فرستاد. الان هر گیت یک group منفیِ جداگانه‌ی خودش را دارد تا
    # هر ۴ تا، برای هر آپدیت، به‌ترتیب اجرا شوند.
    # ══════════════════════════════════════════════════
    app.add_handler(TypeHandler(Update, maintenance_gate),   group=-4)
    app.add_handler(TypeHandler(Update, channel_lock_gate),  group=-3)
    # FIX باگ اصلی: پیام همگانی باید زودتر از ConversationHandler اصلی
    # (conv) چک بشه، وگرنه اگه ادمین در یکی از state های قدیمی conv
    # گیر کرده باشه، متن broadcast اصلاً بهش نمی‌رسه.
    app.add_handler(TypeHandler(Update, broadcast_gate), group=-2)
    app.add_handler(TypeHandler(Update, update_last_active), group=-1)

    app.add_handler(conv)

    # ── Callback handlers — ترتیب مهم: specific قبل از general ──
    cbs = [
        # پروفایل
        (profile_callback,         r'^profile:'),
        # علوم پایه
        (basic_science_callback,   r'^bs[_:]'),
        (basic_science_callback,   r'^bs_dl:'),
        (basic_science_callback,   r'^resources:bs'),
        # رفرنس‌ها
        (references_callback,      r'^ref[_:]'),
        (references_callback,      r'^resources:ref'),
        # منابع
        (route_resources,          r'^resources:menu'),
        (resources_callback,       r'^download_resource:'),
        (route_resources,          r'^resources:'),
        # داشبورد
        (dashboard_callback,       r'^dashboard'),
        # سوالات
        (questions_callback,       r'^(questions|answer:)'),
        # بقیه
        (schedule_callback,        r'^schedule'),
        (stats_callback,           r'^stats'),
        (notifications_callback,   r'^notif'),
        (admin_callback,           r'^admin'),
        (backup_confirm_restore,   r'^backup:confirm_restore$'),
        (backup_callback,          r'^backup:'),
        (faq_callback,             r'^faq:'),
        (content_admin_callback,   r'^ca:'),
        (ticket_callback,          r'^ticket:'),
        (report_callback,          r'^report:'),   # FIX جدید
        (channel_lock_check_callback, r'^channel_lock:check'),   # FIX جدید
        # 🧠 FIX معماری: قبلاً qd: (انتخاب سختی سوال) فقط داخل state
        # CREATING_Q قابل‌دسترس بود؛ چون آن state حذف شد، اینجا
        # standalone ثبت می‌شود تا فلوی ساخت سوال دست‌نخورده بماند.
        (handle_difficulty_choice, r'^qd:'),
        # FIX جدید: سیستم اشتراک
        (subscription_callback,       r'^sub:'),
        (subscription_admin_callback, r'^suba:'),
        (grades_callback,             r'^grades:'),
        (ai_admin_callback,           r'^ai:'),   # 🤖 هوشیار — پنل ادمین
        (ai_user_callback,            r'^aiu:'),  # 🤖 هوشیار — دکمه‌های زیر جواب (گفتگوی جدید/گزارش)
        (referral_callback,           r'^ref:'),   # 🌱 W13 — دعوت دوستان
        (dunning_click,               r'^dun:'),   # 💳 W14 — ادامه‌ی پرداخت نیمه‌تمام
    ]
    for handler, pattern in cbs:
        app.add_handler(CallbackQueryHandler(handler, pattern=pattern))

    # 🧠 FIX معماری: /cancel قبلاً فقط داخل state های حذف‌شده
    # (CA_WAITING_FILE/TEXT، PROFILE_EDIT_WAITING، TICKET_WAITING/
    # REPLY_WAITING) و در fallbacks خودِ conv در دسترس بود. حالا که آن
    # فلوها دیگر conversation جدا ندارند، /cancel باید مستقل ثبت شود
    # تا همچنان بتواند ca_mode/ticket_mode/profile_edit/creating_question
    # را با همان تابع قبلی (cancel_handler) پاک کند.
    app.add_handler(CommandHandler('cancel', cancel_handler, filters=filters.ChatType.PRIVATE))

    # 💍 Ring Street — ثبت *قبل* از هندلرهای یکپارچه، چون در PTB
    # «ترتیب ثبت = اولویت» است. فیلتر این هندلرها «کاربر در flow/چت
    # رینگ است» ⇒ وقتی رینگ خاموش است یا کاربر در رینگ نیست، update
    # دست‌نخورده به مسیرهای قبلی می‌رود (isolation §۵).
    if ring_handlers is not None:
        ring_handlers.register(app)
        app.add_handler(CallbackQueryHandler(ring_handlers.ring_callback,
                                             pattern=r'^ring:'))

    # ── File handler — همه انواع فایل ──
    # FIX باگ مهم: فقط در پیوی خصوصی فعال باشد — وگرنه فایل‌هایی
    # که در گروه‌های لاگ (ادمین/محتوا) فرستاده شوند هم پردازش می‌شدند.
    app.add_handler(MessageHandler(
        (filters.Document.ALL | filters.VIDEO | filters.AUDIO |
         filters.VOICE | filters.PHOTO) & filters.ChatType.PRIVATE,
        unified_file_handler
    ))

    # ── Text handler ──
    # FIX باگ اصلی گزارش‌شده: این handler عمومی هیچ فیلتر چت نداشت،
    # پس روی هر پیام متنی در گروه‌های لاگ هم اجرا می‌شد و از طریق
    # route_message پاسخ «/start بزنید» می‌فرستاد. حالا فقط پیوی.
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        unified_text_handler
    ))

    # ── Error handler ──
    app.add_error_handler(error_handler)

    return app


# ══════════════════════════════════════════════════
#  post_init: ایندکس‌ها + job‌ها
# ══════════════════════════════════════════════════

# ══════════════════════════════════════════════════
#  💓 موج Railway — تپش قلب (diagnostics بین processها)
#  فایل تنها محل اشتراک API و bot در یک container است؛ مسیر با
#  BOT_HEARTBEAT_FILE قابل تغییر است (پیش‌فرض /tmp).
# ══════════════════════════════════════════════════
from bot_heartbeat import HEARTBEAT_INTERVAL


async def bot_heartbeat_job(context: ContextTypes.DEFAULT_TYPE):
    from bot_heartbeat import write_heartbeat
    write_heartbeat({'phase': 'running'})


async def post_init(application: Application):
    # 🌊 W5 — ثبت دستورات تلگرام (منوی / ) و توضیح کوتاه
    try:
        from telegram import BotCommand
        cmds = [
            BotCommand("start", "شروع / ثبت‌نام"),
            BotCommand("help", "راهنما"),
            BotCommand("cancel", "لغو عملیات"),
            BotCommand("profile", "پروفایل"),
            BotCommand("schedule", "برنامه کلاسی"),
        ]
        await application.bot.set_my_commands(cmds)
        try:
            await application.bot.set_my_short_description("هامشیار — دستیار آموزشی پزشکی")
            await application.bot.set_my_description("هامشیار: منابع، بانک سوال، برنامه کلاسی و پشتیبانی — همه در یک ربات.")
            await application.bot.set_chat_menu_button(menu_button=None)
        except Exception:
            pass
        logger.info("✅ دستورات تلگرام ثبت شد")
    except Exception as e:
        logger.warning(f"setMyCommands failed: {e}")
    # 🌊 W5 — Webhook اگر تنظیم شده باشد (Railway: WEBHOOK_URL + WEBHOOK_SECRET)
    try:
        wh_url = (os.getenv("WEBHOOK_URL") or os.getenv("BOT_WEBHOOK_URL") or "").strip()
        wh_secret = (os.getenv("WEBHOOK_SECRET") or os.getenv("BOT_WEBHOOK_SECRET") or "").strip() or None
        if wh_url:
            # اگر webhook ست شده، polling conflict می‌دهد — فقط set کن، run_polling در این حالت توسط run_webhook جایگزین می‌شود (پایین)
            # اینجا فقط اطمینان از ثبت است؛ اگر در حالت polling باشیم، حذف webhook
            if os.getenv("BOT_WEBHOOK_MODE", "").lower() in ("1","true","webhook"):
                await application.bot.set_webhook(url=wh_url, secret_token=wh_secret, allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)
                logger.info(f"🔗 Webhook ثبت شد: {wh_url}")
            else:
                # در حالت polling، webhook باید حذف باشد تا polling کار کند
                try:
                    await application.bot.delete_webhook(drop_pending_updates=False)
                except: pass
    except Exception as e:
        logger.warning(f"webhook setup failed: {e}")

    # 💓 اولین تپش قلب: همان لحظه که ربات بالا آمد (قبل از هر کار کند)
    # نوشته می‌شود تا /api/health/deep بداند polling شروع شده است.
    from bot_heartbeat import write_heartbeat
    write_heartbeat({'phase': 'post_init', 'started_at': now_utc().isoformat()})

    shared_bootstrap = await db.bootstrap_shared()
    logger.info("✅ bootstrap مشترک: آماده=%s", shared_bootstrap.get("ready"))

    # 💍 Ring Street — بازیابی گفت‌وگوهای فعال و flowهای معلق از دیتابیس
    # (§۴۳: state هرگز فقط در RAM نیست). خطای این مرحله مانع بالا آمدن
    # ربات نمی‌شود.
    if ring_street is not None:
        try:
            _ring_rec = await ring_street.post_init(application.bot)
            logger.info("💍 رینگ استریت: flag=%s بازیابی=%s",
                        _ring_rec.get("flag"), _ring_rec.get("loaded"))
        except Exception as e:
            logger.error(f"ring post_init error: {e}")

    # FIX: گارد ایمن — اگر JobQueue نصب نباشد، ربات کرش نکند
    if application.job_queue is not None:
        # زمان‌های user-facing مستقیماً با IANA Asia/Tehran ثبت می‌شوند.
        application.job_queue.run_daily(
            exam_reminder_job,
            time=dtime(hour=8, minute=0, tzinfo=TEHRAN),
            name='exam_reminder'
        )

        application.job_queue.run_daily(
            daily_question_job,
            time=dtime(hour=9, minute=0, tzinfo=TEHRAN),
            name='daily_question'
        )

        # گزارش هفتگی — یکشنبه‌ها ۰۹:۳۰ تهران
        # نکته: در PTB days=(0,) یعنی یکشنبه (0=sunday...6=saturday)
        application.job_queue.run_daily(
            weekly_report_job,
            time=dtime(hour=9, minute=30, tzinfo=TEHRAN),
            days=(0,),
            name='weekly_report'
        )

        # 🔴 FIX حیاتی: پردازش صف پیام‌های Mini App — هر ۲۰ ثانیه چک می‌شود
        application.job_queue.run_repeating(
            mini_app_outbox_job,
            interval=20,
            first=10,
            name='mini_app_outbox'
        )

        # 💓 موج Railway — تپش قلب ربات برای /api/health/deep
        # ربات هر BOT_HEARTBEAT_INTERVAL ثانیه یک فایل کوچک در /tmp
        # می‌نویسد؛ API با عمرِ آن می‌فهمد event loop ربات واقعاً جلو
        # می‌رود (psutil به‌تنهایی فقط می‌گوید PID زنده است — نه اینکه
        # حلقه قفل نشده باشد). خطای نوشتن هیچ‌وقت ربات را متوقف نمی‌کند.
        application.job_queue.run_repeating(
            bot_heartbeat_job,
            interval=HEARTBEAT_INTERVAL,
            first=0,
            name='bot_heartbeat',
        )

        # 💍 Ring Street — timeout صف/جلسه + ترمیم claimهای یتیم (§۲۲/§۶۴)
        # و آمار روزانه (§۳۶). هر دو idempotent‌اند و با flag خاموش بی‌کارند.
        if ring_jobs is not None:
            application.job_queue.run_repeating(
                ring_jobs.ring_housekeeping_job,
                interval=30,
                first=25,
                name='ring_housekeeping'
            )
            application.job_queue.run_daily(
                ring_jobs.ring_daily_job,
                time=dtime(hour=4, minute=10, tzinfo=TEHRAN),
                name='ring_daily'
            )
            # 💍 V5 §۴/§۵ — «تیک» تایمرِ زندهٔ جست‌وجو (edit روی همان پیام، هر
            # ~۱۰ ثانیه، حداکثر SEARCH_TICK_LIMIT کاربر). اگر نسخهٔ ring/jobs.py
            # روی سرور قدیمی‌تر باشد و این تابع را نداشته باشد، ربات نباید در
            # boot بمیرد — پس با hasattr (ریسکِ دیپلویِ ناقص = همان چیزی که
            # باعث شد باگ‌های V۴ در پروداکشن زنده بمانند).
            if hasattr(ring_jobs, 'ring_search_tick_job'):
                application.job_queue.run_repeating(
                    ring_jobs.ring_search_tick_job,
                    interval=10,
                    first=12,
                    name='ring_search_tick'
                )

        # FIX جدید: نوتیف منابع جدید — هر ساعت چک می‌شود، خودش تشخیص
        # می‌دهد آیا فاصله‌ی تنظیم‌شده (۲۴/۴۸/۷۲ ساعت) گذشته یا نه
        application.job_queue.run_repeating(
            new_resources_notif_job,
            interval=3600,
            first=120,
            name='new_resources_notif'
        )

        # 🌊 W8/UX-04 — یادآوری تیکت‌های مانده (هر ۶ ساعت)
        application.job_queue.run_repeating(
            ticket_stale_job,
            interval=21600,
            first=600,
            name='ticket_stale'
        )

        # FIX جدید: بکاپ خودکار — هر ساعت چک می‌شود، فقط در ساعت
        # تنظیم‌شده (از پنل ادمین) واقعاً بکاپ می‌گیرد
        application.job_queue.run_repeating(
            auto_backup_job,
            interval=3600,
            first=180,
            name='auto_backup'
        )

        # چک روزانه‌ی انقضای اشتراک — ۰۹:۱۵ تهران
        application.job_queue.run_daily(
            subscription_expiry_job,
            time=dtime(hour=9, minute=15, tzinfo=TEHRAN),
            name='subscription_expiry'
        )
        # 🗄 W4/DB-02 — retention روزانه‌ی audit_logs (۰۳:۳۰ تهران؛
        # خارج از ساعت بکاپ و رینگ)
        application.job_queue.run_daily(
            audit_retention_job,
            time=dtime(hour=3, minute=30, tzinfo=TEHRAN),
            name='audit_retention'
        )
        # 🌊 W2 — sweep ساعتی (بدون نوتیف تکراری) + reconcile کیف پول + cleanup زرین‌پال
        application.job_queue.run_repeating(
            subscription_expiry_sweep_job,
            interval=3600, first=600, name='subscription_expiry_sweep'
        )
        application.job_queue.run_repeating(
            wallet_reconcile_job,
            interval=1800, first=300, name='wallet_reconcile'
        )
        application.job_queue.run_repeating(
            zarinpal_cleanup_job,
            interval=3600, first=1200, name='zarinpal_cleanup'
        )
        # 💳 W14 — پیگیری پرداخت نیمه‌تمام درگاه (با کلید خاموش بی‌کار است)
        application.job_queue.run_repeating(
            dunning_job,
            interval=600, first=120, name='dunning_tick'
        )

        # بستن هفته‌ی Prestige — شنبه ۰۰:۰۵ تهران (PTB: شنبه=۶)
        application.job_queue.run_daily(
            prestige_weekly_close_job,
            time=dtime(hour=0, minute=5, tzinfo=TEHRAN),
            days=(6,),
            name='prestige_weekly_close'
        )

        # اسکن هفتگی چالش آماده — یکشنبه ۱۹:۴۰ تهران
        application.job_queue.run_daily(
            prestige_challenge_scan_job,
            time=dtime(hour=19, minute=40, tzinfo=TEHRAN),
            days=(0,),
            name='prestige_challenge_scan'
        )

        # FIX: قبلاً اینجا یه job برای جاروی حافظه‌ی موقتِ RAM هوشیار بود؛
        # حافظه الان روی دیتابیس ذخیره می‌شه (پایدار در برابرِ ری‌استارت)
        # و TTL موقعِ خوندن چک می‌شه، پس این job دیگه لازم نیست.

        logger.info("✅ Job‌های زمان‌بندی ثبت شدند")

        # FIX (ارسال زماندار پایدار): اگر ربات بین ثبت یک پیام زماندار
        # و زمان ارسالش ری‌استارت شود، job در حافظه‌ی job_queue از بین
        # می‌رفت و پیام هرگز ارسال نمی‌شد. حالا رکورد آن در دیتابیس هم
        # ذخیره شده بود؛ اینجا در شروع ربات آن‌ها را می‌خوانیم و دوباره
        # زمان‌بندی می‌کنیم (یا اگر زمانش گذشته، فوراً ارسال می‌کنیم).
        try:
            from admin import _scheduled_broadcast_job
            pending = await db.get_settings_by_prefix('scheduled_broadcast_')
            for key, rec in pending.items():
                job_id = key[len('scheduled_broadcast_'):]
                try:
                    send_at = parse_machine_datetime(rec['send_at'])
                except Exception:
                    continue
                remaining = (send_at - now_utc()).total_seconds()
                delay = max(remaining, 0)
                application.job_queue.run_once(
                    _scheduled_broadcast_job,
                    when=timedelta(seconds=delay),
                    data={'msg_data': rec.get('msg_data', {}), 'target': rec.get('target', 'all'),
                          'admin_id': rec.get('created_by', ADMIN_ID)},
                    name=job_id,
                )
            if pending:
                logger.info(f"✅ {len(pending)} پیام زماندار قدیمی دوباره زمان‌بندی شد")
        except Exception:
            logger.exception("خطا در بازیابی پیام‌های زماندار قبلی")
    else:
        logger.warning("⚠️ JobQueue فعال نیست — یادآوری‌ها و گزارش هفتگی غیرفعال هستند")
        logger.warning('   نصب با: pip install "python-telegram-bot[job-queue]"')


def _env_flag(name: str, default: bool = False) -> bool:
    """پرچم boolean از env — مقادیر 1/true/yes/on = True."""
    raw = (os.getenv(name) or '').strip().lower()
    if not raw:
        return default
    return raw in ('1', 'true', 'yes', 'on')


def _run_polling_with_retry(build_app):
    """🛡 HOTFIX پایداری startup — کرش مشاهده‌شده در دیپلوی:

    یک TimedOut گذرا به api.telegram.org حین initialize کل پروسه را
    می‌کشت؛ با چند کرش پیاپی، supervisor به FATAL می‌رفت و بات برای
    همه‌ی پیام‌ها (شامل /start) کاملاً خاموش می‌ماند. حالا خطاهای
    شبکه‌ای با backoff retry می‌شوند و اپلیکیشن در هر تلاش بازسازی
    می‌شود. خطای پیکربندی (InvalidToken) هرگز retry نمی‌شود — باید
    همان کرش صریح بماند تا مشکل توکن دیده شود.
    🌊 W5 — اگر BOT_WEBHOOK_MODE=1 و WEBHOOK_URL ست باشد، به‌جای polling از webhook استفاده می‌شود (پایدارتر روی Railway).
    """
    from telegram.error import TimedOut, NetworkError, RetryAfter

    drop_pending = _env_flag('BOT_DROP_PENDING', False)
    if drop_pending:
        logger.warning("⚠️ BOT_DROP_PENDING=1 — updateهای pending در شروع حذف می‌شوند")

    # 🌊 W5 webhook mode check
    wh_mode = _env_flag('BOT_WEBHOOK_MODE', False) or _env_flag('WEBHOOK_MODE', False)
    wh_url = (os.getenv('WEBHOOK_URL') or os.getenv('BOT_WEBHOOK_URL') or '').strip()
    wh_secret = (os.getenv('WEBHOOK_SECRET') or os.getenv('BOT_WEBHOOK_SECRET') or '').strip() or None
    if wh_mode and wh_url:
        # 🛡 W3/BUG-06 — حالت webhook روی Railway تک‌پورت پشتیبانی
        # نمی‌شود (تک‌پورت با uvicorn تداخل می‌کند)؛ مسیر سالم polling
        # است. این شاخه فقط برای سازگاری/دیباگ نگه داشته شده — جزئیات در
        # docs/runbook.md (بخش «حالت webhook»).
        logger.warning(
            "BOT_WEBHOOK_MODE is set but webhook is NOT supported on "
            "single-port Railway — use polling (unset BOT_WEBHOOK_MODE). "
            "See docs/runbook.md.")
        # در حالت webhook، polling اجرا نمی‌شود — webhook server
        attempt = 0
        while True:
            app = build_app()
            logger.info("🩺 ربات پزشکی (webhook) شروع به کار کرد... url=%s (تلاش %d)", wh_url, attempt + 1)
            try:
                # Railway: پورت داخلی BOT_WEBHOOK_PORT (پیش‌فرض 8001) — باید از WEBHOOK_URL مسیر را جدا کنیم
                import urllib.parse as _up
                parsed = _up.urlparse(wh_url)
                # مسیر webhook: اگر URL شامل path باشد همان، وگرنه /bot-webhook
                url_path = (parsed.path or '/bot-webhook').lstrip('/') or 'bot-webhook'
                listen = os.getenv('BOT_WEBHOOK_LISTEN', '0.0.0.0')
                port = int(os.getenv('BOT_WEBHOOK_PORT') or os.getenv('PORT') or '8001')
                app.run_webhook(
                    listen=listen, port=port, url_path=url_path,
                    webhook_url=wh_url, secret_token=wh_secret,
                    drop_pending_updates=drop_pending, allowed_updates=Update.ALL_TYPES,
                )
                return
            except (TimedOut, NetworkError, RetryAfter) as e:
                attempt += 1
                delay = min(30, 2 ** min(attempt, 4))
                logger.error("⚠️ webhook startup ناپایدار (%s: %s)؛ retry در %dث", type(e).__name__, e, delay)
                time.sleep(delay)
            except Exception as e:
                # InvalidToken یا خطای پیکربندی نباید retry شود
                if 'InvalidToken' in type(e).__name__ or 'Unauthorized' in str(e):
                    raise
                attempt += 1
                delay = min(30, 2 ** min(attempt, 4))
                logger.error("⚠️ webhook error (%s) retry در %dث", e, delay)
                time.sleep(delay)

    attempt = 0
    while True:
        app = build_app()
        logger.info("🩺 ربات پزشکی شروع به کار کرد... (تلاش %d)", attempt + 1)
        try:
            app.run_polling(
                drop_pending_updates=drop_pending,
                allowed_updates=Update.ALL_TYPES,
                poll_interval=0.5,
            )
            return  # خروج تمیز (SIGINT/stop) — نه کرش
        except (TimedOut, NetworkError, RetryAfter) as e:
            attempt += 1
            delay = min(30, 2 ** min(attempt, 4))
            logger.error(
                "⚠️ اتصال تلگرام در startup ناپایدار بود (%s: %s)؛ "
                "تلاش مجدد در %d ثانیه — پروسه زنده می‌ماند تا "
                "supervisor به FATAL نرود.",
                type(e).__name__, e, delay)
            time.sleep(delay)


async def _graceful_shutdown(app):
    # 🌊 W3 — graceful: بستن http client مشترک + آزادسازی db
    try:
        from http_client import aclose_shared_client
        await aclose_shared_client()
    except Exception: pass
    try:
        # short grace for in-flight handlers
        import asyncio as _aio
        await _aio.sleep(0.2)
    except: pass
    try:
        db.client.close()
    except: pass

def _build_application_with_post_init():
    app = build_application()
    app.post_init = post_init
    app.post_shutdown = _graceful_shutdown
    return app


def main():
    _run_polling_with_retry(_build_application_with_post_init)


if __name__ == '__main__':
    main()
