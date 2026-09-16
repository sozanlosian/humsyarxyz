"""💍 Ring Street — گفت‌وگوی ناشناس (V1)

ماژولی **افزودنی و ایزوله**: هیچ importی از این بسته در مسیرهای اصلی ربات
نیست مگر `bot.py` (ثبت هندلر/job)، `utils.py` (دکمه‌ی منوی اصلی) و
`api/main.py` (روت admin). همه‌ی رفتارها پشت یک flag در دیتابیس‌اند
(`ring_enabled`)؛ اگر flag خاموش باشد، این بسته عملاً نامرئی است.

ساختار:
  settings    §۲۹/§۳۸  flag + knobs (منبع: bot_settings)
  models      §۲/§۱۱    سن/جنسیت/حالت + ماشین حالت + تشخیص نشت اطلاعات
  matcher     §۸/§۱۰    فیلتر سخت + امتیاز نرم (fairness در DB انجام می‌شود)
  service     §۷..§۲۱   صف، match اتمیک، پایان جلسه، reveal، اکشن‌های ادمین
  relay       §۱۳..§۱۵  رله از طریق بات با copyMessage/فرستادن مجدد
  moderation  §۱۹..§۲۵  بلاک/گزارش/بن + آستانه‌ها
  state       §۴۲/§۴۳   کش رجیستری چت + بازیابی از DB
  handlers    §۴۲        هندلرهای تلگرام
  jobs        §۲۲/§۴۵   timeoutها + reconcile + آمار روزانه
  analytics   §۳۶        funnel/moderation برای پنل
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = ["register_handlers", "post_init", "pre_dispose"]


def register_handlers(app) -> None:
    """ثبت هندلرهای تلگرام (callback در bot.py انجام می‌شود چون الگوی
    ربات یک لیست `cbs` است و اولویت = ترتیب ثبت)."""
    from ring.handlers import register
    register(app)


async def post_init(bot=None) -> dict:
    """at boot: بات را به لایهٔ اطلاعیه bind می‌کند، flag را می‌خواند و
    sessionهای فعال را از DB برمی‌گرداند. هیچ‌وقت raise نمی‌کند.

    §۱/§۴۵ (V6) — ریشهٔ باگِ زنده این‌جا بود: PTB ۲۱.۳ هیچ
    `Application.get_current()` و `get_running_app()` ندارد، پس
    `notify._bot()` همیشه None برمی‌گرداند و *هر* اطلاعیه/ویرایشِ تایمر بی‌صدا
    دور ریخته می‌شد («MATCH CREATED ولی کاربر در SEARCHING ماند»). `bot.py`
    همین `application.bot` را به این تابع می‌دهد؛ تا V۵ پارامتر `bot` بی‌استفاده
    دور انداخته می‌شد. حالا همان منبع، bind می‌شود (و جست‌وجوی PTB فقط fallback).
    """
    out = {"flag": False, "loaded": 0, "dropped": 0, "notify": "unknown"}
    try:
        from ring import notify
        if bot is not None:
            notify.bind(bot)
            out["notify"] = "bound"
        else:
            out["notify"] = str(notify.health().get("source"))
            logger.warning("💍 post_init بدون بات صدا زده شد؛ اطلاعیه‌ها روی "
                           "fallback می‌مانند: %s", out["notify"])
    except Exception as e:
        logger.warning("💍 bind بات رینگ ناموفق: %s", e)
        out["notify"] = f"bind-error:{type(e).__name__}"
    try:
        from ring import jobs, settings as S, state
        out["flag"] = await S.get_flag()
        await S.get_cfg()
        st = await S.disable_mode()
        if not out["flag"]:
            if st == "hard":
                from database import db
                await jobs._hard_disable(db)
            return out
        from ring.handlers import flow_mark
        rec = await state.load_from_db(mark=flow_mark)
        out["loaded"] = int(rec.get("loaded") or 0)
        out["dropped"] = int(rec.get("dropped") or 0)
        rep = await db_repair()
        out.update(rep)
        # §۱۹/§۳۶ — بعد از بازیابی state، سه کار ناتمام را ببند (اطلاعیهٔ
        # نرسیده، UI معلق، یتیم‌ها). شغلِ دوره‌ای هم همین را می‌کند؛ اینجا
        # انجامش می‌دهیم تا کاربر معادلِ «یک‌دورهٔ ۳۰ ثانیه» معطل نشود.
        from ring import service
        out["boot_repair"] = await service.boot_repair()
        logger.info("💍 notify: %s | boot_repair: %s", out["notify"], out["boot_repair"])
        return out
    except Exception as e:
        logger.warning("💍 post_init رینگ کامل نشد: %s", e)
        return out


async def db_repair() -> dict:
    """reconcile یک‌باره در بوت (session/queue یتیم)."""
    try:
        from database import db
        r = await db.ring_reconcile()
        return {"reconciled": r}
    except Exception as e:
        logger.debug("ring reconcile skipped: %s", e)
        return {}


async def pre_dispose() -> None:
    """رجیستری RAM و bind بات را پاک می‌کند تا در تست/ری‌استارت چیزی نماند.

    V6: unbind عمدی است — اگر مرجعِ باتِ در حال خاموش‌شدن بماند، `send_text`
    روی شیءِ مرده صدا زده می‌شود و خطا گم می‌شود.
    """
    try:
        from ring import notify, state
        state.clear()
        notify.unbind()
    except Exception as e:
        logger.warning("💍 pre_dispose ناتمام: %s", e)
