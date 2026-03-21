"""
LeadForge AI — Search Schemas
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SearchCreateRequest(BaseModel):
    """Request body for creating a new search."""
    niche: str = Field(..., min_length=1, max_length=200, description="Business niche to search")
    location: str = Field(..., min_length=1, max_length=300, description="Geographic location")


class SearchResponse(BaseModel):
    """Full search response."""
    id: str
    user_id: str
    niche: str
    location: str
    status: str = "queued"
    progress_percent: int = 0
    message: str = "Search queued"
    total_results: int = 0
    hot_leads: int = 0
    warm_leads: int = 0
    skipped: int = 0
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class SearchStatusResponse(BaseModel):
    """Lightweight status response for polling."""
    id: str
    status: str
    progress_percent: int = 0
    message: str = ""
    total_results: int = 0
    hot_leads: int = 0
    warm_leads: int = 0
    skipped: int = 0
    processed_count: int = 0
    elapsed_seconds: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class SearchHistoryItem(BaseModel):
    """Search item in history list."""
    id: str
    niche: str
    location: str
    status: str
    total_results: int = 0
    hot_leads: int = 0
    warm_leads: int = 0
    skipped: int = 0
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class SearchHistoryResponse(BaseModel):
    """Paginated search history."""
    items: list[SearchHistoryItem] = []
    total: int = 0
