import pytest

from models import LeadType
from query_builder import (
    NEGATIVE_QUERY_PHRASES,
    PACKED_NEGATIVE_PHRASES,
    build_plan,
    next_queries,
    pack_phrases,
    query_phrases,
    split_query,
)

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
    # Precision-first base still carries both a "looking for" and a "need" verb
    # so the multi-query set covers individual + company buyers.
    assert any("looking for" in q for q in plan.base)
    assert any("need" in q for q in plan.base)


def test_typed_article_is_not_doubled():
    for style in ("packed", "legacy"):
        plan = build_plan("a video editor", LeadType.NEED_FREELANCER, style)
        assert query_phrases(plan.base[0])[0].startswith("looking for a video editor")
        assert not any("a a video" in q or "for a a " in q for q in plan.base)


@pytest.mark.parametrize("service", GENERIC_SERVICES)
@pytest.mark.parametrize("style,expected", [("legacy", NEGATIVE_QUERY_PHRASES),
                                            ("packed", PACKED_NEGATIVE_PHRASES)])
def test_every_query_pairs_negative_seller_phrases(service, style, expected):
    for lt in LeadType:
        plan = build_plan(service, lt, style)
        for q in list(plan.base) + list(plan.pool):
            positive, negatives = split_query(q)
            assert set(negatives) == set(expected), q
            assert positive  # a query is never ONLY negatives
            for n in expected:
                assert f'-"{n}"' in q.lower(), (q, n)


@pytest.mark.parametrize("service", GENERIC_SERVICES)
def test_packed_queries_quote_phrases_and_fit_googles_word_window(service):
    """Packed queries are exact-phrase OR-groups that stay inside Google's
    ~32-word query window (incl. the site: operator the client appends), so
    Google never silently drops the tail (negatives / site:)."""
    for lt in LeadType:
        plan = build_plan(service, lt, "packed")
        for q in list(plan.base) + list(plan.pool):
            positive, _ = split_query(q)
            assert positive.startswith(('"', '("')), q
            assert len(q.split()) + 1 <= 32, q  # +1 for site:linkedin.com/posts


def test_packed_round_zero_covers_more_phrasings_in_same_calls():
    packed = build_plan("video editing", LeadType.NEED_FREELANCER, "packed")
    legacy = build_plan("video editing", LeadType.NEED_FREELANCER, "legacy")
    assert len(packed.base) < len(legacy.base)  # fewer Serper calls...
    phrasings = sum(len(query_phrases(q)) for q in packed.base)
    assert phrasings >= len(legacy.base)  # ...covering at least as many phrasings
    assert phrasings >= 2 * len(packed.base)


def test_pack_phrases_groups_with_or_and_respects_budget():
    packs = pack_phrases(["need a plumber", "anyone know a good plumber", 'plumber "urgent"'],
                         max_words=9)
    assert packs[0] == '("need a plumber" OR "anyone know a good plumber")'
    assert packs[1] == '"plumber urgent"'  # stray quotes never break the syntax
    assert query_phrases(packs[0] + ' -"we offer"') == ["need a plumber", "anyone know a good plumber"]


def test_query_style_env_switch(monkeypatch):
    monkeypatch.setenv("QUERY_STYLE", "legacy")
    assert not build_plan("a plumber", LeadType.NEED_FREELANCER).base[0].startswith(('"', "("))
    monkeypatch.setenv("QUERY_STYLE", "packed")
    assert build_plan("a plumber", LeadType.NEED_FREELANCER).base[0].startswith(('"', "("))


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


