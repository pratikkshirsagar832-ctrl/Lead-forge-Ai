"""Regression test: the LinkedIn branch of POST /api/ai/pitch must work.

The router called `generate_linkedin_pitch(...)` without importing it, so every
LinkedIn (ha_leads) pitch raised `NameError` and the endpoint returned HTTP 500
— the feature was entirely broken. This test drives the real router function
(not a stubbed generator) so the missing import can never come back.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.routers import ai as ai_router  # noqa: E402
from app.services import ai_service  # noqa: E402


class _Resp:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _Query:
    """Minimal PostgREST-shaped builder over an in-memory client."""

    def __init__(self, client, table, kind="select", payload=None):
        self.client = client
        self.table = table
        self.kind = kind
        self.payload = payload
        self.filters: list[tuple] = []
        self._limit = None

    def select(self, cols="*"):
        self.kind = "select"
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def order(self, col, desc=False):
        return self

    def update(self, payload):
        self.kind = "update"
        self.payload = payload
        return self

    def _matches(self, row) -> bool:
        return all(row.get(k) == v for k, v in self.filters)

    def execute(self):
        self.client.calls.append(f"{self.kind}:{self.table}")
        rows = self.client.rows.setdefault(self.table, [])
        if self.kind == "update":
            updated = []
            for row in rows:
                if self._matches(row):
                    row.update(dict(self.payload))
                    updated.append(row)
            return _Resp(updated)
        found = [r for r in rows if self._matches(r)]
        return _Resp(found, count=len(found))


class FakeSupabase:
    def __init__(self, rows: dict):
        self.rows = rows
        self.calls: list[str] = []

    def table(self, name: str) -> _Query:
        return _Query(self, name)


@pytest.fixture
def linkedin_lead_client() -> FakeSupabase:
    return FakeSupabase({
        "leads": [],  # not a Google-Maps lead -> LinkedIn fallback
        "ha_leads": [{
            "id": "lead-1",
            "search_id": "search-1",
            "author_name": "Ada Buyer",
            "post_text": "We need a freelance video editor for a launch.",
            "lead_type": "need_freelancer",
            "overall_quality_score": 0.82,
            "ai_pitch": None,
            "ai_confidence_score": None,
        }],
        "searches": [{"id": "search-1", "user_id": "user-1", "niche": "video editing"}],
    })


def test_linkedin_pitch_path_persists_pitch(monkeypatch, linkedin_lead_client):
    """The router must reach ai_service.generate_linkedin_pitch (was NameError)."""
    # The generator is the REAL one; only OpenAI itself is stubbed out so the
    # call resolves the function and takes its "not configured" fast path.
    monkeypatch.setattr(ai_service, "_get_openai_client", lambda: None)
    monkeypatch.setattr(ai_router, "get_supabase_admin", lambda: linkedin_lead_client)
    # The quota is now consumed inside check_ai_limit; stub only that boundary.
    monkeypatch.setattr(ai_router, "check_ai_limit", _noop_limit)

    result = asyncio.run(
        ai_router.generate_lead_pitch("lead-1", current_user={"id": "user-1"})
    )

    assert result["lead_id"] == "lead-1"
    assert "OPENAI_API_KEY" in result["pitch"]
    # The pitch result must be written back to ha_leads, not the maps table.
    assert "update:ha_leads" in linkedin_lead_client.calls
    assert "update:leads" not in linkedin_lead_client.calls


def test_generate_linkedin_pitch_is_imported_by_the_router():
    """Direct guard on the regression: the name must resolve in the module."""
    assert ai_router.generate_linkedin_pitch is ai_service.generate_linkedin_pitch


async def _noop_limit(user_id: str) -> str:
    return "pro"
