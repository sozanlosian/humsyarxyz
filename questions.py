"""
بانک سوال — نسخه نهایی بهینه‌سازی‌شده
✅ فیکس دکمه‌های بازگشت در همه مسیرها
✅ آزمون سفارشی persistent با اجرای Bot/PDF
✅ تمرین سریع با solved-unique و AI fallback شخصی
✅ طراحی سؤال با lifecycle بررسی مشترک
✅ نمایش طراح سوال
✅ فیلتر درس + مبحث
✅ آمار پیشرفته
✅ بهینه‌سازی سرعت — کش لیست درس‌ها و مباحث
"""
import os, io, asyncio, logging, time
from datetime import datetime
from utils import esc as escape   # 🛡 AUDIT-A6 —escape مرکزی
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import db
from utils import send_audit_log, fmt_jalali_dt
from time_utils import now_tehran, utc_now_iso
from question_bank import ExamService, QuestionBankService, QuestionDomainError
from question_bank.ai_practice import AIPersonalPracticeService
from question_bank.contracts import (
    DIFFICULTY_LABELS, canonical_difficulty, canonical_status,
)

logger     = logging.getLogger(__name__)
ADMIN_ID   = int(os.getenv('ADMIN_ID', '0'))
ANSWERING  = 4
CREATING_Q = 6
question_bank = QuestionBankService(db)
exam_domain = ExamService(db)
ai_practice = AIPersonalPracticeService(db)

DIFF_EMOJI = {'آسان 🟢': '🟢', 'متوسط 🟡': '🟡', 'سخت 🔴': '🔴'}
LETTERS    = ['🅐', '🅑', '🅒', '🅓']


# ══════════════════════════════════════════════════════════
#  ابزارهای کمکی
# ══════════════════════════════════════════════════════════

def _back(label: str, cb: str) -> list:
    """ردیف دکمه بازگشت استاندارد"""
    return [InlineKeyboardButton(label, callback_data=cb)]


def _h(value) -> str:
    """Escape domain/user text before Telegram HTML rendering.

    🛡 AUDIT-A6 — به هلپر مرکزی واگذار شد؛ رفتار قبلی `str(value or "")` بود که
    عدد صفر را به رشته‌ی خالی تبدیل می‌کرد (شماره‌ی جلسه/سوال صفر «گم» می‌شد).
    """
    from utils import esc as _central
    return _central(value)


# ══════════════════════════════════════════════════════════
#  تابع ورودی از ReplyKeyboard (message_router)
# ══════════════════════════════════════════════════════════

async def _main_menu_msg(message):
    """نمایش منوی اصلی از طریق message (نه callback)"""
    keyboard = [
        [InlineKeyboardButton("📝 تمرین سریع",            callback_data='questions:practice')],
        [InlineKeyboardButton("🎯 آزمون سفارشی",          callback_data='questions:custom_exam')],
        [InlineKeyboardButton("✍️ طراحی سؤال",            callback_data='questions:create')],
        [InlineKeyboardButton("📚 سؤال‌های من",           callback_data='questions:my_questions')],
        [InlineKeyboardButton("📊 آمار و پیشرفت من",      callback_data='questions:stats')],
    ]
    await message.reply_text(
        "🧠 <b>بانک سؤال</b>\n\n"
        "📝 <b>تمرین سریع</b>\nبرای یادگیری و دیدن فوری پاسخ و تحلیل.\n\n"
        "🎯 <b>آزمون سفارشی</b>\nبرای سنجش خودت با تعداد، زمان و نوع اجرای دلخواه.\n\n"
        "✍️ <b>طراحی سؤال</b>\nسؤالت را برای بررسی و ورود به بانک پیشنهاد بده.\n\n"
        "📚 <b>سؤال‌های من</b>\nوضعیت بررسی و دلیل اصلاح یا رد را ببین.",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


# ══════════════════════════════════════════════════════════
#  Callback اصلی
# ══════════════════════════════════════════════════════════

async def questions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    data   = query.data
    parts  = data.split(':')
    action = parts[1] if len(parts) > 1 else 'main'
    uid    = update.effective_user.id

    # FIX جدید: دفاع لایه‌دوم اشتراک — اکشن‌های ca_* (بررسی سوال توسط
    # ادمین محتوا) از این گیت مستثنی‌اند، چون کار مدیریتی است نه مصرف محتوا
    if not action.startswith('ca_'):
        from subscription import feature_allowed
        if not await feature_allowed(uid, "question_bank"):
            await query.answer("🔒 اول باید اشتراک فعال کنی — از «🧪 بانک سوال» شروع کن.", show_alert=True)
            return
    await query.answer()

    # ── منوی اصلی ──
    if action == 'main':
        await _main_menu(query)

    # ── آزمون سفارشی ──
    elif action == 'custom_exam':
        await _custom_exam_menu(query, context)

    elif action == 'cx_lesson':
        idx     = int(parts[2])
        lessons = context.user_data.get('_cx_lessons', [])
        if idx < len(lessons):
            selected = lessons[idx]
            context.user_data.setdefault('cx', {}).update({
                'lesson_id': selected['id'], 'lesson': selected['name']})
            context.user_data['cx_lesson_idx'] = idx
            await _cx_topic_select(query, context, selected)

    elif action == 'cx_topic':
        topics = context.user_data.get('_cx_topics', [])
        selected = None if parts[2] == 'all' else (topics[int(parts[2])] if int(parts[2]) < len(topics) else None)
        context.user_data.setdefault('cx', {}).update({
            'topic_id': selected['id'] if selected else '',
            'topic': selected['name'] if selected else 'همه'})
        await _cx_count_select(query, context)

    elif action == 'cx_count':
        count = int(parts[2])
        context.user_data.setdefault('cx', {})['count'] = count
        await _cx_time_select(query, context)

    elif action == 'cx_back_count':
        await _cx_count_select(query, context)

    elif action == 'cx_time':
        minutes = int(parts[2])
        context.user_data.setdefault('cx', {})['time'] = minutes
        await _cx_output_select(query, context)

    elif action == 'cx_output':
        context.user_data.setdefault('cx', {})['output_mode'] = parts[2]
        await _cx_preview(query, context, uid)

    elif action == 'cx_confirm':
        await _cx_start(query, context, uid, allow_smaller=False)

    elif action == 'cx_confirm_smaller':
        await _cx_start(query, context, uid, allow_smaller=True)

    elif action == 'cx_resume':
        context.user_data['exam_session_id'] = parts[2]
        await _next_exam_q(query, context, uid)

    elif action == 'exam_history':
        await _exam_history(query, uid)

    elif action == 'exam_abandon':
        await _abandon_exam(query, context, uid)

    # ── تمرین آزاد ──
    elif action == 'practice':
        await _practice_menu(query)

    elif action == 'free':
        await _term_select(query, context, 'free')

    # §W8 — بازگشت به تمرین پس از گزارشِ سؤال. جریانِ تمرین نباید با
    # گزارش قطع شود؛ وضعیتِ `quiz` دست‌نخورده است، فقط سؤالِ بعدی را
    # می‌آوریم. اگر وضعیتی نمانده باشد، به منوی تمرین برمی‌گردیم.
    elif action == 'practice_next':
        if not context.user_data.get('quiz'):
            await _practice_menu(query)
        else:
            await _next_q(query, context, uid)

    elif action == 'weak':
        context.user_data['quiz'] = {'mode': 'weak', 'answered': [], 'correct': 0, 'total': 999}
        await _next_q(query, context, uid)

    elif action == 'hard':
        context.user_data['quiz'] = {'mode': 'hard', 'difficulty': 'سخت 🔴', 'answered': [], 'correct': 0, 'total': 999}
        await _next_q(query, context, uid)

    elif action == 'exam':
        # Legacy callback now converges on the persistent Custom Exam domain.
        await _custom_exam_menu(query, context)

    elif action == 'sel_term':
        mode = parts[2]; term_idx = int(parts[3])
        await _lesson_select(query, context, mode, term_idx)

    elif action == 'sel_term_back':
        mode = parts[2]
        await _term_select(query, context, mode)

    elif action == 'sel_lesson':
        mode    = parts[2]; idx = int(parts[3])
        lessons = context.user_data.get('_lessons', [])
        if idx < len(lessons):
            lesson = lessons[idx]
            context.user_data['sel_lesson']     = lesson
            context.user_data['sel_lesson_idx'] = idx
            context.user_data['quiz'] = {
                'mode': mode, 'lesson': lesson,
                'answered': [], 'correct': 0,
                'total': 20 if mode == 'exam' else 999
            }
            await _topic_select(query, context, lesson, mode)

    elif action == 'sel_topic':
        mode   = parts[2]
        topics = context.user_data.get('_topics', [])
        topic  = 'همه' if parts[3] == 'all' else (topics[int(parts[3])] if int(parts[3]) < len(topics) else 'همه')
        lesson = context.user_data.get('sel_lesson', '')
        if mode == 'exam':
            context.user_data['cx'] = {'lesson': lesson, 'topic': topic,
                                       'count': 20, 'time': 0}
            await _cx_output_select(query, context)
        else:
            context.user_data.setdefault('quiz', {}).update({
                'lesson': lesson, 'topic': topic, 'mode': mode,
                'answered': [], 'correct': 0, 'total': 999
            })
            await _next_q(query, context, uid)

    elif action == 'next':
        await _next_q(query, context, uid)

    elif action == 'exam_next':
        await _next_exam_q(query, context, uid)

    elif action == 'exam_answer':
        await _handle_exam_answer(query, context, uid, parts[2], int(parts[3]))

    elif action == 'ai_fallback':
        await _generate_personal_ai_question(query, context, uid)

    elif action == 'ai_personal_answer':
        await _answer_personal_ai(query, context, uid, parts[2], int(parts[3]))

    elif action == 'ai_personal_propose':
        await _propose_personal_ai(query, context, uid, parts[2])

    elif action == 'my_questions':
        await _my_questions(query, uid, int(parts[2]) if len(parts) > 2 else 0)

    elif action == 'edit_my':
        await _edit_my_question(query, context, uid, parts[2])

    elif action == 'stats':
        await _quiz_stats(query, uid)

    # ── طراحی سوال ──
    elif action in ('create', 'create_ca'):
        is_ca = (action == 'create_ca') or await db.is_content_admin(uid)
        context.user_data['creating_as_ca'] = is_ca
        await _create_start(query, context)

    elif action == 'cr_lesson':
        idx     = int(parts[2])
        lessons = context.user_data.get('_lessons', [])
        if idx < len(lessons):
            lesson = lessons[idx]
            context.user_data['new_q'] = {'lesson_id': lesson['id'], 'lesson': lesson['name']}
            context.user_data['cr_lesson'] = lesson['name']
            await _create_topic_select(query, context, lesson)

    elif action == 'cr_topic':
        topics = context.user_data.get('_topics', [])
        idx = int(parts[2])
        topic = topics[idx] if idx < len(topics) else None
        if not topic:
            await query.answer("مبحث معتبر نیست", show_alert=True); return
        context.user_data.setdefault('new_q', {}).update({'topic_id': topic['id'], 'topic': topic['name']})
        context.user_data['mode']        = 'creating_question'
        context.user_data['create_step'] = 'question'
        await query.edit_message_text(
            f"✏️ <b>طراحی سوال</b>\n"
            f"📚 {context.user_data.get('cr_lesson','')} — {topic['name']}\n\n"
            "━━━━━━━━━━━━━━━━\n"
            "📝 <b>گام ۱ از ۵ — متن سوال</b>\n\nسوال خود را بنویسید:",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ لغو", callback_data='questions:main')
            ]]))
        return CREATING_Q

    elif action == 'submit_question':
        await _save_question(update, context)

    # Legacy AI-authoring callback now explains the personal-practice policy.
    elif action in ('ai_create', 'ai_lesson', 'ai_topic', 'ai_diff', 'ai_regen', 'ai_save'):
        await query.edit_message_text(
            "🤖 سؤال هوشمند در نسخه جدید فقط وقتی سؤال‌های معتبر یک مبحث را کامل کرده باشی، "
            "از داخل «تمرین سریع» ساخته می‌شود و خودکار وارد بانک مشترک نمی‌شود.",
            reply_markup=InlineKeyboardMarkup([_back("📝 رفتن به تمرین سریع", "questions:practice"),
                                               _back("🔙 بانک سؤال", "questions:main")]))

    # ── ⚠️ قابلیتِ جدید: تاییدِ ذخیره‌سازیِ سوالِ (احتمالاً) تکراری ──
    elif action == 'dup_confirm':
        q = context.user_data.get('new_q') or context.user_data.get('ai_q_generated')
        if context.user_data.get('new_q'):
            context.user_data['allow_probable_duplicate'] = True
            await _do_insert_manual_question(update, context, context.user_data.get('new_q', {}), query.from_user.id)
        else:
            await query.answer("⚠️ چیزی برای ذخیره نیست.", show_alert=True)

    elif action == 'dup_cancel':
        for k in ('new_q', 'create_step', 'mode', 'cr_lesson', 'creating_as_ca',
                  'ai_q_lesson', 'ai_q_topic', 'ai_q_difficulty', 'ai_q_note',
                  'ai_q_generated', '_ai_lessons', '_ai_topics'):
            context.user_data.pop(k, None)
        await query.edit_message_text(
            "❌ لغو شد — سوال ذخیره نشد.",
            reply_markup=InlineKeyboardMarkup([_back("🔙 بازگشت به بانک سوال", "questions:main")]))

    # ── مدیریت سوالات توسط ادمین محتوا/ادمین ──
    elif action == 'ca_q_list':
        await _ca_question_list(query, uid, context)

    elif action == 'ca_q_view':
        qid = parts[2] if len(parts) > 2 else ''
        await _ca_question_view(query, uid, qid)

    elif action == 'ca_q_del':
        await _h_ca_q_del(query, context, uid, parts[2] if len(parts) > 2 else '', target='rejected')

    elif action == 'ca_q_needs_changes':
        await _h_ca_q_del(query, context, uid, parts[2] if len(parts) > 2 else '', target='needs_changes')

    elif action == 'ca_q_edit':
        await _h_ca_q_edit(query, context, uid, parts[2] if len(parts) > 2 else '')

    elif action == 'ca_q_approve':
        await _h_ca_q_approve(query, context, uid, parts[2] if len(parts) > 2 else '')

    # 🛡 §۸۴ — حذف سخت: دو مرحله‌ای، چون برگشت‌ناپذیر است.
    elif action == 'ca_q_purge':
        await _h_ca_q_purge_confirm(query, context, uid, parts[2] if len(parts) > 2 else '')

    elif action == 'ca_q_purge_yes':
        await _h_ca_q_purge(query, context, uid, parts[2] if len(parts) > 2 else '')

    elif action == 'ca_q_filter':
        ftype = parts[2] if len(parts) > 2 else 'all'
        fval  = parts[3] if len(parts) > 3 else ''
        context.user_data[f'caq_filter_{ftype}'] = fval
        context.user_data['caq_page'] = 0
        await _ca_question_list(query, uid, context)

    elif action == 'ca_q_page':
        context.user_data['caq_page'] = max(0, int(parts[2] if len(parts) > 2 else 0))
        await _ca_question_list(query, uid, context)

    elif data.startswith('answer:'):
        await handle_question_answer(update, context)


