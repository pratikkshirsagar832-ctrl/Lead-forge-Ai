"""Hyperclients public API keys.

Format: ``hc_live_<43 url-safe chars>``. Only the sha256 hash is stored
(``api_keys.key_hash``); the raw key is returned exactly once, at creation.
Each key also carries a webhook signing secret (``whsec_…``) used to sign
webhook deliveries for searches created with that key.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

KEY_PREFIX = "hc_live_"
MAX_KEYS_PER_USER = 10
_CACHE_TTL_S = 60.0

_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
_cache_lock = threading.Lock()


def hash_key(raw: str) -> str:
    return hashlib.sha256((raw or "").strip().encode("utf-8")).hexdigest()


def looks_like_key(raw: str | None) -> bool:
    return bool(raw) and raw.startswith(KEY_PREFIX) and len(raw) >= len(KEY_PREFIX) + 20


def generate_key() -> tuple[str, str]:
    """(raw api key, webhook secret)."""
    return KEY_PREFIX + secrets.token_urlsafe(32), "whsec_" + secrets.token_urlsafe(24)


def create_key(supabase, user_id: str, name: str) -> dict[str, Any]:
    """Create a key; the returned dict holds the RAW key + webhook secret
    (shown to the user once, never retrievable again)."""
    active = (
        supabase.table("api_keys").select("id").eq("user_id", user_id).is_("revoked_at", "null").execute()
    )
    if len(active.data or []) >= MAX_KEYS_PER_USER:
        raise ValueError(f"You can have at most {MAX_KEYS_PER_USER} active API keys. Revoke one first.")
    raw, webhook_secret = generate_key()
    row = {
        "user_id": user_id,
        "name": (name or "Default key").strip()[:60] or "Default key",
        "prefix": raw[: len(KEY_PREFIX) + 4],
        "key_hash": hash_key(raw),
        "webhook_secret": webhook_secret,
    }
    resp = supabase.table("api_keys").insert(row).execute()
    saved = (resp.data or [row])[0]
    return {
        "id": saved.get("id"),
        "name": row["name"],
        "prefix": row["prefix"],
        "api_key": raw,
        "webhook_secret": webhook_secret,
        "created_at": saved.get("created_at"),
    }


def list_keys(supabase, user_id: str) -> list[dict[str, Any]]:
    resp = (
        supabase.table("api_keys")
        .select("id,name,prefix,created_at,last_used_at,revoked_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return resp.data or []


def revoke_key(supabase, user_id: str, key_id: str) -> bool:
    resp = (
        supabase.table("api_keys")
        .update({"revoked_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", key_id)
        .eq("user_id", user_id)
        .is_("revoked_at", "null")
        .execute()
    )
    with _cache_lock:  # a revoked key must stop working immediately
        _cache.clear()
    return bool(resp.data)


def verify_key(supabase, raw: str) -> dict[str, Any] | None:
    """The key's owner record, or None for an unknown / revoked key.
    Cached 60 s per key (positive and negative) to keep auth off the DB."""
    if not looks_like_key(raw):
        return None
    digest = hash_key(raw)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(digest)
        if hit and hit[0] > now:
            return hit[1]
    try:
        resp = (
            supabase.table("api_keys")
            .select("id,user_id,name,webhook_secret,revoked_at")
            .eq("key_hash", digest)
            .limit(1)
            .execute()
        )
        row = (resp.data or [None])[0]
    except Exception as exc:  # noqa: BLE001 - DB hiccup must not be cached
        logger.warning("API key lookup failed: %s", exc)
        raise
    record = None
    if row and not row.get("revoked_at"):
        record = {
            "api_key_id": row["id"],
            "user_id": row["user_id"],
            "key_name": row.get("name") or "",
            "webhook_secret": row.get("webhook_secret") or "",
        }
        _touch_last_used(supabase, row["id"])
    with _cache_lock:
        if len(_cache) > 5000:
            _cache.clear()
        _cache[digest] = (now + _CACHE_TTL_S, record)
    return record


def _touch_last_used(supabase, key_id: str) -> None:
    def _run() -> None:
        try:
            supabase.table("api_keys").update(
                {"last_used_at": datetime.now(timezone.utc).isoformat()}
            ).eq("id", key_id).execute()
        except Exception:  # noqa: BLE001 - cosmetic
            pass

    threading.Thread(target=_run, daemon=True).start()
