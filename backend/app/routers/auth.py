import asyncio
import logging
import re
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request

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
async def resolve_team_username(request: Request, payload: dict = Body(...)):
    """Public: turn a team username into its login email so the standard
    Supabase password sign-in works without exposing synthetic emails."""
    username = (payload.get("username") or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise HTTPException(status_code=400, detail={"message": "Invalid username format"})
    # Throttle per caller IP (behind nginx: X-Real-IP / X-Forwarded-For) so one
    # noisy client can never block every team member's login.
    ip = (request.headers.get("x-real-ip") or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
          or (request.client.host if request.client else "unknown"))
    if _throttled(_resolve_hits, ip, _RESOLVE_WINDOW_S, _RESOLVE_MAX):
        raise HTTPException(status_code=429, detail={"message": "Too many requests. Try again shortly."})
    return {"email": f"{username}@{MEMBER_EMAIL_DOMAIN}"}


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    """Profile + plan/usage summary for the dashboard shell (one query path,
    run off the event loop; team members see the owner's shared pool)."""
    from app.services.plans import build_subscription_summary

    subscription = None
    try:
        subscription = await asyncio.to_thread(build_subscription_summary, get_supabase_admin(), current_user["id"])
    except Exception as exc:  # noqa: BLE001 - the shell still renders without plan info
        logger.warning("Subscription summary failed for %s: %s", current_user["id"], exc)
    return {
        "id": current_user["id"],
        "email": current_user["email"],
        "name": current_user["name"],
        "subscription": subscription,
    }
