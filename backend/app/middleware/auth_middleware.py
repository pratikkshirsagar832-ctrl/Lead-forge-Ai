"""
LeadForge AI — Auth Middleware

FastAPI dependency that extracts and verifies Supabase Bearer tokens.
Frontend handles all auth flows directly with Supabase;
backend only validates the token and resolves the current user.
"""

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.database import get_supabase_admin

security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """
    Dependency: Verify Supabase access token and return user data.

    Raises 401 if token is missing/invalid.
    Returns the Supabase user dict (id, email, user_metadata, etc.).
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    try:
        supabase = get_supabase_admin()
        user_response = supabase.auth.get_user(token)

        if user_response is None or user_response.user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return {
            "id": str(user_response.user.id),
            "email": user_response.user.email or "",
            "user_metadata": user_response.user.user_metadata or {},
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token verification failed: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user_id(
    current_user: dict = Depends(get_current_user),
) -> str:
    """Convenience dependency: returns just the user ID string."""
    return current_user["id"]
