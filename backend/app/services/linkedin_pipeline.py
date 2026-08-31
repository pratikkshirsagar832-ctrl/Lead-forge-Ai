"""
Hyperclients — LinkedIn Intent-Lead Pipeline

Flow (scrapeforge/linkedin-all-in-one):

  1. Build BROAD discovery phrases from user niche (not literal "I need X")
  2. post-search mode → raw posts (boolean OR across phrases)
  3. Parse posts into candidates; keep the strongest post per author
  4. profile-detail mode → enrich headline/company/location (AI context)
  5. GPT semantic scoring 0-100 — implicit commercial intent, not just
     explicit "I need X" statements
  6. Rank → dedupe by author → save tagged leads (source='linkedin')
  7. Optional email enrichment via legacy profile-scraper actor
"""

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from app.config import get_settings
from app.database import get_supabase_admin
from app.services.apify_service import (
    ApifyError,
    dedupe_post_items,
    enrich_profiles,
    fetch_profile_details,
    run_post_search,
    run_lane_search,
    run_job_search,
    filter_jobs_by_work_type,
)

logger = logging.getLogger(__name__)

MAX_RESULTS_CAP = 50

# Concurrent OpenAI calls during AI qualification. Kept low (5) for
# reliability — free-tier OpenAI accounts rate-limit quickly when hammered.
AI_QUALIFY_CONCURRENCY = 5

# Profile enrichment bills per row on pay-per-event actors — cap it.
PROFILE_ENRICHMENT_CAP = 30

# Countries to keep leads from — English-speaking + key EU markets.
# Country codes come from author.location.countryCode in harvestapi "main" mode.
ALLOWED_COUNTRY_CODES = {
    # North America
    "US", "CA", "MX",
    # UK & Ireland
    "GB", "IE", "UK",
    # Oceania
    "AU", "NZ",
    # Western Europe (English-friendly business markets)
    "DE", "NL", "FR", "BE", "CH", "AT", "SE", "NO", "DK", "FI", "ES", "IT", "PT", "LU", "IS",
    # Middle East business hubs (often English-speaking clients)
    "AE", "SA", "QA", "KW",
    # Singapore
    "SG",
}

# If no country code is available, fall back to rejecting known low-value markets.
BLOCKED_COUNTRY_CODES = {"IN", "PK", "BD", "PH", "NG", "LK", "NP", "EG", "MA", "DZ", "VN", "ID", "TH", "MY", "KE", "GH", "ZA"}

# Common Indian/Pakistani/Bangladeshi surname & name markers — used only when
# countryCode is missing, to keep individual leads to English-speaking markets.
SOUTH_ASIA_NAME_MARKERS = (
    "kumar", "sharma", "singh", "patel", "gupta", "reddy", "rao", "iya",
    "meskat", "khurana", "malhotra", "kapoor", "mehta", "shah", "jain",
    "agarwal", "bhatt", "desai", "joshi", "kulkarni", "nair", "menon",
    "pillai", "iyer", "chowdhury", "rahman", "khan", "ahmed", "hussain",
    "ali", "hasan", "rana", "akram", "iftikhar", "naseem", "abbas",
    "zahra", "hassan", "hussain", "mirza", "sheikh", "syed", "zaidi",
    "imran", "adnan", "bilal", "tahir", "saifi", "rafiq", "waqas",
    "baig", "chaudhry", "aslam", "anjum", "farooq", "iqbal", "jamal",
)


def _looks_south_asian(name: str) -> bool:
    """Heuristic: is this likely an Indian/Pakistani/Bangladeshi name?"""
    if not name:
        return False
    low = name.lower()
    return any(marker in low for marker in SOUTH_ASIA_NAME_MARKERS)


# ── Location helpers (ported from HyperAgent) ──────────────────────────────
COUNTRY_NAME_TO_CODE = {
    "usa": "US", "united states": "US", "united states of america": "US", "america": "US", "us": "US",
    "canada": "CA",
    "uk": "GB", "united kingdom": "GB", "england": "GB", "britain": "GB", "scotland": "GB",
    "ireland": "IE",
    "australia": "AU", "new zealand": "NZ",
    "germany": "DE", "netherlands": "NL", "france": "FR", "belgium": "BE", "switzerland": "CH",
    "austria": "AT", "sweden": "SE", "norway": "NO", "denmark": "DK", "finland": "FI",
    "spain": "ES", "italy": "IT", "portugal": "PT", "luxembourg": "LU", "iceland": "IS",
    "uae": "AE", "united arab emirates": "AE", "dubai": "AE", "abu dhabi": "AE",
    "saudi arabia": "SA", "qatar": "QA", "kuwait": "KW", "singapore": "SG", "israel": "IL",
    "india": "IN", "pakistan": "PK", "bangladesh": "BD", "philippines": "PH", "nigeria": "NG",
    "vietnam": "VN", "indonesia": "ID", "thailand": "TH", "malaysia": "MY", "kenya": "KE",
    "ghana": "GH", "south africa": "ZA", "egypt": "EG", "mexico": "MX", "brazil": "BR",
    "sri lanka": "LK", "nepal": "NP", "turkey": "TR",
}

CITY_COUNTRY_HINTS = {
    "new york": "US", "nyc": "US", "san francisco": "US", "sf": "US", "los angeles": "US",
    "chicago": "US", "austin": "US", "miami": "US", "seattle": "US", "boston": "US",
    "denver": "US", "dallas": "US", "houston": "US", "phoenix": "US", "atlanta": "US",
    "toronto": "CA", "vancouver": "CA", "montreal": "CA",
    "london": "GB", "manchester": "GB", "birmingham": "GB", "leeds": "GB", "edinburgh": "GB",
    "dublin": "IE", "sydney": "AU", "melbourne": "AU", "brisbane": "AU", "perth": "AU",
    "auckland": "NZ", "berlin": "DE", "munich": "DE", "hamburg": "DE", "frankfurt": "DE",
    "amsterdam": "NL", "rotterdam": "NL", "paris": "FR", "lyon": "FR", "brussels": "BE",
    "zurich": "CH", "geneva": "CH", "vienna": "AT", "stockholm": "SE", "oslo": "NO",
    "copenhagen": "DK", "helsinki": "FI", "madrid": "ES", "barcelona": "ES", "milan": "IT",
    "rome": "IT", "lisbon": "PT", "dubai": "AE", "abu dhabi": "AE", "riyadh": "SA",
    "doha": "QA", "kuwait city": "KW", "singapore": "SG", "tel aviv": "IL",
    "mumbai": "IN", "delhi": "IN", "new delhi": "IN", "bangalore": "IN", "bengaluru": "IN",
    "hyderabad": "IN", "pune": "IN", "chennai": "IN", "karachi": "PK", "lahore": "PK",
    "dhaka": "BD", "manila": "PH", "lagos": "NG", "nairobi": "KE", "cape town": "ZA",
    "johannesburg": "ZA", "cairo": "EG", "mexico city": "MX", "sao paulo": "BR",
}

# Countries users may explicitly request (even if normally gated out)
USER_REQUESTABLE_COUNTRIES = {
    "IN", "PK", "BD", "PH", "NG", "VN", "ID", "TH", "MY", "KE", "GH", "ZA", "EG",
    "LK", "NP", "TR", "AE", "SA", "QA", "KW", "IL", "BR", "MX",
}


def _parse_location_request(location: str) -> tuple[set[str], str | None]:
    """Parse a user location request into (country_codes, city).

    'Mumbai' → ({"IN"}, "mumbai") | 'US' → ({"US"}, None)
    'Asia'   → region set | 'Europe' → region set
    """
    if not location:
        return set(), None
    loc = location.strip().lower()
    region_map = {
        "asia": {"IN", "PK", "BD", "PH", "VN", "ID", "TH", "MY", "SG", "JP", "KR", "TW"},
        "europe": {"GB", "DE", "FR", "NL", "BE", "CH", "AT", "SE", "NO", "DK", "FI", "ES", "IT", "PT", "IE"},
        "united states": {"US"}, "usa": {"US"}, "america": {"US"},
        "india": {"IN"}, "africa": {"NG", "KE", "GH", "ZA", "EG"},
        "australia": {"AU", "NZ"}, "canada": {"CA"},
        "south america": {"BR", "MX", "AR", "CL", "CO"},
        "uk": {"GB"}, "united kingdom": {"GB"}, "uae": {"AE"}, "dubai": {"AE"},
    }
    if loc in region_map:
        return region_map[loc], None
    if loc in COUNTRY_NAME_TO_CODE:
        return {COUNTRY_NAME_TO_CODE[loc]}, None
    # City check (exact or first-word match)
    if loc in CITY_COUNTRY_HINTS:
        return {CITY_COUNTRY_HINTS[loc]}, loc
    for city, code in CITY_COUNTRY_HINTS.items():
        if loc.startswith(city) or city in loc:
            return {code}, loc
    return set(), loc


def _location_matches(author_location: str, author_country_code: str, country_codes: set[str], city: str | None) -> bool:
    """Does an author's location match the user's requested location?"""
    if not country_codes and not city:
        return True
    loc_low = (author_location or "").lower()
    cc = (author_country_code or "").upper()
    if city:
        if city in loc_low:
            return True
        if cc and cc in country_codes:
            return True
        return False
    if country_codes:
        if cc and cc in country_codes:
            return True
        if loc_low:
            if any(city_name in loc_low for city_name, code in CITY_COUNTRY_HINTS.items() if code in country_codes):
                return True
            for name, code in COUNTRY_NAME_TO_CODE.items():
                if code in country_codes and name in loc_low:
                    return True
        return False
    return True


def _get_author_location(author: dict) -> tuple[str, str]:
    """Extract (country_code, location_text) from harvestapi author data."""
    location = author.get("location") or {}
    if not isinstance(location, dict):
        return "", ""
    country_code = (location.get("countryCode") or "").strip().upper()
    linkedin_text = (location.get("linkedinText") or "").strip()
    parsed = location.get("parsed") or {}
    if isinstance(parsed, dict) and parsed.get("text") and not linkedin_text:
        linkedin_text = str(parsed["text"])
    return country_code, linkedin_text


def _get_author_company(author: dict) -> str:
    """Extract company name from harvestapi author.currentPosition."""
    positions = author.get("currentPosition") or []
    if isinstance(positions, list):
        for pos in positions:
            if not isinstance(pos, dict):
                continue
            name = pos.get("companyName") or pos.get("name") or (pos.get("company") or {}).get("name")
            if name:
                return str(name)[:100]
    # fallback: try headline after "at " or "|"
    info = author.get("info") or author.get("headline") or ""
    if " at " in info:
        return info.split(" at ", 1)[1].split("|")[0].strip()[:100]
    return ""


def build_boolean_query(user_query: str) -> list[str]:
    """Broad discovery phrases around a niche, INCLUDING role-based
    hiring/freelance phrases.

    Real buying intent is rarely written as "I need X" — it looks like
    "looking for a freelance web developer", "hiring a designer for our
    project", "website developer required". So discovery searches broad
    topical + role + hiring phrases and the AI scores intent afterwards.
    """
    q = user_query.strip().strip('"')
    q = " ".join(q.split())
    if not q:
        return ["marketing"]

    base = q.replace("ui-ux", "ui ux").replace("ui/ux", "ui ux")
    low = base.lower()

    # If the user already typed an intent phrase, use it verbatim as seed
    if any(low.startswith(p) for p in (
        "i need", "i want", "i'm looking", "i am looking", "looking for",
        "need ", "help with", "anyone", "recommend", "does anyone",
        "hiring", "we are hiring", "we're hiring",
    )):
        return [base]

    # Derive role variants from the service term.
    # "website development" -> "website developer"
    # "graphic design"      -> "graphic designer"
    # "ui ux designer"      -> already a role, no suffix needed
    # "seo"                 -> "seo expert", "seo specialist"
    def _suffix(base_str: str, word: str, suffix: str) -> str:
        """Replace a word with its role form, avoiding double suffixes
        (e.g. 'designer' -> not 'designerer')."""
        replaced = base_str.replace(word, suffix)
        # avoid double 'er'/'or' endings like "designerer"
        for bad in ("erer", "oror", "eror"):
            if bad in replaced:
                replaced = replaced.replace(bad, bad[:2])
        return replaced.strip()

    roles = {base}
    if "development" in low:
        roles.add(_suffix(base, "development", "developer"))
    if "design" in low:
        roles.add(_suffix(base, "design", "designer"))
    if "marketing" in low:
        roles.add(f"{base} expert")
        roles.add(f"{base} specialist")
    if "seo" in low or "search engine" in low:
        roles.add("seo expert")
        roles.add("seo specialist")
    if "shopify" in low or "ecommerce" in low or "e-commerce" in low:
        roles.add("shopify expert")
    if "motion" in low:
        roles.add("motion designer")
        roles.add("video editor")
    if "social media" in low or "smm" in low:
        roles.add("social media manager")
    if "video" in low or "editing" in low:
        roles.add("video editor")
        roles.add("video editor for")
    if "wordpress" in low:
        roles.add("wordpress developer")
    if "web" in low or "website" in low:
        roles.add(f"{base.replace(' website', '').replace('website', 'web').strip()} developer")
        roles.add(f"{base.replace(' website', '').replace('website', 'web').strip()} designer")
    # If the base itself is a role (designer/developer/expert/specialist/manager),
    # make sure we still generate intent phrases around the base itself.
    base_is_role = any(k in low for k in ("designer", "developer", "expert", "specialist", "manager", "editor", "builder", "consultant"))

    phrases: list[str] = [base]
    for role in sorted(roles, key=len):
        role = " ".join(role.split())
        if not role or role == base:
            continue
        # BUYER-INTENT phrases FIRST (highest priority - attract companies hiring)
        phrases.extend([
            f"looking for a freelance {role}",
            f"looking for freelance {role}",
            f"hiring {role}",
            f"need a {role} for our",
            f"looking for {role} for our",
            f"need {role} for our",
        ])
        # SELLER-ATTRACTING phrases LAST (lower priority - may attract freelancers selling)
        phrases.extend([
            f"{role} required for",
            f"freelance {role} for",
            f"need {role} for project",
            f"contract {role}",
            f"{role} needed",
        ])
    # If the user typed a ROLE directly (e.g. "ui ux designer"), also search
    # buyer-intent phrases around that exact role — otherwise we only get
    # the generic base phrases.
    if base_is_role and len(roles) == 1:
        phrases.extend([
            f"looking for a freelance {base}",
            f"looking for freelance {base}",
            f"hiring {base}",
            f"need a {base} for our",
            f"{base} required for",
            f"contract {base}",
        ])
    # general intent phrases too
    phrases.extend([
        f"{base} agency",
        f"looking for {base}",
        f"need {base}",
        f"{base} help",
        f"{base} project",
    ])

    seen: set[str] = set()
    out: list[str] = []
    for p in phrases:
        p = " ".join(p.split())
        key = p.lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out[:12]


