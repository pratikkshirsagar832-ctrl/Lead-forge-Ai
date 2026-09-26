"""
Hyperclients - Search Router

Endpoints:
  POST /api/searches          - create a new search
  GET  /api/searches          - search history
  GET  /api/searches/{id}     - search detail
  GET  /api/searches/{id}/status - search status (for polling)
  POST /api/searches/{id}/cancel - cancel a running search
"""

from datetime import datetime, timezone

import asyncio
import logging
import math

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from app.database import get_supabase_admin
from app.middleware.auth_middleware import get_current_user
from app.middleware.usage_middleware import check_search_limit
from app.schemas.search import (
    SearchCreateRequest,
    SearchHistoryItem,
    SearchHistoryResponse,
    SearchResponse,
    SearchStatusResponse,
)
from app.services.pipeline import cancel_search, run_search_pipeline, load_more_maps_search
from app.services.hyperagent_service import (
    run_hyperagent_pipeline,
    get_progress as get_hyperagent_progress,
    clear_progress as clear_hyperagent_progress,
)

router = APIRouter(prefix="/api/searches", tags=["Searches"])


async def _refund_daily_search(supabase, user_id: str) -> None:
    """Give back the monthly search unit consumed by `check_search_limit`.

    The unit is consumed atomically *before* the handler runs, so any path that
    does not actually create a search row must return it — otherwise a failed
    request silently burns one of the user's monthly searches.
    """
    from app.services.usage import refund_monthly_quota
    try:
        await refund_monthly_quota(supabase, user_id, "search")
    except Exception as e:  # never fail the request over an accounting refund
        logger.warning("Could not refund monthly search unit for user %s: %s", user_id[:8], e)


async def _release_unused_reservation(supabase, user_id: str, quota_source: str, amount: int) -> None:
    """Roll back a monthly reservation when the search row could not be created.

    Best-effort: subtract the reserved amount so a failed search never leaks a
    permanent hole in the user's monthly quota.
    """
    if amount <= 0:
        return
    month_str = datetime.now(timezone.utc).replace(day=1).date().isoformat()
    reserved_col = "linkedin_hq_reserved" if quota_source == "linkedin" else "gmb_reserved"
    try:
        existing = await asyncio.to_thread(
            lambda: supabase.table("monthly_usage")
            .select(reserved_col)
            .eq("user_id", user_id)
            .eq("usage_month", month_str)
            .limit(1)
            .execute()
        )
        if existing.data and len(existing.data) > 0:
            cur = int(existing.data[0].get(reserved_col, 0) or 0)
            await asyncio.to_thread(
                lambda: supabase.table("monthly_usage")
                .update({reserved_col: max(0, cur - amount)})
                .eq("user_id", user_id).eq("usage_month", month_str)
                .execute()
            )
            logger.info(
                "Released %d unused %s reservation(s) for user %s (search row not created)",
                amount, quota_source, user_id[:8],
            )
    except Exception as e:
        # Never fail the request over this, but make the leak visible: without
        # the release the user permanently loses `amount` of monthly quota.
        logger.warning(
            "Could not release unused reservation for user %s (%d %s reserved): %s",
            user_id[:8], amount, quota_source, e, exc_info=True,
        )


