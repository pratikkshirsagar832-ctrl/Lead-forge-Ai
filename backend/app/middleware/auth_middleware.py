"""
LeadForge — Auth Middleware (Local DB + JWT)

Replaces Supabase auth for token verification.
Supabase is ONLY used for Google OAuth token exchange.
"""

import time
import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db import query_one
from app.jwt_auth import verify_token

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

_token_cache: dict[str, dict] = {}
CACHE_TTL = 300  # 5 minutes


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # Check cache
    cached = _token_cache.get(token)
    if cached and cached["expires_at"] > time.time():
        return cached["user"]

    # Verify JWT
    payload = verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload.",
        )

    # Fetch user from local DB
    user = query_one(
        "SELECT id, email, full_name, avatar_url FROM users WHERE id = %s",
        (user_id,),
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )

    result = {
        "id": str(user["id"]),
        "email": user["email"] or "",
        "name": user["full_name"] or user["email"] or "",
    }

    # Auto-create free subscription if missing
    try:
        sub_exists = query_one(
            "SELECT id FROM user_subscriptions WHERE user_id = %s LIMIT 1",
            (user_id,),
        )
        if not sub_exists:
            from datetime import datetime, timedelta, timezone
            now = datetime.now(timezone.utc)
            _create_free_subscription(user_id, now)
    except Exception as e:
        logger.warning(f"Subscription auto-creation failed: {e}")

    # Cache
    _token_cache[token] = {"user": result, "expires_at": time.time() + CACHE_TTL}

    # Cleanup expired entries periodically
    _cleanup_cache()

    return result


def _create_free_subscription(user_id: str, now: datetime):
    """Create a free trial subscription for a new user."""
    from app.db import execute
    execute(
        """INSERT INTO user_subscriptions (user_id, plan_id, status, trial_end, current_period_end)
           VALUES (%s, 'free', 'trial', %s, %s)""",
        (user_id, (now + timedelta(days=3)).isoformat(), (now + timedelta(days=3)).isoformat()),
    )


def _cleanup_cache():
    now = time.time()
    expired = [k for k, v in _token_cache.items() if v["expires_at"] <= now]
    for k in expired:
        _token_cache.pop(k, None)


async def get_current_user_id(current_user: dict = Depends(get_current_user)) -> str:
    return current_user["id"]
