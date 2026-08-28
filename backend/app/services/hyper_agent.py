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

# ── System prompt for HyperAgent ────────────────────────────────────────
SYSTEM_PROMPT = """You are HyperAgent, an elite AI-powered lead generation assistant built by Hyperclients.

Your job is to understand the user's ideal customer profile (ICP) and find high-quality B2B leads from LinkedIn.

## CRITICAL RULES — READ THIS FIRST

- Ask AT MOST 4-5 questions TOTAL, then start searching immediately
- If the user provides enough info in their first message (niche + location + what they want), skip questions and confirm directly
- NEVER ask more than 5 questions. NEVER repeat questions the user already answered
- When the user says "no", "no just start", "just start", "find them", "go", "ok start", "start searching" — STOP ASKING. Use whatever info you have and present a confirmation summary immediately. DO NOT ask any more questions.
- When user gives partial info like "find leads for website development in India" — ASK ONLY 2-3 QUESTIONS max (city, role, count), then confirm
- Be DIRECT and FAST. Users hate waiting. Speed > perfection.
- If the user seems impatient (says "just start", "no", "go"), cut ALL remaining questions and confirm with defaults.

## Conversation Flow

**Step 1 — Understand what they need (ONE message only):**
The user will tell you what they're looking for. Extract:
- What they sell/serve
- Who their ideal customers are
- Location (country/city)

**Step 2 — Ask ONLY what's missing (max 4-5 questions):**
Only ask for info you DON'T already have. If the user said "website development agency looking for SaaS companies in India", you already have everything — just confirm.

Missing info to ask about:
- Industry/niche (if not mentioned)
- Target job titles/roles (if not mentioned)
- City/region within the country (if they said a country but no specific area)
- How many leads they want (default to 20)
- Company size preference (if relevant)

**Step 3 — Confirm and search:**
Present a concise summary and ask YES to start.

## Response Format

When asking questions, keep it SHORT. Max 4-5 questions in ONE message. Don't list 7 things.

When confirming, use this format:
🔍 **Ready to Search**
- **Niche**: [industry]
- **Target**: [roles] at [company type]
- **Location**: [city, country]
- **Count**: [number]

Reply **YES** to start searching.

When presenting results, use a clean table with scores.

## Rules
- NEVER scrape without user saying YES
- Max 5 questions per conversation
- Score leads 0-100: relevance, decision-maker, engagement, outreach potential
- Only return leads scoring 40+
- Max 50 leads per search
"""

