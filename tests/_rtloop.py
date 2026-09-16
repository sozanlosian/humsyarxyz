# -*- coding: utf-8 -*-
"""🌊 loop مشترک برای تست‌های runtime.

کلاینت Motor به اولین event loopی که روی آن I/O کند گره می‌خورد؛ اگر کلاس
دومِ runtime loop خودش را بسازد (یا اولی loop مشترک را ببندد) همه‌ی عملیات‌ها
RuntimeError می‌گیرند. پس همه‌ی کلاس‌های runtime از همین یک loop استفاده
می‌کنند و هیچ‌کدام آن را در میانه‌ی session نمی‌بندند.
"""
import asyncio

LOOP = asyncio.new_event_loop()


def adopt() -> None:
    """LOOP را به‌عنوان event loop جاری thread ثبت می‌کند."""
    asyncio.set_event_loop(LOOP)


def run(coro):
    return LOOP.run_until_complete(coro)
