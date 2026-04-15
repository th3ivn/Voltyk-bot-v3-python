from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.utils.logger import get_logger

logger = get_logger(__name__)

_CLEANUP_INTERVAL = 300  # run cleanup every 5 minutes
_ENTRY_TTL = 60  # remove entries inactive for 60+ seconds
_MAX_ENTRIES = 100_000  # hard cap — sized for 100k active users


class ThrottleMiddleware(BaseMiddleware):
    def __init__(self, rate_limit: float = 0.5):
        self._rate_limit = rate_limit
        self._last_call: dict[int, float] = {}
        self._last_cleanup: float = time.monotonic()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user:
            now = time.monotonic()

            if now - self._last_cleanup > _CLEANUP_INTERVAL:
                before = len(self._last_call)
                cutoff = now - _ENTRY_TTL
                self._last_call = {uid: t for uid, t in self._last_call.items() if t > cutoff}
                evicted_ttl = before - len(self._last_call)

                # Hard cap: evict oldest entries if still over limit after TTL eviction
                if len(self._last_call) > _MAX_ENTRIES:
                    sorted_uids = sorted(self._last_call, key=lambda uid: self._last_call[uid])
                    excess = len(self._last_call) - _MAX_ENTRIES
                    for uid in sorted_uids[:excess]:
                        del self._last_call[uid]
                    logger.debug(
                        "ThrottleMiddleware: evicted %d oldest entries to enforce _MAX_ENTRIES=%d cap",
                        excess,
                        _MAX_ENTRIES,
                    )

                self._last_cleanup = now
                if evicted_ttl:
                    logger.debug("ThrottleMiddleware: TTL-evicted %d stale entries", evicted_ttl)

            if now - self._last_call.get(user.id, 0.0) < self._rate_limit:
                return None
            self._last_call[user.id] = now

        return await handler(event, data)
