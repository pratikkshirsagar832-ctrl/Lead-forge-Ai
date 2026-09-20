import logging

from fastapi import Depends, HTTPException, status

from app.database import get_supabase_admin
from app.middleware.auth_middleware import get_current_user
from app.services.plans import (
    get_monthly_limit,
    get_plan_row,
    quota_owner_id,
    resolve_effective_subscription,
)
from app.services.usage import consume_monthly_quota

logger = logging.getLogger(__name__)


async def check_search_limit(current_user: dict = Depends(get_current_user)) -> dict:
    supabase = get_supabase_admin()
    user_id = current_user["id"]

    try:
        eff = resolve_effective_subscription(supabase, user_id)
        plan_id = eff["plan_id"]
        quota_user = quota_owner_id(eff, user_id)

        if eff["status"] not in ("active", "trial"):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": "Subscription is not active",
                    "remaining_searches": 0,
                    "plan": plan_id,
                    "upgrade_url": "/pricing",
                },
            )

        plan = get_plan_row(supabase, plan_id)
        searches_per_month = get_monthly_limit(plan, "searches_per_month", "searches_per_day", 3)

        # Consume the monthly unit atomically (v16: quotas reset on the 1st).
        # Returns -1 when consumed, otherwise the remaining allowance.
        # Team members share their owner's pool (quota_owner_id).
        consumed = await consume_monthly_quota(
            supabase, quota_user, "search", searches_per_month
        )
        if consumed >= 0:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": "Monthly search limit reached",
                    "remaining_searches": consumed,
                    "searches_per_month": searches_per_month,
                    "plan": plan_id,
                    "upgrade_url": "/pricing",
                },
            )

        return current_user

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Usage check error for user {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify usage limits",
        )
