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
        .select("id,user_id,plan_id,status,current_period_start,current_period_end,trial_end,razorpay_order_id,created_at") \
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

    # Free is perpetual: the monthly quota (3 searches/mo) is the gate, not a
    # 1-day trial clock. Without this, users past trial_end get "Subscription
    # is not active" with 0 searches used and see the upgrade modal forever.
    if (row.get("plan_id") or "free") == "free" and not (row.get("razorpay_order_id") or "").startswith(TEAM_MARKER_PREFIX):
        return {"plan_id": "free", "status": "active", "team_owner_id": None, "username": None,
                "source_row": row}

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


def quota_owner_id(effective: dict, user_id: str) -> str:
    """Quota pool owner: team members draw from their owner's pool.

    Without this each team seat gets a full plan's daily/monthly allowance
    (quota multiplied by seats). Owners use their own id.
    """
    return effective.get("team_owner_id") or user_id


def get_plan_row(supabase, plan_id: str) -> dict:
    try:
        resp = supabase.table("plans").select("id,name,leads_per_day,searches_per_day,searches_per_month,leads_per_month,ai_calls_monthly,gmb_leads_monthly,linkedin_hq_leads_monthly,billing_cycle_days").eq("id", plan_id).limit(1).execute()
        return resp.data[0] if resp.data else {}
    except Exception as exc:
        # Partial schema (e.g. live DB missing billing_cycle_days): retry
        # without the newer columns instead of failing every caller.
        logger.debug("get_plan_row column fallback (%s)", exc)
        resp = supabase.table("plans").select("*").eq("id", plan_id).limit(1).execute()
        return resp.data[0] if resp.data else {}


def get_monthly_limit(plan: dict, key: str, legacy_key: str, default: int) -> int:
    """Monthly cap with fallback to legacy daily column (pre-v16 rows)."""
    if key in plan and plan.get(key) is not None:
        try:
            return max(0, int(plan.get(key) or 0))
        except (TypeError, ValueError):
            pass
    try:
        return max(0, int(plan.get(legacy_key, default) or default))
    except (TypeError, ValueError):
        return default


def get_used_today(supabase, user_id: str) -> tuple[int, int]:
    today_str = datetime.now(timezone.utc).date().isoformat()
    resp = supabase.table("daily_usage") \
        .select("searches_run, leads_generated") \
        .eq("user_id", user_id) \
        .eq("date", today_str) \
        .execute()
    used = (resp.data or [{}])[0] or {}
    return (used.get("searches_run", 0) or 0, used.get("leads_generated", 0) or 0)


def get_monthly_searches_used(supabase, user_id: str) -> int:
    """Count searches created for this user in the CURRENT calendar month.

    The search allowance resets on the 1st of the month (not daily), so the
    quota is measured against `searches.created_at >= month start`.
    """
    month_start = datetime.now(timezone.utc).replace(day=1)
    resp = supabase.table("searches") \
        .select("id", count="exact") \
        .eq("user_id", user_id) \
        .gte("created_at", month_start.isoformat()) \
        .execute()
    return int(resp.count or 0)


def remaining_leads_today(supabase, user_id: str) -> int:
    """Monthly generic lead allowance (v16): team-aware, owner pool."""
    eff = resolve_effective_subscription(supabase, user_id)
    plan = get_plan_row(supabase, eff["plan_id"])
    quota_user = quota_owner_id(eff, user_id)
    limit = get_monthly_limit(plan, "leads_per_month", "leads_per_day", 30)
    used = get_monthly_counters(supabase, quota_user)
    return max(0, limit - int(used.get("leads_used", 0) or 0))


def get_monthly_counters(supabase, user_id: str) -> dict:
    """searches_used / ai_calls_used / generic leads used this calendar month."""
    month_str = datetime.now(timezone.utc).replace(day=1).date().isoformat()
    try:
        resp = supabase.table("monthly_usage") \
            .select("searches_used,ai_calls_used,linkedin_hq_generated,gmb_generated") \
            .eq("user_id", user_id).eq("usage_month", month_str).limit(1).execute()
        row = (resp.data or [{}])[0] or {}
        return {
            "searches_used": int(row.get("searches_used", 0) or 0),
            "ai_used": int(row.get("ai_calls_used", 0) or 0),
            "leads_used": int(row.get("linkedin_hq_generated", 0) or 0) + int(row.get("gmb_generated", 0) or 0),
        }
    except Exception:
        return {"searches_used": 0, "ai_used": 0, "leads_used": 0}