# ══════════════════════════════════════════════════════════
#  🌊 Q2-W8 — هندلرهای استخراج‌شده از questions_callback
#  (بدون تغییر رفتار؛ routing/scope/audit دقیقاً مثل قبل)
# ══════════════════════════════════════════════════════════
async def _h_ca_q_del(query, context, uid: int, qid: str, target='rejected'):
    can_review = (await db.has_permission(uid, 'questions.review') or
                  await db.has_permission(uid, 'questions.review_scoped'))
    if not can_review or not await db.has_permission(uid, 'questions.reject'):
        await query.answer("مجوز رد یا درخواست اصلاح سؤال را ندارید.", show_alert=True); return
    question = await db.get_question_by_id(qid)
    if not question:
        await query.answer("سؤال پیدا نشد.", show_alert=True); return
    scope = await db.get_scoped_intake(uid)
    if scope and (question.get('intake') or '') != scope:
        await query.answer("این سؤال خارج از scope شماست.", show_alert=True); return
    context.user_data['mode'] = 'question_review_reason'
    context.user_data['q_review'] = {'qid': qid, 'target': target}
    label = 'رد' if target == 'rejected' else 'درخواست اصلاح'
    await query.edit_message_text(f"📝 دلیل {label} سؤال را بنویسید (حداقل ۳ کاراکتر):",
        reply_markup=InlineKeyboardMarkup([_back("❌ لغو", "questions:ca_q_list")]))


async def handle_question_review_reason_text(update, context):
    data = context.user_data.get('q_review') or {}; reason = (update.message.text or '').strip()
    if len(reason) < 3:
        await update.message.reply_text("دلیل باید حداقل ۳ کاراکتر باشد."); return
    uid = update.effective_user.id
    try:
        updated = await question_bank.transition(question_id=data.get('qid',''), reviewer={'id': uid},
                                                 target=data.get('target','rejected'), reason=reason)
    except QuestionDomainError as exc:
        await update.message.reply_text(f"❌ {exc.message}"); return
    context.user_data.pop('mode', None); context.user_data.pop('q_review', None)
    await send_audit_log(context.bot, 'content', str(uid), uid,
        "بررسی سؤال", module='Questions', severity='WARNING',
        target_id=str(updated.get('_id')), target_type='question',
        details=f"{updated.get('status')} · {reason}", tags=['بررسی_سؤال'])
    await update.message.reply_text("✅ نتیجه بررسی ثبت و به دانشجو اطلاع داده شد.")


async def _h_ca_q_approve(query, context, uid: int, qid: str):
    if not (await db.has_permission(uid, 'questions.review') or
            await db.has_permission(uid, 'questions.review_scoped')):
        await query.answer("مجوز تأیید سؤال را ندارید.", show_alert=True); return
    question = await db.get_question_by_id(qid)
    if not question:
        await query.answer("سؤال پیدا نشد.", show_alert=True); return
    scope = await db.get_scoped_intake(uid)
    if scope and (question.get('intake') or '') != scope:
        await query.answer("این سؤال خارج از scope شماست.", show_alert=True); return
    try:
        updated = await question_bank.transition(question_id=qid, reviewer={'id': uid},
                                                 target='approved', reason='')
    except QuestionDomainError as exc:
        await query.answer(exc.message, show_alert=True); return
    await query.answer("✅ سؤال تأیید و منتشر شد.", show_alert=True)
    await send_audit_log(context.bot, 'content', str(uid), uid,
        "تأیید سؤال", module='Questions', severity='INFO',
        target_id=qid, target_type='question', target_label=question.get('question','')[:60],
        tags=['تأیید_سؤال'])
    await _ca_question_list(query, uid, context)


async def _h_ca_q_purge_confirm(query, context, uid: int, qid: str):
    """گام ۱ — نمایش هشدار. هیچ تغییری در داده نمی‌دهد."""
    if not await db.has_permission(uid, 'questions.delete'):
        await query.answer("مجوز حذف سؤال را ندارید.", show_alert=True); return
    question = await db.get_question_by_id(qid)
    if not question:
        await query.answer("سؤال پیدا نشد.", show_alert=True); return
    await query.edit_message_text(
        "🗑 <b>حذف همیشگی سؤال</b>\n\n"
        f"❓ {_h((question.get('question') or '')[:200])}\n\n"
        "⚠️ این کار <b>برگشت‌ناپذیر</b> است و سؤال از پایگاه داده پاک می‌شود.\n"
        "اگر فقط می‌خواهید سؤال از چرخه خارج شود، «❌ رد با دلیل» را بزنید "
        "تا داده حفظ و برای طراح قابل اصلاح بماند.",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 بله، برای همیشه حذف کن",
                                  callback_data=f'questions:ca_q_purge_yes:{qid}')],
            _back("🔙 انصراف", f'questions:ca_q_view:{qid}'),
        ]))


async def _h_ca_q_purge(query, context, uid: int, qid: str):
    """گام ۲ — حذف واقعی. مجوزسنجی در question_bank است (منبع یکتا)."""
    question = await db.get_question_by_id(qid)
    if not question:
        await query.answer("سؤال پیدا نشد.", show_alert=True); return
    try:
        removed = await question_bank.delete_question(
            question_id=qid, actor={'id': uid}, reason='حذف از ربات مدیر')
    except QuestionDomainError as exc:
        await query.answer(exc.message, show_alert=True); return
    await query.answer("🗑 سؤال برای همیشه حذف شد.", show_alert=True)
    await send_audit_log(context.bot, 'content', str(uid), uid,
        "حذف سؤال", module='Questions', severity='CRITICAL',
        target_id=qid, target_type='question',
        target_label=(question.get('question') or '')[:60],
        details=f"status={removed.get('status')} · creator={removed.get('creator_id')}",
        tags=['حذف_سؤال'])
    await _ca_question_list(query, uid, context)


# ══════════════════════════════════════════════════════════
#  منوها
# ══════════════════════════════════════════════════════════

