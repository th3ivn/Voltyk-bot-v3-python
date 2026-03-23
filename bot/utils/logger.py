from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger


def setup_logging() -> None:
    """Configure structlog: JSON renderer in production, colored console in development.

    Reads ``settings.ENVIRONMENT`` to select the renderer.  Existing stdlib
    ``%s``-format-string call sites are preserved via ``PositionalArgumentsFormatter``.
    Both native structlog loggers (returned by :func:`get_logger`) and foreign
    stdlib loggers (e.g. from *aiogram*, *sqlalchemy*) share the same processor
    chain and final renderer.
    """
    from bot.config import settings  # deferred import to avoid circular deps at module load

    is_production = settings.ENVIRONMENT == "production"

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.ExceptionPrettyPrinter(),
    ]

    final_renderer = (
        structlog.processors.JSONRenderer()
        if is_production
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    # structlog native loggers: run shared_processors, then hand off to ProcessorFormatter
    structlog.configure(
        processors=shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # stdlib handler: foreign library log records go through shared_processors + renderer
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processor=final_renderer,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)

    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> "BoundLogger":
    """Return a structlog bound logger.

    Supports both legacy stdlib ``%s``-format strings and structlog keyword
    context (e.g. ``logger.bind(region=region, queue=queue).info("msg")``).
    """
    return structlog.stdlib.get_logger(name)
