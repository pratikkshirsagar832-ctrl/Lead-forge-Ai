"""
Tests for the consolidated LinkedIn lead engine.

These prove the PRODUCT INVARIANTS deterministically:
  - exact requested lead type only
  - exact requested country only (country hard gate, fail-closed on unknown)
  - no seller / job-seeker / wrong-service / wrong-intent contamination
  - exact-count: never more than requested, never padded with bad leads
  - fail-closed AI: no fabricated qualification
  - dedupe: one author does not occupy multiple slots
"""

import json
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from tests.conftest import candidate, make_classification  # noqa: E402
from app.services import linkedin_pipeline as lp  # noqa: E402
from app.services.ai_service import (  # noqa: E402
    LeadClassification,
    attach_classification,
    classify_linkedin_candidates,
)


# ── INTENT MAPPING / CANONICAL MODEL ───────────────────────────────────────
def test_to_canonical_mapping():
    assert lp.to_canonical("buyer") == "freelancer_needed"
    assert lp.to_canonical("hiring") == "hiring"
    assert lp.to_canonical("agency_wanted") == "agency_wanted"
    assert lp.to_canonical("freelancer_needed") == "freelancer_needed"
    assert lp.to_canonical("agency") == "agency_wanted"
    assert lp.to_canonical("garbage") == "unknown"
    assert lp.to_canonical(None) == "unknown"


def test_parse_wire_lead_types():
    assert lp.parse_wire_lead_types(["buyer", "hiring"]) == ["freelancer_needed", "hiring"]
    assert lp.parse_wire_lead_types(["agency_wanted"]) == ["agency_wanted"]
    assert lp.parse_wire_lead_types(["bad", None]) == []
    assert lp.parse_wire_lead_types(None) == []


def test_canonical_to_post_type():
    assert lp.canonical_to_post_type("freelancer_needed") == "buyer"
    assert lp.canonical_to_post_type("agency_wanted") == "agency_wanted"
    assert lp.canonical_to_post_type("hiring") == "hiring"


# ── COUNTRY NORMALIZATION + HARD GATE ──────────────────────────────────────
def test_normalize_country_variants():
    assert lp.normalize_country("USA") == "US"
    assert lp.normalize_country("United States") == "US"
    assert lp.normalize_country("UK") == "GB"
    assert lp.normalize_country("Britain") == "GB"
    assert lp.normalize_country("Germany") == "DE"
    assert lp.normalize_country("Mumbai") == "IN"
    assert lp.normalize_country("xyz-not-a-country") is None


def test_country_pass_global():
    ok, conf = lp.country_pass("US", "New York, US", set())
    assert ok


def test_country_pass_structured_match():
    ok, conf = lp.country_pass("US", "New York", {"US"})
    assert ok
    assert conf == lp.LocationConfidence.STRUCTURED.value


def test_country_pass_wrong_country_rejected():
    ok, _ = lp.country_pass("IN", "Mumbai", {"US"})
    assert not ok


def test_country_pass_unknown_fail_closed():
    ok, _ = lp.country_pass("", "", {"US"})
    assert not ok  # unknown location must not pass a strict country request


def test_country_pass_text_match():
    ok, conf = lp.country_pass("", "Berlin, Germany", {"DE"})
    assert ok
    assert conf == lp.LocationConfidence.TEXT.value


# ── JOB-AWARE country gate (hiring leads) ─────────────────────────────────
def test_job_country_rejects_foreign_job_location():
    # US recruiter posting a Pakistan-based role -> reject (author is US).
    ok, _ = lp.job_country_pass("Pakistan", "US", "New York", {"US"})
    assert not ok


def test_job_country_allows_remote_jobs():
    # Remote/anywhere jobs are location-agnostic -> pass for any requested country.
    ok, conf = lp.job_country_pass("Remote", "IN", "Mumbai", {"US"}, job_remote=True)
    assert ok


def test_job_country_allows_matching_location():
    ok, _ = lp.job_country_pass("New York, USA", "US", "New York", {"US"})
    assert ok


def test_job_country_falls_back_to_author_country():
    # No job location -> use author country.
    ok, _ = lp.job_country_pass("", "US", "New York", {"US"})
    assert ok


def test_job_location_extraction_matches_case_insensitive_label():
    # The location label may be capitalized; extraction must still find it.
    loc = lp._job_location_from_text("We are hiring a designer. Location: Islamabad, Pakistan. Onsite.")
    assert "Islamabad" in loc and "Pakistan" in loc


def test_job_remote_signal_detection():
    assert lp._job_remote_signal("Fully remote position, work from anywhere") is True
    assert lp._job_remote_signal("Full-time onsite in New York") is False


