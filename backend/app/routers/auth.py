import logging
from datetime import date

from fastapi import APIRouter, Depends

from app.database import get_supabase_admin
from app.middleware.auth_middleware import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Auth"])


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
