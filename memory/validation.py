"""Strict validation, UTC normalization, and conservative credential detection."""
import os
import re
import unicodedata
from datetime import datetime, timezone
from memory.models import MAX_CONTENT_CHARS, MemoryCategory
from security.validator import ValidationError

CATEGORIES = tuple(item.value for item in MemoryCategory)
_SECRET = re.compile(
    r"-----BEGIN .*PRIVATE KEY-----|\bsk-[\w-]{16,}|\bAIza[\w-]{25,}|"
    r"\bgh[pousr]_[\w]{20,}|\bgithub_pat_[\w]{20,}|\b(?:AKIA|ASIA)[A-Z0-9]{16}|"
    r"\bBearer\s+\S+|\b(?:password|passwd|secret|api[ _-]?key|access[ _-]?token|"
    r"refresh[ _-]?token|private[ _-]?key)\s*(?::|=|\bis\b)\s*\S+|"
    r"\beyJ[\w-]+\.[\w-]+\.[\w-]+|[a-z]+://[^\s/:]+:[^\s/@]+@", re.IGNORECASE)

def invalid():
    raise ValidationError("MEMORY_INVALID_RECORD")

def text(value, maximum, *, empty=False):
    if type(value) is not str or len(value) > maximum:
        invalid()
    # Invisible/control characters could conceal content in the approval display.
    if any(unicodedata.category(char).startswith("C") for char in value):
        invalid()
    value = value.strip()
    if not value and not empty:
        invalid()
    return value

def contains_secret(value):
    key = os.environ.get("GEMINI_API_KEY", "")
    return bool(_SECRET.search(value) or (key and key in value))

def validate_memory_content(content):
    text(content, MAX_CONTENT_CHARS)
    # Preserve the exact approved content, including ordinary outer spaces.
    if contains_secret(content):
        raise ValidationError("SECRET_DETECTED")
    return content

def validate_category(category, *, optional=False):
    if type(category) is not str or category not in CATEGORIES + (("",) if optional else ()):
        invalid()
    return category

def validate_memory_id(memory_id):
    if type(memory_id) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{22}", memory_id):
        invalid()
    return memory_id

def validate_tags(value):
    value = text(value, 256, empty=True)
    if contains_secret(value):
        raise ValidationError("SECRET_DETECTED")
    tags = [item.strip().lower() for item in value.split(",") if item.strip()]
    if len(tags) > 8 or any(not re.fullmatch(r"[\w-]{1,32}", tag) for tag in tags):
        invalid()
    return tuple(sorted(set(tags)))

def validate_timestamp(value):
    value = text(value, 40)
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            invalid()
        return result.astimezone(timezone.utc).isoformat(timespec="microseconds")
    except (ValueError, OverflowError):
        invalid()

def validate_expiration(value):
    return None if value == "" else validate_timestamp(value)

def validate_limit(value):
    if type(value) is not int or not 1 <= value <= 50:
        invalid()
    return value
