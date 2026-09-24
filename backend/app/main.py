import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import get_supabase_admin

from app.routers import search, leads, dashboard, ai, auth, subscriptions, developer, public_api, linkedin_studio
from app.middleware.api_key_auth import ApiError
from app.public_docs import register_public_docs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Hyperclients Backend starting up...")

    try:
        supabase = get_supabase_admin()
        stale_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()

        supabase.table("searches").update({
            "status": "failed",
            "message": "Search timed out (recovered on server restart)",
            "error_message": "Server restarted while search was running",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).in_("status", ["queued", "scraping", "analyzing"]).lt(
            "created_at", stale_cutoff
        ).execute()

        # Hyperagent engine rows run in worker threads with their own status
        # vocabulary; a restart strands them as 'running' forever, which the
        # status endpoint then resurrects as 'scraping'. Close stale rows too.
        try:
            supabase.table("ha_searches").update({
                "status": "failed",
                "error": "Server restarted while search was running",
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }).in_("status", ["queued", "running"]).lt(
                "created_at", stale_cutoff
            ).execute()
        except Exception as ha_err:
            logger.warning(f"Stale ha_searches cleanup failed (non-critical): {ha_err}")

        logger.info("Stale search cleanup completed")
    except Exception as e:
        logger.warning(f"Stale search cleanup failed (non-critical): {e}", exc_info=True)

    settings = get_settings()
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Frontend URL: {settings.frontend_url}")

    # LinkedIn Studio scheduler (LinkedIn has no native scheduling). Posts a
    # restart interrupted mid-publish go back to the queue; the claim RPC
    # guarantees a post is never published twice.
    import asyncio

    li_stop = asyncio.Event()
    li_task = None
    if settings.linkedin_scheduler_enabled:
        try:
            get_supabase_admin().table("linkedin_posts").update({"status": "scheduled"}) \
                .eq("status", "publishing").lt(
                    "updated_at", (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
                ).execute()
        except Exception as e:  # table missing before migration v21
            logger.info(f"LinkedIn publishing recovery skipped: {e}")
        from app.services.linkedin_scheduler import scheduler_loop

        li_task = asyncio.create_task(scheduler_loop(li_stop))
    logger.info(f"Supabase URL: {settings.supabase_url}")

    yield

    li_stop.set()
    if li_task is not None:
        try:
            await asyncio.wait_for(li_task, timeout=10)
        except Exception:  # noqa: BLE001 - shutdown must not hang
            li_task.cancel()
    logger.info("Hyperclients Backend shutting down...")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Hyperclients",
        description="Lead discovery and qualification API for freelance developers and agencies.",
        version="2.2.0",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(subscriptions.router)
    app.include_router(search.router)
    app.include_router(leads.router)
    app.include_router(dashboard.router)
    app.include_router(ai.router)
    app.include_router(developer.router)
    app.include_router(linkedin_studio.router)
    app.include_router(public_api.router)
    register_public_docs(app)

    # Public API (/v1): every error is {"error": {"code", "message", ...}}.
    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status, content=exc.body(), headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/v1"):
            first = (exc.errors() or [{}])[0]
            loc = [str(p) for p in first.get("loc", []) if p not in ("body", "query", "path")]
            msg = str(first.get("msg", "Invalid request")).removeprefix("Value error, ")
            return JSONResponse(status_code=400, content={"error": {
                "code": "invalid_request", "message": msg, "param": ".".join(loc) or None}})
        from fastapi.exception_handlers import request_validation_exception_handler
        return await request_validation_exception_handler(request, exc)

    @app.get("/", tags=["Root"])
    async def root():
        return {
            "app": "Hyperclients",
            "version": "2.2.0",
            "status": "running",
            "docs": "/docs",
        }

    @app.get("/api/health", tags=["Health"])
    async def health_check():
        return {
            "status": "healthy",
            "environment": settings.environment,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    return app


app = create_app()
