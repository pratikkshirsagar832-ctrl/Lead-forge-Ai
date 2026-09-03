"""
Hyperclients — HyperAgent Orchestrator (LinkedIn agent)

The "brain" + "hands" wiring for the autonomous LinkedIn lead agent.

It REUSES the proven, deterministic LinkedIn engine (linkedin_pipeline) — exact
intent, exact country hard-gate, seller/job-seeker/marketplace/content
pre-filters, canonical acceptance, fail-closed AI, exact-count (never pad) —
but swaps two externals:

  * Discovery  : a standalone browser-use scraper SUBPROCESS instead of Apify.
                 The scraper runs in its own venv (Hyper_Agent/browser-use),
                 which has browser_use but not supabase, so it is isolated from
                 the API venv. It opens LinkedIn itself (logged-in via the
                 Cookie-Editor cookies) and emits raw candidates as JSON.
  * AI brain   : DeepSeek V4 Flash (settings.deepseek_model) instead of OpenAI.
                 The qualification classifier (LeadClassification schema) and
                 outreach pitch run on DeepSeek.

Everything else (candidate parse, country gate, pre-filter, acceptance,
quality scoring, dedupe, telemetry) is unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

from app.config import get_settings
from app.database import get_supabase_admin
from app.services.linkedin_pipeline import (
    MAX_POSTS_PER_LANE,
    _update_search,
)


class HyperAgentError(Exception):
    """Base error for the HyperAgent orchestrator."""


class ScraperUnavailableError(HyperAgentError):
    """Raised when the browser-use scraper subprocess cannot be invoked."""


def _scraper_python_path() -> str:
    """Path to the browser-use venv Python (has browser_use, not supabase)."""
    try:
        from app.config import get_settings
        cfg = get_settings().hyperagent_python
    except Exception:  # noqa: BLE001
        cfg = ""
    candidates = [
        cfg,
        os.environ.get("HYPERAGENT_PYTHON", ""),
        "/app/Hyper_Agent/browser-use/.venv/bin/python",          # prod
        "Hyper_Agent/browser-use/.venv/bin/python",               # dev (linux)
        "Hyper_Agent/browser-use/.venv/Scripts/python.exe",       # dev (windows)
    ]
    for cand in candidates:
        if cand and Path(cand).exists():
            return cand
    return sys.executable  # fallback: same interpreter


def _scraper_script_path() -> str:
    """Path to the standalone scraper CLI module."""
    here = Path(__file__).resolve().parent
    # app/services/hyperagent_scrape_cli.py
    return str(here / "hyperagent_scrape_cli.py")


def _run_scraper(payload: dict, timeout: int = 180) -> dict:
    """Invoke the standalone browser-use scraper subprocess, returning its JSON."""
    py = _scraper_python_path()
    script = _scraper_script_path()
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["ANONYMIZED_TELEMETRY"] = "false"
    try:
        proc = subprocess.run(
            [py, script],
            input=json.dumps(payload).encode("utf-8"),
            capture_output=True,
            timeout=timeout,
            env=env,
            cwd=str(Path(script).resolve().parents[2]),  # backend/
        )
    except FileNotFoundError as exc:
        raise ScraperUnavailableError(f"scraper python not found at {py}") from exc
    except subprocess.TimeoutExpired:
        logger.warning("HyperAgent scraper timed out after %ss", timeout)
        return {"ok": 0, "total": 1, "items": [], "errors": ["scraper_timeout"]}
    except Exception as exc:  # noqa: BLE001
        logger.warning("HyperAgent scraper subprocess error: %s", exc)
        return {"ok": 0, "total": 1, "items": [], "errors": [f"subprocess: {type(exc).__name__}: {exc}"]}

    if proc.returncode != 0:
        err_tail = (proc.stderr or b"").decode("utf-8", errors="replace")[-400:]
        logger.warning("HyperAgent scraper failed (rc=%s): %s", proc.returncode, err_tail)
        return {"ok": 0, "total": 1, "items": [], "errors": [f"scraper_rc_{proc.returncode}: {err_tail}"]}
    try:
        return json.loads(proc.stdout.decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("HyperAgent scraper returned non-JSON: %s", exc)
        return {"ok": 0, "total": 1, "items": [], "errors": [f"bad_json: {exc}"]}


def make_browser_discover(
    *,
    headless: bool = True,
    cookies_json: str = "",
    location: str = "",
    default_kind: str = "post",
    max_per_query: int = MAX_POSTS_PER_LANE,
    enrich_locations: bool = True,
) -> Callable:
    """Return a SYNC discover(queries) -> (ok_lanes, total_lanes, items, errors).

    Each call spawns the isolated browser-use scraper subprocess for the query
    batch. When `enrich_locations` is on and `location` (a country request) is
    given, it also fetches each author's profile location so the engine's
    country hard-gate can validate post leads accurately. A transient failure
    returns empty from the item lane (never raises), so the engine can retry
    with diversified queries across iterations.
    """
    def discover(
        queries: list[str], max_posts_per_lane: int = MAX_POSTS_PER_LANE
    ) -> tuple[int, int, list[dict], list[str]]:
        if not queries:
            return 0, 0, [], ["no_queries"]
        lane_count = min(3, max(1, (len(queries) + 3) // 4))
        lanes = [queries[i:i + 3] for i in range(0, len(queries), 3)][:3]
        ok, errors, items = 0, [], []
        for lane in lanes:
            payload = {
                "queries": lane,
                "kind": default_kind,
                "cookies_json": cookies_json,
                "location": location,
                "max_per_query": int(max_posts_per_lane),
                "headless": bool(headless),
            }
            try:
                res = _run_scraper(payload)
            except ScraperUnavailableError as exc:
                logger.warning("HyperAgent scraper unavailable: %s", exc)
                return 0, lane_count, [], [str(exc)[:160]]
            if res.get("ok", 0) > 0:
                ok += 1
            items.extend(res.get("items") or [])
            errors.extend(res.get("errors") or [])

        # Post leads carry no country; enrich authors when a country is requested.
        if enrich_locations and location and default_kind != "job":
            items = _enrich_items_locations(items, cookies_json, headless, errors)
        return ok, lane_count, items, errors

    return discover


def _enrich_items_locations(items: list[dict], cookies_json: str, headless: bool, errors: list[str]) -> list[dict]:
    """Fetch each post author's profile location and inject it into the item so
    the engine's country gate can validate. Non-fatal on failure."""
    urls = []
    seen = set()
    for it in items:
        u = ((it.get("author") or {}).get("url") or "").split("?")[0]
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    if not urls:
        return items
    try:
        payload = {"enrich_urls": urls[:20], "enrich_max": 20, "cookies_json": cookies_json, "headless": headless}
        res = _run_scraper(payload)
        locs = res.get("locations") or {}
    except ScraperUnavailableError as exc:
        logger.warning("HyperAgent author enrichment skipped: %s", exc)
        return items
    for it in items:
        auth = it.get("author") or {}
        u = (auth.get("url") or "").split("?")[0].rstrip("/").lower()
        loc = locs.get(u)
        if loc:
            # Inject location so resolve_author_country finds it.
            auth["location"] = loc
            auth["linkedinText"] = loc
    logger.info("HyperAgent: enriched %d author locations across %d items", len(locs), len(items))
    return items