async def _main_menu(query):
    keyboard = [
        [InlineKeyboardButton("📝 تمرین سریع",            callback_data='questions:practice')],
        [InlineKeyboardButton("🎯 آزمون سفارشی",          callback_data='questions:custom_exam')],
        [InlineKeyboardButton("✍️ طراحی سؤال",            callback_data='questions:create')],
        [InlineKeyboardButton("📚 سؤال‌های من",           callback_data='questions:my_questions')],
        [InlineKeyboardButton("📊 آمار و پیشرفت من",      callback_data='questions:stats')],
        _back("🔙 داشبورد", "dashboard:refresh"),
    ]
    await query.edit_message_text(
        "🧠 <b>بانک سؤال</b>\n\n"
        "📝 <b>تمرین سریع</b> — یادگیری با بازخورد فوری\n"
        "🎯 <b>آزمون سفارشی</b> — سنجش زمان‌دار داخل ربات یا PDF\n"
        "✍️ <b>طراحی سؤال</b> — مشارکت در بانک پس از بررسی\n"
        "📚 <b>سؤال‌های من</b> — وضعیت، دلیل و ارسال مجدد\n"
        "📊 <b>آمار من</b> — سؤال‌های یکتا و مباحث ضعیف",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _practice_menu(query):
    keyboard = [
        [InlineKeyboardButton("📖 تمرین آزاد",                callback_data='questions:free')],
        [InlineKeyboardButton("⚡ نقاط ضعف من",               callback_data='questions:weak')],
        [InlineKeyboardButton("🔴 سؤال‌های سطح سخت",          callback_data='questions:hard')],
        _back("🔙 بازگشت", "questions:main"),
    ]
    await query.edit_message_text(
        "🧪 <b>تمرین سریع</b>\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📖 <b>آزاد:</b> یادگیری با پاسخ و تحلیل فوری\n"
        "⚡ <b>نقاط ضعف:</b> تمرین مبحث‌هایی با دقت پایین\n"
        "🔴 <b>سخت:</b> سؤال‌های سطح hard\n\n"
        "برای سنجش تعداددار و زمان‌دار از «آزمون سفارشی» استفاده کن.",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


# ══════════════════════════════════════════════════════════
#  آزمون سفارشی
# ══════════════════════════════════════════════════════════

async def _picker_intake(uid: int):
    """🌊 C1.5 — scope دید pickerهای سوال (لیست درس/مبحث/فصل/سختی و
    انتخاب گزینه‌های آزمون): مدیر محتوا → None (پیش‌نمایش بدون فیلتر،
    رفتار قدیمی)؛ دانشجو → [ورودی خودش + سراسری].
    enforce حیاتی هرجا لازم است در خودِ کوئری اعمال می‌شود."""
    if await db.is_content_admin(uid):
        return None
    u = await db.get_user(uid)
    return db.student_intake_filter((u or {}).get('intake', ''))


async def _custom_exam_menu(query, context):
    user = await db.get_user(query.from_user.id) or {}
    tree = await question_bank.taxonomy_tree(
        visible_intakes=db.student_intake_filter(user.get('intake', '')),
        only_with_questions=True)
    if not tree:
        await query.edit_message_text("❌ هنوز سؤال معتبر و قابل‌مشاهده‌ای در بانک نیست.",
            reply_markup=InlineKeyboardMarkup([_back("🔙 بازگشت", "questions:main")]))
        return
    context.user_data['_cx_lessons'] = tree
    context.user_data['cx'] = {}
    keyboard = []
    for i in range(0, len(tree), 2):
        row = [InlineKeyboardButton(f"📚 {tree[i]['name']} · {tree[i]['question_count']}", callback_data=f'questions:cx_lesson:{i}')]
        if i + 1 < len(tree):
            row.append(InlineKeyboardButton(f"📚 {tree[i+1]['name']} · {tree[i+1]['question_count']}", callback_data=f'questions:cx_lesson:{i+1}'))
        keyboard.append(row)
    active = await exam_domain.active(user={"id": query.from_user.id, "_db": user})
    if active and active.get('status') == 'active':
        keyboard.insert(0, [InlineKeyboardButton("▶️ ادامه آزمون فعال", callback_data=f"questions:cx_resume:{active['session_id']}")])
    keyboard.append([InlineKeyboardButton("📜 تاریخچه آزمون‌ها", callback_data="questions:exam_history")])
    keyboard.append(_back("🔙 بازگشت", "questions:main"))
    await query.edit_message_text(
        "🎯 <b>آزمون سفارشی</b>\n\nبرای سنجش خودت، درس را انتخاب کن. "
        "آزمون ثبت می‌شود و بعد از restart هم قابل ادامه است.",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _cx_topic_select(query, context, lesson):
    topics = [x for x in lesson.get('topics', []) if x.get('question_count', 0) > 0]
    context.user_data['_cx_topics'] = topics
    keyboard = [[InlineKeyboardButton(f"📌 {t['name']} · {t['question_count']}", callback_data=f'questions:cx_topic:{i}')]
                for i, t in enumerate(topics)]
    keyboard.append([InlineKeyboardButton(f"📂 همه مباحث · {lesson.get('question_count',0)}", callback_data='questions:cx_topic:all')])
    keyboard.append(_back("🔙 بازگشت", "questions:custom_exam"))
    await query.edit_message_text(
        f"🎯 <b>آزمون سفارشی</b>\n📚 {_h(lesson['name'])}\n\n<b>گام ۲:</b> مبحث را انتخاب کن:",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _cx_count_select(query, context):
    cx = context.user_data.get('cx', {})
    keyboard = [
        [InlineKeyboardButton("۵ سؤال", callback_data='questions:cx_count:5'), InlineKeyboardButton("۱۰ سؤال", callback_data='questions:cx_count:10')],
        [InlineKeyboardButton("۱۵ سؤال", callback_data='questions:cx_count:15'), InlineKeyboardButton("۲۰ سؤال", callback_data='questions:cx_count:20')],
        [InlineKeyboardButton("۳۰ سؤال", callback_data='questions:cx_count:30'), InlineKeyboardButton("۴۰ سؤال", callback_data='questions:cx_count:40')],
        _back("🔙 بازگشت", f"questions:cx_lesson:{context.user_data.get('cx_lesson_idx',0)}")]
    await query.edit_message_text(
        f"🎯 <b>آزمون سفارشی</b>\n📚 {_h(cx.get('lesson'))} — {_h(cx.get('topic','همه'))}\n\n<b>گام ۳:</b> تعداد سؤال را انتخاب کن:",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _cx_time_select(query, context):
    cx = context.user_data.get('cx', {})
    keyboard = [
        [InlineKeyboardButton("بدون محدودیت", callback_data='questions:cx_time:0')],
        [InlineKeyboardButton("۱۰ دقیقه", callback_data='questions:cx_time:10'), InlineKeyboardButton("۲۰ دقیقه", callback_data='questions:cx_time:20')],
        [InlineKeyboardButton("۳۰ دقیقه", callback_data='questions:cx_time:30'), InlineKeyboardButton("۴۵ دقیقه", callback_data='questions:cx_time:45')],
        [InlineKeyboardButton("۶۰ دقیقه", callback_data='questions:cx_time:60'), InlineKeyboardButton("۹۰ دقیقه", callback_data='questions:cx_time:90')],
        _back("🔙 بازگشت", "questions:cx_back_count")]
    await query.edit_message_text(
        f"🎯 <b>آزمون سفارشی</b>\n📚 {_h(cx.get('lesson'))} — {_h(cx.get('topic','همه'))}\n"
        f"🔢 {cx.get('count',10)} سؤال\n\n<b>گام ۴:</b> زمان آزمون را انتخاب کن:",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _cx_output_select(query, context):
    cx = context.user_data.get('cx', {})
    keyboard = [
        [InlineKeyboardButton("🤖 اجرا داخل ربات", callback_data='questions:cx_output:bot')],
        [InlineKeyboardButton("📄 PDF تمرینی — پاسخ زیر سؤال", callback_data='questions:cx_output:pdf_practice')],
        [InlineKeyboardButton("📝 PDF آزمونی — پاسخنامه انتهایی", callback_data='questions:cx_output:pdf_exam')],
        _back("🔙 بازگشت", "questions:cx_back_count")]
    await query.edit_message_text(
        f"🎯 <b>نوع اجرای آزمون</b>\n\n📚 {_h(cx.get('lesson',''))} — {_h(cx.get('topic','همه'))}\n"
        f"🔢 {cx.get('count',10)} سؤال · ⏱ {cx.get('time',0) or 'بدون محدودیت'}\n\n"
        "داخل ربات برای پاسخ‌دادن و ثبت نتیجه است؛ PDF برای چاپ یا حل آفلاین.",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _cx_preview(query, context, uid):
    cx = context.user_data.get('cx', {})
    user = await db.get_user(uid) or {}
    taxonomy = {'lesson_id': cx.get('lesson_id',''), 'topic_id': cx.get('topic_id',''),
                'lesson': cx.get('lesson',''), 'topic': '' if cx.get('topic') == 'همه' else cx.get('topic','')}
    try:
        preview = await exam_domain.preview(user={'id': uid, '_db': user}, taxonomy=taxonomy,
            requested_count=int(cx.get('count',10)), minutes=int(cx.get('time',0)),
            output_mode=cx.get('output_mode','bot'))
    except QuestionDomainError as exc:
        await query.edit_message_text(f"❌ {exc.message}", reply_markup=InlineKeyboardMarkup([_back("🔙 بازگشت", "questions:custom_exam")]))
        return
    available, requested = preview['available_count'], preview['requested_count']
    lines = (f"🎯 <b>پیش‌نمایش آزمون</b>\n\n📚 {_h(cx.get('lesson',''))} — {_h(cx.get('topic','همه'))}\n"
             f"📦 سؤال معتبر موجود: <b>{available}</b>\n🔢 تعداد انتخابی: <b>{requested}</b>\n"
             f"⏱ زمان: <b>{cx.get('time',0) or 'بدون محدودیت'}</b>\n")
    keyboard = []
    if available >= requested:
        keyboard.append([InlineKeyboardButton("✅ تأیید و ساخت آزمون", callback_data='questions:cx_confirm')])
    elif available > 0:
        lines += f"\n⚠️ حداکثر {available} سؤال قابل تولید است؛ بدون تأیید شما تعداد کم نمی‌شود."
        keyboard.append([InlineKeyboardButton(f"✅ ساخت با {available} سؤال", callback_data='questions:cx_confirm_smaller')])
    else:
        lines += "\n❌ برای این فیلتر سؤالی وجود ندارد."
    keyboard.append(_back("🔙 تغییر تنظیمات", "questions:custom_exam"))
    await query.edit_message_text(lines, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _cx_start(query, context, uid, allow_smaller=False):
    cx = context.user_data.get('cx', {})
    user = await db.get_user(uid) or {}
    taxonomy = {'lesson_id': cx.get('lesson_id',''), 'topic_id': cx.get('topic_id',''),
                'lesson': cx.get('lesson',''), 'topic': '' if cx.get('topic') == 'همه' else cx.get('topic','')}
    try:
        exam = await exam_domain.create(user={'id': uid, '_db': user}, taxonomy=taxonomy,
            requested_count=int(cx.get('count',10)), minutes=int(cx.get('time',0)),
            output_mode=cx.get('output_mode','bot'), allow_smaller=allow_smaller)
    except QuestionDomainError as exc:
        await query.edit_message_text(f"❌ {exc.message}", reply_markup=InlineKeyboardMarkup([_back("🔙 بازگشت", "questions:custom_exam")]))
        return
    context.user_data['exam_session_id'] = exam['session_id']
    if exam['output_mode'].startswith('pdf_'):
        mode = 'practice' if exam['output_mode'] == 'pdf_practice' else 'exam'
        try:
            pdf, meta = await exam_domain.generate_pdf(session_id=exam['session_id'], user={'id': uid, '_db': user}, mode=mode)
            file_obj = io.BytesIO(pdf)
            file_obj.name = f"humsyar_exam_{meta['exam_code']}.pdf"
            sent = await query.message.reply_document(file_obj, filename=file_obj.name,
                caption=f"📄 <b>دفترچه آزمون</b>\n📚 {_h(exam['lesson'])} — {_h(exam['topic'] or 'همه مباحث')}\n"
                        f"🔢 {exam['actual_count']} سؤال · کد <code>{meta['exam_code']}</code>", parse_mode='HTML')
            sent_doc = getattr(sent, 'document', None)
            await db.question_pdf_generations.update_one(
                {'generation_id': meta['generation_id']},
                {'$set': {'delivery': 'telegram', 'telegram_file_id': getattr(sent_doc, 'file_id', None),
                          'telegram_message_id': getattr(sent, 'message_id', None), 'telegram_chat_id': uid}})
            await query.edit_message_text("✅ دفترچه ساخته و به آزمون ذخیره‌شده متصل شد.",
                reply_markup=InlineKeyboardMarkup([_back("🔙 بانک سؤال", "questions:main")]))
        except Exception:
            logger.exception("question bank PDF generation failed session=%s", exam['session_id'])
            await query.edit_message_text("❌ ساخت فایل با مشکل مواجه شد. لطفاً دوباره تلاش کنید.",
                reply_markup=InlineKeyboardMarkup([_back("🔙 بازگشت", "questions:custom_exam")]))
        return
    await _next_exam_q(query, context, uid)


async def _exam_history(query, uid):
    user_doc = await db.get_user(uid) or {}
    result = await exam_domain.history(user={"id": uid, "_db": user_doc}, skip=0, limit=10)
    if not result.get("exams"):
        await query.edit_message_text("هنوز آزمون ذخیره‌شده‌ای نداری.",
            reply_markup=InlineKeyboardMarkup([_back("🔙 آزمون سفارشی", "questions:custom_exam")]))
        return
    status_labels = {"active": "▶️ فعال", "finished": "✅ تمام‌شده",
                     "expired": "⌛ منقضی", "abandoned": "⏹ رهاشده"}
    lines = []
    keyboard = []
    for exam in result["exams"]:
        lines.append(
            f"{status_labels.get(exam['status'], exam['status'])} · {_h(exam.get('lesson',''))} / {_h(exam.get('topic') or 'همه')}\n"
            f"{exam.get('answered',0)}/{exam.get('total',0)} پاسخ · {exam.get('percentage',0)}٪ · <code>{exam.get('exam_code') or '—'}</code>")
        if exam["status"] == "active":
            keyboard.append([InlineKeyboardButton("▶️ ادامه آزمون فعال",
                                                   callback_data=f"questions:cx_resume:{exam['session_id']}")])
    keyboard.append(_back("🔙 آزمون سفارشی", "questions:custom_exam"))
    await query.edit_message_text("📜 <b>تاریخچه آزمون‌های من</b>\n\n" + "\n\n".join(lines),
                                  parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


async def _abandon_exam(query, context, uid):
    session_id = context.user_data.get("exam_session_id")
    if not session_id:
        await query.answer("آزمون فعالی انتخاب نشده است.", show_alert=True)
        return
    user_doc = await db.get_user(uid) or {}
    try:
        await exam_domain.abandon(session_id=session_id, user={"id": uid, "_db": user_doc})
    except QuestionDomainError as exc:
        await query.answer(exc.message, show_alert=True)
        return
    context.user_data.pop("exam_session_id", None)
    await query.edit_message_text("⏹ آزمون رها شد و در تاریخچه باقی ماند.",
        reply_markup=InlineKeyboardMarkup([_back("📜 تاریخچه", "questions:exam_history"),
                                           _back("🏠 بانک سؤال", "questions:main")]))


async def _next_q(query, context, uid):
    quiz = context.user_data.get('quiz', {})
    mode = quiz.get('mode', 'free')
    user_doc = await db.get_user(uid) or {}
    user = {'id': uid, '_db': user_doc}
    taxonomy = {}
    try:
        if mode == 'weak':
            stats = await question_bank.stats(user=user)
            weak = sorted(stats['weak_topics'], key=lambda x: (x['accuracy'], -x['attempts']))
            if not weak:
                await query.edit_message_text("برای تشخیص نقاط ضعف، اول چند تمرین انجام بده.",
                    reply_markup=InlineKeyboardMarkup([_back("🔙 تمرین سریع", "questions:practice")]))
                return
            taxonomy = weak[0]
        elif quiz.get('lesson'):
            taxonomy = await question_bank.resolve_taxonomy(
                lesson_id=quiz.get('lesson_id'), topic_id=quiz.get('topic_id'),
                lesson=quiz.get('lesson'), topic=None if quiz.get('topic') == 'همه' else quiz.get('topic'),
                visible_intakes=db.student_intake_filter(user_doc.get('intake','')),
                require_topic=bool(quiz.get('topic') and quiz.get('topic') != 'همه'))
            quiz.update({'lesson_id': taxonomy.get('lesson_id'), 'topic_id': taxonomy.get('topic_id')})
        result = await question_bank.practice_next(user=user, taxonomy=taxonomy,
                                                   mode='hard' if mode == 'hard' else mode)
    except QuestionDomainError as exc:
        await query.edit_message_text(f"❌ {exc.message}", reply_markup=InlineKeyboardMarkup([_back("🔙 تمرین سریع", "questions:practice")]))
        return
    q = result.get('question')
    progress = result.get('progress') or {}
    if not q:
        if result.get('ai_available') and taxonomy.get('topic_id'):
            context.user_data['quiz_taxonomy'] = taxonomy
            await query.edit_message_text(
                f"✅ همه {progress.get('total',0)} سؤال معتبر این مبحث را حداقل یک‌بار حل کرده‌ای.\n\n"
                "می‌توانی برای ادامه تمرین، یک سؤال شخصی با هوشیار بسازی. این سؤال خودکار وارد بانک مشترک نمی‌شود.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🤖 ساخت سؤال شخصی", callback_data='questions:ai_fallback')],
                                                   _back("🔙 تمرین سریع", "questions:practice")]))
        else:
            await query.edit_message_text("❌ سؤال حل‌نشده‌ای برای این فیلتر پیدا نشد.",
                reply_markup=InlineKeyboardMarkup([_back("🔙 تمرین سریع", "questions:practice")]))
        return
    qid = q['id']
    context.user_data['current_practice_question'] = qid
    raw = await db.get_question_by_id(qid)
    creator_line = ''
    if raw:
        if raw.get('creator_type') == 'ai': creator_line = "\n<i>🤖 منبع: AI تأییدشده بانک</i>"
        elif raw.get('creator_name'): creator_line = f"\n<i>✏️ طراح: {_h(raw.get('creator_name'))}</i>"
    letters = ['🅐','🅑','🅒','🅓']
    keyboard = [[InlineKeyboardButton(f"{letters[i]} {opt}", callback_data=f'answer:{qid}:{i}')]
                for i, opt in enumerate(q['options'][:4])]
    keyboard.append([InlineKeyboardButton("⚠️ گزارش ایراد سؤال", callback_data=f'report:question:{qid}')])
    keyboard.append([InlineKeyboardButton("🏠 منو", callback_data='questions:main')])
    await query.edit_message_text(
        f"📝 <b>تمرین سریع</b> · {_h(q['difficulty_label'])}\n📚 {_h(q.get('lesson',''))} — {_h(q.get('topic',''))}\n"
        f"📊 یکتا: {progress.get('solved_unique',0)}/{progress.get('total',0)}\n━━━━━━━━━━━━━━━━\n\n{_h(q['question'])}{creator_line}",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _next_exam_q(query, context, uid):
    session_id = context.user_data.get('exam_session_id')
    if not session_id:
        await query.edit_message_text("آزمون فعالی انتخاب نشده است.", reply_markup=InlineKeyboardMarkup([_back("🔙 آزمون سفارشی", "questions:custom_exam")]))
        return
    user_doc = await db.get_user(uid) or {}
    user = {'id': uid, '_db': user_doc}
    try:
        result = await exam_domain.next_question(session_id=session_id, user=user)
    except QuestionDomainError as exc:
        await query.edit_message_text(f"❌ {exc.message}", reply_markup=InlineKeyboardMarkup([_back("🔙 آزمون سفارشی", "questions:custom_exam")]))
        return
    if result.get('finished'):
        await query.edit_message_text(
            f"🏁 <b>آزمون پایان یافت</b>\n\n✅ صحیح: {result.get('correct',0)} از {result.get('answered',0)}\n"
            f"📊 درصد: {result.get('percentage',0)}٪\nکد آزمون: <code>{result.get('exam_code','')}</code>",
            parse_mode='HTML', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📜 آزمون جدید", callback_data='questions:custom_exam')],
                                                                  _back("🏠 بانک سؤال", "questions:main")]))
        return
    q = result['question']
    letters = ['🅐','🅑','🅒','🅓']
    keyboard = [[InlineKeyboardButton(f"{letters[i]} {opt}", callback_data=f"questions:exam_answer:{session_id}:{i}")]
                for i, opt in enumerate(q['options'][:4])]
    keyboard.append([InlineKeyboardButton("⏹ رها کردن آزمون", callback_data="questions:exam_abandon")])
    remain = result.get('seconds_left')
    remain_text = ''
    if remain is not None:
        m, sec = divmod(remain, 60)
        remain_text = f"\n⏱ {m:02d}:{sec:02d} باقی‌مانده"
    await query.edit_message_text(
        f"🎯 <b>آزمون سفارشی · سؤال {result['progress']}/{result['total']}</b>{remain_text}\n"
        f"📚 {_h(q.get('lesson',''))} — {_h(q.get('topic',''))}\n━━━━━━━━━━━━━━━━\n\n{_h(q['question'])}",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _handle_exam_answer(query, context, uid, session_id, selected):
    user_doc = await db.get_user(uid) or {}
    try:
        result = await exam_domain.answer(session_id=session_id, user={'id': uid, '_db': user_doc}, selected=selected)
    except QuestionDomainError as exc:
        await query.answer(exc.message, show_alert=True)
        return
    if result.get('finished'):
        context.user_data.pop('exam_session_id', None)
        summary = result.get('result') or {}
        await query.edit_message_text(
            f"🏁 <b>آزمون تمام شد</b>\n\n"
            f"✅ پاسخ صحیح: <b>{summary.get('correct', 0)}</b> از {summary.get('answered', result.get('total', 0))}\n"
            f"📊 امتیاز: <b>{summary.get('percentage', 0)}٪</b>",
            parse_mode='HTML', reply_markup=InlineKeyboardMarkup([_back("📜 آزمون‌ها", "questions:exam_history"),
                                                                  _back("🏠 بانک سؤال", "questions:main")]))
    else:
        await query.edit_message_text(
            "✅ پاسخ ثبت شد. نتیجه‌ها تا پایان آزمون نمایش داده نمی‌شوند.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➡️ سؤال بعد", callback_data='questions:exam_next')],
                                               [InlineKeyboardButton("⏹ رها کردن آزمون", callback_data='questions:exam_abandon')]]))


async def _generate_personal_ai_question(query, context, uid):
    taxonomy = context.user_data.get('quiz_taxonomy') or {}
    user_doc = await db.get_user(uid) or {}
    try:
        result = await ai_practice.generate(user={'id': uid, '_db': user_doc}, taxonomy=taxonomy,
                                            difficulty='medium', require_exhaustion=True)
    except QuestionDomainError as exc:
        await query.edit_message_text(f"⚠️ {exc.message}", reply_markup=InlineKeyboardMarkup([_back("🔙 تمرین سریع", "questions:practice")]))
        return
    q = result['question']
    aid = q['ai_question_id']
    letters = ['🅐','🅑','🅒','🅓']
    keyboard = [[InlineKeyboardButton(f"{letters[i]} {opt}", callback_data=f"questions:ai_personal_answer:{aid}:{i}")]
                for i, opt in enumerate(q['options'])]
    await query.edit_message_text(
        f"🤖 <b>سؤال شخصی هوشیار</b>\n📚 {_h(q.get('lesson'))} — {_h(q.get('topic'))}\n"
        f"<i>AI generated · {_h(q['provenance']['prompt_version'])}</i>\n━━━━━━━━━━━━━━━━\n\n{_h(q['question'])}",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _answer_personal_ai(query, context, uid, ai_question_id, selected):
    user_doc = await db.get_user(uid) or {}
    try:
        result = await ai_practice.answer(user={'id': uid, '_db': user_doc}, ai_question_id=ai_question_id, selected=selected)
    except QuestionDomainError as exc:
        await query.answer(exc.message, show_alert=True)
        return
    await query.edit_message_text(
        f"{'✅ درست' if result['is_correct'] else '❌ نادرست'}\n\nپاسخ صحیح: گزینه {result['correct_answer'] + 1}\n"
        f"💡 {_h(result.get('explanation') or '—')}\n\nاین سؤال شخصی است و هنوز در بانک مشترک نیست.",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 پیشنهاد به بانک مشترک", callback_data=f"questions:ai_personal_propose:{ai_question_id}")],
            [InlineKeyboardButton("🤖 سؤال شخصی دیگر", callback_data='questions:ai_fallback')],
            _back("🏠 بانک سؤال", "questions:main")]))


