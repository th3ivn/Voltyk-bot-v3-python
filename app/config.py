"""Application configuration via pydantic-settings."""

from __future__ import annotations

from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- Telegram ---
    BOT_TOKEN: str
    OWNER_ID: int | None = None
    ADMIN_IDS: list[int] = []

    # --- Database (Neon PostgreSQL via asyncpg) ---
    DATABASE_URL: str

    # --- Redis / Celery ---
    REDIS_URL: str = "redis://localhost:6379"

    # --- Timezone ---
    TZ: str = "Europe/Kyiv"

    # --- Router (admin SNMP router) ---
    ROUTER_HOST: str | None = None
    ROUTER_PORT: int = 80

    # --- DB connection pool ---
    DB_POOL_MAX: int = 50
    DB_POOL_MIN: int = 5

    # --- Rate limiting ---
    TELEGRAM_RATE_LIMIT: int = 25
    MESSAGE_RETRY_COUNT: int = 3

    # --- Celery ---
    CELERY_CONCURRENCY: int = 15

    # --- Webhook (optional; if not set, bot runs in polling mode) ---
    WEBHOOK_URL: str | None = None
    WEBHOOK_SECRET: str | None = None
    PORT: int = 8000

    # --- Logging ---
    LOG_LEVEL: str = "INFO"
    DEBUG: bool = False

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: Any) -> list[int]:
        """Convert comma-separated string '123,456', single int, or list to list of ints."""
        if isinstance(value, int):
            return [value]
        if isinstance(value, str):
            if not value.strip():
                return []
            return [int(v.strip()) for v in value.split(",") if v.strip()]
        if isinstance(value, list):
            return [int(v) for v in value]
        raise ValueError(f"ADMIN_IDS must be a string, int, or list, got {type(value).__name__}")


settings = Settings()  # type: ignore[call-arg]