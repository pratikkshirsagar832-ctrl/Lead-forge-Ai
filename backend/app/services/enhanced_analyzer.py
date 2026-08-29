"""
Hyperclients — Enhanced Website Analyzer

Uses Scrapling for multi-page crawling and signal extraction only.
No rule-based scoring — all scoring is delegated to OpenAI via deep_analyzer.
"""

import json
import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

try:
    from scrapling import AsyncFetcher
    _SCRAPLING_AVAILABLE = True
except ImportError:
    AsyncFetcher = None
    _SCRAPLING_AVAILABLE = False


logger = logging.getLogger(__name__)

IMPORTANT_PATHS = [
    "/about", "/about-us", "/about-us/",
    "/services", "/service", "/what-we-do",
    "/pricing", "/price", "/plans", "/packages",
    "/contact", "/contact-us", "/get-in-touch",
    "/team", "/our-team", "/staff",
    "/products", "/product",
    "/faq", "/faqs",
]

SOCIAL_DOMAINS = {
    "facebook": ["facebook.com", "fb.com", "fb.me"],
    "twitter": ["twitter.com", "x.com"],
    "instagram": ["instagram.com"],

    "youtube": ["youtube.com", "youtu.be"],
    "tiktok": ["tiktok.com"],
    "pinterest": ["pinterest.com", "pinterest.co.uk"],
    "github": ["github.com"],
    "medium": ["medium.com"],
    "whatsapp": ["wa.me", "whatsapp.com"],
}

CTA_KEYWORDS = [
    "contact us", "get a quote", "book now", "schedule", "call now",
    "free consult", "get started", "request demo", "sign up", "order now",
    "free estimate", "learn more", "see pricing",
]

VP_KEYWORDS = [
    "we provide", "we offer", "we specialize", "our mission",
    "we help", "professional", "expert", "trusted", "since",
    "dedicated to", "committed to", "solutions for",
]


