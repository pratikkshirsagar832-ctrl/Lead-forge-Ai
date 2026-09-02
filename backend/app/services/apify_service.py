"""
Hyperclients — Apify LinkedIn Scraper Service

Primary actor: scrapeforge~linkedin-all-in-one
  - post-search mode   : broad LinkedIn post discovery by keywords (boolean OR supported)
  - profile-detail mode: enrich authors (headline, company, location, connections)

Legacy actors kept for optional extras:
  - harvestapi~linkedin-profile-scraper : email enrichment (all-in-one has no emails)
  - shahidirfan~linkedin-job-scraper    : job postings (hiring leads)

Supports up to 24 API keys with SMART AUTOMATIC ROTATION:
  - When a key's credits run out (402/403) or it fails (401/429/5xx), the next
    key is tried automatically.
  - A rotating cursor means parallel calls start from different positions, so
    keys are spread evenly and dead keys are skipped via a cooldown cache.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

ALL_IN_ONE_ACTOR = "scrapeforge~linkedin-all-in-one"
PROFILE_SCRAPER_ACTOR = "harvestapi~linkedin-profile-scraper"
JOB_SCRAPER_ACTOR = "shahidirfan~linkedin-job-scraper"

SYNC_TIMEOUT_SECONDS = 300

RETRYABLE_STATUS_CODES = {401, 402, 403, 407, 429, 500, 502, 503, 504}

# Dead-key cooldown: a key that hit a quota/auth failure is skipped for this
# many seconds before being retried (free Apify plans reset monthly).
KEY_COOLDOWN_SECONDS = 600

# Permanently revoked keys (user-or-token-not-found / 401) are removed from
# rotation entirely — a revoked token never recovers, so retrying it only
# wastes time and keeps other keys from being tried sooner.
_KEY_PERMA_BLACKLIST: set[str] = set()


def _key_blacklisted(key: str) -> bool:
    return key in _KEY_PERMA_BLACKLIST


def _mark_key_blacklisted(key: str) -> None:
    with _key_lock:
        _KEY_PERMA_BLACKLIST.add(key)
        _key_cooldown.pop(key, None)
    logger.error(f"[Apify] Key {key[-6:]} permanently blacklisted (revoked/invalid token)")


class ApifyError(Exception):
    """Raised when all configured Apify keys fail."""

    def __init__(self, message: str, status_code: int = None):
        super().__init__(message)
        self.status_code = status_code


class ApifyRetryableError(ApifyError):
    """Raised for errors where a different API key might succeed."""


# ── Key rotation state ────────────────────────────────────────────────────
_key_lock = threading.Lock()
_key_cursor = 0
_key_cooldown: dict[str, float] = {}  # key -> timestamp when it can be retried


def _is_key_in_cooldown(key: str) -> bool:
    until = _key_cooldown.get(key, 0.0)
    return time.time() < until


def _mark_key_cooldown(key: str) -> None:
    with _key_lock:
        _key_cooldown[key] = time.time() + KEY_COOLDOWN_SECONDS
    logger.warning(f"[Apify] Key {key[-6:]} marked dead for {KEY_COOLDOWN_SECONDS}s")


def _ordered_keys() -> list[str]:
    """Rotating view of configured keys: the PRIMARY key (APIFY_API_KEY)
    is ALWAYS tried first, then the rest rotate from the cursor. Healthy
    (non-cooldown) keys come before cooldown keys; revoked keys are skipped."""
    keys = _get_api_keys()
    if not keys:
        return []
    primary = None
    try:
        primary = get_settings().apify_api_key or None
    except Exception:
        pass

    global _key_cursor
    with _key_lock:
        start = _key_cursor % len(keys)
        _key_cursor += 1
    rotated = keys[start:] + keys[:start]
    if primary and primary in rotated:
        rotated.remove(primary)
        rotated.insert(0, primary)
    # healthy first, cooldown keys at the end (so they are only tried as last resort)
    live = [k for k in rotated if not _key_blacklisted(k)]
    healthy = [k for k in live if not _is_key_in_cooldown(k)]
    cooling = [k for k in live if _is_key_in_cooldown(k)]
    return healthy + cooling


def _get_api_keys() -> list[str]:
    settings = get_settings()
    keys = settings.apify_keys
    if not keys:
        raise ApifyError("APIFY_API_KEY is not configured")
    return keys


def check_apify_keys_health() -> dict:
    """Validate every configured key with a cheap GET /v2/users/me call.

    Returns {configured, valid, invalid, keys: [{last4, valid, detail}]}.
    Also blacklists revoked keys so rotation skips them immediately.
    """
    try:
        keys = _get_api_keys()
    except ApifyError as e:
        return {"configured": 0, "valid": 0, "invalid": 0, "keys": [], "error": str(e)}

    result = []
    valid = 0
    for key in keys:
        last4 = key[-6:] if len(key) > 6 else key
        try:
            resp = httpx.get(
                "https://api.apify.com/v2/users/me",
                params={"token": key},
                timeout=15,
            )
            if resp.status_code == 200 and resp.json().get("data", {}).get("id"):
                valid += 1
                result.append({"last4": last4, "valid": True, "detail": "ok"})
            else:
                if resp.status_code == 401:
                    _mark_key_blacklisted(key)
                result.append({"last4": last4, "valid": False, "detail": resp.text[:120]})
        except Exception as e:
            result.append({"last4": last4, "valid": False, "detail": str(e)[:120]})

    return {
        "configured": len(keys),
        "valid": valid,
        "invalid": len(keys) - valid,
        "keys": result,
    }


def _run_sync_actor(actor_id: str, payload: dict) -> list[dict]:
    """Run an actor synchronously and return dataset items, with key failover.

    Every key attempt is logged with its last-4 digits + HTTP status so a
    failed search is fully diagnosable from logs. On 402 (credits) the key
    goes into cooldown and the NEXT key is tried immediately.
    """
    last_error: ApifyError | None = None
    stat: dict[str, int] = {}
    attempted = 0
    for key in _ordered_keys():
        attempted += 1
        try:
            items = _run_with_key(actor_id, key, payload)
            logger.info(f"[Apify:{actor_id}] Key {key[-6:]} succeeded ({len(items)} items)")
            return items
        except ApifyRetryableError as e:
            label = str(e.status_code) if e.status_code else "net"
            stat[label] = stat.get(label, 0) + 1
            logger.warning(
                f"[Apify:{actor_id}] Key {key[-6:]} failed (HTTP {label}) — "
                f"rotating to next key ({attempted}/{len(_get_api_keys())} tried)"
            )
            last_error = e
            if e.status_code == 401 and "user-or-token-not-found" in str(e):
                # Token revoked/deleted — permanently remove from rotation.
                _mark_key_blacklisted(key)
            elif e.status_code == 403 and "platform-feature-disabled" in str(e):
                # Apify disabled the paid-actor feature on this account
                # (free-account farm restriction) — it will never recover.
                _mark_key_blacklisted(key)
            elif e.status_code in (401, 402, 403, 429):
                _mark_key_cooldown(key)
        except ApifyError:
            raise

    revoked = stat.get("401", 0)
    no_credits = stat.get("402", 0)
    feature_disabled = stat.get("403", 0)
    net_err = stat.get("net", 0)
    breakdown = " ".join(f"{k}={v}" for k, v in sorted(stat.items()))
    logger.error(f"[Apify:{actor_id}] ALL {attempted} keys failed — statuses: {breakdown}")

    parts = []
    if no_credits:
        parts.append(f"{no_credits} out of credits")
    if feature_disabled:
        parts.append(f"{feature_disabled} feature-disabled (paid actor blocked by Apify)")
    if revoked:
        parts.append(f"{revoked} revoked/invalid")
    if net_err:
        parts.append(f"{net_err} network errors")
    detail = "; ".join(parts) if parts else breakdown or "unknown"
    raise ApifyError(
        f"All {attempted} Apify keys failed: {detail}. "
        "Top up credits at console.apify.com/billing and use accounts that can "
        "run paid actors.",
        last_error.status_code if last_error else 500,
    )


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
    if response.status_code not in (200, 201):
        raise ApifyRetryableError(f"Unexpected status {response.status_code}: {response.text[:500]}", response.status_code)

    data = response.json()
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("items", data.get("data", []))
    return []


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
    with ThreadPoolExecutor(max_workers=min(len(chunks), 4)) as pool:
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
        pid = item.get("postId") or item.get("id") or item.get("url") or item.get("linkedinUrl")
        if not pid or pid in seen_ids:
            continue
        seen_ids.add(pid)
        unique.append(item)
    return unique


HARVEST_POST_SEARCH_ACTOR = "harvestapi~linkedin-post-search"


def run_lane_search(
    search_queries: list[str],
    max_posts: int = 50,
    posted_limit: str = "month",
    buyer_mode: bool = False,
) -> list[dict]:
    """ONE harvestapi actor run — designed to be fired N times IN PARALLEL.

    Each call grabs its own key from the rotating cursor (healthy keys
    first, cooldown keys last resort) with full failover to other keys.

    CREDIT BUDGET: harvestapi's maxPosts is PER QUERY, so a lane's raw
    total = len(queries) × maxPosts. Lanes are capped at 4 queries and
    15 posts each → ≤60 raw records per lane (was 12 queries × 50 = 600).

    buyer_mode: target genuine BUYERS — append boolean NOT operators that
    exclude seller language ("I offer", "available for", "my services",
    "portfolio") and restrict authors to decision-maker roles via
    authorKeywords (Founder/CEO/Owner/Director/Manager) so freelancer
    sellers never reach the AI scorer.
    """
    queries = [q.strip() for q in search_queries if q and q.strip()][:4]
    if not queries:
        queries = ["marketing"]
    if buyer_mode:
        # LinkedIn boolean: NOT excludes posts containing those exact phrases.
        # Keep queries under the 5-boolean-operator / 500-char limit: append
        # at most 3 NOT clauses to the two most promising queries.
        for i, q in enumerate(queries):
            if i >= 2:
                break
            nots = ' NOT "I offer" NOT "available for" NOT "my services"'
            if len(q) + len(nots) < 490:
                queries[i] = q + nots
    payload = {
        "searchQueries": queries,
        "maxPosts": max(10, min(max_posts, 15)),
        "postedLimit": posted_limit if posted_limit in ("1h", "24h", "week", "month") else "month",
        "sortBy": "date",
        "profileScraperMode": "main",
        "scrapeReactions": False,
        "postNestedReactions": False,
        "scrapeComments": False,
        "postNestedComments": False,
    }
    if buyer_mode:
        # Only surface posts from decision makers / companies — sellers
        # (freelancers) usually have "Freelance X" or service headlines.
        payload["authorKeywords"] = "Founder,CEO,Owner,Director,Manager,VP,Head,President,Co-founder,Managing Director"
    return _run_sync_actor(HARVEST_POST_SEARCH_ACTOR, payload)


def dedupe_post_items(items: list[dict]) -> list[dict]:
    """Dedupe raw post items by post id / url across lanes.
    Handles both harvestapi (`id`/`linkedinUrl`) and scrapeforge
    (`postId`/`url`) formats."""
    seen: set[str] = set()
    unique: list[dict] = []
    for it in items:
        pid = it.get("postId") or it.get("id") or it.get("url") or it.get("linkedinUrl")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        unique.append(it)
    return unique


def run_harvest_post_search(
    search_queries: list[str],
    max_posts: int = 100,
    posted_limit: str = "week",
) -> list[dict]:
    """Search LinkedIn posts via harvestapi/linkedin-post-search.

    Queries are split into groups and each group runs IN PARALLEL using a
    DIFFERENT Apify API key (key 0 → group 0, key 1 → group 1, ...). This
    cuts wall time ~Nx while naturally rotating through the 24 configured
    keys — if one key is out of credits, only its group fails and the rest
    still return posts.

    profileScraperMode="main" returns FULL author data per post:
      author.location.countryCode (US/GB/IN...), author.currentPosition
      (company), author.info (headline). Used to filter to English-speaking
      countries and give the AI company context.
    """
    queries = [q.strip() for q in search_queries if q and q.strip()][:12]
    if not queries:
        queries = ["marketing"]

    # Assign each group a DIFFERENT starting key via the rotating cursor.
    # Only HEALTHY keys (not in cooldown) are used for parallel groups —
    # dead keys are skipped automatically until their cooldown expires.
    # Concurrency kept at 6 for reliability — too many simultaneous runs
    # trips Apify free-tier rate limits and causes failures.
    n_groups = min(6, len(queries))
    all_rotated = _ordered_keys()
    healthy_keys = [k for k in all_rotated if not _is_key_in_cooldown(k)]
    group_keys = healthy_keys[:n_groups]
    if not group_keys:
        # Every key is in cooldown — last resort: use the rotation anyway.
        group_keys = all_rotated[:n_groups]
    n_actual = len(group_keys)
    if n_actual == 0:
        raise ApifyError("APIFY_API_KEY is not configured")
    n_groups = min(n_groups, n_actual)
    groups: list[list[str]] = [[] for _ in range(n_groups)]
    for idx, q in enumerate(queries):
        groups[idx % n_groups].append(q)

    per_query = max(5, max_posts // max(len(queries), 1))

    def _run_group(group_idx: int, group_queries: list[str]) -> list[dict]:
        key = group_keys[group_idx]
        payload = {
            "searchQueries": group_queries,
            "maxPosts": min(per_query, 50),
            "postedLimit": posted_limit if posted_limit in ("1h", "24h", "week", "month") else "month",
            "sortBy": "date",
            "profileScraperMode": "main",
            "scrapeReactions": False,
            "postNestedReactions": False,
            "scrapeComments": False,
            "postNestedComments": False,
        }
        try:
            return _run_with_key(HARVEST_POST_SEARCH_ACTOR, key, payload)
        except ApifyRetryableError as e:
            logger.warning(f"[Apify] harvest group {group_idx} failed on key {key[-6:]} ({e}); retrying with failover...")
            # fall back to the standard failover (other keys) for this group
            return _run_sync_actor(HARVEST_POST_SEARCH_ACTOR, payload)
        except ApifyError:
            raise

    items: list[dict] = []
    errors: list[Exception] = []
    logger.info(f"[Apify] harvest parallel groups: {n_groups} (queries per group: {[len(g) for g in groups]})")
    with ThreadPoolExecutor(max_workers=n_groups) as pool:
        futures = [pool.submit(_run_group, i, g) for i, g in enumerate(groups) if g]
        for fut in as_completed(futures):
            try:
                items.extend(fut.result())
            except Exception as e:
                logger.warning(f"[Apify] harvest group failed: {e}")
                errors.append(e)

    if not items and errors:
        raise errors[0]

    # Dedupe by post id / url across groups.
    # harvestapi uses `id`/`linkedinUrl`; scrapeforge uses `postId`/`url`.
    seen: set[str] = set()
    unique: list[dict] = []
    for it in items:
        pid = it.get("postId") or it.get("id") or it.get("url") or it.get("linkedinUrl")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        unique.append(it)
    return unique


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
    """Filter jobs to only include allowed work types (Remote, Part-time, Contract).
    Jobs without a workType field are KEPT — they may still be relevant."""
    allowed = set(t.lower() for t in allowed_types)
    filtered = []
    for job in jobs:
        work_type = (job.get("workType") or "").lower()
        # Keep jobs with no workType data (can't verify, might be relevant)
        if not work_type or any(t in work_type for t in allowed):
            filtered.append(job)
    return filtered
