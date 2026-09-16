"""💍 Ring Street — رله‌ی پیام (§۱۳..§۱۵، §۸، §۳۵)

ناشناس‌سازی در همین‌جا اتفاق می‌افتد (§۱۶/§۱۷ — V4):

  • متن     → `send_message` از طرف **بات**، **بدون هیچ پیشوند/برچسبی**.
              کاربر باید پیام را مثل یک چت عادی ببیند: «سلام» ⇒ «سلام».
              هیچ `forward` نمی‌شود (forward لینک به پیام اصلی و
              «forwarded from» دارد ⇒ هویت لو می‌رود).
              هیچ شناسه‌ای (uid/chat_id/#anon) هرگز به پیام اضافه نمی‌شود؛
              alias فقط در بافرِ شواهد و پنل ادمین می‌ماند.
  • مدیا    → `copy_message`؛ طبق مستندات تلگرام کپی، رفرنس به پیام
              مبدأ ندارد و فرستنده‌ی پیام‌کپی خودِ بات است ⇒ نام/آیدی
              کاربر اصلی نمایش داده نمی‌شود. captionِ **خودِ کاربر** دست
              نمی‌خورد (در V3 جای آن «👤 alias» می‌نشست که هم برچسبِ بیرونی
              بود، هم متن کاربر را دور می‌انداخت).
  • اگر کپی نشد (محتوای protected / نوع پشتیبانی‌نشده) → fallback با
              file_id برای photo/document/voice/video و در نهایت
              «این نوع فایل ارسال نشد» — بدون crash و بدون لو‌رفتن.

هیچ متن پیامی به‌طور پیش‌فرض ذخیره نمی‌شود (§۳۵): فقط یک بافر چرخشی در
RAM نگه داشته می‌شود تا «گزارش» بتواند شواهد را snapshot کند.
"""
from __future__ import annotations

import logging
from collections import deque

from ring import models as M
from ring import notify
from ring import settings as S
from ring import state
from ring import texts
from time_utils import utc_now_iso

logger = logging.getLogger(__name__)

MAX_TEXT = 4000                    # زیر سقف ۴۰۹۶ تلگرام (§۱۸)
BUFFER_SESSIONS = 400              # سقف sessionهایی که بافر نگه می‌داریم
BUFFER_LEN = 30                    # آخرین N پیام هر session

_buffers: dict[str, deque] = {}    # sid -> deque[dict]


def buffer_for(sid: str) -> deque:
    b = _buffers.get(sid)
    if b is None:
        if len(_buffers) > BUFFER_SESSIONS:      # حافظه کرانه‌دار بماند
            _buffers.pop(next(iter(_buffers)), None)
        b = _buffers[sid] = deque(maxlen=BUFFER_LEN)
    return b


def buffer_snapshot(sid: str) -> list[dict]:
    return list(_buffers.get(sid) or [])


def buffer_drop(sid: str) -> None:
    _buffers.pop(sid, None)


def kind_of(msg) -> str:
    """نوعِ پیام (§۱۸ — متن/عکس/ویدیو/ویس/آدیو/سند/استیکر/انیمیشن).

    ⚠️ ترتیب: اولِ مدیا. اگر «عکس با کپشن» مثل متن درجه‌بندی شود، تصویر دور
    ریخته می‌شود و فقط کپشن می‌رود — باگی که در V3 بود و در V4 رفع شد.
    contact/location هم مدیای مجزا نیستند: سیاستِ خودشان را دارند (§۱۸) و
    در غیر این صورت «پشتیبانی نمی‌شود» می‌گیرند، نه رله‌ی خاموش.
    """
    if msg is None:
        return "unknown"
    if msg.sticker:
        return "sticker"
    if msg.photo:
        return "photo"
    if msg.voice or msg.audio:
        return "voice"
    if msg.video or msg.animation:
        return "video"
    if msg.document:
        return "document"
    if getattr(msg, "contact", None):
        return "contact"
    if getattr(msg, "location", None) or getattr(msg, "venue", None):
        return "location"
    if msg.text and not msg.entities:
        return "text"
    if msg.text or msg.caption:
        return "text"
    return "other"


