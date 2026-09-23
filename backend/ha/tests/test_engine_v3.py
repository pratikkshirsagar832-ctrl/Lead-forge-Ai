"""Engine v3: parallel expansion, freshness ladder, URL post-time, prefetch
spend safety and snippet-first full-text enrichment (offline)."""
import threading
from datetime import UTC, datetime, timedelta

from db import MemoryStore
from discovery.base import RawPost, SearchBatchResult
from engine import parse_freshness_ladder, run_search
from models import LeadClassification, LeadType


def _settings(**overrides):
    from config import Settings

    return Settings(**overrides)


def _mk_search(store, *, needed=1, service="video editor", lead_type="need_freelancer"):
    return store.create_search(service=service, country="", lead_type=lead_type,
                               time_window="7d", leads_needed=needed)["id"]


def _verdict(**kw):
    base = dict(
        lead_type="need_freelancer", intent_strength="explicit", is_buying_sourcing=True,
        is_selling_offering=False, is_job_seek=False, service_match_score=92.0,
        commercial_intent_score=85.0, decision_maker_signal=True, evidence_strength=85.0,
        overall_quality_score=88.0, is_qualified=True, confidence=0.9,
        evidence="need a video editor", reason="buyer",
    )
    base.update(kw)
    return LeadClassification(**base)


_VAGUE = dict(intent_strength="recommendation", commercial_intent_score=40.0,
              evidence_strength=45.0, overall_quality_score=45.0, is_qualified=False,
              decision_maker_signal=False, needs_full_text=True)


class ListDiscovery:
    """Serves one fixed list of posts per call; records every `since`."""

    name = "list"

    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.calls = 0
        self.sinces: list[datetime] = []
        self.lock = threading.Lock()

    def search_posts(self, queries, since, **_kw):
        with self.lock:
            self.calls += 1
            self.sinces.append(since)
            posts = self.rounds.pop(0) if self.rounds else []
        return SearchBatchResult(posts=list(posts), queries_used=list(queries))


class TextClassifier:
    """Verdict chosen by a function of the post text."""

    def __init__(self, fn):
        self.fn = fn
        self.calls = 0
        self.seen_kwargs: list[dict] = []
        self.texts: list[str] = []

    def classify_batch(self, candidates, **kwargs):
        self.seen_kwargs.append(kwargs)
        out = []
        for c in candidates:
            self.calls += 1
            self.texts.append(c.text)
            out.append(self.fn(c))
        return out


def _post(i=0, *, text="Need a video editor - anyone know someone", hours_ago=2.0, url=None):
    return RawPost(
        post_url=url or f"https://www.linkedin.com/posts/owner-{i}_need-an-editor",
        text=text, author_name=f"Owner {i}",
        posted_at=datetime.now(UTC) - timedelta(hours=hours_ago),
    )


# ---------------------------------------------------------------- ladder

def test_parse_freshness_ladder():
    assert parse_freshness_ladder("1d,3d") == [timedelta(days=1), timedelta(days=3)]
    assert parse_freshness_ladder("12h, 2w") == [timedelta(hours=12), timedelta(weeks=2)]
    assert parse_freshness_ladder("") == []
    assert parse_freshness_ladder("bogus, 0d, 3d") == [timedelta(days=3)]


def test_ladder_searches_newest_first_and_never_widens_the_window():
    disc = ListDiscovery([[], [], [], []])
    store = MemoryStore()
    sid = _mk_search(store, needed=5)
    run_search(sid, store=store, discovery=disc, classifier=TextClassifier(lambda c: None),
               settings=_settings(freshness_ladder="1d,3d", engine_early_stop_empty_rounds=1,
                                  engine_prefetch=False, engine_max_iterations=4))
    now = datetime.now(UTC)
    ages = [now - s for s in disc.sinces]
    assert timedelta(hours=23) < ages[0] <= timedelta(days=1, minutes=1)   # round 0: last 24h
    assert timedelta(days=2, hours=23) < ages[1] <= timedelta(days=3, minutes=1)  # round 1: 3d
    assert ages[2] <= timedelta(days=7, minutes=1)                          # then full 7d window
    # Narrowed (newest-only) rounds never count toward the empty-round stop:
    # with a 1-round early stop, the engine still reached the full-window round.
    assert len(disc.sinces) == 3


