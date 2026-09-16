"""💍 Ring Street — هندلرها (§۴، §۷..§۱۱، §۱۶..§۲۱، §۴۲)

چرا `ConversationHandler` نه؟
  • ربات از قبل چند ConversationHandler دارد و stateهای آن‌ها در
    `application` نگه داشته می‌شود؛ اضافه‌کردن یک گفت‌وگوی جدید یعنی
    احتمال دعوای state روی متن آزاد کاربر (ریسک شکستن `/start`).
  • ماشین حالت ما در **دیتابیس** می‌ماند (`ring_profiles.state`) ⇒ بعد از
    ری‌استارت هم دقیقاً همان‌جا هستیم که بودیم (§۴۳)، در حالی که
    ConversationHandler در RAM می‌مرد.

اولویت ثبت handler (§۴۲): هندلرهای رینگ *قبل* از مسیریاب یکپارچه‌ی
ر بات ثبت می‌شوند و فیلترشان «کاربر در رجیستری رینگ است» ⇒ وقتی رینگ
خاموش است یا کاربر در flow نیست، هیچupdate‌ای دست‌نخورده به مسیر قبلی
می‌رود (isolation).
"""
from __future__ import annotations

import logging
import re

from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

from ring import keyboards as K
from ring import models as M
from ring import moderation
from ring import notify
from ring import relay
from ring import service
from ring import settings as S
from ring import state
from ring import texts
from time_utils import now_utc, utc_now_iso

logger = logging.getLogger(__name__)

CB = "ring:"
FLOW_TEXT_FIELDS = set(M.PROFILE_FIELDS)          # فیلدهایی که متن آزاد می‌گیرند


# ══════════════════════════════════════════════════════════════
#  کمک‌متدها
# ══════════════════════════════════════════════════════════════

async def _set_st(uid: int, to: str, *, field: str | None = None) -> bool:
    """ماشین حالت در DB (`ring_profiles.state`) — تا ری‌استارت، کاربر
    دقیقاً همان‌جا باشد که بود (§۴۳)."""
    from database import db
    p = await db.ring_profile(uid) or {}
    cur = p.get("state") or M.IDLE
    if not M.can_move(cur, to):
        logger.debug("ring illegal transition %s → %s (uid=%s)", cur, to, uid)
        if to != M.IDLE:
            return False
    await db.ring_profile_update(uid, {"state": to, "pending_field": field})
    return True


def _flow(context) -> dict:
    f = context.user_data.get("ring_flow")
    return f if isinstance(f, dict) else {}


def _flow_set(context, **kw) -> None:
    f = dict(context.user_data.get("ring_flow") or {})
    f.update(kw)
    context.user_data["ring_flow"] = f


def _flow_clear(context) -> None:
    context.user_data.pop("ring_flow", None)


async def _show(q, text: str, kb=None, *, alert: str | None = None,
                md: bool = False):
    """ویرایش پیام دکمه؛ اگر نشد (قدیمی/تکراری) پیام جدید می‌فرستد.

    §۴ (V5) — *خودِ پیام* را برمی‌گرداند، چون صفحهٔ «در حال جست‌وجو» باید
    شناسه‌اش را جا بیاندازد تا تایمر روی همان پیام edit بشود (نه پیامِ تازه).
    «message is not modified» هم برداشت می‌شود: یعنی همان پیام روی صفحه است.
    """
    if alert:
        try:
            await q.answer(alert, show_alert=True)
        except Exception as e:
            # alertِ روی callback بعد از چند ثانیه نامعتبر می‌شود؛ بی‌خطر است،
            # ولی §۱۵ (V6): هیچ exceptی بی‌لاگ نمی‌ماند.
            logger.debug("[RING] alert answer failed: %s", e)
    kw = {"reply_markup": kb} if kb else {}
    if md:
        kw["parse_mode"] = ParseMode.HTML
    try:
        return await q.edit_message_text(text, **kw)
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            return getattr(q, "message", None)
        try:
            return await q.message.reply_text(text, **kw)
        except Exception as e2:
            logger.debug("ring show failed: %s", e2)
    except Exception as e:
        logger.debug("ring show failed: %s", e)
    return None


async def _capture_wait(q, uid: int, msg, *, waited_s: int = 0) -> None:
    """§۴/§۵ (V5) — شناسهٔ پیامِ انتظار را می‌نویسد تا شغلِ تایمر رویش edit کند."""
    if msg is None:
        return
    chat_id = getattr(msg, "chat_id", None) or getattr(
        getattr(msg, "chat", None), "id", None)
    mid = getattr(msg, "message_id", None) or getattr(msg, "id", None)
    if not chat_id or not mid:
        return
    await service.remember_search_msg(uid, int(chat_id), int(mid),
                                      waited_s=int(waited_s or 0))


async def _retire_wait(uid: int, text: str = "✅ انجام شد.") -> None:
    """§۱۰/§۱۲ (V5) — پیامِ «در حال جست‌وجو…» نباید پشتِ سرِ صفحه بماند.

    اگر مچ شد، لغو کرد یا وقتش تمام شد، همان پیام را به یک خطِ بی‌دکمه
    تبدیل می‌کنیم؛ اگر پیام را کاربر پاک کرده باشد، خطا را می‌خوریم (id هم
    پاک شده و تایمر نمی‌ماند).
    """
    from database import db
    p = await db.ring_profile(uid) or {}
    sm = p.get("search_msg") or {}
    await db.ring_search_msg_clear(uid)
    bot = notify._bot()
    if bot is None or not sm.get("m") or not sm.get("c"):
        return
    try:
        await bot.edit_message_text(chat_id=int(sm["c"]), message_id=int(sm["m"]),
                                    text=text)
    except Exception as e:
        logger.debug("[RING] retire wait msg failed uid=%s: %s", uid, e)


async def _age_text() -> str:
    """متن درِ سن، با `min_age` واقعیِ تنظیمات (نه عدد hard-code)."""
    return texts.age_gate(int((await S.get_cfg()).get("min_age", 18)))


async def _guard(update, context):
    """دروازه‌ی ورودی: فیچر روشن + کاربر approved + بن. خروجی: None ادامه."""
    uid = update.effective_user.id
    if not S.flag_sync():
        if not await S.get_flag():
            return "disabled"
    from database import db
    if await db.ring_ban_active(uid):
        return "banned"
    return None


async def _controls(uid: int, sess: dict | None) -> "K.KB | None":
    cfg = await S.get_cfg()
    mode = (sess or {}).get("mode") or (await _profile(uid) or {}).get("mode") or "fun"
    return K.kb_chat(mode, cfg)


async def _profile(uid: int) -> dict | None:
    from database import db
    return await db.ring_profile(uid)


async def _announce_match(uid: int, peer: int, sess: dict, cfg: dict) -> dict:
    """§۱۱/§۲/§۴ (V6) — دیگر اینجا منطقِ مستقلِ نیست: قیفِ مرکزی.

    تا V۵ «کارت مچ + شمارشِ جلسه + نهایی‌کردن پیامِ انتظار» همین‌جا نوشته شده
    بود و بیرون از `service`؛ نتیجه‌اش روی سرورِ زنده: `notify._bot()` None ⇒
    کارت نرفت، شمارش هم نو نشد، ولی بدتر از همه state/UI که به همان تابع گره
    خورده بودند فریز شدند. حالا: DB در `_open_session` نهایی می‌شود و این تابع
    فقط `service.finalize_match` را صدا می‌زند (idempotent؛ شکستِ ارسال در
    `sessions.notify` ثبت می‌شود تا housekeeping جبران کند).
    """
    from ring import service
    sid = sess.get("session_id") or ""
    if not sid:
        logger.warning("RING_ANNOUNCE_NO_SID uid=%s peer=%s", uid, peer)
        return {"ok": False, "why": "no-session-id"}
    return await service.finalize_match(sid, cfg=cfg)


