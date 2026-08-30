"""Bright Data LinkedIn Scraper API client with multi-key rotation.

Replaces Apify completely. Supports:
  - Multiple API keys with rotating cursor
  - Primary key pinning (always tried first)
  - Cooldown cache (600s) for failed keys
  - Permanent blacklist for revoked keys
  - 429 rate limit handling with retry
  - Live key health check

Flow:
  1. Google/DDG search for LinkedIn post/profile URLs matching keywords
  2. Bright Data Profile scraper → author info + recent posts
  3. Bright Data Post scraper → detailed post data (fallback)
  4. Returns structured items compatible with existing qualification pipeline

Dataset IDs:
  - Profiles: gd_l1viktl72bvl7bjuj0
  - Posts:    gd_lyy3tktm25m4avu764
  - Companies: gd_l1vikfnt1wgvvqz95w
"""

import logging
import re
import threading
import time
from typing import Any

import httpx

from ..config import get_settings

logger = logging.getLogger("leadforge.brightdata")

# ---------------------------------------------------------------------------
# Bright Data constants
# ---------------------------------------------------------------------------
BRIGHTDATA_BASE = "https://api.brightdata.com/datasets/v3"
DATASET_PROFILES = "gd_l1viktl72bvl7bjuj0"
DATASET_POSTS = "gd_lyy3tktm25m4avu764"
DATASET_COMPANIES = "gd_l1vikfnt1wgvvqz95w"

# Sync endpoint: up to 20 URLs, 2-minute timeout
SYNC_MAX_URLS = 20
SYNC_TIMEOUT = 120

# Retry / error handling
MAX_RETRIES = 2
RETRY_DELAY = 3

# Key cooldown: 600s after 429/rate-limit
KEY_COOLDOWN_SECONDS = 600

# ---------------------------------------------------------------------------
# Key rotation state (mirrors Apify's _key_lock / _key_cursor / etc.)
# ---------------------------------------------------------------------------
_key_lock = threading.Lock()
_key_cursor: int = 0
_key_cooldown: dict[str, float] = {}   # key → unix timestamp when cooldown expires
_KEY_PERMA_BLACKLIST: set[str] = set()


def _key_blacklisted(key: str) -> bool:
    return key in _KEY_PERMA_BLACKLIST


def _mark_key_blacklisted(key: str) -> None:
    _KEY_PERMA_BLACKLIST.add(key)
    logger.warning(f"[BrightData] Key {key[-8:]} permanently blacklisted (revoked)")


def _is_key_in_cooldown(key: str) -> bool:
    exp = _key_cooldown.get(key, 0)
    if exp and time.time() >= exp:
        # Cooldown expired
        _key_cooldown.pop(key, None)
        return False
    return bool(exp)


def _mark_key_cooldown(key: str) -> None:
    _key_cooldown[key] = time.time() + KEY_COOLDOWN_SECONDS
    logger.warning(f"[BrightData] Key {key[-8:]} cooldown for {KEY_COOLDOWN_SECONDS}s")


# ---------------------------------------------------------------------------
# API key helpers
# ---------------------------------------------------------------------------
def _get_api_keys() -> list[str]:
    """Return ALL configured Bright Data API keys."""
    settings = get_settings()
    return getattr(settings, "_bright_data_keys", []) or []


def _ordered_keys() -> list[str]:
    """Return keys ordered: primary first, then rotation cursor, healthy before cooldown."""
    keys = _get_api_keys()
    if not keys:
        return []

    # Pin primary key first (always tried first)
    primary = None
    try:
        primary = get_settings().bright_data_api_key or None
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

    # Filter: healthy first, then cooldown as last resort
    live = [k for k in rotated if not _key_blacklisted(k)]
    healthy = [k for k in live if not _is_key_in_cooldown(k)]
    cooling = [k for k in live if _is_key_in_cooldown(k)]
    return healthy + cooling


