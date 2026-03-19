from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

from bot.config import settings
from bot.utils.logger import get_logger

logger = get_logger(__name__)

KYIV_TZ = ZoneInfo("Europe/Kyiv")

_schedule_cache: dict[str, tuple[datetime, Any]] = {}
_image_cache: dict[str, tuple[datetime, bytes]] = {}
CACHE_TTL = timedelta(minutes=2)
MAX_CACHE_SIZE = 100

_http_client: aiohttp.ClientSession | None = None
_last_commit_sha: str | None = None


async def init_http_client() -> None:
    """Initialise the shared HTTP client. Call once at bot startup."""
    global _http_client
    connector = aiohttp.TCPConnector(limit=20)
    _http_client = aiohttp.ClientSession(connector=connector)


async def close_http_client() -> None:
    """Close the shared HTTP client. Call once at bot shutdown."""
    global _http_client
    if _http_client is not None:
        await _http_client.close()
        _http_client = None


async def check_source_repo_updated() -> bool:
    """Check if Baskerville42/outage-data-ua has new commits in data/ directory.

    Uses GitHub Commits API which is not affected by CDN caching.
    With GITHUB_TOKEN: 5000 requests/hour limit.
    Without token: 60 requests/hour limit.

    Returns True if new data is available or on any error (fail-open).
    Returns False if no changes detected.
    """
    global _last_commit_sha

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Voltyk-Bot/4.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

    url = "https://api.github.com/repos/Baskerville42/outage-data-ua/commits?per_page=1&path=data"

    _owned = False
    _session = _http_client
    if _session is None:
        _session = aiohttp.ClientSession()
        _owned = True
    try:
        async with _session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=15),
            headers=headers,
        ) as resp:
            if resp.status == 200:
                commits = await resp.json(content_type=None)
                if commits and isinstance(commits, list):
                    first = commits[0]
                    if not isinstance(first, dict) or "sha" not in first:
                        logger.warning("Unexpected commit object structure, falling back to full fetch")
                        return True
                    new_sha = first["sha"]
                    if _last_commit_sha is None:
                        _last_commit_sha = new_sha
                        logger.info("Initial commit SHA: %s", new_sha[:8])
                        return True
                    if new_sha != _last_commit_sha:
                        logger.info("New commit detected: %s -> %s", _last_commit_sha[:8], new_sha[:8])
                        _last_commit_sha = new_sha
                        return True
                    logger.debug("No new commits (SHA: %s)", new_sha[:8])
                    return False
            else:
                logger.warning("GitHub Commits API returned %d, falling back to full fetch", resp.status)
                return True
    except Exception as e:
        logger.warning("GitHub Commits API check failed: %s, falling back to full fetch", e)
        return True
    finally:
        if _owned:
            await _session.close()

    return True


async def fetch_schedule_data(
    region: str, cache_ttl_s: int | None = None, force_refresh: bool = False
) -> dict | None:
    # TTL = interval minus 5s buffer (minimum 10s). Falls back to settings if not provided.
    effective_ttl = timedelta(seconds=max((cache_ttl_s or settings.SCHEDULE_CHECK_INTERVAL_S) - 5, 10))

    cache_key = region
    now = datetime.now()
    if not force_refresh and cache_key in _schedule_cache:
        cached_at, data = _schedule_cache[cache_key]
        if now - cached_at < effective_ttl:
            return data

    url = settings.DATA_URL_TEMPLATE.replace('{region}', region)
    retry_delays = [1, 3]

    for attempt in range(len(retry_delays) + 1):
        _owned = False
        _session = _http_client
        if _session is None:
            logger.warning("HTTP client not initialised, falling back to temporary session")
            _session = aiohttp.ClientSession()
            _owned = True
        try:
            async with _session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=30),
                headers={
                    "User-Agent": "SvitloCheck-Bot/4.0",
                },
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if len(_schedule_cache) >= MAX_CACHE_SIZE:
                        oldest = min(_schedule_cache, key=lambda k: _schedule_cache[k][0])
                        del _schedule_cache[oldest]
                    _schedule_cache[cache_key] = (now, data)
                    return data
                logger.warning("Schedule fetch %s returned %d", region, resp.status)
        except (TimeoutError, aiohttp.ClientError) as e:
            logger.warning("Schedule fetch %s attempt %d failed: %s", region, attempt + 1, e)
        finally:
            if _owned:
                await _session.close()
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

    queue_dashed = queue.replace(".", "-")
    url = settings.IMAGE_URL_TEMPLATE.replace('{region}', region).replace('{queue}', queue_dashed)

    try:
        _owned = False
        _session = _http_client
        if _session is None:
            logger.warning("HTTP client not initialised, falling back to temporary session")
            _session = aiohttp.ClientSession()
            _owned = True
        try:
            async with _session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=30),
                headers={
                    "User-Agent": "SvitloCheck-Bot/4.0",
                },
            ) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if len(_image_cache) >= MAX_CACHE_SIZE:
                        oldest = min(_image_cache, key=lambda k: _image_cache[k][0])
                        del _image_cache[oldest]
                    _image_cache[cache_key] = (now, data)
                    return data
        finally:
            if _owned:
                await _session.close()
    except (TimeoutError, aiohttp.ClientError) as e:
        logger.warning("Image fetch %s/%s failed: %s", region, queue, e)

    return None


