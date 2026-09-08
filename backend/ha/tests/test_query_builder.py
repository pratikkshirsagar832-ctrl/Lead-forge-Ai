import pytest

from models import LeadType
from query_builder import NEGATIVE_QUERY_PHRASES, build_plan, next_queries, split_query

# §0: templates must work for ANY service — a spread across unrelated niches.
GENERIC_SERVICES = [
    "a video editor",
    "a plumber",
    "a UX designer",
    "a wedding photographer",
    "an ad film agency",
    "social media management",
    "a bookkeeper",
]


@pytest.mark.parametrize("service", GENERIC_SERVICES)
def test_base_set_is_multiple_queries_per_type(service):
    for lt in LeadType:
        plan = build_plan(service, lt)
        assert 3 <= len(plan.base) <= 5, (service, lt, plan.base)


@pytest.mark.parametrize("service", GENERIC_SERVICES)
def test_service_words_survive_phrasing(service):
    plan = build_plan(service, LeadType.NEED_FREELANCER)
    assert any("looking for" in q for q in plan.base)
    assert any("need" in q for q in plan.base)


def test_typed_article_is_not_doubled():
    plan = build_plan("a video editor", LeadType.NEED_FREELANCER)
    assert plan.base[0].startswith("looking for a video editor")
    assert not any("a a video" in q or "for a a " in q for q in plan.base)


@pytest.mark.parametrize("service", GENERIC_SERVICES)
def test_every_query_pairs_negative_seller_phrases(service):
    for lt in LeadType:
        plan = build_plan(service, lt)
        for q in list(plan.base) + list(plan.pool):
            positive, negatives = split_query(q)
            assert set(negatives) == set(NEGATIVE_QUERY_PHRASES), q
            assert positive  # a query is never ONLY negatives
            for n in NEGATIVE_QUERY_PHRASES:
                assert f'-"{n}"' in q.lower(), (q, n)


def test_split_query_roundtrip():
    q = 'looking for a plumber -"we offer" -"our services" -"book a call" -"dm us" -"we specialize" -"we help"'
    positive, negatives = split_query(q)
    assert positive == "looking for a plumber"
    assert set(negatives) == {"we offer", "our services", "book a call", "dm us", "we specialize", "we help"}


def test_no_duplicate_queries():
    for lt in LeadType:
        plan = build_plan("social media manager", lt)
        keys = [split_query(q)[0].lower() for q in list(plan.base) + list(plan.pool)]
        assert len(keys) == len(set(keys))


def test_need_freelancer_covers_individual_and_company_buyers():
    plan = build_plan("video editor", LeadType.NEED_FREELANCER)
    joined = " | ".join(split_query(q)[0] for q in plan.base).lower()
    assert "looking for" in joined or "need" in joined
    # No employee-hiring query language in the freelancer lane (job ads are
    # never leads); budget/urgency language stays available in the pool.
    pool = " | ".join(split_query(q)[0] for q in plan.pool).lower()
    assert "join our team" not in pool or "freelance" in pool


def test_our_agency_queries_are_company_seeking_agency():
    plan = build_plan("video editor", LeadType.OUR_AGENCY)
    positives = " | ".join(split_query(q)[0] for q in plan.base).lower()
    # The agency-wanted lane targets companies seeking an agency/outside team.
    assert any(p in positives for p in (
        "looking for an agency for",
        "need an agency for",
        "looking for a video editor agency",
        "recommendations for a video editor agency",
        "hiring an agency for",
    ))
    # Pool still carries agency-sourcing phrases (sibling engine lane), so a
    # freelancer-seller run never starves when companies seek agencies rarely.
    pool_pos = " | ".join(split_query(q)[0] for q in plan.pool).lower()
    assert "freelancers to work with our agency" in pool_pos or "client projects" in pool_pos
    # Self-promotion phrasing must never leak into the positive half.
    assert "our agency can help" not in positives
    assert "we specialize" not in positives


def test_diversification_grows_pool_and_repeats_nothing():
    plan = build_plan("video editor", LeadType.NEED_FREELANCER)
    it0 = next_queries("video editor", LeadType.NEED_FREELANCER, 0)
    it1 = next_queries("video editor", LeadType.NEED_FREELANCER, 1)
    assert set(it0) == set(plan.base)
    added = [q for q in it1 if q not in set(it0)]
    assert added  # iteration 1 must broaden
    assert len(it1) >= len(it0)
    assert len(plan.pool) >= 8
