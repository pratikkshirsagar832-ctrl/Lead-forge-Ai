import logging
import re
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Body

from app.config import get_settings
from app.database import get_supabase_admin
from app.middleware.auth_middleware import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Auth"])

# Team seats per plan — Free/Solo have none.
PLAN_SEATS = {"pro": 2, "agency": 10}
MEMBER_EMAIL_DOMAIN = "members.hyperclients.online"
USERNAME_RE = re.compile(r"^[a-z0-9_]{3,20}$")

# Lightweight in-process throttles (per-process; shared store would need Redis).
# team-resolve is public by design (username->email) — bound enumeration.
# team create is owner-authed but still bound to avoid seat-spam.
import time as _time

_RESOLVE_WINDOW_S = 60
_RESOLVE_MAX = 30
_resolve_hits: dict[str, list[float]] = {}
_TEAM_CREATE_WINDOW_S = 60
_TEAM_CREATE_MAX = 10
_team_create_hits: dict[str, list[float]] = {}


def _throttled(bucket: dict[str, list[float]], key: str, window_s: int, max_hits: int) -> bool:
    now = _time.time()
    hits = [t for t in bucket.get(key, []) if now - t < window_s]
    if len(hits) >= max_hits:
        bucket[key] = hits
        return True
    hits.append(now)
    bucket[key] = hits
    return False


def _get_owner_plan(supabase, user_id: str) -> tuple[str, str]:
    from app.services.plans import resolve_effective_subscription
    eff = resolve_effective_subscription(supabase, user_id)
    return eff["plan_id"], eff["status"]


@router.get("/team")
async def get_team(current_user: dict = Depends(get_current_user)):
    supabase = get_supabase_admin()
    plan_id, _status = _get_owner_plan(supabase, current_user["id"])
    seats_allowed = PLAN_SEATS.get(plan_id, 0)

    rows = supabase.table("user_subscriptions") \
        .select("user_id, razorpay_order_id, created_at") \
        .like("razorpay_order_id", f"team:{current_user['id']}:%") \
        .order("created_at") \
        .execute()

    members = []
    for r in (rows.data or []):
        parts = (r.get("razorpay_order_id") or "").split(":", 2)
        if len(parts) == 3:
            members.append({
                "id": r["user_id"],
                "username": parts[2],
                "email": f"{parts[2]}@{MEMBER_EMAIL_DOMAIN}",
                "created_at": r.get("created_at"),
            })

    return {
        "plan_id": plan_id,
        "seats_allowed": seats_allowed,
        "seats_used": len(members),
        "members": members,
    }