def test_narrow_round_reruns_the_same_best_queries_over_the_full_window():
    """Google lags LinkedIn by 1-3 days: the newest-only round must NOT use up
    the strongest queries - they re-run over the full window next round."""

    class Rec(ListDiscovery):
        def __init__(self):
            super().__init__([[], [], []])
            self.q: list[list[str]] = []

        def search_posts(self, queries, since, **kw):
            self.q.append(list(queries))
            return super().search_posts(queries, since, **kw)

    disc = Rec()
    store = MemoryStore()
    sid = _mk_search(store, needed=5)
    run_search(sid, store=store, discovery=disc, classifier=TextClassifier(lambda c: None),
               settings=_settings(freshness_ladder="3d", engine_prefetch=False,
                                  engine_max_iterations=3, engine_early_stop_empty_rounds=10))
    assert disc.q[0] == disc.q[1]  # same best queries: last 3 days, then full week
    assert disc.q[2] != disc.q[1]  # then diversification continues
    now = datetime.now(UTC)
    assert now - disc.sinces[0] <= timedelta(days=3, minutes=1)
    assert now - disc.sinces[1] > timedelta(days=6)


def test_ladder_step_wider_than_window_is_clamped():
    disc = ListDiscovery([[]])
    store = MemoryStore()
    sid = _mk_search(store)
    run_search(sid, store=store, discovery=disc, classifier=TextClassifier(lambda c: None),
               settings=_settings(freshness_ladder="30d", engine_max_iterations=1,
                                  engine_prefetch=False))
    assert datetime.now(UTC) - disc.sinces[0] <= timedelta(days=7, minutes=1)


# ------------------------------------------------------------ URL post time

def test_undated_post_is_recovered_from_its_activity_id():
    # Activity id minted ~3h ago (id = ms << 22).
    ms = int((datetime.now(UTC) - timedelta(hours=3)).timestamp() * 1000)
    url = f"https://www.linkedin.com/posts/jane_need-an-editor-activity-{ms << 22}-AbCd"
    undated = RawPost(post_url=url, text="Need a video editor for our launch, paid", posted_at=None)
    store = MemoryStore()
    sid = _mk_search(store)
    summary = run_search(sid, store=store, discovery=ListDiscovery([[undated]]),
                         classifier=TextClassifier(lambda c: _verdict()),
                         settings=_settings(freshness_ladder="", engine_prefetch=False))
    assert summary.accepted == 1
    lead = store.list_leads(search_id=sid)[0]
    assert lead["post_url"] == url
    assert lead["post_date"] == (datetime.now(UTC) - timedelta(hours=3)).date()


# ------------------------------------------------------------- enrichment

def test_cut_off_snippet_is_enriched_and_reclassified_on_full_text():
    snippet = _post(1, text="Founder here - we're finally ready to bring in someone to help with our")
    full = ("Founder here - we're finally ready to bring in someone to help with our YouTube "
            "channel: need a freelance video editor for 8 videos a month, paid per video, "
            "starting this week.")

    def verdicts(c):
        return _verdict() if "freelance video editor" in c.text else _verdict(**_VAGUE)

    fetched: list[str] = []
    store = MemoryStore()
    sid = _mk_search(store)
    clf = TextClassifier(verdicts)
    summary = run_search(
        sid, store=store, discovery=ListDiscovery([[snippet]]), classifier=clf,
        settings=_settings(freshness_ladder="", engine_prefetch=False),
        full_text_fetcher=lambda url: fetched.append(url) or full,
    )
    assert fetched == [snippet.post_url]
    assert summary.accepted == 1
    assert clf.calls == 2  # snippet verdict + one full-text re-check
    lead = store.list_leads(search_id=sid)[0]
    assert lead["post_text"] == full  # the saved lead shows the whole post


