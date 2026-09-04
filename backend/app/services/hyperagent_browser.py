"""
Hyperclients — HyperAgent Browser Client (LinkedIn-specific)

The "hands" of the agent. Uses the vendored `browser-use` (Python) library to
drive a real headless/headed Chromium over Chrome DevTools Protocol (CDP), so we
can browse LinkedIn logged-in and read the actual content that is invisible to
guests (post search, people search, feed). This is the replacement for the
removed Apify actor: instead of paying an outsourcer for a JSON dump, the agent
opens LinkedIn itself and extracts real lead candidates.

Every method returns "raw items" in the shape the LinkedIn engine's
`_parse_candidate()` expects:
    {author: {url, name, info/headline, currentPosition, avatar, location},
     content, postUrl/linkedinUrl/url, postedAt, engagement}

`browser_use` is imported lazily so the FastAPI app and its test-suite load fine
even on machines where the heavy browser dependency is not installed; a
`MissingBrowserUseError` is raised only when the agent actually tries to browse.

Authentication is cookie-based: the user logs into LinkedIn once in their own
browser, exports the cookies with the Cookie-Editor Chrome extension, and pastes
the JSON into the config (LINKEDIN_COOKIES). The client wraps them into Playwright
storage_state and injects them via CDP, so the browser appears logged-in — no
credentials are stored. With no cookies the client degrades to guest mode —
which works for Jobs + company pages but NOT for post/people search (authwall).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)


class HyperAgentError(Exception):
    """Base error for the HyperAgent browser client."""


class MissingBrowserUseError(HyperAgentError):
    """Raised when `browser_use` is not importable (browser deps absent)."""


def _browser_use():
    """Import browser_use lazily; raise a clear error if unavailable."""
    try:
        from browser_use import BrowserProfile  # noqa: F401
        from browser_use.browser.session import BrowserSession  # noqa: F401
        from browser_use.actor.page import Page  # noqa: F401
        return True
    except Exception as exc:  # pragma: no cover - depends on deployment env
        raise MissingBrowserUseError(
            "browser-use is not installed in this environment. Add the "
            "Hyper_Agent/browser-use package to deployment to enable the agent."
        ) from exc


# ── Search URL builders ─────────────────────────────────────────────────────
def post_search_url(keywords: str) -> str:
    return f"https://www.linkedin.com/search/results/content/?keywords={_q(keywords)}"


def people_search_url(keywords: str) -> str:
    return f"https://www.linkedin.com/search/results/people/?keywords={_q(keywords)}"


def jobs_search_url(keywords: str, location: str = "") -> str:
    url = f"https://www.linkedin.com/jobs/search/?keywords={_q(keywords)}"
    if location:
        url += f"&location={_q(location)}"
    return url


def _q(s: str) -> str:
    """URL-encode a query term (safe for LinkedIn search params)."""
    from urllib.parse import quote
    return quote((s or "").strip())


# ── Selectors (LinkedIn DOM, current as of this revision) ─────────────────
POST_CARD_SELECTORS = [
    "div.feed-shared-update-v2",
    "article.feed-shared-update-v2",
    "div[data-urn*='urn:li:activity']",
]
JOB_CARD_SELECTOR = "li[data-occludable-job-id], .base-search-card.job-search-card"
PEOPLE_CARD_SELECTORS = [
    "li.reusable-search__result-container",
    "div.reusable-search__result-container",
]

# how long (seconds) to wait for a page to render after navigation
PAGE_SETTLE_SECONDS = 5.0
# fallback page-body grab when structured cards are not found
MAX_NAV_ATTEMPTS = 2


class LinkedInBrowser:
    """Wraps one browser-use BrowserSession for a single agent run.

    Usage (async):
        browser = LinkedInBrowser()
        await browser.start()
        items = await browser.search_posts("looking for video editor")
        await browser.close()
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        cookies_json: str = "",
        allowed_domains: list[str] | None = None,
        user_data_dir: str = "",
        proxy: str = "",
    ) -> None:
        _browser_use()  # fail fast with a clear error if not installed
        self.headless = headless
        self.cookies_json = (cookies_json or "").strip()
        if not self.cookies_json:
            logger.warning("HyperAgent: no LinkedIn cookies set — running in GUEST mode (Jobs+company only).")
        self.domain = "www.linkedin.com"
        self.allowed_domains = allowed_domains or [self.domain]
        self.user_data_dir = user_data_dir
        self.proxy = (proxy or "").strip()
        self._session = None
        self._page = None

    def is_guest(self) -> bool:
        return not bool(self.cookies_json)

    # ── storage-state build (cookie injection) ─────────────────────────────
    def _storage_state(self) -> dict | None:
        """Wrap a Cookie-Editor export into the storage state browser-use applies
        via CDP (see StorageStateWatchdog._load_storage_state).

        Accepts:
          * a bare array:  [{name,value,domain,path,expirationDate,sameSite,...}, ...]
          * a full storage_state object: {"cookies":[...], "origins":[...]}
          * a single cookie object

        Cookie-Editor fields get normalized into the CDP cookie shape
        (`expirationDate` -> `expires`, `sameSite:"no_restriction"` -> `None`,
        dropping hostOnly/session/storeId and null sameSite).
        """
        cookies_json = self.cookies_json
        if not cookies_json:
            return None
        try:
            data = json.loads(cookies_json)
        except json.JSONDecodeError:
            logger.warning("HyperAgent: LINKEDIN_COOKIES is not valid JSON — falling back to guest mode.")
            return None
        raw_cookies: list[dict] = []
        if isinstance(data, dict):
            if data.get("cookies") is not None:
                raw_cookies = data["cookies"]
                origins = data.get("origins") or []
                return {"cookies": [_normalize_cookie(c) for c in raw_cookies if isinstance(c, dict)],
                        "origins": origins}
            if data.get("name") is not None:
                raw_cookies = [data]
        elif isinstance(data, list):
            raw_cookies = data
        else:
            return None
        return {"cookies": [_normalize_cookie(c) for c in raw_cookies if isinstance(c, dict)], "origins": []}

    # ── lifecycle ──────────────────────────────────────────────────────────
    async def start(self) -> None:
        from browser_use import BrowserProfile
        from browser_use.browser.session import BrowserSession

        bp = BrowserProfile(
            headless=self.headless,
            allowed_domains=self.allowed_domains,
            user_data_dir=self.user_data_dir or None,
            storage_state=self._storage_state(),
            proxy=_build_proxy_settings(self.proxy),
        )
        self._session = BrowserSession(browser_profile=bp)
        await self._session.start()
        self._page = await self._session.get_current_page()
        logged_in = bool(self._storage_state())
        if not logged_in:
            logger.warning("HyperAgent: browser session ready (NO cookies => guest mode).")
        else:
            logger.info("HyperAgent: browser session ready (cookies injected).")

    async def close(self) -> None:
        if self._session is not None:
            try:
                await self._session.close()
            except Exception as exc:  # noqa: BLE001 - cleanup must not raise
                logger.warning("HyperAgent: error closing browser: %s", exc)
        self._session = None
        self._page = None

    async def __aenter__(self) -> "LinkedInBrowser":
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    @property
    def page(self):
        return self._page

    # ── public search methods ──────────────────────────────────────────────
    async def search_posts(self, keywords: str, max_items: int = 15) -> list[dict]:
        """Return raw post items from LinkedIn content search (needs login)."""
        return await self._collect_items(
            post_search_url(keywords), POST_CARD_SELECTORS, max_items, kind="post"
        )

    async def search_people(self, keywords: str, max_items: int = 15) -> list[dict]:
        """Return raw people/profile items from people search (needs login)."""
        return await self._collect_items(
            people_search_url(keywords), PEOPLE_CARD_SELECTORS, max_items, kind="people"
        )

    async def search_jobs(self, keywords: str, location: str = "", max_items: int = 15) -> list[dict]:
        """Return raw job items from LinkedIn Jobs search (guest-friendly)."""
        return await self._collect_items(
            jobs_search_url(keywords, location), [JOB_CARD_SELECTOR], max_items, kind="job"
        )

    async def enrich_authors(self, author_urls: list[str], max_items: int = 20) -> dict[str, str]:
        """Visit each author's public profile and capture their location.

        LinkedIn's content-search cards do NOT surface the author's country, so a
        country-gated search needs this pass. Returns {author_url: location_text}.
        """
        out: dict[str, str] = {}
        if not self._page:
            if self._session is None:
                raise HyperAgentError("Browser not started. Call start() first.")
            self._page = await self._session.get_current_page()
        for url in author_urls[:max_items]:
            url = (url or "").strip()
            if not url or "/in/" not in url:
                continue
            loc = await self._profile_location(url)
            if loc:
                # key without query/trailing slash
                out[url.split("?")[0].rstrip("/").lower()] = loc
        logger.info("HyperAgent: enriched %d/%d author locations", len(out), min(len(author_urls), max_items))
        return out

    async def _profile_location(self, profile_url: str) -> str:
        """Extract the location line from a public LinkedIn profile header."""
        try:
            await self._page.goto(profile_url)
            await self._wait(_settle())
            # Location typically sits after the headline block; grab the header text.
            probe = ("(el) => { const n=document.querySelector('.top-card-layout__entity-info, "
                     "main, .profile-topcard, .artdeco-card'); "
                     "return n ? (n.innerText||'').replace(/[\\n\\u00a0]+/g,' \\u00b7 ') : ''; }")
            hdr = await self._page.evaluate(probe)
            return _location_from_header(hdr or "")
        except Exception as exc:  # noqa: BLE001
            logger.debug("HyperAgent: profile location parse failed for %s (%s)", profile_url, exc)
            return ""

    # ── core collection ────────────────────────────────────────────────────
    async def _collect_items(
        self, url: str, selectors: list[str], max_items: int, *, kind: str
    ) -> list[dict]:
        if not self._page:
            if self._session is None:
                raise HyperAgentError("Browser not started. Call start() first.")
            self._page = await self._session.get_current_page()
        try:
            await self._page.goto(url)
            await self._wait(_settle())
        except Exception as exc:  # noqa: BLE001
            logger.warning("HyperAgent: navigation failed for %s: %s", url, exc)
            return []

        # LinkedIn redirects guest/content browsing to the login wall.
        page_url = await self._safe_url()
        if "login" in page_url or "authwall" in page_url:
            logger.warning("HyperAgent: LinkedIn authwall hit for %s (needs login for %s).", url, kind)
            return []

        # Lazy-render: scroll a few times so LinkedIn hydrates the result cards.
        await self._scroll_to_render(rounds=6)

        items: list[dict] = []
        if kind == "job":
            items = await self._extract_jobs(selectors, max_items)
        else:
            # For post/people feeds the robust path is the JS probe that pairs
            # each author profile link with the text of its post container.
            items = await self._extract_posts_by_author(max_items)
            # If the pairing found nothing (LinkedIn's lazy rendering is
            # nondeterministic), fall back to splitting the full page text into
            # "Feed post <author> ..." blocks, which is far more reliable.
            if not items:
                items = self._text_post_splitter(await self._safe_body_text(), max_items)
        if not items:
            items = self._text_blocks_fallback(await self._safe_body_text(), max_items)
        logger.info("HyperAgent: collected %d %s items from %s", len(items), kind, url)
        return items

    def _text_post_splitter(self, body: str, max_items: int) -> list[dict]:
        """Split the full page innerText into real posts by the 'Feed post <name>'
        markers LinkedIn uses, pairing each with the author's profile URL when the
        name is present (author URL is recovered in a later profile pass)."""
        if not body:
            return []
        # Each post begins with "Feed post <Author Name>" then optional meta lines
        # and the body, ending at the next "Feed post" or the engagement footer.
        parts = re.split(r"(?i)\bfeed post\b", body)
        # Also fall back to plain "Post" markers.
        if len(parts) < 2:
            parts = re.split(r"(?i)\npost\b", body)
        items: list[dict] = []
        seen_names: set[str] = set()
        for chunk in parts[1:]:
            chunk = " ".join(chunk.split())
            if len(chunk) < 50:
                continue
            # First token(s) up to a delimiter is the author name (may be 1-3 words).
            m = re.match(r"^([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3})\s+", chunk)
            author = m.group(1).strip() if m else ""
            if not author or author.lower() in ("post", "news", "jobs"):
                continue
            # The real body starts after the author/headline/connection meta,
            # which always ends at "Follow" (or "Connect"/"Message") in feed text.
            body_text = chunk
            for marker in (" Follow ", " Follow·", " Follow ", "· Follow", " Follow"):
                idx = body_text.find(marker)
                if idx > 0:
                    body_text = body_text[idx + len(marker):]
                    break
            # Strip trailing engagement/footer chrome.
            for cut in (" reactions", " comments", " Like · ", " · Comment", " Repost", "… more", " Comment ·"):
                i = body_text.rfind(cut)
                if i > 0:
                    body_text = body_text[:i]
                    break
            body_text = " ".join(body_text.split())
            low = (body_text + author).lower()
            if any(mk in low for mk in ("skip to main content", "join now", "find your dream job", "linkedin membership")):
                continue
            if len(body_text) < 40:
                continue
            key = author.lower()
            if key in seen_names:
                continue
            seen_names.add(key)
            items.append({
                "author": {"url": "", "name": author, "info": ""},
                "content": body_text[:3000],
                "postedAt": None,
                "engagement": {},
            })
            if len(items) >= max_items:
                break
        return items

    async def _scroll_to_render(self, rounds: int = 4) -> None:
        """Scroll the content feed to trigger LinkedIn's lazy hydration."""
        if not self._page:
            return
        try:
            await self._page.evaluate("(el) => window.scrollTo(0, 0)")
        except Exception:  # noqa: BLE001
            return
        for _ in range(rounds):
            try:
                await self._page.evaluate("(el) => window.scrollBy(0, 800)")
            except Exception:  # noqa: BLE001
                break
            await self._wait(2.0)

    async def _extract_posts_by_author(self, max_items: int) -> list[dict]:
        """Pair every LinkedIn profile link with the text of its post container.

        Proven against the live feed: scrolling renders each result, then walking
        up from the author `<a href*=.../in/...>` to a parent whose innerText is
        large enough yields the full post (headline + body + engagement).
        """
        probe = """
        (el) => {
          const out = [];
          const seen = new Set();
          const authors = document.querySelectorAll('a[href*="/in/"]');
          for (const a of authors) {
            const href = (a.getAttribute('href') || '').split('?')[0];
            if (!href || seen.has(href)) continue;
            seen.add(href);
            let node = a, climb = 0, container = null;
            while (node && climb < 12) {
              node = node.parentElement; climb++;
              if (node) {
                const t = (node.innerText || '').trim();
                if (t.length >= 250) { container = node; break; }
              }
            }
            if (!container) continue;
            const txt = (container.innerText || '').replace(/\\u00a0/g, ' ').replace(/\\n+/g, ' ').slice(0, 3000);
            out.push({authorUrl: href, text: txt});
            if (out.length >= %d) break;
          }
          return JSON.stringify(out);
        }
        """ % max_items

        try:
            raw = await self._page.evaluate(probe)
        except Exception as exc:  # noqa: BLE001
            logger.warning("HyperAgent: author pairing probe failed: %s", exc)
            return []
        try:
            import json as _json
            pairs = _json.loads(raw) if isinstance(raw, str) else []
        except Exception:  # noqa: BLE001
            pairs = []

        items: list[dict] = []
        for pair in pairs:
            author_url = (pair.get("authorUrl") or "").strip()
            text = (pair.get("text") or "").strip()
            if not author_url or len(text) < 40:
                continue
            item = _post_block_to_item(author_url, text)
            if item:
                items.append(item)
        return items

    async def _extract_jobs(self, selectors: list[str], max_items: int) -> list[dict]:
        """Extract jobs via the CDP job card nodes (stable selectors)."""
        fallback = await self._safe_body_text()
        for sel in selectors:
            try:
                cards = await self._page.get_elements_by_css_selector(sel)
                if not cards:
                    continue
                out: list[dict] = []
                for card in cards[:max_items]:
                    item = await self._extract_card(card, "job")
                    if item:
                        out.append(item)
                if out:
                    return out
            except Exception as exc:  # noqa: BLE001
                logger.warning("HyperAgent: job selector %r failed (%s); trying next.", sel, exc)
        # Fallback: build job items from body text (keyword + location cues).
        return self._text_blocks_fallback(fallback, max_items)

    async def _extract_card(self, card, kind: str) -> dict | None:
        """Parse a single DOM card into a raw engine item."""
        try:
            info = await card.get_basic_info()
            return _card_to_item(info, card, kind)
        except Exception as exc:  # noqa: BLE001
            logger.debug("HyperAgent: card parse failed (%s).", exc)
            return None


    # ── selectors / helpers ────────────────────────────────────────────────
    async def _safe_url(self) -> str:
        try:
            return await self._page.get_url()
        except Exception:  # noqa: BLE001
            return ""

    async def _safe_body_text(self) -> str:
        try:
            return await self._page.evaluate("(el) => document.body ? document.body.innerText : ''")
        except Exception:  # noqa: BLE001
            return ""

    def _text_blocks_fallback(self, body: str, max_items: int) -> list[dict]:
        if not body:
            return []
        items: list[dict] = []
        lines = [l.strip() for l in body.splitlines() if l.strip()]
        # crude: treat runs of >=2 lines as candidate blocks
        block: list[str] = []
        for line in lines:
            if len(line) > 80:
                if len(block) >= 2:
                    items.append({"content": " ".join(block)[:3000], "author": {}})
                block = []
                continue
            block.append(line)
            if len(block) >= 8:
                items.append({"content": " ".join(block)[:3000], "author": {}})
                block = []
        if len(block) >= 2:
            items.append({"content": " ".join(block)[:3000], "author": {}})
        return items[:max_items]

    @staticmethod
    async def _wait(seconds: float) -> None:
        await asyncio.sleep(seconds)


