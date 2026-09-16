"""
📊 سیستم نمرات
  ✅ ثبت دسته‌ای با اسم دانشجو (نه یکی‌یکی)
  ✅ درس‌ها از همون لیست دروس موجود در دیتابیس (bs_lessons) — چیز جدیدی تعریف نمی‌شود
  ✅ نقش «نماینده‌ی ورودی» فقط می‌تواند برای دانشجویان همان ورودی ثبت کند
  ✅ نوتیف فوری به هر دانشجو بعد از ثبت نمره
"""
import os
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db
from utils import fmt_jalali_dt, safe_send, send_audit_log
from time_utils import today_tehran

logger = logging.getLogger(__name__)
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))


async def _get_intake_scope(uid: int):
    """Scope مشترک RBAC برای Bot grades؛ None فقط یعنی دسترسی global."""
    if uid == ADMIN_ID or await db.has_permission(uid, 'grades.manage'):
        return None
    if await db.has_permission(uid, 'grades.scoped'):
        scope = await db.get_scoped_intake(uid)
        return scope or '__no_access__'
    return '__no_access__'


# ══════════════════════════════════════════════════
#  مرحله ۱: انتخاب درس
# ══════════════════════════════════════════════════

async def _start_new_grade(query, context):
    scope = await _get_intake_scope(query.from_user.id)
    if scope == '__no_access__':
        await query.answer("❌ دسترسی ندارید.", show_alert=True)
        return
    context.user_data['grade_intake_scope'] = scope

    lessons = await db.get_lessons()
    if not lessons:
        await query.answer("❌ هنوز هیچ درسی توی دیتابیس تعریف نشده.", show_alert=True)
        return
    context.user_data['grades_lesson_options'] = lessons
    keyboard = [[InlineKeyboardButton(l, callback_data=f'grades:lesson_pick:{i}')] for i, l in enumerate(lessons)]
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='admin:main')])
    scope_txt = f"\nمحدود به ورودی: <b>{scope}</b>" if scope else ""
    await query.edit_message_text(
        f"📊 <b>ثبت نمره‌ی جدید</b>\n━━━━━━━━━━━━━━━━\n\nاول درس رو انتخاب کن:{scope_txt}",
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _pick_lesson(query, context, idx: int):
    lessons = context.user_data.get('grades_lesson_options', [])
    if idx >= len(lessons):
        await query.answer("❌ منقضی شد، دوباره از اول شروع کن.", show_alert=True)
        return
    context.user_data['grade_lesson'] = lessons[idx]
    # 🛡 §۸۲-ج — طبقه‌بندی ترمی: ترم الزامی و هر ترم جدا؛ ادمین باید صریح انتخاب کند
    # سعی می‌کنیم ترمِ پیشنهادی از روی درس را پیدا کنیم و برجسته کنیم، ولی «بدون ترم» ممنوع است.
    suggested = ""
    try:
        suggested = await db.lesson_term(lessons[idx])
    except Exception:
        suggested = ""
    suggested = (suggested or "").strip()
    from grade_utils import TERM_ORDER
    # گزینه‌های ترم: همان ترتیبِ برنامه‌ی درسی + پیشنهادی هم برجسته
    keyboard = []
    row = []
    for t in TERM_ORDER:
        label = f"✅ {t}" if t == suggested else t
        row.append(InlineKeyboardButton(label, callback_data=f'grades:term_pick:{TERM_ORDER.index(t)}'))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    if suggested and suggested not in TERM_ORDER:
        keyboard.append([InlineKeyboardButton(f"✅ {suggested} (پیشنهادی)", callback_data=f'grades:term_pick_raw:{suggested}')])
    keyboard.append([InlineKeyboardButton("❌ لغو", callback_data='admin:main')])
    hint = f"\n🎓 ترم پیشنهادی: <b>{suggested}</b> — تایید یا ترم دیگر را انتخاب کن" if suggested else "\n⚠️ ترم این درس در فهرست نیست — لطفاً ترم را دستی انتخاب کن"
    await query.edit_message_text(
        f"📚 درس: <b>{lessons[idx]}</b>{hint}\n\n"
        "🎓 <b>ترم را انتخاب کن</b> (هر ترم نمراتش جدا ذخیره می‌شود):",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _pick_term(query, context, idx: int, raw: str | None = None):
    from grade_utils import TERM_ORDER
    term = raw if raw is not None else (TERM_ORDER[idx] if 0 <= idx < len(TERM_ORDER) else "")
    term = (term or "").strip()
    if not term:
        await query.answer("❌ ترم نامعتبر", show_alert=True)
        return
    context.user_data['grade_term'] = term
    context.user_data['mode'] = 'grades_exam_title'
    lesson = context.user_data.get('grade_lesson', '')
    await query.edit_message_text(
        f"📚 درس: <b>{lesson}</b>\n🎓 ترم: <b>{term}</b>\n\n"
        "حالا عنوان امتحان رو بنویس (مثلاً «میان‌ترم» یا «پایان‌ترم بهمن ۱۴۰۳»):",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data='admin:main')]])
    )


