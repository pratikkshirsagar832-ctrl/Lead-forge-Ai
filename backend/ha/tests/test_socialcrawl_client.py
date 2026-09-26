"""SocialCrawl discovery client: request shape, mapping, filters, errors.

The payload mirrors a real /v1/linkedin/search/posts response (2026-09)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from discovery import socialcrawl_client as sc_mod
from discovery.base import DiscoveryConfigError, DiscoveryError
from discovery.socialcrawl_client import SocialCrawlDiscoveryClient, date_filter_for
from models import LeadType
from query_builder import build_plan, emit_queries, next_queries, query_phrases


def _item(pid: str, text: str, *, hours_ago: float = 2, p: float | None = 0.9, comments: int = 3,
          username: str = "karl-g", name: str = "Karl Goldstraw") -> dict:
    published = (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
    return {
        "post": {
            "id": pid,
            "url": f"https://www.linkedin.com/feed/update/urn:li:activity:{pid}",
            "content": {"text": text},
            "author": {"username": username, "display_name": name, "avatar_url": None, "verified": None},
            "engagement": {"views": None, "likes": 4, "comments": comments, "shares": 0, "saves": None},
            "flags": {},
            "published_at": published,
            "ext": {},
        },
        "computed": {"language": "en", "relevance": ({"p": p, "sense": "target"} if p is not None else None)},
    }


def _body(items: list[dict], credits: int = 5) -> dict:
    return {"success": True, "platform": "linkedin", "endpoint": "/v1/linkedin/search/posts",
            "data": {"items": items, "walk": {"returned": len(items), "stopped": "limit"}},
            "credits_used": credits, "credits_remaining": 900, "cached": False,
            "pagination": {"next_cursor": None, "has_more": False, "page_size": len(items)}}


class FakeResp:
    def __init__(self, status: int, payload: dict | None):
        self.status_code = status
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


@pytest.fixture
def calls(monkeypatch):
    seen: list[dict] = []
    replies: dict[str, FakeResp] = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.append({"url": url, "params": dict(params or {}), "headers": dict(headers or {})})
        return replies.get(params["query"], FakeResp(200, _body([], 0)))

    monkeypatch.setattr(sc_mod.httpx, "get", fake_get)
    seen_obj = type("Calls", (), {"seen": seen, "replies": replies})
    return seen_obj


def test_date_filter_rounds_up():
    now = datetime(2026, 9, 24, 12, tzinfo=UTC)
    assert date_filter_for(now - timedelta(hours=20), now) == "past_24h"
    assert date_filter_for(now - timedelta(days=3), now) == "past_week"
    assert date_filter_for(now - timedelta(days=7), now) == "past_week"
    assert date_filter_for(now - timedelta(days=20), now) == "past_month"


def test_request_shape_and_mapping(calls):
    q = '"can anyone recommend an accountant" -"we offer"'
    calls.replies[q] = FakeResp(200, _body([
        _item("7508546539989028865", "Can anyone recommend an accountant for my Ltd company?"),
        _item("7508546539989028865", "duplicate of the same post"),
    ]))
    client = SocialCrawlDiscoveryClient("sc_test", results_per_query=25)
    res = client.search_posts([q], datetime.now(UTC) - timedelta(days=7))

    req = calls.seen[0]
    assert req["url"] == "https://www.socialcrawl.dev/v1/linkedin/search/posts"
    assert req["headers"]["x-api-key"] == "sc_test"
    assert req["params"] == {"query": q, "sort_by": "date_posted", "date_posted": "past_week", "limit": 25}

    assert len(res.posts) == 1  # deduped by canonical URL
    post = res.posts[0]
    assert post.text.startswith("Can anyone recommend")
    assert post.text_source == "full_post" and post.provider == "socialcrawl"
    assert post.author_name == "Karl Goldstraw"
    assert post.author_profile_url == "https://www.linkedin.com/in/karl-g"
    assert post.num_comments == 3
    assert post.posted_at and (datetime.now(UTC) - post.posted_at) < timedelta(hours=3)
    assert client.calls == 1 and client.credits_used == 5 and client.credits_remaining == 900
    assert res.raw_rows_seen == 2


def test_low_relevance_dropped_but_missing_score_kept(calls):
    q = '"need a video editor"'
    calls.replies[q] = FakeResp(200, _body([
        _item("1", "Need a video editor for our podcast", p=0.95),
        _item("2", "Unrelated VAT circular for Malta", p=0.05),
        _item("3", "Looking for a video editor, any leads?", p=None),
    ]))
    client = SocialCrawlDiscoveryClient("sc_test", min_relevance=0.2)
    res = client.search_posts([q], datetime.now(UTC) - timedelta(days=7))
    assert {p.post_url[-1] for p in res.posts} == {"1", "3"}
    assert client.relevance_dropped == 1


def test_empty_results_are_not_an_error(calls):
    client = SocialCrawlDiscoveryClient("sc_test")
    res = client.search_posts(['"very rare phrase"'], datetime.now(UTC) - timedelta(days=1))
    assert res.posts == [] and res.provider_errors == []
    assert calls.seen[0]["params"]["date_posted"] == "past_24h"


def test_bad_key_is_a_config_error(calls):
    calls.replies['"x"'] = FakeResp(401, {"success": False, "error": {"message": "invalid api key"}})
    with pytest.raises(DiscoveryConfigError):
        SocialCrawlDiscoveryClient("sc_bad").search_posts(['"x"'], datetime.now(UTC) - timedelta(days=7))


def test_out_of_credits_fails_the_round_loudly(calls):
    for q in ('"a"', '"b"'):
        calls.replies[q] = FakeResp(402, {"success": False, "error": {"message": "Insufficient credits"}})
    with pytest.raises(DiscoveryError, match="out of credits"):
        SocialCrawlDiscoveryClient("sc_test").search_posts(['"a"', '"b"'], datetime.now(UTC) - timedelta(days=7))


def test_one_failed_query_does_not_kill_the_round(calls):
    calls.replies['"bad"'] = FakeResp(500, {"success": False, "error": {"message": "upstream"}})
    calls.replies['"good"'] = FakeResp(200, _body([_item("9", "Need a plumber in Pune today")]))
    res = SocialCrawlDiscoveryClient("sc_test").search_posts(['"bad"', '"good"'], datetime.now(UTC) - timedelta(days=7))
    assert len(res.posts) == 1 and len(res.provider_errors) == 1


def test_missing_key_rejected():
    with pytest.raises(DiscoveryConfigError):
        SocialCrawlDiscoveryClient("")


def test_single_style_emits_one_quoted_phrase_per_query():
    plan = build_plan("chartered accountant", LeadType.NEED_FREELANCER, "single")
    assert len(plan.base) == 8
    for q in plan.base:
        assert " OR " not in q
        assert len(query_phrases(q)) == 1
        assert q.startswith('"') and '-"we offer"' in q
    # loose recall queries: noun AND verb, still no OR-group
    assert any(q.startswith('"chartered accountant" "recommend"') for q in plan.pool)
    assert emit_queries(["need a CA for GST"], "single") == [
        '"need a CA for GST" -"we offer" -"open to work" -"available for hire"']
    # later rounds never repeat round-0 phrasings
    base_phrases = {query_phrases(q)[0].lower() for q in plan.base}
    for i in (1, 2, 3):
        for q in next_queries("chartered accountant", LeadType.NEED_FREELANCER, i, style="single"):
            phrases = query_phrases(q)
            assert not (len(phrases) == 1 and phrases[0].lower() in base_phrases)


# ------------------------------------------------------------- key rotation

def test_rotates_to_next_key_when_credits_run_out(monkeypatch):
    from discovery.keypool import KeyPool

    used_keys: list[str] = []

    def fake_get(url, params=None, headers=None, timeout=None):
        key = headers["x-api-key"]
        used_keys.append(key)
        if key == "sc_dry":
            return FakeResp(402, {"success": False, "error": {"message": "Insufficient credits"}})
        if key == "sc_bad":
            return FakeResp(401, {"success": False, "error": {"message": "invalid api key"}})
        body = _body([_item("7", "Need an accountant for my startup")], credits=5)
        body["credits_remaining"] = 40
        return FakeResp(200, body)

    monkeypatch.setattr(sc_mod.httpx, "get", fake_get)
    changes, usage = [], []
    pool = KeyPool.from_keys(["sc_dry", "sc_bad", "sc_good"])
    pool._on_change = lambda k, reason: changes.append((k.key, k.status))
    pool._on_usage = lambda k, credits, remaining: usage.append((k.key, credits, remaining))
    client = SocialCrawlDiscoveryClient(pool)

    res = client.search_posts(['"need an accountant"'], datetime.now(UTC) - timedelta(days=7))
    assert len(res.posts) == 1 and res.provider_errors == []
    assert used_keys == ["sc_dry", "sc_bad", "sc_good"]          # same request retried on each key
    assert changes == [("sc_dry", "exhausted"), ("sc_bad", "invalid")]
    assert usage == [("sc_good", 5, 40)]

    used_keys.clear()
    client.search_posts(['"need a plumber"'], datetime.now(UTC) - timedelta(days=7))
    assert used_keys == ["sc_good"]                                # dead keys are skipped afterwards


def test_all_keys_dry_revives_topped_up_key_or_fails(monkeypatch):
    from discovery.keypool import KeyPool

    topped_up = {"sc_a": False}

    def fake_get(url, params=None, headers=None, timeout=None):
        if headers["x-api-key"] == "sc_a" and topped_up["sc_a"]:
            return FakeResp(200, _body([_item("8", "Looking for a video editor")], credits=5))
        return FakeResp(402, {"success": False, "error": {"message": "Insufficient credits"}})

    monkeypatch.setattr(sc_mod.httpx, "get", fake_get)

    def refresher(k):
        topped_up["sc_a"] = True
        return 500 if k.key == "sc_a" else 0

    pool = KeyPool.from_keys(["sc_a", "sc_b"])
    pool._refresher = refresher
    res = SocialCrawlDiscoveryClient(pool).search_posts(['"q"'], datetime.now(UTC) - timedelta(days=7))
    assert len(res.posts) == 1  # sc_a came back after the balance check

    with pytest.raises(DiscoveryError, match="out of credits"):
        SocialCrawlDiscoveryClient(KeyPool.from_keys(["sc_x", "sc_y"])).search_posts(
            ['"q1"', '"q2"'], datetime.now(UTC) - timedelta(days=7))


def test_zero_balance_marks_key_exhausted_proactively(monkeypatch):
    from discovery.keypool import KeyPool

    def fake_get(url, params=None, headers=None, timeout=None):
        body = _body([_item("9", "Need a lawyer")], credits=4)
        body["credits_remaining"] = 0
        return FakeResp(200, body)

    monkeypatch.setattr(sc_mod.httpx, "get", fake_get)
    pool = KeyPool.from_keys(["sc_last", "sc_next"])
    SocialCrawlDiscoveryClient(pool).search_posts(['"q"'], datetime.now(UTC) - timedelta(days=7))
    assert [k.status for k in pool.keys] == ["exhausted", "active"]
    assert pool.acquire().key == "sc_next"


def test_free_intent_labels_are_mapped_onto_the_post(calls):
    """SocialCrawl's free intent label (shape verified live 2026-09) rides on
    RawPost; a post without labels maps to None (never dropped for it)."""
    q = "looking for graphic designer recommendations"
    labelled = _item("7508546539989028866", "I am looking for a graphic designer for a book cover")
    labelled["computed"]["labels"] = {"intent": {
        "label": "asking_for_recommendation", "confidence": 0.97, "buyer": True,
        "seller": 0.02, "fits_offer": None, "urgency": 1.86}}
    calls.replies[q] = FakeResp(200, _body([labelled, _item("7508546539989028867", "no labels here")]))
    res = SocialCrawlDiscoveryClient("sc_test").search_posts([q], datetime.now(UTC) - timedelta(days=7))

    a, b = res.posts
    assert (a.intent_label, a.intent_buyer, a.intent_seller, a.intent_urgency, a.intent_confidence) == \
        ("asking_for_recommendation", True, 0.02, 1.86, 0.97)
    assert (b.intent_label, b.intent_buyer, b.intent_urgency) == (None, None, None)


def test_keys_too_low_for_one_request_leave_rotation():
    """Production logs showed keys with 3-4 credits (a request needs 5) being
    tried on every request. They now leave rotation as soon as that is known."""
    from discovery.keypool import KeyPool

    pool = KeyPool.from_keys(["sc_low", "sc_ok"])
    low, ok = pool.keys
    pool.report(low, credits_used=5, credits_remaining=4)
    assert low.status == "exhausted"
    assert pool.acquire() is ok

    pool2 = KeyPool.from_keys(["sc_a", "sc_b"])
    a, b = pool2.keys
    a.credits_remaining = 3            # e.g. loaded from the DB snapshot
    assert pool2.acquire() is b        # skipped without a wasted request
    assert a.status == "exhausted"
