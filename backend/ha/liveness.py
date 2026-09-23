"""Post liveness: never deliver a deleted (or already-filled) LinkedIn post.

Discovery goes through Google's index of LinkedIn, and Google keeps a post
for days-weeks after its author deletes it (buyers often delete once they've
hired). Every accepted lead is therefore checked against LinkedIn's public
EMBED endpoint before it counts toward the user's N:

    https://www.linkedin.com/embed/feed/update/urn:li:<kind>:<id>

Verified live (logged-out): a live post returns 200 + post markup (~20 KB,
including the full text); a deleted / nonexistent post returns 404. The
public /posts/ page is ambiguous for deleted posts (it bounces to a sign-up
wall), so it is only a fallback.

Fail-OPEN on uncertainty: a LinkedIn throttle (429 / 999), a 5xx or a
timeout yields "unknown" and the lead is kept - a throttle must never wipe
out a whole search. Only a definitive 404/410 or a not-found page is "dead".
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

from discovery.base import activity_urn
from enrich import _HEADERS, _clean, extract_post_text

log = logging.getLogger(__name__)

EMBED_URL = "https://www.linkedin.com/embed/feed/update/urn:li:{kind}:{id}"

_POST_MARKUP = re.compile(r"attributed-text-segment-list__content|feed-shared-update|share-update-card",
                          re.IGNORECASE)
_EMBED_TEXT = re.compile(
    r'<p[^>]+attributed-text-segment-list__content[^>]*>(.*?)</p>', re.IGNORECASE | re.DOTALL)
_DEAD_MARKERS = ("post not found", "page not found", "deleted or removed",
                 "this content isn't available", "this content isn’t available",
                 "this post is unavailable", "this post cannot be displayed")

# The ask is already closed - the post exists but the lead is worthless.
_FILLED = re.compile(
    r"\b(?:contract|project|job|role|position|gig)\s+(?:has\s+been\s+|is\s+|now\s+)*(?:awarded|filled|closed)\b"
    r"|\bupdate\s*[:\-–]\s*(?:filled|closed|hired|awarded|found)"
    r"|\b(?:position|role|vacancy|opening)\s+(?:has\s+been|is|now)\s+(?:filled|closed)\b"
    r"|\bno\s+longer\s+(?:looking|hiring|accepting|needed)\b"
    r"|\bwe(?:'ve|\s+have)?\s+(?:found|hired|filled)\s+(?:someone|the\s+right|our|a\s+great)\b"
    r"|\b(?:found|hired)\s+(?:someone|the\s+right\s+(?:person|fit|candidate))\b"
    r"|\bthanks?\s+(?:you\s+)?(?:everyone|all)[^.!\n]{0,40}\b(?:found|hired|filled|closed)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class PostCheck:
    status: str  # alive | dead | unknown
    text: str | None = None


def is_filled(text: str | None) -> bool:
    """True when the post says the need is already met ("CONTRACT NOW AWARDED")."""
    return bool(_FILLED.search(text or ""))


def _embed_text(html: str) -> str | None:
    parts = [_clean(p) for p in _EMBED_TEXT.findall(html or "")]
    parts = [p for p in parts if len(p) >= 20]
    if parts:
        return max(parts, key=len)[:4000]
    return extract_post_text(html)


def _get(url: str, timeout: float):
    import httpx

    return httpx.get(url, headers=_HEADERS, timeout=timeout, follow_redirects=True)


def check_post(url: str, *, timeout: float = 8.0, retries: int = 1) -> PostCheck:
    """alive / dead / unknown for a LinkedIn post URL (never raises)."""
    urn = activity_urn(url)
    if urn is None:
        return PostCheck("unknown")
    kind, pid = urn
    kinds = [kind] + (["activity"] if kind != "activity" else [])
    for attempt in range(retries + 1):
        throttled = False
        for k in kinds:
            try:
                resp = _get(EMBED_URL.format(kind=k, id=pid), timeout)
            except Exception as exc:  # noqa: BLE001 - network trouble is "unknown"
                log.debug("liveness fetch failed for %s: %s", url, exc)
                throttled = True
                break
            body = resp.text or ""
            if resp.status_code == 200 and _POST_MARKUP.search(body):
                return PostCheck("alive", _embed_text(body))
            if resp.status_code in (404, 410) or (
                    resp.status_code == 200 and any(m in body.lower() for m in _DEAD_MARKERS)):
                continue  # try the next URN kind before declaring it dead
            throttled = True  # 429 / 999 / 5xx / odd 200: cannot tell
            break
        else:
            return PostCheck("dead")
        if throttled and attempt < retries:
            time.sleep(1.0 + attempt)
    return PostCheck("unknown")
