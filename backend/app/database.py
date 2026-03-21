"""
LeadForge AI — Supabase Database Clients

Provides two client factories:
  - get_supabase_client(): anon/user-facing client
  - get_supabase_admin(): service-role admin client (bypasses RLS)

No ORM. No SQLAlchemy. Pure Supabase Python client.
"""

from functools import lru_cache

from supabase import Client, create_client

from app.config import get_settings


@lru_cache()
def get_supabase_client() -> Client:
    """
    Create a Supabase client using the anon key.
    Used for user-scoped operations that respect RLS.
    """
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_anon_key)


@lru_cache()
def get_supabase_admin() -> Client:
    """
    Create a Supabase client using the service role key.
    Bypasses RLS — use only for backend-internal operations
    (e.g., pipeline writes, admin queries, trigger-like behavior).
    """
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
