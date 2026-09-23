"""Central settings. All values come from environment variables (.env supported)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:  # pragma: no cover - dotenv is optional at import time
    pass


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    try:
        return float(raw) if raw not in (None, "") else default
    except ValueError:
        return default


def _str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Settings:
    # Classification LLM — DeepSeek by default (provider: deepseek | openai).
    llm_provider: str = field(default_factory=lambda: _str("LLM_PROVIDER", "deepseek").lower())
    deepseek_api_key: str = field(default_factory=lambda: _str("DEEPSEEK_API_KEY"))
    deepseek_base_url: str = field(default_factory=lambda: _str("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    deepseek_model: str = field(default_factory=lambda: _str("DEEPSEEK_MODEL", "deepseek-chat"))
    llm_timeout_seconds: float = field(default_factory=lambda: _float("LLM_TIMEOUT_SECONDS", 60.0))
    llm_max_retries: int = field(default_factory=lambda: _int("LLM_MAX_RETRIES", 2))
    # Optional legacy OpenAI path (only used when LLM_PROVIDER=openai).
    openai_api_key: str = field(default_factory=lambda: _str("OPENAI_API_KEY"))
    openai_model: str = field(default_factory=lambda: _str("OPENAI_MODEL", "gpt-4o"))

    # Database
    supabase_url: str = field(default_factory=lambda: _str("SUPABASE_URL"))
    supabase_service_role_key: str = field(default_factory=lambda: _str("SUPABASE_SERVICE_ROLE_KEY"))

    # Discovery — Google SERP API (Serper.dev-style wrapper over Google search)
    discovery_provider: str = field(default_factory=lambda: _str("DISCOVERY_PROVIDER", "auto").lower())
    mock_mode: bool = field(default_factory=lambda: _str("MOCK_MODE", "0") in {"1", "true", "yes"})

    serper_api_key: str = field(default_factory=lambda: _str("SERPER_API_KEY"))
    serper_base_url: str = field(default_factory=lambda: _str("SERPER_BASE_URL", "https://google.serper.dev"))
    # Restriction appended to every query, e.g. "linkedin.com/posts".
    serper_site_restriction: str = field(default_factory=lambda: _str("SERPER_SITE_RESTRICTION", "linkedin.com/posts"))
    # Results per query. NOTE: Serper's FREE tier caps `num` at 10 and rejects
    # larger values with HTTP 400 — keep at 10 unless you are on a paid plan.
    serper_results_per_query: int = field(default_factory=lambda: _int("SERPER_RESULTS_PER_QUERY", 10))
    # Pages of results to request per query. Google only returns ~10 posts per
    # page, so paging surfaces more candidates (recall lever), but EVERY page is
    # a separate paid Serper call — default 3 to hit exact lead counts; the
    # per-search ceiling bounds the spend on zero-yield niches.
    serper_pages_per_query: int = field(default_factory=lambda: max(1, min(_int("SERPER_PAGES_PER_QUERY", 3), 5)))
    serper_gl: str = field(default_factory=lambda: _str("SERPER_GL", ""))   # optional Google country ('us', 'in', ...)
    serper_hl: str = field(default_factory=lambda: _str("SERPER_HL", "en"))  # optional Google language
    serper_timeout_seconds: float = field(default_factory=lambda: _float("SERPER_TIMEOUT_SECONDS", 30.0))
    # Date filter: "tbs" = Google's native time filter param (qdr:d / qdr:dN /
    # qdr:w); "after" = legacy in-query `after:YYYY-MM-DD` operator.
    serper_date_mode: str = field(default_factory=lambda: _str("SERPER_DATE_MODE", "tbs").lower())

    # Usage budget
    max_searches_per_day: int = field(default_factory=lambda: _int("MAX_SEARCHES_PER_DAY", 20))

    # Scoring gates
    min_overall_score: float = field(default_factory=lambda: _float("MIN_OVERALL_SCORE", 60.0))
    min_service_match: float = field(default_factory=lambda: _float("MIN_SERVICE_MATCH", 50.0))
    min_intent_strength: str = field(default_factory=lambda: _str("MIN_INTENT_STRENGTH", "recommendation"))

    # Engine loop — the exact-count loop keeps running until N qualified leads
    # are found or discovery is genuinely exhausted; 30 iterations of fresh
    # query diversity is the budget before giving up (never padding).
    engine_max_iterations: int = field(default_factory=lambda: _int("ENGINE_MAX_ITERATIONS", 30))
    engine_deadline_seconds: int = field(default_factory=lambda: _int("ENGINE_DEADLINE_SECONDS", 1800))
    engine_early_stop_empty_rounds: int = field(default_factory=lambda: _int("ENGINE_EARLY_STOP_EMPTY_ROUNDS", 3))
    classifier_concurrency: int = field(default_factory=lambda: _int("CLASSIFIER_CONCURRENCY", 8))
    # Independent hard ceilings per search (regardless of iteration/deadline/
    # empty-round logic) — the safety net for pathological niches.
    max_serper_requests_per_search: int = field(
        default_factory=lambda: _int("MAX_SERPER_REQUESTS_PER_SEARCH", 60))
    max_deepseek_calls_per_search: int = field(
        default_factory=lambda: _int("MAX_DEEPSEEK_CALLS_PER_SEARCH", 150))

    # EXACT-N scaling: ceilings/deadline grow with the leads requested -
    # effective = max(base, per_lead * N), capped by the hard maximum. 0 per
    # lead = no scaling (the base values above apply to every request size).
    serper_requests_per_lead: int = field(default_factory=lambda: _int("SERPER_REQUESTS_PER_LEAD", 0))
    deepseek_calls_per_lead: int = field(default_factory=lambda: _int("DEEPSEEK_CALLS_PER_LEAD", 0))
    max_serper_requests_hard: int = field(default_factory=lambda: _int("MAX_SERPER_REQUESTS_HARD", 0))
    max_deepseek_calls_hard: int = field(default_factory=lambda: _int("MAX_DEEPSEEK_CALLS_HARD", 0))
    engine_deadline_seconds_per_lead: int = field(
        default_factory=lambda: _int("ENGINE_DEADLINE_SECONDS_PER_LEAD", 0))
    engine_deadline_hard_seconds: int = field(default_factory=lambda: _int("ENGINE_DEADLINE_HARD_SECONDS", 0))
    # When the query pool runs dry while still short of N: this many LLM
    # refills (fresh, different phrasings) before the broad legacy fallback.
    max_query_refills: int = field(default_factory=lambda: _int("MAX_QUERY_REFILLS", 2))

    # Query emission style: "packed" (quoted exact phrasings OR-grouped - more
    # precise AND ~3x phrasings per Serper call) or "legacy" (one unquoted
    # phrasing per query). Kill switch for A/B runs.
    query_style: str = field(default_factory=lambda: _str("QUERY_STYLE", "packed").lower())
    # Freshness ladder (newest first): per-iteration discovery windows, e.g.
    # "3d" = round 0 searches the last 3 days first (Google lags LinkedIn by
    # 1-3 days, so 24h alone finds little), then the SAME queries re-run over
    # the full window. Each step is clamped to the search's own
    # window, so the hard freshness cutoff never widens. Empty = full window
    # from round 0. Narrowed rounds never count toward the early-stop streak.
    freshness_ladder: str = field(default_factory=lambda: _str("FRESHNESS_LADDER", "3d"))
    # Snippet-first full-text enrichment: borderline / cut-off snippets get
    # their public post page fetched and are re-classified with the full text.
    fulltext_enrich: bool = field(
        default_factory=lambda: _str("FULLTEXT_ENRICH", "1") in {"1", "true", "yes"})
    max_enrich_per_search: int = field(default_factory=lambda: _int("MAX_ENRICH_PER_SEARCH", 20))
    enrich_concurrency: int = field(default_factory=lambda: _int("ENRICH_CONCURRENCY", 4))
    # Pipeline the next discovery round while the current one is classified.
    engine_prefetch: bool = field(
        default_factory=lambda: _str("ENGINE_PREFETCH", "1") in {"1", "true", "yes"})

    # Buyer-sibling acceptance: when ON, a need_freelancer search also accepts
    # hiring_buyer posts (both are genuine service buyers) and vice-versa.
    # Off by default so strict single-type behavior is preserved in tests.
    accept_sibling_buyers: bool = field(
        default_factory=lambda: _str("ACCEPT_SIBLING_BUYERS", "0") in {"1", "true", "yes"})

    # Volume mode: when OFF the classifier's strict is_qualified verdict is not
    # a hard gate — posts that pass buying-not-selling + service + intent gates
    # are kept even when the model hedged. Default ON (strict) for tests.
    require_model_qualified: bool = field(
        default_factory=lambda: _str("REQUIRE_MODEL_QUALIFIED", "1") not in {"0", "false", "no"})

    # Strict country: hard-reject snippets that explicitly name a country/city
    # different from the requested one (e.g. "agency in Kenya" for a US search).
    strict_country: bool = field(
        default_factory=lambda: _str("STRICT_COUNTRY", "0") in {"1", "true", "yes"})

    # Comment-count ceiling (§6/§10): when a discovery provider reports
    # num_comments (Apify actors do), a post KNOWN to exceed this many comments
    # is dropped before AI spend — heavily-contested posts already have other
    # providers pitching in them. 0/None => ceiling disabled (unknown-count
    # posts are never dropped by this rule).
    max_comments_allowed: int | None = field(
        default_factory=lambda: None if _int("MAX_COMMENTS_ALLOWED", 0) <= 0 else _int("MAX_COMMENTS_ALLOWED", 0))

    @property
    def storage_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "deepseek":
            return bool(self.deepseek_api_key)
        if self.llm_provider == "openai":
            return bool(self.openai_api_key)
        return False

    @property
    def llm_key_env(self) -> str:
        """Name of the env var that must hold the key for the active provider."""
        return "DEEPSEEK_API_KEY" if self.llm_provider == "deepseek" else "OPENAI_API_KEY"

    @property
    def serp_configured(self) -> bool:
        return bool(self.serper_api_key)


settings = Settings()
