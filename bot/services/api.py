from __future__ import annotations

import asyncio
import hashlib
import json
import time
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
_last_etag: str | None = None


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


async def check_source_repo_updated() -> tuple[bool, str | None]:
    """Check if Baskerville42/outage-data-ua has new commits in data/ directory.

    Uses GitHub Commits API which is not affected by caching.
    Sends If-None-Match with the stored ETag so that unchanged responses cost 0
    rate-limit requests (GitHub does not count 304s).
    With GITHUB_TOKEN: 5000 requests/hour limit.
    Without token: 60 requests/hour limit.

    Returns a ``(should_check, pending_sha)`` tuple:
    - ``(True, None)``  — initial run or API error; always run a full check.
    - ``(True, sha)``   — new commit detected; the caller **must** call
      :func:`confirm_source_update` after at least one queue shows changed
      data.
    - ``(False, None)``  — no new commits; skip the check.
    """
    global _last_commit_sha, _last_etag

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Voltyk-Bot/4.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"
    if _last_etag:
        headers["If-None-Match"] = _last_etag

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
            if resp.status == 304:
                logger.debug("GitHub API 304 Not Modified (cached)")
                return False, None
            if resp.status == 200:
                new_etag = resp.headers.get("ETag")
                if new_etag:
                    _last_etag = new_etag
                commits = await resp.json(content_type=None)
                if commits and isinstance(commits, list):
                    first = commits[0]
                    if not isinstance(first, dict) or "sha" not in first:
                        logger.warning("Unexpected commit object structure, falling back to full fetch")
                        return True, None
                    new_sha = first["sha"]
                    if _last_commit_sha is None:
                        _last_commit_sha = new_sha
                        logger.info("Initial commit SHA: %s", new_sha[:8])
                        try:
                            asyncio.get_running_loop().create_task(_save_commit_state())
                        except RuntimeError:
                            pass
                        return True, None
                    if new_sha != _last_commit_sha:
                        logger.info("New commit detected: %s -> %s", _last_commit_sha[:8], new_sha[:8])
                        return True, new_sha
                    logger.debug("No new commits (SHA: %s)", new_sha[:8])
                    return False, None
            else:
                logger.warning("GitHub Commits API returned %d, falling back to full fetch", resp.status)
                return True, None
    except Exception as e:
        logger.warning("GitHub Commits API check failed: %s, falling back to full fetch", e)
        return True, None
    finally:
        if _owned:
            await _session.close()

    return True, None


def confirm_source_update(sha: str) -> None:
    """Confirm that data from a new commit was successfully fetched and processed."""
    global _last_commit_sha
    _last_commit_sha = sha
    logger.debug("Source update confirmed, SHA: %s", sha[:8])
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_save_commit_state())
    except RuntimeError:
        logger.debug("No running event loop; commit state save skipped")


async def _save_commit_state() -> None:
    """Persist current commit SHA and ETag to database."""
    try:
        from bot.db.queries import set_setting
        from bot.db.session import async_session
        async with async_session() as session:
            if _last_commit_sha:
                await set_setting(session, "last_commit_sha", _last_commit_sha)
            if _last_etag:
                await set_setting(session, "last_commit_etag", _last_etag)
            await session.commit()
    except Exception as e:
        logger.warning("Could not save commit state to DB: %s", e)


async def load_last_commit_sha() -> None:
    """Load last known commit SHA and ETag from database on startup."""
    global _last_commit_sha, _last_etag
    try:
        from bot.db.queries import get_setting
        from bot.db.session import async_session
        async with async_session() as session:
            sha = await get_setting(session, "last_commit_sha")
            etag = await get_setting(session, "last_commit_etag")
        if sha:
            _last_commit_sha = sha
            logger.info("Restored last commit SHA from DB: %s", sha[:8])
        if etag:
            _last_etag = etag
            logger.debug("Restored last ETag from DB")
    except Exception as e:
        logger.warning("Could not load last commit SHA from DB: %s", e)


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
    req_headers: dict[str, str] = {"User-Agent": "SvitloCheck-Bot/4.0"}
    if force_refresh:
        url += f"?_cb={int(time.time() * 1000)}"
        req_headers["Cache-Control"] = "no-cache, no-store"

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
                headers=req_headers,
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


def invalidate_image_cache(region: str, queue: str) -> None:
    """Remove a specific region/queue image from the in-memory cache.

    Call this whenever the schedule for that pair changes so the next
    fetch_schedule_image() call always pulls a fresh image from GitHub.
    """
    cache_key = f"{region}_{queue}"
    if cache_key in _image_cache:
        del _image_cache[cache_key]
        logger.debug("Image cache invalidated for %s/%s", region, queue)


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
                    "Cache-Control": "no-cache",
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
