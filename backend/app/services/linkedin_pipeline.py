"""
Hyperclients — LinkedIn Lead Engine (consolidated, single production truth)

THE authoritative LinkedIn lead-generation implementation. It contains, in one
place, the canonical intent model, location hard-gate, intent-specific query
generation, deterministic pre-filters, canonical acceptance + quality scoring,
telemetry and the exact-count iterative orchestrator. It delegates:

  - Discovery         -> app.services.apify_service  (actor, keys, lanes)
  - AI qualification  -> app.services.ai_service     (strict schema, fail-closed)

PRINCIPLE:
  find the EXACT number of genuinely qualified leads the user asked for, for
  the EXACT service, EXACT lead intent and EXACT country, and NEVER sacrifice
  correctness (wrong country / wrong intent / seller / job-seeker / wrong
  service) just to fill the requested count.

run_linkedin_pipeline_fast is the background-task entry point called by the
search router; it runs the engine and updates the searches row for polling.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)

from app.database import get_supabase_admin
from app.services.usage import settle_search_quota
from app.services.apify_service import (
    fetch_profile_details,
    run_lane_search,
)

# ══════════════════════════════════════════════════════════════════════════
# LOOP-SAFETY / ENGINE LIMITS
# ══════════════════════════════════════════════════════════════════════════
MAX_RESULTS_CAP = 50
MAX_ITERATIONS = 6
MAX_NO_PROGRESS_ITERATIONS = 3
WAVE_DEADLINE_SECONDS = 600
MAX_POSTS_PER_LANE = 15
# A single transient Apify total-failure (all lanes empty) must NOT abort
# discovery. Only stop after several consecutive provider failures AND make
# sure a partial (ok_lanes>0) run is never treated as provider failure. The
# engine later diversifies queries and retries, so a transient empty response
# typically resolves on the next iteration.
MAX_PROVIDER_FAIL_ROUNDS = 2
PROFILE_ENRICHMENT_CAP = 30

# Hard gates (canonical policy — no other threshold elsewhere).
MIN_QUALITY_SCORE = 60.0
MIN_SERVICE_MATCH = 50.0
MIN_INTENT_STRENGTH = "recommendation"

QUALITY_WEIGHTS = {
    "intent_strength": 0.30,
    "service_match": 0.25,
    "commercial_intent": 0.15,
    "decision_maker": 0.10,
    "location_confidence": 0.10,
    "evidence": 0.10,
}

# ══════════════════════════════════════════════════════════════════════════
# CANONICAL INTENT MODEL (single source of truth)
# ══════════════════════════════════════════════════════════════════════════
class LeadType(str, Enum):
    FREELANCER_NEEDED = "freelancer_needed"
    HIRING = "hiring"
    AGENCY_WANTED = "agency_wanted"
    IRRELEVANT = "irrelevant"
    UNKNOWN = "unknown"


REQUESTABLE_INTENTS = {LeadType.FREELANCER_NEEDED.value, LeadType.HIRING.value, LeadType.AGENCY_WANTED.value}

WIRE_TO_CANONICAL = {"buyer": LeadType.FREELANCER_NEEDED.value, "hiring": LeadType.HIRING.value, "agency_wanted": LeadType.AGENCY_WANTED.value}
CANONICAL_TO_WIRE = {LeadType.FREELANCER_NEEDED.value: "buyer", LeadType.HIRING.value: "hiring", LeadType.AGENCY_WANTED.value: "agency_wanted"}
CANONICAL_TO_POST_TYPE = {LeadType.FREELANCER_NEEDED.value: "buyer", LeadType.HIRING.value: "hiring", LeadType.AGENCY_WANTED.value: "agency_wanted", LeadType.IRRELEVANT.value: "unknown", LeadType.UNKNOWN.value: "unknown"}


def to_canonical(lead_type: str | None) -> str:
    if not lead_type:
        return LeadType.UNKNOWN.value
    lt = str(lead_type).strip().lower()
    if lt in REQUESTABLE_INTENTS:
        return lt
    if lt in WIRE_TO_CANONICAL:
        return WIRE_TO_CANONICAL[lt]
    aliases = {"agency": LeadType.AGENCY_WANTED.value, "freelancer": LeadType.FREELANCER_NEEDED.value,
               "freelancer_needed": LeadType.FREELANCER_NEEDED.value, "explicit_need": LeadType.FREELANCER_NEEDED.value,
               "problem_awareness": LeadType.FREELANCER_NEEDED.value, "research": LeadType.FREELANCER_NEEDED.value}
    return aliases.get(lt, LeadType.UNKNOWN.value)


def canonical_to_post_type(lead_type: str | None) -> str:
    return CANONICAL_TO_POST_TYPE.get(to_canonical(lead_type), "unknown")


def parse_wire_lead_types(lead_types: list[str] | None) -> list[str]:
    if not lead_types:
        return []
    out, seen = [], set()
    for raw in lead_types:
        c = to_canonical(raw)
        if c in REQUESTABLE_INTENTS and c not in seen:
            seen.add(c)
            out.append(c)
    return out


class IntentStrength(str, Enum):
    EXPLICIT = "explicit"
    ACTIVE_SEARCH = "active_search"
    RECOMMENDATION = "recommendation"
    PROBLEM_AWARENESS = "problem_awareness"
    RESEARCH = "research"
    NONE = "none"


INTENT_STRENGTH_ORDER = {
    IntentStrength.EXPLICIT.value: 6, IntentStrength.ACTIVE_SEARCH.value: 5,
    IntentStrength.RECOMMENDATION.value: 4, IntentStrength.PROBLEM_AWARENESS.value: 2,
    IntentStrength.RESEARCH.value: 1, IntentStrength.NONE.value: 0,
}


class LocationConfidence(str, Enum):
    STRUCTURED = "structured"
    TEXT = "text"
    COMPANY = "company"
    UNKNOWN = "unknown"


# ══════════════════════════════════════════════════════════════════════════
# LOCATION — normalization + hard gate (fail-closed for strict requests)
# ══════════════════════════════════════════════════════════════════════════
COUNTRY_ALIASES = {
    "us": "US", "usa": "US", "united states": "US", "united states of america": "US",
    "u.s": "US", "u.s.a": "US", "america": "US", "ca": "CA", "canada": "CA",
    "uk": "GB", "gb": "GB", "united kingdom": "GB", "britain": "GB", "england": "GB",
    "scotland": "GB", "wales": "GB", "ie": "IE", "ireland": "IE",
    "au": "AU", "australia": "AU", "nz": "NZ", "new zealand": "NZ",
    "de": "DE", "germany": "DE", "nl": "NL", "netherlands": "NL", "holland": "NL",
    "fr": "FR", "france": "FR", "be": "BE", "belgium": "BE", "ch": "CH", "switzerland": "CH",
    "swiss": "CH", "at": "AT", "austria": "AT", "se": "SE", "sweden": "SE", "no": "NO",
    "norway": "NO", "dk": "DK", "denmark": "DK", "fi": "FI", "finland": "FI", "es": "ES",
    "spain": "ES", "it": "IT", "italy": "IT", "pt": "PT", "portugal": "PT",
    "lu": "LU", "luxembourg": "LU", "is": "IS", "iceland": "IS",
    "ae": "AE", "uae": "AE", "united arab emirates": "AE", "dubai": "AE",
    "sa": "SA", "saudi arabia": "SA", "qa": "QA", "qatar": "QA", "kw": "KW", "kuwait": "KW",
    "sg": "SG", "singapore": "SG", "il": "IL", "israel": "IL",
    "in": "IN", "india": "IN", "pk": "PK", "pakistan": "PK", "bd": "BD", "bangladesh": "BD",
    "ph": "PH", "philippines": "PH", "ng": "NG", "nigeria": "NG", "vn": "VN", "vietnam": "VN",
    "id": "ID", "indonesia": "ID", "th": "TH", "thailand": "TH", "my": "MY", "malaysia": "MY",
    "ke": "KE", "kenya": "KE", "gh": "GH", "ghana": "GH", "za": "ZA", "south africa": "ZA",
    "eg": "EG", "egypt": "EG", "mx": "MX", "mexico": "MX", "br": "BR", "brazil": "BR",
    "lk": "LK", "sri lanka": "LK", "np": "NP", "nepal": "NP", "tr": "TR", "turkey": "TR",
    "jp": "JP", "japan": "JP", "kr": "KR", "south korea": "KR", "korea": "KR",
    "tw": "TW", "taiwan": "TW", "cn": "CN", "china": "CN", "ar": "AR", "argentina": "AR",
    "cl": "CL", "chile": "CL", "co": "CO", "colombia": "CO",
}

CITY_COUNTRY = {
    "new york": "US", "nyc": "US", "san francisco": "US", "los angeles": "US", "chicago": "US",
    "austin": "US", "miami": "US", "seattle": "US", "boston": "US", "denver": "US", "dallas": "US",
    "houston": "US", "phoenix": "US", "atlanta": "US", "toronto": "CA", "vancouver": "CA",
    "montreal": "CA", "london": "GB", "manchester": "GB", "birmingham": "GB", "leeds": "GB",
    "edinburgh": "GB", "glasgow": "GB", "dublin": "IE", "sydney": "AU", "melbourne": "AU",
    "brisbane": "AU", "perth": "AU", "auckland": "NZ", "berlin": "DE", "munich": "DE",
    "hamburg": "DE", "frankfurt": "DE", "amsterdam": "NL", "rotterdam": "NL", "the hague": "NL",
    "paris": "FR", "lyon": "FR", "brussels": "BE", "zurich": "CH", "geneva": "CH",
    "vienna": "AT", "stockholm": "SE", "oslo": "NO", "copenhagen": "DK", "helsinki": "FI",
    "madrid": "ES", "barcelona": "ES", "milan": "IT", "rome": "IT", "lisbon": "PT",
    "dubai": "AE", "abu dhabi": "AE", "riyadh": "SA", "doha": "QA", "kuwait city": "KW",
    "singapore": "SG", "tel aviv": "IL", "mumbai": "IN", "delhi": "IN", "new delhi": "IN",
    "bangalore": "IN", "bengaluru": "IN", "hyderabad": "IN", "pune": "IN", "chennai": "IN",
    "karachi": "PK", "lahore": "PK", "dhaka": "BD", "manila": "PH", "lagos": "NG",
    "nairobi": "KE", "cape town": "ZA", "johannesburg": "ZA", "cairo": "EG",
    "mexico city": "MX", "sao paulo": "BR",
}

REGION_COUNTRY_CODES = {
    "asia": {"IN", "PK", "BD", "PH", "VN", "ID", "TH", "MY", "SG", "JP", "KR", "TW", "CN"},
    "europe": {"GB", "DE", "FR", "NL", "BE", "CH", "AT", "SE", "NO", "DK", "FI", "ES", "IT", "PT", "IE", "LU"},
    "eu": {"DE", "FR", "NL", "BE", "AT", "SE", "NO", "DK", "FI", "ES", "IT", "PT", "IE", "LU"},
    "united states": {"US"}, "usa": {"US"}, "america": {"US"}, "us": {"US"}, "india": {"IN"},
    "africa": {"NG", "KE", "GH", "ZA", "EG"}, "australia": {"AU", "NZ"}, "canada": {"CA"},
    "south america": {"BR", "MX", "AR", "CL", "CO"}, "uk": {"GB"}, "united kingdom": {"GB"},
    "britain": {"GB"}, "uae": {"AE"}, "dubai": {"AE"}, "gulf": {"AE", "SA", "QA", "KW"},
    "germany": {"DE"}, "middle east": {"AE", "SA", "QA", "KW", "IL"},
}


def normalize_country(raw: str) -> str | None:
    if not raw:
        return None
    text = raw.strip().lower()
    if text in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[text]
    if text in REGION_COUNTRY_CODES:
        codes = REGION_COUNTRY_CODES[text]
        return codes.pop() if len(codes) == 1 else None
    stripped = re.sub(r"[^a-zA-Z\s]", "", text).strip()
    if stripped in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[stripped]
    if text in CITY_COUNTRY:
        return CITY_COUNTRY[text]
    for city, code in CITY_COUNTRY.items():
        if text.startswith(city) or city in text:
            return code
    return None


def parse_country_request(location: str) -> tuple[set[str], str]:
    if not location:
        return set(), ""
    parts = re.split(r"[,/;]| and ", location.strip())
    codes: set[str] = set()
    for part in parts:
        code = normalize_country(part)
        if code:
            codes.add(code)
    return codes, location.strip()


def extract_country_code(author: dict) -> str:
    location = author.get("location") or {}
    if isinstance(location, dict):
        cc = (location.get("countryCode") or "").strip().upper()
        if cc and len(cc) == 2:
            return cc
        country = location.get("country")
        if isinstance(country, dict):
            cc = (country.get("code") or country.get("countryCode") or "").strip().upper()
            if cc and len(cc) == 2:
                return cc
    return ""


def author_location_text(author: dict) -> str:
    location = author.get("location") or {}
    if isinstance(location, dict):
        linkedin_text = (location.get("linkedinText") or "").strip()
        parsed = location.get("parsed") or {}
        if linkedin_text:
            return linkedin_text
        if isinstance(parsed, dict) and parsed.get("text"):
            return str(parsed["text"])
    return (author.get("location") or "").strip() if isinstance(author.get("location"), str) else ""


def resolve_author_country(author: dict) -> tuple[str, str]:
    cc = extract_country_code(author)
    if cc:
        return cc, LocationConfidence.STRUCTURED.value
    text = author_location_text(author)
    if text:
        code = normalize_country(text)
        if code:
            return code, LocationConfidence.TEXT.value
    headline = author.get("info") or author.get("headline") or ""
    code = normalize_country(headline)
    if code:
        return code, LocationConfidence.TEXT.value
    return "", LocationConfidence.UNKNOWN.value


def text_matches_requested_country(text: str, requested: set[str]) -> bool:
    if not text:
        return False
    low = text.lower()
    for code in requested:
        for alias, mapped in COUNTRY_ALIASES.items():
            if mapped == code and alias in low:
                return True
        for city, mapped in CITY_COUNTRY.items():
            if mapped == code and city in low:
                return True
    return False


def country_pass(country_code: str, location_text_value: str, requested: set[str]) -> tuple[bool, str]:
    """Hard country gate. Strict -> unverifiable candidates are rejected."""
    if not requested:
        return True, LocationConfidence.UNKNOWN.value
    if country_code and country_code.upper() in {c.upper() for c in requested}:
        return True, LocationConfidence.STRUCTURED.value
    if location_text_value and text_matches_requested_country(location_text_value, requested):
        return True, LocationConfidence.TEXT.value
    return False, LocationConfidence.UNKNOWN.value


def job_country_pass(job_location: str, author_country_code: str, author_location_text: str, requested: set[str], job_remote: bool = False) -> tuple[bool, str]:
    """Hard country gate tailored to HIRING/job leads.

    The author's profile may be in the requested country while the actual JOB
    posting is elsewhere (e.g. a US recruiter posting a Pakistan-based role).
    When the posting explicitly names a location we must honor that.

      - REMOTE / anywhere / global jobs: location-agnostic -> PASS. A remote
        role can be performed from the requested country, so it is not a
        wrong-country violation.
      - If the job location names ONLY a non-requested country -> REJECT.
      - If the job location names a requested country/city -> PASS.
      - Otherwise fall back to the author's profile country.
    """
    if not requested:
        return True, LocationConfidence.UNKNOWN.value

    if job_remote:
        return True, LocationConfidence.TEXT.value

    jl = (job_location or "").strip().lower()
    if jl:
        # If it names a requested country/city -> pass.
        if text_matches_requested_country(jl, requested):
            return True, LocationConfidence.TEXT.value
        # If the job location explicitly names a country that is NOT requested
        # -> reject (e.g. a US recruiter posting a "Pakistan preferred" role).
        for name, code in COUNTRY_ALIASES.items():
            if code not in requested and name in jl:
                return False, LocationConfidence.TEXT.value
        # Job location present but doesn't resolve to a known country; fall
        # through to the author's profile country below.
    if author_country_code and author_country_code.upper() in {c.upper() for c in requested}:
        return True, LocationConfidence.STRUCTURED.value
    if author_location_text and text_matches_requested_country(author_location_text, requested):
        return True, LocationConfidence.TEXT.value
    return False, LocationConfidence.UNKNOWN.value


# ══════════════════════════════════════════════════════════════════════════
# INTENT-SPECIFIC QUERY GENERATION (diversified, no cross-intent mixing)
# ══════════════════════════════════════════════════════════════════════════
SERVICE_SYNONYMS = {
    "design": ["graphic designer", "brand designer", "visual designer", "marketing designer"],
    "graphic": ["graphic designer", "graphic design", "brand designer", "visual designer"],
    "web": ["web developer", "website developer", "web designer", "frontend"],
    "website": ["web developer", "website developer", "web designer", "frontend"],
    "shopify": ["shopify developer", "shopify expert", "ecommerce developer"],
    "react": ["react developer", "frontend developer", "react js"],
    "seo": ["seo expert", "seo specialist", "search engine optimization"],
    "video": ["video editor", "post production", "motion designer"],
    "edit": ["video editor", "editor", "post production"],
    "ui": ["ui ux designer", "ui ux", "product designer", "ux designer"],
    "ux": ["ui ux designer", "ui ux", "product designer", "ux designer"],
    "mobile": ["mobile app developer", "app developer", "react native", "flutter"],
    "wordpress": ["wordpress developer", "wordpress"],
    "brand": ["brand designer", "branding", "brand identity"],
    "social": ["social media manager", "social media", "smm"],
    "market": ["marketing", "digital marketing", "growth", "performance marketing"],
    "copy": ["copywriter", "copywriting", "content writer"],
    "account": ["accountant", "accounting", "bookkeeper"],
    "legal": ["lawyer", "attorney", "legal advisor"],
}

FREELANCER_TEMPLATES = [
    "looking for freelance {base}", "need a freelance {base}", "seeking freelance {base}",
    "looking for someone to handle {base}", "need someone for {base}", "hiring freelance {base}",
    "looking for independent {base}", "need a contractor for {base}",
    "anyone know a good freelance {base}", "looking to hire a freelance {base} for a project",
]
HIRING_TEMPLATES = [
    "hiring {base}", "we're hiring {base}", "looking for {base}", "seeking {base} professional",
    "need a {base} for our team", "hiring a {base} to join", "looking for someone experienced in {base}",
    "join our team as {base}", "open position {base}", "recruiting {base}",
]
AGENCY_TEMPLATES = [
    "looking for {base} agency", "need {base} agency", "seeking {base} agency", "looking for agency for {base}",
    "need an agency for {base}", "recommend {base} agency", "searching for {base} agency",
    "hiring an agency for {base}", "need help from an agency with {base}", "anyone recommend a {base} agency",
    "looking for an agency to handle {base}",
]
INTENT_TEMPLATES = {"freelancer_needed": FREELANCER_TEMPLATES, "hiring": HIRING_TEMPLATES, "agency_wanted": AGENCY_TEMPLATES}
BUY_WORDS = ["looking for", "need", "seeking", "searching for", "want", "hiring", "require"]


def _norm(q: str) -> str:
    return re.sub(r"[\s]+", " ", (q or "").strip().lower())


def service_root(service: str) -> str:
    s = _norm(service)
    return s or "service"


def _synonyms(service: str) -> list[str]:
    low = _norm(service)
    variants, seen = [], set()
    for key, words in SERVICE_SYNONYMS.items():
        if key in low:
            variants.extend(words)
    root = service_root(service)
    variants.append(root)
    if "develop" in low:
        variants.append(low.replace("development", "developer"))
    if "design" in low and "designer" not in low:
        variants.append(low.replace("design", "designer"))
    out = []
    for v in variants:
        v = _norm(v)
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out[:6]


_COUNTRY_NAME_FOR_CODE = {"US": "USA", "GB": "UK", "CA": "Canada", "IN": "India", "DE": "Germany",
                          "AU": "Australia", "FR": "France", "AE": "UAE", "SG": "Singapore",
                          "NZ": "New Zealand", "IE": "Ireland", "NL": "Netherlands", "ES": "Spain"}


def _add_country_bias(queries: list[str], country_codes: set[str]) -> list[str]:
    """Soft discovery bias toward the requested country. NEVER a substitute for
    the final deterministic country gate."""
    if not country_codes:
        return queries
    name = _COUNTRY_NAME_FOR_CODE.get(next(iter(country_codes)).upper(), "")
    if not name:
        return queries
    out = []
    for q in queries:
        out.append(q)
        out.append(f"{q} {name}")
    return out


def generate_queries(lead_type: str, service: str, country_codes: set[str], iteration: int, max_queries: int = 12) -> list[str]:
    base = service_root(service)
    templates = INTENT_TEMPLATES.get(lead_type, FREELANCER_TEMPLATES)
    roles = _synonyms(service) or [base]
    slot = iteration % len(templates)
    queries, seen = [], set()

    def _add(q: str) -> None:
        key = _norm(q)
        if key and key not in seen:
            seen.add(key)
            queries.append(q)

    for role in roles:
        _add(templates[slot].replace("{base}", role))
    for offset in range(1, 4):
        idx = (slot + offset) % len(templates)
        _add(templates[idx].replace("{base}", roles[0]))
    buy_word = BUY_WORDS[iteration % len(BUY_WORDS)]
    if lead_type == "agency_wanted":
        _add(f"{buy_word} agency for {base}")
        _add(f"{buy_word} an agency for {base}")
    elif lead_type == "hiring":
        _add(f"{buy_word} {base} for our company")
        _add(f"{buy_word} {base} role")
    else:
        _add(f"{buy_word} a freelance {base}")
        _add(f"{buy_word} freelance {base}")

    queries = _add_country_bias(queries, country_codes)
    out, seen2 = [], set()
    for q in queries:
        key = _norm(q)
        if key and key not in seen2:
            seen2.add(key)
            out.append(q)
    return out[:max_queries]


# ══════════════════════════════════════════════════════════════════════════
# DETERMINISTIC PRE-FILTERS (high-confidence garbage only)
# ══════════════════════════════════════════════════════════════════════════
SELLER_PATTERNS = [
    r"\bwe offer\b", r"\bwe provide\b", r"\bwe specialize in\b", r"\bwe are a (leading |top )?(agency|studio|firm)\b",
    r"\bour services include\b", r"\bmy services include\b", r"\bI offer\b", r"\bI provide\b",
    r"\bcontact us for\b", r"\bDM us for\b", r"\bDM me for\b",
    r"\bbook a call\b", r"\bavailable for (projects|hire|work|clients)\b", r"\bopen to (new )?projects\b",
    r"\bopen to remote work\b", r"\blocking for clients\b", r"\btaking (new )?clients\b",
    r"\bmy portfolio\b", r"\bI am (a|an) (freelance|independent) .{0,60} looking for (clients|work)\b",
    r"\bam looking for clients\b", r"\bwe help businesses\b", r"\bget in touch\b",
    # White-label / partner / OEM sales framing (no literal "we offer"):
    r"\bwhite[- ]?label\b", r"\bwhite[- ]?label[a-z ]*partner\b",
    r"\b(we|our|i)\b[\w\s,.'-]{0,20}\bpartner[s]? for (agencies|businesses|devs|developers|designers|marketers)\b",
    r"\b(help|helps|helping) (you|your|agencies|businesses|companies|clients|them)\b[\w\s,.'-]{0,12}\b(deliver|build|create|scale|win|grow|launch|ship|save)\b",
    r"\bwe (can |will |)>?build (it|this|that|apps|websites|products|software) for you\b",
    r"\b(our|the) (team|agency|studio|firm) (can |will |)>?[a-z]{2,20} for you\b",
    r"\bwe[pt] (be|act|serve|work) as (your|a|an) (white-?label|outsourced|dedicated|virtual) (team|agency|partner|extension)\b",
    r"\boutsource[d]? (your|to us|custom )?\b", r"\bdedicated (team|developer|designer)s?\b for you\b",
    r"\blet['’]s (work together|partner|team up|collaborate)\b",
    r"\b(book|schedule|grab|get) a (free )?(consultation|call|demo|audit|discovery)\b",
    r"\b(we|our agency|our studio) deliver\b", r"\bwe take care of\b",
    r"\bsend (us|me) a (message|dm|note|brief)\b", r"\breach out (to us|today|now)\b",
    r"\bshow (you|them) how we\b", r"\b(results|outcomes) (for|guaranteed)\b",
]
JOB_SEEKER_PATTERNS = [
    r"\blooking for a job\b", r"\blooking for (a )?role\b", r"\blooking for employment\b",
    r"\bopen to work\b", r"#opentowork", r"\bavailable for hire\b", r"\bseeking opportunities\b",
    r"\bactively seeking employment\b", r"\bfeel free to reach out if you are hiring\b",
    r"\bi am looking for (a )?role\b",
]
CONTENT_PATTERNS = [
    r"\b\d+ (tips|ways|mistakes)\b", r"\bwhy you need\b", r"\bhere's how to\b",
    r"\bhow to (improve|grow|boost)\b", r"^(5|7|10) reasons\b", r"\btrends (for|in|to)\b", r"\bcase study\b",
]
RECRUITER_SELLER_PATTERNS = [
    r"\b(we|i) (are|am) (a|an) (talent|staffing|recruiting)( staffing| talent| hiring)? (agency|firm)\b", r"\bwe place (candidates|talents)\b",
    # Staffing/recruitment-firm framing that sells placements rather than hiring
    # for the poster's own company:
    r"\bwe (are )?(currently )?(accepting|taking) applications for\b",
    r"\b(accepting|taking) (applications|resumes) (for|from) (a|the) (wide variety|range)\b",
    r"\bconnect (you|with|we) (with )?talented professionals\b",
    r"\bwe (match|place|arrange|facilitate) (candidates|talent|professionals)\b",
    r"\b(retained|contingency) (recruiting|search|recruitment)\b",
    r"\bwe (recruit|source|vet) (for our )?clients\b",
    r"\b(open )?roles for (our )?clients\b", r"\b(our|the) (clients|client companies) (are|is) hiring\b",
    r"\bwe have (open|vacant) (roles|positions) with (clients|companies|organizations)\b",
    r"\binterested candidates can apply (via|through|with) us\b",
    r"\b(we|our firm) (specialize|specialises) in (executive|talent) (search|recruitment)\b",
    r"\bheadhunt(ers?|ing)?\b",
]

_SELLER_RE = [re.compile(p, re.I) for p in SELLER_PATTERNS]
_JOB_RE = [re.compile(p, re.I) for p in JOB_SEEKER_PATTERNS]
_CONTENT_RE = [re.compile(p, re.I) for p in CONTENT_PATTERNS]
_RECRUITER_RE = [re.compile(p, re.I) for p in RECRUITER_SELLER_PATTERNS]


def _any_match(text: str, patterns: list) -> bool:
    return any(p.search(text) for p in patterns) if text else False


def prefilter_reject(candidate: dict, *, allow_content: bool = False) -> tuple[bool, str]:
    post = candidate.get("post_text") or ""
    headline = candidate.get("headline") or ""
    text = f"{post}\n{headline}"
    if _any_match(text, _SELLER_RE):
        return True, "seller"
    if _any_match(text, _JOB_RE):
        return True, "job_seeker"
    if _any_match(text, _RECRUITER_RE):
        return True, "recruiter_seller"
    if not allow_content and _any_match(text, _CONTENT_RE):
        return True, "content"
    return False, ""


# ══════════════════════════════════════════════════════════════════════════
# CANONICAL ACCEPTANCE + QUALITY SCORE (one authoritative policy)
# ══════════════════════════════════════════════════════════════════════════
def compute_quality_score(classification: dict) -> float:
    intent = classification.get("intent_strength") or IntentStrength.NONE.value
    intent_val = INTENT_STRENGTH_ORDER.get(intent, 0)
    intent_score = intent_val / 6.0 * 100
    service_match = float(classification.get("service_match_score") or 0)
    commercial = float(classification.get("commercial_intent_score") or 0)
    decision_maker = 100.0 if classification.get("decision_maker_signal") else 20.0
    location_conf = float(classification.get("location_confidence") or 0)
    evidence = min(100.0, 40.0 + len(classification.get("reason") or "") * 2.0)
    return round(max(0.0, min(100.0,
        intent_score * QUALITY_WEIGHTS["intent_strength"]
        + service_match * QUALITY_WEIGHTS["service_match"]
        + commercial * QUALITY_WEIGHTS["commercial_intent"]
        + decision_maker * QUALITY_WEIGHTS["decision_maker"]
        + location_conf * QUALITY_WEIGHTS["location_confidence"]
        + evidence * QUALITY_WEIGHTS["evidence"])), 2)


class AcceptanceDecision:
    def __init__(self, accepted: bool, reasons: list[str] = None, rejections: list[str] = None, quality_score: float = 0.0):
        self.accepted = accepted
        self.reasons = reasons or []
        self.rejections = rejections or []
        self.quality_score = quality_score

    def as_dict(self) -> dict:
        return {"accepted": self.accepted, "reasons": self.reasons, "rejections": self.rejections, "quality_score": self.quality_score}


def canonical_accept(candidate: dict, *, request_lead_types: list[str], requested_countries: set[str], service: str) -> AcceptanceDecision:
    classification = candidate.get("classification") or {}
    canonical = to_canonical(candidate.get("lead_type") or classification.get("lead_type"))
    rejections: list[str] = []

    # GATE 1 exact lead type
    if canonical not in request_lead_types:
        rejections.append(f"wrong_intent:{canonical}")
    # GATE 2 country (fail-closed for strict requests)
    country_code = candidate.get("country_code") or candidate.get("location_code") or ""
    passes_country, _ = country_pass(country_code, candidate.get("location") or "", requested_countries)
    if not passes_country:
        rejections.append("wrong_country")
    # GATE 3 seller / job-seeker backstop
    if classification.get("seller_signal") or candidate.get("seller_signal"):
        rejections.append("seller")
    if classification.get("job_seeker_signal") or candidate.get("job_seeker_signal"):
        rejections.append("job_seeker")
    # GATE 4 service match
    cm = float(classification.get("service_match_score") or 0)
    if cm < MIN_SERVICE_MATCH:
        rejections.append(f"weak_service_match:{int(cm)}")
    # GATE 5 intent strength
    intent = classification.get("intent_strength") or IntentStrength.NONE.value
    if INTENT_STRENGTH_ORDER.get(intent, 0) < INTENT_STRENGTH_ORDER[MIN_INTENT_STRENGTH]:
        rejections.append(f"weak_intent:{intent}")
    # GATE 6 quality
    quality = compute_quality_score(classification)
    if quality < MIN_QUALITY_SCORE:
        rejections.append(f"low_quality:{int(quality)}")
    # GATE 7 explicit is_qualified flag from AI (fail-closed)
    if not classification.get("is_qualified"):
        rejections.append("ai_unqualified")

    reasons = ["exact_intent", "country_ok"] if not rejections else []
    if not rejections and classification.get("decision_maker_signal"):
        reasons.append("decision_maker")
    return AcceptanceDecision(accepted=not rejections, reasons=reasons, rejections=rejections, quality_score=quality)


def rank_leads(candidates: list[dict]) -> list[dict]:
    def key_fn(c):
        cls = c.get("classification") or {}
        intent_rank = INTENT_STRENGTH_ORDER.get(cls.get("intent_strength") or IntentStrength.NONE.value, 0)
        return (intent_rank, float(cls.get("service_match_score") or 0), float(cls.get("commercial_intent_score") or 0),
                float(cls.get("overall_quality_score") or 0), len(c.get("post_text") or ""))
    return sorted(candidates, key=key_fn, reverse=True)


# ══════════════════════════════════════════════════════════════════════════
# TELEMETRY
# ══════════════════════════════════════════════════════════════════════════
class IterationTelemetry:
    def __init__(self, iteration: int, remaining_target: int):
        self.iteration = iteration
        self.remaining_target = remaining_target
        self.queries: list[str] = []
        self.provider_raw_count = 0
        self.provider_ok_lanes = 0
        self.provider_total_lanes = 0
        self.provider_errors: list[str] = []
        self.after_country_filter = 0
        self.after_dedupe = 0
        self.after_deterministic = 0
        self.non_qualified_ai = 0
        self.after_ai_qualification = 0
        self.accepted_this_iteration = 0
        self.cumulative_valid = 0
        self.last_scored_types: dict = {}

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


# ══════════════════════════════════════════════════════════════════════════
# ENGINE — iterative exact-count discovery orchestrator
# ══════════════════════════════════════════════════════════════════════════
class LeadRequest:
    def __init__(self, search_id, user_id, service, request_count, lead_types, country_codes, country_text, enrich_emails):
        self.search_id = search_id
        self.user_id = user_id
        self.service = service
        self.request_count = request_count
        self.lead_types = lead_types
        self.country_codes = country_codes
        self.country_text = country_text
        self.enrich_emails = enrich_emails
        self.iteration = 0

    def primary_lead_type(self) -> str:
        return self.lead_types[0] if self.lead_types else LeadType.UNKNOWN.value


def _identity_url(candidate: dict) -> str:
    return (candidate.get("linkedin_url") or candidate.get("post_url") or "").split("?")[0].rstrip("/").lower()


def _parse_candidate(item: dict) -> Optional[dict]:
    author = item.get("author") or {}
    author_url = ((author.get("url") or author.get("linkedinUrl") or "")).strip()
    content = (item.get("content") or "").strip()
    if not author_url or len(content) < 20:
        return None

    post_url = ""
    for key in ("linkedinUrl", "postUrl", "post_url", "url"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            low = val.lower()
            if "/posts/" in low or "/feed/" in low or "/activity-" in low:
                post_url = val.strip()
                break
    if not post_url:
        post_url = item.get("url") or ""

    cc, loc = resolve_author_country(author)
    eng = item.get("engagement") or {}

    def _int(v) -> int:
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0

    def _author_company(a) -> str:
        positions = a.get("currentPosition") or []
        if isinstance(positions, list):
            for pos in positions:
                if isinstance(pos, dict):
                    name = pos.get("companyName") or pos.get("name") or (pos.get("company") or {}).get("name")
                    if name:
                        return str(name)[:100]
        return ""

    def _avatar(a) -> str:
        av = a.get("avatar")
        if isinstance(av, str):
            return av
        if isinstance(av, dict):
            return av.get("url") or ""
        pic = a.get("profilePicture") or {}
        if isinstance(pic, dict):
            return pic.get("url") or ""
        return ""

    def _posted(value):
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
            return _posted(value.get("timestamp") or value.get("date"))
        return None

    return {
        "full_name": author.get("name") or "",
        "headline": (author.get("info") or author.get("headline") or "")[:500],
        "company": _author_company(author),
        "location": loc,
        "country_code": cc,
        "location_code": cc,
        "linkedin_url": author_url,
        "post_url": post_url,
        "post_text": content[:3000],
        "job_location": _job_location_from_text(content[:3000]),
        "job_remote": _job_remote_signal(content[:3000]),
        "posted_at": _posted(item.get("postedAt") or item.get("postedTimestamp")),
        "engagement_likes": _int(eng.get("likes") if eng.get("likes") is not None else eng.get("reactions")),
        "engagement_comments": _int(eng.get("comments")),
        "profile_picture_url": _avatar(author),
        "connections_count": author.get("connectionsCount") or 0,
    }


_REMOTE_SIGNALS = ("remote", "work from home", "wfh", "anywhere", "worldwide", "global", "hybrid")


def _job_remote_signal(text: str) -> bool:
    """True when a job posting is explicitly remote/anywhere/location-agnostic."""
    if not text:
        return False
    low = text.lower()
    return any(sig in low for sig in _REMOTE_SIGNALS)


_JOB_LOC_RE = re.compile(
    r"(?:location|based in|position (?:is )?(?:based )?in|on[- ]site|onsite|hybrid(?: role)?(?: in|,|:)?|site:)"
    r"[\s:,-]*([A-Z][A-Za-z.\- ]{2,40}(?:[,/]\s*[A-Za-z.\- ]{2,20})?)\b",
    re.IGNORECASE,
)


def _job_location_from_text(text: str) -> str:
    """Best-effort extraction of an explicit job location from a posting.

    Returns '' when no confident location phrase is found. Used by the country
    gate to enforce the JOB's location (not only the author's profile country),
    so a US recruiter posting a 'Pakistan preferred' role is caught.
    """
    if not text:
        return ""
    m = _JOB_LOC_RE.search(text)
    if m:
        candidate_loc = m.group(1)
        # Never treat the extraction as a country if a "remote" signal dominates
        # and no strong country/city name follows.
        low = (candidate_loc or "").lower()
        if low not in ("remote", "anywhere", "remote anywhere", "worldwide", "global"):
            return candidate_loc[:60]
    return ""


def _discover(queries: list[str], max_posts_per_lane: int = MAX_POSTS_PER_LANE) -> tuple[int, int, list[dict], list[str]]:
    n_lanes = min(3, max(1, (len(queries) + 3) // 4))
    lanes = [[] for _ in range(n_lanes)]
    for i, q in enumerate(queries):
        lanes[i % n_lanes].append(q)
    ok, errors, items = 0, [], []
    for lane in lanes:
        try:
            result = run_lane_search(lane, max_posts_per_lane, "month", True)
            if result:
                ok += 1
                items.extend(result)
        except Exception as e:
            errors.append(str(e)[:160])
    return ok, n_lanes, items, errors


def _get_openai_client():
    from app.services.ai_service import _get_async_openai_client
    return _get_async_openai_client()


async def _update_search(supabase, search_id: str, data: dict) -> None:
    try:
        await asyncio.to_thread(lambda: supabase.table("searches").update(data).eq("id", search_id).execute())
    except Exception as e:
        logger.error(f"[LinkedIn:{search_id}] update failed: {e}")


async def _prefetch_known_urls(supabase, user_id: str) -> set[str]:
    try:
        resp = await asyncio.to_thread(lambda: supabase.table("leads").select("linkedin_url")
                                       .eq("user_id", user_id).neq("linkedin_url", "").execute())
        return {(r.get("linkedin_url") or "").split("?")[0].rstrip("/").lower() for r in (resp.data or []) if r.get("linkedin_url")}
    except Exception as e:
        logger.warning(f"[LinkedIn] known-url prefetch failed: {e}")
        return set()


async def _save_leads(supabase, search_id: str, user_id: str, leads: list[dict], request: LeadRequest) -> list[str]:
    rows = []
    for lead in leads:
        ai_score = lead.get("ai_score") or lead.get("quality_score") or 0
        lead_category = "hot" if ai_score >= 85 else "warm"
        post_type = canonical_to_post_type(lead.get("lead_type") or "")
        linkedin_url = (lead.get("linkedin_url") or "").strip()
        if not linkedin_url:
            continue
        cls = lead.get("classification") or {}
        rows.append({
            "search_id": search_id, "user_id": user_id, "source": "linkedin",
            "business_name": lead.get("full_name") or "Unknown", "category": lead.get("company") or "LinkedIn",
            "full_address": lead.get("location") or "", "phone": "", "email_found": "", "website_url": "",
            "rating": None, "total_reviews": 0, "google_maps_link": "", "description": lead.get("post_text") or "",
            "lead_category": lead_category, "post_type": post_type, "linkedin_url": linkedin_url,
            "post_url": lead.get("post_url") or "", "post_text": lead.get("post_text") or "",
            "headline": lead.get("headline") or "", "profile_picture_url": lead.get("profile_picture_url") or "",
            "connections_count": lead.get("connections_count") or 0, "posted_at": lead.get("posted_at"),
            "ai_qualified": True, "ai_confidence_score": min(100.0, float(ai_score)) / 100.0,
            "ai_reason": lead.get("ai_reason"), "ai_pitch": lead.get("outreach_angle"),
        })
    if not rows:
        return []
    try:
        existing = await asyncio.to_thread(lambda: supabase.table("leads").select("linkedin_url")
                                           .eq("user_id", user_id).neq("linkedin_url", "").execute())
        existing_urls = {(r.get("linkedin_url") or "").split("?")[0].rstrip("/").lower() for r in (existing.data or [])}
        rows = [r for r in rows if (r.get("linkedin_url") or "").split("?")[0].rstrip("/").lower() not in existing_urls]
    except Exception as e:
        logger.warning(f"[LinkedIn] dedup check failed: {e}")
    if not rows:
        return []
    try:
        response = await asyncio.to_thread(lambda: supabase.table("leads").insert(rows).execute())
        if response.data:
            return [r["id"] for r in response.data]
    except Exception as e:
        logger.warning(f"[LinkedIn] bulk insert failed ({e}); per-row fallback")
        ids = []
        for row in rows:
            try:
                r = await asyncio.to_thread(lambda r=row: supabase.table("leads").insert(r).execute())
                if r.data:
                    ids.append(r.data[0]["id"])
            except Exception as row_err:
                logger.error(f"[LinkedIn] row insert failed ({row.get('business_name')}): {row_err}")
        return ids
    return []


async def _enrich_profiles_for(promising: list[dict]) -> None:
    missing = [c for c in promising if not (c.get("headline") or "").strip()]
    if not missing:
        return
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
        logger.warning(f"[LinkedIn] profile enrichment skipped: {e}")


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


async def run_linkedin_engine(
    search_id: str, user_id: str, query: str, enrich_emails: bool, max_results: int,
    lead_types: list[str] = None, location: str = "",
) -> dict:
    """Strict exact-count iterative engine. Returns a telemetry dict."""
    from app.services.ai_service import (
        attach_classification,
        candidate_key,
        classify_linkedin_candidates,
    )

    supabase = get_supabase_admin()
    country_codes, country_text = parse_country_request(location or "")
    canonical_types = parse_wire_lead_types(lead_types)
    if not canonical_types:
        canonical_types = [LeadType.FREELANCER_NEEDED.value]
    request = LeadRequest(search_id, user_id, query.strip(), max(1, min(int(max_results), MAX_RESULTS_CAP)),
                          canonical_types, country_codes, country_text, enrich_emails)

    await _update_search(supabase, search_id, {
        "status": "scraping", "progress_percent": 3,
        "message": f"Searching LinkedIn for {', '.join(t.replace('_', ' ') for t in request.lead_types)} · {request.service} · {request.country_text or 'Any'}...",
    })

    client = _get_openai_client()
    known_urls = await _prefetch_known_urls(supabase, user_id)

    return await _run_engine_with_externals(
        supabase=supabase,
        request=request,
        client=client,
        known_urls=known_urls,
        discover=_discover,
        classify=classify_linkedin_candidates,
        attach_classification=attach_classification,
        candidate_key=candidate_key,
    )


async def _run_engine_with_externals(
    *,
    supabase: Any,
    request: LeadRequest,
    client: Any,
    known_urls: set[str],
    discover: Any,
    classify: Any,
    attach_classification: Any,
    candidate_key: Any,
) -> dict:
    """Pure exact-count iterative loop. Externals injected for testability.

    verify_known: dedupe against saved leads. The loop calls `discover(queries)`
    -> (ok_lanes, total_lanes, raw_items, errors) and `classify(client, service,
    country, candidates)` -> {candidate_key: LeadClassification}.
    """
    search_id = request.search_id
    user_id = request.user_id
    valid_leads: list[dict] = []
    chosen_urls: set[str] = set()
    seen_post_ids: set[str] = set()
    used_queries: set[str] = set()
    iteration = 0
    no_progress = 0
    provider_fail_rounds = 0
    deadline = time.monotonic() + WAVE_DEADLINE_SECONDS
    iterations: list[IterationTelemetry] = []
    reason = None

    while len(valid_leads) < request.request_count and iteration < MAX_ITERATIONS:
        if time.monotonic() > deadline:
            reason = "deadline"
            break
        iteration += 1
        request.iteration = iteration
        remaining = request.request_count - len(valid_leads)
        it = IterationTelemetry(iteration, remaining)
        it.last_scored_types = {}

        queries = generate_queries(request.primary_lead_type(), request.service, request.country_codes, iteration, 12)
        fresh_q = [q for q in queries if q not in used_queries]
        if not fresh_q:
            used_queries.clear()
            fresh_q = queries
        it.queries = fresh_q
        used_queries.update(fresh_q)

        await _update_search(supabase, search_id, {
            "progress_percent": min(10 + iteration * 12, 82),
            "message": f"Iteration {iteration}: {len(valid_leads)}/{request.request_count} leads...",
        })

        provider_ok, provider_total, raw_items, provider_errors = discover(fresh_q)
        it.provider_ok_lanes = provider_ok
        it.provider_total_lanes = provider_total
        it.provider_errors = provider_errors
        it.provider_raw_count = len(raw_items)
        logger.info(f"[LinkedIn:{search_id}] iter {iteration}: raw={len(raw_items)} ok_lanes={provider_ok}/{provider_total} queries={len(fresh_q)}")

        if not raw_items:
            # A provider total-failure (no lane returned data) is NOT proof the
            # market is empty — it is typically transient (rate-limit/timeout).
            # Retry across up to MAX_PROVIDER_FAIL_ROUNDS before giving up.
            if provider_ok == 0 and provider_total > 0:
                provider_fail_rounds += 1
                logger.warning(
                    f"[LinkedIn:{search_id}] iter {iteration}: provider returned no data "
                    f"({provider_fail_rounds}/{MAX_PROVIDER_FAIL_ROUNDS}) — retrying with diversified queries"
                )
                if provider_fail_rounds >= MAX_PROVIDER_FAIL_ROUNDS:
                    reason = "provider_failure"
                    iterations.append(it)
                    break
                iterations.append(it)
                continue
            # No new content but provider responded (e.g. all seen/deduped).
            no_progress += 1
            iterations.append(it)
            if no_progress >= MAX_NO_PROGRESS_ITERATIONS:
                reason = "no_progress"
                break
            continue

        # A successful discovery round resets the provider-failure counter.
        provider_fail_rounds = 0

        # country hard gate
        candidates = []
        for raw in raw_items:
            pid = raw.get("postId") or raw.get("id") or raw.get("url") or raw.get("linkedinUrl")
            if pid and pid in seen_post_ids:
                continue
            if pid:
                seen_post_ids.add(pid)
            cand = _parse_candidate(raw)
            if not cand:
                continue
            # Country hard gate. For hiring requests, also enforce the JOB's own
            # location (a US recruiter posting a "Pakistan preferred" role must be
            # rejected), while still allowing remote/anywhere jobs.
            if "hiring" in request.lead_types:
                ok_country, _ = job_country_pass(
                    cand.get("job_location") or "",
                    cand.get("country_code") or cand.get("location_code") or "",
                    cand.get("location") or "",
                    request.country_codes,
                    cand.get("job_remote") or False,
                )
                if not ok_country:
                    continue
            else:
                if not country_pass(cand.get("country_code") or cand.get("location_code") or "", cand.get("location") or "", request.country_codes)[0]:
                    continue
            candidates.append(cand)
        it.after_country_filter = len(candidates)
        logger.info(f"[LinkedIn:{search_id}] iter {iteration}: after_country={len(candidates)} (requested={request.country_codes or 'any'})")

        # dedupe by identity
        uniq, seen_ids = [], set()
        for cand in candidates:
            key = _identity_url(cand)
            if key and key in seen_ids:
                continue
            if key:
                seen_ids.add(key)
            uniq.append(cand)
        it.after_dedupe = len(uniq)
        uniq = [c for c in uniq if _identity_url(c) not in known_urls and _identity_url(c) not in chosen_urls]
        logger.info(f"[LinkedIn:{search_id}] iter {iteration}: after_dedupe={len(uniq)} (dropped_known + not-chosen x{len(seen_ids)-len(uniq)})")

        # deterministic pre-filter
        filtered = []
        for cand in uniq:
            reject, _ = prefilter_reject(cand)
            if not reject:
                filtered.append(cand)
        it.after_deterministic = len(filtered)
        logger.info(f"[LinkedIn:{search_id}] iter {iteration}: after_deterministic_prefilter={len(filtered)}")

        if not filtered and not candidates:
            no_progress += 1
            iterations.append(it)
            if no_progress >= MAX_NO_PROGRESS_ITERATIONS:
                reason = "no_progress"
                break
            continue

        # profile enrichment ONLY for candidates missing a headline (cost control).
        await _enrich_profiles_for(filtered)
        await _update_search(supabase, search_id, {
            "progress_percent": min(30 + iteration * 10, 84),
            "message": f"Iteration {iteration}: qualifying {len(filtered)} candidates...",
        })

        # AI classification — fail-closed, structured.
        classifications = await classify(client, request.service, request.country_text, filtered)
        scored = []
        for cand in filtered:
            cls = classifications.get(candidate_key(cand))
            if cls is None:
                continue  # unverified -> rejected (fail-closed)
            scored.append(attach_classification(cand, cls))
        it.after_ai_qualification = len(scored)
        it.non_qualified_ai = len(filtered) - len(scored)
        it.last_scored_types = _type_counts(scored)
        logger.info(f"[LinkedIn:{search_id}] iter {iteration}: ai_classified={len(scored)}/{len(filtered)} types={it.last_scored_types}")

        accepted = []
        for cand in scored:
            decision = canonical_accept(cand, request_lead_types=request.lead_types,
                                        requested_countries=request.country_codes, service=request.service)
            if decision.accepted:
                cand["quality_score"] = decision.quality_score
                key = _identity_url(cand)
                if key and key not in chosen_urls:
                    chosen_urls.add(key)
                    accepted.append(cand)
        it.accepted_this_iteration = len(accepted)
        logger.info(f"[LinkedIn:{search_id}] iter {iteration}: accepted={len(accepted)} total_valid_so_far={len(valid_leads)} target={request.request_count}")

        accepted = rank_leads(accepted)
        new = 0
        for cand in accepted:
            if len(valid_leads) >= request.request_count:
                break
            key = _identity_url(cand)
            if key in known_urls:
                continue
            valid_leads.append(cand)
            new += 1
        it.cumulative_valid = len(valid_leads)
        if new > 0:
            no_progress = 0
            provider_fail_rounds = 0
        else:
            no_progress += 1
        iterations.append(it)
        if no_progress >= MAX_NO_PROGRESS_ITERATIONS:
            reason = "no_progress"
            break

    # EXACT-COUNT SLICE — never overdeliver.
    if len(valid_leads) > request.request_count:
        valid_leads = rank_leads(valid_leads)[: request.request_count]
    status = "complete" if len(valid_leads) >= request.request_count else "exhausted"
    reason = reason or status

    if valid_leads:
        await _save_leads(supabase, search_id, user_id, valid_leads, request)

    await _finalize_search(supabase, search_id, user_id, valid_leads, request.request_count,
                           [i.as_dict() for i in iterations], status, reason)
    return {"status": status, "reason": reason, "final_valid_count": len(valid_leads),
            "request_count": request.request_count, "iterations": [i.as_dict() for i in iterations]}


def _type_counts(candidates: list[dict]) -> dict:
    counts: dict = {}
    for c in candidates:
        t = c.get("lead_type") or "unknown"
        counts[t] = counts.get(t, 0) + 1
    return counts


async def _finalize_search(supabase, search_id: str, user_id: str, valid_leads: list[dict], request_count: int,
                           iterations: list[dict], status: str, reason: str) -> None:
    saved = len(valid_leads)
    hot = sum(1 for l in valid_leads if (l.get("ai_score") or l.get("quality_score") or 0) >= 85)
    warm = len(valid_leads) - hot
    await settle_search_quota(supabase, search_id, user_id, saved)
    msg = f"Found {saved} leads" if saved >= request_count else f"Found {saved} qualifying leads (requested {request_count})"
    await _update_search(supabase, search_id, {
        "status": "completed", "progress_percent": 100, "message": msg,
        "total_results": saved, "hot_leads": hot, "warm_leads": warm, "skipped": 0,
        "emails_found": 0, "completed_at": datetime.now(timezone.utc).isoformat(),
    })
    logger.info(f"[LinkedIn:{search_id}] {status} ({reason}) — saved {saved}/{request_count} leads ({hot} hot), iterations={len(iterations)}")


# ══════════════════════════════════════════════════════════════════════════
# BACKWARD-COMPAT ENTRY POINT — called by the search router. Runs the engine.
# ══════════════════════════════════════════════════════════════════════════
async def run_linkedin_pipeline_fast(
    search_id: str, user_id: str, query: str, enrich_emails: bool, max_results: int,
    lead_types: list[str] = None, location: str = "",
) -> None:
    """Background-task entry point. Runs the strict engine in the foreground of
    this coroutine (search router already runs this as a background task)."""
    try:
        await run_linkedin_engine(search_id, user_id, query, enrich_emails, max_results, lead_types, location)
    except Exception as e:
        logger.error(f"[LinkedIn:{search_id}] engine failed: {e}", exc_info=True)
        supabase = get_supabase_admin()
        await _update_search(supabase, search_id, {
            "status": "failed", "message": "Search failed unexpectedly", "error_message": str(e),
        })
