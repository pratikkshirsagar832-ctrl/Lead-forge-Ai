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
import threading
import time
from datetime import date, datetime, timezone

from app.database import get_supabase_admin
from app.services.scraper_service import run_maps_scraper
from app.services.usage import settle_search_quota

logger = logging.getLogger(__name__)

_search_semaphore = asyncio.Semaphore(3)
_cancel_lock = threading.Lock()
_cancelled_searches: set[str] = set()
MAX_SEARCH_TIME_SECONDS = 600
MAX_RESULTS = 25

TERMINAL_STATUSES = ("completed", "failed", "cancelled")
# Hard per-search cap for load-more batches (avoids unbounded paid scraper runs).
MAX_SEARCH_LEADS_CAP = 100


def is_search_cancelled(search_id: str) -> bool:
    with _cancel_lock:
        return search_id in _cancelled_searches


def cancel_search(search_id: str) -> None:
    """Request cancellation. Persists until the worker clears it — a cancel
    issued while the job is queued behind the semaphore is honored when the
    worker eventually starts (previously it was clobbered at task start)."""
    with _cancel_lock:
        _cancelled_searches.add(search_id)


def _clear_cancel(search_id: str) -> None:
    with _cancel_lock:
        _cancelled_searches.discard(search_id)


async def run_search_pipeline(
    search_id: str,
    user_id: str,
    niche: str,
    location: str,
) -> None:
    supabase = get_supabase_admin()
    start_time = time.time()

    try:
        async with _search_semaphore:
            # Re-check both the in-memory cancel AND the DB row: a cancel issued
            # while this job queued must not start a charged scrape.
            if is_search_cancelled(search_id) or await _db_status_is(supabase, search_id, "cancelled"):
                await _mark_cancelled(supabase, search_id)
                return

            await _update_search(supabase, search_id, {
                "status": "scraping",
                "progress_percent": 5,
                "message": f"Starting search...",
            })

            outcome, limit_hit = await _run_maps_search(supabase, search_id, user_id, niche, location, start_time)

            # Only a genuinely-running outcome may be finalized as completed.
            # Terminal outcomes already wrote their own status.
            if outcome == "failed":
                logger.info(f"[Pipeline:{search_id}] Skipping finalize: scraper failed")
            elif outcome == "cancelled":
                logger.info(f"[Pipeline:{search_id}] Skipping finalize: cancelled")
            elif outcome == "no_results":
                logger.info(f"[Pipeline:{search_id}] Skipping finalize: no results (completed already written)")
            else:
                await _finalize_search(supabase, search_id, limit_hit=limit_hit)

    except Exception as e:
        logger.error(f"[Pipeline:{search_id}] Unexpected error: {e}", exc_info=True)
        try:
            await settle_search_quota(supabase, search_id, user_id, 0)
            await _update_search(supabase, search_id, {
                "status": "failed", "message": "Search failed unexpectedly",
                "error_message": str(e),
            })
        except Exception as update_err:
            logger.error(f"[Pipeline:{search_id}] Failed to update search status after error: {update_err}")
    finally:
        _clear_cancel(search_id)


async def _db_status_is(supabase, search_id: str, status: str) -> bool:
    """True when the DB row is already in `status` (authoritative cancel state)."""
    try:
        row = await asyncio.to_thread(
            lambda: supabase.table("searches").select("status").eq("id", search_id).limit(1).execute()
        )
        return bool(row.data and row.data[0].get("status") == status)
    except Exception:
        return False