async def _propose_personal_ai(query, context, uid, ai_question_id):
    user_doc = await db.get_user(uid) or {}
    try:
        await ai_practice.propose(user={'id': uid, '_db': user_doc}, ai_question_id=ai_question_id)
    except QuestionDomainError as exc:
        await query.answer(exc.message, show_alert=True)
        return
    await query.edit_message_text("✅ سؤال برای بررسی ورود به بانک مشترک ارسال شد.",
        reply_markup=InlineKeyboardMarkup([_back("🏠 بانک سؤال", "questions:main")]))


async def handle_question_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = update.effective_user.id
    parts = query.data.split(':')
    qid   = parts[1]
    sel   = int(parts[2])

    q_doc = await db.get_question_by_id(qid)
    if not q_doc:
        await query.edit_message_text("❌ سوال پیدا نشد!"); return

    correct_idx = q_doc.get('correct_answer', 0)
    is_correct  = (sel == correct_idx)

    # 👑 Prestige (موج P0): پیش‌چک یک‌بارهرسؤال → ثبت → رویداد موتور
    try:
        _ft = (await db.answers.find_one(
            {'user_id': uid, 'question_id': qid}, {'_id': 1})) is None
    except Exception:
        _ft = True
    user_doc = await db.get_user(uid) or {}
    try:
        await question_bank.record_answer(user={'id': uid, '_db': user_doc},
                                          question=q_doc, selected=sel,
                                          is_correct=is_correct, mode='practice')
    except QuestionDomainError as exc:
        await query.answer(exc.message, show_alert=True)
        return
    try:
        _ps_ev = await db.prestige_event(uid, 'answer', {
            'is_correct': is_correct,
            'difficulty': q_doc.get('difficulty', ''),
            'first_time': _ft})
    except Exception:
        _ps_ev = None

    quiz = context.user_data.setdefault('quiz', {})
    if is_correct:
        quiz['correct'] = quiz.get('correct', 0) + 1

    opts    = q_doc.get('options', [])
    expl    = q_doc.get('explanation', '')
    icon    = "✅" if is_correct else "❌"

    options_text = ""
    for i, opt in enumerate(opts):
        if i == correct_idx:                   marker = "✅"
        elif i == sel and not is_correct:      marker = "❌"
        else:                                  marker = "⚫"
        options_text += f"{marker} {_h(opt)}\n"

    text = (f"{icon} <b>{'صحیح!' if is_correct else 'اشتباه!'}</b>\n\n"
            f"{_h(q_doc['question'])}\n\n{options_text}")
    if expl:
        text += f"\n💡 <b>توضیح:</b> {_h(expl)}"

    # 👑 Prestige: خط XP درون همین پیام (بازخورد تعاملی — اعلان جداگانه‌ی جدیدی نیست)
    if _ps_ev and not _ps_ev.get('ignored'):
        _d = _ps_ev.get('display', {})
        _e = _ps_ev.get('events', {})
        if _ps_ev.get('xp_gained', 0) > 0:
            text += (f"\n\n⚡ +<b>{_ps_ev['xp_gained']}</b> XP"
                     f" · {_d.get('icon','')} {_d.get('title','')} {_d.get('stars','')}")
            if _e.get('streak_new_day') and _ps_ev['streak']['current'] >= 2:
                text += f" · 🔥 {_ps_ev['streak']['current']} روز"
        if _e.get('rank_up'):
            _ru = _e['rank_up']
            text += (f"\n\n🎉 <b>تبریک! ارتقای رنک</b>\n"
                     f"حالا {_ru['icon']} <b>{_ru['to']}</b> هستی! 🛡 سپر ارتقا هم فعال شد.")
        elif _e.get('div_up'):
            _du = _e['div_up']
            text += (f"\n\n🎉 <b>ارتقا!</b> حالا {_du['icon']} {_du['rank']}"
                     f" <b>{_du['roman']}</b> هستی!")
        elif _e.get('challenge_ready'):
            text += "\n\n⭐ <b>چالش ارتقا آماده است!</b> برای رنک بعدی باید چالش بزنی."

    # تعیین دکمه بازگشت صحیح
    mode    = quiz.get('mode', 'free')
    back_cb = 'questions:custom_exam' if mode == 'custom' else 'questions:practice'

    keyboard = [[
        InlineKeyboardButton("➡️ سوال بعدی", callback_data='questions:next'),
        InlineKeyboardButton("🏠 منو",        callback_data='questions:main')
    ]]
    await query.edit_message_text(text, parse_mode='HTML',
                                  reply_markup=InlineKeyboardMarkup(keyboard))