async def analyze_website(url: str) -> dict[str, Any]:
    if not url:
        return _empty_result("No website URL provided")
    if not _SCRAPLING_AVAILABLE:
        logger.error("Scrapling library not installed — cannot analyze website")
        return _empty_result("Scraper library not available: scrapling is not installed")
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    parsed = urlparse(url)
    base_domain = parsed.netloc
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    issues: list[str] = []
    emails_found: list[str] = []
    phones_found: list[str] = []
    all_social_urls: dict[str, list[str]] = {}
    og_values: dict[str, str] = {}
    twitter_values: dict[str, str] = {}
    schema_data: list[dict] = []
    pages_crawled: list[str] = []

    def add_issue(reason: str):
        if reason not in issues:
            issues.append(reason)

    try:
        home_response = await _fetch_page(url)

        if home_response is None:
            return _empty_result("No response received")
        status = getattr(home_response, "status", 0)
        if status >= 400:
            return _empty_result(f"HTTP {status}")

        home_html = str(
            getattr(home_response, 'html_content', None)
            or getattr(home_response, 'text', None)
            or (home_response.body or b"").decode('utf-8', errors='replace')
        )
        home_text = str(home_response.get_all_text(separator=" ", strip=True) or "")
        pages_crawled.append(url)

        final_url = str(getattr(home_response, 'url', url))
        parsed = urlparse(final_url)
        base_domain = parsed.netloc
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        content_empty = len(home_text.strip()) < 100
        is_spa = _is_likely_spa(home_html, content_empty)
        if is_spa:
            logger.info(f"[Analyzer] SPA detected for {url}, retrying with DynamicFetcher")
            try:
                from scrapling import DynamicFetcher
                dynamic_resp = await DynamicFetcher.async_fetch(
                    url, headless=True, load_dom=True,
                    network_idle=True, timeout=30000,
                    disable_resources=True,
                )
                if dynamic_resp:
                    home_html = str(
                        getattr(dynamic_resp, 'html_content', None)
                        or getattr(dynamic_resp, 'text', None)
                        or (dynamic_resp.body or b"").decode('utf-8', errors='replace')
                    )
                    home_text = str(dynamic_resp.get_all_text(separator=" ", strip=True) or "")
                    home_response = dynamic_resp
                    final_url = str(getattr(dynamic_resp, 'url', url))
                    parsed = urlparse(final_url)
                    base_domain = parsed.netloc
                    base_url = f"{parsed.scheme}://{parsed.netloc}"
            except Exception as e:
                logger.warning(f"[Analyzer] DynamicFetcher failed for {url}: {e}")

        important_urls = _discover_pages(home_response, base_url, base_domain)
        important_urls = important_urls[:8]

        all_responses: dict[str, Any] = {"homepage": home_response}
        all_texts: dict[str, str] = {"homepage": home_text}
        all_htmls: dict[str, str] = {"homepage": home_html}

        for page_name, page_url in important_urls:
            if page_url == url or page_url in pages_crawled:
                continue
            try:
                page_resp = await _fetch_page(page_url, timeout=15)
                if page_resp and getattr(page_resp, "status", 0) < 400:
                    page_text = str(page_resp.get_all_text(separator=" ", strip=True) or "")
                    if len(page_text) > 50:
                        page_html = str(
                            getattr(page_resp, 'html_content', None)
                            or getattr(page_resp, 'text', None)
                            or (page_resp.body or b"").decode('utf-8', errors='replace')
                        )
                        all_responses[page_name] = page_resp
                        all_texts[page_name] = page_text
                        all_htmls[page_name] = page_html
                        pages_crawled.append(page_url)
            except Exception as e:
                logger.debug(f"[Analyzer] Failed to fetch {page_name} {page_url}: {e}")

        combined_text = " ".join(all_texts.values())
        combined_html = " ".join(all_htmls.values())
        html_lower = combined_html.lower()

        page_count = len(pages_crawled)
        raw: dict[str, Any] = {
            "status": status,
            "final_url": final_url,
            "pages_crawled": pages_crawled,
            "page_count": page_count,
            "is_spa": is_spa,
            "dynamic_rendering": is_spa,
        }

        raw["content_length"] = len(home_response.body or b"")
        raw["page_size_kb"] = round(len(home_response.body or b"") / 1024, 1)
        raw["visible_text_length"] = len(home_text)

        if raw["page_size_kb"] > 3000:
            add_issue(f"Very large page ({raw['page_size_kb']:.0f} KB)")
        elif raw["page_size_kb"] < 5 and not is_spa:
            add_issue("Suspiciously small page")

        if len(home_text) < 200 and not is_spa:
            add_issue("Very thin content")
        elif len(home_text) < 500 and not is_spa:
            add_issue("Thin content")

        title_el = home_response.css("title::text")
        title = str(title_el.get() or "")
        og_values = _extract_og_values(home_response)
        twitter_values = _extract_twitter_values(home_response)
        schema_data = _extract_json_ld(all_responses)

        og_title = og_values.get("og:title", "")
        og_desc = og_values.get("og:description", "")
        og_image = og_values.get("og:image", "")
        og_site_name = og_values.get("og:site_name", "")

        raw["title"] = title
        raw["og_title"] = og_title
        raw["og_description"] = og_desc
        raw["og_image"] = og_image
        raw["og_site_name"] = og_site_name
        raw["og_values"] = og_values
        raw["twitter_values"] = twitter_values

        if not title and not og_title:
            add_issue("Missing page title")
        elif (title and len(title.strip()) < 10) and not og_title:
            add_issue("Title too short")

        meta_el = home_response.find("meta", {"name": "description"})
        desc = meta_el.attrib.get("content", "") if meta_el else (og_desc or "")
        raw["meta_description"] = desc or ""
        if not desc and not og_desc:
            add_issue("Missing meta description")
        elif desc and len(desc.strip()) < 50:
            add_issue("Meta description too short")

        html_el = home_response.find("html")
        lang = html_el.attrib.get("lang", "") if html_el else ""
        raw["language"] = lang or ""
        if not lang:
            add_issue("Missing HTML lang attribute")

        canonical_el = home_response.find("link", {"rel": "canonical"})
        canonical_href = canonical_el.attrib.get("href", "") if canonical_el else ""
        raw["canonical_url"] = canonical_href or ""
        if not canonical_href:
            add_issue("No canonical tag")

        raw["schema_count"] = len(schema_data)
        raw["has_structured_data"] = len(schema_data) > 0
        raw["schema_types"] = sorted(set(
            s.get("@type", "") for s in schema_data
        ))
        business_info = _extract_business_info(schema_data) if schema_data else {}
        raw["business_info"] = business_info
        if not schema_data:
            add_issue("No structured data (schema.org)")
        raw["schema_data"] = schema_data

        og_count = len(og_values)
        raw["og_tags_count"] = og_count
        if og_count < 3:
            add_issue("Poor social sharing (missing Open Graph tags)")

        twitter_count = len(twitter_values)
        raw["twitter_card_count"] = twitter_count
        if twitter_count < 2:
            add_issue("Twitter Card meta tags incomplete")

        has_favicon = bool(
            home_response.css('link[rel="icon"]')
            or home_response.css('link[rel="shortcut icon"]')
            or home_response.css('link[rel="apple-touch-icon"]')
        )
        raw["has_favicon"] = has_favicon
        if not has_favicon:
            add_issue("No favicon")

        emails_found = _extract_emails(combined_text)
        phones_found = _extract_phones(combined_text)
        raw["emails_count"] = len(emails_found)
        raw["phones_count"] = len(phones_found)

        all_social_urls = _extract_social_urls(home_response, base_url)
        raw["social_urls"] = all_social_urls
        raw["social_platforms"] = list(all_social_urls.keys())
        raw["social_count"] = len(all_social_urls)
        if not all_social_urls:
            add_issue("No social media presence")

        has_tel = bool(re.search(r'tel:\+?\d+', html_lower))
        if phones_found and not has_tel:
            add_issue("Phone number not clickable (no tel: link)")
        has_mailto = bool(re.search(r'mailto:', html_lower))
        if emails_found and not has_mailto:
            add_issue("Email not clickable (no mailto: link)")

        is_https = final_url.startswith("https://")
        raw["is_https"] = is_https
        if not is_https:
            add_issue("No HTTPS")

        if _is_parked(home_text):
            add_issue("Site appears parked or default template")

        if _has_broken_layout(html_lower):
            add_issue("Outdated or broken layout")

        has_viewport = bool(home_response.find("meta", {"name": "viewport"}))
        raw["has_viewport"] = has_viewport
        if not has_viewport:
            add_issue("Not mobile-friendly (no viewport meta)")

        framework = _detect_framework(html_lower)
        raw["framework"] = framework

        headings = {}
        for tag in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            els = home_response.css(tag)
            headings[tag] = len(els)
        raw["headings"] = headings
        if headings["h1"] == 0:
            add_issue("No H1 heading")
        elif headings["h1"] > 1:
            add_issue(f"Multiple H1 tags ({headings['h1']})")

        all_links = home_response.css("a[href]")
        internal = 0; external = 0; nofollow = 0; broken_links = 0
        for link in all_links:
            href = link.attrib.get("href", "")
            rel = (link.attrib.get("rel", "") or "").lower()
            if href.startswith("#") or href.startswith("javascript:"):
                continue
            if "nofollow" in rel:
                nofollow += 1
            if href.startswith("/") or href.startswith("?") or base_domain in href:
                internal += 1
            elif href.startswith("http"):
                external += 1
            if href == "" or href == " ":
                broken_links += 1
        total_links = internal + external
        raw["internal_links"] = internal
        raw["external_links"] = external
        raw["nofollow_links"] = nofollow
        raw["total_links"] = total_links
        raw["broken_links"] = broken_links
        if total_links == 0:
            add_issue("No internal links found")
        elif external > 0 and total_links > 0 and external / total_links > 0.5:
            add_issue("Most links point to external sites")
        if broken_links > 0:
            add_issue(f"Found {broken_links} broken/empty link(s)")

        images = home_response.css("img[src]")
        total_imgs = len(images)
        no_alt = 0; lazy_loaded = 0; webp_count = 0
        for img in images:
            alt = img.attrib.get("alt", "")
            if not alt:
                no_alt += 1
            loading = img.attrib.get("loading", "")
            if loading == "lazy":
                lazy_loaded += 1
            src = (img.attrib.get("src", "") or "").lower()
            if ".webp" in src:
                webp_count += 1
        raw["total_images"] = total_imgs
        raw["images_without_alt"] = no_alt
        raw["images_lazy_loaded"] = lazy_loaded
        raw["images_webp"] = webp_count
        if total_imgs > 0 and no_alt / total_imgs > 0.5:
            add_issue("Many images missing alt text")
        if total_imgs > 0 and webp_count / total_imgs < 0.3:
            add_issue("Most images not in WebP/AVIF format")

        has_ga = bool(
            re.search(r'gtag\s*\(|google-analytics\.com|googletagmanager\.com', html_lower)
        )
        raw["has_analytics"] = has_ga
        if not has_ga:
            add_issue("No analytics detected (GA4/GTM)")

        has_cookie_banner = bool(
            re.search(r'cookie[-_]?(consent|banner|notice|popup|bar)', html_lower)
            or home_response.css('[class*="cookie"], [id*="cookie"], [class*="CookieConsent"]')
        )
        raw["has_cookie_consent"] = has_cookie_banner

        forms = home_response.css("form")
        raw["form_count"] = len(forms)
        if forms:
            cta_inputs = home_response.css('button[type="submit"], input[type="submit"]')
            raw["cta_button_count"] = len(cta_inputs)
        else:
            raw["cta_button_count"] = 0

        has_nav = bool(
            home_response.css("nav, header nav, .nav, .navbar, #nav, #navbar")
        )
        raw["has_navigation"] = has_nav
        if not has_nav:
            add_issue("No visible navigation")

        cta_text_found = any(kw in html_lower[:3000] for kw in CTA_KEYWORDS)
        raw["cta_text_found"] = cta_text_found
        if not cta_text_found:
            add_issue("No clear CTA button (Contact/Book/Quote) detected")

        has_value_prop = any(kw in home_text[:2000] for kw in VP_KEYWORDS)
        raw["has_value_proposition"] = has_value_prop
        if not has_value_prop:
            add_issue("No clear value proposition above the fold")

        has_autoplay = bool(re.search(r'autoplay|autoplay=true|autoplay=1', html_lower))
        raw["has_autoplay_media"] = has_autoplay
        if has_autoplay:
            add_issue("Auto-playing video/audio detected (bad UX)")

        has_chat = bool(
            re.search(r'live.?chat|tawk|intercom|crisp|drift|freshchat|zendesk.*chat|hubspot.*chat', html_lower)
        )
        raw["has_live_chat"] = has_chat

        has_testimonials = bool(
            re.search(r'testimonial|review|rating|what.*client.*say|success.story', html_lower[:5000])
        )
        raw["has_testimonials"] = has_testimonials

        has_pricing = bool(
            re.search(r'pricing|our.price|plan|package', html_lower[:3000])
        )
        raw["has_pricing_page"] = has_pricing

        has_search = bool(
            home_response.css('input[type="search"], input[name="s"], .search-form, #search')
        )
        raw["has_search"] = has_search

        try:
            random_url = f"{parsed.scheme}://{parsed.netloc}/nonexistent-page-hyperclients-check"
            err_resp = await AsyncFetcher.get(random_url, timeout=5, follow_redirects=False)
            if err_resp and err_resp.status == 404:
                err_text = str(err_resp.get_all_text(strip=True) or "").lower()
                has_custom_404 = not any(s in err_text for s in ["not found", "404", "page not found"])
                raw["has_custom_404"] = has_custom_404
                if not has_custom_404 and err_text and len(err_text) < 100:
                    add_issue("No custom 404 page (raw server error)")
            else:
                raw["has_custom_404"] = True
        except Exception:
            raw["has_custom_404"] = None

        has_skip_link = bool(
            home_response.css('[href="#main"], [href="#content"], .skip-link, #skip-link')
        )
        raw["has_skip_navigation"] = has_skip_link
        has_aria = bool(re.search(r'role=|aria-label|aria-hidden|aria-expanded', html_lower))
        raw["has_aria_attributes"] = has_aria
        if not has_aria:
            add_issue("Missing ARIA attributes (poor accessibility)")

        ai_bots_blocked = []
        try:
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            robots_resp = await AsyncFetcher.get(robots_url, timeout=8, follow_redirects=False)
            if robots_resp and robots_resp.status == 200:
                robots_text_raw = str(robots_resp.get_all_text(strip=True) or "").lower()
                ai_bots = ["gptbot", "claudebot", "perplexitybot", "google-extended"]
                for bot in ai_bots:
                    if "disallow: /" in robots_text_raw and bot in robots_text_raw:
                        ai_bots_blocked.append(bot)
                raw["robots_txt_found"] = True
                raw["robots_ai_bots_blocked"] = ai_bots_blocked
            else:
                raw["robots_txt_found"] = False
        except Exception:
            raw["robots_txt_found"] = False

        sitemap_found = False
        try:
            sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"
            sitemap_resp = await AsyncFetcher.get(sitemap_url, timeout=6, follow_redirects=False)
            if sitemap_resp and sitemap_resp.status == 200:
                sitemap_found = True
        except Exception:
            pass
        raw["sitemap_found"] = sitemap_found
        if not sitemap_found:
            add_issue("No XML sitemap detected")

        has_footer = bool(home_response.css("footer, .footer, #footer"))
        raw["has_footer"] = has_footer
        if not has_footer:
            add_issue("No footer found")
        if has_footer:
            copyright_match = re.search(r'©\s*(\d{4})', combined_html)
            if copyright_match:
                year = int(copyright_match.group(1))
                if year < 2023:
                    add_issue(f"Outdated copyright year ({year})")

        has_sticky = bool(re.search(r'position:\s*sticky|position:\s*fixed', html_lower))
        raw["has_sticky_elements"] = has_sticky

        has_aggressive_popup = bool(
            re.search(r'(exit.?intent|modal.*show|popup.*onload|overlay.*display)', html_lower)
        )
        raw["has_aggressive_popup"] = has_aggressive_popup

        for page_name, page_text in all_texts.items():
            if page_name != "homepage" and len(page_text) > 100:
                page_emails = _extract_emails(page_text)
                page_phones = _extract_phones(page_text)
                for e in page_emails:
                    if e not in emails_found:
                        emails_found.append(e)
                for p in page_phones:
                    if p not in phones_found:
                        phones_found.append(p)

        return {
            "overall_score": 50,
            "category": "warm",
            "issues": issues,
            "emails_found": emails_found[:10],
            "phones_found": phones_found[:10],
            "raw_analysis": raw,
        }

    except Exception as e:
        logger.error(f"Enhanced analysis failed for {url}: {e}", exc_info=True)
        return _empty_result(f"Analysis error: {e}")


