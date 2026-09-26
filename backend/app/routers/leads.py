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

_ALLOWED_USER_STATUS = {"new", "contacted", "replied", "converted", "lost"}
_ALLOWED_LEAD_CATEGORY = {"hot", "warm"}
_ALLOWED_SOURCE = {"", "google_maps", "linkedin", "all"}


def _sanitize_search(value: str | None, max_len: int = 100) -> str | None:
    if not value:
        return None
    v = value.strip()[:max_len]
    if not v:
        return None
    # Escape PostgREST/ilike wildcards so user input can't broaden the match.
    return v.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("", response_model=LeadPaginatedResponse)
def list_leads(
    search_id: Optional[str] = Query(None, description="Filter by search ID"),
    source: Optional[str] = Query(None, description="Filter by source (google_maps/linkedin)"),
    post_type: Optional[str] = Query(None, description="Filter LinkedIn leads by post type (buyer/agency)"),
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
    if src not in _ALLOWED_SOURCE:
        src = ""
    include_maps = src in ("", "google_maps", "all")
    include_li = src in ("", "linkedin", "all")
    # Allowlist filters to prevent PostgREST filter injection via `or_`.
    if user_status is not None and user_status not in _ALLOWED_USER_STATUS:
        raise HTTPException(status_code=400, detail="Invalid user_status")
    if lead_category is not None and lead_category not in _ALLOWED_LEAD_CATEGORY:
        raise HTTPException(status_code=400, detail="Invalid lead_category")
    if post_type is not None and post_type not in _ALLOWED_POST_TYPE:
        raise HTTPException(status_code=400, detail="Invalid post_type")
    safe_search = _sanitize_search(search)

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
            if safe_search:
                count_query = count_query.ilike("business_name", f"%{safe_search}%")
                data_query = data_query.ilike("business_name", f"%{safe_search}%")

            total += count_query.execute().count or 0

            ALLOWED_SORT_FIELDS = {"created_at", "ai_confidence_score", "business_name", "lead_category", "user_status"}
            s_by = sort_by if sort_by in ALLOWED_SORT_FIELDS else "created_at"
            desc = sort_order.lower() == "desc"
            # Fetch up to a page window per source, then merge in Python below.
            maps_items = data_query.order(s_by, desc=desc).limit(5000).execute().data or []
            items.extend(maps_items)
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("Failed to fetch maps leads for user %s: %s", user_id[:8], e)
            raise HTTPException(status_code=500, detail="Failed to fetch leads")

    # ---- LinkedIn leads (`ha_leads`) owned via searches.id -----------------
    if include_li:
        try:
            items.extend(_fetch_linkedin_leads(
                supabase, user_id,
                search_id=search_id,
                post_type=post_type,
                user_status=user_status,
                is_favorite=is_favorite,
                search=safe_search,
            ))
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("Failed to fetch LinkedIn leads for user %s: %s", user_id[:8], e)
            raise HTTPException(status_code=500, detail="Failed to fetch LinkedIn leads")

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


def _fetch_linkedin_leads(
    supabase,
    user_id: str,
    *,
    search_id: Optional[str] = None,
    post_type: Optional[str] = None,
    user_status: Optional[str] = None,
    is_favorite: Optional[bool] = None,
    search: Optional[str] = None,
    limit: int = 5000,
) -> list[dict]:
    """This user's LinkedIn (`ha_leads`) leads, mapped to LeadListItem shape.

    Shared by the list AND export endpoints: the export used to read only the
    Google-Maps `leads` table, so every LinkedIn lead was silently missing from
    a Pro/Agency customer's CSV (and `source=linkedin` exported nothing).

    Ownership: ha_leads has no user_id — the user owns the parent `searches`
    row. `is_favorite` is filtered in Python rather than in the query because
    the column only exists after migration v10, and a missing column would fail
    the whole request for every user.
    """
    s_query = (
        supabase.table("searches")
        .select("id, lead_types")
        .eq("user_id", user_id)
        .eq("source", "linkedin")
    )
    if search_id:
        s_query = s_query.eq("id", search_id)
    s_rows = s_query.execute().data or []
    li_ids = [r["id"] for r in s_rows]
    # The role the user picked for each search (Freelancer / Agency) decides
    # the badge - see _post_type_for.
    role_by_search = {r["id"]: r.get("lead_types") for r in s_rows}
    li_items: list[dict] = []
    if li_ids:
        for chunk in _chunks(li_ids, 200):
            q = supabase.table("ha_leads").select("*").in_("search_id", chunk)
            if user_status:
                # user_status exists after migration v10; before it,
                # fall back to the engine lifecycle column.
                q = q.or_(f"user_status.eq.{user_status},status.eq.{user_status}")
            li_items.extend(
                q.order("post_date", desc=True).limit(limit).execute().data or []
            )

    out: list[dict] = []
    for r in li_items:
        if search and search.lower() not in (r.get("author_name") or "").lower():
            continue
        mapped = _map_ha_lead(r, role_by_search.get(r.get("search_id")))
        if is_favorite is not None and bool(mapped.get("is_favorite")) != bool(is_favorite):
            continue
        # Filtered after mapping: the type comes from the search's role first.
        if post_type and mapped.get("post_type") != post_type:
            continue
        out.append(mapped)
    return out


def _coerce_lead(d: dict) -> dict:
    """Normalize a raw DB row (Maps `leads` or LinkedIn `ha_leads`) to values
    the LeadListItem schema accepts. Without this, a null lead_category /
    connections_count or a float website_health_score 500s the list."""
    out = dict(d)
    if not out.get("business_name"):
        # LeadDetail requires a string; a NULL business_name would 500 the page.
        out["business_name"] = "Unknown Business"
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


def _owned_ha_lead(supabase, lead_id: str, user_id: str) -> bool:
    """True when `lead_id` is a LinkedIn ha_leads row owned by this user
    (ownership via the parent searches row — ha_leads has no user_id)."""
    try:
        ha = (
            supabase.table("ha_leads")
            .select("id, search_id")
            .eq("id", lead_id)
            .limit(1)
            .execute()
        )
        if not ha.data:
            return False
        srow = (
            supabase.table("searches")
            .select("user_id")
            .eq("id", ha.data[0].get("search_id"))
            .limit(1)
            .execute()
        )
        return bool(srow.data and srow.data[0].get("user_id") == user_id)
    except Exception:
        return False


_ALLOWED_POST_TYPE = ("buyer", "agency")
# Engine lead_type -> the post_type the frontend badges ("buyer" renders as
# "Freelancer Needed", "agency" as "Agency Needed").
_POST_TYPE_BY_LEAD_TYPE = {"need_freelancer": "buyer", "need_agency": "agency", "our_agency": "agency"}
_POST_TYPE_BY_ROLE = {"freelancer": "buyer", "buyer": "buyer", "agency": "agency"}


def post_type_for(row: dict, search_lead_types=None) -> str:
    """Badge type of a LinkedIn lead.

    The role the user SELECTED for the search wins (a search runs in exactly
    one lane - Freelancer or Agency - and every lead it saves belongs to that
    lane); the stored lead_type is the fallback for rows without a search
    role. Every lead used to be mapped to "buyer", so Agency searches showed
    "Freelancer Needed" everywhere.
    """
    for role in search_lead_types or []:
        mapped = _POST_TYPE_BY_ROLE.get(str(role or "").strip().lower())
        if mapped:
            return mapped
    return _POST_TYPE_BY_LEAD_TYPE.get(row.get("lead_type") or "", "buyer")


def _map_ha_lead(row: dict, search_lead_types=None) -> dict:
    """Map a `ha_leads` row to the LeadListItem shape the frontend renders."""
    post_type = post_type_for(row, search_lead_types)

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
        # No email enrichment in the current engine — reserved for a future
        # column; `notes` is the USER's notes field, never an email.
        "email_found": "",
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
        # Exact publish time (v18) when known, else the day-level post_date.
        "posted_at": row.get("posted_at") or row.get("post_date") or None,
        "post_type": post_type or None,
        # 0-1 confidence saved by POST /api/ai/pitch (None until generated).
        "ai_confidence_score": row.get("ai_confidence_score"),
        "ai_pitch": row.get("ai_pitch") or None,
        # Engine `status` is the lifecycle default; user_status mirrors it so
        # PATCH /status + list filters read/write the same column.
        "user_status": row.get("user_status") or row.get("status") or "new",
        "user_notes": row.get("user_notes") or "",
        "is_favorite": bool(row.get("is_favorite") or False),
        "has_pitch": bool(row.get("ai_pitch")),
        "created_at": row.get("created_at") or None,
    }


