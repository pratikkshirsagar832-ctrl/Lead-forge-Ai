"""
Hyperclients — Lead Schemas
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class LeadListItem(BaseModel):
    """Compact lead for list views."""
    id: str
    search_id: str
    source: Optional[str] = None
    business_name: str = "Unknown Business"
    category: Optional[str] = None
    full_address: Optional[str] = None
    phone: Optional[str] = None
    email_found: Optional[str] = None
    website_url: Optional[str] = None
    rating: Optional[float] = None
    total_reviews: int = 0
    lead_category: str = "warm"
    website_health_score: Optional[int] = None
    headline: Optional[str] = None
    linkedin_url: Optional[str] = None
    post_url: Optional[str] = None
    post_text: Optional[str] = None
    profile_picture_url: Optional[str] = None
    connections_count: int = 0
    posted_at: Optional[datetime] = None
    post_type: Optional[str] = None
    ai_qualified: Optional[bool] = None
    ai_confidence_score: Optional[float] = None
    ai_reason: Optional[str] = None
    ai_pitch: Optional[str] = None
    user_status: str = "new"
    is_favorite: bool = False
    has_pitch: bool = False
    created_at: Optional[datetime] = None


class WebsiteAnalysis(BaseModel):
    """Website analysis attached to a lead."""
    id: Optional[str] = None
    lead_id: Optional[str] = None
    overall_score: int = 0
    issues: list[Any] = []
    emails_found: list[str] = []
    phones_found: list[str] = []
    raw_analysis: dict[str, Any] = {}
    created_at: Optional[datetime] = None


class LeadDetail(BaseModel):
    """Full lead detail with all fields."""
    id: str
    search_id: str
    user_id: str
    source: Optional[str] = None
    google_key: Optional[str] = None
    business_name: str
    category: Optional[str] = None
    full_address: Optional[str] = None
    phone: Optional[str] = None
    email_found: Optional[str] = None
    website_url: Optional[str] = None
    rating: Optional[float] = None
    total_reviews: int = 0
    google_maps_link: Optional[str] = None
    photos: list[Any] = []
    business_hours: dict[str, Any] = {}
    description: Optional[str] = None
    headline: Optional[str] = None
    linkedin_url: Optional[str] = None
    post_url: Optional[str] = None
    post_text: Optional[str] = None
    profile_picture_url: Optional[str] = None
    connections_count: int = 0
    posted_at: Optional[datetime] = None
    post_type: Optional[str] = None
    lead_category: str = "warm"
    website_health_score: Optional[int] = None
    ai_pitch: Optional[str] = None
    ai_confidence_score: Optional[float] = None
    estimated_deal_value: Optional[float] = None
    user_status: str = "new"
    user_notes: Optional[str] = ""
    is_favorite: bool = False
    created_at: Optional[datetime] = None
    website_analyses: list[WebsiteAnalysis] = []


class LeadStatusUpdate(BaseModel):
    """Update the user-defined status of a lead."""
    user_status: str = Field(
        ...,
        pattern="^(new|contacted|replied|converted|lost)$",
        description="One of: new, contacted, replied, converted, lost",
    )


class LeadNotesUpdate(BaseModel):
    """Update notes on a lead."""
    user_notes: str = Field("", max_length=5000)


class LeadFavoriteUpdate(BaseModel):
    """Toggle favorite status."""
    is_favorite: bool


class LeadPaginatedResponse(BaseModel):
    """Paginated list of leads."""
    items: list[LeadListItem] = []
    total: int = 0
    page: int = 1
    per_page: int = 20
    total_pages: int = 0
