"""
LeadForge AI — Search Router

Endpoints:
  POST /api/searches          — create a new search
  GET  /api/searches          — search history
  GET  /api/searches/{id}     — search detail
  GET  /api/searches/{id}/status — search status (for polling)
  POST /api/searches/{id}/cancel — cancel a running search
"""

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from app.database import get_supabase_admin
from app.middleware.auth_middleware import get_current_user
from app.schemas.search import (
    SearchCreateRequest,
    SearchHistoryItem,
    SearchHistoryResponse,
    SearchResponse,
    SearchStatusResponse,
)
from app.services.pipeline import cancel_search, run_search_pipeline

router = APIRouter(prefix="/api/searches", tags=["Searches"])


@router.post("", response_model=SearchResponse, status_code=status.HTTP_201_CREATED)
async def create_search(
    request: SearchCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """Create a new search and start the background pipeline."""
    supabase = get_supabase_admin()
    user_id = current_user["id"]

    # Create search row
    search_data = {
        "user_id": user_id,
        "niche": request.niche.strip(),
        "location": request.location.strip(),
        "status": "queued",
        "progress_percent": 0,
        "message": "Search queued",
    }

    try:
        response = supabase.table("searches").insert(search_data).execute()
        if not response.data:
            raise HTTPException(status_code=500, detail="Failed to create search")
        search = response.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create search: {str(e)}")

    # Start background pipeline
    background_tasks.add_task(
        run_search_pipeline,
        search_id=search["id"],
        user_id=user_id,
        niche=request.niche.strip(),
        location=request.location.strip(),
    )

    return search


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
            .eq("user_id", current_user["id"])
            .limit(1)
            .execute()
        )
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="Search not found")
        return response.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch search: {str(e)}")


@router.get("/{search_id}/status", response_model=SearchStatusResponse)
async def get_search_status(
    search_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get search status for polling (lightweight response)."""
    print(f"[DEBUG] Entered get_search_status")
    print(f"[DEBUG] search_id: {search_id}")
    print(f"[DEBUG] current_user_id: {current_user['id']}")
    supabase = get_supabase_admin()

    try:
        response = (
            supabase.table("searches")
            .select("id, status, progress_percent, message, total_results, hot_leads, warm_leads, skipped, error_message, created_at, completed_at")
            .eq("id", search_id)
            .eq("user_id", current_user["id"])
            .limit(1)
            .execute()
        )
        print(f"[DEBUG] Supabase raw result.data: {response.data}")
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="Search not found")
            
        row = response.data[0]
        
        import datetime
        created_dt = None
        if row.get("created_at"):
            try: created_dt = datetime.datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
            except: pass
            
        comp_dt = None
        if row.get("completed_at"):
            try: comp_dt = datetime.datetime.fromisoformat(row["completed_at"].replace("Z", "+00:00"))
            except: pass

        elapsed = 0
        if created_dt:
            end_time = comp_dt or datetime.datetime.now(datetime.timezone.utc)
            elapsed = int((end_time - created_dt).total_seconds())
            
        hot = row.get("hot_leads", 0) or 0
        warm = row.get("warm_leads", 0) or 0
        skip = row.get("skipped", 0) or 0
        processed = hot + warm + skip
        
        return {
            "id": row["id"],
            "status": row.get("status", "queued"),
            "progress_percent": row.get("progress_percent", 0) or 0,
            "message": row.get("message", ""),
            "total_results": row.get("total_results", 0) or 0,
            "hot_leads": hot,
            "warm_leads": warm,
            "skipped": skip,
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
        # Verify ownership and that search is running
        response = (
            supabase.table("searches")
            .select("id, status")
            .eq("id", search_id)
            .eq("user_id", current_user["id"])
            .limit(1)
            .execute()
        )
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="Search not found")

        search = response.data[0]
        if search["status"] in ("completed", "failed", "cancelled"):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel a search with status '{search['status']}'",
            )

        # Signal cancellation to the pipeline
        cancel_search(search_id)

        # Update status immediately
        supabase.table("searches").update({
            "status": "cancelled",
            "message": "Search cancelled by user",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", search_id).execute()

        return {"message": "Search cancelled", "id": search_id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel search: {str(e)}")

from pydantic import BaseModel

class DebugSearchRequest(BaseModel):
    niche: str
    location: str

@router.post("/debug/test-scraper")
async def debug_test_scraper(request: DebugSearchRequest):
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
    except subprocess.TimeoutExpired as e:
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
            "error": f"Timed out after 180s",
            "partial_output": output_preview
        }
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {str(e)}"}
    finally:
        try: os.remove(input_path) 
        except: pass
        try: os.remove(output_path)
        except: pass
