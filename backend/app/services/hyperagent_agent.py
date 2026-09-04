"""
Hyperclients — HyperAgent Autonomous Browser Agent (prime-agent brain + browser-use hands)

This is the GENUINE agent path: instead of deterministic CSS/JS probes, we give the
browser-use `Agent` a strong LinkedIn-specific SYSTEM PROMPT and let the DeepSeek
LLM (the "prime agent" brain) reason, navigate, scroll, click and extract on its own,
using browser-use (Chromium) as its hands.

This produces much higher-quality extraction and can adapt to LinkedIn's changing
DOM. The extracted raw items feed the SAME exact-count qualification engine
(linkedin_pipeline) — deterministic country gate, seller/job-seeker rejection,
canonical acceptance, DeepSeek re-classification, never-pad.

The system prompt is the heart of it. It makes the agent a precision LinkedIn
buyer-intent hunter, NOT a generic browser bot.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════
# PRIME-AGENT SYSTEM PROMPT (LinkedIn lead hunting)
# ══════════════════════════════════════════════════════════════════════════
LINKEDIN_AGENT_SYSTEM_PROMPT = """You are HYPERAGENT, an elite LinkedIn B2B lead-hunting specialist.

You are autonomous. You use your browser tools to navigate LinkedIn, search for posts,
scroll to load results, read the actual content, and extract GENUINE buyer-intent leads.
Do not stop until you have extracted the requested number of high-quality leads.
You think, try, adapt and improve as you work — never give up early.

MISSION
Find LinkedIn posts where the AUTHOR is ACTIVELY SEEKING to BUY / HIRE / OUTSOURCE the
requested service — NOT posts where people are SELLING that service. The author is your
LEAD and you must capture: author name, author profile URL, and the post text.

LEAD TYPES (know the difference — this is critical)
- freelancer_needed (buyer): a company wants an INDEPENDENT freelancer. Signals:
  "looking for a freelance X", "need someone to X", "seeking an independent X",
  "we need a X for one-off". NEVER a seller offering services.
- hiring: a company is HIRING a role. Signals: "we're hiring a X", "open position X",
  "join our team as X", "looking for a X to join". 
- agency_wanted: a company wants an AGENCY. Signals: "looking for an X agency",
  "need an X agency", "recommend an X agency", "seeking agency partner".

MUST REJECT (do NOT extract as leads) — these are sellers/opposite direction:
- Anyone OFFERING their own services ("I offer X", "DM me for X", "we specialize in X")
- Freelancers/agencies announcing they're available / booking clients
- Staffing/recruitment firms placing candidates ("we place talent", "apply with us")
- Talent marketplaces / platforms recruiting a freelancer pool
- Pure advice / "how to choose an agency" content
- Content creators seeking an agency to represent themselves
- Job seekers looking for work ("open to work", "seeking a role")

EXTRACTION RULES
- For each valid lead return exactly: author_name, profile_url (the /in/ link that
  always accompanies the post), post_url (the permalink to the specific post — the
  /feed/update/ or /posts/ link, or the activity URL), post_text (the post body only,
  NOT the headline/name).
- Returns a JSON ARRAY of objects: [{"author_name": "...", "profile_url": "https://www.linkedin.com/in/...", "post_url": "https://www.linkedin.com/feed/update/urn:li:activity:...", "post_text": "..."}, ...]
- Return ONLY the JSON array. No markdown, no prose, no code fences.
- Aim for the requested count. If fewer genuine leads exist, return fewer — NEVER
  pad with sellers or irrelevant posts.

BEHAVIOR
- Use the browser to open the given LinkedIn search URL.
- Scroll down several times (wait for lazy-loaded results) before extracting.
- Read post texts carefully; decide buyer-intent before extracting.
- If LinkedIn shows a login wall, state "LOGIN_WALL" in the final answer.
"""


def build_linkedin_task(service: str, lead_type: str, country: str, count: int, query: str) -> str:
    """Compose the concrete task the autonomous agent will execute."""
    lead_hint = {
        "freelancer_needed": "a company that wants to hire an INDEPENDENT FREELANCER",
        "hiring": "a company that is HIRING for a role",
        "agency_wanted": "a company that is looking for an AGENCY",
    }.get(lead_type, lead_type)

    loc = f" They should be in/near {country}." if country else ""

    return (
        f"Search LinkedIn for posts where {lead_hint} for \"{service}\" is requested.{loc}\n"
        f"Use this search URL: https://www.linkedin.com/search/results/content/?keywords={_q(query)}\n"
        f"Scroll to load results, then extract {count} genuine leads.\n"
        f"Return ONLY a JSON array of {{\"author_name\", \"profile_url\", \"post_url\", \"post_text\"}}."
    )


def _q(s: str) -> str:
    from urllib.parse import quote
    return quote((s or "").strip())


def parse_agent_result(final: str) -> list[dict]:
    """Parse the agent's final JSON-array answer into raw items for the engine."""
    if not final:
        return []
    text = (final or "").strip()
    # If the agent wrapped it in markdown/prose, pull out the JSON array.
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return []
    raw = text[start:end + 1]
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(data, list):
        return []
    items = []
    for obj in data:
        if not isinstance(obj, dict):
            continue
        author_name = (obj.get("author_name") or obj.get("author") or obj.get("name") or "").strip()
        profile_url = (obj.get("profile_url") or obj.get("author_url") or obj.get("url") or "").strip()
        post_url = (obj.get("post_url") or obj.get("postUrl") or obj.get("activity_url") or "").strip()
        post_text = (obj.get("post_text") or obj.get("content") or obj.get("text") or "").strip()
        if not profile_url or not post_text:
            continue
        items.append({
            "author": {"url": profile_url, "name": author_name, "info": ""},
            "content": post_text[:3000],
            "linkedinUrl": post_url or profile_url,
            "postUrl": post_url,
            "url": post_url or profile_url,
            "postedAt": None,
            "engagement": {},
        })
    return items