@router.post("/team")
async def add_team_member(
    payload: dict = Body(...),
    current_user: dict = Depends(get_current_user),
):
    username = (payload.get("username") or "").strip().lower()
    password = payload.get("password") or ""

    if not USERNAME_RE.match(username):
        raise HTTPException(status_code=400, detail={
            "message": "Username must be 3-20 chars: lowercase letters, numbers, underscores",
        })
    if len(password) < 6 or len(password) > 128:
        raise HTTPException(status_code=400, detail={"message": "Password must be 6-128 characters"})
    if _throttled(_team_create_hits, current_user["id"], _TEAM_CREATE_WINDOW_S, _TEAM_CREATE_MAX):
        raise HTTPException(status_code=429, detail={"message": "Too many team invites. Try again shortly."})

    supabase = get_supabase_admin()
    owner_id = current_user["id"]
    plan_id, status = _get_owner_plan(supabase, owner_id)

    if status not in ("active", "trial"):
        raise HTTPException(status_code=403, detail={"message": "Subscription is not active"})

    seats_allowed = PLAN_SEATS.get(plan_id, 0)
    if seats_allowed == 0:
        raise HTTPException(status_code=403, detail={
            "message": "Team seats are available on Pro and Agency plans only",
            "upgrade_url": "/pricing",
        })

    count_resp = supabase.table("user_subscriptions") \
        .select("user_id", count="exact") \
        .like("razorpay_order_id", f"team:{owner_id}:%") \
        .execute()
    if (count_resp.count or 0) >= seats_allowed:
        raise HTTPException(status_code=400, detail={
            "message": f"All {seats_allowed} seats of your plan are in use",
        })

    settings = get_settings()
    member_email = f"{username}@{MEMBER_EMAIL_DOMAIN}"
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{settings.supabase_url}/auth/v1/admin/users",
            headers={
                "apikey": settings.supabase_service_role_key,
                "Authorization": f"Bearer {settings.supabase_service_role_key}",
                "Content-Type": "application/json",
            },
            json={
                "email": member_email,
                "password": password,
                "email_confirm": True,
                "user_metadata": {
                    "role": "team_member",
                    "username": username,
                    "team_owner": owner_id,
                },
            },
        )
    if resp.status_code == 422:
        raise HTTPException(status_code=409, detail={"message": "Username already taken"})
    if resp.status_code not in (200, 201):
        logger.error(f"Team member auth create failed: {resp.status_code} {resp.text[:300]}")
        raise HTTPException(status_code=500, detail={"message": "Failed to create team account"})

    member_uid = (resp.json() or {}).get("id")
    if not member_uid:
        # Without an id the registry row below would be written with a NULL
        # user_id (a 500 after the auth user already existed).
        logger.error(f"Team member auth create returned no id: {resp.text[:300]}")
        raise HTTPException(status_code=500, detail={"message": "Failed to create team account"})

    # Mirror owner's plan onto the member + registry entry encoded in
    # razorpay_order_id (no DDL needed for a dedicated table).
    owner_sub = supabase.table("user_subscriptions") \
        .select("current_period_end") \
        .eq("user_id", owner_id) \
        .order("created_at", desc=True) \
        .limit(1) \
        .execute()
    period_end = owner_sub.data[0].get("current_period_end") if owner_sub.data else None

    try:
        supabase.table("user_subscriptions").insert({
            "user_id": member_uid,
            "plan_id": plan_id,
            "status": "active",
            "current_period_start": datetime.now(timezone.utc).isoformat(),
            "current_period_end": period_end,
            "razorpay_order_id": f"team:{owner_id}:{username}",
        }).execute()
    except Exception as reg_err:
        # The seat is unusable without its registry row (and the seat count
        # would be wrong forever) — delete the orphaned auth user and report.
        logger.error(f"Team member registry insert failed for {username}: {reg_err}")
        try:
            async with httpx.AsyncClient(timeout=20) as cleanup:
                await cleanup.delete(
                    f"{settings.supabase_url}/auth/v1/admin/users/{member_uid}",
                    headers={
                        "apikey": settings.supabase_service_role_key,
                        "Authorization": f"Bearer {settings.supabase_service_role_key}",
                    },
                )
        except Exception as cleanup_err:
            logger.error(
                f"Could not clean up orphaned team auth user {member_uid}: {cleanup_err}"
            )
        raise HTTPException(status_code=500, detail={"message": "Failed to create team account"})

    return {"id": member_uid, "username": username, "email": member_email}


@router.delete("/team/{member_id}")
async def remove_team_member(member_id: str, current_user: dict = Depends(get_current_user)):
    supabase = get_supabase_admin()
    owner_id = current_user["id"]

    rows = supabase.table("user_subscriptions") \
        .select("id") \
        .eq("user_id", member_id) \
        .like("razorpay_order_id", f"team:{owner_id}:%") \
        .order("created_at", desc=True) \
        .limit(1) \
        .execute()
    if not rows.data:
        raise HTTPException(status_code=404, detail={"message": "Team member not found"})
    registry_row_id = rows.data[0]["id"]

    settings = get_settings()
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.delete(
            f"{settings.supabase_url}/auth/v1/admin/users/{member_id}",
            headers={
                "apikey": settings.supabase_service_role_key,
                "Authorization": f"Bearer {settings.supabase_service_role_key}",
            },
        )
    if resp.status_code not in (200, 204):
        logger.warning(f"Team member auth delete returned {resp.status_code} — cleaning registry anyway")

    supabase.table("user_subscriptions").delete().eq("id", registry_row_id).execute()
    return {"ok": True}


