"""Regression test: the CSV export must include LinkedIn (ha_leads) leads.

`export_leads_csv` read only the Google-Maps `leads` table, so a Pro/Agency
customer's LinkedIn leads were silently missing from the export and
`source=linkedin` produced a header-only CSV — even though the same leads were
visible in the dashboard (the list endpoint merges both sources).
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routers import leads as leads_router  # noqa: E402
from app.services import plans as plans_module  # noqa: E402


class _Resp:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _Query:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.filters: list[tuple] = []
        self._order = None
        self._limit = None

    def select(self, cols="*"):
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def in_(self, col, values):
        self.filters.append((col, ("__in__", list(values))))
        return self

    def ilike(self, col, pattern):
        self.filters.append((col, ("__ilike__", pattern)))
        return self

    def gt(self, col, val):
        self.filters.append((col, ("__gt__", val)))
        return self

    def like(self, col, pattern):
        self.filters.append((col, ("__ilike__", pattern)))
        return self

    def or_(self, expr):
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _matches(self, row) -> bool:
        for col, val in self.filters:
            if isinstance(val, tuple):
                op, operand = val
                if op == "__in__":
                    if row.get(col) not in operand:
                        return False
                elif op == "__ilike__":
                    needle = str(operand).strip("%").lower()
                    if needle and needle not in str(row.get(col) or "").lower():
                        return False
                elif op == "__gt__":
                    if (row.get(col) or "") <= operand:
                        return False
            elif row.get(col) != val:
                return False
        return True

    def execute(self):
        rows = self.client.rows.get(self.table, [])
        found = [r for r in rows if self._matches(r)]
        if self._order:
            col, desc = self._order
            found.sort(key=lambda r: (r.get(col) or ""), reverse=desc)
        if self._limit:
            found = found[: self._limit]
        return _Resp(found, count=len(found))


class FakeSupabase:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        return _Query(self, name)


def _fixture_rows():
    return {
        "leads": [{
            "id": "maps-1", "user_id": "user-1", "search_id": "s-maps",
            "source": "google_maps", "business_name": "Bob Plumbing",
            "lead_category": "hot", "user_status": "new", "is_favorite": False,
        }],
        "searches": [{"id": "s-li", "user_id": "user-1", "source": "linkedin"}],
        "ha_leads": [{
            "id": "li-1", "search_id": "s-li", "lead_type": "need_freelancer",
            "author_name": "Ada Buyer", "post_url": "https://linkedin.com/posts/1",
            "post_text": "Need a freelance editor", "post_date": "2026-09-10",
            "overall_quality_score": 0.8, "status": "new",
        }],
    }


def _export(**overrides):
    """Call the endpoint with FastAPI's Query defaults resolved to None
    (calling a handler directly leaves the `Query(...)` sentinels in place)."""
    params = {
        "search_id": None,
        "source": None,
        "post_type": None,
        "lead_category": None,
        "user_status": None,
        "is_favorite": None,
        "search": None,
        "current_user": {"id": "user-1"},
    }
    params.update(overrides)
    return asyncio.run(leads_router.export_leads_csv(**params))


def _body_text(response) -> str:
    it = response.body_iterator
    if hasattr(it, "__aiter__"):
        async def _drain():
            parts = []
            async for chunk in it:
                parts.append(chunk.decode() if isinstance(chunk, (bytes, bytearray)) else str(chunk))
            return "".join(parts)
        return asyncio.run(_drain())
    return "".join(
        c.decode() if isinstance(c, (bytes, bytearray)) else str(c) for c in it
    )


def _wire(monkeypatch, client):
    monkeypatch.setattr(leads_router, "get_supabase_admin", lambda: client)
    monkeypatch.setattr(
        plans_module, "resolve_effective_subscription",
        lambda supabase, user_id: {"plan_id": "pro", "status": "active"},
    )


def test_export_includes_linkedin_leads(monkeypatch):
    _wire(monkeypatch, FakeSupabase(_fixture_rows()))

    csv_text = _body_text(_export())

    assert "Bob Plumbing" in csv_text          # Maps row still exported
    assert "Ada Buyer" in csv_text             # LinkedIn row now exported too
    assert "linkedin.com/posts/1" in csv_text


def test_export_source_linkedin_returns_only_linkedin(monkeypatch):
    _wire(monkeypatch, FakeSupabase(_fixture_rows()))

    csv_text = _body_text(_export(source="linkedin"))

    assert "Ada Buyer" in csv_text
    assert "Bob Plumbing" not in csv_text


def test_export_source_google_maps_still_excludes_linkedin(monkeypatch):
    _wire(monkeypatch, FakeSupabase(_fixture_rows()))

    csv_text = _body_text(_export(source="google_maps"))

    assert "Bob Plumbing" in csv_text
    assert "Ada Buyer" not in csv_text


def test_export_requires_a_paid_plan(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(leads_router, "get_supabase_admin", lambda: FakeSupabase({}))
    monkeypatch.setattr(
        plans_module, "resolve_effective_subscription",
        lambda supabase, user_id: {"plan_id": "free", "status": "trial"},
    )

    try:
        _export()
    except HTTPException as exc:
        assert exc.status_code == 403
    else:  # pragma: no cover
        raise AssertionError("expected HTTPException(403)")


def test_linkedin_rows_are_scoped_to_the_owning_user(monkeypatch):
    """A user must never receive another user's LinkedIn rows."""
    rows = _fixture_rows()
    rows["searches"] = [
        {"id": "s-li", "user_id": "user-1", "source": "linkedin"},
        {"id": "s-other", "user_id": "user-2", "source": "linkedin"},
    ]
    rows["ha_leads"].append({
        "id": "li-other", "search_id": "s-other", "lead_type": "need_freelancer",
        "author_name": "Someone Else", "post_url": "https://linkedin.com/posts/2",
        "post_text": "hire me", "post_date": "2026-09-11",
    })
    _wire(monkeypatch, FakeSupabase(rows))

    csv_text = _body_text(_export())

    assert "Ada Buyer" in csv_text
    assert "Someone Else" not in csv_text
