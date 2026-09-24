import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone

try:
    import razorpay
except ImportError:
    razorpay = None

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import get_supabase_admin
from app.middleware.auth_middleware import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/subscriptions", tags=["Subscriptions"])


def _razorpay_amount_for_plan(settings, plan_id: str) -> int:
    """Return a dashboard-configured INR paise amount; never convert USD live."""
    amounts = {
        "solo": settings.razorpay_solo_amount_inr,
        "pro": settings.razorpay_pro_amount_inr,
        "agency": settings.razorpay_agency_amount_inr,
    }
    amount = int(amounts.get(plan_id, 0) or 0)
    if amount <= 0:
        raise HTTPException(status_code=503, detail="This plan is not configured for payments yet")
    return amount


# ── Payment-order ledger ───────────────────────────────────────────────
#
# `user_subscriptions.razorpay_order_id` is a SINGLE slot, so starting a second
# checkout overwrote the first order id — a payment for the abandoned order
# could then never be verified or webhooked (the customer paid and got
# nothing). Orders now live in their own table (migration v14); the slot is
# still written for backward compatibility.

_PAYMENT_ORDERS_SUPPORTED: bool | None = None


def _payment_orders_supported(supabase) -> bool:
    """True when the payment_orders table exists. Caches True permanently;
    re-probes on False so a migration applied after boot is picked up."""
    global _PAYMENT_ORDERS_SUPPORTED
    if _PAYMENT_ORDERS_SUPPORTED is True:
        return True
    try:
        supabase.table("payment_orders").select("order_id").limit(1).execute()
        _PAYMENT_ORDERS_SUPPORTED = True
    except Exception as e:
        logger.info(f"payment_orders unavailable (migration v14 pending): {e}")
        _PAYMENT_ORDERS_SUPPORTED = False
    return _PAYMENT_ORDERS_SUPPORTED


def _record_payment_order(supabase, order_id: str, user_id: str, plan_id: str, amount: int) -> None:
    """Best-effort insert of a pending order (never fails checkout)."""
    if not _payment_orders_supported(supabase):
        return
    try:
        supabase.table("payment_orders").insert({
            "order_id": order_id,
            "user_id": user_id,
            "plan_id": plan_id,
            "amount": int(amount),
            "status": "pending",
        }).execute()
    except Exception as e:
        logger.warning(f"Could not record payment order {order_id}: {e}")


def _mark_payment_order_paid(supabase, order_id: str, payment_id: str) -> None:
    if not _payment_orders_supported(supabase):
        return
    try:
        supabase.table("payment_orders").update({
            "status": "paid",
            "paid_at": datetime.now(timezone.utc).isoformat(),
            "payment_id": payment_id,
        }).eq("order_id", order_id).execute()
    except Exception as e:
        logger.warning(f"Could not mark payment order {order_id} paid: {e}")