def _settle() -> float:
    return PAGE_SETTLE_SECONDS


def _build_proxy_settings(proxy: str):
    """Parse a proxy URL into browser-use ProxySettings, or None if empty.

    Accepts: http://user:pass@host:port, socks5://host:port, host:port
    """
    if not proxy:
        return None
    from urllib.parse import urlparse
    from browser_use.browser.profile import ProxySettings
    raw = proxy.strip()
    if "://" not in raw:
        raw = "http://" + raw
    try:
        p = urlparse(raw)
    except Exception:  # noqa: BLE001
        logger.warning("HyperAgent: could not parse proxy URL %s", proxy)
        return None
    scheme = p.scheme or "http"
    host = p.hostname or ""
    port = p.port
    if not host or not port:
        logger.warning("HyperAgent: proxy URL must include host:port — got %s", proxy)
        return None
    server = f"{scheme}://{host}:{port}"
    return ProxySettings(server=server, username=p.username or None, password=p.password or None)


# ── DOM → raw item mapping ─────────────────────────────────────────────────
def _card_to_item(info: Any, card, kind: str) -> dict | None:
    """Map a card's ElementInfo + attributes into the engine's raw item shape.

    LinkedIn card DOM varies; we defensively read the most common slots and, for
    everything else, capture the card's visible text via CDP as the post content.
    """
    attrs = (info.attributes or {}) if hasattr(info, "attributes") else {}
    text = ""
    try:
        text = attrs.get("textContent") or attrs.get("innerText") or ""
    except Exception:  # noqa: BLE001
        text = ""

    item: dict[str, Any] = {"author": {}, "engagement": {}}

    if kind == "job":
        urn = attrs.get("data-entity-urn") or ""
        m = re.search(r"urn:li:jobPosting:(\d+)", urn or "")
        if m:
            item["postId"] = f"job-{m.group(1)}"
            item["linkedinUrl"] = f"https://www.linkedin.com/jobs/view/{m.group(1)}/"
        item["postUrl"] = item.get("linkedinUrl", "")
        text = text or _visible_card_text(card)
        item["content"] = text[:3000]
        return _normalize_item(item)

    # post / people
    urn = attrs.get("data-urn") or attrs.get("data-entity-urn") or ""
    if "activity" in urn:
        m = re.search(r"urn:li:(?:activity|feedUpdate):(\d+)", urn or "")
        if m:
            item["postId"] = f"activity-{m.group(1)}"
            item["postUrl"] = f"https://www.linkedin.com/feed/update/urn:li:activity:{m.group(1)}/"
            item["linkedinUrl"] = item["postUrl"]
    # author url: LinkedIn cards carry the author link
    author_link = _author_link(attrs)
    if author_link:
        item["author"]["url"] = author_link
    text = text or _visible_card_text(card)
    item["content"] = text[:3000]
    return _normalize_item(item)


