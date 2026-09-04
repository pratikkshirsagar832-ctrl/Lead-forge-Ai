"""
Hyperclients — LinkedIn Public Post Scraper Service

Runs the in-house Apify actor "linkedin-post-scraper"
(actor id: handwoven_gharial_c6y/linkedin-post-scraper, numeric id from
settings.apify_post_scraper_actor_id) and persists its records.

WHAT THE ACTOR DOES (and does not do)
  - Input : LinkedIn PROFILE urls and/or direct POST urls.
  - Output: the profile's own PUBLIC post history (canonical post url,
            post text, author, date, engagement) — or an honest
            extraction_status (success|partial|failed|unresolved) when the
            page is not publicly reachable (FORBIDDEN / CAPTCHA_OR_CHALLENGE
            / RATE_LIMITED ...). The actor never logs in, never uses cookies,
            never rotates proxies to defeat LinkedIn access controls, and
            never substitutes a non-post url for post_url.
  - It does NOT do LinkedIn keyword search (that is not a public feature).

AUTHENTICATION / KEY SELECTION
  The actor is PRIVATE and can only be run by its owner account. Set
  APIFY_POST_SCRAPER_TOKEN to that owner's Apify token. When it is set, that
  token is tried first; on failure the shared APIFY_API_KEY rotation is used
  as a fallback. When unset, the shared rotation is used directly.
"""

import logging

from app.config import get_settings
from app.services.apify_service import (
    ApifyError,
    ApifyRetryableError,
    _run_sync_actor,
    _run_with_key,
)

logger = logging.getLogger(__name__)

DEFAULT_POST_SCRAPER_ACTOR_ID = "2nZ0rjo0R3O4fzBy3"

POST_TEXT_MAX = 3000  # matches the leads.post_text truncation convention
AUTHOR_TEXT_MAX = 500
URL_MAX = 2000


def _actor_id() -> str:
    settings = get_settings()
    return (settings.apify_post_scraper_actor_id or "").strip() or DEFAULT_POST_SCRAPER_ACTOR_ID


def build_actor_payload(
    profile_urls: list[str] | None = None,
    post_urls: list[str] | None = None,
    max_posts_per_profile: int = 10,
    include_engagement: bool = True,
    include_author: bool = True,
) -> dict:
    """Actor input payload (mirrors .actor/input_schema.json)."""
    profiles = [u.strip() for u in (profile_urls or []) if u and u.strip()][:10]
    posts = [u.strip() for u in (post_urls or []) if u and u.strip()][:20]
    if not profiles and not posts:
        raise ValueError("At least one profile_url or post_url is required")
    raw_max = max_posts_per_profile
    if raw_max is None or raw_max == "":
        posts_per_profile = 10
    else:
        posts_per_profile = max(1, min(int(raw_max), 50))
    payload: dict = {
        "profileUrls": profiles,
        "postUrls": posts,
        "maxPostsPerProfile": posts_per_profile,
        "includeEngagement": bool(include_engagement),
        "includeAuthor": bool(include_author),
        "maxConcurrency": 4,
        "requestTimeoutSecs": 30,
        "useBrowser": False,
    }
    if not profiles:
        payload.pop("profileUrls", None)
    if not posts:
        payload.pop("postUrls", None)
    return payload


def run_post_scraper_actor(payload: dict) -> list[dict]:
    """Run the actor synchronously; owner token first, shared rotation fallback."""
    actor_id = _actor_id()
    settings = get_settings()
    token = (settings.apify_post_scraper_token or "").strip()
    if token:
        try:
            items = _run_with_key(actor_id, token, payload)
            logger.info(f"[PostScraper:{actor_id}] owner token succeeded ({len(items)} items)")
            return items
        except ApifyRetryableError as e:
            # 401/402/403/407/429/5xx/network — try the shared rotation next.
            logger.warning(
                f"[PostScraper:{actor_id}] owner token failed (HTTP {e.status_code}); "
                f"falling back to shared APIFY_API_KEY rotation"
            )
        except ApifyError as e:
            # 400 invalid input — retrying other keys cannot help; surface it.
            logger.warning(f"[PostScraper:{actor_id}] owner token rejected input (HTTP {e.status_code})")
            raise
    return _run_sync_actor(actor_id, payload)


# ── Normalisation ────────────────────────────────────────────────────────

def _cap(value, limit: int) -> str:
    if not value:
        return ""
    text = str(value)
    return text if len(text) <= limit else text[:limit]


