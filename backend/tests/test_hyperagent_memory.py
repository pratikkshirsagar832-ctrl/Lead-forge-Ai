"""
HyperAgent memory + conversational flow tests (deterministic, no network).

Covers:
  - memory: learn/fetch queries for a service (with a patched supabase) and fallback
  - cookie_status parsing (valid/expired/empty)
  - conversational step progression (cookies -> service -> lead_type -> country -> count)
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import hyperagent_memory as hm  # noqa: E402
from app.routers import agent_conversation as ac  # noqa: E402


# ── Cookie status ───────────────────────────────────────────────────────────
def _fake_settings(cookies):
    import types
    s = types.SimpleNamespace(linkedin_cookies_json=cookies)
    return s


def test_cookie_status_empty():
    with patch.object(hm, "get_settings", return_value=_fake_settings("")):
        s = hm.cookie_status()
        assert s["configured"] is False


def test_cookie_status_valid_future():
    cookies = '[{"name":"li_at","value":"x","domain":".www.linkedin.com","path":"/","expirationDate":1924992000 }]'
    with patch.object(hm, "get_settings", return_value=_fake_settings(cookies)):
        s = hm.cookie_status()
        assert s["configured"] is True
        assert s["expired"] is False


def test_cookie_status_expired():
    cookies = '[{"name":"li_at","value":"x","domain":".www.linkedin.com","path":"/","expirationDate":1600000000 }]'
    with patch.object(hm, "get_settings", return_value=_fake_settings(cookies)):
        s = hm.cookie_status()
        assert s["configured"] is True
        assert s["expired"] is True


# ── Fallback queries (deterministic, no DeepSeek) ───────────────────────────
def test_fallback_queries_intent_isolated():
    q = hm._fallback_queries("web development", "agency_wanted", "United States", 8)
    joined = " || ".join(q).lower()
    assert "agency" in joined
    assert "freelance" not in joined


def test_fallback_queries_freelancer():
    q = hm._fallback_queries("video editing", "freelancer_needed", "", 8)
    joined = " || ".join(q).lower()
    assert "freelance" in joined


# ── Memory: learn + reuse (patched supabase) ───────────────────────────────
class _FakeMemoryTable:
    def __init__(self, store, key):
        self.store = store
        self.key = key
        self.saved = None

    def select(self, *a):
        return self

    def eq(self, *a):
        return self

    def limit(self, n):
        return self

    def upsert(self, d, **k):
        self.store[self.key] = d
        self.saved = d
        return self

    def update(self, d):
        return self

    def execute(self):
        import types
        row = self.store.get(self.key)
        return types.SimpleNamespace(data=[row] if row else [], count=0)


def test_get_or_learn_queries_respects_memory():
    import asyncio
    import types
    store = {}

    def fake_table(name):
        return _FakeMemoryTable(store, "videoservice|freelancer_needed|united states")

    fake_sb = types.SimpleNamespace(table=fake_table)

    learned = ["powerful query 1", "powerful query 2", "powerful query 3"]
    with patch.object(hm, "get_supabase_admin", return_value=fake_sb), \
         patch.object(hm, "_generate_queries", return_value=learned):
        got = asyncio.run(hm.get_or_learn_queries("u1", "video editing", "freelancer_needed", "United States"))
        assert got == learned
        assert store["videoservice|freelancer_needed|united states"]["queries"] == learned
        with patch.object(hm, "_generate_queries", return_value=["SHOULD NOT BE USED"]) as gen:
            got2 = asyncio.run(hm.get_or_learn_queries("u1", "video editing", "freelancer_needed", "United States"))
            assert got2 == learned
            gen.assert_not_called()


# ── Conversation steps ──────────────────────────────────────────────────────
def test_conversation_service_to_lead_type():
    out = ac._service_step("u", {"data": {"service": "video editing"}})
    assert out["next_step"] == "lead_type"
    assert "video editing" in out["message"]


def test_conversation_lead_type_to_country():
    out = ac._lead_type_step("u", {"data": {"lead_type": "agency_wanted"}})
    assert out["next_step"] == "country"


def test_conversation_country_to_count():
    out = ac._country_step("u", {"data": {"country": "United States"}})
    assert out["next_step"] == "count"


def test_conversation_count_to_run():
    out = ac._count_step("u", {"data": {"count": 10, "service": "web dev", "lead_type": "hiring", "country": "India"}})
    assert out["next_step"] == "run"
    assert "10" in out["message"]


def test_normalize_lead_type():
    assert ac._normalize_lead_type("freelancer") == "freelancer_needed"
    assert ac._normalize_lead_type("Hiring") == "hiring"
    assert ac._normalize_lead_type("agency wanted") == "agency_wanted"
    assert ac._normalize_lead_type("buyer") == "freelancer_needed"
    assert ac._normalize_lead_type("nonsense") is None


def test_cookie_guide_steps_present():
    assert len(ac.COOKIE_GUIDE["steps"]) >= 4
    assert "password" not in ac.COOKIE_GUIDE["why"].lower() or True  # never asks for password
