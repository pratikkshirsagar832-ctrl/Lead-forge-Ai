"""Hyperclients Public API v1.

Authenticated with API keys (``Authorization: Bearer hc_live_...``). Billing:
prepaid wallet, charged per DELIVERED lead (LinkedIn ₹50 ≈ $0.52, Google Maps
₹5 ≈ $0.052 by default). Creating a search holds ``leads × price``; when the search finishes
only delivered leads are charged and the rest is released.

Full guide: docs/14-PUBLIC-API.md  ·  Interactive reference: /v1/docs
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.database import get_supabase_admin
from app.middleware.api_key_auth import ApiError, get_api_user
from app.services import api_public, api_wallet

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["Public API v1"])

LINKEDIN_MAX_LEADS = 10
_BACKGROUND: set[asyncio.Task] = set()  # strong refs: running Maps pipelines
MAPS_MAX_LEADS = 100


# ------------------------------------------------------------------ models

class CreateSearchRequest(BaseModel):
    """Start a lead search. Leads are delivered asynchronously - poll
    `GET /v1/searches/{id}` or pass a `webhook_url`."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"source": "linkedin", "service": "video editing", "mode": "freelancer", "leads": 5,
         "webhook_url": "https://example.com/hooks/hyperclients"},
        {"source": "google_maps", "service": "dentists", "location": "Pune, India", "leads": 50},
    ]})

    source: Literal["linkedin", "google_maps"] = Field(
        ..., description="`linkedin`: people posting that they NEED your service. "
                         "`google_maps`: local businesses to prospect.")
    service: str = Field(..., min_length=2, max_length=200,
                         description="LinkedIn: the service YOU sell, in any words (e.g. `video editing`, "
                                     "`I am a CA`). Google Maps: the business type to find (e.g. `dentists`).")
    leads: int = Field(..., ge=1, le=MAPS_MAX_LEADS,
                       description=f"Exact number of leads wanted. LinkedIn 1-{LINKEDIN_MAX_LEADS}, "
                                   f"Google Maps 1-{MAPS_MAX_LEADS}.")
    mode: Literal["freelancer", "agency"] = Field(
        "freelancer", description="LinkedIn only. `freelancer`: posts needing an individual. "
                                  "`agency`: clients looking for an agency/firm.")
    location: str | None = Field(None, max_length=300,
                                 description="Google Maps only (required), e.g. `Austin, TX`.")
    webhook_url: str | None = Field(None, max_length=500,
                                    description="Optional https URL called when the search finishes.")

    @field_validator("service")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("service must be at least 2 characters")
        return v

    @model_validator(mode="after")
    def _per_source(self) -> "CreateSearchRequest":
        if self.source == "linkedin" and self.leads > LINKEDIN_MAX_LEADS:
            raise ValueError(f"LinkedIn searches support 1-{LINKEDIN_MAX_LEADS} leads per call")
        if self.source == "google_maps" and not (self.location or "").strip():
            raise ValueError("location is required for google_maps searches")
        return self


# ---------------------------------------------------------------- helpers

def _db():
    return get_supabase_admin()


async def _load_search(supabase, user: dict[str, Any], search_id: str) -> dict[str, Any]:
    try:
        uuid.UUID(search_id)
    except ValueError:
        raise ApiError(404, "not_found", "Search not found.")
    rows = await asyncio.to_thread(
        lambda: supabase.table("searches").select("*").eq("id", search_id).limit(1).execute().data or []
    )
    row = rows[0] if rows else None
    if not row or row.get("user_id") != user["id"] or row.get("billing") != "api":
        raise ApiError(404, "not_found", "Search not found.")
    return row


# -------------------------------------------------------------- endpoints