def _resolve_order_owner(supabase, order_id: str) -> dict | None:
    """Authoritative {user_id, plan_id} for a Razorpay order id.

    Prefers the payment_orders ledger; falls back to the legacy single-slot
    `user_subscriptions.razorpay_order_id` lookup so a deployment that has not
    applied migration v14 keeps working exactly as before.
    """
    if _payment_orders_supported(supabase):
        try:
            resp = (
                supabase.table("payment_orders")
                .select("user_id, plan_id, amount, status")
                .eq("order_id", order_id)
                .limit(1)
                .execute()
            )
            if resp.data:
                row = resp.data[0]
                return {
                    "user_id": row.get("user_id"),
                    "plan_id": row.get("plan_id"),
                    "source": "payment_orders",
                }
        except Exception as e:
            logger.warning(f"payment_orders lookup failed for {order_id}: {e}")
    try:
        resp = (
            supabase.table("user_subscriptions")
            .select("id, user_id, plan_id")
            .eq("razorpay_order_id", order_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if resp.data:
            row = resp.data[0]
            return {
                "user_id": row.get("user_id"),
                "plan_id": row.get("plan_id"),
                "subscription_id": row.get("id"),
                "source": "user_subscriptions",
            }
    except Exception as e:
        logger.warning(f"user_subscriptions lookup failed for {order_id}: {e}")
    return None


def _target_subscription_row(supabase, user_id: str) -> dict | None:
    """Deterministic row to activate/cancel for a user.

    Previously `.limit(1)` with no ordering picked an arbitrary row (a signup
    trigger row, a team row, a legacy row), so a payment could activate the
    wrong subscription.
    """
    try:
        rows = (
            supabase.table("user_subscriptions")
            .select("id, status, plan_id")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(10)
            .execute()
            .data
        ) or []
    except Exception as e:
        logger.warning(f"Could not list subscription rows for {user_id[:8]}: {e}")
        return None
    if not rows:
        return None
    # Mirror resolve_effective_subscription: a cancelled row is never preferred.
    for row in rows:
        if row.get("status") != "cancelled":
            return row
    return rows[0]


def _reject_team_member(supabase, user_id: str) -> None:
    """Team seats ride on the owner's plan. Their subscription row carries the
    `team:<owner>:<username>` marker in razorpay_order_id; checkout/cancel on
    that row would overwrite the marker and silently drop them from the team."""
    from app.services.plans import resolve_effective_subscription

    try:
        eff = resolve_effective_subscription(supabase, user_id)
    except Exception:  # noqa: BLE001 - never block a real owner on a lookup error
        return
    if eff.get("team_owner_id"):
        raise HTTPException(status_code=403, detail=(
            "This is a team seat - billing is managed by your team owner's account."))


def _get_razorpay_client(settings):
    if razorpay is None:
        raise HTTPException(status_code=503, detail="Payment system not configured")
    client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
    client._update_user_agent_header = lambda opts: {
        **opts,
        'headers': {**opts.get('headers', {}), 'User-Agent': 'Razorpay-Python/2.0.1'},
    }
    return client


@router.get("/plans")
async def list_plans():
    supabase = get_supabase_admin()
    try:
        try:
            resp = supabase.table("plans").select("id,name,leads_per_day,searches_per_day,searches_per_month,leads_per_month,ai_calls_monthly,gmb_leads_monthly,linkedin_hq_leads_monthly,linkedin_posts_monthly,billing_cycle_days,sort_order,price_monthly").order("sort_order").execute()
        except Exception as col_err:
            # Pre-v16 / partial schema (e.g. missing billing_cycle_days):
            # fall back to whole-row read rather than 500ing public pricing.
            logger.warning("plans column select failed, falling back to *: %s", col_err)
            resp = supabase.table("plans").select("*").order("sort_order").execute()
        return {"plans": resp.data or []}
    except Exception as e:
        logger.error(f"Failed to fetch plans: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch plans")


@router.get("/current")
async def get_current_subscription(current_user: dict = Depends(get_current_user)):
    from app.services.plans import build_subscription_summary

    try:
        return await asyncio.to_thread(build_subscription_summary, get_supabase_admin(), current_user["id"])
    except Exception as e:
        logger.error(f"Failed to get subscription: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch subscription")


@router.post("/create-order")
async def create_order(
    plan_id: str = Body(..., embed=True),
    current_user: dict = Depends(get_current_user),
):
    settings = get_settings()

    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise HTTPException(status_code=500, detail="Payments not configured")

    if razorpay is None:
        raise HTTPException(status_code=500, detail="Razorpay SDK not installed")

    try:
        client = _get_razorpay_client(settings)
        supabase = get_supabase_admin()
        await asyncio.to_thread(_reject_team_member, supabase, current_user["id"])
        plan_resp = supabase.table("plans").select("*").eq("id", plan_id).limit(1).execute()
        if not plan_resp.data or len(plan_resp.data) == 0:
            raise HTTPException(status_code=404, detail="Plan not found")

        plan = plan_resp.data[0]
        amount = _razorpay_amount_for_plan(settings, plan_id)

        if amount <= 0:
            raise HTTPException(status_code=400, detail="Cannot create order for free plan")

        user_short = current_user["id"].replace("-", "")[:12]
        order = await asyncio.to_thread(client.order.create, {
            "amount": amount,
            "currency": "INR",
            "receipt": f"sub_{user_short}_{plan_id}",
            "notes": {
                "user_id": current_user["id"],
                "plan_id": plan_id,
                "plan_name": plan["name"],
            },
        })

        # Ledger first: this is what makes an abandoned-then-paid order
        # recoverable after a newer checkout overwrites the single slot below.
        _record_payment_order(
            supabase, order["id"], current_user["id"], plan_id, amount
        )

        existing_sub = _target_subscription_row(supabase, current_user["id"])

        if existing_sub:
            supabase.table("user_subscriptions").update({
                "razorpay_order_id": order["id"],
            }).eq("id", existing_sub["id"]).execute()
        else:
            supabase.table("user_subscriptions").insert({
                "user_id": current_user["id"],
                "plan_id": "free",
                "razorpay_order_id": order["id"],
                "status": "pending",
            }).execute()

        return {
            "order_id": order["id"],
            "amount": amount,
            "currency": "INR",
            "key_id": settings.razorpay_key_id,
            "plan_name": plan["name"],
            "plan_id": plan_id,
        }

    except HTTPException:
        raise
    except ImportError:
        raise HTTPException(status_code=500, detail="Razorpay SDK not installed")
    except Exception as e:
        logger.error(f"Failed to create order: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Payment processing failed")


@router.post("/verify")
async def verify_payment(
    data: dict,
    current_user: dict = Depends(get_current_user),
):
    settings = get_settings()

    razorpay_order_id = data.get("razorpay_order_id")
    razorpay_payment_id = data.get("razorpay_payment_id")
    razorpay_signature = data.get("razorpay_signature")

    if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
        raise HTTPException(status_code=400, detail="Missing payment verification fields")
    # Strict string typing: int/None ids would crash hmac.encode with a 500.
    # Reject them as 400 instead.
    if not all(isinstance(v, str) for v in (razorpay_order_id, razorpay_payment_id, razorpay_signature)):
        raise HTTPException(status_code=400, detail="Invalid payment verification fields")

    expected_signature = hmac.new(
        settings.razorpay_key_secret.encode(),
        f"{razorpay_order_id}|{razorpay_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, razorpay_signature or ""):
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    supabase = get_supabase_admin()

    try:
        # Bind the payment to the authenticated user's order. The browser never
        # selects the activated plan. The ledger resolves the order even when a
        # newer checkout has since overwritten the single subscription slot.
        resolved = _resolve_order_owner(supabase, razorpay_order_id)
        if not resolved or resolved.get("user_id") != current_user["id"]:
            raise HTTPException(status_code=400, detail="Payment order does not belong to this account")
        client = _get_razorpay_client(settings)
        order = await asyncio.to_thread(client.order.fetch, razorpay_order_id)
        notes = order.get("notes") or {}
        plan_id = notes.get("plan_id")
        if not plan_id and resolved.get("source") == "payment_orders":
            plan_id = resolved.get("plan_id")
        if notes.get("user_id") and notes.get("user_id") != current_user["id"]:
            raise HTTPException(status_code=400, detail="Invalid payment order metadata")
        if not plan_id:
            raise HTTPException(status_code=400, detail="Invalid payment order metadata")

        # Server-side capture + amount verification. The HMAC proves Razorpay
        # produced the payload, but only a live payment fetch proves the money
        # actually moved and equals the plan price — never trust the client.
        try:
            payment = await asyncio.to_thread(client.payment.fetch, razorpay_payment_id)
        except Exception as pay_exc:
            logger.error(f"Razorpay payment fetch failed for {razorpay_payment_id}: {pay_exc}")
            raise HTTPException(status_code=502, detail="Could not verify payment with Razorpay")
        pay_status = (payment or {}).get("status", "")
        if pay_status != "captured":
            logger.warning(f"Payment {razorpay_payment_id} not captured (status={pay_status})")
            raise HTTPException(status_code=400, detail="Payment has not been captured yet")
        pay_amount = int((payment or {}).get("amount", 0) or 0)
        expected_amount = _razorpay_amount_for_plan(settings, plan_id)
        if pay_amount != expected_amount:
            logger.warning(
                f"Payment amount mismatch: got {pay_amount}, expected {expected_amount} for {plan_id}"
            )
            raise HTTPException(status_code=400, detail="Payment amount does not match plan price")

        plan_resp = supabase.table("plans").select("*").eq("id", plan_id).limit(1).execute()
        if not plan_resp.data or len(plan_resp.data) == 0:
            raise HTTPException(status_code=404, detail="Plan not found")

        plan = plan_resp.data[0]
        billing_cycle_days = plan.get("billing_cycle_days", 30) or 30

        now = datetime.now(timezone.utc)
        period_end = now + timedelta(days=int(billing_cycle_days))

        sub_data = {
            "plan_id": plan_id,
            "status": "active",
            "razorpay_order_id": razorpay_order_id,
            "current_period_start": now.isoformat(),
            "current_period_end": period_end.isoformat(),
            "razorpay_payment_id": razorpay_payment_id,
        }

        existing = _target_subscription_row(supabase, current_user["id"])
        if existing:
            supabase.table("user_subscriptions").update(sub_data).eq(
                "id", existing["id"]
            ).execute()
        else:
            sub_data["user_id"] = current_user["id"]
            supabase.table("user_subscriptions").insert(sub_data).execute()

        _mark_payment_order_paid(supabase, razorpay_order_id, razorpay_payment_id)

        return {
            "status": "success",
            "plan_id": plan_id,
            "plan_name": plan["name"],
            "message": f"Upgraded to {plan['name']} plan",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Payment verification failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Payment verification failed")


@router.post("/webhook")
async def razorpay_webhook(request: Request):
    settings = get_settings()

    body = await request.body()
    received_signature = request.headers.get("X-Razorpay-Signature", "")

    if not received_signature:
        raise HTTPException(status_code=400, detail="Missing signature")

    expected_signature = hmac.new(
        settings.razorpay_key_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, received_signature or ""):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    # Bound before the try so the failure handler can always release the
    # idempotency claim (they used to be undefined if the body was malformed).
    event_id = ""
    event_recorded = False
    supabase = None
    try:
        event = json.loads(body)
        event_type = event.get("event", "")
        payload = event.get("payload", {})
        event_id = event.get("id", "")

        logger.info(f"Razorpay webhook: {event_type} (event_id={event_id[:24] or 'unknown'})")

        supabase = get_supabase_admin()

        # Idempotency: never process the same Razorpay event twice. Best-effort
        # — if the payment_events table does not exist yet (migration pending),
        # log and continue rather than failing the whole webhook. The row is a
        # CLAIM: it is released on failure so a Razorpay retry can still
        # process the event (see the handler below).
        if event_id:
            try:
                seen = supabase.table("payment_events").select("id").eq("event_id", event_id).limit(1).execute()
                if seen.data and len(seen.data) > 0:
                    return {"status": "ok", "duplicate": True}
                try:
                    supabase.table("payment_events").insert({"event_id": event_id, "event_type": event_type}).execute()
                    event_recorded = True
                except Exception as e:
                    logger.warning(f"Could not record payment event {event_id}: {e}")
            except Exception as e:
                logger.warning(f"payment_events table unavailable (idempotency disabled): {e}")

        if event_type == "payment.captured":
            order_id = payload.get("payment", {}).get("entity", {}).get("order_id", "")
            payment_id = payload.get("payment", {}).get("entity", {}).get("id", "")
            payment_status = payload.get("payment", {}).get("entity", {}).get("status", "")
            if order_id and payment_id:
                if payment_status and payment_status != "captured":
                    logger.warning(f"Ignoring payment {payment_id}: status={payment_status} (not captured)")
                    return {"status": "ok", "ignored": "not captured"}
                # Resolve the order through the ledger first: a checkout that
                # started later used to overwrite the single subscription slot,
                # which made this webhook silently drop a payment that HAD been
                # captured (customer charged, plan never activated).
                resolved = _resolve_order_owner(supabase, order_id)
                if not resolved:
                    logger.warning(
                        "Webhook for unknown order %s — no ledger entry or subscription row",
                        order_id,
                    )
                    return {"status": "ok"}
                order_user_id = resolved.get("user_id")
                if order_user_id:
                    order = _get_razorpay_client(settings).order.fetch(order_id)
                    notes = order.get("notes") or {}
                    plan_id = notes.get("plan_id")
                    if not plan_id and resolved.get("source") == "payment_orders":
                        plan_id = resolved.get("plan_id")
                    if not plan_id:
                        logger.warning("Ignoring payment without plan metadata: %s", order_id)
                        return {"status": "ok"}
                    if plan_id == "api_wallet":
                        # Public-API wallet top-up (not a plan): credit the
                        # wallet - idempotent, so a browser verify that
                        # already credited it makes this a no-op.
                        from app.routers.developer import WalletPaymentError, credit_wallet_from_payment
                        try:
                            credit_wallet_from_payment(
                                supabase, _get_razorpay_client(settings), order_id, payment_id)
                        except WalletPaymentError as wallet_exc:
                            if wallet_exc.status >= 500:
                                raise  # Razorpay unreachable: non-2xx -> redelivered later
                            logger.warning("Wallet top-up webhook ignored for %s: %s", order_id, wallet_exc)
                        return {"status": "ok"}
                    # Amount + capture verification: never activate a plan unless
                    # the captured amount matches the configured price and the
                    # payment actually succeeded with Razorpay.
                    try:
                        payment = _get_razorpay_client(settings).payment.fetch(payment_id)
                        pay_status = (payment or {}).get("status", "")
                        pay_amount = int((payment or {}).get("amount", 0) or 0)
                        if pay_status != "captured":
                            logger.warning("Payment %s not captured (status=%s) — plan NOT activated", payment_id, pay_status)
                            return {"status": "ok", "ignored": "payment not captured"}
                        expected_amount = _razorpay_amount_for_plan(settings, plan_id)
                        if pay_amount != expected_amount:
                            logger.warning(
                                "Payment %s amount mismatch: got %s expected %s — plan NOT activated",
                                payment_id, pay_amount, expected_amount,
                            )
                            return {"status": "ok", "ignored": "amount mismatch"}
                    except Exception as amt_exc:
                        # Raise so the outer handler answers non-2xx: Razorpay
                        # then redelivers instead of dropping the payment.
                        raise RuntimeError(
                            f"Could not verify payment {payment_id} via Razorpay: {amt_exc}"
                        ) from amt_exc

                    # Activate on the user's real (deterministically chosen)
                    # row. The period is extended once per PAYMENT id, so a
                    # redelivered event for the same payment never double-extends
                    # while a genuine renewal still does.
                    now = datetime.now(timezone.utc)
                    update_fields = {
                        "status": "active",
                        "razorpay_payment_id": payment_id,
                        "plan_id": plan_id,
                    }
                    target = None
                    if resolved.get("subscription_id"):
                        target = {"id": resolved["subscription_id"]}
                    if target is None:
                        target = _target_subscription_row(supabase, order_user_id)
                    if target is not None:
                        try:
                            cur = (
                                supabase.table("user_subscriptions")
                                .select("id, razorpay_payment_id")
                                .eq("id", target["id"])
                                .limit(1)
                                .execute()
                            )
                            already_applied = bool(
                                cur.data and cur.data[0].get("razorpay_payment_id") == payment_id
                            )
                        except Exception:
                            already_applied = False
                        if not already_applied:
                            cycle_days = 30
                            try:
                                plan_resp = supabase.table("plans").select("billing_cycle_days").eq("id", plan_id).limit(1).execute()
                                if plan_resp.data and len(plan_resp.data) > 0:
                                    cycle_days = plan_resp.data[0].get("billing_cycle_days", 30) or 30
                            except Exception as cycle_err:
                                logger.debug("billing_cycle_days lookup failed, using 30: %s", cycle_err)
                            update_fields["current_period_start"] = now.isoformat()
                            update_fields["current_period_end"] = (now + timedelta(days=int(cycle_days))).isoformat()

                        supabase.table("user_subscriptions").update(update_fields).eq("id", target["id"]).execute()
                    else:
                        cycle_days = 30
                        try:
                            plan_resp = supabase.table("plans").select("billing_cycle_days").eq("id", plan_id).limit(1).execute()
                            if plan_resp.data and len(plan_resp.data) > 0:
                                cycle_days = plan_resp.data[0].get("billing_cycle_days", 30) or 30
                        except Exception as cycle_err:
                            logger.debug("billing_cycle_days lookup failed, using 30: %s", cycle_err)
                        insert_fields = dict(update_fields)
                        insert_fields.update({
                            "user_id": order_user_id,
                            "razorpay_order_id": order_id,
                            "current_period_start": now.isoformat(),
                            "current_period_end": (now + timedelta(days=cycle_days)).isoformat(),
                        })
                        supabase.table("user_subscriptions").insert(insert_fields).execute()

                    _mark_payment_order_paid(supabase, order_id, payment_id)

        elif event_type == "subscription.charged":
            # Not used by the current one-time-order payment flow; logged for
            # visibility rather than acting on data this integration never sets.
            logger.info(f"Ignoring subscription.charged: recurring subscriptions are not in use")

        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook processing failed: {e}", exc_info=True)
        # A 200 here told Razorpay "delivered" — so a transient failure (a
        # Supabase hiccup, a timeout fetching the payment) silently left a
        # paying customer without their plan and was never retried. Release the
        # idempotency claim and answer with a non-2xx so the event is redelivered.
        if event_recorded and event_id and supabase is not None:
            try:
                supabase.table("payment_events").delete().eq("event_id", event_id).execute()
                logger.info(f"Released webhook idempotency claim for {event_id[:24]}")
            except Exception as cleanup_err:
                logger.warning(
                    f"Could not release webhook claim {event_id[:24]}: {cleanup_err}"
                )
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Webhook processing failed"},
        )


@router.post("/cancel")
async def cancel_subscription(current_user: dict = Depends(get_current_user)):
    supabase = get_supabase_admin()
    await asyncio.to_thread(_reject_team_member, supabase, current_user["id"])

    try:
        target = _target_subscription_row(supabase, current_user["id"])
        if not target or target.get("status") != "active":
            return {"status": "cancelled", "message": "No active subscription to cancel"}
        supabase.table("user_subscriptions").update({
            "status": "cancelled",
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", target["id"]).execute()
        return {"status": "cancelled", "message": "Subscription cancelled"}
    except Exception as e:
        logger.error(f"Failed to cancel subscription: {e}")
        raise HTTPException(status_code=500, detail="Failed to cancel subscription")
