"""Exact-N delivery + any-input service handling (offline)."""
from datetime import UTC, datetime, timedelta

import pytest

from db import MemoryStore
from discovery.base import RawPost, SearchBatchResult
from engine import run_search
from models import LeadClassification, LeadType
from query_builder import build_plan, is_messy_service, query_phrases, service_phrases


def _settings(**overrides):
    from config import Settings

    base = dict(freshness_ladder="", engine_prefetch=False)
    base.update(overrides)
    return Settings(**base)


def _verdict(**kw):
    base = dict(
        lead_type="need_freelancer", intent_strength="explicit", is_buying_sourcing=True,
        is_selling_offering=False, is_job_seek=False, service_match_score=92.0,
        commercial_intent_score=85.0, decision_maker_signal=True, evidence_strength=85.0,
        overall_quality_score=88.0, is_qualified=True, confidence=0.9,
        evidence="need help", reason="buyer",
    )
    base.update(kw)
    return LeadClassification(**base)


class Clf:
    def __init__(self, fn=lambda c: _verdict()):
        self.fn = fn
        self.calls = 0

    def classify_batch(self, candidates, **kwargs):
        self.calls += len(candidates)
        return [self.fn(c) for c in candidates]


class Disc:
    """Every call returns `per_call` brand-new posts; records the queries."""

    name = "disc"

    def __init__(self, per_call=1, limit=10_000):
        self.per_call = per_call
        self.limit = limit
        self.calls = 0
        self.queries: list[list[str]] = []
        self._n = 0

    def search_posts(self, queries, since, **_kw):
        self.calls += 1
        self.queries.append(list(queries))
        posts = []
        for _ in range(self.per_call):
            if self._n >= self.limit:
                break
            self._n += 1
            posts.append(RawPost(post_url=f"https://www.linkedin.com/posts/p-{self._n}",
                                 text=f"need help with this {self._n}", author_name="A",
                                 posted_at=datetime.now(UTC) - timedelta(hours=self._n % 100 + 1)))
        return SearchBatchResult(posts=posts, queries_used=list(queries))


def _search(store, service="video editor", needed=5, lead_type="need_freelancer"):
    return store.create_search(service=service, country="", lead_type=lead_type,
                               time_window="7d", leads_needed=needed)["id"]


# ------------------------------------------------------------ any input

@pytest.mark.parametrize("raw,expected", [
    ("a video editor", ["a video editor"]),
    ("I am a video editor", ["video editor"]),
    ("I'm a freelance UI/UX designer", ["UI/UX designer"]),
    ("we offer SEO services for startups", ["SEO"]),
    ("need clients for my bookkeeping business 🙏", ["bookkeeping"]),
    ("Web design & development", ["Web design", "Web development"]),
    ("Shopify store setup, logo design, branding", ["Shopify store setup", "logo design", "branding"]),
    ("plumber in Nairobi", ["plumber"]),
    ("2D/3D animation", ["2D/3D animation"]),
    ("chartered accountant", ["chartered accountant"]),
    ("divorce lawyer", ["divorce lawyer"]),
])
def test_service_phrases_from_any_input(raw, expected):
    assert service_phrases(raw) == expected


def test_any_input_produces_clean_quoted_queries():
    plan = build_plan("I am a freelance video editor for YouTubers", LeadType.NEED_FREELANCER)
    assert query_phrases(plan.base[0])[0] == "looking for a video editor"
    agency = build_plan("we are an SEO agency", LeadType.NEED_AGENCY)
    phrases = [p for q in agency.base for p in query_phrases(q)]
    assert "looking for an agency for SEO" in phrases
    assert not any("agency agency" in p for p in phrases)


@pytest.mark.parametrize("raw", ["", "   ", "!!!", "x" * 300, "मुझे वीडियो एडिटिंग क्लाइंट चाहिए",
                                 "we do everything: web, apps, seo, ads, design, video, ai, bots"])
def test_weird_inputs_never_crash_and_always_emit_queries(raw):
    for lt in (LeadType.NEED_FREELANCER, LeadType.NEED_AGENCY):
        plan = build_plan(raw or "x", lt)
        assert plan.base  # always something to search


def test_messy_detection():
    assert not is_messy_service("video editing")
    assert is_messy_service("helping ambitious creators turn raw long form footage into viral shorts")


def test_messy_input_waits_for_llm_canonical_service_in_round_zero():
    from llm_queries import Expansion

    def expander(service, avoid=None):
        return Expansion(["need a shorts editor for our channel"],
                         canonical_services=["short-form video editing"])

    disc = Disc(per_call=0)
    store = MemoryStore()
    sid = _search(store, service="helping ambitious creators turn raw long form footage into viral shorts")
    run_search(sid, store=store, discovery=disc, classifier=Clf(), query_expander=expander,
               settings=_settings(engine_max_iterations=1))
    first = [p for q in disc.queries[0] for p in query_phrases(q)]
    assert "need a shorts editor for our channel" in first
    assert any("short-form video editor" in p for p in first)  # canonical service templates
    assert not any("helping ambitious creators" in p for p in first)


