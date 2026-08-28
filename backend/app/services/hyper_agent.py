"""
HyperAgent — AI-Powered Lead Discovery Service

Flow:
  1. User describes their business/ideal lead
  2. OpenAI understands intent, asks clarifying questions
  3. User confirms: niche, location, city, lead count
  4. System scrapes LinkedIn via HarvestAPI (Apify)
  5. AI qualifies and scores leads (0-100)
  6. Returns high-quality leads to user

Only available for Pro and Agency plans.
"""

import json
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional

import httpx
from openai import OpenAI

from app.config import get_settings
from app.database import get_supabase_admin
from app.services.apify_service import (
    HARVEST_POST_SEARCH_ACTOR,
    _run_with_key,
    _ordered_keys,
    ApifyError,
)
from app.services.linkedin_pipeline import (
    ALLOWED_COUNTRY_CODES,
    BLOCKED_COUNTRY_CODES,
    _looks_south_asian,
)

logger = logging.getLogger(__name__)

# ── Quality gates (mirrors linkedin_pipeline) ─────────────────────────────
# When the user gives a specific non-US/EU country, respect it; otherwise
# keep leads to English-speaking/key EU markets.
FALLBACK_ALLOWED_COUNTRY_CODES = ALLOWED_COUNTRY_CODES

# Country name → ISO code (for matching author.location.countryCode)
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

# Big-city → country hints (used when a city is given but no country)
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

# Countries in blocked markets — used to decide whether to respect a
# user's requested location (leads allowed there) or gate it out.
USER_REQUESTABLE_COUNTRIES = {
    "IN", "PK", "BD", "PH", "NG", "VN", "ID", "TH", "MY", "KE", "GH", "ZA", "EG",
    "LK", "NP", "TR", "AE", "SA", "QA", "KW", "IL", "BR", "MX",
}


def _parse_location_request(location: str) -> tuple[set[str], str | None]:
    """Parse a user location request into (country_codes, city).

    'Mumbai' → ({"IN"}, "mumbai")
    'US'     → ({"US"}, None)
    'Dubai'  → ({"AE"}, "dubai")
    'UK'     → ({"GB"}, None)
    """
    if not location:
        return set(), None
    low = " ".join(location.lower().split()).strip(" ,.;")
    country_codes: set[str] = set()
    city: str | None = None

    # Whole string is a country code or name
    if low.isalpha() and low.upper() in ALLOWED_COUNTRY_CODES | BLOCKED_COUNTRY_CODES:
        return {low.upper()}, None
    if low in COUNTRY_NAME_TO_CODE:
        return {COUNTRY_NAME_TO_CODE[low]}, None

    # Try longest-match country names inside the string
    for name, code in sorted(COUNTRY_NAME_TO_CODE.items(), key=lambda kv: -len(kv[0])):
        if name in low:
            country_codes.add(code)
            low = low.replace(name, "")
            break
    low = " ".join(low.split()).strip(" ,;")

    # Remaining non-country part is treated as a city
    if low and len(low) >= 2:
        city = low
        if not country_codes:
            for city_name, code in CITY_COUNTRY_HINTS.items():
                if city_name in city:
                    country_codes.add(code)
                    break
    return country_codes, city


def _location_matches(author_location: str, author_country_code: str, country_codes: set[str], city: str | None) -> bool:
    """Does an author's location match the user's requested location?"""
    loc_low = (author_location or "").lower()
    if city:
        if city in loc_low:
            return True
        if author_country_code and author_country_code in country_codes:
            return True
        return False
    if country_codes:
        if author_country_code and author_country_code in country_codes:
            return True
        # No country code on the author — check text for country/city hints
        if loc_low:
            if any(city_name in loc_low for city_name, code in CITY_COUNTRY_HINTS.items() if code in country_codes):
                return True
            for name, code in COUNTRY_NAME_TO_CODE.items():
                if code in country_codes and name in loc_low:
                    return True
        return False
    return True

