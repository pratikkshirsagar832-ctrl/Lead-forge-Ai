"""
LeadForge AI — Lead Schemas
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class LeadListItem(BaseModel):
    """Compact lead for list views."""
    id: str
    search_id: str
    business_name: str
    category: Optional[str] = None
    full_address: Optional[str] = None
    phone: Optional[str] = None
    website_url: Optional[str] = None
    rating: Optional[float] = None
    total_reviews: int = 0
    lead_category: str = "warm"
    website_health_score: Optional[int] = None
    user_status: str = "new"
    is_favorite: bool = False
    has_pitch: bool = False
    created_at: Optional[datetime] = None


class LeadDetail(BaseModel):
    """Full lead detail with all fields."""
    id: str
    search_id: str
    user_id: str
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
    lead_category: str = "warm"
    website_health_score: Optional[int] = None
    ai_pitch: Optional[str] = None
    ai_confidence_score: Optional[float] = None
    estimated_deal_value: Optional[float] = None
    user_status: str = "new"
    user_notes: str = ""
    is_favorite: bool = False
    created_at: Optional[datetime] = None


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
