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

logger = logging.getLogger(__name__)

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
            "scrapeReactions": False,
            "postNestedReactions": False,
            "scrapeComments": False,
            "postNestedComments": False,
        }

        items = _run_with_key(HARVEST_POST_SEARCH_ACTOR, key, payload)
        logger.info(f"[HyperAgent] HarvestAPI returned {len(items)} items")
        return items

    def _build_queries(self, niche: str, roles: str, location: str) -> list[str]:
        """Build targeted LinkedIn search queries."""
        queries = []

        # Core queries combining role + niche
        if roles and niche:
            for role in roles.split(","):
                role = role.strip()
                if role:
                    queries.append(f'"{role}" "{niche}"')
                    queries.append(f'"{role}" {niche}')

        # Location-specific queries
        if location and niche:
            queries.append(f'"{niche}" "{location}"')
            if roles:
                primary_role = roles.split(",")[0].strip()
                queries.append(f'"{primary_role}" "{location}"')

        # Fallback
        if not queries:
            queries = [f'"{niche}"' if niche else "business development"]

        return queries[:8]  # Max 8 queries

    def qualify_leads(self, items: list[dict], context: dict) -> list[dict]:
        """Use AI to qualify and score scraped leads.

        Args:
            items: Raw LinkedIn items from HarvestAPI
            context: ICP context

        Returns:
            Qualified leads sorted by score
        """
        if not items:
            return []

        # Extract author info from items
        authors = []
        seen = set()
        for item in items:
            author = item.get("author") or item.get("profile") or {}
            name = author.get("name") or author.get("fullName") or ""
            if not name or name in seen:
                continue
            seen.add(name)

            post_content = item.get("content") or item.get("text") or item.get("postContent") or ""
            engagement = item.get("engagement") or {}

            authors.append({
                "name": name,
                "headline": author.get("info") or author.get("headline") or author.get("title") or "",
                "company": author.get("currentPosition", {}).get("companyName") if isinstance(author.get("currentPosition"), dict) else "",
                "location": self._extract_location(author),
                "linkedin_url": author.get("url") or author.get("linkedinUrl") or "",
                "post_url": item.get("postUrl") or item.get("url") or "",
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

        # Sort by score and return top leads
        qualified.sort(key=lambda x: x.get("score", 0), reverse=True)

        # If we have fewer than requested, accept remaining authors with
        # a minimum score of 30 as a fallback
        requested_count = context.get("count", 20)
        if len(qualified) < requested_count:
            qualified_urls = {l.get("linkedin_url", "").lower() for l in qualified}
            remaining = [
                a for a in authors
                if a.get("linkedin_url", "").lower() not in qualified_urls
                and a.get("linkedin_url")
            ]
            # Accept top remaining as "research" leads with score 30
            for author in remaining[:requested_count - len(qualified)]:
                author["score"] = 30
                author["is_lead"] = True
                author["lead_type"] = "research"
                author["work_type"] = "unknown"
                author["evidence_strength"] = "moderate"
                author["reason"] = "Accepted as fallback — matches niche criteria"
                author["outreach_angle"] = ""
                qualified.append(author)
            qualified.sort(key=lambda x: x.get("score", 0), reverse=True)

        return qualified[:max(requested_count, 50)]

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
