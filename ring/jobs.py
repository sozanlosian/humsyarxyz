"""💍 Ring Street — jobهای دوره‌ای (§۲۲، §۴۳، §۴۵، §۶۴)

دو job، هر دو idempotent و هر دو «بی‌خطر اگر رینگ خاموش باشد»:

  • housekeeping (هر ۳۰ ثانیه): timeout صف، هشدار/بستن sessionهای بی‌فعال،
    رفع claimهای یتیم، هم‌سان‌سازی رجیستری RAM با DB، تازه‌سازی flag.
  • daily (روزانه): چرخش آمار روز، purge شواهد، لاگ خلاصه.

ایمنی ری‌استارت: هیچ state‌ای فقط در RAM نیست؛ همه از Mongo خوانده
می‌شود (§۴۳) و اگر DB موقتاً نایاب باشد، job فقط warning می‌دهد.
"""
from __future__ import annotations

import logging

from telegram.constants import ParseMode

from ring import models as M
from ring import notify
from ring import keyboards as K
from ring import service
from ring import settings as S
from ring import state
from ring import texts
from time_utils import now_utc

logger = logging.getLogger(__name__)

_WARNED: set[str] = set()        # sidهایی که هشدار «نزدیک به پایان» گرفته‌اند (best-effort)


def forget_warning(session_id: str) -> None:
    """«▶️ ادامه گفتگو» ⇒ کاربر برگشته؛ هشدار بعدی هم فرستاده می‌شود."""
    _WARNED.discard(session_id)


SWEEP_LIMIT = 12
SEARCH_TICK_LIMIT = 200          # سقفِ سختِ هر دور (§۴۹ — هزینه ثابت بماند)
SEARCH_TICK_EDIT_EVERY_S = 10    # §۵ — Telegram flood-safe؛ هر ۱ ثانیه نه
NOTIFY_RETRY_LIMIT = 20          # §۳۱ (V6) — حداکثر ۲۰ session در هر دور
UI_REPAIR_LIMIT = 20             # §۱۴ (V6) — حباب‌های یخ‌زده‌ای که ترمیم می‌شوند
ORPHAN_LIMIT = 50                # §۴۸ (V6) — سقفِ ترمیم یتیم‌ها در هر دور


async def ring_search_tick_job(context) -> None:
    """§۴/§۵/§۱۲ (V5) — تایمرِ زندهٔ «در حال جست‌وجو».

    چرا جدا از housekeeping: آن job هر ۳۰ ثانیه است و برای «تمام‌شدن وقت»
    ساخته شده؛ شمارندهٔ ثانیه‌به‌ثانیه و اتمامِ دقیقِ ۱۰ دقیقه به ریتمِ تندتر
    نیاز دارد. هر دور برای هر کاربرِ منتظر حداکثر **یک edit** می‌زند (نه یک
    پیامِ تازه) و برای کسی که session فعال دارد اصلاً کاری نمی‌کند؛ خطای یک
    کاربر بقیه را متوقف نمی‌کند (§۶۵). صفِ خالی = یک query.
    """
    try:
        if not await S.get_flag():
            return
        st = await service.search_tick(limit=SEARCH_TICK_LIMIT,
                                       edit_every_s=SEARCH_TICK_EDIT_EVERY_S)
    except Exception as e:
        logger.warning("ring search tick failed: %s", e)
        return
    if any(st.values()):
        logger.info("RING_SEARCH_TICK edited=%s expired=%s dropped=%s",
                    st.get("edited"), st.get("expired"), st.get("dropped"))


async def _sweep(db, cfg: dict) -> int:
    """تلاش مجدد برای match کردن منتظرهای صف — idempotent (§۶۲)."""
    from ring import handlers as H
    rows = await db.ring_cols.queue.find(
        {"status": "waiting"}, {"user_id": 1, "mode": 1}
    ).sort("queued_at", 1).to_list(SWEEP_LIMIT)
    if len(rows) < 2:
        return 0
    made = 0
    for d in rows:
        uid = int(d["user_id"])
        cur = await db.ring_queue_get(uid)
        if not cur or cur.get("status") != "waiting":
            continue                    # همین لحظه توسط کسی دیگری برداشته شد
        r = await service.try_match(uid, announce=True)
        if r.get("kind") == "matched":
            made += 1
    if made:
        logger.info("RING_QUEUE_SWEPT pairs=%s", made)
    return made


