# syntax=docker/dockerfile:1
# ════════════════════════════════════════════════════════════════════
#  🚂 هامزیار — تصویر یکپارچه‌ی Railway
#
#  یک image، دو process (زیر supervisord):
#    api → uvicorn api.main:app --host 0.0.0.0 --port $PORT
#    bot → python -u bot.py
#
#  و سه namespace روی یک origin:
#    /app/*  → Telegram Mini App   (از سورس، در همین build)
#    /admin/*→ Web Admin             (از سورس، در همین build)
#    /api/*  → FastAPI
#
#  Vercel در این معماری هیچ نقشی ندارد؛ مینی‌اپ هم‌ریشه‌ی API است.
#
#  ⚠️ replica باید ۱ بماند (railway.json / Settings → Replicas) — job_queue
#  و یادآوری‌ها در هر replica جدا اجرا می‌شوند و پیام‌ها تکراری می‌شوند.
#
#  layer caching: فایل‌های package*.json و requirements.txt جدا کپی
#  می‌شوند تا نصب وابستگی‌ها تا زمانی که تغییر نکرده‌اند کش بماند.
#
#  ── قاعده‌ی ترتیب در این فایل (تغییرش نده) ──
#  `COPY` توسط buildkit با کاربر root اجرا می‌شود، ولی `RUN` با
#  `USER`ی که ست شده. پس `USER humsyar` **باید آخرین دستور فایل**
#  باشد: هر RUN/COPY--chown بعد از آن با uid 10001 اجرا می‌شود و
#  مثلاً `chmod +x /entrypoint.sh` روی فایلِ root‌owner با
#  `Operation not permitted` می‌ترکد (دقیقاً همان خطایی که در
#  بیلد Railway دیدیم). برای همین همه‌ی کارهای نیازمند root
#  (useradd، chown، chmod) بالای USER هستند و بعد از USER فقط
#  دستورهای متادیتا (EXPOSE/ENTRYPOINT/CMD/HEALTHCHECK) می‌آیند.
# ════════════════════════════════════════════════════════════════════

# ────────────────────────────────────────────────────────────
#  Stage 1 — فرانت‌اندها (Node فقط برای build؛ در runtime نیست)
# ────────────────────────────────────────────────────────────
FROM node:20-bookworm-slim AS frontend

WORKDIR /build

# ── Mini App ──
# VITE_BASE=/app/ → تمام assetها، فونت‌ها و chunkهای lazy با پیشوند
# /app/ تولید می‌شوند و react-router هم همان را basename می‌گیرد.
ENV VITE_BASE=/app/
COPY miniapp/package.json miniapp/package-lock.json ./miniapp/
# 🛡 RAILWAY-FIX — فلاک‌های گذرای رجیستری npm نباید بیلد را قرمز کنند؛
# ۵ تلاش دانلود (پیش‌فرض npm فقط ۲ است). رفتار موفق بدون تغییر.
RUN npm --prefix ./miniapp ci --no-audit --no-fund --fetch-retries=5 --fetch-retry-mintimeout=10000 --fetch-retry-maxtimeout=60000
COPY miniapp/ ./miniapp/
RUN npm --prefix ./miniapp run build

# ── Web Admin ── (base آن از قبل در webadmin/vite.config.js روی /admin/ است)
COPY webadmin/package.json webadmin/package-lock.json ./webadmin/
# 🛡 RAILWAY-FIX — مشابه مینی‌اپ: retry دانلود در برابر فلاک رجیستری.
RUN npm --prefix ./webadmin ci --no-audit --no-fund --fetch-retries=5 --fetch-retry-mintimeout=10000 --fetch-retry-maxtimeout=60000
COPY webadmin/ ./webadmin/
RUN npm --prefix ./webadmin run build


