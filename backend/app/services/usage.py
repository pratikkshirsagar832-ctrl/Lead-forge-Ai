"""Server-authoritative monthly lead quota reservations."""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def settle_search_quota(supabase, search_id: str, user_id: str, generated: int) -> None:
    """Convert one search's reservation into actual generated leads once.

    A failed/cancelled search passes zero, releasing all capacity.  The row
    marker makes retries and duplicate finalization safe.
    """
    try:
        row = await asyncio.to_thread(
            lambda: supabase.table("searches").select("quota_source,reserved_leads,quota_settled_at")
            .eq("id", search_id).limit(1).execute()
        )
        data = (row.data or [None])[0]
        if not data or data.get("quota_settled_at") or not data.get("reserved_leads"):
            return
        reserved = int(data["reserved_leads"])
        generated = max(0, min(int(generated), reserved))
        await asyncio.to_thread(
            lambda: supabase.rpc("settle_search_monthly_leads", {
                "p_search_id": search_id,
                "p_user_id": user_id,
                "p_generated": generated,
            }).execute()
        )
    except Exception:
        logger.debug("Quota settle skipped (monthly_usage infrastructure may not exist)")
