"""Iterative exact-count engine (§9).

Deliver exactly N qualified leads, or run out of provider results trying —
never pad the count with weak matches. Sequence per iteration:
queries -> discovery -> canonical dedupe -> deterministic prefilter -> GPT-4o
classification (concurrent, fail-closed) -> scoring gates -> accept.
If short of N, diversify the query set and repeat (iteration + deadline caps,
early stop after consecutive zero-yield rounds), then slice to exactly N.

SERP semantics (§0): with Google-over-LinkedIn discovery, an empty result set
for a tight query is EXPECTED provider behavior (partial crawl, 1-3 day lag),
NOT a failure. Zero-hit searches therefore complete with a shortage and an
explanatory message; only genuine provider errors (network, API rejection)
mark the search failed.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from config import Settings
from discovery.base import DiscoveryClient, DiscoveryConfigError, DiscoveryError, canonical_post_url
from geography import canonical_label
from models import TimeWindow
from prefilter import prefilter
from query_builder import next_queries
from scoring import ScoreConfig, compute_score

log = logging.getLogger(__name__)

ProgressFn = Callable[[str, int, int, int, str], None]

CRAWL_LAG_NOTE = (
    "Google's coverage of LinkedIn posts is partial and typically lags 1–3 days, "
    "so tight queries and short windows often return little — this is expected, not a failure."
)


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
) -> EngineSummary:
    """Synchronous orchestrator. Runs inside a background task/thread.

    `content_filter` (optional) is a cheap text test applied BEFORE any LLM
    call: return False to drop a candidate whose text clearly contradicts the
    requested content direction (e.g. an advice/seller post that merely
    contains the keywords). Dropping here saves the DeepSeek call AND keeps the
    engine's exact-count loop honest — it only counts posts that survive the
    content gate, so it keeps scanning until it genuinely finds N matching
    leads instead of stopping early on posts it later discards at save time.
    """
    progress = progress or _noop_progress
    row = store.get_search(search_id)
    if row is None:
        raise KeyError(f"search {search_id} not found")

    service = row["service"]
    country_raw = row.get("country") or ""  # canonical code when recognized, else raw text
    # Human-friendly label (canonical country name, else the raw free text) —
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

    used_queries: set[str] = set()
    seen_urls: set[str] = set()
    raw_found = 0
    scanned = 0
    classify_failed = 0
    pref_dropped = 0
    dup_existing = 0
    type_mismatch = 0
    dir_dropped = 0  # content-direction gate drops (cheap, zero LLM spend)
    reject_reasons: dict[str, int] = {}
    errors: list[str] = []
    accepted: list[EngineResult] = []  # NEW leads only (not already in the DB)
    deadline = time.monotonic() + settings.engine_deadline_seconds
    deadline_hit = False
    zero_yield_rounds = 0
    iterations = 0
    detail = ""

    def _note_reject(qualified) -> None:
        for name, ok in qualified.gates.items():
            if not ok:
                reject_reasons[name] = reject_reasons.get(name, 0) + 1

    for iteration in range(max(1, settings.engine_max_iterations)):
        iterations = iteration + 1
        if time.monotonic() > deadline:
            deadline_hit = True
            break
        # Cooperative cancel — lets a user cancel stop provider spend promptly.
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
        queries = [q for q in next_queries(service, lead_type, iteration) if q not in used_queries]
        # Country bias: on the first wave (and whenever a country is known and
        # not a huge multi-country region), scope every query with the country
        # name so Google returns posts authored in that country, not the
        # country that happens to rank globally. Later waves broaden.
        if queries and iteration == 0 and country:
            cn = country.lower()
            if cn not in ("", "worldwide", "global", "europe", "asia", "middle east", "gulf"):
                queries = [f"{q} {country}" for q in queries]
        if not queries:
            detail = "query pool exhausted"
            break
        used_queries.update(queries)
        progress("running", raw_found, len(accepted), scanned, f"iteration {iteration + 1}: {len(queries)} queries")

        try:
            batch = discovery.search_posts(queries, cutoff)
        except DiscoveryConfigError as exc:
            errors.append(str(exc))
            log.error("Discovery config error (search %s): %s", search_id, exc)
            store.update_search(search_id, status="failed", error=str(exc), finished_at=datetime.now(UTC))
            progress("failed", raw_found, len(accepted), scanned, str(exc))
            return _summary(search_id, "failed", raw_found, len(accepted), scanned, iterations, str(exc))
        except DiscoveryError as exc:
            # A genuine provider failure (network/API rejection) is loud; an
            # EMPTY result set is handled below as an ordinary shortage.
            errors.append(str(exc))
            log.error("Discovery error (search %s): %s", search_id, exc)
            store.update_search(search_id, status="failed", error=str(exc), finished_at=datetime.now(UTC))
            progress("failed", raw_found, len(accepted), scanned, str(exc))
            return _summary(search_id, "failed", raw_found, len(accepted), scanned, iterations, str(exc))

        raw_found += len(batch.posts)
        candidates = []
        for post in batch.posts:
            if not post.post_url:
                continue  # a lead without a post URL has no identity — never accept it
            key = canonical_post_url(post.post_url)
            if not key or key in seen_urls:
                continue
            seen_urls.add(key)
            verdict = prefilter(
                post.text or "",
                max_comments=settings.max_comments_allowed,
                num_comments=post.num_comments,
            )
            if not verdict.keep:
                pref_dropped += 1
                continue
            # CONTENT-DIRECTION GATE (cheap — NO LLM call). When a content_filter
            # is wired (it mirrors the save-time store gate), a post whose text
            # clearly contradicts the requested buyer direction is dropped here.
            # Only posts that survive this gate can ever be accepted, so the
            # exact-count loop never stops early on posts it would later discard
            # at save time — engine "accepted" == rows actually persisted — and
            # no DeepSeek call is spent classifying a guaranteed discard.
            if content_filter is not None:
                try:
                    if not content_filter(post.text or ""):
                        dir_dropped += 1
                        continue
                except Exception:  # noqa: BLE001 - a broken gate must never kill a search
                    log.debug("content_filter raised for a candidate (kept for classifier)", exc_info=True)
            candidates.append(post)

        if not candidates:
            zero_yield_rounds += 1
            if zero_yield_rounds >= settings.engine_early_stop_empty_rounds and iteration > 0:
                detail = f"{zero_yield_rounds} rounds in a row added nothing new; stopped early"
                break
            continue

        try:
            classifications = classifier.classify_batch(
                candidates,
                service=service,
                lead_type=lead_type,
                country=country,
                max_concurrency=settings.classifier_concurrency,
                accepted_types=accepted_types if len(accepted_types) > 1 else None,
            )
        except Exception as exc:  # noqa: BLE001 - classifier unavailable == fail-closed
            msg = f"classifier unavailable: {exc}"
            errors.append(msg)
            log.exception("Classifier batch failed (search %s) — fail-closed", search_id)
            store.update_search(search_id, status="failed", error=msg, finished_at=datetime.now(UTC))
            progress("failed", raw_found, len(accepted), scanned, msg)
            return _summary(search_id, "failed", raw_found, len(accepted), scanned, iterations, msg)

        gained = 0
        qualified_batch: list[EngineResult] = []
        for post, classification in zip(candidates, classifications):
            scanned += 1
            if classification is None:
                classify_failed += 1  # fail-closed: dropped
                continue
            if classification.lead_type not in accepted_types:
                # TYPE GATE: the user asked for a specific buyer situation. When
                # sibling-buyer acceptance is off, a genuine buyer of a
                # DIFFERENT type (e.g. our_agency found during a
                # need_freelancer search) is not a lead for THIS search.
                type_mismatch += 1
                continue
            qualified = compute_score(
                classification,
                requested_country=country,
                requested_country_code=country_raw,
                post_text=post.text or "",
                cfg=cfg,
            )
            if qualified.keep:
                qualified_batch.append(EngineResult(post=post, classification=classification, qualified=qualified))
            else:
                _note_reject(qualified)

        # post_url is globally unique: posts you already own from EARLIER
        # searches do not count toward N — skip them and keep scanning so the
        # search delivers exactly N NEW leads (never fewer, never padded).
        if qualified_batch:
            existing = store.find_existing_post_urls(r.post.post_url for r in qualified_batch)
            for result in qualified_batch:
                if result.post.post_url in existing:
                    dup_existing += 1
                    log.info("Skipping already-owned lead (from an earlier search): %s", result.post.post_url)
                    continue
                accepted.append(result)
                gained += 1

        zero_yield_rounds = zero_yield_rounds + 1 if gained == 0 else 0
        # Keep the DB row live so the status poll shows progress.
        store.update_search(
            search_id,
            found_count=raw_found,
            accepted_count=len(accepted),
            scanned_count=scanned,
        )
        progress("running", raw_found, len(accepted), scanned,
                 f"accepted {len(accepted)}/{leads_needed} {lead_type} leads (scanned {scanned}, pref-dropped {pref_dropped}, "
                 f"content-dropped {dir_dropped}, classify-dropped {classify_failed}, type-mismatch {type_mismatch}, "
                 f"already-owned {dup_existing})")
        if len(accepted) >= leads_needed:
            break
        # CREDIT SAFETY: stop as soon as several rounds added NO new lead —
        # whether that round had zero posts or posts that all got rejected.
        # Prevents a 0-lead niche from burning 200+ Serper calls.
        if zero_yield_rounds >= settings.engine_early_stop_empty_rounds and iteration > 0:
            detail = f"{zero_yield_rounds} rounds in a row added nothing new; stopped early"
            break

    # -------- slice to EXACTLY N (never overdeliver) -----------------------
    # Recency-first WITHIN quality bands: a fresh post (>=80, or 65-79) is
    # preferred over an older one of similar quality so users see the newest
    # genuine buyers, while weak-but-new posts never crowd out strong ones.
    def _sort_key(result: "EngineResult"):
        posted = result.post.posted_at
        ts = posted.timestamp() if posted else 0.0
        band = 0 if result.overall >= 80 else (1 if result.overall >= 65 else 2)
        return (band, ts)
    accepted.sort(key=_sort_key)
    top = accepted[:leads_needed]

    if not top and not raw_found and not errors and not deadline_hit:
        detail = detail or (
            "no candidate posts returned by Google for this window/query set — "
            + CRAWL_LAG_NOTE
        )

    rows = []
    for result in top:
        p, cl = result.post, result.classification
        row: dict[str, Any] = {
            "search_id": search_id,
            "lead_type": cl.lead_type,
            "time_window": time_window,
            "post_url": p.post_url,
            "author_name": p.author_name,
            "author_profile_url": p.author_profile_url,
            "post_text": p.text,
            "post_date": p.posted_at.date() if p.posted_at else None,
            "overall_quality_score": result.qualified.overall,
            "service_match_score": result.qualified.service_match,
            "intent_strength": result.qualified.intent_strength,
        }
        # Only persist comment counts when the provider actually supplied one
        # (column may not exist on live DBs before migration_lead_types_v9).
        if p.num_comments is not None:
            row["num_comments"] = p.num_comments
        rows.append(row)
    inserted = store.insert_leads_many(rows)
    if inserted < len(rows):
        detail = (detail + " | " if detail else "") + f"{len(rows) - inserted} rows could not be saved (post_url conflict)"
    if dup_existing:
        detail = (detail + " | " if detail else "") + \
            f"{dup_existing} already-owned lead(s) from earlier searches were skipped while scanning for NEW ones"
    if type_mismatch:
        detail = (detail + " | " if detail else "") + \
            f"{type_mismatch} genuine post(s) of a DIFFERENT lead type were excluded (strict match to {lead_type})"

    shortage = len(top) < leads_needed
    status = "completed"
    final_detail = detail
    if shortage:
        suffix = (f"only {len(top)} of {leads_needed} qualified leads found after {iterations} iteration(s)"
                  + (", deadline hit" if deadline_hit else ""))
        if len(top) == 0 and errors:
            suffix += f" ({len(errors)} provider error(s); see log)"
        elif len(top) == 0:
            suffix += f". {CRAWL_LAG_NOTE}"
        final_detail = (final_detail + " | " if final_detail else "") + suffix

    store.update_search(
        search_id,
        status=status,
        found_count=raw_found,
        accepted_count=len(top),
        scanned_count=scanned,
        error=None,
        finished_at=datetime.now(UTC),
    )
    if reject_reasons:
        log.info("Search %s reject breakdown: %s", search_id,
                 ", ".join(f"{k}={v}" for k, v in sorted(reject_reasons.items())))
    log.info("Search %s done: status=%s found=%d accepted=%d scanned=%d (iterations=%d) "
             "pref_dropped=%d content_dropped=%d classify_failed=%d type_mismatch=%d dup_owned=%d",
             search_id, status, raw_found, len(top), scanned, iterations,
             pref_dropped, dir_dropped, classify_failed, type_mismatch, dup_existing)
    progress(status, raw_found, len(top), scanned, final_detail or "search finished")
    return _summary(search_id, status, raw_found, len(top), scanned, iterations, final_detail)


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
