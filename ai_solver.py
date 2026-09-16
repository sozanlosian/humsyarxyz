"""
🤖 هوشیار — موتور هوش مصنوعی حل سوالات درسی (متن/عکس)
  ✅ هیچ‌چیز هاردکد نیست: کلید API، ارائه‌دهنده، مدل، محدودیت روزانه و
     دستور سیستمی همگی از bot_settings (پنل ادمین → ai_admin.py) خوانده
     می‌شوند.
  ✅ معماری چندارائه‌دهنده: برای اضافه‌کردن یک AI دیگر (مثلاً OpenRouter/
     OpenAI) فقط یک تابع جدید به STREAM_PROVIDERS اضافه می‌شود — بقیه‌ی کد و
     پنل ادمین دست‌نخورده باقی می‌ماند.
  ✅ محدودیت روزانه‌ی سوال، به‌ازای هر کاربر (روی خودِ سند کاربر در
     دیتابیس ذخیره می‌شود؛ نیازی به کالکشن جدید نیست).
"""
import os
import re
import json
import time
import shutil
import base64
import random
import asyncio
import logging
from utils import esc as _esc   # 🛡 AUDIT-A6 —escape مرکزی (پارامتر quote حفظ است)
from collections import deque, OrderedDict
from datetime import datetime
from time_utils import (
    format_date_fa, format_datetime_fa, format_time_fa,
    now_utc, parse_machine_datetime, today_tehran,
)

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database import db
try:
    from utils_crypto import decrypt_value, encrypt_value, is_encryption_enabled
except Exception:
    decrypt_value = lambda x: x if isinstance(x,str) else (x.get("c","") if isinstance(x,dict) else str(x or ""))
    encrypt_value = lambda x: x
    is_encryption_enabled = lambda: False

logger   = logging.getLogger(__name__)
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))

# ══════════════════════════════════════════════════
#  پیش‌فرض‌ها — فقط وقتی استفاده می‌شن که ادمین هنوز چیزی ست نکرده
# ══════════════════════════════════════════════════
DEFAULT_MODELS = {
    'gemini':     'gemini-2.5-flash',
    'openrouter': 'google/gemma-4-31b-it:free',
    'groq':       'llama-3.3-70b-versatile',
    'cerebras':   'llama-3.3-70b',
    'mistral':    'mistral-large-latest',
    'deepseek':   'deepseek-chat',
    'nvidia':     'deepseek-ai/deepseek-v3',
    'huggingface':'meta-llama/Meta-Llama-3.1-70B-Instruct',
    'together':   'meta-llama/Llama-3.3-70B-Instruct-Turbo',
}

# ══════════════════════════════════════════════════
#  🌊 W9 — کاتالوگ مرکزی providerها و مدل‌ها (منبع واحد حقیقت).
#  بات (ai_admin)، پنل وب و مینی‌اپ همه از همین‌جا می‌خوانند تا
#  هیچ‌جا مدل دستی تایپ نشود. base_urlها اندپوینتِ سازگار با
#  OpenAI هر provider است (همه‌شان /chat/completions دارند).
# ══════════════════════════════════════════════════
PROVIDERS = {
    'gemini': {
        'label': '🟦 Google Gemini',
        'url': None,   # مسیر اختصاصیِ خودش (_stream_gemini)
        'vision': True, 'images': True,
    },
    'openrouter': {
        'label': '🟪 OpenRouter — هاب مدل‌های رایگان (freellm.net)',
        'url': 'https://openrouter.ai/api/v1',
        'vision': True, 'images': True,
    },
    'groq': {
        'label': '🟧 Groq — سریع‌ترین inference',
        'url': 'https://api.groq.com/openai/v1',
        'vision': False, 'images': True,
    },
    'cerebras': {
        'label': '🟨 Cerebras',
        'url': 'https://api.cerebras.ai/v1',
        'vision': False, 'images': False,
    },
    'mistral': {
        'label': '🟠 Mistral — ۱ میلیارد توکن/ماه رایگان',
        'url': 'https://api.mistral.ai/v1',
        'vision': False, 'images': False,
    },
    'deepseek': {
        'label': '🐋 DeepSeek — استدلال قوی و ارزان',
        'url': 'https://api.deepseek.com/v1',
        'vision': False, 'images': False,
    },
    # 🌊 FreeLLM-favorite free providers — OpenAI-compatible base_url
    'nvidia': {
        'label': '🖥️ NVIDIA NIM — مدل‌های آزاد',
        'url': 'https://integrate.api.nvidia.com/v1',
        'vision': True, 'images': False,
    },
    'huggingface': {
        'label': '🤗 Hugging Face Inference',
        'url': 'https://api-inference.huggingface.co/v1',
        'vision': True, 'images': True,
    },
    'together': {
        'label': '🤝 Together AI — رایگان',
        'url': 'https://api.together.xyz/v1',
        'vision': True, 'images': True,
    },
}

# (شناسه‌ی مدل, برچسب فارسی, رایگان؟) — منبع: https://freellm.net/models/?free=1 (299 مدل رایگان، 239 تأیید Live 2026-09-08)
MODEL_CATALOG = {
    'gemini': [
        ('gemini-3.6-flash',      '🌟 Gemini 3.6 Flash (جدیدترین، پیشنهادی)', False),
        ('gemini-3.5-flash',      '🆕 Gemini 3.5 Flash (قوی، استدلال سنگین)', False),
        ('gemini-3.5-flash-lite', '🆕 Gemini 3.5 Flash-Lite (سریع/ارزان)', False),
        ('gemini-2.5-flash',      '⚡ Gemini 2.5 Flash (پایدار)', True),
        ('gemini-flash-latest',   '🔄 Gemini Flash Latest', True),
        ('gemini-2.5-flash-lite', '💨 Gemini 2.5 Flash-Lite (سبک‌تر)', True),
        ('gemini-2.5-pro',        '🧠 Gemini 2.5 Pro (دقیق‌تر)', False),
        ('gemini-2.0-flash-exp',  '🧪 Gemini 2.0 Flash Exp (رایگان)', True),
    ],
    'openrouter': [
        # FreeLLM top free models aggregated under OpenRouter OpenAI-compatible API
        ('deepseek/deepseek-chat-v3-0324:free', '🐋 DeepSeek V3 (رایگان، freellm verified)', True),
        ('deepseek/deepseek-r1:free', '🧠 DeepSeek R1 (رایگان، استدلال)', True),
        ('qwen/qwen3-235b-a22b:free',           '🎯 Qwen3 235B (رایگان)', True),
        ('qwen/qwen3-coder:free',                '👨‍💻 Qwen3 Coder (رایگان)', True),
        ('qwen/qwen2.5-vl-32b-instruct:free',   '👁️ Qwen2.5 VL 32B (رایگان، vision)', True),
        ('google/gemma-3-27b-it:free',           '⚡ Gemma 3 27B (رایگان، vision)', True),
        ('google/gemma-4-31b-it:free',           '⚡ Gemma 4 31B (رایگان، تصویر+متن)', True),
        ('meta-llama/llama-3.3-70b-instruct:free', '🦙 Llama 3.3 70B Instruct (رایگان)', True),
        ('meta-llama/llama-4-maverick:free',    '🦙 Llama 4 Maverick (رایگان)', True),
        ('mistralai/mistral-small-3.1-24b-instruct:free', '🌪 Mistral Small 3.1 24B (رایگان)', True),
        ('thinkingmachines/inkling-small:free', '💡 Inkling Small (رایگان، image-capable)', True),
        ('inclusionai/ling-3.0-flash-sante:free','🌟 Ling 3.0 Sante (رایگان)', True),
        ('nvidia/llama-3.1-nemotron-70b-instruct:free', '🖥️ Nemotron 70B (رایگان)', True),
        ('openrouter/free',                     '🎲 انتخاب خودکار مدل رایگان', True),
    ],
    'groq': [
        ('llama-3.3-70b-versatile', '🦙 Llama 3.3 70B (رایگان، سریع)', True),
        ('llama-3.1-8b-instant',    '⚡ Llama 3.1 8B Instant (رایگان)', True),
        ('openai/gpt-oss-120b',     '🧠 GPT-OSS 120B (رایگان، استدلال)', True),
        ('openai/gpt-oss-20b',      '💨 GPT-OSS 20B (رایگان، سبک)', True),
        ('mixtral-8x7b-32768',      '🔀 Mixtral 8x7B (رایگان)', True),
        ('llama-3.2-11b-vision-preview', '👁️ Llama 3.2 11B Vision (رایگان)', True),
    ],
    'cerebras': [
        ('llama-3.3-70b',  '🦙 Llama 3.3 70B (رایگان)', True),
        ('qwen-3-32b',     '🎯 Qwen3 32B (رایگان)', True),
        ('llama-4-maverick-17b-128e-instruct', '🦙 Llama 4 Maverick 17B (رایگان)', True),
    ],
    'mistral': [
        ('mistral-large-latest', '🌪 Mistral Large (پرچم‌دار)', False),
        ('mistral-small-latest', '💨 Mistral Small (سریع)', False),
        ('codestral-latest',     '👨‍💻 Codestral (کدنویسی)', False),
        ('mistral-small-3.1-24b-instruct:free','💨 Mistral Small 3.1 24B (رایگان FreeLLM)', True),
    ],
    'deepseek': [
        ('deepseek-chat',     '💬 DeepSeek V3 (چت عمومی)', False),
        ('deepseek-reasoner', '🧠 DeepSeek R1 (استدلال عمیق)', False),
        ('deepseek-chat:free', '💬 DeepSeek V3 Free (via OpenRouter)', True),
    ],
    'nvidia': [
        ('deepseek-ai/deepseek-v3', '🐋 DeepSeek V3 (NIM)', True),
        ('moonshotai/kimi-k2-instruct', '🌙 Kimi K2 (vision, free)', True),
        ('qwen/qwen3-235b-a22b', '🎯 Qwen3 235B (NIM)', True),
    ],
    'huggingface': [
        ('black-forest-labs/FLUX.1-schnell', '⚡ Flux Schnell (رایگان، image)', True),
        ('stabilityai/stable-diffusion-3.5-large', '🖼 SD 3.5 Large (رایگان، image)', True),
    ],
    'together': [
        ('meta-llama/Llama-3.3-70B-Instruct-Turbo', '🦙 Llama 3.3 Turbo (رایگان)', True),
        ('Qwen/Qwen2.5-VL-72B-Instruct', '👁️ Qwen2.5 VL 72B (vision)', True),
    ],
}

# مدل‌های تصویر — universal: Gemini native + OpenAI-compatible (OpenRouter/HF/Together) — freellm.net verified image-capable
IMAGE_MODEL_CATALOG = [
    ('gemini-2.5-flash-image',    '🍌 Gemini 2.5 Flash Image (نانوبانانا)', False),
    ('gemini-3-pro-image-preview', '🖼 Gemini 3 Pro Image (پیش‌نمایش)', False),
    ('google/gemini-2.5-flash-image:free', '🍌 Gemini Image Free (OpenRouter)', True),
    ('black-forest-labs/FLUX.1-schnell:free', '⚡ Flux Schnell (رایگان، سریع)', True),
    ('black-forest-labs/FLUX.1-dev:free', '🎨 Flux 1 Dev (رایگان)', True),
    ('stabilityai/stable-diffusion-3.5-large:free', '🖼 SD 3.5 Large (رایگان)', True),
    ('stabilityai/stable-diffusion-xl:free', '🖼 SDXL (رایگان)', True),
    ('thinkingmachines/inkling-small:free', '💡 Inkling Small Image (رایگان)', True),
]


def ai_catalog_payload() -> dict:
    """خروجی JSON کاتالوگ برای هر سه UI (بات/وب/مینی‌اپ)."""
    return {
        'providers': [
            {
                'id': pid,
                'label': meta['label'],
                'vision': meta['vision'],
                'images': meta['images'],
                'default_model': DEFAULT_MODELS.get(pid, ''),
                'models': [
                    {'id': mid, 'label': label, 'free': free}
                    for mid, label, free in MODEL_CATALOG.get(pid, [])
                ],
            }
            for pid, meta in PROVIDERS.items()
        ],
        'image_models': [
            {'id': mid, 'label': label, 'free': free}
            for mid, label, free in IMAGE_MODEL_CATALOG
        ],
        'default_image_model': DEFAULT_IMAGE_MODEL,
    }
DEFAULT_MODEL  = DEFAULT_MODELS['gemini']   # برای سازگاری با کدهای قبلی
DEFAULT_LIMIT  = 15   # سقف روزانه‌ی هر کاربر عادی؛ 0 = نامحدود
MAX_INPUT_CHARS = 2000  # سقف طول متن ورودی کاربر (جلوگیری از هدررفت توکن/هزینه)

# 🎨 تولید تصویر — مدل/کرانه‌ها از settings قابل تغییرند (ai_image_model و
# ai_image_daily_limit)؛ اینها فقط پیش‌فرض‌اند. aspect ratioها همان فهرست
# رسمی gemini-2.5-flash-image (نانوبانانا) است.
DEFAULT_IMAGE_MODEL = 'gemini-2.5-flash-image'
DEFAULT_IMAGE_LIMIT = 10          # سقف روزانه‌ی تصویر؛ 0 = نامحدود
IMG_RETRY_BASE_DELAY = 0.8        # ثانیه — backoff: 0.8s سپس 1.6s
IMG_RETRY_AFTER_CAP = 25.0        # سقف پذیرش Retry-After (ثانیه)
IMAGE_ASPECT_RATIOS = ('1:1', '4:3', '3:4', '16:9', '9:16',
                       '3:2', '2:3', '21:9', '5:4', '4:5')
IMAGE_PROMPT_MIN = 3
IMAGE_PROMPT_MAX = 1000

# 🛡 W1 — پیام واحد بن هوشیار (قبلاً تعریف‌نشده صدا زده می‌شد → NameError)
AI_BANNED_MSG = "⛔️ دسترسیِ شما به هوشیار توسط مدیریت مسدود شده."


class AiImageError(Exception):
    """خطای نگاشت‌شده‌ی تولید تصویر — code ماشین‌خوان + پیام امن کاربر.
    جزئیات خام provider هرگز از اینجا بیرون نمی‌رود."""

    def __init__(self, code: str, user_message: str, detail: str = ''):
        super().__init__(code)
        self.code = code
        self.user_message = user_message
        self.detail = detail


# نگاشت aspectRatio به size برای APIهای OpenAI-compatible
_ASPECT_TO_SIZE = {
    '1:1': '1024x1024', '4:3': '1024x768', '3:4': '768x1024',
    '16:9': '1792x1024', '9:16': '1024x1792', '3:2': '1024x683',
    '2:3': '683x1024', '21:9': '1792x768', '5:4': '1024x819', '4:5': '819x1024',
}

