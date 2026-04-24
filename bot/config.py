from __future__ import annotations

from zoneinfo import ZoneInfo

from pydantic import Field, PrivateAttr, field_validator, model_validator
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
    HEALTHCHECK_TOKEN: str = ""
    METRICS_TOKEN: str = ""


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

    THROTTLE_MAX_ENTRIES: int = 300_000
    INBOUND_UPDATES_CONCURRENCY_LIMIT: int = 2000

    # DB connection pool sizing — defaults calibrated for 150k+ MAU with bursty
    # handler concurrency.  All values overridable via ENV for per-environment
    # tuning without code changes.
    DB_POOL_SIZE: int = 200
    DB_MAX_OVERFLOW: int = 100
    DB_POOL_TIMEOUT_S: int = 30
    DB_POOL_RECYCLE_S: int = 1800

    # Power-monitor in-memory state retention.  48h keeps a healthy buffer for
    # weekend inactivity while preventing unbounded growth in pathological
    # churn scenarios.
    USER_STATES_STALE_HOURS: int = 48

    # Maximum time allowed for the final dirty-state flush during shutdown.
    # Must be < docker-compose stop_grace_period (30s) so SIGKILL doesn't
    # interrupt the batch upsert mid-transaction.
    SHUTDOWN_FLUSH_TIMEOUT_S: int = 15

    # Anti-spam cooldown for admin startup/shutdown notifications. On a
    # crashloop this prevents admins from getting hammered with every restart.
    ADMIN_NOTIFY_COOLDOWN_S: int = 600

    # Background-task heartbeat threshold. If a registered task has not
    # reported liveness within this many seconds, /health returns 503 and
    # a Prometheus gauge is exposed so Kubernetes/Railway will restart the pod.
    BG_TASK_STALE_THRESHOLD_S: int = 300

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

    CHANNEL_GUARD_BATCH_SIZE: int = 50
    CHANNEL_GUARD_DELAY_BETWEEN_BATCHES_MS: int = 100
    CHANNEL_GUARD_RETRY_ATTEMPTS: int = 3
    CHANNEL_GUARD_RETRY_BASE_DELAY_MS: int = 1000

    DB_STATEMENT_TIMEOUT_MS: int = 30000   # PostgreSQL statement_timeout (ms)
    DB_IDLE_TX_TIMEOUT_MS: int = 60000     # idle_in_transaction_session_timeout (ms)
    DB_COMMAND_TIMEOUT: int = 60           # asyncpg command_timeout (seconds)

    # Decoupled by default: migrations run as an explicit step (docker-compose
    # `migrate` service, Railway start-command prefix, or CI job) rather than
    # on every bot start.  This is the only safe default for multi-replica
    # deployments (concurrent ALTER TABLE holds EXCLUSIVE locks) and keeps
    # single-replica boots fast and observable.  Set to True locally or in
    # environments where the bot process is the only Alembic caller.
    AUTO_MIGRATE: bool = False

    SENTRY_DSN: str = ""
    SENTRY_RELEASE: str = ""
    ENVIRONMENT: str = "production"
    LOG_LEVEL: str = "INFO"

    @field_validator("BOT_TOKEN")
    @classmethod
    def validate_bot_token(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("BOT_TOKEN is required and cannot be empty")
        if ":" not in v:
            raise ValueError("BOT_TOKEN must be in format <bot_id>:<token>")
        return v

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


    @field_validator("WEBHOOK_MAX_CONNECTIONS")
    @classmethod
    def validate_webhook_max_connections(cls, v: int) -> int:
        # Telegram Bot API constraint: 1..100
        if not 1 <= v <= 100:
            raise ValueError("WEBHOOK_MAX_CONNECTIONS must be within 1..100")
        return v

    @field_validator("THROTTLE_MAX_ENTRIES", "INBOUND_UPDATES_CONCURRENCY_LIMIT")
    @classmethod
    def validate_positive_capacity_settings(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Capacity settings must be >= 1")
        return v

    @field_validator(
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "DB_POOL_TIMEOUT_S",
        "DB_POOL_RECYCLE_S",
        "USER_STATES_STALE_HOURS",
        "SHUTDOWN_FLUSH_TIMEOUT_S",
        "ADMIN_NOTIFY_COOLDOWN_S",
        "BG_TASK_STALE_THRESHOLD_S",
    )
    @classmethod
    def validate_positive_runtime_settings(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Runtime tuning settings must be >= 1")
        return v

    @model_validator(mode="after")
    def _warn_default_credentials(self) -> "Settings":
        _default_db = "postgresql+asyncpg://postgres:postgres@localhost:5432/voltyk"
        _default_redis = "redis://localhost:6379/0"
        if self.DATABASE_URL == _default_db:
            logger.warning(
                "DATABASE_URL uses hardcoded default credentials — set DATABASE_URL in .env for production"
            )
        if self.REDIS_URL == _default_redis:
            logger.warning(
                "REDIS_URL uses hardcoded default — set REDIS_URL in .env for production"
            )
        return self

    def model_post_init(self, __context: object) -> None:
        ids: set[int] = set(self.ADMIN_IDS)
        if self.OWNER_ID:
            ids.add(self.OWNER_ID)
        self._admin_ids_set = frozenset(ids)
        try:
            self._tz_info = ZoneInfo(self.TZ)
        except KeyError:
            raise ValueError(f"Invalid timezone: {self.TZ!r}. Use a valid IANA timezone name (e.g. 'Europe/Kyiv')")

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

if settings.USE_WEBHOOK and not settings.WEBHOOK_SECRET.strip():
    raise ValueError(
        "WEBHOOK_SECRET is required when USE_WEBHOOK=True. "
        "Set WEBHOOK_SECRET in your environment to protect the webhook endpoint from unauthorized requests. "
        "For local tunnelling or other development setups, you may use a dummy non-empty value, "
        "but Telegram or your webhook client must be configured to send the same secret token. "
        "Outside local development, use a strong random value."
    )


def ensure_production_endpoint_tokens() -> None:
    """Refuse to boot when /health and /metrics are served without auth.

    Kept as an explicit function — not a module-level guard — so that tooling
    that only imports :mod:`bot.config` (Alembic migrations, ad-hoc scripts,
    unit tests) does not trip it.  The bot entrypoint calls this right before
    the aiohttp server is started; see :func:`bot.app.main`.

    An empty token in :func:`_is_token_authorized` returns True
    unconditionally, which would expose DB pool state, memory, and per-region
    counters to anyone who can reach the health/metrics port — so this guard
    is the last line of defence in a production deployment.
    """
    if settings.ENVIRONMENT != "production":
        return
    missing = [
        name for name, val in (
            ("HEALTHCHECK_TOKEN", settings.HEALTHCHECK_TOKEN),
            ("METRICS_TOKEN", settings.METRICS_TOKEN),
        )
        if not val.strip()
    ]
    if missing:
        raise ValueError(
            "The following tokens are required in production and must be set "
            "to a strong random value: " + ", ".join(missing) + ". "
            "An empty token disables authentication on /health and /metrics, "
            "which leaks internal state (DB pool stats, memory, counters) to anyone."
        )
