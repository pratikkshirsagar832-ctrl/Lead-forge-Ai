"""Regression tests for /api/leads schema coercion.

Guard the bug that 500'd the Leads Pipeline: a null lead_category or
connections_count, or a float website_health_score, must not fail LeadListItem
validation (LinkedIn `ha_leads` rows have no reliable category/connections,
and scores can arrive as floats).
"""
from datetime import date, datetime, timezone

import pytest

from app.routers.leads import _coerce_lead, _map_ha_lead, _map_ha_lead_detail
from app.schemas.lead import LeadDetail, LeadListItem


def test_coerce_handles_none_category_and_connections():
    raw = {"id": "a", "search_id": "s", "lead_category": None, "connections_count": None,
           "website_health_score": None, "total_reviews": None}
    co = _coerce_lead(raw)
    assert co["lead_category"] == "warm"
    assert co["connections_count"] == 0
    assert co["website_health_score"] is None
    assert co["total_reviews"] == 0
    LeadListItem(**co)  # must not raise


def test_coerce_rounds_float_website_health_score():
    co = _coerce_lead({"id": "a", "search_id": "s", "website_health_score": 88.5,
                       "connections_count": 0, "lead_category": "hot"})
    assert isinstance(co["website_health_score"], int)
    assert co["website_health_score"] == 88
    LeadListItem(**co)


def test_coerce_defaults_source_to_google_maps():
    co = _coerce_lead({"id": "a", "search_id": "s", "source": None,
                       "lead_category": "warm", "connections_count": 0})
    assert co["source"] == "google_maps"


def test_map_ha_lead_produces_valid_list_item():
    row = {
        "id": "li-1", "search_id": "s-1", "author_name": "Jane Doe",
        "author_profile_url": "https://linkedin.com/in/jane",
        "post_url": "https://linkedin.com/posts/1", "post_text": "Need a video editor.",
        "post_date": "2026-01-01", "lead_type": "need_freelancer",
        "overall_quality_score": 0.9, "status": "new", "created_at": "2026-01-01T00:00:00Z",
    }
    mapped = _map_ha_lead(row)
    assert mapped["source"] == "linkedin"
    assert mapped["post_type"] == "buyer"
    assert mapped["business_name"] == "Jane Doe"
    item = LeadListItem(**_coerce_lead(mapped))  # must not raise
    assert item.source == "linkedin"
    assert item.lead_category == "warm"  # coerced; hidden in UI for linkedin


def test_map_ha_lead_detail_produces_valid_detail():
    row = {
        "id": "li-9", "search_id": "s-9", "author_name": "ACME Ltd",
        "author_profile_url": "https://linkedin.com/in/acme",
        "post_url": "https://linkedin.com/posts/9", "post_text": "Need an agency.",
        "post_date": "2026-02-01", "lead_type": "our_agency",
        "overall_quality_score": 91.0, "status": "new", "created_at": "2026-02-01T00:00:00Z",
    }
    detail = _map_ha_lead_detail(row, "user-1")
    assert detail["user_id"] == "user-1"
    assert detail["source"] == "linkedin"
    assert detail["post_type"] == "agency_wanted"
    assert detail["lead_category"] == "warm"   # coerced (hidden in UI)
    assert isinstance(detail["connections_count"], int)
    item = LeadDetail(**detail)  # must not raise