def build_boolean_query_variant(user_query: str, iteration: int) -> list[str]:
    """Generate DIFFERENT query sets for loop iterations 2+.

    Each iteration searches from a different angle so we discover NEW leads
    instead of re-finding the same posts:
      iteration 2: problem/pain-point angle ("traffic dropped", "website not")
      iteration 3: urgency/action angle ("looking for someone", "need help")
      iteration 4: broad/nearby terms (agency, services, recommendations)
      iteration 5: hiring/recruitment angle (role + "for our team/company")
      iteration 6: redesign/rebuild angle ("need a new", "want to redesign")
      iteration 7: cost/budget angle ("affordable", "quote", "budget")
      iteration 8: recommendation angle ("recommend", "suggest", "know a good")
    """
    q = user_query.strip().strip('"')
    q = " ".join(q.split())
    if not q:
        q = "marketing"
    base = q.replace("ui-ux", "ui ux").replace("ui/ux", "ui ux")

    if iteration == 2:
        # Problem / pain-point angle — implicit buyers describing issues.
        phrases = [
            base,
            f"our {base} not working",
            f"struggling with {base}",
            f"{base} problem",
            f"{base} issues",
            f"traffic dropped",
            f"website not converting",
            f"need to improve {base}",
            f"{base} not getting results",
            f"help with {base}",
            f"looking for {base} help",
            f"{base} for our business",
        ]
    elif iteration == 3:
        # Urgency / action angle — active hiring & immediate needs.
        phrases = [
            base,
            f"looking for someone to {base}",
            f"need someone for {base}",
            f"urgently need {base}",
            f"hiring {base} urgently",
            f"looking to hire {base}",
            f"want to hire {base}",
            f"{base} services needed",
            f"find a {base} expert",
            f"{base} recommendations",
            f"anyone know a good {base}",
            f"best {base} agency",
            f"looking for {base} services",
        ]
    elif iteration == 4:
        # Broad angle — service + marketplace terms.
        phrases = [
            base,
            f"{base} services",
            f"{base} solutions",
            f"{base} company",
            f"{base} for startups",
            f"{base} for small business",
            f"affordable {base}",
            f"professional {base}",
            f"{base} quote",
            f"{base} cost",
            f"{base} project",
            f"{base} redesign",
            f"{base} revamp",
        ]
    elif iteration == 5:
        # Hiring/recruitment angle — roles being filled for teams/companies.
        phrases = [
            base,
            f"looking for {base} for our team",
            f"hiring {base} for our company",
            f"{base} needed for our business",
            f"join our team as {base}",
            f"we are looking for {base}",
            f"we need a {base} for",
            f"{base} position available",
            f"{base} opportunity",
            f"recruiting {base}",
            f"{base} freelance opportunity",
            f"contract {base} role",
            f"{base} for a project",
        ]
    elif iteration == 6:
        # Redesign/rebuild angle — replace or improve existing assets.
        phrases = [
            base,
            f"need a new {base}",
            f"want to redesign our {base}",
            f"rebuild our {base}",
            f"redesign {base} for our business",
            f"looking to improve our {base}",
            f"our {base} is outdated",
            f"upgrade our {base}",
            f"{base} for a new website",
            f"{base} for relaunch",
            f"{base} refresh",
            f"new {base} for startup",
            f"{base} makeover",
        ]
    elif iteration == 7:
        # Cost/budget angle — buyers mentioning money.
        phrases = [
            base,
            f"affordable {base} services",
            f"{base} within budget",
            f"budget for {base}",
            f"{base} pricing",
            f"cheap {base} services",
            f"cost effective {base}",
            f"{base} freelancer rates",
            f"{base} on a budget",
            f"reasonable {base}",
            f"{base} quotes",
            f"get a {base} quote",
            f"{base} cost estimate",
        ]
    else:
        # Recommendation angle — asking for referrals/vendors.
        phrases = [
            base,
            f"recommend a {base}",
            f"recommendations for {base}",
            f"suggest a {base}",
            f"know a good {base}",
            f"anyone recommend {base}",
            f"best {base} company",
            f"top {base} agency",
            f"{base} referrals",
            f"who is the best {base}",
            f"looking for {base} recommendations",
            f"good {base} agency",
            f"{base} expert needed",
        ]

    seen: set[str] = set()
    out: list[str] = []
    for p in phrases:
        p = " ".join(p.split())
        key = p.lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out[:12]


def _public_id_from_author_url(url: str) -> str:
    """/in/johndoe/ → johndoe; /company/acme/ → company:acme."""
    try:
        part = url.split(".com/in/", 1)[1]
        return part.split("/")[0].split("?")[0].lower()
    except IndexError:
        try:
            part = url.split(".com/company/", 1)[1]
            return "company:" + part.split("/")[0].split("?")[0].lower()
        except IndexError:
            return ""
    except Exception:
        return ""


def _parse_posted_at(value) -> str | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            ts = value / 1000 if value > 10_000_000_000 else value
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except Exception:
            return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
        except Exception:
            return None
    if isinstance(value, dict):
        return _parse_posted_at(value.get("timestamp") or value.get("date"))
    return None


def _get_avatar(author: dict) -> str:
    avatar = author.get("avatar")
    if isinstance(avatar, str):
        return avatar
    if isinstance(avatar, dict):
        return avatar.get("url") or ""
    picture = author.get("profilePicture") or {}
    if isinstance(picture, dict):
        return picture.get("url") or ""
    return ""


def _is_post_url(url: str) -> bool:
    """A LinkedIn POST url contains /posts/, /feed/update/, /activity- or
    linkedin.com/feed/. Profile URLs contain /in/ — those are NOT post URLs."""
    if not url:
        return False
    low = url.lower()
    return (
        "/posts/" in low
        or "/feed/update/" in low
        or "/activity-" in low
        or "linkedin.com/feed/" in low
    )


