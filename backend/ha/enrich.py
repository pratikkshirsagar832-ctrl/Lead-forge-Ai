"""Full-post text enrichment — snippet-first, fail-closed.

Google returns only a ~150-300 char snippet per LinkedIn post, often cut off
before the ask becomes clear. For the FEW candidates whose snippet verdict is
borderline (or that the classifier flagged `needs_full_text`), the engine
fetches the public post page once and re-classifies with the full text.

Public LinkedIn post pages (linkedin.com/posts/...) are served to logged-out
visitors with the post body in JSON-LD (`articleBody`) and in the
og:description meta tag. Extraction takes the LONGEST candidate.

Fail-closed: any network error, block page, login wall or parse miss returns
None and the engine simply keeps the snippet verdict. Enrichment never breaks
or slows a search beyond its own small timeout.
"""
from __future__ import annotations

import html
import json
import logging
import re
from typing import Callable

log = logging.getLogger(__name__)

FetchFn = Callable[[str], "str | None"]

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_META_DESC = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:description|description)["\'][^>]*>', re.IGNORECASE)
_CONTENT_ATTR = re.compile(r'content=(["\'])(.*?)\1', re.IGNORECASE | re.DOTALL)
_LD_JSON = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL)
_COMMENTARY = re.compile(
    r'<p[^>]+(?:attributed-text-segment-list__content|main-feed-activity-card__commentary)[^>]*>(.*?)</p>',
    re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
# Login walls / error pages carry generic copy instead of the post body.
_BLOCK_MARKERS = ("sign in to view", "join linkedin", "authwall", "page not found",
                  "this content isn't available", "security verification")


def _clean(text: str) -> str:
    return _WS.sub(" ", html.unescape(_TAGS.sub(" ", text or ""))).strip()


def _ld_bodies(node) -> list[str]:
    """articleBody / text fields anywhere in a JSON-LD blob."""
    out: list[str] = []
    if isinstance(node, dict):
        for key in ("articleBody", "text", "description"):
            val = node.get(key)
            if isinstance(val, str) and val.strip():
                out.append(val)
        for val in node.values():
            if isinstance(val, (dict, list)):
                out.extend(_ld_bodies(val))
    elif isinstance(node, list):
        for item in node:
            out.extend(_ld_bodies(item))
    return out


def extract_post_text(page_html: str) -> str | None:
    """Best (longest) post body from a public LinkedIn post page, or None."""
    if not page_html:
        return None
    candidates: list[str] = []
    for block in _LD_JSON.findall(page_html):
        try:
            candidates.extend(_ld_bodies(json.loads(block.strip())))
        except (json.JSONDecodeError, ValueError):
            continue
    for tag in _META_DESC.findall(page_html):
        m = _CONTENT_ATTR.search(tag)
        if m:
            candidates.append(m.group(2))
    candidates.extend(_COMMENTARY.findall(page_html))
    cleaned = [_clean(c) for c in candidates]
    cleaned = [c for c in cleaned if len(c) >= 40
               and not any(b in c.lower() for b in _BLOCK_MARKERS)]
    if not cleaned:
        return None
    return max(cleaned, key=len)[:4000]


def _fetch_html(url: str, timeout: float) -> str | None:
    """Plain HTTP GET (no browser). Scrapling's Fetcher when installed (better
    TLS/browser fingerprint), else httpx. None on any failure."""
    try:
        from scrapling.fetchers import Fetcher  # type: ignore[import-not-found]

        page = Fetcher.get(url, timeout=timeout, stealthy_headers=True, follow_redirects=True)
        status = getattr(page, "status", 200)
        body = getattr(page, "html_content", None) or getattr(page, "body", b"")
        if isinstance(body, bytes):
            body = body.decode("utf-8", "replace")
        return body if status == 200 and body else None
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 - fall through to httpx
        log.debug("Scrapling fetch failed for %s: %s", url, exc)
    try:
        import httpx

        resp = httpx.get(url, headers=_HEADERS, timeout=timeout, follow_redirects=True)
        if resp.status_code != 200:
            return None
        return resp.text
    except Exception as exc:  # noqa: BLE001 - fail-closed
        log.debug("Full-text fetch failed for %s: %s", url, exc)
        return None


def fetch_full_text(url: str, *, timeout: float = 8.0) -> str | None:
    """Full post text for a LinkedIn post URL, or None (fail-closed)."""
    if not url or "linkedin.com/" not in url.lower():
        return None
    text = extract_post_text(_fetch_html(url, timeout) or "")
    if text:
        log.info("Full-text enrichment fetched %d chars for %s", len(text), url[:120])
    return text