async def relay(update, context, *, entry: dict | None = None) -> dict:
    """رله‌ی پیام کاربر به پارتنرش.

    خروجی: {'handled': bool, 'why': str}. `handled=False` یعنی این پیام
    به رینگ ربطی نداشت و باید به مسیریاب عادی ربات برود.
    """
    uid = update.effective_user.id
    msg = update.effective_message
    if msg is None:
        return {"handled": True, "why": "empty"}
    ent = entry or state.get(uid)
    if not ent:
        return {"handled": False, "why": "idle"}
    from database import db
    sid = ent["sid"]
    sess = await db.ring_session(sid)
    if not sess or sess.get("status") != "active":
        state.detach(uid)
        state.detach(ent["peer"])
        await notify.send_text(uid, "🔚 این گفت‌وگو بسته شده است.")
        return {"handled": True, "why": "session_closed"}
    cfg = await S.get_cfg()
    kind = kind_of(msg)

    # ── سیاست مدیا (§۱۴/§۱۸) ──
    if kind in ("contact", "location"):
        # سیاستِ مجزا: با اینکه کپیِ بات ناشناس است، شماره/مختصاتِ کاربر در
        # خودِ محتواست و برگشت‌ناپذیر ⇒ پیش‌فرض بسته، با کلیدِ پنل باز می‌شود.
        allowed = bool(cfg.get("media_contact" if kind == "contact"
                              else "media_location", False))
        if not allowed:
            await notify.send_text(
                uid, "🔒 ارسال مخاطب/موقعیت در رینگ مجاز نیست — همان چیزی است "
                     "که هویت شما را لو می‌دهد. اگر لازم داشتی، شماره‌ات را "
                     "خودت (با مسئولیت خودت) تایپ کن.")
            return {"handled": True, "why": "contact_blocked"}
        try:
            okc = await context.bot.copy_message(chat_id=int(state.get(uid)["peer"]),
                                                  from_chat_id=msg.chat_id,
                                                  message_id=msg.message_id)
            return {"handled": True, "why": "relayed"} if okc else \
                   {"handled": True, "why": "delivery_failed"}
        except Exception as e:
            logger.debug("contact/location relay failed: %s", e)
            return {"handled": True, "why": "delivery_failed"}
    key = S.MEDIA_KINDS.get(kind)
    if key and not cfg.get(f"media_{key}", False):
        await notify.send_text(uid, "⛔ ارسال این نوع محتوا در رینگ مجاز نیست.")
        return {"handled": True, "why": "media_off"}
    if kind == "other":
        await notify.send_text(uid, "⚠️ این نوع پیام پشتیبانی نمی‌شود (فقط متن/عکس/استیکر).")
        return {"handled": True, "why": "unsupported"}

    # ── rate limit (§۲۲) ──
    if kind in ("text",):
        rl = await db.ring_limit_hit("ring_msg", uid, int(cfg["max_msg_per_min"]), 60)
        if not rl["ok"]:
            await notify.send_text(uid, f"🐢 کمی آروم‌تر — {rl['retry_after']} ثانیه بعد دوباره.")
            return {"handled": True, "why": "rate_limited"}
    else:
        rl = await db.ring_limit_hit("ring_media", uid, int(cfg["max_media_per_min"]), 60)
        if not rl["ok"] or int(cfg["max_media_per_min"]) == 0:
            await notify.send_text(uid, "🐢 تعداد فایل‌ها زیاد شد؛ کمی صبر کن.")
            return {"handled": True, "why": "rate_limited"}

    # ── بنِ فرستنده ⇒ از چت بیرونش بیاور و به مسیریاب عادی برگردان ──
    ban = await db.ring_ban_active(uid)
    if ban:
        state.detach(uid)
        state.detach(ent["peer"])
        await notify.send_text(
            uid, "🚫 دسترسی شما به رینگ استریت موقتاً محدود شده است.")
        return {"handled": True, "why": "banned"}

    peer = int(ent["peer"])
    # §۲۰/§۲۱/§۵۸ — «نفر بعدی/پایان/گزارش/بلاک» کنشِ کاربر→بات است، نه حرفِ
    # کاربر→پارتنر. اگر کسی برچسبشان را تایپ کرد، رله نمی‌شود و یک راهنمای
    # محلی (فقط برای خودش) می‌گیرد — برای پارتنر هیچ چیزی ساخته نمی‌شود.
    from ring import keyboards as K
    if kind == "text" and K.is_control_label(msg.text) and not K.is_main_menu_label(msg.text):
        await notify.send_text(uid, texts.control_not_message(), bot=context.bot)
        return {"handled": True, "why": "control_label"}
    alias = ent.get("alias") or "ناشناس"      # فقط برای بافر/پنل (§۱۷)
    ok = False
    if kind == "text":
        # §۱۷ — بدون هیچ پیشوندی: دقیقاً همان چیزی که کاربر نوشته
        body = M.clean_text(msg.text or "", MAX_TEXT)
        if not body:
            return {"handled": True, "why": "empty"}
        ok = await notify.send_text(peer, body, bot=context.bot)
    elif kind == "sticker":
        try:
            ok = await context.bot.send_sticker(peer, sticker=msg.sticker.file_id)
        except Exception as e:
            logger.debug("sticker relay failed: %s", e)
            ok = False
    else:
        ok = await _relay_media(context, peer, msg)
        if not ok:                                # fallback: file_id
            ok = await _relay_by_file_id(context, peer, msg, kind)

    if not ok:
        await notify.send_text(
            uid, "⚠️ پیام به طرف مقابل نرسید (شاید رینگ را بسته یا از بات خارج شده). "
                 "کمی بعد دوباره امتحان کن.", bot=context.bot)
        return {"handled": True, "why": "delivery_failed"}

    # ── شمارنده‌ها + بافر شواهد + هشدار اطلاعات شخصی ──
    await db.ring_session_touch(sid, media=(kind != "text"))
    await db.ring_bump(messages=1)
    # متن فقط در بافر RAM می‌ماند (O(۱) و ناپذیرا در DB)؛ نوشتن روی دیسک
    # فقط وقتی که «all» روشن باشد یا گزارشی ثبت شود (§۳۵).
    entry_meta = {"seq": int(sess.get("messages_count", 0)) + 1, "uid": int(uid),
                  "alias": alias, "kind": kind, "at": utc_now_iso(),
                  "text": M.clean_text(msg.text or msg.caption or "", 240)}
    if cfg.get("evidence_mode") == "off":
        entry_meta["text"] = None
    else:
        buffer_for(sid).append(entry_meta)
        if cfg.get("evidence_mode") == "all":
            await db.ring_evidence_put({
                "_id": f"{sid}:{entry_meta['seq']}", "session_id": sid,
                "seq": entry_meta["seq"], "uid": uid, "alias": alias,
                "kind": kind, "text": entry_meta["text"],
                "expires_at": _expiry(cfg)})
    if cfg.get("warn_personal_data") and kind == "text":
        leak = M.has_leak(msg.text or "")
        if leak and not sess.get("leak_warned"):
            await db.ring_session_note(sid, {"leak_warned": True})
            # 🛡 AUDIT-A6 — `leak` تکه‌ای از پیامِ خودِ کاربر است که داخل
            # Markdown خام می‌رفت: هر `_`/`*`/`[` در شماره‌ی تلفنِ تایپ‌شده
            # (مثلاً «0912_34_56») پارس را می‌شکست و **هشدار ایمنی ارسال نمی‌شد**.
            from utils import esc as _esc
            await notify.send_text(
                uid, f"🛡 هشدار: به‌نظر داری <b>{_esc(leak)}</b> می‌فرستی. با غریبه‌ها "
                     "شماره/آیدی/لینک نفرست؛ مسئولیتش با خودته.", parse_mode="HTML")
    if not sess.get("safety_shown") and kind == "text":
        await db.ring_session_note(sid, {"safety_shown": True})
    return {"handled": True, "why": "relayed", "kind": kind, "peer": peer}


