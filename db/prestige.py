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
from time_utils import (
    month_key_tehran, now_utc, parse_gregorian_date, parse_machine_datetime,
    to_tehran, utc_now_iso, week_key_tehran,
)

# نام logger عمداً «database» نگه داشته شد تا کانال لاگ تغییر نکند
logger = logging.getLogger('database')



class DBPrestige:


    async def get_leaderboard(self, limit: int = 10):
        # 🚀 WAVE2 P1 — projection: exclude heavy ai_mem/ai_doc that bloats leaderboard fetch
        # Before: full document (incl ai_mem array) → 12KB per row ×10 =120KB + deserialization
        # After: only needed fields → 0.8KB per row (-93%)
        return await self.users.find(
            {'approved': True, 'total_answers': {'$gt': 0}},
            projection={'user_id': 1, 'name': 1, 'nickname': 1, 'nickname_normalized': 1,
                        'total_answers': 1, 'correct_answers': 1, 'effective_xp': 1,
                        'prestige_xp': 1, 'prestige_rank': 1, 'prestige_div': 1,
                        'streak_current': 1, 'privacy_public': 1, '_id': 0}
        ).sort('correct_answers', -1).limit(limit).to_list(limit)


    # ══════════════════════════════════════════════════
    #  👑 Prestige Engine — Competitive Identity (v3 LOCKED · موج P0)
    #  تک‌منبعِ XP/رنک/دیویژن/سپر/Decay/State — بات و API فقط caller‌اند.
    #  (قرارداد §د: هیچ منطق موازی در روتر/بات تکرار نمی‌شود)
    # ══════════════════════════════════════════════════

    # ───── ثابت‌ها (Spec §۲/§۳ — قفل‌شده، بدون تغییر مگر با تأیید مالک)
    XP_WRONG_FIRST    = 1     # غلطِ اولین‌بار هر سؤال

    XP_DAILY_STREAK   = 10    # اولین فعالیت معتبر روز (خارج از سقف)

    XP_EXAM_COMPLETE  = 20    # تکمیل آزمون ≥۱۰ سؤالی

    XP_EXAM_ACC_BONUS = 10    # بونوس دقت ≥۸۰٪

    XP_EXAM_PERFECT   = 20    # بونوس ۱۰۰٪ (جایگزین قبلی)

    DAILY_ANSWER_CAP  = 120   # سقف روزانه‌ی XPِ پاسخ‌محور

    DIMINISH_AFTER    = 40    # بعد از این تعداد صحیح در روز: ×۰٫۵

    SHIELD_ANSWERS    = 30    # سپر ارتقا: ۳۰ پاسخ

    SHIELD_DAYS       = 10    # یا ۱۰ روز (هرکدام زودتر)

    DECAY_IDLE_DAYS   = 10    # هر ۱۰ روز رکود = −۱ دیویژن (کفِ رنک)

    ACTIVE_WINDOW_DAYS = 90   # تعریف Active User (§۳.۵)

    PC_CACHE_TTL_SEC  = 600   # کش total_active — ۱۰ دقیقه


    # جدول آستانه‌ها (Spec §۱.۱ — key, title, icon, start_xp, color, gradient)
    PRESTIGE_RANKS = [
        ('rookie',    'تازه‌وارد',      '🌱', 0,     '#94A3B8', 'linear-gradient(135deg,#94A3B8,#CBD5E1)'),
        ('student',   'دانشجوی کوشا',   '📚', 300,   '#34D399', 'linear-gradient(135deg,#34D399,#6EE7B7)'),
        ('scholar',   'پژوهنده',        '🧠', 750,   '#60A5FA', 'linear-gradient(135deg,#60A5FA,#93C5FD)'),
        ('apprentice','کارآموز پزشکی', '⚕️', 1500,  '#38BDF8', 'linear-gradient(135deg,#38BDF8,#67E8F9)'),
        ('resident',  'رزیدنت',         '🏥', 2400,  '#A78BFA', 'linear-gradient(135deg,#A78BFA,#C4B5FD)'),
        ('elite',     'مدیک نخبه',      '⭐', 3900,  '#FBBF24', 'linear-gradient(135deg,#FBBF24,#FDE68A)'),
        ('expert',    'متخصص بالینی',  '💎', 6000,  '#22D3EE', 'linear-gradient(135deg,#22D3EE,#A5F3FC)'),
        ('master',    'استاد پزشکی',   '👑', 8700,  '#F59E0B', 'linear-gradient(135deg,#F59E0B,#FBBF24)'),
        ('grand',     'استاد بزرگ',    '🏆', 12000, '#FB923C', 'linear-gradient(135deg,#FB923C,#FDBA74)'),
        ('legend',    'شفابخش افسانه‌ای','🌌', 16500,'#E879F9', 'linear-gradient(135deg,#E879F9,#C084FC,#818CF8)'),
    ]

    CHALLENGE_FROM_IDX = 4          # ورود به رنک ۵ (resident) به بعد نیازمند چالش است

    ROMAN = {3: 'III', 2: 'II', 1: 'I'}

    DIV_STARS = {3: '⭐', 2: '⭐⭐', 1: '⭐⭐⭐'}


    @staticmethod
    def _diff_key(raw) -> str:
        """نگاشت متن difficulty سؤال به کلید XP (Spec §۳.۱ — الگوی متن)."""
        t = str(raw or '')
        if 'آسان' in t: return 'easy'
        if 'سخت' in t: return 'hard'
        if 'متوسط' in t: return 'medium'
        return 'unknown'


    XP_BY_DIFF = {'easy': 5, 'medium': 10, 'hard': 15, 'unknown': 8}


    # ── منابع XP وسیع‌تر (Spec §۲.۱ — جدول قفل‌شده)
    XP_FILE_DOWNLOAD  = 8     # اولین دانلود هر فایل

    XP_AI_DAILY       = 5     # اولین گفت‌وگوی هوشیار در روز

    XP_Q_APPROVED     = 25    # تأیید سؤال طراحی‌شده

    XP_REPORT_USEFUL  = 15    # گزارش مفید (resolve)

    XP_CHALLENGE_WIN  = 50    # برد چالش ارتقا (رنک ۵..۹)

    XP_APEX_WIN       = 200   # برد چالش Apex (یک‌بار در عمر حساب)

    XP_WEEKLY_CHAMPION = 100  # صدر جدول هفتگی (جاب بستن هفته)


    # ── قوانین چالش ارتقا (Spec §۳.۱ — قفل‌شده)
    CH_COUNT            = 20    # سؤال چالش عادی

    CH_APEX_COUNT       = 30    # سؤال چالش Apex (باس‌فایت)

    CH_PASS_PCT         = 80    # شرط قبولی چالش عادی

    CH_APEX_PASS_PCT    = 90    # شرط قبولی Apex

    CH_TTL_HOURS        = 24    # TTL جلسه — Resume پس از انقضا ممنوع

    CH_COOLDOWN_H       = 12    # کول‌داون شکست عادی

    CH_APEX_COOLDOWN_H  = 48    # کول‌داون شکست Apex

    CH_EXCLUDE_RECENT   = 200   # حذف ۲۰۰ پاسخ اخیر از استخر

    CH_EXCLUDE_FALLBACK = [150, 100, 50]   # پنجره‌های جایگزین به ترتیب

    CH_MIX_MIN_HARDMED  = 0.4   # حداقل ۴۰٪ متوسط+سخت

    CH_APEX_STREAK_REQ  = 45    # پیش‌شرط اجتماعی Apex: بهترین استریک

    CH_APEX_CONTRIB_REQ = 5     # پیش‌شرط اجتماعی Apex: مشارکت تأییدشده


    # ── جدول Rarity نشان‌ها (Spec §۴.۱ — label/color/پاداش پیش‌فرض)
    BADGE_RARITY = {
        'common':    ('معمولی',    '#94A3B8', 15),
        'rare':      ('کمیاب',     '#60A5FA', 30),
        'epic':      ('حماسی',     '#A78BFA', 60),
        'legendary': ('افسانه‌ای', '#F59E0B', 120),
        'mythic':    ('اسطوره‌ای', '#E879F9', 300),
        'ancient':   ('باستانی',   '#D6A35C', 500),
        'founder':   ('بنیان‌گذار', '#FFD700', 0),
    }


    # ── پنج نشان تکاملی (Spec §۴.۱ب — مقادیر قطعی)
    # key: (icon, title, counter, tiers=[(target, rarity, xp), ...])
    BADGES_PROG = {
        'p_qmaster': ('🏹', 'استاد سؤال', 'total_answers',
                      [(10, 'common', 15), (100, 'rare', 30), (500, 'epic', 60),
                       (1000, 'legendary', 120), (2500, 'mythic', 300)]),
        'p_flame': ('🔥', 'شعله‌ی پایدار', 'streak_best',
                    [(3, 'common', 15), (7, 'rare', 30), (30, 'epic', 60),
                     (90, 'legendary', 120), (180, 'mythic', 300)]),
        'p_exam': ('⚔️', 'فرمانده‌ی آزمون', 'exams_completed',
                   [(1, 'common', 15), (10, 'rare', 30), (30, 'epic', 60),
                    (150, 'ancient', 500)]),
        'p_companion': ('🤝', 'هم‌گوی هوشیار', 'ai_conv_days',
                        [(1, 'common', 15), (10, 'rare', 30), (50, 'epic', 60)]),
        'p_librarian': ('📚', 'کتابدار', 'downloads_count',
                        [(1, 'common', 15), (10, 'rare', 30), (50, 'epic', 60)]),
    }


    # ── نشان‌های تک‌نسخه‌ی كاتالوگ (Spec §۴.۱ب/§۴.۳)
    # key: dict(icon,title,desc,rarity,xp,kind,secret?,hint?)
    BADGES_SINGLE = {
        # لحظه‌ای‌های احساسی (کاملاً جدا از پله‌ها)
        'q_first': dict(icon='🌱', title='نخستین پاسخ', desc='اولین پاسخ ثبت‌شده‌ات',
                        rarity='common', xp=15, kind='lifetime'),
        'e_first': dict(icon='📝', title='نخستین آزمون', desc='اولین آزمون تکمیل‌شده',
                        rarity='common', xp=15, kind='lifetime'),
        'ai_first': dict(icon='🤖', title='نخستین گفت‌وگو با هوشیار',
                         desc='اولین روز گفت‌وگو با هوشیار',
                         rarity='common', xp=15, kind='lifetime'),
        'e_pass20': dict(icon='🎖', title='گذرنده‌ی آزمون بزرگ',
                         desc='تکمیل آزمون ≥۲۰ سؤالی با دقت ≥۸۰٪',
                         rarity='rare', xp=30, kind='exam'),
        'exam_perfect': dict(icon='🎯', title='برگ کامل',
                             desc='آزمون ≥۱۰ سؤالی با دقت ۱۰۰٪',
                             rarity='epic', xp=60, kind='exam'),
        'lesson_done': dict(icon='📚', title='یک درس، تمام‌شده',
                            desc='دانلود تمام محتوای یک درس علوم‌پایه',
                            rarity='rare', xp=30, kind='resource'),
        'ai_image': dict(icon='🖼', title='چشم‌عقابی',
                         desc='نخستین حل تصویری با هوشیار',
                         rarity='common', xp=15, kind='ai'),
        'ai_pdf': dict(icon='📄', title='خوانش‌گر',
                       desc='نخستین تحلیل PDF با هوشیار',
                       rarity='common', xp=15, kind='ai'),
        # Accuracy ۳ (حداقل ۱۰۰ پاسخ — هم‌ریشه با تب دقت لیدربرد)
        'acc70': dict(icon='🎯', title='تیرانداز مطمئن', desc='دقت کلی ≥۷۰٪ (با ≥۱۰۰ پاسخ)',
                      rarity='common', xp=15, kind='accuracy'),
        'acc80': dict(icon='🏹', title='نشانه‌رو حرفه‌ای', desc='دقت کلی ≥۸۰٪ (با ≥۱۰۰ پاسخ)',
                      rarity='rare', xp=30, kind='accuracy'),
        'acc90': dict(icon='💎', title='چشم‌عقابیِ دقت', desc='دقت کلی ≥۹۰٪ (با ≥۱۰۰ پاسخ)',
                      rarity='epic', xp=60, kind='accuracy'),
        # Community ۴
        'c_first_design': dict(icon='✍️', title='نخستین طرح تأییدشده',
                               desc='اولین سؤال طراحی‌شده‌ی تأییدشده‌ات',
                               rarity='common', xp=15, kind='community'),
        'c_first10': dict(icon='🏛', title='ستون بانک سؤال',
                          desc='۱۰ سؤال تأییدشده در بانک',
                          rarity='legendary', xp=120, kind='community'),
        'c_first_report': dict(icon='🕵️', title='مراقب کیفیت',
                               desc='اولین گزارش مفید تأییدشده',
                               rarity='common', xp=15, kind='community'),
        'c_reports10': dict(icon='🛡', title='نگهبان کیفیت',
                            desc='۱۰ گزارش مفید تأییدشده',
                            rarity='rare', xp=30, kind='community'),
        # Secret ۵ (نمایش مبهم تا زمان باز شدن)
        'x_owl': dict(icon='🦉', title='جغد شب‌زنده‌دار',
                      desc='فعالیت بین ۰۰ تا ۰۳ بامداد',
                      rarity='rare', xp=30, kind='secret', secret=True,
                      hint='بعضی‌ها وقتی همه خوابند…'),
        'x_lark': dict(icon='🐦', title='مرغ سحرخیز',
                       desc='فعالیت بین ۰۵ تا ۰۷ صبح',
                       rarity='rare', xp=30, kind='secret', secret=True,
                       hint='صبح که طلایه‌دار شد…'),
        'x_30day': dict(icon='🧠', title='روز مغز',
                        desc='۳۰ پاسخ صحیح در یک روز',
                        rarity='rare', xp=30, kind='secret', secret=True,
                        hint='یک روز خیلی جدی'),
        'x_comeback': dict(icon='🫶', title='بازگشت قهرمان',
                           desc='برگشتن بعد از ≥۱۴ روز دوری',
                           rarity='rare', xp=30, kind='secret', secret=True,
                           hint='گاهی باید رفت تا برگشت'),
        'x_week300': dict(icon='⚡', title='هفته‌ی برق‌آسا',
                          desc='۳۰۰+ XP در یک هفته',
                          rarity='rare', xp=30, kind='secret', secret=True,
                          hint='یک هفته‌ی تمام‌نشدنی'),
        # Ancient (فرازمانی — سال‌ها)
        'a_q5000': dict(icon='🏺', title='پانزده‌خزان سؤال',
                        desc='۵٬۰۰۰ پاسخ ثبت‌شده',
                        rarity='ancient', xp=500, kind='ancient'),
        'a_s365': dict(icon='🕯', title='شمع جاودان',
                       desc='استریک ۳۶۵ روزه',
                       rarity='ancient', xp=500, kind='ancient'),
        # Founder / Competition
        'f_founder': dict(icon='🏛', title='بنیان‌گذار هامزیار',
                          desc='از نخستین اعضای پلتفرم — دیگر قابل دریافت نیست',
                          rarity='founder', xp=0, kind='founder'),
        'c_top1_week': dict(icon='👑', title='صدرنشین هفته',
                            desc='قهرمان جدول هفتگی',
                            rarity='legendary', xp=120, kind='competition'),
    }


    SHOWCASE_MAX = 3                   # سقف نشان پین‌شده (Spec §۴.۴)

    AI_DAYS_KEEP = 365                 # سقف نگه‌داری روزهای گفت‌وگوی هوشیار


    def _div_width(self, idx: int) -> int:
        """پهنای هر دیویژن درون رنک (تمام بازه‌ها بر ۳ بخش‌پذیرند — Spec §۱.۱)"""
        if idx >= len(self.PRESTIGE_RANKS) - 1:
            return 0
        return (self.PRESTIGE_RANKS[idx + 1][3] - self.PRESTIGE_RANKS[idx][3]) // 3


    def _rank_for(self, xp: int):
        """رنک خام از روی XP: بازگشت (idx, div) — div: 3=III ... 1=I (Apex همیشه 1)"""
        idx = 0
        for i, r in enumerate(self.PRESTIGE_RANKS):
            if xp >= r[3]:
                idx = i
        if idx >= len(self.PRESTIGE_RANKS) - 1:
            return idx, 1
        start = self.PRESTIGE_RANKS[idx][3]
        w = self._div_width(idx)
        off = xp - start
        if off < w:
            return idx, 3
        if off < 2 * w:
            return idx, 2
        return idx, 1


    @staticmethod
    def _puser(u: dict) -> dict:
        """مهاجرت نرم: فیلدهای Prestige کاربرهای کهنه با پیش‌فرض درون‌حافظه‌ای پر می‌شوند.
        (قرارداد: فقط افزایشی — در خودِ سند چیزی حذف نمی‌شود؛ نوشتن با رویداد بعدی)"""
        d = dict(u or {})
        d.setdefault('prestige_xp', 0)
        d.setdefault('decay_penalty', 0)
        d.setdefault('decay_blocks', 0)
        d.setdefault('rank_floor_xp', 0)
        d.setdefault('effective_xp', 0)
        d.setdefault('season_xp', 0)
        d.setdefault('season_key', 'S1-1405')
        d.setdefault('weekly_xp', 0)
        d.setdefault('weekly_reset', '')
        d.setdefault('monthly_xp', 0)          # 👑 P2 — بازه‌ی ماه لیدربرد
        d.setdefault('monthly_reset', '')
        d.setdefault('ai_conv_days', [])       # 👑 P1 — روزهای گفت‌وگوی هوشیار
        d.setdefault('submissions_approved', 0)
        d.setdefault('reports_resolved', 0)
        ch = d.get('challenge') or {}
        if not isinstance(ch, dict):
            ch = {}
        ch.setdefault('target_rank', '')
        ch.setdefault('cooldown_until', '')
        ch.setdefault('last_fail_at', '')
        ch.setdefault('apex', False)
        d['challenge'] = ch
        d.setdefault('last_gain_at', '')
        d.setdefault('last_active_day', '')
        d.setdefault('shield_answers', 0)
        d.setdefault('shield_until', '')
        d.setdefault('daily_xp', {'date': '', 'amount': 0, 'correct': 0})
        if not isinstance(d['daily_xp'], dict):
            d['daily_xp'] = {'date': '', 'amount': 0, 'correct': 0}
        d['daily_xp'].setdefault('correct', 0)
        d.setdefault('streak_current', 0)
        d.setdefault('streak_best', 0)
        d.setdefault('exams_completed', 0)
        d.setdefault('downloads_count', 0)
        rec = d.get('records') or {}
        rec.setdefault('best_acc', 0)
        rec.setdefault('best_exam_pct', 0)
        rec.setdefault('top_rank_key', 'rookie')
        rec.setdefault('top_rank_at', '')
        rec.setdefault('top_div', 3)
        rec.setdefault('top1_weeks_current', 0)
        rec.setdefault('top1_weeks_best', 0)
        rec.setdefault('apex_wins', 0)         # 👑 P1 — تعداد بردهای Apex (رکورد ابدی)
        d['records'] = rec
        d.setdefault('achievements', {})
        if not isinstance(d['achievements'], dict):
            d['achievements'] = {}
        d.setdefault('privacy_public', True)
        d.setdefault('showcase', [])
        return d


    @staticmethod
    def _tehran_today() -> str:
        from utils import now_tehran
        return now_tehran().date().isoformat()


    async def _history_add(self, uid: int, etype: str, key: str = '', detail: dict = None) -> None:
        """ثبت رویداد در prestige_history (نمایش سفر/فید — Spec §۸.۲)"""
        try:
            await self.prestige_history.insert_one({
                'uid': uid, 'type': etype, 'key': key,
                'detail': detail or {}, 'at': utc_now_iso(),
                'reactions': {'clap': 0, 'fire': 0, 'crown': 0},
            })
        except Exception:
            pass


    async def _claim_global_first(self, key: str, uid: int) -> bool:
        """ادعای اتمیک نشان جهانی (Spec §۴.۲ — race غیرممکن با findOneAndUpdate)"""
        try:
            from pymongo import ReturnDocument
            doc = await self.settings.find_one_and_update(
                {'_id': 'global_firsts', f'claims.{key}': {'$exists': False}},
                {'$set': {f'claims.{key}': {'uid': uid, 'at': utc_now_iso()}}},
                upsert=True, return_document=ReturnDocument.AFTER,
            )
            return bool(doc) and (doc.get('claims', {}).get(key, {}).get('uid') == uid)
        except Exception:
            return False


    def _next_info(self, idx: int, div: int, eff: int, challenge_locked: bool) -> dict:
        """هدف بعدی (دیویژن یا چالش) + مقدار لازم — قلب خط «هدف فعلی» (Spec §۵).
        have/span همیشه پر می‌شوند (پیشرفت درون بازه‌ی فعلی) تا نوار پیشرفت
        کلاینت بدون دانستن آستانه‌ها رسم شود — تک‌منبع اعداد همین‌جاست."""
        start = self.PRESTIGE_RANKS[idx][3]
        if idx >= len(self.PRESTIGE_RANKS) - 1:
            return {'kind': 'none', 'needed': 0, 'have': 1, 'span': 1,
                    'label': 'شما در اوج هستید 🌌'}
        w = self._div_width(idx)
        next_start = self.PRESTIGE_RANKS[idx + 1][3]
        if not challenge_locked and div > 1:
            nxt_div = div - 1
            boundary = start + (3 - (div - 1)) * w  # آستانه‌ی شروع div بعدی
            need = max(0, boundary - eff)
            return {'kind': 'div', 'needed': need, 'have': w - need,
                    'span': w, 'to_div': nxt_div,
                    'label': f"فقط {need} XP تا {self.PRESTIGE_RANKS[idx][1]} {self.ROMAN[nxt_div]}"}
        # مرز رنک بعد — نوار = پیشرفت در کل بازه‌ی رنک فعلی
        nxt = self.PRESTIGE_RANKS[idx + 1]
        need = max(0, next_start - eff)
        have = max(0, eff - start)
        span = max(1, next_start - start)
        if idx + 1 >= self.CHALLENGE_FROM_IDX:
            return {'kind': 'challenge', 'needed': need,
                    'have': have, 'span': span,
                    'to_rank': nxt[0], 'ready': need == 0,
                    'label': (f"⭐ چالش ارتقا آماده است — برای {nxt[2]} {nxt[1]}"
                              if need == 0 else
                              f"{need} XP تا چالش {nxt[2]} {nxt[1]}")}
        return {'kind': 'rank', 'needed': need,
                'have': have, 'span': span,
                'to_rank': nxt[0],
                'label': f"فقط {need} XP تا {nxt[2]} {nxt[1]}"}


    async def prestige_event(self, uid: int, kind: str, meta: dict = None) -> dict:
        """قلب موتور (Event-Based — Spec §۵.۱).
        kind: 'answer' (meta: is_correct, difficulty, first_time) |
              'exam_complete' (meta: pct, total)
        خروجی: خلاصه‌ی XP + رویدادها برای caller (بات→پیام، API→payload)."""
        meta = meta or {}
        raw = await self.users.find_one({'user_id': uid})
        if not raw or not raw.get('approved'):
            return {'ignored': True}
        u = self._puser(raw)
        # 👑 P3 — اوررایدهای زنده‌ی تعادل (کش ۶۰ثانیه؛ پیش‌فرض = ثابت‌های کلاس)
        cfg = await self._pcfg()
        n = lambda k, d: self._cnum(cfg, k, d)
        XP_DIFF = {'easy': n('xp_easy', self.XP_BY_DIFF['easy']),
                   'medium': n('xp_medium', self.XP_BY_DIFF['medium']),
                   'hard': n('xp_hard', self.XP_BY_DIFF['hard']),
                   'unknown': n('xp_unknown', self.XP_BY_DIFF['unknown'])}
        today = self._tehran_today()
        bdown = []                       # breakdown فارسی برای نمایش
        inc = {}                         # شمارنده‌های $inc
        sets = {}                        # فیلدهای $set
        gain = 0
        badge_awards = []                # 👑 P1 — نشان‌های بازشده در همین رویداد

        # ── rollover هفته (lazy، idempotent — Spec §۸.۱ weekly_reset)
        business_week = week_key_tehran(parse_gregorian_date(today))
        if u['weekly_reset'] != business_week:
            sets['weekly_xp'] = 0
            sets['weekly_reset'] = business_week

        # 👑 P2 — rollover ماه (تماماً هم‌الگوی هفته؛ برای بازه‌ی «ماه» لیدربرد)
        business_month = month_key_tehran(parse_gregorian_date(today))
        if u['monthly_reset'] != business_month:
            sets['monthly_xp'] = 0
            sets['monthly_reset'] = business_month

        # 👑 P2 — rollover سيزن (All-Time هرگز ریست نمی‌شود — Spec §۱۶)
        season_now = await self._season_key()
        if u.get('season_key') != season_now:
            sets['season_key'] = season_now
            sets['season_xp'] = 0

        return_idle_days = 0              # برای نشان مخفی «بازگشت قهرمان»

        # ── خوش‌آمدِ بازگشت: پاک‌سازی جریمه‌ی Decay (Spec §۳.۳)
        demoted = None
        if u['decay_penalty'] > 0 and u['last_active_day'] != today:
            sets['decay_penalty'] = 0
            sets['decay_blocks'] = 0
            sets['shield_until'] = today      # سپر روزِ برگشت (۱ روز)
            try:
                return_idle_days = (parse_gregorian_date(today)
                                    - parse_gregorian_date(u['last_active_day'])).days
            except Exception:
                return_idle_days = 0
            await self._history_add(uid, 'return', detail={'cleared': u['decay_penalty']})
            try:
                await self.inbox_add(uid, 'return', '🫶 خوش برگشتی',
                    'جریمه‌ی رکود پاک شد؛ امروز سپر داری. بریم ادامه بدیم 💪',
                    '/me/profile')
            except Exception:
                pass

        # ── Decay lazy روی کاربرِ در حال رکود (idempotent با decay_blocks)
        demoted = await self._apply_lazy_decay(u, today, sets)

        # ── XP بر اساس نوع رویداد (قوانین §۲.۱/§۳)
        daily = dict(u['daily_xp'])
        if daily.get('date') != today:
            daily = {'date': today, 'amount': 0, 'correct': 0}

        if kind == 'answer':
            first_time = bool(meta.get('first_time'))
            ok = bool(meta.get('is_correct'))
            if first_time:
                if ok:
                    base = XP_DIFF[self._diff_key(meta.get('difficulty'))]
                    if daily['correct'] >= n('diminish_after', self.DIMINISH_AFTER):
                        base = max(1, base // 2)     # diminishing ۵۰٪ (§۳.۳)
                    diff_fa = {'easy': 'آسان', 'medium': 'متوسط',
                               'hard': 'سخت', 'unknown': 'سؤال'}[self._diff_key(meta.get('difficulty'))]
                    bdown.append((f'پاسخ صحیح · {diff_fa}', base))
                else:
                    base = n('xp_wrong_first', self.XP_WRONG_FIRST)
                    bdown.append(('تلاش (پاسخ اولین‌بار)', base))
                room = max(0, n('daily_cap', self.DAILY_ANSWER_CAP) - daily['amount'])
                add = min(base, room)                # سقف روزانه‌ی ۱۲۰ (§۳.۲)
                gain += add
                daily['amount'] += add
                if bdown and add < bdown[-1][1]:
                    bdown[-1] = (bdown[-1][0] + ' (سقف روزانه)', add)
            if ok:
                daily['correct'] += 1
        elif kind == 'exam_complete':
            total = int(meta.get('total') or 0)
            pct = float(meta.get('pct') or 0)
            inc['exams_completed'] = 1
            if pct > (u['records'].get('best_exam_pct') or 0):
                sets['records.best_exam_pct'] = pct
            if total >= 10:
                xp_exam = n('xp_exam_complete', self.XP_EXAM_COMPLETE)
                base = xp_exam
                bdown.append(('تکمیل آزمون', base))
                if pct >= 100:
                    xp_pf = n('xp_exam_perfect', self.XP_EXAM_PERFECT)
                    base += xp_pf
                    bdown.append(('بونوس برگ کامل 🎯', xp_pf))
                elif pct >= 80:
                    xp_ac = n('xp_exam_acc80', self.XP_EXAM_ACC_BONUS)
                    base += xp_ac
                    bdown.append(('بونوس دقت بالا', xp_ac))
                gain += base               # آزمون خارج از سقف روزانه (§۳.۲)
        elif kind == 'file_download':
            # 👑 P1 — اولین دانلود هر فایل (تک‌بار — Spec §۲.۱)
            first_time = bool(meta.get('first_time'))
            if first_time:
                inc['downloads_count'] = 1
                bdown.append(('منبع جدید 📚', n('xp_file_download', self.XP_FILE_DOWNLOAD)))
                gain += n('xp_file_download', self.XP_FILE_DOWNLOAD)
        elif kind == 'ai_daily':
            # 👑 P1 — اولین گفت‌وگوی هوشیار در روز (یک‌بار/روز — Spec §۲.۱)
            days = list(u.get('ai_conv_days') or [])
            if today not in days:
                days.append(today)
                sets['ai_conv_days'] = days[-self.AI_DAYS_KEEP:]
                bdown.append(('همراهی روزانه با هوشیار 🤖', n('xp_ai_daily', self.XP_AI_DAILY)))
                gain += n('xp_ai_daily', self.XP_AI_DAILY)
        elif kind == 'question_approved':
            # 👑 P1 — تأیید سؤال طراحی‌شده‌ی کاربر (+۲۵ به طراح)
            inc['submissions_approved'] = 1
            bdown.append(('سؤال تأییدشده ✍️', n('xp_question_approved', self.XP_Q_APPROVED)))
            gain += n('xp_question_approved', self.XP_Q_APPROVED)
        elif kind == 'report_useful':
            # 👑 P1 — گزارش مفید (باگِ واقعی گزارش‌شده که resolve شد)
            inc['reports_resolved'] = 1
            bdown.append(('گزارش مفید 🕵️', n('xp_report_useful', self.XP_REPORT_USEFUL)))
            gain += n('xp_report_useful', self.XP_REPORT_USEFUL)
        elif kind == 'referral':
            # 🌱 W13 — جایزه‌ی دعوت دوستان (مبلغ از کانفیگ ریفرال می‌آید، نه ثابت کلاس)
            try:
                _rxp = max(0, int(meta.get('xp') or 0))
            except (TypeError, ValueError):
                _rxp = 0
            if _rxp:
                bdown.append(('دعوت دوستان 🎁', _rxp))
                gain += _rxp
        elif kind == 'challenge_win':
            # 👑 P1 — برد چالش ارتقا (Spec §۳.۱: نتیجه سرورمحور)
            target_idx = int(meta.get('target_idx') or 0)
            apex = bool(meta.get('apex'))
            target_idx = max(0, min(target_idx, len(self.PRESTIGE_RANKS) - 1))
            r_t = self.PRESTIGE_RANKS[target_idx]
            reward = (n('xp_apex_win', self.XP_APEX_WIN) if apex
                      else n('xp_challenge_win', self.XP_CHALLENGE_WIN))
            bdown.append((f"برد چالش ارتقا {r_t[2]} {r_t[1]}", reward))
            gain += reward
            # کفِ رنک بالا می‌رود ⇒ قفل چالش باز و overflow آزاد می‌شود
            sets['rank_floor_xp'] = max(u['rank_floor_xp'], r_t[3])
            sets['challenge'] = {'target_rank': '', 'cooldown_until': '',
                                 'last_fail_at': '', 'apex': False}
            if apex:
                inc['records.apex_wins'] = 1
            await self._history_add(uid, 'challenge_win', r_t[0],
                                    {'apex': apex, 'pct': meta.get('pct')})
            try:
                await self.inbox_add(uid, 'challenge_win',
                    f"⚔️ برد چالش: {r_t[2]} {r_t[1]}",
                    f"آزمون با {meta.get('pct') or 0}٪ پاس شد و رسمی شدی. "
                    f"{reward}+ XP جایزه‌ی چالش + سپر ارتقا فعال شد 🛡",
                    '/me/profile')
            except Exception:
                pass
        elif kind == 'weekly_champion':
            # 👑 P2 — صدر جدول هفتگی (فقط از جاب بستن هفته — Spec §۶.۱)
            wk_str = str(meta.get('week') or '')
            bdown.append(('صدر جدول هفتگی 👑', n('xp_weekly_champion', self.XP_WEEKLY_CHAMPION)))
            gain += n('xp_weekly_champion', self.XP_WEEKLY_CHAMPION)
            prev_ct = int((u.get('achievements') or {}).get('c_top1_week', {}).get('count', 0) or 0)
            new_ct = prev_ct + 1
            sets['achievements.c_top1_week'] = {'at': utc_now_iso(),
                                                'count': new_ct, 'last_week': wk_str}
            cur1 = int(u['records'].get('top1_weeks_current', 0) or 0) + 1
            sets['records.top1_weeks_current'] = cur1
            sets['records.top1_weeks_best'] = max(int(u['records'].get('top1_weeks_best', 0) or 0), cur1)
            badge_awards.append({'key': 'c_top1_week',
                                 **{k: self.BADGES_SINGLE['c_top1_week'][k]
                                    for k in ('icon', 'title', 'rarity', 'xp')},
                                 'count': new_ct})
            # XP خودِ نشان صدرنشینی (legendary +۱۲۰) هم پرداخت می‌شود
            _bxp = int(self.BADGES_SINGLE['c_top1_week']['xp'])
            bdown.append(('نشان صدرنشینی 👑', _bxp))
            gain += _bxp
            await self._history_add(uid, 'weekly_champion', wk_str, {'count': new_ct})
            try:
                await self.inbox_add(uid, 'weekly_champion', '👑 صدر هفته مال تو بود',
                    f"قهرمان جدول هفتگی شدی {'(×' + str(new_ct) + ')' if new_ct > 1 else ''} "
                    f"— {n('xp_weekly_champion', self.XP_WEEKLY_CHAMPION)}+ XP و نشان صدرنشینی 🏅",
                    '/leaderboard')
            except Exception:
                pass
        sets['daily_xp'] = daily

        # ── استریک روز (اولین فعالیت معتبر روز — تهران)
        streak_new = False
        if u['last_active_day'] != today:
            y = (parse_gregorian_date(today) - timedelta(days=1)).isoformat()
            cur = (u['streak_current'] + 1) if u['last_active_day'] == y else 1
            best = max(cur, u['streak_best'])
            sets['streak_current'] = cur
            sets['streak_best'] = best
            sets['last_active_day'] = today
            gain += n('xp_streak_day', self.XP_DAILY_STREAK)
            bdown.append(('فعالیت روزانه 🔥', n('xp_streak_day', self.XP_DAILY_STREAK)))
            streak_new = True
            u['streak_current'], u['streak_best'] = cur, best

        # ── بهترین دقت (رکورد — روی شمارنده‌های تازه‌ی legacy که save_answer زد)
        total_a = int(raw.get('total_answers', 0) or 0)
        corr_a = int(raw.get('correct_answers', 0) or 0)
        acc = round(corr_a / total_a * 100) if total_a else 0
        if acc > (u['records'].get('best_acc') or 0):
            sets['records.best_acc'] = acc

        # 👑 P1 — جاروی نشان‌ها (تکاملی ۵تایی + تک‌نسخه‌ها + جهانی‌های جدید)
        # XP نشان خارج از سقف روزانه است؛ قبل از نوشتن اصلی اعمال می‌شود.
        # ⭐ بونوس نشان/جهانی از xp_gained پاسخ جدا می‌ماند (قرارداد P0:
        # xp_gained = فقط XP رویداد اصلی) اما در DB و رنک کاملاً لحاظ می‌شود.
        bonus_xp = 0
        try:
            weekly_after = float(sets.get('weekly_xp', u['weekly_xp']) or 0) + gain
            bonus_xp += await self._badge_scan(uid, u, raw, inc, sets, bdown, badge_awards,
                {'kind': kind, 'meta': meta, 'daily': dict(daily),
                 'return_idle_days': return_idle_days,
                 'weekly_xp_after': weekly_after})
        except Exception:
            pass

        # ── جمع‌بندی XP
        total_gain = gain + bonus_xp
        if total_gain > 0:
            inc['prestige_xp'] = total_gain
            inc['season_xp'] = total_gain
            inc['weekly_xp'] = total_gain
            inc['monthly_xp'] = total_gain
            sets['last_gain_at'] = utc_now_iso()
        if inc or sets:
            upd = {}
            if inc: upd['$inc'] = inc
            if sets: upd['$set'] = sets
            try:
                await self.users.update_one({'user_id': uid}, upd)
            except Exception:
                return {'ignored': True}

        # ── سپر: مصرف پاسخی
        shield_active = (u['shield_answers'] > 0) or (u['shield_until'] and u['shield_until'] >= today)
        if kind == 'answer' and u['shield_answers'] > 0:
            left = u['shield_answers'] - 1
            await self.users.update_one({'user_id': uid}, {'$set': {'shield_answers': left}})
            u['shield_answers'] = left
            shield_active = left > 0 or (u['shield_until'] and u['shield_until'] >= today)

        # ── محاسبه‌ی رنک/دیویژن جدید (با کلمپ چالش — Spec §۳.۱)
        new_xp = u['prestige_xp'] + total_gain
        penalty = sets.get('decay_penalty', u['decay_penalty'])
        floor = max(u['rank_floor_xp'], int(sets.get('rank_floor_xp', 0) or 0))
        eff = max(new_xp - penalty, floor)
        # مقایسه بر مبنای رنکِ «نمایشیِ» قبلی (کلمپ با کفِ پیشین) — وگرنه بردِ
        # چالش روی overflow انباشته هیچ رخداد rank_up‌ای نمی‌ساخت و جشن گم می‌شد
        old_idx_raw, _ = self._rank_for(u['effective_xp'])
        cap_old = max(self.CHALLENGE_FROM_IDX - 1,
                      self._rank_for(u['rank_floor_xp'])[0])
        old_idx = min(old_idx_raw, cap_old)
        old_div = int(u.get('prestige_div', 3) or 3) if old_idx == old_idx_raw else 1
        new_idx, new_div = self._rank_for(eff)
        # کلمپ: فراتر از کفِ رنک (و آستانه‌ی چالش) رنک صادر نمی‌شود؛
        # رویداد challenge_win کف را بالا می‌برد پس کلمپ هم همراهش باز می‌شود
        cap_idx = max(self.CHALLENGE_FROM_IDX - 1, self._rank_for(floor)[0])
        clamped_idx = min(new_idx, cap_idx)
        if clamped_idx < new_idx:
            new_div = 1                                # در سقف رنک آزاد می‌ایستد
        challenge_ready = new_idx > clamped_idx
        new_idx = clamped_idx
        overflow = (eff - self.PRESTIGE_RANKS[self.CHALLENGE_FROM_IDX][3]) if challenge_ready else 0
        upd2 = {'effective_xp': eff, 'prestige_div': new_div,
                'prestige_rank': self.PRESTIGE_RANKS[new_idx][0]}
        upd2['overflow_xp'] = overflow if overflow > 0 else 0
        await self.users.update_one({'user_id': uid}, {'$set': upd2})

        # ── رویدادهای ارتقا/رکورد/نشان
        events = {'streak_new_day': streak_new, 'challenge_ready': challenge_ready}
        if badge_awards:
            events['badges'] = badge_awards      # 👑 P1 — بازشدن نشان در این رویداد
        awarded_up = (new_idx > old_idx) or (new_idx == old_idx and new_div < old_div)
        if awarded_up:
            sh_a = int(n('shield_answers', self.SHIELD_ANSWERS))
            sets2 = {'shield_answers': sh_a,
                     'shield_until': (parse_gregorian_date(today) + timedelta(days=int(n('shield_days', self.SHIELD_DAYS)))).isoformat()}
            await self.users.update_one({'user_id': uid}, {'$set': sets2})
            u['shield_answers'] = sh_a
            u['shield_until'] = sets2['shield_until']
            shield_active = True                     # سپرِ تازه‌ِ اهدا شده در خروجی هم دیده شود
        if new_idx > old_idx:
            r_old, r_new = self.PRESTIGE_RANKS[old_idx], self.PRESTIGE_RANKS[new_idx]
            await self.users.update_one({'user_id': uid}, {'$set': {
                'rank_floor_xp': r_new[3], 'records.top_rank_key': r_new[0],
                'records.top_rank_at': today, 'records.top_div': new_div}})
            events['rank_up'] = {'from': r_old[1], 'to': r_new[1], 'icon': r_new[2], 'key': r_new[0]}
            await self._history_add(uid, 'rank_up', r_new[0], {'from': r_old[0], 'div': new_div})
            try:
                await self.inbox_add(uid, 'rank_up', f"🎉 ارتقای رنک: {r_new[2]} {r_new[1]}",
                    f'تبریک! به رنک {r_new[2]} {r_new[1]} رسیدی. سپر ارتقا فعال شد (۳۰ پاسخ).',
                    '/me/profile')
            except Exception:
                pass
            # نشان جهانی: اولین نفری که به این رنک برسد (اتمیک — §۴.۲)
            if await self._claim_global_first(f'first_rank_{r_new[0]}', uid):
                await self.users.update_one({'user_id': uid},
                    {'$set': {f'achievements.g_first_{r_new[0]}': {'at': utc_now_iso()}}})
                events['global_first'] = {'key': f'first_rank_{r_new[0]}', 'rank': r_new[1]}
                bonus_xp += await self._global_first_xp(uid, bdown)
                await self._history_add(uid, 'global_first', f'first_rank_{r_new[0]}', {'rank': r_new[1]})
                try:
                    await self.inbox_add(uid, 'global_first', '🏆 نشان جهانی تک‌نسخه!',
                        f'تو اولین نفری در تاریخ هامزیار هستی که به {r_new[2]} {r_new[1]} رسید!',
                        '/me/badges')
                except Exception:
                    pass
        elif new_idx == old_idx and new_div < old_div:
            r = self.PRESTIGE_RANKS[new_idx]
            # اوج دیویژن هم به‌روز می‌شود اگر در رنک برتر فعلی‌اش باشد
            if new_idx == self._rank_idx(u['records']['top_rank_key']) and new_div < u['records']['top_div']:
                await self.users.update_one({'user_id': uid},
                    {'$set': {'records.top_div': new_div}})
            events['div_up'] = {'rank': r[1], 'roman': self.ROMAN[new_div], 'icon': r[2]}
            await self._history_add(uid, 'div_up', r[0], {'div': new_div})
            try:
                await self.inbox_add(uid, 'div_up', f"⭐ ارتقای دسته: {r[2]} {r[1]} {self.ROMAN[new_div]}",
                    f'حالا {r[1]} {self.ROMAN[new_div]} هستی. سپر ارتقا فعال شد (۳۰ پاسخ).',
                    '/me/profile')
            except Exception:
                pass

        # ── مایل‌استون‌های استریک + نشان جهانی مرتبط
        cur_streak = u['streak_current']
        milestones = {3: 'ستریک سه‌روزه', 7: 'یک هفته‌ی پیاپی', 30: 'یک‌ماه آتشین',
                      90: 'فصل پیاپی', 180: 'نیم‌سال آتشین', 365: 'یک‌سال کامل'}
        if streak_new and cur_streak in milestones:
            await self._history_add(uid, 'streak', str(cur_streak), {})
            events['streak_milestone'] = cur_streak
            try:
                await self.inbox_add(uid, 'streak', f"🔥 استریک {cur_streak} روزه!",
                    f'{milestones[cur_streak]} — همین‌طور ادامه بده، زنجیره رو نشکن!',
                    '/me/profile')
            except Exception:
                pass
        if cur_streak >= 365 and await self._claim_global_first('first_streak365', uid):
            await self.users.update_one({'user_id': uid},
                {'$set': {'achievements.g_first_streak365': {'at': utc_now_iso()}}})
            events['global_first'] = {'key': 'first_streak365'}
            bonus_xp += await self._global_first_xp(uid, bdown)
            try:
                await self.inbox_add(uid, 'global_first', '🏆 نشان جهانی تک‌نسخه!',
                    'تو اولین صاحب استریک ۳۶۵ روزه در تاریخ هامزیار هستی!', '/me/badges')
            except Exception:
                pass
        if total_a >= 10000 and await self._claim_global_first('first_q10000', uid):
            await self.users.update_one({'user_id': uid},
                {'$set': {'achievements.g_first_q10000': {'at': utc_now_iso()}}})
            events['global_first'] = {'key': 'first_q10000'}
            bonus_xp += await self._global_first_xp(uid, bdown)
            try:
                await self.inbox_add(uid, 'global_first', '🏆 نشان جهانی تک‌نسخه!',
                    'تو اولین نفری هستی که مرز ۱۰٬۰۰۰ پاسخ را رد کرد!', '/me/badges')
            except Exception:
                pass

        if demoted:
            events['demote'] = demoted

        r = self.PRESTIGE_RANKS[new_idx]
        return {
            'ignored': False, 'kind': kind,
            'xp_gained': gain, 'bonus_xp': bonus_xp,
            'breakdown': [{'label': l, 'xp': x} for l, x in bdown if x > 0],
            'events': events,
            'streak': {'current': u['streak_current'], 'best': u['streak_best']},
            'shield': {'active': shield_active, 'answers_left': u['shield_answers']},
            'display': {'rank_key': r[0], 'title': r[1], 'icon': r[2], 'color': r[4],
                        'gradient': r[5],
                        'div': new_div, 'roman': self.ROMAN[new_div], 'stars': self.DIV_STARS[new_div]},
        }


    def _rank_idx(self, key: str) -> int:
        for i, r in enumerate(self.PRESTIGE_RANKS):
            if r[0] == key:
                return i
        return 0


    async def _apply_lazy_decay(self, u: dict, today: str, sets: dict):
        """Decay نرم درون‌رنکی (Spec §۳.۳) — idempotent با decay_blocks.
        فقط در غیاب سپر فعال؛ خروجی: dict رویداد demote یا None."""
        if not u['last_active_day']:
            return None
        if u['shield_answers'] > 0:
            return None
        idle_from = u['last_active_day']
        if u['shield_until'] and u['shield_until'] > idle_from:
            idle_from = u['shield_until']            # پنجره‌ی امنیت سپر لحاظ می‌شود
        try:
            days = (parse_gregorian_date(today) - parse_gregorian_date(idle_from)).days
        except Exception:
            return None
        # 👑 P3 — پنجره‌ی رکود قابل‌تنظیم زنده است (بدون ری‌دیپلوی)
        cfg = await self._pcfg()
        idle_days = int(self._cnum(cfg, 'decay_idle_days', self.DECAY_IDLE_DAYS))
        if days < idle_days:
            return None
        blocks = days // idle_days
        delta = blocks - u['decay_blocks']
        if delta <= 0:
            return None
        eff = u['prestige_xp'] - u['decay_penalty']
        floor = u['rank_floor_xp']
        from_idx, from_div = self._rank_for(max(eff, floor))
        to_idx, to_div = from_idx, from_div
        for _ in range(delta):
            if to_idx >= len(self.PRESTIGE_RANKS) - 1:
                break                                  # Apex ریزش نمی‌کند
            if to_div == 1:
                to_div = 2
            elif to_div == 2:
                to_div = 3
            else:
                break                                  # از III پایین‌تر نمی‌رویم
        start = self.PRESTIGE_RANKS[to_idx][3]
        w = self._div_width(to_idx)
        new_eff = max(start + (3 - to_div) * w, floor)
        win = eff - new_eff
        if win <= 0:
            sets['decay_blocks'] = blocks
            return None
        sets['decay_penalty'] = u['decay_penalty'] + win
        sets['decay_blocks'] = blocks
        sets['effective_xp'] = new_eff
        sets['prestige_div'] = to_div
        r = self.PRESTIGE_RANKS[to_idx]
        await self._history_add(u['user_id'], 'demote', r[0],
                                {'from_div': from_div, 'to_div': to_div, 'blocks': delta})
        try:
            await self.inbox_add(u['user_id'], 'demote', 'دیویژنت یک پله افتاد',
                f'به‌خاطر رکود اخیر، حالا {r[2]} {r[1]} {self.ROMAN[to_div]} هستی. '
                'رنکت محفوظ است — با چند سؤال برگرد 💪', '/me/profile')
        except Exception:
            pass
        return {'rank': r[1], 'icon': r[2], 'to_div': to_div,
                'roman': self.ROMAN[to_div], 'blocks': delta}


    async def _pc_total_active(self) -> int:
        """تعداد Active Users با کش ۱۰دقیقه‌ای (Spec §۳.۵/§۱۳ — per-request هرگز)"""
        try:
            doc = await self.settings.find_one({'_id': 'pc_cache'})
            now = now_utc().timestamp()
            if doc and (now - float(doc.get('computed_at', 0))) < self.PC_CACHE_TTL_SEC:
                return int(doc.get('total_active', 0))
            cutoff = (parse_gregorian_date(self._tehran_today())
                      - timedelta(days=self.ACTIVE_WINDOW_DAYS)).isoformat()
            total = await self.users.count_documents(
                {'approved': True, 'last_active_day': {'$gte': cutoff}})
            await self.settings.update_one(
                {'_id': 'pc_cache'},
                {'$set': {'total_active': total, 'computed_at': now}},
                upsert=True)
            return total
        except Exception:
            return 0


    async def prestige_state(self, uid: int, lite: bool = False) -> dict:
        """خواندن وضعیت نمایشی یکتا (Spec §۳.۴/§۳.۵/§۵) — بات/API/FE از همین می‌خورند.
        lite=True: بدون رقیب/رتبه‌ی عددی (مسیرهای ارزان مثل داشبورد بات)."""
        raw = await self.users.find_one({'user_id': uid})
        if not raw:
            return None
        u = self._puser(raw)
        today = self._tehran_today()
        sets = {}
        demoted = await self._apply_lazy_decay(u, today, sets)
        if sets:
            try:
                await self.users.update_one({'user_id': uid}, {'$set': sets})
            except Exception as _de:
                # 🛡 AUDIT-R6 — decay تنبلی که نوشته نشود، رنک نمایشی با
                # واقعیت زاویه می‌گیرد؛ لاگ می‌شود و دفعه‌ی بعد اعمال می‌شود.
                logger.warning(f"prestige lazy-decay write failed uid={uid}: {_de}")
            u.update(sets)
        eff = max(u['prestige_xp'] - u['decay_penalty'], u['rank_floor_xp'])
        idx, div = self._rank_for(eff)
        # کلمپ چالش با کفِ رنک به‌دست‌آمده (سازگار با P1: برد چالش، کف را بالا می‌برد)
        floor_idx, _ = self._rank_for(u['rank_floor_xp'])
        cap = max(self.CHALLENGE_FROM_IDX - 1, floor_idx)
        challenge_locked = idx > cap
        if challenge_locked:
            idx, div = cap, 1
        r = self.PRESTIGE_RANKS[idx]
        state = {
            'rank_key': r[0], 'rank_idx': idx, 'title': r[1], 'icon': r[2],
            'color': r[4], 'gradient': r[5],
            'div': div, 'roman': self.ROMAN[div], 'stars': self.DIV_STARS[div],
            'apex': idx == len(self.PRESTIGE_RANKS) - 1,
            'effective_xp': eff, 'prestige_xp': u['prestige_xp'],
            'next': self._next_info(idx, div, eff, challenge_locked),
            'shield': {'active': (u['shield_answers'] > 0) or
                                 (u['shield_until'] and u['shield_until'] >= today),
                       'answers_left': u['shield_answers'], 'until': u['shield_until']},
            'streak': {'current': u['streak_current'], 'best': u['streak_best']},
            'records': u['records'],
            'demoted': demoted,
        }
        start_next = (self.PRESTIGE_RANKS[idx + 1][3]
                      if idx < len(self.PRESTIGE_RANKS) - 1 else None)
        if not lite:
            total_active = await self._pc_total_active()
            state['total_active'] = total_active
            try:
                better = await self.users.count_documents({
                    'approved': True,
                    'last_active_day': {'$gte': (parse_gregorian_date(today)
                                                 - timedelta(days=self.ACTIVE_WINDOW_DAYS)).isoformat()},
                    'effective_xp': {'$gt': eff},
                })
            except Exception:
                better = 0
            state['rank_number'] = (better + 1) if total_active else None
            # Top% = ceil(rank/total*100) — Spec §۳.۵ (نورماتیو، نه round)
            rn = state['rank_number']
            state['top_pct'] = (max(1, (rn * 100 + total_active - 1) // total_active)
                                if total_active and rn else None)
            # رقیب بالا/پایین — با effective_xp (Spec §۳.۵/نکته‌ی ۸)
            async def _rival(cond, sort):
                try:
                    cur = self.users.find(
                        {'approved': True, 'user_id': {'$ne': uid}, **cond}
                    ).sort('effective_xp', sort).limit(1)
                    arr = await cur.to_list(1)
                    if not arr:
                        return None
                    v = arr[0]
                    gap = abs(int(v.get('effective_xp', 0) or 0) - eff)
                    return {'name': (v.get('name') or 'کاربر')
                                    if v.get('privacy_public', True) else 'یک دانشجو',
                            'gap': gap, 'icon': self.PRESTIGE_RANKS[
                                self._rank_for(int(v.get('effective_xp', 0) or 0))[0]][2]}
                except Exception:
                    return None
            state['rival_above'] = await _rival({'effective_xp': {'$gt': eff}}, 1)
            state['rival_below'] = await _rival({'effective_xp': {'$lt': eff}}, -1)
        if start_next and challenge_locked:
            state['overflow_xp'] = max(0, eff - start_next)
        # 👑 P1/P2 — نمای چالش (none/pending/ready/cooldown/locked) و شوکیس
        # در همان خروجی یکتای state تا بات/API/FE چیزی نسازند
        try:
            state['challenge'] = self._challenge_state_view(u, eff, today)
        except Exception:
            state['challenge'] = {'mode': 'none'}
        state['showcase_meta'] = self._showcase_meta(u)
        return state


    def _badge_seed_entries(self, ctx: dict) -> dict:
        """👑 P1 — بازنشانی سکوت نشان‌ها در Backfill (Spec §۱۴):
        نشان‌های قابل‌استناد از تاریخچه بدون **هیچ XP عقب‌گرد** ثبت می‌شوند
        (تعادل اقتصادی — ریپلای فقط XP پاسخ/آزمون است). از این لحظه به بعد
        موتور زنده، پله‌های بعدی را خودش باز می‌کند."""
        out = {}
        at = ctx.get('at') or utc_now_iso()
        for bkey, (icon, title, cname, tiers) in self.BADGES_PROG.items():
            try:
                value = int(ctx.get(cname, 0) or 0)
            except Exception:
                value = 0
            reached = 0
            for i, (target, _r, _x) in enumerate(tiers, 1):
                if value >= target:
                    reached = i
                else:
                    break
            if reached:
                out[bkey] = {'tier': reached, 'at': at, 'value': value,
                             'target': tiers[reached - 1][0]}
        for bkey, ok in (ctx.get('singles') or {}).items():
            if ok and bkey in self.BADGES_SINGLE:
                out[bkey] = {'at': at}
        return out


    async def prestige_backfill(self, pause: float = 0.02) -> dict:
        """P0 — محاسبه‌ی اولیه‌ی یک‌باره‌ی Prestige از تاریخچه (Spec §۱۴).
        Idempotent (prestige_migrated)؛ replay زمانی answers + آزمون‌های تمام‌شده
        + دانلودها؛ اعطای Founder؛ claim اتمیک Global Firsts؛ ریپورت فارسی.
        قانون ویژه‌ی Backfill: کاربران قدیمی رنک‌ها را **بدون چالش** می‌گیرند
        (grandfather — چالش قانون جدیدی است و نباید عطف‌به‌ماسبق شود)."""
        from utils import now_tehran
        today = now_tehran().date().isoformat()
        business_week = week_key_tehran(parse_gregorian_date(today))
        rep = {'scanned': 0, 'migrated': 0, 'founders': 0, 'firsts': [], 'errors': 0}
        sessions_coll = self.client['medicalbot']['exam_sessions']
        migrated = []
        try:
            cursor = self.users.find({'approved': True,
                                      'prestige_migrated': {'$ne': True}})
            users = await cursor.to_list(100000)
        except Exception as e:
            return {**rep, 'fatal': str(e)}
        for u in users:
            rep['scanned'] += 1
            uid = u.get('user_id')
            try:
                # ── replay زمانی پاسخ‌ها (تک‌پاس؛ ترتیب answered_at حفظ می‌شود)
                ans = await self.answers.find({'user_id': uid}).sort(
                    'answered_at', 1).to_list(100000)
                seen_q = set()
                rows = []             # [(date, qid, okc)] فقط پاسخ‌های «اولین‌بار»
                dates = set()         # هر تاریخ فعالیت (حتی تکراری → استریک)
                for a in ans:
                    qid = str(a.get('question_id') or '')
                    dstr = str(a.get('answered_at') or '')[:10]
                    if dstr:
                        dates.add(dstr)
                    if not qid or qid in seen_q:
                        continue
                    seen_q.add(qid)
                    rows.append((dstr, qid, bool(a.get('is_correct'))))
                # نقشه‌ی سختی سؤال‌ها (chunk ۲۰۰)
                diff_map = {}
                uniq_q = list({r[1] for r in rows})
                for i in range(0, len(uniq_q), 200):
                    oids = []
                    for q in uniq_q[i:i + 200]:
                        try:
                            oids.append(ObjectId(q))
                        except Exception:
                            pass
                    if not oids:
                        continue
                    docs = await self.questions.find({'_id': {'$in': oids}}).to_list(200)
                    for qd in docs:
                        diff_map[str(qd.get('_id'))] = qd.get('difficulty', '')
                # پاس دوم: قوانین روزانه (cap ۱۲۰ · diminishing ×۰٫۵ از ۴۰اُم صحیح)
                daily = {}            # date → {'amount','correct'}
                day_gain = {}
                for dstr, qid, okc in rows:
                    ent = daily.setdefault(dstr, {'amount': 0, 'correct': 0})
                    if okc:
                        base = self.XP_BY_DIFF[self._diff_key(diff_map.get(qid, ''))]
                        if ent['correct'] >= self.DIMINISH_AFTER:
                            base = max(1, base // 2)
                        ent['correct'] += 1
                    else:
                        base = self.XP_WRONG_FIRST
                    add = min(base, max(0, self.DAILY_ANSWER_CAP - ent['amount']))
                    ent['amount'] += add
                    day_gain[dstr] = day_gain.get(dstr, 0) + add
                for dstr in daily:     # +۱۰ فعالیت روزانه برای هر روز دارای پاسخ
                    day_gain[dstr] = day_gain.get(dstr, 0) + self.XP_DAILY_STREAK
                xp = sum(day_gain.values())
                # ── آزمون‌های تمام‌شده
                exams_completed = 0
                best_exam_pct = 0.0
                has_perfect = False
                has_pass20 = False
                try:
                    sess = await sessions_coll.find(
                        {'user_id': uid, 'status': 'finished'}).to_list(10000)
                except Exception:
                    sess = []
                for s in sess:
                    qs = s.get('question_ids') or []
                    total = len(qs)
                    cor = int(s.get('correct', 0) or 0)
                    answered = int(s.get('answered', total) or 0)
                    pct = round(cor / answered * 100, 1) if answered else 0
                    best_exam_pct = max(best_exam_pct, pct)
                    exams_completed += 1
                    if total >= 10 and pct >= 100:
                        has_perfect = True
                    if total >= 20 and pct >= 80:
                        has_pass20 = True
                    if total >= 10:
                        g = self.XP_EXAM_COMPLETE
                        if pct >= 100:
                            g += self.XP_EXAM_PERFECT
                        elif pct >= 80:
                            g += self.XP_EXAM_ACC_BONUS
                        finished_at = s.get('finished_at')
                        try:
                            fdate = to_tehran(finished_at).date().isoformat() if finished_at else ''
                        except (TypeError, ValueError):
                            fdate = ''
                        day_gain[fdate] = day_gain.get(fdate, 0) + g
                        xp += g
                        if fdate:
                            dates.add(fdate)
                # ── دانلودها
                try:
                    downloads = await self.stats_col.count_documents({
                        'user_id': uid,
                        'action': {'$in': ['bs_download', 'ref_download', 'qbank_download']}})
                except Exception:
                    downloads = 0
                # 👑 P1 — شمارنده‌های مشارکت (طرح سؤال تأییدشده / گزارش مفید)
                try:
                    subs_ok = await self.questions.count_documents(
                        {'creator_id': uid, 'approved': True})
                except Exception:
                    subs_ok = 0
                try:
                    reps_ok = await self.content_reports.count_documents(
                        {'reporter_id': uid, 'status': 'resolved'})
                except Exception:
                    reps_ok = 0
                # ── استریک از روزهای فعال (متوالی‌ترین دنباله + دنباله‌ی پایانی)
                sorted_days = sorted(d for d in dates if d)
                best_run = 0
                run = 0
                prev = None
                for d in sorted_days:
                    if prev and (parse_gregorian_date(d) - parse_gregorian_date(prev)).days == 1:
                        run += 1
                    else:
                        run = 1
                    best_run = max(best_run, run)
                    prev = d
                tail = 0
                if sorted_days:
                    last = sorted_days[-1]
                    if last >= (now_tehran().date() - timedelta(days=1)).isoformat():
                        tail = 1
                        for i in range(len(sorted_days) - 1, 0, -1):
                            if (parse_gregorian_date(sorted_days[i])
                                    - parse_gregorian_date(sorted_days[i - 1])).days == 1:
                                tail += 1
                            else:
                                break
                # ── رنک بدون چالش (grandfather)
                idx, div = self._rank_for(xp)
                floor = self.PRESTIGE_RANKS[idx][3]
                week_gain = sum(g for d, g in day_gain.items()
                                if d and d[:4] == today[:4]
                                and week_key_tehran(parse_gregorian_date(d)) == business_week) if day_gain else 0
                total_a = int(u.get('total_answers', 0) or 0)
                corr_a = int(u.get('correct_answers', 0) or 0)
                acc = round(corr_a / total_a * 100) if total_a else 0
                registered_at = u.get('registered_at')
                last_gain = max(sorted_days) if sorted_days else ''
                try:
                    founder_at = parse_machine_datetime(registered_at).isoformat() if registered_at else utc_now_iso()
                except (TypeError, ValueError):
                    founder_at = utc_now_iso()
                # 👑 P1 — بازنشانی نشان‌ها از شواهد تاریخی (بدون XP عقب‌گرد)
                any_day30 = any(int(e.get('correct', 0) or 0) >= 30
                                for e in daily.values())
                seeded = self._badge_seed_entries({
                    'at': founder_at,
                    'total_answers': total_a, 'streak_best': best_run,
                    'exams_completed': exams_completed,
                    'downloads_count': downloads, 'ai_conv_days': 0,
                    'singles': {
                        'q_first': total_a >= 1,
                        'e_first': exams_completed >= 1,
                        'e_pass20': has_pass20, 'exam_perfect': has_perfect,
                        'acc70': total_a >= 100 and corr_a * 100 >= total_a * 70,
                        'acc80': total_a >= 100 and corr_a * 100 >= total_a * 80,
                        'acc90': total_a >= 100 and corr_a * 100 >= total_a * 90,
                        'c_first_design': subs_ok >= 1,
                        'c_first10': subs_ok >= 10,
                        'c_first_report': reps_ok >= 1,
                        'c_reports10': reps_ok >= 10,
                        'a_q5000': total_a >= 5000,
                        'a_s365': best_run >= 365,
                        'x_30day': any_day30, 'x_week300': week_gain >= 300,
                    },
                })
                await self.users.update_one({'user_id': uid}, {'$set': {
                    'prestige_xp': xp, 'season_xp': xp, 'weekly_xp': week_gain,
                    'weekly_reset': business_week, 'effective_xp': xp,
                    'prestige_rank': self.PRESTIGE_RANKS[idx][0], 'prestige_div': div,
                    'rank_floor_xp': floor, 'decay_penalty': 0, 'decay_blocks': 0,
                    'overflow_xp': 0,
                    'daily_xp': {'date': today, 'amount': 0, 'correct': 0},
                    'last_active_day': last_gain, 'last_gain_at': last_gain,
                    'streak_current': tail, 'streak_best': best_run,
                    'exams_completed': exams_completed, 'downloads_count': downloads,
                    'submissions_approved': subs_ok, 'reports_resolved': reps_ok,
                    'records': {'best_acc': acc, 'best_exam_pct': best_exam_pct,
                                'top_rank_key': self.PRESTIGE_RANKS[idx][0],
                                'top_rank_at': today, 'top_div': div,
                                'top1_weeks_current': 0, 'top1_weeks_best': 0},
                    'achievements': {**(u.get('achievements') or {}),
                                     'f_founder': {'at': founder_at}, **seeded},
                    'privacy_public': u.get('privacy_public', True),
                    'showcase': u.get('showcase', []),
                    'shield_answers': 0, 'shield_until': '',
                    'prestige_migrated': True,
                }})
                await self._history_add(uid, 'founder', 'f_founder',
                                        {'rank': self.PRESTIGE_RANKS[idx][0], 'xp': xp})
                try:
                    await self.inbox_add(uid, 'founder', '🏛 نشان بنیان‌گذار هامزیار',
                        f'از نخستین اعضای پلتفرمی! نشان ابدی بنیان‌گذار ثبت شد. '
                        f'رنک اولیه‌ت: {self.PRESTIGE_RANKS[idx][2]} {self.PRESTIGE_RANKS[idx][1]} '
                        f'({xp} XP از تاریخچه‌ی فعالیتت)', '/me/badges')
                except Exception:
                    pass
                rep['founders'] += 1
                rep['migrated'] += 1
                # 🛡 AUDIT-B1 — `reg` هرگز تعریف نشده بود: NameError داخل این
                # try بلافاصله به `except Exception: rep['errors'] += 1`
                # می‌رفت، یعنی هر ردیف مهاجرت «خطا» حساب می‌شد و `migrated`
                # خالی می‌ماند (Global Firsts پایین‌تر هیچ کاندیدی نمی‌دید).
                migrated.append({'uid': uid, 'xp': xp, 'idx': idx, 'reg': registered_at,
                                 'total_answers': total_a, 'streak_best': best_run})
                if pause:
                    await asyncio.sleep(pause)
            except Exception:
                rep['errors'] += 1
        # ── Global Firsts: بای اس تاریخی تقریبی (زودترین عضو واجد شرط)
        def _claim_of(cands, key):
            if not cands:
                return None
            win = min(cands, key=lambda c: (c['reg'] or '9999', c['uid']))
            return key, win
        first_defs = []
        for i, r in enumerate(self.PRESTIGE_RANKS):
            if i == 0:
                continue  # rookie برای همه است — «اولین rookie» معنایی ندارد
            cand = [m for m in migrated if m['xp'] >= r[3]]
            if cand:
                first_defs.append(_claim_of(cand, f'first_rank_{r[0]}'))
        q10 = [m for m in migrated if m['total_answers'] >= 10000]
        if q10:
            first_defs.append(_claim_of(q10, 'first_q10000'))
        st365 = [m for m in migrated if m['streak_best'] >= 365]
        if st365:
            first_defs.append(_claim_of(st365, 'first_streak365'))
        for item in first_defs:
            if not item:
                continue
            key, win = item
            if await self._claim_global_first(key, win['uid']):
                await self.users.update_one({'user_id': win['uid']},
                    {'$set': {f'achievements.g_first_{key.replace("first_rank_", "")}':
                              {'at': utc_now_iso()}}})
                await self._history_add(win['uid'], 'global_first', key, {})
                rep['firsts'].append({'key': key, 'uid': win['uid']})
        return rep


    # ══════════════════════════════════════════════════
    #  👑 Prestige P1/P2 — نشان‌ها/چالش/لیدربرد/فید/هفته
    #  (همچنان تک‌موتور؛ همه‌ی قوانین از ثابت‌های بالای کلاس)
    # ══════════════════════════════════════════════════

    async def _season_key(self) -> str:
        """کلید سيزن فعلی از settings (کش پردازه‌ای ۶۰ ثانیه‌ای)"""
        import time as _t
        c = getattr(self, '_skc', None)
        if c and _t.time() - c['at'] < 60:
            return c['key']
        try:
            doc = await self.settings.find_one({'_id': 'season'})
            key = (doc or {}).get('key') or 'S1-1405'
        except Exception:
            key = 'S1-1405'
        self._skc = {'key': key, 'at': _t.time()}
        return key


    async def _season_info(self) -> dict:
        key = await self._season_key()
        try:
            doc = await self.settings.find_one({'_id': 'season'})
        except Exception:
            doc = None
        return {'key': key,
                'label': (doc or {}).get('label') or 'سیزن ۱ · ۱۴۰۵',
                'active': bool((doc or {}).get('active', True))}


    # ─── 👑 P3 — تنظیمات زنده‌ی تعادل (بدون ری‌دیپلوی — Spec §۱۷) ───

    async def _pcfg(self) -> dict:
        """اوررایدهای prestige_config از settings (کش پردازه‌ای ۶۰ ثانیه).
        فقط مقادیر XP/سقف/کول‌داون/سپر — آستانه‌ی رنک‌ها هرگز قابل‌اورراید نیست."""
        import time as _t
        c = getattr(self, '_pcfgc', None)
        if c and _t.time() - c['at'] < 60:
            return c['cfg']
        try:
            doc = await self.settings.find_one({'_id': 'prestige_config'})
            ov = (doc or {}).get('values') or {}
            if not isinstance(ov, dict):
                ov = {}
        except Exception:
            ov = {}
        self._pcfgc = {'cfg': ov, 'at': _t.time()}
        return ov


    @staticmethod
    def _cnum(cfg: dict, key: str, default):
        """خواندن عددی امن از اوررایدها؛ مقدار بد/ناموجود ⇒ پیش‌فرض کلاس"""
        try:
            v = cfg.get(key)
            if v is None:
                return default
            return float(v)
        except Exception:
            return default


    async def prestige_challenge_stats(self) -> dict:
        """👑 P3 — پایش چالش (پنل ادمین): شروع/برد/شکست امروز + در جریان"""
        today = self._tehran_today()
        try:
            started = await self.exam_sessions.count_documents(
                {'promotion': True, 'started_at': {'$gte': today}})
        except Exception:
            started = 0
        try:
            wins = await self.prestige_history.count_documents(
                {'type': 'challenge_win', 'at': {'$gte': today}})
        except Exception:
            wins = 0
        try:
            fails = await self.prestige_history.count_documents(
                {'type': 'challenge_fail', 'at': {'$gte': today}})
        except Exception:
            fails = 0
        try:
            pending = await self.exam_sessions.count_documents(
                {'promotion': True, 'status': 'active'})
        except Exception:
            pending = 0
        return {'started_today': started, 'wins_today': wins,
                'fails_today': fails, 'pending_now': pending}


    async def _global_first_xp(self, uid: int, bdown: list) -> int:
        """اعطای XP باستانی نشان جهانی (۵۰۰) رخ-بعداز-نوشت اصلی — جبران $inc"""
        xp = self.BADGE_RARITY['ancient'][2]
        try:
            await self.users.update_one({'user_id': uid},
                {'$inc': {'prestige_xp': xp, 'season_xp': xp,
                          'weekly_xp': xp, 'monthly_xp': xp}})
            bdown.append(('نشان جهانی تک‌نسخه 🏆', xp))
        except Exception:
            return 0
        return xp


    async def _award_global(self, uid: int, key: str, sets: dict,
                            bdown: list, badge_awards: list, label: str) -> int:
        """ادعای اتمیک + اعطای نشان جهانی جدید (داخل پنجره‌ی پیش‌از-نوشت رویداد)"""
        if not await self._claim_global_first(key, uid):
            return 0
        xp = self.BADGE_RARITY['ancient'][2]
        sets[f'achievements.g_first_{key.replace("first_", "")}'] = \
            {'at': utc_now_iso()}
        bdown.append((f"🏆 نشان جهانی: {label}", xp))
        badge_awards.append({'key': f'g_first_{key.replace("first_", "")}',
                             'icon': '🏆', 'title': label,
                             'rarity': 'ancient', 'xp': xp})
        await self._history_add(uid, 'global_first', key, {'label': label})
        try:
            await self.inbox_add(uid, 'global_first', '🏆 نشان جهانی تک‌نسخه!',
                f'تو اولین نفری در تاریخ هامزیار هستی که به «{label}» رسید!',
                '/me/badges')
        except Exception:
            pass
        return xp


    async def _badge_scan(self, uid: int, u: dict, raw: dict, inc: dict,
                          sets: dict, bdown: list, badge_awards: list,
                          ctx: dict) -> int:
        """جاروی نشان‌ها — خروجی: جمع XP اعطایی (خارج از سقف).
        پله‌ها یک‌در هر رویداد جلو می‌روند (ضدسیل)، تک‌نسخه‌ها هم‌زمان."""
        xp_total = 0
        ach = u.get('achievements') or {}
        # پاسخِ در‌حالِ ثبت (prestige_event پیش از save_answer صدا زده می‌شود)
        # در شمارنده‌های نشان لحاظ می‌شود تا آستانه‌ها off-by-one نشوند
        kind = ctx.get('kind')
        meta = ctx.get('meta') or {}
        inflight = 1 if kind == 'answer' else 0
        total_a = int(raw.get('total_answers', 0) or 0) + inflight
        corr_a = int(raw.get('correct_answers', 0) or 0) + \
            (inflight if meta.get('is_correct') else 0)
        counters = {
            'total_answers': total_a,
            'streak_best': int(sets.get('streak_best', u.get('streak_best', 0) or 0)),
            'exams_completed': int(u.get('exams_completed', 0) or 0)
                               + int(inc.get('exams_completed', 0) or 0),
            'downloads_count': int(u.get('downloads_count', 0) or 0)
                               + int(inc.get('downloads_count', 0) or 0),
            'ai_conv_days': len(sets.get('ai_conv_days', u.get('ai_conv_days') or [])),
            'submissions': int(u.get('submissions_approved', 0) or 0)
                           + int(inc.get('submissions_approved', 0) or 0),
            'reports': int(u.get('reports_resolved', 0) or 0)
                       + int(inc.get('reports_resolved', 0) or 0),
        }
        now_iso = utc_now_iso()

        # ── ۵ نشان تکاملی (فقط یک پله‌ی جلو در هر رویداد)
        for bkey, (icon, title, cname, tiers) in self.BADGES_PROG.items():
            cur_tier = int((ach.get(bkey) or {}).get('tier', 0) or 0)
            value = counters.get(cname, 0)
            reached = 0
            for i, (target, _r, _x) in enumerate(tiers, 1):
                if value >= target:
                    reached = i
                else:
                    break
            if reached <= cur_tier or cur_tier >= len(tiers):
                continue
            nxt = cur_tier + 1
            target, rarity, xp = tiers[nxt - 1]
            sets[f'achievements.{bkey}'] = {'tier': nxt, 'at': now_iso,
                                            'value': value, 'target': target}
            bdown.append((f"نشان {icon} {title} · پله {nxt}", xp))
            xp_total += xp
            badge_awards.append({'key': bkey, 'icon': icon, 'title': title,
                                 'rarity': rarity, 'xp': xp, 'tier': nxt,
                                 'tiers_count': len(tiers)})
            await self._history_add(uid, 'achievement', bkey,
                                    {'tier': nxt, 'rarity': rarity, 'value': value})
            try:
                await self.inbox_add(uid, 'achievement',
                    f"{icon} نشان جدید: {title} — پله {nxt}",
                    f"پله {nxt} از {len(tiers)} ({self.BADGE_RARITY[rarity][0]}) باز شد؛ {xp}+ XP 🎉",
                    '/me/badges')
            except Exception:
                pass

        # ── تک‌نسخه‌های مشروط (kind/meta از ابتدای جارو)
        daily = ctx.get('daily') or {}
        exam_total = int(meta.get('total') or 0)
        exam_pct = float(meta.get('pct') or 0)
        from utils import now_tehran
        hour = now_tehran().hour
        weekly_after = float(ctx.get('weekly_xp_after') or 0)
        conds = {
            'q_first': total_a >= 1,
            'e_first': counters['exams_completed'] >= 1,
            'ai_first': counters['ai_conv_days'] >= 1,
            'e_pass20': kind == 'exam_complete' and exam_total >= 20 and exam_pct >= 80,
            'exam_perfect': kind == 'exam_complete' and exam_total >= 10 and exam_pct >= 100,
            'lesson_done': kind == 'file_download' and bool(meta.get('lesson_done')),
            'ai_image': kind == 'ai_feature' and meta.get('feature') == 'image',
            'ai_pdf': kind == 'ai_feature' and meta.get('feature') == 'pdf',
            'acc70': total_a >= 100 and corr_a * 100 >= total_a * 70,
            'acc80': total_a >= 100 and corr_a * 100 >= total_a * 80,
            'acc90': total_a >= 100 and corr_a * 100 >= total_a * 90,
            'c_first_design': counters['submissions'] >= 1,
            'c_first10': counters['submissions'] >= 10,
            'c_first_report': counters['reports'] >= 1,
            'c_reports10': counters['reports'] >= 10,
            'x_owl': 0 <= hour <= 3,
            'x_lark': 5 <= hour <= 7,
            'x_30day': int(daily.get('correct', 0) or 0) >= 30,
            'x_comeback': int(ctx.get('return_idle_days') or 0) >= 14,
            'x_week300': weekly_after >= 300,
            'a_q5000': total_a >= 5000,
            'a_s365': counters['streak_best'] >= 365,
        }
        for bkey, ok in conds.items():
            if not ok or bkey in ach:
                continue
            info = self.BADGES_SINGLE[bkey]
            sets[f'achievements.{bkey}'] = {'at': now_iso}
            xp = int(info['xp'])
            if xp > 0:
                bdown.append((f"نشان {info['icon']} {info['title']}", xp))
            xp_total += xp
            badge_awards.append({'key': bkey,
                                 **{k: info[k] for k in ('icon', 'title', 'rarity', 'xp')}})
            await self._history_add(uid, 'achievement', bkey, {'rarity': info['rarity']})
            try:
                await self.inbox_add(uid, 'achievement',
                    f"{info['icon']} نشان جدید: {info['title']}",
                    f"{info['desc']} — {xp}+ XP 🎉" if xp > 0 else info['desc'],
                    '/me/badges')
            except Exception:
                pass

        # ── جهانی‌های جدید (اتمیک — Spec §۴.۲)
        if kind == 'exam_complete' and exam_total >= 10 and exam_pct >= 100:
            xp_total += await self._award_global(
                uid, 'first_perfect', sets, bdown, badge_awards,
                'اولین آزمون برگ‌کامل')
        if counters['submissions'] >= 10:
            xp_total += await self._award_global(
                uid, 'first_contrib10', sets, bdown, badge_awards,
                'اولین ۱۰ مشارکت تأییدشده')
        return xp_total


    # ───────── چالش ارتقا (Spec §۳.۱) ─────────

    def _challenge_state_view(self, u: dict, eff: int, today: str) -> dict:
        """وضعیت چالش کاربر — none|pending|ready|cooldown|locked (Spec §۳.۴)"""
        floor_idx = self._rank_for(u['rank_floor_xp'])[0]
        target_idx = floor_idx + 1
        if target_idx >= len(self.PRESTIGE_RANKS):
            return {'mode': 'none'}
        if target_idx < self.CHALLENGE_FROM_IDX:
            return {'mode': 'none'}               # سه رنک اول بدون چالش
        r = self.PRESTIGE_RANKS[target_idx]
        apex = target_idx == len(self.PRESTIGE_RANKS) - 1
        start = r[3]
        base = {'target_rank': r[0], 'title': r[1], 'icon': r[2],
                'apex': apex, 'start': start}
        if eff < start:
            return {'mode': 'pending', **base, 'needed_xp': start - eff}
        ch = u.get('challenge') or {}
        cd_until = ch.get('cooldown_until') or ''
        now_iso = utc_now_iso()
        if cd_until and cd_until > now_iso:
            return {'mode': 'cooldown', **base,
                    'cooldown_until': cd_until, 'overflow_xp': max(0, eff - start)}
        if apex:
            streak_ok = int(u.get('streak_best', 0) or 0) >= self.CH_APEX_STREAK_REQ
            contrib_ok = int(u.get('submissions_approved', 0) or 0) >= self.CH_APEX_CONTRIB_REQ
            if not (streak_ok and contrib_ok):
                return {'mode': 'locked', **base,
                        'overflow_xp': max(0, eff - start),
                        'need': {'streak_best': self.CH_APEX_STREAK_REQ,
                                 'contrib': self.CH_APEX_CONTRIB_REQ},
                        'have': {'streak_best': int(u.get('streak_best', 0) or 0),
                                 'contrib': int(u.get('submissions_approved', 0) or 0)}}
        return {'mode': 'ready', **base, 'overflow_xp': max(0, eff - start)}


    async def challenge_pool(self, uid: int, apex: bool = False):
        """استخر سؤال چالش — pool-200 + fallback پنجره‌ها + mixin ≥۴۰٪ (Spec §۳.۱)"""
        import random
        need = self.CH_APEX_COUNT if apex else self.CH_COUNT
        cur = self.answers.find({'user_id': uid}).sort('answered_at', -1) \
            .limit(self.CH_EXCLUDE_RECENT)
        ans = await cur.to_list(self.CH_EXCLUDE_RECENT)
        recent = []
        seen = set()
        for a in ans:
            q = str(a.get('question_id') or '')
            if q and q not in seen:
                seen.add(q)
                recent.append(q)
        windows = [self.CH_EXCLUDE_RECENT] + list(self.CH_EXCLUDE_FALLBACK)
        selected = None
        used_window = windows[-1]
        # 🌊 C1.5 — استخر چالش فقط در scope دید کاربر (سراسری + ورودی خودش)؛
        # قبلاً روی کل بانک (همه‌ی ورودی‌ها) کوئری می‌زد.
        _pu = await self.get_user(uid)
        _pscope = {'approved': True}
        _pscope.update(self._intake_q(
            self.student_intake_filter((_pu or {}).get('intake', ''))))
        for w in windows:
            excluded = set(recent[:w])
            docs = await self.questions.find(_pscope).to_list(5000)
            pool = [d for d in docs if str(d.get('_id')) not in excluded]
            if len(pool) >= need:
                selected = pool
                used_window = w
                break
        if selected is None:
            logger.warning(f"challenge_pool: استخر ناکافی برای {uid} "
                           f"(حتی با پنجره‌ی {used_window})")
            return None, {'window': used_window}
        buckets = {'easy': [], 'medium': [], 'hard': [], 'unknown': []}
        for d in selected:
            buckets[self._diff_key(d.get('difficulty'))].append(d)
        for b in buckets.values():
            random.shuffle(b)
        # سقف‌گذاری به بالا: حداقل ۴۰٪ متوسط+سخت (ceilِ امن)
        mix_min = max(1, int(round(need * self.CH_MIX_MIN_HARDMED + 0.4999)))
        mix = buckets['medium'] + buckets['hard']
        random.shuffle(mix)
        take = mix[:mix_min]
        taken_ids = {str(d.get('_id')) for d in take}
        rest = [d for d in (buckets['easy'] + buckets['unknown'] +
                            buckets['medium'] + buckets['hard'])
                if str(d.get('_id')) not in taken_ids]
        random.shuffle(rest)
        chosen = take + rest[:need - len(take)]
        random.shuffle(chosen)
        fallback_hit = used_window != self.CH_EXCLUDE_RECENT
        if fallback_hit:
            logger.warning(f"challenge_pool fallback: window {used_window} برای {uid}")
        return [str(d.get('_id')) for d in chosen], \
            {'window': used_window, 'mix_hardmed': min(len(take), need),
             'fallback': fallback_hit}


    async def challenge_start_check(self, uid: int) -> dict:
        """واجد‌شرط‌بودن شروع چالش — خروجی dict برای روتر (قرارداد §۱۵/§۱۲)"""
        raw = await self.users.find_one({'user_id': uid})
        if not raw or not raw.get('approved'):
            return {'ok': False, 'code': 'not_approved'}
        u = self._puser(raw)
        today = self._tehran_today()
        sets = {}
        await self._apply_lazy_decay(u, today, sets)
        if sets:
            try:
                await self.users.update_one({'user_id': uid}, {'$set': sets})
            except Exception as _de:
                # 🛡 AUDIT-R6 — decay تنبلی که نوشته نشود، رنک نمایشی با
                # واقعیت زاویه می‌گیرد؛ لاگ می‌شود و دفعه‌ی بعد اعمال می‌شود.
                logger.warning(f"prestige lazy-decay write failed uid={uid}: {_de}")
            u.update(sets)
        eff = max(u['prestige_xp'] - u['decay_penalty'], u['rank_floor_xp'])
        view = self._challenge_state_view(u, eff, today)
        mode = view['mode']
        if mode != 'ready':
            out = {'ok': False, 'code': mode, 'view': view}
            if mode == 'cooldown':
                try:
                    rem = parse_machine_datetime(view['cooldown_until']) - now_utc()
                    out['hours_left'] = max(1, int(-(-rem.total_seconds() // 3600)))
                except Exception:
                    out['hours_left'] = None
            return out
        sess = await self.exam_sessions.find_one(
            {'user_id': uid, 'promotion': True, 'status': 'active'})
        if sess:
            # چک TTL: جلسه‌ی منقضی = Fail خودکار + کول‌داون (ضدتقلب)؛
            # ⚠️ بلافاصله کول‌داون برگردان — اجازه‌ی شروع تازه در همان نفس نیست
            exp = sess.get('expires_ts')
            if exp and int(now_utc().timestamp()) >= int(exp):
                await self.challenge_expire_session(sess)
                raw2 = await self.users.find_one({'user_id': uid}) or {}
                until = str((raw2.get('challenge') or {}).get('cooldown_until') or '')
                out = {'ok': False, 'code': 'cooldown', 'expired_ttl': True,
                       'cooldown_until': until, 'view': view}
                try:
                    rem = parse_machine_datetime(until) - now_utc()
                    out['hours_left'] = max(1, int(-(-rem.total_seconds() // 3600)))
                except Exception:
                    out['hours_left'] = None
                return out
            return {'ok': True, 'resume': True,
                    'session_id': sess.get('session_id'), 'view': view}
        apex = bool(view.get('apex'))
        pool, pmeta = await self.challenge_pool(uid, apex)
        need = self.CH_APEX_COUNT if apex else self.CH_COUNT
        if not pool or len(pool) < need:
            return {'ok': False, 'code': 'insufficient_pool', 'view': view,
                    'pool_meta': pmeta}
        return {'ok': True, 'resume': False, 'pool': pool, 'view': view,
                'pool_meta': pmeta, 'apex': apex}


    async def challenge_expire_session(self, sess: dict) -> None:
        """TTL/رهاکردن چالش = Fail + کول‌داون (ضدتقلب — Spec §۳.۱)"""
        try:
            await self.exam_sessions.update_one(
                {'_id': sess['_id']},
                {'$set': {'status': 'failed',
                          'finished_at': utc_now_iso()}})
        except Exception:
            pass
        uid = sess.get('user_id')
        answered = int(sess.get('answered', 0) or 0)
        correct = int(sess.get('correct', 0) or 0)
        pct = round(correct / answered * 100, 1) if answered else 0
        await self.challenge_resolve(uid, sess, False, pct)


    async def challenge_resolve(self, uid: int, session: dict,
                                won: bool, pct: float) -> dict:
        """نتیجه‌ی سرورمحور چالش (Spec §۱۵ — کلاینت فقط state می‌خواند)"""
        target_key = session.get('target_rank') or ''
        apex = bool(session.get('apex'))
        target_idx = self._rank_idx(target_key)
        if won:
            ev = await self.prestige_event(uid, 'challenge_win',
                                           {'target_idx': target_idx,
                                            'apex': apex, 'pct': pct})
            return {'win': True, 'pct': pct, 'event': ev,
                    'celebration': (ev.get('events') or {}).get('rank_up')}
        # 👑 P3 — کول‌داون قابل‌تنظیم زنده (پیش‌فرض: ۱۲عادی / ۴۸Apex)
        _cfgc = await self._pcfg()
        cooldown_h = (int(self._cnum(_cfgc, 'challenge_cooldown_apex_h',
                                     self.CH_APEX_COOLDOWN_H)) if apex
                      else int(self._cnum(_cfgc, 'challenge_cooldown_h',
                                          self.CH_COOLDOWN_H)))
        until = (now_utc() + timedelta(hours=cooldown_h)).isoformat()
        await self.users.update_one({'user_id': uid}, {'$set': {
            'challenge.target_rank': target_key, 'challenge.apex': apex,
            'challenge.cooldown_until': until,
            'challenge.last_fail_at': utc_now_iso()}})
        await self._history_add(uid, 'challenge_fail', target_key,
                                {'pct': pct, 'cooldown_h': cooldown_h})
        try:
            await self.inbox_add(uid, 'challenge_fail', 'نزدیک بود 💪',
                f'این بار نشد ({pct}٪). هیچ جریمه‌ای نیست — '
                f'{cooldown_h} ساعت دیگر دوباره می‌تونی.', '/learn/exams?promo=1')
        except Exception:
            pass
        return {'win': False, 'pct': pct,
                'cooldown_until': until, 'cooldown_h': cooldown_h}


    # ───────── کلکسیون نشان‌ها (Spec §۴) ─────────

    def _badge_meta(self, key: str, u: dict):
        ach = (u or {}).get('achievements') or {}
        if key in self.BADGES_PROG:
            icon, title, _c, tiers = self.BADGES_PROG[key]
            tier = int((ach.get(key) or {}).get('tier', 0) or 0)
            rarity = tiers[tier - 1][1] if tier else 'common'
            return {'key': key, 'icon': icon, 'title': title, 'rarity': rarity,
                    'tier': tier, 'tiers_count': len(tiers),
                    'color': self.BADGE_RARITY[rarity][1]}
        if key in self.BADGES_SINGLE:
            info = self.BADGES_SINGLE[key]
            return {'key': key,
                    **{k: info[k] for k in ('icon', 'title', 'rarity')},
                    'color': self.BADGE_RARITY[info['rarity']][1]}
        if key.startswith('g_first'):
            labels = {'g_first_q10000': ('🏆', 'اولین ۱۰٬۰۰۰ پاسخ'),
                      'g_first_streak365': ('🕯', 'اولین استریک ۳۶۵'),
                      'g_first_perfect': ('🎯', 'اولین آزمون برگ‌کامل'),
                      'g_first_contrib10': ('🏛', 'اولین ۱۰ مشارکت'),
                      'g_first_founder': ('🏛', 'بنیان‌گذار جهانی')}
            if key in labels:
                icon, title = labels[key]
            else:
                rk = key.replace('g_first_', '')
                idx = self._rank_idx(rk)
                r = self.PRESTIGE_RANKS[idx]
                icon, title = r[2], f'اولین {r[1]}'
            return {'key': key, 'icon': icon, 'title': title,
                    'rarity': 'ancient', 'color': self.BADGE_RARITY['ancient'][1]}
        return None


    def _showcase_meta(self, u: dict) -> list:
        out = []
        for key in (u.get('showcase') or [])[:self.SHOWCASE_MAX]:
            m = self._badge_meta(key, u)
            if m:
                out.append(m)
        return out


    async def prestige_showcase_set(self, uid: int, keys: list) -> dict:
        """📌 پین حداکثر ۳ نشان بازشده (Spec §۴.۴) — اعتبارسنجی سروری"""
        raw = await self.users.find_one({'user_id': uid})
        if not raw:
            return {'ok': False, 'code': 'not_found'}
        u = self._puser(raw)
        ach = u.get('achievements') or {}
        clean, rejected = [], []
        for k in (keys or [])[:self.SHOWCASE_MAX]:
            k = str(k).strip()
            if k and k in ach and self._badge_meta(k, u):
                clean.append(k)
            else:
                rejected.append(k)
        await self.users.update_one({'user_id': uid},
                                    {'$set': {'showcase': clean}})
        return {'ok': True, 'showcase': self._showcase_meta({**u, 'showcase': clean}),
                'rejected': rejected}


    async def prestige_badges(self, uid: int) -> dict:
        """کلکسیون کامل برای صفحه‌ی نشان‌ها (Spec §۴.۳)"""
        raw = await self.users.find_one({'user_id': uid})
        if not raw:
            return None
        u = self._puser(raw)
        ach = u.get('achievements') or {}
        counters = {
            'total_answers': int(raw.get('total_answers', 0) or 0),
            'streak_best': int(u.get('streak_best', 0) or 0),
            'exams_completed': int(u.get('exams_completed', 0) or 0),
            'ai_conv_days': len(u.get('ai_conv_days') or []),
            'downloads_count': int(u.get('downloads_count', 0) or 0),
        }
        progressive = []
        for bkey, (icon, title, cname, tiers) in self.BADGES_PROG.items():
            cur_tier = int((ach.get(bkey) or {}).get('tier', 0) or 0)
            value = counters.get(cname, 0)
            nxt = tiers[cur_tier] if cur_tier < len(tiers) else None
            rarity = tiers[cur_tier - 1][1] if cur_tier else 'common'
            progressive.append({
                'key': bkey, 'icon': icon, 'title': title,
                'tier': cur_tier, 'tiers_count': len(tiers),
                'rarity': rarity, 'color': self.BADGE_RARITY[rarity][1],
                'value': value,
                'next_target': nxt[0] if nxt else None,
                'next_xp': nxt[2] if nxt else None,
                'tiers': [{'target': t, 'rarity': r, 'xp': x} for t, r, x in tiers],
            })
        singles = []
        for bkey, info in self.BADGES_SINGLE.items():
            if bkey == 'f_founder':
                secret_locked = False
            else:
                secret_locked = info.get('secret') and bkey not in ach
            item = {
                'key': bkey, 'kind': info['kind'],
                'rarity': info['rarity'], 'xp': info['xp'],
                'color': self.BADGE_RARITY[info['rarity']][1],
            }
            if secret_locked:
                item.update({'icon': '❔', 'title': 'نشان مخفی',
                             'desc': info.get('hint') or '؟؟؟', 'secret': True,
                             'earned': False})
            else:
                item.update({'icon': info['icon'], 'title': info['title'],
                             'desc': info['desc'], 'secret': False,
                             'earned': bkey in ach,
                             'at': (ach.get(bkey) or {}).get('at', '')})
            if bkey == 'c_top1_week' and bkey in ach:
                item['count'] = int(ach[bkey].get('count', 1) or 1)
            singles.append(item)
        # جهانی‌ها — صاحب هر کلید (privacy-aware)
        claims = {}
        try:
            doc = await self.settings.find_one({'_id': 'global_firsts'})
            claims = (doc or {}).get('claims', {}) or {}
        except Exception:
            pass
        globals_list = []
        owner_uids = list({v.get('uid') for v in claims.values() if v.get('uid')})
        names = {}
        if owner_uids:
            try:
                docs = await self.users.find({'user_id': {'$in': owner_uids}},
                                             {'user_id': 1, 'name': 1,
                                              'privacy_public': 1}).to_list(len(owner_uids))
                names = {d['user_id']:
                         ((d.get('name') or 'کاربر') if d.get('privacy_public', True)
                          else 'یک دانشجو') for d in docs}
            except Exception:
                pass
        rank_first_keys = [f'first_rank_{r[0]}' for r in self.PRESTIGE_RANKS[1:]] + \
                          ['first_q10000', 'first_streak365',
                           'first_perfect', 'first_contrib10']
        for gk in rank_first_keys:
            claim = claims.get(gk)
            if gk.startswith('first_rank_'):
                rk = gk.replace('first_rank_', '')
                idx = self._rank_idx(rk)
                r = self.PRESTIGE_RANKS[idx]
                icon, title = r[2], f'اولین {r[1]}'
            else:
                icon, title = {
                    'first_q10000': ('🏆', 'اولین ۱۰٬۰۰۰ پاسخ'),
                    'first_streak365': ('🕯', 'اولین استریک ۳۶۵'),
                    'first_perfect': ('🎯', 'اولین آزمون برگ‌کامل'),
                    'first_contrib10': ('🏛', 'اولین ۱۰ مشارکت'),
                }[gk]
            globals_list.append({
                'key': gk, 'icon': icon, 'title': title,
                'rarity': 'ancient', 'color': self.BADGE_RARITY['ancient'][1],
                'claimed': bool(claim),
                'owner_name': (names.get(claim.get('uid'), '؟')
                               if claim else None),
                'owned_by_me': bool(claim and claim.get('uid') == uid),
                'owner_uid': (claim or {}).get('uid'),
            })
        return {'progressive': progressive, 'singles': singles,
                'global': globals_list,
                'showcase': (u.get('showcase') or [])[:self.SHOWCASE_MAX]}


    async def prestige_history_list(self, uid: int, limit: int = 30) -> list:
        """📜 سفر من — تایم‌لاین رنک/نشان/چالش با تاریخ جلالی (Spec §۵)"""
        from utils import fmt_jalali_dt
        rows = await self.prestige_history.find({'uid': uid}) \
            .sort('at', -1).limit(limit).to_list(limit)
        type_labels = {'rank_up': '⬆️ ارتقای رنک', 'div_up': '⭐ ارتقای دسته',
                       'demote': '⬇️ افت دسته', 'achievement': '🏅 نشان',
                       'streak': '🔥 مایل‌استون استریک', 'global_first': '🏆 نشان جهانی',
                       'challenge_win': '⚔️ برد چالش', 'challenge_fail': '💔 شکست چالش',
                       'weekly_champion': '👑 صدر هفته', 'founder': '🏛 بنیان‌گذار',
                       'return': '🫶 بازگشت'}
        out = []
        for r in rows:
            detail = r.get('detail') or {}
            title = type_labels.get(r.get('type'), r.get('type', ''))
            at_jalali = fmt_jalali_dt(r.get('at'))
            out.append({'type': r.get('type'), 'key': r.get('key', ''),
                        'title': title, 'detail': detail,
                        'at': r.get('at'), 'at_jalali': at_jalali})
        return out


    # ───────── Leaderboard (Spec §۶.۱) ─────────

    def _lb_metric(self, u: dict, raw: dict, tab: str, range_: str):
        if tab == 'acc':
            total = int(raw.get('total_answers', 0) or 0)
            if total < 100:
                return None
            return round(int(raw.get('correct_answers', 0) or 0) / total * 1000) / 10
        if tab == 'exam':
            return int(u.get('exams_completed', 0) or 0)
        if tab == 'contrib':
            return int(u.get('submissions_approved', 0) or 0)
        # xp با بازه
        if range_ == 'month':
            return int(u.get('monthly_xp', 0) or 0)
        if range_ == 'season':
            return int(u.get('season_xp', 0) or 0)
        if range_ == 'all':
            return int(u.get('effective_xp', 0) or 0)
        return int(u.get('weekly_xp', 0) or 0)


    async def prestige_leaderboard(self, me_uid: int, range_: str = 'week',
                                   scope: str = 'all', tab: str = 'xp',
                                   limit: int = 50) -> dict:
        """ماتریس بازه×دامنه×تب + dense rank + Jump + رقبا (Spec §۶.۱/§۳.۵)"""
        me_raw = await self.users.find_one({'user_id': me_uid}) or {}
        intake = str(me_raw.get('intake') or '')
        group = str(me_raw.get('group') or '')
        scope_filter = {}
        scope_key = scope
        if scope == 'intake' and intake:
            scope_filter['intake'] = intake
            scope_key = f"intake:{intake}"
        elif scope == 'group' and group:
            scope_filter['group'] = group
            scope_key = f"group:{group}"
        elif scope in ('intake', 'group'):
            scope = 'all'
            scope_key = 'all'
        cache_id = f"lb_cache:{range_}:{scope_key}:{tab}:{limit}"
        cached = None
        try:
            doc = await self.settings.find_one({'_id': cache_id})
            if doc and (now_utc().timestamp()
                        - float(doc.get('computed_at', 0))) < self.PC_CACHE_TTL_SEC:
                cached = doc.get('payload')
        except Exception:
            cached = None
        if cached is None:
            docs = await self.users.find({'approved': True, **scope_filter}) \
                .to_list(100000)
            rows = []
            for raw2 in docs:
                uu = self._puser(raw2)
                v = self._lb_metric(uu, raw2, tab, range_)
                if v is None:
                    continue
                if v <= 0 and range_ in ('week', 'month', 'season') and tab == 'xp':
                    continue
                rows.append({
                    'uid': int(raw2.get('user_id', 0) or 0),
                    # 🏷 Identity v1 — display_name + حفظ privacy
                    # قدیمی (privacy_public=False ⇒ ناشناس، دست‌نخورده)
                    'name': self.display_name_of(raw2)
                            if uu.get('privacy_public', True) else 'یک دانشجو',
                    'privacy': bool(uu.get('privacy_public', True)),
                    'value': v,
                    'streak': int(uu.get('streak_current', 0) or 0),
                    'last_gain_at': uu.get('last_gain_at') or '9999',
                    'registered_at': str(raw2.get('registered_at') or '9999'),
                    'rank_key': uu.get('prestige_rank') or 'rookie',
                    'div': int(raw2.get('prestige_div', 3) or 3),
                    'icon': self.PRESTIGE_RANKS[self._rank_idx(uu.get('prestige_rank') or 'rookie')][2],
                    'title': self.PRESTIGE_RANKS[self._rank_idx(uu.get('prestige_rank') or 'rookie')][1],
                    'color': self.PRESTIGE_RANKS[self._rank_idx(uu.get('prestige_rank') or 'rookie')][4],
                    'roman': self.ROMAN[int(raw2.get('prestige_div', 3) or 3)],
                    'stars': self.DIV_STARS[int(raw2.get('prestige_div', 3) or 3)],
                })
            rows.sort(key=lambda r: (-r['value'], -r['streak'],
                                     r['last_gain_at'], r['registered_at']))
            # dense rank (Spec §۳.۵ب) + Jump از snapshot (فقط week+xp)
            snap = {}
            if range_ == 'week' and tab == 'xp':
                try:
                    sdoc = await self.settings.find_one({'_id': 'lb_snapshot_week'})
                    snap = (sdoc or {}).get('positions', {}) or {}
                except Exception:
                    snap = {}
            prev_val = None
            dense = 0
            for r in rows:
                # dense rank بدون شکاف (۱٬۱٬۲) — هم‌قاعده با rank_number/Top% در state
                if prev_val is None or r['value'] < prev_val:
                    dense += 1
                    prev_val = r['value']
                r['rank'] = dense
                old_pos = snap.get(str(r['uid']), snap.get(r['uid']))
                r['jump'] = (int(old_pos) - dense) if old_pos else None
            # ردیف «من» حتی اگر بیرون از برش limit باشد (ردیف چسبان FE)
            me_full = next((r for r in rows if r['uid'] == me_uid), None)
            top_rows = rows[:limit]
            cached = {'rows': top_rows, 'total': len(rows), 'me': me_full}
            try:
                await self.settings.update_one({'_id': cache_id},
                    {'$set': {'payload': cached,
                              'computed_at': now_utc().timestamp()}},
                    upsert=True)
            except Exception:
                pass
        rows_out = [dict(r, is_me=(r['uid'] == me_uid)) for r in cached['rows']]
        me_row = (dict(cached['me'], is_me=True) if cached.get('me') else None)
        # رقیب بالا/پایین با effective_xp (§۳.۵) — تک‌منبع با state
        eff_mc = max(int(me_raw.get('prestige_xp', 0) or 0)
                     - int(me_raw.get('decay_penalty', 0) or 0),
                     int(me_raw.get('rank_floor_xp', 0) or 0))
        rival_above = await self._rival_row(me_uid, {'effective_xp': {'$gt': eff_mc}}, 1, eff_mc)
        rival_below = await self._rival_row(me_uid, {'effective_xp': {'$lt': eff_mc}}, -1, eff_mc)
        season = await self._season_info()
        return {'range': range_, 'scope': scope, 'tab': tab,
                'rows': rows_out, 'me': me_row, 'total_users': cached['total'],
                'rival_above': rival_above, 'rival_below': rival_below,
                'season': season}


    async def _rival_row(self, uid: int, cond: dict, sort_dir: int, my_eff: int):
        try:
            cur = self.users.find({'approved': True, 'user_id': {'$ne': uid}, **cond}) \
                .sort('effective_xp', sort_dir).limit(1)
            arr = await cur.to_list(1)
            if not arr:
                return None
            v = arr[0]
            gap = abs(int(v.get('effective_xp', 0) or 0) - my_eff)
            return {'name': (v.get('name') or 'کاربر')
                            if v.get('privacy_public', True) else 'یک دانشجو',
                    'gap': gap,
                    'icon': self.PRESTIGE_RANKS[
                        self._rank_for(int(v.get('effective_xp', 0) or 0))[0]][2]}
        except Exception:
            return None


    # ───────── Daily Feed + Reactions (Spec §۶.۳) ─────────

    FEED_WINDOW_H = 48


    def _feed_label(self, doc: dict, name: str) -> str:
        t = doc.get('type')
        key = str(doc.get('key') or '')
        detail = doc.get('detail') or {}
        if t == 'rank_up':
            idx = self._rank_idx(key)
            r = self.PRESTIGE_RANKS[idx]
            return f"🔥 {name} به {r[2]} {r[1]} رسید"
        if t == 'achievement':
            meta = (self.BADGES_SINGLE.get(key) or {})
            icon = meta.get('icon') or '🏅'
            title = meta.get('title') or (self.BADGES_PROG.get(key, ('🏅', key, '', []))[1])
            return f"🏅 {name} نشان {icon} {title} را گرفت"
        if t == 'global_first':
            return f"🏆 {name} اولین نفر در تاریخ هامزیار شد"
        if t == 'weekly_champion':
            return f"👑 صدر هفته: {name}"
        if t == 'streak':
            return f"🔥 استریک {key} روزه‌ی {name}"
        return f"✨ {name}"


    def _feed_is_public(self, doc: dict) -> bool:
        t = doc.get('type')
        if t == 'rank_up':
            return self._rank_idx(str(doc.get('key') or '')) >= self.CHALLENGE_FROM_IDX
        if t == 'achievement':
            key = str(doc.get('key') or '')
            rarity = (doc.get('detail') or {}).get('rarity')
            if not rarity:
                if key in self.BADGES_SINGLE:
                    rarity = self.BADGES_SINGLE[key]['rarity']
                elif key in self.BADGES_PROG:
                    rarity = (doc.get('detail') or {}).get('rarity') or 'common'
            return rarity in ('epic', 'legendary', 'mythic', 'ancient')
        if t == 'streak':
            return str(doc.get('key') or '') in ('7', '30', '90')
        return t in ('global_first', 'weekly_champion')


    async def prestige_feed(self, me_uid: int, limit: int = 5) -> dict:
        """۵ رویداد آخر عمومی (۴۸ ساعت) + واکنش‌ها — کش ۱۰ دقیقه‌ای (Spec §۶.۳)"""
        items = None
        try:
            doc = await self.settings.find_one({'_id': 'feed_cache'})
            if doc and (now_utc().timestamp()
                        - float(doc.get('computed_at', 0))) < self.PC_CACHE_TTL_SEC:
                items = doc.get('items')
        except Exception:
            items = None
        if items is None:
            cutoff = (now_utc() - timedelta(hours=self.FEED_WINDOW_H)).isoformat()
            docs = await self.prestige_history.find({'at': {'$gte': cutoff}}) \
                .sort('at', -1).limit(60).to_list(60)
            docs = [d for d in docs if self._feed_is_public(d)]
            uids = list({int(d.get('uid', 0) or 0) for d in docs})
            names = {}
            if uids:
                try:
                    users = await self.users.find({'user_id': {'$in': uids}},
                        {'user_id': 1, 'name': 1, 'nickname': 1, 'privacy_public': 1}).to_list(len(uids))
                    # 🏷 Identity v1 — فید اجتماعی با display_name
                    names = {d['user_id']:
                             (self.display_name_of(d) if d.get('privacy_public', True)
                              else 'یک دانشجو') for d in users}
                except Exception:
                    pass
            items = []
            for d in docs:
                uid = int(d.get('uid', 0) or 0)
                name = names.get(uid, 'دانشجو')
                eid = str(d.get('_id', '')) or \
                    f"{uid}:{d.get('at')}:{d.get('type')}:{d.get('key')}"
                reactions = d.get('reactions') or {}
                items.append({
                    'id': eid, 'type': d.get('type'), 'uid': uid,
                    'name': name, 'text': self._feed_label(d, name),
                    'at': d.get('at'),
                    'reactions': {'clap': int(reactions.get('clap', 0) or 0),
                                  'fire': int(reactions.get('fire', 0) or 0),
                                  'crown': int(reactions.get('crown', 0) or 0)},
                })
                if len(items) >= limit:
                    break
            try:
                await self.settings.update_one({'_id': 'feed_cache'},
                    {'$set': {'items': items,
                              'computed_at': now_utc().timestamp()}},
                    upsert=True)
            except Exception:
                pass
        # my_reaction جداگانه per request (هویت واکنش‌دهنده خروجی نمی‌شود)
        my_map = {}
        ids = [it['id'] for it in items]
        if ids:
            try:
                mine = await self.feed_reactions.find(
                    {'uid': me_uid, 'event_id': {'$in': ids}}).to_list(len(ids))
                my_map = {r['event_id']: r.get('kind') for r in mine}
            except Exception:
                pass
        return {'items': [dict(it, my_reaction=my_map.get(it['id']))
                          for it in items]}


    async def feed_react(self, uid: int, event_id: str, kind: str = None) -> dict:
        """ثبت/تعویض/حذف واکنش — ضدتکرار (event_id,uid) یکتا (Spec §۶.۳)"""
        if kind not in (None, 'clap', 'fire', 'crown'):
            return {'ok': False, 'code': 'bad_kind'}
        event_id = str(event_id or '')[:120]
        if not event_id:
            return {'ok': False, 'code': 'bad_event'}
        try:
            q = {'_id': ObjectId(event_id)}
        except Exception:
            q = {'_id': event_id}
        ev = await self.prestige_history.find_one(q)
        if not ev:
            return {'ok': False, 'code': 'not_found'}
        existing = await self.feed_reactions.find_one({'event_id': event_id, 'uid': uid})
        delta = {'clap': 0, 'fire': 0, 'crown': 0}
        my = None
        now_iso = utc_now_iso()
        # toggle-off: همان واکنش دوباره یا حذف صریح
        if (kind is None) or (existing and existing.get('kind') == kind):
            if existing:
                await self.feed_reactions.delete_many(
                    {'event_id': event_id, 'uid': uid})
                delta[existing.get('kind', 'clap')] -= 1
            my = None
        elif existing:
            delta[existing.get('kind', 'clap')] -= 1
            await self.feed_reactions.update_one(
                {'event_id': event_id, 'uid': uid},
                {'$set': {'kind': kind, 'at': now_iso}})
            delta[kind] += 1
            my = kind
        else:
            try:
                await self.feed_reactions.insert_one(
                    {'event_id': event_id, 'uid': uid, 'kind': kind, 'at': now_iso})
                delta[kind] += 1
                my = kind
            except Exception:
                # race: جایگزینی به‌جای درج (ایندکس یکتا)
                await self.feed_reactions.update_one(
                    {'event_id': event_id, 'uid': uid},
                    {'$set': {'kind': kind, 'at': now_iso}})
                my = kind
        incs = {f'reactions.{k}': v for k, v in delta.items() if v}
        if incs:
            try:
                await self.prestige_history.update_one(q, {'$inc': incs})
            except Exception as _re:
                logger.warning(f"feed reaction counter update failed: {_re}")   # 🛡 AUDIT-R6
        try:
            # شمارنده‌ها بلافاصله تازه شوند — کش فید ۱۰دقیقه‌ای باطل می‌شود
            await self.settings.delete_many({'_id': 'feed_cache'})
        except Exception:
            pass
        ev2 = await self.prestige_history.find_one(q) or ev
        react = ev2.get('reactions') or {}
        return {'ok': True, 'my_reaction': my,
                'reactions': {'clap': int(react.get('clap', 0) or 0),
                              'fire': int(react.get('fire', 0) or 0),
                              'crown': int(react.get('crown', 0) or 0)}}


    # ───────── Hero Card عمومی (Spec §۶.۲) ─────────

    async def prestige_public(self, target_uid: int) -> dict:
        """کارت عمومی رنک — بدون آمار حساس؛ احترام کامل به privacy"""
        raw = await self.users.find_one(
            {'user_id': int(target_uid), 'approved': True})
        if not raw:
            return {'ok': False, 'code': 'not_found'}
        u = self._puser(raw)
        if not u.get('privacy_public', True):
            return {'ok': True, 'limited': True}
        eff = max(u['prestige_xp'] - u['decay_penalty'], u['rank_floor_xp'])
        idx, div = self._rank_for(eff)
        floor_idx, _ = self._rank_for(u['rank_floor_xp'])
        cap = max(self.CHALLENGE_FROM_IDX - 1, floor_idx)
        if idx > cap:
            idx, div = cap, 1
        r = self.PRESTIGE_RANKS[idx]
        today = self._tehran_today()
        total_active = await self._pc_total_active()
        rank_number = None
        top_pct = None
        if total_active:
            try:
                better = await self.users.count_documents({
                    'approved': True,
                    'last_active_day': {'$gte': (parse_gregorian_date(today)
                                                 - timedelta(days=self.ACTIVE_WINDOW_DAYS)).isoformat()},
                    'effective_xp': {'$gt': eff},
                })
                rank_number = better + 1
                top_pct = max(1, (rank_number * 100 + total_active - 1) // total_active)
            except Exception:
                pass
        bot_username = os.getenv('BOT_USERNAME', '')
        share_link = (f"https://t.me/{bot_username}?startapp=rank_{target_uid}"
                      if bot_username else '')
        # QR سبک سروری (SVG) — اگر پکیج/لینک نبود، FE بلوک را پنهان می‌کند
        qr_svg = ''
        if share_link:
            try:
                import io as _io
                import qrcode as _qr
                import qrcode.image.svg as _qrs
                _img = _qr.make(share_link,
                                image_factory=_qrs.SvgPathImage,
                                box_size=10, border=1)
                _buf = _io.BytesIO()
                _img.save(_buf)
                qr_svg = _buf.getvalue().decode('utf-8', 'ignore')
            except Exception:
                qr_svg = ''
        rec = u.get('records') or {}
        top_idx = self._rank_idx(rec.get('top_rank_key') or 'rookie')
        return {
            'ok': True, 'limited': False,
            'name': raw.get('name') or 'کاربر',
            'icon': r[2], 'title': r[1], 'color': r[4], 'gradient': r[5],
            'div': div, 'roman': self.ROMAN[div], 'stars': self.DIV_STARS[div],
            'rank_number': rank_number, 'top_pct': top_pct,
            'streak': {'current': u['streak_current'], 'best': u['streak_best']},
            'records': {
                'best_acc': rec.get('best_acc', 0),
                'best_exam_pct': rec.get('best_exam_pct', 0),
                'top_rank_icon': self.PRESTIGE_RANKS[top_idx][2],
                'top_rank_title': self.PRESTIGE_RANKS[top_idx][1],
            },
            'showcase': self._showcase_meta(u),
            'share_link': share_link, 'qr_svg': qr_svg,
            'uid': int(target_uid),
        }


    # ───────── بستن هفته (Spec §۶.۱ — جاب) ─────────

    async def prestige_weekly_close(self) -> dict:
        """جاب پایان هفته: snapshot چینش + قهرمان هفته (+۱۰۰/نشان/رکوردها)"""
        today = self._tehran_today()
        business_week = week_key_tehran(parse_gregorian_date(today))
        done_key = f"weekly_closed:{business_week}"
        if await self.get_setting(done_key, False):
            return {'skipped': True, 'week': business_week}
        docs = await self.users.find({'approved': True, 'weekly_xp': {'$gt': 0}}) \
            .to_list(100000)
        docs.sort(key=lambda d: (-int(d.get('weekly_xp', 0) or 0),
                                 -int(d.get('streak_current', 0) or 0),
                                 str(d.get('last_gain_at') or '9999'),
                                 str(d.get('registered_at') or '9999')))
        positions = {str(int(d.get('user_id', 0) or 0)): i + 1
                     for i, d in enumerate(docs)}
        try:
            prev = await self.settings.find_one({'_id': 'lb_snapshot_week'})
            await self.settings.update_one(
                {'_id': 'lb_snapshot_prev'},
                {'$set': prev or {}}, upsert=True)
            await self.settings.update_one(
                {'_id': 'lb_snapshot_week'},
                {'$set': {'week': business_week, 'positions': positions,
                          'at': utc_now_iso()}},
                upsert=True)
        except Exception:
            pass
        champion = None
        if docs:
            champ = docs[0]
            cuid = int(champ.get('user_id', 0) or 0)
            await self.prestige_event(cuid, 'weekly_champion', {'week': business_week})
            champion = {'uid': cuid, 'name': champ.get('name') or 'کاربر',
                        'weekly_xp': int(champ.get('weekly_xp', 0) or 0)}
        # ریست زنجیره‌ی صدر برای همه‌ی غیرقهرمان‌ها (idempotent با خود جاب)
        for d in docs:
            uid_x = int(d.get('user_id', 0) or 0)
            if champion and uid_x == champion['uid']:
                continue
            if int((d.get('records') or {}).get('top1_weeks_current', 0) or 0) > 0:
                try:
                    await self.users.update_one({'user_id': uid_x},
                        {'$set': {'records.top1_weeks_current': 0}})
                except Exception:
                    pass
        try:
            await self.set_setting(done_key, True)
        except Exception:
            pass
        return {'skipped': False, 'week': business_week,
                'rows': len(docs), 'champion': champion}


    async def prestige_weekly_close_state(self) -> dict:
        """وضعیت آخرین بستن هفته — برای نمای مدیریتی/کارت لیدربرد"""
        doc = None
        try:
            doc = await self.settings.find_one({'_id': 'lb_snapshot_week'})
        except Exception:
            pass
        return doc or {}