async def handle_exam_title_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    if not title:
        await update.message.reply_text("❌ عنوان نمی‌تواند خالی باشد.")
        return
    context.user_data['grade_exam_title'] = title
    context.user_data['mode'] = 'grades_bulk_list'
    scope = context.user_data.get('grade_intake_scope')
    scope_txt = f"\n\n⚠️ فقط دانشجویان ورودی <b>{scope}</b> پیدا می‌شوند." if scope else ""
    await update.message.reply_text(
        "📋 <b>لیست نمرات رو بفرست</b>\n\n"
        "هر خط یک نفر، به این فرم:\n"
        "<code>نام دانشجو: نمره</code>\n\n"
        "مثال:\n<code>علی رضایی: 18.5\nسارا محمدی: 15\nحسین کریمی: 12.75</code>"
        f"{scope_txt}",
        parse_mode='HTML'
    )


# ══════════════════════════════════════════════════
#  مرحله ۲: پارس لیست + تطبیق نام + پیش‌نمایش تأیید
# ══════════════════════════════════════════════════

async def handle_bulk_list_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text
    scope = context.user_data.get('grade_intake_scope')
    lesson = context.user_data.get('grade_lesson')
    exam_title = context.user_data.get('grade_exam_title')
    if not lesson or not exam_title:
        await update.message.reply_text("❌ چیزی گم شده، دوباره از «📊 ثبت نمره‌ی جدید» شروع کن.")
        return

    term = context.user_data.get('grade_term') or ""
    if not term:
        try:
            term = await db.lesson_term(lesson)
        except Exception:
            term = ""
        term = (term or "").strip()
        if not term:
            await update.message.reply_text("❌ ترم گم شده — لطفاً از «📊 ثبت نمره‌ی جدید» دوباره شروع کن و ترم را انتخاب کن.")
            return
        context.user_data['grade_term'] = term
    matched, not_found, ambiguous = [], [], []
    for line in raw.splitlines():
        line = line.strip()
        if not line or ':' not in line:
            continue
        name_part, score_part = line.rsplit(':', 1)
        name = name_part.strip()
        try:
            score = float(score_part.strip())
        except ValueError:
            not_found.append(f"{name} (نمره نامعتبر: «{score_part.strip()}»)")
            continue
        if not (0 <= score <= 20):
            not_found.append(f"{name} (نمره باید بین ۰ تا ۲۰ باشد: {score})")
            continue

        candidates = await db.find_students_by_name(name, intake=scope)
        if len(candidates) == 1:
            matched.append({'user_id': candidates[0]['user_id'], 'name': candidates[0].get('name', name), 'score': score})
        elif len(candidates) == 0:
            not_found.append(name)
        else:
            ambiguous.append(name)

    if not matched and not not_found and not ambiguous:
        await update.message.reply_text(
            "❌ هیچ خطی به فرم درست شناسایی نشد.\nهر خط باید مثل این باشد: <code>نام: نمره</code>",
            parse_mode='HTML'
        )
        return

    context.user_data.pop('mode', None)
    context.user_data['grade_matched'] = matched

    lines = [f"📊 <b>پیش‌نمایش ثبت نمره</b>\n📚 {lesson} — {exam_title}\n🎓 ترم: <b>{term}</b>\n━━━━━━━━━━━━━━━━"]
    if matched:
        lines.append(f"\n✅ <b>{len(matched)} نفر پیدا شد:</b>")
        for m in matched[:20]:
            lines.append(f"   • {m['name']}: {m['score']}")
        if len(matched) > 20:
            lines.append(f"   … و {len(matched)-20} نفر دیگر")
    if ambiguous:
        lines.append(f"\n⚠️ <b>{len(ambiguous)} نفر چند نتیجه داشتند (نادیده گرفته می‌شوند):</b>")
        lines.extend(f"   • {n}" for n in ambiguous[:10])
        lines.append("   (برای این‌ها از شماره دانشجویی/نام کامل‌تر دوباره بفرست)")
    if not_found:
        lines.append(f"\n❌ <b>{len(not_found)} نفر پیدا نشدند:</b>")
        lines.extend(f"   • {n}" for n in not_found[:10])

    if not matched:
        await update.message.reply_text("\n".join(lines), parse_mode='HTML')
        return

    keyboard = [
        [InlineKeyboardButton(f"✅ تأیید و ثبت {len(matched)} نفر", callback_data='grades:confirm')],
        [InlineKeyboardButton("❌ انصراف", callback_data='admin:main')],
    ]
    await update.message.reply_text("\n".join(lines), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def _confirm_and_save(query, context):
    matched = context.user_data.pop('grade_matched', [])
    lesson = context.user_data.pop('grade_lesson', None)
    exam_title = context.user_data.pop('grade_exam_title', None)
    term = context.user_data.pop('grade_term', None)
    context.user_data.pop('grade_intake_scope', None)
    context.user_data.pop('grades_lesson_options', None)
    if not matched or not lesson:
        await query.answer("❌ چیزی برای ثبت نبود.", show_alert=True)
        return

    exam_date = today_tehran().isoformat()
    scope = await _get_intake_scope(query.from_user.id)
    if scope == '__no_access__':
        await query.answer("❌ دسترسی نمرات شما منقضی یا حذف شده است.", show_alert=True)
        return
    entries = [{'user_id': m['user_id'], 'score': m['score']} for m in matched]
    if scope is not None:
        allowed = await db.users.distinct(
            'user_id', {'user_id': {'$in': [e['user_id'] for e in entries]},
                        'approved': True, 'intake': scope})
        if set(allowed) != {e['user_id'] for e in entries}:
            await query.answer("❌ یکی از دانشجویان دیگر در scope شما نیست.", show_alert=True)
            return
    if not term:
        try:
            term = await db.lesson_term(lesson)
        except Exception:
            term = ""
        term = (term or "").strip()
        if not term:
            await query.answer("❌ ترم الزامی است — دوباره تلاش کن", show_alert=True)
            return
    saved = await db.grade_bulk_upsert(entries, lesson, exam_title, exam_date, query.from_user.id, term=term)

    # 🔔 موج ۴.۹۰ — اینباکس مینی‌اپ (نمره → کارنامه) برای همه‌ی دانشجویان
    # 🧠 N2 — Deep Link: همان درس در کارنامه فلش می‌خورد
    from urllib.parse import quote as _gq
    await db.inbox_add_many([
        {'user_id': rec['student_id'], 'type': 'grade',
         'title': f"📊 نمره‌ات {'به‌روزرسانی شد' if rec.get('_is_update') else 'ثبت شد'}",
         'body': (f"📚 {lesson}\n🎓 {term}\n📝 {exam_title}\n🎯 نمره: {rec['score']}/20"),
         'link': '/grades?hl=' + _gq(str(lesson or ''))}
        for rec in saved if rec.get('student_id')
    ])

    sent = 0
    for rec in saved:
        verb = "به‌روزرسانی شد" if rec.get('_is_update') else "ثبت شد"
        ok = await safe_send(
            query.get_bot(), rec['student_id'],
            f"📊 <b>نمره‌ات {verb}!</b>\n\n"
            f"📚 درس: {lesson}\n🎓 ترم: {term}\n📝 امتحان: {exam_title}\n"
            f"🎯 نمره: <b>{rec['score']}/20</b>",
            parse_mode='HTML'
        )
        if ok:
            sent += 1

    await query.edit_message_text(
        f"✅ <b>{len(saved)} نمره برای {term} ثبت شد.</b>\nبه {sent} نفر نوتیف رفت.",
        parse_mode='HTML'
    )

    # FIX جدید: قبلاً ثبت نمره هیچ لاگی نداشت — چون مستقیم روی کارنامه‌ی
    # دانشجو اثر می‌ذاره، باید مثل بقیه‌ی عملیات حساس ثبت بشه
    actor = await db.get_user(query.from_user.id)
    actor_name = actor.get('name', 'ادمین/نماینده') if actor else 'ادمین/نماینده'
    actor_role = await db.get_actor_role_label(query.from_user.id)
    await send_audit_log(
        query.get_bot(), 'admin', actor_name, query.from_user.id,
        f"ثبت دسته‌جمعی نمره ({len(saved)} نفر) — {term}", module='Grades', severity='INFO',
        actor_role=actor_role, target_type='lesson', target_label=f"{lesson} — {exam_title} — {term}",
        tags=['ثبت_نمره']
    )


# ══════════════════════════════════════════════════
#  مرور نمرات ثبت‌شده (ادمین/نماینده)
# ══════════════════════════════════════════════════

_PAGE_SIZE = 10


async def _show_recent_grades(query, page: int):
    scope = await _get_intake_scope(query.from_user.id)
    if scope == '__no_access__':
        await query.answer("❌ دسترسی ندارید.", show_alert=True)
        return
    total = await db.grade_count_recent(intake=scope)
    items = await db.grade_list_recent(skip=page * _PAGE_SIZE, limit=_PAGE_SIZE, intake=scope)

    lines = [f"📋 <b>نمرات ثبت‌شده</b> ({total})\n━━━━━━━━━━━━━━━━"]
    if not items:
        lines.append("چیزی ثبت نشده.")
    for g in items:
        user = await db.get_user(g['student_id'])
        name = user.get('name', str(g['student_id'])) if user else str(g['student_id'])
        term_txt = f" [{g.get('term')}]" if g.get('term') else ""
        lines.append(f"• {name} — {g['lesson']}{term_txt} ({g['exam_title']}): <b>{g['score']}/20</b>")

    keyboard = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ قبلی", callback_data=f'grades:list:{page-1}'))
    if (page + 1) * _PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("بعدی ▶️", callback_data=f'grades:list:{page+1}'))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='admin:main')])
    await query.edit_message_text("\n".join(lines), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


# ══════════════════════════════════════════════════
#  نمای دانشجو — «📊 نمرات من»
# ══════════════════════════════════════════════════

async def show_my_grades_msg(update: Update):
    uid = update.effective_user.id
    text = await _build_my_grades_text(uid)
    await update.message.reply_text(text, parse_mode='HTML')


async def _build_my_grades_text(uid: int, term: str | None = None) -> str:
    """🛡 AUDIT-§۸۲ — کارنامه‌ی ترم‌به‌ترم.

    پیش‌تر همه‌ی نمره‌ها در یک لیست می‌آمدند و میانگینِ «کل» یعنی چیزی بین
    ترم ۱ تا ۴؛ با درس‌های متفاوتِ هر ترم این عدد گمراه‌کننده بود. حالا هر
    ترم بلوکِ خودش را دارد (میانگین جدا) و `term` در همین تابع، کارنامه را به
    یک ترم محدود می‌کند (پنل و API از همین مسیر استفاده می‌کنند).
    میانگین‌ها از `group_grades_by_term` می‌آیند — همان منطقِ
    `summarize_grades` (نمره‌ی تهی در مخرج نیست).
    """
    grades = await db.grade_list_for_student(uid, term=term)
    if not grades:
        return ("📊 هنوز هیچ نمره‌ای برات ثبت نشده." if not term
                else f"📊 برای «{term}» نمره‌ای ثبت نشده است.")
    from grade_utils import group_grades_by_term, summarize_grades

    lines = [f"📊 <b>نمرات من{' — ' + term if term else ''}</b>\n━━━━━━━━━━━━━━━━"]
    for grp in group_grades_by_term(grades):
        head = grp["label"]
        avg = grp["avg"]
        lines.append(f"\n🎓 <b>{head}</b> · {grp['total']} نمره"
                     + (f" · میانگین <b>{avg}/20</b>" if avg is not None else ""))
        for g in grp["grades"]:
            lines.append(f"   📚 {g.get('lesson') or '—'} — {g.get('exam_title') or '—'}"
                         f"\n      🎯 <b>{g.get('score') if g.get('score') is not None else '—'}/20</b>"
                         f"  |  {fmt_jalali_dt(g.get('exam_date',''), with_time=False)}")
    overall = summarize_grades(grades)
    if not term and overall["avg"] is not None:
        lines.append(f"\n━━━━━━━━━━━━━━━━\n📈 میانگین کل: <b>{overall['avg']}/20</b>"
                     f"  ({overall['graded_count']} نمره‌ی دارا از {overall['total']})")
    return "\n".join(lines)


# ══════════════════════════════════════════════════
#  callback اصلی
# ══════════════════════════════════════════════════

async def grades_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(':')
    action = parts[1] if len(parts) > 1 else 'new'

    if action == 'new':
        await _start_new_grade(query, context)
    elif action == 'lesson_pick':
        await _pick_lesson(query, context, int(parts[2]))
    elif action == 'term_pick':
        await _pick_term(query, context, int(parts[2]))
    elif action == 'term_pick_raw':
        # term string may contain spaces, join remainder
        raw_term = ':'.join(parts[2:])
        await _pick_term(query, context, -1, raw=raw_term)
    elif action == 'confirm':
        await _confirm_and_save(query, context)
    elif action == 'list':
        await _show_recent_grades(query, int(parts[2]))
    elif action == 'mine':
        # اگر کاربر از ترم خاص آمده باشد، parts[2] حاوی ترم است
        term_filter = ':'.join(parts[2:]) if len(parts) > 2 and parts[2] else None
        term_filter = term_filter.strip() if isinstance(term_filter, str) else None
        if term_filter == "":
            term_filter = None
        text = await _build_my_grades_text(query.from_user.id, term=term_filter)
        # تب‌های ترم: کارنامه‌ی ترم‌به‌ترم — هر ترم جدا با میانگین جدا
        try:
            terms = await db.grade_terms_of_student(query.from_user.id)
        except Exception:
            terms = []
        keyboard = []
        if terms:
            row = []
            for t in terms:
                row.append(InlineKeyboardButton(t, callback_data=f'grades:mine:{t}'))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
            if term_filter:
                keyboard.append([InlineKeyboardButton("📚 همه ترم‌ها", callback_data='grades:mine')])
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='dashboard:refresh')])
        try:
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            await query.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
