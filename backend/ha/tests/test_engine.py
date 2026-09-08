"""End-to-end engine tests against the offline corpus (no external keys)."""
from datetime import UTC, datetime, timedelta

import pytest

from db import MemoryStore
from discovery.base import DiscoveryConfigError, DiscoveryError, RawPost, SearchBatchResult
from engine import run_search
from models import LeadType, TimeWindow
from testing.mock_providers import CORPUS, MockClassifier, MockDiscoveryClient


def _mk_search(store, *, service="video editor", lead_type=LeadType.NEED_FREELANCER,
               window="7d", needed=10, country=""):
    return store.create_search(
        service=service, country=country, lead_type=lead_type.value,
        time_window=window, leads_needed=needed,
    )["id"]


def _settings():
    from config import Settings

    return Settings()


def _qualified_within_corpus(window: str, requested: LeadType = LeadType.NEED_FREELANCER) -> int:
    """Corpus posts of the REQUESTED lead type only (strict-type gate), inside
    the window, whose text matches the service words the engine queries carry."""
    from testing.mock_providers import _now, _service_words

    service_words = _service_words("video editor")
    cutoff = TimeWindow(window).cutoff(datetime.now(UTC))
    count = 0
    for p in CORPUS:
        if p.lead_type == requested:
            if _now(p.days_ago) >= cutoff and any(w in p.text.lower() for w in service_words):
                count += 1
    return count


def test_engine_delivers_exactly_n_when_enough_exist():
    store = MemoryStore()
    expected = _qualified_within_corpus("7d")  # need_freelancer posts in window
    assert expected > 0
    sid = _mk_search(store, needed=expected, window="7d")
    summary = run_search(
        sid, store=store, discovery=MockDiscoveryClient(),
        classifier=MockClassifier(), settings=_settings(),
    )
    assert summary.status == "completed"
    assert summary.accepted == expected  # exactly N — never more
    assert summary.scanned >= expected
    leads = store.list_leads(search_id=sid)
    assert len(leads) == expected
    row = store.get_search(sid)
    assert row["status"] == "completed"
    assert row["accepted_count"] == expected
    # Every persisted lead is of the REQUESTED type and inside the window.
    cutoff = TimeWindow.DAYS_7.cutoff()
    for lead in leads:
        assert lead["post_date"] >= cutoff.date()
        assert lead["status"] == "new"
        assert lead["lead_type"] == LeadType.NEED_FREELANCER.value  # strict type


def test_engine_never_overdelivers_on_small_request():
    store = MemoryStore()
    sid = _mk_search(store, needed=4)
    summary = run_search(sid, store=store, discovery=MockDiscoveryClient(),
                         classifier=MockClassifier(), settings=_settings())
    assert summary.status == "completed"
    assert summary.accepted == 4
    leads = store.list_leads(search_id=sid)
    assert len(leads) == 4
    assert all(l["lead_type"] == LeadType.NEED_FREELANCER.value for l in leads)


def test_engine_stops_short_without_padding():
    store = MemoryStore()
    expected = _qualified_within_corpus("7d")
    sid = _mk_search(store, needed=100)
    summary = run_search(sid, store=store, discovery=MockDiscoveryClient(),
                         classifier=MockClassifier(), settings=_settings())
    assert summary.status == "completed"
    # Exactly as many of the REQUESTED type as were genuinely qualified.
    assert summary.accepted == expected
    assert len(store.list_leads(search_id=sid)) == expected
    row = store.get_search(sid)
    assert row["accepted_count"] == expected
    assert row["accepted_count"] < 100


def test_engine_window_filters_older_posts():
    store = MemoryStore()
    # A 24h window sees far fewer corpus posts than 7d.
    sid = _mk_search(store, needed=100, window="24h")
    summary = run_search(sid, store=store, discovery=MockDiscoveryClient(),
                         classifier=MockClassifier(), settings=_settings())
    assert summary.status == "completed"
    assert summary.accepted == _qualified_within_corpus("24h")
    for lead in store.list_leads(search_id=sid):
        assert lead["post_date"] >= TimeWindow.HOURS_24.cutoff().date()


