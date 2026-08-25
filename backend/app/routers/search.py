"""
Hyperclients — Search Router

Endpoints:
  POST /api/searches          — create a new search
  GET  /api/searches          — search history
  GET  /api/searches/{id}     — search detail
  GET  /api/searches/{id}/status — search status (for polling)
  POST /api/searches/{id}/cancel — cancel a running search
"""

from datetime import datetime, timezone

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
from app.services.linkedin_pipeline import run_linkedin_pipeline_fast

router = APIRouter(prefix="/api/searches", tags=["Searches"])


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

    # Increment usage synchronously BEFORE creating search
    try:
        supabase.rpc("increment_daily_usage", {
            "p_user_id": user_id,
            "p_searches": 1,
            "p_leads": 0,
        }).execute()
    except Exception as e:
        logger.warning(f"Failed to increment daily usage via RPC: {e}")
        try:
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            existing = supabase.table("daily_usage").select("id, searches_run").eq("user_id", user_id).eq("date", today_str).execute()
            if existing.data and len(existing.data) > 0:
                supabase.table("daily_usage").update({
                    "searches_run": (existing.data[0].get("searches_run", 0) or 0) + 1,
                }).eq("id", existing.data[0]["id"]).execute()
            else:
                supabase.table("daily_usage").insert({
                    "user_id": user_id,
                    "date": today_str,
                    "searches_run": 1,
                    "leads_generated": 0,
                }).execute()
        except Exception as fallback_err:
            raise HTTPException(status_code=500, detail=f"Failed to record usage: {str(fallback_err)}")

    if request.source == "linkedin":
        try:
            response = (
                supabase.table("searches")
                .insert({
                    "user_id": user_id,
                    "niche": query_term,
                    "location": location_term or "LinkedIn",
                    "source": "linkedin",
                    "status": "queued",
                    "message": "Search queued",
                    "enrich_emails": request.enrich_emails,
                    "max_results": request.max_results,
                    "lead_types": request.lead_types,
                })
                .execute()
            )
            if not response.data or len(response.data) == 0:
                raise HTTPException(status_code=500, detail="Failed to create search")
            search = response.data[0]
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to create linkedin search: {e}")
            raise HTTPException(status_code=500, detail="Failed to create search")

        background_tasks.add_task(
            run_linkedin_pipeline_fast,
            search_id=search["id"],
            user_id=user_id,
            query=query_term,
            enrich_emails=request.enrich_emails,
            max_results=request.max_results,
            lead_types=request.lead_types,
        )

        return search

    try:
        response = supabase.rpc("create_search", {
            "p_user_id": user_id,
            "p_niche": query_term,
            "p_location": location_term,
        }).execute()
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=500, detail="Failed to create search")
        search = response.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create search: {e}")
        raise HTTPException(status_code=500, detail="Failed to create search")

    background_tasks.add_task(
        run_search_pipeline,
        search_id=search["id"],
        user_id=user_id,
        niche=query_term,
        location=location_term,
    )

    return search


@router.get("/scraper-health")
async def scraper_health_check(current_user: dict = Depends(get_current_user)):
    """Check if scraper binary exists and is executable."""
    from app.config import get_settings
    settings = get_settings()
    if settings.is_production:
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch searches: {str(e)}")


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
        raise HTTPException(status_code=500, detail=f"Failed to fetch search: {str(e)}")


@router.get("/{search_id}/results")
async def get_search_results(
    search_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(4, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
):
    """Get leads for a search progressively (batches of 4 for live display)."""
    supabase = get_supabase_admin()
    offset = (page - 1) * per_page

    try:
        search_owner = supabase.table("searches").select("user_id").eq("id", search_id).limit(1).execute()
        if not search_owner.data or len(search_owner.data) == 0:
            raise HTTPException(status_code=404, detail="Search not found")
        if search_owner.data[0].get("user_id") != current_user["id"]:
            raise HTTPException(status_code=404, detail="Search not found")

        count_resp = (
            supabase.table("leads")
            .select("id", count="exact")
            .eq("search_id", search_id)
            .execute()
        )
        total = count_resp.count or 0

        response = (
            supabase.table("leads")
            .select("id, source, business_name, category, full_address, phone, email_found, website_url, rating, total_reviews, lead_category, website_health_score, headline, linkedin_url, post_url, post_text, profile_picture_url, connections_count, posted_at, post_type, ai_confidence_score, ai_pitch, user_status, is_favorite")
            .eq("search_id", search_id)
            .order("created_at", desc=False)
            .range(offset, offset + per_page - 1)
            .execute()
        )

        return {
            "items": response.data or [],
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": max(1, math.ceil(total / per_page)),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch results: {str(e)}")


@router.get("/{search_id}/status", response_model=SearchStatusResponse)
async def get_search_status(
    search_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get search status for polling (lightweight response)."""
    supabase = get_supabase_admin()

    try:
        response = (
            supabase.table("searches")
            .select("id, user_id, status, source, progress_percent, message, total_results, hot_leads, warm_leads, skipped, emails_found, error_message, created_at, completed_at")
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
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch search status: {str(e)}")


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
        if search["status"] in ("completed", "failed", "cancelled"):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel a search with status '{search['status']}'",
            )

        cancel_search(search_id)

        supabase.table("searches").update({
            "status": "cancelled",
            "message": "Search cancelled by user",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", search_id).not_.in_("status", ["completed", "failed", "cancelled"]).execute()

        return {"message": "Search cancelled", "id": search_id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel search: {str(e)}")


@router.post("/{search_id}/load-more")
async def load_more_results(
    search_id: str,
    current_user: dict = Depends(get_current_user),
    background_tasks: BackgroundTasks = None,
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
        raise HTTPException(status_code=500, detail=f"Failed to load more results: {str(e)}")


class DebugSearchRequest(BaseModel):
    niche: str
    location: str

@router.post("/debug/test-scraper")
async def debug_test_scraper(request: DebugSearchRequest, current_user: dict = Depends(get_current_user)):
    from app.config import get_settings
    settings = get_settings()
    if settings.is_production:
        raise HTTPException(status_code=404, detail="Not found")
    
    import subprocess
    import tempfile
    import os
    from app.services.scraper_service import _get_scraper_path
    
    scraper_path = _get_scraper_path()
    input_fd, input_path = tempfile.mkstemp(suffix=".txt")
    output_fd, output_path = tempfile.mkstemp(suffix=".csv")
    
    # Close FDs immediately — we'll use path-based I/O from here
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



