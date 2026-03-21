"""
LeadForge AI — Dashboard Router

Endpoints:
  GET /api/dashboard/stats — get dashboard statistics
"""

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_supabase_admin
from app.middleware.auth_middleware import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/stats")
async def get_dashboard_stats(
    current_user: dict = Depends(get_current_user),
):
    """
    Get dashboard statistics for the current user.
    Uses the get_dashboard_stats RPC function.
    """
    supabase = get_supabase_admin()
    user_id = current_user["id"]

    try:
        response = supabase.rpc("get_dashboard_stats", {"p_user_id": user_id}).execute()
        if response.data is not None:
            return response.data
        return {
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch dashboard stats: {str(e)}")