def _map_ha_lead_detail(row: dict, user_id: str, search_lead_types=None) -> dict:
    """Map a `ha_leads` row to the LeadDetail schema (LinkedIn lead page)."""
    d = _coerce_lead(_map_ha_lead(row, search_lead_types))
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
    post_type: Optional[str] = Query(None, description="Filter LinkedIn leads by post type (buyer/agency)"),
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
        # Same source selection as GET /api/leads: the export must contain the
        # same leads the user can see in the dashboard.
        src = (source or "").lower()
        include_maps = src in ("", "google_maps", "all")
        include_li = src in ("", "linkedin", "all")

        leads: list[dict] = []
        if include_maps:
            query = supabase.table("leads").select("*").eq("user_id", user_id)
            if search_id:
                query = query.eq("search_id", search_id)
            if src == "google_maps":
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
            leads.extend(query.execute().data or [])

        # LinkedIn rows live in ha_leads; without this the export silently
        # omitted them (source=linkedin produced a header-only CSV).
        if include_li:
            try:
                leads.extend(_fetch_linkedin_leads(
                    supabase, user_id,
                    search_id=search_id,
                    post_type=post_type,
                    user_status=user_status,
                    is_favorite=is_favorite,
                    search=search,
                    limit=EXPORT_MAX_ROWS,
                ))
            except Exception as li_err:
                # Never fail a Maps export because the LinkedIn table is unhappy.
                logger.warning(f"LinkedIn rows omitted from CSV export: {li_err}")

        leads = leads[:EXPORT_MAX_ROWS]

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

    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Failed to export leads: %s", e)
        raise HTTPException(status_code=500, detail="Failed to export leads")


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
        raise HTTPException(status_code=500, detail="Analysis failed")


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
            # Same coercion the list endpoint applies: raw rows can carry a
            # numeric score / NULL counters that the response schema rejects.
            lead = _coerce_lead(response.data[0])
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
                .select("user_id, lead_types")
                .eq("id", ha_row.get("search_id"))
                .limit(1)
                .execute()
            )
            if srow.data and srow.data[0].get("user_id") == current_user["id"]:
                return _map_ha_lead_detail(ha_row, current_user["id"], srow.data[0].get("lead_types"))

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
    """Update the user-defined status of a lead (Maps `leads` AND LinkedIn
    `ha_leads` — LinkedIn ownership resolves via the parent search row)."""
    supabase = get_supabase_admin()

    try:
        response = (
            supabase.table("leads")
            .update({"user_status": update.user_status})
            .eq("id", lead_id)
            .eq("user_id", current_user["id"])
            .execute()
        )
        if response.data:
            return response.data[0]
        # Not a Maps lead — LinkedIn `ha_leads` fallback (status column is the
        # same one the list filter reads, so filters stay consistent).
        if _owned_ha_lead(supabase, lead_id, current_user["id"]):
            resp = (
                supabase.table("ha_leads")
                .update({"status": update.user_status})
                .eq("id", lead_id)
                .execute()
            )
            if resp.data:
                row = dict(resp.data[0])
                row["user_status"] = row.get("status")
                return row
        raise HTTPException(status_code=404, detail="Lead not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Failed to update status for lead %s: %s", lead_id, e)
        raise HTTPException(status_code=500, detail="Failed to update status")


