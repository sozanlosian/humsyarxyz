"""🛡 AUDIT-§۷۵ — مرزِ پاسخ: سندِ خام MongoDB → داده‌ی JSON-پایدار.

ریشه‌ی ایراد (تولید، ۵۰۰ روی `/api/ring/reports`)
────────────────────────────────────────────────
هر هندلری که خروجیِ `find()/find_one()` را بی‌واسطه return کند، شیء
`bson.ObjectIdِ` فیلد `_id` را هم با می‌برد. FastAPI در مرحله‌ی
سریال‌سازی (`jsonable_encoder`) برای شیءِ ناشناخته اول `dict(obj)` و
سپس شاخه‌ی *iterable* را امتحان می‌کند؛ `ObjectId` قابل پیمایش نیست ⇒

    TypeError: 'ObjectId' object is not iterable

و چون این خطا **بعد** از بدنه‌ی هندلر و بعد از effectها (نوشتن/لاگ)
می‌افتد، کلاینت ۵۰۰ می‌بیند در حالی‌که عملیات انجام شده است. بدترین
بخشِ همین الگو: تا وقتی مجموعه خالی است پاسخ ۲۰۰ برمی‌گردد — پس تستِ
بدون‌داده هرگز آن را نمی‌گیرد و فقط رکوردِ واقعی پرچم را بالا می‌آورد.

قرارداد
───────
هر endpoint که مستندِ ذخیره‌شده را به پنل/مینی‌اپ می‌دهد باید از
`doc()` / `docs()` (یا `payload()` برای کل بدنه) استفاده کند. این ماژول
عمداً هیچ فیلدی را حذف یا تغییر نام نمی‌دهد تا مصرف‌کننده‌ی موجود نشکند؛
فقط نوع را به JSON-پایدار تبدیل می‌کند (ObjectId → str). درِ `NaN`/
`Infinity` هم بسته می‌شود، وگرنه همان ۵۰۰ با خطای دیگر برمی‌گردد
(Starlette با `allow_nan=False` سریال‌سازی می‌کند).
"""
from __future__ import annotations

import math
import uuid
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

from bson import (DBRef, Decimal128, Int64, MaxKey, MinKey, ObjectId, Regex, Timestamp)
from bson.binary import Binary
from bson.code import Code

# سقف‌های محافظ: سندِ بدشکل (حلقه‌ی مرجع یا آرایه‌ی غول‌پیکر) نباید
# پاسخ را به بمب CPU/حافظه تبدیل کند.
_MAX_DEPTH = 12
_MAX_ITEMS = 5000
_MAX_STR = 20000

_SCALAR_TYPES = (str, bool, int, float, bytes, bytearray, type(None))
_BSON_TYPES = (ObjectId, DBRef, Binary, Regex, Code, Timestamp, MinKey, MaxKey, uuid.UUID)


def _float(v: float) -> float | None:
    """عددِ شناور را JSON-پایدار می‌کند: NaN/Inf ⇒ None."""
    return v if math.isfinite(v) else None


def _scalar(value: Any) -> Any:
    """تبدیل یک مقدارِ غیر JSON به نزدیک‌ترین معادلِ پایدار."""
    if value is None:
        # باید اول از همه بیاید وگرنه `str(None)` رشته‌ی "None" می‌سازد و
        # فیلدِ تهی در پنل به متن تبدیل می‌شود (تستِ همین‌جا گرفتش).
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):                 # Int64 هم اینجا می‌افتد
        return int(value)
    if isinstance(value, float):
        return _float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, (Decimal, Decimal128)):
        # Decimal128 با `float()` مستقیم ساخته نمی‌شود ⇒ اول به Decimal (همان
        # مسیری که خودِ FastAPI برای Decimal می‌رود: عدد، نه رشته).
        try:
            dec = value.to_decimal() if isinstance(value, Decimal128) else value
            return _float(float(dec))
        except (ArithmeticError, ValueError, TypeError):
            return str(value)
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", "replace")
    if isinstance(value, _BSON_TYPES):
        return str(value)
    if isinstance(value, Enum):
        return to_jsonable(value.value)
    return str(value)


def to_jsonable(value: Any, _depth: int = 0) -> Any:
    """بازگشتی: هر ساختارِ پایتون/Mongo را به چیزی می‌رساند که JSON می‌پذیرد.

    - `dict`/`Mapping` → dict با کلیدِ رشته‌ای (مقدار `_id` → str)
    - list/tuple/set/frozenset → list با سقف `_MAX_ITEMS`
    - `datetime/date/time` → `isoformat`، `bytes` → متن، `NaN/Inf` → None
    - هر چیزِ ناشناخته → `str(value)`؛ هیچ شیءِ خام به FastAPI نمی‌رسد.
    """
    if isinstance(value, _SCALAR_TYPES):
        out = _scalar(value)
        if isinstance(out, str) and len(out) > _MAX_STR:
            return out[:_MAX_STR]
        return out
    if _depth >= _MAX_DEPTH:
        return str(value)[:500]
    if isinstance(value, Mapping):
        out = {}
        for k, v in value.items():
            out[k if isinstance(k, str) else str(k)] = to_jsonable(v, _depth + 1)
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(v, _depth + 1) for v in list(value)[:_MAX_ITEMS]]
    return _scalar(value)


def doc(document: Any) -> Any:
    """یک سند (یا None) را برای پاسخ آماده می‌کند."""
    if document is None:
        return None
    if isinstance(document, Mapping):
        return to_jsonable(dict(document))
    return to_jsonable(document)


def docs(documents: Any) -> list:
    """فهرستِ اسناد را برای پاسخ آماده می‌کند (None/غیرlist بی‌خطر است)."""
    if not documents:
        return []
    if not isinstance(documents, (list, tuple)):
        documents = list(documents)
    return [to_jsonable(dict(d) if isinstance(d, Mapping) else d) for d in documents]


def payload(data: Any) -> Any:
    """کل بدنه‌ی پاسخ را می‌شوید؛ برای هندلرهایی که dictِ ترکیبی می‌سازند."""
    return to_jsonable(data)


__all__ = ["to_jsonable", "doc", "docs", "payload"]