def _parse_hourly_schedule(hourly_data: dict) -> tuple[list[dict], list[dict]]:
    """Parse hourly data (1-24 keys) into planned and possible outage periods."""
    planned: list[dict] = []
    possible: list[dict] = []

    for hour in range(1, 25):
        value = hourly_data.get(str(hour)) or hourly_data.get(hour)
        if value is None:
            continue

        if value in ("no", "first", "second"):
            _add_outage_period(planned, hour, value)
        elif value in ("maybe", "mfirst", "msecond"):
            _add_outage_period(possible, hour, value)

    return _merge_consecutive(planned), _merge_consecutive(possible)


def _add_outage_period(periods: list[dict], hour: int, value: str) -> None:
    """hour=14 with 'no' means period 13:00-14:00 (1-based indexing)."""
    if value in ("no", "maybe"):
        _add_or_extend(periods, hour - 1, hour)
    elif value in ("first", "mfirst"):
        _add_or_extend(periods, hour - 1, hour - 0.5)
    elif value in ("second", "msecond"):
        _add_or_extend(periods, hour - 0.5, hour)


def _add_or_extend(periods: list[dict], start: float, end: float) -> None:
    if periods and periods[-1]["end"] == start:
        periods[-1]["end"] = end
    else:
        periods.append({"start": start, "end": end})


def _merge_consecutive(periods: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for p in periods:
        if merged and merged[-1]["end"] == p["start"]:
            merged[-1]["end"] = p["end"]
        else:
            merged.append({**p})
    return merged


def _hour_to_datetime(base_date: datetime, hour_value: float) -> datetime:
    """Convert hour value (e.g. 13.5 = 13:30) to datetime.
    hour=24 rolls over to 00:00 next day (Python handles this)."""
    h = int(hour_value)
    m = int((hour_value % 1) * 60)
    return base_date.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=h, minutes=m)


def parse_schedule_for_queue(raw_data: dict | None, queue: str) -> dict:
    """Parse raw API data into schedule events for a specific queue."""
    if not raw_data or not isinstance(raw_data, dict):
        return {"hasData": False, "events": [], "queue": queue}

    fact = raw_data.get("fact")
    if not fact or not isinstance(fact, dict):
        return {"hasData": False, "events": [], "queue": queue}

    fact_data = fact.get("data")
    if not fact_data or not isinstance(fact_data, dict):
        return {"hasData": False, "events": [], "queue": queue}

    queue_key = f"GPV{queue}"

    timestamps = sorted(int(ts) for ts in fact_data.keys())
    if not timestamps:
        return {"hasData": False, "events": [], "queue": queue}

    events: list[dict] = []

    today_ts = timestamps[0]
    tomorrow_ts = timestamps[1] if len(timestamps) > 1 else None

    today_schedule = fact_data.get(str(today_ts), {}).get(queue_key)
    if today_schedule:
        today_date = datetime.fromtimestamp(today_ts, tz=KYIV_TZ)
        planned, possible = _parse_hourly_schedule(today_schedule)

        for p in planned:
            events.append({
                "start": _hour_to_datetime(today_date, p["start"]).isoformat(),
                "end": _hour_to_datetime(today_date, p["end"]).isoformat(),
                "isPossible": False,
            })
        for p in possible:
            events.append({
                "start": _hour_to_datetime(today_date, p["start"]).isoformat(),
                "end": _hour_to_datetime(today_date, p["end"]).isoformat(),
                "isPossible": True,
            })

    if tomorrow_ts:
        tomorrow_schedule = fact_data.get(str(tomorrow_ts), {}).get(queue_key)
        if tomorrow_schedule:
            tomorrow_date = datetime.fromtimestamp(tomorrow_ts, tz=KYIV_TZ)
            planned, possible = _parse_hourly_schedule(tomorrow_schedule)

            for p in planned:
                events.append({
                    "start": _hour_to_datetime(tomorrow_date, p["start"]).isoformat(),
                    "end": _hour_to_datetime(tomorrow_date, p["end"]).isoformat(),
                    "isPossible": False,
                })
            for p in possible:
                events.append({
                    "start": _hour_to_datetime(tomorrow_date, p["start"]).isoformat(),
                    "end": _hour_to_datetime(tomorrow_date, p["end"]).isoformat(),
                    "isPossible": True,
                })

    events.sort(key=lambda e: e["start"])

    return {"hasData": len(events) > 0, "events": events, "queue": queue}


def _parse_dt(dt_str: str) -> datetime:
    """Parse an ISO datetime string, attaching Kyiv TZ when the string is offset-naive."""
    dt = datetime.fromisoformat(dt_str)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=KYIV_TZ)
    return dt


def find_next_event(schedule_data: dict) -> dict | None:
    if not schedule_data.get("hasData"):
        return None

    now = datetime.now(KYIV_TZ)
    events = schedule_data.get("events", [])

    for i, ev in enumerate(events):
        start = _parse_dt(ev["start"])
        end = _parse_dt(ev["end"])

        if start <= now < end:
            final_end = end
            j = i + 1
            while j < len(events) and _parse_dt(events[j]["start"]) == final_end:
                final_end = _parse_dt(events[j]["end"])
                j += 1
            return {
                "type": "power_on",
                "time": final_end.isoformat(),
                "startTime": ev["start"],
                "endTime": None,
                "minutes": int((final_end - now).total_seconds() / 60),
                "isPossible": ev.get("isPossible", False),
            }

        if now < start:
            return {
                "type": "power_off",
                "time": ev["start"],
                "endTime": ev["end"],
                "minutes": int((start - now).total_seconds() / 60),
                "isPossible": ev.get("isPossible", False),
            }

    return None


def calculate_schedule_hash(events: list[dict]) -> str:
    data = json.dumps(events, sort_keys=True)
    return hashlib.md5(data.encode()).hexdigest()
