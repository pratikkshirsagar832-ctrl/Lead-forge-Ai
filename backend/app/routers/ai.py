"""
LeadForge AI — AI Router

Endpoints:
  POST /api/ai/pitch/{lead_id} — generate an AI pitch for a lead
"""

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_supabase_admin
from app.middleware.auth_middleware import get_current_user
from app.services.ai_service import generate_pitch

router = APIRouter(prefix="/api/ai", tags=["AI"])


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
            .single()
            .execute()
        )
        if not lead_resp.data:
            raise HTTPException(status_code=404, detail="Lead not found")
        lead = lead_resp.data
    except HTTPException:
        raise
    except Exception as e:
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
    except Exception:
        pass  # Not critical — pitch can be generated without analysis

    # Generate pitch
    result = await generate_pitch(lead=lead, analysis=analysis)

    # Save pitch to lead
    try:
        update_data = {
            "ai_pitch": result["pitch"],
            "ai_confidence_score": result["confidence_score"],
            "estimated_deal_value": result["estimated_deal_value"],
        }
        supabase.table("leads").update(update_data).eq("id", lead_id).execute()
    except Exception as e:
        # Non-critical — pitch was generated, just couldn't save
        pass

    return {
        "lead_id": lead_id,
        "pitch": result["pitch"],
        "confidence_score": result["confidence_score"],
        "estimated_deal_value": result["estimated_deal_value"],
    }
