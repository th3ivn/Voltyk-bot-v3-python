"""Token-bucket rate limiter for Telegram Bot API calls.

Telegram allows ≈30 messages/second globally and ≈1 message/second per
individual chat.  This module implements a shared token-bucket limiter that
caps the *global* outgoing send rate to ``settings.TELEGRAM_RATE_LIMIT_PER_SEC``
(default 25 msg/s), staying safely below the Telegram hard limit.

Usage
-----
Before every ``bot.send_message`` / ``bot.send_photo`` call that participates
in a mass notification blast, acquire a token::

    from bot.utils.rate_limiter import tg_rate_limiter
    await tg_rate_limiter.acquire()
    await bot.send_message(chat_id, text)

The limiter is a module-level singleton so all concurrent workers in
``_send_notifications_to_users`` share the same bucket.
"""

from __future__ import annotations

import asyncio


class TokenBucketRateLimiter:
    """Async token-bucket rate limiter.

    Tokens refill continuously at *rate* tokens/second up to a maximum of
    *burst* tokens.  ``acquire()`` removes one token, sleeping if the bucket
    is empty.

    All state is protected by a single asyncio.Lock so the limiter is safe for
    concurrent callers within the same event loop.
    """

    def __init__(self, rate: float, burst: float | None = None) -> None:
        """
        Args:
            rate:  Tokens per second (e.g. 25 → 25 msg/s).
            burst: Maximum bucket size.  Defaults to *rate* (no burst above
                   the steady-state rate).
        """
        self._rate = rate
        self._burst = burst if burst is not None else rate
        self._tokens = self._burst
        self._last_refill: float = 0.0  # set on first acquire()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until a token is available, then consume it."""
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()

            # Initialise _last_refill lazily so the limiter can be created at
            # import time (before an event loop is running).
            if self._last_refill == 0.0:
                self._last_refill = now

            elapsed = now - self._last_refill
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
                self._last_refill = loop.time()
            else:
                self._tokens -= 1.0

    def update_rate(self, rate: float) -> None:
        """Change the token refill rate at runtime (no lock needed for float assignment)."""
        self._rate = rate
        self._burst = rate


# Module-level singleton — shared across all scheduler workers.
# The rate is set lazily from settings to avoid importing settings at module load.
def _make_limiter() -> TokenBucketRateLimiter:
    try:
        from bot.config import settings
        return TokenBucketRateLimiter(rate=float(settings.TELEGRAM_RATE_LIMIT_PER_SEC))
    except Exception:
        return TokenBucketRateLimiter(rate=25.0)


tg_rate_limiter: TokenBucketRateLimiter = _make_limiter()