# ---------------------------------------------------------------------------
# Headers for a given key
# ---------------------------------------------------------------------------
def _headers(key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Low-level Bright Data API calls with key failover
# ---------------------------------------------------------------------------
class BrightDataError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class BrightDataRetryableError(BrightDataError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message, status_code)


def _run_with_key(dataset_id: str, key: str, inputs: list[dict], timeout: int = SYNC_TIMEOUT) -> list[dict]:
    """Execute a single Bright Data scrape with ONE key. Raises on failure."""
    url = f"{BRIGHTDATA_BASE}/scrape"
    params = {"dataset_id": dataset_id, "format": "json", "include_errors": "true"}
    payload = {"input": inputs}

    try:
        r = httpx.post(url, params=params, headers=_headers(key), json=payload, timeout=timeout)
    except httpx.TimeoutException as e:
        raise BrightDataRetryableError(f"BrightData timeout: {e}", status_code=None) from e
    except httpx.ConnectError as e:
        raise BrightDataRetryableError(f"BrightData network error: {e}", status_code=None) from e

    if r.status_code == 200:
        data = r.json()
        if isinstance(data, list):
            return data
        return [data]

    # Read error body
    try:
        body = r.json()
        err_msg = body.get("error", body.get("message", r.text[:200]))
        err_code = body.get("error_code", "")
    except Exception:
        err_msg = r.text[:200]
        err_code = ""

    # 429 rate limit → retryable, cooldown
    if r.status_code == 429:
        wait = int(r.headers.get("Retry-After", KEY_COOLDOWN_SECONDS))
        raise BrightDataRetryableError(
            f"Rate limited: {err_msg}",
            status_code=429,
        )

    # 401/403 auth errors → permanent blacklist
    if r.status_code in (401, 403):
        detail = str(err_msg).lower()
        if any(kw in detail for kw in ("unauthorized", "invalid", "expired", "token", "not active")):
            raise BrightDataRetryableError(
                f"Auth failed ({r.status_code}): {err_msg}",
                status_code=r.status_code,
            )
        # Other 401/403 (temporary) → retryable
        raise BrightDataRetryableError(
            f"Auth/temp error ({r.status_code}): {err_msg}",
            status_code=r.status_code,
        )

    # 5xx server errors → retryable
    if r.status_code >= 500:
        raise BrightDataRetryableError(
            f"Server error ({r.status_code}): {err_msg}",
            status_code=r.status_code,
        )

    # Other errors → non-retryable
    raise BrightDataError(
        f"BrightData error ({r.status_code}): {err_msg}",
        status_code=r.status_code,
    )


def _run_sync(dataset_id: str, inputs: list[dict]) -> list[dict]:
    """Run a Bright Data scrape with full key rotation and failover.

    Every key attempt is logged with its last-4 digits + HTTP status.
    On 429 (rate limit) the key goes into cooldown and the NEXT key is tried.
    """
    last_error: BrightDataError | None = None
    stat: dict[str, int] = {}
    attempted = 0

    for key in _ordered_keys():
        attempted += 1
        try:
            items = _run_with_key(dataset_id, key, inputs)
            logger.info(f"[BrightData] Key ...{key[-6:]} succeeded ({len(items)} items)")
            return items
        except BrightDataRetryableError as e:
            label = str(e.status_code) if e.status_code else "net"
            stat[label] = stat.get(label, 0) + 1
            logger.warning(
                f"[BrightData] Key ...{key[-6:]} failed (HTTP {label}) — "
                f"rotating to next key ({attempted}/{len(_get_api_keys())} tried)"
            )
            last_error = e

            if e.status_code in (401, 403):
                _mark_key_blacklisted(key)
            elif e.status_code == 429:
                _mark_key_cooldown(key)
            elif e.status_code is None:
                _mark_key_cooldown(key)
        except BrightDataError:
            raise

    # All keys exhausted
    rate_limited = stat.get("429", 0)
    auth_failed = stat.get("401", 0) + stat.get("403", 0)
    net_err = stat.get("net", 0)
    breakdown = " ".join(f"{k}={v}" for k, v in sorted(stat.items()))
    logger.error(f"[BrightData] ALL {attempted} keys failed — statuses: {breakdown}")

    parts = []
    if rate_limited:
        parts.append(f"{rate_limited} rate-limited (cooldown)")
    if auth_failed:
        parts.append(f"{auth_failed} auth-failed (blacklisted)")
    if net_err:
        parts.append(f"{net_err} network errors")
    detail = "; ".join(parts) if parts else breakdown or "unknown"
    raise BrightDataError(
        f"All {attempted} Bright Data keys failed: {detail}. "
        "Add more keys or wait for cooldown.",
        last_error.status_code if last_error else 500,
    )


# ---------------------------------------------------------------------------
# Google/DDG search → LinkedIn URL extraction
# ---------------------------------------------------------------------------
_LINKEDIN_POST_RE = re.compile(
    r"https?://(?:www\.|[\w-]+\.)?linkedin\.com/(?:posts|feed/update)/[^\s\"'<>]+"
)
_LINKEDIN_PROFILE_RE = re.compile(
    r"https?://(?:www\.|[\w-]+\.)?linkedin\.com/in/[A-Za-z0-9_%-]+"
)
_LINKEDIN_COMPANY_RE = re.compile(
    r"https?://(?:www\.|[\w-]+\.)?linkedin\.com/company/[A-Za-z0-9_%-]+"
)


def _extract_urls_from_html(html: str) -> list[str]:
    """Extract unique LinkedIn post/profile URLs from raw HTML/text."""
    urls: list[str] = []
    seen: set[str] = set()
    for pattern in (_LINKEDIN_POST_RE, _LINKEDIN_PROFILE_RE, _LINKEDIN_COMPANY_RE):
        for m in pattern.finditer(html):
            url = m.group(0).rstrip(".,;:!?)>")
            if url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


def _search_duckduckgo_sync(query: str) -> list[str]:
    """Search DuckDuckGo HTML → LinkedIn URLs."""
    try:
        r = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            },
            timeout=15,
            follow_redirects=True,
        )
        if r.status_code == 200:
            return _extract_urls_from_html(r.text)
    except Exception as e:
        logger.warning(f"[BrightData] DDG search failed: {e}")
    return []