# ══════════════════════════════════════════════════════════
#  انتخاب درس/مبحث برای تمرین
# ══════════════════════════════════════════════════════════

async def _term_select(query, context, mode):
    """
    FIX جدید: لایه‌ی انتخاب ترم قبل از درس — مثل بخش منابع علوم پایه.
    قبلاً همه دروس همه ترم‌ها یکجا و تخت نشان داده می‌شد که گیج‌کننده
    و طولانی بود؛ حالا اول ترم، بعد فقط دروس همان ترم.
    """
    from utils import TERMS
    keyboard = []
    for i in range(0, len(TERMS), 2):
        row = [InlineKeyboardButton(f"📘 {TERMS[i]}", callback_data=f'questions:sel_term:{mode}:{i}')]
        if i+1 < len(TERMS):
            row.append(InlineKeyboardButton(f"📘 {TERMS[i+1]}", callback_data=f'questions:sel_term:{mode}:{i+1}'))
        keyboard.append(row)
    keyboard.append(_back("🔙 بازگشت", "questions:practice"))
    label = "شبیه‌سازی امتحان" if mode == 'exam' else "تمرین آزاد"
    await query.edit_message_text(
        f"📚 <b>{label}</b>\n\nترم را انتخاب کنید:",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _lesson_select(query, context, mode, term_idx: int = None):
    from utils import TERMS
    term = TERMS[term_idx] if term_idx is not None and term_idx < len(TERMS) else None
    context.user_data['sel_term_idx'] = term_idx
    # 🌊 C1.5 — لیست درس‌های انتخابی فقط در scope دید کاربر
    lessons = await db.get_lessons(
        term=term, intake=await _picker_intake(query.from_user.id))
    back_cb = f'questions:sel_term_back:{mode}' if term_idx is not None else 'questions:practice'
    if not lessons:
        await query.edit_message_text(
            f"❌ هنوز درسی برای {term or 'این بخش'} ثبت نشده.",
            reply_markup=InlineKeyboardMarkup([
                _back("🔙 بازگشت", back_cb)
            ])); return
    context.user_data['_lessons'] = lessons
    keyboard = []
    for i in range(0, len(lessons), 2):
        row = [InlineKeyboardButton(f"📚 {lessons[i]}", callback_data=f'questions:sel_lesson:{mode}:{i}')]
        if i+1 < len(lessons):
            row.append(InlineKeyboardButton(f"📚 {lessons[i+1]}", callback_data=f'questions:sel_lesson:{mode}:{i+1}'))
        keyboard.append(row)
    keyboard.append(_back("🔙 بازگشت", back_cb))
    label = "شبیه‌سازی امتحان" if mode == 'exam' else "تمرین آزاد"
    term_label = f" — {term}" if term else ""
    await query.edit_message_text(f"📚 <b>{label}{term_label}</b>\n\nدرس را انتخاب کنید:",
                                  parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _topic_select(query, context, lesson, mode):
    # 🌊 C1.5 — مباحث فقط در scope دید کاربر
    topics = await db.get_topics(
        lesson, intake=await _picker_intake(query.from_user.id))
    context.user_data['_topics'] = topics
    # بازگشت به لیست درس‌های همان ترم (نه شروع دوباره از انتخاب ترم)
    term_idx = context.user_data.get('sel_term_idx')
    if term_idx is not None:
        back_cb = f'questions:sel_term:{mode}:{term_idx}'
    else:
        back_cb = f'questions:{"exam" if mode=="exam" else "free"}'
    keyboard = [[InlineKeyboardButton(f"📌 {t}", callback_data=f'questions:sel_topic:{mode}:{i}')]
                for i, t in enumerate(topics)]
    keyboard.append([InlineKeyboardButton("📂 همه مباحث", callback_data=f'questions:sel_topic:{mode}:all')])
    keyboard.append(_back("🔙 بازگشت", back_cb))
    await query.edit_message_text(f"📚 <b>{_h(lesson)}</b>\n\nمبحث را انتخاب کنید:",
                                  parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


# ══════════════════════════════════════════════════════════
#  آمار
# ══════════════════════════════════════════════════════════

async def _my_questions(query, uid, page=0):
    page = max(0, int(page)); page_size = 12
    data = await question_bank.list_my_contributions(uid, skip=page * page_size, limit=page_size)
    if not data['questions']:
        await query.edit_message_text("هنوز سؤالی پیشنهاد نکرده‌ای.",
            reply_markup=InlineKeyboardMarkup([_back("✍️ طراحی سؤال", "questions:create"),
                                               _back("🔙 بانک سؤال", "questions:main")]))
        return
    labels = {'pending': '⏳ در انتظار', 'approved': '✅ تأییدشده',
              'rejected': '❌ ردشده', 'needs_changes': '✏️ نیازمند اصلاح'}
    lines = []; keyboard = []
    for item in data['questions'][:12]:
        status = item['status']; reason = f" — {_h(item['review_reason'])}" if item.get('review_reason') else ''
        lines.append(f"{labels.get(status,status)} · {_h(item['lesson'])} / {_h(item['topic'])}\n{_h(item['question'][:70])}{reason}")
        if status in ('rejected', 'needs_changes'):
            keyboard.append([InlineKeyboardButton(f"✏️ اصلاح: {item['question'][:25]}",
                                                   callback_data=f"questions:edit_my:{item['id']}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("قبلی", callback_data=f"questions:my_questions:{page-1}"))
    if (page + 1) * page_size < data['total']:
        nav.append(InlineKeyboardButton("بعدی", callback_data=f"questions:my_questions:{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append(_back("🔙 بانک سؤال", "questions:main"))
    await query.edit_message_text(f"📚 <b>سؤال‌های من</b> · صفحه {page+1}\n\n" + "\n\n".join(lines),
                                  parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _edit_my_question(query, context, uid, qid):
    q = await db.get_question_by_id(qid)
    if not q or int(q.get('creator_id') or 0) != uid or q.get('status') not in ('rejected', 'needs_changes'):
        await query.answer("این سؤال قابل اصلاح نیست.", show_alert=True); return
    context.user_data['editing_question_id'] = qid
    context.user_data['new_q'] = {'lesson_id': q.get('lesson_id'), 'topic_id': q.get('topic_id'),
                                  'lesson': q.get('lesson',''), 'topic': q.get('topic','')}
    context.user_data['mode'] = 'creating_question'; context.user_data['create_step'] = 'question'
    await query.edit_message_text(
        f"✏️ <b>اصلاح و ارسال مجدد</b>\n\nدلیل بررسی: {_h(q.get('review_reason') or '—')}\n\n"
        "گام ۱ — متن اصلاح‌شده سؤال را بفرست:", parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([_back("❌ لغو", "questions:my_questions")]))


async def _quiz_stats(query, uid):
    user_doc = await db.get_user(uid) or {}; stats = await question_bank.stats(user={'id': uid, '_db': user_doc})
    designed = await db.questions.count_documents({'creator_id': uid})
    text = (f"📊 <b>آمار بانک سؤال من</b>\n━━━━━━━━━━━━━━━━\n\n"
            f"🧠 سؤال یکتای حل‌شده: <b>{stats['solved_unique']}</b>\n"
            f"🧪 کل تلاش‌ها: <b>{stats['attempts']}</b>\n"
            f"✅ درست: <b>{stats['correct']}</b> · ❌ غلط: <b>{stats['wrong']}</b>\n"
            f"📈 دقت: <b>{stats['accuracy']}٪</b>\n"
            f"✍️ سؤال‌های پیشنهادی: <b>{designed}</b>")
    if stats['weak_topics']:
        text += "\n\n⚡ <b>مباحث نیازمند تمرین</b>\n" + "\n".join(
            f"• {_h(x['lesson'])} / {_h(x['topic'])} — {x['accuracy']}٪ از {x['attempts']} تلاش"
            for x in stats['weak_topics'][:5])
    await query.edit_message_text(text, parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([_back("🔙 بانک سؤال", "questions:main")]))


# ══════════════════════════════════════════════════════════
#  طراحی سوال
# ══════════════════════════════════════════════════════════

async def _create_start(query, context):
    user = await db.get_user(query.from_user.id) or {}
    tree = await question_bank.taxonomy_tree(
        visible_intakes=db.student_intake_filter(user.get('intake','')),
        only_with_questions=False)
    if not tree:
        await query.edit_message_text("❌ هنوز taxonomy درس و مبحث تعریف نشده است.",
            reply_markup=InlineKeyboardMarkup([_back("🔙 بانک سؤال", "questions:main")]))
        return
    context.user_data['_lessons'] = tree
    keyboard = []
    for i in range(0, len(tree), 2):
        row = [InlineKeyboardButton(f"📚 {tree[i]['name']}", callback_data=f'questions:cr_lesson:{i}')]
        if i + 1 < len(tree): row.append(InlineKeyboardButton(f"📚 {tree[i+1]['name']}", callback_data=f'questions:cr_lesson:{i+1}'))
        keyboard.append(row)
    keyboard.append(_back("🔙 بانک سؤال", "questions:main"))
    await query.edit_message_text(
        "✍️ <b>طراحی سؤال</b>\n\nسؤال پس از preview و بررسی نقش مجاز وارد بانک می‌شود.\n"
        "ابتدا درس را انتخاب کن:", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _create_topic_select(query, context, lesson):
    topics = lesson.get('topics') or []
    if not topics:
        await query.edit_message_text("❌ برای این درس مبحث معتبری تعریف نشده است.",
            reply_markup=InlineKeyboardMarkup([_back("🔙 انتخاب درس", "questions:create")]))
        return
    context.user_data['_topics'] = topics
    keyboard = [[InlineKeyboardButton(f"📌 {t['name']}", callback_data=f'questions:cr_topic:{i}')]
                for i, t in enumerate(topics)]
    keyboard.append(_back("🔙 انتخاب درس", "questions:create"))
    await query.edit_message_text(f"✍️ <b>{_h(lesson['name'])}</b>\n\nمبحث معتبر را انتخاب کن:",
                                  parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_create_question_steps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    step = context.user_data.get('create_step', '')
    q    = context.user_data.setdefault('new_q', {})

    if text in ('❌ لغو', '/start', '/cancel'):
        context.user_data.pop('mode', None)
        context.user_data.pop('create_step', None)
        await update.message.reply_text("❌ طراحی سوال لغو شد.")
        return ConversationHandler.END

    if step == 'question':
        if len(text) < 10:
            await update.message.reply_text("⚠️ متن سوال باید حداقل ۱۰ کاراکتر باشد.")
            return CREATING_Q
        q['question'] = text
        context.user_data['create_step'] = 'opt1'
        await update.message.reply_text(
            "📝 <b>گام ۲ از ۵ — گزینه الف</b>\n\nگزینه اول را بنویسید:",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ لغو", callback_data='questions:main')
            ]]))

    elif step in ('opt1', 'opt2', 'opt3', 'opt4'):
        opts = q.setdefault('options', [])
        opts.append(text)
        next_map = {'opt1': ('opt2', 'ب', 3), 'opt2': ('opt3', 'ج', 4), 'opt3': ('opt4', 'د', 4)}
        if step == 'opt4':
            context.user_data['create_step'] = 'correct'
            opt_list = "\n".join(f"  {LETTERS[i]} {_h(o)}" for i, o in enumerate(opts))
            await update.message.reply_text(
                f"✅ گزینه‌ها:\n{opt_list}\n\n"
                "📝 <b>گام ۴ از ۵ — گزینه صحیح</b>\n\nشماره گزینه صحیح را بنویسید (1-4):",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ لغو", callback_data='questions:main')
                ]]))
        else:
            ns, label, step_n = next_map[step]
            context.user_data['create_step'] = ns
            await update.message.reply_text(
                f"📝 <b>گام {step_n} از ۵ — گزینه {label}</b>\n\nگزینه بعدی را بنویسید:",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ لغو", callback_data='questions:main')
                ]]))

    elif step == 'correct':
        if text not in ('1', '2', '3', '4'):
            await update.message.reply_text("⚠️ عدد ۱ تا ۴ وارد کنید.")
            return CREATING_Q
        q['correct'] = int(text) - 1
        context.user_data['create_step'] = 'difficulty'
        keyboard = [
            [InlineKeyboardButton("🟢 آسان",  callback_data='qd:easy')],
            [InlineKeyboardButton("🟡 متوسط", callback_data='qd:medium')],
            [InlineKeyboardButton("🔴 سخت",   callback_data='qd:hard')],
        ]
        await update.message.reply_text(
            "📝 <b>گام ۵ از ۵ — سطح سختی</b>\n\nسطح سختی را انتخاب کنید:",
            parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

    elif step == 'explanation':
        q['explanation'] = '' if text == '-' else text
        opts = q.get('options', [])
        preview = "\n".join(f"{'✅' if i == q.get('correct') else '▫️'} {i+1}) {_h(opt)}" for i, opt in enumerate(opts))
        context.user_data['create_step'] = 'preview'
        await update.message.reply_text(
            f"👁 <b>پیش‌نمایش سؤال</b>\n📚 {_h(q.get('lesson'))} — {_h(q.get('topic'))}\n"
            f"━━━━━━━━━━━━━━━━\n❓ {_h(q.get('question'))}\n\n{preview}\n\n💡 {_h(q.get('explanation') or 'بدون تحلیل')}",
            parse_mode='HTML', reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ ارسال برای بررسی", callback_data='questions:submit_question')],
                [InlineKeyboardButton("❌ لغو", callback_data='questions:main')]]))
        return ConversationHandler.END

    return CREATING_Q


async def handle_difficulty_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    diff_map = {'easy': 'آسان 🟢', 'medium': 'متوسط 🟡', 'hard': 'سخت 🔴'}
    diff = diff_map.get(query.data.split(':')[1], 'متوسط 🟡')
    context.user_data.setdefault('new_q', {})['difficulty'] = diff
    context.user_data['create_step'] = 'explanation'
    await query.edit_message_text(
        "📝 <b>گام آخر — توضیح پاسخ</b>\n\n"
        "توضیح پاسخ صحیح را بنویسید.\n"
        "اگر توضیحی ندارید <code>-</code> بزنید:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ لغو", callback_data='questions:main')
        ]]))
    return CREATING_Q