async def _generate_image_gemini(api_key: str, model: str, prompt: str,
                                  aspect_ratio: str, timeout: int, max_retries: int) -> dict:
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/" f"{model}:generateContent")
    payload = {'contents': [{'parts': [{'text': prompt}]}], 'generationConfig': {'responseModalities': ['IMAGE'], 'imageConfig': {'aspectRatio': aspect_ratio}}}
    headers = {'Content-Type': 'application/json', 'x-goog-api-key': api_key}
    last_err = None
    retry_after = None
    for attempt in range(max_retries + 1):
        if attempt:
            if retry_after is not None:
                if retry_after > IMG_RETRY_AFTER_CAP:
                    raise last_err
                delay = retry_after
                retry_after = None
            else:
                delay = IMG_RETRY_BASE_DELAY * (2 ** (attempt - 1))
            await _img_sleep(delay)
        try:
            async with _image_http_client(timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as e:
            last_err = AiImageError('GEMINI_TIMEOUT', 'ساخت تصویر طول کشید؛ دوباره تلاش کن.')
            logger.warning("imggen timeout attempt=%s err=%s", attempt, type(e).__name__)
            continue
        except httpx.HTTPError as e:
            last_err = AiImageError('GEMINI_UNAVAILABLE', 'سرویس تصویر در دسترس نیست؛ کمی بعد دوباره تلاش کن.')
            logger.warning("imggen network error attempt=%s err=%s", attempt, type(e).__name__)
            continue
        if resp.status_code in (429, 500, 502, 503):
            try:
                body_snip = resp.text[:300].replace('\n', ' ')
            except Exception:
                body_snip = ''
            if resp.status_code == 429:
                last_err = AiImageError('GEMINI_RATE_LIMIT', 'سرویس تصویر محدود شده (سهمیه یا ترافیک)؛ چند دقیقه بعد دوباره تلاش کن.')
                ra = resp.headers.get('Retry-After') or resp.headers.get('retry-after')
                try:
                    retry_after = float(ra) if ra else None
                except ValueError:
                    retry_after = None
            else:
                last_err = AiImageError('GEMINI_UNAVAILABLE', 'سرویس تصویر در دسترس نیست؛ کمی بعد دوباره تلاش کن.')
            logger.warning("imggen transient status=%s attempt=%s retry_after=%s body=%s", resp.status_code, attempt, retry_after, body_snip)
            continue
        if resp.status_code in (401, 403):
            raise AiImageError('GEMINI_AUTH_ERROR', 'سرویس تصویر توسط مدیریت آماده نشده است.')
        if resp.status_code == 400:
            raise AiImageError('GEMINI_INVALID_REQUEST', 'این درخواست قابل پردازش نیست؛ توضیح تصویر را تغییر بده.')
        if resp.status_code != 200:
            raise AiImageError('GEMINI_UNAVAILABLE', 'سرویس تصویر پاسخ نامعتبر داد؛ دوباره تلاش کن.')
        try:
            data = resp.json()
        except ValueError:
            raise AiImageError('IMAGE_PARSE_FAILED', 'پاسخ سرویس تصویر خوانده نشد.')
        return _parse_image_response(data)
    raise last_err or AiImageError('GEMINI_UNAVAILABLE', 'ساخت تصویر ناموفق بود؛ دوباره تلاش کن.')

async def _generate_image_openai(api_key: str, model: str, prompt: str,
                                  aspect_ratio: str, provider: str,
                                  timeout: int, max_retries: int) -> dict:
    meta = PROVIDERS.get(provider) or {}
    base = meta.get('url') or 'https://openrouter.ai/api/v1'
    url = f"{base}/images/generations"
    size = _ASPECT_TO_SIZE.get(aspect_ratio, '1024x1024')
    payload = {'model': model, 'prompt': prompt, 'n': 1, 'size': size, 'response_format': 'b64_json'}
    headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
    if provider == 'openrouter':
        headers['HTTP-Referer'] = 'https://humsyar.local'
        headers['X-Title'] = 'Humsyar'
    last_err = None
    retry_after = None
    for attempt in range(max_retries + 1):
        if attempt:
            if retry_after is not None:
                if retry_after > IMG_RETRY_AFTER_CAP:
                    raise last_err
                delay = retry_after
                retry_after = None
            else:
                delay = IMG_RETRY_BASE_DELAY * (2 ** (attempt - 1))
            await _img_sleep(delay)
        try:
            async with _image_http_client(timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as e:
            last_err = AiImageError('IMAGE_TIMEOUT', 'ساخت تصویر طول کشید؛ دوباره تلاش کن.')
            logger.warning("imggen openai timeout provider=%s attempt=%s err=%s", provider, attempt, type(e).__name__)
            continue
        except httpx.HTTPError as e:
            last_err = AiImageError('IMAGE_UNAVAILABLE', 'سرویس تصویر در دسترس نیست؛ کمی بعد دوباره تلاش کن.')
            logger.warning("imggen openai network error provider=%s attempt=%s err=%s", provider, attempt, type(e).__name__)
            continue
        if resp.status_code in (429, 500, 502, 503):
            try:
                body_snip = resp.text[:400].replace('\n', ' ')
            except Exception:
                body_snip = ''
            if resp.status_code == 429:
                last_err = AiImageError('IMAGE_RATE_LIMIT', 'سرویس تصویر محدود شده؛ چند دقیقه بعد دوباره تلاش کن.')
                ra = resp.headers.get('Retry-After') or resp.headers.get('retry-after')
                try:
                    retry_after = float(ra) if ra else None
                except ValueError:
                    retry_after = None
            else:
                last_err = AiImageError('IMAGE_UNAVAILABLE', 'سرویس تصویر در دسترس نیست؛ کمی بعد دوباره تلاش کن.')
            logger.warning("imggen openai transient provider=%s status=%s attempt=%s retry_after=%s body=%s", provider, resp.status_code, attempt, retry_after, body_snip)
            continue
        if resp.status_code in (401, 403):
            raise AiImageError('IMAGE_AUTH_ERROR', f'کلید {meta.get("label", provider)} برای ساخت تصویر تنظیم نشده یا نامعتبر است.')
        if resp.status_code == 400:
            body = ''
            try:
                body = resp.text[:600]
            except Exception:
                pass
            if 'not support' in body.lower() or 'unsupported' in body.lower() or 'image' in body.lower():
                raise AiImageError('IMAGE_NOT_SUPPORTED', 'این مدل قابلیت ساخت تصویر ندارد؛ مدل دیگری (مثلاً Flux یا Gemini Image) را انتخاب کن.')
            raise AiImageError('IMAGE_INVALID_REQUEST', 'این درخواست قابل پردازش نیست؛ توضیح تصویر را تغییر بده.')
        if resp.status_code == 404:
            raise AiImageError('IMAGE_NOT_SUPPORTED', 'این ارائه‌دهنده/مدل از ساخت تصویر پشتیبانی نمی‌کند؛ مدل دیگری را امتحان کن.')
        if resp.status_code != 200:
            raise AiImageError('IMAGE_UNAVAILABLE', 'سرویس تصویر پاسخ نامعتبر داد؛ دوباره تلاش کن.')
        try:
            data = resp.json()
        except ValueError:
            raise AiImageError('IMAGE_PARSE_FAILED', 'پاسخ سرویس تصویر خوانده نشد.')
        try:
            d = (data.get('data') or [])[0] if isinstance(data.get('data'), list) else {}
            b64 = d.get('b64_json') or d.get('b64Json') or d.get('image') or ''
            if not b64:
                url_img = d.get('url')
                if url_img and url_img.startswith('http'):
                    async with _image_http_client(timeout) as client2:
                        r2 = await client2.get(url_img)
                        if r2.status_code == 200:
                            import base64
                            b64 = base64.b64encode(r2.content).decode('utf-8')
            if not b64:
                raise AiImageError('IMAGE_PARSE_FAILED', 'تصویری در پاسخ سرویس پیدا نشد؛ مدل دیگری را امتحان کن.')
            mime = 'image/png'
            return {'mime': mime, 'data_b64': b64}
        except AiImageError:
            raise
        except Exception:
            raise AiImageError('IMAGE_PARSE_FAILED', 'پاسخ سرویس تصویر قابل پردازش نبود.')
    raise last_err or AiImageError('IMAGE_UNAVAILABLE', 'ساخت تصویر ناموفق بود؛ دوباره تلاش کن.')

async def generate_image(api_key: str, model: str, prompt: str,
                         aspect_ratio: str = '1:1',
                         timeout: int = 90, max_retries: int = 2,
                         provider: str | None = None) -> dict:
    aspect_ratio = aspect_ratio if aspect_ratio in IMAGE_ASPECT_RATIOS else '1:1'
    if not api_key:
        raise AiImageError('IMAGE_AUTH_ERROR', 'کلید API برای ساخت تصویر تنظیم نشده.')
    if not provider:
        provider = _detect_provider_for_model(model) or 'gemini'
    if model.startswith('gemini') or provider == 'gemini':
        return await _generate_image_gemini(api_key, model, prompt, aspect_ratio, timeout, max_retries)
    if provider in PROVIDERS and PROVIDERS[provider].get('url'):
        try:
            return await _generate_image_openai(api_key, model, prompt, aspect_ratio, provider, timeout, max_retries)
        except AiImageError as e:
            if e.code == 'IMAGE_NOT_SUPPORTED':
                raise
            raise
    try:
        return await _generate_image_openai(api_key, model, prompt, aspect_ratio, provider or 'openrouter', timeout, max_retries)
    except AiImageError:
        raise


def _image_http_client(timeout: int) -> httpx.AsyncClient:
    """ساخت کلاینت HTTP لایه‌ی تصویر — هوکِ تست‌پذیری (MockTransport)."""
    return httpx.AsyncClient(timeout=timeout)


async def _img_sleep(seconds: float) -> None:
    """هوکِ تست‌پذیری برای انتظار بین retryها."""
    await asyncio.sleep(seconds)


def _parse_image_response(data: dict) -> dict:
    """استخراج تصویر inline از پاسخ generateContent + نگاشت safety.
    تابع خالص — مستقیماً unit-test می‌شود."""
    pf = data.get('promptFeedback') or {}
    if pf.get('blockReason'):
        raise AiImageError('GEMINI_SAFETY_BLOCK',
                           'این درخواست قابل پردازش نیست. لطفاً توضیح '
                           'متفاوتی برای تصویر وارد کنید.')
    candidates = data.get('candidates') or []
    if not candidates:
        raise AiImageError('IMAGE_PARSE_FAILED',
                           'تصویری تولید نشد؛ دوباره تلاش کن.')
    cand = candidates[0]
    if (cand.get('finishReason') or '') in (
            'SAFETY', 'PROHIBITED_CONTENT', 'BLOCKLIST',
            'RECITATION', 'SPII'):
        raise AiImageError('GEMINI_SAFETY_BLOCK',
                           'این درخواست قابل پردازش نیست. لطفاً توضیح '
                           'متفاوتی برای تصویر وارد کنید.')
    parts = ((cand.get('content') or {}).get('parts')) or []
    for part in parts:
        inline = part.get('inlineData') or part.get('inline_data')
        if inline and inline.get('data'):
            mime = (inline.get('mimeType') or inline.get('mime_type')
                    or 'image/png')
            if not mime.startswith('image/'):
                continue
            return {'mime': mime, 'data_b64': inline['data']}
    raise AiImageError('IMAGE_PARSE_FAILED',
                       'تصویری در پاسخ سرویس پیدا نشد؛ دوباره تلاش کن.')

# ══════════════════════════════════════════════════
#  حافظه‌ی مکالمه — ⚠️ فیکس: قبلاً فقط توی RAM بود و با هر ری‌استارتِ
#  سرور (که این چند روز به‌خاطرِ آپدیت‌های پیاپی زیاد اتفاق افتاد)
#  کاملاً پاک می‌شد — انگار هوشیار «حافظه‌ی ماهی» داشت. حالا روی سندِ
#  خودِ کاربر توی دیتابیس ذخیره می‌شه: پایدار در برابرِ ری‌استارت، ولی
#  فشرده — با $slice همیشه فقط چند آیتمِ آخر نگه داشته می‌شه، نه یه
#  آرشیوِ بی‌نهایت‌رشد.
# ══════════════════════════════════════════════════
MEMORY_TTL_SECONDS   = 6 * 60 * 60   # ۶ ساعت بی‌فعالیتی → شروعِ تازه (نه فراموشیِ زودهنگام)
MAX_HISTORY_ITEMS    = 8             # ۸ آیتم = ۴ سوال + ۴ جواب اخیر
REPORT_CACHE_MAX     = 2000      # سقفِ حافظه‌ی کش «گزارش پاسخ» (هرس LRU)
DEFAULT_PROMPT = (
    "تو «هوشیار» هستی؛ دستیار هوش مصنوعیِ ربات هامزیار (Humsyar) برای "
    "دانشجویان دانشگاه علوم پزشکی هرمزگان. یه دستیار باحال، خودمونی و "
    "بامعرفتی که هم می‌تونه احوال‌پرسی کنه و گپ بزنه، هم وقتی پای درس "
    "وسط باشه حسابی حرفه‌ای و دقیق جواب بده.\n\n"

    "🎯 شخصیت و لحن\n"
    "- خودمونی، گرم و بامزه باش؛ مثل یه هم‌کلاسیِ باهوش‌تر که همیشه "
    "حاضر به کمکه، نه یه ربات خشکِ اداری.\n"
    "- اگه کاربر فقط سلام کرد، حال‌پرسی کرد یا خواست گپ بزنه، راحت و "
    "طبیعی جواب بده — لازم نیست هر پیام رو تبدیل به یه درس کنی.\n"
    "- می‌تونی توی موضوعات مختلف (نه فقط پزشکی) هم باهاش حرف بزنی؛ "
    "کنجکاو و بامزه باش، ولی همیشه صادق بمون و چیزی رو که نمی‌دونی با "
    "اطمینانِ دروغین جا نزن.\n"
    "- اگه سوالی درباره‌ی خودِ ربات هامزیار پرسید، خودمونی توضیح بده که "
    "برای اطلاعات کامل‌تر ربات بهتره از منوی اصلی یا پشتیبانی کمک "
    "بگیره.\n\n"

    "📚 وقتی پای سوال درسی وسطه (متن یا عکس)\n"
    "۱. برای تست چندگزینه‌ای:\n"
    "   • خط اول: «✅ گزینه‌ی X صحیح است»\n"
    "   • بعدش در ۲ تا ۴ خط، دلیل علمی‌اش رو دقیق و بی‌حاشیه بگو\n"
    "   • اگه لازم بود، یه اشاره‌ی کوتاه هم به چرایی رد شدن گزینه‌های "
    "پرتکرارِ اشتباه بکن\n"
    "۲. برای سوال باز/تشریحی: پاسخ رو مرتب، خلاصه و در حد ۴ تا ۶ خط "
    "بده؛ اگه فهرست‌وار روشن‌تره از لیست کوتاه استفاده کن.\n"
    "این قالب‌ها یه راهنمان، نه یه چارچوب سفت‌وسخت — اگه سوال طوریه که "
    "یه توضیح متفاوت بهتر جواب می‌ده، همون‌جوری برو جلو.\n\n"

    "🔍 صداقت علمی (این بخش مهمه، حتی توی لحن راحت)\n"
    "- هیچ‌وقت حدس رو جای دونستن جا نزن. اگه عکس نامفهوم بود یا سوال "
    "مبهم بود، رک بگو متوجه نشدی و بخواه واضح‌تر بفرسته.\n"
    "- اگه بین منابع/گایدلاین‌های رایج اختلاف‌نظر هست، بگو که اختلاف‌نظر "
    "وجود داره، به‌جای این‌که یکی رو قطعی جا بزنی.\n"
    "- اسم کتاب، منبع یا آمار رو الکی نساز؛ اگه مطمئن نیستی از کجا "
    "اومده، اصلاً اشاره نکن.\n\n"

    "⚕️ یه‌ذره احتیاط پزشکی\n"
    "- برای چیزای حساس (دوز دارو، مقادیر مرزی آزمایشگاهی، تصمیم "
    "درمانی) با احتیاط جواب بده و در آخر یه یادآوری کوچیک بذار که با "
    "منبع درسی یا استاد چک بشه.\n"
    "- این یه ابزار کمک‌آموزشیه، نه جایگزین مشاوره‌ی پزشکیِ واقعی برای "
    "بیمار واقعی.\n\n"

    "🚫 فقط همین یکی مهمه\n"
    "- هیچ‌وقت توی پاسخت متن‌های فنیِ داخلی، برچسب ارزیابی/دسته‌بندیِ "
    "ایمنی یا فراداده نشون نده — فقط همون جوابی که کاربر منتظرشه."
)


# ══════════════════════════════════════════════════
#  خطاهای اختصاصی
# ══════════════════════════════════════════════════
class AIError(Exception):
    """خطای قابل‌نمایش به کاربر/ادمین."""


class AIQuotaError(AIError):
    pass


class AIConfigError(AIError):
    pass


# ══════════════════════════════════════════════════
#  حافظه‌ی مکالمه (پایدار، روی دیتابیس — نه RAM؛ توضیح در بالا)
# ══════════════════════════════════════════════════

async def _get_history(uid: int) -> list:
    items, updated_at = await db.ai_get_memory(uid)
    if not items:
        return []
    if updated_at and (now_utc() - parse_machine_datetime(updated_at)).total_seconds() > MEMORY_TTL_SECONDS:
        return []   # قدیمیه؛ نادیده‌اش می‌گیریم (خودش با remember بعدی جایگزین می‌شه)
    return [{'role': it.get('r'), 'text': it.get('t', '')} for it in items]


async def _remember(uid: int, role: str, text: str) -> None:
    if not text:
        return
    try:
        await db.ai_remember(uid, role, text, MAX_HISTORY_ITEMS)
    except Exception:
        logger.exception("ذخیره‌ی حافظه‌ی مکالمه‌ی هوشیار ناموفق بود")


async def _clear_memory(uid: int) -> None:
    try:
        await db.ai_clear_memory(uid)
    except Exception:
        logger.exception("پاک‌کردنِ حافظه‌ی مکالمه‌ی هوشیار ناموفق بود")


# ══════════════════════════════════════════════════
#  کشِ «گزارش پاسخ نامناسب» — نگاشتِ (chat_id, message_id) به
#  متن سوال/جواب، فقط برای چند دقیقه‌ای که دکمه‌ی 🚩 زیر پیام فعاله.
#  این هم فقط RAM هست، با سقف LRU که رشدش رو محدود می‌کنه.
# ══════════════════════════════════════════════════
_report_cache: "OrderedDict[str, dict]" = OrderedDict()


def _cache_for_report(chat_id: int, message_id: int, uid: int, name: str,
                       question: str, answer: str) -> None:
    key = f"{chat_id}:{message_id}"
    _report_cache[key] = {
        'uid': uid, 'name': name or '—',
        'question': question or '—', 'answer': answer or '—',
    }
    _report_cache.move_to_end(key)
    while len(_report_cache) > REPORT_CACHE_MAX:
        _report_cache.popitem(last=False)


# ══════════════════════════════════════════════════
#  تنظیمات — همه از bot_settings (کلید-مقدار عمومی دیتابیس)
# ══════════════════════════════════════════════════

DEFAULT_DISABLED_MSG = "🤖 بخش هوش مصنوعی توسط مدیریت غیرفعال شد."


def _detect_provider_for_model(model_id: str) -> str | None:
    """تشخیص provider از روی model_id با کاتالوگ."""
    if not model_id:
        return None
    mid = model_id.strip()
    for pid, models in MODEL_CATALOG.items():
        for m_id, _, _ in models:
            if m_id == mid:
                return pid
    for m_id, _, _ in IMAGE_MODEL_CATALOG:
        if m_id == mid:
            if m_id.startswith('gemini'):
                return 'gemini'
            if 'FLUX' in m_id or 'stable' in m_id.lower() or 'flux' in m_id.lower():
                return 'openrouter'
            if 'gemini' in m_id:
                return 'gemini'
            return 'openrouter'
    if '/' in mid:
        if ':free' in mid or '/' in mid:
            return 'openrouter'
    if mid.startswith('gemini'):
        return 'gemini'
    return None


def _maybe_decrypt(v):
    if isinstance(v, dict) and "c" in v:
        return decrypt_value(v)
    if isinstance(v, str) and v.startswith("gAAAAA"):
        # bare Fernet token stored as string (legacy)
        return decrypt_value(v)
    return v

def _load_vault(raw: dict) -> dict:
    vault: dict = {}
    raw_vault = raw.get('ai_api_keys', '')
    # W1: decrypt if encrypted dict
    if isinstance(raw_vault, dict) and raw_vault.get("enc"):
        try:
            raw_vault = decrypt_value(raw_vault)
        except: raw_vault = ""
    if raw_vault:
        if isinstance(raw_vault, dict):
            vault = dict(raw_vault)
        elif isinstance(raw_vault, str):
            raw_vault = raw_vault.strip()
            if raw_vault:
                try:
                    loaded = json.loads(raw_vault)
                    if isinstance(loaded, dict):
                        vault = loaded
                    elif isinstance(loaded, str) and loaded.startswith("gAAAAA"):
                        vault = json.loads(decrypt_value(loaded) or "{}") if decrypt_value(loaded) else {}
                except Exception:
                    # maybe encrypted JSON string
                    try:
                        dec = decrypt_value(raw_vault)
                        loaded = json.loads(dec)
                        if isinstance(loaded, dict): vault = loaded
                    except: vault = {}
    # legacy single key fallback (may be encrypted)
    legacy = raw.get('ai_api_key')
    legacy = _maybe_decrypt(legacy) if legacy is not None else ""
    legacy = (legacy or "").strip()
    provider = raw.get('ai_provider', 'gemini')
    if legacy and not vault:
        vault[provider] = legacy
    for pid in PROVIDERS:
        kv = raw.get(f'ai_api_key_{pid}')
        kv = _maybe_decrypt(kv) if kv is not None else ""
        k = (kv or "").strip()
        if k and pid not in vault:
            vault[pid] = k
    return vault


async def get_ai_config() -> dict:
    raw = await db.get_settings_by_prefix('ai_')
    provider = (raw.get('ai_provider', 'gemini') or 'gemini').strip() or 'gemini'
    if provider not in PROVIDERS:
        provider = 'gemini'
    personas_raw = raw.get('ai_personas', '{}')
    try:
        personas = json.loads(personas_raw) if isinstance(personas_raw, str) else (personas_raw or {})
    except (ValueError, TypeError):
        personas = {}
    vault = _load_vault(raw)
    model = raw.get('ai_model') or DEFAULT_MODELS.get(provider, DEFAULT_MODEL)
    detected = _detect_provider_for_model(model)
    if detected and detected != provider and detected in vault and vault.get(detected):
        provider = detected
    api_key = vault.get(provider) or raw.get('ai_api_key', '') or ''
    image_model = raw.get('ai_image_model') or DEFAULT_IMAGE_MODEL
    image_enabled = str(raw.get('ai_image_enabled', '1')) not in ('0', 'false', 'False', '')
    image_daily_limit = int(raw.get('ai_image_daily_limit', DEFAULT_IMAGE_LIMIT) or 0)
    image_provider_raw = (raw.get('ai_image_provider') or '').strip()
    if image_provider_raw and image_provider_raw in PROVIDERS:
        image_provider = image_provider_raw
    else:
        d2 = _detect_provider_for_model(image_model)
        image_provider = d2 or provider
        if image_provider not in PROVIDERS:
            image_provider = provider
    image_api_key = vault.get(image_provider) or vault.get(provider) or raw.get('ai_api_key', '') or ''
    return {
        'enabled':          bool(raw.get('ai_enabled', False)),
        'provider':         provider,
        'api_key':          api_key,
        'api_keys':         vault,
        'vault':            vault,
        'model':            model,
        'daily_limit':      int(raw.get('ai_daily_limit', DEFAULT_LIMIT) or 0),
        'system_prompt':    raw.get('ai_system_prompt', DEFAULT_PROMPT),
        'disabled_message': raw.get('ai_disabled_message', ''),
        'personas':         personas,
        'thinking':         raw.get('ai_thinking', 'auto'),
        'image_enabled':    image_enabled,
        'image_model':      image_model,
        'image_provider':   image_provider,
        'image_api_key':    image_api_key,
        'image_daily_limit': image_daily_limit,
    }


async def set_api_key_for_provider(provider: str, key: str) -> None:
    provider = (provider or 'gemini').strip() or 'gemini'
    key = (key or '').strip()
    raw = await db.get_settings_by_prefix('ai_')
    vault = _load_vault(raw)
    if key:
        vault[provider] = key
    else:
        vault.pop(provider, None)
    # W1: encrypt vault JSON if FERNET_KEY enabled
    vault_json = json.dumps(vault, ensure_ascii=False)
    if is_encryption_enabled():
        await db.set_setting('ai_api_keys', encrypt_value(vault_json))
    else:
        await db.set_setting('ai_api_keys', vault_json)
    enc_key = encrypt_value(key) if is_encryption_enabled() and key else (key or "")
    if key:
        await db.set_setting(f'ai_api_key_{provider}', enc_key)
    else:
        await db.set_setting(f'ai_api_key_{provider}', '')
    cur = (raw.get('ai_provider') or 'gemini').strip() or 'gemini'
    if provider == cur and key:
        await db.set_setting('ai_api_key', enc_key if is_encryption_enabled() else key)
    elif provider == cur and not key:
        await db.set_setting('ai_api_key', '')


async def delete_api_key_for_provider(provider: str) -> None:
    await set_api_key_for_provider(provider, '')


async def set_ai_setting(key: str, value) -> None:
    await db.set_setting(f'ai_{key}', value)


async def save_persona(name: str, prompt: str) -> None:
    """پرسونای فعلی رو با یه اسم ذخیره می‌کنه تا بعداً سریع بشه بهش سوییچ کرد."""
    cfg = await get_ai_config()
    personas = cfg['personas']
    personas[name.strip()[:40]] = prompt
    await set_ai_setting('personas', json.dumps(personas, ensure_ascii=False))


async def delete_persona(name: str) -> None:
    cfg = await get_ai_config()
    personas = cfg['personas']
    personas.pop(name, None)
    await set_ai_setting('personas', json.dumps(personas, ensure_ascii=False))


# ══════════════════════════════════════════════════
#  ارائه‌دهنده‌ها (Providers)
#  برای افزودن یک AI جدید: یک تابع async با همین امضا بنویس و در
#  دیکشنری STREAM_PROVIDERS پایین ثبتش کن. سپس از پنل ادمین می‌شود روی
#  provider جدید سوییچ کرد — بدون تغییر جای دیگری از کد.
# ══════════════════════════════════════════════════

# ══════════════════════════════════════════════════
#  ⚠️ قابلیتِ جدید: Function Calling — هوشیار می‌تونه واقعاً از
#  دیتابیسِ خودِ هامزیار (برنامه/نمراتِ همون دانشجو) بخونه، نه اینکه
#  حدس بزنه. فقط وقتی uid داریم (یعنی یه دانشجوی واقعی داره سوال
#  می‌پرسه، نه تستِ ادمین) فعال می‌شه.
# ══════════════════════════════════════════════════
# ══════════════════════════════════════════════════
#  ابزارهایی که به همه‌ی دانشجوها داده می‌شن (uid فقط «همینه که داره
#  چت می‌کنه»، هیچ‌کدوم پارامترِ آیدی/یوزرنیمِ ورودی نمی‌گیرن).
#
#  ⚠️ قانونِ امنیتیِ ثابت — هیچ‌وقت نقض نشه: هر تابعی که اینجا اضافه
#  می‌شه باید فقط و فقط دیتای «uid» ی که خودِ Gemini در زمانِ اجرا از
#  ما می‌گیره رو بخونه (که ما خودمون، نه مدل، تعیینش می‌کنیم — همون
#  آیدیِ تلگرامِ واقعیِ درخواست‌دهنده). هیچ تابعِ دانشجویی نباید یک
#  پارامترِ «آیدی/یوزرنیم/اسمِ کاربرِ دیگر» بگیره؛ وگرنه یه دانشجو با
#  فریب‌دادنِ مدل (مثلاً «فرض کن من آیدی ۱۲۳۴۵۶ام») می‌تونه دیتای یه
#  کاربرِ دیگه رو بخونه. توابعِ «admin_*» که این محدودیت رو ندارن،
#  همیشه پایین‌تر با چکِ دوجداره (uid == ADMIN_ID) محافظت می‌شن.
# ══════════════════════════════════════════════════
AI_FUNCTIONS = [
    {
        'name': 'get_my_schedule',
        'description': (
            'برنامه‌ی کلاسی/امتحانیِ آینده‌ی همین دانشجو رو از دیتابیسِ هامزیار می‌خونه. '
            'برای سوالاتی مثل «کی امتحان دارم؟» یا «برنامه‌ی این هفته‌ام چیه؟» استفاده کن.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'type_filter': {
                    'type': 'string',
                    'description': 'فیلترِ نوع، مثلاً "امتحان" یا "کلاس" — اگه خالی بمونه همه برمی‌گرده.',
                }
            },
        },
    },
    {
        'name': 'get_my_grades',
        'description': (
            'نمراتِ ثبت‌شده‌ی همین دانشجو رو از دیتابیسِ هامزیار می‌خونه. '
            'برای سوالاتی مثل «نمره‌ی آخرین کوییزم چند شد؟» استفاده کن.'
        ),
        'parameters': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'get_my_subscription_status',
        'description': 'وضعیتِ اشتراکِ همین دانشجو (فعال/منقضی، چند روز مونده) رو می‌خونه.',
        'parameters': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'get_my_tickets',
        'description': 'تیکت‌های پشتیبانیِ خودِ همین دانشجو (وضعیت، موضوع) رو می‌خونه.',
        'parameters': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'get_my_profile_summary',
        'description': 'اطلاعاتِ ثبت‌نامِ خودِ همین دانشجو (گروه، ورودی، وضعیتِ تایید) رو می‌خونه.',
        'parameters': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'remember_about_me',
        'description': (
            'وقتی کاربر یه چیزِ ماندگار و مهم درباره‌ی خودش می‌گه (مثلاً درسی که '
            'داره می‌خونه، یه ترجیحِ ثابت مثلِ «جواب‌ها رو کوتاه بگو»، یا یه علاقه‌ی '
            'مشخص) که توی سوالاتِ بعدی هم به‌کارِت میاد، این تابع رو صدا بزن تا یادت '
            'بمونه. برای اطلاعاتِ موقت/بی‌اهمیتِ همون یه سوال استفاده نکن.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {'fact': {'type': 'string', 'description': 'خودِ نکته، خیلی کوتاه و مشخص'}},
            'required': ['fact'],
        },
    },
]

