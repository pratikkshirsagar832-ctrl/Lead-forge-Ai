from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""

    openai_api_key: str = ""

    # ── Bright Data multi-key rotation ────────────────────────────────
    # Primary key (always tried first). Additional keys rotate on failure.
    bright_data_api_key: str = ""
    bright_data_api_key_2: str = ""
    bright_data_api_key_3: str = ""
    bright_data_api_key_4: str = ""
    bright_data_api_key_5: str = ""
    bright_data_api_key_6: str = ""
    bright_data_api_key_7: str = ""
    bright_data_api_key_8: str = ""
    bright_data_api_key_9: str = ""
    bright_data_api_key_10: str = ""
    bright_data_api_key_11: str = ""
    bright_data_api_key_12: str = ""
    bright_data_api_key_13: str = ""
    bright_data_api_key_14: str = ""
    bright_data_api_key_15: str = ""
    bright_data_api_key_16: str = ""

    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""

    gmaps_scraper_path: str = "backend/google-maps-scraper/google-maps-scraper"

    scrapling_proxy: str = ""
    scrapling_solve_cloudflare: bool = True
    scrapling_headless: bool = True

    frontend_url: str = "http://localhost:3000"
    backend_url: str = "http://localhost:8000"
    site_url: str = "http://localhost:3000"

    environment: Literal["development", "staging", "production"] = "development"

    @model_validator(mode="after")
    def _collect_bright_data_keys(self):
        """Collect all non-empty Bright Data API keys."""
        self._bright_data_keys = [
            k for k in (
                self.bright_data_api_key, self.bright_data_api_key_2, self.bright_data_api_key_3,
                self.bright_data_api_key_4, self.bright_data_api_key_5, self.bright_data_api_key_6,
                self.bright_data_api_key_7, self.bright_data_api_key_8, self.bright_data_api_key_9,
                self.bright_data_api_key_10, self.bright_data_api_key_11, self.bright_data_api_key_12,
                self.bright_data_api_key_13, self.bright_data_api_key_14, self.bright_data_api_key_15,
                self.bright_data_api_key_16,
            )
            if k
        ]
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def bright_data_keys(self) -> list[str]:
        return getattr(self, "_bright_data_keys", [k for k in (self.bright_data_api_key, self.bright_data_api_key_2) if k])

    @property
    def scraper_binary_path(self) -> Path:
        path = Path(self.gmaps_scraper_path)
        if self.is_production:
            if not path.is_absolute():
                path = Path("/app") / path
        return path.resolve()

    @property
    def cors_origins(self) -> list[str]:
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
    return Settings()
