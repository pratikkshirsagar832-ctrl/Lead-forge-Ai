"""
Hyperclients — Search Pipeline

Orchestrates the full search lifecycle:
  1. Initialize search row
   2. Run Google Maps scraper
  3. Parse + save leads
  4. Finalize counts
"""

import asyncio
import logging
import time
from datetime import date, datetime, timezone

from app.database import get_supabase_admin
from app.services.scraper_service import run_maps_scraper

logger = logging.getLogger(__name__)

_search_semaphore = asyncio.Semaphore(3)
_active_searches: dict[str, bool] = {}
MAX_SEARCH_TIME_SECONDS = 600
MAX_RESULTS = 25


def is_search_cancelled(search_id: str) -> bool:
    return _active_searches.get(search_id, False)


def cancel_search(search_id: str) -> None:
    _active_searches[search_id] = True


async def run_search_pipeline(
    search_id: str,
    user_id: str,
    niche: str,
    location: str,
) -> None:
    supabase = get_supabase_admin()
    start_time = time.time()
    _active_searches[search_id] = False

    try:
        async with _search_semaphore:
            await _update_search(supabase, search_id, {
                "status": "scraping",
                "progress_percent": 5,
                "message": f"Starting search...",
            })

            if is_search_cancelled(search_id):
                await _mark_cancelled(supabase, search_id)
                return

            await _run_maps_search(supabase, search_id, user_id, niche, location, start_time)

            await _finalize_search(supabase, search_id)

    except Exception as e:
        logger.error(f"[Pipeline:{search_id}] Unexpected error: {e}", exc_info=True)
        try:
            await _update_search(supabase, search_id, {
                "status": "failed", "message": "Search failed unexpectedly",
                "error_message": str(e),
            })
        except Exception as update_err:
            logger.error(f"[Pipeline:{search_id}] Failed to update search status after error: {update_err}")
    finally:
        _active_searches.pop(search_id, None)


async def load_more_maps_search(
    search_id: str,
    user_id: str,
    niche: str,
    location: str,
) -> int:
    """Load 10 more results for an existing search."""
    supabase = get_supabase_admin()
    query = f"{niche} in {location}"

    # Get already-saved business names to avoid duplicates
    existing = await asyncio.to_thread(
        lambda: supabase.table("leads")
        .select("business_name")
        .eq("search_id", search_id)
        .execute()
    )
    existing_names = set()
    for row in existing.data or []:
        name = (row.get("business_name") or "").strip().lower()
        if name:
            existing_names.add(name)

    try:
        raw_results = await run_maps_scraper(
            query=query,
            max_results=20,
            timeout_seconds=120,
            depth=2,
        )
    except Exception as e:
        logger.error(f"[Pipeline:{search_id}] Load more scraper failed: {e}")
        return 0

    # Filter out duplicates
    new_results = []
    for r in raw_results:
        name = (r.get("business_name") or "").strip().lower()
        if name and name not in existing_names:
            existing_names.add(name)
            new_results.append(r)
            if len(new_results) >= 10:
                break

    if not new_results:
        logger.info(f"[Pipeline:{search_id}] No new unique leads found for load-more")
        return 0

    lead_ids = await _save_maps_leads(supabase, search_id, user_id, new_results)
    logger.info(f"[Pipeline:{search_id}] Load-more saved {len(lead_ids)} new leads")

    # Update search totals
    await _finalize_search(supabase, search_id)
    return len(lead_ids)