def test_need_agency_queries_are_client_seeking_agency():
    """Agency mode ("I'm an Agency") targets clients seeking an agency - never
    the retired agency-sources-freelancers direction, never self-promotion."""
    for style in ("packed", "legacy"):
        plan = build_plan("video editor", LeadType.NEED_AGENCY, style)
        positives = " | ".join(p for q in plan.base for p in query_phrases(q)).lower()
        assert any(p in positives for p in (
            "looking for an agency for",
            "need an agency for",
            "looking for a video editor agency",
            "recommendations for a video editor agency",
            "hiring an agency for",
        ))
        everything = " | ".join(p for q in list(plan.base) + list(plan.pool)
                                for p in query_phrases(q)).lower()
        assert "freelancers to work with our agency" not in everything
        assert "client projects" not in everything
        assert "our agency can help" not in everything
        assert "we specialize" not in everything


def test_our_agency_retired_lane_still_builds_sourcing_queries():
    plan = build_plan("video editor", LeadType.OUR_AGENCY, "legacy")
    pool_pos = " | ".join(split_query(q)[0] for q in plan.pool).lower()
    assert "freelancers to work with our agency" in pool_pos or "client projects" in pool_pos


def test_diversification_grows_pool_and_repeats_nothing():
    plan = build_plan("video editor", LeadType.NEED_FREELANCER)
    it0 = next_queries("video editor", LeadType.NEED_FREELANCER, 0)
    it1 = next_queries("video editor", LeadType.NEED_FREELANCER, 1)
    assert set(it0) == set(plan.base)
    added = [q for q in it1 if q not in set(it0)]
    assert added  # iteration 1 must broaden
    assert len(it1) >= len(it0)
    assert len(plan.pool) >= 8


def test_pool_slices_never_repeat_across_iterations():
    """Every Serper call must buy a fresh phrasing: the merged pool slices are
    non-overlapping, so no query ever appears in two iterations."""
    seen: set[str] = []
    for it in range(0, 10):
        for q in next_queries("video editing", LeadType.NEED_FREELANCER, it):
            assert q not in seen, f"query repeated in iteration {it}: {q}"
            seen.append(q)


def test_later_iterations_never_readd_base_queries():
    plan = build_plan("video editing", LeadType.NEED_FREELANCER)
    base = set(plan.base)
    for it in range(1, 6):
        qs = set(next_queries("video editing", LeadType.NEED_FREELANCER, it))
        assert qs and qs.isdisjoint(base)


def test_extra_pool_merges_at_head_with_negatives_and_dedupe():
    """LLM-expanded phrasings lead the first diversification round, carry the
    shared negative suffix, and dedupe against base positives."""
    first_round = next_queries(
        "video editing", LeadType.NEED_FREELANCER, 1,
        extra_pool=("custom buyer phrase", "looking for a video editor"), style="legacy",
    )
    assert first_round, "iteration 1 must return queries"
    # The unique expanded phrasing is merged at the HEAD with negatives.
    assert first_round[0].startswith('custom buyer phrase -"')
    _, negatives = split_query(first_round[0])
    assert set(negatives) == set(NEGATIVE_QUERY_PHRASES)
    # The duplicate-of-base phrasing ("looking for a video editor") is dropped;
    # longer pool phrasings sharing that prefix are legitimate and remain.
    positives = [split_query(q)[0] for q in first_round]
    assert "looking for a video editor" not in positives


def test_extra_pool_packed_leads_round_one_and_dedupes_base_phrases():
    first_round = next_queries(
        "video editing", LeadType.NEED_FREELANCER, 1,
        extra_pool=("custom buyer phrase", "another niche ask", "looking for a video editor"),
        style="packed",
    )
    head = query_phrases(first_round[0])
    assert head[:2] == ["custom buyer phrase", "another niche ask"]
    assert "looking for a video editor" not in head  # already in the base set
    _, negatives = split_query(first_round[0])
    assert set(negatives) == set(PACKED_NEGATIVE_PHRASES)


def test_extra_pool_too_short_still_fills_from_deterministic_pool():
    first_round = next_queries(
        "video editing", LeadType.NEED_FREELANCER, 1, extra_pool=("custom buyer phrase",),
        style="legacy",
    )
    assert first_round[0].startswith('custom buyer phrase -"')
    assert len(first_round) >= 4  # remaining slots come from the template pool