@router.post("/team-resolve")
async def resolve_team_username(payload: dict = Body(...)):
    """Public: turn a team username into its login email so the standard
    Supabase password sign-in works without exposing synthetic emails."""
    # Throttle by a best-effort caller key to bound username enumeration.
    # No auth here by design; the bucket key is intentionally coarse.
    try:
        from fastapi import Request
    except Exception:
        Request = None  # type: ignore
    username = (payload.get("username") or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise HTTPException(status_code=400, detail={"message": "Invalid username format"})
    if _throttled(_resolve_hits, "global", _RESOLVE_WINDOW_S, _RESOLVE_MAX * 10):
        raise HTTPException(status_code=429, detail={"message": "Too many requests. Try again shortly."})
    return {"email": f"{username}@{MEMBER_EMAIL_DOMAIN}"}


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    supabase = get_supabase_admin()
    subscription = None

    # Monthly quotas (v16): searches / AI / generic leads reset on the 1st.
    # daily_usage is reporting-only now.
    from app.services.plans import (
        get_monthly_limit,
        get_monthly_counters,
        quota_owner_id,
    )
    try:
        from app.services.plans import resolve_effective_subscription as _eff
        _eff_row = _eff(supabase, current_user["id"])
        quota_user = quota_owner_id(_eff_row, current_user["id"])
    except Exception:
        quota_user = current_user["id"]
    month_str = datetime.now(timezone.utc).replace(day=1).date().isoformat()
    try:
        monthly = supabase.table("monthly_usage").select("*").eq("user_id", quota_user).eq("usage_month", month_str).limit(1).execute()
        mu = (monthly.data or [{}])[0] if monthly.data else {}
    except Exception:
        mu = {}
    used_searches = int(mu.get("searches_used", 0) or 0)
    used_ai = int(mu.get("ai_calls_used", 0) or 0)
    used_leads = 0  # computed per-plan below from monthly generated totals

    try:
        sub_resp = supabase.rpc(
            "get_user_subscription",
            {"p_user_id": current_user["id"]},
        ).execute()
        if sub_resp and sub_resp.data:
            subscription = sub_resp.data
            searches_per_month = int(subscription.get("searches_per_month") or subscription.get("searches_per_day", 3) or 3)
            leads_per_month = int(subscription.get("leads_per_month") or subscription.get("leads_per_day", 30) or 30)
            subscription["searches_per_month"] = searches_per_month
            subscription["searches_per_day"] = searches_per_month  # compat
            subscription["leads_per_month"] = leads_per_month
            subscription["leads_per_day"] = leads_per_month  # compat
            subscription["remaining_searches"] = max(0, searches_per_month - used_searches)
            subscription["remaining_leads"] = max(0, leads_per_month - used_leads)

            # Monthly usage
            month_str = datetime.now(timezone.utc).replace(day=1).date().isoformat()
            try:
                monthly = supabase.table("monthly_usage").select("*").eq("user_id", current_user["id"]).eq("usage_month", month_str).limit(1).execute()
                mu = (monthly.data or [{}])[0]
            except Exception:
                mu = {}
            plan_row = supabase.table("plans").select("linkedin_hq_leads_monthly,gmb_leads_monthly").eq("id", subscription.get("plan_id", "free")).limit(1).execute()
            plan_cols = (plan_row.data or [{}])[0] if plan_row.data else {}
            subscription["linkedin_hq_leads_monthly"] = int(plan_cols.get("linkedin_hq_leads_monthly", 0) or 0)
            subscription["gmb_leads_monthly"] = int(plan_cols.get("gmb_leads_monthly", 0) or 0)
            subscription["linkedin_hq_leads_used"] = int(mu.get("linkedin_hq_generated", 0) or 0)
            subscription["gmb_leads_used"] = int(mu.get("gmb_generated", 0) or 0)

        # Direct-table truth check: team members resolve their plan LIVE
        # from the owner's subscription (upgrades/renewals propagate instantly).
        try:
            from app.services.plans import get_plan_row, resolve_effective_subscription, get_used_today
            eff = resolve_effective_subscription(supabase, current_user["id"])

            if eff["status"] not in ("active", "trial"):
                # Owner lapsed/downgraded below seats → lock the seat down.
                if eff.get("team_owner_id") and (
                    not subscription or subscription.get("plan_id") != "free"
                ):
                    subscription = {
                        "plan_id": "free",
                        "plan_name": "Free",
                        "status": "inactive",
                        "searches_per_month": 0,
                        "searches_per_day": 0,
                        "leads_per_month": 0,
                        "leads_per_day": 0,
                        "remaining_searches": 0,
                        "remaining_leads": 0,
                        "current_period_start": None,
                        "current_period_end": None,
                        "trial_end": None,
                        "is_trial_expired": True,
                        "is_team_seat": True,
                    }
            elif not subscription or subscription.get("plan_id") != eff["plan_id"]:
                plan = get_plan_row(supabase, eff["plan_id"])
                quota_u = quota_owner_id(eff, current_user["id"])
                counters = get_monthly_counters(supabase, quota_u)
                s_limit = get_monthly_limit(plan, "searches_per_month", "searches_per_day", 3)
                l_limit = get_monthly_limit(plan, "leads_per_month", "leads_per_day", 30)
                subscription = {
                    "plan_id": eff["plan_id"],
                    "plan_name": plan.get("name", eff["plan_id"]),
                    "status": "active",
                    "searches_per_month": s_limit,
                    "searches_per_day": s_limit,
                    "leads_per_month": l_limit,
                    "leads_per_day": l_limit,
                    "remaining_searches": max(0, s_limit - counters["searches_used"]),
                    "remaining_leads": max(0, l_limit - counters["leads_used"]),
                    "linkedin_hq_leads_monthly": int(plan.get("linkedin_hq_leads_monthly", 0) or 0),
                    "gmb_leads_monthly": int(plan.get("gmb_leads_monthly", 0) or 0),
                    "linkedin_hq_leads_used": 0,
                    "gmb_leads_used": 0,
                    "current_period_start": None,
                    "current_period_end": (eff.get("source_row") or {}).get("current_period_end"),
                    "trial_end": None,
                    "is_trial_expired": False,
                    "is_team_seat": eff.get("team_owner_id") is not None,
                }
                # Monthly usage
                month_str = datetime.now(timezone.utc).replace(day=1).date().isoformat()
                try:
                    monthly = supabase.table("monthly_usage").select("*").eq("user_id", current_user["id"]).eq("usage_month", month_str).limit(1).execute()
                    mu = (monthly.data or [{}])[0]
                    subscription["linkedin_hq_leads_used"] = int(mu.get("linkedin_hq_generated", 0) or 0)
                    subscription["gmb_leads_used"] = int(mu.get("gmb_generated", 0) or 0)
                except Exception:
                    pass
        except Exception as tbl_err:
            logger.warning(f"Effective-plan resolution failed: {tbl_err}")
    except Exception as e:
        logger.warning(f"RPC get_user_subscription failed: {e}")

    if not subscription:
        try:
            sub_resp = supabase.table("user_subscriptions") \
                .select("*") \
                .eq("user_id", current_user["id"]) \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute()

            if sub_resp.data and len(sub_resp.data) > 0:
                sub = sub_resp.data[0]
                plan_id = sub.get("plan_id", "free")

                plan_resp = supabase.table("plans") \
                    .select("*") \
                    .eq("id", plan_id) \
                    .limit(1) \
                    .execute()

                plan = plan_resp.data[0] if plan_resp.data and len(plan_resp.data) > 0 else {}
                s_limit = get_monthly_limit(plan, "searches_per_month", "searches_per_day", 3)
                l_limit = get_monthly_limit(plan, "leads_per_month", "leads_per_day", 30)

                subscription = {
                    "plan_id": plan_id,
                    "plan_name": plan.get("name", "Free"),
                    "status": sub.get("status", "active"),
                    "searches_per_month": s_limit,
                    "searches_per_day": s_limit,
                    "leads_per_month": l_limit,
                    "leads_per_day": l_limit,
                    "remaining_searches": max(0, s_limit - used_searches),
                    "remaining_leads": max(0, l_limit - used_leads),
                    "linkedin_hq_leads_monthly": int(plan.get("linkedin_hq_leads_monthly", 0) or 0),
                    "gmb_leads_monthly": int(plan.get("gmb_leads_monthly", 0) or 0),
                    "linkedin_hq_leads_used": 0,
                    "gmb_leads_used": 0,
                    "current_period_start": sub.get("current_period_start"),
                    "current_period_end": sub.get("current_period_end"),
                    "trial_end": sub.get("trial_end"),
                    "is_trial_expired": sub.get("is_trial_expired", False),
                }
                month_str = datetime.now(timezone.utc).replace(day=1).date().isoformat()
                try:
                    monthly = supabase.table("monthly_usage").select("*").eq("user_id", current_user["id"]).eq("usage_month", month_str).limit(1).execute()
                    mu = (monthly.data or [{}])[0]
                    subscription["linkedin_hq_leads_used"] = int(mu.get("linkedin_hq_generated", 0) or 0)
                    subscription["gmb_leads_used"] = int(mu.get("gmb_generated", 0) or 0)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Failed to fetch subscription directly: {e}")

    # Lead quota is MONTHLY (the enforced cap comes from monthly_usage
    # reservations). The daily `remaining_leads` above reads daily_usage,
    # which is never incremented for leads — so it always showed the full cap
    # and appeared to "reset daily". Override with the true monthly remaining
    # per source so it resets on the 1st of the month, not every day.
    if subscription:
        try:
            month_str = datetime.now(timezone.utc).replace(day=1).date().isoformat()
            monthly = supabase.table("monthly_usage").select("*").eq("user_id", current_user["id"]).eq("usage_month", month_str).limit(1).execute()
            mu = (monthly.data or [{}])[0] if monthly.data else {}
        except Exception:
            mu = {}
        try:
            from app.services.plans import get_plan_row
            plan = get_plan_row(supabase, subscription.get("plan_id", "free"))
        except Exception:
            plan = {}
        li_monthly = int(plan.get("linkedin_hq_leads_monthly", 0) or 0)
        gmb_monthly = int(plan.get("gmb_leads_monthly", 0) or 0)
        li_used = int(mu.get("linkedin_hq_generated", 0) or 0)
        gmb_used = int(mu.get("gmb_generated", 0) or 0)
        li_remaining = max(0, li_monthly - li_used)
        gmb_remaining = max(0, gmb_monthly - gmb_used)
        subscription["remaining_leads"] = li_remaining + gmb_remaining
        subscription["linkedin_hq_leads_remaining"] = li_remaining
        subscription["gmb_leads_remaining"] = gmb_remaining
        subscription["linkedin_hq_leads_monthly"] = li_monthly
        subscription["gmb_leads_monthly"] = gmb_monthly

        # Searches + generic leads reset MONTHLY (v16, on the 1st).
        _sub_limit = int(subscription.get("searches_per_month") or subscription.get("searches_per_day", 3) or 3)
        subscription["remaining_searches"] = max(0, _sub_limit - used_searches)
        subscription["searches_used"] = used_searches
        subscription["ai_used"] = used_ai

    return {
        "id": current_user["id"],
        "email": current_user["email"],
        "name": current_user["name"],
        "subscription": subscription,
    }
