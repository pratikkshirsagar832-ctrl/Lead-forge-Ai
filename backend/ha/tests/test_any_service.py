"""ANY service, ANY industry, ANY phrasing -> clean, searchable queries.

A guard for the promise that a user can type whatever they sell and get
sensible Google queries in both modes (Freelancer / Agency): no broken
grammar (exact-phrase search makes grammar matter), no echoed pitch text,
always inside Google's ~32-word query window.
"""
import re

import pytest

from models import LeadType
from query_builder import build_plan, is_messy_service, primary_service, query_phrases

SERVICES = [
    # creative / tech
    "video editing", "a video editor", "logo design", "UI/UX design", "web development",
    "app development", "SEO", "social media management", "copywriting", "ghostwriting",
    "motion graphics", "2D/3D animation", "wedding photography", "product photography",
    "AI chatbot development", "shopify store setup", "email marketing", "podcast editing",
    # professional
    "CA", "chartered accountant", "lawyer", "legal services", "bookkeeping", "tax filing",
    "HR consulting", "company secretary", "patent attorney", "financial modelling",
    # local / trades / people services
    "plumbing", "plumber in Nairobi", "interior design", "AC repair", "house cleaning",
    "catering", "wedding planning", "tutoring", "yoga trainer", "architecture",
    "event management", "translation", "virtual assistant", "data entry",
    # messy real-world input
    "I am a freelance video editor for YouTubers", "we offer SEO services for startups",
    "need clients for my bookkeeping business 🙏", "Web design & development",
    "we are a law firm", "Shopify store setup, logo design, branding",
    "hum log ghar ka interior aur modular kitchen banate hai pune me",
]

_BAD = [
    re.compile(r"\ba (?=[aeiou])(?!(?:ui|ux|uk|us|user|unique|university|one|eu))", re.I),  # "a interior"
    re.compile(r"\ban (?=[bcdfgjkpqtvwyz])(?!(?:seo|sem|smm|sms|hr|mba|mvp|fmcg|sql))", re.I),
    re.compile(r"\bagency agency\b", re.I),
    re.compile(r"\ba a\b|\ban an\b|\bthe the\b", re.I),
    re.compile(r"\bi am a\b.*\b(for|with)\b.*\bi am\b", re.I),
    re.compile(r"\bhelp with an? \w+(er|or|ist|ant|yer)\b", re.I),  # "help with a plumber"
    re.compile(r"\ban? (interior design|web design|video editing|plumbing|bookkeeping)\b(?! (agency|firm|studio))", re.I),
]


@pytest.mark.parametrize("service", SERVICES)
@pytest.mark.parametrize("lead_type", [LeadType.NEED_FREELANCER, LeadType.NEED_AGENCY])
def test_any_service_builds_clean_queries(service, lead_type):
    plan = build_plan(service, lead_type, "packed")
    assert plan.base, "round 0 must always have queries"
    queries = list(plan.base) + list(plan.pool)
    phrases = [p for q in queries for p in query_phrases(q)]
    assert phrases
    for q in queries:
        assert len(q.split()) + 1 <= 32, q  # + site:linkedin.com/posts
    for p in phrases:
        for bad in _BAD:
            assert not bad.search(p), f"{service!r}/{lead_type.value}: bad phrasing {p!r} ({bad.pattern})"
    # The user's pitch words never leak into the search phrases. (A sentence-
    # long / non-English input is templated from the LLM's canonical service
    # in the engine instead - see test_messy_input_templates_use_canonical_service.)
    if not is_messy_service(service):
        for leak in ("i am a freelance", "we offer", "need clients"):
            assert not any(leak in p.lower() for p in phrases), (service, leak)


@pytest.mark.parametrize("service,noun", [
    ("CA", "chartered accountant"), ("lawyer", "lawyer"), ("interior design", "interior designer"),
    ("plumbing", "plumber"), ("SEO", "seo specialist"), ("bookkeeping", "bookkeeper"),
])
def test_freelancer_mode_asks_for_the_person(service, noun):
    base = [p.lower() for q in build_plan(service, LeadType.NEED_FREELANCER).base for p in query_phrases(q)]
    assert any(noun in p for p in base), base


@pytest.mark.parametrize("service,org", [
    ("lawyer", "law firm"), ("we are a law firm", "law firm"), ("CA", "ca firm"),
    ("SEO", "seo agency"), ("video editing", "video editing agency"), ("architecture", "architecture firm"),
])
def test_agency_mode_asks_for_the_organisation(service, org):
    base = [p.lower() for q in build_plan(service, LeadType.NEED_AGENCY).base for p in query_phrases(q)]
    assert any(org in p for p in base), base


def test_primary_service_never_empty_for_real_text():
    for s in SERVICES:
        assert primary_service(s).strip(), s


def test_messy_input_templates_use_canonical_service():
    """Every round of a messy-input search is built from the LLM's canonical
    service name - never from the raw sentence."""
    from db import MemoryStore
    from discovery.base import SearchBatchResult
    from engine import run_search
    from llm_queries import Expansion

    raw = "hum log ghar ka interior aur modular kitchen banate hai pune me"
    assert is_messy_service(raw)
    seen: list[str] = []

    class Disc:
        calls = 0

        def search_posts(self, queries, since, **_kw):
            Disc.calls += 1
            seen.extend(queries)
            return SearchBatchResult(posts=[], queries_used=list(queries))

    class Clf:
        calls = 0

        def classify_batch(self, candidates, **kw):
            return [None for _ in candidates]

    from config import Settings

    store = MemoryStore()
    sid = store.create_search(service=raw, country="", lead_type="need_freelancer",
                              time_window="7d", leads_needed=3)["id"]
    run_search(sid, store=store, discovery=Disc(), classifier=Clf(),
               query_expander=lambda s, avoid=None: Expansion(
                   ["need an interior designer for our flat"], canonical_services=["interior design"]),
               settings=Settings(freshness_ladder="", engine_prefetch=False, engine_max_iterations=6,
                                 engine_early_stop_empty_rounds=50, max_query_refills=0))
    phrases = [p.lower() for q in seen for p in query_phrases(q)]
    assert phrases and not any("hum log" in p or "banate" in p for p in phrases)
    assert any("interior designer" in p for p in phrases)
