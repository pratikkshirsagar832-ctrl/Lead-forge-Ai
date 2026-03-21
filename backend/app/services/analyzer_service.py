"""
LeadForge AI — Website Analyzer Service

Lightweight homepage analysis using Scrapling.
Checks SSL, title, meta, content length, contact info, social links.
Returns a score, category (warm/skip), and issues list.
"""

import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Minimum acceptable content length (characters)
MIN_CONTENT_LENGTH = 200


async def analyze_website(url: str) -> dict[str, Any]:
    """
    Analyze a website's homepage using lightweight heuristics.

    Returns:
        {
            "overall_score": int (0-100),
            "category": "warm" | "skip",
            "issues": [...],
            "emails_found": [...],
            "phones_found": [...],
            "raw_analysis": {...},
        }
    """
    if not url:
        return _empty_result("No website URL provided")

    # Normalize URL
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    issues: list[str] = []
    raw_analysis: dict[str, Any] = {}
    emails_found: list[str] = []
    phones_found: list[str] = []
    score = 100  # Start at 100, deduct for issues

    try:
        # Attempt to use Scrapling for page fetching
        html_content, final_url, used_scrapling = await _fetch_page(url)

        if not html_content:
            return _empty_result("Could not fetch homepage")

        raw_analysis["fetched_url"] = final_url
        raw_analysis["used_scrapling"] = used_scrapling
        raw_analysis["content_length"] = len(html_content)

        # ── SSL/HTTPS Check ─────────────────────────────────
        parsed = urlparse(final_url or url)
        is_https = parsed.scheme == "https"
        raw_analysis["is_https"] = is_https
        if not is_https:
            issues.append("Site does not use HTTPS")
            score -= 15

        # ── Title Check ─────────────────────────────────────
        title = _extract_tag_content(html_content, "title")
        raw_analysis["title"] = title
        if not title:
            issues.append("Missing page title")
            score -= 10
        elif len(title) < 10:
            issues.append("Page title is too short")
            score -= 5

        # ── Meta Description ────────────────────────────────
        meta_desc = _extract_meta_description(html_content)
        raw_analysis["meta_description"] = meta_desc
        if not meta_desc:
            issues.append("Missing meta description")
            score -= 10
        elif len(meta_desc) < 50:
            issues.append("Meta description is too short")
            score -= 5

        # ── Content Length ──────────────────────────────────
        visible_text = _extract_visible_text(html_content)
        text_length = len(visible_text)
        raw_analysis["visible_text_length"] = text_length
        if text_length < MIN_CONTENT_LENGTH:
            issues.append("Very thin content on homepage")
            score -= 15

        # ── Contact Information ─────────────────────────────
        emails_found = _extract_emails(html_content)
        phones_found = _extract_phones(html_content)
        raw_analysis["emails_count"] = len(emails_found)
        raw_analysis["phones_count"] = len(phones_found)
        if not emails_found and not phones_found:
            issues.append("No contact information found on homepage")
            score -= 10

        # ── Social Presence ─────────────────────────────────
        social_links = _extract_social_links(html_content)
        raw_analysis["social_links_count"] = len(social_links)
        raw_analysis["social_platforms"] = social_links

        # ── Weak Quality Signals ────────────────────────────
        if _is_parked_or_template(html_content, visible_text):
            issues.append("Site appears to be parked or a default template")
            score -= 25

        if _has_broken_layout_signals(html_content):
            issues.append("Possible broken or outdated layout")
            score -= 10

        # ── Viewport / Mobile ──────────────────────────────
        has_viewport = 'name="viewport"' in html_content.lower() or "name='viewport'" in html_content.lower()
        raw_analysis["has_viewport"] = has_viewport
        if not has_viewport:
            issues.append("No viewport meta tag (not mobile-friendly)")
            score -= 10

        # Clamp score
        score = max(0, min(100, score))

        # Determine category
        category = "skip" if score >= 50 else "warm"
        # "warm" = website needs improvement = good lead
        # "skip" = website is already decent = less opportunity

        return {
            "overall_score": score,
            "category": category,
            "issues": issues,
            "emails_found": emails_found[:10],  # Cap at 10
            "phones_found": phones_found[:10],
            "raw_analysis": raw_analysis,
        }

    except Exception as e:
        logger.error(f"Website analysis failed for {url}: {e}")
        return _empty_result(f"Analysis failed: {str(e)}")


