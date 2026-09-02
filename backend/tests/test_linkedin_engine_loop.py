"""
Engine-loop integration tests (deterministic, no live Apify/OpenAI).

We drive the pure `_run_engine_with_externals` core directly with injected
discovery + classification + a fake Supabase, so we can verify the ITERATIVE
EXACT-COUNT loop, country hard-gate, dedupe and the "never pad" invariant
end-to-end without any network access.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import linkedin_pipeline as lp  # noqa: E402
from app.services.ai_service import LeadClassification, attach_classification, candidate_key  # noqa: E402
from tests.conftest import candidate, make_classification  # noqa: E402


# ── Fake Supabase admin (swallows writes) ──────────────────────────────────
class FakeSupabase:
    def __init__(self):
        self.written = []

    def table(self, name):
        return FakeTable(name, self)

    def rpc(self, name, params):
        return type("RPC", (), {"execute": lambda self: type("R", (), {"data": None, "count": None})()})()


class FakeTable:
    def __init__(self, name, parent):
        self.name = name
        self.parent = parent

    def select(self, *cols):
        return self

    def eq(self, *a):
        return self

    def neq(self, *a):
        return self

    def limit(self, n):
        return self

    def order(self, *a):
        return self

    def range(self, *a):
        return self

    def update(self, data):
        return self

    def insert(self, data):
        self.parent.written.append(("insert", self.name, data))
        return self

    def execute(self):
        return type("R", (), {"data": [], "count": 0})()


def _raw(item):
    return {
        "id": item.get("post_id"),
        "url": item.get("post_url"),
        "content": item.get("post_text"),
        "postedAt": "2026-08-01T00:00:00+00:00",
        "author": {
            "name": item.get("full_name"),
            "url": item.get("linkedin_url"),
            "info": item.get("headline"),
            "location": {"countryCode": item.get("country_code"), "linkedinText": item.get("location")},
            "currentPosition": [{"companyName": item.get("company")}] if item.get("company") else [],
        },
    }


def make_discover(iterations):
    """Return a SYNC discover callable that yields each fixture batch in turn."""
    batches = list(iterations)
    def _discover(queries):
        if not batches:
            # provider_total=0 => search space exhausted, NOT a provider failure.
            return (0, 0, [], [])
        return batches.pop(0)
    return _discover


def make_classify(classification_by_identity):
    """Return an async classify keyed by candidate_key(candidate) — the SAME key
    the engine uses to look up a classification (default is linkedin_url)."""
    async def _classify(client, service, country, candidates):
        out = {}
        for c in candidates:
            key = candidate_key(c)
            cls_dict = classification_by_identity.get(key)
            if cls_dict:
                out[key] = LeadClassification(**cls_dict)
        return out
    return _classify


async def _run(supabase, request, discover, classify, known_urls=None):
    return await lp._run_engine_with_externals(
        supabase=supabase,
        request=request,
        client=object(),
        known_urls=known_urls or set(),
        discover=discover,
        classify=classify,
        attach_classification=attach_classification,
        candidate_key=candidate_key,
    )


def _request(count, lead_types=None, service="web development", country="US"):
    return lp.LeadRequest(
        search_id="s1", user_id="u1", service=service,
        request_count=count, lead_types=lead_types or ["agency_wanted"],
        country_codes={"US"}, country_text=country, enrich_emails=False,
    )


# ── TEST 1: iterative exact-count reaches target, no over-delivery ─────────
def test_iterative_exact_count_reaches_target():
    supabase = FakeSupabase()
    def gen(prefix, n):
        return [candidate(post_id=f"{prefix}{i}", linkedin_url=f"https://www.linkedin.com/in/{prefix}{i}",
                          post_text="We need a web development agency for our project.",
                          country_code="US", location="New York, US", full_name=f"{prefix}{i}")
                for i in range(n)]

    batches = [
        (1, 1, [_raw(c) for c in gen("a", 3)], []),
        (1, 1, [_raw(c) for c in gen("b", 2)], []),
        (1, 1, [_raw(c) for c in gen("c", 3)], []),
        (1, 1, [_raw(c) for c in gen("d", 3)], []),
    ]
    cls = {}
    for prefix, n in (("a", 3), ("b", 2), ("c", 3), ("d", 3)):
        for i in range(n):
            cls[f"https://www.linkedin.com/in/{prefix}{i}"] = make_classification(lead_type="agency_wanted", service_match=92, quality=90)

    import asyncio
    telemetry = asyncio.run(_run(supabase, _request(10), make_discover(batches), make_classify(cls)))
    assert telemetry["final_valid_count"] == 10
    assert telemetry["status"] == "complete"
    assert telemetry["request_count"] == 10
    # Never more than target.
    assert len(telemetry["iterations"]) >= 2  # needed multiple iterations


# ── TEST 2: wrong-country leads are never padded ───────────────────────────
def test_wrong_country_leads_not_padded():
    supabase = FakeSupabase()
    us1 = candidate(post_id="us1", linkedin_url="https://www.linkedin.com/in/us1",
                    post_text="Need a web development agency.", country_code="US", location="US")
    us2 = candidate(post_id="us2", linkedin_url="https://www.linkedin.com/in/us2",
                    post_text="Seeking a web development agency.", country_code="US", location="US")
    wrong = [candidate(post_id=f"in{i}", linkedin_url=f"https://www.linkedin.com/in/in{i}",
                       post_text="Need web dev agency.", country_code="IN", location="Mumbai, India")
             for i in range(4)]
    cls = {c["linkedin_url"]: make_classification(lead_type="agency_wanted", quality=90) for c in [us1, us2] + wrong}
    import asyncio
    telemetry = asyncio.run(_run(supabase, _request(10),
                                 make_discover([(1, 1, [_raw(c) for c in [us1, us2] + wrong], [])]),
                                 make_classify(cls)))
    assert telemetry["final_valid_count"] == 2  # only US, no IN padding
    assert telemetry["status"] == "exhausted"


# ── TEST 3: sellers + job-seekers never pad; loop terminates safely ────────
def test_sellers_never_pad_and_loop_terminates():
    supabase = FakeSupabase()
    gen = candidate(post_id="g1", linkedin_url="https://www.linkedin.com/in/g1",
                    post_text="We need a web development agency.", country_code="US", location="US")
    sellers = [candidate(post_id=f"s{i}", linkedin_url=f"https://www.linkedin.com/in/s{i}",
                         post_text="We offer web development services. DM us.", country_code="US",
                         location="US", full_name=f"Seller{i}") for i in range(3)]
    seeker = candidate(post_id="j1", linkedin_url="https://www.linkedin.com/in/j1",
                       post_text="I am open to work as a developer.", country_code="US", location="US", full_name="JS")
    all_items = [gen] + sellers + [seeker]
    cls = {"https://www.linkedin.com/in/g1": make_classification(lead_type="agency_wanted", quality=90, is_qualified=True)}
    for c in sellers:
        cls[c["linkedin_url"]] = make_classification(seller=True, is_qualified=False, rejection_reason="seller")
    cls["https://www.linkedin.com/in/j1"] = make_classification(job_seeker=True, is_qualified=False, rejection_reason="job_seeker")
    batches = [(1, 1, [_raw(c) for c in all_items], []) for _ in range(6)]
    import asyncio
    telemetry = asyncio.run(_run(supabase, _request(10), make_discover(batches), make_classify(cls)))
    assert telemetry["final_valid_count"] == 1  # only genuine lead
    assert telemetry["reason"] == "no_progress"  # loop stopped safely


# ── TEST 4: sparse market returns only what exists ─────────────────────────
def test_sparse_market_returns_only_available():
    supabase = FakeSupabase()
    genuine = [candidate(post_id=f"z{i}", linkedin_url=f"https://www.linkedin.com/in/z{i}",
                         post_text="Need a web dev agency for our company.", country_code="US",
                         location="US", full_name=f"Z{i}") for i in range(4)]
    cls = {c["linkedin_url"]: make_classification(lead_type="agency_wanted", quality=90) for c in genuine}
    import asyncio
    telemetry = asyncio.run(_run(supabase, _request(20), make_discover([(1, 1, [_raw(c) for c in genuine], [])]),
                                 make_classify(cls)))
    assert telemetry["final_valid_count"] == 4  # never padded to 20


# ── TEST 5: duplicate author does not occupy multiple slots ────────────────
def test_dedupe_same_author_one_slot():
    supabase = FakeSupabase()
    # Same author (same linkedin_url) with 2 posts; both classified qualified.
    p1 = candidate(post_id="p1", post_url="https://www.linkedin.com/feed/a", linkedin_url="https://www.linkedin.com/in/same",
                   post_text="Need a web development agency.", country_code="US", location="US")
    p2 = candidate(post_id="p2", post_url="https://www.linkedin.com/feed/b", linkedin_url="https://www.linkedin.com/in/same",
                   post_text="Also seeking a web development agency.", country_code="US", location="US")
    cls = {c["linkedin_url"]: make_classification(lead_type="agency_wanted", quality=90) for c in [p1, p2]}
    import asyncio
    telemetry = asyncio.run(_run(supabase, _request(10), make_discover([(1, 1, [_raw(p1), _raw(p2)], [])]),
                                 make_classify(cls)))
    assert telemetry["final_valid_count"] == 1  # one author = one slot


# ── TEST 6: transient provider empty does NOT abort on the first hit ───────
def test_provider_empty_does_not_abort_immediately():
    supabase = FakeSupabase()
    # Iter1: total provider failure (empty). Iter2: supplies 2 valid leads.
    gen = [candidate(post_id=f"g{i}", linkedin_url=f"https://www.linkedin.com/in/g{i}",
                     post_text="We need a web development agency.", country_code="US", location="US") for i in range(2)]
    cls = {c["linkedin_url"]: make_classification(lead_type="agency_wanted", quality=90) for c in gen}
    batches = [
        (0, 3, [], ["all lanes failed"]),          # transient total failure
        (3, 3, [_raw(c) for c in gen], []),        # recovery
    ]
    import asyncio
    telemetry = asyncio.run(_run(supabase, _request(10), make_discover(batches), make_classify(cls)))
    # The engine must recover after a single empty provider run and save 2 leads.
    assert telemetry["final_valid_count"] == 2
    assert telemetry["reason"] != "provider_failure"


# ── TEST 7: persistent provider failure terminates safely ──────────────────
def test_persistent_provider_failure_terminates():
    supabase = FakeSupabase()
    batches = [(0, 3, [], ["fail"]) for _ in range(5)]
    import asyncio
    telemetry = asyncio.run(_run(supabase, _request(10), make_discover(batches), make_classify({})))
    assert telemetry["final_valid_count"] == 0
    assert telemetry["reason"] == "provider_failure"
    assert len(telemetry["iterations"]) <= lp.MAX_PROVIDER_FAIL_ROUNDS


# ── TEST 8: hiring country gate rejects a foreign-jobs posting ─────────────
def test_hiring_gate_rejects_foreign_job_location():
    supabase = FakeSupabase()
    # Author is US but the job posting is explicitly in Pakistan (non-remote).
    bad = candidate(post_id="pak", linkedin_url="https://www.linkedin.com/in/pak",
                    post_text="We are hiring a Graphic Designer. Location: Islamabad, Pakistan. Full-time onsite.",
                    country_code="US", location="San Francisco, US", headline="HR at Acme")
    cls = {bad["linkedin_url"]: make_classification(lead_type="hiring", quality=90, is_qualified=True)}
    import asyncio
    telemetry = asyncio.run(_run(supabase, _request(3, lead_types=["hiring"], service="graphic design"),
                                 make_discover([(1, 1, [_raw(bad)], [])]), make_classify(cls)))
    assert telemetry["final_valid_count"] == 0  # wrong-country job => not saved


# ── TEST 9: hiring gate allows a remote (location-agnostic) job ────────────
def test_hiring_gate_allows_remote_job():
    supabase = FakeSupabase()
    good = candidate(post_id="rem", linkedin_url="https://www.linkedin.com/in/rem",
                     post_text="We are hiring a Graphic Designer, fully remote, work from anywhere.",
                     country_code="US", location="New York, US", headline="HR at Acme")
    cls = {good["linkedin_url"]: make_classification(lead_type="hiring", quality=90, is_qualified=True)}
    import asyncio
    telemetry = asyncio.run(_run(supabase, _request(3, lead_types=["hiring"], service="graphic design"),
                                 make_discover([(1, 1, [_raw(good)], [])]), make_classify(cls)))
    assert telemetry["final_valid_count"] == 1  # remote job passes the gate
