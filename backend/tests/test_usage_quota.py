"""Regression tests for the server-authoritative monthly quota helpers.

These run against a small fake Supabase client so the accounting logic
(RPC-first with a direct fallback, correct PRIMARY KEY keying, idempotent
settle marker) is verified without any network.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.services.usage import (  # noqa: E402
    reserve_monthly_leads_sync,
    settle_search_quota_sync,
)


class _Builder:
    def __init__(self, client, kind: str, table: str):
        self.client = client
        self.kind = kind
        self.table = table
        self.filters: list[tuple] = []
        self._limit = None
        self._order = None
        self._conflict = None
        self._ignore_dups = False
        self._payload = None

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
        self._order = (col, desc)
        return self

    def on_conflict(self, col):
        self._conflict = col
        return self

    def ignore_duplicates(self, flag=True):
        self._ignore_dups = flag
        return self

    def update(self, payload):
        self.kind = "update"
        self._payload = payload
        return self

    def insert(self, payload):
        self.kind = "insert"
        self._payload = payload
        return self

    def upsert(self, payload, on_conflict=None):
        self.kind = "upsert"
        self._payload = payload
        self._conflict = on_conflict
        return self

    def execute(self):
        return self.client._execute(self)


class _RPCBuilder:
    def __init__(self, client, name: str, params: dict):
        self.client = client
        self.name = name
        self.params = params

    def execute(self):
        return self.client._rpc_execute(self)


class FakeSupabase:
    def __init__(self):
        self.rows: dict[str, list[dict]] = {}
        self.calls: list[str] = []
        self.rpc_results: dict[str, object] = {}
        self.rpc_errors: dict[str, Exception] = {}

    def table(self, name: str) -> _Builder:
        return _Builder(self, "select", name)

    def rpc(self, name: str, params: dict) -> _RPCBuilder:
        return _RPCBuilder(self, name, params)

    def _matches(self, row: dict, b: _Builder) -> bool:
        return all(row.get(k) == v for k, v in b.filters)

    def _execute(self, b: _Builder):
        self.calls.append(f"{b.kind}:{b.table}")
        rows = self.rows.setdefault(b.table, [])
        if b.kind == "select":
            if b.table == "searches" and b.filters and b.filters[0][0] == "id":
                found = [r for r in rows if self._matches(r, b)]
                class R:
                    data = found
                return R()
            class R:
                data = rows
                count = len(rows)
            return R()
        if b.kind == "update":
            payload = dict(b._payload)
            for r in rows:
                if self._matches(r, b):
                    r.update(payload)
            class R:
                data = [r for r in rows if self._matches(r, b)]
            return R()
        if b.kind == "insert":
            rows.append(dict(b._payload))
            class R:
                data = [dict(b._payload)]
            return R()
        if b.kind == "upsert":
            merged = False
            for r in rows:
                if all(r.get(k) == dict(b._payload).get(k) for k in (b._conflict.split(",") if b._conflict else [])):
                    r.update(dict(b._payload))
                    merged = True
                    break
            if not merged:
                rows.append(dict(b._payload))
            class R:
                data = [dict(b._payload)]
            return R()
        class R:
            data = []
        return R()

    def _rpc_execute(self, rb: _RPCBuilder):
        self.calls.append(f"rpc:{rb.name}")
        if rb.name in self.rpc_errors:
            raise self.rpc_errors[rb.name]
        class R:
            data = self.rpc_results.get(rb.name)
        return R()


def _mk_searches_row(client: FakeSupabase, search_id: str, user_id: str,
                     source: str = "google_maps", reserved: int = 10) -> None:
    client.rows["searches"] = [{
        "id": search_id, "user_id": user_id, "quota_source": source,
        "reserved_leads": reserved, "quota_settled_at": None,
    }]


def _mk_monthly(client: FakeSupabase, user_id: str, month: str,
                gen=0, res=0) -> None:
    client.rows.setdefault("monthly_usage", []).append({
        "user_id": user_id, "usage_month": month,
        "linkedin_hq_generated": gen if False else 0,
        "gmb_generated": 0, "gmb_reserved": res,
        "linkedin_hq_generated": gen if False else 0,
    })
    client.rows["monthly_usage"][-1]["gmb_generated"] = gen
    client.rows["monthly_usage"][-1]["gmb_reserved"] = res


def _month() -> str:
    return datetime.now(timezone.utc).replace(day=1).date().isoformat()


def test_settle_prefers_rpc_and_marks_settled():
    client = FakeSupabase()
    client.rpc_results["settle_search_monthly_leads"] = None  # VOID fn returns None
    _mk_searches_row(client, "s1", "u1", reserved=10)

    settle_search_quota_sync(client, "s1", "u1", generated=10)
    assert "rpc:settle_search_monthly_leads" in client.calls
    # RPC path is transactional — the marker write is inside the DB function.
    # We only assert the RPC was attempted (no direct fallback write happened).
    assert "update:searches" not in client.calls


def test_settle_falls_back_to_direct_path_when_rpc_missing():
    client = FakeSupabase()
    client.rpc_errors["settle_search_monthly_leads"] = RuntimeError("function missing")
    _mk_searches_row(client, "s1", "u1", reserved=10)
    _mk_monthly(client, "u1", _month(), gen=5, res=10)

    settle_search_quota_sync(client, "s1", "u1", generated=4)
    mu = client.rows["monthly_usage"][0]
    assert mu["gmb_generated"] == 9       # 5 + 4
    assert mu["gmb_reserved"] == 0        # 10 - 10
    # Idempotency marker is written after the successful update.
    assert client.rows["searches"][0]["quota_settled_at"]


def test_settle_is_idempotent_after_marker():
    client = FakeSupabase()
    _mk_searches_row(client, "s1", "u1", reserved=10)
    client.rows["searches"][0]["quota_settled_at"] = "2026-01-01T00:00:00+00:00"
    _mk_monthly(client, "u1", _month(), gen=5, res=10)

    settle_search_quota_sync(client, "s1", "u1", generated=4)
    # No RPC, no direct update: already settled is a silent no-op.
    assert "rpc:settle_search_monthly_leads" not in client.calls
    assert "update:monthly_usage" not in client.calls


def test_settle_never_exceeds_reserved():
    client = FakeSupabase()
    client.rpc_errors["settle_search_monthly_leads"] = RuntimeError("missing")  # force direct path
    _mk_searches_row(client, "s1", "u1", reserved=3)
    _mk_monthly(client, "u1", _month(), gen=0, res=3)

    settle_search_quota_sync(client, "s1", "u1", generated=50)  # engine over-yield
    mu = client.rows["monthly_usage"][0]
    assert mu["gmb_generated"] == 3
    assert mu["gmb_reserved"] == 0


def test_reserve_prefers_rpc_full():
    client = FakeSupabase()
    client.rpc_results["reserve_monthly_leads"] = -1  # fully reserved
    got = reserve_monthly_leads_sync(client, "u1", "pro", "google_maps", 10)
    assert got == 10
    assert "rpc:reserve_monthly_leads" in client.calls


def test_reserve_falls_back_to_direct_and_caps_at_remaining():
    client = FakeSupabase()
    client.rpc_errors["reserve_monthly_leads"] = RuntimeError("missing")
    _mk_monthly(client, "u1", _month(), gen=20, res=10)  # limit-free: plan cap only
    # Plan lookup for 'free' (default gmb_leads_monthly fallback path reads
    # plans row; provide one with limit 30)
    client.rows["plans"] = [{"id": "free", "gmb_leads_monthly": 30, "linkedin_hq_leads_monthly": 0}]
    got = reserve_monthly_leads_sync(client, "u1", "free", "google_maps", 25)
    # 30 limit, 20 generated + 10 reserved = 30 already used -> 0 available
    assert got == 0


def test_reserve_when_usage_row_absent_creates_it():
    client = FakeSupabase()
    client.rpc_errors["reserve_monthly_leads"] = RuntimeError("missing")
    client.rows["plans"] = [{"id": "free", "gmb_leads_monthly": 30, "linkedin_hq_leads_monthly": 0}]
    got = reserve_monthly_leads_sync(client, "u1", "free", "google_maps", 5)
    assert got == 5
    mu = client.rows["monthly_usage"][0]
    assert mu["gmb_reserved"] == 5