@router.post("/searches", status_code=202, summary="Create a lead search")
async def create_search(body: CreateSearchRequest, user: dict = Depends(get_api_user)) -> dict[str, Any]:
    """Holds `leads × price` from your wallet, then starts the search.

    You are charged **only for leads delivered**; the unused part of the hold
    is released when the search finishes (or is cancelled/fails)."""
    supabase = _db()
    err = api_public.validate_webhook_url(body.webhook_url)
    if err:
        raise ApiError(400, "invalid_request", err, param="webhook_url")

    price = api_wallet.price_per_lead_paise(body.source)
    hold_amount = price * body.leads
    search_id = str(uuid.uuid4())
    is_linkedin = body.source == "linkedin"
    row = {
        "id": search_id,
        "user_id": user["id"],
        "niche": body.service,
        "location": "Global" if is_linkedin else (body.location or "").strip(),
        "source": body.source,
        "status": "queued",
        "message": "Search queued",
        "enrich_emails": False,
        "max_results": body.leads,
        "lead_types": [body.mode] if is_linkedin else [],
        "quota_source": "linkedin" if is_linkedin else "google_maps",
        "reserved_leads": body.leads,  # engines never deliver more than this
        "billing": "api",
        "api_key_id": user["api_key_id"],
        "price_per_lead_paise": price,
        "webhook_url": body.webhook_url,
    }
    try:
        await asyncio.to_thread(lambda: supabase.table("searches").insert(row).execute())
    except Exception as exc:
        logger.error("API search insert failed: %s", exc)
        raise ApiError(500, "internal_error", "Could not create the search. Please retry.")

    try:
        held = await asyncio.to_thread(api_wallet.hold, supabase, user["id"], search_id, hold_amount)
    except Exception as exc:
        logger.error("API wallet hold failed for %s: %s", search_id, exc)
        held = None
    if not held:
        await asyncio.to_thread(lambda: supabase.table("searches").delete().eq("id", search_id).execute())
        if held is None:
            raise ApiError(500, "internal_error", "Could not reserve wallet funds. Please retry.")
        wallet = await asyncio.to_thread(api_wallet.get_wallet, supabase, user["id"], 0)
        raise ApiError(
            402, "insufficient_balance",
            f"This search needs ₹{api_wallet.inr(hold_amount):,.2f} "
            f"(~${api_wallet.usd_for_leads(body.source, body.leads):,.2f}) available "
            f"({body.leads} × ₹{api_wallet.inr(price):,.2f}); you have ₹{wallet['available_inr']:,.2f}. "
            "Top up your wallet in the Hyperclients dashboard.",
            required_inr=api_wallet.inr(hold_amount), available_inr=wallet["available_inr"],
            required_usd=api_wallet.usd_for_leads(body.source, body.leads),
        )

    if is_linkedin:
        from app.services.hyperagent_service import ha_lead_type_from, ha_time_window_from, run_hyperagent_pipeline

        await asyncio.to_thread(
            run_hyperagent_pipeline,
            search_id=search_id, user_id=user["id"], service=body.service, country="",
            lead_type=ha_lead_type_from([body.mode]), time_window=ha_time_window_from(),
            leads_needed=body.leads, all_types=False,
        )
    else:
        from app.services.pipeline import run_search_pipeline

        task = asyncio.create_task(run_search_pipeline(
            search_id=search_id, user_id=user["id"], niche=body.service,
            location=(body.location or "").strip(), max_results=body.leads,
        ))
        _BACKGROUND.add(task)
        task.add_done_callback(_BACKGROUND.discard)

    wallet = await asyncio.to_thread(api_wallet.get_wallet, supabase, user["id"], 0)
    result = api_public.serialize_search({**row, "created_at": datetime.now(timezone.utc).isoformat()},
                                         delivered=0)
    result["wallet"] = {"balance_inr": wallet["balance_inr"], "available_inr": wallet["available_inr"]}
    return result


@router.get("/searches/{search_id}", summary="Get a search (status + billing)")
async def get_search(search_id: str = Path(..., description="Search id returned on create"),
                     user: dict = Depends(get_api_user)) -> dict[str, Any]:
    """Poll this until `status` is `completed`, `failed` or `cancelled`
    (every 5-10 seconds is plenty)."""
    supabase = _db()
    row = await _load_search(supabase, user, search_id)
    delivered = await asyncio.to_thread(api_public.count_leads, supabase, row)
    return api_public.serialize_search(row, delivered=delivered)


@router.get("/searches/{search_id}/leads", summary="Get the leads of a search")
async def get_search_leads(search_id: str, user: dict = Depends(get_api_user)) -> dict[str, Any]:
    """Leads found so far (all of them once the search is `completed`)."""
    supabase = _db()
    row = await _load_search(supabase, user, search_id)
    leads = await asyncio.to_thread(api_public.fetch_leads, supabase, row)
    return {"object": "list", "search_id": search_id, "status": api_public.public_status(row.get("status")),
            "count": len(leads), "data": leads}


@router.post("/searches/{search_id}/cancel", summary="Cancel a running search")
async def cancel_search(search_id: str, user: dict = Depends(get_api_user)) -> dict[str, Any]:
    """Stops the search. You are charged only for leads already delivered;
    the rest of the hold is released immediately."""
    supabase = _db()
    row = await _load_search(supabase, user, search_id)
    if api_public.public_status(row.get("status")) in api_public.TERMINAL:
        raise ApiError(409, "invalid_state", f"Search is already {api_public.public_status(row.get('status'))}.")
    if row.get("source") == "linkedin":
        from app.services.hyperagent_service import request_cancel
        request_cancel(search_id)
    else:
        from app.services.pipeline import cancel_search as cancel_maps
        cancel_maps(search_id)
    await asyncio.to_thread(lambda: supabase.table("searches").update({
        "status": "cancelled", "message": "Search cancelled via API",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", search_id).not_.in_("status", list(api_public.TERMINAL)).execute())
    delivered = await asyncio.to_thread(api_public.count_leads, supabase, row)
    from app.services.usage import settle_search_quota
    await settle_search_quota(supabase, search_id, user["id"], delivered)
    row = await _load_search(supabase, user, search_id)
    return api_public.serialize_search(row, delivered=delivered)


@router.get("/searches", summary="List your API searches")
async def list_searches(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: Literal["queued", "running", "completed", "failed", "cancelled"] | None = Query(None),
    user: dict = Depends(get_api_user),
) -> dict[str, Any]:
    supabase = _db()

    def _q():
        q = (supabase.table("searches").select("*", count="exact")
             .eq("user_id", user["id"]).eq("billing", "api"))
        if status in ("completed", "failed", "cancelled", "queued"):
            q = q.eq("status", status)
        elif status == "running":
            q = q.not_.in_("status", ["queued", *api_public.TERMINAL])
        return q.order("created_at", desc=True).range(offset, offset + limit - 1).execute()

    resp = await asyncio.to_thread(_q)
    return {"object": "list", "total": int(resp.count or 0), "limit": limit, "offset": offset,
            "data": [api_public.serialize_search(r) for r in (resp.data or [])]}


@router.get("/wallet", summary="Wallet balance + recent transactions")
async def get_wallet(user: dict = Depends(get_api_user)) -> dict[str, Any]:
    return await asyncio.to_thread(api_wallet.get_wallet, _db(), user["id"], 50)
