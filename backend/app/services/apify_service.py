"""
Hyperclients — Apify LinkedIn Scraper Service

Actor: harvestapi~linkedin-post-search (keyword post-search discovery).
  - run_lane_search: ONE actor run for the LinkedIn buyer-discovery engine;
    Boolean-NOT negative signals strip seller / job-seeker language up front.

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


def _is_perm_feature_disabled(err_text: str) -> bool:
    """Return True only for a PERMANENT platform-feature-disabled 403.

    Apify returns error type 'platform-feature-disabled' in two distinct cases:
      1. Monthly usage hard limit exceeded  -> RECOVERABLE (billing renewal).
      2. Free-account paid-actor restriction -> also potentially recoverable
         once the account is upgraded/funded.
    Neither is a revoked token, so neither should be permanently blacklisted.
    Only an unambiguous permanent rejection (explicit message) is blacklisted.
    """
    low = (err_text or "").lower()
    # Explicitly recoverable limits → never permanent.
    if "usage hard limit" in low or "monthly usage" in low or "credits" in low or "billing" in low:
        return False
    # Any other platform-feature-disabled is treated as temporary (cooldown)
    # rather than a permanent blacklist — blacklisting kills working keys.
    return False


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
    """Round-robin view of configured keys (fair spread across accounts so no
    single free-tier budget exhausts). Every call advances the cursor, so
    sequential lane runs land on DIFFERENT healthy keys. Healthy (non-cooldown)
    keys come before cooldown keys; revoked keys are skipped."""
    keys = _get_api_keys()
    if not keys:
        return []
    # A single key should always be tried (avoids an empty ordering).
    if len(keys) == 1:
        return keys

    global _key_cursor
    with _key_lock:
        start = _key_cursor % len(keys)
        _key_cursor += 1
    rotated = keys[start:] + keys[:start]
    # healthy first, cooldown keys at the end (last resort), revoked skipped
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
                # Token revoked/deleted — never recovers. Remove from rotation.
                _mark_key_blacklisted(key)
            elif _is_perm_feature_disabled(str(e)):
                # A 403 that can never recover. The API returns the error type
                # 'platform-feature-disabled' BOTH for a permanently disabled
                # paid-actor feature AND for a temporary "Monthly usage hard
                # limit exceeded" (which DOES recover on billing renewal). Only
                # blacklist when the message is permanent.
                _mark_key_blacklisted(key)
            elif e.status_code in (401, 402, 403, 429):
                # Credits/feature/rate-limit limit — all recoverable → cooldown.
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


HARVEST_POST_SEARCH_ACTOR = "harvestapi~linkedin-post-search"

# Seller/job-seeker language to EXCLUDE at discovery time using LinkedIn Boolean
# NOT search. LinkedIn supports up to 5 boolean operators (AND/OR/NOT) and 500
# chars per query. NOT is applied after quotes/parentheses, so we phrase intent
# in quotes and exclude seller framing with NOT. Uppercase operators required.
_SELLER_NOT_TERMS = [
    '"i offer"', '"we offer"', '"we provide"', '"our services"', '"dm me"', '"dm us"',
    '"available for"', '"open to work"', '"looking for clients"', '"taking clients"',
    '"my portfolio"', '"we help"', '"book a call"', '"get in touch"', '"we specialize in"',
    '"we are a leading"', '"we deliver"', '"we take care of"', '"our agency"',
]
MAX_NOT_TERMS = 4  # keep within the 5-operator cap and 500-char limit


def _build_negative_query(intent: str, terms: list[str]) -> str | None:
    """Build a Boolean query: "intent phrase" NOT term1 NOT term2 ...

    Falls back to None if the query would exceed LinkedIn's 500-char limit.
    """
    base = f'"{intent.strip()}"'
    remaining = terms[:MAX_NOT_TERMS]
    for term in remaining:
        if len(base) + len(term) + 5 > 500:
            break
        base = f"{base} NOT {term}"
    return base


def add_negative_signal_queries(queries: list[str], max_per_intent: int = 2) -> list[str]:
    """Emit Boolean NOT-filtered variants to strip seller/job-seeker posts at
    discovery time — BEFORE any AI spend.

    LinkedIn officially supports NOT (uppercase), quotes, and parentheses (max
    5 operators / 500 chars). These are emitted as ADDITIONAL queries (never
    replacements of the core intent line) so a false-zero on a NOT variant can
    never void discovery. The AI classifier remains the authoritative gate.
    """
    out: list[str] = []
    for q in queries[:max_per_intent]:
        neg = _build_negative_query(q, _SELLER_NOT_TERMS)
        if neg:
            out.append(neg)
    return out


def run_lane_search(
    search_queries: list[str],
    max_posts: int = 15,
    posted_limit: str = "month",
    use_negative_signals: bool = False,
) -> list[dict]:
    """ONE harvestapi actor run — designed to be fired N times IN PARALLEL.

    Each call grabs its own key from the rotating cursor (healthy keys
    first, cooldown keys last resort) with full failover to other keys.

    CREDIT BUDGET: harvestapi's maxPosts is PER QUERY, so a lane's raw
    total = len(queries) × maxPosts. Lanes are capped at 4 queries and
    15 posts each → ≤60 raw records per lane.

    use_negative_signals: append Boolean-NOT high-precision variants (see
    add_negative_signal_queries) that exclude seller/job-seeker language at
    discovery time. These are EXTRA queries, never replacements, so the intent
    line is safe even if a NOT variant returns nothing.
    """
    queries = [q.strip() for q in search_queries if q and q.strip()][:4]
    if not queries:
        queries = ["marketing"]
    if use_negative_signals:
        queries = queries + add_negative_signal_queries(queries)
    payload = {
        "searchQueries": queries,
        "maxPosts": max(10, min(max_posts, 15)),
        "postedLimit": posted_limit if posted_limit in ("1h", "24h", "week", "month", "3months", "6months", "year") else "month",
        "sortBy": "date",
        "profileScraperMode": "main",
        "scrapeReactions": False,
        "postNestedReactions": False,
        "scrapeComments": False,
        "postNestedComments": False,
    }
    return _run_sync_actor(HARVEST_POST_SEARCH_ACTOR, payload)


