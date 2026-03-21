"""
LeadForge AI — FastAPI Application

Main application entry point.
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import get_supabase_admin

# Import routers
from app.routers import auth, search, leads, dashboard, ai

# ── Logging ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Lifespan ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    logger.info("🚀 LeadForge AI Backend starting up...")

    # Cleanup stale searches (older than 15 minutes and still running)
    try:
        supabase = get_supabase_admin()
        stale_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()

        # Only clean up searches that are clearly stale
        # (created more than 15 min ago AND still in a running state)
        supabase.table("searches").update({
            "status": "failed",
            "message": "Search timed out (recovered on server restart)",
            "error_message": "Server restarted while search was running",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).in_("status", ["queued", "scraping", "analyzing"]).lt(
            "created_at", stale_cutoff
        ).execute()

        logger.info("✅ Stale search cleanup completed")
    except Exception as e:
        logger.warning(f"⚠️  Stale search cleanup failed (non-critical): {e}")

    settings = get_settings()
    logger.info(f"📍 Environment: {settings.environment}")
    logger.info(f"🌐 Frontend URL: {settings.frontend_url}")
    logger.info(f"🔗 Supabase URL: {settings.supabase_url}")

    yield

    logger.info("👋 LeadForge AI Backend shutting down...")


# ── App Creation ─────────────────────────────────────────
def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="LeadForge AI",
        description="Lead discovery and qualification API for freelance developers and agencies.",
        version="2.1.0",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        lifespan=lifespan,
    )

    # ── CORS ─────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ──────────────────────────────────────────
    app.include_router(auth.router)
    app.include_router(search.router)
    app.include_router(leads.router)
    app.include_router(dashboard.router)
    app.include_router(ai.router)

    # ── Root & Health ────────────────────────────────────
    @app.get("/", tags=["Root"])
    async def root():
        return {
            "app": "LeadForge AI",
            "version": "2.1.0",
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


# Create the app instance for uvicorn
app = create_app()
