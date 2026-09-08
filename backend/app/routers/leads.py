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
    """List leads with filtering, sorting, and pagination.

    Combines Google-Maps leads (owned directly via `leads.user_id`) with
    LinkedIn leads (`ha_leads`, which has NO user_id — the user owns the
    search the lead belongs to, so we join through `searches.id`). This is
    the fix for LinkedIn leads silently missing from the Leads Pipeline.
    """
    supabase = get_supabase_admin()
    user_id = current_user["id"]
    offset = (page - 1) * per_page

    src = (source or "").lower()
    include_maps = src in ("", "google_maps", "all")
    include_li = src in ("", "linkedin", "all")

    items: list[dict] = []
    total = 0

    # ---- Google Maps leads (`leads` table, owned by user) ------------------
    if include_maps:
        try:
            count_query = supabase.table("leads").select("id", count="exact").eq("user_id", user_id)
            data_query = supabase.table("leads").select("*").eq("user_id", user_id)
            if search_id:
                count_query = count_query.eq("search_id", search_id)
                data_query = data_query.eq("search_id", search_id)
            if lead_category:
                count_query = count_query.eq("lead_category", lead_category)
                data_query = data_query.eq("lead_category", lead_category)
            if user_status:
                count_query = count_query.eq("user_status", user_status)
                data_query = data_query.eq("user_status", user_status)
            if is_favorite is not None:
                count_query = count_query.eq("is_favorite", is_favorite)
                data_query = data_query.eq("is_favorite", is_favorite)
            if search:
                count_query = count_query.ilike("business_name", f"%{search}%")
                data_query = data_query.ilike("business_name", f"%{search}%")

            total += count_query.execute().count or 0

            ALLOWED_SORT_FIELDS = {"created_at", "ai_confidence_score", "business_name", "lead_category", "user_status"}
            s_by = sort_by if sort_by in ALLOWED_SORT_FIELDS else "created_at"
            desc = sort_order.lower() == "desc"
            # Fetch up to a page window per source, then merge in Python below.
            maps_items = data_query.order(s_by, desc=desc).limit(5000).execute().data or []
            items.extend(maps_items)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch leads: {str(e)}")

    # ---- LinkedIn leads (`ha_leads`) owned via searches.id -----------------
    if include_li:
        try:
            # Fetch the searches rows this user owns (LinkedIn only) to scope
            # ha_leads ownership, since ha_leads has no user_id column.
            s_query = supabase.table("searches").select("id").eq("user_id", user_id).eq("source", "linkedin")
            if search_id:
                s_query = s_query.eq("id", search_id)
            s_rows = s_query.execute().data or []
            li_ids = [r["id"] for r in s_rows]
            li_items: list[dict] = []
            if li_ids:
                for chunk in _chunks(li_ids, 200):
                    q = supabase.table("ha_leads").select("*").in_("search_id", chunk)
                    if post_type:
                        lt = {"buyer": "need_freelancer", "agency_wanted": "our_agency"}.get(post_type)
                        if lt:
                            q = q.eq("lead_type", lt)
                    if user_status:
                        q = q.eq("status", user_status)
                    li_items.extend(q.order("post_date", desc=True).limit(5000).execute().data or [])
            # Map to the LeadListItem shape the frontend expects.
            for r in li_items:
                if search and search.lower() not in (r.get("author_name") or "").lower():
                    continue
                items.append(_map_ha_lead(r))
            total += len(li_items)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch LinkedIn leads: {str(e)}")

    # ---- Merge across sources, dedupe, sort, paginate ----------------------
    deduped: dict[str, dict] = {}
    for it in items:
        key = it.get("post_url") or it.get("id")
        if key is not None:
            # Prefer an existing LinkedIn-row over a maps-row for the same post.
            deduped.setdefault(key, it)
    merged = list(deduped.values())

    s_by = sort_by if sort_by in ("created_at", "ai_confidence_score", "business_name", "lead_category", "user_status") else "created_at"
    desc = sort_order.lower() == "desc"

    def _sort_key(x: dict):
        if s_by == "business_name":
            v = x.get("business_name") or x.get("author_name") or ""
            return (v or "").lower()
        if s_by == "lead_category":
            return {"hot": 0, "warm": 1}.get(x.get("lead_category"), 2)
        if s_by == "ai_confidence_score":
            return x.get("ai_confidence_score") or 0
        return x.get("created_at") or ""

    merged.sort(key=_sort_key, reverse=desc)

    total = len(merged)
    paged = merged[offset: offset + per_page]
    for lead in paged:
        lead["has_pitch"] = bool(lead.get("ai_pitch"))

    # Validate against the response schema (coerce defaulted/converted fields).
    validated = [LeadListItem(**_coerce_lead(lead)) for lead in paged]

    return LeadPaginatedResponse(
        items=validated,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=math.ceil(total / per_page) if total > 0 else 0,
    )


