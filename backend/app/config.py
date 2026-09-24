from functools import lru_cache
from typing import Literal

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

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    # DeepSeek's chat model (deepseek-chat, DeepSeek-V3) — the classifier model.
    deepseek_model: str = "deepseek-chat"

    # SocialCrawl (LinkedIn post search for the Hyperagent lead engine - the
    # only LinkedIn discovery provider). ~5 credits per query of 25 posts.
    socialcrawl_api_key: str = ""
    # Extra keys (comma separated). All env keys are imported into the
    # socialcrawl_keys table and rotated automatically when one runs dry.
    socialcrawl_api_keys: str = ""
    socialcrawl_base_url: str = "https://www.socialcrawl.dev"
    socialcrawl_results_per_query: int = 25
    socialcrawl_min_relevance: float = 0.2

    # Public API v1 — pay per DELIVERED lead from a prepaid wallet (INR).
    api_price_linkedin_inr: int = 50
    api_price_maps_inr: int = 5
    # USD equivalents shown next to INR (billing itself is in INR).
    api_price_linkedin_usd: float = 0.52
    api_price_maps_usd: float = 0.052
    api_min_topup_inr: int = 10000
    api_max_topup_inr: int = 100000
    api_rate_create_per_min: int = 20
    api_rate_read_per_min: int = 120
    public_api_base_url: str = "https://hyperclients.online"

    # Shared secret between the Next.js /admin panel (server side) and the
    # backend admin endpoints (/api/admin/*). Empty = admin endpoints disabled.
    admin_api_token: str = ""

    # LinkedIn Studio — official LinkedIn API only. Two LinkedIn apps:
    #   member app: "Sign In with LinkedIn (OpenID Connect)" + "Share on LinkedIn"
    #   pages app:  "Community Management API" (LinkedIn review; separate app)
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_pages_client_id: str = ""
    linkedin_pages_client_secret: str = ""
    linkedin_pages_enabled: bool = False
    linkedin_redirect_uri: str = "https://hyperclients.online/api/linkedin/callback"
    linkedin_api_version: str = "202608"
    linkedin_token_key: str = ""          # Fernet key (base64, 32 bytes) for tokens at rest
    linkedin_daily_post_cap: int = 5      # per connected account, safety cap
    linkedin_scheduler_enabled: bool = True
    linkedin_scheduler_interval_s: int = 30

    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_solo_amount_inr: int = 0
    razorpay_pro_amount_inr: int = 0
    razorpay_agency_amount_inr: int = 0

    gmaps_scraper_path: str = "backend/google-maps-scraper/google-maps-scraper"
    # Google Maps tuning (GMAPS_CONCURRENCY / _TOTAL_CONCURRENCY / _WORKERS /
    # _DEPTH / _SOFT_DEADLINE_SECONDS / _TIMEOUT_SECONDS are read straight from
    # the environment by scraper_service._gmaps_tuning).
    gmaps_stagger_seconds: float = 3.0
    # Throttled shards must WAIT OUT a Google cooldown, not suicide:
    # the old 12s inactivity exit killed 3/4 parallel workers with 0 rows.
    gmaps_shard_inactivity: str = "45s"
    gmaps_exit_inactivity: str = "12s"

    frontend_url: str = "http://localhost:3000"

    environment: Literal["development", "staging", "production"] = "development"

    # Explicit off-by-default switch for debug/dev-only endpoints. These run a
    # scraper subprocess and reveal host information, so they must NEVER be
    # reachable merely because ENVIRONMENT is not "production" (a staging
    # deployment is still a shared, reachable surface).
    enable_debug_routes: bool = False

    @property
    def debug_routes_enabled(self) -> bool:
        """Debug routes are only live when EXPLICITLY enabled AND not production."""
        return bool(self.enable_debug_routes) and not self.is_production

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

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
