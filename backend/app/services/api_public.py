"""Public API v1 helpers: stable JSON shapes + signed completion webhooks.

The public API never returns internal DB rows directly - everything goes
through the serializers below so field names stay stable across releases.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import threading
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from app.services.api_wallet import inr, price_per_lead_usd, usd_for_leads, usd_from_paise

logger = logging.getLogger(__name__)

TERMINAL = ("completed", "failed", "cancelled")
WEBHOOK_TIMEOUT_S = 10.0
WEBHOOK_BACKOFF_S = (2.0, 10.0, 30.0)
USER_AGENT = "Hyperclients-Webhooks/1.0"


# ---------------------------------------------------------------- shapes

def public_status(status: str | None) -> str:
    s = (status or "queued").lower()
    if s in TERMINAL:
        return s
    return "queued" if s == "queued" else "running"


def serialize_search(row: dict[str, Any], delivered: int | None = None) -> dict[str, Any]:
    source = row.get("source") or "google_maps"
    lead_types = row.get("lead_types") or []
    requested = int(row.get("max_results") or 0)
    price = int(row.get("price_per_lead_paise") or 0)
    status = public_status(row.get("status"))
    if delivered is None:
        delivered = int(row.get("total_results") or 0) if status in TERMINAL else int(row.get("hot_leads") or 0)
    out: dict[str, Any] = {
        "id": row.get("id"),
        "object": "search",
        "source": source,
        "service": row.get("niche"),
        "status": status,
        "progress_percent": int(row.get("progress_percent") or (100 if status == "completed" else 0)),
        "message": _public_message(source, status, requested, int(delivered or 0)),
        "requested": requested,
        "delivered": int(delivered or 0),
        "price_per_lead_inr": inr(price),
        "price_per_lead_usd": price_per_lead_usd(source),
        "max_charge_inr": inr(price * requested),
        "max_charge_usd": usd_for_leads(source, requested),
        "charged_inr": inr(row.get("wallet_charged_paise")) if row.get("wallet_settled_at") else None,
        "charged_usd": (usd_from_paise(source, row.get("wallet_charged_paise"))
                        if row.get("wallet_settled_at") else None),
        "webhook_url": row.get("webhook_url"),
        "created_at": row.get("created_at"),
        "completed_at": row.get("completed_at"),
    }
    if source == "linkedin":
        out["mode"] = "agency" if "agency" in lead_types else "freelancer"
    else:
        out["location"] = row.get("location")
    if status == "failed":
        out["error"] = row.get("error_message") or row.get("message") or "search failed"
    return out


def _public_message(source: str, status: str, requested: int, delivered: int) -> str:
    """Stable, customer-facing progress text (internal engine/scraper
    messages like "Found 25/5 businesses" never leak into the API)."""
    where = "LinkedIn" if source == "linkedin" else "Google Maps"
    if status == "queued":
        return "Search queued"
    if status == "running":
        return f"Searching {where}: {delivered} of {requested} leads found so far"
    if status == "completed":
        if delivered >= requested:
            return f"Done: {delivered} lead{'s' if delivered != 1 else ''} delivered"
        return (f"Done: {delivered} of {requested} leads delivered (only this many qualified "
                f"leads exist right now; you are charged for {delivered})")
    if status == "cancelled":
        return f"Cancelled: {delivered} lead{'s' if delivered != 1 else ''} delivered before cancel"
    return "Search failed - you were not charged for undelivered leads"


def serialize_linkedin_lead(row: dict[str, Any]) -> dict[str, Any]:
    posted = row.get("posted_at") or row.get("post_date")
    return {
        "id": row.get("id"),
        "object": "lead",
        "source": "linkedin",
        "type": "agency_wanted" if row.get("lead_type") == "need_agency" else "freelancer_needed",
        "author_name": row.get("author_name"),
        "author_profile_url": row.get("author_profile_url"),
        "post_url": row.get("post_url"),
        "post_text": row.get("post_text"),
        "posted_at": str(posted) if posted else None,
        "quality_score": _num(row.get("overall_quality_score")),
        "service_match_score": _num(row.get("service_match_score")),
        "intent": row.get("intent_strength"),
        "created_at": row.get("created_at"),
    }


def serialize_maps_lead(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "object": "lead",
        "source": "google_maps",
        "business_name": row.get("business_name"),
        "category": row.get("category") or None,
        "phone": row.get("phone") or None,
        "email": row.get("email_found") or None,
        "website": row.get("website_url") or None,
        "address": row.get("full_address") or None,
        "rating": _num(row.get("rating")),
        "reviews": int(row.get("total_reviews") or 0),
        "google_maps_url": row.get("google_maps_link") or None,
        "has_website": bool(row.get("website_url")),
        "created_at": row.get("created_at"),
    }


def _num(v: Any) -> float | None:
    try:
        return round(float(v), 1) if v is not None else None
    except (TypeError, ValueError):
        return None


def fetch_leads(supabase, search_row: dict[str, Any], limit: int = 500) -> list[dict[str, Any]]:
    sid = search_row["id"]
    if search_row.get("source") == "linkedin":
        rows = (
            supabase.table("ha_leads").select("*").eq("search_id", sid)
            .order("post_date", desc=True).limit(limit).execute().data or []
        )
        return [serialize_linkedin_lead(r) for r in rows]
    rows = (
        supabase.table("leads").select("*").eq("search_id", sid)
        .order("created_at", desc=False).limit(limit).execute().data or []
    )
    return [serialize_maps_lead(r) for r in rows]


def count_leads(supabase, search_row: dict[str, Any]) -> int:
    table = "ha_leads" if search_row.get("source") == "linkedin" else "leads"
    resp = supabase.table(table).select("id", count="exact").eq("search_id", search_row["id"]).execute()
    return int(resp.count or 0)


# -------------------------------------------------------------- webhooks

def validate_webhook_url(url: str | None) -> str | None:
    """Return an error message when the URL is not an acceptable webhook
    target (https only, public host - never internal networks), else None."""
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return "webhook_url is not a valid URL"
    if parts.scheme != "https":
        return "webhook_url must use https://"
    host = parts.hostname or ""
    if not host or host in ("localhost",) or host.endswith((".local", ".internal", ".localhost")):
        return "webhook_url must be a public host"
    if len(url) > 500:
        return "webhook_url is too long"
    return None


def _resolves_public(host: str) -> bool:
    """SSRF guard at DELIVERY time: every resolved address must be public."""
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False
    return bool(infos)


def sign_payload(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={mac}"


def verify_signature(secret: str, header: str, body: bytes, tolerance_s: int = 300) -> bool:
    """Reference verifier (mirrors the documented algorithm)."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        ts = int(parts["t"])
    except (ValueError, KeyError):
        return False
    if abs(time.time() - ts) > tolerance_s:
        return False
    expected = sign_payload(secret, ts, body).split("v1=", 1)[1]
    return hmac.compare_digest(expected, parts.get("v1", ""))


