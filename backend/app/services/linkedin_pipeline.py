"""
Hyperclients — LinkedIn Intent-Lead Pipeline

Orchestrates a LinkedIn intent search that feeds the SAME searches/leads flow
as the Google Maps pipeline:

  1. Build intent Boolean query from user input (e.g. "ui-ux" → I need ui ux)
  2. Run Apify post-search actor
  3. Classify posts: buyer (needs the service) / agency (sells it) / hiring / job_seeker
  4. AI qualification: GPT-4o-mini validates genuine buyer intent
  5. Exclude job seekers, dedupe by author, save tagged leads (source='linkedin')
  6. Optional email enrichment via profile-scraper actor
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from app.config import get_settings
from app.database import get_supabase_admin
from app.services.apify_service import (
    ApifyError,
    enrich_profiles,
    run_post_search,
)

logger = logging.getLogger(__name__)

MAX_RESULTS_CAP = 50
FETCH_MULTIPLIER = 4
FETCH_MIN = 50

# ── Post classification signals ─────────────────────────────────────────

JOB_SEEKER_SIGNALS = (
    "open to work", "seeking a new role", "seeking employment", "seeking new opportunities",
    "looking for a new role", "looking for new opportunities", "seeking a role",
    "looking for a job", "looking for full-time", "looking for a position",
    "available for interviews", "appreciate any leads", "hiring managers",
    "recruiters to reach out", "dm me with opportunities", "seeking referrals",
    "i am open to", "i'm open to", "i am looking for a job",
)

HIRING_SIGNALS = (
    "#hiring", "we are hiring", "we're hiring", "now hiring", "urgently hiring",
    "job opening", "job opportunity", "job vacancy", "open position", "positions available",
    "vacancy", "recruiting", "recruitment", "recruiter", "candidates",
    "to join our", "to join us", "to join my", "join our team", "join my team",
    "join us at", "join our", "internship", "intern", "hiring a", "hiring an",
    "we need a", "we need an",
)

AGENCY_SIGNALS = (
    "we offer", "we provide", "we specialize", "our agency", "my agency",
    "our studio", "my studio", "we're an agency", "we are an agency",
    "we're a studio", "we are a studio", "our services", "we help businesses",
    "we have helped", "we deliver", "our team of", "free consultation",
    "book a call", "schedule a call", "contact us", "dm us", "dm me",
    "check out our work", "our portfolio", "starting at", "pricing",
    "packages", "we build", "we design", "we develop", "we do seo",
    "we do web", "we do design", "i offer", "i provide", "i specialize",
    "freelancer", "freelance", "i'm available for", "i am available for",
    "open for work", "looking for clients", "taking new clients",
    "accepting new clients", "hire me", "let's work together",
    "lets work together", "we can help you", "i can help you",
    "need clients", "available for hire", "quality work", "affordable pricing",
    "get a quote", "get free quote", "limited slots",
)

BUYER_SIGNALS = (
    "i need", "i want", "i'm looking for", "i am looking for", "looking for a",
    "looking for an", "need help with", "help with", "anyone recommend",
    "recommend me", "recommend a", "recommend an", "recommendations for",
    "suggestions for", "suggest me", "does anyone know", "anyone know a good",
    "who can help", "who does", "i'm searching for", "i am searching for",
    "looking to hire", "want to hire", "need to hire", "i need someone",
    "i want someone", "can you recommend", "please recommend", "looking for someone",
    "need a", "need an", "in need of",
)


def build_boolean_query(user_query: str) -> list[str]:
    """Turn a plain phrase/niche into a list of intent search phrases.

    The Apify actor takes `searchQueries` as an ARRAY of simple phrases —
    a single boolean OR string returns zero results. Returns up to 8 plain
    intent phrases for the actor to search.
    """
    q = user_query.strip().strip('"')
    q = " ".join(q.split())
    if not q:
        return ["I need help"]

    # Normalize common tokens
    q_norm = q.replace("ui-ux", "ui ux").replace("ui/ux", "ui ux").replace("website development", "website development")

    low = q.lower()
    # If the user already typed an intent phrase, keep it as the base pattern
    if any(low.startswith(p) for p in ("i need", "i want", "i'm looking", "i am looking", "looking for", "need ", "help with", "anyone", "recommend", "does anyone")):
        base = q_norm
        patterns = [base]
    else:
        base = q_norm
        patterns = [
            f"I need {base}",
            f"I need a {base}",
            f"I want {base}",
            f"I'm looking for {base}",
            f"looking for {base}",
            f"looking for a {base}",
            f"anyone recommend {base}",
            f"need help with {base}",
        ]

    seen: set[str] = set()
    out: list[str] = []
    for p in patterns:
        p = " ".join(p.split())
        key = p.lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out[:8]


def classify_post_type(item: dict) -> str:
    """Classify a post: buyer / agency / hiring / job_seeker."""
    author = item.get("author") or {}
    if author.get("hiring") is True:
        return "hiring"

    text = ((item.get("content") or "") + " " + (author.get("headline") or "")).lower()
    headline = (author.get("headline") or "").lower()

    # Job seeker: author headline/company usually shows current employer; "I'm a [role]" = seeker
    if any(signal in text for signal in JOB_SEEKER_SIGNALS):
        return "job_seeker"
    if "looking for a" in text and "role" in text:
        return "job_seeker"
    if " i'm a " in f" {text} " and any(s in text for s in ("looking for", "seeking", "opportunities", "role")):
        return "job_seeker"
    if " i am a " in f" {text} " and any(s in text for s in ("looking for", "seeking", "opportunities", "role")):
        return "job_seeker"

    if any(signal in text for signal in HIRING_SIGNALS):
        return "hiring"

    if any(signal in text for signal in AGENCY_SIGNALS):
        return "agency"

    if any(signal in headline for signal in ("seo", "web design", "web developer", "ui/ux", "ui ux", "designer", "developer", "freelance", "agency")):
        # Author's headline says they SELL the service → agency
        return "agency"

    if any(signal in text for signal in BUYER_SIGNALS):
        return "buyer"

    return "buyer"


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


def _get_engagement(item: dict) -> tuple[int, int]:
    eng = item.get("engagement") or {}
    likes = eng.get("likes") if isinstance(eng, dict) else None
    comments = eng.get("comments") if isinstance(eng, dict) else None
    if likes is None and isinstance(item.get("reactions"), list):
        likes = len(item["reactions"])
    if comments is None and isinstance(item.get("comments"), list):
        comments = len(item["comments"])
    try:
        likes = int(likes or 0)
    except (TypeError, ValueError):
        likes = 0
    try:
        comments = int(comments or 0)
    except (TypeError, ValueError):
        comments = 0
    return likes, comments


def _get_avatar(author: dict) -> str:
    avatar = author.get("avatar") or {}
    if isinstance(avatar, dict) and avatar.get("url"):
        return avatar["url"]
    picture = author.get("profilePicture") or {}
    if isinstance(picture, dict) and picture.get("url"):
        return picture["url"]
    if isinstance(picture, list) and picture:
        first = picture[0]
        if isinstance(first, dict) and first.get("url"):
            return first["url"]
    return ""


def _get_company(author: dict) -> str:
    positions = author.get("currentPosition") or []
    for pos in positions:
        if not isinstance(pos, dict):
            continue
        company = pos.get("companyName") or (pos.get("company") or {}).get("name")
        if company:
            return company
    return ""


def _get_location(author: dict) -> str:
    location = author.get("location") or {}
    if isinstance(location, dict):
        linkedin_text = location.get("linkedinText")
        if linkedin_text:
            return linkedin_text
        parsed = location.get("parsed") or {}
        if isinstance(parsed, dict) and parsed.get("text"):
            return parsed["text"]
    return ""


POST_TYPE_ORDER = {"buyer": 0, "agency": 1, "hiring": 2, "job_seeker": 3}


def process_items(items: list[dict], max_results: int) -> tuple[list[dict], int]:
    """Classify + dedupe raw actor items into lead records.

    Returns (leads, skipped_count). Job seekers are always skipped.
    Buyers are kept first, then agencies and hiring posts (all tagged).
    """
    seen: set[str] = set()
    leads: list[dict] = []
    skipped = 0
    for item in items:
        author = item.get("author") or {}
        public_id = author.get("publicIdentifier") or ""
        if not public_id or public_id in seen:
            skipped += 1
            continue
        seen.add(public_id)

        post_type = classify_post_type(item)
        if post_type == "job_seeker":
            skipped += 1
            continue

        likes, comments = _get_engagement(item)
        leads.append({
            "full_name": author.get("name") or "",
            "headline": (author.get("headline") or author.get("info") or "")[:500],
            "company": _get_company(author),
            "location": _get_location(author),
            "linkedin_url": author.get("linkedinUrl") or "",
            "post_url": item.get("linkedinUrl") or "",
            "post_text": (item.get("content") or "")[:2000],
            "posted_at": _parse_posted_at(item.get("postedAt")),
            "engagement_likes": likes,
            "engagement_comments": comments,
            "profile_picture_url": _get_avatar(author),
            "connections_count": author.get("connectionsCount") or 0,
            "post_type": post_type,
        })
        if len(leads) >= max_results:
            break

    leads.sort(key=lambda l: POST_TYPE_ORDER.get(l["post_type"], 9))
    return leads, skipped


async def qualify_leads_with_ai(leads: list[dict], query: str, client=None, lead_types=None) -> list[dict]:
    """Use GPT-5 to score commercial intent semantically (0-100). Catches implicit buying signals."""
    if client is None:
        settings = get_settings()
        if not settings.openai_api_key:
            logger.warning("OpenAI API key not configured, skipping AI qualification")
            return leads
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)

    qualified = []
    for lead in leads:
        post_text = lead.get("post_text", "")[:3000]
        headline = lead.get("headline", "")[:500]
        company = lead.get("company", "")[:200]
        full_name = lead.get("full_name", "?")

        prompt = f"""You are a senior B2B lead qualification specialist for a marketing agency offering '{query}' services.

