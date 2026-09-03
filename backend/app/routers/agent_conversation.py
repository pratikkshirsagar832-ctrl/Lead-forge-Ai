"""
Hyperclients — HyperAgent Conversational Flow

The agent has a guided conversation:
  1. COOKIES: if no LinkedIn cookies are configured, the agent asks the user to
     export them (with a step-by-step guide) BEFORE anything else.
  2. SERVICE: "what service are you looking for?" (learned into memory)
  3. LEAD TYPE: "what type of lead?" — one of freelancer_needed / hiring / agency_wanted
  4. COUNTRY: "which country?" (or 'Any' / 'Global')
  5. COUNT: "how many leads?"
  6. RUNS: launches the browser agent, saves qualified leads to the same `leads` table.

The agent asks ONE question at a time and stores partial state per user, so the
conversation survives refresh. It re-prompts for cookies when they expire.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

import logging
logger = logging.getLogger(__name__)

from app.database import get_supabase_admin
from app.middleware.auth_middleware import get_current_user
from app.services import hyperagent_memory as mem

router = APIRouter(prefix="/api/agent", tags=["Agent"])

AGENT_SOURCE = "hyper_agent"
LEAD_TYPE_CHOICES = {
    "freelancer_needed": "Freelancer needed – a company looking for an independent contractor",
    "hiring": "Hiring – a company posting a job for a role",
    "agency_wanted": "Agency wanted – a company seeking an agency partner",
}
COUNT_DEFAULT = 10
COUNT_MIN, COUNT_MAX = 1, 50


# ── Cookie guide (shown to the user when no/expired cookies) ────────────────
COOKIE_GUIDE = {
    "title": "Connect LinkedIn",
    "what": "The agent browses LinkedIn as YOU so it can read posts that are hidden from guests.",
    "steps": [
        "Install the Cookie-Editor extension (Chrome/Edge/Firefox).",
        "Log into LinkedIn in that browser (linkedin.com).",
        "Open the page, click the Cookie-Editor icon.",
        "Click Export → Export JSON. Copy the whole JSON array.",
        "Paste it into the cookie box below (or save as sessions/linkedin_cookies.json).",
    ],
    "why": "It stays on YOUR device / server. We never ask for your LinkedIn password.",
    "does": "Lets the agent read post & people search results, qualify leads, and save them for you.",
}


def _state_table():
    return get_supabase_admin().table("agent_chat_state")


def _load_state(user_id: str) -> dict:
    try:
        resp = _state_table().select("*").eq("user_id", user_id).limit(1).execute()
        rows = resp.data or []
        if rows:
            return rows[0]
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_chat_state load failed: %s", exc)
    return {}


def _save_state(user_id: str, state: dict) -> None:
    row = {
        "user_id": user_id,
        "step": state.get("step", "cookies"),
        "data": state.get("data", {}),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _state_table().upsert(row, on_conflict="user_id").execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_chat_state save failed: %s", exc)


def _reset_state(user_id: str) -> None:
    try:
        _state_table().delete().eq("user_id", user_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_chat_state reset failed: %s", exc)


def _agent_message(msg: str, *, next_step: str | None = None, options: list[str] | None = None,
                   guide: dict | None = None, done: bool = False, run: dict | None = None) -> dict:
    out = {"message": msg, "done": done}
    if next_step:
        out["next_step"] = next_step
    if options:
        out["options"] = options
    if guide:
        out["guide"] = guide
    if run:
        out["run"] = run
    # step the conversation forward.
    if next_step:
        out["step"] = next_step
    return out


# ── Step 1: cookies ─────────────────────────────────────────────────────────
def _cookies_step(user_id: str) -> dict:
    status = mem.cookie_status()
    if status.get("configured") and not status.get("expired"):
        # already connected -> skip to service
        state = _load_state(user_id)
        state["step"] = "service"
        _save_state(user_id, state)
        return _agent_message(
            "Great — your LinkedIn connection is active. What service are you looking for? "
            "e.g. `video editing`, `web development`, `SEO`.",
            next_step="service",
        )
    # ask for cookies (or re-ask when expired)
    state = _load_state(user_id)
    state["step"] = "cookies"
    _save_state(user_id, state)
    if status.get("expired"):
        msg = "Your LinkedIn session expired. Please re-export fresh cookies to continue."
    else:
        msg = "To find leads on LinkedIn, first let me connect your account."
    return _agent_message(msg, next_step="cookies", guide=COOKIE_GUIDE)


def _service_step(user_id: str, state: dict) -> dict:
    service = (state.get("data") or {}).get("service")
    if service:
        state["step"] = "lead_type"
        _save_state(user_id, state)
        return _agent_message(
            f'Got it — **{service}**. What type of lead are you hunting for?',
            next_step="lead_type",
            options=list(LEAD_TYPE_CHOICES.keys()),
        )
    return _agent_message("What service are you looking for?", next_step="service")


def _lead_type_step(user_id: str, state: dict) -> dict:
    lead_type = (state.get("data") or {}).get("lead_type")
    if lead_type:
        state["step"] = "country"
        _save_state(user_id, state)
        return _agent_message(
            "Which country should the leads be from? (Type a country, a region like `Europe`, or `Any`/`Global`.)",
            next_step="country",
        )
    return _agent_message(
        "What type of lead do you want? Choose one:", next_step="lead_type", options=list(LEAD_TYPE_CHOICES.values()),
    )


def _country_step(user_id: str, state: dict) -> dict:
    data = state.get("data") or {}
    country = data.get("country")
    if country is not None:
        state["step"] = "count"
        _save_state(user_id, state)
        return _agent_message(
            f"Perfect — {country}. How many leads do you want? (e.g. `10`, up to 50)",
            next_step="count",
        )
    return _agent_message(
        "Which country/region? (`Any` works too)", next_step="country",
    )


def _count_step(user_id: str, state: dict) -> dict:
    data = state.get("data") or {}
    count = data.get("count")
    if count:
        return _agent_message(
            f"Great — searching for up to **{count}** {data.get('lead_type')} leads for "
            f"**{data.get('service')}** in {data.get('country') or 'Any'}...",
            next_step="run",
        )
    return _agent_message("How many leads do you want? (1–50)", next_step="count")


# ── Public endpoint: current conversation state (for the UI to resume) ──────
@router.get("/chat")
async def get_agent_chat(current_user: dict = Depends(get_current_user)):
    """Return the agent's current step + cookie status, so the UI renders the
    right prompt (cookie guide vs. service question, etc.)."""
    status = mem.cookie_status()
    state = _load_state(current_user["id"])
    step = state.get("step", "cookies")
    return {"step": step, "cookie_status": status, "guide": COOKIE_GUIDE if step == "cookies" else None,
            "data": state.get("data", {})}


# ── Public endpoint: one message at a time ──────────────────────────────────
@router.post("/chat")
async def agent_chat(payload: dict, background_tasks: BackgroundTasks = BackgroundTasks(),
                     current_user: dict = Depends(get_current_user)):
    """Advance the agent conversation by one step."""
    user_id = current_user["id"]
    text = (payload.get("message") or "").strip()
    action = payload.get("action") or "next"  # 'next' | 'submit_cookies' | 'start' | 'reset'
    state = _load_state(user_id)
    data = state.get("data") or {}
    step = payload.get("step") or state.get("step") or "cookies"

    if action == "reset":
        _reset_state(user_id)
        return _cookies_step(user_id)

    # Cookies submission (from the UI cookie box).
    if action == "submit_cookies" or (step == "cookies" and text.startswith("{")):
        cookies_raw = payload.get("cookies_json") or text
        if cookies_raw.startswith("{"):
            from app.config import get_settings
            settings = get_settings()
            # Persist inline to the configured cookie source.
            _write_cookies_inline(cookies_raw)
            status = mem.cookie_status()
            if status.get("configured") and not status.get("expired"):
                # connected -> proceed to service
                state = _load_state(user_id)
                state["step"] = "service"
                _save_state(user_id, state)
                return _agent_message(
                    "LinkedIn connected. What service are you looking for?",
                    next_step="service",
                )
        # fall through to the cookie step again (invalid/expired cookies)
        return _agent_message(
            "I couldn't read those cookies. Please export a fresh JSON from Cookie-Editor "
            "and paste it (it should be a JSON array starting with `[`).",
            next_step="cookies", guide=COOKIE_GUIDE,
        )

    # Advance through available steps.
    if step in ("service",) or (step == "cookies" and mem.has_cookies()):
        data["service"] = text
        state["data"] = data
        state["step"] = "lead_type"
        _save_state(user_id, state)
        return _agent_message(
            f'Got it — **{text}**. What type of lead are you hunting for?',
            next_step="lead_type", options=list(LEAD_TYPE_CHOICES.values()),
        )

    if step == "lead_type":
        lead_type = _normalize_lead_type(text)
        if not lead_type:
            return _agent_message(
                "Please choose one of: freelancer needed, hiring, agency wanted.",
                next_step="lead_type", options=list(LEAD_TYPE_CHOICES.values()),
            )
        data["lead_type"] = lead_type
        state["data"] = data
        state["step"] = "country"
        _save_state(user_id, state)
        return _agent_message(
            "Which country should the leads be from? (e.g. `United States`, `India`, `Europe`, or `Any`)",
            next_step="country",
        )

    if step == "country":
        data["country"] = text
        state["data"] = data
        state["step"] = "count"
        _save_state(user_id, state)
        return _agent_message("How many leads do you want? (1–50)", next_step="count")

    if step == "count":
        try:
            count = max(COUNT_MIN, min(COUNT_MAX, int(text)))
        except ValueError:
            return _agent_message("Please enter a number between 1 and 50.", next_step="count")
        data["count"] = count
        state["data"] = data
        state["step"] = "run"
        _save_state(user_id, state)
        # Kick off the browser agent.
        run = _launch_run(user_id, data, background_tasks)
        _reset_state(user_id)
        return _agent_message(
            f"Launching the agent for **{count}** {LEAD_TYPE_CHOICES.get(data.get('lead_type'), data.get('lead_type'))} "
            f"lead(s) — {data.get('service')} in {data.get('country') or 'Any'}. I'll refresh with live results.",
            done=False, run=run,
        )

    # Default: restart from cookies check.
    return _cookies_step(user_id)


def _normalize_lead_type(text: str) -> str | None:
    t = (text or "").strip().lower().replace("_", " ")
    if any(k in t for k in ("freelanc", "buyer", "contractor", "independent")):
        return "freelancer_needed"
    if "hir" in t:
        return "hiring"
    if "agenc" in t:
        return "agency_wanted"
    return None


def _write_cookies_inline(cookies_json: str) -> None:
    """Persist cookies to the configured source so the scraper subprocess uses them."""
    from app.config import get_settings
    settings = get_settings()
    if settings.linkedin_cookies:
        # already inline; update file mirror
        pass
    # Write to the cookie file (default sessions/linkedin_cookies.json).
    from pathlib import Path
    path = Path(settings.linkedin_cookies_file)
    if not path.is_absolute():
        base = Path(__file__).resolve().parent.parent  # backend/
        path = base / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cookies_json, encoding="utf-8")
    # Also update the in-memory config setting so this request sees it.
    settings.linkedin_cookies = cookies_json


def _launch_run(user_id: str, data: dict, background_tasks: BackgroundTasks | None = None) -> dict:
    """Create a `searches` row (source=hyper_agent) and start the agent task."""
    from app.services.hyperagent_service import run_hyperagent_pipeline_fast
    supabase = get_supabase_admin()
    service = data.get("service", "")
    country = data.get("country", "")
    lead_type = data.get("lead_type", "freelancer_needed")
    count = int(data.get("count", COUNT_DEFAULT))
    try:
        resp = (
            supabase.table("searches")
            .insert({
                "user_id": user_id, "niche": service, "location": country or "LinkedIn",
                "source": AGENT_SOURCE, "status": "queued", "message": "Agent queued",
                "enrich_emails": True, "max_results": count, "lead_types": [lead_type],
                "quota_source": "linkedin", "reserved_leads": count,
            })
            .execute()
        )
        row = (resp.data or [{}])[0] if resp.data else {}
        run_id = row.get("id")
        if run_id and background_tasks is not None:
            background_tasks.add_task(
                run_hyperagent_pipeline_fast,
                search_id=run_id, user_id=user_id, query=service,
                enrich_emails=True, max_results=count, lead_types=[lead_type],
                location=country,
            )
        return {"id": run_id, "status": row.get("status", "queued")}
    except Exception as exc:  # noqa: BLE001
        logger.error("agent run creation failed: %s", exc)
        return {"id": None, "status": "failed", "error": str(exc)}