async def _save_question(update, context):
    """Submit through the shared duplicate/lifecycle service only."""
    uid = update.effective_user.id
    await _do_insert_manual_question(update, context, context.user_data.get('new_q', {}), uid)


async def _h_ca_q_edit(query, context, uid: int, qid: str):
    """🐛 §W7 — ورود بازبین به ویرایشِ سؤال، در هر وضعیتی.

    از همان wizard چندمرحله‌ای «ساخت سؤال» استفاده می‌شود تا سیستمِ
    دومی ساخته نشود؛ فقط مقصدِ ذخیره فرق می‌کند (`edit_pending` به‌جای
    `create_question`). مقادیرِ فعلی پیش‌فرض می‌شوند تا بازبین مجبور
    نباشد همه‌چیز را دوباره بنویسد.
    """
    if not await db.has_permission(uid, 'questions.edit'):
        await query.answer("مجوز ویرایش سؤال را ندارید.", show_alert=True); return
    q = await db.get_question_by_id(qid)
    if not q:
        await query.answer("سؤال پیدا نشد.", show_alert=True); return
    scope = await db.get_scoped_intake(uid)
    if scope and (q.get('intake') or '') != scope:
        await query.answer("این سؤال خارج از scope شماست.", show_alert=True); return

    context.user_data['reviewer_editing_id'] = qid
    context.user_data['new_q'] = {
        'lesson_id': q.get('lesson_id'), 'topic_id': q.get('topic_id'),
        'lesson': q.get('lesson', ''), 'topic': q.get('topic', ''),
    }
    context.user_data['mode'] = 'creating_question'
    context.user_data['create_step'] = 'question'
    status_key = canonical_status(q)
    warn = ""
    if status_key == 'approved':
        warn = ("\n\n⚠️ این سؤال هم‌اکنون <b>تأییدشده</b> است. اگر متن، گزینه‌ها "
                "یا پاسخِ صحیح را عوض کنی، برای تأیید مجدد به صف بررسی برمی‌گردد.")
    await query.edit_message_text(
        f"📝 <b>ویرایش سؤال</b>\n\n<i>متن فعلی:</i>\n{_h(q.get('question',''))}{warn}\n\n"
        "گام ۱ — متن جدید سؤال را بفرست:", parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([_back("❌ لغو", f"questions:ca_q_view:{qid}")]))