Analyze this LinkedIn post for COMMERCIAL OPPORTUNITY — not just explicit "I need to buy" statements.

POST:
"{post_text}"

AUTHOR HEADLINE:
"{headline}"

COMPANY:
"{company}"

SCORING FRAMEWORK (0-100 each):

1. SERVICE_MATCH (0-25): Does the post relate to problems '{query}' solves?
   25 = Directly mentions the exact service or its core problem
   20 = Mentions adjacent/related problem (e.g., "traffic dropped" for SEO)
   15 = General business growth/marketing problem
   10 = Vague business challenge
   0 = Unrelated or pure thought leadership

2. BUSINESS_PROBLEM (0-20): Is there a concrete, current business problem?
   20 = Specific metrics declining (traffic -40%, conversions down, revenue drop)
   15 = Clear pain point described ("struggling with...", "failing to...")
   10 = General dissatisfaction or desire to improve
   5 = Exploring options, researching
   0 = No problem stated (tips, trends, opinions, success stories)

3. BUYING_INTENT (0-20): How close to purchasing/hiring?
   20 = Explicit: "Looking for agency", "Need to hire", "Budget $X", "ASAP"
   15 = Strong implicit: "Recommendations?", "Who can help?", "Need expert"
   10 = Problem awareness + commercial context: "For my business", "For our startup"
   5 = Passive interest: "Anyone else experiencing...?"
   0 = No commercial intent (learning, sharing, debating)

