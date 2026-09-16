# -*- coding: utf-8 -*-
"""
📄 هسته — قرارداد صفحه‌بندی واحد

قبل: Bot با `skip/limit`، WebAdmin با `page/per_page`، MiniApp با `after` cursor
  — هرکدام قرارداد جدا و اسکن بی‌پایان ممکن.

بعد: Cursor واحد (after_id + limit) + Page wrapper. همه APIها همین را برمی‌گردانند.
"""
from dataclasses import dataclass
from typing import Optional, List, Any

@dataclass
class Cursor:
    after: Optional[str] = None
    limit: int = 20

@dataclass
class Page:
    items: List[Any]
    next_cursor: Optional[str]  # برای درخواست بعدی ?after=
    total: Optional[int] = None
    has_more: bool = False
