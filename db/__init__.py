# -*- coding: utf-8 -*-
"""
🗄️ HUMSYAR DB layer — 🌊 موج Q2/W12: ماژولارسازی database.py
این ماژول بخشی از mixinهای کلاس DB است؛ facade در database.py بدون تغییر
رفتار، همه‌ی importهای قبلی را سالم نگه می‌دارد.
"""
import os
import logging
import asyncio
import difflib
from datetime import datetime, timedelta
from bson import ObjectId
import motor.motor_asyncio

# نام logger عمداً «database» نگه داشته شد تا کانال لاگ تغییر نکند
logger = logging.getLogger('database')


from .core import DBCore
from .content import DBContent
from .rbac import DBRbac
from .prestige import DBPrestige
from .finance import DBFinance
from .ring import DBRing
from .wallet import DBWallet, WalletError, WALLET_CURRENCY
from .referral import DBReferral

__all__ = ['DBCore', 'DBContent', 'DBRbac', 'DBPrestige', 'DBFinance', 'DBRing',
           'DBWallet', 'WalletError', 'WALLET_CURRENCY', 'DBReferral']