def _author_link(attrs: Any) -> str:
    for key in ("authorHref", "actorLink", "authorUrl"):
        v = attrs.get(key)
        if isinstance(v, str) and "/in/" in v:
            return v
    return ""


def _visible_card_text(card) -> str:
    try:
        # evaluate passes a callback `(el) =>` bound to the element
        return card.evaluate("(el) => el ? (el.innerText || el.textContent || '') : ''")
    except Exception:  # noqa: BLE001
        return ""


def _normalize_item(item: dict) -> dict | None:
    content = (item.get("content") or "").strip()
    if len(content) < 20:
        return None
    return item


# Profile-header structure (from live LinkedIn, SDUI-rendered):
#   <Name> | · 3rd | <headline> | <LOCATION> | · | Contact info | <company> ...
# The LOCATION is ALWAYS the segment immediately before "Contact info". We find
# "Contact info" then walk back past empty "·" separators to the prior real
# segment. Place-hint/comma checks are used only as a sanity guard.
_LANG_MARKERS = ("ukrain", "україн", "english", "español", "deutsch", "français", "português",
                 "हिन्दी", "中文", "日本語", "한국어")
_PLACE_HINTS = ("india", "usa", "united states", "uk", "canada", "australia", "germany", "uae",
                "singapore", "delhi", "mumbai", "noida", "bengaluru", "bangalore", "new york",
                "london", "toronto", "dubai", "berlin", "paris", "bangladesh", "pakistan",
                "sri lanka", "nepal", "area", "region", "province", "district", "city")
