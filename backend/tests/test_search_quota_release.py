"""Regression test: a failed searches-row insert must release the reservation.

`_release_unused_reservation` called `asyncio.to_thread` without importing
`asyncio`; the resulting NameError was swallowed by its own broad `except`, so
the monthly quota reservation leaked silently (the user permanently lost the
capacity of a search that never ran).
"""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routers.search import _release_unused_reservation  # noqa: E402


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, table, kind="select", payload=None):
        self.client = client
        self.table = table
        self.kind = kind
        self.payload = payload
        self.filters: list[tuple] = []

    def select(self, cols="*"):
        self.kind = "select"
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def limit(self, n):
        return self

    def update(self, payload):
        self.kind = "update"
        self.payload = payload
        return self

    def _matches(self, row) -> bool:
        return all(row.get(k) == v for k, v in self.filters)

    def execute(self):
        rows = self.client.rows.setdefault(self.table, [])
        if self.kind == "update":
            updated = []
            for row in rows:
                if self._matches(row):
                    row.update(dict(self.payload))
                    updated.append(row)
            return _Resp(updated)
        return _Resp([r for r in rows if self._matches(r)])


class FakeSupabase:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        return _Query(self, name)


def _month() -> str:
    return datetime.now(timezone.utc).replace(day=1).date().isoformat()


def test_release_decrements_reserved_quota():
    client = FakeSupabase({"monthly_usage": [{
        "user_id": "user-1", "usage_month": _month(),
        "gmb_generated": 3, "gmb_reserved": 10,
    }]})

    asyncio.run(_release_unused_reservation(client, "user-1", "google_maps", 4))

    row = client.rows["monthly_usage"][0]
    assert row["gmb_reserved"] == 6  # 10 - 4, no NameError short-circuit
    assert row["gmb_generated"] == 3  # generated is never touched


def test_release_is_clamped_at_zero_for_linkedin():
    client = FakeSupabase({"monthly_usage": [{
        "user_id": "user-1", "usage_month": _month(),
        "linkedin_hq_generated": 0, "linkedin_hq_reserved": 2,
    }]})

    asyncio.run(_release_unused_reservation(client, "user-1", "linkedin", 5))

    assert client.rows["monthly_usage"][0]["linkedin_hq_reserved"] == 0


def test_release_without_a_usage_row_is_a_noop():
    client = FakeSupabase({"monthly_usage": []})

    asyncio.run(_release_unused_reservation(client, "user-1", "google_maps", 3))

    assert client.rows["monthly_usage"] == []
