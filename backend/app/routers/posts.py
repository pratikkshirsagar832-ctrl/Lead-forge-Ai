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

    # Cost guard: each run fires a paid Apify actor. Per-user sliding window —
    # the free tier also has no business firing dozens of paid runs an hour.
    from app.utils.rate_limit import check_rate_limit
    if not check_rate_limit(f"posts_scrape:{user_id}", limit=6, window_seconds=3600):
        raise HTTPException(status_code=429, detail="Scrape rate limit reached. Try again in about an hour.")

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
            raise HTTPException(status_code=500, detail="Failed to load lead")

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
        logger.warning("Invalid scrape request for user %s: %s", user_id[:8], e)
        raise HTTPException(status_code=400, detail="Invalid scrape request")
    except ApifyError as e:
        logger.warning("Post scraper provider failed for user %s: %s", user_id[:8], e)
        raise HTTPException(status_code=502, detail="Post scraper temporarily unavailable")
    except Exception as e:
        logger.error(f"[Posts:{user_id[:8]}] scrape failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Scrape failed")

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
        raise HTTPException(status_code=500, detail="Failed to list posts")
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
        except Exception as e:
            logger.error(f"Failed to load lead {lead_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error")

        owner_lead_id: str | None = None
        profile_url = ""
        if lead.data:
            owner_lead_id = lead_id
            profile_url = (lead.data[0].get("linkedin_url") or "").strip()
        else:
            # LinkedIn leads live in ha_leads (no user_id): ownership resolves
            # through the parent search row. They used to 404 here even though
            # the profile url is known, so the post history was unreachable.
            try:
                ha = (
                    supabase.table("ha_leads")
                    .select("id, search_id, author_profile_url")
                    .eq("id", lead_id)
                    .limit(1)
                    .execute()
                )
                if ha.data:
                    srow = (
                        supabase.table("searches")
                        .select("user_id")
                        .eq("id", ha.data[0].get("search_id"))
                        .limit(1)
                        .execute()
                    )
                    if srow.data and srow.data[0].get("user_id") == user_id:
                        profile_url = (ha.data[0].get("author_profile_url") or "").strip()
            except Exception as e:
                logger.error(f"Failed to resolve LinkedIn lead {lead_id}: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail="Internal server error")

        if owner_lead_id is None and not profile_url:
            raise HTTPException(status_code=404, detail="Lead not found")

        try:
            data = await asyncio.to_thread(
                post_scraper_service.list_profile_posts,
                supabase,
                user_id,
                lead_id=owner_lead_id,
                profile_url=profile_url or None,
                page=page,
                per_page=per_page,
            )
            # Stored profile urls may differ only by a trailing slash.
            if not data["items"] and profile_url:
                variant = profile_url.rstrip("/")
                if variant and variant != profile_url:
                    data = await asyncio.to_thread(
                        post_scraper_service.list_profile_posts,
                        supabase,
                        user_id,
                        lead_id=owner_lead_id,
                        profile_url=variant,
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