_UI_SKIP = ("contact info", "follow", "message", "connect", "about", "see more", "open to",
            "followers", "connections", "experience", "education")


def _bad_segment(s: str) -> bool:
    s = s.strip()
    if not s or len(s) > 80 or s.isdigit():
        return True
    low = s.lower()
    if any(m in low for m in _LANG_MARKERS):
        return True
    if any(m in low for m in _UI_SKIP):
        return True
    if s[0].isdigit():
        return True
    # A headline/role line uses pipe separators; a location never does.
    if "|" in s:
        return True
    return False


def _location_from_header(header: str) -> str:
    """Extract the location line from a LinkedIn profile header text.

    Positional rule: the location is the segment immediately preceding the
    "Contact info" tile in the top card. Verified against live profiles
    ("New Delhi, Delhi, India", "Noida, Uttar Pradesh, India", "Greater Delhi Area").
    """
    if not header:
        return ""
    segs = [s.strip(" ·|") for s in header.split("·")]
    # find "Contact info" index
    ci = next((i for i, s in enumerate(segs) if "contact info" in s.lower()), -1)
    if ci > 0:
        # walk back over empty separators to the next non-empty, non-skip segment
        i = ci - 1
        while i >= 0:
            cand = segs[i].strip()
            if cand and not _bad_segment(cand):
                return cand
            i -= 1
    # Fallback: any comma-separated, place-hinted segment that is not skip.
    for s in segs:
        cand = s.strip()
        if "," in cand and not _bad_segment(cand):
            low = cand.lower()
            if any(h in low for h in _PLACE_HINTS) or tail_is_country(cand):
                return cand
    return ""


