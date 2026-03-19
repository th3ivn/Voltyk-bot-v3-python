from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import TypeVar

_T = TypeVar("_T")


async def retry_bot_call(
    coro_factory: Callable[[], Awaitable[_T]],
    *,
    max_retries: int = 1,
) -> _T:
    """Execute a Telegram bot API call, retrying on TelegramRetryAfter (429).

    Pass a lambda so a fresh coroutine is created for each attempt:
        await retry_bot_call(lambda: bot.send_message(chat_id, text))
    """
    from aiogram.exceptions import TelegramRetryAfter

    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except TelegramRetryAfter as e:
            if attempt >= max_retries:
                raise
            await asyncio.sleep(e.retry_after + 1)

    raise RuntimeError("unreachable")


def is_valid_ip_or_domain(address: str) -> dict:
    address = address.strip()
    if " " in address:
        return {"valid": False, "error": "Адреса не може містити пробіли"}

    host = address
    port = None
    if ":" in address:
        parts = address.rsplit(":", 1)
        if parts[1].isdigit():
            host = parts[0]
            port = int(parts[1])
            if not (1 <= port <= 65535):
                return {"valid": False, "error": "Порт має бути від 1 до 65535"}

    ip_pattern = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")
    match = ip_pattern.match(host)
    if match:
        octets = [int(g) for g in match.groups()]
        if all(0 <= o <= 255 for o in octets):
            return {"valid": True, "address": address, "host": host, "port": port, "type": "ip"}

    domain_pattern = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$")
    if domain_pattern.match(host):
        return {"valid": True, "address": address, "host": host, "port": port, "type": "domain"}

    return {"valid": False, "error": "Невірний формат адреси. Приклад: 192.168.1.1 або router.example.com"}


CHANNEL_NAME_PREFIX = "СвітлоБот ⚡️ "
CHANNEL_DESCRIPTION_BASE = (
    "⚡️ СвітлоБот — слідкує, щоб ви не слідкували.\n\n"
    "💬 Маєте ідеї або знайшли помилку?"
)
def get_channel_welcome_message(queue: str) -> str:
    return (
        "👋 Цей канал підключено до СвітлоБота — чат-бота для моніторингу світла.\n\n"
        "Тут публікуватимуться:\n"
        "• 📊 Графіки відключень\n"
        "• ⚡ Сповіщення про стан світла (якщо IP налаштований)\n\n"
        f"Черга: {queue}"
    )