async def ring_housekeeping_job(context) -> None:
    """§۳۵/§۴۹/§۵۱ + §۳۹ — جاروی صف و تخلیهٔ شمارنده‌های آن‌مِوری.

    هزینه‌ی هر دور: ۴ query محدود (§۵۳)."""
    from database import db
    try:
        cfg = await S.get_cfg()
        flag = await S.get_flag()
        if not flag:
            if state.count():
                # فیچر همین حالا خاموش شده ⇒ sessions را ببند (hard) یا بگذار تمام شود (soft)
                if await S.disable_mode() == "hard":
                    await _hard_disable(db)
            return
        closed = warned = repaired = swept = 0
        # ۱) صف‌های کهنه (queue_timeout) — §۲۲ + §۱۲ (V5).
        # در V۵ این کار را `ring_search_tick_job` انجام می‌دهد (با دقت ~۱۰ ثانیه،
        # و edit روی همان پیامِ انتظار)؛ اینجا فقط تورِ ایمنی است: اگر آن شغل
        # مدتی نکارد (crash/تأخیرِ queue) یا کاربر پیامِ انتظار را پاک کرده
        # باشد، *همان* تابع expire صدا زده می‌شود تا کاربر دو نسخهٔ «وقت تمام
        # شد» نگیرد (§۱۰/§۳۶). سقف این‌جا +۶۰ ثانیه است تا با tick مسابقه ندهد.
        for uid in await db.ring_queue_stale(int(cfg["queue_timeout_s"]) + 60):
            q = await db.ring_queue_get(uid)
            if not q or q.get("status") == "in_chat":
                continue
            if await service.expire_search(uid):
                closed += 1
                continue
            await db.ring_queue_leave(uid)
            await service.forget_search_msg(uid, expired=True)
            closed += 1
        # ۲) claimهای یتیم (crash وسط match) — §۶۳
        repaired = await db.ring_queue_repair_claims(max(60, int(cfg["queue_timeout_s"]) // 4))
        # ۲.۵) جاروی صف (§۴۰): اگر زیر همزمانی، دو نفرِ آخر همدیگر را
        # لحظه‌اً claimed ببینند و واگذار کنند، کسی نیست که trigger بعدی را
        # بزند ⇒ این job جفت‌های جامانده را وصل می‌کند. حداکثر SWEEP_LIMIT
        # کاربر در هر دور، و فقط وقتی ≥۲ نفر منتظر باشند (هزینه محدود §۵۳).
        swept = await _sweep(db, cfg)
        # ۳) sessionهای بی‌فعال
        idle_s = int(cfg["session_idle_s"])
        grace = int(cfg["session_grace_s"])
        for sess in await db.ring_session_idle(max(30, idle_s - grace), limit=200):
            sid = sess["session_id"]
            mins = max(1, (idle_s - min(idle_s, idle_s - grace)) // 60 or grace // 60 or 1)
            age = _age_s(sess.get("last_activity_at"))
            if age >= idle_s:
                await service.end_session(None, sid, "idle_timeout")
                await _notify_pair(sess, "⌛ به‌دلیل بی‌فعالیت، گفت‌وگو بسته شد.")
                _WARNED.discard(sid)
                closed += 1
            elif sid not in _WARNED and grace > 0:
                _WARNED.add(sid)
                # §۵۰ — یادآوری بی‌فعالی با دو دکمهٔ روشن: «ادامه گفتگو»
                # (همان چت) و «پایان گفتگو». هیچ دکمه‌ای فقط «متن» نیست.
                for u in (sess.get("slots") or []):
                    await notify.send_text(
                        int(u), texts.idle_prompt(max(1, int((idle_s - age) / 60))),
                        parse_mode=ParseMode.HTML, reply_markup=K.kb_idle_prompt())
                warned += 1
        # ۳.۵) §۳۹ — شمارنده‌های «چرا مچ نشد» که در RAM جمع شده‌اند، همین‌جا
        # روی دیسک می‌نشینند (یک $inc دسته‌ای، نه به‌ازای هر رد).
        from ring import analytics as _A
        await _A.flush_rejects()
        # ۳.۷) §۱۹/§۳۱/§۴۸ (V6) — «تورِ ایمنیِ» قیفِ match. مسیرِ اصلی همان
        # لحظهٔ مچ‌شدن همه‌چیز را انجام می‌دهد؛ این سه فراخوانی فقط برای
        # شکست‌های نیمه‌کاره‌اند (crash/ری‌استارت/۴۲۹/باتِ bind‌نشده):
        #   • کارت مچی که نرسیده → با backoff ۵/۱۵/۶۰ و حداکثر ۳ تلاش
        #   • حباب «در حال جست‌وجو»ی نهایی‌نشده (pend) → همان پیام edit می‌شود
        #   • یتیم‌ها (session/queue/timer ناسازگار) → محافظه‌کارانه ترمیم
        # هیچ‌کدام صف را دوباره پر نمی‌کند و پیام تکراری نمی‌فرستد (per-user
        # «sent» flag در `sessions.notify`).
        try:
            n_not = (await service.retry_pending_notify(limit=NOTIFY_RETRY_LIMIT)).get("retried", 0)
        except Exception as e:
            n_not = 0
            logger.warning("RING_NOTIFY_RETRY_FAIL err=%s", str(e)[:140])
        try:
            n_ui = await service.repair_search_ui(limit=UI_REPAIR_LIMIT)
        except Exception as e:
            n_ui = 0
            logger.warning("RING_UI_REPAIR_FAIL err=%s", str(e)[:140])
        try:
            n_orph = await service.repair_orphans(limit=ORPHAN_LIMIT)
        except Exception as e:
            n_orph = {}
            logger.warning("RING_ORPHAN_REPAIR_FAIL err=%s", str(e)[:140])
        # ۴) هم‌سان‌سازی RAM با DB
        rows = await db.ring_cols.sessions.find({"status": "active"},
                                                {"session_id": 1}).to_list(1000)
        valid = {r["session_id"] for r in rows}
        stale = state.drop_staleuids(valid)
        if stale:
            logger.info("ring: %d entry بیات از RAM حذف شد", stale)
        if closed or warned or repaired or swept or n_not or n_ui or any(n_orph.values()):
            logger.info("💍 رینگ housekeeping: بسته=%s هشدار=%s ترمیم‌claim=%s جارو=%s "
                        "اطلاعیه‌مجدد=%s ui-ترمیم=%s یتیم=%s",
                        closed, warned, repaired, swept, n_not, n_ui, n_orph)
    except Exception as e:
        logger.warning("ring housekeeping ناتمام: %s", e)


async def _hard_disable(db) -> None:
    from ring import state
    for row in state.snapshot():
        await service.end_session(None, row["session_id"], "disabled_hard")
    await db.ring_cols.queue.update_many({"status": {"$in": ["waiting", "claimed", "claiming"]}},
                                        {"$set": {"status": "left", "left_at": now_utc().isoformat()}})
    logger.info("💍 رینگ خاموش شد (hard): sessions و صف بسته شدند")


async def _notify_pair(sess: dict, text: str) -> None:
    for u in (sess.get("slots") or []):
        await notify.send_text(int(u), text)


def _age_s(iso) -> int:
    try:
        t = now_utc().fromisoformat(str(iso))
        if t.tzinfo is None:
            t = t.replace(tzinfo=now_utc().tzinfo)
        return max(0, int((now_utc() - t).total_seconds()))
    except Exception:
        return 10 ** 9      # ناشناخته ⇒ قدیمی فرض کن (fail-closed به سمت بستن)


async def ring_daily_job(context) -> None:
    """چرخش آمار + پاک‌سازی شواهد (§۳۵) — TTL Mongo هم کار را می‌کند؛
    این تابع فقط برای روزهای بدون تردد و لاگ خلاصه است."""
    from database import db
    try:
        purged = await db.ring_evidence_purge()
        ov = await db.ring_overview()
        logger.info("💍 رینگ daily: in_chat=%s waiting=%s گزارش_باز=%s شواهد_purge=%s",
                    ov.get("in_chat"), ov.get("waiting"),
                    ov.get("reports_pending"), purged)
        if purged:
            await db.ring_audit("system", "PURGE_EVIDENCE", "", f"n={purged}", {})
    except Exception as e:
        logger.warning("ring daily job failed: %s", e)
