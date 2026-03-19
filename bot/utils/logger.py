from __future__ import annotations

import logging
import sys
from datetime import datetime

_LEVEL_EMOJIS = {
    logging.DEBUG: "🔍 ",
    logging.INFO: "ℹ️ ",
    logging.WARNING: "⚠️ ",
    logging.ERROR: "❌ ",
    logging.CRITICAL: "🔥 ",
}

# Maps logger name prefixes to human-readable context labels
_CONTEXT_MAP = {
    "bot.app": "App",
    "bot.config": "App",
    "bot.db": "DB",
    "bot.services.scheduler": "Scheduler",
    "bot.services.power_monitor": "PowerMonitor",
    "bot.services": "Services",
    "bot.handlers": "Handler",
    "bot.middlewares": "Middleware",
    "bot.utils": "Utils",
    "bot": "Bot",
    "alembic": "Alembic",
}


def _get_context(name: str) -> str:
    """Derive a short context label from a logger name."""
    for prefix, label in _CONTEXT_MAP.items():
        if name == prefix or name.startswith(prefix + "."):
            return label
    # Fallback: capitalise the last segment of the dotted name
    return name.split(".")[-1].capitalize() if name else "App"


class _EmojiFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%dT%H:%M:%S")
        emoji = _LEVEL_EMOJIS.get(record.levelno, "ℹ️ ")
        context = _get_context(record.name)
        message = record.getMessage()
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            message = f"{message}\n{exc_text}"
        return f"[{timestamp}] {emoji} [{context}] {message}"


def setup_logging() -> None:
    """Configure root logger with emoji formatter writing to stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_EmojiFormatter())

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)

    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a standard Logger; formatting is handled by the root handler."""
    return logging.getLogger(name)