def _extract_post_url(item: dict) -> str:
    """Extract the real LinkedIn POST url from a harvestapi/scrapeforge item.

    harvestapi format: item.linkedinUrl is the POST url; item.url may be
    absent or a profile link. Validate the candidate actually looks like a
    post link before returning it.
    """
    for key in ("linkedinUrl", "postUrl", "post_url", "url"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            cleaned = val.strip()
            if _is_post_url(cleaned):
                return cleaned
    sc = item.get("socialContent") or {}
    if isinstance(sc, dict):
        share = sc.get("shareUrl")
        if isinstance(share, str) and _is_post_url(share):
            return share
    return ""


def _company_from_profile(profile: dict) -> str:
    positions = profile.get("currentPosition") or []
    for pos in positions:
        if isinstance(pos, dict):
            name = pos.get("companyName") or pos.get("name") or (pos.get("company") or {}).get("name")
            if name:
                return str(name)[:100]
    return ""


def _location_from_profile(profile: dict) -> str:
    location = profile.get("location") or {}
    if isinstance(location, dict):
        text = location.get("linkedinText")
        if text:
            return text
        parsed = location.get("parsed") or {}
        if isinstance(parsed, dict) and parsed.get("text"):
            return parsed["text"]
    return ""


def _post_strength(lead: dict) -> int:
    likes = lead.get("engagement_likes") or 0
    comments = lead.get("engagement_comments") or 0
    return likes * 2 + comments * 3 + min(len(lead.get("post_text") or ""), 2000)


def process_items(items: list[dict], max_results: int, req_country_codes: set[str] | None = None) -> tuple[list[dict], int]:
    """Parse raw all-in-one post items into candidate lead records.

    NO keyword classification here — the LLM scores intent later.
    Keeps ONE post per author (strongest by engagement) so profile
    enrichment isn't wasted on duplicate rows.

    Country filter: when the user requested specific countries
    (req_country_codes), leads from those countries are KEPT even if
    they're outside the default ALLOWED list (e.g. user asks for India).
    Returns (candidates, skipped_count).
    """
    best_by_author: dict[str, dict] = {}
    skipped = 0

    def _int(v) -> int:
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0

    for item in items:
        author = item.get("author") or {}
        # harvestapi: author.linkedinUrl / author.info; scrapeforge: author.url
        author_url = ((author.get("url") or author.get("linkedinUrl") or "")).strip()
        content = (item.get("content") or "").strip()
        if not author_url or len(content) < 20:
            skipped += 1
            continue

        # Country filter — harvestapi "main" mode gives location.countryCode.
        # Keep leads from the user's requested countries OR the default
        # English-speaking / target markets.
        country_code, location_text = _get_author_location(author)
        if country_code:
            if req_country_codes:
                if country_code not in req_country_codes:
                    logger.info(f"[CountryFilter] skipped {author.get('name')} ({country_code} - {location_text[:40]})")
                    skipped += 1
                    continue
            elif country_code not in ALLOWED_COUNTRY_CODES:
                logger.info(f"[CountryFilter] skipped {author.get('name')} ({country_code} - {location_text[:40]})")
                skipped += 1
                continue
        else:
            # No country data: if scrapeforge fallback, keep (unknown); we can't filter.
            # If headline hints a blocked market, skip it.
            hint = (author.get("info") or author.get("headline") or "").lower()
            name_hint = (author.get("name") or "")
            if not req_country_codes and any(k in hint for k in ("bengaluru", "mumbai", "new delhi", "hyderabad", "pune", "india", "pakistan", "bangladesh", "manila", "lagos", "nairobi")):
                logger.info(f"[CountryFilter] skipped {author.get('name')} (region hint in headline)")
                skipped += 1
                continue
            # Company pages are fine (prime targets). Individuals with South-Asian
            # names and no country data are most likely from blocked markets.
            if not req_country_codes and "/company/" not in author_url and _looks_south_asian(name_hint):
                logger.info(f"[CountryFilter] skipped {author.get('name')} (South-Asian name, no country data)")
                skipped += 1
                continue

        eng = item.get("engagement") or {}
        lead = {
            "full_name": author.get("name") or "",
            # harvestapi provides the author's headline inline (author.info)
            "headline": (author.get("info") or author.get("headline") or "")[:500],
            "company": _get_author_company(author),
            "location": location_text,
            "country_code": country_code,
            "linkedin_url": author_url,
            # harvestapi: item.linkedinUrl is the POST url; item.url may be
            # absent or a profile link. Validate it's actually a post link.
            "post_url": _extract_post_url(item),
            "post_text": content[:3000],
            "posted_at": _parse_posted_at(item.get("postedAt") or item.get("postedTimestamp")),
            "engagement_likes": _int(eng.get("likes") if eng.get("likes") is not None else eng.get("reactions")),
            "engagement_comments": _int(eng.get("comments")),
            "profile_picture_url": _get_avatar(author),
            "connections_count": author.get("connectionsCount") or 0,
        }

        # Dedupe by clean profile URL (strip ?miniProfileUrn=... query params)
        key = author_url.split("?")[0].rstrip("/").lower()
        existing = best_by_author.get(key)
        if existing is None:
            best_by_author[key] = lead
        else:
            skipped += 1
            if _post_strength(lead) > _post_strength(existing):
                best_by_author[key] = lead

    leads = sorted(
        best_by_author.values(),
        key=_post_strength,
        reverse=True,
    )
    if len(leads) > max_results:
        leads = leads[:max_results]
    return leads, skipped


async def qualify_leads_with_ai(leads: list[dict], query: str, client=None, lead_types=None) -> list[dict]:
    """Score commercial intent semantically (0-100) with GPT-4o-mini.

    Runs up to AI_QUALIFY_CONCURRENCY (10) OpenAI calls in parallel using a
    thread pool — big speedup over sequential scoring for large candidate
    lists (55+ candidates per round).
    """
    if client is None:
        settings = get_settings()
        if not settings.openai_api_key:
            logger.warning("OpenAI API key not configured, skipping AI qualification")
            return leads
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)

    SYSTEM_PROMPT = """You are a senior B2B lead qualification specialist for an AI-powered lead-generation platform. You decide whether a LinkedIn post is a genuine BUYING signal that a service provider could convert into a client. Your decisions feed a CRM, so precision matters more than recall: one excellent lead is worth more than ten noise records.

WORKFLOW — always follow these steps in order:
1. Read the post and identify the AUTHOR's role (headline/company).
2. Determine WHO IS THE SUBJECT: is the author BUYING this service, or SELLING their own labor/services?
3. Identify the work arrangement (remote / contract / part-time / full-time on-site).
4. Apply the hard rules below.
5. Score the six dimensions, then compute lead_score.
6. Cross-check internal consistency before emitting JSON.

HARD RULES (never violate):
- R1: A company/owner HIRING a freelancer/contractor/agency on a REMOTE, CONTRACT or PART-TIME basis = STRONG LEAD.
- R2: A company hiring a FULL-TIME ON-SITE employee = NOT a lead (is_lead=false). They are building a payroll team, not buying your service.
- R3: The author SELLING their own services ("I'm available", "open to projects", "seeking contract work", "DM me for work", "I offer X", "my services include") = NEVER a lead, regardless of how well the post matches the niche.
- R4: A RECRUITER/STAFFING agency posting on behalf of clients = NOT a lead.
- R5: Job seekers looking for a role for themselves = NOT a lead.
- R6: Pure content/thought-leadership ("5 tips", "why you need", "trends", "case study", "opinion") = NOT a lead even if it scores high on service_match.
- R7: NON-ENGLISH posts (Spanish, German, French, Hindi, Arabic, etc.) = NOT a lead (is_lead=false). We only serve English-speaking markets. If the post is mostly in another language, reject it even if it describes hiring.

WHO IS THE SUBJECT? (the single most important question)
🚫 SELLING (reject): "I'm available for X", "I'm open to remote work", "I'm seeking projects", "Looking to collaborate", "I offer X", "DM me for X", "I provide X", "My services include", "I build X", "I'm a freelance X looking for clients", "Open to contract work", "Taking new clients". Headline reads "Freelance X", "X Developer/Designer" and the post promotes their availability, portfolio, or services.
✅ BUYING (accept): "We're looking for a developer", "I need a website", "Looking for someone to build our X", "We are hiring a freelance X for a project", "Need a designer on contract", "Anyone know a good agency?", "Recommendations for X services?", "We're looking for the right partners to build our marketing", "Seeking agencies & marketers to work with", or a business describing a problem it needs solved (traffic drop, no website, bad conversions, launching a product).
⚠️ "Looking for partners/agencies/marketers/freelancers" = the company is SOURCING suppliers = BUYER. Only "we offer X / I provide X / we help businesses with X" is a SELLER.
⚠️ RECRUITER EXCEPTION: A staffing agency placing candidates at THIRD-PARTY clients = reject. BUT a company/firm saying "We are building our pool of experts", "Experts required for our projects", "Building a team of freelancers" = they are BUYING expertise for their own work = ACCEPT (lead_type="hiring").

TRAP CASES — the mistakes to avoid:
- Trap 1: A post says "Looking for a freelance SEO expert to work on our project" — this is a BUYER (they're hiring) even though the word "freelance" appears. work_type=contract, is_lead=true.
- Trap 2: A freelancer posts "Freelance SEO expert available for remote projects" — this is a SELLER despite matching the niche perfectly. is_lead=false.
- Trap 3: "We're hiring a full-time SEO manager, on-site in NY" — payroll hire, on-site. is_lead=false.
- Trap 4: "Hiring a remote contract web designer for a 3-month project" — BUYER, remote + contract. Strong lead, score 80+.
- Trap 5: Thought leadership: "5 SEO mistakes killing your rankings" or "How we grew traffic 300%" — content, not intent. is_lead=false.
- Trap 6: A company complains "our organic traffic dropped 40% since the update" WITHOUT asking for help — this is implicit buying intent. problem_awareness, is_lead=true (score 60-80).
- Trap 7: "Anyone else seeing traffic drops?" (no business context, no "for my business") — passive/research, low score (40-55) or reject if purely casual.
- Trap 8: A COMPANY/AGENCY/FIRM says "We are building our pool of experts", "Service Line Experts Required", "Looking for experts to join our project roster", "Building a team of freelancers for client projects" — this is a BUYER of talent/expertise. They are not selling their own services; they are recruiting service providers to work FOR them on projects. is_lead=true, lead_type="hiring". (Exception to the recruiter rule: a firm hiring experts for ITS OWN projects is a buyer; only staffing agencies that place candidates at THIRD-PARTY clients are rejected.)
- Trap 9: "We fired our agency and now use X" — if the post is about replacing a service with a tool, they are NOT currently buying; is_lead=false. But if they say "we fired our agency, looking for a replacement" → buyer.
- Trap 10: "We're looking for partners / looking for the right partners / seeking agencies & marketers to work with / building our marketing engine" — the author is a COMPANY SEEKING service providers = BUYER. is_lead=true, lead_type="hiring". NEVER classify "looking for partners/marketers/agencies" as a seller — they are sourcing suppliers, not offering services. ONLY if the post says "we offer X", "I provide X", "we help businesses with X" is it a seller.

SCORING (six dimensions, then total):
- service_match (0-25): direct mention of the service or its core problem = 25; adjacent problem (traffic drop for SEO, slow site for web dev) = 20; general growth/marketing = 15; vague = 10; unrelated = 0.
- business_problem (0-20): metrics declining or explicit build needed = 20; clear pain ("struggling", "can't") = 15; dissatisfaction/improvement desire = 10; exploring = 5; none = 0.
- buying_intent (0-20): explicit vendor/freelancer search with budget/ASAP = 20; HIRING freelancer/contractor/remote/part-time = 18; strong implicit ("recommendations?", "who can help?") = 15; problem + commercial context ("for my business") = 10; passive = 5; none = 0.
- decision_maker_likelihood (0-15): Founder/CEO/Owner/VP/Director/Head of Marketing = 15; Manager/Lead = 12; unclear but business context = 10; individual contributor/freelancer = 5; student/job-seeker = 0.
- urgency (0-10): urgent/ASAP/deadline = 10; "looking now"/project starting = 8; soon/this month = 7; active problem no timeline = 5; none = 0.
- outreach_worthiness (0-10): explicit vendor search + problem + decision maker = 10; strong problem + reachable role = 8; clear problem unclear authority = 6; vague = 4; wrong audience = 0.

lead_score = service_match + business_problem + buying_intent + decision_maker_likelihood + urgency + outreach_worthiness (0-100).

TIERS:
- 85+ HOT: explicit need or active hiring + decision-maker + concrete problem.
- 70-84 WARM: clear problem or hiring intent, may need light nurturing.
- 40-69 POTENTIAL: relevant but vague; still worth saving.
- 25-39 BORDERLINE: weak signal but real buyer context; still worth saving (they exist).
- <25 NOT a lead.

CONSISTENCY CHECKS (verify before output):
- is_lead=true ⟹ lead_score >= 25.
- is_lead=true ⟹ service_match >= 10 (must relate to the niche).
- lead_type="hiring" + work_type="full_time_onsite" ⟹ is_lead MUST be false.
- lead_type="agency" or "irrelevant" ⟹ is_lead MUST be false.
- Score >= 80 ⟹ reason must cite explicit evidence from the post, not generic phrases.

OUTREACH_ANGLE rules:
- MUST reference a SPECIFIC detail from the post (their company, their problem, their exact words).
- NEVER start with "I noticed your insights on" or "I noticed your recent post" — too generic.
- Sound like a human expert offering a specific next step, not a sales pitch.
- 1 sentence, under 25 words.

Always output valid JSON. Never include markdown, commentary, or text outside the JSON object."""

    PROMPT_TEMPLATE = """Analyze this LinkedIn post for a business offering: {query}

--- POST CONTENT ---
{post_text}

--- AUTHOR HEADLINE ---
{headline}

--- AUTHOR COMPANY ---
{company}

--- AUTHOR LOCATION ---
{location}

FIRST, mentally classify with this decision tree, THEN emit JSON.

STEP 1 — Who is the subject?
  A) Author is BUYING/hiring this service (company/owner/manager looking to get work done)
  B) Author is SELLING their own services/availability
  C) Author is a recruiter/staffing agency, job seeker, student, or pure content creator
  If B or C → is_lead=false, lead_type="agency" or "irrelevant", and STOP (still fill all fields).

STEP 2 — If A (buying), what arrangement?
  - remote / contract / freelance / project basis / part-time / hourly → VALID lead
  - full-time on-site / in-office / no remote → is_lead=false (R2)

STEP 3 — Score the six dimensions honestly. Don't inflate: vague posts get 40-55, strong hiring posts get 80+.

STEP 4 — Verify consistency (is_lead=true requires score>=25 AND service_match>=10).

Output EXACTLY this JSON:
{{
  "is_lead": true/false,
  "lead_score": 0-100,
  "service_match": 0-25,
  "business_problem": 0-20,
  "buying_intent": 0-20,
  "decision_maker_likelihood": 0-15,
  "urgency": 0-10,
  "outreach_worthiness": 0-10,
  "lead_type": "explicit_need|problem_awareness|research|hiring|agency|irrelevant",
  "work_type": "remote|contract|part_time|full_time_onsite|unknown",
  "reason": "1-2 sentences with SPECIFIC quoted evidence from the post or headline that justify lead_score",
  "outreach_angle": "one specific, human, actionable opening line referencing their exact situation (max 25 words)"
}}

REMEMBER:
- Hiring remote/contract/part-time talent for THIS service = high-value lead (80+ if decision-maker).
- "looking for a freelance X" from a company = buyer (contract). "I'm a freelance X available" = seller.
- Full-time on-site = never a lead. Content/tips/opinions = never a lead.
- A firm building a "pool of experts" or saying "experts required for our projects" is BUYING expertise = lead (hiring). Only staffing agencies placing candidates at third-party clients are rejected.
- "Looking for partners/agencies/marketers" = company sourcing suppliers = BUYER, never a seller.
- NON-ENGLISH posts = reject (we serve English-speaking markets only).
- If lead_type is "agency" or "irrelevant", is_lead MUST be false regardless of score.

Return ONLY valid JSON, nothing else."""

    def _qualify_one(lead: dict) -> dict | None:
        """Score a single lead. Returns the lead (mutated) or None if rejected."""
        post_text = lead.get("post_text", "")[:3000]
        headline = lead.get("headline", "")[:500]
        company = lead.get("company", "")[:200]
        location = lead.get("location", "")[:100]
        full_name = lead.get("full_name", "?")

        prompt = PROMPT_TEMPLATE.format(
            query=query, post_text=post_text,
            headline=headline, company=company, location=location,
        )
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
                max_tokens=700,
                response_format={"type": "json_object"}
            )
            result = json.loads(resp.choices[0].message.content)
        except Exception as e:
            logger.error(f"[AI Qualify] Error for {full_name}: {e}")
            # On error, be LENIENT - accept the lead
            lead["ai_qualified"] = True
            lead["ai_score"] = 50
            lead["lead_type"] = "problem_awareness"
            lead["work_type"] = "unknown"
            lead["ai_reason"] = "AI call failed — accepted on error"
            lead["outreach_angle"] = ""
            logger.info(f"[AI Qualify] ACCEPTED on error: {full_name}")
            return lead

        work_type = (result.get("work_type") or "unknown").lower()
        is_hiring = result.get("lead_type") == "hiring"
        # HARD RULE: only remote / contract / part-time hiring leads
        if is_hiring and work_type == "full_time_onsite":
            logger.info(f"[AI Qualify] FILTERED OUT {full_name} - on-site/full-time job, not remote/contract/part-time")
            return None
        logger.info(f"[AI Qualify DEBUG] {full_name} -> is_lead={result.get('is_lead')}, score={result.get('lead_score')}, type={result.get('lead_type')}, work={work_type}, reason={(result.get('reason') or '')[:100]}")

        if result.get("is_lead") and result.get("lead_score", 0) >= 25:
            lead["ai_qualified"] = True
            lead["ai_score"] = result.get("lead_score")
            lead["lead_type"] = result.get("lead_type", "potential")
            lead["work_type"] = work_type
            lead["business_problem"] = result.get("business_problem", False)
            lead["service_match"] = result.get("service_match", False)
            lead["buying_intent"] = result.get("buying_intent", 0)
            lead["urgency"] = result.get("urgency", 0)
            lead["decision_maker_likelihood"] = result.get("decision_maker_likelihood", 0)
            lead["outreach_worthiness"] = result.get("outreach_worthiness", 0)
            lead["ai_reason"] = result.get("reason", "")
            lead["outreach_angle"] = result.get("outreach_angle", "")
            logger.info(f"[AI Qualify] KEPT {full_name} (score: {result.get('lead_score')}, type: {result.get('lead_type')}, work: {work_type})")
            return lead
        else:
            logger.info(f"[AI Qualify] FILTERED OUT {full_name} - score: {result.get('lead_score')}, type: {result.get('lead_type')}, reason: {result.get('reason')}")
            return None

    if not leads:
        return []

    qualified: list[dict] = []
    with ThreadPoolExecutor(max_workers=AI_QUALIFY_CONCURRENCY) as pool:
        results = list(pool.map(_qualify_one, leads))
    qualified = [r for r in results if r is not None]
    return qualified


