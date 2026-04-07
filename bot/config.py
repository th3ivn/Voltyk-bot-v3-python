from __future__ import annotations

from zoneinfo import ZoneInfo

from pydantic import Field, PrivateAttr, field_validator
from pydantic_settings import BaseSettings

from bot.utils.logger import get_logger

logger = get_logger(__name__)


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # Private attribute: frozenset of all admin IDs (owner + ADMIN_IDS), computed once at init
    _admin_ids_set: frozenset[int] = PrivateAttr(default_factory=frozenset)
    # Cached ZoneInfo to avoid re-creating on every property access
    _tz_info: ZoneInfo | None = PrivateAttr(default=None)

    BOT_TOKEN: str
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/voltyk"
    DB_SSL_INSECURE_SKIP_VERIFY: bool = False
    REDIS_URL: str = "redis://localhost:6379/0"

    OWNER_ID: int | None = None
    ADMIN_IDS: list[int] = Field(default_factory=list)

    TZ: str = "Europe/Kyiv"

    PORT: int = 3000

    USE_WEBHOOK: bool = False
    WEBHOOK_URL: str = ""
    WEBHOOK_PATH: str = "/webhook"
    WEBHOOK_PORT: int = 3000
    WEBHOOK_SECRET: str = ""
    WEBHOOK_MAX_CONNECTIONS: int = 100

    HEALTH_PORT: int = 3000

    GITHUB_TOKEN: str = ""

    SCHEDULE_CHECK_INTERVAL_S: int = 60
    POWER_CHECK_INTERVAL_S: int = 0
    POWER_DEBOUNCE_MINUTES: int = 5
    POWER_PING_TIMEOUT_MS: int = 3000
    POWER_MAX_CONCURRENT_PINGS: int = 200
    POWER_NOTIFICATION_COOLDOWN_S: int = 60
    POWER_MIN_STABILIZATION_S: int = 30

    TELEGRAM_RATE_LIMIT_PER_SEC: int = 25
    TELEGRAM_MAX_RETRIES: int = 3

    SCHEDULER_BATCH_SIZE: int = 50
    SCHEDULER_STAGGER_MS: int = 20

    DATA_URL_TEMPLATE: str = (
        "https://raw.githubusercontent.com/Baskerville42/outage-data-ua/main/data/{region}.json"
    )
    IMAGE_URL_TEMPLATE: str = (
        "https://raw.githubusercontent.com/Baskerville42/outage-data-ua/main/images/{region}/gpv-{queue}-emergency.png"
    )

    SUPPORT_CHANNEL_URL: str = ""
    FAQ_CHANNEL_URL: str = ""

    DTEK_CHECK_INTERVAL_S: int = 300   # 5 minutes
    DTEK_REQUEST_TIMEOUT_S: int = 15
    DTEK_MAX_RETRIES: int = 2

    CHANNEL_GUARD_BATCH_SIZE: int = 5
    CHANNEL_GUARD_DELAY_BETWEEN_BATCHES_MS: int = 1000
    CHANNEL_GUARD_RETRY_ATTEMPTS: int = 3
    CHANNEL_GUARD_RETRY_BASE_DELAY_MS: int = 1000

    SENTRY_DSN: str = ""
    ENVIRONMENT: str = "production"

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: str | list) -> list:
        if isinstance(v, list):
            return v
        if not v:
            return []
        result: list[int] = []
        for x in str(v).split(","):
            x = x.strip()
            if not x:
                continue
            try:
                result.append(int(x))
            except ValueError:
                logger.warning("Skipping invalid ADMIN_ID value: %r", x)
        return result

    def model_post_init(self, __context: object) -> None:
        ids: set[int] = set(self.ADMIN_IDS)
        if self.OWNER_ID:
            ids.add(self.OWNER_ID)
        self._admin_ids_set = frozenset(ids)
        self._tz_info = ZoneInfo(self.TZ)

    @property
    def all_admin_ids(self) -> list[int]:
        return list(self._admin_ids_set)

    def is_admin(self, user_id: int) -> bool:
        return user_id in self._admin_ids_set

    def is_owner(self, user_id: int) -> bool:
        return self.OWNER_ID is not None and user_id == self.OWNER_ID

    @property
    def timezone(self) -> ZoneInfo:
        # _tz_info is guaranteed to be set by model_post_init
        return self._tz_info  # type: ignore[return-value]

    @property
    def sync_database_url(self) -> str:
        # Safe: DATABASE_URL always uses "+asyncpg" as the asyncpg driver suffix;
        # removing it yields the standard psycopg2-compatible URL for sync usage.
        return self.DATABASE_URL.replace("+asyncpg", "")


settings = Settings()  # type: ignore[call-arg]

if settings.USE_WEBHOOK and not settings.WEBHOOK_SECRET:
    raise ValueError(
        "WEBHOOK_SECRET is required when USE_WEBHOOK=True. "
        "Set WEBHOOK_SECRET in your environment to protect the webhook endpoint from unauthorized requests. "
        "If you intentionally want to disable secret verification (e.g. local tunnelling), "
        "set WEBHOOK_SECRET to any non-empty value."
    )