# ---------------------------------------------------------------------------
# High-level: search + scrape pipeline
# ---------------------------------------------------------------------------
def _build_search_queries(services: list[str], location: str | None = None) -> list[str]:
    """Build Google/DDG search queries from service + location."""
    queries: list[str] = []
    for svc in services[:6]:
        base = f'"{svc}" LinkedIn post site:linkedin.com'
        if location and location.lower() not in ("global", "worldwide", ""):
            base += f' "{location}"'
        queries.append(base)
    for svc in services[:4]:
        base = f'"{svc}" LinkedIn profile site:linkedin.com/in'
        if location and location.lower() not in ("global", "worldwide", ""):
            base += f' "{location}"'
        queries.append(base)
    return queries


def discover_linkedin_urls(
    services: list[str],
    location: str | None = None,
    max_urls: int = 60,
) -> dict[str, list[str]]:
    """Search DDG for LinkedIn URLs matching service queries.

    Returns {"profiles": [...], "posts": [...], "companies": [...]}
    """
    queries = _build_search_queries(services, location)
    all_profiles: list[str] = []
    all_posts: list[str] = []
    all_companies: list[str] = []
    seen: set[str] = set()

    for q in queries:
        urls = _search_duckduckgo_sync(q)
        for u in urls:
            if u in seen:
                continue
            seen.add(u)
            if "/posts/" in u or "/feed/update/" in u:
                all_posts.append(u)
            elif "/in/" in u:
                all_profiles.append(u)
            elif "/company/" in u:
                all_companies.append(u)
        if len(all_profiles) + len(all_posts) >= max_urls:
            break

    all_profiles = all_profiles[:max_urls]
    all_posts = all_posts[:max_urls]
    all_companies = all_companies[:20]

    logger.info(
        f"[BrightData] URL discovery: {len(all_profiles)} profiles, "
        f"{len(all_posts)} posts, {len(all_companies)} companies"
    )
    return {
        "profiles": all_profiles,
        "posts": all_posts,
        "companies": all_companies,
    }


