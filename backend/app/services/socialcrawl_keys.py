"""SocialCrawl API keys: encrypted storage, admin management, usage, rotation.

Keys live in `socialcrawl_keys` (migration v23), encrypted with the app's
Fernet key (token_crypto). Keys listed in SOCIALCRAWL_API_KEY /
SOCIALCRAWL_API_KEYS are imported once per process; after that the table is
the source of truth and /admin/keys adds, removes, disables and re-checks keys.

`build_pool()` hands the LinkedIn engine a KeyPool: when a key runs out of
credits mid-search it is marked `exhausted` here and the next key takes over.
If the table is missing (migration not applied) the env keys are used as-is.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.services import hyperagent_service  # noqa: F401 - puts backend/ha on sys.path
from app.services.token_crypto import decrypt, encrypt

from discovery.keypool import KeyPool, PoolKey  # noqa: E402
from discovery.socialcrawl_client import check_balance  # noqa: E402

logger = logging.getLogger(__name__)

TABLE = "socialcrawl_keys"
LISTED = ("active", "exhausted", "invalid", "disabled")
_env_imported = False
_env_lock = threading.Lock()
_usage_writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sc-usage")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def key_hash(key: str) -> str:
    return hashlib.sha256(key.strip().encode()).hexdigest()


def env_keys() -> list[str]:
    s = get_settings()
    raw = [s.socialcrawl_api_key] + (s.socialcrawl_api_keys or "").replace("\n", ",").split(",")
    out: list[str] = []
    for k in raw:
        k = (k or "").strip()
        if k and k not in out:
            out.append(k)
    return out


def _base_url() -> str:
    return get_settings().socialcrawl_base_url


# ------------------------------------------------------------------ storage

def _insert(supabase, key: str, *, label: str, source: str, priority: int,
            balance: dict[str, Any] | None = None) -> dict[str, Any]:
    balance = balance or {}
    status = balance.get("status") if balance.get("status") in ("active", "exhausted", "invalid") else "active"
    row = {
        "label": label or None, "key_enc": encrypt(key.strip()), "key_hash": key_hash(key),
        "key_hint": key.strip()[-4:], "status": status, "source": source, "priority": priority,
        "credits_remaining": balance.get("credits_remaining"),
        "last_error": balance.get("error") or None,
        "last_checked_at": _now() if balance else None,
    }
    return supabase.table(TABLE).insert(row).execute().data[0]


def import_env_keys(supabase, *, force: bool = False) -> int:
    """Add env keys that are not in the table yet (never re-adds a removed one)."""
    global _env_imported
    with _env_lock:
        if _env_imported and not force:
            return 0
        keys = env_keys()
        if not keys:
            _env_imported = True
            return 0
        hashes = [key_hash(k) for k in keys]
        existing = {r["key_hash"] for r in (supabase.table(TABLE).select("key_hash").in_("key_hash", hashes)
                                            .execute().data or [])}
        added = 0
        for i, k in enumerate(keys):
            if key_hash(k) in existing:
                continue
            _insert(supabase, k, label=f"env key {i + 1}", source="env", priority=100 + i)
            added += 1
        _env_imported = True
        if added:
            logger.info("Imported %d SocialCrawl key(s) from the environment", added)
        return added


def public_row(r: dict[str, Any]) -> dict[str, Any]:
    """Admin-safe view: never the key itself."""
    return {k: r.get(k) for k in ("id", "label", "key_hint", "status", "source", "priority", "credits_remaining",
                                  "credits_used", "calls", "last_error", "last_used_at", "last_checked_at",
                                  "created_at")}


def list_keys(supabase) -> dict[str, Any]:
    import_env_keys(supabase)
    rows = (supabase.table(TABLE).select("*").in_("status", list(LISTED))
            .order("priority").order("created_at").execute().data or [])
    keys = [public_row(r) for r in rows]
    active = [k for k in keys if k["status"] == "active"]
    return {
        "keys": keys,
        "totals": {
            "keys": len(keys),
            "active": len(active),
            "credits_remaining": sum(int(k["credits_remaining"] or 0) for k in active),
            "credits_used": sum(int(k["credits_used"] or 0) for k in keys),
            "calls": sum(int(k["calls"] or 0) for k in keys),
        },
        "in_use": active[0]["id"] if active else None,
    }


def add_key(supabase, key: str, label: str = "") -> dict[str, Any]:
    key = (key or "").strip()
    if not key.startswith("sc_") or len(key) < 20:
        raise ValueError("That does not look like a SocialCrawl API key (they start with sc_).")
    balance = check_balance(key, base_url=_base_url())
    if balance["status"] == "invalid":
        raise ValueError("SocialCrawl rejected this key. Check it and try again.")
    existing = supabase.table(TABLE).select("*").eq("key_hash", key_hash(key)).limit(1).execute().data or []
    if existing:
        row = existing[0]
        if row["status"] != "removed":
            raise ValueError("This key is already in the list.")
        status = balance["status"] if balance["status"] in ("active", "exhausted") else "active"
        row = supabase.table(TABLE).update({
            "status": status, "label": label or row.get("label"), "credits_remaining": balance.get("credits_remaining"),
            "last_error": balance.get("error") or None, "last_checked_at": _now(), "updated_at": _now(),
        }).eq("id", row["id"]).execute().data[0]
        return public_row(row)
    top = supabase.table(TABLE).select("priority").order("priority", desc=True).limit(1).execute().data or []
    priority = int(top[0]["priority"]) + 1 if top else 100
    return public_row(_insert(supabase, key, label=label, source="admin", priority=priority, balance=balance))


def remove_key(supabase, key_id: str) -> bool:
    res = supabase.table(TABLE).update({"status": "removed", "updated_at": _now()}).eq("id", key_id).execute()
    return bool(res.data)


def set_enabled(supabase, key_id: str, enabled: bool) -> dict[str, Any] | None:
    status = "active" if enabled else "disabled"
    res = supabase.table(TABLE).update({"status": status, "updated_at": _now()}) \
        .eq("id", key_id).neq("status", "removed").execute()
    return public_row(res.data[0]) if res.data else None


def refresh_balances(supabase) -> dict[str, Any]:
    """Live balance of every key (free dry-run calls); revives topped-up keys."""
    import_env_keys(supabase)
    rows = supabase.table(TABLE).select("*").in_("status", ["active", "exhausted", "invalid"]).execute().data or []
    for r in rows:
        try:
            bal = check_balance(decrypt(r["key_enc"]), base_url=_base_url())
        except Exception as exc:  # noqa: BLE001 - one bad row never stops the rest
            bal = {"status": "error", "credits_remaining": None, "error": str(exc)[:200]}
        update: dict[str, Any] = {"last_checked_at": _now(), "updated_at": _now(), "last_error": bal.get("error") or None}
        if bal.get("credits_remaining") is not None:
            update["credits_remaining"] = bal["credits_remaining"]
        if bal["status"] in ("active", "exhausted", "invalid"):
            update["status"] = bal["status"]
        supabase.table(TABLE).update(update).eq("id", r["id"]).execute()
    return list_keys(supabase)


# ------------------------------------------------------------------ engine

def build_pool(supabase) -> KeyPool:
    """KeyPool for one search. Falls back to env keys if the table is missing."""
    try:
        import_env_keys(supabase)
        rows = (supabase.table(TABLE).select("*").in_("status", ["active", "exhausted"])
                .order("priority").order("created_at").execute().data or [])
    except Exception as exc:  # noqa: BLE001 - migration v23 not applied yet
        logger.warning("SocialCrawl key table unavailable (%s) - using env keys", exc)
        return KeyPool.from_keys(env_keys())

    keys: list[PoolKey] = []
    for r in rows:
        try:
            keys.append(PoolKey(key=decrypt(r["key_enc"]), id=r["id"], label=r.get("label") or "",
                                status=r["status"], credits_remaining=r.get("credits_remaining"),
                                priority=int(r.get("priority") or 100)))
        except Exception as exc:  # noqa: BLE001 - undecryptable row (key rotated)
            logger.error("Cannot decrypt SocialCrawl key %s: %s", r.get("id"), exc)
    if not keys:
        return KeyPool.from_keys(env_keys()) if not rows else KeyPool(keys)

    def on_change(k: PoolKey, reason: str) -> None:
        status, remaining = k.status, k.credits_remaining

        def write() -> None:
            try:
                supabase.table(TABLE).update({
                    "status": status, "credits_remaining": remaining, "last_error": reason[:300] or None,
                    "updated_at": _now(),
                }).eq("id", k.id).execute()
            except Exception as exc:  # noqa: BLE001
                logger.warning("SocialCrawl key status write failed: %s", exc)
        # same single-thread writer as usage rows -> writes land in order
        _usage_writer.submit(write)
        logger.info("SocialCrawl key ...%s -> %s (%s)", k.hint, k.status, reason)

    def on_usage(k: PoolKey, credits: int, remaining: int | None) -> None:
        def write() -> None:
            try:
                supabase.rpc("record_socialcrawl_usage", {"p_id": k.id, "p_calls": 1, "p_credits": credits,
                                                          "p_remaining": remaining}).execute()
            except Exception as exc:  # noqa: BLE001 - usage stats are best-effort
                logger.debug("SocialCrawl usage write failed: %s", exc)
        _usage_writer.submit(write)

    def refresher(k: PoolKey) -> int | None:
        bal = check_balance(k.key, base_url=_base_url())
        supabase.table(TABLE).update({"credits_remaining": bal.get("credits_remaining"), "last_checked_at": _now(),
                                      "updated_at": _now()}).eq("id", k.id).execute()
        return bal.get("credits_remaining") if bal["status"] == "active" else None

    return KeyPool(keys, on_change=on_change, on_usage=on_usage, refresher=refresher)
