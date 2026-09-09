"""
Hyperclients — Dashboard Router

Endpoints:
  GET /api/dashboard/stats — get dashboard statistics
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_supabase_admin
from app.middleware.auth_middleware import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/stats")
async def get_dashboard_stats(
    current_user: dict = Depends(get_current_user),
):
    """
    Get dashboard statistics for the current user.

    The get_dashboard_stats RPC counts only the Google-Maps `leads` table, so
    LinkedIn (`ha_leads`) leads were invisible in every dashboard card. This
    merges the LinkedIn counts router-side (ownership via the user's LinkedIn
    `searches` rows — ha_leads has no user_id) on top of the RPC result, and
    degrades to the raw RPC/zero shape on any partial failure.
    """
    supabase = get_supabase_admin()
    user_id = current_user["id"]

    zero = {
        "total_searches": 0,
        "completed_searches": 0,
        "total_leads": 0,
        "hot_leads": 0,
        "warm_leads": 0,
        "skipped_leads": 0,
        "favorite_leads": 0,
        "contacted_leads": 0,
        "converted_leads": 0,
        "recent_searches": [],
    }
    try:
        response = supabase.rpc("get_dashboard_stats", {"p_user_id": user_id}).execute()
        stats = dict(response.data) if response.data is not None else dict(zero)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch dashboard stats: {str(e)}")

    # ---- LinkedIn counts (best-effort: never fail the whole endpoint) ------
    try:
        li_leads = 0
        li_hot = 0
        li_warm = 0
        li_favorites = 0
        s_rows = (
            supabase.table("searches")
            .select("id")
            .eq("user_id", user_id)
            .eq("source", "linkedin")
            .execute()
            .data or []
        )
        search_ids = [r["id"] for r in s_rows]
        if search_ids:
            for i in range(0, len(search_ids), 200):
                chunk = search_ids[i:i + 200]
                resp = (
                    supabase.table("ha_leads")
                    .select("id, overall_quality_score, is_favorite")
                    .in_("search_id", chunk)
                    .limit(5000)
                    .execute()
                )
                rows = resp.data or []
                li_leads += len(rows)
                li_favorites += sum(1 for r in rows if r.get("is_favorite"))
                for r in rows:
                    try:
                        score = float(r.get("overall_quality_score") or 0)
                    except (TypeError, ValueError):
                        continue
                    if score <= 1:
                        score *= 100  # normalize a 0-1 stored score to 0-100
                    if score >= 85:
                        li_hot += 1
                    elif score >= 50:
                        li_warm += 1
        stats["total_leads"] = int(stats.get("total_leads") or 0) + li_leads
        stats["hot_leads"] = int(stats.get("hot_leads") or 0) + li_hot
        stats["warm_leads"] = int(stats.get("warm_leads") or 0) + li_warm
        stats["favorite_leads"] = int(stats.get("favorite_leads") or 0) + li_favorites
        stats["linkedin_leads"] = li_leads
    except Exception as e:
        # Transient error: still expose the RPC's Maps-only numbers.
        logger.warning(f"LinkedIn stats merge failed: {e}")
        stats.setdefault("linkedin_leads", 0)

    return stats
