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
    'Asia'   → ({"IN","PK","BD","PH","VN","ID","TH","MY","SG","JP","KR","TW"}, None)
    'Europe' → ({"GB","DE","FR","NL","BE","CH","AT","SE","NO","DK","FI","ES","IT","PT","IE"}, None)
    """
    if not location:
        return set(), None
    low = " ".join(location.lower().split()).strip(" ,.;")

    # Region name mappings (for Q3 location selections)
    REGION_MAP = {
        "asia": {"IN", "PK", "BD", "PH", "VN", "ID", "TH", "MY", "SG", "JP", "KR", "TW"},
        "united states": {"US"},
        "india": {"IN"},
        "europe": {"GB", "DE", "FR", "NL", "BE", "CH", "AT", "SE", "NO", "DK", "FI", "ES", "IT", "PT", "IE"},
        "africa": {"NG", "KE", "GH", "ZA", "EG"},
        "australia": {"AU", "NZ"},
        "canada": {"CA"},
        "south america": {"BR", "MX", "AR", "CL", "CO"},
    }

    # Handle region names first (exact match or contained)
    # Support multiple regions separated by commas
    all_region_codes: set[str] = set()
    found_region = False
    for region_name, codes in REGION_MAP.items():
        if region_name in low:
            all_region_codes |= codes
            found_region = True
    if found_region:
        return all_region_codes, None

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


def _is_post_url(url: str) -> bool:
    """A LinkedIn POST url contains /posts/ or /feed/update/ or /activity-.
    Profile URLs contain /in/ — those are NOT post URLs."""
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
    """Extract the real LinkedIn POST url from a harvestapi item.

    Actor format (confirmed from harvestapi docs):
      item.linkedinUrl  → the POST url  (https://www.linkedin.com/posts/...)
      item.url          → may be absent or something else
      author.linkedinUrl → the PROFILE url (never use for posts)
    """
    for key in ("linkedinUrl", "postUrl", "post_url", "url"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            cleaned = val.strip()
            if _is_post_url(cleaned):
                return cleaned
    # last resort: nested socialContent.shareUrl
    sc = item.get("socialContent") or {}
    if isinstance(sc, dict):
        share = sc.get("shareUrl")
        if isinstance(share, str) and _is_post_url(share):
            return share
    return ""

# ── System prompt for HyperAgent (V3 — conversational) ──────────────────
SYSTEM_PROMPT = """You are HyperAgent, an elite AI-powered B2B lead generation assistant built by Hyperclients.

Your job is to help freelancers, consultants, and agencies find highly relevant LinkedIn leads for the services they sell.

==================================================
CONVERSATION FLOW — 3 QUESTIONS MAX THEN CONFIRM
==================================================

Always follow this EXACT order. Do NOT skip questions the user hasn't answered.

**Step 1 — Ask Q1: Lead Type**
Start your FIRST message with:
LEAD_TYPES_QUESTION

Then ask:
What kind of leads are you looking for?
1️⃣ Hiring posts (Full-time/contractor/Part-time/Freelancers)
2️⃣ People or Companies Looking for Freelancers
3️⃣ People or Companies Looking for Agencies

**Step 2 — Ask Q2: Services Provided**
After the user answers Q1, ask:
What services do you provide? (comma-separated, e.g. website banner design, social media post design, email newsletter design)

**Step 3 — Ask Q3: Buyer Location**
After the user answers Q2, ask:
Where are your buyers located?

Start your message with the exact line:
LOCATION_QUESTION

Then list the options:
📍 Select one or more:
- Asia
- United States
- India
- Europe
- Africa
- Australia
- Canada
- South America

**Step 4 — Confirm & Search**
Once all 3 questions are answered, present the confirmation card and wait for YES.

==================================================
ICP UNDERSTANDING
==================================================

From the user's answers, identify:
1. SERVICE — What exactly does the user sell? (from Q2)
2. TARGET CUSTOMER — What type of company/person should buy it?
3. TARGET ROLES — Who within the target customer is the buyer/decision-maker?
4. LOCATION — From Q3, map regions to country codes:
   - Asia → IN, PK, BD, PH, VN, ID, TH, MY, SG, JP, KR, TW
   - United States → US
   - India → IN
   - Europe → GB, DE, FR, NL, BE, CH, AT, SE, NO, DK, FI, ES, IT, PT, IE
   - Africa → NG, KE, GH, ZA, EG
   - Australia → AU, NZ
   - Canada → CA
   - South America → BR, MX, AR, CL, CO
5. LEAD COUNT — Default = 20.

NEVER confuse SERVICE (what user sells) with TARGET CUSTOMER (who buys it).

==================================================
CONVERSATION RULES
==================================================

- Ask AT MOST 3 questions (Q1, Q2, Q3), then confirm immediately
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

==================================================
LOCATION MAPPING FROM Q3
==================================================

When the user selects regions in Q3, convert to country codes:
- "Asia" → India, Pakistan, Bangladesh, Philippines, Vietnam, Indonesia, Thailand, Malaysia, Singapore, Japan, South Korea, Taiwan
- "United States" → US
- "India" → India
- "Europe" → UK, Germany, France, Netherlands, Belgium, Switzerland, Austria, Sweden, Norway, Denmark, Finland, Spain, Italy, Portugal, Ireland
- "Africa" → Nigeria, Kenya, Ghana, South Africa, Egypt
- "Australia" → Australia, New Zealand
- "Canada" → Canada
- "South America" → Brazil, Mexico, Argentina, Chile, Colombia

Use these country codes when building the search.

==================================================
LEAD TYPE QUESTION (ask FIRST as Q1)
==================================================

When you ask the lead type question, start your message with the exact line:

LEAD_TYPES_QUESTION

Then ask:
Which kind of leads would you want?
1️⃣ Hiring posts — companies hiring freelancers/contractors (Full-time/contractor/Part-time/Freelancers)
2️⃣ People or Companies Looking for Freelancers
3️⃣ People or Companies Looking for Agencies

The user may pick one, several, or say "all". Record their answer as lead_types: "hiring", "freelancer", "agency".

IMPORTANT BUSINESS RULE:
- If the user IS an agency/company (they sell services as a business), they almost always want type 3 (people looking for Agencies) and possibly type 2 — NOT hiring posts. If they say they're an agency, recommend type 3 and confirm they don't want hiring posts.
- If the user is a freelancer, they want type 2 (people looking for Freelancers), not hiring posts.
- Hiring posts (type 1) are only for users who explicitly want to find companies hiring.

When confirming, use this format:
🔍 **Ready to Search**
- **Service**: [service]
- **Target**: [customer type + roles]
- **Location**: [location]
- **Count**: [number]

Reply **YES** to start searching.

NEVER search without explicit user confirmation.
"""

QUALIFICATION_PROMPT = """You are a senior B2B lead qualification specialist for an AI-powered lead-generation platform. You decide whether a LinkedIn post is a genuine BUYING signal that a service provider could convert into a client. Your decisions feed a CRM, so precision matters more than recall: one excellent lead is worth more than ten noise records.

TARGET SERVICE: {niche}
TARGET ROLES: {roles}
TARGET LOCATION: {location}

WORKFLOW — always follow these steps in order:
1. Read the post and identify the AUTHOR's role (headline/company).
2. Determine WHO IS THE SUBJECT: is the author BUYING this service, or SELLING their own labor/services?
3. Identify the work arrangement (remote / contract / part-time / full-time on-site).
4. Apply the hard rules below.
5. Score the six dimensions, then compute score.
6. Cross-check internal consistency before emitting JSON.

==================================================
🚨 SELLER REJECTION — READ THIS FIRST (MOST IMPORTANT)
==================================================

We ONLY want REAL BUYERS: people and companies that NEED a service and are looking to HIRE/PURCHASE it. We NEVER want service providers promoting themselves.

AUTHOR IS A SELLER/PROVIDER (REJECT — is_lead=false, score=0) if ANY of these are true:
- Their headline contains: "Freelance X", "Founder of X agency", "X Agency", "X Studio", "X Company", "X Consultant", "X Solutions", "X Services", "X Marketing", "Helping businesses with X", "I help businesses", "X agency helping"
- Their company contains: agency, studio, solutions, services, consultancy, consulting, marketing, digital, media, tech solutions, "& co", "llc" that provides the same service as the target
- The post promotes their OWN services: "I help", "we help", "we provide", "I provide", "our services", "my agency", "my team", "DM me", "book a call", "portfolio", "check my work", "case studies", "we specialize", "I specialize", "open for projects", "available for work", "taking new clients", "need clients", "clients in X", "I'm looking for clients"
- They are sharing their work/achievements: "proud to announce", "launched a website for", "my new project", "I built", "we built", "client work", "success story", "case study of"

AUTHOR IS A REAL BUYER (ACCEPT) if:
- They explicitly need a service: "we're looking for", "I need someone to", "looking for someone who can", "need help with X"
- They are sourcing: "looking for an agency", "recommend an agency", "who do you use for X?", "need a freelancer for X project", "hiring a designer/developer for our project"
- They describe a BUSINESS PROBLEM their company has: "our website isn't converting", "our sales dropped", "we don't have a website", "launching a product, need X"
- "Looking for partners/agencies/marketers/freelancers" = SOURCING suppliers = BUYER.

THE #1 MISTAKE TO AVOID: Rejecting a post just because it mentions the service name. "I help companies with SEO" (seller) vs "our SEO isn't working, need help" (buyer). ALWAYS ask: does the author WANT to buy this service, or DO they provide it?

==================================================
HARD RULES (never violate)
==================================================
- R1: A company/owner HIRING a freelancer/contractor/agency on a REMOTE, CONTRACT or PART-TIME basis = STRONG LEAD.
- R2: A company hiring a FULL-TIME ON-SITE employee = NOT a lead (is_lead=false). They are building a payroll team, not buying your service.
- R3: SELLER/PROVIDER (see above) = NEVER a lead, regardless of how well the post matches the niche.
- R4: A RECRUITER/STAFFING agency posting on behalf of clients = NOT a lead.
- R5: Job seekers looking for a role for themselves = NOT a lead.
- R6: Pure content/thought-leadership ("5 tips", "why you need", "trends", "case study", "opinion") = NOT a lead even if it scores high on service_match.
- R7: NON-ENGLISH posts (Spanish, German, French, Hindi, Arabic, etc.) = NOT a lead (is_lead=false). We only serve English-speaking markets.
- R8: IF HEADLINE SAYS "FREELANCE X" OR "X AGENCY" AND THE POST DOES NOT EXPLICITLY REQUEST THE SERVICE → REJECT. Sellers rarely buy; when in doubt, REJECT.

WHO IS THE SUBJECT? (the single most important question)
SELLING (reject): "I'm available for X", "I'm open to remote work", "I'm seeking projects", "Looking to collaborate", "I offer X", "DM me for X", "I provide X", "My services include", "I build X", "I help companies". Headline reads "Freelance X"/"X Agency"/"Founder of X Agency" and the post promotes their availability or work.
BUYING (accept): "We're looking for a developer", "I need a website", "Looking for someone to build our X", "We are hiring a freelance X for a project", "Need a designer on contract", "Anyone know a good agency?", "Recommendations for X services?", or a business describing a problem it needs solved (traffic drop, no website, bad conversions, launching a product).
RECRUITER EXCEPTION: staffing agency placing candidates at THIRD-PARTY clients = reject. BUT a firm saying "Experts required for our projects" = BUYING expertise = ACCEPT (lead_type="hiring").

SCORING (six dimensions, then total):
- service_match (0-25): direct mention = 25; adjacent problem = 20; general growth = 15; vague = 10; unrelated = 0.
- business_problem (0-20): metrics declining/explicit build = 20; clear pain = 15; dissatisfaction = 10; exploring = 5; none = 0.
- buying_intent (0-20): explicit vendor search with budget/ASAP = 20; HIRING freelancer/remote/part-time = 18; strong implicit ("recommendations?") = 15; problem + commercial context = 10; passive = 5; none = 0.
- decision_maker_likelihood (0-15): Founder/CEO/Owner/VP/Director = 15; Manager/Lead = 12; unclear but business context = 10; individual contributor = 5; student = 0.
- urgency (0-10): urgent/ASAP = 10; looking now = 8; soon = 7; active problem no timeline = 5; none = 0.
- outreach_worthiness (0-10): explicit vendor search + problem + decision maker = 10; strong problem + reachable role = 8; clear problem unclear authority = 6; vague = 4; wrong audience = 0.

score = sum (0-100).
TIERS: 85+ HOT, 70-84 WARM, 40-69 POTENTIAL, 25-39 BORDERLINE, <25 NOT a lead.

CONSISTENCY: is_lead=true requires score>=25 AND service_match>=10. hiring+full_time_onsite => is_lead=false. agency/irrelevant => is_lead=false. SELLER (R3/R8) => is_lead=false.

OUTREACH_ANGLE: reference a SPECIFIC detail from their post/company; never generic; 1 sentence under 25 words.

OUTPUT FORMAT — return ONLY valid JSON array:
[
  {{
    "name": "Full Name",
    "headline": "Job title at Company",
    "company": "Company Name",
    "location": "City, Country",
    "linkedin_url": "the EXACT LinkedIn profile URL from the input (copy unchanged)",
    "post_url": "the EXACT LinkedIn POST URL from the input (copy unchanged; if missing, empty string)",
    "is_lead": true,
    "score": 85,
    "tier": "HOT",
    "service_match": 22,
    "business_problem": 18,
    "buying_intent": 17,
    "decision_maker_likelihood": 13,
    "urgency": 8,
    "outreach_worthiness": 7,
    "lead_type": "explicit_need|problem_awareness|research|hiring|agency|irrelevant",
    "work_type": "remote|contract|part_time|full_time_onsite|unknown",
    "evidence_strength": "explicit|strong|moderate",
    "outreach_competition": "very_low|low|moderate|high|very_high",
    "reason": "1-2 sentences with SPECIFIC quoted evidence from the post",
    "outreach_angle": "one specific opening line referencing their exact situation (max 25 words)",
    "post_content": "First 200 chars of post"
  }}
]

RULES:
- Return ONLY valid JSON, no markdown
- Maximum 50 qualifying leads
- Never include leads below score 25 or with service_match < 10
- Never include rejected candidates (is_lead=false)
- Sort by score descending
- Preserve LinkedIn URLs (profile AND post) and engagement numbers exactly
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

    def chat(self, message: str, history: list[dict], user_id: str, lead_types: list[str] | None = None) -> dict:
        """Process a chat message and return AI response.

        Args:
            message: User's message
            history: Conversation history [{role: "user"|"assistant", content: "..."}]
            user_id: Current user ID
            lead_types: User-selected lead type preference (from checkboxes)

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

        # If the AI is asking the lead-type question, return a special action
        # so the frontend can render checkbox options.
        if "LEAD_TYPES_QUESTION" in (ai_message or ""):
            clean = (ai_message or "").replace("LEAD_TYPES_QUESTION", "").strip()
            return {
                "response": clean,
                "action": "lead_types",
                "data": {
                    "options": [
                        {"id": "hiring", "label": "Hiring posts (Full-time/contractor/Part-time/Freelancers)", "description": "Companies hiring freelancers/contractors"},
                        {"id": "freelancer", "label": "People or Companies Looking for Freelancers", "description": "\"Need a freelancer for X\""},
                        {"id": "agency", "label": "People or Companies Looking for Agencies", "description": "\"Looking for an X agency\", \"recommend a good agency\""},
                    ],
                    "context": self._extract_context(history + [{"role": "user", "content": message}]),
                },
            }

        # If the AI is asking the location question, return a special action
        # so the frontend can render region checkboxes.
        if "LOCATION_QUESTION" in (ai_message or ""):
            clean = (ai_message or "").replace("LOCATION_QUESTION", "").strip()
            return {
                "response": clean,
                "action": "location",
                "data": {
                    "options": [
                        {"id": "asia", "label": "Asia", "countries": "IN, PK, BD, PH, VN, ID, TH, MY, SG, JP, KR, TW"},
                        {"id": "united_states", "label": "United States", "countries": "US"},
                        {"id": "india", "label": "India", "countries": "IN"},
                        {"id": "europe", "label": "Europe", "countries": "GB, DE, FR, NL, BE, CH, AT, SE, NO, DK, FI, ES, IT, PT, IE"},
                        {"id": "africa", "label": "Africa", "countries": "NG, KE, GH, ZA, EG"},
                        {"id": "australia", "label": "Australia", "countries": "AU, NZ"},
                        {"id": "canada", "label": "Canada", "countries": "CA"},
                        {"id": "south_america", "label": "South America", "countries": "BR, MX, AR, CL, CO"},
                    ],
                    "context": self._extract_context(history + [{"role": "user", "content": message}]),
                },
            }

        # Check if user confirmed (YES/CONFIRM/START)
        if self._is_confirmation(message):
            # Check if we have enough info from history
            context = self._extract_context(history + [{"role": "user", "content": message}])
            if lead_types:
                context["lead_types"] = lead_types
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
  "posted_within": "timeframe (e.g., week, month)",
  "lead_types": ["hiring", "freelancer", "agency"] — which kinds of leads the user wants. 
    "hiring" = companies hiring freelancers/contractors (hiring posts)
    "freelancer" = people looking FOR freelancers ("need a freelancer")
    "agency" = people looking FOR agencies ("looking for an X agency")
    If the user picked options, extract from their answer. If the user said they are an agency/company, default to ["agency"]. If freelancer, default to ["freelancer"]. If "all" or unspecified, use null.
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
        niche = context.get("niche") or ""
        roles = context.get("roles") or ""
        location = context.get("location") or ""
        try:
            count = min(int(context.get("count") or 20), 50)
        except (TypeError, ValueError):
            count = 20
        lead_types = context.get("lead_types") or []

        # Build search queries from context
        queries = self._build_queries(niche, roles, location, lead_types)
        logger.info(f"[HyperAgent] Queries: {queries}")

        key = self._get_harvest_key()
        max_posts = count * 3  # Get 3x to have enough after qualification filtering

        payload = {
            "searchQueries": queries[:8],
            "maxPosts": min(max_posts, 80),
            "postedLimit": str(context.get("posted_within") or "month"),
            "sortBy": "date",
            "timeoutSeconds": 540,
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

    def _build_queries(self, niche: str, roles: str, location: str, lead_types: list[str] | None = None) -> list[str]:
        """Build targeted LinkedIn search queries using BUYER-INTENT phrases.

        Mirrors the search section's approach: real buying intent rarely looks
        like "I need X" — it looks like "looking for a freelance web developer",
        "hiring a designer for our project", "website developer required".

        lead_types (optional) restricts query phrasing:
          ["agency"]      → "looking for an X agency", "recommend an X agency"
          ["freelancer"]  → "looking for a freelance X"
          ["hiring"]      → "hiring X", "we are hiring X"
        """
        queries = []
        seen: set[str] = set()

        def _add(q: str) -> None:
            q = " ".join(q.split())
            key = q.lower().strip('"')
            if key and key not in seen and len(queries) < 12:
                seen.add(key)
                queries.append(q)

        lead_types = lead_types or []
        want_hiring = (not lead_types) or "hiring" in lead_types
        want_freelancer = (not lead_types) or "freelancer" in lead_types
        want_agency = (not lead_types) or "agency" in lead_types

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

        # AGENCY-seekers first (highest value: people asking FOR an agency)
        if want_agency:
            for role in all_roles:
                _add(f"looking for an {role} agency")
                _add(f"recommend an {role} agency")
                _add(f"need an {role} agency")
                _add(f"looking for {role} agency")
                _add(f"best {role} agency")
            for n in niche_terms:
                _add(f"looking for an {n} agency")
                _add(f"recommend a good {n} agency")

        # FREELANCER-seekers
        if want_freelancer:
            for role in all_roles:
                _add(f"looking for a freelance {role}")
                _add(f"looking for freelance {role}")
                _add(f"need a freelance {role}")
                _add(f"freelance {role} needed")

        # HIRING posts
        if want_hiring:
            for role in all_roles:
                _add(f"hiring {role}")
                _add(f"need a {role} for our")
                _add(f"looking for {role} for our")
                _add(f"we are hiring {role}")

        # Generic niche-level intent phrases
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

        context = {k: ("" if v is None else v) for k, v in context.items()}
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
                "post_url": _extract_post_url(item),
                "profile_picture_url": self._extract_avatar(author),
                "post_content": post_content[:200],
                "engagement": {
                    "likes": engagement.get("likes", 0),
                    "comments": engagement.get("comments", 0),
                },
            })

        # Relevance gate: posts SHOULD mention the service/niche keyword, but
        # never hard-drop everything — if too few posts match, keep the rest
        # and let the AI judge with service_match instead (avoids 0 results).
        niche = context.get("niche", "")
        roles = context.get("roles", "")
        relevance_kws: set[str] = set()
        for kw in (niche + "," + roles).split(","):
            kw = kw.strip().lower()
            if len(kw) >= 3:
                relevance_kws.add(kw)
        # Derived role keywords: "website development" -> "web developer" etc.
        if "development" in niche.lower():
            relevance_kws.add(niche.lower().replace("development", "developer").strip())
        if "design" in niche.lower():
            relevance_kws.add(niche.lower().replace("design", "designer").strip())
        # Also add role terms to relevance keywords
        for r in (roles or "").split(","):
            r = r.strip().lower()
            if len(r) >= 3:
                relevance_kws.add(r)

        if relevance_kws:
            authors_filtered = []
            for a in authors:
                text = ((a.get("post_content") or "") + " " + (a.get("headline") or "")).lower()
                if any(kw in text for kw in relevance_kws):
                    authors_filtered.append(a)
            logger.info(f"[HyperAgent] Relevance gate: {len(authors_filtered)}/{len(authors)} matched keywords")
            # Only hard-filter when we still have at least 2x requested count;
            # otherwise keep everyone and rely on AI service_match scoring.
            requested_count_hint = 20
            try:
                requested_count_hint = int(context.get("count") or 20)
            except (TypeError, ValueError):
                pass
            # When lead_types are used, be MORE lenient — queries already target
            # specific buyer-intent phrases, so keep more candidates.
            lead_types = context.get("lead_types") or []
            min_keep = max(requested_count_hint * 2, 10) if not lead_types else max(requested_count_hint, 5)
            if len(authors_filtered) >= min_keep:
                authors = authors_filtered
            else:
                logger.info(f"[HyperAgent] Relevance gate: only {len(authors_filtered)} matched, keeping all {len(authors)} to avoid 0 results")

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

        # Code-level SELLER gate: reject service PROVIDERS (freelancers,
        # agencies, studios selling their work). Only strong signals —
        # company names like "ABC Services LLC" alone must NOT reject a
        # genuine buyer, otherwise we return 0 results.
        SELLER_PROVIDER_HEADLINE = (
            "freelance", "freelancer", "digital agency", "web agency",
            "design agency", "seo agency", "marketing agency", "social media agency",
            "i help businesses", "i help companies", "we help businesses",
            "we help companies", "we build websites", "we build apps",
            "service provider",
        )
        SELLER_POST_MARKERS = (
            "i offer", "we offer", "i provide", "we provide", "my services",
            "our services", "dm me", "book a call", "open to work",
            "open for work", "available for hire", "available for work",
            "taking new clients", "need clients", "i specialize",
            "we specialize", "check out my", "portfolio", "case studies",
            "i'm a freelance", "im a freelance", "i am a freelance",
            "i am a web developer", "i am a designer", "my agency",
        )

        def _is_seller(q: dict) -> bool:
            headline = (q.get("headline") or "").lower()
            company = (q.get("company") or "").lower()
            post = (q.get("post_content") or "").lower()
            # Strong: post is clearly selling their own services
            if any(m in post for m in SELLER_POST_MARKERS):
                return True
            # Strong: headline explicitly claims to be a freelancer/provider
            # AND the post does not clearly ask to BUY the service
            if any(m in headline for m in SELLER_PROVIDER_HEADLINE):
                buying_hints = (
                    "looking for", "need a", "need help", "recommend",
                    "hiring", "anyone know", "looking to hire", "for our project",
                )
                if not any(h in post for h in buying_hints):
                    return True
            # Company name alone ("ABC Services LLC") is NEVER enough to reject.
            return False

        qualified = [q for q in qualified if not _is_seller(q)]
        logger.info(f"[HyperAgent] Seller gate kept {len(qualified)} non-provider leads")

        # Lead-type preference gate: if the user only wants certain kinds of
        # leads (hiring / freelancer-seekers / agency-seekers), filter here.
        # This fixes: an agency user should NEVER get hiring posts.
        lead_types = context.get("lead_types") or []
        if lead_types:
            want_hiring = "hiring" in lead_types
            want_freelancer = "freelancer" in lead_types
            want_agency = "agency" in lead_types

            def _type_ok(q: dict) -> bool:
                lt = (q.get("lead_type") or "").lower()
                if lt == "hiring":
                    return want_hiring
                if lt == "agency":
                    return want_agency
                # explicit_need / problem_awareness / research — seekers
                return want_freelancer or want_agency

            qualified = [q for q in qualified if _type_ok(q)]

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

        # Absolute last resort: if every gate combined still yields zero, return
        # the top candidates that passed country + relevance as research leads
        # so the user never sees an empty result for a valid query.
        if not qualified and authors:
            logger.warning(f"[HyperAgent] All gates produced 0 — falling back to {min(len(authors), requested_count)} top candidates")
            for author in authors[:min(len(authors), requested_count)]:
                author = dict(author)
                author["score"] = 40
                author["is_lead"] = True
                author["lead_type"] = "research"
                author["work_type"] = "unknown"
                author["evidence_strength"] = "moderate"
                author["reason"] = "Returned as research candidate after strict qualification found no buyers"
                author["outreach_angle"] = ""
                qualified.append(author)

        return qualified[:min(requested_count, 50)]

    def _ai_triage_batch(self, batch: list[dict], context: dict) -> list[dict]:
        """Cheap single-question screen for remaining authors (mirrors triage in
        linkedin_pipeline). Only genuine buyers with a requirement are kept."""
        triage_prompt = f"""You are a B2B lead triage specialist. TARGET SERVICE: {context.get('niche', '')}.

For each post below, decide ONE thing: is the AUTHOR a genuine BUYER of this service (hiring freelancers/agencies/contractors, asking for recommendations, or describing a project/requirement the service solves)?

REJECT (do NOT keep) if the author is:
- SELLING their own services — freelancers, agencies, studios, consultants promoting "I offer", "we help", "DM me", "portfolio", "I provide X", "my services"
- Their headline reads "Freelance X", "X Agency", "Founder of X Agency", "Consultant", "Solutions", "Studio" and the post does not explicitly request the service
- A job seeker looking for work for themselves
- A recruiter/staffing agency placing candidates for clients
- Sharing content/tips/thought leadership
- Hiring for full-time on-site roles
- Post is not English

We ONLY want REAL BUYERS: people/companies that NEED the service. When in doubt, REJECT — better to return fewer, higher-quality leads.

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
                # Filter: accept leads with score >= 25 and service_match >= 10
                # (matches the proven linkedin search pipeline quality gate)
                return [
                    l for l in leads
                    if l.get("is_lead", True)
                    and l.get("score", 0) >= 25
                    and l.get("service_match", 0) >= 10
                ]
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
        """Save qualified leads to the database (linkedin-search quality format)."""
        saved = 0
        for lead in leads:
            try:
                score = lead.get("score", 0)
                is_lead = lead.get("is_lead", True) if "is_lead" in lead else True
                if not is_lead or score < 25:
                    continue

                lead_category = "hot" if score >= 85 else "warm"

                # Map AI lead_type to post_type CHECK values
                ai_type = (lead.get("lead_type") or "").lower()
                if ai_type in ("explicit_need", "problem_awareness", "research"):
                    post_type = "buyer"
                elif ai_type == "hiring":
                    post_type = "hiring"
                elif ai_type == "agency":
                    post_type = "agency"
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
