"""Serper/Google-SERP discovery client tests — HTTP fully mocked, no network."""
from datetime import UTC, datetime

import pytest

import discovery.serp_client as serp_mod
from discovery.base import DiscoveryConfigError
from discovery.serp_client import SerperDiscoveryClient


class FakeResp:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or ""

    def json(self):
        return self._payload


def _client(**kw):
    return SerperDiscoveryClient("test-serper-key", results_per_query=5, **kw)


def test_requires_api_key():
    with pytest.raises(DiscoveryConfigError):
        SerperDiscoveryClient("")
    assert _client().config_errors == []


def test_full_query_appends_site_and_no_after_in_tbs_mode():
    client = _client()
    since = datetime(2025, 6, 10, 12, 0, 0, tzinfo=UTC)
    q = client._full_query('looking for a plumber -"we offer"', since)
    assert q.startswith('looking for a plumber -"we offer"')
    assert "site:linkedin.com/posts" in q
    assert "after:" not in q  # date rides in the `tbs` param instead


def test_legacy_after_mode_keeps_in_query_date():
    client = _client(date_mode="after")
    since = datetime(2025, 6, 10, 12, 0, 0, tzinfo=UTC)
    assert "after:2025-06-10" in client._full_query("looking for a plumber", since)


@pytest.mark.parametrize("hours,expected", [
    (1, "qdr:d"), (24, "qdr:d"), (30, "qdr:d2"), (72, "qdr:d3"),
    (6 * 24, "qdr:d6"), (7 * 24, "qdr:w"), (14 * 24, "qdr:m"),
])
def test_tbs_rounds_up_to_cover_window(hours, expected):
    from datetime import timedelta
    now = datetime(2026, 9, 23, 12, tzinfo=UTC)
    assert SerperDiscoveryClient.tbs_for(now - timedelta(hours=hours), now=now) == expected


def test_url_activity_id_beats_google_date(monkeypatch):
    from discovery.base import posted_at_from_url
    link = "https://www.linkedin.com/posts/jane-doe_need-an-editor-activity-7372000000000000000-AbCd"
    exact = posted_at_from_url(link)
    assert exact is not None

    def fake_post(url, headers, json, timeout):
        return FakeResp(payload={"organic": [
            {"link": link, "title": "Need an editor", "snippet": "Need a video editor this week.",
             "date": "Jan 1, 2020"},
            {"link": "https://www.linkedin.com/posts/nodate-activity-7372000000000000000-xy",
             "title": "Need a plumber", "snippet": "Need a plumber asap."},
        ]})

    monkeypatch.setattr(serp_mod.httpx, "post", fake_post)
    batch = _client().search_posts(["need an editor"], datetime(2025, 6, 1, tzinfo=UTC))
    by_url = {p.post_url: p for p in batch.posts}
    assert by_url[link].posted_at == exact  # URL time wins over Google's date
    # An undated SERP row is recovered from its activity id (no longer dropped).
    assert all(p.posted_at is not None for p in batch.posts)


