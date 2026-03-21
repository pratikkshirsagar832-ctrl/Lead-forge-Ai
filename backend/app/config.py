"""
LeadForge AI — Application Configuration

Uses pydantic-settings for strongly-typed, validated config.
Fails fast with clear errors if required variables are missing.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Supabase ──────────────────────────────────────────
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

    # ── AI ────────────────────────────────────────────────
    deepseek_api_key: str = ""

    # ── Paths ─────────────────────────────────────────────
    gmaps_scraper_path: str = "./google-maps-scraper/google-maps-scraper"

    # ── URLs ──────────────────────────────────────────────
    frontend_url: str = "http://localhost:3000"
    backend_url: str = "http://localhost:8000"

    # ── Environment ───────────────────────────────────────
    environment: str = "development"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def scraper_binary_path(self) -> Path:
        """Resolved path to the google-maps-scraper binary."""
        return Path(self.gmaps_scraper_path).resolve()

    @property
    def cors_origins(self) -> list[str]:
        """Allowed CORS origins."""
        origins = [self.frontend_url]
        if not self.is_production:
            origins.extend([
                "http://localhost:3000",
                "http://localhost:3001",
                "http://127.0.0.1:3000",
            ])
        return list(set(origins))


@lru_cache()
def get_settings() -> Settings:
    """Singleton settings loader. Cached after first call."""
    return Settings()
