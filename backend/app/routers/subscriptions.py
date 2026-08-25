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


def _get_razorpay_client(settings):
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
    supabase = get_supabase_admin()

    from datetime import date

    # Compute correct remaining counts from actual table state
    today = date.today().isoformat()
    usage_resp = supabase.table("daily_usage") \
        .select("searches_run, leads_generated") \
        .eq("user_id", current_user["id"]) \
        .eq("date", today) \
        .execute()
    used = usage_resp.data[0] if usage_resp.data and len(usage_resp.data) > 0 else {}
    used_searches = used.get("searches_run", 0) or 0
    used_leads = used.get("leads_generated", 0) or 0

    try:
        resp = supabase.rpc(
            "get_user_subscription",
            {"p_user_id": current_user["id"]},
        ).execute()

        if resp and resp.data:
            data = resp.data
            searches_per_day = data.get("searches_per_day", 3)
            leads_per_day = data.get("leads_per_day", 30)
            data["remaining_searches"] = max(0, searches_per_day - used_searches)
            data["remaining_leads"] = max(0, leads_per_day - used_leads)
            return data
    except Exception as e:
        logger.warning(f"RPC get_user_subscription failed: {e}")

    # Fallback: query tables directly
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

            from datetime import date
            today = date.today().isoformat()
            usage_resp = supabase.table("daily_usage") \
                .select("searches_run, leads_generated") \
                .eq("user_id", current_user["id"]) \
                .eq("date", today) \
                .execute()

            used = usage_resp.data[0] if usage_resp.data else {}
            searches_per_day = plan.get("searches_per_day", 3)
            leads_per_day = plan.get("leads_per_day", 30)

            return {
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

        return {
            "plan_id": "free",
            "plan_name": "Free",
            "leads_per_day": 30,
            "searches_per_day": 3,
            "status": "trial",
            "remaining_searches": 3,
            "remaining_leads": 30,
            "is_trial_expired": False,
        }
    except Exception as e:
        logger.error(f"Failed to get subscription: {e}")
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
        # price_monthly is stored in USD CENTS (display pricing is USD).
        # Razorpay settles in INR for Indian accounts, so convert at a
        # fixed rate: usd_cents x rate = INR paise (e.g. $19 -> Rs.1672).
        USD_TO_INR_RATE = 88
        amount = int(int(plan["price_monthly"]) * USD_TO_INR_RATE)

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
    plan_id = data.get("plan_id")

    if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature, plan_id]):
        raise HTTPException(status_code=400, detail="Missing payment verification fields")

    expected_signature = hmac.new(
        settings.razorpay_key_secret.encode(),
        f"{razorpay_order_id}|{razorpay_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()

    if expected_signature != razorpay_signature:
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    supabase = get_supabase_admin()

    try:
        plan_resp = supabase.table("plans").select("*").eq("id", plan_id).limit(1).execute()
        if not plan_resp.data or len(plan_resp.data) == 0:
            raise HTTPException(status_code=404, detail="Plan not found")

        plan = plan_resp.data[0]
        billing_cycle_days = plan.get("billing_cycle_days", 30)

        now = datetime.now(timezone.utc)
        period_end = now + timedelta(days=int(billing_cycle_days))

        existing = supabase.table("user_subscriptions").select("id").eq("user_id", current_user["id"]).limit(1).execute()

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

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        existing_usage = supabase.table("daily_usage").select("searches_run").eq("user_id", current_user["id"]).eq("date", today_str).execute()
        if existing_usage.data and len(existing_usage.data) > 0:
            supabase.table("daily_usage").update({
                "searches_run": 0,
                "leads_generated": 0,
            }).eq("user_id", current_user["id"]).eq("date", today_str).execute()
        else:
            supabase.table("daily_usage").insert({
                "user_id": current_user["id"],
                "date": today_str,
                "searches_run": 0,
                "leads_generated": 0,
            }).execute()

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

    if received_signature != expected_signature:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        event = json.loads(body)
        event_type = event.get("event", "")
        payload = event.get("payload", {})

        logger.info(f"Razorpay webhook: {event_type}")

        supabase = get_supabase_admin()

        if event_type == "payment.captured":
            order_id = payload.get("payment", {}).get("entity", {}).get("order_id", "")
            payment_id = payload.get("payment", {}).get("entity", {}).get("id", "")
            if order_id and payment_id:
                # Idempotency check: skip if payment already processed
                existing = supabase.table("user_subscriptions").select("id, user_id").eq("razorpay_order_id", order_id).limit(1).execute()
                sub_data = existing.data[0] if existing.data and len(existing.data) > 0 else None
                if sub_data:
                    supabase.table("user_subscriptions").update({
                        "status": "active",
                        "razorpay_payment_id": payment_id,
                    }).eq("id", sub_data["id"]).execute()

                    # Reset daily usage so user gets full plan limits
                    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    supabase.table("daily_usage").delete().eq("user_id", sub_data["user_id"]).eq("date", today_str).execute()

        elif event_type == "subscription.charged":
            sub_id = payload.get("subscription", {}).get("entity", {}).get("id", "")
            if sub_id:
                existing = supabase.table("user_subscriptions").select("id, user_id").eq("razorpay_subscription_id", sub_id).limit(1).execute()
                if existing.data and len(existing.data) > 0:
                    sub_row = existing.data[0]
                    supabase.table("user_subscriptions").update({
                        "status": "active",
                    }).eq("id", sub_row["id"]).execute()

                    # Reset daily usage
                    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    supabase.table("daily_usage").delete().eq("user_id", sub_row["user_id"]).eq("date", today_str).execute()

        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Webhook processing failed")


@router.post("/cancel")
async def cancel_subscription(current_user: dict = Depends(get_current_user)):
    supabase = get_supabase_admin()

    try:
        supabase.table("user_subscriptions").update({
            "status": "cancelled",
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
        }).eq("user_id", current_user["id"]).execute()
        return {"status": "cancelled", "message": "Subscription cancelled"}
    except Exception as e:
        logger.error(f"Failed to cancel subscription: {e}")
        raise HTTPException(status_code=500, detail="Failed to cancel subscription")