def test_strict_lead_type_only_requested_type_is_accepted():
    """Asking for our_agency must return ONLY our_agency leads — genuine
    need_freelancer posts matched by the same queries are excluded."""
    expected = _qualified_within_corpus("7d", LeadType.OUR_AGENCY)
    assert expected > 0
    store = MemoryStore()
    sid = _mk_search(store, lead_type=LeadType.OUR_AGENCY, needed=100)
    summary = run_search(sid, store=store, discovery=MockDiscoveryClient(),
                         classifier=MockClassifier(), settings=_settings())
    assert summary.status == "completed"
    assert summary.accepted == expected
    leads = store.list_leads(search_id=sid)
    assert len(leads) == expected
    assert all(l["lead_type"] == LeadType.OUR_AGENCY.value for l in leads)
    # The engine explicitly reported other genuine buyer types were excluded.
    assert "DIFFERENT lead type" in summary.detail



def test_provider_error_marks_search_failed_loudly():
    class BrokenProvider(MockDiscoveryClient):
        def search_posts(self, queries, since, *, results_per_query=25):  # type: ignore[no-untyped-def]
            raise DiscoveryError("Serper request failed (HTTP 500): upstream exploded")

    store = MemoryStore()
    sid = _mk_search(store, needed=10)
    summary = run_search(sid, store=store, discovery=BrokenProvider(),
                         classifier=MockClassifier(), settings=_settings())
    assert summary.status == "failed"  # real provider errors are loud
    row = store.get_search(sid)
    assert row["status"] == "failed"
    assert "HTTP 500" in (row["error"] or "")
    assert store.list_leads(search_id=sid) == []


def test_quiet_zero_serp_hits_complete_with_shortage_note():
    # §0: with Google-SERP discovery, an empty result set is EXPECTED provider
    # behavior (partial crawl + lag), never a fake failure.
    class QuietEmptyDiscovery(MockDiscoveryClient):
        def search_posts(self, queries, since, *, results_per_query=25):  # type: ignore[no-untyped-def]
            return SearchBatchResult(posts=[], queries_used=list(queries))

    store = MemoryStore()
    sid = _mk_search(store, needed=10)
    summary = run_search(sid, store=store, discovery=QuietEmptyDiscovery(),
                         classifier=MockClassifier(), settings=_settings())
    assert summary.status == "completed"
    assert summary.accepted == 0
    assert "lag" in summary.detail or "partial" in summary.detail or "crawl" in summary.detail.lower()
    assert store.get_search(sid)["status"] == "completed"


def test_config_error_marks_failed():
    class BrokenDiscovery(MockDiscoveryClient):
        def search_posts(self, queries, since, *, results_per_query=25):  # type: ignore[no-untyped-def]
            raise DiscoveryConfigError("SERPER_API_KEY is not set")

    store = MemoryStore()
    sid = _mk_search(store, needed=10)
    summary = run_search(sid, store=store, discovery=BrokenDiscovery(),
                         classifier=MockClassifier(), settings=_settings())
    assert summary.status == "failed"
    assert (store.get_search(sid)["error"] or "").startswith("SERPER_API_KEY")


def test_fail_closed_when_classifier_drops_candidates():
    # Mock classifier returns None (unclassifiable) for posts it does not know.
    class PickyClassifier(MockClassifier):
        def classify_batch(self, candidates, *, service, lead_type, country="", max_concurrency=8,
                           accepted_types=None):  # type: ignore[no-untyped-def]
            return [None for _ in candidates]

    store = MemoryStore()
    sid = _mk_search(store, needed=10)
    summary = run_search(sid, store=store, discovery=MockDiscoveryClient(),
                         classifier=PickyClassifier(), settings=_settings())
    assert summary.status == "completed"
    assert summary.accepted == 0  # nothing guessed into qualified
    assert store.list_leads(search_id=sid) == []


