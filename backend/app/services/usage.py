"""Server-authoritative monthly lead quota reservations."""

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def settle_search_quota(supabase, search_id: str, user_id: str, generated: int) -> None:
    """Convert one search's reservation into actual generated leads.

    Updates monthly_usage table directly. Safe to call multiple times
    (idempotent via quota_settled_at marker).
    """
    try:
        row = await asyncio.to_thread(
            lambda: supabase.table("searches").select("quota_source,reserved_leads,quota_settled_at")
            .eq("id", search_id).limit(1).execute()
        )
        data = (row.data or [None])[0]
        if not data:
            return

        # Already settled — skip
        if data.get("quota_settled_at"):
            return

        source = data.get("quota_source") or "google_maps"
        reserved = int(data.get("reserved_leads") or 0)
        generated = max(0, min(int(generated), reserved)) if reserved > 0 else int(generated)

        # Mark as settled to prevent double-counting
        month_str = datetime.now(timezone.utc).replace(day=1).date().isoformat()
        try:
            await asyncio.to_thread(
                lambda: supabase.table("searches").update({"quota_settled_at": datetime.now(timezone.utc).isoformat()})
                .eq("id", search_id).execute()
            )
        except Exception:
            pass  # Column may not exist, that's fine

        if generated <= 0:
            return

        # Update monthly_usage directly (upsert)
        try:
            existing = await asyncio.to_thread(
                lambda: supabase.table("monthly_usage")
                .select("id")
                .eq("user_id", user_id)
                .eq("usage_month", month_str)
                .limit(1)
                .execute()
            )

            col = "linkedin_hq_generated" if source == "linkedin" else "gmb_generated"

            if existing.data and len(existing.data) > 0:
                row_id = existing.data[0]["id"]
                # Increment
                current = await asyncio.to_thread(
                    lambda: supabase.table("monthly_usage").select(col).eq("id", row_id).limit(1).execute()
                )
                current_val = int((current.data or [{}])[0].get(col, 0) or 0)
                await asyncio.to_thread(
                    lambda: supabase.table("monthly_usage").update({col: current_val + generated})
                    .eq("id", row_id).execute()
                )
            else:
                # Create new row
                insert_data = {
                    "user_id": user_id,
                    "usage_month": month_str,
                    col: generated,
                }
                await asyncio.to_thread(
                    lambda: supabase.table("monthly_usage").insert(insert_data).execute()
                )

            # Also update daily_usage leads_generated count
            today_str = datetime.now(timezone.utc).date().isoformat()
            try:
                daily = await asyncio.to_thread(
                    lambda: supabase.table("daily_usage")
                    .select("id,leads_generated")
                    .eq("user_id", user_id)
                    .eq("date", today_str)
                    .limit(1)
                    .execute()
                )
                if daily.data and len(daily.data) > 0:
                    daily_id = daily.data[0]["id"]
                    daily_leads = int(daily.data[0].get("leads_generated", 0) or 0)
                    await asyncio.to_thread(
                        lambda: supabase.table("daily_usage").update({"leads_generated": daily_leads + generated})
                        .eq("id", daily_id).execute()
                    )
            except Exception:
                pass

            logger.info(f"[Settle:{search_id}] +{generated} {col} leads (user={user_id[:8]})")

        except Exception as e:
            logger.warning(f"[Settle:{search_id}] monthly_usage update failed: {e}")

    except Exception as e:
        logger.debug(f"Quota settle skipped: {e}")
