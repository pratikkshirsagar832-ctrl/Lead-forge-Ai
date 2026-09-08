"""Hyperagent service — runs the ORIGINAL standalone Hyperagent engine
(backend/ha/) inside the main backend process.

The engine and its modules are copied verbatim from backend/Hyperagent/backend
(no rewrites). It persists to dedicated ha_searches / ha_leads tables in the
same main Supabase project (see supabase/migration_ha_tables.sql).
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_HA_DIR = Path(__file__).resolve().parent.parent.parent / "ha"
if str(_HA_DIR) not in sys.path:
    sys.path.insert(0, str(_HA_DIR))

# Original Hyperagent engine modules (imported as-is from backend/ha/)
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "")

from config import Settings as HaSettings  # noqa: E402
from db import SupabaseStore as HaSupabaseStore, build_store as ha_build_store  # noqa: E402
from discovery.base import DiscoveryClient  # noqa: E402
from discovery.serp_client import SerperDiscoveryClient  # noqa: E402
from engine import run_search as ha_run_search  # noqa: E402
from geography import normalize_country  # noqa: E402

log = logging.getLogger(__name__)

# In-process progress registry (polled by status endpoint)
_PROGRESS: dict[str, dict[str, Any]] = {}
_PROGRESS_LOCK = threading.Lock()

# Cancellation registry: the engine checks this between iterations so a user
# cancel stops Serper/DeepSeek spend promptly instead of running to completion.
_CANCELLED: set[str] = set()
_CANCEL_LOCK = threading.Lock()


def request_cancel(search_id: str) -> None:
    with _CANCEL_LOCK:
        _CANCELLED.add(search_id)


def _is_cancelled(search_id: str) -> bool:
    with _CANCEL_LOCK:
        return search_id in _CANCELLED


def _clear_cancel(search_id: str) -> None:
    with _CANCEL_LOCK:
        _CANCELLED.discard(search_id)


def _progress_push(search_id: str, stage: str, found: int, accepted: int, scanned: int, message: str = "") -> None:
    with _PROGRESS_LOCK:
        if len(_PROGRESS) > 500:
            _PROGRESS.pop(next(iter(_PROGRESS)), None)
        _PROGRESS[search_id] = {
            "search_id": search_id, "stage": stage, "found": found,
            "accepted": accepted, "scanned": scanned, "message": message,
        }


def get_progress(search_id: str) -> dict[str, Any] | None:
    with _PROGRESS_LOCK:
        return _PROGRESS.get(search_id)


def ha_normalize_country(value: str):
    """Normalize free-text country → canonical code (original geography table)."""
    return normalize_country(value)


def ha_lead_type_from(lead_types) -> str:
    """Map main-app lead_types (buyer/agency_wanted) → Hyperagent type.

    UI semantics:
      buyer          -> need_freelancer : posts asking for a freelancer
      agency_wanted  -> our_agency      : posts seeking an agency/outside team
    Hiring / employee job-ads are never requested (filtered out by the store
    content gate below). Engine sibling acceptance keeps genuine buyers of any
    bucket flowing so a request never starves.
    """
    lts = lead_types or []
    if lts and "agency_wanted" in lts and "buyer" not in lts:
        return "our_agency"
    return "need_freelancer"


def ha_time_window_from() -> str:
    """Freshness window — latest-first with enough pool volume.

    14d window (Google crawl lag 1–3 days ⇒ ~11-13 real days of posts). The
    engine + results endpoint sort newest-first, so the freshest genuine
    buyers are always shown while a larger window keeps volume healthy.
    """
    return "14d"


def _ha_settings() -> HaSettings:
    """Build the original engine's Settings from main backend env vars."""
    from app.config import get_settings as get_app_settings

    main = get_app_settings()
    os.environ["DEEPSEEK_API_KEY"] = main.deepseek_api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    os.environ["SUPABASE_URL"] = main.supabase_url
    os.environ["SUPABASE_SERVICE_ROLE_KEY"] = main.supabase_service_role_key
    os.environ["SERPER_API_KEY"] = main.serper_api_key or os.environ.get("SERPER_API_KEY", "")
    os.environ.setdefault("SERPER_RESULTS_PER_QUERY", str(main.serper_results_per_query))
    os.environ.setdefault("SERPER_PAGES_PER_QUERY", str(main.serper_pages_per_query))
    os.environ.setdefault("LLM_PROVIDER", "deepseek")
    os.environ.setdefault("DEEPSEEK_MODEL", main.deepseek_model)
    # GLOBAL SEARCH: no country filter at all. STRICT_COUNTRY stays off so
    # every country's genuine buyers are accepted.
    os.environ["ACCEPT_SIBLING_BUYERS"] = "1"
    os.environ["MIN_OVERALL_SCORE"] = "55"
    os.environ["MIN_SERVICE_MATCH"] = "45"
    os.environ["MIN_INTENT_STRENGTH"] = "recommendation"
    # Credit safety: cap iterations/deadline/empty rounds so one search can
    # never burn unbounded Serper calls on a niche with no leads. Pagination
    # now returns 3-4x more candidates per query, so give the engine a few
    # more iterations and slack to scan them before declaring it exhausted.
    os.environ["ENGINE_MAX_ITERATIONS"] = "12"
    os.environ["ENGINE_DEADLINE_SECONDS"] = "540"
    os.environ["ENGINE_EARLY_STOP_EMPTY_ROUNDS"] = "4"
    # Model gate OFF: referral/recommendation posts (very common for agency
    # seekers) often hedge is_qualified=false despite real buying intent — the
    # score/intent/content gates already protect precision.
    os.environ["REQUIRE_MODEL_QUALIFIED"] = "0"
    os.environ["STRICT_COUNTRY"] = "0"
    return HaSettings()


