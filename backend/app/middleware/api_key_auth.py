"""API-key authentication + per-key rate limits for the public API (/v1).

Accepts ``Authorization: Bearer hc_live_…`` or ``X-API-Key: hc_live_…``.
Resolves to the same user dict shape as ``get_current_user`` (plus
``api_key_id``/``webhook_secret``) so shared services work unchanged.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.database import get_supabase_admin
from app.services import api_keys
from app.utils.rate_limit import check_rate_limit

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """Public-API error rendered as {"error": {"code", "message", ...}}."""

    def __init__(self, status: int, code: str, message: str, headers: dict[str, str] | None = None,
                 **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}
        self.extra = extra

    def body(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, **self.extra}}


# Declared as OpenAPI security schemes so /v1/docs shows an "Authorize" button.
_bearer = HTTPBearer(auto_error=False, scheme_name="ApiKeyBearer",
                     description="Your API key: `Authorization: Bearer hc_live_...`")
_header = APIKeyHeader(name="X-API-Key", auto_error=False, scheme_name="ApiKeyHeader",
                       description="Alternative: `X-API-Key: hc_live_...`")


async def get_api_user(
    request: Request,
    bearer: HTTPAuthorizationCredentials | None = Depends(_bearer),
    x_api_key: str | None = Depends(_header),
) -> dict[str, Any]:
    raw = (x_api_key or "").strip() or (bearer.credentials.strip() if bearer else "")
    if not raw:
        raise ApiError(401, "unauthorized",
                       "Missing API key. Send 'Authorization: Bearer hc_live_...' or 'X-API-Key'.",
                       headers={"WWW-Authenticate": "Bearer"})
    if not api_keys.looks_like_key(raw):  # malformed: reject without a DB round-trip
        raise ApiError(401, "unauthorized", "Invalid API key format (expected hc_live_...).",
                       headers={"WWW-Authenticate": "Bearer"})
    try:
        record = api_keys.verify_key(get_supabase_admin(), raw)
    except Exception as exc:
        logger.warning("API key verification failed: %s", exc)
        raise ApiError(503, "service_unavailable", "Could not verify the API key. Please retry.")
    if record is None:
        raise ApiError(401, "unauthorized", "Invalid or revoked API key.",
                       headers={"WWW-Authenticate": "Bearer"})

    settings = get_settings()
    is_create = request.method == "POST" and request.url.path.rstrip("/").endswith("/searches")
    limit = settings.api_rate_create_per_min if is_create else settings.api_rate_read_per_min
    bucket = f"api:{record['api_key_id']}:{'create' if is_create else 'read'}"
    if not check_rate_limit(bucket, limit, 60):
        raise ApiError(429, "rate_limited",
                       f"Rate limit exceeded ({limit} requests/minute for this endpoint).",
                       headers={"Retry-After": "60"})

    return {
        "id": record["user_id"],
        "email": "",
        "name": record.get("key_name") or "",
        "api_key_id": record["api_key_id"],
        "webhook_secret": record.get("webhook_secret") or "",
    }
