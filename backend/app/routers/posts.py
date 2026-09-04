"""
Hyperclients — Profile Posts Router (in-house public post scraper)

Endpoints:
  POST /api/posts/scrape — run the actor for profile/post URLs, persist posts
  GET  /api/posts        — list saved posts (filters: lead_id, profile_url)
  GET  /api/leads/{lead_id}/posts — list saved posts for one lead

LinkedIn keyword discovery is not provided here (that is served by the harvest
Apify actor on the LinkedIn search path). This module extracts PUBLIC posts
from profile/post URLs the product already knows.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import get_supabase_admin
from app.middleware.auth_middleware import get_current_user
from app.schemas.post import (
    ProfilePostRow,
    ProfilePostsPaginatedResponse,
    ProfilePostScrapeResult,
    ScrapeProfilePostsRequest,
)
from app.services import post_scraper_service
from app.services.apify_service import ApifyError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/posts", tags=["Posts"])


@router.post("/scrape", response_model=ProfilePostScrapeResult, status_code=200)
async def scrape_profile_posts(
    body: ScrapeProfilePostsRequest,
    current_user: dict = Depends(get_current_user),
):
    """Run the post-scraper actor for the given profile/post URLs and store
    every publicly extracted post for this user (deduped by post URL)."""
    user_id = current_user["id"]
    supabase = get_supabase_admin()

    # Optional lead must belong to this user and must have a linkedin_url.
    lead_id = body.lead_id
    if lead_id:
        try:
            lead = (
                supabase.table("leads")
                .select("id, linkedin_url, source")
                .eq("id", lead_id)
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if not (lead.data or []):
                raise HTTPException(status_code=404, detail="Lead not found")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to load lead {lead_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to load lead: {str(e)}")

    try:
        result = await asyncio.to_thread(
            post_scraper_service.store_profile_posts_sync,
            supabase,
            user_id,
            profile_urls=body.profile_urls,
            post_urls=body.post_urls,
            max_posts_per_profile=body.max_posts_per_profile,
            include_engagement=body.include_engagement,
            include_author=body.include_author,
            lead_id=lead_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ApifyError as e:
        raise HTTPException(status_code=502, detail=f"Post scraper provider failed: {e}")
    except Exception as e:
        logger.error(f"[Posts:{user_id[:8]}] scrape failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Scrape failed: {str(e)}")

    return ProfilePostScrapeResult(
        status="ok",
        items=[ProfilePostRow(**r) for r in result["saved"]],
        total=result["saved_count"],
        stats=result["stats"],
    )


@router.get("", response_model=ProfilePostsPaginatedResponse)
async def list_posts(
    lead_id: str | None = Query(None, description="Filter by owning lead"),
    profile_url: str | None = Query(None, description="Filter by profile URL"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """List this user's saved profile posts."""
    try:
        data = await asyncio.to_thread(
            post_scraper_service.list_profile_posts,
            get_supabase_admin(),
            current_user["id"],
            lead_id=lead_id,
            profile_url=profile_url,
            page=page,
            per_page=per_page,
        )
    except Exception as e:
        logger.error(f"Failed to list posts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list posts: {str(e)}")
    return ProfilePostsPaginatedResponse(
        items=[ProfilePostRow(**r) for r in data["items"]],
        total=data["total"],
        page=data["page"],
        per_page=data["per_page"],
        total_pages=data["total_pages"],
    )


def register_lead_posts_endpoint(app) -> None:
    """Attach GET /api/leads/{lead_id}/posts to the app (lives with leads)."""
    from fastapi import APIRouter

    lead_router = APIRouter(prefix="/api/leads", tags=["Leads"])

    @lead_router.get("/{lead_id}/posts", response_model=ProfilePostsPaginatedResponse)
    async def get_lead_posts(
        lead_id: str,
        page: int = Query(1, ge=1),
        per_page: int = Query(20, ge=1, le=100),
        current_user: dict = Depends(get_current_user),
    ):
        supabase = get_supabase_admin()
        user_id = current_user["id"]
        try:
            lead = (
                supabase.table("leads")
                .select("id, linkedin_url")
                .eq("id", lead_id)
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if not (lead.data or []):
                raise HTTPException(status_code=404, detail="Lead not found")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to load lead {lead_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error")

        lead = lead.data[0]
        linkedin_url = (lead.get("linkedin_url") or "").strip()
        try:
            data = await asyncio.to_thread(
                post_scraper_service.list_profile_posts,
                supabase,
                user_id,
                lead_id=lead_id if linkedin_url else None,
                profile_url=linkedin_url if linkedin_url else None,
                page=page,
                per_page=per_page,
            )
        except Exception as e:
            logger.error(f"Failed to list lead posts: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error")
        return ProfilePostsPaginatedResponse(
            items=[ProfilePostRow(**r) for r in data["items"]],
            total=data["total"],
            page=data["page"],
            per_page=data["per_page"],
            total_pages=data["total_pages"],
        )

    app.include_router(lead_router)
