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

# Profile enrichment bills per row on pay-per-event actors — cap it.
PROFILE_ENRICHMENT_CAP = 60


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
    # "website development" -> "web developer", "website developer", "web designer"
    # "seo"                -> "seo expert", "seo specialist"
    # "graphic design"     -> "graphic designer"
    roles = {base}
    lowb = " " + low + " "
    if "development" in low:
        roles.add(base.replace("development", "developer").strip())
    if "design" in low:
        roles.add(base.replace("design", "designer").strip())
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

    phrases: list[str] = [base]
    for role in sorted(roles, key=len):
        role = " ".join(role.split())
        if not role or role == base:
            continue
        phrases.extend([
            f"looking for a freelance {role}",
            f"looking for freelance {role}",
            f"hiring {role}",
            f"need a {role} for our",
            f"{role} required for",
            f"freelance {role} for",
            f"need {role} for project",
            f"contract {role}",
            f"{role} needed",
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
        author_url = (author.get("url") or "").strip()
        content = (item.get("content") or "").strip()
        if not author_url or len(content) < 20:
            skipped += 1
            continue

        eng = item.get("engagement") or {}
        lead = {
            "full_name": author.get("name") or "",
            "headline": "",  # filled by profile enrichment
            "company": "",
            "location": "",
            "linkedin_url": author_url,
            "post_url": item.get("url") or "",
            "post_text": content[:3000],
            "posted_at": _parse_posted_at(item.get("postedAt") or item.get("postedTimestamp")),
            "engagement_likes": _int(eng.get("likes") if eng.get("likes") is not None else eng.get("reactions")),
            "engagement_comments": _int(eng.get("comments")),
            "profile_picture_url": _get_avatar(author),
            "connections_count": 0,
        }

        key = author_url.rstrip("/").lower()
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

        SYSTEM_PROMPT = """You are a senior B2B lead qualification specialist for an AI-powered lead-generation platform.

YOUR MISSION
Analyze LinkedIn posts and identify people/companies with COMMERCIAL INTENT to buy a service — including implicit intent (a business problem, pain point, or hiring need that a service provider could solve). You are NOT a content reviewer; you are a sales intelligence analyst.

THE ONE HARD RULE
We ONLY want leads tied to REMOTE, CONTRACT-BASIS, or PART-TIME work.
- A company hiring a freelancer/contractor/agency remotely or on a contract/project basis = STRONG LEAD.
- A company posting a full-time on-site job = REJECT (is_lead=false).
- If work type is ambiguous but the post is a project/hiring need, lean toward "contract" unless the post explicitly says full-time on-site.

WHAT IS A LEAD
- Explicit: "Looking for an SEO agency", "Need a website developer", "Hiring a designer for our project", "Anyone know a good marketing agency?"
- Implicit: "Our organic traffic dropped 40%", "We can't convert website visitors", "We're launching and need a brand identity", "Looking for someone to build our Shopify store"
- Hiring for freelance/contract/remote/part-time talent to do this work = a lead (they are BUYING the service).

WHAT IS NOT A LEAD
- People LOOKING FOR A JOB for themselves ("open to work", "seeking a role", "available for opportunities")
- Agencies/freelancers SELLING their services ("we offer", "our agency does", "DM for quote", "I provide")
- Recruiters hiring on behalf of clients (staffing agencies)
- Pure content/thought leadership ("5 tips", "why you need", trends, opinions, success stories)
- Students/learners ("learning", "course", "internship", "portfolio feedback")

SCORING PHILOSOPHY
- 85+ = HOT: explicit need/active hiring + decision-maker + concrete problem
- 70-84 = WARM: clear problem or hiring intent, may need light nurturing
- 40-69 = POTENTIAL: relevant but vague; still worth saving
- <40 = NOT a lead: content, job-seeking, selling, or unrelated

Always output valid JSON. Never include markdown, commentary, or text outside the JSON object."""

        prompt = f"""Analyze this LinkedIn post for a business offering: {query}

--- POST CONTENT ---
{post_text}

--- AUTHOR HEADLINE ---
{headline}

--- AUTHOR COMPANY ---
{company}

Evaluate the post and produce a JSON object with EXACTLY these fields:

1. is_lead (boolean): whether this is a genuine commercial opportunity.
2. lead_score (0-100): overall lead quality.
3. service_match (0-25): does this post relate to problems '{query}' solves?
   25 = directly mentions the service or its core problem
   20 = adjacent/related problem (e.g. "traffic dropped" for SEO, "need a website" for web dev)
   15 = general business growth/marketing problem
   10 = vague business challenge
   0 = unrelated or pure thought leadership
4. business_problem (0-20): concrete current business need?
   20 = specific metrics declining or explicit new build needed ("traffic -40%", "need a website", "redesign")
   15 = clear pain point ("struggling with", "failing to", "can't")
   10 = general dissatisfaction or improvement desire
   5 = exploring/researching
   0 = none stated
5. buying_intent (0-20): how close to buying/hiring?
   20 = explicit request for agency/vendor/freelancer, budget, ASAP
   18 = HIRING a freelancer/contractor/remote/part-time talent to DO the work
   15 = strong implicit ("recommendations?", "who can help?", "need an expert")
   10 = problem awareness + commercial context ("for my business", "for our startup")
   5 = passive ("anyone else experiencing?")
   0 = none
6. decision_maker_likelihood (0-15): can this person authorize spend?
   15 = Founder/CEO/Owner/VP/Director/Head of Marketing/Growth
   12 = Manager/Lead in relevant department
   10 = unclear seniority but business context suggests authority
   5 = individual contributor/freelancer
   0 = student, job seeker, no budget authority
7. urgency (0-10):
   10 = urgent/ASAP/this week/deadline
   8 = "looking now", "need this done", project starting
   7 = soon/this month/before launch
   5 = active problem, no timeline
   0 = none
8. outreach_worthiness (0-10): would personalized outreach likely get a reply?
   10 = explicit vendor search + concrete problem + decision maker
   8 = strong problem + commercial context + reachable role
   6 = clear problem but unclear authority
   4 = vague, needs nurturing
   0 = wrong audience
9. lead_type: exactly one of
   - "explicit_need" (explicit vendor search)
   - "problem_awareness" (implicit business problem)
   - "research" (exploring/comparing)
   - "hiring" (hiring freelancer/contractor/employee to do the work)
   - "agency" (someone selling this service)
   - "irrelevant" (content, job seeking, student, etc.)
10. work_type: exactly one of
   - "remote" (remote, WFH, anywhere, virtual)
   - "contract" (contract, freelance, project basis, consultant)
   - "part_time" (part-time, hourly, flexible hours)
   - "full_time_onsite" (full-time, on-site, office — ⛔ REJECT as lead)
   - "unknown" (not stated — default to "contract" if it is a hiring/project post)
11. reason (string): 1-2 sentences citing SPECIFIC evidence from the post/headline.
12. outreach_angle (string): one personalized, human-sounding opening message line for a sales rep to send this person — reference their specific situation, no fluff.

CRITICAL:
- If lead_type is "hiring" and work_type is "full_time_onsite" → is_lead MUST be false.
- Remote/contract/part-time hiring posts are HIGH-VALUE leads — score them accordingly (80+ if the service matches and the person is a decision-maker).
- If a post says "looking for a freelance X", "contract X", "project basis", "remote X" → work_type = "contract" or "remote", lead_type = "hiring", is_lead = true.

Return ONLY valid JSON, nothing else."""

        try:
            resp = await asyncio.to_thread(
                lambda: client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.0,
                    max_tokens=700,
                    response_format={"type": "json_object"}
                )
            )
            result = json.loads(resp.choices[0].message.content)
            work_type = (result.get("work_type") or "unknown").lower()
            is_hiring = result.get("lead_type") == "hiring"
            # HARD RULE: only remote / contract / part-time hiring leads
            if is_hiring and work_type == "full_time_onsite":
                logger.info(f"[AI Qualify] FILTERED OUT {full_name} - on-site/full-time job, not remote/contract/part-time")
                continue
            logger.info(f"[AI Qualify DEBUG] {full_name} -> is_lead={result.get('is_lead')}, score={result.get('lead_score')}, type={result.get('lead_type')}, work={work_type}, reason={result.get('reason')[:100]}")

            if result.get("is_lead") and result.get("lead_score", 0) >= 40:
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
                qualified.append(lead)
                logger.info(f"[AI Qualify] KEPT {full_name} (score: {result.get('lead_score')}, type: {result.get('lead_type')}, work: {work_type})")
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

        # Broad discovery phrases — combined into one boolean OR search
        phrases = build_boolean_query(query)
        fetch_target = min(max(max_results * 8, 100), 300)
        logger.info(f"[LinkedInPipeline:{search_id}] Queries: {phrases} (fetch {fetch_target})")

        await _update_search(supabase, search_id, {
            "progress_percent": 15,
            "message": f"Searching LinkedIn posts for '{query}'...",
        })

        items = await asyncio.to_thread(run_post_search, phrases, fetch_target)
        raw_count = len(items)
        logger.info(f"[LinkedInPipeline:{search_id}] Actor returned {raw_count} raw posts")

        await _update_search(supabase, search_id, {
            "progress_percent": 35,
            "message": f"Found {raw_count} posts. Enriching author profiles...",
        })

        leads, skipped = process_items(items, max_results * 3)
        all_skipped += skipped
        logger.info(f"[LinkedInPipeline:{search_id}] Candidates after parsing: {len(leads)} (skipped {skipped})")

        # Enrich authors via profile-detail mode: headline/company/location.
        # Without headlines the AI cannot tell buyers from sellers/seekers.
        if leads:
            enrich_urls = [l["linkedin_url"] for l in leads[:PROFILE_ENRICHMENT_CAP]]
            try:
                profiles = await asyncio.to_thread(fetch_profile_details, enrich_urls, "basic")
                by_url = {(p.get("url") or "").rstrip("/").lower(): p for p in profiles if isinstance(p, dict)}
                enriched = 0
                for lead in leads:
                    p = by_url.get((lead.get("linkedin_url") or "").rstrip("/").lower())
                    if not p:
                        continue
                    lead["headline"] = (p.get("headline") or "")[:500]
                    lead["company"] = _company_from_profile(p)
                    lead["location"] = _location_from_profile(p)
                    lead["connections_count"] = p.get("connectionsCount") or 0
                    enriched += 1
                logger.info(f"[LinkedInPipeline:{search_id}] Profile enrichment: {enriched}/{len(enrich_urls)}")
            except Exception as e:
                logger.warning(f"[LinkedInPipeline:{search_id}] Profile enrichment failed (continuing without): {e}")

        await _update_search(supabase, search_id, {
            "progress_percent": 50,
            "message": f"Found {raw_count} posts. AI qualifying...",
        })

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
        # Map old lead_types to new AI lead_type values
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
        existing_urls = {l.get("linkedin_url") for l in all_leads if l.get("linkedin_url")}
        new_leads = [l for l in leads if l.get("linkedin_url") not in existing_urls]
        all_leads.extend(new_leads)

        logger.info(f"[LinkedInPipeline:{search_id}] Found {len(new_leads)} qualified leads from posts (total: {len(all_leads)})")

        # ALSO search for hiring leads via LinkedIn Job Scraper if "hiring" in lead_types
        if "hiring" in lead_types:
            await _update_search(supabase, search_id, {
                "progress_percent": 55,
                "message": f"Searching LinkedIn jobs for '{query}' (remote/contract/part-time US/Europe)...",
            })

            # Cap to 2 queries — each job-actor run can take minutes
            job_queries = get_job_queries_for_niche(query)[:2]
            logger.info(f"[LinkedInPipeline:{search_id}] Job queries: {job_queries}")

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
                        job_lead = {
                            "full_name": job.get("company") or "Unknown Company",
                            "headline": f"{job.get('title', '')} at {job.get('company', '')}",
                            "company": job.get("company", ""),
                            "location": job.get("location", ""),
                            "linkedin_url": job.get("companyUrl", ""),
                            "post_url": job.get("jobUrl", ""),
                            "post_text": job.get("descriptionText", "")[:3000],
                            "posted_at": job.get("postedAt"),
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