# ────────────────────────────────────────────────────────────
#  Stage 2 — runtime پایتون
# ────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# PYTHONUNBUFFERED: لاگ‌ها بی‌فاصله به stdout/stderr می‌روند (Railway
# فقط همین را می‌بیند). PIP_NO_CACHE_DIR: لایه‌ی cache در image نماند.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# reportlab/Pillow به libjpeg و zlib برای PDF/تصویر نیاز دارند؛
# curl فقط برای HEALTHCHECK. (supervisor را با pip می‌گذاریم تا
# image قابل بازتولید باشد و به نسخه‌ی apt وابسته نماند.)
# 🛡 RAILWAY-FIX — فلاک گذرای mirror دبیان شایع‌ترین علت قرمزی بی‌دلیل
# بیلد است: اول تا ۳ بار update را retry می‌کنیم و بعد یک update نهایی
# (بدون guard) اجرا می‌شود تا اگر واقعاً شبکه خراب است، بیلد با همان
# خطای روشن apt بایستد — نه با خطای گمراه‌کننده‌ی install.
RUN for i in 1 2 3; do apt-get update && break || sleep 8; done \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      curl \
      libjpeg62-turbo \
      zlib1g \
      libfreetype6 \
 && rm -rf /var/lib/apt/lists/*

# ── MTProto برای فایل‌های بزرگ — بدون نیاز به باینری Local Bot API ──
# رینیم بزرگ (>20MB) از طریق pyrogram (همون منابع Railway) انجام می‌شود
WORKDIR /srv/humsyar

# ── وابستگی پایتون ──
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir "supervisor==4.3.0"

# ── کد بک‌اند + ربات ──
COPY . .

# ── خروجی build فرانت‌اندها (dist داخل git نبود؛ از stage 1 می‌آید) ──
COPY --from=frontend /build/miniapp/dist  ./miniapp/dist
COPY --from=frontend /build/webadmin/dist ./webadmin/dist

# ── کاربر غیرroot (همه‌ی کارهای root همین‌جا، قبل از USER) ──
# /tmp تنها جایی است که این process می‌نویسد (heartbeat ربات، سوکت
# supervisor، pidfile) و از قبل world-writable است؛ هیچ داده‌ی
# ماندگار دیگری روی دیسک نوشته نمی‌شود (خروجی‌ها BytesIO‌اند).
RUN groupadd --gid 10001 humsyar \
 && useradd  --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin humsyar \
 && mkdir -p /tmp \
 && chmod 1777 /tmp \
 && chown -R humsyar:humsyar /srv/humsyar

# PORT فقط پیش‌فرض است؛ Railway خودش PORT را inject می‌کند و آن
# مقدار بر این ENV اولویت دارد (عمداً در Variables ستش نکنید).
ENV PORT=8000 \
    PYTHONPATH=/srv/humsyar \
    BOT_HEARTBEAT_FILE=/tmp/humsyar-bot-heartbeat.json

COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/start_botapi.sh /usr/local/bin/start_botapi.sh

# bit اجرایی را خودمان قطعی می‌کنیم: git معمولاً آن را نگه می‌دارد،
# ولی اگر فایل از ZIP/ویرایشگر ویندوزی رد شود ممکن است ۰۶۴۴ بیاید و
# آن‌وقت ENTRYPOINT هنگام *اجرا* می‌میرد (exec format error /
# Permission denied). این chmod باید این‌جا (هنوز root) انجام شود.
# بقیه‌ی خط‌ها یک self-check زمان build‌اند: اگر entrypoint، config،
# supervisord یا هر دو dist درست نسازده نشوند، build با پیام روشن
# می‌ایستد — نه اینکه سرویس بالا بیاید و /app/ سفید بدهد.
RUN set -eu; \
    chmod 0755 /entrypoint.sh; \
    chmod 0755 /usr/local/bin/start_botapi.sh; \
    chmod 0755 /usr/local/bin/telegram-bot-api || true; \
    test -x /entrypoint.sh                || { echo "Dockerfile selfcheck: /entrypoint.sh executable نیست"; exit 1; }; \
    test -f /etc/supervisor/conf.d/supervisord.conf \
                                          || { echo "Dockerfile selfcheck: supervisord.conf کپی نشده"; exit 1; }; \
    test -f /srv/humsyar/miniapp/dist/index.html  \
                                          || { echo "Dockerfile selfcheck: miniapp/dist نساخته شد"; exit 1; }; \
    test -f /srv/humsyar/webadmin/dist/index.html \
                                          || { echo "Dockerfile selfcheck: webadmin/dist نساخته شد"; exit 1; }; \
    command -v supervisord >/dev/null      || { echo "Dockerfile selfcheck: supervisord در PATH نیست"; exit 1; }; \
    id humsyar >/dev/null                  || { echo "Dockerfile selfcheck: کاربر humsyar ساخته نشده"; exit 1; }; \
    /entrypoint.sh /bin/true >/dev/null     # entrypoint را واقعاً اجرا می‌کند (shebang/CRLF/set -e)

EXPOSE 8000

# startCommand در railway.json همین است؛ اینجا هم به‌عنوان پیش‌فرض
# می‌گذاریم تا `docker run` خالی (بدون config) همان رفتار را داشته باشد.
ENTRYPOINT ["/entrypoint.sh"]
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf", "-n"]

# سلامت API — همان endpointی که Railway healthcheck می‌کند.
# عمداً /api/health و نه /api/health/deep: کرش‌کردن ربات نباید
# کانتینر را unhealthy و restart کند.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" || exit 1

# ── آخرین دستور: کاربر غیرroot ──
# عمداً این‌جاست (قبلش همه‌ی RUNها root باشند). بعد از این خط هیچ
# RUN اضافه نکنید.
USER humsyar