async def _fetch_page(url: str, timeout: int = 20) -> Any:
    try:
        return await AsyncFetcher.get(
            url, timeout=timeout, follow_redirects=True, stealthy_headers=True,
        )
    except Exception as e:
        logger.debug(f"Failed to fetch {url}: {e}")
        return None


def _is_likely_spa(html: str, content_empty: bool) -> bool:
    if content_empty:
        return True
    signals = [
        '<div id="root">', '<div id="app">', '<div id="__next">',
        'id="__NEXT_DATA__"', 'id="__NUXT__"', 'ng-version',
        'data-reactroot', 'data-react-helmet',
    ]
    return any(s in html for s in signals) or len(html) < 500


def _discover_pages(response: Any, base_url: str, base_domain: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    seen_urls: set[str] = set()

    nav_links = response.css("nav a[href], header a[href], .menu a[href], .nav a[href], footer a[href]")
    link_texts: list[tuple[str, str]] = []
    for link in nav_links:
        href = link.attrib.get("href", "")
        text = str(link.get_all_text(strip=True) or "").lower()
        if href and not href.startswith(("#", "javascript:", "tel:", "mailto:")):
            full_url = urljoin(base_url, href.split("?")[0].split("#")[0]).rstrip("/")
            if base_domain in full_url and full_url not in seen_urls:
                seen_urls.add(full_url)
                link_texts.append((text, full_url))

    path_map: dict[str, str] = {
        "about": "/about", "services": "/services", "service": "/services",
        "pricing": "/pricing", "contact": "/contact", "team": "/team",
        "products": "/products", "faq": "/faq",
    }

    for keyword, fallback_path in path_map.items():
        matched = False
        for text, full_url in link_texts:
            if keyword in text:
                found.append((keyword, full_url))
                matched = True
                break
        if not matched:
            candidate = urljoin(base_url, fallback_path)
            if candidate not in seen_urls:
                found.append((keyword, candidate))
                seen_urls.add(candidate)

    return found


def _extract_og_values(response: Any) -> dict[str, str]:
    values = {}
    for meta in response.css('meta[property^="og:"], meta[name^="og:"]'):
        prop = meta.attrib.get("property", "") or meta.attrib.get("name", "")
        content = meta.attrib.get("content", "")
        if prop and content:
            values[prop] = content
    return values


def _extract_twitter_values(response: Any) -> dict[str, str]:
    values = {}
    for meta in response.css('meta[name^="twitter:"]'):
        name = meta.attrib.get("name", "")
        content = meta.attrib.get("content", "")
        if name and content:
            values[name] = content
    return values


def _extract_json_ld(responses: dict[str, Any]) -> list[dict]:
    results = []
    for page_name, response in responses.items():
        for script in response.css('script[type="application/ld+json"]'):
            try:
                raw_text = str(script.get_all_text(strip=True) or "")
                if not raw_text:
                    continue
                data = json.loads(raw_text)
                if isinstance(data, dict):
                    results.append(data)
                    if "@graph" in data and isinstance(data["@graph"], list):
                        results.extend(data["@graph"])
                elif isinstance(data, list):
                    results.extend(data)
            except (json.JSONDecodeError, Exception) as e:
                logger.debug(f"JSON-LD parse error on {page_name}: {e}")
    unique = []
    seen = set()
    for item in results:
        key = json.dumps(item, sort_keys=True)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _extract_business_info(schemas: list[dict]) -> dict:
    info: dict[str, Any] = {
        "name": "", "description": "", "telephone": "", "email": "",
        "address": "", "opening_hours": [], "social_profiles": [],
        "same_as": [], "price_range": "",
    }
    for item in schemas:
        if not isinstance(item, dict):
            continue
        t = item.get("@type", "")
        if t in ("LocalBusiness", "Organization", "ProfessionalService", "Store", "Restaurant"):
            info["name"] = info["name"] or item.get("name", "")
            info["description"] = info["description"] or item.get("description", "")
            info["telephone"] = info["telephone"] or item.get("telephone", "")
            info["email"] = info["email"] or item.get("email", "")
            info["price_range"] = info["price_range"] or item.get("priceRange", "")
            addr = item.get("address", {})
            if isinstance(addr, dict):
                info["address"] = info["address"] or ", ".join(
                    filter(None, [addr.get(k, "") for k in
                                  ["streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry"]]))
            hours = item.get("openingHoursSpecification", [])
            if isinstance(hours, list):
                info["opening_hours"].extend(hours)
            same_as = item.get("sameAs", [])
            if isinstance(same_as, list):
                info["same_as"].extend(same_as)
                info["social_profiles"].extend(same_as)
            elif isinstance(same_as, str):
                info["same_as"].append(same_as)
                info["social_profiles"].append(same_as)
    info["same_as"] = list(set(info["same_as"]))
    info["social_profiles"] = list(set(info["social_profiles"]))
    return info


def _extract_social_urls(response: Any, base_url: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for link in response.css("a[href]"):
        href = link.attrib.get("href", "")
        if not href or href.startswith(("#", "javascript:")):
            continue
        full_url = urljoin(base_url, href)
        for platform, domains in SOCIAL_DOMAINS.items():
            if any(d in full_url.lower() for d in domains):
                found.setdefault(platform, []).append(full_url)
    for platform in found:
        seen = set()
        unique = []
        for u in found[platform]:
            if u not in seen:
                seen.add(u)
                unique.append(u)
        found[platform] = unique[:3]
    return found


def _extract_emails(text: str) -> list[str]:
    pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    seen: set[str] = set()
    result: list[str] = []
    for email in re.findall(pattern, text):
        low = email.lower()
        if low not in seen and not low.endswith((".png", ".jpg", ".gif", ".svg", ".css", ".js")):
            seen.add(low)
            result.append(email)
    return result


def _extract_phones(text: str) -> list[str]:
    phones: list[str] = []
    for pat in [
        r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
        r"\+\d{1,3}[-.\s]?\d{4,14}",
    ]:
        phones.extend(re.findall(pat, text))
    seen: set[str] = set()
    result: list[str] = []
    for phone in phones:
        cleaned = re.sub(r"\D", "", phone)
        if cleaned not in seen and len(cleaned) >= 7:
            seen.add(cleaned)
            result.append(phone.strip())
    return result


def _is_parked(text: str) -> bool:
    signals = [
        "domain is for sale", "parked free", "buy this domain",
        "this domain is for sale", "powered by godaddy",
        "this page is under construction", "website coming soon",
        "default web page", "it works!", "welcome to nginx",
        "this domain has been registered", "coming soon",
    ]
    lower = text.lower()
    return any(s in lower for s in signals)


def _has_broken_layout(html_lower: str) -> bool:
    return any(s in html_lower for s in ["<frameset", "<marquee"])


def _detect_framework(html_lower: str) -> str:
    if any(s in html_lower for s in ["wp-content", "wp-includes", "/wp-json/"]):
        return "wordpress"
    if any(s in html_lower for s in ["wix-static", "wix-builder", "wix.com"]):
        return "wix"
    if "squarespace" in html_lower or "static1.squarespace" in html_lower:
        return "squarespace"
    if any(s in html_lower for s in ["shopify.com", "/cdn/shop/", "myshopify"]):
        return "shopify"
    if "webflow" in html_lower:
        return "webflow"
    if any(s in html_lower for s in ["drupal"]):
        return "drupal"
    if any(s in html_lower for s in ["joomla", "com_content"]):
        return "joomla"
    if any(s in html_lower for s in ["next/js", "__next_data__", "next-static"]):
        return "nextjs"
    if "__nuxt__" in html_lower:
        return "nuxt"
    return "none"


def _empty_result(reason: str) -> dict:
    return {
        "overall_score": 0,
        "category": "hot",
        "issues": [reason],
        "emails_found": [],
        "phones_found": [],
        "raw_analysis": {
            "error": reason,
        },
    }
