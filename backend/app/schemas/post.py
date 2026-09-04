"""
Hyperclients — Profile Posts Schemas (post-scraper output)
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

LINKEDIN_HOST_HINTS = ("linkedin.com", "lnkd.in")


class ProfilePostRow(BaseModel):
    """One stored public post (profile_posts table row)."""
    id: Optional[str] = None
    user_id: Optional[str] = None
    lead_id: Optional[str] = None
    profile_url: str = ""
    post_url: str = ""
    post_id: Optional[str] = None
    post_text: Optional[str] = None
    author_name: Optional[str] = None
    author_url: Optional[str] = None
    author_headline: Optional[str] = None
    author_type: str = "unknown"
    posted_at: Optional[datetime] = None
    num_likes: Optional[int] = None
    num_comments: Optional[int] = None
    num_shares: Optional[int] = None
    hashtags: list[Any] = []
    mentions: list[Any] = []
    media: list[Any] = []
    extraction_status: str = "success"
    extraction_method: Optional[str] = None
    source_url: Optional[str] = None
    extracted_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class ScrapeProfilePostsRequest(BaseModel):
    """Body for POST /api/posts/scrape."""
    profile_urls: list[str] = Field(default_factory=list, description="LinkedIn profile URLs (person or company).")
    post_urls: list[str] = Field(default_factory=list, description="Optional direct LinkedIn post URLs to verify/extract.")
    max_posts_per_profile: int = Field(10, ge=1, le=50, description="Upper bound on posts per profile.")
    include_engagement: bool = True
    include_author: bool = True
    lead_id: Optional[str] = Field(None, description="Optional owning lead for the detail-page flow.")

    @field_validator("profile_urls", "post_urls")
    @classmethod
    def _check_urls(cls, v: list[str]) -> list[str]:
        out = []
        for raw in v or []:
            url = (raw or "").strip()
            if not url:
                continue
            if not (url.startswith("http://") or url.startswith("https://")):
                raise ValueError(f"Not an http(s) URL: {url[:120]}")
            out.append(url)
        return out

    @field_validator("profile_urls", "post_urls")
    @classmethod
    def _linkedin_only(cls, v: list[str]) -> list[str]:
        for url in v or []:
            host = (url.split("://", 1)[-1].split("/", 1)[0] or "").lower()
            if not any(h in host for h in LINKEDIN_HOST_HINTS):
                raise ValueError("Only LinkedIn URLs are supported by this endpoint")
        return v


class ProfilePostScrapeResult(BaseModel):
    status: str = "ok"
    items: list[ProfilePostRow] = []
    total: int = 0
    stats: dict[str, Any] = {}


class ProfilePostsPaginatedResponse(BaseModel):
    items: list[ProfilePostRow] = []
    total: int = 0
    page: int = 1
    per_page: int = 20
    total_pages: int = 0
