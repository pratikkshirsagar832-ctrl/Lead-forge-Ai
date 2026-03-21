"""
LeadForge AI — User Schemas
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


class UserResponse(BaseModel):
    """Public user profile response."""
    id: str
    email: EmailStr
    name: str = ""
    avatar_url: str = ""
    auth_provider: str = "email"
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UserProfileUpdate(BaseModel):
    """Fields allowed when updating a user profile."""
    name: Optional[str] = None
    avatar_url: Optional[str] = None


class CurrentUserResponse(BaseModel):
    """Response for GET /api/auth/me."""
    id: str
    email: str
    name: str = ""
    avatar_url: str = ""
    auth_provider: str = "email"
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
