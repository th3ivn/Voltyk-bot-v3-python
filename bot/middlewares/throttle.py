from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

_CLEANUP_INTERVAL = 300  # run cleanup every 5 minutes
_ENTRY_TTL = 60  # remove entries inactive for 60+ seconds


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
                cutoff = now - _ENTRY_TTL
                self._last_call = {uid: t for uid, t in self._last_call.items() if t > cutoff}
                self._last_cleanup = now

            if now - self._last_call.get(user.id, 0.0) < self._rate_limit:
                return None
            self._last_call[user.id] = now

        return await handler(event, data)
