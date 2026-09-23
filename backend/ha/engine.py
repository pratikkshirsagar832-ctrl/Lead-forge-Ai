"""Iterative exact-count engine (§9).

Deliver exactly N qualified leads, or run out of provider results trying -
never pad the count with weak matches. Sequence per iteration:
queries -> discovery -> canonical dedupe -> deterministic prefilter -> DeepSeek
classification (concurrent, fail-closed) -> [full-text enrichment of borderline
snippets] -> scoring gates -> accept.
If short of N, diversify the query set and repeat (iteration + deadline caps,
early stop after consecutive zero-yield rounds), then slice to exactly N.

Parallelism: the LLM query expansion runs alongside round 0's discovery, and
the NEXT round's discovery is prefetched while the current round is being
classified, so Serper and DeepSeek work overlap instead of taking turns.

Freshness (newest first): early rounds search a narrower recent window
(FRESHNESS_LADDER, e.g. last 24h, then last 3 days) before the full window, so
the newest buyers are found first; every post's exact publish time is decoded
from its URL's activity id, and results are delivered newest first.

SERP semantics (§0): with Google-over-LinkedIn discovery, an empty result set
for a tight query is EXPECTED provider behavior (partial crawl, 1-3 day lag),
NOT a failure. Zero-hit searches therefore complete with a shortage and an
explanatory message; only genuine provider errors (network, API rejection)
mark the search failed.
"""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from config import Settings
from discovery.base import (
    DiscoveryClient,
    DiscoveryConfigError,
    DiscoveryError,
    canonical_post_url,
    posted_at_from_url,
)
from geography import canonical_label
from models import TimeWindow
from prefilter import prefilter
from query_builder import (
    emit_queries,
    is_messy_service,
    next_queries,
    query_phrases,
    query_style,
    seed_phrases,
    service_phrases,
)
from liveness import is_filled
from scoring import ScoreConfig, compute_score

log = logging.getLogger(__name__)

ProgressFn = Callable[[str, int, int, int, str], None]
FullTextFn = Callable[[str], "str | None"]
# url -> object with .status ("alive" | "dead" | "unknown") and .text (liveness.PostCheck)
PostCheckFn = Callable[[str], Any]

CRAWL_LAG_NOTE = (
    "Google's coverage of LinkedIn posts is partial and typically lags 1-3 days, "
    "so tight queries and short windows often return little - this is expected, not a failure."
)

# How long round 1 waits for the (parallel) LLM query expansion before it
# falls back to the deterministic pool.
_EXPANSION_WAIT_S = 30.0
# Snippet verdicts at/above this overall score (that failed a gate) are worth
# a full-text re-check; below it even a full post rarely flips the verdict.
_ENRICH_MIN_OVERALL = 45.0
_LADDER_STEP = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([hdw])\s*$", re.IGNORECASE)


@dataclass(slots=True)
class EngineSummary:
    search_id: str
    status: str  # completed | failed
    found: int
    accepted: int
    scanned: int
    iterations: int
    detail: str = ""


@dataclass(slots=True)
class EngineResult:
    """Everything the engine learned for one accepted candidate post."""

    post: Any
    classification: Any
    qualified: Any

    @property
    def overall(self) -> float:
        return self.qualified.overall


def _noop_progress(stage: str, found: int, accepted: int, scanned: int, message: str = "") -> None:  # pragma: no cover
    pass


def parse_freshness_ladder(raw: str | None) -> list[timedelta]:
    """"1d,3d" -> [1 day, 3 days]. Invalid steps are ignored (never raises)."""
    out: list[timedelta] = []
    for part in (raw or "").split(","):
        m = _LADDER_STEP.match(part)
        if not m:
            continue
        n = float(m.group(1))
        unit = m.group(2).lower()
        hours = n * {"h": 1, "d": 24, "w": 168}[unit]
        if hours > 0:
            out.append(timedelta(hours=hours))
    return out


def run_search(
    search_id: str,
    *,
    store,
    discovery: DiscoveryClient,
    classifier,
    settings: Settings,
    progress: ProgressFn | None = None,
    should_stop: Callable[[], bool] | None = None,
    content_filter: Callable[[str], bool] | None = None,
    query_expander: Callable[[str], list[str]] | None = None,
    full_text_fetcher: FullTextFn | None = None,
    post_checker: PostCheckFn | None = None,
) -> EngineSummary:
    """Synchronous orchestrator. Runs inside a background task/thread.

    `content_filter` (optional) is a cheap text test applied BEFORE any LLM
    call: return False to drop a candidate whose text clearly contradicts the
    requested content direction (e.g. an advice/seller post that merely
    contains the keywords). Dropping here saves the DeepSeek call AND keeps the
    engine's exact-count loop honest - it only counts posts that survive the
    content gate, so it keeps scanning until it genuinely finds N matching
    leads instead of stopping early on posts it later discards at save time.

    `full_text_fetcher` (optional) maps a post URL to its full text (or None).
    When wired, borderline snippet verdicts are re-classified on the full post
    (bounded by settings.max_enrich_per_search and the DeepSeek ceiling).
    """
    # Side workers: the parallel query expansion + the prefetched discovery
    # round. Never waited on at exit (a cancelled/finished search must not
    # hang on an in-flight HTTP call).
    side_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix=f"ha-{search_id[:6]}")
    try:
        return _run_search(
            search_id, store=store, discovery=discovery, classifier=classifier,
            settings=settings, progress=progress or _noop_progress, should_stop=should_stop,
            content_filter=content_filter, query_expander=query_expander,
            full_text_fetcher=full_text_fetcher, post_checker=post_checker, side_pool=side_pool,
        )
    finally:
        side_pool.shutdown(wait=False, cancel_futures=True)