def test_enrichment_skips_sellers_and_respects_budget():
    seller = _post(1, text="We help brands with video editing - DM us")
    vague = [_post(i, text=f"Looking for a video editor, anyone {i}") for i in range(2, 6)]
    fetched: list[str] = []

    def verdicts(c):
        if "DM us" in c.text:
            return _verdict(lead_type="irrelevant", is_buying_sourcing=False,
                            is_selling_offering=True, is_qualified=False)
        return _verdict(**_VAGUE)

    store = MemoryStore()
    sid = _mk_search(store, needed=3)
    run_search(sid, store=store, discovery=ListDiscovery([[seller, *vague]]),
               classifier=TextClassifier(verdicts),
               settings=_settings(freshness_ladder="", engine_prefetch=False,
                                  max_enrich_per_search=2, engine_max_iterations=1),
               full_text_fetcher=lambda url: fetched.append(url) or None)
    assert seller.post_url not in fetched  # direction already clear: no fetch
    assert len(fetched) == 2  # per-search enrichment budget


def test_full_text_that_fails_the_direction_gate_is_rejected():
    snippet = _post(1, text="Need a video editor for our")
    full = "Need a video editor for our team - full-time, join our team, salary + benefits."

    store = MemoryStore()
    sid = _mk_search(store)
    summary = run_search(
        sid, store=store, discovery=ListDiscovery([[snippet]]),
        classifier=TextClassifier(lambda c: _verdict(**_VAGUE)),
        settings=_settings(freshness_ladder="", engine_prefetch=False, engine_max_iterations=1),
        content_filter=lambda text: "full-time" not in text,
        full_text_fetcher=lambda url: full,
    )
    assert summary.accepted == 0


def test_fetcher_crash_keeps_snippet_verdict():
    store = MemoryStore()
    sid = _mk_search(store)

    def boom(url):
        raise RuntimeError("blocked")

    summary = run_search(
        sid, store=store, discovery=ListDiscovery([[_post(1)]]),
        classifier=TextClassifier(lambda c: _verdict()),
        settings=_settings(freshness_ladder="", engine_prefetch=False),
        full_text_fetcher=boom,
    )
    assert summary.status == "completed" and summary.accepted == 1


# --------------------------------------------------------------- prefetch

def test_prefetch_overlaps_rounds_and_respects_serper_ceiling():
    rounds = [[_post(i, text=f"need a video editor {i}")] for i in range(20)]
    disc = ListDiscovery(rounds)
    store = MemoryStore()
    sid = _mk_search(store, needed=50)
    run_search(sid, store=store, discovery=disc,
               classifier=TextClassifier(lambda c: _verdict(**_VAGUE)),
               settings=_settings(freshness_ladder="", engine_prefetch=True,
                                  max_serper_requests_per_search=3,
                                  engine_early_stop_empty_rounds=50))
    # The ceiling check covers prefetched rounds too: never more than cap + 0.
    assert disc.calls <= 3


def test_prefetch_skipped_once_target_is_reachable():
    posts = [_post(i, text=f"need a video editor {i}") for i in range(10)]
    disc = ListDiscovery([posts, [], []])
    store = MemoryStore()
    sid = _mk_search(store, needed=1)
    summary = run_search(sid, store=store, discovery=disc,
                         classifier=TextClassifier(lambda c: _verdict()),
                         settings=_settings(freshness_ladder="", engine_prefetch=True))
    assert summary.accepted == 1
    # est. yield (15%) x 10 candidates >= 1 needed -> no speculative round.
    assert disc.calls == 1


# ------------------------------------------------------ expansion wiring

def test_expansion_vocabulary_reaches_the_classifier():
    from llm_queries import Expansion

    def expander(service):
        return Expansion(["need a reels editor"], role_nouns=["reels editor"],
                         synonyms=["short-form editing"], not_this_service=["videographer"])

    disc = ListDiscovery([[], [_post(1)]])
    clf = TextClassifier(lambda c: _verdict())
    store = MemoryStore()
    sid = _mk_search(store)
    run_search(sid, store=store, discovery=disc, classifier=clf, query_expander=expander,
               settings=_settings(freshness_ladder="", engine_prefetch=False))
    ctx = clf.seen_kwargs[-1]["service_context"]
    assert ctx == {"role_nouns": ["reels editor"], "synonyms": ["short-form editing"],
                   "not_this_service": ["videographer"]}


