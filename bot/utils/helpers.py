from __future__ import annotations

import asyncio
import ipaddress
import re
from collections.abc import Awaitable, Callable
from typing import TypeVar

from aiogram.exceptions import TelegramRetryAfter

_T = TypeVar("_T")

_IP_RE = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")
_DOMAIN_RE = re.compile(
    r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?"
    r"(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$"
)

# Networks that must never be reachable via user-supplied router IPs.
# Allowing these would enable SSRF attacks against the internal network,
# cloud metadata services (169.254.169.254), or the loopback interface.
_BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network, ...] = (
    ipaddress.IPv4Network("10.0.0.0/8"),        # RFC 1918 private
    ipaddress.IPv4Network("172.16.0.0/12"),      # RFC 1918 private
    ipaddress.IPv4Network("192.168.0.0/16"),     # RFC 1918 private
    ipaddress.IPv4Network("127.0.0.0/8"),        # loopback
    ipaddress.IPv4Network("169.254.0.0/16"),     # link-local / cloud metadata
    ipaddress.IPv4Network("0.0.0.0/8"),          # "this" network
    ipaddress.IPv4Network("100.64.0.0/10"),      # carrier-grade NAT
    ipaddress.IPv4Network("192.0.0.0/24"),       # IETF protocol assignments
    ipaddress.IPv4Network("198.18.0.0/15"),      # benchmarking
    ipaddress.IPv4Network("198.51.100.0/24"),    # documentation (TEST-NET-2)
    ipaddress.IPv4Network("203.0.113.0/24"),     # documentation (TEST-NET-3)
    ipaddress.IPv4Network("240.0.0.0/4"),        # reserved
    ipaddress.IPv4Network("255.255.255.255/32"), # broadcast
)


def _is_private_ip(address: str) -> bool:
    """Return True if *address* belongs to any SSRF-blocked network."""
    try:
        ip = ipaddress.IPv4Address(address)
        return any(ip in net for net in _BLOCKED_NETWORKS)
    except ValueError:
        return False


async def retry_bot_call(
    coro_factory: Callable[[], Awaitable[_T]],
    *,
    max_retries: int = 3,
) -> _T:
    """Execute a Telegram bot API call, retrying on TelegramRetryAfter (429).

    Pass a lambda so a fresh coroutine is created for each attempt:
        await retry_bot_call(lambda: bot.send_message(chat_id, text))
    """
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except TelegramRetryAfter as e:
            if attempt >= max_retries:
                raise
            await asyncio.sleep(e.retry_after + 1)
    raise RuntimeError("unreachable")


def is_valid_ip_or_domain(address: str) -> dict:
    """Validate a user-supplied router address (IP[:port] or domain[:port]).

    Security: rejects private/loopback/link-local IP ranges to prevent SSRF.
    Routers are expected to have public or LAN IPs accessible from the host
    running the bot.  If a user has a LAN router with a private IP they should
    run the bot on the same network — but the bot process itself must not be
    weaponised to probe internal infrastructure.

    NOTE: Private IP ranges (192.168.x.x, 10.x.x.x, 172.16–31.x.x) ARE the
    typical home-router addresses, so we intentionally ALLOW them here and only
    block the truly dangerous ranges (loopback, link-local/metadata, broadcast).
    This balances usability (most users have a 192.168.x.x router) against
    SSRF risk (cloud metadata at 169.254.169.254, localhost at 127.x.x.x).
    """
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

    match = _IP_RE.match(host)
    if match:
        octets = [int(g) for g in match.groups()]
        if all(0 <= o <= 255 for o in octets):
            # Block loopback and cloud-metadata ranges (SSRF risk).
            # Private RFC-1918 ranges are allowed — typical home router IPs.
            try:
                ip = ipaddress.IPv4Address(host)
                _ssrf_blocked = (
                    ipaddress.IPv4Network("127.0.0.0/8"),        # loopback
                    ipaddress.IPv4Network("169.254.0.0/16"),     # link-local / AWS metadata
                    ipaddress.IPv4Network("0.0.0.0/8"),          # "this" network
                    ipaddress.IPv4Network("240.0.0.0/4"),        # reserved
                    ipaddress.IPv4Network("255.255.255.255/32"), # broadcast
                )
                if any(ip in net for net in _ssrf_blocked):
                    return {"valid": False, "error": "Недопустима адреса"}
            except ValueError:
                pass
            return {"valid": True, "address": address, "host": host, "port": port, "type": "ip"}

    if _DOMAIN_RE.match(host):
        return {"valid": True, "address": address, "host": host, "port": port, "type": "domain"}

    return {"valid": False, "error": "Невірний формат адреси. Приклад: 192.168.1.1 або router.example.com"}


def safe_parse_callback_int(data: str | None, prefix: str) -> int | None:
    """Safely extract an integer from callback data by removing the prefix.

    Returns None if the data doesn't start with the prefix or the remainder
    is not a valid integer.
    """
    if not data or not data.startswith(prefix):
        return None
    remainder = data[len(prefix):]
    try:
        return int(remainder)
    except (ValueError, TypeError):
        return None