def tail_is_country(s: str) -> bool:
    """True if the last comma segment of `s` looks like a country name."""
    if "," not in s:
        return False
    tail = s.rsplit(",", 1)[-1].strip().lower()
    return len(tail) >= 4 and re.search(r"[a-z]", tail) and not tail.isdigit()


# Regexes to lift useful fields out of a raw "Feed post <Name> <headline> <meta> <body>..." blob.
_AUTHOR_NAME_RE = re.compile(r"Feed post\s*([A-Za-z][A-Za-z .'-]{1,60})")
_HEADLINE_RE = re.compile(r"•\s*3rd\+\s*([^\n•]{5,220})", re.IGNORECASE)
_REACTIONS_RE = re.compile(r"(\d[\d,.]*[kKmM]?)\s*(reactions?|likes?)", re.IGNORECASE)
_COMMENTS_RE = re.compile(r"(\d[\d,.]*[kKmM]?)\s*comments?", re.IGNORECASE)


def _post_block_to_item(author_url: str, text: str) -> dict | None:
    """Convert a paired (author URL, post container text) into a raw engine item.

    The feed block has the shape:
        Feed post <Author Name>  •  3rd+ <headline>  <ago>  •  Follow  <post body ...>  ...  <n> reactions  ...
    We extract the author name, headline (which often carries the company/role),
    the post body, and engagement counts, then strip UI chrome ("Follow",
    "… more", like/comment/repost) so the classifier sees the real content.
    """
    # Bootstrap author name from the URL slug if the text header is missing.
    author = _name_from_url(author_url)

    m = _AUTHOR_NAME_RE.search(text)
    if m:
        author = m.group(1).strip()

    headline = ""
    hm = _HEADLINE_RE.search(text)
    if hm:
        headline = " ".join(hm.group(1).split())[:500]

    # Post body = everything after the "Follow" marker, before the engagement footer.
    body = text
    for marker in ("Follow ", "Comment\n", " Repost ", " Repost\n", "… more", "\nMore"):
        idx = body.find(marker)
        if idx > 0:
            body = body[idx + len(marker):]
            break
    # Cut engagement footer / trailing chrome.
    for cut in (" reactions", " comments", "comment · ", " Like · ", " · Repost"):
        i = body.rfind(cut)
        if i > 0:
            body = body[:i]
            break
    body = " ".join(body.split())
    if len(body) < 25:
        body = " ".join(text.split())[:2000]

    reactions = _num_from(_REACTIONS_RE.search(text))
    comments = _num_from(_COMMENTS_RE.search(text))

    # Reject page chrome / boilerplate so we don't feed the classifier junk
    # (sign-in banner, nav, search suggestions, get-the-app, footer, etc.).
    if _is_boilerplate(body, author_url, author):
        return None

    item = {
        "author": {"url": author_url, "name": author, "info": headline},
        "content": body[:3000],
        "postedAt": None,
        "engagement": {"likes": reactions, "comments": comments},
    }
    if author_url and "/in/" in author_url:
        item["linkedinUrl"] = author_url
    return _normalize_item(item)


