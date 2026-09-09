"""App-side wiring tests: hyperagent_service -> ha engine with PRODUCTION
settings (env-injected), offline (MemoryStore + mock providers, no network).

Covers what the ha/ unit suite cannot see: the 7d window switch, the tuned
engine env, the query-expander construction, the content-direction gate, and
an end-to-end engine run under the exact production Settings object.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

import app.services.hyperagent_service as ha_service
from discovery.base import RawPost, SearchBatchResult
from engine import run_search
from models import LeadType, TimeWindow
from testing.mock_providers import CORPUS, MockClassifier, MockDiscoveryClient


# ---------------------------------------------------------------------------
# Production env wiring
# ---------------------------------------------------------------------------

def test_time_window_is_strict_7d():
    assert ha_service.ha_time_window_from() == "7d"


def test_lead_type_mapping():
    assert ha_service.ha_lead_type_from(["buyer"]) == "need_freelancer"
    assert ha_service.ha_lead_type_from(["agency_wanted"]) == "our_agency"
    assert ha_service.ha_lead_type_from(["buyer", "agency_wanted"]) == "need_freelancer"
    assert ha_service.ha_lead_type_from(None) == "need_freelancer"


def test_production_settings_are_tuned():
    settings = ha_service._ha_settings()
    assert settings.engine_max_iterations == 20
    assert settings.engine_deadline_seconds == 540
    assert settings.engine_early_stop_empty_rounds == 5
    assert settings.max_serper_requests_per_search == 80
    assert settings.max_deepseek_calls_per_search == 150
    assert settings.accept_sibling_buyers is True
    assert settings.require_model_qualified is False
    assert settings.min_overall_score == 55.0
    assert settings.min_service_match == 45.0
    assert settings.min_intent_strength == "recommendation"
    assert settings.serper_pages_per_query == 4


def test_production_settings_drive_exact_count_engine():
    """End-to-end: the REAL production Settings object must still deliver
    exactly N qualified leads from a fresh corpus (exact-count + freshness)."""
    from config import Settings

    settings = ha_service._ha_settings()
    # Use the production-tuned gates with the offline corpus.
    production = Settings(
        engine_max_iterations=settings.engine_max_iterations,
        engine_deadline_seconds=settings.engine_deadline_seconds,
        engine_early_stop_empty_rounds=settings.engine_early_stop_empty_rounds,
        max_serper_requests_per_search=settings.max_serper_requests_per_search,
        max_deepseek_calls_per_search=settings.max_deepseek_calls_per_search,
        accept_sibling_buyers=settings.accept_sibling_buyers,
        require_model_qualified=settings.require_model_qualified,
        min_overall_score=settings.min_overall_score,
        min_service_match=settings.min_service_match,
        min_intent_strength=settings.min_intent_strength,
        serper_pages_per_query=settings.serper_pages_per_query,
    )

    from db import MemoryStore

    def _qualified_in_window(window: str) -> int:
        from testing.mock_providers import _now, _service_words

        service_words = _service_words("video editor")
        cutoff = TimeWindow(window).cutoff(datetime.now(UTC))
        return sum(
            1 for p in CORPUS
            if p.lead_type == LeadType.NEED_FREELANCER
            and _now(p.days_ago) >= cutoff
            and any(w in p.text.lower() for w in service_words)
        )

    expected = _qualified_in_window("7d")
    assert expected > 0
    store = MemoryStore()
    sid = store.create_search(
        service="video editor", country="", lead_type="need_freelancer",
        time_window="7d", leads_needed=expected,
    )["id"]
    summary = run_search(
        sid, store=store, discovery=MockDiscoveryClient(),
        classifier=MockClassifier(), settings=production,
    )
    assert summary.status == "completed"
    assert summary.accepted == expected  # exactly N — the promise holds
    assert len(store.list_leads(search_id=sid)) == expected
    cutoff = TimeWindow.DAYS_7.cutoff()
    for lead in store.list_leads(search_id=sid):
        assert lead["post_date"] >= cutoff.date()  # strictly fresh


def test_query_expander_construction_is_fail_closed():
    """make_query_expander is built for the requested lead type and never
    raises even when the classifier has no client (missing key)."""
    from llm_queries import make_query_expander

    class NoClientClassifier:
        model = "deepseek-chat"
        calls = 0
        _client = None

    expand = make_query_expander(NoClientClassifier(), lead_type="our_agency")
    assert expand("video editing") == []
    assert NoClientClassifier.calls == 0


def test_content_direction_gate_matches_store_rule():
    cf = ha_service._content_matches_requested_type
    # need_freelancer: genuine freelance ask kept.
    assert cf("we are looking for a freelance video editor for a project", "need_freelancer")
    # need_freelancer: employee job-ad without freelance wording dropped.
    assert not cf("we are hiring a full-time video editor, apply now, salary", "need_freelancer")
    # need_freelancer: agency-sourcing (freelancers for ITS clients) dropped.
    assert not cf("looking for freelancers to work with our agency on client projects", "need_freelancer")
    # our_agency: agency/outside-team sourcing kept.
    assert cf("our agency needs extra video editing help", "our_agency")
    # our_agency: pure individual freelance ask dropped.
    assert not cf("i need a freelance video editor for my channel", "our_agency")
    # Empty text is never cheap-dropped (classifier owns it).
    assert cf("", "need_freelancer")


# ---------------------------------------------------------------------------
# Freshness gate details (production cutoff semantics)
# ---------------------------------------------------------------------------

def test_engine_window_cutoff_is_exact():
    """The 7d cutoff is EXACTLY now-7d (strict freshness: a post older than
    7x24h can never ship, so no day rounding pulls the boundary older)."""
    now = datetime(2026, 9, 9, 14, 30, tzinfo=UTC)
    cutoff = TimeWindow.DAYS_7.cutoff(now)
    assert cutoff == datetime(2026, 9, 2, 14, 30, 0, tzinfo=UTC)
    assert now - cutoff == timedelta(days=7)


def test_engine_drops_post_at_window_boundary_minus_epsilon():
    """A post 7d+1s old is strictly outside the window and must never ship."""
    from db import MemoryStore

    now = datetime.now(UTC)
    just_over = now - timedelta(days=7, seconds=1)

    class BoundaryDiscovery(MockDiscoveryClient):
        def search_posts(self, queries, since, *, results_per_query=25):  # type: ignore[no-untyped-def]
            return SearchBatchResult(posts=[
                RawPost(
                    post_url="https://www.linkedin.com/posts/boundary-1",
                    text="We are looking for a video editor for our campaign, budget ready.",
                    author_name="B A", author_profile_url="https://www.linkedin.com/in/b",
                    posted_at=just_over,
                ),
            ], queries_used=list(queries))

    store = MemoryStore()
    sid = store.create_search(
        service="video editor", country="", lead_type="need_freelancer",
        time_window="7d", leads_needed=3,
    )["id"]
    summary = run_search(
        sid, store=store, discovery=BoundaryDiscovery(),
        classifier=MockClassifier(), settings=ha_service._ha_settings(),
    )
    assert summary.accepted == 0  # 7d+1s old -> NOT delivered
    assert store.list_leads(search_id=sid) == []


def _boundary_corpus(url: str):
    """A genuine need_freelancer FakePost so MockClassifier can classify it."""
    from models import IntentStrength
    from testing.mock_providers import FakePost

    return FakePost(
        url=url,
        text="We are looking for a video editor for our campaign, budget ready.",
        author="Boundary Author", author_url="https://www.linkedin.com/in/boundary",
        days_ago=1.0, lead_type=LeadType.NEED_FREELANCER,
        intent=IntentStrength.EXPLICIT, service_match=92.0, commercial=85.0,
        decision_maker=True, evidence="looking for a video editor", reason="boundary",
    )


def _run_single_post_search(posted_at, lead_type="need_freelancer"):
    """Run the engine against one synthetic post with the PRODUCTION settings;
    return (summary, leads). `posted_at` is the discovery-side datetime (or
    None for an undated post) — what the freshness gate sees."""
    from db import MemoryStore

    post = _boundary_corpus("https://www.linkedin.com/posts/matrix-1")

    class FixedDiscovery(MockDiscoveryClient):
        def search_posts(self, queries, since, *, results_per_query=25):  # type: ignore[no-untyped-def]
            return SearchBatchResult(posts=[
                RawPost(
                    post_url=post.url, text=post.text,
                    author_name=post.author, author_profile_url=post.author_url,
                    posted_at=posted_at,
                ),
            ], queries_used=list(queries))

    store = MemoryStore()
    sid = store.create_search(
        service="video editor", country="", lead_type=lead_type,
        time_window="7d", leads_needed=1,
    )["id"]
    summary = run_search(
        sid, store=store, discovery=FixedDiscovery(),
        classifier=MockClassifier(corpus=[post]), settings=ha_service._ha_settings(),
    )
    return summary, store.list_leads(search_id=sid)


def test_engine_accepts_post_just_inside_window():
    """A post 6d23h old is inside the window and is delivered."""
    summary, leads = _run_single_post_search(
        datetime.now(UTC) - timedelta(days=6, hours=23))
    assert summary.status == "completed"
    assert len(leads) == 1
    assert leads[0]["post_url"] == "https://www.linkedin.com/posts/matrix-1"


@pytest.mark.parametrize("case,expected", [
    ("undated", False),        # unverifiable -> never ships
    ("ancient", False),        # 30d old
    ("just_outside", False),   # 7d + 1s old
    ("just_inside", True),     # 6d23h old
    ("brand_new", True),       # 5 minutes old
])
def test_freshness_matrix(case, expected):
    """The full freshness decision table in one place. Timestamps are computed
    INSIDE the test (import-time dates would drift across the boundary while
    the suite runs)."""
    now = datetime.now(UTC)
    stamps = {
        "undated": None,
        "ancient": now - timedelta(days=30),
        "just_outside": now - timedelta(days=7, seconds=1),
        "just_inside": now - timedelta(days=6, hours=23),
        "brand_new": now - timedelta(minutes=5),
    }
    summary, leads = _run_single_post_search(stamps[case])
    assert bool(leads) is expected
    assert summary.accepted == (1 if expected else 0)
