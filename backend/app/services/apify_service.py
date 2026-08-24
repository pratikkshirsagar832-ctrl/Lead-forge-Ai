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
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    """Broad LinkedIn post discovery.

    Primary: harvestapi/linkedin-post-search — native searchQueries array,
    author headline included in every post (critical for AI qualification),
    optional authorKeywords to target decision-makers. Fast (~10s).

    Fallback: scrapeforge/linkedin-all-in-one — phrases packed into ≤60-char
    OR-chunks, parallel runs. Slower but works when harvestapi is unavailable.

    Returns raw post items (both formats normalized):
      { postId, url, content, postedAt, postedTimestamp,
        author: {id, name, url, info/headline, avatar},
        engagement: {likes, comments, shares, reactions}, ... }
    """
    if isinstance(search_queries, str):
        search_queries = [search_queries]
    clean = [q.strip() for q in search_queries if q and q.strip()][:12]
    if not clean:
        clean = ["marketing"]

    try:
        items = run_harvest_post_search(clean, max_posts, posted_limit)
        logger.info(f"[Apify] harvestapi post-search returned {len(items)} posts")
        return items
    except Exception as e:
        logger.warning(f"[Apify] harvestapi post-search failed, falling back to scrapeforge: {e}")

    chunks = _chunk_search_phrases(clean)
    per_chunk = max(20, max_posts // len(chunks))
    logger.info(f"[Apify] post-search chunks ({len(chunks)}): {chunks}")

    items: list[dict] = []
    errors: list[Exception] = []
    with ThreadPoolExecutor(max_workers=min(len(chunks), 3)) as pool:
        futures = {
            pool.submit(_run_post_search_chunk, c, per_chunk, posted_limit): c
            for c in chunks
        }
        for fut in as_completed(futures):
            try:
                items.extend(fut.result())
            except Exception as e:
                logger.warning(f"[Apify] post-search chunk failed ({futures[fut]!r}): {e}")
                errors.append(e)

    # Partial results beat none — only raise if EVERYTHING failed.
    if not items and errors:
        raise errors[0]

    seen_ids: set[str] = set()
    unique: list[dict] = []
    for item in items:
        pid = item.get("postId") or item.get("url")
        if not pid or pid in seen_ids:
            continue
        seen_ids.add(pid)
        unique.append(item)
    return unique


HARVEST_POST_SEARCH_ACTOR = "harvestapi~linkedin-post-search"


def run_harvest_post_search(
    search_queries: list[str],
    max_posts: int = 100,
    posted_limit: str = "week",
) -> list[dict]:
    """Search LinkedIn posts via harvestapi/linkedin-post-search.

    Author headline (`author.info`) is included per post — no separate
    profile enrichment required. No authorKeywords filter: the AI
    WHO-IS-THE-SUBJECT rule rejects freelancers/sellers at scoring time,
    and a keyword filter silently returns 0 results on longer phrases.
    """
    per_query = max(5, max_posts // max(len(search_queries), 1))
    payload = {
        "searchQueries": search_queries[:12],
        "maxPosts": min(per_query, 50),
        "postedLimit": posted_limit if posted_limit in ("1h", "24h", "week", "month") else "month",
        "sortBy": "date",
        "profileScraperMode": "short",
        "scrapeReactions": False,
        "postNestedReactions": False,
        "scrapeComments": False,
        "postNestedComments": False,
    }
    return _run_sync_actor(HARVEST_POST_SEARCH_ACTOR, payload)


def _run_post_search_chunk(search: str, max_posts: int, posted_limit: str) -> list[dict]:
    payload = {
        "mode": "post-search",
        "search": search,
        "postedLimit": posted_limit if posted_limit in ("24h", "week", "month") else "month",
        "sortBy": "date",
        "maxPosts": max(10, min(max_posts, 500)),
    }
    return _run_sync_actor(ALL_IN_ONE_ACTOR, payload)


def _chunk_search_phrases(phrases: list[str], max_chars: int = 60) -> list[str]:
    """Greedily pack phrases into boolean-OR chunks within LinkedIn's query limit."""
    chunks: list[str] = []
    current = ""
    for p in phrases:
        p = p[:max_chars] if len(p) > max_chars else p
        candidate = f"{current} OR {p}" if current else p
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = p
    if current:
        chunks.append(current)
    return chunks


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
    """Email enrichment via legacy harvestapi actor (all-in-one exposes no emails).

    Note: rows may be error stubs ({status: 404, error: ...}) when the
    upstream provider fails — callers must ignore rows without emails.
    """
    if not profile_urls:
        return []
    payload = {
        "profileScraperMode": "Profile details + email search ($10 per 1k)",
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
