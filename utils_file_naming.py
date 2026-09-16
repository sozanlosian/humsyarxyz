# -*- coding: utf-8 -*-
"""
📄 Humsyar File Naming — Production-ready filename branding pipeline

Implements Steps 4-14 of the rename specification:
- Extension preservation
- Smart extension handling when user supplies one
- Sanitization (allow Persian, block dangerous chars)
- Truncation (UTF-8 safe)
- Duplicate handling
- Full format support (generic, not hard-coded to PDF)

Does NOT touch actual file bytes — only string logic. Storage/re-upload
lives in telegram_send / content_admin.
"""

import re
import unicodedata

# ──────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────

# Max filename length including extension and dot, per spec §14
# 255 is filesystem limit; we leave margin for extension safety
MAX_FILENAME_LEN = 200

# Characters that must be stripped on any OS/storage (Windows + POSIX + S3 keys)
FORBIDDEN_RE = re.compile(r'[/\\:*?"<>|\x00-\x1f]')

# Also normalize control chars and strip leading/trailing dots/spaces
TRIM_CHARS = ' .'

# Allowed to keep: Persian, Arabic, Latin, digits, space, -, _, (, ), [, ], ., +, etc
# We DONT whitelist strictly — we blacklist only dangerous ones (§13).
# So فارسی، فاصله، پرانتز، خط تیره، underscore مجاز می‌مونن.

# ──────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────

def get_extension(filename: str) -> str:
    """
    Extract extension without dot, lowercase.
    'archive.tar.gz' -> 'gz' (simple, not compound)
    'photo' -> ''
    '.hidden' -> ''
    """
    name = (filename or '').strip()
    if not name or '.' not in name:
        return ''
    # last dot, not first char
    idx = name.rfind('.')
    if idx <= 0 or idx == len(name) - 1:
        return ''
    ext = name[idx + 1:].strip().lower()
    # sanitize ext: only alnum
    ext = re.sub(r'[^a-z0-9]', '', ext)
    return ext[:10]  # safety cap


def strip_extension(filename: str) -> str:
    """Remove extension, return base."""
    ext = get_extension(filename)
    if not ext:
        return (filename or '').strip()
    # remove last .ext
    idx = (filename or '').rfind('.')
    return filename[:idx].strip()


def sanitize_filename(name: str, allow_empty: bool = False) -> str:
    """
    §13 — Sanitize user input for filename base (without extension).

    - Normalize Unicode (NFC) for Persian
    - Remove forbidden chars: / \ : * ? " < > | and controls
    - Strip leading/trailing spaces and dots
    - Collapse whitespace
    - Prevent path traversal (../, ...)
    - Keep Persian, spaces, parentheses, dash, underscore
    """
    if not name:
        return '' if allow_empty else 'بدون_عنوان'
    # NFC for Persian composition (ی vs ي etc)
    name = unicodedata.normalize('NFC', str(name))
    # Remove forbidden
    name = FORBIDDEN_RE.sub('', name)
    # Remove path traversal attempts explicitly
    # e.g. "../../test" -> after forbidden removal becomes "....test" -> strip dots handles
    # Also handle encoded? Already removed slashes
    name = name.strip(TRIM_CHARS)
    # Collapse whitespace (including ZWJ? keep ZWJ for Persian)
    # Use split/join for spaces, but preserve single spaces
    name = ' '.join(name.split())
    # Still empty?
    if not name:
        return '' if allow_empty else 'بدون_عنوان'
    # Disallow names that are just dots? already stripped
    # Limit base length will be done in build, but also cap here to avoid extreme input
    if len(name) > MAX_FILENAME_LEN:
        # truncate safely without splitting grapheme? Python slice is codepoint-safe, enough
        name = name[:MAX_FILENAME_LEN].strip(TRIM_CHARS)
    return name


def build_display_filename(user_input: str, original_filename: str, fallback: str = "فایل") -> str:
    """
    §4 / §5 — Build final display filename with extension preserved.

    user_input: what admin typed (may or may not contain extension)
    original_filename: e.g. 'lecture.mp4' or 'IMG_123.jpg'
    fallback: if both empty

    Rules:
    - If user_input is empty/whitespace -> use original_filename's base or fallback
    - If original has extension ext0, final must have ext0 (never change type)
      e.g. original mp4, user 'x.pdf' -> 'x.mp4'
    - If user_input has extension ext_u == ext0 -> use user_input as-is (sanitized)
    - If user_input has different ext -> strip it, keep ext0
    - If no original ext -> use user_input ext if any, else no ext
    """
    orig_ext = get_extension(original_filename)
    orig_base = strip_extension(original_filename) if orig_ext else (original_filename or '').strip()

    user_raw = (user_input or '').strip()
    if not user_raw:
        # No custom name -> keep original or fallback
        if original_filename and original_filename.strip():
            sanitized = sanitize_filename(strip_extension(original_filename) if orig_ext else original_filename)
            return f"{sanitized}.{orig_ext}" if orig_ext else sanitized
        return sanitize_filename(fallback)

    # Detect if user_input contains an extension
    user_ext = get_extension(user_raw)
    user_base = strip_extension(user_raw) if user_ext else user_raw

    # Sanitize base
    sanitized_base = sanitize_filename(user_base)
    if not sanitized_base:
        sanitized_base = sanitize_filename(fallback)

    if orig_ext:
        # Always preserve original ext, ignore user's ext if different
        # If user_ext == orig_ext, we already stripped and will re-add same, so de-dup avoided
        return f"{sanitized_base}.{orig_ext}"
    else:
        # Original has no ext: respect user ext if provided
        if user_ext:
            # sanitize user_ext already via get_extension
            return f"{sanitized_base}.{user_ext}"
        return sanitized_base