# ══════════════════════════════════════════════════
#  ⚠️ قابلیتِ جدید: ابزارهای «فقط ادمین ارشد» — دسترسیِ خوندنیِ گسترده
#  به دیتای ربات (کاربران، تیکت‌ها، آمار، بانکِ سوال). این‌ها هیچ‌وقت
#  به دانشجوها اضافه نمی‌شن (چک هم توی ساختِ لیستِ ابزارها و هم داخلِ
#  خودِ اجرا انجام می‌شه — دفاعِ دوجداره). فقط خوندن — هیچ‌کدوم چیزی رو
#  توی دیتابیس تغییر نمی‌دن.
# ══════════════════════════════════════════════════
ADMIN_AI_FUNCTIONS = [
    {
        'name': 'admin_search_user',
        'description': (
            'فقط برای ادمین ارشد: یک کاربرِ خاص رو با آیدیِ عددی، یوزرنیم یا اسم پیدا '
            'می‌کنه و پروفایل/وضعیتش (گروه، ورودی، تاییدشده یا نه، آخرین فعالیت) رو برمی‌گردونه.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {'query': {'type': 'string', 'description': 'آیدیِ عددی، یوزرنیم یا اسمِ کاربر'}},
            'required': ['query'],
        },
    },
    {
        'name': 'admin_get_bot_stats',
        'description': 'فقط برای ادمین ارشد: آمارِ کلیِ ربات (تعدادِ کاربران، فعالیتِ روزانه/هفتگی، تیکت‌های باز/بسته) رو می‌ده.',
        'parameters': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'admin_list_tickets',
        'description': 'فقط برای ادمین ارشد: لیستِ تیکت‌های پشتیبانی رو می‌ده (پیش‌فرض: فقط بازها).',
        'parameters': {
            'type': 'object',
            'properties': {
                'status_filter': {'type': 'string', 'description': '"open" یا "closed"؛ اگه خالی بمونه هر دو.'},
            },
        },
    },
    {
        'name': 'admin_search_questions',
        'description': 'فقط برای ادمین ارشد: جستجوی متنیِ آزاد توی بانکِ سوال (روی متنِ سوال/توضیح).',
        'parameters': {
            'type': 'object',
            'properties': {'query': {'type': 'string', 'description': 'عبارتِ جستجو'}},
            'required': ['query'],
        },
    },
    {
        'name': 'admin_get_user_full_profile',
        'description': (
            'فقط برای ادمین ارشد: یه دیدِ کاملِ ۳۶۰درجه از یک کاربرِ خاص می‌ده — پروفایل + '
            'وضعیتِ اشتراک + تعدادِ نمرات ثبت‌شده + تعدادِ تیکت‌های باز. برای سوالاتی مثلِ '
            '«وضعیتِ کاملِ فلان کاربر چیه؟» استفاده کن.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {'query': {'type': 'string', 'description': 'آیدیِ عددی، یوزرنیم یا اسمِ کاربر'}},
            'required': ['query'],
        },
    },
    {
        'name': 'admin_get_subscription_stats',
        'description': 'فقط برای ادمین ارشد: تعدادِ کاربرانِ فعال/منقضی/در انتظارِ پرداختِ اشتراک رو می‌ده.',
        'parameters': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'admin_search_faq',
        'description': 'فقط برای ادمین ارشد: جستجوی متنی توی سوالاتِ متداول (FAQ) ربات.',
        'parameters': {
            'type': 'object',
            'properties': {'query': {'type': 'string', 'description': 'عبارتِ جستجو'}},
            'required': ['query'],
        },
    },
    {
        'name': 'admin_list_content_admins',
        'description': 'فقط برای ادمین ارشد: لیستِ ادمین‌های محتوایِ فعلیِ ربات رو می‌ده.',
        'parameters': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'admin_list_pending_approvals',
        'description': (
            'فقط برای ادمین ارشد: خلاصه‌ی همه‌ی چیزهایی که منتظرِ تاییدِ ادمین هستن — '
            'کاربرانِ در انتظارِ تایید، سوالاتِ در انتظارِ تایید، پرداخت‌های در انتظارِ بررسی.'
        ),
        'parameters': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'admin_get_interaction_insights',
        'description': (
            'فقط برای ادمین ارشد: بر اساسِ گزارش‌های اخیرِ «پاسخِ نامناسب» که دانشجوها ثبت '
            'کردن، یه خلاصه‌ی تحلیلی از الگوهای مشکل‌ساز می‌ده — برای اینکه ادمین بتونه دستی '
            'تصمیم بگیره پرامپت/شخصیتِ هوشیار رو تغییر بده یا نه. (این تحلیل صرفاً پیشنهادیه، '
            'خودکار چیزی رو تغییر نمی‌ده.)'
        ),
        'parameters': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'admin_get_ticket_detail',
        'description': 'فقط برای ادمین ارشد: جزئیاتِ کاملِ یک تیکتِ خاص (متنِ اصلی + همه‌ی پاسخ‌ها) رو با شماره‌ی تیکت می‌ده.',
        'parameters': {
            'type': 'object',
            'properties': {'ticket_id': {'type': 'integer', 'description': 'شماره‌ی تیکت'}},
            'required': ['ticket_id'],
        },
    },
    {
        'name': 'admin_get_schedule_overview',
        'description': 'فقط برای ادمین ارشد: خلاصه‌ی برنامه‌ی کلاسی/امتحانیِ آینده‌ی همه‌ی گروه‌ها (نه فقط یک دانشجوی خاص) رو می‌ده.',
        'parameters': {'type': 'object', 'properties': {}},
    },
]


async def _execute_ai_function(name: str, args: dict, uid: int) -> str:
    args = args or {}
    try:
        if name == 'get_my_schedule':
            user = await db.get_user(uid) or {}
            rows = await db.get_schedules(group=user.get('group'))
            type_filter = (args.get('type_filter') or '').strip()
            if type_filter:
                rows = [r for r in rows if type_filter in (r.get('type') or '')]
            if not rows:
                return 'هیچ برنامه‌ی آینده‌ای برای این دانشجو ثبت نشده.'
            lines = [
                f"- {r.get('type','')}: {r.get('lesson','')} | استاد: {r.get('teacher','')} | "
                f"{format_date_fa(r.get('date'), long=True, date_only=True)} ساعت {format_time_fa(r.get('time'))}"
                for r in rows[:15]
            ]
            return "\n".join(lines)

        if name == 'get_my_grades':
            rows = await db.grade_list_for_student(uid)
            if not rows:
                return 'هنوز نمره‌ای برای این دانشجو ثبت نشده.'
            lines = [
                f"- {r.get('lesson','')} ({r.get('exam_title','')}): {r.get('score','')} "
                f"| تاریخ: {r.get('exam_date','')}"
                for r in rows[:20]
            ]
            return "\n".join(lines)

        if name == 'get_my_subscription_status':
            sub = await db.sub_get(uid)
            if not sub:
                return 'این کاربر هیچ اشتراکی ثبت نکرده.'
            active = await db.sub_is_active(uid)
            days   = await db.sub_days_left(uid)
            return (
                f"وضعیت: {'فعال ✅' if active else 'غیرفعال/منقضی ⌛'}\n"
                f"پلن: {sub.get('plan_name','—')}\n"
                f"روزهای باقی‌مانده: {days if active else 0}\n"
                f"تاریخِ پایان: {format_datetime_fa(sub.get('end_date'))}"
            )

        if name == 'get_my_tickets':
            rows = await db.ticket_list_for_user(uid)
            if not rows:
                return 'این کاربر هیچ تیکتی ثبت نکرده.'
            lines = [
                f"- #{t.get('ticket_id')} | موضوع: {t.get('subject','—')} | وضعیت: {t.get('status','—')} | {format_datetime_fa(t.get('created_at'))}"
                for t in rows
            ]
            return "\n".join(lines)

        if name == 'get_my_profile_summary':
            user = await db.get_user(uid) or {}
            return (
                f"نام: {user.get('name','—')}\n"
                f"گروه: {user.get('group','—')} | ورودی: {user.get('intake','—')}\n"
                f"وضعیتِ تایید: {'تاییدشده ✅' if user.get('approved') else 'در انتظارِ تایید ⏳'}\n"
                f"تاریخِ عضویت: {format_datetime_fa(user.get('registered_at',''), fallback='—')}"
            )

        if name == 'remember_about_me':
            fact = (args.get('fact') or '').strip()
            if not fact:
                return 'چیزی برای به‌خاطرسپردن نبود.'
            await db.ai_remember_fact(uid, fact)
            return 'یادم موند.'

        # ⚠️ همه‌ی توابعِ زیر «فقط ادمین ارشد» هستن — حتی اگه به هر دلیلی
        # (باگ/تغییرِ آینده) این تابع‌ها برای یه کاربرِ دیگه هم صدا زده
        # بشن، اینجا دوباره چک می‌شه و اجرا نمی‌شن.
        if name in (
            'admin_search_user', 'admin_get_bot_stats', 'admin_list_tickets', 'admin_search_questions',
            'admin_get_user_full_profile', 'admin_get_subscription_stats', 'admin_search_faq',
            'admin_list_content_admins', 'admin_list_pending_approvals', 'admin_get_interaction_insights',
            'admin_get_ticket_detail', 'admin_get_schedule_overview',
        ):
            if uid != ADMIN_ID:
                return 'این تابع فقط برای ادمین ارشد در دسترسه.'

            if name == 'admin_search_user':
                results = await db.search_users(args.get('query', ''))
                if not results:
                    return 'کاربری با این مشخصات پیدا نشد.'
                lines = []
                for u in results[:5]:
                    lines.append(
                        f"- {u.get('name','—')} (آیدی: {u.get('user_id')}) | "
                        f"یوزرنیم: @{u.get('username') or '—'} | گروه: {u.get('group','—')} | "
                        f"ورودی: {u.get('intake','—')} | تایید‌شده: {'بله' if u.get('approved') else 'خیر'} | "
                        f"ثبت‌نام: {format_datetime_fa(u.get('registered_at',''), fallback='—')} | آخرین فعالیت: {format_datetime_fa(u.get('last_active',''), fallback='—')} | "
                        f"مسدودِ هوشیار: {'بله' if u.get('ai_banned') else 'خیر'}"
                    )
                return "\n".join(lines)

            if name == 'admin_get_bot_stats':
                u_stats = await db.stats_dashboard_users()
                t_stats = await db.stats_dashboard_tickets()
                return (
                    f"👥 کاربرانِ تاییدشده: {u_stats['total_approved']} | در انتظارِ تایید: {u_stats['total_pending']}\n"
                    f"🆕 ثبت‌نامِ امروز: {u_stats['new_today']} | این هفته: {u_stats['new_week']}\n"
                    f"🟢 فعالِ امروز: {u_stats['active_today']} | فعالِ این هفته: {u_stats['active_week']}\n"
                    f"😴 غیرفعالِ بیش از ۱۴ روز: {u_stats['inactive_14d']}\n"
                    f"🚫 بلاک‌کننده‌ی ربات: {u_stats['blocked_bot']}\n"
                    f"🎫 تیکتِ باز: {t_stats['open']} | بسته: {t_stats['closed']}\n"
                    f"⏱ میانگینِ زمانِ رسیدگی به تیکت: "
                    f"{t_stats['avg_resolution_h'] if t_stats['avg_resolution_h'] is not None else '—'} ساعت"
                )

            if name == 'admin_list_tickets':
                status = (args.get('status_filter') or '').strip().lower() or None
                if status not in ('open', 'closed'):
                    status = None
                rows = await db.ticket_get_all(status)
                if not rows:
                    return 'تیکتی پیدا نشد.'
                lines = [
                    f"- #{t.get('ticket_id')} | {t.get('user_name','—')} | موضوع: {t.get('subject','—')} | "
                    f"وضعیت: {t.get('status','—')} | {format_datetime_fa(t.get('created_at'))}"
                    for t in rows[:15]
                ]
                return "\n".join(lines)

            if name == 'admin_search_questions':
                rows = await db.search_questions_text(args.get('query', ''))
                if not rows:
                    return 'سوالی با این عبارت پیدا نشد.'
                lines = [
                    f"- [{r.get('lesson','—')} / {r.get('topic','—')}] {(r.get('question') or '')[:120]}"
                    for r in rows
                ]
                return "\n".join(lines)

            if name == 'admin_get_user_full_profile':
                results = await db.search_users(args.get('query', ''))
                if not results:
                    return 'کاربری با این مشخصات پیدا نشد.'
                u = results[0]
                target_uid = u.get('user_id')
                grades  = await db.grade_list_for_student(target_uid)
                tickets = await db.ticket_get_all(None)
                open_tickets = [t for t in tickets if t.get('user_id') == target_uid and t.get('status') == 'open']
                sub_active = await db.sub_count_by_status('active')  # فقط برای رفرنس کلی
                return (
                    f"👤 {u.get('name','—')} (آیدی: {u.get('user_id')})\n"
                    f"یوزرنیم: @{u.get('username') or '—'} | گروه: {u.get('group','—')} | ورودی: {u.get('intake','—')}\n"
                    f"تایید‌شده: {'بله' if u.get('approved') else 'خیر'} | مسدودِ هوشیار: {'بله' if u.get('ai_banned') else 'خیر'}\n"
                    f"ثبت‌نام: {format_datetime_fa(u.get('registered_at',''), fallback='—')} | آخرین فعالیت: {format_datetime_fa(u.get('last_active',''), fallback='—')}\n"
                    f"📊 تعدادِ نمراتِ ثبت‌شده: {len(grades)}\n"
                    f"🎫 تیکتِ بازِ این کاربر: {len(open_tickets)}"
                )

            if name == 'admin_get_subscription_stats':
                active  = await db.sub_count_by_status('active')
                expired = await db.sub_count_by_status('expired')
                pending = await db.sub_payment_list_pending()
                return (
                    f"💳 اشتراکِ فعال: {active}\n"
                    f"⌛ اشتراکِ منقضی‌شده: {expired}\n"
                    f"⏳ پرداختِ در انتظارِ بررسی: {len(pending)}"
                )

            if name == 'admin_search_faq':
                rows = await db.faq_search_text(args.get('query', ''))
                if not rows:
                    return 'سوالِ متداولی با این عبارت پیدا نشد.'
                lines = [f"- {r.get('question','')} → {(r.get('answer') or '')[:150]}" for r in rows]
                return "\n".join(lines)

            if name == 'admin_list_content_admins':
                rows = await db.get_content_admins()
                if not rows:
                    return 'هیچ ادمینِ محتوایی ثبت نشده.'
                lines = [f"- {u.get('name','—')} (آیدی: {u.get('user_id')})" for u in rows]
                return "\n".join(lines)

            if name == 'admin_list_pending_approvals':
                from question_bank.contracts import status_query
                pending_u = await db.pending_users()
                pending_q_count = await db.questions.count_documents(status_query('pending'))
                pending_p = await db.sub_payment_list_pending()
                return (
                    f"👥 کاربرِ در انتظارِ تایید: {len(pending_u)}\n"
                    f"❓ سوالِ در انتظارِ تایید: {pending_q_count}\n"
                    f"💳 پرداختِ در انتظارِ بررسی: {len(pending_p)}"
                )

            if name == 'admin_get_interaction_insights':
                # ⚠️ نسخه‌ی امنِ «یادگیریِ خودکار»: به‌جای اینکه ربات
                # خودش شخصیتشو تغییر بده، فقط یه خلاصه‌ی تحلیلی از
                # گزارش‌های دانشجوها می‌ده — تصمیمِ نهایی همیشه با ادمینه.
                reports = await db.ai_recent_reports(limit=30)
                if not reports:
                    return 'هنوز گزارشی از دانشجوها ثبت نشده — چیزِ خاصی برای تحلیل نیست.'
                sample = "\n---\n".join(
                    f"سوال: {r.get('question','')[:150]}\nپاسخ: {r.get('answer','')[:200]}"
                    for r in reports[:15]
                )
                return (
                    f"📋 {len(reports)} گزارشِ اخیر پیدا شد. خلاصه‌ی نمونه‌ای ازشون:\n\n{sample}\n\n"
                    "(بر اساسِ این‌ها، اگه الگویی می‌بینی — مثلاً یه نوع سوال که مدام اشتباه جواب داده "
                    "می‌شه — می‌تونی از پنلِ هوشیار دستورِ سیستمی رو دستی اصلاح کنی.)"
                )

            if name == 'admin_get_ticket_detail':
                try:
                    tid = int(args.get('ticket_id'))
                except (TypeError, ValueError):
                    return 'شماره‌ی تیکت نامعتبره.'
                t = await db.ticket_get(tid)
                if not t:
                    return f'تیکت #{tid} پیدا نشد.'
                replies = t.get('replies', [])
                replies_txt = "\n".join(f"  - {r}" for r in replies) if replies else "  (بدون پاسخ)"
                return (
                    f"🎫 تیکت #{tid} | {t.get('user_name','—')} (آیدی: {t.get('user_id')})\n"
                    f"موضوع: {t.get('subject','—')} | وضعیت: {t.get('status','—')} | {format_datetime_fa(t.get('created_at'))}\n"
                    f"متن: {t.get('message','—')}\n"
                    f"پاسخ‌ها:\n{replies_txt}"
                )

            if name == 'admin_get_schedule_overview':
                rows = await db.get_schedules()  # بدونِ group یعنی همه‌ی گروه‌ها
                if not rows:
                    return 'هیچ برنامه‌ی آینده‌ای برای هیچ گروهی ثبت نشده.'
                lines = [
                    f"- [{r.get('group','—')}] {r.get('type','')}: {r.get('lesson','')} | "
                    f"{format_date_fa(r.get('date'), long=True, date_only=True)} ساعت {format_time_fa(r.get('time'))}"
                    for r in rows[:20]
                ]
                return "\n".join(lines)

        return 'تابعِ ناشناخته.'
    except Exception:
        logger.exception("اجرای تابعِ هوشیار (%s) ناموفق بود", name)
        return 'خطا در خواندنِ اطلاعات از دیتابیس.'


