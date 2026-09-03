"""
Hyperclients — HyperAgent Memory + Smart Query Brain

The agent keeps an up-to-date memory of every service it has ever searched:
  * It learns POWERFUL LinkedIn search queries per (service, lead_type, country)
    using DeepSeek V4 Flash (not just a static template), then stores them in the
    `agent_services` table.
  * On a repeat search it reuses + diversifies the learned queries, so the agent
    gets better over time instead of starting from scratch.
  * It surfaces cookie health so the UI can re-prompt the user when the LinkedIn
    session expires.
  * It drives the conversational flow (cookies -> service -> lead type -> country
    -> count), answering one question at a time.

Everything here is deterministic and cheap: query generation is one DeepSeek call,
the rest is DB reads/writes. No browser is involved.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

from app.database import get_supabase_admin
from app.config import get_settings

# The lead types we understand, in the order the agent asks about them.
LEAD_TYPES = ["freelancer_needed", "hiring", "agency_wanted"]
LEAD_TYPE_LABELS = {
    "freelancer_needed": "Freelancer needed (a company looking for an independent contractor)",
    "hiring": "Hiring (a company posting a job / recruiting for a role)",
    "agency_wanted": "Agency wanted (a company seeking an agency partner)",
}

# ✍️ Powerful query-generation prompt (the "prime agent" brain for discovery).
# DeepSeek writes high-intent LinkedIn search phrases that actually surface posts
# where someone is asking for / hiring / seeking the service.
QUERY_GEN_PROMPT = """You are an elite LinkedIn lead-discovery strategist for a B2B service business.

TASK: Write {n} powerful, natural LinkedIn SEARCH queries that will surface posts where
the author is ACTIVELY seeking the service below — NOT posts from people selling that service.

SERVICE: {service}
LEAD INTENT: {lead_type_hint}
COUNTRY BIAS: {country}

RULES:
- Write queries as phrases a real buyer would type into LinkedIn search, e.g.
  "looking for a web development agency", "need a video editor for our brand",
  "hiring a react developer", "recommend a good seo agency".
- MUST match the lead intent exactly.
  - freelancer_needed: buyer wants an independent freelancer. Use words like
    "freelance", "looking for someone", "need a freelancer", "independent".
    NEVER "agency", NEVER "we offer/we help".
  - hiring: company is hiring for a role. Use "hiring", "we're hiring", "open
    position", "looking for a <Role>", "join our team". Avoid "agency"/"freelance".
  - agency_wanted: company wants an agency. Use "agency", "looking for an X agency",
    "need an X agency", "recommend a X agency". NEVER "freelance".
- Add the country when given (append the country name to some queries so results
  lean toward it).