async def _fetch_page(url: str) -> tuple[str, str, bool]:
    """
    Fetch page HTML. Tries Scrapling first, falls back to httpx.
    Returns (html_content, final_url, used_scrapling).
    """
    # Try Scrapling first
    try:
        from scrapling import Fetcher

        fetcher = Fetcher(auto_match=False)
        page = fetcher.get(url, timeout=15)
        if page and page.status == 200:
            return page.text or str(page.body), str(page.url), True
    except ImportError:
        logger.info("Scrapling not installed, falling back to httpx")
    except Exception as e:
        logger.warning(f"Scrapling fetch failed for {url}: {e}")

    # Fallback to httpx
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=15.0,
            headers={"User-Agent": "Mozilla/5.0 (compatible; LeadForgeBot/1.0)"},
        ) as client:
            response = await client.get(url)
            return response.text, str(response.url), False
    except Exception as e:
        logger.error(f"httpx fetch also failed for {url}: {e}")
        return "", url, False


def _extract_tag_content(html: str, tag: str) -> str:
    """Extract text content of the first occurrence of a tag."""
    pattern = rf"<{tag}[^>]*>(.*?)</{tag}>"
    match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _extract_meta_description(html: str) -> str:
    """Extract meta description content."""
    pattern = r'<meta\s+[^>]*name=["\']description["\'][^>]*content=["\']([^"\']*)["\']'
    match = re.search(pattern, html, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # Try reverse order (content before name)
    pattern2 = r'<meta\s+[^>]*content=["\']([^"\']*)["\'][^>]*name=["\']description["\']'
    match2 = re.search(pattern2, html, re.IGNORECASE)
    return match2.group(1).strip() if match2 else ""


def _extract_visible_text(html: str) -> str:
    """Strip HTML tags to get approximate visible text."""
    # Remove script and style blocks
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.IGNORECASE | re.DOTALL)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_emails(html: str) -> list[str]:
    """Extract email addresses from HTML."""
    pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    emails = re.findall(pattern, html)
    # Deduplicate and filter common false positives
    seen = set()
    result = []
    for email in emails:
        lower = email.lower()
        if lower not in seen and not lower.endswith((".png", ".jpg", ".gif", ".svg", ".css", ".js")):
            seen.add(lower)
            result.append(email)
    return result


def _extract_phones(html: str) -> list[str]:
    """Extract phone numbers from HTML."""
    # Match common phone formats
    patterns = [
        r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
        r"\+\d{1,3}[-.\s]?\d{4,14}",
    ]
    phones = []
    for pattern in patterns:
        found = re.findall(pattern, html)
        phones.extend(found)
    # Deduplicate
    seen = set()
    result = []
    for phone in phones:
        cleaned = re.sub(r"\D", "", phone)
        if cleaned not in seen and len(cleaned) >= 7:
            seen.add(cleaned)
            result.append(phone.strip())
    return result


def _extract_social_links(html: str) -> list[str]:
    """Find social media platform references."""
    social_patterns = {
        "facebook": r"facebook\.com",
        "twitter": r"(twitter\.com|x\.com)",
        "instagram": r"instagram\.com",
        "linkedin": r"linkedin\.com",
        "youtube": r"youtube\.com",
        "tiktok": r"tiktok\.com",
    }
    found = []
    for platform, pattern in social_patterns.items():
        if re.search(pattern, html, re.IGNORECASE):
            found.append(platform)
    return found


def _is_parked_or_template(html: str, visible_text: str) -> bool:
    """Detect parked domains or default template sites."""
    parked_signals = [
        "domain is for sale",
        "parked free",
        "buy this domain",
        "this domain is for sale",
        "powered by godaddy",
        "this page is under construction",
        "website coming soon",
        "default web page",
        "it works!",  # Apache default
        "welcome to nginx",
    ]
    lower_text = visible_text.lower()
    return any(signal in lower_text for signal in parked_signals)


def _has_broken_layout_signals(html: str) -> bool:
    """Detect signals of a broken or extremely outdated website."""
    broken_signals = [
        "<frameset",
        "<marquee",
        "frontpage",
        "dreamweaver",
    ]
    lower_html = html.lower()
    return any(signal in lower_html for signal in broken_signals)


def _empty_result(reason: str) -> dict:
    """Return a default empty analysis result."""
    return {
        "overall_score": 0,
        "category": "warm",
        "issues": [reason],
        "emails_found": [],
        "phones_found": [],
        "raw_analysis": {"error": reason},
    }