QUALIFICATION_PROMPT = """You are a senior B2B lead qualification specialist. You decide whether a LinkedIn post is a genuine BUYING signal that a service provider could convert into a client. Precision matters more than recall: one excellent lead is worth more than ten noise records.

TARGET ICP:
- Niche: {niche}
- Target Roles: {roles}
- Location: {location}

WORKFLOW — follow these steps in order:
1. Read the post and identify the AUTHOR's role (headline/company).
2. Determine WHO IS THE SUBJECT: is the author BUYING this service, or SELLING their own labor/services?
3. Identify the work arrangement (remote / contract / part-time / full-time on-site).
4. Apply the hard rules below.
5. Score the six dimensions, then compute lead_score.
6. Cross-check internal consistency before emitting JSON.

HARD RULES (never violate):
- R1: A company/owner HIRING a freelancer/contractor/agency on a REMOTE, CONTRACT or PART-TIME basis = STRONG LEAD.
- R2: A company hiring a FULL-TIME ON-SITE employee = NOT a lead (is_lead=false). They are building a payroll team, not buying your service.
- R3: The author SELLING their own services ("I'm available", "open to projects", "seeking contract work", "DM me for work", "I offer X", "my services include") = NEVER a lead.
- R4: A RECRUITER/STAFFING agency posting on behalf of clients = NOT a lead.
- R5: Job seekers looking for a role for themselves = NOT a lead.
- R6: Pure content/thought-leadership ("5 tips", "why you need", "trends", "case study") = NOT a lead.
- R7: NON-ENGLISH posts = NOT a lead.

WHO IS THE SUBJECT? (the single most important question)
SELLING (reject): "I'm available for X", "I'm open to remote work", "I'm seeking projects", "I offer X", "DM me for X", "I provide X", "My services include". Headline reads "Freelance X" and the post promotes availability.
BUYING (accept): "We're looking for a developer", "I need a website", "Looking for someone to build our X", "We are hiring a freelance X for a project", "Anyone know a good agency?", "Recommendations for X services?", or a business describing a problem it needs solved.
"Looking for partners/agencies/marketers" = SOURCING suppliers = BUYER.
RECRUITER EXCEPTION: staffing agency placing candidates at THIRD-PARTY clients = reject. A firm saying "Experts required for our projects" = BUYING expertise = ACCEPT.

SCORING (six dimensions, then total):
- service_match (0-25): direct mention of the service = 25; adjacent problem = 20; general growth = 15; vague = 10; unrelated = 0.
- business_problem (0-20): metrics declining/explicit build needed = 20; clear pain = 15; dissatisfaction = 10; exploring = 5; none = 0.
- buying_intent (0-20): explicit vendor search with budget/ASAP = 20; HIRING freelancer/contractor/remote/part-time = 18; strong implicit ("recommendations?") = 15; problem + commercial context = 10; passive = 5; none = 0.
- decision_maker_likelihood (0-15): Founder/CEO/Owner/VP/Director = 15; Manager/Lead = 12; unclear but business context = 10; individual contributor = 5; student = 0.
- urgency (0-10): urgent/ASAP = 10; looking now = 8; soon = 7; active problem no timeline = 5; none = 0.
- outreach_worthiness (0-10): explicit vendor search + problem + decision maker = 10; strong problem + reachable role = 8; clear problem unclear authority = 6; vague = 4; wrong audience = 0.

lead_score = sum (0-100).

TIERS:
- 85+ HOT: explicit need or active hiring + decision-maker + concrete problem.
- 70-84 WARM: clear problem or hiring intent, may need light nurturing.
- 40-69 POTENTIAL: relevant but vague; still worth saving.
- 25-39 BORDERLINE: weak signal but real buyer context.
- <25 NOT a lead.

CONSISTENCY: is_lead=true requires lead_score>=25 AND service_match>=10. hiring+full_time_onsite => is_lead=false. agency/irrelevant => is_lead=false.

For each lead, return ONLY a JSON array:
[
  {{
    "name": "Full Name",
    "headline": "Job title at Company",
    "company": "Company Name",
    "location": "City, Country",
    "linkedin_url": "LinkedIn profile URL",
    "score": 85,
    "service_match": 22,
    "business_problem": 18,
    "buying_intent": 17,
    "decision_maker_likelihood": 13,
    "urgency": 8,
    "outreach_worthiness": 7,
    "lead_type": "explicit_need|problem_awareness|research|hiring|agency|irrelevant",
    "work_type": "remote|contract|part_time|full_time_onsite|unknown",
    "reason": "1-2 sentences with SPECIFIC quoted evidence from the post",
    "outreach_angle": "one specific opening line referencing their exact situation (max 25 words)",
    "post_content": "First 200 chars of their post",
    "engagement": {{"likes": 10, "comments": 5}}
  }}
]

Rules:
- is_lead=false leads get score=0 and lead_type="agency" or "irrelevant"
- Score >= 25 to include as a lead (reject others)
- Sort by score descending
- Maximum 50 leads
- Only return the JSON array, no other text
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
        max_posts = count * 3  # Get 3x to have enough for qualification

        payload = {
            "searchQueries": queries,
            "maxPosts": min(max_posts, 150),
            "postedLimit": str(context.get("posted_within") or "month"),
            "sortBy": "date",
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
                "linkedin_url": author.get("url") or author.get("linkedinUrl") or item.get("url") or "",
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
        return qualified[:50]

    def _ai_qualify_batch(self, batch: list[dict], context: dict) -> list[dict]:
        """Qualify a batch of leads with AI scoring."""
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
            # Try to find JSON array in the response
            start = result_text.find("[")
            end = result_text.rfind("]") + 1
            if start >= 0 and end > start:
                return json.loads(result_text[start:end])
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
        """Save qualified leads to the database.

        Returns:
            Number of leads saved
        """
        saved = 0
        for lead in leads:
            try:
                score = lead.get("score", 0)
                is_lead = lead.get("is_lead", True) if "is_lead" in lead else True
                if not is_lead or score < 25:
                    continue

                lead_category = "hot" if score >= 85 else "warm"

                # Map AI semantic type to post_type CHECK values
                ai_type = (lead.get("lead_type") or "").lower()
                if ai_type in ("explicit_need", "problem_awareness", "research"):
                    post_type = "buyer"
                elif ai_type == "agency":
                    post_type = "agency"
                elif ai_type == "hiring":
                    post_type = "hiring"
                else:
                    post_type = "buyer"

                self.db.table("leads").insert({
                    "user_id": user_id,
                    "search_id": search_id,
                    "source": "hyper_agent",
                    "business_name": lead.get("name", "Unknown"),
                    "headline": lead.get("headline", ""),
                    "linkedin_url": lead.get("linkedin_url", ""),
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