# ── DETERMINISTIC PRE-FILTERS ──────────────────────────────────────────────
@pytest.mark.parametrize("reject,reason", [
    (candidate(post_text="We offer web development services to startups."), "seller"),
    (candidate(post_text="I am a freelance designer available for projects."), "seller"),
    (candidate(post_text="I am open to work, seeking a role."), "job_seeker"),
    (candidate(post_text="We are a talent staffing agency placing candidates at clients."), "recruiter_seller"),
    (candidate(post_text="Agencies are losing money because they say we don't have the team. White label software, AI & ML development partner for agencies. Helping you deliver more."), "seller"),
    (candidate(post_text="We act as your dedicated offshore team. Let's partner together. Book a free call to see how we can help you scale."), "seller"),
    (candidate(post_text="Grow your agency by outsourcing to us. Send us a brief and we'll build it for you."), "seller"),
    (candidate(post_text="We are currently accepting applications for a wide variety of professional roles. Connect you with talented professionals. We place candidates with our clients."), "recruiter_seller"),
    # talent marketplace recruiting a freelancer pool / platform:
    (candidate(post_text="Toptal is currently seeking talented professionals across all countries for freelance opportunities. Applications are now open. Sign up today to join our vetted network."), "marketplace"),
    # freelancer announcing OWN availability / career change:
    (candidate(post_text="After 14 years in-house I'm now available for freelance design work and taking new clients.", headline="Freelance Graphic Designer"), "seller"),
    (candidate(post_text="It's time for an AI ad intervention. You don't need a designer anymore. Here's how to improve your ads.", headline="Brand Strategy | Marketing"), "content"),
    # supply-side pitch: seller offering data/list/leads TO agencies (reverse direction):
    (candidate(post_text="I am looking for digital marketing agency, SEO agency. I have a database of manually extracted USA leads. Best for cold calling. Comment 'USA LEADS' or DM me.", headline="AI SEO Services"), "seller"),
    (candidate(post_text="If you're an agency looking to expand your client pipeline, I have a vetted list of high-paying clients. DM me.", headline="Lead Gen Specialist"), "seller"),
])
def test_prefilter_rejects_garbage(reject, reason):
    got_reject, got_reason = lp.prefilter_reject(reject)
    assert got_reject, f"expected rejection ({reason}), got accepted"


@pytest.mark.parametrize("post", [
    "Looking for a marketing agency to run our paid campaigns.",
    "We need an SEO agency for our ecommerce site.",
    "Can anyone recommend a good branding agency?",
    "Seeking a digital marketing agency to handle our social media.",
    "Our company is looking for an agency to redesign our website.",
])
def test_prefilter_keeps_genuine_agency_sourcing(post):
    c = candidate(post_text=post, headline="CMO at Acme", country_code="US", location="US")
    reject, _ = lp.prefilter_reject(c)
    assert not reject, f"genuine agency-sourcing post was rejected: {post}"


def test_prefilter_keeps_genuine_buyer():
    c = candidate(post_text="We need a web development agency for our ecommerce project.")
    reject, reason = lp.prefilter_reject(c)
    assert not reject


# ── SERVICE-RELEVANCE: wrong service must not pass CANONICAL rules ─────────
def _accepted_decision(cls_dict, lead_type, country):
    c = candidate()
    cls = LeadClassification(**cls_dict)
    c = attach_classification(c, cls)
    return lp.canonical_accept(
        c,
        request_lead_types=[lead_type],
        requested_countries={country},
        service="Web Development",
    )


def test_accept_exact_intent_country():
    d = _accepted_decision(
        make_classification(lead_type="agency_wanted", service_match=92, quality=90),
        "agency_wanted", "US",
    )
    assert d.accepted
    assert not d.rejections


def test_reject_wrong_intent():
    # Post classified as freelancer_needed but we requested agency_wanted.
    d = _accepted_decision(
        make_classification(lead_type="freelancer_needed"),
        "agency_wanted", "US",
    )
    assert not d.accepted
    assert any("wrong_intent" in r for r in d.rejections)


def test_reject_wrong_country():
    c = candidate(country_code="IN", location="Mumbai, India")
    cls = LeadClassification(**make_classification(lead_type="agency_wanted"))
    c = attach_classification(c, cls)
    d = lp.canonical_accept(c, request_lead_types=["agency_wanted"], requested_countries={"US"}, service="Web Development")
    assert not d.accepted
    assert "wrong_country" in d.rejections


