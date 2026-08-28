"""
LeadForge — Auth Router (Local DB)

Handles:
  - POST /api/auth/signup       — Email + password registration
  - POST /api/auth/login        — Email + password login
  - POST /api/auth/google       — Google OAuth token exchange (uses Supabase)
  - POST /api/auth/logout       — Logout
  - GET  /api/auth/me           — Current user + subscription
  - Team management endpoints
"""

import hashlib
import logging
import re
from datetime import date, datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Body

from app.config import get_settings
from app.db import query_one, query_all, execute, execute_returning
from app.jwt_auth import create_token
from app.middleware.auth_middleware import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Auth"])

PLAN_SEATS = {"pro": 2, "agency": 10}
MEMBER_EMAIL_DOMAIN = "members.hyperclients.online"
USERNAME_RE = re.compile(r"^[a-z0-9_]{3,20}$")


def _hash_password(password: str) -> str:
    salt = "leadforge-salt-2026"
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()


# ── Signup ──────────────────────────────────────────────────────

@router.post("/signup")
async def signup(payload: dict = Body(...)):
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    name = (payload.get("name") or "").strip()

    if not email or not password:
        raise HTTPException(status_code=400, detail={"message": "Email and password required"})
    if len(password) < 6:
        raise HTTPException(status_code=400, detail={"message": "Password must be at least 6 characters"})
    if "@" not in email:
        raise HTTPException(status_code=400, detail={"message": "Invalid email"})

    # Check if user exists
    existing = query_one("SELECT id FROM users WHERE email = %s", (email,))
    if existing:
        raise HTTPException(status_code=409, detail={"message": "Email already registered"})

    # Create user
    password_hash = _hash_password(password)
    user = execute_returning(
        """INSERT INTO users (email, full_name, password_hash, auth_provider)
           VALUES (%s, %s, %s, 'email') RETURNING id, email, full_name""",
        (email, name or email.split("@")[0], password_hash),
    )
    if not user:
        raise HTTPException(status_code=500, detail={"message": "Failed to create user"})

    user_id = str(user["id"])
    now = datetime.now(timezone.utc)

    # Create free trial subscription
    execute(
        """INSERT INTO user_subscriptions (user_id, plan_id, status, trial_end, current_period_end)
           VALUES (%s, 'free', 'trial', %s, %s)""",
        (user_id, (now + timedelta(days=3)).isoformat(), (now + timedelta(days=3)).isoformat()),
    )

    token = create_token(user_id, email, name or email.split("@")[0])

    return {
        "token": token,
        "user": {
            "id": user_id,
            "email": email,
            "name": name or email.split("@")[0],
        },
    }


# ── Login ───────────────────────────────────────────────────────

@router.post("/login")
async def login(payload: dict = Body(...)):
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""

    if not email or not password:
        raise HTTPException(status_code=400, detail={"message": "Email and password required"})

    user = query_one(
        "SELECT id, email, full_name, password_hash FROM users WHERE email = %s",
        (email,),
    )
    if not user:
        raise HTTPException(status_code=401, detail={"message": "Invalid credentials"})

    if user["password_hash"] and user["password_hash"] != _hash_password(password):
        raise HTTPException(status_code=401, detail={"message": "Invalid credentials"})

    token = create_token(str(user["id"]), user["email"], user["full_name"])

    return {
        "token": token,
        "user": {
            "id": str(user["id"]),
            "email": user["email"],
            "name": user["full_name"],
        },
    }


# ── Google OAuth (uses Supabase) ───────────────────────────────