# ══════════════════════════════════════════════════
#  ⚠️ قابلیتِ جدید: آپلودِ فایل به Gemini Files API — برای «سندِ مرجعِ
#  فعال» (RAG سبک). خودِ فایل روی سرورهای گوگل ذخیره می‌شه (رایگان،
#  ۴۸ ساعت)، فقط یه URI کوچیک برمی‌گردونیم که بعداً توی سوالاتِ بعدی
#  ارجاع بدیم — بدون اینکه هر بار کاربر دوباره فایل رو بفرسته.
# ══════════════════════════════════════════════════

async def _gemini_upload_file(api_key: str, file_bytes: bytes, mime_type: str, display_name: str) -> dict:
    base = "https://generativelanguage.googleapis.com/upload/v1beta/files"
    start_headers = {
        'x-goog-api-key':                    api_key,
        'X-Goog-Upload-Protocol':            'resumable',
        'X-Goog-Upload-Command':             'start',
        'X-Goog-Upload-Header-Content-Length': str(len(file_bytes)),
        'X-Goog-Upload-Header-Content-Type': mime_type,
        'Content-Type':                      'application/json',
    }
    async with httpx.AsyncClient(timeout=60) as client:
        start_resp = await client.post(base, headers=start_headers, json={'file': {'display_name': display_name}})
        if start_resp.status_code != 200:
            raise AIError("آپلودِ فایل روی سرویسِ هوش مصنوعی ناموفق بود.")
        upload_url = start_resp.headers.get('x-goog-upload-url')
        if not upload_url:
            raise AIError("آپلودِ فایل ناموفق بود (URL آپلود دریافت نشد).")

        upload_resp = await client.post(
            upload_url,
            headers={
                'Content-Length':          str(len(file_bytes)),
                'X-Goog-Upload-Offset':    '0',
                'X-Goog-Upload-Command':   'upload, finalize',
            },
            content=file_bytes,
        )
        if upload_resp.status_code != 200:
            raise AIError("آپلودِ فایل روی سرویسِ هوش مصنوعی ناموفق بود.")
        file_info = (upload_resp.json() or {}).get('file') or {}
        if not file_info.get('uri'):
            raise AIError("آپلودِ فایل ناموفق بود (URI دریافت نشد).")
        return file_info


def _raise_gemini_status_error(status_code: int) -> None:
    if status_code == 429:
        raise AIQuotaError("سقف رایگان API برای امروز پر شده — کمی بعد دوباره امتحان کن.")
    if status_code == 402:
        raise AIConfigError(
            "خطای ۴۰۲ (نیاز به پرداخت) از گوگل — پروژه‌ی Google Cloud این کلید "
            "نیاز به فعال‌سازی Billing داره یا در منطقه‌ی شما ردهٔ رایگان در "
            "دسترس نیست."
        )
    if status_code in (400, 401, 403, 404):
        raise AIConfigError(
            "کلید API نامعتبره، مدل اشتباهه یا دسترسی لازم رو نداره — ادمین باید از پنل "
            f"هوشیار تنظیماتش رو چک کنه. (کد خطا: {status_code})"
        )
    if status_code >= 500:
        raise AIError("سرویس هوش مصنوعی موقتاً در دسترس نیست — کمی بعد دوباره امتحان کن.")


async def _stream_gemini(api_key: str, model: str, system_prompt: str,
                          text: str = None, image_bytes: bytes = None,
                          image_mime: str = 'image/jpeg', history: list = None,
                          thinking: str = 'auto', uid: int = None, doc: dict = None, **_):
    """
    ⚠️ موتورِ جدید — سه قابلیت رو یکجا پیاده می‌کنه:
      ۱) پاسخِ استریمینگ (کلمه‌به‌کلمه) به‌جای یک‌جا برگشتنِ کل جواب
      ۲) Function Calling (خوندنِ برنامه/نمره از دیتابیسِ خودِ هامزیار)
      ۳) ابزارِ url_context (خوندنِ لینک‌هایی که کاربر می‌فرسته)
    این یک async generator است که رویدادهای {'type': 'delta'/'done'}
    yield می‌کند. حلقه‌ی function-calling کاملاً داخلی و نامرئی برای
    فراخوان است — فقط دلتاهای متنِ جوابِ نهایی به بیرون می‌رسه.
    """
    # FIX: از اواسط ۲۰۲۶ گوگل کلیدهای جدید با پیشوند «AQ.» صادر می‌کند که
    # با روش قدیمیِ فرستادن کلید در URL (?key=...) کار نمی‌کنند و ۴۰۴/۴۰۳
    # برمی‌گردانند. روش رسمی و سازگار با هر دو فرمت فرستادن کلید در هدر
    # x-goog-api-key است.
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse"
    headers = {'Content-Type': 'application/json', 'x-goog-api-key': api_key}

    contents = []
    for item in (history or []):
        role = 'model' if item.get('role') == 'assistant' else 'user'
        contents.append({'role': role, 'parts': [{'text': item.get('text', '')}]})

    parts = []
    if image_bytes:
        parts.append({'inline_data': {'mime_type': image_mime, 'data': base64.b64encode(image_bytes).decode('utf-8')}})
    if doc and doc.get('uri'):
        # ⚠️ سندِ مرجعِ فعال (RAG سبک) — اگه دانشجو قبلاً یه PDF فرستاده
        # و هنوز منقضی نشده، خودکار به همین سوال هم اضافه می‌شه.
        parts.append({'file_data': {'mime_type': doc.get('mime') or 'application/pdf', 'file_uri': doc['uri']}})
    if text:
        parts.append({'text': text})
    if not parts:
        parts.append({'text': 'کاربر متن یا فایلی ارسال نکرده.'})
    contents.append({'role': 'user', 'parts': parts})

    # ⚠️ طبق مستندات رسمیِ گوگل، برای خانواده‌ی مدل‌های Gemini 3.x توصیه
    # شده temperature از پیش‌فرض تغییر داده نشه.
    generation_config = {'maxOutputTokens': 3072}
    if not model.startswith('gemini-3'):
        generation_config['temperature'] = 0.3
    if thinking == 'high':
        if model.startswith('gemini-3'):
            generation_config['thinkingConfig'] = {'thinkingLevel': 'high'}
        else:
            generation_config['thinkingConfig'] = {'thinkingBudget': -1}

    tools = [{'code_execution': {}}, {'url_context': {}}]
    tool_config = None
    if uid is not None:
        # ⚠️ قابلیتِ جدید: ابزارهای «فقط ادمین ارشد» فقط وقتی uid دقیقاً
        # ADMIN_ID باشه اضافه می‌شن — دانشجوها هیچ‌وقت به این‌ها دسترسی
        # ندارن (چک دوباره هم داخلِ _execute_ai_function انجام می‌شه).
        function_declarations = list(AI_FUNCTIONS)
        if uid == ADMIN_ID:
            function_declarations += ADMIN_AI_FUNCTIONS
        tools.append({'function_declarations': function_declarations})
        # ⚠️ فیکسِ ارورِ ۴۰۰: وقتی function_declarations (تابع‌های سفارشیِ
        # برنامه/نمره) با ابزارهای توکارِ گوگل (code_execution/url_context)
        # با هم توی یه درخواست باشن، Gemini این فلگ رو صریحاً می‌خواد،
        # وگرنه با «Please enable tool_config.include_server_side_tool_
        # invocations…» ارور ۴۰۰ می‌ده. تستِ اتصالِ ادمین چون uid نداره
        # (پس تابعی هم اضافه نمی‌شه) هیچ‌وقت این مشکل رو نشون نمی‌داد —
        # برای همین «تست» موفق بود ولی چتِ واقعی خطا می‌داد.
        tool_config = {'function_calling_config': {'mode': 'AUTO'}, 'include_server_side_tool_invocations': True}

    total_tokens = 0
    full_answer_parts = []
    finish_reason = None

    for _round in range(4):   # سقفِ دورهای فراخوانیِ تابع — جلوگیری از حلقه‌ی بی‌نهایت
        payload = {
            'system_instruction': {'parts': [{'text': system_prompt}]},
            'contents': contents,
            'generationConfig': generation_config,
            'tools': tools,
        }
        if tool_config:
            payload['tool_config'] = tool_config

        function_call = None
        round_model_parts = []

        client = httpx.AsyncClient(timeout=90)
        try:
            for attempt in range(2):   # ⚠️ یک بار ری‌ترای خودکار روی خطای موقتِ سرور (۵xx)
                try:
                    async with client.stream('POST', url, headers=headers, json=payload) as resp:
                        if resp.status_code != 200:
                            if resp.status_code >= 500 and attempt == 0:
                                await asyncio.sleep(1.5)
                                continue
                            _raise_gemini_status_error(resp.status_code)
                        async for line in resp.aiter_lines():
                            if not line.startswith('data:'):
                                continue
                            chunk_str = line[5:].strip()
                            if not chunk_str:
                                continue
                            try:
                                chunk = json.loads(chunk_str)
                            except ValueError:
                                continue
                            usage = chunk.get('usageMetadata') or {}
                            if usage.get('totalTokenCount'):
                                total_tokens = int(usage['totalTokenCount'])
                            cands = chunk.get('candidates') or []
                            if not cands:
                                continue
                            cand = cands[0]
                            if cand.get('finishReason'):
                                finish_reason = cand['finishReason']
                            for part in (cand.get('content', {}) or {}).get('parts', []) or []:
                                if part.get('thought'):
                                    continue
                                if 'functionCall' in part:
                                    function_call = part['functionCall']
                                    round_model_parts.append(part)
                                elif part.get('text') and function_call is None:
                                    round_model_parts.append(part)
                                    full_answer_parts.append(part['text'])
                                    yield {'type': 'delta', 'text': part['text']}
                    break   # استریم با موفقیت تموم شد، از حلقه‌ی ری‌ترای خارج شو
                except httpx.TimeoutException:
                    raise AIError("سرویس هوش مصنوعی دیر جواب داد (timeout) — دوباره امتحان کن.")
                except httpx.HTTPError as e:
                    raise AIError(f"خطا در اتصال به سرویس هوش مصنوعی: {e}")
        finally:
            await client.aclose()

        if function_call:
            fn_name = function_call.get('name')
            fn_args = function_call.get('args') or {}
            result_text = await _execute_ai_function(fn_name, fn_args, uid)
            contents.append({'role': 'model', 'parts': round_model_parts})
            contents.append({'role': 'user', 'parts': [{
                'function_response': {'name': fn_name, 'response': {'result': result_text}}
            }]})
            continue   # دورِ بعدی — این‌بار با نتیجه‌ی تابع

        break   # این دور function call نداشت → جوابِ نهایی همینه

    answer = ''.join(full_answer_parts).strip()
    if not answer:
        raise AIConfigError("مدل پاسخی برنگردوند.")
    if finish_reason == 'MAX_TOKENS':
        note = "\n\n⏳ (جواب طولانی بود و همین‌جا قطع شد؛ اگه خواستی بقیه‌ش رو بگم، بنویس «ادامه بده».)"
        answer += note
        yield {'type': 'delta', 'text': note}

    yield {'type': 'done', 'answer': answer, 'tokens': total_tokens}