def build_subscription_summary(supabase, user_id: str) -> dict:
    """Everything the UI shows about a user's plan and usage, in ONE place.

    Used by /api/auth/me and /api/subscriptions/current (blocking - call via
    asyncio.to_thread). Team members see their OWNER's live plan and shared
    quota pool; reserved (in-flight) leads count as used; the free plan is
    always active (its monthly quota is the gate, not a trial clock).
    """
    eff = resolve_effective_subscription(supabase, user_id)
    team_seat = eff.get("team_owner_id") is not None
    source_row = eff.get("source_row") or get_latest_subscription_row(supabase, user_id) or {}

    if eff["status"] == "expired_team":
        # Owner lapsed / downgraded below seats: the seat is locked.
        return {
            "plan_id": "free", "plan_name": "Free", "status": "inactive",
            "searches_per_month": 0, "searches_per_day": 0, "leads_per_month": 0, "leads_per_day": 0,
            "ai_calls_monthly": 0, "remaining_searches": 0, "remaining_leads": 0, "searches_used": 0,
            "ai_used": 0, "ai_remaining": 0, "linkedin_hq_leads_monthly": 0, "gmb_leads_monthly": 0,
            "linkedin_hq_leads_used": 0, "gmb_leads_used": 0, "linkedin_hq_leads_remaining": 0,
            "gmb_leads_remaining": 0, "current_period_start": None, "current_period_end": None,
            "trial_end": None, "is_trial_expired": True, "is_team_seat": True,
        }

    plan_id = eff["plan_id"]
    plan = get_plan_row(supabase, plan_id)
    quota_user = quota_owner_id(eff, user_id)
    month = datetime.now(timezone.utc).replace(day=1).date().isoformat()
    try:
        resp = supabase.table("monthly_usage").select("*").eq("user_id", quota_user) \
            .eq("usage_month", month).limit(1).execute()
        usage = (resp.data or [{}])[0] or {}
    except Exception:  # noqa: BLE001 - table missing on very old schemas
        usage = {}

    def n(key: str) -> int:
        try:
            return int(usage.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    searches_limit = get_monthly_limit(plan, "searches_per_month", "searches_per_day", 3)
    leads_limit = get_monthly_limit(plan, "leads_per_month", "leads_per_day", 30)
    ai_limit = get_monthly_limit(plan, "ai_calls_monthly", "ai_calls", 5)
    li_limit = int(plan.get("linkedin_hq_leads_monthly", 0) or 0)
    gmb_limit = int(plan.get("gmb_leads_monthly", 0) or 0)
    li_remaining = max(0, li_limit - n("linkedin_hq_generated") - n("linkedin_hq_reserved"))
    gmb_remaining = max(0, gmb_limit - n("gmb_generated") - n("gmb_reserved"))
    searches_used = n("searches_used")
    ai_used = n("ai_calls_used")
    status = eff["status"]
    is_trial_expired = status == "inactive" and (source_row.get("status") == "trial")

    return {
        "plan_id": plan_id,
        "plan_name": plan.get("name", plan_id.title() if plan_id else "Free"),
        "status": status,
        "searches_per_month": searches_limit,
        "searches_per_day": searches_limit,  # compat
        "leads_per_month": leads_limit,
        "leads_per_day": leads_limit,  # compat
        "ai_calls_monthly": ai_limit,
        "remaining_searches": max(0, searches_limit - searches_used),
        "searches_used": searches_used,
        "ai_used": ai_used,
        "ai_remaining": max(0, ai_limit - ai_used),
        "remaining_leads": li_remaining + gmb_remaining,
        "linkedin_hq_leads_monthly": li_limit,
        "gmb_leads_monthly": gmb_limit,
        "linkedin_hq_leads_used": n("linkedin_hq_generated"),
        "gmb_leads_used": n("gmb_generated"),
        "linkedin_hq_leads_remaining": li_remaining,
        "gmb_leads_remaining": gmb_remaining,
        "current_period_start": source_row.get("current_period_start"),
        "current_period_end": source_row.get("current_period_end"),
        "trial_end": source_row.get("trial_end"),
        "is_trial_expired": is_trial_expired,
        "is_team_seat": team_seat,
    }
