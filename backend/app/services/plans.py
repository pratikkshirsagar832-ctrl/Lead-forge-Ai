"""
Hyperclients — Plan Resolution Service

Single source of truth for "what plan does this user effectively have".

Team members (created by Pro/Agency owners) carry a registry marker in
their user_subscriptions row: razorpay_order_id = "team:{owner_uuid}:{username}".
Their EFFECTIVE plan is always resolved LIVE from the owner's current
subscription — so upgrades, renewals and downgrades propagate to the whole
team instantly, with no sync jobs.
"""

import logging
from datetime import date, datetime, timezone

from app.database import get_supabase_admin

logger = logging.getLogger(__name__)

TEAM_MARKER_PREFIX = "team:"
VALID_STATUSES = ("active", "trial")


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _row_is_active(row: dict) -> bool:
    """Active = status valid AND (no period_end OR period_end in future)."""
    if row.get("status") not in VALID_STATUSES:
        return False
    pe = _parse_dt(row.get("current_period_end"))
    if pe is None:
        # Trial rows may rely on trial_end instead
        te = _parse_dt(row.get("trial_end"))
        if te is not None:
            if te.tzinfo is None:
                te = te.replace(tzinfo=timezone.utc)
            return te >= datetime.now(timezone.utc)
        return True
    return pe > datetime.now(timezone.utc)


def get_latest_subscription_row(supabase, user_id: str) -> dict | None:
    resp = supabase.table("user_subscriptions") \
        .select("*") \
        .eq("user_id", user_id) \
        .order("created_at", desc=True) \
        .limit(10) \
        .execute()
    rows = resp.data or []
    if not rows:
        return None
    # Prefer an active row when several share the same created_at second
    # (a DB trigger also inserts a default free/trial row on signup).
    for r in rows:
        if _row_is_active(r):
            return r
    return rows[0]


def resolve_effective_subscription(supabase, user_id: str) -> dict:
    """Resolve the effective subscription for ANY user (owner or team member).

    Returns {plan_id, status, source_row, team_owner_id, username} — plan_id
    is ALWAYS the live owner plan for team members.
    """
    row = get_latest_subscription_row(supabase, user_id)
    if not row:
        return {"plan_id": "free", "status": "trial", "team_owner_id": None, "username": None}

    marker = row.get("razorpay_order_id") or ""
    if marker.startswith(TEAM_MARKER_PREFIX):
        parts = marker.split(":", 2)
        if len(parts) == 3:
            owner_id, username = parts[1], parts[2]
            owner_row = get_latest_subscription_row(supabase, owner_id)
            if owner_row and _row_is_active(owner_row):
                return {
                    "plan_id": owner_row.get("plan_id", "free"),
                    "status": "active",
                    "team_owner_id": owner_id,
                    "username": username,
                    "source_row": owner_row,
                }
            # Owner lapsed/downgraded below seats → member loses access
            return {"plan_id": "free", "status": "expired_team",
                    "team_owner_id": owner_id, "username": username}

    return {"plan_id": row.get("plan_id", "free"),
            "status": row.get("status", "trial") if _row_is_active(row) else "inactive",
            "team_owner_id": None, "username": None}


def get_plan_row(supabase, plan_id: str) -> dict:
    resp = supabase.table("plans").select("*").eq("id", plan_id).limit(1).execute()
    return resp.data[0] if resp.data else {}


def get_used_today(supabase, user_id: str) -> tuple[int, int]:
    today_str = date.today().isoformat()
    resp = supabase.table("daily_usage") \
        .select("searches_run, leads_generated") \
        .eq("user_id", user_id) \
        .eq("date", today_str) \
        .execute()
    used = resp.data[0] if resp.data else {}
    return (used.get("searches_run", 0) or 0, used.get("leads_generated", 0) or 0)


def remaining_leads_today(supabase, user_id: str) -> int:
    """Python-side replacement for the get_remaining_leads RPC —
    team-aware: members draw from their OWNER's plan quota scale."""
    eff = resolve_effective_subscription(supabase, user_id)
    plan = get_plan_row(supabase, eff["plan_id"])
    _, used_leads = get_used_today(supabase, user_id)
    return max(0, (plan.get("leads_per_day", 30) or 30) - used_leads)