async def _call_openai_compat(api_key: str, model: str, system_prompt: str,
                              text: str = None, image_bytes: bytes = None,
                              image_mime: str = 'image/jpeg', history: list = None,
                              provider: str = 'openrouter', **_) -> tuple:
    """
    🌊 W9 — فراخوان عمومیِ همه‌ی providerهای سازگار با OpenAI
    (openrouter/groq/cerebras/mistral/deepseek). همه‌شان همان
    /chat/completions را با Bearer token حرف می‌زنند؛ فقط base_url فرق
    می‌کند. پیام‌های خطای خاص OpenRouter (۴۰۲) به‌صورت شرطی حفظ شده‌اند.
    """
    meta = PROVIDERS.get(provider) or {}
    base = meta.get('url') or PROVIDERS['openrouter']['url']
    url = f"{base}/chat/completions"
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type':  'application/json',
    }

    if image_bytes and not meta.get('vision'):
        raise AIConfigError(
            f"ارائه‌دهنده‌ی {meta.get('label', provider)} ورودی تصویر را "
            "پشتیبانی نمی‌کند — برای سوالِ تصویری provider را روی Gemini "
            "یا OpenRouter بگذارید.")

    content = []
    if text:
        content.append({'type': 'text', 'text': text})
    if image_bytes:
        b64 = base64.b64encode(image_bytes).decode('utf-8')
        content.append({
            'type': 'image_url',
            'image_url': {'url': f'data:{image_mime};base64,{b64}'},
        })
    if not content:
        content.append({'type': 'text', 'text': 'کاربر متن یا عکسی ارسال نکرده.'})

    messages = [{'role': 'system', 'content': system_prompt}]
    for item in (history or []):
        role = 'assistant' if item.get('role') == 'assistant' else 'user'
        messages.append({'role': role, 'content': item.get('text', '')})
    messages.append({'role': 'user', 'content': content})

    payload = {
        'model': model,
        'messages': messages,
        'temperature': 0.3,
        'max_tokens': 3072,   # ⚠️ فیکس باگِ «پیامِ نصفه» — قبلاً 1024 بود
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = None
            for attempt in range(2):   # ⚠️ یک بار ری‌ترای خودکار روی خطای موقتِ سرور (۵xx)
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code >= 500 and attempt == 0:
                    await asyncio.sleep(1.5)
                    continue
                break
    except httpx.TimeoutException:
        raise AIError("سرویس هوش مصنوعی دیر جواب داد (timeout) — دوباره امتحان کن.")
    except httpx.HTTPError as e:
        raise AIError(f"خطا در اتصال به سرویس هوش مصنوعی: {e}")

    if resp.status_code == 429:
        raise AIQuotaError("سقف رایگان API برای امروز پر شده — کمی بعد دوباره امتحان کن.")
    if resp.status_code == 402:
        if provider == 'openrouter':
            raise AIConfigError(
                "خطای ۴۰۲ (نیاز به پرداخت) از OpenRouter. معمولاً یکی از این‌هاست:\n"
                "۱) نام مدل درست/کامل نیست — باید دقیقاً مثل فهرست کاتالوگ باشه "
                "(با :free آخرش)\n"
                "۲) موجودی حساب openrouter.ai/settings/credits منفیه\n"
                "۳) توی تنظیمات اکانت OpenRouter، Provider ی که این مدل رایگان رو "
                "می‌ده Ignore/بلاک شده"
            )
        raise AIConfigError(
            "خطای ۴۰۲ (نیاز به پرداخت) — سهمیه‌ی رایگانِ این ارائه‌دهنده تمام "
            "شده یا مدل انتخابی پولی است.")
    if resp.status_code in (400, 401, 403, 404):
        raise AIConfigError(
            "کلید API نامعتبره، مدل اشتباهه یا دسترسی لازم رو نداره — ادمین باید از پنل "
            f"هوشیار تنظیماتش رو چک کنه. (کد خطا: {resp.status_code})"
        )
    if resp.status_code >= 500:
        raise AIError("سرویس هوش مصنوعی موقتاً در دسترس نیست — یه بار دیگه هم امتحان شد ولی جواب نداد؛ کمی بعد دوباره امتحان کن.")

    try:
        resp.raise_for_status()
        data = resp.json()
        choice = data['choices'][0]
        answer = choice['message']['content'].strip()
        tokens = int((data.get('usage') or {}).get('total_tokens', 0) or 0)
        if choice.get('finish_reason') == 'length':
            answer += "\n\n⏳ (جواب طولانی بود و همین‌جا قطع شد؛ اگه خواستی بقیه‌ش رو بگم، بنویس «ادامه بده».)"
        return answer, tokens
    except (KeyError, IndexError, ValueError):
        raise AIConfigError("مدل پاسخی برنگردوند — احتمالاً مدل انتخاب‌شده الان در دسترس نیست.")


STREAM_PROVIDERS = {
    'gemini': _stream_gemini,
    # نمونه برای بعداً: یک async generator با همین قرارداد رویداد بنویس
    # ({'type': 'delta', 'text': ...} / {'type': 'done', 'answer':..., 'tokens':...})
}


def _make_compat_stream(provider_name: str):
    """🌊 W9 — استریمِ همسان‌ساز برای providerهای سازگار با OpenAI.
    استریم واقعی ندارن؛ کل جواب یک‌جا به‌عنوان delta واحد + done
    برمی‌گردد — کدِ بالادستی (نمایش پیام) فرقی نمی‌کند."""
    async def _stream(**kwargs):
        answer, tokens = await _call_openai_compat(
            provider=provider_name, **kwargs)
        yield {'type': 'delta', 'text': answer}
        yield {'type': 'done', 'answer': answer, 'tokens': tokens}
    return _stream


for _p in ('openrouter', 'groq', 'cerebras', 'mistral', 'deepseek', 'nvidia', 'huggingface', 'together'):
    STREAM_PROVIDERS[_p] = _make_compat_stream(_p)


# سازگاری با نامِ قدیمی (اگر جای دیگری صدا زده می‌شد)
async def _call_openrouter(**kwargs):
    return await _call_openai_compat(provider='openrouter', **kwargs)


async def ask_ai_stream(text: str = None, image_bytes: bytes = None,
                         image_mime: str = 'image/jpeg', history: list = None,
                         uid: int = None):
    """
    رابطِ اصلیِ جدید: یک async generator که رویدادهای {'type': 'delta',
    'text': ...} (پاسخِ تدریجی) و در آخر {'type': 'done', 'answer':...,
    'tokens':...} می‌دهد. uid برای Function Calling و سندِ مرجعِ فعال
    (RAG) استفاده می‌شود.
    """
    cfg = await get_ai_config()
    if not cfg['enabled']:
        raise AIConfigError("بخش هوش مصنوعی فعلاً توسط مدیریت غیرفعال است.")
    if not cfg['api_key']:
        raise AIConfigError("هنوز کلید API توسط ادمین تنظیم نشده.")

    fn = STREAM_PROVIDERS.get(cfg['provider'])
    if not fn:
        raise AIConfigError(f"ارائه‌دهنده‌ی «{cfg['provider']}» پشتیبانی نمی‌شود.")

    doc = None
    if cfg['provider'] == 'gemini' and uid is not None:
        try:
            doc = await db.ai_get_doc(uid)
            if doc and doc.get('at') and (now_utc() - parse_machine_datetime(doc['at'])).total_seconds() > 48 * 3600:
                doc = None   # فایلِ گوگل بعد از ۴۸ ساعت خودش منقضی می‌شه
        except Exception:
            doc = None

    # ⚠️ قابلیتِ جدید: تزریقِ «پروفایلِ ماندگارِ فشرده» — نکاتی که خودِ
    # مدل قبلاً درباره‌ی همین کاربر یاد گرفته (با remember_about_me) به
    # دستورِ سیستمیِ همین درخواست اضافه می‌شه، تا بدونِ نیاز به دوباره‌
    # گفتنِ کاربر، ادامه‌ی طبیعیِ رابطه حفظ بشه.
    system_prompt = cfg['system_prompt']
    if uid is not None:
        try:
            notes = await db.ai_get_profile_notes(uid)
            if notes:
                system_prompt += (
                    "\n\n[نکاتِ ماندگاری که قبلاً درباره‌ی این کاربر یاد گرفتی — طبیعی و بدونِ اشاره‌ی مستقیم بهشون استفاده کن:]\n"
                    + "\n".join(f"- {n}" for n in notes)
                )
        except Exception:
            pass

    kwargs = dict(
        api_key=cfg['api_key'], model=cfg['model'], system_prompt=system_prompt,
        text=text, image_bytes=image_bytes, image_mime=image_mime,
        history=history or [], thinking=cfg['thinking'],
    )
    if cfg['provider'] == 'gemini':
        kwargs['uid'] = uid
        kwargs['doc'] = doc

    full_answer = None
    async for event in fn(**kwargs):
        if event['type'] == 'done':
            full_answer = event['answer']
        yield event

    if full_answer is not None:
        _guard_against_meta_leak(full_answer, cfg)


async def ask_ai(text: str = None, image_bytes: bytes = None,
                  image_mime: str = 'image/jpeg', history: list = None,
                  uid: int = None) -> tuple:
    """
    نسخه‌ی ساده (غیر-استریم) برای فراخوان‌هایی که فقط جوابِ نهایی رو
    می‌خوان (مثلاً دکمه‌ی «تست اتصال» توی پنل ادمین) — همون
    ask_ai_stream رو زیرِ پوستش صدا می‌زنه و رویدادها رو جمع می‌کنه.
    """
    answer, tokens = '', 0
    async for event in ask_ai_stream(text=text, image_bytes=image_bytes,
                                      image_mime=image_mime, history=history, uid=uid):
        if event['type'] == 'done':
            answer, tokens = event['answer'], event['tokens']
    return answer, tokens


# ══════════════════════════════════════════════════
#  ⚠️ قابلیتِ جدید: طراحیِ خودکارِ سوالِ چهارگزینه‌ای با هوش مصنوعی —
#  برای بخشِ «بانکِ سوال و طرحِ سوال». برخلافِ چتِ هوشیار، اینجا به
#  استریم/تاریخچه/تابع نیازی نیست؛ فقط یک درخواستِ ساده با خروجیِ
#  JSON تضمین‌شده (Structured Output) — قابل‌اعتمادتر از پارس‌کردنِ
#  متنِ آزاد.
# ══════════════════════════════════════════════════

# ══════════════════════════════════════════════════
#  🐛 رفعِ باگ: اطلاعیه/پاسخِ تیکت/سوال نصفه تولید می‌شد.
#
#  ریشه: مدلِ پیش‌فرض `gemini-2.5-flash` یک مدلِ «تفکری» است و توکن‌هایی
#  که صرفِ استدلالِ داخلی می‌کند از همان سهمیه‌ی maxOutputTokens کم
#  می‌شود. توابعِ کمکیِ زیر بدونِ thinkingConfig صدا زده می‌شدند، پس
#  تفکر بخشِ بزرگی از بودجه را می‌بلعید و متنِ واقعی وسطِ کار قطع
#  می‌شد — بدونِ هیچ خطایی، چون کد فقط parts[0].text را می‌خواند و
#  finishReason را نادیده می‌گرفت.
#
#  دو اصلاح:
#   ۱) thinkingBudget=0 → برای این کارهای «قالب‌محور» تفکرِ داخلی لازم
#      نیست و کلِ بودجه صرفِ خروجی می‌شود.
#   ۲) _extract_gemini_text() → اگر باز هم به سقف خورد، به‌جای برگرداندنِ
#      متنِ ناقص، خطای شفاف می‌دهد تا ادمین متنِ نصفه را همگانی نفرستد.
# ══════════════════════════════════════════════════

#  ۳) _sanitize_tg_html() → خروجیِ مدل همیشه HTMLِ معتبرِ تلگرام نیست.
#     تگِ بسته‌نشده، تگِ غیرمجاز (<div>, <p>, <br>) یا تودرتویِ نامتوازن
#     باعث BadRequest می‌شود؛ یعنی پیش‌نمایش می‌شکند و پنلِ ادمین قفل
#     می‌شود، یا بدتر، ارسالِ همگانی برای همه شکست می‌خورد. پس قبل از
#     برگرداندنِ متن، آن را پاک‌سازی می‌کنیم.

# تگ‌هایی که Bot API تلگرام در parse_mode=HTML می‌پذیرد
_TG_ALLOWED_TAGS = {
    'b', 'strong', 'i', 'em', 'u', 'ins', 's', 'strike', 'del',
    'a', 'code', 'pre', 'blockquote', 'span', 'tg-spoiler',
}
_TAG_RE = re.compile(r'<(/?)([a-zA-Z0-9-]+)([^>]*)>')


def _sanitize_tg_html(text: str) -> str:
    """HTMLِ خروجیِ مدل را به HTMLِ معتبرِ تلگرام تبدیل می‌کند.

    - تگ‌های غیرمجاز حذف می‌شوند (محتوایشان می‌ماند)؛ <br> و </p> به خطِ
      جدید تبدیل می‌شوند.
    - تگ‌های بسته‌نشده در انتها بسته می‌شوند.
    - بسته‌شدن‌های نامتوازن/اضافه دور ریخته می‌شوند.
    خودِ متن دست‌نخورده می‌ماند؛ فقط ساختارِ تگ‌ها اصلاح می‌شود.
    """
    if not text:
        return text

    out, stack, pos = [], [], 0
    for m in _TAG_RE.finditer(text):
        out.append(text[pos:m.start()])
        pos = m.end()
        closing, tag, attrs = m.group(1), m.group(2).lower(), m.group(3)

        if tag in ('br', 'p', 'div'):
            # این‌ها ساختارِ بلوکی‌اند؛ به شکستِ خط ترجمه می‌شوند
            out.append('\n' if (tag == 'br' or closing) else '')
            continue
        if tag not in _TG_ALLOWED_TAGS:
            continue                      # تگ را بینداز، متن را نگه دار
        if closing:
            if tag in stack:              # فقط اگر واقعاً باز شده بود
                while stack and stack[-1] != tag:
                    out.append(f'</{stack.pop()}>')   # تگ‌های داخلی را ببند
                stack.pop()
                out.append(f'</{tag}>')
            continue
        stack.append(tag)
        out.append(f'<{tag}{attrs}>')

    out.append(text[pos:])
    while stack:                          # هرچه باز مانده را ببند
        out.append(f'</{stack.pop()}>')
    return ''.join(out).strip()


def _no_thinking(cfg: dict) -> dict:
    """تفکرِ داخلی را خاموش می‌کند تا کلِ maxOutputTokens صرفِ متن شود.

    فقط روی مدل‌های Gemini اثر دارد؛ برای مدل‌های دیگر بی‌ضرر است چون
    کلیدِ ناشناخته در generationConfig نادیده گرفته می‌شود.
    """
    cfg = dict(cfg)
    cfg['thinkingConfig'] = {'thinkingBudget': 0}
    return cfg


def _extract_gemini_text(data: dict, what: str = "متن") -> str:
    """متنِ پاسخِ Gemini را درمی‌آورد و «ناقص بودن» را صریحاً تشخیص می‌دهد.

    برخلافِ نسخه‌ی قبلی، finishReason بررسی می‌شود: اگر مدل به سقفِ توکن
    خورده باشد، متنِ نصفه برگردانده نمی‌شود.
    """
    try:
        cand = data['candidates'][0]
    except (KeyError, IndexError, TypeError):
        raise AIConfigError("هوش مصنوعی پاسخی برنگرداند — دوباره امتحان کن.")

    reason = cand.get('finishReason')
    parts = (cand.get('content') or {}).get('parts') or []
    text = ''.join(p.get('text', '') for p in parts).strip()

    if reason == 'MAX_TOKENS':
        raise AIError(
            f"{what} طولانی‌تر از سهمیه‌ی مدل شد و ناقص ماند. "
            "دوباره بساز یا نکته‌ها را کوتاه‌تر بنویس."
        )
    if reason == 'SAFETY':
        raise AIError("مدل به‌دلیلِ فیلترِ ایمنی جواب نداد — متن را بازنویسی کن.")
    if not text:
        raise AIConfigError("هوش مصنوعی متنِ قابل‌فهمی برنگردوند — دوباره امتحان کن.")
    return text


QUESTION_SCHEMA = {
    'type': 'object',
    'properties': {
        'question':      {'type': 'string', 'description': 'متنِ کاملِ سوال'},
        'options':       {
            'type': 'array', 'items': {'type': 'string'},
            'minItems': 4, 'maxItems': 4,
            'description': 'دقیقاً ۴ گزینه',
        },
        'correct_index': {'type': 'integer', 'description': 'ایندکسِ گزینه‌ی درست، از 0 تا 3'},
        'explanation':   {'type': 'string', 'description': 'تحلیلِ کاملِ پاسخ (چرا درست/چرا بقیه غلط)'},
    },
    'required': ['question', 'options', 'correct_index', 'explanation'],
}


async def generate_question_ai(lesson: str, topic: str, difficulty: str = None,
                               note: str = None, grounding: list[str] = None) -> dict:
    """
    یک سوالِ چهارگزینه‌ی کامل (سوال/گزینه‌ها/پاسخِ درست/تحلیل) برای درس و
    مبحثِ داده‌شده می‌سازد. خروجی: {'question','options','correct_index','explanation'}.
    """
    cfg = await get_ai_config()
    if not cfg['enabled']:
        raise AIConfigError("بخش هوش مصنوعی فعلاً توسط مدیریت غیرفعال است.")
    if not cfg['api_key']:
        raise AIConfigError("هنوز کلید API توسط ادمین تنظیم نشده.")
    if cfg['provider'] != 'gemini':
        raise AIConfigError("طراحیِ سوال با AI فعلاً فقط با ارائه‌دهنده‌ی Gemini در دسترسه.")

    prompt = (
        "یک سوالِ چهارگزینه‌ای (تستی) دقیق و علمی برای دانشجویانِ پزشکی طراحی کن.\n"
        f"درس: {lesson}\nمبحث: {topic}\n"
    )
    if difficulty:
        prompt += f"سطح سختی: {difficulty}\n"
    if note:
        prompt += f"نکته‌ی خاصِ موردنظر: {note}\n"
    if grounding:
        prompt += ("\nزمینه تأییدشده سامانه؛ سؤال باید فقط با این زمینه سازگار باشد و "
                   "اگر زمینه کافی نیست، خروجی نامعتبر تولید نکن:\n" +
                   "\n".join(f"- {str(item)[:300]}" for item in grounding[:8]) + "\n")
    prompt += (
        "سوال باید بدونِ ابهام باشه و فقط یکی از ۴ گزینه دقیقاً درست باشه. "
        "توی «explanation» هم توضیح بده چرا گزینه‌ی درست، درسته و بقیه چرا غلطن."
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['model']}:generateContent"
    headers = {'Content-Type': 'application/json', 'x-goog-api-key': cfg['api_key']}
    payload = {
        'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
        'generationConfig': _no_thinking({
            'responseMimeType': 'application/json',
            'responseSchema': QUESTION_SCHEMA,
            'maxOutputTokens': 2048,
        }),
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException:
        raise AIError("سرویس هوش مصنوعی دیر جواب داد — دوباره امتحان کن.")
    except httpx.HTTPError as e:
        raise AIError(f"خطا در اتصال به سرویس هوش مصنوعی: {e}")

    if resp.status_code != 200:
        _raise_gemini_status_error(resp.status_code)

    try:
        data = resp.json()
        raw_text = _extract_gemini_text(data, "سوال")
        parsed = json.loads(raw_text)
        options = parsed.get('options') or []
        if len(options) != 4 or not parsed.get('question') or 'correct_index' not in parsed:
            raise ValueError('ساختارِ ناقص')
        correct_index = int(parsed['correct_index'])
        if not (0 <= correct_index <= 3):
            raise ValueError('correct_index خارج از محدوده')
        return {
            'question':      str(parsed['question']).strip(),
            'options':       [str(o).strip() for o in options],
            'correct_index': correct_index,
            'explanation':   str(parsed.get('explanation') or '').strip(),
            'model':         cfg['model'],
        }
    except (KeyError, IndexError, ValueError, TypeError, json.JSONDecodeError):
        raise AIConfigError("هوش مصنوعی خروجیِ قابل‌فهمی برنگردوند — دوباره امتحان کن.")


# ══════════════════════════════════════════════════
#  ⚠️ قابلیتِ جدید: دستیارِ نوشتنِ اطلاعیه + پیش‌نویسِ پاسخِ تیکت.
#
#  نکته‌ی طراحیِ مهم: این دو تابع کاملاً «کمکی» هستن، نه بخشی از مسیرِ
#  اصلیِ ربات. هر خطایی (سهمیه تموم شده، کلید غلط، سرویس قطع، هر چیزِ
#  دیگه) به‌شکلِ AIError بالا می‌ره و فراخوان (admin.py/ticket.py) باید
#  همیشه یه راهِ برگشتِ ساده به مسیرِ دستیِ همیشگی داشته باشه — یعنی
#  اگه هوش مصنوعی کار نکرد، نوشتنِ اطلاعیه یا پاسخِ تیکت دقیقاً مثلِ
#  قبل (بدونِ AI) کار می‌کنه.
# ══════════════════════════════════════════════════

BROADCAST_STYLE_INSTRUCTION = """تو دستیارِ نوشتنِ اطلاعیه‌های رسمیِ ربات «هامزیار» هستی — یک ربات آموزشی دانشگاهی برای دانشجویان دانشگاه علوم پزشکی هرمزگان.

از این قوانین دقیقاً و بدون استثنا پیروی کن:

هویت و لحن: لحن باید حسِ یک سامانه‌ی رسمیِ دانشگاهیِ مدرن رو منتقل کنه؛ حرفه‌ای، تمیز، قابل‌اعتماد و پریمیوم.

سبک نگارش: رسمی اما صمیمی، کوتاه و مفید، بدون زیاده‌گویی، بدون متن‌های شعاری، خوانا و مرتب، مناسبِ پیامِ همگانیِ تلگرام. هر پاراگراف حداکثر ۲ تا ۳ خط.

قالب: همیشه خروجی رو با HTML تلگرام بنویس. فقط از تگ‌های <b>، <a> و <code> استفاده کن — هیچ تگ HTML دیگری مجاز نیست. <code> فقط برای دستورها مثل /start. هیچ‌وقت از Markdown یا ** استفاده نکن.

ساختارِ ثابت (دقیقاً به همین شکل):
📣 <b>عنوان اطلاعیه</b>
━━━━━━━━━━━━━━━━
🎓 <b>دانشجویان گرامی،</b>
متن اطلاعیه...
📌 نکته مهم (در صورت نیاز)
💙 <b>از همراهی و اعتماد شما سپاسگزاریم.</b>
✨ <b>تیم اطلاع‌رسانی هامزیار</b>

ایموجی‌های مجاز برای استفاده در متن (بسته به موضوع): 📣 اطلاعیه، 🎓 دانشجویان، 📌 نکته مهم، ⚠️ هشدار، 🔔 خبر، 📚 منابع، 🧪 بانک سوالات، ✏️ طراحی سوال، 🤖 هوشیار، 📝 فرم، 🗳️ انتخابات، 🔗 لینک، 📱 اپلیکیشن، 💳 اشتراک، ⚙️ بروزرسانی، 🚀 قابلیت جدید، 💙 تشکر، ✨ امضا. از ایموجیِ اضافی/خارج از این لیست استفاده نکن.

بولد: همیشه موارد مهم (ساعت، تاریخ، لینک، نام درس، نام قابلیت، نام بخش، اسمِ سامانه، اطلاعیه‌ی مهم، تغییرات، قیمت، مدتِ اشتراک) رو Bold کن.

لینک: اگه لینکی بود، دقیقاً به این شکل بنویس: <a href="URL">متن نمایشی</a>

امضا: بسته به موضوع یکی از این سه رو انتخاب کن: «✨ <b>تیم اطلاع‌رسانی هامزیار</b>» یا «✨ <b>تیم توسعه هامزیار</b>» یا «✨ <b>مدیریت هامزیار</b>».

لحن بر اساسِ موضوع: اگه موضوع قابلیتِ جدید/بروزرسانی/نسخه‌ی جدید/هوش‌مصنوعی/اشتراک/بانکِ سوالات بود، لحن هیجان‌انگیز اما حرفه‌ای باشه. اگه موضوع امتحانات/اطلاعیه‌ی دانشگاه/نمرات/قوانین/انتخابات/اخبارِ رسمی بود، لحن کاملاً رسمی باشه.

اطلاعیه‌های «رونمایی»: اگه موضوع رونماییِ یک بخشِ بزرگ یا بروزرسانیِ اساسی بود (نه یک تغییرِ جزئی)، این ساختار رو به کار ببر تا حسِ یک پروژه‌ی بلندمدت منتقل بشه، نه یک قابلیتِ کوچک:
• عنوان با حسِ رونمایی و ایموجی 🚀
• یک پاراگراف درباره‌ی مسیرِ ساخت (ماه‌ها طراحی و توسعه)
• بلافاصله بعدش یک جمله‌ی هدف‌گذارانه با 🎯 که نشون بده هدف ساختِ یک «اکوسیستمِ آموزشیِ کامل» بوده، نه صرفاً یک ربات
• فهرستِ تیتروارِ امکانات، هر خط یک ایموجیِ مرتبط از لیستِ مجاز
• یک جمله‌ی «و این تازه آغازِ راهه...» درباره‌ی آینده
• راهنمای دسترسی به‌صورتِ گام‌به‌گام (اگه لازم بود از <code> برای دستور استفاده کن)
• تشکر از کاربران و امضا
در این حالت فهرستِ امکانات می‌تونه بلندتر از حدِ معمول باشه و محدودیتِ «۲ تا ۳ خط در هر پاراگراف» فقط به پاراگراف‌های توضیحی مربوطه، نه به فهرست.

خروجی: فقط متنِ نهاییِ HTML رو تولید کن — هیچ توضیحِ اضافه، هیچ مقدمه یا موخره‌ای نده."""


async def generate_broadcast_ai(notes: str) -> str:
    """از روی چند نکته/بولت‌پوینتی که ادمین می‌ده، متنِ کاملِ اطلاعیه رو طبقِ استانداردِ هامزیار می‌سازه."""
    cfg = await get_ai_config()
    if not cfg['enabled']:
        raise AIConfigError("بخش هوش مصنوعی فعلاً توسط مدیریت غیرفعال است.")
    if not cfg['api_key']:
        raise AIConfigError("هنوز کلید API توسط ادمین تنظیم نشده.")
    if cfg['provider'] != 'gemini':
        raise AIConfigError("این قابلیت فعلاً فقط با ارائه‌دهنده‌ی Gemini در دسترسه.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['model']}:generateContent"
    headers = {'Content-Type': 'application/json', 'x-goog-api-key': cfg['api_key']}
    payload = {
        'system_instruction': {'parts': [{'text': BROADCAST_STYLE_INSTRUCTION}]},
        'contents': [{'role': 'user', 'parts': [{'text': f"این نکته‌ها رو به یه اطلاعیه تبدیل کن:\n\n{notes}"}]}],
        'generationConfig': _no_thinking({'maxOutputTokens': 2048}),
    }
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException:
        raise AIError("سرویس هوش مصنوعی دیر جواب داد — دوباره امتحان کن.")
    except httpx.HTTPError as e:
        raise AIError(f"خطا در اتصال به سرویس هوش مصنوعی: {e}")

    if resp.status_code != 200:
        _raise_gemini_status_error(resp.status_code)

    return _sanitize_tg_html(_extract_gemini_text(resp.json(), "اطلاعیه"))


TICKET_REPLY_INSTRUCTION = """تو داری به ادمینِ پشتیبانیِ ربات «هامزیار» (ربات آموزشیِ دانشگاه علوم پزشکی هرمزگان) کمک می‌کنی تا به تیکتِ یک دانشجو جواب بده.

یه پیش‌نویسِ پاسخِ کوتاه، محترمانه، دوستانه و کاربردی بنویس — انگار خودِ پشتیبانیِ هامزیار داره جواب می‌ده، نه یه ربات. مستقیم برو سراغِ راه‌حل یا جوابِ سوال، بدون مقدمه‌چینیِ اضافه. اگه اطلاعاتِ کافی برای حلِ قطعیِ مشکل نیست، ازش بخواه جزئیاتِ بیشتر بده.
فقط از تگِ <b> برای تاکید استفاده کن (اگه لازم بود)، بدونِ Markdown. خروجی فقط خودِ متنِ پاسخه، بدون توضیحِ اضافه."""


async def generate_ticket_reply_ai(subject: str, ticket_text: str, previous_replies: list = None) -> str:
    """یک پیش‌نویسِ پاسخ برای تیکتِ پشتیبانی می‌سازد — ادمین می‌تونه مستقیم بفرستدش یا ویرایش کنه."""
    cfg = await get_ai_config()
    if not cfg['enabled']:
        raise AIConfigError("بخش هوش مصنوعی فعلاً توسط مدیریت غیرفعال است.")
    if not cfg['api_key']:
        raise AIConfigError("هنوز کلید API توسط ادمین تنظیم نشده.")
    if cfg['provider'] != 'gemini':
        raise AIConfigError("این قابلیت فعلاً فقط با ارائه‌دهنده‌ی Gemini در دسترسه.")

    convo = f"موضوعِ تیکت: {subject}\n\nمتنِ تیکت:\n{ticket_text}\n"
    if previous_replies:
        convo += "\nپاسخ‌های قبلی:\n" + "\n".join(f"- {r}" for r in previous_replies[-5:])

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['model']}:generateContent"
    headers = {'Content-Type': 'application/json', 'x-goog-api-key': cfg['api_key']}
    payload = {
        'system_instruction': {'parts': [{'text': TICKET_REPLY_INSTRUCTION}]},
        'contents': [{'role': 'user', 'parts': [{'text': convo}]}],
        'generationConfig': _no_thinking({'maxOutputTokens': 1024}),
    }
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException:
        raise AIError("سرویس هوش مصنوعی دیر جواب داد — دوباره امتحان کن.")
    except httpx.HTTPError as e:
        raise AIError(f"خطا در اتصال به سرویس هوش مصنوعی: {e}")

    if resp.status_code != 200:
        _raise_gemini_status_error(resp.status_code)

    return _sanitize_tg_html(_extract_gemini_text(resp.json(), "پاسخِ تیکت"))


# نشانه‌های شناخته‌شده‌ی «نشتِ فراداده»: بعضی مدل‌های رایگان (مخصوصاً وقتی
# با روتر خودکارِ «openrouter/free» یک مدل نامناسب/کلاسیفایر انتخاب می‌شود)
# به‌جای پاسخِ واقعی، برچسب‌های داخلیِ ارزیابیِ ایمنی را برمی‌گردانند، مثل:
#   "User Safety: safe / Response Safety: unsafe / Safety Categories: ..."
# این خروجی برای دانشجو کاملاً بی‌معنی و گمراه‌کننده است، پس به‌جای نمایش
# مستقیم آن، خطای شفاف نشان می‌دهیم تا ادمین مدل را عوض کند.
_META_LEAK_MARKERS = (
    'user safety', 'response safety', 'safety categories',
    'safety category', 'content policy violation', 'moderation result',
)


def _guard_against_meta_leak(answer: str, cfg: dict) -> None:
    lowered = (answer or '').lower()
    if any(marker in lowered for marker in _META_LEAK_MARKERS):
        hint = (
            "اگه از OpenRouter استفاده می‌کنی و مدلت روی «انتخاب خودکار» "
            "(openrouter/free) تنظیمه، از پنل ادمین یه مدل مشخص مثل "
            "google/gemma-4-31b-it:free رو انتخاب کن."
            if cfg.get('provider') == 'openrouter' else
            "مدل انتخابی خروجی نامناسب برگردوند؛ از پنل ادمین مدل رو عوض کن."
        )
        raise AIConfigError(
            f"مدل به‌جای پاسخِ درسی، یک خروجیِ فنیِ نامرتبط برگردوند. {hint}"
        )


# ══════════════════════════════════════════════════
#  محدودیت روزانه‌ی هر کاربر
# ══════════════════════════════════════════════════

async def check_and_consume_quota(uid: int) -> tuple:
    """
    برمی‌گرداند (allowed, used_after, limit).
    ادمین ارشد همیشه نامحدود است؛ daily_limit=0 یعنی نامحدود برای همه.
    در هر دو حالت، ai_total_usage (مصرف کل، برای آمار پنل ادمین) هم
    یک واحد بالا می‌رود. اگه روز عوض شده باشه، ai_tokens_today هم صفر
    می‌شه (خودِ record_token_usage بعد از جواب گرفتن رویش $inc می‌زند).
    """
    cfg = await get_ai_config()
    # 🌊 W6/MISS-04 — سقف پلنی (پیش‌فرض: سراسری)؛ همه‌ی صداکننده‌ها خودکار پلنی شدند
    limit = await db.ai_limit_for_user(uid, cfg['daily_limit'])
    today = today_tehran().isoformat()
    # The DB conditional update is the source of truth; this remains correct
    # when Bot and Mini App requests land on different processes.
    return await db.ai_consume_quota(uid, limit, today)


async def record_token_usage(uid: int, tokens: int) -> None:
    """بعد از دریافت جواب صدا زده می‌شه؛ توکن مصرفی رو (امروز + کل) اضافه می‌کنه."""
    if not tokens:
        return
    try:
        await db.ai_inc_tokens(uid, tokens)
    except Exception:
        logger.exception("ثبت توکن مصرفی هوشیار ناموفق بود")


# ══════════════════════════════════════════════════
#  فلوی کاربر — دکمه‌ی «🤖 هوشیار» در منوی اصلی
# ══════════════════════════════════════════════════

async def show_ai_intro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    # 🌊 W7 — گیت فیچر (پیش‌فرض FREE ⇒ بدون تغییر رفتار امروز)
    from subscription import feature_allowed, show_paywall
    if not await feature_allowed(uid, "ai_chat"):
        await show_paywall(update.message, uid, feature="ai_chat")
        return
    cfg = await get_ai_config()

    if not cfg['enabled']:
        await update.message.reply_text(
            "🤖 بخش «هوشیار» فعلاً توسط مدیریت غیرفعال است. بعداً دوباره سر بزن."
        )
        return

    context.user_data['mode'] = 'ai_query'

    limit = await db.ai_limit_for_user(uid, cfg['daily_limit'])
    if uid == ADMIN_ID or limit <= 0:
        quota_line = "🔓 امروز محدودیتی نداری — هر چقدر دلت خواست بپرس"
    else:
        user  = await db.get_user(uid) or {}
        today = today_tehran().isoformat()
        used  = user.get('ai_usage_count', 0) if user.get('ai_usage_date') == today else 0
        quota_line = f"📊 تا الان {used} از {limit} سوالِ امروزتو استفاده کردی"

    await update.message.reply_text(
        "⚡️ <b>سلام، هوشیارم!</b>\n"
        "همون هم‌کلاسیِ باهوش‌تر که همیشه حاضر به کمکه 😎\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "هر جور راحتی سوالتو بفرست:\n"
        "📝 تایپ کن، ساده و مستقیم\n"
        "📷 عکسِ سوال رو بفرست (می‌تونی زیرش توضیح هم بنویسی)\n"
        "📄 یا جزوه/برگه‌ت رو به‌صورت PDF بفرست\n"
        "🎙️ یا اصلاً برام ویس بفرست و سوالتو بگو، حوصله‌ی تایپ نداری بی‌خیال\n\n"
        f"{quota_line}\n\n"
        "💡 فقط یه نکته: من هوش مصنوعی‌ام، نه پیغمبر! ممکنه یه‌جا اشتباه کنم — "
        "برای چیزای مهم حتماً با منبع درسی یا استاد هم یه چک بزن.\n\n"
        "هر وقت خواستی بری سراغ کارِ دیگه، کافیه یه دکمه‌ی دیگه از منو رو بزنی — "
        "من همیشه همینجام 👋",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🎨 ساخت تصویر", callback_data='aiu:imgstart'),
        ]]) if cfg.get('image_enabled') else None,
    )