def test_maps_organic_results_and_parses_author(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["payload"] = json
        captured["url"] = url
        return FakeResp(payload={
            "organic": [
                {
                    "link": "https://www.linkedin.com/posts/jane-123-abc",
                    "title": "Jane Smith on LinkedIn: We are looking for a video editor for our launch",
                    "snippet": "We are looking for a video editor for our product launch. Budget is ready.",
                    "date": "Aug 24, 2026",
                },
                {
                    "link": "https://www.linkedin.com/posts/john-456-def",
                    "title": "Anyone know a good plumber in Nairobi?",
                    "snippet": "Anyone know a good plumber in Nairobi? Need one this week.",
                    # no date -> kept, engine/UI tolerate missing post dates
                },
            ]
        })

    monkeypatch.setattr(serp_mod.httpx, "post", fake_post)
    client = _client()
    since = datetime(2025, 6, 1, tzinfo=UTC)
    batch = client.search_posts(['looking for a video editor', 'need a plumber'], since)
    assert captured["payload"]["num"] == 5
    assert "site:linkedin.com/posts" in captured["payload"]["q"]
    assert "after:" not in captured["payload"]["q"]
    assert captured["payload"]["tbs"] == "qdr:y"  # window > 1 month -> widest bucket
    assert captured["url"] == "https://google.serper.dev/search"

    posts = {p.post_url: p for p in batch.posts}
    assert len(posts) == 2
    jane = posts["https://www.linkedin.com/posts/jane-123-abc"]
    assert jane.author_name == "Jane Smith"
    assert jane.posted_at is not None and jane.posted_at.year == 2026 and jane.posted_at.month == 8
    assert "video editor" in jane.text
    john = posts["https://www.linkedin.com/posts/john-456-def"]
    assert john.posted_at is None  # undated results are kept, not silently dropped
    assert batch.provider_errors == []


def test_dedupes_and_filters_non_post_results(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResp(payload={"organic": [
            {"link": "https://www.linkedin.com/posts/same-post", "title": "t", "snippet": "a"},
            {"link": "https://www.linkedin.com/posts/same-post?trk=abc", "title": "t2", "snippet": "a2"},
            {"link": "https://example.com/blog/video-editors", "title": "not a post", "snippet": "x"},
        ]})

    monkeypatch.setattr(serp_mod.httpx, "post", fake_post)
    batch = _client().search_posts(["q1", "q2"], datetime(2025, 1, 1, tzinfo=UTC))
    assert len(batch.posts) == 1
    assert batch.posts[0].post_url == "https://www.linkedin.com/posts/same-post"


def test_zero_results_is_quiet_normal_behavior(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResp(payload={"organic": []})

    monkeypatch.setattr(serp_mod.httpx, "post", fake_post)
    batch = _client().search_posts(["tight phrase query"], datetime(2025, 1, 1, tzinfo=UTC))
    assert batch.posts == []           # expected SERP behavior, not an error
    assert batch.provider_errors == []
    assert batch.queries_used == ["tight phrase query"]


def test_provider_errors_are_loud_and_isolated(monkeypatch):
    """Failed queries are isolated (batch survives). Queries run in parallel,
    so assertions are order-agnostic."""
    calls = {"n": 0}

    def fake_post(url, headers, json, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResp(status_code=401, payload={}, text="unauthorized")
        if calls["n"] == 2:
            return FakeResp(payload={"error": "Rate limit exceeded"})
        return FakeResp(payload={"organic": []})

    monkeypatch.setattr(serp_mod.httpx, "post", fake_post)
    since = datetime(2025, 1, 1, tzinfo=UTC)
    batch = _client().search_posts(["q1", "q2", "q3"], since)
    assert len(batch.provider_errors) == 2  # failed queries isolated, batch survives
    assert any("401" in e for e in batch.provider_errors)
    assert any("Rate limit" in e for e in batch.provider_errors)
    assert batch.posts == []


def test_every_request_failing_is_a_loud_provider_error(monkeypatch):
    """All requests failing is an outage, never a silent 'no posts' result."""
    from discovery.base import DiscoveryError

    def boom(url, headers, json, timeout):
        raise serp_mod.httpx.HTTPError("connection reset")

    monkeypatch.setattr(serp_mod.httpx, "post", boom)
    with pytest.raises(DiscoveryError, match="connection reset"):
        _client().search_posts(["q1", "q2"], datetime(2025, 1, 1, tzinfo=UTC))


def test_out_of_credits_is_reported_clearly(monkeypatch):
    from discovery.base import DiscoveryError

    def no_credits(url, headers, json, timeout):
        return FakeResp(status_code=400, payload={}, text='{"message":"Not enough credits","statusCode":400}')

    monkeypatch.setattr(serp_mod.httpx, "post", no_credits)
    with pytest.raises(DiscoveryError, match="out of credits"):
        _client().search_posts(["q1"], datetime(2025, 1, 1, tzinfo=UTC))


def test_pagination_fetches_multiple_pages_and_dedupes(monkeypatch):
    """Pagination is the recall lever: one query should fetch `pages` result
    pages and return the union of unique posts (deduped by canonical URL).
    Deep pages run in parallel, so page-request order is not asserted."""
    import threading

    url_lock = threading.Lock()
    url_seen = []

    def fake_post(url, headers, json, timeout):
        with url_lock:
            url_seen.append(json.get("page", 1))
        page = json.get("page", 1)
        # Full pages (>= per_q) so paging continues; empty page 3 stops it.
        bucket = {
            1: [
                {"link": "https://www.linkedin.com/posts/p1", "title": "t", "snippet": "looking for a video editor"},
                {"link": "https://www.linkedin.com/posts/p2", "title": "t", "snippet": "need a plumber"},
                {"link": "https://www.linkedin.com/posts/p1e1", "title": "t", "snippet": "e"},
                {"link": "https://www.linkedin.com/posts/p1e2", "title": "t", "snippet": "e"},
                {"link": "https://www.linkedin.com/posts/p1e3", "title": "t", "snippet": "e"},
            ],
            2: [
                {"link": "https://www.linkedin.com/posts/p1?trk=share", "title": "dup", "snippet": "dup of p1"},
                {"link": "https://www.linkedin.com/posts/p3", "title": "t", "snippet": "anyone know a good designer"},
                {"link": "https://www.linkedin.com/posts/p2e1", "title": "t", "snippet": "e"},
                {"link": "https://www.linkedin.com/posts/p2e2", "title": "t", "snippet": "e"},
                {"link": "https://www.linkedin.com/posts/p2e3", "title": "t", "snippet": "e"},
            ],
            3: [],
        }
        return FakeResp(payload={"organic": bucket.get(page, [])})

    monkeypatch.setattr(serp_mod.httpx, "post", fake_post)
    since = datetime(2025, 1, 1, tzinfo=UTC)
    client = SerperDiscoveryClient("test-serper-key", results_per_query=5, pages_per_query=3)
    batch = client.search_posts(["q1"], since)
    # 10 raw posts across pages 1-2, deduped to 9 unique (p1?trk=share == p1).
    assert len(batch.posts) == 9
    assert sorted(url_seen) == [1, 2, 3]  # requested pages 1,2,3 (any order for 2/3)
    assert len({p.post_url for p in batch.posts}) == 9


def test_deep_pages_fetched_only_for_full_first_pages(monkeypatch):
    """Phase-2 paging runs concurrently but ONLY for queries whose page 1 was
    full — a short first page means Google signaled the last page, and paging
    it would waste credits."""
    import threading

    req_lock = threading.Lock()
    requested: list[tuple[str, int]] = []

    def fake_post(url, headers, json, timeout):
        q = json["q"]
        page = json.get("page", 1)
        with req_lock:
            requested.append((q, page))
        if page == 1:
            # "full..." queries fill the page; "short..." ones don't.
            n = 5 if q.startswith("full") else 2
            tag = "fl" if q.startswith("full") else "sh"
            items = [
                {"link": f"https://www.linkedin.com/posts/{tag}-{page}-{i}", "title": "t", "snippet": "looking for a dev"}
                for i in range(n)
            ]
            return FakeResp(payload={"organic": items})
        return FakeResp(payload={"organic": []})

    monkeypatch.setattr(serp_mod.httpx, "post", fake_post)
    since = datetime(2025, 1, 1, tzinfo=UTC)
    client = SerperDiscoveryClient("test-serper-key", results_per_query=5, pages_per_query=3)
    batch = client.search_posts(["full one", "short two"], since)
    deep = [q for q, page in requested if page > 1]
    assert len(deep) == 2  # pages 2 and 3 for the ONE full query only
    assert all(q.startswith("full") for q in deep)
    short_posts = [p for p in batch.posts if p.post_url.startswith("https://www.linkedin.com/posts/sh-")]
    assert len(short_posts) == 2  # short query: exactly its page-1 posts


def test_call_counter_is_thread_safe_and_exact(monkeypatch):
    """Discovery calls run in parallel; the spend counter must equal the real
    number of HTTP requests (the per-search ceiling depends on it)."""
    import threading

    lock = threading.Lock()
    requests = {"n": 0}

    def fake_post(url, headers, json, timeout):
        with lock:
            requests["n"] += 1
            n = requests["n"]
        return FakeResp(payload={"organic": [
            {"link": f"https://www.linkedin.com/posts/p-{n}", "title": "t", "snippet": "s"},
        ]})

    monkeypatch.setattr(serp_mod.httpx, "post", fake_post)
    since = datetime(2025, 1, 1, tzinfo=UTC)
    client = _client()
    queries = [f"query {i}" for i in range(20)]
    batch = client.search_posts(queries, since)
    # Each query's page 1 returns 1 result (< per_q) -> no deep pages.
    assert requests["n"] == 20
    assert client.calls == requests["n"]  # counter matches actual spend exactly
    assert len(batch.posts) == 20


def test_pagination_stops_early_when_page_is_short(monkeypatch):
    """Once a page returns fewer than `per_q` results, stop paging that query
    (Google signals the last page). No wasted credits on empty pages."""
    pages_requested = []

    def fake_post(url, headers, json, timeout):
        page = json.get("page", 1)
        pages_requested.append(page)
        items = [
            {"link": f"https://www.linkedin.com/posts/{page}-1", "title": "t", "snippet": "looking for a dev"}
        ] if page in (1, 2) else []
        return FakeResp(payload={"organic": items})

    monkeypatch.setattr(serp_mod.httpx, "post", fake_post)
    since = datetime(2025, 1, 1, tzinfo=UTC)
    client = SerperDiscoveryClient("test-serper-key", results_per_query=5, pages_per_query=5)
    batch = client.search_posts(["q"], since)
    # page1 (5/per_q => 1 result < per_q => stop). So only page 1 is fetched.
    assert pages_requested == [1]
    assert len(batch.posts) == 1