# ── System prompt for HyperAgent (V3 — conversational) ──────────────────
SYSTEM_PROMPT = """You are HyperAgent, an elite AI-powered B2B lead generation assistant built by Hyperclients.

Your job is to help freelancers, consultants, and agencies find highly relevant LinkedIn leads for the services they sell.

==================================================
ICP UNDERSTANDING
==================================================

Before searching, identify:

1. SERVICE — What exactly does the user sell?
2. TARGET CUSTOMER — What type of company/person should buy it?
3. TARGET ROLES — Who within the target customer is the buyer/decision-maker?
4. LOCATION — Country, region, or city.
5. LEAD COUNT — How many leads? Default = 20.

NEVER confuse SERVICE (what user sells) with TARGET CUSTOMER (who buys it).

Example: "I run an SEO agency and want SaaS companies in the US."
→ service=SEO, target_customer=SaaS companies, target_roles=Founder/CEO/Head of Marketing, location=US

LOCATION GRANULARITY:
- If the user names a CITY (e.g. "Mumbai", "London", "Dubai") — keep the city; leads will be filtered to that city/country.
- If the user names a COUNTRY (e.g. "India", "US", "UK") — use the whole country.
- If the user names a REGION (e.g. "Europe", "Gulf", "Middle East") — ask which country/city they mean (ONE question max), or use the largest English-speaking markets.
- The system filters leads by the requested location AFTER scraping, so accuracy matters: city → targeted city leads; country → country-wide leads.
- If the user gives BOTH a city and a country ("SaaS companies in Mumbai, India"), keep both.

==================================================
CONVERSATION RULES
==================================================

- Ask AT MOST 4 questions TOTAL, then confirm immediately
- NEVER ask questions the user already answered
- If user gives enough info in first message, skip to confirmation
- When user says "yes", "go", "start", "just start", "find them" — STOP ASKING, confirm with defaults immediately
- Be DIRECT and FAST. Speed > perfection.

DEFAULTS:
- lead_count = 20
- If target roles missing → choose most relevant decision-makers
- If city missing but country provided → use entire country
- If target industry missing → ask
- If service unclear → ask

When confirming, use this format:
🔍 **Ready to Search**
- **Service**: [service]
- **Target**: [customer type + roles]
- **Location**: [location]
- **Count**: [number]

Reply **YES** to start searching.

NEVER search without explicit user confirmation.
"""

