"""
HyperAgent Router — AI-Powered Lead Discovery API

Endpoints:
  POST /api/hyper-agent/chat        — Conversational lead discovery
  POST /api/hyper-agent/scrape      — Execute LinkedIn scrape
  POST /api/hyper-agent/qualify     — Qualify scraped leads
  GET  /api/hyper-agent/results     — Get qualified results
  GET  /api/hyper-agent/health      — Health check
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.middleware.auth_middleware import get_current_user
from app.middleware.usage_middleware import check_search_limit
from app.services.hyper_agent import HyperAgentService
from app.database import get_supabase_admin
from app.services.plans import resolve_effective_subscription, get_plan_row

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hyper-agent", tags=["HyperAgent"])

# Allowed plans for HyperAgent
ALLOWED_PLANS = {"pro", "agency"}


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list)


class ChatResponse(BaseModel):
    response: str
    action: str
    data: dict | None = None


class ScrapeRequest(BaseModel):
    context: dict = Field(..., description="ICP context: niche, roles, location, count")


class ScrapeResponse(BaseModel):
    leads: list[dict]
    total: int
    qualified: int
    search_id: str
    message: str


def _check_plan_access(current_user: dict) -> dict:
    """Verify user has Pro or Agency plan."""
    supabase = get_supabase_admin()
    user_id = current_user["id"]

    eff = resolve_effective_subscription(supabase, user_id)
    plan_id = eff.get("plan_id", "free")

    if plan_id not in ALLOWED_PLANS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "HyperAgent is available for Pro and Agency plans only",
                "current_plan": plan_id,
                "upgrade_url": "/pricing",
            },
        )

    return eff


@router.post("/chat", response_model=ChatResponse)
async def hyper_agent_chat(
    request: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """Conversational lead discovery — understand user's ICP."""
    # Plan check
    _check_plan_access(current_user)

    try:
        service = HyperAgentService()
        result = service.chat(
            message=request.message,
            history=request.history,
            user_id=current_user["id"],
        )
        return ChatResponse(**result)
    except Exception as e:
        logger.error(f"[HyperAgent] Chat error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process message",
        )


@router.post("/scrape", response_model=ScrapeResponse)
async def hyper_agent_scrape(
    request: ScrapeRequest,
    current_user: dict = Depends(get_current_user),
):
    """Execute LinkedIn scrape with confirmed ICP context."""
    # Plan check
    _check_plan_access(current_user)

    context = request.context
    if not context.get("niche") or not context.get("location"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Context must include 'niche' and 'location'",
        )

    try:
        service = HyperAgentService()
        supabase = get_supabase_admin()

        # Create search record
        search_result = supabase.table("searches").insert({
            "user_id": current_user["id"],
            "niche": f"HyperAgent: {context.get('niche', '')}",
            "location": context.get("location", ""),
            "source": "hyper_agent",
            "status": "scraping",
            "message": f"Searching for {context.get('niche', '')} in {context.get('location', '')}",
            "max_results": min(context.get("count", 20), 50),
        }).execute()

        search_id = search_result.data[0]["id"]

        # Scrape LinkedIn
        raw_items = service.scrape_leads(context)
        logger.info(f"[HyperAgent] Scraped {len(raw_items)} raw items")

        # Qualify with AI
        qualified = service.qualify_leads(raw_items, context)
        logger.info(f"[HyperAgent] Qualified {len(qualified)} leads")

        # Save to database
        saved = service.save_leads(qualified, current_user["id"], search_id)

        # Update search record
        supabase.table("searches").update({
            "status": "completed",
            "total_results": saved,
            "hot_leads": len([l for l in qualified if l.get("score", 0) >= 80]),
            "warm_leads": len([l for l in qualified if 60 <= l.get("score", 0) < 80]),
            "skipped": len(raw_items) - saved,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", search_id).execute()

        # Update daily usage
        try:
            supabase.rpc("increment_daily_usage", {
                "p_user_id": current_user["id"],
                "p_field": "leads_generated",
                "p_amount": saved,
            }).execute()
        except Exception as e:
            logger.warning(f"[HyperAgent] Usage increment failed: {e}")

        return ScrapeResponse(
            leads=qualified,
            total=len(raw_items),
            qualified=len(qualified),
            search_id=search_id,
            message=f"Found {len(qualified)} high-quality leads from {len(raw_items)} results",
        )

    except ApifyError as e:
        logger.error(f"[HyperAgent] Apify error: {e}")
        # Update search status on failure
        try:
            supabase.table("searches").update({
                "status": "failed",
                "error_message": str(e),
            }).eq("id", search_id).execute()
        except Exception:
            pass

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LinkedIn scraping failed: {str(e)}",
        )
    except Exception as e:
        logger.error(f"[HyperAgent] Scrape error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to execute search",
        )


@router.get("/results/{search_id}")
async def get_results(
    search_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get qualified leads from a HyperAgent search."""
    supabase = get_supabase_admin()

    # Verify search belongs to user
    search = supabase.table("searches").select("*").eq("id", search_id).eq("user_id", current_user["id"]).execute()
    if not search.data:
        raise HTTPException(status_code=404, detail="Search not found")

    # Get leads
    leads = supabase.table("leads").select("*").eq("search_id", search_id).order("ai_confidence_score", desc=True).execute()

    return {
        "search": search.data[0],
        "leads": leads.data,
        "total": len(leads.data),
    }


@router.get("/health")
async def health():
    """HyperAgent health check."""
    from app.config import get_settings
    settings = get_settings()

    return {
        "status": "healthy",
        "service": "HyperAgent",
        "apify_key_configured": bool(settings.apify_api_key),
        "openai_key_configured": bool(settings.openai_api_key),
    }
