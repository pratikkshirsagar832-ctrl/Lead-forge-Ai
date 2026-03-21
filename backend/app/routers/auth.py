"""
LeadForge AI — Auth Router

Endpoints:
  GET  /api/auth/me     — get current user profile
  PUT  /api/auth/profile — update current user profile
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.middleware.auth_middleware import get_current_user
from app.schemas.user import CurrentUserResponse, UserProfileUpdate, UserResponse
from app.services.auth_service import ensure_user_exists, update_user_profile

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.get("/me", response_model=CurrentUserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    """
    Get the current authenticated user's profile.
    If the public profile doesn't exist yet, it gets created as a fallback.
    """
    profile = await ensure_user_exists(
        user_id=current_user["id"],
        email=current_user["email"],
        metadata=current_user.get("user_metadata"),
    )
    return profile


@router.put("/profile", response_model=UserResponse)
async def update_profile(
    updates: UserProfileUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Update the current user's profile (name, avatar_url)."""
    result = await update_user_profile(
        user_id=current_user["id"],
        updates=updates.model_dump(exclude_none=True),
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found",
        )
    return result
