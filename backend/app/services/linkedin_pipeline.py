"""
Hyperclients — LinkedIn Intent-Lead Pipeline

Orchestrates a LinkedIn intent search:
  1. Build Boolean search query from user input
  2. Run Apify post-search actor
  3. Filter out recruiter/hiring posts, dedupe by author
  4. Save person leads to linkedin_leads
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
HIRING_SIGNALS = (
    "#hiring", "we are hiring", "we're hiring", "now hiring", "urgently hiring",
    "job opening", "job opportunity", "job vacancy", "open position", "positions available",
    "vacancy", "recruiting", "recruitment", "recruiter", "candidate", "candidates",
    "to join our", "to join us", "to join my", "join our team", "join my team",
    "join us at", "join our", "we are looking for", "we're looking for",
    "looking for talented", "looking for skilled", "looking for an experienced",
    "we need a", "we need an", "send your portfolio", "share your portfolio",
    "submit your resume", "apply now", "apply here", "apply via", "internship",
    "intern", "hiring a", "hiring an",
)


def build_boolean_query(user_query: str) -> str:
    """Turn a plain phrase into a LinkedIn Boolean query with quoted variants."""
    q = user_query.strip().strip('"')
    low = q.lower()
    if any(low.startswith(p) for p in ("i need", "i want", "i'm looking", "i am looking", "looking for", "need ")):
        patterns = [q]
    else:
        service = q
        patterns = [
            f"I need {service}",
            f"I need a {service}",
            f"I want {service}",
            f"looking for {service}",
            f"looking for a {service}",
            f"I'm looking for {service}",
        ]
    seen: set[str] = set()
    out: list[str] = []
    for p in patterns:
        p = " ".join(p.split())
        key = p.lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return " OR ".join(f'"{p}"' for p in out[:6])


def is_hiring_post(item: dict) -> bool:
    """True if the post is a recruiter post (poster wants to hire, not buy)."""
    author = item.get("author") or {}
    if author.get("hiring") is True:
        return True
    text = ((item.get("content") or "") + " " + (author.get("headline") or "")).lower()
    return any(signal in text for signal in HIRING_SIGNALS)


def _parse_posted_at(value) -> str | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
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


def process_items(items: list[dict], max_results: int) -> list[dict]:
    """Filter + dedupe raw actor items into lead records (max max_results)."""
    seen: set[str] = set()
    leads: list[dict] = []
    for item in items:
        author = item.get("author") or {}
        public_id = author.get("publicIdentifier") or ""
        if not public_id or public_id in seen:
            continue
        if is_hiring_post(item):
            continue
        seen.add(public_id)

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
            "raw_data": item,
        })
        if len(leads) >= max_results:
            break
    return leads


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
            "status": "running",
            "progress_percent": 5,
            "message": "Building search queries...",
        })

        boolean_query = build_boolean_query(query)
        fetch_target = min(max(max_results * FETCH_MULTIPLIER, max_results + 10), 100)
        logger.info(f"[LinkedInPipeline:{search_id}] Query: {boolean_query} (fetch {fetch_target})")

        await _update_search(supabase, search_id, {
            "progress_percent": 15,
            "message": f"Searching LinkedIn posts for '{query}'...",
        })

        items = await asyncio.to_thread(run_post_search, boolean_query, fetch_target)
        raw_count = len(items)
        logger.info(f"[LinkedInPipeline:{search_id}] Actor returned {raw_count} raw posts")

        await _update_search(supabase, search_id, {
            "progress_percent": 55,
            "message": f"Found {raw_count} posts. Filtering for buyers...",
        })

        leads = process_items(items, max_results)
        if not leads:
            await _update_search(supabase, search_id, {
                "status": "completed",
                "progress_percent": 100,
                "message": "No relevant leads found. Try different wording.",
                "total_results": 0,
                "emails_found": 0,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            logger.info(f"[LinkedInPipeline:{search_id}] No leads after filtering")
            return

        await _update_search(supabase, search_id, {
            "progress_percent": 65,
            "message": f"Saving {len(leads)} leads...",
        })

        lead_ids = await _save_leads(supabase, search_id, user_id, leads)

        emails_found = 0
        if enrich_emails and lead_ids:
            await _update_search(supabase, search_id, {
                "progress_percent": 80,
                "message": "Finding emails for your leads...",
            })
            emails_found = await _enrich_emails(supabase, search_id, user_id, leads, lead_ids)

        suffix = f", {emails_found} emails" if emails_found else ""
        await _update_search(supabase, search_id, {
            "status": "completed",
            "progress_percent": 100,
            "message": f"Found {len(lead_ids)} leads{suffix}",
            "total_results": len(lead_ids),
            "emails_found": emails_found,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"[LinkedInPipeline:{search_id}] Completed — {len(lead_ids)} leads, {emails_found} emails")

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
    lead_ids: list[str] = []
    for lead in leads:
        try:
            row = {
                "search_id": search_id,
                "user_id": user_id,
                **lead,
            }
            response = await asyncio.to_thread(
                lambda: supabase.table("linkedin_leads").upsert(row, on_conflict="user_id,linkedin_url").execute()
            )
            if response.data and len(response.data) > 0:
                lead_ids.append(response.data[0]["id"])
        except Exception as e:
            logger.error(f"[LinkedInPipeline:{search_id}] Failed to save lead '{lead.get('full_name', '?')}': {e}")
    return lead_ids


async def _enrich_emails(
    supabase, search_id: str, user_id: str, leads: list[dict], lead_ids: list[str]
) -> int:
    urls = []
    url_to_index = {}
    for idx, lead in enumerate(leads):
        url = (lead.get("linkedin_url") or "").strip()
        if url:
            urls.append(url)
            url_to_index[url] = idx
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
        identifier = ((lead.get("raw_data") or {}).get("author") or {}).get("publicIdentifier") or ""
        email = email_by_identifier.get(identifier)
        if not email:
            continue
        try:
            update_data = {"email": email}
            location = location_by_identifier.get(identifier)
            if location:
                update_data["location"] = location
            company = company_by_identifier.get(identifier)
            if company:
                update_data["company"] = company
            await asyncio.to_thread(
                lambda: supabase.table("linkedin_leads")
                .update(update_data)
                .eq("id", lead_ids[idx])
                .eq("user_id", user_id)
                .execute()
            )
            emails_found += 1
        except Exception as e:
            logger.warning(f"[LinkedInPipeline:{search_id}] Failed to attach email: {e}")
    return emails_found


async def _update_search(supabase, search_id: str, data: dict) -> None:
    try:
        await asyncio.to_thread(
            lambda: supabase.table("linkedin_searches").update(data).eq("id", search_id).execute()
        )
    except Exception as e:
        logger.error(f"[LinkedInPipeline:{search_id}] Failed to update search: {e}")