def test_classifier_prompt_is_mode_specific():
    from classifier import _user_prompt, system_prompt_for

    free, agency = system_prompt_for("need_freelancer"), system_prompt_for("need_agency")
    assert "FREELANCER QUALITY BAR" in free and "AGENCY QUALITY BAR" not in free
    assert "AGENCY QUALITY BAR" in agency and "FREELANCER QUALITY BAR" not in agency
    for p in (free, agency):
        assert "SNIPPET AWARENESS" in p and '"needs_full_text": false' in p
        assert "<<MODE_BLOCK>>" not in p
    up = _user_prompt({"text": "x"}, "video editing", "", "need_freelancer",
                      service_context={"role_nouns": ["video editor"], "synonyms": [],
                                       "not_this_service": ["videographer"]})
    assert "Counts as this service: video editor." in up
    assert "NOT this service (service_match_score <= 50): videographer." in up


def test_needs_full_text_is_optional_in_model_output():
    v = _verdict()
    assert v.needs_full_text is False
    assert LeadType.NEED_AGENCY.value == "need_agency"


# --------------------------------------------------------------- liveness

def test_deleted_post_is_replaced_and_never_delivered():
    """Google still indexes deleted posts: a dead accepted post must be
    swapped for the next live one, keeping exactly N."""
    from liveness import PostCheck

    posts = [_post(i, text=f"need a video editor {i}", hours_ago=i + 1) for i in range(4)]
    dead_url = posts[0].post_url  # the NEWEST one is deleted
    checked: list[str] = []

    def checker(url):
        checked.append(url)
        return PostCheck("dead") if url == dead_url else PostCheck("alive")

    store = MemoryStore()
    sid = _mk_search(store, needed=3)
    summary = run_search(sid, store=store, discovery=ListDiscovery([posts]),
                         classifier=TextClassifier(lambda c: _verdict()),
                         settings=_settings(freshness_ladder="", engine_prefetch=False),
                         post_checker=checker)
    urls = [l["post_url"] for l in store.list_leads(search_id=sid)]
    assert summary.accepted == 3 and len(urls) == 3
    assert dead_url not in urls
    assert set(checked) == {p.post_url for p in posts}  # only accepted posts are checked


def test_filled_post_is_dropped_and_live_full_text_is_saved():
    from liveness import PostCheck

    a = _post(1, text="Looking for a web designer for our site")
    b = _post(2, text="Need a video editor for reels")
    full_b = "Need a video editor for reels - 10 reels a month, paid per reel, starting this week."

    def checker(url):
        if url == a.post_url:
            return PostCheck("alive", "UPDATE: CONTRACT NOW AWARDED. Looking for a web designer for our site")
        return PostCheck("alive", full_b)

    store = MemoryStore()
    sid = _mk_search(store, needed=2)
    summary = run_search(sid, store=store, discovery=ListDiscovery([[a, b]]),
                         classifier=TextClassifier(lambda c: _verdict()),
                         settings=_settings(freshness_ladder="", engine_prefetch=False, engine_max_iterations=1),
                         post_checker=checker)
    leads = store.list_leads(search_id=sid)
    assert summary.accepted == 1
    assert [l["post_url"] for l in leads] == [b.post_url]
    assert leads[0]["post_text"] == full_b


def test_unknown_liveness_keeps_the_lead():
    from liveness import PostCheck

    store = MemoryStore()
    sid = _mk_search(store, needed=1)
    summary = run_search(sid, store=store, discovery=ListDiscovery([[_post(1)]]),
                         classifier=TextClassifier(lambda c: _verdict()),
                         settings=_settings(freshness_ladder="", engine_prefetch=False),
                         post_checker=lambda url: PostCheck("unknown"))
    assert summary.accepted == 1


def test_crashing_checker_keeps_the_lead():
    def boom(url):
        raise RuntimeError("linkedin down")

    store = MemoryStore()
    sid = _mk_search(store, needed=1)
    summary = run_search(sid, store=store, discovery=ListDiscovery([[_post(1)]]),
                         classifier=TextClassifier(lambda c: _verdict()),
                         settings=_settings(freshness_ladder="", engine_prefetch=False),
                         post_checker=boom)
    assert summary.accepted == 1
