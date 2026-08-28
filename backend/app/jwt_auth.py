"""
LeadForge — JWT Auth System

Generates and verifies JWT tokens for local user authentication.
Supabase is only used for Google OAuth flow.
"""

import time
import hashlib
import hmac
import json
import base64
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

JWT_SECRET = os.getenv("JWT_SECRET", "leadforge-jwt-secret-2026-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 72


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_token(user_id: str, email: str, name: str = "") -> str:
    """Create a JWT token."""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "name": name,
        "iat": now,
        "exp": now + (JWT_EXPIRY_HOURS * 3600),
    }
    return _encode_jwt(payload)


def verify_token(token: str) -> Optional[dict]:
    """Verify and decode a JWT token. Returns payload or None if invalid."""
    try:
        payload = _decode_jwt(token)
        if not payload:
            return None
        # Check expiry
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception as e:
        logger.debug(f"JWT verify failed: {e}")
        return None


def refresh_token(token: str) -> Optional[str]:
    """Refresh a JWT token (if valid, create a new one with extended expiry)."""
    payload = verify_token(token)
    if not payload:
        return None
    return create_token(
        user_id=payload["sub"],
        email=payload.get("email", ""),
        name=payload.get("name", ""),
    )


# ── Low-level JWT implementation ────────────────────────────────

def _encode_jwt(payload: dict) -> str:
    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    header_b64 = _b64url_encode(json.dumps(header).encode())
    payload_b64 = _b64url_encode(json.dumps(payload).encode())
    signing_input = f"{header_b64}.{payload_b64}"
    signature = hmac.new(
        JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256
    ).digest()
    signature_b64 = _b64url_encode(signature)
    return f"{signing_input}.{signature_b64}"


def _decode_jwt(token: str) -> Optional[dict]:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    header_b64, payload_b64, signature_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}"
    expected_sig = hmac.new(
        JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256
    ).digest()
    actual_sig = _b64url_decode(signature_b64)
    if not hmac.compare_digest(expected_sig, actual_sig):
        return None
    payload = json.loads(_b64url_decode(payload_b64))
    return payload
