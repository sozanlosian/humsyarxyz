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
from datetime import timedelta
from bson import ObjectId
import motor.motor_asyncio
from time_utils import now_utc, parse_machine_datetime, utc_now_iso

# نام logger عمداً «database» نگه داشته شد تا کانال لاگ تغییر نکند
logger = logging.getLogger('database')



class DBRbac:


    async def get_content_admins(self):
        return await self.users.find(
            {'role': 'content_admin', 'approved': True}
        ).to_list(100)


    async def is_content_admin(self, uid: int) -> bool:
        if uid == int(os.getenv('ADMIN_ID', '0')):
            return True
        u = await self.get_user(uid)
        if u and u.get('role') in ('content_admin', 'admin'):
            return True
        # FIX جدید: نقش content_scoped (مدیر محتوای محدود به یک ورودی)
        # هم باید بتواند وارد پنل محتوا شود — فقط با محدودیت ورودی
        role_doc = await self.get_admin_role(uid)
        if role_doc and role_doc.get('role') == 'content_scoped':
            return True
        # 🛡 RBAC-W1 (افزایشی — مسیرهای بالا دست‌نخورده‌اند): نقش‌های
        # دیتابیس‌محور با مجوز content.* هم پنل محتوا را باز می‌کنند.
        return (
            await self.has_perm(uid, 'content.manage')
            or await self.has_perm(uid, 'content.scoped')
        )


    # ══════════════════════════════════════════════════
    #  مدیریت ورودی‌های دانشجویی
    # ══════════════════════════════════════════════════

    async def get_active_intakes(self) -> list:
        return await self.intakes.find(
            {'active': True}
        ).sort('created_at', -1).to_list(50)


    async def get_all_intakes(self) -> list:
        return await self.intakes.find({}).sort('created_at', -1).to_list(100)


    async def add_intake(self, code: str, label: str) -> bool:
        exists = await self.intakes.find_one({'code': code})
        if exists:
            return False
        await self.intakes.insert_one({
            'code':       code,
            'label':      label,
            'active':     True,
            'created_at': utc_now_iso(),
        })
        return True


    async def toggle_intake(self, code: str) -> bool:
        doc = await self.intakes.find_one({'code': code})
        if not doc:
            return False
        new_state = not doc.get('active', True)
        await self.intakes.update_one({'code': code}, {'$set': {'active': new_state}})
        return new_state


    async def delete_intake(self, code: str):
        await self.intakes.delete_one({'code': code})


    async def get_users_by_intake(self, intake_code: str) -> list:
        return await self.users.find(
            {'intake': intake_code, 'approved': True}
        ).to_list(500)


    async def intake_stats(self, intake_code: str) -> dict:
        users  = await self.get_users_by_intake(intake_code)
        total  = len(users)
        groups = {}
        for u in users:
            g = u.get('group', 'نامشخص')
            groups[g] = groups.get(g, 0) + 1
        return {'total': total, 'groups': groups, 'users': users}


    async def notif_users_by_intake(self, intake_code: str, ntype: str) -> list:
        users = await self.get_users_by_intake(intake_code)
        # 🧠 N1.2 — canonical با fallback به مقدار قدیمی ذخیره‌شده
        return [
            u for u in users
            if self.notif_pref_on(u.get('notification_settings', {}), ntype)
        ]


    # ══════════════════════════════════════════════════
    #  علوم پایه — درس‌ها
    # ══════════════════════════════════════════════════

    @staticmethod
    def _intake_q(intake):
        """🌊 C1 — ساخت فیلتر intake: None=بدون فیلتر (رفتار قدیمی)،
        str=دقیقاً همان scope، list=هرکدام (مسیر دانشجو: خودش+سراسری)."""
        if intake is None:
            return {}
        if isinstance(intake, (list, tuple, set)):
            return {'intake': {'$in': list(intake)}}
        return {'intake': intake or ''}


    # ══════════════════════════════════════════════════
    #  سطوح دسترسی چندگانه ادمین (admin_roles)
    #  جدا از users.role (student/content_admin) — مخصوص
    #  زیرمجموعه‌های ادمین ارشد: مدیر محتوا کلی/محدود، پشتیبان
    # ══════════════════════════════════════════════════

    # نقش‌های ممکن و برچسب فارسی‌شان
    ROLE_LABELS = {
        'support':        '🎫 پشتیبان (فقط تیکت)',
        # 🌊 موج C1 — rename برچسب‌ها (کلید نقش دست‌نخورده):
        # content_admin  = ادمین ارشد محتوا (همه ورودی‌ها + سراسری)
        # content_scoped = ادمین محتوای ورودی خاص (قفل‌شده روی scope_intake)
        'content_admin':  '🎓 ادمین ارشد محتوا',
        'content_scoped': '📅 ادمین محتوای ورودی خاص',
        'broadcaster':    '📢 مسئول اطلاعیه',
        'reviewer':       '🤓 خرخون (بررسی سؤال و گزارش)',
        'bot_admin':      '👮 ادمین ربات (نماینده)',            # FIX جدید
        'grade_rep':      '📊 نماینده ورودی (ثبت نمره)',        # FIX جدید
    }


    # ماتریس مجوزها برای هر نقش — استفاده در has_permission
    ROLE_PERMISSIONS = {
        'support':        {'tickets'},
        'content_admin':  {'content', 'questions_review'},
        'content_scoped': {'content_scoped', 'questions_review_scoped'},
        'broadcaster':    {'broadcast'},
        'reviewer':       {'reports_review', 'questions_review', 'questions_reject', 'questions_edit'},
        'bot_admin':      {'users', 'schedules', 'notifications', 'broadcast',
                           'questions_review', 'questions_reject', 'questions_edit'},
        'grade_rep':      {'grades_scoped'},                           # FIX جدید
    }


    async def add_admin_role(self, uid: int, role: str, added_by: int,
                              scope_intake: str = None) -> bool:
        """افزودن نقش فرعی ادمین — اگه از قبل نقشی داشت، آپدیت میشه"""
        if role not in self.ROLE_LABELS:
            return False
        await self.admin_roles.update_one(
            {'_id': uid},
            {'$set': {
                'role':         role,
                'scope_intake': scope_intake,
                'added_by':     added_by,
                'added_at':     utc_now_iso(),
            }},
            upsert=True
        )
        # 🛡 RBAC-W1 — آینه‌ی دوطرفه: کالکشن جدید هم هم‌زمان به‌روز
        # می‌شود تا هر دو مخزن قدیمی/جدید همیشه Sync بمانند (§۵).
        await self._add_role_key(uid, role, scope_intake)
        return True


    async def remove_admin_role(self, uid: int):
        # 🛡 RBAC-W1 — قبل از حذف، کلید نقش را می‌دانیم تا آینه را هم پاک کنیم
        doc = await self.get_admin_role(uid)
        await self.admin_roles.delete_one({'_id': uid})
        if doc and doc.get('role'):
            await self._remove_role_key(uid, doc['role'])


    async def get_admin_role(self, uid: int) -> dict:
        """نقش فرعی یک کاربر — None اگه نداشت"""
        return await self.admin_roles.find_one({'_id': uid})


    async def get_all_admin_roles(self) -> list:
        return await self.admin_roles.find({}).sort('added_at', -1).to_list(100)


    async def has_permission(self, uid: int, permission: str) -> bool:
        """
        چک کردن دسترسی — ADMIN_ID (مدیر ارشد) همیشه همه‌چیز دارد.
        بقیه بر اساس admin_roles چک می‌شوند.
        """
        if uid == int(os.getenv('ADMIN_ID', '0')):
            return True
        doc = await self.get_admin_role(uid)
        legacy_ok = False
        if doc:
            perms = self.ROLE_PERMISSIONS.get(doc.get('role', ''), set())
            legacy_ok = permission in perms
        # 🛡 RBAC-W1 — مسیر دیتابیس‌محور (مکمل مسیر قدیمی؛ هیچ
        # دسترسی قبلی کم نمی‌شود، فقط نقش‌های جدید هم پاس می‌شوند)
        if not legacy_ok:
            legacy_ok = await self.has_perm(uid, permission)
        return legacy_ok


    async def get_scoped_intake(self, uid: int) -> str:
        """
        اگه کاربر مدیر محتوای محدود به یک ورودی خاص باشد، کد آن
        ورودی را برمی‌گرداند، وگرنه None (یعنی دسترسی کامل/بدون محدودیت)
        🌊 موج C1: منبع دوم — دارندگان مجوز content.scoped که فقط در
        user_roles.scope_intake ثبت شده‌اند (داربست تک‌منبع RBAC).
        """
        if uid == int(os.getenv('ADMIN_ID', '0')):
            return None
        doc = await self.get_admin_role(uid)
        if doc and doc.get('scope_intake') and doc.get('role') in (
                'content_scoped', 'grade_rep'):
            return doc.get('scope_intake')
        # C1 — fallback: نقش دیتابیس‌محور با scope (میرور دوطرفه موجود،
        # ولی اگر user_roles جلوتر بود، scope از آنجا خوانده می‌شود)
        ur = await self.user_roles.find_one({'_id': uid})
        if ur and ur.get('scope_intake'):
            scope = ur.get('scope_intake')
            keys  = list(ur.get('roles') or [])
            if 'content_scoped' in keys or 'grade_rep' in keys:
                return scope
            # نقش سفارشی دارای مجوز scoped محتوا/نمرات
            if (await self.has_perm(uid, 'content.scoped')
                    or await self.has_perm(uid, 'grades.scoped')):
                return scope
        return None


    # ══════════════════════════════════════════════════
    #  🌊 موج C1 — متن (scope) محتوای ورودی‌محور
    #  قرارداد: intake='' یعنی «🌐 سراسری» (شامل داده legacy).
    #  لنگرهای scope فعال: bs_lessons / ref_subjects / questions
    #  فرزندان scope را از والد به ارث می‌برند (resolver زنجیره‌ای).
    # ══════════════════════════════════════════════════

    async def get_content_scope(self, uid: int) -> dict:
        """
        منبع واحد تصمیم scope محتوا (§۸ spec):
          {'kind':'global'}              → ادمین ارشد محتوا/مالک/ادمین
          {'kind':'scoped','intake': X}  → ادمین محتوای ورودی خاص
          None                           → کاربر عادی (دسترسی مدیریتی ندارد)
        ترتیب: global همیشه بر scoped غلبه دارد (Never-Narrow).
        """
        if uid == int(os.getenv('ADMIN_ID', '0')):
            return {'kind': 'global', 'intake': None}
        u = await self.get_user(uid)
        if u and u.get('role') in ('admin', 'content_admin'):
            return {'kind': 'global', 'intake': None}
        doc = await self.get_admin_role(uid)
        if doc and doc.get('role') == 'content_scoped' and doc.get('scope_intake'):
            return {'kind': 'scoped', 'intake': doc.get('scope_intake')}
        # RBAC دیتابیس‌محور
        if await self.has_perm(uid, 'content.manage'):
            return {'kind': 'global', 'intake': None}
        if await self.has_perm(uid, 'content.scoped'):
            scope = await self.get_scoped_intake(uid)
            if scope:
                return {'kind': 'scoped', 'intake': scope}
            # مجوز scoped بدون scope تنظیم‌شده ⇒ فقط مشاهده‌ی سراسری (🛡 C3.1:
            # از can_access_intake جواب False می‌گیرد؛ چیزی برای ویرایش ندارد)
            return {'kind': 'scoped', 'intake': ''}
        return None


    async def can_access_intake(self, uid: int, intake: str) -> bool:
        """enforce مدیریتی: آیا actor اجازه‌ی CRUD روی محتوای این intake را
        دارد؟ global → همه؛ scoped → فقط دقیقاً scope خودش.

        🛡 C3.1 — ادمین scoped که هنوز برایش ورودی تنظیم نشده، سطلِ «تنظیم‌
        نشده» ندارد: قبلاً «کد خالی == سراسری» با هم یکی گرفته می‌شدند و چنین
        حسابی عملاً روی هسته‌ی 🌐 سراسری WRITE داشت. اکنون مقایسه فقط وقتی
        انجام می‌شود که scope واقعاً تنظیم شده باشد؛ کاربرِ بدون scope محتوای
        سراسری را فقط‌خواندنی می‌بیند (مسیرهای مشاهده از
        get_content_scope/ITEM_VIEW_ACTIONS جدا از این گیت‌اند) و هیچ جایی
        نمی‌تواند بنویسد.
        """
        scope = await self.get_content_scope(uid)
        if not scope:
            return False
        if scope['kind'] == 'global':
            return True
        own = scope.get('intake') or ''
        if not own:
            return False
        return (intake or '') == own


    async def scoped_child_intake(self, uid: int, parent_intake: str):
        """🌊 موج C3 — «فرزند ورودی‌خاص»: ساخت آیتم جدید *زیر* یک والد.

        تک‌منبع تصمیم برای عملیاتی که والدش را تغییر نمی‌دهد بلکه فرزندِ
        scope‌دار تولید می‌کند (مثلاً جلسه‌ای که فقط متعلق به ورودی X است
        و زیر درسِ 🌐 سراسری آویزان شده). can_access_intake برای این کار
        کافی نیست: آن «اجازه‌ی CRUD روی خودِ والد» را می‌سنجد.

        خروجی (سه‌حالته — None با '' و با کد اشتباه نشود):
          ''    → فرزند عادی؛ scope را از والد به ارث می‌برد (رفتار قبلی)
          کد    → فرزند فقط برای آن ورودی (کلید سطل مقصد روی سند فرزند)
          None  → اجازه ندارد
        قواعد:
          • هر کس که روی خودِ والد writable است → '' (هیچ رفتاری عوض نمی‌شود)
          • scoped + والد سراسری ('') → کد scope خودش (اگر scope داشته باشد)
          • scoped + والد ورودی دیگر → None
          • global با والد سراسری → '' (او فرزندِ scope‌دار را با intake
            صریح خودش می‌سازد، نه با اجبارِ scope؛ رفتار قدیمی دست‌نخورده)
        """
        if await self.can_access_intake(uid, parent_intake or ''):
            return ''
        scope = await self.get_content_scope(uid)
        if not scope or scope.get('kind') != 'scoped':
            return None
        if (parent_intake or '') != '':
            return None
        own = scope.get('intake') or ''
        return own or None


    # ── resolverهای زنجیره‌ای intake (پیش‌فرض '' = سراسری) ──

    async def lesson_intake(self, lesson_id: str) -> str:
        try:
            d = await self.bs_lessons.find_one(
                {'_id': ObjectId(lesson_id)})
            return (d or {}).get('intake') or ''
        except Exception:
            return ''


    async def session_intake(self, session_id: str) -> str:
        s = await self.bs_get_session(session_id)
        if not s:
            return ''
        # 🍴 موج C2 — جلسه‌ی دارای فیلد intake صریح (fork) همان را برمی‌گرداند؛
        # جلسات قدیمی فیلد ندارند و از درس والد ارث می‌برند (رفتار C1).
        if 'intake' in s:
            return s.get('intake') or ''
        return await self.lesson_intake(s.get('lesson_id', ''))


    async def content_intake(self, content_id: str) -> str:
        c = await self.bs_get_content_item(content_id)
        if not c:
            return ''
        return await self.session_intake(c.get('session_id', ''))


    async def ref_subject_intake(self, subject_id: str) -> str:
        try:
            d = await self.ref_subjects.find_one(
                {'_id': ObjectId(subject_id)})
            return (d or {}).get('intake') or ''
        except Exception:
            return ''


    async def ref_book_intake(self, book_id: str) -> str:
        b = await self.ref_get_book(book_id)
        if not b:
            return ''
        # 🍴 موج C2 — کتاب fork فیلد intake صریح دارد؛ کتاب قدیمی از موضوع ارث می‌برد
        if 'intake' in b:
            return b.get('intake') or ''
        return await self.ref_subject_intake(b.get('subject_id', ''))


    async def ref_file_intake(self, file_id: str) -> str:
        f = await self.ref_get_file(file_id)
        if not f:
            return ''
        return await self.ref_book_intake(f.get('book_id', ''))


    async def question_intake(self, qid: str) -> str:
        q = await self.get_question_by_id(qid)
        return (q or {}).get('intake') or ''


    def student_intake_filter(self, user_intake: str):
        """لیست intakeهای قابل مشاهده برای دانشجو: ورودی خودش + سراسری.
        این تنها قرارداد خواندن سمت دانشجوست (Bot + API)."""
        return [user_intake or '', ''] if user_intake else ['']


    # ══════════════════════════════════════════════════
    #  🛡 RBAC دیتابیس‌محور — موج W1 (Execution Contract 🔒)
    #  تک‌منبع حقیقت: کالکشن‌های roles / user_roles / perm_catalog
    #  قوانین قفل (§۴ و §۶ قرارداد):
    #   • هیچ نقش/مجوز/برچسب/رنگ/آیکون جدیدی «در کد» ساخته نمی‌شود —
    #     دو ثابت زیر فقط بذر اولیه‌ی idempotent‌اند؛ پس از seed،
    #     خوانده/نوشته فقط از دیتابیس (تغییر دستی ادمین حفظ می‌شود).
    #   • Improve, Never Replace: admin_roles و users.role به‌عنوان
    #     mirror سازگاری دوطرفه زنده می‌مانند (§۱۰ سند).
    #   • ADMIN_ID (مالک) همیشه بای‌پس — تنها استثنای قرارداد §۸.
    # ══════════════════════════════════════════════════

    # دسته‌های مجوز (حفظ ترتیب نمایش در ماتریس مینی‌اپ)
    PERM_CATEGORIES = [
        ('users',         'کاربران'),
        ('roles',         'نقش‌ها'),
        ('content',       'محتوا'),
        ('questions',     'سؤالات'),
        ('schedules',     'برنامه و امتحان'),
        ('grades',        'نمرات'),
        ('tickets',       'تیکت'),
        ('reports',       'گزارش‌ها'),
        ('notifications', 'اعلان‌ها'),
        ('ai',            'هوشیار'),
        ('subscription',  'اشتراک'),
        ('stats',         'آمار'),
        ('prestige',      'پرستیژ'),
        ('settings',      'تنظیمات'),
        ('backup',        'بکاپ'),
        ('system',        'سیستم'),
        # 🛡 §۸۴ — 'ring' در PERMISSION_CATALOG استفاده می‌شد ولی برچسب
        # نداشت، پس سرتیترش در ماتریس مجوزها خام و انگلیسی می‌ماند.
        ('ring',          'رینگ استریت'),
    ]


    # کاتالوگ مجوزها — (key, برچسب فارسی, دسته)
    # هر سوییچ تکی است (§۶): هیچ گروه‌بندی منطقی در کد نیست.
    PERMISSION_CATALOG = [
        ('users.view',           'مشاهده‌ی کاربران',            'users'),
        ('users.manage',         'مدیریت کاربران',              'users'),
        ('users.suspend',        'تعلیق/رفع تعلیق کاربر',       'users'),
        ('users.delete',         'حذف/بلاک کاربر',              'users'),
        ('users.message',        'ارسال پیام به کاربر',         'users'),
        ('roles.manage',         'مدیریت نقش‌ها و مجوزها',      'roles'),
        ('content.manage',       'مدیریت محتوا (کلی)',          'content'),
        ('content.scoped',       'محتوای محدود به ورودی',       'content'),
        ('questions.review',     'بررسی سؤالات پیشنهادی',       'questions'),
        ('questions.review_scoped','بررسی سؤالات (ورودی خود)',  'questions'),
        ('questions.reject',     'رد/نیازمند اصلاح سؤال',       'questions'),
        ('questions.edit',       'ویرایش سؤال (هر وضعیت)',     'questions'),
        ('questions.delete',     'حذف دائمی سؤال',              'questions'),
        ('questions.import',     'درون‌ریزی بانک سؤال',         'questions'),
        ('schedules.manage',     'مدیریت برنامه و امتحان',      'schedules'),
        ('grades.manage',        'مدیریت نمرات (کلی)',          'grades'),
        ('grades.scoped',        'ثبت نمره (ورودی خود)',        'grades'),
        ('tickets.reply',        'پاسخ به تیکت',                'tickets'),
        ('tickets.manage',       'مدیریت وضعیت تیکت‌ها',        'tickets'),
        ('reports.review',       'بررسی گزارش سؤال/جزوه',       'reports'),
        ('notifications.manage', 'تنظیمات پیش‌فرض اعلان',       'notifications'),
        ('broadcast.send',       'ارسال همگانی/اطلاعیه',        'notifications'),
        ('ai.manage',            'مدیریت هوشیار',               'ai'),
        ('subscription.manage',  'مدیریت اشتراک‌ها',            'subscription'),
        ('stats.view',           'آمار و داشبورد مدیریتی',      'stats'),
        # 🌊 موج Analytics-Filters — گیت دومرحله‌ای تحلیل بازه‌ای (bundle)
        ('stats.deep',           'تحلیل عمیق بازه‌ای',           'stats'),
        ('ring.manage',          'مدیریت رینگ استریت',            'ring'),
        ('prestige.manage',      'تنظیمات پرستیژ',              'prestige'),
        ('settings.manage',      'تنظیمات سیستم',               'settings'),
        ('backup.manage',        'بکاپ و بازیابی',              'backup'),
        ('audit.view',           'مشاهده‌ی لاگ حساس',           'system'),
        # ↩️ §۸۸ — بازگردانی تغییر، اختیاری جدا از دیدنِ تاریخچه است.
        ('audit.undo',           'بازگردانی تغییرات ثبت‌شده',   'system'),
        ('system.manage',        'عملیات حساس سیستم',           'system'),
    ]


    # نگاشت مجوز قدیمی (ROLE_PERMISSIONS) → کلیدهای جدید — فقط برای بذر
    _LEGACY_PERM_MAP = {
        'tickets':                 ['tickets.reply', 'tickets.manage'],
        'content':                 ['content.manage'],
        'questions_review':        ['questions.review'],
        'questions_reject':        ['questions.reject'],
        'questions_edit':          ['questions.edit'],
        'questions_import':        ['questions.import'],
        'content_scoped':          ['content.scoped'],
        'questions_review_scoped': ['questions.review_scoped'],
        'broadcast':               ['broadcast.send'],
        'reports_review':          ['reports.review'],
        'users':                   ['users.view', 'users.manage'],
        'schedules':               ['schedules.manage'],
        'notifications':           ['notifications.manage'],
        'grades_scoped':           ['grades.scoped'],
        'grades':                  ['grades.manage'],
    }


    async def ensure_rbac_seed(self) -> dict:
        """بذر idempotent (§۱۰): اجرای دوباره هیچ چیز را بازنویسی نمی‌کند.

        roles با $setOnInsert ساخته می‌شوند ⇒ ویرایش دستی ادمین
        (نام/رنگ/مجوزها) در اجراهای بعدی سالم می‌ماند. نقش‌های سیستم
        با permsِ نگاشت‌یافته از ماتریس قدیمی — قفل رفتاری کامل."""
        now = utc_now_iso()

        # ۱) کاتالوگ مجوزها: فقط اگر کالکشن خالی است
        perms_seeded = 0
        catalog_was_empty = await self.perm_catalog.count_documents({}) == 0
        for key, label, cat in self.PERMISSION_CATALOG:
            await self.perm_catalog.update_one(
                {'_id': key},
                {'$setOnInsert': {
                    '_id': key, 'label': label, 'category': cat}},
                upsert=True,
            )
        if catalog_was_empty:
            perms_seeded = len(self.PERMISSION_CATALOG)

        # 🌊 موج Analytics-Filters — درج idempotent مجوز جدید حتی اگر بذرِ
        # اولیه قبلاً اجرا شده ($setOnInsert ⇒ هیچ ویرایش دستی پاک نمی‌شود)
        await self.perm_catalog.update_one(
            {'_id': 'stats.deep'},
            {'$setOnInsert': {'_id': 'stats.deep',
                              'label': 'تحلیل عمیق بازه‌ای',
                              'category': 'stats'}},
            upsert=True,
        )

        # ۲) نقش‌های سیستمی: upsertِ صرفاً-درج (ویرایش‌ها حفظ می‌شود)
        roles_before = await self.roles.count_documents({})
        for key, label in self.ROLE_LABELS.items():
            legacy_perms = self.ROLE_PERMISSIONS.get(key, set())
            perms = []
            for lp in legacy_perms:
                perms.extend(self._LEGACY_PERM_MAP.get(lp, [lp]))
            # یکتا و مرتب — بدون تکرار
            perms = sorted(set(perms))
            await self.roles.update_one(
                {'_id': key},
                {'$setOnInsert': {
                    '_id':        key,
                    'label':      label,
                    'desc':       '',
                    'icon':       label.split(' ')[0] if label else '🛡',
                    'color':      '#70A7FF',
                    'priority':   50,
                    'system':     True,   # حذف‌ناپذیر ولی قابل ویرایش
                    'active':     True,
                    'visible':    True,
                    'perms':      perms,
                    'created_at': now,
                    'updated_at': now,
                }},
                upsert=True,
            )
        # Question Bank v2 permission contract is mandatory for legacy system roles.
        # $addToSet is idempotent and does not replace any custom permissions.
        await self.roles.update_one({'_id': 'reviewer'}, {'$addToSet': {'perms': {'$each': [
            'questions.review', 'questions.reject', 'questions.edit', 'reports.review']}}})
        await self.roles.update_one({'_id': 'bot_admin'}, {'$addToSet': {'perms': {'$each': [
            'questions.review', 'questions.reject', 'questions.edit']}}})
        await self.roles.update_one({'_id': 'content_admin'}, {'$addToSet': {'perms': {'$each': [
            'questions.review', 'questions.reject', 'questions.edit']}}})
        await self.roles.update_one({'_id': 'content_scoped'}, {'$addToSet': {'perms': {'$each': [
            'questions.review_scoped', 'questions.reject', 'questions.edit']}}})
        # 💍 Ring Street — مجوز فیچر به نقش‌های مرتبط (idempotent، درست مثل
        # قرارداد Question Bank). این‌جا لازم است چون `ring_bootstrap` از
        # ensure_indexes *قبل* از ساخت نقش‌ها اجرا می‌شود.
        await self.roles.update_one({'_id': 'bot_admin'}, {'$addToSet': {'perms': 'ring.manage'}})
        await self.roles.update_one({'_id': 'reviewer'}, {'$addToSet': {'perms': 'ring.manage'}})
        roles_after = await self.roles.count_documents({})
        return {
            'roles_seeded': max(0, roles_after - roles_before),
            'perms_seeded': perms_seeded,
        }


    async def rbac_migrate_users(self) -> dict:
        """مهاجرت idempotent (§۱۰): admin_roles + users.role → user_roles.

        از addToSet-منطقی (dedup در پایتون) استفاده می‌کند ⇒ اجرای چندباره
        هیچ داده‌ای تکرار/بازنویسی نمی‌کند؛ هیچ نقشی حذف نمی‌شود."""
        count_ar = 0
        async for doc in self.admin_roles.find({}):
            role = doc.get('role')
            if not role:
                continue
            await self._add_role_key(
                doc['_id'], role, doc.get('scope_intake'))
            count_ar += 1

        count_ur = 0
        # 🛡 AUDIT-V4 — مهاجرت legacy نباید همه‌ی کاربران را یک‌جا در RAM
        # بگذارد؛ روی cursor پیمایش می‌کنیم (تعداد پردازش‌شده عیناً همان).
        legacy_cursor = self.users.find(
            {'role': {'$in': ['content_admin', 'support']}}
        ).batch_size(500)
        async for u in legacy_cursor:
            role_key = u.get('role')
            if role_key in ('content_admin', 'support'):
                await self._add_role_key(u['user_id'], role_key)
                count_ur += 1

        return {'from_admin_roles': count_ar, 'from_users_role': count_ur}


    # ══════════════════════════════════════════════════
    #  🌊 موج C1 — مهاجرت scope ورودی محتوا
    # ══════════════════════════════════════════════════

    async def migrate_content_intake_scope(self) -> dict:
        """مهاجرت Safe + Idempotent + Re-runnable (§۲۴ spec).

        ۱) backfill «intake:''» (= 🌐 سراسری/legacy) روی چهار لنگر
           محتوایی — فقط اسنادِ فاقد فیلد ($exists:false) ⇒ اجرای
           دوباره صفر نوشتاری و هیچ overrideای رخ نمی‌دهد. هیچ سندی
           حذف نمی‌شود و داده‌ی بدون scope orphan نمی‌شود ('' همان
           سطل نگه‌داری legacy است).
        ۲) rename شرطی label نقش‌های content_* در کالکشن roles — فقط
           اگر label هنوز یکی از برچسب‌های قدیمیِ شناخته‌شده باشد؛
           برچسب سفارشی‌شده‌ی دستی ادمین هرگز له نمی‌شود.
        ۳) وضعیت اجرا در کالکشن migrations ثبت می‌شود (قابل ردیابی).
        """
        now = utc_now_iso()
        backfilled = {}
        for name, col in [('bs_lessons', self.bs_lessons),
                          ('ref_subjects', self.ref_subjects),
                          ('questions', self.questions),
                          # QBank file metadata was introduced additively;
                          # existing documents (if any) inherit global scope.
                          ('qbank_files', self.qbank_files)]:
            r = await col.update_many(
                {'intake': {'$exists': False}},
                {'$set': {'intake': ''}},
            )
            backfilled[name] = r.modified_count

        # rename شرطی label — کلید نقش دست‌نخورده می‌ماند
        label_map = {
            'content_admin': {
                'olds': ['🎓 مدیر محتوا (کلی)', 'مدیر محتوا (کلی)',
                         'مدیر محتوا کلی', 'مدیر محتوا'],
                'new': self.ROLE_LABELS['content_admin'],
            },
            'content_scoped': {
                'olds': ['📅 مدیر محتوا (محدود به ورودی)',
                         '📅 مدیر محتوا (محدود)', 'مدیر محتوا (محدود به ورودی)'],
                'new': self.ROLE_LABELS['content_scoped'],
            },
        }
        labels_renamed = 0
        for key, cfg in label_map.items():
            r = await self.roles.update_one(
                {'_id': key, 'label': {'$in': cfg['olds']}},
                {'$set': {'label': cfg['new'],
                          'icon': cfg['new'].split(' ')[0],
                          'updated_at': now}},
            )
            labels_renamed += r.modified_count

        await self.migrations.update_one(
            {'_id': 'c1_content_intake_scope'},
            {'$set': {'backfilled': backfilled,
                      'labels_renamed': labels_renamed,
                      'last_run_at': now},
             '$setOnInsert': {'first_run_at': now}},
            upsert=True,
        )
        return {'backfilled': backfilled, 'labels_renamed': labels_renamed}


    # ──────────────────────────────────────────────────
    #  CRUD نقش‌ها
    # ──────────────────────────────────────────────────

    async def list_roles(self) -> list:
        """همه‌ی نقش‌ها — مرتب: priority ↑ سپس برچسب (منبع UI/API)."""
        docs = await self.roles.find({}).to_list(1000)   # 🛡 AUDIT-V4 کرانه
        return sorted(
            docs,
            key=lambda d: (d.get('priority', 99), d.get('label', '')),
        )


    async def rbac_restore_role(self, key: str, snapshot: dict = None) -> None:
        """Compensating restore used when mandatory RBAC audit persistence fails."""
        if snapshot is None:
            await self.roles.delete_many({'_id': key})
        else:
            await self.roles.replace_one({'_id': key}, snapshot, upsert=True)


    async def rbac_assignment_snapshot(self, uid: int) -> dict:
        user = await self.users.find_one({'user_id': uid}, {'role': 1})
        return {
            'user_roles': await self.user_roles.find_one({'_id': uid}),
            'admin_role': await self.admin_roles.find_one({'_id': uid}),
            'legacy_role_present': bool(user and 'role' in user),
            'legacy_role': (user or {}).get('role'),
        }


    async def rbac_restore_assignment(self, uid: int, snapshot: dict) -> None:
        """Restore canonical assignment and both legacy projections exactly."""
        for collection, key in ((self.user_roles, 'user_roles'),
                                (self.admin_roles, 'admin_role')):
            doc = snapshot.get(key)
            if doc is None:
                await collection.delete_many({'_id': uid})
            else:
                await collection.replace_one({'_id': uid}, doc, upsert=True)
        if snapshot.get('legacy_role_present'):
            await self.users.update_one({'user_id': uid},
                                        {'$set': {'role': snapshot.get('legacy_role')}})
        else:
            await self.users.update_one({'user_id': uid}, {'$unset': {'role': ''}})


    async def get_role(self, key: str):
        return await self.roles.find_one({'_id': key})


    async def role_label(self, key: str) -> str:
        """برچسب نقش: دیتابیس اول، fallback به لیست قدیمی (سازگاری)."""
        doc = await self.get_role(key)
        if doc and doc.get('label'):
            return doc['label']
        return self.ROLE_LABELS.get(key, key)


    async def _valid_perm_keys(self) -> set:
        docs = await self.perm_catalog.find({}).to_list(1000)   # 🛡 AUDIT-V4
        if not docs:
            return {k for k, _, _ in self.PERMISSION_CATALOG}
        return {d['_id'] for d in docs}


    async def create_role(self, payload: dict, actor: int = 0):
        """ساخت نقش دلخواه (§۶). خروجی: (doc, err)"""
        key = (payload.get('key') or '').strip()
        label = (payload.get('label') or '').strip()
        if not label or len(label) > 60:
            return None, 'label_invalid'
        if not key:
            key = f"custom_{int(now_utc().timestamp())}"
        if not key.isidentifier() or ' ' in key or len(key) > 40:
            return None, 'key_invalid'
        if await self.get_role(key):
            return None, 'key_exists'
        valid = await self._valid_perm_keys()
        perms = sorted({p for p in (payload.get('perms') or [])
                        if p in valid})
        now = utc_now_iso()
        doc = {
            '_id':        key,
            'label':      label,
            'desc':       (payload.get('desc') or '')[:200],
            # آیکون پیش‌فرض از خودِ برچسب (توکن اول اگر اموجی باشد)
            # — هم‌سو با منطق seed؛ در غیر این صورت 🛡
            'icon':       (payload.get('icon')
                           or label.split(' ')[0][:4] or '🛡')[:4],
            'color':      payload.get('color') or '#70A7FF',
            'priority':   int(payload.get('priority') or 90),
            'system':     False,
            'active':     True,
            'visible':    True,
            'perms':      perms,
            'created_at': now,
            'updated_at': now,
        }
        await self.roles.insert_one(doc)
        return doc, None


    _ROLE_EDITABLE = ('label', 'desc', 'icon', 'color',
                      'priority', 'active', 'visible', 'perms')


    async def update_role(self, key: str, changes: dict, actor: int = 0):
        """ویرایش نقش — فقط فیلدهای لیست‌سفید _ROLE_EDITABLE.
        label خالی ممنوع؛ perms فقط کلیدهای معتبر کاتالوگ."""
        old = await self.get_role(key)
        if not old:
            return None, 'not_found'
        valid = await self._valid_perm_keys()
        updates = {}
        for field in self._ROLE_EDITABLE:
            if field not in changes or changes[field] is None:
                continue
            val = changes[field]
            if field == 'label':
                val = str(val).strip()
                if not val or len(val) > 60:
                    return None, 'label_invalid'
            elif field == 'perms':
                val = sorted({p for p in val if p in valid})
            elif field == 'priority':
                val = max(1, min(999, int(val)))
            updates[field] = val
        if not updates:
            return old, None
        updates['updated_at'] = utc_now_iso()
        updates['updated_by'] = actor
        await self.roles.update_one({'_id': key}, {'$set': updates})
        return await self.get_role(key), None


    async def delete_role(self, key: str):
        """حذف نقش — گاردها (§۶): system و نقشِ دارای کاربر حذف‌ناپذیر."""
        role = await self.get_role(key)
        if not role:
            return False, 'not_found', 0
        if role.get('system'):
            return False, 'system_role', 0
        count = await self.user_roles.count_documents({'roles': key})
        if count:
            return False, 'in_use', count
        await self.roles.delete_many({'_id': key})
        return True, '', 0


    async def users_count_by_role(self) -> dict:
        rows = await self.user_roles.aggregate([
            {'$unwind': '$roles'},
            {'$group': {'_id': '$roles', 'count': {'$sum': 1}}},
        ]).to_list(500)          # 🛡 AUDIT-V4 — خروجی به تعداد نقش‌هاست
        return {str(row.get('_id')): int(row.get('count') or 0)
                for row in rows if row.get('_id')}


    async def user_ids_by_role(self, role: str, limit: int = 1000) -> list:
        """شناسه اعضای نقش از منبع RBAC، با mirrorهای میراثی.

        این entry point برای مصرف مشترک Bot/API است تا routeها مستقیماً
        کالکشن‌های نقش را نخوانند. خروجی deduplicate و به سقف محدود است.
        """
        role = (role or '').strip()
        if not role:
            return []
        limit = max(1, min(int(limit), 100000))
        ids = []
        docs = await self.user_roles.find(
            {'roles': role}, {'_id': 1}
        ).to_list(limit)
        ids.extend(int(d['_id']) for d in docs if d.get('_id') is not None)

        # mirrorهای legacy برای داده‌هایی که هنوز migration نشده‌اند.
        if role == 'content_admin':
            legacy_users = await self.users.find(
                {'role': 'content_admin'}, {'user_id': 1}
            ).to_list(limit)
            ids.extend(int(u['user_id']) for u in legacy_users
                       if u.get('user_id') is not None)
        legacy_roles = await self.admin_roles.find(
            {'role': role}, {'_id': 1}
        ).to_list(limit)
        ids.extend(int(d['_id']) for d in legacy_roles
                   if d.get('_id') is not None)
        return list(dict.fromkeys(ids))[:limit]


    # ──────────────────────────────────────────────────
    #  تخصیص نقش به کاربر (چندنقشی — Union مجوزها)
    # ──────────────────────────────────────────────────

    async def _add_role_key(self, uid: int, key: str,
                            scope_intake: str = None):
        doc = await self.user_roles.find_one({'_id': uid})
        roles = list((doc or {}).get('roles') or [])
        changed = key not in roles
        if changed:
            roles.append(key)
        updates = {'updated_at': utc_now_iso()}
        if changed:
            updates['roles'] = roles
        if scope_intake is not None:
            updates['scope_intake'] = scope_intake
        if changed or scope_intake is not None or not doc:
            await self.user_roles.update_one(
                {'_id': uid}, {'$set': updates}, upsert=True)
        # 🛡 RBAC-W3 — پروجکشن میراثی هم‌زمان (§۵)
        await self._sync_admin_role_projection(uid)
        return changed


    async def _remove_role_key(self, uid: int, key: str):
        doc = await self.user_roles.find_one({'_id': uid})
        roles = [r for r in ((doc or {}).get('roles') or [])
                 if r != key]
        await self.user_roles.update_one(
            {'_id': uid},
            {'$set': {'roles': roles,
                      'updated_at': utc_now_iso()}},
            upsert=True)
        # 🛡 RBAC-W3 — پروجکشن میراثی هم‌زمان (§۵)
        await self._sync_admin_role_projection(uid)
        return True


    async def get_user_roles(self, uid: int) -> dict:
        """نقش‌های کاربر: کلیدها + سندهای resolveشده + scope.

        نقش ناموجود (custom حذف‌شده) در خروجی نمی‌آید ولی کلیدش
        در keys باقی می‌ماند تا UI بتواند هشدار دهد."""
        doc = await self.user_roles.find_one({'_id': uid})
        keys = list((doc or {}).get('roles') or [])
        roles = []
        for key in keys:
            role = await self.get_role(key)
            if role:
                roles.append(role)
        return {
            'keys': keys,
            'roles': roles,
            'scope_intake': (doc or {}).get('scope_intake'),
        }


    async def get_users_roles_keys(self, uids: list) -> dict:
        """🗄 W4/PERF-01 — فقط کلیدهای نقش (بدون resolve) با یک کوئری."""
        ids = []
        for u in (uids or []):
            try:
                ids.append(int(u))
            except (TypeError, ValueError):
                continue
        out = {i: [] for i in ids}
        if not ids:
            return out
        async for doc in self.user_roles.find({'_id': {'$in': ids}}):
            try:
                out[int(doc['_id'])] = list(doc.get('roles') or [])
            except (TypeError, ValueError):
                continue
        return out


    async def get_user_perms(self, uid: int) -> set:
        """Union مجوزهای نقش‌های «فعال» — §۷ قرارداد (Multi Role).

        مالک همیشه کل کاتالوگ را دارد (تنها استثنا — §۸)."""
        valid = await self._valid_perm_keys()
        if uid == int(os.getenv('ADMIN_ID', '0')):
            return set(valid)
        perms = set()
        info = await self.get_user_roles(uid)
        # ⏳ §۸۶ — نقشِ سررسیدشده باید در همین لحظه‌ی تصمیم بی‌اثر باشد،
        # نه فقط وقتی کسی صفحه‌ی RBAC را باز کند. بدون این فیلتر،
        # «دسترسی دو ساعته» تا اولین بازدیدِ ادمین زنده می‌ماند.
        expiry = await self.role_expiry_map(uid)
        now_iso = utc_now_iso()
        for role in info['roles']:
            if not role.get('active', True):
                continue
            if self._expiry_passed(expiry.get(role.get('_id')), now_iso):
                continue
            perms.update(role.get('perms') or [])
        return perms & valid


    # ══════════════════════════════════════════════════════════
    #  ⏳ §۸۶ — دسترسی موقت (نقشِ خودمنقضی)
    # ══════════════════════════════════════════════════════════
    #  انگیزه: «این استاد فقط تا پایان ترم» یا «دسترسی اضطراری دو
    #  ساعته». بدون انقضای خودکار، ادمین باید دستی یادش بماند پس
    #  بگیرد — که نمی‌ماند، و دسترسی‌ها آرام‌آرام انباشته می‌شوند.
    #
    #  طراحی: انقضا در همان سند user_roles ذخیره می‌شود
    #  (`role_expiry: {<role_key>: <iso>}`) تا هیچ کالکشن جدیدی لازم
    #  نباشد و snapshot/restore موجود خودبه‌خود آن را پوشش دهد.

    async def set_role_expiry(self, uid: int, key: str, expires_at) -> None:
        """زمان انقضا را روی یک نقشِ تخصیص‌یافته می‌گذارد یا برمی‌دارد."""
        field = f'role_expiry.{key}'
        if expires_at is None:
            await self.user_roles.update_one(
                {'_id': int(uid)}, {'$unset': {field: ''}})
            return
        iso = expires_at if isinstance(expires_at, str) else expires_at.isoformat()
        await self.user_roles.update_one(
            {'_id': int(uid)},
            {'$set': {field: iso, 'updated_at': utc_now_iso()}}, upsert=True)

    @staticmethod
    def _expiry_passed(value, now_iso: str) -> bool:
        if not value:
            return False
        raw = value if isinstance(value, str) else getattr(value, 'isoformat', lambda: '')()
        return bool(raw) and str(raw) <= now_iso

    async def expire_due_roles(self, uid: int = None) -> list:
        """نقش‌های سررسیدشده را برمی‌دارد و گزارش می‌دهد.

        ایمن برای اجرای مکرر (idempotent): نقشی که قبلاً برداشته شده
        دوباره گزارش نمی‌شود. اگر `uid` بدهید فقط همان کاربر بررسی
        می‌شود — همان مسیری که در زمان ورود/تصمیم استفاده می‌شود.
        """
        now_iso = utc_now_iso()
        query = {'role_expiry': {'$exists': True}}
        if uid is not None:
            query['_id'] = int(uid)
        removed = []
        for doc in await self.user_roles.find(query).to_list(10000):
            expiry = doc.get('role_expiry') or {}
            due = [k for k, v in expiry.items() if self._expiry_passed(v, now_iso)]
            due = [k for k in due if k in (doc.get('roles') or [])]
            if not due:
                continue
            target = int(doc['_id'])
            for key in due:
                # مقدار را *قبل* از پاک‌کردن برمی‌داریم؛ وگرنه گزارش
                # حسابرسی همیشه expired_at=None می‌شود.
                when = expiry.get(key)
                await self._remove_role_key(target, key)
                await self.set_role_expiry(target, key, None)
                removed.append({'uid': target, 'role': key, 'expired_at': when})
            await self.sync_legacy_role_mirror(target)
        return removed

    async def role_expiry_map(self, uid: int) -> dict:
        doc = await self.user_roles.find_one({'_id': int(uid)})
        return dict((doc or {}).get('role_expiry') or {})

    # ══════════════════════════════════════════════════════════
    #  🛡 §۸۵ — محافظت در برابر قفل‌شدن سیستم (self-lockout)
    # ══════════════════════════════════════════════════════════
    #  مجوزهایی که اگر آخرین دارنده‌شان را از دست بدهیم، پنل برای
    #  همیشه غیرقابل مدیریت می‌شود و تنها راه نجات، دست‌کاری مستقیم
    #  دیتابیس است. `delete_role` از قبل وابستگی را چک می‌کرد، ولی
    #  `assign_roles` هیچ گاردی نداشت.
    LOCKOUT_CRITICAL_PERMS = ('roles.manage', 'users.manage')

    async def _owner_id(self) -> int:
        return int(os.getenv('ADMIN_ID', '0'))

    async def perm_holders(self, permission: str, exclude_owner: bool = True) -> list:
        """uidهایی که این مجوز را از راه نقش‌های *فعال* دارند.

        مالک (ADMIN_ID) عمداً حساب نمی‌شود: او تور نجات است، نه یک
        دارنده‌ی عادی. اگر او را بشماریم، گارد هیچ‌وقت فعال نمی‌شود و
        عملاً بی‌اثر است.
        """
        owner = await self._owner_id()
        role_keys = [r['_id'] for r in await self.list_roles()
                     if r.get('active', True) and permission in (r.get('perms') or [])]
        if not role_keys:
            return []
        holders = []
        cursor = self.user_roles.find({'roles': {'$in': role_keys}}, {'_id': 1})
        for doc in await cursor.to_list(10000):
            uid = int(doc['_id'])
            if exclude_owner and uid == owner:
                continue
            holders.append(uid)
        return holders

    async def assignment_lockout_risk(self, uid: int, add: list, remove: list) -> dict:
        """آیا این تغییرِ نقش، آخرین دارنده‌ی یک مجوز حیاتی را حذف می‌کند؟

        شبیه‌سازی خالص — هیچ چیزی نوشته نمی‌شود. خروجی dict است تا هم
        گاردِ سرور و هم پیش‌نمایشِ UI از یک منبع تغذیه شوند.
        """
        owner = await self._owner_id()
        if int(uid) == owner:
            return {'blocked': False, 'perms': []}     # مالک قابل قفل‌شدن نیست

        roles_by_key = {r['_id']: r for r in await self.list_roles()}
        current = await self.get_user_roles(uid)
        after_keys = [k for k in current['keys'] if k not in set(remove or [])]
        after_keys += [k for k in (add or []) if k not in after_keys]

        def perms_of(keys):
            out = set()
            for k in keys:
                role = roles_by_key.get(k)
                if role and role.get('active', True):
                    out.update(role.get('perms') or [])
            return out

        had, has_now = perms_of(current['keys']), perms_of(after_keys)
        at_risk = []
        for perm in self.LOCKOUT_CRITICAL_PERMS:
            if perm in had and perm not in has_now:
                others = [h for h in await self.perm_holders(perm) if h != int(uid)]
                if not others:
                    at_risk.append(perm)
        return {'blocked': bool(at_risk), 'perms': at_risk}

    async def role_edit_lockout_risk(self, key: str, new_perms: list,
                                     active: bool = True) -> dict:
        """همان گارد، برای ویرایشِ خودِ نقش.

        گرفتنِ `roles.manage` از تنها نقشی که آن را دارد، دقیقاً همان
        فاجعه است — فقط از درِ دیگر. غیرفعال‌کردن نقش هم همین اثر را دارد.
        """
        roles_by_key = {r['_id']: r for r in await self.list_roles()}
        old = roles_by_key.get(key)
        if not old:
            return {'blocked': False, 'perms': []}
        new_set = set(new_perms or []) if active else set()
        at_risk = []
        for perm in self.LOCKOUT_CRITICAL_PERMS:
            if perm in (old.get('perms') or []) and perm not in new_set:
                # آیا نقشِ فعالِ دیگری این مجوز را دارد و کاربری دارد؟
                others = []
                for other_key, role in roles_by_key.items():
                    if other_key == key or not role.get('active', True):
                        continue
                    if perm in (role.get('perms') or []):
                        others.append(other_key)
                holders = []
                if others:
                    cursor = self.user_roles.find({'roles': {'$in': others}}, {'_id': 1})
                    owner = await self._owner_id()
                    holders = [int(d['_id']) for d in await cursor.to_list(10000)
                               if int(d['_id']) != owner]
                if not holders:
                    at_risk.append(perm)
        return {'blocked': bool(at_risk), 'perms': at_risk}


    async def has_perm(self, uid: int, permission: str) -> bool:
        """چک مرکزی دسترسی — تنها نقطه‌ی تصمیم Permission-Driven.

        بای‌پسها (قفل سازگاری): ۱) مالک ADMIN_ID  ۲) users.role=='admin'
        قدیمی (سوپریوزر میراثی که در چند مسیر قدیمی پذیرفته شده است)."""
        if uid == int(os.getenv('ADMIN_ID', '0')):
            return True
        u = await self.get_user(uid)
        if u and u.get('role') == 'admin':
            return True
        return permission in await self.get_user_perms(uid)


    async def sync_legacy_role_mirror(self, uid: int) -> str:
        """نگه‌داشت users.role (mirror سازگاری) — §۵ Sync.

        قانون: قوی‌ترین نقش سازگارِ قدیمی، از روی user_roles محاسبه
        می‌شود؛ users.role=='admin' هرگز دست‌نخورده می‌ماند؛ اگر سند
        user_roles وجود نداشته باشد (کاربر دست‌نخورده‌ی RBAC) هیچ
        تغییری نمی‌دهد ⇒ هیچ downgrade بی‌دلیلی ممکن نیست."""
        doc = await self.user_roles.find_one({'_id': uid})
        if not doc:
            return ''
        user = await self.get_user(uid)
        cur = (user or {}).get('role', 'student')
        if cur == 'admin':
            return cur
        info = await self.get_user_roles(uid)
        keys = info['keys']
        perms = await self.get_user_perms(uid)
        target = 'student'
        if 'content_admin' in keys or 'content.manage' in perms:
            target = 'content_admin'
        elif 'support' in keys or 'tickets.reply' in perms:
            target = 'support'
        if target != cur:
            await self.update_user(uid, {'role': target})
        return target


    async def _sync_admin_role_projection(self, uid: int) -> None:
        """پروجکشن admin_roles (تک‌نقشی میراثی) از روی user_roles
        (چندنقشی) — §۵ Sync قرارداد: منوهای ربات که مدل قدیمی را
        می‌خوانند برای کلیدهای legacy همیشه درست می‌مانند.
        پایداری: نقش فعلی admin_roles اگر هنوز تخصیص‌یافته است ابقا
        می‌شود؛ در غیر این صورت اولین کلید legacy از لیست کاربر."""
        doc = await self.user_roles.find_one({'_id': uid})
        keys = list((doc or {}).get('roles') or [])
        legacy_keys = [k for k in keys if k in self.ROLE_LABELS]
        cur = await self.admin_roles.find_one({'_id': uid})
        cur_role = (cur or {}).get('role')
        if cur_role and cur_role in legacy_keys:
            primary = cur_role
        elif legacy_keys:
            primary = legacy_keys[0]
        else:
            primary = None
        if primary is None:
            if cur is not None:
                await self.admin_roles.delete_many({'_id': uid})
            return
        scope = (doc or {}).get('scope_intake')
        if cur and cur_role == primary \
           and cur.get('scope_intake') == scope:
            return  # بدون تغییر — صفر نویز نوشتاری
        await self.admin_roles.update_one(
            {'_id': uid},
            {'$set': {
                'role':         primary,
                'scope_intake': scope,
                'added_by':     'rbac',
                'added_at':     utc_now_iso(),
            }},
            upsert=True,
        )


    # ══════════════════════════════════════════════════
    #  🏷 Identity Layer v1 — لقب (Nickname)
    #  تک‌منبع نمایش نام (§۴): full_name=هویت واقعی (آموزش/
    #  مدیریت)، nickname=هویت اجتماعی، display_name=آنچه
    #  رابط‌ها نشان می‌دهند (nickname یا name). همه‌چیز
    #  در همان سند users است ⇒ Hot Path صفر کوئری اضافه.
    #  Future-ready: رنگ/تأیید/بج لقب = فقط توسعه‌ی
    #  display_name_of، بدون Refactor.
    # ══════════════════════════════════════════════════

    # کلمات رزروشده (بذر — در identity_config قابل ویرایش است)
    RESERVED_NICKNAMES = [
        'admin', 'support', 'system', 'developer', 'moderator',
        'bot', 'humsyar', 'هامزیار', 'مدیر', 'پشتیبانی', 'ادمین',
    ]


    IDENTITY_DEFAULTS = {
        'min_length':       3,
        'max_length':       24,
        'cooldown_days':    30,
        'allow_emoji':      True,
        'allow_spaces':     True,
        'blacklist':        [],
        'reserved_words':   RESERVED_NICKNAMES,
    }


    def display_name_of(self, user: dict) -> str:
        """🏷 تک‌منبع نمایش نام — SYNC (بدون کوئری، §Performance).

        قانون §۳: لقب اگر هست، همان؛ وگرنه نام واقعی."""
        if not isinstance(user, dict):
            return 'کاربر هامزیار'
        nick = (user.get('nickname') or '').strip()
        if nick:
            return nick
        return (user.get('name') or '').strip() or 'کاربر هامزیار'


    # پیام‌های فارسی خطای لقب — تک‌منبع مشترک API و Bot (§یک منبع واحد)
    NICK_ERROR_FA = {
        'empty':        'لقب خالی است',
        'too_short':    'لقب کوتاه است (حداقل طول از تنظیمات)',
        'too_long':     'لقب بلند است (حداکثر از تنظیمات)',
        'bad_chars':    'فقط حروف فارسی/انگلیسی، عدد، فاصله، _ و - و ایموجی محدود مجاز است',
        'emoji_spam':   'بیش از حد ایموجی (حداکثر ۳ عدد)',
        'emoji_only':   'لقب نمی‌تواند فقط ایموجی باشد',
        'emoji_denied': 'استفاده از ایموجی در لقب خاموش است',
        'space_denied': 'فاصله در لقب مجاز نیست',
        'link_denied':  'لینک در لقب مجاز نیست',
        'phone_denied': 'شماره تماس در لقب مجاز نیست',
        'tg_denied':    'آیدی/اشاره تلگرامی در لقب مجاز نیست',
        'reserved':     'این لقب رزرو شده است',
        'blacklisted':  'این لقب مجاز نیست',
        'taken':        'این لقب قبلاً انتخاب شده است',
        'cooldown':     'فعلاً نمی‌توانی لقب را تغییر بدهی (Cooldown)',
        'not_found':    'کاربر پیدا نشد',
    }


    def nick_error_text(self, err: str, info: dict = None) -> str:
        """متن فارسی خطای لقب (+ تاریخ در Cooldown) — مشترک API/Bot."""
        info = info or {}
        detail = self.NICK_ERROR_FA.get(err, err or 'خطای نامشخص')
        if err == 'cooldown' and info.get('next_change_at'):
            detail = (f"{detail} — "
                      f"از {str(info['next_change_at'])[:10]} به بعد")
        return detail


    async def get_identity_config(self) -> dict:
        """تنظیمات لایه‌ی هویت — قابل تغییر بدون Deploy (§Settings)."""
        doc = await self.settings.find_one({'_id': 'identity_config'})
        cfg = dict(self.IDENTITY_DEFAULTS)
        if doc:
            overrides = doc.get('config') or {}
            for key in self.IDENTITY_DEFAULTS:
                if key in overrides and overrides[key] is not None:
                    cfg[key] = overrides[key]
        return cfg


    async def update_identity_config(self, patch: dict,
                                     actor: int = 0) -> dict:
        """به‌روزرسانی whitelist تنظیمات هویت (پنل ادمین)."""
        allowed = set(self.IDENTITY_DEFAULTS)
        clean = {k: v for k, v in (patch or {}).items() if k in allowed}
        await self.settings.update_one(
            {'_id': 'identity_config'},
            {'$set': {**{f'config.{k}': v for k, v in clean.items()},
                      'updated_by': actor,
                      'updated_at': utc_now_iso()}},
            upsert=True,
        )
        return await self.get_identity_config()


    # ── Normalize و Validate (کاملاً سمت سرور — §قوانین) ──

    _INVISIBLE_CHARS = (
        '​‌‍‎‏‪‫‬‭‮⁠'
        '﻿᠎‌'
    )


    _EMOJI_RE = None   # lazy compile


    @classmethod
    def _emoji_pattern(cls):
        if cls._EMOJI_RE is None:
            import re as _re
            cls._EMOJI_RE = _re.compile(
                '[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍‏⁉‼™↔-↙'
                '⤴-⤵�-�️]'
            )
        return cls._EMOJI_RE


    def _norm_nick(self, raw: str) -> str:
        """Normalize (§قوانین): NFKC (Ａｍｉｒ→Amir) + حذف
        کاراکترهای نامرئی/Zero-Width + جمع‌کردن فاصله‌های اضافه + trim."""
        import re
        import unicodedata
        text = unicodedata.normalize('NFKC', raw or '')
        for ch in self._INVISIBLE_CHARS:
            text = text.replace(ch, '')
        text = re.sub(r'\s+', ' ', text)
        return text.strip()


    def validate_nickname(self, raw: str, cfg: dict):
        """اعتبارسنجی کامل لقب — خروجی: (ok, err, clean)

        کنترل‌ها: طول، الفبا (فا/En/عدد/_/-/space)، سقف ایموجی،
        HTML/Markdown/RTL-hack/Injection (از مسیر الفبا رد می‌شوند)،
        لینک/تلفن/@آیدی، رزرو و بلک‌لیست (case-insensitive)."""
        import re
        clean = self._norm_nick(raw)

        if not clean:
            return False, 'empty', clean

        # طول با شمارش یونیکد (بدون ایموجی‌ها هم طول کافی باشد؟ — خیر؛ کل)
        min_len = int(cfg.get('min_length', 3))
        max_len = int(cfg.get('max_length', 24))
        if len(clean) < min_len:
            return False, 'too_short', clean
        if len(clean) > max_len:
            return False, 'too_long', clean

        # ایموجی — سقف ۳ عدد ضداسپم (§Emoji Spam)
        emoji_hits = self._emoji_pattern().findall(clean)
        if emoji_hits and not cfg.get('allow_emoji', True):
            return False, 'emoji_denied', clean
        if len(emoji_hits) > 3:
            return False, 'emoji_spam', clean
        if emoji_hits and len(clean) == len(emoji_hits) + (
                ' ' in clean and clean.count(' ') or 0):
            # فقط ایموجی/فاصله = بدون حرف ⇒ نام نیست
            letters = self._emoji_pattern().sub('', clean).replace(' ', '')
            if not letters:
                return False, 'emoji_only', clean

        if ' ' in clean and not cfg.get('allow_spaces', True):
            return False, 'space_denied', clean

        # الفبا — هرچیزی خارج از این‌ها (HTML/Markdown/@/لینک‌گرافی/
        # کاراکترهای کنترل/اسکریپت) داری رد مستقیم
        base = self._emoji_pattern().sub('', clean)
        if not re.fullmatch(
            r'[A-Za-z0-9_\-\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF ]+',
            base,
        ):
            return False, 'bad_chars', clean

        # لینک/تلفن/آیدی تلگرام (§Abuse Prevention)
        low = clean.lower()
        if re.search(r'(https?|www\.|t\.me|\.com|\.ir|\.net|\.org)', low):
            return False, 'link_denied', clean
        if re.search(r'\d[\d\s\-\.]{7,}\d', low):
            return False, 'phone_denied', clean
        if '@' in clean or 'تلگرام' in clean:
            return False, 'tg_denied', clean

        # رزرو + بلک‌لیست (case-insensitive)
        canon = low
        reserved = [str(w).lower() for w in cfg.get('reserved_words') or []]
        blacklist = [str(w).lower() for w in cfg.get('blacklist') or []]
        if canon in reserved:
            return False, 'reserved', clean
        for bad in blacklist:
            if bad and bad in canon:
                return False, 'blacklisted', clean
        return True, '', clean


    async def nickname_status(self, uid: int, user: dict = None) -> dict:
        """وضعیت لقب کاربر برای API پروفایل — اگر `user` سند
        آماده باشد از همان استفاده می‌شود (صفر کوئری اضافه)."""
        if user is None:
            user = await self.get_user(uid) or {}
        cfg = await self.get_identity_config()
        cool = int(cfg.get('cooldown_days', 30))
        last = user.get('nickname_updated_at')
        can_change = True
        next_at = None
        if last:
            try:
                last_dt = parse_machine_datetime(last)
                next_dt = last_dt + timedelta(days=cool)
                if now_utc() < next_dt:
                    can_change = False
                    next_at = next_dt.isoformat()
            except ValueError:
                pass
        return {
            'nickname':           user.get('nickname') or None,
            'display_name':       self.display_name_of(user),
            'can_change_nickname': can_change,
            'next_change_at':     next_at,
            'show_real_name':     user.get('show_real_name', True),
            'cooldown_days':      cool,
        }


    async def set_nickname(self, uid: int, raw: str,
                           changed_by: str = 'user',
                           reason: str = ''):
        """تنظیم/تغییر/پاک‌کردن لقب — خروجی: (ok, err, info)

        • raw خالی ⇒ پاک‌کردن لقب (display به نام واقعی برمی‌گردد)
        • Cooldown فقط برای خود کاربر؛ ادمین (changed_by!='user') بای‌پس
        • History + display_name_cache + Audit (§Audit/§History)"""
        user = await self.get_user(uid)
        if not user:
            return False, 'not_found', {}
        cfg = await self.get_identity_config()
        now = utc_now_iso()
        old_nick = user.get('nickname') or None

        # پاک‌کردن لقب — بدون Cooldown و بدون Validation
        if raw is None or not str(raw).strip():
            await self.update_user(uid, {
                'nickname':            None,
                'nickname_normalized': None,
                'nickname_updated_at': now,
                'display_name_cache':  (user.get('name') or '').strip(),
            })
            await self.users.update_one(
                {'user_id': uid},
                # 🛡 AUDIT-V3 — کرانه (تغییر لقب cooldown دارد؛ ۵۰ مورد یعنی
                # سال‌ها سابقه). رکوردِ دائمی در _audit_nickname/audit_logs است.
                {'$push': {'nickname_history': {'$each': [{
                    'old': old_nick, 'new': None, 'at': now,
                    'by': changed_by, 'reason': reason or 'clear',
                }], '$slice': -50}}},
            )
            await self._audit_nickname(uid, user, old_nick, None,
                                       changed_by, 'حذف لقب')
            return True, '', {'nickname': None,
                              'display_name': (user.get('name') or '').strip()}

        ok, err, clean = self.validate_nickname(raw, cfg)
        if not ok:
            return False, err, {'clean': clean}

        # Cooldown — فقط برای خود کاربر (§تغییر لقب)
        if changed_by == 'user':
            status = await self.nickname_status(uid)
            if not status['can_change_nickname']:
                return False, 'cooldown', {
                    'next_change_at': status['next_change_at']}

        # یکتایی — case-insensitive روی nickname_normalized
        canon = clean.lower()
        clash = await self.users.find_one({
            'nickname_normalized': canon,
            'user_id': {'$ne': uid},
        })
        if clash:
            return False, 'taken', {}

        await self.update_user(uid, {
            'nickname':            clean,
            'nickname_normalized': canon,
            'nickname_updated_at': now,
            'display_name_cache':  clean,
        })
        await self.users.update_one(
            {'user_id': uid},
            {'$push': {'nickname_history': {'$each': [{
                'old': old_nick, 'new': clean, 'at': now,
                'by': changed_by, 'reason': reason or 'set',
            }], '$slice': -50}}},
        )
        await self._audit_nickname(uid, user, old_nick, clean,
                                   changed_by, 'تغییر لقب')
        return True, '', {'nickname': clean, 'display_name': clean}


    async def _audit_nickname(self, uid: int, user: dict,
                              old_nick, new_nick,
                              changed_by: str, action: str):
        """§Audit — هر تغییر لقب با before/after (خطا مسیر را نمی‌شکند)."""
        try:
            performer_id = uid
            if changed_by.startswith('admin:'):
                raw_id = changed_by.split(':', 1)[1]
                if raw_id.isdigit():
                    performer_id = int(raw_id)
            performer = {} if performer_id == uid \
                else (await self.get_user(performer_id) or {})
            await self.log_action(
                performer_id,
                self.display_name_of(performer or user),
                'student' if changed_by == 'user' else 'مدیر',
                action,
                module='Users', severity='INFO',
                target_id=str(uid), target_type='user',
                target_label=self.display_name_of(user),
                before={'nickname': old_nick},
                after={'nickname': new_nick},
                tags=['identity'],
            )
        except Exception:
            pass


    async def set_show_real_name(self, uid: int, value: bool) -> bool:
        """سوئیچ حریم خصوصی (§Privacy) — فقط نمایش را کنترل می‌کند."""
        await self.update_user(uid, {'show_real_name': bool(value)})
        return True
