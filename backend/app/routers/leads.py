"""
Hyperclients — Leads Router

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
import logging
import math
from typing import Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query
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
from app.services.analyzer_service import analyze_website

router = APIRouter(prefix="/api/leads", tags=["Leads"])


@router.get("", response_model=LeadPaginatedResponse)
async def list_leads(
    search_id: Optional[str] = Query(None, description="Filter by search ID"),
    source: Optional[str] = Query(None, description="Filter by source (google_maps/linkedin)"),
    post_type: Optional[str] = Query(None, description="Filter LinkedIn leads by post type (buyer/agency_wanted)"),
    lead_category: Optional[str] = Query(None, description="Filter by category (hot/warm)"),
    user_status: Optional[str] = Query(None, description="Filter by user status"),
    is_favorite: Optional[bool] = Query(None, description="Filter favorites only"),
    search: Optional[str] = Query(None, description="Search business name"),
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
        if source:
            count_query = count_query.eq("source", source)
        if post_type:
            count_query = count_query.eq("post_type", post_type)
        if lead_category:
            count_query = count_query.eq("lead_category", lead_category)
        if user_status:
            count_query = count_query.eq("user_status", user_status)
        if is_favorite is not None:
            count_query = count_query.eq("is_favorite", is_favorite)
        if search:
            count_query = count_query.ilike("business_name", f"%{search}%")

        count_resp = count_query.execute()
        total = count_resp.count or 0
        total_pages = math.ceil(total / per_page) if total > 0 else 0

        # Build query for data
        data_query = supabase.table("leads").select("*").eq("user_id", user_id)
        if search_id:
            data_query = data_query.eq("search_id", search_id)
        if source:
            data_query = data_query.eq("source", source)
        if post_type:
            data_query = data_query.eq("post_type", post_type)
        if lead_category:
            data_query = data_query.eq("lead_category", lead_category)
        if user_status:
            data_query = data_query.eq("user_status", user_status)
        if is_favorite is not None:
            data_query = data_query.eq("is_favorite", is_favorite)
        if search:
            data_query = data_query.ilike("business_name", f"%{search}%")

        # Sort
        ALLOWED_SORT_FIELDS = {"created_at", "updated_at", "ai_confidence_score", "business_name", "lead_category", "user_status"}
        if sort_by not in ALLOWED_SORT_FIELDS:
            sort_by = "created_at"
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


EXPORT_MAX_ROWS = 10000
CSV_EXPORT_PLANS = {"pro", "agency"}


@router.get("/export")
async def export_leads_csv(
    search_id: Optional[str] = Query(None, description="Filter by search ID"),
    source: Optional[str] = Query(None, description="Filter by source (google_maps/linkedin)"),
    post_type: Optional[str] = Query(None, description="Filter LinkedIn leads by post type (buyer/agency_wanted)"),
    lead_category: Optional[str] = Query(None),
    user_status: Optional[str] = Query(None),
    is_favorite: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Export leads as a CSV file (max 10,000 rows). Pro & Agency plans only."""
    from app.services.plans import resolve_effective_subscription
    supabase = get_supabase_admin()
    user_id = current_user["id"]

    plan_id = resolve_effective_subscription(supabase, user_id)["plan_id"]
    if plan_id not in CSV_EXPORT_PLANS:
        raise HTTPException(status_code=403, detail={
            "message": "CSV export is available on Pro and Agency plans",
            "upgrade_url": "/pricing",
        })

    try:
        query = supabase.table("leads").select("*").eq("user_id", user_id)
        if search_id:
            query = query.eq("search_id", search_id)
        if source:
            query = query.eq("source", source)
        if post_type:
            query = query.eq("post_type", post_type)
        if lead_category:
            query = query.eq("lead_category", lead_category)
        if user_status:
            query = query.eq("user_status", user_status)
        if is_favorite is not None:
            query = query.eq("is_favorite", is_favorite)
        if search:
            query = query.ilike("business_name", f"%{search}%")

        query = query.order("created_at", desc=True).limit(EXPORT_MAX_ROWS)
        response = query.execute()
        leads = response.data or []

        output = io.StringIO()
        fieldnames = [
            "source", "business_name", "category", "full_address", "phone",
            "email_found", "website_url", "rating", "total_reviews",
            "google_maps_link", "lead_category", "website_health_score",
            "headline", "linkedin_url", "post_url", "post_text",
            "connections_count", "posted_at", "post_type",
            "user_status", "user_notes", "is_favorite", "ai_pitch",
            "ai_confidence_score", "ai_qualified", "ai_reason",
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


@router.post("/{lead_id}/analyze-website")
async def analyze_lead_website(
    lead_id: str,
    current_user: dict = Depends(get_current_user),
):
    """On-demand website analysis for a warm lead."""
    supabase = get_supabase_admin()

    try:
        lead_resp = (
            supabase.table("leads")
            .select("id, website_url, business_name, lead_category")
            .eq("id", lead_id)
            .eq("user_id", current_user["id"])
            .limit(1)
            .execute()
        )
        if not lead_resp.data or len(lead_resp.data) == 0:
            raise HTTPException(status_code=404, detail="Lead not found")

        lead = lead_resp.data[0]
        url = lead.get("website_url", "")
        if not url:
            raise HTTPException(status_code=400, detail="Lead has no website URL")

        result = await analyze_website(url)

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

        update_data = {
            "website_health_score": result.get("overall_score", 0),
            "lead_category": result.get("category", "warm"),
        }
        emails = result.get("emails_found", [])
        if emails and not lead.get("email_found"):
            update_data["email_found"] = emails[0]
        supabase.table("leads").update(update_data).eq("id", lead_id).eq("user_id", current_user["id"]).execute()

        return {
            "status": "ok",
            "data": result,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to analyze website for lead {lead_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


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
            .limit(1)
            .execute()
        )
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="Lead not found")

        lead = response.data[0]

        # Fetch associated website analyses
        try:
            analysis_resp = (
                supabase.table("website_analyses")
                .select("*")
                .eq("lead_id", lead_id)
                .execute()
            )
            if analysis_resp.data:
                lead["website_analyses"] = analysis_resp.data
        except Exception as e:
            logger.warning(f"Failed to fetch analysis for lead {lead_id}: {e}")

        return lead
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching lead {lead_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


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