def _name_from_url(author_url: str) -> str:
    slug = (author_url or "").rstrip("/").split("/")[-1]
    parts = [p for p in re.split(r"[-_+]", slug) if p][:3]
    name = " ".join(p.title() for p in parts if len(p) > 1)
    return name or slug


# Page chrome / boilerplate that must never be treated as a post.
_BOILERPLATE_MARKERS = (
    "skip to main content", "skip to search", "skip to footer", "join now",
    "sign in", "find your dream job", "build your career", "people learning",
    "jobs games", "top content", "linkedin corporation", "privacy & terms",
    "help center", "accessibility", "get the linkedin app", "notifications",
    "recent entity history", "suggestions available",
)


def _is_boilerplate(body: str, author_url: str, author_name: str) -> bool:
    low = (body or "").lower()
    # A real post has an in-repo author link and a few sentences.
    if not author_url or "/in/" not in author_url:
        return True
    # Too short to be a real post.
    if len((body or "").strip()) < 40:
        return True
    # If it's mostly chrome markers, drop it.
    hits = sum(1 for m in _BOILERPLATE_MARKERS if m in low)
    if hits >= 2:
        return True
    if any(m in low for m in ("skip to main content", "join now", "find your dream job")):
        return True
    return False


def _num_from(match) -> int:
    if not match:
        return 0
    raw = match.group(1).replace(",", "").lower().strip()
    try:
        if raw.endswith("k"):
            return int(float(raw[:-1]) * 1000)
        if raw.endswith("m"):
            return int(float(raw[:-1]) * 1000000)
        return int(float(raw))
    except (ValueError, TypeError):
        return 0