def _inject_deepseek_classifier():
    """Return the (classify, attach_classification, candidate_key) trio for
    DeepSeek; import lazily so the app loads even if openai is absent."""
    from app.services.ai_service import (
        attach_classification,
        candidate_key,
        classify_linkedin_candidates,
    )
    return classify_linkedin_candidates, attach_classification, candidate_key


def _make_query_provider(user_id: str):
    """Return a sync callable(lead_type, service, country) -> list[learned queries].

    The agent uses its up-to-date MEMORY of powerful queries (learned from DeepSeek
    and stored in `agent_services`) so repeat searches get better and stay
    consistent. Falls back to the engine's own templates if memory is empty.
    """
    from app.services.hyperagent_memory import get_or_learn_queries

    def provider(lead_type: str, service: str, country: str) -> list[str]:
        try:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(get_or_learn_queries(user_id, service, lead_type, country or ""))
            finally:
                loop.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("HyperAgent query provider failed (%s) — using templates", exc)
            return []

    return provider


async def run_hyperagent_engine(
    search_id: str,
    user_id: str,
    query: str,
    enrich_emails: bool,
    max_results: int,
    lead_types: list[str] | None = None,
    location: str = "",
) -> dict:
    """Agent entry point — mirrors run_linkedin_engine but uses the browser
    scraper subprocess (discovery) + DeepSeek (classification)."""
    from app.config import get_settings as _settings
    from app.services.linkedin_pipeline import (
        LeadType,
        LeadRequest,
        MAX_RESULTS_CAP,
        parse_country_request,
        parse_wire_lead_types,
        _prefetch_known_urls,
        _run_engine_with_externals,
    )

    settings = _settings()
    supabase = get_supabase_admin()
    country_codes, country_text = parse_country_request(location or "")
    canonical_types = parse_wire_lead_types(lead_types)
    if not canonical_types:
        canonical_types = [LeadType.FREELANCER_NEEDED.value]

    request = LeadRequest(
        search_id, user_id, query.strip(),
        max(1, min(int(max_results), MAX_RESULTS_CAP)),
        canonical_types, country_codes, country_text, enrich_emails,
        source="hyper_agent",
        query_provider=_make_query_provider(user_id),
    )

    await _update_search(supabase, search_id, {
        "status": "scraping", "progress_percent": 3,
        "message": f"HyperAgent browsing LinkedIn for {', '.join(t.replace('_', ' ') for t in request.lead_types)} · {request.service} · {request.country_text or 'Any'}...",
    })

    # DeepSeek powers the AI brain (OpenAI-compatible AsyncOpenAI client).
    if not settings.deepseek_api_key:
        raise HyperAgentError("DEEPSEEK_API_KEY not configured — cannot run the agent without an AI brain.")
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)

    classify, attach_classification, candidate_key = _inject_deepseek_classifier()
    known_urls = await _prefetch_known_urls(supabase, user_id)

    # Route discovery by lead type: hiring -> Jobs (guest-friendly), else posts.
    default_kind = "job" if set(canonical_types) == {LeadType.HIRING.value} else "post"
    discover = make_browser_discover(
        headless=settings.hyperagent_headless,
        cookies_json=settings.linkedin_cookies_json,
        location=request.country_text,
        default_kind=default_kind,
    )

    return await _run_engine_with_externals(
        supabase=supabase,
        request=request,
        client=client,
        known_urls=known_urls,
        discover=discover,
        classify=classify,
        attach_classification=attach_classification,
        candidate_key=candidate_key,
    )


async def run_hyperagent_pipeline_fast(
    search_id: str,
    user_id: str,
    query: str,
    enrich_emails: bool,
    max_results: int,
    lead_types: list[str] | None = None,
    location: str = "",
) -> None:
    """Background-task entry point (runs the engine, mirrors pipeline_fast)."""
    try:
        await run_hyperagent_engine(search_id, user_id, query, enrich_emails, max_results, lead_types, location)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[HyperAgent:{search_id}] engine failed: {exc}", exc_info=True)
        supabase = get_supabase_admin()
        await _update_search(supabase, search_id, {
            "status": "failed", "message": "Agent search failed unexpectedly",
            "error_message": str(exc),
        })
