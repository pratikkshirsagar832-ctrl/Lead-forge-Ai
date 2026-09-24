"""Admin: SocialCrawl API key pool (add / remove / enable / usage / balances).

Called server-to-server by the Next.js /admin panel with the shared
ADMIN_API_TOKEN (header X-Admin-Token). Keys are never returned, only their
last 4 characters.

  GET    /api/internal/admin/socialcrawl-keys           list + usage totals
  POST   /api/internal/admin/socialcrawl-keys           {key, label}  (validated live)
  PATCH  /api/internal/admin/socialcrawl-keys/{id}      {enabled: bool}
  DELETE /api/internal/admin/socialcrawl-keys/{id}
  POST   /api/internal/admin/socialcrawl-keys/refresh   live balance of every key (free)
"""
from __future__ import annotations

import asyncio
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.database import get_supabase_admin
from app.services import socialcrawl_keys as keys

router = APIRouter(prefix="/api/internal/admin/socialcrawl-keys", tags=["Admin"], include_in_schema=False)


def require_admin(x_admin_token: str = Header(default="")) -> None:
    expected = get_settings().admin_api_token
    if not expected:
        raise HTTPException(status_code=503, detail="Admin API is not configured (ADMIN_API_TOKEN).")
    if not hmac.compare_digest(x_admin_token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Unauthorized")


class KeyIn(BaseModel):
    key: str = Field(..., min_length=10, max_length=200)
    label: str = Field("", max_length=80)


class KeyPatch(BaseModel):
    enabled: bool


def _call(fn, *args):
    try:
        return fn(get_supabase_admin(), *args)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "socialcrawl_keys" in msg and ("does not exist" in msg or "schema cache" in msg):
            raise HTTPException(status_code=503, detail="Run supabase/migration_socialcrawl_keys_v23.sql first.")
        raise HTTPException(status_code=500, detail=f"Key store error: {msg[:200]}")


@router.get("", dependencies=[Depends(require_admin)])
async def list_keys():
    return await asyncio.to_thread(_call, keys.list_keys)


@router.post("", dependencies=[Depends(require_admin)], status_code=201)
async def add_key(body: KeyIn):
    return {"key": await asyncio.to_thread(_call, keys.add_key, body.key, body.label)}


@router.post("/refresh", dependencies=[Depends(require_admin)])
async def refresh():
    return await asyncio.to_thread(_call, keys.refresh_balances)


@router.patch("/{key_id}", dependencies=[Depends(require_admin)])
async def set_enabled(key_id: str, body: KeyPatch):
    row = await asyncio.to_thread(_call, keys.set_enabled, key_id, body.enabled)
    if not row:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"key": row}


@router.delete("/{key_id}", dependencies=[Depends(require_admin)])
async def remove_key(key_id: str):
    if not await asyncio.to_thread(_call, keys.remove_key, key_id):
        raise HTTPException(status_code=404, detail="Key not found")
    return {"removed": True}
