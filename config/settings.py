"""Central configuration. Everything comes from the environment via .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- database ----
    database_url: str = "postgresql+asyncpg://markets:changeme@postgres:5432/markets"

    @property
    def sync_database_url(self) -> str:
        """Alembic runs synchronously and cannot use asyncpg - swap the
        driver in the same DSN rather than requiring a second env var."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")

    # ---- auth ----
    api_bearer_token: str = ""

    # ---- providers ----
    # Preference order for real-time quotes: finnhub > alphavantage > yfinance.
    # yfinance is always available (no key) and is the default/fallback, and
    # is also the sole source for /history - the free tiers on the other two
    # don't handle bulk/long-range OHLCV pulls well, and yfinance is what
    # Yahoo actually built for that.
    finnhub_api_key: str = ""
    alphavantage_api_key: str = ""

    quote_cache_seconds: int = 600  # 10 minutes, per free-tier courtesy
    # Conservative defaults matching each provider's documented free-tier
    # ceiling with headroom - Finnhub allows 60/min, Alpha Vantage 5/min.
    finnhub_requests_per_minute: int = 50
    alphavantage_requests_per_minute: int = 5
    yfinance_requests_per_minute: int = 30

    # ---- market hours (America/Chicago, matches the scheduler jobs) ----
    market_timezone: str = "America/Chicago"

    # ---- retention ----
    snapshot_retention_days: int = 730  # 2 years

    log_level: str = "INFO"
    environment: str = "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