def scrape_profiles(urls: list[str]) -> list[dict]:
    """Scrape LinkedIn profiles via Bright Data. Returns structured profile data."""
    if not urls:
        return []

    results: list[dict] = []
    for i in range(0, len(urls), SYNC_MAX_URLS):
        batch = urls[i : i + SYNC_MAX_URLS]
        inputs = [{"url": u} for u in batch]
        try:
            items = _run_sync(DATASET_PROFILES, inputs)
            for item in items:
                if isinstance(item, dict) and "error" not in item and "name" in item:
                    results.append(item)
                elif isinstance(item, dict) and "error" in item:
                    logger.debug(f"[BrightData] profile error: {item.get('error')}")
        except BrightDataError as e:
            logger.error(f"[BrightData] scrape_profiles failed: {e}")
    return results


def scrape_posts(urls: list[str]) -> list[dict]:
    """Scrape LinkedIn posts via Bright Data. Returns structured post data."""
    if not urls:
        return []

    results: list[dict] = []
    for i in range(0, len(urls), SYNC_MAX_URLS):
        batch = urls[i : i + SYNC_MAX_URLS]
        inputs = [{"url": u} for u in batch]
        try:
            items = _run_sync(DATASET_POSTS, inputs)
            for item in items:
                if isinstance(item, dict) and "error" not in item:
                    results.append(item)
        except BrightDataError as e:
            logger.error(f"[BrightData] scrape_posts failed: {e}")
    return results