def test_dedupe_by_canonical_url():
    class DupDiscovery(MockDiscoveryClient):
        def search_posts(self, queries, since, *, results_per_query=25):  # type: ignore[no-untyped-def]
            batch = super().search_posts(queries, since, results_per_query=results_per_query)
            # duplicate every post with a tracking-query variant of its URL
            doubled = []
            for p in batch.posts:
                doubled.append(p)
                doubled.append(RawPost(
                    post_url=p.post_url + "?trackingId=abc123", text=p.text,
                    author_name=p.author_name, author_profile_url=p.author_profile_url,
                    posted_at=p.posted_at, query_used=p.query_used, provider=p.provider,
                ))
            return SearchBatchResult(posts=doubled, queries_used=batch.queries_used)
    store = MemoryStore()
    sid = _mk_search(store, needed=25)
    summary = run_search(sid, store=store, discovery=DupDiscovery(),
                         classifier=MockClassifier(), settings=_settings())
    urls = [l["post_url"] for l in store.list_leads(search_id=sid)]
    assert len(urls) == len(set(urls))
    assert all("trackingId" not in u for u in urls)


def test_progress_callback_fires():
    store = MemoryStore()
    sid = _mk_search(store, needed=10)
    seen = []
    run_search(sid, store=store, discovery=MockDiscoveryClient(),
               classifier=MockClassifier(), settings=_settings(),
               progress=lambda stage, f, a, s, m: seen.append(stage))
    assert "running" in seen
    assert seen[-1] == "completed"


def test_cooperative_cancel_stops_spend():
    """A cancel requested mid-run (should_stop) must stop provider spend and
    mark the search cancelled instead of running to completion."""
    store = MemoryStore()
    sid = _mk_search(store, needed=100)  # would need many rounds
    cancelled = {"flag": False}

    class CancelDiscovery(MockDiscoveryClient):
        def search_posts(self, queries, since, *, results_per_query=25):  # type: ignore[no-untyped-def]
            if cancelled["flag"]:
                raise AssertionError("provider called after cancel")
            return super().search_posts(queries, since, results_per_query=results_per_query)

    def should_stop():
        cancelled["flag"] = True  # cancel on the first iteration boundary
        return True

    summary = run_search(sid, store=store, discovery=CancelDiscovery(),
                         classifier=MockClassifier(), settings=_settings(),
                         should_stop=should_stop)
    assert summary.status == "cancelled"
    row = store.get_search(sid)
    assert row["status"] == "cancelled"
    assert row["finished_at"] is not None


def test_engine_keeps_looping_until_exactly_n_is_reached():
    """The exact-count loop must keep iterating past the old 6-round cap until
    it collects exactly N qualified leads (discovery here drips out new posts
    a couple at a time, so many rounds are required)."""
    from models import IntentStrength
    from testing.mock_providers import FakePost

    n_posts = 40
    drip: list[FakePost] = [
        FakePost(
            url=f"https://www.linkedin.com/posts/drip-{i:03d}",
            text=f"We are looking for a plumber for project #{i}. Budget is ready, DM if you know someone.",
            author=f"Drip Author {i}",
            author_url=f"https://www.linkedin.com/in/drip-{i}",
            days_ago=0.2 + i * 0.05,
            lead_type=LeadType.NEED_FREELANCER,
            intent=IntentStrength.EXPLICIT,
            service_match=92.0,
            commercial=85.0,
            decision_maker=True,
            evidence=f"project #{i}",
            reason=f"drip corpus {i}",
        )
        for i in range(n_posts)
    ]

    class DripDiscovery(MockDiscoveryClient):
        def __init__(self):
            self._pos = 0

        def search_posts(self, queries, since, *, results_per_query=25):  # type: ignore[no-untyped-def]
            chunk = drip[self._pos : self._pos + 2]  # two new posts per round
            self._pos += 2
            posts = [
                RawPost(post_url=p.url, text=p.text, author_name=p.author,
                        author_profile_url=p.author_url, posted_at=None)
                for p in chunk
            ]
            return SearchBatchResult(posts=posts, queries_used=list(queries))

    store = MemoryStore()
    sid = _mk_search(store, needed=18)  # needs ~9 rounds: > the old cap of 6
    summary = run_search(sid, store=store, discovery=DripDiscovery(),
                         classifier=MockClassifier(corpus=drip), settings=_settings())
    assert summary.status == "completed"
    assert summary.iterations >= 7  # proved it looped well past a 6-round cap
    assert summary.accepted == 18   # exactly N — neither fewer nor more
    leads = store.list_leads(search_id=sid)
    assert len(leads) == 18
    assert len({l["post_url"] for l in leads}) == 18  # no dupes across rounds


