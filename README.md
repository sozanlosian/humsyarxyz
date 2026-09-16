# هامزیار X (HumsYarX)

پلتفرم آموزشی تلگرام‌محور: **ربات تلگرام** + **مینی‌اپ دانشجویی** + **پنل وب ادمین** + **API واحد** روی MongoDB.

## نقشه‌ی سریع

| بخش | مسیر | توضیح |
|---|---|---|
| ربات تلگرام | `bot.py` + `subscription.py` + `start.py` + ... | polling (پیش‌فرض سالم) |
| API | `api/main.py` + `api/routers/` (۲۵ روتر) | FastAPI؛ احراز با `X-Init-Data` تلگرام |
| دیتابیس | `database.py` + `db/` (mixinها) | Motor async روی MongoDB |
| درگاه پرداخت | `payments/zarinpal.py` | زرین‌پال v4 + mock نمایشی |
| مینی‌اپ | `miniapp/` (React + Vite، مسیر `/app/`) | پنل دانشجو |
| وب‌ادمین | `webadmin/` (React + Vite، مسیر `/admin/`) | پنل مدیریت |
| استقرار | `Dockerfile` + `railway.json` + `supervisord` | تک‌کانتینر: API و ربات کنار هم |

پرداخت‌ها: رسید دستی (بررسی ادمین) + زرین‌پال آنلاین + کیف پول داخلی. همه‌ی جریان‌های پولی idempotent و قابل مغایرت‌گیری‌اند (`/admin` → اشتراک‌ها → مغایرت‌گیری).

## شروع سریع (لوکال)

```bash
# ۱) پیش‌نیازها: Python 3.11+‎ و MongoDB لوکال و Node 18+
cp .env.example .env          # و مقادیر واقعی (دست‌کم MONGODB_URI و TELEGRAM_TOKEN)

# ۲) بک‌اند
pip install -r requirements.txt
python -m unittest discover -s tests      # ~۲۳۰ تست؛ بدون Mongo بخشی skip می‌شود
uvicorn api.main:app --port 8000          # API روی :8000
python bot.py                             # ربات (polling) — ترمینال جدا

# ۳) فرانت‌اندها (ترمینال جدا)
cd miniapp  && npm install && npm run dev     # :5173 با VITE_BASE=/
cd webadmin && npm install && npm run dev
```

نکته: درگاه بدون مرچنت در **حالت نمایشی** کار می‌کند (پول واقعی جابه‌جا نمی‌شود).

## تست و کیفیت

```bash
python -m unittest discover -s tests   # گیت CI همین را اجرا می‌کند
python -m pyflakes <file>              # بدون هشدار جدید (۴ هشدار قدیمی شناخته‌شده)
```

## استقرار

تک‌کانتینر Docker روی Railway؛ `supervisord` هم API (`$PORT`) و هم ربات را بالا می‌آورد. هلث‌چک: `/api/health`. جزئیات عملیاتی (حادثه‌ها، بکاپ، درگاه، webhook) در **`docs/runbook.md`**.

## مستندات

- `docs/runbook.md` — ران‌بوک عملیات و بازیابی
- `.env.example` — همه‌ی متغیرهای محیطی با پیش‌فرض
- `FINAL_REPORT.md` — گزارش تاریخی پروژه
