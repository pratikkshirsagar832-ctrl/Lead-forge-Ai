import logging
import re
from datetime import date, datetime, timezone

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
    if len(password) < 6:
        raise HTTPException(status_code=400, detail={"message": "Password must be at least 6 characters"})

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

    member_uid = resp.json().get("id")

    # Mirror owner's plan onto the member + registry entry encoded in
    # razorpay_order_id (no DDL needed for a dedicated table).
    owner_sub = supabase.table("user_subscriptions") \
        .select("current_period_end") \
        .eq("user_id", owner_id) \
        .order("created_at", desc=True) \
        .limit(1) \
        .execute()
    period_end = owner_sub.data[0].get("current_period_end") if owner_sub.data else None

    supabase.table("user_subscriptions").insert({
        "user_id": member_uid,
        "plan_id": plan_id,
        "status": "active",
        "current_period_start": datetime.now(timezone.utc).isoformat(),
        "current_period_end": period_end,
        "razorpay_order_id": f"team:{owner_id}:{username}",
    }).execute()

    return {"id": member_uid, "username": username, "email": member_email}


@router.delete("/team/{member_id}")
async def remove_team_member(member_id: str, current_user: dict = Depends(get_current_user)):
    supabase = get_supabase_admin()
    owner_id = current_user["id"]

    rows = supabase.table("user_subscriptions") \
        .select("id") \
        .eq("user_id", member_id) \
        .like("razorpay_order_id", f"team:{owner_id}:%") \
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
    username = (payload.get("username") or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise HTTPException(status_code=400, detail={"message": "Invalid username format"})
    return {"email": f"{username}@{MEMBER_EMAIL_DOMAIN}"}


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    supabase = get_supabase_admin()
    subscription = None

    # Compute correct remaining counts from actual table state
    today_str = date.today().isoformat()
    usage_resp = supabase.table("daily_usage") \
        .select("searches_run, leads_generated") \
        .eq("user_id", current_user["id"]) \
        .eq("date", today_str) \
        .execute()
    used = usage_resp.data[0] if usage_resp.data and len(usage_resp.data) > 0 else {}
    used_searches = used.get("searches_run", 0) or 0
    used_leads = used.get("leads_generated", 0) or 0

    try:
        sub_resp = supabase.rpc(
            "get_user_subscription",
            {"p_user_id": current_user["id"]},
        ).execute()
        if sub_resp and sub_resp.data:
            subscription = sub_resp.data
            searches_per_day = subscription.get("searches_per_day", 3)
            leads_per_day = subscription.get("leads_per_day", 30)
            subscription["remaining_searches"] = max(0, searches_per_day - used_searches)
            subscription["remaining_leads"] = max(0, leads_per_day - used_leads)

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
                        "searches_per_day": 0,
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
                used_s, used_l = get_used_today(supabase, current_user["id"])
                subscription = {
                    "plan_id": eff["plan_id"],
                    "plan_name": plan.get("name", eff["plan_id"]),
                    "status": "active",
                    "searches_per_day": plan.get("searches_per_day", 3),
                    "leads_per_day": plan.get("leads_per_day", 30),
                    "remaining_searches": max(0, plan.get("searches_per_day", 3) - used_s),
                    "remaining_leads": max(0, plan.get("leads_per_day", 30) - used_l),
                    "current_period_start": None,
                    "current_period_end": (eff.get("source_row") or {}).get("current_period_end"),
                    "trial_end": None,
                    "is_trial_expired": False,
                    "is_team_seat": eff.get("team_owner_id") is not None,
                }
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
                today_str = date.today().isoformat()

                usage_resp = supabase.table("daily_usage") \
                    .select("searches_run, leads_generated") \
                    .eq("user_id", current_user["id"]) \
                    .eq("date", today_str) \
                    .execute()

                used = usage_resp.data[0] if usage_resp.data else {}
                searches_per_day = plan.get("searches_per_day", 1)
                leads_per_day = plan.get("leads_per_day", 10)

                subscription = {
                    "plan_id": plan_id,
                    "plan_name": plan.get("name", "Free"),
                    "status": sub.get("status", "active"),
                    "searches_per_day": searches_per_day,
                    "leads_per_day": leads_per_day,
                    "remaining_searches": max(0, searches_per_day - (used.get("searches_run", 0) or 0)),
                    "remaining_leads": max(0, leads_per_day - (used.get("leads_generated", 0) or 0)),
                    "current_period_start": sub.get("current_period_start"),
                    "current_period_end": sub.get("current_period_end"),
                    "trial_end": sub.get("trial_end"),
                    "is_trial_expired": sub.get("is_trial_expired", False),
                }
        except Exception as e:
            logger.error(f"Failed to fetch subscription directly: {e}")

    return {
        "id": current_user["id"],
        "email": current_user["email"],
        "name": current_user["name"],
        "subscription": subscription,
    }
