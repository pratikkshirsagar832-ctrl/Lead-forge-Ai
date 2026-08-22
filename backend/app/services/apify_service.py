"""
Hyperclients — Apify LinkedIn Scraper Service

Primary actor: scrapeforge~linkedin-all-in-one
  - post-search mode   : broad LinkedIn post discovery by keywords (boolean OR supported)
  - profile-detail mode: enrich authors (headline, company, location, connections)

Legacy actors kept for optional extras:
  - harvestapi~linkedin-profile-scraper : email enrichment (all-in-one has no emails)
  - shahidirfan~linkedin-job-scraper    : job postings (hiring leads)

Supports multiple API keys with automatic failover: if a call fails with a
retryable error (quota exhausted, auth, server error), the next configured key
is tried.
"""

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

ALL_IN_ONE_ACTOR = "scrapeforge~linkedin-all-in-one"
PROFILE_SCRAPER_ACTOR = "harvestapi~linkedin-profile-scraper"
JOB_SCRAPER_ACTOR = "shahidirfan~linkedin-job-scraper"

SYNC_TIMEOUT_SECONDS = 300

RETRYABLE_STATUS_CODES = {401, 402, 403, 407, 429, 500, 502, 503, 504}


class ApifyError(Exception):
    """Raised when all configured Apify keys fail."""

    def __init__(self, message: str, status_code: int = None):
        super().__init__(message)
        self.status_code = status_code


class ApifyRetryableError(ApifyError):
    """Raised for errors where a different API key might succeed."""


def _get_api_keys() -> list[str]:
    settings = get_settings()
    keys = []
    for key in (settings.apify_api_key, settings.apify_api_key_2):
        if key:
            keys.append(key)
    if not keys:
        raise ApifyError("APIFY_API_KEY is not configured")
    return keys


def _run_sync_actor(actor_id: str, payload: dict) -> list[dict]:
    """Run an actor synchronously and return dataset items, with key failover."""
    last_error: ApifyError | None = None
    for key in _get_api_keys():
        try:
            return _run_with_key(actor_id, key, payload)
        except ApifyRetryableError as e:
            logger.warning(f"[Apify:{actor_id}] Key failed (HTTP {e.status_code}): {e}. Trying next key...")
            last_error = e
        except ApifyError:
            raise

    raise last_error or ApifyError("All Apify API keys failed")


def _run_with_key(actor_id: str, key: str, payload: dict) -> list[dict]:
    url = (
        f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"
        f"?token={key}&timeout={SYNC_TIMEOUT_SECONDS}"
    )
    headers = {"Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=SYNC_TIMEOUT_SECONDS + 20) as client:
            response = client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException:
        raise ApifyRetryableError("Apify request timed out")
    except httpx.HTTPError as e:
        raise ApifyRetryableError(f"Apify network error: {e}")

    if response.status_code == 400:
        raise ApifyError(f"Invalid Apify input: {response.text[:500]}", 400)
    if response.status_code in RETRYABLE_STATUS_CODES:
        raise ApifyRetryableError(f"{response.text[:500]}", response.status_code)
    if response.status_code != 201:
        raise ApifyRetryableError(f"Unexpected status {response.status_code}: {response.text[:500]}", response.status_code)

    return response.json()


def run_post_search(
    search_queries: str | list[str],
    max_posts: int = 100,
    posted_limit: str = "week",
) -> list[dict]:
    """Broad LinkedIn post discovery via scrapeforge/linkedin-all-in-one.

    The actor takes ONE search string; multiple phrases are merged into a
    single boolean OR query so one actor run covers all discovery phrases.
    Returns raw post items:
      { postId, url, content, postedAt, postedTimestamp,
        author: {id, name, url, avatar},
        engagement: {likes, comments, shares, reactions}, ... }
    """
    if isinstance(search_queries, str):
        search_queries = [search_queries]
    clean = [q.strip() for q in search_queries if q and q.strip()]
    if not clean:
        clean = ["marketing"]
    # Boolean OR across discovery phrases — LinkedIn matches any of them.
    combined = " OR ".join(clean[:8])

    payload = {
        "mode": "post-search",
        "search": combined,
        "postedLimit": posted_limit if posted_limit in ("24h", "week", "month") else "month",
        "sortBy": "date",
        "maxPosts": max(10, min(max_posts, 500)),
    }
    return _run_sync_actor(ALL_IN_ONE_ACTOR, payload)


def fetch_profile_details(
    profile_urls: list[str],
    depth: str = "basic",
) -> list[dict]:
    """Enrich authors via profile-detail mode: headline, current company,
    location, follower/connection counts. One batched call per run.

    Returns profile items:
      { publicIdentifier, url, name, headline, about, location:{linkedinText},
        currentPosition:[{companyName}], followerCount, connectionsCount, ... }
    """
    urls = [u.strip() for u in (profile_urls or []) if u and u.strip()]
    if not urls:
        return []
    payload = {
        "mode": "profile-detail",
        "profileUrls": urls[:100],
        "profileDepth": depth if depth in ("basic", "full") else "basic",
        "maxPosts": len(urls[:100]),
    }
    return _run_sync_actor(ALL_IN_ONE_ACTOR, payload)


def enrich_profiles(profile_urls: list[str], max_items: int = 50) -> list[dict]:
    """Email enrichment via legacy harvestapi actor (all-in-one exposes no emails)."""
    if not profile_urls:
        return []
    payload = {
        "profileScraperMode": "Profile details + email search",
        "urls": profile_urls[:max_items],
        "maxItems": min(len(profile_urls), max_items),
    }
    return _run_sync_actor(PROFILE_SCRAPER_ACTOR, payload)


def run_job_search(
    query: str,
    location: str = "United States",
    time_range: str = "7d",
    max_jobs: int = 50,
    work_types: list[str] = None,
) -> list[dict]:
    """Search LinkedIn job postings using shahidirfan/linkedin-job-scraper."""
    payload = {
        "query": query,
        "location": location,
        "timeRange": time_range,
        "maxJobs": min(max_jobs, 1000),
        "collectOnly": False,
        "maxConcurrency": 5,
    }
    return _run_sync_actor(JOB_SCRAPER_ACTOR, payload)


def filter_jobs_by_work_type(jobs: list[dict], allowed_types: list[str]) -> list[dict]:
    """Filter jobs to only include allowed work types (Remote, Part-time, Contract)."""
    allowed = set(t.lower() for t in allowed_types)
    filtered = []
    for job in jobs:
        work_type = (job.get("workType") or "").lower()
        if any(t in work_type for t in allowed):
            filtered.append(job)
    return filtered
