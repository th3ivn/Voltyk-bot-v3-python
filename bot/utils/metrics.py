"""Prometheus metrics for Voltyk Bot.

Exposes a ``/metrics`` endpoint (via ``generate_latest``) that Prometheus can
scrape.  Import and increment/observe these objects from anywhere in the bot.

All metrics are lazily initialised so that importing this module at test time
does not require ``prometheus_client`` to be installed in the base environment.

Usage
-----
    from bot.utils.metrics import SCHEDULE_NOTIFICATIONS_SENT, POWER_NOTIFICATIONS_SENT
    SCHEDULE_NOTIFICATIONS_SENT.inc()
    POWER_NOTIFICATIONS_SENT.labels(state="off").inc()
"""

from __future__ import annotations

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

    # ── Counters ──────────────────────────────────────────────────────────

    SCHEDULE_NOTIFICATIONS_SENT = Counter(
        "voltyk_schedule_notifications_sent_total",
        "Total schedule notifications dispatched to users",
        ["region"],
    )

    POWER_NOTIFICATIONS_SENT = Counter(
        "voltyk_power_notifications_sent_total",
        "Total power state change notifications sent",
        ["state"],  # "on" | "off"
    )

    SCHEDULE_FETCH_ERRORS = Counter(
        "voltyk_schedule_fetch_errors_total",
        "Total failures fetching schedule data from upstream",
        ["region"],
    )

    CIRCUIT_BREAKER_TRIPS = Counter(
        "voltyk_circuit_breaker_trips_total",
        "Number of times a circuit breaker opened",
        ["name"],
    )

    TELEGRAM_RETRY_AFTER_TOTAL = Counter(
        "voltyk_telegram_retry_after_total",
        "Number of TelegramRetryAfter responses received",
    )

    USER_REGISTRATIONS_TOTAL = Counter(
        "voltyk_user_registrations_total",
        "Total new user registrations via /start",
    )

    USER_DEACTIVATIONS_TOTAL = Counter(
        "voltyk_user_deactivations_total",
        "Total user deactivations (user confirmed deactivate)",
    )

    USER_DELETIONS_TOTAL = Counter(
        "voltyk_user_deletions_total",
        "Total user data deletion requests confirmed",
    )

    # ── Gauges ────────────────────────────────────────────────────────────

    USER_STATES_IN_MEMORY = Gauge(
        "voltyk_user_states_in_memory",
        "Number of power-monitor user states currently held in memory",
    )

    DIRTY_STATES_COUNT = Gauge(
        "voltyk_dirty_states_count",
        "Number of user states pending DB flush",
    )

    DB_POOL_SIZE = Gauge(
        "voltyk_db_pool_size",
        "SQLAlchemy connection pool: pool_size (fixed slots)",
    )

    DB_POOL_CHECKED_OUT = Gauge(
        "voltyk_db_pool_checked_out",
        "SQLAlchemy connection pool: connections currently in use",
    )

    # ── Histograms ────────────────────────────────────────────────────────

    SCHEDULE_FETCH_DURATION = Histogram(
        "voltyk_schedule_fetch_duration_seconds",
        "Time spent fetching schedule data (successful requests only)",
        buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
    )

    NOTIFICATION_BLAST_DURATION = Histogram(
        "voltyk_notification_blast_duration_seconds",
        "Time to send a full notification blast for one region/queue pair",
        buckets=[1, 5, 15, 30, 60, 120, 300],
    )

    PROMETHEUS_AVAILABLE = True

    def metrics_response() -> tuple[bytes, str]:
        """Return (body, content_type) for the /metrics HTTP response."""
        return generate_latest(), CONTENT_TYPE_LATEST

except ImportError:
    PROMETHEUS_AVAILABLE = False

    # Stub objects so callers don't need ``if PROMETHEUS_AVAILABLE`` guards

    class _Noop:  # type: ignore[no-redef]
        def inc(self, *a: object, **kw: object) -> None: ...
        def dec(self, *a: object, **kw: object) -> None: ...
        def set(self, *a: object, **kw: object) -> None: ...
        def observe(self, *a: object, **kw: object) -> None: ...
        def labels(self, *a: object, **kw: object) -> "_Noop": return self
        def time(self) -> "_Noop": return self
        def __enter__(self) -> "_Noop": return self
        def __exit__(self, *a: object) -> None: ...

    _noop = _Noop()

    SCHEDULE_NOTIFICATIONS_SENT = _noop  # type: ignore[assignment]
    POWER_NOTIFICATIONS_SENT = _noop  # type: ignore[assignment]
    SCHEDULE_FETCH_ERRORS = _noop  # type: ignore[assignment]
    CIRCUIT_BREAKER_TRIPS = _noop  # type: ignore[assignment]
    TELEGRAM_RETRY_AFTER_TOTAL = _noop  # type: ignore[assignment]
    USER_REGISTRATIONS_TOTAL = _noop  # type: ignore[assignment]
    USER_DEACTIVATIONS_TOTAL = _noop  # type: ignore[assignment]
    USER_DELETIONS_TOTAL = _noop  # type: ignore[assignment]
    USER_STATES_IN_MEMORY = _noop  # type: ignore[assignment]
    DIRTY_STATES_COUNT = _noop  # type: ignore[assignment]
    DB_POOL_SIZE = _noop  # type: ignore[assignment]
    DB_POOL_CHECKED_OUT = _noop  # type: ignore[assignment]
    SCHEDULE_FETCH_DURATION = _noop  # type: ignore[assignment]
    NOTIFICATION_BLAST_DURATION = _noop  # type: ignore[assignment]

    def metrics_response() -> tuple[bytes, str]:  # type: ignore[misc]
        return b"# prometheus_client not installed\n", "text/plain"
