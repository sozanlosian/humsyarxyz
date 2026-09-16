# -*- coding: utf-8 -*-
"""
⚙️ هسته — تنظیمات تایپ‌شده (به‌جای get_setting("string_key") پراکنده)

هر کلید یک property تایپ‌دار است؛ مقدار پیش‌فرض و ولیدیشن یک‌جا است.
Bot و API و WebAdmin از همین کلاس می‌خوانند — typo غیرممکن.
"""
from database import db

class Settings:
    # کیف پول — ضداسپم
    @staticmethod
    async def wallet_alert_enabled() -> bool:
        v = await db.get_setting("wallet_alert_enabled", None)
        return True if v is None else bool(v)

    @staticmethod
    async def wallet_alert_cooldown_hours() -> int:
        v = await db.get_setting("wallet_alert_cooldown_hours", None)
        return 6 if v is None else int(v)

    @staticmethod
    async def wallet_alert_muted_until():
        return await db.get_setting("wallet_alert_muted_until", None)

    # زرین‌پال
    @staticmethod
    async def zarinpal() -> dict:
        return {
            "merchant_id": await db.get_setting("zarinpal_merchant_id", None),
            "sandbox": bool(await db.get_setting("zarinpal_sandbox", False)),
            "callback_url": await db.get_setting("zarinpal_callback_url", None),
            "enabled": await db.get_setting("zarinpal_enabled", None),
        }

    # بکاپ خودکار
    @staticmethod
    async def auto_backup_enabled() -> bool:
        return bool(await db.get_setting("auto_backup_enabled", False))

    # ... می‌توان بقیه کلیدها را همین‌جا تایپ‌دار کرد بدون تغییر DB