def _footer(limit: int, used: int) -> str:
    if not limit:
        return ""
    return f"\n\n📊 {used}/{limit} سوال امروز"


# ══════════════════════════════════════════════════
#  عبارت‌های بامزه‌ی «در حال فکر کردن» و «طول کشیدن»
#  هرچی جواب دیرتر بیاد، پیام یکی‌یکی عوض می‌شه و باحال‌تر می‌شه 😄
# ══════════════════════════════════════════════════
THINKING_PHRASES = [
    "💭 در حال فکر کردن...",
    "🧠 هوشیار داره رو سوالت مغز می‌ریزه...",
    "🔎 دارم سوالتو دقیق می‌خونم...",
    "⚡️ یه لحظه، دارم جوابتو آماده می‌کنم...",
    "📖 دارم می‌رم سراغ جواب...",
    "🚀 موشکِ فکر کردن پرتاب شد، منتظر بمون...",
    "🍿 بشین یه چیزی ببین، الان میام با جواب...",
]

STALL_PHRASES = [
    "🕵️‍♂️ هوشیار رفته کوچه‌پس‌کوچه‌های اینترنت دنبال جوابت بگرده...",
    "🤯 مخِ هوشیار یه لحظه هنگید، یه دقه صبر کن 😂",
    "⏳ ویت‌ا‌مینت (wait a minute)... دارم روش کار می‌کنم",
    "😎 صبر کن رفیق، الان بهت میگم...",
    "🥹 عزیزم بذار یه‌کم فکر کنم...",
    "📚 دارم کتابای قطور رو ورق می‌زنم، یه لحظه صبر کن...",
    "🧩 دارم تیکه‌های جواب رو کنار هم می‌چینم...",
    "☕️ یه چایی بریز، دارم رو جوابت کار می‌کنم...",
    "🌀 مغزم داره لود می‌شه... ۹۹٪ ... یه‌کم دیگه مونده",
    "🔬 دارم زیر ذره‌بین بررسیش می‌کنم، صبور باش...",
    "🛰 دارم از فضا سیگنال جواب رو می‌گیرم، یه لحظه...",
    "🎯 دقیقاً دارم رو نشونه می‌رم، چند لحظه‌ی دیگه می‌رسم...",
    "🐌 اینترنتم امروز یه‌کم تنبله، ولی دارم میام...",
    "🧙‍♂️ داره یه طلسمِ علمی رو می‌خونم، یه ثانیه...",
    "🍃 نفس عمیق بکش، جوابت داره می‌رسه...",
    "😵‍💫 اوه اوه سوالت باحاله‌ها، بذار درست فکر کنم...",
    "🕰 یه چرخِ کوچولو بزن، الان جوابتو در میارم...",
    "🥱 نه بابا خوابم نبرد، دارم فکر می‌کنم فقط 😄",
    "🍵 یه استکان چایی بخور تا من فکرامو جمع کنم...",
    "📡 آنتنام یه‌کم ضعیفه، دارم سیگنال جواب رو می‌گیرم...",
    "🧑‍🔬 دارم توی آزمایشگاه مغزم دنبالش می‌گردم...",
    "🐢 آروم‌آروم داریم می‌رسیم به جواب، صبور باش رفیق...",
    "🎲 تاس جواب رو انداختم، منتظر بمون ببینم چی میاد 😂",
    "🍔 بذار اول این لقمه فکرو قورت بدم، الان میام...",
    "🚦 چراغ فکر کردن سبز شد، دارم می‌رونم سمت جواب...",
    "🧵 دارم نخِ جواب رو از کلاف درسا در میارم...",
    "🐝 مثل زنبورِ کارگر دارم روش وز‌وز می‌کنم...",
    "🎧 یه آهنگ بذار تا من مغزمو داغ کنم...",
    "🧊 مخم یخ زده بود، دارم گرمش می‌کنم دوباره 😅",
    "🏃‍♂️ دارم می‌دوئم سمت جواب، نفس‌نفس می‌زنم ولی می‌رسم...",
    "🧵 دارم سرنخ سوالتو دنبال می‌کنم...",
    "🛎 زنگ فکر کردن به صدا در اومد، یه لحظه...",
    "🎨 دارم جوابتو رنگ‌آمیزی می‌کنم، قشنگ میشه...",
    "🍜 عینِ رشته‌ی آش دارم افکارمو جمع می‌کنم...",
    "🧨 ترقه‌ی فکر منفجر شد، الان می‌گم چی شد 😂",
    "🚴‍♂️ دارم رکاب می‌زنم سمت جواب، نزدیکم...",
    "🧃 یه‌کم آبمیوه بخور، من دارم فکر می‌کنم...",
    "🏗 دارم جوابتو از پایه می‌سازم، محکم باشه بهتره...",
    "🎬 صحنه‌ی «هوشیار داره فکر می‌کنه» رو تصور کن، الان تمومه...",
    "🐇 خرگوش فکرم داره می‌دوئه، تقریباً رسیدیم...",
]


def _pick_unused(pool: list, used: set) -> str:
    choices = [p for p in pool if p not in used] or pool
    choice = random.choice(choices)
    used.add(choice)
    return choice


# ══════════════════════════════════════════════════
#  تبدیل Markdown سبکِ خروجیِ مدل (**bold**, `code`, لیست‌ها، #تیتر) به
#  HTML قابل‌نمایش در تلگرام. ⚠️ فیکس باگ: قبلاً متنِ خامِ AI بدون هیچ
#  parse_mode ای فرستاده می‌شد، برای همین کاراکترهای «**» و امثالش عیناً
#  توی پیامِ کاربر دیده می‌شدن. اول باید کاراکترهای خاصِ HTML (& < >) رو
#  escape کنیم (که خودِ متنِ AI باعث خرابیِ پارسِ HTML نشه)، بعد الگوهای
#  Markdown رو به تگ‌های HTML تبدیل کنیم.
# ══════════════════════════════════════════════════

def _md_to_telegram_html(text: str) -> str:
    if not text:
        return text
    out = _esc(text, quote=False)                                      # 1) امن‌سازی HTML
    out = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', out, flags=re.S)       # 2) **bold**
    out = re.sub(r'(?m)^#{1,6}\s*(.+)$', r'<b>\1</b>', out)             # 3) # تیتر → بولد
    out = re.sub(r'`([^`\n]+?)`', r'<code>\1</code>', out)              # 4) `code`
    out = re.sub(r'(?m)^[*\-]\s+', '• ', out)                          # 5) لیست * یا - → •
    out = re.sub(r'(?<!\w)_(?!_)(.+?)(?<!_)_(?!\w)', r'<i>\1</i>', out)  # 6) _italic_
    return out


EDIT_THROTTLE_SECONDS = 0.7   # حداقل فاصله بین دو ادیتِ پیام حین استریم (جلوگیری از Flood-limit تلگرام)


async def _typing_pinger(context: ContextTypes.DEFAULT_TYPE, chat_id: int, stop_event: asyncio.Event):
    """در پس‌زمینه هر چند ثانیه یک‌بار وضعیتِ «در حال تایپ» رو نگه می‌داره — تا وقتی stop_event ست بشه."""
    while not stop_event.is_set():
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action='typing')
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=4)
        except asyncio.TimeoutError:
            pass


async def _answer_with_live_edit(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                  stream_gen, footer_suffix: str,
                                  uid: int, question_label: str) -> None:
    """
    ⚠️ قابلیتِ جدید: پاسخِ استریمینگِ واقعی — به‌جای اینکه یک‌جا منتظرِ
    کلِ جواب بمونیم و بعد نشونش بدیم، همون‌طور که متن از Gemini می‌رسه،
    پیام رو تدریجاً (با یه throttle برای رعایتِ محدودیتِ ویرایشِ تلگرام)
    آپدیت می‌کنیم — دقیقاً حسِ «داره جلوی چشمت تایپ می‌کنه» رو می‌ده.
    اگه جواب موفق بود: توی حافظه‌ی مکالمه ثبتش می‌کنه، توکن مصرفی رو به
    دیتابیس اضافه می‌کنه، و زیرِ پیام دکمه‌ها رو می‌ذاره.
    """
    chat_id = update.effective_chat.id
    thinking_msg = await context.bot.send_message(chat_id, random.choice(THINKING_PHRASES))

    stop_event = asyncio.Event()
    pinger = asyncio.ensure_future(_typing_pinger(context, chat_id, stop_event))

    buffer: list = []
    tokens = 0
    answer_text = None
    last_edit_at = 0.0
    last_edit_len = 0
    final_text = ''

    try:
        async for event in stream_gen:
            if event['type'] == 'delta':
                buffer.append(event['text'])
                now = time.time()
                raw_partial = ''.join(buffer)
                # ⚠️ فیکس باگِ «فقط یه خط | میاد بعد یهو کل پیام»: قبلاً
                # اولین دلتا (حتی اگه فقط ۱-۲ کاراکتر بود) بلافاصله ادیت
                # می‌شد (چون last_edit_at از 0.0 شروع می‌شد)، و چون throttle
                # طولانی بود (1.3 ثانیه) و خیلی از جواب‌ها زودتر از اون
                # تموم می‌شدن، هیچ ادیتِ میانی‌ای اتفاق نمی‌افتاد — نتیجه:
                # یه پیامِ تقریباً خالی، بعد یهو جوابِ کامل جای‌گزینش می‌شد.
                # حالا: هم فاصله‌ی زمانی کوتاه‌تره، هم یه شرطِ «حجمِ متنِ
                # جدید» اضافه شده تا حتی برای جواب‌های کوتاه هم چند بار
                # واقعی آپدیت بشه، و هم اولین ادیت با حداقل چند کاراکتر
                # محتوا انجام می‌شه (نه یه پیامِ تقریباً خالی).
                should_edit = len(raw_partial) >= 8 and (
                    now - last_edit_at >= EDIT_THROTTLE_SECONDS or
                    len(raw_partial) - last_edit_len >= 50
                )
                if should_edit:
                    display = raw_partial[:3480] + "…" if len(raw_partial) > 3480 else raw_partial
                    try:
                        await thinking_msg.edit_text(
                            f"🤖 {_md_to_telegram_html(display)} ▌", parse_mode='HTML',
                        )
                    except Exception:
                        pass   # مثلاً «message not modified» یا محدودیتِ نرخ — بی‌خیالش شو، دورِ بعد دوباره امتحان می‌شه
                    last_edit_at = now
                    last_edit_len = len(raw_partial)
            elif event['type'] == 'done':
                answer_text = event['answer']
                tokens = event['tokens']

        raw_answer = answer_text or ''
        # ⚠️ برشِ طولِ پیام روی متنِ خام (نه HTML) انجام می‌شه تا هیچ‌وقت
        # وسطِ یه تگ قطع نشه.
        if len(raw_answer) > 3500:
            raw_answer = raw_answer[:3480] + "…"
        final_text = f"🤖 {_md_to_telegram_html(raw_answer)}{_esc(footer_suffix, quote=False)}"

    except AIConfigError as e:
        # ⚠️ این خطا فنیه و فقط برای ادمین معنی داره. دانشجو فقط یه پیامِ
        # ساده می‌بینه، و متنِ فنی مستقیم برای ادمین ارشد فوروارد می‌شه.
        final_text = (
            "⚠️ هوشیار الان یه مشکل فنی داره و نمی‌تونه درست جواب بده.\n"
            "به ادمین اطلاع داده شد؛ لطفاً چند دقیقه‌ی دیگه دوباره امتحان کن 🙏"
        )
        if ADMIN_ID:
            try:
                await context.bot.send_message(
                    ADMIN_ID,
                    "🛠 <b>خطای فنیِ هوشیار</b> (فقط برای شما نمایش داده می‌شه؛ کاربر پیامِ ساده دید)\n\n"
                    f"👤 کاربر: {_esc(update.effective_user.full_name or '—')} "
                    f"(<code>{uid}</code>)\n\n"
                    f"❓ سوال:\n{_esc(question_label[:500])}\n\n"
                    f"🧩 جزئیات خطا:\n{_esc(str(e))}",
                    parse_mode='HTML',
                )
            except Exception:
                logger.exception("ارسال هشدار خطای فنیِ هوشیار به ادمین ناموفق بود")
    except AIError as e:
        final_text = f"⚠️ {_esc(str(e), quote=False)}"
    except Exception:
        logger.exception("AI error")
        final_text = "⚠️ مشکلی در ارتباط با سرویس هوش مصنوعی پیش اومد، دوباره امتحان کن."
    finally:
        stop_event.set()
        pinger.cancel()
        try:
            await pinger
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    if len(final_text) > 4000:  # محافظِ نهایی (به‌ندرت لازم می‌شه)
        final_text = final_text[:3990] + "…"

    reply_markup = None
    if answer_text:
        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔬 مثال بزن", callback_data="aiu:fu:example"),
                InlineKeyboardButton("📝 خلاصه‌ترش کن", callback_data="aiu:fu:summary"),
                InlineKeyboardButton("🎯 سوالِ مشابه", callback_data="aiu:fu:similar"),
            ],
            [
                InlineKeyboardButton("🆕 گفتگوی جدید", callback_data="aiu:newchat"),
                InlineKeyboardButton("🚩 گزارش این جواب", callback_data=f"aiu:report:{chat_id}:{thinking_msg.message_id}"),
            ],
        ])

    try:
        await thinking_msg.edit_text(final_text, reply_markup=reply_markup, parse_mode='HTML')
    except Exception:
        try:
            await thinking_msg.edit_text(final_text, reply_markup=reply_markup)
        except Exception:
            await context.bot.send_message(chat_id, final_text, reply_markup=reply_markup)

    if tokens:
        await record_token_usage(uid, tokens)

    if answer_text:
        await _remember(uid, 'user', question_label)
        await _remember(uid, 'assistant', answer_text)
        _cache_for_report(
            chat_id, thinking_msg.message_id, uid,
            update.effective_user.full_name, question_label, answer_text,
        )


# ══════════════════════════════════════════════════
#  قفل هم‌زمانی — جلوگیری از اینکه یک کاربر قبل از تمام‌شدن جواب سوال
#  قبلی‌اش، سوال دومی بفرسته و دو تا درخواست هم‌زمان برای AI اجرا بشه
#  (هم هزینه‌ی اضافه داره، هم می‌تونه باعث به‌هم‌ریختن پیامِ در حال ادیت
#  بشه چون هر دو تا درخواست دارن روی یک thinking_msg کار می‌کنن).
# ══════════════════════════════════════════════════
_busy_users: set = set()