4. DECISION_MAKER_LIKELIHOOD (0-15): Can this person authorize/approve spend?
   15 = Founder/CEO/Owner/VP/Director/Head of Marketing/Growth
   12 = Manager/Lead in relevant dept
   10 = Unclear seniority but business context suggests authority
   5 = Individual contributor / freelancer
   0 = Student, job seeker, or clearly no budget authority

5. URGENCY (0-10): Time pressure?
   10 = "Urgent", "ASAP", "This week", "Immediately", "Deadline"
   7 = "Soon", "This month", "Q3", "Before launch"
   5 = No timeline but active problem
   0 = No urgency signals

6. OUTREACH_WORTHINESS (0-10): Would a personalized outreach likely get a reply?
   10 = Explicit vendor search + specific problem + decision maker
   8 = Strong problem + commercial context + reachable role
   6 = Clear problem but unclear authority/timeline
   4 = Vague interest, would need nurturing
   0 = Wrong audience (job seeker, student, competitor, pure content)

NEGATIVE SIGNALS (apply deductions):
- Job seeker: "open to work", "seeking role", "looking for job", "available for opportunities" → MINUS 50
- Agency/freelancer selling: "we offer", "our agency", "I provide", "book a call", "dm for quote", "freelancer available", "taking clients" → MINUS 50
- Recruiter hiring for clients: "hiring for client", "staffing", "executive search" → MINUS 50
- Generic content: "tips", "how to", "trends", "why you need", "5 ways to", thought leadership → MINUS 30
- Engagement bait: "agree?", "comment yes", "thoughts?", polls → MINUS 30
- Student/learning: "learning", "course", "certification", "internship" → MINUS 40

