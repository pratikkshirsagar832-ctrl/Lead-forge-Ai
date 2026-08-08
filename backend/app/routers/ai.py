"""
Hyperclients — AI Router

Endpoints:
  POST /api/ai/pitch/{lead_id}           — generate an AI pitch for a lead
  POST /api/ai/website-message/{lead_id} — generate a short WhatsApp outreach message
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_supabase_admin
from app.middleware.auth_middleware import get_current_user
from app.services.ai_service import generate_pitch, generate_website_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["AI"])


def _increment_ai_usage(user_id: str) -> None:
    supabase = get_supabase_admin()
    try:
        supabase.rpc("increment_daily_usage", {
            "p_user_id": user_id,
            "p_ai_calls": 1,
            "p_searches": 0,
            "p_leads": 0,
        }).execute()
    except Exception as e:
        logger.warning(f"Failed to increment AI usage via RPC: {e}")
        today = date.today().isoformat()
        existing = supabase.table("daily_usage").select("id, ai_calls").eq("user_id", user_id).eq("date", today).execute()
        if existing.data and len(existing.data) > 0:
            supabase.table("daily_usage").update({
                "ai_calls": (existing.data[0].get("ai_calls", 0) or 0) + 1,
            }).eq("id", existing.data[0]["id"]).execute()
        else:
            supabase.table("daily_usage").insert({
                "user_id": user_id,
                "date": today.isoformat(),
                "searches_run": 0,
                "leads_generated": 0,
                "ai_calls": 1,
            }).execute()

AI_DAILY_LIMIT = 100


async def check_ai_limit(user_id: str) -> None:
    supabase = get_supabase_admin()
    today = date.today().isoformat()
    usage_resp = supabase.table("daily_usage").select("ai_calls").eq("user_id", user_id).eq("date", today).execute()
    used = 0
    if usage_resp.data and len(usage_resp.data) > 0:
        used = usage_resp.data[0].get("ai_calls", 0) or 0
    if used >= AI_DAILY_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Daily AI call limit ({AI_DAILY_LIMIT}) reached. Please try again tomorrow.",
        )


@router.post("/pitch/{lead_id}")
async def generate_lead_pitch(
    lead_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Generate an AI outreach pitch for a specific lead.
    Uses business details and website analysis (if available) as context.
    """
    supabase = get_supabase_admin()
    user_id = current_user["id"]

    # Fetch lead
    try:
        lead_resp = (
            supabase.table("leads")
            .select("*")
            .eq("id", lead_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if not lead_resp.data or len(lead_resp.data) == 0:
            raise HTTPException(status_code=404, detail="Lead not found")
        lead = lead_resp.data[0]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Fetch website analysis if available
    analysis = None
    try:
        analysis_resp = (
            supabase.table("website_analyses")
            .select("*")
            .eq("lead_id", lead_id)
            .limit(1)
            .execute()
        )
        if analysis_resp.data:
            analysis = analysis_resp.data[0]
    except Exception as fetch_err:
        logger.warning(f"Failed to fetch website analysis for lead {lead_id}: {fetch_err}")

    await check_ai_limit(user_id)

    # Generate pitch
    result = await generate_pitch(lead=lead, analysis=analysis)

    # Track AI usage
    try:
        _increment_ai_usage(user_id)
    except Exception as e:
        logger.warning(f"Failed to track AI usage: {e}")

    # Save pitch to lead
    try:
        update_data = {
            "ai_pitch": result["pitch"],
            "ai_confidence_score": result["confidence_score"],
            "estimated_deal_value": result["estimated_deal_value"],
        }
        supabase.table("leads").update(update_data).eq("id", lead_id).execute()
    except Exception as e:
        logger.warning(f"Failed to save pitch for lead {lead_id}: {e}")

    return {
        "lead_id": lead_id,
        "pitch": result["pitch"],
        "confidence_score": result["confidence_score"],
        "estimated_deal_value": result["estimated_deal_value"],
    }


@router.post("/website-message/{lead_id}")
async def generate_lead_website_message(
    lead_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Generate a short personalized website outreach message for WhatsApp.
    Mentions specific website issues and offers help.
    """
    supabase = get_supabase_admin()
    user_id = current_user["id"]

    try:
        lead_resp = (
            supabase.table("leads")
            .select("*")
            .eq("id", lead_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if not lead_resp.data or len(lead_resp.data) == 0:
            raise HTTPException(status_code=404, detail="Lead not found")
        lead = lead_resp.data[0]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Lead not found")

    analysis = None
    try:
        analysis_resp = (
            supabase.table("website_analyses")
            .select("*")
            .eq("lead_id", lead_id)
            .limit(1)
            .execute()
        )
        if analysis_resp.data:
            analysis = analysis_resp.data[0]
    except Exception as fetch_err:
        logger.warning(f"Failed to fetch website analysis for lead {lead_id}: {fetch_err}")

    await check_ai_limit(user_id)

    result = await generate_website_message(lead=lead, analysis=analysis)

    try:
        _increment_ai_usage(user_id)
    except Exception as e:
        logger.warning(f"Failed to track AI usage: {e}")

    return {
        "lead_id": lead_id,
        "message": result["message"],
    }
