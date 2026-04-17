"""Tests for bot/utils/rate_limiter.py.

Covers:
- TokenBucketRateLimiter: token consumption, sleep behaviour, refill logic,
  update_rate(), burst cap, and concurrent safety.
- tg_rate_limiter: module-level singleton exists.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from bot.utils.rate_limiter import TokenBucketRateLimiter, tg_rate_limiter

# ===========================================================================
# TokenBucketRateLimiter
# ===========================================================================


class TestTokenBucketRateLimiter:
    """Unit tests for TokenBucketRateLimiter."""

    # ── helpers ─────────────────────────────────────────────────────────────

    def _make_limiter(self, rate: float = 10.0, burst: float | None = None) -> TokenBucketRateLimiter:
        return TokenBucketRateLimiter(rate=rate, burst=burst)

    # ── test_tokens_consumed_on_acquire ─────────────────────────────────────

    async def test_tokens_consumed_on_acquire(self):
        """After a successful acquire(), the token count decreases by 1."""
        limiter = self._make_limiter(rate=10.0)
        initial_tokens = limiter._tokens  # should equal burst (10.0)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await limiter.acquire()

        # _tokens should now be burst - 1
        assert limiter._tokens == pytest.approx(initial_tokens - 1.0, abs=0.1)

    # ── test_no_sleep_when_tokens_available ──────────────────────────────────

    async def test_no_sleep_when_tokens_available(self):
        """asyncio.sleep is NOT called when the bucket has tokens."""
        limiter = self._make_limiter(rate=10.0)
        # Ensure bucket is full
        limiter._tokens = 10.0

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await limiter.acquire()

        mock_sleep.assert_not_called()

    # ── test_sleeps_when_bucket_empty ────────────────────────────────────────

    async def test_sleeps_when_bucket_empty(self):
        """asyncio.sleep IS called when the bucket is empty."""
        limiter = self._make_limiter(rate=10.0)
        limiter._tokens = 0.0
        # Pre-set _last_refill so elapsed ≈ 0 → no automatic top-up
        loop = asyncio.get_running_loop()
        limiter._last_refill = loop.time()

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await limiter.acquire()

        mock_sleep.assert_called_once()
        wait_arg = mock_sleep.call_args[0][0]
        assert wait_arg > 0.0

    # ── test_last_refill_updated_after_sleep ─────────────────────────────────

    async def test_last_refill_updated_after_sleep(self):
        """After the sleep path, _last_refill is updated to the current loop time."""
        limiter = self._make_limiter(rate=10.0)
        limiter._tokens = 0.0
        loop = asyncio.get_running_loop()
        old_time = loop.time()
        limiter._last_refill = old_time

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await limiter.acquire()

        # _last_refill must be >= the value we set (it's refreshed after sleep)
        assert limiter._last_refill >= old_time

    # ── test_tokens_refill_over_time ─────────────────────────────────────────

    async def test_tokens_refill_over_time(self):
        """Tokens are replenished based on elapsed time when acquire() runs."""
        rate = 10.0
        limiter = self._make_limiter(rate=rate)
        limiter._tokens = 0.0

        loop = asyncio.get_running_loop()
        # Pretend the last refill happened 0.5 s ago → 5 tokens should be added
        limiter._last_refill = loop.time() - 0.5

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await limiter.acquire()

        # After acquiring 1 token from the ~5 refilled, _tokens should be ~4
        # (allow some tolerance for execution time)
        assert limiter._tokens >= 3.5

    # ── test_update_rate ────────────────────────────────────────────────────

    async def test_update_rate(self):
        """update_rate() changes both _rate and _burst."""
        limiter = self._make_limiter(rate=10.0)
        limiter.update_rate(5.0)

        assert limiter._rate == 5.0
        assert limiter._burst == 5.0

    # ── test_burst_cap ──────────────────────────────────────────────────────

    async def test_burst_cap(self):
        """Tokens never exceed the burst limit even when a lot of time has passed."""
        burst = 5.0
        limiter = self._make_limiter(rate=10.0, burst=burst)
        limiter._tokens = burst

        loop = asyncio.get_running_loop()
        # Simulate a very long gap (100 s worth of refill)
        limiter._last_refill = loop.time() - 100.0

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await limiter.acquire()

        # After acquire the bucket was capped at burst, then one token consumed
        assert limiter._tokens == pytest.approx(burst - 1.0, abs=0.01)

    # ── test_concurrent_acquires ─────────────────────────────────────────────

    async def test_concurrent_acquires(self):
        """Concurrent acquires all complete without token count going below -1."""
        rate = 20.0
        limiter = self._make_limiter(rate=rate)
        limiter._tokens = rate  # full bucket

        call_count = 10

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await asyncio.gather(*(limiter.acquire() for _ in range(call_count)))

        # tokens should be >= -1 (never over-consumed by more than a rounding error)
        assert limiter._tokens >= -1.0


# ===========================================================================
# tg_rate_limiter singleton
# ===========================================================================


class TestTgRateLimiterSingleton:
    """Sanity-checks for the module-level singleton."""

    def test_singleton_is_token_bucket(self):
        assert isinstance(tg_rate_limiter, TokenBucketRateLimiter)

    def test_singleton_has_positive_rate(self):
        assert tg_rate_limiter._rate > 0

    def test_make_limiter_falls_back_on_import_error(self):
        """If settings import raises, _make_limiter() returns a 25 req/s limiter."""

        from unittest.mock import patch

        with patch.dict("sys.modules", {"bot.config": None}):
            from bot.utils import rate_limiter as rl_mod
            limiter = rl_mod._make_limiter()

        assert isinstance(limiter, TokenBucketRateLimiter)
        assert limiter._rate == 25.0
