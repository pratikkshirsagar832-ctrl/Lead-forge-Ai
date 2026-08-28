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

## Conversation Flow

1. **Understand the business**: Ask what the user sells/serves, who their ideal customers are
2. **Clarify the ICP**: Nail down:
   - Industry/niche (SaaS, E-commerce, Real Estate, etc.)
   - Job titles/roles (CTO, Marketing Director, Founder, etc.)
   - Location (country, city, state)
   - Company size (employees, revenue)
   - Lead count needed
3. **Confirm before scraping**: Present a clear summary and ask for confirmation
4. **Scrape & qualify**: Run the LinkedIn scrape, then present qualified leads

## Response Format

When asking questions, be conversational and specific. Give examples.

When confirming, use this format:
```
🔍 **Lead Search Summary**

- **Niche**: [industry]
- **Target Roles**: [job titles]
- **Location**: [city, country]
- **Company Size**: [range]
- **Leads Needed**: [count]
- **Posted Within**: [timeframe]

Ready to find these leads? Reply **YES** to start or **EDIT** to change.
```

When presenting results, use a clean table format with scores.

## Rules
- Always confirm before scraping (never scrape without user saying YES)
- Be specific about what you'll search for
- Score leads 0-100 based on: relevance, decision-maker likelihood, engagement quality
- Only return leads scoring 40+ (reject low quality)
- Max 50 leads per search (quality over quantity)
"""

QUALIFICATION_PROMPT = """You are a lead qualification expert. Score each lead from 0-100 based on:

1. **Relevance** (0-25): How well does this person match the target ICP?
2. **Decision Maker** (0-25): Are they a decision maker or influencer?
3. **Engagement Quality** (0-25): Is their post genuine engagement or spam?
4. **Outreach Potential** (0-25): How reachable and likely to respond?

Target ICP:
- Niche: {niche}
- Target Roles: {roles}
- Location: {location}

For each lead, return ONLY a JSON array with this format:
[
  {{
    "name": "Full Name",
    "headline": "Job title at Company",
    "company": "Company Name",
    "location": "City, Country",
    "linkedin_url": "LinkedIn profile URL",
    "score": 85,
    "reason": "Brief 1-line explanation of score",
    "post_content": "First 100 chars of their post",
    "engagement": {{"likes": 10, "comments": 5}}
  }}
]

Rules:
- Score >= 40 to include (reject others)
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
        """Check if user is confirming the search."""
        keywords = ["yes", "confirm", "start", "go", "do it", "proceed", "find them", "let's go", "search"]
        msg = message.lower().strip()
        return any(kw in msg for kw in keywords)

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
            "postedLimit": context.get("posted_within", "month"),
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
                lead_category = "hot" if score >= 80 else "warm"

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
                    "ai_confidence_score": score,
                    "ai_reason": lead.get("reason", ""),
                    "ai_pitch": lead.get("post_content", ""),
                    "post_text": lead.get("post_content", ""),
                    "user_status": "new",
                    "is_favorite": False,
                }).execute()
                saved += 1
            except Exception as e:
                logger.warning(f"[HyperAgent] Failed to save lead: {e}")

        return saved
