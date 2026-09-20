"""Regression test: GET /api/leads/{id}/posts must resolve LinkedIn leads.

The handler only looked in the Google-Maps `leads` table, so every LinkedIn
(ha_leads) lead 404'd even though its profile URL was known and the post
history was already stored — the feature was unreachable for the primary lead
source.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routers import posts as posts_router  # noqa: E402

PROFILE_URL = "https://www.linkedin.com/in/ada"


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

    def neq(self, col, val):
        return self

    def order(self, col, desc=False):
        return self

    def range(self, start, end):
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
        self.client.calls.append((self.table, list(self.filters)))
        rows = self.client.rows.get(self.table, [])
        found = [dict(r) for r in rows if self._matches(r)]
        if self._limit:
            found = found[: self._limit]
        return _Resp(found)


class FakeSupabase:
    def __init__(self, rows):
        self.rows = rows
        self.calls: list[tuple] = []

    def table(self, name):
        return _Query(self, name)


class _AppStub:
    """Records the router that register_lead_posts_endpoint() attaches."""

    def __init__(self):
        self.routers = []

    def include_router(self, router):
        self.routers.append(router)


def _get_lead_posts_handler():
    """The endpoint is attached to the app by register_lead_posts_endpoint.

    (Inspect the returned APIRouter directly — this FastAPI version keeps
    app-included routers behind a lazy wrapper, so app.routes is empty here.)
    """
    stub = _AppStub()
    posts_router.register_lead_posts_endpoint(stub)
    for router in stub.routers:
        for route in router.routes:
            if getattr(route, "path", "").endswith("/{lead_id}/posts"):
                return route.endpoint
    raise AssertionError("route not registered")


def _wire(monkeypatch, client):
    import app.services.post_scraper_service as scraper

    monkeypatch.setattr(posts_router, "get_supabase_admin", lambda: client)
    # Keep the query-recording fake in the loop while staying offline.
    monkeypatch.setattr(scraper, "run_post_scraper_actor", lambda payload: [])
    return scraper


def test_linkedin_lead_posts_query_the_author_profile(monkeypatch):
    client = FakeSupabase({
        "leads": [],  # not a Maps lead
        "ha_leads": [{
            "id": "li-1", "search_id": "s-li", "author_profile_url": PROFILE_URL,
        }],
        "searches": [{"id": "s-li", "user_id": "user-1"}],
        "profile_posts": [],
    })
    _wire(monkeypatch, client)

    handler = _get_lead_posts_handler()
    result = asyncio.run(
        handler(lead_id="li-1", page=1, per_page=20, current_user={"id": "user-1"})
    )

    assert result.total == 0
    # The post history must be filtered by the lead's LinkedIn profile URL.
    assert any(
        table == "profile_posts" and ("profile_url", PROFILE_URL) in filters
        for table, filters in client.calls
    ), client.calls


def test_linkedin_lead_of_another_user_is_not_found(monkeypatch):
    from fastapi import HTTPException

    client = FakeSupabase({
        "leads": [],
        "ha_leads": [{
            "id": "li-2", "search_id": "s-other", "author_profile_url": PROFILE_URL,
        }],
        "searches": [{"id": "s-other", "user_id": "someone-else"}],
        "profile_posts": [],
    })
    _wire(monkeypatch, client)

    handler = _get_lead_posts_handler()
    try:
        asyncio.run(
            handler(lead_id="li-2", page=1, per_page=20, current_user={"id": "user-1"})
        )
    except HTTPException as exc:
        assert exc.status_code == 404
    else:  # pragma: no cover
        raise AssertionError("expected HTTPException(404)")


def test_maps_lead_still_queries_by_lead_id(monkeypatch):
    client = FakeSupabase({
        "leads": [{"id": "maps-1", "user_id": "user-1", "linkedin_url": PROFILE_URL}],
        "profile_posts": [],
    })
    _wire(monkeypatch, client)

    handler = _get_lead_posts_handler()
    asyncio.run(
        handler(lead_id="maps-1", page=1, per_page=20, current_user={"id": "user-1"})
    )

    assert any(
        table == "profile_posts" and ("lead_id", "maps-1") in filters
        for table, filters in client.calls
    ), client.calls
