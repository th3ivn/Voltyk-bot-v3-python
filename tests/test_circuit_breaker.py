"""Tests for bot/utils/circuit_breaker.py.

Covers:
- CircuitBreaker state machine: CLOSED → OPEN → HALF_OPEN → CLOSED / OPEN
- CircuitBreakerOpen exception attributes
- exclude parameter (non-counted exceptions)
- .state and .failures properties
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.utils.circuit_breaker import CircuitBreaker, CircuitBreakerOpen


# ===========================================================================
# Helpers
# ===========================================================================


def _make_cb(
    fail_max: int = 3,
    reset_timeout: float = 60.0,
    exclude: tuple = (),
) -> CircuitBreaker:
    return CircuitBreaker(
        name="test_cb",
        fail_max=fail_max,
        reset_timeout=reset_timeout,
        exclude=exclude,
    )


async def _ok_fn(*args, **kwargs):
    return "ok"


async def _fail_fn(*args, **kwargs):
    raise ValueError("boom")


# ===========================================================================
# CircuitBreaker state machine
# ===========================================================================


class TestCircuitBreakerStateMachine:

    # ── test_initial_state_is_closed ─────────────────────────────────────────

    def test_initial_state_is_closed(self):
        cb = _make_cb()
        assert cb._state == CircuitBreaker._CLOSED

    # ── test_success_keeps_closed ────────────────────────────────────────────

    async def test_success_keeps_closed(self):
        cb = _make_cb()
        result = await cb.call(_ok_fn)
        assert result == "ok"
        assert cb._state == CircuitBreaker._CLOSED

    # ── test_failures_increment_counter ──────────────────────────────────────

    async def test_failures_increment_counter(self):
        cb = _make_cb(fail_max=10)
        for i in range(1, 4):
            with pytest.raises(ValueError):
                await cb.call(_fail_fn)
            assert cb._failures == i

    # ── test_opens_after_fail_max ────────────────────────────────────────────

    async def test_opens_after_fail_max(self):
        cb = _make_cb(fail_max=3)
        for _ in range(3):
            with pytest.raises(ValueError):
                await cb.call(_fail_fn)
        assert cb._state == CircuitBreaker._OPEN

    # ── test_open_raises_circuit_breaker_open ────────────────────────────────

    async def test_open_raises_circuit_breaker_open(self):
        cb = _make_cb(fail_max=1)
        with pytest.raises(ValueError):
            await cb.call(_fail_fn)
        # Circuit is now OPEN — next call must raise CircuitBreakerOpen
        with pytest.raises(CircuitBreakerOpen):
            await cb.call(_ok_fn)

    # ── test_half_open_after_reset_timeout ───────────────────────────────────

    async def test_half_open_after_reset_timeout(self):
        cb = _make_cb(fail_max=1, reset_timeout=30.0)
        with pytest.raises(ValueError):
            await cb.call(_fail_fn)
        assert cb._state == CircuitBreaker._OPEN

        # Simulate reset_timeout seconds having passed
        with patch("time.monotonic", return_value=cb._opened_at + 31.0):
            state = cb.state  # triggers _get_state() which checks timeout

        assert state == CircuitBreaker._HALF_OPEN

    # ── test_half_open_success_closes ────────────────────────────────────────

    async def test_half_open_success_closes(self):
        cb = _make_cb(fail_max=1, reset_timeout=30.0)
        with pytest.raises(ValueError):
            await cb.call(_fail_fn)

        # Move to HALF_OPEN by simulating elapsed time
        with patch("time.monotonic", return_value=cb._opened_at + 31.0):
            cb._get_state()  # transition to HALF_OPEN

        assert cb._state == CircuitBreaker._HALF_OPEN

        # Probe succeeds → should close
        result = await cb.call(_ok_fn)
        assert result == "ok"
        assert cb._state == CircuitBreaker._CLOSED
        assert cb._failures == 0

    # ── test_half_open_failure_reopens ───────────────────────────────────────

    async def test_half_open_failure_reopens(self):
        cb = _make_cb(fail_max=1, reset_timeout=30.0)
        with pytest.raises(ValueError):
            await cb.call(_fail_fn)

        # Move to HALF_OPEN
        with patch("time.monotonic", return_value=cb._opened_at + 31.0):
            cb._get_state()

        assert cb._state == CircuitBreaker._HALF_OPEN

        # Probe fails → should reopen
        with pytest.raises(ValueError):
            await cb.call(_fail_fn)

        assert cb._state == CircuitBreaker._OPEN

    # ── test_exclude_exception_not_counted ───────────────────────────────────

    async def test_exclude_exception_not_counted(self):
        """Excluded exception types must not increment the failure counter."""
        cb = _make_cb(fail_max=2, exclude=(KeyError,))

        async def raise_key_error():
            raise KeyError("not a real failure")

        # Call it more than fail_max times — should never open
        for _ in range(5):
            with pytest.raises(KeyError):
                await cb.call(raise_key_error)

        assert cb._failures == 0
        assert cb._state == CircuitBreaker._CLOSED


# ===========================================================================
# Properties
# ===========================================================================


class TestCircuitBreakerProperties:

    # ── test_state_property ──────────────────────────────────────────────────

    def test_state_property(self):
        cb = _make_cb()
        assert cb.state == "closed"

        cb._state = CircuitBreaker._OPEN
        cb._opened_at = 0.0  # very far in the past will trip HALF_OPEN in _get_state
        # Patch monotonic so we stay in OPEN (not enough time passed)
        with patch("time.monotonic", return_value=1.0):
            cb._opened_at = 1.0  # opened "just now"
            assert cb.state == "open"

        cb._state = CircuitBreaker._HALF_OPEN
        assert cb.state == "half_open"

    # ── test_failures_property ───────────────────────────────────────────────

    async def test_failures_property(self):
        cb = _make_cb(fail_max=10)
        assert cb.failures == 0

        with pytest.raises(ValueError):
            await cb.call(_fail_fn)
        assert cb.failures == 1

        with pytest.raises(ValueError):
            await cb.call(_fail_fn)
        assert cb.failures == 2


# ===========================================================================
# CircuitBreakerOpen exception
# ===========================================================================


class TestCircuitBreakerOpenException:

    # ── test_circuit_breaker_open_exception_message ──────────────────────────

    def test_circuit_breaker_open_exception_message(self):
        exc = CircuitBreakerOpen(name="my_service", retry_after=42.5)

        assert exc.name == "my_service"
        assert exc.retry_after == pytest.approx(42.5)
        # The string representation should mention the name and the retry time
        msg = str(exc)
        assert "my_service" in msg
        assert "42.5" in msg