QUALIFICATION_PROMPT = """You are a senior B2B lead qualification specialist. You decide whether a LinkedIn post is a genuine BUYING signal. Precision > recall: one excellent lead > ten noise records.

TARGET SERVICE: {niche}
TARGET ROLES: {roles}
TARGET LOCATION: {location}

==================================================
BUYER VS SELLING (MOST IMPORTANT)
==================================================

BUYING (potential lead):
- "We're looking for a developer"
- "I need someone to redesign our website"
- "Looking for an SEO agency"
- "Can anyone recommend a good paid ads agency?"
- "We need a freelancer to edit our videos"
- "We need help improving our Shopify conversion rate"

SELLING (reject):
- "I'm available for freelance work"
- "I'm open to new projects"
- "I offer web development services"
- "DM me if you need a designer"
- "My agency is taking on new clients"
- "I'm a freelance SEO specialist looking for projects"

==================================================
HARD REJECTION RULES (is_lead=false, score=0)
==================================================

R1 — SELLER: Author selling their own services
R2 — JOB SEEKER: Author looking for employment/clients for themselves
R3 — RECRUITER/STAFFING: Sourcing candidates for third-party employers
R4 — FULL-TIME EMPLOYEE: Permanent full-time hire (unless user specifically does recruitment)
R5 — FREE/UNPAID WORK: Volunteer, favors, student projects
R6 — CONTENT: Tips, trends, thought leadership, tutorials, case studies, opinions
R7 — SELF-PROMOTION: Promoting own service/agency/portfolio
R8 — THIRD-PARTY TALENT: Sourcing freelancers for another company
R9 — SERVICE MISMATCH: Requirement doesn't match user's service
R10 — KEYWORD TRAP: Post contains service keywords but NO buying intent
  Examples of keyword traps (NOT leads):
  - "SEO is important for SaaS"
  - "Looking for SEO professionals to follow"
  - "Web development trends"
  - "Any developers here?"
  There MUST be evidence of: a requirement, project, problem, vendor search, recommendation request, or hiring need.
R11 — DUPLICATE: Same requirement from same person/company
R12 — NON-ENGLISH: Post not in English

==================================================
BUYING SIGNAL TYPES
==================================================

- explicit_service_request: Directly asking for a service provider
- vendor_recommendation: Asking for recommendations/referrals
- hiring: Seeking freelance/contract/external expertise
- business_problem: Describing a problem the user's service can solve
- project_need: Current/upcoming project requires the service
- provider_dissatisfaction: Unhappy with existing provider
- research: Evaluating options, weaker buying evidence

==================================================
SCORING (5 dimensions, total 0-100)
==================================================

BUYING INTENT (0-30):
30 = explicit provider/service request with clear need
27 = explicit freelancer/contractor/external provider requirement
25 = direct recommendation/vendor request
22 = clear problem requiring the service
15 = legitimate but vague requirement
5 = weak commercial signal
0 = no buying intent

REQUIREMENT CLARITY (0-20):
20 = specific service + clear deliverable/project
17 = clear service requirement
12 = legitimate but general
5 = vague requirement
0 = no meaningful requirement

DECISION-MAKER RELEVANCE (0-20):
20 = founder/CEO/owner directly requesting
18 = VP/director/head with relevant responsibility
15 = manager/lead with relevant responsibility
10 = employee posting for the company
5 = authority unclear
0 = no credible buyer relevance

URGENCY (0-15):
15 = ASAP/urgent/immediate
12 = actively looking now
10 = current project/starting soon
5 = active requirement but no timeline
2 = future consideration
0 = no urgency

COMMERCIAL POTENTIAL (0-15):
15 = explicit budget, commercial project, provider search
12 = clearly commercial business requirement
8 = likely commercial requirement
3 = commercial potential unclear
0 = non-commercial

TOTAL = buying_intent + requirement_clarity + decision_maker + urgency + commercial_potential

==================================================
TIERS
==================================================

75-100 = HOT
40-74 = WARM
Below 40 = REJECT

MINIMUM for is_lead=true:
- score >= 40
- buying_intent > 0
- requirement_clarity >= 5
- genuine service match
- no hard rejection rule

==================================================
OUTPUT FORMAT
==================================================

Return ONLY valid JSON array:
[
  {{
    "name": "Full Name",
    "headline": "Job title at Company",
    "company": "Company Name",
    "location": "City, Country",
    "linkedin_url": "LinkedIn profile URL",
    "post_url": "the EXACT LinkedIn POST URL from the input (copy it unchanged; if missing, use empty string)",
    "is_lead": true,
    "score": 85,
    "tier": "HOT",
    "buying_intent": 27,
    "requirement_clarity": 18,
    "decision_maker_likelihood": 18,
    "urgency": 12,
    "commercial_potential": 10,
    "lead_type": "explicit_service_request|vendor_recommendation|hiring|business_problem|project_need|provider_dissatisfaction|research",
    "work_type": "remote|contract|part_time|full_time_onsite|unknown",
    "evidence_strength": "explicit|strong|moderate",
    "outreach_competition": "very_low|low|moderate|high|very_high",
    "comments": 8,
    "likes": 35,
    "reason": "1-2 sentences with SPECIFIC evidence from post",
    "outreach_angle": "one specific opening line referencing their exact situation (max 25 words)",
    "post_content": "First 200 chars of post"
  }}
]

RULES:
- Return ONLY valid JSON, no markdown
- Maximum 50 qualifying leads
- Never include leads below score 40
- Never include rejected candidates
- Sort by score descending
- Preserve LinkedIn URLs and engagement numbers exactly
- Use null when info unavailable
"""