def test_exact_count_skips_already_owned_posts_and_keeps_scanning():
    """Leads already saved globally (post_url unique) must NOT count toward N:
    the engine skips them and keeps looping until N NEW leads are delivered."""
    from models import IntentStrength
    from testing.mock_providers import FakePost

    n_posts = 40
    drip: list[FakePost] = [
        FakePost(
            url=f"https://www.linkedin.com/posts/owned-{i:03d}",
            text=f"We are looking for a plumber for job #{i}. Paid, DM if you know someone.",
            author=f"Owner {i}", author_url=f"https://www.linkedin.com/in/owner-{i}",
            days_ago=0.3 + i * 0.05,
            lead_type=LeadType.NEED_FREELANCER, intent=IntentStrength.EXPLICIT,
            service_match=90.0, commercial=85.0, decision_maker=True,
            evidence=f"job #{i}", reason=f"owned corpus {i}",
        )
        for i in range(n_posts)
    ]

    class OwnedDripDiscovery(MockDiscoveryClient):
        def __init__(self):
            self._pos = 0

        def search_posts(self, queries, since, *, results_per_query=25):  # type: ignore[no-untyped-def]
            chunk = drip[self._pos : self._pos + 2]
            self._pos += 2
            posts = [RawPost(post_url=p.url, text=p.text, author_name=p.author,
                             author_profile_url=p.author_url, posted_at=None) for p in chunk]
            return SearchBatchResult(posts=posts, queries_used=list(queries))

    store = MemoryStore()
    # Simulate one of those posts ALREADY being owned from an earlier search.
    store.insert_leads_many([{
        "lead_type": "need_freelancer", "post_url": drip[0].url,
        "author_name": drip[0].author, "post_date": None,
    }])
    sid = _mk_search(store, needed=18)
    summary = run_search(sid, store=store, discovery=OwnedDripDiscovery(),
                         classifier=MockClassifier(corpus=drip), settings=_settings())
    assert summary.status == "completed"
    assert summary.accepted == 18          # exactly N NEW leads delivered
    assert "already-owned" in summary.detail or "skipped" in summary.detail
    leads = store.list_leads(search_id=sid)
    assert len(leads) == 18
    assert drip[0].url not in {l["post_url"] for l in leads}  # owned post not re-delivered


def test_engine_independent_spend_ceiling_stops_honestly():
    """Tier 1.2: a hard Serper ceiling must stop the search (stop_reason
    ceiling_hit) even when the niche would otherwise keep looping."""
    import dataclasses
    from config import Settings

    settings = dataclasses.replace(
        _settings(),
        max_serper_requests_per_search=1,   # one request is the budget
        engine_early_stop_empty_rounds=99,  # never stop on empty rounds
        engine_max_iterations=10,
    )
    store = MemoryStore()
    sid = _mk_search(store, needed=100)  # far more than the corpus holds
    summary = run_search(sid, store=store, discovery=MockDiscoveryClient(),
                         classifier=MockClassifier(), settings=settings)
    assert summary.status == "completed"
    assert "ceiling" in summary.detail
    row = store.get_search(sid)
    assert row["stop_reason"] == "ceiling_hit"
    assert row["serper_requests_used"] == 1
    assert row["deepseek_calls_used"] <= settings.max_deepseek_calls_per_search


