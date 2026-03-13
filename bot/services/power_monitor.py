from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from bot.config import settings
from bot.db.queries import get_users_with_ip
from bot.db.session import async_session

logger = logging.getLogger(__name__)

_running = False


async def power_monitor_loop():
    global _running
    _running = True
    logger.info("Power monitor started (interval: %ds)", settings.POWER_CHECK_INTERVAL_S)

    while _running:
        try:
            await _check_all_ips()
        except Exception as e:
            logger.error("Power monitor error: %s", e)
        await asyncio.sleep(settings.POWER_CHECK_INTERVAL_S)


async def _check_all_ips():
    async with async_session() as session:
        users = await get_users_with_ip(session)

        for user in users:
            if not user.router_ip:
                continue

            is_online = await _ping_host(user.router_ip)
            new_state = "on" if is_online else "off"

            pt = user.power_tracking
            if pt and pt.power_state != new_state:
                pt.power_state = new_state
                pt.power_changed_at = datetime.utcnow()
                logger.info(
                    "Power state changed: user=%s ip=%s state=%s",
                    user.telegram_id,
                    user.router_ip,
                    new_state,
                )

        await session.commit()


async def _ping_host(host: str) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping",
            "-c",
            "1",
            "-W",
            str(settings.POWER_PING_TIMEOUT_MS // 1000),
            host,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=settings.POWER_PING_TIMEOUT_MS / 1000 + 1)
        return proc.returncode == 0
    except (TimeoutError, OSError):
        return False


def stop_power_monitor():
    global _running
    _running = False
