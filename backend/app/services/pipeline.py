"""
LeadForge AI — Search Pipeline

Orchestrates the full search lifecycle:
  1. Initialize search row
  2. Run Google Maps scraper
  3. Parse + save leads
  4. Analyze websites
  5. Finalize counts
  
Uses asyncio.Semaphore for concurrency control.
Enforces 10-minute max search time with partial result save.
No automatic AI pitch generation.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone

from app.database import get_supabase_admin
from app.services.analyzer_service import analyze_website
from app.services.scraper_service import run_maps_scraper

logger = logging.getLogger(__name__)

# Concurrency control — max 3 searches at once
_search_semaphore = asyncio.Semaphore(3)

# Track active searches for cancellation
_active_searches: dict[str, bool] = {}  # search_id -> cancelled flag

MAX_SEARCH_TIME_SECONDS = 600  # 10 minutes
MAX_RESULTS = 50


def is_search_cancelled(search_id: str) -> bool:
    """Check if a search has been cancelled."""
    return _active_searches.get(search_id, False)


def cancel_search(search_id: str) -> None:
    """Mark a search as cancelled."""
    _active_searches[search_id] = True


async def run_search_pipeline(search_id: str, user_id: str, niche: str, location: str) -> None:
    """
    Main pipeline entry point. Run within FastAPI BackgroundTasks.
    
    Stages:
      1. Mark search as 'scraping'
      2. Run maps scraper
      3. Save leads to DB
      4. Analyze websites (with concurrency)
      5. Finalize counts
    """
    supabase = get_supabase_admin()
    start_time = time.time()
    _active_searches[search_id] = False  # Not cancelled

    try:
        async with _search_semaphore:
            # ── Stage 1: Initialize ───────────────────────────
            await _update_search(supabase, search_id, {
                "status": "scraping",
                "progress_percent": 5,
                "message": "Starting Google Maps search...",
            })

            if is_search_cancelled(search_id):
                await _mark_cancelled(supabase, search_id)
                return

            # ── Stage 2: Run Scraper ──────────────────────────
            query = f"{niche} in {location}"
            elapsed = time.time() - start_time
            remaining_timeout = max(60, int(MAX_SEARCH_TIME_SECONDS - elapsed - 60))

            await _update_search(supabase, search_id, {
                "progress_percent": 10,
                "message": f"Scraping Google Maps for '{niche}' in {location}...",
            })

            try:
                raw_results = await run_maps_scraper(
                    query=query,
                    max_results=MAX_RESULTS,
                    timeout_seconds=remaining_timeout,
                )
            except Exception as e:
                logger.error(f"[Pipeline:{search_id}] Scraper failed: {e}")
                await _update_search(supabase, search_id, {
                    "status": "failed",
                    "message": "Scraper failed",
                    "error_message": str(e),
                    "progress_percent": 0,
                })
                return

            if is_search_cancelled(search_id):
                await _mark_cancelled(supabase, search_id)
                return

            if not raw_results:
                await _update_search(supabase, search_id, {
                    "status": "completed",
                    "progress_percent": 100,
                    "message": "No results found. Try a different search.",
                    "total_results": 0,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                })
                return

            # ── Stage 3: Save Leads ───────────────────────────
            await _update_search(supabase, search_id, {
                "progress_percent": 40,
                "message": f"Found {len(raw_results)} businesses. Saving leads...",
            })

            lead_ids = await _save_leads(supabase, search_id, user_id, raw_results)
            logger.info(f"[Pipeline:{search_id}] Saved {len(lead_ids)} leads")

            if is_search_cancelled(search_id):
                await _mark_cancelled(supabase, search_id)
                return

            # ── Stage 4: Analyze Websites ─────────────────────
            await _update_search(supabase, search_id, {
                "status": "analyzing",
                "progress_percent": 50,
                "message": "Analyzing websites...",
            })

            await _analyze_lead_websites(
                supabase, search_id, user_id, lead_ids, start_time
            )

            if is_search_cancelled(search_id):
                await _mark_cancelled(supabase, search_id)
                return

            # ── Stage 5: Finalize ─────────────────────────────
            await _finalize_search(supabase, search_id)

    except Exception as e:
        logger.error(f"[Pipeline:{search_id}] Unexpected error: {e}", exc_info=True)
        try:
            await _update_search(supabase, search_id, {
                "status": "failed",
                "message": "Search failed unexpectedly",
                "error_message": str(e),
            })
        except Exception:
            pass
    finally:
        _active_searches.pop(search_id, None)


async def _save_leads(
    supabase, search_id: str, user_id: str, raw_results: list[dict]
) -> list[str]:
    """Save raw scraper results as lead rows. Returns list of lead IDs."""
    lead_ids = []

    for result in raw_results:
        try:
            # Determine initial lead category based on whether website exists
            has_website = bool(result.get("website_url"))
            initial_category = "warm" if has_website else "hot"

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
                "lead_category": initial_category,
            }

            response = supabase.table("leads").insert(lead_data).execute()
            if response.data:
                lead_ids.append(response.data[0]["id"])
        except Exception as e:
            logger.error(f"Failed to save lead '{result.get('business_name', '?')}': {e}")

    return lead_ids


async def _analyze_lead_websites(
    supabase,
    search_id: str,
    user_id: str,
    lead_ids: list[str],
    start_time: float,
) -> None:
    """
    Analyze websites for all leads that have a website_url.
    Respects the overall 10-minute timeout.
    """
    # Fetch leads with websites
    try:
        response = (
            supabase.table("leads")
            .select("id, website_url, business_name")
            .eq("search_id", search_id)
            .neq("website_url", "")
            .execute()
        )
        leads_with_websites = response.data or []
    except Exception as e:
        logger.error(f"[Pipeline:{search_id}] Failed to fetch leads for analysis: {e}")
        return

    total = len(leads_with_websites)
    if total == 0:
        return

    analyzed = 0
    analysis_semaphore = asyncio.Semaphore(5)  # Concurrent analysis limit

    async def analyze_one(lead: dict) -> None:
        nonlocal analyzed
        async with analysis_semaphore:
            # Check timeout
            elapsed = time.time() - start_time
            if elapsed > MAX_SEARCH_TIME_SECONDS:
                logger.warning(f"[Pipeline:{search_id}] Timeout during analysis")
                return

            # Check cancellation
            if is_search_cancelled(search_id):
                return

            url = lead.get("website_url", "")
            lead_id = lead["id"]

            try:
                result = await analyze_website(url)

                # Save analysis
                analysis_data = {
                    "lead_id": lead_id,
                    "website_url": url,
                    "overall_score": result.get("overall_score", 0),
                    "issues": result.get("issues", []),
                    "emails_found": result.get("emails_found", []),
                    "phones_found": result.get("phones_found", []),
                    "raw_analysis": result.get("raw_analysis", {}),
                }
                supabase.table("website_analyses").insert(analysis_data).execute()

                # Update lead with analysis results
                category = result.get("category", "warm")
                update_data = {
                    "website_health_score": result.get("overall_score", 0),
                    "lead_category": category,
                }

                # If analysis found emails, update lead
                emails = result.get("emails_found", [])
                if emails and not lead.get("email_found"):
                    update_data["email_found"] = emails[0]

                supabase.table("leads").update(update_data).eq("id", lead_id).execute()

            except Exception as e:
                logger.error(f"[Pipeline:{search_id}] Analysis failed for {lead.get('business_name', '?')}: {e}")

            analyzed += 1
            # Update progress
            progress = 50 + int((analyzed / total) * 45)
            progress = min(progress, 95)
            try:
                await _update_search(supabase, search_id, {
                    "progress_percent": progress,
                    "message": f"Analyzed {analyzed}/{total} websites...",
                })
            except Exception:
                pass

    # Run analyses concurrently with timeout
    tasks = [analyze_one(lead) for lead in leads_with_websites]
    remaining = MAX_SEARCH_TIME_SECONDS - (time.time() - start_time)

    if remaining > 0:
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=max(30, remaining),
            )
        except asyncio.TimeoutError:
            logger.warning(f"[Pipeline:{search_id}] Analysis stage timed out — saving partial results")


async def _finalize_search(supabase, search_id: str) -> None:
    """Count lead categories and mark search as completed."""
    try:
        # Count leads by category
        all_leads = (
            supabase.table("leads")
            .select("lead_category")
            .eq("search_id", search_id)
            .execute()
        )
        leads_data = all_leads.data or []

        total = len(leads_data)
        hot = sum(1 for l in leads_data if l.get("lead_category") == "hot")
        warm = sum(1 for l in leads_data if l.get("lead_category") == "warm")
        skip = sum(1 for l in leads_data if l.get("lead_category") == "skip")

        await _update_search(supabase, search_id, {
            "status": "completed",
            "progress_percent": 100,
            "message": f"Found {total} leads: {hot} hot, {warm} warm, {skip} skip",
            "total_results": total,
            "hot_leads": hot,
            "warm_leads": warm,
            "skipped": skip,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })

        logger.info(f"[Pipeline:{search_id}] Completed — {total} leads ({hot}H/{warm}W/{skip}S)")

    except Exception as e:
        logger.error(f"[Pipeline:{search_id}] Finalization failed: {e}")
        await _update_search(supabase, search_id, {
            "status": "completed",
            "progress_percent": 100,
            "message": "Search completed (finalization had issues)",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })


async def _mark_cancelled(supabase, search_id: str) -> None:
    """Mark a search as cancelled."""
    await _update_search(supabase, search_id, {
        "status": "cancelled",
        "message": "Search cancelled by user",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    })
    logger.info(f"[Pipeline:{search_id}] Cancelled")


async def _update_search(supabase, search_id: str, data: dict) -> None:
    """Update a search row in the database."""
    try:
        supabase.table("searches").update(data).eq("id", search_id).execute()
    except Exception as e:
        logger.error(f"[Pipeline:{search_id}] Failed to update search: {e}")
