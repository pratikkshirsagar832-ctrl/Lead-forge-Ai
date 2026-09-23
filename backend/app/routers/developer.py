"""Developer dashboard: API keys + prepaid API wallet (JWT-authenticated).

Endpoints (logged-in web users):
  GET    /api/developer/keys            list API keys (never the secret)
  POST   /api/developer/keys            create a key (raw key shown ONCE)
  DELETE /api/developer/keys/{id}       revoke a key
  GET    /api/developer/wallet          balance, held, prices, ledger
  POST   /api/developer/wallet/topup    start a Razorpay top-up order
  POST   /api/developer/wallet/verify   verify the payment + credit the wallet
  GET    /api/developer/usage           recent API searches (for the dashboard)
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from app.config import get_settings
from app.database import get_supabase_admin
from app.middleware.auth_middleware import get_current_user
from app.services import api_keys, api_public, api_wallet

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/developer", tags=["Developer"])

WALLET_PLAN_ID = "api_wallet"  # payment_orders.plan_id marker for wallet top-ups


# ------------------------------------------------------------------ keys

@router.get("/keys")
async def list_keys(current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    keys = await asyncio.to_thread(api_keys.list_keys, get_supabase_admin(), current_user["id"])
    return {"keys": keys}


@router.post("/keys", status_code=201)
async def create_key(name: str = Body("Default key", embed=True),
                     current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(api_keys.create_key, get_supabase_admin(), current_user["id"], name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/keys/{key_id}")
async def revoke_key(key_id: str, current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    ok = await asyncio.to_thread(api_keys.revoke_key, get_supabase_admin(), current_user["id"], key_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Key not found or already revoked")
    return {"revoked": True, "id": key_id}


# ---------------------------------------------------------------- wallet

@router.get("/wallet")
async def get_wallet(current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    settings = get_settings()
    wallet = await asyncio.to_thread(api_wallet.get_wallet, get_supabase_admin(), current_user["id"], 50)
    wallet["topup_limits_inr"] = {"min": settings.api_min_topup_inr, "max": settings.api_max_topup_inr}
    return wallet


@router.get("/usage")
async def api_usage(current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    supabase = get_supabase_admin()
    rows = await asyncio.to_thread(
        lambda: supabase.table("searches").select("*").eq("user_id", current_user["id"])
        .eq("billing", "api").order("created_at", desc=True).limit(50).execute().data or []
    )
    return {"searches": [api_public.serialize_search(r) for r in rows]}


@router.post("/wallet/topup")
async def create_topup(amount_inr: int = Body(..., embed=True),
                       current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    settings = get_settings()
    if not (settings.api_min_topup_inr <= amount_inr <= settings.api_max_topup_inr):
        raise HTTPException(
            status_code=400,
            detail=f"Top-up must be between ₹{settings.api_min_topup_inr:,} and ₹{settings.api_max_topup_inr:,}",
        )
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise HTTPException(status_code=500, detail="Payments not configured")
    from app.routers.subscriptions import _get_razorpay_client, _record_payment_order

    supabase = get_supabase_admin()
    amount_paise = int(amount_inr) * 100
    try:
        client = _get_razorpay_client(settings)
        order = await asyncio.to_thread(client.order.create, {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": f"apiw_{current_user['id'].replace('-', '')[:12]}",
            "notes": {"user_id": current_user["id"], "plan_id": WALLET_PLAN_ID, "purpose": "api_wallet_topup"},
        })
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Wallet top-up order failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Payment processing failed")
    await asyncio.to_thread(_record_payment_order, supabase, order["id"], current_user["id"],
                            WALLET_PLAN_ID, amount_paise)
    return {"order_id": order["id"], "amount": amount_paise, "currency": "INR",
            "key_id": settings.razorpay_key_id, "purpose": "api_wallet_topup"}


@router.post("/wallet/verify")
async def verify_topup(data: dict, current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    settings = get_settings()
    order_id = data.get("razorpay_order_id")
    payment_id = data.get("razorpay_payment_id")
    signature = data.get("razorpay_signature")
    if not all(isinstance(v, str) and v for v in (order_id, payment_id, signature)):
        raise HTTPException(status_code=400, detail="Missing payment verification fields")
    expected = hmac.new(settings.razorpay_key_secret.encode(), f"{order_id}|{payment_id}".encode(),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    supabase = get_supabase_admin()
    from app.routers.subscriptions import _get_razorpay_client

    try:
        balance = await asyncio.to_thread(
            credit_wallet_from_payment, supabase, _get_razorpay_client(settings),
            order_id, payment_id, current_user["id"],
        )
    except WalletPaymentError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    return {"credited": True, "balance_inr": api_wallet.inr(balance)}


class WalletPaymentError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def credit_wallet_from_payment(supabase, client, order_id: str, payment_id: str,
                               expected_user_id: str | None = None) -> int:
    """Credit an API wallet for a CAPTURED Razorpay payment of a wallet
    top-up order. Shared by the browser verify call and the Razorpay webhook;
    idempotent (a payment credits once). Returns the new balance in paise."""
    from app.routers.subscriptions import _mark_payment_order_paid

    rows = (supabase.table("payment_orders").select("user_id,plan_id,amount")
            .eq("order_id", order_id).limit(1).execute().data or [])
    order_row = rows[0] if rows else None
    if not order_row or order_row.get("plan_id") != WALLET_PLAN_ID:
        raise WalletPaymentError(400, "Unknown wallet top-up order")
    user_id = order_row["user_id"]
    if expected_user_id and user_id != expected_user_id:
        raise WalletPaymentError(400, "Payment order does not belong to this account")
    try:
        payment = client.payment.fetch(payment_id)
    except Exception as exc:
        logger.error("Razorpay payment fetch failed for %s: %s", payment_id, exc)
        raise WalletPaymentError(502, "Could not verify payment with Razorpay")
    if (payment or {}).get("status") != "captured":
        raise WalletPaymentError(400, "Payment has not been captured yet")
    if (payment or {}).get("order_id") not in (None, "", order_id):
        raise WalletPaymentError(400, "Payment does not belong to this order")
    amount = int((payment or {}).get("amount", 0) or 0)
    if amount != int(order_row.get("amount") or 0) or amount <= 0:
        raise WalletPaymentError(400, "Payment amount does not match the top-up order")
    balance = api_wallet.credit(supabase, user_id, amount, payment_id, "topup",
                                f"Razorpay top-up {order_id}")
    _mark_payment_order_paid(supabase, order_id, payment_id)
    logger.info("API wallet top-up: user=%s +%d paise (payment %s)", user_id[:8], amount, payment_id)
    return balance
