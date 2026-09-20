"""Regression tests for atomic daily quota consumption + v16 monthly quotas.

Daily caps were checked with a plain read and only incremented after the work
finished (overrun under concurrency). Consumption goes through row-locked RPCs
(v13 daily, v16 monthly) with direct fallbacks. v16: searches/AI/leads are
MONTHLY, same numbers, reset on the 1st.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.usage import (  # noqa: E402
    consume_daily_quota_sync,
    refund_daily_quota_sync,
    consume_monthly_quota_sync,
    refund_monthly_quota_sync,
)


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
        self._limit = None

    def select(self, cols="*"):
        self.kind = "select"
        self.cols = cols
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def insert(self, payload):
        self.kind = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.kind = "update"
        self.payload = payload
        return self

    def _matches(self, row) -> bool:
        return all(row.get(k) == v for k, v in self.filters)

    def execute(self):
        rows = self.client.rows.setdefault(self.table, [])
        if self.kind == "insert":
            rows.append(dict(self.payload))
            return _Resp([dict(self.payload)])
        if self.kind == "update":
            changed = []
            for row in rows:
                if self._matches(row):
                    row.update(dict(self.payload))
                    changed.append(row)
            return _Resp(changed)
        return _Resp([r for r in rows if self._matches(r)])


class _RPC:
    def __init__(self, client, name, params):
        self.client = client
        self.name = name
        self.params = params

    def execute(self):
        if self.name in self.client.rpc_errors:
            raise self.client.rpc_errors[self.name]
        return _Resp(self.client.rpc_results.get(self.name))


class FakeSupabase:
    def __init__(self):
        self.rows: dict[str, list[dict]] = {}
        self.rpc_results: dict[str, object] = {}
        self.rpc_errors: dict[str, Exception] = {}

    def table(self, name):
        return _Query(self, name)

    def rpc(self, name, params):
        return _RPC(self, name, params)


def test_consume_uses_rpc_and_reports_consumed():
    client = FakeSupabase()
    client.rpc_results["consume_daily_quota"] = -1

    assert consume_daily_quota_sync(client, "u1", "search", 5) == -1
    # The atomic path must not touch the table directly.
    assert client.rows.get("daily_usage") is None


def test_consume_refuses_when_rpc_reports_exhausted():
    client = FakeSupabase()
    client.rpc_results["consume_daily_quota"] = 0

    assert consume_daily_quota_sync(client, "u1", "search", 5) == 0


def test_consume_falls_back_to_direct_path_and_increments_once():
    client = FakeSupabase()
    client.rpc_errors["consume_daily_quota"] = RuntimeError("function missing")
    client.rows["daily_usage"] = [{
        "user_id": "u1", "date": _today(), "searches_run": 2, "ai_calls": 0,
    }]

    assert consume_daily_quota_sync(client, "u1", "search", 5) == -1
    assert client.rows["daily_usage"][0]["searches_run"] == 3


def test_consume_direct_path_refuses_at_the_cap():
    client = FakeSupabase()
    client.rpc_errors["consume_daily_quota"] = RuntimeError("function missing")
    client.rows["daily_usage"] = [{
        "user_id": "u1", "date": _today(), "searches_run": 5, "ai_calls": 0,
    }]

    assert consume_daily_quota_sync(client, "u1", "search", 5) == 0
    assert client.rows["daily_usage"][0]["searches_run"] == 5  # not incremented


def test_consume_direct_path_creates_the_row_for_the_right_column():
    client = FakeSupabase()
    client.rpc_errors["consume_daily_quota"] = RuntimeError("function missing")

    assert consume_daily_quota_sync(client, "u1", "ai", 5) == -1
    row = client.rows["daily_usage"][0]
    assert row["ai_calls"] == 1
    assert row["searches_run"] == 0


def test_consume_allows_the_request_when_counters_are_unavailable():
    """A missing daily_usage table must not lock a paying user out."""

    class _Broken(FakeSupabase):
        def table(self, name):
            raise RuntimeError("relation does not exist")

    broken = _Broken()
    broken.rpc_errors["consume_daily_quota"] = RuntimeError("rpc missing")

    assert consume_daily_quota_sync(broken, "u1", "search", 5) == -1


def test_consume_rejects_unknown_kind_and_zero_limit():
    client = FakeSupabase()

    assert consume_daily_quota_sync(client, "u1", "nonsense", 5) == 0
    assert consume_daily_quota_sync(client, "u1", "search", 0) == 0


def test_refund_prefers_rpc_then_clamps_direct_path():
    client = FakeSupabase()
    client.rpc_results["refund_daily_quota"] = None
    refund_daily_quota_sync(client, "u1", "search")
    assert client.rows.get("daily_usage") is None  # RPC did the work

    fallback = FakeSupabase()
    fallback.rpc_errors["refund_daily_quota"] = RuntimeError("missing")
    fallback.rows["daily_usage"] = [{
        "user_id": "u1", "date": _today(), "searches_run": 3, "ai_calls": 0,
    }]
    refund_daily_quota_sync(fallback, "u1", "search")
    assert fallback.rows["daily_usage"][0]["searches_run"] == 2

    # Clamped: never goes negative (daily_usage has CHECK (>= 0)).
    refund_daily_quota_sync(fallback, "u1", "search")
    refund_daily_quota_sync(fallback, "u1", "search")
    refund_daily_quota_sync(fallback, "u1", "search")
    assert fallback.rows["daily_usage"][0]["searches_run"] == 0


def test_ai_limit_consumes_through_the_atomic_helper(monkeypatch):
    """check_ai_limit must consume (not merely read) the monthly AI allowance (v16)."""
    from app.routers import ai as ai_router

    consumed: list[tuple] = []

    async def _fake_consume(supabase, user_id, kind, limit):
        consumed.append((user_id, kind, limit))
        return -1

    monkeypatch.setattr(ai_router, "get_supabase_admin", lambda: FakeSupabase())
    monkeypatch.setattr(
        ai_router, "resolve_effective_subscription",
        lambda supabase, user_id: {"plan_id": "pro", "status": "active"},
    )
    import app.services.usage as usage_module
    monkeypatch.setattr(usage_module, "consume_monthly_quota", _fake_consume)

    plan_id = asyncio.run(ai_router.check_ai_limit("user-1"))

    assert plan_id == "pro"
    assert consumed == [("user-1", "ai", 100)]


def test_ai_limit_raises_429_when_quota_is_exhausted(monkeypatch):
    from fastapi import HTTPException

    from app.routers import ai as ai_router

    async def _refuse(supabase, user_id, kind, limit):
        return 0

    monkeypatch.setattr(ai_router, "get_supabase_admin", lambda: FakeSupabase())
    monkeypatch.setattr(
        ai_router, "resolve_effective_subscription",
        lambda supabase, user_id: {"plan_id": "free", "status": "active"},
    )
    import app.services.usage as usage_module
    monkeypatch.setattr(usage_module, "consume_monthly_quota", _refuse)

    try:
        asyncio.run(ai_router.check_ai_limit("user-1"))
    except HTTPException as exc:
        assert exc.status_code == 429
    else:  # pragma: no cover
        raise AssertionError("expected HTTPException(429)")


def test_monthly_rejection_gives_the_daily_unit_back(monkeypatch):
    """A 403 from the monthly quota must not also burn a monthly search (v16).

    `check_search_limit` consumes the monthly unit before the handler runs, so
    every rejection path in between has to refund it.
    """
    from fastapi import HTTPException

    import app.services.plans as plans_module
    import app.services.usage as usage_module
    from app.routers import search as search_router
    from app.schemas.search import SearchCreateRequest

    client = FakeSupabase()
    client.rows["monthly_usage"] = [{
        "user_id": "u1", "usage_month": _month(), "searches_used": 1, "ai_calls_used": 0,
    }]
    client.rows["daily_usage"] = []
    # Exercise the direct-path refund (what a pre-v16 schema does).
    client.rpc_errors["refund_monthly_quota"] = RuntimeError("function missing")

    async def _reserve_nothing(*args, **kwargs):
        return 0

    monkeypatch.setattr(search_router, "get_supabase_admin", lambda: client)
    monkeypatch.setattr(usage_module, "reserve_monthly_leads", _reserve_nothing)
    monkeypatch.setattr(
        plans_module, "resolve_effective_subscription",
        lambda supabase, user_id: {"plan_id": "free", "status": "active"},
    )
    monkeypatch.setattr(
        plans_module, "get_plan_row",
        lambda supabase, plan_id: {"id": "free", "gmb_leads_monthly": 30},
    )

    request = SearchCreateRequest(niche="plumbers", location="Dallas TX")
    try:
        asyncio.run(
            search_router.create_search(request, None, current_user={"id": "u1"})
        )
    except HTTPException as exc:
        assert exc.status_code == 403
    else:  # pragma: no cover
        raise AssertionError("expected HTTPException(403)")

    assert client.rows["monthly_usage"][0]["searches_used"] == 0  # refunded


def _month() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(day=1).date().isoformat()


def _today() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).date().isoformat()


def test_monthly_consume_and_refund_roundtrip():
    client = FakeSupabase()
    client.rpc_errors["consume_monthly_quota"] = RuntimeError("function missing")
    client.rpc_errors["refund_monthly_quota"] = RuntimeError("function missing")
    assert consume_monthly_quota_sync(client, "u9", "search", 15) == -1
    row = client.rows["monthly_usage"][0]
    assert row["searches_used"] == 1
    refund_monthly_quota_sync(client, "u9", "search")
    assert client.rows["monthly_usage"][0]["searches_used"] == 0


def test_monthly_consume_refuses_at_cap():
    client = FakeSupabase()
    client.rpc_errors["consume_monthly_quota"] = RuntimeError("function missing")
    client.rows["monthly_usage"] = [{
        "user_id": "u9", "usage_month": _month(), "searches_used": 15, "ai_calls_used": 0,
    }]
    assert consume_monthly_quota_sync(client, "u9", "search", 15) == 0
    assert client.rows["monthly_usage"][0]["searches_used"] == 15
