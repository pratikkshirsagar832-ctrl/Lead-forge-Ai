"""Public API reference: /v1/openapi.json, /v1/docs (Swagger), /v1/redoc.

Only /v1 routes are published - internal dashboard endpoints never appear.
Served in every environment (the internal /docs stays dev-only).
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from app.config import get_settings

logger = logging.getLogger(__name__)

API_VERSION = "1.0.0"

DESCRIPTION = """
Find **people who need your service right now** (LinkedIn) and **local
businesses to prospect** (Google Maps) - programmatically.

## Quick start

1. Create an API key in the dashboard: **Developer → API keys** (it is shown once).
2. Top up your wallet in **Developer → Wallet**.
3. Start a search, then poll it (or receive a webhook):

```bash
curl -X POST {base}/v1/searches \\
  -H "Authorization: Bearer $HYPERCLIENTS_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"source": "linkedin", "service": "video editing", "mode": "freelancer", "leads": 5}'

curl {base}/v1/searches/SEARCH_ID -H "Authorization: Bearer $HYPERCLIENTS_API_KEY"
curl {base}/v1/searches/SEARCH_ID/leads -H "Authorization: Bearer $HYPERCLIENTS_API_KEY"
```

## Authentication
Send your key as `Authorization: Bearer hc_live_...` (or `X-API-Key: hc_live_...`).
Keep keys server-side - never ship them in a browser or mobile app.

## Pricing (prepaid wallet, INR)
| Source | Price |
|---|---|
| LinkedIn | **₹{li} per lead delivered** |
| Google Maps | **₹{maps} per lead delivered** |

Creating a search **holds** `leads × price`. When it finishes you are charged
**only for leads actually delivered**; the rest of the hold is released
automatically. Insufficient balance → `402 insufficient_balance`.

## Search lifecycle
`queued` → `running` → `completed` | `failed` | `cancelled`.
LinkedIn searches typically finish in 20 s - 3 min, Google Maps in ~1 min.

## Webhooks
Pass `webhook_url` (https) when creating a search. When it finishes we `POST`
`{"event": "search.completed", "data": {"search": {...}, "leads": [...]}}`
signed with your key's webhook secret:
`X-Hyperclients-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "<t>.<raw body>")>`.
Retries: 3 (after 2 s, 10 s, 30 s).

## Errors
Every error is `{"error": {"code": "...", "message": "..."}}`:
`invalid_request` (400), `unauthorized` (401), `insufficient_balance` (402),
`not_found` (404), `invalid_state` (409), `rate_limited` (429),
`internal_error` (500), `service_unavailable` (503).

## Rate limits
{create}/min for `POST /v1/searches`, {read}/min for all other calls, per key.
"""


def _fill(text: str, values: dict) -> str:
    """Replace {name} placeholders only (JSON braces in the text stay intact)."""
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def _public_routes(app: FastAPI) -> list:
    """The /v1 endpoints, taken from the public router itself (independent of
    how the app's route table is assembled in a given deployment), falling
    back to scanning the app for /v1 API routes."""
    from fastapi.routing import APIRoute

    from app.routers import public_api

    routes = [r for r in public_api.router.routes if isinstance(r, APIRoute)]
    if not routes:
        routes = [r for r in app.routes if isinstance(r, APIRoute)
                  and r.path.startswith("/v1/") and r.include_in_schema]
    return routes


def _spec(app: FastAPI) -> dict:
    settings = get_settings()
    routes = _public_routes(app)
    logger.info("Public API docs: %d endpoint(s) published", len(routes))
    spec = get_openapi(
        title="Hyperclients API",
        version=API_VERSION,
        description=_fill(DESCRIPTION, {
            "base": settings.public_api_base_url.rstrip("/"),
            "li": settings.api_price_linkedin_inr, "maps": settings.api_price_maps_inr,
            "create": settings.api_rate_create_per_min, "read": settings.api_rate_read_per_min,
        }),
        routes=routes,
        servers=[{"url": settings.public_api_base_url.rstrip("/")}],
    )
    spec.setdefault("info", {})["contact"] = {"name": "Hyperclients", "url": "https://hyperclients.online"}
    return spec


def register_public_docs(app: FastAPI) -> None:
    cache: dict[str, dict] = {}

    @app.get("/v1/openapi.json", include_in_schema=False)
    async def public_openapi():
        spec = cache.get("spec") or _spec(app)
        if spec.get("paths"):  # never pin an empty spec for the process lifetime
            cache["spec"] = spec
        return JSONResponse(spec)

    @app.get("/v1/docs", include_in_schema=False)
    async def public_swagger():
        return get_swagger_ui_html(openapi_url="/v1/openapi.json", title="Hyperclients API - Reference",
                                   swagger_ui_parameters={"persistAuthorization": True,
                                                          "defaultModelsExpandDepth": 0})

    @app.get("/v1/redoc", include_in_schema=False)
    async def public_redoc():
        return get_redoc_html(openapi_url="/v1/openapi.json", title="Hyperclients API - Reference")
