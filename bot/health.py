"""Health check HTTP endpoints for liveness and readiness probes.

Exposes two endpoints via :mod:`aiohttp.web`:

* ``GET /health`` — **Liveness probe**.  Returns 200 as long as the process is
  alive and records whether the scheduler has run recently.
* ``GET /ready``  — **Readiness probe**.  Returns 200 only when every
  dependency (database, Telegram bot instance, scheduler) is healthy; 503
  otherwise.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from aiohttp import web
from sqlalchemy import text

from bot.config import settings
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from aiogram import Bot

logger = get_logger(__name__)


def _scheduler_status(interval_s: int) -> tuple[bool, str | None]:
    """Return ``(alive, last_check_iso)`` for the scheduler liveness check.

    *alive* is ``True`` when the last successful check occurred within
    ``interval_s * 3`` seconds (i.e. the scheduler has not missed three
    consecutive cycles).
    """
    from bot.services.scheduler import get_last_check_at  # deferred import

    last = get_last_check_at()
    if last is None:
        return False, None

    last_iso = last.isoformat()
    threshold = timedelta(seconds=interval_s * 3)
    now = datetime.now(timezone.utc)
    alive = (now - last) < threshold
    return alive, last_iso


def make_health_handler(interval_s: int):
    """Return an aiohttp request handler for ``GET /health``."""

    async def health_handler(_request: web.Request) -> web.Response:
        """Liveness probe — always 200 while the process is alive."""
        from bot.app import _start_time  # deferred import

        uptime = time.time() - _start_time.timestamp()
        alive, last_check_iso = _scheduler_status(interval_s)

        payload = {
            "status": "ok",
            "uptime_seconds": round(uptime, 1),
            "scheduler": {
                "alive": alive,
                "last_check_at": last_check_iso,
            },
        }
        return web.json_response(payload)

    return health_handler


def make_ready_handler(bot: "Bot", interval_s: int):
    """Return an aiohttp request handler for ``GET /ready``."""

    async def ready_handler(_request: web.Request) -> web.Response:
        """Readiness probe — 200 when all checks pass, 503 otherwise."""
        from bot.db.session import async_session  # deferred import

        checks: dict = {}
        all_ok = True

        # ── Database ──────────────────────────────────────────────────────
        db_start = time.perf_counter()
        try:
            async with async_session() as session:
                await session.execute(text("SELECT 1"))
            db_latency_ms = round((time.perf_counter() - db_start) * 1000, 2)
            checks["database"] = {"status": "ok", "latency_ms": db_latency_ms}
        except Exception as exc:
            checks["database"] = {"status": "error", "message": str(exc)}
            all_ok = False
            logger.warning("Readiness: database check failed: %s", exc)

        # ── Telegram API (bot object existence check — no network call) ───
        if bot is not None and bot.token:
            checks["telegram_api"] = {"status": "ok"}
        else:
            checks["telegram_api"] = {
                "status": "error",
                "message": "bot instance not configured",
            }
            all_ok = False

        # ── Scheduler ─────────────────────────────────────────────────────
        alive, last_check_iso = _scheduler_status(interval_s)
        if alive:
            checks["scheduler"] = {"status": "ok", "last_check_at": last_check_iso}
        else:
            checks["scheduler"] = {
                "status": "error",
                "last_check_at": last_check_iso,
                "message": "scheduler has not run recently",
            }
            all_ok = False

        status_text = "ready" if all_ok else "unavailable"
        http_status = 200 if all_ok else 503
        payload = {"status": status_text, "checks": checks}
        return web.json_response(payload, status=http_status)

    return ready_handler


def register_health_routes(app: web.Application, bot: "Bot") -> None:
    """Register ``/health`` and ``/ready`` on an existing :class:`aiohttp.web.Application`.

    Call this before starting the aiohttp runner so that the routes are
    available immediately when the server begins accepting connections.
    """
    interval_s = settings.SCHEDULE_CHECK_INTERVAL_S
    app.router.add_get("/health", make_health_handler(interval_s))
    app.router.add_get("/ready", make_ready_handler(bot, interval_s))
    logger.info("Health routes registered (/health, /ready)")


async def start_health_server(bot: "Bot") -> tuple[web.AppRunner, web.TCPSite]:
    """Create and start a standalone aiohttp health server on ``settings.HEALTH_PORT``.

    Used in *polling* mode where no webhook aiohttp app already exists.
    Returns ``(runner, site)`` so the caller can shut them down gracefully.
    """
    app = web.Application()
    register_health_routes(app, bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.HEALTH_PORT)
    await site.start()
    logger.info("Health server started on 0.0.0.0:%d", settings.HEALTH_PORT)
    return runner, site
