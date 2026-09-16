"""💍 Ring Street — تنها راهِ ارسال پیام از سمتِ ربات (هندلر، job، API)

چرا این فایل در V6 بازنویسی شد (ریشهٔ باگِ پروداکشن):

  • هندلرها `context.bot` دارند؛ **jobها، شغلِ تایمر و روتر API ندارند**.
  • تا V5 این ماژول بات را از `Application.get_current()` می‌گرفت. در
    `python-telegram-bot[job-queue]==21.3` (قفلِ requirementsِ همین پروژه)
    چنین متدی وجود **ندارد** ⇒ AttributeError ⇒ داخل `except Exception:
    return None` ⇒ `_bot()` همیشه None بود.
  • نتیجه: هر اطلاعیه‌ای (کارت مچ، «طرف مقابل رفت»، بن/گزارش) بی‌صدا دور
    ریخته می‌شد و `search_tick` هم زودتر از ویرایش برمی‌گشت ⇒ روی سرورِ زنده
    session فعال بود و رله کار می‌کرد، ولی هر دو کاربر روی پیامِ
    «🔎 در حال جست‌وجو… ⏱ 00:00» میخکوب ماندند.

V6:
  ۱) باتِ واقعی در `post_init` bind می‌شود (همان `ring_street.post_init(
     application.bot)` که bot.py از قبل صدا می‌زند) — هیچ مکانیزمِ تازه‌ای
     اختراع نشد؛ ریزولوشنِ PTB فقط fallback است.
  ۲) «بی‌صدا رد کردن» حذف شد: هر شکست یا `logger.warning` با برچسبِ
     grep‌پذیر دارد یا (برای اطلاعیه‌های حیاتی) در session به‌صورت pending
     ثبت می‌شود تا housekeeping با backoff دوباره امتحان کند.
"""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

_BOUND = None                     # باتِ bind‌شده در post_init (منبعِ اصلی)
_SOURCE = "none"                  # bind | ptb:<name> | none  (برای دیباگِ پنل)
_LAST_ERR: str | None = None
_DROPS = 0                        # چند ارسال به‌دلیل نبودنِ بات رد شد
_NOBOT_AT: dict[int, float] = {}  # rate-limitِ لاگِ NOBOT (به‌ازای هر کاربر)
_LOG_EVERY_S = 60.0

# نام‌های متدی که PTB در نسخه‌های مختلف برای «رسیدن به Applicationِ در حال
# اجرا» داشته است؛ هر کدام بود، استفاده می‌شود (fallback، نه منبعِ حقیقت).
_PTB_NAMES = ("get_running_app", "get_current", "get_current_application")


def bind(bot) -> bool:
    """باتِ واقعی را ثبت می‌کند. `bot=None` صدا کند، وضعیت دست‌نخورده می‌ماند."""
    global _BOUND, _SOURCE
    if bot is None:
        return False
    if _BOUND is bot:
        return True
    _BOUND, _SOURCE = bot, "bind"
    logger.info("RING_NOTIFY_BOUND source=bind (%s)", type(bot).__name__)
    return True


def unbind() -> None:
    """فقط برای تست/ری‌استارت: رجیستری بات را پاک می‌کند."""
    global _BOUND, _SOURCE
    _BOUND, _SOURCE = None, "none"


def bound() -> bool:
    return _BOUND is not None


def health() -> dict:
    """برای پنل ادمین (§۴۶ V6): «آیا اصلاً می‌توانیم پیام بدهیم؟»"""
    return {"bound": _BOUND is not None, "source": _SOURCE,
            "drops": int(_DROPS), "last_error": _LAST_ERR}


def _note_err(err) -> None:
    global _LAST_ERR
    _LAST_ERR = str(err)[:200]


def _resolve():
    """(bot, source) — اول bind، بعد PTB (fallback)، وگرنه (None, "none")."""
    global _BOUND, _SOURCE
    if _BOUND is not None:
        return _BOUND, _SOURCE
    try:
        from telegram.ext import Application
    except Exception as e:                 # pragma: no cover — تلگرام نصب نیست
        _note_err(e)
        return None, "none"
    for name in _PTB_NAMES:
        fn = getattr(Application, name, None)
        if not callable(fn):
            continue
        try:
            app = fn()
        except Exception as e:             # قدیمی/جدید/no-running-app ⇒ رد شو
            _note_err(e)
            continue
        b = getattr(app, "bot", None)
        if b is not None:
            _BOUND, _SOURCE = b, f"ptb:{name}"
            logger.debug("RING_NOTIFY_BOUND source=ptb:%s (fallback)", name)
            return b, _SOURCE
    return None, "none"


def _bot():
    return _resolve()[0]


def _warn_nobot(uid: int, text: str) -> None:
    """§۱۵ (V6) — «بات نیست» باید در لاگِ INFO دیده شود، اما سیل نشود."""
    global _DROPS
    _DROPS += 1
    now = time.monotonic()
    if now - _NOBOT_AT.get(int(uid), -1e9) < _LOG_EVERY_S:
        return
    _NOBOT_AT[int(uid)] = now
    logger.warning("RING_NOTIFY_NOBOT uid=%s len=%s source=none — بات هنوز bind "
                   "نشده (post_init رینگ را در bot.py بررسی کن)", uid, len(text))


async def send_text(uid: int, text: str, **kw) -> bool:
    """True ⇒ واقعاً به تلگرام رسید. False ⇒ **هرگز بی‌صدا نیست**: یا warning
    یا `last_error` که در `health()` و `/api/ring/overview` دیده می‌شود.

    فراخوان‌های حیاتی (کارت مچ، اطلاعیهٔ پایان) به این bool بی‌تفاوت نیستند:
    `service.notify_match_started` نتیجه را در سند session ثبت می‌کند تا اگر
    False شد، housekeeping دوباره امتحان کند (§۱۰/§۱۳/§۳۱ V6).
    """
    bot = kw.pop("bot", None) or _bot()
    if bot is None or not text:
        if text:
            _warn_nobot(uid, text)
        return False
    from telegram.error import RetryAfter
    for attempt in range(3):
        try:
            await bot.send_message(int(uid), text, **kw)
            return True
        except asyncio.CancelledError:              # هرگز نباید «خورد» شود
            raise
        except RetryAfter as e:
            _note_err(e)
            await asyncio.sleep(min(getattr(e, "retry_after", 3), 20) + 0.4)
        except Exception as e:
            # §۹ (V5) — «طرف مقابل اطلاعیه نگرفت» نباید در لاگ گم شود (قبلاً
            # debug بود و در سطح INFO پروداکشن دیده نمی‌شد).
            _note_err(e)
            logger.warning("RING_NOTIFY_FAIL uid=%s attempt=%s err=%s",
                           uid, attempt + 1, str(e)[:160])
            return False
    logger.warning("RING_NOTIFY_FAIL uid=%s err=retry-exhausted", uid)
    return False


async def send_to_peer_of(uid: int, session: dict, text: str, bot=None) -> bool:
    """ارسال به طرف مقابل یک جلسه (اگر جلسه دیگر فعال نبود، کاری نمی‌کنیم)."""
    if not session:
        return False
    slots = session.get("slots") or []
    peer = next((int(s) for s in slots if int(s) != int(uid)), None)
    if peer is None:
        return False
    return await send_text(peer, text, bot=bot)