def _run_search(
    search_id: str,
    *,
    store,
    discovery: DiscoveryClient,
    classifier,
    settings: Settings,
    progress: ProgressFn,
    should_stop: Callable[[], bool] | None,
    content_filter: Callable[[str], bool] | None,
    query_expander: Callable[[str], list[str]] | None,
    full_text_fetcher: FullTextFn | None,
    post_checker: PostCheckFn | None,
    side_pool: ThreadPoolExecutor,
) -> EngineSummary:
    row = store.get_search(search_id)
    if row is None:
        raise KeyError(f"search {search_id} not found")

    service = row["service"]
    country_raw = row.get("country") or ""  # canonical code when recognized, else raw text
    # Human-friendly label (canonical country name, else the raw free text) -
    # used for classifier context and location scoring, never for hard rejects.
    country = canonical_label(country_raw)
    lead_type = row["lead_type"]
    # Volume/sibling mode: every genuine buyer bucket is accepted regardless of
    # the requested phrasing, so a need_freelancer search never throws away an
    # agency-sourcing post (and vice-versa). Off => strict single-type behavior
    # (tests).
    accepted_types: set[str] = {lead_type}
    if settings.accept_sibling_buyers:
        accepted_types.update({"need_freelancer", "our_agency"})
    time_window = row["time_window"]
    leads_needed = int(row["leads_needed"])

    # §3: freshness recomputed fresh from *now* on every request/run.
    try:
        cutoff = TimeWindow(time_window).cutoff()
    except ValueError:
        cutoff = TimeWindow.DAYS_7.cutoff()
        time_window = TimeWindow.DAYS_7.value
        log.warning("Unknown time_window %r; defaulted to 7d", row["time_window"])

    cfg = ScoreConfig(
        min_overall=settings.min_overall_score,
        min_service_match=settings.min_service_match,
        min_intent_strength=settings.min_intent_strength,
        require_model_qualified=settings.require_model_qualified,
        strict_country=settings.strict_country,
    )

    store.update_search(search_id, status="running")
    progress("running", 0, 0, 0, f"window: last posts since {cutoff.date().isoformat()}")

    # LLM query expansion (optional, fail-closed) runs IN PARALLEL with round
    # 0: round 0 uses the template base set, the expansion's niche phrasings
    # lead the pool from round 1, and its service vocabulary (role nouns,
    # synonyms, adjacent-but-different crafts) feeds the classifier. Any
    # failure silently keeps the deterministic templates.
    expander_future: Future | None = None
    if query_expander is not None:
        expander_future = side_pool.submit(query_expander, service)
    expansion_box: dict[str, Any] = {}

    def _expansion(wait: float) -> list[str]:
        if "value" in expansion_box:
            return expansion_box["value"]
        if expander_future is None:
            expansion_box["value"] = []
            return expansion_box["value"]
        try:
            res = expander_future.result(timeout=wait)
        except FuturesTimeout:
            return []  # not ready yet - do not cache, a later round may use it
        except Exception:  # noqa: BLE001 - expansion must never kill a search
            log.debug("query_expander raised (ignored)", exc_info=True)
            res = []
        expansion_box["value"] = res if res is not None else []
        return expansion_box["value"]

    def _service_context() -> dict[str, list[str]] | None:
        exp = _expansion(0.0)
        ctx = {k: list(getattr(exp, k, None) or []) for k in ("role_nouns", "synonyms", "not_this_service")}
        return ctx if any(ctx.values()) else None

    ladder = parse_freshness_ladder(getattr(settings, "freshness_ladder", ""))

    def _round_since(iteration: int) -> tuple[datetime, bool]:
        """(discovery `since`, narrowed?) - newest-first freshness ladder,
        always clamped INSIDE the search window (never widens the cutoff)."""
        if iteration < len(ladder):
            since = max(cutoff, datetime.now(UTC) - ladder[iteration])
            return since, since > cutoff
        return cutoff, False

    used_queries: set[str] = set()
    seen_urls: set[str] = set()
    raw_found = 0
    scanned = 0
    classify_failed = 0
    pref_dropped = 0
    dup_existing = 0
    type_mismatch = 0
    dir_dropped = 0  # content-direction gate drops (cheap, zero LLM spend)
    undated_dropped = 0  # STRICT freshness: no verifiable post date -> no lead
    stale_dropped = 0  # STRICT freshness: dated older than the window -> no lead
    enriched = 0  # posts re-classified on their full text
    enrich_flipped = 0  # ... of which the full text turned into an accepted lead
    dead_dropped = 0  # accepted, but the post was deleted/removed on LinkedIn
    filled_dropped = 0  # accepted, but the post says the need is already filled
    liveness_unknown = 0  # liveness could not be confirmed (throttle) - kept
    reject_reasons: dict[str, int] = {}
    errors: list[str] = []
    accepted: list[EngineResult] = []  # NEW leads only (not already in the DB)
    # EXACT-N budget: spend ceilings and the deadline scale with the number
    # of leads requested (small requests keep the base budget), bounded by
    # hard maxima - a 50-lead search needs far more scanning than a 5-lead one.
    def _scaled(base: int, per_lead: int, hard: int) -> int:
        if not base or base <= 0:
            return 0  # ceiling disabled stays disabled
        value = max(base, per_lead * leads_needed) if per_lead > 0 else base
        return min(value, hard) if hard and hard > 0 else value

    deadline_s = _scaled(settings.engine_deadline_seconds, settings.engine_deadline_seconds_per_lead,
                         settings.engine_deadline_hard_seconds)
    deadline = time.monotonic() + deadline_s
    deadline_hit = False
    zero_yield_rounds = 0
    iterations = 0
    detail = ""
    # Tier-0 observability: per-search call counters + stop reason.
    serp_base = int(getattr(discovery, "calls", 0) or 0)
    llm_base = int(getattr(classifier, "calls", 0) or 0)
    stop_reason = "target_reached"
    reject_rows: list[dict[str, Any]] = []
    max_iterations = max(1, settings.engine_max_iterations)
    serp_cap = _scaled(settings.max_serper_requests_per_search or 0,
                       settings.serper_requests_per_lead, settings.max_serper_requests_hard)
    llm_cap = _scaled(settings.max_deepseek_calls_per_search or 0,
                      settings.deepseek_calls_per_lead, settings.max_deepseek_calls_hard)
    # Prior accept-rate used to decide whether the next round is needed; replaced
    # by the observed rate once posts have been scanned.
    est_yield = 0.15
    pending: Future | None = None
    pending_iter = -1

    def _call_counts() -> tuple[int, int]:
        s = int(getattr(discovery, "calls", 0) or 0) - serp_base
        d = int(getattr(classifier, "calls", 0) or 0) - llm_base
        return max(0, s), max(0, d)

    def _persist_stats(reason: str | None = None) -> None:
        """Best-effort write of stat columns; ha_searches may not have them
        migrated yet, so a failure must never crash the search."""
        try:
            s, d = _call_counts()
            payload: dict[str, Any] = {"serper_requests_used": s, "deepseek_calls_used": d}
            if reason:
                payload["stop_reason"] = reason
            store.update_search(search_id, **payload)
        except Exception:  # noqa: BLE001
            log.debug("ha_searches stat columns not present yet (ignored)", exc_info=True)

    def _record_reject(post, classification, *, reason: str, verdict_type: str | None = None) -> None:
        reject_rows.append({
            "search_id": search_id,
            "post_url": (post.post_url or "")[:400],
            "post_text": (post.text or "").replace("�", "")[:500],
            "lead_type_verdict": verdict_type,
            "reason": (reason or "").replace("�", "")[:500],
            "evidence": (getattr(classification, "evidence", None) or "").replace("�", "")[:300],
            "accepted": False,
            "is_qualified": bool(getattr(classification, "is_qualified", False)),
        })

    def _note_reject(qualified) -> None:
        for name, ok in qualified.gates.items():
            if not ok:
                reject_reasons[name] = reject_reasons.get(name, 0) + 1

    # ANY-INPUT support: the user may type a sentence, a pitch, a list of
    # services, typos or another language. Secondary services seed the pool
    # right away; the LLM's canonical service names + role nouns seed it once
    # the (parallel) expansion lands. A messy input (template queries would
    # be noise) makes round 0 wait for that canonical reading instead.
    secondary_seeds: list[str] = []
    for extra_service in service_phrases(service)[1:]:
        secondary_seeds += seed_phrases(extra_service, lead_type, 6)
    messy_input = is_messy_service(service)
    plan_state: dict[str, Any] = {"style": getattr(settings, "query_style", None),
                                  "offset": 0, "refills": 0}
    refill_queue: list[str] = []

    def _extra_phrases(wait: float) -> list[str]:
        exp = _expansion(wait)
        phrases: list[str] = list(exp)
        for canon in (getattr(exp, "canonical_services", None) or [])[:3]:
            phrases += seed_phrases(canon, lead_type, 8)
        for role in (getattr(exp, "role_nouns", None) or [])[:2]:
            phrases += seed_phrases(role, lead_type, 4)
        phrases += secondary_seeds
        seen: set[str] = set()
        out: list[str] = []
        for p in phrases:
            key = p.strip().lower()
            if key and key not in seen:
                seen.add(key)
                out.append(p)
        return out

    def _template_service() -> str:
        """Service text the deterministic templates are built from. A messy
        input (a sentence, a pitch, another language) uses the LLM's canonical
        service name once known - templates built from the raw sentence would
        only burn Serper calls on phrases nobody writes."""
        if messy_input:
            exp = _expansion(_EXPANSION_WAIT_S)
            canon = [c for c in (getattr(exp, "canonical_services", None) or []) if c.strip()]
            if canon:
                return canon[0]
        return service

    def _refill() -> list[str]:
        """Pool ran dry while still short of N: ask the expander for a fresh,
        DIFFERENT batch of phrasings (never repeats what was searched)."""
        tried = [p for q in used_queries for p in query_phrases(q)]
        tried_keys = {t.lower() for t in tried}
        try:
            res = query_expander(service, avoid=tried)  # type: ignore[misc]
        except TypeError:
            return []  # an expander without refill support
        except Exception:  # noqa: BLE001 - refill is best-effort
            log.debug("query refill failed (ignored)", exc_info=True)
            return []
        return [p for p in (res or []) if p.strip().lower() not in tried_keys]

    def _bias(queries: list[str], iteration: int) -> list[str]:
        # Country bias: on the first wave (and whenever a country is known and
        # not a huge multi-country region), scope every query with the country
        # name so Google returns posts authored in that country, not the
        # country that happens to rank globally. Later waves broaden.
        if queries and iteration == 0 and country:
            cn = country.lower()
            if cn not in ("", "worldwide", "global", "europe", "asia", "middle east", "gulf"):
                queries = [f"{q} {country}" for q in queries]
        return queries

    def _plan(iteration: int) -> list[str]:
        """Next round's queries. Recall ladder when the pool runs dry (so a
        search short of N keeps finding NEW posts instead of stopping):
        templates + expansion -> LLM refills (fresh angles) -> broad legacy
        unquoted phrasings -> exhausted."""
        if iteration - plan_state["offset"] == 0 and messy_input:
            lead = [q for q in emit_queries(_extra_phrases(_EXPANSION_WAIT_S), plan_state["style"])
                    if q not in used_queries][:4]
            if lead:
                return _bias(lead, iteration)
        while True:
            if refill_queue:
                take = [q for q in refill_queue[:8] if q not in used_queries]
                del refill_queue[:8]
                if take:
                    return _bias(take, iteration)
                continue
            extra = _extra_phrases(_EXPANSION_WAIT_S) if iteration >= 1 else []
            rel = iteration - plan_state["offset"]
            queries = [q for q in next_queries(_template_service(), lead_type, rel, extra_pool=extra,
                                               style=plan_state["style"])
                       if q not in used_queries]
            if queries:
                return _bias(queries, iteration)
            if query_expander is not None and plan_state["refills"] < settings.max_query_refills:
                plan_state["refills"] += 1
                fresh = _refill()
                if fresh:
                    log.info("Search %s: query pool dry - refilled %d fresh phrasings", search_id, len(fresh))
                    refill_queue.extend(emit_queries(fresh, plan_state["style"]))
                    continue
            if query_style(plan_state["style"]) != "legacy":
                # Last resort: broad unquoted phrasings (bag-of-words recall).
                plan_state["style"] = "legacy"
                plan_state["offset"] = iteration
                continue
            return []

    def _discover(iteration: int):
        queries = _plan(iteration)
        if not queries:
            return queries, None
        since, _narrowed = _round_since(iteration)
        return queries, discovery.search_posts(queries, since)

    def _classify(posts: list[Any]) -> list[Any]:
        kwargs: dict[str, Any] = dict(
            service=service,
            lead_type=lead_type,
            country=country,
            max_concurrency=settings.classifier_concurrency,
            accepted_types=accepted_types if len(accepted_types) > 1 else None,
        )
        ctx = _service_context()
        if ctx:
            kwargs["service_context"] = ctx
        return classifier.classify_batch(posts, **kwargs)

    def _judge(post, classification):
        """-> (kind, qualified): kind in none | type | score | accept."""
        if classification is None:
            return "none", None
        if classification.lead_type not in accepted_types:
            return "type", None
        qualified = compute_score(
            classification,
            requested_country=country,
            requested_country_code=country_raw,
            post_text=post.text or "",
            cfg=cfg,
            posted_at=post.posted_at,
        )
        return ("accept" if qualified.keep else "score"), qualified

    def _worth_full_text(post, classification, kind: str, qualified) -> bool:
        """Borderline snippet verdicts that a full post could plausibly flip."""
        if classification is None or kind == "accept":
            return False
        if getattr(post, "text_source", "") == "full_post":
            return False
        if classification.is_selling_offering or classification.is_job_seek:
            return False  # direction already clear - more text will not help
        if getattr(classification, "needs_full_text", False):
            return True
        if kind != "score" or qualified is None:
            return False
        return bool(qualified.gates.get("service_match_ok")) and qualified.overall >= _ENRICH_MIN_OVERALL

    def _fail(exc: Exception) -> EngineSummary:
        errors.append(str(exc))
        log.error("Discovery error (search %s): %s", search_id, exc)
        store.update_search(search_id, status="failed", error=str(exc), finished_at=datetime.now(UTC))
        progress("failed", raw_found, len(accepted), scanned, str(exc))
        return _summary(search_id, "failed", raw_found, len(accepted), scanned, iterations, str(exc))

    for iteration in range(max_iterations):
        iterations = iteration + 1
        if time.monotonic() > deadline:
            deadline_hit = True
            stop_reason = "deadline_hit"
            break
        # Independent spend ceilings (Tier 1.2) - enforced regardless of the
        # iteration/deadline/empty-round logic. 0/None disables a ceiling.
        s_now, d_now = _call_counts()
        if (serp_cap > 0 and s_now >= serp_cap) or (llm_cap > 0 and d_now >= llm_cap):
            detail = f"provider-spend ceiling reached (serper {s_now}/{serp_cap}, deepseek {d_now}/{llm_cap})"
            stop_reason = "ceiling_hit"
            break
        # Cooperative cancel - lets a user cancel stop provider spend promptly.
        if should_stop is not None:
            try:
                if should_stop():
                    log.info("Search %s cancelled by user (iteration %d)", search_id, iteration + 1)
                    store.update_search(
                        search_id, status="cancelled", error=None,
                        found_count=raw_found, accepted_count=len(accepted),
                        scanned_count=scanned, finished_at=datetime.now(UTC),
                    )
                    return _summary(search_id, "cancelled", raw_found, len(accepted), scanned,
                                    iterations, "cancelled by user")
            except Exception:  # never let the cancel probe kill a search
                log.debug("Cancel probe failed for %s (ignored)", search_id)

        _since, narrowed = _round_since(iteration)
        try:
            if pending is not None and pending_iter == iteration:
                # Prefetched while the previous round was being classified.
                job, pending = pending, None
                queries, batch = job.result()
            else:
                queries = _plan(iteration)
                batch = discovery.search_posts(queries, _since) if queries else None
        except DiscoveryConfigError as exc:
            return _fail(exc)
        except DiscoveryError as exc:
            # A genuine provider failure (network/API rejection) is loud; an
            # EMPTY result set is handled below as an ordinary shortage.
            return _fail(exc)
        if not queries or batch is None:
            detail = "query pool exhausted"
            stop_reason = "query_pool_exhausted"
            break
        if narrowed:
            # A newest-only round never uses up its queries: the SAME (best)
            # queries re-run next round over the full window. Google indexes
            # LinkedIn with a 1-3 day lag, so a narrow round alone finds little
            # and must never cost the search its strongest phrasings.
            plan_state["offset"] += 1
        else:
            used_queries.update(queries)
        progress("running", raw_found, len(accepted), scanned,
                 f"iteration {iteration + 1}: {len(queries)} queries"
                 + (" (newest posts first)" if narrowed else ""))

        raw_found += len(batch.posts)
        # Pass 1: intra-search URL dedupe only - no prefilter/gate/LLM spend.
        round_unique: list[Any] = []
        for post in batch.posts:
            if not post.post_url:
                continue  # a lead without a post URL has no identity - never accept it
            key = canonical_post_url(post.post_url)
            if not key or key in seen_urls:
                continue
            seen_urls.add(key)
            round_unique.append(post)
        # Pass 2 (Tier 1.1): cross-search ownership dedupe BEFORE the content
        # gate and DeepSeek. A post already saved by an earlier search is
        # skipped here (one cheap indexed lookup per round) instead of being
        # fully classified first - previously it reached DeepSeek before being
        # skipped (audit §6: dup_owned reached 11 in one run).
        owned: set[str] = set()
        if round_unique:
            try:
                owned = store.find_existing_post_urls(p.post_url for p in round_unique) or set()
            except Exception:  # noqa: BLE001 - ownership lookup must never kill a round
                log.debug("find_existing_post_urls failed (assuming all new)", exc_info=True)
        candidates = []
        for post in round_unique:
            # Exact publish time from the permalink's activity id when the
            # provider supplied no date (recovers posts that used to be
            # dropped as undated).
            if post.posted_at is None:
                post.posted_at = posted_at_from_url(post.post_url)
            # STRICT FRESHNESS (fail-closed, zero-cost): the product promise is
            # "latest posts only" - a post with NO verifiable date or dated
            # older than the window can never be delivered. Dropped BEFORE the
            # ownership lookup / prefilter / any LLM spend.
            if post.posted_at is None:
                undated_dropped += 1
                continue
            if post.posted_at < cutoff:
                stale_dropped += 1
                continue
            if post.post_url in owned:
                dup_existing += 1
                log.info("Skipping already-owned lead (from an earlier search): %s", post.post_url)
                continue
            verdict = prefilter(
                post.text or "",
                max_comments=settings.max_comments_allowed,
                num_comments=post.num_comments,
            )
            if not verdict.keep:
                pref_dropped += 1
                continue
            # CONTENT-DIRECTION GATE (cheap - NO LLM call). When a content_filter
            # is wired (it mirrors the save-time store gate), a post whose text
            # clearly contradicts the requested buyer direction is dropped here.
            # Only posts that survive this gate can ever be accepted, so the
            # exact-count loop never stops early on posts it would later discard
            # at save time - engine "accepted" == rows actually persisted - and
            # no DeepSeek call is spent classifying a guaranteed discard.
            if content_filter is not None:
                try:
                    if not content_filter(post.text or ""):
                        dir_dropped += 1
                        continue
                except Exception:  # noqa: BLE001 - a broken gate must never kill a search
                    log.debug("content_filter raised for a candidate (kept for classifier)", exc_info=True)
            candidates.append(post)

        # PIPELINE: start the NEXT round's discovery now, so Serper works while
        # DeepSeek classifies this round. Only when the next round is actually
        # likely to be needed (spend safety): under both ceilings, this round
        # cannot plausibly reach N on its own, and an empty round would not
        # already trigger the early stop.
        if (getattr(settings, "engine_prefetch", False) and iteration + 1 < max_iterations
                and time.monotonic() < deadline):
            s_now, d_now = _call_counts()
            under_caps = ((serp_cap <= 0 or s_now < serp_cap)
                          and (llm_cap <= 0 or d_now + len(candidates) < llm_cap))
            likely_short = len(accepted) + est_yield * len(candidates) < leads_needed
            stop_if_empty = (zero_yield_rounds + 1 >= settings.engine_early_stop_empty_rounds
                             and iteration > 0 and not narrowed)
            if under_caps and likely_short and not stop_if_empty:
                pending = side_pool.submit(_discover, iteration + 1)
                pending_iter = iteration + 1

        if not candidates:
            if not narrowed:  # a newest-only ladder round never counts as "empty"
                zero_yield_rounds += 1
            if zero_yield_rounds >= settings.engine_early_stop_empty_rounds and iteration > 0:
                detail = f"{zero_yield_rounds} rounds in a row added nothing new; stopped early"
                stop_reason = "empty_rounds_stop"
                break
            continue

        try:
            classifications = list(_classify(candidates))
        except Exception as exc:  # noqa: BLE001 - classifier unavailable == fail-closed
            msg = f"classifier unavailable: {exc}"
            errors.append(msg)
            log.exception("Classifier batch failed (search %s) - fail-closed", search_id)
            store.update_search(search_id, status="failed", error=msg, finished_at=datetime.now(UTC))
            progress("failed", raw_found, len(accepted), scanned, msg)
            return _summary(search_id, "failed", raw_found, len(accepted), scanned, iterations, msg)

        outcomes = [_judge(p, c) for p, c in zip(candidates, classifications)]

        # SNIPPET-FIRST FULL-TEXT ENRICHMENT: borderline verdicts get the public
        # post page fetched and are re-classified on the full text. Bounded by
        # the per-search enrichment budget and the DeepSeek ceiling; any fetch
        # or classify failure keeps the original (snippet) verdict.
        enrich_budget = max(0, settings.max_enrich_per_search - enriched) if full_text_fetcher else 0
        if enrich_budget and llm_cap > 0:
            enrich_budget = min(enrich_budget, max(0, llm_cap - _call_counts()[1]))
        if enrich_budget:
            picks = [i for i, (p, c, (kind, q)) in enumerate(zip(candidates, classifications, outcomes))
                     if _worth_full_text(p, c, kind, q)][:enrich_budget]
            if picks:
                with ThreadPoolExecutor(max_workers=max(1, min(settings.enrich_concurrency, len(picks)))) as ex:
                    texts = list(ex.map(lambda i: _safe_fetch(full_text_fetcher, candidates[i].post_url), picks))
                redo: list[int] = []
                for i, text in zip(picks, texts):
                    post = candidates[i]
                    if not text or len(text) <= len(post.text or "") + 20:
                        continue  # nothing new to read
                    post.text = text
                    post.text_source = "full_post"
                    # The saved lead carries the full text, so it must pass the
                    # same save-time direction gate (exact-count honesty).
                    if content_filter is not None:
                        try:
                            if not content_filter(text):
                                outcomes[i] = ("gate", None)
                                continue
                        except Exception:  # noqa: BLE001
                            log.debug("content_filter raised on full text (kept)", exc_info=True)
                    redo.append(i)
                if redo:
                    try:
                        again = list(_classify([candidates[i] for i in redo]))
                    except Exception:  # noqa: BLE001 - keep snippet verdicts
                        log.debug("Full-text re-classification failed (snippet verdicts kept)", exc_info=True)
                        again = [None] * len(redo)
                    for i, cl in zip(redo, again):
                        enriched += 1
                        if cl is None:
                            continue  # fail-closed: keep the snippet verdict
                        before = outcomes[i][0]
                        classifications[i] = cl
                        outcomes[i] = _judge(candidates[i], cl)
                        if outcomes[i][0] == "accept" and before != "accept":
                            enrich_flipped += 1

        # LIVENESS: Google keeps deleted LinkedIn posts in its index for days,
        # so every would-be lead is checked BEFORE it counts toward N - a dead
        # post is replaced by the exact-N loop instead of reaching the user as
        # "Post not found". Already-filled asks ("CONTRACT NOW AWARDED") are
        # dropped the same way. Uncertain checks (throttle) keep the lead.
        accept_idx = [i for i, (kind, _q) in enumerate(outcomes) if kind == "accept"]
        for i in accept_idx:
            if is_filled(candidates[i].text):
                outcomes[i] = ("filled", None)
        accept_idx = [i for i in accept_idx if outcomes[i][0] == "accept"]
        if post_checker is not None and accept_idx:
            workers = max(1, min(settings.liveness_concurrency, len(accept_idx)))
            with ThreadPoolExecutor(max_workers=workers) as ex:
                checks = list(ex.map(lambda i: _safe_check(post_checker, candidates[i].post_url), accept_idx))
            for i, chk in zip(accept_idx, checks):
                status = getattr(chk, "status", "unknown")
                text = getattr(chk, "text", None)
                post = candidates[i]
                if status == "dead":
                    outcomes[i] = ("dead", None)
                elif status == "alive":
                    if is_filled(text):
                        outcomes[i] = ("filled", None)
                    elif text and len(text) > len(post.text or "") + 20:
                        # The live full post replaces the snippet on the saved
                        # lead - same save-time direction gate applies.
                        if content_filter is not None and not _gate_ok(content_filter, text):
                            outcomes[i] = ("gate", None)
                        else:
                            post.text = text
                            post.text_source = "full_post"
                else:
                    liveness_unknown += 1

        gained = 0
        for post, classification, (kind, qualified) in zip(candidates, classifications, outcomes):
            scanned += 1
            if kind == "none":
                classify_failed += 1  # fail-closed: dropped
                _record_reject(post, None, reason="classifier returned no verdict / parse failed")
            elif kind == "dead":
                dead_dropped += 1
                _record_reject(post, classification, verdict_type=classification.lead_type,
                               reason="post deleted/removed on LinkedIn")
            elif kind == "filled":
                filled_dropped += 1
                _record_reject(post, classification, verdict_type=classification.lead_type,
                               reason="need already filled (post says hired/awarded/closed)")
            elif kind == "gate":
                dir_dropped += 1
                _record_reject(post, classification, verdict_type=getattr(classification, "lead_type", None),
                               reason="full post text contradicts the requested lead direction")
            elif kind == "type" and classification.lead_type == "irrelevant":
                # Not a buyer at all (seller, job ad, advice...) - a plain
                # rejection, NOT a "different lead type" genuine buyer.
                reject_reasons["not_a_buyer"] = reject_reasons.get("not_a_buyer", 0) + 1
                _record_reject(post, classification, verdict_type="irrelevant",
                               reason=classification.reason or "not a buyer")
            elif kind == "type":
                # TYPE GATE: the user asked for a specific buyer situation. When
                # sibling-buyer acceptance is off, a genuine buyer of a
                # DIFFERENT type (e.g. need_agency found during a
                # need_freelancer search) is not a lead for THIS search.
                type_mismatch += 1
                _record_reject(post, classification, verdict_type=classification.lead_type,
                               reason=classification.reason or "type mismatch")
            elif kind == "accept":
                # Cross-search ownership was already checked before the LLM call
                # (Tier 1.1), so every survivor here is a NEW lead.
                accepted.append(EngineResult(post=post, classification=classification, qualified=qualified))
                gained += 1
            else:
                _note_reject(qualified)
                _record_reject(post, classification,
                               reason=qualified.reason or "failed scoring gates",
                               verdict_type=classification.lead_type)
        if scanned:
            est_yield = max(0.02, len(accepted) / scanned)

        if gained:
            zero_yield_rounds = 0
        elif not narrowed:
            zero_yield_rounds += 1
        # Keep the DB row live so the status poll shows progress.
        store.update_search(
            search_id,
            found_count=raw_found,
            accepted_count=len(accepted),
            scanned_count=scanned,
        )
        _persist_stats()
        progress("running", raw_found, len(accepted), scanned,
                 f"accepted {len(accepted)}/{leads_needed} {lead_type} leads (scanned {scanned}, pref-dropped {pref_dropped}, "
                 f"content-dropped {dir_dropped}, classify-dropped {classify_failed}, type-mismatch {type_mismatch}, "
                 f"already-owned {dup_existing}, undated {undated_dropped}, stale {stale_dropped}, "
                 f"full-text {enriched}, deleted {dead_dropped}, filled {filled_dropped})")
        if len(accepted) >= leads_needed:
            stop_reason = "target_reached"
            break
        # CREDIT SAFETY: stop as soon as several rounds added NO new lead -
        # whether that round had zero posts or posts that all got rejected.
        # Prevents a 0-lead niche from burning 200+ Serper calls.
        if zero_yield_rounds >= settings.engine_early_stop_empty_rounds and iteration > 0:
            detail = f"{zero_yield_rounds} rounds in a row added nothing new; stopped early"
            stop_reason = "empty_rounds_stop"
            break

    # A prefetched round the loop no longer needs: let it finish in the
    # background (its Serper calls are already paid) but never wait on it.
    if pending is not None:
        pending.cancel()

    # -------- flush Tier-0 rejection telemetry -----------------------------
    try:
        if reject_rows:
            store.record_rejections(reject_rows)
    except Exception:  # noqa: BLE001 - telemetry must never break a search
        log.debug("record_rejections unavailable (ignored)", exc_info=True)

    # -------- slice to EXACTLY N (never overdeliver) -----------------------
    # NEWEST FIRST: the user wants the LATEST genuine buyers. Recency is the
    # primary sort key (older low-freshness posts never crowd out a newer one);
    # quality score is only a tiebreak among posts with the same timestamp.
    def _sort_key(result: "EngineResult"):
        posted = result.post.posted_at
        ts = posted.timestamp() if posted else 0.0
        return (-ts, -result.overall)
    accepted.sort(key=_sort_key)
    top = accepted[:leads_needed]

    if not top and not raw_found and not errors and not deadline_hit:
        detail = detail or (
            "no candidate posts returned by Google for this window/query set - "
            + CRAWL_LAG_NOTE
        )

    def _row(result: "EngineResult") -> dict[str, Any]:
        p, cl = result.post, result.classification
        row: dict[str, Any] = {
            "search_id": search_id,
            "lead_type": cl.lead_type,
            "time_window": time_window,
            "post_url": p.post_url,
            "author_name": (p.author_name or "").replace("�", "") or None,
            "author_profile_url": p.author_profile_url,
            "post_text": (p.text or "").replace("�", ""),
            "post_date": p.posted_at.date() if p.posted_at else None,
            # Exact publish time (store drops it on schemas predating v18).
            "posted_at": p.posted_at,
            "overall_quality_score": result.qualified.overall,
            "service_match_score": result.qualified.service_match,
            "intent_strength": result.qualified.intent_strength,
        }
        # Only persist comment counts when the provider actually supplied one
        # (column may not exist on live DBs before migration_lead_types_v9).
        if p.num_comments is not None:
            row["num_comments"] = p.num_comments
        return row

    # EXACT N, NEVER MORE: save the newest N. If the store rejects some rows
    # (e.g. a post_url another account already owns on a pre-v18 schema),
    # backfill from the next-newest accepted leads - never exceeding N.
    delivered = store.insert_leads_many([_row(r) for r in top]) if top else 0
    conflicts = len(top) - delivered
    surplus = accepted[len(top):]
    while delivered < leads_needed and surplus:
        want = leads_needed - delivered
        chunk, surplus = surplus[:want], surplus[want:]
        got = store.insert_leads_many([_row(r) for r in chunk])
        conflicts += len(chunk) - got
        delivered += got
    if conflicts:
        detail = (detail + " | " if detail else "") + (
            f"{conflicts} lead(s) could not be saved (already owned elsewhere)")
    if dup_existing:
        detail = (detail + " | " if detail else "") + \
            f"{dup_existing} already-owned lead(s) from earlier searches were skipped while scanning for NEW ones"
    if type_mismatch:
        detail = (detail + " | " if detail else "") + \
            f"{type_mismatch} genuine post(s) of a DIFFERENT lead type were excluded (strict match to {lead_type})"

    shortage = delivered < leads_needed
    status = "completed"
    final_detail = detail
    if shortage:
        suffix = (f"only {delivered} of {leads_needed} qualified leads found after {iterations} iteration(s)"
                  + (", deadline hit" if deadline_hit else ""))
        if delivered == 0 and errors:
            suffix += f" ({len(errors)} provider error(s); see log)"
        elif delivered == 0:
            suffix += f". {CRAWL_LAG_NOTE}"
        final_detail = (final_detail + " | " if final_detail else "") + suffix

    # Rate-limit UX: when we made many Serper calls but the source returned
    # very few results (and few/no leads), tell the user it may be throttled
    # instead of an unexplained 0. Never hides a genuine shortage.
    if shortage and raw_found < 20:
        _sr, _dc = _call_counts()
        if _sr >= 30:
            final_detail = (final_detail + " | " if final_detail else "") + (
                "The search engine is returning very few results right now - it may be "
                "rate-limiting. Try again in a little while or with a different niche."
            )

    store.update_search(
        search_id,
        status=status,
        found_count=raw_found,
        accepted_count=delivered,
        scanned_count=scanned,
        error=None,
        finished_at=datetime.now(UTC),
    )
    _persist_stats(stop_reason)
    if reject_reasons:
        log.info("Search %s reject breakdown: %s", search_id,
                 ", ".join(f"{k}={v}" for k, v in sorted(reject_reasons.items())))
    _s, _d = _call_counts()
    newest = top[0].post.posted_at.isoformat() if top and top[0].post.posted_at else "-"
    log.info("Search %s done: status=%s found=%d accepted=%d scanned=%d (iterations=%d) "
             "pref_dropped=%d content_dropped=%d classify_failed=%d type_mismatch=%d dup_owned=%d "
             "undated_dropped=%d stale_dropped=%d full_text=%d full_text_flipped=%d "
             "dead_dropped=%d filled_dropped=%d liveness_unknown=%d newest=%s "
             "serper_requests=%d deepseek_calls=%d stop_reason=%s",
             search_id, status, raw_found, delivered, scanned, iterations,
             pref_dropped, dir_dropped, classify_failed, type_mismatch, dup_existing,
             undated_dropped, stale_dropped, enriched, enrich_flipped,
             dead_dropped, filled_dropped, liveness_unknown, newest,
             _s, _d, stop_reason)
    progress(status, raw_found, delivered, scanned, final_detail or "search finished")
    return _summary(search_id, status, raw_found, delivered, scanned, iterations, final_detail)


def _safe_check(checker: PostCheckFn, url: str):
    try:
        return checker(url)
    except Exception:  # noqa: BLE001 - a broken checker never costs a lead
        log.debug("post_checker raised for %s (kept)", url, exc_info=True)
        return None


def _gate_ok(content_filter: Callable[[str], bool], text: str) -> bool:
    try:
        return bool(content_filter(text))
    except Exception:  # noqa: BLE001
        return True


def _safe_fetch(fetcher: FullTextFn | None, url: str) -> str | None:
    if fetcher is None:
        return None
    try:
        return fetcher(url)
    except Exception:  # noqa: BLE001 - enrichment is best-effort
        log.debug("full_text_fetcher raised for %s (ignored)", url, exc_info=True)
        return None


def _summary(search_id: str, status: str, found: int, accepted: int, scanned: int,
             iterations: int, detail: str) -> EngineSummary:
    return EngineSummary(
        search_id=search_id,
        status=status,
        found=found,
        accepted=accepted,
        scanned=scanned,
        iterations=iterations,
        detail=detail,
    )
