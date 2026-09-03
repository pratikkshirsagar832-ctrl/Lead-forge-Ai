"""
Hyperclients — HyperAgent Router (LinkedIn Agent)

Endpoints for the autonomous LinkedIn lead agent:
  POST /api/agent/runs          — start a new agent run (browses LinkedIn)
  GET  /api/agent/runs          — agent run history (paginated)
  GET  /api/agent/runs/{id}     — agent run detail
  GET  /api/agent/runs/{id}/status — lightweight polling status
  GET  /api/agent/runs/{id}/results — progressive lead fetch
"""

from datetime import datetime, timezone

import math

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

import logging

logger = logging.getLogger(__name__)

from app.database import get_supabase_admin
from app.middleware.auth_middleware import get_current_user
from app.middleware.usage_middleware import check_search_limit
from app.services.hyperagent_service import run_hyperagent_pipeline_fast

router = APIRouter(prefix="/api/agent", tags=["Agent"])

AGENT_SOURCE = "hyper_agent"


def _increment_daily_searches(supabase, user_id: str) -> None:
    try:
        from datetime import date
        today_str = datetime.now(timezone.utc).date().isoformat()
        existing = supabase.table("daily_usage").select("id,searches_run").eq("user_id", user_id).eq("date", today_str).limit(1).execute()
        rows = existing.data or []
        if rows:
            cur = int(rows[0].get("searches_run", 0) or 0)
            supabase.table("daily_usage").update({"searches_run": cur + 1}).eq("id", rows[0]["id"]).execute()
        else:
            supabase.table("daily_usage").insert({
                "user_id": user_id, "date": today_str, "searches_run": 1, "leads_generated": 0, "ai_calls": 0,
            }).execute()
    except Exception as e:
        logger.warning(f"Failed to increment daily searches: {e}")


@router.post("/runs", status_code=201)
async def create_agent_run(
    niche: str = Query(..., min_length=1, max_length=200),
    location: str = Query("", max_length=300),
    lead_type: str = Query("buyer", pattern="^(buyer|hiring|agency_wanted)$"),
    max_results: int = Query(20, ge=1, le=50),
    enrich_emails: bool = Query(True),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: dict = Depends(get_current_user),
):
    """Start a new agent run. Browses LinkedIn for matching leads."""
    supabase = get_supabase_admin()
    user_id = current_user["id"]
    query_term = niche.strip()

    # Monthly lead quota (linkedin source bucket)
    from app.services.plans import get_plan_row, resolve_effective_subscription
    effective = resolve_effective_subscription(supabase, user_id)
    plan = get_plan_row(supabase, effective["plan_id"])
    plan_limit = int(plan.get("linkedin_hq_leads_monthly", 0) or 0)
    month_str = datetime.now(timezone.utc).replace(day=1).date().isoformat()
    try:
        existing_usage = supabase.table("monthly_usage").select("linkedin_hq_generated").eq("user_id", user_id).eq("usage_month", month_str).limit(1).execute()
        used = int((existing_usage.data or [{}])[0].get("linkedin_hq_generated", 0) or 0)
    except Exception:
        used = 0
    remaining = max(0, plan_limit - used)
    if remaining <= 0:
        raise HTTPException(status_code=403, detail=f"Monthly lead limit reached ({plan_limit}/{plan_limit})")

    try:
        response = (
            supabase.table("searches")
            .insert({
                "user_id": user_id,
                "niche": query_term,
                "location": location or "LinkedIn",
                "source": AGENT_SOURCE,
                "status": "queued",
                "message": "Agent queued",
                "enrich_emails": enrich_emails,
                "max_results": max_results,
                "lead_types": [lead_type],
                "quota_source": "linkedin",
                "reserved_leads": min(max_results, remaining),
            })
            .execute()
        )
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=500, detail="Failed to create agent run")
        run = response.data[0]
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to create agent run: {exc}")
        raise HTTPException(status_code=500, detail="Failed to create agent run")

    _increment_daily_searches(supabase, user_id)

    background_tasks.add_task(
        run_hyperagent_pipeline_fast,
        search_id=run["id"],
        user_id=user_id,
        query=query_term,
        enrich_emails=enrich_emails,
        max_results=max_results,
        lead_types=[lead_type],
        location=location,
    )

    return run


