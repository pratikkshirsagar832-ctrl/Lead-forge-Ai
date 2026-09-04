"""Tests for the in-house LinkedIn public post-scraper service.

Pure-function tests (payload, normalisation, summaries) plus a persistence
test with a faked Supabase + faked actor run — deterministic, no network.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.services import post_scraper_service as pss  # noqa: E402

SAMPLE_RECORD = {
    "postUrl": "https://www.linkedin.com/feed/update/urn:li:activity:123456/",
    "postId": "activity-123456",
    "text": "Hello LinkedIn!  " * 50,  # 700 chars -> exercises no truncation
    "authorName": "Pratik Kshirsagar",
    "authorUrl": "https://www.linkedin.com/in/pratik-kshirsagar-9a344739b/",
    "authorHeadline": "Full-stack developer",
    "authorType": "person",
    "datePosted": "2026-09-01T10:00:00Z",
    "relativeDate": "2d",
    "numLikes": 12,
    "numComments": None,
    "numShares": 3,
    "hashtags": ["#webdev"],
    "mentions": [],
    "media": [],
    "sourceUrl": "https://www.linkedin.com/in/pratik-kshirsagar-9a344739b/",
    "extractionMethod": "scored-layered",
    "extractedAt": "2026-09-04T08:00:00Z",
    "extractionStatus": "success",
    "qualityScore": 0.97,
}


# ── Payload ──────────────────────────────────────────────────────────────

def test_build_payload_profile_only():
    payload = pss.build_actor_payload(profile_urls=[" https://www.linkedin.com/in/x "], max_posts_per_profile=7)
    assert payload["profileUrls"] == ["https://www.linkedin.com/in/x"]
    assert "postUrls" not in payload
    assert payload["maxPostsPerProfile"] == 7
    assert payload["includeEngagement"] is True
    assert payload["includeAuthor"] is True


def test_build_payload_clamps_max_posts():
    assert pss.build_actor_payload(profile_urls=["u"], max_posts_per_profile=5000)["maxPostsPerProfile"] == 50
    assert pss.build_actor_payload(profile_urls=["u"], max_posts_per_profile=0)["maxPostsPerProfile"] == 1


def test_build_payload_requires_some_url():
    with pytest.raises(ValueError):
        pss.build_actor_payload()


# ── Normalisation ────────────────────────────────────────────────────────

def test_normalize_record_maps_fields():
    row = pss.normalize_actor_record(SAMPLE_RECORD)
    assert row["post_url"] == SAMPLE_RECORD["postUrl"]
    assert row["post_id"] == "activity-123456"
    assert row["post_text"].startswith("Hello LinkedIn!")
    assert row["author_name"] == "Pratik Kshirsagar"
    assert row["author_type"] == "person"
    assert row["num_likes"] == 12
    assert row["num_comments"] is None
    assert row["num_shares"] == 3
    assert row["hashtags"] == ["#webdev"]
    assert row["extraction_status"] == "success"
    assert row["posted_at"] == "2026-09-01T10:00:00Z"


def test_normalize_record_long_text_truncated():
    rec = dict(SAMPLE_RECORD)
    rec["text"] = "x" * 9000
    row = pss.normalize_actor_record(rec)
    assert len(row["post_text"]) == pss.POST_TEXT_MAX


def test_normalize_record_invalid_status_falls_back_to_unresolved():
    rec = dict(SAMPLE_RECORD)
    rec["extractionStatus"] = "whatever"
    assert pss.normalize_actor_record(rec)["extraction_status"] == "unresolved"


def test_normalize_record_bad_engagement_is_none():
    rec = dict(SAMPLE_RECORD)
    rec["numLikes"] = "1,234"
    rec["numShares"] = "abc"
    row = pss.normalize_actor_record(rec)
    assert row["num_likes"] is None
    assert row["num_shares"] is None


def test_summarize_records_counts_statuses():
    recs = [
        pss.normalize_actor_record(SAMPLE_RECORD),
        pss.normalize_actor_record({**SAMPLE_RECORD, "postId": "b", "postUrl": "…/urn:li:activity:2/", "extractionStatus": "partial"}),
        pss.normalize_actor_record({**SAMPLE_RECORD, "postId": "c", "postUrl": None, "extractionStatus": "unresolved"}),
    ]
    summary = pss.summarize_records(recs)
    assert summary["totals"]["discovered"] == 3
    assert summary["totals"]["success"] == 1
    assert summary["totals"]["partial"] == 1
    assert summary["totals"]["unresolved"] == 1
    assert len(summary["per_profile"]) == 1


# ── Persistence (faked supabase + faked actor) ───────────────────────────

class _FakeQuery:
    def __init__(self, store, table, method):
        self._store = store
        self._table = table
        self._method = method

    def eq(self, *a, **k):  # ignore filters for the fake
        return self

    def neq(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def order(self, *a, **k):
        return self

    def range(self, a, b):
        return self

    def execute(self):
        if self._method == "select":
            rows = self._store.get(self._table, [])
            if rows:
                return type("R", (), {"data": rows, "count": len(rows)})()
            return type("R", (), {"data": [], "count": 0})()
        if self._method == "insert":
            inserted = self._store.get("_inserted", [])
            inserted.append(self._store["_payload"])
            return type("R", (), {"data": [self._store["_payload"]]})()

    def select(self, *a, **k):
        return self

    def insert(self, rows):
        self._store["_payload"] = rows
        return _FakeQuery(self._store, self._table, "insert")


class _FakeTable:
    def __init__(self, store, table):
        self._store = store
        self._table = table

    def select(self, *a, **k):
        return _FakeQuery(self._store, self._table, "select")

    def insert(self, rows):
        self._store["_payload"] = rows
        return _FakeQuery(self._store, self._table, "insert")


class _FakeSupabase:
    def __init__(self):
        self._store = {"_inserted": []}

    def table(self, name):
        return _FakeTable(self._store, name)


def test_store_persists_and_dedupes(monkeypatch):
    fake = _FakeSupabase()
    monkeypatch.setattr(
        pss, "run_post_scraper_actor", lambda payload: [SAMPLE_RECORD, SAMPLE_RECORD]
    )
    result = pss.store_profile_posts_sync(
        fake, "user-1", profile_urls=["https://www.linkedin.com/in/x"], lead_id="lead-1"
    )
    # Second identical actor record is a duplicate row (post_url in row list),
    # but the fake stores what we pass; run twice through a real store to see dedupe:
    inserted = fake._store["_inserted"]
    assert len(inserted) == 1  # one insert call
    assert inserted[0][0]["user_id"] == "user-1"
    assert inserted[0][0]["lead_id"] == "lead-1"
    assert result["saved_count"] == 1
    assert result["actor_records"] == 2  # duplicate detected within this batch
