from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any

import aiohttp

from bot.config import settings

logger = logging.getLogger(__name__)

_schedule_cache: dict[str, tuple[datetime, Any]] = {}
_image_cache: dict[str, tuple[datetime, bytes]] = {}
CACHE_TTL = timedelta(minutes=2)
MAX_CACHE_SIZE = 100


async def fetch_schedule_data(region: str) -> dict | None:
    cache_key = region
    now = datetime.now()
    if cache_key in _schedule_cache:
        cached_at, data = _schedule_cache[cache_key]
        if now - cached_at < CACHE_TTL:
            return data

    url = settings.DATA_URL_TEMPLATE.replace("{region}", region)
    retry_delays = [5, 15, 45]

    for attempt in range(len(retry_delays) + 1):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=30),
                    headers={"User-Agent": "SvitloCheck-Bot/4.0"},
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if len(_schedule_cache) >= MAX_CACHE_SIZE:
                            oldest = min(_schedule_cache, key=lambda k: _schedule_cache[k][0])
                            del _schedule_cache[oldest]
                        _schedule_cache[cache_key] = (now, data)
                        return data
                    logger.warning("Schedule fetch %s returned %d", region, resp.status)
        except (TimeoutError, aiohttp.ClientError) as e:
            logger.warning("Schedule fetch %s attempt %d failed: %s", region, attempt + 1, e)
        if attempt < len(retry_delays):
            await asyncio.sleep(retry_delays[attempt])

    return None


async def fetch_schedule_image(region: str, queue: str) -> bytes | None:
    cache_key = f"{region}_{queue}"
    now = datetime.now()
    if cache_key in _image_cache:
        cached_at, data = _image_cache[cache_key]
        if now - cached_at < CACHE_TTL:
            return data

    url = settings.IMAGE_URL_TEMPLATE.replace("{region}", region).replace("{queue}", queue)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"User-Agent": "SvitloCheck-Bot/4.0"},
            ) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if len(_image_cache) >= MAX_CACHE_SIZE:
                        oldest = min(_image_cache, key=lambda k: _image_cache[k][0])
                        del _image_cache[oldest]
                    _image_cache[cache_key] = (now, data)
                    return data
    except (TimeoutError, aiohttp.ClientError) as e:
        logger.warning("Image fetch %s/%s failed: %s", region, queue, e)

    return None


def parse_schedule_for_queue(raw_data: dict | None, queue: str) -> dict:
    if not raw_data:
        return {"hasData": False, "events": []}

    events = []
    groups = raw_data.get("groups", raw_data.get("data", []))
    if isinstance(groups, dict):
        group_data = groups.get(queue, [])
    elif isinstance(groups, list):
        group_data = []
        for g in groups:
            if g.get("queue") == queue or g.get("group") == queue:
                group_data = g.get("events", g.get("periods", []))
                break
    else:
        group_data = []

    for ev in group_data:
        start = ev.get("start")
        end = ev.get("end")
        if start and end:
            try:
                start_dt = datetime.fromisoformat(str(start))
                end_dt = datetime.fromisoformat(str(end))
                events.append({
                    "start": start_dt.isoformat(),
                    "end": end_dt.isoformat(),
                    "isPossible": ev.get("isPossible", ev.get("is_possible", False)),
                })
            except (ValueError, TypeError):
                continue

    return {"hasData": len(events) > 0, "events": events}


def find_next_event(schedule_data: dict) -> dict | None:
    if not schedule_data.get("hasData"):
        return None

    now = datetime.now()
    events = schedule_data.get("events", [])
    next_ev = None
    min_diff = float("inf")

    for ev in events:
        start = datetime.fromisoformat(ev["start"])
        end = datetime.fromisoformat(ev["end"])

        if now < start:
            diff = (start - now).total_seconds() / 60
            if diff < min_diff:
                min_diff = diff
                next_ev = {
                    "type": "power_off",
                    "time": ev["start"],
                    "endTime": ev["end"],
                    "minutes": int(diff),
                    "isPossible": ev.get("isPossible", False),
                }
        elif start <= now <= end:
            diff = (end - now).total_seconds() / 60
            if diff < min_diff:
                min_diff = diff
                next_ev = {
                    "type": "power_on",
                    "time": ev["end"],
                    "startTime": ev["start"],
                    "minutes": int(diff),
                    "isPossible": ev.get("isPossible", False),
                }

    return next_ev


def calculate_schedule_hash(events: list[dict]) -> str:
    data = json.dumps(events, sort_keys=True)
    return hashlib.md5(data.encode()).hexdigest()
