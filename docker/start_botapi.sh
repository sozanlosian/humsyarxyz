#!/bin/sh
# Dedicated Rename — الان MTProto (pyrogram) جای Local Bot API binary رو گرفته
# این اسکریپت فقط برای سازگاری supervisord نگه داشته شده و منابع نمی‌گیرد

echo "[botapi] Local Bot API binary not required — MTProto (pyrogram) will handle >20MB renames on same Railway resources" >&2
echo "[botapi] TELEGRAM_API_ID=${TELEGRAM_API_ID:-not_set} TELEGRAM_LOCAL_API_URL=${TELEGRAM_LOCAL_API_URL:-not_set (fallback to MTProto)}" >&2

# Keep process alive so supervisord doesn't restart loop
exec sleep infinity
