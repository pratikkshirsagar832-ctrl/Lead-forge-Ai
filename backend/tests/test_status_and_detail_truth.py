"""Regression tests for two "authoritative data" bugs.

1. `GET /api/searches/{id}/status` merged the in-memory live-progress registry
   on top of the DB row, and the registry was never cleared when a search
   finished — a completed search could report stale live numbers.
2. `GET /api/leads/{id}` returned the raw DB row, so a NULL business_name or a
   float score failed the response schema (HTTP 500) while the list endpoint —
   which coerces — worked fine.
"""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routers import leads as leads_router  # noqa: E402
from app.routers import search as search_router  # noqa: E402
from app.schemas.lead import LeadDetail  # noqa: E402
from app.services import hyperagent_service  # noqa: E402


class _Resp:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count if count is not None else len(data)


class _Query:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.filters: list[tuple] = []
        self._limit = None

    def select(self, cols="*", count=None):
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def or_(self, expr):
        return self

    def order(self, col, desc=False):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def in_(self, col, values):
        self.filters.append((col, ("__in__", list(values))))
        return self

    def _matches(self, row) -> bool:
        for col, val in self.filters:
            if isinstance(val, tuple) and val[0] == "__in__":
                if row.get(col) not in val[1]:
                    return False
            elif row.get(col) != val:
                return False
        return True

    def execute(self):
        rows = self.client.rows.get(self.table, [])
        found = [dict(r) for r in rows if self._matches(r)]
        if self._limit:
            found = found[: self._limit]
        return _Resp(found)


class FakeSupabase:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        return _Query(self, name)


def _wire(monkeypatch, client):
    """Routers import get_supabase_admin by value — patch it per module."""
    monkeypatch.setattr(search_router, "get_supabase_admin", lambda: client)
    monkeypatch.setattr(leads_router, "get_supabase_admin", lambda: client)


def test_terminal_status_clears_stale_progress_and_uses_db_counts(monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    client = FakeSupabase({
        "searches": [{
            "id": "s1", "user_id": "u1", "status": "completed", "source": "linkedin",
            "progress_percent": 100, "message": "done", "total_results": 3,
            "hot_leads": 3, "warm_leads": 50, "skipped": 47, "emails_found": 0,
            "created_at": now, "completed_at": now, "niche": "video editing",
            "location": "Global", "max_results": 3, "lead_types": ["buyer"],
            "error_message": None,
        }],
        "ha_searches": [{
            "id": "s1", "status": "completed", "scanned_count": 50,
            "accepted_count": 3, "leads_needed": 3, "finished_at": now,
            "error": None,
        }],
        "ha_leads": [
            {"id": "l1", "search_id": "s1"},
            {"id": "l2", "search_id": "s1"},
            {"id": "l3", "search_id": "s1"},
        ],
    })
    _wire(monkeypatch, client)

    # A leftover live-progress entry from the finished run.
    hyperagent_service._progress_push("s1", "running", 999, 999, 999)
    try:
        result = search_router.get_search_status("s1", current_user={"id": "u1"})
        assert result["hot_leads"] == 3          # DB truth, not the registry
        assert result["total_results"] == 3
        assert hyperagent_service.get_progress("s1") is None
    finally:
        hyperagent_service.clear_progress("s1")


def test_lead_detail_row_is_coerced_before_schema_validation(monkeypatch):
    client = FakeSupabase({
        "leads": [{
            "id": "lead-1", "search_id": "s1", "user_id": "u1",
            "business_name": None,             # NULL -> schema requires a string
            "lead_category": None,
            "website_health_score": 72.6,      # float -> schema requires int
            "connections_count": None,
            "total_reviews": None,
            "rating": "4.5",                   # string -> schema requires float
            "source": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }],
        "website_analyses": [],
    })
    _wire(monkeypatch, client)

    result = asyncio.run(
        leads_router.get_lead_detail("lead-1", current_user={"id": "u1"})
    )

    # The strongest assertion: the exact schema FastAPI validates it against.
    detail = LeadDetail(**result)
    assert detail.business_name == "Unknown Business"
    assert detail.website_health_score == 73
    assert detail.connections_count == 0
    assert detail.rating == 4.5
    assert detail.lead_category == "warm"
    assert detail.source == "google_maps"


def test_lead_detail_still_404s_for_an_unknown_lead(monkeypatch):
    from fastapi import HTTPException

    client = FakeSupabase({"leads": [], "ha_leads": [], "searches": []})
    _wire(monkeypatch, client)

    try:
        asyncio.run(leads_router.get_lead_detail("nope", current_user={"id": "u1"}))
    except HTTPException as exc:
        assert exc.status_code == 404
    else:  # pragma: no cover
        raise AssertionError("expected HTTPException(404)")
