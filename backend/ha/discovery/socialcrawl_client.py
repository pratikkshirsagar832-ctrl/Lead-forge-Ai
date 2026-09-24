"""SocialCrawl discovery client - the LinkedIn post search provider.

    GET https://www.socialcrawl.dev/v1/linkedin/search/posts
        ?query=<phrase>&sort_by=date_posted&date_posted=past_week&limit=25
    x-api-key: sc_...

What it returns (measured 2026-09): newest-first public LinkedIn posts with the
FULL post text, an exact `published_at`, the author (display_name, username),
engagement counts and a free relevance score (`computed.relevance.p`). Posts
are typically hours old, and the text is complete, so no post-page fetch is
needed for classification.

Provider trade-offs (not bugs):
* It reads a public search index of LinkedIn, not LinkedIn's own search, so
  coverage is best-effort; a precise phrase can legitimately return 0 posts.
* One QUOTED buyer phrase per query works best ("can anyone recommend"
  accountant). OR-packed phrases return unrelated posts, so the engine uses
  the "single" query style with this provider.
* Negatives (-"we offer") are honoured, but then the relevance score is often
  absent; a missing score never drops a post.
* Billing: 1 credit per 5 posts returned; cache hits and empty results free.
Every candidate still goes through the DeepSeek classifier upstream.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from .keypool import KeyPool, PoolKey
from .base import (
    DiscoveryClient,
    DiscoveryConfigError,
    DiscoveryError,
    RawPost,
    SearchBatchResult,
    canonical_post_url,
    parse_posted_at,
    posted_at_from_url,
)

log = logging.getLogger(__name__)

SEARCH_PATH = "/v1/linkedin/search/posts"
MAX_LIMIT = 200


def date_filter_for(since: datetime, now: datetime | None = None) -> str:
    """SocialCrawl `date_posted` covering everything posted at/after `since`.

    Rounds UP (never narrower than the requested window); the engine's
    per-post date gate enforces the exact boundary."""
    now = now or datetime.now(UTC)
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    age = now - since
    if age <= timedelta(hours=24, minutes=30):
        return "past_24h"
    if age <= timedelta(days=7, minutes=30):
        return "past_week"
    return "past_month"


def _error_message(body: Any) -> str:
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        return str(err.get("message") or err.get("code") or "")
    return str(err or "")


def _is_credit_error(status: int, message: str) -> bool:
    # Real response (2026-09): HTTP 402, error.type INSUFFICIENT_CREDITS,
    # "Your account has 23 credits remaining. This endpoint requires 40..."
    low = message.lower()
    return status == 402 or "credit" in low or "insufficient" in low or "balance" in low


def check_balance(api_key: str, *, base_url: str = "https://www.socialcrawl.dev",
                  timeout: float = 30.0) -> dict[str, Any]:
    """Live balance of one key via a FREE dry-run call (0 credits).

    Returns {"ok": bool, "credits_remaining": int | None, "status": "active" |
    "exhausted" | "invalid" | "error", "error": str}."""
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}{SEARCH_PATH}",
                         params={"query": "balance check", "limit": 1, "dry_run": 1},
                         headers={"x-api-key": api_key, "accept": "application/json"}, timeout=timeout)
        body = resp.json() if resp.content else {}
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "credits_remaining": None, "status": "error", "error": str(exc)[:200]}
    message = _error_message(body)
    if resp.status_code in (401, 403):
        return {"ok": False, "credits_remaining": None, "status": "invalid", "error": message or "invalid API key"}
    remaining = _int_or_none(body.get("credits_remaining")) if isinstance(body, dict) else None
    if _is_credit_error(resp.status_code, message) or remaining == 0:
        return {"ok": True, "credits_remaining": remaining or 0, "status": "exhausted", "error": message}
    if resp.status_code != 200:
        return {"ok": False, "credits_remaining": remaining, "status": "error", "error": message or f"HTTP {resp.status_code}"}
    return {"ok": True, "credits_remaining": remaining, "status": "active", "error": ""}


def _int_or_none(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


class SocialCrawlDiscoveryClient(DiscoveryClient):
    name = "socialcrawl"

    def __init__(
        self,
        api_key: str | list[str] | KeyPool,
        *,
        base_url: str = "https://www.socialcrawl.dev",
        results_per_query: int = 25,
        min_relevance: float = 0.2,
        timeout_seconds: float = 60.0,
        max_workers: int = 8,
    ) -> None:
        if isinstance(api_key, KeyPool):
            pool = api_key
        else:
            pool = KeyPool.from_keys([api_key] if isinstance(api_key, str) else list(api_key or []))
        if not len(pool):
            raise DiscoveryConfigError("SOCIALCRAWL_API_KEY is required")
        self.pool = pool
        self.base_url = base_url.rstrip("/")
        self.default_results_per_query = max(1, min(int(results_per_query or 25), MAX_LIMIT))
        self.min_relevance = float(min_relevance or 0.0)
        self.timeout_seconds = timeout_seconds
        self.max_workers = max(1, int(max_workers))
        self.calls = 0
        self.credits_used = 0
        self.credits_remaining: int | None = None
        self.relevance_dropped = 0
        self._lock = threading.Lock()

    @property
    def config_errors(self) -> list[str]:
        return [] if len(self.pool) else ["SOCIALCRAWL_API_KEY is not set - LinkedIn discovery cannot run"]

    # ------------------------------------------------------------------ http
    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        """One search request with KEY ROTATION: a key that is out of credits
        (or rejected) is taken out of the pool and the SAME request is retried
        on the next key, so a search never stops because one key ran dry."""
        tried: set[str] = set()
        while True:
            k: PoolKey | None = self.pool.acquire(tried)
            if k is None:
                if self.pool.revive():  # a topped-up key came back
                    tried.clear()
                    continue
                statuses = {p.status for p in self.pool.keys}
                if statuses and statuses <= {"invalid", "disabled"}:
                    raise DiscoveryConfigError("SocialCrawl rejected every API key - check the keys in /admin/keys")
                raise DiscoveryError("All SocialCrawl API keys are out of credits - add or top up a key in /admin/keys")
            tried.add(k.key)
            with self._lock:
                self.calls += 1
            try:
                resp = httpx.get(f"{self.base_url}{SEARCH_PATH}", params=params,
                                 headers={"x-api-key": k.key, "accept": "application/json"},
                                 timeout=self.timeout_seconds)
            except httpx.HTTPError as exc:
                raise DiscoveryError(f"SocialCrawl request failed: {exc}") from exc
            try:
                body = resp.json()
            except ValueError:
                body = {}
            message = _error_message(body)
            if resp.status_code in (401, 403):
                log.warning("SocialCrawl key ...%s rejected (HTTP %s) - switching key", k.hint, resp.status_code)
                self.pool.invalid(k, message or f"HTTP {resp.status_code}")
                continue
            if _is_credit_error(resp.status_code, message):
                log.warning("SocialCrawl key ...%s is out of credits - switching key", k.hint)
                left = _int_or_none(body.get("credits_remaining")) if isinstance(body, dict) else None
                self.pool.exhausted(k, message or "out of credits", remaining=left)
                continue
            if resp.status_code != 200 or not isinstance(body, dict) or body.get("success") is False:
                raise DiscoveryError(f"SocialCrawl request failed (HTTP {resp.status_code}): {message or str(body)[:200]}")
            used = int(body.get("credits_used") or 0)
            remaining = _int_or_none(body.get("credits_remaining"))
            with self._lock:
                self.credits_used += used
                if remaining is not None:
                    self.credits_remaining = remaining
            self.pool.report(k, used, remaining)
            return body

    # --------------------------------------------------------------- mapping
    def _map_item(self, item: Any, query: str) -> RawPost | None:
        if not isinstance(item, dict):
            return None
        post = item.get("post") if isinstance(item.get("post"), dict) else item
        url = str(post.get("url") or "").strip()
        content = post.get("content") if isinstance(post.get("content"), dict) else {}
        text = str(content.get("text") or post.get("text") or "").strip()
        if not url or "linkedin.com" not in url.lower() or not text:
            return None
        relevance = ((item.get("computed") or {}).get("relevance") or {}) if isinstance(item.get("computed"), dict) else {}
        p = relevance.get("p") if isinstance(relevance, dict) else None
        if isinstance(p, (int, float)) and p < self.min_relevance:
            with self._lock:
                self.relevance_dropped += 1
            return None
        author = post.get("author") if isinstance(post.get("author"), dict) else {}
        username = str(author.get("username") or "").strip().strip("/")
        profile = ""
        if username:
            profile = username if username.startswith("http") else f"https://www.linkedin.com/in/{username}"
        engagement = post.get("engagement") if isinstance(post.get("engagement"), dict) else {}
        posted = parse_posted_at(post.get("published_at")) or posted_at_from_url(url)
        return RawPost(
            post_url=url,
            text=text,
            author_name=(str(author.get("display_name") or author.get("name") or "").strip() or None),
            author_profile_url=profile or None,
            posted_at=posted,
            query_used=query,
            provider=self.name,
            num_comments=_int_or_none(engagement.get("comments")),
            text_source="full_post",
        )

    def _fetch(self, query: str, date_posted: str, limit: int) -> tuple[list[RawPost], int]:
        body = self._get({"query": query, "sort_by": "date_posted", "date_posted": date_posted, "limit": limit})
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        items = data.get("items") or []
        posts = [p for p in (self._map_item(i, query) for i in items) if p is not None]
        log.info("SocialCrawl %r %s -> %d items, %d kept (%s credits)", query[:160], date_posted,
                 len(items), len(posts), body.get("credits_used"))
        return posts, len(items)

    # ---------------------------------------------------------------- search
    def search_posts(
        self,
        queries: list[str],
        since: datetime,
        *,
        results_per_query: int | None = None,
        pages: int = 1,
    ) -> SearchBatchResult:
        queries = [q for q in (queries or []) if q and q.strip()]
        if not queries:
            return SearchBatchResult()
        if since.tzinfo is None:
            since = since.replace(tzinfo=UTC)
        limit = max(1, min(int(results_per_query or self.default_results_per_query), MAX_LIMIT))
        date_posted = date_filter_for(since)

        def _run(query: str) -> tuple[str, list[RawPost], int, str | None]:
            try:
                posts, seen = self._fetch(query, date_posted, limit)
                return query, posts, seen, None
            except DiscoveryConfigError:
                raise
            except DiscoveryError as exc:
                return query, [], 0, str(exc)
            except Exception as exc:  # noqa: BLE001 - one query must not kill the round
                return query, [], 0, f"query {query!r} failed: {exc}"

        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(queries))) as pool:
            results = list(pool.map(_run, queries))

        errors = [err for _q, _p, _s, err in results if err]
        for err in errors:
            log.warning("%s", err)
        if errors and len(errors) == len(results):
            # Every request failed: provider outage / no credits, never "no posts exist".
            first = errors[0]
            if "credit" in first.lower():
                raise DiscoveryError(first)
            raise DiscoveryError(f"All LinkedIn search requests failed this round: {first}")

        seen_keys: set[str] = set()
        unique: list[RawPost] = []
        raw_rows = 0
        for _q, posts, seen, _err in results:
            raw_rows += seen
            for p in posts:
                key = canonical_post_url(p.post_url)
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    unique.append(p)
        return SearchBatchResult(
            posts=unique,
            queries_used=queries,
            provider_errors=errors,
            raw_rows_seen=raw_rows,
        )
