#!/bin/sh
# ════════════════════════════════════════════════════════════════
#  🚂 entrypoint — پوسته‌ی نازک قبل از supervisord
#
#  تنها کار حیاتی اینجا `exec` است: با exec، supervisord همان PID 1
#  می‌شود و سیگنال‌های `docker stop` (SIGTERM) مستقیم به آن می‌رسد؛
#  آن‌وقت supervisor خودش SIGTERM را به api و bot ارسال می‌کند و بعد
#  از stopwaitsecs به SIGKILL ارتقا می‌دهد. بدون exec، شل PID 1 بود و
#  سیگنال‌ها در میانه گم می‌شدند.
#
#  هیچ منطق کسب‌وکاری اینجا نیست و نباید باشد.
# ════════════════════════════════════════════════════════════════
set -e

# Railway همیشه PORT را تزریق می‌کند؛ بقیه محیط‌ها (docker run محلی)
# پیش‌فرض ۸۰۰۰ می‌گیرند. بدون این مقدار، %(ENV_PORT)s در
# supervisord.conf خطای راه‌اندازی می‌داد.
PORT="${PORT:-8000}"
export PORT

# heartbeat ربات: اگر کسی override نکرده باشد، /tmp (ephemeral ولی
# بین دو process یک کانتینر مشترک).
BOT_HEARTBEAT_FILE="${BOT_HEARTBEAT_FILE:-/tmp/humsyar-bot-heartbeat.json}"
export BOT_HEARTBEAT_FILE

# ── هشدارهای محیطی (غیرکشنده) ──
# عمداً fail نمی‌کنیم: سرویس باید بالا بیاید و لاگِ روشن بدهد، نه
# crash-loop بی‌پیام. ADMIN_TOKEN/MONGODB_URI نبودن خودش در log
# API و bot دیده می‌شود.
if [ -z "${MONGODB_URI:-}" ]; then
  echo "[entrypoint] ⚠️ MONGODB_URI تنظیم نشده — API و ربات به دیتابیس وصل نمی‌شوند." >&2
fi
if [ -z "${WEBAPP_URL:-}" ]; then
  echo "[entrypoint] ⚠️ WEBAPP_URL تنظیم نشده — دکمه‌های web_app ربات نمایش داده نمی‌شوند." >&2
  echo "[entrypoint]    مقدار درست: https://<domain-railway>/app" >&2
fi

# صحت وجود build مینی‌اپ — اگر نبود، /app/ عمداً 503 روشن می‌دهد
# (نه صفحه‌ی سفید). اینجا فقط یک خط log اضافه می‌کنیم تا علت در
# ابتدای deploy مشخص باشد.
if [ ! -f /srv/humsyar/miniapp/dist/index.html ]; then
  echo "[entrypoint] ⚠️ miniapp/dist/index.html یافت نشد — /app/ در دسترس نخواهد بود." >&2
fi
if [ ! -f /srv/humsyar/webadmin/dist/index.html ]; then
  echo "[entrypoint] ⚠️ webadmin/dist/index.html یافت نشد — /admin/ در دسترس نخواهد بود." >&2
fi

echo "[entrypoint] PORT=${PORT} · API:/api/* · MiniApp:/app/ · Admin:/admin/"

exec "$@"
