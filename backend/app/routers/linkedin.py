"""
Hyperclients — LinkedIn Intent Leads Router

Endpoints:
  POST   /api/linkedin/searches          — start an intent search
  GET    /api/linkedin/searches          — search history
  GET    /api/linkedin/searches/{id}     — search detail
  GET    /api/linkedin/searches/{id}/status — status (for polling)
  GET    /api/linkedin/searches/{id}/results — leads for a search
  GET    /api/linkedin/leads             — all saved LinkedIn leads (filtered)
  PATCH  /api/linkedin/leads/{id}        — update status / favorite / notes
  DELETE /api/linkedin/leads/{id}        — delete a lead
"""

import logging
import math
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.database import get_supabase_admin
from app.middleware.auth_middleware import get_current_user
from app.middleware.usage_middleware import check_search_limit
from app.services.linkedin_pipeline import run_linkedin_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/linkedin", tags=["LinkedIn"])


class LinkedInSearchCreateRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=200, description="What people are asking for, e.g. 'I need SEO' or 'website developer'")
    enrich_emails: bool = Field(True, description="Try to find emails for leads")
    max_results: int = Field(20, ge=1, le=50, description="Number of leads to return")


class LinkedInLeadUpdateRequest(BaseModel):
    user_status: Optional[Literal["new", "contacted", "replied", "converted", "lost"]] = None
    is_favorite: Optional[bool] = None
    user_notes: Optional[str] = None


