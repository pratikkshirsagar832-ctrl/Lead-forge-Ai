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
    enrich_profiles,
    fetch_profile_details,
    run_post_search,
    run_job_search,
    filter_jobs_by_work_type,
)

logger = logging.getLogger(__name__)

MAX_RESULTS_CAP = 50

# Concurrent OpenAI calls during AI qualification — big speedup for large
# candidate lists. Cap at 10 so we don't trip OpenAI rate limits.
AI_QUALIFY_CONCURRENCY = 10

# Profile enrichment bills per row on pay-per-event actors — cap it.
PROFILE_ENRICHMENT_CAP = 60

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


def process_items(items: list[dict], max_results: int) -> tuple[list[dict], int]:
    """Parse raw all-in-one post items into candidate lead records.

    NO keyword classification here — the LLM scores intent later.
    Keeps ONE post per author (strongest by engagement) so profile
    enrichment isn't wasted on duplicate rows.

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
        # Only keep leads from English-speaking / target markets.
        country_code, location_text = _get_author_location(author)
        if country_code:
            if country_code not in ALLOWED_COUNTRY_CODES:
                logger.info(f"[CountryFilter] skipped {author.get('name')} ({country_code} - {location_text[:40]})")
                skipped += 1
                continue
        else:
            # No country data: if scrapeforge fallback, keep (unknown); we can't filter.
            # If headline hints a blocked market, skip it.
            hint = (author.get("info") or author.get("headline") or "").lower()
            name_hint = (author.get("name") or "")
            if any(k in hint for k in ("bengaluru", "mumbai", "new delhi", "hyderabad", "pune", "india", "pakistan", "bangladesh", "manila", "lagos", "nairobi")):
                logger.info(f"[CountryFilter] skipped {author.get('name')} (region hint in headline)")
                skipped += 1
                continue
            # Company pages are fine (prime targets). Individuals with South-Asian
            # names and no country data are most likely from blocked markets.
            if "/company/" not in author_url and _looks_south_asian(name_hint):
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
            # harvestapi: item.linkedinUrl; scrapeforge: item.url
            "post_url": item.get("url") or item.get("linkedinUrl") or "",
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
        logger.info(f"[AI Qualify DEBUG] {full_name} -> is_lead={result.get('is_lead')}, score={result.get('lead_score')}, type={result.get('lead_type')}, work={work_type}, reason={result.get('reason')[:100]}")

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
) -> None:
    supabase = get_supabase_admin()
    max_results = max(1, min(max_results, MAX_RESULTS_CAP))
    if lead_types is None:
        lead_types = ["buyer", "agency", "hiring"]

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

        # LOOP SYSTEM: keep searching with rotating query variants until we
        # collect AT LEAST the requested number of leads. Rounds scale with
        # the requested count so a bigger request searches harder:
        #   10 leads -> 10 rounds (one per lead) capped at 24.
        MAX_ITERATIONS = min(max(max_results, 3), 24)
        iteration = 0
        seen_post_urls: set[str] = set()

        while len(all_leads) < max_results and iteration < MAX_ITERATIONS:
            iteration += 1

            # Rotate query sets each iteration to find NEW leads (cycles 1-8).
            if iteration == 1:
                phrases = build_boolean_query(query)
            else:
                variant = ((iteration - 1) % 7) + 2  # 2,3,4,5,6,7,8 then repeat
                phrases = build_boolean_query_variant(query, variant)

            # Fetch scales with the remaining need — the more leads we still
            # need, the more posts this round tries to collect.
            remaining = max_results - len(all_leads)
            fetch_target = min(max(remaining * 15, 100), 400)
            logger.info(f"[LinkedInPipeline:{search_id}] Iteration {iteration}/{MAX_ITERATIONS} Queries: {phrases} (fetch {fetch_target})")

            await _update_search(supabase, search_id, {
                "progress_percent": min(15 + iteration * 4, 45),
                "message": f"Searching LinkedIn posts for '{query}' (round {iteration}/{MAX_ITERATIONS})...",
            })

            try:
                items = await asyncio.to_thread(run_post_search, phrases, fetch_target)
            except Exception as e:
                logger.error(f"[LinkedInPipeline:{search_id}] Iteration {iteration} post-search failed: {e}")
                # Key failover already tried all keys; if still failing, stop.
                if iteration == 1:
                    raise
                break
            raw_count = len(items)
            logger.info(f"[LinkedInPipeline:{search_id}] Iteration {iteration} returned {raw_count} raw posts")

            # Skip posts already seen in earlier iterations.
            # harvestapi uses id/linkedinUrl; scrapeforge uses postId/url.
            def _pid(it):
                return it.get("postId") or it.get("id") or it.get("url") or it.get("linkedinUrl")

            fresh = [it for it in items if _pid(it) not in seen_post_urls]
            for it in items:
                pid = _pid(it)
                if pid:
                    seen_post_urls.add(pid)
            logger.info(f"[LinkedInPipeline:{search_id}] Fresh posts this round: {len(fresh)} (of {raw_count})")

            leads, skipped = process_items(fresh, max_results * 3)
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
                "progress_percent": min(45 + iteration * 4, 60),
                "message": f"Found {raw_count} posts this round. AI qualifying...",
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

            logger.info(f"[LinkedInPipeline:{search_id}] Round {iteration}: +{len(new_leads)} qualified leads (total: {len(all_leads)}/{max_results})")

            # Keep looping until the requested count is met — each round uses
            # a different query angle, so more rounds = more chances.
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

            for job_query in job_queries:
                try:
                    jobs = await asyncio.to_thread(
                        run_job_search,
                        query=job_query,
                        location="United States",
                        time_range="7d",
                        max_jobs=min(max_results * 2, 40),
                    )
                    logger.info(f"[LinkedInPipeline:{search_id}] Job search '{job_query}' returned {len(jobs)} jobs")

                    # Filter for remote/part-time/contract only
                    filtered_jobs = filter_jobs_by_work_type(jobs, ["Remote", "Part-time", "Contract"])
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

                except Exception as e:
                    logger.error(f"[LinkedInPipeline:{search_id}] Job search error for '{job_query}': {e}")
                    continue

        # Trim to max_results
        if len(all_leads) > max_results:
            all_leads = all_leads[:max_results]

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
    try:
        resp = await asyncio.to_thread(
            lambda: supabase.rpc("get_remaining_leads", {"p_user_id": user_id}).execute()
        )
        if resp and resp.data is not None:
            return int(resp.data)
    except Exception:
        pass
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