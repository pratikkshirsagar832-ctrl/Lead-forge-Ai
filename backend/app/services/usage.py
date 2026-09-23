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


# ── monthly lead quota ──────────────────────────────────────────────────
#
# The monthly cap is enforced by reserving leads BEFORE they are delivered:
# the number reserved for a search is the number of leads the pipeline is
# allowed to save (`create_search` clamps `max_results` to it). Because of
# that every path in here must fail CLOSED — a reservation that reports more
# than the plan allows directly over-delivers, which is how a Free plan
# (3 LinkedIn leads/month) used to hand out a 10-lead LinkedIn run.

_QUOTA_COLUMNS = {
    "linkedin": ("linkedin_hq_generated", "linkedin_hq_reserved"),
    "google_maps": ("gmb_generated", "gmb_reserved"),
}
_PLAN_LIMIT_COLUMN = {
    "linkedin": "linkedin_hq_leads_monthly",
    "google_maps": "gmb_leads_monthly",
}


def _quota_columns(source: str) -> tuple[str, str]:
    return _QUOTA_COLUMNS[source]


def get_monthly_plan_limit(supabase, plan_id: str, source: str) -> int | None:
    """Monthly cap for `source` in the plan, or None when undeterminable.

    None (pre-v5 schema — the column is absent from the plans row) is
    deliberately distinct from 0, which means the plan genuinely has no
    allowance for that source.
    """
    from app.services.plans import get_plan_row

    key = _PLAN_LIMIT_COLUMN[source]
    try:
        plan = get_plan_row(supabase, plan_id) or {}
    except Exception as exc:
        logger.warning("Could not read plan %s to determine the quota cap: %s", plan_id, exc)
        return None
    if key not in plan:
        return None
    try:
        return max(0, int(plan.get(key) or 0))
    except (TypeError, ValueError):
        return None


