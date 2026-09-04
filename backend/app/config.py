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

    # Apify (search-page LinkedIn provider)
    apify_api_key: str = ""
    apify_api_key_2: str = ""
    apify_api_key_3: str = ""
    apify_api_key_4: str = ""
    apify_api_key_5: str = ""
    apify_api_key_6: str = ""
    apify_api_key_7: str = ""
    apify_api_key_8: str = ""
    apify_api_key_9: str = ""
    apify_api_key_10: str = ""
    apify_api_key_11: str = ""
    apify_api_key_12: str = ""
    apify_api_key_13: str = ""
    apify_api_key_14: str = ""
    apify_api_key_15: str = ""
    apify_api_key_16: str = ""
    apify_api_key_17: str = ""
    apify_api_key_18: str = ""
    apify_api_key_19: str = ""
    apify_api_key_20: str = ""
    apify_api_key_21: str = ""
    apify_api_key_22: str = ""
    apify_api_key_23: str = ""
    apify_api_key_24: str = ""

    # LinkedIn public post-scraper actor (profile-URL -> public post history).
    # The actor is private and owned by the account whose token is set here;
    # when empty, the shared APIFY_API_KEY rotation is used as a fallback.
    apify_post_scraper_actor_id: str = "2nZ0rjo0R3O4fzBy3"
    apify_post_scraper_token: str = ""

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"

    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_solo_amount_inr: int = 0
    razorpay_pro_amount_inr: int = 0
    razorpay_agency_amount_inr: int = 0

    gmaps_scraper_path: str = "backend/google-maps-scraper/google-maps-scraper"

    scrapling_proxy: str = ""
    scrapling_solve_cloudflare: bool = True
    scrapling_headless: bool = True

    frontend_url: str = "http://localhost:3000"
    backend_url: str = "http://localhost:8000"
    site_url: str = "http://localhost:3000"

    environment: Literal["development", "staging", "production"] = "development"

    @model_validator(mode="after")
    def _collect_apify_keys(self):
        self._apify_keys = [
            k for k in (
                self.apify_api_key, self.apify_api_key_2, self.apify_api_key_3,
                self.apify_api_key_4, self.apify_api_key_5, self.apify_api_key_6,
                self.apify_api_key_7, self.apify_api_key_8, self.apify_api_key_9,
                self.apify_api_key_10, self.apify_api_key_11, self.apify_api_key_12,
                self.apify_api_key_13, self.apify_api_key_14, self.apify_api_key_15,
                self.apify_api_key_16, self.apify_api_key_17, self.apify_api_key_18,
                self.apify_api_key_19, self.apify_api_key_20, self.apify_api_key_21,
                self.apify_api_key_22, self.apify_api_key_23, self.apify_api_key_24,
            )
            if k
        ]
        return self

    @property
    def apify_keys(self) -> list[str]:
        return getattr(self, "_apify_keys", [k for k in (self.apify_api_key, self.apify_api_key_2) if k])

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

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