- Each query must be a natural, real-world phrase a business person would post.
- Vary the phrasing; no duplicates.
- Output ONLY a JSON array of strings, e.g. ["query 1", "query 2", ...].
"""


def _deepseek_client() -> Any:
    """Return a DeepSeek OpenAI-compatible client, or raise if unconfigured."""
    from openai import OpenAI
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY not configured")
    return OpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)


async def _generate_queries(service: str, lead_type: str, country: str, count: int = 10) -> list[str]:
    """Ask DeepSeek for powerful, intent-matched LinkedIn search queries."""
    from openai import OpenAI
    settings = get_settings()
    client = _deepseek_client()
    prompt = QUERY_GEN_PROMPT.format(
        n=count,
        service=service,
        lead_type_hint=LEAD_TYPE_LABELS.get(lead_type, lead_type),
        country=country or "Any (global)",
    )
    try:
        resp = client.chat.completions.create(
            model=settings.deepseek_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1200,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or ""
        data = json.loads(content)
        if isinstance(data, dict):
            data = data.get("queries", data.get("results", []))
        if not isinstance(data, list):
            return []
        return [str(q).strip() for q in data if str(q).strip()][:count]
    except Exception as exc:  # noqa: BLE001
        logger.warning("HyperAgent query generation failed (falling back to templates): %s", exc)
        return []


def _fallback_queries(service: str, lead_type: str, country: str, count: int = 8) -> list[str]:
    """Deterministic fallback so the agent still works offline / when DeepSeek
    is rate-limited. Mirrors the query intent isolation in linkedin_pipeline."""
    from app.services.linkedin_pipeline import generate_queries
    codes = set()
    if country:
        from app.services.linkedin_pipeline import parse_country_request
        codes, _ = parse_country_request(country)
    return generate_queries(lead_type, service, codes, 0, count)


async def get_or_learn_queries(user_id: str, service: str, lead_type: str, country: str) -> list[str]:
    """Return learned queries for (service, lead_type, country), learning + storing
    new powerful queries if this combination was never searched before.

    The agent stays up-to-date: a brand-new service gets fresh DeepSeek queries
    captured to `agent_services`; a repeat service reuses the learned set so the
    next run is faster and consistent.
    """
    supabase = get_supabase_admin()
    service_norm = (service or "").strip().lower()
    lead_norm = (lead_type or "freelancer_needed").strip().lower()

    row = _fetch_memory(supabase, user_id, service_norm, lead_norm, (country or "").strip().lower())
    if row and row.get("queries"):
        _bump_used(supabase, row.get("id"))
        return row["queries"]

    # Learn: generate powerful queries (DeepSeek), fallback to templates.
    queries = await _generate_queries(service_norm, lead_norm, country, 10)
    if not queries:
        queries = _fallback_queries(service_norm, lead_norm, country, 8)
    _save_memory(supabase, user_id, service_norm, lead_norm, (country or "").strip().lower(), queries)
    return queries


def _fetch_memory(supabase, user_id, service: str, lead_type: str, country: str) -> dict | None:
    try:
        resp = (
            supabase.table("agent_services")
            .select("*")
            .eq("user_id", user_id)
            .eq("service", service)
            .eq("lead_type", lead_type)
            .eq("country", country)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if rows and rows[0].get("queries"):
            return rows[0]
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_services fetch failed: %s", exc)
    return None


def _save_memory(supabase, user_id: str, service: str, lead_type: str, country: str, queries: list[str]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    try:
        supabase.table("agent_services").upsert({
            "user_id": user_id, "service": service, "lead_type": lead_type, "country": country,
            "queries": queries, "used_count": 1, "last_used_at": now, "updated_at": now,
        }, on_conflict="user_id,service,lead_type,country").execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_services save failed: %s", exc)


def _bump_used(supabase, row_id: str) -> None:
    try:
        resp = supabase.table("agent_services").select("used_count").eq("id", row_id).limit(1).execute()
        cur = int((resp.data or [{}])[0].get("used_count", 0) or 0)
        supabase.table("agent_services").update({
            "used_count": cur + 1,
            "last_used_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", row_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.debug("agent_services used_count bump failed: %s", exc)


# ── Cookie health (so the UI re-prompts on expiry) ──────────────────────────
def cookie_status() -> dict:
    """Inspect the configured LinkedIn cookies: set? near expiry? empty?"""
    settings = get_settings()
    cookies_raw = settings.linkedin_cookies_json
    if not cookies_raw:
        return {"configured": False, "expired": False, "expires_at": None, "note": "No cookies set"}
    # Check whether the session cookie (li_at) is still in the future.
    try:
        data = json.loads(cookies_raw)
        cookies = data if isinstance(data, list) else (data or {}).get("cookies", [])
        expires_at = None
        for c in cookies:
            if c.get("name") == "li_at" and c.get("expirationDate"):
                ex = float(c["expirationDate"])
                if ex > 10_000_000_000:
                    ex = ex / 1000.0
                expires_at = datetime.fromtimestamp(ex, tz=timezone.utc).isoformat()
                break
        now = datetime.now(timezone.utc)
        expired = expires_at is not None and datetime.fromisoformat(expires_at) < now
        return {"configured": True, "expired": expired, "expires_at": expires_at,
                "note": "Session expired — re-export cookies" if expired else "Session valid"}
    except Exception:  # noqa: BLE001
        return {"configured": True, "expired": False, "expires_at": None, "note": "Could not parse cookie expiry"}


def has_cookies() -> bool:
    return bool(get_settings().linkedin_cookies_json)