#: TTL قفلِ «یک پرسشِ در جریان». از سقفِ منطقیِ یک پاسخِ استریمی بلندتر است
#: تا پاسخ‌های کند قطع نشوند، ولی آن‌قدر کوتاه که کرشِ یک پراسس کاربر را
#: بیش از این مدت قفل نکند (op_claim قفلِ منقضی را خودش تحویل می‌گیرد).
AI_INFLIGHT_TTL = 180


async def ai_claim_inflight(uid: int) -> bool:
    """ادعای «این کاربر همین حالا یک پرسشِ در جریان دارد» — بین پراسس‌ها.

    🔧 FIX هم‌زمانیِ واقعی: `_busy_users` یک set درون‌پراسسی است و طبق
    supervisord، ربات و API دو پراسس جدا هستند. یعنی کاربر می‌توانست
    هم‌زمان یکی از ربات و یکی از مینی‌اپ بفرستد و هر دو رد شوند از گاردِ
    محلی — دو درخواستِ هم‌زمان به provider، دو بار هزینه، و در ربات دو
    تسک روی یک پیامِ در حال ادیت. سقفِ روزانه از قبل اتمیک بود
    (`db.ai_consume_quota`)، ولی «یکی در لحظه» نبود.

    حالا set محلی به‌عنوان مسیرِ سریع می‌ماند و قفلِ مشترکِ دیتابیس
    (همان `admin_op_locks` که قبلاً برای اشتراک استفاده می‌شد) تصمیمِ
    نهایی است. اگر دیتابیس در دسترس نباشد `op_claim` عمداً fail-open است
    ⇒ رفتار دقیقاً به حالتِ امروز برمی‌گردد، نه بدتر.
    """
    uid = int(uid)
    if uid in _busy_users:
        return False
    try:
        from database import db
        if not await db.op_claim('ai_inflight', str(uid), ttl_seconds=AI_INFLIGHT_TTL):
            return False
    except Exception:
        logger.exception("ai_claim_inflight degraded for %s", uid)
    _busy_users.add(uid)
    return True


async def ai_is_inflight(uid: int) -> bool:
    """آیا این کاربر همین حالا پرسشی در جریان دارد؟ (فقط خواندن)

    برای گاردهای *مخرب* استفاده می‌شود (پاک‌کردن حافظه/سندِ مرجع وسطِ
    استریم). چون قفل در `admin_op_locks` مشترک است، پاسخِ در جریان در
    پراسسِ ربات هم دیده می‌شود — نه فقط درخواست‌های همین پراسس.
    """
    uid = int(uid)
    if uid in _busy_users:
        return True
    try:
        from database import db
        doc = await db.admin_op_locks.find_one({'_id': f"ai_inflight:{uid}"})
        if not doc:
            return False
        expires = doc.get('expires_at')
        return not expires or expires > now_utc()
    except Exception:
        logger.exception("ai_is_inflight check degraded for %s", uid)
        return False


async def ai_release_inflight(uid: int) -> None:
    """آزادسازی قفلِ پرسشِ در جریان — همیشه در finally صدا زده می‌شود."""
    uid = int(uid)
    _busy_users.discard(uid)
    try:
        from database import db
        await db.op_release('ai_inflight', str(uid))
    except Exception:
        logger.exception("ai_release_inflight failed for %s", uid)


async def handle_ai_image_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🎨 تولید تصویر در بات — متنِ حالتِ ai_image_prompt.

    ترتیبِ گاردها عمداً همین است: ban → enabled → اعتبارسنجی ورودی →
    سهمیه → قفلِ سراسری → provider؛ سهمیه فقط **بعد از موفقیت** مصرف
    می‌شود تا شکستِ provider سهمیه‌ی کاربر را نسوزاند.
    """
    uid  = update.effective_user.id
    # 🌊 W7 — گیت فیچر (پیش‌فرض FREE ⇒ بدون تغییر رفتار امروز)
    from subscription import feature_allowed, show_paywall
    if not await feature_allowed(uid, "ai_image"):
        context.user_data.pop('mode', None)
        await show_paywall(update.message, uid, feature="ai_image")
        return
    text = (update.message.text or '').strip()
    if not text:
        return

    cfg = await get_ai_config()
    if not cfg['enabled'] or not cfg.get('image_enabled'):
        context.user_data.pop('mode', None)
        await update.message.reply_text(cfg.get('disabled_message') or DEFAULT_DISABLED_MSG)
        return

    # universal image: use image_provider/image_api_key from vault, not hard-coded gemini
    effective_key = cfg.get('image_api_key') or cfg.get('api_key') or ''
    effective_model = cfg.get('image_model') or DEFAULT_IMAGE_MODEL
    effective_provider = cfg.get('image_provider') or cfg.get('provider') or 'gemini'
    if not effective_key:
        context.user_data.pop('mode', None)
        await update.message.reply_text(
            "🎨 کلید API برای ساخت تصویر هنوز تنظیم نشده — از پنل مدیریت کلید مربوطه را وارد کن.")
        return

    if await db.ai_is_banned(uid):
        context.user_data.pop('mode', None)
        await update.message.reply_text(AI_BANNED_MSG, disable_web_page_preview=True)
        return

    if not (IMAGE_PROMPT_MIN <= len(text) <= IMAGE_PROMPT_MAX):
        await update.message.reply_text(
            f"✋ توضیح تصویر باید بین {IMAGE_PROMPT_MIN} و "
            f"{IMAGE_PROMPT_MAX} نویسه باشه.")
        return

    img_limit = cfg['image_daily_limit']
    today = today_tehran().isoformat()
    if uid != ADMIN_ID and img_limit > 0:
        used = await db.ai_image_used_today(uid, today)
        if used >= img_limit:
            await update.message.reply_text(
                f"📊 سهمیه‌ی امروزت ({img_limit} تصویر) تموم شده — "
                "فردا دوباره بیا، یا از حالت پرسش استفاده کن. 💬")
            return

    claimed = await ai_claim_inflight(uid)
    if not claimed:
        await update.message.reply_text(
            "⏳ یه لحظه! یه درخواست هوش مصنوعی‌ات هنوز در حال انجامه — "
            "صبر کن تموم شه، بعد اینو بزن.")
        return

    status = await update.message.reply_text(
        "🎨 در حال ساخت تصویر... یه لحظه صبر کن 🖌️\n"
        "(ممکنه تا یک دقیقه طول بکشه)")
    try:
        try:
            res = await generate_image(effective_key, effective_model,
                                       text, '1:1', provider=effective_provider)
        except AiImageError as e:
            logger.warning("bot image generation failed uid=%s code=%s",
                           uid, e.code)
            await status.edit_text(e.user_message)
            return

        img_bytes = base64.b64decode(res['data_b64'])
        from io import BytesIO
        await update.message.reply_photo(
            BytesIO(img_bytes), filename='humsyar_image.png',
            caption=f"🎨 تصویرت آماده شد!\n«{text[:80]}»")
        if uid != ADMIN_ID and img_limit > 0:
            try:
                await db.ai_image_inc(uid, today)
            except Exception:
                logger.exception("ثبت مصرف تصویر ناموفق بود uid=%s", uid)
        try:
            await status.edit_text("✅ تصویرت ارسال شد!")
        except Exception:
            pass  # پیامِ وضعیت پاک نشه — مشکلی نیست
    except Exception:
        logger.exception("bot image generation crashed uid=%s", uid)
        try:
            await status.edit_text(
                "❌ یه مشکلِ فنی پیش اومد؛ چند لحظه دیگه دوباره تلاش کن.")
        except Exception:
            pass
    finally:
        await ai_release_inflight(uid)


async def handle_ai_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    # 🌊 W7 — گیت فیچر (پیش‌فرض FREE ⇒ بدون تغییر رفتار امروز)
    from subscription import feature_allowed, show_paywall
    if not await feature_allowed(uid, "ai_chat"):
        context.user_data.pop('mode', None)
        await show_paywall(update.message, uid, feature="ai_chat")
        return
    text = (update.message.text or '').strip()
    if not text:
        return

    cfg = await get_ai_config()
    if not cfg['enabled']:
        context.user_data.pop('mode', None)
        await update.message.reply_text(cfg.get('disabled_message') or DEFAULT_DISABLED_MSG)
        return

    if await db.ai_is_banned(uid):
        await update.message.reply_text(AI_BANNED_MSG)
        return

    if len(text) > MAX_INPUT_CHARS:
        await update.message.reply_text(
            f"✍️ سوالت یه‌کم طولانیه (بیشتر از {MAX_INPUT_CHARS} کاراکتر). "
            "لطفاً خلاصه‌ترش کن یا فقط بخش اصلی سوال رو بفرست."
        )
        return

    # قفل *قبل* از مصرفِ سهمیه گرفته می‌شود: اگر بعد از کسرِ سهمیه رد
    # می‌شدیم، درخواستِ دومِ هم‌زمان یک واحد از سهمیه را می‌سوزاند بدون
    # اینکه هیچ پاسخی بگیرد.
    if not await ai_claim_inflight(uid):
        await update.message.reply_text("⏳ صبر کن جواب سوال قبلی‌ت آماده بشه، بعد این یکی رو بفرست 🙂")
        return

    try:
        allowed, used, limit = await check_and_consume_quota(uid)
        if not allowed:
            await update.message.reply_text(
                f"⛔️ سقف روزانه‌ی سوال از هوشیار تموم شده ({used}/{limit}).\n"
                "فردا دوباره امتحان کن."
            )
            return

        history = await _get_history(uid)
        await _answer_with_live_edit(
            update, context, ask_ai_stream(text=text, history=history, uid=uid),
            _footer(limit, used), uid, text,
        )
    finally:
        await ai_release_inflight(uid)


MAX_MEDIA_BYTES = 15 * 1024 * 1024  # ⚠️ قابلیتِ جدید (PDF/صدا): سقفِ حجمِ فایلِ ورودی

def _find_ffmpeg() -> str | None:
    """
    اول دنبالِ ffmpeg سیستمی می‌گرده (شاید ادمین با apt نصبش کرده باشه).
    اگه پیدا نشد، سراغِ پکیجِ pip به‌اسمِ imageio-ffmpeg می‌ره — این پکیج
    یه نسخه‌ی آماده‌ی ffmpeg رو خودش موقعِ نصب دانلود می‌کنه، پس نیازی
    به sudo/apt روی سرور نیست؛ کافیه توی requirements.txt باشه.
    """
    path = shutil.which('ffmpeg')
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


_FFMPEG_PATH = _find_ffmpeg()  # فقط یک بار موقعِ import چک می‌شه


async def _transcode_ogg_opus_to_wav(ogg_bytes: bytes) -> bytes | None:
    """
    ⚠️ فیکسِ باگِ «ارور ۴۰۰ روی پیامِ صوتی»: پیام‌های صوتیِ تلگرام با
    فرمتِ OGG (کدکِ Opus) ضبط می‌شن، ولی طبقِ مستنداتِ رسمیِ گوگل،
    Gemini از «OGG Vorbis» پشتیبانی می‌کنه، نه Opus — همین ناهماهنگی
    باعثِ ارور ۴۰۰ می‌شد. اینجا با ffmpeg (اگه روی سرور نصب باشه) به
    WAV (که همه‌جا پشتیبانی می‌شه) تبدیلش می‌کنیم. اگه ffmpeg نصب نبود،
    None برمی‌گردونه و فراخوان باید به کاربر پیامِ روشن بده.
    """
    if not _FFMPEG_PATH:
        return None
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            _FFMPEG_PATH, '-y', '-i', 'pipe:0', '-ar', '16000', '-ac', '1', '-f', 'wav', 'pipe:1',
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        wav_bytes, stderr = await asyncio.wait_for(proc.communicate(input=ogg_bytes), timeout=30)
        if proc.returncode != 0 or not wav_bytes:
            logger.warning("ffmpeg transcode شکست خورد: %s", (stderr or b'')[:300])
            return None
        return wav_bytes
    except Exception:
        logger.exception("تبدیلِ صدا با ffmpeg ناموفق بود")
        return None


async def handle_ai_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    ⚠️ قابلیتِ جدید: قبلاً این تابع (به اسمِ handle_ai_photo) فقط عکس
    قبول می‌کرد. الان از همین ساختارِ inline_data که Gemini برای هر نوع
    رسانه‌ای پشتیبانی می‌کنه، برای PDF (جزوه/برگه‌ی اسکن‌شده) و پیامِ
    صوتی/فایلِ صوتی (سوالِ گفتاری) هم استفاده می‌کنیم — بدون تغییری در
    مدلِ هزینه (این‌ها هم جزوِ همون Free Tier هستن).
    """
    uid = update.effective_user.id
    # 🌊 W7 — گیت فیچر (پیش‌فرض FREE ⇒ بدون تغییر رفتار امروز)
    from subscription import feature_allowed, show_paywall
    if not await feature_allowed(uid, "ai_chat"):
        context.user_data.pop('mode', None)
        await show_paywall(update.message, uid, feature="ai_chat")
        return

    cfg = await get_ai_config()
    if not cfg['enabled']:
        context.user_data.pop('mode', None)
        await update.message.reply_text(cfg.get('disabled_message') or DEFAULT_DISABLED_MSG)
        return

    if await db.ai_is_banned(uid):
        await update.message.reply_text(AI_BANNED_MSG)
        return

    kind = None
    if update.message.photo:
        tg_file = await update.message.photo[-1].get_file()
        mime, kind = 'image/jpeg', 'image'
    elif update.message.voice:
        tg_file = await update.message.voice.get_file()
        mime, kind = (update.message.voice.mime_type or 'audio/ogg'), 'audio'
    elif update.message.audio:
        tg_file = await update.message.audio.get_file()
        mime, kind = (update.message.audio.mime_type or 'audio/mpeg'), 'audio'
    elif update.message.document:
        doc_mime = update.message.document.mime_type or ''
        if doc_mime.startswith('image/'):
            tg_file = await update.message.document.get_file()
            mime, kind = doc_mime, 'image'
        elif doc_mime == 'application/pdf':
            tg_file = await update.message.document.get_file()
            mime, kind = doc_mime, 'pdf'
        else:
            return  # نوع فایل پشتیبانی‌نشده — نادیده گرفته می‌شود
    else:
        return

    # PDF و صدا فقط از طریقِ Gemini کار می‌کنن (OpenRouter برای این
    # نوع‌ها راه‌اندازی نشده)؛ اگه ادمین ارائه‌دهنده رو روی OpenRouter
    # گذاشته، مودبانه بگو فقط عکس/متن پشتیبانی می‌شه.
    if kind != 'image' and cfg['provider'] != 'gemini':
        await update.message.reply_text(
            "⚠️ فعلاً فقط عکس یا متن رو می‌تونم پردازش کنم "
            "(فایلِ PDF/صوتی فقط با ارائه‌دهنده‌ی Gemini کار می‌کنه)."
        )
        return

    if getattr(tg_file, 'file_size', None) and tg_file.file_size > MAX_MEDIA_BYTES:
        await update.message.reply_text(
            f"⚠️ حجمِ فایل بیشتر از {MAX_MEDIA_BYTES // (1024*1024)} مگابایته — "
            "یه نسخه‌ی کوچیک‌تر بفرست."
        )
        return

    caption = (update.message.caption or '').strip() or None
    if caption and len(caption) > MAX_INPUT_CHARS:
        await update.message.reply_text(
            f"✍️ توضیحِ فایل یه‌کم طولانیه (بیشتر از {MAX_INPUT_CHARS} کاراکتر). "
            "لطفاً خلاصه‌ترش کن."
        )
        return

    # قفلِ مشترکِ بین‌پراسسی از همین‌جا گرفته می‌شود تا دانلودِ فایل و
    # transcode هم زیر همان ادعا باشند (این‌ها گران‌اند و نباید دوباره
    # به‌ازای یک درخواستِ هم‌زمانِ مینی‌اپ تکرار شوند).
    if not await ai_claim_inflight(uid):
        await update.message.reply_text("⏳ صبر کن جواب سوال قبلی‌ت آماده بشه، بعد این یکی رو بفرست 🙂")
        return

    try:
        try:
            media_bytes = bytes(await tg_file.download_as_bytearray())
        except Exception:
            logger.exception("دانلود فایل هوشیار ناموفق بود")
            await update.message.reply_text("⚠️ دانلودِ فایل ناموفق بود — دوباره امتحان کن.")
            return

        # ⚠️ فیکسِ ارورِ ۴۰۰: پیام‌های صوتیِ تلگرام OGG/Opus هستن، ولی Gemini
        # فقط OGG Vorbis رو قبول می‌کنه. قبل از فرستادن (و قبل از مصرفِ
        # سهمیه‌ی روزانه) تبدیلش می‌کنیم — اگه تبدیل شکست بخوره، کاربر
        # سهمیه‌شو الکی از دست نده.
        if kind == 'audio' and 'ogg' in mime.lower():
            wav_bytes = await _transcode_ogg_opus_to_wav(media_bytes)
            if wav_bytes:
                media_bytes, mime = wav_bytes, 'audio/wav'
            else:
                await update.message.reply_text(
                    "⚠️ فعلاً امکانِ پردازشِ این پیامِ صوتی نیست (مشکلِ سازگاریِ فرمت). "
                    "لطفاً سوالتو تایپ کن یا عکس/PDF بفرست — یا به ادمین اطلاع بده."
                )
                return

        # ⚠️ قابلیتِ جدید: «سندِ مرجعِ فعال» — به‌جای فرستادنِ PDF به‌صورتِ
        # inline (که فقط برای همین یه سوال کار می‌کنه)، آپلودش می‌کنیم روی
        # Gemini Files API (رایگان، ۴۸ ساعت نگه‌داری) و فقط یه اشاره‌گرِ
        # کوچیک ذخیره می‌کنیم. این‌جوری سوالاتِ بعدیِ همین دانشجو هم خودکار
        # به همین سند دسترسی دارن، بدون اینکه دوباره بفرستتش.
        display_name = None
        if update.message.document:
            display_name = update.message.document.file_name
        if kind == 'pdf':
            try:
                file_info = await _gemini_upload_file(cfg['api_key'], media_bytes, mime, display_name or 'جزوه.pdf')
                await db.ai_set_doc(uid, file_info['uri'], file_info.get('mimeType', mime), display_name or 'جزوه')
                media_bytes = None   # دیگه لازم نیست inline بفرستیمش؛ از طریقِ doc reference میره
            except Exception:
                logger.exception("آپلودِ PDF به Gemini Files API ناموفق بود")
                await update.message.reply_text("⚠️ آپلودِ فایل ناموفق بود — دوباره امتحان کن.")
                return

        allowed, used, limit = await check_and_consume_quota(uid)
        if not allowed:
            await update.message.reply_text(
                f"⛔️ سقف روزانه‌ی سوال از هوشیار تموم شده ({used}/{limit}).\n"
                "فردا دوباره امتحان کن."
            )
            return

        labels = {
            'image': "[یک سوال به‌صورت عکس فرستاد]",
            'pdf':   f"[یک فایل PDF فرستاد: {display_name or 'جزوه'} — به‌عنوانِ سندِ مرجع ذخیره شد]",
            'audio': "[یک پیام صوتی فرستاد]",
        }
        question_label = caption or labels.get(kind, "[یک فایل فرستاد]")

        history = await _get_history(uid)
        await _answer_with_live_edit(
            update, context,
            ask_ai_stream(text=caption, image_bytes=media_bytes, image_mime=mime, history=history, uid=uid),
            _footer(limit, used), uid, question_label,
        )
    finally:
        await ai_release_inflight(uid)


# ══════════════════════════════════════════════════
#  دکمه‌های زیرِ جواب («🆕 گفتگوی جدید» / «🚩 گزارش این جواب») —
#  callback_data با پیشوند aiu: (برای هر کاربری، برخلاف ai: که مخصوص
#  پنل ادمینه).
# ══════════════════════════════════════════════════