def _int_or_none(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_actor_record(record: dict) -> dict:
    """Map one actor dataset record to a profile_posts DB row."""
    rec = record or {}
    return {
        "profile_url": _cap(rec.get("sourceUrl") or "", URL_MAX),
        "post_url": _cap(rec.get("postUrl") or "", URL_MAX),
        "post_id": _cap(rec.get("postId") or "", 255),
        "post_text": _cap(rec.get("text") or "", POST_TEXT_MAX),
        "author_name": _cap(rec.get("authorName") or "", 255),
        "author_url": _cap(rec.get("authorUrl") or "", URL_MAX),
        "author_headline": _cap(rec.get("authorHeadline") or "", AUTHOR_TEXT_MAX),
        "author_type": rec.get("authorType") if rec.get("authorType") in ("person", "company", "unknown") else "unknown",
        "posted_at": (rec.get("datePosted") or None),
        "num_likes": _int_or_none(rec.get("numLikes")),
        "num_comments": _int_or_none(rec.get("numComments")),
        "num_shares": _int_or_none(rec.get("numShares")),
        "hashtags": rec.get("hashtags") or [],
        "mentions": rec.get("mentions") or [],
        "media": rec.get("media") or [],
        "extraction_status": rec.get("extractionStatus")
        if rec.get("extractionStatus") in ("success", "partial", "failed", "unresolved")
        else "unresolved",
        "extraction_method": _cap(rec.get("extractionMethod") or "", 255),
        "source_url": _cap(rec.get("sourceUrl") or "", URL_MAX),
        "extracted_at": (rec.get("extractedAt") or None),
        "raw": record or {},
    }


def summarize_records(records: list[dict]) -> dict:
    """Per-profile counts used for the API response + honest block reporting."""
    per_profile: dict[str, dict] = {}
    totals = {"discovered": 0, "success": 0, "partial": 0, "failed": 0, "unresolved": 0}
    for rec in records:
        status = rec.get("extraction_status") or "unresolved"
        if status in totals:
            totals[status] += 1
        totals["discovered"] += 1
        profile = rec.get("profile_url") or rec.get("source_url") or ""
        bucket = per_profile.setdefault(profile, {"discovered": 0, "success": 0, "partial": 0, "failed": 0, "unresolved": 0})
        bucket["discovered"] += 1
        if status in bucket:
            bucket[status] += 1
    return {"totals": totals, "per_profile": per_profile}


# ── Persistence (profile_posts table) ───────────────────────────────────

def _fetch_existing_post_urls(supabase, user_id: str) -> set[str]:
    """Post urls already stored for this user (skip re-inserting them)."""
    try:
        resp = supabase.table("profile_posts").select("post_url").eq("user_id", user_id).neq("post_url", "").execute()
        return {(r.get("post_url") or "").split("?")[0].rstrip("/") for r in (resp.data or [])}
    except Exception as e:
        logger.warning(f"[PostScraper] existing-post lookup failed: {e}")
        return set()


def store_profile_posts_sync(
    supabase,
    user_id: str,
    *,
    profile_urls: list[str] | None = None,
    post_urls: list[str] | None = None,
    max_posts_per_profile: int = 10,
    include_engagement: bool = True,
    include_author: bool = True,
    lead_id: str | None = None,
) -> dict:
    """Run the actor and persist records; returns saved rows + honest stats."""
    payload = build_actor_payload(
        profile_urls=profile_urls,
        post_urls=post_urls,
        max_posts_per_profile=max_posts_per_profile,
        include_engagement=include_engagement,
        include_author=include_author,
    )
    raw_records = run_post_scraper_actor(payload)

    rows = []
    for rec in raw_records:
        row = normalize_actor_record(rec)
        row["user_id"] = user_id
        if lead_id:
            row["lead_id"] = lead_id
        rows.append(row)

    existing = _fetch_existing_post_urls(supabase, user_id)
    new_rows = []
    skipped = 0
    for row in rows:
        key = (row.get("post_url") or "").split("?")[0].rstrip("/")
        if key and key in existing:
            skipped += 1
            continue
        if key:
            existing.add(key)
        new_rows.append(row)

    saved = []
    if new_rows:
        # Batch insert; fall back row-by-row on partial failures (house style).
        try:
            resp = supabase.table("profile_posts").insert(new_rows).execute()
            saved = [r for r in (resp.data or [])]
        except Exception as e:
            logger.warning(f"[PostScraper] bulk insert failed ({e}); per-row fallback")
            for row in new_rows:
                try:
                    r = supabase.table("profile_posts").insert(row).execute()
                    if r.data:
                        saved.append(r.data[0])
                except Exception as row_err:
                    logger.warning(f"[PostScraper] row insert skipped: {row_err}")

    return {
        "saved": saved,
        "saved_count": len(saved),
        "actor_records": len(raw_records),
        "skipped_existing": skipped,
        "stats": summarize_records(rows),
    }


def list_profile_posts(
    supabase,
    user_id: str,
    *,
    lead_id: str | None = None,
    profile_url: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """Paginated profile_posts for a user (filters: lead_id, profile_url)."""
    page = max(1, int(page))
    per_page = max(1, min(int(per_page), 100))
    offset = (page - 1) * per_page

    def _apply_filters(q):
        q = q.eq("user_id", user_id)
        if lead_id:
            q = q.eq("lead_id", lead_id)
        if profile_url:
            q = q.eq("profile_url", profile_url)
        return q

    count_resp = _apply_filters(supabase.table("profile_posts").select("id", count="exact")).execute()
    total = count_resp.count or 0

    data_resp = (
        _apply_filters(supabase.table("profile_posts").select("*"))
        .order("created_at", desc=True)
        .range(offset, offset + per_page - 1)
        .execute()
    )
    items = data_resp.data or []
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total else 0,
    }