def deliver_search_webhook(supabase, search_id: str) -> None:
    """POST the finished search + its leads to the search's webhook_url.
    Blocking (retries with backoff) - call from a daemon thread."""
    row = None
    # Settlement can run a moment BEFORE the pipeline writes the final status
    # (Maps settles, then marks completed): wait for a terminal status.
    for _ in range(20):
        try:
            row = (supabase.table("searches").select("*").eq("id", search_id).limit(1).execute().data or [None])[0]
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Webhook:%s] could not load search: %s", search_id, exc)
            return
        if not row or public_status(row.get("status")) in TERMINAL:
            break
        time.sleep(1.5)
    if not row or row.get("billing") != "api" or not row.get("webhook_url"):
        return
    url = row["webhook_url"]
    secret = ""
    if row.get("api_key_id"):
        key = (supabase.table("api_keys").select("webhook_secret").eq("id", row["api_key_id"])
               .limit(1).execute().data or [{}])[0]
        secret = key.get("webhook_secret") or ""
    if not secret or validate_webhook_url(url) or not _resolves_public(urlsplit(url).hostname or ""):
        _mark_webhook(supabase, search_id, "rejected", 0)
        return

    leads = fetch_leads(supabase, row) if public_status(row.get("status")) == "completed" else []
    search = serialize_search(row, delivered=len(leads) if leads else None)
    event = "search.completed" if search["status"] == "completed" else f"search.{search['status']}"
    body = json.dumps({
        "event": event,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data": {"search": search, "leads": leads},
    }, default=str).encode()

    import httpx

    attempts = 0
    for delay in (0.0, *WEBHOOK_BACKOFF_S):
        if delay:
            time.sleep(delay)
        attempts += 1
        ts = int(time.time())
        try:
            resp = httpx.post(url, content=body, timeout=WEBHOOK_TIMEOUT_S, follow_redirects=False, headers={
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "X-Hyperclients-Event": event,
                "X-Hyperclients-Signature": sign_payload(secret, ts, body),
            })
            if 200 <= resp.status_code < 300:
                _mark_webhook(supabase, search_id, "delivered", attempts)
                return
            logger.info("[Webhook:%s] attempt %d -> HTTP %s", search_id, attempts, resp.status_code)
        except Exception as exc:  # noqa: BLE001 - retry
            logger.info("[Webhook:%s] attempt %d failed: %s", search_id, attempts, exc)
    _mark_webhook(supabase, search_id, "failed", attempts)


def deliver_search_webhook_async(supabase, search_id: str) -> None:
    threading.Thread(target=deliver_search_webhook, args=(supabase, search_id),
                     daemon=True, name=f"webhook-{search_id[:8]}").start()


def _mark_webhook(supabase, search_id: str, status: str, attempts: int) -> None:
    try:
        supabase.table("searches").update(
            {"webhook_status": status, "webhook_attempts": attempts}
        ).eq("id", search_id).execute()
    except Exception:  # noqa: BLE001
        pass