@router.post("/google")
async def google_auth(payload: dict = Body(...)):
    """Exchange a Supabase Google OAuth token for a local JWT."""
    supabase_token = payload.get("access_token") or payload.get("token")
    if not supabase_token:
        raise HTTPException(status_code=400, detail={"message": "Missing Google token"})

    settings = get_settings()

    # Verify token with Supabase and get user info
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{settings.supabase_url}/auth/v1/user",
            headers={
                "apikey": settings.supabase_anon_key,
                "Authorization": f"Bearer {supabase_token}",
            },
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail={"message": "Invalid Google token"})

    google_user = resp.json()
    email = (google_user.get("email") or "").strip().lower()
    full_name = google_user.get("user_metadata", {}).get("full_name", "") or google_user.get("user_metadata", {}).get("name", "")
    avatar_url = google_user.get("user_metadata", {}).get("avatar_url", "")
    google_id = google_user.get("id", "")

    if not email:
        raise HTTPException(status_code=400, detail={"message": "No email from Google"})

    # Find or create user
    user = query_one("SELECT id, email, full_name FROM users WHERE email = %s", (email,))
    if user:
        # Update name/avatar if changed
        execute(
            "UPDATE users SET full_name = COALESCE(NULLIF(%s, ''), full_name), avatar_url = COALESCE(NULLIF(%s, ''), avatar_url) WHERE id = %s",
            (full_name, avatar_url, user["id"]),
        )
        user_id = str(user["id"])
    else:
        new_user = execute_returning(
            """INSERT INTO users (email, full_name, avatar_url, auth_provider, google_id)
               VALUES (%s, %s, %s, 'google', %s)
               RETURNING id""",
            (email, full_name, avatar_url, google_id),
        )
        user_id = str(new_user["id"])

        # Create free trial subscription
        now = datetime.now(timezone.utc)
        execute(
            """INSERT INTO user_subscriptions (user_id, plan_id, status, trial_end, current_period_end)
               VALUES (%s, 'free', 'trial', %s, %s)""",
            (user_id, (now + timedelta(days=3)).isoformat(), (now + timedelta(days=3)).isoformat()),
        )

    token = create_token(user_id, email, full_name)

    return {
        "token": token,
        "user": {
            "id": user_id,
            "email": email,
            "name": full_name,
        },
    }


# ── Logout ──────────────────────────────────────────────────────

@router.post("/logout")
async def logout():
    return {"ok": True}


# ── Current User ────────────────────────────────────────────────

@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    today_str = date.today().isoformat()

    # Get usage
    used = query_one(
        "SELECT searches_run, leads_generated FROM daily_usage WHERE user_id = %s AND date = %s",
        (user_id, today_str),
    )
    used_searches = (used or {}).get("searches_run", 0) or 0
    used_leads = (used or {}).get("leads_generated", 0) or 0

    # Get subscription via RPC function
    subscription = None
    try:
        sub = call_fn_one(
            "SELECT * FROM get_user_subscription(%s)",
            (user_id,),
        )
        if sub:
            subscription = sub
            searches_per_day = sub.get("searches_per_day", 3)
            leads_per_day = sub.get("leads_per_day", 30)
            subscription["remaining_searches"] = max(0, searches_per_day - used_searches)
            subscription["remaining_leads"] = max(0, leads_per_day - used_leads)
    except Exception as e:
        logger.warning(f"get_user_subscription failed: {e}")

    # Fallback: direct table query
    if not subscription:
        sub_row = query_one(
            """SELECT us.plan_id, us.status, us.current_period_start, us.current_period_end,
                      us.trial_end, us.is_trial_expired,
                      p.name as plan_name, p.searches_per_day, p.leads_per_day
               FROM user_subscriptions us
               JOIN plans p ON p.id = us.plan_id
               WHERE us.user_id = %s
               ORDER BY us.created_at DESC LIMIT 1""",
            (user_id,),
        )
        if sub_row:
            subscription = dict(sub_row)
            searches_per_day = sub_row.get("searches_per_day", 3) or 3
            leads_per_day = sub_row.get("leads_per_day", 30) or 30
            subscription["remaining_searches"] = max(0, searches_per_day - used_searches)
            subscription["remaining_leads"] = max(0, leads_per_day - used_leads)

    if not subscription:
        subscription = {
            "plan_id": "free",
            "plan_name": "Free",
            "status": "trial",
            "searches_per_day": 3,
            "leads_per_day": 30,
            "remaining_searches": 3,
            "remaining_leads": 30,
        }

    return {
        "id": user_id,
        "email": current_user["email"],
        "name": current_user["name"],
        "subscription": subscription,
    }


def call_fn_one(sql: str, params: tuple = None):
    """Helper to call a function and return one row."""
    return query_one(sql, params)


