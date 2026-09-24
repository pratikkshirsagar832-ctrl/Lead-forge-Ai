"""
Hyperclients — Supabase Database Clients

Provides two client factories:
  - get_supabase_client(): anon/user-facing client
  - get_supabase_admin(): service-role admin client (bypasses RLS)

No ORM. No SQLAlchemy. Pure Supabase Python client.
"""

import httpx
from supabase import Client, ClientOptions, create_client

from app.config import get_settings

_anon_client: Client | None = None
_admin_client: Client | None = None


def _http_client() -> httpx.Client:
    """HTTP/1.1 connection POOL shared by every thread.

    The default client multiplexes all requests over ONE HTTP/2 connection.
    Handlers now run in FastAPI's threadpool (and the lead engine has worker
    threads), so many requests share that connection concurrently; when the
    Supabase edge closes it (GOAWAY, seen in production as
    "ConnectionTerminated" / "Server disconnected") every in-flight request
    failed at once - e.g. the sales pipeline's 5 parallel stage loads -> 500.
    With HTTP/1.1 each request has its own pooled connection; idle
    connections expire before the server drops them and connect errors retry.
    """
    return httpx.Client(
        http2=False,
        timeout=httpx.Timeout(120.0, connect=10.0),
        transport=httpx.HTTPTransport(
            retries=2,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=15.0),
        ),
    )


def _create(url: str, key: str) -> Client:
    try:  # supabase-py >= 2.2x: every sub-client shares the pool
        return create_client(url, key, options=ClientOptions(httpx_client=_http_client()))
    except TypeError:  # older supabase-py (production pins 2.13): swap the DB session only
        client = create_client(url, key)
        try:
            old = client.postgrest.session
            client.postgrest.session = httpx.Client(
                base_url=old.base_url, headers=old.headers, timeout=old.timeout, http2=False,
                transport=httpx.HTTPTransport(retries=2, limits=httpx.Limits(
                    max_connections=100, max_keepalive_connections=20, keepalive_expiry=15.0)))
            old.close()
        except Exception:  # noqa: BLE001 - keep the default client rather than fail
            pass
        return client


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
        _anon_client = _create(settings.supabase_url, settings.supabase_anon_key)
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
        _admin_client = _create(settings.supabase_url, settings.supabase_service_role_key)
    return _admin_client
