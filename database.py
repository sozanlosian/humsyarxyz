"""
🗄️ Database — نسخه نهایی کامل
  ✅ MONGODB_URI اجباری
  ✅ ensure_indexes برای سرعت
  ✅ مدیریت ورودی‌های دانشجویی (intakes) داخل class
  ✅ weekly_activity، get_leaderboard، search_resources
  ✅ فیکس: متدهای intakes داخل class DB
"""
import os
import logging
import asyncio
import difflib
from datetime import datetime, timedelta
from bson import ObjectId
import motor.motor_asyncio

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# 🌊 موج Q2/W12 — Facade ماژولار: بدنه‌ی DB به mixinهای db/* منتقل شد.
# «from database import db / DB» و تمام attributeها/متدها عیناً کار می‌کنند.
from db import DBCore, DBContent, DBRbac, DBPrestige, DBFinance, DBRing, DBWallet, DBReferral


class DB(DBCore, DBContent, DBRbac, DBPrestige, DBFinance, DBRing, DBWallet, DBReferral):
    """لایه‌ی دسترسی به داده — ترکیب mixinهای core/content/rbac/prestige/finance.
    رفتار و امضای عمومی بدون تغییر (موج Q2/W12)."""
    pass


db = DB()
