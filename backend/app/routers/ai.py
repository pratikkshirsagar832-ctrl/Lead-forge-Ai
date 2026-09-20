"""
Hyperclients — AI Router

Endpoints:
  POST /api/ai/pitch/{lead_id}           — generate an AI pitch for a lead
  POST /api/ai/website-message/{lead_id} — generate a short WhatsApp outreach message
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_supabase_admin
from app.middleware.auth_middleware import get_current_user
from app.services.ai_service import (
    generate_linkedin_pitch,
    generate_pitch,
    generate_website_message,
)
from app.services.plans import quota_owner_id, resolve_effective_subscription

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["AI"])

# Plan-based AI limits (MONTHLY, v16 — same numbers, reset on the 1st)
AI_MONTHLY_LIMITS = {
    "free": 5,
    "solo": 25,
    "pro": 100,
    "agency": 300,
}
AI_DEFAULT_LIMIT = 5


def _get_ai_monthly_limit(plan: dict, plan_id: str) -> int:
    from app.services.plans import get_monthly_limit
    return get_monthly_limit(plan, "ai_calls_monthly", "ai_calls", AI_MONTHLY_LIMITS.get(plan_id, AI_DEFAULT_LIMIT))


async def check_ai_limit(user_id: str) -> str:
    """Consume one monthly AI call for this user. Returns the effective plan_id."""
    from app.services.plans import get_plan_row
    from app.services.usage import consume_monthly_quota

    supabase = get_supabase_admin()

    eff = resolve_effective_subscription(supabase, user_id)
    plan_id = eff.get("plan_id", "free")
    quota_user = quota_owner_id(eff, user_id)
    plan = get_plan_row(supabase, plan_id)
    limit = _get_ai_monthly_limit(plan, plan_id)

    consumed = await consume_monthly_quota(supabase, quota_user, "ai", limit)
    if consumed >= 0:
        raise HTTPException(
            status_code=429,
            detail=f"Monthly AI call limit ({limit} for {plan_id} plan) reached. Resets on the 1st.",
        )
    return plan_id


async def _refund_ai(user_id: str) -> None:
    """Give back a consumed AI unit when generation could not run."""
    from app.services.plans import resolve_effective_subscription as _resolve
    from app.services.usage import refund_monthly_quota

    try:
        supabase = get_supabase_admin()
        try:
            eff = _resolve(supabase, user_id)
            quota_user = quota_owner_id(eff, user_id)
        except Exception:
            quota_user = user_id
        await refund_monthly_quota(supabase, quota_user, "ai")
    except Exception as e:  # never fail the request over accounting
        logger.warning("Could not refund AI unit for user %s: %s", user_id[:8], e)


@router.post("/pitch/{lead_id}")
async def generate_lead_pitch(
    lead_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Generate an AI outreach pitch for a specific lead (Maps AND LinkedIn).
    Maps leads: business + website-analysis context.
    LinkedIn leads: author + post context (the post IS the buying signal).
    """
    supabase = get_supabase_admin()
    user_id = current_user["id"]

    # Fetch lead — Maps `leads` first, LinkedIn `ha_leads` fallback.
    lead: dict | None = None
    is_linkedin = False
    try:
        lead_resp = (
            supabase.table("leads")
            .select("*")
            .eq("id", lead_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if lead_resp.data and len(lead_resp.data) > 0:
            lead = lead_resp.data[0]
    except Exception:
        lead = None
    if lead is None:
        try:
            ha_resp = (
                supabase.table("ha_leads")
                .select("*")
                .eq("id", lead_id)
                .limit(1)
                .execute()
            )
            if ha_resp.data and len(ha_resp.data) > 0:
                ha_row = ha_resp.data[0]
                srow = (
                    supabase.table("searches")
                    .select("user_id, niche")
                    .eq("id", ha_row.get("search_id"))
                    .limit(1)
                    .execute()
                )
                if srow.data and srow.data[0].get("user_id") == user_id:
                    lead = ha_row
                    lead["_search_niche"] = srow.data[0].get("niche") or ""
                    is_linkedin = True
        except HTTPException:
            raise
        except Exception:
            lead = None
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Fetch website analysis if available (Maps leads only).
    analysis = None
    if not is_linkedin:
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

    # Generate pitch (post-context prompt for LinkedIn leads).
    try:
        if is_linkedin:
            result = await generate_linkedin_pitch(lead=lead)
        else:
            result = await generate_pitch(lead=lead, analysis=analysis)
    except Exception:
        await _refund_ai(user_id)
        raise

    # Save pitch to the source table so it persists across reloads.
    try:
        update_data = {
            "ai_pitch": result["pitch"],
            "ai_confidence_score": result["confidence_score"],
        }
        if is_linkedin:
            supabase.table("ha_leads").update(update_data).eq("id", lead_id).execute()
        else:
            update_data["estimated_deal_value"] = result["estimated_deal_value"]
            supabase.table("leads").update(update_data).eq("id", lead_id).eq("user_id", user_id).execute()
    except Exception as e:
        logger.warning(f"Failed to save pitch for lead {lead_id}: {e}")

    return {
        "lead_id": lead_id,
        "pitch": result["pitch"],
        "confidence_score": result["confidence_score"],
        "estimated_deal_value": result.get("estimated_deal_value", 0),
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

    try:
        result = await generate_website_message(lead=lead, analysis=analysis)
    except Exception:
        await _refund_ai(user_id)
        raise

    return {
        "lead_id": lead_id,
        "message": result["message"],
    }
