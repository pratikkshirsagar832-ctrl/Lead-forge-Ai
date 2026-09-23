"""Prepaid API wallet (INR, stored in paise).

All money movement goes through the atomic SQL functions from
``supabase/migration_public_api_v20.sql``:

* ``hold``   — reserve ``leads × price`` when an API search starts
* ``settle`` — charge only DELIVERED leads × price, release the rest
* ``credit`` — Razorpay top-ups (idempotent per payment id) / adjustments
"""
from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

SOURCES = ("linkedin", "google_maps")


def price_per_lead_paise(source: str) -> int:
    settings = get_settings()
    inr = settings.api_price_linkedin_inr if source == "linkedin" else settings.api_price_maps_inr
    return int(inr) * 100


def inr(paise: int | float | None) -> float:
    return round(int(paise or 0) / 100.0, 2)


def get_wallet(supabase, user_id: str, ledger_limit: int = 20) -> dict[str, Any]:
    row = (
        supabase.table("api_wallets").select("balance_paise,held_paise,updated_at")
        .eq("user_id", user_id).limit(1).execute()
    )
    data = (row.data or [{}])[0] or {}
    balance = int(data.get("balance_paise") or 0)
    held = int(data.get("held_paise") or 0)
    ledger: list[dict[str, Any]] = []
    if ledger_limit > 0:
        led = (
            supabase.table("api_wallet_ledger")
            .select("kind,amount_paise,balance_after,search_id,note,created_at")
            .eq("user_id", user_id).order("created_at", desc=True).limit(ledger_limit).execute()
        )
        ledger = [
            {
                "type": r.get("kind"),
                "amount_inr": inr(r.get("amount_paise")),
                "balance_after_inr": inr(r.get("balance_after")),
                "search_id": r.get("search_id"),
                "note": r.get("note"),
                "created_at": r.get("created_at"),
            }
            for r in (led.data or [])
        ]
    return {
        "currency": "INR",
        "balance_inr": inr(balance),
        "held_inr": inr(held),
        "available_inr": inr(max(0, balance - held)),
        "prices": {
            "linkedin_per_lead_inr": inr(price_per_lead_paise("linkedin")),
            "google_maps_per_lead_inr": inr(price_per_lead_paise("google_maps")),
        },
        "ledger": ledger,
    }


def hold(supabase, user_id: str, search_id: str, amount_paise: int) -> bool:
    resp = supabase.rpc("api_wallet_hold", {
        "p_user_id": user_id, "p_search_id": search_id, "p_amount": int(amount_paise),
    }).execute()
    return bool(resp.data)


def settle(supabase, search_id: str, delivered: int) -> int:
    """Charge delivered leads, release the rest of the hold. Idempotent."""
    resp = supabase.rpc("api_wallet_settle", {
        "p_search_id": search_id, "p_delivered": max(0, int(delivered)),
    }).execute()
    try:
        return int(resp.data or 0)
    except (TypeError, ValueError):
        return 0


def credit(supabase, user_id: str, amount_paise: int, payment_id: str | None,
           kind: str = "topup", note: str | None = None) -> int:
    resp = supabase.rpc("api_wallet_credit", {
        "p_user_id": user_id, "p_amount": int(amount_paise), "p_payment_id": payment_id,
        "p_kind": kind, "p_note": note,
    }).execute()
    return int(resp.data or 0)