class HyperAgentService:
    """Main HyperAgent service for conversational lead discovery."""

    def __init__(self):
        settings = get_settings()
        self.openai = OpenAI(api_key=settings.openai_api_key)
        self.db = get_supabase_admin()

    def _get_harvest_key(self) -> str:
        """Get a working HarvestAPI key from the key rotation pool."""
        settings = get_settings()

        # Try the primary key first
        primary_key = settings.apify_api_key
        if primary_key:
            try:
                httpx.get(
                    f"https://api.apify.com/v2/acts/{HARVEST_POST_SEARCH_ACTOR}",
                    params={"token": primary_key},
                    timeout=10,
                )
                return primary_key
            except Exception:
                pass

        # Fallback to key rotation
        keys = _ordered_keys()
        if keys:
            return keys[0]
        raise ApifyError("No Apify keys available")

    def chat(self, message: str, history: list[dict], user_id: str) -> dict:
        """Process a chat message and return AI response.

        Args:
            message: User's message
            history: Conversation history [{role: "user"|"assistant", content: "..."}]
            user_id: Current user ID

        Returns:
            {response: str, action: str, data: dict|None}
        """
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history)
        messages.append({"role": "user", "content": message})

        response = self.openai.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.7,
            max_tokens=2000,
        )

        ai_message = response.choices[0].message.content

        # Check if user confirmed (YES/CONFIRM/START)
        if self._is_confirmation(message):
            # Check if we have enough info from history
            context = self._extract_context(history + [{"role": "user", "content": message}])
            if context.get("niche") and context.get("location"):
                return {
                    "response": ai_message,
                    "action": "scrape",
                    "data": context,
                }
            else:
                return {
                    "response": ai_message + "\n\n⚠️ I still need more details. Please specify the niche and location.",
                    "action": "chat",
                    "data": None,
                }

        return {
            "response": ai_message,
            "action": "chat",
            "data": None,
        }

    def _is_confirmation(self, message: str) -> bool:
        """Check if user is confirming the search. Uses word boundaries to avoid false matches."""
        import re
        msg = message.lower().strip()
        # Reject messages that start with "no"
        if msg.startswith("no"):
            return False
        # Exact match or standalone word match
        exact_matches = ["yes", "confirm", "go", "proceed", "find them", "let's go"]
        if any(msg == kw for kw in exact_matches):
            return True
        # Word boundary match for longer phrases
        word_matches = [r'\byes\b', r'\bconfirm\b', r'\bstart\b', r'\bgo\b', r'\bdo it\b', r'\bproceed\b', r'\bfind them\b', r"\blet's go\b", r'\bsearch\b']
        return any(re.search(pat, msg) for pat in word_matches)

    def _extract_context(self, history: list[dict]) -> dict:
        """Extract ICP context from conversation history using AI."""
        # Build a summary of the conversation
        conversation = "\n".join(
            f"{m['role']}: {m['content']}" for m in history[-10:]  # last 10 messages
        )

        response = self.openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """Extract the lead search parameters from this conversation.
Return ONLY a JSON object with these fields:
{
  "niche": "industry/niche (e.g., SaaS, E-commerce, Real Estate)",
  "roles": "target job titles (e.g., CTO, Marketing Director, Founder)",
  "location": "city, country (e.g., San Francisco, USA)",
  "company_size": "company size range (e.g., 10-50 employees)",
  "count": number of leads needed (default 20),
  "posted_within": "timeframe (e.g., week, month)"
}
If a field is not mentioned, use null.""",
                },
                {"role": "user", "content": conversation},
            ],
            temperature=0,
            max_tokens=500,
            response_format={"type": "json_object"},
        )

        try:
            return json.loads(response.choices[0].message.content)
        except Exception:
            return {}

    def scrape_leads(self, context: dict) -> list[dict]:
        """Scrape LinkedIn using HarvestAPI based on confirmed context.

        Args:
            context: {niche, roles, location, count, ...}

        Returns:
            List of raw LinkedIn post/author items
        """
        niche = context.get("niche", "")
        roles = context.get("roles", "")
        location = context.get("location", "")
        count = min(context.get("count", 20), 50)

        # Build search queries from context
        queries = self._build_queries(niche, roles, location)
        logger.info(f"[HyperAgent] Queries: {queries}")

        key = self._get_harvest_key()
        max_posts = count * 5  # Get 5x to have enough after qualification filtering

        payload = {
            "searchQueries": queries,
            "maxPosts": min(max_posts, 150),
            "postedLimit": str(context.get("posted_within") or "month"),
            "sortBy": "date",
            # "main" mode returns full author metadata (countryCode, currentPosition,
            # info) on every post — critical for country gating + company extraction.
            # This does NOT change post search into profile scraping.
            "profileScraperMode": "main",
            "scrapeReactions": False,
            "postNestedReactions": False,
            "scrapeComments": False,
            "postNestedComments": False,
        }

        items = _run_with_key(HARVEST_POST_SEARCH_ACTOR, key, payload)
        logger.info(f"[HyperAgent] HarvestAPI returned {len(items)} items")
        return items

    def _build_queries(self, niche: str, roles: str, location: str) -> list[str]:
        """Build targeted LinkedIn search queries using BUYER-INTENT phrases.

        Mirrors the search section's approach: real buying intent rarely looks
        like "I need X" — it looks like "looking for a freelance web developer",
        "hiring a designer for our project", "website developer required".
        """
        queries = []
        seen: set[str] = set()

        def _add(q: str) -> None:
            q = " ".join(q.split())
            key = q.lower().strip('"')
            if key and key not in seen and len(queries) < 12:
                seen.add(key)
                queries.append(q)

        role_list = [r.strip() for r in roles.split(",") if r.strip()] if roles else []
        niche_terms = [n.strip() for n in niche.split(",") if n.strip()] if niche else []

        # Role variants from niche (website development -> website developer)
        role_variants: set[str] = set()
        niche_low = niche.lower()
        if "development" in niche_low:
            role_variants.add(niche.replace("development", "developer").strip())
        if "design" in niche_low:
            role_variants.add(niche.replace("design", "designer").strip())
        if "marketing" in niche_low:
            role_variants.add(f"{niche} expert")
            role_variants.add(f"{niche} specialist")
        if "seo" in niche_low:
            role_variants.add("seo expert")
        if "shopify" in niche_low or "ecommerce" in niche_low:
            role_variants.add("shopify expert")
        if "web" in niche_low or "website" in niche_low:
            role_variants.add(f"{niche.replace(' website', '').replace('website', 'web').strip()} developer")
            role_variants.add(f"{niche.replace(' website', '').replace('website', 'web').strip()} designer")
        all_roles = list(dict.fromkeys(role_list + list(role_variants)))

        # BUYER-INTENT phrases first (highest priority - attract companies hiring)
        for role in all_roles:
            _add(f"looking for a freelance {role}")
            _add(f"looking for freelance {role}")
            _add(f"hiring {role}")
            _add(f"need a {role} for our")
            _add(f"looking for {role} for our")
            _add(f"need {role} for our")
            _add(f"recommend a {role}")

        # Niche-level intent phrases
        for n in niche_terms:
            _add(f"looking for {n}")
            _add(f"need {n}")
            _add(f"{n} help")
            _add(f"recommend {n}")

        # Location-scoped queries — if a city is given, target it directly
        if location:
            loc = location.split(",")[0].strip() if location else ""
            if loc:
                for role in all_roles[:3]:
                    _add(f"hiring {role} in {loc}")
                    _add(f"looking for {role} in {loc}")
                    _add(f"{role} {loc}")
                for n in niche_terms[:2]:
                    _add(f"{n} in {loc}")
                    _add(f"looking for {n} in {loc}")

        # Fallback
        if not queries:
            queries = [f'"{niche}"' if niche else "business development"]

        return queries[:12]  # Max 12 queries

    def qualify_leads(self, items: list[dict], context: dict) -> list[dict]:
        """Use AI to qualify and score scraped leads.

        Quality gates mirror the search section pipeline:
        1. Country gating (exclude low-value markets unless user asked for them)
        2. Author dedupe (one best post per author)
        3. AI qualification (5-dimension V3 scoring)
        4. Code-level work-type gate (full_time_onsite hiring rejected)
        5. AI triage fallback — remaining authors are screened, not blindly accepted

        Args:
            items: Raw LinkedIn items from HarvestAPI
            context: ICP context

        Returns:
            Qualified leads sorted by score
        """
        if not items:
            return []

        user_location = (context.get("location") or "").lower()
        req_country_codes, req_city = _parse_location_request(user_location)
        # If the user explicitly wants a country we'd normally gate out, allow it.
        respect_user_location = bool(
            req_country_codes & USER_REQUESTABLE_COUNTRIES
            or req_city and any(city_name in user_location for city_name in ("mumbai", "delhi", "bangalore", "bengaluru", "hyderabad", "pune", "chennai", "karachi", "lahore", "dhaka", "manila", "lagos", "nairobi", "dubai", "abu dhabi", "riyadh", "doha", "kuwait", "singapore", "tel aviv", "sao paulo", "mexico city", "cairo"))
        )

        # Extract author info from items (mirroring linkedin_pipeline.process_items)
        authors = []
        seen: set[str] = set()
        for item in items:
            author = item.get("author") or item.get("profile") or {}
            if not isinstance(author, dict):
                author = {}
            name = author.get("name") or author.get("fullName") or ""
            author_url = (author.get("url") or author.get("linkedinUrl") or "").strip()
            if not name or not author_url:
                continue
            clean_url = author_url.split("?")[0].rstrip("/").lower()
            if clean_url in seen:
                continue
            seen.add(clean_url)

            post_content = item.get("content") or item.get("text") or item.get("postContent") or ""
            if len(post_content) < 20:
                continue  # too thin to judge intent
            engagement = item.get("engagement") or {}
            if not isinstance(engagement, dict):
                engagement = {}

            # Country gate — drop authors from low-value markets unless the
            # user explicitly asked for that market.
            country_code = ""
            loc = author.get("location") or {}
            if isinstance(loc, dict):
                country_code = (loc.get("countryCode") or "").strip().upper()
            if not respect_user_location:
                if country_code and country_code in BLOCKED_COUNTRY_CODES:
                    continue
                if not country_code and _looks_south_asian(name):
                    continue

            # Company extraction (handles list or dict currentPosition)
            company = ""
            positions = author.get("currentPosition") or []
            if isinstance(positions, list):
                for pos in positions:
                    if not isinstance(pos, dict):
                        continue
                    company = pos.get("companyName") or pos.get("name") or (pos.get("company") or {}).get("name")
                    if company:
                        company = str(company)[:100]
                        break
            elif isinstance(positions, dict):
                company = positions.get("companyName") or positions.get("name") or ""

            headline = author.get("info") or author.get("headline") or author.get("title") or ""
            if not company:
                if " at " in headline:
                    company = headline.split(" at ", 1)[1].split("|")[0].strip()[:100]

            author_location = self._extract_location(author)
            loc_match = _location_matches(author_location, country_code, req_country_codes, req_city) if (req_country_codes or req_city) else True

            authors.append({
                "name": name,
                "headline": headline,
                "company": company,
                "location": author_location,
                "country_code": country_code,
                "location_match": loc_match,
                "linkedin_url": author_url,
                "post_url": item.get("url") or item.get("linkedinUrl") or item.get("postUrl") or "",
                "profile_picture_url": self._extract_avatar(author),
                "post_content": post_content[:200],
                "engagement": {
                    "likes": engagement.get("likes", 0),
                    "comments": engagement.get("comments", 0),
                },
            })

        if not authors:
            return []

        # Batch qualify with AI (max 25 per batch for reliability)
        qualified = []
        for i in range(0, len(authors), 25):
            batch = authors[i:i+25]
            batch_qualified = self._ai_qualify_batch(batch, context)
            qualified.extend(batch_qualified)

        # Code-level hard gate: full-time on-site hiring is never a lead
        qualified = [
            q for q in qualified
            if not ((q.get("lead_type") == "hiring") and (q.get("work_type") == "full_time_onsite"))
        ]

        # Sort by score
        qualified.sort(key=lambda x: x.get("score", 0), reverse=True)

        # If the user requested a specific location, keep only location-matching
        # leads first; relax to any allowed-country leads only if we fall short.
        requested_count = context.get("count", 20)
        if req_country_codes or req_city:
            loc_matched = [q for q in qualified if q.get("location_match")]
            if len(loc_matched) >= requested_count:
                qualified = loc_matched
            else:
                qualified = loc_matched + [q for q in qualified if not q.get("location_match")]

        # If we have fewer than requested, run an AI triage pass on the
        # remaining authors instead of blindly accepting them. Location
        # matches are prioritized in the triage order.
        if len(qualified) < requested_count:
            qualified_urls = {l.get("linkedin_url", "").lower() for l in qualified}
            remaining = [
                a for a in authors
                if a.get("linkedin_url", "").lower() not in qualified_urls
            ]
            remaining.sort(key=lambda a: (a.get("location_match") or False, a.get("engagement", {}).get("likes", 0)), reverse=True)
            for i in range(0, len(remaining), 25):
                batch = remaining[i:i+25]
                batch_qualified = self._ai_triage_batch(batch, context)
                qualified.extend(batch_qualified)
            qualified.sort(key=lambda x: (x.get("location_match") or False, x.get("score", 0)), reverse=True)

        return qualified[:max(requested_count, 50)]

    def _ai_triage_batch(self, batch: list[dict], context: dict) -> list[dict]:
        """Cheap single-question screen for remaining authors (mirrors triage in
        linkedin_pipeline). Only genuine buyers with a requirement are kept."""
        triage_prompt = f"""You are a B2B lead triage specialist. TARGET SERVICE: {context.get('niche', '')}.

For each post below, decide ONE thing: is the AUTHOR a genuine BUYER of this service (hiring freelancers/agencies/contractors, asking for recommendations, or describing a project/requirement the service solves)?

REJECT if the author is: selling their own services, a job seeker, a recruiter/staffing agency, sharing content/tips, hiring for full-time on-site roles, or the post is not English.

Return ONLY a JSON array of indices of KEEP posts, e.g. [0, 3, 5]. If none, return []."""

        batch_text = "\n\n".join(
            f"[{i}] {b.get('name', '')} | {b.get('headline', '')} | {b.get('post_content', '')[:300]}"
            for i, b in enumerate(batch)
        )

        try:
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": triage_prompt},
                    {"role": "user", "content": f"Posts:\n\n{batch_text}"},
                ],
                temperature=0,
                max_tokens=80,
            )
            result_text = response.choices[0].message.content or ""
            start = result_text.find("[")
            end = result_text.rfind("]") + 1
            keep_idx = []
            if start >= 0 and end > start:
                keep_idx = json.loads(result_text[start:end])
        except Exception as e:
            logger.warning(f"[HyperAgent] Triage failed: {e}")
            return []

        accepted = []
        for i in keep_idx:
            if isinstance(i, int) and 0 <= i < len(batch):
                author = dict(batch[i])
                author["score"] = 45
                author["is_lead"] = True
                author["lead_type"] = "research"
                author["work_type"] = "unknown"
                author["evidence_strength"] = "moderate"
                author["reason"] = "Triaged as genuine buyer with a requirement"
                author["outreach_angle"] = ""
                accepted.append(author)
        return accepted

    def _ai_qualify_batch(self, batch: list[dict], context: dict) -> list[dict]:
        """Qualify a batch of leads with AI scoring (V3 format)."""
        prompt = QUALIFICATION_PROMPT.format(
            niche=context.get("niche", ""),
            roles=context.get("roles", ""),
            location=context.get("location", ""),
        )

        leads_text = json.dumps(batch, indent=2)

        response = self.openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Qualify these leads:\n\n{leads_text}"},
            ],
            temperature=0,
            max_tokens=4000,
        )

        result_text = response.choices[0].message.content

        # Extract JSON from response
        try:
            start = result_text.find("[")
            end = result_text.rfind("]") + 1
            if start >= 0 and end > start:
                leads = json.loads(result_text[start:end])
                # Re-attach author-only fields the AI doesn't return:
                # post_url, profile_picture_url, location, country_code,
                # location_match — matched by linkedin_url or name.
                by_url = {}
                for a in batch:
                    url = (a.get("linkedin_url") or "").strip().lower()
                    if url:
                        by_url[url] = a
                    elif a.get("name"):
                        by_url.setdefault(("name:" + a["name"].lower()), a)
                for l in leads:
                    url = (l.get("linkedin_url") or "").strip().lower()
                    src = by_url.get(url) or by_url.get("name:" + (l.get("name") or "").lower())
                    if src:
                        for field in ("post_url", "profile_picture_url", "location", "country_code", "location_match"):
                            if not l.get(field):
                                l[field] = src.get(field) or ""
                # Filter: accept leads with score >= 40 (V3 threshold)
                return [l for l in leads if l.get("score", 0) >= 40 and l.get("is_lead", True)]
        except json.JSONDecodeError:
            logger.warning(f"[HyperAgent] Failed to parse AI qualification response")

        return []

    def _extract_location(self, author: dict) -> str:
        """Extract location string from author data."""
        loc = author.get("location") or {}
        if isinstance(loc, dict):
            return loc.get("linkedinText") or loc.get("text") or loc.get("city") or ""
        return str(loc) if loc else ""

    def _extract_avatar(self, author: dict) -> str:
        """Extract profile picture URL from author data."""
        avatar = author.get("avatar") or author.get("profilePicture") or {}
        if isinstance(avatar, dict):
            return avatar.get("url") or ""
        return str(avatar) if avatar else ""

    def save_leads(self, leads: list[dict], user_id: str, search_id: str) -> int:
        """Save qualified leads to the database (V3 format)."""
        saved = 0
        for lead in leads:
            try:
                score = lead.get("score", 0)
                is_lead = lead.get("is_lead", True) if "is_lead" in lead else True
                if not is_lead or score < 40:
                    continue

                lead_category = "hot" if score >= 75 else "warm"

                # Map V3 lead_type to post_type CHECK values
                ai_type = (lead.get("lead_type") or "").lower()
                if ai_type in ("explicit_service_request", "vendor_recommendation", "business_problem", "project_need", "provider_dissatisfaction", "research"):
                    post_type = "buyer"
                elif ai_type == "hiring":
                    post_type = "hiring"
                else:
                    post_type = "buyer"

                # Build headline with work_type tag
                headline = lead.get("headline") or ""
                work_type = (lead.get("work_type") or "").lower()
                work_label = {
                    "remote": "🌍 Remote",
                    "contract": "📄 Contract",
                    "part_time": "⏱️ Part-time",
                    "full_time_onsite": "🏢 On-site",
                }.get(work_type)
                if work_label and headline:
                    headline = f"{work_label} — {headline}"
                elif work_label:
                    headline = work_label

                self.db.table("leads").insert({
                    "user_id": user_id,
                    "search_id": search_id,
                    "source": "hyper_agent",
                    "business_name": lead.get("name", "Unknown"),
                    "headline": headline,
                    "linkedin_url": lead.get("linkedin_url", ""),
                    "post_url": lead.get("post_url", ""),
                    "full_address": lead.get("location", ""),
                    "category": lead.get("company", ""),
                    "lead_category": lead_category,
                    "post_type": post_type,
                    "profile_picture_url": lead.get("profile_picture_url", ""),
                    "ai_qualified": True,
                    "ai_confidence_score": score / 100.0,
                    "ai_reason": lead.get("reason", ""),
                    "ai_pitch": lead.get("outreach_angle", ""),
                    "post_text": lead.get("post_content", ""),
                    "user_status": "new",
                    "is_favorite": False,
                }).execute()
                saved += 1
            except Exception as e:
                logger.warning(f"[HyperAgent] Failed to save lead: {e}")

        return saved