# ISO alpha-2 → Serper `gl` (Google country bias). Serper wants lowercase,
# e.g. "us", "gb", "in". Falls back to "" (no bias) when unknown.
_GL_BY_CODE = {
    "US": "us", "GB": "uk", "IN": "in", "CA": "ca", "AU": "au", "NZ": "nz",
    "DE": "de", "FR": "fr", "NL": "nl", "BE": "be", "CH": "ch", "AT": "at",
    "SE": "se", "NO": "no", "DK": "dk", "FI": "fi", "ES": "es", "IT": "it",
    "PT": "pt", "IE": "ie", "AE": "ae", "SA": "sa", "QA": "qa", "KW": "kw",
    "SG": "sg", "IL": "il", "JP": "jp", "KR": "kr", "TW": "tw", "CN": "cn",
    "BR": "br", "MX": "mx", "AR": "ar", "CL": "cl", "CO": "co", "ZA": "za",
    "NG": "ng", "KE": "ke", "EG": "eg", "PK": "pk", "BD": "bd", "PH": "ph",
    "VN": "vn", "ID": "id", "TH": "th", "MY": "my", "TR": "tr", "PL": "pl",
}


def build_discovery(settings: HaSettings, country_code: str = "") -> DiscoveryClient:
    if settings.serp_configured:
        gl = _GL_BY_CODE.get((country_code or "").strip().upper(), "")
        return SerperDiscoveryClient(
            settings.serper_api_key,
            base_url=settings.serper_base_url,
            site_restriction=settings.serper_site_restriction,
            results_per_query=settings.serper_results_per_query,
            pages_per_query=settings.serper_pages_per_query,
            gl=gl,
            hl=settings.serper_hl,
            timeout_seconds=settings.serper_timeout_seconds,
        )
    raise RuntimeError("SERPER_API_KEY is not set — cannot run LinkedIn search")