def _coerce_lead(d: dict) -> dict:
    """Normalize a raw DB row (Maps `leads` or LinkedIn `ha_leads`) to values
    the LeadListItem schema accepts. Without this, a null lead_category /
    connections_count or a float website_health_score 500s the list."""
    out = dict(d)
    if out.get("lead_category") is None:
        # Schema requires a non-optional str; 'warm' is hidden in the UI for
        # LinkedIn leads (which have no reliable category).
        out["lead_category"] = "warm"
    if out.get("connections_count") is None:
        out["connections_count"] = 0
    else:
        try:
            out["connections_count"] = int(out["connections_count"])
        except (TypeError, ValueError):
            out["connections_count"] = 0
    if out.get("website_health_score") is not None:
        try:
            out["website_health_score"] = int(round(float(out["website_health_score"])))
        except (TypeError, ValueError):
            out["website_health_score"] = None
    if out.get("total_reviews") is None:
        out["total_reviews"] = 0
    if out.get("rating") is not None:
        try:
            out["rating"] = float(out["rating"])
        except (TypeError, ValueError):
            out["rating"] = None
    if out.get("source") is None:
        out["source"] = "google_maps"
    return out


def _chunks(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _map_ha_lead(row: dict) -> dict:
    """Map a `ha_leads` row to the LeadListItem shape the frontend renders."""
    lead_type = row.get("lead_type") or ""
    post_type = {
        "need_freelancer": "buyer",
        "our_agency": "agency_wanted",
    }.get(lead_type, lead_type or "")

    score = row.get("overall_quality_score")
    try:
        score = float(score) if score is not None else None
    except (TypeError, ValueError):
        score = None

    return {
        "id": row.get("id"),
        "search_id": row.get("search_id"),
        "source": "linkedin",
        "business_name": row.get("author_name") or "Unknown LinkedIn Post",
        "category": None,
        "full_address": None,
        "phone": None,
        "email_found": row.get("notes") or "",
        "website_url": None,
        "rating": None,
        "total_reviews": 0,
        # No reliable category for LinkedIn leads — leave unset so the UI can
        # omit the Warm/Hot tag instead of guessing.
        "lead_category": None,
        "website_health_score": round(score * 100) if (score is not None and score <= 1) else (score if score is not None else None),
        "headline": row.get("author_name") or "",
        "linkedin_url": row.get("author_profile_url") or None,
        "post_url": row.get("post_url") or None,
        "post_text": row.get("post_text") or None,
        "profile_picture_url": None,
        "connections_count": None,
        "posted_at": row.get("post_date") or None,
        "post_type": post_type or None,
        "ai_confidence_score": None,
        "ai_pitch": None,
        "user_status": row.get("status") or "new",
        "user_notes": row.get("notes") or "",
        "is_favorite": False,
        "has_pitch": False,
        "created_at": row.get("created_at") or None,
    }


def _map_ha_lead_detail(row: dict, user_id: str) -> dict:
    """Map a `ha_leads` row to the LeadDetail schema (LinkedIn lead page)."""
    d = _coerce_lead(_map_ha_lead(row))
    d.update({
        "user_id": user_id,
        "google_key": None,
        "google_maps_link": None,
        "photos": [],
        "business_hours": {},
        "description": None,
        "estimated_deal_value": None,
        "website_analyses": [],
    })
    return d


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

        # CSV formula-injection guard: spreadsheet apps execute cells that
        # start with = + - @ (and tab/CR variants). Escape a leading special
        # character so exporter data can never become a formula.
        def _sanitize_cell(value):
            if value is None:
                return ""
            s = str(value)
            if s and s.lstrip()[0] in ("=", "+", "-", "@", "\t", "\r"):
                return "'" + s
            return s

        for lead in leads:
            writer.writerow({k: _sanitize_cell(v) for k, v in lead.items()})

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

    # Cost guard: each call pays a Scrapling crawl + OpenAI run. Cap it per user.
    from app.utils.rate_limit import check_rate_limit
    if not check_rate_limit(f"analyze:{current_user['id']}", limit=10, window_seconds=60):
        raise HTTPException(status_code=429, detail="Too many website analyses. Wait a minute and try again.")

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

        # On a genuine analyzer failure the result carries raw_analysis.error
        # with placeholder score 0 / category hot — surface the failure to the
        # user and do NOT overwrite a stored score/category with that placeholder.
        raw = result.get("raw_analysis", {}) or {}
        if raw.get("error"):
            logger.warning(f"Analyzer failed for {url}; keeping existing lead score/category")
            raise HTTPException(status_code=502, detail=raw["error"][:300])

        # The DB CHECK only allows 'hot'/'warm'. The analyzer may return
        # 'skip' (good site, low opportunity) — fold it into warm rather than
        # failing the UPDATE with a constraint violation.
        ai_category = result.get("category", "warm")
        category = "warm" if ai_category in ("skip", "warm") else ai_category

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
            "lead_category": category,
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
    """Get full lead details.

    Handles BOTH sources: Google-Maps leads live in `leads`, LinkedIn leads
    live in `ha_leads` (which has no user_id — ownership is via the search row
    it shares its id with). Without the ha_leads fallback, clicking a LinkedIn
    lead 404'd ("lead can't load").
    """
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
        if response.data and len(response.data) > 0:
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

        # Not a Google-Maps lead — fall back to LinkedIn `ha_leads`.
        ha = (
            supabase.table("ha_leads")
            .select("*")
            .eq("id", lead_id)
            .limit(1)
            .execute()
        )
        if ha.data and len(ha.data) > 0:
            ha_row = ha.data[0]
            srow = (
                supabase.table("searches")
                .select("user_id")
                .eq("id", ha_row.get("search_id"))
                .limit(1)
                .execute()
            )
            if srow.data and srow.data[0].get("user_id") == current_user["id"]:
                return _map_ha_lead_detail(ha_row, current_user["id"])

        raise HTTPException(status_code=404, detail="Lead not found")
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
