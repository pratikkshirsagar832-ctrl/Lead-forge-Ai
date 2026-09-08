"""Server-authoritative monthly lead quota reservations.

Settlement is idempotent and safe to call many times:
  * a `searches.quota_settled_at` marker guards double-counting, and
  * `monthly_usage` is keyed by PRIMARY KEY (user_id, usage_month) — the code
    never assumes a surrogate `id` column.

Preferred path is the transactional SQL RPC `settle_search_monthly_leads`
(created by migration_production_v5.sql); when that function is absent on the
live database we fall back to direct table updates that are equivalent in
effect (reserved -= reserved, generated += actual, capped at reserved).
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_SETTLE_RETRIES = 3
_SETTLE_RETRY_DELAY_S = 1.5


def reserve_monthly_leads_sync(supabase, user_id: str, plan_id: str, source: str, amount: int) -> int:
    """Atomically reserve `amount` monthly leads for a user.

    Returns the amount ACTUALLY reserved (may be < amount when remaining quota
    is smaller). Returns `amount` when the quota machinery is absent on the
    live DB (degraded but non-breaking — the search row still carries the
    reservation for accounting when the RPC/columns exist).

    Preferred path: the transactional SQL RPC `reserve_monthly_leads`
    (migration_production_v5.sql). Fallback: direct read-modify-write on
    monthly_usage keyed by PRIMARY KEY (user_id, usage_month).
    """
    if amount <= 0:
        return 0
    if source not in ("linkedin", "google_maps"):
        return 0
    month_str = _month_start_iso()

    # 1) Atomic RPC (row-locked) when available.
    #    Returns -1 when the FULL amount was reserved; otherwise returns the
    #    remaining capacity WITHOUT reserving (>=0), so we retry with that
    #    smaller amount to actually record the partial reservation.
    try:
        try_rpc = amount
        for _attempt in range(2):
            rpc = (
                supabase.rpc(
                    "reserve_monthly_leads",
                    {"p_user_id": user_id, "p_plan_id": plan_id, "p_source": source, "p_amount": try_rpc},
                )
                .execute()
            )
            result = rpc.data if rpc is not None else None
            if isinstance(result, (int, float)):
                val = int(result)
                if val == -1:
                    return try_rpc  # fully reserved
                if val >= 0:
                    if val <= 0:
                        return 0  # no capacity left
                    try_rpc = val  # retry with the remaining capacity
                    continue
            # Unexpected shape — assume fully reserved (defensive).
            return try_rpc
        return try_rpc
    except Exception as exc:
        logger.debug("RPC reserve_monthly_leads unavailable (%s) — using direct path", exc)

    # 2) Direct fallback with a single read-modify-write (best-effort).
    try:
        reserved_col = "linkedin_hq_reserved" if source == "linkedin" else "gmb_reserved"
        generated_col = "linkedin_hq_generated" if source == "linkedin" else "gmb_generated"
        existing = (
            supabase.table("monthly_usage")
            .select(f"{generated_col},{reserved_col}")
            .eq("user_id", user_id)
            .eq("usage_month", month_str)
            .limit(1)
            .execute()
        )
        if (existing.data or []) and len(existing.data) > 0:
            used = int((existing.data[0] or {}).get(generated_col, 0) or 0) + \
                int((existing.data[0] or {}).get(reserved_col, 0) or 0)
            cur_res = int((existing.data[0] or {}).get(reserved_col, 0) or 0)
            from app.services.plans import get_plan_row
            plan = get_plan_row(supabase, plan_id)
            plan_limit = int(plan.get(
                "linkedin_hq_leads_monthly" if source == "linkedin" else "gmb_leads_monthly", 0) or 0)
            actual = max(0, min(amount, plan_limit - used))
            if actual > 0:
                (
                    supabase.table("monthly_usage")
                    .update({reserved_col: cur_res + actual})
                    .eq("user_id", user_id)
                    .eq("usage_month", month_str)
                    .execute()
                )
            return actual
        # No row yet — insert one with the reservation.
        (
            supabase.table("monthly_usage")
            .upsert({"user_id": user_id, "usage_month": month_str, reserved_col: amount},
                    on_conflict="user_id,usage_month")
            .execute()
        )
        return amount
    except Exception as exc:
        # monthly_usage table/columns missing (pre-v5 DB): cannot enforce quota
        # server-side — degrade gracefully and keep the search row reservation.
        logger.warning("Quota reservation unavailable for user %s (monthly_usage missing?): %s", user_id[:8], exc)
        return amount


async def reserve_monthly_leads(supabase, user_id: str, plan_id: str, source: str, amount: int) -> int:
    return await asyncio.to_thread(
        reserve_monthly_leads_sync, supabase, user_id, plan_id, source, amount
    )


def _month_start_iso() -> str:
    return datetime.now(timezone.utc).replace(day=1).date().isoformat()


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def record_monthly_generated_sync(supabase, user_id: str, source: str, count: int) -> bool:
    """Account extra generated leads (e.g. load-more batches) into monthly_usage.

    Unlike settle_search_quota this is NOT tied to a single search's reserved
    marker — it simply adds `count` to the user's generated column for the
    current month. Callers must already have verified remaining quota.
    """
    if count <= 0 or source not in ("linkedin", "google_maps"):
        return False
    month_str = _month_start_iso()
    col = "linkedin_hq_generated" if source == "linkedin" else "gmb_generated"
    try:
        existing = (
            supabase.table("monthly_usage")
            .select("user_id")
            .eq("user_id", user_id)
            .eq("usage_month", month_str)
            .limit(1)
            .execute()
        )
        if (existing.data or []) and len(existing.data) > 0:
            cur_gen = int((existing.data[0] or {}).get(col, 0) or 0)
            (
                supabase.table("monthly_usage")
                .update({col: cur_gen + count})
                .eq("user_id", user_id)
                .eq("usage_month", month_str)
                .execute()
            )
        else:
            (
                supabase.table("monthly_usage")
                .upsert({"user_id": user_id, "usage_month": month_str, col: count},
                        on_conflict="user_id,usage_month")
                .execute()
            )
        return True
    except Exception as exc:
        logger.warning("record_monthly_generated failed for user %s: %s", user_id[:8], exc)
        return False


async def record_monthly_generated(supabase, user_id: str, source: str, count: int) -> bool:
    return await asyncio.to_thread(record_monthly_generated_sync, supabase, user_id, source, count)


def _settle_sync(supabase, search_id: str, user_id: str, generated: int) -> bool:
    """One synchronous settlement attempt. Returns True on success/complete,
    False when the search is not settleable (missing row / already settled).

    Must only be called from a worker thread or an asyncio.to_thread wrapper —
    it performs blocking Supabase calls.
    """
    try:
        row = (
            supabase.table("searches")
            .select("quota_source,reserved_leads,quota_settled_at")
            .eq("id", search_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # column set missing on live DB -> not settleable
        logger.debug("Quota settle skipped for %s (quota columns unavailable): %s", search_id, exc)
        return False
    data = (row.data or [None])[0]
    if not data:
        logger.debug("Quota settle skipped for %s (no searches row)", search_id)
        return False
    if data.get("quota_settled_at"):
        return True  # already settled — idempotent no-op

    source = data.get("quota_source") or "google_maps"
    reserved = int(data.get("reserved_leads") or 0)
    actual = max(0, min(int(generated), reserved)) if reserved > 0 else max(0, int(generated))
    month_str = _month_start_iso()

    # 1) Prefer the atomic SQL RPC that v5 ships (single-statement FOR UPDATE).
    try:
        rpc = (
            supabase.rpc(
                "settle_search_monthly_leads",
                {
                    "p_search_id": search_id,
                    "p_user_id": user_id,
                    "p_generated": actual,
                },
            )
            .execute()
        )
        # Marking is handled inside the RPC (quota_settled_at set on success).
        if actual > 0:
            logger.info("[Settle:%s] +%d %s leads (RPC; user=%s)", search_id, actual, source, user_id[:8])
        return True
    except Exception as exc:
        logger.debug(
            "[Settle:%s] RPC settle_search_monthly_leads unavailable (%s) — using direct path",
            search_id,
            exc,
        )

    # 2) Direct-table path (same accounting, keyed by the real PK).
    try:
        col = "linkedin_hq_generated" if source == "linkedin" else "gmb_generated"
        reserved_col = "linkedin_hq_reserved" if source == "linkedin" else "gmb_reserved"
        existing = (
            supabase.table("monthly_usage")
            .select(f"{col},{reserved_col}")
            .eq("user_id", user_id)
            .eq("usage_month", month_str)
            .limit(1)
            .execute()
        )
        if (existing.data or []) and len(existing.data) > 0:
            cur_gen = int((existing.data[0] or {}).get(col, 0) or 0)
            cur_res = int((existing.data[0] or {}).get(reserved_col, 0) or 0)
            (
                supabase.table("monthly_usage")
                .update({col: cur_gen + actual, reserved_col: max(0, cur_res - reserved)})
                .eq("user_id", user_id)
                .eq("usage_month", month_str)
                .execute()
            )
        else:
            if actual == 0 and reserved == 0:
                return True  # nothing to record
            # No monthly_usage row for the user yet: if a reservation was never
            # recorded (e.g. the create-time reservation silently degraded),
            # there is nothing to release — only record generated leads.
            insert_data: dict[str, Any] = {
                "user_id": user_id,
                "usage_month": month_str,
                col: actual,
            }
            # If a row was inserted between our select and here, upsert instead.
            (
                supabase.table("monthly_usage")
                .upsert(insert_data, on_conflict="user_id,usage_month")
                .execute()
            )
        # Only now mark settled — a failed update above leaves the marker clear
        # so a later call retries instead of silently dropping the count.
        (
            supabase.table("searches")
            .update({"quota_settled_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", search_id)
            .execute()
        )
        if actual > 0:
            logger.info("[Settle:%s] +%d %s leads (direct; user=%s)", search_id, actual, source, user_id[:8])
        return True
    except Exception as exc:
        logger.warning("[Settle:%s] monthly_usage direct update failed: %s", search_id, exc)
        return False


def settle_search_quota_sync(supabase, search_id: str, user_id: str, generated: int) -> None:
    """Synchronous settlement with retries. Intended for worker threads
    (e.g. the Hyperagent engine thread) that have no running event loop."""
    for attempt in range(_SETTLE_RETRIES):
        try:
            if _settle_sync(supabase, search_id, user_id, generated):
                return
        except Exception as exc:  # defensive — never let settlement crash a job
            logger.warning("[Settle:%s] attempt %d failed: %s", search_id, attempt + 1, exc)
        time.sleep(_SETTLE_RETRY_DELAY_S * (attempt + 1))
    logger.warning("[Settle:%s] gave up after %d attempts", search_id, _SETTLE_RETRIES)


async def settle_search_quota(supabase, search_id: str, user_id: str, generated: int) -> None:
    """Async wrapper used from the event loop (pipeline finalizers etc.)."""
    for attempt in range(_SETTLE_RETRIES):
        try:
            ok = await asyncio.to_thread(
                lambda: _settle_sync(supabase, search_id, user_id, generated)
            )
            if ok:
                return
        except Exception as exc:  # defensive — never let settlement crash a job
            logger.warning("[Settle:%s] attempt %d failed: %s", search_id, attempt + 1, exc)
        await asyncio.sleep(_SETTLE_RETRY_DELAY_S * (attempt + 1))
    logger.warning("[Settle:%s] gave up after %d attempts", search_id, _SETTLE_RETRIES)