# ── Team Endpoints ──────────────────────────────────────────────

@router.get("/team")
async def get_team(current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    sub = query_one(
        """SELECT us.plan_id FROM user_subscriptions us
           WHERE us.user_id = %s ORDER BY us.created_at DESC LIMIT 1""",
        (user_id,),
    )
    plan_id = (sub or {}).get("plan_id", "free")
    seats_allowed = PLAN_SEATS.get(plan_id, 0)

    rows = query_all(
        """SELECT us.user_id, us.razorpay_order_id, us.created_at
           FROM user_subscriptions us
           WHERE us.razorpay_order_id LIKE %s
           ORDER BY us.created_at""",
        (f"team:{user_id}:%",),
    )
    members = []
    for r in rows:
        parts = (r.get("razorpay_order_id") or "").split(":", 2)
        if len(parts) == 3:
            members.append({
                "id": str(r["user_id"]),
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
async def add_team_member(payload: dict = Body(...), current_user: dict = Depends(get_current_user)):
    username = (payload.get("username") or "").strip().lower()
    password = payload.get("password") or ""

    if not USERNAME_RE.match(username):
        raise HTTPException(status_code=400, detail={"message": "Username must be 3-20 chars: lowercase, numbers, underscores"})
    if len(password) < 6:
        raise HTTPException(status_code=400, detail={"message": "Password must be at least 6 characters"})

    user_id = current_user["id"]
    sub = query_one(
        "SELECT plan_id, status FROM user_subscriptions WHERE user_id = %s ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    )
    plan_id = (sub or {}).get("plan_id", "free")
    sub_status = (sub or {}).get("status", "trial")

    if sub_status not in ("active", "trial"):
        raise HTTPException(status_code=403, detail={"message": "Subscription is not active"})

    seats_allowed = PLAN_SEATS.get(plan_id, 0)
    if seats_allowed == 0:
        raise HTTPException(status_code=403, detail={"message": "Team seats available on Pro/Agency plans only", "upgrade_url": "/pricing"})

    count_row = query_one(
        "SELECT COUNT(*) as cnt FROM user_subscriptions WHERE razorpay_order_id LIKE %s",
        (f"team:{user_id}:%",),
    )
    if (count_row or {}).get("cnt", 0) >= seats_allowed:
        raise HTTPException(status_code=400, detail={"message": f"All {seats_allowed} seats are in use"})

    member_email = f"{username}@{MEMBER_EMAIL_DOMAIN}"
    member = execute_returning(
        """INSERT INTO users (email, full_name, password_hash, auth_provider)
           VALUES (%s, %s, %s, 'team') RETURNING id""",
        (member_email, username, _hash_password(password)),
    )
    member_uid = str(member["id"])

    # Mirror owner's plan
    owner_sub = query_one(
        "SELECT current_period_end FROM user_subscriptions WHERE user_id = %s ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    )
    period_end = (owner_sub or {}).get("current_period_end")

    execute(
        """INSERT INTO user_subscriptions (user_id, plan_id, status, current_period_start, current_period_end, razorpay_order_id)
           VALUES (%s, %s, 'active', %s, %s, %s)""",
        (member_uid, plan_id, datetime.now(timezone.utc).isoformat(), period_end, f"team:{user_id}:{username}"),
    )

    return {"id": member_uid, "username": username, "email": member_email}


@router.delete("/team/{member_id}")
async def remove_team_member(member_id: str, current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    row = query_one(
        "SELECT id FROM user_subscriptions WHERE user_id = %s AND razorpay_order_id LIKE %s LIMIT 1",
        (member_id, f"team:{user_id}:%"),
    )
    if not row:
        raise HTTPException(status_code=404, detail={"message": "Team member not found"})

    execute("DELETE FROM user_subscriptions WHERE id = %s", (row["id"],))
    execute("DELETE FROM users WHERE id = %s", (member_id,))
    return {"ok": True}


@router.post("/team-resolve")
async def resolve_team_username(payload: dict = Body(...)):
    username = (payload.get("username") or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise HTTPException(status_code=400, detail={"message": "Invalid username"})
    return {"email": f"{username}@{MEMBER_EMAIL_DOMAIN}"}