_SAMESITE_MAP = {
    "no_restriction": "None",
    "none": "None",
    "lax": "Lax",
    "strict": "Strict",
    "unspecified": "Lax",
}


def _normalize_cookie(c: dict) -> dict:
    """Convert a Cookie-Editor cookie into the CDP cookie shape browser-use sets.

    - expirationDate (float seconds) -> expires
    - sameSite 'no_restriction'|null -> 'None'|'Lax' (CDP only accepts None/Lax/Strict)
    - drop hostOnly / session / storeId / sameSite-null noise
    """
    out: dict = {
        "name": c.get("name", ""),
        "value": c.get("value", ""),
        "domain": c.get("domain", ""),
        "path": c.get("path", "/"),
    }
    expires = c.get("expires")
    if expires is None:
        expires = c.get("expirationDate")
    if expires is not None and isinstance(expires, (int, float)) and not isinstance(expires, bool):
        # CDP expects Unix seconds.
        try:
            ex = float(expires)
            if ex > 10_000_000_000:  # milliseconds -> seconds
                ex = ex / 1000.0
            out["expires"] = int(ex)
        except (TypeError, ValueError):
            pass
    if c.get("httpOnly"):
        out["httpOnly"] = True
    if c.get("secure"):
        out["secure"] = True
    ss = c.get("sameSite")
    if ss:
        mapped = _SAMESITE_MAP.get(str(ss).lower())
        if mapped:
            out["sameSite"] = mapped
    return out


# ── Convenience: one-shot scrape helper ─────────────────────────────────────
async def scrape_linkedin(
    *,
    queries: list[str],
    kind: str = "post",
    max_items_per_query: int = 15,
    headless: bool = True,
    cookies_json: str = "",
    location: str = "",
) -> tuple[int, int, list[dict], list[str]]:
    """Scrape LinkedIn for a batch of queries. Mirrors the engine's discover
    contract: returns (ok_lanes, total_lanes, raw_items, errors)."""
    ok, errors, items = 0, [], []
    if not queries:
        return 0, 0, [], ["no_queries"]
    async with LinkedInBrowser(headless=headless, cookies_json=cookies_json) as browser:
        for q in queries[:3]:
            try:
                if kind == "job":
                    batch = await browser.search_jobs(q, location, max_items_per_query)
                elif kind == "people":
                    batch = await browser.search_people(q, max_items_per_query)
                else:
                    batch = await browser.search_posts(q, max_items_per_query)
                if batch:
                    ok += 1
                    items.extend(batch)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{q}: {str(exc)[:160]}")
    return ok, min(3, max(1, len(queries))), items, errors