@router.get("/runs")
async def get_agent_history(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """Agent run history for the current user."""
    supabase = get_supabase_admin()
    user_id = current_user["id"]
    offset = (page - 1) * per_page
    try:
        count_resp = (
            supabase.table("searches")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("source", AGENT_SOURCE)
            .execute()
        )
        total = count_resp.count or 0
        response = (
            supabase.table("searches")
            .select("*")
            .eq("user_id", user_id)
            .eq("source", AGENT_SOURCE)
            .order("created_at", desc=True)
            .range(offset, offset + per_page - 1)
            .execute()
        )
        items = [{
            "id": r.get("id"),
            "service": r.get("niche"),
            "country": r.get("location"),
            "status": r.get("status"),
            "progress_percent": r.get("progress_percent", 0) or 0,
            "message": r.get("message"),
            "total_results": r.get("total_results", 0) or 0,
            "hot_leads": r.get("hot_leads", 0) or 0,
            "warm_leads": r.get("warm_leads", 0) or 0,
            "emails_found": r.get("emails_found", 0) or 0,
            "created_at": r.get("created_at"),
            "completed_at": r.get("completed_at"),
            "lead_type": (",".join(r.get("lead_types") or [])) if r.get("lead_types") else None,
        } for r in (response.data or [])]
        return {"items": items, "total": total}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch agent history: {str(exc)}")


def _verify_owner(supabase, run_id: str, user_id: str) -> dict:
    resp = supabase.table("searches").select("*").eq("id", run_id).limit(1).execute()
    if not resp.data or len(resp.data) == 0:
        raise HTTPException(status_code=404, detail="Agent run not found")
    row = resp.data[0]
    if row.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return row


@router.get("/runs/{run_id}")
async def get_agent_run_detail(run_id: str, current_user: dict = Depends(get_current_user)):
    supabase = get_supabase_admin()
    row = _verify_owner(supabase, run_id, current_user["id"])
    return {
        "id": row["id"], "service": row.get("niche"), "country": row.get("location"),
        "status": row.get("status"), "progress_percent": row.get("progress_percent", 0) or 0,
        "message": row.get("message"), "total_results": row.get("total_results", 0) or 0,
        "hot_leads": row.get("hot_leads", 0) or 0, "warm_leads": row.get("warm_leads", 0) or 0,
        "skipped": row.get("skipped", 0) or 0, "emails_found": row.get("emails_found", 0) or 0,
        "error_message": row.get("error_message"), "created_at": row.get("created_at"),
        "completed_at": row.get("completed_at"), "lead_type": (",".join(row.get("lead_types") or [])) if row.get("lead_types") else None,
        "max_results": row.get("max_results"),
    }


@router.get("/runs/{run_id}/status")
async def get_agent_run_status(run_id: str, current_user: dict = Depends(get_current_user)):
    supabase = get_supabase_admin()
    resp = supabase.table("searches").select("*").eq("id", run_id).limit(1).execute()
    if not resp.data or len(resp.data) == 0:
        raise HTTPException(status_code=404, detail="Agent run not found")
    row = resp.data[0]
    if row.get("user_id") != current_user["id"]:
        raise HTTPException(status_code=404, detail="Agent run not found")

    hot = row.get("hot_leads", 0) or 0
    warm = row.get("warm_leads", 0) or 0
    skip = row.get("skipped", 0) or 0

    created_dt = None
    if row.get("created_at"):
        try:
            created_dt = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
        except Exception:
            created_dt = None
    comp_dt = None
    if row.get("completed_at"):
        try:
            comp_dt = datetime.fromisoformat(row["completed_at"].replace("Z", "+00:00"))
        except Exception:
            comp_dt = None
    elapsed = 0
    if created_dt:
        end_time = comp_dt or datetime.now(timezone.utc)
        elapsed = max(0, int((end_time - created_dt).total_seconds()))

    return {
        "id": row["id"],
        "status": row.get("status", "queued"),
        "progress_percent": row.get("progress_percent", 0) or 0,
        "message": row.get("message", ""),
        "total_results": row.get("total_results", 0) or 0,
        "hot_leads": hot, "warm_leads": warm, "skipped": skip,
        "emails_found": row.get("emails_found", 0) or 0,
        "processed_count": hot + warm + skip,
        "elapsed_seconds": elapsed,
        "started_at": row.get("created_at"),
        "completed_at": row.get("completed_at"),
        "error_message": row.get("error_message"),
        "requested_count": row.get("max_results"),
        "returned_count": row.get("total_results"),
        "lead_type": (",".join(row.get("lead_types") or [])) if row.get("lead_types") else None,
        "country": row.get("location"),
        "service": row.get("niche"),
    }


@router.get("/runs/{run_id}/results")
async def get_agent_run_results(
    run_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(4, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
):
    supabase = get_supabase_admin()
    resp = supabase.table("searches").select("user_id").eq("id", run_id).limit(1).execute()
    if not resp.data or len(resp.data) == 0:
        raise HTTPException(status_code=404, detail="Agent run not found")
    if resp.data[0].get("user_id") != current_user["id"]:
        raise HTTPException(status_code=404, detail="Agent run not found")

    offset = (page - 1) * per_page
    count_resp = supabase.table("leads").select("id", count="exact").eq("search_id", run_id).execute()
    total = count_resp.count or 0
    response = (
        supabase.table("leads")
        .select("id, source, business_name, category, full_address, phone, email_found, website_url, rating, total_reviews, lead_category, website_health_score, headline, linkedin_url, post_url, post_text, profile_picture_url, connections_count, posted_at, post_type, ai_confidence_score, ai_pitch, user_status, is_favorite")
        .eq("search_id", run_id)
        .order("created_at", desc=False)
        .range(offset, offset + per_page - 1)
        .execute()
    )
    return {
        "items": response.data or [], "total": total, "page": page,
        "per_page": per_page, "total_pages": max(1, math.ceil(total / per_page)),
    }