@router.post("", response_model=SearchResponse, status_code=status.HTTP_201_CREATED)
async def create_search(
    request: SearchCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(check_search_limit),
):
    """Create a new search and start the background pipeline."""
    supabase = get_supabase_admin()
    user_id = current_user["id"]

    query_term = request.niche.strip()
    location_term = request.location.strip()

    # Product policy: LinkedIn runs in exactly ONE role lane — freelancer
    # (posts needing a freelancer) or agency (clients seeking an agency).
    # Never mixed. Hiring/job-ads and job-seeker intents are never requested.
    if request.source == "linkedin":
        requested = request.lead_types or ["freelancer"]
        # Legacy "buyer" == freelancer lane. First valid role wins (one lane).
        norm = ["freelancer" if t == "buyer" else t for t in requested]
        lead_types = [t for t in norm if t in ("freelancer", "agency")] or ["freelancer"]
        lead_types = lead_types[:1]
    else:
        lead_types = request.lead_types or []

    # Check monthly lead quota and reserve leads (server-authoritative).
    # `check_search_limit` already consumed one daily search unit, so every
    # rejection between here and the searches row must give it back.
    from app.services.plans import get_plan_row, quota_owner_id, resolve_effective_subscription
    from app.services.usage import reserve_monthly_leads
    quota_user = user_id
    try:
        effective = resolve_effective_subscription(supabase, user_id)
        quota_user = quota_owner_id(effective, user_id)
        plan = get_plan_row(supabase, effective["plan_id"])
        quota_source = "linkedin" if request.source == "linkedin" else "google_maps"
        plan_limit = int(plan.get(
            "linkedin_hq_leads_monthly" if quota_source == "linkedin" else "gmb_leads_monthly", 0
        ) or 0)
        # LinkedIn lead runs are capped at 10 requested leads (UI offers 3/5/10).
        effective_max_results = request.max_results
        if request.source == "linkedin":
            effective_max_results = min(request.max_results, 10)

        reservation_amount = await reserve_monthly_leads(
            supabase, quota_user, effective["plan_id"], quota_source, effective_max_results
        )
    except Exception:
        await _refund_daily_search(supabase, quota_user)
        raise

    if reservation_amount <= 0:
        # Monthly quota exhausted: nothing was reserved and no search will run.
        await _refund_daily_search(supabase, quota_user)
        raise HTTPException(
            status_code=403,
            detail=f"Monthly {quota_source} lead limit reached ({plan_limit}/{plan_limit}). "
                   "Upgrade your plan or try again next month.",
        )
    # If quota forced a partial reservation, honor it (never over-deliver).
    effective_max_results = min(effective_max_results, reservation_amount)

    if request.source == "linkedin":
        # Hyperagent engine: SocialCrawl LinkedIn search + DeepSeek classification
        from app.services.hyperagent_service import (
            ha_lead_type_from,
            ha_time_window_from,
        )

        # Map frontend role to Hyperagent lead type.
        # Frontend sends ["freelancer"] or ["agency"] (single role lane).
        ha_lead_type = ha_lead_type_from(lead_types)
        ha_time_window = ha_time_window_from()
        all_types = False

        # GLOBAL SEARCH: location is intentionally removed for LinkedIn - the
        # engine scans posts from every country and returns the latest buyers.
        country_stored = ""
        stored_location = "Global"

        try:
            response = (
                supabase.table("searches")
                .insert({
                    "user_id": user_id,
                    "niche": query_term,
                    "location": stored_location,
                    "source": "linkedin",
                    "status": "queued",
                    "message": "Search queued",
                    "enrich_emails": request.enrich_emails,
                    "max_results": effective_max_results,
                    "lead_types": lead_types,
                    "quota_source": quota_source,
                    "reserved_leads": reservation_amount,
                })
                .execute()
            )
            if not response.data or len(response.data) == 0:
                raise HTTPException(status_code=500, detail="Failed to create search")
            search = response.data[0]
        except Exception as e:
            # Do not leak the reservation if the row could not be created.
            await _release_unused_reservation(supabase, quota_user, quota_source, reservation_amount)
            await _refund_daily_search(supabase, quota_user)
            if not isinstance(e, HTTPException):
                logger.error(f"Failed to create linkedin search: {e}")
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(status_code=500, detail="Failed to create search")

        background_tasks.add_task(
            run_hyperagent_pipeline,
            search_id=search["id"],
            user_id=user_id,
            service=query_term,
            country=country_stored,
            lead_type=ha_lead_type,
            time_window=ha_time_window,
            leads_needed=effective_max_results,
            all_types=all_types,
        )

        return search

    # Google Maps search - direct insert (no broken RPC)
    try:
        response = (
            supabase.table("searches")
            .insert({
                "user_id": user_id,
                "niche": query_term,
                "location": location_term or "Google Maps",
                "source": "google_maps",
                "status": "queued",
                "message": "Search queued",
                "enrich_emails": request.enrich_emails,
                "max_results": effective_max_results,
                "lead_types": lead_types,
                "quota_source": quota_source,
                "reserved_leads": reservation_amount,
            })
            .execute()
        )
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=500, detail="Failed to create search")
        search = response.data[0]
    except Exception as e:
        # Do not leak the reservation if the row could not be created.
        await _release_unused_reservation(supabase, quota_user, quota_source, reservation_amount)
        await _refund_daily_search(supabase, quota_user)
        if isinstance(e, HTTPException):
            raise
        logger.error(f"Failed to create search: {e}")
        raise HTTPException(status_code=500, detail="Failed to create search")

    background_tasks.add_task(
        run_search_pipeline,
        search_id=search["id"],
        user_id=user_id,
        niche=query_term,
        location=location_term,
        max_results=effective_max_results,
    )

    return search