@router.post("/searches", status_code=status.HTTP_201_CREATED)
async def create_linkedin_search(
    request: LinkedInSearchCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(check_search_limit),
):
    """Create a new LinkedIn intent search and start the background pipeline."""
    supabase = get_supabase_admin()
    user_id = current_user["id"]

    try:
        supabase.rpc("increment_daily_usage", {
            "p_user_id": user_id,
            "p_searches": 1,
            "p_leads": 0,
        }).execute()
    except Exception as e:
        logger.warning(f"Failed to increment daily usage via RPC: {e}")

    try:
        response = (
            supabase.table("linkedin_searches")
            .insert({
                "user_id": user_id,
                "query": request.query.strip(),
                "enrich_emails": request.enrich_emails,
                "max_results": request.max_results,
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
        run_linkedin_pipeline,
        search_id=search["id"],
        user_id=user_id,
        query=request.query.strip(),
        enrich_emails=request.enrich_emails,
        max_results=request.max_results,
    )

    return search


@router.get("/searches")
async def get_linkedin_search_history(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """Get paginated LinkedIn search history for the current user."""
    supabase = get_supabase_admin()
    user_id = current_user["id"]
    offset = (page - 1) * per_page

    try:
        count_resp = (
            supabase.table("linkedin_searches")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .execute()
        )
        total = count_resp.count or 0

        response = (
            supabase.table("linkedin_searches")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .range(offset, offset + per_page - 1)
            .execute()
        )
        return {"items": response.data or [], "total": total}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch searches: {str(e)}")


@router.get("/searches/{search_id}/status")
async def get_linkedin_search_status(
    search_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get lightweight search status for polling."""
    supabase = get_supabase_admin()

    try:
        response = (
            supabase.table("linkedin_searches")
            .select("id, user_id, status, progress_percent, message, total_results, emails_found, error_message, created_at, completed_at")
            .eq("id", search_id)
            .limit(1)
            .execute()
        )
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="Search not found")
        if response.data[0].get("user_id") != current_user["id"]:
            raise HTTPException(status_code=404, detail="Search not found")

        row = response.data[0]
        return {
            "id": row["id"],
            "status": row.get("status", "queued"),
            "progress_percent": row.get("progress_percent", 0) or 0,
            "message": row.get("message", ""),
            "total_results": row.get("total_results", 0) or 0,
            "emails_found": row.get("emails_found", 0) or 0,
            "error_message": row.get("error_message"),
            "created_at": row.get("created_at"),
            "completed_at": row.get("completed_at"),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch status: {str(e)}")


@router.get("/searches/{search_id}/results")
async def get_linkedin_search_results(
    search_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """Get leads for a LinkedIn search (paginated)."""
    supabase = get_supabase_admin()
    offset = (page - 1) * per_page

    try:
        owner = (
            supabase.table("linkedin_searches")
            .select("user_id")
            .eq("id", search_id)
            .limit(1)
            .execute()
        )
        if not owner.data or len(owner.data) == 0:
            raise HTTPException(status_code=404, detail="Search not found")
        if owner.data[0].get("user_id") != current_user["id"]:
            raise HTTPException(status_code=404, detail="Search not found")

        count_resp = (
            supabase.table("linkedin_leads")
            .select("id", count="exact")
            .eq("search_id", search_id)
            .execute()
        )
        total = count_resp.count or 0

        response = (
            supabase.table("linkedin_leads")
            .select("*")
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
            "total_pages": max(1, math.ceil(total / per_page)) if total else 0,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch results: {str(e)}")


@router.get("/searches/{search_id}")
async def get_linkedin_search_detail(
    search_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get full LinkedIn search details."""
    supabase = get_supabase_admin()

    try:
        response = (
            supabase.table("linkedin_searches")
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


@router.get("/leads")
async def list_linkedin_leads(
    search_id: Optional[str] = Query(None),
    user_status: Optional[str] = Query(None),
    is_favorite: Optional[bool] = Query(None),
    search: Optional[str] = Query(None, description="Search by name"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """List saved LinkedIn leads with filtering and pagination."""
    supabase = get_supabase_admin()
    user_id = current_user["id"]
    offset = (page - 1) * per_page

    try:
        count_query = supabase.table("linkedin_leads").select("id", count="exact").eq("user_id", user_id)
        if search_id:
            count_query = count_query.eq("search_id", search_id)
        if user_status:
            count_query = count_query.eq("user_status", user_status)
        if is_favorite is not None:
            count_query = count_query.eq("is_favorite", is_favorite)
        if search:
            count_query = count_query.ilike("full_name", f"%{search}%")
        total = count_query.execute().count or 0

        data_query = supabase.table("linkedin_leads").select("*").eq("user_id", user_id)
        if search_id:
            data_query = data_query.eq("search_id", search_id)
        if user_status:
            data_query = data_query.eq("user_status", user_status)
        if is_favorite is not None:
            data_query = data_query.eq("is_favorite", is_favorite)
        if search:
            data_query = data_query.ilike("full_name", f"%{search}%")

        response = (
            data_query.order("created_at", desc=True)
            .range(offset, offset + per_page - 1)
            .execute()
        )
        return {
            "items": response.data or [],
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": max(1, math.ceil(total / per_page)) if total else 0,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch leads: {str(e)}")


@router.patch("/leads/{lead_id}")
async def update_linkedin_lead(
    lead_id: str,
    update: LinkedInLeadUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    """Update status / favorite / notes of a LinkedIn lead."""
    supabase = get_supabase_admin()
    patch = update.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(status_code=400, detail="Nothing to update")

    try:
        response = (
            supabase.table("linkedin_leads")
            .update(patch)
            .eq("id", lead_id)
            .eq("user_id", current_user["id"])
            .execute()
        )
        if not response.data:
            raise HTTPException(status_code=404, detail="Lead not found")
        return response.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update lead: {str(e)}")


@router.delete("/leads/{lead_id}")
async def delete_linkedin_lead(
    lead_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete a LinkedIn lead."""
    supabase = get_supabase_admin()

    try:
        response = (
            supabase.table("linkedin_leads")
            .delete()
            .eq("id", lead_id)
            .eq("user_id", current_user["id"])
            .execute()
        )
        if not response.data:
            raise HTTPException(status_code=404, detail="Lead not found")
        return {"message": "Lead deleted", "id": lead_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete lead: {str(e)}")