async def _do_insert_manual_question(update, context, q: dict, uid: int):
    creator_user = await db.get_user(uid) or {}; actor = {'id': uid, '_db': creator_user}
    can_review = await db.has_permission(uid, 'questions.review')
    editing_id = context.user_data.get('editing_question_id')
    reviewer_edit_id = context.user_data.get('reviewer_editing_id')
    try:
        payload = {**q, 'correct_answer': q.get('correct', q.get('correct_answer', 0))}
        if reviewer_edit_id:
            # §W7 — ویرایشِ بازبین. لایه‌ی دامنه تصمیم می‌گیرد که تغییر
            # «محتوایی» است یا نه، و در صورت لزوم سؤال را به صف برمی‌گرداند.
            document = await question_bank.edit_pending(
                question_id=reviewer_edit_id, reviewer=actor, payload=payload,
                allow_probable_duplicate=bool(context.user_data.get('allow_probable_duplicate')))
        elif editing_id:
            document = await question_bank.update_contribution(
                question_id=editing_id, user=actor, payload=payload, resubmit=True)
        else:
            scoped = await db.get_scoped_intake(uid) if can_review else None
            # 🐛 §W6-1 — ادمینِ محتوا (دارنده‌ی `questions.review`) سؤالش
            # مستقیم ثبت می‌شود. پیش‌تر اینجا همیشه `auto_approve=False`
            # بود، پس سؤالِ خودِ ادمین هم به صف می‌رفت و چون خودتأییدی
            # ممنوع است، در نصبِ تک‌ادمینه برای همیشه در `pending`
            # می‌ماند. اعتماد در لایه‌ی دامنه دوباره با RBAC سنجیده
            # می‌شود، پس این پرچم به‌تنهایی چیزی را دور نمی‌زند.
            result = await question_bank.create_question(
                actor=actor, payload=payload,
                source='admin_bot' if can_review else 'student_bot',
                creator_type='admin' if can_review else 'student',
                auto_approve=can_review,
                intake=scoped if scoped is not None else creator_user.get('intake',''),
                allow_probable_duplicate=bool(context.user_data.get('allow_probable_duplicate')))
            document = result['question']
    except QuestionDomainError as exc:
        target = update.callback_query if getattr(update, 'callback_query', None) else None
        if exc.code == 'probable_duplicate' and not editing_id:
            probable = ((exc.details or {}).get('probable') or [{}])[0]
            similar = escape(str(probable.get('question') or 'سؤال مشابه'))
            ratio = int(float(probable.get('ratio') or 0) * 100)
            msg = (f"⚠️ <b>سؤال مشابه پیدا شد</b> ({ratio}٪)\n\n<i>{similar}</i>\n\n"
                   "اگر مطمئنی محتوای سؤال متفاوت است، ثبت را تأیید کن.")
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ ثبت با وجود شباهت", callback_data='questions:dup_confirm')],
                [InlineKeyboardButton("❌ لغو", callback_data='questions:dup_cancel')]])
            if target: await target.edit_message_text(msg, parse_mode='HTML', reply_markup=markup)
            else: await update.message.reply_text(msg, parse_mode='HTML', reply_markup=markup)
            return
        msg = f"⚠️ {escape(exc.message)}"
        if target: await target.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([_back("🔙 بانک سؤال", "questions:main")]))
        else: await update.message.reply_text(msg)
        return
    for key in ['new_q','create_step','mode','cr_lesson','creating_as_ca','editing_question_id','reviewer_editing_id','allow_probable_duplicate']:
        context.user_data.pop(key, None)
    status = document.get('status')
    message = ("✅ سؤال ثبت و در بانک منتشر شد." if status == 'approved' else
               "✅ سؤال برای بررسی ارسال شد. وضعیت آن را از «سؤال‌های من» دنبال کن.")
    markup = InlineKeyboardMarkup([_back("📚 سؤال‌های من", "questions:my_questions"),
                                   _back("🔙 بانک سؤال", "questions:main")])
    if getattr(update, 'message', None):
        await update.message.reply_text(message, reply_markup=markup)
    else:
        await update.callback_query.edit_message_text(message, reply_markup=markup)


# ══════════════════════════════════════════════════════════
#  مدیریت سوالات توسط ادمین محتوا
# ══════════════════════════════════════════════════════════

