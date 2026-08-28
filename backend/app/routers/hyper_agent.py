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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.middleware.auth_middleware import get_current_user
from app.middleware.usage_middleware import check_search_limit
from app.services.hyper_agent import HyperAgentService
from app.database import get_supabase_admin
from app.services.plans import resolve_effective_subscription, get_plan_row, get_used_today
from app.services.apify_service import ApifyError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hyper-agent", tags=["HyperAgent"])

# Allowed plans for HyperAgent
ALLOWED_PLANS = {"pro", "agency"}


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list)
    lead_types: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    response: str
    action: str
    data: dict | None = None


class ScrapeRequest(BaseModel):
    context: dict = Field(..., description="ICP context: niche, roles, location, count")


class ScrapeResponse(BaseModel):
    search_id: str
    status: str
    message: str


def run_hyper_agent_job(search_id: str, user_id: str, context: dict) -> None:
    """Background job: scrape LinkedIn → AI qualify → save leads → update search."""
    supabase = get_supabase_admin()

    def _mark(status_val: str, message: str, extra: dict | None = None) -> None:
        try:
            payload = {"status": status_val, "message": message}
            if extra:
                payload.update(extra)
            supabase.table("searches").update(payload).eq("id", search_id).execute()
        except Exception as e:
            logger.warning(f"[HyperAgent] Status update failed: {e}")

    try:
        _mark("scraping", f"Searching for {context.get('niche', '')} in {context.get('location', '')}")

        service = HyperAgentService()

        # Scrape LinkedIn
        raw_items = service.scrape_leads(context)
        logger.info(f"[HyperAgent] Scraped {len(raw_items)} raw items")

        if not raw_items:
            _mark("failed", "No results found on LinkedIn for this search")
            return

        # Qualify with AI
        _mark("qualifying", "Analyzing and scoring leads with AI")
        qualified = service.qualify_leads(raw_items, context)
        logger.info(f"[HyperAgent] Qualified {len(qualified)} leads")

        # Save to database
        saved = service.save_leads(qualified, user_id, search_id)

        # Update search record
        _mark("completed", f"Found {len(qualified)} high-quality leads from {len(raw_items)} results", {
            "total_results": saved,
            "hot_leads": len([l for l in qualified if l.get("score", 0) >= 85]),
            "warm_leads": len([l for l in qualified if 25 <= l.get("score", 0) < 85]),
            "skipped": max(0, len(raw_items) - saved),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })

        # Update daily usage (DB trigger already counts leads_generated, so only increment searches)
        try:
            supabase.rpc("increment_daily_usage", {
                "p_user_id": user_id,
                "p_leads": 0,
                "p_searches": 1,
            }).execute()
        except Exception as e:
            logger.warning(f"[HyperAgent] Usage increment failed: {e}")

    except ApifyError as e:
        logger.error(f"[HyperAgent] Apify error: {e}")
        _mark("failed", f"LinkedIn scraping failed: {str(e)}")
    except Exception as e:
        logger.error(f"[HyperAgent] Scrape error: {e}", exc_info=True)
        _mark("failed", f"Search failed: {str(e)}")


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
            lead_types=request.lead_types,
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
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """Queue a LinkedIn scrape job — returns immediately with a search_id.

    The actual scrape runs in the background. Frontend polls
    GET /api/hyper-agent/results/{search_id} for status and leads.
    """
    # Plan check
    _check_plan_access(current_user)

    context = request.context
    if not context.get("niche") or not context.get("location"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Context must include 'niche' and 'location'",
        )

    supabase = get_supabase_admin()

    try:
        # Daily limit pre-check: fail fast before spending Apify/OpenAI credits
        eff = resolve_effective_subscription(supabase, current_user["id"])
        plan = get_plan_row(supabase, eff.get("plan_id", "free"))
        used_searches, used_leads = get_used_today(supabase, current_user["id"])
        search_limit = plan.get("searches_per_day", 3) or 3
        lead_limit = plan.get("leads_per_day", 30) or 30
        if used_searches >= search_limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Daily search limit reached ({search_limit}/day). Upgrade your plan for more.",
            )
        if used_leads >= lead_limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Daily lead limit reached ({lead_limit}/day). Upgrade your plan for more.",
            )

        # Create search record
        search_result = supabase.table("searches").insert({
            "user_id": current_user["id"],
            "niche": f"HyperAgent: {context.get('niche', '')}",
            "location": context.get("location", ""),
            "source": "hyper_agent",
            "status": "queued",
            "message": f"Searching for {context.get('niche', '')} in {context.get('location', '')}",
            "max_results": min(context.get("count", 20), 50),
        }).execute()

        search_id = search_result.data[0]["id"]

        # Run in background so the HTTP request returns instantly
        background_tasks.add_task(
            run_hyper_agent_job,
            search_id=search_id,
            user_id=current_user["id"],
            context=context,
        )

        return ScrapeResponse(
            search_id=search_id,
            status="queued",
            message="Search queued — results will be ready shortly",
        )

    except Exception as e:
        logger.error(f"[HyperAgent] Failed to queue search: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start search",
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


@router.post("/backfill-post-urls")
async def backfill_post_urls(current_user: dict = Depends(get_current_user)):
    """Backfill missing post_url on existing LinkedIn leads.

    Finds leads (source=linkedin or hyper_agent) with empty post_url for the
    current user, re-runs the HarvestAPI post-search actor for each search,
    matches posts back to leads by author URL + post text, and fills post_url.
    """
    from app.services.hyper_agent import HyperAgentService, _extract_post_url
    from app.services.apify_service import HARVEST_POST_SEARCH_ACTOR, _run_with_key

    supabase = get_supabase_admin()
    user_id = current_user["id"]

    # Find leads with empty post_url
    leads_resp = (
        supabase.table("leads")
        .select("id, search_id, linkedin_url, post_text, business_name")
        .in_("source", ["linkedin", "hyper_agent"])
        .eq("user_id", user_id)
        .eq("post_url", "")
        .limit(200)
        .execute()
    )
    leads = leads_resp.data or []
    if not leads:
        return {"updated": 0, "message": "No leads need backfill"}

    # Group by search_id and get the search context (niche/location)
    search_ids = {l["search_id"] for l in leads}
    searches_resp = supabase.table("searches").select("id, niche, location").in_("id", list(search_ids)).execute()
    search_map = {s["id"]: s for s in (searches_resp.data or [])}

    service = HyperAgentService()
    updated = 0
    # author-url → post_url map (cleaned profile url)
    post_by_author: dict[str, str] = {}

    for search_id in search_ids:
        search = search_map.get(search_id)
        if not search:
            continue
        niche = (search.get("niche") or "").replace("HyperAgent: ", "").strip()
        if not niche:
            continue

        try:
            queries = service._build_queries(niche, "", search.get("location", ""))
            payload = {
                "searchQueries": queries,
                "maxPosts": 100,
                "postedLimit": "year",
                "sortBy": "date",
                "profileScraperMode": "main",
                "scrapeReactions": False,
                "postNestedReactions": False,
                "scrapeComments": False,
                "postNestedComments": False,
            }
            key = service._get_harvest_key()
            items = _run_with_key(HARVEST_POST_SEARCH_ACTOR, key, payload)
            for item in items:
                author = item.get("author") or {}
                author_url = (author.get("url") or author.get("linkedinUrl") or "").strip()
                if not author_url:
                    continue
                clean = author_url.split("?")[0].rstrip("/").lower()
                post_url = _extract_post_url(item)
                if post_url:
                    post_by_author.setdefault(clean, post_url)
        except Exception as e:
            logger.warning(f"[HyperAgent] Backfill scrape failed for search {search_id}: {e}")
            continue

    # Match and update leads
    for lead in leads:
        linkedin_url = (lead.get("linkedin_url") or "").strip()
        clean = linkedin_url.split("?")[0].rstrip("/").lower()
        post_url = post_by_author.get(clean)
        if not post_url:
            continue
        supabase.table("leads").update({"post_url": post_url}).eq("id", lead["id"]).execute()
        updated += 1

    return {"updated": updated, "message": f"Backfilled post_url for {updated} leads"}
