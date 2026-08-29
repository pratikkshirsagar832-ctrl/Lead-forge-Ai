"""
Hyperclients — Supabase Database Clients

Provides two client factories:
  - get_supabase_client(): anon/user-facing client
  - get_supabase_admin(): service-role admin client (bypasses RLS)

No ORM. No SQLAlchemy. Pure Supabase Python client.
"""

from supabase import Client, create_client

from app.config import get_settings

_anon_client: Client | None = None
_admin_client: Client | None = None


def get_supabase_client() -> Client:
    """
    Create a Supabase client using the anon key.
    Used for user-scoped operations that respect RLS.
    Cached after first call.
    """
    global _anon_client
    if _anon_client is None:
        settings = get_settings()
        if not settings.supabase_url or not settings.supabase_anon_key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY must be set")
        _anon_client = create_client(settings.supabase_url, settings.supabase_anon_key)
    return _anon_client


def get_supabase_admin() -> Client:
    """
    Create a Supabase client using the service role key.
    Bypasses RLS — use only for backend-internal operations
    (e.g., pipeline writes, admin queries, trigger-like behavior).
    Cached after first call.
    """
    global _admin_client
    if _admin_client is None:
        settings = get_settings()
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        _admin_client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    return _admin_client