def _expiry(cfg):
    from datetime import timedelta
    from time_utils import now_utc
    return now_utc() + timedelta(days=int(cfg.get("evidence_ttl_days", 7)))


async def _relay_media(context, peer: int, msg) -> bool:
    """کپی مدیا بدون ارجاع به پیام مبدأ و بدون برچسب اضافه (§۱۳/§۱۷).

    `caption` پاس داده نمی‌شود ⇒ کپشنِ خودِ کاربر دست‌نخورده کپی می‌شود.
    """
    try:
        await context.bot.copy_message(
            chat_id=peer,
            from_chat_id=msg.chat_id,
            message_id=msg.message_id,
            disable_notification=False,
        )
        return True
    except Exception as e:
        logger.debug("copy_message failed: %s", str(e)[:160])
        return False


async def _relay_by_file_id(context, peer: int, msg, kind: str) -> bool:
    """فقط مدیاهایی که file_id قابل‌بازارسال دارند؛ بدون دانلود فایل.
    کپشن = کپشنِ خودِ کاربر (§۱۷) — هیچ برچسب «چه‌کسی»‌ای اضافه نمی‌شود."""
    cap = (getattr(msg, "caption", None) or None)
    try:
        if kind == "photo" and msg.photo:
            await context.bot.send_photo(peer, msg.photo[-1].file_id, caption=cap)
        elif kind == "voice" and (msg.voice or msg.audio):
            m = msg.voice or msg.audio
            await context.bot.send_voice(peer, m.file_id, caption=cap) if msg.voice \
                else await context.bot.send_audio(peer, m.file_id, caption=cap)
        elif kind == "video" and (msg.video or msg.animation):
            m = msg.video or msg.animation
            await context.bot.send_video(peer, m.file_id, caption=cap)
        elif kind == "document" and msg.document:
            await context.bot.send_document(peer, msg.document.file_id, caption=cap)
        else:
            return False
        return True
    except Exception as e:
        logger.debug("file_id relay failed: %s", str(e)[:160])
        return False


async def persist_buffer_as_evidence(sid: str, report_id: int) -> int:
    """§۳۵ — فقط وقتی گزارش ثبت شد، محتوای بافر روی دیسک می‌نشیند (TTL‌دار)."""
    from database import db
    cfg = await S.get_cfg()
    rows = buffer_snapshot(sid)
    n = 0
    for r in rows:
        if not r.get("text"):
            continue
        await db.ring_evidence_put({
            "_id": f"{sid}:{r['seq']}:r{report_id}", "session_id": sid,
            "report_id": report_id, "seq": r["seq"], "uid": r["uid"],
            "alias": r.get("alias"), "kind": r.get("kind"), "at": r.get("at"),
            "text": r["text"], "expires_at": _expiry(cfg), "reason": "report"})
        n += 1
    return n