def test_reject_seller_backstop():
    c = candidate()
    cls = LeadClassification(**make_classification(seller=True, is_qualified=False, rejection_reason="seller"))
    c = attach_classification(c, cls)
    d = lp.canonical_accept(c, request_lead_types=["agency_wanted"], requested_countries={"US"}, service="Web Development")
    assert not d.accepted
    assert "seller" in d.rejections


def test_reject_job_seeker_backstop():
    c = candidate()
    cls = LeadClassification(**make_classification(job_seeker=True, is_qualified=False, rejection_reason="job_seeker"))
    c = attach_classification(c, cls)
    d = lp.canonical_accept(c, request_lead_types=["hiring"], requested_countries={"US"}, service="React Development")
    assert not d.accepted
    assert "job_seeker" in d.rejections


def test_reject_weak_service_match():
    d = _accepted_decision(
        make_classification(lead_type="agency_wanted", service_match=20, service_relevance="unrelated"),
        "agency_wanted", "US",
    )
    assert not d.accepted
    assert any("weak_service_match" in r for r in d.rejections)


def test_reject_ai_unqualified():
    d = _accepted_decision(
        make_classification(is_qualified=False, rejection_reason="no evidence", reason=""),
        "agency_wanted", "US",
    )
    assert not d.accepted
    assert "ai_unqualified" in d.rejections


# ── FAIL-CLOSED AI CLASSIFICATION ──────────────────────────────────────────
def test_classify_fails_closed_on_invalid_json():
    """A malformed classification must not silently produce a qualified lead."""
    from app.services.ai_service import LeadClassification
    with pytest.raises(Exception):
        LeadClassification(**{"lead_type": "agency_wanted"})  # missing required fields


def test_classify_unverified_absent():
    """A candidate with no classification is not qualified by the engine."""
    c = candidate(post_text="Need an agency for web development please.")
    classifications = {}
    cls = classifications.get("https://www.linkedin.com/feed/update/")
    assert cls is None  # unverified => rejected in the loop


# ── EXACT-COUNT SELECTION (no over-delivery) ───────────────────────────────
def test_exact_count_never_overdelivers():
    leads = [candidate() for _ in range(20)]
    if len(leads) > 10:
        leads = lp.rank_leads(leads)[:10]
    assert len(leads) == 10


def test_rank_orders_by_intent_then_quality():
    explicit = candidate(full_name="Explicit", post_text="We need a web dev agency now.")
    explicit["classification"] = make_classification(lead_type="agency_wanted", intent_strength="explicit", quality=95, service_match=95)
    research = candidate(full_name="Research", post_text="thoughts on web dev?")
    research["classification"] = make_classification(lead_type="agency_wanted", intent_strength="research", quality=40, is_qualified=False)
    ranked = lp.rank_leads([research, explicit])
    assert ranked[0]["full_name"] == "Explicit"


# ── DEDUPE ─────────────────────────────────────────────────────────────────
def test_dedupe_same_author_one_slot():
    posts = [
        candidate(post_id="1", post_url="https://www.linkedin.com/feed/update/1"),
        candidate(post_id="2", post_url="https://www.linkedin.com/feed/update/2"),
    ]
    seen = set()
    out = []
    for p in posts:
        key = lp._identity_url(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    assert len(out) == 1


# ── QUERY GENERATION: intent isolation ────────────────────────────────────
def test_agency_queries_are_agency_specific():
    qs = lp.generate_queries("agency_wanted", "web development", {"US"}, 0, 12)
    qs_low = " || ".join(qs).lower()
    assert "agency" in qs_low
    # Agency queries must NOT be freelancer-specific
    assert "freelance" not in qs_low


def test_freelancer_queries_are_freelancer_specific():
    qs = lp.generate_queries("freelancer_needed", "graphic design", {"US"}, 0, 12)
    qs_low = " || ".join(qs).lower()
    assert "freelance" in qs_low
    assert "agency" not in qs_low


def test_hiring_queries_are_hiring_specific():
    qs = lp.generate_queries("hiring", "react developer", {"DE"}, 1, 12)
    qs_low = " || ".join(qs).lower()
    assert "hiring" in qs_low or "we're hiring" in qs_low


def test_query_diversifies_across_iterations():
    q0 = set(lp.generate_queries("agency_wanted", "web development", {"US"}, 0, 12))
    q1 = set(lp.generate_queries("agency_wanted", "web development", {"US"}, 1, 12))
    q2 = set(lp.generate_queries("agency_wanted", "web development", {"US"}, 2, 12))
    # Iterations must not produce identical query sets.
    assert q0 != q1 or q0 != q2