def test_secondary_services_are_searched_too():
    disc = Disc(per_call=0)
    store = MemoryStore()
    sid = _search(store, service="logo design, video editing")
    run_search(sid, store=store, discovery=disc, classifier=Clf(),
               settings=_settings(engine_max_iterations=3, engine_early_stop_empty_rounds=10))
    later = [p for qs in disc.queries[1:] for q in qs for p in query_phrases(q)]
    assert any("video editor" in p for p in later)


# ------------------------------------------------------------- exact N

@pytest.mark.parametrize("needed", [1, 3, 7, 12])
def test_never_more_than_requested(needed):
    store = MemoryStore()
    sid = _search(store, needed=needed)
    summary = run_search(sid, store=store, discovery=Disc(per_call=25), classifier=Clf(),
                         settings=_settings())
    assert summary.accepted == needed
    assert len(store.list_leads(search_id=sid)) == needed


def test_pool_refill_keeps_searching_until_n():
    """The deterministic pool runs dry, the LLM refill supplies fresh
    phrasings, and the search still reaches exactly N."""
    calls = {"refill": 0}

    def expander(service, avoid=None):
        if avoid:
            calls["refill"] += 1
            return [f"fresh angle {calls['refill']}-{i}" for i in range(12)]
        return []

    disc = Disc(per_call=2)
    store = MemoryStore()
    sid = _search(store, needed=45)
    summary = run_search(sid, store=store, discovery=disc, classifier=Clf(), query_expander=expander,
                         settings=_settings(engine_max_iterations=80, engine_early_stop_empty_rounds=50,
                                            max_discovery_requests_per_search=0,
                                            max_deepseek_calls_per_search=0, max_query_refills=6))
    assert calls["refill"] >= 1
    assert summary.accepted == 45
    used = [p for qs in disc.queries for q in qs for p in query_phrases(q)]
    assert any(p.startswith("fresh angle") for p in used)


def test_legacy_fallback_after_refills_are_exhausted():
    disc = Disc(per_call=1)
    store = MemoryStore()
    sid = _search(store, needed=60)
    run_search(sid, store=store, discovery=disc, classifier=Clf(),
               settings=_settings(engine_max_iterations=80, engine_early_stop_empty_rounds=50,
                                  max_discovery_requests_per_search=0, max_deepseek_calls_per_search=0))
    flat = [q for qs in disc.queries for q in qs]
    assert any(q.startswith("(") or q.startswith('"') for q in flat)       # packed first
    assert any(not q.startswith(("(", '"')) for q in flat)                 # then broad legacy
    assert len(flat) == len(set(flat))                                     # never a repeat


def test_insert_conflicts_are_backfilled_to_exactly_n():
    """A post another account already owns (pre-v18 global unique) is skipped
    on insert; the engine backfills from the next-newest accepted lead."""
    store = MemoryStore()
    # Another user already owns p-1 (the newest post this search will find).
    store.insert_leads_many([{"post_url": "https://www.linkedin.com/posts/p-1", "lead_type": "need_freelancer"}],
                            user_id="someone-else")

    class OwnershipBlind(MemoryStore):
        pass

    sid = _search(store, needed=3)
    # Hide the other user's row from the per-user ownership check, like the
    # user-scoped Supabase lookup does.
    store.find_existing_post_urls = lambda urls, user_id=None: set()  # type: ignore[assignment]
    summary = run_search(sid, store=store, discovery=Disc(per_call=6), classifier=Clf(),
                         settings=_settings())
    assert summary.accepted == 3
    urls = {l["post_url"] for l in store.list_leads(search_id=sid)}
    assert len(urls) == 3 and "https://www.linkedin.com/posts/p-1" not in urls


def test_budget_scales_with_leads_requested():
    """Base ceilings for small requests; per-lead scaling (hard-capped) for big ones."""
    def run(needed):
        disc = Disc(per_call=0)
        store = MemoryStore()
        sid = _search(store, needed=needed)
        run_search(sid, store=store, discovery=disc, classifier=Clf(),
                   settings=_settings(max_discovery_requests_per_search=5, discovery_requests_per_lead=2,
                                      max_discovery_requests_hard=30, engine_max_iterations=200,
                                      engine_early_stop_empty_rounds=500, max_query_refills=0))
        return disc.calls

    assert run(1) <= 5 + 1          # base ceiling
    assert 5 < run(10) <= 20 + 1    # 2 per lead
    assert run(100) <= 30 + 1       # hard cap