@router.get("/scraper-health")
async def scraper_health_check(current_user: dict = Depends(get_current_user)):
    """Check if scraper binary exists and is executable (explicit opt-in only)."""
    from app.config import get_settings
    settings = get_settings()
    if not settings.debug_routes_enabled:
        raise HTTPException(status_code=404, detail="Not found")

    from app.services.scraper_service import _get_scraper_path
    import os

    scraper_path = _get_scraper_path()

    result = {
        "scraper_path": str(scraper_path),
        "exists": os.path.exists(scraper_path),
        "is_file": False,
        "is_executable": False,
        "environment": settings.environment,
        "os_type": os.name,
    }

    if os.path.exists(scraper_path):
        result["is_file"] = os.path.isfile(scraper_path)
        result["is_executable"] = os.access(scraper_path, os.X_OK)
        try:
            file_stat = os.stat(scraper_path)
            result["file_mode"] = oct(file_stat.st_mode)
            result["file_size_bytes"] = file_stat.st_size
        except Exception as e:
            result["stat_error"] = str(e)

    return result


@router.get("", response_model=SearchHistoryResponse)
async def get_search_history(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """Get paginated search history for the current user."""
    supabase = get_supabase_admin()
    user_id = current_user["id"]
    offset = (page - 1) * per_page

    try:
        # Get total count
        count_resp = (
            supabase.table("searches")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .execute()
        )
        total = count_resp.count or 0

        # Get paginated results
        response = (
            supabase.table("searches")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .range(offset, offset + per_page - 1)
            .execute()
        )

        return SearchHistoryResponse(
            items=[SearchHistoryItem(**s) for s in (response.data or [])],
            total=total,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Failed to fetch searches for user %s: %s", user_id[:8] if 'user_id' in dir() else 'unknown', e)
        raise HTTPException(status_code=500, detail="Failed to fetch searches")


@router.get("/{search_id}", response_model=SearchResponse)
async def get_search_detail(
    search_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get full search details."""
    supabase = get_supabase_admin()

    try:
        response = (
            supabase.table("searches")
            .select("*")
            .eq("id", search_id)
            .limit(1)
            .execute()
        )
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="Search not found")
        if response.data[0].get("user_id") != current_user["id"]:
            raise HTTPException(status_code=404, detail="Search not found")
        return response.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Failed to fetch search %s: %s", search_id, e)
        raise HTTPException(status_code=500, detail="Failed to fetch search")


@router.get("/{search_id}/results")
def get_search_results(
    search_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(4, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
):
    """Get leads for a search progressively (batches of 4 for live display)."""
    supabase = get_supabase_admin()
    offset = (page - 1) * per_page

    try:
        search_owner = supabase.table("searches").select("user_id, source").eq("id", search_id).limit(1).execute()
        if not search_owner.data or len(search_owner.data) == 0:
            raise HTTPException(status_code=404, detail="Search not found")
        if search_owner.data[0].get("user_id") != current_user["id"]:
            raise HTTPException(status_code=404, detail="Search not found")

        # LinkedIn searches persist to the dedicated ha_leads table
        # (original Hyperagent engine schema). Google Maps uses `leads`.
        if search_owner.data[0].get("source") == "linkedin":
            count_resp = (
                supabase.table("ha_leads")
                .select("id", count="exact")
                .eq("search_id", search_id)
                .execute()
            )
            total = count_resp.count or 0
            response = (
                supabase.table("ha_leads")
                .select("*")
                .eq("search_id", search_id)
                # Newest buyer first by EXACT publish time (post_date is day-level).
                .order("posted_at", desc=True)
                .order("post_date", desc=True)
                .range(offset, offset + per_page - 1)
                .execute()
            )
        else:
            count_resp = (
                supabase.table("leads")
                .select("id", count="exact")
                .eq("search_id", search_id)
                .execute()
            )
            total = count_resp.count or 0
            response = (
                supabase.table("leads")
                .select("*")
                .eq("search_id", search_id)
                .order("created_at", desc=False)
                .range(offset, offset + per_page - 1)
                .execute()
            )

        # Enrich leads with search source for frontend rendering
        items = response.data or []
        if items:
            search_row = supabase.table("searches").select("source, niche, lead_types").eq("id", search_id).limit(1).execute()
            srow = (search_row.data or [{}])[0] if search_row.data else {}
            search_source = srow.get("source", "google_maps")
            for item in items:
                if not item.get("source"):
                    item["source"] = search_source
                # Map Hyperagent fields to frontend-expected fields
                if search_source == "linkedin":
                    if not item.get("business_name") and item.get("author_name"):
                        item["business_name"] = item["author_name"]
                    if not item.get("linkedin_url") and item.get("author_profile_url"):
                        item["linkedin_url"] = item["author_profile_url"]
                    if not item.get("post_type"):
                        # Badge follows the lane the user picked for this
                        # search (Freelancer XOR Agency, never mixed).
                        from app.routers.leads import post_type_for
                        item["post_type"] = post_type_for(item, srow.get("lead_types"))
                    if not item.get("headline") and item.get("author_name"):
                        item["headline"] = item["author_name"]
                    if not item.get("posted_at") and item.get("post_date"):
                        item["posted_at"] = item["post_date"]
                    if not item.get("website_health_score") and item.get("overall_quality_score"):
                        item["website_health_score"] = round(item["overall_quality_score"] * 100) if item["overall_quality_score"] <= 1 else item["overall_quality_score"]
                    # ha_leads has no ai_pitch/rating/etc â†’ default safe values
                    item.setdefault("email_found", "")
                    item.setdefault("ai_pitch", None)
                    item.setdefault("user_status", item.get("status") or "new")
                    item.setdefault("user_notes", item.get("notes") or "")

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": max(1, math.ceil(total / per_page)),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Failed to fetch results for %s: %s", search_id, e)
        raise HTTPException(status_code=500, detail="Failed to fetch results")


@router.get("/{search_id}/status", response_model=SearchStatusResponse)
def get_search_status(
    search_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get search status for polling (lightweight response)."""
    supabase = get_supabase_admin()

    try:
        response = (
            supabase.table("searches")
            .select("id, user_id, status, source, progress_percent, message, total_results, hot_leads, warm_leads, skipped, emails_found, error_message, created_at, completed_at, niche, location, max_results, lead_types")
            .eq("id", search_id)
            .limit(1)
            .execute()
        )
        if not response.data or len(response.data) == 0:
            logger.warning(f"Status 404: search={search_id} user={current_user['id']} resp={response}")
            raise HTTPException(status_code=404, detail="Search not found")
        if response.data[0].get("user_id") != current_user["id"]:
            logger.warning(f"Status 403: search={search_id} owner={response.data[0].get('user_id')} requester={current_user['id']}")
            raise HTTPException(status_code=404, detail="Search not found")
            
        row = response.data[0]

        # A restart marks the main row failed (see main.py lifespan cleanup).
        # If ha_searches is still 'running', do NOT resurrect it as scraping.
        _restart_failed = (
            row.get("status") == "failed"
            and "restart" in str(row.get("error_message") or "").lower()
        )
        # A user cancel is written to the main row immediately, while the
        # engine thread may still report 'running' until it reaches its next
        # checkpoint. The cancel wins - otherwise the UI kept showing
        # "Searching..." and a second click failed with "status 'cancelled'".
        _user_cancelled = row.get("status") == "cancelled"

        # For LinkedIn searches, the authoritative state lives in ha_searches
        # (original Hyperagent engine). Pull it and map to main-search fields.
        if row.get("source") == "linkedin" and not _restart_failed and not _user_cancelled:
            try:
                ha = (
                    supabase.table("ha_searches")
                    .select("*")
                    .eq("id", search_id)
                    .limit(1)
                    .execute()
                )
                ha_row = ha.data[0] if ha.data else None
            except Exception:
                ha_row = None
            if ha_row:
                # Map engine lifecycle â†’ main status vocabulary
                ha_status = ha_row.get("status") or "queued"
                if ha_status == "running":
                    ha_status = "scraping"
                elif ha_status == "no_results":
                    ha_status = "completed"
                row["status"] = ha_status
                row["warm_leads"] = int(ha_row.get("scanned_count") or 0)
                # ACTUAL saved leads (engine accepted_count can overstate: the
                # type-content filter drops mismatched posts at save time).
                try:
                    cnt = (
                        supabase.table("ha_leads")
                        .select("id", count="exact")
                        .eq("search_id", search_id)
                        .execute()
                    )
                    row["hot_leads"] = int(cnt.count or 0)
                except Exception:
                    row["hot_leads"] = int(ha_row.get("accepted_count") or 0)
                # "Total Found" = the DELIVERED qualified leads (<= requested N).
                # Raw `found_count` is the count of posts reviewed, not leads -
                # showing it here made "Total Found 40 / Processed 56" (processed
                # > found), which is impossible. Show delivered leads instead.
                row["total_results"] = row["hot_leads"]
                row["skipped"] = max(int(row.get("skipped") or 0),
                                     int(row.get("warm_leads") or 0)
                                     - int(row.get("hot_leads") or 0))
                if ha_row.get("error"):
                    row["error_message"] = ha_row["error"]
                if ha_row.get("finished_at"):
                    row["completed_at"] = ha_row["finished_at"]
                # Exact-count context for the frontend contract
                row["max_results"] = ha_row.get("leads_needed") or row.get("max_results")
                # Tier-0 observability: per-search spend + stop reason (columns
                # exist only after the observability migration; else 0/None).
                row["serper_requests_used"] = int(ha_row.get("serper_requests_used") or 0)
                row["deepseek_calls_used"] = int(ha_row.get("deepseek_calls_used") or 0)
                row["stop_reason"] = ha_row.get("stop_reason")

        # A terminal row is authoritative: drop any leftover registry entry so
        # it can never overwrite the final counts on a later poll.
        if row.get("status") in ("completed", "failed", "cancelled"):
            clear_hyperagent_progress(search_id)

        # Merge Hyperagent live progress if available
        ha_progress = get_hyperagent_progress(search_id)
        if ha_progress and row.get("status") in ("queued", "running", "scraping", "analyzing"):
            row["total_results"] = ha_progress.get("found") or row.get("total_results", 0)
            row["hot_leads"] = ha_progress.get("accepted") or row.get("hot_leads", 0)
            row["warm_leads"] = ha_progress.get("scanned") or row.get("warm_leads", 0)
            # Friendly live message - engine's internal iteration detail stays
            # in the logs, never in the UI.
            if row.get("source") == "linkedin":
                accepted_so_far = row["hot_leads"]
                wanted = row.get("max_results") or row.get("requested_count")
                try:
                    wanted = int(wanted) if wanted else None
                except (TypeError, ValueError):
                    wanted = None
                found_so_far = row["total_results"]
                raw_niche = (row.get("niche") or "").strip()
                try:
                    # Any-input: "I am a freelance video editor for YouTubers"
                    # reads as "video editor" in the live message.
                    from query_builder import primary_service
                    svc_label = primary_service(raw_niche) if raw_niche else ""
                except Exception:  # noqa: BLE001 - label is cosmetic
                    svc_label = raw_niche
                if not svc_label or len(svc_label.split()) > 5:
                    svc_label = "your service"
                if accepted_so_far > 0 and wanted:
                    row["message"] = (
                        f"We found {accepted_so_far} of {wanted} genuine {svc_label} buyers so far. "
                        "Scanning the latest posts to deliver the rest."
                    )
                elif found_so_far > 0:
                    row["message"] = (
                        f"Searching LinkedIn for {svc_label} buyers... {found_so_far} posts reviewed, "
                        "still looking for the strongest matches."
                    )
                else:
                    row["message"] = f"Searching LinkedIn for {svc_label} buyers..."
            elif ha_progress.get("message"):
                row["message"] = ha_progress["message"]
            # Surface engine stage as progress percent (best-effort)
            wanted = row.get("max_results") or row.get("requested_count") or 1
            try:
                wanted = int(wanted)
            except (TypeError, ValueError):
                wanted = 1
            pct = min(95, max(5, int((row["hot_leads"] / wanted) * 100))) if wanted else 5
            row["progress_percent"] = max(row.get("progress_percent") or 0, pct)

        created_dt = None
        if row.get("created_at"):
            try: created_dt = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
            except Exception: logger.warning(f"Failed to parse created_at: {row.get('created_at')}")
            
        comp_dt = None
        if row.get("completed_at"):
            try: comp_dt = datetime.fromisoformat(row["completed_at"].replace("Z", "+00:00"))
            except Exception: logger.warning(f"Failed to parse completed_at: {row.get('completed_at')}")

        elapsed = 0
        if created_dt:
            end_time = comp_dt or datetime.now(timezone.utc)
            elapsed = int((end_time - created_dt).total_seconds())
            
        hot = row.get("hot_leads", 0) or 0
        warm = row.get("warm_leads", 0) or 0
        skip = row.get("skipped", 0) or 0
        # "Processed" = how many posts we actually ran through the pipeline.
        # For LinkedIn that is the scanned/classified count (as many as we
        # could process); never hot+warm+skip, which double-counts scanned.
        if row.get("source") == "linkedin":
            processed = warm
        else:
            processed = hot + warm + skip
        
        return {
            "id": row["id"],
            "status": row.get("status", "queued"),
            "source": row.get("source", "google_maps"),
            "progress_percent": row.get("progress_percent", 0) or 0,
            "message": row.get("message", ""),
            "total_results": row.get("total_results", 0) or 0,
            "hot_leads": hot,
            "warm_leads": warm,
            "skipped": skip,
            "emails_found": row.get("emails_found", 0) or 0,
            "processed_count": processed,
            "elapsed_seconds": max(0, elapsed),
            "started_at": row.get("created_at"),
            "completed_at": row.get("completed_at"),
            "error_message": row.get("error_message"),
            # Exact-count / intent contract (linkedin only). Backward compatible.
            "requested_count": row.get("max_results"),
            "returned_count": row.get("total_results"),
            "lead_type": ("," .join(row.get("lead_types") or [])) if row.get("lead_types") else None,
            "country": "Global" if row.get("source") == "linkedin" else (row.get("location") or ""),
            "service": row.get("niche"),
            "lead_status": "complete" if row.get("status") == "completed" else None,
            "serper_requests_used": int(row.get("serper_requests_used") or 0),
            "deepseek_calls_used": int(row.get("deepseek_calls_used") or 0),
            "stop_reason": row.get("stop_reason"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Failed to fetch search status %s: %s", search_id, e)
        raise HTTPException(status_code=500, detail="Failed to fetch search status")


@router.post("/{search_id}/cancel")
async def cancel_search_endpoint(
    search_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Cancel a running search."""
    supabase = get_supabase_admin()

    try:
        # Verify search exists
        response = (
            supabase.table("searches")
            .select("id, status, user_id")
            .eq("id", search_id)
            .limit(1)
            .execute()
        )
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="Search not found")
        if response.data[0].get("user_id") != current_user["id"]:
            raise HTTPException(status_code=404, detail="Search not found")

        search = response.data[0]
        if search["status"] == "cancelled":
            # Idempotent: a double click (or a retry after a slow network)
            # is not an error.
            return {"message": "Search cancelled", "id": search_id}
        if search["status"] in ("completed", "failed"):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel a search with status '{search['status']}'",
            )

        # LinkedIn (Hyperagent) searches run in their own worker thread with a
        # cooperative cancel; Google Maps searches use the pipeline flag.
        if search.get("source") == "linkedin":
            from app.services.hyperagent_service import request_cancel
            request_cancel(search_id)
        else:
            cancel_search(search_id)

        supabase.table("searches").update({
            "status": "cancelled",
            "message": "Search cancelled by user",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", search_id).not_.in_("status", ["completed", "failed", "cancelled"]).execute()

        if search.get("source") == "linkedin":
            # Close the engine row too, so nothing (history, a restart, a
            # later poll) can ever see this search as still running.
            try:
                supabase.table("ha_searches").update({
                    "status": "cancelled",
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", search_id).in_("status", ["queued", "running"]).execute()
            except Exception as ha_err:  # noqa: BLE001 - main row is authoritative
                logger.warning("Could not mark ha_searches %s cancelled: %s", search_id, ha_err)

        return {"message": "Search cancelled", "id": search_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Failed to cancel search %s: %s", search_id, e)
        raise HTTPException(status_code=500, detail="Failed to cancel search")


@router.post("/{search_id}/load-more")
async def load_more_results(
    search_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Load 10 more results for a completed search."""
    supabase = get_supabase_admin()
    try:
        response = (
            supabase.table("searches")
            .select("id, niche, location, source, status, total_results, user_id")
            .eq("id", search_id)
            .limit(1)
            .execute()
        )
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="Search not found")
        if response.data[0].get("user_id") != current_user["id"]:
            raise HTTPException(status_code=404, detail="Search not found")

        search = response.data[0]

        # Load-more only exists for completed Google Maps searches; LinkedIn
        # runs a bounded exact-count engine and has no Maps scraper semantics.
        if search.get("source") != "google_maps":
            raise HTTPException(status_code=400, detail="Load more is only available for Google Maps searches")
        if search.get("status") != "completed":
            raise HTTPException(status_code=400, detail="Search must be completed before loading more results")

        new_count = await load_more_maps_search(
                search_id=search_id,
                user_id=current_user["id"],
                niche=search["niche"],
                location=search["location"],
            )

        return {
            "new_leads": new_count,
            "total_results": (search.get("total_results", 0) or 0) + new_count,
            "message": f"Found {new_count} more leads" if new_count > 0 else "No more leads found",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Failed to load more for %s: %s", search_id, e)
        raise HTTPException(status_code=500, detail="Failed to load more results")


class DebugSearchRequest(BaseModel):
    niche: str
    location: str

@router.post("/debug/test-scraper")
async def debug_test_scraper(request: DebugSearchRequest, current_user: dict = Depends(get_current_user)):
    from app.config import get_settings
    settings = get_settings()
    if not settings.debug_routes_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    
    import subprocess
    import tempfile
    import os
    from app.services.scraper_service import _get_scraper_path
    
    scraper_path = _get_scraper_path()
    input_fd, input_path = tempfile.mkstemp(suffix=".txt")
    output_fd, output_path = tempfile.mkstemp(suffix=".csv")
    
    # Close FDs immediately - we'll use path-based I/O from here
    os.close(input_fd)
    os.close(output_fd)
    
    with open(input_path, "w", encoding="utf-8") as f:
        f.write(f"{request.niche} in {request.location}\n")
        
    cmd = [
        scraper_path,
        "-input", input_path,
        "-results", output_path,
        "-exit-on-inactivity", "3m",
        "-depth", "1",
        "-c", "4",
        "-email"
    ]
    
    try:
        proc = subprocess.run(cmd, env={**os.environ}, capture_output=True, text=True, timeout=180)
        output_exists = os.path.exists(output_path)
        output_size = os.path.getsize(output_path) if output_exists else 0
        output_preview = ""
        if output_exists and output_size > 0:
            with open(output_path, "r", encoding="utf-8", errors="replace") as f:
                output_preview = f.read()[:2000]
                
        return {
            "success": proc.returncode == 0,
            "return_code": proc.returncode,
            "command": " ".join(cmd),
            "stdout": (proc.stdout or "")[:3000],
            "stderr": (proc.stderr or "")[:3000],
            "output_exists": output_exists,
            "output_size": output_size,
            "output_preview": output_preview
        }
    except subprocess.TimeoutExpired:
        # Still try to read partial results on timeout
        output_preview = ""
        try:
            if os.path.exists(output_path):
                with open(output_path, "r", encoding="utf-8", errors="replace") as f:
                    output_preview = f.read()[:2000]
        except Exception:
            pass
        return {
            "success": False,
            "error": "Timed out after 180s",
            "partial_output": output_preview
        }
    except Exception as err:
        return {"success": False, "error": f"{type(err).__name__}: {str(err)}"}
    finally:
        try: os.remove(input_path)
        except OSError as e: logger.warning(f"Failed to remove temp input: {e}")
        try: os.remove(output_path)
        except OSError as e: logger.warning(f"Failed to remove temp output: {e}")