async def generate_search_queries(client, niche: str, lead_types: list[str], iteration: int, existing_leads: list[dict]) -> list[str]:
    """Generate HIGHLY EFFECTIVE LinkedIn search queries using GPT-4o-mini."""
    if not client:
        return build_boolean_query(niche)[:4]

    # Build context about what we already found
    found_summary = ""
    if existing_leads:
        types_found = {}
        for l in existing_leads:
            t = l.get("post_type", "unknown")
            types_found[t] = types_found.get(t, 0) + 1
        found_summary = f"Already found: {types_found}. Need more of: {', '.join(lead_types)}. "

    wants_buyer = "buyer" in lead_types
    wants_agency = "agency" in lead_types
    wants_hiring = "hiring" in lead_types

    prompt = f"""Generate 8 HIGHLY EFFECTIVE LinkedIn search queries to find '{niche}' posts.

Target lead types: {', '.join(lead_types)}
{found_summary}
Iteration: {iteration}

CRITICAL: Generate queries that match EXACT phrases real people type on LinkedIn.

{"BUYER INTENT (people NEEDING services):" if wants_buyer else ""}
{"- \"I need a " + niche + "\" | \"I'm looking for a " + niche + "\" | \"We need " + niche + " for our business\"" if wants_buyer else ""}
{"- \"Can anyone recommend a good " + niche + "?\" | \"Who does " + niche + "?\" | \"Looking to hire " + niche + "\"" if wants_buyer else ""}
{"- \"Need help with " + niche + "\" | \"Struggling with " + niche + "\" | \"Budget for " + niche + "\"" if wants_buyer else ""}
{"- \"Urgent: need " + niche + "\" | \"ASAP " + niche + "\" | \"Hiring a " + niche + " expert\"" if wants_buyer else ""}

{"AGENCY/SELLER INTENT (people OFFERING services):" if wants_agency else ""}
{"- \"We offer " + niche + "\" | \"Our agency provides " + niche + "\" | \"I provide " + niche + " services\"" if wants_agency else ""}
{"- \"Freelance " + niche + " available\" | \"Taking new " + niche + " clients\" | \"Book a call for " + niche + "\"" if wants_agency else ""}
{"- \"We specialize in " + niche + "\" | \"Starting at $ for " + niche + "\" | \"DM for " + niche + " quote\"" if wants_agency else ""}

{"HIRING INTENT (companies HIRING):" if wants_hiring else ""}
{"- \"We're hiring a " + niche + "\" | \"Join our team as " + niche + "\" | \"Open position: " + niche + "\"" if wants_hiring else ""}
{"- \"Our company is hiring " + niche + "\" | \"Looking for a " + niche + " to join\"" if wants_hiring else ""}

STRICT RULES:
- Each query 3-8 words MAX
- NO generic terms like just "seo", "ui-ux", "website" - MUST include intent words
- Queries must be EXACT phrases people actually type on LinkedIn
- Prioritize BUYER intent queries (highest conversion)
- Return 8 queries MAX

Reply with JSON only:
{{
  "queries": ["query1", "query2", "query3", "query4", "query5", "query6", "query7", "query8"]
}}"""

    try:
        resp = await asyncio.to_thread(
            lambda: client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a LinkedIn search query expert generating buyer-intent queries. Output only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=400,
                response_format={"type": "json_object"}
            )
        )
        result = json.loads(resp.choices[0].message.content)
        return result.get("queries", [])[:6]
    except Exception as e:
        logger.error(f"[AI Query Gen] Error: {e}")
        return build_boolean_query(niche)[:4]


# Service-specific job search queries for hiring leads
SERVICE_JOB_QUERIES = {
    "marketing": ["Marketing Manager", "Digital Marketing Specialist", "Growth Marketing", "Performance Marketing"],
    "seo": ["SEO Specialist", "SEO Manager", "Search Engine Optimization", "Technical SEO"],
    "motion graphic": ["Motion Designer", "Motion Graphics Artist", "Video Editor", "After Effects"],
    "smm": ["Social Media Manager", "Social Media Specialist", "Community Manager"],
    "graphic design": ["Graphic Designer", "Visual Designer", "Brand Designer", "UI Designer"],
    "shopify": ["Shopify Developer", "Shopify Expert", "Ecommerce Developer"],
    "ecommerce": ["Ecommerce Manager", "Ecommerce Specialist", "Shopify Manager"],
}

def get_job_queries_for_niche(niche: str) -> list[str]:
    """Get relevant job search queries for a niche."""
    niche_lower = niche.lower()
    for key, queries in SERVICE_JOB_QUERIES.items():
        if key in niche_lower:
            return queries
    # Default: use the niche as-is plus common variations
    return [niche, f"{niche} specialist", f"{niche} manager"]