# ══════════════════════════════════════════════════════════════
#  ورودی‌ها: /ring و دکمه‌ی منوی اصلی
# ══════════════════════════════════════════════════════════════

announce_match = _announce_match   # برای job جاروی صف (ring/jobs.py)


async def ring_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    args = [a.lower() for a in (context.args or [])]
    if args and args[0] == "status":
        await _status_card(update, context)
        return
    if not await S.get_flag():
        await update.message.reply_text(texts.disabled())
        return
    if await _guard(update, context) == "banned":
        await update.message.reply_text(texts.ban_notice())
        return
    await _menu(update.effective_message, uid, context)


async def ring_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه‌ی «💍 رینگ استریت» در کیبورد اصلی (§۴۱)."""
    uid = update.effective_user.id
    if not S.flag_sync():
        await update.message.reply_text(texts.disabled())
        return
    await _menu(update.effective_message, uid, context)


async def _menu(msg, uid: int, context) -> None:
    """منوی /ring — وضعیت فعلی کاربر را از DB می‌خواند (§۴۳)."""
    from database import db
    p = await db.ring_profile(uid) or {}
    if not p:
        await _set_st(uid, M.IDLE)
        await msg.reply_text(await _age_text(), reply_markup=K.kb_age(),
                             parse_mode=ParseMode.HTML)
        await _set_st(uid, M.AGE_GATE)
        return
    q = await db.ring_queue_get(uid)
    sess = await db.ring_session_active_for(uid)
    if sess:
        state.attach(uid, await db.ring_session_peer(sess, uid) or uid,
                     sess["session_id"], sess.get("mode", "fun"),
                     sess.get("alias_a", ""), sess.get("alias_b", ""))
    # §۵/§۱۲ — همه‌ی نمای‌ها از یک تابع: state_of (پروفایل + ردیف صف + session)
    st = await service.state_of(uid)
    view = {
        "in_chat": bool(sess),
        "in_queue": bool(q and q.get("status") in ("waiting", "claimed", "claiming")),
        "paused": st == M.US_PAUSED,
        "restricted": st == M.US_RESTRICTED,
        "mode_missing": not p.get("mode"),
        "state": st,
    }
    head = _menu_head(p, q, sess)
    head += f"\n\n📍 وضعیت شما: {M.US_LABELS.get(st, '—')}"
    if await S.maintenance():                       # §۴۵ — بنر وضعیت، نه خطا
        head += "\n\n🟡 رینگ استریت موقتاً در حالت نگهداری است: گفت‌وگوهای جاری " \
                "باز می‌مانند، ولی جفت‌تازگی ساخته نمی‌شود."
    await msg.reply_text(head, reply_markup=K.kb_menu(view), parse_mode=ParseMode.HTML)


def _menu_head(p: dict, q: dict | None, sess: dict | None, *,
               ready: bool = True) -> str:
    """خط وضعیت بالای منو — اول می‌گوید کاربر کجاست، بعد چه می‌تواند بکند."""
    if sess:
        return ("💍 <b>رینگ استریت</b>\n\n"
                "💬 <b>در حال گفتگو</b>\n"
                f"✅ حالت فعلی: {M.MODES.get(sess.get('mode'), '—')}\n\n"
                "«🔄 نفر بعدی» این گفت‌وگو را می‌بندد و تو را به صف برمی‌گرداند؛\n"
                "«⏹ پایان گفتگو» فقط گفت‌وگو را می‌بندد.")
    if q and q.get("status") == "waiting":
        return ("💍 <b>رینگ استریت</b>\n\n🔎 <b>در حال جست‌وجو</b>\n"
                f"✅ حالت فعلی: {M.MODES.get(q.get('mode'), '—')}\n\n"
                "به محض پیدا شدنِ نفر مناسب، همین‌جا پیام می‌دهیم.")
    if p.get("search_expired_at") and not q and not sess:
        # §۳۶ (V5) — صفحهٔ رینگ باید بگوید جست‌وجوی قبلی *تمام* شده، نه اینکه
        # کاربر فرض کند هنوز در صف است.
        return ("💍 <b>رینگ استریت</b>\n\n⌛ <b>زمان جست‌وجوی قبلی تمام شد</b>\n"
                f"   حالت: {M.MODES.get(p.get('mode'), '—')}\n\n"
                "کسی مطابق معیارهای آن زمان پیدا نشد. با «🔎 پیدا کردن نفر» "
                "دوباره شروع کن یا معیارها را بازتر کن.")
    who = (f"👤 ناشناس #{str(p.get('anon_id') or '').lstrip('#')}"
           if p.get("anon_id") else "👤 هنوز پروفایلی نداری")
    mode = M.MODES.get(p.get("mode"), "—")
    tail = ("   با «🔎 پیدا کردن نفر» وارد صف می‌شوی." if ready
            else "   اول چند سؤال کوتاه را جواب بده.")
    return (f"💍 <b>رینگ استریت</b> — {who}\n"
            f"✅ حالت فعلی: {mode}\n"      # §۱۶ (V5) — کاربر باید بداند کجاست
            + ("🟢 آمادهٔ جست‌وجو\n" + tail if p.get("mode") else "📝 هنوز آماده نیستی\n" + tail))


async def _status_card(update: Update, context) -> None:
    from database import db
    uid = update.effective_user.id
    p = await db.ring_profile(uid) or {}
    q = await db.ring_queue_get(uid)
    sess = await db.ring_session_active_for(uid)
    st = M.US_LABELS.get(await service.state_of(uid), "—")   # §۵ — همان حالتِ واحد
    # 🔧 FIX: `q` و `sess` واکشی می‌شدند (دو رفت‌وبرگشت به دیتابیس) ولی هیچ‌وقت
    # در خروجی نمی‌آمدند — یعنی هزینه‌اش پرداخت می‌شد و سودش صفر بود، و
    # کاربر در «/ring status» نمی‌فهمید که اصلاً در صف است یا چت فعال دارد.
    # دقیقاً همان دو چیزی که برای این دستور مهم است. حالا نمایش داده می‌شوند
    # و هیچ داده‌ی هویتیِ طرفِ مقابل هم فاش نمی‌شود (فقط وجود/نبودِ جلسه).
    lines = [
        f"📋 وضعیت رینگ: {st}",
        f"   حالت: {M.MODES.get(p.get('mode'), '—')}",
        f"   وضعیت پروفایل: {p.get('status', 'active')}",
        f"   جلسه‌های تمام‌شده: {int(p.get('sessions_count') or 0)}",
    ]
    if sess:
        lines.append("   💬 یک گفت‌وگوی فعال داری — پیام بفرستی همان‌جا می‌رود.")
    elif q:
        lines.append(f"   ⏳ در صف جست‌وجو هستی (وضعیت: {q.get('status', 'waiting')}).")
    else:
        lines.append("   ⚪️ نه در صفی، نه در گفت‌وگو.")
    lines.append("🔒 اطلاعات هویتی تو جایی ذخیره/نمایش داده نمی‌شود.")
    await update.message.reply_text("\n".join(lines))


# ══════════════════════════════════════════════════════════════
#  dispatcher اصلی callback‌ها
# ══════════════════════════════════════════════════════════════

async def ring_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    uid = update.effective_user.id
    data = q.data or ""
    if not data.startswith(CB):
        return
    key = data[len(CB):]
    parts = key.split(":")
    head = parts[0]
    arg = parts[1] if len(parts) > 1 else ""
    try:
        if head == "home":
            # «↩️ فعلاً نه/بازگشت» روی صفحه‌هایی است که *قبل* از گاردها ساخته
            # می‌شوند (مثل پرسش سن) ⇒ نباید پشت `disabled/banned` گیر کند؛
            # بدنه در `_r_home` است تا route هم ثبت باشد (§۴۲ و تست رجیستری).
            await _r_home(q, context, uid, "", parts)
            return
        blocked = await _guard(update, context)
        if blocked == "disabled":
            await _show(q, texts.disabled())
            return
        if blocked == "banned":
            await _show(q, texts.ban_notice())
            return
        handler = _ROUTES.get(head)
        if handler is None:
            await q.answer()
            return
        await handler(q, context, uid, arg, parts)
    except Exception as e:
        logger.exception("ring callback failed (%s)", key[:40])
        try:
            await _show(q, "⚠️ یک خطای لحظه‌ای رخ داد؛ کمی بعد دوباره امتحان کن.")
        except Exception as e2:
            # §۴۴ (V6) — این یعنی کاربر *هیچ* بازخوردی نگرفته؛ باید در لاگِ
            # warning بماند (روی سرورِ زنده دقیقاً همین گم شده بود).
            logger.warning("RING_ERROR_NOTICE_UNDELIVERED uid=%s err=%s",
                           uid, str(e2)[:140])
    finally:
        try:
            await q.answer()
        except Exception as e2:
            logger.debug("[RING] callback answer failed: %s", e2)


async def _r_age(q, context, uid, arg, parts):
    # §۶۳ (V5) — دکمهٔ «زیر ۱۸ سال» از کیبورد حذف شده، ولی این مسیر می‌ماند:
    # پیام‌هایی که کاربر از قبل روی صفحه‌اش دارد آن دکمه را دارند و دکمهٔ مرده
    # ممنوع (§۹). رفتار هم همان است: خروج بی‌پروفایل.
    if arg == "under":
        await _set_st(uid, M.IDLE)
        await _show(q, texts.too_young())
        return
    r = await service.set_age(uid, M.AGE_INDEX.get(arg, (0, 0))[0])
    if r["kind"] != "ok":
        await _show(q, texts.too_young())
        return
    await _set_st(uid, M.GENDER_PICK)
    await _show(q, texts.gender_ask(), K.kb_gender())


async def _r_gender(q, context, uid, arg, parts):
    await service.set_gender(uid, arg)
    await _set_st(uid, M.MODE_PICK)
    cfg = await S.get_cfg()
    await _show(q, texts.mode_ask(cfg), K.kb_mode(cfg), md=True)


async def _r_mode(q, context, uid, arg, parts):
    # §۱۶/§۴۶ (V5) — «ring:mode» بدون آرگومان = صفحهٔ عوض‌کردن حالت با نشان‌دادنِ
    # حالتِ فعلی؛ «ring:m:<mode>» = انتخاب. گاردِ «وسط جست‌وجو/چت ممنوع» داخل
    # service.set_mode است، پس این UI فقط دلیل را نشان می‌دهد نه بیشتر.
    if not arg:
        p = await _profile(uid) or {}
        await _show(q, texts.mode_switch(p, await S.get_cfg()),
                    K.kb_mode_switch(p, await S.get_cfg()), md=True)
        return
    r = await service.set_mode(uid, arg)
    if r["kind"] == "locked":
        why = r.get("why") or "searching"
        await _show(q, texts.mode_locked(why, arg), K.kb_mode_locked(why), md=True)
        return
    if r["kind"] == "mode_off":
        await _show(q, texts.feature_off(M.MODES.get(arg, arg)))
        return
    if r["kind"] == "ok":
        # §۱۹ — حالتِ تازه persist می‌شود و پیام بعدیِ رینگ همان را نشان می‌دهد
        from database import db
        await db.ring_profile_update(uid, {"search_expired_at": None})
        await q.answer(f"🎭 حالت: {M.MODES.get(r['mode'], r['mode'])}")
    cfg = await S.get_cfg()
    if not await service.rules_pending(uid):
        # §۲۷ — این کاربر نسخهٔ فعلی قوانین را پذیرفته ⇒ نگهش نداریم
        await _set_st(uid, M.IDLE)
        await _menu(q.message, uid, context)
        return
    await _set_st(uid, M.TERMS)
    await _show(q, texts.terms(arg, cfg) + "\n\n" + texts.rules_version_line(cfg),
                K.kb_terms(int(cfg.get("rules_version") or M.RULES_VERSION)), md=True)


async def _r_terms(q, context, uid, arg, parts):
    if arg != "yes":
        await _set_st(uid, M.IDLE)
        await _show(q, texts.declined_terms())
        return
    await service.accept_terms(uid)
    p = await _profile(uid) or {}
    if (p.get("bio") or "").strip():
        await _set_st(uid, M.IDLE)
        await _show(q, "✅ موافقت ثبت شد.", K.kb_menu({"in_chat": False}))
        return
    await _set_st(uid, M.PROFILE, field="bio")
    _flow_set(context, field="bio")
    flow_mark(uid, "bio")
    await _show(q, texts.profile_ask("bio") + "\n\nمی‌توانی «رد» را بزنی.",
                K.KB([[K.B("⏭ رد کردن", callback_data=f"{CB}p:skip")]]))


async def _r_home(q, context, uid, arg, parts):
    """↩️ بازگشت از هر مرحلهٔ رینگ — فقط flow را پاک می‌کند، نه session/صف.

    🔧 FIX تجربهٔ کاربری: قبلاً فقط متنِ «/start را بزن» نمایش داده می‌شد و
    کاربر باید دستی یک دستور تایپ می‌کرد؛ کیبورد اصلی هم اگر در جریان رینگ
    برداشته شده بود برنمی‌گشت. حالا خودِ کیبورد اصلیِ متناسب با نقشِ کاربر
    دوباره فرستاده می‌شود. اگر ساختنِ کیبورد به هر دلیلی شکست بخورد، رفتار
    قبلی (پیام راهنما) به‌عنوان fallback حفظ می‌شود — هیچ مسیری بدتر نمی‌شود.
    """
    _flow_clear(context)
    await _show(q, "↩️ از رینگ خارج شدی.")
    try:
        from database import db
        from utils import get_keyboard_for_user
        user = await db.get_user(uid)
        if user:
            await q.message.reply_text(
                "🏠 منوی اصلی ربات:",
                reply_markup=await get_keyboard_for_user(user, uid),
            )
            return
    except Exception as e:
        logger.warning("[RING] home keyboard restore failed for %s: %s", uid, e)
    await q.message.reply_text("↩️ برای منوی اصلی ربات /start را بزن.")


async def _r_menu(q, context, uid, arg, parts):
    await _menu(q.message, uid, context)


async def _r_go(q, context, uid, arg, parts):
    await _do_search(q, context, uid)


async def _r_next(q, context, uid, arg, parts):
    """⏭ نفر بعدی — اول تأیید (§۲۴)، بعد پایانِ *همین* session و ورود دوباره
    به صف. پارتنر فقط یک اطلاعیه می‌بیند، نه پیامِ ساختگی در گفت‌وگو (§۱۰)."""
    from database import db
    sess = await db.ring_session_active_for(uid)
    if not sess:
        await _do_search(q, context, uid)
        return
    if arg != "yes":
        await _show(q, texts.next_confirm(), K.kb_next_confirm())
        return
    r = await service.next_partner(uid, sess["session_id"])
    await _show(q, "⏭ گفت‌وگو بسته شد و دوباره در صف نشستی. "
                   "به او هم گفته شد که تو رفتی.", None)
    r = r.get("next") or service.Result.of("empty")
    await _finish_search(q, context, uid, r)


async def _do_search(q, context, uid) -> None:
    from database import db
    p = await _profile(uid) or {}
    mode = p.get("mode") or "fun"
    qrow = None
    queue_n = None
    try:                     # شمارشِ bounded (§۵۳) — خطا نباید جست‌وجو را بخواباند
        qrow = await db.ring_queue_get(uid)
        queue_n = await db.ring_queue_waiting_count(mode, [int(uid)], cap=200)
    except Exception as e:
        # §۳۷ — عددِ مطمئن‌نبودنِ صف حذف می‌شود (نه ساختنِ آمار)، و لاگ می‌ماند
        logger.debug("[RING] queue count unavailable uid=%s: %s", uid, e)
    # §۳۴ — «چقدر است» + «چند نفر در صف‌اند» روی همان صفحهٔ جست‌وجو
    waited = int(service._waited_s(qrow))
    await _show(q, texts.searching(mode, p, waited_s=waited, queue_n=queue_n),
                K.kb_searching(), md=True)
    r = await service.search(uid)
    await _finish_search(q, context, uid, r)


async def _finish_search(q, context, uid, r) -> None:
    cfg = await S.get_cfg()
    kind = r.get("kind")
    p = await _profile(uid) or {}
    if kind == "matched":
        sess, peer = r["session"], r["peer"]
        if r.get("silent"):
            # matcherِ دیگری کارت را برای هر دو فرستاده ⇒ فقط صفحه را ببند
            await _show(q, "🎉 یک نفر پیدا شد! کارت گفت‌وگو همین بالا آمد.", None)
            return
        await _announce_match(uid, peer, sess, cfg)
        return
    if kind in ("waiting", "empty", "busy"):
        # §۲/§۳/§۳۶ (V5) — «جست‌وجو» یک *حالت* است، نه نتیجه. تا سقفِ انتظار
        # (queue_timeout_s) تمام نشده هیچ‌وقت «کسی پیدا نشد» نمی‌نویسیم؛ پیام
        # انتظار را نشان می‌دهیم و شناسه‌اش را نگه می‌داریم تا تایمرِ زنده
        # (ring.jobs → service.search_tick) همان را 00:00 → 00:10 → … کند.
        mode = r.get("mode") or p.get("mode") or "fun"
        waited = int(r.get("waited_s") or 0)
        if await service.expire_search(uid):
            return                       # پیامِ «⌛ زمان جست‌وجو تمام شد» ارسال شد
        if kind in ("busy", "waiting") and (r.get("reserving") or kind == "busy"):
            # کاربر در فاصلهٔ claim تا session است؛ کارت دارد می‌آید
            msg = await _show(q, texts.being_picked(mode), K.kb_searching(), md=True)
        else:
            msg = await _show(q, texts.searching(
                mode, p, waited_s=waited, queue_n=r.get("queued"),
                why=r.get("why"),
                timeout_s=max(30, int(cfg.get("queue_timeout_s") or 600))),
                K.kb_searching(), md=True)
        await _capture_wait(q, uid, msg, waited_s=waited)
        return
    if kind == "maintenance":                        # §۴۵
        await _show(q, texts.maintenance(), K.kb_after_end())
        return
    if kind == "rules_outdated":                     # §۲۷
        p = await _profile(uid) or {}
        await _set_st(uid, M.TERMS)
        cfg2 = await S.get_cfg()
        await _show(q, texts.rules(p.get("mode") or "fun", cfg2)
                    + "\n\nقوانین به‌روز شده؛ برای ادامه باید دوباره بپذیری.",
                    K.kb_terms(int(cfg2.get("rules_version") or M.RULES_VERSION)), md=True)
        return
    if kind == "in_chat":
        await _show(q, "💬 هنوز در گفت‌وگویی؛ اول تمامش کن.", await _controls(uid, None))
        return
    if kind == "rate_limited":
        await _show(q, f"🐢 زیاد سریع بود — {r.get('retry_after', 30)} ثانیه بعد دوباره.")
        return
    if kind in ("too_young", "no_gender", "no_mode", "no_terms"):
        await _set_st(uid, M.AGE_GATE if kind == "too_young" else M.TERMS)
        await _show(q, await _age_text(), K.kb_age(), md=True)
        return
    if kind in ("banned", "paused"):
        await _show(q, texts.ban_notice() if kind == "banned"
                    else "⛔ دسترسی‌ات موقتاً محدود است؛ از بخش «🛡 امنیت و قوانین» "
                         "می‌توانی وضعیتت را ببینی.")
        return
    if kind == "mode_off":
        await _show(q, texts.feature_off("این حالت"))
        return
    await _show(q, "🙂 الان چیزی دستم نیست؛ کمی بعد دوباره امتحان کن.")


async def _r_stopq(q, context, uid, arg, parts):
    """⏸ توقف جست‌وجو: خروج از صف · بدون بستن/ساختن session · پروفایل می‌ماند."""
    p = await _profile(uid) or {}
    await service.pause_search(uid)        # تایمرِ انتظار هم خاموش می‌شود (§۱۲)
    await _show(q, texts.search_paused(),
                K.kb_queue(p.get("mode") or "fun", await S.get_cfg(), "paused"))


async def _r_cancelq(q, context, uid, arg, parts):
    """⏹ لغو جست‌وجو (§۱۴ V5) — فقط بیرون از صف؛ بر خلاف «توقف»، ماندگار نیست.

    اگر کاربر وسط گفت‌وگو باشد `cancel_search` هیچی از چت نمی‌کشد (§۴۴).
    """
    r = await service.cancel_search(uid)
    if r["kind"] == "in_chat":
        from database import db
        await _show(q, "💬 تو الان وسط گفت‌وگویی؛ جست‌وجویی باز نیست که لغو شود.",
                    await _controls(uid, await db.ring_session_active_for(uid)))
        return
    if r["kind"] == "matched":
        # §۳۹ (V6) — دکمهٔ «لغو» درست لحظه‌ای خورد که مچ شدی؛ بگوییم چی شد
        # (و نگوییم «لغو شد» که دروغ است) و همان کنترل‌های چت را نشان بدهیم.
        from database import db
        sess = await db.ring_session(r.get("session_id") or "")
        await _show(q, "🎉 همین حالا مچ شدی! لغو نشد — گفت‌وگو از این‌پایین باز است ✅",
                    K.kb_chat((sess or {}).get("mode") or "fun", await S.get_cfg()))
        return
    if r["kind"] == "busy":
        # ردیف توسط matcher برداشته شده (claimed) یا همین حالا عوض شده؛
        # «لغو شد» نشان دادن گمراه‌کننده است. یک دورِ try_match بعد از
        # چند صدم‌ثانیه همه‌چیز را روشن می‌کند، پس فقط صادق‌انه می‌گوییم.
        await _show(q, "⏳ یک لحظه صبر کن — همین الان داشتی مچ می‌شدی؛ نتیجه‌اش را "
                       "همین‌جا می‌بینی.", K.kb_searching())
        return
    await _show(q, texts.search_cancelled(), K.kb_cancelled())


async def _r_resq(q, context, uid, arg, parts):
    """🔎 ادامه جست‌وجو: ورود دوباره به همان صف (اگر در چت باشد، در چت می‌ماند)."""
    await _do_search(q, context, uid)


async def _r_end(q, context, uid, arg, parts):
    """⏹ پایان گفتگو: فقط پایان session، بازگشت به منوی رینگ، بدون ورود به صف."""
    from database import db
    _flow_clear(context)
    sess = await db.ring_session_active_for(uid)
    if not sess:
        await service.leave_queue(uid)
        await _show(q, texts.bye(), K.kb_menu({}))
        return
    await service.stop(uid, sess["session_id"])
    await _retire_wait(uid)                # §۱۲ — تایمرِ یتیم از جست‌وجوی قبلی
    await _show(q, "⏹ گفت‌وگو بسته شد. اگر خواستی، با «🔎 پیدا کردن نفر» "
                    "دوباره وارد صف می‌شوی.", K.kb_after_end())


async def _r_extend(q, context, uid, arg, parts):
    """«▶️ ادامه گفتگو» در یادآوری بی‌فعالی — فقط گفت‌وگو را زنده نگه می‌دارد."""
    from database import db
    sess = await db.ring_session_active_for(uid)
    if not sess:
        await _show(q, texts.no_session(), K.kb_menu({}))
        return
    sid = sess["session_id"]
    try:
        await db.ring_cols.sessions.update_one(
            {"session_id": sid, "status": "active"},
            {"$set": {"last_activity_at": utc_now_iso()}})
    except Exception as e:
        logger.debug("ring extend touch failed: %s", e)
    from ring import jobs
    jobs.forget_warning(sid)
    await _show(q, "👌 گفت‌وگو باز است؛ هر وقت خواستی بنویس.", await _controls(uid, sess))


async def _r_blocked(q, context, uid, arg, parts):
    """🚫 مسدودشده‌ها (§۲۱) — صفحهٔ جدا برای آزاد کردن."""
    from database import db
    rows = await db.ring_blocks_list(uid)
    out = [{"uid": int(r["blocked_user_id"]),
            "anon": (await db.ring_profile(int(r["blocked_user_id"])) or {}).get("anon_id")}
           for r in rows]
    await _show(q, ("🚫 مسدودشده‌ها\n\n"
                    + (f"• {len(out)} نفر را مسدود کرده‌ای؛ با «آزاد کردن» دوباره "
                       "می‌توانید جفت شوید." if out else
                       "کسی را مسدود نکرده‌ای.")),
                K.kb_blocked(out))


async def _r_view(q, context, uid, arg, parts):
    """👁 «چه چیزهایی از پروفایلم دیده شود» (§۳۵)."""
    from database import db
    if arg and arg in M.PROFILE_VIEW:
        cur = await db.ring_profile(uid) or {}
        await service.set_view(uid, arg, not M.view_on(cur, arg))
    p = await db.ring_profile_ensure(uid)
    preview = texts.profile_summary(p, for_whom="peer")
    await _show(q, "👁 <b>چه چیزهایی از پروفایلم دیده شود</b>\n\n"
                   "هر کدام را که خاموش کنی، طرف مقابل آن بخش را نمی‌بیند.\n"
                   "هیچ‌وقت آیدی، نام، شماره یا شناسۀ تلگرامی تو نمایش داده "
                   "نمی‌شود.\n\n"
                   "👀 <b>آنچه طرف مقابل می‌بیند:</b>\n" + preview,
                K.kb_view(p), md=True)


async def _r_rate(q, context, uid, arg, parts):
    """🌟 امتیاز دادن (از منو): برای آخرین گفت‌وگوی تمام‌شده."""
    from database import db
    sess = await db.ring_last_ended_session(uid)
    if not sess:
        await _show(q, "🌟 گفت‌وگوی تمام‌شدۀ تازه‌ای نداری که به آن امتیاز بدهی.",
                    K.kb_menu({}))
        return
    await _show(q, "🌟 این گفت‌وگو چطور بود؟\n\nامتیاز فقط ناشناس ثبت می‌شود و "
                   "هویت هیچ‌کس را افشا نمی‌کند.", K.kb_rating())


async def _r_stop(q, context, uid, arg, parts):
    from database import db
    _flow_clear(context)
    sess = await db.ring_session_active_for(uid)
    if sess:
        await service.stop(uid, sess["session_id"])
        await _show(q, texts.chat_closed_by_you(), K.kb_after_end())
        return
    await service.leave_queue(uid)
    await _show(q, texts.bye(), K.kb_menu({}))


async def _r_chat(q, context, uid, arg, parts):
    from database import db
    sess = await db.ring_session_active_for(uid)
    if not sess:
        await _show(q, texts.no_session(), K.kb_menu({}))
        return
    await _show(q, texts.chat_opened(sess.get("mode") or "fun"),
                await _controls(uid, sess), md=True)


async def _r_rules(q, context, uid, arg, parts):
    p = await _profile(uid) or {}
    cfg = await S.get_cfg()
    body = texts.rules(p.get("mode") or "fun", cfg)
    body += "\n\n🛡 " + "\n🛡 ".join(texts.SAFETY_NOTES[:3])
    body += "\n\n" + texts.rules_version_line(cfg)
    if await service.rules_pending(uid):
        await _show(q, body + "\n\nبرای ادامه، «✅ می‌پذیرم» را بزن.",
                    K.kb_rules_back(), md=True)
        return
    await _show(q, body, K.KB([[K.B("↩️ بازگشت به رینگ", callback_data=f"{CB}menu")]]),
                md=True)


async def _r_mdiff(q, context, uid, arg, parts):
    """«ℹ️ تفاوت این دو حالت» (§۵) — توضیح، بدون تغییر وضعیت."""
    cfg = await S.get_cfg()
    await _show(q, texts.mode_diff(), K.kb_mode(cfg), md=True)


async def _r_profile(q, context, uid, arg, parts):
    from database import db
    p = await db.ring_profile_ensure(uid)
    cfg = await S.get_cfg()
    _flow_set(context, view="profile")
    await _show(q, texts.profile_summary(p) + "\n\nچه چیزی را ویرایش کنم؟",
                K.kb_profile_menu(p, cfg), md=True)


async def _r_field(q, context, uid, arg, parts):
    from database import db
    p = await db.ring_profile(uid) or {}
    if arg == "skip":
        await _set_st(uid, M.IDLE)
        flow_mark(uid, None)
        _flow_set(context, field=None)
        await _show(q, "⏭ رد شد. هر وقت خواستی از «👤 پروفایل».",
                    K.kb_menu({}))
        return
    if arg == "done":
        await _set_st(uid, M.IDLE)
        flow_mark(uid, None)
        _flow_clear(context)
        await _r_profile_done_edit(q, context, uid)
        return
    if arg == "ratings":
        st = await db.ring_rating_stats(uid)
        avg = st.get("avg")
        await _show(q, f"🌟 میانگین: {(str(avg).replace('.', '٫')) if avg is not None else '—'} از ۵ · {st.get('n', 0)} نفر",
                    K.KB([[K.B("↩️ پروفایل", callback_data=f"{CB}profile")]]))
        return
    if arg == "intent":
        await _show(q, "🎯 هدفت از این فضا چیست؟", K.kb_intent())
        return
    if arg == "topics":
        await _show(q, "🏷 موضوع‌های مورد علاقه (حداکثر ۶ تا):",
                    K.kb_topics(p.get("topics")))
        return
    if arg == "prefs":
        # §۱۴ (V5) — ردیفِ صف *اسنیپشات*ی از معیارهاست؛ اگر وسط جست‌وجو معیارها
        # عوض شود، مچِ بعدی با دادهٔ کهنه ساخته می‌شود ⇒ اول از صف بیرون
        # («لغو»، نه «توقف» ماندگار) و تایمر هم می‌میرد. اگر در چت باشد
        # `cancel_search` هیچی از چت نمی‌کشد (§۴۴).
        r = await service.cancel_search(uid)
        note = ("\n\n🔎 جست‌وجو را موقتاً کنار گذاشتم تا معیارهایت کهنه "
                "به کار نرود؛ بعد از تغییر، «🔎 پیدا کردن نفر» را بزن."
                if r["kind"] == "ok" and r.get("queued") else "")
        await _show(q, "⚙️ با چه کسانی حاضری گفت‌وگو کنی؟" + note, K.kb_prefs(p))
        return
    if arg in FLOW_TEXT_FIELDS:
        await _set_st(uid, M.PROFILE, field=arg)
        _flow_set(context, field=arg)
        flow_mark(uid, arg)
        await _show(q, texts.profile_ask(arg) + "\n\n(برای خالی‌کردن «-» را بفرست.)",
                    K.KB([[K.B("⏭ رد کردن", callback_data=f"{CB}p:skip")]]))
        return
    await _show(q, "🤔 این گزینه در دسترس نیست.", K.kb_menu({}))


async def _r_profile_done_edit(q, context, uid) -> None:
    """بازگشت به منوی پروفایل بدون تغییر متن (یک refresh ساده)."""
    from database import db
    p = await db.ring_profile(uid) or {}
    cfg = await S.get_cfg()
    await _show(q, texts.profile_summary(p), K.kb_profile_menu(p, cfg), md=True)


async def _r_intent(q, context, uid, arg, parts):
    await service.update_profile(uid, {"intent": arg})
    await _show(q, "✅ ثبت شد.", K.KB([[K.B("↩️ پروفایل", callback_data=f"{CB}profile")]]))


async def _r_topic(q, context, uid, arg, parts):
    from database import db
    if arg == "done":
        sel = _flow(context).get("topics") or []
        await service.update_profile(uid, {"topics": sel})
        _flow_set(context, topics=None)
        await _show(q, "✅ موضوع‌ها ثبت شد.",
                    K.KB([[K.B("↩️ پروفایل", callback_data=f"{CB}profile")]]))
        return
    p = await db.ring_profile(uid) or {}
    cur = list(_flow(context).get("topics") if _flow(context).get("topics") is not None
               else (p.get("topics") or []))
    if arg in cur:
        cur.remove(arg)
    elif arg in M.TOPICS and len(cur) < 6:
        cur.append(arg)
    _flow_set(context, topics=cur)
    await _show(q, f"🏷 انتخاب‌شده: {len(cur)}/6", K.kb_topics(cur))


async def _clear_expired(uid: int) -> None:
    """§۳۶ — با عوض‌شدن معیار/حالت، «وقت قبلی تمام شد» معنا ندارد."""
    from database import db
    await db.ring_profile_update(uid, {"search_expired_at": None})


async def _r_pref_gender(q, context, uid, arg, parts):
    await service.update_profile(uid, {"pref_gender": arg})
    from database import db
    await _clear_expired(uid)
    p = await db.ring_profile(uid) or {}
    await _show(q, "✅ ترجیح جنسیت ثبت شد.", K.kb_prefs(p))


async def _r_pref_age(q, context, uid, arg, parts):
    from database import db
    if arg == "open":
        _flow_set(context, pa=list(str((await _profile(uid) or {}).get("pref_age_ranges") or "").split(",")))
        await _show(q, "🎂 کدام حلقه‌های سنی؟ (چندتایی مجاز است)",
                    K.kb_pref_age(_flow(context).get("pa")))
        return
    p = await db.ring_profile(uid) or {}
    if arg == "any":
        await service.update_profile(uid, {"pref_age_ranges": "any"})
        await _show(q, "✅ بدون محدودیت سنی.", K.kb_prefs(await db.ring_profile(uid) or {}))
        return
    if arg == "done":
        sel = [x for x in (_flow(context).get("pa") or []) if x in M.AGE_INDEX]
        await service.update_profile(uid, {"pref_age_ranges": ",".join(sel) or "any"})
        _flow_set(context, pa=None)
        await _show(q, "✅ ثبت شد.", K.kb_prefs(await db.ring_profile(uid) or {}))
        return
    cur = list(_flow(context).get("pa") or [])
    if arg in cur:
        cur.remove(arg)
    elif arg in M.AGE_INDEX:
        cur.append(arg)
    _flow_set(context, pa=cur)
    await _show(q, f"🎂 انتخاب: {len(cur)} حلقه", K.kb_pref_age(cur))


async def _r_safety(q, context, uid, arg, parts):
    from database import db
    rows = await db.ring_blocks_list(uid)
    blocks = [{"uid": int(r["blocked_user_id"]), "anon": (await db.ring_profile(int(r["blocked_user_id"])) or {}).get("anon_id"),
               "label": None} for r in rows]
    for b in blocks:
        b["label"] = f"🧷 بلاک‌شده {'#' + b['anon'].lstrip('#') if b.get('anon') else ''}".strip()
    await _show(q, "🛡 <b>امنیت و قوانین</b>\n\n"
                   "• هر وقت اذیت شدی: 🚫 مسدود کردن (دیگر جفت نمی‌شوید) و "
                   "🚨 گزارش (تیم نظارت بررسی می‌کند).\n"
                   "• اگر ناشناس‌آی‌دی کسی را داری، «گزارش بدون چت» هم کار می‌کند.\n"
                   "• هیچ‌کس به شماره، آیدی یا لوکیشن تو دسترسی ندارد.",
                K.kb_safety(blocks), md=True)


async def _r_block(q, context, uid, arg, parts):
    from database import db
    if arg == "yes":
        sess = await db.ring_session_active_for(uid)
        r = await moderation.block(uid, sess["session_id"] if sess else "")
        if r.get("ok"):
            await _show(q, texts.blocked(), K.kb_menu({}))
        else:
            await _show(q, "🙂 الان پارتنری نداری که بلاک شود.")
        return
    if arg == "now":
        sess = await db.ring_session_active_for(uid)
        r = await moderation.block(uid, sess["session_id"] if sess else "")
        await _show(q, texts.blocked() if r.get("ok") else "🙂 در گفت‌وگو نیستی.")
        return
    await _show(q, "مطمئنی؟ او دیگر با تو جفت نمی‌شود و گفت‌وگو بسته می‌شود.",
                K.kb_confirm_block())


async def _r_unblock(q, context, uid, arg, parts):
    if arg and arg.isdigit():
        await moderation.unblock(uid, int(arg))
        await _show(q, texts.unblocked(), K.kb_menu({}))
    else:
        await _show(q, "🤔 نشد.")


async def _r_report(q, context, uid, arg, parts):
    from database import db
    if arg == "anon":
        await _set_st(uid, M.REPORT_WHY, field="report_anon")
        _flow_set(context, mode="anon")
        flow_mark(uid, "report_anon")
        await _show(q, "🔎 ناشناس‌آی‌دی طرف را بفرست (مثلاً #A7K3).")
        return
    if arg == "send" or arg == "send_block":
        r = await _submit_report(uid, context, block_too=(arg == "send_block"))
        if not r.get("ok"):
            await _show(q, "⚠️ " + ("خیلی زود است؛ کمی صبر کن." if r.get("why") == "rate_limited"
                                    else "گفت‌وگوی فعالی برای گزارش پیدا نشد."))
            return
        await _show(q, texts.report_done(r))
        return
    if arg and arg in M.REPORT_REASONS:
        _flow_set(context, reason=arg, sid=(await db.ring_session_active_for(uid) or {}).get("session_id"))
        await _set_st(uid, M.REPORT_WHY, field="report")
        flow_mark(uid, "report")
        await _show(q, f"⚠️ {M.REPORT_REASONS[arg][0]}\n"
                        "چند خط توضیح بده (یا «رد» بفرست):",
                    K.kb_report_send())
        return
    await _show(q, texts.report_ask(), K.kb_report_reasons())


async def _submit_report(uid: int, context, *, block_too: bool) -> dict:
    f = _flow(context)
    sid = f.get("sid")
    reason = f.get("reason") or "other"
    details = f.get("details") or ""
    if f.get("mode") == "anon":
        anon = f.get("anon") or details
        _flow_clear(context)
        return await moderation.report(uid, None, reason, details,
                                       block_too=block_too, target_anon=anon)
    _flow_clear(context)
    return await moderation.report(uid, sid, reason, details, block_too=block_too)


async def _r_reveal(q, context, uid, arg, parts):
    if arg == "ask":
        r = await service.reveal_request(uid)
        await _show(q, {"off": texts.feature_off("معرفی دوطرفه"),
                        "serious_only": "🔒 معرفی فقط در حالت آشنایی جدی ممکن است.",
                        "no_session": texts.no_session()}.get(r["kind"],
                        "🤝 درخواست معرفی برای پارتنرت فرستاده شد."))
        return
    if arg in ("yes", "no"):
        r = await service.reveal_answer(uid, arg == "yes")
        if r["kind"] == "both_yes":
            await _show(q, "🎉 معرفی انجام شد.")
        else:
            await _show(q, "✅ پاسخت ثبت شد." if arg == "yes" else "🙏 باشه، ناشناس می‌مانید.")
        return
    await _show(q, "🤔 دستور ناشناخته.")


_RATING_BY_LABEL = {lbl.split(" ")[-1]: k for k, lbl in M.RATING_LABELS.items()}


async def _r_rating(q, context, uid, arg, parts):
    """امتیاز پس از پایان (§۳۴). پیام‌های قدیمی برچسب فارسی می‌فرستادند ⇒
    هر دو قالب پذیرفته می‌شود. امتیاز منفی هیچ‌وقت بن نمی‌سازد."""
    from database import db
    sess = await db.ring_last_ended_session(uid)
    if not sess:
        await _show(q, "🌟 الان گفت‌وگوی تمام‌شدۀ تازه‌ای نداری.", K.kb_menu({}))
        return
    key = arg if arg in M.RATINGS else _RATING_BY_LABEL.get(str(arg).strip(), "")
    if not key:
        await _show(q, "🤔 نشناختم؛ دوباره از روی دکمه‌ها انتخاب کن.", K.kb_rating())
        return
    r = await moderation.rating(uid, sess["session_id"], key)
    if r.get("ok") and not r.get("duplicate"):
        await _show(q, "🌟 ممنون! بازخوردت فقط به‌صورت ناشناس ثبت شد.", K.kb_after_end())
    else:
        await _show(q, "🤔 امتیاز برای این گفت‌وگو قبلاً ثبت شده بود.", K.kb_after_end())


async def _r_report_anon(q, context, uid, arg, parts):
    """🚨 گزارش بدون چت — با ناشناس‌آی‌دی (§۵۷)."""
    await _r_report(q, context, uid, "anon", parts)


async def _r_restricted(q, context, uid, arg, parts):
    """جایگزین «مکث/ادامه» برای پیام‌های قدیمی (§۳/§۶۶) — دیگر از منو نیست."""
    r = await service.set_paused(uid, arg == "pause")
    await _show(q, "⛔ تا خودت برنگردانی در صف نمی‌شوی." if arg == "pause"
                else "✅ برگشتی؛ با «🔎 پیدا کردن نفر» دوباره در صف بگذار.",
                K.kb_menu({}))


async def _r_delete(q, context, uid, arg, parts):
    if arg == "no":
        await _show(q, "🙂 حذف نشد.", K.kb_menu({}))
        return
    if arg != "yes":
        await _show(q, texts.delete_confirm(), K.kb_delete_confirm())
        return
    await service.delete_all(uid)
    _flow_clear(context)
    await _show(q, "🗑 پروفایل رینگ حذف شد. هر وقت خواستی با /ring از نو.\n"
                   "سوابق نظارتیِ گزارش‌های تأییدشده (برای الزامات حقوقی) "
                   "مطابق سیاست نگهداری نگه داشته می‌شود.")


async def _r_back(q, context, uid, arg, parts):
    step = arg or ""
    if step == "age":
        await _show(q, await _age_text(), K.kb_age(), md=True)
    elif step == "gender":
        await _show(q, texts.gender_ask(), K.kb_gender())
    else:
        await _menu(q.message, uid, context)


_ROUTES = {
    "": _r_menu, "menu": _r_menu, "go": _r_go, "next": _r_next, "stop": _r_stop,
    "chat": _r_chat, "rules": _r_rules, "profile": _r_profile, "safety": _r_safety,
    # ⚠️ هر دو شکلِ کلید ثبت می‌شود: کیبوردها `ring:age:24-26` می‌فرستند
    # و تست‌ها/مستندات `ring:a:24-26` — قبلاً فقط `a` بود ⇒ دکمه‌های بازهٔ
    # سن (و «زیر ۱۸») هیچ هندلری نداشتند و کاربر در مرحلهٔ سن گیر می‌کرد.
    "a": _r_age, "age": _r_age, "gender": _r_gender, "g": _r_gender,
    "mode": _r_mode, "m": _r_mode, "terms": _r_terms, "t": _r_terms,
    "p": _r_field,
    "i": _r_intent, "tp": _r_topic, "pg": _r_pref_gender, "pa": _r_pref_age,
    "block": _r_block, "block_now": _r_block, "unblock": _r_unblock,
    # §۱۴/§۱۵/§۱۷ — سه کنش جدا (قبلاً «مکث/ادامه/پایان» مبهم بود)
    "stopq": _r_stopq, "resq": _r_resq, "end": _r_end, "extend": _r_extend,
    "cancelq": _r_cancelq,   # §۱۴ (V5) — «⏹ لغو جست‌وجو» روی همان پیامِ انتظار
    "mdiff": _r_mdiff, "blocked": _r_blocked, "view": _r_view, "rate": _r_rate,
    "r": _r_report, "report": _r_report, "report_anon": _r_report_anon,
    "reveal": _r_reveal, "rt": _r_rating, "del": _r_delete, "back": _r_back,
    "home": _r_home,     # §۶۳ (V5) — «↩️ فعلاً نه» روی صفحهٔ سن
    # سازگاری با پیام‌های قدیمی (§۳/§۶۶): دکمه‌های «مکث/ادامه/پایان» دیگر در
    # کیبوردها نیستند، ولی روی پیام‌های روی صفحهٔ کاربر همچنان کار می‌کنند.
    "pause": _r_restricted, "resume": _r_restricted,
}


# ══════════════════════════════════════════════════════════════
#  متن‌های flow (پروفایل / توضیح گزارش)
# ══════════════════════════════════════════════════════════════

def _uid_of(obj) -> int | None:
    """هم `Update` (تست‌ها/فراخوانی مستقیم) و هم `Message` (فیلتر PTB)."""
    try:
        for attr in ("effective_user", "from_user"):
            u = getattr(obj, attr, None)
            uid = getattr(u, "id", None)
            if uid is not None:
                return int(uid)
    except Exception:
        return None
    return None


def _flow_filter(update) -> bool:
    """سمک: آیا این کاربر در حالتِ منتظرِ متن است؟"""
    uid = _uid_of(update)
    if uid is None:
        return False
    if not S.flag_sync():
        return False
    return _FLOW_UIDS.get(uid) is not None


_FLOW_UIDS: dict[int, str] = {}


def flow_mark(uid: int, what: str | None) -> None:
    if what:
        _FLOW_UIDS[int(uid)] = what
    else:
        _FLOW_UIDS.pop(int(uid), None)


async def ring_text_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """متن آزاد در حالت PROFILE/REPORT_WHY. اگر flow تمام شد، mark پاک می‌شود
    و از این لحظه پیام‌ها دوباره به مسیریاب ربات می‌روند."""
    uid = update.effective_user.id
    msg = update.effective_message
    what = _FLOW_UIDS.get(uid)
    if not what:
        return
    txt = (msg.text or "").strip()
    from database import db
    if what == "report_anon":
        if txt in ("رد", "skip", "-"):
            _flow_clear(context)
            flow_mark(uid, None)
            await _set_st(uid, M.IDLE)
            await msg.reply_text("🙏 باشه.")
            return
        f = dict(context.user_data.get("ring_flow") or {})
        f["anon"] = txt[:16]
        f["reason"] = f.get("reason") or "other"
        context.user_data["ring_flow"] = f
        flow_mark(uid, None)
        await msg.reply_text("✅ حالا «ثبت گزارش» را بزن.")
        return
    if what == "report":
        f = dict(context.user_data.get("ring_flow") or {})
        if txt in ("رد", "skip", "-"):
            txt = ""
        f["details"] = M.clean_text(txt, 600)
        context.user_data["ring_flow"] = f
        flow_mark(uid, None)
        await _set_st(uid, M.IDLE)
        r = await _submit_report(uid, context, block_too=False)
        await msg.reply_text(texts.report_done(r) if r.get("ok")
                             else "⚠️ گزارش ثبت نشد (شاید گفت‌وگوی فعالی نباشد).")
        return
    field = what
    if txt in ("رد", "skip", "-"):
        flow_mark(uid, None)
        await _set_st(uid, M.IDLE)
        await msg.reply_text("⏭ رد شد.", reply_markup=K.kb_menu({}))
        await _set_st(uid, M.IDLE)
        return
    r = await service.update_profile(uid, {field: txt})
    flow_mark(uid, None)
    await _set_st(uid, M.IDLE)
    if r["kind"] == "rate_limited":
        await msg.reply_text(f"🐢 زیاد شد؛ {r.get('retry_after', 3600)} ثانیه بعد.")
        return
    p = await db.ring_profile(uid) or {}
    await msg.reply_text(f"✅ {M.PROFILE_FIELDS[field][0]} ذخیره شد.\n\n"
                         + texts.profile_summary(p),
                         reply_markup=K.kb_profile_menu(p, await S.get_cfg()),
                         parse_mode=ParseMode.HTML)


def _relay_filter(update) -> bool:
    """آیا این پیام *محتوایِ کاربر* است که باید به پارتنر برود؟ (§۲۰/§۲۱/§۴۶/§۵۸)

    رله فقط کانال «کاربر → پارتنر» است؛ کنترل‌ها «کاربر → بات»‌اند. پس:
      • هیچ برچسبِ دکمهٔ منوی اصلی (ReplyKeyboard) رله نمی‌شود — تپ‌های منو
        باید به هندلرهای خودِ ربات برسند و فقط برای همین کاربر کار کنند (§۱۲/§۴۷)؛
      • برچسبِ کنترل‌های رینگ اگر تایپ شود وارد relay نمی‌شود، ولی هندلر
        خودش راهنمای محلی می‌دهد (§۲۱)؛
      • دستور/کماند هرگز رله نمی‌شود (با `~filters.COMMAND` در register) §۲۸/§۵۳.
    """
    uid = _uid_of(update)
    if not uid or not state.in_chat(uid):
        return False
    msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
    txt = (getattr(msg, "text", None) if msg is not None else None)
    if not txt:                       # مدیا ⇒ محتوای کاربر است (§۱۸)
        return True
    # اولویت با منوی اصلی است: «👤 پروفایل» هم دکمهٔ ربات است هم رینگ ⇒ بگذار
    # به هندلر خودِ ربات برسد (برای همین کاربر کار می‌کند، برای پارتنر هیچ)
    if K.is_main_menu_label(txt):
        return False
    return not K.is_control_label(txt)     # relay خودش راهنمای محلی می‌دهد (§۲۱)


def _menu_bypass_filter(update) -> bool:
    """§۲۳..§۲۶/§۵۰..§۵۳ (V5) — «تپِ منوی اصلی» وسط چت، در *روتور* می‌پیچد.

    چرا این‌جا و نه فقط با فیلترِ رله: فیلترِ رله پیام را «ول» می‌کند و
    هندلرهای بعدیِ همان گروه شانس دوباره دارند؛ اگر روزی ترتیب ثبت عوض
    شود، یک سوراخِ تازه باز می‌شود. این هندلر قبلِ رله ثبت می‌شود، پس
    پیام‌های دکمهٔ ربات اصلاً به کانال «کاربر → پارتنر» نمی‌رسند.
    """
    uid = _uid_of(update)
    if uid is None or not S.flag_sync():
        return False
    if not state.in_chat(uid):
        return False                      # بیرون چت، رله‌ای در کار نیست
    msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
    txt = (getattr(msg, "text", None) if msg is not None else None)
    if not txt or K.is_control_label(txt):
        return False                      # کنترل‌های رینگ هندلرِ خودشان را دارند
    return K.is_menu_tap(txt)


async def ring_menu_bypass(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تپِ منو را به مسیریابِ خودِ ربات می‌دهد — برای همین کاربر، بدون رله."""
    try:
        from bot import unified_text_handler
        # ⚠️ SystemExit هم گرفته می‌شود: اگر bot.py در محیطِ تست (بدون توکن)
        # import نشود، `sys.exit(1)` می‌کند و آن جزو Exception نیست.
    except (Exception, SystemExit) as e:
        logger.debug("[RING] router bypass unavailable: %s", e)
        try:
            await update.effective_message.reply_text(
                "ℹ️ این دکمه برای ربات است و داخل گفت‌وگوی رینگ ارسال نمی‌شود.")
        except Exception as e2:
            logger.debug("[RING] bypass notice failed: %s", e2)
        return
    await unified_text_handler(update, context)


