from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    BOT_TOKEN: str
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/voltyk"
    REDIS_URL: str = "redis://localhost:6379/0"

    OWNER_ID: int | None = None
    ADMIN_IDS: list[int] = []

    TZ: str = "Europe/Kyiv"

    PORT: int = 3000

    USE_WEBHOOK: bool = False
    WEBHOOK_URL: str = ""
    WEBHOOK_PATH: str = "/webhook"
    WEBHOOK_PORT: int = 3000
    WEBHOOK_SECRET: str = ""
    WEBHOOK_MAX_CONNECTIONS: int = 100

    HEALTH_PORT: int = 3000

    SCHEDULE_CHECK_INTERVAL_S: int = 60
    POWER_CHECK_INTERVAL_S: int = 0
    POWER_DEBOUNCE_MINUTES: int = 5
    POWER_PING_TIMEOUT_MS: int = 3000
    POWER_MAX_CONCURRENT_PINGS: int = 10
    POWER_NOTIFICATION_COOLDOWN_S: int = 60
    POWER_MIN_STABILIZATION_S: int = 30

    TELEGRAM_RATE_LIMIT_PER_SEC: int = 25
    TELEGRAM_MAX_RETRIES: int = 3

    SCHEDULER_BATCH_SIZE: int = 5
    SCHEDULER_STAGGER_MS: int = 50

    DATA_URL_TEMPLATE: str = (
        "https://raw.githubusercontent.com/Baskerville42/outage-data-ua/main/data/{region}.json"
    )
    IMAGE_URL_TEMPLATE: str = (
        "https://raw.githubusercontent.com/Baskerville42/outage-data-ua/main/images/{region}/gpv-{queue}-emergency.png"
    )

    CHANNEL_GUARD_BATCH_SIZE: int = 5
    CHANNEL_GUARD_DELAY_BETWEEN_BATCHES_MS: int = 1000
    CHANNEL_GUARD_RETRY_ATTEMPTS: int = 3
    CHANNEL_GUARD_RETRY_BASE_DELAY_MS: int = 1000

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: str | list) -> list:
        if isinstance(v, list):
            return v
        if not v:
            return []
        return [int(x.strip()) for x in str(v).split(",") if x.strip()]

    @property
    def all_admin_ids(self) -> list[int]:
        ids = list(self.ADMIN_IDS)
        if self.OWNER_ID and self.OWNER_ID not in ids:
            ids.append(self.OWNER_ID)
        return ids

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.all_admin_ids

    def is_owner(self, user_id: int) -> bool:
        return self.OWNER_ID is not None and user_id == self.OWNER_ID

    @property
    def sync_database_url(self) -> str:
        return self.DATABASE_URL.replace("+asyncpg", "")


settings = Settings()
