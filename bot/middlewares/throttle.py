from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class ThrottleMiddleware(BaseMiddleware):
    def __init__(self, rate_limit: float = 0.5):
        self._rate_limit = rate_limit
        self._last_call: dict[int, float] = defaultdict(float)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user:
            now = time.monotonic()
            if now - self._last_call[user.id] < self._rate_limit:
                return None
            self._last_call[user.id] = now

        return await handler(event, data)
