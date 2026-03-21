"""
LeadForge AI — Utility Helpers

Shared helper functions used across the application.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return utc_now().isoformat()


def safe_str(value: Any, default: str = "") -> str:
    """Safely convert a value to a string."""
    if value is None:
        return default
    return str(value).strip()


def safe_int(value: Any, default: int = 0) -> int:
    """Safely convert a value to an integer."""
    if value is None:
        return default
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default


def safe_float(value: Any, default: float | None = None) -> float | None:
    """Safely convert a value to a float."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def truncate(text: str, max_length: int = 500, suffix: str = "...") -> str:
    """Truncate text to a maximum length."""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def normalize_url(url: Optional[str]) -> str:
    """Normalize a URL (add scheme if missing)."""
    if not url:
        return ""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url


def extract_domain(url: str) -> str:
    """Extract the domain from a URL."""
    if not url:
        return ""
    # Remove scheme
    domain = re.sub(r"https?://", "", url)
    # Remove path
    domain = domain.split("/")[0]
    # Remove port
    domain = domain.split(":")[0]
    return domain.lower()


def sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    # Replace non-alphanumeric characters with underscores
    name = re.sub(r"[^\w\s-]", "_", name)
    name = re.sub(r"[\s]+", "_", name)
    return name.strip("_")[:100]
