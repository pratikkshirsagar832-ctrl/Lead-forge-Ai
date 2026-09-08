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
        resp = supabase.table("plans").select("*").order("sort_order").execute()
        return {"plans": resp.data or []}
    except Exception as e:
        logger.error(f"Failed to fetch plans: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch plans")


@router.get("/current")
async def get_current_subscription(current_user: dict = Depends(get_current_user)):
    from app.services.plans import (
        resolve_effective_subscription,
        get_plan_row,
        get_used_today,
        get_latest_subscription_row,
    )

    supabase = get_supabase_admin()
    user_id = current_user["id"]

    try:
        eff = resolve_effective_subscription(supabase, user_id)
        plan_id = eff["plan_id"]
        status = eff["status"]

        plan = get_plan_row(supabase, plan_id)
        searches_per_day = plan.get("searches_per_day", 3) or 3
        leads_per_day = plan.get("leads_per_day", 30) or 30

        used_searches, used_leads = get_used_today(supabase, user_id)
        month = datetime.now(timezone.utc).replace(day=1).date().isoformat()
        usage = {}
        try:
            monthly = supabase.table("monthly_usage").select("*").eq("user_id", user_id).eq("usage_month", month).limit(1).execute()
            usage = (monthly.data or [{}])[0]
        except Exception as monthly_err:
            logger.debug(f"monthly_usage table not available: {monthly_err}")
        linkedin_limit = int(plan.get("linkedin_hq_leads_monthly", 0) or 0)
        gmb_limit = int(plan.get("gmb_leads_monthly", 0) or 0)

        source_row = eff.get("source_row") or get_latest_subscription_row(supabase, user_id) or {}

        return {
            "plan_id": plan_id,
            "plan_name": plan.get("name", "Free"),
            "status": status,
            "searches_per_day": searches_per_day,
            "leads_per_day": leads_per_day,
            "remaining_searches": max(0, searches_per_day - used_searches),
            "remaining_leads": max(0, leads_per_day - used_leads),
            "linkedin_hq_leads_monthly": linkedin_limit,
            "gmb_leads_monthly": gmb_limit,
            "linkedin_hq_leads_used": int(usage.get("linkedin_hq_generated", 0) or 0),
            "gmb_leads_used": int(usage.get("gmb_generated", 0) or 0),
            "linkedin_hq_leads_remaining": max(0, linkedin_limit - int(usage.get("linkedin_hq_generated", 0) or 0) - int(usage.get("linkedin_hq_reserved", 0) or 0)),
            "gmb_leads_remaining": max(0, gmb_limit - int(usage.get("gmb_generated", 0) or 0) - int(usage.get("gmb_reserved", 0) or 0)),
            "current_period_start": source_row.get("current_period_start"),
            "current_period_end": source_row.get("current_period_end"),
            "trial_end": source_row.get("trial_end"),
            "is_trial_expired": source_row.get("is_trial_expired", False),
        }
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
        plan_resp = supabase.table("plans").select("*").eq("id", plan_id).limit(1).execute()
        if not plan_resp.data or len(plan_resp.data) == 0:
            raise HTTPException(status_code=404, detail="Plan not found")

        plan = plan_resp.data[0]
        amount = _razorpay_amount_for_plan(settings, plan_id)

        if amount <= 0:
            raise HTTPException(status_code=400, detail="Cannot create order for free plan")

        user_short = current_user["id"].replace("-", "")[:12]
        order = client.order.create({
            "amount": amount,
            "currency": "INR",
            "receipt": f"sub_{user_short}_{plan_id}",
            "notes": {
                "user_id": current_user["id"],
                "plan_id": plan_id,
                "plan_name": plan["name"],
            },
        })

        existing_sub = supabase.table("user_subscriptions").select("id").eq("user_id", current_user["id"]).limit(1).execute()

        if existing_sub.data and len(existing_sub.data) > 0:
            sub_id = existing_sub.data[0]["id"]
            supabase.table("user_subscriptions").update({
                "razorpay_order_id": order["id"],
            }).eq("id", sub_id).execute()
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

    expected_signature = hmac.new(
        settings.razorpay_key_secret.encode(),
        f"{razorpay_order_id}|{razorpay_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, razorpay_signature or ""):
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    supabase = get_supabase_admin()

    try:
        # Bind the payment to the authenticated user's pending order. The
        # browser never selects the activated plan.
        pending = supabase.table("user_subscriptions").select("id, razorpay_order_id").eq(
            "user_id", current_user["id"]
        ).eq("razorpay_order_id", razorpay_order_id).limit(1).execute()
        if not pending.data:
            raise HTTPException(status_code=400, detail="Payment order does not belong to this account")
        client = _get_razorpay_client(settings)
        order = client.order.fetch(razorpay_order_id)
        notes = order.get("notes") or {}
        plan_id = notes.get("plan_id")
        if notes.get("user_id") != current_user["id"] or not plan_id:
            raise HTTPException(status_code=400, detail="Invalid payment order metadata")

        # Server-side capture + amount verification. The HMAC proves Razorpay
        # produced the payload, but only a live payment fetch proves the money
        # actually moved and equals the plan price — never trust the client.
        try:
            payment = client.payment.fetch(razorpay_payment_id)
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
        billing_cycle_days = plan.get("billing_cycle_days", 30)

        now = datetime.now(timezone.utc)
        period_end = now + timedelta(days=int(billing_cycle_days))

        existing = pending

        sub_data = {
            "plan_id": plan_id,
            "status": "active",
            "razorpay_order_id": razorpay_order_id,
            "current_period_start": now.isoformat(),
            "current_period_end": period_end.isoformat(),
        }

        if existing.data and len(existing.data) > 0:
            sub_data["razorpay_payment_id"] = razorpay_payment_id
            sub_id = existing.data[0]["id"]
            supabase.table("user_subscriptions").update(sub_data).eq("id", sub_id).execute()
        else:
            sub_data["user_id"] = current_user["id"]
            sub_data["razorpay_payment_id"] = razorpay_payment_id
            supabase.table("user_subscriptions").insert(sub_data).execute()

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

    try:
        event = json.loads(body)
        event_type = event.get("event", "")
        payload = event.get("payload", {})
        event_id = event.get("id", "")

        logger.info(f"Razorpay webhook: {event_type} (event_id={event_id[:24] or 'unknown'})")

        supabase = get_supabase_admin()

        # Idempotency: never process the same Razorpay event twice. Best-effort
        # — if the payment_events table does not exist yet (migration pending),
        # log and continue rather than failing the whole webhook.
        event_recorded = False
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
                existing = supabase.table("user_subscriptions").select("id, user_id, plan_id").eq("razorpay_order_id", order_id).limit(1).execute()
                sub_data = existing.data[0] if existing.data and len(existing.data) > 0 else None
                if sub_data:
                    order = _get_razorpay_client(settings).order.fetch(order_id)
                    notes = order.get("notes") or {}
                    plan_id = notes.get("plan_id")
                    if not plan_id:
                        logger.warning("Ignoring payment without plan metadata: %s", order_id)
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
                        logger.error(f"Could not verify payment {payment_id} via Razorpay: {amt_exc}")
                        return {"status": "error", "message": "Payment verification failed"}

                    # Look up plan to get billing cycle for period dates
                    now = datetime.now(timezone.utc)
                    update_fields = {
                        "status": "active",
                        "razorpay_payment_id": payment_id,
                        "plan_id": plan_id,
                    }
                    if not sub_data.get("razorpay_payment_id"):
                        plan_resp = supabase.table("plans").select("billing_cycle_days").eq("id", plan_id).limit(1).execute()
                        cycle_days = 30
                        if plan_resp.data and len(plan_resp.data) > 0:
                            cycle_days = plan_resp.data[0].get("billing_cycle_days", 30)
                        update_fields["current_period_start"] = now.isoformat()
                        update_fields["current_period_end"] = (now + timedelta(days=cycle_days)).isoformat()

                    supabase.table("user_subscriptions").update(update_fields).eq("id", sub_data["id"]).execute()

        elif event_type == "subscription.charged":
            # Not used by the current one-time-order payment flow; logged for
            # visibility rather than acting on data this integration never sets.
            logger.info(f"Ignoring subscription.charged: recurring subscriptions are not in use")

        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook processing failed: {e}", exc_info=True)
        return {"status": "error", "message": "Webhook processing failed"}


@router.post("/cancel")
async def cancel_subscription(current_user: dict = Depends(get_current_user)):
    supabase = get_supabase_admin()

    try:
        supabase.table("user_subscriptions").update({
            "status": "cancelled",
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
        }).eq("user_id", current_user["id"]).eq("status", "active").execute()
        return {"status": "cancelled", "message": "Subscription cancelled"}
    except Exception as e:
        logger.error(f"Failed to cancel subscription: {e}")
        raise HTTPException(status_code=500, detail="Failed to cancel subscription")