async def _ca_question_list(query, uid: int, context):
    """لیست سوالات با قابلیت فیلتر — برای ادمین محتوا و ادمین"""
    if not (await db.has_permission(uid, 'questions.review') or await db.has_permission(uid, 'questions.review_scoped')):
        await query.answer("❌ مجوز بررسی سؤال را ندارید.", show_alert=True)
        return

    # فیلترها
    f_status = context.user_data.get('caq_filter_status', 'all')  # all/approved/pending
    f_source = context.user_data.get('caq_filter_source', 'all')  # all/bot/student

    # ساخت query
    q_filter = {}
    from question_bank.contracts import status_query, canonical_status
    if f_status in ('approved', 'pending', 'rejected', 'needs_changes'):
        q_filter = status_query(f_status)

    if f_source == 'bot':
        q_filter['source'] = 'admin_bot'
    elif f_source == 'student':
        q_filter['creator_type'] = 'student'
    elif f_source == 'ai':
        q_filter['source'] = 'ai_student'

    # 🌊 موج C1 — فیلتر scope ورودی (Backend-Enforced):
    # scoped → دقیقاً scope خودش؛ ادمین ارشد → context انتخاب‌شده در پنل؛
    # مالک بدون context → رفتار قدیمی (نمایش همه) حفظ می‌شود.
    _intake_note = None
    try:
        _qscope = await question_bank.permissions.review_scope({'id': uid})
    except QuestionDomainError:
        await query.answer("مجوز یا scope بررسی سؤال کامل نیست.", show_alert=True)
        return
    if _qscope['kind'] == 'scoped':
        q_filter['intake'] = _qscope.get('intake') or ''
        _intake_note = q_filter['intake']
    elif uid != ADMIN_ID:
        _ctx_i = context.user_data.get('ca_intake')
        if _ctx_i is not None:
            q_filter['intake'] = _ctx_i
            _intake_note = _ctx_i

    from question_bank.contracts import and_query
    total = await db.questions.count_documents(q_filter)
    approved = await db.questions.count_documents(and_query(q_filter, status_query('approved')))
    pending = await db.questions.count_documents(and_query(q_filter, status_query('pending')))
    by_bot_c = await db.questions.count_documents(and_query(q_filter, {'source': 'admin_bot'}))
    by_stu_c = await db.questions.count_documents(and_query(q_filter, {'creator_type': 'student'}))
    page = max(0, int(context.user_data.get('caq_page', 0) or 0)); page_size = 15
    if page * page_size >= total and total:
        page = max(0, (total - 1) // page_size); context.user_data['caq_page'] = page
    questions = await db.questions.find(q_filter).sort('created_at', -1).skip(page * page_size).limit(page_size).to_list(page_size)

    # دکمه‌های فیلتر
    status_labels = {
        'all':      f"{'✅' if f_status=='all' else '⬜'} همه",
        'approved': f"{'✅' if f_status=='approved' else '⬜'} تأییدشده",
        'pending':  f"{'✅' if f_status=='pending' else '⬜'} در انتظار",
    }
    source_labels = {
        'all':     f"{'✅' if f_source=='all' else '⬜'} همه منابع",
        'bot':     f"{'✅' if f_source=='bot' else '⬜'} توسط بات",
        'student': f"{'✅' if f_source=='student' else '⬜'} توسط دانشجو",
        'ai':      f"{'✅' if f_source=='ai' else '⬜'} توسط هوشیار",
    }

    keyboard = [
        [
            InlineKeyboardButton(status_labels['all'],      callback_data='questions:ca_q_filter:status:all'),
            InlineKeyboardButton(status_labels['approved'], callback_data='questions:ca_q_filter:status:approved'),
            InlineKeyboardButton(status_labels['pending'],  callback_data='questions:ca_q_filter:status:pending'),
        ],
        [
            InlineKeyboardButton(source_labels['all'],     callback_data='questions:ca_q_filter:source:all'),
            InlineKeyboardButton(source_labels['bot'],     callback_data='questions:ca_q_filter:source:bot'),
            InlineKeyboardButton(source_labels['student'], callback_data='questions:ca_q_filter:source:student'),
        ],
        [
            InlineKeyboardButton(source_labels['ai'], callback_data='questions:ca_q_filter:source:ai'),
        ],
    ]

    # لیست سوالات (حداکثر ۱۵ تا)
    for q in questions[:15]:
        qid     = str(q['_id'])
        status_map = {'approved':'✅','pending':'⏳','rejected':'❌','needs_changes':'✏️'}
        status = status_map.get(canonical_status(q), '⏳')
        source  = "🧠" if q.get('source') == 'ai_student' else ("🤖" if q.get('source') == 'admin_bot' else "✏️")
        creator = q.get('creator_name', '') or ''
        lesson  = q.get('lesson', '')
        text_q  = q.get('question', '')[:30]
        creator_tag = f" | {creator}" if (creator and q.get('source') != 'admin_bot' and q.get('source') != 'ai_student') else ''
        keyboard.append([InlineKeyboardButton(
            f"{status}{source} {text_q} | {lesson}{creator_tag}",
            callback_data=f'questions:ca_q_view:{qid}'
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("قبلی", callback_data=f'questions:ca_q_page:{page-1}'))
    if (page + 1) * page_size < total:
        nav.append(InlineKeyboardButton("بعدی", callback_data=f'questions:ca_q_page:{page+1}'))
    if nav:
        keyboard.append(nav)
    back_cb = 'ca:main' if uid != int(__import__('os').getenv('ADMIN_ID', '0')) else 'admin:main'
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=back_cb)])

    # 🌊 C1 — نمایش label ورودی فعال در هدر (اگر فیلتر scope فعال است)
    if _intake_note is not None:
        from content_admin import _intake_label as _ilabel
        _scope_line = f"📅 ورودی: <b>{await _ilabel(_intake_note)}</b>\n"
    else:
        _scope_line = ""
    header = (
        f"🧪 <b>مدیریت سوالات</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{_scope_line}"
        f"📊 مجموع: <b>{total}</b>  ✅ تأیید: <b>{approved}</b>  ⏳ انتظار: <b>{pending}</b> · صفحه {page + 1}\n"
        f"🤖 توسط بات: <b>{by_bot_c}</b>  ✏️ توسط دانشجو: <b>{by_stu_c}</b>\n\n"
        f"<i>روی هر سوال بزنید برای مشاهده و مدیریت</i>"
    )

    try:
        await query.edit_message_text(
            header, parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception:
        pass


async def _ca_question_view(query, uid: int, qid: str):
    """نمایش کامل یک سوال با دکمه‌های مدیریت"""
    if not (await db.has_permission(uid, 'questions.review') or await db.has_permission(uid, 'questions.review_scoped')):
        await query.answer("❌ مجوز بررسی سؤال را ندارید.", show_alert=True)
        return

    q = await db.get_question_by_id(qid)
    if not q:
        await query.answer("❌ سوال پیدا نشد!", show_alert=True)
        return

    # Scope نمایش همان contract mutation است؛ content scope جداگانه نیست.
    try:
        scope = await question_bank.permissions.review_scope({'id': uid})
        if scope['kind'] == 'scoped' and (q.get('intake') or '') != scope['intake']:
            raise QuestionDomainError('question_out_of_scope', 'سؤال خارج از scope شماست', 403)
    except QuestionDomainError as exc:
        await query.answer(f"⛔ {exc.message}", show_alert=True)
        return

    opts    = q.get('options', [])
    ltrs    = ['الف', 'ب', 'ج', 'د']
    ca_idx  = q.get('correct_answer', 0)
    opts_text = '\n'.join(
        f"  {'✅' if i == ca_idx else '▪️'} {ltrs[i]}) {_h(opt)}"
        for i, opt in enumerate(opts[:4])
    )

    diff_map = {'آسان 🟢': '🟢 آسان', 'متوسط 🟡': '🟡 متوسط', 'سخت 🔴': '🔴 سخت'}
    diff_txt = diff_map.get(q.get('difficulty', ''), q.get('difficulty', ''))

    status_key = canonical_status(q)
    status = {'approved':'✅ تأیید شده','pending':'⏳ در انتظار تأیید','rejected':'❌ رد شده','needs_changes':'✏️ نیازمند اصلاح'}.get(status_key, status_key)

    # تگ طراح
    if q.get('source') == 'ai_student':
        creator_line = "🧠 <b>طراح:</b> هوشیار (پیشنهاد شخصیِ بررسی‌شده)"
    elif q.get('source') == 'admin_bot':
        creator_line = "🤖 <b>طراح:</b> ادمین محتوا (بات)"
    elif q.get('creator_name'):
        creator_line = f"✏️ <b>طراح:</b> {_h(q['creator_name'])}"
    else:
        creator_line = "✏️ <b>طراح:</b> نامشخص"

    text = (
        f"🧪 <b>مشاهده سوال</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📚 {_h(q.get('lesson',''))} — {_h(q.get('topic',''))}\n"
        f"📊 {diff_txt}  |  {status}\n"
        f"{creator_line}\n"
        f"📅 {fmt_jalali_dt(q.get('created_at',''), with_time=False)}\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"❓ <b>{_h(q.get('question',''))}</b>\n\n"
        f"{opts_text}\n\n"
        f"📝 <b>توضیح:</b> {_h(q.get('explanation','') or '—')}\n\n"
        f"📈 آمار: {q.get('attempt_count',0)} بار — {q.get('correct_count',0)} صحیح"
    )

    keyboard = []

    # دکمه‌های mutation دقیقاً مطابق permission contract مشترک.
    #
    # 🐛 §W6-2 — پیش‌تر وقتی بازبین خودش سازنده‌ی سؤال بود، دکمه‌ی «تأیید»
    # بی‌هیچ توضیحی حذف می‌شد ولی «رد با دلیل» می‌ماند. کاربر صفحه‌ای
    # می‌دید که راهی برای تأیید نداشت و نمی‌فهمید چرا. حالا به‌جای حذفِ
    # خاموش، علت نمایش داده می‌شود.
    if status_key == 'pending':
        is_own = int(q.get('creator_id') or 0) == uid
        if not is_own:
            keyboard.append([InlineKeyboardButton("✅ تأیید", callback_data=f'questions:ca_q_approve:{qid}')])
        else:
            text += ("\n\n<i>ℹ️ این سؤال را خودت ثبت کرده‌ای، پس تأییدش "
                     "باید توسط بازبین دیگری انجام شود.</i>")
        if await db.has_permission(uid, 'questions.reject'):
            keyboard.append([
                InlineKeyboardButton("✏️ نیازمند اصلاح", callback_data=f'questions:ca_q_needs_changes:{qid}'),
                InlineKeyboardButton("❌ رد با دلیل", callback_data=f'questions:ca_q_del:{qid}'),
            ])

    # 🐛 §W7 — ویرایش در هر وضعیتی.
    #
    # پیش‌تر صفحه‌ی سؤالِ «تأییدشده» هیچ دکمه‌ای جز «بازگشت» نداشت: نه
    # ویرایش (چون فقط pending قابلِ ویرایش بود)، نه حذف (قفلِ approved).
    # عملاً بن‌بست بود. حالا ویرایش همیشه در دسترس است و لایه‌ی دامنه
    # تصمیم می‌گیرد که آیا تغییر «محتوایی» است و باید به صف برگردد.
    if await db.has_permission(uid, 'questions.edit'):
        keyboard.append([InlineKeyboardButton(
            "📝 ویرایش سؤال", callback_data=f'questions:ca_q_edit:{qid}')])
        if status_key == 'approved':
            text += ("\n\n<i>ℹ️ ویرایشِ متن، گزینه‌ها یا پاسخِ صحیح، سؤال را "
                     "برای تأیید مجدد به صف بررسی برمی‌گرداند. تغییرِ سطحِ سختی "
                     "یا توضیح، وضعیت را عوض نمی‌کند.</i>")

    if status_key == 'approved':
        # مسیرِ خروج از «تأییدشده» در دامنه وجود داشت (approved → rejected)
        # ولی هیچ دکمه‌ای نشانش نمی‌داد. حذفِ مستقیم عمداً ممنوع می‌ماند،
        # چون سؤال ممکن است در آزمون‌های ثبت‌شده ارجاع داشته باشد.
        if await db.has_permission(uid, 'questions.reject'):
            keyboard.append([InlineKeyboardButton(
                "🚫 خروج از بانک (رد با دلیل)", callback_data=f'questions:ca_q_del:{qid}')])

    # 🛡 §۸۴ — حذف سخت در هر وضعیتی جز «تأییدشده» (که قفل است).
    if status_key != 'approved' and await db.has_permission(uid, 'questions.delete'):
        keyboard.append([InlineKeyboardButton(
            "🗑 حذف همیشگی", callback_data=f'questions:ca_q_purge:{qid}')])

    keyboard.append([InlineKeyboardButton("🔙 بازگشت به لیست", callback_data='questions:ca_q_list')])

    try:
        await query.edit_message_text(
            text, parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception:
        pass
