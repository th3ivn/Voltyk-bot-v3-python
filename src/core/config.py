from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Telegram
    bot_token: str = Field(..., description="Telegram bot token from @BotFather")
    owner_id: int | None = Field(None, description="Telegram ID of the bot owner")
    admin_ids: list[int] = Field(default_factory=list, description="List of admin Telegram IDs")

    # Database (Neon)
    database_url: str = Field(..., description="PostgreSQL connection string (asyncpg)")

    # Redis
    redis_url: str = Field("redis://localhost:6379/0", description="Redis connection URL")

    # Webhook
    webhook_url: str = Field("", description="Public domain for webhook")
    webhook_path: str = Field("/webhook", description="Webhook endpoint path")
    webhook_secret: str = Field("", description="Webhook verification secret")

    # Server
    port: int = Field(8080, description="HTTP server port")

    # Timezone
    tz: str = Field("Europe/Kyiv", description="Timezone")

    # Celery
    celery_broker_url: str = Field("redis://localhost:6379/0")
    celery_result_backend: str = Field("redis://localhost:6379/1")
    celery_concurrency: int = Field(4)

    # Database pool
    db_pool_size: int = Field(20)
    db_max_overflow: int = Field(10)

    # Rate limiting
    telegram_rate_limit: int = Field(25)

    # Data sources
    data_url_template: str = Field(
        "https://raw.githubusercontent.com/Baskerville42/outage-data-ua/main/data/{region}.json"
    )
    image_url_template: str = Field(
        "https://raw.githubusercontent.com/Baskerville42/outage-data-ua/main/images/{region}/gpv-{queue}-emergency.png"
    )

    # Logging
    log_level: str = Field("INFO")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
