# -*- coding: utf-8 -*-
"""
🔐 W1 — At-rest encryption for secrets (AI keys etc.)
- Fernet (AES-128-CBC + HMAC) via `cryptography` if available
- Falls back to plaintext with warning if FERNET_KEY missing/invalid — never crashes boot
- Key: 32 url-safe base64 bytes (Fernet.generate_key()). Set via env FERNET_KEY.

Stored shape in bot_settings:
    {"enc": true, "v": 1, "c": "<fernet token>"}  OR  plaintext legacy (backward compat)

Callers should use encrypt_value / decrypt_value / get_secret / set_secret helpers.
"""
import os
import base64
import logging

logger = logging.getLogger(__name__)

_FERNET_KEY = (os.getenv("FERNET_KEY") or os.getenv("AI_ENC_KEY") or "").strip()

_fernet = None
if _FERNET_KEY:
    try:
        from cryptography.fernet import Fernet, InvalidToken
        # Validate key is 32 url-safe b64
        # Fernet will validate itself; we just try to create
        _fernet = Fernet(_FERNET_KEY.encode() if isinstance(_FERNET_KEY, str) else _FERNET_KEY)
        logger.info("🔐 Fernet encryption enabled (FERNET_KEY present)")
    except Exception as e:
        logger.warning(f"⚠️ FERNET_KEY invalid, encryption disabled: {e}")
        _fernet = None
else:
    logger.info("ℹ️ FERNET_KEY not set — secrets stored plaintext (set FERNET_KEY to enable at-rest encryption)")

def is_encryption_enabled() -> bool:
    return _fernet is not None

def encrypt_value(plaintext: str) -> dict:
    """Encrypt string → dict to store in DB. If disabled, returns plaintext wrapper."""
    if not plaintext:
        return {"enc": False, "v": 1, "c": plaintext or ""}
    if _fernet is None:
        return {"enc": False, "v": 1, "c": plaintext}
    try:
        tok = _fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")
        return {"enc": True, "v": 1, "c": tok}
    except Exception as e:
        logger.warning(f"encrypt failed, storing plaintext: {e}")
        return {"enc": False, "v": 1, "c": plaintext}

def decrypt_value(stored) -> str:
    """Decrypt DB value → plaintext. Handles legacy plaintext, dict, or None."""
    if stored is None:
        return ""
    if isinstance(stored, str):
        # legacy plaintext
        if stored.startswith("gAAAAA"):  # looks like Fernet token stored as bare string (legacy)
            if _fernet is not None:
                try:
                    from cryptography.fernet import InvalidToken
                    return _fernet.decrypt(stored.encode("utf-8")).decode("utf-8")
                except Exception:
                    return stored
        return stored
    if isinstance(stored, dict):
        c = stored.get("c", "")
        enc = stored.get("enc")
        if not enc:
            return c or ""
        if _fernet is None:
            logger.warning("⚠️ Encrypted value encountered but FERNET_KEY missing — cannot decrypt")
            return ""  # fail closed: don't leak token, but don't crash
        try:
            return _fernet.decrypt(c.encode("utf-8")).decode("utf-8")
        except Exception as e:
            logger.warning(f"decrypt failed: {e}")
            return ""
    return str(stored)

def encrypt_bytes(raw: bytes) -> bytes | None:
    """🌊 W5/REL-04 — رمزنگاری بایت‌ها (بکاپ)؛ None اگر خاموش/ناموفق."""
    if _fernet is None or not raw:
        return None
    try:
        return _fernet.encrypt(bytes(raw))
    except Exception as e:
        logger.warning(f"encrypt_bytes failed: {e}")
        return None


def decrypt_bytes(token: bytes) -> bytes | None:
    """🌊 W5/REL-04 — رمزگشایی بایت‌ها؛ None اگر خاموش/ناموفق (fail-closed)."""
    if _fernet is None or not token:
        return None
    try:
        return _fernet.decrypt(bytes(token))
    except Exception as e:
        logger.warning(f"decrypt_bytes failed: {e}")
        return None


def mask_secret(val: str, keep: int = 4) -> str:
    if not val: return "—"
    if len(val) <= keep*2: return "•"*8
    return val[:keep] + "•"*(len(val)-keep*2) + val[-keep:]