def truncate_display_filename(display_name: str, max_len: int = MAX_FILENAME_LEN) -> str:
    """
    §14 — Truncate safely preserving extension, UTF-8 safe (codepoint slice).
    """
    if not display_name or len(display_name) <= max_len:
        return display_name
    ext = get_extension(display_name)
    base = strip_extension(display_name) if ext else display_name
    # Reserve for dot + ext
    reserve = len(ext) + 1 if ext else 0
    allowed_base = max_len - reserve
    if allowed_base <= 0:
        # extreme: just truncate ext too
        return display_name[:max_len]
    # Truncate base without splitting in middle of ... Python slice is codepoint-safe, okay for Persian
    # Avoid cutting in middle of surrogate? Python handles.
    truncated_base = base[:allowed_base].rstrip(TRIM_CHARS)
    if ext:
        return f"{truncated_base}.{ext}"
    return truncated_base


def deduplicate_filename(desired: str, existing: set, start: int = 1) -> str:
    """
    §15 — If desired exists in session, append (1), (2) etc.

    existing: set of existing display_file_name strings in same session
    """
    if desired not in existing:
        return desired
    ext = get_extension(desired)
    base = strip_extension(desired) if ext else desired
    for i in range(start, 1000):
        candidate = f"{base} ({i})"
        if ext:
            candidate = f"{candidate}.{ext}"
        if candidate not in existing:
            # Ensure still within max len
            candidate = truncate_display_filename(candidate)
            if candidate not in existing:
                return candidate
    # fallback with unique suffix
    import secrets
    suffix = secrets.token_hex(2)
    return truncate_display_filename(f"{base} ({suffix}){'.' + ext if ext else ''}")


# ──────────────────────────────────────────────────────────
# Public pipeline helper
# ──────────────────────────────────────────────────────────

def prepare_rename(
    user_input: str,
    original_filename: str,
    existing_names: set | None = None,
    fallback: str = "فایل",
) -> dict:
    """
    Full pipeline: sanitize -> build -> truncate -> deduplicate.

    Returns dict with:
        display_name: final filename with ext
        base: sanitized base
        ext: final ext
        original_ext: original ext
        truncated: bool
        deduplicated: bool
    """
    built = build_display_filename(user_input, original_filename, fallback=fallback)
    truncated = truncate_display_filename(built)
    was_truncated = truncated != built
    final = truncated
    was_deduplicated = False
    if existing_names is not None:
        deduped = deduplicate_filename(truncated, existing_names)
        was_deduplicated = deduped != truncated
        final = deduped
    return {
        "display_name": final,
        "base": strip_extension(final) if get_extension(final) else final,
        "ext": get_extension(final),
        "original_ext": get_extension(original_filename),
        "truncated": was_truncated,
        "deduplicated": was_deduplicated,
    }


# ──────────────────────────────────────────────────────────
# Media type helpers (§ 6 / 7)
# ──────────────────────────────────────────────────────────

# Generic: we don't hardcode per-MIME. Extension drives type.
# But for Telegram API choice (sendDocument vs sendPhoto etc) we need media_type.

def detect_media_type(mime: str, ext: str) -> str:
    """
    Lightweight detection for caption/log, not for branching filename logic.
    Returns one of: 'document','photo','video','audio','voice','archive'
    """
    ext = (ext or '').lower()
    mime = (mime or '').lower()
    if ext in ('jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'svg') or 'image' in mime:
        # Telegram treats these as photo if sent as photo, but we send as document for rename
        return 'photo'
    if ext in ('mp4', 'mov', 'mkv', 'avi', 'webm', 'flv') or 'video' in mime:
        return 'video'
    if ext in ('mp3', 'wav', 'm4a', 'ogg', 'flac', 'aac') or mime.startswith('audio'):
        return 'audio'
    if ext in ('zip', 'rar', '7z', 'tar', 'gz'):
        return 'archive'
    return 'document'


def should_reupload_as_document(media_type: str) -> bool:
    """
    §7 — For photo, renaming requires re-upload as document to preserve filename.
    Document keeps filename natively; photo does not.
    """
    return media_type == 'photo'
