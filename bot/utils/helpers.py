from __future__ import annotations

import re
from html import escape as html_escape


def escape_html(text: str) -> str:
    return html_escape(text)


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
DEFAULT_SCHEDULE_CAPTION = "Графік на {dd}, {dm} для черги {queue}"
DEFAULT_PERIOD_FORMAT = "{s} - {f} ({h} год)"


def get_channel_welcome_message(queue: str) -> str:
    return (
        "👋 Цей канал підключено до СвітлоБота — чат-бота для моніторингу світла.\n\n"
        "Тут публікуватимуться:\n"
        "• 📊 Графіки відключень\n"
        "• ⚡ Сповіщення про стан світла (якщо IP налаштований)\n\n"
        f"Черга: {queue}"
    )
