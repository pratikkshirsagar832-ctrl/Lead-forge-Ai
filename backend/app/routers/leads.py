"""
LeadForge AI — Leads Router

Endpoints:
  GET    /api/leads              — list leads (paginated + filtered)
  GET    /api/leads/export       — export leads as CSV
  GET    /api/leads/{id}         — lead detail
  PATCH  /api/leads/{id}/status  — update lead status
  PATCH  /api/leads/{id}/notes   — update lead notes
  PATCH  /api/leads/{id}/favorite — toggle favorite
"""

import csv
import io
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.database import get_supabase_admin
from app.middleware.auth_middleware import get_current_user
from app.schemas.lead import (
    LeadDetail,
    LeadFavoriteUpdate,
    LeadListItem,
    LeadNotesUpdate,
    LeadPaginatedResponse,
    LeadStatusUpdate,
)

router = APIRouter(prefix="/api/leads", tags=["Leads"])


@router.get("", response_model=LeadPaginatedResponse)
async def list_leads(
    search_id: Optional[str] = Query(None, description="Filter by search ID"),
    lead_category: Optional[str] = Query(None, description="Filter by category (hot/warm/skip)"),
    user_status: Optional[str] = Query(None, description="Filter by user status"),
    is_favorite: Optional[bool] = Query(None, description="Filter favorites only"),
    sort_by: str = Query("created_at", description="Sort field"),
    sort_order: str = Query("desc", description="Sort order (asc/desc)"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """List leads with filtering, sorting, and pagination."""
    supabase = get_supabase_admin()
    user_id = current_user["id"]
    offset = (page - 1) * per_page

    try:
        # Build query for count
        count_query = supabase.table("leads").select("id", count="exact").eq("user_id", user_id)
        if search_id:
            count_query = count_query.eq("search_id", search_id)
        if lead_category:
            count_query = count_query.eq("lead_category", lead_category)
        if user_status:
            count_query = count_query.eq("user_status", user_status)
        if is_favorite is not None:
            count_query = count_query.eq("is_favorite", is_favorite)

        count_resp = count_query.execute()
        total = count_resp.count or 0
        total_pages = math.ceil(total / per_page) if total > 0 else 0

        # Build query for data
        data_query = supabase.table("leads").select("*").eq("user_id", user_id)
        if search_id:
            data_query = data_query.eq("search_id", search_id)
        if lead_category:
            data_query = data_query.eq("lead_category", lead_category)
        if user_status:
            data_query = data_query.eq("user_status", user_status)
        if is_favorite is not None:
            data_query = data_query.eq("is_favorite", is_favorite)

        # Sort
        desc = sort_order.lower() == "desc"
        data_query = data_query.order(sort_by, desc=desc)

        # Paginate
        data_query = data_query.range(offset, offset + per_page - 1)
        response = data_query.execute()

        items = []
        for lead in (response.data or []):
            lead["has_pitch"] = bool(lead.get("ai_pitch"))
            items.append(LeadListItem(**lead))

        return LeadPaginatedResponse(
            items=items,
            total=total,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch leads: {str(e)}")


@router.get("/export")
async def export_leads_csv(
    search_id: Optional[str] = Query(None, description="Filter by search ID"),
    lead_category: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Export leads as a CSV file."""
    supabase = get_supabase_admin()
    user_id = current_user["id"]

    try:
        query = supabase.table("leads").select("*").eq("user_id", user_id)
        if search_id:
            query = query.eq("search_id", search_id)
        if lead_category:
            query = query.eq("lead_category", lead_category)

        query = query.order("created_at", desc=True)
        response = query.execute()
        leads = response.data or []

        # Generate CSV
        output = io.StringIO()
        fieldnames = [
            "business_name", "category", "full_address", "phone",
            "email_found", "website_url", "rating", "total_reviews",
            "google_maps_link", "lead_category", "website_health_score",
            "user_status", "user_notes", "is_favorite", "ai_pitch",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for lead in leads:
            writer.writerow(lead)

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=leads_export.csv"},
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to export leads: {str(e)}")


@router.get("/{lead_id}", response_model=LeadDetail)
async def get_lead_detail(
    lead_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get full lead details."""
    supabase = get_supabase_admin()

    try:
        response = (
            supabase.table("leads")
            .select("*")
            .eq("id", lead_id)
            .eq("user_id", current_user["id"])
            .single()
            .execute()
        )
        if not response.data:
            raise HTTPException(status_code=404, detail="Lead not found")
        return response.data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail="Lead not found")


@router.patch("/{lead_id}/status")
async def update_lead_status(
    lead_id: str,
    update: LeadStatusUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Update the user-defined status of a lead."""
    supabase = get_supabase_admin()

    try:
        response = (
            supabase.table("leads")
            .update({"user_status": update.user_status})
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
        raise HTTPException(status_code=500, detail=f"Failed to update status: {str(e)}")


@router.patch("/{lead_id}/notes")
async def update_lead_notes(
    lead_id: str,
    update: LeadNotesUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Update notes on a lead."""
    supabase = get_supabase_admin()

    try:
        response = (
            supabase.table("leads")
            .update({"user_notes": update.user_notes})
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
        raise HTTPException(status_code=500, detail=f"Failed to update notes: {str(e)}")


@router.patch("/{lead_id}/favorite")
async def toggle_lead_favorite(
    lead_id: str,
    update: LeadFavoriteUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Toggle the favorite status of a lead."""
    supabase = get_supabase_admin()

    try:
        response = (
            supabase.table("leads")
            .update({"is_favorite": update.is_favorite})
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
        raise HTTPException(status_code=500, detail=f"Failed to update favorite: {str(e)}")