# ---------------------------------------------------------------------------
# Unified scrape function (drop-in replacement for Apify scrape_leads)
# ---------------------------------------------------------------------------
def scrape_leads(
    services: list[str],
    location: str | None = None,
    max_results: int = 20,
    posted_limit: str = "month",
) -> list[dict]:
    """Bright Data replacement for Apify's harvestapi~linkedin-post-search.

    Flow:
      1. Search DDG for LinkedIn profile + post URLs
      2. Scrape profiles → get author info + recent posts
      3. Scrape posts directly (if needed to fill quota)
      4. Normalize to harvestapi-compatible format

    Returns list of dicts with keys matching harvestapi output:
      url, text, author_name, author_url, author_headline,
      numLikes, numComments, postedAt, etc.
    """
    keys = _get_api_keys()
    if not keys:
        raise BrightDataError("BRIGHT_DATA_API_KEY not configured")

    logger.info(
        f"[BrightData] scrape_leads(services={services}, location={location}, "
        f"max_results={max_results})"
    )

    # Step 1: Discover LinkedIn URLs
    discovered = discover_linkedin_urls(services, location, max_urls=max(max_results * 3, 60))

    all_items: list[dict] = []

    # Step 2: Scrape profiles → get posts + author info
    profile_urls = discovered["profiles"]
    profiles: list[dict] = []
    if profile_urls:
        profiles = scrape_profiles(profile_urls)
        for prof in profiles:
            author_name = prof.get("name", "")
            author_url = prof.get("url", "")
            author_headline = prof.get("position", "") or prof.get("about", "")
            city = prof.get("city", "")
            country = prof.get("country_code", "")

            posts = prof.get("posts", [])
            for post in posts:
                item = {
                    "url": post.get("link", ""),
                    "text": post.get("attribution", "") or post.get("title", ""),
                    "title": post.get("title", ""),
                    "author_name": author_name,
                    "author_url": author_url,
                    "author_headline": author_headline,
                    "author_city": city,
                    "author_country": country,
                    "numLikes": _parse_engagement(post.get("interaction", ""), "likes"),
                    "numComments": _parse_engagement(post.get("interaction", ""), "comments"),
                    "postedAt": post.get("created_at", ""),
                    "postId": post.get("id", ""),
                    "source": "brightdata_profile",
                }
                if item["url"]:
                    all_items.append(item)

    # Step 3: Scrape posts directly (if more needed)
    post_urls = discovered["posts"]
    direct_posts: list[dict] = []
    if post_urls and len(all_items) < max_results:
        direct_posts = scrape_posts(post_urls[:SYNC_MAX_URLS])
        for post in direct_posts:
            item = {
                "url": post.get("url", ""),
                "text": post.get("post_text", "") or post.get("title", ""),
                "title": post.get("title", ""),
                "author_name": post.get("user_id", ""),
                "author_url": post.get("use_url", ""),
                "author_headline": post.get("headline", ""),
                "numLikes": post.get("num_likes", 0),
                "numComments": post.get("num_comments", 0),
                "postedAt": post.get("date_posted", ""),
                "postId": post.get("id", ""),
                "hashtags": post.get("hashtags", []),
                "source": "brightdata_post",
            }
            if item["url"]:
                all_items.append(item)

    # Step 4: Deduplicate by URL
    seen_urls: set[str] = set()
    unique_items: list[dict] = []
    for item in all_items:
        url = item.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_items.append(item)

    logger.info(
        f"[BrightData] scraped {len(unique_items)} unique items "
        f"(from {len(profiles)} profiles, {len(direct_posts)} direct posts)"
    )
    return unique_items[:max_results]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_engagement(interaction: str, field: str) -> int:
    """Parse '2,53 - 141 Comments' → likes=253, comments=141."""
    try:
        parts = re.split(r"\s*-\s*", interaction)
        if field == "likes" and parts:
            return int(parts[0].replace(",", "").strip())
        if field == "comments" and len(parts) > 1:
            m = re.search(r"(\d+)", parts[1])
            if m:
                return int(m.group(1))
    except (ValueError, IndexError):
        pass
    return 0


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
def check_brightdata_health() -> dict:
    """Validate all configured Bright Data API keys."""
    keys = _get_api_keys()
    if not keys:
        return {
            "configured": 0,
            "valid": 0,
            "invalid": 0,
            "keys": [],
            "detail": "no keys configured",
        }

    results: list[dict] = []
    valid_count = 0
    invalid_count = 0

    for key in keys:
        last4 = key[-4:] if len(key) >= 4 else key
        try:
            # Test with a lightweight profile scrape
            r = httpx.post(
                f"{BRIGHTDATA_BASE}/scrape",
                params={"dataset_id": DATASET_PROFILES, "format": "json", "include_errors": "true"},
                headers=_headers(key),
                json={"input": [{"url": "https://www.linkedin.com/in/satyanadella"}]},
                timeout=30,
            )
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and len(data) > 0 and "name" in data[0]:
                    status = "ok"
                    valid_count += 1
                else:
                    status = "unexpected_response"
                    invalid_count += 1
            elif r.status_code in (401, 403):
                status = "revoked"
                invalid_count += 1
                _mark_key_blacklisted(key)
            elif r.status_code == 429:
                status = "rate_limited"
                invalid_count += 1
            else:
                status = f"HTTP {r.status_code}"
                invalid_count += 1
        except Exception as e:
            status = str(e)[:50]
            invalid_count += 1

        results.append({"last4": last4, "status": status})

    return {
        "configured": len(keys),
        "valid": valid_count,
        "invalid": invalid_count,
        "keys": results,
        "detail": f"{valid_count}/{len(keys)} valid",
    }