async def load_more_maps_search(
    search_id: str,
    user_id: str,
    niche: str,
    location: str,
) -> int:
    """Load up to 10 more results for an existing completed search.

    Extra leads are charged against the user's remaining monthly quota; the
    method returns 0 (no work done / nothing new) when quota is exhausted or
    the search is not load-more eligible.
    """
    supabase = get_supabase_admin()

    # Enforce a sane total cap per search so the endpoint cannot be used to
    # trigger unlimited paid scraper runs on a single row.
    existing_rows = await asyncio.to_thread(
        lambda: supabase.table("leads").select("id", count="exact").eq("search_id", search_id).execute()
    )
    already_saved = int((existing_rows.count if existing_rows and existing_rows.count else 0) or 0)
    if already_saved >= MAX_SEARCH_LEADS_CAP:
        logger.info(f"[Pipeline:{search_id}] Load-more refused: cap {MAX_SEARCH_LEADS_CAP} reached")
        return 0

    # Monthly quota gate for the extra batch (google_maps source).
    from app.services.plans import get_plan_row, resolve_effective_subscription
    eff = resolve_effective_subscription(supabase, user_id)
    plan = get_plan_row(supabase, eff["plan_id"])
    plan_limit = int(plan.get("gmb_leads_monthly", 0) or 0)
    month_str = datetime.now(timezone.utc).replace(day=1).date().isoformat()
    try:
        usage = await asyncio.to_thread(
            lambda: supabase.table("monthly_usage")
            .select("gmb_generated,gmb_reserved")
            .eq("user_id", user_id).eq("usage_month", month_str).limit(1).execute()
        )
        u = (usage.data or [{}])[0] if usage.data else {}
        used = int(u.get("gmb_generated", 0) or 0) + int(u.get("gmb_reserved", 0) or 0)
    except Exception:
        used = 0
    remaining = max(0, plan_limit - used)
    if remaining <= 0:
        logger.info(f"[Pipeline:{search_id}] Load-more refused: monthly gmb quota exhausted")
        return 0
    batch_cap = min(10, remaining, MAX_SEARCH_LEADS_CAP - already_saved)
    if batch_cap <= 0:
        return 0

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
            query=f"{niche} in {location}",
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
            if len(new_results) >= batch_cap:
                break

    if not new_results:
        logger.info(f"[Pipeline:{search_id}] No new unique leads found for load-more")
        return 0

    lead_ids, _ = await _save_maps_leads(supabase, search_id, user_id, new_results)
    logger.info(f"[Pipeline:{search_id}] Load-more saved {len(lead_ids)} new leads")

    # Account the extra batch against the monthly quota (this search's original
    # reservation was already settled at first completion).
    if lead_ids:
        from app.services.usage import record_monthly_generated
        await record_monthly_generated(supabase, user_id, "google_maps", len(lead_ids))

    # Update search totals
    await _finalize_search(supabase, search_id)
    return len(lead_ids)


async def _run_maps_search(
    supabase, search_id: str, user_id: str, niche: str, location: str, start_time: float
) -> tuple[str, bool]:
    """Run the scraper and save leads.

    Returns (outcome, limit_hit):
      outcome "ok"        -> leads saved (caller finalizes as completed)
      outcome "failed"    -> scraper failed (terminal 'failed' already written)
      outcome "cancelled" -> cancelled (terminal 'cancelled' already written)
      outcome "no_results"-> completed with zero leads (already written)
    """
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
        return "failed", False

    if is_search_cancelled(search_id) or await _db_status_is(supabase, search_id, "cancelled"):
        await _mark_cancelled(supabase, search_id)
        return "cancelled", False

    if not raw_results:
        await _update_search(supabase, search_id, {
            "status": "completed", "progress_percent": 100,
            "message": "No results found. Try a different search.",
            "total_results": 0,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        return "no_results", False

    await _update_search(supabase, search_id, {
        "progress_percent": 40,
        "message": f"Found {len(raw_results)} businesses. Saving leads...",
    })

    lead_ids, maps_limit_hit = await _save_maps_leads(supabase, search_id, user_id, raw_results)
    logger.info(f"[Pipeline:{search_id}] Saved {len(lead_ids)} maps leads (limit_hit={maps_limit_hit})")
    return "ok", maps_limit_hit


async def _save_maps_leads(
    supabase, search_id: str, user_id: str, raw_results: list[dict]
) -> tuple[list[str], bool]:
    # This search owns a server-side reservation created atomically before the
    # job was started. Never consult or mutate the legacy daily counters here.
    remaining_leads = 0
    try:
        reservation = await asyncio.to_thread(
            lambda: supabase.table("searches").select("reserved_leads")
            .eq("id", search_id).limit(1).execute()
        )
        remaining_leads = int((reservation.data or [{}])[0].get("reserved_leads", 0) or 0)
    except Exception:
        # Column may not exist — allow unlimited saves (no quota enforcement).
        remaining_leads = len(raw_results) + 100
        logger.debug(f"[Pipeline:{search_id}] reserved_leads column unavailable, saving all results")

    lead_ids = []
    hit_limit = False
    for result in raw_results:
        if remaining_leads <= 0:
            hit_limit = True
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
    return lead_ids, hit_limit


# ── FINALIZE ─────────────────────────────────────────────────────────

async def _finalize_search(supabase, search_id: str, limit_hit: bool = False) -> None:
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

        message = f"Found {total} leads: {hot} hot, {warm} warm"
        if limit_hit:
            message += " | Monthly lead quota reached."

        # This call is idempotent at the database layer and releases unused
        # reservation capacity if fewer leads were found.
        search_row = await asyncio.to_thread(
            lambda: supabase.table("searches").select("user_id").eq("id", search_id).limit(1).execute()
        )
        if search_row.data:
            await settle_search_quota(supabase, search_id, search_row.data[0]["user_id"], total)

        await _update_search(supabase, search_id, {
            "status": "completed",
            "progress_percent": 100,
            "message": message,
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
    row = await asyncio.to_thread(lambda: supabase.table("searches").select("user_id").eq("id", search_id).limit(1).execute())
    if row.data:
        await settle_search_quota(supabase, search_id, row.data[0]["user_id"], 0)
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