def test_engine_records_rejections_for_observability():
    """Tier 0.1: candidates that reach the classifier and are rejected are
    recorded (search_id, url, verdict) instead of only being counted."""
    store = MemoryStore()
    sid = _mk_search(store, needed=100)
    run_search(sid, store=store, discovery=MockDiscoveryClient(),
               classifier=MockClassifier(), settings=_settings())
    rej = getattr(store, "_rejections", [])
    assert len(rej) > 0  # corpus contains sellers/job-seekers -> rejections
    assert all(r.get("search_id") == sid for r in rej)
    assert all(r.get("post_url") for r in rej)
    assert all(r.get("accepted") is False for r in rej)


def test_content_filter_drops_wrong_direction_before_llm_and_keeps_count_honest():
    """A cheap pre-LLM content-direction gate must (a) never reach the
    classifier with a post whose text it would reject, and (b) keep the
    engine's accepted count exactly equal to what is actually saved (accepted
    == saved), so an N-lead search really stores N leads."""
    from testing.mock_providers import _now, _service_words

    def _gated_qualified(window: str, gate) -> int:
        service_words = _service_words("video editor")
        cutoff = TimeWindow(window).cutoff(datetime.now(UTC))
        n = 0
        for p in CORPUS:
            if p.lead_type == LeadType.NEED_FREELANCER:
                if (_now(p.days_ago) >= cutoff and any(w in p.text.lower() for w in service_words)
                        and gate(p.text)):
                    n += 1
        return n

    # Direction gate: a freelancer-direction search should not even consider
    # posts that talk about an agency as the counterparty (mirrors the store's
    # save-time rule — e.g. "Our company needs a video editing AGENCY ...").
    def gate(text: str) -> bool:
        return "agency" not in (text or "").lower()

    class RecordingClassifier(MockClassifier):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.seen_texts: list[str] = []

        def classify_batch(self, candidates, **kwargs):  # type: ignore[no-untyped-def]
            self.seen_texts.extend((c.text or "").lower() for c in candidates)
            return super().classify_batch(candidates, **kwargs)

    expected = _gated_qualified("7d", gate)
    assert expected > 0

    store = MemoryStore()
    clf = RecordingClassifier()
    sid = _mk_search(store, needed=100, window="7d")
    summary = run_search(
        sid, store=store, discovery=MockDiscoveryClient(),
        classifier=clf, settings=_settings(),
        content_filter=gate,
    )
    assert summary.status == "completed"
    assert summary.accepted == expected          # only gate-passing posts counted
    assert summary.accepted == len(store.list_leads(search_id=sid))  # accepted == saved
    leads = store.list_leads(search_id=sid)
    assert all(gate(l.get("post_text") or "") for l in leads)
    # The classifier never saw a text the gate rejects (zero LLM spend on them).
    assert all(gate(t) or not t for t in clf.seen_texts)


def test_content_filter_rejecting_everything_yields_zero_and_no_llm_calls():
    """If the gate rejects every candidate, the engine must stop with a clean
    zero-lead shortage and must not have spent a single classifier call."""
    class NoopClassifier(MockClassifier):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.calls = 0

        def classify_batch(self, candidates, **kwargs):  # type: ignore[no-untyped-def]
            self.calls += 1
            return super().classify_batch(candidates, **kwargs)

    store = MemoryStore()
    clf = NoopClassifier()
    sid = _mk_search(store, needed=5)
    summary = run_search(
        sid, store=store, discovery=MockDiscoveryClient(),
        classifier=clf, settings=_settings(),
        content_filter=lambda text: False,
    )
    assert summary.status == "completed"
    assert summary.accepted == 0
    assert len(store.list_leads(search_id=sid)) == 0
    assert clf.calls == 0  # zero DeepSeek spend on a direction-mismatched pool
