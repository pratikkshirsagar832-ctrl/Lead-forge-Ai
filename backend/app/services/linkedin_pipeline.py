"""
Hyperclients — LinkedIn Intent-Lead Pipeline

Orchestrates a LinkedIn intent search that feeds the SAME searches/leads flow
as the Google Maps pipeline:

  1. Build intent Boolean query from user input (e.g. "ui-ux" → I need ui ux)
  2. Run Apify post-search actor
  3. Classify posts: buyer (needs the service) / agency (sells it) / hiring / job_seeker
  4. Exclude job seekers, dedupe by author, save tagged leads (source='linkedin')
  5. Optional email enrichment via profile-scraper actor
"""

import asyncio
import logging
from datetime import datetime, timezone

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


async def run_linkedin_pipeline(
    search_id: str,
    user_id: str,
    query: str,
    enrich_emails: bool,
    max_results: int,
) -> None:
    supabase = get_supabase_admin()
    max_results = max(1, min(max_results, MAX_RESULTS_CAP))

    try:
        await _update_search(supabase, search_id, {
            "status": "scraping",
            "progress_percent": 5,
            "message": "Building intent queries...",
        })

        phrases = build_boolean_query(query)[:4]
        fetch_target = min(max(max_results * FETCH_MULTIPLIER, FETCH_MIN), 100)
        logger.info(f"[LinkedInPipeline:{search_id}] Queries: {phrases} (fetch {fetch_target})")

        await _update_search(supabase, search_id, {
            "progress_percent": 15,
            "message": f"Searching LinkedIn posts for '{query}'...",
        })

        items = await asyncio.to_thread(run_post_search, phrases, fetch_target)
        raw_count = len(items)
        logger.info(f"[LinkedInPipeline:{search_id}] Actor returned {raw_count} raw posts")

        await _update_search(supabase, search_id, {
            "progress_percent": 55,
            "message": f"Found {raw_count} posts. Classifying buyers vs agencies...",
        })

        leads, skipped = process_items(items, max_results)
        buyers = sum(1 for l in leads if l["post_type"] == "buyer")

        if not leads:
            await _update_search(supabase, search_id, {
                "status": "completed",
                "progress_percent": 100,
                "message": "No relevant leads found. Try different wording.",
                "total_results": 0,
                "hot_leads": 0,
                "warm_leads": 0,
                "skipped": raw_count,
                "emails_found": 0,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            logger.info(f"[LinkedInPipeline:{search_id}] No leads after classification")
            return

        await _update_search(supabase, search_id, {
            "progress_percent": 65,
            "message": f"Saving {len(leads)} leads ({buyers} buyers)...",
        })

        lead_ids = await _save_leads(supabase, search_id, user_id, leads)

        emails_found = 0
        if enrich_emails and lead_ids:
            await _update_search(supabase, search_id, {
                "progress_percent": 80,
                "message": "Finding emails for your leads...",
            })
            emails_found = await _enrich_emails(supabase, search_id, user_id, leads, lead_ids)

        saved = len(lead_ids)
        total_skipped = max(0, raw_count - saved)
        suffix = f", {emails_found} emails" if emails_found else ""
        await _update_search(supabase, search_id, {
            "status": "completed",
            "progress_percent": 100,
            "message": f"Found {saved} leads{suffix}",
            "total_results": saved,
            "hot_leads": saved,
            "warm_leads": 0,
            "skipped": total_skipped,
            "emails_found": emails_found,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"[LinkedInPipeline:{search_id}] Completed — {saved} leads, {emails_found} emails")

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
            "lead_category": "hot",
            "post_type": lead.get("post_type") or "unknown",
            "linkedin_url": linkedin_url,
            "post_url": lead.get("post_url") or "",
            "post_text": lead.get("post_text") or "",
            "headline": lead.get("headline") or "",
            "profile_picture_url": lead.get("profile_picture_url") or "",
            "connections_count": lead.get("connections_count") or 0,
            "posted_at": lead.get("posted_at"),
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