"""Simple async circuit-breaker pattern (no external dependencies).

States
------
CLOSED  → normal; failures are counted.
OPEN    → all calls fail fast; reopens after *reset_timeout* seconds.
HALF_OPEN → one probe call allowed; success → CLOSED, failure → OPEN.

Usage
-----
    cb = CircuitBreaker(name="schedule_api", fail_max=5, reset_timeout=60)

    result = await cb.call(fetch_schedule_data, region)
    # raises CircuitBreakerOpen if the circuit is OPEN
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from bot.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class CircuitBreakerOpen(Exception):
    """Raised when a call is rejected because the circuit breaker is open."""

    def __init__(self, name: str, retry_after: float) -> None:
        self.name = name
        self.retry_after = retry_after
        super().__init__(f"Circuit breaker '{name}' is OPEN — retry after {retry_after:.1f}s")


class CircuitBreaker:
    """Async circuit breaker.

    Thread/coroutine safety: all state changes are protected by an
    asyncio.Lock, so the breaker is safe for concurrent callers within
    one event loop.

    Args:
        name:          Human-readable name used in log messages.
        fail_max:      Consecutive failures before opening the circuit.
        reset_timeout: Seconds to stay OPEN before allowing a probe (HALF_OPEN).
        exclude:       Exception types that do NOT count as failures
                       (e.g. application-level 404 is expected, not a fault).
    """

    _CLOSED = "closed"
    _OPEN = "open"
    _HALF_OPEN = "half_open"

    def __init__(
        self,
        name: str,
        fail_max: int = 5,
        reset_timeout: float = 60.0,
        exclude: tuple[type[BaseException], ...] = (),
    ) -> None:
        self.name = name
        self.fail_max = fail_max
        self.reset_timeout = reset_timeout
        self.exclude = exclude

        self._state = self._CLOSED
        self._failures = 0
        self._opened_at: float = 0.0
        self._lock = asyncio.Lock()

    # ── Public ────────────────────────────────────────────────────────────

    async def call(self, fn: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
        """Execute *fn* if the circuit allows it, otherwise raise CircuitBreakerOpen."""
        async with self._lock:
            state = self._get_state()
            if state == self._OPEN:
                retry_after = self.reset_timeout - (time.monotonic() - self._opened_at)
                raise CircuitBreakerOpen(self.name, max(0.0, retry_after))
            # For HALF_OPEN we allow the call through (one probe)

        try:
            result = await fn(*args, **kwargs)
        except Exception as exc:
            if not self.exclude or not isinstance(exc, self.exclude):
                await self._on_failure(exc)
            raise

        await self._on_success()
        return result

    @property
    def state(self) -> str:
        return self._get_state()

    @property
    def failures(self) -> int:
        return self._failures

    # ── Internal ──────────────────────────────────────────────────────────

    def _get_state(self) -> str:
        if self._state == self._OPEN:
            if time.monotonic() - self._opened_at >= self.reset_timeout:
                self._state = self._HALF_OPEN
                logger.info("CircuitBreaker '%s': OPEN → HALF_OPEN (probe allowed)", self.name)
        return self._state

    async def _on_success(self) -> None:
        async with self._lock:
            if self._state in (self._HALF_OPEN, self._OPEN):
                logger.info("CircuitBreaker '%s': probe succeeded → CLOSED", self.name)
            self._state = self._CLOSED
            self._failures = 0

    async def _on_failure(self, exc: Exception) -> None:
        async with self._lock:
            self._failures += 1
            if self._state == self._HALF_OPEN or self._failures >= self.fail_max:
                self._state = self._OPEN
                self._opened_at = time.monotonic()
                logger.warning(
                    "CircuitBreaker '%s': OPEN after %d failure(s) — last: %s",
                    self.name, self._failures, exc,
                )
                # Local import avoids a module-level circular dependency
                # (metrics → circuit_breaker would form a cycle).
                from bot.utils.metrics import CIRCUIT_BREAKER_TRIPS  # noqa: PLC0415
                CIRCUIT_BREAKER_TRIPS.labels(name=self.name).inc()
