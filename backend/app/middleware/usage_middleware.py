import logging

from fastapi import Depends, HTTPException, status

from app.database import get_supabase_admin
from app.middleware.auth_middleware import get_current_user
from app.services.plans import (
    get_plan_row,
    get_used_today,
    resolve_effective_subscription,
)

logger = logging.getLogger(__name__)


async def check_search_limit(current_user: dict = Depends(get_current_user)) -> dict:
    supabase = get_supabase_admin()
    user_id = current_user["id"]

    try:
        eff = resolve_effective_subscription(supabase, user_id)
        plan_id = eff["plan_id"]

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
        searches_per_day = int(plan.get("searches_per_day", 0) or 0)
        used_searches, _ = get_used_today(supabase, user_id)
        remaining = max(0, searches_per_day - used_searches)

        if remaining <= 0:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": "Daily search limit reached",
                    "remaining_searches": 0,
                    "searches_per_day": searches_per_day,
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