LEAD TYPE (choose ONE):
- explicit_need: "Looking for SEO agency", "Need to hire Shopify expert"
- problem_awareness: "Traffic dropped 40%", "Conversions plummeted", "Struggling with rankings"
- research: "Anyone else seeing traffic drops?", "Best tools for SEO?", "Comparing agencies"
- hiring: "We're hiring SEO manager", "Join our team as growth lead"
- agency: "We offer SEO", "Our agency specializes", "Freelancer available"
- irrelevant: None of the above

Reply with JSON ONLY:
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
  "reason": "Specific evidence from post/headline for the score",
  "outreach_angle": "One-sentence personalized opener for sales outreach"
}}"""

        try:
            resp = await asyncio.to_thread(
                lambda: client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a senior B2B lead qualification specialist. Score commercial intent semantically. Return only valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.0,
                    max_tokens=500,
                    response_format={"type": "json_object"}
                )
            )
            result = json.loads(resp.choices[0].message.content)
            logger.info(f"[AI Qualify DEBUG] {full_name} -> is_lead={result.get('is_lead')}, score={result.get('lead_score')}, type={result.get('lead_type')}, reason={result.get('reason')[:100]}")

            if result.get("is_lead") and result.get("lead_score", 0) >= 40:
                lead["ai_qualified"] = True
                lead["ai_score"] = result.get("lead_score")
                lead["lead_type"] = result.get("lead_type", "potential")
                lead["business_problem"] = result.get("business_problem", False)
                lead["service_match"] = result.get("service_match", False)
                lead["buying_intent"] = result.get("buying_intent", 0)
                lead["urgency"] = result.get("urgency", 0)
                lead["decision_maker_likelihood"] = result.get("decision_maker_likelihood", 0)
                lead["outreach_worthiness"] = result.get("outreach_worthiness", 0)
                lead["ai_reason"] = result.get("reason", "")
                lead["outreach_angle"] = result.get("outreach_angle", "")
                qualified.append(lead)
                logger.info(f"[AI Qualify] KEPT {full_name} (score: {result.get('lead_score')}, type: {result.get('lead_type')})")
            else:
                logger.info(f"[AI Qualify] FILTERED OUT {full_name} - score: {result.get('lead_score')}, type: {result.get('lead_type')}, reason: {result.get('reason')}")
        except Exception as e:
            logger.error(f"[AI Qualify] Error for {full_name}: {e}")
            # On error, be LENIENT - accept the lead
            qualified.append(lead)
            logger.info(f"[AI Qualify] ACCEPTED on error: {full_name}")

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

        # Use simple high-converting intent queries directly
        phrases = build_boolean_query(query)[:6]
        fetch_target = min(max(max_results * 8, 80), 200)
        logger.info(f"[LinkedInPipeline:{search_id}] Queries: {phrases} (fetch {fetch_target})")

        await _update_search(supabase, search_id, {
            "progress_percent": 15,
            "message": f"Searching LinkedIn posts for '{query}'...",
        })

        items = await asyncio.to_thread(run_post_search, phrases, fetch_target)
        raw_count = len(items)
        logger.info(f"[LinkedInPipeline:{search_id}] Actor returned {raw_count} raw posts")

        await _update_search(supabase, search_id, {
            "progress_percent": 50,
            "message": f"Found {raw_count} posts. AI qualifying...",
        })

        leads, skipped = process_items(items, max_results * 3)
        all_skipped += skipped

        # AI qualify with semantic scoring
        leads = await qualify_leads_with_ai(leads, query, openai_client, lead_types)

        # Rank by AI score (highest first)
        leads.sort(key=lambda x: x.get("ai_score", 0), reverse=True)

        # Dedupe by author (keep highest scoring post per author)
        best_by_author = {}
        for lead in leads:
            author_url = lead.get("linkedin_url")
            if not author_url:
                continue
            score = lead.get("ai_score", 0)
            if author_url not in best_by_author or score > best_by_author[author_url].get("ai_score", 0):
                best_by_author[author_url] = lead
        leads = list(best_by_author.values())
        leads.sort(key=lambda x: x.get("ai_score", 0), reverse=True)

        # Filter by requested types using lead_type
        if lead_types and lead_types != ["buyer", "agency", "hiring"]:
            leads = [l for l in leads if l.get("lead_type") in lead_types]

        # Add to all_leads and dedupe again
        existing_urls = {l.get("linkedin_url") for l in all_leads if l.get("linkedin_url")}
        new_leads = [l for l in leads if l.get("linkedin_url") not in existing_urls]
        all_leads.extend(new_leads)

        logger.info(f"[LinkedInPipeline:{search_id}] Found {len(new_leads)} qualified leads (total: {len(all_leads)})")

        # Trim to max_results
        if len(all_leads) > max_results:
            all_leads = all_leads[:max_results]

        # Count by lead_category based on ai_score
        hot = sum(1 for l in all_leads if l.get("ai_score", 0) >= 85)
        warm = sum(1 for l in all_leads if 70 <= l.get("ai_score", 0) < 85)
        potential = sum(1 for l in all_leads if 40 <= l.get("ai_score", 0) < 70)

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
            "message": f"Saving {len(all_leads)} qualified leads ({hot} hot, {warm} warm, {potential} potential)...",
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
        logger.info(f"[LinkedInPipeline:{search_id}] Completed — {saved} leads ({hot} hot, {warm} warm, {potential} potential), {emails_found} emails")

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
        elif ai_score >= 70:
            lead_category = "warm"
        else:
            lead_category = "potential"

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
            "lead_type": lead.get("lead_type") or "unknown",
            "linkedin_url": linkedin_url,
            "post_url": lead.get("post_url") or "",
            "post_text": lead.get("post_text") or "",
            "headline": lead.get("headline") or "",
            "profile_picture_url": lead.get("profile_picture_url") or "",
            "connections_count": lead.get("connections_count") or 0,
            "posted_at": lead.get("posted_at"),
            "ai_qualified": lead.get("ai_qualified", False),
            "ai_score": lead.get("ai_score"),
            "ai_reason": lead.get("ai_reason"),
            "outreach_angle": lead.get("outreach_angle"),
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
        location = _get_location(profile)
        if location:
            location_by_identifier[identifier] = location
        company = _get_company(profile)
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