async def ring_relay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """رله‌ی متن/مدیا به پارتنر. اگر رله نشد، چیزی نمی‌فرستیم و update به
    هندلرهای بعدی می‌رسد (چون PTB فقط اولین هندلرِ منطبق را اجرا می‌کند،
    اینجا عملاً «خوردن» پیام یعنی success)."""
    res = await relay.relay(update, context)
    if not res.get("handled"):
        logger.debug("ring relay passed-through: %s", res.get("why"))


# ══════════════════════════════════════════════════════════════
#  ثبت هندلرها (§۴۲) — از bot.py صدا زده می‌شود
# ══════════════════════════════════════════════════════════════

class _RingFlowFilter(filters.MessageFilter):
    """فیلتر سفارشی — در PTB 21.3 هیچ `filters.Function` عمومی وجود ندارد
    (این باگ در boot ربات می‌ترکید؛ تست رجیستری گرفتش)."""
    name = "ring_flow"

    def filter(self, message: Message) -> bool:        # type: ignore[override]
        return _flow_filter(message)

    def __hash__(self) -> int:
        return hash(self.name)


class _RingMenuBypass(filters.MessageFilter):
    """فیلترِ گاردِ منو (همراه `ring_menu_bypass`)."""
    name = "ring_menu_bypass"

    def filter(self, message: Message) -> bool:        # type: ignore[override]
        return _menu_bypass_filter(message)

    def __hash__(self) -> int:
        return hash(self.name)


