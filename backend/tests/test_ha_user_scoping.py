"""Regression tests: LinkedIn engine rows must carry their owner.

`ha_searches` / `ha_leads` are owner-scoped by RLS (migration v8), but the
engine never wrote `user_id`, so every new row was NULL-owned and could not be
attributed (or read by any policy-scoped client). These tests pin the wiring:
the service-level wrappers stamp the owner, and the Supabase store degrades
cleanly on a pre-v8 schema where the column does not exist yet.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ha.db import SupabaseStore  # noqa: E402

from app.services.hyperagent_service import (  # noqa: E402
    _ForceTypeStore,
    _UserScopedStore,
)


class _Resp:
    def __init__(self, data):
        self.data = data


class _FakeClient:
    """Minimal client: `.table(name).select(cols).limit(n).execute()`."""

    def __init__(self, tables: set[str], columns: set[str]):
        self.tables = tables
        self.columns = columns
        self.inserted: list[tuple[str, dict]] = []

    def table(self, name: str):
        client = self
        if name not in client.tables:
            raise AssertionError(f"unexpected table {name!r}")

        class _Q:
            def __init__(self):
                self.kind = "select"
                self.payload = None
                self.upserted = None

            def select(self, cols="*"):
                for col in str(cols).split(","):
                    if col.strip() and col.strip() not in client.columns:
                        raise RuntimeError(f"column {col.strip()} does not exist")
                return self

            def limit(self, n):
                return self

            def insert(self, payload):
                self.kind = "insert"
                self.payload = payload
                return self

            def upsert(self, payload, on_conflict=None, ignore_duplicates=False):
                self.kind = "upsert"
                self.payload = payload
                return self

            def execute(self):
                if self.kind in ("insert", "upsert"):
                    rows = self.payload if isinstance(self.payload, list) else [self.payload]
                    for r in rows:
                        client.inserted.append((name, dict(r)))
                    return _Resp(rows)
                return _Resp([])

        return _Q()


def _store(client) -> SupabaseStore:
    """A SupabaseStore with the network client swapped out."""
    store = object.__new__(SupabaseStore)
    store._client = client
    store._user_col_cache = {}
    return store


class _RecordingInner:
    """Inner store that records what it was asked to persist."""

    def __init__(self):
        self.rows: list[dict] = []
        self.last_user_id = "unset"

    def insert_leads_many(self, rows, user_id=None):
        self.rows = [dict(r) for r in rows]
        self.last_user_id = user_id
        return len(self.rows)


def test_user_scoped_store_stamps_owner_on_leads():
    inner = _RecordingInner()
    store = _UserScopedStore(inner, "user-1")

    store.insert_leads_many([{"post_url": "https://x/1", "post_text": "hire me"}])

    assert inner.last_user_id == "user-1"


def test_force_type_wrapper_keeps_owner_through_the_chain():
    """Production chain: _ForceTypeStore(_UserScopedStore(SupabaseStore))."""
    inner = _RecordingInner()
    store = _ForceTypeStore(_UserScopedStore(inner, "user-9"), "need_freelancer",
                            user_id="user-9")

    store.insert_leads_many([{"post_url": "https://x/2", "post_text": "need a freelancer"}])

    assert inner.last_user_id == "user-9"
    assert inner.rows[0]["lead_type"] == "need_freelancer"


def test_supabase_store_stamps_user_id_when_column_exists():
    client = _FakeClient(tables={"ha_leads"}, columns={"user_id", "post_url"})
    store = _store(client)

    store.insert_leads_many([{"post_url": "https://x/3"}], user_id="user-2")

    assert client.inserted[0][1]["user_id"] == "user-2"


def test_supabase_store_drops_user_id_on_pre_v8_schema():
    client = _FakeClient(tables={"ha_leads"}, columns={"post_url"})
    store = _store(client)

    store.insert_leads_many([{"post_url": "https://x/4"}], user_id="user-2")

    assert "user_id" not in client.inserted[0][1]
    # Negative probes are NOT cached permanently: caching False would pin the
    # process to the degraded path even after v8/v12 is applied. Only True
    # is cached, so a later migration is picked up on retry.
    assert store._user_col_cache.get("ha_leads") is not True


def test_supabase_store_create_search_carries_owner_and_id():
    client = _FakeClient(
        tables={"ha_searches"},
        columns={"user_id", "service", "country", "lead_type", "time_window",
                 "leads_needed", "id"},
    )
    store = _store(client)

    store.create_search(
        service="video editing", country="", lead_type="need_freelancer",
        time_window="7d", leads_needed=5, search_id="search-1", user_id="user-3",
    )

    table, row = client.inserted[0]
    assert table == "ha_searches"
    assert row["id"] == "search-1"
    assert row["user_id"] == "user-3"
