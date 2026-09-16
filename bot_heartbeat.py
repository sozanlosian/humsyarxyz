"""💓 تپش قلب ربات — تنها پل قابل‌مشاهده بین process ربات و API.

چرا این فایل هست؟
در معماری یک‌کانتینری Railway، دو process مستقل اجرا می‌شوند:
  • uvicorn (API)      → پاسخ به /api/* و سرو /app و /admin
  • python bot.py      → polling تلگرام + job_queue
API نمی‌تواند از «زنده بودن process» مطمئن باشد: یک ربات می‌تواند
PID داشته باشد ولی event loop‌ش قفل کرده باشد (blocked loop / اتصال
پوسیده). psutil فقط حضور را می‌بیند، نه سلامت. پس ربات هر N ثانیه
یک heartbeat می‌نویسد و API عمر آن را گزارش می‌کند.

چرا فایل و نه Mongo؟
• صفر بار روی دیتابیس (heartbeat هر ۳۰ ثانیه، ۲۴/۷ = ~۲۹۰۰ نوشتن/روز)
• API حتی وقتی Mongo down است هنوز می‌تواند بگوید ربات زنده بوده
• هر دو process در *یک* container هستند، پس /tmp مشترک است — و دقیقاً
  به همین دلیل است که replica باید ۱ بماند
• اگر روزی bot و API روی ماشین‌های جدا بروند، تنها لازم است
  BOT_HEARTBEAT_FILE به یک مسیر مشترک (یا همان Mongo) تغییر کند

هیچ داده‌ی کسب‌وکاری اینجا نوشته/خوانده نمی‌شود؛ فقط تشخیص سلامت.
فایل به‌صورت atomic نوشته می‌شود (write→rename) تا خواننده هرگز
JSON نصفه نبیند. اگر نوشتن شکست بخورد، بی‌صدا نادیده گرفته می‌شود:
سلامت‌سنجی نباید ربات را بخواباند.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time

logger = logging.getLogger(__name__)

#: مسیر پیش‌فرض عمداً در /tmp است: در Railway فضای دیسک persist نشده
#: و این داده transient است (با هر deploy از صفر شروع می‌شود).
DEFAULT_PATH = "/tmp/humsyar-bot-heartbeat.json"

#: آستانه‌ی کهنه‌بودن. اگر heartbeat از این قدیمی‌تر باشد، stale=True.
#: ۳× دوره‌ی نوشتن — تا یک تأخیر کوتاه (GC، request تلگرام کند) هشدار ندهد.
STALE_MULTIPLIER = 3

#: فاصله‌ی نوشتن heartbeat توسط ربات (ثانیه)
HEARTBEAT_INTERVAL = int(os.getenv("BOT_HEARTBEAT_INTERVAL", "30"))


def heartbeat_path() -> str:
    return (os.getenv("BOT_HEARTBEAT_FILE") or DEFAULT_PATH).strip() or DEFAULT_PATH


def write_heartbeat(extra: dict | None = None) -> bool:
    """یک رکورد تپش ثبت می‌کند. فقط از سمت ربات صدا زده می‌شود.

    True اگر نوشتن موفق بود. هیچ استثنا را به بیرون راه نمی‌دهد.
    """
    path = heartbeat_path()
    payload = {
        "pid": os.getpid(),
        # wall clock — برای گزارش عمر به خواننده‌ی انسانی/دیاگنوستیک
        "at": time.time(),
        "at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        # monotonic — برای تشخیص «چرخه‌ی ربات واقعاً جلو می‌رود»
        "mono": time.monotonic(),
        "seq": _SEQ.next(),
    }
    if extra:
        payload.update(extra)
    try:
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".hb-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        return True
    except Exception as exc:  # pragma: no cover - only on read-only fs
        logger.debug("heartbeat write failed: %s", exc)
        return False


class _Seq:
    n = 0

    def next(self) -> int:
        self.n += 1
        return self.n


_SEQ = _Seq()


def read_heartbeat() -> dict:
    """آخرین تپش + تشخیص عمر. همیشه dict می‌دهد و هرگز raise نمی‌کند.

    کلیدها:
      seen           bool  — آیا اصلاً فایلی پیدا شد
      pid, at, at_iso, seq — همان چیزی که ربات نوشته
      age_seconds    float|None
      stale          bool  — seen و (age > STALE_MULTIPLIER × فاصله)
      error          str   — دلیل «دیدن‌نشدن»، برای دیباگ
    """
    path = heartbeat_path()
    out: dict = {"seen": False, "path": path, "error": ""}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("heartbeat file is not an object")
    except FileNotFoundError:
        out["error"] = "no_heartbeat_file"
        return out
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        return out

    # همه‌ی فیلدهای نوشته‌شده عبور داده می‌شوند (نه فقط لیست ثابت):
    # ربات می‌تواند context تشخیصی اضافه کند و API همان را گزارش کند.
    out.update(data)
    out["seen"] = True
    at = data.get("at")
    if isinstance(at, (int, float)):
        age = time.time() - float(at)
        out["age_seconds"] = round(age, 1)
        out["stale"] = age > HEARTBEAT_INTERVAL * STALE_MULTIPLIER
    else:
        out["age_seconds"] = None
        out["stale"] = True
    return out