def _read_month_usage(supabase, user_id: str, month_str: str, source: str) -> tuple[int, int] | None:
    """(generated, reserved) for the month, or None when there is no row yet."""
    generated_col, reserved_col = _quota_columns(source)
    result = (
        supabase.table("monthly_usage")
        .select(f"{generated_col},{reserved_col}")
        .eq("user_id", user_id)
        .eq("usage_month", month_str)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        return None
    row = rows[0] or {}
    return (
        int(row.get(generated_col, 0) or 0),
        int(row.get(reserved_col, 0) or 0),
    )


def _try_rpc_reserve(supabase, user_id: str, plan_id: str, source: str, amount: int) -> int | None:
    """Reserve through the row-locked RPC. Never returns an unverified amount.

    Contract of `reserve_monthly_leads` (migration_production_v5.sql): -1 means
    `p_amount` WAS written; any other non-negative value is the remaining
    capacity and means NOTHING was reserved, so we retry with it.

    Returns the verified reserved count, or None when the RPC answered
    something unusable so the caller falls back to the clamped direct path.
    """
    try:
        request_amount = amount
        # Each round either reserves or reports a smaller remaining capacity,
        # so the loop converges (and <= 0 short-circuits).
        for _attempt in range(3):
            rpc = supabase.rpc(
                "reserve_monthly_leads",
                {"p_user_id": user_id, "p_plan_id": plan_id, "p_source": source, "p_amount": request_amount},
            ).execute()
            result = getattr(rpc, "data", None)
            if isinstance(result, (list, tuple)) and len(result) == 1:
                result = result[0]  # scalar wrapped in a list by the client
            if isinstance(result, bool) or not isinstance(result, (int, float)):
                logger.warning(
                    "reserve_monthly_leads answered %r (unusable) — using the clamped direct path", result
                )
                return None
            value = int(result)
            if value == -1:
                return request_amount  # confirmed written by the database
            if value <= 0:
                return 0  # nothing reserved, no capacity left
            request_amount = value  # nothing reserved yet; retry with the remainder
        logger.warning("reserve_monthly_leads did not settle after 3 rounds — reserving nothing")
        return 0
    except Exception as exc:
        logger.debug("RPC reserve_monthly_leads unavailable (%s) — using direct path", exc)
        return None


def _enforce_plan_cap(supabase, user_id: str, month_str: str, source: str, reserved: int, limit: int | None) -> int:
    """Read the ledger back and release anything above the plan cap.

    Final guard for the fallback paths (the RPC path is already verified by the
    database under a row lock): even if a read-modify-write raced with another
    request, the amount reported to the caller — and therefore what the
    pipeline may save — never exceeds the plan's monthly cap.
    """
    if reserved <= 0 or limit is None:
        return reserved
    reserved_col = _quota_columns(source)[1]
    try:
        usage = _read_month_usage(supabase, user_id, month_str, source)
    except Exception as exc:
        logger.warning("Could not re-read monthly_usage to verify the quota cap: %s", exc)
        return reserved
    if usage is None:
        return reserved
    generated, recorded = usage
    excess = min((generated + recorded) - limit, reserved)
    if excess <= 0:
        return reserved
    try:
        (
            supabase.table("monthly_usage")
            .update({reserved_col: max(0, recorded - excess)})
            .eq("user_id", user_id)
            .eq("usage_month", month_str)
            .execute()
        )
    except Exception as exc:
        logger.error(
            "Could not release %d over-reserved %s lead(s) for user %s: %s",
            excess, source, user_id[:8], exc, exc_info=True,
        )
    logger.warning(
        "Released %d over-reserved %s lead(s) for user %s (plan cap %d, ledger %d generated + %d reserved)",
        excess, source, user_id[:8], limit, generated, recorded,
    )
    return reserved - excess


def _direct_reserve(supabase, user_id: str, plan_id: str, source: str, amount: int, month_str: str) -> int:
    """Clamped fallback used when the RPC is unavailable.

    Every branch is bounded by the plan cap. The previous version upserted the
    full requested amount when the month had no row yet, which is what let a
    Free plan deliver 10 LinkedIn leads instead of 3 on the first search of a
    month (and again whenever the ledger was unreadable).
    """
    reserved_col = _quota_columns(source)[1]
    limit = get_monthly_plan_limit(supabase, plan_id, source)
    if limit is not None:
        amount = min(amount, limit)
    if amount <= 0:
        return 0

    try:
        usage = _read_month_usage(supabase, user_id, month_str, source)
    except Exception as exc:
        # Ledger missing/unreadable (pre-v5 schema): the month cannot be
        # counted, so bound this single run by the plan cap instead of handing
        # out the whole request.
        logger.warning(
            "monthly_usage unavailable for user %s (%s) — bounding this run to %d lead(s)",
            user_id[:8], exc, amount,
        )
        return amount

    if usage is None:
        # First reservation of the month: nothing used, so the cap is intact.
        try:
            (
                supabase.table("monthly_usage")
                .upsert(
                    {"user_id": user_id, "usage_month": month_str, reserved_col: amount},
                    on_conflict="user_id,usage_month",
                )
                .execute()
            )
        except Exception as exc:
            logger.warning("Could not record the reservation for user %s: %s", user_id[:8], exc)
        return amount

    generated, reserved = usage
    if limit is None:
        logger.warning(
            "Plan %s has no readable monthly cap — reserving %d %s lead(s) unclamped",
            plan_id, amount, source,
        )
        actual = amount
    else:
        actual = max(0, min(amount, limit - generated - reserved))
    if actual <= 0:
        return 0
    (
        supabase.table("monthly_usage")
        .update({reserved_col: reserved + actual})
        .eq("user_id", user_id)
        .eq("usage_month", month_str)
        .execute()
    )
    return actual


def reserve_monthly_leads_sync(supabase, user_id: str, plan_id: str, source: str, amount: int) -> int:
    """Atomically reserve `amount` monthly leads for a user.

    Returns the amount ACTUALLY reserved AND recorded (may be < amount when the
    remaining quota is smaller). The caller uses this number as the number of
    leads the pipeline may deliver, so it must never report more than the plan
    allows:

    * the RPC path is verified by the database itself (row-locked),
    * every fallback path is clamped to the plan's monthly cap and re-checked
      against the ledger before the number is returned,
    * when the ledger cannot be read at all we degrade to the plan cap per run
      rather than the full request — fail closed, not open.
    """
    if amount <= 0:
        return 0
    if source not in _QUOTA_COLUMNS:
        return 0
    month_str = _month_start_iso()

    rpc_amount = _try_rpc_reserve(supabase, user_id, plan_id, source, amount)
    if rpc_amount is not None:
        return rpc_amount

    limit = get_monthly_plan_limit(supabase, plan_id, source)
    reserved = _direct_reserve(supabase, user_id, plan_id, source, amount, month_str)
    return _enforce_plan_cap(supabase, user_id, month_str, source, reserved, limit)


async def reserve_monthly_leads(supabase, user_id: str, plan_id: str, source: str, amount: int) -> int:
    return await asyncio.to_thread(
        reserve_monthly_leads_sync, supabase, user_id, plan_id, source, amount
    )


# ── daily quota (searches / AI calls) ────────────────────────────────────
#
# The daily caps used to be checked with a plain read and incremented only
# after the work finished, so two concurrent requests both saw "under the
# limit" and both ran (each search burns paid provider spend). Consumption is
# now atomic via the row-locked RPC from migration v13.

_DAILY_KINDS = ("search", "ai")
_DAILY_COLUMN = {"search": "searches_run", "ai": "ai_calls"}


def consume_daily_quota_sync(supabase, user_id: str, kind: str, limit: int) -> int:
    """Atomically consume one daily unit for `kind`.

    Returns -1 when the unit was consumed (caller may proceed); returns the
    REMAINING allowance (>= 0) when the limit is already reached (caller must
    refuse). Degrades to "allowed" only when the counters are entirely
    unavailable — a missing table must never lock a paying user out.
    """
    if kind not in _DAILY_KINDS:
        return 0
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return 0
    if limit <= 0:
        return 0

    # 1) Atomic, row-locked RPC (migration v13).
    try:
        rpc = (
            supabase.rpc(
                "consume_daily_quota",
                {"p_user_id": user_id, "p_kind": kind, "p_limit": limit},
            )
            .execute()
        )
        result = rpc.data if rpc is not None else None
        if isinstance(result, (int, float)):
            return int(result)
        logger.debug(
            "consume_daily_quota returned an unexpected shape (%r) — using direct path",
            result,
        )
    except Exception as exc:
        logger.debug("RPC consume_daily_quota unavailable (%s) — using direct path", exc)

    # 2) Direct read-modify-write fallback (best effort on a pre-v13 schema).
    today = _today_iso()
    col = _DAILY_COLUMN[kind]
    try:
        existing = (
            supabase.table("daily_usage")
            .select(col)
            .eq("user_id", user_id)
            .eq("date", today)
            .limit(1)
            .execute()
        )
        rows = existing.data or []
        cur = int(((rows[0] if rows else {}) or {}).get(col, 0) or 0)
        if cur >= limit:
            return max(0, limit - cur)
        if rows:
            (
                supabase.table("daily_usage")
                .update({col: cur + 1})
                .eq("user_id", user_id)
                .eq("date", today)
                .execute()
            )
        else:
            (
                supabase.table("daily_usage")
                .insert({
                    "user_id": user_id,
                    "date": today,
                    "leads_generated": 0,
                    "searches_run": 1 if kind == "search" else 0,
                    "ai_calls": 1 if kind == "ai" else 0,
                })
                .execute()
            )
        return -1
    except Exception as exc:
        logger.warning(
            "Daily quota consume unavailable for user %s (%s): %s — allowing request",
            user_id[:8], kind, exc,
        )
        return -1


async def consume_daily_quota(supabase, user_id: str, kind: str, limit: int) -> int:
    return await asyncio.to_thread(
        consume_daily_quota_sync, supabase, user_id, kind, limit
    )


def refund_daily_quota_sync(supabase, user_id: str, kind: str) -> None:
    """Give back a consumed daily unit the caller could not use.

    Used when a search was charged but its row (and therefore the job) could
    not be created. Clamped at zero on the DB side.
    """
    if kind not in _DAILY_KINDS:
        return
    try:
        supabase.rpc(
            "refund_daily_quota", {"p_user_id": user_id, "p_kind": kind}
        ).execute()
        return
    except Exception as exc:
        logger.debug("RPC refund_daily_quota unavailable (%s) — using direct path", exc)
    today = _today_iso()
    col = _DAILY_COLUMN[kind]
    try:
        existing = (
            supabase.table("daily_usage")
            .select(col)
            .eq("user_id", user_id)
            .eq("date", today)
            .limit(1)
            .execute()
        )
        rows = existing.data or []
        if not rows:
            return
        cur = int(((rows[0] or {}).get(col, 0) or 0))
        if cur <= 0:
            return
        (
            supabase.table("daily_usage")
            .update({col: cur - 1})
            .eq("user_id", user_id)
            .eq("date", today)
            .execute()
        )
    except Exception as exc:
        logger.warning(
            "Daily quota refund failed for user %s (%s): %s", user_id[:8], kind, exc
        )


async def refund_daily_quota(supabase, user_id: str, kind: str) -> None:
    await asyncio.to_thread(refund_daily_quota_sync, supabase, user_id, kind)


# ── monthly quota (searches / AI calls) ──────────────────────────────────
# Product decision (v16): searches, AI and generic leads are MONTHLY caps
# keeping the same numbers (pro 15/day -> 15/mo). daily_usage stays for
# reporting; enforcement reads monthly_usage via consume_monthly_quota.

_MONTHLY_KINDS = ("search", "ai")
_MONTHLY_COLUMN = {"search": "searches_used", "ai": "ai_calls_used"}


def consume_monthly_quota_sync(supabase, user_id: str, kind: str, limit: int) -> int:
    """Atomically consume one monthly unit. -1 = consumed, >=0 = remaining."""
    if kind not in _MONTHLY_KINDS:
        return 0
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return 0
    if limit <= 0:
        return 0
    try:
        rpc = supabase.rpc(
            "consume_monthly_quota",
            {"p_user_id": user_id, "p_kind": kind, "p_limit": limit},
        ).execute()
        result = rpc.data if rpc is not None else None
        if isinstance(result, (int, float)):
            return int(result)
        logger.debug("consume_monthly_quota unexpected shape (%r) — direct path", result)
    except Exception as exc:
        logger.debug("RPC consume_monthly_quota unavailable (%s) — direct path", exc)
    month_str = _month_start_iso()
    col = _MONTHLY_COLUMN[kind]
    try:
        existing = (
            supabase.table("monthly_usage").select(col)
            .eq("user_id", user_id).eq("usage_month", month_str).limit(1).execute()
        )
        rows = existing.data or []
        cur = int(((rows[0] if rows else {}) or {}).get(col, 0) or 0)
        if cur >= limit:
            return max(0, limit - cur)
        if rows:
            supabase.table("monthly_usage").update({col: cur + 1}) \
                .eq("user_id", user_id).eq("usage_month", month_str).execute()
        else:
            supabase.table("monthly_usage").insert({
                "user_id": user_id, "usage_month": month_str,
                "searches_used": 1 if kind == "search" else 0,
                "ai_calls_used": 1 if kind == "ai" else 0,
            }).execute()
        return -1
    except Exception as exc:
        logger.warning("Monthly quota consume unavailable for %s (%s): %s — allowing",
                       user_id[:8], kind, exc)
        return -1


async def consume_monthly_quota(supabase, user_id: str, kind: str, limit: int) -> int:
    return await asyncio.to_thread(consume_monthly_quota_sync, supabase, user_id, kind, limit)


def refund_monthly_quota_sync(supabase, user_id: str, kind: str) -> None:
    """Give back a consumed monthly unit the caller could not use."""
    if kind not in _MONTHLY_KINDS:
        return
    try:
        supabase.rpc("refund_monthly_quota", {"p_user_id": user_id, "p_kind": kind}).execute()
        return
    except Exception as exc:
        logger.debug("RPC refund_monthly_quota unavailable (%s) — direct path", exc)
    month_str = _month_start_iso()
    col = _MONTHLY_COLUMN[kind]
    try:
        existing = (
            supabase.table("monthly_usage").select(col)
            .eq("user_id", user_id).eq("usage_month", month_str).limit(1).execute()
        )
        rows = existing.data or []
        if not rows:
            return
        cur = int(((rows[0] or {}).get(col, 0) or 0))
        if cur <= 0:
            return
        supabase.table("monthly_usage").update({col: cur - 1}) \
            .eq("user_id", user_id).eq("usage_month", month_str).execute()
    except Exception as exc:
        logger.warning("Monthly quota refund failed for %s (%s): %s", user_id[:8], kind, exc)


async def refund_monthly_quota(supabase, user_id: str, kind: str) -> None:
    await asyncio.to_thread(refund_monthly_quota_sync, supabase, user_id, kind)


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
            .select(f"{col},{'linkedin_hq_reserved' if source == 'linkedin' else 'gmb_reserved'}")
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


def _settle_api_wallet(supabase, search_id: str, generated: int) -> bool:
    """True when this is an API-billed search (then it is fully handled here:
    wallet charged for delivered leads, unused hold released, webhook sent).
    False for normal web-plan searches (or before migration v20)."""
    try:
        row = (
            supabase.table("searches").select("billing,wallet_settled_at")
            .eq("id", search_id).limit(1).execute()
        )
    except Exception:  # billing column missing (pre-v20) -> plan billing
        return False
    data = (row.data or [None])[0]
    if not data or data.get("billing") != "api":
        return False
    if data.get("wallet_settled_at"):
        return True  # idempotent: already charged + webhook already queued
    from app.services import api_public, api_wallet

    charged = api_wallet.settle(supabase, search_id, generated)
    logger.info("[Settle:%s] API wallet: %d delivered, %d paise charged", search_id, generated, charged)
    api_public.deliver_search_webhook_async(supabase, search_id)
    return True


def _settle_sync(supabase, search_id: str, user_id: str, generated: int) -> bool:
    """One synchronous settlement attempt. Returns True on success/complete,
    False when the search is not settleable (missing row / already settled).

    Must only be called from a worker thread or an asyncio.to_thread wrapper —
    it performs blocking Supabase calls.
    """
    # Public-API searches are paid from the prepaid wallet (per delivered
    # lead), never from the web plan's monthly quota.
    if _settle_api_wallet(supabase, search_id, generated):
        return True
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
