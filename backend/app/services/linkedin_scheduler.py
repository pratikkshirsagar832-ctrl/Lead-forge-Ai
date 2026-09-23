"""LinkedIn Studio background scheduler (LinkedIn has no native scheduling).

Started from the FastAPI lifespan. Every LINKEDIN_SCHEDULER_INTERVAL_S:
  1. claim due posts atomically (claim_due_linkedin_posts: FOR UPDATE SKIP
     LOCKED -> a post is never published twice) and publish them;
  2. at most hourly per user, the AUTOPILOT planner fills upcoming posting
     slots with DeepSeek-written posts - as drafts for approval, or scheduled
     directly when the user opted into auto-approve.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.services import linkedin_studio as studio

logger = logging.getLogger(__name__)

PLAN_EVERY = timedelta(hours=1)
SLOT_TOLERANCE = timedelta(minutes=45)
MAX_NEW_PER_RUN = 5


def publish_due(supabase, limit: int = 10) -> int:
    rows = supabase.rpc("claim_due_linkedin_posts", {"p_limit": limit}).execute().data or []
    for post in rows:
        try:
            studio.publish(supabase, post)
        except Exception:  # noqa: BLE001 - one post must never stop the loop
            logger.exception("Scheduler: publishing post %s crashed", post.get("id"))
            supabase.table("linkedin_posts").update({"status": "failed", "error": "Unexpected error"}) \
                .eq("id", post["id"]).eq("status", "publishing").execute()
    return len(rows)


def upcoming_slots(cfg: dict[str, Any], now: datetime) -> list[datetime]:
    """UTC datetimes of the user's posting slots within the lookahead window."""
    try:
        tz = ZoneInfo(cfg.get("timezone") or "UTC")
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    days = int(cfg.get("lookahead_days") or 7)
    local_now = now.astimezone(tz)
    out = []
    for d in range(days + 1):
        day = (local_now + timedelta(days=d)).date()
        for slot in cfg.get("slots") or []:
            try:
                if int(slot["dow"]) != day.weekday():
                    continue
                hh, mm = (int(x) for x in str(slot["time"]).split(":")[:2])
            except (KeyError, ValueError, TypeError):
                continue
            at = datetime.combine(day, time(hh, mm), tzinfo=tz).astimezone(timezone.utc)
            if at > now + timedelta(minutes=10):
                out.append(at)
    return sorted(out)


def plan_autopilot(supabase, cfg: dict[str, Any], now: datetime | None = None) -> int:
    """Fill empty slots for one user. Returns the number of posts created."""
    from app.services import linkedin_writer

    now = now or datetime.now(timezone.utc)
    user_id = cfg["user_id"]
    if not cfg.get("enabled") or not cfg.get("account_id"):
        return 0
    info = studio.plan_info(supabase, user_id)
    if not info["enabled"] or info["remaining"] <= 0:
        return 0
    slots = upcoming_slots(cfg, now)
    if not slots:
        return 0
    existing = (supabase.table("linkedin_posts").select("scheduled_at,commentary")
                .eq("user_id", user_id).in_("status", ["draft", "scheduled", "publishing", "published"])
                .gte("scheduled_at", (now - SLOT_TOLERANCE).isoformat()).execute().data or [])
    taken = [studio._parse(r.get("scheduled_at")) for r in existing if r.get("scheduled_at")]
    free = [s for s in slots if not any(t and abs(t - s) <= SLOT_TOLERANCE for t in taken)]
    free = free[: min(MAX_NEW_PER_RUN, info["remaining"])]
    if not free:
        return 0
    recent = (supabase.table("linkedin_posts").select("commentary").eq("user_id", user_id)
              .order("created_at", desc=True).limit(15).execute().data or [])
    posts = linkedin_writer.plan_posts(
        list(cfg.get("pillars") or []), len(free), audience=cfg.get("audience"),
        voice_profile=cfg.get("voice_profile"),
        avoid=[(r.get("commentary") or "")[:120] for r in recent])
    status = "scheduled" if cfg.get("auto_approve") and cfg.get("consent_at") else "draft"
    rows = [{
        "user_id": user_id, "account_id": cfg["account_id"], "status": status,
        "commentary": p["post"], "scheduled_at": slot.isoformat(), "source": "autopilot",
        "ai_meta": {"pillar": p.get("pillar"), "topic": p.get("topic")},
    } for slot, p in zip(free, posts)]
    if rows:
        supabase.table("linkedin_posts").insert(rows).execute()
    return len(rows)


def run_autopilot(supabase, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    cfgs = supabase.table("linkedin_autopilot").select("*").eq("enabled", True).execute().data or []
    created = 0
    for cfg in cfgs:
        last = studio._parse(cfg.get("last_planned_at"))
        if last and now - last < PLAN_EVERY:
            continue
        try:
            created += plan_autopilot(supabase, cfg, now)
        except Exception as exc:  # noqa: BLE001 - one user never blocks the rest
            logger.warning("Autopilot planning failed for %s: %s", cfg.get("user_id", "")[:8], exc)
        supabase.table("linkedin_autopilot").update({"last_planned_at": now.isoformat()}) \
            .eq("user_id", cfg["user_id"]).execute()
    return created


async def scheduler_loop(stop: asyncio.Event) -> None:
    from app.database import get_supabase_admin

    settings = get_settings()
    interval = max(10, int(settings.linkedin_scheduler_interval_s))
    logger.info("LinkedIn scheduler started (every %ss)", interval)
    ticks = 0
    while not stop.is_set():
        try:
            supabase = get_supabase_admin()
            await asyncio.to_thread(publish_due, supabase)
            if ticks % max(1, 300 // interval) == 0:  # autopilot check ~every 5 min
                await asyncio.to_thread(run_autopilot, supabase)
        except Exception as exc:  # noqa: BLE001 - e.g. migration v21 not applied yet
            logger.debug("LinkedIn scheduler tick skipped: %s", exc)
        ticks += 1
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