async def ai_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    uid    = update.effective_user.id
    parts  = query.data.split(':')
    action = parts[1] if len(parts) > 1 else ''

    if action == 'newchat':
        await _clear_memory(uid)
        await db.ai_clear_doc(uid)
        await query.answer("✅ حافظه‌ی مکالمه (و سندِ مرجعِ فعال، اگه بود) پاک شد؛ از اول شروع کن 🙂", show_alert=True)
        return

    if action == 'imgstart':
        await query.answer()
        cfg = await get_ai_config()
        if not cfg['enabled'] or not cfg.get('image_enabled'):
            await query.message.reply_text(
                "🎨 بخشِ ساخت تصویر فعلاً توسط مدیریت غیرفعال است.")
            return
        # universal image — any provider allowed, just check image_enabled
        # (key check is done at generation time, so button stays enabled for all providers)
        context.user_data['mode'] = 'ai_image_prompt'
        context.user_data['last_question'] = ''
        img_limit = cfg['image_daily_limit']
        if uid == ADMIN_ID or img_limit <= 0:
            q_line = "🔓 امروز محدودیتی نداری."
        else:
            used = await db.ai_image_used_today(uid, today_tehran().isoformat())
            q_line = f"📊 {used} از {img_limit} تصویرِ امروزت استفاده شده."
        await query.message.reply_text(
            "🎨 <b>حالت ساخت تصویر</b>\n\n"
            "توضیح تصویری که می‌خوای رو <b>همینجا تایپ کن</b> — هرچی "
            "جزئیات بیشتر بدی، نتیجه بهتر می‌شه:\n\n"
            "مثلاً: «یک کتابخانه‌ی چوبیِ گرم با نور عصرگاهی، سبک "
            "واقع‌گرایانه»\n\n"
            "برای بازگشت به حالت سوال، فقط سوالتو بفرست یا از منو «پرسش از "
            "هوشیار» رو دوباره بزن.\n"
            "برای لغو: /cancel",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "💬 بازگشت به پرسش", callback_data='aiu:imgoff')],
            ]),
        )
        return

    if action == 'imgoff':
        await query.answer("💬 برگشتیم به حالت پرسش.", show_alert=False)
        context.user_data['mode'] = 'ai_query'
        await query.message.reply_text(
            "💬 هر سوالی داری بفرست؛ برای ساخت تصویر دوباره از منو یا "
            "دکمه‌ی 🎨 استفاده کن.")
        return

    if action == 'fu':
        fu_type = parts[2] if len(parts) > 2 else ''
        prompts = {
            'example': 'یه مثالِ ملموس و کاربردی برای همون چیزی که الان توضیح دادی بزن.',
            'summary': 'همون جوابِ قبلی رو خیلی خلاصه‌تر (در حد ۲ تا ۳ خط) بگو.',
            'similar': 'یه سوالِ چهارگزینه‌ایِ مشابهِ همون موضوع بساز و ازم بپرس.',
        }
        prompt = prompts.get(fu_type)
        if not prompt:
            await query.answer()
            return

        cfg = await get_ai_config()
        if not cfg['enabled']:
            await query.answer(cfg.get('disabled_message') or DEFAULT_DISABLED_MSG, show_alert=True)
            return
        if await db.ai_is_banned(uid):
            await query.answer(AI_BANNED_MSG, show_alert=True)
            return
        if not await ai_claim_inflight(uid):
            await query.answer("⏳ صبر کن جوابِ قبلی آماده بشه.", show_alert=True)
            return
        try:
            allowed, used, limit = await check_and_consume_quota(uid)
            if not allowed:
                await query.answer(f"⛔️ سقفِ روزانه تموم شده ({used}/{limit}).", show_alert=True)
                return

            await query.answer()
            history = await _get_history(uid)
            await _answer_with_live_edit(
                update, context, ask_ai_stream(text=prompt, history=history, uid=uid),
                _footer(limit, used), uid, prompt,
            )
        finally:
            await ai_release_inflight(uid)
        return

    if action == 'report':
        key  = f"{parts[2]}:{parts[3]}" if len(parts) > 3 else ''
        info = _report_cache.get(key)
        if not info:
            await query.answer("⚠️ این پیام قدیمیه و دیگه قابل گزارش نیست.", show_alert=True)
            return
        # ⚠️ فیکس: قبلاً گزارش‌ها فقط توی RAM بودن و با ری‌استارتِ ربات از
        # بین می‌رفتن. حالا در کنار پیامِ فوری به ادمین، توی دیتابیس هم
        # ثبت می‌شه تا از پنل ادمین («📋 گزارش‌های اخیر») همیشه قابل مرور باشه.
        try:
            await db.ai_log_report(info['uid'], info['name'], info['question'], info['answer'])
        except Exception:
            logger.exception("ثبت گزارش هوشیار در دیتابیس ناموفق بود")
        if ADMIN_ID:
            try:
                await context.bot.send_message(
                    ADMIN_ID,
                    "🚩 <b>گزارش پاسخ نامناسب هوشیار</b>\n\n"
                    f"👤 کاربر: {_esc(str(info['name']))} (<code>{info['uid']}</code>)\n\n"
                    f"❓ سوال:\n{_esc(info['question'][:800])}\n\n"
                    f"🤖 پاسخ:\n{_esc(info['answer'][:1500])}",
                    parse_mode='HTML',
                )
            except Exception:
                logger.exception("گزارش پاسخ هوشیار به ادمین ارسال نشد")
        await query.answer("✅ گزارش شد، ممنون از دقتت 🙏", show_alert=True)
        return

    await query.answer()

# ══════════════════════════════════════════════════
#  📅 اسکن برنامه با هوشیار — الگوی هفتگی و امتحان
#  ورودی: عکس جدول (vision) → JSON ساختاریافته
#  هیچ‌چیز هاردکد نیست: از همین vault/provider فعلی استفاده می‌کند
# ══════════════════════════════════════════════════

# توجه: برای schedule_scan provider باید vision True باشد؛ در غیر این صورت fallback به Gemini/OpenRouter vision-free model

WEEKLY_SCHEDULE_SCHEMA = {
    'type': 'object',
    'properties': {
        'slots': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'weekday': {'type': 'integer', 'description': '0=شنبه ... 6=جمعه'},
                    'time': {'type': 'string', 'description': 'HH:MM شروع مثل 08:00'},
                    'end_time': {'type': 'string', 'description': 'HH:MM پایان مثل 10:00 — برای بازه 8-10'},
                    'lesson': {'type': 'string', 'description': 'نام درس کامل فارسی'},
                    'teacher': {'type': 'string', 'description': 'نام استاد اگر دیده شد'},
                    'location': {'type': 'string', 'description': 'مکان/کلاس'},
                    'group': {'type': 'string', 'description': '1 یا 2 یا هر دو'},
                    'flex_type': {'type': 'string', 'description': 'fixed یا flexible'},
                    'notes': {'type': 'string', 'description': 'توضیح کوتاه اختیاری'},
                },
                'required': ['weekday', 'time', 'lesson'],
            },
        }
    },
    'required': ['slots'],
}

EXAM_SCHEDULE_SCHEMA = {
    'type': 'object',
    'properties': {
        'exams': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'date': {'type': 'string', 'description': 'تاریخ شمسی YYYY/MM/DD — دقیقاً همان که در عکس است'},
                    'time': {'type': 'string', 'description': 'ساعت HH:MM یا بازه مثل 10:00'},
                    'lesson': {'type': 'string', 'description': 'نام درس'},
                    'location': {'type': 'string'},
                    'group': {'type': 'string', 'description': 'گروه اگر مشخص است'},
                },
                'required': ['date', 'lesson'],
            }
        }
    },
    'required': ['exams'],
}

def _pick_vision_config(cfg: dict) -> tuple:
    """Choose vision-capable provider/model/key from current config, with fallback."""
    vault = cfg.get('vault') or {}
    provider = cfg.get('provider') or 'gemini'
    model = cfg.get('model') or ''
    key = cfg.get('api_key') or ''
    meta = PROVIDERS.get(provider) or {}
    if meta.get('vision') and key and not key.strip() == '':
        return provider, model, key
    # fallback: try gemini vault
    if vault.get('gemini') and PROVIDERS['gemini']['vision']:
        return 'gemini', DEFAULT_MODELS['gemini'], vault['gemini']
    # fallback: any vision provider with key
    for pid in ('openrouter', 'nvidia', 'together', 'huggingface'):
        if PROVIDERS.get(pid, {}).get('vision') and vault.get(pid):
            m = DEFAULT_MODELS.get(pid) or MODEL_CATALOG.get(pid, [(None, '', True)])[0][0]
            # for openrouter use vision model
            if pid == 'openrouter':
                m = 'qwen/qwen2.5-vl-32b-instruct:free'
            return pid, m, vault[pid]
    # last resort: current even if non-vision (will error clearly)
    return provider, model, key

WEEKLY_SYSTEM = (
    "تو یک دستیار استخراج برنامه کلاسی دانشگاه پزشکی هستی. از روی عکس جدول هفتگی (شنبه تا جمعه، ستون‌ها روز، سطرها ساعت 8-10/10-12/13-15/15-17/17-19) تمام درس‌ها را استخراج کن.\n"
    "قواعد:\n"
    "• weekday: شنبه=0، یکشنبه=1، دوشنبه=2، سه‌شنبه=3، چهارشنبه=4، پنج‌شنبه=5، جمعه=6\n"
    "• time/end_time: بازه کامل را استخراج کن — ابتدا و انتها هر دو HH:MM (مثلاً بازه 8-10 → time=08:00 و end_time=10:00، 10-12→10:00/12:00، 13-15→13:00/15:00، 15-17→15:00/17:00، 17-19→17:00/19:00). هر slot باید نمایانگر یک کلاس ۲ساعته واحد باشد، نه دو slot مجزا.\n"
    "• اگر یک خانه دو درس موازی دارد (مثلاً 'آیین زندگی (دخترا) / عملی (پسرا)' یا 'آز بیوشیمی / بیوشیمی') هر دو را به‌صورت دو slot جداگانه با همان weekday/time/end_time تولید کن.\n"
    "• group: اگر جدول برای گروه 1 یا 2 جداست همان را بگذار؛ اگر ستون 'هر دو' یا نامشخص است 'هر دو'.\n"
    "• flex_type: درس‌های عملی/آز/آزمایشگاه → flexible، بقیه fixed.\n"
    "• فقط JSON مطابق schema برگردان، بدون توضیح اضافه."
)

EXAM_SYSTEM = (
    "تو یک دستیار استخراج برنامه امتحانی هستی. از روی عکس جدول امتحانات، تمام ردیف‌ها را استخراج کن.\n"
    "• date: تاریخ شمسی دقیقاً همان که در عکس دیده می‌شود به شکل YYYY/MM/DD (اعداد انگلیسی، مثل 1405/10/26). اگر تاریخ میلادی دیدی همان را حفظ کن.\n"
    "• time: ساعت شروع امتحان به HH:MM (مثلاً '10-12'→10:00، '08:00'→08:00). اگر بازه بود ابتدای بازه.\n"
    "• lesson: نام کامل درس فارسی.\n"
    "• فقط JSON مطابق schema برگردان."
)

async def _vision_json_gemini(api_key: str, model: str, system_prompt: str, user_prompt: str, image_bytes: bytes, image_mime: str, schema: dict) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {'Content-Type': 'application/json', 'x-goog-api-key': api_key}
    payload = {
        'system_instruction': {'parts': [{'text': system_prompt}]},
        'contents': [{'role': 'user', 'parts': [
            {'inline_data': {'mime_type': image_mime or 'image/jpeg', 'data': base64.b64encode(image_bytes).decode('utf-8')}},
            {'text': user_prompt},
        ]}],
        'generationConfig': _no_thinking({
            'responseMimeType': 'application/json',
            'responseSchema': schema,
            'maxOutputTokens': 4096,
        }),
    }
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(url, headers=headers, json=payload)
    if resp.status_code != 200:
        _raise_gemini_status_error(resp.status_code)
    data = resp.json()
    raw = _extract_gemini_text(data, "برنامه")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # fallback: extract first {...}
        m = re.search(r'\{.*\}', raw, flags=re.S)
        if m:
            return json.loads(m.group(0))
        raise AIConfigError("هوشیار خروجی قابل فهم برنگرداند — دوباره با عکس واضح‌تر امتحان کن.")

async def _vision_json_openai(api_key: str, model: str, system_prompt: str, user_prompt: str, image_bytes: bytes, image_mime: str, provider: str) -> dict:
    meta = PROVIDERS.get(provider) or {}
    base = meta.get('url') or PROVIDERS['openrouter']['url']
    url = f"{base}/chat/completions"
    headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
    if provider == 'openrouter':
        headers['HTTP-Referer'] = 'https://humsyar.local'
        headers['X-Title'] = 'Humsyar'
    b64 = base64.b64encode(image_bytes).decode('utf-8')
    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': [
            {'type': 'text', 'text': user_prompt},
            {'type': 'image_url', 'image_url': {'url': f'data:{image_mime or "image/jpeg"};base64,{b64}'}},
        ]},
    ]
    payload = {
        'model': model,
        'messages': messages,
        'temperature': 0.1,
        'max_tokens': 4096,
    }
    # ask for JSON
    if provider in ('openrouter', 'together'):
        payload['response_format'] = {'type': 'json_object'}
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(url, headers=headers, json=payload)
    if resp.status_code == 429:
        raise AIQuotaError("سقف API پر شد — کمی بعد دوباره امتحان کن.")
    if resp.status_code >= 400:
        raise AIConfigError(f"خطای سرویس هوشیار ({resp.status_code}) — تنظیمات را بررسی کن.")
    data = resp.json()
    try:
        txt = data['choices'][0]['message']['content']
    except Exception:
        raise AIConfigError("پاسخ هوشیار خوانده نشد.")
    txt = txt.strip()
    # strip markdown fences
    if txt.startswith('```'):
        txt = re.sub(r'^```(?:json)?\s*', '', txt)
        txt = re.sub(r'\s*```$', '', txt)
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        m = re.search(r'\{.*\}', txt, flags=re.S)
        if m:
            return json.loads(m.group(0))
        raise AIConfigError("هوشیار JSON معتبر برنگرداند.")

async def scan_schedule_image(image_bytes: bytes, image_mime: str = 'image/jpeg', kind: str = 'weekly', group_hint: str = None, extra_note: str = None) -> dict:
    """Single entry for image scan — kind: weekly|exam. Returns parsed JSON."""
    if not image_bytes or len(image_bytes) < 100:
        raise AIError("عکس نامعتبر یا خیلی کوچک است.")
    if len(image_bytes) > 12 * 1024 * 1024:
        raise AIError("حجم عکس بیش از حد زیاد است — نسخه کم‌حجم‌تر بفرست.")
    cfg = await get_ai_config()
    if not cfg.get('enabled'):
        raise AIConfigError("بخش هوشیار غیرفعال است.")
    provider, model, key = _pick_vision_config(cfg)
    if not key:
        raise AIConfigError("کلید API vision تنظیم نشده — از پنل هوشیار یک کلید Gemini/OpenRouter وارد کن.")
    if kind == 'exam':
        system = EXAM_SYSTEM
        schema = EXAM_SCHEDULE_SCHEMA
        prompt = "این عکس جدول امتحانات است. تمام ردیف‌ها را استخراج کن و فقط JSON برگردان."
        if extra_note:
            prompt += f"\nنکته: {extra_note}"
    else:
        system = WEEKLY_SYSTEM
        schema = WEEKLY_SCHEDULE_SCHEMA
        prompt = "این عکس جدول برنامه هفتگی کلاسی است. تمام خانه‌های پر را استخراج کن و فقط JSON برگردان."
        if group_hint and group_hint.strip() not in ('', 'هر دو'):
            prompt += f"\nاین جدول مربوط به گروه {group_hint} است؛ اگر گروه در عکس مشخص نبود همین را بگذار."
        if extra_note:
            prompt += f"\nنکته: {extra_note}"
    # choose path
    if provider == 'gemini':
        return await _vision_json_gemini(key, model, system, prompt, image_bytes, image_mime, schema)
    else:
        # openai-compatible vision
        return await _vision_json_openai(key, model, system, prompt, image_bytes, image_mime, provider)

async def scan_weekly_schedule_image(image_bytes: bytes, image_mime: str = 'image/jpeg', group_hint: str = None) -> dict:
    data = await scan_schedule_image(image_bytes, image_mime, kind='weekly', group_hint=group_hint)
    # normalize — interval-aware + 12h → 24h fix
    slots = data.get('slots') or []
    norm = []
    # helper: 01:00-05:00 → 13:00-17:00 (دانشگاه بعدازظهر)
    def _fix_pm(hhmm: str) -> str:
        try:
            if not hhmm:
                return hhmm
            hh, mm = hhmm.split(':')
            h = int(hh)
            if 1 <= h <= 5:
                return f"{h+12:02d}:{mm}"
            return hhmm
        except Exception:
            return hhmm
    SYNTH_END = {"08:00":"10:00","10:00":"12:00","13:00":"15:00","15:00":"17:00","17:00":"19:00"}
    for s in slots:
        try:
            wd = int(s.get('weekday'))
            if not 0 <= wd <= 6:
                continue
            t = str(s.get('time') or '').strip()
            et = str(s.get('end_time') or s.get('time_end') or '').strip()
            # legacy: time may contain range "08:00-10:00" or "08:00 تا 10:00"
            if t and ("-" in t or "تا" in t) and not et:
                from time_utils import en_digits as _en
                tmp = _en(t).replace('—','-').replace('–','-').replace('تا','-')
                times = re.findall(r'(\d{1,2}:\d{2})', tmp)
                if len(times) >=2:
                    t = f"{int(times[0].split(':')[0]):02d}:{times[0].split(':')[1]}"
                    et = f"{int(times[1].split(':')[0]):02d}:{times[1].split(':')[1]}"
            # ensure HH:MM
            for val in (t, et):
                pass
            if not re.match(r'^\d{2}:\d{2}$', t):
                if re.match(r'^\d{1,2}:\d{2}$', t):
                    hh, mm = t.split(':')
                    t = f"{int(hh):02d}:{mm}"
                else:
                    continue
            # normalize end_time
            if et:
                if not re.match(r'^\d{2}:\d{2}$', et):
                    if re.match(r'^\d{1,2}:\d{2}$', et):
                        hh, mm = et.split(':')
                        et = f"{int(hh):02d}:{mm}"
                    else:
                        et = ""
            t = _fix_pm(t)
            if et:
                et = _fix_pm(et)
            # validate times
            from time_utils import parse_clock_time as _pct
            try:
                _pct(t)
                if et:
                    _pct(et)
                    if int(et.split(':')[0])*60+int(et.split(':')[1]) <= int(t.split(':')[0])*60+int(t.split(':')[1]):
                        et = SYNTH_END.get(t, "")
            except Exception:
                continue
            if not et:
                et = SYNTH_END.get(t, "")
            lesson = str(s.get('lesson') or '').strip()
            if not lesson:
                continue
            g = str(s.get('group') or group_hint or 'هر دو').strip() or 'هر دو'
            from database import db as _db
            g = _db.normalize_group(g) or 'هر دو'
            if g not in ('1','2','هر دو'):
                g = 'هر دو'
            flex = str(s.get('flex_type') or '').strip().lower()
            if flex not in ('fixed','flexible'):
                flex = 'flexible' if any(k in lesson for k in ('عملی','آز','آزمایشگاه')) else 'fixed'
            norm.append({
                'weekday': wd,
                'time': t,
                'end_time': et,
                'lesson': lesson[:120],
                'teacher': str(s.get('teacher') or '').strip()[:80],
                'location': str(s.get('location') or '').strip()[:80],
                'group': g,
                'type': 'class',
                'flex_type': flex,
                'notes': str(s.get('notes') or '').strip()[:200],
            })
        except Exception:
            continue
    # dedup: یک کلاس 2ساعته نباید دو ردیف شود — اگر دقیقاً (weekday,time,end_time,lesson,group) تکراری بود حذف
    seen = set()
    deduped = []
    for it in norm:
        k = (it['weekday'], it['time'], it['end_time'], it['lesson'], it['group'])
        if k in seen:
            continue
        seen.add(k)
        deduped.append(it)
    return {'slots': deduped}

async def scan_exam_schedule_image(image_bytes: bytes, image_mime: str = 'image/jpeg') -> dict:
    data = await scan_schedule_image(image_bytes, image_mime, kind='exam')
    exams = data.get('exams') or []
    norm = []
    for e in exams:
        try:
            lesson = str(e.get('lesson') or '').strip()
            if not lesson:
                continue
            raw_date = str(e.get('date') or '').strip()
            if not raw_date:
                continue
            # normalize digits and slashes
            from time_utils import en_digits
            raw_date = en_digits(raw_date).replace('-', '/').strip()
            # ensure YYYY/MM/DD
            parts = re.split(r'[/\s]+', raw_date)
            if len(parts) >= 3:
                y, m, d = parts[0], parts[1], parts[2]
                raw_date = f"{int(y):04d}/{int(m):02d}/{int(d):02d}"
            t = str(e.get('time') or '08:00').strip()
            t = en_digits(t)
            # extract HH:MM from possibly "10-12" or "۱۰:۰۰"
            m = re.search(r'(\d{1,2}):(\d{2})', t)
            if m:
                t = f"{int(m.group(1)):02d}:{m.group(2)}"
            elif re.search(r'(\d{1,2})\s*-\s*(\d{1,2})', t):
                hh = int(re.search(r'(\d{1,2})', t).group(1))
                t = f"{hh:02d}:00"
            else:
                t = '08:00'
            g = str(e.get('group') or 'هر دو').strip() or 'هر دو'
            from database import db as _db
            g = _db.normalize_group(g) or 'هر دو'
            norm.append({
                'date': raw_date,
                'time': t,
                'lesson': lesson[:120],
                'teacher': '',
                'location': str(e.get('location') or '').strip()[:80],
                'group': g,
                'type': 'exam',
            })
        except Exception:
            continue
    return {'exams': norm}