async def run_linkedin_pipeline(
    search_id: str,
    user_id: str,
    query: str,
    enrich_emails: bool,
    max_results: int,
    lead_types: list[str] = None,
    location: str = "",
) -> None:
    supabase = get_supabase_admin()
    max_results = max(1, min(max_results, MAX_RESULTS_CAP))
    if lead_types is None:
        lead_types = ["buyer", "agency", "hiring"]

    req_country_codes, req_city = _parse_location_request(location or "")
    logger.info(
        f"[LinkedInPipeline:{search_id}] location='{location}' → "
        f"countries={req_country_codes or 'default-allowed'} city={req_city or ''}"
    )

    settings = get_settings()
    openai_client = None
    if settings.openai_api_key:
        from openai import OpenAI
        openai_client = OpenAI(api_key=settings.openai_api_key)

    all_leads: list[dict] = []
    all_skipped = 0

    try:
        await _update_search(supabase, search_id, {
            "status": "scraping",
            "progress_percent": 5,
            "message": "Building intent queries...",
        })

        # MEGA-PARALLEL DISCOVERY: build ALL query angles up front and fire
        # them in ONE batch. run_post_search splits the queries across all
        # healthy Apify keys and runs them CONCURRENTLY — so 10 leads means
        # ~96 queries hit ~10-24 keys simultaneously in a single pass, not
        # round after round. Repeat only if still short.
        MAX_PASSES = 2
        seen_post_urls: set[str] = set()

        # All 8 query angles (12 queries each = up to 96 distinct phrases).
        all_phrases: list[str] = []
        all_phrases.extend(build_boolean_query(query))
        for variant in range(2, 9):
            all_phrases.extend(build_boolean_query_variant(query, variant))
        # Dedupe, cap to a sane number (harvest splits into <=12 groups/keys)
        seen_q: set[str] = set()
        final_phrases: list[str] = []
        for p in all_phrases:
            k = p.lower()
            if k not in seen_q:
                seen_q.add(k)
                final_phrases.append(p)
        final_phrases = final_phrases[:96]

        pass_no = 0
        while len(all_leads) < max_results and pass_no < MAX_PASSES:
            pass_no += 1
            remaining = max_results - len(all_leads)
            fetch_target = min(max(remaining * 6, 60), 150)
            logger.info(f"[LinkedInPipeline:{search_id}] Pass {pass_no}/{MAX_PASSES} — firing {len(final_phrases)} queries in parallel across keys (fetch {fetch_target})")

            await _update_search(supabase, search_id, {
                "progress_percent": 15,
                "message": f"Searching LinkedIn with {len(final_phrases)} intent queries in parallel...",
            })

            try:
                items = await asyncio.to_thread(run_post_search, final_phrases, fetch_target)
            except Exception as e:
                logger.error(f"[LinkedInPipeline:{search_id}] Pass {pass_no} post-search failed: {e}")
                if pass_no == 1:
                    raise
                break
            raw_count = len(items)
            logger.info(f"[LinkedInPipeline:{search_id}] Pass {pass_no} returned {raw_count} raw posts (parallel)")

            # Skip posts already seen in earlier passes.
            def _pid(it):
                return it.get("postId") or it.get("id") or it.get("url") or it.get("linkedinUrl")

            fresh = [it for it in items if _pid(it) not in seen_post_urls]
            for it in items:
                pid = _pid(it)
                if pid:
                    seen_post_urls.add(pid)
            logger.info(f"[LinkedInPipeline:{search_id}] Fresh posts this pass: {len(fresh)} (of {raw_count})")

            leads, skipped = process_items(fresh, max_results * 2, req_country_codes)
            all_skipped += skipped
            logger.info(f"[LinkedInPipeline:{search_id}] Candidates after parsing: {len(leads)} (skipped {skipped})")

            # Enrich authors (only scrapeforge results lack headlines).
            missing_headline = sum(1 for l in leads if not (l.get("headline") or "").strip())
            if leads and missing_headline > 0:
                enrich_urls = [l["linkedin_url"] for l in leads[:PROFILE_ENRICHMENT_CAP] if not (l.get("headline") or "").strip()]
                try:
                    profiles = await asyncio.to_thread(fetch_profile_details, enrich_urls, "basic")
                    by_url = {(p.get("url") or "").rstrip("/").lower(): p for p in profiles if isinstance(p, dict)}
                    for lead in leads:
                        p = by_url.get((lead.get("linkedin_url") or "").rstrip("/").lower())
                        if not p:
                            continue
                        lead["headline"] = (p.get("headline") or lead.get("headline") or "")[:500]
                        lead["company"] = _company_from_profile(p)
                        lead["location"] = _location_from_profile(p)
                        lead["connections_count"] = p.get("connectionsCount") or 0
                except Exception as e:
                    logger.warning(f"[LinkedInPipeline:{search_id}] Profile enrichment failed (continuing without): {e}")

            await _update_search(supabase, search_id, {
                "progress_percent": min(45 + pass_no * 4, 60),
                "message": f"Found {raw_count} posts this pass. AI qualifying...",
            })

            # AI qualify with semantic scoring
            leads = await qualify_leads_with_ai(leads, query, openai_client, lead_types)

            # Rank by AI score (highest first)
            leads.sort(key=lambda x: x.get("ai_score", 0), reverse=True)

            # Dedupe by author (keep highest scoring post per author).
            # Use clean URL (strip query params) so ?miniProfileUrn= variants merge.
            def _clean_url(u: str) -> str:
                return (u or "").split("?")[0].rstrip("/").lower()

            best_by_author = {}
            for lead in leads:
                author_url = lead.get("linkedin_url")
                if not author_url:
                    continue
                score = lead.get("ai_score", 0)
                key = _clean_url(author_url)
                if key not in best_by_author or score > best_by_author[key].get("ai_score", 0):
                    best_by_author[key] = lead
            leads = list(best_by_author.values())
            leads.sort(key=lambda x: x.get("ai_score", 0), reverse=True)

            # Filter by requested types using lead_type
            lead_type_mapping = {
                "buyer": ["explicit_need", "problem_awareness", "research"],
                "agency": ["agency"],
                "hiring": ["hiring"],
            }
            if lead_types and lead_types != ["buyer", "agency", "hiring"]:
                allowed_types = set()
                for lt in lead_types:
                    allowed_types.update(lead_type_mapping.get(lt, [lt]))
                leads = [l for l in leads if l.get("lead_type") in allowed_types]

            # Add to all_leads and dedupe again
            existing_urls = {_clean_url(l.get("linkedin_url")) for l in all_leads if l.get("linkedin_url")}
            new_leads = [l for l in leads if _clean_url(l.get("linkedin_url")) not in existing_urls]
            all_leads.extend(new_leads)

            logger.info(f"[LinkedInPipeline:{search_id}] Pass {pass_no}: +{len(new_leads)} qualified leads (total: {len(all_leads)}/{max_results})")

            # Keep looping until the requested count is met — next pass skips
            # already-seen posts and searches fresh angles.
            # (No early break: user asked for exactly this many leads.)

        # ALSO search for hiring leads via LinkedIn Job Scraper if "hiring" in lead_types
        if "hiring" in lead_types and len(all_leads) < max_results:
            await _update_search(supabase, search_id, {
                "progress_percent": 55,
                "message": f"Searching LinkedIn jobs for '{query}' (remote/contract/part-time US/Europe)...",
            })

            # Use more job queries when we still need many leads — up to 4
            # queries to fill the gap faster.
            remaining_need = max_results - len(all_leads)
            job_queries = get_job_queries_for_niche(query)[: min(4, max(2, remaining_need))]
            logger.info(f"[LinkedInPipeline:{search_id}] Job queries: {job_queries} (need {remaining_need} more)")

            async def _fetch_jobs(job_query: str) -> list[dict]:
                try:
                    # Hard timeout — the job actor can hang; never let it block
                    # the whole search for more than 60s.
                    jobs = await asyncio.wait_for(
                        asyncio.to_thread(
                            run_job_search,
                            query=job_query,
                            location="United States",
                            time_range="7d",
                            max_jobs=min(max_results, 20),
                        ),
                        timeout=60,
                    )
                    logger.info(f"[LinkedInPipeline:{search_id}] Job search '{job_query}' returned {len(jobs)} jobs")
                    return filter_jobs_by_work_type(jobs, ["Remote", "Part-time", "Contract"])
                except asyncio.TimeoutError:
                    logger.warning(f"[LinkedInPipeline:{search_id}] Job search '{job_query}' timed out — skipping")
                    return []
                except Exception as e:
                    logger.error(f"[LinkedInPipeline:{search_id}] Job search error for '{job_query}': {e}")
                    return []

            # Run all job queries IN PARALLEL — big speedup over sequential.
            job_results = await asyncio.gather(*[_fetch_jobs(q) for q in job_queries])
            for filtered_jobs in job_results:
                logger.info(f"[LinkedInPipeline:{search_id}] After work type filter: {len(filtered_jobs)} jobs")
                # Convert jobs to lead format
                for job in filtered_jobs:
                    company_url = (job.get("companyUrl") or "").strip()
                    job_url = (job.get("jobUrl") or "").strip()
                    linkedin_url = company_url or job_url
                    job_lead = {
                        "full_name": job.get("company") or "Unknown Company",
                        "headline": f"{job.get('title', '')} at {job.get('company', '')}",
                        "company": job.get("company", ""),
                        "location": job.get("location", ""),
                        "linkedin_url": linkedin_url,
                        "post_url": job.get("jobUrl", ""),
                        "post_text": job.get("descriptionText", "")[:3000],
                        "posted_at": _parse_posted_at(job.get("postedAt")),
                        "engagement_likes": 0,
                        "engagement_comments": 0,
                        "profile_picture_url": job.get("companyLogo", ""),
                        "connections_count": 0,
                        "lead_type": "hiring",
                        "job_work_type": job.get("workType", ""),
                        "job_salary": job.get("salary", ""),
                        "job_seniority": job.get("seniority", ""),
                        "job_function": job.get("jobFunction", ""),
                        "job_industry": job.get("companyIndustry", ""),
                    }
                    all_leads.append(job_lead)

        # Trim to max_results
        if len(all_leads) > max_results:
            all_leads = all_leads[:max_results]

        # User-requested country filter (slow pipeline)
        if req_country_codes:
            before = len(all_leads)
            all_leads = [l for l in all_leads if _country_ok(l, "requested", req_country_codes)]
            logger.info(f"[LinkedInPipeline:{search_id}] Country filter: {len(all_leads)}/{before} matched requested countries")

        # Count by lead_category based on ai_score
        hot = sum(1 for l in all_leads if l.get("ai_score", 0) >= 85)
        warm = len(all_leads) - hot

        if not all_leads:
            await _update_search(supabase, search_id, {
                "status": "completed",
                "progress_percent": 100,
                "message": "No relevant leads found after AI qualification.",
                "total_results": 0,
                "hot_leads": 0,
                "warm_leads": 0,
                "skipped": all_skipped,
                "emails_found": 0,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            return

        await _update_search(supabase, search_id, {
            "progress_percent": 85,
            "message": f"Saving {len(all_leads)} qualified leads ({hot} hot, {warm} warm)...",
        })

        lead_ids = await _save_leads(supabase, search_id, user_id, all_leads)

        emails_found = 0
        if enrich_emails and lead_ids:
            await _update_search(supabase, search_id, {
                "progress_percent": 80,
                "message": "Finding emails for your leads...",
            })
            emails_found = await _enrich_emails(supabase, search_id, user_id, all_leads, lead_ids)

        saved = len(lead_ids)
        total_skipped = max(0, raw_count - saved)
        suffix = f", {emails_found} emails" if emails_found else ""
        await _update_search(supabase, search_id, {
            "status": "completed",
            "progress_percent": 100,
            "message": f"Found {saved} leads{suffix}",
            "total_results": saved,
            "hot_leads": hot,
            "warm_leads": warm,
            "skipped": total_skipped,
            "emails_found": emails_found,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"[LinkedInPipeline:{search_id}] Completed — {saved} leads ({hot} hot, {warm} warm), {emails_found} emails")

    except ApifyError as e:
        logger.error(f"[LinkedInPipeline:{search_id}] Apify error: {e}", exc_info=True)
        await _update_search(supabase, search_id, {
            "status": "failed",
            "message": "LinkedIn scraper failed",
            "error_message": str(e),
        })
    except Exception as e:
        logger.error(f"[LinkedInPipeline:{search_id}] Unexpected error: {e}", exc_info=True)
        await _update_search(supabase, search_id, {
            "status": "failed",
            "message": "Search failed unexpectedly",
            "error_message": str(e),
        })


async def _save_leads(supabase, search_id: str, user_id: str, leads: list[dict]) -> list[str]:
    remaining_leads = await _get_remaining_leads(supabase, user_id)
    if remaining_leads <= 0:
        logger.warning(f"[LinkedInPipeline:{search_id}] Daily leads limit reached, skipping saves")
        return []

    existing = await asyncio.to_thread(
        lambda: supabase.table("leads")
        .select("linkedin_url")
        .eq("user_id", user_id)
        .neq("linkedin_url", "")
        .execute()
    )
    existing_urls = set((row.get("linkedin_url") or "") for row in (existing.data or []))

    lead_ids: list[str] = []
    for lead in leads:
        if remaining_leads <= 0:
            logger.warning(f"[LinkedInPipeline:{search_id}] Daily leads limit reached. Stopping at {len(lead_ids)} saved.")
            break
        linkedin_url = (lead.get("linkedin_url") or "").strip()
        if linkedin_url and linkedin_url in existing_urls:
            continue

        ai_score = lead.get("ai_score", 0)
        if ai_score >= 85:
            lead_category = "hot"
        else:
            lead_category = "warm"

        # Map AI semantic type to the post_type CHECK values the DB allows
        # (buyer / agency / hiring / job_seeker)
        ai_type = lead.get("lead_type") or ""
        if ai_type in ("explicit_need", "problem_awareness", "research"):
            post_type = "buyer"
        elif ai_type in ("agency",):
            post_type = "agency"
        elif ai_type in ("hiring",):
            post_type = "hiring"
        elif ai_type in ("job_seeker",):
            post_type = "job_seeker"
        else:
            post_type = "buyer"

        # Prepend work-type tag to headline so the UI shows Remote/Contract/Part-time
        work_label = {
            "remote": "🌍 Remote",
            "contract": "📄 Contract",
            "part_time": "⏱️ Part-time",
            "full_time_onsite": "🏢 On-site",
        }.get((lead.get("work_type") or "").lower())
        headline = lead.get("headline") or ""
        if work_label and headline:
            headline = f"{work_label} — {headline}"
        elif work_label:
            headline = work_label

        # Skip leads with empty linkedin_url (cannot dedupe or reference)
        if not linkedin_url:
            logger.warning(f"[LinkedInPipeline:{search_id}] Skipping lead '{lead.get('full_name')}' - empty linkedin_url")
            continue

        row = {
            "search_id": search_id,
            "user_id": user_id,
            "source": "linkedin",
            "business_name": lead.get("full_name") or "Unknown",
            "category": lead.get("company") or "LinkedIn",
            "full_address": lead.get("location") or "",
            "phone": "",
            "email_found": "",
            "website_url": "",
            "rating": None,
            "total_reviews": 0,
            "google_maps_link": "",
            "description": lead.get("post_text") or "",
            "lead_category": lead_category,
            "post_type": post_type,
            "linkedin_url": linkedin_url,
            "post_url": lead.get("post_url") or "",
            "post_text": lead.get("post_text") or "",
            "headline": headline,
            "profile_picture_url": lead.get("profile_picture_url") or "",
            "connections_count": lead.get("connections_count") or 0,
            "posted_at": lead.get("posted_at"),
            "ai_qualified": True,
            # column is constrained to 0..1 — store normalized score
            "ai_confidence_score": ai_score / 100.0,
            "ai_reason": lead.get("ai_reason"),
            "ai_pitch": lead.get("outreach_angle"),
        }
        try:
            response = await asyncio.to_thread(
                lambda: supabase.table("leads").insert(row).execute()
            )
            if response.data and len(response.data) > 0:
                lead_ids.append(response.data[0]["id"])
                remaining_leads -= 1
                if linkedin_url:
                    existing_urls.add(linkedin_url)
        except Exception as e:
            logger.error(f"[LinkedInPipeline:{search_id}] Failed to save lead '{lead.get('full_name', '?')}': {e}")
    return lead_ids


async def _get_remaining_leads(supabase, user_id: str) -> int:
    from app.services.plans import remaining_leads_today
    try:
        return await asyncio.to_thread(remaining_leads_today, supabase, user_id)
    except Exception as e:
        logger.warning(f"[LinkedInPipeline] remaining-leads calc failed, defaulting: {e}")
        return 50


async def _enrich_emails(
    supabase, search_id: str, user_id: str, leads: list[dict], lead_ids: list[str]
) -> int:
    urls = []
    for lead in leads:
        url = (lead.get("linkedin_url") or "").strip()
        if url:
            urls.append(url)
    if not urls:
        return 0

    try:
        profiles = await asyncio.to_thread(enrich_profiles, urls, 50)
    except ApifyError as e:
        logger.warning(f"[LinkedInPipeline:{search_id}] Email enrichment failed: {e}")
        return 0

    email_by_identifier: dict[str, str] = {}
    location_by_identifier: dict[str, str] = {}
    company_by_identifier: dict[str, str] = {}
    for profile in profiles:
        identifier = profile.get("publicIdentifier") or ""
        if not identifier:
            continue
        emails = profile.get("emails") or []
        if emails:
            email_by_identifier[identifier] = emails[0]
        location = _location_from_profile(profile)
        if location:
            location_by_identifier[identifier] = location
        company = _company_from_profile(profile)
        if company:
            company_by_identifier[identifier] = company

    if not email_by_identifier:
        return 0

    emails_found = 0
    for idx, lead in enumerate(leads):
        if idx >= len(lead_ids):
            break
        identifier = _public_id_from_url(lead.get("linkedin_url") or "")
        email = email_by_identifier.get(identifier)
        if not email:
            continue
        try:
            update_data = {"email_found": email}
            location = location_by_identifier.get(identifier)
            if location:
                update_data["full_address"] = location
            company = company_by_identifier.get(identifier)
            if company:
                update_data["category"] = company
            await asyncio.to_thread(
                lambda: supabase.table("leads")
                .update(update_data)
                .eq("id", lead_ids[idx])
                .eq("user_id", user_id)
                .execute()
            )
            emails_found += 1
        except Exception as e:
            logger.warning(f"[LinkedInPipeline:{search_id}] Failed to attach email: {e}")
    return emails_found


def _public_id_from_url(url: str) -> str:
    try:
        part = url.split(".com/in/", 1)[1]
        return part.split("/")[0].split("?")[0]
    except Exception:
        return ""


async def _update_search(supabase, search_id: str, data: dict) -> None:
    try:
        await asyncio.to_thread(
            lambda: supabase.table("searches").update(data).eq("id", search_id).execute()
        )
    except Exception as e:
        logger.error(f"[LinkedInPipeline:{search_id}] Failed to update search: {e}")


# ══════════════════════════════════════════════════════════════════════════
# FAST PIPELINE — N selected leads → N parallel Apify lanes + async OpenAI
# ══════════════════════════════════════════════════════════════════════════

# Max concurrent OpenAI calls during async qualification. gpt-4o-mini TPM
# budget is 200k tokens/call-org-min; each qualification call is ~1.7k
# tokens, so 12 concurrent keeps us comfortably under the ceiling.
AI_ASYNC_CONCURRENCY = 12

# Acceptance tiers for the guarantee loop. Applied to ALREADY-SCORED leads,
# so relaxing costs zero extra API calls. Only two gates: strict quality
# first (25), absolute last resort (10).
TIER_1 = {"min_score": 25, "country": "allowed"}   # strict — best quality
TIER_FINAL = {"min_score": 10, "country": "any"}   # last resort
TIERS = [TIER_1, TIER_FINAL]

# ── Persistent guarantee loop limits ──────────────────────────────────────
MAX_WAVES = 4                 # hunt up to 4 waves (down from 5 — saves Apify credits)
WAVE_DEADLINE_SECONDS = 480   # never hunt longer than 8 minutes total
TRIAGE_BATCH_SIZE = 20        # posts per cheap triage call
TRIAGE_CONCURRENCY = 12
DEEP_SCORE_CAP = 40           # max survivors sent to full GPT scoring (down from 90)


async def triage_candidates_async(
    candidates: list[dict],
    query: str,
    client=None,
    concurrency: int = TRIAGE_CONCURRENCY,
) -> list[dict]:
    """Stage-1 CHEAP screening of EVERY parsed post (no engagement bias).

    Batches of 20 posts per call ask gpt-4o-mini ONLY one question: does the
    author show BUYING/HIRING intent for this service? Sellers, thought-
    leadership, job-seekers and non-English posts are dropped here so the
    expensive deep scorer only sees genuine prospects. Costs ~500 tokens per
    batch — screening 300 posts costs less than deep-scoring 15.
    """
    import json as _json

    if not candidates:
        return []
    if client is None:
        return candidates  # no key configured → don't gate, let deep stage decide

    SYSTEM = """You triage LinkedIn posts for a B2B lead-generation CRM. For each numbered post decide if the AUTHOR shows BUYING signal for the given service: they need it done, are hiring a freelancer/contractor/agency (remote/contract/part-time), ask for recommendations of providers, or describe a business problem needing this service.

KEEP (always include): posts mentioning "hiring", "looking for", "need", "want", "seeking", "we're hiring", "urgent hiring", "freelance", "contract", "remote", "part-time", "join our team", "we are looking for", "join us"; posts from companies/individuals actively recruiting for roles related to the service niche; posts asking for recommendations of service providers.

REJECT (do NOT keep): freelancers/agents SELLING their own services ("I offer", "available for", portfolio posts, "I'm a [service] specialist"); pure content/tips/opinions/case-studies; job-seekers describing their own availability; students; non-English posts.

When in doubt, KEEP — better to pass a marginal lead than lose a genuine buyer. Output strict JSON."""

    USER_TMPL = """Service niche: {query}

Posts:
{posts}

Return JSON: {{"keep": [post numbers showing buying/hiring intent]}}"""

    sem = asyncio.Semaphore(concurrency)
    batches = [candidates[i:i + TRIAGE_BATCH_SIZE] for i in range(0, len(candidates), TRIAGE_BATCH_SIZE)]

    async def _triage_batch(batch_idx: int, batch: list[dict]) -> list[int]:
        lines = []
        for j, c in enumerate(batch):
            head = f"{c.get('full_name','?')} | {c.get('company') or c.get('headline','')[:80]}"
            text = (c.get('post_text') or '')[:400].replace('\n', ' ')
            lines.append(f"{j}. [{head}] {text}")
        prompt = USER_TMPL.format(query=query, posts="\n".join(lines))
        async with sem:
            try:
                resp = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.0,
                    max_tokens=80,
                    response_format={"type": "json_object"},
                )
                data = _json.loads(resp.choices[0].message.content)
                keep = data.get("keep", [])
                return [int(k) for k in keep if isinstance(k, (int, float)) and 0 <= int(k) < len(batch)]
            except Exception as e:
                # Triage must never LOSE candidates on error → keep whole batch
                logger.warning(f"[Triage] batch {batch_idx} failed ({str(e)[:100]}) — keeping all {len(batch)}")
                return list(range(len(batch)))

    results = await asyncio.gather(*[_triage_batch(i, b) for i, b in enumerate(batches)])
    kept: list[dict] = []
    for batch, keep_idx in zip(batches, results):
        kept.extend(batch[k] for k in keep_idx)

    logger.info(f"[LinkedInPipeline] Triage: {len(kept)}/{len(candidates)} posts show buying/hiring intent")
    return kept


def _job_country_ok(job: dict, req_country_codes: set[str]) -> bool:
    """Does a job posting's location text match the requested countries?"""
    loc = (job.get("location") or "").lower()
    if not loc or "remote" in loc:
        return True  # Remote — could be anywhere, allow
    if any(name in loc for name, code in COUNTRY_NAME_TO_CODE.items() if code in req_country_codes):
        return True
    if any(city in loc for city, code in CITY_COUNTRY_HINTS.items() if code in req_country_codes):
        return True
    return True  # Unknown location — allow (cannot verify)


def _country_ok(lead: dict, mode: str, req_country_codes: set[str] | None = None) -> bool:
    """Country gate. mode='any' → always OK.
    req_country_codes set → lead must match one of those countries
    (unknown-country leads are rejected only if they look like a blocked
    market; otherwise allowed — queries are location-scoped)."""
    if mode == "any":
        return True
    cc = lead.get("country_code") or ""
    if req_country_codes:
        if cc:
            return cc in req_country_codes
        # Unknown country + user explicitly requested a location — allow
        # (cannot verify; the scrape queries were location-scoped and the
        # AI gates still judge relevance).
        return True
    if not cc:
        # Unknown country: apply the cheap heuristics from discovery phase.
        return not (
            _looks_south_asian(lead.get("full_name") or "")
            or any(k in (lead.get("headline") or "").lower() for k in (
                "india", "pakistan", "bangladesh", "manila", "lagos", "nairobi"))
        )
    return cc in ALLOWED_COUNTRY_CODES


def _type_ok(lead: dict, allowed_types: set[str] | None) -> bool:
    if not allowed_types:
        return True
    return lead.get("lead_type") in allowed_types


# Lead type mapping: UI selection → AI lead_type values
_LEAD_TYPE_MAP = {
    # "buyer" = people/companies needing freelancers — includes
    # contract/freelance hiring posts (a company hiring a freelance
    # designer IS a freelancer-need).
    "buyer": ["explicit_need", "problem_awareness", "research", "hiring"],
    "agency": ["agency"],
    "hiring": ["hiring"],
}


def tier_filter(scored: list[dict], lead_types: list[str], tier: dict, req_country_codes: set[str] | None = None) -> list[dict]:
    """Filter scored leads by a relaxation tier.

    Returns (accepted_leads, rejected_author_urls). Rejected URLs are
    authors whose ONLY post failed this tier — they may pass a looser tier.
    """
    all_types = lead_types is None or set(lead_types) == {"buyer", "agency", "hiring"}
    allowed = None
    if not all_types:
        allowed = set()
        for lt in lead_types or []:
            allowed.update(_LEAD_TYPE_MAP.get(lt, [lt]))

    accepted: list[dict] = []
    for lead in scored:
        score = lead.get("ai_score", 0) or 0
        if score < tier["min_score"]:
            continue
        if not _country_ok(lead, tier["country"], req_country_codes):
            continue
        if not _type_ok(lead, allowed):
            continue
        accepted.append(lead)
    return accepted


def split_lane_phrases(pool: list[str], n_lanes: int, per_lane_cap: int = 12) -> tuple[list[list[str]], list[str]]:
    """Split the phrase pool into n_lanes chunks (+ leftover phrases for wave 2)."""
    pool = list(dict.fromkeys(p.strip() for p in pool if p.strip()))
    per_lane = min(per_lane_cap, max(4, len(pool) // n_lanes))
    lanes, used = [], 0
    for i in range(n_lanes):
        chunk = pool[used : used + per_lane]
        if not chunk:
            break
        lanes.append(chunk)
        used += len(chunk)
    return lanes, pool[used:]


async def qualify_leads_with_ai_async(
    leads: list[dict],
    query: str,
    client=None,
    concurrency: int = AI_ASYNC_CONCURRENCY,
) -> list[dict]:
    """Async twin of qualify_leads_with_ai — SAME prompts & rules (quality
    unchanged), but all OpenAI calls fire concurrently via AsyncOpenAI +
    semaphore instead of a 5-worker thread pool."""
    import json as _json

    if not leads:
        return []
    if client is None:
        settings = get_settings()
        if not settings.openai_api_key:
            logger.warning("OpenAI API key not configured, skipping AI qualification")
            for l in leads:
                l.setdefault("ai_qualified", True)
                l.setdefault("ai_score", 50)
                l.setdefault("lead_type", "problem_awareness")
                l.setdefault("work_type", "unknown")
            return leads
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.openai_api_key)

    SYSTEM_PROMPT = """You are a senior B2B lead qualification specialist for an AI-powered lead-generation platform. You decide whether a LinkedIn post is a genuine BUYING signal that a service provider could convert into a client. Your decisions feed a CRM, so precision matters more than recall: one excellent lead is worth more than ten noise records.

WORKFLOW — always follow these steps in order:
1. Read the post and identify the AUTHOR's role (headline/company).
2. Determine WHO IS THE SUBJECT: is the author BUYING this service, or SELLING their own labor/services?
3. Identify the work arrangement (remote / contract / part-time / full-time on-site).
4. Apply the hard rules below.
5. Score the six dimensions, then compute lead_score.
6. Cross-check internal consistency before emitting JSON.

HARD RULES (never violate):
- R1: A company/owner HIRING a freelancer/contractor/agency on a REMOTE, CONTRACT or PART-TIME basis = STRONG LEAD.
- R2: A company hiring a FULL-TIME ON-SITE employee = NOT a lead (is_lead=false). They are building a payroll team, not buying your service.
- R3: The author SELLING their own services ("I'm available", "open to projects", "seeking contract work", "DM me for work", "I offer X", "my services include") = NEVER a lead, regardless of how well the post matches the niche.
- R4: A RECRUITER/STAFFING agency posting on behalf of clients = NOT a lead.
- R5: Job seekers looking for a role for themselves = NOT a lead.
- R6: Pure content/thought-leadership ("5 tips", "why you need", "trends", "case study", "opinion") = NOT a lead even if it scores high on service_match.
- R7: NON-ENGLISH posts (Spanish, German, French, Hindi, Arabic, etc.) = NOT a lead (is_lead=false). We only serve English-speaking markets. If the post is mostly in another language, reject it even if it describes hiring.

WHO IS THE SUBJECT? (the single most important question)
SELLING (reject): "I'm available for X", "I'm open to remote work", "I'm seeking projects", "Looking to collaborate", "I offer X", "DM me for X", "I provide X", "My services include", "I build X". Headline reads "Freelance X" and the post promotes their availability.
BUYING (accept): "We're looking for a developer", "I need a website", "Looking for someone to build our X", "We are hiring a freelance X for a project", "Need a designer on contract", "Anyone know a good agency?", "Recommendations for X services?", or a business describing a problem it needs solved (traffic drop, no website, bad conversions, launching a product).
"Looking for partners/agencies/marketers/freelancers" = SOURCING suppliers = BUYER.
RECRUITER EXCEPTION: staffing agency placing candidates at THIRD-PARTY clients = reject. BUT a firm saying "Experts required for our projects" = BUYING expertise = ACCEPT (lead_type="hiring").

SCORING (six dimensions, then total):
- service_match (0-25): direct mention = 25; adjacent problem = 20; general growth = 15; vague = 10; unrelated = 0.
- business_problem (0-20): metrics declining/explicit build = 20; clear pain = 15; dissatisfaction = 10; exploring = 5; none = 0.
- buying_intent (0-20): explicit vendor search with budget/ASAP = 20; HIRING freelancer/remote/part-time = 18; strong implicit ("recommendations?") = 15; problem + commercial context = 10; passive = 5; none = 0.
- decision_maker_likelihood (0-15): Founder/CEO/Owner/VP/Director = 15; Manager/Lead = 12; unclear but business context = 10; individual contributor = 5; student = 0.
- urgency (0-10): urgent/ASAP = 10; looking now = 8; soon = 7; active problem no timeline = 5; none = 0.
- outreach_worthiness (0-10): explicit vendor search + problem + decision maker = 10; strong problem + reachable role = 8; clear problem unclear authority = 6; vague = 4; wrong audience = 0.

lead_score = sum (0-100).
TIERS: 85+ HOT, 70-84 WARM, 40-69 POTENTIAL, 25-39 BORDERLINE, <25 NOT a lead.

CONSISTENCY: is_lead=true requires lead_score>=25 AND service_match>=10. hiring+full_time_onsite => is_lead=false. agency/irrelevant => is_lead=false.

OUTREACH_ANGLE: reference a SPECIFIC detail from their post/company; never generic; 1 sentence under 25 words.

Always output valid JSON only."""

    PROMPT_TEMPLATE = """Analyze this LinkedIn post for a business offering: {query}

--- POST CONTENT ---
{post_text}

--- AUTHOR HEADLINE ---
{headline}

--- AUTHOR COMPANY ---
{company}

--- AUTHOR LOCATION ---
{location}

STEP 1 — Who is the subject? A) BUYING B) SELLING C) recruiter/job-seeker/content. If B or C → is_lead=false.
STEP 2 — If A: remote/contract/freelance/part-time → VALID lead; full-time on-site → is_lead=false.
STEP 3 — Score the six dimensions honestly. Vague posts 40-55, strong hiring posts 80+.
STEP 4 — Verify consistency (is_lead=true requires score>=25 AND service_match>=10).

Output EXACTLY this JSON:
{{
  "is_lead": true/false,
  "lead_score": 0-100,
  "service_match": 0-25,
  "business_problem": 0-20,
  "buying_intent": 0-20,
  "decision_maker_likelihood": 0-15,
  "urgency": 0-10,
  "outreach_worthiness": 0-10,
  "lead_type": "explicit_need|problem_awareness|research|hiring|agency|irrelevant",
  "work_type": "remote|contract|part_time|full_time_onsite|unknown",
  "reason": "1-2 sentences with SPECIFIC quoted evidence",
  "outreach_angle": "one specific opening line referencing their exact situation (max 25 words)"
}}

Return ONLY valid JSON."""

    sem = asyncio.Semaphore(concurrency)

    # Shared TPM cooldown: when any call hits a 429, ALL tasks pause until
    # this timestamp. Single event loop → no lock needed.
    cooldown_until = 0.0
    import re as _re

    def _retry_wait_ms(err_text: str, attempt: int) -> float:
        m = _re.search(r"try again in (\d+)ms", err_text)
        if m:
            return int(m.group(1)) + 150
        return (1.5 ** attempt) * 1000 + 250

    async def _one(lead: dict) -> dict | None:
        nonlocal cooldown_until
        async with sem:
            post_text = lead.get("post_text", "")[:3000]
            prompt = PROMPT_TEMPLATE.format(
                query=query,
                post_text=post_text,
                headline=lead.get("headline", "")[:500],
                company=lead.get("company", "")[:200],
                location=lead.get("location", "")[:100],
            )
            result = None
            # Up to 4 attempts with adaptive backoff on rate limits.
            for attempt in range(4):
                pause = cooldown_until - asyncio.get_event_loop().time()
                if pause > 0:
                    await asyncio.sleep(pause)
                try:
                    resp = await client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.0,
                        max_tokens=700,
                        response_format={"type": "json_object"},
                    )
                    result = _json.loads(resp.choices[0].message.content)
                    break
                except Exception as e:
                    err_text = str(e)
                    if "rate_limit" in err_text or "429" in err_text:
                        # Cool the WHOLE org briefly so parallel calls drain.
                        cooldown_until = asyncio.get_event_loop().time() + 2.0
                        if attempt < 3:
                            await asyncio.sleep(_retry_wait_ms(err_text, attempt) / 1000.0)
                            continue
                    logger.warning(f"[FastQualify] dropping {lead.get('full_name', '?')} after {attempt + 1} attempts: {err_text[:120]}")
                    return None  # NEVER accept unqualified — quality first

            if result is None:
                return None

        work_type = (result.get("work_type") or "unknown").lower()
        if result.get("lead_type") == "hiring" and work_type == "full_time_onsite":
            return None  # hard rule: no on-site payroll hires
        if result.get("is_lead") and (result.get("lead_score", 0) >= 10):
            lead["ai_qualified"] = True
            lead["ai_score"] = result.get("lead_score")
            lead["lead_type"] = result.get("lead_type", "potential")
            lead["work_type"] = work_type
            lead["ai_reason"] = result.get("reason", "")
            lead["outreach_angle"] = result.get("outreach_angle", "")
            return lead
        return None

    results = await asyncio.gather(*[_one(l) for l in leads])
    qualified = [r for r in results if r is not None]
    logger.info(f"[FastQualify] {len(qualified)}/{len(leads)} candidates passed AI gate")
    return qualified


async def _save_leads_bulk(supabase, search_id: str, user_id: str, leads: list[dict]) -> list[str]:
    """Bulk-insert leads in ONE Supabase call (per-row fallback on error).
    Respects the user's daily remaining-leads limit."""
    remaining_leads = await _get_remaining_leads(supabase, user_id)
    if remaining_leads <= 0:
        logger.warning(f"[LinkedInPipeline:{search_id}] Daily leads limit reached, skipping saves")
        return []

    rows: list[dict] = []
    for lead in leads[:remaining_leads]:
        ai_score = lead.get("ai_score", 0) or 0
        lead_category = "hot" if ai_score >= 85 else "warm"

        ai_type = lead.get("lead_type") or ""
        if ai_type in ("explicit_need", "problem_awareness", "research"):
            post_type = "buyer"
        elif ai_type == "agency":
            post_type = "agency"
        elif ai_type == "hiring":
            post_type = "hiring"
        elif ai_type == "job_seeker":
            post_type = "job_seeker"
        else:
            post_type = "buyer"

        work_label = {
            "remote": "🌍 Remote",
            "contract": "📄 Contract",
            "part_time": "⏱️ Part-time",
            "full_time_onsite": "🏢 On-site",
        }.get((lead.get("work_type") or "").lower())
        headline = lead.get("headline") or ""
        if work_label and headline:
            headline = f"{work_label} — {headline}"
        elif work_label:
            headline = work_label

        linkedin_url = (lead.get("linkedin_url") or "").strip()
        rows.append({
            "search_id": search_id,
            "user_id": user_id,
            "source": "linkedin",
            "business_name": lead.get("full_name") or "Unknown",
            "category": lead.get("company") or "LinkedIn",
            "full_address": lead.get("location") or "",
            "phone": "",
            "email_found": "",
            "website_url": "",
            "rating": None,
            "total_reviews": 0,
            "google_maps_link": "",
            "description": lead.get("post_text") or "",
            "lead_category": lead_category,
            "post_type": post_type,
            "linkedin_url": linkedin_url,
            "post_url": lead.get("post_url") or "",
            "post_text": lead.get("post_text") or "",
            "headline": headline,
            "profile_picture_url": lead.get("profile_picture_url") or "",
            "connections_count": lead.get("connections_count") or 0,
            "posted_at": lead.get("posted_at"),
            "ai_qualified": True,
            "ai_confidence_score": min(ai_score, 100) / 100.0,
            "ai_reason": lead.get("ai_reason"),
            "ai_pitch": lead.get("outreach_angle"),
        })

    if not rows:
        return []

    # DEDUPLICATION: before inserting, remove leads whose linkedin_url
    # already exists for this user. Prevents duplicates across searches.
    try:
        existing = await asyncio.to_thread(
            lambda: supabase.table("leads").select("linkedin_url")
            .eq("user_id", user_id).neq("linkedin_url", "").execute()
        )
        existing_urls = {
            (r.get("linkedin_url") or "").split("?")[0].rstrip("/").lower()
            for r in (existing.data or [])
        }
        rows = [r for r in rows if (r.get("linkedin_url") or "").split("?")[0].rstrip("/").lower() not in existing_urls]
        if not rows:
            logger.info(f"[LinkedInPipeline:{search_id}] All {len(rows)} leads already exist for user — skipping insert")
            return []
    except Exception as e:
        logger.warning(f"[LinkedInPipeline:{search_id}] Dedup check failed ({e}) — proceeding with insert")

    try:
        response = await asyncio.to_thread(
            lambda: supabase.table("leads").insert(rows).execute()
        )
        if response.data:
            return [r["id"] for r in response.data]
        return []
    except Exception as e:
        logger.warning(f"[LinkedInPipeline:{search_id}] Bulk insert failed ({e}), falling back to per-row")
        lead_ids: list[str] = []
        for row in rows:
            try:
                response = await asyncio.to_thread(
                    lambda r=row: supabase.table("leads").insert(r).execute()
                )
                if response.data and len(response.data) > 0:
                    lead_ids.append(response.data[0]["id"])
            except Exception as row_err:
                logger.error(f"[LinkedInPipeline:{search_id}] Row insert failed for '{row.get('business_name')}': {row_err}")
        return lead_ids


async def run_linkedin_pipeline_fast(
    search_id: str,
    user_id: str,
    query: str,
    enrich_emails: bool,
    max_results: int,
    lead_types: list[str] = None,
    location: str = "",
) -> None:
    """GUARANTEED-COUNT fast pipeline.

    User selects N leads → N parallel Apify lanes (each on its own key)
    fire SIMULTANEOUSLY → all candidates scored by GPT-4o-mini with up to
    30 CONCURRENT async calls → tiered acceptance guarantees at least N
    fresh leads whenever they exist. Wave 2 lanes + job-scraper act as
    gap fillers. Quality ordering is always by ai_score desc.
    """
    supabase = get_supabase_admin()
    max_results = max(1, min(max_results, MAX_RESULTS_CAP))
    if lead_types is None:
        lead_types = ["buyer", "agency", "hiring"]

    # User-requested location → country codes (e.g. "Mumbai" → IN, "US" → US)
    req_country_codes, req_city = _parse_location_request(location or "")
    if req_country_codes & USER_REQUESTABLE_COUNTRIES:
        country_gate_mode = "requested"
    else:
        country_gate_mode = "requested" if req_country_codes else "default"
    logger.info(
        f"[LinkedInPipeline:{search_id}] location='{location}' → "
        f"countries={req_country_codes or 'default-allowed'} city={req_city or ''}"
    )

    settings = get_settings()
    openai_client = None
    if settings.openai_api_key:
        from openai import AsyncOpenAI
        openai_client = AsyncOpenAI(api_key=settings.openai_api_key)

    try:
        # ── Phase 0: prefetch user's already-saved author URLs so the
        # guarantee counts FRESH leads only (no silent dedupe shrink later).
        await _update_search(supabase, search_id, {
            "status": "scraping", "progress_percent": 3,
            "message": "Preparing parallel search...",
        })
        try:
            existing_resp = await asyncio.to_thread(
                lambda: supabase.table("leads").select("linkedin_url")
                .eq("user_id", user_id).neq("linkedin_url", "").execute()
            )
            known_urls = {
                (r.get("linkedin_url") or "").split("?")[0].rstrip("/").lower()
                for r in (existing_resp.data or [])
            }
        except Exception as e:
            logger.warning(f"[LinkedInPipeline:{search_id}] Known-url prefetch failed: {e}")
            known_urls = set()

        # ── HARD LIMIT: no daily leads left → fail fast WITHOUT burning
        # any Apify/OpenAI credits. User sees the upgrade prompt.
        remaining_now = await _get_remaining_leads(supabase, user_id)
        if remaining_now <= 0:
            logger.warning(f"[LinkedInPipeline:{search_id}] HARD STOP — daily lead limit already reached")
            await _update_search(supabase, search_id, {
                "status": "completed", "progress_percent": 100,
                "message": "Daily lead limit reached — upgrade your plan to get more leads.",
                "total_results": 0, "hot_leads": 0, "warm_leads": 0,
                "skipped": 0, "emails_found": 0,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            return

        # ── Phase 1: build phrase pool (cycled across guarantee waves).
        pool = list(build_boolean_query(query))
        for variant in range(2, 9):
            pool.extend(build_boolean_query_variant(query, variant))
        # CREDIT BUDGET: scale lanes and fetch count with request size.
        # 3 leads → 1 lane, 5 → 2, 10 → 2, 20 → 3, 50 → 3
        n_lanes = min(max_results, 3) if max_results >= 10 else (2 if max_results >= 5 else 1)
        lanes_check, _ = split_lane_phrases(pool, n_lanes)
        n_lanes = max(1, len(lanes_check))
        # raw_budget: generous cap — count×3 items, max 90
        raw_budget = min(max_results * 3, 90)
        fetch_per_lane = max(5, min(10, -(-raw_budget // n_lanes)))

        logger.info(
            f"[LinkedInPipeline:{search_id}] FAST start: {n_lanes} parallel lanes "
            f"(~{fetch_per_lane} posts each, raw budget {n_lanes * fetch_per_lane}), "
            f"{len(pool)}-phrase pool, up to {MAX_WAVES} waves / {WAVE_DEADLINE_SECONDS}s"
        )
        await _update_search(supabase, search_id, {
            "progress_percent": 8,
            "message": f"Firing {n_lanes} parallel LinkedIn searches...",
        })

        seen_post_ids: set[str] = set()
        raw_count_total = 0
        all_skipped = 0
        last_scored_candidates: list[dict] = []  # track scored candidates for final relaxation

        async def _run_wave_async(lane_list: list[list[str]]) -> list[dict]:
            results = await asyncio.gather(*[
                asyncio.to_thread(run_lane_search, lq, fetch_per_lane, "month")
                for lq in lane_list
            ])
            items: list[dict] = []
            ok_lanes = 0
            for lane_items in results:
                if lane_items:
                    ok_lanes += 1
                    items.extend(lane_items)
            logger.info(f"[LinkedInPipeline:{search_id}] wave done: {ok_lanes}/{len(lane_list)} lanes returned data")
            return items

        async def _process_items_to_candidates(items: list[dict]) -> tuple[list[dict], int]:
            fresh = []
            for it in items:
                pid = it.get("postId") or it.get("id") or it.get("url") or it.get("linkedinUrl")
                if pid and pid in seen_post_ids:
                    continue
                if pid:
                    seen_post_ids.add(pid)
                fresh.append(it)
            deduped = dedupe_post_items(fresh)
            # Keep EVERY parsed post (cap 400) — Stage-1 triage screens all of
            # them cheaply, so genuine low-engagement buyers are never lost to
            # viral-noise ranking.
            candidates, skipped = process_items(deduped, 400, req_country_codes)
            # Drop authors the user already has — BEFORE scoring (saves tokens).
            candidates = [
                c for c in candidates
                if (c.get("linkedin_url") or "").split("?")[0].rstrip("/").lower() not in known_urls
            ]
            return candidates, skipped

        # ── Phases 2-6: PERSISTENT GUARANTEE LOOP ─────────────────────────
        # Waves keep hunting (fresh angles → cheap intent-triage on EVERY
        # post → deep scoring on survivors → tiered absorption → job-postings
        # filler) until max_results leads are delivered or the wave/time
        # budget is exhausted. Accepted leads ACCUMULATE across waves.
        # Exact-count policy: the user asked for max_results leads, they get
        # EXACTLY max_results — no over-delivery, no wasted Apify/OpenAI credits.
        overdeliver_cap = max_results
        final_leads: list[dict] = []
        chosen_urls: set[str] = set()
        deadline = asyncio.get_event_loop().time() + WAVE_DEADLINE_SECONDS

        def _absorb(leads_in: list[dict]) -> int:
            """Accept tier-passing leads, best-scored first, into final list."""
            added = 0
            for l in sorted(leads_in, key=lambda x: x.get("ai_score", 0) or 0, reverse=True):
                if len(final_leads) >= overdeliver_cap:
                    break
                key = (l.get("linkedin_url") or "").split("?")[0].rstrip("/").lower()
                if key and key not in chosen_urls:
                    chosen_urls.add(key)
                    final_leads.append(l)
                    added += 1
            return added

        # Flat cycling phrase queue — repeated phrases are safe because
        # seen_post_ids drops already-processed posts across waves.
        flat_pool = list(dict.fromkeys(pool))
        flat_pos = {"i": 0}

        def _next_wave_lanes(count: int, per_lane: int) -> list[list[str]]:
            lane_list = []
            for _ in range(count):
                chunk = []
                for _ in range(per_lane):
                    chunk.append(flat_pool[flat_pos["i"] % len(flat_pool)])
                    flat_pos["i"] += 1
                lane_list.append(chunk)
            return lane_list

        async def _run_job_filler(need: int) -> int:
            """Hiring-intent filler from live job postings (strong buying signal)."""
            if need <= 0 or ("hiring" not in lead_types and "buyer" not in lead_types):
                return 0
            await _update_search(supabase, search_id, {
                "progress_percent": 70,
                "message": f"Adding hiring-intent leads from job postings ({need} more)...",
            })
            job_queries = get_job_queries_for_niche(query)[: min(4, max(2, need))]
            added = 0
            # Expand location for better coverage: user's location → major
            # cities in that country → Remote (global). For India, try
            # Bangalore/Mumbai/Delhi since LinkedIn job search is city-level.
            raw_loc = (location or "").strip()
            if raw_loc:
                expanded = [raw_loc]
                if "india" in raw_loc.lower():
                    expanded.extend(["Bangalore", "Mumbai", "Delhi", "Remote"])
                elif "united states" in raw_loc.lower():
                    expanded.extend(["New York", "San Francisco", "Remote"])
                else:
                    expanded.append("Remote")
                job_locations = expanded
            else:
                job_locations = ["United States", "Remote"]
            for job_loc in job_locations:
                if added >= need:
                    break
                try:
                    job_lists = await asyncio.gather(*[
                        asyncio.wait_for(
                            asyncio.to_thread(
                                run_job_search,
                                query=q,
                                location=job_loc,
                                time_range="7d",
                                max_jobs=min(need * 2, 20),
                            ),
                            timeout=60,
                        )
                        for q in job_queries
                    ])
                except Exception as e:
                    logger.warning(f"[LinkedInPipeline:{search_id}] job filler ({job_loc}) failed: {e}")
                    continue
                for jobs in job_lists:
                    # Accept ALL jobs — work type filter is unreliable for
                    # India locations. Country filter below handles quality.
                    filtered = jobs
                    # Country filter: drop jobs whose location text clearly
                    # doesn't match the user's requested country.
                    if req_country_codes:
                        filtered = [j for j in filtered if _job_country_ok(j, req_country_codes)]
                    logger.info(f"[LinkedInPipeline:{search_id}] job filler ({job_loc}): {len(filtered)} remote/contract jobs")
                    for job in filtered:
                        if len(final_leads) >= overdeliver_cap or added >= need:
                            break
                        company_url = (job.get("companyUrl") or "").strip()
                        job_url = (job.get("jobUrl") or "").strip()
                        linkedin_url = company_url or job_url
                        key = linkedin_url.split("?")[0].rstrip("/").lower()
                        if not linkedin_url or key in chosen_urls or key in known_urls:
                            continue
                        final_leads.append({
                            "full_name": job.get("company") or "Unknown Company",
                            "headline": f"{job.get('title', '')} at {job.get('company', '')}",
                            "company": job.get("company", ""),
                            "location": job.get("location", ""),
                            "linkedin_url": linkedin_url,
                            "post_url": job_url,
                            "post_text": (job.get("descriptionText") or "")[:3000],
                            "posted_at": _parse_posted_at(job.get("postedAt")),
                            "engagement_likes": 0,
                            "engagement_comments": 0,
                            "profile_picture_url": job.get("companyLogo", ""),
                            "connections_count": 0,
                            "ai_qualified": True,
                            "ai_score": 75,
                            "lead_type": "hiring",
                            "work_type": "contract",
                            "ai_reason": "Active LinkedIn job posting (remote/contract/part-time)",
                            "outreach_angle": "",
                            "country_code": "",
                        })
                        chosen_urls.add(key)
                        added += 1
            return added

        async def _hunt_wave(wave_no: int, lane_list: list[list[str]]) -> None:
            nonlocal raw_count_total, all_skipped
            remaining = max_results - len(final_leads)
            await _update_search(supabase, search_id, {
                "progress_percent": min(25 + wave_no * 13, 82),
                "message": f"Wave {wave_no}: hunting {remaining} more leads with {len(lane_list)} parallel searches...",
            })

            items = await _run_wave_async(lane_list)
            raw_count_total += len(items)
            candidates_w, skipped_w = await _process_items_to_candidates(items)
            all_skipped += skipped_w
            if not candidates_w:
                logger.info(f"[LinkedInPipeline:{search_id}] Wave {wave_no}: no fresh candidates")
                return

            # STAGE 1 — cheap buying-intent triage over EVERY parsed post.
            promising = await triage_candidates_async(candidates_w, query, openai_client)

            # Enrich ONLY triage survivors missing a headline (Apify cost control).
            missing = [c for c in promising if not (c.get("headline") or "").strip()]
            if missing:
                try:
                    enrich_urls = [c["linkedin_url"] for c in missing[:PROFILE_ENRICHMENT_CAP]]
                    profiles = await asyncio.to_thread(fetch_profile_details, enrich_urls, "basic")
                    by_url = {(p.get("url") or "").rstrip("/").lower(): p for p in profiles if isinstance(p, dict)}
                    for c in promising:
                        p = by_url.get((c.get("linkedin_url") or "").rstrip("/").lower())
                        if not p:
                            continue
                        c["headline"] = (p.get("headline") or c.get("headline") or "")[:500]
                        c["company"] = _company_from_profile(p) or c.get("company") or ""
                        c["location"] = _location_from_profile(p) or c.get("location") or ""
                except Exception as e:
                    logger.warning(f"[LinkedInPipeline:{search_id}] enrichment skipped: {e}")

            await _update_search(supabase, search_id, {
                "progress_percent": min(30 + wave_no * 13, 84),
                "message": f"Wave {wave_no}: {len(promising)} prospects found. AI scoring...",
            })

            # STAGE 2 — full semantic scoring on the best survivors only.
            survivors = promising[:DEEP_SCORE_CAP]
            scored_w = await qualify_leads_with_ai_async(survivors, query, openai_client)
            last_scored_candidates.extend(scored_w)  # track for final relaxation
            if scored_w:
                for sw in scored_w:
                    logger.info(
                        f"[LinkedInPipeline:{search_id}] scored: "
                        f"{sw.get('full_name', '?')[:20]} | type={sw.get('lead_type')} "
                        f"score={sw.get('ai_score')} cc={sw.get('country_code') or '?'}"
                    )

            for tier_idx, tier in enumerate(TIERS, 1):
                if len(final_leads) >= max_results:
                    break
                got = _absorb(tier_filter(scored_w, lead_types, tier, req_country_codes))
                logger.info(
                    f"[LinkedInPipeline:{search_id}] Wave {wave_no} Tier {tier_idx}: "
                    f"+{got} (total {len(final_leads)}/{max_results}, cap {overdeliver_cap})"
                )

            # Mid-loop filler: top up with job postings while still short.
            if len(final_leads) < max_results:
                added = await _run_job_filler(max_results - len(final_leads))
                if added:
                    logger.info(f"[LinkedInPipeline:{search_id}] Wave {wave_no} job filler: +{added}")

        wave_no = 0
        while len(final_leads) < max_results and wave_no < MAX_WAVES:
            if asyncio.get_event_loop().time() > deadline:
                logger.warning(f"[LinkedInPipeline:{search_id}] Wave deadline reached after {wave_no} waves")
                break
            if raw_count_total >= raw_budget:
                # DYNAMIC BUDGET: if still short, expand budget by 50% and continue
                remaining_needed = max_results - len(final_leads)
                if remaining_needed > 0 and wave_no < MAX_WAVES:
                    raw_budget = int(raw_budget * 1.5)
                    logger.info(
                        f"[LinkedInPipeline:{search_id}] Budget expanded to {raw_budget} "
                        f"(still need {remaining_needed} leads)"
                    )
                else:
                    logger.info(
                        f"[LinkedInPipeline:{search_id}] Apify raw budget reached "
                        f"({raw_count_total}/{raw_budget}) — stopping waves"
                    )
                    break
            wave_no += 1
            await _hunt_wave(wave_no, _next_wave_lanes(n_lanes, fetch_per_lane))

        # Final safety net: one last filler pass if somehow still short.
        if len(final_leads) < max_results:
            await _run_job_filler(max_results - len(final_leads))

        # FINAL RELAXATION: if still short after all waves, do one more pass
        # with relaxed gates (accept all lead types, lower score threshold).
        # This ensures the user gets EXACTLY the count they requested.
        if len(final_leads) < max_results:
            remaining_needed = max_results - len(final_leads)
            logger.info(
                f"[LinkedInPipeline:{search_id}] Final relaxation pass: "
                f"need {remaining_needed} more leads, relaxing gates"
            )
            # Collect ALL scored candidates from last wave (not just tier-filtered)
            all_scored = [s for s in last_scored_candidates if s.get("linkedin_url")]
            # Relax: lower score threshold (50), but STILL respect lead type.
            # User asked for specific types — don't give them wrong types.
            relax_allowed = set()
            for lt in (lead_types or []):
                relax_allowed.update(_LEAD_TYPE_MAP.get(lt, [lt]))
            for s in all_scored:
                if len(final_leads) >= max_results:
                    break
                if (s.get("ai_score") or 0) < 50:
                    continue
                # Type gate: still enforce user's requested types
                if relax_allowed and s.get("lead_type") not in relax_allowed:
                    continue
                key = (s.get("linkedin_url") or "").split("?")[0].rstrip("/").lower()
                if not key or key in chosen_urls or key in known_urls:
                    continue
                # Country gate still applies (don't violate user's location request)
                if not _country_ok(s, "any", req_country_codes):
                    continue
                final_leads.append(s)
                chosen_urls.add(key)
            if final_leads:
                logger.info(
                    f"[LinkedInPipeline:{search_id}] Final relaxation: +{len(final_leads)} total"
                )

        final_leads = final_leads[:overdeliver_cap]  # == max_results (exact count)

        # ── Phase 7: save (bulk) + optional email enrichment.
        hot = sum(1 for l in final_leads if (l.get("ai_score", 0) or 0) >= 85)
        warm = len(final_leads) - hot

        if not final_leads:
            await _update_search(supabase, search_id, {
                "status": "completed", "progress_percent": 100,
                "message": "No relevant leads found after AI qualification.",
                "total_results": 0, "hot_leads": 0, "warm_leads": 0,
                "skipped": all_skipped, "emails_found": 0,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            return

        await _update_search(supabase, search_id, {
            "progress_percent": 88,
            "message": f"Saving {len(final_leads)} leads ({hot} hot, {warm} warm)...",
        })
        lead_ids = await _save_leads_bulk(supabase, search_id, user_id, final_leads)

        saved = len(lead_ids)
        lead_limit_hit = saved < len(final_leads)  # plan cap truncated saves
        emails_found = 0
        if enrich_emails and lead_ids:
            await _update_search(supabase, search_id, {
                "progress_percent": 94, "message": "Finding emails for your leads...",
            })
            emails_found = await _enrich_emails(supabase, search_id, user_id, final_leads, lead_ids)

        suffix = f", {emails_found} emails" if emails_found else ""
        final_message = f"Found {saved} leads{suffix}"
        if lead_limit_hit:
            final_message += " | Daily lead limit reached — upgrade your plan for more."
        await _update_search(supabase, search_id, {
            "status": "completed", "progress_percent": 100,
            "message": final_message,
            "total_results": saved, "hot_leads": hot, "warm_leads": warm,
            "skipped": max(0, raw_count_total - saved),
            "emails_found": emails_found,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(
            f"[LinkedInPipeline:{search_id}] FAST completed — {saved}/{max_results} leads "
            f"({hot} hot), {emails_found} emails, limit_hit={lead_limit_hit}, {raw_count_total} raw posts"
        )

    except ApifyError as e:
        logger.error(f"[LinkedInPipeline:{search_id}] Apify error: {e}", exc_info=True)
        await _update_search(supabase, search_id, {
            "status": "failed", "message": "LinkedIn scraper failed", "error_message": str(e),
        })
    except Exception as e:
        logger.error(f"[LinkedInPipeline:{search_id}] Unexpected error: {e}", exc_info=True)
        await _update_search(supabase, search_id, {
            "status": "failed", "message": "Search failed unexpectedly", "error_message": str(e),
        })