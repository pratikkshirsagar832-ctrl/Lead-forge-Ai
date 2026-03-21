"""
LeadForge AI — Auth Service

Helper methods for user profile operations.
Token verification is handled by the auth middleware dependency.
"""

import logging

from app.database import get_supabase_admin

logger = logging.getLogger(__name__)


async def get_user_profile(user_id: str) -> dict | None:
    """
    Fetch the public user profile from the users table.
    Returns None if not found.
    """
    try:
        supabase = get_supabase_admin()
        response = (
            supabase.table("users")
            .select("*")
            .eq("id", user_id)
            .single()
            .execute()
        )
        return response.data
    except Exception as e:
        logger.error(f"Failed to fetch user profile for {user_id}: {e}")
        return None


async def update_user_profile(user_id: str, updates: dict) -> dict | None:
    """
    Update fields in the public user profile.
    Only non-None fields in `updates` are applied.
    """
    try:
        # Filter out None values
        clean_updates = {k: v for k, v in updates.items() if v is not None}
        if not clean_updates:
            return await get_user_profile(user_id)

        supabase = get_supabase_admin()
        response = (
            supabase.table("users")
            .update(clean_updates)
            .eq("id", user_id)
            .execute()
        )
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        logger.error(f"Failed to update user profile for {user_id}: {e}")
        return None


async def ensure_user_exists(user_id: str, email: str, metadata: dict | None = None) -> dict:
    """
    Ensure a public.users row exists for the given auth user.
    Creates one if missing (fallback in case trigger didn't fire).
    """
    profile = await get_user_profile(user_id)
    if profile:
        return profile

    try:
        supabase = get_supabase_admin()
        meta = metadata or {}
        data = {
            "id": user_id,
            "email": email,
            "name": meta.get("full_name", meta.get("name", "")),
            "avatar_url": meta.get("avatar_url", ""),
            "auth_provider": meta.get("provider", "email"),
        }
        response = supabase.table("users").upsert(data).execute()
        if response.data:
            return response.data[0]
        return data
    except Exception as e:
        logger.error(f"Failed to ensure user exists for {user_id}: {e}")
        return {"id": user_id, "email": email}
