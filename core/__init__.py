# -*- coding: utf-8 -*-
"""
🧠 HumsyarCore — هسته واحد هامشیار (W8)

چرا هسته؟
  قبل از W8، هر لایه (Bot / MiniApp / WebAdmin) منطق خودش را برای
  «آیا کاربر حق دیدن دارد؟» ، «اشتراک فعال است؟»، «کدام ورودی؟» و
  «چه خطایی برگردانیم؟» داشت. نتیجه: ۳ پیاده‌سازی موازی که با هر
  تغییر، یکی عقب می‌ماند → IDOR، paywall ناسازگار، validate دوگانه.

هسته یک بسته thin-wrapper است که **همان** متدهای موجود DB را با
  قرارداد واحد و کد خطای ماشین‌خوان صادر می‌کند. Bot و API و MiniApp
  (از طریق API) از همین هسته می‌خوانند — هیچ منطق کسب‌وکاری در هسته
  تکرار نمی‌شود، فقط قرارداد.

  import از هسته:
    from core.access import has_access, require_access, AccessResult
    from core.rbac import has_permission, get_user_perms, require_perm
    from core.content_scope import get_content_scope, is_content_admin
    from core.settings import Settings
    from core.errors import Code
    from core.pagination import Cursor, Page
"""
from . import access, rbac, content_scope, settings, errors, pagination, audit
__all__ = ["access", "rbac", "content_scope", "settings", "errors", "pagination", "audit"]