@router.patch("/{lead_id}/notes")
async def update_lead_notes(
    lead_id: str,
    update: LeadNotesUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Update notes on a lead (Maps `leads` AND LinkedIn `ha_leads`)."""
    supabase = get_supabase_admin()

    try:
        response = (
            supabase.table("leads")
            .update({"user_notes": update.user_notes})
            .eq("id", lead_id)
            .eq("user_id", current_user["id"])
            .execute()
        )
        if response.data:
            return response.data[0]
        if _owned_ha_lead(supabase, lead_id, current_user["id"]):
            resp = (
                supabase.table("ha_leads")
                .update({"user_notes": update.user_notes})
                .eq("id", lead_id)
                .execute()
            )
            if resp.data:
                row = dict(resp.data[0])
                row["user_notes"] = update.user_notes
                return row
        raise HTTPException(status_code=404, detail="Lead not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Failed to update notes for lead %s: %s", lead_id, e)
        raise HTTPException(status_code=500, detail="Failed to update notes")


@router.patch("/{lead_id}/favorite")
async def toggle_lead_favorite(
    lead_id: str,
    update: LeadFavoriteUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Toggle the favorite status of a lead (Maps `leads` AND LinkedIn
    `ha_leads`)."""
    supabase = get_supabase_admin()

    try:
        response = (
            supabase.table("leads")
            .update({"is_favorite": update.is_favorite})
            .eq("id", lead_id)
            .eq("user_id", current_user["id"])
            .execute()
        )
        if response.data:
            return response.data[0]
        if _owned_ha_lead(supabase, lead_id, current_user["id"]):
            try:
                resp = (
                    supabase.table("ha_leads")
                    .update({"is_favorite": update.is_favorite})
                    .eq("id", lead_id)
                    .execute()
                )
            except Exception as col_err:
                # ha_leads.is_favorite exists only after migration v10.
                if "is_favorite" in str(col_err) and "column" in str(col_err):
                    raise HTTPException(
                        status_code=503,
                        detail="Favorites for LinkedIn leads need a database update "
                               "(migration_ha_user_columns_v10.sql has not been applied).",
                    )
                raise
            if resp.data:
                row = dict(resp.data[0])
                row["is_favorite"] = update.is_favorite
                return row
        raise HTTPException(status_code=404, detail="Lead not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Failed to update favorite for lead %s: %s", lead_id, e)
        raise HTTPException(status_code=500, detail="Failed to update favorite")