class _RingRelayFilter(filters.MessageFilter):
    name = "ring_relay"

    def filter(self, message: Message) -> bool:         # type: ignore[override]
        return _relay_filter(message)

    def __hash__(self) -> int:
        return hash(self.name)


async def ring_reentry_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/start` و `/cancel` = خروج از جست‌وجو (§۴۴/§۶۴).

    در `group=1` ثبت می‌شود: PTB برای هر گروه جدا تصمیم می‌گیرد، پس با
    وجودِ بلاک‌بودنِ هندلر اصلی /start در group=0، این هم اجرا می‌شود و
    هیچ‌کدام از جریان‌های فعلی ربات را عوض نمی‌کند. هیچ پیامی هم نمی‌فرستد
    (وظیفه‌اش فقط پاک‌سازی حالت است).
    """
    try:
        uid = update.effective_user.id
    except Exception:
        return
    try:
        if not S.flag_sync() and not await S.get_flag():
            return
        await service.cancel_search(uid)
    except Exception as e:
        logger.debug("ring re-entry cleanup نادیده گرفته شد: %s", e)


def register(app) -> None:
    """همه‌ی هندلرهای رینگ. ترتیب = اولویت."""
    app.add_handler(CommandHandler("ring", ring_command))
    app.add_handler(CommandHandler("start", ring_reentry_cleanup), group=1)
    app.add_handler(CommandHandler("cancel", ring_reentry_cleanup), group=1)
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND & _RingFlowFilter(),
        ring_text_flow))
    # §۵۰..§۵۳ (V5) — گاردِ منو باید *قبل* از رله باشد (PTB: ترتیب ثبت = اولویت)
    app.add_handler(MessageHandler(
        filters.UpdateType.MESSAGE & filters.ChatType.PRIVATE & ~filters.COMMAND
        & _RingMenuBypass(),
        ring_menu_bypass))
    app.add_handler(MessageHandler(
        filters.UpdateType.MESSAGE & filters.ChatType.PRIVATE & ~filters.COMMAND
        & _RingRelayFilter(),
        ring_relay))
    app.add_handler(MessageHandler(
        filters.Regex(r"^💍 رینگ استریت$") & filters.ChatType.PRIVATE,
        ring_menu_button))


def handlers():
    """برای ادغام در لیست `cbs` خودِ bot.py (الگوی فعلی ربات)."""
    return [(ring_callback, rf"^{CB}")]