async def _run_maps_search(
    supabase, search_id: str, user_id: str, niche: str, location: str, start_time: float
) -> None:
    query = f"{niche} in {location}"
    elapsed = time.time() - start_time
    remaining_timeout = max(60, int(MAX_SEARCH_TIME_SECONDS - elapsed - 60))

    await _update_search(supabase, search_id, {
        "progress_percent": 10,
        "message": f"Searching Google Maps for '{niche}' in {location}...",
    })

    try:
        raw_results = await run_maps_scraper(
            query=query,
            max_results=MAX_RESULTS,
            timeout_seconds=remaining_timeout,
            depth=3,
        )
    except Exception as e:
        logger.error(f"[Pipeline:{search_id}] Maps scraper failed: {e}")
        await _update_search(supabase, search_id, {
            "status": "failed", "message": "Scraper failed",
            "error_message": str(e), "progress_percent": 0,
        })
        return

    if is_search_cancelled(search_id):
        await _mark_cancelled(supabase, search_id)
        return

    if not raw_results:
        await _update_search(supabase, search_id, {
            "status": "completed", "progress_percent": 100,
            "message": "No results found. Try a different search.",
            "total_results": 0,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        return

    await _update_search(supabase, search_id, {
        "progress_percent": 40,
        "message": f"Found {len(raw_results)} businesses. Saving leads...",
    })

    lead_ids = await _save_maps_leads(supabase, search_id, user_id, raw_results)
    logger.info(f"[Pipeline:{search_id}] Saved {len(lead_ids)} maps leads")


async def _save_maps_leads(
    supabase, search_id: str, user_id: str, raw_results: list[dict]
) -> list[str]:
    # Check remaining leads limit before saving
    remaining_leads = 30  # default fallback
    try:
        rem_resp = await asyncio.to_thread(
            lambda: supabase.rpc("get_remaining_leads", {"p_user_id": user_id}).execute()
        )
        if rem_resp and rem_resp.data is not None:
            remaining_leads = rem_resp.data
    except Exception:
        # Try direct query as fallback
        try:
            sub_resp = supabase.table("user_subscriptions").select("plan_id").eq("user_id", user_id).order("created_at", desc=True).limit(1).execute()
            if sub_resp.data and len(sub_resp.data) > 0:
                plan_resp = supabase.table("plans").select("leads_per_day").eq("id", sub_resp.data[0].get("plan_id", "free")).execute()
                if plan_resp.data and len(plan_resp.data) > 0:
                    remaining_leads = plan_resp.data[0].get("leads_per_day", 30)
            usage_resp = supabase.table("daily_usage").select("leads_generated").eq("user_id", user_id).eq("date", date.today().isoformat()).execute()
            if usage_resp.data and len(usage_resp.data) > 0:
                remaining_leads = max(0, remaining_leads - (usage_resp.data[0].get("leads_generated", 0) or 0))
        except Exception:
            pass

    lead_ids = []
    for result in raw_results:
        if remaining_leads <= 0:
            logger.warning(f"[Pipeline:{search_id}] Daily leads limit reached. Skipping {len(raw_results) - len(lead_ids)} remaining results.")
            break
        try:
            has_website = bool(result.get("website_url"))
            lead_data = {
                "search_id": search_id,
                "user_id": user_id,
                "google_key": result.get("google_key", ""),
                "business_name": result.get("business_name", "Unknown"),
                "category": result.get("category", ""),
                "full_address": result.get("full_address", ""),
                "phone": result.get("phone", ""),
                "email_found": result.get("email_found", ""),
                "website_url": result.get("website_url", ""),
                "rating": result.get("rating"),
                "total_reviews": result.get("total_reviews", 0),
                "google_maps_link": result.get("google_maps_link", ""),
                "photos": result.get("photos", []),
                "business_hours": result.get("business_hours", {}),
                "description": result.get("description", ""),
                "lead_category": "warm" if has_website else "hot",
            }
            response = await asyncio.to_thread(
                lambda: supabase.rpc("save_lead", {"p_data": lead_data}).execute()
            )
            if response.data and len(response.data) > 0:
                lead_ids.append(response.data[0]["id"])
                remaining_leads -= 1  # decrement local counter after successful save
        except Exception as e:
            logger.error(f"Failed to save lead '{result.get('business_name', '?')}': {e}")
    return lead_ids


# ── FINALIZE ─────────────────────────────────────────────────────────

async def _finalize_search(supabase, search_id: str) -> None:
    try:
        all_leads = await asyncio.to_thread(
            lambda: supabase.table("leads")
            .select("lead_category")
            .eq("search_id", search_id)
            .execute()
        )
        leads_data = all_leads.data or []

        total = len(leads_data)
        hot = sum(1 for l in leads_data if l.get("lead_category") == "hot")
        warm = sum(1 for l in leads_data if l.get("lead_category") == "warm")

        await _update_search(supabase, search_id, {
            "status": "completed",
            "progress_percent": 100,
            "message": f"Found {total} leads: {hot} hot, {warm} warm",
            "total_results": total,
            "hot_leads": hot,
            "warm_leads": warm,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })

        logger.info(f"[Pipeline:{search_id}] Completed — {total} leads ({hot}H/{warm}W)")

    except Exception as e:
        logger.error(f"[Pipeline:{search_id}] Finalization failed: {e}")
        await _update_search(supabase, search_id, {
            "status": "completed",
            "progress_percent": 100,
            "message": "Search completed (finalization had issues)",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })


async def _mark_cancelled(supabase, search_id: str) -> None:
    await _update_search(supabase, search_id, {
        "status": "cancelled",
        "message": "Search cancelled by user",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    })
    logger.info(f"[Pipeline:{search_id}] Cancelled")


async def _update_search(supabase, search_id: str, data: dict) -> None:
    try:
        await asyncio.to_thread(
            lambda: supabase.table("searches").update(data).eq("id", search_id).execute()
        )
    except Exception as e:
        logger.error(f"[Pipeline:{search_id}] Failed to update search: {e}")
