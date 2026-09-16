# -*- coding: utf-8 -*-
"""🌊 W5/REL-03 — شمارنده‌های درون‌حافظه‌ای همه‌ی /api/* (leaf: بدون هیچ
واردات اپی؛ middleware می‌نویسد، observability می‌خواند).

- ارزان (dict + حلقه‌ی ۳۰تایی) و بدون write-amplification روی Mongo.
- با ری‌استارت صفر می‌شود (موقتی‌بودن در پاسخ اعلام می‌شود)؛
  wa_api_metrics همچنان منبع ماندگار وب‌ادمین است.
"""
from collections import deque

_counters: dict = {}
_recent_5xx: deque = deque(maxlen=30)


def record(method: str, route: str, status: int, request_id: str = "") -> None:
    """ثبت یک درخواست — هرگز exception بیرون نمی‌دهد."""
    try:
        cls = f"{int(status) // 100}xx"
    except Exception:
        cls = "?"
    try:
        key = (str(method or "?")[:8], str(route or "?")[:180], cls)
        _counters[key] = _counters.get(key, 0) + 1
        if cls == "5xx":
            _recent_5xx.appendleft({
                "route": key[1], "method": key[0],
                "status": int(status), "request_id": request_id or "",
            })
    except Exception:
        pass


def snapshot(limit_routes: int = 50) -> dict:
    """نمای تجمیعی برای observability (additive؛ قرارداد قبلی دست‌نخورده)."""
    rows: dict = {}
    try:
        for (method, route, cls), n in _counters.items():
            r = rows.setdefault(route, {"route": route, "requests": 0,
                                        "by_class": {}})
            r["requests"] += n
            r["by_class"][cls] = r["by_class"].get(cls, 0) + n
        out = sorted(rows.values(), key=lambda r: -r["requests"])[:limit_routes]
        return {"routes": out, "recent_5xx": list(_recent_5xx),
                "total": sum(_counters.values()), "ephemeral": True}
    except Exception:
        return {"routes": [], "recent_5xx": [], "total": 0,
                "ephemeral": True}