def build_classifier(settings: HaSettings):
    from classifier import GptClassifier

    if settings.llm_provider == "deepseek":
        return GptClassifier(
            settings.deepseek_api_key,
            model=settings.deepseek_model,
            base_url=settings.deepseek_base_url,
            provider="deepseek",
            json_mode="json_object",
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
    raise RuntimeError("No LLM provider configured (DEEPSEEK_API_KEY)")


class _ForceTypeStore:
    """Delegating store wrapper that enforces the requested lead type on save.

    The engine (sibling mode) accepts every genuine buyer (need_freelancer /
    our_agency) so nothing starves; THIS wrapper is what makes a Freelancer
    search show freelancer-needed posts and an Agency search show agency/
    team-sourcing posts. The type label is stamped AND opposite-direction
    content is dropped.
    """

    # Employee-role / job-ad markers. When present WITHOUT any freelance/contract
    # wording the post is a company job-ad, so it is dropped from a Freelancer
    # search (employee job-ads are never leads).
    _EMPLOYEE_HIRING = (
        "we are hiring", "we're hiring", "hiring:", "vacancy", "open role",
        "open position", "job opening", "position available", "salary",
        "recruiting", "headcount", "careers page", "apply now", "benefits package",
        "full-time", "full time", "part-time", "part time", "join our team",
        "join our growing team", "to join our team", "for our team",
    )
    # Freelancer / contract wording (keeps a company freelancer-ask in
    # Freelancer mode even when it also says "hiring a freelance").
    _FREELANCER_WORDS = ("freelance", "freelancer", "freelancers", "contractor",
                         "contract work", "independent contractor", "one-off project",
                         "project basis", "gig")
    # Agency / outside-team wording. A post is agency-relevant when it names an
    # agency/team/firm OR when a company/team is sourcing help to build its own
    # bench of creators/developers (very common phrasing on LinkedIn).
    _AGENCY_WORDS = ("agency", "agencies", "an agency", "agency for", "marketing agency",
                     "digital agency", "creative agency", "design agency", "development agency",
                     "outsource", "white label", "white-label", "a firm", "creative partner",
                     "agency to handle", "for our agency", "a team of", "our partner agency",
                     "looking for a team", "need a team", "hire a team")
    _AGENCY_TEAM_CONTEXT = ("we need", "we are looking for", "we're looking for",
                            "looking for a few", "looking for several", "we want to build",
                            "help us build", "for our brand", "for our company",
                            "for our startup", "for our business", "for our channel",
                            "for our clients", "build our content", "video editors and",
                            "editors and writers", "freelancers to work with")
    # Agency-sourcing phrasing (an agency recruiting freelancers for its clients)
    # — not a freelancer-needed ask, so dropped in Freelancer mode even when the
    # word "freelancers" appears.
    _AGENCY_SOURCING = ("for client projects", "on client projects", "for our clients",
                        "client projects", "client work", "work with our agency",
                        "freelance bench", "overflow work", "white label freelancers",
                        "white-label freelancers")

    def __init__(self, inner, lead_type: str) -> None:
        self._inner = inner
        self._lead_type = lead_type

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def insert_leads_many(self, rows) -> int:
        forced = []
        for r in rows:
            item = dict(r)
            item["lead_type"] = self._lead_type
            text = (item.get("post_text") or "").lower()
            if text and not _content_matches_requested_type(text, self._lead_type):
                log.info("Type mismatch dropped (%s): %s",
                         self._lead_type, text[:60].replace("\n", " "))
                continue
            forced.append(item)
        return self._inner.insert_leads_many(forced)


# Near-certain non-buyers: a post carrying one of these AND showing NO genuine
# buyer ask is a seller / job-ad / self-promo, not a lead. The engine was
# classifying ~70-90 such posts per search only to reject them as `irrelevant`,
# burning DeepSeek credits. Dropping them BEFORE the LLM call is the biggest
# single credit saver that does not reduce the genuine accepts.
_STRONG_NEGATIVES: tuple[str, ...] = (
    # employee job ads
    "apply now", "apply here", "vacancy", "open position", "send your resume",
    "careers page", "full-time position", "benefits package", "salary range",
    "job opening", "joining our team", "we are hiring a", "we're hiring a",
    # sellers / self-promotion
    "we offer", "we provide", "our agency can help", "book a call", "get a quote",
    "free consultation", "get started today", "sign up now", "limited spots",
    "link in bio", "we specialize", "our services include", "shoot me a dm",
    "we are a full-service", "we're a full-service", "we deliver", "dm me for",
    "dm to book", "contact us", "we are a leading", "we're a leading",
    "helping brands", "we help brands", "i provide", "my services include",
    "taking new clients", "available for work",
    # job seekers
    "open to work", "available for projects", "seeking new clients",
    "available for hire", "freelance for hire", "hire me",
    # talent marketplaces / recruiting-sellers
    "join our network", "we connect brands", "staffing agency", "we place",
    "submit your portfolio", "talent pool", "register as a freelancer",
    # thought leadership / engagement bait
    "save this for later", "pro tip", "top 10", "lessons learned", "why your",
)

# Strong buyer-ask phrases. When present, the post stays for the classifier even
# if it also mixes in seller/self-promo wording (genuine ask, ambiguous framing).
# Deliberately excludes bait like "need a X?" — that is how sellers open posts.
_STRONG_NEED: tuple[str, ...] = (
    "we need", "our company needs", "our team needs", "anyone know", "anyone recommend",
    "in need of", "seeking a ", "seeking an ", "hiring a freelance", "freelancer needed",
    "freelancers needed", "we want to", "help us build", "for our brand", "for our company",
    "for our channel", "for our startup", "for our business", "recommendations for",
    "on the hunt for", "who can handle", "who can help", "dm if you know",
)


def _content_matches_requested_type(text: str, lead_type: str) -> bool:
    """Pure text gate: is this post's content compatible with the REQUESTED
    buyer direction?

    This is the single source of truth used BOTH by the save-time store gate
    (drop mismatches before persistence) AND by the engine BEFORE any DeepSeek
    call (a cheap pre-LLM `content_filter`). Because the engine only counts
    posts that survive the exact same predicate the store applies, an accepted
    post is never discarded at save time — a search that claims N leads really
    saves N.

    need_freelancer  -> someone needs an independent freelancer/contractor.
    our_agency       -> an agency / outside team is being sourced.
    Clear seller / job-ad / job-seeker / marketplace content with NO genuine
    buyer ask is dropped here for free (biggest credit saver) rather than being
    classified only to be rejected. Empty text is never cheap-dropped.
    """
    low = (text or "").lower()
    if not low:
        return True
    emp_hiring = any(m in low for m in _ForceTypeStore._EMPLOYEE_HIRING)
    freelance = any(m in low for m in _ForceTypeStore._FREELANCER_WORDS)
    agency = any(m in low for m in _ForceTypeStore._AGENCY_WORDS)
    agency_sourcing = any(m in low for m in _ForceTypeStore._AGENCY_SOURCING)
    team_ctx = any(m in low for m in _ForceTypeStore._AGENCY_TEAM_CONTEXT)
    neg = any(m in low for m in _STRONG_NEGATIVES)
    need = any(m in low for m in _STRONG_NEED)
    if lead_type == "need_freelancer":
        if agency_sourcing:
            return False
        if emp_hiring and not freelance:
            return False
        # Seller/job-ad/job-seeker with no genuine ask and no freelance wording.
        if neg and not freelance and not need:
            return False
        return True
    if lead_type == "our_agency":
        if not (agency or team_ctx):
            return False
        if neg and not need and not team_ctx:
            return False
        return True
    return True


# Max concurrently-running Hyperagent engines. Each burns paid Serper +
# DeepSeek calls, so users must not be able to stack unbounded parallel spend.
_ENGINE_SLOT = threading.BoundedSemaphore(4)
_ENGINE_SLOT_WAIT_S = 30.0


def _run_search_worker(search_id: str, user_id: str, settings: HaSettings, store, leads_needed: int = 10,
                       force_lead_type: str | None = None, country_code: str = "") -> None:
    # Acquire before doing ANY paid work; other queued searches wait their turn
    # instead of running concurrently with the same user's (or others') engines.
    if not _ENGINE_SLOT.acquire(timeout=_ENGINE_SLOT_WAIT_S):
        log.error("Hyperagent engine slot timeout for %s — failing search", search_id)
        try:
            store.update_search(search_id, status="failed",
                                error="too many searches running at once; try again shortly",
                                finished_at=datetime.now(UTC))
        except Exception:
            log.exception("Could not fail search %s on slot timeout", search_id)
        _sync_main_search_row(search_id, None, user_id=user_id, error="Too many searches running at once. Try again shortly.",
                              leads_needed=leads_needed)
        return
    try:
        _run_search_worker_body(search_id, user_id, settings, store, leads_needed,
                                force_lead_type, country_code)
    finally:
        _ENGINE_SLOT.release()


def _run_search_worker_body(search_id: str, user_id: str, settings: HaSettings, store, leads_needed: int = 10,
                            force_lead_type: str | None = None, country_code: str = "") -> None:
    def cb(stage: str, found: int, accepted: int, scanned: int, message: str = "") -> None:
        _progress_push(search_id, stage, found, accepted, scanned, message)

    def should_stop() -> bool:
        # Cooperative cancel: the router registers the id via request_cancel().
        return _is_cancelled(search_id)

    try:
        discovery = build_discovery(settings, country_code=country_code)
        classifier = build_classifier(settings)
        # Store wrapper: the engine may classify a genuine post under either
        # buyer bucket (need_freelancer / our_agency). The product promise is
        # that a freelancer search returns freelancer-needed leads and an
        # agency search returns agency-sourcing leads — so the STORED type is
        # forced to the requested wire type before persistence.
        content_filter = None
        if force_lead_type:
            store = _ForceTypeStore(store, force_lead_type)
            # Pre-LLM direction gate (cheap, no DeepSeek spend): drop posts the
            # store would discard at save time BEFORE they are classified. The
            # engine therefore only counts posts that will really be saved —
            # requested N leads => N saved (when the pool has them) — and the
            # ~70% of LLM-classified candidates that were obvious non-matches
            # never burn a DeepSeek call.
            content_filter = lambda text: _content_matches_requested_type(text, force_lead_type)  # noqa: E731
        summary = ha_run_search(
            search_id,
            store=store,
            discovery=discovery,
            classifier=classifier,
            settings=settings,
            progress=cb,
            should_stop=should_stop,
            content_filter=content_filter,
        )
        _progress_push(search_id, summary.status, summary.found, summary.accepted, summary.scanned,
                       summary.detail or summary.status)
        # Mirror the engine result into the MAIN searches row so history /
        # dashboard / status endpoints see a consistent lifecycle.
        _sync_main_search_row(search_id, summary, user_id=user_id, leads_needed=leads_needed)
    except Exception as exc:
        log.exception("Hyperagent search worker crashed for %s", search_id)
        try:
            store.update_search(search_id, status="failed", error=f"internal error: {exc}",
                                finished_at=datetime.now(UTC))
        except Exception:
            log.exception("Could not mark search %s failed", search_id)
        _progress_push(search_id, "failed", 0, 0, 0, f"internal error: {exc}")
        try:
            _sync_main_search_row(search_id, None, user_id=user_id, error=f"internal error: {exc}",
                                  leads_needed=leads_needed)
        except Exception:
            log.exception("Could not sync main search row %s", search_id)
    finally:
        _clear_cancel(search_id)


def _sync_main_search_row(search_id: str, summary, user_id: str,
                          error: str | None = None,
                          leads_needed: int | None = None) -> None:
    """Copy the Hyperagent engine outcome into the main `searches` row.

    The engine persists to ha_searches; the main app reads searches for
    history, the lead manager and (partly) status. Keep both in sync so a
    finished LinkedIn run never shows as 'queued' in the UI.
    """
    from app.database import get_supabase_admin

    supabase = get_supabase_admin()

    # A user cancel flips the main row to 'cancelled' while the engine thread
    # is still finishing — never resurrect it to completed/failed.
    try:
        cur = (
            supabase.table("searches")
            .select("status,user_id")
            .eq("id", search_id)
            .limit(1)
            .execute()
        )
        current_status = (cur.data or [{}])[0].get("status") if cur.data else None
    except Exception:
        current_status = None
    if current_status == "cancelled":
        log.info("Main searches row %s already cancelled — skipping sync, settling quota", search_id)
        _settle_hyperagent_quota(search_id, user_id)
        return

    status = summary.status if summary else "failed"
    # Engine vocabulary -> main searches CHECK constraint vocabulary.
    if status == "running":
        status = "scraping"
    elif status == "no_results":
        status = "completed"
    elif status == "cancelled":
        status = "cancelled"
    payload: dict[str, Any] = {
        "status": status,
        "completed_at": datetime.now(UTC).isoformat(),
        "error_message": error,
    }
    if summary is not None and status != "cancelled":
        payload.update({
            "message": _friendly_summary_message(summary, leads_needed=leads_needed),
            "total_results": int(summary.found),
            "hot_leads": int(summary.accepted),
            "warm_leads": int(summary.scanned),
            "skipped": max(0, int(summary.scanned) - int(summary.accepted)),
            "progress_percent": 100 if status == "completed" else 95,
        })
    elif status == "cancelled":
        payload.update({"message": "Search cancelled by user", "progress_percent": 0})
    # The store wrapper may have dropped rows that did not match the requested
    # content type — reflect the ACTUAL saved count, not the engine's.
    saved: int | None = None
    for _attempt in range(3):
        try:
            count = (
                supabase.table("ha_leads")
                .select("id", count="exact")
                .eq("search_id", search_id)
                .execute()
            )
            saved = int(count.count or 0)
            break
        except Exception:
            import time as _t
            _t.sleep(1.0)
    if saved is not None and saved >= 0 and status != "cancelled":
        payload["hot_leads"] = saved
        if summary is not None:
            payload["message"] = _friendly_summary_message(
                summary, leads_needed=leads_needed, actual_accepted=saved)
    # Transient Supabase disconnects happen under load — retry the write.
    last_exc: Exception | None = None
    for _attempt in range(3):
        try:
            supabase.table("searches").update(payload).eq("id", search_id).execute()
            log.info("Main searches row synced for %s (status=%s)", search_id, status)
            break
        except Exception as exc:
            last_exc = exc
            import time as _t
            _t.sleep(1.5)
    else:
        log.warning("Could not sync main searches row for %s after retries: %s", search_id, last_exc)

    # Charge the LinkedIn monthly quota against what was actually saved.
    _settle_hyperagent_quota(search_id, user_id, saved if saved is not None else (summary.accepted if summary else 0))


def _settle_hyperagent_quota(search_id: str, user_id: str, saved: int = 0) -> None:
    """Idempotent LinkedIn monthly-quota settlement (runs in the worker thread,
    so it uses the synchronous settle path)."""
    try:
        from app.database import get_supabase_admin
        from app.services.usage import settle_search_quota_sync
        settle_search_quota_sync(get_supabase_admin(), search_id, user_id, saved)
    except Exception as exc:
        log.warning("Hyperagent quota settle failed for %s: %s", search_id, exc)


def _friendly_summary_message(summary, leads_needed: int | None = None,
                              actual_accepted: int | None = None) -> str:
    """Human-facing completion message (no internal engine jargon)."""
    accepted = int(actual_accepted if actual_accepted is not None else summary.accepted)
    wanted = int(leads_needed or 0)
    if summary.status == "failed":
        return "We hit a temporary issue while searching. Please try again in a few minutes."
    if summary.status == "completed":
        if accepted > 0:
            return (
                f"Done! {accepted} qualified lead{'s' if accepted != 1 else ''} found"
                + (f" of {wanted} requested." if wanted and accepted < wanted else " and saved.")
            )
        return (
            "We searched LinkedIn but couldn't find qualified leads for this yet. "
            "Try a different wording, a broader description, or a different location."
        )
    if summary.status == "no_results":
        return (
            "We searched but found no matching posts. Try a different wording or "
            "a broader description."
        )
    return "Search finished."


def run_hyperagent_pipeline(
    search_id: str,
    user_id: str,
    service: str,
    country: str = "",
    lead_type: str = "need_freelancer",
    time_window: str = "7d",
    leads_needed: int = 10,
) -> None:
    """Entry point called from the search router. Spawns a background thread."""
    settings = _ha_settings()
    store = HaSupabaseStore(settings.supabase_url, settings.supabase_service_role_key)

    # Seed the ha_searches row with id == main searches.id (engine looks it up
    # by that id, so both tables share one id for traceability).
    try:
        store.create_search(
            service=service,
            country=country,
            lead_type=lead_type,
            time_window=time_window,
            leads_needed=leads_needed,
            search_id=search_id,
        )
        log.info("ha_searches row created for %s", search_id)
    except Exception as exc:
        log.warning("Could not pre-create ha_searches row (id=%s): %s", search_id, exc)

    thread = threading.Thread(
        target=_run_search_worker,
        args=(search_id, user_id, settings, store, leads_needed, lead_type, country),
        daemon=True,
        name=f"hyperagent-{search_id[:8]}",
    )
    thread.start()
    log.info("Hyperagent search %s started (queued or running): service=%r country=%r type=%s window=%s need=%d",
             search_id, service, country, lead_type, time_window, leads_needed)
